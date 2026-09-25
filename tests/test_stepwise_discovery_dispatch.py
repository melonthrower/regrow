"""Discovery can change the pipeline destination before any action is assembled."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

@pytest.mark.parametrize('entry', ['initial', 'task_proposal'])
@pytest.mark.parametrize('mode', ['recover', 'review_result'])
def test_discovery_routes_before_action_context(tmp_path, monkeypatch, entry, mode):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location('dispatch_runner', ROOT / 'run_task_step.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    run = tmp_path / 'run'; run.mkdir()
    (run / 'run_manifest.json').write_text(json.dumps({'device':'fake','app':'test.app'}))
    (run / 'knowledge_current.json').write_text('{}')
    state = {'next_action_mode': 'discover' if entry == 'initial' else 'explore'}
    monkeypatch.setattr(m.RecoveryRun, 'screenshot', lambda self,p: p.write_bytes(b'frame'))
    monkeypatch.setattr(m.discovery_step, 'load', lambda run: (None, {}, state))
    def discover(*args, **kwargs): state['next_action_mode'] = mode
    monkeypatch.setattr(m.discovery_step, 'run_stage', discover)
    monkeypatch.setattr(m.step_repair, 'pending', lambda run: None)
    monkeypatch.setattr(m.exploration_loop, 'observe', lambda *args: None)
    def perform(*args): state['next_action_mode'] = 'discover'
    monkeypatch.setattr(m.step_repair, 'Runner', lambda *args: SimpleNamespace(perform=perform))
    def assemble(*args):
        assert state['next_action_mode'] == 'explore', 'ordinary context assembled after exceptional discovery'
        return {'stage':'task_proposal'}
    monkeypatch.setattr(m, 'assemble_current_context', assemble)
    routed = []
    def recover(*args, **kwargs):
        routed.append(state['next_action_mode'])
        return {'status':'paused_after_recovery_discovery','gui_actions':0}
    monkeypatch.setattr(m.recover_loop, 'run', recover)
    out = tmp_path / 'round'
    m._run_step(ROOT, run, out)
    assert routed == [mode]
    assert json.loads((out/'result.json').read_text())['status'] == 'paused_after_recovery_discovery'
    assert json.loads((out/'budget.json').read_text())['http_started'] == 0
