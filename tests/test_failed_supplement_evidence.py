"""Failed supplementary observations remain available to the correction consumer."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('failure', ['schema', 'identity'])
def test_failed_supplement_reaches_next_correction_without_registration(tmp_path, monkeypatch, failure):
    import locator
    stages, repair, discovery = load('repair_stages'), load('step_repair'), load('discovery_step')
    item = {'identity': 'uncertain', 'previous_name': 'Old arrow'}
    reply = {'regions': [], 'controls': [item]}
    if failure == 'schema':
        reply = {'unrecognized': 'raw reply must survive'}
    q = {'system_prompt': 'Observe', 'user_prompt': '{}', 'screenshots': ['original.png'],
         'response_schema': {'type': 'object', 'required': ['regions', 'controls']},
         'discovery_context': {}}
    original = deepcopy(q)
    published = []
    # Only the observation setup is replaced; validation, persistence and the
    # correction request consumer use the production implementations.
    observed = SimpleNamespace(load=lambda run: (tmp_path, {}, {}),
        focus_task=lambda *args: None, prepare=lambda *args: deepcopy(q),
        validate_identity=locator.validate_identity,
        publish=lambda *args: published.append(args))
    real_helper = stages.helper
    monkeypatch.setattr(stages, 'helper', lambda name: observed if name in ('discovery_step','locator') else real_helper(name))
    def call(request):
        repair.atomic(tmp_path / 'calls/0002/request.json', request)
        return '0002', deepcopy(reply)
    runner = repair.Runner(ROOT, tmp_path, call, lambda p: p.write_bytes(b'new frame'), lambda: 1)
    job = {'path': 'episode.json', 'stage': 'discovery', 'request': original,
           'observations': 0, 'candidate': {}, 'supplements': [], 'history': [],
           'observation_question': 'Which card owns the arrow?'}
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        stages.observe(runner, job)
    saved = json.loads((tmp_path / 'episode.json').read_text())
    assert len(saved['supplements']) == 1
    supplement = saved['supplements'][0]
    assert supplement['reply'] == reply
    assert supplement['source_call'] == '0002'
    assert supplement['validation']['status'] == 'rejected'
    assert supplement['validation']['error']
    assert saved['request'] == original and saved['observations'] == 1
    assert not published
    correction = repair.request(ROOT, saved, {})
    assert correction['screenshots'] == ['original.png', str(tmp_path / 'supplement.png')]
    assert json.loads(correction['user_prompt'])['补充观察'][0] == supplement
    with pytest.raises(ValueError, match='补观察已尝试'):
        stages.observe(runner, saved)
    assert len(saved['supplements']) == 1
