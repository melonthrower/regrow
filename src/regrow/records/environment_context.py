"""Readable forests projected from existing identities and observed forward links.

No tree is persisted. Display parents are neither physical containment nor routes.
"""
from regrow.records.object_store import owned_controls, owned_actions, owned_tasks, region_work


def links(records, rid):
    """Use observed forward relations; retain conditions and shared destinations."""
    from regrow.records.control_routes import with_source
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
                or action.get('returns_to_previous') or action.get('result', {}).get('returns_to_previous')
                or action.get('operation') == 'back'):
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


def structure(records):
    """Stable expansion owners; disconnected components and cycles keep their nodes."""
    graph = {rid: links(records, rid) for rid in sorted(records)}
    incoming = {edge['region'] for edges in graph.values() for edge in edges
                if not edge.get('target_control')}
    roots = [rid for rid in graph if rid not in incoming]
    parents, seen, expansion = {}, set(), []

    def visit(rid, parent=None):
        if rid in seen:
            return
        seen.add(rid)
        parents[rid] = parent
        for edge in graph[rid]:
            if not edge.get('target_control'):
                visit(edge['region'], rid)
    for rid in [*roots, *graph]:
        if rid not in seen:
            expansion.append(rid)
            visit(rid)
    return graph, expansion, parents


def forest(records, *, view='controls', focus=None):
    """Two presentations of the same graph; names are always read from current records."""
    if view not in ('controls', 'operations'):
        raise ValueError('unknown forest view')
    graph, roots, parents = structure(records)
    shown, out = set(), []
    title = '控件树' if view == 'controls' else '应用操作树'
    out.append(title + '（已登记内容与已观察的访问关系）')
    out.append('下级区块表示操作可到达的目标；条件标在相应去向旁。')

    def target(edge, depth, source):
        rid = edge['region']
        conditions = edge.get('conditions', [])
        prefix = ('（条件：' + '；'.join(conditions) + '）') if conditions else ''
        observed = edge.get('observed_source')
        if observed in records:
            prefix += '（曾在' + records[observed]['name'] + '观察）'
        cid = edge.get('target_control')
        if cid:
            control = owned_controls(records[rid]).get(cid, {})
            out.append('  '*depth + '└─ ' + prefix + '[引用：' + records[rid]['name'] + ' / '
                       + control.get('name', cid) + ' ' + cid + ']')
        elif rid in shown or parents.get(rid) != source:
            out.append('  '*depth + '└─ ' + prefix + '[引用：' + records[rid]['name'] + ' ' + rid + ']')
        else:
            node(rid, depth, prefix)

    def node(rid, depth, prefix=''):
        shown.add(rid)
        region = records[rid]
        mark = '（当前区块）' if rid == focus else ''
        if region_work(region).get('out_of_scope_reason'):
            mark += '（本次范围外）'
        out.append('  '*depth + ('└─ ' if depth else '') + prefix + region['name'] + ' [' + rid + ']' + mark)
        if view == 'controls':
            for cid, control in owned_controls(region).items():
                out.append('  '*(depth+1) + '├─ ' + control['name'] + ' [' + cid + ']')
                for edge in graph[rid]:
                    if edge.get('control') == cid:
                        target(edge, depth+2, rid)
            for edge in graph[rid]:
                if edge.get('control') is None:
                    out.append('  '*(depth+1) + '├─ 已记录的区块操作')
                    target(edge, depth+2, rid)
        else:
            # Functions remain owned by their original Regions. Shared controls do
            # not move a destination's functions to its entry's owner.
            from regrow.records.function_updates import resolved_constraints
            used = set()
            functions = region.get('functions', {})
            if not functions:
                out.append('  '*(depth+1) + '└─ 尚无已登记应用操作')
            for name, function in functions.items():
                out.append('  '*(depth+1) + '├─ ' + name + ' [' + rid + '/' + name + ']')
                parameters = resolved_constraints(region, function)
                if parameters:
                    out.append('  '*(depth+2) + '参数引用：' + '、'.join(parameters))
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
    for rid in sorted(records):
        if rid not in shown:
            node(rid, 0)
    return '\n'.join(out)


def local_progress(records, focus):
    """Expand progress only for focus, its display parent and siblings."""
    from regrow.records.tasks import coverage
    if focus not in records:
        return ''
    _, _, parents = structure(records)
    parent = parents[focus]
    peers = [rid for rid in sorted(records) if parents.get(rid) == parent] if parent else [focus]
    selected = list(dict.fromkeys(([parent] if parent else []) + peers))
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


def render(records, state, focus, goal=None, kind='observation'):
    goal = goal or {}
    view = 'operations' if kind == 'function_registration' else 'controls'
    out = [forest(records, view=view, focus=focus)]
    if focus in records:
        out.append(local_progress(records, focus))
    gr, cid = goal.get('region'), goal.get('control')
    if gr in records:
        control = owned_controls(records[gr]).get(cid, {})
        out.append('原探索目标：' + records[gr]['name'] + (' / ' + control['name'] if control else ''))
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
    return render(records, state, focus, goal, kind=kind)
