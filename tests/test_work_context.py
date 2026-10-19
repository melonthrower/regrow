"""Work purpose survives the native request chain without creating task records."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import ROOT
from tests.test_context_relevance import records, task, effort

@pytest.fixture(autouse=True)
def path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))

def case():
    rs = records()
    rs['r1']['tasks'] = {'Goal': {**task(), 'control': 'cr1', 'handling': 'explore', 'registration_kind': 'parameter', 'reason': 'Which options are available?', 'attempts': ['a1'], 'status': 'blocked'}, 'Unrelated': {**task(), 'control': 'cr1', 'handling': 'explore', 'reason': 'OLD_UNRELATED_QUESTION', 'attempts': ['a2'], 'status': 'pending'}}
    rs['r1']['actions'] = {a: effort('cr1', p) for (a, p) in [('a1', 'goal evidence'), ('a2', 'UNRELATED_EFFORT'), ('a3', 'latest result')]}
    state = {'working_region': 'r1', 'interactive_regions': ['r1'], 'observation': {'id': 'now', 'image': 'frame.png', 'control_refs': ['cr1']}, 'active_task': {'region': 'r1', 'name': 'Unrelated'}, 'last_action_result': {'region': 'r1', 'action': 'a3'}}
    return (rs, state)

def test_inventory_purpose_reaches_final_map_without_inheriting_old_active_task():
    from regrow.traversal import task_proposer as task_proposer
    from regrow.records import page_context as page_context
    (rs, state) = case()
    before = deepcopy((rs, state))
    q = task_proposer.plan_request(ROOT, rs, state, 'r1')
    standalone = deepcopy(q['page_history']['events'])
    page_context.attach(q, rs, state)
    page_context.refresh(q)
    assert set(standalone) == set(q['page_context']['history']['events']) == {'a3'}
    assert q['work_context']['kind'] == 'task_proposal' and q['work_context']['task'] is None
    assert 'UNRELATED_EFFORT' not in q['user_prompt']
    assert {t['name'] for t in json.loads(q['user_prompt'])['已有任务']} == {'Goal', 'Unrelated'}
    assert 'Goal' in q['user_prompt'] and (rs, state) == before

def test_explicit_old_question_review_keeps_its_evidence_and_original_owner():
    from regrow.traversal import task_proposer as task_proposer
    from regrow.records import page_context as page_context
    (rs, state) = case()
    rs['r1']['task_inventory'] = {'review': {'kind': 'entry_observation', 'task': 'Goal', 'reason': 'Register new evidence for Goal'}}
    q = task_proposer.plan_request(ROOT, rs, state, 'r1')
    page_context.attach(q, rs, state)
    assert q['work_context']['task'] == {'region': 'r1', 'name': 'Goal'}
    assert set(q['page_context']['history']['events']) == {'a1', 'a3'}
    assert 'UNRELATED_EFFORT' not in q['user_prompt']

def test_initial_discovery_and_task_supplement_have_explicit_purposes():
    from regrow.traversal import work_context as work_context
    q = {'stage': 'discovery', 'user_prompt': '{}'}
    work_context.attach(q, {}, {})
    assert q['work_context']['kind'] == 'locate' and q['work_context']['task'] is None
    assert json.loads(q['user_prompt'])['本轮工作']['范围'] == '当前前景'
    (rs, state) = case()
    original = {'stage': 'action_selection', 'source': {'region': 'r2', 'task_region': 'r1', 'task_name': 'Goal'}}
    work = work_context.observation_work(original, rs, state, 'Locate the original selector')
    assert work['kind'] == 'locate' and work['task'] == {'region': 'r1', 'name': 'Goal'}
    assert work_context.describe(work, rs)['原问题'] == 'Which options are available?'

def test_broken_task_reference_is_disclosed_without_falling_back_to_other_task():
    from regrow.records import page_history as page_history
    (rs, state) = case()
    q = {'stage': 'action_selection', 'source': {'region': 'r1', 'task_name': 'Missing'}, 'user_prompt': '{}'}
    page_history.attach(q, rs, state)
    assert q['work_context']['task']['name'] == 'Missing'
    assert '关联缺口' in json.loads(q['user_prompt'])['本轮工作']
    assert 'UNRELATED_EFFORT' not in q['user_prompt']

def test_repair_refresh_keeps_original_review_purpose_and_scope_contract(monkeypatch):
    from regrow.traversal import task_proposer as task_proposer
    from regrow.traversal import repair_stages as repair_stages
    from regrow.traversal import discovery_step as discovery_step
    from regrow.traversal import step_repair as step_repair
    (rs, state) = case()
    q = task_proposer.TaskProposer.request(ROOT, rs, state, 'r1', scope_review=True)
    assert q['work_context']['kind'] == 'scope_review'
    assert json.loads(q['user_prompt'])['当前任务后续观察']['任务'] == 'Unrelated'
    original = deepcopy(q['work_context'])
    state['working_region'] = 'r2'
    state['active_task'] = {'region': 'r1', 'name': 'Goal'}
    monkeypatch.setattr(discovery_step, 'load', lambda run: (None, rs, state))
    helper = repair_stages.helper
    monkeypatch.setattr(repair_stages, 'helper', lambda name: discovery_step if name == 'discovery_step' else helper(name))
    job = {'stage': 'task_proposal', 'request': q, 'history': [], 'error': 'repair this scope review'}
    refreshed = repair_stages.refresh(ROOT, 'unused', job)
    assert refreshed['work_context'] == original and refreshed['task_scope_review']
    assert json.loads(refreshed['user_prompt'])['当前任务后续观察']['任务'] == 'Unrelated'
    assert {t['name'] for t in json.loads(refreshed['user_prompt'])['已有任务']} == {'Goal', 'Unrelated'}
    corrected = step_repair.request(ROOT, {**job, 'request': refreshed}, {})
    assert corrected['work_context'] == corrected['original_request']['work_context'] == original

def test_normal_inventory_drops_visibility_reports_but_targeted_review_keeps_them():
    from regrow.traversal import task_proposer as task_proposer
    (rs, state) = case()
    rs['r1']['actions']['a3']['region_changes'] = [{'region': 'r1', 'state': 'retained_interactive', 'evidence': 'VISIBILITY_DETAIL'}]
    q = task_proposer.plan_request(ROOT, rs, state, 'r1')
    assert 'latest result feedback' in q['user_prompt'] and 'VISIBILITY_DETAIL' not in q['user_prompt']
    rs['r1']['task_inventory'] = {'review': {'kind': 'entry_observation', 'task': 'Goal', 'reason': 'Need comparison'}}
    q = task_proposer.plan_request(ROOT, rs, state, 'r1')
    assert 'VISIBILITY_DETAIL' in q['user_prompt']

def test_normal_update_and_its_supplement_keep_task_and_actual_action(tmp_path, monkeypatch):
    from regrow.traversal import work_context as work_context
    from regrow.traversal import repair_stages as repair_stages
    from regrow.traversal import discovery_step as discovery_step
    (rs, state) = case()
    original = {'stage': 'observation_update', 'source': {'region': 'r2', 'task_region': 'r1', 'task_name': 'Goal', 'attempt': 'a4'}, 'user_prompt': json.dumps({'实际入口': 'Privacy', '实际动作': [{'action': 'click', 'target': 'Privacy'}], '准备动作说明': 'Preparation for Goal'}), 'region_names': {}}
    work_context.attach(original, rs, state)
    view = json.loads(original['user_prompt'])['本轮工作']
    assert original['work_context']['kind'] == 'update'
    assert view['处理'] == '登记实际动作结果' and view['本步边界']
    original['user_prompt'] += '\n\n本轮遍历允许范围：测试实例\n截图坐标说明：1280×800'
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, rs, state))
    helper = repair_stages.helper
    monkeypatch.setattr(repair_stages, 'helper', lambda name: discovery_step if name == 'discovery_step' else helper(name))
    q = repair_stages.update_observation_request(ROOT, tmp_path, {'stage': 'update', 'request': original, 'attempt': 'a4', 'observation_question': 'Which panel belongs to Goal?'}, tmp_path / 'later.png')
    assert q['source'] == original['source']
    assert q['work_context']['task'] == {'region': 'r1', 'name': 'Goal'}
    assert q['work_context']['kind'] == 'step_observation' and q['work_context']['attempt'] == 'a4'
    assert json.loads(q['user_prompt'])['原实际动作']['实际入口'] == 'Privacy'
    assert q['screenshots'] == [str(tmp_path / 'action_attempts/a4/before.png'), str(tmp_path / 'action_attempts/a4/after.png'), str(tmp_path / 'later.png')]

def test_scheduler_scope_review_matches_direct_entry_and_keeps_recovery_observation():
    from regrow.traversal import action_proposer as action_proposer
    from regrow.traversal import task_proposer as task_proposer
    (rs, state) = case()
    state.update(exception='blocking_popup', recovery_handoff='recovered original task')
    q = action_proposer.render_work(ROOT, rs, state, {'kind': 'scope_review', 'region': 'r1', 'working_region': 'r1', 'reason': 'review scope'})
    direct = task_proposer.TaskProposer.request(ROOT, rs, state, 'r1', scope_review=True)
    for key in ('当前任务后续观察', '已有任务'):
        assert json.loads(q['user_prompt'])[key] == json.loads(direct['user_prompt'])[key]
    assert q['work_context']['kind'] == 'scope_review'

def test_attach_to_readable_request_keeps_scope_suffix_and_single_work():
    import json
    from regrow.prompts import history_disclosure as history_disclosure
    from regrow.traversal import work_context as work_context
    q = history_disclosure.project({'role': 'task_proposal', 'user_prompt': json.dumps({'已有材料': 'Keep'}) + '\n原范围说明'})
    work = {'kind': 'task_proposal', 'region': 'r1', 'task': None, 'reason': 'Check current controls'}
    work_context.attach(q, {'r1': {'name': 'Nav'}}, {}, work)
    (value, end) = json.JSONDecoder().raw_decode(q['user_prompt'])
    assert value['已有材料'] == 'Keep' and q['user_prompt'][end:] == '\n原范围说明'
    assert value['本轮工作']['目的'] == 'Check current controls'
