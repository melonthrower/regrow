"""Offline contracts; native saved-frame model acceptance is recorded separately."""
from pathlib import Path
from PIL import Image
from regrow.records.snapshots import write_json, load, publish
from regrow.records.object_store import owned_tasks, owned_controls, observation_history
from regrow.records.region_evidence import new_region
from regrow.recognition.visual_region_locator import plan
from regrow.traversal import target_registration as target
import pytest


def test_related_history_is_disclosed_without_visibility_or_name_binding(tmp_path):
    records = {f'r{i:04d}': new_region(f'r{i:04d}', 'Panel') for i in range(1, 12)}
    records['r0002']['controls']['c0001'] = {'name': 'Editor'}
    records['r0003']['controls']['c0002'] = {'name': 'Editor'}
    controls, owners = target.target_candidates(records, 'Editor')
    assert controls == ['c0001', 'c0002'] and owners == ['r0002', 'r0003']
    result = plan(records, 'r0001', 'unused', required_regions=owners + list(records), locate=lambda *a: {'accepted': False})
    assert result['mode'] == 'relocate'
    assert [r['region'] for r in result['regions']][:3] == ['r0001', 'r0002', 'r0003']
    assert len(result['regions']) == 8
    assert all(not r['strong'] and not r['anchors'] for r in result['regions'])
    assert not target.registered(records, {'controls': controls, 'target': 'Editor'}, '0002')
    assert plan(records, 'r0001', 'unused', locate=lambda *a: {'accepted': False})['mode'] == 'local'


def seed(tmp_path):
    run = tmp_path / 'run';snap = run / 'knowledge_snapshots/seed';snap.mkdir(parents=True)
    frame = run / 'frame.png';image = Image.new('RGB', (40, 40))
    image.putdata([(x * 6, y * 6, (x + y) * 3) for y in range(40) for x in range(40)])
    image.save(frame)
    r = new_region('r0001', 'Toolbar')
    r['tasks'] = {name: {'task_type': 'region_content', 'status': 'pending', 'completion_condition': name} for name in ['first', 'second']}
    r['observations'] = [{'evidence': {'source_field': '/regions/0', 'source_call': '0002', 'observation': 'obs2'}}]
    write_json(snap/'regions/r0001/region.json', r)
    write_json(snap/'regions/r0002/region.json', new_region('r0002', 'Hidden panel'))
    write_json(run/'knowledge_current.json', {'snapshot': 'knowledge_snapshots/seed'})
    write_json(snap/'source.json', {})
    q = {'role': 'action_selection', 'stage': 'action', 'screenshots': [str(frame)], 'source': {'region': 'r0001', 'observation': 'obs0', 'task_region': 'r0001', 'task_name': 'first'}}
    proposal = {'action': 'click', 'target': 'Button', 'x': 5, 'y': 5}
    episode = 'repair_episodes/action/episode.json'
    write_json(run/episode, {'stage': 'action', 'path': episode, 'request': q, 'call': '0001', 'status': 'complete'})
    write_json(run/'calls/0001/request.json', q);write_json(run/'calls/0001/response.json', proposal)
    goal = {'call': '0001', 'episode': episode, 'task': {'region': 'r0001', 'name': 'first'}, 'target': 'Button', 'controls': [], 'regions': ['r0001'], 'frame': str(frame), 'supplements': 0, 'status': 'pending'}
    gap = {'item': 'Button gap', 'kind': 'control', 'name': 'Button', 'owner': 'Toolbar', 'proposal': {'name': 'Button', 'identity_evidence': 'Hidden panel'}}
    state = {'next_action_mode': 'explore', 'working_region': 'r0001', 'interactive_regions': ['r0001'], 'active_task': goal['task'], 'observation': {'id': 'obs2', 'image': str(frame), 'control_refs': []}, 'action_target_registration': goal, 'discovery_completion': {'pending': [gap], 'regions': ['r0001'], 'controls': [], 'calls': ['0002']}}
    write_json(snap/'runtime_state.json', state)
    return run, frame, {'discovery_context': {'region_names': {'r0001': 'r0001'}}}


def test_one_new_candidate_supplement_then_defer_and_resume_only_relevant_evidence(tmp_path):
    from regrow.traversal.task_deferral import resume_localized
    run, frame, request = seed(tmp_path)
    target.advance(run, '0002', request)
    _, _, state = load(run)
    assert state['next_action_mode'] == 'discover'
    assert state['action_target_registration']['supplements'] == 1
    assert state['action_target_registration']['completion_items'] == ['Button gap']
    target.advance(run, '0003', request)
    _, records, state = load(run)
    task = owned_tasks(records['r0001'])['first']
    assert task['status'] == 'blocked' and state['active_task']['name'] == 'second'
    assert state['discovery_completion']['pending'][0]['item'] == 'Button gap'
    resume_localized(records, ['r0001'], '0002', run=run, frame=frame)
    assert task['status'] == 'blocked'
    owned_controls(records['r0002'])['c0001'] = {'name': 'Renamed Button', 'observations': [{'image': str(frame), 'image_quality': 'clear', 'image_quality_reason': 'fixture', 'evidence': {'source_field': '/controls/0', 'source_call': '0004', 'observation': 'new-target'}}]}
    task['deferral']['source_call'] = 'new-defer'
    retries = {('r0001', 'first'): '0001'}
    resume_localized(records, ['r0002'], '0004', run=run, frame=frame, snapshot=load(run)[0], retry_targets=retries)
    assert task['status'] == 'blocked'
    task['deferral']['source_call'] = '0001'
    resume_localized(records, ['r0002'], '0004', run=run, frame=frame, snapshot=load(run)[0], retry_targets=retries)
    assert task['status'] == 'pending'
    assert not (run/'action_attempts').exists()


def test_registered_target_continues_with_unrelated_gaps_intact(tmp_path):
    run, frame, request = seed(tmp_path)
    def observed(records, state, *_):
        owned_controls(records['r0001'])['c0001'] = {'name': 'Renamed Button', 'observations': [{'image': str(frame), 'image_quality': 'clear', 'image_quality_reason': 'fixture', 'evidence': {'source_field': '/controls/0', 'source_call': '0004', 'observation': 'obs4'}}]}
        state['discovery_completion']['pending'][0].update(name='Other', item='Other gap')
    publish(run, 'accepted-target', observed)
    target.advance(run, '0004', request)
    _, records, state = load(run)
    assert state['next_action_mode'] == 'explore'
    assert state['action_target_registration']['status'] == 'registered'
    assert state['discovery_completion']['pending'][0]['item'] == 'Other gap'
    assert owned_tasks(records['r0001'])['first']['status'] == 'pending'


def test_target_supplement_preserves_unrelated_pending_and_normal_completion_contract():
    from regrow.recognition.discovery_completion import prepare_registration
    class Diagnostics:
        @staticmethod
        def collect(*args): return {'errors': []}
        @staticmethod
        def check(*args): pass
    gaps = [{'kind': 'control', 'item': name, 'proposal': {'name': name}} for name in ['target', 'other']]
    batch = {'pending': gaps, 'regions': ['r0001'], 'controls': []}
    reply = {'regions': [], 'controls': [], 'completion_updates': [{'item': 'target', 'resolution': 'excluded', 'region_index': None, 'control_index': None, 'evidence': 'not visible in the original frame'}]}
    records = {'r0001': new_region('r0001', 'Panel')}
    request = {'discovery_context': {'completion': True, 'completion_items': ['target']}}
    _, remaining, _, _ = prepare_registration(reply, request, records, batch, Diagnostics)
    assert remaining == [gaps[1]] and batch['pending'] == gaps
    with pytest.raises(ValueError, match='每个旧缺口'):
        prepare_registration(reply, {'discovery_context': {'completion': True}}, records, batch, Diagnostics)
