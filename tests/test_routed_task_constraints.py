from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks,proposal,row
from tests.test_stepwise_resume_route import fixture,ROOT


def setup_chain():
    flow,r,s=fixture()
    r['menu']['controls']={}
    r['middle']['reached_by']=[{'source_region':'main','source_control':'open','attempt':'a1'}]
    r['menu']['reached_by']=[{'source_region':'middle','source_control':'open','attempt':'a2'}]
    s['interactive_regions']=['menu'];s['working_region']='menu'
    tasks().apply_plan(r['menu'],proposal([]),'inventory')
    return flow,r,s


def test_menu_and_child_return_to_immediate_observed_parent_even_if_working_here():
    flow,r,s=setup_chain();m=tasks();routing=m.helper('task_routing')
    assert routing.entry_path(r,'menu')==['main','middle','menu']
    q=m.attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q['source']['return_to']=='middle'
    before=deepcopy(r)
    next_state={'interactive_regions':['middle']}
    routing.advance(r,s,next_state,'menu',{},'back')
    assert next_state['region_path']==['main','middle'] and r==before


def test_parameter_task_continues_in_child_without_becoming_child_task():
    flow,r,s=setup_chain();m=tasks()
    p=row(control='打开中间区');p['task_type']='parameter'
    m.apply_plan(r['middle'],proposal([p]),'plan')
    s['active_task']={'region':'middle','name':'查看内容'}
    q=m.attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q['source']['region']=='menu' and q['source']['task_region']=='middle'
    assert q['allow_input'] and q['allow_back']
    assert q['source']['task_name']=='查看内容'
    assert 'input_text' in q['response_schema']['properties']['action']['enum']


def test_scroll_is_region_owned_and_cannot_claim_done_from_delivery_only():
    flow,r,s=fixture();m=tasks();r['menu']['controls']={}
    p=row(control='');p.update(task_type='scroll',action='scroll')
    m.apply_plan(r['menu'],proposal([p]),'plan')
    assert r['menu']['tasks']['查看内容']['control'] is None
    assert not m.coverage(r['menu'])['complete']


def alarm_region():
    m=tasks();flow,r,s=fixture();region=r['menu'];region['name']='闹钟编辑'
    operations=[]
    facts=[('时间','time',[], '07:00'),('周期','enum',['每周六','每天'],'每周六'),('振动','enum',['开启','关闭'],'开启'),('标签','text',[],'早饭')]
    for name,kind,values,value in facts:
        p=row(name=name);p['task_type']='parameter';operations.append(p)
    m.apply_plan(region,proposal(operations),'plan')
    for name,kind,values,value in facts:
        reply={'action_result':{'exception':'none'},'task_result':{'name':name,'status':'done','evidence':'测试夹具中的已观察参数',
            'findings':[{'name':name,'description':'已观察'+name,'domain':{'type':kind,'values':values,'min':None,'max':None},'conditions':[], 'evidence':'明确的控件输入或选项观察'}]}}
        m.settle_task(region,{'task_name':name,'task_region':'menu','region_ref':'menu','control_ref':region['tasks'][name]['control']},reply,'attempt_'+name)
    return m,region,facts


def test_parameter_done_requires_facts_and_command_input_does_not_fake_unicode():
    flow,r,s=fixture();m=tasks();p=row();p['task_type']='parameter';m.apply_plan(r['menu'],proposal([p]),'p')
    with pytest.raises(ValueError):m.settle_task(r['menu'],{'task_name':'查看内容'},
        {'action_result':{'exception':'none'},'task_result':{'name':'查看内容','status':'done','evidence':'clicked','findings':[]}},'a')
    commands=m.helper('action_commands').commands
    assert len(commands({'action':'input_text','x':1,'y':2,'text':'Breakfast'}))==2
    with pytest.raises(ValueError):commands({'action':'input_text','x':1,'y':2,'text':'早饭'})


def test_scroll_binding_requires_both_endpoints_in_matched_region(tmp_path):
    from tests.test_region_stepwise_context import module,visual_graph
    flow=module();g=visual_graph(tmp_path);q=flow.assemble_region_choice(ROOT,g,'o2','r2')
    q.update(allow_scroll=True,region_target='Menu',region_image=str(tmp_path/'screen.png'))
    p={'target':'Menu','action':'scroll','x':30,'y':70,'end_x':30,'end_y':30,'reason':'inspect'}
    assert flow.bind_action_target(q,p)['status']=='matched'
    assert flow.bind_action_target(q,{**p,'end_y':500})['status']=='unresolved'


def test_parent_completion_returns_home_not_same_menu():
    flow,r,s=setup_chain();m=tasks();r['middle']['controls']={};m.apply_plan(r['middle'],proposal([]),'plan')
    s.update(interactive_regions=['middle'],region_path=['main','middle'],working_region='menu')
    q=m.attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q['source']['return_to']=='main'
