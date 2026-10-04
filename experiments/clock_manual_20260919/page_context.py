"""Read-only page composition and visit ancestry derived from recorded evidence.

Composition, incoming navigation and task ownership remain distinct. Nothing in
this view authorizes an action or changes the underlying Region graph.
"""
import hashlib
import json
from pathlib import Path


TITLE = '登记页面组成与访问来路'
MARKER = '\n\n' + TITLE + '：\n'


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else None


def _observed(obj, observation):
    return next((row for row in reversed(obj.get('observations', []))
                 if observation and row.get('evidence', {}).get('observation') == observation), {})


def _region(records, ref):
    return {'ref': ref, 'name': records.get(ref, {}).get('name', ref)}


def _parent_branches(records, refs):
    branches = []
    for ref in refs:
        region = records.get(ref, {})
        branches.append({**_region(records, ref), 'details_folded': True,
            'completion': 'not_evaluated', 'evidence': 'historical_known_branches',
            'entries': [{'control': t.get('source_control'), 'target_region': t.get('target_region'),
                         'attempt': t.get('attempt')} for t in region.get('transitions', [])],
            'pending_tasks': [name for name, task in region.get('tasks', {}).items()
                              if task.get('status') == 'pending']})
    return branches


def _index(records):
    index = {}
    for rid, region in records.items():
        for aid, action in region.get('actions', {}).items():
            after = action.get('evidence', {}).get('after_observation')
            if after and action.get('delivery') == 'executed_receipt_zero':
                index.setdefault(after, []).append((rid, aid, action))
    return index


def _entry(records, rid, aid, action):
    evidence = action.get('evidence', {})
    before = list(evidence.get('before_regions', []))
    return {'from_regions': before, 'to_regions': list(action.get('interactive_regions', [])),
            'via': {'region': rid, 'attempt': aid, 'control': action.get('control')},
            'before_observation': evidence.get('before_observation'),
            'after_observation': evidence.get('after_observation'),
            'parent_branches': _parent_branches(records, before)}


def _origin(records, index, observation):
    chain, visited = [], set()
    cursor = observation
    boundary = 'no_recorded_action_for_observation'
    while cursor:
        if cursor in visited:
            boundary = 'cyclic_action_observation'
            # An inconsistent chain is unsuitable for ancestor inference.
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
    entries, surfaces = [], []
    for rid, aid, action in reversed(chain):
        evidence = action.get('evidence', {})
        before = list(evidence.get('before_regions', []))
        after = list(action.get('interactive_regions', []))
        if not before or not after:
            entries, surfaces = [], []
            continue
        src, dst = frozenset(before), frozenset(after)
        if surfaces and surfaces[-1] != src:
            entries, surfaces = [], []
        if not surfaces:
            surfaces = [src]
        if dst == src:
            continue
        if dst in surfaces:
            # Collapse the displayed visit path only; effects stay in the ledger.
            at = surfaces.index(dst)
            entries, surfaces = entries[:at], surfaces[:at + 1]
            continue
        entries.append(_entry(records, rid, aid, action))
        surfaces.append(dst)
    last = chain[0] if chain else None
    return {'entries': entries, 'boundary': boundary,
            'last_effect': ({'region': last[0], 'attempt': last[1],
                             'result': last[2].get('result', {})} if last else None)}


def build(records, state, run=None):
    """Build a fresh projection; records/state and stored identities are untouched."""
    observation = state.get('observation') or {}
    frame = observation.get('image')
    if run and frame:
        frame = str((Path(run) / frame).resolve())
    oid = observation.get('id')
    refs = list(dict.fromkeys(state.get('interactive_regions', [])))
    current_controls = set(observation.get('control_refs', []))
    issues, nodes, parents = [], {}, {}
    for rid in refs:
        if rid not in records:
            issues.append({'kind': 'missing_region', 'ref': rid})
            continue
        region = records[rid]
        controls = []
        for cid, control in region.get('controls', {}).items():
            if cid not in current_controls:
                continue
            row = _observed(control, oid)
            confirmed = bool(row) and not row.get('visual_only')
            controls.append({'ref': cid, 'name': control.get('name', cid),
                             'state': row.get('state', '') if confirmed else '',
                             'evidence': 'current_observation' if confirmed else 'needs_recheck'})
        nodes[rid] = {**_region(records, rid), 'controls': controls, 'children': []}
        parent = region.get('parent_region')
        if parent:
            own_row = _observed(region, oid)
            parent_row = _observed(records.get(parent, {}), oid)
            if parent in refs and own_row and parent_row and not (own_row.get('visual_only') or parent_row.get('visual_only')):
                parents[rid] = parent
            else:
                issues.append({'kind': 'unconfirmed_containment', 'ref': rid, 'parent': parent})
    cyclic = set()
    for rid in parents:
        path, cursor = [], rid
        while cursor in parents:
            if cursor in path:
                cyclic.update(path[path.index(cursor):])
                break
            path.append(cursor)
            cursor = parents[cursor]
    if cyclic:
        issues.append({'kind': 'containment_cycle', 'refs': sorted(cyclic)})
    roots = []
    for rid, node in nodes.items():
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
        background = [_region(records, row['region']) for row in matches[0][2].get('region_changes', [])
                      if row.get('state') == 'visible_background_blocked' and row.get('region') not in refs]
    if not matches:
        last = state.get('last_action_result') or {}
        action = records.get(last.get('region'), {}).get('actions', {}).get(last.get('action'), {})
        prior = action.get('evidence', {}).get('after_observation')
        if prior:
            origin['historical_entries'] = _origin(records, index, prior)['entries']
    # After reobservation, later same-page actions must not erase known entries.
    # These are independent historical alternatives, never a reconstructed visit chain.
    boundary_refs = origin['entries'][0]['from_regions'] if origin['entries'] else refs
    if not origin.get('historical_entries') and origin['boundary'] == 'no_recorded_action_for_observation':
        origin['known_entries'] = [_entry(records, rid, aid, action)
            for rows in index.values() for rid, aid, action in rows
            if boundary_refs and set(action.get('interactive_regions', [])) == set(boundary_refs)
            and action.get('evidence', {}).get('before_regions')
            and set(action['evidence']['before_regions']) != set(boundary_refs)]
    active = state.get('active_task') or {}
    task = records.get(active.get('region'), {}).get('tasks', {}).get(active.get('name'), {})
    names = {rid: r.get('name', rid) for rid, r in records.items()}
    for region in records.values():
        names.update({cid: c.get('name', cid) for cid, c in region.get('controls', {}).items()})
    visual = state.get('visual_navigation') or {}
    localization_only = (visual.get('observation') == oid
                         and bool(visual.get('replay') or str(oid).startswith('navigation:')))
    import page_history
    return {'history': page_history.build(records, state, run), 'current_tree': roots, 'background_regions': background, 'names': names,
            'goal': {**active, 'status': task.get('status', 'unknown')}, 'origin': origin,
            'issues': issues, 'localization_only': localization_only,
            'observation': {'id': oid, 'image': frame, 'sha256': _digest(frame)},
            'usage': 'selection', 'run_root': str(run) if run else None,
            'frame_relation': 'historical_structure_needs_recheck'}


def _display(view):
    # IDs live in request metadata. The prompt presents names and evidence roles.
    names = view.get('names', {})
    name = lambda ref: names.get(ref, ref) or '未绑定具体控件'
    usage = view.get('usage', 'selection')
    evidence = ('发现前的历史地图；按新截图重新核对区块、控件和父子关系，不证明当前可见。' if usage == 'discovery'
        else '动作前地图；动作后结果尚未登记，须依据动作后图核对变化，不把这棵树当作动作后状态。' if usage == 'before_action'
        else '与本次截图一致的已登记观察。' if view['frame_relation'] == 'same_observation_frame'
        else '历史观察；当前截图已更换或来源未核实，须逐项核对，不能据此断言可见或可点击。')
    lines = ['这是观察记录派生的结构与来路，不是新的视觉判断或固定返回路线。', '结构来源：' + evidence]
    if view['localization_only']:
        lines.append('本轮仅视觉定位，未登记新的动作效果。')
    def tree(nodes, depth=0):
        for node in nodes:
            lines.append('  ' * depth + '- ' + node['name'])
            for control in node['controls']:
                state = control['state'] if control['evidence'] == 'current_observation' else '状态待核对'
                lines.append('  ' * (depth + 1) + '- ' + control['name'] + (f'（{state}）' if state else ''))
            tree(node['children'], depth + 1)
    lines.append(('动作前' if usage == 'before_action' else '先前' if usage == 'discovery' else '') + '登记前景区块与控件：')
    tree(view['current_tree'])
    if view['background_regions']:
        lines.append('该次登记观察的受阻背景：' + '、'.join(n['name'] for n in view['background_regions']))
    goal = view['goal']
    if goal.get('name'):
        lines.append(f"保留目标：{name(goal.get('region'))} / {goal['name']}（{goal['status']}）")
    origin = view['origin']
    entries = origin['entries']
    confirmed_entries = bool(entries)
    if not entries and origin.get('historical_entries'):
        lines.append('以下仅为先前来路，尚未确认连接到本轮观察：')
        entries = origin['historical_entries']
    if entries:
        lines.append('历史访问路径（不是页面包含层级；更早经过的页面不等于父页面）：')
    for index, entry in enumerate(entries):
        via = entry['via']
        prefix = '当前区块' if usage == 'selection' else '动作前区块' if usage == 'before_action' else '先前区块'
        label = prefix + '的直接进入来源：' if confirmed_entries and index == len(entries) - 1 else '更早经过：'
        lines.append(label + '、'.join(map(name, entry['from_regions'])) + ' → ' +
                     name(via.get('control')) + ' → ' + '、'.join(map(name, entry['to_regions'])))
        for branch in entry['parent_branches']:
            destinations = [name(v.get('control')) + ' → ' + name(v.get('target_region')) for v in branch['entries']]
            lines.append('  来路页面已知分支 ' + branch['name'] + '（详情折叠，不代表完成或当前可操作）' +
                         ('；入口：' + '；'.join(dict.fromkeys(destinations)) if destinations else '') +
                         ('；未完成：' + '；'.join(branch['pending_tasks']) if branch['pending_tasks'] else ''))
    for entry in origin.get('known_entries', []):
        lines.append('已登记历史入口（未证明是本次来路）：' + '、'.join(map(name, entry['from_regions'])) +
                     ' → ' + name(entry['via'].get('control')) + ' → ' + '、'.join(map(name, entry['to_regions'])))
        for branch in entry['parent_branches']:
            lines.append('  来源区块 ' + branch['name'] + '（历史分支折叠，不代表完成或当前可操作）' +
                         ('；未完成：' + '；'.join(branch['pending_tasks']) if branch['pending_tasks'] else ''))
    lines.append('来路追溯边界：' + {'no_recorded_action_for_observation': '更早观察无可追溯动作',
        'ambiguous_action_observation': '动作与观察对应有歧义，未选择父路径',
        'cyclic_action_observation': '观察链成环，未选择父路径'}.get(origin['boundary'], origin['boundary']))
    if view.get('history'):
        import page_history
        lines.append(page_history.TITLE + '：\n' + page_history.render(view['history']))
    if view['issues']:
        lines.append('部分包含关系缺少本轮依据或成环；已保留区块并展开为独立节点。')
    return '\n'.join(lines)


def _frame_relation(view, frames):
    path = frames[0] if frames else None
    if path and view.get('run_root'):
        path = Path(view['run_root']) / path
    digest = _digest(path)
    matches = bool(digest and digest == view['observation']['sha256'])
    view['frame_relation'] = ('before_action_frame' if view.get('usage') == 'before_action' and matches
        else 'same_observation_frame' if view.get('usage') == 'selection' and len(frames) == 1 and matches
        else 'historical_structure_needs_recheck')
    return digest


def live(records, state, run):
    """Project the latest committed observation against the latest device frame."""
    view = build(records, state, run)
    frame = Path(run) / 'live_frame.png'
    if not frame.is_file():
        frame = view['observation']['image']
    current_digest = _frame_relation(view, [str(frame)] if frame else [])
    pending = (state.get('next_action_mode') == 'discover' or (Path(run) / 'execution_pending.json').exists()
               or (Path(run) / 'visual_navigation_pending.json').exists())
    view['sync_status'] = 'observed' if view['frame_relation'] == 'same_observation_frame' and not pending else 'checking'
    if view['sync_status'] == 'observed' and view['localization_only']:
        view['sync_status'] = 'localized'
    view['latest_frame_sha256'] = current_digest
    return view


def refresh(request):
    view = request.get('page_context')
    if view is None:
        return request
    frames = request.get('screenshots') or request.get('image_refs') or []
    _frame_relation(view, frames)
    rendered = _display(view)
    previous = request.get('_page_context_text')
    texts = {key: request.get(key, request.get('user_prompt', '')) for key in ('user_prompt', 'dynamic_prompt')}
    import page_history
    standalone = request.get('_page_history_text')
    for key, text in texts.items():
        if standalone:
            text = text.replace('\n\n' + page_history.TITLE + '：\n' + standalone, '', 1)
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            obj.pop(page_history.TITLE, None)
            page_history.link_incoming(obj, view['history'])
            obj[TITLE] = rendered
            request[key] = json.dumps(obj, ensure_ascii=False, indent=2)
        else:
            if previous and MARKER + previous in text:
                text = text.replace(MARKER + previous, '', 1)
            request[key] = text + MARKER + rendered
    request['_page_context_text'] = rendered
    request.pop('page_history', None)
    request.pop('_page_history_text', None)
    return request


def attach(request, records, state, *, usage='selection', run=None, extra_regions=()):
    if usage == 'selection' and request.get('stage') != 'task_proposal' and not request.get('action_ready'):
        return request
    import page_history
    goal = None
    try:dynamic = json.loads(request['user_prompt'])
    except (ValueError, TypeError):dynamic = {}
    incoming = [r['动作记录'] for r in page_history.incoming_entries(dynamic) if r.get('动作记录')]
    if usage == 'before_action':
        goal = dynamic.get('任务目标')
        if goal:
            # Move only event bodies; keep parameter baselines and historical
            # judgments in their established task-goal contract.
            goal = dict(goal)
            if '最近连续动作' not in goal and request.get('_page_history_goal'):
                goal = request['_page_history_goal']
            request['_page_history_goal'] = goal
            for key in ('最近连续动作', '此前动作与观察'):
                dynamic['任务目标'].pop(key, None)
            note = '下列参数摘要及当时判断中的图号属于其来源历史，不指本轮附图。'
            if not dynamic['任务目标'].get('历史阅读','').startswith(note):
                dynamic['任务目标']['历史阅读'] = note + dynamic['任务目标'].get('历史阅读','')
            dynamic['任务目标']['历史分段说明'] = '事件正文及参数差异观察见共同地图的区块控件历史；按登记动作顺序阅读，参数基准仍为本任务已有参数发现。'
            request['user_prompt'] = request['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    view = build(records, state, run)
    source = request.get('source', {})
    view['history'] = page_history.build(records, state, run, goal=goal,
        extra_regions=[*extra_regions, *[source.get(k) for k in ('region','task_region','return_to')]],
        navigation=bool(request.get('navigation_advice')), extra_attempts=incoming)
    view['usage'] = usage
    request['page_context'] = view
    return refresh(request)


def advances_goal(request, records, state):
    """Scheduling evidence only, never an action eligibility check."""
    active = state.get('active_task') or {}
    owner, task_name = active.get('region'), active.get('name')
    source = request.get('source', {})
    task = records.get(owner, {}).get('tasks', {}).get(task_name, {})
    if (not owner or owner != state.get('working_region') or task.get('status') != 'pending'
            or task.get('handling') != 'explore' or state.get('next_action_mode') != 'explore'
            or (state.get('observation') or {}).get('foreground', {}).get('exception', 'none') != 'none'
            or state.get('visual_navigation') or request.get('navigation_advice')
            or source.get('region') not in state.get('interactive_regions', [])):
        return False
    if request.get('stage') != 'task_proposal' and not (request.get('action_ready')
            and source.get('task_region') == owner and source.get('task_name') == task_name):
        return False
    origin = _origin(records, _index(records), (state.get('observation') or {}).get('id'))
    return bool(origin['entries'] and source.get('region') in origin['entries'][-1]['to_regions']
                and any(owner in entry['from_regions'] for entry in origin['entries']))
