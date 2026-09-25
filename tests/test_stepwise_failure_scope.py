from copy import deepcopy
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def test_function_gap_does_not_hide_other_gui_work(tmp_path):
    run,q,d=setup(tmp_path);_,r,s=d.load(run)
    r['r2']=deepcopy(r['r1']);r['r2']['registration_gaps']={'function_registration':{'reason':'model error'}}
    s['working_region']='r1';s['interactive_regions']=['r1']
    assert tasks().helper('task_deferral').choose_unfinished(r,s)['region']=='r2'


def test_task_failure_does_not_block_other_action_on_same_control(tmp_path):
    run,q,d=setup(tmp_path);_,r,s=d.load(run);region=r['r1']
    region['tasks']['Policy']['status']='blocked'
    region['tasks']['Settings']['control']=region['tasks']['Policy']['control']
    assert [n for n,t in tasks().helper('task_deferral').pending_tasks(region)]==['Settings']


def test_failed_inventory_not_immediately_reproposed_without_new_evidence(tmp_path):
    run,q,d=setup(tmp_path);_,r,s=d.load(run)
    r['r2']=deepcopy(r['r1']);r['r2']['tasks']={};r['r2']['task_inventory']={}
    r['r2']['registration_gaps']={'task_proposal':{'reason':'unresolved'}}
    s['working_region']='r1';s['interactive_regions']=['r1']
    assert tasks().helper('task_deferral').choose_unfinished(r,s) is None
    r['r2']['registration_gaps']['task_proposal']['recheck_after']='new-evidence'
    assert tasks().helper('task_deferral').choose_unfinished(r,s)['region']=='r2'


def test_historical_function_failure_only_blocks_extraction(tmp_path):
    run,q,d=setup(tmp_path);q['source']['observation']='historical'
    job={'stage':'function_registration','request':q,'path':'repair_episodes/extract/episode.json','call':'failed'}
    result=tasks().helper('task_deferral').defer(run,job,'service unavailable')
    assert result is not None
    _,records,state=d.load(run)
    assert all(t['status']=='pending' for t in records['r1']['tasks'].values())
    assert 'function_registration' in records['r1']['registration_gaps']


def test_transient_service_error_retries_identical_request_once(tmp_path,monkeypatch):
    import json,subprocess,pytest
    from tests.test_stepwise_task_correction import repair
    run,q,d=setup(tmp_path);m=repair();seen=[]
    def call(request):
        seen.append(deepcopy(request))
        if len(seen)==1:
            folder=run/'calls/transient';folder.mkdir(parents=True)
            (folder/'http_error.json').write_text('{"status":503}')
            (run/'run_manifest.json').write_text('{"last_call":"transient"}')
            raise subprocess.CalledProcessError(1,['model'])
        return 'success',{'ok':True}
    runner=m.Runner(__import__('tests.test_recovery_discovery',fromlist=['ROOT']).ROOT,run,call,None,lambda:5)
    monkeypatch.setattr(runner.adapters,'accept',lambda *a:{'ok':True})
    result=runner.perform('action',q)
    assert result['status']=='complete' and len(seen)==2 and seen[0]==seen[1]
    assert len(result['service_error_history'])==1 and result['service_retry_used']
