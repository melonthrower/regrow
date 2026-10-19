"""Complete send preparation preserves rule versions and decision boundaries."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from regrow.runtime import action_commands as action_commands
from regrow.prompts import output as output_contract
from regrow.prompts import compose as prompt_rules
from regrow.traversal import recovery as recovery
from regrow.traversal import task_proposer as task_proposer
from regrow.runtime.model_transport import ModelTransport as ModelTransport
from regrow.runtime.model_transport import BudgetExhausted as BudgetExhausted
from regrow.runtime.desktop_transport import prepare_request as prepare_request
ROOT = Path(task_proposer.__file__).parent

def send_view(q, tmp_path, monkeypatch, platform='desktop'):
    from regrow.runtime import progress as progress
    captured = []
    monkeypatch.setattr(progress, 'request', lambda value: captured.append(value))
    candidate = prepare_request(ROOT, q) if platform == 'desktop' else q
    with pytest.raises(BudgetExhausted):
        ModelTransport.call(SimpleNamespace(root=ROOT, run=tmp_path, platform=platform, account={'http_started': 0, 'max_http': 0}), candidate)
    assert len(captured) == 1
    return captured[0]

@pytest.mark.parametrize('platform', ['android', 'desktop'])
@pytest.mark.parametrize('role,stage,schema', [('action_selection', 'action_selection', action_commands.schema), ('task_proposal', 'task_proposal', task_proposer.proposal_schema), ('recovery', 'recovery_action', recovery.schema)])
def test_complete_transport_can_repeat_without_growing_or_changing_source(tmp_path, monkeypatch, platform, role, stage, schema):
    parts = prompt_rules.parts(ROOT, 'recovery' if role == 'recovery' else role)
    q = dict(role=role, stage=stage, fixed_parts=parts, system_prompt='\n\n'.join((p['text'] for p in parts)), user_prompt=json.dumps({'原任务': 'Keep this task', '必要事实': {'conditions': [], 'value': False}}), screenshots=[], response_schema=schema())
    original = deepcopy(q)
    first = send_view(q, tmp_path, monkeypatch, platform)
    second = send_view(first, tmp_path, monkeypatch, platform)
    third = send_view(second, tmp_path, monkeypatch, platform)
    for key in ('system_prompt', 'user_prompt', 'response_schema', 'fixed_parts', 'screenshots'):
        assert first[key] == second[key] == third[key]
    assert q == original
    assert not any((p['path'].startswith('通用/未索引原规则') for p in first['fixed_parts']))
    assert not (tmp_path / 'calls').exists()

def test_saved_fragment_retains_its_version_and_unknown_rules_survive(tmp_path, monkeypatch):
    parts = prompt_rules.parts(ROOT, 'action_selection')
    q = dict(role='action_selection', stage='action_selection', fixed_parts=parts, system_prompt='\n\n'.join((p['text'] for p in parts)), user_prompt='{}', screenshots=[], response_schema=action_commands.schema())
    first = send_view(q, tmp_path, monkeypatch)
    saved = deepcopy(first)
    index = next((i for (i, p) in enumerate(saved['fixed_parts']) if p['path'] == '平台/桌面执行.prompt/片段-2'))
    old = saved['fixed_parts'][index]['text']
    new = old + '\nSaved-version-only instruction.'
    saved['fixed_parts'][index]['text'] = new
    saved['system_prompt'] = saved['system_prompt'].replace(old, new, 1)
    result = send_view(saved, tmp_path, monkeypatch)
    assert result['system_prompt'] == saved['system_prompt']
    assert result['system_prompt'].count('Saved-version-only instruction.') == 1
    result['system_prompt'] += '\n\nExplicit unindexed instruction.'
    prepared = output_contract.prepare(result, ROOT)
    assert prepared['system_prompt'].count('Explicit unindexed instruction.') == 1
    assert output_contract.prepare(prepared, ROOT) == prepared

def test_unindexed_removal_does_not_cut_a_later_block_or_remove_repeated_evidence():
    short = '### heading\nA repeated fact.'
    whole = '## source\n' + short + '\nMore facts.'
    parts = [{'path': 'a/片段-1', 'text': short}, {'path': 'b', 'text': whole}]
    text = short + '\n\n' + whole + '\n'
    assert prompt_rules.unindexed(text, parts) == ''
    assert prompt_rules.unindexed(text + '\nExplicit unindexed instruction.', parts) == 'Explicit unindexed instruction.'
    assert prompt_rules.unindexed(short + '\n\n' + short, parts[:1]) == short

def test_identity_selection_offers_only_its_question_not_record_edit_permissions(tmp_path):
    from regrow.recognition import control_identity_review as identity
    from regrow.traversal import step_repair as step_repair
    from regrow.prompts import history_disclosure as history_disclosure
    from tests.test_control_identity_review import scene, pairs
    data = scene(tmp_path)
    data[0]['r1']['controls']['c2'] = deepcopy(data[0]['r1']['controls']['c1'])
    data[0]['r1']['controls']['c2']['name'] = 'Resume'
    group = pairs(tmp_path, data)
    original = {**data[2], 'role': 'observation_update', 'stage': 'observation_update', 'screenshots': [str(data[1])], 'fixed_parts': [], 'system_prompt': 'Original stage rules', 'user_prompt': json.dumps({'本轮探索任务': 'Investigate direct input', '实际动作': [{'action': 'click', 'target': 'Delete'}], '回执': {'exit_code': 0}, '任务目标': {'说明': 'Keep original question', '历史分段说明': '事件正文见共同地图的区块控件历史', '已知限制': 'Keep this actual condition evidence'}, '当前任务引用': 'r1/Investigate direct input', '来源区块已有任务': [{'task': 'r1/Investigate direct input', 'status': 'pending', 'reason': 'Keep original question', 'conditions': ['required state'], 'prerequisite': {'condition': 'focus editor'}}], '任务与实际对象核对': {'任务区块': 'Timer', '待执行控件': 'Input', '待执行动作': 'input_text', '适用条件': ['required state']}, '动作请求来源上下文': 'Unconfirmed surface', '来源身份说明': 'This is context, not confirmed ownership', '控件关联待核对': {'status': 'unconfirmed'}}), 'response_schema': {'type': 'object', 'properties': {}}}
    job = dict(stage='update', request=original, candidate=data[3], control_identity_candidates=group, history=[{'call': 'old', 'error': 'Hover did not resolve identity'}], supplements=[], error='Choose identity')
    before = deepcopy(original)
    q = step_repair.request(ROOT, job, {'开放能力': ['SHOULD_NOT_OFFER_EDIT_RECORD']})
    value = json.loads(q['user_prompt'])
    assert '相关记录与可用能力' not in value and '原动态上下文' not in value
    card = value['原任务与实际操作']['当前任务']
    assert card['task'] == 'r1/Investigate direct input'
    assert card['原有用途条件'] == ['required state'] and card['status'] == 'pending'
    assert card['prerequisite'] == {'condition': 'focus editor'}
    assert card['完成对象']['待执行控件'] == 'Input'
    assert card['任务补充'] == {'已知限制': 'Keep this actual condition evidence'}
    assert value['原任务与实际操作']['控件关联待核对'] == {'status': 'unconfirmed'}
    assert q['frame_context'][str(data[1])] == '原动作后图（身份候选选择）'
    sent = history_disclosure.project(output_contract.prepare(q, ROOT))
    assert output_contract.fields(q['response_schema']) == {'candidate', 'reason'}
    assert 'SHOULD_NOT_OFFER_EDIT_RECORD' not in sent['user_prompt']
    assert '原步骤的回复哪里' not in sent['user_prompt']
    assert 'Hover did not resolve identity' in sent['user_prompt'] and 'required state' in sent['user_prompt']
    assert original == before

def test_correction_exposes_only_record_edits_supported_by_this_request():
    from regrow.traversal import step_repair as step_repair
    from regrow.traversal import repair_stages as repair_stages
    base = dict(role='observation_update', stage='observation_update', system_prompt='', user_prompt='{}', fixed_parts=[], screenshots=['after'], response_schema={'type': 'object', 'properties': {}})
    job = dict(stage='update', request=base, history=[], error='scope', attempt='a1')
    q = step_repair.request(ROOT, job, {})
    fields = output_contract.fields(q['response_schema']['properties']['record_edit'])
    assert 'attempt' not in fields and 'observations' not in fields and ('task' not in fields)
    assert not any(('观察归属纠正' in x or '动作归属纠正' in x for x in repair_stages.record_capabilities('update', base)))
    no_image = {**base, 'screenshots': []}
    q = step_repair.request(ROOT, {**job, 'request': no_image, 'stage': 'function_registration', 'attempt': None}, {})
    assert q['response_schema']['properties']['record_edit'] == {'type': 'null'}
    assert 'edit_record' not in q['response_schema']['properties']['resolution']['enum']
    assert '## 记录修订 → edit_record' not in q['system_prompt']
    assert '## 修复重复或误登记控件' not in q['system_prompt']

def test_result_correction_guidance_uses_the_original_output_fields():
    from regrow.traversal import correction_prompts as correction_prompts
    for (stage, properties, expected, absent) in [('function_registration', {'functions': {'type': 'array', 'items': {'type': 'string'}}}, '功能整理', '对照动作前记录核对previous_regions'), ('task_result_review', {'task_update': {'type': 'object', 'properties': {}}}, '原任务判断', '对照动作前记录核对previous_regions'), ('update', {'action_result': {'type': 'object', 'properties': {}}, 'previous_regions': {'type': 'array', 'items': {'type': 'string'}}}, '已执行动作与旧区块', 'task_update明确decision')]:
        job = {'stage': stage, 'request': {'screenshots': ['frame'], 'response_schema': {'type': 'object', 'properties': properties}}, 'error': {'errors': [{'code': 'schema'}]}}
        parts = correction_prompts.parts(ROOT, job, {})
        text = '\n'.join((p['text'] for p in parts if p['path'] == '纠错/结果证据.prompt'))
        assert expected in text and absent not in text
