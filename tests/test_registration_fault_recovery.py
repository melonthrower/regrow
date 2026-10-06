"""Faults use current acceptance paths; simulated replies are not Luna validation."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import mod, ROOT, seeded_run
from tests.test_shared_step_repair import strict_reply
from tests.test_stepwise_task_correction import Calls, answer, repair


def complete_reply():
    reply=strict_reply()
    for r in reply['regions']:r.update(task_review_reason='',controls_complete=True,out_of_scope_reason='',context_matches=None)
    for c in reply['controls']:c['click_bbox']=c['bbox']
    return reply


def test_discovery_and_bad_correction_then_good_correction_preserve_evidence(tmp_path):
    import locator
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','fault-case')
    q=locator.request_from_run(ROOT,run);good=complete_reply();bad=deepcopy(good)
    bad['controls'][0]['region_index']=99
    before=(run/'knowledge_current.json').read_bytes()
    old={p:p.read_bytes() for p in (run/'knowledge_snapshots').rglob('*.json')}
    class CheckedCalls(Calls):
        def __call__(self,request):
            assert (run/'knowledge_current.json').read_bytes()==before
            assert all(p.read_bytes()==value for p,value in old.items())
            return super().__call__(request)
    # The correction model fixes the index but invents an unknown identity.
    bad_fix=deepcopy(good);bad_fix['controls'][0]['previous_name']='Ghost'
    calls=CheckedCalls(run,[bad,answer('revise',bad_fix),answer('revise',good)])
    result=repair().Runner(ROOT,run,calls,None,lambda:10).perform('discovery',q)
    assert result['status']=='complete'
    assert len(calls.requests)==3
    assert all(p.read_bytes()==value for p,value in old.items())
    assert d.load(run)[2]['interactive_regions']==['r1']


def test_framework_publication_failure_keeps_old_pointer_then_retry(tmp_path):
    run=seeded_run(tmp_path);d=mod('discovery_step')
    before=(run/'knowledge_current.json').read_bytes()
    old={p:p.read_bytes() for p in (run/'knowledge_snapshots').rglob('*.json')}
    def fail(records,state,*args):
        records['r1']['description']='must not leak'
        raise OSError('injected before publication')
    with pytest.raises(OSError):d.publish(run,'fault',fail)
    assert (run/'knowledge_current.json').read_bytes()==before
    assert all(p.read_bytes()==v for p,v in old.items())
    d.publish(run,'recovered',lambda records,state,*args:state.update(audit_recovered=True))
    assert d.load(run)[2]['audit_recovered']
    assert d.load(run)[1]['r1']['description']!='must not leak'


def test_repeated_identical_bad_correction_stops_without_publishing(tmp_path):
    import locator
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','fault-case')
    q=locator.request_from_run(ROOT,run);bad=complete_reply();bad['controls'][0]['region_index']=99
    before=(run/'knowledge_current.json').read_bytes();calls=Calls(run,[bad,answer('revise',bad)])
    m=repair()
    with pytest.raises(m.Paused):m.Runner(ROOT,run,calls,None,lambda:10).perform('discovery',q)
    assert (run/'knowledge_current.json').read_bytes()==before
    assert len(calls.requests)==2


def test_failed_action_receipt_cannot_become_successful_update():
    updater=mod('result_updater')
    reply={'action_result':{'exception':'external_app'},'regions':[],'controls':[]}
    result=updater.route_update(ROOT,reply,{'exit_code':1},schema={'type':'object'})
    assert result['status']=='execution_unconfirmed' and result['next_action_mode']=='review_execution'
    result=updater.route_update(ROOT,reply,{'exit_code':0},schema={'type':'object'})
    assert result['status']=='validated_candidate' and result['next_action_mode']=='recover'




def test_real_update_transaction_keeps_action_without_false_completion(tmp_path):
    from tests.test_shared_step_repair import update_case
    run,q,reply=update_case(tmp_path);d=mod('discovery_step')
    def add_task(records,state,*args):
        records['r1']['tasks']={'inspect Settings':{'control':'c2','task_type':'single_action','action':'tap','status':'pending','attempts':[]}}
    d.publish(run,'add-task',add_task)
    snapshot,records,state=d.load(run)
    selection=run/'calls/selection';selection.mkdir()
    (selection/'request.json').write_text(json.dumps({'source':{'snapshot':str(snapshot.relative_to(run)),'observation':'o2'}}))
    (selection/'response.json').write_text('{}')
    binding_path=run/'action_attempts/a2/binding.json';binding=json.loads(binding_path.read_text());binding.update(task_region='r1',task_name='inspect Settings');binding_path.write_text(json.dumps(binding))
    q=mod('result_updater').build_update_request(ROOT,{'本轮探索任务':'inspect Settings','任务目标':{'type':'single_action'}},q['screenshots'])
    reply['action_result'].update(exception='none',returns_to_previous=False)
    reply['exploration_update'].pop('entry_name',None)
    reply['source_region_split']=None
    reply['previous_regions']=[{'name':'Menu','state':'retained_interactive','evidence':'still visible','context_matches':None}]
    reply['task_result']={'name':'inspect Settings','status':'done','evidence':'Policy clicked','findings':[]}
    evidence={p:p.read_bytes() for p in (run/'action_attempts/a2').iterdir() if p.is_file()}
    calls=Calls(run,[reply]);result=repair().Runner(ROOT,run,calls,None,lambda:10).perform('update',q,'a2')
    assert result['status']=='complete'
    region=d.load(run)[1]['r1']
    assert region['actions']['a2']['control']=='c1'
    assert region['tasks']['inspect Settings']['status']=='pending'
    assert all(p.read_bytes()==v for p,v in evidence.items())
