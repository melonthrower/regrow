"""Request-local rule selection and lossless display references."""
from copy import deepcopy
import json
from tests.test_recovery_discovery import mod, ROOT

def test_bound_selection_survives_late_scope_and_correction(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    module = mod('context_scope')
    task = {'task_type': 'parameter', 'prepares': {'region': 'r', 'task': 'parent'}}
    q = {'role': 'observation_update', 'source': {'region': 'r', 'task_name': 'prepare'}, 'work_context': {'kind': 'update', 'region': 'r', 'task': None}, 'task_update_candidates': []}
    selected = module.rule_selection(q, tasks=[task], binding={'preparatory_action': True})
    assert selected['registration_kinds'] == ['parameter'] and selected['preparatory_action']
    assert 'parameter_facts_needed' not in selected
    q['context_scope'] = {'selection': selected}
    records = {'r': {'tasks': {'other': {'task_type': 'parameter'}}, 'controls': {}}}
    scope = module.for_request(q, records, {'active_task': {'region': 'r', 'name': 'other'}})
    assert scope['tasks'] == [] and scope['selection'] == selected
    assert module.rule_selection({'role': 'step_correction', 'original_request': q}) == selected
    assert module.rule_selection({'role': 'observation_update'}, tasks=[])['registration_kinds'] == []
    assert module.rule_selection({'role': 'observation_update'})['registration_kinds'] is None
    assert module.rule_selection({'stage': 'action_selection'}, tasks=[])['role'] == 'action_selection'

def test_global_and_local_discovery_allow_joint_registration(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    rules = mod('prompt_rules')
    global_parts = rules.parts(ROOT, 'observation', selection={'mode': 'global'})
    local_parts = rules.parts(ROOT, 'observation', selection={'mode': 'local'})
    g = '\n'.join((p['text'] for p in global_parts))
    l = '\n'.join((p['text'] for p in local_parts))
    assert 'click_bbox' in g and 'click_bbox' in l
    assert 'region_index' in g and 'context_matches' in g
    assert '信息展示也是用途' in g
    assert 'previous_name' in l and '两个框无需相互包含' in g

def test_diagnostic_reference_requires_exact_pointer_value():
    m = mod('prompt_material')
    candidate = {'a/b': {'~key': [False, 0, None]}, 'text': 'full answer'}
    value = {'被拒绝回复': candidate, '具体校验错误': {'errors': [{'path': '/a~1b/~0key/0', 'actual': False, 'repair': 'correct'}, {'path': '/a~1b/~0key/0', 'actual': 0}, {'path': '/missing', 'actual': None}, {'path': '', 'actual': candidate}]}}
    before = deepcopy(value)
    got = m.view(value, {'role': 'step_correction'})
    errors = got['具体校验错误']['errors']
    assert errors[0]['actual'] == {'候选引用': '被拒绝回复#/a~1b/~0key/0'}
    assert errors[1]['actual'] == 0 and errors[2]['actual'] is None
    assert errors[3]['actual'] == {'候选引用': '被拒绝回复（根节点）'}
    assert got['被拒绝回复'] == candidate and value == before

def test_summary_shares_same_source_body_but_keeps_task_conditions():
    m = mod('prompt_material')
    action = {'动作记录': 'a1', '结果': 'opened', '动作后观察': 'u1'}
    supports = [{'区块': 'r1', '任务': 'one', 'conditions': [], '动作结果': [deepcopy(action)]}, {'区块': 'r1', '任务': 'two', 'conditions': ['enabled'], '动作结果': [deepcopy(action)]}, {'区块': 'r2', '任务': 'three', '动作结果': [deepcopy(action)]}]
    value = {'按本地参数任务披露的支持': supports}
    before = deepcopy(value)
    got = m.view(value, {'role': 'function_registration'})['按本地参数任务披露的支持']
    assert got[0]['动作结果'] == [action] and got[0]['conditions'] == []
    assert got[1]['动作结果'][0]['证据正文'].startswith('见按本地') and got[1]['conditions'] == ['enabled']
    assert got[2]['动作结果'] == [action] and value == before

def test_empty_material_still_has_purpose_and_all_questions():
    q = {'role': 'task_proposal', 'work_context': {'kind': 'task_proposal', 'reason': 'Check newly discovered controls'}, 'user_prompt': json.dumps({'本轮工作': {'范围': 'Panel'}, 'unknown_evidence': False})}
    text = mod('history_disclosure').project(q)['user_prompt']
    assert 'Check newly discovered controls' in text and '问题 1' in text and ('问题 2' in text)
    assert 'unknown_evidence' in text and 'false' in text

def test_identity_history_different_image_cannot_be_merged():
    m = mod('control_history_context')
    old = {'icon_description': 'same', 'evidence': {'observation': 'old'}, 'crop': 'a.png'}
    region = {'controls': {'c': {'name': 'Control', 'observations': [old, deepcopy(old)]}}}
    key = '历史身份观察（首末及最近明确字段，非当前可见性证明）'
    assert '观察正文' in m.describe(region, 'c')[key][1]
    region['controls']['c']['observations'][1]['crop'] = 'b.png'
    assert '观察正文' not in m.describe(region, 'c')[key][1]

def test_parameter_baseline_only_shares_equal_fields_of_same_source():
    from tests.test_current_page_context import action
    m = mod('page_history')
    event = action('before', 'after', ['r'], ['r'], 'c')
    event['parameter_findings'] = [{'name': 'limit', 'domain': {'max': 0}, 'evidence': 'sample', 'conditions': []}]
    records = {'r': {'id': 'r', 'name': 'Panel', 'controls': {'c': {'name': 'Field'}}, 'actions': {'a1': event}, 'tasks': {'inspect': {'status': 'pending', 'control': 'c', 'attempts': ['a1']}}}}
    baseline = {'region': 'r', 'task': 'inspect', 'finding': 'limit', 'source': {'region': 'r', 'task_region': 'r', 'attempt': 'a1'}, 'displayed': {'domain': {'max': False}, 'evidence': 'sample'}}
    state = {'working_region': 'r', 'active_task': {'region': 'r', 'name': 'inspect'}}
    got = m.build(records, state, displayed_findings=[baseline])['events']['a1']['已记录参数事实'][0]
    assert got['domain'] == {'max': 0} and got['conditions'] == []
    assert got['相同字段来源']['字段'] == ['evidence']
    baseline['source']['region'] = 'other'
    got = m.build(records, state, displayed_findings=[baseline])['events']['a1']['已记录参数事实'][0]
    assert got == event['parameter_findings'][0]

def test_identity_index_keeps_latest_semantic_doubt_and_source_without_geometry():
    from copy import deepcopy
    from regrow.records import context_scope as context_scope
    from regrow.records import control_history_context as control_history_context
    old = {'uncertainty': 'group covered by independent control', 'image_quality': 'occluded', 'image_quality_reason': 'overlay', 'evidence': {'source_call': 'old', 'observation': 'o'}, 'bbox': {'left': 1}, 'click_bbox': None}
    region = {'id': 'r', 'name': 'panel', 'controls': {'c': {'name': 'group', 'observations': [old, {'visual_only': True, 'uncertainty': ''}]}}, 'tasks': {}, 'actions': {}}
    before = deepcopy(region)
    for detailed in (False, True):
        row = context_scope.identity(region, 'c', detailed=detailed)
        doubt = row['历史观察中的不确定性'][0]
        assert doubt['uncertainty'] == old['uncertainty'] and doubt['evidence'] == old['evidence']
        assert doubt['image_quality_reason'] == 'overlay' and 'bbox' not in doubt
    assert region == before
    region['controls']['c']['observations'].append({'uncertainty': '', 'image_quality': 'clear', 'evidence': {'source_call': 'later'}})
    assert '历史观察中的不确定性' not in context_scope.identity(region, 'c')
    assert len(control_history_context.uncertain_observations(region['controls']['c'], latest_only=False)) == 1

def test_old_identity_doubt_is_disclosed_with_later_answer_and_conditions():
    from regrow.records import context_scope as context_scope
    region = {'id': 'r', 'name': 'timer', 'controls': {'c': {'name': 'start', 'observations': [{'uncertainty': 'hover did not identify purpose', 'evidence': {'source_call': '1'}}]}}, 'tasks': {'start': {'control': 'c', 'action': 'click', 'status': 'done', 'handling': 'explore', 'conditions': ['nonzero duration'], 'knowledge': 'starts countdown', 'attempts': ['a2']}}, 'actions': {'a2': {'control': 'c', 'operation': 'click', 'delivery': 'executed_receipt_zero', 'conditions': ['nonzero duration'], 'knowledge': 'starts countdown', 'result': {'exception': 'none', 'description': 'running countdown and pause button', 'evidence': 'after'}, 'evidence': {'result_call': '2'}}}}
    for detailed in (False, True):
        row = context_scope.identity(region, 'c', detailed=detailed)
        assert row['历史观察中的不确定性'][0]['evidence'] == {'source_call': '1'}
        assert row['关联任务'][0]['knowledge'] == 'starts countdown'
        assert row['关联任务'][0]['conditions'] == ['nonzero duration']
        assert row['实际尝试与来源']['a2']['来源'] == {'result_call': '2'}
