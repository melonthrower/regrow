"""Task-owned seed files and observed desktop readiness, outside the trajectory."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import time

import jsonschema


SETUP_SCHEMA = {
    'type': 'object', 'properties': {
        'assets': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'name': {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9_.-]*$'},
                'kind': {'type': 'string', 'enum': ['image', 'text']},
                'content': {'type': 'string'}},
            'required': ['name', 'kind', 'content'], 'additionalProperties': False}},
        'open_file': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        'initial_state': {'type': 'string'}},
    'required': ['assets', 'open_file', 'initial_state'], 'additionalProperties': False}

SETUP_CAPABILITIES = {
    'image': '标准1080×1440 PNG测试图片，content作为图片上的文字标签；不支持指定图层或复杂画面。',
    'text': 'UTF-8纯文本文件，content是完整文件内容；不是富文本文档。',
    'device': '桌面端可将生成文件放入独立目录，并用目标应用打开open_file；不能预设选中状态或执行目标修改。'}


def validate_setup(setup):
    jsonschema.validate(setup, SETUP_SCHEMA)
    names = [asset['name'] for asset in setup['assets']]
    if len(names) != len(set(names)):
        raise ValueError('Seed file names must be distinct')
    for asset in setup['assets']:
        suffix = Path(asset['name']).suffix.lower()
        if suffix not in (('.png',) if asset['kind'] == 'image' else ('.txt', '.md')):
            raise ValueError('Seed file extension does not match its kind')
    if setup['open_file'] is not None and setup['open_file'] not in names:
        raise ValueError('Seed open_file must name one of its assets')
    if setup['assets'] and not setup['initial_state'].strip():
        raise ValueError('Seed assets need an observable initial_state')


def materialize_seed(setup, output):
    """Produce exactly the requested files using the existing seed image maker."""
    validate_setup(setup)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'setup.json').write_text(json.dumps(setup, ensure_ascii=False, indent=2))
    assets = output / 'assets'
    assets.mkdir()
    files = []
    for asset in setup['assets']:
        path = assets / asset['name']
        if asset['kind'] == 'image':
            from tools.guitraverse_seed.shared_v1 import _make_image
            _make_image(path, asset['content'], '#385170')
        else:
            path.write_text(asset['content'], encoding='utf-8')
        files.append({'name': asset['name'], 'local_path': str(path.resolve()),
                      'kind': asset['kind'], 'size_bytes': path.stat().st_size})
    return files


def initialize_collection_environment(task, env, agent, app_name, output, *,
                                      platform='desktop', desktop_window_owner=None):
    """Start the declared seed file directly, avoiding lifecycle sample files."""
    from ..app_lifecycle import launch_app, wait_for_app
    if not (task.get('setup') or {}).get('open_file'):
        launch_app(env, app_name, desktop_window_owner=desktop_window_owner)
        if not wait_for_app(env, app_name, desktop_window_owner=desktop_window_owner):
            raise RuntimeError('Target application did not appear')
    seed, observation = prepare_collection_seed(task, env, agent, app_name, output, platform=platform)
    if desktop_window_owner is not None and not desktop_window_owner.bind_active(app_name):
        raise RuntimeError('Prepared application window could not be bound')
    return seed, observation


def prepare_collection_seed(task, env, agent, app_name, output, *, platform='desktop'):
    """Prepare declared resources and check the actual starting screen once.

    A missing setup preserves existing tasks' behavior. A declared initial state
    is checked even when no file is needed. No seed action enters the Collector.
    """
    setup = task.get('setup')
    if setup is None:
        return None, None
    validate_setup(setup)
    output = Path(output)
    report = {'ready': False, 'model_calls': 0,
              'instruction_id': task.get('instruction_id'),
              'source_ledger_digest': task.get('source_ledger_digest'),
              'files': [], 'events': [], 'initial_state': setup['initial_state']}
    try:
        files = materialize_seed(setup, output)
        if files and platform != 'desktop':
            raise ValueError('This seed file adapter currently supports desktop only')
        if files:
            remote_dir = '/tmp/regrow_collection/' + output.parent.name
            for item in files:
                remote = remote_dir + '/' + item['name']
                env.setup_controller._upload_file_setup([
                    {'local_path': item['local_path'], 'path': remote}])
                matched = env.controller.get_file(remote) == Path(item['local_path']).read_bytes()
                report['files'].append({**item, 'device_path': remote, 'readback_matches': matched})
                _write_report(output, report)
                if not matched:
                    raise RuntimeError('Seed file readback did not match: ' + item['name'])
        if setup['open_file'] is not None:
            from gui_rewalk.src.config.config import APP_BINARY_MAP
            from ..app_lifecycle import wait_for_app, _active_desktop_window
            if app_name not in APP_BINARY_MAP:
                raise ValueError('Seed has no file-opening command for application: ' + app_name)
            command = shlex.split(APP_BINARY_MAP[app_name]) + [remote_dir + '/' + setup['open_file']]
            report['events'].append({'operation': 'open_file', 'command': command, 'status': 'requested'})
            _write_report(output, report)
            # The controller launches argv directly; model text is never shell code.
            env.setup_controller._launch_setup(command=command)
            if not wait_for_app(env, app_name):
                raise RuntimeError('Seed target application did not appear')
            report['events'][-1]['status'] = 'application_visible'
            # Application presence alone can precede document loading. A title
            # match only ends this bounded wait; the screenshot check decides readiness.
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                window = _active_desktop_window(env)
                if window and Path(setup['open_file']).stem in window.title:
                    break
                time.sleep(0.5)
        observation = env._get_obs()
        (output / 'initial.png').write_bytes(observation['screenshot'])
        if setup['initial_state'].strip():
            report['model_calls'] = 1
            _write_report(output, report)
            check = agent._call(
                role='collection_seed_check', screenshots=[observation['screenshot']],
                response_schema={
                    'type': 'object', 'properties': {'ready': {'type': 'boolean'}, 'reason': {'type': 'string'}},
                    'required': ['ready', 'reason'], 'additionalProperties': False},
                system_prompt=('检查采集初态是否满足给定要求，只观察，不执行操作。'
                               '文件已经投放不代表已在应用中打开；按当前截图判断。'
                               '这是正式任务开始前的检查，不要求任务目标已经完成。看不清必要条件时ready=false。'),
                user_prompt=json.dumps({'application': app_name, 'instruction': task['instruction'],
                                        'required_initial_state': setup['initial_state'],
                                        'files': [{'name': f['name'], 'device_path': f['device_path']}
                                                  for f in report['files']]}, ensure_ascii=False))
            report['check'] = check
            report['ready'] = check.get('ready') is True
        else:
            report['ready'] = True
        _write_report(output, report)
        if not report['ready']:
            raise RuntimeError('Seed initial state was not confirmed: ' + report['check']['reason'])
        return report, observation
    except Exception as exc:
        report['error'] = str(exc)
        if output.exists():
            _write_report(output, report)
        raise


def _write_report(output, report):
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
