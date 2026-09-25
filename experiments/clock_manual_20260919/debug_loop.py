"""Round-robin supervision of the existing traversal, with isolated repair trials."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import threading
import re
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent
CONTINUE={'updated','paused_after_recovery_discovery','task_proposal','ready_next_round','repair_pending','task_deferred'}


def read(path,default=None):
    path=Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def helper(root,name):
    spec=importlib.util.spec_from_file_location('debug_'+name,Path(root)/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def graph_summary(run,source=ROOT):
    module_source=source if (Path(source)/'debug_progress.py').exists() else ROOT
    return helper(module_source,'debug_progress').graph_summary(run,source)


def classify(session,result,http_status,device_error=False):
    if result.get('status')=='environment_blocked':return {'kind':'environment_blocked','reason':result.get('reason','system recovery stopped')}
    if session.get('status') in ('paused_by_user','budget_limit','round_limit'):
        return {'kind':'paused','reason':session['status']}
    if http_status in (408,429,500,502,503,504):return {'kind':'service_wait','reason':f'HTTP {http_status}'}
    if http_status in (401,402,403):return {'kind':'service_blocked','reason':f'HTTP {http_status}'}
    if device_error:return {'kind':'device_wait','reason':'device/transport unavailable'}
    if result.get('status')=='scope_idle':return {'kind':'scope_idle','reason':'no actionable work; coverage gaps preserved'}
    if result.get('status') in CONTINUE:return {'kind':'continue','reason':result['status']}
    if result.get('status') in ('region_complete','task_blocked','return_blocked'):
        return {'kind':'schedule','reason':result['status']}
    return {'kind':'framework','reason':result.get('reason') or session.get('last_result') or session.get('status') or 'runner_interrupted'}


def fingerprint(issue):
    return hashlib.sha256(json.dumps({k:issue.get(k) for k in ('kind','stage')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]


def device_key(run):
    manifest=read(Path(run)/'run_manifest.json',{})
    return str(manifest.get('platform','unknown'))+':'+str(manifest.get('device') or Path(run).resolve())


def live_run(run):
    target=Path(run).resolve();device=device_key(target)
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args=[os.fsdecode(a) for a in p.read_bytes().split(b'\0') if a]
            for i,arg in enumerate(args[:-1]):
                if Path(arg).name!='run_progress_session.py':continue
                other=Path(args[i+1]);other=other if other.is_absolute() else (p.parent/'cwd').resolve()/other
                if other.resolve()==target or device_key(other)==device:return int(p.parent.name)
        except (OSError,ValueError):continue
    return None


@contextmanager
def device_lock(run):
    folder=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp'))/('gui-rewalk-device-locks-'+str(os.getuid()));folder.mkdir(parents=True,exist_ok=True)
    name=hashlib.sha256(device_key(run).encode()).hexdigest()
    with (folder/name).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def freeze(source,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    for p in Path(source).iterdir():
        if p.is_file() and p.suffix in ('.py','.md'):shutil.copy2(p,destination/p.name)
    shutil.copytree(Path(source)/'遍历prompt',destination/'遍历prompt')
    return destination


def source_hash(source):
    source=Path(source)
    files=[p for p in source.iterdir() if p.is_file() and p.suffix in ('.py','.md')]
    files += [p for p in (source/'遍历prompt').rglob('*') if p.is_file()]
    rows=[(str(p.relative_to(source)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()


class Supervisor:
    def __init__(self,out,apps,source=ROOT):
        self.out=Path(out).resolve();self.out.mkdir(parents=True,exist_ok=True);self.source=Path(source).resolve()
        prior=read(self.out/'status.json')
        self.apps=prior['apps'] if prior else [{**a,'run':str(Path(a['run']).resolve()) if a.get('run') else None,'status':'queued' if a.get('run') else 'no_graph','failures':{},'stagnant':0} for a in apps]
        if any(not re.fullmatch(r'[A-Za-z0-9_.-]+',a['key']) or a['key'] in ('.','..') for a in self.apps):raise ValueError('invalid application key')
        if len({a['key'] for a in self.apps})!=len(self.apps):raise ValueError('application keys must be unique')
        if prior and not (self.out/'STOP').exists():
            for app in self.apps:
                if app.get('status')=='paused' and app.get('pause_reason')=='user':app['status']='queued'
        # Preserve already spent attempts when resuming pre-normalization runs.
        for app in self.apps:
            merged={}
            for key,count in app.get('failures',{}).items():
                evidence=sorted((self.out/'issues'/app['key']/key).glob('attempt-*/issue.json'))
                canonical=fingerprint(read(evidence[-1])) if evidence else key
                merged[canonical]=merged.get(canonical,0)+count
            app['failures']=merged
        self.repair_lock=threading.Lock();self.save_lock=threading.RLock()
        self.save()

    def save(self):
        counts={s:sum(a['status']==s for a in self.apps) for s in sorted({a['status'] for a in self.apps})}
        with self.save_lock:
            apps=[{**a,'failures':dict(a.get('failures',{})),'accounting':dict(a.get('accounting',{})),'tried_versions':list(a.get('tried_versions',[]))} for a in self.apps]
            write(self.out/'status.json',{'apps':apps,'counts':counts,'updated_at':time.time()})

    def stopped(self):return (self.out/'STOP').exists()

    def notify(self,app,event,details):
        with (self.out/'events.jsonl').open('a') as f:f.write(json.dumps({'at':time.time(),'app':app['key'],'event':event,'details':details},ensure_ascii=False)+'\n')

    def run_round(self,app,source):
        with device_lock(app['run']):return self._run_round(app,source)

    def _run_round(self,app,source):
        run=Path(app['run'])
        if live_run(run):raise RuntimeError('existing traversal owns this run')
        output=run/'step_rounds'/('supervised-'+uuid.uuid4().hex)
        logdir=self.out/'rounds'/app['key']/output.name;logdir.mkdir(parents=True)
        manifest=read(run/'run_manifest.json');write(logdir/'source_before.json',{'framework_source':manifest.get('framework_source')})
        manifest['framework_source']=str(source);write(run/'run_manifest.json',manifest)
        command=[sys.executable,str(Path(source)/'run_progress_session.py'),str(run),str(output),'step']
        write(logdir/'invocation.json',{'argv':command,'source_hash':source_hash(source),'output':str(output)})
        with (logdir/'runner.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            app.update(status='running',pid=process.pid,session=str(output));self.save()
            while process.poll() is None:
                if self.stopped():output.with_suffix('.pause').touch()
                time.sleep(.5)
        result=read(output/'round-0001/result.json',{})
        session=read(output/'session.json',{'status':'interrupted'})
        calls=sorted((run/'calls').glob('[0-9][0-9][0-9][0-9]'))
        q=read(calls[-1]/'request.json',{}) if calls else {}
        # Only a failed call from this round can classify this interruption.
        round_start=(logdir/'invocation.json').stat().st_mtime
        error=read(calls[-1]/'http_error.json',{}) if calls and (calls[-1]/'request.json').stat().st_mtime>=round_start else {}
        text=(logdir/'runner.log').read_text()[-12000:]
        device_error=any(v in text for v in ('ConnectionRefusedError','DeviceUnavailable','device offline','no devices/emulators found'))
        issue=classify(session,result,error.get('status'),device_error)
        issue.update(stage=q.get('stage'),error=issue['reason'],output=str(output),log=str(logdir/'runner.log'),exit_code=process.returncode)
        app['rounds']=app.get('rounds',0)+1
        app['accounting']={**app.get('accounting',{}),**{k:app.get('accounting',{}).get(k,0)+session.get(k,0) for k in ('http_started','gui_started')}}
        write(logdir/'outcome.json',{'session':session,'result':result,'issue':issue})
        return issue

    def evidence(self,app,issue):
        run=Path(app['run']);key=fingerprint(issue);number=app['failures'].get(key,0)+1
        parent=self.out/'issues'/app['key']/key
        previous=sorted(parent.glob('attempt-*'),key=lambda p:p.stat().st_mtime) if parent.exists() else []
        folder=parent/(f'attempt-{number:02d}-'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True,exist_ok=False)
        if previous:
            write(folder/'previous_feedback.json',{'attempt':str(previous[-1]),'result':read(previous[-1]/'candidate_result.json',{}),'trial':read(previous[-1]/'live_trial.json',{})})
        write(folder/'issue.json',issue);write(folder/'graph_summary.json',app['graph'])
        for name in ('knowledge_current.json','pending_step.json','execution_pending.json','progress_current.json','ownership_review.json'):
            if (run/name).exists():shutil.copy2(run/name,folder/name)
        calls=sorted((run/'calls').glob('[0-9][0-9][0-9][0-9]'))[-3:]
        for call in calls:
            dest=folder/'calls'/call.name;dest.mkdir(parents=True)
            for name in ('request.json','response.json','http_error.json'):
                if (call/name).exists():shutil.copy2(call/name,dest/name)
            request=read(call/'request.json',{})
            for i,frame in enumerate(request.get('screenshots',[])):
                path=Path(frame);path=path if path.is_absolute() else run/path
                if path.is_file():shutil.copy2(path,dest/f'frame-{i}.png')
        shutil.copy2(issue['log'],folder/'runner.log')
        write(folder/'references.json',{'run':str(run),'source':app['source'],'snapshot':read(run/'knowledge_current.json'),'calls':[str(c) for c in calls]})
        app['failures'][key]=number;app['issue']=str(folder);return folder

    def promote(self,app,candidate):
        if not candidate.get('accepted'):return False
        source=Path(candidate['source'])
        if source_hash(source)!=candidate['source_hash']:raise ValueError('candidate changed after validation')
        app['source']=str(source);app['status']='queued';return True

    def reusable(self,app,signature):
        key=source_hash(Path(app['source']))+':'+signature
        candidate=read(self.out/'accepted_versions.json',{}).get(key)
        if not candidate or candidate['source_hash'] in app.get('tried_versions',[]):return None
        if source_hash(Path(candidate['source']))!=candidate['source_hash']:return None
        return candidate

    def cache_version(self,baseline,signature,candidate):
        with self.save_lock:
            path=self.out/'accepted_versions.json';versions=read(path,{})
            versions[source_hash(Path(baseline))+':'+signature]=candidate;write(path,versions)

    def luna_capacity(self,app):
        limit=read(Path(app['run'])/'run_manifest.json',{}).get('session_limits',{}).get('max_http')
        return limit is None or app.get('accounting',{}).get('http_started',0)<limit

    def charge_luna(self,app):
        if self.stopped():raise RuntimeError('paused before model dispatch')
        if not self.luna_capacity(app):raise RuntimeError('model budget exhausted')
        account=app.setdefault('accounting',{});account['http_started']=account.get('http_started',0)+1
        account['repair_http_started']=account.get('repair_http_started',0)+1
        path=Path(app['run'])/'run_manifest.json';manifest=read(path)
        manifest['actual_model_calls']=manifest.get('actual_model_calls',0)+1;write(path,manifest);self.save()

    def capacity(self,app):
        limits=read(Path(app['run'])/'run_manifest.json',{}).get('session_limits',{})
        used=app.get('accounting',{})
        return not (any(limits.get(limit) is not None and used.get(counter,0)+6>limits[limit] for counter,limit in [('http_started','max_http'),('gui_started','max_gui_commands')]) or (limits.get('max_rounds') is not None and app.get('rounds',0)>=limits['max_rounds']))

    def block_environment(self,app,issue):
        device=device_key(app['run'])
        for other in self.apps:
            if other.get('run') and device_key(other['run'])==device:
                other.update(status='environment_blocked',environment_reason=issue['reason'])
        app.update(status='environment_blocked',environment_reason=issue['reason'])
        self.notify(app,'environment_blocked',issue)

    def tick(self,app,repair=None):
        if self.stopped() or app.get('status')=='environment_blocked':return
        if live_run(app['run']):app['status']='externally_running';self.save();return
        if not app.get('source'):
            target=self.out/'sources'/(app['key']+'-'+uuid.uuid4().hex[:8]);app['source']=str(freeze(self.source,target))
        if not self.capacity(app):
            app.update(status='paused',pause_reason='budget');self.notify(app,'budget_limit',app.get('accounting',{}));self.save();return
        issue=self.run_round(app,app['source']);app['graph']=graph_summary(app['run'],app['source'])
        if issue['kind']=='paused':app.update(status='paused',pause_reason='user' if issue['reason']=='paused_by_user' else 'budget')
        elif issue['kind'] in ('service_wait','device_wait'):
            app.update(status='waiting',retry_after=time.time()+30);self.notify(app,'waiting',issue)
        elif issue['kind']=='environment_blocked':self.block_environment(app,issue)
        elif issue['kind']=='scope_idle':
            app['status']='complete' if app['graph']['complete'] else 'scope_idle'
            self.notify(app,app['status'],{'reason':issue['reason'],'graph':app['graph']})
        elif issue['kind']=='service_blocked':app['status']='service_blocked';self.notify(app,'stopped',issue)
        elif app['graph']['complete'] and issue['kind'] in ('continue','schedule'):app['status']='complete';self.notify(app,'complete',app['graph'])
        else:
            key=app['graph'].get('progress_key')
            app['stagnant']=app.get('stagnant',0)+1 if key and key==app.get('progress_key') else 0;app['progress_key']=key
            if issue['kind']=='continue' and app['stagnant']<6:app['status']='queued'
            else:
                if issue['kind']=='continue':issue.update(kind='framework',stage='stagnation',error='six rounds without graph progress')
                signature=fingerprint(issue)
                if app['failures'].get(signature,0)>=3:app['status']='needs_attention';self.notify(app,'repair_exhausted',issue)
                else:
                    folder=self.evidence(app,issue);app['status']='repairing';self.save();self.notify(app,'repair_started',issue)
                    if repair is None:
                        from debug_candidate import repair_candidate
                        repair=lambda source,folder:repair_candidate(source,folder,before_luna=lambda:self.charge_luna(app),stopped=self.stopped)
                    with self.repair_lock:
                        if self.stopped():app.update(status='paused',pause_reason='user');self.save();return
                        if not self.luna_capacity(app):app.update(status='paused',pause_reason='budget');self.save();return
                        candidate=self.reusable(app,signature)
                        if candidate is not None:
                            write(folder/'candidate_result.json',{**candidate,'reused':True});self.notify(app,'reusing_verified_candidate',candidate)
                        else:candidate=repair(Path(app['source']),folder)
                    if candidate.get('accepted') and source_hash(Path(candidate['source']))!=candidate.get('source_hash'):
                        raise ValueError('candidate changed before live trial')
                    if candidate.get('accepted') and not self.capacity(app):
                        app.update(status='paused',pause_reason='budget');self.notify(app,'trial_waits_for_budget',candidate);self.save();return
                    if candidate.get('accepted') and not self.stopped():
                        old=app['source'];accepted=False
                        app.setdefault('tried_versions',[]).append(candidate['source_hash'])
                        try:
                            trial_before=graph_summary(app['run'],candidate['source'])
                            trial=self.run_round(app,candidate['source'])
                            trial_graph=graph_summary(app['run'],candidate['source'])
                            settled=not any((Path(app['run'])/name).exists() for name in ('pending_step.json','execution_pending.json','ownership_review.json'))
                            accepted=settled and trial.get('reason')!='repair_pending' and trial['exit_code']==0 and (trial['kind']=='continue' or trial['kind']=='schedule' and trial_graph['complete'])
                            if issue['stage']=='stagnation' and trial_graph.get('progress_key')==trial_before.get('progress_key'):accepted=False
                            write(folder/'live_trial.json',{'issue':trial,'accepted':accepted,'graph':trial_graph})
                            if accepted:
                                self.promote(app,candidate);self.cache_version(old,signature,candidate);app['stagnant']=0;self.notify(app,'version_accepted',candidate)
                            else:
                                app['status']='queued'
                                if trial['kind']=='paused':app.update(status='paused',pause_reason='user' if trial['reason']=='paused_by_user' else 'budget')
                                elif trial['kind']=='environment_blocked':self.block_environment(app,trial)
                                elif trial['kind']=='service_blocked':app['status']='service_blocked'
                                elif trial['kind'] in ('device_wait','service_wait'):app.update(status='waiting',retry_after=time.time()+30)
                                self.notify(app,'trial_failed',trial)
                        finally:
                            if not accepted:
                                manifest=read(Path(app['run'])/'run_manifest.json');manifest['framework_source']=old;write(Path(app['run'])/'run_manifest.json',manifest)
                    else:
                        app['status']='queued' if not self.stopped() else 'paused';app['pause_reason']='user' if self.stopped() else None
                        if candidate.get('kind')=='service_blocked':app['status']='service_blocked'
                        self.notify(app,'candidate_rejected',candidate)
        self.save()

    def serve(self):
        with (self.out/'supervisor.lock').open('w') as lock, ThreadPoolExecutor(max_workers=2) as pool:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            active={}
            while not self.stopped() or active:
                ready=[] if self.stopped() else [a for a in self.apps if a['key'] not in active and (a['status'] in ('queued','externally_running','running','repairing') or a['status']=='waiting' and time.time()>=a.get('retry_after',0))]
                ready.sort(key=lambda a:a.get('scheduled_at',0))
                for app in ready[:max(0,2-len(active))]:
                    app['scheduled_at']=time.time();active[app['key']]=(pool.submit(self.tick,app),app)
                if not active:
                    if any(a['status']=='waiting' for a in self.apps) and not self.stopped():time.sleep(1);continue
                    break
                wait([v[0] for v in active.values()],timeout=1,return_when=FIRST_COMPLETED)
                for key,(future,app) in list(active.items()):
                    if not future.done():continue
                    try:future.result()
                    except BlockingIOError:
                        app.update(status='waiting',retry_after=time.time()+5)
                    except Exception as error:
                        app.update(status='needs_attention',supervisor_error=f'{type(error).__name__}: {error}');self.notify(app,'supervisor_error',app['supervisor_error'])
                    active.pop(key);self.save()
                if not active and ready and all(a['status']=='externally_running' for a in ready):time.sleep(5)
            self.save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('apps',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    Supervisor(args.output,read(args.apps)['apps']).serve()
