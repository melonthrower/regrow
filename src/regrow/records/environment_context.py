"""Readable navigation views projected from observed Region access links.

No Region containment tree is stored. Indentation is display order only.
"""
from regrow.records.object_store import owned_controls, owned_actions, owned_tasks, region_work


def links(records, rid):
    """Use observed forward relations; retain conditions and shared destinations."""
    from regrow.records.control_routes import with_source
    from regrow.records.navigation import contextual_return
    region = records[rid]
    candidates = []
    for cid, record in [(None, region), *owned_controls(region).items()]:
        for route in record.get('jump_to', []):
            edge = with_source(record, route)
            candidates.append({**edge, 'control': cid, 'target_control': route.get('control')})
    actions = {aid: (owner, action) for owner, record in records.items()
               for aid, action in owned_actions(record).items()}
    rows, seen = [], set()
    for edge in candidates:
        target = edge.get('region')
        source, action = actions.get(edge.get('attempt'), (None, {}))
        if (target not in records or not edge.get('attempt')
                or action.get('delivery') != 'executed_receipt_zero'
                or action.get('result', {}).get('exception', 'none') != 'none'
                or contextual_return(action)):
            continue
        if source != rid:
            edge['observed_source'] = source
        if target == rid and not edge.get('target_control'):
            continue
        key = (edge.get('control'), target, edge.get('target_control'), tuple(edge.get('conditions', [])))
        if key not in seen:
            seen.add(key)
            rows.append(edge)
    return rows


def structure(records, region_ids=None):
    """Stable expansion owners; disconnected components and cycles keep their nodes."""
    selected = records.keys() if region_ids is None else records.keys() & set(region_ids)
    graph = {rid: links(records, rid) for rid in sorted(selected)}
    incoming = {edge['region'] for edges in graph.values() for edge in edges
                if not edge.get('target_control')}
    roots = [rid for rid in graph if rid not in incoming]
    expansion_sources, seen, expansion = {}, set(), []

    def visit(rid, source=None):
        if rid in seen:
            return
        seen.add(rid)
        expansion_sources[rid] = source
        for edge in graph[rid]:
            if not edge.get('target_control') and edge['region'] in graph:
                visit(edge['region'], rid)
    for rid in [*roots, *graph]:
        if rid not in seen:
            expansion.append(rid)
            visit(rid)
    return graph, expansion, expansion_sources


def forest(records, *, view='controls', focus=None, task_region=None, region_ids=None, interaction=None,
           control_regions=None):
    """Two presentations of the same graph; names are always read from current records."""
    if view not in ('controls', 'operations'):
        raise ValueError('unknown forest view')
    graph, roots, expansion_sources = structure(records, region_ids)
    shown, out = set(), []
    interaction = interaction or {}
    overview = view == 'controls' and control_regions is not None
    title = '应用结构概览' if overview else '控件树' if view == 'controls' else '应用操作树'
    if region_ids is not None:
        title = '局部' + title
    out.append(title if overview else title + '（已登记内容与已观察的访问关系）')
    if not overview:
        out.append('缩进只展示已观察的操作可达关系；条件标在相应去向旁。')

    def tasks(region, cid, depth):
        if region['id'] != task_region:
            return
        from regrow.records.task_settlement import task_definition
        labels = {'done': '已完成', 'pending': '待推进', 'blocked': '暂挂'}
        for task in owned_tasks(region).values():
            if task.get('control') == cid:
                out.append('  '*depth + '任务：' + task_definition(task)['label']
                           + '；' + labels.get(task.get('status'), task.get('status', '未知')))

    def target(edge, depth, source):
        rid = edge['region']
        if overview:
            if rid not in shown and expansion_sources.get(rid) == source:
                node(rid, depth)
            return
        conditions = edge.get('conditions', [])
        prefix = ('（条件：' + '；'.join(conditions) + '）') if conditions else ''
        observed = edge.get('observed_source')
        if observed in records:
            prefix += '（曾在' + records[observed]['name'] + '观察）'
        cid = edge.get('target_control')
        if cid:
            control = owned_controls(records[rid]).get(cid, {})
            out.append('  '*depth + '└─ ' + prefix + '[引用：' + rid + '/' + records[rid]['name']
                       + ' / ' + cid + '/' + control.get('name', cid) + ']')
        elif rid in shown or expansion_sources.get(rid) != source:
            out.append('  '*depth + '└─ ' + prefix + '[引用：' + rid + '/' + records[rid]['name'] + ']')
        else:
            node(rid, depth, prefix)

    def node(rid, depth, prefix=''):
        shown.add(rid)
        region = records[rid]
        mark = '（本步关注区块）' if rid == focus else ''
        if rid == interaction.get('region'):
            mark += '【上次交互所在区块】'
        if region_work(region).get('out_of_scope_reason'):
            mark += '（本次范围外）'
        out.append('  '*depth + '└─ ' + prefix + rid + '/' + region['name'] + mark)
        tasks(region, None, depth+1)
        if view == 'controls':
            for cid, control in owned_controls(region).items():
                if control_regions is not None and rid not in control_regions:
                    continue
                mark = ''
                if rid == interaction.get('region') and cid == interaction.get('control_ref'):
                    from regrow.prompts.prompt_material import identity_steps
                    operation = identity_steps([{'action': interaction['operation']}])[0]['操作']
                    mark = '【上次交互：' + operation + '】'
                out.append('  '*(depth+1) + '├─ ' + cid + '/' + control['name'] + mark)
                if mark:
                    from regrow.records.control_knowledge import card
                    from regrow.prompts.history_disclosure import readable
                    knowledge = card(control)
                    if knowledge:
                        out.extend('  '*(depth+2) + line for line in
                                   readable({'已有知识': knowledge}, 1).splitlines())
                tasks(region, cid, depth+2)
                if control_regions is None:
                    for edge in graph[rid]:
                        if edge.get('control') == cid:
                            target(edge, depth+2, rid)
            if control_regions is None:
                for edge in graph[rid]:
                    if edge.get('control') is None:
                        out.append('  '*(depth+1) + '├─ 已记录的区块操作')
                        target(edge, depth+2, rid)
            else:
                for edge in graph[rid]:
                    if edge['region'] == rid:
                        continue
                    target({**edge, 'target_control': None}, depth+1, rid)
        else:
            # Functions remain owned by their original Regions. Shared controls do
            # not move a destination's functions to its entry's owner.
            from regrow.records.candidate_access import candidate_access_entries, describe
            from regrow.records.function_updates import resolved_parameters
            candidates = candidate_access_entries(records, rid)
            used = set()
            functions = region.get('functions', {})
            if not functions:
                out.append('  '*(depth+1) + '└─ 尚无已登记应用操作')
            for name, function in functions.items():
                out.append('  '*(depth+1) + '├─ ' + name + ' [' + rid + '/' + name + ']')
                parameters = resolved_parameters(records, function)
                if parameters:
                    out.append('  '*(depth+2) + '参数引用：' + '、'.join(parameters))
                if function.get('target_role'):
                    out.append('  '*(depth+2) + '预期目标职责：' + function['target_role'])
                for row in candidates:
                    if row['function_ref'] == rid + '/' + name:
                        out.append('  '*(depth+2) + describe(row, records))
                supports = {row.get('control') for row in function.get('support_controls', [])}
                for index, edge in enumerate(graph[rid]):
                    if edge.get('control') is not None and edge.get('control') in supports:
                        used.add(index)
                        out.append('  '*(depth+2) + '相关已知去向（不表示必需步骤）')
                        target(edge, depth+3, rid)
            remaining = [edge for i, edge in enumerate(graph[rid]) if i not in used]
            if remaining:
                out.append('  '*(depth+1) + '├─ 尚未关联到具体操作的已知去向')
                for edge in remaining:
                    target(edge, depth+2, rid)
    for rid in roots:
        if rid not in shown:
            node(rid, 0)
    # Different function ordering cannot drop a component from the view.
    for rid in sorted(graph):
        if rid not in shown:
            node(rid, 0)
    return '\n'.join(out)


def local_progress(records, focus):
    """Expand progress only for focus and nearby access-map entries."""
    from regrow.records.tasks import coverage
    if focus not in records:
        return ''
    _, _, sources = structure(records)
    source = sources[focus]
    peers = [rid for rid in sorted(records) if sources.get(rid) == source] if source else [focus]
    selected = list(dict.fromkeys(([source] if source else []) + peers))
    lines = ['局部探索进度']
    for rid in selected:
        progress = coverage(records[rid], records)
        status = ('本次范围外' if progress.get('excluded') else '探索完成' if progress['complete']
                  else '已提出任务' if progress['inventory_complete'] else '尚未完成任务提出')
        lines.append(records[rid]['name'] + ' [' + rid + ']：' + status
                     + '；已解决' + str(len(progress['done']))
                     + '、待推进' + str(len(progress['pending']))
                     + '、暂挂' + str(len(progress['blocked'])))
    return '\n'.join(lines)


def render(records, state, focus, goal=None, kind='observation', interaction=None):
    goal = goal or {}
    control_regions = {focus}
    if kind == 'update' and interaction:
        control_regions.add(interaction.get('working_region'))
    out = [forest(records, view='controls', focus=focus,
                  task_region=focus if kind == 'task_proposal' else None,
                  control_regions=control_regions, interaction=interaction)]
    gr, cid = goal.get('region'), goal.get('control')
    if gr in records:
        control = owned_controls(records[gr]).get(cid, {})
        out.append('原探索目标：' + records[gr]['name']
                   + (' / ' + control['name'] if control and gr == focus else ''))
    last = state.get('last_action_result') or {}
    action = owned_actions(records.get(last.get('region'), {})).get(last.get('action'), {})
    obs = state.get('observation') or {}
    foreground = state.get('interactive_regions', []) if obs else action.get('interactive_regions', [])
    if foreground:
        out.append('上次已登记前景：' + '、'.join(records[r]['name'] for r in foreground if r in records))
    background = [c['region'] for c in action.get('region_changes', [])
                  if c.get('state') == 'visible_background_blocked' and c.get('region') in records]
    if background:
        out.append('上次更新所报背景：' + '、'.join(records[r]['name'] for r in background))
    if kind == 'update':
        out.append('位置材料来自动作前；本步结果以动作后图为准。')
    return '\n'.join(out)


def for_request(request, records, state):
    # Corrections keep the original question's identity/execution scope.
    while request.get('original_request'):
        request = request['original_request']
    source = request.get('source', {})
    work = request.get('work_context', {})
    focus = source.get('region') or request.get('discovery_context', {}).get('focus') or work.get('region') or state.get('working_region')
    rid = source.get('task_region');goal = {}
    if rid in records:
        task = owned_tasks(records[rid]).get(source.get('task_name'), {})
        goal = {'region': rid, 'control': source.get('task_control', task.get('control'))}
    elif source.get('return_to') in records:
        goal = {'region': source['return_to']}
    elif request.get('stage') == 'task_proposal':
        goal = {'region': focus}
    kind = 'update' if request.get('role') == 'observation_update' else request.get('role', work.get('kind'))
    interaction = source if kind == 'update' and source.get('attempt') and source.get('operation') else None
    return render(records, state, focus, goal, kind=kind, interaction=interaction)
