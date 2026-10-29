from regrow.records.calls import submission as _owner_submission
from regrow.records.snapshots import load as _record_load
'Same-call foreground reports, geometric validation and frame-bound reuse.'
from regrow.records.object_store import observation_history
from pathlib import Path
import hashlib
import json

def guidance():
    return '判断当前前景及遮挡；被模态表面接管的底层内容按背景处理。当前前景包含纯展示区，不以有控件为前提。'

def extend_schema(schema):
    field = schema['properties']['foreground']
    field['properties'].pop('interactive_areas', None)
    field['required'] = [key for key in field['required'] if key != 'interactive_areas']
    return schema

def fingerprint(frame):
    return hashlib.sha256(Path(frame).read_bytes()).hexdigest()

def load(run, frame):
    path = Path(run) / 'foreground_scopes' / (fingerprint(frame) + '.json')
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    return {**value['scope'], 'source_call': value.get('source_call')} if value.get('frame_sha256') == fingerprint(frame) else None

def audit(run, job):
    q = job['request']
    fields = q.get('response_schema', {}).get('properties', {}).get('foreground', {}).get('properties', {})
    if job['stage'] not in ('discovery', 'update') or not fields:
        return None
    from regrow.recognition import history_matching as history_matching
    (q, reply) = _owner_submission(run, job['call'])
    from regrow.prompts.frame_context import primary
    frame = Path(run) / primary(q)
    if job['stage'] == 'discovery' and q.get('discovery_context'):
        from regrow.recognition.region_identity import prepare
        (q, reply, _) = prepare(run, q, reply)
    scope = {}
    from PIL import Image
    with Image.open(frame) as image:
        (width, height) = image.size
    (snapshot, records, _) = _record_load(run)
    names = q.get('region_names') or q.get('discovery_context', {}).get('region_names', {})
    excluded = set()
    for previous in reply.get('previous_regions', []):
        if previous.get('state') not in ('not_visible', 'visible_background_blocked', 'uncertain'):
            continue
        label = previous.get('name')
        rid = names.get(label)
        if rid is None:
            matches = [key for (key, r) in records.items() if r['name'] == label]
            if len(matches) == 1:
                rid = matches[0]
        if rid is not None:
            excluded.add(rid)
    identified = []
    issues = []
    for (index, region) in enumerate(reply.get('regions', [])):
        rid = region.get('_matched_id') or names.get(region.get('ref'))
        if rid in excluded or region.get('identity') == 'uncertain':
            continue
        box = region.get('bbox')
        if box:
            values = [box[k] for k in ('left', 'top', 'right', 'bottom')]
            if not (0 <= values[0] < values[2] <= width and 0 <= values[1] < values[3] <= height):
                issues.append({'source_field': f'/regions/{index}', 'field': 'image', 'reason': '区块框为空、倒置或超出当前截图；不缓存该边界或保存模板'})
            else:
                identified.append({'source_field': f'/regions/{index}', 'bbox': box})
    ranking = history_matching.scan({rid: r for (rid, r) in records.items() if rid not in excluded}, snapshot, frame)
    value = {'identified_regions': identified, 'template_rejections': issues, 'source_call': job['call'], 'frame_sha256': fingerprint(frame), 'scope': scope, 'ranking': ranking, 'basis': 'same-call semantic foreground; image matches are identity candidates only', 'limitation': 'geometry checks do not prove the model selected the correct foreground'}
    path = Path(run) / 'calls' / job['call'] / 'foreground_matching.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    return value

def remember(run, value):
    if value is None:
        return
    (_, records, state) = _record_load(run)
    path = Path(run) / 'foreground_scopes' / (value['frame_sha256'] + '.json')
    previous = json.loads(path.read_text()) if path.exists() else {}
    active = set(state.get('interactive_regions', []))
    if active and (state.get('observation') or {}).get('scope') == 'local':
        active.update(previous.get('scope', {}).get('regions', previous.get('scope', {}).get('region_bounds', {})))
    value['scope']['regions'] = sorted(active)
    value['scope']['region_bounds'] = {rid: box for (rid, box) in previous.get('scope', {}).get('region_bounds', {}).items() if rid in records and rid in active}
    for item in value.get('identified_regions', []):
        ids = [rid for (rid, r) in records.items() if any((o.get('evidence', {}).get('source_call') == value.get('source_call') and o.get('evidence', {}).get('source_field') == item['source_field'] for o in observation_history(r)))]
        if len(ids) == 1 and ids[0] in active:
            value['scope']['region_bounds'][ids[0]] = [item['bbox'][k] for k in ('left', 'top', 'right', 'bottom')]
    path = Path(run) / 'foreground_scopes' / (value['frame_sha256'] + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
