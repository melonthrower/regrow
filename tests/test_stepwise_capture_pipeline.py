import importlib.util
from pathlib import Path
from io import BytesIO
import json
import pytest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def png():
 b=BytesIO();Image.new('RGB',(10,10),'green').save(b,format='PNG');return b.getvalue()

def test_container_capture_never_uses_guest_http(tmp_path,monkeypatch):
 monkeypatch.syspath_prepend(str(ROOT));import desktop_transport as m
 t=m.DesktopRun.__new__(m.DesktopRun);t.run=tmp_path
 t.configure({'desktop':{'controller':'http://test','launch_command':['test'],'window_class':'test','container':'test'}})
 calls=[]
 def failed(*a,**k):calls.append(1);raise m.requests.exceptions.ReadTimeout()
 monkeypatch.setattr(m.requests,'get',failed);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 monkeypatch.setattr(m,'display_capture',lambda c:png())
 t.screenshot(tmp_path/'after.png')
 assert len(calls)==0
 assert (tmp_path/'live_frame.png').read_bytes()==png()
 assert json.loads((tmp_path/'after.png.source.json').read_text())['source']=='qemu_display'
 t.screenshot(tmp_path/'next.png');assert len(calls)==0

def test_web_frame_is_cached_and_never_calls_vm(tmp_path,monkeypatch):
 monkeypatch.syspath_prepend(str(ROOT));import progress_window as m
 import threading,urllib.request
 (tmp_path/'live_frame.png').write_bytes(png())
 monkeypatch.setattr(m,'urlopen',lambda *a,**k:pytest.fail('web must not capture'))
 app=m.server(tmp_path,'http://127.0.0.1:1');th=threading.Thread(target=app.serve_forever,daemon=True);th.start()
 try:
  assert urllib.request.urlopen(f'http://127.0.0.1:{app.server_port}/frame.png').read()==png()
 finally:app.shutdown();app.server_close();th.join()

def test_pending_receipt_rebuilds_update_without_action(tmp_path,monkeypatch):
 monkeypatch.syspath_prepend(str(ROOT));import result_updater as m
 folder=tmp_path/'action_attempts/a1';folder.mkdir(parents=True)
 (folder/'receipt.json').write_text(json.dumps({'exit_code':0}))
 (folder/'binding.json').write_text('{}');(folder/'proposal.json').write_text('{}')
 (folder/'before.png').write_bytes(png())
 class T:
  run=tmp_path;package='app'
  def screenshot(self,p):p.write_bytes(png())
  def command(self,*a):pytest.fail('must not deliver')
 monkeypatch.setattr(m,'foreground_window',lambda t:None)
 monkeypatch.setattr(m,'build_attempt_update',lambda *a:{'role':'observation_update'})
 q=m.resume_update_request(ROOT,T(),folder)
 assert q['role']=='observation_update' and (folder/'after.png').exists()
 (folder/'receipt.json').write_text(json.dumps({'exit_code':1}))
 with pytest.raises(ValueError):m.resume_update_request(ROOT,T(),folder)


def test_resume_preserves_existing_frame_and_window_evidence(tmp_path,monkeypatch):
 monkeypatch.syspath_prepend(str(ROOT));import result_updater as m
 folder=tmp_path/'a1';folder.mkdir()
 for name,value in [('receipt',{'exit_code':0}),('binding',{}),('proposal',{}),('after_window',{'original':True})]:
  (folder/(name+'.json')).write_text(json.dumps(value))
 (folder/'after.png').write_bytes(png())
 class T:
  run=tmp_path;package='app'
  def screenshot(self,p):pytest.fail('saved evidence must be reused')
 monkeypatch.setattr(m,'foreground_window',lambda t:pytest.fail('must not mix new window evidence'))
 monkeypatch.setattr(m,'build_attempt_update',lambda *a:{})
 m.resume_update_request(ROOT,T(),folder)
 assert json.loads((folder/'after_window.json').read_text())=={'original':True}
