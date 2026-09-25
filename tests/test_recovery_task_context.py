from pathlib import Path
from copy import deepcopy
import importlib.util
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def evidence():
 task={'name':'观察服务启动','reason':'启动一次并观察反馈','status':'blocked','handling':'explore','attempts':['a1'],'result_evidence':'出现权限弹窗'}
 return {'r1':{'name':'服务区','tasks':{'观察服务启动':task}},'r2':{'name':'其他区','tasks':{'无关':{**task,'attempts':['a2']}}}}, {'attempt':'a1'}

def test_interrupted_task_comes_from_attempt_not_current_work():
 records,state=evidence();state['working_region']='r2';before=deepcopy((records,state))
 rows=load('recovery').interrupted_tasks(records,state)
 assert len(rows)==1 and rows[0]['区块']=='服务区'
 assert rows[0]['任务依据与范围']=='启动一次并观察反馈'
 assert (records,state)==before

def test_recovery_fact_survives_consumed_discovery_handoff(tmp_path,monkeypatch):
 m=load('discovery_step');records,state=evidence();frame=tmp_path/'frame.png';frame.write_bytes(b'frame')
 monkeypatch.setattr(m,'publish',lambda run,tag,mutate:mutate(records,state,None,None))
 m.await_discovery(tmp_path,str(frame),'recovery-0057','权限已拒绝，服务仍未启动')
 state.pop('recovery_handoff',None);state['handoff_summary']='新前景'
 task=records['r1']['tasks']['观察服务启动']
 assert task['status']=='blocked'
 assert '出现权限弹窗' in task['result_evidence'] and '权限已拒绝' in task['result_evidence']
 assert 'recovery-0057' in task['result_evidence']
 assert records['r2']['tasks']['无关']['result_evidence']=='出现权限弹窗'
 prior=task['result_evidence'];m.await_discovery(tmp_path,str(frame),'recovery-0057','权限已拒绝，服务仍未启动')
 assert task['result_evidence']==prior

def test_cleared_exception_preserves_handoff_without_followup_action():
 m=load('recovery');reply={'exception':'none','decision':'resume_exploration','action':None,'framework_tool':None,'reason':'弹窗消失','handoff':'权限已拒绝，未录音'}
 result=m.resolve(reply)
 assert reply['handoff'] in result['handoff'] and result['action'] is None

def test_recovered_blocked_task_is_reviewed_once_without_being_completed(tmp_path,monkeypatch):
 m=load('discovery_step');records,state=evidence();frame=tmp_path/'frame.png';frame.write_bytes(b'frame')
 records['r1']['id']='r1'
 monkeypatch.setattr(m,'publish',lambda run,tag,mutate:mutate(records,state,None,None))
 m.await_discovery(tmp_path,str(frame),'recovery-0057','权限已拒绝，服务未启动')
 t=records['r1']['tasks']['观察服务启动'];review=load('task_result_review');state['observation']={'id':'new'}
 assert review.reviewable(t,'new')
 with pytest.raises(ValueError):review.apply(records['r1'],state,'观察服务启动',{'name':'观察服务启动','status':'done','evidence':'弹窗消失'},'0058')
 review.apply(records['r1'],state,'观察服务启动',{'name':'观察服务启动','status':'blocked','evidence':'权限尚未满足'},'0058')
 assert not review.reviewable(t,'later')
 m.await_discovery(tmp_path,str(frame),'recovery-0057','权限已拒绝，服务未启动')
 assert not review.reviewable(t,'later')
 assert '权限已拒绝' in t['deferral']['reason']

def test_recovery_must_not_replace_crash_or_policy_blocker(tmp_path,monkeypatch):
 m=load('discovery_step');records,state=evidence();t=records['r1']['tasks']['观察服务启动']
 t['blocker']={'condition':'review_required','reason':'禁止修改环境'};t['deferral']={'retry_when':'范围变化'}
 before=deepcopy(t);frame=tmp_path/'frame.png';frame.touch()
 monkeypatch.setattr(m,'publish',lambda run,tag,mutate:mutate(records,state,None,None))
 m.await_discovery(tmp_path,str(frame),'recovery-0057','弹窗消失')
 assert t['blocker']==before['blocker'] and t['deferral']==before['deferral']
 assert not load('task_result_review').reviewable(t,'new')

def test_exit_detected_during_recovery_keeps_real_crash_blocker(tmp_path,monkeypatch):
 from types import SimpleNamespace
 loop=load('recover_loop');reg=load('register_update');policy=load('recovery')
 records,state=evidence();t=records['r1']['tasks']['观察服务启动'];t['status']='pending'
 state.update(next_action_mode='recover',active_task={'region':'r1','name':'观察服务启动'},source_call='failed',exception='blocking_popup')
 discovery=SimpleNamespace(load=lambda run:(None,records,state),publish=lambda run,tag,mutate:mutate(records,state,None,None))
 actual=loop.helper
 monkeypatch.setattr(loop,'helper',lambda n:discovery if n=='discovery_step' else actual(n))
 monkeypatch.setattr(loop,'stalled',lambda *a:False)
 transport=SimpleNamespace(run=tmp_path,package='test',platform='android',account={'gui_started':0,'http_started':0,'max_http':1},screenshot=lambda p:p.write_bytes(b'frame'))
 reply={'exception':'unexpected_exit','decision':'stop','action':None,'framework_tool':None,'reason':'恢复时目标应用意外退出，原因未确认','handoff':'仍不可操作'}
 loop.run(ROOT,transport,tmp_path/'out',lambda q:('exit-call',reply))
 assert t['status']=='blocked' and t['blocker']['exception']=='unexpected_exit'
 assert t['deferral']['retry_when']=='explicit_crash_cause_resolved'
 assert not load('task_result_review').reviewable(t,'later')

def test_scope_is_provided_by_run_not_inferred_from_task(tmp_path):
 import sys,json
 sys.path.insert(0,str(ROOT));m=load('recover_external');q={'user_prompt':'任务要求','source':{'task_name':'新增权限任务'}}
 assert m.with_run_scope(q,tmp_path)==q
 (tmp_path/'run_manifest.json').write_text(json.dumps({'exploration_scope':'仅测试环境内应用功能，必要权限取最小范围'}))
 new=m.with_run_scope(q,tmp_path)
 assert '仅测试环境内应用功能' in new['user_prompt'] and q['user_prompt']=='任务要求'
