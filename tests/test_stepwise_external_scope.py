from copy import deepcopy
from tests.test_stepwise_region_tasks import tasks,row,proposal
from tests.test_stepwise_resume_route import fixture,ROOT
from tests.test_stepwise_task_correction import saved


def test_scope_review_can_record_external_task_without_erasing_history():
    _,records,_=fixture();m=tasks();r=records['menu']
    m.apply_plan(r,proposal([row()]),'old');r['tasks']['查看内容']['attempts']=['a1']
    old=deepcopy(r['tasks']['查看内容'])
    reply=proposal([{**row(handling='record'),'reason':'入口显示外部网站URL，按范围只记录'}])
    m.apply_plan(r,reply,'review',scope_review=True)
    t=r['tasks']['查看内容']
    assert t['status']=='record_only' and t['attempts']==['a1']
    assert t['scope_history'][0]['status']==old['status']
    assert m.coverage(r)['complete']


def test_known_external_is_skipped_but_ordinary_unknown_task_remains(tmp_path):
    run,q,_=saved(tmp_path);d=tasks().helper('discovery_step');scope=tasks().helper('traversal_scope')
    def seed(records,state,*args):
        r=records['r1'];r['tasks']={
          'policy':{'control':'c1','handling':'explore','status':'pending','attempts':['a1'],'reason':'observe'},
          'settings':{'control':'c2','handling':'explore','status':'pending','attempts':[],'reason':'unknown'}}
        state.update(next_action_mode='explore',active_task={'region':'r1','name':'policy'})
    d.publish(run,'policy-seed',seed)
    before=d.load(run)[1]['r1']['actions']
    assert scope.exclude_known_external(run)
    _,r,s=d.load(run)
    assert r['r1']['tasks']['policy']['status']=='record_only'
    assert r['r1']['tasks']['settings']['status']=='pending'
    assert r['r1']['actions']==before and 'active_task' not in s
    assert not scope.exclude_known_external(run)


def test_visible_completed_work_is_retired(tmp_path,monkeypatch):
    import traversal_scheduler
    run,q,_=saved(tmp_path);d=tasks().helper('discovery_step');original_helper=traversal_scheduler.helper
    def seed(records,state,*args):
        r=records['r1'];r['tasks']={};r['controls']={};r['task_inventory']={'inventory':'complete','controls':[]}
        state.update(next_action_mode='explore',working_region='r1',interactive_regions=['r1'])
    d.publish(run,'complete-visible',seed)
    calls=[]
    from types import SimpleNamespace
    monkeypatch.setattr(traversal_scheduler,'helper',lambda name:SimpleNamespace(advance_unfinished=lambda run:calls.append(run) or {'region':'next'}) if name=='task_deferral' else original_helper(name))
    assert traversal_scheduler.retire_completed_goal(run) and calls==[run]


def test_service_scope_review_keeps_attempts_without_claiming_execution():
    _,records,_=fixture();m=tasks();r=records['menu']
    m.apply_plan(r,proposal([row('关闭对话框')]),'old')
    original=deepcopy(r['tasks']['关闭对话框'])
    m.apply_plan(r,proposal([{**row('关闭对话框',handling='record'),'reason':'纯退出服务动作，需要离开时使用，不为验证退出重新进入'}]),'review',scope_review='task_scope_review')
    t=r['tasks']['关闭对话框']
    assert t['status']=='record_only' and t['attempts']==original['attempts']==[]
    assert t['scope_exclusion']['policy']=='task_scope_review'
    assert t['scope_history'][0]['status']=='pending'
    assert m.coverage(r)['complete']


def test_scope_review_cannot_silently_skip_unfinished_tasks():
    import pytest
    _,records,_=fixture();m=tasks();r=records['menu']
    m.apply_plan(r,proposal([row()]),'old')
    with pytest.raises(ValueError,match='遗漏'):
        m.apply_plan(r,proposal([]),'review',scope_review='task_scope_review')
    assert r['tasks']['查看内容']['status']=='pending'


def test_scope_review_discloses_later_foreground_for_active_owner(monkeypatch):
    from types import SimpleNamespace
    import json
    scope=tasks().helper('traversal_scope')
    monkeypatch.setattr(scope,'helper',lambda name:SimpleNamespace(plan_request=lambda *args:{'user_prompt':'{"已有任务":[]}','system_prompt':'rules','fixed_parts':[]}))
    state={'active_task':{'region':'r','name':'反馈'},'exception':'external_app','source_call':'later','handoff_summary':'外部反馈页面'}
    q=scope.review_request(ROOT,{'r':{'tasks':{}}},state,'r')
    assert json.loads(q['user_prompt'])['当前任务后续观察']['来源调用']=='later'
    state['active_task']['region']='other'
    assert '当前任务后续观察' not in json.loads(scope.review_request(ROOT,{'r':{'tasks':{}}},state,'r')['user_prompt'])


def test_completed_discovery_target_switches_without_claiming_location(tmp_path):
    import traversal_scheduler
    run,_,_=saved(tmp_path);d=tasks().helper('discovery_step')
    def seed(records,state,*args):
        r=records['r1'];r['tasks']={};r['controls']={};r['task_inventory']={'inventory':'complete','controls':[]}
        records['next']={**deepcopy(r),'id':'next','name':'new target','task_inventory':{'inventory':'partial','controls':[]}}
        state.update(next_action_mode='discover',working_region='r1',interactive_regions=[],observation=None,
                     inspection_region='r1',required_control='old',discovery_mode='local',pending_frame='latest.png')
    d.publish(run,'complete-awaiting-location',seed)
    assert traversal_scheduler.retire_completed_goal(run)
    _,_,state=d.load(run)
    assert state['working_region']=='next'
    assert state['next_action_mode']=='discover' and state['observation'] is None
    assert state['interactive_regions']==[] and state['pending_frame']=='latest.png'
    assert state['discovery_mode']=='relocate'
    assert 'inspection_region' not in state and 'required_control' not in state
