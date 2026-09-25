"""Application/run selection for the experimental Android traversal path."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid


def configured_model():
    import sys
    root=str(repository())
    if root not in sys.path:sys.path.insert(0,root)
    from gui_rewalk.src.core.explore.api_config import load_explore_api_config, local_explore_api_config_path
    return load_explore_api_config(local_explore_api_config_path()).model


def repository():
    return next(p for p in Path(__file__).resolve().parents if (p/'gui_rewalk').is_dir() and (p/'tools/android_web_mirror.py').is_file())


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def create_run(parent,package,name,device,frame):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]+',package):raise ValueError('Invalid application package')
    key=package+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    run=Path(parent)/key;run.mkdir(parents=True,exist_ok=False)
    for name_ in ['calls','action_attempts','screenshots','knowledge_snapshots/initial/regions']:(run/name_).mkdir(parents=True)
    shutil.copy2(frame,run/'screenshots/initial.png')
    shutil.copy2(Path(__file__).with_name('call_model_once.py'),run/'call_once.py')
    write(run/'run_manifest.json',{'record_type':'program_run_metadata','app':package,'app_name':name,'device':device,
        'created_utc':datetime.now(timezone.utc).isoformat(),'actual_model_calls':0,'actual_gui_actions':0,
        'model_planned':configured_model(),'framework_source':str(Path(__file__).resolve().parent),'run_directory':str(run.resolve()),'app_data_reset':False})
    write(run/'knowledge_snapshots/initial/runtime_state.json',{'working_region':None,'interactive_regions':[],
        'next_action_mode':'discover','phase':'awaiting_discovery','observation':None,'pending_frame':'screenshots/initial.png'})
    write(run/'knowledge_snapshots/initial/source.json',{'record_format':'region_image_knowledge','stage':'empty_initialization'})
    write(run/'knowledge_current.json',{'snapshot':'knowledge_snapshots/initial'})
    return run


class Device:
    def __init__(self,serial):
        self.serial=serial
        self.adb=str(Path.home()/'android-sdk/platform-tools/adb')
    def command(self,args):
        result=subprocess.run([self.adb,'-s',self.serial,*args],capture_output=True,timeout=30)
        result.check_returncode();return result.stdout
    def applications(self):
        output=self.command(['shell','cmd','package','query-activities','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER']).decode()
        names={'com.google.android.deskclock':'Clock','com.android.settings':'Settings','com.android.chrome':'Chrome'}
        apps={}
        for line in output.splitlines():
            match=re.fullmatch(r'\s*([A-Za-z][\w.]+)/([\w.$]+)\s*',line)
            if match:
                package=match[1];apps.setdefault(package,{'package':package,'name':names.get(package,package.rsplit('.',1)[-1]),'component':line.strip()})
        return sorted(apps.values(),key=lambda a:a['name'].casefold())
    def activate(self,component,folder):
        command=['shell','am','start','-n',component]
        write(folder/'activation.json',{'command':command,'device':self.serial,'max_gui_commands':1,'gui_started':1})
        data=self.command(command).decode();write(folder/'activation_receipt.json',{'stdout':data})
        if 'Error:' in data:raise ValueError('Application activation failed')
        time.sleep(2)
        frame=folder/'current.png';frame.write_bytes(self.command(['exec-out','screencap','-p']));return frame


class ApplicationHub:
    def __init__(self,parent,device,runner_factory,initial=None):
        self.parent=Path(parent);self.parent.mkdir(parents=True,exist_ok=True)
        self.device=device;self.runner_factory=runner_factory;self.run=Path(initial) if initial else None
        self.runner=runner_factory(self.run) if self.run else None
        self.apps=device.applications();self.lock=threading.Lock()
    def catalog(self):
        values=[]
        for app in self.apps:
            runs=[]
            for path in self.parent.glob('*/run_manifest.json'):
                value=json.loads(path.read_text())
                if value.get('app')==app['package'] and value.get('device')==self.device.serial and (path.parent/'knowledge_current.json').is_file():
                    runs.append({'id':path.parent.name,'created':value.get('created_utc',''),'name':path.parent.name})
            values.append({**app,'runs':sorted(runs,key=lambda r:r['created'],reverse=True)})
        return {'device':self.device.serial,'apps':values,'selected_run':self.run.name if self.run else None}
    def select(self,package,mode,run_id=None):
        import discovery_step,progress
        with self.lock:
            if self.runner and (self.runner.status()['running'] or progress.snapshot(self.run)['status']=='running'):
                raise RuntimeError('Pause the current traversal before switching applications')
            app=next((a for a in self.catalog()['apps'] if a['package']==package),None)
            if app is None:raise ValueError('Application is not installed on this device')
            if mode not in ('new','resume'):raise ValueError('Invalid selection mode')
            if mode=='resume' and run_id not in [r['id'] for r in app['runs']]:raise ValueError('Unknown saved run')
            evidence=self.parent/'launcher_events'/uuid.uuid4().hex;evidence.mkdir(parents=True)
            write(evidence/'selection.json',{'app':package,'mode':mode,'run_id':run_id,'app_data_reset':False})
            retained=self.parent/run_id if mode=='resume' else None
            pending=retained is not None and any((retained/name).exists() for name in ('pending_step.json','execution_pending.json','visual_navigation_pending.json'))
            if pending:
                run=retained  # Settle the old step before activation changes the foreground.
            else:
                frame=self.device.activate(app['component'],evidence)
                if mode=='new':run=create_run(self.parent,package,app['name'],self.device.serial,frame)
                else:
                    run=retained
                    discovery_step.await_discovery(run,str(frame.resolve()),'launcher-'+evidence.name)
            self.run=run;self.runner=self.runner_factory(run)
            write(self.parent/'launcher_current.json',{'run':run.name,'device':self.device.serial})
            return {'run':run.name,**self.runner.start('auto')}
