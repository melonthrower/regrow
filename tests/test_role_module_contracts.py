"""Role entry points preserve discovery, task context and candidate-only updates."""
from copy import deepcopy
import json

from tests.test_recovery_discovery import ROOT, mod, seeded_run
from tests.test_stepwise_resume_route import fixture


def test_locator_keeps_recovery_goal_and_historical_identity_context(tmp_path):
    run = seeded_run(tmp_path)
    registry = mod('discovery_step')
    registry.await_discovery(run, 'returned.png', 'role-entry')
    before = (run / 'knowledge_current.json').read_bytes()
    request = mod('locator').request_from_run(ROOT, run)
    context = json.loads(request['user_prompt'])
    assert request['stage'] == 'discovery'
    assert context['待继续的工作区块'] == 'Menu'
    assert request['discovery_context']['focus'] == 'r1'
    assert request['screenshots'] == [str(run.resolve() / 'returned.png')]
    assert (run / 'knowledge_current.json').read_bytes() == before


def test_task_proposer_exposes_current_controls_without_claiming_inventory_complete():
    _, records, state = fixture()
    state['interactive_regions'] = ['menu']
    before = deepcopy((records, state))
    request = mod('task_proposer').plan_request(ROOT, records, state, 'menu')
    context = json.loads(request['user_prompt'])
    assert request['role'] == 'task_proposal' and not request['action_ready']
    assert request['source'] == {'region': 'menu', 'observation': 'now'}
    assert context['控件'][0]['name'] == '打开菜单'
    assert request['screenshots'] == ['frame.png']
    assert (records, state) == before


def test_result_updater_does_not_turn_failed_delivery_into_recovery_or_success():
    updater = mod('result_updater')
    reply = {'action_result': {'exception': 'external_app'}, 'regions': [], 'controls': []}
    result = updater.route_update(ROOT, reply, {'exit_code': 1}, schema={'type': 'object'})
    assert result['status'] == 'execution_unconfirmed'
    assert result['next_action_mode'] == 'review_execution'
    result = updater.route_update(ROOT, reply, {'exit_code': 0}, schema={'type': 'object'})
    assert result['status'] == 'validated_candidate'
    assert result['next_action_mode'] == 'recover'


def test_scheduler_allows_leaving_known_foreground_without_control_inventory():
    _, records, state = fixture()
    for record in records.values():
        record['transitions'] = []
        record['controls'] = {}
    records['main']['out_of_scope_reason'] = '当前菜单不探索业务'
    mod('traversal_scheduler').schedule_local_inspection(records, state)
    assert state['working_region'] == 'menu'
    assert state['next_action_mode'] == 'explore'
    assert state['reason'] == 'navigation_from_foreground'
    assert 'inspection_region' not in state
