"""Render selected work and propose actions through the normal correction/binding path."""
import identity_templates as templates
from region_tasks import helper, coverage


def render_work(root, records, state, decision):
    """Build the selected request; no fallback selection or stop decisions here."""
    from stepwise_flow import _assemble_local_context, assemble_context
    from task_selection import render_current
    from task_proposer import TaskProposer
    kind, rid = decision['kind'], decision['region']
    working = decision['working_region']
    if kind in ('task_proposal','scope_review'):
        return TaskProposer.request(root, records, state, rid, scope_review=kind=='scope_review')
    if kind == 'function_registration':
        return helper('region_functions').request(root, records[rid], state, records)
    if kind == 'navigate':
        return assemble_context(root, records, state, rid)
    if kind != 'action':
        return {'stage':'scope_idle' if kind=='idle' else kind,
                'action_ready':False, 'reason':decision['reason'],
                'source':{'region':rid, 'working_region':working}}
    region = records[rid]
    q = _assemble_local_context(root, records, state, rid)
    refs = decision.get('source_regions', [rid])
    if len(refs) > 1:
        q['backend_candidates'] = [{**candidate,'region_ref':ref} for ref in refs
            for candidate in _assemble_local_context(root, records, state, ref)['backend_candidates']]
    q['source']['working_region'] = working
    q['pipeline_step'] = 'action'
    selected = decision['task']
    task_region, name = selected['region'], selected['name']
    task = records[task_region]['tasks'][name]
    target = helper('task_settlement').completion_target(records[task_region], task)
    cid = target['control']
    q['source'].update(task_name=name, task_region=task_region,
        task_type=task.get('task_type','single_action'), task_control=cid,
        task_action=target['action'], completion_region=target['region'])
    q.update(preparation_allowed=True, allow_scroll=True, allow_input=True,
        region_target=region['name'], region_image=templates.image(region),
        region_image_assessment=templates.assessment(templates.latest(region) or {}))
    if rid != task_region:
        q['allow_back'] = True
    text, q['context_evidence'] = helper('task_action_context').build(records,state,task_region,name,task)
    visible = set(state['observation']['control_refs'])
    if rid==task_region and cid in visible:
        text += '\n最近登记的任务入口（仍需核对当前截图）：'+region['controls'][cid]['name']
    text += '\n\n'+render_current(records,state,current_task=selected)
    text += '\n\n本任务所需登记：'+helper('task_settlement').registration_kind(task)+'。框架按实际绑定动作和所需信息登记计算进度；第三步说明实际反馈与信息缺口，无需另一次任务完成核对。当前目标未定位可用none补发现；准备动作不代替原动作。'
    q['user_prompt'] = q['dynamic_prompt'] = text
    q['task_progress'] = coverage(region, records)
    if helper('inventory_scroll').active(records, state, rid):
        helper('inventory_scroll').restrict(q)
    return helper('page_history').attach(q, records, state)


def request_from_run(root, run, region_ref=None, task_ref=None, *, decision=None, frame=None):
    from stepwise_flow import resolve_action_operations
    from traversal_scheduler import select_work
    import json
    from pathlib import Path
    run=Path(run);pointer=json.loads((run/'knowledge_current.json').read_text())
    snapshot=run/pointer['snapshot']
    source=json.loads((snapshot/'source.json').read_text())
    if source.get('record_format')!='region_image_knowledge':
        raise ValueError('historical record layout; rebuild saved evidence before reading current knowledge')
    records={p.parent.name:json.loads(p.read_text()) for p in (snapshot/'regions').glob('*/region.json')}
    state=json.loads((snapshot/'runtime_state.json').read_text())
    if state.get('next_action_mode')=='discover':raise ValueError('discovery required before action context')
    if region_ref is None:region_ref=state['working_region']
    if task_ref:
        task=records.get(task_ref['region'],{}).get('tasks',{}).get(task_ref['name'])
        if not task or task.get('status')!='pending':raise ValueError('原动作任务已不可继续，不能切换成其他任务')
        state['active_task']=dict(task_ref)
        region_ref=task_ref['region']
    if (snapshot/'recovery.json').exists():
        recovery=json.loads((snapshot/'recovery.json').read_text())
        if recovery['actions']:state['recovery_arrival']=recovery['actions'][-1]
    resolve_action_operations(records,run)
    # Resolve references only in this in-memory request, never rewrite knowledge.
    for ref,r in records.items():
        for v in r['observations']:
            if v.get('image'):v['image']=str((snapshot/f'regions/{ref}'/v['image']).resolve())
        for c in r['controls'].values():
            for v in c['observations']:
                for field in ('image','icon_image'):
                    if v.get(field):v[field]=str((snapshot/f'regions/{ref}'/v[field]).resolve())
                if v.get('source_image'):v['source_image']=str((snapshot/f'regions/{ref}'/v['source_image']).resolve())
    if state['observation'].get('image'):
        state['observation']['image']=str((run/state['observation']['image']).resolve())
    import importlib.util
    if state.get('visual_navigation'):
        nav_spec=importlib.util.spec_from_file_location('visual_backtrack',Path(__file__).with_name('visual_backtrack.py'))
        navigation=importlib.util.module_from_spec(nav_spec);nav_spec.loader.exec_module(navigation)
        navigation.project(records,state)
    import importlib.util
    spec=importlib.util.spec_from_file_location('region_tasks',Path(__file__).with_name('region_tasks.py'))
    tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    decision = decision or select_work(records, state, region_ref)
    result = render_work(root, records, state, decision)
    tasks.helper('action_candidates').attach_related(result,records,state)
    result=tasks.helper('target_observation').attach(result,records)
    tasks.helper('target_observation').attach_handoff(result,records,state,run)
    if state.get('navigation_handoff') and result.get('action_ready'):
        result['user_prompt']=result['dynamic_prompt']=result['user_prompt']+'\n\n自动回溯交接：'+json.dumps(state['navigation_handoff'],ensure_ascii=False)
    result['source']['snapshot']=pointer['snapshot']
    tasks.helper('page_context').attach(result,records,state,run=run)
    if frame is not None and result['stage'] != 'function_registration':
        history = result.get('screenshots', [])[1:] if result.get('source', {}).get('parameter_fact_review') else []
        frames = [str(Path(frame).resolve()), *history]
        result.update(screenshots=frames, image_refs=list(frames))
        tasks.helper('page_context').refresh(result)
        if result.get('action_ready'):
            result = tasks.helper('target_observation').refresh(result)
    return helper('operation_blocking').attach(result, records, state)



class ActionProposer:
    def __init__(self, repair):
        self.repair = repair

    def propose(self, request, resumed=None):
        request['role'] = 'action_selection'
        return resumed if resumed and resumed['stage']=='action' else self.repair.perform('action', request)
