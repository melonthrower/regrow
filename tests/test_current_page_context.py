"""The page view must retain provenance without creating a second graph."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'


def module():
    path = ROOT/'page_context.py'
    assert path.is_file(), 'The current-page and parent-page context is not implemented'
    spec = importlib.util.spec_from_file_location('page_context_test', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def control(ref, name, obs, state=''):
    return {'id': ref, 'name': name, 'observations': [
        {'evidence': {'observation': obs}, 'state': state, 'text': name}], 'action_refs': []}


def region(ref, name, obs, controls=None, parent=None):
    return {'id': ref, 'name': name, 'parent_region': parent,
            'controls': controls or {}, 'observations': [{'evidence': {'observation': obs}}],
            'actions': {}, 'tasks': {}, 'transitions': [], 'reached_by': []}


def action(before, after, before_regions, after_regions, cid, changes=()):
    return {'control': cid, 'operation': 'click', 'delivery': 'executed_receipt_zero',
            'result': {'exception': 'none', 'description': 'Observed actual result'},
            'interactive_regions': after_regions, 'region_changes': list(changes),
            'evidence': {'before_observation': before, 'after_observation': after,
                         'before_regions': before_regions}}


def case(tmp_path):
    frame = tmp_path/'dialog.png'; frame.write_bytes(b'original observed screenshot')
    records = {
        'world': region('world', 'World', 'base', {'open': control('open', 'Add city', 'base')}),
        'nav': region('nav', 'Navigation', 'base', {'alarm': control('alarm', 'Alarms', 'base')}),
        'dialog': region('dialog', 'Add city dialog', 'opened', {
            'search': control('search', 'Search', 'opened'),
            'submit': control('submit', 'Add', 'opened', 'disabled')}),
        'alarms': region('alarms', 'Alarms', 'older'),
    }
    records['world']['tasks']['inspect'] = {'status': 'pending', 'handling': 'explore',
        'control': 'open', 'attempts': ['a1'], 'task_type': 'single_action'}
    records['world']['actions']['a1'] = action('base', 'opened', ['world', 'nav'], ['dialog'], 'open', [
        {'region': 'world', 'state': 'visible_background_blocked', 'evidence': 'dimmed'},
        {'region': 'nav', 'state': 'visible_background_blocked', 'evidence': 'dimmed'}])
    records['nav']['actions']['old'] = action('start', 'older', ['nav'], ['alarms'], 'alarm')
    records['nav']['transitions'] = [{'source_control': 'alarm', 'target_region': 'alarms', 'attempt': 'old'}]
    state = {'working_region': 'world', 'interactive_regions': ['dialog'],
        'active_task': {'region': 'world', 'name': 'inspect'}, 'next_action_mode': 'explore',
        'last_action_result': {'region': 'world', 'action': 'a1'},
        'region_path': ['world', 'dialog'], 'observation': {'id': 'opened', 'image': str(frame),
            'control_refs': ['search', 'submit'], 'foreground': {'description': 'modal', 'exception': 'none'}}}
    return records, state, frame


def test_current_dialog_keeps_parent_page_and_folded_other_entry(tmp_path):
    records, state, _ = case(tmp_path)
    before = deepcopy((records, state)); view = module().build(records, state)
    assert [n['ref'] for n in view['current_tree']] == ['dialog']
    assert {n['ref'] for n in view['background_regions']} == {'world', 'nav'}
    entry = view['origin']['entries'][-1]
    assert entry['from_regions'] == ['world', 'nav'] and entry['via']['attempt'] == 'a1'
    assert entry['via']['control'] == 'open'
    sibling = next(n for n in entry['parent_branches'] if n['ref'] == 'nav')
    assert sibling['entries'][0]['target_region'] == 'alarms'
    assert sibling['details_folded'] and sibling['completion'] == 'not_evaluated'
    assert view['goal']['region'] == 'world' and view['goal']['name'] == 'inspect'
    assert (records, state) == before


def test_same_region_input_preserves_real_parent_not_global_latest_incoming(tmp_path):
    records, state, _ = case(tmp_path)
    records['dialog']['actions']['a2'] = action('opened', 'searched', ['dialog'], ['dialog'], 'search')
    records['dialog']['actions']['a2']['operation'] = 'input_text'
    state['observation']['id'] = 'searched'; state['last_action_result'] = {'region': 'dialog', 'action': 'a2'}
    records['dialog']['reached_by'] = [{'source_region': 'alarms', 'attempt': 'unrelated-newer'}]
    view = module().build(records, state)
    assert len(view['origin']['entries']) == 1
    assert view['origin']['entries'][0]['via']['attempt'] == 'a1'
    assert 'alarms' not in view['origin']['entries'][0]['from_regions']


def test_closed_dialog_leaves_current_tree_and_current_ancestry(tmp_path):
    records, state, _ = case(tmp_path)
    records['dialog']['actions']['a2'] = action('opened', 'closed', ['dialog'], ['world', 'nav'], 'submit', [
        {'region': 'dialog', 'state': 'not_visible', 'evidence': 'closed'}])
    records['dialog']['actions']['a2']['result']['returns_to_previous'] = True
    state.update(interactive_regions=['world', 'nav'], active_task=None,
                 last_action_result={'region': 'dialog', 'action': 'a2'})
    state['observation'].update(id='closed', control_refs=['open', 'alarm'])
    view = module().build(records, state)
    assert {n['ref'] for n in view['current_tree']} == {'world', 'nav'}
    assert not view['background_regions'] and not view['origin']['entries']
    assert view['origin']['last_effect']['attempt'] == 'a2'


def test_bad_parent_cycle_is_reported_without_losing_nodes_or_mutating_graph(tmp_path):
    records, state, _ = case(tmp_path)
    records['group'] = region('group', 'Group', 'opened', {'plus': control('plus', '+', 'opened')}, 'dialog')
    records['dialog']['parent_region'] = 'group'
    state['interactive_regions'].append('group'); state['observation']['control_refs'].append('plus')
    before = deepcopy(records); view = module().build(records, state)
    assert {n['ref'] for n in view['current_tree']} == {'dialog', 'group'}
    assert any(v['kind'] == 'containment_cycle' for v in view['issues'])
    assert records == before


def test_explicit_current_containment_keeps_same_appearance_controls_separate(tmp_path):
    records, state, _ = case(tmp_path)
    for ref in ['hours', 'minutes']:
        records[ref] = region(ref, ref, 'opened', {ref+'+': control(ref+'+', '+', 'opened')}, 'dialog')
        state['interactive_regions'].append(ref); state['observation']['control_refs'].append(ref+'+')
    view = module().build(records, state)
    children = view['current_tree'][0]['children']
    assert {n['ref'] for n in children} == {'hours', 'minutes'}
    assert {n['controls'][0]['ref'] for n in children} == {'hours+', 'minutes+'}


def test_unconfirmed_replay_does_not_reuse_previous_action_as_current_parent(tmp_path):
    records, state, _ = case(tmp_path)
    state['observation']['id'] = 'navigation:replay'
    state['visual_navigation'] = {'observation': 'navigation:replay'}
    view = module().build(records, state)
    assert not view['origin']['entries'] and not view['background_regions']
    assert view['origin']['boundary'] == 'no_recorded_action_for_observation'
    assert view['localization_only']


def test_ambiguous_or_cyclic_action_history_is_not_selected_arbitrarily(tmp_path):
    records, state, _ = case(tmp_path)
    records['nav']['actions']['conflict'] = deepcopy(records['world']['actions']['a1'])
    view = module().build(records, state)
    assert not view['origin']['entries']
    assert view['origin']['boundary'] == 'ambiguous_action_observation'
    del records['nav']['actions']['conflict']
    records['world']['actions']['a1']['evidence']['before_observation'] = 'opened'
    view = module().build(records, state)
    assert view['origin']['boundary'] == 'cyclic_action_observation'


def test_request_refresh_marks_replaced_frame_historical_and_is_idempotent(tmp_path):
    records, state, frame = case(tmp_path); m = module()
    q = {'stage': 'action_selection', 'action_ready': True, 'user_prompt': 'original task',
         'dynamic_prompt': 'original task', 'source': {'region': 'dialog'},
         'screenshots': [str(frame)], 'image_refs': [str(frame)]}
    m.attach(q, records, state)
    assert q['page_context']['frame_relation'] == 'same_observation_frame'
    text = q['user_prompt']; m.refresh(q); assert q['user_prompt'] == text
    fresh = tmp_path/'new.png'; fresh.write_bytes(b'new current screenshot')
    q.update(screenshots=[str(fresh)], image_refs=[str(fresh)])
    m.refresh(q)
    assert q['page_context']['frame_relation'] == 'historical_structure_needs_recheck'
    assert q['user_prompt'].count('页面结构与父页面来路') == 1
    assert q['screenshots'] == [str(fresh)] and 'original task' in q['user_prompt']


def test_json_task_context_stays_json_and_preserves_catalog(tmp_path):
    records, state, frame = case(tmp_path); m = module()
    q = {'stage': 'task_proposal', 'action_ready': False, 'user_prompt': '{"控件":["Search"]}',
         'dynamic_prompt': '{"控件":["Search"]}', 'screenshots': [str(frame)], 'image_refs': [str(frame)]}
    m.attach(q, records, state); m.attach(q, records, state)
    assert json.loads(q['user_prompt'])['控件'] == ['Search']
    assert '页面结构与父页面来路' in json.loads(q['user_prompt'])
    rendered = json.loads(q['user_prompt'])['页面结构与父页面来路']
    assert '不是页面包含层级' in rendered and rendered.count('当前区块的直接进入来源') == 1


def test_parent_goal_can_advance_in_foreground_but_unrelated_or_missing_parent_cannot(tmp_path):
    records, state, frame = case(tmp_path); m = module()
    q = {'stage': 'task_proposal', 'action_ready': False, 'source': {'region': 'dialog'}}
    assert m.advances_goal(q, records, state)
    q.update(stage='action_selection', action_ready=True)
    q['source'].update(task_region='world', task_name='inspect')
    assert m.advances_goal(q, records, state)
    q['source']['task_name'] = 'unrelated'; assert not m.advances_goal(q, records, state)
    q['source']['task_name'] = 'inspect'; records['world']['actions'].clear()
    assert not m.advances_goal(q, records, state)


def test_stale_containment_and_control_state_are_not_current_facts(tmp_path):
    records, state, _ = case(tmp_path)
    records['dialog']['parent_region'] = 'world'
    state['interactive_regions'].append('world')
    state['observation']['id'] = 'new-unregistered-observation'
    view = module().build(records, state)
    assert {n['ref'] for n in view['current_tree']} == {'dialog', 'world'}
    assert any(v['kind'] == 'unconfirmed_containment' for v in view['issues'])
    submit = view['current_tree'][0]['controls'][1]
    assert submit['state'] == '' and submit['evidence'] == 'needs_recheck'


def test_discovery_gap_retains_only_historical_parent_and_no_priority(tmp_path):
    records, state, _ = case(tmp_path)
    state['observation']['id'] = 'discovery:new'
    q = {'stage': 'task_proposal', 'source': {'region': 'dialog'}}
    view = module().build(records, state)
    assert not view['origin']['entries']
    assert view['origin']['historical_entries'][0]['via']['attempt'] == 'a1'
    assert not module().advances_goal(q, records, state)
    q['user_prompt'] = 'task'
    module().attach(q, records, state)
    assert '当前区块的直接进入来源' not in q['user_prompt']
    assert '尚未确认连接到本轮观察' in q['user_prompt']
    assert q['dynamic_prompt'] == q['user_prompt']


def test_reentry_uses_new_entry_and_keeps_new_effect(tmp_path):
    records, state, _ = case(tmp_path)
    records['dialog']['actions']['a2'] = action('opened', 'closed', ['dialog'], ['world', 'nav'], 'submit')
    records['world']['actions']['a3'] = action('closed', 'opened-again', ['world', 'nav'], ['dialog'], 'open')
    records['world']['actions']['a3']['result']['description'] = 'Reopened after a city was added'
    state['observation']['id'] = 'opened-again'
    view = module().build(records, state)
    assert [e['via']['attempt'] for e in view['origin']['entries']] == ['a3']
    assert view['origin']['last_effect']['result']['description'] == 'Reopened after a city was added'


def test_normal_target_refresh_updates_page_frame_even_without_candidates(tmp_path):
    records, state, frame = case(tmp_path)
    from tests.test_stepwise_region_tasks import tasks
    q = {'action_ready': True, 'user_prompt': 'task', 'screenshots': [str(frame)], 'image_refs': [str(frame)]}
    module().attach(q, records, state)
    fresh = tmp_path/'fresh.png'; fresh.write_bytes(b'changed frame')
    q.update(screenshots=[str(fresh)], image_refs=[str(fresh)])
    tasks().helper('target_observation').refresh(q)
    assert q['page_context']['frame_relation'] == 'historical_structure_needs_recheck'


def test_discovery_map_is_prior_knowledge_even_on_the_same_saved_frame(tmp_path):
    records, state, frame = case(tmp_path)
    q = {'stage': 'discovery', 'user_prompt': '{}', 'screenshots': [str(frame)]}
    module().attach(q, records, state, usage='discovery', run=tmp_path)
    assert q['page_context']['usage'] == 'discovery'
    assert '发现前的历史地图' in q['user_prompt']
    assert '与本次截图一致的已登记观察' not in q['user_prompt']


def test_update_map_is_anchored_to_before_not_after_screenshot(tmp_path):
    records, state, frame = case(tmp_path)
    after = tmp_path/'after.png'; after.write_bytes(b'dialog closed')
    state['observation']['image'] = frame.name
    q = {'stage': 'observation_update', 'user_prompt': '{}', 'screenshots': [frame.name, after.name]}
    module().attach(q, records, state, usage='before_action', run=tmp_path)
    view = q['page_context']
    assert view['observation']['sha256'] and view['frame_relation'] == 'before_action_frame'
    assert '动作前地图' in q['user_prompt'] and '动作后结果尚未登记' in q['user_prompt']
    assert q['screenshots'] == [frame.name, after.name]


def test_live_map_marks_new_frame_pending_then_tracks_new_committed_observation(tmp_path):
    records, state, frame = case(tmp_path); m = module()
    (tmp_path/'live_frame.png').write_bytes(frame.read_bytes())
    view = m.live(records, state, tmp_path)
    assert view['sync_status'] == 'observed'
    (tmp_path/'live_frame.png').write_bytes(b'new GUI frame')
    assert m.live(records, state, tmp_path)['sync_status'] == 'checking'

    state['observation'].update(id='closed', image=str(tmp_path/'live_frame.png'), control_refs=['open'])
    state['interactive_regions'] = ['world']
    view = m.live(records, state, tmp_path)
    assert view['sync_status'] == 'observed'
    assert [n['ref'] for n in view['current_tree']] == ['world']
    (tmp_path/'execution_pending.json').write_text('{}')
    assert m.live(records, state, tmp_path)['sync_status'] == 'checking'


def test_live_map_distinguishes_visual_replay_from_registered_observation(tmp_path):
    records, state, frame = case(tmp_path)
    state['observation']['id'] = 'navigation:old'
    state['visual_navigation'] = {'observation': 'navigation:old', 'replay': 'old'}
    assert module().live(records, state, tmp_path)['sync_status'] == 'localized'
    state['observation']['id'] = 'opened'
    state['visual_navigation'] = {'observation': 'opened', 'controls': {'search': 'dialog'}}
    assert not module().build(records, state)['localization_only']


def test_known_parent_entries_survive_actions_after_discovery_gap(tmp_path):
    records, state, _ = case(tmp_path)
    records['dialog']['actions']['a2'] = action('discovery:new', 'typed', ['dialog'], ['dialog'], 'search')
    records['alarms']['actions']['another_entry'] = action('other-page', 'other-open', ['alarms'], ['dialog'], None)
    records['nav']['actions']['unexecuted'] = action('old', 'unknown', ['nav'], ['dialog'], 'alarm')
    records['nav']['actions']['unexecuted']['delivery'] = 'unconfirmed'
    state['observation']['id'] = 'typed'
    state['last_action_result'] = {'region': 'dialog', 'action': 'a2'}
    before = deepcopy((records, state)); m = module(); view = m.build(records, state)
    assert not view['origin']['entries']
    assert {e['via']['attempt'] for e in view['origin']['known_entries']} == {'a1', 'another_entry'}
    assert (records, state) == before
    q = {'stage': 'task_proposal', 'source': {'region': 'dialog'}, 'user_prompt': 'task'}
    m.attach(q, records, state)
    assert '已登记历史入口（未证明是本次来路）' in q['user_prompt']
    assert '当前区块的直接进入来源' not in q['user_prompt']
    assert '未绑定具体控件' in q['user_prompt']
    assert '无控件入口' not in q['user_prompt']
    assert not m.advances_goal(q, records, state)
    # A later transition retains only its proven suffix; the earlier entry stays unconnected.
    records['dialog']['actions']['a3'] = action('typed', 'left', ['dialog'], ['alarms'], 'submit')
    state.update(interactive_regions=['alarms'], last_action_result={'region': 'dialog', 'action': 'a3'})
    state['observation']['id'] = 'left'
    view = m.build(records, state)
    assert [e['via']['attempt'] for e in view['origin']['entries']] == ['a3']
    assert {e['via']['attempt'] for e in view['origin']['known_entries']} == {'a1', 'another_entry'}
