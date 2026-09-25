"""Observed entry ancestry and task continuation; ancestry is not a return edge."""


def entry_path(records, current):
    path=[];seen=set();rid=current
    while rid in records and rid not in seen:
        seen.add(rid);path.insert(0,rid)
        entries=records[rid].get('reached_by',[])
        if not entries:break
        source=None
        for e in reversed(entries):
            candidate=e['source_region'];action=records.get(candidate,{}).get('actions',{}).get(e['attempt'],{})
            if candidate!=rid and action.get('delivery')=='executed_receipt_zero' and action.get('operation')!='back':
                source=candidate;break
        if source is None:break
        rid=source
    return path


def path_for(records,state,current):
    path=state.get('region_path',[])
    return path[:path.index(current)+1] if current in path else entry_path(records,current)


def parent_region(records,state,current):
    path=path_for(records,state,current)
    return path[-2] if len(path)>1 else None


def destination_work(records, refs):
    """Choose work among observed destinations, not a unique navigation edge."""
    if len(refs)==1:return refs[0]
    if not refs:return None
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('handoff_region_tasks',Path(__file__).with_name('region_tasks.py'))
    tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    return min(refs,key=lambda rid:(tasks.coverage(records[rid],records)['complete'],
                                   records[rid].get('region_role')=='navigation'))


def advance(records,previous,state,source,binding,attempt):
    path=path_for(records,previous,source)
    refs=state['interactive_regions']
    if len(refs)==1:
        dest=refs[0]
        if dest in path:path=path[:path.index(dest)+1]
        else:path.append(dest)
    state['region_path']=path
    target=previous.get('deferred_routing_target')
    if target and target not in refs:state['deferred_routing_target']=target
    # A single entry action ends at its observed destination. The destination
    # owns its own inventory; do not turn opening a menu into testing every item.
    if binding.get('task_name') and refs and source not in refs:
        owner=records[binding.get('task_region',source)]
        task=owner.get('tasks',{}).get(binding['task_name'],{})
        action=records[source].get('actions',{}).get(attempt,{})
        if (task.get('task_type')=='single_action' and task.get('status') in ('pending','done')
                and not binding.get('preparatory_action') and binding.get('task_region',source)==source
                and task.get('control')==binding.get('control_ref')
                and action.get('operation') in ('click','tap')
                and action.get('delivery')=='executed_receipt_zero'
                and action.get('result',{}).get('exception')=='none'):
            dest=destination_work(records,refs)
            task['status']='done'
            task['result_evidence']='入口动作当时已执行，观察到区块：'+ '、'.join('「'+records[r]['name']+'」' for r in refs)+'。'
            task['completion_basis']={'attempt':attempt,'destination_region':dest,'destination_regions':list(refs),'rule':'single_action_destination_observed'}
            state['working_region']=dest
            state['region_path']=path[:path.index(dest)+1] if dest in path else path+[dest]
            state.pop('deferred_routing_target',None)
            state.pop('active_task',None)
    active=previous.get('active_task')
    if binding.get('task_name'):
        active={'region':binding.get('task_region',source),'name':binding['task_name']}
    if active:
        task=records[active['region']].get('tasks',{}).get(active['name'])
        if task and task['status']=='pending':state['active_task']=active
    if active and task and task.get('status')=='done':state['active_task']=active
    handoff(records,state)
    if active and records.get(active['region'],{}).get('tasks',{}).get(active['name'],{}).get('status')!='pending':
        state.pop('active_task',None)
    # Finished task evidence belongs to its original owner even if it crossed Regions.
    if binding.get('task_name'):
        task=records[binding.get('task_region',source)]['tasks'][binding['task_name']]
        task.setdefault('visited_regions',[])
        for rid in refs:
            if rid not in task['visited_regions']:task['visited_regions'].append(rid)


def foreground_work(records,state):
    """Choose independent observed work only after a continuous goal is settled."""
    observation=state.get('observation') or {}
    if state.get('next_action_mode')!='explore' or not observation:return None
    if observation.get('foreground',{}).get('exception','none')!='none':return None
    if state.get('execution_pending') or state.get('reason')=='verify_prepared_dependency':return None
    active=state.get('active_task') or {}
    task=records.get(active.get('region'),{}).get('tasks',{}).get(active.get('name'),{})
    if task.get('status')=='pending':return None
    last=state.get('last_action_result') or {}
    completed=task.get('status')=='done' or any(
        t.get('status')=='done' and last.get('action') in t.get('attempts',[])
        for t in records.get(last.get('region'),{}).get('tasks',{}).values())
    if not completed:return None
    target=state.get('deferred_routing_target')
    refs=state.get('interactive_regions',[])
    if target:return None
    import region_tasks
    choices=[rid for rid in refs if rid in records and not records[rid].get('out_of_scope_reason')
             and not region_tasks.coverage(records[rid],records)['complete']
             and not records[rid].get('registration_gaps')]
    if not choices:return None
    return min(choices,key=lambda rid:(bool(records[rid].get('task_inventory')),
                                      rid!=state.get('working_region')))


def handoff(records,state):
    target=foreground_work(records,state)
    if not target or target==state.get('working_region'):return False
    state['working_region']=target
    state.pop('navigation_handoff',None);state.pop('visual_navigation',None)
    state.pop('active_task',None)
    if state.get('deferred_routing_target')==target:state.pop('deferred_routing_target',None)
    return True
