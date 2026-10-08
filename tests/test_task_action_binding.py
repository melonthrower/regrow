"""Traversal work is consumed by recorded actions, never by a model's done label."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import region_tasks
import task_settlement
from result_updater import build_update_request

ROOT=Path(region_tasks.__file__).parent

def fixture():
    task={'name':'查看选项','control':'c1','action':'click','task_type':'parameter',
          'handling':'explore','status':'pending','reason':'点击入口，记录直接反馈',
          'attempts':[],'equivalent_to':'','prerequisite':None}
    region={'id':'r1','name':'设置','description':'设置内容','controls':{'c1':{'name':'样式'},'c2':{'name':'其他入口'}},
            'tasks':{'查看选项':task},'actions':{}}
    binding={'task_name':'查看选项','task_region':'r1','region_ref':'r1','control_ref':'c1'}
    fact={'name':'样式','description':'可选样式','domain':{'type':'enum','values':['Digital','Analog'],'min':None,'max':None},
          'conditions':[],'evidence':'选择器显示两个选项'}
    reply={'task_update':{'findings':[fact],'next_action':None,'registration_gap':''},
           'action_result':{'exception':'none','description':'打开样式菜单；未切换设置'},
           'exploration_update':{'attempt_status':'executed'}}
    receipt={'exit_code':0,'executed_steps':[{'action':'click'}]}
    region['actions']['a1']={'operation':'click','control':'c1','delivery':'executed_receipt_zero','result':reply['action_result'],'parameter_findings':[fact]}
    return region,binding,reply,receipt

def settle(region,binding,reply,receipt):
    task_settlement.settle_task(region,binding,reply,'a1',{region['id']:region},receipt=receipt)
    return region['tasks']['查看选项']

def test_recorded_bound_action_finishes_exploration_without_model_status():
    r,b,q,receipt=fixture()
    t=settle(r,b,q,receipt)
    assert t['status']=='done'
    assert t['completion_basis']['rule']=='exploration_result_registered'
    assert t['completion_basis']['registration_kind']=='parameter'
    assert t['result_evidence']=='打开样式菜单；未切换设置'

@pytest.mark.parametrize('change',['other_control','other_action','unconfirmed','failed_delivery','partial_input'])
def test_nonmatching_or_unconfirmed_execution_does_not_finish_original(change):
    r,b,q,receipt=fixture();a=r['actions']['a1']
    if change=='other_control':a['control']='c2';b['control_ref']='c2'
    if change=='other_action':a['operation']='hover';receipt['executed_steps']=[{'action':'hover'}]
    if change=='unconfirmed':a['association']={'status':'unconfirmed'}
    if change=='failed_delivery':receipt['exit_code']=1
    if change=='partial_input':
        r['tasks']['查看选项']['action']='input_text';a['operation']='input_text';receipt['text_delivered']=False
    assert settle(r,b,q,receipt)['status']=='pending'

def test_next_action_is_advice_and_preserves_original_goal():
    r,b,q,receipt=fixture()
    q['task_update']['next_action']={'region':'设置','control':'其他入口','action':'click','reason':'原入口仅聚焦；需要点击实际展开入口'}
    t=settle(r,b,q,receipt)
    assert t['status']=='pending'
    assert t['control']=='c1'
    assert 'completion_action' not in t
    assert r['actions']['a1']['next_action']['control']=='c2'
    assert 'a1' in r['actions'] and 'a1' in t['attempts']
    r['actions']['a2']={**r['actions']['a1'],'control':'c2'}
    q['task_update']['next_action']=None
    task_settlement.settle_task(r,{**b,'control_ref':'c2'},q,'a2',{'r1':r},receipt=receipt)
    assert t['status']=='pending' and 'completion_basis' not in t
    assert r['actions']['a2']['next_action'] is None

def test_renamed_same_control_action_reuses_done_task_and_keeps_other_action():
    r,b,q,receipt=fixture();settle(r,b,q,receipt)
    row={'control':'样式','name':'再看一次样式菜单','action':'click','handling':'explore',
         'reason':'查看样式选项','equivalent_to':'','task_type':'parameter'}
    region_tasks.apply_plan(r,{'inventory':'partial','evidence':'样式可见','operations':[row]},'new',records={'r1':r})
    assert list(r['tasks'])==['查看选项'] and r['tasks']['查看选项']['status']=='done'
    row.update(name='悬停反馈',action='hover',task_type='single_action')
    region_tasks.apply_plan(r,{'inventory':'partial','evidence':'悬停有独立反馈','operations':[row]},'next',records={'r1':r})
    assert r['tasks']['悬停反馈']['status']=='pending'

def test_update_schema_records_facts_and_optional_next_action_without_task_verdict():
    q=build_update_request(ROOT,{'本轮探索任务':'查看选项','任务目标':{'type':'parameter'}},['before.png','after.png'])
    fields=q['response_schema']['properties']
    assert 'task_result' not in fields and 'related_task_results' not in fields
    assert set(fields['task_update']['properties'])=={'findings','next_action','registration_gap','knowledge'}
    assert '累计任务' not in q['system_prompt']

def test_preparation_requires_observed_condition_not_just_entry_click():
    r,b,q,receipt=fixture()
    r['tasks']['查看选项']['prepares']={'region':'r1','task':'主任务'}
    assert settle(r,b,q,receipt)['status']=='pending'
    assert not task_settlement.reconcile({'r1':r})

def test_reconcile_preserves_observed_parameter_facts():
    r,b,q,receipt=fixture()
    fact={'name':'样式','description':'可选样式','domain':{'type':'enum','values':['Digital','Analog'],'min':None,'max':None},
          'conditions':[],'evidence':'选择器显示两个选项'}
    r['actions']['a1']['parameter_findings']=[fact]
    assert task_settlement.reconcile({'r1':r})
    assert r['tasks']['查看选项']['findings']['样式']['domain']['values']==['Digital','Analog']


@pytest.mark.parametrize('candidate_control,excluded,expected', [('c1',False,'blocked'),('c2',False,'pending'),('c1',True,'pending')])
def test_delivered_unconfirmed_task_candidate_is_a_gap_not_a_repeat_click(candidate_control,excluded,expected):
    r,_,_,_=fixture();task=r['tasks']['查看选项'];task['attempts']=['a1']
    action=r['actions']['a1'];action['control']=None
    action['association']={'status':'unconfirmed','candidates':[{'region':'r1','control':candidate_control}]}
    if excluded:task['completion_action']={'region':'r1','control':'c1','action':'click','excluded_attempts':['a1']}
    original=deepcopy(action)
    assert task_settlement.reconcile({'r1':r}) == (expected=='blocked')
    assert task['status']==expected and action==original and 'completion_basis' not in task
    if expected=='blocked':
        assert task['deferral']['retry_when']=='explicit_task_ownership_review'
        assert not task_settlement.reconcile({'r1':r})


def test_missing_parameter_registration_requires_correction_or_explicit_gap():
    r,b,q,receipt=fixture();r['actions']['a1']['parameter_findings']=[];q['task_update']['findings']=[]
    with pytest.raises(ValueError,match='findings参数事实'):settle(r,b,q,receipt)
    assert not task_settlement.reconcile({'r1':r})
    q['task_update']['registration_gap']='菜单未展开，尚未看见参数选项'
    task=settle(r,b,q,receipt)
    assert task['status']=='blocked' and task['attempts']==['a1']
    assert 'a1' in r['actions'] and not task_settlement.reconcile({'r1':r})


def test_entry_registration_resolves_actual_destination_and_keeps_semantics():
    r,b,q,receipt=fixture();task=r['tasks']['查看选项'];task['registration_kind']='entry'
    dest={'id':'r2','name':'样式菜单','tasks':{},'controls':{},'actions':{}}
    records={'r1':r,'r2':dest};a=r['actions']['a1']
    a.update(interactive_regions=['r2'],evidence={'before_regions':['r1']},region_changes=[])
    r['transitions']=[{'attempt':'a1','target_region':'r2','source_control':'c1'}]
    q['task_update']['entry']={'region':'样式菜单','meaning':'打开样式选项','conditions':[], 'evidence':'原设置表面被样式菜单覆盖'}
    task_settlement.settle_task(r,b,q,'a1',records,receipt=receipt)
    assert task['status']=='done' and a['entry_registration']['region']=='r2'
    assert r['transitions'][0]['entry_semantics']['meaning']=='打开样式选项'
    task['status']='pending';q['task_update']['entry']['region']='设置'
    with pytest.raises(ValueError,match='入口去向必须'):task_settlement.settle_task(r,b,q,'a1',records,receipt=receipt)


def test_no_transition_cannot_finish_entry_but_probe_can_record_no_visible_change():
    r,b,q,receipt=fixture();task=r['tasks']['查看选项'];task['registration_kind']='entry'
    q['task_update'].update(entry=None,registration_gap='点击后未确认入口去向')
    assert settle(r,b,q,receipt)['status']=='blocked'
    r,b,q,receipt=fixture();r['tasks']['查看选项']['registration_kind']='control_effect'
    q['action_result']['description']='试点击后本图未见变化，功能含义仍未确定'
    assert settle(r,b,q,receipt)['status']=='done'


def test_direct_parameter_record_requires_catalog_fact():
    r,b,q,receipt=fixture();r['tasks']={}
    row={'control':'样式','name':'登记样式','action':'click','handling':'record','reason':'可见选项',
         'equivalent_to':'','task_type':'single_action','registration_kind':'parameter','findings':[]}
    plan={'inventory':'partial','evidence':'实际可见','operations':[row]}
    with pytest.raises(ValueError,match='参数直接登记需要findings'):region_tasks.apply_plan(r,plan,'plan')
    row['findings']=q['task_update']['findings']
    region_tasks.apply_plan(r,plan,'plan')
    assert r['tasks']['登记样式']['status']=='record_only' and r['tasks']['登记样式']['findings']


def test_historical_parameter_supplement_keeps_task_fact_provenance():
    import task_result_review
    r,b,q,receipt=fixture();task=r['tasks']['查看选项']
    task.update(task_type='single_action',registration_kind='parameter',attempts=['a1'])
    r['actions']['a1']['parameter_findings']=[]
    result={'name':'查看选项','status':'done','evidence':'原动作图与后续补录支持同一参数对象'}
    with pytest.raises(ValueError,match='参数任务缺少已登记参数事实，需先补观察登记'):
        task_result_review.apply(r,{},'查看选项',result,'review')
    task_settlement.store_findings(task,q['task_update']['findings'],{'source_call':'fact-author'})
    task_result_review.apply(r,{},'查看选项',result,'review')
    assert task['status']=='done' and task['findings']['样式']['source']['source_call']=='fact-author'
    assert r['actions']['a1']['parameter_findings']==[]
