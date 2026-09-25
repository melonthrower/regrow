import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
spec=importlib.util.spec_from_file_location('deferred_task_review',ROOT/'task_result_review.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def task():
 return {'status':'blocked','handling':'explore','attempts':[], 'blocker':{'condition':'review_required'},
         'deferral':{'trigger':{'kind':'exploration_loop'},'reason':'导航重复，没有到达菜单','switch_call':'0014'}}

def test_only_untried_loop_suspensions_and_one_review_per_observation():
 t=task();assert m.reviewable(t,'obs1')
 t['deferral']['reviewed_observation']='obs1';assert not m.reviewable(t,'obs1')
 assert not m.reviewable(t,'obs2')
 t['deferral'].pop('reviewed_observation')
 t['attempts']=['a1'];assert not m.reviewable(t,'obs2')
 t['attempts']=[];t['deferral']['trigger']['kind']='model_service_error';assert not m.reviewable(t,'obs2')
 t['deferral']['trigger']['kind']='exploration_loop';t['blocker']['exception']='unexpected_exit';assert not m.reviewable(t,'obs2')

def test_review_reopens_only_selected_task_without_erasing_failure():
 t=task();other=task();r={'id':'r1','tasks':{'menu':t,'other':other}};state={'observation':{'id':'obs1'}}
 m.apply(r,state,'menu',{'name':'menu','status':'pending','evidence':'当前菜单按钮可见；直接打开菜单，避开原来的页签循环'},'0020')
 assert t['status']=='pending' and other['status']=='blocked'
 assert t['deferral']['reason']=='导航重复，没有到达菜单'
 assert t['deferral']['reviewed_observation']=='obs1'
 assert t['blocker_history'][-1]['resolved_by']=='0020'
 assert state['working_region']=='r1'

def test_review_cannot_complete_untried_task_and_blocked_is_not_repeated():
 t=task();r={'id':'r1','tasks':{'menu':t}};s={'observation':{'id':'obs1'}}
 with pytest.raises(ValueError):m.apply(r,s,'menu',{'name':'menu','status':'done','evidence':'按钮可见'},'0020')
 assert t['status']=='blocked'
 m.apply(r,s,'menu',{'name':'menu','status':'blocked','evidence':'仍无不同的可行方法'},'0021')
 assert t['deferral']['reason']=='导航重复，没有到达菜单'
 assert not m.reviewable(t,'obs1')
