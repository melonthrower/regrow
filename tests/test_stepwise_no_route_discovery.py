"""No known return route is ordinary incomplete knowledge, not an exception."""
from copy import deepcopy
from tests.test_stepwise_resume_route import fixture,ROOT
from tests.test_recovery_discovery import mod


def test_multiple_visible_regions_without_route_stay_in_discovery():
    import traversal_scheduler
    flow,records,state=fixture();d=mod('discovery_step')
    records['main']['transitions']=[];records['middle']['transitions']=[]
    state.update(interactive_regions=['main','middle'],required_control='stale',pending_frame='current.png')
    before=deepcopy(records)
    traversal_scheduler.schedule_local_inspection(records,state)
    assert state['next_action_mode']=='explore' and 'inspection_region' not in state
    assert state['working_region']=='menu' and 'required_control' not in state
    assert state['pending_frame']=='current.png' and records==before


def test_stage_driver_reaches_local_discovery_then_normal_action_without_recovery(monkeypatch):
    import locator, traversal_scheduler
    flow,records,state=fixture();d=mod('discovery_step')
    records['main']['transitions']=[];records['middle']['transitions']=[]
    state.update(interactive_regions=['main','middle'],next_action_mode='discover',pending_frame='current.png')
    monkeypatch.setattr(d,'load',lambda run:(None,records,state))
    modes=[]
    def request(root,run):
        mode='local' if state.get('inspection_region') else 'relocate'
        modes.append(mode);return {'mode':mode}
    monkeypatch.setattr(locator,'request_from_run',request)
    original_helper=locator.helper
    monkeypatch.setattr(locator,'helper',lambda name:d if name=='discovery_step' else original_helper(name))
    def commit(root,run,ref):
        if ref=='relocate':traversal_scheduler.schedule_local_inspection(records,state)
        else:
            state.update(next_action_mode='explore',interactive_regions=['main'])
            state.pop('inspection_region',None)
        return {'snapshot':ref}
    from types import SimpleNamespace
    repair=SimpleNamespace(perform=lambda stage,q:{'result':commit(ROOT,'run',q['mode'])})
    locator.run_stage(ROOT,'run',lambda q:(q['mode'],{}),repair=repair)
    assert modes==['relocate']
    before=deepcopy(records)
    q=flow.assemble_context(ROOT,records,state,'menu')
    binding=flow.bind_action_target(q,{'target':'系统返回','action':'back','x':None,'y':None})
    assert binding['status']=='matched' and binding['control_ref'] is None
    assert binding['region_ref']=='main' and binding['working_region']=='menu'
    assert records==before
    assert q['action_ready'] and q['stage']=='action_selection' and q['allow_back']
    assert q['navigation_path'] is None and '自行寻找入口' in q['user_prompt']
    assert state['working_region']=='menu'


def test_blocked_route_source_hands_known_foreground_to_action():
    import traversal_scheduler
    flow,records,state=fixture();d=mod('discovery_step')
    records['middle']['parent_region']='main'
    state.update(interactive_regions=['main','middle'],inspection_region='main',required_control='x',next_action_mode='discover',pending_frame=state['observation']['image'])
    reply={'focus_presence':'not_interactive','foreground':{'description':'菜单打开，侧栏被接管','exception':'none'},'uncertainties':[]}
    assert traversal_scheduler.offer_foreground_navigation(records,state,'main',reply)
    assert state['interactive_regions']==['middle'] and state['next_action_mode']=='explore'
    assert state['working_region']=='menu' and 'required_control' not in state
    q=flow.assemble_context(ROOT,records,state,'menu')
    assert q['action_ready'] and q['allow_back'] and q['navigation_advice']
    assert '菜单打开' in q['user_prompt']


def test_unknown_foreground_still_requires_discovery():
    import traversal_scheduler
    _,records,state=fixture();d=mod('discovery_step')
    state['interactive_regions']=['main']
    before=deepcopy(state)
    assert not traversal_scheduler.offer_foreground_navigation(records,state,'main',{'focus_presence':'not_interactive','foreground':{}})
    assert state==before
