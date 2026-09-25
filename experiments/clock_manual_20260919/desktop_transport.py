"""OSWorld HTTP adapter for the existing stepwise pipeline, without action retries."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time
import requests
from recover_external import RecoveryRun
from desktop_capture import display_capture,publish_frame


def receipt(body):
    return subprocess.CompletedProcess([],body.get('returncode',-1),str(body.get('output','')).encode(),str(body.get('error','')).encode())


def commands(p):
    from action_commands import normalize,commands as android_validate
    p=normalize(p)
    if p['action']=='scroll':
        from desktop_scroll import commands as wheel_commands
        return wheel_commands(p)
    extended=p['action'] in ('key_press','hotkey','hover','right_click','drag')
    if not extended:android_validate(p)
    k=p['action'];x,y=p.get('x'),p.get('y')
    if k in ('none','wait'):return []
    if k in ('key_press','hotkey'):
        text=p.get('text')
        if not isinstance(text,str):raise ValueError('keyboard action needs key names in text')
        keys=[key.strip().lower() for key in text.split('+')]
        allowed=set('abcdefghijklmnopqrstuvwxyz0123456789')|{'enter','tab','esc','backspace','delete','space','up','down','left','right','home','end','pageup','pagedown','insert','ctrl','alt','shift','win','super'}|{f'f{i}' for i in range(1,25)}
        if any(key not in allowed for key in keys) or (k=='key_press' and len(keys)!=1) or (k=='hotkey' and len(keys)<2):raise ValueError('unsupported key names')
        keys=['win' if key=='super' else key for key in keys]
        return [f'pyautogui.press({keys[0]!r})' if k=='key_press' else 'pyautogui.hotkey('+', '.join(repr(key) for key in keys)+')']
    if extended:
        if any(type(v) is not int or v<0 for v in (x,y)):raise ValueError('pointer action needs coordinates')
        if k=='hover':return [f'pyautogui.moveTo({x},{y})']
        if k=='right_click':return [f"pyautogui.click({x},{y},button='right')"]
        ex,ey=p.get('end_x'),p.get('end_y')
        if any(type(v) is not int or v<0 for v in (ex,ey)) or (x,y)==(ex,ey):raise ValueError('drag needs distinct endpoints')
        return [f'pyautogui.moveTo({x},{y}); pyautogui.dragTo({ex},{ey},duration=0.5)']
    if k=='back':return ["pyautogui.press('esc')"]
    if k=='click':return [f'pyautogui.click({x},{y})']
    if k=='double_click':return [f'pyautogui.doubleClick({x},{y},interval=0.1)']
    if k=='long_press':return [f'pyautogui.moveTo({x},{y}); pyautogui.mouseDown(); time.sleep(0.8); pyautogui.mouseUp()']
    if k=='input_text':return [f'pyautogui.click({x},{y})',"pyautogui.hotkey('ctrl','a')",f'pyautogui.write({p["text"]!r},interval=0.03)' if p['text'] else "pyautogui.press('backspace')"]
    raise ValueError('unsupported desktop action')


def prepare_request(root,request):
    q=deepcopy(request);q['platform']='desktop'
    for path in ('平台/桌面执行.prompt','平台/桌面悬停观察.prompt'):
        text=(Path(root)/'遍历prompt'/path).read_text()
        q['fixed_parts'].append({'path':path,'text':text});q['system_prompt']+='\n\n'+text
    try:
        d=json.loads(q['user_prompt']);d['平台']='OSWorld Linux桌面';q['user_prompt']=json.dumps(d,ensure_ascii=False,indent=2)
    except (ValueError,TypeError):q['user_prompt']='本轮平台：OSWorld Linux桌面。\n'+q['user_prompt']
    return q


class DesktopRun(RecoveryRun):
    platform='desktop'

    def configure(self,manifest):
        self.manifest=manifest
        self.endpoint=manifest['desktop']['controller'];self.launch_command=manifest['desktop']['launch_command']
        self.window_class=manifest['desktop']['window_class']

    def command(self,argv,timeout=90):
        r=requests.post(self.endpoint+'/execute',json={'command':argv,'shell':False},timeout=timeout);r.raise_for_status();return receipt(r.json())

    def send_command(self,code):
        return self.command(['python','-c','import pyautogui,time; '+code])

    def screenshot(self,path):
        from io import BytesIO
        from PIL import Image
        import progress
        path=Path(path);started=time.monotonic();attempt=0
        container=getattr(self,'manifest',{}).get('desktop',{}).get('container')
        def report(status,error_type=None):
            row={'status':status,'failures':attempt,'elapsed_seconds':round(time.monotonic()-started,1)}
            if error_type:row['error_type']=error_type
            path.with_name(path.name+'.capture.json').write_text(json.dumps(row,indent=2))
            with path.with_name(path.name+'.capture.jsonl').open('a') as log:log.write(json.dumps(row)+'\n')
            progress.detail(('等待虚拟机截图恢复' if status=='waiting' else '截图已恢复' if status=='recovered' else '截图等待已暂停')+
                            f' · 已重试 {attempt} 次 · 等待 {row["elapsed_seconds"]} 秒')
        while True:
            try:progress.check_capture_pause()
            except progress.CapturePaused:
                report('paused');raise
            error_type=None
            if container:
                try:
                    content=display_capture(container)
                    path.write_bytes(content)
                    path.with_name(path.name+'.source.json').write_text(json.dumps({'source':'qemu_display'}))
                    publish_frame(getattr(self,'run',None),path,'qemu_display')
                    if attempt:report('recovered')
                    return
                except (subprocess.SubprocessError,OSError,ValueError) as error:
                    error_type='display_'+type(error).__name__
            try:
                if error_type:raise requests.exceptions.ConnectionError(error_type)
                r=requests.get(self.endpoint+'/screenshot',timeout=15);r.raise_for_status()
            except requests.exceptions.SSLError:raise
            except (requests.exceptions.ChunkedEncodingError,requests.exceptions.ConnectionError,requests.exceptions.Timeout) as error:
                error_type=type(error).__name__
            except requests.exceptions.HTTPError as error:
                if error.response is None or error.response.status_code not in (500,502,503,504):raise
                error_type='HTTP'+str(error.response.status_code)
            if error_type is None:
                try:
                    with Image.open(BytesIO(r.content)) as image:
                        if image.format!='PNG':raise ValueError('OSWorld screenshot is not PNG')
                        image.verify()
                except (OSError,ValueError,SyntaxError) as error:
                    error_type=type(error).__name__
                    # Keep one raw example; repeated failures get small append-only records.
                    evidence=path.with_name(path.name+'.invalid.bin')
                    if not evidence.exists():evidence.write_bytes(r.content)
            if error_type is None:
                path.write_bytes(r.content)
                path.with_name(path.name+'.source.json').write_text(json.dumps({'source':'guest_http'}))
                publish_frame(getattr(self,'run',None),path,'guest_http')
                if attempt:report('recovered')
                return
            attempt+=1;report('waiting',error_type)
            # Back off to five seconds, while checking the existing pause request.
            for _ in range(min(attempt,5)*4):
                try:progress.check_capture_pause()
                except progress.CapturePaused:
                    report('paused');raise
                time.sleep(.25)

    def foreground_window(self):
        code="import subprocess,re; root=subprocess.check_output(['xprop','-root','_NET_ACTIVE_WINDOW'],text=True); window=re.search(r'0x[0-9a-fA-F]+',root).group(); print(subprocess.check_output(['xprop','-id',window,'WM_CLASS','_NET_WM_NAME'],text=True))"
        try:
            result=self.command(['python','-c',code],timeout=5)
        except requests.exceptions.SSLError:raise
        except (requests.exceptions.ConnectionError,requests.exceptions.Timeout,requests.exceptions.ChunkedEncodingError) as error:
            return {'目标应用':self.package,'与目标应用一致':None,'窗口记录':'',
                    '读取错误':type(error).__name__+'：前景辅助信息暂不可用，以当前截图核验','来源':'OSWorld X11 read failed'}
        raw=result.stdout.decode();return {'目标应用':self.package,'与目标应用一致':self.window_class.casefold() in raw.casefold() if result.returncode==0 else None,'窗口记录':raw,'读取错误':result.stderr.decode() if result.returncode else '', '来源':'OSWorld X11 active window WM_CLASS/title'}

    def restart_commands(self):
        # The user manager owns the application, not the HTTP controller service.
        launch=Path(__file__).with_name('desktop_lifecycle.py').read_text()
        return [f'import subprocess; subprocess.run(["pkill","-x",{self.launch_command[0][:15]!r}],check=False)',
                launch+f'\nstart({self.launch_command!r})']

    def call(self,request):
        return super().call(prepare_request(self.root,request))
