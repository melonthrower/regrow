"""Outgoing rule scope: task facts/schema survive; unrelated rules do not leak."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def imports(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


@pytest.mark.parametrize('role,needed,unneeded', [
    ('action_selection', 'end_y<y', 'foreground.exception=blocking_popup'),
    ('observation_update', 'click_bbox', 'hotkey 使用'),
    ('observation', 'recovery_handoff', 'hotkey 使用'),
    ('task_proposal', '不为每个缺图控件强造任务', 'icon_bbox'),
    ('recovery', 'end_y<y', 'controls_complete'),
])
def test_stage_rules_follow_consumer_including_correction(role, needed, unneeded):
    original={'role':role, 'system_prompt':'任务专属规则', 'user_prompt':'{"任务":"保留"}',
              'fixed_parts':[], 'response_schema':{'type':'object'}, 'screenshots':['actual.png']}
    for request in (original, {**original,'role':'step_correction','original_request':original}):
        before=deepcopy(request)
        sent=mod('desktop_transport').prepare_request(ROOT,request)
        assert needed in sent['system_prompt'] and unneeded not in sent['system_prompt']
        assert '不要把tooltip登记成独立业务区块' in sent['system_prompt']
        assert sent['screenshots']==request['screenshots'] and sent['response_schema']==request['response_schema']
        assert request==before


def test_correction_references_only_exact_complete_shared_parts():
    common={'path':'common.prompt','text':'规则A\n\n必须保留权限'}
    original={'fixed_parts':[common,{'path':'variant.prompt','text':'不同规则'}]}
    q={'role':'step_correction', 'original_request':original,
       'fixed_parts':[common,{'path':'variant.prompt','text':'不同规则：新版'}],
       'system_prompt':'纠错规则\n\n'+common['text']+'\n\n不同规则：新版',
       'user_prompt':json.dumps({'原任务要求':'专属规则\n\n'+common['text']+'\n\n不同规则',
                                '原动态上下文':'事实与地图','被拒绝回复':{'reason':'规则A'}})}
    before=deepcopy(q);sent=mod('history_disclosure').project(q)
    assert common['text'] not in sent['user_prompt']
    assert common['text'] in sent['system_prompt'] and 'common.prompt' in sent['user_prompt']
    assert '专属规则' in sent['user_prompt'] and '不同规则' in sent['user_prompt']
    assert json.JSONDecoder().raw_decode(sent['user_prompt'])[0]['被拒绝回复']=={'reason':'规则A'}
    assert mod('history_disclosure').project(sent)==sent and q==before
    # Same words embedded in a larger clause must not be stripped.
    q['user_prompt']=json.dumps({'原任务要求':'补充：'+common['text']+'不适用于当前条件'})
    assert common['text'] in mod('history_disclosure').project(q)['user_prompt']


def test_parameter_reading_rules_require_actual_parameter_facts():
    helper=mod('history_context')
    empty=helper.task_goal({'reason':'观察入口','task_type':'entry'}, {})
    assert '原观察缺失字段' not in empty['历史阅读']
    assert '不推断成功' in empty['历史阅读']
    task={'reason':'参数','findings':{'value':{'description':'latest','observations':[{'description':'old'}]}}}
    full=helper.task_goal(task,{})
    assert '原观察缺失字段保持未知' in full['历史阅读']
    assert full['已有参数发现']['value']['description']=='latest'
    assert full['未关联动作的历史观察'][0]['description']=='old'


@pytest.mark.parametrize('judgment', [None, '图2中仍未输入'])
@pytest.mark.parametrize('parameters', [False, True])
def test_map_history_note_names_only_present_content(tmp_path, judgment, parameters):
    from tests.test_current_page_context import case
    records,state,frame=case(tmp_path)
    task={'reason':'确认入口'}
    if judgment:task['result_evidence']=judgment
    if parameters:task['findings']={'value':{'description':'历史值'}}
    goal=mod('history_context').task_goal(task,records)
    request={'user_prompt':json.dumps({'任务目标':goal}), 'screenshots':[str(frame)]}
    mod('page_context').attach(request,records,state,usage='before_action')
    value=json.loads(request['user_prompt'])['任务目标']
    assert ('参数摘要' in value['历史阅读']) == parameters
    assert ('当时判断中的图号' in value['历史阅读']) == bool(judgment)
    if judgment or parameters:assert '不指本轮附图' in value['历史阅读']
    mod('page_context').attach(request,records,state,usage='before_action')
    assert json.loads(request['user_prompt'])['任务目标']['历史阅读']==value['历史阅读']
