from copy import deepcopy
import pytest
from regrow.recognition import action_target_review as review


def test_unmatched_text_uses_current_visual_identity_before_model_review(tmp_path, monkeypatch):
    from PIL import Image
    from regrow.traversal.action_binding import bind_action_target
    frame = tmp_path / 'current.png'; Image.new('RGB', (100, 100)).save(frame)
    q = {'source': {'region': 'r1', 'observation': 'o1', 'task_name': 'original',
                    'task_control': 'c1', 'completion_region': 'r1'},
         'preparation_allowed': True, 'image_refs': [str(frame)],
         'backend_candidates': [
             {'id': 'c1', 'region_ref': 'r1', 'name': 'Original', 'image': 'one'},
             {'id': 'c2', 'region_ref': 'r2', 'name': 'Visible', 'image': 'two'}]}
    hits = {'one': {'accepted': True, 'box': [0, 0, 20, 20]},
            'two': {'accepted': True, 'box': [30, 30, 50, 50]}}
    monkeypatch.setattr(review, 'match_appearances', lambda rows, locate: hits[rows[0]['image']])
    p = {'action': 'click', 'target': 'the visible green button', 'x': 40, 'y': 40}
    original = deepcopy(p)
    binding = bind_action_target(q, p)
    assert (binding['region_ref'], binding['control_ref']) == ('r2', 'c2')
    assert binding['task_name'] == 'original' and binding['preparatory_action']
    assert p == original and review.conflict(q, p, binding) is None
    hits['one'] = hits['two']
    with pytest.raises(review.Conflict):
        bind_action_target(q, p)
    hits['one'] = hits['two'] = {'accepted': False}
    with pytest.raises(review.Conflict):
        bind_action_target(q, p)
    confirmed = {**q, 'action_target_confirmation': {'frames': [str(frame)], 'action': review.action_key(p)}}
    assert bind_action_target(confirmed, p)['association']['status'] == 'unconfirmed'
    hits['two'] = {'accepted': True, 'box': [30, 30, 50, 50]}
    assert bind_action_target(confirmed, p)['association']['status'] == 'unconfirmed'
    hits['two'] = {'accepted': False}
    fresh = tmp_path / 'fresh.png'; Image.new('RGB', (100, 100)).save(fresh)
    assert review.conflict({**q, 'image_refs': [str(fresh)]}, p, binding)
