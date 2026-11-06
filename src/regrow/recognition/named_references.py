"""Readable call-local references; storage identities and registration stay canonical.

The wire reply is immutable. Only an explicit derived reply flattens nested
observations and resolves names within the objects disclosed by this request.
"""
from copy import deepcopy
from collections import Counter
import json
import re
import unicodedata

TOKEN = re.compile(r'(?<![A-Za-z0-9_])[rc]\d+(?![A-Za-z0-9_])')
REFERENCE_FIELDS = {'ref','target','control','region','source_region','source_control',
                    'task','supports','constraints','access_entry','replace_with','candidate','path','parent'}


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


def text(value, names):
    if isinstance(value, str):
        def display(match):
            name = names.get(match[0], match[0])
            if name.startswith(match[0] + '/') and value[match.end():].startswith('/'):
                return match[0]
            return name
        return TOKEN.sub(display, value)
    if isinstance(value, list):
        return [text(v, names) for v in value]
    if isinstance(value, dict):
        # The function directory has its own ID and parameter-reference fields.
        return {k: deepcopy(v) if k == 'function_updates' else text(v, names) for k, v in value.items()}
    return value


def labels(run, request, *, id_name=True):
    from regrow.records.snapshots import load
    from regrow.records.object_store import owned_controls
    try:
        _, records, _ = load(run)
    except (OSError, ValueError):
        records = {}
    material = json.dumps({k: request.get(k) for k in ('user_prompt','response_schema','control_refs',
                          'region_names','discovery_context','backend_candidates')}, ensure_ascii=False)
    ids = set(TOKEN.findall(material))
    names = {rid: rid + '/' + r['name'] if id_name else r['name'] for rid,r in records.items() if rid in ids}
    owners = {}
    from regrow.recognition.control_references import label
    for rid,r in records.items():
        for cid,c in owned_controls(r).items():
            if cid in ids:
                names[cid] = label(cid, c['name']) if id_name else c['name']
                owners.setdefault(cid, []).append(rid)
                names.setdefault(rid, rid + '/' + r['name'] if id_name else r['name'])
    counts = Counter(normalized(n) for n in names.values())
    for ref,name in list(names.items()):
        if counts[normalized(name)] > 1:
            if ref in owners:
                names[ref] = ' / '.join([records[owners[ref][0]]['name'], name])
            else:
                r = records[ref]
                names[ref] = name + '（' + r.get('description', '') + '）'
    # If even the supplied descriptions do not distinguish two objects, leave
    # both unresolved; never silently map a shared label to the last object.
    counts = Counter(names.values())
    names = {ref:name for ref,name in names.items() if counts[name] == 1}
    return names, _display_owners(run, request, owners)


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
    value = _decode_references(reply, contract['aliases'])
    if isinstance(value.get('proposal'), dict):
        value = value['proposal']
    from regrow.records.object_knowledge import control_only
    result = {}
    for row in value.get('regions', []):
        if not isinstance(row, dict) or row.get('ref') not in contract['names']:
            continue
        for control in row.get('controls', []):
            if isinstance(control, dict) and control_only(control):
                result.setdefault(control['ref'], row['ref'])
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


def wire_schema(schema, nested):
    s = deepcopy(schema)
    def item_schema(item):
        if 'properties' in item:return item
        props={}
        for branch in item.get('anyOf',[]):props.update(deepcopy(branch.get('properties',{})))
        props.pop('candidate_index',None)
        if 'remove_fields' in props:
            values=props['remove_fields'].get('items',{}).get('enum',[])
            props['remove_fields']['items']['enum']=['parent' if k == 'parent_index' else k
                for k in values if k not in ('region_index','candidate_index')]
        props['ref']={'type':'string','minLength':1}
        return {'type':'object','properties':props,'anyOf':[{'required':['ref']},{'required':['name']}],'additionalProperties':False}
    def visit(node):
        if isinstance(node, list):
            for child in node: visit(child)
        if not isinstance(node, dict): return
        if node.get('pattern') in ('^r[0-9]+$', '^c[0-9]+$'): node.pop('pattern')
        props = node.get('properties', {})
        if nested and 'regions' in props and 'controls' in props:
            region = item_schema(props['regions']['items']); props['regions']['items']=region
            control = item_schema(deepcopy(props['controls']['items']))
            _drop(control, {'region_index','candidate_index'})
            _drop(region, {'candidate_index'})
            region['properties']['controls'] = {'type':'array','items':control}
            if 'parent_index' in region['properties']:
                region['properties'].pop('parent_index')
                region['properties']['parent'] = {'type':['string','null'], 'minLength': 1}
                region['required'] = [k for k in region.get('required',[]) if k != 'parent_index']
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


def encode_objects(value, names, owners, *, current=False):
    """Present a canonical correction base without positional relationship work."""
    v = deepcopy(value)
    if not isinstance(v,dict) or 'regions' not in v or 'controls' not in v:
        return text(v,names)
    regions=v['regions']; selected=set()
    def reference(rows, index):
        # A rejected candidate may contain an unresolved name or bad position.
        # Keep that value visible for correction instead of indexing with it.
        return _key(rows[index]) if type(index) is int and 0 <= index < len(rows) else deepcopy(index)
    for r in v.get('current_regions',[]):
        if type(r.get('region_index')) is int: selected.add(r['region_index'])
        elif r.get('ref'):
            selected.update(i for i,row in enumerate(regions) if row.get('ref')==r['ref'])
    for i,row in enumerate(regions):
        row.pop('candidate_index',None)
        if current: row['current']=i in selected
        if 'parent_index' in row:
            row['parent']=reference(regions,row.pop('parent_index'))
    for c in v.pop('controls'):
        c.pop('candidate_index',None);i=c.pop('region_index',None)
        if i is None:
            locations = owners.get(c.get('ref'), [])
            locations = [locations] if isinstance(locations, str) else locations
            # The retained outer Region is preferred. Otherwise use a
            # display-only reference to a known member.
            # decode still strips this container for pure knowledge; it never
            # writes membership, visibility, observation or task ownership.
            rid = locations[0] if locations else None
            matches=[j for j,r in enumerate(regions) if rid and r.get('ref')==rid]
            if not matches and rid:
                regions.append({'ref':rid});matches=[len(regions)-1]
            if not matches:
                raise ValueError('无法确定知识修订控件的所属区块：'+str(c.get('ref')))
            # Duplicate rows can occur in a rejected reply. They still name
            # one owner; retain the rows for correction without rebinding it.
            i=matches[0]
        regions[i].setdefault('controls',[]).append(c)
    for row in v.get('jump_to',[]):
        if 'region_index' in row:
            row['region']=reference(regions,row.pop('region_index'))
        if 'control_index' in row:
            row['control']=reference(value['controls'],row.pop('control_index'))
    if current:  # Retained only for already-sent inline-current contracts.
        v.pop('current_regions',None)
    return text(v,names)


def prepare(run, request):
    """Select the wire contract before the normal field-section renderer runs."""
    q=deepcopy(request)
    if q.get('name_contract'): return q
    from regrow.runtime.model_transport import expand_schema
    schema=expand_schema(q['response_schema'])
    props=schema.get('properties',{})
    nested=('regions' in props and 'controls' in props and
            ('region_index' in json.dumps(props['controls']) or q.get('original_request',{}).get('named_nested')))
    names,owners=labels(run,q)
    if 'region_refs' in q:
        from regrow.recognition.control_references import _schemas
        q['region_refs'] = [ref for ref in q['region_refs'] if ref in names]
        for item in _schemas(schema, 'regions'):
            field = item.get('properties', {}).get('ref', {})
            if 'enum' in field:
                field['enum'] = [ref for ref in field['enum'] if ref in names]
    aliases={name:ref for ref,name in names.items()}
    # Task/function references are scoped compound names, also copied verbatim.
    def collect(node):
        if isinstance(node,dict):
            for value in node.get('enum',[]):
                if isinstance(value,str): aliases[text(value,names)]=value
            for child in node.values():collect(child)
        elif isinstance(node,list):
            for child in node:collect(child)
    collect(schema)
    paths={}
    if q.get('registration_paths'):
        material=json.JSONDecoder().raw_decode(q.get('dynamic_prompt') or q['user_prompt'])[0]
        for row in material.get('待补齐对象',[]):
            path=row['path'];label=row.get('名称') or row.get('name') or path
            if row.get('所属区块'):label=str(row['所属区块'])+' / '+label
            paths[path]=label
        if len(set(paths.values())) != len(paths):
            paths={p:p for p in paths}  # ambiguity stays explicit, never chooses an object
        aliases.update({name:path for path,name in paths.items()})
    contract={'schema':schema,'names':names,'aliases':aliases,'owners':owners,'nested':nested,
              'control_reference_style':'id_name', 'region_reference_style':'id_name',
              'current':False,'paths':paths}
    q['name_contract']=contract
    q['response_schema']=text(wire_schema(schema,nested),names)
    if paths:
        q['response_schema']=_replace_paths(q['response_schema'],paths)
    feedback = q.get('_correction_context')
    if feedback and q.get('named_nested') and nested:
        from regrow.prompts.correction_feedback import body
        issues = deepcopy(feedback['issues'])
        for row in issues if isinstance(issues, list) else []:
            if not isinstance(row, dict):
                continue
            location = str(row.get('所在字段', ''))
            if 'parent_index' in location:
                row['问题'] = ('父区块引用未能对应本次回复或修订基准中的唯一对象。'
                             '请补充该父区块引用，或依据实际包含关系修正。')
            for key in ('字段', '所在字段', '问题', '修正要求'):
                if isinstance(row.get(key), str):
                    for old, new in [('parent_index', '父区块'), ('region_index', '所属区块'),
                                     ('control_index', '目标控件'), ('candidate_index', '对象引用')]:
                        row[key] = row[key].replace(old, new)
        shown = encode_objects(feedback['reply'], names, owners, current=contract['current'])
        q['user_prompt'] = q['dynamic_prompt'] = body(feedback['context'], issues, shown, feedback['notes'])
        q['named_issue'] = json.dumps(issues, ensure_ascii=False, indent=2)
    if q.get('proposal_base') is not None and nested:
        contract['base']=deepcopy(q['proposal_base'])
    if q.get('proposal_base') is not None and nested:
        from regrow.prompts.correction_feedback import organize
        base=encode_objects(q['proposal_base'],names,owners,current=contract['current'])
        original=q.get('original_request',{})
        part={'path':'纠错/具名对象修订','text':'# 修订对象\n按原格式只提交要修订的对象；已有对象用ref，原稿新对象用其name。控件放在所属区块的controls内。未提到的对象和字段保留；撤回时填写ref或name、remove:true和reason。撤掉对象内误填字段时用remove_fields列出字段名，单纯省略仍会保留旧稿字段。current_regions和jump_to只有明确提交时整体替换。'}
        issue=q.get('named_issue') or re.split(r'# 本次补充材料|\n原任务与相关材料',q.get('user_prompt',''),maxsplit=1)[0]
        issue=issue.removeprefix('本次问题\n').removeprefix('# 本次问题\n').strip()
        if 'ref和knowledge' in issue or 'ref、knowledge' in issue:
            affected=set(TOKEN.findall(issue))
            for control in contract['base'].get('controls',[]):
                ref=control.get('ref');label=names.get(ref,ref)
                identified=ref in affected or bool(label and ('「'+label+'」' in issue or '"'+label+'"' in issue))
                if identified and ref and 'knowledge' in control:
                    fields=[k for k in control if k not in ('ref','knowledge','identity','name','_matched_id','region_index')]
                    if fields:issue+='\n控件「'+names.get(control['ref'],control['ref'])+'」旧稿还保留'+ '、'.join(fields)+'；仅补知识时，请明确提交 remove_fields: '+json.dumps(fields,ensure_ascii=False)+'，不必提交内部归属编号。'
        q['user_prompt']='本次问题\n'+issue+'\n\n原任务与相关材料\n'+original.get('user_prompt','')+'\n\n本次合并基准（省略字段保留）\n'+json.dumps(base,ensure_ascii=False,indent=2)
        q['system_prompt']=original.get('system_prompt','')+'\n\n'+part['text']
        from regrow.prompts.response_example import guide
        q['system_prompt']+='\n\n'+guide(q['response_schema'])
        q['fixed_parts']=[{'path':'原调用/具名合同','text':original.get('system_prompt','')},part,{'path':'纠错/具名格式','text':guide(q['response_schema'])}]
    return q


def _replace_paths(value, paths):
    if isinstance(value,str):
        for old,new in sorted(paths.items(),key=lambda x:-len(x[0])):value=value.replace(old,new)
        return value
    if isinstance(value,list):return [_replace_paths(v,paths) for v in value]
    if isinstance(value,dict):return {k:_replace_paths(v,paths) for k,v in value.items()}
    return value


def render(request):
    """Only model-facing prose changes; source/binding/history metadata stay IDs."""
    q=deepcopy(request);contract=q.get('name_contract')
    if not contract:return q
    names=contract['names']
    def prose(value):
        value=_replace_paths(text(value,names),contract['paths'])
        for old,new in [('控件ID','控件引用'),('区块ID','区块名称'),('控件 ID','控件引用'),('区块 ID','区块名称'),('稳定编号','引用名称'),('ref编号','ref名称')]:value=value.replace(old,new)
        return value
    literal = contract.get('region_reference_style') == 'id_name'
    for field in ('system_prompt','user_prompt','dynamic_prompt'):
        if field in q:
            if literal and field == 'system_prompt':
                continue
            if field == 'user_prompt':
                from regrow.prompts.history_disclosure import replace_presentation
                replace_presentation(q, prose(q[field]))
            else:
                q[field]=prose(q[field])
    if not literal:
        for part in q.get('fixed_parts',[]):part['text']=prose(part['text'])
    return q


def internal_request(request, reply=None):
    q=deepcopy(request);c=q.pop('name_contract',None)
    if c:
        q['response_schema']=c['schema']
        q['named_nested']=c['nested']
        if c.get('control_reference_style') == 'id_name':
            q['control_reference_style'] = 'id_name'
            q['control_reference_names'] = {ref: name for ref, name in c['names'].items()
                                            if re.fullmatch(r'c\d+', ref)}
        if c.get('region_reference_style') == 'id_name':
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
    if isinstance(value,str) and (key in REFERENCE_FIELDS or key=='function_refs'):
        if 'function_updates' in path:
            if key in ('region', 'supports', 'access_entry') and value in {**(control_labels or {}), **(region_labels or {})}:
                return value
            if key == 'constraints' and value.partition('/')[0] in (control_labels or {}):
                return value
        if key == 'control' and 'new_tasks' in path and value in new_controls:
            return value
        function_ref=(key=='function_refs' or ('function_updates' in path and key in ('ref','replace_with')))
        if (function_ref or key in ('constraints', 'task')) and value in aliases:
            return aliases[value]
        if control_labels is not None:
            from regrow.recognition.control_references import resolve_label
            resolved = resolve_label(value, control_labels, allow_path=function_ref or key == 'constraints')
            if resolved is not None:
                return resolved
        if region_labels is not None and not function_ref and key not in ('constraints', 'task'):
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
    new_names = {control.get('name') for region in main.get('regions', [])
                 for control in region.get('controls', [])
                 if isinstance(control, dict) and control.get('name') and not control.get('ref')}
    control_labels = ({ref: name for ref, name in contract['names'].items() if re.fullmatch(r'c\d+', ref)}
                      if contract.get('control_reference_style') == 'id_name' else None)
    region_labels = ({ref: name for ref, name in contract['names'].items() if re.fullmatch(r'r\d+', ref)}
                     if contract.get('region_reference_style') == 'id_name' else None)
    value=_decode_references(deepcopy(main),contract['aliases'],control_labels=control_labels,region_labels=region_labels,new_controls=new_names)
    if main is not reply and 'next_action' in reply:
        value['next_action'] = deepcopy(reply['next_action'])
    if (isinstance(reply.get('proposal'), dict) and isinstance(main.get('proposal'), dict)
            and 'next_action' in reply['proposal'] and 'next_action' not in main['proposal']):
        value['proposal']['next_action'] = deepcopy(reply['proposal']['next_action'])
    original = request.get('original_request', request)
    edit = value.get('record_edit')
    if original.get('done_task_review') and isinstance(edit, dict) and edit.get('field') == 'reopen_task':
        edit['before'] = resolve(edit.get('before'), contract['aliases'])
        task_name = original['done_task_review']['task']
        if reply['record_edit'].get('task') == text(task_name, contract['names']):
            edit['task'] = task_name
    if not contract['nested']:return value
    new_names = {control.get('name') for region in reply.get('regions', [])
                 for control in region.get('controls', [])
                 if isinstance(control, dict) and control.get('name') and not control.get('ref')}
    for raw, operation in zip(reply.get('new_tasks', []), value.get('new_tasks', [])):
        if isinstance(raw, dict) and isinstance(operation, dict) and raw.get('control') in new_names:
            operation['control'] = raw['control']
    rows=value.get('regions',[]);base=contract.get('base')
    regions=[];controls=[];indexes=[]
    from regrow.recognition.update_visibility import selected_indices
    selected = selected_indices(value)
    for position, row in enumerate(rows):
        if not isinstance(row,dict):raise ValueError('区块列表中的每项须为对象')
        if not isinstance(row.get('controls',[]),list):raise ValueError('区块「'+str(_key(row))+'」的controls须为列表，不能为null或其他类型')
        region={k:v for k,v in row.items() if k not in ('controls','current','parent')}
        if 'remove_fields' in region:
            region['remove_fields'] = ['parent_index' if field == 'parent' else field for field in region['remove_fields']]
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
        if 'parent' in row:
            raw_parent = row['parent']
            parent = resolve(raw_parent, references) if raw_parent is not None else None
            if parent is not None and type(parent) is not int:
                if raw_parent not in contract['names'] or not re.fullmatch(r'r\d+', raw_parent):
                    raise ValueError('区块「' + str(_key(row)) + '」的父区块「' + str(raw_parent)
                        + '」未能对应已知区块或本次回复中的唯一对象；请核对实际包含关系。')
                parent = raw_parent
            regions[i]['parent_index'] = parent
        for c in row.get('controls',[]):
            if not isinstance(c,dict):raise ValueError('区块「'+str(_key(row))+'」的控件列表中每项须为对象')
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
    planned=deepcopy(base.get('controls',[])) if base else []
    for c in controls:
        ci=c.get('candidate_index')
        if type(ci) is int:
            merged={k:v for k,v in planned[ci].items() if k not in c.get('remove_fields',[])}
            merged.update({k:v for k,v in c.items() if k not in ('candidate_index','remove_fields')})
            planned[ci]=merged
        else:planned.append(c)
    for route_number, route in enumerate(value.get('jump_to',[])):
        if 'region' in route:route['region_index']=resolve(route.pop('region'),references)
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
