from tests.test_debug_loop import ROOT
import debug_candidate as d
import pytest
from pathlib import Path


def test_repair_cannot_change_existing_tests_or_delete_code():
    with pytest.raises(ValueError):d.assert_scope({'tests/test_old.py':'a'},{'tests/test_old.py':'b'})
    with pytest.raises(ValueError):d.assert_scope({str(d.REL/'a.py'):'a'}, {})


def test_code_only_change_and_new_test_allowed():
    name=str(d.REL/'a.py')
    assert d.assert_scope({name:'a'},{name:'b','tests/test_debug_regression_a.py':'test'})


def test_rejected_reader_stops_before_luna(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();(source/'a.py').write_text('a')
    incident=tmp_path/'incident';incident.mkdir()
    def workspace(repo,source,dest):
        new=dest/d.REL;new.mkdir(parents=True);(new/'a.py').write_text('old');return new
    monkeypatch.setattr(d,'workspace',workspace)
    def fake_codex(cwd,out,prompt,schema,write_access=False,images=()):
        if out.name=='developer':
            (cwd/d.REL/'a.py').write_text('new')
            return {'summary':'fix','tests':['tests/test_debug_regression_a.py'],'replay_request':'replay/request.json'}
        if out.name=='reader':return {'reading':'behavior','issues':['wrong']}
        return {'accepted':False,'reason':'wrong behavior'}
    monkeypatch.setattr(d,'codex',fake_codex)
    def test(repo,source,tests,out):
        out.mkdir();(out/'output.log').write_text('1 failed' if out.name=='baseline_test' else '1 passed')
        return int(out.name=='baseline_test')
    monkeypatch.setattr(d,'pytest_run',test)
    monkeypatch.setattr(d,'luna',lambda *args:pytest.fail('rejected candidate cannot call Luna'))
    result=d.repair_candidate(source,incident)
    assert not result['accepted'] and 'reader rejected' in result['reason']


def test_agent_timeout_records_failure_and_stops_process_group(tmp_path,monkeypatch):
    import subprocess
    class Process:
        pid=12345
        returncode=-15
        def communicate(self,*args,**kwargs):raise subprocess.TimeoutExpired('codex',900)
        def wait(self,**kwargs):return -15
    stopped=[]
    monkeypatch.setattr(d.subprocess,'Popen',lambda *args,**kwargs:Process())
    monkeypatch.setattr(d.os,'killpg',lambda pid,sig:stopped.append(pid))
    with pytest.raises(RuntimeError):d.codex(tmp_path,tmp_path/'call','prompt',d.VERDICT)
    assert stopped==[12345]
    assert d.read(tmp_path/'call/receipt.json')['timed_out']


def test_transient_saved_frame_http_retries_exact_sender_and_charges_each():
    from types import SimpleNamespace
    states=iter([503,503,200]);charges=[];calls=[]
    def send():calls.append('same request');return SimpleNamespace(status_code=next(states))
    result=d.retry_http(send,charges.append,lambda seconds:None)
    assert result.status_code==200 and charges==[1,2,3] and len(calls)==3


def test_service_rejection_not_retried():
    from types import SimpleNamespace
    charges=[]
    assert d.retry_http(lambda:SimpleNamespace(status_code=402),charges.append).status_code==402
    assert charges==[1]


def test_blind_reader_does_not_receive_developer_notes():
    paths=[str(d.REL/'ownership_review.py'),'tests/test_debug_regression_x.py','replay/build.py','replay/request.json','replay/README.md','replay/implementation.diff']
    assert d.reader_paths(paths)==paths[:4]


def test_supervisor_self_edit_cannot_be_silently_promoted():
    from debug_candidate import assert_scope,REL
    import pytest
    name=str(REL/'debug_loop.py')
    with pytest.raises(ValueError,match='explicit restart'):
        assert_scope({name:'before'},{name:'after'})
