"""One bounded Region task round: inventory if needed, action, update, then pause."""
import argparse
import json
from pathlib import Path
import shutil

from recover_external import RecoveryRun
from register_update import read,write_json,commit_update
from stepwise_flow import StepwiseFlow,assemble_current_context,bind_action_target
from region_tasks import commit_plan
from update_step import build_update_request
import discovery_step
import jsonschema
from action_commands import commands,execute as execute_action,validate as validate_action
import region_functions
import recover_loop
import progress
import step_repair
import visual_backtrack
import exploration_loop
import traversal_scope


def foreground_window(transport):
    if hasattr(transport,"foreground_window"):return transport.foreground_window()
    import re
    result=transport.adb(['shell','dumpsys','window'])
    if result.returncode!=0:return None
    match=re.search(r'mCurrentFocus=Window\{([^}]+)\}',result.stdout.decode(errors='replace'))
    return match.group(1) if match else None


def window_evidence(window, target):
    """Expose actual window ownership; system overlays still need visual context."""
    if isinstance(window,dict):return window
    import re
    match=re.search(r'\bu\d+\s+([A-Za-z0-9_.]+)/[^\s}]+',window or '')
    package=match.group(1) if match else None
    return {'目标应用':target,'前台应用':package,'与目标应用一致':package==target if package else None,
            '窗口记录':window,'来源':'Android mCurrentFocus；读取失败或不能解析时未知'}


def system_action_changed(action, before, after, before_window=None, after_window=None):
    if action not in ('back','key_press','hotkey'):return False
    if action in ('key_press','hotkey'):
        return bool(before_window and after_window and before_window!=after_window) or not visual_backtrack.same_surface(before,after)
    # Back has no image coordinate. A stable Android window tolerates animations
    # and live clocks; changed/unknown windows retain the visual check.
    if before_window and after_window:return before_window!=after_window
    return not visual_backtrack.same_surface(before,after)


def build_attempt_update(root,transport,folder):
    run=transport.run
    snapshot,records,state=discovery_step.load(run)
    binding=read(folder/'binding.json');proposal=read(folder/'proposal.json');receipt=read(folder/'receipt.json')
    after_window=read(folder/'after_window.json')
    owner=records[binding['region_ref']];work=records[binding['working_region']]
    dynamic={'动作后前台应用证据':after_window,'目标应用':transport.package,'工作区块':work['name'],'实际来源区块':owner['name'],
        '实际入口':'系统返回' if proposal['action']=='back' else owner['name'] if proposal['action'] in ('scroll','wait') else owner['controls'][binding['control_ref']]['name'] if binding.get('control_ref') in owner['controls'] else proposal['target'],
        '动作意图':proposal,'实际动作':receipt.get('executed_steps', [proposal]),'回执':receipt,
        '登记说明':'保留工作区块，按实际前后图登记落点；系统返回属于来源区块，无控件，不为它新建控件。'}
    import source_region_candidates as source_candidates
    recalled=source_candidates.recall(records,binding,proposal['action'],folder.name)
    from region_behavior_split import history as source_history
    dynamic['来源区块历史行为比较']=source_history(owner,proposal.get('target',''))
    if not recalled['confirmed']:
        dynamic['旧入口说明']='这里按旧入口名称提供线索，不证明本次来源身份或历史所在标签。'
    if binding.get('association'):
        dynamic['控件关联待核对']=binding['association']
        if binding['association'].get('status')=='unconfirmed':
            dynamic['动作请求来源上下文']=dynamic.pop('实际来源区块')
            dynamic['来源身份说明']='上列区块只是动作请求的上下文，不证明实际控件属于该区块；按原前后图登记真实归属，不为迎合上下文迁移控件。'
        dynamic['登记说明']+=' 本动作已按模型坐标执行，控件身份尚未确认；不要把候选当事实。仍可见的实际控件按普通更新登记名称及点击框，空白关闭不虚构控件。'
    if binding.get('task_name'):
        dynamic['本轮探索任务']=binding['task_name']
        if binding.get('preparatory_action'):dynamic['准备动作说明']='本动作与原定控件或动作不同。正常导航和后续操作允许执行；只有原任务对象对应的证据链满足目标时可done，不能因另一入口也打开类似界面就完成原入口任务。'
        task=records[binding.get('task_region',binding['region_ref'])]['tasks'][binding['task_name']]
        from history_context import task_goal
        dynamic['任务目标']=task_goal(task,records,run)
        from region_tasks import task_object_context
        dynamic['任务与实际对象核对']=task_object_context(records,binding)
    from region_tasks import coverage
    progress_now=coverage(owner,records)
    dynamic['来源区块已有任务']=[{'name':n,'action':t.get('action'),'control':owner['controls'].get(t.get('control'),{}).get('name'),
        'status':'done' if n in progress_now['done'] else 'record_only' if n in progress_now['record_only'] else t.get('status')}
        for n,t in owner.get('tasks',{}).items()]
    import related_task_results
    dynamic['同次动作可核对的其他任务']=related_task_results.candidates(owner,binding.get('control_ref'),proposal['action'],binding.get('task_name') if binding.get('task_region',binding['region_ref'])==binding['region_ref'] else None)
    import history_matching
    ranking=history_matching.scan(records,snapshot,folder/'after.png',scope=history_matching.foreground_scope.load(run,folder/'after.png'))
    dynamic['当前截图视觉匹配到的既有区块']=[{'region_ref':r['region'],'name':records[r['region']]['name'],
        'control_positions':[h['box'] for h in r['anchors']]} for r in ranking if r['anchors']]
    from update_step import known_regions
    dynamic['已知区块']=known_regions(records,state,binding,dynamic['当前截图视觉匹配到的既有区块'],source_destinations=recalled['destinations'])
    reference=source_candidates.reference(records,snapshot,recalled,dynamic['当前截图视觉匹配到的既有区块'],folder/'after.png')
    from history_matching import with_history as named_candidates
    dynamic['已知区块'],region_names=named_candidates(records,dynamic['已知区块'])
    labels={rid:label for label,rid in region_names.items()}
    dynamic['当前截图视觉匹配到的既有区块']=[
        {**{k:v for k,v in hit.items() if k!='region_ref'},'name':labels[hit['region_ref']]}
        for hit in dynamic['当前截图视觉匹配到的既有区块']]
    dynamic['本次入口历史落点']=source_candidates.describe(recalled,labels)
    dynamic['区块名称使用']='身份引用使用已知区块中的完整name；同名区块附描述区别，仅用于本轮关联，不代表新建或合并。'
    u=build_update_request(root,dynamic,[str((folder/n).relative_to(run)) for n in ['before.png','after.png']])
    if binding.get('task_name'):
        from history_context import with_task_frames
        u=with_task_frames(root,run,u,task,binding.get('task_region',binding['region_ref']))
    u=source_candidates.attach(u,reference,labels)
    u=history_matching.attach(u,records,ranking,region_names,snapshot)
    u['region_names']=region_names
    write_json(folder/'update_request.json',u)
    return u


def resume_update_request(root,transport,folder):
    receipt=read(folder/'receipt.json')
    if receipt.get('exit_code')!=0:raise ValueError('delivery not confirmed; do not retry')
    if (folder/'update_request.json').exists():return read(folder/'update_request.json')
    # A confirmed action awaits observation, never another delivery.
    fresh=not (folder/'after.png').exists()
    if fresh:transport.screenshot(folder/'after.png')
    if not (folder/'after_window.json').exists():
        evidence=window_evidence(foreground_window(transport),transport.package) if fresh else {
            '与目标应用一致':None,'来源':'已保存动作后截图缺少同期窗口证据，仅依据该截图核验'}
        write_json(folder/'after_window.json',evidence)
    return build_attempt_update(root,transport,folder)


def _run_step(root,run,out):
    root,run,out=Path(root).resolve(),Path(run).resolve(),Path(out).resolve()
    out.mkdir(parents=True,exist_ok=False)
    manifest=read(run/"run_manifest.json")
    if manifest.get("platform")=="desktop":
        from desktop_transport import DesktopRun
        transport=DesktopRun.__new__(DesktopRun);transport.configure(manifest)
    else:transport=RecoveryRun.__new__(RecoveryRun)
    transport.root=root;transport.run=run;transport.ledger=out/'budget.json'
    manifest=read(run/'run_manifest.json');transport.device=manifest['device'];transport.package=manifest['app']
    transport.account={'max_http':6,'max_gui_commands':6,'http_started':0,'gui_started':0,'status':'running'};transport.save()
    write_json(out/'knowledge_before.json',read(run/'knowledge_current.json'))
    selection_window=foreground_window(transport)
    write_json(out/'selection_window.json',{'window':selection_window})
    transport.screenshot(out/'current.png')
    calls=[]
    def call(q):
        ref,reply=transport.call(q);calls.append(ref);return ref,reply
    def current():
        step_repair.helper('coverage_exemption').refresh(run)
        _,known,state=discovery_step.load(run)
        discovery_step.registration().sibling('traversal_scope').exclude_known_external(run,known,state)
        discovery_step.retire_completed_goal(run)
        step_repair.helper('task_prerequisites').prioritize(run,out/'current.png')
        if discovery_step.load(run)[2].get('reason')=='verify_prepared_dependency' and discovery_step.load(run)[2].get('next_action_mode')=='discover':
            raise step_repair.Paused('ready_next_round','准备任务已完成；下一轮观察目标是否解锁')
        snapshot,known,state=discovery_step.load(run)
        candidate=None
        def current_request():
            nonlocal candidate
            if candidate is None:candidate=assemble_current_context(root,run)
            return candidate
        historical=discovery_step.registration().sibling('historical_inventory').request(
            root,snapshot,known,state,current_request=current_request)
        if historical:return historical
        q=current_request()
        if q['stage'] in ('region_complete','task_blocked','return_blocked') and not q.get('needs_task_inspection'):
            if discovery_step.registration().sibling('task_deferral').advance_unfinished(run):
                q=assemble_current_context(root,run)
            else:
                deferred=step_repair.helper('task_result_review').next_deferred(root,run,out/'current.png')
                if deferred:return deferred
                if not (run/'execution_pending.json').exists() and not step_repair.pending(run):
                    q.update(stage='scope_idle',action_ready=False,reason='当前无可执行任务；保留暂挂及登记缺口，不声明全图完成')
        if discovery_step.locate_task_control(run,q,out/'current.png'):
            q=assemble_current_context(root,run)
        if q['stage']!='function_registration':
            q.update(screenshots=[str((out/'current.png').resolve())],image_refs=[str((out/'current.png').resolve())])
            step_repair.helper('region_scroll').attach(run,discovery_step.load(run)[2],q)
        return q
    repair=step_repair.Runner(root,run,call,transport.screenshot,lambda:transport.account['max_http']-transport.account['http_started'])
    if (run/'ownership_review.json').exists():
        result=step_repair.helper('ownership_review').run(root,transport,out,call)
        write_json(out/'result.json',{**result,'gui_actions':transport.account['gui_started']})
        transport.account['status']=result['status'];transport.save();return
    resumed=None
    step_repair.reopen_blocked(run,out/'current.png')
    pending=step_repair.pending(run)
    if pending:
        if pending.get('pre_dispatch_review') and pending['stage']=='action':
            # A paused round must not confirm a historical frame as the current one.
            frame=str(out/'current.png')
            pending['pre_dispatch_review'].update(current=frame,window=selection_window)
            pending['request'].update(screenshots=[frame],image_refs=[frame])
            pending['history'].append({'observation':frame,'reason':'投递前重新确认使用本轮新截图；原提案仍未执行'})
            repair.save(pending)
        resumed=repair.perform(pending['stage'])
        if resumed['stage'] in ('task_result_review','shared_control_review'):
            write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0,'task_result_review':resumed['result']})
            transport.account['status']='ready_next_round';transport.save();return
        if resumed['stage']=='update':
            attempt=resumed['attempt'];pointer=resumed['result']
            write_json(run/'action_attempts'/attempt/'commit.json',pointer)
            (run/'execution_pending.json').unlink(missing_ok=True)
            write_json(out/'result.json',{'status':'updated','calls':calls,'attempt':attempt,'gui_actions':0,'pointer':pointer})
            transport.account['status']='paused_after_update';transport.save();return
    elif (run/'execution_pending.json').exists():
        receipt=read(run/'execution_pending.json');attempt=receipt['attempt'];folder=run/'action_attempts'/attempt
        if (folder/'commit.json').exists():
            (run/'execution_pending.json').unlink()
        elif (folder/'receipt.json').exists() and read(folder/'receipt.json').get('exit_code')==0:
            job=repair.perform('update',resume_update_request(root,transport,folder),attempt)
            write_json(folder/'commit.json',job['result']);(run/'execution_pending.json').unlink()
            write_json(out/'result.json',{'status':'updated','calls':calls,'attempt':attempt,'gui_actions':0})
            transport.account['status']='paused_after_update';transport.save();return
        else:raise step_repair.Paused('execution_unconfirmed','已有动作投递记录，但结算证据尚不齐全；禁止重复执行')
    navigation=visual_backtrack.resume_pending(transport,out/'current.png')
    if navigation:
        write_json(out/'result.json',{**navigation,'calls':calls});return
    loop=exploration_loop.observe(run,str(out))
    if loop:exploration_loop.correct(repair,loop)
    def route_recovery():
        if discovery_step.load(run)[2].get('next_action_mode') not in ('recover','recover_scope','review_result'):
            return False
        result=recover_loop.run(root,transport,out,call,repair=repair)
        write_json(out/'result.json',{**result,'calls':calls})
        transport.account['status']=result['status'];transport.save()
        return True
    if route_recovery():return
    if discovery_step.load(run)[2].get('next_action_mode')=='discover':
        discovery_step.run_stage(root,run,call,repair=repair)
        if route_recovery():return
    step_repair.helper('shared_control_review').run_pending(repair)
    q=current()
    if q['stage']=='task_proposal':
        repair.perform('task_proposal',q)
        if discovery_step.load(run)[2].get('next_action_mode')=='discover':
            discovery_step.run_stage(root,run,call,repair=repair)
            if route_recovery():return
        q=current()
        if q['stage']=='task_proposal':
            write_json(out/'result.json',{'status':'task_proposal','calls':calls,'gui_actions':0})
            transport.account['status']='paused_after_rediscovery';transport.save();return
    # Missing historical localization is advisory; Luna can choose a preparation action from the frame.
    if q['stage']=='function_registration':
        repair.perform('function_registration',q);q=current()
        if q['stage']=='function_registration':
            write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0})
            transport.account['status']='ready_next_round';transport.save();return
    if q.get('stage')=='task_result_review':
        reviewed=repair.perform('task_result_review',q)
        write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0,'task_result_review':reviewed['result']})
        transport.account['status']='ready_next_round';transport.save();return
    write_json(out/'action_request.json',q)
    if not q['action_ready']:
        write_json(out/'result.json',{'status':q['stage'],'calls':calls,'gui_actions':0})
        transport.account['status']='paused_'+q['stage'];transport.save();return
    if transport.account['max_http']-transport.account['http_started']<2:
        write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0})
        transport.account['status']='ready_next_round';transport.save();return
    navigation=visual_backtrack.try_step(transport,q,out/'current.png') if resumed is None else None
    if navigation:
        write_json(out/'result.json',{**navigation,'calls':calls})
        transport.account['status']=navigation['status'];transport.save();return
    q['role']='action_selection'
    if resumed and resumed['stage']=='action':accepted=resumed
    elif (q.get('source',{}).get('task_type')=='scroll'
            and q.get('response_schema',{}).get('properties',{}).get('action',{}).get('enum')==['scroll','none']
            and not q.get('region_scroll_bounds')):
        accepted=repair.repair_unlocated(q,'当前区块滚动缺少本帧已登记边界；需要正常补观察确认前景范围，再继续原滚动任务。当前尚未请求或执行动作，不必先提出必然无法绑定的滚动坐标。')
    else:accepted=repair.perform('action',q)
    result=accepted['result'];q=result['request'];ref=result['call'];proposal=result['proposal'];binding=result['binding']
    write_json(out/'binding.json',binding)
    if traversal_scope.skip_prohibited(run,q,proposal,ref):
        write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0,
                   'skipped_task':q['source'].get('task_name'),'reason':proposal['reason']})
        transport.account['status']='ready_next_round';transport.save();return
    # Repairs can consume the reserve; never deliver without result-call capacity.
    if transport.account['http_started']>=transport.account['max_http']:
        raise step_repair.Paused('ready_next_round','动作尚未执行，下一轮重新核对目标后继续')
    if binding['status']=='no_action' and proposal.get('request_task_review'):
        from task_result_review import request as review_request
        review=review_request(root,run,q['source'],q.get('screenshots') or [str(out/'current.png')])
        review['user_prompt']+='\n\n本次申请核对的理由（动作步判断，须结合证据核实）：'+proposal['reason']
        reviewed=repair.perform('task_result_review',review)
        write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0,'task_result_review':reviewed['result']})
        transport.account['status']='ready_next_round';transport.save();return
    if binding['status']=='no_action':
        def observe_navigation(records,state,*args):
            state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,
                         pending_frame=(q.get('screenshots') or q.get('image_refs') or [str(out/'current.png')])[0],correction_context='本次动作未执行，需要补充发现：'+proposal['reason'])
        discovery_step.publish(run,'navigation-observe-'+ref,observe_navigation)
        write_json(out/'result.json',{'status':'ready_next_round','calls':calls,'gui_actions':0});return
    if binding['status']!='matched':
        write_json(out/'result.json',{'status':binding['status'],'calls':calls,'gui_actions':0})
        transport.account['status']='paused_'+binding['status'];transport.save();return
    snapshot,records,state=discovery_step.load(run)
    attempt='a'+str(max([int(p.name[1:]) for p in (run/'action_attempts').iterdir() if p.name[1:].isdigit()]+[0])+1).zfill(4)
    folder=run/'action_attempts'/attempt;folder.mkdir()
    shutil.copy2(run/q['screenshots'][0],folder/'before.png')
    write_json(folder/'proposal.json',proposal);write_json(folder/'binding.json',binding)
    transport.screenshot(folder/'pre_dispatch.png')
    if proposal['action'] in ('tap','click','double_click','long_press','right_click','hover','drag','scroll','input_text'):
        fresh={**q,'image_refs':[str(folder/'pre_dispatch.png')],'screenshots':[str(folder/'pre_dispatch.png')]}
        from visual_backtrack import same_surface
        dispatch_window=foreground_window(transport)
        changed_window=bool(selection_window and dispatch_window and selection_window!=dispatch_window)
        confirmed=step_repair.confirmed_dispatch_review(run,accepted,calls,dispatch_window,out/'current.png')
        write_json(folder/'pre_dispatch_check.json',{'window':dispatch_window,'changed_window':changed_window,'confirmed_call':ref if confirmed else None})
        if changed_window or (not confirmed and not same_surface(folder/'before.png',folder/'pre_dispatch.png')):
            repair.reject_action(fresh,proposal,ref,'投递前窗口或画面发生变化；动作未执行，请比较两图核对目标，而非仅因动态内容变化反复刷新。',
                pre_dispatch_review={'before':str(folder/'before.png'),'current':str(folder/'pre_dispatch.png'),'window':dispatch_window})
        write_json(folder/'pre_dispatch_binding.json',binding)
    elif proposal['action'] in ('back','key_press','hotkey') and system_action_changed(proposal['action'],folder/'before.png',folder/'pre_dispatch.png',selection_window,foreground_window(transport)):
        repair.reject_action({**q,'screenshots':[str(folder/'pre_dispatch.png')],'image_refs':[str(folder/'pre_dispatch.png')]},proposal,ref,'投递前前景画面变化；键盘动作尚未执行，请重新核对')
    try:command_list=commands(proposal,getattr(transport,"platform","android"))  # Validate platform support before charging or tapping.
    except ValueError as error:
        write_json(out/'result.json',{'status':'unsupported_action','reason':str(error),'calls':calls,'gui_actions':0})
        transport.account['status']='paused_unsupported_action';transport.save();return
    def deliver(p):
        if transport.account['gui_started']:raise ValueError('single action already dispatched')
        write_json(run/'execution_pending.json',{'attempt':attempt})
        write_json(folder/'dispatch.json',{'source_call':ref,'source_region':binding['region_ref'],'source_control':binding['control_ref'],
                    'working_region':binding['working_region'],'action':p,'status':'dispatching'})
        input_context=None
        if p['action']=='input_text':
            from input_target import context
            from register_update import attach_execution
            attach_execution(records,run)
            input_context=context(snapshot,records,binding,q)
        result=execute_action(transport,p,folder/'execution',input_context=input_context)
        write_json(folder/'receipt.json',result)
        manifest=read(run/'run_manifest.json');manifest['actual_gui_actions']=manifest.get('actual_gui_actions',0)+1;write_json(run/'run_manifest.json',manifest)
        return result
    flow=StepwiseFlow(lambda role,q:call(q)[1],deliver,lambda role,value:write_json(out/(role+'.json'),value))
    flow.proposal=proposal;flow.phase='execute'
    receipt=flow.execute(lambda p:True)  # Includes the shared 2-second settling wait.
    if receipt['exit_code']!=0:raise ValueError('delivery not confirmed; do not retry')
    transport.screenshot(folder/'after.png')
    after_window=window_evidence(foreground_window(transport),transport.package)
    write_json(folder/'after_window.json',after_window)
    u=build_attempt_update(root,transport,folder)
    pointer=repair.perform('update',u,attempt)['result']
    write_json(folder/'commit.json',pointer)
    (run/'execution_pending.json').unlink(missing_ok=True)
    nextq=assemble_current_context(root,run);write_json(out/'next_request.json',nextq)
    write_json(out/'result.json',{'status':'updated','calls':calls,'attempt':attempt,'gui_actions':1,'pointer':pointer,'next_stage':nextq['stage']})
    transport.account['status']='paused_after_update';transport.save()


@progress.tracked
def run_step(root,run,out):
    try:return _run_step(root,run,out)
    except step_repair.Paused as error:
        out=Path(out);budget=read(out/'budget.json');budget['status']=error.status
        write_json(out/'budget.json',budget)
        write_json(out/'result.json',{'status':error.status,'reason':error.reason,'gui_actions':budget['gui_started']})
        progress.detail(error.reason)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    run_step(Path(__file__).resolve().parent,a.run,a.output)
