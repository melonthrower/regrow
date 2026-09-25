"""Background pixels must not contribute to accepted foreground vote counts."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from tests.test_recovery_discovery import mod, ROOT


@pytest.fixture(autouse=True)
def module_path(monkeypatch):monkeypatch.syspath_prepend(str(ROOT))


def test_background_only_control_gets_zero_foreground_votes(tmp_path):
    pixels=np.random.default_rng(42).integers(0,256,(40,40,3),dtype=np.uint8)
    template=tmp_path/'button.png';Image.fromarray(pixels).save(template)
    screen=Image.new('RGB',(200,100),'white');screen.paste(Image.fromarray(pixels),(10,10));frame=tmp_path/'frame.png';screen.save(frame)
    rs={'r':{'name':'background','controls':{'c':{'name':'button','observations':[{'image':str(template),'image_quality':'clear','image_quality_reason':'fixture'}]}},'observations':[]}}
    m=mod('history_matching')
    raw=m.scan(rs,tmp_path,frame)[0];assert raw['matched_controls']==1 and not raw['foreground_confirmed']
    confirmed=m.scan(rs,tmp_path,frame,scope={'interactive_areas':[[100,0,200,100]],'excluded_areas':[]})[0]
    assert confirmed['matched_controls']==0 and confirmed['foreground_confirmed']
    full=m.scan(rs,tmp_path,frame,scope={'interactive_areas':[[0,0,200,100]],'excluded_areas':[[5,5,60,60]]})[0]
    assert full['matched_controls']==1


def test_foreground_unknown_has_no_public_vote_count(tmp_path):
    m=mod('history_matching');row={'region':'r','matched_controls':9,'eligible_controls':9,'total_controls':9,'anchors':[],
                                 'whole':{'accepted':False},'foreground_confirmed':False}
    q=m.attach({'screenshots':['current.png'],'user_prompt':'{}'},{'r':{'controls':{},'observations':[]}},[row],{'Panel':'r'})
    assert json.loads(q['user_prompt'])['历史匹配对照']['候选匹配线索'][0]['前景独立控件命中数'] is None


def test_foreground_bounds_and_empty_uncertainty_are_checked(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(100,100)).save(frame);m=mod('foreground_scope')
    with pytest.raises(ValueError,match='不确定性'):m.validate({'interactive_areas':[],'excluded_areas':[]},frame)
    with pytest.raises(ValueError,match='超出'):m.validate({'interactive_areas':[{'bbox':dict(left=0,top=0,right=101,bottom=50)}],'excluded_areas':[]},frame)
    assert m.contains([0,0,10,10],{'interactive_areas':[[0,0,100,100]],'excluded_areas':[[5,5,20,20]]})


def test_foreground_anchors_cannot_extrapolate_a_background_local_surface(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(200,100)).save(frame)
    old=tmp_path/'old.png';Image.new('RGB',(100,80)).save(old)
    r={'observations':[{'image':str(old),'image_quality':'clear','image_quality_reason':'fixture'}],
       'controls':{str(i):{'observations':[{'image':f'c{i}','image_quality':'clear','image_quality_reason':'fixture'}]} for i in range(2)}}
    def match(path,scene=None):
        if path==str(old):return {'accepted':False}
        i=int(path[1:]);x=5+20*i if scene is not None else 15+20*i
        return {'accepted':True,'score':1,'box':[x,15,x+10,25]}
    result=mod('history_matching').match_region('r',r,match,frame,scope={'interactive_areas':[[0,0,60,40]],'excluded_areas':[]})
    assert result['matched_controls']==2 and not result['strong'] and result['bounds'] is None


def test_control_identity_boxes_reject_local_coordinates():
    m=mod('foreground_scope')
    scope={'interactive_areas':[[239,54,1109,745]],'excluded_areas':[]}
    owner={'bbox':dict(left=239,top=54,right=1109,bottom=101)}
    bad={'region_index':0,'bbox':dict(left=6,top=5,right=42,bottom=41),'icon_bbox':None}
    with pytest.raises(ValueError,match='控件身份框'):
        m.validate_control_boxes({'regions':[owner],'controls':[bad]},scope)
    good={**bad,'bbox':dict(left=245,top=59,right=281,bottom=95)}
    m.validate_control_boxes({'regions':[owner],'controls':[good]},scope)
    m.validate_control_boxes({'regions':[owner],'controls':[{**bad,'bbox':None}]},scope)
