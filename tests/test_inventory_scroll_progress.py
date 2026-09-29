"""An explicit viewport investigation must not be trapped in same-frame inventory."""
from copy import deepcopy
import json

import pytest

from tests.test_stepwise_task_correction import saved
from tests.test_stepwise_region_tasks import tasks, row, proposal, ROOT


def plan_scroll(tmp_path, inventory='partial', handling='explore', prerequisite=None):
    run, q, _ = saved(tmp_path)
    m = tasks()
    op = {**row(name='辨认列表下缘被遮挡的条目', control='', handling=handling),
          'action': 'scroll', 'task_type': 'scroll', 'findings': [],
          'prerequisite': prerequisite}
    reply = proposal([op], inventory)
    reply['evidence'] = '容器明确，但下缘条目标签被遮挡，身份仍未知；需要滚动取得上下文。'
    folder = run / 'calls/901'
    folder.mkdir(parents=True)
    (folder/'request.json').write_text(json.dumps(q))
    (folder/'response.json').write_text(json.dumps(reply))
    before = deepcopy(m.helper('discovery_step').load(run)[1]['r1'])
    m.commit_plan(ROOT, run, '901')
    _, records, state = m.helper('discovery_step').load(run)
    return m, run, records, state, before, reply


def test_partial_inventory_scroll_enters_normal_action_and_retains_gap(tmp_path):
    m, run, records, state, before, reply = plan_scroll(tmp_path)
    region = records['r1']
    assert region['task_inventory']['inventory'] == 'partial'
    assert region['task_inventory']['evidence'] == reply['evidence']
    assert state['next_action_mode'] == 'explore'
    assert state['active_task'] == {'region': 'r1', 'name': '辨认列表下缘被遮挡的条目'}
    assert region['tasks'][state['active_task']['name']]['status'] == 'pending'
    assert region['actions'] == before['actions']
    assert set(region['controls']) == set(before['controls'])
    q = m.attach(ROOT, records, state, 'r1', {'progress': {}})
    assert q['action_ready'] and q['source']['task_type'] == 'scroll'
    assert q['source']['task_control'] is None and q['allow_scroll']
    assert q['response_schema']['properties']['action']['enum'] == ['scroll', 'none']
    assert not q['preparation_allowed'] and not q['allow_back'] and not q['allow_input']
    assert q['backend_candidates'] == []
    assert not m.coverage(region, records)['complete']
    # The original deficit must be reconsidered when the viewport task finishes.
    region['tasks'][state['active_task']['name']]['status'] = 'done'
    followup = m.attach(ROOT, records, state, 'r1', {'progress': {}})
    assert followup['stage'] == 'task_proposal'
    assert reply['evidence'] in followup['user_prompt']


@pytest.mark.parametrize('inventory,handling', [('uncertain', 'explore'), ('partial', 'defer'), ('partial', 'record')])
def test_uncertain_or_non_executable_scroll_does_not_bypass_discovery(tmp_path, inventory, handling):
    _, _, records, state, _, _ = plan_scroll(tmp_path, inventory, handling)
    assert state['next_action_mode'] == 'discover'
    assert not state.get('active_task')
    assert records['r1']['task_inventory']['inventory'] == inventory


def test_unmet_prerequisite_keeps_scroll_blocked(tmp_path):
    prerequisite = {'region': '未知区域', 'control': '未知控件', 'condition': '尚不可滚动',
                    'preparation': '先解锁', 'evidence': '当前未满足', 'permitted': False}
    _, _, records, state, _, _ = plan_scroll(tmp_path, prerequisite=prerequisite)
    assert state['next_action_mode'] == 'discover'
    task = records['r1']['tasks']['辨认列表下缘被遮挡的条目']
    assert task['status'] == 'blocked'
    assert task['blocker']['condition'] == 'prerequisite'


def test_historical_scroll_not_nominated_in_this_plan_is_not_selected(tmp_path):
    m, _, records, _, _, _ = plan_scroll(tmp_path)
    assert m.helper('inventory_scroll').select(records['r1'], proposal([], 'partial')) is None


def test_other_foreground_cannot_continue_partial_scroll_as_generic_action(tmp_path):
    m, _, records, state, _, _ = plan_scroll(tmp_path)
    records['r2'] = deepcopy(records['r1'])
    records['r2'].update(name='另一个区块', tasks={}, task_inventory={'inventory': 'complete'})
    state['interactive_regions'] = ['r2']
    q = m.attach(ROOT, records, state, 'r1', {'progress': {}})
    assert q.get('source', {}).get('task_name') is None


def test_visible_original_scroll_region_keeps_restriction_with_multiple_regions(tmp_path):
    m, _, records, state, _, _ = plan_scroll(tmp_path)
    records['r2'] = deepcopy(records['r1'])
    records['r2'].update(name='另一个区块', tasks={}, task_inventory={'inventory': 'complete'})
    state['interactive_regions'] = ['r2', 'r1']
    q = m.attach(ROOT, records, state, 'r2', {'progress': {}})
    assert q['source']['region'] == 'r1'
    assert q['response_schema']['properties']['action']['enum'] == ['scroll', 'none']


@pytest.mark.parametrize('change', ['other_region', 'not_interactive', 'exception', 'blocked'])
def test_partial_scroll_bypass_requires_current_executable_region(tmp_path, change):
    m, _, records, state, _, _ = plan_scroll(tmp_path)
    if change == 'other_region':
        state['active_task']['region'] = 'r2'
    elif change == 'not_interactive':
        state['interactive_regions'] = []
    elif change == 'exception':
        state['observation'].setdefault('foreground', {})['exception'] = 'blocking_popup'
    else:
        records['r1']['tasks'][state['active_task']['name']]['status'] = 'blocked'
    assert not m.helper('inventory_scroll').active(records, state, 'r1')


def test_current_partial_scroll_precedes_unrelated_historical_finishing(tmp_path):
    m, run, records, state, _, _ = plan_scroll(tmp_path)
    records['r2'] = deepcopy(records['r1'])
    records['r2'].update(id='r2', name='已探索的其他区块', controls={}, tasks={}, actions={},
        task_inventory={'inventory': 'complete', 'controls': []})
    snapshot=m.helper('discovery_step').load(run)[0]
    assert m.helper('historical_inventory').request(ROOT,snapshot,records,state) is None
    # The historical obligation remains available after the viewport task finishes.
    records['r1']['tasks'][state['active_task']['name']]['status']='done'
    assert m.helper('historical_inventory').request(ROOT,snapshot,records,state)['stage']=='function_registration'
