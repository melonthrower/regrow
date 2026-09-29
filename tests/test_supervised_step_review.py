"""Supervision enters the ordinary round; review waiting is never code failure."""
import json
from pathlib import Path
import pytest
from tests.test_recovery_discovery import ROOT,mod
from tests.test_update_semantic_review import fixture,verdict

@pytest.fixture(autouse=True)
def modules(monkeypatch):monkeypatch.syspath_prepend(str(ROOT))

def test_normal_round_waits_then_resumes_without_dispatch(tmp_path,monkeypatch):
    import run_task_step as step
    job=fixture(tmp_path);job.update(status='accept',seen=[],repairs=0,observations=0,supplements=[])
    step.write_json(tmp_path/job['path'],job);step.write_json(tmp_path/'pending_step.json',{'episode':job['path']})
    step.write_json(tmp_path/'run_manifest.json',{'device':'fake','app':'Clock'})
    step.write_json(tmp_path/'execution_pending.json',{'attempt':'a1'})
    attempt=tmp_path/'action_attempts/a1';attempt.mkdir(parents=True)
    (attempt/'receipt.json').write_text('{"exit_code":0}')
    class Transport:
        def save(self):step.write_json(self.ledger,self.account)
        def screenshot(self,path):Path(path).write_bytes(b'fresh frame')
        def call(self,q):pytest.fail('resuming a reviewed update must not call a model')
    monkeypatch.setattr(step,'RecoveryRun',Transport)
    monkeypatch.setattr(step,'foreground_window',lambda _:None)
    monkeypatch.setattr(step,'execute_action',lambda *a:pytest.fail('must not replay GUI'))
    original=step.step_repair.Runner;published=[]
    def runner(*args,**kwargs):
        instance=original(*args,**kwargs)
        def accept(*args):published.append(True);return {'snapshot':'approved'}
        monkeypatch.setattr(instance.adapters,'accept',accept)
        return instance
    monkeypatch.setattr(step.step_repair,'Runner',runner)
    before=(tmp_path/'knowledge_current.json').read_bytes()
    step.run_step(ROOT,tmp_path,tmp_path/'round1',review_update=lambda e:None)
    assert json.loads((tmp_path/'round1/result.json').read_text())['status']=='review_pending'
    assert not published and (tmp_path/'knowledge_current.json').read_bytes()==before
    assert (tmp_path/'execution_pending.json').exists()
    step.run_step(ROOT,tmp_path,tmp_path/'round2',review_update=lambda e:verdict(True))
    result=json.loads((tmp_path/'round2/result.json').read_text())
    assert result['status']=='updated' and result['gui_actions']==0 and len(published)==1
    assert not (tmp_path/'execution_pending.json').exists() and not (tmp_path/'pending_step.json').exists()
    assert json.loads((attempt/'receipt.json').read_text())=={'exit_code':0}
    assert (attempt/'commit.json').exists()

@pytest.mark.parametrize('mode',['auto','step'])
def test_session_stops_as_review_pending_and_keeps_costs(tmp_path,mode):
    session=mod('run_progress_session');calls=[]
    def step(root,run,out):
        out.mkdir();calls.append(out)
        (out/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':1}))
        (out/'result.json').write_text(json.dumps({'status':'review_pending'}))
    result=session.run_session(ROOT,tmp_path,tmp_path/'session',mode,step)
    assert result['status']=='review_pending' and len(calls)==1
    assert result['http_started']==result['gui_started']==1

def test_supervisor_wait_does_not_start_code_repair(tmp_path,monkeypatch):
    from tests.test_debug_loop import seed
    m=mod('debug_loop');run,_,_=seed(tmp_path)
    sup=m.Supervisor(tmp_path/'supervisor',[],ROOT)
    app={'key':'clock','run':str(run),'source':str(ROOT),'failures':{},'status':'queued'}
    issue=m.classify({}, {'status':'review_pending','reason':'review not supplied'},None)
    assert issue['kind']=='review_pending'
    monkeypatch.setattr(sup,'run_round',lambda *args:issue)
    monkeypatch.setattr(sup,'evidence',lambda *args:pytest.fail('not a code defect'))
    sup.tick(app,repair=lambda *args:pytest.fail('no automatic repair'))
    assert app['status']=='awaiting_review' and app['failures']=={}
