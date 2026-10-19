from regrow.records.snapshots import publish as _test_fn_publish
'Object answer persistence and provenance boundaries; no model/GUI acceptance.'
from pathlib import Path
import sys
import json
from copy import deepcopy
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_tasks as owned_tasks
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.object_store import owned_actions as owned_actions
from regrow.records.object_store import observation_history as observation_history
from regrow.records.object_store import load as load
from regrow.records.object_store import region_work as region_work
from regrow.records.tasks import audit as audit
from regrow.records.tasks import read as read
from regrow.records.tasks import store_knowledge as store_knowledge
from regrow.records.tasks import store_entry as store_entry
from regrow.records.tasks import import_products as import_products
from regrow.records.task_settlement import store_findings as store_findings
from regrow.records.task_settlement import missing_product_fields as missing_product_fields
from regrow.records.region_evidence import new_region as new_region
from tests.test_flat_object_store import legacy_run

def fact(conditions=()):
    return {'name': '匹配方式', 'description': '选择文件名匹配方式。', 'conditions': list(conditions), 'domain': {'type': 'enum', 'values': ['完整名称', '部分名称'], 'min': None, 'max': None}, 'evidence': '界面给出两种匹配选项。'}

def records():
    result = Records({'r0001': new_region('r0001', '文件面板'), 'r0002': new_region('r0002', '目录面板')})
    owned_controls(result['r0001'])['c0001'] = {'name': '文件名搜索'}
    owned_controls(result['r0002'])['c0002'] = {'name': '打开目录', 'observations': [{'evidence': {'observation': 'o1'}}]}
    owned_tasks(result['r0001'])['搜索匹配范围'] = {'name': '搜索匹配范围', 'control': 'c0001', 'task_type': 'parameter', 'status': 'pending'}
    return (result, owned_tasks(result['r0001'])['搜索匹配范围'])

def test_task_products_leave_only_questions_in_normal_published_snapshot(tmp_path):
    from regrow.traversal import discovery_step as discovery_step
    (run, _) = legacy_run(tmp_path)

    def answer(records, state, *args):
        task = owned_tasks(records['r0001'])['保存行为']
        store_knowledge(task, '保存当前条目。', {'source_call': '2', 'basis': 'observation_only'})
        store_findings(task, [fact()], {'source_call': '2', 'basis': 'observation_only'})
        task['status'] = 'done'
        audit(task)['completion_basis'] = {'source_call': '2', 'basis': 'observation_only'}
    pointer = _test_fn_publish(run, 'answer', answer)
    snapshot = run / pointer['snapshot']
    raw = json.loads((snapshot / 'tasks.json').read_text())['r0001/保存行为']
    assert not {'knowledge', 'findings', 'entry_registration', 'attempts', 'knowledge_source', 'completion_basis', '_task_audit'} & raw.keys()
    restored = load(snapshot)
    task = owned_tasks(restored['r0001'])['保存行为']
    assert restored.controls['c0002']['knowledge'] == [{'description':'保存当前条目。','conditions':[]}]
    assert read(task, 'findings')['匹配方式']['source']['source_call'] == '2'
    assert audit(task)['completion_basis']['basis'] == 'observation_only'
    assert (snapshot / 'task_history.json').is_file()
    from gui_rewalk.src.core.scenario.collection_graph import snapshot_records
    (readonly, dependencies) = snapshot_records(snapshot)
    assert readonly['r0001']['controls']['c0002']['knowledge'] == restored.controls['c0002']['knowledge']
    assert readonly['r0001']['tasks']['保存行为']['completion_basis'] == audit(task)['completion_basis']
    assert snapshot / 'task_history.json' in dependencies

def test_referenced_split_writes_to_effective_target_and_executed_entry_reads_once():
    from regrow.records import function_scope as function_scope
    from regrow.traversal import region_functions as region_functions
    (result, task) = records()
    result['r0003'] = new_region('r0003', '目录内容')
    task['completion_action'] = {'region': 'r0002', 'control': 'c0002'}
    store_knowledge(task, '打开所选目录。', {'basis': 'explored', 'attempt': 'a1'})
    store_findings(task, [fact()], {'basis': 'observation_only', 'source_call': '2'})
    entry = {'region': 'r0003', 'meaning': '打开所选目录。', 'conditions': [], 'attempt': 'a1', 'evidence': '目录内容出现。'}
    store_entry(task, entry)
    owned_actions(result['r0002'])['a1'] = {'control': 'c0002', 'delivery': 'executed_receipt_zero', 'entry_registration': entry}
    assert 'knowledge' not in result.controls['c0001']
    assert result.controls['c0002']['knowledge'] == [{'description':'打开所选目录。','conditions':[]}]
    assert read(task, 'findings') and read(task, 'entry_registration')['attempt'] == 'a1'
    links = function_scope.entries(result['r0002'], result)
    assert len(links) == 1 and links[0]['attempt'] == 'a1' and (links[0]['status'] == 'registered_entry')
    region_work(result['r0002'])['task_inventory'] = {'inventory': 'complete', 'controls': ['c0002']}
    assert not region_functions.ready(result['r0002'], result)
    task['status'] = 'done'
    supports = region_functions.support_catalog(result['r0002'], result)
    assert supports[task.ref]['region'] == 'r0002' and supports[task.ref]['control'] == 'c0002'
    assert task.ref not in region_functions.support_catalog(result['r0001'], result)
    result['r0002']['functions'] = {'打开目录': {'support_tasks': [{'region': 'r0001', 'task': '搜索匹配范围'}]}}
    owned_tasks(result['r0001'])['另一个问题'] = {'name': '另一个问题', 'control': 'c0001', 'status': 'pending', 'task_type': 'control_effect'}
    assert region_functions.ready(result['r0002'], result)

def test_same_object_facts_do_not_become_preparation_products_and_adoption_deduplicates():
    from regrow.traversal import region_functions as region_functions
    (result, task) = records()
    region = result['r0001']
    store_findings(task, [fact()], {'basis': 'observation_only', 'source_call': '1'})
    task['status'] = 'done'
    owned_tasks(region)['准备搜索'] = {'name': '准备搜索', 'control': 'c0001', 'task_type': 'control_effect', 'status': 'done', 'prepares': {'region': 'r0001', 'task': '搜索匹配范围'}}
    preparation = owned_tasks(region)['准备搜索']
    assert read(preparation, 'findings') is None
    owned_tasks(region)['选项含义'] = {'name': '选项含义', 'control': 'c0001', 'task_type': 'parameter', 'status': 'pending'}
    adopter = owned_tasks(region)['选项含义']
    assert missing_product_fields(adopter) == ['findings']
    before = len(observation_history(result.controls['c0001']))
    store_findings(adopter, [fact()], {'basis': 'observation_only', 'source_call': '2'})
    adopter['status'] = 'done'
    assert len(observation_history(result.controls['c0001'])) == before
    assert read(adopter, 'findings')['匹配方式']['source']['task_ref'] == task.ref
    assert len(region_functions.catalog(region, result)) == 1

def test_control_merge_preserves_products_and_remaps_adopted_parameter_refs():
    from regrow.records import control_records as control_records
    (result, task) = records()
    region = result['r0001']
    owned_controls(region)['c0003'] = {'name': '搜索入口'}
    owned_tasks(region)['原方式'] = {'name': '原方式', 'control': 'c0003', 'task_type': 'parameter', 'status': 'done'}
    other = owned_tasks(region)['原方式']
    store_findings(other, [fact(['精确模式'])], {'source_call': '1', 'basis': 'observation_only'})
    store_knowledge(other, '按文件名筛选列表。', {'source_call': '1', 'basis': 'observation_only'})
    store_entry(other, {'region': 'r0002', 'meaning': '显示目录。', 'conditions': [], 'source': {'source_call': '1', 'basis': 'observation_only'}})
    store_findings(task, [fact()], {'source_call': '2', 'basis': 'observation_only'})
    owned_tasks(region)['采用方式'] = {'name': '采用方式', 'control': 'c0003', 'task_type': 'parameter', 'status': 'done'}
    adopter = owned_tasks(region)['采用方式']
    store_findings(adopter, [fact(['精确模式'])], {'source_call': '3', 'basis': 'observation_only'})
    control_records.merge(result, {}, 'r0001', ['c0003'], 'c0001')
    assert adopter['control'] == 'c0001' and 'c0003' not in result.controls
    assert read(adopter, 'findings')['匹配方式 / 精确模式']['conditions'] == ['精确模式']
    assert read(other, 'entry_registration')['region'] == 'r0002'
    assert result.controls['c0001']['knowledge'] == '按文件名筛选列表。'

def test_owner_correction_withdraws_wrong_current_knowledge_without_erasing_history():
    from regrow.records import action_owner_correction as action_owner_correction
    from regrow.records import task_knowledge as task_knowledge
    (result, task) = records()
    task['task_type'] = 'control_effect'
    task['status'] = 'done'
    owned_actions(result['r0001'])['a1'] = {'task': task.ref, 'control': 'c0001', 'delivery': 'executed_receipt_zero', 'operation': 'click', 'result': {'description': '目录内容出现。', 'exception': 'none'}, 'evidence': {'before_observation': 'o1'}}
    store_knowledge(task, '打开目录内容。', {'basis': 'explored', 'attempt': 'a1', 'source_call': '1'})
    audit(task)['completion_basis'] = {'basis': 'explored', 'attempt': 'a1'}
    action_owner_correction.apply(result, {}, {'attempt': 'a1', 'from_region': '文件面板', 'from_control': '文件名搜索', 'to_region': '目录面板', 'to_control': '打开目录', 'evidence': '原图中的操作位置属于目录按钮。'}, '2')
    assert result.controls['c0001']['knowledge'] == [] and task['status'] == 'blocked'
    assert not task_knowledge.observed_purpose(result.controls['c0001'])
    assert any((row.get('knowledge') == [{'description':'打开目录内容。','conditions':[]}] for row in observation_history(result.controls['c0001'])))
    assert result.actions['a1']['task'] == task.ref and result.actions['a1']['control'] == 'c0002'

def test_latest_no_action_assessment_expires_old_action_advice():
    from regrow.records.task_updates import latest_suggestion as latest_suggestion
    (result, task) = records()
    owned_actions(result['r0001'])['a1'] = {'task': task.ref, 'control': 'c0001', 'next_action': {'action': 'click'}}
    audit(task)['latest_update'] = {'decision': 'continue', 'next_action': None, 'source': {'source_call': '2'}}
    assert latest_suggestion(result, task) is None

def test_immutable_unowned_binding_overrides_old_attempt_reverse_list(tmp_path):
    from regrow.records.action_evidence import resolve_operations as resolve_operations
    (result, task) = records()
    audit(task)['imported_attempts'] = ['a1']
    owned_actions(result['r0001'])['a1'] = {'control': 'c0001', 'operation': 'click'}
    folder = tmp_path / 'action_attempts/a1'
    folder.mkdir(parents=True)
    (folder / 'binding.json').write_text(json.dumps({'region_ref': 'r0001', 'task_name': None}))
    resolve_operations(result, tmp_path)
    assert result.actions['a1']['task'] is None and read(task, 'attempts') == []
    assert 'imported_attempts' not in audit(task)

def test_merged_knowledge_keeps_both_sources_for_later_withdrawal():
    from regrow.records.tasks import merge_products as merge_products
    from regrow.records.tasks import invalidate_products as invalidate_products
    from regrow.records.tasks import source_attempts as source_attempts
    (result, task) = records()
    owned_tasks(result['r0002'])['另一用途'] = {'name': '另一用途', 'control': 'c0002', 'status': 'done'}
    other = owned_tasks(result['r0002'])['另一用途']
    store_knowledge(task, '打开文件列表。', {'basis': 'explored', 'attempt': 'a1'})
    store_knowledge(other, '切换到目录列表。', {'basis': 'explored', 'attempt': 'a2'})
    (first, second) = (result.controls['c0001'], result.controls['c0002'])
    merge_products(first, second)
    row = next((row for row in reversed(observation_history(first)) if row.get('knowledge') == first['knowledge']))
    assert source_attempts(row['evidence']) == {'a1', 'a2'}
    invalidate_products(first, 'a2', {'source_call': '3'})
    assert first['knowledge'] == [] and any((row.get('knowledge') == [{'description':'打开文件列表。','conditions':[]}] for row in observation_history(first)))
    store_knowledge(task, '打开文件列表。', {'basis': 'observation_only', 'source_call': '4'})
    store_knowledge(task, '打开文件列表。', {'basis': 'explored', 'attempt': 'a3', 'source_call': '5'})
    invalidate_products(first, 'a3', {'source_call': '6'})
    from regrow.records.task_knowledge import observed_purpose as observed_purpose
    assert first['knowledge'] == [{'description':'打开文件列表。','conditions':[]}]
    assert observed_purpose(first)['evidence']['source_call'] == '4'
    store_knowledge(task, '只显示目录。', {'basis': 'explored', 'attempt': 'a4'})
    store_knowledge(task, '只显示目录。', {'basis': 'explored', 'attempt': 'a5'})
    invalidate_products(first, 'a5', {'source_call': '7'})
    assert first['knowledge'] == [{'description':'只显示目录。','conditions':[]}]
    invalidate_products(first, 'a4', {'source_call': '8'})
    assert first['knowledge'] == [] and (not observed_purpose(first))

def test_legacy_prerequisite_history_merges_with_separate_task_audit():
    before = {'condition': '原准备条件', 'evidence': '此前记录'}
    result = Records({'r0001': new_region('r0001', '表单')}, tasks={'r0001/准备问题': {'name': '准备问题', 'control': None, 'task_type': 'control_effect', 'status': 'pending', 'entry': None, 'prerequisite_history': [before]}}, task_history={'r0001/准备问题': {'original_ref': 'r0001/准备问题', 'result_evidence': '先前结论'}})
    task = result.tasks['r0001/准备问题']
    assert 'entry' not in task and 'prerequisite_history' not in task
    assert audit(task)['prerequisite_history'] == [before]
    assert audit(task)['result_evidence'] == '先前结论'
    assert 'entry' not in audit(task)
