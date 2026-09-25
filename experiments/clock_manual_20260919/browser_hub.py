"""One-origin original traversal panels with demand-driven device projection."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit
import json,sys,time,threading,subprocess,base64,html,os,re
import requests
from PIL import Image
from io import BytesIO
ROOT=Path(__file__).resolve().parent;B=ROOT/'records/browser_hub_20260923'
sys.path.insert(0,str(ROOT))
import progress
from desktop_transport import display_capture
APPS={}
LOCKS={key:threading.Lock() for key in APPS};CACHE={}
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(v,ensure_ascii=False,indent=2));temp.replace(p)
def frame(key):
 app=APPS[key];run=Path(app['run']) if app.get('run') else None
 if run is None:return {'error':'没有可续接的应用记录','stale':True}
 with LOCKS.setdefault(key,threading.Lock()):
  now=time.time();old=CACHE.get(key)
  if old and now-old['checked_at']<3:return old
  result={'checked_at':now,'stale':False,'error':None}
  try:
   m=json.loads((run/'run_manifest.json').read_text())
   if m.get('platform')=='desktop':
    data=display_capture(m['desktop']['container'])
   else:
    r=subprocess.run(['/data/shenghonghui/android-sdk/platform-tools/adb','-s',m['device'],'exec-out','screencap','-p'],capture_output=True,timeout=8);r.check_returncode();data=r.stdout
   Image.open(BytesIO(data)).verify()
   result.update(captured_at=time.time(),image='data:image/png;base64,'+base64.b64encode(data).decode())
   target=B/'captures'/key;target.mkdir(parents=True,exist_ok=True);(target/'latest.png').write_bytes(data)
   save(target/'capture.json',{'captured_at':result['captured_at'],'source':'device_capture','gui_actions':0})
  except Exception as error:
   result.update(stale=True,error='设备取图未成功：'+type(error).__name__)
   if old and old.get('image'):result.update(image=old['image'],captured_at=old['captured_at'])
   else:
    p=run/'live_frame.png'
    if p.exists():result.update(image='data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),captured_at=p.stat().st_mtime)
  try:
   s=progress.snapshot(run);result['traversal']={k:s.get(k) for k in ('status','phase_label','detail','current_task')}
  except Exception:result['traversal']={'status':'unknown'}
  CACHE[key]=result;return result

BACKENDS={};SERVICES=[];BACKEND_LOCK=threading.Lock()
from progress_window import RoundRunner
class ExistingProcess:
 def __init__(self,path,command):self.path=path;self.command=command
 def poll(self):
  try:return None if self.path.read_bytes()==self.command else 0
  except OSError:return 0
class SharedRunner(RoundRunner):
 def __init__(self,run):
  super().__init__(run,launch=self.launch_configured)
  sessions=list((self.run/'step_rounds').glob('*/session.json'))
  if sessions:self.output=max(sessions,key=lambda p:p.stat().st_mtime).parent
 def launch_configured(self,argv,**kwargs):
  manifest=json.loads((self.run/'run_manifest.json').read_text())
  source=Path(manifest['framework_source'])
  actual=[argv[0],str(source/'run_progress_session.py'),*argv[2:]]
  output=Path(argv[3])
  save(output.parent/(output.name+'.launch.json'),{'argv':actual,'cwd':str(source)})
  return subprocess.Popen(actual,**{**kwargs,'cwd':source})
 def status(self):
  if self.child is None or self.child.poll() is not None:
   for cmd in Path('/proc').glob('[0-9]*/cmdline'):
    try:raw=cmd.read_bytes();args=[a.decode() for a in raw.split(b'\0') if a]
    except (OSError,UnicodeError):continue
    for i,arg in enumerate(args[:-2]):
     if arg.endswith('/run_progress_session.py') and args[i+1]==str(self.run):
      output=Path(args[i+2]).resolve()
      if output.parent==self.run/'step_rounds':
       self.child=ExistingProcess(cmd,raw);self.output=output
       return super().status()
  return super().status()

def backend(key):
 with BACKEND_LOCK:
  if key in BACKENDS:return BACKENDS[key]
  item=APPS[key]
  run=item.get('run')
  if not run or not Path(run).exists():return None
  from progress_window import server
  service=server(run,'http://127.0.0.1:1',0,runner=SharedRunner(run))
  threading.Thread(target=service.serve_forever,daemon=True).start();SERVICES.append(service)
  url=f'http://127.0.0.1:{service.server_port}/';BACKENDS[key]=url;return url
def panel_html(key,text):
 prefix='/panel/'+key
 # Keep all original panel/graph controls within this single forwarded origin.
 text=re.sub(r"""(["'`])/(?!/)""",lambda m:m.group(1)+prefix+'/',text)
 text=text.replace('href="'+prefix+'/"','href="/view/'+key+'"')
 links=' · '.join('<a href="/view/'+html.escape(k)+'">'+html.escape(k)+'</a>' for k in APPS)
 nav='<details style="padding:8px 26px;background:#fff"><summary>切换应用：'+html.escape(key)+'</summary>'+links+'</details>'
 text=text.replace('<header>',nav+'<header>',1)
 if 'function frame(){' in text:
  begin=text.index('function frame(){');end=text.index('async function submit',begin)
  live="""async function frame(){if(document.hidden){setTimeout(frame,2000);return}try{
const r=await fetch('/api/APPKEY',{cache:'no-store'}),v=await r.json();
if(v.image)$('frame').src=v.image;
put('mirror-status',(v.stale?'断流／历史截图：'+v.error:'当前设备投屏')+' · '+(v.captured_at?new Date(v.captured_at*1000).toLocaleTimeString():'无截图'));
}catch(e){put('mirror-status','设备投屏连接失败；下方保留旧图')}finally{setTimeout(frame,3000)}}
""".replace('APPKEY',key)
  text=text[:begin]+live+text[end:]
  text=text.replace('async function refresh(){try{','async function refresh(){if(document.hidden){setTimeout(refresh,1500);return}try{')
 return text
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  parsed=urlsplit(self.path);path=parsed.path
  if path=='/' or path.startswith('/view/'):
   key=path.split('/')[-1] if path!='/' else 'clock'
   if key not in APPS:self.send_error(404);return
   origin=backend(key)
   if origin:
    text=requests.get(origin,timeout=10).text
    data=panel_html(key,text).encode()
   else:
    data=('<meta charset="utf-8"><p>该应用暂无遍历记录。</p><a href="/">返回应用列表</a>').encode()
   mime='text/html; charset=utf-8'
  elif path.startswith('/api/') and path[5:] in APPS:
   data=json.dumps(frame(path[5:]),ensure_ascii=False).encode();mime='application/json'
  elif path.startswith('/panel/'):
   parts=path.split('/',3)
   if len(parts)!=4 or parts[2] not in APPS:self.send_error(404);return
   key=parts[2];endpoint=parts[3]
   if endpoint not in ('progress.json','graph.json','graph','graph-image','frame.png','applications.json','replay','replay.json','replay-image'):self.send_error(404);return
   origin=backend(key)
   if not origin:self.send_error(404);return
   response=requests.get(origin+endpoint+('?' + parsed.query if parsed.query else ''),timeout=15)
   if not response.ok:self.send_error(response.status_code);return
   mime=response.headers.get('Content-Type','application/octet-stream');data=response.content
   if endpoint in ('graph','replay'):data=panel_html(key,response.text).encode()
   elif endpoint=='replay.json':data=response.text.replace('/replay-image?','/panel/'+key+'/replay-image?').replace('/graph-image?','/panel/'+key+'/graph-image?').encode()
   elif endpoint=='graph.json':data=response.text.replace('/graph-image?','/panel/'+key+'/graph-image?').encode()
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers()
  try:self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_POST(self):
  parts=urlsplit(self.path).path.split('/',3)
  if len(parts)!=4 or parts[1]!='panel' or parts[2] not in APPS or parts[3] not in ('start','next','pause'):
   self.send_error(404);return
  origin=backend(parts[2])
  if not origin:self.send_error(404);return
  response=requests.post(origin+parts[3],data=b'',headers={'X-Run-Token':self.headers.get('X-Run-Token','')},timeout=15)
  data=response.content;self.send_response(response.status_code);self.send_header('Content-Type',response.headers.get('Content-Type','application/json'));self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
if __name__=='__main__':
 APPS={a['key']:a for a in json.loads((ROOT/'records/multi_resume_20260923/status.json').read_text())['apps']}
 port=urlsplit(json.loads((B/'server.json').read_text())['url']).port if (B/'server.json').exists() else 0
 app=ThreadingHTTPServer(('127.0.0.1',port),Handler)
 save(B/'server.json',{'url':f'http://127.0.0.1:{app.server_port}/','pid':os.getpid(),'apps':list(APPS)})
 app.serve_forever()
