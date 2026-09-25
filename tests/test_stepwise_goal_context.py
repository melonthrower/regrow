from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import fixture,ROOT
from tests.test_stepwise_region_tasks import tasks,proposal,row


def scenario():
    flow,records,state=fixture();state.update(working_region='menu',interactive_regions=['menu'])
    region=records['menu'];region['controls']['missing']={'name':'候选条目','observations':[],'action_refs':[]}
    plan=[row('观察选择结果','missing'),row('准备入口','open',handling='record')]
    plan[0]['control']='候选条目';plan[1]['control']=region['controls']['open']['name']
    tasks().apply_plan(region,proposal(plan),'plan')
    region['actions']['clear']={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':{'description':'已清空内容，候选列表消失。','exception':'none'}}
    state['last_action_result']={'region':'menu','action':'clear'}
    return flow,records,state


def test_missing_target_uses_normal_action_and_program_history():
    flow,r,s=scenario();before=deepcopy((r,s));q=tasks().attach(ROOT,r,s,'menu',{})
    assert q['stage']=='action_selection' and q['action_ready']
    assert not q.get('needs_task_inspection') and q['allow_input']
    assert [c['id'] for c in q['backend_candidates']]==['open']
    assert '当前目标：观察选择结果' in q['user_prompt']
    assert '已清空内容，候选列表消失。' in q['user_prompt']
    assert '尚未完成：观察选择结果' in q['user_prompt']
    assert (r,s)==before
    r['menu']['actions']['clear']['result']['description']='另一条真实观察'
    assert '另一条真实观察' in tasks().attach(ROOT,r,s,'menu',{})['user_prompt']


def test_preparation_does_not_complete_original_single_action_task():
    _,r,s=scenario();region=r['menu'];before=deepcopy(region)
    reply={'action_result':{'exception':'none'},'task_result':{'name':'观察选择结果','status':'pending','evidence':'只打开准备入口，尚无目标反馈','findings':[]}}
    binding={'task_name':'观察选择结果','preparatory_action':True,'region_ref':'menu','control_ref':'open'}
    tasks().settle_task(region,binding,reply,'prep')
    assert region['tasks']['观察选择结果']['status']=='pending'
    assert region['tasks']['观察选择结果']['attempts']==['prep']


def test_visible_goal_does_not_hide_other_current_controls():
    flow,r,s=scenario();r['menu']['controls']['missing']['observations']=[{'image':'other.png','icon_description':'row','evidence':{'observation':'now'}}];s['observation']['control_refs'].append('missing')
    q=tasks().attach(ROOT,r,s,'menu',{})
    assert {c['id'] for c in q['backend_candidates']}=={'open','missing'}


def test_parameter_continues_across_multiple_visible_regions_instead_of_returning():
    _,r,s=scenario();task=r['menu']['tasks']['观察选择结果'];task['task_type']='parameter'
    s.update(active_task={'region':'menu','name':'观察选择结果'},interactive_regions=['main','middle'])
    s['observation']['control_refs']=[cid for rid in s['interactive_regions'] for cid in r[rid]['controls']]
    q=tasks().attach(ROOT,r,s,'menu',{'navigation_advice':True,'navigation_path':['old route']})
    assert q['stage']=='task_proposal'
    r['main']['task_inventory']={'inventory':'complete','controls':list(r['main']['controls'])}
    q=tasks().attach(ROOT,r,s,'menu',{})
    assert q['source']['task_region']=='menu' and q['source']['task_name']=='观察选择结果'
    assert not q.get('navigation_advice') and 'return_to' not in q['source']
    assert {c['region_ref'] for c in q['backend_candidates']}=={'main','middle'}


def test_in_flight_goal_overrides_automatic_route_to_its_owner():
    _,r,s=scenario();task=r['menu']['tasks']['观察选择结果'];task['attempts']=['already_clicked']
    s.update(active_task={'region':'menu','name':'观察选择结果'},interactive_regions=['main','middle'],visual_navigation=True,deferred_routing_target='menu')
    r['main']['task_inventory']={'inventory':'complete','controls':list(r['main']['controls'])}
    q=tasks().attach(ROOT,r,s,'menu',{'navigation_advice':True,'navigation_path':['return to menu']})
    assert q['source']['task_region']=='menu' and q['source']['task_name']=='观察选择结果'
    assert not q.get('navigation_advice') and not q.get('navigation_path')
    assert {c['region_ref'] for c in q['backend_candidates']}=={'main','middle'}
    assert '已清空内容' in q['user_prompt']


def test_unstarted_single_action_still_navigates_to_its_control():
    _,r,s=scenario();s.update(active_task={'region':'menu','name':'观察选择结果'},interactive_regions=['main'],visual_navigation=True)
    base={'navigation_advice':True,'navigation_path':['return to menu']}
    assert tasks().attach(ROOT,r,s,'menu',base)==base


def test_completed_surface_uses_known_route_instead_of_inventing_return():
    flow,r,s=fixture();m=tasks()
    r['main']['controls']={};m.apply_plan(r['main'],proposal([]),'p')
    # Actual source control must stay registered for a known navigation edge.
    r['main']['controls']['open']={'name':'打开主体','observations':[{'image':'crop.png','icon_description':'菜单','evidence':{'observation':'now'}}],'action_refs':[]}
    r['main']['task_inventory']['controls']=['open']
    s.update(working_region='menu',interactive_regions=['main'],region_path=['menu','main'])
    base=flow.assemble_context(ROOT,r,s,'menu')
    q=m.attach(ROOT,r,s,'menu',base)
    assert q.get('navigation_advice') and q['navigation_path'][0]['attempt']=='a3'
    assert '最短已知路径' in q['user_prompt']
    assert '本轮任务：退出' not in q['user_prompt']


def test_navigation_handoff_is_not_replaced_by_local_unrelated_task():
    flow,r,s=fixture();m=tasks()
    s.update(working_region='menu',interactive_regions=['middle'])
    m.apply_plan(r['middle'],proposal([row('检查路过菜单','打开中间区')]),'plan')
    base=flow.assemble_context(ROOT,r,s,'menu')
    assert base['navigation_advice']
    q=m.attach(ROOT,r,s,'menu',base)
    assert q['navigation_advice'] and q['source'].get('task_name') is None
    assert q['source']['return_to']=='menu'


def test_continuing_parent_task_discloses_current_region_work():
    _,r,s=scenario();m=tasks();r['menu']['tasks']['观察选择结果']['task_type']='parameter'
    s.update(active_task={'region':'menu','name':'观察选择结果'},interactive_regions=['main'])
    current=r['main'];current['tasks']={'编辑当前字段':{'control':next(iter(current['controls'])),'name':'编辑当前字段','action':'input_text','handling':'explore','status':'pending','task_type':'parameter','reason':'测试输入','attempts':[]}}
    current['external_entry_policy']='record_only';current['task_inventory']={'inventory':'complete','controls':list(current['controls'])}
    s['observation']['control_refs']=list(current['controls'])
    q=m.attach(ROOT,r,s,'menu',{})
    assert '当前目标：观察选择结果' in q['user_prompt']
    assert '编辑当前字段' in q['user_prompt']
    assert '准备入口：仅记录' not in q['user_prompt']
    assert q['source']['task_region']=='menu'
