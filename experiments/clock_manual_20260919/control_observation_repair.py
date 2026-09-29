"""Explicit source-scoped observation reassignment, never whole-control merging."""
from copy import deepcopy


def schema():
    source={'type':'object','properties':{k:{'type':'string','minLength':1} for k in ('source_call','source_field')},'required':['source_call','source_field'],'additionalProperties':False}
    fields={k:{'type':'string','minLength':1} for k in ('region','from_control','to_control','retained_name','evidence')}
    fields['observations']={'type':'array','items':source,'minItems':1}
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}


def key(observation):
    evidence=observation.get('evidence',{})
    return evidence.get('source_call'),evidence.get('source_field')


def apply(records,state,edit,call):
    regions=[r for r in records.values() if r['name']==edit['region']]
    if len(regions)!=1:raise ValueError('观察纠正区块不唯一')
    region=regions[0]
    def find(name):
        ids=[cid for cid,c in region['controls'].items() if c['name']==name]
        if len(ids)!=1:raise ValueError('观察纠正控件不唯一')
        return ids[0]
    old,new=find(edit['from_control']),find(edit['to_control'])
    selectors=[(x['source_call'],x['source_field']) for x in edit['observations']]
    if old==new or not edit['evidence'].strip() or not selectors or len(set(selectors))!=len(selectors):
        raise ValueError('观察纠正需要不同对象、唯一来源及依据')
    retained=edit['retained_name'].strip()
    if not retained or any(cid!=old and c['name']==retained for cid,c in region['controls'].items()):
        raise ValueError('保留对象需要明确且不重复的职责名称')
    source=region['controls'][old];target=region['controls'][new]
    chosen=[]
    for selector in selectors:
        hits=[o for o in source.get('observations',[]) if key(o)==selector]
        if len(hits)!=1 or any(key(o)==selector for o in target.get('observations',[])):
            raise ValueError('观察来源缺失、重复或已在目标对象')
        chosen.append(hits[0])
    if len(chosen)==len(source.get('observations',[])):
        raise ValueError('不能迁移来源控件的最后观察；需另行核对整个身份')
    observations={o.get('evidence',{}).get('observation') for o in chosen}
    for owner in records.values():
        for action in owner.get('actions',{}).values():
            if owner.get('id')==region.get('id') and action.get('control')==old and action.get('evidence',{}).get('before_observation') in observations:
                raise ValueError('被迁移观察支撑已执行动作；先独立核对动作归属，不随观察自动迁移')
    # No mutation occurs before all selectors and executed-action bindings pass.
    previous_name=source['name']
    source['name']=retained
    source['observations']=[o for o in source['observations'] if key(o) not in selectors]
    target.setdefault('observations',[]).extend(deepcopy(chosen))
    # Keep temporal order independent of when this correction was requested.
    target['observations'].sort(key=lambda o:(str(o.get('evidence',{}).get('source_call','')),str(o.get('evidence',{}).get('source_field',''))))
    audit={'source_call':call,'from_control':old,'to_control':new,'observations':deepcopy(edit['observations']),'evidence':edit['evidence'],'previous_name':previous_name,'retained_name':retained}
    region.setdefault('control_observation_revisions',[]).append(audit)
    current=state.get('observation',{})
    if current.get('id') in observations and old in current.get('control_refs',[]):
        remaining=any(o.get('evidence',{}).get('observation')==current['id'] for o in source['observations'])
        current['control_refs']=list(dict.fromkeys([c for c in current['control_refs'] if c!=old or remaining]+[new]))
    region.setdefault('task_inventory',{})['review']={'source_call':call,'reason':'历史观察对象已纠正；核对任务与功能依据，不继承另一对象的完成状态。'}
    region.get('function_inventory',{}).pop('evidence_digest',None)
    state.pop('visual_navigation',None)


def validate_scope(run,job,edit,records,scope):
    from pathlib import Path
    import json
    candidates=job['request'].get('control_observation_candidates',[])
    matched=[c for c in candidates if c['region'] in scope and scope[c['region']]['name']==edit['region']
             and scope[c['region']]['controls'].get(c['from_control'],{}).get('name')==edit['from_control']
             and scope[c['region']]['controls'].get(c['to_control'],{}).get('name')==edit['to_control']]
    if len(matched)!=1:raise ValueError('观察纠正对象没有随本轮披露')
    c=matched[0]
    if c['region'] not in scope or any(cid not in scope[c['region']]['controls'] for cid in (c['from_control'],c['to_control'])):
        raise ValueError('观察纠正超出本轮控件范围')
    pointer=json.loads((Path(run)/'knowledge_current.json').read_text())
    if pointer['snapshot']!=job['request'].get('control_observation_snapshot'):
        raise ValueError('观察纠正快照已变化')
    allowed={(s['source_call'],s['source_field']) for s in c['observations']}
    if not all((s['source_call'],s['source_field']) in allowed for s in edit['observations']):
        raise ValueError('观察来源没有随本轮披露')
    # Bind original request labels before same-batch renames; the raw edit remains in the audit.
    return {**edit,'from_control':records[c['region']]['controls'][c['from_control']]['name'],
            'to_control':records[c['region']]['controls'][c['to_control']]['name']}


def begin(root,run,rid,from_control,to_control,selectors,frame):
    """Supervised diagnosis enters normal task correction with complete run context."""
    from pathlib import Path
    import importlib.util,json,uuid
    def helper(name):
        spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    run=Path(run).resolve();snapshot,records,state=helper('discovery_step').load(run)
    if any((run/n).exists() for n in ('pending_step.json','execution_pending.json')):
        raise ValueError('先完成当前步骤或待结算动作，再核对历史观察')
    import hashlib
    observed=(state.get('observation') or {}).get('image')
    if rid not in state.get('interactive_regions',[]) or not observed:
        raise ValueError('当前区块未确认可交互，不能进入本轮观察纠正')
    current=(run/observed).resolve();provided=Path(frame).resolve()
    if not current.is_file() or not provided.is_file() or hashlib.sha256(current.read_bytes()).digest()!=hashlib.sha256(provided.read_bytes()).digest():
        raise ValueError('观察纠正必须使用当前记录的原始观察图')
    region=records[rid];source=region['controls'][from_control];target=region['controls'][to_control]
    chosen=[]
    for selector in selectors:
        hits=[o for o in source['observations'] if key(o)==(selector['source_call'],selector['source_field'])]
        if len(hits)!=1:raise ValueError('诊断观察不唯一')
        chosen+=hits
    q=helper('region_tasks').plan_request(root,records,state,rid)
    q['screenshots']=[str(Path(frame).resolve())]
    # Include original full frames, with their provenance, not manually reduced prompts/crops.
    examples=[source['observations'][0],*chosen,target['observations'][-1]]
    labels=[{'image':1,'purpose':'当前保存观察；本轮没有执行动作'}]
    for o in examples:
        image=(snapshot/'regions'/rid/o['source_image']).resolve()
        if not image.is_file():raise ValueError('历史观察缺少原始截图')
        if str(image) not in q['screenshots']:
            q['screenshots'].append(str(image));labels.append({'image':len(q['screenshots']),'source':o['evidence'],'purpose':'历史原图，仅核对对象身份，不表示当前状态'})
    q['image_refs']=list(q['screenshots'])
    q['control_observation_snapshot']=str(snapshot.relative_to(run))
    q['control_observation_candidates']=[{'region':rid,'from_control':from_control,'to_control':to_control,'observations':deepcopy(selectors)}]
    details={'来源控件':deepcopy(source),'目标候选控件':deepcopy(target),'图片顺序':labels,
             '说明':'来源和目标只是待核对候选。核对职责、原始图和历史任务；若确有混写，按source_call/source_field迁移指定观察，同时必须填写retained_name：它是来源控件在移除误挂观察后，依据剩余观察和原任务职责应使用的准确名称；不能继续沿用描述被移走对象的错误名称。from_control/to_control仍引用本轮披露的原名称用于身份绑定，retained_name是本次修正后的名称。不得整条合并、迁移旧任务或改写动作。若同一物理对象只是模式变化，不应拆分。回复沿正常纠错，修订后完整清点当前区块。'}
    q['user_prompt']+='\n历史观察归属核对：'+json.dumps(details,ensure_ascii=False,indent=2)
    q['dynamic_prompt']=q['user_prompt']
    job={'path':'repair_episodes/observation-review-'+uuid.uuid4().hex+'/episode.json',
         'stage':'task_proposal','request':q,'attempt':None,'status':'repair','repairs':0,'observations':0,
         'history':[],'seen':[],'supplements':[],'candidate':None,'blocked_by':'binding_conflict',
         'error':'历史控件的部分观察可能对应不同职责对象；按原图及来源核对并修订，未确认前不得继承任务完成。'}
    helper('step_repair').atomic(run/job['path'],job)
    helper('step_repair').atomic(run/'pending_step.json',{'episode':job['path']})
    return job
