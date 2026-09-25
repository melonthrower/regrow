"""Optional region-map tool for the new evidence explorer: build, recognize, goto."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from gui_rewalk.src.core.evidence_explore.panorama import RegionPanorama
from gui_rewalk.src.core.evidence_explore.panorama_runtime import PanoramaSession


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['build','recognize','goto'])
    p.add_argument('--output',required=True);p.add_argument('--map')
    p.add_argument('--app');p.add_argument('--server-port',type=int)
    p.add_argument('--region-box',nargs=4,type=int);p.add_argument('--scroll-point',nargs=2,type=int)
    p.add_argument('--park-point',nargs=2,type=int);p.add_argument('--target')
    p.add_argument('--max-scrolls',type=int,default=12)
    p.add_argument('--execute',action='store_true');p.add_argument('--supervised',action='store_true')
    args=p.parse_args()
    if args.mode in {'recognize','goto'} and not args.map:p.error('--map required')
    if args.mode=='build' and not args.region_box:p.error('--region-box required')
    if args.mode=='goto' and not args.target:p.error('--target required')
    if not 1<=args.max_scrolls<=20:p.error('scroll budget must be 1..20')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    for f in Path('gui_rewalk/src/core/evidence_explore').glob('panorama*.py'):(out/f.name).write_bytes(f.read_bytes())
    if args.mode=='recognize':
        from gui_rewalk.src.core.evidence_explore.panorama_perception import recognize
        from gui_rewalk.src.core.evidence_explore.response import final_response_body
        from gui_rewalk.src.core.explore.agent import OpenAIAPIExplorerAgent
        from gui_rewalk.src.core.explore import agent as transport
        from gui_rewalk.src.core.explore.api_config import load_explore_api_config,local_explore_api_config_path
        panorama=RegionPanorama.load(args.map)
        if panorama.controls:raise ValueError('map already has a catalog; do not overwrite control IDs')
        cfg=load_explore_api_config(local_explore_api_config_path())
        agent=OpenAIAPIExplorerAgent(base_url=cfg.base_url,api_key=cfg.api_key,model='gpt-5.6-luna',reasoning_effort='medium',output_root=str(out),timeout=cfg.timeout_seconds)
        native=transport.requests.post;http=[]
        def post(*a,**kw):
            if http:raise RuntimeError('single model request budget; retry disabled')
            kw['json']['text']['verbosity']='low';kw['json']['max_output_tokens']=3500
            row=dict(started=time.time());http.append(row);save('http.json',http)
            try:
                response=native(*a,**kw);body=response.json();row.update(status=response.status_code,usage=body.get('usage'),model=body.get('model'))
                safe=json.dumps(body,ensure_ascii=False).replace(cfg.api_key,'<redacted>').replace(cfg.base_url,'<endpoint>')
                save('transport_response.json',json.loads(safe))
                normalized=final_response_body(body);response.json=lambda:normalized;return response
            finally:row['seconds']=time.time()-row['started'];save('http.json',http)
        transport.requests.post=post
        try:
            reply=recognize(panorama,agent)
            save('result.json',dict(status='recognized',controls=len(reply['controls']),uncertain=reply['uncertain'],new_gui_actions=0))
        except Exception as exc:
            save('result.json',dict(status='unresolved',error=type(exc).__name__,new_gui_actions=0));raise
        finally:transport.requests.post=native
        return
    if not args.app or not args.server_port or not args.scroll_point or not args.park_point:
        p.error('--app, --server-port, --scroll-point and --park-point required for GUI modes')
    from gui_rewalk.env.osworld_reload import PythonController
    c=PythonController('127.0.0.1',server_port=args.server_port)
    region_box=args.region_box if args.mode=='build' else RegionPanorama.load(args.map).region_box
    x,y=args.scroll_point
    if not region_box[0]<x<region_box[2] or not region_box[1]<y<region_box[3]:p.error('scroll point must be inside region')
    if region_box[0]<=args.park_point[0]<=region_box[2] and region_box[1]<=args.park_point[1]<=region_box[3]:p.error('park point must be outside region')
    class Driver:
        def scope_ok(self):
            code="""from Xlib import display
d=display.Display()
try:
 root=d.screen().root;p=root.get_full_property(d.intern_atom('_NET_ACTIVE_WINDOW'),0)
 w=d.create_resource_object('window',int(p.value[0]));print(w.get_wm_class())
finally:d.close()
"""
            r=c.execute_python_command(code)
            return r.get('returncode')==0 and args.app.lower() in r.get('output','').lower()
        def capture(self):
            r=c.execute_python_command(f'import pyautogui,time\npyautogui.moveTo({args.park_point[0]},{args.park_point[1]})\ntime.sleep(.2)')
            if r.get('returncode')!=0:raise RuntimeError('cursor preparation failed')
            return c.get_screenshot()
        def scroll(self,direction):
            r=c.execute_python_command(f'import pyautogui,time\npyautogui.moveTo({x},{y})\npyautogui.scroll({2 if direction=="up" else -2})\ntime.sleep(.5)')
            if r.get('returncode')!=0:raise RuntimeError('scroll delivery unknown')
        def click(self,point):
            r=c.execute_python_command(f'import pyautogui,time\npyautogui.click({point[0]},{point[1]})\ntime.sleep(.5)')
            if r.get('returncode')!=0:raise RuntimeError('click delivery unknown')
    def approve(plan,source):
        if not args.supervised:return True
        save('click_proposal.json',dict(plan=plan,source=source))
        print('CLICK_REVIEW',json.dumps(plan),flush=True)
        while not (out/'approved').exists():
            if (out/'STOP').exists():return False
            time.sleep(.2)
        return not (out/'STOP').exists()
    session=PanoramaSession(Driver(),out,region_box,args.max_scrolls,before_click=approve)
    if args.mode=='goto':session.map=RegionPanorama.load(args.map)
    save('condition.json',dict(mode=args.mode,app=args.app,region_box=region_box,scroll_point=args.scroll_point,park_point=args.park_point,
        map=args.map,target=args.target,execute=args.execute,supervised=args.supervised,scope='caller must supply a currently active, unobscured, fixed-geometry region'))
    try:
        if args.mode=='build':
            m=session.build();result=dict(kind='built',coverage=m.coverage,shape=list(m.image.shape))
        else:result=session.goto(args.target,max_steps=min(8,args.max_scrolls+1),execute=args.execute)
        save('result.json',dict(result=result,scrolls=session.scrolls,clicks=session.clicks,new_model_calls=0))
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as exc:
        save('result.json',dict(result={'kind':'unresolved','reason':str(exc)},scrolls=session.scrolls,clicks=session.clicks,new_model_calls=0))
        raise


if __name__=='__main__':main()
