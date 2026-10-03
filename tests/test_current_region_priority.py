"""Keep current Region progress ahead of unrelated historical function finishing."""
from copy import deepcopy
import pytest
from tests.test_inventory_scroll_progress import plan_scroll
from tests.test_stepwise_region_tasks import ROOT


def case(tmp_path):
    m, run, records, state, _, _ = plan_scroll(tmp_path)
    records['r1']['tasks'][state['active_task']['name']]['status'] = 'done'
    state['active_task'] = None
    records['r2'] = deepcopy(records['r1'])
    records['r2'].update(id='r2', name='Other completed Region', controls={}, tasks={}, actions={},
                         task_inventory={'inventory': 'complete', 'controls': []})
    snapshot = m.helper('discovery_step').load(run)[0]
    return m, snapshot, records, state


def test_normal_current_inventory_precedes_history_without_settling_it(tmp_path):
    m, snapshot, records, state = case(tmp_path)
    original = deepcopy(records)
    def current():
        q = m.attach(ROOT, records, state, 'r1', {'progress': {}})
        assert q['stage'] == 'task_proposal' and not q['action_ready']
        return q
    assert m.helper('historical_inventory').request(ROOT, snapshot, records, state, current_request=current) is None
    assert records == original
    # A blocked local request must still allow the old finishing obligation.
    q = m.helper('historical_inventory').request(ROOT, snapshot, records, state,
        current_request=lambda: {'stage': 'task_blocked', 'action_ready': False, 'source': {'region': 'r1'}})
    assert q['stage'] == 'function_registration' and q['source']['region'] == 'r2'


@pytest.mark.parametrize('change', ['not_interactive', 'exception', 'recover', 'navigation', 'other_owner'])
def test_unconfirmed_or_nonlocal_work_does_not_hide_history(tmp_path, change):
    m, snapshot, records, state = case(tmp_path)
    q = {'stage': 'task_proposal', 'action_ready': False, 'source': {'region': 'r1'}}
    if change == 'not_interactive': state['interactive_regions'] = []
    elif change == 'exception': state['observation'].setdefault('foreground', {})['exception'] = 'blocking_popup'
    elif change == 'recover': state['next_action_mode'] = 'recover'
    elif change == 'navigation': q['navigation_advice'] = True
    else: q['source']['region'] = 'r2'
    result = m.helper('historical_inventory').request(ROOT, snapshot, records, state, current_request=lambda: q)
    assert result['stage'] == 'function_registration'


def test_current_local_action_precedes_history_but_other_task_does_not(tmp_path):
    m, snapshot, records, state = case(tmp_path)
    q = {'stage': 'action_selection', 'action_ready': True, 'source': {'region': 'r1', 'task_region': 'r1'}}
    history = m.helper('historical_inventory')
    assert history.request(ROOT, snapshot, records, state, current_request=lambda: q) is None
    q['source']['task_region'] = 'r2'
    assert history.request(ROOT, snapshot, records, state, current_request=lambda: q)['stage'] == 'function_registration'


def test_support_review_is_not_bypassed_or_eagerly_building_current(tmp_path):
    m, snapshot, records, state = case(tmp_path)
    records['r1']['task_inventory']['review'] = {'kind': 'function_support', 'reason': 'Missing support'}
    region = records['r1']
    image = snapshot/'regions/r1/history.png'
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b'evidence path only; request construction does not decode')
    region['observations'].append({'source_image': 'history.png', 'evidence': {'observation': 'old'}})
    def current():
        raise AssertionError('mandatory support review must run before constructing current request')
    q = m.helper('historical_inventory').request(ROOT, snapshot, records, state, current_request=current)
    assert q['function_support_review'] and q['source']['region'] == 'r1'


def test_navigation_from_foreground_to_work_precedes_unrelated_finishing(tmp_path):
    m, snapshot, records, state = case(tmp_path)
    state['working_region'] = 'r2'
    state['interactive_regions'] = ['r1']
    original = deepcopy((records, state))
    q = m.helper('stepwise_flow')._assemble_action_context(ROOT, records, state, 'r2')
    assert q['action_ready'] and q['navigation_advice']
    assert q['source']['region'] == 'r1' and q['source']['return_to'] == 'r2'
    assert m.helper('historical_inventory').request(
        ROOT, snapshot, records, state, current_request=lambda: q) is None
    assert (records, state) == original


@pytest.mark.parametrize('change', ['no_foreground', 'unobserved_source', 'different_goal', 'different_work', 'not_ready', 'recover', 'exception'])
def test_navigation_priority_requires_observed_source_and_original_goal(tmp_path, change):
    m, snapshot, records, state = case(tmp_path)
    state['working_region'] = 'r2'
    state['interactive_regions'] = ['r1']
    q = m.helper('stepwise_flow')._assemble_action_context(ROOT, records, state, 'r2')
    if change == 'no_foreground': state['interactive_regions'] = []
    elif change == 'unobserved_source': state['interactive_regions'] = ['r2']
    elif change == 'different_goal': q['source']['return_to'] = 'r1'
    elif change == 'different_work': q['source']['working_region'] = 'r1'
    elif change == 'not_ready': q['action_ready'] = False
    elif change == 'recover': state['next_action_mode'] = 'recover'
    else: state['observation'].setdefault('foreground', {})['exception'] = 'blocking_popup'
    result = m.helper('historical_inventory').request(
        ROOT, snapshot, records, state, current_request=lambda: q)
    assert result['stage'] == 'function_registration'


@pytest.mark.parametrize('confirmed', [True, False])
def test_parent_goal_foreground_inventory_uses_real_current_entry(tmp_path, confirmed):
    m, snapshot, records, state = case(tmp_path)
    state.update(working_region='r1', interactive_regions=['child'],
                 active_task={'region': 'r1', 'name': 'parent-goal'})
    records['r1']['tasks']['parent-goal'] = {'status': 'pending', 'handling': 'explore', 'attempts': []}
    state['observation']['id'] = 'current'
    records['r1']['actions']['entry'] = {'delivery': 'executed_receipt_zero',
        'interactive_regions': ['child'], 'evidence': {'before_observation': 'before',
        'after_observation': 'current' if confirmed else 'old', 'before_regions': ['r1']}}
    q = {'stage': 'task_proposal', 'source': {'region': 'child'}}
    result = m.helper('historical_inventory').request(ROOT, snapshot, records, state, current_request=lambda: q)
    if confirmed:
        assert result is None
    else:
        assert result['stage'] == 'function_registration'
