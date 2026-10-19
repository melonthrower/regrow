from regrow.records.tasks import coverage as _test_fn_coverage
'Auxiliary checks for identity references and abstract, sourced knowledge.'
from pathlib import Path
import sys
import jsonschema
import pytest
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.recognition import discovery_delta as discovery_delta
from regrow.recognition import locator as locator
from regrow.records import object_store as object_store
from regrow.records.region_evidence import new_region as new_region
from regrow.records.region_evidence import control_observation as control_observation
from regrow.records import task_knowledge as task_knowledge
from regrow.records import task_updates as task_updates

def reply(regions=None, controls=None):
    return {'foreground': {'description': '编辑区', 'exception': 'none', 'evidence': '可见编辑区', 'uncertainty': '', 'recovery_handoff': ''}, 'focus_presence': None, 'regions': regions or [{'ref': 'r0001'}], 'controls': controls if controls is not None else [{'ref': 'c0002'}], 'uncertainties': []}

def records():
    store = object_store.Records({'r0001': new_region('r0001', '编辑区')})
    object_store.owned_controls(store['r0001'])['c0002'] = {'name': '保存', 'observations': [{'text': '保存', 'state': '禁用', 'evidence': {'observation': 'old'}}], 'action_refs': []}
    return store

def test_reference_does_not_require_repeat_state_name_or_owner():
    schema = locator.schema(ROOT, 'global', False)
    raw = reply()
    jsonschema.validate(raw, schema)
    q = {'discovery_context': {'region_names': {'r0001': 'r0001'}, 'control_names': {'c0002': 'c0002'}}}
    (normalized, _) = discovery_delta.resolve(records(), q, raw)
    control = normalized['controls'][0]
    assert control['region_index'] == 0 and control['name'] == '保存'
    assert 'state' not in control and 'text' not in control
    assert raw['controls'] == [{'ref': 'c0002'}]

def test_missing_reference_is_not_implicit_new_identity():
    schema = locator.schema(ROOT, 'global', False)
    new = {'identity': 'new', 'name': '关闭', 'region_index': 0, 'bbox': None}
    jsonschema.validate(reply(controls=[new]), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(reply(controls=[{k: v for (k, v) in new.items() if k != 'identity'}]), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(reply(controls=[{'ref': '保存'}]), schema)

def test_control_reference_needs_current_owner_confirmation():
    q = {'discovery_context': {'region_names': {}, 'control_names': {'c0002': 'c0002'}}}
    with pytest.raises(ValueError, match='所属区块'):
        discovery_delta.resolve(records(), q, {'regions': [], 'controls': [{'ref': 'c0002'}]})

def test_icon_description_survives_output_registration_and_history_read():
    from regrow.records.control_history_context import last_reported as last_reported
    row = control_observation({'icon_appearance': '向左箭头', 'knowledge': '返回上一级。'}, {'source_call': '10', 'observation': 'new'})
    control = {'observations': [row]}
    assert last_reported(control, 'icon_description')['icon_description'] == '向左箭头'
    assert row['knowledge'] == '返回上一级。'
    assert row['evidence']['source_call'] == '10'
    assert 'possible_operation' not in row

def test_model_reorganized_task_knowledge_replaces_text_but_keeps_sources():
    store = records()
    region = store['r0001']
    object_store.owned_tasks(region)['了解输入方式'] = {'name': '了解输入方式', 'control': 'c0002', 'status': 'pending'}
    task = object_store.owned_tasks(region)['了解输入方式']
    task_updates.store_knowledge(task, '支持输入文件名。', {'source_call': '1', 'basis': 'observation_only'})
    task_updates.store_knowledge(task, '输入文件名后按文件名筛选列表。', {'source_call': '2', 'basis': 'explored'})
    assert 'knowledge' not in task and 'knowledge_source' not in task
    assert store.controls['c0002']['knowledge'] == '输入文件名后按文件名筛选列表。'
    rows = [row for row in object_store.observation_history(store.controls['c0002']) if 'knowledge' in row]
    assert rows[0]['knowledge'] == '支持输入文件名。'
    assert {row['evidence']['source_call'] for row in rows} == {'1', '2'}

def test_abstract_purpose_does_not_change_with_enabled_state_or_input_value():
    store = records()
    control = store.controls['c0002']
    object_store.observation_history(control).append(control_observation({'knowledge': '保存当前条目。', 'state': '禁用'}, {'source_call': '2', 'observation': 'observed'}))
    object_store.observation_history(control).append(control_observation({'state': '启用', 'text': '未命名条目'}, {'source_call': '3', 'observation': 'later'}))
    knowledge = task_knowledge.control_knowledge(store['r0001'], 'c0002', store)
    assert knowledge['已知用途']['description'] == '保存当前条目。'
    assert task_knowledge.observed_purpose(control)['evidence']['source_call'] == '2'
    assert 'source_call' not in knowledge['已知用途']['source']

def test_direct_purpose_can_be_inventoried_and_summarized_without_fake_tasks():
    from regrow.traversal import region_tasks as region_tasks
    from regrow.traversal import region_functions as region_functions
    from regrow.records.task_inventory_context import project as project
    store = records()
    control = store.controls['c0002']
    object_store.observation_history(control).append(control_observation({'knowledge': '保存当前条目。'}, {'source_call': '2', 'observation': 'observed'}))
    state = {'working_region': 'r0001', 'interactive_regions': ['r0001'], 'observation': {'id': 'observed', 'control_refs': ['c0002']}}
    material = project(store, state, 'r0001')
    assert material['控件'][0]['knowledge'] == '保存当前条目。'
    region_tasks.apply_plan(store['r0001'], {'inventory': 'complete', 'evidence': '已核对用途，无其他未知。', 'operations': [], 'shared_instances': []}, '3', records=store, state=state)
    assert dict(object_store.owned_tasks(store['r0001'])) == {}
    assert _test_fn_coverage(store['r0001'], store)['complete'] is True
    schema = region_functions.request_schema(ROOT, store['r0001'], store)
    assert schema['properties']['functions']['items']['properties']['supports']['items']['enum'] == ['c0002']
    summary = {'local_knowledge': {'add': ['保存当前条目。']}, 'parameter_definitions': [], 'functions': [{'name': '保存条目', 'description': '保存当前条目。', 'object': '当前条目', 'completion': '当前条目已保存', 'supports': ['c0002'], 'constraints': [], 'unconfirmed': ['未检查重启后的持久性']}], 'evidence': '引用已登记控件用途。'}
    region_functions.register(store['r0001'], summary, '4', store)
    function = store['r0001']['functions']['保存条目']
    assert dict(object_store.owned_tasks(store['r0001'])) == {} and dict(object_store.owned_actions(store['r0001'])) == {}
    assert function['support_tasks'] == []
    assert function['support_controls'][0]['source']['source_call'] == '2'
    assert function['support_controls'][0]['basis'] == 'observation_only'
