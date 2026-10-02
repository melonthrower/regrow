from copy import deepcopy
import json
import pytest
from PIL import Image
from tests.test_stepwise_deferral import setup
from tests.test_recovery_discovery import mod, ROOT


def case(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,*args):
        task=records['r1']['tasks']['Policy']
        task.update(task_type='parameter',action='input_text',attempts=['a1'])
        records['r1']['actions']['a1'].update(control=None,operation='input_text',text='Reset',
            association={'status':'unconfirmed'},delivery='executed_receipt_zero',
            result={'description':'Reset results visible','exception':'none'})
    d.publish(run,'parameter-case',seed)
    folder=run/'action_attempts/a1';folder.mkdir(exist_ok=True,parents=True)
    for when in ('before','after'):Image.new('RGB',(50,80)).save(folder/(when+'.png'))
    for name,value in [('commit',{}),('receipt',{'exit_code':0,'text_delivered':True}),('binding',{'control_ref':None})]:
        (folder/(name+'.json')).write_text(json.dumps(value))
    job={'path':'repair_episodes/old/episode.json','stage':'task_result_review','request':q,
         'status':'repair','candidate':{'name':'Policy','status':'done','evidence':'Reset results visible'},
         'call':'old-call','attempt':None,'repairs':2,'observations':1,'history':[{'error':'missing facts'}]}
    job['error']='参数任务缺少已登记参数事实，需先补观察登记'
    return run,d,job


def test_exhausted_review_hands_off_without_rewriting_action_or_resetting_counts(tmp_path):
    run,d,job=case(tmp_path);before=deepcopy(d.load(run)[1]['r1'])
    repair=mod('step_repair');repair.atomic(run/job['path'],job)
    repair.atomic(run/'pending_step.json',{'episode':job['path']})
    runner=repair.Runner(ROOT,run,lambda q:pytest.fail('handoff needs no model call'),None,lambda:0)
    with pytest.raises(repair.Paused) as exc:runner.perform('task_result_review')
    assert exc.value.status=='ready_next_round'
    archived=json.loads((run/job['path']).read_text())
    assert archived['repairs']==2 and archived['observations']==1 and archived['history']==job['history']
    assert not (run/'pending_step.json').exists()
    region=d.load(run)[1]['r1']
    assert region['actions']==before['actions'] and region['tasks']==before['tasks']
    assert region['task_inventory']['review']['kind']=='parameter_facts'
    _,records,state=d.load(run)
    q=mod('region_tasks').plan_request(ROOT,records,state,'r1')
    assert q['stage']=='task_proposal' and q['source']['parameter_fact_review']['task']=='Policy'
    assert q['screenshots'][-2:]==['action_attempts/a1/before.png','action_attempts/a1/after.png']
    assert 'unconfirmed' in q['user_prompt'] and 'Reset results visible' in q['user_prompt']
    region['task_inventory'].pop('review')
    d.publish(run,'consumed',lambda records,*args:records['r1']['task_inventory'].pop('review'))
    assert not mod('parameter_evidence_review').request_review(run,job)


@pytest.mark.parametrize('condition',['execution','service','blocked_task','not_done','wrong_name','has_facts','no_history','missing_frame'])
def test_handoff_does_not_bypass_other_missing_evidence(tmp_path,condition):
    run,d,job=case(tmp_path)
    if condition=='execution':(run/'execution_pending.json').write_text('{}')
    if condition=='service':job['service_failure']={'call':'failed'}
    if condition=='not_done':job['candidate']['status']='pending'
    if condition=='wrong_name':job['candidate']['name']='other'
    if condition=='missing_frame':(run/'action_attempts/a1/after.png').unlink()
    def alter(records,*args):
        t=records['r1']['tasks']['Policy']
        if condition=='blocked_task':t['status']='blocked'
        if condition=='has_facts':t['findings']={'existing':{}}
        if condition=='no_history':t['attempts']=[]
    d.publish(run,'alter',alter)
    pointer=(run/'knowledge_current.json').read_bytes()
    assert not mod('parameter_evidence_review').request_review(run,job)
    assert pointer==(run/'knowledge_current.json').read_bytes()


def test_normal_round_keeps_original_frames_in_fact_author_request(tmp_path,monkeypatch):
    run,d,job=case(tmp_path)
    assert mod('parameter_evidence_review').request_review(run,job)
    import run_task_step
    (run/'run_manifest.json').write_text(json.dumps({'device':'saved','app':'Clock'}))
    seen=[]
    class Transport:
        def save(self):self.ledger.write_text(json.dumps(self.account))
        def screenshot(self,p):p.write_bytes((run/'action_attempts/a1/after.png').read_bytes())
        def foreground_window(self):return {'saved_frame':True}
        def call(self,q):
            seen.append(q)
            raise run_task_step.step_repair.Paused('review_pending','inspect native request')
    monkeypatch.setattr(run_task_step,'RecoveryRun',Transport)
    monkeypatch.setattr(run_task_step,'execute_action',lambda *args:pytest.fail('no new GUI'))
    run_task_step.run_step(ROOT,run,tmp_path/'round')
    assert len(seen)==1 and seen[0]['stage']=='task_proposal'
    assert seen[0]['source']['parameter_fact_review']['task']=='Policy'
    assert seen[0]['screenshots'][0].endswith('/round/current.png')
    assert seen[0]['screenshots'][1:]==['action_attempts/a1/before.png','action_attempts/a1/after.png']
