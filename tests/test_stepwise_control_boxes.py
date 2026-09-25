import importlib.util
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
sys.path.insert(0,str(ROOT))
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def box(l,t,r,b):return dict(zip(('left','top','right','bottom'),(l,t,r,b)))

def test_observation_keeps_both_boxes():
    proposal={'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','bbox':box(10,20,210,60),'click_bbox':box(175,25,205,55)}
    row=module('stepwise_flow').control_observation(proposal,{'source_call':'test'})
    assert row['bbox']==proposal['bbox']
    assert row['click_bbox']==proposal['click_bbox']

def test_identity_match_projects_click_area_and_rejects_label(tmp_path):
    identity=Image.new('RGB',(200,40),'white');d=ImageDraw.Draw(identity)
    d.text((3,8),'Automatic Screen Lock',fill='black');d.rectangle((165,5,195,35),fill='orange')
    identity.save(tmp_path/'control.png')
    scene=Image.new('RGB',(400,160),'#aaaaaa');scene.paste(identity,(70,80));scene.save(tmp_path/'frame.png')
    c={'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','id':'c','name':'Lock','image':str(tmp_path/'control.png'),'bbox':box(10,20,210,60),'click_bbox':box(175,25,205,55)}
    q={'source':{'region':'r','observation':'o'},'image_refs':[str(tmp_path/'frame.png')],'backend_candidates':[c]}
    choices=module('visual_choices');hit=choices.match_control(c,q['image_refs'][0])
    assert hit['identity_box']==[70,80,270,120]
    assert hit['box']==[235,85,265,115]
    flow=module('stepwise_flow');q=choices.prepare(q)
    action={'action':'click','target':'Lock','x':250,'y':100,'reason':'toggle'}
    assert flow.bind_action_target(q,action)['status']=='matched'
    assert flow.bind_action_target(q,{**action,'x':90})['status']=='unresolved'

def test_registration_saves_identity_and_click_crops(tmp_path):
    image=Image.new('RGB',(240,100),'white');image.save(tmp_path/'frame.png')
    evidence={'source_call':'new','source_field':'controls/0'}
    r={'id':'r','observations':[{'evidence':{'source_field':'regions/0'}}],
       'controls':{'c':{'observations':[{'evidence':evidence}]}}}
    reply={'regions':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','bbox':box(0,0,240,100)}],
           'controls':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','bbox':box(10,20,210,60),'click_bbox':box(175,25,205,55),'icon_bbox':None}]}
    module('register_update').save_region_images({'r':r},['r'],reply,'new',tmp_path,'frame.png',tmp_path/'snapshot',tmp_path/'temp')
    row=r['controls']['c']['observations'][0]
    with Image.open(tmp_path/'temp/regions/r'/row['image']) as im:assert im.size==(200,40)
    with Image.open(tmp_path/'temp/regions/r'/row['click_image']) as im:assert im.size==(30,30)

def test_click_projection_scales_and_unknown_does_not_use_label():
    m=module('visual_choices')
    c={'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','bbox':box(10,20,210,60),'click_bbox':box(175,25,205,55)}
    assert m.click_box(c,[50,60,450,140])==[380,70,440,130]
    assert m.click_box({**c,'click_bbox':None},[50,60,450,140]) is None

def test_new_discovery_schema_requires_both_boxes():
    import json
    m=module('control_records')
    for name in ('首屏观察','动作后更新','动作后Region增量'):
        schema=json.loads((ROOT/'遍历prompt/输出格式'/f'{name}.schema').read_text())
        item=m.extend_schema(schema,required=True)['properties']['controls']['items']
        assert {'bbox','click_bbox'} <= set(item['required'])
        assert 'click_bbox' in item['properties']


def test_click_row_can_extend_beyond_identity_label():
    c={'bbox':box(82,120,231,163),'click_bbox':box(70,119,312,164)}
    assert module('visual_choices').click_box(c,[82,120,231,163])==[70,119,312,164]
    assert module('visual_choices').click_box(c,[182,220,331,263])==[170,219,412,264]
