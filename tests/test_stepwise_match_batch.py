import numpy as np
from PIL import Image
from tests.test_recovery_discovery import mod


def test_repeated_control_template_is_scanned_once(tmp_path,monkeypatch):
    m=mod('history_matching');matcher=mod('image_match')
    pixels=np.random.default_rng(1).integers(0,256,(30,40,3),dtype=np.uint8)
    path=tmp_path/'template.png';Image.fromarray(pixels).save(path)
    observation={'image':str(path),'image_quality':'clear','image_quality_reason':'test capture'}
    records={'r1':{'controls':{cid:{'observations':[observation]} for cid in ['c1','c2']}}}
    import image_match
    calls=[];original=matcher.SceneMatcher.locate_pixels
    def locate(self,template):
        calls.append(1)
        return original(self,template)
    monkeypatch.setattr(matcher.SceneMatcher,'locate_pixels',locate)
    monkeypatch.setattr(image_match,'SceneMatcher',matcher.SceneMatcher)
    rows=m.scan(records,tmp_path,path)
    assert len(calls)==1
    assert rows[0]['eligible_controls']==2 and rows[0]['matched_controls']==1


def test_batch_matching_preserves_exact_result(tmp_path):
    m=mod('image_match')
    pixels=np.random.default_rng(2).integers(0,256,(40,50,3),dtype=np.uint8)
    frame=np.zeros((150,180,3),dtype=np.uint8);frame[50:90,60:110]=pixels
    Image.fromarray(pixels).save(tmp_path/'template.png');Image.fromarray(frame).save(tmp_path/'frame.png')
    expected=m.locate(tmp_path/'template.png',tmp_path/'frame.png')
    assert m.SceneMatcher(tmp_path/'frame.png').locate_pixels(pixels)==expected
    assert expected['accepted']


def test_distinct_pixels_and_region_identities_are_not_dropped(tmp_path):
    m=mod('history_matching');records={}
    frame=np.random.default_rng(8).integers(0,256,(80,120,3),dtype=np.uint8)
    path=tmp_path/'frame.png';Image.fromarray(frame).save(path)
    for i,rid in enumerate(['r1','r2']):
        crop=tmp_path/(rid+'.png')
        Image.fromarray(frame[10:40,10+i*60:40+i*60]).save(crop)
        records[rid]={'controls':{'c':{'observations':[{'image':str(crop),
            'image_quality':'clear','image_quality_reason':'test capture'}]}}}
    rows=m.scan(records,tmp_path,path)
    assert {r['region'] for r in rows}=={'r1','r2'}
    assert all(r['matched_controls']==1 for r in rows)
