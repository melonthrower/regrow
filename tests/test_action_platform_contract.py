"""Completion is task settlement; platform manuals and field contracts agree."""
from copy import deepcopy
from pathlib import Path
import jsonschema
import pytest
from regrow.runtime import action_commands as action_commands
from regrow.prompts import output as output_contract
from regrow.prompts import output as prompt_delivery
from regrow.prompts import compose as prompt_rules
from regrow.records import task_updates as task_updates
from regrow.paths import SOURCE_ROOT
ROOT = SOURCE_ROOT

def request(platform='desktop', kind='control_effect'):
    schema = action_commands.schema()
    branch = next((b for b in schema['properties']['operation']['anyOf'] if 'task_update' in b['properties']))
    branch['properties']['task_update'] = task_updates.schema([kind], ['r7/原问题'])
    schema = action_commands.selection_schema(schema)
    parts = prompt_rules.parts(ROOT, 'action_selection')
    q = {'role': 'action_selection', 'platform': platform, 'response_schema': schema, 'fixed_parts': parts, 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'source': {'task_region': 'r7', 'task_name': '原问题', 'region': 'r9'}}
    q = action_commands.platform_request(q, platform)
    additions = list(prompt_delivery.desktop_parts(ROOT, q)) if platform == 'desktop' else [prompt_delivery.android_part(ROOT, q)]
    q['fixed_parts'] += additions
    q['system_prompt'] += '\n\n' + '\n\n'.join((p['text'] for p in additions))
    return q

@pytest.mark.parametrize('platform', ['desktop', 'android'])
def test_complete_uses_framework_task_owner_and_never_dispatches_a_wait(platform):
    q = request(platform)
    reply = {'action': 'complete', 'reason': '已有观察回答了原问题', 'knowledge': '按名称筛选内容'}
    before = deepcopy(reply)
    jsonschema.validate(reply, q['response_schema'])
    mapped = action_commands.for_request(reply, q)
    action_commands.validate(mapped, platform)
    normalized = action_commands.normalize(mapped)
    assert reply == before
    assert normalized['action'] == 'none' and normalized['x'] is None
    assert normalized['task_update'] == {'task': 'r7/原问题', 'decision': 'answered', 'reason': reply['reason'], 'knowledge': reply['knowledge']}
    for extra in ({'task': 'r9/其他任务'}, {'target': 'r9/c1'}, {'x': 2, 'y': 3}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**reply, **extra}, q['response_schema'])
    wait = {'action': 'wait', 'reason': '等待正在加载的内容'}
    jsonschema.validate(wait, q['response_schema'])
    assert action_commands.for_request(wait, q) == wait and (not action_commands.normalize(wait).get('task_update'))

def test_current_task_kind_controls_completion_products_and_old_replies_still_read():
    q = request(kind='control_effect')
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'action': 'complete', 'reason': 'known', 'findings': []}, q['response_schema'])
    old = {'operation': {'action': 'none', 'task_update': {'task': 'r7/原问题', 'decision': 'answered', 'reason': '已有旧证据'}}}
    jsonschema.validate(old, action_commands.schema())
    assert action_commands.for_request(old, q) == old
    with pytest.raises(ValueError, match='原探索任务'):
        action_commands.for_request({'action': 'complete', 'reason': 'known'}, {})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(old['operation'], q['response_schema'])
    assert action_commands.selection_schema(q['response_schema']) == q['response_schema']
    assert not any(('complete' in b['properties']['action']['enum'] for b in action_commands.selection_schema(action_commands.execution_schema())['anyOf']))

@pytest.mark.parametrize('platform', ['desktop', 'android'])
def test_one_platform_table_preserves_semantics_and_saved_contract(platform):
    q = request(platform, kind='parameter')
    before = deepcopy(q['response_schema'])
    sent = output_contract.prepare(q, ROOT)
    text = sent['system_prompt']
    assert text.count('| action |') == 1 and '### 动作字段' not in text and ('### 动作与参数' not in text)
    assert text.count('- target：') == 1 and 'text_delivered=false' in text
    assert '空字符串清空' in text and '聚焦验证' in text
    assert '"complete"' in text and '- answered：' not in text
    assert 'findings?' in text and 'domain:' in text
    if platform == 'desktop':
        assert 'end_y<y' in text and '不是拖动终点' in text and ('不要求落在同一内容区' in text)
        assert '不把Esc当作页面后退' in text and 'BACKSPACE' in text and ('CTRL+SHIFT+P' in text)
    else:
        assert '同一可滚动内容区' in text and 'Android系统返回' in text
        assert '| hotkey |' not in text and '| hover |' not in text
    assert sent['response_schema'] == before and output_contract.prepare(sent, ROOT) == sent
    fragment = next((p for p in sent['fixed_parts'] if p['path'].endswith('/片段-动作合同')))
    old = fragment['text']
    fragment['text'] += '\nRetained platform wording.'
    sent['system_prompt'] = sent['system_prompt'].replace(old, fragment['text'], 1)
    assert output_contract.prepare(sent, ROOT) == sent

def test_complete_correction_retains_original_task_and_same_public_contract(tmp_path):
    from regrow.traversal.step_repair import request as correction
    from PIL import Image
    frame = tmp_path / 'auxiliary-frame.png'
    Image.new('RGB', (200, 100), 'white').save(frame)
    q = request()
    q.update(stage='action_selection', user_prompt='{}', screenshots=[str(frame)], image_refs=[str(frame)])
    fixed = correction(ROOT, {'stage': 'action', 'request': q, 'candidate': {'action': 'complete'}, 'history': [], 'supplements': [], 'error': 'reason missing'}, {})
    assert fixed['original_request']['source'] == q['source']
    schema = fixed['response_schema']['properties']['proposal']
    jsonschema.validate({'action': 'complete', 'reason': '已有观察'}, schema)
    sent = output_contract.prepare(fixed, ROOT)
    assert 'complete' in sent['system_prompt']

def test_old_flat_request_keeps_observation_answered_semantics():
    old = action_commands.schema()['properties']['operation']
    q = request('desktop')
    q['response_schema'] = old
    prepared = output_contract.prepare(q, ROOT)
    text = prepared['system_prompt']
    assert '本步不操作时填写action="none"' in text
    assert '原问题仍未回答时' not in text
    assert '"answered"' in text
    jsonschema.validate({'action': 'none', 'task_update': {'task': 'r7/原问题', 'decision': 'answered', 'reason': '已有旧证据'}}, prepared['response_schema'])
    assert output_contract.prepare(prepared, ROOT) == prepared
