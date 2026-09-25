from tests.test_stepwise_resume_route import ROOT


def test_window_evidence_exposes_owner_without_equating_all_system_ui_to_external(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as m
    e=m.window_evidence('ca7dcdd u0 com.example.settings/.Main','com.example.clock')
    assert e['前台应用']=='com.example.settings' and e['与目标应用一致'] is False
    assert 'exception' not in e
    assert m.window_evidence('x u0 com.example.clock/.Main','com.example.clock')['与目标应用一致'] is True
    assert m.window_evidence(None,'com.example.clock')['与目标应用一致'] is None
    assert m.window_evidence('x u0 InputMethod','com.example.clock')['前台应用'] is None
