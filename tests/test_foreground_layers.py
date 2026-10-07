"""Only positive interactive areas define the current foreground."""
from PIL import Image
from tests.test_foreground_scope import mod, ROOT


def test_original_untyped_dialog_accepts_foreground_only(tmp_path):
    m=mod('foreground_scope');frame=tmp_path/'frame.png';Image.new('RGB',(1200,800)).save(frame)
    def area(box):return {'bbox':dict(zip(('left','top','right','bottom'),box)),'reason':'fixture'}
    report={'interactive_areas':[area([473,105,875,694])],'excluded_areas':[area([238,54,1109,745])]}
    scope=m.validate(report,frame)
    assert scope=={'interactive_areas':[[473,105,875,694]]}  # Old reply evidence is not propagated.
    assert m.contains([473,105,875,694],scope)
    assert m.contains([500,200,800,250],scope)
    assert not m.contains([250,60,300,90],scope)
    m.validate_control_boxes({'regions':[area([473,105,875,694])], 'controls':[{'region_index':0,**area([500,200,800,250])}]},scope)


def test_normal_update_schema_only_requests_interactive_areas():
    q=mod('result_updater').build_update_request(ROOT,{},['before.png','after.png'])
    foreground=q['response_schema']['properties']['foreground']
    assert 'excluded_areas' not in foreground['properties']
    assert 'excluded_areas' not in foreground['required']
    assert 'excluded_areas' not in q['system_prompt']
    row=foreground['properties']['interactive_areas']['items']
    assert set(row['properties'])=={'bbox','reason'}
    assert set(row['required'])=={'bbox','reason'}
