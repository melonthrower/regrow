from copy import deepcopy
from types import SimpleNamespace
from tests.test_recovery_discovery import mod


def test_correction_discloses_effective_equivalent_status(monkeypatch):
    m=mod('repair_stages')
    representative={'control':'c','status':'done','handling':'explore','reason':'代表性验证','result_evidence':'已选择 Silent','action':'click'}
    alias={'control':'c','status':'pending','handling':'equivalent','equivalent_to':'选择代表项','reason':'同类入口','action':'click'}
    records={'r':{'name':'声音','description':'列表','controls':{'c':{'name':'声音项'}},'tasks':{'选择代表项':representative,'另一个名称':alias}}}
    before=deepcopy(records)
    original=m.helper
    monkeypatch.setattr(m,'related',lambda *a:deepcopy(records))
    monkeypatch.setattr(m,'helper',lambda name:SimpleNamespace(load=lambda *a:(None,records,{})) if name=='discovery_step' else original(name))
    result=m.context(None,{'stage':'action','request':{'source':{'region':'r'},'user_prompt':''}})
    task=result['区块'][0]['任务'][1]
    assert task['状态']=='done'
    assert task['覆盖任务']=='选择代表项'
    assert task['处理方式']=='equivalent'
    assert any('已选择 Silent' in fact for fact in task['尝试事实'])
    assert records==before

    alias['registration_kind']='entry'
    result=m.context(None,{'stage':'action','request':{'source':{'region':'r'},'user_prompt':''}})
    task=result['区块'][0]['任务'][1]
    assert task['状态']=='blocked' and task['覆盖任务']=='选择代表项'
    assert not any('已选择 Silent' in fact for fact in task['尝试事实'])


def test_exploration_tree_uses_representative_result():
    m=mod('region_tasks')
    region={'id':'r','name':'声音','controls':{},'tasks':{
        '选择代表项':{'handling':'explore','status':'done','result_evidence':'已选中Silent'},
        '同类选择':{'handling':'equivalent','equivalent_to':'选择代表项','status':'pending'}}}
    text=m.render(region)
    assert '同类选择：已完成\n  已选中Silent' in text
    assert '尚未执行' not in text


def test_alternative_action_can_complete_observed_goal():
    m=mod('region_tasks')
    owner={'id':'r','tasks':{'观察反馈':{'control':'icon','task_type':'single_action','attempts':[]}}}
    binding={'task_name':'观察反馈','preparatory_action':True,'control_ref':'row','region_ref':'r'}
    reply={'action_result':{'exception':'none'},'task_result':{'name':'观察反馈','status':'done','evidence':'操作后已看到目标状态图标；音频未验证','findings':[]}}
    m.settle_task(owner,binding,reply,'a')
    assert owner['tasks']['观察反馈']['status']=='done'
