"""One CLI for new desktop batches, persistent resume and truthful status."""
from pathlib import Path
import argparse
import datetime
import fcntl
import grp
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid

from register_update import write_json
from debug_loop import freeze, read, live_run
from run_source import source_hash


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--new', type=Path, metavar='OUTPUT', help='Create a new batch in a new output directory')
    mode.add_argument('--resume', type=Path, metavar='RUN_JSON', help='Continue the same run with its remaining total budget')
    mode.add_argument('--status', type=Path, metavar='RUN_JSON', help='Read status; never launch or capture')
    parser.add_argument('--template-run', type=Path, help='Existing desktop run supplying device/app/scope configuration')
    parser.add_argument('--max-calls', type=int, help='Total new-batch HTTP budget, including corrections and recovery')
    parser.add_argument('--clear-app-data', action='store_true', help='Back up and clear supported app data before a new run')
    parser.add_argument('--restart-container', action='store_true', help='Restart the configured container before a new run')
    args = parser.parse_args(argv)
    if args.new:
        if not args.template_run or args.max_calls is None or args.max_calls <= 0:
            parser.error('--new requires --template-run and positive --max-calls')
    elif args.template_run or args.max_calls is not None or args.clear_app_data or args.restart_container:
        parser.error('Creation/reset/budget arguments are only valid with --new; resume preserves the existing contract')
    return args


def config_for(args, source):
    if not args.new:
        path = (args.resume or args.status).expanduser().resolve()
        config = read(path)
        if not isinstance(config, dict):
            raise ValueError('Run configuration does not exist or is not an object')
        for key in ('source', 'source_hash', 'total_call_limit'):
            if key not in config:
                raise ValueError('Missing run configuration field: '+key)
        if not Path(config['source']).is_absolute() or type(config['total_call_limit']) is not int or config['total_call_limit'] <= 0:
            raise ValueError('Invalid pinned source or total budget')
        if config.get('kind') != 'new' and ('run' not in config or not Path(config['run']).is_absolute()):
            raise ValueError('Resume needs the original run.json (or new batch.json)')
        return path
    template = args.template_run.expanduser().resolve()
    manifest = read(template/'run_manifest.json')
    if manifest.get('platform') != 'desktop':
        raise ValueError('The batch entry currently supports desktop runs only')
    if args.clear_app_data and manifest['app'] != 'org.gnome.clocks':
        raise ValueError('Data reset is currently supported only for org.gnome.clocks')
    output = args.new.expanduser().resolve()
    # Native call_once locates its runtime repository through its run ancestors.
    repository = next((p for p in template.parents if (p/'gui_rewalk').is_dir()), None)
    if repository is None or not output.is_relative_to(repository):
        raise ValueError('Output must be inside the original runtime repository')
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output).free < 2 * 1024**3:
        raise RuntimeError('Output filesystem needs at least 2 GiB free')
    frozen = output/'source'; freeze(source, frozen)
    dependencies = []
    for name in ('gui_rewalk/src/core/explore/api_config.py', 'gui_rewalk/src/core/explore/agent.py', 'ops/coverage100_environment.py'):
        path = repository/name
        destination = output/'shared_dependencies'/name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, destination)
        dependencies.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    config = {'kind': 'new', 'template_run': str(template), 'output': str(output), 'source': str(frozen),
              'source_hash': source_hash(frozen), 'total_call_limit': args.max_calls,
              'clear_app_data': args.clear_app_data, 'restart_container': args.restart_container,
              'dependencies': dependencies}
    write_json(output/'template-manifest.json', manifest)
    write_json(output/'batch.json', config)
    return output/'batch.json'


def unit_state(unit):
    result = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '-p', 'SubState'],
                            capture_output=True, text=True, timeout=10)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def status(config_path):
    config_path = Path(config_path); config = read(config_path); base = config_path.parent
    latest = read(base/'batch-launch-current.json', {})
    launch = Path(latest['launch']) if latest else None
    state = read(launch/'state.json', {}) if launch else {}
    service = unit_state(latest['unit']) if latest else {}
    active = service.get('ActiveState') in ('active', 'activating')
    descriptor = base/'run.json' if config.get('kind') == 'new' else config_path
    selected = read(descriptor, {})
    run = Path(selected['run']) if selected.get('run') else None
    manifest = read(run/'run_manifest.json', {}) if run else {}
    calls = manifest.get('actual_model_calls', 0)
    phase = state.get('phase', 'not_started')
    native_pid = live_run(run) if run and not latest else None
    if not latest and run:
        sessions = sorted(base.glob('session-*/session.json'))
        previous = read(sessions[-1], {}) if sessions else {}
        if native_pid:
            phase = 'device_busy_external'
        elif previous.get('status') in ('running', 'interrupted'):
            phase = 'interrupted'
            state['reason'] = previous['status']
        elif previous:
            phase = 'finished'
            state['reason'] = previous.get('status')
    if latest and not active and phase not in ('finished', 'failed'):
        phase = 'interrupted' if state else 'startup_failed'
    elif active:
        session = Path(state['session']) if state.get('session') else None
        capture_files = set(session.rglob('*.capture.json')) if session else set()
        if run:
            capture_files.update(run.rglob('*.capture.json'))
        started = datetime.datetime.fromisoformat(state['started_utc']).timestamp() if state.get('started_utc') else 0
        waits = sorted((p for p in capture_files if p.stat().st_mtime >= started),
                       key=lambda p: p.stat().st_mtime_ns)
        if waits and read(waits[-1]).get('status') == 'waiting':
            phase = 'waiting_screenshot'
        elif calls > state.get('calls_before', calls) and run:
            last = run/'calls'/str(manifest['last_call']).zfill(4)
            phase = 'running' if (last/'response.json').exists() else 'waiting_model'
        else:
            phase = 'preparing' if not session else 'starting'
    return {'status': phase, 'service_active': active, 'native_pid': native_pid, 'calls': calls,
            'total_call_limit': config['total_call_limit'], 'remaining_calls': max(0, config['total_call_limit']-calls),
            'run': str(run) if run else None, 'session': state.get('session'),
            'reason': state.get('reason'), 'error_type': state.get('error_type'),
            'launch': str(launch) if launch else None}


def service_command(unit, worker, config_path, launch):
    # The existing user's docker membership may be newer than the user manager.
    # sg establishes that membership in the actual service, without sudo/root.
    group = grp.getgrgid(Path('/var/run/docker.sock').stat().st_gid).gr_name
    command = shlex.join([sys.executable, str(worker), str(config_path), str(launch)])
    return ['systemd-run', '--user', '--collect', '--unit='+unit,
            '--property=WorkingDirectory='+str(config_path.parent),
            '--property=StandardOutput=append:'+str(launch/'worker.log'),
            '--property=StandardError=append:'+str(launch/'worker.log'),
            '/usr/bin/sg', group, '-c', command]


def launch(config_path, source):
    config_path = Path(config_path); base = config_path.parent
    with (base/'.batch-launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = status(config_path)
        if current['service_active'] or current.get('native_pid'):
            return current
        config = read(config_path)
        if current['remaining_calls'] <= 0:
            return {**current, 'status': 'budget_limit'}
        folder = base/'launches'/uuid.uuid4().hex; folder.mkdir(parents=True, exist_ok=False)
        worker_source = folder/'launcher-source'; freeze(source, worker_source)
        unit = 'regrow-traversal-'+folder.name
        write_json(folder/'request.json', {'config': str(config_path), 'argv': sys.argv,
                                        'launcher_source_hash': source_hash(worker_source),
                                        'previous_status': current, 'unit': unit})
        write_json(base/'batch-launch-current.json', {'launch': str(folder), 'unit': unit})
        argv = service_command(unit, worker_source/'batch_runtime.py', config_path, folder)
        write_json(folder/'service-command.json', {'argv': argv})
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        (folder/'service-launch.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
        return status(config_path)


def main(argv=None):
    args = arguments(argv)
    source = Path(__file__).resolve().parent
    path = config_for(args, source)
    result = status(path) if args.status else launch(path, source)
    print(json.dumps({'config': str(path), **result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
