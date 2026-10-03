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


def test_execution_evidence_does_not_require_a_supported_task_or_control():
    _,r,_=alarm_region();m=mod('region_functions');r['tasks']['时间']['attempts']=['proposal']
    r['actions']={'proposal':{'control':None,'delivery':'dispatching','result':{'description':'未执行提案'}},
        'other':{'control':None,'delivery':'executed_receipt_zero','result':{'description':'无本轮已支持任务引用'}}}
    rows=m.action_results(r)
    assert [row['动作记录'] for row in rows]==['other']
    assert rows[0]['关联任务']==[] and rows[0]['控件关联']=='未确认'


def test_confirmed_action_without_catalog_task_is_preserved_and_invalidates_review():
    _,r,_=alarm_region();m=mod('region_functions');cid=r['tasks']['时间']['control']
    r['tasks']={};r['actions']={}
    before=m.signature(r)
    r['actions']['a21']={'control':cid,'operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'对话框关闭，内容恢复可见','evidence':'实际后图','exception':'none'}}
    row=m.action_results(r)[0]
    assert row['控件']==r['controls'][cid]['name'] and row['关联任务']==[]
    assert m.signature(r)!=before


def test_action_scope_and_destination_are_context_not_automatic_navigation_classification():
    _,r,_=alarm_region();m=mod('region_functions');cid=r['tasks']['时间']['control']
    r['actions']={'a8':{'control':cid,'operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'返回列表并回显新标签','evidence':'实际后图','exception':'none'},
        'interactive_regions':['list'],'region_changes':[{'region':'list','state':'changed_interactive','evidence':'列表回显新标签'}]}}
    r['transitions']=[{'source_control':cid,'target_region':'list','attempt':'a8','relation':'observed_interactive_candidate'}]
    records={r['id']:r,'list':{'id':'list','name':'对象列表','description':'可见对象摘要'}}
    q=json.loads(m.request(ROOT,r,{},records)['user_prompt']);row=q['同区块已执行动作结果'][0]
    assert row['动作后可交互区块'][0]['名称']=='对象列表'
    assert row['动作后可交互区块'][0]=={'区块':'list','名称':'对象列表'}
    assert row['区块变化'][0]['state']=='changed_interactive'
    assert row['观察到的区块连接'][0]['relation']=='observed_interactive_candidate'
    assert 'region_role' not in row and '仅导航' not in row
    signature=m.signature(r,records);records['list']['description']='摘要结果已展开'
    assert m.signature(r,records)==signature


def test_task_and_attribute_provenance_remain_explicit_in_function_request():
    _,r,_=alarm_region();m=mod('region_functions')
    r['tasks']['时间']['source_call']='0010'
    q=json.loads(m.request(ROOT,r,{})['user_prompt'])
    task=next(t for t in q['已登记操作'] if t['任务']=='时间')
    assert task['任务提出调用']=='0010'
    assert task['依据时态']=='历史记录：其中当前、本轮、未验证均指对应观察时刻，须与后续动作和恢复观察合看'
    fact=q['已记录属性（待甄别）']['时间']['时间 / 时间']
    expected=r['tasks']['时间']['findings']['时间']
    assert fact['事实来源']==expected.get('sources',[expected['source']])


def test_failed_result_is_retained_without_claiming_success_and_no_result_is_accounted_for():
    _,r,_=alarm_region();m=mod('region_functions')
    r['actions']={'a1':{'control':None,'delivery':'executed_receipt_zero','result':{'description':'对话框仍在','exception':'unexpected_result'}},
        'a2':{'control':None,'delivery':'dispatching','result':{'description':'拟打开'}},
        'a3':{'control':None,'delivery':'executed_receipt_zero','result':{}}}
    q=json.loads(m.request(ROOT,r,{})['user_prompt'])
    assert [x['动作记录'] for x in q['同区块已执行动作结果']]==['a1']
    assert q['同区块已执行动作结果'][0]['异常']=='unexpected_result'
    audit=q['动作证据覆盖']
    assert audit['账本动作数']==3 and audit['已提供动作']==['a1']
    assert {x['动作记录'] for x in audit['未提供结果']}=={'a2','a3'}
    assert all(x['原因'] for x in audit['未提供结果'])


def test_incoming_result_has_traceable_identity_and_does_not_grant_local_task_ownership():
    _,r,_=alarm_region();m=mod('region_functions')
    r['reached_by']=[{'source_region':'source','source_control':None,'attempt':'a21'}]
    action={'control':None,'operation':'click','delivery':'executed_receipt_zero',
        'association':{'target':'关闭按钮','status':'unconfirmed'},
        'evidence':{'selection_call':'21','result_call':'22','before_observation':'before','after_observation':'after'},
        'result':{'description':'返回并显示内容','exception':'none','evidence':'真实后图'}}
    records={'source':{'id':'source','name':'浮层','controls':{},'tasks':{},'actions':{'a21':action}},r['id']:r}
    before=deepcopy(records);row=m.incoming_results(r,records)[0]
    assert row['动作记录']=='a21' and row['结果调用']=='22'
    assert row['控件关联']=='未确认' and row['来源任务']==[]
    assert row['动作后观察']=='after' and row['结果']=='返回并显示内容'
    assert records==before
