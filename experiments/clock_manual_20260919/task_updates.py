"""One task-update interface for the active goal and explicitly answered questions."""
from copy import deepcopy


def reference(region, name):
    return region + '/' + name


def catalog(records, binding):
    """Keep task ownership; disclose local goals, not another pending ledger."""
    from task_settlement import registration_kind
    rows=[]
    for rid in dict.fromkeys([binding['region_ref'], binding.get('task_region', binding['region_ref'])]):
        region=records[rid]
        for name, task in region.get('tasks', {}).items():
            row={'task':reference(rid,name),'region':rid,'name':name,
                 'control':task.get('control'),'control_name':region['controls'].get(task.get('control'),{}).get('name','区块本身'),
                 'status':task.get('status'),'action':task.get('action'),
                 'registration_kind':registration_kind(task),'conditions':task.get('conditions',[])}
            if task.get('status') in ('pending','blocked'):
                row.update(reason=task.get('reason',''),
                           blocker=task.get('blocker',{}),prerequisite=task.get('prerequisite'))
            rows.append(row)
    return rows


def current(reply, binding):
    value=reply.get('task_update')
    if isinstance(value,list):
        ref=reference(binding.get('task_region',binding['region_ref']),binding.get('task_name',''))
        return next((row for row in value if row.get('task')==ref),{})
    return value or reply.get('task_result') or {}


def apply(owner,binding,reply,attempt,records,*,receipt,labels,candidates,settle):
    """Called within the normal update transaction after real identity registration."""
    from task_settlement import (completion_target,recorded_match,registration_kind,action_name)
    rows=reply['task_update'];allowed={row['task']:row for row in candidates or []}
    selected={};active=binding.get('task_update_ref') or reference(owner['id'],binding.get('task_name',''))
    actual=records[binding['region_ref']];action=actual['actions'][attempt]
    for row in rows:
        ref=row['task']
        if ref not in allowed or ref in selected:
            raise ValueError('任务更新须引用本次披露的唯一任务，不得重复或新建任务')
        candidate=allowed[ref]
        region=owner if ref==active else records[candidate['region']]
        task=region.get('tasks',{}).get(candidate['name'])
        if task is None:raise ValueError('任务已迁移或不再存在，不能沿旧候选结算其他任务')
        if (task.get('status') not in ('pending','blocked') or task.get('handling')!='explore'
                or task.get('shared_task_ref') or task.get('coverage_exemption')):
            raise ValueError('只能更新本次未结束的本地探索任务')
        migrated=ref==active and any(h.get('region')==candidate['region'] and h.get('control')==candidate['control']
                                    and h.get('attempt')==attempt for h in task.get('ownership_history',[]))
        if (candidate['control']!=task.get('control') and not migrated
                or candidate['conditions']!=task.get('conditions',[])):
            raise ValueError('任务身份或适用条件已变化，需重新核对本次候选')
        if ref!=active:
            target=completion_target(region,task)
            blocker=task.get('blocker',{})
            if (registration_kind(task)!='control_effect' or task.get('prepares')
                    or blocker.get('exception') or blocker.get('condition') not in (None,'review_required')
                    or task.get('prerequisite') or row.get('entry') or row['findings']
                    or row.get('next_action') is not None or not row.get('knowledge','').strip()
                    or row.get('registration_gap')):
                raise ValueError('其他任务仅可登记本次实际控件已回答的用途问题；不得顺带结束参数、前置或异常任务')
            observed={**target,'action':action_name(action.get('operation'))}
            if (target.get('control') is None or not recorded_match(actual,attempt,action,observed,receipt)
                    or action.get('result',{}).get('exception')!='none'):
                raise ValueError('旧问题答案必须来自同一已确认实际控件的成功投递与观察')
        selected[ref]=(region,task,row)
    if binding.get('task_name') and active not in selected:
        raise ValueError('更新需保留本轮当前任务的进展，即使本次只是准备动作')
    active_row=selected.get(active,(None,None,{}))[2]
    if active_row:
        # Existing settlement owns entry/parameter registration and preparations.
        settle(owner,binding,{**reply,'task_update':active_row},attempt,records,
               receipt=receipt,labels=labels,explicit=True)
    for ref,(region,task,row) in selected.items():
        if ref==active:continue
        if not set(task.get('conditions',[])).issubset(set(action.get('conditions',[]))):
            raise ValueError('本次动作没有确认旧问题所需适用条件，不能借用其他条件用途的结果')
        for field in ('blocker','deferral'):
            if task.get(field):
                task.setdefault(field+'_history',[]).append({**task.pop(field),'resolved_by':attempt})
        # Publish only the observed use, never an unconditional answer inferred
        # from a result that was registered under a narrower condition.
        task.update(status='done',conditions=deepcopy(action.get('conditions',[])),knowledge=row['knowledge'].strip(),
                    result_evidence=action['result']['description'],
                    completion_basis={'rule':'question_answered_by_registered_action',
                        'registration_kind':registration_kind(task),'region':actual['id'],
                        'control':action['control'],'operation':action['operation'],'attempt':attempt,
                        'evidence':action['result'].get('evidence',''),
                        'meaning':'本次真实结果回答旧问题；旧尝试和实际动作归属不变'})
    action['task_update']=deepcopy(rows)


def latest_suggestion(records,task):
    """Null on the latest task attempt expires earlier advice."""
    refs=task.get('attempts',[])
    if not refs:return None
    actions=[r['actions'][refs[-1]] for r in records.values() if refs[-1] in r.get('actions',{})]
    return actions[0].get('next_action') if len(actions)==1 else None
