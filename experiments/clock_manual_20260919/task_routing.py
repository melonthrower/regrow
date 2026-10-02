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
    # Result assessment owns completion. Once it has finished a single action,
    # hand off to destination work without changing the task's semantic result.
    if binding.get('task_name') and refs and source not in refs:
        owner=records[binding.get('task_region',source)]
        task=owner.get('tasks',{}).get(binding['task_name'],{})
        action=records[source].get('actions',{}).get(attempt,{})
        if (task.get('task_type')=='single_action' and task.get('status')=='done'
                and not binding.get('preparatory_action') and binding.get('task_region',source)==source
                and task.get('control')==binding.get('control_ref')
                and action.get('operation') in ('click','tap')
                and action.get('delivery')=='executed_receipt_zero'
                and action.get('result',{}).get('exception')=='none'):
            dest=destination_work(records,refs)
            task.setdefault('completion_basis',{}).update(
                destination_region=dest,destination_regions=list(refs))
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
    # Finished task evidence belongs to its original owner even if it crossed Regions.
    if binding.get('task_name'):
        task=records[binding.get('task_region',source)]['tasks'][binding['task_name']]
        task.setdefault('visited_regions',[])
        for rid in refs:
            if rid not in task['visited_regions']:task['visited_regions'].append(rid)
