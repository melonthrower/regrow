"""Stable control references at the model boundary; names are display text."""
from copy import deepcopy
import re
import unicodedata
from regrow.records.diagnostics import reject


def label(control, name):
    return control + '/' + name


def recorded_target(records, value):
    """Resolve an explicit object ref against records, independently of UI lists."""
    if records is None or not isinstance(value, str):
        return None
    value = value.strip()
    match = re.fullmatch(r'([cr]\d+)(?:/(.*))?', value)
    if not match:
        return None
    ref, name = match.groups()
    from regrow.records.object_store import control_record, owned_controls
    record = records.get(ref) if ref.startswith('r') else control_record(records, ref)
    title = '区块' if ref.startswith('r') else '控件'
    if record is None:
        reject('object_reference', value, value, '已登记的准确' + title + 'ref',
               field='动作目标', reason='动作目标“' + value + '”没有对应的已登记' + title + '。')
    expected = ref + '/' + record['name']
    if name is not None and value != expected:
        reject('object_reference', value, value, expected, field='动作目标',
               reason='动作目标编号与名称不一致；该编号对应“' + expected + '”。')
    owners = ([ref] if ref.startswith('r') else
              [rid for rid, region in records.items() if ref in owned_controls(region)])
    return {'ref': ref, 'kind': 'region' if ref.startswith('r') else 'control',
            'regions': owners}


def decode_action_target(request, proposal, call):
    """Interpret a retained Action using the labels actually sent with its call."""
    if request.get('action_source', {}).get('call') != call:
        return proposal
    value = deepcopy(proposal)
    if 'received_control_labels' in request:
        from regrow.recognition.named_references import _decode_references
        labels = request['received_control_labels']
        value = _decode_references(value, {name: cid for cid, name in labels.items()},
                                  control_labels=labels, region_labels=request.get('received_region_labels'))
    action = value.get('operation', value)
    ref = request.get('received_new_targets', {}).get(action.get('target'))
    if ref and not re.fullmatch(r'[cr]\d+', str(action.get('target', ''))):
        action['target'] = ref
    return value


def resolve_label(value, labels, *, allow_path=False, prefix='c'):
    """Resolve a disclosed ID/name string; never repair it by another name."""
    if not isinstance(value, str):
        return None
    control, _, _ = value.partition('/')
    supplied = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value).partition('/')[0])
    if not re.fullmatch(prefix + r'\d+', supplied, re.I):
        return None
    title = '控件' if prefix == 'c' else '区块'
    expected = labels.get(control)
    if expected is None:
        reject('object_reference', value, value, '本轮材料提供的' + title + 'ID/名称',
               field=title + '引用', reason=title + '引用“' + value + '”的ID未在本轮材料中提供。',
               repair='核对本次目标，使用材料中对应的完整引用。')
    if value == expected:
        return control
    if allow_path and value.startswith(expected + '/'):
        return control + value[len(expected):]
    reject('object_reference', value, value, expected, field=title + '引用',
           reason=title + '编号与名称不一致；该编号在本轮材料中对应“' + expected + '”。',
           repair='核对实际要引用的对象，使用其给定编号和名称。')


def mapping(request):
    original = request.get('original_request', {})
    return request.get('control_refs', request.get('control_indexes',
        original.get('control_refs', original.get('control_indexes', []))))


def _schemas(schema, group='controls'):
    def branches(item):
        # Object-field revisions already use the retained candidate's contract.
        # Do not turn a partial edit or explicit removal into a full new object.
        if 'candidate_index' in item.get('properties', {}):
            return
        if 'properties' in item:
            yield item
        for key in ('anyOf', 'oneOf'):
            for child in item.get(key, []):
                yield from branches(child)
    if isinstance(schema, dict):
        controls = schema.get('properties', {}).get(group)
        if isinstance(controls, dict) and 'items' in controls:
            yield from branches(controls['items'])
        for value in schema.values():
            yield from _schemas(value, group)
    elif isinstance(schema, list):
        for value in schema:
            yield from _schemas(value, group)


def prepare(request):
    q = deepcopy(request)
    if q.get('name_contract'):
        return q  # An already bound wire contract retains its actual references.
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
                            'description': '使用本轮材料提供的控件ID/名称。'}
            continue
        full = [k for k in item.get('required', []) if k not in ('ref','identity','identity_evidence')]
        for branch in item.get('allOf', []):
            full += [k for k in branch.get('else', {}).get('required', []) if k not in ('ref','identity','identity_evidence')]
        for key in ('identity','identity_evidence'): props.pop(key, None)
        props['ref'] = {'type': 'string', 'enum': allowed, 'description': '已有控件填写本轮提供的ID/名称；新控件省略。'}
        item['required'] = []
        item['allOf'] = [b for b in item.get('allOf', []) if not any(k in b.get('if', {}).get('properties', {}) or k in b.get('if', {}).get('required', []) for k in ('ref','identity'))]
        item['allOf'].append({'if': {'required': ['ref']}, 'then': {},
            'else': {'required': list(dict.fromkeys(full + ['name','region_index']))}})
        item['description'] = '已有控件用ref及变化信息；新控件省略ref并填写新对象资料。'
        if not allowed:
            # Keep the explicit empty scope in saved/correction contracts.
            item['required'] = list(dict.fromkeys(full + ['name','region_index']))
            item['allOf'] = [b for b in item['allOf'] if 'ref' not in b.get('if', {}).get('required', [])]
            if not item['allOf']:
                item.pop('allOf')
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
                reject('object_reference', row.get('name') or '历史控件引用', index,
                       '原请求提供的控件编号', field='控件引用',
                       reason='历史回复引用的控件编号不在原请求提供的范围内。')
            row['ref'] = ids[index]
        if row.get('ref'):
            row.setdefault('identity', 'same')
        else:
            row.setdefault('ref', None)
            row.setdefault('identity', 'new')
    if legacy:
        for group in value.get('function_updates', []):
            for row in [*group.get('add', []), *(r['changes'] for r in group.get('update', []))]:
                for key in ('supports', 'parameters', 'constraints'):
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
