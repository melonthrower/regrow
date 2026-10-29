"""One incremental function directory; tasks link to purposes, not another backlog."""
from copy import deepcopy
from regrow.records.object_store import owned_controls, owned_tasks
from regrow.records.control_knowledge import parameter_facts, evidence


def schema(regions=None):
    string = {'type': 'string', 'minLength': 1}
    strings = {'type': 'array', 'items': string, 'uniqueItems': True}
    def obj(props, required=()):
        return {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False}
    fields = {k: deepcopy(string) for k in ('name', 'description')}
    fields.update(supports={'type': 'array', 'minItems': 1, 'uniqueItems': True,
                           'items': {'anyOf': [string, {'type': 'integer', 'minimum': 0}]}},
                  constraints=deepcopy(strings))
    region = deepcopy(string)
    if regions is not None:
        region['enum'] = list(regions)
    return {'type': 'array', 'items': obj({
        'region': region,
        'add': {'type': 'array', 'items': obj(fields, ('name','description','supports'))},
        'update': {'type': 'array', 'items': obj({'ref': string, 'changes': obj(fields)}, ('ref','changes'))},
        'remove': {'type': 'array', 'items': obj({'ref': string, 'reason': string, 'replace_with': string}, ('ref','reason'))},
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
    raise ValueError('功能引用未登记或不明确：' + value)


def task_refs(records, owner, refs):
    return list(dict.fromkeys(resolve(records, value, owner) for value in refs))


def catalog(region):
    return {cid + '/' + key: {**deepcopy(fact), 'support': cid, 'region': region['id'], 'control': cid}
            for cid,c in owned_controls(region).items() for key,fact in parameter_facts(c).items()}


def support_rows(region, values):
    result = []
    for value in values:
        if value == region['id']:
            if not region.get('local_knowledge'):
                raise ValueError('区块「' + region['name'] + '」引用有效，但缺少区块用途知识；有观察依据时补充local_knowledge，否则撤回无依据的功能支持。')
            result.append({'kind':'region','region':region['id'],'control':None,'name':region['name']})
            continue
        controls = owned_controls(region)
        cid = value if value in controls else next((k for k,c in controls.items()
                      if c['name'] == value and sum(c2['name']==value for c2 in controls.values()) == 1), None)
        if cid is None:
            available = '、'.join(c['name'] + '（' + k + '）' for k,c in controls.items())
            raise ValueError('区块「' + region['name'] + '」的功能支持引用无法对应本区块对象：' + str(value) + '。请使用给定控件index或本区块引用，不拼接区块与控件引用。本区块控件：' + available + '。这不是缺少用途知识的诊断。')
        if not controls[cid].get('knowledge'):
            raise ValueError('区块「' + region['name'] + '」的「' + controls[cid]['name'] + '」缺少用途知识；有观察依据时在同次回复补充knowledge，否则撤回无依据的功能支持。')
        c = controls[cid]
        result.append({'kind':'control','region':region['id'],'control':cid,'name':c['name'],'source':evidence(c)})
    if not result:
        raise ValueError('新增功能至少需要一项本区块已有用途知识作为支持')
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
    jsonschema.validate(updates, schema(allowed_regions))
    for group in updates:
        rid = group['region']
        if rid not in records:
            raise ValueError('功能所属区块尚未登记：' + rid)
        region = records[rid]; directory = region.setdefault('functions', {})
        for row in group.get('add', []):
            name = row['name'].strip()
            if name in directory:
                raise ValueError('功能「'+name+'」已存在，请引用原功能增量更新')
            _store(region, name, row, source)
        for row in group.get('update', []):
            ref = resolve(records, row['ref'], rid)
            if not ref.startswith(rid + '/'):
                raise ValueError('功能更新引用必须属于指定区块')
            old = ref[len(rid)+1:]; changes = row['changes']; name = changes.get('name', old).strip()
            if name != old and name in directory:
                raise ValueError('目标功能已存在；合并请用remove.replace_with，不覆盖已有功能')
            previous = deepcopy(directory[old]); _store(region, name, changes, source, previous)
            if name != old:
                del directory[old]; _rewrite_refs(records, ref, reference(rid,name))
        for row in group.get('remove', []):
            ref = resolve(records,row['ref'],rid)
            if not ref.startswith(rid+'/'):
                raise ValueError('删除功能必须属于指定区块')
            replacement = resolve(records,row['replace_with'],rid) if row.get('replace_with') else None
            if replacement == ref:
                raise ValueError('功能不能合并到自身')
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
        raise ValueError('功能名称和用途说明不能为空')
    if 'supports' in fields:
        row['support_controls'] = support_rows(region,fields['supports'])
    elif not row.get('support_controls'):
        raise ValueError('首次更新旧功能时请明确它的对象知识支持')
    facts = catalog(region)
    constraints = fields.get('constraints', row.get('constraints', {}))
    controls = {s.get('control') for s in row['support_controls']}
    for ref in constraints:
        if ref not in facts or facts[ref]['control'] not in controls:
            raise ValueError('功能「'+name+'」的constraints应填写参数引用，不是观察或规则句子。实际填写：'+ref+'。本功能支持对象可用参数引用：'+('、'.join(k for k,v in facts.items() if v['control'] in controls) or '无；没有参数引用时省略constraints')+'。规则正文归来源对象knowledge。')
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
        rows.append(item)
    return rows


def attach(request, records, region_ids, task=None, *, refs=None):
    """Expose only the selected Region directory or the current task's linked purposes."""
    from regrow.prompts.prompt_material import assign
    ids=list(dict.fromkeys(rid for rid in region_ids if rid in records))
    request['function_update_regions']=ids
    request['response_schema']['properties']['function_updates']=schema(ids)
    rows=[]
    for rid in ids:
        rows.extend(view(records, rid, refs))
    values={'可更新功能的区块':[{'名称':records[rid]['name'],'ref':rid} for rid in ids]}
    if rows:values['已有功能轮廓']=rows
    if refs is not None:
        directory = [{'功能': name, '引用': reference(rid, name)}
                     for rid in ids for name in records[rid].get('functions', {})
                     if reference(rid, name) not in refs]
        if directory:
            values['其他已有功能（仅目录）'] = directory
    assign(request,values,remove=('已有功能轮廓', '其他已有功能（仅目录）'))
    return request
