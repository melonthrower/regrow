"""Bounded desktop preparation for the maintained batch entry."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import time

from register_update import read, write_json
from desktop_capture import display_capture
from desktop_transport import DesktopRun


def adapter(manifest):
    if manifest.get('platform') != 'desktop':
        raise ValueError('The batch entry currently supports desktop runs only')
    desktop = DesktopRun.__new__(DesktopRun)
    desktop.configure(manifest)
    desktop.package = manifest['app']
    return desktop


def preflight(manifest, folder, *, minimum_free=2 * 1024**3):
    """Run inside the same user service that will drive the traversal."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(folder).free < minimum_free:
        raise RuntimeError('Output filesystem needs at least 2 GiB free')
    desktop = adapter(manifest)
    container = manifest['desktop']['container']
    result = subprocess.run(['docker', 'inspect', '--format', '{{.Id}} {{.State.Running}}', container],
                            capture_output=True, text=True, timeout=15)
    (folder/'docker.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    identity, running = result.stdout.strip().split()
    if identity != container or running != 'true':
        raise RuntimeError('Expected running container ID does not match')
    # Unlike screenshot(), this probe has bounded subprocess timeouts and does
    # not turn missing Docker permissions into an infinite capture retry.
    (folder/'frame.png').write_bytes(display_capture(container))
    desktop.command(['python', '-c', 'print("controller-ready")'], timeout=10).check_returncode()
    from app_launcher import configured_model
    model = configured_model()
    if not model:
        raise RuntimeError('No model configured')
    write_json(folder/'result.json', {'container': identity, 'screenshot': 'frame.png',
                                    'controller': 'ready', 'model': model})
    return desktop


def clear_clock_data(desktop, folder):
    """Explicitly supported app reset; never guess another app's data paths."""
    if desktop.package != 'org.gnome.clocks':
        raise ValueError('Data reset is currently supported only for org.gnome.clocks')
    folder = Path(folder); folder.mkdir(exist_ok=False)
    def command(name, args):
        write_json(folder/(name+'.command.json'), {'argv': args})
        result = desktop.command(args)
        (folder/(name+'.log')).write_bytes(result.stdout + result.stderr)
        result.check_returncode()
        return result.stdout
    # Refuse unknown app directories before stopping or resetting the app.
    dirs = json.loads(command('cache-inventory', ['python', '-c',
        'import pathlib,json; p=pathlib.Path.home(); print(json.dumps([str(x) for d in [p/".local/share",p/".config",p/".cache"] if d.exists() for x in d.iterdir() if "clock" in x.name.lower()]))']))
    if dirs:
        raise RuntimeError('Unrecognized Clock data/cache directories; reset not performed')
    command('stop', ['python', '-c',
        'import subprocess; r=subprocess.run(["pkill","-x","gnome-clocks"]); assert r.returncode in (0,1)'])
    data = command('backup', ['dconf', 'dump', '/org/gnome/clocks/'])
    backup = folder/'clocks.dconf'; backup.write_bytes(data); backup.chmod(0o600)
    digest = hashlib.sha256(data).hexdigest()
    write_json(folder/'backup.json', {'sha256': digest, 'restore': 'dconf load /org/gnome/clocks/ < clocks.dconf'})
    if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Application backup verification failed')
    command('reset', ['dconf', 'reset', '-f', '/org/gnome/clocks/'])
    if command('verify-empty', ['dconf', 'dump', '/org/gnome/clocks/']).strip():
        raise RuntimeError('Application data reset did not read back empty')
    write_json(folder/'complete.json', {'data_empty': True, 'dedicated_cache_directories': dirs})


def prepare_new(config, manifest, launch):
    """Called only after locking and preflight; an existing run never enters here."""
    desktop = adapter(manifest)
    if config['clear_app_data']:
        clear_clock_data(desktop, launch/'app_data_backup')
    if config['restart_container']:
        desktop.command(['sync']).check_returncode()
        result = subprocess.run(['docker', 'restart', '--time', '60', manifest['desktop']['container']],
                                capture_output=True, timeout=120)
        (launch/'container-restart.log').write_bytes(result.stdout + result.stderr)
        result.check_returncode()
        deadline = time.monotonic() + 180
        while True:
            try:
                desktop.command(['python', '-c', 'print("ready")'], timeout=5).check_returncode()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Container did not become ready within 180 seconds')
                time.sleep(2)
    for index, code in enumerate(desktop.restart_commands()):
        result = desktop.command(['python', '-c', code])
        (launch/f'activation-{index}.log').write_bytes(result.stdout + result.stderr)
        result.check_returncode()
    time.sleep(2)
    frame = launch/'initial.png'
    frame.write_bytes(display_capture(manifest['desktop']['container']))
    window = desktop.foreground_window(); write_json(launch/'initial-window.json', window)
    if window['与目标应用一致'] is not True:
        raise RuntimeError('Target application is not in the foreground')
    from app_launcher import create_run
    run = create_run(Path(config['output'])/'runs', manifest['app'], manifest.get('app_name', manifest['app']),
                     manifest['device'], frame)
    created = read(run/'run_manifest.json')
    created.update(platform='desktop', desktop=manifest['desktop'], framework_source=config['source'],
                   app_data_reset=config['clear_app_data'], exploration_scope=manifest.get('exploration_scope', {}))
    write_json(run/'run_manifest.json', created)
    return run
