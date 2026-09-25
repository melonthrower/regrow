import json
import subprocess


def test_fresh_desktop_uses_seed_image_new_storage_and_cleans(monkeypatch, tmp_path):
    from ops import coverage100_environment as environment
    commands = []
    monkeypatch.setattr(environment, '_free_port', lambda: 4000 + len(commands) + 1)
    monkeypatch.setattr(environment.subprocess, 'run', lambda command, **kwargs: commands.append(command) or subprocess.CompletedProcess(command, 0, 'container-id', ''))
    monkeypatch.setattr(environment, '_wait', lambda *args, **kwargs: None)
    class Response:
        status_code = 200
    class Requests:
        @staticmethod
        def get(*args, **kwargs): return Response()
    monkeypatch.setitem(__import__('sys').modules, 'requests', Requests)
    seed = tmp_path / 'seed.qcow2'; seed.write_bytes(b'seed')
    fresh = environment.start_fresh_desktop(name='coverage-test', qcow=str(seed), log_path=tmp_path/'launch.log')
    run = commands[0]
    assert run[0:5] == ['docker', 'run', '-d', '--rm', '--name']
    assert str(seed) in ' '.join(run)
    assert '/dev/kvm' in run and 'NET_ADMIN' in run
    assert all(value in run for value in ['RAM_SIZE=4G', 'CPU_CORES=4', 'DISK_SIZE=32G'])
    assert json.loads((tmp_path/'launch.command.json').read_text()) == run
    assert 'type=volume,dst=/storage' in run
    fresh.cleanup()


def test_fresh_android_is_read_only_and_terminates(monkeypatch):
    from ops import coverage100_environment as environment
    monkeypatch.setattr(environment, '_free_port', lambda: 5600)
    calls = []
    class Process:
        def terminate(self): calls.append('terminate')
        def wait(self, **kwargs): calls.append('wait')
        def kill(self): calls.append('kill')
    monkeypatch.setattr(environment.subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr(environment.subprocess, 'run', lambda *args, **kwargs: type('Result', (), {'stdout':'1'})())
    monkeypatch.setattr(environment, '_wait', lambda *args, **kwargs: None)
    fresh = environment.start_fresh_android()
    fresh.cleanup()
    assert calls == ['terminate', 'wait']


def test_desktop_waits_for_controller_and_preserves_failed_launch(monkeypatch, tmp_path):
    from ops import coverage100_environment as environment
    import requests
    import pytest
    seed = tmp_path/'seed'; seed.write_bytes(b'seed')
    monkeypatch.setattr(environment.subprocess, 'run', lambda command, **kw:
        subprocess.CompletedProcess(command, 0, 'owned-container', ''))
    attempts = []
    def get(*args, **kw):
        attempts.append(True)
        if len(attempts) == 1:
            raise requests.ConnectionError('booting')
        return type('Response', (), {'status_code': 200})()
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(environment.time, 'sleep', lambda _: None)
    environment.start_fresh_desktop(name='test', qcow=str(seed), log_path=tmp_path/'ok.log')
    assert len(attempts) == 2
    monkeypatch.setattr(environment.subprocess, 'run', lambda command, **kw:
        subprocess.CompletedProcess(command, 125, '', 'seed mount failed'))
    with pytest.raises(subprocess.CalledProcessError):
        environment.start_fresh_desktop(name='test', qcow=str(seed), log_path=tmp_path/'failed.log')
    failure = json.loads((tmp_path/'failed.log').read_text())
    assert failure['returncode'] == 125 and failure['stderr'] == 'seed mount failed'
