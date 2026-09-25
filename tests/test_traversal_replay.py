import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def test_replay_does_not_promote_proposal_or_leak_future_graph(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import traversal_replay as replay
    def save(p, v):
        p = tmp_path / p; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(v))
    save('run_manifest.json', {'app':'test'})
    save('knowledge_current.json', {'snapshot':'knowledge_snapshots/update'})
    for name, parent, call, regions in [('initial',None,None,[]),('first','knowledge_snapshots/initial','0001',['r1']),('update','knowledge_snapshots/first','0003',['r1','r2'])]:
        save(f'knowledge_snapshots/{name}/source.json', {'parent_snapshot':parent,'call':call})
        save(f'knowledge_snapshots/{name}/runtime_state.json', {'interactive_regions':regions,'working_region':'r1'})
        for rid in regions:save(f'knowledge_snapshots/{name}/regions/{rid}/region.json', {'id':rid,'name':rid,'controls':{},'tasks':{}})
    save('calls/0002/request.json', {'stage':'action_selection','screenshots':[]})
    save('calls/0002/response.json', {'action':'click','target':'Open'})
    save('action_attempts/a1/dispatch.json', {'source_call':'0002','action':{'action':'click'}})
    save('action_attempts/a1/binding.json', {'region_ref':'r1','control_ref':'c1'})
    save('action_attempts/a1/receipt.json', {'exit_code':0,'executed_steps':[{'action':'click'}]})
    for file in ['screenshots/initial.png','action_attempts/a1/before.png','action_attempts/a1/after.png']:
        p=tmp_path/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'png')
    save('knowledge_snapshots/frontier/source.json', {'parent_snapshot':'knowledge_snapshots/update'})
    save('knowledge_snapshots/frontier/runtime_state.json', {'interactive_regions':['r2'],'working_region':'r2'})
    save('knowledge_current.json', {'snapshot':'knowledge_snapshots/frontier'})
    result=replay.project(tmp_path)
    before=next(e for e in result['events'] if e['kind']=='before')
    after=next(e for e in result['events'] if e['kind']=='after')
    assert before['snapshot']=='knowledge_snapshots/first'
    assert after['snapshot']=='knowledge_snapshots/first'  # GUI receipt is not a registered landing
    assert result['events'][-1]['snapshot']=='knowledge_snapshots/frontier'
    assert next(e for e in result['events'] if e['snapshot']=='knowledge_snapshots/update')['kind']=='registered'
    assert after['label'].startswith('已执行')
    (tmp_path/'action_attempts/a1/receipt.json').unlink()
    assert not any(e['kind']=='after' for e in replay.project(tmp_path)['events'])
    save('action_attempts/a0/proposal.json', {'action':'click','target':'Open'})
    save('action_attempts/a0/binding.json', {'region_ref':'r1'})
    (tmp_path/'action_attempts/a0/pre_dispatch.png').write_bytes(b'png')
    check=next(e for e in replay.project(tmp_path)['events'] if e['id']=='a0-check')
    assert check['kind']=='blocked' and '尚无执行回执' in check['label']
    with pytest.raises(ValueError):replay.asset(tmp_path,'../../secret.png')
