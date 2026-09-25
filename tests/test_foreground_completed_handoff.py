"""Offline handoff checks; synthetic records, no model or GUI execution."""
from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import fixture, ROOT
from tests.test_stepwise_region_tasks import tasks, proposal, row


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket, subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError('External actions forbidden in this offline test')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def completed_entry():
    flow, records, state = fixture()
    m = tasks()
    m.apply_plan(records['menu'], proposal([row('Open details', '打开菜单')]), 'source-plan')
    m.apply_plan(records['middle'], proposal([row('Inspect details', '打开中间区')]), 'detail-plan')
    task = records['menu']['tasks']['Open details']
    task.update(status='done', attempts=['entry'])
    state.update(working_region='menu', interactive_regions=['middle'],
                 last_action_result={'region':'menu', 'action':'entry'})
    return flow, records, state


def test_completed_entry_yields_to_observed_pending_work():
    flow, records, state = completed_entry()
    before = deepcopy(records)
    base = flow._assemble_action_context(ROOT, records, state, 'menu')
    assert base.get('navigation_advice')
    result = tasks().attach(ROOT, records, state, 'menu', base)
    assert result['source'].get('task_region') == 'middle'
    assert result['source']['task_name'] == 'Inspect details'
    assert not result.get('navigation_advice')
    assert records == before


@pytest.mark.parametrize('guard', ['pending_goal', 'unsettled', 'exception', 'navigation', 'preparation', 'no_completed_entry'])
def test_handoff_preserves_unfinished_or_unsafe_context(guard):
    _, records, state = completed_entry()
    if guard == 'pending_goal':
        records['menu']['tasks']['Open details']['status'] = 'pending'
        state['active_task'] = {'region':'menu', 'name':'Open details'}
    elif guard == 'unsettled': state['execution_pending'] = True
    elif guard == 'exception': state['observation']['foreground'] = {'exception':'blocking_popup'}
    elif guard == 'navigation': state['deferred_routing_target'] = 'main'
    elif guard == 'preparation': state['reason'] = 'verify_prepared_dependency'
    else: state.pop('last_action_result')
    before = deepcopy(state)
    assert not tasks().helper('task_routing').handoff(records, state)
    assert state == before


def test_completed_keyboard_preparation_does_not_keep_old_owner_as_working_region():
    _, records, state = completed_entry()
    previous = deepcopy(state)
    previous['active_task'] = {'region':'menu', 'name':'Open details'}
    before = deepcopy(records['menu']['tasks'])
    tasks().helper('task_routing').advance(records, previous, state, 'menu',
        {'task_region':'menu', 'task_name':'Open details', 'control_ref':None,
         'preparatory_action':True}, 'entry')
    assert state['working_region'] == 'middle'
    assert 'active_task' not in state
    for name, task in before.items():
        assert records['menu']['tasks'][name]['control'] == task['control']
        assert records['menu']['tasks'][name]['attempts'] == task['attempts']


def test_pending_parent_still_owns_cross_region_work():
    flow, records, state = completed_entry()
    records['menu']['tasks']['Open details'].update(status='pending', task_type='parameter')
    state['active_task'] = {'region':'menu', 'name':'Open details'}
    base = flow._assemble_action_context(ROOT, records, state, 'menu')
    result = tasks().attach(ROOT, records, state, 'menu', base)
    assert result['source']['task_region'] == 'menu'
    assert result['source']['task_name'] == 'Open details'
    assert state['working_region'] == 'menu'


@pytest.mark.parametrize('pending', [False, True])
def test_normal_retirement_persists_handoff_only_without_pending_receipt(tmp_path, pending):
    import json
    _, records, state = completed_entry()
    run = tmp_path/'run'; snapshot = run/'knowledge_snapshots/seed'
    for rid, region in records.items():
        folder = snapshot/'regions'/rid; folder.mkdir(parents=True)
        (folder/'region.json').write_text(json.dumps(region))
    (snapshot/'runtime_state.json').write_text(json.dumps(state))
    (snapshot/'source.json').write_text(json.dumps({'record_format':'region_image_knowledge'}))
    pointer = run/'knowledge_current.json'
    pointer.write_text(json.dumps({'snapshot':'knowledge_snapshots/seed'}))
    if pending: (run/'execution_pending.json').write_text('{"attempt":"unsettled"}')
    before = pointer.read_bytes()
    d = tasks().helper('discovery_step')
    assert d.retire_completed_goal(run) is not pending
    _, after_records, after_state = d.load(run)
    assert after_state['working_region'] == ('menu' if pending else 'middle')
    for rid, region in records.items():
        assert after_records[rid].get('tasks', {}) == region.get('tasks', {})
        assert after_records[rid]['actions'] == region['actions']
        assert set(after_records[rid]['controls']) == set(region['controls'])
    if pending: assert pointer.read_bytes() == before


def test_completed_cross_region_owner_can_handoff():
    _, records, state = completed_entry()
    previous = deepcopy(state)
    previous['active_task'] = {'region':'menu', 'name':'Open details'}
    state['last_action_result'] = {'region':'main', 'action':'entry'}
    tasks().helper('task_routing').advance(records, previous, state, 'main',
        {'task_region':'menu', 'task_name':'Open details', 'control_ref':None,
         'preparatory_action':True}, 'entry')
    assert state['working_region'] == 'middle'
    assert 'active_task' not in state


def test_visible_explicit_navigation_target_is_not_preempted():
    _, records, state = completed_entry()
    state.update(deferred_routing_target='main', interactive_regions=['main','middle'])
    before = deepcopy(state)
    assert not tasks().helper('task_routing').handoff(records, state)
    assert state == before
