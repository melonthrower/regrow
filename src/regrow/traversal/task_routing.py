from regrow.records.tasks import coverage as _record_coverage
from regrow.records.object_store import incoming
'Observed entry ancestry and task continuation; ancestry is not a return edge.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks

def entry_path(records, current):
    path = []
    seen = set()
    rid = current
    while rid in records and rid not in seen:
        seen.add(rid)
        path.insert(0, rid)
        entries = incoming(records[rid], records)
        if not entries:
            break
        source = None
        for e in reversed(entries):
            candidate = e['source_region']
            action = owned_actions(records.get(candidate, {})).get(e['attempt'], {})
            if candidate != rid and action.get('delivery') == 'executed_receipt_zero' and (action.get('operation') != 'back'):
                source = candidate
                break
        if source is None:
            break
        rid = source
    return path

def path_for(records, state, current):
    path = state.get('region_path', [])
    return path[:path.index(current) + 1] if current in path else entry_path(records, current)

def parent_region(records, state, current):
    path = path_for(records, state, current)
    return path[-2] if len(path) > 1 else None

def destination_work(records, refs):
    """Choose work among observed destinations, not a unique navigation edge."""
    if len(refs) == 1:
        return refs[0]
    if not refs:
        return None
    return min(refs, key=lambda rid: _record_coverage(records[rid], records)['complete'])

def advance(records, previous, state, source, binding, attempt):
    path = path_for(records, previous, source)
    refs = state['interactive_regions']
    if len(refs) == 1:
        dest = refs[0]
        if dest in path:
            path = path[:path.index(dest) + 1]
        else:
            path.append(dest)
    state['region_path'] = path
    target = previous.get('deferred_routing_target')
    if target and target not in refs:
        state['deferred_routing_target'] = target
    if binding.get('task_name') and refs:
        owner = records[binding.get('task_region', source)]
        task = owned_tasks(owner).get(binding['task_name'], {})
        action = owned_actions(records[source]).get(attempt, {})
        if task.get('control') and task.get('status') == 'done' and (not binding.get('preparatory_action')) and (binding.get('task_region', source) == source) and (task.get('control') == binding.get('control_ref')) and (action.get('operation') in ('click', 'tap')) and (action.get('delivery') == 'executed_receipt_zero') and (action.get('result', {}).get('exception') == 'none'):
            from regrow.records.action_evidence import entries_for_action
            observed_targets = list(dict.fromkeys(edge['region'] for edge in
                entries_for_action(records[source], attempt, binding['control_ref'])
                if edge['region'] in refs and edge['region'] in records and edge['region'] != source))
            # A confirmed effect selects the reached surface even when its source remains visible.
            # Without a declared destination retain the existing source-disappeared fallback.
            candidates = observed_targets or (refs if source not in refs else [])
            dest = destination_work(records, candidates)
            if dest is not None:
                task_audit(task).setdefault('completion_basis', {}).update(destination_region=dest, destination_regions=list(candidates))
                state['working_region'] = dest
                state['region_path'] = path[:path.index(dest) + 1] if dest in path else path + [dest]
                state.pop('deferred_routing_target', None)
                state.pop('active_task', None)
    active = previous.get('active_task')
    if binding.get('task_name'):
        active = {'region': binding.get('task_region', source), 'name': binding['task_name']}
    if active:
        task = owned_tasks(records[active['region']]).get(active['name'])
        if task and task['status'] == 'pending':
            state['active_task'] = active
    if binding.get('task_name'):
        task = owned_tasks(records[binding.get('task_region', source)])[binding['task_name']]
        task_audit(task).setdefault('visited_regions', [])
        for rid in refs:
            if rid not in task_value(task, 'visited_regions'):
                task_value(task, 'visited_regions').append(rid)
