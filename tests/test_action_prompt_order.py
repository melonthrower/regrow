"""Action prompt order is explicit; model replies express one decision."""
from pathlib import Path
from copy import deepcopy
import pytest
import jsonschema
from regrow.runtime import action_commands
from regrow.runtime.model_transport import with_run_scope
from regrow.prompts import output,compose,history_disclosure
from regrow.paths import SOURCE_ROOT

def request(platform):
    parts=compose.parts(SOURCE_ROOT,'action_selection')
    q={'role':'action_selection','platform':platform,'system_prompt':'\n\n'.join(p['text'] for p in parts),'fixed_parts':parts,'response_schema':action_commands.selection_schema(action_commands.schema())}
    q=action_commands.platform_request(q,platform)
    q['fixed_parts']+=list(output.desktop_parts(SOURCE_ROOT,q)) if platform=='desktop' else [output.android_part(SOURCE_ROOT,q)]
    return q

@pytest.mark.parametrize('platform',['desktop','android'])
def test_explicit_order_and_single_action_contract(platform):
    q=output.prepare(request(platform),SOURCE_ROOT);text=q['system_prompt']
    headings=['# 本步目的','# 探索范围','# 对象与当前场景','# 选择下一步','# 输出要求','# 输出示例']
    assert [text.index(h) for h in headings]==sorted(text.index(h) for h in headings)
    assert '### action_selection' not in text
    assert 'registration_gap' not in text and 'next_action' not in text and 'task_update' not in text
    assert output.prepare(q,SOURCE_ROOT)==q
    jsonschema.validate({'action':'none','reason':'目标位置尚不能确认'},q['response_schema'])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'action':'none','task_update':{'task':'r1/问题','decision':'continue','reason':'待查','registration_gap':'结果'}},q['response_schema'])

def test_run_scope_is_material_before_task_and_keeps_history(tmp_path):
    import json
    (tmp_path/'run_manifest.json').write_text(json.dumps({'exploration_scope':'只探索当前测试实例'}))
    q={'role':'action_selection','user_prompt':json.dumps({'本轮工作':{'范围':'编辑区'},'当前任务':{'任务':'保存结果'},'登记页面组成与访问来路':'此前输入了文件名'})}
    q=with_run_scope(q,tmp_path);q=history_disclosure.project(q)
    assert q['user_prompt'].index('只探索当前测试实例')<q['user_prompt'].index('保存结果')<q['user_prompt'].index('此前输入了文件名')
    assert history_disclosure.project(with_run_scope(q,tmp_path))['user_prompt']==q['user_prompt']

def test_flat_partial_answer_and_deferral_use_existing_registration_without_second_plan():
    from regrow.records import task_updates
    from regrow.records.object_store import Records,owned_tasks
    q=request('desktop');q['source']={'task_region':'r1','task_name':'问题'}
    raw={'action':'none','reason':'已确认搜索用途，结果排序仍待观察','knowledge':'按名称筛选内容。'}
    jsonschema.validate(raw,q['response_schema'])
    mapped=action_commands.for_request(raw,q)
    assert mapped['task_update']['decision']=='continue'
    assert mapped['task_update']['registration_gap']==raw['reason']
    assert 'next_action' not in mapped['task_update']
    defer={'action':'none','reason':'当前操作仍被对话框阻挡','retry_when':'阻挡解除后'}
    jsonschema.validate(defer,q['response_schema'])
    row=action_commands.for_request(defer,q)['task_update']
    records=Records({'r1':{'id':'r1','name':'区块','controls':{},'tasks':{'问题':{'name':'问题','control':None,'task_type':'control_effect','status':'pending'}},'actions':{}}})
    task=owned_tasks(records['r1'])['问题']
    assert task_updates.decide(task,row,{'source_call':'test'},product_complete=False,records=records)=='blocked'
    assert task['deferral']['retry_when']=='阻挡解除后'
    assert raw=={'action':'none','reason':'已确认搜索用途，结果排序仍待观察','knowledge':'按名称筛选内容。'}
