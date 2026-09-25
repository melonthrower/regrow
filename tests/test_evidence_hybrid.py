import json
from copy import deepcopy
import pytest
from tests.test_evidence_revisit import route_fixture, Driver, NoAgent, png
from tests.test_evidence_explore import reply
from gui_rewalk.src.core.evidence_explore.route import KnownRoute
from gui_rewalk.src.core.evidence_explore.hybrid import HybridRuntime
from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime


def stop_reply():
    r=reply();r['controls']=[];r['regions']=[];r['action']=dict(kind='stop',point=[0,0],direction='',reason='done');return r


def test_hybrid_reuses_store_actions_and_remaining_budget(tmp_path):
    records,images=route_fixture(tmp_path);driver=Driver(images)
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1;context=json.loads(kw['user_prompt'])
            assert context['pending'] is None
            assert context['budget']['actions_remaining']==0
            assert len(kw['screenshots'])==2
            return stop_reply()
    agent=Agent();runtime=HybridRuntime(driver=driver,agent=agent,route=KnownRoute.from_records(records,['a1','a2']),output=tmp_path/'out',goal='inspect arrival',max_calls=1,max_actions=2)
    result=runtime.run()
    assert result['status']=='stopped_by_model' and result['model_calls']==1
    assert result['delivered_actions']==2 and agent.calls==1
    assert len(runtime.store.frames)==5 and len(runtime.store.attempts)==2
    assert (tmp_path/'out/phases/route.json').exists()


def test_failed_route_never_enters_exploration(tmp_path):
    records,images=route_fixture(tmp_path)
    r=HybridRuntime(driver=Driver([png(98),images[1]]),agent=NoAgent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',goal='unused',max_calls=0)
    result=r.run()
    assert result['status']=='call_limit' and not result['exploration_started']


def test_route_consumed_call_budget_does_not_reset_for_exploration(tmp_path):
    records,images=route_fixture(tmp_path)
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1
            return dict(surface='Current',surface_kind='page',surface_box=[0,0,1000,1000],control_box=[100,100,300,300],context_box=[100,100,300,300],point=[200,200],state='enabled',target_found=True,destination_matches=False,reason='Visible')
    a=Agent();r=HybridRuntime(driver=Driver([png(98),images[1]]),agent=a,route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',goal='unused',max_calls=1)
    result=r.run()
    assert a.calls==1 and result['status']=='call_limit_after_route'
    assert not result['exploration_started'] and result['pending'] is None


def test_invalid_inventory_can_settle_valid_receipt_without_dispatch(tmp_path):
    r=EvidenceRuntime(driver=Driver([png(1),png(2)]),agent=None,output=tmp_path/'out',goal='inspect',max_calls=1,separate_receipts=True)
    raw=reply();obs,action=r.store.accept(raw,png(1));a=r.store.plan(action);r.store.delivered(a['ref']);r.actions=1
    bad=reply();bad['receipt']=dict(outcome='changed',intent='met',description='actual result');bad['controls'][0]['context_box']=[20,20,40,40]
    class Agent:
        def _call(self,**kw):return bad
    r.agent=Agent();result=r.run()
    assert result['pending'] is None and not r.driver.executed
    assert r.store.frames[-1]['controls']==[]
    assert r.store.attempts[0]['intent']=='met'
    assert (tmp_path/'out/frames/f2/derivation.json').exists()
    assert json.loads((tmp_path/'out/calls/0001/response.json').read_text())==bad


def test_invalid_receipt_is_not_rescued_by_inventory_quarantine(tmp_path):
    r=EvidenceRuntime(driver=Driver([png(1)]),agent=None,output=tmp_path/'out',goal='inspect',max_calls=1,separate_receipts=True)
    _,action=r.store.accept(reply(),png(1));a=r.store.plan(action);r.store.delivered(a['ref'])
    bad=reply();bad['receipt']=dict(outcome='invented',intent='met',description='bad');bad['controls'][0]['context_box']=[20,20,40,40]
    class Agent:
        def _call(self,**kw):return bad
    r.agent=Agent();result=r.run()
    assert result['pending']=='a1' and len(r.store.frames)==1


def test_region_candidates_keep_identity_unverified_and_no_models(tmp_path):
    from gui_rewalk.src.core.evidence_explore.region_revisit import region_candidates
    records,images=route_fixture(tmp_path);f=records['frames'][0]
    f['controls'].append(dict(f['controls'][0],ref='f1:c1',key='other',box=[600,600,800,800]))
    f['regions']=[dict(ref='f1:r0',name='buttons',parent=-1,control_refs=['f1:c0','f1:c1'])]
    result=region_candidates(f,images[0])
    assert result['input_layer_visual']
    assert result['regions'][0]['match']['accepted']
    assert result['regions'][0]['identity_verified'] is False
    assert not region_candidates(f,png(99))['regions'][0]['match']['accepted']


def test_continued_exploration_checks_scene_after_supervision(tmp_path):
    driver=Driver([png(1),png(2)])
    class Agent:
        def _call(self,**kw):return reply()
    def approve(*_):driver.images[0]=png(99);return True
    r=EvidenceRuntime(driver=driver,agent=Agent(),output=tmp_path/'out',goal='inspect',max_calls=2,
        before_action=approve,verify_before_dispatch=True)
    result=r.run()
    assert result['status']=='changed_before_dispatch' and not driver.executed


def test_optional_region_failure_does_not_authorize_or_block_route(tmp_path,monkeypatch):
    from gui_rewalk.src.core.evidence_explore import region_revisit
    records,images=route_fixture(tmp_path)
    def fail(*_):raise ValueError('malformed optional region')
    monkeypatch.setattr(region_revisit,'region_candidates',fail)
    from gui_rewalk.src.core.evidence_explore.route import RouteRuntime
    r=RouteRuntime(driver=Driver(images),agent=NoAgent(),route=KnownRoute.from_records(records,['a1']),
        output=tmp_path/'out',max_calls=0,record_regions=True)
    result=r.run()
    assert result['status']=='route_complete' and result['delivered_actions']==1
    assert json.loads((tmp_path/'out/region_revisit/f1.json').read_text())['error']=='ValueError'


@pytest.mark.parametrize('action_kind',['click','scroll'])
def test_cli_hybrid_uses_one_ledger_and_transport_budget(tmp_path,monkeypatch,action_kind):
    import sys,types
    from gui_rewalk import run_evidence_explore as cli
    records,images=route_fixture(tmp_path);source=tmp_path/'source.json';source.write_text(json.dumps(records));out=tmp_path/'run'
    class Env:
        def _get_obs(self):return dict(screenshot=images[self._step_no])
    envmod=types.ModuleType('gui_rewalk.env.desktop_gui_gen_env');envmod.DesktopGUIGenEnv=Env
    controller=types.ModuleType('gui_rewalk.env.osworld_reload');controller.PythonController=lambda *a,**kw:None
    monkeypatch.setitem(sys.modules,'gui_rewalk.env.desktop_gui_gen_env',envmod)
    monkeypatch.setitem(sys.modules,'gui_rewalk.env.osworld_reload',controller)
    from gui_rewalk.src.core import app_lifecycle
    from gui_rewalk.src.core.explore import actions,scope
    class Owner:
        def __init__(self,*_):pass
        def bind_active(self,*_):return True
    monkeypatch.setattr(app_lifecycle,'DesktopWindowOwner',Owner)
    monkeypatch.setattr(scope,'ScopeGuard',lambda **_:types.SimpleNamespace(check=lambda:'target'))
    def execute(env,*args,**kw):
        if args[0].kind=='scroll':assert args[0].amount==125
        env._step_no+=1;return dict(screenshot=images[env._step_no])
    monkeypatch.setattr(actions,'execute_action',execute)
    cfg=types.SimpleNamespace(base_url='https://unit.invalid',api_key='unit-secret',timeout_seconds=1)
    monkeypatch.setattr(cli,'load_explore_api_config',lambda _:cfg)
    requests=[]
    def post(url,**kw):
        requests.append(kw['json'])
        report=reply() if len(requests)==1 else stop_reply()
        if len(requests)==1 and action_kind=='scroll':report['action'].update(kind='scroll',point=[500,500],direction='down')
        if len(requests)==2:report['receipt']=dict(outcome='changed',intent='met',description='Observed test transition')
        body=dict(status='completed',model='gpt-5.6-luna',usage=dict(input_tokens=1,output_tokens=1),output=[dict(type='message',phase='final_answer',content=[dict(type='output_text',text=json.dumps(report))])])
        return types.SimpleNamespace(status_code=200,json=lambda:body)
    monkeypatch.setattr(cli.transport.requests,'post',post)
    class Agent:
        model='gpt-5.6-luna';reasoning_effort='medium'
        def __init__(self,**_):pass
        def _call(self,**kw):
            response=cli.transport.requests.post(cfg.base_url+'/responses',json=dict(model=self.model,text={}))
            return json.loads(response.json()['output'][0]['content'][0]['text'])
    monkeypatch.setattr(cli,'OpenAIAPIExplorerAgent',Agent)
    monkeypatch.setattr(sys,'argv',['run','--app','Example','--goal','continue','--server-port','1','--output',str(out),'--known-records',str(source),'--route-attempts','a1','--explore-after-route','--max-calls','2','--max-actions','2'])
    cli.main()
    status=json.loads((out/'status.json').read_text());assert status['mode']=='route_then_explore'
    assert status['model_calls']==2 and status['delivered_actions']==2 and status['pending'] is None
    assert len(requests)==2 and len(json.loads((out/'http.json').read_text()))==2
    assert json.loads((out/'phases/route.json').read_text())['model_calls']==0
    d=json.loads((out/'records.json').read_text());assert [a['ref'] for a in d['attempts']]==['a1','a2']
    assert len(d['frames'])==4 and all(a['status']=='observed' for a in d['attempts'])


def test_partial_fallback_budget_leaves_only_remaining_exploration_calls(tmp_path):
    records,images=route_fixture(tmp_path)
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1
            if kw['role']=='evidence_route_ground':
                return dict(surface='Current',surface_kind='page',surface_box=[0,0,1000,1000],control_box=[100,100,300,300],context_box=[100,100,300,300],point=[200,200],state='enabled',target_found=True,destination_matches=False,reason='Visible')
            r=stop_reply();r['action']['kind']='observe';return r
    a=Agent();runtime=HybridRuntime(driver=Driver([png(98),images[1]]),agent=a,route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',goal='inspect',max_calls=3)
    result=runtime.run()
    assert result['status']=='call_limit' and result['exploration_started']
    assert a.calls==result['model_calls']==3 and result['delivered_actions']==1
    assert sorted(p.name for p in (tmp_path/'out/calls').iterdir())==['0001','0002','0003']
