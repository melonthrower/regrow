"""The receiving boundary must use the contract actually sent to the model."""
import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import jsonschema
import pytest
import subprocess

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_runner_keeps_sent_contract_for_acceptance_and_correction(tmp_path):
    m = module('step_repair')
    original = {'stage':'discovery', 'role':'discover', 'system_prompt':'Observe',
                'user_prompt':'Current frame', 'screenshots':[], 'fixed_parts':[],
                'response_schema':{'type':'object','properties':{},'additionalProperties':False}}
    sent = deepcopy(original)
    sent.update(dependency_candidates=[{'region':'r1','task':'unlock'}])
    sent['response_schema'].update(properties={'dependency_updates':{'type':'array'}}, required=['dependency_updates'])
    reply = {'dependency_updates':[]}
    def call(q):
        m.atomic(tmp_path / 'calls/0001/request.json', sent)
        m.atomic(tmp_path / 'calls/0001/response.json', reply)
        return '0001', reply
    def accept(root, run, job):
        assert job['request'] == sent
        jsonschema.validate(job['candidate'], job['request']['response_schema'])
        correction = m.request(root, job, {})
        assert correction['original_request']['dependency_candidates'] == sent['dependency_candidates']
        jsonschema.validate(reply, correction['response_schema']['properties']['proposal'])
        return {'accepted':True}
    runner = m.Runner(ROOT, tmp_path, call, None, lambda:1)
    runner.adapters = SimpleNamespace(accept=accept)
    job = runner.perform('discovery', original)
    assert job['result']['accepted']
    assert original['response_schema']['properties'] == {}

def test_reused_augmented_request_preserves_original_candidates(tmp_path):
    m = module('task_prerequisites')
    q = {'stage':'discovery','dependency_candidates':[{'region':'r1','task':'old'}],
         'response_schema':{'required':['dependency_updates'],'properties':{'dependency_updates':{'type':'array'}}}}
    # No current graph exists: an already sent request must not reselect from it.
    assert m.augment(ROOT, tmp_path, q) == q

@pytest.mark.parametrize('failure', ['parse', 'http'])
def test_failed_model_call_keeps_sent_contract_before_repair_or_retry(tmp_path, failure):
    m = module('step_repair')
    original = {'stage':'discovery', 'response_schema':{'type':'object'}}
    sent = {**original, 'dependency_candidates':[{'region':'r1','task':'unlock'}]}
    calls = []
    def call(q):
        calls.append(q)
        m.atomic(tmp_path/'run_manifest.json', {'last_call':'0001'})
        m.atomic(tmp_path/'calls/0001/request.json', sent)
        if failure == 'parse':
            m.atomic(tmp_path/'calls/0001/parse_error.json', {'reason':'incomplete JSON'})
        else:
            m.atomic(tmp_path/'calls/0001/http_error.json', {'status':503})
        raise subprocess.CalledProcessError(1, 'model')
    runner = m.Runner(ROOT, tmp_path, call, None, lambda:0 if calls else 1)
    with pytest.raises(m.Paused):
        runner.perform('discovery', original)
    job = m.pending(tmp_path)
    assert job['request'] == sent
    if failure == 'http':
        assert job['service_retry_request'] == sent
