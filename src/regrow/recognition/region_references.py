"""Region registration at the model boundary; stored identity remains canonical."""
from copy import deepcopy
import re
from regrow.recognition.control_references import _schemas


def prepare(request):
    q = deepcopy(request)
    if q.get('name_contract'):
        return q
    from regrow.runtime.model_transport import expand_schema
    q['response_schema'] = expand_schema(q['response_schema'])
    ids = list(q.get('region_refs', []))
    from regrow.recognition.named_references import disclosed_ids
    disclosed = {ref for ref in disclosed_ids(q) if ref.startswith('r')}
    disclosed.update(ref for ref in q.get('region_names', {}).values()
                     if isinstance(ref, str) and re.fullmatch(r'r[0-9]+', ref))
    for rid in sorted(disclosed):
        if rid not in ids:
            ids.append(rid)
    q['region_refs'] = ids
    for item in _schemas(q['response_schema'], 'regions'):
        props = item['properties']
        if 'ref' not in props and 'name' not in props:
            continue
        # Knowledge-only edits retain their explicitly supplied write scope.
        if set(props) <= {'ref', 'local_knowledge'}:
            continue
        for key in ('identity', 'identity_evidence'):
            props.pop(key, None)
        required = [k for k in item.get('required', []) if k not in ('ref', 'identity', 'identity_evidence')]
        for branch in item.get('allOf', []):
            required += [k for k in branch.get('else', {}).get('required', [])
                         if k not in ('ref', 'identity', 'identity_evidence')]
        allowed = props.get('ref', {}).get('enum', ids)
        props['ref'] = {'type': 'string', 'enum': allowed,
                        'description': '已有区块使用本轮给出的ID/名称；新区块省略ref。'}
        item['required'] = []
        item['allOf'] = [branch for branch in item.get('allOf', [])
                        if not any(k in branch.get('if', {}).get('properties', {})
                                   or k in branch.get('if', {}).get('required', [])
                                   for k in ('ref', 'identity'))]
        item['allOf'].append({'if': {'required': ['ref']}, 'then': {},
                             'else': {'required': list(dict.fromkeys(required + ['name', 'description']))}})
        item['description'] = '新区块填写name/description等本步字段；已有区块填写ref及变化信息。'
        if not allowed:
            item['required'] = list(dict.fromkeys(required + ['name', 'description']))
            item['allOf'] = [branch for branch in item['allOf'] if 'ref' not in branch.get('if', {}).get('required', [])]
            if not item['allOf']:
                item.pop('allOf')
    return q


def decode(request, reply):
    value = deepcopy(reply)
    if 'region_refs' not in request:
        return value  # A saved old request keeps its original identity contract.
    for row in value.get('regions', []):
        row.setdefault('ref', None)
        row.setdefault('identity', 'same' if row['ref'] else 'new')
    return value
