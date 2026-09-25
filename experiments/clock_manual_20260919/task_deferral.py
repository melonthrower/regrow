"""Isolate local repair gaps using existing blocked tasks and observed routes."""
from copy import deepcopy
from pathlib import Path
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def pending_tasks(region,records=None):
    if region.get('out_of_scope_reason'):return []
    return [(n,t) for n,t in region.get('tasks',{}).items()
            if t.get('status')=='pending' and t.get('handling')=='explore' and helper('task_prerequisites').in_scope(region,t,records)]


def choose(records,state):
    """Prefer other observed local entries, then shortest verified outbound route."""
    if state.get('next_action_mode')!='explore' or not state.get('observation'):return None
    refs=state['interactive_regions'];visible=set(state['observation']['control_refs'])
    ordered=sorted(refs,key=lambda r:r!=state.get('working_region'))
    for rid in ordered:
        names=[n for n,t in pending_tasks(records[rid],records) if t.get('control') is None or t['control'] in visible]
        if names:return {'region':rid,'task':names[0],'route':[]}
    choices=[];flow=helper('stepwise_flow')
    for rid,r in records.items():
        if rid in refs or not pending_tasks(r,records):continue
        path=flow.shortest_known_path(records,state,rid)
        choices.append({'region':rid,'task':pending_tasks(r,records)[0][0],'route':path})
    return min(choices,key=lambda c:(not bool(c['route']),len(c['route'] or []))) if choices else None


def defer(run,job,reason):
    """Return None when the failure cannot be isolated without trusting new facts."""
    if job.get('attempt') or job.get('requires_observation') or (Path(run)/'execution_pending.json').exists():return None
    stage=job['stage']
    if stage not in ('action','task_proposal','function_registration','task_result_review'):return None
    discovery=helper('discovery_step');_,records,state=discovery.load(run)
    q=job['request'];source=q.get('source',{});rid=source.get('task_region') or source.get('region')
    obs=state.get('observation') or {}
    # Deferring the selected task does not require navigating back to its hidden owner.
    visible=state.get('interactive_regions',[])
    selected_navigation=(stage=='action' and state.get('active_task')=={'region':rid,'name':source.get('task_name')}
                         and source.get('region') in visible)
    if (rid not in records or state.get('next_action_mode')!='explore' or (stage!='function_registration' and (not (rid in visible or selected_navigation)
            or source.get('observation')!=obs.get('id'))) or state.get('exception','none')!='none'
            or obs.get('foreground',{}).get('exception','none')!='none'):return None
    name=source.get('task_name')
    if stage in ('action','task_result_review') and (name not in records[rid].get('tasks',{}) or records[rid]['tasks'][name].get('status')!='pending'):return None
    episode=job['path'];decision={}
    blocked_by=job.get('blocked_by','none')
    exception=blocked_by if blocked_by in ('blocking_popup','system_error','unexpected_exit','external_app') else None
    condition='foreground_exception' if exception else 'control_not_visible' if blocked_by=='control_not_visible' or q.get('needs_task_inspection') else 'review_required'
    def mutate(records,state,snapshot,temp):
        region=records[rid]
        evidence={'reason':reason,'episode':episode,'observation':obs['id'],'source_call':job.get('call')}
        if stage in ('action','task_result_review'):
            task=region['tasks'][name]
            task.update(status='blocked',deferral={**evidence,'retry_when':'new_localized_control_observation'},
                        blocker={'condition':condition,'source_call':job.get('call'),'episode':episode,**({'exception':exception} if exception else {})})
            if state.get('active_task')=={'region':rid,'name':name}:state.pop('active_task',None)
        else:
            region.setdefault('registration_gaps',{})[stage]=evidence
        if exception:
            state.update(next_action_mode='recover',exception=exception,recovery_handoff=reason,source_call=job.get('call'))
            decision.update(region=rid,task=name,stage=stage,next={'stage':'recovery'},reason=reason)
            return
        selection=choose(records,state) or choose_unfinished(records,state)
        if selection:
            state['working_region']=selection['region'];state.pop('active_task',None)
            if selection['region'] not in state.get('interactive_regions',[]):state['deferred_routing_target']=selection['region']
            else:state.pop('deferred_routing_target',None)
        decision.update(region=rid,task=name,stage=stage,next=selection,reason=reason)
    discovery.publish(run,'defer-'+Path(episode).parent.name,mutate)
    return decision


def resume_localized(records,refs,call,foreground=None):
    """Only a newly accepted control crop can release a repair-deferred task."""
    for rid in refs:
        region=records[rid]
        for task in region.get('tasks',{}).values():
            if task.get('status')!='blocked':continue
            blocker=task.get('blocker')
            if blocker:
                if blocker.get('exception')=='unexpected_exit':continue
                condition=blocker['condition']
                if condition=='foreground_exception':
                    if not foreground or foreground.get('exception')!='none':continue
                elif condition!='control_not_visible':continue
            elif task.get('handling')!='explore' or not task.get('deferral'):continue
            control=region['controls'].get(task.get('control'),{});observations=control.get('observations',[])
            if not observations:continue
            latest=observations[-1]
            if latest.get('image') and latest.get('evidence',{}).get('source_call')==call:
                task['status']='pending'
                if task.get('handling')=='defer':task['handling']='explore'
                if task.get('deferral'):task['deferral']['resumed_by']=call
                if blocker:
                    task.setdefault('blocker_history',[]).append({**blocker,'resolved_by':call})
                    task.pop('blocker',None)
        # New localized knowledge can reopen a failed inventory; repeating the same job cannot.
        if any(c.get('observations') and c['observations'][-1].get('image') and
               c['observations'][-1].get('evidence',{}).get('source_call')==call for c in region['controls'].values()):
            gap=region.get('registration_gaps',{}).get('task_proposal')
            if gap:gap['recheck_after']=call


def runnable(region,records=None):
    """A failed registration stage is not a ban on the Region's other work."""
    if region.get('out_of_scope_reason'):return False
    if pending_tasks(region,records):return True
    progress=helper('region_tasks').coverage(region,records)
    if progress['inventory_complete']:return False
    gap=region.get('registration_gaps',{}).get('task_proposal')
    return not gap or bool(gap.get('recheck_after'))


def choose_unfinished(records,state):
    """Select known unfinished Regions, including those without task inventories."""
    if state.get('next_action_mode') not in ('explore','discover'):return None
    coverage=helper('region_tasks').coverage;flow=helper('stepwise_flow')
    current=state.get('working_region');choices=[]
    for rid,region in records.items():
        if rid==current or not runnable(region,records):continue
        visible=rid in state.get('interactive_regions',[])
        route=[] if visible else flow.shortest_known_path(records,state,rid)
        # Unknown paths remain ordinary navigation goals for Luna, never invented edges.
        choices.append({'region':rid,'route':route,'rank':(0 if any(t.get('prepares') and t.get('status')=='pending' for t in region.get('tasks',{}).values()) else 1,0 if visible else 1 if route else 2,len(route) if route else 0)})
    return min(choices,key=lambda c:c['rank']) if choices else None


def advance_unfinished(run):
    discovery=helper('discovery_step');_,records,state=discovery.load(run)
    selection=choose_unfinished(records,state)
    if not selection:return None
    import uuid
    def mutate(records,state,*args):
        target=selection['region'];state['working_region']=target;state.pop('active_task',None)
        state.pop('navigation_handoff',None)
        if state.get('next_action_mode')=='discover':
            state.pop('inspection_region',None);state.pop('required_control',None)
            state['discovery_mode']='relocate'
        if target not in state.get('interactive_regions',[]):state['deferred_routing_target']=target
        else:state.pop('deferred_routing_target',None)
    discovery.publish(run,'frontier-'+uuid.uuid4().hex,mutate)
    return selection
