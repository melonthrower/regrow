"""Selected model evidence and archived action provenance remain separate."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from PIL import Image
from regrow.prompts import frame_context as frame_context
from regrow.prompts import output as output_contract
from regrow.traversal import step_repair as step_repair
from regrow.traversal import result_updater as result_updater
from regrow.traversal import parameter_evidence_review as parameter_evidence_review
from regrow.records import region_behavior_split as region_behavior_split
ROOT = Path(result_updater.__file__).parent

def test_disabled_arrays_do_not_publish_unreachable_fields_or_glossary():
    schema = {'type': 'object', 'properties': {'controls': {'type': 'array', 'maxItems': 0, 'items': {'type': 'object', 'properties': {'findings': {'type': 'string'}}, 'required': ['findings']}}}, 'required': ['controls']}
    saved = deepcopy(schema)
    assert 'controls: []' in output_contract.shape(schema)
    assert 'findings' not in output_contract.fields(schema)
    assert 'controls_item' not in output_contract.shape(schema)
    assert schema == saved

def test_update_builder_and_correction_use_after_without_changing_archived_inputs():
    images = ['action_attempts/a/before.png', 'action_attempts/a/after.png']
    q = result_updater.build_update_request(ROOT, {}, images)
    assert q['screenshots'] == images[1:]
    assert 'source_region_split必须为null' in q['system_prompt']
    with_basis = result_updater.build_update_request(ROOT, {'动作前已登记几何': {'source': 'before'}}, images)
    assert 'source_region_split通常填null' in with_basis['system_prompt']
    assert 'acted_control为动作前记录实际执行的控件' in with_basis['system_prompt']
    job = dict(stage='update', request=q, candidate={}, history=[], supplements=[{'image': 'later.png', 'observation': {'finding': 'later state'}}], error='missing identity')
    corrected = step_repair.request(ROOT, job, {})
    assert corrected['screenshots'] == corrected['image_refs'] == images[1:]
    assert 'later state' in corrected['user_prompt']
    assert images == ['action_attempts/a/before.png', 'action_attempts/a/after.png']

def test_transport_guard_rejects_multiple_frames_instead_of_truncating():
    q = {'screenshots': ['before', 'after'], 'image_refs': ['before', 'after']}
    old = deepcopy(q)
    with pytest.raises(ValueError):
        frame_context.validate(q)
    assert q == old
    assert frame_context.primary({**q, 'role': 'observation_update'}) == 'after'
    q['response_schema'] = {'type': 'object', 'properties': {'decision': {'type': 'string'}}}
    frame_context.validate(q)
    q['response_schema']['properties']['proposal'] = {'type': 'array', 'items': {'type': 'object', 'properties': {'bbox': {'type': 'object'}}}}
    with pytest.raises(ValueError, match='bbox'):
        frame_context.validate(q)

def test_parameter_review_retains_real_effort_without_history_image_attachment():
    context = {'最近连续动作': [{'动作记录': 'a3', '实际归属': 'preparation', '观察': 'selected city, Add enabled'}]}
    region = {'task_inventory': {'review': {'kind': 'parameter_facts', 'context': context, 'task': 'search', 'key': 'k', 'frames': ['old-before.png', 'old-after.png']}}}
    q = {'user_prompt': '{}', 'screenshots': ['selected.png'], 'source': {}}
    parameter_evidence_review.augment(q, region)
    assert q['screenshots'] == q['image_refs'] == ['selected.png']
    assert json.loads(q['user_prompt'])['待补参数事实的原任务证据'] == context

def test_before_geometry_is_not_taken_from_a_different_frame(tmp_path):
    before = tmp_path / 'before.png'
    other = tmp_path / 'other.png'
    Image.new('RGB', (20, 20), 'white').save(before)
    Image.new('RGB', (20, 20), 'black').save(other)
    obs = {'evidence': {'observation': 'o'}, 'source_image': str(before), 'bbox': dict(left=0, top=0, right=20, bottom=20)}
    region = {'id': 'r', 'name': 'panel', 'observations': [obs], 'controls': {'c': {'name': 'button', 'observations': [deepcopy(obs)]}}}
    binding = {'observation_ref': 'o', 'control_ref': 'c'}
    assert region_behavior_split.before_objects(region, binding, tmp_path, before)['acted_control']['name'] == 'button'
    assert region_behavior_split.before_objects(region, binding, tmp_path, other) is None

def test_source_split_cannot_invent_unobserved_before_geometry():
    with pytest.raises(ValueError, match='缺少'):
        region_behavior_split.bind_geometry({}, None)
    box = dict(left=1, top=2, right=3, bottom=4)
    basis = {'region': {'bbox': box}, 'acted_control': {'bbox': box}, 'controls': [{'bbox': box}]}
    split = {'region': {'bbox': box}, 'controls': [{'name': 'new', 'bbox': box}], 'acted_control': 'new'}
    assert region_behavior_split.bind_geometry(split, basis) == split
    split['controls'][0]['bbox'] = {**box, 'right': 9}
    with pytest.raises(ValueError):
        region_behavior_split.bind_geometry(split, basis)

@pytest.mark.parametrize('legacy', [False, True])
def test_suspended_update_checks_archived_images_separately_from_sent_frame(tmp_path, legacy):
    from regrow.traversal import suspended_updates as suspended_updates
    write = step_repair.atomic
    folder = tmp_path / 'action_attempts/a'
    folder.mkdir(parents=True)
    for name in ('before.png', 'after.png'):
        (folder / name).write_bytes(b'saved evidence')
    write(folder / 'receipt.json', {'exit_code': 0})
    episode = 'repair_episodes/a/episode.json'
    archive = 'suspended_steps/a'
    frames = ['action_attempts/a/after.png']
    if legacy:
        frames.insert(0, 'action_attempts/a/before.png')
    job = {'stage': 'update', 'attempt': 'a', 'status': 'suspended', 'path': episode, 'request': {'role': 'observation_update', 'screenshots': frames}, 'branch_switch': {'archive': archive}}
    write(tmp_path / episode, job)
    write(tmp_path / archive / 'pending_step.json', {'episode': episode})
    write(tmp_path / archive / 'execution_pending.json', {'attempt': 'a'})
    assert suspended_updates.restore_next(tmp_path, tmp_path / 'later.png')
    assert step_repair.pending(tmp_path)['attempt'] == 'a'
    assert (folder / 'before.png').read_bytes() == b'saved evidence'

def test_task_review_after_owner_edit_uses_current_observation_not_historical_before(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from regrow.traversal import repair_stages as repair_stages
    oldhelper = repair_stages.helper
    monkeypatch.setattr(repair_stages, 'helper', lambda n: SimpleNamespace(load=lambda r: (tmp_path, {}, {'observation': {'image': 'current.png'}})) if n == 'discovery_step' else SimpleNamespace(request=lambda root, run, source, frames: {'screenshots': frames}) if n == 'task_result_review' else oldhelper(n))
    q = repair_stages.refresh(ROOT, tmp_path, {'stage': 'task_result_review', 'request': {'source': {}, 'screenshots': ['action_attempts/old/before.png'], 'user_prompt': '{}'}})
    assert q['screenshots'] == [str(tmp_path / 'current.png')]

@pytest.mark.parametrize('compatible', [False, True])
@pytest.mark.parametrize('after_comparison', [False, True])
def test_retained_identity_resume_checks_candidate_contract_before_spending_a_call(tmp_path, compatible, after_comparison):
    request = {'role': 'observation_update', 'screenshots': ['after.png'], 'response_schema': {'type': 'object', 'properties': {'decision': {'enum': ['continue']}}, 'required': ['decision'], 'additionalProperties': False}}
    candidate = {'decision': 'continue'} if compatible else {'old_task_result': 'pending'}
    job = {'path': 'repair_episodes/saved/episode.json', 'stage': 'update', 'attempt': 'real-a', 'request': request, 'candidate': candidate, 'status': 'repair', 'repairs': 1, 'observations': 0, 'history': [{'framework': 'rebuilt_stage_image_contract', 'original_request': 'saved-original.json'}], 'control_identity_candidates': [{'control': 'stable-c'}], 'service_retry_request': {'role': 'control_identity_selection'}, 'service_retry_used': True, 'service_error_history': [{'call': 'old-failed'}], 'call': 'old-candidate', 'seen': [], 'supplements': []}
    if after_comparison:
        job.pop('control_identity_candidates')
        job['history'].append({'call': 'identity-call', 'role': 'control_identity_comparison'})
    before = deepcopy(job)
    step_repair.atomic(tmp_path / job['path'], job)
    step_repair.atomic(tmp_path / 'pending_step.json', {'episode': job['path']})
    (tmp_path / 'after.png').write_bytes(b'original after evidence')

    def unexpected(*args):
        raise AssertionError('No model or GUI before checkpoint')
    runner = step_repair.Runner(ROOT, tmp_path, unexpected, unexpected, lambda : 0)
    with pytest.raises(step_repair.Paused, match='等待下一轮额度'):
        runner.perform('update')
    after = step_repair.pending(tmp_path)
    assert after['attempt'] == 'real-a' and after['repairs'] == 1
    assert after['service_retry_used'] and after['service_error_history'] == before['service_error_history']
    assert (tmp_path / 'after.png').read_bytes() == b'original after evidence'
    if compatible:
        assert after == before
    else:
        archive = after['history'][-1]['original_episode']
        assert step_repair.read(tmp_path / archive) == before
        assert after['status'] == 'initial' and after['candidate'] is None
        assert 'control_identity_candidates' not in after and 'service_retry_request' not in after
        assert after['request'] == request
        retry = deepcopy(after)
        retry.update(status='repair', candidate={'new_bad_answer': True})
        assert not step_repair.refresh_retained_identity_candidate(tmp_path, retry)
        assert retry['status'] == 'repair'
