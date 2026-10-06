"""Shared Android action contract for exploration and recovery.

Names follow the original traversal contract; ADB performs platform translation.
Old tap evidence is readable, but new requests advertise click.
"""
import json
from pathlib import Path
import shlex
import time

ANDROID_ACTIONS=('click','double_click','long_press','input_text','scroll','back','wait','none','key_press')

ACTIONS=ANDROID_ACTIONS+('hotkey','hover','right_click','drag')


def schema():
    return json.loads((Path(__file__).parent/'遍历prompt/输出格式/选择探索入口.schema').read_text())


def platform_request(request,platform):
    from copy import deepcopy
    q=deepcopy(request);q['platform']=platform
    def restrict(node):
        if isinstance(node,dict):
            if 'enum' in node and 'click' in node['enum'] and platform=='android':node['enum']=[v for v in node['enum'] if v in ANDROID_ACTIONS]
            for child in node.values():restrict(child)
        elif isinstance(node,list):
            for child in node:restrict(child)
    restrict(q.get('response_schema',{}))
    return q


def normalize(proposal):
    p={**proposal,'action':{'tap':'click'}.get(proposal['action'],proposal['action'])}
    if p['action']=='back':p['target']='系统返回'
    if p['action'] not in ('input_text','key_press','hotkey'):p['text']=None
    if p['action'] not in ('scroll','drag'):p.update(end_x=None,end_y=None)
    if p['action'] in ('back','wait','none','key_press','hotkey'):p.update(x=None,y=None)
    return p


def validate(proposal,platform="android"):
    import jsonschema
    if proposal.get('request_task_review'):
        raise ValueError('普通动作不再申请任务完成复核；按绑定动作执行或补发现')
    jsonschema.validate({'skip_task':False,**{k:v for k,v in proposal.items() if k!='request_task_review'}},schema())
    if proposal.get("skip_task") and (proposal["action"]!="none" or not proposal.get("reason","").strip()):
        raise ValueError("跳过任务使用none，并说明违反哪项当前限制")
    commands(normalize(proposal),platform)


def commands(proposal,platform="android"):
    if platform=="desktop":
        from desktop_transport import commands as desktop_commands
        return desktop_commands(proposal)
    p=normalize(proposal);kind=p['action']
    if kind not in ANDROID_ACTIONS:raise ValueError('unsupported Android action: '+kind)
    if kind=='key_press':
        keys={'ENTER':'66','TAB':'61','ESC':'111','BACKSPACE':'67'}
        if p.get('text') not in keys:raise ValueError('key_press text must be ENTER, TAB, ESC or BACKSPACE')
        return [['shell','input','keyevent',keys[p['text']]]]
    if kind=='back':return [['shell','input','keyevent','4']]
    if kind in ('wait','none'):return []
    x,y=p.get('x'),p.get('y')
    if type(x) is not int or type(y) is not int or min(x,y)<0:raise ValueError('action needs valid coordinates')
    tap=['shell','input','tap',str(x),str(y)]
    if kind=='click':return [tap]
    if kind=='double_click':return [tap,tap]
    if kind=='long_press':return [['shell','input','swipe',str(x),str(y),str(x),str(y),'800']]
    if kind=='scroll':
        ex,ey=p.get('end_x'),p.get('end_y')
        if type(ex) is not int or type(ey) is not int or min(ex,ey)<0 or (x,y)==(ex,ey):raise ValueError('invalid scroll endpoints')
        return [['shell','input','swipe',str(x),str(y),str(ex),str(ey),'500']]
    text=p.get('text')
    if not isinstance(text,str) or any(ord(c)>127 or ord(c)<32 for c in text):
        raise ValueError('Android adapter supports printable ASCII input only; do not deliver partial text')
    replacement=['shell','input','text',shlex.quote(text.replace(' ','%s'))] if text else ['shell','input','keyevent','67']
    return [tap,['shell','input','keycombination','113','29'],replacement]


def execute(transport,proposal,folder,*,input_context=None):
    """Shared receipts and command accounting; delivery is never semantic success."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    platform=getattr(transport,"platform","android")
    argv=commands(proposal,platform)
    from model_transport import BudgetExhausted
    if transport.account['gui_started']+len(argv)>transport.account['max_gui_commands']:raise BudgetExhausted('GUI command budget exhausted')
    def save(name,data):(folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    save('dispatch.json',{'action':proposal,'commands':argv,'status':'dispatching'})
    if input_context is not None:save('input_context.json',input_context)
    receipts=[];steps=[];target=None
    def send(command,step):
        if transport.account['gui_started']>=transport.account['max_gui_commands']:raise BudgetExhausted('GUI command budget exhausted')
        transport.account['gui_started']+=1;transport.save()
        save('pending_command.json',{'command':command,'step':step})
        try:
            result=transport.send_command(command) if platform=="desktop" else transport.adb(command)
            receipt={'exit_code':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode()}
        except BaseException:
            save('receipt.json',{'exit_code':None,'semantic_result':'unverified','executed_steps':steps});raise
        receipts.append(receipt);save('command_receipts.json',receipts)
        if receipt['exit_code']==0:steps.append(step)
        save('executed_steps.json',steps)
        return receipt
    def finish(delivered=None,description=''):
        receipt={**(receipts[-1] if receipts else {'exit_code':0}),'semantic_result':'unverified','executed_steps':steps}
        if delivered is not None:
            receipt['text_delivered']=delivered
            receipt['input_mode']='replace'
            if not delivered and receipt['exit_code']==0:receipt.update(semantic_result='focus_changed_surface',description=description)
        if target:receipt['input_target']=target
        save('receipt.json',receipt);return receipt
    if proposal['action']!='input_text':
        if proposal['action']=='wait':
            time.sleep(2)
            steps.append({'action':'wait','seconds':2})
            save('executed_steps.json',steps)
        for command in argv:
            if send(command,dict(proposal))['exit_code']!=0:break
        return finish()
    transport.screenshot(folder/'before_focus.png')
    if send(argv[0],{'action':'click','x':proposal['x'],'y':proposal['y']})['exit_code']!=0:return finish(False)
    time.sleep(2);transport.screenshot(folder/'after_focus.png')
    if input_context is None:
        # Recovery has no graph target. Preserve its conservative visual check.
        from visual_backtrack import same_surface
        decision={'status':'same_target' if same_surface(folder/'before_focus.png',folder/'after_focus.png') else 'unresolved','reason':'无区块控件证据，采用整图保守核验'}
    else:
        from input_target import resolve
        decision=resolve(input_context,folder/'before_focus.png',folder/'after_focus.png')
    save('focus_check.json',decision)
    if decision['status']=='known_target':
        if transport.account['gui_started']+3>transport.account['max_gui_commands']:
            return finish(False,'已匹配输入目标，但剩余GUI额度不足以重新聚焦并输入')
        target=decision['target'];x,y=decision['x'],decision['y']
        if send(commands({**proposal,'action':'click','x':x,'y':y},platform)[0],{'action':'click','x':x,'y':y,**target,'route_attempt':decision['route_attempt']})['exit_code']!=0:return finish(False)
        time.sleep(2);transport.screenshot(folder/'after_retarget.png')
        selected=next(t for t in input_context['targets'] if all(t[k]==target[k] for k in target))
        decision=resolve({'source':selected,'targets':[]},folder/'after_focus.png',folder/'after_retarget.png')
        save('retarget_check.json',decision)
    if decision['status']!='same_target':return finish(False,'实际点击已保存；输入对象未可靠确认，尚未发送文字，交回发现与更新流程')
    target=decision.get('target',target)
    if send(argv[1],{'action':'select_all','method':'CTRL+A'})['exit_code']!=0:return finish(False,'全选命令失败，未发送文字')
    result=send(argv[2],{'action':'input_text','text':proposal['text'],**(target or {})})
    return finish(result['exit_code']==0)
