"""Shared map history: semantic evidence stays once, with original ownership."""
from copy import deepcopy
import json
from tests.test_recovery_discovery import mod, ROOT
from tests.test_current_page_context import case, action
from tests.test_update_history_projection import fixture as parameter_case


def test_grouped_history_preserves_receipt_effects_and_unconfirmed_identity(tmp_path):
    records,state,_=case(tmp_path)
    records['dialog']['actions']['a2']=action('opened','typed',['dialog'],['dialog'],'search')
    records['dialog']['actions']['a2'].update(operation='input_text',text='London',text_delivered=False)
    records['dialog']['actions']['a2']['result']['description']='图1未输入，图2仍为空'
    unknown=action('typed','closed',['dialog'],['world'],'search')
    unknown['association']={'status':'unconfirmed','target':'另一入口'}
    unknown['result']['description']='关闭后创建内容仍保留'
    records['dialog']['actions']['a3']=unknown
    before=deepcopy((records,state))
    h=mod('page_history').build(records,state)
    group=next(r for r in h['regions'] if r['ref']=='dialog')
    assert group['unbound']==['a3']
    assert next(c for c in group['controls'] if c['ref']=='search')['attempts']==['a2']
    text=mod('page_history').render(h)
    assert text.count('关闭后创建内容仍保留')==1
    assert '另一入口' in text and '未确认' in text and '未发送' in text
    assert 'London' in text and '历史动作图片引用' in text
    assert h['events']['a2']['观察']=='图1未输入，图2仍为空'
    assert (records,state)==before


def test_parameter_goal_events_are_moved_without_losing_gaps_or_intervening_actions(tmp_path):
    task,records=parameter_case();records['r'].update(id='r',tasks={},observations=[])
    goal=mod('history_context').task_goal(task,records)
    before=deepcopy(goal)
    q={'pipeline_step':'update','user_prompt':json.dumps({'任务目标':goal},ensure_ascii=False),'screenshots':[]}
    state={'interactive_regions':['r'],'observation':{},'working_region':'r'}
    mod('page_context').attach(q,records,state,usage='before_action')
    obj=json.loads(q['user_prompt']);m=mod('page_context');text=obj[m.TITLE]
    assert '最近连续动作' not in obj['任务目标'] and '此前动作与观察' not in obj['任务目标']
    assert text.count('other task changed value')==1
    assert '期间其他动作' in text and 'A selected' in text and '原观察缺失字段' in text
    assert obj['任务目标']['已有参数发现']==before['已有参数发现']
    assert goal==before
    mod('page_context').refresh(q)
    assert json.loads(q['user_prompt'])[m.TITLE]==text


def test_planning_standalone_history_merges_into_map_once(tmp_path):
    from tests.test_stepwise_resume_route import fixture
    _,records,state=fixture()
    records['main']['actions']['a0001']={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':{'description':'unique observed business change'},'interactive_regions':['menu']}
    state['last_action_result']={'region':'main','action':'a0001'}
    q=mod('region_tasks').plan_request(ROOT,records,state,'main')
    assert q['user_prompt'].count('unique observed business change')==1
    mod('page_context').attach(q,records,state)
    obj=json.loads(q['user_prompt'])
    assert mod('page_history').TITLE not in obj
    assert q['user_prompt'].count('unique observed business change')==1
    assert '已登记动作' not in obj['控件'][0]
    assert len(q['image_refs'])==1


def test_action_goal_and_task_status_do_not_repeat_map_event(tmp_path):
    records,state,_=case(tmp_path)
    task=records['world']['tasks']['inspect'];task.update(reason='Open then verify object',action='click')
    text,metadata=mod('history_context').action_context(records,state,'world','inspect',task)
    q={'action_ready':True,'user_prompt':text,'screenshots':[],'source':{'task_region':'world'}}
    mod('target_observation').attach_handoff(q,records,state)
    mod('page_context').attach(q,records,state)
    assert q['user_prompt'].count('Observed actual result')==1
    assert 'Open then verify object' in q['user_prompt']
    assert metadata['recent_action']==state['last_action_result']


def test_missing_task_attempt_and_receipt_only_coordinates_survive(tmp_path):
    records,state,_=case(tmp_path)
    records['world']['tasks']['inspect']['attempts']+=['a2missing']
    folder=tmp_path/'action_attempts/a1';folder.mkdir(parents=True)
    (folder/'dispatch.json').write_text(json.dumps({'action':{'action':'click','x':169,'y':154}}))
    (folder/'receipt.json').write_text(json.dumps({'exit_code':0}))
    h=mod('page_history').build(records,state,tmp_path)
    text=mod('page_history').render(h)
    assert '缺失' in text and '169' in text
    (folder/'receipt.json').write_text(json.dumps({'exit_code':1}))
    assert '169' not in mod('page_history').render(mod('page_history').build(records,state,tmp_path))


def test_incoming_identity_candidates_reference_map_without_losing_comparison(tmp_path):
    records,state,_=case(tmp_path)
    incoming=mod('function_evidence').incoming_results
    records['dialog']['reached_by']=[{'source_region':'world','attempt':'a1'}]
    rows=incoming(records['dialog'],records)
    q={'stage':'discovery','user_prompt':json.dumps({'已知区块':[{'历史进入记录（不证明当前可见或行为等价）':rows}]},ensure_ascii=False),'screenshots':[]}
    mod('page_context').attach(q,records,state,usage='discovery')
    obj=json.loads(q['user_prompt']);entry=obj['已知区块'][0]['历史进入记录（不证明当前可见或行为等价）'][0]
    assert q['user_prompt'].count('Observed actual result')==1
    assert 'Add city' in entry['动作历史'] and '共同地图' in entry['动作历史']
    assert entry['来源区块']=='World' and entry['控件关联']=='已登记'


def test_equal_parameter_baseline_and_receipt_steps_have_single_body():
    task,records=parameter_case()
    a=records['r']['actions']['a0003'];a['executed_steps']=[{'action':'click','x':20,'y':40}]
    a['parameter_findings']=[{'name':'selection',**{k:v for k,v in task['findings']['selection'].items() if k in ('description','domain','conditions','evidence')}}]
    goal=mod('history_context').task_goal(task,records)
    h=mod('page_history').build(records,{'interactive_regions':['r']},goal=goal)
    text=mod('page_history').render(h)
    assert 'executed_steps' not in text
    assert '与任务目标的已有参数发现' in text
    assert '原观察缺失字段' in text
    a['parameter_findings'][0]['conditions']=['different historical condition']
    h=mod('page_history').build(records,{'interactive_regions':['r']},goal=goal)
    assert 'different historical condition' in mod('page_history').render(h)
