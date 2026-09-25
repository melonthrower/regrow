from copy import deepcopy
from tests.test_stepwise_deferral import setup
from tests.test_recovery_discovery import mod,ROOT


def test_missing_support_returns_to_task_proposal_without_fabricating_tasks(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(r,s,*args):
        for t in r['r1']['tasks'].values():t['status']='done'
        r['r1']['tasks'].pop('Settings')
    d.publish(run,'finish-existing',seed)
    f=mod('region_functions');before=deepcopy(d.load(run)[1]['r1']['tasks'])
    assert f.request_support_review(run,'r1','failed-call')
    snapshot,records,state=d.load(run)
    assert records['r1']['tasks']==before
    assert records['r1']['task_inventory']['review']['kind']=='function_support'
    assert not f.request_support_review(run,'r1','same-failure')


def test_ownership_review_without_moves_preserves_inventory(tmp_path):
    from tests.test_stepwise_deferral import setup
    from copy import deepcopy
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run)
    original=deepcopy(records);old_state=deepcopy(state)
    ep={'source_region':'r1','assignments':{cid:{'region':records['r1']['name']} for cid in records['r1']['controls']},'conflicts':{}}
    import ownership_review
    assert ownership_review.repartition(records,state,ep,snapshot)=={}
    assert records==original and state==old_state


def test_resolved_ownership_hands_conclusion_to_next_discovery(tmp_path,monkeypatch):
    import ownership_review as o,json
    from types import SimpleNamespace
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run)
    episode={'actions':[],'source_region':'r1','assignments':{},'conflicts':{}}
    (run/'ownership_review.json').write_text(json.dumps({'episode':'review.json'}))
    (run/'review.json').write_text(json.dumps(episode))
    def publish(run,tag,mutate):mutate(records,state,snapshot,tmp_path)
    def atomic(path,data):path.write_text(json.dumps(data))
    monkeypatch.setattr(o,'helper',lambda name:SimpleNamespace(atomic=atomic) if name=='step_repair' else SimpleNamespace(load=lambda r:(snapshot,records,state),publish=publish))
    monkeypatch.setattr(o,'request',lambda *args:{'response_schema':{}})
    monkeypatch.setattr(o,'record_observation',lambda *args:None)
    monkeypatch.setattr(o,'repartition',lambda *args:{})
    reply={'status':'resolved','reason':'原归属正确，本次疑问已解决','observed_assignments':[],'action':None}
    transport=SimpleNamespace(run=run,screenshot=lambda path:None)
    assert o.run(ROOT,transport,tmp_path,lambda q:('review',reply))['status']=='ready_next_round'
    assert state['correction_context']['结论']==reply['reason']
    assert state['pending_frame']==str(tmp_path/'ownership-current.png')


def test_ownership_prompt_exposes_text_not_only_control_name(tmp_path,monkeypatch):
    import ownership_review as o,json
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run)
    c=next(iter(records['r1']['controls'].values()));c['observations']=[{'text':'Essential, Crop','icon_description':'tabs','state':'Crop selected'}]
    original=o.helper
    monkeypatch.setattr(o,'helper',lambda name:type('D',(),{'load':staticmethod(lambda r:(snapshot,records,state))}) if name=='discovery_step' else original(name))
    q=o.request(ROOT,run,{'source_region':'r1','proposed_regions':[],'assignments':{},'conflicts':{},'actions':[]},tmp_path/'frame.png')
    row=json.loads(q['user_prompt'])['待核对历史控件'][0]
    assert row['最近登记观察']['text']=='Essential, Crop'
