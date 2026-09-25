from copy import deepcopy
import pytest
from gui_rewalk.src.core.evidence_explore.records import EvidenceStore


def reply():
    return dict(surface='Example',surface_kind='page',surface_box=[0,0,1000,1000],controls=[dict(key='open',label='Open',function='Open panel',box=[10,10,100,100],state='enabled')],
        receipt=None,regions=[dict(key='panel',name='Panel',parent='',controls=['open'],description='Main controls')],claims=[],links=[],
        action=dict(kind='click',point=[50,50],direction='',reason='Inspect panel'),uncertain=[])


def test_invalid_optional_graph_preserves_action_and_observation(tmp_path):
    store=EvidenceStore(tmp_path)
    raw=reply();raw['regions'][0]['parent']='missing'
    observation,action=store.accept(raw,b'frame')
    assert observation['controls'][0]['ref']=='f1:c0'
    assert action['owner']=='f1:c0'
    assert observation['regions']==[] and observation['note_errors']


def test_action_must_use_current_control_and_its_box(tmp_path):
    store=EvidenceStore(tmp_path);raw=reply();raw['action']['point']=[500,500]
    obs,action=store.accept(raw,b'frame')
    assert action is None and obs['action_error']
    assert store.frames[0]['controls']


def test_planned_is_not_delivered_or_success(tmp_path):
    store=EvidenceStore(tmp_path);obs,action=store.accept(reply(),b'frame')
    planned=store.plan(action)
    assert planned['status']=='planned'
    assert store.pending is None
    store.delivered(planned['ref'])
    assert store.pending['ref']=='a1' and planned['status']=='delivered'
    raw=reply();raw['receipt']=None
    obs,action=store.accept(raw,b'after')
    assert action is None and store.pending['ref']=='a1'
    assert obs['receipt_error']


def test_receipt_and_claim_provenance(tmp_path):
    store=EvidenceStore(tmp_path);_,a=store.accept(reply(),b'before')
    attempt=store.plan(a);store.delivered(attempt['ref'])
    raw=reply();raw['receipt']=dict(outcome='changed',description='Panel appeared')
    raw['claims']=[dict(text='Panel appears after Open',basis='action',controls=['open'])]
    obs,action=store.accept(raw,b'after')
    assert store.pending is None
    assert store.attempts[0]['after']=='f2'
    assert obs['claims'][0]['attempt']=='a1'
    assert store.frames[0]['image_sha256']!=obs['image_sha256']


def test_claim_without_executed_action_stays_hypothesis(tmp_path):
    store=EvidenceStore(tmp_path);raw=reply()
    raw['claims']=[dict(text='Open reveals panel',basis='action',controls=['open'])]
    obs,_=store.accept(raw,b'frame')
    assert obs['claims'][0]['basis']=='hypothesis'
    assert not obs['claims'][0]['attempt']


def test_failed_delivery_and_disabled_control_never_execute(tmp_path):
    store=EvidenceStore(tmp_path);raw=reply();raw['controls'][0]['state']='disabled'
    obs,action=store.accept(raw,b'frame');assert action is None
    raw=reply();_,action=store.accept(raw,b'frame2');a=store.plan(action)
    store.delivery_failed(a['ref'],'transport_error')
    assert store.pending is None and a['status']=='delivery_unknown'


def test_runtime_one_call_per_frame_and_receipt_budget(tmp_path):
    from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
    class Driver:
        actions=[]
        def scope_ok(self):return True
        def observe(self):return b'frame'+str(len(self.actions)).encode()
        def execute(self,a):self.actions.append(a);return {}
    class Agent:
        calls=0
        def _call(self,**kwargs):
            self.calls+=1;r=reply()
            if self.calls==2:r['receipt']=dict(outcome='changed',description='Panel opened');r['action']['kind']='stop'
            return r
    driver=Driver();agent=Agent();runtime=EvidenceRuntime(driver=driver,agent=agent,output=tmp_path,goal='Inspect',max_calls=2,max_actions=1)
    result=runtime.run()
    assert result['model_calls']==2 and result['delivered_actions']==1
    assert result['pending'] is None and runtime.store.attempts[0]['status']=='observed'


def test_last_call_cannot_dispatch_without_receipt_budget(tmp_path):
    from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
    class Driver:
        def scope_ok(self):return True
        def observe(self):return b'frame'
        def execute(self,a):raise AssertionError('must reserve observation')
    class Agent:
        def _call(self,**kwargs):return reply()
    result=EvidenceRuntime(driver=Driver(),agent=Agent(),output=tmp_path,goal='Inspect',max_calls=1).run()
    assert result['delivered_actions']==0 and result['status']=='reserve_receipt_budget'


def test_receipt_correction_keeps_original_before_image(tmp_path):
    from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
    class Driver:
        count=0
        def scope_ok(self):return True
        def observe(self):return b'before' if not self.count else b'after'
        def execute(self,a):self.count+=1;return {}
    class Agent:
        count=0
        def _call(self,**kwargs):
            self.count+=1;r=reply()
            if self.count==2:r['receipt']=None
            if self.count==3:
                assert kwargs['screenshots']==[b'before',b'after']
                r['receipt']=dict(outcome='changed',description='Changed');r['action']['kind']='stop'
            return r
    result=EvidenceRuntime(driver=Driver(),agent=Agent(),output=tmp_path,goal='inspect',max_calls=3).run()
    assert result['status']=='stopped_by_model' and result['pending'] is None


def test_duplicate_note_keys_do_not_block_unambiguous_current_click(tmp_path):
    store=EvidenceStore(tmp_path);raw=reply()
    other=deepcopy(raw['controls'][0]);other['box']=[200,200,300,300]
    raw['controls'].append(other)
    obs,action=store.accept(raw,b'frame')
    assert action['owner']=='f1:c0' and obs['note_errors']
    assert len(obs['controls'])==2


def test_overlapping_physical_candidates_require_correction(tmp_path):
    store=EvidenceStore(tmp_path);raw=reply()
    other=deepcopy(raw['controls'][0]);other['key']='other'
    raw['controls'].append(other)
    obs,action=store.accept(raw,b'frame')
    assert action is None and 'exactly one' in obs['action_error']


def test_previous_semantic_key_is_scoped_to_comparison_frame(tmp_path):
    store=EvidenceStore(tmp_path);store.accept(reply(),b'first')
    raw=reply();raw['links']=[dict(current_region='panel',previous_region='panel',relation='same_component',description='Same visible group')]
    obs,_=store.accept(raw,b'second')
    assert obs['links'][0]['previous_region']=='f1:r0'
    assert obs['links'][0]['identity_verified'] is False


def test_missing_receipts_stop_after_one_local_correction(tmp_path):
    from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
    class Driver:
        def scope_ok(self):return True
        def observe(self):return b'frame'
        def execute(self,a):return {}
    class Agent:
        def _call(self,**kwargs):return reply()
    result=EvidenceRuntime(driver=Driver(),agent=Agent(),output=tmp_path,goal='inspect',max_calls=16).run()
    assert result['status']=='local_correction_limit'
    assert result['model_calls']==3 and result['delivered_actions']==1 and result['pending']=='a1'


def test_changed_screen_does_not_mean_intent_met(tmp_path):
    store=EvidenceStore(tmp_path);_,action=store.accept(reply(),b'before')
    a=store.plan(action);store.delivered(a['ref'])
    raw=reply();raw['receipt']=dict(outcome='changed',intent='not_met',description='Only popup dismissed; target unchanged')
    store.accept(raw,b'after')
    assert store.attempts[0]['intent']=='not_met'
    assert store.attempts[0]['outcome']=='changed'


def test_two_failed_same_point_actions_block_third_but_allow_recovery(tmp_path):
    store=EvidenceStore(tmp_path);_,action=store.accept(reply(),b'first')
    for i in range(2):
        a=store.plan(action);store.delivered(a['ref'])
        raw=reply();raw['receipt']=dict(outcome='unchanged',intent='not_met',description='No effect')
        obs,action=store.accept(raw,bytes([i]))
    assert action is None and 'same location' in obs['action_error']
    raw=reply();raw['action']['kind']='back'
    obs,action=store.accept(raw,b'recovery')
    assert action and action['kind']=='back'


def test_partial_background_control_cannot_cross_popup_boundary(tmp_path):
    raw=reply();raw['surface_kind']='popup';raw['surface_box']=[40,40,80,80]
    store=EvidenceStore(tmp_path);obs,action=store.accept(raw,b'popup')
    assert action is None and 'input surface' in obs['action_error']
    assert obs['controls'][0]['in_surface'] is False


@pytest.mark.parametrize('missing',[False,True])
def test_unknown_surface_blocks_click(missing,tmp_path):
    raw=reply();raw['surface_kind']='unknown'
    if missing:raw.pop('surface_kind')
    obs,action=EvidenceStore(tmp_path).accept(raw,b'frame')
    assert action is None and 'input surface unknown' in obs['action_error']


def test_context_separates_historical_regions_from_current_controls(tmp_path):
    store=EvidenceStore(tmp_path);store.accept(reply(),b'first')
    context=store.context()
    assert 'controls' not in context['previous']
    assert 'control_refs' not in context['previous']['regions'][0]
    assert context['previous']['regions'][0]['key']=='panel'


def test_receipt_correction_uses_latest_error_with_original_before(tmp_path):
    store=EvidenceStore(tmp_path);_,a=store.accept(reply(),b'before')
    a=store.plan(a);store.delivered(a['ref'])
    store.accept(reply(),b'after')
    context=store.context()
    assert context['previous']['ref']=='f1'
    assert context['correction']['receipt']
