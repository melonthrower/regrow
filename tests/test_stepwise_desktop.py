import json
import pytest

@pytest.fixture(autouse=True)
def module_path(monkeypatch):
 monkeypatch.syspath_prepend(str(ROOT))

from tests.test_recovery_discovery import mod,ROOT


def action(kind,**kw):
 return dict(target='control',action=kind,x=12,y=24,text=None,end_x=None,end_y=None,reason='test',**{})|kw


def test_desktop_commands_are_not_adb_and_back_is_escape():
 m=mod('desktop_transport')
 assert "press('esc')" in m.commands(action('back'))[0]
 code=m.commands(action('input_text',text="a'b"))
 assert len(code)==3 and "hotkey('ctrl','a')" in code[1]
 compile(code[2],'<input>','exec')
 assert 'scroll(' in m.commands(action('scroll',dx=0,dy=2))[0]


def test_desktop_receipt_checks_process_exit():
 m=mod('desktop_transport')
 assert m.receipt({'returncode':1,'output':'','error':'failed'}).returncode==1
 assert m.receipt({'status':'success','output':''}).returncode!=0


def test_desktop_call_platform_context():
 m=mod('desktop_transport')
 q={'system_prompt':'shared','user_prompt':json.dumps({'平台':'Android触屏，不支持hover'}),'fixed_parts':[]}
 r=m.prepare_request(ROOT,q)
 assert json.loads(r['user_prompt'])['平台']=='OSWorld Linux桌面'
 assert 'Esc' in r['system_prompt']
 assert q['system_prompt']=='shared'


def test_existing_executor_dispatches_desktop_without_adb(tmp_path):
 m=mod('action_commands');d=mod('desktop_transport')
 class Fake:
  platform='desktop'
  account={'gui_started':0,'max_gui_commands':6}
  sent=[]
  def save(self):pass
  def send_command(self,code):
   self.sent.append(code);return d.receipt({'returncode':0,'output':'','error':''})
 t=Fake();r=m.execute(t,action('click'),tmp_path/'execution')
 assert t.sent==['pyautogui.click(12,24)']
 assert t.account['gui_started']==1 and r['exit_code']==0
 assert r['executed_steps'][0]['action']=='click'


def test_screenshot_retries_bad_image_without_actions(tmp_path,monkeypatch):
 from io import BytesIO
 from PIL import Image
 from types import SimpleNamespace
 m=mod('desktop_transport');buf=BytesIO();Image.new('RGB',(8,8)).save(buf,format='PNG')
 replies=iter([b'',b'\x89PNGbroken',buf.getvalue()]);calls=[]
 def get(*a,**k):
  calls.append(a);return SimpleNamespace(content=next(replies),status_code=200,raise_for_status=lambda:None)
 monkeypatch.setattr(m.requests,'get',get);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 t=m.DesktopRun.__new__(m.DesktopRun);t.endpoint='http://test'
 t.screenshot(tmp_path/'frame.png')
 assert len(calls)==3 and (tmp_path/'frame.png').read_bytes()==buf.getvalue()
 assert json.loads((tmp_path/'frame.png.capture.json').read_text())['failures']==2



@pytest.mark.parametrize('broken',['transfer','image'])
def test_screenshot_keeps_retrying_then_recovers(tmp_path,monkeypatch,broken):
 from io import BytesIO
 from PIL import Image
 from types import SimpleNamespace
 m=mod('desktop_transport');buf=BytesIO();Image.new('RGB',(8,8)).save(buf,format='PNG');calls=[]
 def get(*a,**k):
  calls.append(a)
  if len(calls)<6 and broken=='transfer':raise m.requests.exceptions.ChunkedEncodingError('incomplete')
  return SimpleNamespace(content=b'bad' if len(calls)<6 else buf.getvalue(),raise_for_status=lambda:None)
 monkeypatch.setattr(m.requests,'get',get);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 monkeypatch.setattr(m.requests,'post',lambda *a,**k:pytest.fail('must not repeat GUI'))
 t=m.DesktopRun.__new__(m.DesktopRun);t.endpoint='http://test';t.screenshot(tmp_path/'frame.png')
 assert len(calls)==6 and (tmp_path/'frame.png').read_bytes()==buf.getvalue()
 state=json.loads((tmp_path/'frame.png.capture.json').read_text())
 assert state['status']=='recovered' and state['failures']==5
 assert len((tmp_path/'frame.png.capture.jsonl').read_text().splitlines())==6


def test_screenshot_pause_preserves_delivered_action(tmp_path,monkeypatch):
 m=mod('desktop_transport');import progress
 out=tmp_path/'session/round-0001';out.mkdir(parents=True)
 pending=tmp_path/'execution_pending.json';pending.write_text('delivered')
 def get(*a,**k):
  (tmp_path/'session.pause').touch()
  raise m.requests.exceptions.ChunkedEncodingError('incomplete')
 monkeypatch.setattr(m.requests,'get',get)
 t=m.DesktopRun.__new__(m.DesktopRun);t.endpoint='http://test'
 with pytest.raises(progress.CapturePaused):
  with progress.round_status(tmp_path,out):t.screenshot(tmp_path/'frame.png')
 assert pending.read_text()=='delivered'
 state=json.loads((tmp_path/'progress_current.json').read_text())
 assert state['status']=='paused' and 'failure' not in state


def test_screenshot_configuration_error_is_not_retried(tmp_path,monkeypatch):
 m=mod('desktop_transport');calls=[]
 def get(*a,**k):
  calls.append(a);raise m.requests.exceptions.InvalidURL('bad config')
 monkeypatch.setattr(m.requests,'get',get)
 t=m.DesktopRun.__new__(m.DesktopRun);t.endpoint='bad'
 with pytest.raises(m.requests.exceptions.InvalidURL):t.screenshot(tmp_path/'frame.png')
 assert len(calls)==1


def test_screenshot_retries_http500_without_sending_actions(tmp_path,monkeypatch):
 from io import BytesIO
 from PIL import Image
 from types import SimpleNamespace
 m=mod('desktop_transport');buf=BytesIO();Image.new('RGB',(8,8)).save(buf,format='PNG');calls=[]
 def get(*a,**k):
  calls.append(a)
  if len(calls)==1:
   response=m.requests.Response();response.status_code=500
   raise m.requests.exceptions.HTTPError('capture failed',response=response)
  return SimpleNamespace(content=buf.getvalue(),raise_for_status=lambda:None)
 monkeypatch.setattr(m.requests,'get',get);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 monkeypatch.setattr(m.requests,'post',lambda *a,**k:pytest.fail('must not repeat GUI'))
 t=m.DesktopRun.__new__(m.DesktopRun);t.endpoint='http://test';t.screenshot(tmp_path/'frame.png')
 assert len(calls)==2 and (tmp_path/'frame.png').read_bytes()==buf.getvalue()
 assert json.loads((tmp_path/'frame.png.capture.jsonl').read_text().splitlines()[0])['error_type']=='HTTP500'


def test_foreground_connection_failure_is_unknown_not_fatal(monkeypatch):
 m=mod('desktop_transport');t=m.DesktopRun.__new__(m.DesktopRun);t.package='Clock';t.window_class='clocks'
 def failed(argv,**kwargs):raise m.requests.exceptions.ConnectionError('reset')
 monkeypatch.setattr(t,'command',failed)
 value=t.foreground_window()
 assert value['与目标应用一致'] is None and value['窗口记录']==''
 assert 'ConnectionError' in value['读取错误']


def test_foreground_configuration_failure_is_not_hidden(monkeypatch):
 m=mod('desktop_transport');t=m.DesktopRun.__new__(m.DesktopRun);t.package='Clock'
 def failed(argv,**kwargs):raise m.requests.exceptions.InvalidURL('bad config')
 monkeypatch.setattr(t,'command',failed)
 with pytest.raises(m.requests.exceptions.InvalidURL):t.foreground_window()
