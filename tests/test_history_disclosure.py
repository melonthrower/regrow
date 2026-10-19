import json
from copy import deepcopy
from tests.test_recovery_discovery import mod

def test_all_json_stages_preserve_complete_history_and_unknown_fields():
    for role in ('observation', 'task_proposal', 'observation_update', 'function_registration', 'recovery', 'branch_correction'):
        value = {'历史': [{'attempt': str(i), 'conditions': ['old'], 'evidence': None, 'text': '多行\n"原文"'} for i in range(30)]}
        q = {'role': role, 'user_prompt': json.dumps(value, ensure_ascii=False, indent=2) + '\n截图说明', 'response_schema': {'type': 'object'}, 'screenshots': ['a.png']}
        original = deepcopy(q)
        result = mod('history_disclosure').project(q)
        (decoded, end) = json.JSONDecoder().raw_decode(mod('history_disclosure').structured_text(result))
        assert decoded == value and mod('history_disclosure').structured_text(result)[end:] == '\n截图说明'
        assert q == original and result['screenshots'] == q['screenshots'] and (result['response_schema'] == q['response_schema'])

def test_repair_discloses_exact_target_and_keeps_original_rules_and_suffix():
    original = {'本轮探索任务': 'Exact task', '任务目标': {'reason': 'Observe only'}, '历史': [{'status': 'unknown'}]}
    d = {'原任务要求': 'Rules\nKeep conditions', '原动态上下文': json.dumps(original, ensure_ascii=False) + '\n原图说明', '被拒绝回复': {'task_result': {'name': 'Changed task'}}, '具体校验错误': 'missing actual task outcome', '相关记录与可用能力': {'other': 'retain'}}
    q = {'role': 'step_correction', 'user_prompt': json.dumps(d, ensure_ascii=False, indent=2) + '\n新图说明'}
    result = mod('history_disclosure').project(q)
    (p, end) = json.JSONDecoder().raw_decode(mod('history_disclosure').structured_text(result))
    assert p['原动态上下文']['上下文'] == original
    assert p['原动态上下文']['附加说明'] == '\n原图说明'
    assert p['任务名称对照'] == {'原任务': 'Exact task', '回复任务': 'Changed task'}
    assert p['相关记录与可用能力'] == d['相关记录与可用能力']
    assert 'Rules\nKeep conditions' in mod('history_disclosure').structured_text(result)[end:]
    assert '\n新图说明' in mod('history_disclosure').structured_text(result)[end:]
    assert mod('history_disclosure').project(result) == result

def test_retained_action_prose_is_not_reinterpreted_by_the_renderer():
    text = '原任务：Task\n- Region / Task / A：{"说明":"old"}\n- Region / Task / B：{"说明":"new"}\n其他历史保留'
    q = {'role': 'action_selection', 'user_prompt': text}
    assert mod('history_disclosure').project(q) == q

def test_unparseable_context_and_unrecognized_role_remain_verbatim():
    for q in [{'role': 'unknown', 'user_prompt': '{"x":1}'}, {'role': 'recovery', 'user_prompt': 'plain\nhistory'}, {'role': 'observation_update', 'user_prompt': '本轮平台：桌面。\n{}'}]:
        assert mod('history_disclosure').project(q) == q

def test_malformed_rejected_task_result_can_still_reach_correction():
    for rejected in ('wrong type', ['wrong type'], 12):
        d = {'原动态上下文': json.dumps({'本轮探索任务': 'Task'}), '被拒绝回复': {'task_result': rejected}}
        result = mod('history_disclosure').project({'role': 'step_correction', 'user_prompt': json.dumps(d)})
        value = json.loads(mod('history_disclosure').structured_text(result))
        assert value['被拒绝回复']['task_result'] == rejected
        assert value['任务名称对照'] == {'原任务': 'Task', '回复任务': None}

def test_update_wire_keeps_values_chains_unknowns_and_suffix():
    value = {'任务目标': {'已有参数发现': {'状态': {'description': '最新 B', '最新来源动作': 'a0003'}}, '相关历史动作与观察': [{'记录': ref, '观察': note, '参数观察': [{'属性': '状态', 'conditions': [], '原观察缺失字段': ['evidence'], '来源对象': {'region': '旧区块', 'control': None}}]} for (ref, note) in [('a0001', 'A selected'), ('a0002', 'other action'), ('a0003', 'B selected')]]}, '当前': {'text': '引号"、换行\n、反斜线\\都保留'}}
    suffix = '\n\n截图坐标说明：原图像素。'
    q = {'role': 'observation_update', 'pipeline_step': 'update', 'user_prompt': json.dumps(value, ensure_ascii=False, indent=2) + suffix, 'screenshots': ['before.png', 'after.png'], 'response_schema': {'type': 'object'}}
    before = deepcopy(q)
    result = mod('history_disclosure').project(q)
    (decoded, end) = json.JSONDecoder().raw_decode(mod('history_disclosure').structured_text(result))
    assert decoded == value and mod('history_disclosure').structured_text(result)[end:] == suffix
    assert result['user_prompt'].startswith('## 本步问题')
    assert '### 任务目标' in result['user_prompt']
    assert '任务目标：{' not in result['user_prompt']
    assert q == before
    assert {k: v for (k, v) in result.items() if k not in ('user_prompt', '_structured_user_prompt', '_presentation_digest')} == {k: v for (k, v) in q.items() if k not in ('user_prompt', '_structured_user_prompt', '_presentation_digest')}
    assert mod('history_disclosure').project(result) == result

def test_readable_body_is_actual_send_and_restores_for_refresh():
    module = mod('history_disclosure')
    q = {'role': 'task_proposal', 'user_prompt': json.dumps({'本轮工作': {'reason': '补登记未选中的A'}, '控件': [{'name': 'A', 'knowledge': '切换到A内容'}]}, ensure_ascii=False)}
    sent = module.project(q)
    assert '理由：补登记未选中的A' in sent['user_prompt']
    assert '1. A' in sent['user_prompt'] and '切换到A内容' in sent['user_prompt']
    assert '已知用途：' not in sent['user_prompt'] and '"knowledge"' not in sent['user_prompt']
    assert not sent['user_prompt'].startswith('{')
    restored = module.restore(sent)
    assert json.loads(restored['user_prompt']) == json.loads(q['user_prompt'])
    assert module.project(restored) == sent
    sent['user_prompt'] = json.dumps({'修改后的范围': 'B'})
    assert module.structured_text(sent) == sent['user_prompt']
    assert 'B' in module.project(sent)['user_prompt'] and '补登记' not in module.project(sent)['user_prompt']

def test_desktop_resend_preserves_readable_source_suffix_and_one_platform_rule():
    from tests.test_recovery_discovery import ROOT
    from regrow.runtime import desktop_transport as desktop_transport
    module = mod('history_disclosure')
    q = {'role': 'task_proposal', 'stage': 'task_proposal', 'user_prompt': json.dumps({'当前任务': 'A'}) + '\n坐标说明', 'fixed_parts': [], 'system_prompt': 'Rules', 'response_schema': {'type': 'object'}}
    first = module.project(desktop_transport.prepare_request(ROOT, q))
    second = module.project(desktop_transport.prepare_request(ROOT, first))
    assert second == first
    assert first['user_prompt'].count('OSWorld Linux桌面') == 1
    assert first['user_prompt'].endswith('\n坐标说明')
