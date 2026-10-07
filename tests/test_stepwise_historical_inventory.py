from copy import deepcopy
from tests.test_stepwise_region_tasks import tasks, ROOT, fixture
from tests.test_recovery_discovery import mod


def test_parameter_continuation_can_advance_before_inventory_completion():
    flow,records,state=fixture();m=tasks()
    state['interactive_regions']=['middle'];state['active_task']={'region':'menu','name':'配置'}
    records['menu']['tasks']={'配置':{'status':'pending','task_type':'parameter','control':'open','handling':'explore','action':'click','reason':'test'}}
    q=m.attach(ROOT,records,state,'menu',flow.assemble_context(ROOT,records,state,'menu'))
    assert q['stage']=='action_selection'
    assert q['source']['region']=='middle'
    assert q['source']['task_region']=='menu'


def test_historical_plan_uses_saved_frame_and_does_not_change_current(tmp_path):
    m=mod('historical_inventory');_,records,state=fixture();rid='menu'
    frame=tmp_path/'frame.png';frame.write_bytes(b'image')
    records[rid]['observations']=[{'source_image':str(frame),'controls_complete':True,'evidence':{'observation':'old'}}]
    records[rid]['actions']['prior']={'result':{'description':'closed'}}
    state['working_region']=rid;state['interactive_regions']=['middle']
    before=deepcopy(state)
    q=m.request(ROOT,tmp_path,records,state)
    assert q['screenshots']==[str(frame)]
    assert q['historical_inventory']['evidence_digest']==m.digest(records[rid])
    assert '历史截图' in q['user_prompt']
    assert state==before
    records[rid]['task_inventory']={'inventory':'partial'}
    assert m.request(ROOT,tmp_path,records,state) is None


def test_historical_validation_rejects_changed_record():
    import pytest
    m=mod('historical_inventory');region={'description':'observed'}
    q={'historical_inventory':{'evidence_digest':m.digest(region)}}
    m.validate(region,q)
    region['description']='changed'
    with pytest.raises(ValueError,match='记录已变化'):m.validate(region,q)


def test_historical_commit_does_not_require_current_observation(tmp_path):
    import json
    from tests.test_stepwise_task_correction import saved,Calls
    run,q,reply=saved(tmp_path);d=mod('discovery_step');m=mod('historical_inventory')
    snapshot,records,state=d.load(run)
    state['observation']=None;state['interactive_regions']=[]
    (snapshot/'runtime_state.json').write_text(json.dumps(state))
    q['historical_inventory']={'evidence_digest':m.digest(records[q['source']['region']])}
    ref,_=Calls(run,[reply])(q)
    tasks().commit_plan(ROOT,run,ref)
    _,registered,after=d.load(run)
    assert registered[q['source']['region']]['task_inventory']['inventory']=='complete'
    assert after['observation'] is None and after['interactive_regions']==[]


def test_complete_saved_region_needs_no_prior_action_to_plan(tmp_path):
    m=mod('historical_inventory');_,records,state=fixture();rid='menu'
    frame=tmp_path/'frame.png';frame.write_bytes(b'image')
    records[rid]['actions']={}
    records[rid]['observations']=[{'source_image':str(frame),'controls_complete':True,'evidence':{'observation':'old'}}]
    state['working_region']=rid;state['interactive_regions']=['middle']
    before=deepcopy(state)
    q=m.request(ROOT,tmp_path,records,state)
    assert q is not None and q['stage']=='task_proposal'
    assert q['screenshots']==[str(frame)] and state==before
    records[rid]['observations'][0]['controls_complete']=False
    assert m.request(ROOT,tmp_path,records,state) is None


def test_completed_nonworking_region_gets_function_review_without_navigation(tmp_path):
    from tests.test_stepwise_region_tasks import proposal, row
    m=mod('historical_inventory');_,records,state=fixture()
    tasks().apply_plan(records['menu'],proposal([row(handling='record')]),'plan')
    state['working_region']='middle';state['interactive_regions']=['middle']
    before=deepcopy(state)
    q=m.request(ROOT,tmp_path,records,state)
    assert q and q['stage']=='function_registration'
    assert q['source']['region']=='menu' and state==before
    fn=mod('region_functions')
    fn.register(records['menu'],{'parameter_definitions':[],'local_knowledge':{'summary':'本地用途测试记录','parameter_refs':[],'conditions':[],'unconfirmed':[]},'region_role':'navigation','role_evidence':'导航','functions':[],'evidence':'仅导航'},'review',records)
    assert m.request(ROOT,tmp_path,records,state) is None


def test_function_backfill_does_not_retry_deferred_registration(tmp_path):
    from tests.test_stepwise_region_tasks import proposal, row
    m=mod('historical_inventory');_,records,state=fixture()
    tasks().apply_plan(records['menu'],proposal([row(handling='record')]),'plan')
    records['menu']['registration_gaps']={'function_registration':{'reason':'failed'}}
    state['working_region']='middle';state['interactive_regions']=['middle']
    assert m.request(ROOT,tmp_path,records,state) is None


def test_function_backfill_preserves_unfinished_active_task_without_current_frame(tmp_path):
    from tests.test_stepwise_region_tasks import proposal, row
    m=mod('historical_inventory');_,records,state=fixture()
    tasks().apply_plan(records['menu'],proposal([row(handling='record')]),'plan')
    state.update(working_region='middle',observation=None,active_task={'region':'middle','name':'search'})
    before=deepcopy(state)
    q=m.request(ROOT,tmp_path,records,state)
    assert q['stage']=='function_registration' and q['source']['observation'] is None
    assert state==before


def test_multiple_function_reviews_continue_as_next_round(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ROOT))
    import run_task_step as runner
    run=tmp_path/'run';run.mkdir()
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'test.app'}))
    (run/'knowledge_current.json').write_text('{}')
    monkeypatch.setattr(runner,'foreground_window',lambda *a:None)
    monkeypatch.setattr(runner.RecoveryRun,'screenshot',lambda self,p:p.write_bytes(b'frame'))
    monkeypatch.setattr(runner.discovery_step,'load',lambda r:(None,{}, {'next_action_mode':'explore'}))
    monkeypatch.setattr(runner.Locator,'locate_control',lambda *a:False)
    monkeypatch.setattr(runner.exploration_loop,'observe',lambda *a:None)
    monkeypatch.setattr(runner.step_repair,'pending',lambda r:None)
    monkeypatch.setattr(runner.step_repair,'reopen_blocked',lambda *a:None)
    original_helper=runner.step_repair.helper
    monkeypatch.setattr(runner.step_repair,'helper',lambda name:SimpleNamespace(run_pending=lambda *a:None) if name=='shared_control_review' else original_helper(name))
    monkeypatch.setattr(runner.visual_backtrack,'resume_pending',lambda *a:None)
    q={'stage':'function_registration','action_ready':False,'source':{'region':'finished'}}
    monkeypatch.setattr(runner.Scheduler,'current',lambda *a:q)
    calls=[]
    monkeypatch.setattr(runner.step_repair,'Runner',lambda *a,**kw:SimpleNamespace(perform=lambda *a:calls.append(a)))
    runner._run_step(ROOT,run,tmp_path/'round')
    result=json.loads((tmp_path/'round/result.json').read_text())
    assert result['status']=='ready_next_round' and result['gui_actions']==0
    assert len(calls)==1 and calls[0][0]=='function_registration'


def test_historical_merge_and_plan_refresh_in_one_transaction(tmp_path):
    from tests.test_stepwise_task_correction import saved,Calls,answer,repair
    run,q,good=saved(tmp_path);d=mod('discovery_step');h=mod('historical_inventory')
    for row in good['operations']:row['registration_kind']='control_effect'
    def duplicate(records,state,*args):
        r=records['r1'];cid=next(iter(r['controls']));r['controls']['duplicate']=deepcopy(r['controls'][cid]);r['controls']['duplicate']['id']='duplicate'
        state['interactive_regions']=[]
    d.publish(run,'duplicate',duplicate)
    _,records,_=d.load(run);r=records['r1'];name=next(iter(r['controls'].values()))['name']
    q['historical_inventory']={'evidence_digest':h.digest(r)}
    calls=Calls(run,[good,answer('revise',good,{'region':r['name'],'control':name,'field':'merge_into','before':name,'after':name,'evidence':'same physical entry in duplicate records'})])
    job=repair().Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert job['status']=='complete'
    registered=d.load(run)[1]['r1']
    assert 'duplicate' not in registered['controls']
    assert registered['task_inventory']['inventory']=='complete'
