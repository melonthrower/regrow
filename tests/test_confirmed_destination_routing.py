from copy import deepcopy
import pytest
from regrow.traversal.task_routing import advance
from regrow.records.object_store import Records,owned_controls,owned_tasks,owned_actions
from regrow.records.region_evidence import new_region
from regrow.records.tasks import read as task_value

def scene(status='done', preparation=False, target='r0002', entry_attempt='a1'):
    records=Records({rid:new_region(rid,rid) for rid in ['r0001','r0002']})
    source=records['r0001']
    owned_controls(source)['c0001']={'name':'按钮','entries':[{'region':target,'attempt':entry_attempt,'meaning':'展开目标'}]}
    owned_tasks(source)['功能探索']={'name':'功能探索','control':'c0001','task_type':'function','status':status}
    owned_actions(source)['a1']={'control':'c0001','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}
    before={'working_region':'r0001','region_path':['r0001'],'active_task':{'region':'r0001','name':'功能探索'}}
    state={'working_region':'r0001','interactive_regions':['r0001','r0002']}
    binding={'task_region':'r0001','task_name':'功能探索','control_ref':'c0001','preparatory_action':preparation}
    return records,before,state,binding

def test_confirmed_menu_is_working_surface_even_if_source_is_visible():
    records,before,state,binding=scene()
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0002'
    assert state['region_path']==['r0001','r0002']
    assert owned_tasks(records['r0001'])['功能探索']['status']=='done'
    assert not owned_tasks(records['r0002'])

@pytest.mark.parametrize('status,preparation', [('pending',False),('done',True)])
def test_pending_or_preparation_keeps_original_work(status,preparation):
    records,before,state,binding=scene(status,preparation)
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0001'
    if status=='pending':assert state['active_task']==before['active_task']

@pytest.mark.parametrize('target,attempt',[('r0001','a1'),('r0002','old')])
def test_local_control_relation_or_old_route_does_not_switch_work(target,attempt):
    records,before,state,binding=scene(target=target,entry_attempt=attempt)
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0001'

def test_source_disappeared_without_explicit_entry_preserves_fallback():
    records,before,state,binding=scene(entry_attempt='old')
    state['interactive_regions']=['r0002']
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0002'

@pytest.mark.parametrize('explicit_target', [False, True])
def test_actual_completion_target_routes_without_moving_original_task(explicit_target):
    records,before,state,binding=scene()
    owner=records['r0001']
    records['r0003']=new_region('r0003','实际操作区块')
    actual=records['r0003']
    owned_controls(actual)['c0001']=owned_controls(owner)['c0001']
    owned_actions(actual)['a1']=owned_actions(owner).pop('a1')
    task=owned_tasks(owner)['功能探索']
    if explicit_target:
        owned_controls(owner)['c_original']={'name':'原目标'}
        task.update(control='c_original',completion_action={'region':'r0003','control':'c0001'})
    before['region_path']=['r0001','r0003']
    state.update(working_region='r0003',interactive_regions=['r0003','r0002'])
    advance(records,before,state,'r0003',binding,'a1')
    assert state['working_region']=='r0002'
    assert state['region_path']==['r0001','r0003','r0002']
    assert owned_tasks(owner)['功能探索'] is task
    assert not owned_tasks(actual) and not owned_tasks(records['r0002'])
    assert task_value(task,'completion_basis')['destination_region']=='r0002'
    assert task_value(task,'visited_regions')==['r0003','r0002']

@pytest.mark.parametrize('operation', ['right_click','double_click','long_press','hover','input_text','drag'])
def test_confirmed_destination_works_for_other_control_operations(operation):
    records,before,state,binding=scene()
    owned_actions(records['r0001'])['a1'].update(operation=operation,text_delivered=True)
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0002'

@pytest.mark.parametrize('operation', ['right_click','double_click','long_press','hover','input_text','drag'])
def test_other_operations_do_not_gain_an_unconfirmed_fallback(operation):
    records,before,state,binding=scene(entry_attempt='old')
    owned_actions(records['r0001'])['a1'].update(operation=operation,text_delivered=True)
    state['interactive_regions']=['r0002']
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0001'
    assert task_value(owned_tasks(records['r0001'])['功能探索'],'visited_regions')==['r0002']

@pytest.mark.parametrize('change', ['other_control','unexecuted','exception'])
def test_mismatched_or_unsuccessful_action_does_not_route(change):
    records,before,state,binding=scene()
    action=owned_actions(records['r0001'])['a1']
    if change=='other_control':
        action['control']='other'
    elif change=='unexecuted':
        action['delivery']='not_executed'
    else:
        action['result']['exception']='blocking_popup'
    advance(records,before,state,'r0001',binding,'a1')
    assert state['working_region']=='r0001'
