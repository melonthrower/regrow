from copy import deepcopy
import pytest
from tests.test_recovery_discovery import ROOT,mod


def records():
    def obs(call,field,view):return {'evidence':{'source_call':call,'source_field':field,'observation':'update:'+call},'icon_description':view,'possible_operation':view,'image':'images/'+call+'.png'}
    return {'r':{'id':'r','name':'picker','controls':{
        'dial':{'name':'clock','observations':[obs('1','/controls/0','select hour'),obs('2','/controls/0','switch mode')],'action_refs':['a1']},
        'switch':{'name':'mode','observations':[obs('1','/controls/1','switch mode')],'action_refs':[]}},
        'tasks':{'select':{'control':'dial','status':'done','attempts':['a1']}},
        'actions':{'a1':{'control':'dial','evidence':{'before_observation':'update:1'}}},
        'functions':[{'name':'old'}],'task_inventory':{'inventory':'complete'}}}


def edit():return {'region':'picker','from_control':'clock','to_control':'mode','retained_name':'dial restored','observations':[{'source_call':'2','source_field':'/controls/0'}],'evidence':'original frame shows mode button'}


def test_move_only_selected_observation_and_keep_business_history():
    m=mod('control_observation_repair');r=records();before=deepcopy(r);state={'observation':{'id':'update:2','control_refs':['dial']}}
    m.apply(r,state,edit(),'3')
    assert r['r']['controls']['dial']['name']=='dial restored'
    revision=r['r']['control_observation_revisions'][-1]
    assert revision['previous_name']=='clock' and revision['retained_name']=='dial restored'
    assert len(r['r']['controls']['dial']['observations'])==1
    assert len(r['r']['controls']['switch']['observations'])==2
    assert r['r']['tasks']==before['r']['tasks'] and r['r']['actions']==before['r']['actions']
    assert state['observation']['control_refs']==['switch']
    assert r['r']['controls']['dial']['action_refs']==['a1']
    assert r['r']['task_inventory']['review'] and r['r']['control_observation_revisions']


def test_moving_evidence_used_by_action_requires_separate_owner_review():
    m=mod('control_observation_repair');r=records();r['r']['actions']['a1']['evidence']['before_observation']='update:2';before=deepcopy(r)
    with pytest.raises(ValueError,match='动作'):m.apply(r,{},edit(),'3')
    assert r==before


def test_unknown_or_duplicate_source_is_not_a_best_effort_edit():
    m=mod('control_observation_repair');r=records();e=edit();e['observations']*=2
    with pytest.raises(ValueError):m.apply(r,{},e,'3')
    assert len(r['r']['controls']['dial']['observations'])==2


def test_candidate_projection_keeps_role_history_after_relabel():
    m=mod('region_candidate_names');r=records();r['r']['description']='picker'
    rows,_=m.candidates(r,[{'region_ref':'r','name':'picker'}]);c=rows[0]['controls'][0]
    assert c['name']=='clock'
    assert 'select hour' in str(c) and 'switch mode' in str(c) and 'select' in str(c)


def test_new_edit_variant_is_not_treated_as_proposal_field_edit(tmp_path):
    m=mod('repair_stages')
    assert m.edit_proposal(tmp_path,{'stage':'update','candidate':{'regions':[{'name':'picker'}]}},edit()) is False


def test_same_frame_two_objects_retains_unmoved_identity():
    m=mod('control_observation_repair');r=records()
    r['r']['controls']['dial']['observations'][0]['evidence']['observation']='update:2'
    r['r']['actions']={};state={'observation':{'id':'update:2','control_refs':['dial']}}
    m.apply(r,state,edit(),'3')
    assert state['observation']['control_refs']==['dial','switch']


def test_cannot_remove_last_observation_from_retained_control():
    m=mod('control_observation_repair');r=records();r['r']['controls']['dial']['observations']=r['r']['controls']['dial']['observations'][1:];r['r']['actions']={}
    with pytest.raises(ValueError,match='最后'):m.apply(r,{},edit(),'3')


def test_same_transaction_rename_does_not_invalidate_original_source_label(tmp_path):
    import json
    m=mod('control_observation_repair');r=records();scope=deepcopy(r)
    (tmp_path/'knowledge_current.json').write_text(json.dumps({'snapshot':'s'}))
    job={'request':{'control_observation_snapshot':'s','control_observation_candidates':[{'region':'r','from_control':'dial','to_control':'switch','observations':edit()['observations']}]}}
    r['r']['controls']['dial']['name']='dial restored'
    bound=m.validate_scope(tmp_path,job,edit(),r,scope)
    m.apply(r,{},bound,'3')
    assert r['r']['controls']['dial']['name']=='dial restored'
    assert len(r['r']['controls']['switch']['observations'])==2
