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


def request(root, original, candidate, rows):
    text = (Path(root) / 'regrow/prompts/任务/对象识别资料.prompt').read_text()
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


def complete(runner, job):
    """Resume a normal child repair; no GUI capture or partial graph publication."""
    if job['stage'] != 'update':
        return
    candidate = job.get('candidate') or {}
    jsonschema.validate(candidate, job['request']['response_schema'])
    rows = missing(candidate)
    if not rows:
        return
    digest = hashlib.sha256(json.dumps([candidate, job['request'].get('control_indexes')],
                                      sort_keys=True).encode()).hexdigest()[:16]
    pointer = str(Path(job['path']).parent / ('objects-' + digest + '.json'))
    saved = job.get('object_registration', {})
    if saved.get('digest') == digest:
        result = saved['result']
    else:
        child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot,
                             runner.available, pointer_name=pointer)
        from regrow.traversal.step_repair import pending
        q = None if pending(runner.run, pointer) else request(runner.root, job['request'], candidate, rows)
        result = child.perform('object_registration', q)
        job['object_registration'] = {'digest': digest, 'result': result}
        runner.save(job)
    enriched = deepcopy(candidate)
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
    q['registration_sources'] = {'semantic_call': job['call'], 'appearance_call': result['call']}
    folder = runner.run / 'calls' / job['call']
    job['registration_submission'] = {'request': q, 'candidate': enriched}
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
