"""Task products and the final normal/correction output contract agree."""
from copy import deepcopy
from pathlib import Path
import jsonschema
import pytest
from regrow.runtime import action_commands as action_commands
from regrow.prompts import output as output_contract
from regrow.traversal import task_proposer as task_proposer
from regrow.records import task_knowledge as task_knowledge
from regrow.records import task_settlement as task_settlement
from regrow.records import task_updates as task_updates
from regrow.traversal import region_tasks as region_tasks
from tests.test_explicit_task_decisions import case, row, register
from tests.test_task_knowledge_flow import fact
ROOT = Path(task_proposer.__file__).parent

def test_parameter_answer_without_duplicate_knowledge_reaches_next_inventory():
    (r, t, records, state) = case('parameter')
    register(r, t, records, state, row(findings=[fact()]))
    task_knowledge.refresh(records, state)
    assert t['status'] == 'done' and (not t.get('knowledge')) and (not t['attempts'])
    assert t['findings']['duration']['source']['basis'] == 'observation_only'
    value = r['controls']['c']['knowledge']['question']
    assert value['parameters']['duration']['domain']['values'] == ['1 minute', '5 minutes']
    assert value['source']['basis'] == 'observation_only'
    from regrow.records import task_inventory_context as task_inventory_context
    after = task_inventory_context.task_catalog(r, state, records)
    assert after[0]['已知参数']['duration']['domain']['values'] == ['1 minute', '5 minutes']

def test_record_parameter_without_knowledge_preserves_observation_source():
    (r, t, records, state) = case('parameter')
    r['tasks'] = {}
    item = dict(control='Choice', name='options', action='click', registration_kind='parameter', conditions=[], handling='record', reason='Observed options', findings=[fact()])
    region_tasks.apply_plan(r, dict(inventory='complete', evidence='Current options', operations=[item], shared_instances=[]), '002', records=records, state=state)
    task_knowledge.refresh(records, state)
    assert r['tasks']['options']['status'] == 'record_only' and (not r['actions'])
    assert r['controls']['c']['knowledge']['options']['parameters']['duration']
    assert r['controls']['c']['knowledge']['options']['source']['basis'] == 'observation_only'

def test_action_product_does_not_require_duplicate_sentence():
    (_, t, _, _) = case('parameter')
    action = dict(conditions=[], knowledge='', parameter_findings=[fact()])
    assert task_settlement.registered_result(t, action)
    action['registration_gap'] = 'Missing options'
    action['registration_kind'] = 'parameter'
    assert not task_settlement.registered_result(t, action)

@pytest.mark.parametrize('answer', [row('continue'), row('defer', registration_gap='Need observation'), row(next_action=None), row(registration_gap='Still unknown'), row('continue', registration_gap='Need observation', retry_when='Later'), row(findings=[fact()])])
def test_decision_and_product_fields_cannot_cross_meanings(answer):
    (_, task, _, _) = case('control_effect')
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        task_updates.validate(answer, task)

def test_android_restricts_actions_without_dropping_task_definition():
    schema = action_commands.platform_request({'response_schema': task_proposer.proposal_schema()}, 'android')['response_schema']
    new = schema['properties']['operations']['items']['anyOf'][0]
    assert 'click' in new['properties']['action']['enum'] and 'hover' not in new['properties']['action']['enum']
    assert len(schema['properties']['operations']['items']['anyOf']) == 2

def test_delivery_is_idempotent_and_correction_keeps_single_glossary():
    from regrow.prompts.compose import parts as parts
    from regrow.traversal.step_repair import request as request
    fixed = parts(ROOT, 'task_proposal')
    q = dict(role='task_proposal', stage='task_proposal', system_prompt='\n\n'.join((p['text'] for p in fixed)), user_prompt='{}', fixed_parts=fixed, screenshots=[], response_schema=task_proposer.proposal_schema())
    sent = output_contract.prepare(q, ROOT)
    assert output_contract.prepare(sent, ROOT) == sent
    assert sent['system_prompt'].count('# 术语定义\n') == 1
    assert sent['system_prompt'].count('- continue：') == 1
    assert sent['system_prompt'] == '\n\n'.join((p['text'] for p in sent['fixed_parts']))
    job = dict(stage='task_proposal', request=sent, candidate={}, history=[], supplements=[], error='Missing evidence')
    corrected = output_contract.prepare(request(ROOT, job, {}), ROOT)
    assert corrected['system_prompt'].count('# 术语定义\n') == 1
    assert corrected['system_prompt'].count('- continue：') == 1
    assert corrected['system_prompt'].count('字段名后的?') == 1
    assert '原步骤保存规则' not in [p['path'] for p in corrected['fixed_parts']]
    assert corrected['original_request']['response_schema'] == sent['response_schema']

def test_parameter_observation_shares_without_inventing_member_execution():
    (r, t, records, state) = case('parameter')
    register(r, t, records, state, row(findings=[fact()]))
    other = deepcopy(r)
    other.update(id='other', name='Other panel', tasks={}, actions={})
    records['other'] = other
    region_tasks.apply_plan(other, dict(inventory='complete', evidence='Equivalent observed member', operations=[], shared_instances=[dict(control='Choice', source_region='r', source_control='c', reason='Same operation and parameter meaning')]), '003', records=records, state=state)
    proxy = next(iter(other['tasks'].values()))
    assert proxy['status'] == 'record_only' and proxy['shared_result']['observation_only']
    assert proxy['attempts'] == [] and other['actions'] == {}
    task_knowledge.refresh(records, state)
    value = next(iter(other['controls']['c']['knowledge'].values()))
    assert value['parameters']['duration']['domain']['values'] == ['1 minute', '5 minutes']
    assert value['source']['local_execution'] is False

def test_related_answer_does_not_rewrite_active_action_assessment():
    (r, t, records, state) = case('parameter')
    old = deepcopy(t)
    old.update(name='purpose', registration_kind='control_effect', knowledge='Select a duration')
    r['tasks']['purpose'] = old
    a = dict(control='c', operation='click', delivery='executed_receipt_zero', result={'exception': 'none', 'description': 'Duration list displayed'}, interactive_regions=['r'], evidence={'result_call': '002', 'after_observation': 'o'}, parameter_findings=[fact()])
    r['actions']['a'] = a
    candidates = [dict(task='r/' + name, region='r', name=name, control='c', conditions=[]) for name in ('question', 'purpose')]
    active = row('continue', findings=[fact()], registration_gap='Minimum remains unknown', next_action={'region': 'Panel', 'control': 'Choice', 'action': 'click', 'reason': 'Observe remaining range'})
    related = dict(task='r/purpose', decision='answered', reason='Use already observed', knowledge='Select a duration')
    task_settlement.settle_task(r, dict(region_ref='r', task_region='r', task_name='question', control_ref='c'), {'task_update': [active, related]}, 'a', records, candidates=candidates)
    assert t['status'] == 'pending' and old['status'] == 'done'
    assert a['registration_kind'] == 'parameter' and a['registration_gap'] == 'Minimum remains unknown'
    assert a['next_action']['control'] == 'c' and a['knowledge'] == ''
    assert t['attempts'] == ['a'] and old['attempts'] == []
    assert old['knowledge_source']['attempt'] == 'a' and len(a['task_update']) == 2

def test_final_input_mentions_json_before_any_delivery(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from regrow.runtime.model_transport import ModelTransport as ModelTransport
    from regrow.runtime.model_transport import BudgetExhausted as BudgetExhausted
    from regrow.runtime import progress as progress
    from regrow.traversal import task_prerequisites as task_prerequisites
    from regrow.prompts import history_disclosure as history_disclosure
    q = dict(role='task_result_review', stage='task_result_review', system_prompt='', user_prompt='{"原问题":"事实"}', fixed_parts=[], screenshots=[], response_schema=task_updates.object_schema({'task_update': task_updates.schema()}))
    monkeypatch.setattr(task_prerequisites, 'augment', lambda root, run, q: q)
    sent = []
    monkeypatch.setattr(progress, 'request', lambda q: sent.append(q))
    obj = SimpleNamespace(root=ROOT, run=tmp_path, platform='desktop', account={'http_started': 0, 'max_http': 0})
    with pytest.raises(BudgetExhausted):
        ModelTransport.call(obj, q)
    assert sent and sent[0]['user_prompt'].endswith('请按上述字段与输出要求返回一个JSON对象。')
    restored = history_disclosure.structured_text(sent[0])
    assert restored.startswith('{') and '原问题' in restored
    assert history_disclosure.restore(sent[0])['user_prompt'] == restored

def test_focused_review_cannot_change_neighbor_strategy_but_scope_review_can():
    (r, t, records, state) = case('parameter')
    neighbor = deepcopy(t)
    neighbor.update(name='next', registration_kind='control_effect')
    r['tasks']['next'] = neighbor
    r['task_inventory'] = {'review': {'kind': 'parameter_facts', 'task': 'question'}}
    assert task_proposer.update_names(r) == ['question']
    assert task_proposer.update_names(r, scope_review=True) == ['question', 'next']
    answer = dict(task='r/next', decision='defer', reason='This stage does not execute', registration_gap='Needs click', retry_when='Action stage')
    with pytest.raises(ValueError, match='只评估原任务'):
        region_tasks.apply_plan(r, dict(inventory='partial', evidence='Current question', operations=[answer], shared_instances=[]), '002', records=records, state=state)
    assert neighbor['status'] == 'pending' and 'latest_update' not in neighbor

def test_recovery_output_has_only_actual_operations_and_no_task_decisions():
    from regrow.traversal import recovery as recovery
    from regrow.prompts import compose as prompt_rules
    s = recovery.schema()
    assert 'task_update' not in output_contract.fields(s)
    branches = s['properties']['action']['anyOf'][0]['properties']['operation']['anyOf']
    assert branches and all(('none' not in b['properties']['action']['enum'] for b in branches))
    fixed = prompt_rules.parts(ROOT, 'recovery')
    text = '\n'.join((p['text'] for p in fixed))
    assert '有原任务且已有回答' not in text
    assert 'task_update' in output_contract.fields(action_commands.schema())

def test_platform_operation_rules_agree_with_recovery_and_ownership_fields():
    from regrow.prompts.output import android_part as android_part
    from regrow.prompts.output import desktop_parts as desktop_parts
    for role in ('action_selection', 'recovery', 'ownership_review'):
        android = android_part(ROOT, {'role': role})['text']
        desktop = '\n'.join((p['text'] for p in desktop_parts(ROOT, {'role': role})))
        assert '未用字段填null' not in android
        assert 'scroll：从 x、y 滑至 end_x、end_y' in android
        assert 'end_x、end_y 编码方向与幅度' in desktop
        assert 'none' not in android + desktop
