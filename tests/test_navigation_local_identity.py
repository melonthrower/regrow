from pathlib import Path
from types import SimpleNamespace
from tests.test_stepwise_visual_backtrack import module


def case(tmp_path,monkeypatch):
    m=module(monkeypatch)
    import navigation_identity
    monkeypatch.setattr(navigation_identity,'load',lambda *a:{'interactive_areas':[[0,0,100,40]],'region_bounds':{'r':[0,0,100,40]}})
    row={'image':'control.png','bbox':{'left':10,'top':10,'right':30,'bottom':30},'click_bbox':{'left':12,'top':12,'right':28,'bottom':28},'evidence':{'observation':'new'}}
    region={'image':'region.png','evidence':{'observation':'new'}}
    for x in (row,region):x.update(image_quality='clear',image_quality_reason='visible test template')
    records={'r':{'controls':{'c':{'observations':[row]}},'observations':[region], 'actions':{'a':{'control':'c','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'},'interactive_regions':['goal'],'evidence':{'before_observation':'old','before_image':'old.png','after_image':'after.png'}}}}}
    edge={'source_region':'r','source_control':'c','target_region':'goal','attempt':'a','operation':'click'}
    monkeypatch.setattr(m.image_match,'locate',lambda template,frame:{'accepted':True,'box':[0,0,100,40] if str(template).endswith('region.png') else [10,10,30,30]})
    monkeypatch.setattr(m,'same_surface',lambda *a:False)
    return m,records,{'interactive_regions':['r'],'observation':{}},edge


def test_latest_owner_and_control_allow_changed_whole_screen(tmp_path,monkeypatch):
    m,records,state,edge=case(tmp_path,monkeypatch)
    hit=m.shortcut_match(tmp_path,records,state,edge,tmp_path/'frame.png')
    assert hit and hit['box']==[12,12,28,28]
    assert hit['basis']=='current_foreground_region_and_control'


def test_background_and_ambiguous_entry_rejected(tmp_path,monkeypatch):
    m,records,state,edge=case(tmp_path,monkeypatch)
    state['interactive_regions']=[]
    assert m.shortcut_match(tmp_path,records,state,edge,tmp_path/'frame.png') is None
    state['interactive_regions']=['r']
    monkeypatch.setattr(m.image_match,'locate',lambda *a:{'accepted':False,'candidates':[{'box':[10,10,30,30]},{'box':[40,10,60,30]}]})
    assert m.shortcut_match(tmp_path,records,state,edge,tmp_path/'frame.png') is None


def test_control_outside_owner_rejected(tmp_path,monkeypatch):
    m,records,state,edge=case(tmp_path,monkeypatch)
    monkeypatch.setattr(m.image_match,'locate',lambda template,frame:{'accepted':True,'box':[0,0,5,5] if str(template).endswith('region.png') else [10,10,30,30]})
    assert m.shortcut_match(tmp_path,records,state,edge,tmp_path/'frame.png') is None


def test_new_frame_without_foreground_proof_rejected(tmp_path,monkeypatch):
    m,records,state,edge=case(tmp_path,monkeypatch)
    import navigation_identity
    monkeypatch.setattr(navigation_identity,'load',lambda *a:None)
    assert m.shortcut_match(tmp_path,records,state,edge,tmp_path/'new-popup.png') is None


def test_destination_visible_in_background_is_not_arrival(tmp_path,monkeypatch):
    m=module(monkeypatch)
    import foreground_scope
    row={'image':'menu.png','image_quality':'clear','image_quality_reason':'visible','evidence':{'observation':'after'}}
    records={'menu':{'observations':[row]}}
    monkeypatch.setattr(m.image_match,'locate',lambda *a:{'accepted':True,'box':[10,10,30,30]})
    for scope in [None,{'region_bounds':{},'interactive_areas':[[0,0,100,100]]},
                  {'region_bounds':{'menu':[10,10,30,30]},'interactive_areas':[[50,50,100,100]]}]:
        monkeypatch.setattr(foreground_scope,'load',lambda *a:scope)
        assert m.confirm_regions(tmp_path,records,['menu'],'after','current.png')==[]
    monkeypatch.setattr(foreground_scope,'load',lambda *a:{'region_bounds':{'menu':[10,10,30,30]},'interactive_areas':[[0,0,100,100]]})
    assert m.confirm_regions(tmp_path,records,['menu'],'after','current.png')==['menu']


def test_pre_dispatch_missing_foreground_does_not_ban_unexecuted_edge(tmp_path,monkeypatch):
    from tests.test_stepwise_visual_backtrack import setup
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    import foreground_scope
    original=m.shortcut_match
    monkeypatch.setattr(m,'shortcut_match',lambda snap,rec,st,edge,frame:None if 'pre_dispatch' in str(frame) else original(snap,rec,st,edge,frame))
    monkeypatch.setattr(foreground_scope,'load',lambda *a:None)
    result=m.try_step(t,q,run/'current.png')
    assert result['navigation']=='luna_handoff' and t.account['gui_started']==0
    assert state['navigation_failed_edges']==[]
