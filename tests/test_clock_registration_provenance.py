from copy import deepcopy
from tests.test_recovery_discovery import mod


def test_wrong_control_result_is_preserved_but_does_not_complete_task():
    owner={'id':'r1','tasks':{'inspect':{'control':'center','action':'click','handling':'explore','task_type':'single_action','status':'pending','attempts':[]}},
           'actions':{'a1':{'control':'top','operation':'click','delivery':'executed_receipt_zero',
                            'result':{'exception':'none','description':'Opened dialog'}}}}
    reply={'task_result':{'name':'inspect','status':'done','evidence':'Opened dialog','findings':[]},'action_result':{'exception':'none'}}
    mod('region_tasks').settle_task(owner,{'task_name':'inspect','region_ref':'r1','control_ref':'top'},reply,'a1')
    task=owner['tasks']['inspect']
    assert task['status']=='pending'
    assert task['attempts']==['a1']
    assert 'completion_basis' not in task
    assert owner['actions']['a1']['control']=='top'
    assert reply['task_result']['status']=='done'  # immutable model evidence


def test_same_control_can_complete():
    owner={'id':'r1','tasks':{'inspect':{'control':'center','task_type':'single_action','status':'pending','attempts':[]}}}
    reply={'task_result':{'name':'inspect','status':'done','evidence':'Opened dialog','findings':[]},'action_result':{'exception':'none'}}
    mod('region_tasks').settle_task(owner,{'task_name':'inspect','region_ref':'r1','control_ref':'center'},reply,'a1')
    assert owner['tasks']['inspect']['status']=='done'


def test_confirmed_history_survives_navigation_but_invalidated_history_does_not():
    for invalid in [False,True]:
        task={'control':'center','action':'click','task_type':'single_action','status':'pending','attempts':['old']}
        if invalid:task['ownership_history']=[{'invalidated_attempt':'old'}]
        owner={'id':'r1','tasks':{'inspect':task},'actions':{'old':{'control':'center','operation':'click',
            'delivery':'executed_receipt_zero','result':{'exception':'none','description':'Opened dialog'}}}}
        reply={'task_result':{'name':'inspect','status':'done','evidence':'Earlier entry opened dialog','findings':[]},'action_result':{'exception':'none'}}
        mod('region_tasks').settle_task(owner,{'task_name':'inspect','region_ref':'r2','control_ref':'back'},reply,'new')
        assert task['status']==('pending' if invalid else 'done')


def proposal():
    return {'regions':[{'name':'panel','previous_name':'panel','parent_index':None,'bbox':{'left':100,'top':100,'right':400,'bottom':400}}],
            'controls':[{'name':'plus','previous_name':'','region_index':0,'bbox':{'left':10,'top':10,'right':30,'bottom':30},'click_bbox':{'left':10,'top':10,'right':30,'bottom':30}}]}


def test_disjoint_control_owner_reports_specific_correction():
    errors=mod('registration_diagnostics').collect('update',{},proposal(),{'r1':{'name':'panel','controls':{}}})['errors']
    assert any(e['code']=='control_owner_surface' for e in errors)


def test_missing_or_partly_overlapping_box_is_not_proof_of_wrong_owner():
    for box in [None,{'left':95,'top':110,'right':150,'bottom':140}]:
        p=proposal();p['controls'][0]['click_bbox']=box;p['controls'][0]['bbox']=box
        errors=mod('registration_diagnostics').collect('update',{},p,{'r1':{'name':'panel','controls':{}}})['errors']
        assert not any(e['code']=='control_owner_surface' for e in errors)


def test_context_specific_reuse_requires_current_context_confirmation():
    p=proposal();p['controls']=[]
    records={'r1':{'name':'panel','controls':{},'behavior_context':'calendar selected'}}
    for value in [None,False]:
        p['regions'][0]['context_matches']=value
        assert any(e['code']=='region_context' for e in mod('registration_diagnostics').collect('update',{},p,records)['errors'])
    p['regions'][0]['context_matches']=True
    assert not mod('registration_diagnostics').collect('update',{},p,records)['errors']


def test_retained_context_cannot_bypass_check_and_background_is_allowed():
    records={'r1':{'name':'panel','controls':{},'behavior_context':'calendar selected'}}
    p={'regions':[],'controls':[],'previous_regions':[{'name':'panel','state':'retained_interactive'}]}
    assert mod('registration_diagnostics').collect('update',{},p,records)['errors'][0]['code']=='region_context'
    p['previous_regions'][0]['state']='visible_background_blocked'
    assert not mod('registration_diagnostics').collect('update',{},p,records)['errors']


def test_generated_schema_requires_context_on_both_reuse_paths_and_split():
    from tests.test_recovery_discovery import ROOT
    q=mod('result_updater').build_update_request(ROOT,{},['before.png','after.png'])
    props=q['response_schema']['properties']
    for item in [props['regions']['items'],props['previous_regions']['items'],props['source_region_split']['anyOf'][1]['properties']['region']]:
        assert 'context_matches' in item['required']


def test_dynamic_object_comparison_uses_ids_not_similar_labels():
    records={'r1':{'id':'r1','name':'window','controls':{'center':{'name':'Add'},'top':{'name':'Add'}},'tasks':{'inspect':{'control':'center'}}}}
    d=mod('region_tasks').task_object_context(records,{'region_ref':'r1','control_ref':'top','task_name':'inspect'})
    assert d['登记身份一致'] is False
    assert '不证明视觉身份' in d['核对说明']


def test_same_frame_parent_child_duplicate_control_reported():
    p=proposal();p['regions'][0]['bbox']={'left':0,'top':0,'right':400,'bottom':400}
    p['regions'].append({'name':'child','previous_name':'','parent_index':0,'bbox':{'left':0,'top':0,'right':100,'bottom':100}})
    p['controls'].append({**deepcopy(p['controls'][0]),'region_index':1})
    errors=mod('registration_diagnostics').collect('update',{},p,{'r1':{'name':'panel','controls':{}}})['errors']
    assert any(e['code']=='duplicate_control_owner' for e in errors)
