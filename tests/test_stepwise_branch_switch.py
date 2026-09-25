import json
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_resume_route import ROOT
from tests.test_stepwise_region_tasks import tasks


def fixture(tmp_path):
    run,q,d=setup(tmp_path)
    def add(records,state,*args):
        from copy import deepcopy
        records['r2']=deepcopy(records['r1']);records['r2']['name']='Other';records['r2']['tasks']={};records['r2'].pop('task_inventory',None)
    d.publish(run,'other-region',add)
    job={'path':'repair_episodes/service/episode.json','stage':'update','request':q,'attempt':'a1','status':'initial','history':[]}
    p=run/job['path'];p.parent.mkdir(parents=True);p.write_text(json.dumps(job))
    (run/'pending_step.json').write_text(json.dumps({'episode':job['path']}))
    (run/'execution_pending.json').write_text(json.dumps({'attempt':'a1'}))
    folder=run/'action_attempts/a1';folder.mkdir(parents=True,exist_ok=True);(folder/'receipt.json').write_text('{"exit_code":0}')
    frame=run/'fresh.png';frame.write_bytes(b'preserved-frame')
    error=run/'calls/0675/http_error.json';error.parent.mkdir(parents=True,exist_ok=True);error.write_text('{"status":402}')
    return run,job,d,frame


def test_switch_preserves_unsettled_result_and_requires_discovery(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    q=m.request(ROOT,run,job,frame,{'status':402},'0675')
    assert 'Other' in q['response_schema']['properties']['next_region']['enum']
    before=d.load(run)[1]['r1']['controls']
    m.commit(run,job,q,{'decision':'switch','next_region':'Other','reason':'暂挂当前分支'},'0676')
    _,records,state=d.load(run)
    assert state['working_region']=='r2' and state['next_action_mode']=='discover'
    assert state['observation'] is None and state['interactive_regions']==[]
    assert records['r1']['controls']==before
    assert records['r1']['tasks']['Policy']['status']=='blocked'
    assert not (run/'pending_step.json').exists() and not (run/'execution_pending.json').exists()
    assert not (run/'action_attempts/a1/commit.json').exists()
    assert (run/job['path']).exists()
    assert state['suspended_updates'][-1]['attempt']=='a1'


def test_stop_and_unknown_target_do_not_mutate(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch');q=m.request(ROOT,run,job,frame,{'status':402},'0675')
    before=(run/'knowledge_current.json').read_bytes()
    assert m.commit(run,job,q,{'decision':'stop','next_region':None,'reason':'没有独立分支'},'0676') is None
    with pytest.raises(Exception):m.commit(run,job,q,{'decision':'switch','next_region':'invented','reason':'x'},'0677')
    assert before==(run/'knowledge_current.json').read_bytes()
    assert (run/'execution_pending.json').exists()


def test_unconfirmed_delivery_is_not_suspended(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    (run/'action_attempts/a1/receipt.json').write_text('{"exit_code":null}')
    q=m.request(ROOT,run,job,frame,{'status':402},'0675')
    with pytest.raises(ValueError,match='delivery'):m.commit(run,job,q,{'decision':'switch','next_region':'Other','reason':'x'},'0676')
    assert (run/'execution_pending.json').exists()


def test_service_error_calls_branch_correction_once(tmp_path,monkeypatch):
    import subprocess
    from tests.test_stepwise_task_correction import repair
    run,job,d,frame=fixture(tmp_path);m=repair();count=[]
    (run/'run_manifest.json').write_text('{"last_call":"0675"}')
    folder=run/'calls/0675';folder.mkdir(parents=True,exist_ok=True);(folder/'http_error.json').write_text('{"status":402}')
    def call(q):
        count.append(q)
        if len(count)==1:raise subprocess.CalledProcessError(1,['call'])
        return '0676',{'decision':'switch','next_region':'Other','reason':'独立分支可继续'}
    def screenshot(path):path.write_bytes(frame.read_bytes())
    with pytest.raises(m.Paused) as error:m.Runner(ROOT,run,call,screenshot,lambda:4).perform('update')
    assert error.value.status=='task_deferred'
    assert len(count)==2 and count[1]['role']=='branch_correction'
    assert d.load(run)[2]['next_action_mode']=='discover'


def test_correction_service_failure_does_not_retry_original(tmp_path):
    import subprocess
    from tests.test_stepwise_task_correction import repair
    run,job,d,frame=fixture(tmp_path);m=repair()
    job['service_failure']={'call':'0675','error':{'status':402}}
    (run/job['path']).write_text(json.dumps(job));calls=[]
    def call(q):calls.append(q);raise subprocess.CalledProcessError(1,['call'])
    runner=m.Runner(ROOT,run,call,lambda p:p.write_bytes(frame.read_bytes()),lambda:4)
    with pytest.raises(subprocess.CalledProcessError):runner.perform('update')
    with pytest.raises(m.Paused):runner.perform('update')
    assert len(calls)==1 and calls[0]['role']=='branch_correction'
    assert (run/'execution_pending.json').exists()


def test_known_destination_of_failed_entry_is_not_independent(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    def seed(records,state,*args):
        records['r1']['actions']['a-known']={'control':'c1','delivery':'executed_receipt_zero','result':{'exception':'none'},'interactive_regions':['r2']}
    d.publish(run,'known-destination',seed)
    (run/'action_attempts/a1/binding.json').write_text(json.dumps({'region_ref':'r1','control_ref':'c1','task_region':'r1','task_name':'Policy'}))
    q=m.request(ROOT,run,job,frame,{'status':402},'0675')
    assert 'Other' not in q['response_schema']['properties']['next_region']['enum']


def test_missing_service_evidence_cannot_open_switch(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    with pytest.raises(ValueError,match='requires recorded'):
        m.request(ROOT,run,job,frame,{'message':'定位困难'},None)
    assert (run/'execution_pending.json').exists()


def test_loop_detector_calls_correction_and_reenters_discovery(tmp_path):
    from tests.test_stepwise_task_correction import repair
    run,job,d,frame=fixture(tmp_path)
    (run/'pending_step.json').unlink();(run/'execution_pending.json').unlink()
    loop=tasks().helper('exploration_loop');m=repair();calls=[]
    for i in range(3):evidence=loop.observe(run,str(i))
    def call(q):
        calls.append(q)
        assert q['switch_context']['trigger']['kind']=='exploration_loop'
        return 'loop1',{'decision':'switch','next_region':'Other','reason':'三轮无进展，暂挂并继续其他区块'}
    runner=m.Runner(ROOT,run,call,lambda p:p.write_bytes(frame.read_bytes()),lambda:4)
    with pytest.raises(Exception) as error:loop.correct(runner,evidence)
    assert getattr(error.value,'status',None)=='task_deferred'
    assert len(calls)==1 and d.load(run)[2]['working_region']=='r2'
    assert d.load(run)[2]['next_action_mode']=='discover'


def test_loop_disclosure_does_not_repeat_one_action_as_new_clicks():
    m=tasks().helper('branch_switch')
    row={'work':'r1','task':None,'position':['r1'],'mode':'explore','progress':'same',
         'recent_action_ref':['r1','a1'],'recent_action':{'动作':'click','目标':'Cancel'}}
    cause={'kind':'exploration_loop','repetitions':3,'cycle_length':1,'history':[dict(row) for _ in range(3)]}
    shown=m.readable_trigger(cause,{'r1':{'name':'Settings'}})
    assert '本轮没有新增' in shown['近期经过'][1]['最近动作']
    assert '本轮没有新增' in shown['近期经过'][2]['最近动作']
    cause['history'][2]['recent_action_ref']=['r1','a2']
    shown=m.readable_trigger(cause,{'r1':{'name':'Settings'}})
    assert shown['近期经过'][2]['最近动作']['目标']=='Cancel'


def test_legacy_loop_disclosure_does_not_infer_action_count():
    m=tasks().helper('branch_switch')
    row={'work':'r1','task':None,'position':['r1'],'mode':'explore','progress':'same',
         'recent_action':{'动作':'click','目标':'Cancel'}}
    shown=m.readable_trigger({'kind':'exploration_loop','repetitions':3,'cycle_length':1,
        'history':[dict(row) for _ in range(3)]},{'r1':{'name':'Settings'}})
    assert all('无法确认' in r['动作进展'] for r in shown['近期经过'])


def test_same_action_result_amendment_is_visible_without_new_execution():
    from copy import deepcopy
    m=tasks().helper('branch_switch')
    row={'work':'r1','task':None,'position':['r1'],'mode':'explore','progress':'same',
         'recent_action_ref':['r1','a1'],'recent_action':{'动作':'click','目标':'Cancel','结果':'暂未确认'}}
    history=[deepcopy(row) for _ in range(3)]
    history[1]['recent_action']['结果']='已确认关闭对话框'
    history[2]['recent_action']['结果']='已确认关闭对话框'
    shown=m.readable_trigger({'kind':'exploration_loop','repetitions':3,'cycle_length':1,'history':history},{'r1':{'name':'Settings'}})
    assert shown['近期经过'][1]['最近动作']['结果']=='已确认关闭对话框'
    assert '不是新执行' in shown['近期经过'][1]['动作进展']
    assert '本轮没有新增' in shown['近期经过'][2]['最近动作']


def test_zero_action_stagnation_can_resume_normal_planning_once(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch');loop=tasks().helper('exploration_loop')
    (run/'pending_step.json').unlink();(run/'execution_pending.json').unlink()
    for i in range(3):evidence=loop.observe(run,str(i))
    job.update(stage='action',attempt=None,switch_trigger=evidence)
    (run/'pending_step.json').write_text(json.dumps({'episode':job['path']}))
    q=m.request(ROOT,run,job,frame,None,None)
    assert 'resume' in q['response_schema']['properties']['decision']['enum']
    before=d.load(run)[1]['r1']['tasks']
    result=m.commit(run,job,q,{'decision':'resume','next_region':None,'reason':'没有重复点击；可用组合键显露入口'},'resume1')
    assert result and not (run/'pending_step.json').exists()
    _,records,state=d.load(run)
    assert records['r1']['tasks']==before and state['next_action_mode']=='discover'
    assert state['resolved_loop']['status']=='resolved'


def test_old_branch_attempt_can_be_reviewed_once_after_policy_change(tmp_path,monkeypatch):
    from types import SimpleNamespace
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    job.update(branch_switch_attempted=True,service_failure={'call':'0675','error':{'status':402}})
    seen=[]
    runner=SimpleNamespace(run=run,root=ROOT,available=lambda:4,save=lambda j:None,screenshot=lambda p:p.write_bytes(frame.read_bytes()),call=lambda q:seen.append(q) or ('new-review',{'decision':'stop','next_region':None,'reason':'仍无独立目标'}))
    assert m.correct(runner,job) is None
    assert len(seen)==1
    assert m.correct(runner,job) is None and len(seen)==1


def test_branch_discloses_earlier_task_action_not_just_last_wait(tmp_path):
    run,job,d,frame=fixture(tmp_path);m=tasks().helper('branch_switch')
    def seed(records,state,*args):
        task=records['r1']['tasks']['Policy']
        task['attempts']=['clicked','waited']
        records['r1']['actions']['clicked']={'control':'c1','operation':'click','delivery':'executed_receipt_zero','result':{'description':'selection showed a loading indicator'}}
        records['r1']['actions']['waited']={'control':None,'operation':'wait','delivery':'executed_receipt_zero','result':{'description':'later observation did not establish a saved location'}}
    d.publish(run,'earlier-action',seed)
    (run/'action_attempts/a1/binding.json').write_text(json.dumps({'region_ref':'r1','task_region':'r1','task_name':'Policy'}))
    before=(run/'knowledge_current.json').read_bytes()
    q=m.request(ROOT,run,job,frame,{'status':402},'0675')
    assert 'selection showed a loading indicator' in q['user_prompt']
    assert 'later observation did not establish a saved location' in q['user_prompt']
    assert (run/'knowledge_current.json').read_bytes()==before
    assert q['response_schema']['properties']['decision']['enum']==['switch','stop']
