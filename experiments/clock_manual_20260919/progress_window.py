"""Traversal progress, run controls and optional application selection."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen
import progress
import region_graph


class RoundRunner:
    def __init__(self,run,launch=subprocess.Popen):
        self.run=Path(run).resolve();self.launch=launch;self.child=None;self.output=None;self.lock=threading.Lock()

    def status(self):
        session={}
        if self.output and (self.output/'session.json').exists():session=progress.read(self.output/'session.json')
        result={}
        if self.output and session.get('rounds'):
            last=self.output/session['rounds'][-1]/'result.json'
            if last.exists():result=progress.read(last)
        return {'last_result':result.get('status'),'stop_reason':result.get('reason'),'running':self.child is not None and self.child.poll() is None,
                'exit_code':None if self.child is None else self.child.poll(),
                'pause_requested':bool(self.output and self.output.with_suffix('.pause').exists()),
                'session_status':session.get('status'),'mode':session.get('mode')}

    def pause(self):
        with self.lock:
            if not self.status()['running']:raise RuntimeError('No running session')
            self.output.with_suffix('.pause').write_text('Pause after current round\n')
            return self.status()

    def start(self,mode='step'):
        if mode not in ('step','auto'):raise ValueError('invalid run mode')
        with self.lock:
            if self.status()['running'] or progress.snapshot(self.run)['status']=='running':
                raise RuntimeError('已有遍历回合正在运行')
            parent=self.run/'step_rounds';parent.mkdir(exist_ok=True)
            name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
            self.output=parent/name
            argv=[sys.executable,str(Path(__file__).with_name('run_progress_session.py')),str(self.run),str(self.output),mode]
            (parent/(name+'.launch.json')).write_text(json.dumps({'argv':argv,'cwd':str(Path(__file__).parent)},ensure_ascii=False,indent=2))
            with (parent/(name+'.log')).open('xb') as log:
                self.child=self.launch(argv,stdout=log,stderr=subprocess.STDOUT,cwd=Path(__file__).parent,start_new_session=True)
            return self.status()


def server(run,mirror,port=0,runner=None,hub=None):
    parsed=urlsplit(mirror)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1') or parsed.username or parsed.password:
        raise ValueError('mirror must be a local HTTP origin')
    mirror=f'http://127.0.0.1:{parsed.port or 80}'
    runner=runner or (RoundRunner(run) if run else None);token=secrets.token_urlsafe(32)
    def active():return (hub.run,hub.runner) if hub else (run,runner)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            try:
                if path=='/':body=Path(__file__).with_name('progress_window.html').read_text().replace('__RUN_TOKEN__',token).encode();mime='text/html; charset=utf-8'
                elif path=='/replay':
                    body=Path(__file__).with_name('traversal_replay.html').read_bytes();mime='text/html; charset=utf-8'
                elif path=='/replay.json':
                    import traversal_replay
                    active_run,_=active()
                    body=json.dumps(traversal_replay.project(active_run),ensure_ascii=False).encode();mime='application/json; charset=utf-8'
                elif path=='/replay-image':
                    import traversal_replay
                    active_run,_=active();args=parse_qs(urlsplit(self.path).query)
                    body=traversal_replay.asset(active_run,args['path'][0]).read_bytes();mime='image/png'
                elif path=='/graph':
                    body=Path(__file__).with_name('region_graph.html').read_bytes();mime='text/html; charset=utf-8'
                elif path=='/graph.json':
                    active_run,_=active()
                    value=region_graph.project(active_run) if active_run else {'nodes':[],'edges':[],'app':'尚未选择应用','snapshot':None}
                    body=json.dumps(value,ensure_ascii=False).encode();mime='application/json; charset=utf-8'
                elif path=='/graph-image':
                    active_run,_=active();args=parse_qs(urlsplit(self.path).query)
                    file=region_graph.asset(active_run,args['snapshot'][0],args['region'][0],args.get('control',[None])[0])
                    body=file.read_bytes();mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(file.suffix.lower(),'image/png')
                elif path=='/applications.json':
                    value=hub.catalog() if hub else {'apps':[]};body=json.dumps(value,ensure_ascii=False).encode();mime='application/json; charset=utf-8'
                elif path=='/health':
                    body=json.dumps({'service':'stepwise_launcher','root':str(hub.parent.resolve()) if hub else None}).encode();mime='application/json'
                elif path=='/progress.json':
                    active_run,active_runner=active()
                    value=progress.snapshot(active_run) if active_run else {'no_run':True,'status':'idle'}
                    value['runner']=active_runner.status() if active_runner else {'running':False}
                    from exploration_summary import summarize
                    value['exploration_summary']=summarize(active_run,getattr(active_runner,'output',None),value['runner']['running']) if active_run else {}
                    if value['runner']['running'] and value['status']!='running':
                        value.update(status='running',phase=None,phase_label=None,current_task=None,detail='本轮正在启动或收尾')
                    body=json.dumps(value,ensure_ascii=False).encode();mime='application/json; charset=utf-8'
                elif path=='/frame.png':
                    active_run,_=active()
                    if not active_run:self.send_error(503,'No traversal frame yet');return
                    cached=Path(active_run)/'live_frame.png'
                    if not cached.exists():cached=Path(active_run)/'screenshots/initial.png'
                    body=cached.read_bytes()
                    mime='image/png'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except (OSError,ValueError,KeyError):self.send_error(503,'Data temporarily unavailable')
        def do_POST(self):
            path=urlsplit(self.path).path
            if path not in ('/next','/start','/pause','/select'):self.send_error(404);return
            if self.headers.get('X-Run-Token')!=token:self.send_error(403);return
            try:
                if path=='/select':
                    if hub is None:raise ValueError('Application launcher is unavailable')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=4096:raise ValueError('Invalid selection request')
                    selection=json.loads(self.rfile.read(size));result=hub.select(selection['package'],selection['mode'],selection.get('run_id'))
                else:
                    _,active_runner=active()
                    if active_runner is None:raise ValueError('Select an application first')
                    result=active_runner.pause() if path=='/pause' else active_runner.start('auto' if path=='/start' else 'step')
            except RuntimeError:self.send_error(409,'A traversal round is already running');return
            except (OSError,ValueError,KeyError):self.send_error(503,'Could not start traversal');return
            body=json.dumps(result).encode();self.send_response(202);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);parser.add_argument('mirror')
    args=parser.parse_args();app=server(args.run.resolve(),args.mirror)
    print(json.dumps({'url':f'http://127.0.0.1:{app.server_port}/','run':str(args.run.resolve())}),flush=True)
    app.serve_forever()
