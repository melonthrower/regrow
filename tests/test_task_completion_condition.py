from copy import deepcopy
import jsonschema
import pytest

from regrow.records.object_store import Records, owned_controls, owned_tasks, save, load
from regrow.records.region_evidence import new_region
from regrow.records.snapshots import write_json
from regrow.records.task_settlement import completion_condition, exploration_goal
from regrow.records.task_updates import schema as update_schema, store_increment, catalog
from regrow.records.history_context import question
from regrow.traversal.task_proposer import proposal_schema
from regrow.traversal.region_tasks import apply_plan


def test_condition_is_saved_and_shared_by_goal_readers_and_settlement(tmp_path):
    records = Records({'r1': new_region('r1', '操作栏')})
    region = records['r1']
    owned_controls(region)['c1'] = {'name': '入口', 'knowledge': [{'description': '点击打开面板。'}]}
    condition = '操作入口并确认、记录直接响应及去向后结束。'
    reply = {'inventory': 'complete', 'evidence': '入口去向尚需确认',
             'operations': [{'control': 'c1', 'task_type': 'function', 'completion_condition': condition}],
             'shared_instances': [], 'function_updates': []}
    state = {'working_region': 'r1', 'interactive_regions': ['r1'], 'observation': {'id': 'o1'}}
    apply_plan(region, reply, 'proposal', records=records, state=state)
    save(records, tmp_path, write_json)
    restored = load(tmp_path); owner = restored['r1']; name, task = next(iter(owned_tasks(owner).items()))
    assert task['completion_condition'] == condition
    assert condition in question(owner, name, task)['探索内容']
    binding = {'region_ref': 'r1', 'control_ref': 'c1', 'task_region': 'r1', 'task_name': name}
    assert condition in catalog(restored, binding)[0]['reason']
    before = exploration_goal(task)
    store_increment(owner, task, name, {'task': 'r1/'+name, 'decision': 'continue',
                    'remaining_question': '历史模型追加的另一入口比较'}, restored, state, {'source_call': 'old-review'})
    assert exploration_goal(task) == before
    store_increment(owner, task, name, {'task': 'r1/'+name, 'decision': 'answered',
                    'reason': '已有直接打开面板的观察回答原条件。'}, restored, state, {'source_call': 'review'})
    assert task['status'] == 'done' and task['completion_condition'] == condition
    restored['r2'] = new_region('r2', '共享操作栏')
    owned_controls(restored['r2'])['c2'] = {'name': '共享入口'}
    owned_tasks(restored['r2'])['共享任务'] = {'control': 'c2', 'task_type': 'function', 'status': 'pending',
        'shared_task_ref': {'region': 'r1', 'task': name, 'control': 'c1'}}
    shared = owned_tasks(restored['r2'])['共享任务']
    assert 'completion_condition' not in shared
    assert completion_condition(shared) == condition
    from regrow.records.shared_tasks import synchronize_tasks, reconcile_detached_tasks
    restored.actions['a1'] = {'task': 'r2/共享任务'}  # Unit-only local attempt association.
    synchronize_tasks(restored)
    assert shared['shared_task_active'] is False
    reconcile_detached_tasks(restored, state, {('r2', 'c2')}, {'region': 'r2'}, 'detach')
    assert 'shared_task_ref' not in shared and shared['status'] == 'blocked'
    assert completion_condition(shared) == condition


def test_new_proposals_require_condition_but_legacy_tasks_and_updates_do_not_redefine_it():
    schema = proposal_schema()
    base = {'inventory': 'complete', 'evidence': '已考虑给定对象', 'shared_instances': [], 'function_updates': [],
            'operations': [{'control': 'c1', 'task_type': 'function'}]}
    for value in [None, '', '   ']:
        reply = deepcopy(base)
        if value is not None: reply['operations'][0]['completion_condition'] = value
        with pytest.raises(jsonschema.ValidationError): jsonschema.validate(reply, schema)
    legacy = {'control': 'c1', 'task_type': 'function', 'status': 'pending'}
    before = deepcopy(legacy)
    assert '本任务结算条件' not in exploration_goal(legacy)
    assert legacy == before
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'task': 'r1/t', 'decision': 'answered', 'completion_condition': '改成更大目标'}, update_schema())
