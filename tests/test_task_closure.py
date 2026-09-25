from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def fixture():
 t={'control':'recent','status':'pending','handling':'explore','task_type':'single_action','action':'click','reason':'observe Music','attempts':[]}
 r={'id':'r','name':'Sidebar','controls':{'recent':{'name':'Recent','task_refs':['Music']},'music':{'name':'Music','task_refs':[]}},'tasks':{'Music':t},'functions':{},'task_inventory':{'inventory':'complete'}}
 return r,{'active_task':{'region':'r','name':'Music'}}


def test_rebind_only_unexecuted_task_and_rebuild_refs():
 r,s=fixture();m=mod('task_record_repair')
 m.apply(r,s,{'task':'Music','field':'task_control','before':'Recent','after':'Music','evidence':'distinct visible rows'},'review')
 assert r['tasks']['Music']['control']=='music'
 assert r['controls']['recent']['task_refs']==[] and r['controls']['music']['task_refs']==['Music']


@pytest.mark.parametrize('history',[{'attempts':['a1']},{'findings':{'x':{}}},{'equivalent_to':'Other'}])
def test_history_cannot_move_with_task(history):
 r,s=fixture();r['tasks']['Music'].update(history);before=deepcopy(r)
 with pytest.raises(ValueError):mod('task_record_repair').apply(r,s,{'task':'Music','field':'task_control','before':'Recent','after':'Music','evidence':'visible'},'review')
 assert r==before


def test_suspend_preserves_history_and_reopens_inventory():
 r,s=fixture();r['tasks']['Music']['attempts']=['a1'];r['tasks']['Music']['findings']={'value':{'source':'Recent'}}
 mod('task_record_repair').apply(r,s,{'task':'Music','field':'suspend_task','before':'Recent','after':'','evidence':'wrong owner'},'review')
 t=r['tasks']['Music'];assert t['control']=='recent' and t['attempts']==['a1'] and t['findings']=={'value':{'source':'Recent'}}
 assert t['status']=='blocked' and 'active_task' not in s and r['task_inventory']['review']


def test_no_action_review_signal_does_not_deliver_or_skip():
 p={'action':'none','target':'Music','x':None,'y':None,'text':None,'end_x':None,'end_y':None,'reason':'history answers goal','skip_task':False,'request_task_review':True}
 mod('action_commands').validate(p)
 assert mod('action_commands').commands(p)==[]
 for change in [{'action':'click','x':4,'y':5},{'skip_task':True}]:
  with pytest.raises(ValueError):mod('action_commands').validate({**p,**change})


def test_review_settles_without_new_attempt():
 r,s=fixture();t=r['tasks']['Music'];t['attempts']=['a1'];r['actions']={'a1':{'control':'recent','delivery':'executed_receipt_zero','result':{'description':'opened Music'}}}
 before=deepcopy(r['actions']);mod('task_result_review').apply(r,s,'Music',{'name':'Music','status':'done','evidence':'a1 observed destination'},'review')
 assert t['status']=='done' and t['attempts']==['a1'] and r['actions']==before and 'active_task' not in s


def test_review_without_history_cannot_claim_done():
 r,s=fixture()
 with pytest.raises(ValueError):mod('task_result_review').apply(r,s,'Music',{'name':'Music','status':'done','evidence':'probably done'},'review')
 assert r['tasks']['Music']['status']=='pending'


def test_suspended_ownership_not_completed_by_entry_reuse(monkeypatch):
 r,s=fixture();r['tasks']['Music']['attempts']=['a1']
 mod('task_record_repair').apply(r,s,{'task':'Music','field':'suspend_task','before':'Recent','after':'','evidence':'wrong owner'},'review')
 m=mod('entry_evidence')
 monkeypatch.setattr(m,'known_entries',lambda *args:[{'description':'opened Recent','destination_region':'other'}])
 m.reuse(r)
 assert r['tasks']['Music']['status']=='blocked'


def test_review_commit_uses_existing_update_repair_without_attempt(tmp_path):
 import json
 from tests.test_recovery_discovery import seeded_run, ROOT
 from tests.test_stepwise_task_correction import Calls, repair
 run=seeded_run(tmp_path);d=mod('discovery_step')
 def seed(records,state,*args):
  r=records['r1'];r['tasks']={'inspect':{'control':'c1','status':'pending','handling':'explore','task_type':'single_action','reason':'observe destination','attempts':['a1']}}
  state['active_task']={'region':'r1','name':'inspect'}
 d.publish(run,'review-seed',seed)
 before=d.load(run)[1]['r1']
 q=mod('task_result_review').request(ROOT,run,{'task_region':'r1','task_name':'inspect'},[str(run/'returned.png')])
 calls=Calls(run,[{'name':'inspect','status':'done','evidence':'a1 observed destination'}])
 result=repair().Runner(ROOT,run,calls,None,lambda:3).perform('task_result_review',q)
 after=d.load(run)[1]['r1'];state=d.load(run)[2]
 assert result['status']=='complete' and after['tasks']['inspect']['status']=='done'
 assert after['actions']==before['actions'] and after['tasks']['inspect']['attempts']==['a1']
 assert 'active_task' not in state and not (run/'execution_pending.json').exists()


@pytest.mark.parametrize('retry',['explicit_task_ownership_review','explicit_result_review'])
def test_explicit_review_blockers_survive_entry_reuse(retry,monkeypatch):
 r,s=fixture();t=r['tasks']['Music'];t.update(status='blocked',deferral={'retry_when':retry})
 m=mod('entry_evidence');monkeypatch.setattr(m,'known_entries',lambda *a:[{'attempt':'a1','description':'old destination','destination_region':'other'}])
 m.reuse(r);assert t['status']=='blocked'


def test_suspended_equivalent_keeps_coverage_gap():
 r,s=fixture();r['tasks']['Music'].update(handling='equivalent',equivalent_to='canonical',status='blocked',deferral={'retry_when':'explicit_task_ownership_review'})
 r['tasks']['canonical']={**r['tasks']['Music'],'handling':'explore','status':'done'}
 assert 'Music' in mod('region_tasks').coverage(r)['blocked']


def test_function_dependency_prevents_rebinding():
 r,s=fixture();r['functions']={'open':{'task_refs':['Music']}}
 with pytest.raises(ValueError):
  mod('task_record_repair').apply(r,s,{'task':'Music','field':'task_control','before':'Recent','after':'Music','evidence':'visible'},'review')
 assert r['tasks']['Music']['control']=='recent'
