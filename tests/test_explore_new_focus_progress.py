"""New focus selection must use the same reachability gate as a held focus.

VLC batch14 call0001 -> call0002 exposed this shape: successful menu
settlement releases the old focus, an unreachable ancestor wins by age,
and visible pending work is ignored until the *next* scheduler call.
Full saved-input replay is retained with the investigation artifacts.
"""
from copy import deepcopy

import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.models import ActionAttempt, CanonicalOperation, Transition
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.tasks import TaskScheduler
from .explore_fixtures import _Env, _known_screen, _ledger_with_current_canonical_binding, _png, _turn


def _new_focus_ledger():
    ledger, old = _ledger_with_current_canonical_binding()
    # These are distinct operations; this is not evidence for identity merging.
    ledger.canonical_operations['co1'].operation_ids.remove('o2')
    ledger.canonical_operations['co2'] = CanonicalOperation(
        'co2', 'r1', 'click', 'Other function', ['o2'])
    ledger.regions['r1'].canonical_operation_ids.append('co2')
    ledger.operations['o2'].canonical_operation_id = 'co2'
    ledger.operations['o2'].parameter_status = 'none'
    ledger.operations['o2'].parameter_summary = 'No parameters'
    old.status = 'pending'
    ledger.current_task_id = ''
    # Observed one-way arrival makes s1 an ancestor, not a verified way back.
    ledger.attempts['a-arrival'] = ActionAttempt(
        'a-arrival', '', 's1', 'route', {'kind': 'back'}, 'before.png',
        after_ref='after.png', outcome='success', target_state_id='s2')
    ledger.transitions.append(Transition(
        'e-arrival', 's1', 's2', 'a-arrival', {'kind': 'back'}, 'Arrived'))
    return ledger, old


def test_new_unreachable_ancestor_yields_on_first_selection():
    ledger, old = _new_focus_ledger()
    attempts = deepcopy(ledger.attempts)
    transitions = deepcopy(ledger.transitions)

    selected = TaskScheduler().choose(ledger)

    assert selected.task_id == 't-current'
    assert old.status == 'pending'
    assert ledger.operations[old.operation_id].status == 'pending'
    assert old.attempt_count == 0
    assert ledger.operations['o1'].canonical_operation_id == 'co1'
    assert ledger.operations['o2'].canonical_operation_id == 'co2'
    assert ledger.attempts == attempts
    assert ledger.transitions == transitions
    assert any(old.operation_id in gap for gap in TaskScheduler.gaps(ledger))


def test_runtime_dispatches_visible_work_without_a_detour(tmp_path):
    ledger, old = _new_focus_ledger()
    before, after = _png('white'), _png('blue')
    env = _Env(before, after)
    screen = {**_known_screen(), 'state_ref': 's2', 'state_name': 'Current'}

    class Agent:
        def decide(self, **kwargs):
            assert runtime.ledger.current_task_id == 't-current'
            if not kwargs['has_pending_action']:
                return parse_turn(_turn(screen=screen, action={
                    'kind': 'click', 'owner_ref': 'el2', 'target': 'Other function',
                    'point_1000': [500, 500],
                }), has_pending_action=False)
            return parse_turn(_turn(screen=screen, previous={
                'attempt_ref': kwargs['pending_attempt_id'],
                'element_actions': [{'element_ref': 'el2', 'action': 'click', 'completed': True}],
                'region_actions': [], 'function_info': [], 'region_effects': [],
                'reason': 'The requested control visibly changed.',
            }), has_pending_action=True)

    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=Agent(), max_actions=1)
    runtime.ledger = ledger
    result = runtime.run(env._get_obs())

    assert result.actions_used == 1
    assert result.stop_reason == 'action_limit'
    assert runtime.ledger.tasks['t-current'].status == 'done'
    assert runtime.ledger.operations['o2'].status == 'verified'
    assert runtime.ledger.tasks[old.task_id].status == 'pending'
    assert runtime.ledger.operations['o1'].status == 'pending'
    executed = [a for a in runtime.ledger.attempts.values() if a.attempt_id != 'a-arrival']
    assert len(executed) == 1
    assert executed[0].action['operation_ref'] == 'o2'
    assert executed[0].outcome == 'success'
    assert not runtime.pending_attempt_id


@pytest.mark.parametrize('guard', ['pending', 'unfinished_survey', 'no_local_work', 'explicit_scope'])
def test_new_focus_preserves_existing_yield_guards(guard):
    ledger, old = _new_focus_ledger()
    if guard == 'pending':
        ledger.attempts['a-pending'] = ActionAttempt(
            'a-pending', old.task_id, 's1', 'route', {'kind': 'back'}, 'before.png')
    elif guard == 'unfinished_survey':
        ledger.states['s2'].survey_complete = False
    elif guard == 'no_local_work':
        ledger.tasks['t-current'].status = 'failed'
        ledger.operations['o2'].status = 'failed'
    else:
        old.status = 'active'
        ledger.current_task_id = old.task_id

    assert TaskScheduler().choose(
        ledger, automatic_operation_selection=guard != 'explicit_scope') is old
    assert not any(e['kind'] == 'unreachable_focus_parked' for e in ledger.events)
