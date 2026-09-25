from copy import deepcopy
import json
import pytest
from tests.test_stepwise_task_correction import saved,repair,Calls,answer
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def setup(tmp_path):
    run,q,good=saved(tmp_path);d=tasks().helper('discovery_step')
    def seed(records,state,snapshot,temp):
        tasks().apply_plan(records['r1'],good,'seed')
        state['observation']['control_refs']=['c1','c2'];state.pop('exception',None)
        state['observation']['foreground']={'exception':'none'}
    d.publish(run,'seed-tasks',seed)
    q['source'].update(task_name='Policy',task_region='r1')
    return run,q,d


def test_model_defer_blocks_only_bound_task_and_continues_local(tmp_path):
    run,q,d=setup(tmp_path);m=repair()
    calls=Calls(run,[{},answer('defer')])
    with pytest.raises(m.Paused) as e:m.Runner(ROOT,run,calls,None,lambda:6).perform('action',q)
    assert e.value.status=='task_deferred' and m.pending(run) is None
    _,records,state=d.load(run);r=records['r1']
    assert r['tasks']['Policy']['handling']=='explore' and r['tasks']['Policy']['status']=='blocked'
    assert r['tasks']['Settings']['status']=='pending' and not tasks().coverage(r)['complete']
    assert r['tasks']['Policy']['deferral']['reason']
    req=tasks().helper('stepwise_flow').assemble_current_context(ROOT,run)
    assert req['source']['task_name']=='Settings'


def test_limit_uses_same_defer_without_extra_model_call(tmp_path):
    run,q,d=setup(tmp_path);m=repair();calls=Calls(run,[{}, {}, {}])
    with pytest.raises(m.Paused) as e:m.Runner(ROOT,run,calls,None,lambda:6).perform('action',q)
    assert e.value.status=='task_deferred' and len(calls.requests)==3
    assert d.load(run)[1]['r1']['tasks']['Policy']['status']=='blocked'


def test_unbound_proposal_keeps_gap_without_inventing_control(tmp_path):
    run,q,d=setup(tmp_path);q['source'].pop('task_name');q['source'].pop('task_region');m=repair()
    calls=Calls(run,[{},answer('defer')]);before=deepcopy(d.load(run)[1]['r1']['controls'])
    with pytest.raises(m.Paused) as e:m.Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert e.value.status=='task_deferred'
    r=d.load(run)[1]['r1'];assert r['controls']==before and 'task_proposal' in r['registration_gaps']
    assert all(t['status']=='pending' for t in r['tasks'].values())


def test_no_independent_task_pauses_but_never_claims_complete(tmp_path):
    run,q,d=setup(tmp_path)
    d.publish(run,'other-completed',lambda r,s,*a:r['r1']['tasks']['Settings'].update(status='done'))
    m=repair();calls=Calls(run,[{},answer('defer')])
    with pytest.raises(m.Paused) as e:m.Runner(ROOT,run,calls,None,lambda:6).perform('action',q)
    assert e.value.status=='task_blocked' and m.pending(run) is None
    assert not tasks().coverage(d.load(run)[1]['r1'])['complete']


@pytest.mark.parametrize('condition',['update','unobserved','execution','pre_dispatch'])
def test_uncertain_or_executed_step_cannot_release_scheduler(tmp_path,condition):
    run,q,d=setup(tmp_path);job={'stage':'action','request':q,'path':'repair_episodes/test/episode.json','call':'test'}
    if condition=='update':job.update(stage='update',attempt='a2')
    if condition=='unobserved':q['source']['observation']='stale'
    if condition=='execution':(run/'execution_pending.json').write_text('{}')
    if condition=='pre_dispatch':job['requires_observation']=True
    before=(run/'knowledge_current.json').read_bytes()
    assert tasks().helper('task_deferral').defer(run,job,'缺少证据') is None
    assert (run/'knowledge_current.json').read_bytes()==before


def test_deferred_task_needs_new_crop_to_resume(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('task_deferral')
    q['needs_task_inspection']=True
    m.defer(run,{'stage':'action','request':q,'path':'repair_episodes/test/episode.json','call':'test'},'无法定位')
    _,records,state=d.load(run);m.resume_localized(records,['r1'],'fresh')
    assert records['r1']['tasks']['Policy']['status']=='blocked'
    records['r1']['controls']['c1']['observations'].append({'image':'fresh.png','evidence':{'source_call':'fresh'}})
    m.resume_localized(records,['r1'],'fresh')
    assert records['r1']['tasks']['Policy']['status']=='pending'
    assert records['r1']['tasks']['Policy']['deferral']['resumed_by']=='fresh'


def test_local_before_remote_and_no_invented_reverse_route():
    from tests.test_stepwise_resume_route import fixture
    flow,r,s=fixture();m=tasks().helper('task_deferral');s['interactive_regions']=['main'];s['observation']['control_refs']=['open']
    for rid in r:
        r[rid]['tasks']={'go':{'handling':'explore','status':'pending','control':'open'}}
        r[rid]['controls']['open']['observations']=[{'image':'crop.png','evidence':{'observation':s['observation']['id']}}]
    assert m.choose(r,s)['region']=='main'
    r['main']['tasks']['go']['status']='done';assert m.choose(r,s)['region']=='middle'
    s['interactive_regions']=['menu'];r['menu']['tasks']['go']['status']='done'
    assert m.choose(r,s)['region']=='middle'  # Unknown routes are offered to normal navigation.


def test_registration_gap_prevents_false_completion_and_reproposal(tmp_path):
    run,q,d=setup(tmp_path);q['source'].pop('task_name');q['source'].pop('task_region');m=repair()
    with pytest.raises(m.Paused):m.Runner(ROOT,run,Calls(run,[{},answer('defer')]),None,lambda:6).perform('task_proposal',q)
    region=d.load(run)[1]['r1'];assert not tasks().coverage(region)['inventory_complete']
    req=tasks().helper('stepwise_flow').assemble_current_context(ROOT,run)
    assert req['stage']!='task_proposal' and req['source']['task_name']=='Policy'
    for t in region['tasks'].values():t['status']='done'
    assert not tasks().coverage(region)['complete']


def test_unlocated_failure_calls_correction_before_deferring(tmp_path):
    run,q,d=setup(tmp_path);m=repair()
    calls=Calls(run,[answer('defer')])
    runner=m.Runner(ROOT,run,calls,None,lambda:6)
    with pytest.raises(m.Paused) as e:runner.repair_unlocated(q,'定位失败')
    assert e.value.status=='task_deferred'
    assert len(calls.requests)==1 and calls.requests[0]['role']=='step_correction'
    assert d.load(run)[1]['r1']['tasks']['Settings']['status']=='pending'


def test_blocked_task_does_not_hide_independent_task_but_route_still_needs_evidence():
    from tests.test_stepwise_resume_route import fixture
    flow,r,s=fixture();m=tasks().helper('task_deferral');s['interactive_regions']=['main'];s['observation']['control_refs']=['open']
    r['main']['tasks']={'bad':{'status':'blocked','handling':'explore','control':'open'},'alias':{'status':'pending','handling':'explore','control':'open'}}
    r['middle']['tasks']={'next':{'status':'pending','handling':'explore','control':'open'}}
    assert m.choose(r,s)['task']=='alias'
    assert flow.shortest_known_path(r,s,'middle') is None


def test_remote_fallback_uses_existing_edge_and_preserves_old_gap(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,snapshot,temp):
        r=records['r1'];r['tasks']['Settings']['status']='done'
        other=tasks().helper('stepwise_flow').new_region('r2','Other','other region')
        other['controls']['c3']=deepcopy(r['controls']['c2']);other['controls']['c3']['action_refs']=[]
        other['tasks']={'target':{**deepcopy(r['tasks']['Settings']),'control':'c3','status':'pending'}}
        other['task_inventory']={'inventory':'complete','controls':['c3']};records['r2']=other
        r['controls']['c2']['observations'].append({'image':'crop.png','icon_description':'按钮','evidence':{'observation':state['observation']['id']}})
        r['actions']['route']={'control':'c2','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}
        r['transitions'].append({'source_control':'c2','target_region':'r2','attempt':'route'})
    d.publish(run,'remote-seed',seed)
    decision=tasks().helper('task_deferral').defer(run,{'stage':'action','request':q,'path':'repair_episodes/remote/episode.json'},'无法绑定')
    assert decision['next']['region']=='r2'
    _,records,state=d.load(run)
    assert state['working_region']=='r2' and state['deferred_routing_target']=='r2'
    assert records['r1']['tasks']['Policy']['status']=='blocked'
    request=tasks().helper('stepwise_flow').assemble_current_context(ROOT,run)
    assert request['navigation_path'][0]['source_control']=='c2'


def test_auto_session_continues_after_deferral(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_progress_session
    calls=[]
    def step(root,run,out):
        out.mkdir();calls.append(out)
        (out/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':0}))
        (out/'result.json').write_text(json.dumps({'status':'task_deferred' if len(calls)==1 else 'task_blocked'}))
    result=run_progress_session.run_session(ROOT,tmp_path,tmp_path/'session','auto',step=step)
    assert len(calls)==2 and result['last_result']=='task_blocked'


def test_targeted_inspection_ignores_exhausted_scan_cursor(tmp_path):
    run,q,d=setup(tmp_path)
    _,records,state=d.load(run)
    state['control_scan']={'r1':99}
    d.focus_task(records,state,q)
    assert state['required_control']=='c1'
    assert state['inspection_region']=='r1'
    assert 'Policy' in state['correction_context']
    assert state['control_scan']['r1']==99  # targeted lookup overrides cursor, not global reset


def test_unlocated_request_explains_observation_prerequisite(tmp_path):
    run,q,d=setup(tmp_path);q['needs_task_inspection']=True
    m=repair();calls=Calls(run,[answer('defer')])
    with pytest.raises(m.Paused):m.Runner(ROOT,run,calls,None,lambda:6).repair_unlocated(q,'未定位')
    dynamic=json.loads(calls.requests[0]['user_prompt'])
    assert 'observe' in dynamic['当前前置缺口']
    assert dynamic['原任务']=='Policy'


def test_localization_observation_returns_to_normal_action_selection(tmp_path,monkeypatch):
    run,q,d=setup(tmp_path);q['needs_task_inspection']=True
    m=repair();calls=Calls(run,[answer('observe'),{}]);runner=m.Runner(ROOT,run,calls,None,lambda:6)
    def observed(runner,job):
        job['request'].pop('needs_task_inspection')
        job['request']['action_ready']=True
        job['observations']+=1
    monkeypatch.setattr(runner.adapters,'observe',observed)
    monkeypatch.setattr(runner.adapters,'accept',lambda *args:{'accepted':True})
    result=runner.repair_unlocated(q,'未定位')
    assert result['repairs']==1 and result['observations']==1
    assert len(calls.requests)==2 and calls.requests[1].get('role')!='step_correction'


def test_action_refresh_preserves_current_observation_image(tmp_path,monkeypatch):
    run,q,d=setup(tmp_path);m=tasks().helper('repair_stages')
    import types
    state={'observation':{'image':'fresh-observation.png'}}
    refreshed={'source':q['source'],'action_ready':True}
    helper=m.helper
    monkeypatch.setattr(m,'helper',lambda name:types.SimpleNamespace(load=lambda run:(None,{},state)) if name=='discovery_step' else types.SimpleNamespace(assemble_current_context=lambda *a:refreshed) if name=='stepwise_flow' else helper(name))
    actual=m.refresh(ROOT,run,{'stage':'action','request':q})
    assert actual['screenshots']==actual['image_refs']==['fresh-observation.png']
