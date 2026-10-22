"""Read real call traces; rebuild isolated saved-frame jobs with normal Regrow entry points."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import sys
from threading import Lock
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[1] / 'src'
LABELS = {'observation': '发现与识别', 'task_proposal': '提出探索任务', 'action_selection': '选择动作', 'observation_update': '动作后更新', 'step_correction': '纠错', 'function_registration': '功能总结'}
LOCK = Lock()


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else default


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.new')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def catalog(root):
    return read(Path(root) / 'trace_catalog.json', {'traces': []})


def trace(root, key):
    return next(row for row in catalog(root)['traces'] if row['id'] == key)


def source_call(root, key, call):
    entry = trace(root, key)
    if call not in entry['calls']:
        raise ValueError('未知调用')
    run = Path(entry['run'])
    return run, read(run / 'calls' / call / 'request.json')


def recorded_source(run, request):
    """Recover old update metadata only from its real attempt and dispatch record."""
    if request.get('source'):
        return request['source']
    if request.get('role') != 'observation_update':
        return {}
    attempts = {Path(frame).parts[Path(frame).parts.index('action_attempts') + 1]
                for frame in request.get('screenshots', []) if 'action_attempts' in Path(frame).parts}
    if len(attempts) != 1:
        raise ValueError('历史更新没有唯一实际动作来源')
    attempt = attempts.pop()
    dispatch = read(Path(run) / 'action_attempts' / attempt / 'dispatch.json')
    selection = read(Path(run) / 'calls' / dispatch['source_call'] / 'request.json')
    return {**selection['source'], 'attempt': attempt}


def before_snapshot(run, call, q):
    source = recorded_source(run, q)
    if source.get('snapshot'):
        return source['snapshot']
    if source.get('attempt'):
        dispatch = read(run / 'action_attempts' / source['attempt'] / 'dispatch.json', {})
        original = read(run / 'calls' / str(dispatch.get('source_call')) / 'request.json', {})
        return original.get('source', {}).get('snapshot')
    # A committed discovery explicitly records its parent; do not guess by timestamps.
    if q.get('role') == 'observation':
        matches = [p for p in (run / 'knowledge_snapshots').glob('*/source.json') if read(p, {}).get('stage') == 'discovery-' + call]
        if len(matches) == 1:
            return read(matches[0]).get('parent_snapshot')
    return None


def snapshots_for_call(run, call):
    found = []
    for p in (run / 'knowledge_snapshots').glob('*/source.json'):
        stage = read(p, {}).get('stage', '')
        if stage.endswith('-' + call):
            found.append(str(p.parent.relative_to(run)))
    return found


def records_at(run, snapshot):
    if not snapshot:
        return None
    folder = (run / snapshot).resolve()
    if not folder.is_relative_to(run.resolve()):
        raise ValueError('快照不在原运行内')
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    from regrow.records.object_store import load, region_state
    records = load(folder)
    return {'snapshot': snapshot, 'state': read(folder / 'runtime_state.json'),
            'regions': {rid: region_state(r) for rid, r in records.items()}}


def step(root, key, call):
    run, q = source_call(root, key, call)
    folder = run / 'calls' / call
    parts = list(dict.fromkeys(p['path'].split('/片段-', 1)[0] for p in q.get('fixed_parts', [])))
    snap = before_snapshot(run, call, q)
    after = snapshots_for_call(run, call)
    attempt = (q.get('source') or {}).get('attempt')
    actions = []
    for p in sorted((run / 'action_attempts').glob('*/dispatch.json')):
        dispatch = read(p)
        if dispatch.get('source_call') == call or p.parent.name == attempt:
            actions.append({'attempt': p.parent.name, 'dispatch': dispatch, 'receipt': read(p.parent / 'receipt.json')})
    repairs = []
    for episode in (run / 'repair_episodes').glob('*/episode.json'):
        data = read(episode)
        if data.get('call') == call or any(h.get('call') == call for h in data.get('history', [])):
            repairs.append({k:data.get(k) for k in ('stage','status','call','history','repairs','observations','result')})
    return {'call': call, 'label': LABELS.get(q.get('role'), q.get('role')), 'request': q,
            'modules': parts, 'repairs': repairs, 'before': records_at(run, snap),
            'after': [records_at(run, s) for s in after], 'actions': actions,
            'response': read(folder / 'response.json'), 'usage': read(folder / 'usage.json'),
            'error': read(folder / 'transport_error.json') or read(folder / 'http_error.json'),
            'replayable': bool(snap and q.get('role') in LABELS and q.get('role') != 'step_correction'),
            'replay_note': '完整原记录恢复到调用前快照；以当前代码重建。' if snap else '缺少可确定的调用前快照；仅展示原件，不猜测重建。'}


def overview(root):
    result = []
    for entry in catalog(root)['traces']:
        run = Path(entry['run'])
        steps = []
        for call in entry['calls']:
            q = read(run / 'calls' / call / 'request.json')
            steps.append({'call': call, 'role': q['role'], 'label': LABELS.get(q['role'], q['role']),
                          'modules': list(dict.fromkeys(p['path'].split('/片段-', 1)[0] for p in q.get('fixed_parts', [])))})
        result.append({'id': entry['id'], 'title': entry['title'], 'archived': entry.get('archived', False), 'steps': steps})
    return result


def image_path(root, key, call, index):
    run, q = source_call(root, key, call)
    path = Path(q.get('screenshots', [])[int(index)])
    path = path if path.is_absolute() else run / path
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('不是截图')
    return path


def jobs(root):
    return [read(p) for p in sorted((Path(root) / 'trace_jobs').glob('*/status.json'), reverse=True)]


def start(root, payload, store, *, frozen=None):
    """Freeze exactly the selected modules; launch a non-GUI worker. Never mutate live source."""
    root = Path(root)
    key, call = payload['trace'], payload['call']
    item = step(root, key, call)
    if not item['replayable']:
        raise ValueError('该调用不能独立重建；纠错请从其正常调用开始，保留正常纠错流程。')
    mode = payload.get('mode', 'preview')
    if mode not in ('preview', 'test'):
        raise ValueError('未知操作')
    selected = payload.get('modules', [])
    if not isinstance(selected, list) or not set(selected).issubset(item['modules']):
        raise ValueError('只允许替换此调用关联的提示模块')
    with LOCK:
        batches_running = any(read(p, {}).get('status') == 'running' for p in root.glob('working_traces/*/batches/*/status.json'))
        if (batches_running and frozen is None) or any(j.get('status') == 'running' for j in jobs(root)):
            raise ValueError('已有请求在生成或测试，请等待其结束。')
        ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
        dest = root / 'trace_jobs' / ident
        dest.mkdir(parents=True)
        replacements = {}
        for name in selected:
            # Only listed editable prompt paths, never arbitrary filesystem paths.
            if name not in store.paths or not (SOURCE / 'regrow/prompts' / name).is_file():
                raise ValueError('该模块不能直接映射到当前框架：' + name)
            replacements[name] = frozen['modules'][name] if frozen is not None else store.read(name)['text']
        write(dest / 'replacements.json', replacements)
        run, original = source_call(root, key, call)
        write(dest / 'job.json', {'id': ident, 'mode': mode, 'trace': key, 'call': call,
             'run': str(run), 'snapshot': before_snapshot(run, call, original),
             'platform': trace(root, key).get('platform', 'desktop'), 'source': frozen['source'] if frozen else str(SOURCE),
             'context': frozen.get('context') if frozen else None, 'revision': frozen.get('revision') if frozen else None,
             'dependency_job': frozen.get('dependency_job') if frozen else None,
             'original_request': original, 'max_calls': 3, 'GUI': 0})
        write(dest / 'status.json', {'id': ident, 'status': 'running', 'mode': mode, 'trace': key, 'call': call,
                                     'modules': selected, 'calls': 0, 'GUI': 0})
        # The server interpreter must be the same environment used by the framework.
        with (dest / 'worker.log').open('w') as log:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(dest)], stdout=log, stderr=log)
        write(dest / 'process.json', {'pid': proc.pid})
        return read(dest / 'status.json')


def job_images(dest):
    dest = Path(dest)
    after = read(dest / 'after-records.json', {})
    base = Path(after.get('snapshot', str(dest / 'run')))
    found = []
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('image', 'icon_image') and isinstance(item, str) and Path(item).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                    path = (base / item).resolve()
                    if path.is_file() and str(path) not in found:
                        found.append(str(path))
                visit(item)
        elif isinstance(value, list):
            for item in value:visit(item)
    visit(after.get('regions', {}))
    return found


def job_image(root, ident, index):
    if Path(ident).name != ident:
        raise ValueError('无效测试编号')
    return Path(job_images(Path(root) / 'trace_jobs' / ident)[int(index)])


def job_view(root, ident):
    if not ident or Path(ident).name != ident:
        raise ValueError('无效测试编号')
    dest = Path(root) / 'trace_jobs' / ident
    status = read(dest / 'status.json')
    if not status:
        raise ValueError('不存在此测试')
    return {**status, 'images': [{'index': i, 'name': Path(p).name} for i,p in enumerate(job_images(dest))], 'preview': read(dest / 'preview.json'), 'summary': read(dest / 'summary.json'),
            'result': read(dest / 'result.json'), 'next_request': read(dest / 'next-request.json'),
            'after': read(dest / 'after-records.json'),
            'reused_frames': [read(p) for p in (dest / 'run/repair_episodes').rglob('*.source.json')], 'calls_detail': [
                {'call': p.name, 'request': read(p / 'request.json'), 'response': read(p / 'response.json'),
                 'usage': read(p / 'usage.json'), 'error': read(p / 'transport_error.json') or read(p / 'http_error.json')}
                for p in sorted((dest / 'run/calls').glob('*')) if p.is_dir() and (p / 'request.json').exists()
                and p.name not in read(dest / 'inherited-calls.json', [])]}


def worker(dest):
    from types import SimpleNamespace
    from unittest.mock import patch
    dest = Path(dest).resolve()
    spec = read(dest / 'job.json'); original = spec['original_request']
    source = dest / 'source'
    shutil.copytree(spec['source'], source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, text in read(dest / 'replacements.json').items():
        (source / 'regrow/prompts' / name).write_text(text)
    write(dest / 'source-manifest.json', {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in source.rglob('*') if p.is_file()})
    sys.path.insert(0, str(source))
    from regrow.records import snapshots
    from regrow.recognition import locator
    from regrow.traversal import task_proposer, action_proposer, result_updater, region_functions, traversal_scheduler
    from regrow.traversal.step_repair import Runner, Paused
    from regrow.runtime.model_transport import ModelTransport, BudgetExhausted
    from regrow.runtime.desktop_transport import DesktopRun, prepare_request
    from regrow.runtime.recover_external import RecoveryRun
    run = dest / 'run'; origin = Path(spec['run'])
    dependency = spec.get('dependency_job')
    if dependency:
        if Path(dependency).name != dependency:raise ValueError('无效登记来源')
        origin = dest.parent / dependency / 'run'
        spec['snapshot'] = read(origin / 'knowledge_current.json')['snapshot']
    if any(p.is_symlink() for p in origin.rglob('*')):
        raise ValueError('运行含符号链接，未复制；先核对依赖边界')
    shutil.copytree(origin, run)
    # Isolate historical point: future calls/actions cannot become evidence for this step.
    for p in (run / 'calls').iterdir():
        if not dependency and p.name.isdigit() and int(p.name) >= int(spec['call']):
            shutil.rmtree(p)
    for p in (run / 'action_attempts').iterdir():
        dispatch = read(p / 'dispatch.json', {})
        if not dependency and str(dispatch.get('source_call', '')).isdigit() and int(dispatch['source_call']) >= int(spec['call']):
            shutil.rmtree(p)
    # Legacy object loading scans sibling snapshots for ID allocation. Keep only
    # the explicit ancestor chain so later objects cannot leak into a replay.
    ancestors = set()
    cursor = spec['snapshot']
    while cursor and cursor not in ancestors:
        ancestors.add(cursor)
        cursor = read(run / cursor / 'source.json', {}).get('parent_snapshot')
    for p in (run / 'knowledge_snapshots').iterdir():
        if p.is_dir() and str(p.relative_to(run)) not in ancestors:
            archive = dest / 'inherited-future-snapshots' / p.name
            archive.parent.mkdir(exist_ok=True)
            shutil.move(p, archive)
    for p in (run / 'repair_episodes').glob('*/episode.json'):
        episode = read(p)
        refs = [str(episode.get('call', ''))] + [str(h.get('call', '')) for h in episode.get('history', [])]
        if not dependency and any(v.isdigit() and int(v) >= int(spec['call']) for v in refs):
            archive = dest / 'inherited-future-episodes' / p.parent.name
            archive.parent.mkdir(exist_ok=True)
            shutil.move(p.parent, archive)
    for p in (run / 'foreground_scopes').glob('*.json'):
        call_ref = str(read(p, {}).get('source_call', ''))
        if not dependency and call_ref.isdigit() and int(call_ref) >= int(spec['call']):
            p.unlink()
    for name in ('pending_step.json', 'execution_pending.json', 'visual_navigation_pending.json', 'knowledge_current.pending.json'):
        pending = run / name
        if pending.exists():
            archive = dest / 'inherited-pending' / name
            archive.parent.mkdir(exist_ok=True)
            shutil.move(pending, archive)
    if original['role'] == 'observation_update':
        write(run / 'execution_pending.json', {'attempt': recorded_source(origin, original)['attempt']})
    write(run / 'knowledge_current.json', {'snapshot': spec['snapshot']})
    write(dest / 'inherited-calls.json', [p.name for p in (run / 'calls').iterdir()])
    manifest = read(run / 'run_manifest.json');manifest['framework_source'] = str(source)
    write(run / 'run_manifest.json', manifest)
    shutil.copy2(source / 'regrow/runtime/call_model_once.py', run / 'call_once.py')
    if spec.get('context'):
        from regrow.records.object_store import Records, rebase, save as save_records
        edit = spec['context']
        old_base = Path(spec['run']) / edit['snapshot']
        new_base = run / 'knowledge_snapshots' / ('case-context-' + spec['id'])
        new_base.mkdir()
        edited = rebase(Records(edit['regions']), old_base, new_base)
        save_records(edited, new_base, write)
        write(new_base / 'runtime_state.json', edit['state'])
        write(new_base / 'source.json', {'parent_snapshot': spec['snapshot'], 'stage': 'manual_case_context', 'revision': spec.get('revision')})
        write(run / 'knowledge_current.json', {'snapshot': str(new_base.relative_to(run))})
    snapshot, records, state = snapshots.load(run)
    role = original['role'];src = recorded_source(origin, original);attempt = src.get('attempt')
    if role == 'observation':
        # Same historical screenshot and stored discovery state, normal builder.
        q = locator.request_from_run(source, run)
        stage = 'discovery'
    elif role == 'action_selection':
        task = {'region': src.get('task_region', src.get('region')), 'name': src['task_name']} if src.get('task_name') else None
        q = action_proposer.request_from_run(source, run, region_ref=src.get('working_region'), task_ref=task,
                frame=str(origin / original['screenshots'][0]), decision=original.get('selection'))
        stage = 'action' if q.get('action_ready') else q.get('role')
    elif role == 'observation_update':
        # Commit receipt from the historical future must not suppress normal registration.
        (run / 'action_attempts' / attempt / 'commit.json').unlink(missing_ok=True)
        q = result_updater.build_attempt_update(source, SimpleNamespace(run=run, package=manifest['app']), run / 'action_attempts' / attempt)
        stage = 'update'
    elif role == 'task_proposal':
        q = task_proposer.plan_request(source, records, state, src['region']);stage = 'task_proposal'
    elif role == 'task_result_review':
        from regrow.traversal import task_result_review
        q = task_result_review.request(source, run, src, original.get('screenshots', []));stage = 'task_result_review'
    else:
        q = region_functions.request(source, records[src['region']], state, records);stage = 'function_registration'
    def capture_request(request):
        if spec['platform'] == 'desktop':request = prepare_request(source, request)
        captured = []
        with patch('regrow.runtime.progress.request', side_effect=captured.append):
            try:ModelTransport.call(SimpleNamespace(root=source, run=run, platform=spec['platform'], account={'http_started':0,'max_http':0}), request)
            except BudgetExhausted:pass
        if len(captured) != 1:raise ValueError('未取得正常发送请求')
        return captured[0]
    class PreviewDone(BaseException):pass
    def preview_send(request):
        write(dest / 'preview.json', capture_request(request));raise PreviewDone()
    def no_gui(*args, **kwargs):raise RuntimeError('保存帧测试禁止GUI执行')
    preview_runner = Runner(source, run, preview_send, no_gui, lambda: 1, pointer_name='trace-preview-' + spec['id'] + '.json')
    try:
        if stage == 'action':action_proposer.ActionProposer(preview_runner).propose(q)
        else:preview_runner.perform(stage, q, attempt)
    except PreviewDone:pass
    preview = read(dest / 'preview.json')
    selected = set(read(dest / 'replacements.json'))
    used = {p['path'].split('/片段-',1)[0] for p in preview.get('fixed_parts',[])}
    summary = {'stage': stage, 'snapshot':spec['snapshot'], 'selected_modules':sorted(selected),
               'unused_modules': sorted(selected-used), 'historical_role':role, 'rebuilt_role':preview.get('role'),
               'context_edited':bool(spec.get('context')), 'revision':spec.get('revision'),
               'validation_scope':'编辑案例测试，不是未修改真实记录验收' if spec.get('context') else '原始记录保存帧检查',
               'original_chars':{k:len(original.get(k,'')) for k in ('system_prompt','user_prompt')},
               'current_chars':{k:len(preview.get(k,'')) for k in ('system_prompt','user_prompt')}, 'GUI':0}
    write(dest / 'summary.json', summary)
    if spec['mode'] == 'preview':return {'status':'preview_ready','calls':0}
    if selected-used:raise ValueError('所选模块未进入正常请求，先检查组合位置；本次不调用Luna')
    class Saved(DesktopRun if spec['platform']=='desktop' else RecoveryRun):
        def __init__(self):
            self.root=source;self.run=run;self.package=manifest['app'];self.ledger=dest/'ledger.json'
            self.account={'http_started':0,'gui_started':0,'max_http':spec['max_calls'],'max_gui_commands':0,'total_call_limit':None}
        def save(self):
            write(self.ledger,self.account)
            status=read(dest/'status.json');status['calls']=self.account['http_started'];write(dest/'status.json',status)
        adb=command=send_command=no_gui
    transport=Saved();transport.save()
    from regrow.prompts.frame_context import primary
    frame = (run / primary(preview)) if preview.get('screenshots') else None
    def saved_frame(destination):
        if frame is None:raise ValueError('本步没有原截图，不能补造观察')
        path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(frame,path)
        write(path.with_suffix('.source.json'),{'source':str(frame),'new_GUI':False})
    runner=Runner(source,run,transport.call,saved_frame,lambda:spec['max_calls']-transport.account['http_started'],pointer_name='trace-model-' + spec['id'] + '.json')
    no_action_registered = False
    try:
        result=action_proposer.ActionProposer(runner).propose(q) if stage=='action' else runner.perform(stage,q,attempt)
        if stage == 'action' and result.get('result', {}).get('binding', {}).get('status') == 'no_action':
            accepted = result['result']
            result['handoff'] = traversal_scheduler.handoff_no_action(run, accepted['request'], accepted['proposal'], accepted['call'], frame)
            no_action_registered = True
        if stage == 'update':
            result_updater.ResultUpdater(source, transport, runner).complete(attempt, result['result'])
        write(dest/'result.json',result)
        status='checked'
    except Paused as error:
        write(dest/'result.json',{'status':error.status,'reason':error.reason});status='paused'
    from regrow.records.object_store import region_state
    snap, new_records, new_state=snapshots.load(run)
    write(dest/'after-records.json',{'snapshot':str(snap),'regions':{rid: region_state(r) for rid,r in new_records.items()},'state':new_state})
    if (stage!='action' or no_action_registered) and status=='checked':
        try:
            nxt=traversal_scheduler.preview_next(source,run)
            if nxt.get('stage')=='locate':nxt=locator.request_from_run(source,run)
            if nxt.get('action_ready'):
                def next_send(request):
                    write(dest/'next-request.json',capture_request(request))
                    raise PreviewDone()
                next_runner=Runner(source,run,next_send,no_gui,lambda:1,pointer_name='trace-next-'+spec['id']+'.json')
                try:action_proposer.ActionProposer(next_runner).propose(nxt)
                except PreviewDone:pass
            else:
                write(dest/'next-request.json',capture_request(nxt) if nxt.get('response_schema') else nxt)
        except Exception as error:write(dest/'next-request.json',{'error':str(error)})
    return {'status':status,'calls':transport.account['http_started'],'note':'保存帧检查；动作选择不执行GUI，不沿用旧动作后图证明新动作成功。语义结果需人工审阅。'}


if __name__ == '__main__':
    dest=Path(sys.argv[1]);state=read(dest/'status.json')
    try:state.update(worker(dest))
    except Exception as error:
        import traceback
        traceback.print_exc()
        state.update(status='failed',error=str(error),calls=read(dest/'ledger.json',{}).get('http_started',0))
    write(dest/'status.json',state)
