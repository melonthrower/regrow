from regrow.records.tasks import coverage as _test_fn_coverage
'Known navigation meaning, visible destination and activation evidence stay distinct.'
from copy import deepcopy
import pytest
from regrow.records import entry_observation as entry_observation
from regrow.traversal import region_tasks as region_tasks
from regrow.records import task_knowledge as task_knowledge
from regrow.records import task_settlement as task_settlement
from regrow.records import task_updates as task_updates
from regrow.records import function_scope as function_scope

def case():
    task = {'name': 'inspect connection', 'control': 'link', 'action': 'click', 'conditions': [], 'registration_kind': 'entry', 'task_type': 'single_action', 'handling': 'explore', 'status': 'pending', 'reason': 'Discover connection content', 'attempts': [], 'equivalent_to': ''}
    owner = {'id': 'nav', 'name': 'Navigation', 'description': 'Navigation', 'controls': {'link': {'name': 'Connection', 'observations': [{'state': 'selected', 'evidence': {'observation': 'o'}}]}, 'parent': {'name': 'Privacy'}}, 'tasks': {'inspect connection': task}, 'actions': {}, 'transitions': []}
    dest = {'id': 'page', 'name': 'Connection settings', 'description': 'Connection settings', 'controls': {}, 'tasks': {}, 'actions': {}, 'transitions': []}
    records = {'nav': owner, 'page': dest}
    state = {'interactive_regions': ['nav', 'page'], 'observation': {'id': 'o', 'control_refs': ['link']}}
    entry = {'region': 'Connection settings', 'meaning': 'Navigate to connection settings', 'conditions': [], 'evidence': 'Connection is selected; the right panel title and checking setting correspond to it'}
    return (records, owner, task, state, entry)

def operation(task, entry=None):
    return {**{k: v for (k, v) in task.items() if k in ('name', 'action', 'conditions', 'registration_kind', 'task_type', 'handling', 'reason', 'equivalent_to')}, 'control': 'Connection', 'knowledge': 'Navigate to connection settings', 'entry': entry, 'findings': []}

def test_known_purpose_keeps_unseen_destination_pending_and_no_parameter_leak():
    (records, r, t, s, e) = case()
    r['tasks'] = {}
    region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': 'Navigation labels', 'operations': [operation(t)]}, 'q', records=records, state=s)
    task_knowledge.refresh(records, s)
    t = r['tasks']['inspect connection']
    assert t['status'] == 'pending' and (not t.get('completion_basis')) and (not r['actions'])
    learned = r['controls']['link']['knowledge']['inspect connection']
    assert learned['source']['basis'] == 'observation_only' and learned['parameters'] == {}
    assert function_scope.entries(r, records) == []
    assert _test_fn_coverage(r, records)['pending'] == ['inspect connection']

def test_entry_record_cannot_omit_destination_or_turn_known_purpose_into_completion():
    (records, r, t, s, e) = case()
    r['tasks'] = {}
    row = operation(t)
    row['handling'] = 'record'
    with pytest.raises(ValueError, match='须用entry'):
        region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': 'Selected destination visible', 'operations': [row]}, 'q', records=records, state=s)
    assert not r['tasks']
    row['registration_kind'] = 'control_effect'
    region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': 'Auxiliary entry recorded under scope', 'operations': [row]}, 'q', records=records, state=s)
    assert r['tasks'][t['name']]['status'] == 'record_only' and (not r['actions'])

@pytest.mark.parametrize('existing_exclusion', [False, True])
def test_entry_scope_record_preserves_history_without_unknown_destination(existing_exclusion):
    from regrow.traversal.traversal_scope import record_only as record_only
    (records, r, t, s, e) = case()
    t['attempts'] = ['old_attempt']
    if existing_exclusion:
        t = record_only(t, 'External destination', {'source_call': 'old_review'})
        r['tasks'][t['name']] = t
    row = operation(t)
    row.update(handling='record', reason='External destination excluded from traversal')
    region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': 'External service link', 'operations': [row]}, 'q', scope_review=False if existing_exclusion else 'task_scope_review', records=records, state=s)
    settled = r['tasks'][t['name']]
    assert settled['status'] == 'record_only' and settled['registration_kind'] == 'entry'
    assert settled['scope_exclusion'] and settled['scope_history'][0]['status'] == 'pending'
    assert settled['attempts'] == ['old_attempt']
    assert not settled.get('entry_registration') and (not settled.get('completion_basis'))
    assert not r['actions'] and (not r['transitions'])

def test_task_inventory_registers_visible_target_without_an_action_or_child_completion():
    (records, r, t, s, e) = case()
    child = deepcopy(records['page'])
    region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': e['evidence'], 'operations': [operation(t, e)]}, 'q', records=records, state=s)
    task_knowledge.refresh(records, s)
    assert t['status'] == 'done' and (not t['attempts']) and (not r['actions']) and (not r['transitions'])
    assert records['page'] == {**child, 'current_observation': {'observation': 'o', 'controls': {}}, 'operation_knowledge': {}}
    link = function_scope.entries(r, records)[0]
    assert link['status'] == 'observed_entry' and link['attempt'] is None and (link['region'] == 'page')
    assert r['controls']['link']['knowledge']['inspect connection']['source']['basis'] == 'observation_only'

def prepare_update(records, r, t, s):
    r['actions']['a'] = {'control': 'parent', 'operation': 'click', 'delivery': 'executed_receipt_zero', 'result': {'exception': 'none', 'description': 'Privacy revealed the selected Connection page'}, 'interactive_regions': ['nav', 'page'], 'region_changes': [{'region': 'page', 'state': 'changed_interactive'}], 'evidence': {'after_observation': 'o', 'result_call': 'q', 'before_regions': ['nav']}}
    b = {'region_ref': 'nav', 'task_region': 'nav', 'task_name': t['name'], 'control_ref': 'parent'}
    return (b, {'exit_code': 0, 'executed_steps': [{'action': 'click'}]})

def test_preparation_result_answers_entry_without_changing_actual_effect_or_other_task():
    (records, r, t, s, e) = case()
    (b, receipt) = prepare_update(records, r, t, s)
    other = {**deepcopy(t), 'name': 'other', 'registration_kind': 'parameter', 'control': 'parent'}
    r['tasks']['other'] = other
    before = deepcopy(r['actions']['a'])
    row = {'task': 'nav/' + t['name'], 'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': e, 'next_action': None, 'registration_gap': ''}
    task_settlement.settle_task(r, b, {'task_update': [row], 'action_result': before['result']}, 'a', records, receipt=receipt, candidates=task_updates.catalog(records, b))
    assert t['status'] == 'done' and t['completion_basis']['source_attempt'] == 'a'
    assert r['actions']['a']['control'] == 'parent' and 'entry_registration' not in r['actions']['a']
    assert r['actions']['a']['result'] == before['result'] and (not r['transitions'])
    assert other['status'] == 'pending' and (not other.get('knowledge'))

@pytest.mark.parametrize('bad', ['historical', 'visual_only', 'target_absent', 'owner_absent', 'parameter', 'conditions', 'prerequisite', 'exception', 'gap'])
def test_observation_does_not_complete_unsupported_obligations(bad):
    (records, r, t, s, e) = case()
    (b, receipt) = prepare_update(records, r, t, s)
    row = {'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': e, 'next_action': None, 'registration_gap': ''}
    if bad == 'historical':
        r['controls']['link']['observations'][0]['evidence']['observation'] = 'old'
    if bad == 'visual_only':
        r['controls']['link']['observations'][0]['visual_only'] = True
    if bad == 'target_absent':
        r['actions']['a']['interactive_regions'] = ['nav']
    if bad == 'owner_absent':
        r['actions']['a']['interactive_regions'] = ['page']
    if bad == 'parameter':
        t['registration_kind'] = 'parameter'
    if bad == 'conditions':
        t['conditions'] = ['A different page']
    if bad == 'prerequisite':
        t['prerequisite'] = {'satisfied': False}
    if bad == 'exception':
        r['actions']['a']['result']['exception'] = 'unexpected_exit'
    if bad == 'gap':
        row['registration_gap'] = 'Target not known'
    with pytest.raises(ValueError):
        task_settlement.settle_task(r, b, {'task_update': row, 'action_result': r['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert t['status'] == 'pending' and 'completion_basis' not in t

def test_no_action_routes_to_existing_task_inventory_without_fake_execution():
    (records, r, t, s, e) = case()
    s.update(next_action_mode='explore', working_region='nav', active_task={'region': 'nav', 'name': t['name']})
    r['external_entry_policy'] = 'record_only'
    q = {'source': {'region': 'nav', 'task_region': 'nav', 'task_name': t['name'], 'observation': 'o'}}
    assert entry_observation.request_review(records, s, q, {'action': 'none', 'reason': 'Already selected and content visible'})
    from regrow.traversal import traversal_scheduler as traversal_scheduler
    assert traversal_scheduler.select_work(records, s)['kind'] == 'task_proposal'
    assert s['observation']['id'] == 'o' and (not r['actions']) and (t['status'] == 'pending')

def test_executed_transition_replaces_earlier_observation_knowledge_basis():
    (records, r, t, s, e) = case()
    (b, receipt) = prepare_update(records, r, t, s)
    t['knowledge_source'] = {'basis': 'observation_only', 'source_call': 'old'}
    r['actions']['a']['control'] = 'link'
    b['control_ref'] = 'link'
    row = {'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': e, 'next_action': None, 'registration_gap': ''}
    task_settlement.settle_task(r, b, {'task_update': row, 'action_result': r['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert t['status'] == 'done' and 'knowledge_source' not in t
    assert r['actions']['a']['entry_registration']['region'] == 'page'
    assert task_knowledge.control_knowledge(r, 'link')[t['name']]['source']['basis'] == 'explored'

def test_visual_only_no_action_keeps_normal_discovery_path():
    (records, r, t, s, e) = case()
    r['controls']['link']['observations'][0]['visual_only'] = True
    q = {'source': {'region': 'nav', 'task_name': t['name'], 'observation': 'o'}}
    assert not entry_observation.request_review(records, s, q, {'action': 'none', 'reason': 'Need observation'})
    assert not r.get('task_inventory')

def test_pending_entry_without_registered_destination_returns_to_discovery():
    (records, r, t, s, e) = case()
    review = {'kind': 'entry_observation', 'task': t['name']}
    assert entry_observation.unresolved_review(r, review, s, 'current.png', 'Target still needs identification')
    assert s['next_action_mode'] == 'discover' and s['discovery_mode'] == 'relocate'
    assert t['status'] == 'pending' and (not r['actions'])

def test_deferred_entry_observation_keeps_handling_and_resolves_its_information_gap():
    (records, r, t, s, e) = case()
    t.update(handling='defer', status='blocked', blocker={'condition': 'review_required'})
    region_tasks.apply_plan(r, {'inventory': 'partial', 'evidence': e['evidence'], 'operations': [operation(t, e)]}, 'q', records=records, state=s)
    assert t['handling'] == 'defer' and t['status'] == 'done' and t['blocker_history']
    assert not r['actions']

def test_observed_entry_can_narrow_conditions_without_claiming_broader_knowledge():
    (records, r, t, s, e) = case()
    (b, receipt) = prepare_update(records, r, t, s)
    e['conditions'] = ['In privacy subnavigation']
    row = {'knowledge': 'Navigate to connection settings', 'findings': [], 'entry': e, 'next_action': None, 'registration_gap': ''}
    task_settlement.settle_task(r, b, {'task_update': row, 'action_result': r['actions']['a']['result']}, 'a', records, receipt=receipt)
    assert t['status'] == 'done' and t['conditions'] == e['conditions']
    assert t['condition_history'][0]['conditions'] == []
    assert task_knowledge.control_knowledge(r, 'link')[t['name']]['conditions'] == e['conditions']
    assert r['actions']['a']['control'] == 'parent' and 'conditions' not in r['actions']['a']
