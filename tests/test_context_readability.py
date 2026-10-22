from copy import deepcopy
import jsonschema
import pytest
from regrow.records.registration_diagnostics import schema_errors
from regrow.prompts.correction_feedback import describe, present
from regrow.prompts.prompt_material import view
from regrow.records.control_knowledge import schema, update
from regrow.records.control_records import extend_schema


def test_nested_schema_errors_name_the_current_control():
    contract = {'type': 'object', 'properties': {'proposal': {'anyOf': [
        {'type': 'object', 'properties': {'controls': {'type': 'array', 'items': {
            'type': 'object', 'properties': {'knowledge': schema()}}}}}, {'type': 'null'}]}}}
    reply = {'proposal': {'controls': [{'name': 'Help', 'knowledge': []}]}}
    errors = [row for e in jsonschema.Draft202012Validator(contract).iter_errors(reply) for row in schema_errors(e)]
    assert len(errors) == 1
    assert errors[0]['path'] == '/proposal/controls/0/knowledge'
    shown = describe({'errors': errors}, reply)
    assert shown == [{'对象': 'Help', '字段': '用途知识', '问题': '要求至少 1 项，实际提交 0 项。'}]
    value = {'被拒绝回复': reply, '上次失败或停止诊断（保留原文，非当前能力清单）': {'errors': errors},
             '本次修复历史': [{'call': '1', 'error': errors}, {'call': '2', 'role': 'step_correction'}]}
    present(value)
    assert value['被拒绝回复'] == reply and '本次修复历史' not in value
    assert value['本次需要修正的问题'] == shown


def test_empty_identification_knowledge_does_not_weaken_task_answer():
    contract = {'properties': {'controls': {'items': {'properties': {'ref': {}}, 'required': []}}}}
    extend_schema(contract)
    jsonschema.validate([], contract['properties']['controls']['items']['properties']['knowledge'])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate([], schema())
    record = {'knowledge': [{'description': '已知用途', 'conditions': []}]}
    old = deepcopy(record['knowledge'])
    update(record, [], {'basis': 'discovery'})
    assert record['knowledge'] == old


def test_update_view_preserves_evidence_and_geometry_without_addresses():
    obj = {'name': '菜单', 'bbox': [1, 2, 3, 4], 'evidence': {'source_field': '/controls/0'}}
    raw = {'动作前已登记几何': {'acted_control': obj, 'controls': [obj]},
           '动作前对象观察': {'控件': '菜单', '来源': {'source_call': '1'}, 'uncertainty': '外观有遮挡'},
           '实际动作': [{'action': 'click', 'x': 2, 'y': 3}],
           '回执': {'exit_code': 0, 'semantic_result': 'unverified'}}
    old = deepcopy(raw)
    shown = view(raw, {'role': 'observation_update'})
    assert raw == old
    assert shown['动作前已登记几何']['controls'][0]['bbox'] == [1, 2, 3, 4]
    assert 'acted_control' not in shown['动作前已登记几何']
    assert shown['动作前对象观察']['uncertainty'] == '外观有遮挡'
    assert shown['回执'] == raw['回执'] and shown['实际动作'] == raw['实际动作']
    assert 'source_field' not in str(shown)


def test_purpose_has_no_scheduler_instruction():
    from regrow.records.control_history_context import purpose_text
    assert purpose_text({'knowledge': [{'description': '打开菜单', 'conditions': []}],
                         'may_open_content': True, 'needs_exploration': False}) == '推测用途：打开菜单'


def test_semantic_errors_keep_named_requirements_without_string_assumptions():
    reply = {'regions': [{'name': '菜单区'}], 'controls': [{'name': 'Help'}, {'name': 'Help'}]}
    errors = [
        {'code': 'owner', 'path': '/controls/0/region_index', 'expected': [0], 'repair': '归属到本轮实际区块。'},
        {'code': 'duplicate_submission', 'path': '/controls/1/name', 'expected': '/controls/0', 'repair': '同一对象只提交一次。'},
        {'code': 'existing_control_conflict', 'path': '/controls/1/name', 'expected': {'matching_records': ['Help']}, 'repair': '核对旧对象后复用。'}]
    shown = describe({'errors': errors}, reply)
    assert len(shown) == 3 and '菜单区' in shown[0]['问题']
    assert shown[1]['对象'] == 'Help' and shown[1]['问题'] == 'Help'
    assert all('修正要求' in row for row in shown)
    assert '/controls/' not in str(shown)


def test_same_names_in_distinct_regions_keep_both_errors():
    reply = {'regions': [{'name': '菜单'}, {'name': '工具栏'}], 'controls': [
        {'name': 'Help', 'region_index': 0}, {'name': 'Help', 'region_index': 1}]}
    errors = [{'path': f'/controls/{i}/knowledge', 'expected': '缺少用途知识'} for i in range(2)]
    shown = describe({'errors': errors}, reply)
    assert [row['对象'] for row in shown] == ['菜单中的Help', '工具栏中的Help']


def test_old_control_reference_uses_supplied_identity_name():
    reply = {'controls': [{'index': 0}]}
    request = {'control_indexes': ['c0001'], 'page_context': {'names': {'c0001': 'Help'}, 'history': {'names': {'r1': '菜单'}}}}
    shown = describe({'errors': [{'path': '/controls/0/knowledge', 'expected': '缺少用途知识'}]}, reply, request)
    assert shown[0]['对象'] == 'Help'
