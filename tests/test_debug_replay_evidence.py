from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'
sys.path.insert(0, str(ROOT))
import debug_candidate
from debug_loop import write


def evidence(tmp_path):
    run = tmp_path / 'run'
    incident = tmp_path / 'incident'
    original = {'stage': 'function_registration', 'role': 'function_registration',
                'source': {'region': 'r1'}, 'screenshots': [], 'image_refs': [],
                'action_ready': False, 'user_prompt': '{"history": "observed"}'}
    write(incident / 'references.json', {'run': str(run), 'snapshot': {'snapshot': 'snapshot'}})
    write(run / 'snapshot/regions/r1/region.json', {
        'registration_gaps': {'function_registration': {'episode': 'episode.json'}}})
    write(run / 'episode.json', {'request': original})
    return incident, run, original


def test_real_text_only_function_request_preserves_original_history(tmp_path):
    incident, _, request = evidence(tmp_path)
    debug_candidate.validate_replay_evidence(incident, request)
    with pytest.raises(ValueError):
        debug_candidate.validate_replay_evidence(incident, {**request, 'user_prompt': '{}'})


def test_empty_visual_or_relabelled_original_cannot_bypass(tmp_path):
    incident, run, request = evidence(tmp_path)
    with pytest.raises(ValueError):
        debug_candidate.validate_replay_evidence(incident, {**request, 'stage': 'update'})
    write(run / 'episode.json', {'request': {**request, 'role': 'observation_update'}})
    with pytest.raises(ValueError):
        debug_candidate.validate_replay_evidence(incident, request)


def test_missing_original_is_not_text_evidence(tmp_path):
    incident, run, request = evidence(tmp_path)
    (run / 'episode.json').unlink()
    with pytest.raises(ValueError):
        debug_candidate.validate_replay_evidence(incident, request)


def test_visual_evidence_must_be_original_pixels(tmp_path):
    incident, _, request = evidence(tmp_path)
    frame = incident / 'calls/0001/frame-0.png'
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b'original')
    debug_candidate.validate_replay_evidence(incident, {**request, 'screenshots': [str(frame)]})
    foreign = tmp_path / 'foreign.png'
    foreign.write_bytes(b'changed')
    with pytest.raises(ValueError):
        debug_candidate.validate_replay_evidence(incident, {**request, 'screenshots': [str(foreign)]})
