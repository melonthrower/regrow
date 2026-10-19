from regrow.records.control_knowledge import parameters
from regrow.records.action_evidence import entries_for_action
from regrow.records.tasks import read as task_value
'Select request materials by the working Region and explicit task references.\n\nThis is a read-only request view, not another task ledger. Identity matching and\nregistration keep the full graph; prompt consumers use these same selections.\n'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
MISSING = object()

def rule_selection(request, *, tasks=MISSING, binding=None):
    """Freeze known request facts, independently of later active-task changes.

    An unknown candidate list is None; an explicitly empty list stays empty.
    This metadata selects guidance, never grants registration permission.
    """
    original = request
    while original.get('role') in ('step_correction', 'control_identity_selection') and original.get('original_request'):
        original = original['original_request']
    saved = original.get('context_scope', {}).get('selection')
    if saved is not None:
        return deepcopy(saved)
    from regrow.records.task_settlement import registration_kind
    from regrow.prompts.output import effective_role
    work = original.get('work_context', {})
    kinds = None if tasks is MISSING else sorted({registration_kind(t) for t in tasks})
    return {'role': effective_role(original), 'mode': original.get('discovery_context', {}).get('mode'), 'work_kind': work.get('kind'), 'source': deepcopy(original.get('source', {})), 'task_types': kinds, 'preparatory_action': bool((binding or {}).get('preparatory_action'))}

def task_refs(records, state, work=None):
    work = work if work is not None else state.get('_work_context', {})
    active = work.get('task') if 'task' in work else state.get('active_task')
    refs = set()

    def add(ref):
        if not ref:
            return
        (rid, name) = (ref.get('region'), ref.get('name', ref.get('task')))
        if name in owned_tasks(records.get(rid, {})):
            refs.add((rid, name))
    add(active)
    if active:
        task = owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {})
        add(task.get('prepares'))
        add((task.get('prerequisite') or {}).get('scheduled'))
        for (rid, region) in records.items():
            for (name, candidate) in owned_tasks(region).items():
                if candidate.get('prepares') == {'region': active.get('region'), 'task': active.get('name')}:
                    add({'region': rid, 'name': name})
    if work.get('kind') in ('scope_review', 'task_proposal'):
        rid = work.get('region')
        refs.update(((rid, name) for (name, t) in owned_tasks(records.get(rid, {})).items() if t.get('status') in ('pending', 'blocked')))
    return sorted(refs)

def preparation_entries(records, state, work=None):
    """Visible entrances with recorded evidence of revealing the task control.

    A necessary route can predate a preparation task. Match the target's actual
    observation to an executed entry, never infer a route from similar names.
    """
    work = work if work is not None else state.get('_work_context', {})
    if work.get('kind') not in (None, 'action', 'navigate', 'locate', 'recover'):
        return []
    active = work.get('task') if 'task' in work else state.get('active_task')
    if not active:
        return []
    owner = records.get(active.get('region'), {})
    task = owned_tasks(owner).get(active.get('name'), {})
    from regrow.records.task_settlement import completion_target
    target = completion_target(owner, task) if task else {}
    cid = target.get('control')
    visible = set((state.get('observation') or {}).get('control_refs', []))
    if not cid or cid in visible:
        return []
    control = owned_controls(records.get(target.get('region'), {})).get(cid, {})
    observations = {o.get('evidence', {}).get('observation') for o in observation_history(control) if not o.get('visual_only')} - {None}
    result = []
    for rid in state.get('interactive_regions', []):
        for (aid, action) in owned_actions(records.get(rid, {})).items():
            if action.get('control') in visible and entries_for_action(records[rid], aid, action.get('control')) and (action.get('delivery') == 'executed_receipt_zero') and (action.get('result', {}).get('exception') in (None, '', 'none')) and (action.get('evidence', {}).get('after_observation') in observations):
                result.append((rid, action['control'], aid))
    return result

def select(records, state, *, work=None, source=None, regions=(), controls=()):
    """Current surface identities stay available; task details do not spread."""
    source = source or {}
    work = work if work is not None else state.get('_work_context', {})
    focus = work.get('region') or source.get('region') or state.get('working_region')
    tasks = task_refs(records, state, work)
    owners = {focus, source.get('region'), source.get('working_region'), source.get('task_region'), *regions, *(rid for (rid, _) in tasks)} - {None}
    surface = set(state.get('interactive_regions', []))
    selected = {rid: set() for rid in owners | surface if rid in records}
    for (rid, name) in tasks:
        task = owned_tasks(records[rid])[name]
        selected.setdefault(rid, set()).add(task.get('control'))
        target = task.get('completion_action') or {}
        if target.get('region') in records:
            selected.setdefault(target['region'], set()).add(target.get('control'))
    for (rid, cid) in controls:
        if rid in records:
            selected.setdefault(rid, set()).add(cid)
    for (rid, cid, _) in preparation_entries(records, state, work):
        selected.setdefault(rid, set()).add(cid)
    for key in ('task_control', 'control_ref'):
        cid = source.get(key)
        if cid:
            for rid in owners:
                if cid in owned_controls(records.get(rid, {})):
                    selected.setdefault(rid, set()).add(cid)
    return {'region': focus, 'kind': work.get('kind'), 'tasks': [{'region': rid, 'name': name} for (rid, name) in tasks], 'regions': sorted((rid for rid in owners if rid in records)), 'controls': {rid: sorted((cid for cid in ids if cid in owned_controls(records[rid]))) for (rid, ids) in sorted(selected.items())}}

def for_request(request, records, state, *, regions=(), controls=()):
    from regrow.traversal.work_context import from_request
    work = from_request(request, records, state)
    scope = select(records, state, work=work, source=request.get('source'), regions=regions, controls=controls)
    tasks = MISSING
    if 'task_update_candidates' in request:
        tasks = [owned_tasks(records[row['region']])[row['name']] for row in request['task_update_candidates']]
    elif 'task' in work:
        ref = work['task']
        tasks = [] if ref is None else [owned_tasks(records.get(ref['region'], {})).get(ref['name'], {})]
    scope['selection'] = rule_selection(request, tasks=tasks)
    request['context_scope'] = scope
    return scope

def identity(region, cid, *, detailed=False, records=None):
    """The object's current identity and function, without raw source metadata."""
    from regrow.records.control_history_context import describe
    row = describe(region, cid, detailed=detailed)
    row['ref'] = cid
    return row

def history_changes(records, state, owner, action):
    """Select historical visibility details for the current question, not storage."""
    changes = action.get('region_changes', [])
    work = state.get('_work_context') or {}
    if work.get('kind') not in ('action', 'navigate', 'locate') or action.get('result', {}).get('exception') not in (None, '', 'none') or any((row.get('remaining_question') for region in records.values() for task in owned_tasks(region).values() for row in [task_value(task, 'latest_update', {})] if row.get('source', {}).get('source_call') == action.get('evidence', {}).get('result_call'))):
        return deepcopy(changes)
    scope = select(records, state, work=work)
    related = {owner, *scope['regions'], *action.get('interactive_regions', []), *action.get('evidence', {}).get('before_regions', [])}
    return [deepcopy(row) for row in changes if row.get('region') in related or row.get('region') not in records or row.get('state') not in ('visible_background_blocked', 'not_visible')]

def source_attempts(view, scope):
    """Prompt arrival evidence; the dashboard can retain the full visit index."""
    if scope.get('tasks') and scope.get('kind') in ('action', 'update', 'task_proposal', 'scope_review'):
        return []
    if view.get('last_action'):
        return [view['last_action']['attempt']]
    focus = scope['region']
    refs = [row['attempt'] for row in view.get('incoming_actions', {}).get(focus, [])]
    refs.extend((row['via']['attempt'] for row in view.get('origin', {}).get('known_entries', []) if focus in row.get('to_regions', [])))
    from regrow.records.page_history import _order
    return [max(refs, key=_order)] if refs else []

def region_information(region, scope):
    if scope.get('kind') in ('locate', 'update', 'task_proposal', 'scope_review'):
        return {}
    if region['id'] not in scope.get('regions', []):
        return {}
    return {k: deepcopy(region[k]) for k in ('local_knowledge', 'constraints') if region.get(k)}

def control_information(region, cid, scope):
    if scope.get('kind') in ('locate', 'update', 'task_proposal', 'scope_review'):
        return {}
    from regrow.records.control_history_context import known_information
    control = owned_controls(region)[cid]
    result = {}
    value = known_information(control, parameters=False)
    if value:
        result['knowledge'] = value
    records = getattr(region, 'store', {region['id']: region})
    pending = [owned_tasks(records.get(ref['region'], {})).get(ref['name'], {}) for ref in scope.get('tasks', [])]
    needed = any((task.get('status') in ('pending', 'blocked') and (task.get('completion_action') or {}).get('control', task.get('control')) == cid for task in pending))
    if needed and parameters(control):
        result['constraints'] = deepcopy(parameters(control))
    from regrow.records.shared_controls import view
    if view(records, region['id'], cid):
        from regrow.records.task_knowledge import control_knowledge
        shared = {key: value for (key, value) in control_knowledge(region, cid, getattr(region, 'store', None)).items() if value.get('source', {}).get('shared')}
        if shared:
            result['共享知识'] = shared
    return result
