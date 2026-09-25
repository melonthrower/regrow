from copy import deepcopy
import json
from tests.test_stepwise_visual_backtrack import setup
from tests.test_stepwise_resume_route import fixture, ROOT


def later_edge(records,q):
    records['b']['controls']['next']={'name':'Destination','observations':[{'image':'crop.png','bbox':{'left':10,'top':10,'right':30,'bottom':30},'click_bbox':{'left':10,'top':10,'right':30,'bottom':30},'image_quality':'clear','image_quality_reason':'test entry','evidence':{'observation':'later'}}]}
    records['b']['actions']['later']={'control':'next','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'},'interactive_regions':['goal'],
        'evidence':{'before_observation':'later','before_image':'later_before.png','after_image':'later_after.png'}}
    records['b']['observations']=[{'image':'region.png','image_quality':'clear','image_quality_reason':'test owner','evidence':{'observation':'later'}}]
    records['goal']={**deepcopy(records['b']),'controls':{},'actions':{},'id':'goal','name':'goal'}
    q['source']['working_region']='goal'
    q['navigation_path'].append({'source_region':'b','source_control':'next','target_region':'goal','attempt':'later','operation':'click'})


def test_visible_later_entry_skips_first_edge_without_writing_graph(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    state['interactive_regions']=['a','b']
    before=deepcopy(records)
    result=m.try_step(t,q,run/'current.png')
    assert result['navigation']=='confirmed' and state['interactive_regions']==['goal']
    saved=json.loads((__import__('pathlib').Path(result['replay'])/'result.json').read_text())
    assert saved['edge']['attempt']=='later' and saved['skipped_attempts']==['old']
    assert records==before and t.account['gui_started']==1


def test_future_back_is_not_a_shortcut(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    q['navigation_path'][1]['operation']='back'
    result=m.try_step(t,q,run/'current.png')
    assert state['interactive_regions']==['b']


def test_failed_or_composite_later_edge_keeps_original_route(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    records['b']['actions']['later']['executed_steps']=[{'action':'click'},{'action':'click'}]
    m.try_step(t,q,run/'current.png')
    assert state['interactive_regions']==['b']


def test_prompt_discloses_future_buttons_as_history_not_current_targets():
    m,records,state=fixture();records['main']['actions'].pop('a3');records['main']['transitions']=records['main']['transitions'][:1]
    q=m.assemble_context(ROOT,records,state,'menu')
    assert '后续入口参考' in q['user_prompt'] and '打开中间区' in q['user_prompt']
    assert '尚未确认当前可操作' in q['user_prompt']
    assert {c['region_ref'] for c in q['backend_candidates']}=={'main'}


def test_matching_icon_in_unconfirmed_background_does_not_skip(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    monkeypatch.setattr(m,'same_surface',lambda old,new:'later_before' not in str(old))
    result=m.try_step(t,q,run/'current.png')
    assert state['interactive_regions']==['b']
    assert json.loads((__import__('pathlib').Path(result['replay'])/'result.json').read_text())['skipped_attempts']==[]


def test_shortcut_failed_landing_hands_off_actual_selected_edge(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    state['interactive_regions']=['a','b']
    monkeypatch.setattr(m,'confirm_regions',lambda *a:[])
    m.try_step(t,q,run/'current.png')
    assert state['next_action_mode']=='discover' and t.account['gui_started']==1
    assert state['navigation_failed_edges']==['later']
    assert state['navigation_handoff']['skipped_attempts']==['old']


def test_shortcut_rechecks_before_dispatch(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    state['interactive_regions']=['a','b']
    original=m.shortcut_match
    monkeypatch.setattr(m,'shortcut_match',lambda snap,rec,st,edge,frame:None if 'pre_dispatch' in str(frame) else original(snap,rec,st,edge,frame))
    m.try_step(t,q,run/'current.png')
    assert state['next_action_mode']=='discover' and t.account['gui_started']==0


def test_known_foreground_region_can_match_without_identical_whole_screen(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    records['b']['observations']=[{'image':'region.png','image_quality':'clear','image_quality_reason':'test owner','evidence':{'observation':'later'}}]
    state['interactive_regions']=['b']
    monkeypatch.setattr(m,'same_surface',lambda *args:False)
    hit=m.shortcut_match(run,records,state,q['navigation_path'][1],run/'current.png')
    assert hit['basis']=='current_foreground_region_and_control'
    state['interactive_regions']=['a']
    assert m.shortcut_match(run,records,state,q['navigation_path'][1],run/'current.png') is None


def test_previously_failed_later_edge_is_not_retried(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch);later_edge(records,q)
    state['navigation_failed_edges']=['later']
    m.try_step(t,q,run/'current.png')
    assert state['interactive_regions']==['b'] and t.account['gui_started']==1


def test_first_edge_reuses_fresh_observation_after_old_surface_changed(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    records['a']['actions']['old'].update(control='c',operation='click',delivery='executed_receipt_zero',result={'status':'observed_effect'})
    state['observation']['image']=str(run/'current.png')
    monkeypatch.setattr(m,'same_surface',lambda old,new:'old_before' not in str(old))
    result=m.try_step(t,q,run/'current.png')
    assert result['navigation']=='confirmed' and t.account['gui_started']==1
    saved=json.loads((__import__('pathlib').Path(result['replay'])/'result.json').read_text())
    assert saved['shortcut_match']['basis']=='current_foreground_region_and_control'
    assert saved['skipped_attempts']==[]


def test_foreground_membership_cannot_authorize_missing_owner_template(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    records['a']['observations']=[]
    assert m.shortcut_match(run,records,state,q['navigation_path'][0],run/'current.png') is None


def test_current_observation_path_is_relative_to_run(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    records['a']['actions']['old'].update(control='c',operation='click',delivery='executed_receipt_zero',result={'exception':'none'})
    state['observation']['image']='current.png'
    snapshot=run/'knowledge_snapshots'/'current'
    monkeypatch.setattr(m,'same_surface',lambda old,new: __import__('pathlib').Path(old)==run/'current.png')
    hit=m.shortcut_match(snapshot,records,state,q['navigation_path'][0],run/'current.png')
    assert hit and hit['basis']=='current_foreground_region_and_control'
