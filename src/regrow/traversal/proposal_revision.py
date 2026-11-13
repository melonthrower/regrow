"""Apply explicit object edits to a retained update, then use normal validation."""
from copy import deepcopy

MODE = 'object_fields'
OBJECTS = ('regions', 'controls')


def continuation_source(original, correction, proposal):
    """An edited Action belongs to the request which supplied that subtree."""
    q = deepcopy(original)
    if not isinstance(proposal, dict) or 'next_action' not in proposal:
        return q
    contract = correction.get('sent_name_contract')
    schema = correction.get('next_action_wire_schema')
    if contract and schema:
        q['sent_name_contract'] = deepcopy(contract)
        q['next_action_wire_schema'] = deepcopy(schema)
    return q


def _object_branches(schema):
    if schema.get('type') == 'object' or 'properties' in schema:
        yield schema
    for key in ('anyOf', 'oneOf'):
        for child in schema.get(key, []):
            yield from _object_branches(child)


def prepare(job, original, schema):
    from regrow.traversal.object_registration import semantic_revision
    from regrow.runtime.model_transport import expand_schema
    if job['stage'] != 'update' or job.get('control_identity_pair') or job.get('control_identity_candidates'):
        return None
    base = job.get('candidate')
    if not isinstance(base, dict) or not base:
        return None
    _, base = semantic_revision(job['request'], base)
    refs = [row['ref'] for row in base.get('regions', []) if row.get('ref')]
    if len(refs) != len(set(refs)):
        return None  # Duplicate names cannot address a partial object edit.
    expanded = expand_schema(schema)
    allowed = expanded.get('properties', {})
    if not allowed or set(base) - set(allowed):
        return None
    for kind in OBJECTS:
        if kind not in allowed or not base.get(kind):
            continue
        item = allowed[kind].get('items', {})
        fields = {}
        for branch in _object_branches(item):
            for key, value in branch.get('properties', {}).items():
                options = fields.setdefault(key, [])
                if value not in options:
                    options.append(deepcopy(value))
        if not fields:
            continue
        fields = {key: values[0] if len(values) == 1 else {'anyOf': values}
                  for key, values in fields.items()}
        index = {'type': 'integer', 'enum': list(range(len(base[kind]))),
                 'description': '要修订或撤回的原稿条目编号。'}
        edit = {'type': 'object', 'properties': {'candidate_index': index, **fields,
                'remove_fields': {'type': 'array', 'items': {'type': 'string', 'enum': list(fields)},
                                  'minItems': 1, 'uniqueItems': True,
                                  'description': '明确撤掉本对象中误填的字段；未列出的字段保留。'}},
                'required': ['candidate_index'], 'minProperties': 2, 'additionalProperties': False}
        remove = {'type': 'object', 'properties': {
            'candidate_index': deepcopy(index), 'remove': {'const': True},
            'reason': {'type': 'string', 'minLength': 1}},
            'required': ['candidate_index', 'remove', 'reason'], 'additionalProperties': False}
        allowed[kind]['items'] = {'anyOf': [deepcopy(item), edit, remove]}
    expanded['required'] = []
    expanded['minProperties'] = 1
    schema.clear()
    schema.update(expanded)
    return deepcopy(base)


def guidance():
    return ('只提交需要修改的字段；省略字段保留。regions、controls按对象修订：'
            '已有对象用ref，原稿中的新对象用candidate_index；未提到的条目保持原序，新增接在末尾。'
            '撤回原稿条目用candidate_index、remove:true和reason；空对象列表不撤回任何条目。'
            '只撤掉误填字段时，用candidate_index和remove_fields列出字段名。'
            '对象内明确提交的字段及其他顶层字段整体替换。关系索引按原稿编号，新增从原稿长度起编号；'
            '撤回对象后仍引用它的关系须同时修正。')


def display(base):
    result = deepcopy(base)
    for kind in OBJECTS:
        for index, row in enumerate(result.get(kind, [])):
            if isinstance(row, dict):
                row['candidate_index'] = index
    return result


def examples(base):
    if base.get('controls'):
        return [{'controls': [{'candidate_index': 0, 'knowledge': [
            {'description': '打开功能面板，继续选择操作。'}]}]},
            {'controls': [{'candidate_index': 0, 'remove': True,
                           'reason': '该候选是文字标签，不能独立操作。'}]}]
    if base.get('regions'):
        return [{'regions': [{'candidate_index': 0, 'description': '显示当前对象的属性。'}]}]
    return []


def _error(path, message, **facts):
    from regrow.records.registration_diagnostics import Rejected
    raise Rejected({'errors': [{'code': 'candidate_revision', 'path': path,
                               'expected': message, **facts}], 'unchecked': []})


def _objects(base, edits, kind, *, provenance=None):
    if not isinstance(base, list) or not isinstance(edits, list):
        _error('/' + kind, '对象修订须为数组')
    rows = deepcopy(base)
    touched = set()
    removed = set()
    for position, edit in enumerate(edits):
        path = f'/{kind}/{position}'
        if not isinstance(edit, dict):
            _error(path, '每个对象修订须为对象')
        index = edit.get('candidate_index')
        if 'candidate_index' in edit:
            if type(index) is not int or not 0 <= index < len(base):
                _error(path, 'candidate_index须引用给定原稿中的条目')
        elif edit.get('ref'):
            matches = [i for i, row in enumerate(base)
                       if isinstance(row, dict) and row.get('ref') == edit['ref']]
            if len(matches) > 1:
                _error(path, '该ref对应多个原稿条目，请用candidate_index指定')
            index = matches[0] if matches else None
        if index is not None and index in touched:
            _error(path, f'原稿candidate_index={index}被重复修订或撤回；每个条目只能提交一次')
        if edit.get('remove') is True:
            if ('candidate_index' not in edit or not str(edit.get('reason', '')).strip()
                    or set(edit) != {'candidate_index', 'remove', 'reason'}):
                _error(path, '撤回须仅填写candidate_index、remove:true和reason')
            removed.add(index)
        else:
            removed_fields = edit.get('remove_fields', [])
            if 'remove_fields' in edit and ('candidate_index' not in edit or index is None):
                _error(path, '撤掉字段须用candidate_index指定原稿对象')
            if any(key in edit for key in removed_fields):
                _error(path, '同一字段不能同时撤掉和重新赋值')
            changes = {key: deepcopy(value) for key, value in edit.items() if key not in ('candidate_index', 'remove_fields')}
            if provenance is not None:
                origin = len(rows) if index is None else index
                for field in changes:
                    provenance[(origin, field)] = position
            if index is None:
                rows.append(changes)
            else:
                for key in removed_fields:
                    rows[index].pop(key, None)
                rows[index] = {**rows[index], **changes}
        if index is not None:
            touched.add(index)
    indexes = {old: new for new, old in enumerate(i for i in range(len(rows)) if i not in removed)}
    return [row for i, row in enumerate(rows) if i not in removed], indexes


def _references(result, indexes, proposal=None, provenance=None):
    # Only protocol relationships are indexes; knowledge parameter names are data.
    origins = {kind: {new: old for old, new in values.items()} for kind, values in indexes.items()}
    def remap(row, key, kind, path):
        if key not in row or row[key] is None:
            return
        value = row[key]
        if type(value) is not int or value not in indexes[kind]:
            parts = path.strip('/').split('/')
            group = parts[0]
            edit = (provenance or {}).get(group, {}).get((int(parts[1]), key))
            latest = edit is not None or group not in OBJECTS and group in (proposal or {})
            location = f'/{group}/{edit}/{key}' if edit is not None else path + '/' + key
            _error(location,
                   f'按原稿编号，{path}/{key}={value}指向已撤回或不存在的对象；请同时修正这条关系',
                   actual=value, reply_source='latest_reply' if latest else 'proposal_base')
        row[key] = indexes[kind][value]
    for i, row in enumerate(result.get('controls', [])):
        remap(row, 'region_index', 'regions', f'/controls/{origins["controls"][i]}')
    for i, row in enumerate(result.get('current_regions', [])):
        remap(row, 'region_index', 'regions', f'/current_regions/{i}')
    for i, row in enumerate(result.get('jump_to', [])):
        remap(row, 'region_index', 'regions', f'/jump_to/{i}')
        remap(row, 'control_index', 'controls', f'/jump_to/{i}')


def merge(request, proposal):
    if 'proposal_base' not in request:
        return proposal
    if not isinstance(proposal, dict):
        raise ValueError('revise需要提供本次修订的字段')
    base = request['proposal_base']
    if request.get('proposal_revision') != MODE:
        # Saved older requests retain the contract actually sent to their model.
        return {**deepcopy(base), **deepcopy(proposal)}
    result = {**deepcopy(base), **deepcopy(proposal)}
    indexes = {}
    provenance = {}
    for kind in OBJECTS:
        provenance[kind] = {}
        rows, indexes[kind] = _objects(base.get(kind, []), proposal.get(kind, []), kind,
                                      provenance=provenance[kind])
        if kind in base or kind in proposal:
            result[kind] = rows
    _references(result, indexes, proposal, provenance)
    return result
