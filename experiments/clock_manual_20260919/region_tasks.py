"""Region-owned task proposals, deterministic coverage and ordinary return work.

Adapts original canonical-operation/handling semantics without importing Page/State.
"""
import json
from pathlib import Path

import identity_templates as templates


def helper(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def proposal_schema():
    value=json.loads((Path(__file__).parent/'遍历prompt/输出格式/区块探索任务.schema').read_text())
    value['properties']['operations']['items']['properties']['findings']={'type':'array','items':json.loads((Path(__file__).parent/'遍历prompt/输出格式/参数发现.schema').read_text())}
    value['properties']['operations']['items']['properties']['prerequisite']=helper('task_prerequisites').schema()
    return value


def coverage(region,records=None):
    if region.get('out_of_scope_reason'):
        return {'inventory_complete':True,'complete':False,'excluded':True,'pending':[],'blocked':[],'done':[],'record_only':[]}
    plan=region.get('task_inventory')
    tasks=region.get('tasks',{})
    missing=set(region['controls'])-set((plan or {}).get('controls',[]))
    complete=bool(plan and plan['inventory']=='complete' and not plan.get('review') and not missing and not region.get('registration_gaps',{}).get('task_proposal'))
    pending=[];blocked=[];done=[];recorded=[]
    for name,t in tasks.items():
        if not helper('task_prerequisites').in_scope(region,t,records):continue
        if t.get('status')=='blocked' and t.get('blocker',{}).get('condition')=='prerequisite':blocked.append(name);continue
        if t.get('coverage_exemption') and not helper('coverage_exemption').valid(records or {region['id']:region},t):pending.append(name);continue
        if t['handling']=='record':recorded.append(name);continue
        canonical=tasks.get(t['equivalent_to']) if t['handling']=='equivalent' and t.get('deferral',{}).get('retry_when')!='explicit_task_ownership_review' else t
        status=canonical.get('status') if canonical else 'pending'
        if status=='done':done.append(name)
        elif status=='blocked':blocked.append(name)
        else:pending.append(name)
    return {'inventory_complete':complete,'complete':complete and not pending and not blocked,
            'pending':pending,'blocked':blocked,'done':done,'record_only':recorded}


def plan_request(root,records,state,rid):
    normalize=helper('action_commands').normalize
    region=records[rid]
    schema=proposal_schema()
    # Strict API requires every property; local validation still accepts old evidence.
    schema['properties']['operations']['items']['required']+=['findings','prerequisite']
    schema['properties']['operations']['items']['properties']['control']['enum']=[c['name'] for cid,c in region['controls'].items() if not helper('shared_controls').automatic_tasks(region,cid)]+['']
    visible=set(state.get('observation',{}).get('control_refs',[]))
    dynamic={'区块':region['name'],'描述':region['description'],
        '上步观察交接':helper('target_observation').handoff(records,state),
        '描述来源':'已有区块记录，可能来自更早观察；当前对象与状态以截图为准。图片匹配定位不重新确认语义，登记名中的实例与本图不一致时，不把当前对象的任务绑定给历史实例；用partial说明需重新辨认的控件与归属缺口。',
        '补充清点原因':region.get('task_inventory',{}).get('review',{}).get('reason',''),
        '控件':[{'name':c['name'],'目标观察':helper('target_observation').describe(c,state.get('observation',{}).get('id')),
                 '当前定位':'本轮已定位，仍需看图核对' if cid in visible else '本轮未定位，仅为历史记录',
                 '已有任务':[n for n,t in region.get('tasks',{}).items() if t.get('control')==cid],
                 '已验证入口':helper('entry_evidence').disclose(region,cid,records),
                 '框架已关联共享任务':helper('shared_controls').automatic_tasks(region,cid),
                 '其他区块的同名入口历史':helper('entry_evidence').related(region,cid,records),
                 '已登记动作':[region['actions'][a]['result'] for a in c['action_refs']]} for cid,c in region['controls'].items()],
        '已有任务':region.get('tasks',{}),
        '其他区块（历史记录，不表示本图可见，不在本轮清点范围）':[{'名称':r['name'],'描述':r['description']} for other,r in records.items() if other!=rid],
        '说明':'只清点本区块，control逐字使用给定控件名称；其他区块入口不影响本区块清点。本区块内仍有未辨认或未登记入口时用partial，仅说明缺口，不为未知入口编造任务。入口及任务已列齐就用complete；尚未执行的explore任务不影响清点完整性，完成进度由框架另算。空任务不自动表示清点完成。'}
    # Backend control IDs are absent from the model's task catalog.
    dynamic['已有任务']=[{'name':n,'control':region['controls'][t['control']]['name'] if t['control'] else region['name'],
                         '知识来源':'历史共享任务，不是本地执行或当前状态' if t.get('shared_task_ref') else '本区块任务',
                         'handling':t['handling'],'status':t['status'],'reason':t['reason'],'action':normalize(t)['action'],'task_type':t['task_type'],
                         '已登记前置条件':t.get('prerequisite'),
                         '暂挂原因':t.get('deferral',{}).get('reason') or t.get('blocker',{}).get('reason',''),
                         '恢复条件':t.get('deferral',{}).get('retry_when','需显式复核；仅重新定位不解除' if t.get('blocker',{}).get('condition')=='review_required' else '')}
                        for n,t in region.get('tasks',{}).items()]
    # One ordered source for both the sent prompt and its per-file audit trail.
    paths=(
        '任务/区块探索任务.prompt',
        '任务/探索范围与退出.prompt',
        '任务/任务粒度与反馈.prompt',
        '任务/历史入口与共享复用.prompt',
        '任务/任务登记与补全.prompt',
        '任务/输入与搜索探索正反例.prompt',
        '共享/参数观察值.prompt',
        '共享/任务结束条件.prompt',
        '任务/参数关系调查.prompt',
        '任务/前置条件与恢复.prompt',
    )
    parts=[{'path':path,'text':(Path(root)/'遍历prompt'/path).read_text()} for path in paths]
    return {'pipeline_step':'discovery','stage':'task_proposal','role':'task_proposal','action_ready':False,
        'system_prompt':'\n\n'.join(part['text'] for part in parts),'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'dynamic_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'screenshots':[state['observation']['image']],'image_refs':[state['observation']['image']],
        'response_schema':schema,'fixed_parts':parts,
        'source':{'region':rid,'observation':state['observation']['id']}}


def apply_plan(region,reply,call,scope_review=False,records=None,state=None):
    import jsonschema
    jsonschema.validate(reply,proposal_schema())
    if not reply['evidence'].strip():raise ValueError('inventory needs evidence')
    normalize=helper('action_commands').normalize
    old=region.get('tasks',{});tasks=dict(old);seen=set()
    covered={t['control'] for t in old.values() if t.get('control') in region['controls']}
    for row in reply['operations']:
        names=[cid for cid,c in region['controls'].items() if c['name']==row['control']]
        if row['task_type']=='scroll' and row['control']=='':names=[None]
        if (row['task_type']=='scroll') != (row['action']=='scroll'):raise ValueError('scroll task/action mismatch')
        if len(names)!=1:
            if reply['inventory']!='complete' and not names:continue
            raise ValueError('task owner ambiguous or missing')
        name=row['name'].strip();cid=names[0]
        if not name or name in seen or not row['reason'].strip():raise ValueError('task name/reason missing or repeated')
        seen.add(name)
        if cid is not None:covered.add(cid)
        t={**{k:v for k,v in row.items() if k!='findings'},'control':cid,'status':'pending','source_call':call,'attempts':[]}
        if row['handling']=='record':t['status']='record_only'
        if row['handling']=='defer':t.update(status='blocked',blocker={'condition':'review_required','source_call':call})
        if name in old:
            prior=old[name]
            if scope_review and prior.get('status') in ('pending','blocked') and t['handling']=='record' and prior['handling']!='record':
                if normalize(prior)['action']!=t['action'] or any(prior[k]!=t[k] for k in ('control','task_type')):
                    raise ValueError('范围复核不能更换任务对象或动作')
                prior=helper('traversal_scope').record_only(prior,row['reason'],{'source_call':call,**({'policy':'task_scope_review'} if scope_review=='task_scope_review' else {})})
            if normalize(prior)['action']!=t['action'] or any(prior[k]!=t[k] for k in ('control','handling','equivalent_to','task_type')):
                raise ValueError('已有任务归属或操作不匹配：'+json.dumps({'任务名':name,'原控件':region['controls'].get(prior.get('control'),{}).get('name'),'回复控件':row['control'],'说明':'不同控件或不同探索目标应新建不同名称的任务；补充旧任务沿用原归属、动作、类型和处理方式。原记录确实错误时说明冲突并保留缺口；未执行且无事实/依赖的pending任务可用record_edit/task_control显式纠正；有历史则suspend_task保留记录并补建独立任务，不借普通清点改挂。'},ensure_ascii=False))
            t=prior
            if row.get('prerequisite') and row['prerequisite']!={k:v for k,v in (prior.get('prerequisite') or {}).items() if k not in ('scheduled','satisfied','last_check','recheck_requested')}:
                if prior.get('prerequisite'):t.setdefault('prerequisite_history',[]).append(dict(prior['prerequisite']))
                t['prerequisite']=dict(row['prerequisite'])
        if row.get('findings'):
            store_findings(t,row['findings'],{'region':region['id'],'task_region':region['id'],'task':name,'control':cid,'source_call':call})
        tasks[name]=t
    if scope_review:
        missing_review={n for n,t in old.items() if t.get('status') in ('pending','blocked') and t.get('handling')!='record'}-seen
        if missing_review:raise ValueError('旧任务范围复核遗漏未完成任务：'+'、'.join(sorted(missing_review)))
    for name,t in tasks.items():
        if t['handling']=='equivalent':
            canonical=tasks.get(t['equivalent_to'])
            if not canonical or canonical['handling']!='explore' or normalize(canonical)['action']!=normalize(t)['action'] or canonical['task_type']!=t['task_type'] or name==t['equivalent_to']:
                raise ValueError('equivalence must name a direct same-action exploration task')
        elif t['equivalent_to']:raise ValueError('unexpected equivalence')
    if reply['inventory']=='complete' and covered!=set(region['controls']):
        raise ValueError('complete inventory omitted registered controls')
    region['tasks']=tasks
    helper('entry_evidence').reuse(region)
    region['external_entry_policy']='record_only'
    for cid,control in region['controls'].items():
        control['task_refs']=[n for n,t in tasks.items() if t['control']==cid]
    region['task_inventory']={'inventory':reply['inventory'],'evidence':reply['evidence'],
                              'controls':sorted(covered),'source_call':call}


def commit_plan(root,run,call):
    reg=helper('register_update');discovery=helper('discovery_step')
    q,reply=helper('step_repair').submission(run,call)
    rid=q['source']['region']
    if q.get('role')=='task_correction':reply=reply['proposal']
    def mutate(records,state,snapshot,temp):
        if q.get('historical_inventory'):
            # publish rebases image paths for the new snapshot. Validate the
            # frozen evidence against the current persisted source, before rebasing.
            helper('historical_inventory').validate(discovery.load(run)[1][rid],q)
        elif state['observation']['id']!=q['source']['observation'] or rid not in state['interactive_regions']:
            raise ValueError('task inventory belongs to an old observation')
        apply_plan(records[rid],reply,call,scope_review='task_scope_review' if q.get('task_scope_review') else q.get('external_scope_review',False),records=records,state=state)
        helper('task_prerequisites').enroll(records,rid,call)
        active=state.get('active_task') or {}
        if active.get('region')==rid and (records[rid].get('tasks',{}).get(active.get('name'),{}).get('handling')=='record' or records[rid].get('tasks',{}).get(active.get('name'),{}).get('status')=='done'):
            state.pop('active_task',None)
        exception='none' if q.get('historical_inventory') else (state.get('observation') or {}).get('foreground',{}).get('exception','none')
        if exception in ('blocking_popup','system_error','unexpected_exit','external_app','unclassified'):
            for task in records[rid]['tasks'].values():
                if task.get('source_call')==call and task['status']=='blocked':
                    task['blocker']={'condition':'foreground_exception','exception':exception,'source_call':call}
        records[rid].get('registration_gaps',{}).pop('task_proposal',None)
        if reply['inventory']!='complete' and not q.get('historical_inventory'):
            state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,
                pending_frame=q['screenshots'][0],discovery_mode='local',inspection_region=rid,reason='task_inventory_incomplete',
                correction_context='任务清点反馈（来源区块：'+records[rid]['name']+'）：\n'+reply['evidence']+'\n请结合截图核对上述缺口；补充可见但未登记的控件，已登记的控件复用原身份。反馈只是待核对线索，不据此虚构控件、改挂旧任务或宣布探索完成。')
            state.pop('required_control',None)
    return discovery.publish(run,'task-plan-'+call,mutate)


def attach(root,records,state,working,base):
    """Route a local obligation or continuation; return to observed entry parent."""
    if state.get('next_action_mode')!='explore':return base
    if base.get('navigation_advice') and state.get('reason')=='navigation_from_foreground':return base
    refs=state['interactive_regions']
    rid=refs[0] if len(refs)==1 else (working if working in refs else None)
    active=state.get('active_task')
    continuing=records.get((active or {}).get('region'),{}).get('tasks',{}).get((active or {}).get('name'),{})
    in_progress=helper('task_prerequisites').in_scope(records.get((active or {}).get('region'),{}),continuing,records) and continuing.get('status')=='pending' and (bool(continuing.get('attempts')) or continuing.get('task_type') in ('parameter','scroll'))
    if state.get('visual_navigation') and base.get('navigation_advice') and base.get('navigation_path') and not in_progress:return base
    multi_continuation=rid is None and refs and in_progress
    if multi_continuation:rid=refs[0]
    # A completed entry does not finish its owner's Region. Return before
    # inventorying independent work on the destination surface.
    if working not in refs and not in_progress and base.get('navigation_advice'):return base
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
    if not progress['inventory_complete'] and (not gap or gap.get('recheck_after')):
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
        if continuation:
            task_region,name,task=continuation;cid=task['control']
        else:
            names=[n for n in progress['pending'] if region['tasks'][n]['handling'] in ('explore','equivalent')
                   and (region['tasks'][n]['control'] in visible or region['tasks'][n]['control'] is None)]
            if not names:
                unlocated=list(progress['pending'])
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
            if task['handling']=='equivalent':name=task['equivalent_to'];task=region['tasks'][name]
        kind=task.get('task_type','single_action')
        if rid!=task_region and kind=='single_action' and not in_progress:
            q=flow._assemble_action_context(root,records,state,task_region)
            q['pipeline_step']='action'
            return q  # A one-step task cannot silently become another Region's work.
        q['source'].update(task_name=name,task_region=task_region,task_type=kind,task_control=cid,task_action=task.get('action'))
        q['preparation_allowed']=True
        q['allow_scroll']=True
        q['allow_input']=True
        q['region_target']=region['name']
        q['region_image']=templates.image(region)
        q['region_image_assessment']=templates.assessment(templates.latest(region) or {})
        if rid!=task_region:
            q['allow_back']=True  # Task ownership is not a command to return to its Region.
        text,q['context_evidence']=helper('task_action_context').build(records,state,task_region,name,task)
        if rid==task_region and cid in visible:text+='\n当前可见的任务入口：'+region['controls'][cid]['name']
        text+='\n\n'+render_current(records,state)
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
    text+='\n\n若原任务控件本轮未定位，而已有另一入口的实际结果可能覆盖同一直接去向，可用none并申请request_task_review核对；未定位不等于消失，不能直接跳过或记完成。参数、创建保存目标不能用打开窗口代替。'
    q['user_prompt']=q['dynamic_prompt']=text;q['task_progress']=progress
    return q


def render_current(records,state):
    return '\n\n'.join(render(records[rid],records) for rid in dict.fromkeys(state.get('interactive_regions',[])) if rid in records)


def render(region,records=None):
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
        status='已完成' if name in c['done'] else '仅记录' if name in c['record_only'] else '受阻' if name in c['blocked'] else '待完成'
        lines.append(f'- {name}：{status}')
        if name not in c['record_only']:
            task=region['tasks'][name]
            effective=region['tasks'].get(task.get('equivalent_to'),task) if task.get('handling')=='equivalent' else task
            lines.extend('  '+fact for fact in describe(effective,records))
    return '\n'.join(lines)


def task_object_context(records,binding):
    owner=records[binding.get('task_region',binding['region_ref'])]
    task=owner['tasks'][binding['task_name']]
    actual=records[binding['region_ref']]
    return {'原任务区块':owner['name'],'原任务控件':owner['controls'].get(task.get('control'),{}).get('name','区块本身'),
            '当前绑定的动作区块':actual['name'],'当前绑定的动作控件':actual['controls'].get(binding.get('control_ref'),{}).get('name','尚未关联控件或区块动作'),
            '登记身份一致':owner['id']==actual['id'] and task.get('control')==binding.get('control_ref'),
            '核对说明':'这里比较后台登记身份，不证明视觉身份、当前上下文或动作成功；有待确认关联时仅作线索。对象不同可以是导航或后续操作，完成仍须有原对象对应的操作与结果链。'}


def settle_task(owner,binding,reply,attempt,records=None):
    name=binding.get('task_name')
    if not name:return
    task=owner['tasks'][name];assessment=reply.get('task_result')
    if not isinstance(assessment,dict):
        raise ValueError('缺少任务结果：task_result应为当前任务的结果对象；原任务名：'+name)
    if assessment.get('name')!=name:
        raise ValueError('任务名不匹配：'+json.dumps({'原任务名':name,'回复任务名':assessment.get('name'),
            '修正说明':'核对回复是否描述原任务；若是，沿用原任务完整名称，保留有依据的状态和观察。若不是，不可只改名冒充原任务结果。'},ensure_ascii=False))
    if not isinstance(assessment.get('evidence'),str) or not assessment['evidence'].strip():
        raise ValueError('缺少观察依据：任务名已匹配，请说明实际观察；原任务名：'+name)
    if (reply['action_result']['exception']=='external_app' and task.get('task_type')=='single_action'
            and not binding.get('preparatory_action') and binding.get('region_ref',owner['id'])==owner['id']
            and binding.get('control_ref')==task.get('control')):
        reason='已观察到入口跳转应用外；按当前探索范围仅记录，不继续外部流程。'+reply['action_result'].get('description','')
        task=helper('traversal_scope').record_only(task,reason,{'attempts':[attempt]})
        task['result_evidence']=assessment['evidence']
        if attempt not in task['attempts']:task['attempts'].append(attempt)
        owner['tasks'][name]=task
        return
    observed_popup_entry=(reply['action_result']['exception']=='blocking_popup'
        and task.get('task_type')=='single_action' and not binding.get('preparatory_action')
        and binding.get('region_ref')==owner['id'] and binding.get('control_ref')==task.get('control')
        and reply.get('exploration_update',{}).get('attempt_status')=='executed')
    if assessment['status']=='done' and reply['action_result']['exception']!='none' and not observed_popup_entry:
        raise ValueError('exception cannot verify task completion')
    findings=assessment.get('findings',[])
    same_object=(binding.get('region_ref',owner['id'])==owner['id']
                 and binding.get('control_ref')==task.get('control'))
    # Navigation is allowed, but it cannot silently substitute another control
    # for the object being investigated. Previously confirmed same-object history
    # may still satisfy a cumulative task after navigating away.
    supported=[]
    for aid in helper('action_owner_correction').effective_attempts(task):
        action=(records or {owner['id']:owner}).get(owner['id'],{}).get('actions',{}).get(aid,{})
        if (action.get('control')==task.get('control') and action.get('delivery')=='executed_receipt_zero'
                and action.get('result',{}).get('exception')=='none'
                and action.get('result',{}).get('description')
                and (not task.get('action') or action.get('operation')==task['action'])):
            supported.append(aid)
    if not same_object and assessment['status']=='done' and not supported:
        task['completion_review']={'attempt':attempt,'expected_region':owner['id'],
            'expected_control':task.get('control'),'actual_region':binding.get('region_ref'),
            'actual_control':binding.get('control_ref'),
            'reason':'本次结果属于另一操作对象，原任务缺少对应控件的完成证据；保留实际动作，可继续导航或探索其他任务。'}
        task.update(status='pending',result_evidence=task['completion_review']['reason'])
        if attempt not in task['attempts']:task['attempts'].append(attempt)
        return
    # Facts about the other object remain in the action record, not as parameters
    # of this task's control. The raw response is retained unchanged.
    if not same_object and not supported:findings=[]
    if helper('task_prerequisites').needs_parameter_facts(task) and assessment['status']=='done' and not (findings or task.get('findings')):
        raise ValueError('parameter task needs observed parameter facts')
    source={'region':binding.get('region_ref',owner['id']),'task_region':owner['id'],'task':name,
            'attempt':attempt,'control':binding.get('control_ref',task['control'])}
    store_findings(task,findings,source)
    status='blocked' if reply['action_result']['exception']=='unexpected_exit' else assessment['status']
    task.update(status=status,result_evidence=assessment['evidence'])
    if status=='done':task.pop('completion_review',None)
    if reply['action_result']['exception']=='unexpected_exit':
        task['blocker']={'condition':'review_required','exception':'unexpected_exit','attempt':attempt,
                         'reason':'该入口导致应用异常退出；恢复应用不代表入口故障已消除，不自动重试'}
        task['deferral']={'reason':task['blocker']['reason'],'retry_when':'explicit_crash_cause_resolved','attempt':attempt}
    if attempt not in task['attempts']:task['attempts'].append(attempt)


def store_findings(task,findings,source):
    """Visible facts and action-result facts share validation; provenance stays distinct."""
    import jsonschema
    schema=json.loads((Path(__file__).parent/'遍历prompt/输出格式/参数发现.schema').read_text())
    for fact in findings:
        jsonschema.validate(fact,schema)
        if not fact['name'].strip() or not fact['evidence'].strip():raise ValueError('parameter evidence missing')
        d=fact['domain']
        if d['type']=='enum' and not d['values']:raise ValueError('empty observed options')
        if d['type']=='integer' and d['min'] is not None and d['max'] is not None and d['min']>d['max']:raise ValueError('invalid observed range')
        evidence={**source,'evidence':fact['evidence']}
        previous=task.get('findings',{}).get(fact['name'])
        sources=list(previous.get('sources',[previous['source']])) if previous else []
        if previous and previous['domain']['type']!=d['type']:
            raise ValueError('参数类型冲突：任务「'+str(source.get('task',''))+'」事实「'+fact['name']+'」从'+previous['domain']['type']+'变为'+d['type']+'；不同参数应使用不同事实名称')
        if previous and previous['conditions']==fact['conditions'] and d['type']=='enum':
            d={**d,'values':list(dict.fromkeys(previous['domain']['values']+d['values']))}
        if evidence not in sources:sources.append(evidence)
        observations=list(previous.get('observations',[])) if previous else []
        if previous and not observations:
            observations.append({k:previous[k] for k in ('description','domain','conditions','source')})
        current={'description':fact['description'],'domain':fact['domain'],'conditions':fact['conditions'],'source':evidence}
        if current not in observations:observations.append(current)
        task.setdefault('findings',{})[fact['name']]={**fact,'domain':d,'source':evidence,'sources':sources,'observations':observations}
