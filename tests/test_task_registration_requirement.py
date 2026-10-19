"""Show the selected task's actual missing products without requiring duplicate answers."""
from copy import deepcopy
import pytest
from regrow.records import task_settlement as task_settlement
from regrow.records import task_updates as task_updates
from regrow.records import history_context as history_context

@pytest.mark.parametrize('kind,values,missing', [('parameter', {}, ['findings']), ('parameter', {'findings': {'query': {}}}, []), ('control_effect', {}, ['knowledge']), ('control_effect', {'knowledge': 'known'}, []), ('entry', {}, ['knowledge', 'entry']), ('entry', {'knowledge': 'opens', 'entry_registration': {'region': 'r'}}, [])])
def test_current_missing_fields_match_existing_product_gate(kind, values, missing):
    task = {'status': 'pending', 'registration_kind': kind, 'reason': 'question', **values}
    before = deepcopy(task)
    assert task_settlement.missing_product_fields(task) == missing
    assert task_settlement.task_product(task) == (not missing)
    assert task_settlement.registration_requirement(task) == ({'若判断answered，尚需登记': missing} if missing else {})
    assert task == before

def test_completed_or_preparation_tasks_are_not_reopened_by_product_hint():
    assert task_settlement.registration_requirement({'status': 'done', 'registration_kind': 'parameter'}) == {}
    assert task_settlement.registration_requirement({'status': 'pending', 'prepares': {'region': 'r', 'task': 'goal'}}) == {}

def test_update_catalog_and_task_goal_show_knowledge_requirement_with_precise_rejection():
    task = {'status': 'pending', 'registration_kind': 'control_effect', 'control': 'c', 'action': 'click', 'reason': 'observe the result'}
    records = {'r': {'id': 'r', 'name': 'Panel', 'controls': {'c': {'name': 'Add', 'observations': []}}, 'tasks': {'Inspect': task}, 'actions': {}}}
    binding = {'region_ref': 'r', 'task_name': 'Inspect', 'control_ref': 'c'}
    assert task_updates.catalog(records, binding)[0]['若判断answered，尚需登记'] == ['knowledge']
    assert history_context.task_goal(task, records)['若判断answered，尚需登记'] == ['knowledge']
    with pytest.raises(ValueError, match='knowledge'):
        task_updates.decide(task, {'task': 'r/Inspect', 'decision': 'answered', 'reason': 'effect observed'}, {}, product_complete=False, records=records)
