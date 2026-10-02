"""Service-failure correction: suspend evidence, choose independent work, reobserve."""
import json
import hashlib
from pathlib import Path
import shutil
import jsonschema
import importlib.util

def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

discovery_step=helper("discovery_step")
atomic=helper("step_repair").atomic
read=helper("step_repair").read


def trigger(run,job,failure,failed_call):
    loop=job.get('switch_trigger')
    if loop:
        path=Path(run)/'exploration_loop.json'
        if loop.get('kind')!='exploration_loop' or not path.exists():raise ValueError('unsupported branch switch trigger')
        current=helper('exploration_loop').detect(read(path)['history'])
        if current!=loop:raise ValueError('loop evidence changed or invalid')
        return loop
    path=Path(run)/'calls'/str(failed_call)/'http_error.json'
    if not path.exists() or read(path)!=failure:raise ValueError('branch switch requires recorded model service error or exploration loop')
    return {'kind':'model_service_error','call':failed_call,'error':failure}


def readable_trigger(cause,records):
    if cause.get('kind')!='exploration_loop':return cause
    def name(ref):return records.get(ref,{}).get('name','历史区块（当前记录无法解析名称）')
    rows=[];previous=None;previous_action=None;previous_summary=None
    key="task_progress" if any(r.get('task') for r in cause['history']) else "navigation_progress" if any(r.get("navigating") or r.get("mode") in ("recover","recover_scope","review_result") for r in cause["history"]) else "progress"
    for row in cause['history']:
        task=row.get('task') or {}
        action_ref=row.get('recent_action_ref')
        action=row.get('recent_action','旧记录未提供动作摘要，不能推断执行了什么')
        summary=action
        if not action_ref:
            action_progress='旧记录缺少动作标识，无法确认本轮是否新执行；不能按行数推算动作次数'
        elif previous_action is None:
            action_progress='此段起点的最近一次已登记动作，不表示在本轮重新执行'
        elif action_ref==previous_action:
            if summary!=previous_summary:
                action_progress='同一动作的结果记录更新，不是新执行'
            else:
                action_progress='本轮没有新增已登记动作'
                action='本轮没有新增已登记动作；沿用上次结果，不代表再次执行'
        else:
            action_progress='与上轮相比有新的已登记动作'
        previous_action=action_ref;previous_summary=summary
        rows.append({'所在区块':[name(r) for r in row.get('position',[])],
            '工作区块':name(row.get('work')),'工作任务':task.get('name') if isinstance(task,dict) else task,
            '进展':'此段起点；后续与此比较' if previous is None else ('记录摘要未变化' if row.get(key,row.get('progress'))==previous else '记录摘要发生变化'),
            '动作进展':action_progress,'最近动作':action})
        previous=row.get(key,row.get('progress'))
    return {'类型':'探索循环','重复次数':cause['repetitions'],'循环长度':cause['cycle_length'],
        '判定依据':'框架发现同一目标下重复经过相同位置。导航或反复恢复段比较稳定控件清单、任务状态、已登记参数事实和动作关系，忽略观察措辞；普通活动任务仍保留参数显示变化依据。轮次可能只整理记录，不能把同一最近动作在多轮出现当作执行多次。请结合截图和动作历史判断是否确为循环，不能据此声称所有参数均未变化。',
        '近期经过':rows}


def request(root, run, job, frame, failure, failed_call):
    cause=trigger(run,job,failure,failed_call)
    snapshot,records,state=discovery_step.load(run)
    source=job['request'].get('source',{})
    if job.get('attempt'):
        binding=Path(run)/'action_attempts'/job['attempt']/'binding.json'
        if binding.exists():
            bound=read(binding)
            source={**source,'region':bound.get('region_ref'),'task_region':bound.get('task_region') or bound.get('working_region'),'task_name':bound.get('task_name'),'control':bound.get('control_ref')}
    affected=source.get('region') or state.get('working_region')
    work=source.get('task_region') or state.get('working_region')
    excluded={affected,work}
    if source.get('control'):
        for action in records.get(affected,{}).get('actions',{}).values():
            if action.get('control')==source['control'] and action.get('delivery')=='executed_receipt_zero' and action.get('result',{}).get('exception')=='none':
                excluded.update(action.get('interactive_regions',[]))
    candidates={}
    for rid,r in records.items():
        if rid in excluded or not helper('task_deferral').runnable(r,records):continue
        pending=[n for n,t in helper('task_deferral').pending_tasks(r,records)]
        if not pending and helper('region_tasks').coverage(r,records)['inventory_complete']:continue
        candidates.setdefault(r['name'],[]).append((rid,pending))
    candidates={n:v[0] for n,v in candidates.items() if len(v)==1}
    dynamic={'当前问题':{'失败步骤':job['stage'],'触发证据':readable_trigger(cause,records),
             '已执行动作':job.get('attempt'),'说明':'本次放弃处理原请求；不要求推断被拒原因或补写原结果。'},
             '暂挂区块':[records[rid]['name'] for rid in sorted(excluded) if rid in records],
             '工作任务':source.get('task_name'),
             '可继续的独立区块':[{'名称':n,'描述':records[rid].get('description',''),'待办':todo} for n,(rid,todo) in candidates.items()],
             '当前截图':'本次提供的观察画面；仅用于选择独立分支，不用于补写缺失的原动作结果。'}
    task=records.get(work,{}).get('tasks',{}).get(source.get('task_name'))
    if task:
        dynamic['原任务累计证据']=helper('history_context').task_goal(task,records,run)
        dynamic['累计证据用途']='判断所提办法是否已经尝试；不能只因最近动作是等待，就说之前未点击。本步不结算任务，也不推断未确认的最终效果。'
    prompt=Path(root)/'遍历prompt/纠错/暂挂分支并切换.prompt'
    text=json.dumps(dynamic,ensure_ascii=False,indent=2)
    loop_key=hashlib.sha256(json.dumps([state.get('working_region'),state.get('active_task'),helper('exploration_loop').progress_key(records,navigation=True)],sort_keys=True).encode()).hexdigest()
    allow_resume=cause.get('kind')=='exploration_loop' and not job.get('attempt') and not (Path(run)/'execution_pending.json').exists() and state.get('resolved_loop',{}).get('key')!=loop_key
    dynamic['继续原分支']='可以选择resume：指出一个具体可行的新办法，框架解除此次循环挂起并回到发现步，再由动作步执行。' if allow_resume else '不能再次以同一证据恢复原分支；选择独立区块或说明实际阻塞。'
    text=json.dumps(dynamic,ensure_ascii=False,indent=2)
    schema={'type':'object','properties':{'decision':{'type':'string','enum':['switch','stop']+(['resume'] if allow_resume else [])},
        'next_region':{'type':['string','null'],'enum':list(candidates)+[None]},'reason':{'type':'string'}},
        'required':['decision','next_region','reason'],'additionalProperties':False}
    return {'role':'branch_correction','stage':'branch_correction','system_prompt':prompt.read_text(),
        'user_prompt':text,'dynamic_prompt':text,'screenshots':[str(Path(frame).resolve())],
        'image_refs':[str(Path(frame).resolve())],'fixed_parts':[{'path':'纠错/暂挂分支并切换.prompt','text':prompt.read_text()}],
        'response_schema':schema,'switch_context':{'loop_key':loop_key,'trigger':cause,'snapshot':str(snapshot),'affected':affected,'excluded':sorted(r for r in excluded if r in records),'work':work,
        'task':source.get('task_name'),'candidates':{n:rid for n,(rid,_) in candidates.items()},'failed_call':failed_call}}


def commit(run, job, q, reply, call):
    run=Path(run);jsonschema.validate(reply,q['response_schema'])
    if not reply['reason'].strip():raise ValueError('missing switch reason')
    if reply['decision']=='stop':return None
    ctx=q['switch_context']
    cause=ctx['trigger']
    if trigger(run,job,cause.get('error'),cause.get('call'))!=cause:raise ValueError('trigger changed')
    if reply['decision']=='resume':
        if reply['next_region'] is not None or job.get('attempt') or (run/'execution_pending.json').exists():raise ValueError('resume cannot bypass unsettled execution')
        if str(discovery_step.load(run)[0])!=ctx['snapshot'] or read(run/'pending_step.json')['episode']!=job['path']:raise ValueError('resume evidence changed')
        def resume(records,state,*args):
            state['resolved_loop']={'status':'resolved','key':ctx['loop_key'],'source_call':call,'reason':reply['reason'],'trigger':cause}
            state.update(next_action_mode='discover',discovery_mode='relocate',phase='awaiting_discovery',interactive_regions=[],observation=None,pending_frame=q['screenshots'][0],reason='loop_review_resolved',correction_context='纠错已解决本次循环判断：'+reply['reason']+'。请重新定位后交给正常动作步骤；未执行任何新动作。')
        pointer=discovery_step.publish(run,'loop-resume-'+call,resume)
        job.update(status='resolved',branch_resolution={'call':call,'reply':reply,'knowledge':pointer});atomic(run/job['path'],job)
        (run/'pending_step.json').unlink()
        path=run/'exploration_loop.json';ledger=read(path)
        ledger.setdefault('reviewed_history',[]).append({'source_call':call,'history':ledger['history'],'reason':reply['reason']});ledger['history']=[];atomic(path,ledger)
        return {'resumed':True,'call':call,'knowledge':pointer}
    target=ctx['candidates'].get(reply['next_region'])
    if not target:raise ValueError('unknown independent branch')
    if str(discovery_step.load(run)[0])!=ctx['snapshot']:raise ValueError('knowledge changed before switch')
    if read(run/'pending_step.json')['episode']!=job['path']:raise ValueError('pending step changed')
    execution=run/'execution_pending.json';attempt=job.get('attempt')
    if execution.exists():
        if not attempt or read(execution).get('attempt')!=attempt:raise ValueError('different pending execution')
    if attempt:
        receipt=run/'action_attempts'/attempt/'receipt.json'
        if not receipt.exists() or read(receipt).get('exit_code')!=0:raise ValueError('delivery remains unconfirmed')
    folder=run/'suspended_steps'/call;folder.mkdir(parents=True,exist_ok=False)
    shutil.copy2(run/'pending_step.json',folder/'pending_step.json')
    if execution.exists():shutil.copy2(execution,folder/'execution_pending.json')
    frame=folder/'current.png';shutil.copy2(q['screenshots'][0],frame)
    evidence={'episode':job['path'],'attempt':attempt,'failed_call':ctx['failed_call'],'switch_call':call,
              'trigger':cause,'reason':reply['reason'],'status':'unresolved','archive':str(folder.relative_to(run))}
    def mutate(records,state,snapshot,temp):
        for rid in ctx['excluded']:
            region=records[rid]
            region.setdefault('registration_gaps',{})['suspended_branch']=evidence
            for task in region.get('tasks',{}).values():
                if (task.get('status')=='pending' and not (cause.get('kind')=='model_service_error'
                        and helper('step_repair').content_rejection(cause['error']))):
                    task.update(status='blocked',deferral=evidence,blocker={'condition':'review_required'})
        task=records.get(ctx['work'],{}).get('tasks',{}).get(ctx['task'])
        if task and task.get('status')=='pending':task.update(status='blocked',deferral=evidence,blocker={'condition':'review_required'})
        state.setdefault('suspended_updates',[]).append(evidence)
        state.update(working_region=target,next_action_mode='discover',discovery_mode='relocate',phase='awaiting_discovery',
            interactive_regions=[],observation=None,pending_frame=str(frame.relative_to(run)),
            discovery_trigger='branch-switch-'+call,reason='branch_suspended',
            handoff_summary='纠错选择继续'+reply['next_region']+'；尚未到达，先重新识别当前画面。')
        for key in ('active_task','inspection_region','deferred_routing_target','correction_context'):state.pop(key,None)
    pointer=discovery_step.publish(run,'branch-switch-'+call,mutate)
    job.update(status='suspended',branch_switch=evidence);atomic(run/job['path'],job)
    execution.unlink(missing_ok=True);(run/'pending_step.json').unlink()
    atomic(folder/'decision.json',{'reply':reply,'knowledge':pointer})
    return {'region':target,'call':call,'knowledge':pointer}


def correct(runner, job):
    """One correction call per failure, no retry of the rejected request."""
    policy=(Path(runner.root)/'遍历prompt/纠错/暂挂分支并切换.prompt').read_bytes()
    signature=hashlib.sha256(policy+json.dumps(helper('action_commands').schema(),sort_keys=True).encode()).hexdigest()
    if job.get('branch_switch_attempted') and job.get('branch_review_signature')==signature:return None
    if job.get('branch_switch_attempted'):
        job.setdefault('branch_review_history',[]).append({'previous_signature':job.get('branch_review_signature'),'reason':'纠错规则或动作能力已更新，原失败标记保留，允许一次按新规则复核'})
    job['branch_review_signature']=signature
    if runner.available()<1:return None
    job['branch_switch_attempted']=True;runner.save(job)
    folder=Path(runner.run)/Path(job['path']).parent
    frame=folder/'switch_current.png';runner.screenshot(frame)
    failure=job.get('service_failure',{'error':None,'call':None})
    q=request(runner.root,runner.run,job,frame,failure['error'],failure['call'])
    ref,reply=runner.call(q)
    return commit(runner.run,job,q,reply,ref)
