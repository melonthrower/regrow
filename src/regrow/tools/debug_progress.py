from regrow.records.tasks import coverage as _record_coverage
from regrow.records.object_store import region_work
from regrow.records.object_store import owned_tasks
from regrow.records import object_store as object_store
'Candidate-loadable graph progress; no scheduling or GUI effects.'
from regrow.records.object_store import owned_controls
from pathlib import Path
import hashlib
import json
from regrow.tools.debug_loop import read
from regrow.tools.debug_loop import ROOT

def graph_summary(run, source=ROOT):
    run = Path(run)
    pointer = read(run / 'knowledge_current.json', {})
    if not pointer:
        return {'complete': False, 'regions': 0, 'done': 0, 'pending': 0, 'blocked': 0, 'gaps': ['no_graph']}
    base = run / pointer['snapshot']
    records = object_store.load(base)
    from regrow.traversal import region_functions as functions
    result = {'regions': len(records), 'done': 0, 'pending': 0, 'blocked': 0, 'gaps': [], 'excluded': 0}
    for (rid, r) in records.items():
        if region_work(r).get('out_of_scope_reason'):
            result['excluded'] += 1
            continue
        c = _record_coverage(r, records)
        result['pending'] += len(c['pending'])
        result['blocked'] += len(c['blocked'])
        functional = functions.review_current(r, records)
        if c['complete'] and functional and (not region_work(r).get('registration_gaps')):
            result['done'] += 1
        else:
            result['gaps'].append({'region': rid, 'inventory': c['inventory_complete'], 'functions': functional, 'registration_gaps': region_work(r).get('registration_gaps', {})})
    unsettled = [p for p in ('execution_pending.json', 'pending_step.json', 'ownership_review.json') if (run / p).exists()]
    state = read(base / 'runtime_state.json', {})
    if state.get('next_action_mode') in ('recover', 'recover_scope', 'review_result', 'discover'):
        unsettled.append(state['next_action_mode'])
    result['unsettled'] = unsettled
    result['complete'] = bool(records) and result['done'] + result['excluded'] == len(records) and (not unsettled)
    semantic = {rid: {'excluded': bool(region_work(r).get('out_of_scope_reason')), 'controls': sorted(owned_controls(r)), 'tasks': {n: {k: t.get(k) for k in ('status',)} for (n, t) in owned_tasks(r).items()}, 'functions': sorted(r.get('functions', {})), 'function_review_current': functions.review_current(r, records), 'transitions': [{k: t.get(k) for k in ('source_control', 'action', 'target_region', 'destination', 'returns_to_previous')} for t in r.get('transitions', [])], 'inventory': region_work(r).get('task_inventory', {}).get('inventory')} for (rid, r) in records.items()}
    result['progress_key'] = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result
