"""Render the work selected by traversal; read navigation references without executing actions."""
from regrow.records.navigation import contextual_return
from regrow.records.navigation import navigation_description
from regrow.records.object_store import control_actions
from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.recognition import identity_templates as templates

def _assemble_local_context(root, records, state, region_ref):
    """Render names and recorded statements, never fabricate outcome summaries."""
    import json
    from pathlib import Path
    region = records[region_ref]
    obs = state['observation']
    interactive = region_ref in state['interactive_regions']
    supplied = state.get('action_history_supplied', True)
    progress = {'registered_controls': len(owned_controls(region)), 'controls_with_delivery': 0, 'controls_with_observed_effect': 0, 'controls_with_unresolved_attempts': 0, 'controls_without_record': 0 if supplied else None, 'scope': 'registered_region_controls'}
    lines = [f"本轮任务：继续探索「{region['name']}」，选择一个入口。"]
    backend = []
    statuses = {}
    for (cid, c) in owned_controls(region).items():
        attempts = list(control_actions(region, cid).values())
        delivered = any((a['delivery'] == 'executed_receipt_zero' for a in attempts))
        observed = any((a['delivery'] == 'executed_receipt_zero' and a['result'].get('status') == 'observed_effect' for a in attempts))
        unresolved = any((a['delivery'] != 'executed_receipt_zero' or a['result'].get('exception') in ('external_app', 'blocking_popup', 'system_error', 'unexpected_exit', 'unclassified', 'uncertain') or ('exception' not in a['result'] and a['result'].get('status') != 'observed_effect') for a in attempts))
        progress['controls_with_delivery'] += delivered
        progress['controls_with_observed_effect'] += observed
        progress['controls_with_unresolved_attempts'] += unresolved
        if supplied and (not attempts):
            progress['controls_without_record'] += 1
        summary = '未提供动作记录，进度未知' if not supplied else '所提供图中无动作记录' if not attempts else '有执行回执' if delivered else '执行未确认'
        statuses[cid] = {'attempts': list(control_actions(region, cid)), 'summary': summary}
        if interactive:
            from regrow.records.action_candidates import candidate
            item = candidate(region, cid, obs['id'])
            if item is not None:
                backend.append(item)
    ready = bool(obs.get('id')) and state.get('next_action_mode') == 'explore'
    if not ready:
        lines.append('当前不生成本区块点击请求；等待处理已登记的运行分支。')
    dynamic = json.dumps({'本轮任务': lines}, ensure_ascii=False, indent=2)
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import entry as prompt_entry
    stage = prompt_entry(root, 'action_selection')
    from regrow.prompts.compose import parts
    fixed = parts(root, 'action_selection') if ready else []
    from regrow.runtime.action_commands import schema as action_schema
    schema = action_schema() if ready else None
    return {'stage': stage['stage'] if ready else 'region_history', 'action_ready': ready, 'system_prompt': '\n\n'.join((p['text'].strip() for p in fixed)), 'user_prompt': dynamic, 'dynamic_prompt': dynamic, 'fixed_parts': fixed, 'response_schema': schema, 'response_schema_path': stage['schema'] if ready else None, 'image_refs': [obs['image']] if obs.get('image') else [], 'progress': progress, 'control_progress': statuses, 'backend_candidates': backend if ready else [], 'source': {'observation': obs['id'], 'region': region_ref}}

def shortest_known_path(records, state, target, *, require_control=True):
    """Fewest recorded directed tap edges; first control must be observed now."""
    from collections import deque
    starts = [r for r in state['interactive_regions'] if r in records]
    queue = deque(((r, []) for r in starts))
    seen = set(starts)
    obs = state['observation']
    while queue:
        (source, path) = queue.popleft()
        if source == target:
            return path
        region = records[source]
        for edge in region['transitions']:
            dest = edge['target_region']
            cid = edge['source_control']
            action = owned_actions(region).get(edge['attempt'], {})
            from regrow.traversal.operation_blocking import applicable
            if applicable(records, source, cid, action.get('operation'), action.get('conditions', [])):
                continue
            result = action.get('result', {})
            if contextual_return(action):
                continue
            back = action.get('operation') == 'back' and cid is None
            if dest not in records or dest in seen or (not back and cid not in owned_controls(region)) or (action.get('control') != cid) or (action.get('operation') not in ('tap', 'click', 'back')) or (len(action.get('executed_steps', [])) > 1) or (action.get('delivery') != 'executed_receipt_zero') or (result.get('exception', 'none') != 'none') or (not (result.get('exception') == 'none' or result.get('status') == 'observed_effect')):
                continue
            if require_control and (not path) and (not back) and (cid not in obs['control_refs']):
                continue
            step = {'source_region': source, 'source_control': cid, 'target_region': dest, 'attempt': edge['attempt'], 'operation': action['operation']}
            seen.add(dest)
            queue.append((dest, path + [step]))
    return None

def render_exploration_tree(records, state, region_ref, *, limit=8):
    """Task-relative view of existing evidence; no new graph or completion state.

    Adapts original region_work.environment_view's focus/collapse semantics to
    the experimental Region records. Navigation is not containment.
    """
    region = records[region_ref]
    if region_ref not in state['interactive_regions']:
        return ''
    current_controls = set(state['observation']['control_refs'])
    supplied = state.get('action_history_supplied', True)
    lines = [region['name']]
    controls = list(owned_controls(region).items())
    controls.sort(key=lambda item: (item[0] not in current_controls, bool(control_actions(region, item[0]))))
    for (cid, control) in controls[:limit]:
        attempts = list(control_actions(region, cid).items())
        if not attempts:
            status = '尚未点击。' if supplied else '未提供动作历史。'
        else:
            last = attempts[-1][1]
            result = last['result']
            operation = {'tap': '点击', 'click': '点击', 'long_press': '长按', 'swipe': '滑动'}.get(last.get('operation'), '执行动作')
            if last['delivery'] != 'executed_receipt_zero':
                status = operation + '投递未确认。'
            else:
                description = navigation_description(last) or result.get('evidence') or '未提供结果描述'
                excerpt = description.split('。')[0].split('\n')[0]
                if len(excerpt) > 80:
                    excerpt = excerpt[:80] + '…'
                status = operation + ' → ' + excerpt
                if result.get('exception') == 'uncertain' or result.get('status') == 'uncertain':
                    status += '（结果待确认）'
        lines.append(f"  ├─ {control['name']}：{status}")
        destinations = set()
        for edge in region['transitions']:
            if edge['source_control'] != cid:
                continue
            action = owned_actions(region).get(edge['attempt'], {})
            result = action.get('result', {})
            target = edge['target_region']
            if target in records and target not in destinations and (action.get('control') == cid) and (action.get('delivery') == 'executed_receipt_zero') and (result.get('exception', 'none') == 'none') and (result.get('exception') == 'none' or result.get('status') == 'observed_effect'):
                destinations.add(target)
                lines.append('  │  已观察跳转 → ' + records[target]['name'] + ('（本次返回落点，依赖进入路径）' if contextual_return(action) else '（详情折叠，不代表探索完成）'))
    if len(controls) > limit:
        lines.append(f'  └─ 另有 {len(controls) - limit} 个已登记控件折叠，不代表探索完成。')
    children = [r['name'] for r in records.values() if r.get('parent_region') == region_ref and r is not region]
    if children:
        lines.append('已登记子区块（独立探索，详情折叠）：' + '、'.join(children[:limit]))
        if len(children) > limit:
            lines.append(f'另有 {len(children) - limit} 个子区块折叠。')
    return '\n'.join(lines)

def assemble_context(root, records, state, region_ref):
    request = _assemble_action_context(root, records, state, region_ref)
    tree = render_exploration_tree(records, state, region_ref)
    request['exploration_tree'] = tree
    if tree:
        from regrow.prompts.prompt_material import assign
        assign(request, {'探索树': tree})
    return request

def _assemble_action_context(root, records, state, region_ref):
    """Keep unfinished work while navigating from the currently observed Regions."""
    request = _assemble_local_context(root, records, state, region_ref)
    if region_ref in state['interactive_regions'] or state.get('next_action_mode') != 'explore':
        return request
    import json
    from pathlib import Path
    path = shortest_known_path(records, state, region_ref)
    target = records[region_ref]
    dynamic = {'导航目标': {'region': region_ref, 'name': target['name'], 'description': target['description']}, '最近登记的前景': {'observation': state.get('observation', {}).get('id'), '前景区块': [records[r]['name'] for r in state['interactive_regions'] if r in records], 'description': state.get('observation', {}).get('foreground', {}).get('description', '')}, '已登记路线': [], '后续入口参考': []}
    for edge in path or []:
        owner = records[edge['source_region']]
        dynamic['已登记路线'].append({**edge, '来源区块': owner['name'], '入口': '系统返回' if edge['operation'] == 'back' else owned_controls(owner)[edge['source_control']]['name'], '目标区块': records[edge['target_region']]['name']})
    for edge in (path or [])[1:]:
        if edge['operation'] not in ('click', 'tap'):
            continue
        owner = records[edge['source_region']]
        control = owned_controls(owner)[edge['source_control']]
        described = next((o for o in reversed(observation_history(control)) if o.get('icon_description')), {})
        current = edge['source_region'] in state['interactive_regions'] and edge['source_control'] in state['observation'].get('control_refs', [])
        row = {'名称': control['name'], '所属区块': owner['name'], '已知去向': records[edge['target_region']]['name'], '历史外观': described.get('icon_description', ''), '来源': described.get('evidence', {}), '登记定位': {'observation': state['observation'].get('id'), '已定位': current}}
        if templates.evidence_limit(described):
            row['视觉依据限定'] = templates.evidence_limit(described)
        dynamic['后续入口参考'].append(row)
    visible = [rid for rid in state['interactive_regions'] if rid in records]
    if visible:
        owner = path[0]['source_region'] if path else visible[0]
        current = _assemble_local_context(root, records, state, owner)
        request.update({k: current[k] for k in ('stage', 'action_ready', 'fixed_parts', 'system_prompt', 'response_schema', 'response_schema_path')})
        request['backend_candidates'] = [{**c, 'region_ref': rid} for rid in visible for c in _assemble_local_context(root, records, state, rid)['backend_candidates']]
        request['source']['region'] = owner
        request['allow_back'] = True
        request['region_image'] = templates.image(records[owner])
        request['region_image_assessment'] = templates.assessment(templates.latest(records[owner]) or {})
        request['region_target'] = records[owner]['name']
        request['allow_scroll'] = True
        request['allow_input'] = True
        request['source']['return_to'] = region_ref
        request['navigation_advice'] = True
        from regrow.prompts.compose import supplement
        request['fixed_parts'].append(supplement(root, 'navigation'))
        request['system_prompt'] = '\n\n'.join((p['text'].strip() for p in request['fixed_parts']))
    request['navigation_path'] = path
    request['source']['working_region'] = region_ref
    request['user_prompt'] = request['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    from regrow.records import page_history as page_history
    return page_history.attach(request, records, state)
from regrow.records.region_evidence import region_records
from regrow.records.region_evidence import graph_state
