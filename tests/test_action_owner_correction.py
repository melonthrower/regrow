from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def fixture():
    a={'control':'old','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'blocking_popup','description':'permission'},'evidence':{'before_observation':'o1','before_image':'before.png','after_image':'after.png'}}
    old={'id':'r1','name':'A','controls':{'old':{'name':'First Continue','action_refs':['a1'],'task_refs':['old goal']}},'actions':{'a1':a},'tasks':{'old goal':{'name':'old goal','control':'old','action':'click','task_type':'single_action','handling':'explore','status':'done','reason':'first entry','attempts':['a1'],'result_evidence':'permission'},'alias':{'name':'alias','control':'old','action':'click','task_type':'single_action','handling':'equivalent','equivalent_to':'old goal','status':'pending','attempts':[]}},'functions':{},'transitions':[],'task_inventory':{'inventory':'complete'}}
    new={'id':'r2','name':'B','controls':{'new':{'name':'Second Continue','action_refs':[],'task_refs':['new goal'],'observations':[{'evidence':{'observation':'o1'}}]}},'actions':{},'tasks':{'new goal':{'name':'new goal','control':'new','action':'click','task_type':'single_action','handling':'explore','status':'pending','reason':'second entry','attempts':[]}},'functions':{},'transitions':[],'task_inventory':{'inventory':'complete'}}
    return {'r1':old,'r2':new},{'active_task':{'region':'r2','name':'new goal'}}, {'attempt':'a1','from_region':'A','from_control':'First Continue','to_region':'B','to_control':'Second Continue','evidence':'before point and surrounding label identify second entry'}


def test_move_only_one_action_and_invalidate_wrong_completion():
    records,state,edit=fixture();before=deepcopy(records)
    mod('action_owner_correction').apply(records,state,edit,'review')
    assert 'a1' not in records['r1']['actions']
    action=records['r2']['actions']['a1'];assert action['control']=='new' and action['result']==before['r1']['actions']['a1']['result']
    assert records['r1']['controls']['old']['action_refs']==[] and records['r2']['controls']['new']['action_refs']==['a1']
    assert records['r1']['tasks']['old goal']['status']=='blocked'
    assert records['r1']['tasks']['old goal']['attempts']==['a1']
    assert records['r2']['tasks']['new goal']['status']=='pending' and records['r2']['tasks']['new goal']['attempts']==[]
    assert records['r1']['tasks']['alias']['equivalent_to']=='old goal'
    assert records['r1']['tasks']['old goal']['ownership_history'][0]['result_evidence']=='permission'
    assert action['ownership_history'][0]['control']=='old'


@pytest.mark.parametrize('change',[{'from_control':'different'},{'to_control':'missing'},{'evidence':''}])
def test_reject_inconsistent_edit_without_mutation(change):
    records,state,edit=fixture();before=deepcopy(records)
    with pytest.raises(ValueError):mod('action_owner_correction').apply(records,state,{**edit,**change},'review')
    assert records==before


def test_target_must_have_observation_from_before_action():
    records,state,edit=fixture();records['r2']['controls']['new']['observations'][0]['evidence']['observation']='later'
    with pytest.raises(ValueError):mod('action_owner_correction').apply(records,state,edit,'review')


def test_same_control_history_does_not_fake_new_attempt():
    records,state,edit=fixture();m=mod('action_owner_correction');m.apply(records,state,edit,'review')
    target=records['r2'];task=target['tasks']['new goal'];assert m.control_history(target,task)==['a1']
    assert task['attempts']==[]
    assert m.control_history(records['r1'],records['r1']['tasks']['old goal'])==[]


def test_other_evidence_reopens_review_without_discarding_it():
    records,state,edit=fixture();t=records['r1']['tasks']['old goal'];t['attempts'].append('a2')
    mod('action_owner_correction').apply(records,state,edit,'review')
    assert t['status']=='pending' and t['attempts']==['a1','a2']
    assert mod('action_owner_correction').effective_attempts(t)==['a2']
    assert 'blocker' not in t


def test_invalidated_attempt_cannot_complete_old_task_again():
    records,state,edit=fixture();mod('action_owner_correction').apply(records,state,edit,'review')
    t=records['r1']['tasks']['old goal'];t['status']='pending'
    with pytest.raises(ValueError,match='没有累计'):
        mod('task_result_review').apply(records['r1'],state,'old goal',{'name':'old goal','status':'done','evidence':'old history'},'later')
    history=mod('history_context').task_goal(t,records)
    assert '不支持本控件完成' in history['最近连续动作'][0]['关联']


def test_only_edges_supported_by_corrected_attempt_move():
    records,state,edit=fixture();edge={'attempt':'a1','source_region':'r1','source_control':'old','target_region':'r2'}
    other={**edge,'attempt':'a2'};records['r1']['transitions']=[edge,other]
    records['r2']['reached_by']=[deepcopy(edge),deepcopy(other)]
    mod('action_owner_correction').apply(records,state,edit,'review')
    assert records['r1']['transitions']==[other]
    assert records['r2']['transitions'][0]['source_control']=='new'
    assert records['r2']['reached_by'][0]['source_region']=='r2'
    assert records['r2']['reached_by'][1]==other


def test_reused_completion_consumer_is_invalidated_too():
    records,state,edit=fixture();t=records['r1']['tasks']['old goal'];t['attempts']=[];t['completion_basis']={'rule':'reviewed_control_history','attempts':['a1']}
    mod('action_owner_correction').apply(records,state,edit,'review')
    assert t['status']=='blocked' and 'completion_basis' not in t
    assert t['ownership_history'][0]['completion_basis']['attempts']==['a1']
