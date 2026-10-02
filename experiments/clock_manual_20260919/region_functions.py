"""Region-owned reusable functions; instruction composition happens after traversal."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import identity_templates as templates


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
    # An explicit visible capability need not be executed to enter the catalog.
    return {name:t for name,t in region.get('tasks',{}).items() if t['status'] in ('done','record_only') and not t.get('coverage_exemption') and not t.get('shared_result')}


def catalog(region):
    return {task_name+' / '+name:{**deepcopy(fact),'task':task_name}
            for task_name,task in supported_tasks(region).items()
            for name,fact in task.get('findings',{}).items()}


def attribute_context(region):
    """Keep full binding keys and facts, grouped under the supporting task."""
    result={}
    for key,fact in catalog(region).items():
        result.setdefault(fact['task'],{})[key]={k:v for k,v in fact.items() if k not in ('source','sources')}
    return result


def action_results(region):
    """Task summaries and their original executed action results complement each other."""
    tasks=supported_tasks(region)
    controls={t.get('control') for t in tasks.values()}
    rows=[]
    for aid,action in region.get('actions',{}).items():
        cid=action.get('control');result=action.get('result',{})
        related=[name for name,t in tasks.items() if aid in t.get('attempts',[])]
        unconfirmed=cid is None and bool(related)
        if (not unconfirmed and (cid not in controls or cid not in region['controls'])):continue
        if action.get('delivery')!='executed_receipt_zero' or not result.get('description'):continue
        row={'动作记录':aid,'结果调用':action.get('result_call') or action.get('evidence',{}).get('result_call'),
             '选择调用':action.get('evidence',{}).get('selection_call'),'动作目的':action.get('purpose',''),
             '动作前观察':action.get('evidence',{}).get('before_observation'),
             '动作后观察':action.get('evidence',{}).get('after_observation'),
             '关联任务':related,
             '控件':'' if unconfirmed else region['controls'][cid]['name'],'动作':action.get('operation',''),
             '结果':result['description'],'依据':result.get('evidence',''),
             '异常':result.get('exception','')}
        if unconfirmed:
            row.update(控件关联='未确认',提案目标=action.get('association',{}).get('target',''),
                       归属边界='以下是关联任务的真实动作结果；提案目标未成为已确认控件，不补做身份绑定。')
        if action.get('parameter_findings'):row['已记录参数事实']=deepcopy(action['parameter_findings'])
        if row not in rows:rows.append(row)
    return rows


def incoming_results(region,records=None):
    """Resolve existing incoming edges to observed results, without inventing persistence."""
    rows=[]
    for edge in region.get('reached_by',[]):
        if edge.get('source_region')==region['id']:continue
        source=(records or {}).get(edge.get('source_region'),{})
        action=source.get('actions',{}).get(edge.get('attempt'),{})
        result=action.get('result',{})
        if action.get('delivery')!='executed_receipt_zero' or result.get('exception')!='none' or not result.get('description'):continue
        control=source.get('controls',{}).get(action.get('control'),{})
        row={'来源区块':source.get('name',''),'入口':control.get('name',''),
             '归属说明':'这是其他区块的操作，本区块仅接收结果；不能把来源控件名用作本区块任务名。',
             '来源任务':[n for n,t in source.get('tasks',{}).items() if t.get('control')==action.get('control') and action.get('control')],
             '结果':result['description'],'依据':result.get('evidence','')}
        if row not in rows:rows.append(row)
    return rows


def evidence_projection(region,records=None):
    """Build once for the request and its invalidation digest; keep observation provenance."""
    controls=[]
    for c in region['controls'].values():
        observation=(c.get('observations') or [{}])[-1]
        source={**observation.get('evidence',{}),**observation}
        controls.append({'名称':c['name'],**{k:v for k,v in observation.items() if k in ('text','state','possible_operation','uncertainty')},
            '观察出处':{k:source[k] for k in ('source_call','observation','source_field') if k in source}})
        if templates.evidence_limit(observation):controls[-1]['视觉依据限定']=templates.evidence_limit(observation)
    return {'已观察控件':controls,
        '已登记操作':[{'任务':n,'依据':t.get('result_evidence',t['reason']),
                     '结果动作记录':list(t.get('attempts',[])),
                     '登记方式':'本任务以直接观察登记；不否认其他历史动作' if t['status']=='record_only' else '依据本任务探索结果登记'} for n,t in supported_tasks(region).items()],
        '已记录属性（待甄别）':attribute_context(region),
        '同区块已执行动作结果':action_results(region),
        '进入本区块的已观察结果':incoming_results(region,records)}


def signature(region,records=None):
    evidence=evidence_projection(region,records)
    # Reobserving unchanged facts does not require another catalog call.
    for c in evidence['已观察控件']:c.pop('观察出处',None)
    data={'extraction_rules':[(Path(__file__).parent/'遍历prompt'/p).read_text() for p in PROMPT_PATHS],
          'name':region['name'],'tasks':region.get('tasks',{}),'inventory':region.get('task_inventory'),
          'evidence':evidence}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def review_current(region,records=None):
    return bool(region.get('region_role')) and region.get('function_inventory',{}).get('evidence_digest')==signature(region,records)


def schema(root):
    return json.loads((Path(root)/'遍历prompt/输出格式/区块功能登记.schema').read_text())


def request_schema(root,region):
    value=wire_schema(root)
    fields=value['properties']['functions']['items']['properties']
    names=list(supported_tasks(region));keys=list(catalog(region))
    fields['tasks']['minItems']=1
    if names:fields['tasks']['items']['enum']=names
    else:value['properties']['functions']['maxItems']=0
    if keys:fields['constraints']['items']['enum']=keys
    else:fields['constraints']['maxItems']=0
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
    if reply['region_role'] in ('functional','mixed') and not reply['functions']:raise ValueError('functional role needs a supported function')
    if not reply['evidence'].strip():raise ValueError('function inventory needs evidence')
    facts=catalog(region);tasks=supported_tasks(region);result={};errors=[]
    for proposed in reply['functions']:
        name=proposed['name'].strip();refs=proposed['tasks']
        if not name or name in result or not proposed['description'].strip() or not proposed['object'].strip() or not proposed['completion'].strip() or not refs or any(n not in tasks for n in refs):
            raise ValueError('function needs known supporting tasks')
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
            evidence=deepcopy(fact.get('sources',[fact['source']]))
            constraints[key]={'name':fact['name'],'description':fact['description'],
                'domain':deepcopy(fact['domain']),'conditions':list(fact['conditions']),
                'locations':locations(evidence),'sources':evidence}
            sources.extend(evidence)
        entries=[{'region':region['id'],'control':tasks[n]['control']} for n in refs]
        result[name]={'description':proposed['description'],'object':proposed['object'],'completion':proposed['completion'],
            'region':region['id'],'task_refs':refs,
            'locations':locations(entries+sources),'constraints':constraints,
            'unconfirmed':list(proposed['unconfirmed']),'source_call':call}
    if errors:
        raise ValueError('constraint lacks supporting task evidence；constraints引用属性名，tasks引用任务名。只选择确有可设置证据的属性，不要为了通过校验全部填入。\n'+json.dumps(errors,ensure_ascii=False,indent=2))
    # Old snapshots retain previous records. No GUI task, chosen value or graph edge is created.
    gap=region.get('registration_gaps',{}).pop('function_registration',None)
    if gap:region.setdefault('registration_gap_history',[]).append({**deepcopy(gap),'stage':'function_registration','resolved_by':call})
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
        **evidence_projection(region,records),
        '已有功能名称（仅供命名复用）':list(region.get('functions',{})),
        '要求':'整理可复用功能，引用操作任务和属性的完整名称。属性目录只是原始事实，不保证可设置；仅将证据支持可由用户设置的属性选作constraints，标题等只读事实不选。只登记能力，不选择目标值、不生成指令、不执行。'}
    dynamic=json.dumps(user,ensure_ascii=False,indent=2)
    return {'pipeline_step':'discovery','stage':'function_registration','role':'function_registration','action_ready':False,
        'system_prompt':text,'user_prompt':dynamic,'dynamic_prompt':dynamic,'screenshots':[],'image_refs':[],
        'fixed_parts':parts,'response_schema':request_schema(root,region),
        'source':{'region':region['id'],'observation':(state.get('observation') or {}).get('id'),'evidence_digest':signature(region,records)}}


def commit(root,run,call):
    tasks=task_module();reg=tasks.helper('register_update');discovery=tasks.helper('discovery_step')
    q,reply=tasks.helper('step_repair').submission(run,call)
    rid=q['source']['region']
    def mutate(records,state,snapshot,temp):
        if q.get('stage')!='function_registration':raise ValueError('not a function registration request')
        if signature(records[rid],records)!=q['source']['evidence_digest']:raise ValueError('function evidence changed since request')
        register(records[rid],reply,call,records)
    return discovery.publish(run,'functions-'+call,mutate)
