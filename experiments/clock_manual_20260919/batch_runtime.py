"""Persistent worker; reuse the selected run's native session and pending recovery."""
from pathlib import Path
import datetime
import json
import subprocess
import sys


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def execute(config_path, launch):
    config_path, launch = Path(config_path), Path(launch)
    config = json.loads(config_path.read_text())
    # Load native helpers from the pinned run source, not the CLI's checkout.
    sys.path.insert(0, config['source'])
    from register_update import read, write_json
    from run_source import source_hash, session_command
    from debug_loop import device_lock, live_run
    from batch_environment import preflight, prepare_new
    state = {'phase': 'preparing', 'started_utc': utc()}
    def save(**values):
        state.update(values); write_json(launch/'state.json', state)
    save()
    try:
        if source_hash(config['source']) != config['source_hash']:
            raise RuntimeError('Pinned traversal source changed')
        for row in config.get('dependencies', []):
            import hashlib
            if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Pinned shared dependency changed')
        base = config_path.parent
        descriptor = base/'run.json' if config.get('kind') == 'new' else config_path
        existing = read(descriptor) if descriptor.exists() else None
        if existing:
            run = Path(existing['run'])
        else:
            # Freeze the device identity too: never consult a mutable template
            # run when deciding which device to lock, reset or restart.
            run = launch/'device-lock-context'
            write_json(run/'run_manifest.json', read(base/'template-manifest.json'))
        with device_lock(run):
            if live_run(run):
                raise RuntimeError('Another native traversal owns this device')
            manifest = read(run/'run_manifest.json')
            if existing and Path(manifest['framework_source']).resolve() != Path(config['source']).resolve():
                raise RuntimeError('Run manifest and pinned source disagree')
            if config.get('clear_app_data') and manifest['app'] != 'org.gnome.clocks':
                raise ValueError('Data reset is currently supported only for org.gnome.clocks')
            preflight(manifest, launch/'preflight')
            if not existing:
                marker = base/'preparation-started.json'
                if marker.exists():
                    raise RuntimeError('Previous preparation was interrupted; inspect its evidence before a new preparation')
                write_json(marker, {'launch': str(launch), 'utc': utc()})
                run = prepare_new(config, manifest, launch)
                existing = {'run': str(run), 'source': config['source'], 'source_hash': config['source_hash'],
                            'total_call_limit': config['total_call_limit'], 'dependencies': config.get('dependencies', [])}
                write_json(descriptor, existing)
            manifest = read(run/'run_manifest.json')
            used = manifest['actual_model_calls']
            remaining = config['total_call_limit'] - used
            save(run=str(run), calls_before=used, total_call_limit=config['total_call_limit'], phase='ready')
            if remaining <= 0:
                save(phase='finished', reason='budget_limit', ended_utc=utc()); return 0
            sessions = sorted(base.glob('session-*/session.json'))
            numbers = [int(p.parent.name.split('-')[1]) for p in sessions]
            # Also preserve a session directory whose process died before session.json.
            numbers += [int(p.name.split('-')[1]) for p in base.glob('session-*') if p.is_dir() and p.name.split('-')[1].isdigit()]
            out = base/f'session-{max(numbers, default=0)+1:02d}'
            write_json(launch/'manifest-before.json', manifest)
            manifest['session_limits'] = {'max_http': remaining, 'max_gui_commands': None, 'max_rounds': None}
            write_json(run/'run_manifest.json', manifest)
            argv = session_command(run, out, 'auto')
            write_json(launch/'session-command.json', {'argv': argv, 'remaining_http': remaining,
                                                      'source_hash': config['source_hash']})
            save(phase='starting', session=str(out))
            with (launch/'session.log').open('xb') as log:
                child = subprocess.Popen(argv, cwd=config['source'], stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT)
                save(native_pid=child.pid)
                code = child.wait()
            latest = read(run/'run_manifest.json')
            if latest['actual_model_calls'] > config['total_call_limit']:
                raise RuntimeError('Native session exceeded the total call budget')
            account = read(out/'session.json') if (out/'session.json').exists() else {}
            save(phase='finished' if code == 0 else 'failed', exit_code=code,
                 reason=account.get('status', 'interrupted'), calls=latest['actual_model_calls'], ended_utc=utc())
            return code
    except BaseException as error:
        save(phase='failed', error_type=type(error).__name__, ended_utc=utc())
        raise


if __name__ == '__main__':
    sys.exit(execute(*sys.argv[1:]))
