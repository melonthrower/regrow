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


def test_executed_unconfirmed_task_action_keeps_facts_without_owner_claim():
    _,r,_=alarm_region();m=mod('region_functions')
    r['tasks']['时间']['attempts']=['a8']
    fact={'name':'代表配置','description':'选1m后显示00:01:00','evidence':'实际后图'}
    r['actions']={'a8':{'control':None,'operation':'click','delivery':'executed_receipt_zero',
        'association':{'status':'unconfirmed','target':'1m预设'},'parameter_findings':[fact],
        'evidence':{'selection_call':'0010','result_call':'0011'},
        'result':{'description':'变为00:01:00，播放可用','evidence':'真实前后图','exception':'none'}}}
    before=deepcopy(r)
    row=m.action_results(r)[0]
    assert row['动作记录']=='a8' and row['控件']=='' and row['控件关联']=='未确认'
    assert row['提案目标']=='1m预设' and row['关联任务']==['时间']
    assert row['已记录参数事实']==[fact] and row['结果调用']=='0011'
    assert r==before
    signature=m.signature(r)
    r['actions']['a8']['parameter_findings'][0]['description']='选2m后显示00:02:00'
    assert m.signature(r)!=signature


def test_unconfirmed_proposal_or_unrelated_action_does_not_enter_function_evidence():
    _,r,_=alarm_region();m=mod('region_functions');r['tasks']['时间']['attempts']=['proposal']
    r['actions']={'proposal':{'control':None,'delivery':'dispatching','result':{'description':'未执行提案'}},
        'other':{'control':None,'delivery':'executed_receipt_zero','result':{'description':'无本轮已支持任务引用'}}}
    assert m.action_results(r)==[]
