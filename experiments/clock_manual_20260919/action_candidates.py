"""Recall control identities without treating their whole owner as interactive."""
from pathlib import Path
import identity_templates as templates


def candidate(region, cid, observation):
    control = region['controls'][cid]
    rows = control.get('observations', [])
    current = [row for row in rows if row.get('evidence', {}).get('observation') == observation]
    appearance = templates.latest(control) or {}
    if not current and not appearance:
        return None
    row = (current or rows)[-1]
    return {'id': cid, 'name': control['name'], 'region_ref': region['id'],
            'image': appearance.get('image'), 'source_image': appearance.get('source_image'),
            **templates.assessment(appearance), 'icon_description': row.get('icon_description', ''),
            'region_image': templates.image(region),
            **{key: appearance[key] for key in ('bbox', 'click_bbox') if key in appearance}}


def use_recorded_icon(item, control):
    """Reuse an admitted icon while keeping its recorded button click area."""
    row = templates.latest(control) or {}
    if not templates.usable(row, 'icon_image'):
        return
    icon, source = row['icon_image'], row.get('source_image')
    if not source or not Path(source).is_file() or not Path(icon).is_file():
        return
    import image_match
    original = image_match.locate(icon, source)
    box, owner = original.get('box'), row.get('bbox')
    if not original.get('accepted') or not owner or not box:
        return
    if not (owner['left'] <= box[0] < box[2] <= owner['right']
            and owner['top'] <= box[1] < box[3] <= owner['bottom']):
        return
    item.update(image=icon, image_quality=row['icon_quality'],
                bbox=dict(zip(('left','top','right','bottom'),box)),
                click_bbox=row.get('click_bbox') or owner,
                identity_source='admitted recorded icon located in its original source image')


def attach_related(request, records, state):
    """One-hop foreground entry triggers, not every control in a background Region."""
    if not request.get('action_ready'):
        return request
    active = set(state.get('interactive_regions', []))
    existing = {(c.get('region_ref', request['source']['region']), c['id'])
                for c in request.get('backend_candidates', [])}
    extra = []
    for rid in state.get('interactive_regions', []):
        for edge in records.get(rid, {}).get('reached_by', []):
            owner, cid = edge.get('source_region'), edge.get('source_control')
            region = records.get(owner, {})
            if owner in active or (owner, cid) in existing or region.get('out_of_scope_reason'):
                continue
            if cid not in region.get('controls', {}):
                continue
            action = region.get('actions', {}).get(edge.get('attempt'), {})
            if action.get('delivery') != 'executed_receipt_zero' or action.get('control') != cid:
                continue
            item = candidate(region, cid, (state.get('observation') or {}).get('id'))
            if item is None:
                continue
            use_recorded_icon(item, region['controls'][cid])
            item.update(candidate_scope='foreground_entry_trigger', foreground_region=rid,
                        candidate_reason='曾打开当前前景的外层控件；按本图判断是否仍可操作及本次作用，不代表所属后台整体可交互')
            request.setdefault('backend_candidates', []).append(item)
            existing.add((owner, cid));extra.append(item)
    if extra:
        text = '\n\n当前前景的相关外层身份候选（保留原区块归属，不新增或迁移探索任务）：\n'
        text += '\n'.join(records[c['region_ref']]['name'] + ' / ' + c['name'] + '：' + c['candidate_reason'] for c in extra)
        text += '\n优先处理当前前景中与目标有关的工作；需要退出时可使用当前图支持的外层按钮或空白处。区分收起浮层与执行后台功能，同一控件可随展开状态承担打开或关闭作用。'
        for key in ('user_prompt', 'dynamic_prompt'):
            request[key] = request.get(key, '') + text
    return request
