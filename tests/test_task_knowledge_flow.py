"""Task completion gates knowledge; current state belongs to this observation."""
from copy import deepcopy
import pytest
import task_knowledge as knowledge
import task_settlement as settlement
from tests.test_current_page_context import case, module


def learning_case():
    task={'control':'c','action':'click','task_type':'parameter','registration_kind':'parameter',
          'handling':'explore','status':'pending','reason':'observe duration options','attempts':[]}
    action={'control':'c','operation':'click','delivery':'executed_receipt_zero',
            'result':{'exception':'none','description':'Menu opened; 5 minutes selected'},
            'parameter_findings':[fact()]}
    owner={'id':'r','name':'Dialog','controls':{'c':{'name':'Duration','observations':[
        {'text':'Duration','state':'5 minutes selected','evidence':{'observation':'o'}}]}},
        'tasks':{'options':task},'actions':{'a':action}}
    state={'interactive_regions':['r'],'observation':{'id':'o','control_refs':['c']}}
    return owner,task,action,state


def fact():
    return {'name':'duration','description':'Duration of ringing','domain':{'type':'enum',
        'values':['1 minute','5 minutes'],'min':None,'max':None},'conditions':[],
        'evidence':'Menu opened with 5 minutes selected'}


def reply(**extra):
    return {'action_result':{'exception':'none'},'task_update':{'findings':[fact()],
        'knowledge':'Select the ringing duration from the menu','registration_gap':'','next_action':None,**extra}}


def test_observe_then_settle_then_materialize_without_waiting_for_summary():
    r,t,a,s=learning_case();records={'r':r}
    settlement.store_findings(t,[fact()],{'region':'r','task':'options','control':'c'})
    knowledge.refresh(records,s)
    assert not r['controls']['c']['knowledge']
    assert r['current_observation']['controls']['c']['state']=='5 minutes selected'
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(),'a',records)
    knowledge.refresh(records,s)
    assert t['status']=='done'
    learned=r['controls']['c']['knowledge']['options']
    assert learned['parameters']['duration']['description']=='Duration of ringing'
    assert 'selected' not in str(learned)
    assert not r.get('local_knowledge')
    assert 'selected' in t['findings']['duration']['source']['evidence']


def test_gap_or_continuation_does_not_publish_stable_knowledge():
    r,t,a,s=learning_case();records={'r':r}
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(knowledge='',registration_gap='menu still obscured'),'a',records)
    knowledge.refresh(records,s)
    assert t['status']=='blocked' and not r['controls']['c']['knowledge']
    assert r['current_observation']['controls']['c']
    assert not settlement.reconcile(records)
    r,t,a,s=learning_case();records={'r':r}
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(knowledge='',next_action={
        'region':'Dialog','control':'Duration','action':'click','reason':'focus only; now open menu'}),'a',records)
    knowledge.refresh(records,s)
    assert t['status']=='pending' and not r['controls']['c']['knowledge']
    assert not settlement.reconcile(records)


def test_unknown_effect_cannot_complete_just_because_it_was_clicked():
    r,t,a,s=learning_case();t['registration_kind']='control_effect'
    with pytest.raises(ValueError,match='稳定knowledge'):
        settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(knowledge=''),'a',{'r':r})


def test_new_frame_does_not_carry_old_or_visual_only_state():
    r,t,a,s=learning_case();records={'r':r};knowledge.refresh(records,s)
    s['observation']['id']='new';knowledge.refresh(records,s)
    assert r['current_observation']['controls']=={}
    r['controls']['c']['observations'].append({'state':'enabled','visual_only':True,'evidence':{'observation':'new'}})
    knowledge.refresh(records,s);assert r['current_observation']['controls']=={}
    s['interactive_regions']=[];knowledge.refresh(records,s);assert r['current_observation']=={}


def test_reopening_removes_current_knowledge_without_deleting_task_evidence():
    r,t,a,s=learning_case();records={'r':r}
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(),'a',records)
    knowledge.refresh(records,s);assert r['controls']['c']['knowledge']
    t['status']='pending';knowledge.refresh(records,s)
    assert not r['controls']['c']['knowledge'] and t['knowledge'] and t['findings']


def test_map_only_discloses_current_state_on_matching_selection_frame(tmp_path):
    records,state,frame=case(tmp_path);view=module().build(records,state,run=tmp_path)
    view['frame_relation']='same_observation_frame'
    assert '本次状态' in module()._display(view)
    view['frame_relation']='historical_structure_needs_recheck'
    assert '本次状态' not in module()._display(view)
    view['frame_relation']='same_observation_frame';view['usage']='before_action'
    assert '本次状态' not in module()._display(view)


def test_record_observation_can_publish_without_claiming_execution():
    import region_tasks
    r,t,a,s=learning_case();r['tasks']={};r['actions']={}
    row={'control':'Duration','name':'options','action':'click','task_type':'parameter',
         'registration_kind':'parameter','handling':'record','reason':'Options visible in the menu',
         'equivalent_to':'','findings':[fact()],'knowledge':'Choose a ringing duration'}
    region_tasks.apply_plan(r,{'inventory':'complete','evidence':'Visible menu','operations':[row]},'q',records={'r':r},state=s)
    knowledge.refresh({'r':r},s)
    assert r['controls']['c']['knowledge']['options']['source']['basis']=='observation_only'
    assert not r['actions']
    r['tasks']={};row['handling']='explore'
    with pytest.raises(ValueError,match='不得预写'):
        region_tasks.apply_plan(r,{'inventory':'complete','evidence':'Visible','operations':[row]},'q2',records={'r':r},state=s)


def test_compact_summary_keeps_conditions_constraints_and_result_limits():
    view=knowledge.summary_view({'self':{'summary':'configure'},'entries':[],
        'knowledge':{'conditions':[{'description':'enable first','tasks':['enable']}],
        'parameters':{'duration':{**fact(),'source':{'call':'historical'}}}},
        'functions':{'configure':{'completion':'visible update','unconfirmed':['restart not checked'],
            'constraints':{'duration':{**fact(),'sources':[{'call':'historical'}]}},'locations':['old']}}})
    assert view['conditions'][0]['description']=='enable first'
    assert view['functions']['configure']['constraints']['duration']['domain']['values']==['1 minute','5 minutes']
    assert view['functions']['configure']['unconfirmed']==['restart not checked']
    assert 'historical' not in str(view)


def test_region_owned_knowledge_reaches_next_map(tmp_path):
    records,state,frame=case(tmp_path)
    records['dialog']['tasks']['scroll']={'control':None,'status':'done','handling':'explore',
        'knowledge':'Scroll the list to reveal more options','attempts':[]}
    knowledge.refresh(records,state)
    view=module().build(records,state,run=tmp_path)
    assert records['dialog']['operation_knowledge']['scroll']
    assert 'Scroll the list to reveal more options' in module()._display(view)
