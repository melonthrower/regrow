import numpy as np
import pytest
from PIL import Image
from tests.test_recovery_discovery import mod, ROOT

@pytest.fixture
def action_request(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    crop=np.random.default_rng(45).integers(0,255,(24,40,3),dtype=np.uint8)
    frame=np.zeros((120,200,3),dtype=np.uint8);frame[40:64,70:110]=crop
    Image.fromarray(frame).save(tmp_path/'frame.png');Image.fromarray(crop).save(tmp_path/'control.png')
    return {'source':{'region':'navigation','observation':'obs','working_region':'work'},'image_refs':[str(tmp_path/'frame.png')],
            'backend_candidates':[{'id':'gateway','region_ref':'form','name':'Gateway','image':str(tmp_path/'control.png'),
                'image_quality':'clear','image_quality_reason':'unobscured fixture'} ]}

@pytest.mark.parametrize('action',['hover','drag','click'])
def test_pointer_actions_bind_actual_control_owner(action_request,action):
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':action,'target':'Gateway','x':85,'y':50,'end_x':120,'end_y':80,'reason':'visible Gateway'})
    assert result['status']=='matched'
    assert (result['region_ref'],result['control_ref'])==('form','gateway')
    assert result['working_region']=='work'

@pytest.mark.parametrize('action',['hover','drag'])
def test_unknown_pointer_target_keeps_association_gap(action_request,action):
    action_request['backend_candidates']=[]
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':action,'target':'unknown','x':85,'y':50,'end_x':120,'end_y':80,'reason':'visible'})
    assert result['status']=='matched'
    assert result['control_ref'] is None
    assert result['association']['status']=='unconfirmed'

@pytest.mark.parametrize('end_x,end_y',[(250,50),(85,50),(True,80)])
def test_drag_invalid_endpoint_is_not_dispatched(action_request,end_x,end_y):
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'drag','target':'Gateway','x':85,'y':50,'end_x':end_x,'end_y':end_y,'reason':'visible'})
    assert result['status']=='unresolved'


def test_unknown_wording_never_guesses_owner_from_point(action_request):
    result=mod('action_binding').bind_action_target(action_request,{'action':'click','target':'visible arrow','x':85,'y':50})
    assert result['control_ref'] is None and result['association']['candidates']==[]


def test_explicit_identity_ignores_missing_click_area_and_other_geometry(action_request):
    c=action_request['backend_candidates'][0]
    c.update(image=None,click_bbox=None)
    action_request['backend_candidates'].append({**c,'id':'other','name':'Gateway','region_ref':'other'})
    proposal={'action':'click','target':'form/gateway','x':5,'y':5}
    result=mod('action_binding').bind_action_target(action_request,proposal)
    assert (result['region_ref'],result['control_ref'])==('form','gateway')
    ambiguous=mod('action_binding').bind_action_target(action_request,{**proposal,'target':'Gateway'})
    assert ambiguous['status']=='unresolved'
    outside=mod('action_binding').bind_action_target(action_request,{**proposal,'x':250})
    assert outside['status']=='unresolved'


def test_explicit_preparation_keeps_actual_owner(action_request):
    action_request.update(preparation_allowed=True,allow_input=True)
    action_request['source'].update(task_type='single_action',task_control='submit',task_action='click',task_region='form')
    result=mod('action_binding').bind_action_target(action_request,{'action':'input_text','target':'form/gateway','text':'London','x':5,'y':5})
    assert result['preparatory_action'] and result['control_ref']=='gateway' and result['task_region']=='form'
