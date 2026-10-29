"""Select explicit task evidence; temporal proximity alone is not relevance."""
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import control_actions
from regrow.records.object_store import find_control

def for_request(records, state, source, work=None):
    """Use the selected obligation before it is persisted, without writing state."""
    if work is not None:
        from regrow.traversal.work_context import reading_state
        return reading_state(state, work)
    owner = source.get('task_region') or source.get('region')
    name = source.get('task_name')
    if name in owned_tasks(records.get(owner, {})):
        return {**state, 'active_task': {'region': owner, 'name': name}}
    return state

def task_attempts(task):
    refs = set(task_value(task, 'attempts', []))
    if task_value(task, 'completion_basis', {}).get('attempt'):
        refs.add(task_value(task, 'completion_basis')['attempt'])
    refs.update(task_value(task, 'completion_basis', {}).get('attempts', []))
    for episode in task_value(task, 'navigation_history', []):
        refs.update((episode.get('completion_basis') or {}).get('attempts', []))
    refs.update((h['invalidated_attempt'] for h in task_value(task, 'ownership_history', []) if h.get('invalidated_attempt')))
    for fact in task_value(task, 'findings', {}).values():
        sources = [fact.get('source', {}), *fact.get('sources', []), *[o.get('source', {}) for o in fact.get('observations', [])]]
        refs.update((s['attempt'] for s in sources if s.get('attempt')))
    return refs

def related_tasks(records, state, related):
    """Expand the selected obligation and explicit preparation only.

    Completed tasks remain in the task catalog and control knowledge; planning
    does not need to replay every completed task's execution history.
    """
    from regrow.records.context_scope import task_refs
    for (owner, name) in task_refs(records, state):
        yield (owner, name, owned_tasks(records[owner])[name])

def latest_control_attempt(region, task):
    """Related evidence can belong to another task; ownership does not change."""
    cid = task.get('control')
    if not find_control(region, cid):
        return None
    from regrow.records.control_context import same_use
    refs = [aid for (aid, action) in control_actions(region, cid).items() if action.get('association', {}).get('status') != 'unconfirmed' and same_use(task, action)]
    if not refs:
        return None
    from regrow.records.page_history import _order
    return max(refs, key=_order)
