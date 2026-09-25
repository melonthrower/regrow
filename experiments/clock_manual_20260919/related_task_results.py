"""Share actual action evidence across explicitly verified goals on its control."""
from copy import deepcopy


def candidates(region,control,operation,current_task):
    region_scroll=control is None and operation=='scroll'
    if not region_scroll and (not control or operation not in ('click','tap','input_text')):return []
    operations=('click','tap') if operation in ('click','tap') else (operation,)
    types=('scroll',) if region_scroll else ('single_action','parameter')
    return [{'name':name,'reason':t.get('reason',''),'task_type':t['task_type'],
             '已有参数事实':t.get('findings',{})} for name,t in region.get('tasks',{}).items()
            if name!=current_task and t.get('control')==control and t.get('handling')=='explore'
            and t.get('status')=='pending' and t.get('task_type') in types
            and t.get('action') in operations]


def apply(region,binding,reply,attempt,call,allowed,operation=None):
    items=reply.get('related_task_results',[])
    if items and reply['action_result']['exception']!='none':raise ValueError('异常结果不能完成关联任务')
    prepared={}
    for item in items:
        name=item['name'];task=deepcopy(region.get('tasks',{}).get(name,{}))
        scroll=(operation=='scroll' and binding.get('region_ref')==region['id']
                and binding.get('control_ref') is None and task.get('task_type')=='scroll'
                and task.get('action')=='scroll')
        if (name not in allowed or name in prepared or not item['evidence'].strip()
                or task.get('control')!=binding.get('control_ref') or task.get('handling')!='explore'
                or not (scroll or (task.get('task_type') in ('single_action','parameter')
                                   and task.get('action') in ('click','tap','input_text')))):
            raise ValueError('关联任务必须来自本次实际控件的候选清单，并有明确观察证据')
        findings=item.get('findings',[])
        if task['task_type']=='parameter' and not (findings or task.get('findings')):
            raise ValueError('关联参数任务需要已观察的取值或条件证据，投递成功不够')
        if findings:
            import importlib.util
            from pathlib import Path
            spec=importlib.util.spec_from_file_location('related_region_tasks',Path(__file__).with_name('region_tasks.py'))
            tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
            tasks.store_findings(task,findings,{'region':region['id'],'task_region':region['id'],'task':name,
                'control':binding['control_ref'],'attempt':attempt,'source_call':call})
        task.update(status='done',result_evidence=item['evidence'],completion_basis={
            'rule':'same_action_observed_goal','attempt':attempt,'source_call':call})
        task['attempts']=list(dict.fromkeys(task.get('attempts',[])+[attempt]))
        prepared[name]=task
    if prepared:region['tasks'].update(prepared)
