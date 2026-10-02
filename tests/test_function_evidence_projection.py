import json
from copy import deepcopy
from tests.test_recovery_discovery import mod
from tests.test_region_function_inventory import ROOT, alarm_region, reply


def test_destination_handoff_preserves_actual_result():
    t={'task_type':'single_action','control':'ok','status':'done','result_evidence':'选择器关闭，背景由白色变深色'}
    records={'picker':{'name':'选择器','tasks':{'确认':t},'actions':{'a8':{'operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}}},
             'canvas':{'name':'画布','tasks':{},'task_inventory':{'inventory':'complete'},'controls':{}}}
    state={'interactive_regions':['canvas']}
    mod('task_routing').advance(records,{},state,'picker',{'task_name':'确认','control_ref':'ok'},'a8')
    assert t['result_evidence']=='选择器关闭，背景由白色变深色'
    assert t['completion_basis']['destination_region']=='canvas'


def test_completed_task_attempt_remains_in_function_input():
    _,r,_=alarm_region();m=mod('region_functions');cid=r['tasks']['时间']['control']
    r['tasks']['时间']['attempts']=['a8']
    r['actions']={'a8':{'control':cid,'operation':'click','delivery':'executed_receipt_zero','evidence':{'result_call':'0025'},
        'result':{'description':'选择器关闭，背景变深色','evidence':'实际前后图','exception':'none'}}}
    rows=json.loads(m.request(ROOT,r,{})['user_prompt'])['同区块已执行动作结果']
    assert rows[0]['结果']=='选择器关闭，背景变深色'
    assert rows[0]['动作记录']=='a8' and rows[0]['结果调用']=='0025'
    assert rows[0]['关联任务']==['时间']


def test_changed_observation_fact_invalidates_review_but_repeated_fact_does_not():
    _,r,_=alarm_region();m=mod('region_functions');cid=r['tasks']['时间']['control']
    r['controls'][cid]['observations']=[{'state':'未操作','evidence':{'source_call':'0010'}}]
    m.register(r,reply(),'catalog')
    r['controls'][cid]['observations'].append({'state':'已确认','evidence':{'source_call':'0025'}})
    assert not m.review_current(r)
    current=m.signature(r)
    r['controls'][cid]['observations'].append({'state':'已确认','evidence':{'source_call':'0099'}})
    assert m.signature(r)==current
    request=json.loads(m.request(ROOT,r,{})['user_prompt'])
    assert request['已观察控件'][0].get('观察出处') or any(c.get('观察出处') for c in request['已观察控件'])
