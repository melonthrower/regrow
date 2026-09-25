import json
from types import SimpleNamespace
from tests.test_recovery_discovery import mod


def test_completed_wait_has_execution_evidence_without_gui_command(tmp_path,monkeypatch):
    m=mod('action_commands');slept=[]
    monkeypatch.setattr(m.time,'sleep',lambda seconds:slept.append(seconds))
    transport=SimpleNamespace(account={'gui_started':0,'max_gui_commands':1})
    receipt=m.execute(transport,{'action':'wait'},tmp_path)
    assert slept==[2]
    assert receipt['executed_steps']==[{'action':'wait','seconds':2}]
    assert receipt['semantic_result']=='unverified'
    assert transport.account['gui_started']==0
    assert json.loads((tmp_path/'executed_steps.json').read_text())==receipt['executed_steps']


def test_interrupted_wait_does_not_claim_execution(tmp_path,monkeypatch):
    m=mod('action_commands')
    def interrupted(seconds):raise InterruptedError('interrupted')
    monkeypatch.setattr(m.time,'sleep',interrupted)
    transport=SimpleNamespace(account={'gui_started':0,'max_gui_commands':1})
    import pytest
    with pytest.raises(InterruptedError):m.execute(transport,{'action':'wait'},tmp_path)
    assert not (tmp_path/'receipt.json').exists()
