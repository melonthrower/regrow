"""Known-route replay never treats delivery or a familiar background as success."""
import io
from copy import deepcopy
import numpy as np
from PIL import Image
import pytest
from gui_rewalk.src.core.evidence_explore.reidentify import locate_control, same_view
from gui_rewalk.src.core.evidence_explore.route import KnownRoute, RouteRuntime


def png(seed):
    a=np.random.default_rng(seed).integers(0,256,(160,240,3),dtype=np.uint8)
    out=io.BytesIO();Image.fromarray(a).save(out,format='PNG');return out.getvalue()


def route_fixture(tmp_path):
    images=[png(i) for i in range(3)];frames=[]
    for i,b in enumerate(images):
        path=tmp_path/f'original{i}.png';path.write_bytes(b)
        frames.append(dict(ref=f'f{i+1}',image=str(path),surface=f'page{i}',surface_kind='page',surface_box=[0,0,1000,1000],
            controls=[dict(ref=f'f{i+1}:c0',key='next',label='Next',function='Open next page',box=[100,100,300,300],state='enabled')],regions=[],claims=[],links=[],uncertain=[]))
    attempts=[dict(ref=f'a{i+1}',before=f'f{i+1}',after=f'f{i+2}',status='observed',intent='met',outcome='changed',action=dict(kind='click',point=[200,200],direction='',reason='Open next page',owner=f'f{i+1}:c0')) for i in range(2)]
    return dict(frames=frames,attempts=attempts,pending=None),images


class Driver:
    def __init__(self,images):self.images=images;self.index=0;self.executed=[]
    def scope_ok(self):return True
    def observe(self):return self.images[self.index]
    def execute(self,action):self.executed.append(action);self.index+=1;return {}


class NoAgent:
    def _call(self,**kwargs):raise AssertionError('known deterministic step should not call model')


def test_known_two_step_route_zero_calls(tmp_path):
    records,images=route_fixture(tmp_path);route=KnownRoute.from_records(records,['a1','a2'])
    d=Driver(images);r=RouteRuntime(driver=d,agent=NoAgent(),route=route,output=tmp_path/'out',max_calls=3,max_actions=2).run()
    assert r['status']=='route_complete' and r['model_calls']==0 and r['delivered_actions']==2
    assert r['pending'] is None
    import json
    exported=json.loads((tmp_path/'out/records.json').read_text())
    assert len(KnownRoute.from_records(exported,['a1','a2']).steps)==2


def test_refuses_unconfirmed_or_disconnected_route(tmp_path):
    records,_=route_fixture(tmp_path);records['attempts'][0]['intent']='uncertain'
    with pytest.raises(ValueError):KnownRoute.from_records(records,['a1'])
    records,_=route_fixture(tmp_path)
    with pytest.raises(ValueError):KnownRoute.from_records(records,['a2','a1'])


def test_changed_after_supervision_does_not_dispatch_stale_point(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver(images)
    def approve(*a):d.images[0]=png(99);return True
    result=RouteRuntime(driver=d,agent=NoAgent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',before_action=approve,max_calls=2).run()
    assert not d.executed and result['status']=='changed_before_dispatch'


def test_unknown_destination_requests_model_and_preserves_failure(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver([images[0],png(55)])
    class Agent:
        def _call(self,**kwargs):return dict(surface='Other',surface_kind='page',surface_box=[0,0,1000,1000],control_box=[0,0,0,0],point=[0,0],state='unknown',target_found=False,destination_matches=False,reason='Unexpected page')
    result=RouteRuntime(driver=d,agent=Agent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out').run()
    assert result['status']=='destination_unconfirmed' and result['model_calls']==1
    assert result['delivered_actions']==1 and result['pending'] is None


def test_grounding_fallback_is_front_surface_checked(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver([png(66),images[1]])
    class Agent:
        def _call(self,**kw):return dict(surface='Popup',surface_kind='popup',surface_box=[500,500,1000,1000],control_box=[100,100,300,300],point=[200,200],state='enabled',target_found=True,destination_matches=False,reason='Incorrect background')
    result=RouteRuntime(driver=d,agent=Agent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out').run()
    assert not d.executed and result['status']=='grounding_rejected'


def test_missing_call_budget_never_guesses(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver([png(77),images[1]])
    result=RouteRuntime(driver=d,agent=NoAgent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',max_calls=0).run()
    assert result['status']=='call_limit' and not d.executed


def test_foreground_and_duplicate_controls():
    a=np.full((160,400,3),240,np.uint8)
    for x in [30,220]:a[50:66,x:x+16]=0;a[53:63,x+3:x+13]=255
    # Nearby unique registration evidence disambiguates otherwise identical squares.
    a[48:68,60:140]=np.random.default_rng(2).integers(0,256,(20,80,3),dtype=np.uint8)
    out=locate_control(a,a,[30,50,46,66],[0,0,400,160])
    assert out['accepted'] and abs(out['box'][0]-30)<=2
    out=locate_control(a,a,[30,50,46,66],[210,40,260,80])
    assert not out['accepted']


def test_same_view_detects_modal():
    a=png(2);assert same_view(a,a)
    b=np.array(Image.open(io.BytesIO(a)));b[30:120,40:200]=0;o=io.BytesIO();Image.fromarray(b).save(o,format='PNG')
    assert not same_view(a,o.getvalue())


def test_region_cannot_count_one_control_twice():
    from gui_rewalk.src.core.evidence_explore.reidentify import locate_region
    image=np.random.default_rng(8).integers(0,256,(160,240,3),dtype=np.uint8)
    result=locate_region(image,image,[0,0,240,160],[0,0,240,160],anchors=[[30,30,70,70],[30,30,70,70]])
    assert not result['accepted']


def test_successful_grounding_then_visual_destination(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver([png(99),images[1]])
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1
            return dict(surface='Current',surface_kind='page',surface_box=[0,0,1000,1000],control_box=[100,100,300,300],point=[200,200],state='enabled',target_found=True,destination_matches=False,reason='Visible current target')
    a=Agent();result=RouteRuntime(driver=d,agent=a,route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out').run()
    assert result['status']=='route_complete' and a.calls==1
    assert (tmp_path/'out/memory/corrections.json').exists()


def test_unconfirmed_delivery_preserves_pending_when_budget_exhausted(tmp_path):
    records,images=route_fixture(tmp_path);d=Driver([images[0],png(98)])
    result=RouteRuntime(driver=d,agent=NoAgent(),route=KnownRoute.from_records(records,['a1']),output=tmp_path/'out',max_calls=0).run()
    assert result['status']=='call_limit' and result['pending']=='a1'


def test_confirmed_new_appearance_does_not_repeat_foreground_call(tmp_path):
    records,images=route_fixture(tmp_path)
    changed=np.array(Image.open(io.BytesIO(images[1])));changed[80:110,150:210]=0
    out=io.BytesIO();Image.fromarray(changed).save(out,format='PNG');d=Driver([images[0],out.getvalue(),images[2]])
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1
            return dict(surface='Known intermediate',surface_kind='page',surface_box=[0,0,1000,1000],control_box=[0,0,0,0],point=[0,0],state='unknown',target_found=False,destination_matches=True,reason='Same navigation destination, changed contents')
    a=Agent();result=RouteRuntime(driver=d,agent=a,route=KnownRoute.from_records(records,['a1','a2']),output=tmp_path/'out').run()
    assert result['status']=='route_complete' and a.calls==1


def test_explicit_semantic_context_drives_checkbox_identity():
    image=np.full((160,400,3),240,np.uint8)
    for x in [30,220]:image[50:66,x:x+16]=0;image[53:63,x+3:x+13]=255
    image[48:68,60:140]=np.random.default_rng(2).integers(0,256,(20,80,3),dtype=np.uint8)
    result=locate_control(image,image,[30,50,46,66],[0,0,400,160],context_box=[25,45,145,72])
    assert result['accepted'] and result['method']=='semantic_context'
    assert result['context_box']==[25,45,145,72]


def test_context_must_contain_action_box(tmp_path):
    from gui_rewalk.src.core.evidence_explore.records import EvidenceStore
    raw=dict(surface='Page',surface_kind='page',surface_box=[0,0,1000,1000],controls=[dict(key='x',label='Read',function='Read',box=[100,100,200,200],context_box=[300,300,400,400],state='enabled')],regions=[],claims=[],links=[],uncertain=[],receipt=None,action=dict(kind='click',point=[150,150],direction='',reason='Read'))
    with pytest.raises(ValueError,match='context'):EvidenceStore(tmp_path/'store').accept(raw,png(1))


def test_bad_registration_context_is_returned_to_luna_for_correction(tmp_path):
    from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
    class Agent:
        calls=0
        def _call(self,**kwargs):
            self.calls+=1
            if self.calls==2:assert 'registration_correction' in kwargs['user_prompt']
            context=[300,300,400,400] if self.calls==1 else [90,90,300,250]
            return dict(surface='Page',surface_kind='page',surface_box=[0,0,1000,1000],controls=[dict(key='x',label='Read',function='Read',box=[100,100,200,200],context_box=context,state='enabled')],regions=[],claims=[],links=[],uncertain=[],receipt=None,action=dict(kind='stop',point=[0,0],direction='',reason='Registered'))
    a=Agent();d=Driver([png(3)])
    result=EvidenceRuntime(driver=d,agent=a,output=tmp_path/'out',goal='Register',max_calls=2).run()
    assert result['status']=='stopped_by_model' and result['model_calls']==2 and not d.executed
    assert (tmp_path/'out/calls/0001/validation_error.json').exists()
