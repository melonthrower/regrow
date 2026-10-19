from regrow.tools import branch_switch as _test_branch_switch
'Information survives display, binding, settlement and the next work choice.'
from copy import deepcopy
import pytest
from tests.test_stepwise_name_independent_binding import request as binding_request
from tests.test_task_action_binding import fixture as action_fixture
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_resume_route import ROOT

def test_displayed_identity_round_trip_and_saved_original_line(tmp_path):
    from regrow.traversal import action_binding as binding
    q = binding_request(tmp_path)
    q.update(user_prompt='原问题', dynamic_prompt='原问题')
    binding.disclose_candidates(q)
    import json
    rows = json.loads(q['user_prompt'])['可登记动作身份']
    assert {row['target'] for row in rows} == {'r/style', 'r/back'}
    for target in [row['target'] for row in rows]:
        assert binding.bind_action_target(q, {'action': 'click', 'target': target, 'x': 40, 'y': 40})['control_ref'] == target.split('/')[1]
    q['_action_identity_text'] = '- r/style：样式选项（r）'
    original = {'action': 'click', 'target': 'r/style：样式选项（r）', 'x': 40, 'y': 40}
    before = deepcopy(original)
    assert binding.bind_action_target(q, original)['control_ref'] == 'style'
    assert original == before

def test_conflicting_identity_is_corrected_but_new_preparation_remains_possible(tmp_path):
    from regrow.traversal import action_binding as binding
    q = binding_request(tmp_path)
    for target in ('r/style：返回', 'r/style 或 r/back', 'r0009/c9999'):
        assert binding.bind_action_target(q, {'action': 'click', 'target': target, 'x': 40, 'y': 40})['status'] == 'unresolved'
    fresh = binding.bind_action_target(q, {'action': 'click', 'target': '关闭弹层的空白', 'x': 40, 'y': 40})
    assert fresh['status'] == 'matched' and fresh['control_ref'] is None
    q['backend_candidates'].append({**q['backend_candidates'][0], 'id': 'other'})
    assert binding.bind_action_target(q, {'action': 'click', 'target': '样式选项', 'x': 40, 'y': 40})['status'] == 'unresolved'

def test_exact_region_control_names_keep_the_original_task_binding(tmp_path):
    from regrow.traversal import action_binding as binding
    q = binding_request(tmp_path)
    q['preparation_allowed'] = True
    q['source'].update(task_type='single_action', task_action='click', task_control='style')
    q['backend_candidates'][0]['region_name'] = '参数菜单'
    proposal = {'action': 'click', 'target': '参数菜单/样式选项', 'x': 40, 'y': 40}
    original = deepcopy(proposal)
    got = binding.bind_action_target(q, proposal)
    assert got['region_ref'] == 'r' and got['control_ref'] == 'style'
    assert not got['preparatory_action'] and 'association' not in got
    assert proposal == original
    q['backend_candidates'].append({**q['backend_candidates'][0], 'region_ref': 'other'})
    assert binding.bind_action_target(q, proposal)['status'] == 'unresolved'

@pytest.mark.parametrize('answer', [True, False])
@pytest.mark.parametrize('cross_region', [True, False])
def test_empty_identity_candidates_preserve_only_the_original_answer_gap(answer, cross_region):
    from regrow.records import task_settlement as settlement
    (r, _, _, _) = action_fixture()
    task = r['tasks']['查看选项']
    task['attempts'] = ['a1']
    r['tasks']['另一问题'] = {**deepcopy(task), 'control': 'c2', 'attempts': []}
    a = r['actions']['a1']
    a.update(control=None, association={'status': 'unconfirmed', 'candidates': []}, task_update=[{'task': 'r1/查看选项', 'knowledge': '已观察参数选项' if answer else '', 'findings': [], 'next_action': None if answer else {'reason': '还需打开目标'}}])
    original = deepcopy(a)
    records = {'r1': r}
    if cross_region:
        records['r2'] = {'id': 'r2', 'actions': {'a1': r['actions'].pop('a1')}, 'tasks': {}}
    settlement.reconcile(records)
    assert task['status'] == ('blocked' if answer else 'pending')
    assert r['tasks']['另一问题']['status'] == 'pending' and a == original
    assert 'completion_basis' not in task and (not task.get('knowledge'))

def test_observed_entry_knowledge_does_not_claim_task_completion(tmp_path):
    from tests.test_current_page_context import case, module
    from regrow.records.task_knowledge import refresh as refresh
    (records, state, _) = case(tmp_path)
    task = {'status': 'pending', 'handling': 'explore', 'control': 'submit', 'registration_kind': 'entry', 'knowledge': '按钮用于提交当前选择；去向尚未观察', 'knowledge_source': {'basis': 'observation_only', 'call': 'original'}, 'attempts': []}
    records['dialog']['tasks']['submit destination'] = task
    before = deepcopy(task)
    refresh(records, state)
    view = module().build(records, state, run=tmp_path)
    text = module()._display(view)
    assert '已登记控件知识' in text and '已完成任务知识' not in text
    assert 'observation_only' in text and '去向尚未观察' in text
    assert records['dialog']['controls']['submit']['knowledge']['submit destination']['source']['attempts'] == []
    assert task == before

@pytest.mark.parametrize('current,interactive', [(True, True), (False, True), (True, False)])
def test_navigation_none_retains_target_and_requires_current_operability(tmp_path, current, interactive):
    from regrow.traversal import traversal_scheduler as scheduler
    (run, _, discovery) = setup(tmp_path)
    frame = run / 'saved-frame.png'
    frame.write_bytes(b'current-evidence')
    old = run / 'old-frame.png'
    old.write_bytes(b'old-evidence')

    def seed(records, state, *_):
        records['r2'] = {**deepcopy(records['r1']), 'id': 'r2', 'name': 'Target', 'tasks': {}, 'actions': {}}
        state.update(working_region='r1', inspection_region='r1', required_control='c1', observation={'id': 'now', 'image': str(frame if current else old), 'control_refs': [], 'foreground': {'exception': 'none'}}, interactive_regions=['r1', 'r2'] if interactive else ['r1'])
    discovery.publish(run, 'navigation-fixture', seed)
    q = {'stage': 'action_selection', 'navigation_advice': True, 'source': {'region': 'r1', 'working_region': 'r2', 'observation': 'now'}, 'screenshots': [str(frame)]}
    scheduler.handoff_no_action(run, q, {'action': 'none', 'reason': '目标页面已显示，请核对能否继续'}, 'none', frame)
    (_, records, state) = discovery.load(run)
    assert state['working_region'] == 'r2' and (not state.get('inspection_region'))
    assert state['next_action_mode'] == ('explore' if current and interactive else 'discover')
    assert not records['r2']['actions']
    if not (current and interactive):
        from regrow.traversal.work_context import select as select
        work = select(records, state, 'locate')
        assert work['region'] == 'r2' and 'none' in work['reason']

def test_switch_advice_is_a_sourced_unexecuted_handoff(tmp_path):
    from tests.test_stepwise_branch_switch import fixture
    from tests.test_stepwise_region_tasks import tasks
    from regrow.traversal.work_context import select as select
    (run, job, d, frame) = fixture(tmp_path)
    m = _test_branch_switch
    q = m.request(ROOT, run, job, frame, {'status': 402}, '0675')
    m.commit(run, job, q, {'decision': 'switch', 'next_region': 'Other', 'reason': '先关闭当前遮挡，再核对目标'}, '0676')
    (_, records, state) = d.load(run)
    work = select(records, state, 'locate')
    assert '先关闭当前遮挡' in work['reason'] and '0676' in work['reason']
    assert state['navigation_handoff']['source_call'] == '0676'
    assert '未执行' in state['navigation_handoff']['status']

def test_history_selection_omits_unrelated_background_but_keeps_failures():
    from regrow.records.context_scope import history_changes as history_changes
    records = {rid: {'id': rid, 'controls': {}, 'tasks': {}} for rid in ('goal', 'menu', 'background')}
    state = {'working_region': 'goal', 'interactive_regions': ['goal'], '_work_context': {'kind': 'action', 'region': 'goal', 'task': None}}
    rows = [{'region': rid, 'state': 'not_visible', 'evidence': rid + ' evidence'} for rid in records]
    action = {'region_changes': rows, 'result': {'exception': 'none'}, 'evidence': {'before_regions': ['menu']}}
    before = deepcopy(action)
    assert [r['region'] for r in history_changes(records, state, 'menu', action)] == ['goal', 'menu']
    assert action == before
    action['result']['exception'] = 'system_error'
    assert history_changes(records, state, 'menu', action) == rows
