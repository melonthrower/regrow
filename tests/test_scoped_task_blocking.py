from copy import deepcopy

import pytest

import operation_blocking as blocking
import task_prerequisites as prerequisites
from tests.test_stepwise_resume_route import fixture


def records():
    r = {'id': 'r', 'name': 'Timer', 'controls': {
        'start': {'name': 'Start', 'task_refs': [], 'observations': []},
        'add': {'name': 'Add', 'task_refs': [], 'observations': []}}, 'tasks': {}, 'actions': {}}
    r['tasks']['Add purpose'] = {'control': 'add', 'action': 'click', 'status': 'pending',
        'handling': 'explore', 'prerequisite': {'region': 'Timer', 'control': 'Start',
        'condition': 'running', 'preparation': 'start timer', 'evidence': 'setup visible', 'permitted': True}}
    return {'r': r}


def crash(rs, *, owner='r', actual='r', cid='start', operation='click', conditions=()):
    rs[actual]['actions']['crash'] = {'control': cid, 'operation': operation,
        'conditions': list(conditions), 'delivery': 'executed_receipt_zero',
        'result': {'exception': 'unexpected_exit', 'description': 'app exited'}}
    parent_control = 'add' if 'add' in rs[owner]['controls'] else next(iter(rs[owner]['controls']))
    rs[owner].setdefault('tasks', {})['failed'] = {'control': parent_control, 'action': 'input_text',
        'status': 'blocked', 'blocker': {'exception': 'unexpected_exit', 'attempt': 'crash'}}


def test_unanswered_hover_does_not_block_start_preparation_or_finish_parent():
    rs = records();r = rs['r']
    r['tasks']['hover'] = {'control': 'start', 'action': 'hover', 'status': 'blocked',
                          'blocker': {'condition': 'review_required', 'reason': 'no tooltip'}}
    before = deepcopy(r['tasks']['hover'])
    prerequisites.enroll(rs, 'r', 'plan')
    task = r['tasks']['Add purpose'];ref = task['prerequisite']['scheduled']
    assert task['status'] == 'blocked'
    assert r['tasks'][ref['task']]['status'] == 'pending'
    assert r['tasks'][ref['task']]['control'] == 'start'
    assert r['tasks']['hover'] == before
    prerequisites.enroll(rs, 'r', 'again')
    assert len([t for t in r['tasks'].values() if t.get('prepares')]) == 1


def test_same_control_parent_does_not_prevent_its_own_preparation():
    rs = records();rs['r']['tasks']['Add purpose']['control'] = 'start'
    prerequisites.enroll(rs, 'r', 'plan')
    assert rs['r']['tasks']['Add purpose']['prerequisite'].get('scheduled')


@pytest.mark.parametrize('excluded', ['permission', 'scope', 'crash'])
def test_real_restrictions_still_prevent_preparation(excluded):
    rs = records();r = rs['r'];task = r['tasks']['Add purpose']
    if excluded == 'permission':task['prerequisite']['permitted'] = False
    elif excluded == 'scope':r['out_of_scope_reason'] = 'outside requested work'
    else:crash(rs)
    prerequisites.enroll(rs, 'r', 'plan')
    assert not task['prerequisite'].get('scheduled')


def test_failure_is_scoped_to_actual_action_not_the_original_task_target():
    rs = records();crash(rs)
    assert blocking.applicable(rs, 'r', 'start', 'tap')
    assert not blocking.applicable(rs, 'r', 'add', 'input_text')
    assert not blocking.applicable(rs, 'r', 'start', 'hover')


def test_cross_region_preparation_crash_uses_actual_owner():
    rs = records();rs['other'] = {'name': 'Other', 'controls': {'actual': {'name': 'Actual'}}, 'actions': {}, 'tasks': {}}
    crash(rs, actual='other', cid='actual')
    assert blocking.applicable(rs, 'other', 'actual', 'click')
    assert not blocking.applicable(rs, 'r', 'add', 'input_text')


def test_conditional_failure_does_not_become_global_or_match_unknown_conditions():
    rs = records();crash(rs, conditions=['paused'])
    assert blocking.applicable(rs, 'r', 'start', 'click', ['paused'])
    assert blocking.applicable(rs, 'r', 'start', 'click', ['paused', 'selected'])
    assert not blocking.applicable(rs, 'r', 'start', 'click', ['setup'])
    assert not blocking.applicable(rs, 'r', 'start', 'click')
    # Preparation intent has no declared use conditions; normal action selection sees the failure.
    prerequisites.enroll(rs, 'r', 'plan')
    assert rs['r']['tasks']['Add purpose']['prerequisite'].get('scheduled')


def test_unconfirmed_failed_operation_does_not_ban_original_target():
    rs = records();crash(rs);rs['r']['actions']['crash']['control'] = None
    assert not blocking.applicable(rs, 'r', 'add', 'input_text')
    q = {'action_ready': True, 'user_prompt': 'original', 'source': {'region': 'r'}}
    blocking.attach(q, rs, {'interactive_regions': ['r']})
    assert '"实际操作归属明确": false' in q['user_prompt']
    assert '"实际控件": null' in q['user_prompt']
    assert 'app exited' in q['user_prompt']


def test_resolved_crash_does_not_keep_a_hidden_control_ban():
    rs = records();crash(rs);rs['r']['tasks']['failed']['status'] = 'pending'
    assert not blocking.applicable(rs, 'r', 'start', 'click')


def test_preparation_result_only_wakes_parent_on_current_target_observation():
    rs = records();r = rs['r'];prerequisites.enroll(rs, 'r', 'plan')
    parent = r['tasks']['Add purpose'];prep = r['tasks'][parent['prerequisite']['scheduled']['task']]
    reply = {'dependency_updates': [{'region': 'Timer', 'task': 'Add purpose', 'ready': True, 'evidence': 'Add visible in running view'}]}
    allowed = [{'region': 'r', 'task': 'Add purpose'}]
    with pytest.raises(ValueError, match='重新确认'):prerequisites.apply(rs, reply, 'after', allowed)
    r['controls']['add']['observations'].append({'evidence': {'source_call': 'after'}})
    prerequisites.apply(rs, reply, 'after', allowed)
    assert parent['status'] == 'pending' and prep['status'] == 'done'
    assert 'completion_basis' not in parent


def test_known_route_survives_unanswered_task_but_not_same_use_crash():
    flow,rs,state = fixture()
    rs['main']['tasks'] = {'question': {'control': 'open', 'action': 'hover', 'status': 'blocked'}}
    assert flow.shortest_known_path(rs, state, 'menu')
    crash(rs, owner='main', actual='main', cid='open')
    assert flow.shortest_known_path(rs, state, 'menu') is None
    rs['main']['actions']['crash']['conditions'] = ['paused']
    rs['main']['actions']['a3']['conditions'] = ['setup']
    assert flow.shortest_known_path(rs, state, 'menu')


def test_action_acceptance_rejects_known_failure_even_for_another_task_name():
    rs = records();crash(rs)
    binding = {'region_ref': 'r', 'control_ref': 'start', 'task_region': 'r', 'task_name': 'Add purpose'}
    with pytest.raises(ValueError, match='应用退出'):blocking.check_action(rs, binding, {'action': 'click'})
    blocking.check_action(rs, binding, {'action': 'hover'})


def test_conditional_direct_action_guard_and_preparation_context_are_separate():
    rs = records();crash(rs, conditions=['paused'])
    rs['r']['tasks']['new name'] = {'control': 'start', 'action': 'click', 'conditions': ['paused']}
    b = {'region_ref': 'r', 'control_ref': 'start', 'task_region': 'r', 'task_name': 'new name'}
    with pytest.raises(ValueError, match='应用退出'):blocking.check_action(rs, b, {'action': 'click'})
    rs['r']['tasks']['new name']['conditions'] = ['setup']
    blocking.check_action(rs, b, {'action': 'click'})
    rs['r']['tasks']['new name']['prepares'] = {'region': 'r', 'task': 'Add purpose'}
    assert blocking.action_conditions(rs, b, {'action': 'click'}) is None


def test_navigation_request_retains_scoped_failure_for_normal_model_judgment():
    flow,rs,state = fixture();crash(rs, owner='main', actual='main', cid='open', conditions=['paused'])
    q = flow.assemble_context(__import__('tests.test_stepwise_resume_route', fromlist=['ROOT']).ROOT, rs, state, 'menu')
    blocking.attach(q, rs, state)
    assert 'paused' in q['user_prompt'] and '实际控件' in q['user_prompt']
    assert '待继续探索区块：菜单' in q['user_prompt']


@pytest.mark.parametrize('operation, rejected', [('click', True), ('hover', False)])
def test_normal_action_acceptance_uses_actual_operation_guard(monkeypatch, tmp_path, operation, rejected):
    from types import SimpleNamespace
    import repair_stages as stages
    rs = records();crash(rs);events = []
    q = {'response_schema': {'type': 'object'}};proposal = {'action': operation}
    binding = {'status': 'matched', 'region_ref': 'r', 'control_ref': 'start',
               'task_region': 'r', 'task_name': 'Add purpose', 'observation_ref': 'now'}
    helpers = {
        'discovery_step': SimpleNamespace(load=lambda run: (None, rs, {'observation': {'id': 'now'}})),
        'step_repair': SimpleNamespace(submission=lambda *a: (q, proposal)),
        'action_commands': SimpleNamespace(validate=lambda *a: None, normalize=lambda p: p, commands=lambda *a: None),
        'stepwise_flow': SimpleNamespace(bind_action_target=lambda *a: binding),
        'operation_blocking': blocking,
        'attempt_guard': SimpleNamespace(check=lambda *a, **k: events.append('attempt_guard'))}
    monkeypatch.setattr(stages, 'helper', helpers.__getitem__)
    job = {'stage': 'action', 'call': 'candidate', 'request': q}
    if rejected:
        with pytest.raises(ValueError, match='应用退出'):stages.accept_candidate(None, tmp_path, job)
        assert events == []
    else:
        assert stages.accept_candidate(None, tmp_path, job)['binding'] == binding
        assert events == ['attempt_guard']


def test_normal_crash_registration_preserves_only_matching_task_conditions():
    from task_settlement import settle_task
    rs = records();r = rs['r'];task = r['tasks']['Add purpose']
    task.pop('prerequisite');task['conditions'] = ['paused']
    action = {'control': 'add', 'operation': 'click', 'delivery': 'executed_receipt_zero',
              'result': {'exception': 'unexpected_exit', 'description': 'app exited'}}
    r['actions']['actual'] = action
    binding = {'region_ref': 'r', 'control_ref': 'add', 'task_region': 'r', 'task_name': 'Add purpose'}
    settle_task(r, binding, {'action_result': action['result']}, 'actual', rs)
    assert 'conditions' not in action  # Native crash registration does not write this field.
    assert blocking.applicable(rs, 'r', 'add', 'click', ['paused'])
    assert not blocking.applicable(rs, 'r', 'add', 'click', ['setup'])
    # A preparation operation does not inherit the parent target's use conditions.
    action['control'] = 'start'
    assert next(blocking.failures(rs))['conditions'] is None
    assert not blocking.applicable(rs, 'r', 'start', 'click', ['paused'])


def test_unconfirmed_association_does_not_establish_failed_control():
    rs = records();crash(rs)
    rs['r']['actions']['crash']['association'] = {'status': 'unconfirmed'}
    assert not next(blocking.failures(rs))['confirmed']
    assert not blocking.applicable(rs, 'r', 'start', 'click')


def test_outer_foreground_candidate_keeps_its_conditional_failure_visible():
    rs = records();crash(rs, conditions=['menu open'])
    rs['overlay'] = {'id': 'overlay', 'name': 'Menu', 'controls': {}, 'tasks': {}, 'actions': {}}
    q = {'action_ready': True, 'user_prompt': 'original', 'source': {'region': 'overlay'},
         'backend_candidates': [{'region_ref': 'r', 'id': 'start', 'name': 'Start'}]}
    blocking.attach(q, rs, {'interactive_regions': ['overlay']})
    assert 'menu open' in q['user_prompt'] and 'app exited' in q['user_prompt']
