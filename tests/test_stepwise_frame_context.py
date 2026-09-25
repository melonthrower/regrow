from copy import deepcopy
from PIL import Image
from tests.test_recovery_discovery import mod, ROOT


def test_each_image_has_actual_original_coordinate_range(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    Image.new('RGB',(1080,2340)).save(tmp_path/'current.png')
    Image.new('RGB',(800,600)).save(tmp_path/'before.png')
    q={'user_prompt':'原任务','screenshots':['before.png','current.png']}
    original=deepcopy(q)
    sent=mod('recover_external').with_frame_context(q,tmp_path)
    assert q==original
    assert '第1张：800×600' in sent['user_prompt']
    assert '第2张：1080×2340' in sent['user_prompt']
    assert 'right≤1080，0≤top<bottom≤2340' in sent['user_prompt']
