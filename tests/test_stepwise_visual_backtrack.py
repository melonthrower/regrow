from pathlib import Path
import importlib.util
from types import SimpleNamespace
from copy import deepcopy
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec=importlib.util.spec_from_file_location('visual_backtrack',ROOT/'visual_backtrack.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_repeated_icon_uses_historical_position(monkeypatch):
    m=module(monkeypatch)
    old={'accepted':True,'box':[80,10,100,30]}
    new={'accepted':False,'candidates':[{'box':[5,10,25,30]},{'box':[80,10,100,30]}]}
    assert m.choose_position(old,new,(100,100),(100,100))==[80,10,100,30]
    new['candidates'].append({'box':[79,11,99,31]})
    assert m.choose_position(old,new,(100,100),(100,100)) is None


def setup(tmp_path,monkeypatch):
    m=module(monkeypatch);run=tmp_path/'run';run.mkdir();snap=run/'knowledge_snapshots/initial';snap.mkdir(parents=True)
    from PIL import Image
    for name in ['old_before','old_after','control','current']:
        Image.new('RGB',(100,100)).save(run/(name+'.png'))
    records={'a':{'controls':{'c':{'name':'Menu','observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':str(run/'control.png'),'bbox':{'left':0,'top':0,'right':100,'bottom':100},'click_bbox':{'left':0,'top':0,'right':100,'bottom':100}}]}},
        'actions':{'old':{'evidence':{'before_image':str(run/'old_before.png'),'after_image':str(run/'old_after.png')},'interactive_regions':['b']} }},
        'b':{'controls':{},'actions':{}}}
    state={'working_region':'b','next_action_mode':'explore','interactive_regions':['a'],'observation':{'id':'old','control_refs':['c']}}
    for rid,r in records.items():r.update(id=rid,name=rid,observations=[],transitions=[],tasks={})
    records['a']['actions']['old'].update(control='c',operation='click',delivery='executed_receipt_zero',result={'exception':'none'})
    records['a']['observations']=[{'image':str(run/'control.png'),'image_quality':'clear','image_quality_reason':'test source region'}]
    monkeypatch.setattr(m.image_match,'locate',lambda *a:{'accepted':True,'box':[10,10,30,30]})
    (run/'run_manifest.json').write_text('{}')
    import navigation_identity
    monkeypatch.setattr(navigation_identity,'load',lambda *a:{'interactive_areas':[[0,0,100,100]],'region_bounds':{rid:[0,0,100,100] for rid in state['interactive_regions']}})
    monkeypatch.setattr(m.discovery,'load',lambda r:(snap,records,state))
    def publish(run,tag,change):change(records,state,snap,tmp_path);return {'snapshot':tag}
    monkeypatch.setattr(m.discovery,'publish',publish)
    transport=SimpleNamespace(run=run,account={'max_gui_commands':6,'gui_started':0},save=lambda:None,
        screenshot=lambda p:p.write_bytes((run/'current.png').read_bytes()))
    q={'navigation_advice':True,'source':{'working_region':'b'},'navigation_path':[{'source_region':'a','source_control':'c','target_region':'b','attempt':'old','operation':'click'}]}
    monkeypatch.setattr(m,'confirm_regions',lambda snapshot,records,refs,*a:refs)
    monkeypatch.setattr(m,'same_surface',lambda *a:True)
    monkeypatch.setattr(m,'locate_control',lambda *a:[10,10,30,30])
    monkeypatch.setattr(m.time,'sleep',lambda t:None)
    def execute(*args):transport.account['gui_started']+=1;return {'exit_code':0}
    monkeypatch.setattr(m.actions,'execute',execute)
    return m,run,records,state,transport,q


def test_known_edge_updates_location_without_graph_registration(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);before=deepcopy(records)
    result=m.try_step(t,q,run/'current.png')
    assert result['status']=='ready_next_round'
    assert state['interactive_regions']==['b'] and state['working_region']=='b'
    assert records==before and not (run/'visual_navigation_pending.json').exists()
    assert json.loads((run/'run_manifest.json').read_text())['actual_navigation_actions']==1


def test_failed_landing_hands_off_without_retry(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);before=deepcopy(records)
    monkeypatch.setattr(m,'confirm_regions',lambda *a:[])
    result=m.try_step(t,q,run/'current.png')
    assert state['next_action_mode']=='discover' and t.account['gui_started']==1
    assert 'old' in state['navigation_failed_edges'] and records==before
    assert m.try_step(t,q,run/'current.png') is None


def test_crash_marker_never_replays_gui(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    (run/'visual_navigation_pending.json').write_text(json.dumps({'edge':q['navigation_path'][0],'status':'dispatching'}))
    assert m.resume_pending(t,run/'current.png')['status']=='ready_next_round'
    assert t.account['gui_started']==0 and state['next_action_mode']=='discover'


def test_real_visual_match_rejects_changed_surface(tmp_path,monkeypatch):
    import numpy as np
    from PIL import Image
    m=module(monkeypatch)
    pixels=np.random.default_rng(23).integers(0,256,(120,120,3),dtype=np.uint8)
    old=tmp_path/'old.png';new=tmp_path/'new.png'
    Image.fromarray(pixels).save(old);Image.fromarray(pixels).save(new)
    assert m.same_surface(old,new)
    pixels[20:100,20:100]=128;Image.fromarray(pixels).save(new)
    assert not m.same_surface(old,new)


def test_known_route_keeps_automatic_priority(monkeypatch):
    module(monkeypatch)
    from region_tasks import attach
    base={'navigation_advice':True,'navigation_path':[{'attempt':'old'}]}
    assert attach(ROOT,{}, {'next_action_mode':'explore','interactive_regions':['a'],'visual_navigation':{'replay':'active'}},'goal',base) is base


def test_runner_auto_route_makes_no_model_call(tmp_path,monkeypatch):
    module(monkeypatch)
    import run_task_step as runner
    monkeypatch.setattr(runner.exploration_loop,"observe",lambda *a:None)
    run=tmp_path/'run';run.mkdir()
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'test.app'}))
    (run/'knowledge_current.json').write_text('{}')
    monkeypatch.setattr(runner.RecoveryRun,'screenshot',lambda self,p:p.write_bytes(b'frame'))
    monkeypatch.setattr(runner.discovery_step,'load',lambda r:(None,{}, {'next_action_mode':'explore'}))
    monkeypatch.setattr(runner.step_repair,'pending',lambda r:None)
    monkeypatch.setattr(runner.step_repair,'Runner',lambda *a:SimpleNamespace())
    monkeypatch.setattr(runner,'assemble_current_context',lambda *a:{'stage':'action_selection','action_ready':True,'navigation_advice':True})
    monkeypatch.setattr(runner.visual_backtrack,'try_step',lambda *a:{'status':'ready_next_round','navigation':'confirmed','gui_actions':1})
    runner._run_step(ROOT,run,tmp_path/'round')
    result=json.loads((tmp_path/'round/result.json').read_text())
    assert result['calls']==[] and result['navigation']=='confirmed'


def test_luna_unknown_navigation_entry_requests_discovery(tmp_path,monkeypatch):
    module(monkeypatch)
    import run_task_step as runner
    monkeypatch.setattr(runner.exploration_loop,"observe",lambda *a:None)
    run=tmp_path/'run';run.mkdir()
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'test.app'}))
    (run/'knowledge_current.json').write_text('{}')
    state={'next_action_mode':'explore'}
    monkeypatch.setattr(runner.RecoveryRun,'screenshot',lambda self,p:p.write_bytes(b'frame'))
    monkeypatch.setattr(runner.discovery_step,'load',lambda r:(None,{},state))
    monkeypatch.setattr(runner.discovery_step,'publish',lambda r,tag,mutate:mutate({},state))
    monkeypatch.setattr(runner.step_repair,'pending',lambda r:None)
    q={'stage':'action_selection','action_ready':True,'navigation_advice':True}
    accepted={'result':{'request':q,'call':'test','proposal':{'reason':'发现尚未登记的侧栏入口'},'binding':{'status':'no_action'}}}
    monkeypatch.setattr(runner.step_repair,'Runner',lambda *a:SimpleNamespace(perform=lambda *a:accepted))
    monkeypatch.setattr(runner,'assemble_current_context',lambda *a:q)
    monkeypatch.setattr(runner.visual_backtrack,'try_step',lambda *a:None)
    runner._run_step(ROOT,run,tmp_path/'round')
    assert state['next_action_mode']=='discover' and '侧栏入口' in state['correction_context']
    assert json.loads((tmp_path/'round/result.json').read_text())['gui_actions']==0


def test_replay_clicks_operation_area_not_identity_center(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    records['a']['controls']['c']['observations'][0].update(
        bbox={'left':0,'top':0,'right':100,'bottom':100},
        click_bbox={'left':70,'top':20,'right':90,'bottom':80})
    seen=[]
    monkeypatch.setattr(m.actions,'execute',lambda t,p,f:seen.append(p) or {'exit_code':0})
    m.try_step(t,q,run/'current.png')
    assert (seen[0]['x'],seen[0]['y'])==(26,20)


def test_legacy_replay_uses_recorded_point_not_crop_center(monkeypatch):
    m=module(monkeypatch)
    monkeypatch.setattr(m.image_match,'locate',lambda *a:{'accepted':True,'box':[497,193,1095,249]})
    point=m.replay_point({'image':'old.png'},{'x':1004,'y':221},'before.png',[597,293,1195,349])
    assert point==(1104,321)


def test_destination_menu_must_match_even_when_whole_frame_matches(tmp_path,monkeypatch):
    m=module(monkeypatch)
    monkeypatch.setattr(m.image_match,'locate',lambda *a:{'accepted':False,'box':[0,0,10,10]})
    import foreground_scope
    monkeypatch.setattr(foreground_scope,'load',lambda *a:{'region_bounds':{'menu':[0,0,10,10]},'interactive_areas':[[0,0,10,10]]})
    records={'menu':{'observations':[{'image':'menu.png','evidence':{'observation':'after'}}]}}
    assert m.confirm_regions(tmp_path,records,['menu'],'after','current.png')==[]
