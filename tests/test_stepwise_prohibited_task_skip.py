from copy import deepcopy
import pytest
from tests.test_stepwise_task_correction import saved
from tests.test_stepwise_region_tasks import tasks


def setup(tmp_path):
    run,q,_=saved(tmp_path);scope=tasks().helper('traversal_scope');d=scope.helper('discovery_step')
    def seed(records,state,*args):
        records['r1']['tasks']={
            'change':{'control':'c1','handling':'explore','status':'pending','attempts':['old'],'reason':'verify setting'},
            'inspect':{'control':'c2','handling':'explore','status':'pending','attempts':[],'reason':'read options'}}
        state.update(next_action_mode='explore',working_region='r1',active_task={'region':'r1','name':'change'})
    d.publish(run,'seed',seed)
    q={'source':{'task_region':'r1','task_name':'change'}}
    return run,q,scope,d


def test_prohibited_task_is_deferred_and_another_remains_schedulable(tmp_path):
    run,q,scope,d=setup(tmp_path)
    before=deepcopy(d.load(run)[1]['r1']['actions']);obs=deepcopy(d.load(run)[2]['observation'])
    assert scope.skip_prohibited(run,q,{'action':'none','skip_task':True,'reason':'任务要求修改熄屏配置，违反当前只读限制'},'call')
    _,records,state=d.load(run);t=records['r1']['tasks']['change']
    assert t['status']=='blocked' and t['handling']=='defer' and t['attempts']==['old']
    assert t['blocker']['condition']=='review_required'
    assert t['deferral']['reason']=='任务要求修改熄屏配置，违反当前只读限制'
    assert t['deferral']['source_call']=='call'
    assert not tasks().coverage(records['r1'])['complete']
    assert t['scope_history'][0]['status']=='pending'
    assert records['r1']['actions']==before and state['observation']==obs
    assert 'active_task' not in state and state['next_action_mode']=='explore'
    assert [n for n,_ in tasks().helper('task_deferral').pending_tasks(records['r1'])]==['inspect']


def test_ordinary_none_keeps_task_and_pending_execution_cannot_be_skipped(tmp_path):
    run,q,scope,d=setup(tmp_path)
    assert not scope.skip_prohibited(run,q,{'action':'none','reason':'need position'},'call')
    (run/'execution_pending.json').write_text('{}')
    with pytest.raises(ValueError):scope.skip_prohibited(run,q,{'action':'none','skip_task':True,'reason':'forbidden'},'call')
    assert d.load(run)[1]['r1']['tasks']['change']['status']=='pending'


def test_skip_marker_never_accompanies_gui_action(tmp_path):
    run,q,scope,d=setup(tmp_path)
    with pytest.raises(ValueError):scope.skip_prohibited(run,q,{'action':'click','skip_task':True,'reason':'forbidden'},'call')


def test_runner_continues_after_skip_without_rediscovery_or_gui(tmp_path,monkeypatch):
    import sys,json
    from types import SimpleNamespace
    from tests.test_stepwise_resume_route import ROOT
    monkeypatch.syspath_prepend(str(ROOT))
    import run_task_step as runner
    run=tmp_path/'run';run.mkdir()
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'test.app'}))
    (run/'knowledge_current.json').write_text('{}')
    monkeypatch.setattr(runner,'foreground_window',lambda *a:None)
    monkeypatch.setattr(runner.RecoveryRun,'screenshot',lambda self,p:p.write_bytes(b'frame'))
    monkeypatch.setattr(runner.discovery_step,'load',lambda r:(None,{}, {'next_action_mode':'explore'}))
    monkeypatch.setattr(runner.exploration_loop,'observe',lambda *a:None)
    monkeypatch.setattr(runner.step_repair,'pending',lambda r:None)
    q={'stage':'action_selection','action_ready':True,'source':{'task_name':'change'}}
    proposal={'action':'none','skip_task':True,'reason':'explicit environment restriction'}
    result={'stage':'action','result':{'request':q,'call':'call','proposal':proposal,'binding':{'status':'no_action'}}}
    monkeypatch.setattr(runner.step_repair,'Runner',lambda *a:SimpleNamespace(perform=lambda *a:result))
    monkeypatch.setattr(runner,'assemble_current_context',lambda *a:q)
    monkeypatch.setattr(runner.visual_backtrack,'try_step',lambda *a:None)
    skipped=[]
    monkeypatch.setattr(runner.traversal_scope,'skip_prohibited',lambda *a:skipped.append(a) or True)
    runner._run_step(ROOT,run,tmp_path/'round')
    report=json.loads((tmp_path/'round/result.json').read_text())
    assert skipped and report['status']=='ready_next_round' and report['gui_actions']==0
    assert report['skipped_task']=='change'


def test_action_schema_is_accepted_by_strict_model_output_contract():
    m=tasks().helper('action_commands');schema=m.schema()
    assert set(schema['properties'])==set(schema['required'])


def test_forbidden_prerequisite_stays_blocked_after_reobservation(tmp_path):
    run,q,scope,d=setup(tmp_path)
    reason='灰色入口可能依赖总开关；本轮禁止修改该连接条件，尚未验证依赖关系'
    proposal={'action':'none','skip_task':True,'reason':reason}
    assert scope.skip_prohibited(run,q,proposal,'call')
    _,records,state=d.load(run)
    records['r1']['controls']['c1']['observations']=[{'image':'new.png','evidence':{'source_call':'next'}}]
    tasks().helper('task_deferral').resume_localized(records,['r1'],'next',{'exception':'none'})
    assert records['r1']['tasks']['change']['status']=='blocked'
    assert records['r1']['tasks']['change']['deferral']['reason']==reason
    assert scope.skip_prohibited(run,q,proposal,'call')
    assert len(d.load(run)[1]['r1']['tasks']['change']['scope_history'])==1


def test_prerequisite_reason_reaches_task_review(tmp_path):
    import json
    from tests.test_stepwise_resume_route import fixture,ROOT
    _,records,state=fixture();region=records['menu']
    region['tasks']={'inspect':{'control':'open','handling':'defer','status':'blocked','action':'click','task_type':'single_action','reason':'inspect options',
        'deferral':{'reason':'Requires forbidden connection change','retry_when':'Explicit review required'}}}
    q=tasks().plan_request(ROOT,records,state,'menu')
    item=json.loads(q['user_prompt'])['已有任务'][0]
    assert item['暂挂原因']=='Requires forbidden connection change'
    assert item['恢复条件']=='Explicit review required'
