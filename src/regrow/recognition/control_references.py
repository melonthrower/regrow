"""Stable control references at the model boundary; names are display text."""
from copy import deepcopy
import re


def mapping(request):
    original = request.get('original_request', {})
    return request.get('control_refs', request.get('control_indexes',
        original.get('control_refs', original.get('control_indexes', []))))


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
    q = deepcopy(request)
    from regrow.runtime.model_transport import expand_schema
    q['response_schema'] = expand_schema(q.get('response_schema', {}))
    items = list(_schemas(q['response_schema']))
    ids = list(mapping(q))
    candidates = set(re.findall(r'(?<![A-Za-z0-9_])c\d+(?![A-Za-z0-9_])', q.get('user_prompt', '')))
    candidates.update(q.get('discovery_context', {}).get('control_names', {}).values())
    for cid in sorted(candidates, key=lambda value: int(value[1:])):
        if cid not in ids: ids.append(cid)
    q['control_refs'] = ids
    if q.get('original_request') and 'control_indexes' not in q['original_request']:
        # Corrections retain the actual original contract, including old evidence.
        q['original_request'].setdefault('control_refs', ids)
    for item in items:
        props = item['properties']
        known_edits = set(props) <= {'ref', 'knowledge'}
        allowed = props.get('ref', {}).get('enum', ids)
        if known_edits:
            props['ref'] = {'type': 'string', 'enum': allowed,
                            'description': '控件树中的控件ID，例如c0008。'}
            continue
        full = [k for k in item.get('required', []) if k not in ('ref','identity','identity_evidence')]
        for branch in item.get('allOf', []):
            full += [k for k in branch.get('else', {}).get('required', []) if k not in ('ref','identity','identity_evidence')]
        for key in ('identity','identity_evidence'): props.pop(key, None)
        props['ref'] = {'type': 'string', 'enum': ids, 'description': '已有控件填写控件树中的ID；新控件省略。'}
        item['required'] = []
        item['allOf'] = [b for b in item.get('allOf', []) if not any(k in b.get('if', {}).get('properties', {}) or k in b.get('if', {}).get('required', []) for k in ('ref','identity'))]
        item['allOf'].append({'if': {'required': ['ref']}, 'then': {},
            'else': {'required': list(dict.fromkeys(full + ['name','region_index']))}})
        item['description'] = '已有控件用ref及变化信息；新控件省略ref并填写新对象资料。'
        if not ids:
            props.pop('ref')
            item['required'] = list(dict.fromkeys(full + ['name','region_index']))
            item['allOf'] = [b for b in item['allOf'] if 'ref' not in b.get('if', {}).get('required', [])]
    return q


def decode(request, reply):
    """Derive registration flags without changing the recorded model reply."""
    value = deepcopy(reply)
    ids = mapping(request)
    legacy = 'control_indexes' in request and 'control_refs' not in request
    for row in value.get('controls', []):
        if legacy and 'index' in row:
            index = row.pop('index')
            if type(index) is not int or not 0 <= index < len(ids):
                raise ValueError('历史回复的控件编号不在原请求中')
            row['ref'] = ids[index]
        if row.get('ref'):
            row.setdefault('identity', 'same')
        else:
            row.setdefault('ref', None)
            row.setdefault('identity', 'new')
    if legacy:
        for group in value.get('function_updates', []):
            for row in [*group.get('add', []), *(r['changes'] for r in group.get('update', []))]:
                for key in ('supports', 'constraints'):
                    if key in row:
                        row[key] = [re.sub(r'控件\[index=(\d+)\]', lambda m: ids[int(m[1])], ref) if isinstance(ref,str) else ids[ref] for ref in row[key]]
    return value


def encode(request, reply):
    value = deepcopy(reply)
    ids = mapping(request)
    legacy = 'control_indexes' in request and 'control_refs' not in request
    for row in value.get('controls', []):
        row.pop('identity', None); row.pop('identity_evidence', None)
        if not row.get('ref'): row.pop('ref', None)
        elif legacy: row['index'] = ids.index(row.pop('ref'))
    return value


def after_record_edit(original, refreshed, records):
    from regrow.records.control_records import aliases
    q = deepcopy(refreshed)
    ids = []
    for cid in mapping(original):
        matches = [key for key, control in records.controls.items()
                   if key == cid or any(row.get('id') == cid for row in aliases(control))]
        ids.append(matches[0] if len(matches) == 1 else cid)
    q['control_refs'] = ids
    if 'discovery_context' in q:
        q['discovery_context'].setdefault('control_names', {}).update({cid:cid for cid in ids})
    return prepare(q)
