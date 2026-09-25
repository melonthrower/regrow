import numpy as np
from PIL import Image
from tests.test_recovery_discovery import mod


def test_duplicate_region_pixels_are_scanned_once(tmp_path):
    m=mod('region_identity');folder=tmp_path/'regions/r1';folder.mkdir(parents=True)
    pixels=np.random.default_rng(1).integers(0,256,(30,40,3),dtype=np.uint8)
    Image.fromarray(pixels).save(folder/'a.png');Image.fromarray(pixels).save(folder/'b.png')
    records={'r1':{'observations':[{'image':'a.png'},{'image':'b.png'}]}}
    assert len(list(m.templates(records,tmp_path)))==1


def test_batch_matching_preserves_exact_result(tmp_path):
    m=mod('image_match')
    pixels=np.random.default_rng(2).integers(0,256,(40,50,3),dtype=np.uint8)
    frame=np.zeros((150,180,3),dtype=np.uint8);frame[50:90,60:110]=pixels
    Image.fromarray(pixels).save(tmp_path/'template.png');Image.fromarray(frame).save(tmp_path/'frame.png')
    expected=m.locate(tmp_path/'template.png',tmp_path/'frame.png')
    assert m.SceneMatcher(tmp_path/'frame.png').locate_pixels(pixels)==expected
    assert expected['accepted']


def test_distinct_pixels_and_region_identities_are_not_dropped(tmp_path):
    m=mod('region_identity');records={}
    for rid in ['r1','r2']:
        folder=tmp_path/'regions'/rid;folder.mkdir(parents=True)
        for i in range(2):
            pixels=np.zeros((15,20,3),dtype=np.uint8);pixels[0,0]=i
            Image.fromarray(pixels).save(folder/f'{i}.png')
        records[rid]={'observations':[{'image':'0.png'},{'image':'1.png'}]}
    assert len(list(m.templates(records,tmp_path)))==4
    assert {rid for rid,*_ in m.templates(records,tmp_path,skip={'r1'})}=={'r2'}
