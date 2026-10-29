from regrow.records.object_store import incoming
from regrow.records.object_store import region_work
'Current foreground identities and directly relevant historical triggers.'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from pathlib import Path
from regrow.recognition import identity_templates as templates

def candidate(region, cid, observation):
    control = owned_controls(region)[cid]
    rows = observation_history(control)
    current = [row for row in rows if row.get('evidence', {}).get('observation') == observation]
    appearance = templates.latest(control) or {}
    if not current and (not appearance):
        return None
    row = (current or rows)[-1]
    return {'id': cid, 'name': control['name'], 'region_ref': region['id'], 'image': appearance.get('image'), 'appearances': templates.variants(control), 'source_image': appearance.get('source_image'), **templates.assessment(appearance), 'icon_description': control.get('description') or row.get('description') or row.get('icon_description', ''), 'region_image': templates.image(region), **{key: appearance[key] for key in ('bbox',) if key in appearance}}

def attach_related(request, records, state):
    """Complete foreground controls; recall older triggers only when relevant."""
    if not request.get('action_ready'):
        return request
    active = set(state.get('interactive_regions', []))
    existing = {(c.get('region_ref', request['source']['region']), c['id']) for c in request.get('backend_candidates', [])}
    source = request.get('source', {})
    owner, cid = source.get('completion_region') or source.get('task_region'), source.get('task_control')
    if owner in records and cid in owned_controls(records[owner]) and (owner, cid) not in existing:
        item = candidate(records[owner], cid, (state.get('observation') or {}).get('id'))
        if item is not None:
            item.update(candidate_scope='task_target_history',
                        candidate_reason='原任务目标的历史身份；按当前截图判断是否可操作，必要时先准备，不表示所属区块当前处于前景。')
            request.setdefault('backend_candidates', []).append(item)
            existing.add((owner, cid))
    for rid in state.get('interactive_regions', []):
        region = records.get(rid, {})
        if region_work(region).get('out_of_scope_reason'):
            continue
        for cid in owned_controls(region):
            if (rid, cid) in existing:
                continue
            item = candidate(region, cid, (state.get('observation') or {}).get('id'))
            if item is not None:
                request.setdefault('backend_candidates', []).append(item)
                existing.add((rid, cid))
    # A local inspection does not re-observe the rest of the last action surface.
    # Offer that recorded surface as history, never promote it to current foreground.
    observation = state.get('observation') or {}
    last = state.get('last_action_result') or {}
    action = owned_actions(records.get(last.get('region'), {})).get(last.get('action'), {})
    surface = action.get('interactive_regions', [])
    if (observation.get('scope') == 'local' and active.intersection(surface)
            and action.get('delivery') == 'executed_receipt_zero'):
        for rid in surface:
            region = records.get(rid, {})
            if rid in active or region_work(region).get('out_of_scope_reason'):
                continue
            for cid in owned_controls(region):
                if (rid, cid) in existing:
                    continue
                item = candidate(region, cid, observation.get('id'))
                if item is not None:
                    item.update(candidate_scope='last_action_surface',
                                candidate_reason='最近实际动作更新曾确认与本次局部区块同处前景；'
                                '本轮局部观察未重新核对，按当前图判断身份、遮挡及是否可操作。',
                                candidate_observation=action.get('evidence', {}).get('after_observation'))
                    request.setdefault('backend_candidates', []).append(item)
                    existing.add((rid, cid))
    from regrow.records.context_scope import select
    from regrow.records.context_scope import preparation_entries
    scope = select(records, state, work=request.get('work_context'), source=request.get('source'))
    needed = {(rid, cid) for (rid, ids) in scope['controls'].items() for cid in ids}
    needed.update(((rid, cid) for (rid, cid, _) in preparation_entries(records, state, request.get('work_context'))))
    needed.update(((edge.get('source_region'), edge.get('source_control')) for edge in request.get('navigation_path') or []))
    visible = set((state.get('observation') or {}).get('control_refs', []))
    for rid in state.get('interactive_regions', []):
        for edge in incoming(records.get(rid, {}), records):
            (owner, cid) = (edge.get('source_region'), edge.get('source_control'))
            region = records.get(owner, {})
            if owner in active or (owner, cid) in existing or region_work(region).get('out_of_scope_reason'):
                continue
            if (owner, cid) not in needed and cid not in visible:
                continue
            if cid not in owned_controls(region):
                continue
            action = owned_actions(region).get(edge.get('attempt'), {})
            if action.get('delivery') != 'executed_receipt_zero' or action.get('control') != cid:
                continue
            item = candidate(region, cid, (state.get('observation') or {}).get('id'))
            if item is None:
                continue
            item.update(candidate_scope='foreground_entry_trigger', foreground_region=rid, candidate_reason='曾打开当前前景的外层控件；按本图判断是否仍可操作及本次作用，不代表所属后台整体可交互')
            request.setdefault('backend_candidates', []).append(item)
            existing.add((owner, cid))
    return request
