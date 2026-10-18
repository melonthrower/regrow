from regrow.records.snapshots import load as _record_load
from regrow.records.object_store import region_work
'Detect repeated settled traversal states without additional model calls.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
import hashlib
import json
from pathlib import Path

def same_observation(a, b):
    from regrow.recognition import visual_backtrack as _visual_backtrack
    return Path(a).read_bytes() == Path(b).read_bytes() or _visual_backtrack.same_surface(a, b)

def progress_key(records, *, navigation=False):
    rows = {}
    for (rid, r) in records.items():
        edges = []
        for a in owned_actions(r).values():
            edges.append(json.dumps([a.get('control'), a.get('operation'), a.get('interactive_regions'), a.get('result', {}).get('exception')], sort_keys=True))
        rows[rid] = {'controls': sorted(owned_controls(r)), 'tasks': {n: {k: t.get(k) for k in (('status',) if navigation else ('status', 'result_evidence'))} for (n, t) in owned_tasks(r).items()}, 'findings': {n: {f: {k: v.get(k) for k in ('description', 'domain', 'conditions')} for (f, v) in task_value(t, 'findings', {}).items()} for (n, t) in owned_tasks(r).items()}, 'edges': sorted(set(edges)), 'function_review': region_work(r).get('function_inventory', {}).get('evidence_digest'), 'knowledge': {} if navigation else {c: next((o['knowledge'] for o in reversed(observation_history(v)) if o.get('knowledge') and (not o.get('visual_only'))), '') for (c, v) in owned_controls(r).items()}}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def observe(run, round_key):
    from regrow.traversal import step_repair as _step_repair
    run = Path(run)
    repair = _step_repair
    if any(((run / p).exists() for p in ('pending_step.json', 'execution_pending.json', 'visual_navigation_pending.json'))):
        return None
    (_, records, state) = _record_load(run)
    work = state.get('working_region')
    if work not in records:
        return None
    path = run / 'exploration_loop.json'
    ledger = repair.read(path) if path.exists() else {'history': []}
    if any((r['round'] == str(round_key) for r in ledger['history'])):
        return None
    row = {'round': str(round_key), 'work': work, 'task': state.get('active_task'), 'position': sorted(state.get('interactive_regions', [])), 'mode': state.get('next_action_mode'), 'progress': progress_key(records), 'navigation_progress': progress_key(records, navigation=True), 'task_progress': progress_key(records, navigation=True), 'navigating': not state.get('active_task') and (work not in state.get('interactive_regions', []) or state.get('next_action_mode') in ('recover', 'recover_scope', 'review_result'))}
    frame = Path(round_key) / 'current.png'
    if frame.is_file():
        row['frame'] = str(frame.resolve())
    last = state.get('last_action_result', {})
    action = owned_actions(records.get(last.get('region'), {})).get(last.get('action'))
    if action:
        owner = records[last['region']]
        row['recent_action_ref'] = [last['region'], last['action']]
        row['recent_action'] = {'区块': owner['name'], '目标': owned_controls(owner).get(action.get('control'), {}).get('name') or action.get('association', {}).get('target', '未关联控件'), '动作': action.get('operation'), '结果': action.get('result', {})}
    ledger['history'] = (ledger['history'] + [row])[-9:]
    repair.atomic(path, ledger)
    return detect(ledger['history'])

def detect(rows):
    for width in (1, 2, 3):
        window = rows[-3 * width:]
        if len(window) != 3 * width:
            continue
        key = 'task_progress' if any((r.get('task') for r in window)) else 'navigation_progress' if any((r.get('navigating') or r.get('mode') in ('recover', 'recover_scope', 'review_result') for r in window)) else 'progress'
        if len({json.dumps([r['work'], r['task'], r.get(key, r['progress'])], sort_keys=True) for r in window}) != 1:
            continue
        locations = [(r['position'], r['mode']) for r in window]
        if locations[:width] == locations[width:2 * width] == locations[2 * width:]:
            if all((r.get('frame') and Path(r['frame']).is_file() for r in window)):
                same = same_observation
                if not all((same(window[i]['frame'], window[i - width]['frame']) for i in range(width, len(window)))):
                    continue
            return {'kind': 'exploration_loop', 'cycle_length': width, 'repetitions': 3, 'history': window}
    return None

def correct(runner, evidence):
    from regrow.traversal import step_repair as _step_repair
    repair = _step_repair
    (_, records, state) = _record_load(runner.run)
    import uuid
    job = {'path': 'repair_episodes/' + uuid.uuid4().hex + '/episode.json', 'stage': 'action', 'attempt': None, 'request': {'source': {'region': state['working_region'], 'task_region': state['working_region'], 'task_name': (state.get('active_task') or {}).get('name')}}, 'status': 'initial', 'history': [], 'switch_trigger': evidence}
    runner.save(job)
    repair.atomic(Path(runner.run) / runner.pointer_name, {'episode': job['path']})
    runner.switch_branch(job)
