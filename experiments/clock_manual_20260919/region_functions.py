"""Region-owned reusable functions; instruction composition happens after traversal."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import identity_templates as templates
from function_evidence import action_results, action_row, omitted_reason, incoming_results, coverage as action_evidence_coverage
import function_scope as knowledge


def task_module():
    import importlib.util
    spec=importlib.util.spec_from_file_location('region_tasks',Path(__file__).with_name('region_tasks.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def wire_schema(root):
    # The API rejects uniqueItems; keep it in the local registration schema.
    def strip(value):
        if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if k!='uniqueItems'}
        if isinstance(value,list):return [strip(v) for v in value]
        return value
    return strip(schema(root))


PROMPT_PATHS=['任务/区块功能登记.prompt','功能识别/单区块任务判定规则.prompt','功能识别/单区块任务正反例.prompt']


def request_support_review(run,rid,call):
    """Ask the task author to classify observed controls; never invent support tasks."""
    tasks=task_module();discovery=tasks.helper('discovery_step');_,records,_=discovery.load(run)
    region=records.get(rid,{})
    supported={t.get('control') for t in region.get('tasks',{}).values()}
    missing=[cid for cid in region.get('controls',{}) if cid not in supported]
    key=hashlib.sha256(json.dumps([missing,sorted(region.get('actions',{}))],sort_keys=True).encode()).hexdigest()
    if not missing or region.get('support_review_key')==key:return False
    def mutate(records,state,*args):
        r=records[rid];r['support_review_key']=key
        r.setdefault('task_inventory',{})['review']={'kind':'function_support','source_call':call,
            'reason':'功能登记缺少操作任务依据。请结合已登记截图与动作，补充这些控件的任务或仅观察记录：'+ '、'.join(r['controls'][cid]['name'] for cid in missing)+'。不要把控件名当任务名，也不要为显而易见的能力补做无意义点击。'}
    import uuid
    discovery.publish(run,'support-review-'+uuid.uuid4().hex,mutate)
    return True


def supported_tasks(region):
    return knowledge.supported(region)


def supporting_tasks(region,records=None):
    records=records or {region['id']:region}
    local={name:{'region':region['id'],'name':name,'task':task}
           for name,task in supported_tasks(region).items()}
    return {**local, **knowledge.parameter_support(region,records)}


def catalog(region,records=None):
    return {key+' / '+name:{**deepcopy(fact),'task':key,'task_region':support['region'],
                           'task_name':support['name']}
            for key,support in supporting_tasks(region,records).items()
            for name,fact in support['task'].get('findings',{}).items()}


def attribute_context(region):
    """Keep full binding keys and facts, grouped under the supporting task."""
    result={}
    for key,fact in catalog(region).items():
        item={k:v for k,v in fact.items() if k not in ('source','sources')}
        item['事实来源']=deepcopy(fact.get('sources') or ([fact['source']] if fact.get('source') else []))
        result.setdefault(fact['task'],{})[key]=item
    return result


def semantic_observation(control):
    # Visual navigation adds transient localization rows, not registered meaning.
    return next((row for row in reversed(control.get('observations',[])) if not row.get('visual_only')), {})


def evidence_projection(region,records=None):
    """Build once for the request and its invalidation digest; keep observation provenance."""
    controls=[]
    for c in region['controls'].values():
        observation=semantic_observation(c)
        source={**observation.get('evidence',{}),**observation}
        controls.append({'名称':c['name'],**{k:v for k,v in observation.items() if k in ('text','state','possible_operation','uncertainty')},
            '观察出处':{k:source[k] for k in ('source_call','observation','source_field') if k in source}})
        if templates.evidence_limit(observation):controls[-1]['视觉依据限定']=templates.evidence_limit(observation)
    return {'已观察控件':controls,
        '已登记操作':[{'任务':n,'依据':t.get('result_evidence',t['reason']),
                     '任务提出调用':t.get('source_call'),
                     '依据时态':'历史记录：其中当前、本轮、未验证均指对应观察时刻，须与后续动作和恢复观察合看',
                     '结果动作记录':list(t.get('attempts',[])),
                     '登记方式':'本任务以直接观察登记；不否认其他历史动作' if t['status']=='record_only' else '绑定动作已探索；只采用实际观察，不把done或任务意图当作功能成功'} for n,t in supported_tasks(region).items()],
        '已记录属性（待甄别）':attribute_context(region),
        '同区块已执行动作结果':action_results(region,records),
        '动作证据覆盖':action_evidence_coverage(region,records),
        '进入本区块的已观察结果':incoming_results(region,records)}


def summary_projection(region,records=None):
    records=records or {region['id']:region}
    supports=supporting_tasks(region,records)
    return {'已登记操作':[knowledge.task_product(n,t) for n,t in supported_tasks(region).items()],
        '控件用途标注':[{'名称':c['name'],**{k:v for k,v in semantic_observation(c).items()
            if k in ('possible_operation','uncertainty')}} for c in region.get('controls',{}).values()],
        '同区块已执行动作结果':[knowledge.compact_action(row) for row in action_results(region,records)],
        '动作证据覆盖':action_evidence_coverage(region,records),
        '进入本区块的已观察结果':[knowledge.compact_action(row) for row in incoming_results(region,records)],
        '入口与目标一级摘要':[{**edge,'destination':knowledge.card(records[edge['region']],records)}
                               for edge in knowledge.entries(region,records)],
        '按本地参数任务披露的支持':[{'区块':support['region'],
            **knowledge.task_product(support['name'],support['task']),
            '动作结果':[knowledge.compact_action(row) for row in action_results(records[support['region']],records)
                if row['动作记录'] in support['task'].get('attempts',[])
                or row['控件'] and row['控件']==records[support['region']].get('controls',{}).get(support['task'].get('control'),{}).get('name')]} for key,support in supports.items()
            if support['region']!=region['id']],
        '支持任务引用目录':{key:{'区块':support['region'],'任务':support['name']} for key,support in supports.items()},
        '可引用参数事实':{key:knowledge.fact_card(fact) for key,fact in catalog(region,records).items()}}


def signature(region,records=None):
    records=records or {region['id']:region}
    evidence=evidence_projection(region,records)
    evidence.pop('动作证据覆盖')
    for c in evidence['已观察控件']:c.pop('观察出处',None)
    selected={(row['region'],row['task']) for f in region.get('functions',{}).values()
              for row in f.get('support_tasks',[]) if row['region']!=region['id']}
    dependencies=[]
    for rid,name in sorted(selected):
        source=records.get(rid,{})
        task=source.get('tasks',{}).get(name)
        control=source.get('controls',{}).get((task or {}).get('control'),{})
        observed=semantic_observation(control)
        dependencies.append({'region':rid,'task_name':name,'task':task,
            'control':{'name':control.get('name'),**{k:v for k,v in observed.items()
                if k in ('possible_operation','uncertainty')}},
            'results':[action_row(source,aid,action,records) for aid,action in source.get('actions',{}).items()
                if task and omitted_reason(action) is None and (aid in task.get('attempts',[])
                    or task.get('control') is not None and action.get('control')==task['control'])]})
    # Destination summaries and unselected neighbour detail are read-time views.
    # Only local work and explicitly adopted foreign support invalidate this owner.
    evidence.pop('进入本区块的已观察结果')
    for control in evidence['已观察控件']:
        control.pop('state',None);control.pop('text',None)
    data={'extraction_rules':[(Path(__file__).parent/'遍历prompt'/p).read_text() for p in PROMPT_PATHS],
          'name':region['name'],'tasks':region.get('tasks',{}),'inventory':region.get('task_inventory'),
          'evidence':evidence,'entries':knowledge.entries(region,records),
          'selected_foreign_support':dependencies}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def request_signature(region,records=None):
    """Protect every offered fact, including support first selected in this reply."""
    data={'rules':[(Path(__file__).parent/'遍历prompt'/p).read_text() for p in PROMPT_PATHS],
          'name':region['name'],'description':region['description'],
          'evidence':summary_projection(region,records)}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def review_current(region,records=None):
    return bool(region.get('region_role')) and region.get('function_inventory',{}).get('evidence_digest')==signature(region,records)


def next_ready(records,state):
    """Summarize closed Region work once per evidence revision, without navigation."""
    for region in sorted(records.values(),key=lambda r:r['id']!=state.get('working_region')):
        if (task_module().coverage(region,records)['complete']
                and not region.get('registration_gaps',{}).get('function_registration')
                and not review_current(region,records)):
            return region['id']
    return None


def schema(root):
    return json.loads((Path(root)/'遍历prompt/输出格式/区块功能登记.schema').read_text())


def request_schema(root,region,records=None):
    value=wire_schema(root)
    fields=value['properties']['functions']['items']['properties']
    names=list(supporting_tasks(region,records));keys=list(catalog(region,records))
    fields['tasks']['minItems']=1
    if names:fields['tasks']['items']['enum']=names
    else:value['properties']['functions']['maxItems']=0
    if keys:fields['constraints']['items']['enum']=keys
    else:fields['constraints']['maxItems']=0
    definitions=value['properties']['parameter_definitions']
    if keys:definitions['items']['properties']['ref']['enum']=keys
    else:definitions['maxItems']=0
    local=value['properties']['local_knowledge']['properties']
    local_names=list(supported_tasks(region));local_facts=list(catalog(region))
    for refs,names in [(local['parameter_refs'],local_facts),
                       (local['conditions']['items']['properties']['tasks'],local_names)]:
        if names:refs['items']['enum']=names
        else:refs['maxItems']=0
    return value


def locations(sources):
    result=[]
    for source in sources:
        item={'region':source['region'],'control':source.get('control')}
        if item not in result:result.append(item)
    return result


def register(region,reply,call,records=None):
    import jsonschema
    jsonschema.validate(reply,schema(Path(__file__).parent))
    if not task_module().coverage(region,records)['complete']:raise ValueError('Region exploration is not complete')
    if not reply['role_evidence'].strip():raise ValueError('region role needs evidence')
    if reply['region_role']=='navigation' and reply['functions']:raise ValueError('navigation cannot claim business functions')
    # A parameter surface can support business work without owning a complete atom.
    if not reply['evidence'].strip():raise ValueError('function inventory needs evidence')
    facts=catalog(region,records)
    definitions={}
    for definition in reply['parameter_definitions']:
        ref=definition['ref']
        if ref not in facts or ref in definitions or not definition['description'].strip():
            raise ValueError('stable parameter definition needs unique known fact and description')
        definitions[ref]=definition
    def stable_fact(ref):
        if ref not in definitions:raise ValueError('selected parameter needs stable definition: '+ref)
        fact=facts[ref]
        return {**deepcopy(fact),'description':definitions[ref]['description'],
                'conditions':list(definitions[ref]['conditions'])}
    local=reply['local_knowledge']
    if not local['summary'].strip():raise ValueError('local summary must describe this Region')
    local_facts=catalog(region)
    if any(ref not in local_facts for ref in local['parameter_refs']):
        raise ValueError('local parameters must belong to local tasks')
    for ref in local['parameter_refs']:stable_fact(ref)
    for condition in local['conditions']:
        if not condition['description'].strip() or not condition['tasks'] or any(n not in supported_tasks(region) for n in condition['tasks']):
            raise ValueError('local condition needs local supporting tasks')
    facts=catalog(region,records);tasks=supporting_tasks(region,records);result={};errors=[]
    for proposed in reply['functions']:
        name=proposed['name'].strip();refs=proposed['tasks']
        if not name or name in result or not proposed['description'].strip() or not proposed['object'].strip() or not proposed['completion'].strip() or not refs or any(n not in tasks for n in refs):
            raise ValueError('function needs known supporting tasks')
        if not any(tasks[n]['region']==region['id'] for n in refs):
            raise ValueError('原子操作主区块需要本地支持任务：'+name+'的支持任务全部来自相关区块。本区块实际承担同一业务目的时引用对应本地任务；仅显示结果时由实际业务区块登记，不以无关任务凑引用。')
        constraints={};sources=[]
        for key in proposed['constraints']:
            if key not in facts:
                matches=[full for full,fact in facts.items() if fact['task'] in refs and fact['name']==key]
                if len(matches)==1:key=matches[0]
            fact=facts.get(key)
            if not fact or fact['task'] not in refs:
                if fact:
                    reason=f"属性的来源任务“{fact['task']}”不在本功能tasks中；只有该任务确实支持功能时才加入tasks"
                    candidates=[key]
                else:
                    matches=[full for full,value in facts.items() if value['name']==key and value['task'] in refs]
                    reason='短属性名不唯一，请使用完整属性名' if len(matches)>1 else '该名称未匹配本功能支持任务的属性；不能用任务名或控件名代替属性名'
                    candidates=matches or [full for full,value in facts.items() if value['task'] in refs]
                errors.append({'功能':name,'约束引用':key,'原因':reason,'可核对的完整属性名':candidates})
                continue
            fact=stable_fact(key)
            evidence=deepcopy(fact.get('sources',[fact['source']]))
            constraints[key]={'name':fact['name'],'description':fact['description'],
                'domain':deepcopy(fact['domain']),'conditions':list(fact['conditions']),
                'locations':locations(evidence),'sources':evidence}
            sources.extend(evidence)
        entries=[{'region':tasks[n]['region'],'control':tasks[n]['task']['control']} for n in refs]
        result[name]={'description':proposed['description'],'object':proposed['object'],'completion':proposed['completion'],
            'region':region['id'],'task_refs':[tasks[n]['name'] for n in refs if tasks[n]['region']==region['id']],
            'support_tasks':[{'region':tasks[n]['region'],'task':tasks[n]['name']} for n in refs],
            'locations':locations(entries+sources),'constraints':constraints,
            'unconfirmed':list(proposed['unconfirmed']),'source_call':call}
    if errors:
        raise ValueError('constraint lacks supporting task evidence；constraints引用属性名，tasks引用任务名。只选择确有可设置证据的属性，不要为了通过校验全部填入。\n'+json.dumps(errors,ensure_ascii=False,indent=2))
    # Old snapshots retain previous records. No GUI task, chosen value or graph edge is created.
    gap=region.get('registration_gaps',{}).pop('function_registration',None)
    if gap:region.setdefault('registration_gap_history',[]).append({**deepcopy(gap),'stage':'function_registration','resolved_by':call})
    region['local_knowledge']={'summary':local['summary'],
        'parameters':{ref:knowledge.fact_card(stable_fact(ref)) for ref in local['parameter_refs']},
        'conditions':deepcopy(local['conditions']),
        'source_call':call}
    region.update(region_role=reply['region_role'],role_evidence=reply['role_evidence'])
    region['functions']=result
    region['function_inventory']={'source_call':call,'evidence':reply['evidence'],'evidence_digest':signature(region,records)}


def request(root,region,state,records=None):
    if not task_module().coverage(region,records)['complete']:raise ValueError('Region exploration is not complete')
    pr=Path(root)/'遍历prompt'
    paths=PROMPT_PATHS
    parts=[{'path':path,'text':(pr/path).read_text()} for path in paths]
    text='\n\n'.join(part['text'] for part in parts)
    user={'区块':region['name'],'描述':region['description'],
        **summary_projection(region,records),
        '要求':'整理本区块自身的稳定知识及多个独立用途。入口仅引用目标一级摘要，不把目标功能写回本区块。仅明确参数支持可按引用补充本地功能。动态值只作历史证据，不进入通用摘要或完成条件。保留条件、限制和未确认项。'}
    dynamic=json.dumps(user,ensure_ascii=False,indent=2)
    return {'pipeline_step':'discovery','stage':'function_registration','role':'function_registration','action_ready':False,
        'system_prompt':text,'user_prompt':dynamic,'dynamic_prompt':dynamic,'screenshots':[],'image_refs':[],
        'fixed_parts':parts,'response_schema':request_schema(root,region,records),
        'source':{'region':region['id'],'observation':(state.get('observation') or {}).get('id'),'evidence_digest':request_signature(region,records)}}


def commit(root,run,call):
    tasks=task_module();reg=tasks.helper('register_update');discovery=tasks.helper('discovery_step')
    q,reply=tasks.helper('step_repair').submission(run,call)
    rid=q['source']['region']
    def mutate(records,state,snapshot,temp):
        if q.get('stage')!='function_registration':raise ValueError('not a function registration request')
        if request_signature(records[rid],records)!=q['source']['evidence_digest']:raise ValueError('function evidence changed since request')
        register(records[rid],reply,call,records)
    return discovery.publish(run,'functions-'+call,mutate)
