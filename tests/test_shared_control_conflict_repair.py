"""Local guards; acceptance additionally replays real framework requests and Luna."""
import json
from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod, ROOT
from tests.test_stepwise_shared_controls import records, action


def test_historical_dispatch_recovers_actual_click_without_guessing_owner(tmp_path):
    r=records();r['five']['actions']['a']=action();r['five']['actions']['a']['operation']=None
    p=tmp_path/'action_attempts/a';p.mkdir(parents=True)
    (p/'dispatch.json').write_text(json.dumps({'source_region':'five','source_control':'c','action':{'action':'click'}}))
    mod('stepwise_flow').resolve_action_operations(r,tmp_path)
    assert r['five']['actions']['a']['operation']=='click'
    r['eight']['actions']['a']=deepcopy(r['five']['actions']['a']);r['eight']['actions']['a']['operation']=None
    mod('stepwise_flow').resolve_action_operations(r,tmp_path)
    assert r['eight']['actions']['a']['operation'] is None


def conflicting():
    r=records();r['five']['actions']['a']=action('world');r['eight']['actions']['b']=action('timer')
    for rid in r:r[rid].update(description=rid,observations=[],transitions=[])
    r['five']['tasks']={'open world':{'control':'c','status':'done','handling':'explore','action':'click','task_type':'single_action','reason':'open world','attempts':['a']}}
    r['eight']['tasks']={}
    mod('shared_controls').link(r,'plus',[('five','c'),('eight','c')],'same button',[{'region':'five','attempt':'a'}])
    return r


def test_detach_preserves_actual_actions_and_removes_wrong_unexecuted_projection():
    m=mod('shared_control_review');r=conflicting();s={};before=deepcopy(r)
    case=m.conflicts(r)[0]
    m.apply(r,s,case,{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'World versus Timer results'},'test')
    assert not r['eight']['controls']['c'].get('shared_control_ref')
    assert not m.conflicts(r)
    assert r['five']['actions']==before['five']['actions'] and r['eight']['actions']==before['eight']['actions']
    assert r['five']['tasks']['open world']['status']=='done'


def test_confirmation_applies_only_to_reviewed_evidence():
    m=mod('shared_control_review');r=conflicting();case=m.conflicts(r)[0]
    m.apply(r,{},case,{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'shared','evidence':'different data, same function'},'test')
    mod('shared_controls').refresh(r);assert not m.conflicts(r)
    r['eight']['actions']['b']['result']['description']='new contradictory observation'
    mod('shared_controls').refresh(r);assert m.conflicts(r)


def test_unchanged_evidence_detach_does_not_touch_another_conflict():
    m=mod('shared_control_review');r=conflicting()
    unrelated=deepcopy(r['eight']);unrelated['id']='unrelated'
    unrelated['tasks']={'old':{'control':'c','status':'blocked','shared_task_ref':{'region':'missing','task':'old','control':'c'},'shared_task_active':False}}
    unrelated['controls']['c'].pop('shared_control_ref',None);r['unrelated']=unrelated
    expected=deepcopy(unrelated['tasks'])
    m.apply(r,{},m.conflicts(r)[0],{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'different effect'},'test')
    assert r['unrelated']['tasks']==expected


def test_stale_correction_cannot_change_newer_results():
    m=mod('shared_control_review');r=conflicting();case=m.conflicts(r)[0]
    r['eight']['actions']['b']['result']['description']='new observation'
    mod('shared_controls').refresh(r);before=deepcopy(r)
    with pytest.raises(ValueError,match='证据已变化'):
        m.apply(r,{},case,{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'old evidence'},'test')
    assert r==before


def test_detach_archives_wrong_inherited_task_but_keeps_local_attempts():
    m=mod('shared_control_review');r=conflicting()
    # Projection was created earlier, before the conflicting action was observed.
    old=r['eight']['actions'].pop('b');mod('shared_controls').refresh(r)
    assert r['eight']['tasks']['open world']['status']=='record_only'
    r['eight']['actions']['b']=old;mod('shared_controls').refresh(r)
    before=deepcopy(r['eight']['actions'])
    m.apply(r,{},m.conflicts(r)[0],{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'different effect'},'test')
    assert 'open world' not in r['eight']['tasks']
    assert r['eight']['controls']['c']['shared_task_history'][0]['name']=='open world'
    assert r['eight']['actions']==before
    assert r['eight']['task_inventory']['review']


def test_normal_action_boundary_repairs_before_requesting_an_action(tmp_path):
    from tests.test_stepwise_task_correction import Calls
    import step_repair
    r=conflicting();run=tmp_path/'run';snapshot=run/'knowledge_snapshots/start'
    for rid,record in r.items():
        p=snapshot/'regions'/rid/'region.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(record))
    (snapshot/'runtime_state.json').write_text(json.dumps({'working_region':'eight'}))
    (run/'knowledge_current.json').write_text(json.dumps({'snapshot':'knowledge_snapshots/start'}))
    reply={'blocked_by':'none','reason':'两处实际功能不同，解除共享','resolution':'edit_record','proposal':None,
           'record_edit':{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'World versus Timer'}}
    calls=Calls(run,[reply]);runner=step_repair.Runner(ROOT,run,calls,None,lambda:3)
    with pytest.raises(step_repair.Paused) as error:runner.perform('action',{'role':'action_selection'})
    assert error.value.status=='ready_next_round'
    assert len(calls.requests)==1 and calls.requests[0]['role']=='step_correction'
    assert not step_repair.pending(run)
    assert not mod('shared_control_review').conflicts(mod('discovery_step').load(run)[1])
    assert not list(run.glob('action_attempts/*'))


def test_missing_member_can_be_detached_without_losing_survivor():
    m=mod('shared_control_review');r=conflicting();del r['five']['controls']['c'];mod('shared_controls').refresh(r)
    m.apply(r,{},m.conflicts(r)[0],{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'source missing'},'test')
    assert not r['eight']['controls']['c'].get('shared_control_ref')
    assert not m.conflicts(r)


def test_broken_member_reference_cannot_be_confirmed_as_repaired():
    m=mod('shared_control_review');r=conflicting();r['eight']['controls']['c'].pop('shared_control_ref');mod('shared_controls').refresh(r)
    with pytest.raises(ValueError,match='引用断开'):
        m.apply(r,{},m.conflicts(r)[0],{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'shared','evidence':'same'},'test')


def test_detach_keeps_attempted_projected_task_and_requires_inventory():
    m=mod('shared_control_review');r=conflicting();old=r['eight']['actions'].pop('b');mod('shared_controls').refresh(r)
    t=r['eight']['tasks']['open world'];t.update(attempts=['b'],status='done');r['eight']['actions']['b']=old;mod('shared_controls').refresh(r)
    m.apply(r,{},m.conflicts(r)[0],{'region':'eight','control':'Screen saver','field':'shared_behavior','before':'plus','after':'independent','evidence':'different'},'test')
    t=r['eight']['tasks']['open world'];assert t['attempts']==['b'] and t['status']=='blocked'
    assert 'shared_task_ref' not in t and r['eight']['task_inventory']['review']
