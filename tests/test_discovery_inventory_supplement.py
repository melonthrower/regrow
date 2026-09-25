"""A local inventory gap must survive relocation without repeating the old batch."""
import json
from copy import deepcopy
from tests.test_recovery_discovery import ROOT, mod, seeded_run


def test_local_schema_accepts_more_than_eight_controls():
    import jsonschema
    schema=deepcopy(mod('discovery_step').schema(ROOT,'local')['properties']['controls'])
    schema['items']={}  # Exercise the array contract independently of control fields.
    jsonschema.validate([{} for _ in range(12)],schema)


def test_inventory_feedback_survives_loss_of_transient_correction(tmp_path,monkeypatch):
    m=mod('discovery_step');run=seeded_run(tmp_path)
    m.await_discovery(run,'returned.png','return')
    def mark(records,state,*args):
        records['r1']['task_inventory']={'inventory':'partial','evidence':'右上角的缺失入口需要补登记'}
        state.pop('correction_context',None)
    m.publish(run,'missing-control',mark)
    # Isolate prompt assembly from image-matcher fixture heuristics.
    from types import SimpleNamespace
    reg=m.registration();sibling=reg.sibling
    locator=SimpleNamespace(plan=lambda *a,**k:{'mode':'local','focus':'r1','regions':[],'controls':[],'next_offset':0})
    reg.sibling=lambda name:locator if name=='visual_region_locator' else sibling(name)
    monkeypatch.setattr(m,'registration',lambda:reg)
    q=m.request_from_run(ROOT,run)
    assert q['discovery_context']['mode']=='local'
    d=json.loads(q['user_prompt'])
    assert d['本区块待补登记']['任务清点反馈']=='右上角的缺失入口需要补登记'
    assert '不必重复输出' in q['system_prompt']
    assert d['本区块待补登记']['已登记控件数']==len(m.load(run)[1]['r1']['controls'])


def test_complete_inventory_does_not_request_gap_supplement(tmp_path):
    m=mod('discovery_step');run=seeded_run(tmp_path)
    m.await_discovery(run,'returned.png','return')
    m.publish(run,'complete',lambda records,*args:records['r1'].update(task_inventory={'inventory':'complete','evidence':'已列齐'}))
    q=m.request_from_run(ROOT,run)
    assert '本区块待补登记' not in json.loads(q['user_prompt'])
