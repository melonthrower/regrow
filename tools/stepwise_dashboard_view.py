"""Read-only task focus and action evidence for the dashboard, never scheduling."""
import json
import re
from pathlib import Path


STAGES = {'discovery': '发现区块与控件', 'task_proposal': '清点探索任务',
          'action_selection': '选择下一步操作', 'observation_update': '观察结果并登记',
          'function_registration': '总结区块功能', 'step_correction': '纠正当前步骤',
          'task_correction': '纠正任务登记', 'recovery_action': '处理应用异常'}
KINDS = {'entry': '入口去向与功能', 'parameter': '参数及可配置范围',
         'control_effect': '控件的操作效果'}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def evidence_asset(run, attempt, frame):
    if not re.fullmatch(r'a\d+', attempt) or frame not in ('before', 'after'):
        raise ValueError('Unknown action evidence')
    root = Path(run).resolve()
    path = (root / 'action_attempts' / attempt / (frame + '.png')).resolve()
    path.relative_to(root / 'action_attempts')
    return path


def task_card(region, name, task, effective):
    return {'name': name, 'region': region.get('name', '未关联区块'),
            'control': region.get('controls', {}).get(task.get('control'), {}).get('name', '区块任务'),
            'purpose': task.get('reason', ''), 'conditions': task.get('conditions', []),
            'product': KINDS.get(task.get('registration_kind'), '对应功能信息'),
            'status': effective.get('status', 'pending'), 'handling': task.get('handling'),
            'gap': (effective.get('registration_gap') or effective.get('deferral', {}).get('reason')
                    or effective.get('result_evidence', '') if effective.get('status') == 'blocked' else ''),
            'knowledge': effective.get('knowledge', '') if effective.get('status') in ('done', 'record_only') else ''}


def project(run, view, effective_task):
    """Use exactly the snapshot already selected by the graph/progress response."""
    run = Path(run)
    base = (run / view['snapshot']).resolve()
    base.relative_to(run.resolve() / 'knowledge_snapshots')
    records = {p.parent.name: read(p) for p in (base / 'regions').glob('*/region.json')}
    state = read(base / 'runtime_state.json')
    runtime = read(run / 'progress_current.json')
    manifest = read(run / 'run_manifest.json')
    last = str(manifest.get('last_call', '')).zfill(4)
    folder = run / 'calls' / last
    context = read(folder / 'exploration_context.json')
    # A request from an earlier round/session must not become today's active goal.
    event = run / 'progress_events' / (str(runtime.get('round', '')) + '.jsonl')
    try:
        with event.open() as stream:
            first = json.loads(stream.readline())
        from datetime import datetime
        current_call = (folder / 'request.json').stat().st_mtime >= datetime.fromisoformat(first['updated_at']).timestamp()
    except (OSError, ValueError, KeyError):
        current_call = False
    request = read(folder / 'request.json') if current_call else {}
    source = request.get('source') or {}
    stage = request.get('stage')
    if not current_call:
        context = {}
    active = state.get('active_task') or {}
    name = context.get('task') or runtime.get('task') or active.get('name')
    if stage in ('discovery', 'task_proposal', 'function_registration') and not context.get('task'):
        name = None
    owner_id = context.get('task_region') or source.get('task_region') or active.get('region')
    owner = records.get(owner_id, {})
    task = owner.get('tasks', {}).get(name, {})
    # exploration_context.region_id follows task ownership for action requests;
    # it is not the active working surface. Non-action stages may target a Region
    # explicitly (for example, summarizing a Region no longer in the foreground).
    work_id = state.get('working_region')
    if stage in ('discovery', 'task_proposal', 'function_registration'):
        work_id = source.get('region') or (request.get('discovery_context') or {}).get('focus') or work_id
    work = records.get(work_id, {})
    tasks = [task_card(work, n, t, effective_task(work.get('tasks', {}), t))
             for n, t in work.get('tasks', {}).items()]
    selected = task_card(owner, name, task, effective_task(owner.get('tasks', {}), task)) if task else None
    if selected is None and name:
        selected = {'name': name, 'region': owner.get('name', '归属尚未登记'), 'purpose': '',
                    'conditions': [], 'control': '', 'product': '', 'status': 'pending', 'gap': ''}
    actions = []
    registered = {aid: (r, a) for r in records.values() for aid, a in r.get('actions', {}).items()}
    for path in sorted((run / 'action_attempts').glob('a*'), reverse=True)[:12]:
        if not re.fullmatch(r'a\d+', path.name):
            continue
        binding = read(path / 'binding.json')
        region, action = registered.get(path.name, (records.get(binding.get('region_ref'), {}), {}))
        receipt = read(path / 'receipt.json')
        dispatch = read(path / 'dispatch.json')
        proposal = dispatch.get('action') or {}
        if not isinstance(proposal, dict):
            proposal = {}
        aid = path.name
        images = [part for part in ('before', 'after') if evidence_asset(run, aid, part).is_file()]
        actions.append({'attempt': aid, 'region': region.get('name', records.get(binding.get('region_ref'), {}).get('name', '尚未关联')),
                        'control': region.get('controls', {}).get(action.get('control') or binding.get('control_ref'), {}).get('name', '未绑定具体控件'),
                        'task': binding.get('task_name'), 'operation': action.get('operation') or proposal.get('action'),
                        'purpose': action.get('purpose') or proposal.get('reason', ''),
                        'state': '结果已登记' if action.get('result') else '已投递，待登记' if receipt.get('exit_code') == 0 else '投递未确认',
                        'result': action.get('result', {}).get('description', ''),
                        'knowledge': action.get('knowledge', ''), 'conditions': action.get('conditions', []),
                        'images': images})
    calls = []
    for path in sorted((run / 'calls').glob('*'), reverse=True)[:8]:
        if not path.name.isdigit():
            continue
        meta = read(path / 'exploration_context.json')
        calls.append({'id': path.name, 'stage': STAGES.get(meta.get('stage'), meta.get('stage') or '阶段处理'),
                      'region': meta.get('region', '未关联区块'), 'task': meta.get('task'),
                      'reply': (path / 'response.json').is_file()})
    return {'snapshot': view['snapshot'], 'region': work.get('name', view['work_region']['name']),
            'description': work.get('description', ''), 'task': selected, 'tasks': tasks,
            'stage': STAGES.get(stage, view.get('phase_label') or '准备下一步'),
            'call': last if current_call else None, 'waiting': current_call and not (folder / 'response.json').exists(),
            'preparing': bool(task.get('prepares')), 'actions': actions, 'calls': calls}
