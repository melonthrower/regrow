"""Read-only page composition and visit ancestry derived from recorded evidence.

Composition, incoming navigation and task ownership remain distinct. Nothing in
this view authorizes an action or changes the underlying Region graph.
"""
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
import hashlib
import json
from pathlib import Path
from regrow.prompts.prompt_material import task_present
TITLE = '登记页面组成与访问来路'
MARKER = '\n\n' + TITLE + '：\n'

def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else None

def _observed(obj, observation):
    return next((row for row in reversed(observation_history(obj)) if observation and row.get('evidence', {}).get('observation') == observation), {})

def _region(records, ref):
    return {'ref': ref, 'name': records.get(ref, {}).get('name', ref)}

def _parent_branches(records, refs):
    branches = []
    for ref in refs:
        region = records.get(ref, {})
        branches.append({**_region(records, ref), 'details_folded': True, 'completion': 'not_evaluated', 'evidence': 'historical_known_branches', 'entries': [{'control': t.get('source_control'), 'target_region': t.get('target_region'), 'attempt': t.get('attempt')} for t in region.get('transitions', [])], 'pending_tasks': [name for (name, task) in owned_tasks(region).items() if task.get('status') == 'pending']})
    return branches

def _index(records):
    index = {}
    for (rid, region) in records.items():
        for (aid, action) in owned_actions(region).items():
            after = action.get('evidence', {}).get('after_observation')
            if after and action.get('delivery') == 'executed_receipt_zero':
                index.setdefault(after, []).append((rid, aid, action))
    return index

def _entry(records, rid, aid, action):
    evidence = action.get('evidence', {})
    before = list(evidence.get('before_regions', []))
    return {'from_regions': before, 'to_regions': list(action.get('interactive_regions', [])), 'via': {'region': rid, 'attempt': aid, 'control': action.get('control')}, 'before_observation': evidence.get('before_observation'), 'after_observation': evidence.get('after_observation'), 'parent_branches': _parent_branches(records, before)}

def _origin(records, index, observation):
    (chain, visited) = ([], set())
    cursor = observation
    boundary = 'no_recorded_action_for_observation'
    while cursor:
        if cursor in visited:
            boundary = 'cyclic_action_observation'
            chain = []
            break
        visited.add(cursor)
        matches = index.get(cursor, [])
        if not matches:
            break
        if len(matches) != 1:
            boundary = 'ambiguous_action_observation'
            chain = []
            break
        chain.append(matches[0])
        cursor = matches[0][2].get('evidence', {}).get('before_observation')
    (entries, surfaces) = ([], [])
    for (rid, aid, action) in reversed(chain):
        evidence = action.get('evidence', {})
        before = list(evidence.get('before_regions', []))
        after = list(action.get('interactive_regions', []))
        if not before or not after:
            (entries, surfaces) = ([], [])
            continue
        (src, dst) = (frozenset(before), frozenset(after))
        if surfaces and surfaces[-1] != src:
            (entries, surfaces) = ([], [])
        if not surfaces:
            surfaces = [src]
        if dst == src:
            continue
        if dst in surfaces:
            at = surfaces.index(dst)
            (entries, surfaces) = (entries[:at], surfaces[:at + 1])
            continue
        entries.append(_entry(records, rid, aid, action))
        surfaces.append(dst)
    last = chain[0] if chain else None
    return {'entries': entries, 'boundary': boundary, 'last_effect': {'region': last[0], 'attempt': last[1], 'result': last[2].get('result', {})} if last else None}

def build(records, state, run=None, *, scope=None):
    """Build a fresh projection; records/state and stored identities are untouched."""
    observation = state.get('observation') or {}
    frame = observation.get('image')
    if run and frame:
        frame = str((Path(run) / frame).resolve())
    oid = observation.get('id')
    refs = list(dict.fromkeys(state.get('interactive_regions', [])))
    current_controls = set(observation.get('control_refs', []))
    (issues, nodes, parents) = ([], {}, {})
    for rid in refs:
        if rid not in records:
            issues.append({'kind': 'missing_region', 'ref': rid})
            continue
        region = records[rid]
        controls = []
        for (cid, control) in owned_controls(region).items():
            if cid not in current_controls:
                continue
            row = _observed(control, oid)
            confirmed = bool(row) and (not row.get('visual_only'))
            controls.append({'ref': cid, 'name': control.get('name', cid), 'evidence': 'current_observation' if confirmed else 'needs_recheck'})
        from regrow.records.function_scope import disclose
        from regrow.records.task_knowledge import control_knowledge
        from regrow.records.context_scope import region_information
        from regrow.records.context_scope import control_information
        nodes[rid] = {**_region(records, rid), 'controls': controls, 'children': [], 'knowledge': disclose(records, rid) if scope is None else region_information(region, scope)}
        if scope is None:
            nodes[rid]['operation_knowledge'] = control_knowledge(region, None)
        for control in controls:
            control['knowledge'] = control_knowledge(region, control['ref']) if scope is None else control_information(region, control['ref'], scope)
        parent = region.get('parent_region')
        if parent:
            own_row = _observed(region, oid)
            parent_row = _observed(records.get(parent, {}), oid)
            if parent in refs and own_row and parent_row and (not (own_row.get('visual_only') or parent_row.get('visual_only'))):
                parents[rid] = parent
            else:
                issues.append({'kind': 'unconfirmed_containment', 'ref': rid, 'parent': parent})
    cyclic = set()
    for rid in parents:
        (path, cursor) = ([], rid)
        while cursor in parents:
            if cursor in path:
                cyclic.update(path[path.index(cursor):])
                break
            path.append(cursor)
            cursor = parents[cursor]
    if cyclic:
        issues.append({'kind': 'containment_cycle', 'refs': sorted(cyclic)})
    roots = []
    for (rid, node) in nodes.items():
        parent = parents.get(rid)
        if parent in nodes and rid not in cyclic:
            nodes[parent]['children'].append(node)
        else:
            roots.append(node)
    index = _index(records)
    origin = _origin(records, index, oid)
    matches = index.get(oid, [])
    background = []
    if len(matches) == 1:
        background = [_region(records, row['region']) for row in matches[0][2].get('region_changes', []) if row.get('state') == 'visible_background_blocked' and row.get('region') not in refs]
    if not matches:
        last = state.get('last_action_result') or {}
        action = owned_actions(records.get(last.get('region'), {})).get(last.get('action'), {})
        prior = action.get('evidence', {}).get('after_observation')
        if prior:
            origin['historical_entries'] = _origin(records, index, prior)['entries']
    boundary_refs = origin['entries'][0]['from_regions'] if origin['entries'] else refs
    if not origin.get('historical_entries') and origin['boundary'] == 'no_recorded_action_for_observation':
        origin['known_entries'] = [_entry(records, rid, aid, action) for rows in index.values() for (rid, aid, action) in rows if boundary_refs and set(action.get('interactive_regions', [])) == set(boundary_refs) and action.get('evidence', {}).get('before_regions') and (set(action['evidence']['before_regions']) != set(boundary_refs))]
    active = state.get('active_task') or {}
    task = owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {})
    names = {rid: r.get('name', rid) for (rid, r) in records.items()}
    for region in records.values():
        names.update({cid: c.get('name', cid) for (cid, c) in owned_controls(region).items()})
    visual = state.get('visual_navigation') or {}
    localization_only = visual.get('observation') == oid and bool(visual.get('replay') or str(oid).startswith('navigation:'))
    from regrow.records import page_history as page_history
    from regrow.records import function_evidence as function_evidence
    incoming = {rid: [{'region': row['来源区块记录'], 'attempt': row['动作记录']} for row in function_evidence.incoming_results(records[rid], records) if row['异常'] in ('', 'none') and rid in [r['区块'] for r in row['动作后可交互区块']]] for rid in refs if rid in records}
    last_action = {'region': matches[0][0], 'attempt': matches[0][1], 'changes_surface': bool(matches[0][2].get('evidence', {}).get('before_regions')) and set(matches[0][2]['evidence']['before_regions']) != set(matches[0][2].get('interactive_regions', []))} if len(matches) == 1 and origin['boundary'] not in ('ambiguous_action_observation', 'cyclic_action_observation') else None
    view = {'current_tree': roots, 'background_regions': background, 'names': names, 'last_action': last_action, 'incoming_actions': incoming, 'goal': {**active, 'status': task.get('status', 'unknown')}, 'origin': origin, 'issues': issues, 'localization_only': localization_only, 'observation': {'id': oid, 'image': frame, 'sha256': _digest(frame)}, 'usage': 'selection', 'run_root': str(run) if run else None, 'frame_relation': 'historical_structure_needs_recheck'}
    if scope is None:
        view['history'] = page_history.build(records, state, run, extra_attempts=_source_attempts(view))
    return view

def _source_attempts(view):
    """Keep source references resolvable in the one existing event history."""
    refs = [] if view.get('last_action') else [entry['attempt'] for rows in view['incoming_actions'].values() for entry in rows]
    if not (view.get('last_action') or {}).get('changes_surface'):
        refs.extend((entry['via']['attempt'] for entry in view.get('origin', {}).get('known_entries', [])))
    if view.get('last_action'):
        refs.append(view['last_action']['attempt'])
    return refs

def _display(view, goal_in_task_context=False):
    from regrow.records import page_history as page_history
    from regrow.records.task_knowledge import summary_view
    from regrow.prompts.history_disclosure import knowledge_text
    names = view.get('names', {})
    name = lambda ref: names.get(ref, ref) or '未绑定具体控件'
    usage = view.get('usage', 'selection')
    inventory_region = view.get('inventory_region')
    relation = '动作前记录' if usage == 'before_action' else '同帧观察' if view['frame_relation'] == 'same_observation_frame' else '历史观察'
    observation = view['observation'].get('id')
    action_view = bool(view.get('action_material'))
    lines = [] if action_view else ['结构来源：' + str(observation) + '（' + relation + '）'] if observation else ['尚无已登记结构观察']
    location = view.get('environment_context_text')
    if location:
        lines = location.splitlines()
    if view['localization_only'] and (not action_view):
        lines.append('观察类型：图片定位')
    history = view.get('history') or {}
    events = history.get('events', {})
    controls = {(group['ref'], control['ref']): control['attempts'] for group in history.get('regions', []) for control in group['controls']}
    last = view.get('last_action') or {}
    last_ref = page_history.reference(history, last.get('attempt'))
    if last_ref and (not action_view):
        lines.append('上一步记录：' + last_ref)

    def tree(nodes, depth=0):
        for node in nodes:
            lines.append('  ' * depth + '- ' + node['ref'] + ' ' + node['name'])
            if node.get('knowledge') and (not inventory_region):
                from regrow.prompts.prompt_material import map_knowledge
                knowledge = map_knowledge(summary_view(node['knowledge'])) if 'self' in node['knowledge'] else node['knowledge']
                if knowledge:
                    lines.extend(('  ' * (depth + 1) + line for line in knowledge_text(knowledge).splitlines()))
            if node.get('operation_knowledge') and (not inventory_region):
                lines.extend(('  ' * (depth + 1) + line for line in knowledge_text(node['operation_knowledge']).splitlines()))
            for control in node['controls']:
                qualifier = '（历史候选）' if control.get('evidence') == 'needs_recheck' else ''
                lines.append('  ' * (depth + 1) + '- ' + control['ref'] + ' ' + control['name'] + qualifier)
                if control.get('knowledge') and (not inventory_region):
                    lines.extend(('  ' * (depth + 2) + line for line in knowledge_text(control['knowledge']).splitlines()))
            tree(node['children'], depth + 1)
    if inventory_region:
        pass
    if not action_view and not location:
        lines.append(('动作前' if usage == 'before_action' and view['frame_relation'] == 'before_action_frame' else '先前' if usage == 'discovery' else '') + '区块与控件：')
    if not action_view and not location:
        tree(view['current_tree'])
    if view['background_regions'] and not action_view and not location:
        lines.append('该次登记观察的受阻背景：' + '、'.join((n['name'] for n in view['background_regions'])))
    goal = view['goal']
    if goal_in_task_context:
        pass
    elif goal.get('name') and (not action_view):
        lines.append(f"任务引用：{name(goal.get('region'))} / {goal['name']}（{goal['status']}）")
    if view.get('history'):
        from regrow.records import page_history as page_history
        current = {'region': goal['region'], 'name': goal['name']} if goal_in_task_context else None
        history_text = page_history.render(view['history'], current)
        if history_text:
            lines.append(history_text if action_view else page_history.TITLE + '：\n' + history_text)
    if view['issues'] and not action_view and not location:
        lines.append('部分包含关系缺少本轮依据或成环；已保留区块并展开为独立节点。')
    return '\n'.join(lines)

def _frame_relation(view, frames):
    path = frames[0] if frames else None
    if path and view.get('run_root'):
        path = Path(view['run_root']) / path
    digest = _digest(path)
    matches = bool(digest and digest == view['observation']['sha256'])
    view['frame_relation'] = 'before_action_frame' if view.get('usage') == 'before_action' and matches else 'same_observation_frame' if view.get('usage') == 'selection' and len(frames) == 1 and matches else 'historical_structure_needs_recheck'
    return digest

def live(records, state, run):
    """Project the latest committed observation against the latest device frame."""
    view = build(records, state, run)
    frame = Path(run) / 'live_frame.png'
    if not frame.is_file():
        frame = view['observation']['image']
    current_digest = _frame_relation(view, [str(frame)] if frame else [])
    pending = state.get('next_action_mode') == 'discover' or (Path(run) / 'execution_pending.json').exists() or (Path(run) / 'visual_navigation_pending.json').exists()
    view['sync_status'] = 'observed' if view['frame_relation'] == 'same_observation_frame' and (not pending) else 'checking'
    if view['sync_status'] == 'observed' and view['localization_only']:
        view['sync_status'] = 'localized'
    view['latest_frame_sha256'] = current_digest
    return view

def compact_observation(card, view, region, observation, *, control=None, name=None):
    """Keep role and appearance references; current values come from the frame."""
    return {key: value for (key, value) in card.items() if key not in ('文字', '可见状态')}

def separate_map(request):
    """Extract only the controlled map slot; retain every other original field."""
    from regrow.prompts.history_disclosure import structured_text
    (text, rendered) = (structured_text(request), request.get('_page_context_text'))
    if not rendered:
        return (text, None)
    try:
        (obj, end) = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError):
        (obj, end) = (None, 0)
    if isinstance(obj, dict) and obj.get(TITLE) == rendered:
        obj[TITLE] = '见本请求共同地图正文。'
        return (json.dumps(obj, ensure_ascii=False, indent=2) + text[end:], rendered)
    if MARKER + rendered in text:
        return (text.replace(MARKER + rendered, MARKER + '见本请求共同地图正文。', 1), rendered)
    return (text, None)

def refresh(request):
    # Identity questions disclose their frozen subjects at the send boundary.
    # Keep the inherited page context for validation; do not append its raw view.
    if request.get('role') in ('control_identity_selection', 'control_identity_comparison'):
        return request
    from regrow.prompts.history_disclosure import structured_text
    request['user_prompt'] = structured_text(request)
    if request.get('stage') == 'step_correction' and request.get('original_request'):
        original = request['original_request']
        original['screenshots'] = original['image_refs'] = request.get('screenshots', [])[:len(original.get('screenshots', []))]
        refresh(original)
        (text, rendered) = separate_map(original)
        if rendered:
            (obj, end) = json.JSONDecoder().raw_decode(request['user_prompt'])
            suffix = request['user_prompt'][end:]
            (obj['原动态上下文'], obj[TITLE]) = (text, rendered)
            request['user_prompt'] = request['dynamic_prompt'] = json.dumps(obj, ensure_ascii=False, indent=2) + suffix
            (request['page_context'], request['_page_context_text']) = (original['page_context'], rendered)
        return request
    view = request.get('page_context')
    if view is None:
        return request
    frames = request.get('screenshots') or request.get('image_refs') or []
    _frame_relation(view, frames)
    source = request.get('source', {})
    goal = view.get('goal', {})
    goal_in_task = request.get('action_ready') and goal.get('name') and (source.get('task_region') == goal.get('region')) and (source.get('task_name') == goal['name']) and task_present(request, goal['region'], goal['name'])
    rendered = _display(view, goal_in_task_context=bool(goal_in_task))
    previous = request.get('_page_context_text')
    texts = {key: request.get(key, request.get('user_prompt', '')) for key in ('user_prompt', 'dynamic_prompt')}
    from regrow.records import page_history as page_history
    standalone = request.get('_page_history_text')
    for (key, text) in texts.items():
        if standalone:
            text = text.replace('\n\n' + page_history.TITLE + '：\n' + standalone, '', 1)
        try:
            (obj, end) = json.JSONDecoder().raw_decode(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            obj.pop(page_history.TITLE, None)
            page_history.link_incoming(obj, view['history'])
            if isinstance(obj.get('上步观察交接'), dict):
                from regrow.prompts import target_observation as target_observation
                obj['上步观察交接'] = target_observation.compact_handoff(obj['上步观察交接'], view['history'])
            if request.get('stage') == 'task_proposal':
                for item in obj.get('控件', []):
                    if isinstance(item, dict) and isinstance(item.get('目标观察'), dict):
                        item['目标观察'] = compact_observation(item['目标观察'], view, source.get('region'), source.get('observation'), name=item.get('name'))
            obj[TITLE] = rendered
            request[key] = json.dumps(obj, ensure_ascii=False, indent=2) + text[end:]
        else:
            if previous and MARKER + previous in text:
                text = text.replace(MARKER + previous, '', 1)
            request[key] = text + MARKER + rendered
    request['_page_context_text'] = rendered
    request.pop('page_history', None)
    request.pop('_page_history_text', None)
    if request.get('observation_handoff'):
        from regrow.prompts import target_observation as target_observation
        target_observation.render_handoff(request)
    if request.get('action_ready'):
        from regrow.prompts import target_observation as target_observation
        target_observation.render(request)
    return request

def attach(request, records, state, *, usage='selection', run=None, extra_regions=()):
    if usage == 'selection' and request.get('stage') != 'task_proposal' and (not request.get('action_ready')):
        return request
    from regrow.prompts.history_disclosure import structured_text
    request['user_prompt'] = structured_text(request)
    from regrow.records import page_history as page_history
    from regrow.traversal.work_context import attach as attach_work
    work = attach_work(request, records, state)
    goal = None
    try:
        dynamic = json.loads(request['user_prompt'])
    except (ValueError, TypeError):
        dynamic = {}
    incoming = [r['动作记录'] for r in page_history.incoming_entries(dynamic) if r.get('动作记录')]
    goal_slot = '待补参数事实的原任务证据' if '待补参数事实的原任务证据' in dynamic else '任务目标'
    if usage == 'before_action' or goal_slot == '待补参数事实的原任务证据':
        goal = dynamic.get(goal_slot)
        if goal:
            goal = dict(goal)
            if '相关动作' not in goal and '最近连续动作' not in goal and request.get('_page_history_goal'):
                goal = request['_page_history_goal']
            request['_page_history_goal'] = goal
            for key in ('相关动作', '最近连续动作', '此前动作与观察'):
                dynamic[goal_slot].pop(key, None)
            historical = [label for (key, label) in (('已有参数发现', '参数摘要'), ('原任务已有判断', '当时判断')) if goal.get(key)]
            note = '下列' + '及'.join(historical) + '中的图号属于其来源历史，不指本轮附图。' if historical else ''
            if note and (not dynamic[goal_slot].get('历史阅读', '').startswith(note)):
                dynamic[goal_slot]['历史阅读'] = note + dynamic[goal_slot].get('历史阅读', '')
            dynamic[goal_slot].pop('历史分段说明', None)
            request['user_prompt'] = request['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    source = request.get('source', {})
    from regrow.records.history_selection import for_request
    state = for_request(records, state, source, work)
    from regrow.records import context_scope as context_scope
    scope = context_scope.for_request(request, records, state, regions=extra_regions)
    view = build(records, state, run, scope=scope)
    view['history'] = page_history.build(records, state, run, goal=goal, displayed_findings=request.get('context_evidence', {}).get('known_findings', []) if task_present(request, source.get('task_region'), source.get('task_name')) else [], extra_regions=[*extra_regions, *[source.get(k) for k in ('region', 'task_region', 'return_to')]], navigation=bool(request.get('navigation_advice')), extra_attempts=[*incoming, *context_scope.source_attempts(view, scope), *[edge['attempt'] for edge in request.get('navigation_path') or [] if edge.get('attempt')]], planning_region=source.get('region') if request.get('stage') == 'task_proposal' else None)
    from regrow.records.environment_context import for_request
    view['environment_context_text'] = for_request(request, records, state)
    view['usage'] = usage
    view['action_material'] = bool(request.get('action_ready') and usage == 'selection')
    if request.get('stage') == 'task_proposal':
        view['inventory_region'] = source.get('region')
    request['page_context'] = view
    return refresh(request)

def advances_goal(request, records, state):
    """Scheduling evidence only, never an action eligibility check."""
    active = state.get('active_task') or {}
    (owner, task_name) = (active.get('region'), active.get('name'))
    source = request.get('source', {})
    task = owned_tasks(records.get(owner, {})).get(task_name, {})
    if not owner or owner != state.get('working_region') or task.get('status') != 'pending' or task.get('equivalent_to') or (state.get('next_action_mode') != 'explore') or ((state.get('observation') or {}).get('foreground', {}).get('exception', 'none') != 'none') or state.get('visual_navigation') or request.get('navigation_advice') or (source.get('region') not in state.get('interactive_regions', [])):
        return False
    if request.get('stage') != 'task_proposal' and (not (request.get('action_ready') and source.get('task_region') == owner and (source.get('task_name') == task_name))):
        return False
    origin = _origin(records, _index(records), (state.get('observation') or {}).get('id'))
    return bool(origin['entries'] and source.get('region') in origin['entries'][-1]['to_regions'] and any((owner in entry['from_regions'] for entry in origin['entries'])))
