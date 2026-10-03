import json
import pytest
from tests.test_region_registration import fixture,module,invoke,read_region
from tests.test_stepwise_region_tasks import tasks


def test_retained_region_without_delta_stays_interactive(tmp_path):
    run,graph,reply=fixture(tmp_path);reply['action_result']['exception']='none'
    reply['previous_regions'][0]['state']='retained_interactive'
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    p=invoke(module(),run);state=json.loads((run/p['snapshot']/'runtime_state.json').read_text())
    assert state['interactive_regions']==['r1'] and state['next_action_mode']=='explore'
    assert state['observation']['control_refs']==[] # no current image location in this fixture
    assert read_region(run,p)['controls']['c1']['action_refs']==['a1']


def test_changed_without_delta_is_known_interactive_but_not_old_control_location(tmp_path):
    run,_,reply=fixture(tmp_path);reply['action_result']['exception']='none';reply['previous_regions'][0]['state']='changed_interactive'
    (run/'calls/0001/response.json').write_text(json.dumps(reply));p=invoke(module(),run)
    state=json.loads((run/p['snapshot']/'runtime_state.json').read_text())
    assert state['interactive_regions']==['r1'] and state['observation']['control_refs']==[]


def test_historical_reason_and_recovery_are_explicit():
    m=tasks().helper('task_action_context');r={'r':{'name':'Files','actions':{}}}
    t={'reason':'当前弹窗阻挡操作','status':'pending','blocker_history':[{'condition':'foreground_exception','exception':'blocking_popup','resolved_by':'36'}]}
    text,evidence=m.build(r,{},'r','探索排序',t)
    assert '原任务目标与结束条件（仍用于本轮核对，其中界面描述属于建立时观察）' in text
    assert '阻塞已在后续观察中解除' in text
    assert '目标说明：当前弹窗' not in text


@pytest.mark.parametrize("supplement", [False, True])
def test_normal_none_routes_to_discovery_without_gui(tmp_path,monkeypatch,supplement):
    from tests.test_stepwise_task_correction import saved
    from tests.test_stepwise_resume_route import ROOT
    from types import SimpleNamespace
    from PIL import Image
    run,_,_=saved(tmp_path);(run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'Clock'}))
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as runner
    q={'stage':'action_selection','action_ready':True}
    if supplement:
        frame=tmp_path/'supplement.png';Image.new('RGB',(50,80),'white').save(frame)
        q['screenshots']=[str(frame)]
    class Transport:
        def save(self):self.ledger.write_text(json.dumps(self.account))
        def screenshot(self,path):Image.new('RGB',(50,80)).save(path)
        def adb(self,args):
            assert args==['shell','dumpsys','window']
            return SimpleNamespace(returncode=0,stdout=b'')
        def call(self,q):raise AssertionError('model mocked at acceptance boundary')
    monkeypatch.setattr(runner,'RecoveryRun',Transport)
    monkeypatch.setattr(runner,'assemble_current_context',lambda *args:q.copy())
    monkeypatch.setattr(runner.visual_backtrack,'resume_pending',lambda *args:None)
    accepted={'result':{'request':q,'call':'test-none','proposal':{'action':'none','reason':'输入控件缺少定位'},'binding':{'status':'no_action'}}}
    monkeypatch.setattr(runner.step_repair,'Runner',lambda *args:SimpleNamespace(perform=lambda *args:accepted))
    out=tmp_path/'round';runner._run_step(ROOT,run,out)
    state=tasks().helper('discovery_step').load(run)[2]
    assert state['next_action_mode']=='discover' and state['pending_frame']==str(frame if supplement else out/'current.png')
    assert json.loads((out/'result.json').read_text())['status']=='ready_next_round'
    assert not (run/'execution_pending.json').exists()


def test_only_explicitly_interactive_regions_are_reused():
    m=tasks().helper('update_visibility')
    changes=[{'region':'visible','state':'retained_interactive'}, {'region':'hidden','state':'not_visible'}, {'region':'background','state':'visible_background_blocked'}]
    assert m.regions([],changes,'none')==['visible']
    assert m.regions([],changes,'external_app')==[]


def test_action_context_discloses_task_facts_not_all_visible_region_facts():
    m=tasks().helper('task_action_context')
    fact={'name':'已见选项','description':'首屏列表','domain':{'type':'enum','values':['Midway','Hawaii']},'conditions':['开关开启'],'source':{'source_call':'before'}}
    task={'reason':'调查参数','status':'pending','findings':{'范围':fact}}
    records={'owner':{'name':'设置','actions':{},'tasks':{'参数':task}},
             'visible':{'name':'选择器','tasks':{'选项':{'findings':{'范围':dict(fact,description='后续列表',domain={'type':'enum','values':['Tokyo']})}}}},
             'other':{'name':'无关区块','tasks':{'无关':{'findings':{'范围':dict(fact,description='不应披露')}}}}}
    text,evidence=m.build(records,{'interactive_regions':['visible']},'owner','参数',task)
    assert all(value in text for value in ['Midway','Hawaii','开关开启'])
    assert '不应披露' not in text and 'Tokyo' not in text and '不代表完整范围' in text
    assert len(evidence['known_findings'])==1
