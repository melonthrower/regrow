"""Select explicit task evidence; temporal proximity alone is not relevance."""


def for_request(records,state,source):
    """Use the selected obligation before it is persisted, without writing state."""
    owner=source.get('task_region') or source.get('region')
    name=source.get('task_name')
    if name in records.get(owner,{}).get('tasks',{}):
        return {**state,'active_task':{'region':owner,'name':name}}
    return state


def task_attempts(task):
    refs = set(task.get('attempts', []))
    if task.get('completion_basis',{}).get('attempt'):refs.add(task['completion_basis']['attempt'])
    refs.update(task.get('completion_basis', {}).get('attempts', []))
    for episode in task.get('navigation_history', []):
        refs.update((episode.get('completion_basis') or {}).get('attempts', []))
    refs.update(h['invalidated_attempt'] for h in task.get('ownership_history', [])
                if h.get('invalidated_attempt'))
    for fact in task.get('findings', {}).values():
        sources = [fact.get('source', {}), *fact.get('sources', []),
                   *[o.get('source', {}) for o in fact.get('observations', [])]]
        refs.update(s['attempt'] for s in sources if s.get('attempt'))
    return refs


def related_tasks(records, state, related):
    """Current obligation plus its explicit preparation; planning sees local tasks."""
    active = state.get('active_task') or {}
    owner, name = active.get('region'), active.get('name')
    task = records.get(owner, {}).get('tasks', {}).get(name)
    if task is not None:
        yield owner, name, task
        parent=task.get('prepares',{})
        parent_task=records.get(parent.get('region'),{}).get('tasks',{}).get(parent.get('task'))
        if parent_task is not None:yield parent['region'],parent['task'],parent_task
        for rid, region in records.items():
            for label, candidate in region.get('tasks', {}).items():
                if candidate.get('prepares') == {'region':owner, 'task':name}:
                    yield rid, label, candidate
        return
    for rid in related:
        for label, candidate in records.get(rid, {}).get('tasks', {}).items():
            yield rid, label, candidate
