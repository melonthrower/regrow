"""Standalone desktop evidence-first explorer; existing traversal is not modified."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from PIL import Image
import io
from gui_rewalk.src.core.explore.agent import OpenAIAPIExplorerAgent
from gui_rewalk.src.core.explore import agent as transport
from gui_rewalk.src.core.explore.api_config import load_explore_api_config,local_explore_api_config_path
from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
from gui_rewalk.src.core.evidence_explore.hybrid import HybridRuntime
from gui_rewalk.src.core.evidence_explore.protocol import PROMPT
from gui_rewalk.src.core.evidence_explore.route import KnownRoute,RouteRuntime
from gui_rewalk.src.core.evidence_explore.response import final_response_body


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',required=True);p.add_argument('--goal',required=True)
    p.add_argument('--server-port',type=int,required=True);p.add_argument('--output',required=True)
    p.add_argument('--max-calls',type=int,default=16);p.add_argument('--max-actions',type=int,default=12)
    p.add_argument('--repaint-active',action='store_true');p.add_argument('--supervised',action='store_true')
    p.add_argument('--known-records',help='Existing evidence records for explicitly selected navigation replay')
    p.add_argument('--route-attempts',help='Comma-separated observed navigation attempts in execution order')
    p.add_argument('--explore-after-route',action='store_true',help='Continue exploration after the explicit route, sharing call/action budgets and evidence')
    p.add_argument('--review-inventory',action='store_true',help='Audit new visible inventories and post-scroll value changes using the shared model budget')
    args=p.parse_args()
    if args.review_inventory and args.known_records and not args.explore_after_route:p.error('--review-inventory requires exploration; add --explore-after-route')
    if args.explore_after_route and not args.known_records:p.error('--explore-after-route requires --known-records and --route-attempts')
    if bool(args.known_records)!=bool(args.route_attempts):p.error('--known-records and --route-attempts are required together')
    route=(KnownRoute.from_records(json.loads(Path(args.known_records).read_text()),args.route_attempts.split(',')) if args.known_records else None)
    if not (0 if route else 1)<=args.max_calls<=16 or not 0<=args.max_actions<=12:p.error('prototype budget: calls 1..16 (known route permits 0); actions 0..12')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
    from gui_rewalk.env.osworld_reload import PythonController
    from gui_rewalk.src.core.app_lifecycle import DesktopWindowOwner
    from gui_rewalk.src.core.explore.actions import execute_action
    from gui_rewalk.src.core.explore.contracts import ActionRequest
    class Attached(DesktopGUIGenEnv):
        def __init__(self):
            self.controller=PythonController('127.0.0.1',server_port=args.server_port)
            self.require_terminal=False;self.action_space='gen_data';self._step_no=0;self.is_environment_used=False
        def _get_obs(self):
            if args.repaint_active:
                code="""from Xlib import display
import time
d=display.Display()
try:
 root=d.screen().root
 prop=root.get_full_property(d.intern_atom('_NET_ACTIVE_WINDOW'),0)
 if prop is None or not prop.value[0]:raise RuntimeError('No active client')
 w=d.create_resource_object('window',int(prop.value[0]));w.clear_area(exposures=True);d.sync()
finally:d.close()
time.sleep(.5)
"""
                receipt=self.controller.execute_python_command(code)
                if not receipt or receipt.get('returncode')!=0:raise RuntimeError('active repaint failed')
            return super()._get_obs()
        def close(self):pass
    env=Attached();owner=DesktopWindowOwner(env)
    if not owner.bind_active(args.app):raise RuntimeError('target app is not active')
    class Driver:
        def scope_ok(self):
            from gui_rewalk.src.core.explore.scope import ScopeGuard
            return ScopeGuard(env=env,app_name=args.app,platform='desktop',desktop_window_owner=owner).check()=='target'
        def observe(self):return env._get_obs()['screenshot']
        def execute(self,action):
            a=ActionRequest(kind=action['kind'],purpose='recover',target=action['reason'],
                point_1000=action['point'] if action['kind'] in {'click','scroll'} else None,
                text='',direction=action['direction'],amount=125 if action['kind']=='scroll' else 500,operation_ref='',owner_ref='')
            frame=Path(runtime.store.frames[-1]['image']).read_bytes();primitives=[]
            result=execute_action(env,a,screenshot=frame,platform='desktop',pause=1,executed_actions=primitives)
            runtime.store.write(f'actions/{runtime.store.attempts[-1]["ref"]}/controller.json',dict(primitives=primitives,action_error=result.get('action_error','')))
            if result.get('screenshot'):(out/'actions'/runtime.store.attempts[-1]['ref']/'after_delivery.png').write_bytes(result['screenshot'])
            return result
    cfg=load_explore_api_config(local_explore_api_config_path())
    agent=OpenAIAPIExplorerAgent(base_url=cfg.base_url,api_key=cfg.api_key,model='gpt-5.6-luna',reasoning_effort='medium',output_root=str(out),timeout=cfg.timeout_seconds)
    def approve(attempt,observation):
        if not args.supervised:return True
        folder=out/'actions'/attempt['ref']
        print('ACTION_REVIEW',attempt['ref'],attempt['action']['kind'],attempt['action']['reason'],flush=True)
        while not (folder/'approved').exists():
            if (out/'STOP').exists():return False
            time.sleep(.2)
        return not (out/'STOP').exists()
    if args.explore_after_route:
        runtime=HybridRuntime(driver=Driver(),agent=agent,route=route,output=out,goal=args.goal,
            max_calls=args.max_calls,max_actions=args.max_actions,before_action=approve,review_inventory=args.review_inventory)
    elif route:
        runtime=RouteRuntime(driver=Driver(),agent=agent,route=route,output=out,
            max_calls=args.max_calls,max_actions=args.max_actions,before_action=approve)
    else:
        runtime=EvidenceRuntime(driver=Driver(),agent=agent,output=out,goal=args.goal,
            max_calls=args.max_calls,max_actions=args.max_actions,before_action=approve,review_inventory=args.review_inventory)
    native=transport.requests.post;http=[];native_call=agent._call
    def call(**kwargs):
        used=False
        def post(*a,**kw):
            nonlocal used
            if a[0]!=cfg.base_url.rstrip('/')+'/responses':return native(*a,**kw)
            if used or len(http)>=args.max_calls:raise RuntimeError('model HTTP budget/retry rejected')
            if kw['json']['model']!='gpt-5.6-luna':raise RuntimeError('model upgrade rejected')
            used=True;kw['json']['max_output_tokens']=6500
            kw['json']['text']['verbosity']='low'
            row=dict(call=runtime.calls,started=time.time());http.append(row);runtime.store.write('http.json',http)
            try:
                response=native(*a,**kw);body=response.json();row.update(status=response.status_code,usage=body.get('usage'),model=body.get('model'))
                safe=json.dumps(body,ensure_ascii=False).replace(cfg.api_key,'<redacted>') if cfg.api_key else json.dumps(body,ensure_ascii=False)
                safe=safe.replace(cfg.base_url,'<endpoint>')
                runtime.store.write(f'calls/{runtime.calls:04d}/transport_response.json',json.loads(safe))
                if 200 <= response.status_code < 300:
                    selected=final_response_body(body)
                    runtime.store.write(f'calls/{runtime.calls:04d}/response_selection.json',dict(
                        phase='final_answer_or_single_unphased',original_messages=sum(
                            item.get('type')=='message' for item in body.get('output',[]))))
                    response.json=lambda: selected
                return response
            finally:row['seconds']=time.time()-row['started'];runtime.store.write('http.json',http)
        transport.requests.post=post
        try:return native_call(**kwargs)
        except Exception as exc:
            message=str(exc).replace(cfg.api_key,'<redacted>') if cfg.api_key else str(exc)
            runtime.store.write(f'calls/{runtime.calls:04d}/transport_error.json',dict(type=type(exc).__name__,message=message.replace(cfg.base_url,'<endpoint>')))
            raise
        finally:transport.requests.post=native
    agent._call=call
    runtime.store.write('condition.json',dict(app=args.app,goal=args.goal,max_calls=args.max_calls,max_actions=args.max_actions,
        mode='route_then_explore' if args.explore_after_route else ('known_route' if route else 'explore'),route_attempts=args.route_attempts,model=agent.model,reasoning_effort=agent.reasoning_effort,supervised=args.supervised,review_inventory=args.review_inventory,repaint_active=args.repaint_active,
        source_hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('gui_rewalk/src/core/evidence_explore').glob('*.py')}))
    for f in Path('gui_rewalk/src/core/evidence_explore').glob('*.py'):(out/f.name).write_bytes(f.read_bytes())
    result=runtime.run();(out/'final.png').write_bytes(env._get_obs()['screenshot'])
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
