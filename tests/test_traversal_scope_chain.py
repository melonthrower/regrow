import pytest
from tests.test_recovery_discovery import mod,ROOT
from tests.test_pointer_action_binding import action_request

def test_desktop_scroll_endpoint_is_not_mouse_target(action_request):
    action_request.update(platform='desktop',allow_scroll=True,region_image=action_request['backend_candidates'][0]['image'])
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'scroll','target':'content','x':85,'y':50,'end_x':85,'end_y':100,'reason':'reveal expanded controls'})
    assert result['status']=='matched'

def test_android_scroll_still_requires_region_endpoints(action_request):
    action_request.update(platform='android',allow_scroll=True,region_image=action_request['backend_candidates'][0]['image'])
    result=mod('stepwise_flow').bind_action_target(action_request,{'action':'scroll','target':'content','x':85,'y':50,'end_x':85,'end_y':100,'reason':'scroll'})
    assert result['status']=='unresolved'

def test_scope_exclusion_preserves_tasks_but_removes_frontier():
    r={'id':'r1','controls':{},'tasks':{'old':{'status':'pending','handling':'explore','attempts':['a1']}},'out_of_scope_reason':'web business outside requested browser scope'}
    assert not mod('task_deferral').runnable(r)
    assert r['tasks']['old']['attempts']==['a1']

def test_scope_idle_is_not_framework_failure():
    result=mod('debug_loop').classify({'status':'scope_idle'},{'status':'scope_idle'},None)
    assert result['kind']=='scope_idle'

def test_scope_excluded_surface_never_generates_tasks_or_functions(tmp_path):
    from tests.test_recovery_discovery import seeded_run
    d=mod('discovery_step');run=seeded_run(tmp_path)
    def exclude(records,state,*args):
        records['r1']['out_of_scope_reason']='test material outside the requested scope'
        state.update(next_action_mode='explore',interactive_regions=['r1'],working_region='r1')
    d.publish(run,'excluded',exclude)
    snapshot,records,state=d.load(run)
    assert mod('historical_inventory').request(ROOT,snapshot,records,state) is None
    q=mod('stepwise_flow').assemble_current_context(ROOT,run)
    assert q['stage']=='scope_idle' and not q['action_ready']
    assert mod('task_deferral').choose_unfinished(records,state) is None

def test_scope_idle_does_not_invoke_repair_or_mark_incomplete_graph_done(tmp_path,monkeypatch):
    from tests.test_debug_loop import seed
    loop=mod('debug_loop');run,_,_=seed(tmp_path)
    sup=loop.Supervisor(tmp_path/'supervisor',[],ROOT)
    app={'key':'test','run':str(run),'source':str(ROOT),'failures':{}}
    monkeypatch.setattr(loop,'live_run',lambda _:False)
    monkeypatch.setattr(sup,'run_round',lambda *a:{'kind':'scope_idle','reason':'only blocked work remains'})
    monkeypatch.setattr(loop,'graph_summary',lambda *a:{'complete':False,'regions':1,'done':0,'blocked':1})
    sup.tick(app,repair=lambda *a:pytest.fail('scope_idle must not repair'))
    assert app['status']=='scope_idle'

def test_scope_conflict_does_not_merge_or_erase_records():
    import pytest
    rr=mod('region_records');rs={'r1':{'out_of_scope_reason':'outside'},'r2':{}}
    with pytest.raises(ValueError,match='范围'):
        rr.merge(rs,{},['r1'],'r2',snapshot=None,rebase=None,evidence='same crop')
    assert set(rs)=={'r1','r2'}

def test_scope_blocks_prerequisite_enrollment_and_review_candidates():
    p=mod('task_prerequisites')
    task={'status':'blocked','blocker':{'condition':'prerequisite'},'prerequisite':{'permitted':True,'region':'inside','control':'switch','condition':'enabled','preparation':'enable'}}
    rs={'outside':{'name':'outside','out_of_scope_reason':'excluded','tasks':{'old':task}},'inside':{'name':'inside','controls':{'c':{'name':'switch'}},'tasks':{}}}
    p.enroll(rs,'outside','call')
    assert rs['inside']['tasks']=={} and p.candidates(rs)==[]

def test_scope_completion_excludes_only_confirmed_owner_control_gap():
    c=mod('discovery_completion')
    rs={'r1':{'name':'outside','out_of_scope_reason':'web scope'}}
    control={'kind':'control','owner':'outside','item':'one'}
    region={'kind':'region','name':'outside','item':'two'}
    batch={'regions':['r1'],'pending':[control,region]}
    actual=c.scoped_batch(rs,batch)
    assert actual['pending']==[region]
    assert actual['excluded_gaps'][0]['owner_region']=='r1'
    assert batch['pending']==[control,region]

def test_desktop_navigation_scroll_endpoint_is_direction(action_request):
    action_request.update(platform='desktop',navigation_advice={'target':'other'})
    q={'action':'scroll','target':'content','x':85,'y':50,'end_x':85,'end_y':1000,'reason':'reveal lower content'}
    assert mod('stepwise_flow').bind_action_target(action_request,q)['status']=='matched'
    action_request['platform']='android'
    assert mod('stepwise_flow').bind_action_target(action_request,q)['status']=='unresolved'

def test_old_preparation_is_not_runnable_after_goal_excluded():
    task={'status':'pending','handling':'explore','equivalent_to':'','prepares':{'region':'outside','task':'old'}}
    r={'controls':{},'tasks':{'prepare':task},'task_inventory':{'inventory':'complete','controls':[]}}
    rs={'inside':r,'outside':{'out_of_scope_reason':'outside'}}
    assert mod('task_deferral').pending_tasks(r,rs)==[]
    assert not mod('task_deferral').runnable(r,rs)
    assert mod('region_tasks').coverage(r,rs)['pending']==[]
    assert task['status']=='pending'

def test_function_review_of_region_with_excluded_preparation(tmp_path):
    from tests.test_recovery_discovery import seeded_run
    d=mod('discovery_step');run=seeded_run(tmp_path);_,records,state=d.load(run)
    r=records['r1'];r['task_inventory']={'inventory':'complete','controls':list(r['controls'])}
    r['tasks']={'prepare':{'status':'pending','handling':'explore','equivalent_to':'','prepares':{'region':'outside'},'attempts':[]}}
    records['outside']={'out_of_scope_reason':'web content'}
    f=mod('region_functions')
    q=f.request(ROOT,r,state,records)
    assert q['stage']=='function_registration'
    f.register(r,{'parameter_definitions':[],'local_knowledge':{'summary':'本地用途测试记录','parameter_refs':[],'conditions':[],'unconfirmed':[]},'region_role':'navigation','role_evidence':'navigation only','functions':[],'evidence':'observed navigation'},'scope-test',records)
    assert r['tasks']['prepare']['status']=='pending'
