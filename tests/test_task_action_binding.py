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
    reply={'task_update':{'findings':[],'next_action':None},
           'action_result':{'exception':'none','description':'打开样式菜单；未切换设置'},
           'exploration_update':{'attempt_status':'executed'}}
    receipt={'exit_code':0,'executed_steps':[{'action':'click'}]}
    region['actions']['a1']={'operation':'click','control':'c1','delivery':'executed_receipt_zero','result':reply['action_result']}
    return region,binding,reply,receipt

def settle(region,binding,reply,receipt):
    task_settlement.settle_task(region,binding,reply,'a1',{region['id']:region},receipt=receipt)
    return region['tasks']['查看选项']

def test_recorded_bound_action_finishes_exploration_without_model_status():
    r,b,q,receipt=fixture();q['action_result']['exception']='blocking_popup'
    t=settle(r,b,q,receipt)
    assert t['status']=='done'
    assert t['completion_basis']['rule']=='bound_action_recorded'
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

def test_replacement_completion_action_preserves_original_execution():
    r,b,q,receipt=fixture()
    q['task_update']['next_action']={'region':'设置','control':'其他入口','action':'click','reason':'原入口仅聚焦；需要点击实际展开入口'}
    t=settle(r,b,q,receipt)
    assert t['status']=='pending'
    assert t['control']=='c1'
    assert t['completion_action']['control']=='c2'
    assert 'a1' in r['actions'] and 'a1' in t['attempts']
    r['actions']['a2']={**r['actions']['a1'],'control':'c2'}
    q['task_update']['next_action']=None
    task_settlement.settle_task(r,{**b,'control_ref':'c2'},q,'a2',{'r1':r},receipt=receipt)
    assert t['status']=='done' and t['completion_basis']['attempt']=='a2'

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
    assert set(fields['task_update']['properties'])=={'findings','next_action'}
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
