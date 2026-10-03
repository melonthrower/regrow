"""Legacy pending navigation is observed, never replayed."""
from pathlib import Path
import importlib.util
from types import SimpleNamespace
import json
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec=importlib.util.spec_from_file_location('visual_backtrack',ROOT/'visual_backtrack.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_real_visual_match_rejects_changed_surface(tmp_path,monkeypatch):
    import numpy as np
    from PIL import Image
    m=module(monkeypatch)
    pixels=np.random.default_rng(23).integers(0,256,(120,120,3),dtype=np.uint8)
    old=tmp_path/'old.png';new=tmp_path/'new.png'
    Image.fromarray(pixels).save(old);Image.fromarray(pixels).save(new)
    assert m.same_surface(old,new)
    pixels[20:100,20:100]=128;Image.fromarray(pixels).save(new)
    assert not m.same_surface(old,new)


def test_legacy_pending_marker_hands_off_without_any_gui(tmp_path, monkeypatch):
    m = module(monkeypatch)
    frame = tmp_path/'actual.png'; frame.write_bytes(b'actual capture')
    event = {'edge': {'attempt': 'old-submit'}, 'status': 'dispatching'}
    (tmp_path/'visual_navigation_pending.json').write_text(json.dumps(event))
    state = {}; records = {}; published = []
    def publish(run, tag, change):
        change(records, state)
        published.append(tag)
    monkeypatch.setattr(m.discovery, 'publish', publish)
    transport = SimpleNamespace(run=tmp_path)
    result = m.resume_pending(transport, frame)
    assert result['navigation'] == 'luna_handoff' and published
    assert state['next_action_mode'] == 'discover' and not state['interactive_regions']
    assert state['navigation_handoff']['status'] == 'dispatching'
    assert state['pending_frame'] == str(frame) and not records
    assert not (tmp_path/'visual_navigation_pending.json').exists()


def test_known_business_route_reaches_normal_selector_without_replay(tmp_path, monkeypatch):
    from tests.test_stepwise_task_correction import saved
    run, q, _ = saved(tmp_path)
    module(monkeypatch)
    import run_task_step as runner
    (run/'run_manifest.json').write_text(json.dumps({'device': 'fake', 'app': 'test.app'}))
    from PIL import Image
    frame = run/'selector-frame.png'; Image.new('RGB', (100, 160), 'white').save(frame)
    content = frame.read_bytes()
    class Transport:
        def save(self):self.ledger.write_text(json.dumps(self.account))
        def screenshot(self, path):path.write_bytes(content)
        def call(self, request):pytest.fail('model isolated at Runner boundary')
        def adb(self, args):return SimpleNamespace(returncode=0, stdout=b'')
        def send_command(self, *args):pytest.fail('no shortcut may send a GUI command')
    class Selected(Exception):pass
    seen = []
    original_runner = runner.step_repair.Runner
    def selector(stage, request):
        seen.append((stage, request))
        raise Selected()
    def repair(*args, **kwargs):
        instance = original_runner(*args, **kwargs)
        instance.perform = selector
        return instance
    q.update(stage='action_selection', action_ready=True, navigation_advice=True,
             navigation_path=[{'attempt': 'old-business-submit', 'operation': 'click'}])
    monkeypatch.setattr(runner, 'RecoveryRun', Transport)
    monkeypatch.setattr(runner, 'assemble_current_context', lambda *args: q.copy())
    monkeypatch.setattr(runner.step_repair, 'Runner', repair)
    monkeypatch.setattr(runner.exploration_loop, 'observe', lambda *args: None)
    with pytest.raises(Selected):runner._run_step(ROOT, run, tmp_path/'round')
    assert seen[0][0] == 'action' and seen[0][1]['role'] == 'action_selection'
    assert len(seen[0][1]['screenshots']) == 1
    assert not (run/'navigation_replays').exists() and not (run/'execution_pending.json').exists()
