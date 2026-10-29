"""Complete one batch of new object appearances before publishing an update.

The semantic reply remains immutable. Geometry comes only from the original
after-image; the derived submission records both calls and uses normal commit.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import jsonschema
from regrow.records.snapshots import read, write_json
from regrow.prompts.frame_context import primary, label, select

GEOMETRY = {'bbox', 'icon_bbox', 'click_bbox', 'click_area', 'x', 'y', 'end_x', 'end_y',
            'left', 'top', 'right', 'bottom'}
BOX = {'type': 'object', 'properties': {k: {'type': 'integer', 'minimum': 0}
       for k in ('left', 'top', 'right', 'bottom')},
       'required': ['left', 'top', 'right', 'bottom'], 'additionalProperties': False}


def semantic_schema(schema):
    from regrow.runtime.model_transport import expand_schema
    def strip(value):
        if isinstance(value, list):
            return [strip(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {k: strip(v) for k, v in value.items()}
        if 'properties' in result:
            result['properties'] = {k: v for k, v in result['properties'].items() if k not in GEOMETRY}
        if 'required' in result:
            result['required'] = [k for k in result['required'] if k not in GEOMETRY]
        return result
    return strip(expand_schema(schema))


def missing(candidate):
    rows = []
    for kind in ('regions', 'controls'):
        for i, row in enumerate(candidate.get(kind, [])):
            known = row.get('ref') or (kind == 'controls' and 'index' in row)
            if (known and not (kind == 'controls' and row.get('add_image'))) or row.get('bbox'):
                continue
            rows.append({'path': f'/{kind}/{i}', **deepcopy(row)})
    return rows


def request(root, original, candidate, rows, *, grounding=None):
    text = (Path(root) / 'regrow/prompts/任务/对象识别资料.prompt').read_text()
    rows = deepcopy(rows)
    grounding = grounding or {}
    for row in rows:
        if row['path'] in grounding:
            info = grounding[row['path']]
            row['名称'] = info['name']
            row['当前外观'] = info['state']
    paths = [row['path'] for row in rows]
    item = {'type': 'object', 'properties': {
        'path': {'type': 'string', 'enum': paths}, 'bbox': {'anyOf':[deepcopy(BOX), {'type':'null'}]}, 'reason': {'type':'string'}},
        'required': ['path', 'bbox'], 'additionalProperties': False}
    q = {'role': 'object_registration', 'stage': 'object_registration',
         'system_prompt': text, 'fixed_parts': [{'path': '任务/对象识别资料.prompt', 'text': text}],
         'user_prompt': json.dumps({'待补齐对象': rows, '所属区块': candidate.get('regions', [])}, ensure_ascii=False),
         'screenshots': [primary(original)], 'source': deepcopy(original.get('source', {})),
         'response_schema': {'type': 'object', 'properties': {'objects': {
             'type': 'array', 'items': item, 'minItems': len(rows), 'maxItems': len(rows)}},
             'required': ['objects'], 'additionalProperties': False},
         'registration_paths': paths}
    if grounding:
        q['response_schema']['properties']['objects']['items']['required'].append('reason')
        material = json.loads(q['user_prompt'])
        material['定位要求'] = '给定旧控件已完成历史身份与状态比较。现在逐一确认当前图中的具体对象，并框出符合其名称和当前外观的控件；reason简述框内对象的辨认依据，不把旁边相似对象作为它。无法确认时bbox填null。'
        q['user_prompt'] = json.dumps(material, ensure_ascii=False)
        q['appearance_grounding'] = deepcopy(grounding)
    label(q, primary(original), '原动作后图；仅补齐本批对象外观，不判断动作效果')
    return q


def validate(q, reply, run):
    from PIL import Image
    jsonschema.validate(reply, q['response_schema'])
    rows = reply['objects']
    if sorted(v['path'] for v in rows) != sorted(q['registration_paths']):
        raise ValueError('每个待补齐对象必须且只能返回一次')
    with Image.open(Path(run) / primary(q)) as im:
        width, height = im.size
    for row in rows:
        b = row['bbox']
        if b is None:
            raise ValueError('对象尚不能定位：' + row.get('reason', row['path']))
        if not (0 <= b['left'] < b['right'] <= width and 0 <= b['top'] < b['bottom'] <= height):
            raise ValueError('识别范围须位于本张图片内且具有正面积')
    return reply


def reused_boxes(saved, current):
    """Reuse a complete verified batch only with unique unchanged object bindings."""
    old = saved.get('request', {})
    if not old or primary(old) != primary(current):
        return None
    def bindings(q):
        result = {}
        for path in q.get('registration_paths', []):
            info = q.get('appearance_grounding', {}).get(path)
            if not info or not info.get('control'):
                return None
            identity = (info['control'], info.get('state'), info.get('comparison_call'))
            if identity in result:
                return None
            result[identity] = path
        return result or None
    try:
        old_keys, new_keys = bindings(old), bindings(current)
    except (ValueError, TypeError):
        return None
    if not old_keys or not new_keys or set(old_keys) != set(new_keys):
        return None
    boxes = {r['path']: r for r in saved['candidate']['objects']}
    if set(boxes) != set(old_keys.values()) or any(not r.get('bbox') for r in boxes.values()):
        return None
    return [{**deepcopy(boxes[old_keys[key]]), 'path': path} for key,path in new_keys.items()]


def complete(runner, job):
    """Resume a normal child repair; no GUI capture or partial graph publication."""
    if job['stage'] != 'update':
        return
    candidate = job.get('candidate') or {}
    jsonschema.validate(candidate, job['request']['response_schema'])
    # A derived submission is already the active request. Do not rebuild it
    # from a historical semantic request or revive an old request cache.
    if job['request'].get('registration_sources') and not missing(candidate):
        job.pop('registration_submission', None)
        return
    digest = hashlib.sha256(json.dumps([candidate, job['request'].get('control_indexes')],
                                      sort_keys=True).encode()).hexdigest()[:16]
    enriched = deepcopy(candidate)
    labels = []
    confirmed = set()
    grounding = {}
    from regrow.recognition import appearance_comparison
    from regrow.traversal.step_repair import pending
    for number, (source, batch) in enumerate(appearance_comparison.batches(runner.run, job['request'], candidate)):
        comparison = appearance_comparison.request(runner.root, runner.run, job['request'], source, batch)
        key = appearance_comparison.comparison_key(comparison)
        pointer = str(Path(job['path']).parent / ('appearance-' + key + '.json'))
        cache = job.setdefault('appearance_comparisons', {})
        saved = cache.get(pointer)
        if saved is None:
            # Existing job results remain usable after upgrading the cache key.
            saved = next((value for value in cache.values()
                          if value.get('request', {}).get('appearance_rows')
                          and appearance_comparison.comparison_key(value['request']) == key), None)
        if saved is None:
            child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot,
                                 runner.available, pointer_name=pointer)
            q = None if pending(runner.run, pointer) else comparison
            saved = child.perform('appearance_comparison', q)
            cache[pointer] = saved
            runner.save(job)
        replies = appearance_comparison.replies_by_control(saved)
        for old in batch:
            reply = replies[old['control']]
            if reply['relation'] in ('different_control', 'uncertain'):
                raise ValueError(old['name'] + '的外观比较未确认本次复用：' + reply['reason'] + '；请在原动作更新中修正该控件引用或追加提议')
            current = enriched['controls'][old['position']]
            current['add_image'] = reply['relation'] == 'new_appearance'
            current['image_conditions'] = [reply['current_state']] if current['add_image'] else []
            labels.append({'control': old['control'], 'image': old['image'],
                           'state': reply['historical_state'], 'source_call': saved['call'],
                           'reason': reply['reason']})
            confirmed.add(old['control'])
            if current['add_image']:
                grounding['/controls/' + str(old['position'])] = {
                    'control': old['control'], 'name': old['name'],
                    'state': reply['current_state'], 'comparison_call': saved['call']}
    rows = missing(enriched)
    if not rows and not labels:
        return
    appearance_call = None
    if rows:
        pointer = str(Path(job['path']).parent / ('objects-' + digest + '.json'))
        saved = job.get('object_registration', {})
        current = request(runner.root, job['request'], enriched, rows, grounding=grounding)
        reused = reused_boxes(saved.get('result', {}), current)
        if reused is not None:
            result = deepcopy(saved['result'])
            result['candidate']['objects'] = reused
        elif saved.get('digest') == digest:
            result = saved['result']
        else:
            child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot,
                                 runner.available, pointer_name=pointer)
            q = None if pending(runner.run, pointer) else current
            result = child.perform('object_registration', q)
            job['object_registration'] = {'digest': digest, 'result': result}
            runner.save(job)
        appearance_call = result['call']
        for row in result['candidate']['objects']:
            _, kind, index = row['path'].split('/')
            enriched[kind][int(index)]['bbox'] = row['bbox']
    q = deepcopy(job['request'])
    from regrow.runtime.model_transport import expand_schema
    q['response_schema'] = expand_schema(q['response_schema'])
    for kind in ('regions', 'controls'):
        q['response_schema']['properties'][kind]['items']['properties']['bbox'] = deepcopy(BOX)
    select(q, primary(job['request']), '原动作后图；识别范围由单图补登记取得')
    q['semantic_request'] = deepcopy(job['request'])
    q['semantic_request'].pop('control_identity_reviews', None)
    q['registration_sources'] = {'semantic_call': job['call'], 'appearance_call': appearance_call}
    q['appearance_labels'] = labels
    # Identity/state and current-box grounding have separate model evidence.
    # Preserve both sources when satisfying the existing publication review.
    if confirmed:
        from regrow.recognition.control_identity_review import reused_candidates
        from regrow.recognition.control_indexes import decode
        from regrow.records.snapshots import load
        snapshot, records, _ = load(runner.run)
        for pair in reused_candidates(records, snapshot, runner.run / primary(q), q, decode(q, enriched)):
            if pair['control'] in confirmed:
                q.setdefault('control_identity_reviews', []).append({
                    'key': pair['key'], 'decision': 'same',
                    'reason': ('双图比较确认旧身份与状态；当前框由单图定位独立确认'
                               if pair.get('current_box') else '双图比较确认本帧旧身份及相同外观'),
                    'comparison_calls': [r['source_call'] for r in labels if r['control'] == pair['control']],
                    'grounding_call': appearance_call if pair.get('current_box') else None})
    folder = runner.run / 'calls' / job['call']
    job['registration_submission'] = {
        'objects': [{'path': '/' + kind + '/' + str(index), 'bbox': deepcopy(row['bbox'])}
                    for kind in ('regions', 'controls')
                    for index, row in enumerate(enriched.get(kind, [])) if row.get('bbox')],
        'registration_sources': deepcopy(q['registration_sources']),
        'schema_extension': {'bbox': deepcopy(BOX)}}
    job.update(request=q, candidate=enriched)
    runner.save(job)
    write_json(folder / 'registration_request.json', q)
    write_json(folder / 'registration_candidate.json', enriched)


def semantic_revision(reviewed, candidate):
    original = deepcopy(reviewed.get('semantic_request', reviewed))
    original['control_indexes'] = reviewed.get('control_indexes', original.get('control_indexes', []))
    original['control_identity_reviews'] = deepcopy(reviewed.get('control_identity_reviews', []))
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k,v in value.items() if k not in GEOMETRY}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return original, strip(candidate)
