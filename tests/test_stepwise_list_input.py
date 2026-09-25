import importlib.util
from pathlib import Path
from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_control_identity_name_is_not_display_time():
    flow=tasks().helper('stepwise_flow')
    assert flow.control_name({'name':'城市候选项','text':'London 8:18','icon_appearance':''})=='城市候选项'


def test_list_group_accepts_only_one_representative():
    m=tasks().helper('control_records')
    with pytest.raises(ValueError,match='representative'):
        m.validate([{'region_index':0,'list_group':'城市结果','name':'城市1'}, {'region_index':0,'list_group':'城市结果','name':'城市2'}])
    m.validate([{'region_index':0,'list_group':'城市结果','name':'城市候选'}, {'region_index':0,'list_group':'','name':'清除'}])


def test_merge_keeps_action_and_rewrites_references():
    m=tasks().helper('control_records')
    r={'controls':{'a':{'name':'Back','observations':[],'action_refs':['one']},'b':{'name':'Back duplicate','observations':[],'action_refs':['two']}},
       'actions':{'one':{'control':'a'},'two':{'control':'b'}},'transitions':[{'source_control':'b'}],
       'tasks':{'t':{'control':'b'}},'task_inventory':{'controls':['a','b']}}
    records={'r':r};state={'observation':{'control_refs':['b']}}
    m.merge(records,state,'r',['b'],'a')
    assert list(r['controls'])==['a'] and r['actions']['two']['control']=='a'
    assert r['transitions'][0]['source_control']=='a' and r['tasks']['t']['control']=='a'
    assert r['controls']['a']['action_refs']==['one','two'] and state['observation']['control_refs']==['a']


def test_remove_refuses_record_with_history():
    m=tasks().helper('control_records')
    r={'controls':{'a':{'action_refs':['one']}},'actions':{},'tasks':{},'transitions':[]}
    with pytest.raises(ValueError):m.remove({'r':r},{},'r','a')


def test_input_stops_before_typing_when_focus_opens_new_surface(tmp_path,monkeypatch):
    import sys,json
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ROOT))
    import action_commands as m
    import visual_backtrack
    monkeypatch.setattr(m.time,'sleep',lambda t:None)
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *a:False)
    sent=[]
    t=SimpleNamespace(account={'gui_started':0,'max_gui_commands':6},save=lambda:None,
        screenshot=lambda p:p.write_bytes(b'frame'),adb=lambda argv:sent.append(argv) or SimpleNamespace(returncode=0,stdout=b'',stderr=b''))
    result=m.execute(t,{'action':'input_text','x':10,'y':10,'text':'wifi'},tmp_path/'execution')
    assert len(sent)==1 and result['text_delivered'] is False
    assert result['semantic_result']=='focus_changed_surface'
    assert (tmp_path/'execution/after_focus.png').exists()


def test_repeated_unfinished_attempt_enters_correction(tmp_path,monkeypatch):
    import json
    monkeypatch.syspath_prepend(str(ROOT))
    import visual_backtrack
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *args:True)
    m=tasks().helper('attempt_guard')
    binding={'region_ref':'r','control_ref':'c','task_name':'search'}
    proposal={'action':'input_text','text':'wifi'}
    records={'r':{'tasks':{'search':{'status':'pending','attempts':['a1','a2']}}}}
    for a in ['a1','a2']:
        f=tmp_path/'action_attempts'/a;f.mkdir(parents=True)
        (f/'binding.json').write_text(json.dumps(binding));(f/'proposal.json').write_text(json.dumps(proposal))
    with pytest.raises(ValueError,match='defer'):m.check(tmp_path,records,binding,proposal,'current.png')
    m.check(tmp_path,records,{**binding,'control_ref':'new_field'},proposal,'current.png')
    m.check(tmp_path,records,binding,{'action':'scroll'},'current.png')
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *args:False)
    m.check(tmp_path,records,binding,proposal,'changed.png')


def test_record_repair_batch_is_atomic_and_preserves_old_snapshot(tmp_path):
    from tests.test_stepwise_task_correction import saved
    run,q,_=saved(tmp_path)
    d=tasks().helper('discovery_step');stages=tasks().helper('repair_stages')
    def add(records,state,*args):
        records['r1']['controls']['duplicate']=deepcopy(records['r1']['controls']['c1'])
    d.publish(run,'duplicate-fixture',add)
    before,records,_=d.load(run)
    original=(before/'regions/r1/region.json').read_bytes()
    edit={'region':'Menu','control':'Policy','field':'merge_into','before':'Policy','after':'Policy','evidence':'同一箭头重复登记'}
    job={'request':q,'stage':'task_proposal','call':'batch','supplements':[]}
    with pytest.raises(ValueError):
        stages.edit_record(ROOT,run,job,[edit,{**edit,'control':'absent','before':'absent','field':'remove','after':''}])
    assert d.load(run)[0]==before
    stages.edit_record(ROOT,run,job,[edit])
    assert 'duplicate' not in d.load(run)[1]['r1']['controls']
    assert (before/'regions/r1/region.json').read_bytes()==original
