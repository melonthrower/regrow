from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_deferral import setup


def test_cross_region_candidate_reports_ownership_not_missing_name():
    m=tasks().helper('registration_diagnostics')
    records={'r1':{'name':'Old form','controls':{'c1':{'name':'IPv4'}}}}
    q={'discovery_context':{'region_names':{'Old form':'r1'},'control_names':{'IPv4':'c1'}}}
    p={'regions':[{'name':'Tabs','previous_name':None,'identity':'new','parent_index':None}],
       'controls':[{'region_index':0,'text':'IPv4','identity':'same','previous_name':'IPv4'}]}
    errors=m.collect('discovery',q,p,records)['errors']
    assert any(e['code']=='region_ownership_review' and e['actual']['control_id']=='c1' for e in errors)
    assert not any(e['code']=='unknown_candidate_control' for e in errors)


def test_partition_moves_identity_history_and_keeps_unobserved(tmp_path):
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run);m=tasks().helper('ownership_review')
    old=deepcopy(records['r1']['controls']['c1'])
    episode={'source_region':'r1','assignments':{'c1':{'region':'Tabs','description':'tab selection','call':'review1','frame':'frame.png','evidence':'visible tab'}},'conflicts':{}}
    moved=m.repartition(records,state,episode,snapshot)
    dest=records[moved['c1']]
    assert 'c1' not in records['r1']['controls'] and 'c2' in records['r1']['controls']
    assert dest['controls']['c1']['action_refs']==old['action_refs']
    assert 'Policy' in dest['tasks'] and 'Policy' not in records['r1']['tasks']
    assert records['r1']['partition_review']['status']=='partial'


def test_conflicting_observations_do_not_move_control(tmp_path):
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run);m=tasks().helper('ownership_review')
    ep={'source_region':'r1','assignments':{'c1':{'region':'Tabs'}},'conflicts':{'c1':[{},{}]}}
    assert m.repartition(records,state,ep,snapshot)=={}
    assert 'c1' in records['r1']['controls']


def test_dependency_preparation_and_evidence_scoped_wakeup(tmp_path):
    run,q,d=setup(tmp_path);_,records,state=d.load(run);m=tasks().helper('task_prerequisites')
    r=records['r1'];r['tasks']['Policy']['prerequisite']={'region':r['name'],'control':r['controls']['c2']['name'],
        'condition':'Policy entry enabled','preparation':'enable parent','evidence':'entry grey and parent off','permitted':True}
    m.enroll(records,'r1','plan1');t=r['tasks']['Policy'];assert t['status']=='blocked'
    prep=t['prerequisite']['scheduled'];assert r['tasks'][prep['task']]['prepares']=={'region':'r1','task':'Policy'}
    reply={'dependency_updates':[{'region':r['name'],'task':'Policy','ready':True,'evidence':'entry visibly enabled'}]}
    allowed=[{'region':'r1','task':'Policy'}]
    with pytest.raises(ValueError,match='准备动作'):m.apply(records,reply,'later',allowed)
    r['controls']['c1']['observations'].append({'evidence':{'source_call':'later'}})
    m.apply(records,reply,'later',allowed);assert t['status']=='pending' and 'blocker' not in t


def test_crash_task_does_not_wake_when_application_returns(tmp_path):
    run,q,d=setup(tmp_path);_,records,state=d.load(run);r=records['r1'];t=r['tasks']['Policy']
    tasks().settle_task(r,{'task_name':'Policy','region_ref':'r1','control_ref':t['control']}, {'action_result':{'exception':'unexpected_exit'},
        'task_result':{'name':'Policy','status':'pending','evidence':'app exited','findings':[]}},'crash1')
    r['controls']['c1']['observations'].append({'image':'visible.png','evidence':{'source_call':'returned'}})
    tasks().helper('task_deferral').resume_localized(records,['r1'],'returned',foreground={'exception':'none'})
    assert t['status']=='blocked' and t['deferral']['retry_when']=='explicit_crash_cause_resolved'


def test_keyboard_submit_is_shared_and_explicit(monkeypatch):
    from tests.test_stepwise_resume_route import ROOT
    monkeypatch.syspath_prepend(str(ROOT))
    m=tasks().helper('action_commands');p={'target':'current terminal prompt','action':'key_press','text':'ENTER',
        'x':None,'y':None,'end_x':None,'end_y':None,'reason':'submit already entered read-only command',
        'skip_task':False,'request_task_review':False}
    m.validate(p)
    assert m.commands(p)==[['shell','input','keyevent','66']]
    assert m.commands(p,'desktop')==["pyautogui.press('enter')"]
    with pytest.raises(ValueError):m.commands({**p,'text':'arbitrary code'})


def test_existing_task_receives_new_prerequisite_through_plan(tmp_path):
    from tests.test_stepwise_region_tasks import row,proposal
    run,q,d=setup(tmp_path);_,records,state=d.load(run);r=records['r1']
    operations=[row(n,r['controls'][t['control']]['name'],t['handling'],t.get('equivalent_to','')) for n,t in r['tasks'].items()]
    operations[0]['prerequisite']={'region':r['name'],'control':r['controls']['c2']['name'],
        'condition':'Policy enabled','preparation':'enable parent','evidence':'grey entry','permitted':True}
    tasks().apply_plan(r,proposal(operations),'new-plan')
    tasks().helper('task_prerequisites').enroll(records,'r1','new-plan')
    assert r['tasks'][operations[0]['name']]['status']=='blocked'
    assert any(t.get('prepares') for t in r['tasks'].values())


def test_global_split_request_and_local_multi_region_reassignment_are_detected():
    m=tasks().helper('ownership_review');records={'r1':{'controls':{'c1':{'name':'IPv4'}}}}
    q={'discovery_context':{'focus':'r1','control_names':{'IPv4':'c1'},'region_names':{'Old':'r1'}}}
    assert m.conflict(q,{'foreground':{'exception':'region_ownership_review','description':'old tabs mixed'},'controls':[]},records)['errors'][0]['actual']=={'region_id':'r1'}
    p={'regions':[{'previous_name':'Old'},{'previous_name':None}],
       'controls':[{'previous_name':'IPv4','identity':'same','region_index':1}]}
    assert m.conflict(q,p,records)['errors'][0]['actual']['control_id']=='c1'


def test_historical_crash_does_not_wake_on_fresh_frame(tmp_path):
    run,q,d=setup(tmp_path);_,records,state=d.load(run);r=records['r1'];t=r['tasks']['Policy']
    t.update(status='blocked',blocker={'condition':'foreground_exception','exception':'unexpected_exit'})
    r['controls']['c1']['observations'].append({'image':'visible.png','evidence':{'source_call':'returned'}})
    tasks().helper('task_deferral').resume_localized(records,['r1'],'returned',foreground={'exception':'none'})
    assert t['status']=='blocked'


def test_cross_region_preparation_is_prioritized_before_ordinary_tasks(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('task_prerequisites')
    def seed(records,state,*args):
        r=deepcopy(records['r1']);r['id']='r2';r['name']='Prerequisite region'
        r['tasks']={'Prepare':{'status':'pending','prepares':{'region':'r1','task':'Policy'}}}
        records['r2']=r;state.update(next_action_mode='explore',working_region='r1');state.pop('active_task',None)
    d.publish(run,'prep-seed',seed)
    assert m.prioritize(run)
    state=d.load(run)[2]
    assert state['working_region']=='r2' and state['deferred_routing_target']=='r2'
    assert not m.prioritize(run)


def test_partition_rewrites_paired_dependency_task_references(tmp_path):
    run,q,d=setup(tmp_path);snapshot,records,state=d.load(run);m=tasks().helper('ownership_review')
    records['r1']['tasks']['Settings']['prerequisite']={'scheduled':{'region':'r1','task':'Policy'}}
    records['r1']['tasks']['Settings']['prepares']={'region':'r1','task':'Policy'}
    ep={'source_region':'r1','assignments':{'c1':{'region':'Tabs','description':'tabs','call':'review','frame':'frame','evidence':'visible'}},'conflicts':{}}
    target=m.repartition(records,state,ep,snapshot)['c1']
    remaining=records['r1']['tasks']['Settings']
    assert remaining['prerequisite']['scheduled']['region']==target
    assert remaining['prepares']['region']==target


def test_disallowed_dependency_is_visible_as_blocked_not_completed(tmp_path):
    run,q,d=setup(tmp_path);_,records,state=d.load(run);r=records['r1'];t=r['tasks']['Policy']
    t.update(handling='record',status='record_only',prerequisite={'region':r['name'],'control':r['controls']['c2']['name'],
        'condition':'entry enabled','preparation':'enable parent','evidence':'grey entry','permitted':False})
    tasks().helper('task_prerequisites').enroll(records,'r1','plan')
    assert 'Policy' in tasks().coverage(r)['blocked']
    assert not any(x.get('prepares') for x in r['tasks'].values())


def test_preparation_done_routes_back_then_observes_without_waking(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('task_prerequisites')
    def seed(records,state,*args):
        records['r2']=deepcopy(records['r1']);records['r2']['id']='r2';records['r2']['name']='Prepare region'
        records['r2']['tasks']={'Prepare':{'status':'done','prepares':{'region':'r1','task':'Policy'}}}
        records['r1']['tasks']['Policy'].update(status='blocked',blocker={'condition':'prerequisite'},
            prerequisite={'permitted':True,'scheduled':{'region':'r2','task':'Prepare'}})
        state.update(working_region='r2',interactive_regions=['r2'],next_action_mode='explore');state.pop('active_task',None)
    d.publish(run,'prepared',seed)
    assert m.prioritize(run,'frame.png')
    assert d.load(run)[2]['working_region']=='r1'
    d.publish(run,'returned',lambda r,s,*args:s.update(interactive_regions=['r1']))
    assert m.prioritize(run,'frame.png')
    _,records,state=d.load(run)
    assert state['next_action_mode']=='discover' and state['inspection_region']=='r1'
    assert records['r1']['tasks']['Policy']['status']=='blocked'


def test_same_dependency_report_preserves_completed_preparation_receipt(tmp_path):
    from tests.test_stepwise_region_tasks import row,proposal
    run,q,d=setup(tmp_path);_,records,state=d.load(run);r=records['r1']
    dep={'region':r['name'],'control':r['controls']['c2']['name'],'condition':'enabled','preparation':'enable','evidence':'grey','permitted':True}
    r['tasks']['Policy']['prerequisite']={**dep,'scheduled':{'region':'r1','task':'Prepare'},'recheck_requested':'frame.png'}
    ops=[row(n,r['controls'][t['control']]['name'],t['handling'],t.get('equivalent_to','')) for n,t in r['tasks'].items()]
    next(x for x in ops if x['name']=='Policy')['prerequisite']=dep
    tasks().apply_plan(r,proposal(ops),'again')
    assert r['tasks']['Policy']['prerequisite']['scheduled']['task']=='Prepare'
    assert r['tasks']['Policy']['prerequisite']['recheck_requested']=='frame.png'
