"""Same-attempt evidence repair keeps unrelated blockers and the original record."""
from copy import deepcopy
import pytest
from tests.test_entry_observation import case, prepare_update
from regrow.records import task_settlement as task_settlement

@pytest.mark.parametrize('remaining', ['', 'Destination purpose is still unknown'])
def test_same_attempt_reassessment_resolves_only_filled_gap(remaining):
    (records, owner, task, state, entry) = case()
    (binding, receipt) = prepare_update(records, owner, task, state)
    owner['actions']['a']['control'] = 'link'
    binding['control_ref'] = 'link'
    row = {'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': entry, 'next_action': None, 'registration_gap': 'Destination purpose was not registered'}
    task_settlement.settle_task(owner, binding, {'task_update': row, 'action_result': owner['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert task['status'] == 'blocked'
    old = deepcopy(task['blocker'])
    owner['actions']['a']['evidence']['result_call'] = 'new-review'
    row['registration_gap'] = remaining
    task_settlement.settle_task(owner, binding, {'task_update': row, 'action_result': owner['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert task['status'] == ('blocked' if remaining else 'done')
    assert task['attempts'] == ['a']
    if not remaining:
        assert {k: v for (k, v) in task['blocker_history'][-1].items() if k != 'resolved_by'} == old
        assert task['blocker_history'][-1]['resolved_by']['source_call'] == 'new-review'
        assert owner['actions']['a']['entry_registration']['region'] == 'page'
        assert records['page']['tasks'] == {}

@pytest.mark.parametrize('change', ['other_attempt', 'ownership', 'exception'])
def test_reassessment_cannot_clear_an_unrelated_blocker(change):
    (records, owner, task, state, entry) = case()
    (binding, receipt) = prepare_update(records, owner, task, state)
    owner['actions']['a']['control'] = 'link'
    binding['control_ref'] = 'link'
    task.update(status='blocked', blocker={'attempt': 'a', 'condition': 'review_required', 'reason': 'unresolved'}, deferral={'attempt': 'a', 'retry_when': 'explicit_evidence_registration'})
    if change == 'other_attempt':
        task['blocker']['attempt'] = 'earlier'
    if change == 'ownership':
        task['deferral']['retry_when'] = 'explicit_task_ownership_review'
    if change == 'exception':
        task['blocker']['exception'] = 'unexpected_exit'
    old = deepcopy(task['blocker'])
    row = {'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': entry, 'next_action': None, 'registration_gap': ''}
    task_settlement.settle_task(owner, binding, {'task_update': row, 'action_result': owner['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert task['status'] == 'blocked' and task['blocker'] == old

@pytest.mark.parametrize('same_frame', [True, False])
def test_local_discovery_keeps_only_same_frame_partition_members(tmp_path, same_frame):
    from tests.test_discovery_incremental import seed, save_call, ROOT, module
    from regrow.recognition import locator as locator
    (m, run, q, reply) = seed(tmp_path)
    q['discovery_context'].update(mode='local', partition_context={'focus': 'r0001', 'sha256': module().fingerprint(run / 'frame.png') if same_frame else 'older-frame', 'regions': [{'region': 'r0001', 'bounds': [0, 0, 100, 50]}, {'region': 'r0002', 'bounds': [0, 50, 100, 100]}]})
    q['discovery_context']['visual_plan']['next_offset'] = 0
    q['response_schema'] = locator.schema(ROOT, 'local')
    reply['regions'] = reply['regions'][:1]
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    assert set(state['interactive_regions']) == ({'r0001', 'r0002'} if same_frame else {'r0001'})
    assert records['r0002']['observations'] == [] and (not records['r0002']['controls'])

def test_correction_shares_one_attachment_without_changing_first_role():
    from tests.test_action_correction_single_frame import job, ROOT, mod
    value = job('task_result_review')
    value['request']['screenshots'] = ['supplement.png']
    value['request']['frame_context'] = {'supplement.png': 'Current inventory evidence'}
    value['supplements'] = [{'image': 'supplement.png', 'source_call': 'global'}, {'image': 'supplement.png', 'source_call': 'local'}]
    before = deepcopy(value)
    q = mod('step_repair').request(ROOT, value, {})
    assert q['screenshots'] == ['supplement.png']
    assert q['frame_context']['supplement.png'] == 'Current inventory evidence'
    assert 'global' in q['user_prompt'] and 'local' in q['user_prompt'] and (value == before)

def test_same_attempt_valid_continuation_reopens_question_without_answer():
    (records, owner, task, state, entry) = case()
    (binding, receipt) = prepare_update(records, owner, task, state)
    owner['actions']['a']['control'] = 'link'
    binding['control_ref'] = 'link'
    task.update(status='blocked', blocker={'attempt': 'a', 'condition': 'review_required', 'reason': 'options unknown'}, deferral={'attempt': 'a', 'retry_when': 'explicit_evidence_registration'})
    owner['actions']['a']['registration_gap'] = 'options unknown'
    row = {'knowledge': '', 'findings': [], 'entry': None, 'registration_gap': 'options still unknown', 'next_action': {'region': owner['name'], 'control': owner['controls']['link']['name'], 'action': 'click', 'reason': 'previous action closed overlay; goal remains open'}}
    task_settlement.settle_task(owner, binding, {'task_update': row, 'action_result': owner['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert task['status'] == 'pending' and 'blocker' not in task
    assert not task.get('completion_basis') and (not task.get('knowledge'))
    assert task['attempts'] == ['a'] and task['blocker_history'][-1]['reason'] == 'options unknown'
    assert owner['actions']['a']['next_action']['control'] == 'link'
    assert not owner['actions']['a'].get('registration_gap')
