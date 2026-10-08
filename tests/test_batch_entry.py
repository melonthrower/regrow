"""Entry contract checks; fixtures do not claim live GUI/model acceptance."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


@pytest.fixture
def entry(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import batch_launch
    return batch_launch


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def configuration(tmp_path, used=38):
    run = tmp_path/'run'; run.mkdir()
    dump(run/'run_manifest.json', {'framework_source': str(ROOT), 'actual_model_calls': used,
        'last_call': used, 'platform': 'desktop', 'app': 'org.gnome.clocks', 'device': 'fixture-device'})
    config = tmp_path/'run.json'
    dump(config, {'run': str(run), 'source': str(ROOT), 'source_hash': 'fixture', 'total_call_limit': 100})
    return config, run


@pytest.mark.parametrize('argv', [
    ['--resume', 'run.json', '--clear-app-data'],
    ['--resume', 'run.json', '--max-calls', '100'],
    ['--status', 'run.json', '--restart-container'],
    ['--new', 'out', '--template-run', 'old', '--max-calls', '0'],
    ['--new', 'out', '--resume', 'run.json'],
])
def test_reject_conflicting_or_renewed_budget(entry, argv):
    with pytest.raises(SystemExit): entry.arguments(argv)


def test_new_reset_and_restart_are_explicit(entry):
    a = entry.arguments(['--new', 'out', '--template-run', 'old', '--max-calls', '100'])
    assert not a.clear_app_data and not a.restart_container


def test_dead_service_overrides_stale_running_state(tmp_path, entry, monkeypatch):
    config, run = configuration(tmp_path)
    launch = tmp_path/'launches/one'
    dump(tmp_path/'batch-launch-current.json', {'launch': str(launch), 'unit': 'fixture'})
    dump(launch/'state.json', {'phase': 'starting', 'calls_before': 0})
    monkeypatch.setattr(entry, 'unit_state', lambda _: {'ActiveState': 'inactive'})
    assert entry.status(config)['status'] == 'interrupted'
    assert entry.status(config)['remaining_calls'] == 62


def test_live_service_does_not_mean_progress(tmp_path, entry, monkeypatch):
    config, run = configuration(tmp_path)
    launch = tmp_path/'launches/one'; session = tmp_path/'session-01'
    dump(tmp_path/'batch-launch-current.json', {'launch': str(launch), 'unit': 'fixture'})
    dump(launch/'state.json', {'phase': 'starting', 'calls_before': 38, 'session': str(session)})
    monkeypatch.setattr(entry, 'unit_state', lambda _: {'ActiveState': 'active'})
    assert entry.status(config)['status'] == 'starting'
    dump(session/'round-0001/current.png.capture.json', {'status': 'waiting'})
    assert entry.status(config)['status'] == 'waiting_screenshot'
    dump(session/'round-0001/current.png.capture.json', {'status': 'recovered'})
    m = json.loads((run/'run_manifest.json').read_text()); m.update(actual_model_calls=39, last_call=39)
    dump(run/'run_manifest.json', m)
    assert entry.status(config)['status'] == 'waiting_model'
    dump(run/'calls/0039/response.json', {})
    assert entry.status(config)['status'] == 'running'
    dump(run/'action_attempts/a0011/after.png.capture.json', {'status': 'waiting'})
    assert entry.status(config)['status'] == 'waiting_screenshot'


def test_active_launch_is_idempotent(tmp_path, entry, monkeypatch):
    config, _ = configuration(tmp_path)
    monkeypatch.setattr(entry, 'status', lambda _: {'service_active': True, 'status': 'waiting_model'})
    monkeypatch.setattr(entry, 'freeze', lambda *_: pytest.fail('must not freeze or start a second worker'))
    assert entry.launch(config, ROOT)['service_active']


def test_worker_uses_durable_count_and_preserves_pending(tmp_path, entry, monkeypatch):
    import batch_runtime, batch_environment, debug_loop, run_source
    config, run = configuration(tmp_path)
    launch = tmp_path/'launch'; launch.mkdir()
    dump(run/'pending_step.json', {'episode': 'original'})
    before = (run/'pending_step.json').read_bytes()
    monkeypatch.setattr(run_source, 'source_hash', lambda _: 'fixture')
    monkeypatch.setattr(debug_loop, 'device_lock', lambda _: nullcontext())
    monkeypatch.setattr(debug_loop, 'live_run', lambda _: None)
    monkeypatch.setattr(batch_environment, 'preflight', lambda *_: None)
    monkeypatch.setattr(batch_environment, 'prepare_new', lambda *_: pytest.fail('resume must not reset or initialize'))
    class Child:
        pid = 123
        def __init__(self, argv, **kwargs):
            self.out = Path(argv[-2]); self.out.mkdir()
            assert json.loads((run/'run_manifest.json').read_text())['session_limits']['max_http'] == 62
        def wait(self):
            m = json.loads((run/'run_manifest.json').read_text()); m['actual_model_calls'] = 100
            dump(run/'run_manifest.json', m)
            dump(self.out/'session.json', {'status': 'budget_limit'})
            return 0
    monkeypatch.setattr(batch_runtime.subprocess, 'Popen', Child)
    batch_runtime.execute(config, launch)
    assert (run/'pending_step.json').read_bytes() == before
    assert json.loads((launch/'state.json').read_text())['reason'] == 'budget_limit'
    assert json.loads((launch/'manifest-before.json').read_text())['actual_model_calls'] == 38


def test_preflight_failure_stops_before_reset_or_session(tmp_path, entry, monkeypatch):
    import batch_runtime, batch_environment, debug_loop, run_source
    config, _ = configuration(tmp_path)
    launch = tmp_path/'launch'; launch.mkdir()
    monkeypatch.setattr(run_source, 'source_hash', lambda _: 'fixture')
    monkeypatch.setattr(debug_loop, 'device_lock', lambda _: nullcontext())
    monkeypatch.setattr(debug_loop, 'live_run', lambda _: None)
    def fail(*_): raise PermissionError('fixture Docker access denied')
    monkeypatch.setattr(batch_environment, 'preflight', fail)
    monkeypatch.setattr(batch_runtime.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('must not launch'))
    with pytest.raises(PermissionError): batch_runtime.execute(config, launch)
    assert json.loads((launch/'state.json').read_text())['phase'] == 'failed'
    assert not list(tmp_path.glob('session-*'))


def test_other_live_traversal_blocks_preparation(tmp_path, entry, monkeypatch):
    import batch_runtime, batch_environment, debug_loop, run_source
    config, _ = configuration(tmp_path); launch = tmp_path/'launch'; launch.mkdir()
    monkeypatch.setattr(run_source, 'source_hash', lambda _: 'fixture')
    monkeypatch.setattr(debug_loop, 'device_lock', lambda _: nullcontext())
    monkeypatch.setattr(debug_loop, 'live_run', lambda _: 456)
    monkeypatch.setattr(batch_environment, 'preflight', lambda *_: pytest.fail('must not touch device'))
    with pytest.raises(RuntimeError, match='owns this device'): batch_runtime.execute(config, launch)


def test_clock_backup_precedes_reset_and_unknown_paths_refuse(tmp_path, entry):
    import batch_environment
    class Desktop:
        package = 'org.gnome.clocks'
        def __init__(self, directories): self.directories=directories; self.commands=[]; self.data=b'old alarm data'
        def command(self, args):
            self.commands.append(args)
            if args[:2] == ['python', '-c']:
                data = json.dumps(self.directories).encode() if 'json.dumps' in args[-1] else b''
            elif args[1] == 'dump': data=self.data
            else:
                assert (tmp_path/'good/clocks.dconf').read_bytes() == self.data
                self.data=b''; data=b''
            return subprocess.CompletedProcess(args, 0, data, b'')
    good = Desktop([])
    batch_environment.clear_clock_data(good, tmp_path/'good')
    assert (tmp_path/'good/clocks.dconf').read_bytes() == b'old alarm data'
    bad = Desktop(['/home/user/.cache/clock'])
    with pytest.raises(RuntimeError, match='reset not performed'):
        batch_environment.clear_clock_data(bad, tmp_path/'bad')
    assert len(bad.commands) == 1


def test_new_preparation_uses_saved_target_not_mutable_template(tmp_path, entry, monkeypatch):
    import batch_runtime, batch_environment, debug_loop, run_source
    config = tmp_path/'batch.json'; template = tmp_path/'old'; launch = tmp_path/'launch'; launch.mkdir()
    dump(config, {'kind':'new', 'template_run':str(template), 'source':str(ROOT),
                 'source_hash':'fixture', 'total_call_limit':100})
    dump(tmp_path/'template-manifest.json', {'device':'intended-device', 'app':'org.gnome.clocks'})
    dump(template/'run_manifest.json', {'device':'wrong-device', 'app':'another.app'})
    monkeypatch.setattr(run_source, 'source_hash', lambda _: 'fixture')
    def lock(run):
        assert json.loads((run/'run_manifest.json').read_text())['device'] == 'intended-device'
        return nullcontext()
    monkeypatch.setattr(debug_loop, 'device_lock', lock)
    monkeypatch.setattr(debug_loop, 'live_run', lambda _: None)
    def preflight(manifest, _):
        assert manifest['device'] == 'intended-device'
        raise RuntimeError('fixture stop after confirming target')
    monkeypatch.setattr(batch_environment, 'preflight', preflight)
    with pytest.raises(RuntimeError, match='confirming target'): batch_runtime.execute(config, launch)
    assert not (tmp_path/'preparation-started.json').exists()


def test_existing_external_driver_is_not_restarted(tmp_path, entry, monkeypatch):
    config, _ = configuration(tmp_path)
    monkeypatch.setattr(entry, 'live_run', lambda _: 777)
    monkeypatch.setattr(entry, 'freeze', lambda *_: pytest.fail('must not start a competing worker'))
    result = entry.launch(config, ROOT)
    assert result['status'] == 'device_busy_external' and result['native_pid'] == 777


@pytest.mark.parametrize('saved_status', ['running', 'interrupted'])
def test_existing_stale_session_is_reported_interrupted(tmp_path, entry, monkeypatch, saved_status):
    config, _ = configuration(tmp_path)
    monkeypatch.setattr(entry, 'live_run', lambda _: None)
    dump(tmp_path/'session-01/session.json', {'status':saved_status})
    assert entry.status(config)['status'] == 'interrupted'
