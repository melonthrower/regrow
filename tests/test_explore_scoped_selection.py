"""A finite goal keeps the graph but does not inherit automatic operation focus."""
import json
import pytest
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.tasks import TaskScheduler
from .explore_fixtures import _seed_ledger, _Agent, _Env, _png, _turn, _known_screen


def test_scoped_scheduler_preserves_pending_work_without_auto_selecting_it():
    ledger = _seed_ledger()
    task = ledger.operation_task('o1')
    assert TaskScheduler().choose(ledger, automatic_operation_selection=False) is None
    assert task.status == 'pending'
    chosen = TaskScheduler().select_visible_operation(ledger, 'co1', 'chosen for this goal')
    assert TaskScheduler().choose(ledger, automatic_operation_selection=False) is chosen


def test_current_region_exposes_missing_function_identity_without_old_owner_binding():
    from dataclasses import replace
    from gui_rewalk.src.core.explore.models import PageState
    from gui_rewalk.src.core.explore.status import current_page_record
    ledger = _seed_ledger()
    ledger.states['s2'] = PageState('s2', 'p1', 'Other view', '', 'other.png', ['ro2'])
    ledger.pages['p1'].state_ids.append('s2')
    ledger.occurrences['ro2'] = replace(ledger.occurrences['ro1'], occurrence_id='ro2', state_id='s2', variant_id='rv2')
    ledger.region_variants['rv2'] = replace(ledger.region_variants['rv1'], variant_id='rv2',
        occurrence_ids=['ro2'], operation_ids=[], element_ids=[])
    record = current_page_record(ledger, state_id='s2')['regions'][0]
    assert record['elements'] == []
    assert record['unbound_known_operations'][0]['operation_ref'] == 'co1'
    assert 'el1' not in json.dumps(record['unbound_known_operations'])


def click():
    return {'kind': 'click', 'owner_ref': 'el1', 'target': 'Control',
            'point_1000': [500, 500], 'text': '', 'direction': '', 'amount': 650}


def receipt():
    return {'attempt_ref': 'a1', 'element_actions': [
        {'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'region_effects': [],
        'parameter_info': None, 'representative_same_kind': None,
        'reason': 'The control visibly changed.'}


def test_scoped_agent_action_selects_its_own_pending_operation(tmp_path):
    agent = _Agent([
        (_turn(screen=_known_screen(), action=click()), False),
        (_turn(screen=_known_screen(), previous=receipt()), True),
    ])
    env = _Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1, exploration_goal='Investigate this control')
    runtime.ledger = _seed_ledger()
    result = runtime.run(env._get_obs())
    assert 'task_ref' not in agent.contexts[0]['当前任务精确卡']
    assert runtime.ledger.operations['o1'].status == 'verified'
    assert runtime.ledger.attempts['a1'].task_id
    assert result.actions_used == 1


def test_scoped_recorded_control_can_restore_without_an_open_task(tmp_path):
    agent = _Agent([
        (_turn(screen=_known_screen(), action=click()), False),
        (_turn(screen=_known_screen(), previous=receipt()), True),
        (_turn(screen=_known_screen()), False),
    ])
    env = _Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=3, exploration_goal='Restore the original view')
    runtime.ledger = _seed_ledger()
    runtime.ledger.tasks.pop(runtime.ledger.operation_task('o1').task_id)
    runtime.ledger.operations['o1'].status = 'recorded'
    result = runtime.run(env._get_obs())
    assert runtime.actions_used == 1
    assert runtime.ledger.attempts['a1'].task_id == ''
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert result.stop_reason == 'scope_idle'
    assert result.status == 'partial'


def test_scoped_idle_does_not_complete_or_erase_unselected_tasks(tmp_path):
    agent = _Agent([(_turn(screen=_known_screen()), False)])
    env = _Env(_png('white'), _png('white'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1, exploration_goal='Observe only')
    runtime.ledger = _seed_ledger()
    runtime.max_turns = 1
    result = runtime.run(env._get_obs())
    assert result.stop_reason == 'scope_idle'
    assert result.status == 'partial'
    assert runtime.ledger.operation_task('o1').status == 'pending'
    assert not env.actions
    assert json.loads((tmp_path / 'modular_completion.json').read_text())['exploration_goal'] == 'Observe only'


@pytest.mark.parametrize('outcome,allowed', [('no_effect', False), ('uncertain', False), ('success', True)])
def test_scoped_taskless_binding_keeps_repeat_protection(tmp_path, outcome, allowed):
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.actions import action_dict
    from gui_rewalk.src.core.explore.models import ActionAttempt
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')),
        app_name='fixture', platform='desktop', output_root=str(tmp_path),
        agent=_Agent([]), max_actions=2, exploration_goal='Restore')
    runtime.ledger = _seed_ledger()
    runtime.ledger.operations['o1'].status = 'recorded'
    action = runtime._bind_action(None, parse_turn(
        _turn(screen=_known_screen(), action=click()), has_pending_action=False).action)
    runtime.ledger.attempts['a1'] = ActionAttempt('a1', '', 's1', 'execute',
        action_dict(action), 'before.png', outcome=outcome)
    assert (runtime._validate_action(None, action) == '') is allowed


@pytest.mark.parametrize('intervening,blocked', [('back', True), ('click', False)])
@pytest.mark.parametrize('has_task', [False, True])
def test_successful_back_does_not_erase_a_failed_operation(tmp_path, intervening, blocked, has_task):
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.actions import action_dict
    from gui_rewalk.src.core.explore.models import ActionAttempt
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')),
        app_name='fixture', platform='desktop', output_root=str(tmp_path),
        agent=_Agent([]), max_actions=3, exploration_goal='Continue')
    runtime.ledger = _seed_ledger()
    task = runtime.ledger.operation_task('o1') if has_task else None
    runtime.ledger.operations['o1'].status = 'active' if has_task else 'recorded'
    action = runtime._bind_action(task, parse_turn(
        _turn(screen=_known_screen(), action=click()), has_pending_action=False).action)
    task_id = task.task_id if task else ''
    runtime.ledger.attempts['a1'] = ActionAttempt('a1', task_id, 's1', 'execute',
        action_dict(action), 'before.png', outcome='uncertain')
    runtime.ledger.attempts['a2'] = ActionAttempt('a2', task_id, 's2', 'recover',
        {'kind': intervening, 'owner_ref': '', 'operation_ref': ''}, 'popup.png', outcome='success')
    assert bool(runtime._validate_action(task, action)) is blocked


def test_repeating_the_same_observation_on_a_new_frame_does_not_keep_scope_running(tmp_path):
    from .test_explore_control_actions import report
    raw = _turn(screen=_known_screen(), page_report=report('el1'))
    agent = _Agent([(raw, False), (raw, False)])
    env = _Env(_png('white'), _png('white'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1, exploration_goal='Observe the current value')
    runtime.ledger = _seed_ledger()
    runtime.max_turns = 2
    result = runtime.run(env._get_obs())
    assert result.stop_reason == 'scope_idle'
    assert len(runtime.ledger.elements['el1'].observations) == 2
    assert not env.actions


@pytest.mark.parametrize('active_task', [True, False])
def test_known_return_reuses_inventory_without_identity_review(tmp_path, active_task):
    from gui_rewalk.src.core.explore.models import PageState, Transition
    back = {'kind': 'back', 'owner_ref': '', 'target': 'Close menu',
            'point_1000': None, 'text': '', 'direction': '', 'amount': 650}
    returned = {**receipt(), 'element_actions': [], 'reason': 'Menu closed; source controls visible.'}
    final = {**receipt(), 'attempt_ref': 'a2'}
    menu = {**_known_screen(), 'state_ref': 's2', 'state_name': 'Menu', 'state_summary': 'Menu open'}

    class Agent(_Agent):
        def correspond_regions(self, **kwargs):
            pytest.fail('Known unchanged return must not trigger Region review')

        def review_element_identities(self, **kwargs):
            pytest.fail('Known unchanged return must not trigger Element review')

    turns = [
        (_turn(screen=menu, action=back), False),
        (_turn(screen=_known_screen(), previous=returned, action=click()), True),
        (_turn(screen=_known_screen(), previous=final), True),
    ]
    if not active_task:
        turns[1:2] = [(_turn(screen=_known_screen(), previous=returned), True),
                      (_turn(screen=_known_screen(), action=click()), False)]
    agent = Agent(turns)
    class Env(_Env):
        def step(self, action, pause=0):
            self.after = _png('white' if self.actions else 'black')
            return super().step(action, pause)

    env = Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=2, exploration_goal='Return and investigate')
    runtime.ledger = _seed_ledger()
    ledger = runtime.ledger
    ledger.states['s2'] = PageState('s2', 'p1', 'Menu', 'Menu open', '', survey_complete=True)
    ledger.pages['p1'].state_ids.append('s2')
    ledger.transitions.append(Transition('e0', 's1', 's2', '', {}, 'Opened menu'))
    ledger.current_state_id = 's2'
    if active_task:
        task = ledger.operation_task('o1')
        task.status = 'active'
        ledger.current_task_id = task.task_id

    result = runtime.run(env._get_obs())

    assert '已知State候选绑定' not in agent.contexts[1]
    if active_task:
        assert agent.contexts[1]['当前任务精确卡']['known_source_bindings'] == [
            {'state_ref': 's1', 'region_ref': 'r1', 'owner_ref': 'el1'}]
    else:
        assert agent.contexts[2]['当前页面已登记内容']['regions'][0]['elements'][0]['element_ref'] == 'el1'
    assert len(agent.contexts) == (3 if active_task else 4)
    assert result.actions_used == 2
    assert runtime.ledger.attempts['a2'].source_state_id == 's1'
    assert runtime.ledger.operations['o1'].status == 'verified'


def test_historical_candidate_cannot_bind_an_owner_in_an_unexpected_state(tmp_path):
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.models import PageState
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')),
        app_name='fixture', platform='desktop', output_root=str(tmp_path),
        agent=_Agent([]), max_actions=1, exploration_goal='Explore')
    runtime.ledger = _seed_ledger()
    runtime.ledger.states['s2'] = PageState('s2', 'p1', 'Unexpected', '', '', survey_complete=True)
    runtime.ledger.pages['p1'].state_ids.append('s2')
    runtime.ledger.current_state_id = 's2'
    with pytest.raises(SettlementContractError) as error:
        runtime._bind_action(None, parse_turn(
            _turn(screen={**_known_screen(), 'state_ref': 's2'}, action=click()), has_pending_action=False).action)
    assert error.value.field_path == 'action.owner_ref'
    assert not runtime.env.actions


def test_first_menu_inventory_can_execute_safe_back_in_the_same_turn(tmp_path):
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent

    class Agent(_Agent):
        def decide(self, **kwargs):
            self.contexts.append(kwargs['context'])
            return QwenExplorerAgent.decide(self, **kwargs)

        def _call(self, **kwargs):
            return self.turns.pop(0)[0]

    menu = {**_known_screen(), 'identity': 'new_state', 'state_ref': '',
            'state_name': 'Options', 'state_summary': 'A foreground choice menu'}
    report = {'regions': [{'region_ref': '', 'parent_ref': None, 'name': 'Options menu',
        'summary': 'A foreground choice menu', 'memory': 'Choices Alpha and Beta observed',
        'elements': [], 'region_operations': []}], 'survey_complete': True,
        'coverage_note': 'All visible choices observed; no value selected'}
    back = {'kind': 'back', 'owner_ref': '', 'target': 'Close the observed menu',
            'point_1000': None, 'text': '', 'direction': '', 'amount': 650}
    returned = {**receipt(), 'attempt_ref': 'a2', 'element_actions': [],
                'reason': 'The menu closed and the original page is visible'}
    agent = Agent([
        (_turn(screen=_known_screen(), action=click()), False),
        (_turn(screen=menu, previous=receipt(), page_report=report, action=back), True),
        (_turn(screen=_known_screen(), previous=returned), True),
    ])

    class Env(_Env):
        def step(self, action, pause=0):
            self.after = _png('white' if self.actions else 'black')
            return super().step(action, pause)

    env = Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=2, exploration_goal='Inspect and return')
    runtime.ledger = _seed_ledger()
    result = runtime.run(env._get_obs())
    assert result.actions_used == 2
    assert len(agent.contexts) == 3
    assert runtime.ledger.states['s2'].survey_complete is True
    assert runtime.ledger.attempts['a2'].source_state_id == 's2'
    assert runtime.ledger.attempts['a2'].action['kind'] == 'back'
    assert runtime.ledger.attempts['a2'].outcome == 'success'
    assert runtime.ledger.current_state_id == 's1'
