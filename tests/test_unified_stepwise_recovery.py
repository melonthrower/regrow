from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_recovery_uses_same_action_schema_as_exploration():
    actions=tasks().helper('action_commands');policy=tasks().helper('recovery')
    assert policy.schema()['properties']['action']['anyOf'][0]==actions.schema()
    assert {'click','double_click','long_press','input_text','scroll','back','wait'}<=set(actions.schema()['properties']['action']['enum'])
    assert 'restart_app' not in actions.schema()['properties']['action']['enum']
    with pytest.raises(ValueError):actions.commands({'action':'hover','x':1,'y':2})


def decision(exception='blocking_popup',mode='act',action=None,tool=None):
    if action:action={**{'text':None,'end_x':None,'end_y':None,'skip_task':False},**action}
    return {'exception':exception,'decision':mode,'action':action,'framework_tool':tool,'reason':'明确关闭入口','handoff':'查看下一张截图确认是否清除'}


def test_recovery_separates_flow_tools_and_actions():
    p=tasks().helper('recovery');a={'action':'click','target':'Got it','x':20,'y':20,'reason':'关闭教学'}
    p.validate(decision(action=a))
    with pytest.raises(ValueError):p.validate(decision(action=a,tool='restart_app'))
    with pytest.raises(ValueError):p.validate(decision(mode='resume_exploration',action=a))
    with pytest.raises(ValueError):p.validate(decision(tool='restart_app'))
    p.validate(decision(exception='unexpected_exit',tool='restart_app'))


def test_exit_blocks_task_but_popup_preserves_pending():
    from tests.test_stepwise_region_tasks import proposal,row
    from tests.test_stepwise_resume_route import fixture
    m=tasks();_,r,_=fixture();m.apply_plan(r['menu'],proposal([row()]),'p')
    reply={'action_result':{'exception':'unexpected_exit'},'task_result':{'name':'查看内容','status':'pending','evidence':'应用退出','findings':[]}}
    m.settle_task(r['menu'],{'task_name':'查看内容'},reply,'a')
    assert r['menu']['tasks']['查看内容']['status']=='blocked'


def test_new_exceptions_route_without_registering_external_regions():
    from tests.test_stepwise_update_exception import reply
    m=tasks().helper('update_step')
    for name in ['blocking_popup','unexpected_exit','external_app','unclassified']:
        r=reply(name)
        r['exploration_update'].pop('entry_name')  # Removed from the current wire schema.
        assert m.route_update(ROOT,r,{'exit_code':0})['next_action_mode']=='recover'


def test_popup_loop_has_no_region_registration_between_actions(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from PIL import Image
    from tests.test_region_registration import fixture,invoke,module as regmodule
    loop=tasks().helper('recover_loop');run,_,_=fixture(tmp_path);invoke(regmodule(),run)
    (run/'run_manifest.json').write_text('{}');before=(run/'knowledge_current.json').read_bytes()
    events=[]
    class Transport:
        package='Clock';account={'gui_started':0,'max_gui_commands':6,'http_started':0,'max_http':6}
        def save(self):pass
        def screenshot(self,path):Image.new('RGB',(100,100),'blue').save(path)
        def adb(self,argv):events.append(argv);return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    t=Transport();t.run=run
    discovery=loop.helper('discovery_step');original=loop.helper
    monkeypatch.setattr(loop,'helper',lambda name:discovery if name=='discovery_step' else original(name))
    monkeypatch.setattr(discovery,'await_discovery',lambda *args:events.append('await_discovery'))
    monkeypatch.setattr(discovery,'run_stage',lambda *args,**kwargs:events.append('discover'))
    monkeypatch.setattr(loop.time,'sleep',lambda n:None)
    replies=[decision(action={'action':'click','target':'Got it','x':20,'y':20,'reason':'关闭'}),decision(exception='none',mode='resume_exploration')]
    def call(q):
        assert q['stage']=='recovery_action' and 'regions' not in q['response_schema']['properties']
        n=2-len(replies);return str(n),replies.pop(0)
    result=loop.run(ROOT,t,tmp_path,call)
    assert events==[['shell','input','tap','20','20'],'await_discovery','discover']
    assert before==(run/'knowledge_current.json').read_bytes()
    assert result['status']=='paused_after_recovery_discovery'


def test_recovery_restart_fallback_and_failed_delivery_stop(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from PIL import Image
    from tests.test_region_registration import fixture,invoke,module as regmodule
    loop=tasks().helper('recover_loop');run,_,_=fixture(tmp_path);invoke(regmodule(),run)
    (run/'run_manifest.json').write_text('{}');seen=[]
    class Transport:
        package='Clock';account={'gui_started':0,'max_gui_commands':6,'http_started':0,'max_http':6}
        def save(self):pass
        def screenshot(self,path):Image.new('RGB',(100,100),'blue').save(path)
        def adb(self,argv):
            seen.append(argv)
            if argv[:3]==['shell','cmd','package']:return SimpleNamespace(returncode=0,stdout=b'Clock/.Main',stderr=b'',check_returncode=lambda:None)
            return SimpleNamespace(returncode=1 if 'force-stop' in argv else 0,stdout=b'',stderr=b'')
    t=Transport();t.run=run;monkeypatch.setattr(loop.time,'sleep',lambda n:None)
    def call(q):return str(len(seen)),decision(exception='external_app',action={'action':'back','target':'系统返回','x':None,'y':None,'reason':'尝试返回'})
    result=loop.run(ROOT,t,tmp_path,call)
    assert result['status']=='review_execution'
    assert seen.count(['shell','input','keyevent','4'])==2
    assert ['shell','am','force-stop','Clock'] in seen
    before=len(seen);assert loop.run(ROOT,t,tmp_path,call)['status']=='review_execution';assert len(seen)==before


def test_no_exception_hands_off_without_executing_proposed_back():
    p=tasks().helper('recovery')
    raw=decision(exception='none',action={'action':'back','target':'全屏时钟','x':None,'y':None,'reason':'退出屏保'})
    result=p.resolve(raw)
    assert result['decision']=='resume_exploration' and result['action'] is None
    assert raw['action']['action']=='back'  # Preserve the model's original reply as evidence.


def test_restart_history_discloses_restriction_and_feedback():
    import json
    p=tasks().helper('recovery')
    q=p.build_request(ROOT,{'actions':[{'framework_tool':'restart_app','execution_feedback':[{'stdout':'pid 42'}]}],
        'framework_feedback':'Already restarted; choose another recovery'},'Clock','World','exit','frame.png')
    d=json.loads(q['user_prompt'])
    assert '已使用' in d['重启工具状态']
    assert d['框架反馈']=='Already restarted; choose another recovery'
    assert 'pid 42' in q['user_prompt']


def test_repeated_restart_replans_instead_of_stopping(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from PIL import Image
    from tests.test_region_registration import fixture,invoke,module as regmodule
    loop=tasks().helper('recover_loop');run,_,_=fixture(tmp_path);invoke(regmodule(),run)
    (run/'run_manifest.json').write_text('{}');events=[]
    class Transport:
        package='Clock';account={'gui_started':0,'max_gui_commands':6,'http_started':0,'max_http':6}
        def save(self):pass
        def screenshot(self,path):Image.new('RGB',(100,100),'blue').save(path)
        def adb(self,argv):
            events.append(argv)
            if argv[:3]==['shell','cmd','package']:return SimpleNamespace(stdout=b'Clock/.Main',check_returncode=lambda:None)
            return SimpleNamespace(returncode=0,stdout=b'launch accepted',stderr=b'')
    t=Transport();t.run=run
    discovery=loop.helper('discovery_step');original=loop.helper
    monkeypatch.setattr(loop,'helper',lambda n:discovery if n=='discovery_step' else original(n))
    monkeypatch.setattr(discovery,'await_discovery',lambda *a:None)
    monkeypatch.setattr(discovery,'run_stage',lambda *a,**k:None)
    monkeypatch.setattr(loop.time,'sleep',lambda n:None)
    replies=[decision(exception='unexpected_exit',tool='restart_app'),decision(exception='unexpected_exit',tool='restart_app'),decision(exception='none',mode='resume_exploration')]
    requests=[]
    def call(q):requests.append(q);return str(len(requests)),replies.pop(0)
    result=loop.run(ROOT,t,tmp_path,call)
    assert result['status']=='paused_after_recovery_discovery'
    assert len(requests)==3 and t.account['gui_started']==2
    assert '重复请求未执行' in requests[-1]['user_prompt']
    assert 'launch accepted' in requests[-1]['user_prompt']
