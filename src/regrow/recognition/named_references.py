"""Readable call-local references; storage identities and registration stay canonical.

The wire reply is immutable. Only an explicit derived reply flattens nested
observations and resolves names within the objects disclosed by this request.
"""
from copy import deepcopy
import json
import re
import unicodedata
from regrow.records.diagnostics import reject
from regrow.recognition import reference_fields

TOKEN = re.compile(r'(?<![A-Za-z0-9_])[rc]\d+(?![A-Za-z0-9_])')
OBJECT_ID = re.compile(r'[rc][0-9]+')
REFERENCE_FIELDS = {'ref','target','control','region','source_region','source_control',
                    'task','supports','parameters','constraints','access_entry','replace_with','candidate','path'}


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


def resolve(value, aliases):
    """Never choose the closest object or infer an object's historical identity."""
    if not isinstance(value, str):
        return value
    if value in aliases:
        return aliases[value] if aliases[value] is not None else value
    key = normalized(value)
    hits = {v for k, v in aliases.items() if normalized(k) == key}
    if not hits:
        # A conventional optional area suffix is a spelling variant, not a
        # general edit-distance rule (import/export must remain different).
        stem = lambda s: re.sub(r'(区域|区)$', '', normalized(s))
        hits = {v for k, v in aliases.items() if stem(k) == stem(value)}
    return next(iter(hits)) if len(hits) == 1 and None not in hits else value


def labels(run, request):
    from regrow.records.snapshots import load
    from regrow.records.object_store import owned_controls
    try:
        _, records, _ = load(run)
    except (OSError, ValueError):
        records = {}
    ids = disclosed_ids(request)
    ids.update(request.get('control_refs', []))
    ids.update(request.get('region_refs', []))
    from regrow.recognition.control_references import label
    names = {rid: label(rid, region['name']) for rid, region in records.items() if rid in ids}
    owners = {}
    for rid,r in records.items():
        for cid,c in owned_controls(r).items():
            if cid in ids:
                names[cid] = label(cid, c['name'])
                owners.setdefault(cid, []).append(rid)
                names.setdefault(rid, label(rid, r['name']))
    return names, _display_owners(run, request, owners)


def disclosed_ids(request):
    """Use explicit candidates and typed material, without reading IDs out of prose."""
    from regrow.prompts.prompt_material import body
    material, _ = body(request)
    ids = set()

    def add(value):
        if isinstance(value, str):
            prefix = value.partition('/')[0]
            if OBJECT_ID.fullmatch(prefix):
                ids.add(prefix)

    fields = {'id', 'ref', 'control', 'region', 'source_region', 'source_control', 'region_ref',
              'control_ref', 'task_region', 'task_control', 'working_region', 'completion_region',
              'return_to', 'from_region', 'to_region', 'from_control', 'to_control', 'next_region'}
    def material_ids(node):
        if isinstance(node, list):
            for item in node:
                material_ids(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in fields:
                    add(value)
                if isinstance(value, (dict, list)):
                    material_ids(value)

    from regrow.runtime.model_transport import expand_schema
    for ref in reference_fields.reference_values(expand_schema(request['response_schema'])):
        add(ref)
    material_ids(request.get('source', {}))
    material_ids(request.get('backend_candidates', []))
    page = request.get('page_context', {})
    for key in ('current_tree', 'origin', 'background_regions', 'goal'):
        material_ids(page.get(key))
    discovery = request.get('discovery_context', {})
    for key in ('region_names', 'control_names'):
        for ref in discovery.get(key, {}).values():
            add(ref)
    for key in ('本次身份候选', '本轮局部控件', '待核对历史控件', '比较对象', '待补齐对象',
                '原区块', '当前任务', '本轮可判断旧任务', '已有功能', '任务关联功能', '可修订候选的完整知识'):
        material_ids(material.get(key))
    # These two producers emit object labels as tree nodes. Free-form
    # descriptions in those sections cannot add objects to the mapping.
    for key in ('控件树', '环境位置'):
        block = material.get(key)
        if isinstance(block, str):
            ids.update(re.findall(r'(?m)^ *[└├]─ ([rc][0-9]+)(?=/)', block))
    return ids


def _display_owners(run, request, memberships):
    """Keep all display locations; a knowledge edit has no unique owner claim."""
    original = request.get('original_request', request)
    hints = original.get('display_regions', {})
    return {cid: ([hints[cid]] + [rid for rid in rids if rid != hints[cid]]
                  if hints.get(cid) in rids else list(rids))
            for cid, rids in memberships.items()}

def display_regions(request, reply):
    """Retain the original outer Region solely in the interpreted call context."""
    contract = request.get('name_contract')
    if not contract or not contract.get('nested') or not isinstance(reply, dict):
        return {}
    if contract.get('typed_fields'):
        names = {label: ref for ref, label in contract['names'].items()}
    else:
        names = contract['aliases']
    value = reply
    if isinstance(value.get('proposal'), dict):
        value = value['proposal']
    from regrow.records.object_knowledge import control_only
    result = {}
    rows = value.get('regions', [])
    for row in rows if isinstance(rows, list) else ():
        label = row.get('ref') if isinstance(row, dict) else None
        rid = names.get(label) if isinstance(label, str) else None
        if rid not in contract['names']:
            continue
        controls = row.get('controls', [])
        for control in controls if isinstance(controls, list) else ():
            if isinstance(control, dict) and control_only(control):
                label = control.get('ref')
                cid = names.get(label) if isinstance(label, str) else None
                if cid in contract['names']:
                    result.setdefault(cid, rid)
    return result


def _drop(schema, keys):
    if isinstance(schema, dict):
        if 'properties' in schema:
            for key in keys: schema['properties'].pop(key, None)
        if 'required' in schema:
            schema['required'] = [k for k in schema['required'] if k not in keys]
        for child in schema.values(): _drop(child, keys)
    elif isinstance(schema, list):
        for child in schema: _drop(child, keys)


def _output_objects(schema):
    """Yield the current business shape, including the proposal inside a repair."""
    if not isinstance(schema, dict):
        return
    fields = schema.get('properties', {})
    if 'proposal' in fields:
        yield from _output_objects(fields['proposal'])
    else:
        yield fields
    for key in ('anyOf', 'oneOf'):
        for branch in schema.get(key, []):
            yield from _output_objects(branch)


def wire_schema(schema, nested):
    s = deepcopy(schema)
    def item_schema(item):
        if 'properties' in item:return item
        props={}
        for branch in item.get('anyOf',[]):props.update(deepcopy(branch.get('properties',{})))
        props.pop('candidate_index',None)
        if 'remove_fields' in props:
            values=props['remove_fields'].get('items',{}).get('enum',[])
            props['remove_fields']['items']['enum']=[k for k in values if k not in ('region_index','candidate_index')]
        props['ref']={'type':'string','minLength':1}
        return {'type':'object','properties':props,'anyOf':[{'required':['ref']},{'required':['name']}],'additionalProperties':False}
    def visit(node):
        if isinstance(node, list):
            for child in node: visit(child)
        if not isinstance(node, dict): return
        props = node.get('properties', {})
        if nested and 'regions' in props and 'controls' in props:
            if 'current_regions' in props:
                props['current_regions']['items'] = {
                    'type': 'object', 'properties': {'ref': {
                        'type': 'string', 'minLength': 1,
                        'description': '已有区块使用本轮给出的ID/名称；本次新区块使用其登记名称。'}},
                    'required': ['ref'], 'additionalProperties': False}
            region = item_schema(props['regions']['items']); props['regions']['items']=region
            control = item_schema(deepcopy(props['controls']['items']))
            _drop(control, {'region_index','candidate_index'})
            _drop(region, {'candidate_index'})
            region['properties']['controls'] = {'type':'array','items':control}
            props.pop('controls')
            node['required'] = [k for k in node.get('required',[]) if k != 'controls']
            if 'jump_to' in props:
                def route(node):
                    if isinstance(node,list):
                        for child in node:route(child)
                    elif isinstance(node,dict):
                        rp=node.get('properties',{})
                        for old,new in [('region_index','region'),('control_index','control')]:
                            if old in rp:
                                rp.pop(old);rp[new]={'type':'string','minLength':1}
                                node['required']=[new if k==old else k for k in node.get('required',[])]
                        for child in node.values():route(child)
                route(props['jump_to'])
        for child in node.values(): visit(child)
    visit(s)
    return s


def _key(row):
    return row.get('ref') or row.get('name', '')


def encode_reply(value, contract):
    """Present the correction candidate before serializing it as JSON."""
    if not contract or not isinstance(value, dict):
        return deepcopy(value)
    v = deepcopy(value)
    if isinstance(v.get('proposal'), dict):
        v['proposal'] = _nest_objects(v['proposal'], contract)
    else:
        v = _nest_objects(v, contract)
    if contract.get('typed_fields'):
        return reference_fields.translate(v, contract, to_wire=True)
    # Old sent contracts deliberately used IDs inside function_updates.
    return reference_fields.translate(v, {**contract, 'legacy': True}, to_wire=True)


def _nest_objects(value, contract):
    if not contract.get('nested') or 'regions' not in value or 'controls' not in value:
        return value
    owners, current = contract['owners'], contract['current']
    v = deepcopy(value)
    regions = v['regions']
    selected = set()
    if not isinstance(regions, list) or not isinstance(v['controls'], list):
        return v
    def reference(rows, index):
        # A rejected candidate may contain an unresolved name or bad position.
        # Keep that value visible for correction instead of indexing with it.
        return _key(rows[index]) if type(index) is int and 0 <= index < len(rows) else deepcopy(index)
    for r in v.get('current_regions', []):
        if not isinstance(r, dict):
            continue
        if type(r.get('region_index')) is int: selected.add(r['region_index'])
        elif r.get('ref'):
            selected.update(i for i, row in enumerate(regions)
                            if isinstance(row, dict) and row.get('ref') == r['ref'])
    for i, row in enumerate(regions):
        if not isinstance(row, dict):
            continue
        row.pop('candidate_index',None)
        if current: row['current']=i in selected
    for c in v.pop('controls'):
        if not isinstance(c, dict):
            v.setdefault('controls', []).append(c)
            continue
        c.pop('candidate_index',None);i=c.pop('region_index',None)
        if i is None:
            locations = owners.get(c.get('ref'), [])
            locations = [locations] if isinstance(locations, str) else locations
            # The retained outer Region is preferred. Otherwise use a
            # display-only reference to a known member.
            # decode still strips this container for pure knowledge; it never
            # writes membership, visibility, observation or task ownership.
            rid = locations[0] if locations else None
            matches = [j for j, row in enumerate(regions)
                       if rid and isinstance(row, dict) and row.get('ref') == rid]
            if not matches and rid:
                regions.append({'ref':rid});matches=[len(regions)-1]
            if not matches:
                v.setdefault('controls', []).append(c)
                continue
            # Duplicate rows can occur in a rejected reply. They still name
            # one owner; retain the rows for correction without rebinding it.
            i=matches[0]
        if type(i) is int and 0 <= i < len(regions) and isinstance(regions[i], dict):
            controls = regions[i].setdefault('controls', [])
            if isinstance(controls, list):
                controls.append(c)
                continue
        v.setdefault('controls', []).append({**c, 'region_index': i})
    for row in v.get('jump_to',[]):
        if not isinstance(row, dict):
            continue
        if 'region_index' in row:
            row['region']=reference(regions,row.pop('region_index'))
        if 'control_index' in row:
            row['control']=reference(value['controls'],row.pop('control_index'))
    for row in v.get('current_regions', []):
        if not isinstance(row, dict):
            continue
        if 'region_index' in row:
            row['ref'] = reference(regions, row.pop('region_index'))
    if current:  # Retained only for already-sent inline-current contracts.
        v.pop('current_regions',None)
    return v


def prepare(run, request):
    """Select the wire contract before the normal field-section renderer runs."""
    q=deepcopy(request)
    if q.get('name_contract'):
        return q
    from regrow.runtime.model_transport import expand_schema
    schema=expand_schema(q['response_schema'])
    nested = any('regions' in props and 'controls' in props and
                 ('region_index' in json.dumps(props['controls']) or q.get('original_request', {}).get('named_nested'))
                 for props in _output_objects(schema))
    saved = q.get('sent_name_contract') or q.get('original_request', {}).get('sent_name_contract')
    if saved:
        names, owners = deepcopy(saved['names']), deepcopy(saved['owners'])
    else:
        names, owners = labels(run, q)
    if q.get('action_source') and q.get('received_new_targets'):
        new_ids = set(q['received_new_targets'].values())
        registered, _ = labels(run, {**q, 'control_refs': [*q.get('control_refs', []), *new_ids]})
        names.update({ref: label for ref, label in registered.items() if ref in new_ids})
    if 'region_refs' in q and not saved:
        from regrow.recognition.control_references import _schemas
        q['region_refs'] = [ref for ref in q['region_refs'] if ref in names]
        for item in _schemas(schema, 'regions'):
            field = item.get('properties', {}).get('ref', {})
            if 'enum' in field:
                field['enum'] = [ref for ref in field['enum'] if ref in names]
    paths={}
    if q.get('registration_paths'):
        original = q.get('original_request', q)
        saved_paths = original.get('registration_path_names', {})
        from regrow.prompts.prompt_material import body
        material, _ = body(original)
        used = set()
        for row in material.get('待补齐对象', []):
            path = row['path']
            ref = row.get('ref')
            label = names.get(ref) or saved_paths.get(path) or row.get('名称') or row.get('name') or path
            if ref not in names and row.get('所属区块') and path not in saved_paths:
                label = str(row['所属区块']) + ' / ' + label
            if label in used:
                label = path
            paths[path] = label
            used.add(label)
        paths = {path: paths.get(path, saved_paths.get(path, path)) for path in q['registration_paths']}
        if len(set(paths.values())) != len(paths):
            paths={p:p for p in paths}  # Distinct request slots may have the same display name.
    candidates = q.get('backend_candidates', [])
    example = next((names[row['id']] for row in candidates if row['id'] in names),
                   '未登记控件的可见描述')
    contract={'schema':schema,'names':names,'owners':owners,'nested':nested,
              'control_reference_style':'id_name', 'region_reference_style':'id_name',
              'current':False,'paths':paths,'typed_fields':True,'action_example':example}
    review = q.get('done_task_review')
    if review:
        contract['edit_task_region'] = review['region']
    if q.get('proposal_base') is not None:
        contract['base'] = deepcopy(q['proposal_base'])
    q['name_contract']=contract
    q['response_schema']=reference_fields.wire_schema(wire_schema(schema,nested),contract)
    return q


def present_revision(q):
    """Keep partial edits and the retained base in the same bound contract."""
    contract = q.get('name_contract')
    if not contract or q.get('proposal_base') is None or not contract['nested']:
        return q
    from regrow.prompts.response_example import guide
    wrapped = 'proposal' in q['response_schema'].get('properties', {})
    original = q.get('original_request', {})
    field = '在 proposal 内' if wrapped else ''
    part = {'path': '纠错/具名对象修订', 'text': '# 修订对象\n' + field
            + '按本轮格式提交要修订的对象。已有对象用 ref，原稿中的新对象用其登记名称。'
            + '控件放在所属区块的 controls 内。未提到的对象及字段保留。撤回对象时提供其引用、remove 和 reason。'
            + '撤掉误填字段时用 remove_fields 指明。current_regions 和 jump_to 在提交时整体替换。'}
    fmt = {'path': '纠错/具名格式', 'text': guide(q['response_schema'])}
    q['fixed_parts'] = [*q.get('fixed_parts', []), part, fmt]
    q['system_prompt'] = '\n\n'.join(p['text'] for p in q['fixed_parts'])
    if not q.get('_correction_context'):
        base = encode_reply(q['proposal_base'], contract)
        q['user_prompt'] = original.get('user_prompt', '') + '\n\n本次合并基准\n' + json.dumps(base, ensure_ascii=False)
    return q


def render(request):
    """Display disclosed references beside prose without rewriting rendered JSON."""
    q = deepcopy(request)
    contract = q.get('name_contract')
    if not contract:
        return q
    from regrow.prompts.history_disclosure import replace_presentation
    if q.get('role') == 'object_registration' and not q.get('_correction_context'):
        from regrow.prompts.prompt_material import body
        material, suffix = body(q)
        paths = contract['paths']
        for row in material.get('待补齐对象', []):
            row['path'] = paths.get(row['path'], row['path'])
            if row.get('ref') in contract['names']:
                row['ref'] = contract['names'][row['ref']]
        replace_presentation(q, json.dumps(material, ensure_ascii=False, indent=2) + suffix)
        return q
    feedback = q.get('_correction_context')
    shown = feedback['context'] if feedback else q.get('user_prompt', '')
    labels = [label for label in contract['names'].values() if label not in shown]
    if labels:
        material = shown + '\n\n## 本轮已有对象引用\n' + '、'.join(labels)
        if feedback:
            feedback['context'] = material
        else:
            replace_presentation(q, material)
    return q


def continuation_schema(request):
    """Select the next Action contract from the call that supplied that Action."""
    from regrow.runtime.model_transport import expand_schema

    def find(schema):
        spec = schema.get('properties', {}).get('next_action')
        if spec is not None:
            return spec
        for key in ('anyOf', 'oneOf'):
            for branch in schema.get(key, []):
                spec = find(branch)
                if spec is not None:
                    return spec
        return None

    schema = expand_schema(request['response_schema'])
    if 'proposal' in schema.get('properties', {}):
        schema = schema['properties']['proposal']
    return find(schema)


def internal_request(request, reply=None):
    q=deepcopy(request);c=q.pop('name_contract',None)
    if c:
        q['response_schema']=c['schema']
        q['named_nested']=c['nested']
        q['sent_name_contract'] = {key: deepcopy(c[key])
                                   for key in ('names', 'owners', 'paths', 'typed_fields', 'aliases') if key in c}
        if c.get('paths'):
            q['registration_path_names'] = c['paths']
        continuation = continuation_schema(request)
        if continuation is not None:
            q['next_action_wire_schema'] = continuation
        if not c.get('typed_fields') and c.get('control_reference_style') == 'id_name':
            q['control_reference_style'] = 'id_name'
            q['control_reference_names'] = {ref: name for ref, name in c['names'].items()
                                            if re.fullmatch(r'c\d+', ref)}
        if not c.get('typed_fields') and c.get('region_reference_style') == 'id_name':
            q['region_reference_style'] = 'id_name'
            q['region_reference_names'] = {ref: name for ref, name in c['names'].items()
                                           if re.fullmatch(r'r\d+', ref)}
        if reply is not None:
            hints = display_regions(request, reply)
            if hints:
                q['display_regions'] = hints
    return q


def _decode_references(value, aliases, key=None, path=(), *, control_labels=None, region_labels=None, new_controls=()):
    if key == 'target' and 'new_tasks' in path:
        return deepcopy(value)
    if key == 'task_update' and isinstance(value, dict):
        from regrow.records.task_updates import is_batch
        if is_batch(value):
            updates = {}
            for label, row in value.items():
                ref = aliases.get(label) or label
                if ref in updates:
                    reject('task_update_reference', ref, label, '同一道任务只使用一个完整引用',
                           field='任务更新引用', reason='不同键指向同一道任务。')
                updates[ref] = deepcopy(row)
            return updates
    if isinstance(value,str) and (key in REFERENCE_FIELDS or key=='function_refs'):
        if 'function_updates' in path:
            if key in ('region', 'supports', 'access_entry') and value in {**(control_labels or {}), **(region_labels or {})}:
                return value
            if key in ('parameters', 'constraints') and value.partition('/')[0] in (control_labels or {}):
                return value
        if key == 'control' and 'new_tasks' in path and value in new_controls:
            return value
        function_ref=(key=='function_refs' or ('function_updates' in path and key in ('ref','replace_with')))
        if (function_ref or key in ('parameters', 'constraints', 'task')) and value in aliases:
            return aliases[value]
        if control_labels is not None:
            from regrow.recognition.control_references import resolve_label
            resolved = resolve_label(value, control_labels, allow_path=function_ref or key in ('parameters', 'constraints'))
            if resolved is not None:
                return resolved
        if region_labels is not None and not function_ref and key not in ('parameters', 'constraints', 'task'):
            from regrow.recognition.control_references import resolve_label
            resolved = resolve_label(value, region_labels, prefix='r')
            if resolved is not None:
                return resolved
        resolved=value if function_ref else resolve(value,aliases)
        if resolved!=value:return resolved
        for pos in reversed([i for i,ch in enumerate(value) if ch=='/']):
            prefix=value[:pos]; bound=resolve(prefix,aliases)
            if bound!=prefix and isinstance(bound,str):return bound+value[pos:]
        return value
    if isinstance(value,list):return [_decode_references(v,aliases,key,path,control_labels=control_labels,region_labels=region_labels,new_controls=new_controls) for v in value]
    if isinstance(value,dict):return {k:_decode_references(v,aliases,k,(*path,k),control_labels=control_labels,region_labels=region_labels,new_controls=new_controls) for k,v in value.items()}
    return value


def decode(request, reply):
    contract=request.get('name_contract')
    if not contract:return deepcopy(reply)
    from regrow.records.object_knowledge import control_only
    # A next Action is interpreted after this update's objects are accepted.
    # Its malformed subtree cannot prevent the main observation from decoding.
    from regrow.runtime.update_reply import main_pair
    _, main = main_pair(request['response_schema'], reply)
    typed = contract.get('typed_fields')
    if typed:
        value = reference_fields.translate(main, contract)
    else:
        new_names = {c['name'] for r in main.get('regions', []) if isinstance(r, dict)
                     and isinstance(r.get('controls', []), list) for c in r.get('controls', [])
                     if isinstance(c, dict) and isinstance(c.get('name'), str) and not c.get('ref')}
        controls = ({ref: name for ref, name in contract['names'].items() if re.fullmatch(r'c\d+', ref)}
                    if contract.get('control_reference_style') == 'id_name' else None)
        regions = ({ref: name for ref, name in contract['names'].items() if re.fullmatch(r'r\d+', ref)}
                   if contract.get('region_reference_style') == 'id_name' else None)
        value = _decode_references(main, contract['aliases'], control_labels=controls,
                                   region_labels=regions, new_controls=new_names)
    if typed and isinstance(value.get('proposal'), dict):
        proposal = dict(value['proposal'])
        if isinstance(reply.get('proposal'), dict) and 'next_action' in reply['proposal']:
            proposal['next_action'] = deepcopy(reply['proposal']['next_action'])
        return {**value, 'proposal': _decode_objects(request, proposal, reply['proposal'])}
    if main is not reply and 'next_action' in reply:
        value['next_action'] = deepcopy(reply['next_action'])
    if not typed:
        if (isinstance(reply.get('proposal'), dict) and isinstance(main.get('proposal'), dict)
                and 'next_action' in reply['proposal'] and 'next_action' not in main['proposal']):
            value['proposal']['next_action'] = deepcopy(reply['proposal']['next_action'])
        original = request.get('original_request', request)
        edit = value.get('record_edit')
        if original.get('done_task_review') and isinstance(edit, dict) and edit.get('field') == 'reopen_task':
            edit['before'] = resolve(edit.get('before'), contract['aliases'])
            task_name = original['done_task_review']['task']
            if contract['aliases'].get(reply['record_edit'].get('task'), reply['record_edit'].get('task')) == task_name:
                edit['task'] = task_name
    return _decode_objects(request, value, reply)


def _decode_objects(request, value, reply):
    contract = request['name_contract']
    from regrow.records.object_knowledge import control_only
    from regrow.records.object_supplements import combine
    value, omitted_controls = combine(value, contract['names'])
    if not contract['nested']:return value
    regions_value = value.get('regions', [])
    if not isinstance(regions_value, list) or any(
            not isinstance(row, dict) or not isinstance(row.get('controls', []), list)
            or any(not isinstance(control, dict) for control in row.get('controls', []))
            for row in regions_value):
        reject('object_format', '本次区块及控件', regions_value, '区块和控件条目均须为对象列表',
               path='/regions', field='区块及控件')
    if not contract.get('typed_fields'):
        new_names = {c['name'] for r in reply.get('regions', []) if isinstance(r, dict)
                     and isinstance(r.get('controls', []), list) for c in r.get('controls', [])
                     if isinstance(c, dict) and isinstance(c.get('name'), str) and not c.get('ref')}
        for raw, operation in zip(reply.get('new_tasks', []), value.get('new_tasks', [])):
            label = raw.get('control') if isinstance(raw, dict) else None
            if isinstance(label, str) and label in new_names and isinstance(operation, dict):
                operation['control'] = label
    rows=value.get('regions',[]);base=contract.get('base')
    regions=[];controls=[];indexes=[]
    from regrow.recognition.update_visibility import selected_indices
    selected = selected_indices(value)
    for position, row in enumerate(rows):
        if not isinstance(row,dict):
            reject('object_format', '本次登记的区块条目', row, '对象', field='区块条目',
                   reason='区块列表中提交了非对象内容。')
        if not isinstance(row.get('controls',[]),list):
            reject('object_format', str(_key(row)), row.get('controls'), '控件列表', field='控件',
                   reason='该区块的 controls 需要填写列表，不能填写 null 或其他类型。')
        region={k:v for k,v in row.items() if k not in ('controls','current')}
        if ((contract['current'] or 'current_regions' in value) and row.get('ref') and set(row) <= {'ref', 'controls', 'current'}
                and (row.get('current') is not True if contract['current'] else position not in selected) and row.get('controls')
                and all(control_only(c) for c in row['controls'])):
            # A container used only to show global knowledge is itself a
            # no-op knowledge reference, not a newly observed Region.
            region['local_knowledge'] = {}
        match=None
        if base:
            matches=[i for i,r in enumerate(base.get('regions',[])) if
                     (row.get('ref') and row['ref']==r.get('ref')) or
                     (row.get('name') and row['name']==r.get('name')) or
                     (row.get('ref') and row['ref']==r.get('name'))]
            if len(matches)==1:match=matches[0]
            if match is not None:
                region['candidate_index']=match
                if not base['regions'][match].get('ref'):region.pop('ref',None)
        index=match if match is not None else len(base.get('regions',[]))+sum(i>=len(base.get('regions',[])) for i in indexes) if base else len(regions)
        if region.get('remove') and match is not None:
            region={k:region[k] for k in ('candidate_index','remove','reason') if k in region}
        indexes.append(index);regions.append(region)
    references={}
    for i,r in enumerate(rows):
        for name in (r.get('name'),r.get('ref'),contract['names'].get(r.get('ref'))):
            if name:
                if name in references and references[name]!=indexes[i]:references[name]=None
                else:references[name]=indexes[i]
    if base:
        for i,r in enumerate(base.get('regions',[])):
            for name in (r.get('name'),r.get('ref'),contract['names'].get(r.get('ref'))):
                if name and name not in references:references[name]=i
    for i,row in enumerate(rows):
        for j, c in enumerate(row.get('controls',[])):
            if ('regions', i, 'controls', j) in omitted_controls:
                continue
            if not isinstance(c,dict):
                reject('object_format', str(_key(row)), c, '控件对象', field='控件条目',
                       reason='该区块的控件列表中提交了非对象内容。')
            c=deepcopy(c)
            if not control_only(c):c['region_index']=indexes[i]
            if base:
                matches=[j for j,old in enumerate(base.get('controls',[])) if
                         (c.get('ref') and c['ref']==old.get('ref')) or
                         (old.get('region_index')==indexes[i] and _key(c)==_key(old)) or
                         (old.get('region_index')==indexes[i] and c.get('ref')==old.get('name'))]
                if len(matches)==1:
                    c['candidate_index']=matches[0]
                    old=base['controls'][matches[0]]
                    if not old.get('ref'):c.pop('ref',None)
                    effective={k:v for k,v in old.items() if k not in (*c.get('remove_fields',[]),'region_index')}
                    effective.update({k:v for k,v in c.items() if k not in ('candidate_index','remove_fields','region_index')})
                    if control_only(effective) and 'region_index' in old:
                        c.pop('region_index',None)
                        c.setdefault('remove_fields',[]).append('region_index')
            if c.get('remove') and 'candidate_index' in c:
                c={k:c[k] for k in ('candidate_index','remove','reason') if k in c}
            controls.append(c)
    value['regions']=regions
    if not base or any('controls' in r for r in rows):value['controls']=controls
    if contract['current'] and (not base or any('current' in r or r.get('remove') for r in rows)):
        members=deepcopy(base.get('current_regions',[])) if base else []
        for i,row in enumerate(rows):
            if not base or 'current' in row or row.get('remove'):
                members=[m for m in members if m.get('region_index')!=indexes[i] and not (row.get('ref') and m.get('ref')==row['ref'])]
                if row.get('current') is True and not row.get('remove'):members.append({'region_index':indexes[i]})
        value['current_regions']=members
    for member in value.get('current_regions', []):
        ref = member.get('ref')
        if ref and ref not in contract['names']:
            index = references.get(ref) if contract.get('typed_fields') else resolve(ref, references)
            if type(index) is not int:
                reject('current_region_reference', str(ref),
                       {'当前前景引用': ref, '本次登记区块': [_key(r) for r in rows]},
                       '本轮提供的已有区块引用或本次登记的唯一区块名称', field='当前前景区块',
                       reason='当前前景引用未能唯一对应一个区块，请核对名称。')
            member.clear()
            member['region_index'] = index
    planned=deepcopy(base.get('controls',[])) if base else []
    for c in controls:
        ci=c.get('candidate_index')
        if type(ci) is int:
            merged={k:v for k,v in planned[ci].items() if k not in c.get('remove_fields',[])}
            merged.update({k:v for k,v in c.items() if k not in ('candidate_index','remove_fields')})
            planned[ci]=merged
        else:planned.append(c)
    direct_routes = any('region' in props.get('jump_to', {}).get('items', {}).get('properties', {})
                        for props in _output_objects(contract['schema']))
    for route_number, route in enumerate(value.get('jump_to',[]) if not direct_routes else []):
        if 'region' in route:
            name = route.pop('region')
            route['region_index'] = references.get(name, name) if contract.get('typed_fields') else resolve(name, references)
        if 'control' in route:
            name=route.pop('control')
            raw_name=reply.get('jump_to',[])[route_number].get('control',name)
            ri=route.get('region_index')
            matches=[i for i,c in enumerate(planned) if not c.get('remove') and c.get('region_index')==ri
                     and (_key(c)==name or c.get('name') in (name,raw_name))]
            if not matches and name in contract['names'] and re.fullmatch(r'c[0-9]+',name):
                # An explicit named destination may refer to a disclosed stored
                # control without repeating its observation. Reuse its identity
                # through a knowledge-only reference; never manufacture a sighting.
                known=[i for i,c in enumerate(planned) if not c.get('remove') and c.get('ref')==name and control_only(c)]
                if len(known)==1:
                    matches=known
                elif not known:
                    carrier={'ref':name,'knowledge':[]}
                    matches=[len(planned)]
                    controls.append(carrier);planned.append(carrier)
                    value['controls']=controls
            route['control_index']=matches[0] if len(matches)==1 else name
    return value


def normalize_reply(schema, reply):
    """Canonicalize only values admitted by this wire field, preserving raw JSON."""
    if not isinstance(schema,dict):return deepcopy(reply)
    if isinstance(reply,str) and schema.get('enum'):
        allowed={v:v for v in schema['enum'] if isinstance(v,str)}
        if any(re.match(r'^[cr]\d+/', value) for value in allowed):
            return reply
        return resolve(reply,allowed)
    if isinstance(reply,list):return [normalize_reply(schema.get('items',{}),v) for v in reply]
    if isinstance(reply,dict):
        props=dict(schema.get('properties',{}))
        for kind in ('anyOf','oneOf','allOf'):
            for branch in schema.get(kind,[]):props.update(branch.get('properties',{}))
        return {k:normalize_reply(props.get(k,{}),v) for k,v in reply.items()}
    return deepcopy(reply)
