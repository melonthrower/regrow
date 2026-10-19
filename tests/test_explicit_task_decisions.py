"""Explicit strategy, incremental evidence, and provenance through shared contracts."""
from copy import deepcopy
from pathlib import Path
import jsonschema
import pytest
from regrow.records import task_updates as u
from regrow.records import task_settlement as s
from regrow.traversal import task_deferral as task_deferral
from regrow.traversal import task_result_review as task_result_review
from regrow.traversal import task_proposer as task_proposer
from regrow.runtime.model_transport import compact_schema as compact_schema

def case(kind='control_effect'):
    t = dict(name='question', control='c', action='click', registration_kind=kind, task_type='single_action', conditions=[], handling='explore', status='pending', reason='Determine what this control does', attempts=[], equivalent_to='')
    r = dict(id='r', name='Panel', description='Panel', controls={'c': {'name': 'Choice', 'observations': [{'evidence': {'observation': 'o', 'source_call': '001'}, 'image': 'crop.png'}]}}, tasks={'question': t}, actions={}, transitions=[])
    state = dict(observation={'id': 'o', 'foreground': {'exception': 'none'}, 'control_refs': ['c']}, interactive_regions=['r'])
    return (r, t, {'r': r}, state)

def row(decision='answered', **extra):
    return dict(task='r/question', decision=decision, reason='The supplied observation answers this question', **extra)

def register(r, t, records, state, answer, call='002', observed=True):
    return u.store_increment(r, t, 'question', answer, records, state, {'basis': 'observation_only', 'source_call': call, 'observation': 'o'}, observed=observed)

def test_partial_facts_survive_strategy_and_minimal_answer_expires_advice():
    (r, t, records, state) = case()
    register(r, t, records, state, row('continue', knowledge='Opens a panel.', registration_gap='Which content?', next_action={'region': 'Panel', 'control': 'Choice', 'action': 'click', 'reason': 'Inspect content'}))
    assert t['status'] == 'pending' and u.latest_suggestion(records, t)['control'] == 'c'
    register(r, t, records, state, row(knowledge='Panel contains the clock.'), call='003')
    assert t['status'] == 'done' and 'Opens a panel.' in t['knowledge'] and ('contains the clock' in t['knowledge'])
    assert u.latest_suggestion(records, t) is None and 'registration_gap' not in t['latest_update']
    assert t['history'][0]['knowledge_source']['source_call'] == '002' and (not t['attempts'])

def test_continue_omission_and_schemas_do_not_share_mutable_fields():
    (r, t, records, state) = case()
    answer = row('continue', registration_gap='Need content')
    jsonschema.validate(answer, u.schema(['control_effect'], ['r/question']))
    schema = task_proposer.proposal_schema()
    sharing = schema['properties']['shared_instances']['items']['properties']
    sharing['source_control']['enum'] = ['c']
    new = dict(control='Choice', name='purpose', action='click', registration_kind='control_effect', conditions=[], handling='record', reason='Label explains purpose', knowledge='Selects a choice')
    payload = dict(inventory='complete', evidence='One observed control', operations=[new], shared_instances=[])
    jsonschema.validate(payload, schema)
    jsonschema.validate(payload, compact_schema(schema))
    assert 'enum' not in sharing['reason']

def test_deferred_continue_is_runnable_outside_current_surface():
    (r, t, records, state) = case()
    t.update(handling='defer', status='blocked', deferral={'reason': 'not now'})
    register(r, t, records, state, row('continue', registration_gap='Still need feedback'))
    assert t['handling'] == 'explore' and task_deferral.runnable(r, records)

def test_new_observation_requests_one_review_without_overriding_defer():
    (r, t, records, state) = case()
    register(r, t, records, state, row('defer', registration_gap='Need another observation', retry_when='Control visible'))
    r['controls']['c']['observations'].append({'image': 'new.png', 'evidence': {'source_call': '003', 'observation': 'new'}})
    task_deferral.resume_localized(records, ['r'], '003', {'exception': 'none'})
    assert t['status'] == 'blocked' and task_result_review.reviewable(t, 'new')
    register(r, t, records, {**state, 'observation': {'id': 'new'}}, row('defer', registration_gap='Still disabled', retry_when='Enabled'), call='004')
    t['latest_update']['source']['observation'] = 'new'
    assert not task_result_review.reviewable(t, 'new')

@pytest.mark.parametrize('blocker', [{'exception': 'unexpected_exit'}, {'condition': 'prerequisite'}])
def test_answer_cannot_erase_hard_block(blocker):
    (r, t, records, state) = case()
    t['blocker'] = blocker
    with pytest.raises(ValueError, match='真实执行'):
        register(r, t, records, state, row(knowledge='Known'))
    assert t['status'] != 'done' and t['blocker'] == blocker

def test_preparation_needs_observed_readiness_and_cannot_complete_business():
    (r, t, records, state) = case()
    t['prepares'] = {'region': 'r', 'task': 'business'}
    parent = dict(status='blocked', prerequisite={})
    r['tasks']['business'] = parent
    with pytest.raises(ValueError):
        register(r, t, records, state, row())
    parent['prerequisite']['satisfied'] = {'source_call': '002', 'evidence': 'Original target visibly enabled'}
    with pytest.raises(ValueError, match='冲突'):
        register(r, t, records, state, row('continue', registration_gap='Unready'))
    register(r, t, records, state, row())
    assert t['status'] == 'done' and parent['status'] == 'blocked' and (not t['attempts'])

def test_observation_facts_do_not_become_preparation_click_effects():
    (r, t, records, state) = case()
    r['controls']['other'] = {'name': 'Other'}
    r['actions']['a'] = dict(control='other', operation='click', delivery='executed_receipt_zero', result={'exception': 'none', 'description': 'Panel exposed'}, interactive_regions=['r'], evidence={'result_call': '002', 'after_observation': 'o'})
    b = dict(region_ref='r', task_region='r', task_name='question', control_ref='other')
    s.settle_task(r, b, {'task_update': row(knowledge='Choice selects a clock')}, 'a', records)
    assert t['status'] == 'done' and t['knowledge_source']['basis'] == 'observation_only'
    assert not r['actions']['a'].get('knowledge') and t['knowledge_source']['source_attempt'] == 'a'

def test_none_fact_source_is_sent_frame_without_old_observation_gate(tmp_path):
    (r, t, records, state) = case()
    (tmp_path / 'old').write_bytes(b'old')
    (tmp_path / 'new').write_bytes(b'new')
    state['observation']['image'] = 'old'
    q = {'screenshots': ['new'], 'source': {'observation': 'o'}}
    assert u.current_frame(tmp_path, q, r, t, state) == tmp_path / 'new'
    q['screenshots'] = ['old']
    assert u.current_frame(tmp_path, q, r, t, state) == tmp_path / 'old'

def test_wire_action_parameters_remain_platform_specific():
    from regrow.runtime import action_commands as a
    payload = {'operation': dict(action='click', target='Choice', reason='Inspect', x=0, y=12)}
    a.validate(payload)
    assert a.commands(payload)[0][-2:] == ['0', '12']
    with pytest.raises(jsonschema.ValidationError):
        a.validate({'operation': {**payload['operation'], 'text': None}})
    q = a.platform_request({'response_schema': a.schema()}, 'android')
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'operation': dict(action='hover', target='Choice', reason='Inspect', x=0, y=0)}, q['response_schema'])

def test_compact_contract_survives_normal_correction_embedding():
    from regrow.runtime.model_transport import expand_schema as expand_schema
    raw = task_proposer.proposal_schema()
    sent = compact_schema(raw)
    expanded = expand_schema(sent)
    assert expanded == raw
    wrapper = compact_schema(u.object_schema({'proposal': expanded}))
    payload = {'proposal': dict(inventory='partial', evidence='No new information', operations=[], shared_instances=[])}
    jsonschema.validate(payload, wrapper)

def test_minimal_answer_can_adopt_same_task_recorded_knowledge():
    (r, t, records, state) = case('parameter')
    t['attempts'] = ['a']
    t['findings'] = {'known': {'description': 'Already registered'}}
    r['actions']['a'] = dict(control='c', operation='click', delivery='executed_receipt_zero', result={'exception': 'none', 'description': 'List displayed'}, knowledge='Opens a radio list', evidence={'result_call': '001'})
    register(r, t, records, state, row(), observed=False)
    assert t['status'] == 'done' and t['knowledge'] == 'Opens a radio list'
    assert t['knowledge_source']['source_call'] == '001' and t['latest_update']['source']['source_call'] == '002'
