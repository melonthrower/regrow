"""Automatic input continuation uses recorded visual targets, never model guesses."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.test_stepwise_resume_route import ROOT

@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from regrow.runtime import action_commands as action_commands
    from regrow.runtime import input_target as input_target
    monkeypatch.setattr(action_commands.time, 'sleep', lambda _: None)
    return (action_commands, input_target)

def transport():
    sent = []
    t = SimpleNamespace(account={'gui_started': 0, 'max_gui_commands': 4}, save=lambda : None, screenshot=lambda p: p.write_bytes(b'frame'), adb=lambda args: sent.append(args) or SimpleNamespace(returncode=0, stdout=b'', stderr=b''))
    return (t, sent)

def test_local_target_continues_without_whole_frame_match(modules, tmp_path, monkeypatch):
    (a, m) = modules
    (t, sent) = transport()
    monkeypatch.setattr(m, 'resolve', lambda *args: {'status': 'same_target', 'target': {'region': 'r', 'control': 'c'}})
    result = a.execute(t, {'action': 'input_text', 'x': 20, 'y': 30, 'text': 'wifi'}, tmp_path, input_context={'source': {}})
    assert len(sent) == 3 and result['text_delivered']
    assert [s['action'] for s in result['executed_steps']] == ['click', 'select_all', 'input_text']

def test_historical_input_target_never_generates_another_click(modules, tmp_path, monkeypatch):
    (a, m) = modules
    (t, sent) = transport()
    monkeypatch.setattr(m, 'resolve', lambda *args: {'status': 'known_target', 'target': {'region': 'r2', 'control': 'c2'}, 'x': 80, 'y': 90})
    result = a.execute(t, {'action': 'input_text', 'x': 20, 'y': 30, 'text': 'wifi'}, tmp_path, input_context={'source': {}})
    assert len(sent) == 1 and (not result['text_delivered'])
    assert not (tmp_path / 'after_retarget.png').exists()

def test_unknown_or_failed_retarget_never_sends_text(modules, tmp_path, monkeypatch):
    (a, m) = modules
    (t, sent) = transport()
    monkeypatch.setattr(m, 'resolve', lambda *args: {'status': 'unresolved', 'reason': 'unknown surface'})
    result = a.execute(t, {'action': 'input_text', 'x': 20, 'y': 30, 'text': 'wifi'}, tmp_path, input_context={'source': {}})
    assert len(sent) == 1 and (not result['text_delivered'])
    assert result['executed_steps'][0]['action'] == 'click'

def test_partial_input_history_is_a_click_not_a_successful_input(tmp_path):
    from tests.test_region_registration import module
    folder = tmp_path / 'action_attempts/a1'
    folder.mkdir(parents=True)
    (folder / 'proposal.json').write_text(json.dumps({'action': 'input_text', 'reason': 'test input'}))
    (folder / 'receipt.json').write_text(json.dumps({'exit_code': 0, 'text_delivered': False, 'executed_steps': [{'action': 'click', 'x': 1, 'y': 2}]}))
    records = {'r': {'actions': {'a1': {}}}}
    module().attach_execution(records, tmp_path)
    a = records['r']['actions']['a1']
    assert a['operation'] == 'click' and a['intended_operation'] == 'input_text' and (not a['text_delivered'])

def test_ambiguous_known_inputs_are_not_automatically_chosen(modules, monkeypatch):
    (_, m) = modules
    monkeypatch.setattr(m, 'locate', lambda target, *args: None if target['control'] == 'source' else {'x': 1, 'y': 2})
    candidates = [{'region': 'r', 'control': c, 'frame': 'old', 'route_attempt': 'a'} for c in ('one', 'two')]
    assert m.resolve({'source': {'control': 'source'}, 'targets': candidates}, 'before', 'after')['status'] == 'unresolved'

def test_lost_target_after_automatic_focus_does_not_type(modules, tmp_path, monkeypatch):
    (a, m) = modules
    (t, sent) = transport()
    replies = iter([{'status': 'known_target', 'target': {'region': 'r', 'control': 'c'}, 'x': 10, 'y': 20, 'route_attempt': 'old'}, {'status': 'unresolved'}])
    monkeypatch.setattr(m, 'resolve', lambda *args: next(replies))
    result = a.execute(t, {'action': 'input_text', 'x': 1, 'y': 2, 'text': 'wifi'}, tmp_path, input_context={'source': {}, 'targets': [{'region': 'r', 'control': 'c'}]})
    assert len(sent) == 1 and (not result['text_delivered'])

def test_auto_retarget_obeys_remaining_command_budget(modules, tmp_path, monkeypatch):
    (a, m) = modules
    (t, sent) = transport()
    t.account['max_gui_commands'] = 3
    monkeypatch.setattr(m, 'resolve', lambda *args: {'status': 'known_target', 'target': {'region': 'r', 'control': 'c'}, 'x': 10, 'y': 20, 'route_attempt': 'old'})
    result = a.execute(t, {'action': 'input_text', 'x': 1, 'y': 2, 'text': 'wifi'}, tmp_path, input_context={'source': {}})
    assert len(sent) == 1 and (not result['text_delivered'])

def test_sparse_recognition_keeps_older_identity_image_for_focus_check(modules, tmp_path):
    (_, m) = modules
    obs = {'image': 'crop.png', 'image_quality': 'clear', 'evidence': {'observation': 'old'}}
    records = {'source': {'name': 'source', 'controls': {'s': {'name': 'field', 'observations': [obs, {'image': None, 'evidence': {'observation': 'now'}}]}}}}
    binding = {'region_ref': 'source', 'control_ref': 's', 'observation_ref': 'now'}
    q = {'image_refs': ['current.png']}
    result = m.context(tmp_path, records, binding, q)
    assert result['source']['image'] == str(tmp_path / 'regions/source/crop.png')
    assert 'targets' not in result
    records['source']['controls']['s']['observations'] = [{'image': None}]
    assert m.context(tmp_path, records, binding, q) is None

def test_multiple_focus_clicks_are_not_a_single_replay_edge():
    from tests.test_stepwise_resume_route import fixture
    (m, records, state) = fixture()
    records['main']['actions']['a3']['executed_steps'] = [{'action': 'click'}, {'action': 'click'}]
    path = m.shortest_known_path(records, state, 'menu')
    assert [e['attempt'] for e in path] == ['a1', 'a2']

@pytest.mark.parametrize('border_width,expected_match', [(4, True), (8, True)])
def test_focus_border_change_uses_current_target_appearance(modules, tmp_path, border_width, expected_match):
    import numpy as np
    from PIL import Image, ImageDraw
    (_, m) = modules
    scene = Image.new('RGB', (320, 240), '#202830')
    draw = ImageDraw.Draw(scene)
    draw.text((15, 15), 'Edit value', fill='white')
    draw.text((20, 205), 'Cancel                  OK', fill='white')
    box = (100, 75, 220, 175)
    draw.rectangle(box, fill='#404850', outline='white', width=2)
    pattern = Image.fromarray(np.random.default_rng(21).integers(100, 255, (40, 50, 3), dtype=np.uint8))
    scene.paste(pattern, (135, 105))
    scene.save(tmp_path / 'before.png')
    scene.save(tmp_path / 'region.png')
    scene.crop(box).save(tmp_path / 'control.png')
    changed = scene.copy()
    ImageDraw.Draw(changed).rectangle(box, outline='#60caff', width=border_width)
    changed.save(tmp_path / 'after.png')
    target = {'image': str(tmp_path / 'control.png'), 'region_image': str(tmp_path / 'region.png')}
    hit = m.locate(target, tmp_path / 'before.png', tmp_path / 'after.png')
    assert (hit is not None) == expected_match
    if hit:
        assert hit['control_box'] and 'x' not in hit and ('y' not in hit)
    ImageDraw.Draw(changed).rectangle((120, 95, 200, 155), fill='black')
    changed.save(tmp_path / 'different.png')
    assert m.locate(target, tmp_path / 'before.png', tmp_path / 'different.png') is None
