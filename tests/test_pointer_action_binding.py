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


def test_wording_fallback_preserves_actual_ambiguous_visual_hits(action_request):
    first=action_request['backend_candidates'][0]
    action_request['backend_candidates'].append({**first,'id':'duplicate','name':'Other','region_ref':'other'})
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'click','target':'visible arrow','x':85,'y':50,'reason':'visible'})
    candidates=result['association']['candidates']
    assert {c['control'] for c in candidates}=={'gateway','duplicate'}
    assert all(c['position']==[70,40,110,64] and c['basis'] for c in candidates)
    assert result['control_ref'] is None


@pytest.mark.parametrize('ambiguous',[False,True])
def test_input_wording_uses_only_unique_strong_match(action_request,ambiguous):
    action_request['allow_input']=True
    if ambiguous:
        action_request['backend_candidates'].append({**action_request['backend_candidates'][0],'id':'duplicate'})
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'input_text','target':'visible search field',
        'text':'Reset','x':85,'y':50,'reason':'type into the visible field'})
    assert result['control_ref']==(None if ambiguous else 'gateway')
    if not ambiguous:assert result['region_ref']=='form' and result['working_region']=='work'


@pytest.mark.parametrize('change',['weak','outside','unauthorized'])
def test_input_wording_does_not_relax_input_or_visual_requirements(action_request,change):
    action_request['allow_input']=change!='unauthorized'
    if change=='weak':action_request['backend_candidates'][0]['image_quality']='uncertain'
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'input_text','target':'visible search field',
        'text':'Reset','x':5 if change=='outside' else 85,'y':50,'reason':'type'})
    assert result['control_ref'] is None
    if change=='unauthorized':assert result['status']=='unresolved'


@pytest.mark.parametrize('competitor',['at_point','outside','no_candidates','unusable'])
def test_point_fallback_does_not_discard_competing_object(action_request,monkeypatch,competitor):
    """A weaker child match is uncertainty, not proof that the container owns a drag."""
    broad=action_request['backend_candidates'][0]
    child={**broad,'id':'child','name':'Scrollbar'}
    action_request['backend_candidates'].append(child)
    box=[80,40,90,65] if competitor!='outside' else [120,40,130,65]
    def match(c,frame):
        if c['id']=='gateway':return {'accepted':True,'box':[70,40,110,64],'candidates':[]}
        return {'accepted':False,'box':None if competitor=='unusable' else box,
                'candidates':[{'box':box}] if competitor in ('at_point','outside') else []}
    flow=mod('stepwise_flow')
    # The binder independently loads the matcher module.
    import importlib.util
    original_loader=importlib.util.spec_from_file_location
    def loader(name,path,*args,**kwargs):
        spec=original_loader(name,path,*args,**kwargs)
        if name=='stepwise_image_match':
            execute=spec.loader.exec_module
            def load(module):execute(module);module.match_control=match
            spec.loader.exec_module=load
        return spec
    monkeypatch.setattr(importlib.util,'spec_from_file_location',loader)
    proposal={'action':'drag','target':'right side thumb','x':85,'y':50,'end_x':85,'end_y':85,'reason':'drag the visible thumb'}
    result=flow.bind_action_target(action_request,proposal)
    if competitor=='at_point':
        assert result['status']=='unresolved'
        assert result['control_ref'] is None
        assert 'Scrollbar' in result['reason'] and 'Gateway' in result['reason']
    else:assert result['status']=='matched' and result['control_ref']=='gateway'
    # An explicit object name follows its existing validation path.
    named=flow.bind_action_target(action_request,{**proposal,'target':'Gateway'})
    assert named['status']=='matched' and named['control_ref']=='gateway'


@pytest.mark.parametrize('weak_path',['disclosed','best_box'])
@pytest.mark.parametrize('other',['strong_at_point','strong_elsewhere','weak','missing'])
def test_weak_named_target_cannot_override_strong_other_object(action_request,monkeypatch,weak_path,other):
    broad=action_request['backend_candidates'][0]
    child={**broad,'id':'child','name':'Scrollbar'}
    action_request['backend_candidates'].append(child)
    if other=='missing':broad['image']=None
    box=[80,40,90,65]
    action_request['visual_choices']={'child':[{'box':box}]} if weak_path=='disclosed' else {}
    def match(c,frame):
        if c['id']=='gateway':
            return {'accepted':other!='weak','box':[120,40,160,64] if other=='strong_elsewhere' else [70,40,110,64],'candidates':[]}
        return {'accepted':False,'box':box,'candidates':[{'box':box}] if weak_path=='disclosed' else []}
    import importlib.util
    original_loader=importlib.util.spec_from_file_location
    def loader(name,path,*args,**kwargs):
        spec=original_loader(name,path,*args,**kwargs)
        if name=='stepwise_image_match':
            execute=spec.loader.exec_module
            def load(module):execute(module);module.match_control=match
            spec.loader.exec_module=load
        return spec
    monkeypatch.setattr(importlib.util,'spec_from_file_location',loader)
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'drag','target':'Scrollbar',
        'x':85,'y':50,'end_x':85,'end_y':85,'reason':'I see a scrollbar'})
    if other=='strong_at_point':
        assert result['status']=='unresolved' and result['control_ref'] is None
        assert 'Gateway' in result['reason'] and 'Scrollbar' in result['reason']
    else:assert result['status']=='matched' and result['control_ref']=='child'
