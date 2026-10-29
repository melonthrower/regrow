from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
'Continue Region questions while retaining an incomplete task inventory.'
from regrow.records.object_store import owned_tasks

def eligible(region, task):
    prerequisite = task.get('prerequisite') or {}
    return not region_work(region).get('out_of_scope_reason') and task.get('status') == 'pending' and (not task.get('equivalent_to')) and (task.get('control') is None) and (not task.get('blocker')) and (not prerequisite or bool(prerequisite.get('satisfied')))

def select(region, reply):
    from regrow.records.task_settlement import registration_kind
    if reply.get('inventory') == 'complete':
        return None
    for row in reply.get('operations', []):
        if 'task' in row:
            from regrow.records.task_updates import reference
            for (name, task) in owned_tasks(region).items():
                if row['task'] == reference(region['id'], name) and row.get('decision') == 'continue' and eligible(region, task):
                    return name
            continue
        if row.get('control'):
            continue
        for (name, task) in owned_tasks(region).items():
            if eligible(region, task) and registration_kind(task) == registration_kind(row):
                return name
    return None

def target(records, state):
    chosen = state.get('active_task') or {}
    region = records.get(chosen.get('region'), {})
    if region_work(region).get('task_inventory', {}).get('inventory') == 'partial' and eligible(region, owned_tasks(region).get(chosen.get('name'), {})):
        return chosen['region']
    return None

def active(records, state, rid):
    foreground = (state.get('observation') or {}).get('foreground', {})
    return target(records, state) == rid and rid in state.get('interactive_regions', []) and (foreground.get('exception', 'none') == 'none')

def restrict(request):
    request.update(preparation_allowed=True, allow_back=True, allow_input=True)
    from regrow.prompts.prompt_material import assign
    return assign(request, {'当前清点缺口': '继续回答当前区块问题，结合当前截图选择操作，并据新观察补充发现。'})

def resume_after_region_observation(run, request, call):
    """Resume the same foreground Region task without waiting for a full scan."""
    (_, records, state) = _record_load(run)
    source = request.get('source', {})
    rid = source.get('task_region')
    chosen = state.get('active_task') or {}
    if source.get('task_control') is not None or chosen.get('region') != rid or chosen.get('name') != source.get('task_name') or (state.get('reason') != 'locate_local_controls') or (not active(records, state, rid)):
        return False

    def advance(records, state, *args):
        state.update(next_action_mode='explore', phase='ready_for_next_action', reason='scroll_region_observed')
    _record_publish(run, 'scroll-region-observed-' + call, advance)
    return True
