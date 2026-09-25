from pathlib import Path
import importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
sys.path.insert(0,str(ROOT))
import pytest
from debug_loop import classify,graph_summary,fingerprint,Supervisor,write,source_hash


def seed(tmp_path):
    run=tmp_path/'run';s=run/'knowledge_snapshots/s1';(s/'regions/r1').mkdir(parents=True)
    write(run/'run_manifest.json',{})
    write(run/'knowledge_current.json',{'snapshot':'knowledge_snapshots/s1'})
    write(s/'runtime_state.json',{})
    region={'id':'r1','name':'Panel','controls':{},'tasks':{},'task_inventory':{'inventory':'complete','controls':[]},'region_role':'navigation','function_inventory':{'evidence_digest':'x'},'functions':{}}
    write(s/'regions/r1/region.json',region)
    return run,s,region


def test_empty_graph_and_unsettled_never_complete(tmp_path):
    run,s,r=seed(tmp_path)
    (s/'regions/r1/region.json').unlink()
    assert not graph_summary(run)['complete']
    write(s/'regions/r1/region.json',r);write(run/'execution_pending.json',{'attempt':'a1'})
    assert not graph_summary(run)['complete']


def test_blocked_and_missing_function_never_complete(tmp_path):
    run,s,r=seed(tmp_path);r['tasks']={'t':{'handling':'explore','status':'blocked'}}
    write(s/'regions/r1/region.json',r)
    assert graph_summary(run)['blocked']==1
    assert not graph_summary(run)['complete']
    r['tasks']={};r.pop('function_inventory');write(s/'regions/r1/region.json',r)
    assert not graph_summary(run)['complete']


def test_service_and_pause_not_code_repair():
    assert classify({'status':'paused_by_user'}, {},None)['kind']=='paused'
    assert classify({}, {},503)['kind']=='service_wait'
    assert classify({}, {},402)['kind']=='service_blocked'
    assert classify({'status':'interrupted'}, {},None)['kind']=='framework'


def test_same_error_fingerprint_ignores_call_number():
    assert fingerprint({'stage':'update','error':'missing owner','call':'001'})==fingerprint({'stage':'update','error':'missing owner','call':'999'})


def test_failed_candidate_never_promoted(tmp_path):
    run,s,r=seed(tmp_path)
    sup=Supervisor(tmp_path/'out',[],ROOT)
    app={'key':'app','run':str(run),'source':str(ROOT),'failures':{}}
    original=(run/'run_manifest.json').read_bytes()
    assert not sup.promote(app,{'accepted':False,'source':'bad'})
    assert (run/'run_manifest.json').read_bytes()==original


def test_user_stop_prevents_new_step(tmp_path):
    sup=Supervisor(tmp_path/'out',[],ROOT);(sup.out/'STOP').touch()
    assert sup.stopped()


def test_observation_rephrasing_is_not_graph_progress(tmp_path):
    run,s,r=seed(tmp_path);r['tasks']={'t':{'handling':'explore','status':'pending','result_evidence':'old'}}
    write(s/'regions/r1/region.json',r);before=graph_summary(run)['progress_key']
    r['tasks']['t']['result_evidence']='rephrased same failure';r['observations']=[{'call':'new'}]
    write(s/'regions/r1/region.json',r)
    assert graph_summary(run)['progress_key']==before


def test_session_budget_cannot_reset_each_supervised_round(tmp_path,monkeypatch):
    run,s,r=seed(tmp_path);write(run/'run_manifest.json',{'session_limits':{'max_http':12}})
    sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run),'source':str(ROOT),'accounting':{'http_started':7},'failures':{}}
    monkeypatch.setattr(sup,'run_round',lambda *args:pytest.fail('budget should prevent dispatch'))
    sup.tick(app)
    assert app['status']=='paused'


def test_real_complete_positive_and_discovery_not_complete(tmp_path):
    from debug_loop import helper
    run,s,r=seed(tmp_path)
    r['function_inventory']['evidence_digest']=helper(ROOT,'region_functions').signature(r,{'r1':r})
    write(s/'regions/r1/region.json',r)
    assert graph_summary(run)['complete']
    write(s/'runtime_state.json',{'next_action_mode':'discover'})
    assert not graph_summary(run)['complete']


def test_same_device_lock_across_two_runs(tmp_path):
    from debug_loop import device_lock
    a=tmp_path/'a';b=tmp_path/'b'
    for run in (a,b):write(run/'run_manifest.json',{'device':'unit-test-shared-device','platform':'test'})
    with device_lock(a):
        with pytest.raises(BlockingIOError):
            with device_lock(b):pass


def test_user_pause_resumes_but_budget_pause_does_not(tmp_path):
    out=tmp_path/'out';apps=[{'key':'a','run':str(tmp_path/'a'),'status':'paused','pause_reason':'user'},{'key':'b','run':str(tmp_path/'b'),'status':'paused','pause_reason':'budget'}]
    write(out/'status.json',{'apps':apps})
    sup=Supervisor(out,[],ROOT)
    assert [a['status'] for a in sup.apps]==['queued','paused']


@pytest.mark.parametrize('trial_kind',['service_blocked','paused','device_wait','raises'])
def test_trial_failure_restores_source_and_reason(tmp_path,monkeypatch,trial_kind):
    run,s,r=seed(tmp_path);sup=Supervisor(tmp_path/'out',[],ROOT)
    app={'key':'a','run':str(run),'source':str(ROOT),'failures':{}}
    folder=tmp_path/'issue';folder.mkdir()
    monkeypatch.setattr(sup,'evidence',lambda *args:folder)
    n=[0]
    def step(app,source):
        n[0]+=1
        if n[0]==1:return {'kind':'framework','reason':'bad','error':'bad','stage':'update','exit_code':1}
        write(run/'run_manifest.json',{'framework_source':str(source)})
        if trial_kind=='raises':raise ValueError('device failed')
        return {'kind':trial_kind,'reason':'paused_by_user','exit_code':1}
    monkeypatch.setattr(sup,'run_round',step)
    # The graph read is not reached for raised exceptions; elsewhere this is a failed trial.
    if trial_kind=='raises':
        with pytest.raises(ValueError):sup.tick(app,lambda *args:{'accepted':True,'source':str(ROOT),'source_hash':source_hash(ROOT)})
    else:
        sup.tick(app,lambda *args:{'accepted':True,'source':str(ROOT),'source_hash':source_hash(ROOT)})
        assert app['status']=={'service_blocked':'service_blocked','paused':'paused','device_wait':'waiting'}[trial_kind]
    assert json.loads((run/'run_manifest.json').read_text())['framework_source']==str(ROOT)


def test_fair_scheduling_reaches_third_app(tmp_path,monkeypatch):
    apps=[{'key':n,'run':str(tmp_path/n)} for n in ('a','b','c')];sup=Supervisor(tmp_path/'out',apps,ROOT);seen=[]
    def tick(app):
        seen.append(app['key']);app['status']='queued'
        if 'c' in seen:(sup.out/'STOP').touch()
    monkeypatch.setattr(sup,'tick',tick);sup.serve()
    assert 'c' in seen and len(seen)<=5


def test_saved_frame_http_is_charged_and_stops_at_limit(tmp_path):
    run,s,r=seed(tmp_path);write(run/'run_manifest.json',{'session_limits':{'max_http':1}})
    sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run)}
    sup.charge_luna(app)
    assert app['accounting']['http_started']==1
    assert json.loads((run/'run_manifest.json').read_text())['actual_model_calls']==1
    with pytest.raises(RuntimeError,match='budget'):sup.charge_luna(app)


def test_trial_repair_pending_is_not_accepted(tmp_path,monkeypatch):
    run,s,r=seed(tmp_path);sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run),'source':str(ROOT),'failures':{}}
    folder=tmp_path/'issue';folder.mkdir();monkeypatch.setattr(sup,'evidence',lambda *args:folder)
    outcomes=iter([{'kind':'framework','reason':'bad','error':'bad','stage':'update','exit_code':1},{'kind':'continue','reason':'repair_pending','exit_code':0}])
    monkeypatch.setattr(sup,'run_round',lambda *args:next(outcomes))
    monkeypatch.setattr(sup,'promote',lambda *args:pytest.fail('unresolved trial must not promote'))
    sup.tick(app,lambda *args:{'accepted':True,'source':str(ROOT),'source_hash':source_hash(ROOT)})
    assert not json.loads((folder/'live_trial.json').read_text())['accepted']


def test_repair_attempt_carries_previous_rejection(tmp_path):
    from debug_loop import read
    run,s,r=seed(tmp_path);sup=Supervisor(tmp_path/'out',[],ROOT)
    app={'key':'a','run':str(run),'source':str(ROOT),'failures':{},'graph':graph_summary(run)}
    log=tmp_path/'runner.log';log.write_text('error')
    issue={'kind':'framework','stage':'update','error':'bad','log':str(log)}
    first=sup.evidence(app,issue);write(first/'candidate_result.json',{'accepted':False,'reason':'missing context'})
    second=sup.evidence(app,issue)
    assert read(second/'previous_feedback.json')['result']['reason']=='missing context'
    assert (first/'candidate_result.json').exists()


def test_duplicate_app_keys_rejected(tmp_path):
    with pytest.raises(ValueError,match='unique'):
        Supervisor(tmp_path/'out',[{'key':'clock','run':'a'},{'key':'clock','run':'b'}],ROOT)


def test_three_rejected_repairs_stop_only_that_app(tmp_path,monkeypatch):
    run,s,r=seed(tmp_path);sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run),'source':str(ROOT),'failures':{}}
    log=tmp_path/'runner.log';log.write_text('bad')
    monkeypatch.setattr(sup,'run_round',lambda *args:{'kind':'framework','reason':'bad','stage':'update','error':'bad','log':str(log),'exit_code':1})
    repairs=[]
    def repair(*args):repairs.append(1);return {'accepted':False,'reason':'still bad'}
    for _ in range(4):sup.tick(app,repair)
    assert len(repairs)==3 and app['status']=='needs_attention'


def test_candidate_hash_checked_before_any_trial_dispatch(tmp_path,monkeypatch):
    run,s,r=seed(tmp_path);sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run),'source':str(ROOT),'failures':{}}
    folder=tmp_path/'issue';folder.mkdir();monkeypatch.setattr(sup,'evidence',lambda *args:folder)
    calls=[]
    def step(*args):calls.append(1);return {'kind':'framework','reason':'bad','stage':'update','error':'bad'}
    monkeypatch.setattr(sup,'run_round',step)
    with pytest.raises(ValueError,match='before live trial'):
        sup.tick(app,lambda *args:{'accepted':True,'source':str(ROOT),'source_hash':'stale'})
    assert calls==[1]


def test_same_issue_and_baseline_reuse_verified_candidate_once(tmp_path):
    sup=Supervisor(tmp_path/'out',[],ROOT)
    app={'source':str(ROOT)};candidate={'accepted':True,'source':str(ROOT),'source_hash':source_hash(ROOT)}
    sup.cache_version(ROOT,'same-error',candidate)
    assert sup.reusable(app,'same-error')==candidate
    assert sup.reusable(app,'different-error') is None
    app['tried_versions']=[candidate['source_hash']]
    assert sup.reusable(app,'same-error') is None


def test_apps_without_graph_remain_visible_in_queue_summary(tmp_path):
    sup=Supervisor(tmp_path/'out',[{'key':'missing','run':None}],ROOT)
    status=json.loads((sup.out/'status.json').read_text())
    assert status['counts']=={'no_graph':1}
    assert status['apps'][0]['key']=='missing'


def test_error_explanation_does_not_reset_attempt_identity():
    assert fingerprint({'kind':'framework','stage':'recovery_action','error':'窗口消失'})==fingerprint({'kind':'framework','stage':'recovery_action','error':'应用窗口无法恢复'})
    assert fingerprint({'kind':'framework','stage':'action'})!=fingerprint({'kind':'framework','stage':'update'})


def test_progress_loads_selected_candidate(tmp_path):
    from debug_loop import freeze
    source=freeze(ROOT,tmp_path/'candidate')
    (source/'debug_progress.py').write_text("def graph_summary(run,source):\n return {'complete':False,'progress_key':'candidate-behavior'}\n")
    assert graph_summary(tmp_path,source)['progress_key']=='candidate-behavior'


def test_review_validity_counts_as_progress(tmp_path,monkeypatch):
    import debug_progress
    from types import SimpleNamespace
    run,s,r=seed(tmp_path);valid=[False]
    coverage=lambda r,records=None:{'pending':[],'blocked':[],'complete':True,'inventory_complete':True}
    monkeypatch.setattr(debug_progress,'helper',lambda source,name:SimpleNamespace(coverage=coverage) if name=='region_tasks' else SimpleNamespace(review_current=lambda *args:valid[0]))
    before=debug_progress.graph_summary(run)
    valid[0]=True
    after=debug_progress.graph_summary(run)
    assert before['progress_key']!=after['progress_key']
    assert after['progress_key']==debug_progress.graph_summary(run)['progress_key']


def test_resume_preserves_old_wording_attempts(tmp_path):
    out=tmp_path/'out';write(out/'status.json',{'apps':[{'key':'app','run':str(tmp_path),'status':'queued','failures':{'old1':2,'old2':1}}]})
    issue={'kind':'framework','stage':'recovery_action','error':'one description'}
    for key in ('old1','old2'):write(out/'issues/app'/key/'attempt-01/issue.json',issue)
    sup=Supervisor(out,[])
    assert sup.apps[0]['failures']=={fingerprint(issue):3}
    sup.save()
    assert Supervisor(out,[]).apps[0]['failures']=={fingerprint(issue):3}


def test_old_source_without_progress_module_resumes(tmp_path):
    from debug_loop import freeze
    run,s,r=seed(tmp_path);source=freeze(ROOT,tmp_path/'old')
    (source/'debug_progress.py').unlink()
    assert graph_summary(run,source)==graph_summary(run,ROOT)


def test_candidate_hash_change_alone_is_not_live_progress(tmp_path,monkeypatch):
    import debug_loop
    from debug_loop import freeze
    run,s,r=seed(tmp_path);source=freeze(ROOT,tmp_path/'candidate')
    sup=Supervisor(tmp_path/'out',[],ROOT);app={'key':'a','run':str(run),'source':str(ROOT),'failures':{}}
    folder=tmp_path/'issue';folder.mkdir()
    monkeypatch.setattr(sup,'evidence',lambda *args:folder)
    monkeypatch.setattr(debug_loop,'graph_summary',lambda run,src:{'complete':False,'progress_key':'new' if str(src)==str(source) else 'old'})
    n=[0]
    def step(*args):
        n[0]+=1
        return {'kind':'framework','reason':'stalled','error':'stalled','stage':'stagnation','exit_code':0} if n[0]==1 else {'kind':'continue','reason':'updated','exit_code':0}
    monkeypatch.setattr(sup,'run_round',step)
    sup.tick(app,lambda *args:{'accepted':True,'source':str(source),'source_hash':source_hash(source)})
    assert app['source']==str(ROOT)
    assert not json.loads((folder/'live_trial.json').read_text())['accepted']
