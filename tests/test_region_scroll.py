"""Region scrolling uses the current screenshot without a cached Region box."""
import json
import pytest
from PIL import Image
from tests.test_recovery_discovery import mod


def scene(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(120,100),'white').save(frame)
    scope=mod('foreground_scope');stamp=scope.fingerprint(frame)
    folder=tmp_path/'foreground_scopes';folder.mkdir()
    (folder/(stamp+'.json')).write_text(json.dumps({'frame_sha256':stamp,'scope':{
        'interactive_areas':[[0,0,120,100]],'excluded_areas':[], 'region_bounds':{'r1':[10,10,110,90]}}}))
    state={'interactive_regions':['r1'],'observation':{'id':'o1','image':str(frame)}}
    q={'allow_scroll':True,'source':{'region':'r1','observation':'o1'},'image_refs':[str(frame)]}
    return q,state,frame


def test_normal_current_and_refreshed_scroll_work_without_cached_bounds(tmp_path):
    from tests.test_inventory_scroll_progress import plan_scroll, ROOT
    m,run,records,state,_,_=plan_scroll(tmp_path)
    frame=run/'test-frame.png';Image.new('RGB',(120,100),'white').save(frame)
    def with_frame(records,state,*args):state['observation']['image']='test-frame.png'
    m.helper('discovery_step').publish(run,'test-observed-frame',with_frame)
    _,records,state=m.helper('discovery_step').load(run)
    q=m.helper('stepwise_flow').assemble_current_context(ROOT,run,'r1')
    assert q['response_schema']['properties']['action']['enum'].__contains__('scroll')
    refreshed=m.helper('repair_stages').refresh(ROOT,run,{'stage':'action','request':q})
    assert refreshed['image_refs']==[str(frame.resolve())]
    assert m.helper('stepwise_flow').bind_action_target(refreshed,
        {'action':'scroll','x':50,'y':80,'end_x':50,'end_y':20})['status']=='matched'


def test_scroll_binds_without_region_template_or_cached_boundary(tmp_path):
    q,state,_=scene(tmp_path)
    proposal={'action':'scroll','x':50,'y':80,'end_x':50,'end_y':20}
    binding=mod('stepwise_flow').bind_action_target(q,proposal)
    assert binding['status']=='matched' and binding['control_ref'] is None
    assert binding['region_ref']=='r1'
    proposal['end_y']=95
    assert mod('stepwise_flow').bind_action_target(q,proposal)['status']=='matched'
    proposal['end_y']=500
    assert mod('stepwise_flow').bind_action_target(q,proposal)['status']=='unresolved'
    q['platform']='desktop'
    assert mod('stepwise_flow').bind_action_target(q,proposal)['status']=='matched'


def test_new_frame_does_not_require_reobserving_region_bounds(tmp_path):
    q,state,frame=scene(tmp_path)
    q['region_scroll_bounds']={'region':'old','observation':'old','frame_sha256':'old','box':[0,0,1,1]}
    Image.new('RGB',(120,100),'black').save(frame)
    assert mod('stepwise_flow').bind_action_target(q,
        {'action':'scroll','x':50,'y':80,'end_x':50,'end_y':20})['status']=='matched'


@pytest.mark.parametrize('change',['missing_frame','two_frames','not_allowed','outside','stationary','not_integer'])
def test_scroll_keeps_current_image_and_coordinate_checks(tmp_path,change):
    q,_,frame=scene(tmp_path)
    p={'action':'scroll','x':50,'y':80,'end_x':50,'end_y':20}
    if change=='missing_frame':frame.unlink()
    elif change=='two_frames':q['image_refs']*=2
    elif change=='not_allowed':q['allow_scroll']=False
    elif change=='outside':p['x']=120
    elif change=='stationary':p['end_y']=80
    elif change=='not_integer':p['x']=True
    assert mod('stepwise_flow').bind_action_target(q,p)['status']=='unresolved'


@pytest.mark.parametrize('blocked', [None, 'different_task', 'missing_scope', 'identity_gap'])
def test_region_observation_can_resume_partial_scroll_without_control_completion(tmp_path, blocked):
    from tests.test_inventory_scroll_progress import plan_scroll, ROOT
    m,run,records,state,_,_=plan_scroll(tmp_path)
    q=m.attach(ROOT,records,state,'r1',{'progress':{}})
    frame=run/'observed.png';Image.new('RGB',(120,100),'white').save(frame)
    def observation(records,state,*args):
        state.update(next_action_mode='discover',reason='locate_local_controls',control_inventory_status='partial')
        state['observation'].update(image=str(frame),control_refs=[])
    m.helper('discovery_step').publish(run,'test-region-observed',observation)
    scope=m.helper('foreground_scope');stamp=scope.fingerprint(frame)
    folder=run/'foreground_scopes';folder.mkdir()
    (folder/(stamp+'.json')).write_text(json.dumps({'frame_sha256':stamp,'scope':{
        'interactive_areas':[[0,0,120,100]],'excluded_areas':[],'region_bounds':{'r1':[0,0,120,100]}}}))
    if blocked=='different_task':q['source']['task_name']='另一任务'
    elif blocked=='missing_scope':(folder/(stamp+'.json')).unlink()
    elif blocked=='identity_gap':
        m.helper('discovery_step').publish(run,'test-identity-gap',
            lambda records,state,*args:state.update(discovery_completion={'pending':[{'unresolved':'identity'}]}))
    if blocked == 'different_task':
        assert not m.helper('inventory_scroll').resume_after_region_observation(run,q,'x')
        assert m.helper('discovery_step').load(run)[2]['next_action_mode']=='discover'
        return
    assert m.helper('inventory_scroll').resume_after_region_observation(run,q,'x')
    _,after,state=m.helper('discovery_step').load(run)
    assert state['next_action_mode']=='explore'
    assert state['control_inventory_status']=='partial' and state['observation']['control_refs']==[]
    assert after['r1']['task_inventory']==records['r1']['task_inventory']
    assert after['r1']['tasks']==records['r1']['tasks']
    assert m.helper('stepwise_flow').assemble_current_context(ROOT,run,'r1')['response_schema']['properties']['action']['enum'].__contains__('scroll')
