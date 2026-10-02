"""Content refusal must not repeat GUI delivery or block sibling tasks."""
from copy import deepcopy
import json
import subprocess

import pytest

from tests.test_stepwise_deferral import setup
from tests.test_stepwise_task_correction import repair
from tests.test_stepwise_resume_route import ROOT


REFUSAL = {'status': 402, 'body': json.dumps({'error': {
    'message': '检测到有敏感词', 'type': 'param_error', 'code': '402'}}, ensure_ascii=False)}


def refused_call(run, module, requests, failure=REFUSAL):
    def call(q):
        requests.append(deepcopy(q))
        ref = f'{len(requests):04d}'
        module.atomic(run / 'calls' / ref / 'request.json', q)
        module.atomic(run / 'calls' / ref / 'http_error.json', failure)
        module.atomic(run / 'run_manifest.json', {'last_call': ref})
        raise subprocess.CalledProcessError(1, ['model'])
    return call


def test_content_refusal_retries_once_then_blocks_only_selected_task(tmp_path):
    run, q, discovery = setup(tmp_path)
    module = repair()
    requests = []
    runner = module.Runner(ROOT, run, refused_call(run, module, requests), None, lambda: 6)
    with pytest.raises(module.Paused) as stopped:
        runner.perform('action', q)
    assert stopped.value.status == 'task_deferred'
    assert len(requests) == 2 and requests[0] == requests[1]
    _, records, state = discovery.load(run)
    assert records['r1']['tasks']['Policy']['status'] == 'blocked'
    assert records['r1']['tasks']['Settings']['status'] == 'pending'
    assert records['r1']['tasks']['Policy']['deferral']['trigger']['kind'] == 'model_service_error'
    assert records['r1']['tasks']['Policy']['deferral']['retry_when'] == 'explicit_service_retry'
    assert module.pending(run) is None
    assert not (run / 'execution_pending.json').exists()
    assert not records['r1'].get('registration_gaps', {}).get('suspended_branch')


def test_content_refusal_after_action_keeps_pending_registration(tmp_path):
    run, q, discovery = setup(tmp_path)
    module = repair()
    requests = []
    module.atomic(run / 'execution_pending.json', {'attempt': 'a1'})
    before = (run / 'knowledge_current.json').read_bytes()
    runner = module.Runner(ROOT, run, refused_call(run, module, requests), None, lambda: 6)
    with pytest.raises(module.Paused) as stopped:
        runner.perform('update', q, 'a1')
    assert stopped.value.status == 'correction_blocked'
    assert len(requests) == 2 and all(r == q for r in requests)
    job = module.pending(run)
    assert job['stage'] == 'update' and job['attempt'] == 'a1'
    assert module.read(run / 'execution_pending.json') == {'attempt': 'a1'}
    assert (run / 'knowledge_current.json').read_bytes() == before
    assert len(job['service_error_history']) == 2


def test_failed_content_request_is_not_reopened_by_automatic_capture(tmp_path):
    run, q, discovery = setup(tmp_path)
    module = repair()
    job = {'path': 'repair_episodes/refusal/episode.json', 'stage': 'discovery',
        'status': 'blocked', 'attempt': None, 'request': q,
        'service_failure': {'call': '0001', 'error': REFUSAL}}
    module.atomic(run / job['path'], job)
    module.atomic(run / 'pending_step.json', {'episode': job['path']})
    frame = run / 'fresh.png'
    frame.write_bytes(b'capture')
    before = (run / 'knowledge_current.json').read_bytes()
    assert not module.reopen_blocked(run, frame)
    assert (run / 'knowledge_current.json').read_bytes() == before
    assert module.pending(run)['path'] == job['path']


def test_explicit_service_resume_keeps_attempt_and_failure_history(tmp_path):
    run, q, discovery = setup(tmp_path)
    module = repair()
    requests = []
    module.atomic(run / 'execution_pending.json', {'attempt': 'a1'})
    runner = module.Runner(ROOT, run, refused_call(run, module, requests), None, lambda: 6)
    with pytest.raises(module.Paused):
        runner.perform('update', q, 'a1')
    before = deepcopy(module.pending(run))
    result = module.resume_service_failure(run)
    assert result['stage'] == 'update' and result['attempt'] == 'a1'
    assert result['request'] == before['request']
    assert result['service_error_history'] == before['service_error_history']
    assert result['service_retry_used'] is True
    assert result['status'] == 'initial' and not result.get('service_failure')
    assert result['service_resume_history'][-1]['failure'] == before['service_failure']
    assert module.read(run / 'execution_pending.json') == {'attempt': 'a1'}


def test_explicit_task_resume_reopens_only_its_original_task(tmp_path):
    run, q, discovery = setup(tmp_path)
    from PIL import Image
    frame = run / 'resume.png'
    Image.new('RGB', (1080, 2340)).save(frame)
    discovery.publish(run, 'real-frame', lambda records, state, *args:
        state['observation'].update(image=str(frame)))
    module = repair()
    requests = []
    runner = module.Runner(ROOT, run, refused_call(run, module, requests), None, lambda: 6)
    with pytest.raises(module.Paused):
        runner.perform('action', q)
    episode = next((run / 'repair_episodes').glob('*/episode.json'))
    job = module.read(episode)
    module.resume_service_failure(run, job['path'])
    _, records, state = discovery.load(run)
    assert records['r1']['tasks']['Policy']['status'] == 'pending'
    assert records['r1']['tasks']['Settings']['status'] == 'pending'
    assert records['r1']['tasks']['Policy']['deferral_history'][-1]['trigger']['kind'] == 'model_service_error'
    assert state['active_task'] == {'region': 'r1', 'name': 'Policy'}
    assert module.pending(run)['path'] == job['path']


@pytest.mark.parametrize('failure', [{'status': 402}, {'status': 402, 'body': '{"error":{"message":"insufficient balance"}}'}])
def test_payment_status_alone_is_not_classified_as_content_refusal(failure):
    assert not repair().content_rejection(failure)


def test_discovery_refusal_keeps_stage_gap_without_blocking_region_tasks(tmp_path):
    from tests.test_stepwise_branch_switch import fixture
    from tests.test_stepwise_region_tasks import tasks
    run, job, discovery, frame = fixture(tmp_path)
    (run / 'execution_pending.json').unlink()
    job.update(stage='discovery', attempt=None)
    job['request']['source'].pop('task_name', None)
    module = repair()
    module.atomic(run / job['path'], job)
    module.atomic(run / 'calls/0675/http_error.json', REFUSAL)
    branch = tasks().helper('branch_switch')
    q = branch.request(ROOT, run, job, frame, REFUSAL, '0675')
    branch.commit(run, job, q, {'decision': 'switch', 'next_region': 'Other',
        'reason': '当前发现请求被服务拒绝，保留缺口并继续独立工作'}, '0676')
    _, records, state = discovery.load(run)
    assert records['r1']['tasks']['Policy']['status'] == 'pending'
    assert records['r1']['tasks']['Settings']['status'] == 'pending'
    assert records['r1']['registration_gaps']['suspended_branch']['failed_call'] == '0675'
    assert state['working_region'] == 'r2' and state['next_action_mode'] == 'discover'


def test_refusal_then_valid_reply_uses_normal_inventory_registration(tmp_path):
    from tests.test_stepwise_region_tasks import proposal, row
    run, q, discovery = setup(tmp_path)
    module = repair()
    requests = []
    refused = refused_call(run, module, requests)
    def call(request):
        if not requests:
            return refused(request)
        requests.append(deepcopy(request))
        records = discovery.load(run)[1]
        reply = proposal([{**row(name=c['name'], control=c['name']), 'findings': []}
            for c in records['r1']['controls'].values()])
        module.atomic(run / 'calls/0002/request.json', request)
        module.atomic(run / 'calls/0002/response.json', reply)
        return '0002', reply
    job = module.Runner(ROOT, run, call, None, lambda: 6).perform('task_proposal', q)
    assert job['status'] == 'complete' and requests[0] == requests[1]
    assert discovery.load(run)[1]['r1']['task_inventory']['source_call'] == '0002'
    assert module.pending(run) is None
    assert not (run / 'execution_pending.json').exists()


def test_service_resume_cannot_release_an_independent_blocker(tmp_path):
    run, q, discovery = setup(tmp_path)
    module = repair()
    requests = []
    with pytest.raises(module.Paused):
        module.Runner(ROOT, run, refused_call(run, module, requests), None, lambda: 6).perform('action', q)
    episode = next((run / 'repair_episodes').glob('*/episode.json'))
    discovery.publish(run, 'new-blocker', lambda records, state, *args:
        records['r1']['tasks']['Policy']['blocker'].update(condition='foreground_exception', exception='unexpected_exit'))
    before = (run / 'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError, match='来源不匹配'):
        module.resume_service_failure(run, module.read(episode)['path'])
    assert (run / 'knowledge_current.json').read_bytes() == before
    assert module.pending(run) is None


def test_native_retry_does_not_duplicate_run_scope_or_frame_context(tmp_path):
    from PIL import Image
    module = repair()
    transport = module.helper('recover_external')
    module.atomic(tmp_path / 'run_manifest.json', {'exploration_scope': 'Clock 本地功能'})
    frame = tmp_path / 'current.png'
    Image.new('RGB', (1080, 2340)).save(frame)
    q = {'user_prompt': '按真实当前图执行原任务', 'screenshots': [str(frame)]}
    once = transport.with_frame_context(transport.with_run_scope(q, tmp_path), tmp_path)
    twice = transport.with_frame_context(transport.with_run_scope(once, tmp_path), tmp_path)
    assert twice == once
