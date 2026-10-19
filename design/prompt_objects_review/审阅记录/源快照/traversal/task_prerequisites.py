from regrow.records.tasks import in_scope as _record_in_scope
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
'Evidence-backed prerequisites, ordinary preparation tasks and scoped wakeups.'
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records.object_store import find_control
from copy import deepcopy
import json

def schema():
    return {'anyOf': [{'type': 'null'}, {'type': 'object', 'properties': {'region': {'type': 'string'}, 'control': {'type': 'string'}, 'condition': {'type': 'string'}, 'preparation': {'type': 'string'}, 'evidence': {'type': 'string'}, 'permitted': {'type': 'boolean'}}, 'required': ['region', 'control', 'condition', 'preparation', 'evidence', 'permitted'], 'additionalProperties': False}]}

def enroll(records, rid, call):
    """Create one ordinary preparation task when an allowed known prerequisite exists."""
    if region_work(records[rid]).get('out_of_scope_reason'):
        return
    for (name, task) in list(owned_tasks(records[rid]).items()):
        if not _record_in_scope(records[rid], task, records):
            continue
        dep = task.get('prerequisite')
        if not dep or task.get('status') == 'done' or dep.get('scheduled') or task.get('coverage_exemption') or task.get('shared_result'):
            continue
        if task.get('blocker', {}).get('exception') == 'unexpected_exit':
            continue
        task.update(status='blocked', blocker={'condition': 'prerequisite', 'reason': dep['condition'], 'source_call': call})
        task['deferral'] = {'reason': dep['condition'], 'retry_when': 'observed_prerequisite_satisfied'}
        if not dep['permitted']:
            continue
        targets = [(rr, cid) for (rr, r) in records.items() if r['name'] == dep['region'] and (not region_work(r).get('out_of_scope_reason')) for (cid, c) in owned_controls(r).items() if c['name'] == dep['control']]
        if len(targets) != 1:
            continue
        (rr, cid) = targets[0]
        prep_name = '满足前置条件：' + dep['preparation'] + '（' + records[rid]['name'] + ' / ' + name + '）'
        prep = {'name': prep_name, 'control': cid, 'task_type': 'function', 'status': 'pending', 'equivalent_to': '', 'reason': dep['preparation'] + '；返回目标观察是否满足：' + dep['condition'], 'source_call': call, 'attempts': [], 'prepares': {'region': rid, 'task': name}}
        owned_tasks(records[rr], create=True).setdefault(prep_name, prep)
        dep['scheduled'] = {'region': rr, 'task': prep_name, 'source_call': call}

def candidates(records):
    return [(rid, n, t) for (rid, r) in records.items() for (n, t) in owned_tasks(r).items() if _record_in_scope(r, t, records) and t.get('status') == 'blocked' and (t.get('blocker', {}).get('condition') == 'prerequisite') and t.get('prerequisite') and t['prerequisite'].get('permitted')]

def augment(root, run, q):
    if q.get('stage') not in ('discovery', 'update', 'observation_update'):
        return q
    if 'dependency_candidates' in q:
        return q
    (_, records, state) = _record_load(run)
    from regrow.records.context_scope import for_request
    scope = for_request(q, records, state)
    linked = {(row['region'], row['name']) for row in scope['tasks']}
    rows = [(rid, n, t) for (rid, n, t) in candidates(records) if rid in scope['regions'] or (rid, n) in linked]
    if not rows:
        return q
    q = deepcopy(q)
    entries = [{'region': records[rid]['name'], 'task': n, 'control': owned_controls(records[rid]).get(t.get('control'), {}).get('name'), '前置条件': t['prerequisite']['condition'], '准备操作': t['prerequisite']['preparation']} for (rid, n, t) in rows]
    item = {'type': 'object', 'properties': {'region': {'type': 'string'}, 'task': {'type': 'string'}, 'ready': {'type': 'boolean'}, 'evidence': {'type': 'string'}}, 'required': ['region', 'task', 'ready', 'evidence'], 'additionalProperties': False}
    q['response_schema']['properties']['dependency_updates'] = {'type': 'array', 'items': item}
    q['response_schema']['required'].append('dependency_updates')
    q['dependency_candidates'] = [{'region': rid, 'task': n} for (rid, n, t) in rows]
    q['user_prompt'] += '\n\n可在本次观察核对的暂挂任务（不表示它们在本图可见）：\n' + json.dumps(entries, ensure_ascii=False)
    from regrow.prompts.compose import supplement
    part = supplement(root, 'preconditions')
    q['system_prompt'] += '\n\n' + part['text']
    q['fixed_parts'].append(part)
    return q

def apply(records, reply, call, allowed):
    allowed = {(x['region'], x['task']) for x in allowed}
    for row in reply.get('dependency_updates', []):
        ids = [rid for (rid, r) in records.items() if r['name'] == row['region'] and (rid, row['task']) in allowed]
        if len(ids) != 1:
            raise ValueError('dependency update must identify a disclosed task uniquely')
        rid = ids[0]
        if region_work(records[rid]).get('out_of_scope_reason'):
            continue
        t = owned_tasks(records[rid])[row['task']]
        if not _record_in_scope(records[rid], t, records):
            continue
        if not row['evidence'].strip():
            raise ValueError('dependency update requires observed evidence')
        if t.get('blocker', {}).get('condition') != 'prerequisite':
            continue
        if row['ready']:
            c = find_control(records[rid], t.get('control'))
            observed = any((v.get('evidence', {}).get('source_call') == call for v in observation_history(c)))
            if not observed:
                raise ValueError('不能仅因准备动作完成而解除暂挂：需在本次观察重新确认目标控件已解锁')
            task_audit(t).setdefault('blocker_history', []).append({**t['blocker'], 'resolved_by': call, 'evidence': row['evidence']})
            t.pop('blocker')
            t.update(status='pending')
            t['prerequisite']['satisfied'] = {'source_call': call, 'evidence': row['evidence']}
        else:
            t['prerequisite']['last_check'] = {'source_call': call, 'evidence': row['evidence']}

def prioritize(run, frame=None):
    (_, records, state) = _record_load(run)
    if state.get('next_action_mode') != 'explore':
        return False
    active = state.get('active_task') or {}
    active_task = owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {})
    if active_task.get('status') == 'pending' and _record_in_scope(records.get(active.get('region'), {}), active_task, records):
        return False
    targets = [rid for (rid, r) in records.items() if not region_work(r).get('out_of_scope_reason') and any((t.get('prepares') and (not region_work(records.get(t['prepares']['region'], {})).get('out_of_scope_reason')) and (t.get('status') == 'pending') for t in owned_tasks(r).values()))]
    checks = [(rid, n) for (rid, n, t) in candidates(records) if not t['prerequisite'].get('recheck_requested') and owned_tasks(records.get(t['prerequisite'].get('scheduled', {}).get('region'), {})).get(t['prerequisite'].get('scheduled', {}).get('task'), {}).get('status') == 'done']
    checking = not targets and bool(checks)
    if checking:
        targets = [checks[0][0]]
    if not targets:
        return False
    inspect = checking and targets[0] in state.get('interactive_regions', []) and (frame is not None)
    if state.get('working_region') == targets[0] and (not inspect):
        return False

    def mutate(records, state, *args):
        state.update(working_region=targets[0], deferred_routing_target=targets[0])
        state.pop('active_task', None)
        if inspect:
            owned_tasks(records[checks[0][0]])[checks[0][1]]['prerequisite']['recheck_requested'] = str(frame)
            state.pop('correction_context', None)
            state['required_control'] = owned_tasks(records[checks[0][0]])[checks[0][1]]['control']
            state.update(next_action_mode='discover', phase='awaiting_discovery', pending_frame=str(frame), discovery_mode='local', inspection_region=targets[0], reason='verify_prepared_dependency')
    import uuid
    _record_publish(run, 'prerequisite-priority-' + uuid.uuid4().hex, mutate)
    return True
