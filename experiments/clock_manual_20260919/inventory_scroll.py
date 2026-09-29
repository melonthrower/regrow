"""Route explicit Region scrolling while retaining an incomplete task inventory."""


def eligible(region, task):
    prerequisite = task.get('prerequisite') or {}
    return (not region.get('out_of_scope_reason')
            and task.get('status') == 'pending' and task.get('handling') == 'explore'
            and task.get('task_type') == 'scroll' and task.get('action') == 'scroll'
            and task.get('control') is None and not task.get('blocker')
            and (not prerequisite or bool(prerequisite.get('satisfied'))))


def select(region, reply):
    if reply.get('inventory') != 'partial':
        return None
    for row in reply.get('operations', []):
        task = region.get('tasks', {}).get(row['name'], {})
        if eligible(region, task):
            return row['name']
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
    # The normal acceptance path validates this exact schema before binding.
    request['response_schema']['properties']['action']['enum'] = ['scroll', 'none']
    request.update(preparation_allowed=False, allow_back=False, allow_input=False,
                   backend_candidates=[])
    request['user_prompt'] += ('\n\n当前清点仍为partial，身份缺口尚未解决。本轮只允许在已确认的'
        '当前区块内scroll取得缺失上下文，或none说明为何无法滚动；不能点击、输入或返回。'
        '滚动后必须依据真实新图重新核对缺口，不能仅因投递成功就宣布身份或清点完成。')
    request['dynamic_prompt'] = request['user_prompt']
    return request


def resume_after_region_observation(run, request, call):
    """A Region scroll needs its observed boundary, not a complete control scan."""
    import discovery_step
    import region_scroll
    _, records, state = discovery_step.load(run)
    source = request.get('source', {})
    rid = source.get('task_region')
    chosen = state.get('active_task') or {}
    if (source.get('task_type') != 'scroll' or chosen.get('region') != rid
            or chosen.get('name') != source.get('task_name')
            or state.get('reason') != 'locate_local_controls'
            or state.get('discovery_completion', {}).get('pending')
            or not active(records, state, rid)):
        return False
    obs = state['observation']
    probe = {'allow_scroll': True, 'source': {'region': rid, 'observation': obs['id']},
             'image_refs': [obs['image']]}
    region_scroll.attach(run, state, probe)
    if not probe.get('region_scroll_bounds'):
        return False
    def advance(records, state, *args):
        state.update(next_action_mode='explore', phase='ready_for_next_action',
                     reason='scroll_region_observed')
        # The partial inventories and original task remain unmodified.
    discovery_step.publish(run, 'scroll-region-observed-'+call, advance)
    return True
