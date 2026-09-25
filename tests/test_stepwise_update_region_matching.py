from copy import deepcopy
from pathlib import Path
import numpy as np
from PIL import Image
from tests.test_stepwise_region_tasks import tasks


def case(tmp_path):
    m=tasks().helper('region_identity')
    pixels=np.random.default_rng(4).integers(0,256,(80,100,3),dtype=np.uint8)
    Image.fromarray(pixels).save(tmp_path/'region.png')
    frame=np.zeros((260,300,3),dtype=np.uint8);frame[140:220,170:270]=pixels
    Image.fromarray(frame).save(tmp_path/'after.png')
    records={'r0001':{'id':'r0001','name':'菜单','observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':str(tmp_path/'region.png')}],
                        'controls':{'c0001':{'name':'Settings'}}}}
    reply={'regions':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','name':'其他页面菜单','previous_name':'','bbox':{'left':170,'top':140,'right':270,'bottom':220}}],
           'controls':[{'region_index':0,'name':'Settings','previous_name':''}]}
    return m,records,reply


def test_identical_region_pixels_do_not_override_model_identity(tmp_path):
    m,records,reply=case(tmp_path);original=deepcopy(reply)
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized == original and not audit
    assert reply == original


def test_changed_pixels_not_forced_to_match(tmp_path):
    m,records,reply=case(tmp_path)
    Image.new('RGB',(300,260),'white').save(tmp_path/'after.png')
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized==reply and not audit


def test_multiple_identical_historical_regions_not_arbitrarily_selected(tmp_path):
    m,records,reply=case(tmp_path);records['r0002']=deepcopy(records['r0001']);records['r0002']['id']='r0002'
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized==reply and not audit


def test_region_without_control_templates_has_no_visual_votes(tmp_path):
    import history_matching
    _,records,_=case(tmp_path)
    hits=history_matching.scan(records,tmp_path,tmp_path/'after.png')
    assert len(hits)==1 and hits[0]['matched_controls']==0
    assert hits[0]['bounds'] is None


def test_crop_with_different_menu_content_not_automatically_reused(tmp_path):
    m,records,reply=case(tmp_path)
    with Image.open(tmp_path/'after.png') as im:pixels=np.array(im)
    pixels[160:180,180:240]=255
    Image.fromarray(pixels).save(tmp_path/'after.png')
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized==reply and not audit
