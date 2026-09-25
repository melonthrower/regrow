"""Survey may investigate registered controls without declaring coverage complete."""
import pytest

from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.status import build_task_view
from .explore_fixtures import _Agent, _Env, _png, _turn, _new_screen, _known_screen, _report


def test_partial_survey_can_execute_and_settle_an_existing_owner(tmp_path):
    agent = _Agent([
        (_turn(screen=_new_screen(), page_report={**_report(), 'survey_complete': False}), False),
        (_turn(screen=_known_screen(), action={
            'kind': 'click', 'owner_ref': 'el1', 'target': 'Open options',
            'point_1000': [500, 500], 'text': '', 'direction': '', 'amount': 650}), False),
        (_turn(screen=_known_screen(), previous={
            'attempt_ref': 'a1', 'element_actions': [
                {'element_ref': 'el1', 'action': 'click', 'completed': True}],
            'region_actions': [], 'function_info': [], 'parameter_info': None,
            'representative_same_kind': None, 'region_effects': [],
            'reason': 'The registered control visibly changed.'}), True),
    ])
    env = _Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 3
    result = runtime.run(env._get_obs())
    assert runtime.actions_used == 1
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert runtime.ledger.operations['o1'].status == 'verified'
    assert not runtime.ledger.states['s1'].survey_complete
    assert runtime.ledger.survey_task('s1').status in {'active', 'pending'}
    assert not runtime.pending_attempt_id


@pytest.mark.parametrize('owner,operation', [('el404', 'o1'), ('el1', 'o404')])
def test_survey_still_rejects_invalid_action_binding(tmp_path, owner, operation):
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.explore.contracts import ActionRequest
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')),
        app_name='fixture', platform='desktop', output_root=str(tmp_path), agent=_Agent([]), max_actions=1)
    runtime.ledger = _seed_ledger()
    task = runtime.ledger.survey_task('s1')
    task.status = 'active'
    action = ActionRequest('click', 'execute', 'Control', [500, 500], '', '', 650,
        operation_ref=operation, owner_ref=owner)
    assert runtime._validate_action(task, action)


def test_survey_instruction_keeps_finite_options_and_data_coverage_distinct():
    from .explore_fixtures import _seed_ledger
    ledger = _seed_ledger()
    task = ledger.survey_task('s1')
    task.status = 'active'
    instruction = build_task_view(ledger, task)['instruction']
    assert '有限参数列表' in instruction
    assert '已登记' in instruction
    assert '清点时不执行功能' not in instruction
