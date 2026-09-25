"""Bounded recovery without business Region identification between actions."""
import hashlib
import json
from pathlib import Path
import time
from PIL import Image,ImageChops
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def stalled(episode,frame):
    """Repeated observed surfaces, not total tutorial steps, bound recovery."""
    same_surface=helper('exploration_loop').same_observation
    frames=[a['frame'] for a in episode.get('actions',[]) if a.get('frame') and a.get('delivery')=='executed_receipt_zero'][-8:]
    repeats=sum(Path(p).is_file() and same_surface(p,frame) for p in frames)
    return repeats>=3


def recovery_result(episode,gui_actions,path):
    status=episode['status']
    if episode.get('exception')=='system_error' and status in ('stopped','review_execution'):
        status='environment_blocked'
    return {'status':status,'gui_actions':gui_actions,'episode':str(path),'reason':episode.get('reason')}


def run(root,transport,out,call,repair=None):
    reg=helper('register_update');discovery=helper('discovery_step');policy=helper('recovery');actions=helper('action_commands')
    _,records,state=discovery.load(transport.run)
    if state['next_action_mode'] not in ('recover','recover_scope','review_result'):raise ValueError('not in recovery')
    key=hashlib.sha256(str(state.get('source_call',state.get('update_digest'))).encode()).hexdigest()[:12]
    folder=transport.run/'recovery_episodes'/key;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'episode.json'
    episode=reg.read(path) if path.exists() else {'actions':[],'status':'running','handoff':state.get('recovery_handoff',''),'source_call':state.get('source_call'),'exception':state.get('exception')}
    episode['interrupted_tasks']=policy.interrupted_tasks(records,state)
    def save():reg.write_json(path,episode)
    if episode['status']=='stopped' and episode.get('exception')!='system_error' and str(Path(out).parent.resolve()) not in episode.get('resume_sessions',[]):
        episode.setdefault('stop_history',[]).append({'reason':episode.get('reason'),'observations':episode.get('observations',0)})
        episode.setdefault('resume_sessions',[]).append(str(Path(out).parent.resolve()))
        episode.update(status='running',framework_feedback='上次恢复已停止；本次用户续跑先看新截图，历史动作与重启限制仍保留，不重放旧建议。')
        save()
    if episode['status'] in ('stopped','review_execution'):return recovery_result(episode,0,path)
    if episode['actions'] and episode['actions'][-1]['delivery'] in ('dispatching','unconfirmed'):
        episode['status']='review_execution';save()
        return recovery_result(episode,0,path)
    save();work=records.get(state.get('working_region'),{}).get('name','待重新定位')
    trigger=state.get('handoff_summary',state.get('reason',''))
    initial=transport.account['gui_started']
    while True:
        if transport.account['http_started']>=transport.account['max_http']:
            save()
            return {'status':'ready_next_round','gui_actions':transport.account['gui_started']-initial,'episode':str(path)}
        index=len(episode['actions']);observations=folder/f'observation-{episode.get("observations",0)+1:04d}';observations.mkdir()
        episode['observations']=episode.get('observations',0)+1;save()
        transport.screenshot(observations/'current.png')
        repeated_surface=stalled(episode,observations/'current.png');save()
        q=policy.build_request(root,episode,transport.package,work,trigger,str((observations/'current.png').resolve()))
        ref,raw_reply=call(q);reply=policy.resolve(raw_reply,getattr(transport,"platform","android"))
        reg.write_json(observations/'framework_decision.json',{'source_call':ref,'decision':reply,'overrode_model':reply!=raw_reply})
        if episode['actions']:
            episode['actions'][-1]['observed_result']={'exception':reply['exception'],'description':reply['reason'],'source_call':ref}
        episode['handoff']=reply['handoff'];episode['exception']=reply['exception'];save()
        if reply['exception']=='unexpected_exit' and state.get('active_task'):
            active=state['active_task']
            def suspend(records,current,snapshot,temp):
                task=records[active['region']]['tasks'][active['name']]
                if task['status']=='pending':
                    task.update(status='blocked',result_evidence=reply['reason'],
                                blocker={'condition':'review_required','exception':'unexpected_exit','source_call':ref,'reason':reply['reason']},
                                deferral={'reason':reply['reason'],'retry_when':'explicit_crash_cause_resolved','source_call':ref})
                current.pop('active_task',None)
            discovery.publish(transport.run,'exit-suspend-'+ref,suspend)
            state.pop('active_task',None)
        if reply['decision']=='resume_exploration':
            discovery.await_discovery(transport.run,str((observations/'current.png').resolve()),'recovery-'+ref,reply['handoff'])
            episode['status']='awaiting_discovery';save()
            discovery.run_stage(root,transport.run,call,repair=repair)
            episode['status']='discovery_complete';save()
            return {'status':'paused_after_recovery_discovery','gui_actions':transport.account['gui_started']-initial,'episode':str(path),'reason':episode.get('reason')}
        if reply['decision']=='stop' or (repeated_surface and helper('recovery_stall').repeated_attempt(episode,reply)):
            episode.update(status='stopped',reason=reply['reason'] if reply['decision']=='stop' else 'recovery repeatedly returned to the same observed surface without resolving the obstruction');save();break
        restarted=any(a.get('framework_tool')=='restart_app' for a in episode['actions'])
        returns=sum(a.get('action',{}).get('action')=='back' for a in episode['actions'])
        tool=reply['framework_tool'];proposal=reply['action'];issuer='agent'
        if reply['exception']=='external_app' and returns>=2 and not restarted:
            tool='restart_app';proposal=None;issuer='framework'
        if tool and restarted:
            episode['rejected_restarts']=episode.get('rejected_restarts',0)+1
            episode['framework_feedback']='重启工具本次已使用，重复请求未执行。请结合启动回执和截图判断：可等待启动、关闭系统概览或切回已有窗口；没有允许的恢复办法时stop并说明具体原因。'
            if episode['rejected_restarts']>=2:
                episode.update(status='stopped',reason='已反馈重启限制，但模型仍重复请求；未再次重启应用。需检查启动回执及当前窗口。');save();break
            save();continue
        if proposal and episode['actions']:
            last=episode['actions'][-1]
            same={k:v for k,v in proposal.items() if k!='reason'}=={k:v for k,v in last.get('action',{}).items() if k!='reason'}
            old_frame=last.get('frame')
            if same and old_frame and helper('visual_backtrack').same_surface(old_frame,observations/'current.png') and reply['exception']==last.get('exception') and proposal['action'] not in ('back','wait'):
                episode.update(status='stopped',reason='same action and unresolved exception; do not repeat blindly');save();break
        target=observations/'pre_dispatch.png';transport.screenshot(target)
        changed=False
        with Image.open(observations/'current.png') as before,Image.open(target) as after:
            if before.size!=after.size:changed=True
            elif proposal and proposal['action'] not in ('back','wait','none'):
                actions.commands(proposal,getattr(transport,"platform","android"))
                if proposal['action'] in ('key_press','hotkey'):
                    box=(0,0,before.width,before.height)
                else:
                    x,y=proposal['x'],proposal['y']
                    if not (0<=x<before.width and 0<=y<before.height):raise ValueError('target outside frame')
                    if (proposal['action']=='drag' or (proposal['action']=='scroll' and getattr(transport,'platform','android')!='desktop')) and not(0<=proposal['end_x']<before.width and 0<=proposal['end_y']<before.height):raise ValueError('endpoint outside frame')
                    box=(max(0,x-48),max(0,y-48),min(before.width,x+49),min(before.height,y+49))
                changed=bool(ImageChops.difference(before.convert('RGB').crop(box),after.convert('RGB').crop(box)).getbbox())
        if changed:
            episode.setdefault('withheld_actions',[]).append({'source_call':ref,'action':proposal,'reason':'target changed before delivery','frame':str(target.resolve())})
            episode['framework_feedback']='刚才建议未投递：投递前目标画面发生变化。请根据新截图重新选择；这不是已执行动作。'
            consecutive=episode.get('withheld_streak',0)+1;episode['withheld_streak']=consecutive
            if consecutive>=3:
                episode.update(status='stopped',reason='目标连续变化，三次建议均未投递；需检查环境稳定性');save();break
            save();continue
        episode['withheld_streak']=0
        needed=2 if tool else len(actions.commands(proposal,getattr(transport,'platform','android')))
        if transport.account['gui_started']+needed>transport.account['max_gui_commands']:
            save()
            return {'status':'ready_next_round','gui_actions':transport.account['gui_started']-initial,'episode':str(path),'reason':'round action allowance exhausted; observe again next round'}
        row={'source_call':ref,'exception':reply['exception'],'action':proposal or {},'framework_tool':tool,'issuer':issuer,'delivery':'dispatching','frame':str((observations/'current.png').resolve())}
        episode['actions'].append(row);save()
        try:
            if tool:
                if getattr(transport,'platform','android')=='desktop':argv=transport.restart_commands()
                else:
                    result=transport.adb(['shell','cmd','package','resolve-activity','--brief',transport.package]);result.check_returncode()
                    argv=policy.restart_commands(transport.package,result.stdout.decode().strip().splitlines()[-1])
                if transport.account['gui_started']+len(argv)>transport.account['max_gui_commands']:raise ValueError('GUI budget exhausted')
                reg.write_json(observations/'restart_dispatch.json',{'commands':argv,'issuer':issuer})
                receipts=[]
                for command in argv:
                    transport.account['gui_started']+=1;transport.save();result=transport.send_command(command) if getattr(transport,"platform","android")=="desktop" else transport.adb(command)
                    receipt={'exit_code':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode()}
                    if 'Error:' in receipt['stdout']+receipt['stderr']:receipt['exit_code']=1
                    receipts.append(receipt);reg.write_json(observations/'restart_receipts.json',receipts)
                    if receipt['exit_code']!=0:break
            else:receipt=actions.execute(transport,proposal,observations/'execution')
        except BaseException as error:
            row['delivery']='unconfirmed';episode['status']='review_execution';episode['reason']=str(error);save()
            if episode.get('exception')=='system_error' and isinstance(error,Exception):
                return recovery_result(episode,transport.account['gui_started']-initial,path)
            raise
        if tool:row['execution_feedback']=receipts
        row['delivery']='executed_receipt_zero' if receipt['exit_code']==0 else 'delivery_exception';save()
        manifest=reg.read(transport.run/'run_manifest.json');manifest['actual_recovery_actions']=manifest.get('actual_recovery_actions',0)+1;reg.write_json(transport.run/'run_manifest.json',manifest)
        if receipt['exit_code']!=0:episode['status']='review_execution';save();break
        time.sleep(2)
    return recovery_result(episode,transport.account['gui_started']-initial,path)
