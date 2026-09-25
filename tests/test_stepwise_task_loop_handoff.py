from copy import deepcopy
import json
from types import SimpleNamespace
from tests.test_recovery_discovery import mod


def test_opened_region_owns_remaining_exploration():
    m=mod('task_routing');task={'task_type':'single_action','control':'open','status':'pending'}
    records={'page':{'tasks':{'open menu':task},'reached_by':[],'actions':{'a':{'operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}}},
             'menu':{'name':'菜单','reached_by':[],'actions':{}}}
    old={'working_region':'page','active_task':{'region':'page','name':'open menu'},'deferred_routing_target':'page'}
    new={**old,'interactive_regions':['menu']}
    binding={'region_ref':'page','control_ref':'open','task_name':'open menu'}
    m.advance(records,old,new,'page',binding,'a')
    assert task['status']=='done' and new['working_region']=='menu'
    assert 'active_task' not in new and 'deferred_routing_target' not in new


def test_parameter_task_keeps_ownership():
    m=mod('task_routing');task={'task_type':'parameter','control':'open','status':'pending'}
    records={'page':{'tasks':{'select value':task},'reached_by':[],'actions':{}},'dialog':{'name':'选项','reached_by':[],'actions':{}}}
    old={'working_region':'page'};new={**old,'interactive_regions':['dialog']}
    m.advance(records,old,new,'page',{'control_ref':'open','task_name':'select value'},'a')
    assert task['status']=='pending' and new['active_task']['region']=='page'


def test_repeated_click_position_changes_enter_correction(tmp_path,monkeypatch):
    import pytest
    m=mod('attempt_guard')
    import sys
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda *args:True))
    records={'r':{'tasks':{'try':{'status':'pending','attempts':['a','b']}}}}
    binding={'region_ref':'r','control_ref':'c','task_name':'try'}
    for aid,x in [('a',10),('b',30)]:
        p=tmp_path/'action_attempts'/aid;p.mkdir(parents=True)
        (p/'proposal.json').write_text(json.dumps({'action':'click','x':x}))
        (p/'binding.json').write_text(json.dumps(binding))
    with pytest.raises(ValueError,match='点击位置不构成新依据'):
        m.check(tmp_path,records,binding,{'action':'click','x':50},tmp_path/'frame.png')


def test_repeat_guard_calls_correction_before_deferral(tmp_path,monkeypatch):
    import pytest
    from tests.test_stepwise_deferral import setup
    from tests.test_stepwise_task_correction import repair,Calls,answer
    run,q,d=setup(tmp_path);m=repair();calls=Calls(run,[{'action':'click'},answer('defer')])
    runner=m.Runner(__import__('tests.test_recovery_discovery',fromlist=['ROOT']).ROOT,run,calls,None,lambda:6)
    def reject(*args):raise mod('attempt_guard').RepeatedAttempt('重复无进展')
    monkeypatch.setattr(runner.adapters,'accept',reject)
    with pytest.raises(m.Paused) as error:runner.perform('action',q)
    assert error.value.status=='task_deferred' and len(calls.requests)==2
    assert d.load(run)[1]['r1']['tasks']['Policy']['status']=='blocked'


def test_visible_region_with_uncertain_interactivity_returns_to_discovery(tmp_path):
    from tests.test_region_registration import fixture,module,invoke
    run,g,reply=fixture(tmp_path)
    g['action_edges'][0]['after_image']='after.png'
    (run/'after.png').write_bytes(b'no crops')
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    reply['action_result']['exception']='none'
    reply['previous_regions'][0]['state']='uncertain'
    reply['regions']=[{'name':'Menu','previous_name':'Menu','description':'visible','reason':'visible','parent_index':None,'bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    pointer=invoke(module(),run)
    state=json.loads((run/pointer['snapshot']/'runtime_state.json').read_text())
    assert state['next_action_mode']=='discover' and state['pending_frame']


def test_multi_region_entry_hands_off_to_unfinished_content_not_finished_navigation():
    m=mod('task_routing')
    task={'task_type':'single_action','control':'open','status':'done'}
    records={'source':{'tasks':{'open':task},'reached_by':[],'actions':{'a':{'operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}}},
        'nav':{'name':'导航','controls':{},'tasks':{},'task_inventory':{'inventory':'complete','controls':[]},'region_role':'navigation'},
        'content':{'name':'新内容','controls':{},'tasks':{}}}
    old={'working_region':'source','active_task':{'region':'source','name':'open'}}
    new={**old,'interactive_regions':['nav','content']}
    m.advance(records,old,new,'source',{'region_ref':'source','control_ref':'open','task_name':'open'},'a')
    assert new['working_region']=='content'
    assert new['region_path']==['source','content']
    assert task['completion_basis']['destination_regions']==['nav','content']
    assert 'active_task' not in new


def test_multiple_new_regions_do_not_complete_parameter_task():
    m=mod('task_routing');task={'task_type':'parameter','control':'open','status':'pending'}
    records={'source':{'tasks':{'configure':task},'reached_by':[],'actions':{}},
             'one':{'name':'选项','controls':{}},'two':{'name':'预览','controls':{}}}
    old={'working_region':'source'};new={**old,'interactive_regions':['one','two']}
    m.advance(records,old,new,'source',{'control_ref':'open','task_name':'configure'},'a')
    assert new['working_region']=='source' and task['status']=='pending'
