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
    """Count finished rounds with unchanged done-task count in the same Region."""
    from regrow.traversal import step_repair as repair
    run = Path(run)
    if any((run / name).exists() for name in
           ('pending_step.json', 'execution_pending.json', 'visual_navigation_pending.json')):
        return None
    _, records, state = _record_load(run)
    work = state.get('working_region')
    if work not in records:
        return None
    path = run / 'exploration_loop.json'
    ledger = repair.read(path) if path.exists() else {'history': []}
    if any(row['round'] == str(round_key) for row in ledger['history']):
        return None
    done = sum(task.get('status') == 'done' for task in owned_tasks(records[work]).values())
    previous = ledger['history'][-1] if ledger['history'] else {}
    # The first round compares with its real start snapshot, not an invented count.
    if 'done' not in previous or previous.get('work') != work:
        before = Path(round_key) / 'knowledge_before.json'
        if before.is_file():
            snapshot = repair.read(before)['snapshot']
            _, old_records, old_state = _record_load(run, snapshot=(run / snapshot).resolve())
            old_work = old_state.get('working_region')
            previous = {'work': old_work, 'done': sum(t.get('status') == 'done'
                        for t in owned_tasks(old_records.get(old_work, {})).values())}
    unchanged = (previous.get('unchanged', 0) + 1
                 if previous.get('work') == work and previous.get('done') == done else 0)
    row = {'round': str(round_key), 'work': work, 'done': done, 'unchanged': unchanged}
    ledger['history'].append(row)
    repair.atomic(path, ledger)
    return detect(ledger['history'])


def detect(rows):
    if rows and rows[-1].get('unchanged', 0) >= 3:
        return {'kind': 'no_task_settlement', 'region': rows[-1]['work'],
                'rounds': rows[-1]['unchanged'], 'done': rows[-1]['done']}
    return None


def finish(run, out):
    """Yield after three unchanged rounds, preserving all unfinished tasks."""
    from regrow.traversal import task_deferral
    from regrow.records.snapshots import read, write_json
    from regrow.traversal.traversal_scheduler import after_round
    result = read(Path(out) / 'result.json')
    if after_round(result['status'], False) != 'continue':
        return
    evidence = observe(run, str(out))
    if not evidence:
        return
    selection = task_deferral.advance_unfinished(run)
    status = 'ready_next_round' if selection else 'exploration_stalled'
    result.update(status=status, settlement_exit={**evidence, 'next': selection},
                  reason='同一工作区块连续3轮已完成任务数未变化，已让出区块。' if selection
                  else '同一工作区块连续3轮已完成任务数未变化，当前未选出可切换区块；保留未完成任务并暂停。')
    write_json(Path(out) / 'result.json', result)
    budget = read(Path(out) / 'budget.json')
    budget['status'] = status
    write_json(Path(out) / 'budget.json', budget)
