"""Archived updates resume their saved evidence, never another GUI dispatch."""
from copy import deepcopy
import json
import subprocess
import pytest

from tests.test_stepwise_branch_switch import fixture
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def archived(tmp_path):
    run, job, discovery, frame = fixture(tmp_path)
    module = tasks().helper('step_repair')
    job.update(repairs=0, observations=0, seen=[], supplements=[],
        service_failure={'call': '0675', 'error': {'status': 503}}, service_retry_used=True)
    job['request']['screenshots'] = ['action_attempts/a1/before.png', 'action_attempts/a1/after.png']
    for name in ('before.png', 'after.png'):
        (run/'action_attempts/a1'/name).write_bytes(frame.read_bytes())
    module.atomic(run/job['path'], job)
    module.atomic(run/'calls/0675/http_error.json', {'status': 503})
    branch = tasks().helper('branch_switch')
    request = branch.request(ROOT, run, job, frame, {'status': 503}, '0675')
    branch.commit(run, job, request, {'decision': 'switch', 'next_region': 'Other',
        'reason': '原结果尚未登记，继续独立工作'}, '0676')
    return run, job, discovery, frame


def recovery():
    return tasks().helper('suspended_updates')


def test_native_round_recovers_archived_update_before_new_work(tmp_path, monkeypatch):
    run, job, discovery, frame = archived(tmp_path)
    step = tasks().helper('run_task_step')
    (run/'run_manifest.json').write_text(json.dumps({'app': 'org.test', 'device': 'test'}))
    monkeypatch.setattr(step, 'foreground_window', lambda _: None)
    monkeypatch.setattr(step.RecoveryRun, 'screenshot', lambda _, path: path.write_bytes(frame.read_bytes()))
    seen = []
    def perform(self, stage, *args):
        saved = step.step_repair.pending(run)
        seen.append((stage, saved['attempt'], saved['request']))
        raise step.step_repair.Paused('repair_pending', 'stop before model in auxiliary test')
    monkeypatch.setattr(step.step_repair.Runner, 'perform', perform)
    with pytest.raises(step.step_repair.Paused):
        step._run_step(ROOT, run, tmp_path/'round')
    assert seen == [('update', 'a1', job['request'])]
    assert json.loads((tmp_path/'round/budget.json').read_text())['gui_started'] == 0


def test_restore_uses_archive_even_when_later_runtime_lost_queue(tmp_path):
    run, job, discovery, frame = archived(tmp_path)
    discovery.publish(run, 'unrelated-progress', lambda records, state, *args:
        (state.pop('suspended_updates'), records['r2'].update(description='new independent evidence')))
    before = (run/'knowledge_current.json').read_bytes()
    saved_request = deepcopy(job['request'])
    assert recovery().restore_next(run, frame)
    restored = tasks().helper('step_repair').pending(run)
    assert restored['attempt'] == 'a1' and restored['request'] == saved_request
    assert restored['service_retry_used'] and restored['repairs'] == 0
    assert restored['service_resume_history'][-1]['failure'] == job['service_failure']
    assert (run/'knowledge_current.json').read_bytes() == before
    assert not recovery().restore_next(run, frame)


@pytest.mark.parametrize('missing', ['after.png', 'before.png', 'receipt.json'])
def test_missing_original_execution_evidence_stops_without_restoring(tmp_path, missing):
    run, _, _, frame = archived(tmp_path)
    (run/'action_attempts/a1'/missing).unlink()
    with pytest.raises(Exception, match='原动作|执行证据'):
        recovery().restore_next(run, frame)
    assert not (run/'execution_pending.json').exists()
    assert not (run/'pending_step.json').exists()


def test_restored_service_failure_keeps_pending_instead_of_archiving_again(tmp_path):
    run, _, _, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    module = tasks().helper('step_repair')
    calls = []
    def fail(q):
        calls.append(deepcopy(q))
        module.atomic(run/'run_manifest.json', {'last_call': '0677'})
        module.atomic(run/'calls/0677/request.json', q)
        module.atomic(run/'calls/0677/http_error.json', {'status': 503})
        raise subprocess.CalledProcessError(1, ['model'])
    with pytest.raises(module.Paused) as stopped:
        module.Runner(ROOT, run, fail, None, lambda: 6).perform('update')
    assert stopped.value.status == 'correction_blocked'
    assert len(calls) == 1
    assert module.pending(run)['attempt'] == 'a1'
    assert json.loads((run/'execution_pending.json').read_text())['attempt'] == 'a1'
    assert len(list((run/'suspended_steps').iterdir())) == 1


def test_unrelated_progress_is_allowed_but_changed_owner_is_a_conflict(tmp_path):
    run, _, discovery, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    discovery.publish(run, 'other-work', lambda records, state, *args:
        records['r2'].update(description='later work must remain'))
    snapshot, records, _ = discovery.load(run)
    binding = {'region_ref': 'r1', 'task_region': 'r1'}
    assert recovery().validate_commit(run, 'a1', {}, {}, binding, snapshot, records)
    discovery.publish(run, 'conflicting-work', lambda records, state, *args:
        records['r1']['tasks']['Policy'].update(status='done', result_evidence='later outcome'))
    snapshot, records, _ = discovery.load(run)
    before = (run/'knowledge_current.json').read_bytes()
    with pytest.raises(Exception, match='后续变化'):
        recovery().validate_commit(run, 'a1', {}, {}, binding, snapshot, records)
    assert (run/'knowledge_current.json').read_bytes() == before


def test_success_releases_only_owned_blocks_and_preserves_current_work(tmp_path):
    run, job, discovery, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    snapshot, records, previous = discovery.load(run)
    context = recovery().validate_commit(run, 'a1', {}, {},
        {'region_ref':'r1', 'task_region':'r1'}, snapshot, records)
    records['r1']['tasks']['Policy']['status'] = 'done'  # Normal settlement result.
    previous.update(active_task={'region':'r2', 'name':'later work'}, last_action_result={'action':'later'})
    state = {'observation': {'image':'old-after.png'}, 'working_region':'r1',
        'update_status':'committed', 'update_digest':'new-digest'}
    recovery().complete(records, previous, state, context, '0677', 'a1')
    assert records['r1']['tasks']['Policy']['status'] == 'done'
    assert 'blocker' not in records['r1']['tasks']['Policy']
    assert records['r1']['tasks']['Settings']['status'] == 'pending'
    assert not records['r1']['registration_gaps'].get('suspended_branch')
    assert state['working_region'] == 'r2' and state['last_action_result']['action'] == 'later'
    assert state['active_task'] == previous['active_task']
    assert state['observation'] is None and state['interactive_regions'] == []
    assert state['next_action_mode'] == 'discover'
    assert state['update_digest'] == 'new-digest'
    assert not state.get('suspended_updates')
    assert state['suspended_update_history'][-1]['resolved_by'] == '0677'


def test_interrupted_restore_reuses_original_episode_and_counters(tmp_path):
    run, job, _, frame = archived(tmp_path)
    module = tasks().helper('step_repair')
    job = module.read(run/job['path']);job.update(repairs=2, observations=1, seen=['rejected'])
    module.atomic(run/job['path'], job)
    marker = {'episode':job['path'], 'archive':'suspended_steps/0676', 'frame':str(frame)}
    module.atomic(run/'execution_pending.json', {'attempt':'a1','suspended_recovery':marker})
    assert recovery().restore_next(run, frame)
    restored = module.pending(run)
    assert restored['path'] == job['path'] and restored['repairs'] == 2
    assert restored['observations'] == 1 and restored['seen'] == ['rejected']


def test_model_blocked_result_is_not_reopened_with_archived_siblings(tmp_path):
    run, _, discovery, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    snapshot, records, previous = discovery.load(run)
    marker = recovery().validate_commit(run, 'a1', {}, {},
        {'region_ref':'r1','task_region':'r1','task_name':'Policy'}, snapshot, records)
    records['r1']['tasks']['Policy'].update(status='blocked', result_evidence='still unresolved')
    state = {'update_status':'committed','update_digest':'new'}
    recovery().complete(records, previous, state, marker, '0677', 'a1')
    assert records['r1']['tasks']['Policy']['status'] == 'blocked'
    assert records['r1']['tasks']['Settings']['status'] == 'pending'


def test_active_restored_update_refreshes_only_current_frame_not_original_evidence(tmp_path):
    run, job, _, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    second = run/'new-current.png';second.write_bytes(b'new-current')
    recovery().restore_next(run, second)
    module = tasks().helper('step_repair')
    assert module.pending(run)['request'] == job['request']
    assert recovery().context(run, 'a1')['frame'] == str(second.resolve())


def test_historical_edit_reply_cannot_mutate_current_records(tmp_path, monkeypatch):
    run, job, _, frame = archived(tmp_path)
    recovery().restore_next(run, frame)
    module = tasks().helper('step_repair');saved = module.pending(run)
    saved.update(status='blocked', error='await review', call='edit')
    module.atomic(run/saved['path'], saved)
    module.atomic(run/'calls/edit/response.json', {'resolution':'edit_record','record_edit':{}})
    runner = module.Runner(ROOT, run, lambda _:pytest.fail('no call'), None, lambda:6)
    monkeypatch.setattr(runner.adapters,'edit_proposal',lambda *args:pytest.fail('must not edit historical recovery'))
    with pytest.raises(module.Paused):runner.perform('update')


def test_next_round_relocalizes_with_its_new_capture(tmp_path, monkeypatch):
    run, _, discovery, frame = archived(tmp_path)
    # Already settled historical update; its discovery frame belongs to the
    # prior round. This round must use the observation it just captured.
    discovery.publish(run, 'historical-complete', lambda records, state, *args:
        state.update(reason='historical_update_registered', pending_frame=str(frame)))
    for path in (run/'suspended_steps').glob('*/pending_step.json'):
        module=tasks().helper('step_repair');job=module.read(run/module.read(path)['episode'])
        job['status']='complete';module.atomic(run/job['path'],job)
    step=tasks().helper('run_task_step')
    (run/'run_manifest.json').write_text(json.dumps({'app':'org.test','device':'test'}))
    monkeypatch.setattr(step,'foreground_window',lambda _:None)
    monkeypatch.setattr(step.RecoveryRun,'screenshot',lambda _,p:p.write_bytes(frame.read_bytes()))
    seen=[]
    def perform(self,stage,q=None,*args):
        seen.append((stage,q['screenshots']))
        raise step.step_repair.Paused('repair_pending','pause before model')
    monkeypatch.setattr(step.step_repair.Runner,'perform',perform)
    out=tmp_path/'next-round'
    with pytest.raises(step.step_repair.Paused):step._run_step(ROOT,run,out)
    assert seen[0]==('discovery',[str((out/'current.png').resolve())])
