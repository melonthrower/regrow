import numpy as np
import pytest
from gui_rewalk.src.core.evidence_explore.panorama import RegionPanorama, locate_view, down_shift


def scene():
    rng=np.random.default_rng(17)
    return rng.integers(0,256,(700,140,3),dtype=np.uint8)


def test_stitch_and_locate_preserve_map_positions(tmp_path):
    image=scene();p=RegionPanorama(tmp_path,[10,20,150,320])
    p.add_view(image[:300],source='first.png')
    assert p.add_view(image[110:410],source='second.png')==110
    assert p.add_view(image[220:520],source='third.png')==110
    assert np.array_equal(p.image,image[:520])
    assert locate_view(image[180:480],p.image)==180
    assert p.tiles[2]['offset']==220


def test_low_texture_and_missing_overlap_rejected(tmp_path):
    assert locate_view(np.zeros((300,140,3),dtype=np.uint8),np.zeros((600,140,3),dtype=np.uint8)) is None
    image=scene();p=RegionPanorama(tmp_path,[0,0,140,300]);p.add_view(image[:300],source='first')
    with pytest.raises(ValueError):p.add_view(image[390:690],source='jump')
    assert p.image.shape[0]==300 and len(p.tiles)==1


def test_target_plan_scrolls_then_matches_visible_control(tmp_path):
    image=scene();p=RegionPanorama(tmp_path,[10,20,150,320]);p.add_view(image[:300],source='first')
    p.add_view(image[150:450],source='second')
    p.register([dict(key='top',label='Top',function='Open top',box=[10,20,100,55])])
    assert p.plan('top',image[150:450])['kind']=='scroll'
    plan=p.plan('top',image[:300]);assert plan['kind']=='click'
    assert plan['point_px']==[65,57]
    assert p.plan('top',np.zeros_like(image[:300]))['kind']=='unresolved'


def test_persistence_retains_control_ids_and_provenance(tmp_path):
    image=scene();p=RegionPanorama(tmp_path,[0,0,140,300]);p.add_view(image[:300],source='original.png')
    p.register([dict(key='target',label='Target',function='Open',box=[20,30,80,60])]);p.save()
    q=RegionPanorama.load(tmp_path)
    assert q.controls[0]['ref']==p.controls[0]['ref']
    assert q.tiles[0]['source']=='original.png'
    assert np.array_equal(q.image,p.image)


def test_repeated_visual_content_is_not_a_unique_viewport():
    image=scene()[:300]
    assert locate_view(image[:200],np.vstack([image,image])) is None


def test_changed_target_pixels_are_not_clicked(tmp_path):
    image=scene();p=RegionPanorama(tmp_path,[0,0,140,300]);p.add_view(image[:300],source='first')
    p.register([dict(key='target',label='Target',function='Open',box=[10,50,100,75])])
    changed=image[:300].copy();changed[50:75,10:100]=0
    plan=p.plan('target',changed)
    assert plan['kind']=='unresolved'


def test_session_scrolls_by_observation_without_vlm(tmp_path):
    from gui_rewalk.src.core.evidence_explore.panorama_runtime import PanoramaSession
    from PIL import Image
    import io
    class Driver:
        y=0;actions=[]
        def scope_ok(self):return True
        def capture(self):
            b=io.BytesIO();Image.fromarray(scene()[self.y:self.y+300]).save(b,format='PNG');return b.getvalue()
        def scroll(self,direction):
            self.actions.append(direction);self.y=max(0,min(300,self.y+(100 if direction=='down' else -100)))
        def click(self,point):self.actions.append(('click',point))
    driver=Driver();s=PanoramaSession(driver,tmp_path,[0,0,140,300],max_scrolls=12)
    s.build();s.map.register([dict(key='target',label='Target',function='Open',box=[10,20,100,55])])
    assert driver.y==300
    result=s.goto('target',execute=True)
    assert result['kind']=='clicked_unverified'
    assert driver.actions[-1]==('click',[55,37])
    assert 'up' in driver.actions


def test_scope_loss_never_scrolls_or_clicks(tmp_path):
    from gui_rewalk.src.core.evidence_explore.panorama_runtime import PanoramaSession
    class Driver:
        def scope_ok(self):return False
        def capture(self):raise AssertionError('unowned capture')
        def scroll(self,d):raise AssertionError('unowned scroll')
    with pytest.raises(ValueError,match='scope'):
        PanoramaSession(Driver(),tmp_path,[0,0,100,100]).capture()


def test_existing_catalog_does_not_trigger_another_model_call(tmp_path):
    from gui_rewalk.src.core.evidence_explore.panorama_perception import recognize
    image=scene();p=RegionPanorama(tmp_path,[0,0,140,300]);p.add_view(image[:300],source='frame')
    p.register([dict(key='target',label='Target',function='Open',box=[10,20,100,55])])
    class Agent:
        def _call(self,**kwargs):raise AssertionError('unnecessary paid call')
    with pytest.raises(ValueError,match='already'):recognize(p,Agent())


def test_one_perception_uses_panorama_coordinates_not_screen(tmp_path):
    from gui_rewalk.src.core.evidence_explore.panorama_perception import recognize
    p=RegionPanorama(tmp_path,[20,40,160,340]);p.add_view(scene()[:300],source='frame')
    class Agent:
        calls=0
        def _call(self,**kwargs):
            self.calls+=1
            assert kwargs['screenshots']==[(tmp_path/'panorama.png').read_bytes()]
            return dict(controls=[dict(key='target',label='Target',function='Open',box_1000=[100,100,500,200])],uncertain=[])
    agent=Agent();recognize(p,agent)
    assert agent.calls==1 and p.controls[0]['box']==[14,30,70,60]
    assert p.plan('target',scene()[:300])['point_px']==[62,85]
