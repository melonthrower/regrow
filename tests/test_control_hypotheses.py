from regrow.records.control_history_context import purpose_text, confirmed_information
from regrow.records.control_records import extend_schema
from regrow.recognition.discovery_delta import schema as delta
from regrow.records.region_evidence import control_observation
from regrow.records.tasks import merge_products

def test_guesses_are_plain_text_and_not_confirmed_knowledge():
    c={'possible_purpose':'搜索设置项','may_open_content':True,'needs_exploration':True}
    assert purpose_text(c)=='推测用途：搜索设置项；可能打开其他功能内容；需要探索'
    assert not confirmed_information(c)
    c.update(may_open_content=False,needs_exploration=False)
    assert '无需进一步探索，可以跳过' in purpose_text(c)
    c['needs_exploration']=None
    assert '尚不确定' in purpose_text(c)

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
