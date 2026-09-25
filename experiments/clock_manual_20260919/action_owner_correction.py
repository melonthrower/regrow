"""Explicit correction of one executed action; immutable delivery evidence stays put."""
from copy import deepcopy


def schema():
    fields={k:{'type':'string','minLength':1} for k in
            ('attempt','from_region','from_control','to_region','to_control','evidence')}
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}


def effective_attempts(task):
    invalid={h['invalidated_attempt'] for h in task.get('ownership_history',[]) if h.get('invalidated_attempt')}
    return [a for a in dict.fromkeys(task.get('attempts',[])+task.get('completion_basis',{}).get('attempts',[])) if a not in invalid]


def control_history(region,task):
    """Candidate evidence for this exact control, never same-name inference."""
    if task.get('task_type')!='single_action':return []
    return [aid for aid,a in region.get('actions',{}).items()
            if a.get('control')==task.get('control') and a.get('operation')==task.get('action')
            and a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('description')]


def apply(records,state,edit,call,snapshot=None):
    def find(region_name,control_name):
        hits=[(rid,cid) for rid,r in records.items() if r['name']==region_name
              for cid,c in r['controls'].items() if c['name']==control_name]
        if len(hits)!=1:raise ValueError('动作归属纠正需要唯一的已披露区块与控件')
        return hits[0]
    old,old_control=find(edit['from_region'],edit['from_control'])
    new,new_control=find(edit['to_region'],edit['to_control']);aid=edit['attempt']
    action=records[old].get('actions',{}).get(aid)
    if (not edit['evidence'].strip() or (old,old_control)==(new,new_control)
            or action is None or action.get('control')!=old_control
            or action.get('delivery')!='executed_receipt_zero'
            or sum(aid in r.get('actions',{}) for r in records.values())!=1):
        raise ValueError('单笔动作的当前归属、投递状态或纠正依据不匹配')
    before=action.get('evidence',{}).get('before_observation')
    if not before or not any(o.get('evidence',{}).get('observation')==before
                             for o in records[new]['controls'][new_control].get('observations',[])):
        raise ValueError('目标控件缺少该动作前观察的身份依据；不能用后来同名控件倒推')
    affected=[t for t in records[old].get('tasks',{}).values() if t.get('control')==old_control
              and aid in set(t.get('attempts',[])+t.get('completion_basis',{}).get('attempts',[]))]
    if any(t.get('task_type')!='single_action' or t.get('findings') for t in affected):
        raise ValueError('参数事实或多步效果须先逐项核对，不能仅改动作对象迁移其结论')
    proof={'source_call':call,'region':old,'control':old_control,'evidence':edit['evidence']}
    moved=deepcopy(action)
    if snapshot is not None:
        from pathlib import Path
        import importlib.util
        spec=importlib.util.spec_from_file_location('owner_registration',Path(__file__).with_name('register_update.py'))
        reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
        moved=reg.rebase(moved,Path(snapshot)/'regions'/old,Path(snapshot)/'regions'/new)
    moved['control']=new_control;moved.setdefault('ownership_history',[]).append(proof)
    del records[old]['actions'][aid];records[new].setdefault('actions',{})[aid]=moved
    records[old]['controls'][old_control]['action_refs']=[a for a in records[old]['controls'][old_control].get('action_refs',[]) if a!=aid]
    target=records[new]['controls'][new_control];target['action_refs']=list(dict.fromkeys(target.get('action_refs',[])+[aid]))
    edges=[]
    for region in records.values():
        kept=[]
        for edge in region.get('transitions',[]):
            if edge.get('attempt')==aid and edge.get('source_region',region['id'])==old and edge.get('source_control')==old_control:
                edge.update(source_region=new,source_control=new_control);edges.append(edge)
            else:kept.append(edge)
        region['transitions']=kept
        for edge in region.get('reached_by',[]):
            if edge.get('attempt')==aid and edge.get('source_region')==old and edge.get('source_control')==old_control:
                edge.update(source_region=new,source_control=new_control)
    records[new]['transitions'].extend(edges)
    for name,task in records[old].get('tasks',{}).items():
        if task.get('control')!=old_control or aid not in set(task.get('attempts',[])+task.get('completion_basis',{}).get('attempts',[])):continue
        task.setdefault('ownership_history',[]).append({'invalidated_attempt':aid,'source_call':call,
            **{k:deepcopy(task[k]) for k in ('status','result_evidence','completion_basis') if k in task}})
        # Keep independently supported work for explicit review, not blanket suspension.
        if effective_attempts(task):
            if task.get('status')=='done':
                task.update(status='pending',result_evidence='原完成依据中一笔动作对象已纠正；须核对其余独立证据，不能继续沿用旧完成结论。')
                task.pop('completion_basis',None)
            records[old].setdefault('task_inventory',{})['review']={'source_call':call,'reason':'一笔动作的实际对象已纠正；核对剩余证据是否仍支持原任务结论。'}
            continue
        reason='原尝试 '+aid+' 实际作用于其他控件，不能证明本入口结果。'+edit['evidence']
        task.update(status='blocked',result_evidence=reason)
        task.pop('completion_basis',None)
        if not task.get('blocker'):
            task.update(blocker={'condition':'review_required','source_call':call},
                        deferral={'reason':reason,'source_call':call,'retry_when':'explicit_task_ownership_review'})
        records[old].setdefault('task_inventory',{})['review']={'source_call':call,'reason':reason+' 保留旧尝试，给未确认入口提出独立任务，不继承错误完成。'}
        if state.get('active_task')=={'region':old,'name':name}:state.pop('active_task',None)
    if state.get('last_action_result')=={'region':old,'action':aid}:state['last_action_result']={'region':new,'action':aid}
    state.pop('visual_navigation',None)


def request(root,run,attempt,target_region,target_control,task_source,frame):
    """Build the existing correction call for a diagnosed historical owner conflict."""
    from pathlib import Path
    import importlib.util,json
    def helper(name):
        spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    snapshot,records,_=helper('discovery_step').load(run)
    owners=[(rid,a) for rid,r in records.items() for aid,a in r.get('actions',{}).items() if aid==attempt]
    if len(owners)!=1:raise ValueError('历史动作记录缺失或不唯一')
    rid,action=owners[0];source_control=action.get('control')
    target=records[target_region]['controls'][target_control]
    q=helper('task_result_review').request(root,run,task_source,[str(frame)])
    q['discovery_context']={'region_names':{records[k]['name']:k for k in (rid,target_region)}}
    q['action_owner_candidates']=[{'attempt':attempt,'from_region':rid,'from_control':source_control,'to_region':target_region,'to_control':target_control}]
    images=[Path(run)/'action_attempts'/attempt/(when+'.png') for when in ('before','after')]
    if not all(p.is_file() for p in images):raise ValueError('缺少原动作前后图')
    q['screenshots']+= [str(p.resolve()) for p in images]
    dispatch=json.loads((Path(run)/'action_attempts'/attempt/'dispatch.json').read_text())
    before=action.get('evidence',{}).get('before_observation')
    details={'待核对动作':attempt,'原投递（不可改写）':dispatch,
        '当前有效归属':{'区块':records[rid]['name'],'控件':records[rid]['controls'][source_control]['name']},
        '候选实际对象':{'区块':records[target_region]['name'],'控件':target['name'],
                  '当时观察':[o for o in target.get('observations',[]) if o.get('evidence',{}).get('observation')==before]},
        '已登记直接结果':action.get('result'),
        '说明':'目标仅为待核对候选，不是身份结论。最后两张为该动作原前、后图；结合实际坐标、卡片职责核对，不能只凭同名或相似按钮改挂。原始任务意图、投递和截图不改写。'}
    q['user_prompt']+='\n\n历史归属核对材料：'+json.dumps(details,ensure_ascii=False,indent=2)
    job={'stage':'task_result_review','request':q,'candidate':None,'error':'历史动作实际对象与登记归属可能冲突，请按原前后图核对；修正归属与原任务结果需一并经过正常校验。',
         'blocked_by':'binding_conflict','history':[],'supplements':[]}
    context=helper('repair_stages').context(run,job)
    wire=helper('step_repair').request(root,job,context)
    dynamic=json.loads(wire['user_prompt'])
    dynamic['图片说明']=['图1是当前任务的保存观察，不是本次新执行。','图2是待纠正动作 '+attempt+' 的原动作前图。','图3是该动作的原动作后图；不表示今天再次执行。']
    wire['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return job,wire
