from regrow.records.control_records import aliases as control_aliases
"""Per-request control aliases at the model boundary; stable IDs stay in records."""
from copy import deepcopy
import json
import re


def mapping(request):
    return request.get('control_indexes', request.get('original_request', {}).get('control_indexes', []))


def _schemas(schema):
    if isinstance(schema, dict):
        controls = schema.get('properties', {}).get('controls')
        if isinstance(controls, dict) and 'items' in controls:
            yield controls['items']
        for value in schema.values():
            yield from _schemas(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _schemas(value)


def prepare(request):
    """Bind and disclose aliases once, before generating the sent schema text."""
    q = deepcopy(request)
    from regrow.runtime.model_transport import expand_schema
    q['response_schema'] = expand_schema(q.get('response_schema', {}))
    items = list(_schemas(q['response_schema']))
    if not items:
        return q
    ids = list(mapping(q))
    body = q.get('user_prompt', '')
    candidates = set(re.findall(r'(?<![A-Za-z0-9_])c\d+(?![A-Za-z0-9_])', body))
    candidates.update(q.get('discovery_context', {}).get('control_names', {}).values())
    for cid in sorted(candidates, key=lambda value: int(value[1:])):
        if cid not in ids:
            ids.append(cid)
    q['control_indexes'] = ids
    if q.get('original_request'):
        q['original_request']['control_indexes'] = list(ids)
        q['original_request'] = prepare(q['original_request'])
    for item in items:
        props = item['properties']
        full = [k for k in item.get('required', []) if k not in ('ref','identity','identity_evidence','index')]
        for branch in item.get('allOf', []):
            full += [k for k in branch.get('else', {}).get('required', []) if k not in ('ref','identity','identity_evidence','index')]
        for key in ('ref','identity','identity_evidence'):
            props.pop(key, None)
        props['index'] = {'type':'integer', 'enum':list(range(len(ids))), 'description':'引用本轮材料中的已有控件index；不是本次输出的位置。'} if ids else {'not':{}, 'description':'本轮没有历史控件，新控件不填index。'}
        item['required'] = []
        item['allOf'] = [branch for branch in item.get('allOf', []) if not any(k in branch.get('if', {}).get('properties', {}) or k in branch.get('if', {}).get('required', []) for k in ('ref','index'))]
        item['allOf'].append({'if':{'required':['index']}, 'then':{}, 'else':{'required':list(dict.fromkeys(full + ['name','region_index']))}})
        item['description'] = '已有控件填写index及本次变化；确认新增时不填index并填写新控件资料。身份未确定的对象写入uncertainties，暂不提交控件记录。'
        if not ids:
            props.pop('index', None)
            item['required'] = list(dict.fromkeys(full + ['name','region_index']))
            item['allOf'] = [b for b in item['allOf'] if 'index' not in b.get('if', {}).get('required', [])]
            item['description'] = '本轮没有历史控件；确认新对象时填写新控件资料，身份不确定写入uncertainties。'
        if not item.get('allOf'):
            item.pop('allOf', None)
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(q['response_schema'])
    return q


def display(request):
    """Replace control IDs in sent prose, preserving literal task-output references."""
    ids = mapping(request)
    if not ids and 'control_indexes' not in request:
        return request
    q = deepcopy(request)
    protected = []
    def tasks(schema):
        if isinstance(schema, dict):
            protected.extend(value for value in schema.get('enum', []) if isinstance(value, str) and re.search(r'(?<![A-Za-z0-9_])c\d+(?![A-Za-z0-9_])', value))
            for child in schema.values(): tasks(child)
        elif isinstance(schema,list):
            for child in schema: tasks(child)
    tasks(q.get('response_schema', {}))
    for key in ('system_prompt','user_prompt'):
        text = q.get(key,'')
        for i, value in enumerate(protected):text = text.replace(value, f'__TASK_LITERAL_{i}__')
        for i, cid in enumerate(ids):text = re.sub(r'(?<![A-Za-z0-9_])'+re.escape(cid)+r'(?![A-Za-z0-9_])', f'控件[index={i}]', text)
        for i, value in enumerate(protected):text = text.replace(f'__TASK_LITERAL_{i}__', value)
        q[key] = text
    if '_presentation_digest' in q:
        import hashlib
        q['_presentation_digest'] = hashlib.sha256(q['user_prompt'].encode()).hexdigest()
    return q


def decode(request, reply):
    """Derive internal identity decisions; never change the saved model reply."""
    if 'control_indexes' not in request:
        return deepcopy(reply)
    value = deepcopy(reply)
    ids = mapping(request)
    for row in value.get('controls', []):
        if 'index' in row:
            index = row.pop('index')
            if type(index) is not int or not 0 <= index < len(ids):
                raise ValueError('controls.index不在本轮历史控件列表中')
            if row.get('ref') and row['ref'] != ids[index]:
                raise ValueError('控件index与内部身份冲突')
            row['ref'] = ids[index]
            row['identity'] = 'same'
        elif 'ref' not in row:
            row.update(ref=None, identity='new')
    return value


def encode(request, reply):
    """Return a derived identity-review candidate to the same output contract."""
    if 'control_indexes' not in request:
        return deepcopy(reply)
    value = deepcopy(reply)
    ids = mapping(request)
    for row in value.get('controls', []):
        ref = row.pop('ref', None)
        row.pop('identity', None)
        row.pop('identity_evidence', None)
        if ref:
            if ref not in ids:
                raise ValueError('身份复核对象未提供本轮index')
            row['index'] = ids.index(ref)
        else:
            row.pop('index', None)
    return value


def after_record_edit(original, refreshed, records):
    """Keep submitted positions while following explicitly merged stable identities."""
    if 'control_indexes' not in original:
        return refreshed
    from regrow.records.object_store import owned_controls
    q = deepcopy(refreshed)
    ids = []
    for cid in original['control_indexes']:
        matches = [key for region in records.values() for key, control in owned_controls(region).items()
                   if key == cid or any(row.get('id') == cid for row in control_aliases(control))]
        matches = list(dict.fromkeys(matches))
        ids.append(matches[0] if len(matches) == 1 else cid)
    q['control_indexes'] = ids
    if 'discovery_context' in q:
        q['discovery_context'].setdefault('control_names', {}).update({cid:cid for cid in ids})
    return prepare(q)
