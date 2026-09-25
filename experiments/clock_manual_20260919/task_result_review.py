"""Update-stage settlement of cumulative evidence, without a new GUI attempt."""
import json
from pathlib import Path
from copy import deepcopy
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def reviewable(task, observation):
    """Review new recovery evidence or an untried loop suspension once."""
    blocker=task.get('blocker',{});deferred=task.get('deferral',{})
    if not observation or task.get('status')!='blocked' or task.get('handling')!='explore' or deferred.get('reviewed_observation'):return False
    trigger=deferred.get('trigger',{})
    if trigger.get('kind')=='recovery':return bool(trigger.get('source_call') and not blocker)
    return bool(not task.get('attempts') and blocker.get('condition')=='review_required'
                and not blocker.get('exception') and trigger.get('kind')=='exploration_loop')


def later_entry_history(region,task):
    """A legacy blocked entry may have later evidence; this never settles it."""
    if (task.get('status')!='blocked' or task.get('handling')!='explore'
            or task.get('blocker') or task.get('deferral')):return []
    candidates=helper('action_owner_correction').control_history(region,task)
    return [aid for aid in candidates if aid not in task.get('attempts',[])
            and region['actions'][aid].get('result',{}).get('exception')=='none'
            and region['actions'][aid].get('result',{}).get('returns_to_previous') is not True
            and region['actions'][aid].get('text_delivered') is not False]


def next_deferred(root,run,frame):
    _,records,state=helper('discovery_step').load(run)
    if state.get('next_action_mode')!='explore' or state.get('exception','none')!='none':return None
    observation=(state.get('observation') or {}).get('id')
    for rid,region in records.items():
        if region.get('out_of_scope_reason'):continue
        for name,task in region.get('tasks',{}).items():
            if not helper('task_prerequisites').in_scope(region,task,records):continue
            if reviewable(task,observation) or later_entry_history(region,task):
                return request(root,run,{'task_region':rid,'task_name':name},[str(frame)])
    return None


def request(root,run,source,frames):
    snapshot,records,state=helper('discovery_step').load(run)
    rid=source.get('task_region') or source.get('region');name=source.get('task_name')
    task=records.get(rid,{}).get('tasks',{}).get(name)
    later=later_entry_history(records[rid],task) if task is not None else []
    deferred=task is not None and reviewable(task,(state.get('observation') or {}).get('id'))
    if task is None or not (task.get('status')=='pending' or deferred or later):raise ValueError('需要待完成任务或有未复核恢复/循环证据的暂挂任务')
    recovered=deferred and task.get('deferral',{}).get('trigger',{}).get('kind')=='recovery'
    paths=['更新/恢复后任务复核.prompt' if recovered else '更新/暂挂任务复核.prompt'] if deferred else ['更新/累计任务结果核对.prompt','共享/任务结束条件.prompt']
    parts=[{'path':p,'text':(Path(root)/'遍历prompt'/p).read_text()} for p in paths]
    history=later or helper('action_owner_correction').control_history(records[rid],task)
    history=[a for a in history if a not in task.get('attempts',[])][-3:]
    projected=deepcopy(task);projected['attempts']=list(dict.fromkeys(task.get('attempts',[])+history))
    dynamic={'本轮探索任务':name,'来源区块':records[rid]['name'],
             '任务目标与累计证据':helper('history_context').task_goal(task if later else projected,records,run),
             '任务结束条件':task['reason'],'说明':'本轮没有执行新动作；本轮观察图反映当前界面，另附历史原图时按标注时点阅读。'}
    if later:
        dynamic['独立入口历史']=[{'动作记录':aid,'直接效果':helper('history_context').task_goal(
            {'task_type':task['task_type'],'reason':task['reason'],'attempts':[aid]},records,run)} for aid in history]
        dynamic['历史间隔']='这些是独立尝试的直接前后效果，不是连续操作链；未提供期间全部操作，不能推断状态持续或跨尝试因果。'
        dynamic['本次核对原因']='旧任务暂挂后，同一控件另有已执行记录。比较原前后图与原结束条件；历史清单可能不完整，不能仅凭区块集合变化判完成。旧失败不抹去，新的历史也不代表当前界面可操作。'
    if history:
        dynamic['同控件历史复用']='额外提供同一已登记控件的既有动作：'+ '、'.join(history)+'。它们不是本任务的新执行；核对真实对象、原前后图及结束条件后才可采用。归属纠正不自动证明任务完成。'
    if recovered:
        dynamic.update(复核目的='原任务被提示中断，恢复界面后仍未完成；只核对能否继续，不判完成。',
                       恢复后的实际观察=task['deferral']['reason'],恢复证据来源=task['deferral']['trigger']['source_call'])
    elif deferred:
        path=helper('stepwise_flow').shortest_known_path(records,state,rid) or []
        route=[{'来源':records[e['source_region']]['name'],
                '入口':records[e['source_region']]['controls'].get(e['source_control'],{}).get('name',e['operation']),
                '动作':e['operation'],'到达':records[e['target_region']]['name']} for e in path]
        dynamic.update(复核目的='原任务尚未尝试，仅因旧导航循环被整支暂挂。只判断能否避开旧重复过程继续，不能判完成。',
                       目标控件=records[rid]['controls'].get(task.get('control'),{}).get('name'),
                       原暂挂原因={'原因':task['deferral']['reason'],'循环证据':helper('branch_switch').readable_trigger(task['deferral']['trigger'],records)},
                       最近登记区块={'说明':'历史观察，不是本轮截图识别结论','区块':[records[x]['name'] for x in state.get('interactive_regions',[]) if x in records]},
                       已知到达路径={'说明':'仅供参考；当前图中可用的后续入口可以直接使用，不必重复中间导航','路径':route})
    fields={'name':{'type':'string'},'status':{'type':'string','enum':['pending','blocked'] if deferred else ['done','pending','blocked']},'evidence':{'type':'string'}}
    result={'pipeline_step':'update','stage':'task_result_review','role':'task_result_review',
        'system_prompt':'\n\n'.join(p['text'] for p in parts),'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'screenshots':list(frames),'fixed_parts':parts,
        'response_schema':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False},
        'source':{'region':rid,'task_region':rid,'task_name':name,'task_control':task.get('control'),
                  'observation':(state.get('observation') or {}).get('id'),'snapshot':str(snapshot.relative_to(Path(run).resolve())),
                  'review_control_history':history}}
    if history:
        labels=[]
        for aid in history:
            for when in ('before','after'):
                frame=Path(run)/'action_attempts'/aid/(when+'.png')
                if frame.is_file() and str(frame.resolve()) not in result['screenshots']:
                    result['screenshots'].append(str(frame.resolve()))
                    labels.append('图'+str(len(result['screenshots']))+'：既有动作 '+aid+' 的'+('前' if when=='before' else '后')+'图，原任务意图不因当前复用而改写。')
        dynamic['既有动作原图']=labels
        result['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    result=helper('history_context').with_task_frames(root,run,result,task,rid)
    return helper('coverage_exemption').augment(root,run,result,records,state,rid,name)


def apply(region,state,name,assessment,call,available_history=()):
    task=region['tasks'][name]
    if assessment['name']!=name:raise ValueError('任务名不匹配：原任务名='+name+'；回复任务名='+assessment['name'])
    if not assessment['evidence'].strip():raise ValueError('累计结果核对缺少观察依据')
    if assessment['status'] not in ('done','pending','blocked'):raise ValueError('未知任务结果状态')
    later=later_entry_history(region,task)
    historical=bool(later and available_history and all(a in later for a in available_history))
    if task.get('status')=='blocked' and not historical:
        observation=(state.get('observation') or {}).get('id')
        if not reviewable(task,observation) or assessment['status']=='done':raise ValueError('暂挂复核只允许保留阻塞或恢复待探索，不能完成任务')
        task['deferral']['reviewed_observation']=observation
        task['result_evidence']=assessment['evidence']
        if assessment['status']=='pending':
            if task.get('blocker'):task.setdefault('blocker_history',[]).append({**task.pop('blocker'),'resolved_by':call,'evidence':assessment['evidence']})
            task['status']='pending';task['deferral']['resumed_by']=call
            state['working_region']=region['id'];state.pop('active_task',None)
        return
    if task.get('status')!='pending' and not historical:raise ValueError('原任务已不处于pending，不能覆盖旧结论')
    if assessment['status']=='done':
        if not (helper('action_owner_correction').effective_attempts(task) or task.get('findings') or available_history):
            control=region.get('controls',{}).get(task.get('control'),{}).get('name','未登记控件')
            raise ValueError(f'任务「{name}」对应控件「{control}」没有累计尝试或观察事实可用于本次核对，不能结算为done。'
                             '若引用其他控件的历史，先核对身份；确为同一对象的重复记录时，可用record_edit / merge_into显式修订，再核对历史实例与本任务结束条件。'
                             '合并不自动证明完成；身份或适用性不能确认时保留具体缺口，不为通过校验合并或补造历史。')
        if helper('task_prerequisites').needs_parameter_facts(task) and not task.get('findings'):raise ValueError('参数任务缺少已登记参数事实，需先补观察登记')
    if historical:
        task.setdefault('history',[]).append({'status':task['status'],'result_evidence':task.get('result_evidence',''),'reviewed_by':call})
    if assessment['status']=='done' and available_history:
        task['completion_basis']={'rule':'reviewed_control_history','attempts':list(available_history),'source_call':call}
    task.update(status=assessment['status'],result_evidence=assessment['evidence'])
    if assessment['status']=='blocked':
        task.update(blocker={'condition':'review_required','source_call':call},
                    deferral={'reason':assessment['evidence'],'source_call':call,'retry_when':'explicit_result_review'})
    elif assessment['status']=='done':
        task.pop('blocker',None);task.pop('deferral',None)
    if assessment['status']!='pending' and state.get('active_task')=={'region':region['id'],'name':name}:state.pop('active_task',None)


def commit(root,run,call):
    if (Path(run)/'execution_pending.json').exists():raise ValueError('动作尚未结算，不能无动作复核')
    discovery=helper('discovery_step');q,reply=helper('step_repair').submission(run,call)
    source=q['source'];old,_,_=discovery.load(run)
    if str(old.relative_to(Path(run).resolve()))!=source['snapshot']:raise ValueError('累计证据快照已变化，刷新后重新核对')
    def mutate(records,state,snapshot,temp):
        region=records[source['task_region']]
        if region['tasks'][source['task_name']].get('control')!=source['task_control']:raise ValueError('任务归属已变化，不能沿用原结果')
        history=source.get('review_control_history',[])
        available=helper('action_owner_correction').control_history(region,region['tasks'][source['task_name']])
        if any(a not in available for a in history):raise ValueError('同控件历史依据已变化')
        provided={str((Path(run)/f).resolve()) for f in q.get('screenshots',[])}
        if any(not all(str((Path(run)/'action_attempts'/aid/(when+'.png')).resolve()) in provided for when in ('before','after')) for aid in history):
            raise ValueError('历史复用核对缺少原前后图')
        if reply.get('coverage') is not None:
            if reply.get('name')!=source['task_name'] or reply.get('status')!='pending':raise ValueError('覆盖豁免不能冒充原任务done或更换任务')
            refs=source.get('coverage_candidates',[])
            for ref in refs:
                if not all(str((Path(run)/'action_attempts'/ref['attempt']/(when+'.png')).resolve()) in provided for when in ('before','after')):
                    raise ValueError('覆盖复核缺少候选真实前后图')
            helper('coverage_exemption').apply(records,state,source['task_region'],source['task_name'],reply['coverage'],refs,call)
        else:
            apply(region,state,source['task_name'],reply,call,history)
        helper('register_update').write_json(temp/'task_result_review.json',{'source_call':call,'task':source,'result':reply,'new_gui_action':False})
    return discovery.publish(run,'task-review-'+call,mutate)
