"""Reuse shared task definitions/results and withdraw invalid projections.

Local attempts and control identities always remain with their actual owners.
"""
from copy import deepcopy


def synchronize_tasks(records):
    """Project one shared task definition onto local controls, without copying acts."""
    from action_owner_correction import effective_attempts
    from shared_controls import view
    from control_context import same_use
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
                        t={k:deepcopy(definition[k]) for k in ('action','task_type','reason','source_call','registration_kind','conditions') if k in definition}
                        t.update(control=cid,status='pending',handling='explore',equivalent_to='',attempts=[],
                            shared_task_ref={'region':rr,'task':name,'control':cc},
                            shared_definition={'handling':definition['handling'],'reason':definition['reason']})
                        if definition.get('prerequisite'):
                            t['prerequisite']={k:deepcopy(v) for k,v in definition['prerequisite'].items() if k not in ('scheduled','satisfied','last_check','recheck_requested')}
                        tasks[label]=t;local=(label,t)
                    if not local[1].get('attempts') and not same_use(local[1],definition):
                        local[1].setdefault('condition_history',[]).append({'conditions':local[1].get('conditions',[]),'source_task':name})
                        local[1]['conditions']=deepcopy(definition.get('conditions',[]))
                    local[1]['shared_task_active']=True
                    if definition.get('registration_kind'):
                        local[1]['registration_kind']=definition['registration_kind']
                    members.append((rid,*local))
                # Only actual member outcomes close shared execution work. A proxy
                # is never a new source of evidence and cannot form a coverage chain.
                winner=None
                from task_settlement import registered_result
                for rid,n,t in members:
                    if t.get('status')!='done' or not same_use(t,definition):continue
                    evidence=[aid for aid in effective_attempts(t) if
                        records[rid].get('actions',{}).get(aid,{}).get('control')==t.get('control') and
                        records[rid]['actions'][aid].get('delivery')=='executed_receipt_zero' and
                        records[rid]['actions'][aid].get('result',{}).get('exception')=='none' and
                        registered_result(t,records[rid]['actions'][aid])]
                    if evidence:winner={'region':rid,'task':n,'attempts':evidence};break
                for rid,n,t in members:
                    if (rid,n)==(rr,name) or t.get('status')=='done':continue
                    if not same_use(t,definition):
                        t.pop('shared_result',None)
                        if t.get('shared_prior_state'):t.update(t.pop('shared_prior_state'))
                        continue
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
                if winner and (winner['region'],winner['task'])!=(rr,name) and definition.get('status')!='done':
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
             '适用条件':t.get('conditions',[]),'说明':'框架引用共享知识，本地未执行' if t.get('shared_result') else '共享任务尚未完成，仍需探索'}
            for n,t in region.get('tasks',{}).items() if t.get('control')==cid and t.get('shared_task_ref') and t.get('shared_task_active',True)]



def reconcile_detached_tasks(records, state, affected, member, call):
    """After relation refresh, archive invalid inheritance; retain local evidence."""
    for rid, region in records.items():
        for name, task in list(region.get('tasks', {}).items()):
            if (rid, task.get('control')) not in affected: continue
            if not task.get('shared_task_ref') or task.get('shared_task_active', True): continue
            control = region['controls'][task['control']]
            control.setdefault('shared_task_history', []).append({'name': name, 'record': deepcopy(task), 'source_call': call})
            if task.get('attempts') or task.get('findings'):
                task.update(status='blocked', handling='explore', reason='共享已解除；保留本地尝试，重新核对任务定义')
                task.pop('shared_task_ref', None)
            else:
                del region['tasks'][name]
                control['task_refs'] = [n for n in control.get('task_refs', []) if n != name]
                if state.get('active_task') == {'region': rid, 'name': name}: state.pop('active_task', None)
            region.setdefault('task_inventory', {})['review'] = {'kind':'shared_behavior','reason': '共享关系已解除，按本地控件重新清点任务', 'source_call': call}
    records[member['region']].setdefault('task_inventory', {})['review'] = {'kind':'shared_behavior','reason': '控件已独立，核对本地任务', 'source_call': call}
