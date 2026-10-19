"""Materialize accepted object observations and preserve their frame-specific identity images."""
from regrow.records import region_evidence as _region_evidence
from regrow.records.object_store import region_work
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
from regrow.records.object_store import owned_controls
from copy import deepcopy
import os
from regrow.recognition import identity_templates as templates

def unique(items, name, get_name):
    matches = [item for item in items if get_name(item) == name]
    if len(matches) != 1:
        raise ValueError(f'unknown or ambiguous name: {name}')
    return matches[0]

def label(control):
    return control['name']

def materialize_regions(records, reply, call_ref, observation, region_names=None, *, frame=None):
    from regrow.records import registration_diagnostics as _registration_diagnostics
    from regrow.recognition import region_candidate_names as _region_candidate_names
    from regrow.records import control_records as _control_records
    _registration_diagnostics.check('update', {'region_names': region_names or {}}, reply, records, frame=frame)
    next_r = max([int(k[1:]) for k in records] + [0]) + 1
    next_c = max([int(k[1:]) for r in records.values() for k in owned_controls(r)] + [0]) + 1
    region_refs = []
    for (i, p) in enumerate(reply['regions']):
        if p.get('parent_index') is not None and (not (0 <= p['parent_index'] < len(reply['regions']) and p['parent_index'] != i)):
            raise ValueError('invalid parent Region index')
        if p['ref']:
            r = records[p['_matched_id']] if p.get('_matched_id') else records[_region_candidate_names.resolve(records, p['ref'], region_names)]
            ref = r['id']
        else:
            ref = records.allocate('region') if isinstance(records, object_store.Records) else f'r{next_r:04d}'
            next_r += 1
            r = _region_evidence.new_region(ref, p['name'], p['description'])
            records[ref] = r
            r = records[ref]
        if 'name' in p and p['name'] not in (region_names or {}):
            r['name'] = p['name']
        if 'description' in p:
            r['description'] = p['description']
        if 'out_of_scope_reason' in p:
            region_work(r)['out_of_scope_reason'] = p['out_of_scope_reason'].strip()
        if p.get('task_review_reason', '').strip() and region_work(r).get('task_inventory'):
            region_work(r)['task_inventory']['review'] = {'reason': p['task_review_reason'], 'source_call': call_ref}
        observation_history(r).append(_region_evidence.region_observation(p, {'source_call': call_ref, 'source_field': f'/regions/{i}', 'observation': observation}))
        region_refs.append(ref)
    if len(set(region_refs)) != len(region_refs):
        raise ValueError('same Region reported twice')
    for (i, p) in enumerate(reply['regions']):
        if 'parent_index' in p:
            records[region_refs[i]]['parent_region'] = region_refs[p['parent_index']] if p['parent_index'] is not None else None
    _control_records.validate(reply['controls'])
    for (i, p) in enumerate(reply['controls']):
        if not 0 <= p['region_index'] < len(region_refs):
            raise ValueError('invalid control owner index')
        r = records[region_refs[p['region_index']]]
        if p['ref']:
            ref = p['_matched_id'] if p.get('_matched_id') else p['ref'] if object_store.control_record(records, p['ref']) is not None else unique(owned_controls(r), p['ref'], lambda k: label(owned_controls(r)[k]))
        else:
            ref = records.allocate('control') if isinstance(records, object_store.Records) else f'c{next_c:04d}'
            next_c += 1
        c = owned_controls(r).setdefault(ref, {'name': _region_evidence.control_name(p), 'observations': []})
        c['name'] = _region_evidence.control_name(p)
        if 'description' in p:
            c['description'] = p['description']
        if 'list_group' in p:
            from regrow.records.control_records import set_group
            set_group(r, ref, p['list_group'])
        changed = any(k in p and c.get(k) != p[k] for k in ('knowledge','may_open_content','needs_exploration'))
        if changed and region_work(r).get('task_inventory'):
            region_work(r)['task_inventory']['review'] = {'reason':'控件用途判断更新，核对是否仍需探索','source_call':call_ref}
        observation_history(c).append(_region_evidence.control_observation(p, {'source_call': call_ref, 'source_field': f'/controls/{i}', 'observation': observation, 'region': r['id']}))
        if 'knowledge' in p:
            from regrow.records.control_knowledge import update
            update(c, p['knowledge'], {'source_call': call_ref, 'observation': observation, 'region': r['id'], 'basis': 'discovery'})
        for key in ('may_open_content','needs_exploration'):
            if key in p:
                c[key] = deepcopy(p[key])
    return region_refs

def frame_observation(record, *, kind=None, call=None, observation=None, region=None):
    """Select a model-reported object, not a knowledge/entry event sharing its time."""
    for row in reversed(observation_history(record or {})):
        evidence = row.get('evidence', {})
        field = evidence.get('source_field', '').split('/')
        if row.get('visual_only') or len(field) < 2 or field[-2] not in ('regions', 'controls') or not field[-1].isdigit():
            continue
        if kind and field[-2] != kind:
            continue
        if call is not None and evidence.get('source_call') != call:
            continue
        if region is not None and evidence.get('region') not in (None, region):
            continue
        if observation is not None and evidence.get('observation') != observation:
            continue
        return row
    return {}

def save_region_images(records, region_refs, reply, call_ref, run, image_ref, snapshot, temp, *, image_tag=None, observation=None, update_images=False, text_control=None):

    def crop(r, name, box, *, identity_field=None, observed=None, owner=None, region=False):
        if box is None:
            return None
        from PIL import Image
        source_image = run / image_ref
        with Image.open(source_image) as image:
            xy = [box[k] for k in ('left', 'top', 'right', 'bottom')]
            if identity_field:
                reason = templates.crop_rejection(box, image.size, owner)
                if not reason and templates.uniform_pixels(image.crop(xy)):
                    reason = '身份裁图完全单色，没有可区分外观；不使用该模板，不判定对象不存在'
                if reason:
                    observed.setdefault('template_rejections', {})[identity_field] = {'kind': 'crop_quality', 'reason': reason, 'source_call': call_ref, 'source_field': observed['evidence']['source_field']}
                    return None
            if not (0 <= xy[0] < xy[2] <= image.width and 0 <= xy[1] < xy[3] <= image.height):
                raise ValueError('crop box outside source frame')
            pixels = image.crop(xy)
            if identity_field == 'image' and not region:
                from regrow.records.control_images import existing
                previous = existing(owned_controls(r)[name], pixels, snapshot)
                if previous:
                    return None  # Reuse the original admitted image event, not a new crop/source pairing.
            relative = f"regions/{r['id']}/images/{image_tag or call_ref}/{name}.png"
            dest = temp / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            pixels.save(dest)
        return {'image': relative, 'source_image': os.path.relpath(source_image, snapshot), 'source_call': call_ref}
    for ref in region_refs:
        r = records[ref]
        v = frame_observation(r, kind='regions', call=call_ref, observation=observation)
        if not v:
            raise ValueError('区块缺少本轮对象观察来源：' + ref)
        proposal = reply['regions'][int(v['evidence']['source_field'].split('/')[-1])]
        v['source_image'] = os.path.relpath(run / image_ref, snapshot)
        visual = crop(r, 'region', templates.admitted_box(proposal), identity_field='image', observed=v, region=True)
        if visual:
            v.update(image=visual['image'], source_image=visual['source_image'])
        for (cid, c) in owned_controls(r).items():
            v = frame_observation(c, kind='controls', call=call_ref, observation=observation, region=ref)
            if v:
                proposal = reply['controls'][int(v['evidence']['source_field'].split('/')[-1])]
                v['source_image'] = os.path.relpath(run / image_ref, snapshot)
                previous = templates.latest(c)
                if previous and (not update_images or not proposal.get('add_image') or cid == text_control):
                    continue
                owner = frame_observation(r, kind='regions', call=call_ref, observation=observation).get('bbox')
                visual = crop(r, cid, templates.admitted_box(proposal), identity_field='image', observed=v, owner=owner)
                v['image_conditions'] = list(proposal.get('image_conditions', []))
                if visual:
                    v.update(image=visual['image'], source_image=visual['source_image'])
                from regrow.records.control_images import images
                c['image'] = images(c)
                if 'click_bbox' in proposal:
                    click = crop(r, cid + '_click', proposal['click_bbox'])
                    v.update(click_bbox=deepcopy(proposal['click_bbox']), click_image=click['image'] if click else None)
