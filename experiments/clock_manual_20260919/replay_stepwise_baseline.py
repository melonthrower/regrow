"""Replay frozen replies only; never imports a model client or device controller."""
import hashlib
import importlib.util
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent
RUN = EXP/'luna_runs/clock_region_20260919_01'
COPY = EXP/'framework_copies/region_stepwise_20260919_01'


def main():
    out = COPY/'stepwise/baseline_replay'
    out.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('flow', COPY/'stepwise/stepwise_flow.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    call_map = {'observe':'0001','choose':'0002','settle':'0003'}
    trace, records, hashes = [], [], {}
    def model(role, request):
        folder = RUN/'calls'/call_map[role]
        expected = json.loads((folder/'request.json').read_text())
        assert request == expected
        trace.append({'phase':role,'source_call':call_map[role],
                      'system_sha256':hashlib.sha256(request['system_prompt'].encode()).hexdigest(),
                      'new_http':0})
        return json.loads((folder/'response.json').read_text())
    def delivery(proposal):
        assert proposal == json.loads((RUN/'action_attempts/a0001/proposal.json').read_text())
        trace.append({'phase':'execution','source_attempt':'a0001','new_gui':0})
        return json.loads((RUN/'action_attempts/a0001/receipt.json').read_text())
    def record(role, value):
        records.append({'phase':role,'value':value})
    source_files = [p for p in RUN.rglob('*') if p.is_file()]
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    f = module.StepwiseFlow(model, delivery, record)
    request = lambda role: json.loads((RUN/'calls'/call_map[role]/'request.json').read_text())
    f.observe(request('observe'))
    f.choose(request('choose'))
    # Replay the historical root clearance; this does not clear any future action.
    f.execute(lambda p: p == json.loads((RUN/'action_attempts/a0001/proposal.json').read_text()))
    f.settle(request('settle'))
    assert [x['phase'] for x in trace] == ['observe','choose','execution','settle']
    graph = json.loads((RUN/'graph_snapshots/0002.json').read_text())
    edges = module.region_transitions(graph)
    assert [(e['source_region'],e['source_control'],e['target_region']) for e in edges] == [('r0001','c0001','r0003')]
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    for name,value in [('trace.json',trace),('records.json',records),('region_transitions.json',edges),
                       ('result.json',{'status':'offline_baseline_match','model_calls_replayed':3,'actions_replayed':1,'new_http':0,'new_gui':0,'original_evidence_unchanged':True,'live_adapter_wiring':'not implemented by this stage driver'})]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
