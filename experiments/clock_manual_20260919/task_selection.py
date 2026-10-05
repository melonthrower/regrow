"""Select existing Region tasks and render their current progress."""
import identity_templates as templates


def attach(root,records,state,working,base):
    """Route a local obligation or continuation; return to observed entry parent."""
    from region_tasks import helper, coverage, plan_request
    if state.get('next_action_mode')!='explore':return base
    refs=state['interactive_regions']
    rid=refs[0] if len(refs)==1 else (working if working in refs else None)
    scroll_target=helper('inventory_scroll').target(records,state)
    if scroll_target:
        if scroll_target not in refs:
            return helper('stepwise_flow')._assemble_action_context(root,records,state,scroll_target)
        rid=scroll_target
    active=state.get('active_task')
    continuing=records.get((active or {}).get('region'),{}).get('tasks',{}).get((active or {}).get('name'),{})
    in_progress=helper('task_prerequisites').in_scope(records.get((active or {}).get('region'),{}),continuing,records) and continuing.get('status')=='pending' and (bool(continuing.get('attempts')) or continuing.get('task_type') in ('parameter','scroll'))
    if (base.get('navigation_advice') and state.get('reason')=='navigation_from_foreground'
            and not (in_progress and continuing.get('task_type') in ('parameter','scroll'))):return base
    if state.get('visual_navigation') and base.get('navigation_advice') and base.get('navigation_path') and not in_progress:return base
    multi_continuation=rid is None and refs and in_progress
    if multi_continuation:rid=refs[0]
    target=continuing.get('completion_action',{})
    if in_progress and target.get('region') in refs:rid=target['region']
    if rid is None:return base
    region=records[rid];progress=coverage(region,records)
    if progress.get('excluded'):
        return {**base,'action_ready':False,'stage':'region_complete','reason':'outside current run exploration scope'}
    if region.get('tasks') and region.get('external_entry_policy')!='record_only':
        return helper('traversal_scope').review_request(root,records,state,rid)
    flow=helper('stepwise_flow');routing=helper('task_routing')
    active=state.get('active_task');continuation=None
    if active:
        task=records[active['region']].get('tasks',{}).get(active['name'])
        if task and task['status']=='pending' and helper('task_prerequisites').in_scope(records[active['region']],task,records):continuation=(active['region'],active['name'],task)
    if state.get('deferred_routing_target')==working and working not in refs and not in_progress:return base
    gap=region.get('registration_gaps',{}).get('task_proposal',{})
    inventory_scroll=helper('inventory_scroll').active(records,state,rid)
    if not progress['inventory_complete'] and not inventory_scroll and (not gap or gap.get('recheck_after')):
        q=plan_request(root,records,state,rid);q['progress']=base.get('progress',{});return q
    if base.get('navigation_advice') and not in_progress and not progress['complete']:return base
    q=flow._assemble_local_context(root,records,state,rid)
    if multi_continuation:
        q['backend_candidates']=[{**candidate,'region_ref':ref} for ref in refs
            for candidate in flow._assemble_local_context(root,records,state,ref)['backend_candidates']]
    q['source']['working_region']=working
    q['pipeline_step']='action'
    q['task_progress']=progress
    if continuation or progress['pending']:
        visible=set(state['observation']['control_refs'])
        # Equivalence inherits coverage, not another control's execution identity.
        # Choose actual obligations before testing which entry is visible.
        pending=[n for n in progress['pending'] if region['tasks'][n]['handling']!='equivalent']
        if continuation:
            task_region,name,task=continuation;cid=task['control']
        else:
            names=[n for n in pending if region['tasks'][n]['handling']=='explore'
                   and (region['tasks'][n]['control'] in visible or region['tasks'][n]['control'] is None)]
            if not names:
                unlocated=list(pending)
                if not unlocated:
                    q.update(action_ready=False,stage='task_blocked')
                    choice=helper('task_deferral').choose(records,state)
                    if choice and choice['region']!=rid:return flow._assemble_action_context(root,records,state,choice['region'])
                    return q
                # Missing goal control on a normal surface is ordinary planning,
                # not an instruction to repeatedly inspect the same absent target.
                names=unlocated
            names.sort(key=lambda n:not bool(region['tasks'][n].get('prepares')))
            name=names[0];task=region['tasks'][name];cid=task['control'];task_region=rid
        kind=task.get('task_type','single_action')
        if rid!=task_region and kind=='single_action' and not in_progress:
            q=flow._assemble_action_context(root,records,state,task_region)
            q['pipeline_step']='action'
            return q  # A one-step task cannot silently become another Region's work.
        target=helper('task_settlement').completion_target(records[task_region],task)
        cid=target['control']
        q['source'].update(task_name=name,task_region=task_region,task_type=kind,task_control=cid,task_action=target['action'],completion_region=target['region'])
        q['preparation_allowed']=True
        q['allow_scroll']=True
        q['allow_input']=True
        q['region_target']=region['name']
        q['region_image']=templates.image(region)
        q['region_image_assessment']=templates.assessment(templates.latest(region) or {})
        if rid!=task_region:
            q['allow_back']=True  # Task ownership is not a command to return to its Region.
        text,q['context_evidence']=helper('task_action_context').build(records,state,task_region,name,task)
        if rid==task_region and cid in visible:text+='\n最近登记的任务入口（仍需核对当前截图）：'+region['controls'][cid]['name']
        text+='\n\n'+render_current(records,state,current_task={'region':task_region,'name':name})
    elif progress['complete']:
        functions=helper('region_functions')
        if not functions.review_current(region,records) and not region.get('registration_gaps',{}).get('function_registration'):
            request=functions.request(root,region,state,records);request['progress']=progress;return request
        parent=working if working!=rid and working in records else routing.parent_region(records,state,rid)
        if not parent:q.update(action_ready=False,stage='region_complete');return q
        navigation=flow._assemble_action_context(root,records,state,parent)
        previous=[a for a in region['actions'].values() if a.get('operation')=='back']
        if not navigation.get('navigation_path') and previous and (not previous[-1].get('interactive_regions') or rid in previous[-1]['interactive_regions']):
            q.update(action_ready=False,stage='return_blocked');return q
        # An observed origin is not a reverse edge. Reuse normal route planning.
        return navigation
    else:
        choice=helper('task_deferral').choose(records,state)
        if choice and choice['region']!=rid:
            other=choice['region']
            if other in refs:return attach(root,records,{**state,'interactive_regions':[other]},other,base)
            return flow._assemble_action_context(root,records,state,other)
        q.update(action_ready=False,stage='task_blocked');return q
    text+='\n\n完成状态由已登记的绑定动作计算，不申请另一次任务完成核对。当前目标未定位可用none补发现；准备动作不代替原动作。'
    q['user_prompt']=q['dynamic_prompt']=text;q['task_progress']=progress
    if inventory_scroll:helper('inventory_scroll').restrict(q)
    return helper('page_history').attach(q,records,state)



def render_current(records,state,current_task=None):
    return '\n\n'.join(render(records[rid],records,include_history=False,current_task=current_task) for rid in dict.fromkeys(state.get('interactive_regions',[])) if rid in records)



def render(region,records=None,*,include_history=True,current_task=None):
    from region_tasks import helper, coverage
    records=records if records is not None else {region["id"]:region}
    describe=helper("task_attempt_context").describe
    lines=[region['name']+'：探索任务']
    lines.extend(helper('shared_controls').render(records,region['id']))
    c=coverage(region,records)
    for name in region.get('tasks',{}):
        if not helper('task_prerequisites').in_scope(region,region['tasks'][name],records):
            lines.append(f'- {name}：本轮范围外，保留历史记录')
            continue
        if region['tasks'][name].get('coverage_exemption'):
            e=region['tasks'][name]['coverage_exemption']
            lines.append('- '+name+'：免重复探索（非执行完成）'+'；'+e['evidence']+'；未验证：'+e['unverified'])
            continue
        status='已探索（结果见动作记录）' if name in c['done'] else '仅记录' if name in c['record_only'] else '受阻' if name in c['blocked'] else '待完成'
        label='本轮当前任务（定义见任务卡）' if current_task=={'region':region['id'],'name':name} else name
        lines.append(f'- {label}：{status}')
        if include_history and name not in c['record_only']:
            task=region['tasks'][name]
            effective=region['tasks'].get(task.get('equivalent_to'),task) if task.get('handling')=='equivalent' else task
            lines.extend('  '+fact for fact in describe(effective,records))
    return '\n'.join(lines)
