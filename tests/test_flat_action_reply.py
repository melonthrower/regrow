"""Flat model answers retain normal validation, binding and no-action decisions."""
from pathlib import Path
from copy import deepcopy
import json
import sys
import pytest
import jsonschema
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.runtime import action_commands as action_commands
from regrow.prompts import output as output_contract
from regrow.prompts import compose as step_questions
from regrow.prompts import history_disclosure as history_disclosure

def schema():
    return action_commands.selection_schema(action_commands.schema())

def test_only_selected_action_fields_are_required_and_internal_defaults_stay_internal():
    value = schema()
    for reply in [{'target': 'r1/c1', 'action': 'click', 'reason': '查看内容', 'x': 12, 'y': 20}, {'action': 'back', 'reason': '关闭弹层'}, {'action': 'wait', 'reason': '观察反馈'}, {'action': 'key_press', 'reason': '确认输入', 'text': 'ENTER'}]:
        jsonschema.validate(reply, value)
        normalized = action_commands.normalize(reply)
        assert normalized['action'] == reply['action'] and normalized['target']
    jsonschema.validate({'action': 'back', 'target': '当前弹层', 'reason': '取消'}, value)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'target': 'r1/c1', 'action': 'input_text', 'reason': '填写', 'x': 12, 'y': 20}, value)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'operation': {'target': 'r1/c1', 'action': 'click', 'reason': '查看', 'x': 12, 'y': 20}}, value)

def test_no_action_partial_answer_uses_bound_task_without_repeating_reference():
    value = schema()
    reply = {'action':'none','reason':'结果尚未完全显示','knowledge':'已确认可输入名称。'}
    jsonschema.validate(reply, value)
    mapped = action_commands.for_request(reply, {'source':{'task_region':'r1','task_name':'了解保存方式'}})
    assert mapped['task_update']['task'] == 'r1/了解保存方式'
    assert mapped['task_update']['decision'] == 'continue'
    text = output_contract.action_shape(value)
    assert 'operation' not in text and 'input_text' in text and 'task_update' not in text
    assert 'retry_when' in text


def test_original_framework_schema_and_reply_remain_readable():
    old = action_commands.schema()
    before = deepcopy(old)
    flat = action_commands.selection_schema(old)
    assert old == before and action_commands.selection_schema(flat) == flat
    reply = {'operation': {'action': 'click', 'target': 'r1/c1', 'reason': '查看', 'x': 1, 'y': 2}}
    jsonschema.validate(reply, old)
    assert action_commands.normalize(reply) == action_commands.normalize(reply['operation'])

def test_question_follows_full_task_and_attempts_and_wire_does_not_add_type_aliases():
    value = {'当前任务': {'task': 'r1/了解保存方式', '探索内容': '了解保存文件的方式及完成反馈'}, '本轮工作': {'范围': '编辑区'}, '登记页面组成与访问来路': 'a1：已输入文件名，尚未保存。', '相关控件': 'r1/c1 保存'}
    text = step_questions.render(value, {'role': 'action_selection'}, history_disclosure.readable)
    assert text.index('探索内容') < text.index('已做尝试与剩余问题') < text.index('## 下一步')
    assert '下一步怎样推进' in text and 'operation' not in text
    parts = step_questions.parts(ROOT, 'action_selection')
    q = {'role': 'action_selection', 'platform':'desktop', 'response_schema': schema(), 'system_prompt': '\n\n'.join(p['text'] for p in parts), 'fixed_parts': parts, 'user_prompt': '{}'}
    q['fixed_parts'] += list(output_contract.desktop_parts(ROOT,q))
    sent = output_contract.prepare(q, ROOT)
    assert 'operation1' not in sent['system_prompt'] and '回复 =' not in sent['system_prompt']

def test_conditional_task_judgment_declares_only_the_current_product_structure():
    from regrow.records.task_updates import schema as task_schema
    for (kind, field) in [('parameter', 'findings'), ('entry', 'entry'), ('control_effect', 'knowledge')]:
        value = action_commands.schema()
        branch = next((b for b in value['properties']['operation']['anyOf'] if 'task_update' in b['properties']))
        branch['properties']['task_update'] = task_schema([kind], ['r1/当前问题'])
        value = action_commands.selection_schema(value)
        text = output_contract.action_shape(value)
        assert 'task_update是一个对象' not in text and 'r1/当前问题' not in text
        assert field + '?' in text
        if kind == 'parameter':
            assert all((name in text for name in ('domain:', 'values:', 'min:', 'max:', 'conditions:', 'evidence:')))
        else:
            assert 'findings?' not in text
        parts = step_questions.parts(ROOT, 'action_selection')
        q = {'role':'action_selection','platform':'desktop','response_schema':value,'system_prompt':'\n\n'.join(p['text'] for p in parts),'fixed_parts':parts}
        q['fixed_parts'] += list(output_contract.desktop_parts(ROOT,q))
        sent = output_contract.prepare(q, ROOT)
        if kind == 'control_effect':
            assert all((field not in sent['system_prompt'] for field in ('findings', 'entry', 'evidence')))
        assert output_contract.prepare(sent, ROOT) == sent
        assert 'operation' not in text
