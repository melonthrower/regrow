from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import fixture
from tests.test_stepwise_region_tasks import tasks, row, proposal

def case():
    (_, records, state) = fixture()
    owner = records['menu']
    owner['actions'] = {}
    owner['transitions'] = []
    state.update(working_region='menu', interactive_regions=['menu'])
    operation = dict(row(), registration_kind='parameter', task_type='parameter', action='input_text', conditions=[], knowledge='', findings=[])
    tasks().apply_plan(owner, proposal([operation]), 'seed', records=records, state=state)
    task = owner['tasks'][operation['name']]
    return (records, state, owner, task, operation)

def test_none_uses_fact_author_then_records_observation_without_adopting_actions(tmp_path):
    from regrow.traversal import parameter_evidence_review as review
    from regrow.records import task_knowledge as task_knowledge
    (records, state, owner, task, operation) = case()
    q = {'source': {'region': 'menu', 'task_region': 'menu', 'task_name': operation['name'], 'observation': 'now'}}
    before = deepcopy(owner['actions'])
    assert review.from_no_action(tmp_path, records, state, q, {'action': 'none', 'reason': '当前参数选项已明确'}, 'none')
    assert owner['task_inventory']['review']['kind'] == 'parameter_facts'
    assert task['status'] == 'pending'
    operation.update(knowledge='选择一个已列出的值作为输入。', findings=[{'name': '输入选项', 'description': '当前可见两项', 'domain': {'type': 'enum', 'values': ['A', 'B'], 'min': None, 'max': None}, 'conditions': [], 'evidence': '当前同一参数控件列出 A 与 B'}])
    tasks().apply_plan(owner, proposal([operation]), 'facts', records=records, state=state)
    assert task['status'] == 'done' and task['handling'] == 'explore' and (task['attempts'] == [])
    assert task['completion_basis']['basis'] == 'observation_only' and owner['actions'] == before
    task_knowledge.refresh(records, state)
    knowledge = owner['controls']['open']['knowledge'][operation['name']]
    assert knowledge['source']['basis'] == 'observation_only'
    assert knowledge['parameters']['输入选项']['domain']['values'] == ['A', 'B']

@pytest.mark.parametrize('boundary', ['visual_only', 'prepares', 'blocker', 'no_control_observation'])
def test_none_does_not_replace_missing_semantics_or_other_obligations(tmp_path, boundary):
    from regrow.traversal import parameter_evidence_review as review
    (records, state, owner, task, operation) = case()
    if boundary == 'visual_only':
        owner['controls']['open']['observations'][0]['visual_only'] = True
    if boundary == 'prepares':
        task['prepares'] = {'region': 'menu', 'task': 'other'}
    if boundary == 'blocker':
        task['blocker'] = {'condition': 'review_required'}
    if boundary == 'no_control_observation':
        state['observation']['control_refs'] = []
    q = {'source': {'region': 'menu', 'task_name': operation['name'], 'observation': 'now'}}
    assert not review.from_no_action(tmp_path, records, state, q, {'action': 'none', 'reason': '已有答案'}, 'none')
    assert task['status'] == 'pending' and (not owner.get('task_inventory', {}).get('review'))

def test_missing_facts_cannot_finish_and_unanswered_review_keeps_gap(tmp_path):
    from regrow.traversal import parameter_evidence_review as review
    (records, state, owner, task, operation) = case()
    q = {'source': {'region': 'menu', 'task_name': operation['name'], 'observation': 'now'}}
    review.from_no_action(tmp_path, records, state, q, {'action': 'none', 'reason': '请核对'}, 'none')
    operation['knowledge'] = '只有文字判断，无参数事实'
    with pytest.raises(ValueError, match='findings'):
        tasks().apply_plan(owner, proposal([operation]), 'bad', records=records, state=state)
    assert task['status'] == 'pending'
    saved = deepcopy(owner['task_inventory']['review'])
    operation['knowledge'] = ''
    tasks().apply_plan(owner, proposal([operation]), 'gap', records=records, state=state)
    review.unresolved(owner, saved, state, '参数范围仍不可见', 'gap')
    assert task['status'] == 'blocked' and '参数范围仍不可见' in task['blocker']['reason']
    assert not task.get('completion_basis')

def test_cumulative_fact_review_retains_its_original_settlement_path_and_blank_is_not_answer():
    from regrow.traversal import parameter_evidence_review as review
    (records, state, owner, task, operation) = case()
    owner['task_inventory']['review'] = {'kind': 'parameter_facts', 'task': operation['name'], 'episode': 'repair_episodes/old/episode.json'}
    saved = deepcopy(owner['task_inventory']['review'])
    assert not review.reviewing(owner, task, operation['name'], state)
    review.unresolved(owner, saved, state, '只有参数补录', 'old')
    assert task['status'] == 'pending'
    owner['task_inventory']['review'].pop('episode')
    operation.update(knowledge='  \n ', findings=[{'name': '选项', 'description': '两项', 'domain': {'type': 'enum', 'values': ['A', 'B'], 'min': None, 'max': None}, 'conditions': [], 'evidence': '当前可见'}])
    review.register(owner, task, operation['name'], operation, state, 'blank')
    assert task['status'] == 'pending' and (not task.get('completion_basis'))
