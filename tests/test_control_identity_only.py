from copy import deepcopy
from pathlib import Path
import pytest
from tests.test_recovery_discovery import ROOT,mod

@pytest.fixture(autouse=True)
def modules(monkeypatch):monkeypatch.syspath_prepend(str(ROOT))


def test_region_pixels_never_override_model_new_identity(tmp_path):
    from tests.test_stepwise_shared_region_identity import control_case
    m,records,reply=control_case(tmp_path)
    records['r0001']['observations'].insert(0,{'image':None,'controls_complete':True,'image_quality':'occluded'})
    original=deepcopy(reply);result,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert result==original and audit==[]


def test_only_eligible_nonshared_control_templates_vote(tmp_path):
    m=mod('history_matching');calls=[]
    def item(path,**kw):return {'observations':[{'image':None,'image_quality':'occluded'},{'image':path,'image_quality':'clear','image_quality_reason':'clear'}],**kw}
    region={**item('region.png'),'controls':{'a':item('a.png'),'b':item('b.png',shared_control_ref={'region':'other','name':'shared'}),'empty':{'observations':[{'image':None,'image_quality':'clear'}]}}}
    def match(path,*args):calls.append(path);return {'accepted':True,'score':1,'box':[10,10,20,20]}
    row=m.match_region('r',region,match,None,scope={'interactive_areas':[[0,0,100,100]],'excluded_areas':[]})
    assert calls==['a.png'] and row['matched_controls']==1 and row['shared_controls']==1
    assert not row['strong'] and row['bounds'] is None


def test_local_scan_uses_same_frame_model_boundary_not_region_image(monkeypatch):
    m=mod('visual_region_locator');records={'r':{'name':'Panel','controls':{},'observations':[{'image':'forbidden.png','image_quality':'clear','image_quality_reason':'clear'}]}}
    monkeypatch.setattr(m.history,'scan',lambda *a,**kw:[{'region':'r','anchors':[],'whole':{'accepted':False},'strong':False,'bounds':None,'matched_controls':0}])
    scope={'interactive_areas':[[0,0,100,100]],'excluded_areas':[],'region_bounds':{'r':[0,0,100,100]}}
    plan=m.plan(records,'r','frame',foreground=scope,locate=lambda *a:pytest.fail('whole image was read'))
    assert plan['mode']=='local' and plan['regions'][0]['bounds']==[0,0,100,100]


def test_boundary_cache_is_frame_specific_and_keeps_same_frame_peers(tmp_path,monkeypatch):
    import json,hashlib,discovery_step
    from PIL import Image
    m=mod('foreground_scope');frame=tmp_path/'frame.png';Image.new('RGB',(100,100),'red').save(frame)
    monkeypatch.setattr(discovery_step,'load',lambda _: (None,{f'r{i+1}':{'name':name,'observations':[{'evidence':{'source_call':'c','source_field':f'/regions/{i}'}}]} for i,name in enumerate(['One','Two'])},{}))
    def value(items):return {'source_call':'c','frame_sha256':m.fingerprint(frame),'scope':{'interactive_areas':[[0,0,100,100]],'excluded_areas':[]},'identified_regions':items}
    one={'source_field':'/regions/0','bbox':dict(left=0,top=0,right=40,bottom=40)}
    two={'source_field':'/regions/1','bbox':dict(left=50,top=0,right=90,bottom=40)}
    m.remember(tmp_path,value([one,two]));m.remember(tmp_path,value([one]))
    unregistered={'source_field':'/regions/2','bbox':dict(left=0,top=0,right=100,bottom=100)}
    m.remember(tmp_path,value([unregistered]))
    assert set(m.load(tmp_path,frame)['region_bounds'])=={'r1','r2'}
    Image.new('RGB',(100,100),'blue').save(frame)
    assert m.load(tmp_path,frame) is None


def test_generated_update_prompt_has_no_legacy_region_pixel_override():
    q=mod('result_updater').build_update_request(ROOT,{},['before.png','after.png'])
    for stale in ['框架在登记前统一比较区块裁图','历史区块裁图在当前整图','唯一的像素相同区块会自动复用','自动复用条件见']:
        assert stale not in q['system_prompt']
    assert '程序不依据区块整体外观自动覆盖' in q['system_prompt']
