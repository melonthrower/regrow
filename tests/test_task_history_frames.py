import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'


def module():
    spec = importlib.util.spec_from_file_location('history_frames_test', ROOT / 'history_context.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def attempt(run, name, control='target', committed=True, executed=True):
    folder = run / 'action_attempts' / name
    folder.mkdir(parents=True)
    for file, data in [('binding.json', {'region_ref': 'region', 'control_ref': control}),
                       ('receipt.json', {'exit_code': 0 if executed else 1})]:
        (folder / file).write_text(json.dumps(data))
    if committed:
        (folder / 'commit.json').write_text('{}')
    for stage in ('before', 'after'):
        (folder / (stage + '.png')).write_bytes((name + stage).encode())


def request():
    return {'system_prompt': 'original', 'user_prompt': '{}',
            'screenshots': ['current-before.png', 'current-after.png'], 'fixed_parts': []}


def test_two_business_attempts_retain_baseline_and_change_not_reopen(tmp_path):
    for name, control in [('a1', 'target'), ('a2', 'navigation'), ('a3', 'target'), ('a4', 'navigation')]:
        attempt(tmp_path, name, control)
    task = {'status': 'pending', 'control': 'target', 'attempts': ['a1', 'a2', 'a3', 'a4']}
    original = request()
    result = module().with_task_frames(ROOT, tmp_path, original, task, 'region')
    assert result['screenshots'] == original['screenshots'] + [
        'action_attempts/a1/after.png', 'action_attempts/a3/before.png', 'action_attempts/a3/after.png']
    assert result['screenshots'][:2] == original['screenshots']
    assert 'a1' in result['user_prompt'] and 'a3' in result['user_prompt']
    assert len(original['screenshots']) == 2


def test_unconfirmed_unsettled_or_failed_attempts_do_not_supply_chain(tmp_path):
    attempt(tmp_path, 'a1')
    attempt(tmp_path, 'a2', None)
    attempt(tmp_path, 'a3', committed=False)
    attempt(tmp_path, 'a4', executed=False)
    task = {'status': 'pending', 'control': 'target', 'attempts': ['a1', 'a2', 'a3', 'a4']}
    original = request()
    result = module().with_task_frames(ROOT, tmp_path, original, task, 'region')
    assert result['screenshots'] == original['screenshots'] + [
        'action_attempts/a1/before.png', 'action_attempts/a1/after.png']
    assert 'a2' not in result['user_prompt'] and 'a3' not in result['user_prompt'] and 'a4' not in result['user_prompt']


def test_no_confirmed_attempt_keeps_request_unchanged(tmp_path):
    attempt(tmp_path, 'a1', None)
    task = {'status': 'pending', 'control': 'target', 'attempts': ['a1']}
    original = request()
    assert module().with_task_frames(ROOT, tmp_path, original, task, 'region') == original


def test_current_frames_deduplicated_and_done_tasks_unchanged(tmp_path):
    attempt(tmp_path, 'a1')
    attempt(tmp_path, 'a2')
    task = {'status': 'pending', 'control': 'target', 'attempts': ['a1', 'a2']}
    original = request()
    (tmp_path / 'current-before.png').write_bytes(b'a2after')
    result = module().with_task_frames(ROOT, tmp_path, original, task, 'region')
    assert 'action_attempts/a2/after.png' not in result['screenshots']
    task['status'] = 'done'
    assert module().with_task_frames(ROOT, tmp_path, original, task, 'region') == original
