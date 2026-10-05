"""A recorded bound action determines exploration progress; model status is ignored."""
from copy import deepcopy

import pytest

from tests.test_recovery_discovery import mod


@pytest.mark.parametrize('status', ['pending', 'blocked', 'done'])
def test_routing_preserves_settled_goal_and_evidence(status):
    task = {'control': 'ok', 'task_type': 'single_action', 'handling': 'explore',
            'action': 'click', 'status': 'pending', 'attempts': [],
            'reason': 'Confirm the setting and observe the original object feedback'}
    records = {
        'dialog': {'id': 'dialog', 'name': 'Inner dialog', 'tasks': {'confirm': task},
                   'controls': {'ok': {'name': 'OK'}}, 'actions': {'a1': {
                       'control': 'ok', 'operation': 'click', 'delivery': 'executed_receipt_zero',
                       'result': {'exception': 'none', 'description': 'Outer dialog visible'}}}},
        'outer': {'id': 'outer', 'name': 'Outer dialog', 'controls': {}, 'tasks': {}},
    }
    binding = {'region_ref': 'dialog', 'task_region': 'dialog', 'control_ref': 'ok', 'task_name': 'confirm'}
    evidence = 'Goal observed' if status == 'done' else 'Original feedback remains obscured'
    reply = {'action_result': {'exception': 'none'},
             'task_result': {'name': 'confirm', 'status': status, 'evidence': evidence, 'findings': []}}
    raw_reply = deepcopy(reply)
    old = {'working_region': 'dialog', 'active_task': {'region': 'dialog', 'name': 'confirm'}}
    state = {'working_region': 'dialog', 'interactive_regions': ['outer']}
    mod('region_tasks').settle_task(records['dialog'], binding, reply, 'a1', records)
    mod('task_routing').advance(records, old, state, 'dialog', binding, 'a1')
    assert task['status'] == 'done'
    assert task['result_evidence'] == 'Outer dialog visible'
    assert task['reason'] == 'Confirm the setting and observe the original object feedback'
    assert reply == raw_reply
    assert state['working_region'] == 'outer' and 'active_task' not in state



@pytest.mark.parametrize('retry', [None, 'explicit_task_ownership_review', 'explicit_result_review'])
def test_task_inventory_does_not_finish_new_goal_from_old_entry(retry):
    from tests.test_stepwise_region_tasks import tasks, proposal, row
    from tests.test_stepwise_resume_route import fixture
    _, records, _ = fixture()
    region = records['menu']
    goal = row()
    control = next(cid for cid, c in region['controls'].items() if c['name'] == goal['control'])
    region['actions']['old'] = {'control': control, 'operation': 'click',
        'delivery': 'executed_receipt_zero', 'interactive_regions': ['other'],
        'result': {'exception': 'none', 'description': 'Opened a dialog'}}
    if retry:
        tasks().apply_plan(region, proposal([goal]), 'old-plan')
        region['tasks'][goal['name']].update(status='blocked', deferral={'retry_when': retry})
    tasks().apply_plan(region, proposal([goal]), 'new-plan')
    task = region['tasks'][goal['name']]
    assert task['status'] == ('blocked' if retry else 'pending') and task['attempts'] == []
    assert mod('entry_evidence').known_entries(region, control, 'click')[0]['attempt'] == 'old'
