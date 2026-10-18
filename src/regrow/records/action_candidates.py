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
    return {'id': cid, 'name': control['name'], 'region_ref': region['id'], 'image': appearance.get('image'), 'source_image': appearance.get('source_image'), **templates.assessment(appearance), 'icon_description': row.get('icon_description', ''), 'region_image': templates.image(region), **{key: appearance[key] for key in ('bbox',) if key in appearance}}

def use_recorded_icon(item, control):
    """Reuse an admitted icon as appearance evidence only."""
    row = templates.latest(control) or {}
    if not templates.usable(row, 'icon_image'):
        return
    (icon, source) = (row['icon_image'], row.get('source_image'))
    if not source or not Path(source).is_file() or (not Path(icon).is_file()):
        return
    from regrow.recognition import matching as image_match
    original = image_match.locate(icon, source)
    (box, owner) = (original.get('box'), row.get('bbox'))
    if not original.get('accepted') or not owner or (not box):
        return
    if not (owner['left'] <= box[0] < box[2] <= owner['right'] and owner['top'] <= box[1] < box[3] <= owner['bottom']):
        return
    item.update(image=icon, bbox=dict(zip(('left', 'top', 'right', 'bottom'), box)), identity_source='admitted recorded icon located in its original source image')

def attach_related(request, records, state):
    """Complete foreground controls; recall older triggers only when relevant."""
    if not request.get('action_ready'):
        return request
    active = set(state.get('interactive_regions', []))
    existing = {(c.get('region_ref', request['source']['region']), c['id']) for c in request.get('backend_candidates', [])}
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
            use_recorded_icon(item, owned_controls(region)[cid])
            item.update(candidate_scope='foreground_entry_trigger', foreground_region=rid, candidate_reason='曾打开当前前景的外层控件；按本图判断是否仍可操作及本次作用，不代表所属后台整体可交互')
            request.setdefault('backend_candidates', []).append(item)
            existing.add((owner, cid))
    return request
