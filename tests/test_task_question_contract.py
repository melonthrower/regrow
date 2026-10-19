"""Question contracts; these checks do not claim model or GUI acceptance."""
from pathlib import Path
import sys
import jsonschema
import pytest
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.object_store import owned_tasks as owned_tasks
from regrow.records.object_store import owned_actions as owned_actions
from regrow.records.object_store import observation_history as observation_history
from regrow.records.region_evidence import new_region as new_region
from regrow.traversal.region_tasks import apply_plan as apply_plan
from regrow.records.task_settlement import completion_target as completion_target
from regrow.records.task_settlement import recorded_match as recorded_match
from regrow.records.task_settlement import settle_task as settle_task
from regrow.traversal.task_proposer import proposal_schema as proposal_schema
from regrow.records.tasks import audit as audit
from regrow.records.tasks import read as task_value
from regrow.records.tasks import import_products as import_products

def setup_question(name='文件名搜索支持完整名称还是部分名称？', kind='parameter'):
    records = Records({'r0001': new_region('r0001', '文件面板')})
    region = records['r0001']
    owned_controls(region)['c0001'] = {'name': '文件名搜索框'}
    row = {'control': '文件名搜索框', 'name': name, 'task_type': kind, 'conditions': []}
    reply = {'inventory': 'complete', 'evidence': '当前仅搜索匹配范围未知。', 'operations': [row], 'shared_instances': []}
    state = {'observation': {'id': 'o1', 'control_refs': ['c0001']}, 'interactive_regions': ['r0001']}
    apply_plan(region, reply, '1', records=records, state=state)
    return (records, region, name, state)

def test_new_question_has_one_type_no_prescribed_method_or_duplicate_state():
    (records, region, name, state) = setup_question()
    task = owned_tasks(region)[name]
    assert task['status'] == 'pending' and task['task_type'] == 'parameter'
    assert not {'handling', 'action', 'registration_kind', 'reason'}.intersection(task)
    definition = proposal_schema()['properties']['operations']['items']['anyOf'][0]
    assert set(definition['required']) == {'control', 'name', 'task_type', 'conditions'}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'control': '文件名搜索框', 'name': name, 'task_type': 'parameter', 'conditions': [], 'action': 'input_text'}, definition)
    from regrow.records.task_inventory_context import task_catalog as task_catalog
    catalog = task_catalog(region, state, records)
    assert catalog[0]['name'] == name and 'action' not in catalog[0] and ('handling' not in catalog[0])

def test_actual_method_is_checked_against_receipt_not_task_proposal():
    (records, region, name, state) = setup_question()
    task = owned_tasks(region)[name]
    target = completion_target(region, task)
    action = {'control': 'c0001', 'operation': 'long_press', 'delivery': 'executed_receipt_zero', 'result': {'description': '搜索框显示编辑菜单。', 'exception': 'none'}}
    assert recorded_match(region, 'a1', action, target, {'exit_code': 0, 'executed_steps': [{'action': 'long_press'}]})
    assert not recorded_match(region, 'a1', action, target, {'exit_code': 0, 'executed_steps': [{'action': 'click'}]})
    records['r0002'] = new_region('r0002', '新归属区块')
    owned_controls(records['r0002'])['c0001'] = owned_controls(region).pop('c0001')
    target = completion_target(region, task)
    assert target['region'] == 'r0002'
    assert recorded_match(region, 'a1', action, target, {'exit_code': 0, 'executed_steps': [{'action': 'long_press'}]})
    action['operation'] = 'input_text'
    assert not recorded_match(region, 'a1', action, target, {'exit_code': 0, 'executed_steps': [{'action': 'input_text'}], 'text_delivered': False})
    assert recorded_match(region, 'a1', action, target, {'exit_code': 0, 'executed_steps': [{'action': 'input_text'}], 'text_delivered': True})

def test_different_method_can_answer_the_question_without_changing_task_owner():
    (records, region, name, state) = setup_question('搜索框是否支持文本编辑菜单？', 'control_effect')
    task = owned_tasks(region)[name]
    owned_actions(region)['a1'] = {'control': 'c0001', 'operation': 'long_press', 'delivery': 'executed_receipt_zero', 'result': {'description': '搜索框显示编辑菜单。', 'exception': 'none'}, 'evidence': {'result_call': '2', 'after_observation': 'o2'}, 'interactive_regions': ['r0001']}
    row = {'task': 'r0001/' + name, 'decision': 'answered', 'reason': '实际长按后显示编辑菜单。', 'knowledge': '搜索框支持长按打开编辑菜单。'}
    settle_task(region, {'region_ref': 'r0001', 'task_region': 'r0001', 'task_name': name, 'control_ref': 'c0001'}, {'task_update': row}, 'a1', records, receipt={'exit_code': 0, 'executed_steps': [{'action': 'long_press'}]})
    assert task['status'] == 'done' and 'action' not in task and ('handling' not in task)
    assert audit(task)['completion_basis']['basis'] == 'explored'
    assert 'knowledge' not in task and 'completion_basis' not in task and ('attempts' not in task)
    assert records.controls['c0001']['knowledge'] == '搜索框支持长按打开编辑菜单。'
    assert 'r0001/' + name in records.tasks

def test_preparation_is_based_on_target_not_a_fixed_click():
    from regrow.traversal.action_binding import bind_action_target as bind_action_target
    request = {'preparation_allowed': True, 'source': {'region': 'r0001', 'observation': 'o1', 'task_name': '继续检查列表内容', 'task_type': 'control_effect', 'task_control': None, 'completion_region': 'r0001'}}
    assert not bind_action_target(request, {'action': 'wait'})['preparatory_action']
    request['source']['task_control'] = 'c0001'
    assert bind_action_target(request, {'action': 'wait'})['preparatory_action']

def test_import_preserves_observation_basis_and_shared_answer_can_be_withdrawn():
    from regrow.records.shared_tasks import synchronize_tasks as synchronize_tasks
    from regrow.records.shared_controls import propose_instances as propose_instances
    (records, region, name, state) = setup_question()
    records['r0002'] = new_region('r0002', '另一个文件面板')
    owned_controls(records['r0002'])['c0002'] = {'name': '文件名搜索框'}
    propose_instances(records, 'r0002', [{'control': '文件名搜索框', 'source_region': 'r0001', 'source_control': 'c0001', 'reason': '两者为相同的文件名搜索控件。'}], '2')
    task = dict(owned_tasks(region)[name])
    task.update(status='record_only', handling='record', knowledge='按文件名筛选。')
    task['registration_kind'] = 'control_effect'
    owned_tasks(region)[name] = task
    import_products(records)
    task = owned_tasks(region)[name]
    assert task['status'] == 'done' and audit(task)['completion_basis']['basis'] == 'observation_only'
    assert not {'handling', 'registration_kind', 'action'}.intersection(task)
    synchronize_tasks(records)
    member = next(iter(owned_tasks(records['r0002']).values()))
    assert member['status'] == 'done' and member['shared_result']['observation_only']
    assert not owned_actions(records['r0002'])
    task['status'] = 'pending'
    synchronize_tasks(records)
    assert member['status'] == 'pending' and 'shared_result' not in member

def test_explicit_inventory_can_consider_known_controls_without_creating_tasks():
    from regrow.records.tasks import coverage as coverage
    records = Records({'r0001': new_region('r0001', '文件面板')})
    region = records['r0001']
    owned_controls(region)['c0001'] = {'name': '关闭'}
    assert not coverage(region, records)['inventory_complete']
    reply = {'inventory': 'complete', 'evidence': '关闭用途明确，没有需调查的未知。', 'operations': [], 'shared_instances': []}
    apply_plan(region, reply, '1', records=records, reviewed_controls=['c0001'])
    assert not owned_tasks(region) and coverage(region, records)['complete']
    owned_controls(region)['c0002'] = {'name': '更多选项'}
    assert not coverage(region, records)['inventory_complete']

def test_region_question_can_be_answered_from_its_current_semantic_observation():
    from regrow.records.task_updates import store_increment as store_increment
    records = Records({'r0001': new_region('r0001', '文件列表')})
    region = records['r0001']
    name = '当前列表是否还有其他类别的内容？'
    owned_tasks(region)[name] = {'name': name, 'control': None, 'task_type': 'control_effect', 'status': 'pending'}
    task = owned_tasks(region)[name]
    state = {'observation': {'id': 'o1', 'foreground': {'exception': 'none'}}, 'interactive_regions': ['r0001']}
    observation_history(region, create=True).append({'evidence': {'observation': 'o1', 'source_call': '1'}})
    from regrow.records.task_updates import observed_control as observed_control
    assert observed_control(region, task, state)
    observation_history(region)[-1]['visual_only'] = True
    assert not observed_control(region, task, state)
    observation_history(region)[-1].pop('visual_only')
    row = {'task': 'r0001/' + name, 'decision': 'answered', 'reason': '当前列表完整显示两个类别。', 'knowledge': '列表分为文件和目录两个类别。'}
    store_increment(region, task, name, row, records, state, {'basis': 'observation_only', 'source_call': '1'}, observed=observed_control(region, task, state))
    assert task['status'] == 'done' and audit(task)['completion_basis']['basis'] == 'observation_only'
    assert 'knowledge' not in task and (not region.get('local_knowledge'))
    assert task_value(task, 'knowledge') == '列表分为文件和目录两个类别。'
    assert not owned_actions(region)

def test_preparation_checks_stable_control_after_current_membership_changes():
    from regrow.traversal.task_prerequisites import apply as apply
    (records, region, name, state) = setup_question()
    task = owned_tasks(region)[name]
    task.update(status='blocked', blocker={'condition': 'prerequisite'}, prerequisite={'condition': '编辑可用'})
    records['r0002'] = new_region('r0002', '新归属区块')
    owned_controls(records['r0002'])['c0001'] = owned_controls(region).pop('c0001')
    observation_history(records.controls['c0001'], create=True).append({'evidence': {'source_call': '2', 'observation': 'o2'}})
    apply(records, {'dependency_updates': [{'region': region['name'], 'task': name, 'ready': True, 'evidence': '当前搜索框已可编辑。'}]}, '2', [{'region': 'r0001', 'task': name}])
    assert task['status'] == 'pending' and task['prerequisite']['satisfied']['source_call'] == '2'
    assert 'r0001/' + name in records.tasks and 'r0002/' + name not in records.tasks

def test_normal_diagnostics_do_not_require_one_question_per_control():
    from regrow.records.registration_diagnostics import check as check
    from regrow.records.tasks import coverage as coverage
    (records, region, name, state) = setup_question()
    owned_controls(region)['c0002'] = {'name': '目录项'}
    request = {'source': {'region': 'r0001', 'controls': ['c0001', 'c0002']}, 'response_schema': proposal_schema()}
    reply = {'inventory': 'complete', 'evidence': '已考虑搜索框和目录项，当前没有要新增的问题。', 'operations': [], 'shared_instances': []}
    check('task_proposal', request, reply, records)
    apply_plan(region, reply, '2', records=records, state=state, reviewed_controls=request['source']['controls'])
    assert coverage(region, records)['inventory_complete']
    assert list(owned_tasks(region)) == [name]
    reply['operations'] = [{'control': '', 'name': '目录展示哪些信息？', 'task_type': 'control_effect', 'conditions': []}]
    check('task_proposal', request, reply, records)
