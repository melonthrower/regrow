"""Route explicit Region scrolling while retaining an incomplete task inventory."""


def eligible(region, task):
    prerequisite = task.get('prerequisite') or {}
    return (not region.get('out_of_scope_reason')
            and task.get('status') == 'pending' and task.get('handling') == 'explore'
            and task.get('task_type') == 'scroll' and task.get('action') == 'scroll'
            and task.get('control') is None and not task.get('blocker')
            and (not prerequisite or bool(prerequisite.get('satisfied'))))


def select(region, reply):
    if reply.get('inventory') == 'complete':
        return None
    for row in reply.get('operations', []):
        if row.get('task_type') != 'scroll' or row.get('control'):
            continue
        # apply_plan may have merged the reply name into an existing task.
        for name, task in region.get('tasks', {}).items():
            if eligible(region, task):
                return name
    return None


def target(records, state):
    chosen = state.get('active_task') or {}
    region = records.get(chosen.get('region'), {})
    if (region.get('task_inventory', {}).get('inventory') == 'partial'
            and eligible(region, region.get('tasks', {}).get(chosen.get('name'), {}))):
        return chosen['region']
    return None


def active(records, state, rid):
    foreground = (state.get('observation') or {}).get('foreground', {})
    return (target(records, state) == rid and rid in state.get('interactive_regions', [])
            and foreground.get('exception', 'none') == 'none')


def restrict(request):
    request.update(preparation_allowed=True, allow_back=True, allow_input=True)
    request['user_prompt'] += ('\n\n当前清点有缺口，先推进可信滚动目标；允许关闭遮挡等必要准备动作，'
        '准备动作不完成滚动任务。直接按当前单图选择滚动坐标，不要求预先登记区块框。'
        '滚动后依据真实新图登记结果，不能因投递成功宣布清点完整。')
    request['dynamic_prompt'] = request['user_prompt']
    return request


def resume_after_region_observation(run, request, call):
    """Resume the same foreground Region task without waiting for a full scan."""
    import discovery_step
    _, records, state = discovery_step.load(run)
    source = request.get('source', {})
    rid = source.get('task_region')
    chosen = state.get('active_task') or {}
    if (source.get('task_type') != 'scroll' or chosen.get('region') != rid
            or chosen.get('name') != source.get('task_name')
            or state.get('reason') != 'locate_local_controls'
            or not active(records, state, rid)):
        return False
    def advance(records, state, *args):
        state.update(next_action_mode='explore', phase='ready_for_next_action',
                     reason='scroll_region_observed')
        # The partial inventories and original task remain unmodified.
    discovery_step.publish(run, 'scroll-region-observed-'+call, advance)
    return True
