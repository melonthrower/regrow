import pytest
from regrow.records.control_history_context import purpose_text, confirmed_information
from regrow.records.control_records import extend_schema
from regrow.recognition.discovery_delta import schema as delta
from regrow.records.region_evidence import control_observation
from regrow.records.tasks import merge_products

@pytest.mark.parametrize('decision', [True, False, None])
@pytest.mark.parametrize('unfinished', [True, False])
def test_guesses_do_not_decide_whether_to_schedule_or_skip(decision, unfinished):
    c={'possible_purpose':'搜索设置项','may_open_content':True,'needs_exploration':decision}
    assert purpose_text(c, unfinished=unfinished)=='推测用途：搜索设置项；可能打开其他内容'
    assert not confirmed_information(c)
    c['may_open_content']=False
    assert purpose_text(c, unfinished=unfinished)=='推测用途：搜索设置项'

def test_confirmed_answer_replaces_guess_and_legacy_is_not_promoted():
    c={'knowledge':'打开搜索并筛选设置','possible_purpose':'猜测','observations':[{'knowledge':'打开搜索并筛选设置','evidence':{'source_field':'/controls/0'}}]}
    assert not confirmed_information(c)
    assert '推测用途' in purpose_text(c)
    c['observations'].append({'knowledge':c['knowledge'],'evidence':{'task_ref':'r1/t','basis':'explored'}})
    assert purpose_text(c)=='已知功能：打开搜索并筛选设置'
    assert '猜测' not in purpose_text(c)

def test_observation_keeps_hypotheses_not_knowledge():
    p={'possible_purpose':'关闭','may_open_content':False,'needs_exploration':False,'knowledge':'不应写入'}
    row=control_observation(p,{'source_call':'1'})
    assert row['needs_exploration'] is False and 'knowledge' not in row

def test_merge_keeps_uncertain_judgments_separate():
    a={'possible_purpose':'用途A','needs_exploration':True};b={'possible_purpose':'用途B','needs_exploration':False}
    merge_products(a,b)
    assert a['needs_exploration'] is None and '用途B' in a['possible_purpose']

def test_merge_does_not_promote_guess_or_drop_confirmed_function():
    known={'knowledge':'已确认功能','observations':[{'knowledge':'已确认功能','evidence':{'task_ref':'r/t','basis':'explored'}}]}
    guessed={'knowledge':'旧猜测','observations':[{'knowledge':'旧猜测','evidence':{'source_field':'/controls/0'}}]}
    merge_products(known,guessed)
    assert confirmed_information(known)=='已确认功能'
    assert '旧猜测' not in known['knowledge']

def test_old_graph_import_keeps_legacy_purpose_without_confirming_it():
    from regrow.records.region_evidence import region_records
    from regrow.records.object_store import owned_controls
    graph={'observations':[{'id':'o1','region_refs':['r1'],'control_refs':['c1'],'frame':'screen.png'}],
           'regions':[{'id':'r1','observation':'o1','proposal':{'name':'面板','description':'内容'}}],
           'controls':[{'id':'c1','owner_ref':'r1','observation':'o1','proposal':{'name':'搜索','knowledge':'旧用途'}}], 'action_edges':[]}
    records=region_records(graph);c=owned_controls(records['r1'])['c1']
    assert c['knowledge']=='旧用途'
    assert not confirmed_information(c)
    assert '缺少确认依据' in purpose_text(c)

def test_task_request_keeps_failure_conditions_and_open_question_without_skip_advice():
    import json
    from regrow.paths import SOURCE_ROOT
    from regrow.records.object_store import Records, owned_controls, owned_actions, owned_tasks
    from regrow.records.region_evidence import new_region
    from regrow.records.tasks import audit
    from regrow.traversal.task_proposer import plan_request
    records=Records({'r1':new_region('r1','本地选项')})
    region=records['r1']
    owned_controls(region)['c1']={'name':'筛选','possible_purpose':'筛选本地选项',
        'may_open_content':True,'needs_exploration':False}
    owned_actions(region)['a1']={'control':'c1','operation':'input_text',
        'delivery':'not_executed','text_delivered':False,
        'result':{'exception':'none','description':'输入投递失败'},'conditions':['仅当前列表']}
    owned_tasks(region)['question']={'name':'功能探索','task_type':'function','control':'c1',
        'status':'pending','conditions':['仅当前列表']}
    task=owned_tasks(region)['question']
    audit(task)['latest_update']={'decision':'continue','reason':'已有尝试未发送文字',
                                  'remaining_question':'尚未确认实际筛选结果'}
    state={'working_region':'r1','interactive_regions':['r1'],
           'observation':{'id':'obs','image':'screen.png','region_refs':['r1'],'control_refs':['c1']}}
    request=plan_request(SOURCE_ROOT,records,state,'r1')
    material=json.loads(request['user_prompt'])['控件']
    for text in ['推测用途：筛选本地选项','可能打开其他内容','输入投递失败',
                 '文字未发送','仅当前列表','尚未确认实际筛选结果','功能探索待完成']:
        assert text in material
    assert '可以跳过' not in material and '需要探索' not in material
    assert task['status']=='pending'
