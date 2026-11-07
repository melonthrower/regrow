"""One incremental function directory; tasks link to purposes, not another backlog."""
from copy import deepcopy
from regrow.records.object_store import owned_controls, owned_tasks
from regrow.records.control_knowledge import parameter_facts, evidence
from regrow.records.diagnostics import reject


def schema(regions=None):
    string = {'type': 'string', 'minLength': 1}
    strings = {'type': 'array', 'items': string, 'uniqueItems': True}
    def obj(props, required=()):
        return {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False}
    fields = {k: deepcopy(string) for k in ('name', 'description')}
    fields.update(supports={'type': 'array', 'minItems': 1, 'uniqueItems': True,
                           'items': string},
                  constraints=deepcopy(strings),
                  target_role=deepcopy(string), access_entry=deepcopy(string))
    changes = deepcopy(fields)
    for key in ('target_role', 'access_entry'):
        changes[key] = {'anyOf': [deepcopy(string), {'type': 'null'}]}
    region = deepcopy(string)
    if regions is not None:
        region['enum'] = list(regions)
    return {'type': 'array', 'items': obj({
        'region': region,
        'add': {'type': 'array', 'items': obj(fields, ('name','description','supports'))},
        'update': {'type': 'array', 'items': obj({'ref': string, 'changes': obj(changes)}, ('ref','changes'))},
        'remove': {'type': 'array', 'items': obj({'ref': string, 'replace_with': string}, ('ref',))},
    }, ('region',))}


def reference(rid, name):
    return rid + '/' + name


def resolve(records, value, owner):
    """Names are local; cross-Region associations must use the provided full ref."""
    if value in records[owner].get('functions', {}):
        return reference(owner, value)
    rid, sep, name = value.partition('/')
    if sep and name in records.get(rid, {}).get('functions', {}):
        return value
    reject('function_reference', value, value,
           [reference(owner, name) for name in records[owner].get('functions', {})],
           field='功能引用', reason='填写的功能引用没有对应到已登记功能。',
           repair='已有功能使用其提供的引用；尚未登记的功能使用新增，不以更新替代新增。')


def task_refs(records, owner, refs):
    return list(dict.fromkeys(resolve(records, value, owner) for value in refs))


def catalog(region):
    return {cid + '/' + key: {**deepcopy(fact), 'support': cid, 'region': region['id'], 'control': cid}
            for cid,c in owned_controls(region).items() for key,fact in parameter_facts(c).items()}


def support_rows(region, values, source=None):
    from regrow.records.object_store import observation_history
    call = (source or {}).get('source_call')
    result = []
    for value in values:
        if value == region['id']:
            if not region.get('local_knowledge'):
                reject('function_support_knowledge', region['name'],
                       {'支持对象': value, '区块知识': region.get('local_knowledge')},
                       '支持区块已有与功能相关的用途知识', field='功能支持对象',
                       reason='区块引用有效，但该区块没有可支持功能的用途知识。',
                       repair='有观察依据时补充区块知识，否则撤回无依据的功能支持。')
            result.append({'kind':'region','region':region['id'],'control':None,'name':region['name']})
            continue
        controls = owned_controls(region)
        cid = value if value in controls else None
        if cid is None and call:
            # New objects receive IDs only during this publication. Resolve
            # their declared names against this call's accepted objects only.
            matches = [key for key, control in controls.items()
                       if control.get('name') == value and any(
                           event.get('evidence', {}).get('source_call') == call
                           for event in observation_history(control))]
            if len(matches) == 1:
                cid = matches[0]
        if cid is None:
            reject('function_support_reference', region['name'],
                   {'填写的支持对象': value, '本区块控件': {k: c['name'] for k,c in controls.items()}},
                   '本区块已登记控件的引用或本区块引用', field='功能支持对象',
                   reason='填写的支持引用没有对应到该区块中的对象。')
        if not controls[cid].get('knowledge'):
            reject('function_support_knowledge', region['name'] + '中的' + controls[cid]['name'],
                   {'支持对象': cid, '控件知识': controls[cid].get('knowledge')},
                   '支持控件已有与功能相关的用途知识', field='功能支持对象',
                   reason='控件引用有效，但该控件没有可支持功能的用途知识。',
                   repair='有观察依据时补充控件知识，否则撤回无依据的功能支持。')
        c = controls[cid]
        result.append({'kind':'control','region':region['id'],'control':cid,'name':c['name'],'source':evidence(c)})
    if not result:
        reject('function_support_empty', region['name'], values,
               '至少一项本区块已有用途知识作为功能支持', field='功能支持对象',
               reason='本次功能没有任何知识支持对象。')
    return result


def _rewrite_refs(records, old, new):
    for region in records.values():
        for task in owned_tasks(region).values():
            if old in task.get('function_refs', []):
                task['function_refs'] = list(dict.fromkeys(
                    new if ref == old else ref for ref in task['function_refs'] if ref != old or new is not None))


def apply(records, updates, source, allowed_regions=None):
    """Called in the normal publication transaction, after object knowledge edits."""
    import jsonschema
    updates = deepcopy(updates)
    for group in updates:
        for row in group.get('remove', []):
            row.pop('reason', None)  # Old accepted requests may still carry it.
    jsonschema.validate(updates, schema(allowed_regions))
    for group in updates:
        rid = group['region']
        if rid not in records:
            reject('function_owner', rid, rid, '已登记的功能所属区块', field='功能所属区块',
                   reason='填写的功能所属区块尚未登记。')
        region = records[rid]; directory = region.setdefault('functions', {})
        for row in group.get('add', []):
            name = row['name'].strip()
            if name in directory:
                reject('function_duplicate', region['name'] + '的' + name, row,
                       '新增功能名称与已有功能不同；已有功能通过原引用更新', field='新增功能',
                       reason='该区块已经登记了同名功能。')
            _store(region, name, row, source)
        for row in group.get('update', []):
            ref = resolve(records, row['ref'], rid)
            if not ref.startswith(rid + '/'):
                reject('function_owner', row['ref'], {'功能引用': ref, '填写的区块': region['name']},
                       '被更新功能属于指定区块', field='功能更新', reason='更新的功能不属于填写的区块。')
            old = ref[len(rid)+1:]; changes = row['changes']; name = changes.get('name', old).strip()
            if name != old and name in directory:
                reject('function_duplicate', region['name'] + '的' + old, {'新名称': name, '已有功能': list(directory)},
                       '新名称不覆盖其他已有功能', field='功能名称',
                       reason='改名后的目标功能已经存在；合并需要使用删除时的替换引用。')
            previous = deepcopy(directory[old]); _store(region, name, changes, source, previous)
            if name != old:
                del directory[old]; _rewrite_refs(records, ref, reference(rid,name))
        for row in group.get('remove', []):
            ref = resolve(records,row['ref'],rid)
            if not ref.startswith(rid+'/'):
                reject('function_owner', row['ref'], {'功能引用': ref, '填写的区块': region['name']},
                       '被删除功能属于指定区块', field='删除功能', reason='删除的功能不属于填写的区块。')
            replacement = resolve(records,row['replace_with'],rid) if row.get('replace_with') else None
            if replacement == ref:
                reject('function_self_merge', row['ref'], {'删除的功能': ref, '替换为': replacement},
                       '合并的来源与目标为不同功能', field='功能合并', reason='合并目标与被删除功能是同一个对象。')
            del directory[ref[len(rid)+1:]]; _rewrite_refs(records, ref, replacement)
    for region in records.values():
        for task in owned_tasks(region).values():
            for ref in task.get('function_refs', []):
                resolve(records,ref,region['id'])


def description(function):
    parts = [function.get('description', '')]
    for key, label in [('object', '作用对象'), ('completion', '完成效果'), ('unconfirmed', '尚未确认')]:
        value = function.get(key)
        values = value if isinstance(value, list) else [value] if value else []
        for text in values:
            if text and not any(text in part for part in parts):
                parts.append(label + '：' + text)
    return '；'.join(part for part in parts if part)


def parameter_references(region, values, supports, source):
    """Bind same-call named parameters after their controls have received IDs."""
    from regrow.records.object_store import observation_history
    facts = catalog(region)
    controls = {row.get('control') for row in supports}
    call = (source or {}).get('source_call')
    result = []
    for value in values:
        ref = value
        if ref not in facts and call:
            matches = [key for key, fact in facts.items()
                       if fact['control'] in controls
                       and value == owned_controls(region)[fact['control']]['name'] + '/' + key.split('/', 1)[1]
                       and any(event.get('evidence', {}).get('source_call') == call
                               for event in observation_history(owned_controls(region)[fact['control']]))]
            if len(matches) == 1:
                ref = matches[0]
        result.append(ref)
    return result


def _store(region, name, fields, source, previous=None):
    row = deepcopy(previous or {})
    if previous:
        row['description'] = description(previous)
    for key in ('object', 'completion', 'unconfirmed'):
        row.pop(key, None)
    for key in ('description',):
        if key in fields:
            row[key] = deepcopy(fields[key])
    if not name or not row.get('description','').strip():
        reject('function_description', name or region['name'],
               {'功能名称': name, '用途说明': row.get('description')}, '非空的功能名称和用途说明',
               field='功能名称与用途', reason='功能名称或用途说明为空。')
    if 'supports' in fields:
        row['support_controls'] = support_rows(region,fields['supports'],source)
    elif not row.get('support_controls'):
        reject('function_support_missing', name, row.get('support_controls'),
               '首次更新时给出功能所依赖的对象知识支持', field='功能支持对象',
               reason='旧功能尚无知识支持，本次更新也没有给出支持对象。')
    for key in ('target_role', 'access_entry'):
        if key in fields:
            if fields[key] is None:
                row.pop(key, None)
            else:
                row[key] = fields[key]
    if row.get('access_entry'):
        entry = support_rows(region, [row['access_entry']], source)[0].get('control')
        if entry is None or entry not in {s.get('control') for s in row['support_controls']}:
            reject('function_access_entry', name,
                   {'填写的独立入口': row['access_entry'], '功能支持控件': [s.get('control') for s in row['support_controls']]},
                   '独立入口为本功能支持对象中的实际控件', field='功能独立入口',
                   reason='独立入口没有对应到本功能的实际支持控件。')
        row['access_entry'] = entry
    facts = catalog(region)
    constraints = parameter_references(region, fields.get('constraints', row.get('constraints', {})), row['support_controls'], source)
    controls = {s.get('control') for s in row['support_controls']}
    for ref in constraints:
        if ref not in facts or facts[ref]['control'] not in controls:
            reject('function_parameter_reference', name, ref,
                   [k for k,v in facts.items() if v['control'] in controls], field='功能参数引用',
                   reason='填写内容没有对应到本功能支持对象的参数引用。',
                   repair='使用已有参数引用；规则正文归来源对象知识，没有参数引用时省略 constraints。')
    row['constraints'] = {ref: {'ref':ref, 'region':region['id'], 'control':facts[ref]['control']}
                          for ref in constraints}
    row.setdefault('constraints',{})
    row.update(region=region['id'],source_call=source.get('source_call'), support_tasks=[],task_refs=[])
    row['locations'] = [{'region':s['region'],'control':s.get('control')} for s in row['support_controls']]
    region['functions'][name] = row


def resolved_constraints(region, function):
    """Project current parameter facts without replacing persisted references."""
    facts = catalog(region)
    return {key: deepcopy(facts.get(key, value))
            for key, value in function.get('constraints', {}).items()}


def view(records, rid, refs=None):
    region=records[rid]; rows=[]
    for name,f in region.get('functions',{}).items():
        ref=reference(rid,name)
        if refs is not None and ref not in refs:continue
        item={'功能':name,'引用':ref,'用途':description(f)}
        item['支持对象']=[s.get('name',s.get('control') or rid) for s in f.get('support_controls',[])]
        constraints=resolved_constraints(region, f)
        if constraints:item['参数知识引用']=constraints
        if f.get('target_role'):item['预期目标职责']=f['target_role']
        if f.get('access_entry'):item['独立入口']=f['access_entry']
        rows.append(item)
    return rows


def apply_for_request(records, request, reply, source):
    """Apply offered edits; an omitted/empty increment does not inspect old refs."""
    def offered(node):
        if isinstance(node, dict):
            return ('function_updates' in node.get('properties', {}) or
                    any(offered(child) for child in node.values()))
        return isinstance(node, list) and any(offered(child) for child in node)
    if reply.get('function_updates') and offered(request.get('response_schema', {})):
        apply(records, reply.get('function_updates', []), source,
              request.get('function_update_regions'))
