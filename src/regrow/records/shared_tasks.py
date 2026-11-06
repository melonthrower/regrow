"""Retire historical shared-task effects without recreating a member backlog."""
from copy import deepcopy

from regrow.records.tasks import audit, detached, read as task_value

FIELDS = ('shared_result', 'shared_task_ref', 'shared_task_active',
          'shared_prior_state', 'shared_origin_state', 'shared_definition')


def local_state(task, records=None):
    """One rule for legacy reads and normalization; None means a pure old copy."""
    if not any(key in task for key in FIELDS):
        return task
    from regrow.records.object_store import owned_actions
    from regrow.records.task_settlement import registered_result
    records = records if records is not None else getattr(task, 'store', {})
    history = audit(task)
    latest = task_value(task, 'latest_update', {}) or {}
    basis = history.get('completion_basis', {})
    attempts = task_value(task, 'attempts', [])
    actions = {aid: action for region in records.values() for aid, action in owned_actions(region).items()}
    invalid = {row['invalidated_attempt'] for row in history.get('ownership_history', [])
               if row.get('invalidated_attempt')}
    valid = [aid for aid in attempts if aid not in invalid
             and actions.get(aid, {}).get('delivery') == 'executed_receipt_zero'
             and actions[aid].get('result', {}).get('exception', 'none') == 'none'
             and registered_result(task, actions[aid], aid)]
    source = latest.get('source') or basis
    own_source = bool(source and not source.get('shared') and
                      any(source.get(key) for key in ('source_call', 'observation', 'attempt', 'attempts')))
    local_work = bool(attempts or latest or own_source or history.get('source_call')
                      or task.get('remaining_question') or task.get('registration_gap')
                      or task.get('blocker') or task.get('prepares'))
    if task.get('shared_task_ref') and not local_work:
        return None
    result = {key: value for key, value in task.items() if key not in FIELDS}
    prior = task.get('shared_prior_state') or task.get('shared_origin_state') or {}
    if task.get('shared_result') or task.get('shared_task_ref') and task.get('status') == 'done':
        # A later independent judgement wins over the saved pre-inheritance state.
        if latest.get('state') in ('pending', 'blocked'):
            result['status'] = latest['state']
        elif latest.get('state') == 'done' and own_source:
            result['status'] = 'done'
        elif task.get('status') == 'done' and (valid or own_source and basis):
            result['status'] = 'done'
        else:
            result.update(deepcopy(prior))
            if result.get('status') not in ('pending', 'blocked'):
                result['status'] = 'blocked' if task.get('blocker') else 'pending'
    return result


def normalize(records, state=None):
    """Normalize in memory on load and persist with the next normal transaction."""
    from regrow.records.object_store import owned_tasks, owned_controls, observation_history, region_work
    changed = False
    for rid, region in records.items():
        tasks = owned_tasks(region)
        for name, task in list(tasks.items()):
            if not any(key in task for key in FIELDS):
                continue
            result = local_state(task, records)
            original = detached(task)
            if result is None:
                control = owned_controls(region).get(task.get('control'))
                owner = control if control is not None else region
                observation_history(owner, create=True).append({
                    'shared_task_history': [{'name': name, 'record': original,
                                             'retired_because': 'shared_task_projection_removed'}]})
                del tasks[name]
                if state is not None and state.get('active_task') == {'region': rid, 'name': name}:
                    state.pop('active_task', None)
            else:
                audit(task).setdefault('shared_history', []).append({
                    'record': original, 'retired_because': 'shared_task_projection_removed'})
                for key in FIELDS:
                    task.pop(key, None)
                task.update(result)
            changed = True
        inventory = region_work(region).get('task_inventory', {})
        if inventory.get('review', {}).get('kind') == 'shared_behavior':
            inventory.pop('review')
            changed = True
    active = (state or {}).get('active_task') or {}
    if active.get('region') in records:
        owner = records[active['region']]
        if active.get('name') not in owned_tasks(owner):
            retired = [row for record in [owner, *owned_controls(owner).values()]
                       for event in observation_history(record)
                       for row in event.get('shared_task_history', [])]
            if any(row.get('name') == active.get('name') and
                   row.get('retired_because') == 'shared_task_projection_removed' for row in retired):
                state.pop('active_task', None)
                changed = True
    return changed
