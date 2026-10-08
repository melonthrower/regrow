"""Task answers are explicit; preparation and unrelated obligations remain open."""
from copy import deepcopy
import pytest
import task_updates
import task_settlement as settlement
import task_knowledge
import history_selection
from result_updater import build_update_request
from tests.test_task_action_binding import ROOT


def case():
    def task(control,action,kind='control_effect',status='pending',**extra):
        return {'control':control,'action':action,'registration_kind':kind,
                'task_type':'single_action','handling':'explore','status':status,
                'reason':'discover behavior','attempts':[],'conditions':[],**extra}
    r={'id':'r','name':'Panel','controls':{'start':{'name':'Start'},'seconds':{'name':'Seconds'},'delete':{'name':'Delete'}},
       'tasks':{'start':task('start','click'),
                'identify':task('start','hover',status='blocked',attempts=['old-hover'],
                    blocker={'condition':'review_required','reason':'hover gave no hint'},
                    deferral={'retry_when':'explicit_evidence_registration'}),
                'input':task('seconds','input_text','parameter')},
       'actions':{'a':{'control':'start','operation':'click','delivery':'executed_receipt_zero',
                    'result':{'exception':'none','description':'Countdown shown','evidence':'Running panel and pause button'},
                    'parameter_findings':[]}},'transitions':[]}
    b={'region_ref':'r','task_region':'r','control_ref':'start','task_name':'start'}
    receipt={'exit_code':0,'executed_steps':[{'action':'click'}]}
    return {'r':r},b,receipt


def row(name,knowledge='Starts the countdown',**extra):
    return {'task':'r/'+name,'findings':[],'next_action':None,'knowledge':knowledge,
            'registration_gap':'','entry':None,**extra}


def run(records,binding,receipt,rows):
    r=records['r']
    settlement.settle_task(r,binding,{'action_result':r['actions']['a']['result'],'task_update':rows},'a',records,
                          receipt=receipt,candidates=task_updates.catalog(records,binding))


def test_same_control_click_answers_old_question_without_rewriting_hover():
    records,b,receipt=case();r=records['r'];old_input=deepcopy(r['tasks']['input'])
    run(records,b,receipt,[row('start'),row('identify')])
    t=r['tasks']['identify']
    assert t['status']=='done' and t['action']=='hover' and t['attempts']==['old-hover']
    assert 'blocker' not in t and 'deferral' not in t and t['blocker_history']
    assert t['completion_basis']['operation']=='click'
    assert history_selection.task_attempts(t)=={'old-hover','a'}
    assert task_knowledge.control_knowledge(r,'start')['identify']['source']['completion_basis']['attempt']=='a'
    assert r['tasks']['input']==old_input


@pytest.mark.parametrize('change',['other_control','parameter','conditions','exception','unconfirmed','duplicate'])
def test_no_incidental_completion(change):
    records,b,receipt=case();r=records['r'];t=r['tasks']['identify']
    rows=[row('start'),row('identify')]
    if change=='other_control':t['control']='seconds'
    if change=='parameter':t['registration_kind']='parameter'
    if change=='conditions':t['conditions']=['Paused']
    if change=='exception':t['blocker']['exception']='unexpected_exit'
    if change=='unconfirmed':r['actions']['a']['association']={'status':'unconfirmed'}
    if change=='duplicate':rows.append(row('identify'))
    with pytest.raises(ValueError):run(records,b,receipt,rows)


def test_omitted_old_question_is_not_silently_completed():
    records,b,receipt=case();run(records,b,receipt,[row('start')])
    assert records['r']['tasks']['identify']['status']=='blocked'


def test_answered_question_inherits_observed_conditions():
    records,b,receipt=case();r=records['r']
    r['tasks']['start']['conditions']=['Nonzero duration']
    run(records,b,receipt,[row('start'),row('identify')])
    assert r['tasks']['identify']['conditions']==['Nonzero duration']
    assert task_knowledge.control_knowledge(r,'start')['identify']['conditions']==['Nonzero duration']


def test_preparation_and_null_advice_preserve_input_goal():
    records,b,receipt=case();r=records['r'];b['task_name']='input'
    suggestion={'region':'Panel','control':'Delete','action':'click','reason':'Return to the editable fields'}
    run(records,b,receipt,[row('input','',next_action=suggestion,registration_gap='Input field not visible yet')])
    t=r['tasks']['input'];assert t['status']=='pending' and 'completion_action' not in t
    assert task_updates.latest_suggestion(records,t)['control']=='delete'
    r['actions']['a']['control']='delete'
    run(records,b,receipt,[row('input','',registration_gap='Returned; text not entered yet')])
    assert t['status']=='pending' and t['control']=='seconds' and t['action']=='input_text'
    assert not task_updates.latest_suggestion(records,t)
    assert not task_knowledge.control_knowledge(r,'seconds')


def test_normal_list_schema_has_one_update_interface():
    q=build_update_request(ROOT,{'本轮探索任务':'start','任务目标':{'registration_kind':'control_effect'},
                                '任务更新引用':['r/start','r/identify']},['before.png','after.png'])
    props=q['response_schema']['properties'];schema=props['task_update']
    assert 'resolved_tasks' not in props and schema['type']=='array'
    assert schema['items']['properties']['task']['enum']==['r/start','r/identify']
    assert set(schema['items']['properties'])=={'task','findings','next_action','knowledge','registration_gap','entry'}


def test_active_task_cannot_be_omitted():
    records,b,receipt=case()
    with pytest.raises(ValueError,match='当前任务'):run(records,b,receipt,[row('identify')])


def test_navigation_without_open_tasks_keeps_the_same_empty_list_interface():
    import jsonschema
    q=build_update_request(ROOT,{'任务更新引用':[],'来源区块已有任务':[]},['before.png','after.png'])
    schema=q['response_schema']['properties']['task_update']
    jsonschema.Draft202012Validator.check_schema(q['response_schema'])
    assert schema['type']=='array' and schema['maxItems']==0


def test_answered_goal_can_finish_with_following_cleanup_suggestion():
    records,b,receipt=case();r=records['r']
    suggestion={'region':'Panel','control':'Delete','action':'click','reason':'Clean up after the observation'}
    run(records,b,receipt,[row('start',next_action=suggestion)])
    assert r['tasks']['start']['status']=='done'
    assert r['tasks']['start']['knowledge']=='Starts the countdown'
    assert r['tasks']['identify']['status']=='blocked'


def test_reconciliation_does_not_complete_omitted_tasks():
    records,b,receipt=case();r=records['r']
    r['tasks']['other_question']={**deepcopy(r['tasks']['start']),'reason':'A different question'}
    run(records,b,receipt,[row('start')])
    assert not settlement.reconcile(records)
    assert r['tasks']['other_question']['status']=='pending'


@pytest.mark.parametrize('referenced',[False,True])
def test_list_update_retains_reference_through_real_split(referenced):
    from tests.test_control_context import split_case
    from tests.test_task_knowledge_flow import reply
    import control_context
    records,b,t=split_case();candidates=task_updates.catalog(records,b)
    if referenced:
        records['r']['tasks']['alias']={**deepcopy(t),'handling':'equivalent','equivalent_to':'options'}
    revised=control_context.migrate_split_task(records,b,'new','newc','a')
    revised.update(region_ref='new',control_ref='newc',task_update_ref='r/options')
    q=reply();q['task_update']=[{**q['task_update'],'task':'r/options','entry':None}]
    settlement.settle_task(records[revised['task_region']],revised,q,'a',records,candidates=candidates)
    assert t['status']=='done' and t['completion_basis']['region']=='new'
