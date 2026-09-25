"""Explicit cross-Region behavior links; local observation identity stays local.

One canonical record lives under the first member's Region. Other members hold
only a reference. Existing snapshot transactions persist both atomically.
"""
from copy import deepcopy


def link(records,name,members,reason,evidence):
    members=list(dict.fromkeys(tuple(m) for m in members))
    if not name.strip() or not reason.strip() or len({r for r,c in members})<2:
        raise ValueError('shared behavior needs distinct Regions and an explicit reason')
    for rid,cid in members:
        control=records[rid]['controls'][cid]
        if control.get('shared_control_ref'):raise ValueError('control already linked')
    if not evidence:raise ValueError('shared behavior needs observed action evidence')
    for item in evidence:
        owner=records[item['region']];a=owner['actions'][item['attempt']]
        if (item['region'],a.get('control')) not in members or a.get('delivery')!='executed_receipt_zero' or a.get('result',{}).get('exception')!='none':
            raise ValueError('link evidence is not a successful member action')
    owner=members[0][0]
    if name in records[owner].get('shared_controls',{}):raise ValueError('shared name already exists')
    records[owner].setdefault('shared_controls',{})[name]={
        'name':name,'scope':'behavior_only','reason':reason,'evidence':deepcopy(evidence),
        'members':[{'region':r,'control':c} for r,c in members], 'results':[], 'status':'confirmed'}
    for rid,cid in members:
        records[rid]['controls'][cid]['shared_control_ref']={'region':owner,'name':name}
    refresh(records)


def refresh(records):
    """Refresh canonical behavior from actual member actions, never copy attempts."""
    for owner in records.values():
        for group in owner.get('shared_controls',{}).values():
            if group.get('status')=='separated':continue
            results=[];destinations=set();executed_members=set();broken=False
            for member in group['members']:
                rid,cid=member['region'],member['control'];region=records.get(rid,{})
                c=region.get('controls',{}).get(cid)
                if not c or c.get('shared_control_ref')!={'region':owner['id'],'name':group['name']}:
                    broken=True;continue
                for aid,a in region.get('actions',{}).items():
                    if a.get('control')!=cid or a.get('delivery')!='executed_receipt_zero':continue
                    result=a.get('result',{})
                    if not result.get('description'):continue
                    targets=list(a.get('interactive_regions',[]))
                    row={'source':{'region':rid,'control':cid,'attempt':aid},
                         'operation':a.get('operation'),'description':result['description'],
                         'evidence':result.get('evidence',''),'exception':result.get('exception'),
                         'destination_regions':targets}
                    results.append(row)
                    if result.get('exception')!='none':broken=True
                    if targets and a.get('operation') in ('tap','click') and not result.get('returns_to_previous'):
                        before=set(a.get('evidence',{}).get('before_regions',[]))
                        # A changed source/background is not a destination. Newly
                        # appearing surfaces are conflict hints, not causal proof.
                        direct=set(targets)-before-{rid}
                        if direct:
                            destinations.add(tuple(sorted(direct)));executed_members.add((rid,cid))
            group['results']=results
            from shared_control_review import signature
            reviewed=group.get('reviewed_signature')==signature(group)
            group['status']='needs_review' if broken or not results or (len(executed_members)>1 and len(destinations)>1 and not reviewed) else 'confirmed'

    synchronize_tasks(records)

def view(records,rid,cid):
    ref=records[rid]['controls'][cid].get('shared_control_ref')
    if not ref:return None
    return deepcopy(records.get(ref['region'],{}).get('shared_controls',{}).get(ref['name']))


def disclose(records,rid,cid):
    group=view(records,rid,cid)
    if not group:return []
    return [{'共享关系':group['name'],'关联区块':[records.get(m['region'],{}).get('name',m['region']) for m in group['members']],
             '共享范围':'行为知识；当前状态、位置和执行记录仍属于各自控件',
             '已观察结果':[{'来源区块':records.get(row['source']['region'],{}).get('name',''),
                 '结果':row['description'],'依据':row['evidence'],
                 '目的区块':[records.get(r,{}).get('name',r) for r in row['destination_regions']]} for row in group['results']],
             '用途':('共享结果存在冲突或成员缺失，需重新核对，不能据此跳过探索' if group['status']=='needs_review'
                    else '关联入口的已有行为证据；结合当前对象和状态判断适用性，不代表本地已执行') }]


def render(records,rid):
    lines=[]
    for cid,c in records[rid]['controls'].items():
        group=view(records,rid,cid)
        if not group:continue
        lines.append('共享控件「'+c['name']+'」：'+('关系需重新核对' if group['status']=='needs_review' else '关联入口行为已确认'))
        for row in group['results']:
            source=records.get(row['source']['region'],{}).get('name',row['source']['region'])
            lines.append('  '+source+'中实际观察：'+row['description'])
        lines.append('  不代表本区块已执行；本地状态与任务仍分别登记。')
    return lines


def extend_link(records,old_region,old_control,new_region,new_control,evidence,call):
    """Preserve local observations; only explicitly stable behavior is linked."""
    ref=records[old_region]['controls'][old_control].get('shared_control_ref')
    if ref:
        group=records[ref['region']]['shared_controls'][ref['name']]
        if group['status']!='confirmed':raise ValueError('旧共享关系仍有冲突，不能扩展')
        group['members'].append({'region':new_region,'control':new_control})
        records[new_region]['controls'][new_control]['shared_control_ref']=deepcopy(ref)
    else:
        actions=[{'region':old_region,'attempt':aid} for aid,a in records[old_region]['actions'].items()
                 if a.get('control')==old_control and a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('exception')=='none']
        label=records[old_region]['controls'][old_control]['name']+'（'+old_control+'）'
        link(records,label,[(old_region,old_control),(new_region,new_control)],evidence,actions)
        group=records[old_region]['shared_controls'][label]
    group.setdefault('membership_evidence',[]).append({'region':new_region,'control':new_control,'source_call':call,'evidence':evidence})


def synchronize_tasks(records):
    """Project one shared task definition onto local controls, without copying acts."""
    from action_owner_correction import effective_attempts
    active=set()
    for owner in records.values():
        for group in owner.get('shared_controls',{}).values():
            if group['status']!='confirmed':continue
            origin=group['members'][0];rr,cc=origin['region'],origin['control']
            source=records[rr]
            for name,definition in list(source.get('tasks',{}).items()):
                if definition.get('control')!=cc or definition.get('shared_task_ref'):continue
                if definition.get('handling')=='equivalent':continue
                key=(rr,name);active.add(key)
                members=[(rr,name,definition)]
                for member in group['members'][1:]:
                    rid,cid=member['region'],member['control'];region=records[rid]
                    tasks=region.setdefault('tasks',{})
                    local=next(((n,t) for n,t in tasks.items() if t.get('control')==cid and
                        (t.get('shared_task_ref') or {}).get('region')==rr and
                        (t.get('shared_task_ref') or {}).get('task')==name),None)
                    if local is None:
                        label=name if name not in tasks else name+'（共享：'+region['controls'][cid]['name']+'）'
                        if label in tasks:continue  # never overwrite an independent obligation
                        t={k:deepcopy(definition[k]) for k in ('action','task_type','reason','source_call') if k in definition}
                        t.update(control=cid,status='pending',handling='explore',equivalent_to='',attempts=[],
                            shared_task_ref={'region':rr,'task':name,'control':cc},
                            shared_definition={'handling':definition['handling'],'reason':definition['reason']})
                        if definition.get('prerequisite'):
                            t['prerequisite']={k:deepcopy(v) for k,v in definition['prerequisite'].items() if k not in ('scheduled','satisfied','last_check','recheck_requested')}
                        tasks[label]=t;local=(label,t)
                    local[1]['shared_task_active']=True
                    members.append((rid,*local))
                # Only actual member outcomes close shared execution work. A proxy
                # is never a new source of evidence and cannot form a coverage chain.
                winner=None
                for rid,n,t in members:
                    if t.get('status')!='done':continue
                    evidence=[aid for aid in effective_attempts(t) if
                        records[rid].get('actions',{}).get(aid,{}).get('control')==t.get('control') and
                        records[rid]['actions'][aid].get('delivery')=='executed_receipt_zero' and
                        records[rid]['actions'][aid].get('result',{}).get('exception')=='none']
                    if evidence:winner={'region':rid,'task':n,'attempts':evidence};break
                for rid,n,t in members:
                    if rid==rr or t.get('status')=='done':continue
                    t.pop('shared_result',None)
                    if winner:
                        t.setdefault('shared_prior_state',{'status':t['status'],'handling':t['handling']})
                        t.update(status='record_only',handling='record',shared_result=deepcopy(winner))
                    elif definition.get('handling')=='record' and not definition.get('shared_result'):
                        t.setdefault('shared_prior_state',{'status':t['status'],'handling':t['handling']})
                        t.update(status='record_only',handling='record',shared_result={'region':rr,'task':name,'observation_only':True})
                    elif t.get('shared_prior_state'):t.update(t.pop('shared_prior_state'))
                    t['reason']=definition['reason']
                    refs=records[rid]['controls'][t['control']].setdefault('task_refs',[])
                    if n not in refs:refs.append(n)
                # If the task was executed on another shared member, the origin
                # references that outcome too, without claiming a local attempt.
                if not winner and definition.get('shared_origin_state'):
                    definition.update(definition.pop('shared_origin_state'));definition.pop('shared_result',None)
                if winner and winner['region']!=rr and definition.get('status')!='done':
                    definition.setdefault('shared_origin_state',{'handling':definition['handling'],'status':definition['status']})
                    definition.update(handling='record',status='record_only',shared_result=deepcopy(winner))
    for rid,r in records.items():
        for t in r.get('tasks',{}).values():
            ref=t.get('shared_task_ref');origin=t.get('shared_origin_state')
            valid=False
            if ref:
                group=view(records,rid,t['control'])
                valid=(ref['region'],ref['task']) in active and bool(group and group['status']=='confirmed' and
                    any(m['region']==ref['region'] and m['control']==ref['control'] for m in group['members']))
                if not valid:
                    if t.get('shared_task_active',True):
                        t.setdefault('shared_history',[]).append({'reference':deepcopy(ref),'result':t.get('shared_result')})
                    t['shared_task_active']=False
                    t.pop('shared_result',None)
                    if t.get('shared_prior_state'):t.update(t.pop('shared_prior_state'))
            if origin:
                group=view(records,rid,t['control'])
                if not group or group['status']!='confirmed':
                    t.update(t.pop('shared_origin_state'));t.pop('shared_result',None)


def automatic_tasks(region,cid):
    return [{'任务':n,'结束条件':t['reason'],'状态':t['status'],'知识来源':'历史共享成员；名称和描述中的选中/当前值不是本图状态',
             '说明':'框架引用共享知识，本地未执行' if t.get('shared_result') else '共享任务尚未完成，仍需探索'}
            for n,t in region.get('tasks',{}).items() if t.get('control')==cid and t.get('shared_task_ref') and t.get('shared_task_active',True)]
