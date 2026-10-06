import json
from pathlib import Path
from tests.test_recovery_discovery import ROOT
from tests.test_recovery_discovery import mod
import pytest


def test_session_passes_remaining_allowance_and_uses_tail(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_progress_session as m
    (tmp_path/'run_manifest.json').write_text(json.dumps({'session_limits':{'max_http':4,'max_gui_commands':3}}))
    allowances=[]
    def step(root,run,folder,*,limits=None):
        allowances.append(limits);folder.mkdir()
        (folder/'budget.json').write_text(json.dumps({'http_started':2,'gui_started':1}))
        (folder/'result.json').write_text(json.dumps({'status':'updated'}))
    result=m.run_session(ROOT,tmp_path,tmp_path/'session','auto',step)
    assert result['status']=='budget_limit' and result['http_started']==4 and result['gui_started']==2
    assert allowances==[{'max_http':4,'max_gui_commands':3},{'max_http':2,'max_gui_commands':2}]


def test_budget_stop_preserves_pending_receipt_and_accounting(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as m
    import model_transport
    def exhausted(root,run,out,**kwargs):
        out.mkdir();(out/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':1}))
        (run/'execution_pending.json').write_text('real receipt')
        raise model_transport.BudgetExhausted('HTTP')
    monkeypatch.setattr(m,'_run_step',exhausted)
    out=tmp_path/'round';m.run_step(ROOT,tmp_path,out,limits={'max_http':1,'max_gui_commands':1})
    assert json.loads((out/'result.json').read_text())['status']=='budget_limit'
    assert (tmp_path/'execution_pending.json').read_text()=='real receipt'
    assert json.loads((out/'budget.json').read_text())['gui_started']==1


def test_insufficient_gui_budget_never_starts_partial_input(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from types import SimpleNamespace
    from model_transport import BudgetExhausted
    transport=SimpleNamespace(account={'max_gui_commands':2,'gui_started':0})
    proposal={'action':'input_text','target':'Name','x':4,'y':5,'text':'Example',
              'end_x':None,'end_y':None,'reason':'observe explicit input','skip_task':False}
    with pytest.raises(BudgetExhausted):mod('action_commands').execute(transport,proposal,tmp_path)
    assert transport.account['gui_started']==0
    assert not (tmp_path/'dispatch.json').exists()


def test_idle_finalization_uses_http_tail_without_extra_gui(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_progress_session as m
    (tmp_path/'run_manifest.json').write_text(json.dumps({'session_limits':{'max_http':3,'max_gui_commands':1}}))
    def step(root,run,folder,*,limits=None):
        folder.mkdir();(folder/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':0}))
        (folder/'result.json').write_text(json.dumps({'status':'scope_idle'}))
    def finish(root,run,folder,*,max_http):
        assert max_http==2;folder.mkdir()
        (folder/'budget.json').write_text(json.dumps({'http_started':2,'gui_started':0}))
        return {'status':'knowledge_complete'}
    monkeypatch.setattr(m,'finalize_knowledge',finish)
    result=m.run_session(ROOT,tmp_path,tmp_path/'session','auto',step)
    assert result['http_started']==3 and result['gui_started']==0
    assert result['knowledge_status']=='knowledge_complete'


@pytest.mark.parametrize('limit,used,expected',[(1,0,'budget_limit'),(6,5,'ready_next_round'),(6,0,None)])
def test_action_capacity_distinguishes_local_progress_from_empty_tail(monkeypatch,limit,used,expected):
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step
    assert run_task_step.action_capacity_status({'max_http':limit,'http_started':used})==expected
