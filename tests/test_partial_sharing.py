from copy import deepcopy
from tests.test_recovery_discovery import mod
from tests.test_stepwise_shared_controls import records,action


def test_background_changes_do_not_break_direct_behavior_share():
    r=records();m=mod('shared_controls');a=action();a.update(interactive_regions=['screen','backgroundA'],evidence={'before_regions':['backgroundA']});r['five']['actions']['a']=a
    m.link(r,'stable',[('five','c'),('eight','c')],'same behavior',[{'region':'five','attempt':'a'}])
    b=action();b.update(interactive_regions=['screen','backgroundB'],evidence={'before_regions':['backgroundB']});r['eight']['actions']['b']=b
    m.refresh(r);assert m.view(r,'eight','c')['status']=='confirmed'
    r['eight']['actions']['b']['interactive_regions']=['other','backgroundB'];m.refresh(r)
    assert m.view(r,'eight','c')['status']=='needs_review'


def test_partial_split_keeps_only_declared_stable_control_shared():
    flow=mod('stepwise_flow');old=flow.new_region('r0001','World toolbar')
    old['controls']={'c0001':{'name':'Add','observations':[],'action_refs':[]},'c0002':{'name':'World','observations':[],'action_refs':['a1']}}
    old['actions']={'a1':{**action('world'),'control':'c0002'}}
    r={'r0001':old}
    split={'name':'Timer toolbar','description':'Timer','context':'Timer selected','original_context':'World selected','evidence':'Add opened timer','acted_control':'Add timer',
        'region':{'name':'Timer toolbar','description':'Timer','previous_name':'','parent_index':None},
        'controls':[{'name':n,'previous_name':'','region_index':0} for n in ['Add timer','World','Unknown']],
        'shared_controls':[{'control':'World','previous_control':'World','evidence':'same World navigation label and role; independent of Add'}]}
    rid,cid,_=mod('region_behavior_split').apply(r,'r0001',split,'call','obs','a2')
    cs=r[rid]['controls'];stable=next(c for c in cs.values() if c['name']=='World')
    assert stable['shared_control_ref']
    assert not cs[cid].get('shared_control_ref')
    assert not next(c for c in cs.values() if c['name']=='Unknown').get('shared_control_ref')
    assert r[rid]['actions']=={} and not r[rid].get('tasks')
    assert old['actions']['a1']['control']=='c0002'


def test_task_reuses_shared_knowledge_without_copying_execution_and_reopens_on_conflict():
    from tests.test_coverage_exemption import fixture
    from tests.test_stepwise_region_tasks import row,proposal
    r,ref,_=fixture();r['r1']['name']='Old toolbar'
    r['r2']={'id':'r2','name':'New toolbar','controls':{'local':{'name':'World','observations':[],'action_refs':[]}},'tasks':{},'actions':{}}
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'same independent navigation',[{'region':'r1','attempt':'a1'}])
    t=next(iter(r['r2']['tasks'].values()))
    assert t['status']=='record_only' and t['attempts']==[] and r['r2']['actions']=={}
    mod('coverage_exemption').reconcile(r,{'observation':{'id':'next','control_refs':['local']}})
    assert t['status']=='record_only'  # normal visibility must not revoke shared-member knowledge
    r['r1']['actions']['a1']['result']['exception']='unexpected_exit';m.refresh(r)
    mod('coverage_exemption').reconcile(r,{})
    assert t['status']=='pending' and t['handling']=='explore'


def test_difference_control_cannot_be_declared_shared():
    import pytest
    from tests.test_stepwise_behavior_split import tasks
    r={'r0001':tasks().helper('stepwise_flow').new_region('r0001','old')}
    r['r0001']['controls']={'c':{'name':'Add','observations':[]}}
    s={'name':'new','description':'new','context':'new','original_context':'old','evidence':'different',
       'region':{'previous_name':'','parent_index':None},'controls':[{'name':'Add','previous_name':'','region_index':0}],
       'acted_control':'Add','shared_controls':[{'control':'Add','previous_control':'Add','evidence':'same icon'}]}
    before=deepcopy(r)
    with pytest.raises(ValueError):mod('region_behavior_split').apply(r,'r0001',s,'call','obs','a')
    assert r==before


def test_changed_source_does_not_hide_new_conflicting_destination():
    r=records();m=mod('shared_controls')
    for rid,aid,target in [('five','a','screen'),('eight','b','other')]:
        r[rid]['actions'][aid]={**action(target),'interactive_regions':[rid,target],
           'evidence':{'before_regions':[rid]},'region_changes':[{'region':rid,'state':'changed_interactive'}]}
    m.link(r,'stable',[('five','c'),('eight','c')],'same assumption',[{'region':'five','attempt':'a'}])
    assert m.view(r,'eight','c')['status']=='needs_review'


def test_task_prompt_does_not_ask_for_sharing_decision():
    from tests.test_coverage_exemption import fixture
    from tests.test_recovery_discovery import ROOT
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    mod('shared_controls').link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    for rr in r.values():rr.setdefault('name','Old');rr.setdefault('description','Old')
    q=mod('region_tasks').plan_request(ROOT,r,{'observation':{'id':'now','image':'frame.png'}},'r2')
    props=q['response_schema']['properties']['operations']['items']['properties']
    assert 'shared_from' not in props
    assert props['control']['enum']==['']


def test_revoked_action_is_not_a_shared_task_result():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    origin=next(t for t in r['r1']['tasks'].values() if t['control']=='top')
    origin['ownership_history']=[{'invalidated_attempt':'a1'}]
    m.refresh(r)
    target=next(iter(r['r2']['tasks'].values()))
    assert target['status']=='pending' and not target.get('shared_result')


def test_shared_pending_task_keeps_local_prerequisite_blocker():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    origin=next(t for t in r['r1']['tasks'].values() if t['control']=='top');origin['status']='pending'
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    target=next(iter(r['r2']['tasks'].values()));target.update(status='blocked',blocker={'condition':'prerequisite'})
    m.refresh(r)
    assert target['status']=='blocked'


def test_member_completion_covers_origin_with_old_failed_attempts():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    origin=next(t for t in r['r1']['tasks'].values() if t['control']=='top');origin['status']='pending'
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    target=next(iter(r['r2']['tasks'].values()));target.update(status='done',attempts=['a2'])
    r['r2']['actions']['a2']={**deepcopy(r['r1']['actions']['a1']),'control':'local'}
    m.refresh(r)
    assert origin['status']=='record_only' and origin['attempts']==['a1']
    assert origin['shared_result']['region']=='r2'
    target['ownership_history']=[{'invalidated_attempt':'a2'}];m.refresh(r)
    assert origin['status']=='pending' and not origin.get('shared_result')


def test_reconfirm_reuses_the_same_task_reference():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    names=list(r['r2']['tasks']);r['r1']['actions']['a1']['result']['exception']='unexpected_exit';m.refresh(r)
    assert not next(iter(r['r2']['tasks'].values()))['shared_task_active']
    r['r1']['actions']['a1']['result']['exception']='none';m.refresh(r)
    assert list(r['r2']['tasks'])==names and next(iter(r['r2']['tasks'].values()))['status']=='record_only'


def test_member_with_attempts_restores_blocked_state_after_support_revoked():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    origin=next(t for t in r['r1']['tasks'].values() if t['control']=='top');origin['status']='pending'
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    target=next(iter(r['r2']['tasks'].values()));target.update(status='blocked',attempts=['failed'],blocker={'condition':'prerequisite'})
    origin['status']='done';m.refresh(r);assert target['status']=='record_only'
    origin['ownership_history']=[{'invalidated_attempt':'a1'}];m.refresh(r)
    assert target['status']=='blocked' and target['handling']=='explore' and target['attempts']==['failed']


def test_repeated_conflict_refresh_preserves_unattempted_blocker():
    from tests.test_coverage_exemption import fixture
    r,_,_=fixture();r['r2']=mod('stepwise_flow').new_region('r2','New toolbar')
    r['r2']['controls']={'local':{'name':'World','observations':[],'action_refs':[]}}
    origin=next(t for t in r['r1']['tasks'].values() if t['control']=='top');origin['status']='pending'
    m=mod('shared_controls');m.link(r,'World',[('r1','top'),('r2','local')],'stable',[{'region':'r1','attempt':'a1'}])
    target=next(iter(r['r2']['tasks'].values()));target.update(status='blocked',blocker={'condition':'prerequisite'})
    origin['status']='done';m.refresh(r);assert target['status']=='record_only'
    r['r1']['actions']['a1']['result']['exception']='unexpected_exit'
    m.refresh(r);m.refresh(r)
    assert target['status']=='blocked' and target['handling']=='explore'
