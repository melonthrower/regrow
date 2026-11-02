"""Persistent worker; reuse the selected run's native session and pending recovery."""
from pathlib import Path
import datetime
import json
import subprocess
import sys

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def call_allowance(config, used):
    """A review boundary limits this session, independently of the total cap."""
    limit=config.get('total_call_limit')
    if limit is not None and (type(limit) is not int or limit<=0):
        raise ValueError('total_call_limit must be positive or null')
    remaining=max(0,limit-used) if limit is not None else None
    interval=config.get('review_interval_calls')
    if interval is not None:
        if type(interval) is not int or interval<=0:
            raise ValueError('review_interval_calls must be positive')
        reviewed=config.get('last_reviewed_call',0)
        if type(reviewed) is not int or reviewed<0:
            raise ValueError('last_reviewed_call must be a nonnegative integer')
        boundary=max(0,interval-max(0,used-reviewed))
        remaining=boundary if remaining is None else min(remaining,boundary)
    return remaining


def finish_reason(config, status, used):
    if status!='budget_limit':return status
    limit=config.get('total_call_limit')
    if limit is not None and used>=limit:return 'budget_limit'
    # A native action needs both selection and result capacity. Its one-call
    # tail can request an early review; acknowledgement opens a fresh interval.
    return 'review_checkpoint' if config.get('review_interval_calls') else status

def execute(config_path, launch):
    (config_path, launch) = (Path(config_path), Path(launch))
    config = json.loads(config_path.read_text())
    sys.path.insert(0, config['source'])
    from regrow.records.snapshots import read
    from regrow.records.snapshots import write_json
    from regrow.runtime.run_source import source_hash
    from regrow.runtime.run_source import session_command
    from regrow.tools.debug_loop import device_lock
    from regrow.tools.debug_loop import live_run
    from regrow.tools.batch_environment import preflight
    from regrow.tools.batch_environment import prepare_new
    state = {'phase': 'preparing', 'started_utc': utc()}

    def save(**values):
        state.update(values)
        write_json(launch / 'state.json', state)
    save()
    try:
        if source_hash(config['source']) != config['source_hash']:
            raise RuntimeError('Pinned traversal source changed')
        for row in config.get('dependencies', []):
            import hashlib
            if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Pinned shared dependency changed')
        base = config_path.parent
        descriptor = base / 'run.json' if config.get('kind') == 'new' else config_path
        existing = read(descriptor) if descriptor.exists() else None
        if existing:
            run = Path(existing['run'])
        else:
            run = launch / 'device-lock-context'
            write_json(run / 'run_manifest.json', read(base / 'template-manifest.json'))
        with device_lock(run):
            if live_run(run):
                raise RuntimeError('Another native traversal owns this device')
            manifest = read(run / 'run_manifest.json')
            if existing and Path(manifest['framework_source']).resolve() != Path(config['source']).resolve():
                raise RuntimeError('Run manifest and pinned source disagree')
            if config.get('clear_app_data') and manifest['app'] != 'org.gnome.clocks':
                raise ValueError('Data reset is currently supported only for org.gnome.clocks')
            preflight(manifest, launch / 'preflight')
            if not existing:
                marker = base / 'preparation-started.json'
                if marker.exists():
                    raise RuntimeError('Previous preparation was interrupted; inspect its evidence before a new preparation')
                write_json(marker, {'launch': str(launch), 'utc': utc()})
                run = prepare_new(config, manifest, launch)
                existing = {'run': str(run), 'source': config['source'], 'source_hash': config['source_hash'], 'total_call_limit': config['total_call_limit'], 'dependencies': config.get('dependencies', [])}
                for key in ('review_interval_calls','last_reviewed_call'):
                    if key in config:existing[key]=config[key]
                write_json(descriptor, existing)
            manifest = read(run / 'run_manifest.json')
            used = manifest['actual_model_calls']
            if used == 0:
                from regrow.tools import startup_readiness
                if not startup_readiness.confirmed(run):
                    review = startup_readiness.capture(run)
                    save(phase='finished', reason='startup_review', run=str(run),
                         calls_before=0, startup_review=str(review), ended_utc=utc())
                    return 0
            remaining = call_allowance(config, used)
            save(run=str(run), calls_before=used, total_call_limit=config['total_call_limit'], phase='ready')
            if remaining is not None and remaining <= 0:
                save(phase='finished', reason=finish_reason(config,'budget_limit',used), ended_utc=utc())
                return 0
            sessions = sorted(base.glob('session-*/session.json'))
            numbers = [int(p.parent.name.split('-')[1]) for p in sessions]
            numbers += [int(p.name.split('-')[1]) for p in base.glob('session-*') if p.is_dir() and p.name.split('-')[1].isdigit()]
            out = base / f'session-{max(numbers, default=0) + 1:02d}'
            write_json(launch / 'manifest-before.json', manifest)
            manifest['session_limits'] = {'max_http': remaining, 'max_gui_commands': None, 'max_rounds': None}
            write_json(run / 'run_manifest.json', manifest)
            argv = session_command(run, out, 'auto')
            write_json(launch / 'session-command.json', {'argv': argv, 'remaining_http': remaining, 'source_hash': config['source_hash']})
            save(phase='starting', session=str(out))
            with (launch / 'session.log').open('xb') as log:
                child = subprocess.Popen(argv, cwd=config['source'], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                save(native_pid=child.pid)
                code = child.wait()
            latest = read(run / 'run_manifest.json')
            if config['total_call_limit'] is not None and latest['actual_model_calls'] > config['total_call_limit']:
                raise RuntimeError('Native session exceeded the total call budget')
            account = read(out / 'session.json') if (out / 'session.json').exists() else {}
            reason=finish_reason(config,account.get('status','interrupted'),latest['actual_model_calls'])
            save(phase='finished' if code == 0 else 'failed', exit_code=code, reason=reason, calls=latest['actual_model_calls'], ended_utc=utc())
            return code
    except BaseException as error:
        save(phase='failed', error_type=type(error).__name__, ended_utc=utc())
        raise
if __name__ == '__main__':
    sys.exit(execute(*sys.argv[1:]))
