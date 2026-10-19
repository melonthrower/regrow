from regrow.records.snapshots import publish as _test_fn_publish
from regrow.records.snapshots import load as _test_fn_load
'Publication and source readback for compact work/action records; no model claims.'
import json
from pathlib import Path
import sys
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.object_store import owned_tasks as owned_tasks
from regrow.records.object_store import owned_actions as owned_actions
from regrow.records.object_store import region_work as region_work
from regrow.records.object_store import incoming as incoming
from regrow.records.object_store import observation_history as observation_history
from regrow.records.tasks import audit as audit
from regrow.records.tasks import read as read
from regrow.records.tasks import store_findings as store_findings
from regrow.records.region_evidence import new_region as new_region
from tests.test_flat_object_store import legacy_run

def test_work_and_single_direction_navigation_survive_publish(tmp_path):
    from regrow.traversal import discovery_step as discovery_step
    from regrow.traversal.task_routing import entry_path as entry_path
    (run, _) = legacy_run(tmp_path)

    def mutate(records, state, *_):
        records['r0002'] = new_region('r0002', '明细')
        region_work(records['r0001']).update(task_inventory={'inventory': 'complete', 'controls': ['c0002']}, out_of_scope_reason='本轮只查看')
        owned_actions(records['r0001'])['a0001'] = {'control': 'c0002', 'delivery': 'executed_receipt_zero', 'operation': 'click', 'result': {'description': '明细出现', 'exception': 'none'}}
        records['r0001']['transitions'] = [{'source_control': 'c0002', 'target_region': 'r0002', 'attempt': 'a0001'}]
    pointer = _test_fn_publish(run, 'work', mutate)
    snapshot = run / pointer['snapshot']
    raw = json.loads((snapshot / 'objects.json').read_text())
    assert not {'task_inventory', 'out_of_scope_reason', 'reached_by'} & raw['regions']['r0001'].keys()
    (_, records, _) = _test_fn_load(run)
    assert region_work(records['r0001'])['out_of_scope_reason'] == '本轮只查看'
    assert incoming(records['r0002'])[0]['source_region'] == 'r0001'
    assert entry_path(records, 'r0002') == ['r0001', 'r0002']
    copy = deepcopy(records)
    region_work(copy['r0001'])['out_of_scope_reason'] = ''
    assert region_work(records['r0001'])['out_of_scope_reason']
    from gui_rewalk.src.core.scenario.collection_graph import snapshot_records
    (readonly, dependencies) = snapshot_records(snapshot)
    assert readonly['r0001']['out_of_scope_reason'] == '本轮只查看'
    assert snapshot / 'runtime_work.json' in dependencies

def test_entry_settlement_keeps_product_off_actual_action():
    from regrow.records.task_settlement import settle_task as settle_task
    from regrow.records.task_settlement import registered_result as registered_result
    from regrow.records.task_updates import latest_suggestion as latest_suggestion
    records = Records({rid: new_region(rid, name) for (rid, name) in [('r0001', '目录'), ('r0002', '明细')]})
    owner = records['r0001']
    owned_controls(owner)['c0001'] = {'name': '展开'}
    owned_tasks(owner)['展开结果'] = {'name': '展开结果', 'control': 'c0001', 'task_type': 'entry', 'status': 'pending', 'conditions': []}
    task = owned_tasks(owner)['展开结果']
    action = {'control': 'c0001', 'operation': 'click', 'delivery': 'executed_receipt_zero', 'result': {'description': '出现明细区', 'exception': 'none'}, 'interactive_regions': ['r0002'], 'evidence': {'before_regions': ['r0001'], 'result_call': '2', 'after_observation': 'o2'}}
    owned_actions(owner)['a0001'] = action
    settle_task(owner, {'region_ref': 'r0001', 'task_name': '展开结果'}, {'task_update': {'task': 'r0001/展开结果', 'decision': 'answered', 'reason': '明细已出现', 'knowledge': '显示所选目录的明细。', 'entry': {'region': '明细', 'evidence': '点击后出现明细区'}}}, 'a0001', records)
    action = owned_actions(owner)['a0001']
    assert task['status'] == 'done' and registered_result(task, action, 'a0001')
    assert not {'knowledge', 'entry_registration', 'task_update', 'next_action', 'registration_kind'} & action.keys()
    assert records.controls['c0001']['entries'][0]['attempt'] == 'a0001'
    assert latest_suggestion(records, task) is None
    assert audit(task)['latest_update']['source']['attempt'] == 'a0001'

def test_parameter_review_rebuilds_from_original_snapshot(tmp_path):
    from regrow.traversal import discovery_step as discovery_step
    from regrow.traversal import parameter_evidence_review as review
    (run, _) = legacy_run(tmp_path)

    def prepare(records, state, *_):
        task = owned_tasks(records['r0001'])['保存行为']
        task['task_type'] = 'parameter'
        observation_history(records.controls['c0002']).append({'evidence': {'observation': 'o1'}})
        owned_actions(records['r0001'])['a0001'] = {'task': 'r0001/保存行为', 'control': 'c0002', 'operation': 'input_text', 'delivery': 'executed_receipt_zero', 'result': {'description': '原观察：输入被接受', 'exception': 'none'}}
        state.update(interactive_regions=['r0001'], observation={'id': 'o1', 'control_refs': ['c0002'], 'foreground': {'exception': 'none'}})
    prior = _test_fn_publish(run, 'prepare', prepare)

    def start(records, state, *_):
        assert review.from_no_action(run, records, state, {'source': {'task_region': 'r0001', 'task_name': '保存行为', 'observation': 'o1', 'snapshot': prior['snapshot']}}, {'action': 'none', 'reason': '可从已有观察确认输入方式'}, '3')
    pointer = _test_fn_publish(run, 'review', start)
    (_, records, _) = _test_fn_load(run)
    row = region_work(records['r0001'])['task_inventory']['review']
    assert not {'context', 'frames'} & row.keys()
    owned_actions(records['r0001'])['a0001']['result']['description'] = '后来的其他观察'
    context = review.evidence_context(records['r0001'])
    assert context['最近连续动作'][0]['观察'] == '原观察：输入被接受'
    assert context['最近连续动作'][0]['原任务'] == 'r0001/保存行为'
    assert json.loads((run / pointer['snapshot'] / 'runtime_work.json').read_text())['r0001']['task_inventory']['review']['snapshot'] == prior['snapshot']

def test_parameter_observation_does_not_claim_preparation_action():
    from regrow.records.task_settlement import registered_result as registered_result
    from tests.test_task_product_storage import records, fact
    (values, task) = records()
    action = {'conditions': [], 'result': {'description': '准备完成'}}
    store_findings(task, [fact()], {'basis': 'observation_only', 'source_attempt': 'a0001'})
    assert not registered_result(task, action, 'a0001')

def test_repeat_entry_registration_preserves_earlier_actual_sources():
    from regrow.records.action_evidence import compact as compact
    from regrow.records.action_evidence import entries_for_action as entries_for_action
    from regrow.records.tasks import store_entry as store_entry
    from regrow.records.tasks import invalidate_products as invalidate_products
    from tests.test_task_product_storage import records
    (values, task) = records()
    owner = values['r0001']
    control = values.controls['c0001']
    for aid in ('a0001', 'a0002'):
        entry = {'region': 'r0002', 'conditions': [], 'attempt': aid, 'meaning': '显示目录'}
        owned_actions(owner)[aid] = {'control': 'c0001', 'entry_registration': entry}
    store_entry(task, {'region': 'r0002', 'conditions': [], 'attempt': 'a0002', 'meaning': '显示目录'})
    compact(values)
    store_entry(task, {'region': 'r0002', 'conditions': [], 'meaning': '显示目录', 'source': {'basis': 'observation_only'}})
    assert entries_for_action(owner, 'a0001', 'c0001')
    assert entries_for_action(owner, 'a0002', 'c0001')
    assert not any(('entry_registration' in a for a in values.actions.values()))
    invalidate_products(control, 'a0001', {'source_call': 'correction'})
    assert not entries_for_action(owner, 'a0001', 'c0001')
    assert entries_for_action(owner, 'a0002', 'c0001')
