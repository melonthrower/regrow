"""Executor owns the ordered dispatch/evidence boundary; these are offline adapters."""
import json
from types import SimpleNamespace
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_resume_route import ROOT


def executor_case(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import action_executor as module
    run, q, _ = setup(tmp_path)
    out=tmp_path/'round';out.mkdir()
    frame=tmp_path/'frame.png';frame.write_bytes(b'offline frame')
    q['screenshots']=[str(frame)]
    trace=[]
    class Transport:
        package='app'
        platform='android'
        def screenshot(self, path):
            trace.append(path.name);path.write_bytes(frame.read_bytes())
        def foreground_window(self):return 'same-window'
        def save(self):pass
    transport=Transport()
    transport.run=run
    transport.account={'gui_started':0,'max_gui_commands':1,'http_started':1,'max_http':3}
    manifest=json.loads((run/'run_manifest.json').read_text()) if (run/'run_manifest.json').exists() else {}
    (run/'run_manifest.json').write_text(json.dumps(manifest))
    (run/'action_attempts').mkdir(exist_ok=True)
    def deliver(t,p,path,**kwargs):
        assert (run/'execution_pending.json').exists()
        trace.append('dispatch')
        t.account['gui_started']+=1
        return {'exit_code':0,'executed_steps':[p]}
    monkeypatch.setattr(module,'execute_action',deliver)
    monkeypatch.setattr(module.StepwiseFlow.execute.__globals__['time'],'sleep',lambda _:None)
    accepted={'result':{'request':q,'call':'test-call',
        'proposal':{'action':'back','target':'back','x':None,'y':None,'reason':'return'},
        'binding':{'status':'matched','region_ref':'r1','working_region':'r1','control_ref':None}}}
    executor=module.ActionExecutor(transport,out,SimpleNamespace(reject_action=lambda *a,**k:pytest.fail('unchanged frame')))
    return module,executor,accepted,run,trace


def test_executor_records_receipt_before_post_action_observation(tmp_path,monkeypatch):
    _,executor,accepted,run,trace=executor_case(tmp_path,monkeypatch)
    folder=executor.execute(accepted,'same-window',[])
    assert trace==['pre_dispatch.png','dispatch','after.png']
    assert json.loads((folder/'receipt.json').read_text())['exit_code']==0
    assert (folder/'after_window.json').exists()
    assert (run/'execution_pending.json').exists()
    assert not (folder/'commit.json').exists()


def test_executor_never_replays_an_existing_pending_delivery(tmp_path,monkeypatch):
    module,executor,accepted,run,trace=executor_case(tmp_path,monkeypatch)
    (run/'execution_pending.json').write_text('{"attempt":"old"}')
    with pytest.raises(module.step_repair.Paused,match='已投递'):
        executor.execute(accepted,'same-window',[])
    assert trace==[]
    assert json.loads((run/'execution_pending.json').read_text())=={'attempt':'old'}


def test_executor_requires_remaining_result_call_capacity(tmp_path,monkeypatch):
    module,executor,accepted,run,trace=executor_case(tmp_path,monkeypatch)
    executor.transport.account['http_started']=3
    with pytest.raises(module.step_repair.Paused):
        executor.execute(accepted,'same-window',[])
    assert trace==[]
    assert not (run/'execution_pending.json').exists()
