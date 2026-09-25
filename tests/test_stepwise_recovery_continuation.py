import json
from types import SimpleNamespace
from PIL import Image
from tests.test_region_registration import fixture,invoke,module as regmodule
from tests.test_recovery_discovery import mod,ROOT


def test_changed_pre_dispatch_target_reobserves_instead_of_stopping(tmp_path,monkeypatch):
    loop=mod('recover_loop');run,_,_=fixture(tmp_path);invoke(regmodule(),run)
    (run/'run_manifest.json').write_text('{}');events=[];captures=[]
    class Transport:
        package='Clock';account={'gui_started':0,'max_gui_commands':6,'http_started':0,'max_http':6}
        def save(self):pass
        def screenshot(self,path):
            captures.append(path);Image.new('RGB',(100,100),'blue' if len(captures)==1 else 'red').save(path)
        def adb(self,argv):raise AssertionError('must not dispatch stale click')
    t=Transport();t.run=run;original=loop.helper;d=original('discovery_step')
    monkeypatch.setattr(loop,'helper',lambda n:d if n=='discovery_step' else original(n))
    monkeypatch.setattr(d,'await_discovery',lambda *a:events.append('await'))
    monkeypatch.setattr(d,'run_stage',lambda *a,**k:events.append('discover'))
    calls=[]
    def call(q):
        calls.append(q)
        if len(calls)==1:
            a=dict(action='click',target='Close',x=20,y=20,end_x=None,end_y=None,text=None,reason='close',skip_task=False,request_task_review=False)
            return '1',dict(exception='blocking_popup',decision='act',action=a,framework_tool=None,reason='close',handoff='verify')
        assert '未投递' in json.loads(q['user_prompt'])['框架反馈']
        return '2',dict(exception='none',decision='resume_exploration',action=None,framework_tool=None,reason='now clear',handoff='resume')
    result=loop.run(ROOT,t,tmp_path,call)
    assert result['status']=='paused_after_recovery_discovery' and events==['await','discover']
    episode=json.loads(next((run/'recovery_episodes').glob('*/episode.json')).read_text())
    assert episode['actions']==[] and episode['withheld_actions'][0]['source_call']=='1'
