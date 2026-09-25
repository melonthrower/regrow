import numpy as np
from PIL import Image
from tests.test_stepwise_resume_route import load


def request(tmp_path):
    pixels=np.random.default_rng(12).integers(0,256,(180,180,3),dtype=np.uint8)
    frame=tmp_path/'frame.png';Image.fromarray(pixels).save(frame)
    entries=[]
    for name,cid,box in [('样式选项','style',(10,10,80,80)),('返回','back',(100,100,160,160))]:
        crop=tmp_path/(cid+'.png');Image.fromarray(pixels[box[1]:box[3],box[0]:box[2]]).save(crop)
        entries.append({'id':cid,'name':name,'image':str(crop)})
    return {'action_ready':True,'source':{'region':'r','observation':'o'},'image_refs':[str(frame)],'backend_candidates':entries}


def test_rephrased_click_uses_unique_strong_visual_match(tmp_path):
    q=request(tmp_path);m=load()
    bound=m.bind_action_target(q,{'target':'样式选项 Analog','action':'click','x':40,'y':40})
    assert bound['status']=='matched' and bound['control_ref']=='style'
    assert bound['basis']=='unique strong visual match at model point; target wording differed'


def test_known_name_conflict_and_blank_space_execute_without_false_binding(tmp_path):
    q=request(tmp_path);m=load()
    assert m.bind_action_target(q,{'target':'返回','action':'click','x':40,'y':40})['control_ref'] is None
    assert m.bind_action_target(q,{'target':'关闭菜单外空白','action':'click','x':90,'y':90})['control_ref'] is None
    assert m.bind_action_target(q,{'target':'','action':'click','x':40,'y':40})['control_ref'] is None


def test_ambiguous_registered_objects_do_not_get_arbitrary_identity(tmp_path):
    q=request(tmp_path);m=load();q['backend_candidates'].append({**q['backend_candidates'][0],'id':'duplicate','name':'另一个名称'})
    assert m.bind_action_target(q,{'target':'样式选择','action':'click','x':40,'y':40})['control_ref'] is None


def test_coordinate_fallback_keeps_evidence_and_rejects_invalid_position(tmp_path):
    q=request(tmp_path);m=load()
    p={'target':'关闭菜单外空白','action':'click','x':90,'y':90,'reason':'关闭菜单'}
    b=m.bind_action_target(q,p)
    assert b['status']=='matched' and b['control_ref'] is None
    assert b['association']['status']=='unconfirmed' and b['association']['target']==p['target']
    assert m.bind_action_target(q,{**p,'x':-1})['status']=='unresolved'
