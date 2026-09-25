import pytest
from tests.test_recovery_discovery import mod,ROOT


def region():
    return {'id':'r','tasks':{
        '字段参数':{'control':'field','handling':'explore','status':'pending','task_type':'parameter','action':'click','reason':'了解取值','attempts':[]},
        '刻度反馈':{'control':'dial','handling':'explore','status':'pending','task_type':'single_action','action':'click','reason':'观察选择反馈','attempts':[]},
        '另一入口':{'control':'other','handling':'explore','status':'pending','task_type':'single_action','action':'click','reason':'其他','attempts':[]}}}


def test_candidates_are_actual_control_goals():
    m=mod('related_task_results');r=region()
    assert [t['name'] for t in m.candidates(r,'dial','click','字段参数')]==['刻度反馈']
    assert [t['name'] for t in m.candidates(r,'field','click',None)]==['字段参数']


def test_same_evidence_completes_only_reported_related_task():
    m=mod('related_task_results');r=region()
    reply={'action_result':{'exception':'none'},'related_task_results':[{'name':'刻度反馈','evidence':'点击12后显示12并切换分钟盘'}]}
    m.apply(r,{'control_ref':'dial'},reply,'a','call',['刻度反馈'])
    assert r['tasks']['刻度反馈']['status']=='done'
    assert r['tasks']['刻度反馈']['attempts']==['a']
    assert r['tasks']['字段参数']['status']=='pending'
    with pytest.raises(ValueError):m.apply(r,{'control_ref':'other'},reply,'a','call',['刻度反馈'])


def test_request_exposes_only_candidate_names_in_result_schema():
    m=mod('update_step')
    q=m.build_update_request(ROOT,{'同次动作可核对的单步任务':[{'name':'刻度反馈','reason':'观察反馈'}]},[])
    assert q['response_schema']['properties']['related_task_results']['items']['properties']['name']['enum']==['刻度反馈']


def test_unobserved_or_exceptional_related_tasks_stay_pending():
    m=mod('related_task_results');r=region()
    m.apply(r,{'control_ref':'dial'},{'action_result':{'exception':'none'}},'a','call',[])
    assert r['tasks']['刻度反馈']['status']=='pending'
    reply={'action_result':{'exception':'external_app'},'related_task_results':[{'name':'刻度反馈','evidence':'打开外部应用'}]}
    with pytest.raises(ValueError):m.apply(r,{'control_ref':'dial'},reply,'a','call',['刻度反馈'])
    assert r['tasks']['刻度反馈']['status']=='pending'


def test_parameter_target_cannot_be_completed_as_related_single_action():
    m=mod('related_task_results');r=region()
    reply={'action_result':{'exception':'none'},'related_task_results':[{'name':'字段参数','evidence':'点击已投递'}]}
    with pytest.raises(ValueError):m.apply(r,{'control_ref':'field'},reply,'a','call',['字段参数'])
    assert r['tasks']['字段参数']['status']=='pending'


def test_parameter_can_share_observed_result_with_parameter_facts():
    m=mod('related_task_results');r=region()
    fact={'name':'可选值','description':'显示两项','domain':{'type':'enum','values':['Digital','Analog'],'min':None,'max':None},'conditions':[],'evidence':'菜单显示两项'}
    reply={'action_result':{'exception':'none'},'related_task_results':[{'name':'字段参数','evidence':'选择Analog后菜单关闭且父界面显示Analog','findings':[fact]}]}
    m.apply(r,{'control_ref':'field'},reply,'a','call',['字段参数'])
    t=r['tasks']['字段参数']
    assert t['status']=='done' and t['attempts']==['a']
    assert t['findings']['可选值']['source']['attempt']=='a'
    assert t['completion_basis']['source_call']=='call'
    assert r['tasks']['刻度反馈']['status']=='pending'


def test_region_scroll_can_settle_related_scroll_goal_but_not_other_operations():
    m=mod('related_task_results');r=region()
    r['tasks']['列表调查']={'control':None,'handling':'explore','status':'pending','task_type':'scroll','action':'scroll','reason':'确认后续结构','attempts':[]}
    assert [t['name'] for t in m.candidates(r,None,'scroll',None)]==['列表调查']
    assert m.candidates(r,None,'scroll','列表调查')==[]
    assert m.candidates(r,None,'back',None)==[]
    reply={'action_result':{'exception':'none'},'related_task_results':[{'name':'列表调查','evidence':'滚动后仍为相同选项结构，无新增入口','findings':[]}]}
    for binding,operation in [({'region_ref':'other','control_ref':None},'scroll'),({'region_ref':'r','control_ref':None},'back')]:
        with pytest.raises(ValueError):m.apply(r,binding,reply,'a','call',['列表调查'],operation=operation)
    m.apply(r,{'region_ref':'r','control_ref':None},reply,'a','call',['列表调查'],operation='scroll')
    assert r['tasks']['列表调查']['status']=='done'
    assert r['tasks']['列表调查']['attempts']==['a']
    assert r['tasks']['字段参数']['status']=='pending'
