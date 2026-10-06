"""Pre-dispatch checks, single GUI delivery, receipt and before/after evidence."""
import shutil
from register_update import read, write_json
from stepwise_flow import StepwiseFlow
from action_commands import commands, execute as execute_action
import discovery_step
import step_repair
import visual_backtrack


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



class ActionExecutor:
    def __init__(self, transport, output, repair):
        self.transport, self.output, self.repair = transport, output, repair

    def execute(self, accepted, selection_window, calls):
        transport, out, repair = self.transport, self.output, self.repair
        run = transport.run
        if (run/'execution_pending.json').exists():
            raise step_repair.Paused('execution_unconfirmed','已有已投递动作待登记，禁止再次执行')
        if transport.account['http_started'] >= transport.account['max_http']:
            raise step_repair.Paused('ready_next_round','动作尚未执行；结果调用额度不足，下一轮重新核对目标')
        result = accepted['result']
        q, ref, proposal, binding = (result[key] for key in ('request','call','proposal','binding'))
        if binding['status'] != 'matched':
            raise ValueError('executor requires a validated matched proposal')
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
                repair.reject_action(fresh,proposal,ref,'投递前窗口或画面发生变化；动作未执行，请按唯一最新投递前图重新确认目标与坐标，而非仅因动态内容变化反复刷新。',
                    pre_dispatch_review={'before':str(folder/'before.png'),'current':str(folder/'pre_dispatch.png'),'window':dispatch_window})
            write_json(folder/'pre_dispatch_binding.json',binding)
        elif proposal['action'] in ('back','key_press','hotkey') and system_action_changed(proposal['action'],folder/'before.png',folder/'pre_dispatch.png',selection_window,foreground_window(transport)):
            repair.reject_action({**q,'screenshots':[str(folder/'pre_dispatch.png')],'image_refs':[str(folder/'pre_dispatch.png')]},proposal,ref,'投递前前景画面变化；键盘动作尚未执行，请重新核对')
        try:command_list=commands(proposal,getattr(transport,"platform","android"))  # Validate platform support before charging or tapping.
        except ValueError as error:
            write_json(out/'result.json',{'status':'unsupported_action','reason':str(error),'calls':calls,'gui_actions':0})
            transport.account['status']='paused_unsupported_action';transport.save();return
        if transport.account['gui_started']+len(command_list)>transport.account['max_gui_commands']:
            from model_transport import BudgetExhausted
            raise BudgetExhausted('GUI额度不足以投递完整动作；未执行，保留原任务')
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
        flow=StepwiseFlow(None,deliver,lambda role,value:write_json(out/(role+'.json'),value))
        flow.proposal=proposal;flow.phase='execute'
        receipt=flow.execute(lambda p:True)  # Includes the shared 2-second settling wait.
        if receipt['exit_code']!=0:raise ValueError('delivery not confirmed; do not retry')
        transport.screenshot(folder/'after.png')
        after_window=window_evidence(foreground_window(transport),transport.package)
        write_json(folder/'after_window.json',after_window)

        return folder
