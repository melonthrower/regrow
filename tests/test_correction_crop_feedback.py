from copy import deepcopy
import json
import pytest
from PIL import Image
from tests.test_recovery_discovery import mod


def test_feedback_uses_rejected_box_and_keeps_original_frames(tmp_path, monkeypatch):
    from tests.test_recovery_discovery import ROOT
    monkeypatch.syspath_prepend(str(ROOT))
    folder=tmp_path/'action_attempts/a1';folder.mkdir(parents=True)
    frame=folder/'after.png';Image.new('RGB',(200,300),'white').save(frame)
    job={'stage':'update','attempt':'a1','call':'12','path':'repair_episodes/e/episode.json',
         'identity_controls':[0], 'candidate':{'controls':[{'name':'time','bbox':{'left':10,'top':20,'right':100,'bottom':80}}]},
         'request':{'screenshots':[str(frame)]}}
    q={'screenshots':[str(frame)],'image_refs':[str(frame)],'user_prompt':'full original context','dynamic_prompt':'full original context'}
    before=deepcopy(job)
    mod('correction_crop_feedback').attach(tmp_path,job,q)
    assert job==before and q['screenshots'][0]==str(frame) and len(q['screenshots'])==2
    meta=q['identity_crop_evidence'];assert meta['controls'][0]['bbox']==job['candidate']['controls'][0]['bbox']
    crop=Image.open(tmp_path/meta['controls'][0]['crop']);assert crop.size==(90,60)
    assert crop.getpixel((0,0))==(255,255,255)
    assert q['user_prompt'].startswith('full original context')
    assert Image.open(q['screenshots'][-1]).width>0


def test_review_indices_are_evidence_bound_and_invalid_indices_rejected(tmp_path,monkeypatch):
    from tests.test_recovery_discovery import ROOT
    from tests.test_update_semantic_review import fixture,verdict
    monkeypatch.syspath_prepend(str(ROOT));m=mod('update_semantic_review');job=fixture(tmp_path)
    job['candidate']={'controls':[{'name':'time','bbox':None}]}
    with pytest.raises(RuntimeError):m.check(tmp_path,job,lambda e:{**verdict(False),'identity_controls':[9]})
    with pytest.raises(m.Rejected) as caught:m.check(tmp_path,job,lambda e:{**verdict(False),'identity_controls':[0]})
    assert caught.value.identity_controls==[0]


def test_missing_box_does_not_describe_original_frame_as_contact_sheet(tmp_path,monkeypatch):
    from tests.test_recovery_discovery import ROOT
    monkeypatch.syspath_prepend(str(ROOT))
    folder=tmp_path/'action_attempts/a1';folder.mkdir(parents=True)
    frame=folder/'after.png';Image.new('RGB',(20,30)).save(frame)
    job={'stage':'update','attempt':'a1','path':'repair_episodes/e/episode.json','identity_controls':[0],
         'candidate':{'controls':[{'bbox':None}]},'request':{'screenshots':[str(frame)]}}
    q={'screenshots':[str(frame)],'user_prompt':'original'}
    mod('correction_crop_feedback').attach(tmp_path,job,q)
    assert q['screenshots']==[str(frame)] and 'image_number' not in q['identity_crop_evidence']
    assert '最后追加图的左列' not in q['user_prompt']
    assert q['identity_crop_evidence']['controls'][0]['unavailable']
