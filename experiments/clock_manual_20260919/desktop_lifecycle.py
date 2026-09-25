"""Start target applications outside the controller service's cleanup cgroup."""
import json
import os
import subprocess
import time
import uuid


def start(argv):
    unit='gui-rewalk-app-'+uuid.uuid4().hex
    command=['systemd-run','--user','--collect','--unit='+unit,'--property=Type=exec']
    for key in ('DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS'):
        if os.environ.get(key):command.append('--setenv='+key+'='+os.environ[key])
    launched=subprocess.run([*command,'--',*argv],capture_output=True,text=True)
    if launched.returncode:
        print(json.dumps({'unit':unit,'exit_code':launched.returncode,'startup_log':launched.stderr}))
        raise SystemExit(launched.returncode)
    time.sleep(2)
    result=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,MainPID,ExecMainStatus'],capture_output=True,text=True)
    state=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    ok=result.returncode==0 and state.get('ActiveState')=='active' and int(state.get('MainPID','0'))>0
    log=subprocess.run(['journalctl','--user','-u',unit,'-n','12','--no-pager'],capture_output=True,text=True)
    print(json.dumps({'unit':unit,'pid':int(state.get('MainPID','0')),'active_state':state.get('ActiveState'),
                     'exit_code':0 if ok else 1,'startup_log':log.stdout[-2000:]}))
    if not ok:raise SystemExit(1)
