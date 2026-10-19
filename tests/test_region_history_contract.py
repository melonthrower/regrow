from regrow.records.snapshots import publish as _test_fn_publish
'Region history uses stable object knowledge and original task ownership.'
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.object_store import owned_tasks as owned_tasks
from regrow.records.object_store import owned_actions as owned_actions
from regrow.records.object_store import load as load
from regrow.records.region_evidence import new_region as new_region
from regrow.records.tasks import audit as audit
from regrow.records.tasks import read as read
from regrow.records import page_history as page_history
from regrow.records import context_scope as context_scope
from regrow.records import history_context as history_context
from regrow.records import task_inventory_context as task_inventory_context
from regrow.traversal import task_proposer as task_proposer

def fixture():
    rs = Records({'r0001': new_region('r0001', '文件面板'), 'r0002': new_region('r0002', '位置选择')})
    for (rid, cid, name, knowledge) in [('r0001', 'c0001', '保存', '保存文件。'), ('r0001', 'c0003', '关闭', '关闭窗口。'), ('r0002', 'c0002', '位置项', '选择保存位置。')]:
        owned_controls(rs[rid])[cid] = {'name': name, 'knowledge': knowledge}
    owned_tasks(rs['r0001'])['保存反馈'] = {'name': '保存反馈', 'control': 'c0001', 'status': 'pending', 'task_type': 'control_effect', 'conditions': ['当前文件有改动'], 'source_call': '0001'}
    owned_tasks(rs['r0001'])['关闭反馈'] = {'name': '关闭反馈', 'control': 'c0003', 'status': 'done', 'task_type': 'control_effect', 'conditions': []}

    def action(cid, owner, result, **extra):
        return {'control': cid, 'task': owner, 'operation': 'click', 'delivery': 'executed_receipt_zero', 'association': {'status': 'confirmed'}, 'result': {'description': result, 'evidence': '原始详细证据', 'exception': 'none'}, 'interactive_regions': ['r0002'], 'evidence': {'before_regions': ['r0002']}, **extra}
    owned_actions(rs['r0002'])['a0001'] = action('c0002', 'r0001/保存反馈', '已选择工作目录。', purpose='PREPARATION_INTENT')
    owned_actions(rs['r0001'])['a0002'] = action('c0001', 'r0001/保存反馈', '显示“目录不可写”。', conditions=['当前文件有改动'])
    owned_actions(rs['r0001'])['a0009'] = action('c0003', 'r0001/关闭反馈', 'UNRELATED_COMPLETED_OPERATION')
    state = {'working_region': 'r0001', 'interactive_regions': ['r0001'], 'observation': {'id': 'o1', 'image': 'frame.png', 'control_refs': ['c0001', 'c0003']}, 'active_task': {'region': 'r0001', 'name': '保存反馈'}, '_work_context': {'kind': 'action', 'region': 'r0001', 'task': {'region': 'r0001', 'name': '保存反馈'}}}
    return (rs, state)

def test_task_history_keeps_original_owner_preparation_failure_and_conditions():
    (rs, state) = fixture()
    before = deepcopy(rs.packed())
    h = page_history.build(rs, state)
    text = page_history.render(h)
    assert set(h['events']) == {'a0001', 'a0002'}
    assert all((row.get('task') == 'r0001/保存反馈' for row in h['events'].values()))
    assert '保存反馈' not in text
    assert '位置项' in text and '已选择工作目录。' in text and ('目录不可写' in text)
    assert '当前文件有改动' in text and 'PREPARATION_INTENT' not in text
    assert 'UNRELATED_COMPLETED_OPERATION' not in text
    assert page_history.reference(h, 'a0001') == '动作 a0001'
    assert rs.packed() == before

def test_delivery_failure_and_unconfirmed_target_do_not_become_success():
    (rs, state) = fixture()
    row = rs.actions['a0002']
    row.update(delivery='dispatch_failed', text_delivered=False, text='report')
    row['association'] = {'status': 'unconfirmed', 'target': '保存候选'}
    h = page_history.build(rs, state)
    text = page_history.render(h)
    assert 'dispatch_failed' in text and '未确认' in text and ('未发送' in text)
    assert h['events']['a0002']['control'] is None and h['events']['a0002'].get('缺口')

def test_inventory_shows_questions_and_one_copy_of_knowledge():
    (rs, state) = fixture()
    audit(rs.tasks['r0001/关闭反馈'])['latest_update'] = {'decision': 'answered', 'reason': 'OLD_COMPLETION_BODY', 'source': {'source_call': '0003'}}
    work = {'kind': 'task_proposal', 'region': 'r0001', 'task': None, 'reason': '提出本区块尚未回答的问题'}
    state = {**state, 'active_task': None, '_work_context': work}
    assert context_scope.select(rs, state)['tasks'] == [{'region': 'r0001', 'name': '保存反馈'}]
    catalog = task_inventory_context.task_catalog(rs['r0001'], state, rs)
    completed = next((row for row in catalog if row['task'] == 'r0001/关闭反馈'))
    assert completed['status'] == 'done' and '最新判断' not in completed and ('knowledge' not in completed)
    assert 'source_call' not in json.dumps(catalog)
    q = task_proposer.plan_request(ROOT, rs, state, 'r0001', work=work)
    assert 'OLD_COMPLETION_BODY' not in q['user_prompt']
    assert q['user_prompt'].count('保存文件。') == 1
    assert 'UNRELATED_COMPLETED_OPERATION' not in q['user_prompt']

def test_material_selects_only_relevant_control_constraints():
    (rs, state) = fixture()
    rs.controls['c0001']['constraints'] = {'文件名': {'conditions': ['自定义名称'], 'domain': {'type': 'text'}}}
    rs.controls['c0003']['constraints'] = {'unrelated': 'NOISE'}
    scope = context_scope.select(rs, state)
    assert context_scope.control_information(rs['r0001'], 'c0001', scope)['constraints']['文件名']['conditions'] == ['自定义名称']
    assert context_scope.control_information(rs['r0001'], 'c0003', scope) == {'knowledge': '关闭窗口。'}
    scope['kind'] = 'locate'
    assert context_scope.control_information(rs['r0001'], 'c0001', scope) == {}

def test_question_keeps_unresolved_conditions_and_failure_without_source_metadata():
    (rs, state) = fixture()
    t = rs.tasks['r0001/保存反馈']
    t['blocker'] = {'condition': 'permission', 'reason': '目录不可写', 'source_call': '0012'}
    audit(t)['latest_update'] = {'decision': 'defer', 'reason': '目录不可写', 'registration_gap': '尚未确认文件保存', 'retry_when': '选择可写目录', 'source': {'source_call': '0012'}}
    row = history_context.question(rs['r0001'], '保存反馈', t)
    assert row['conditions'] == ['当前文件有改动'] and row['最新判断']['registration_gap'] == '尚未确认文件保存'
    assert row['blocker']['condition'] == 'permission' and 'source_call' not in json.dumps(row)

def test_constraint_and_creation_source_survive_normal_publish_reload(tmp_path):
    from regrow.traversal import discovery_step as discovery_step
    from tests.test_flat_object_store import legacy_run
    (run, _) = legacy_run(tmp_path)

    def mutate(rs, state, *args):
        c = owned_controls(rs['r0001'])['c0002']
        assert 'parameters' not in c
        c['constraints'] = {'文件名': {'description': '用于命名文件', 'domain': {'type': 'text'}, 'conditions': []}}
        audit(rs.tasks['r0001/保存行为'])['source_call'] = '0012'
    pointer = _test_fn_publish(run, 'constraint-history', mutate)
    snapshot = run / pointer['snapshot']
    rs = load(snapshot)
    task = rs.tasks['r0001/保存行为']
    raw = json.loads((snapshot / 'tasks.json').read_text())['r0001/保存行为']
    assert 'source_call' not in raw and read(task, 'source_call') == '0012'
    assert rs.controls['c0002']['constraints']['文件名']['domain'] == {'type': 'text'}
    assert 'parameters' not in json.dumps(json.loads((snapshot / 'objects.json').read_text()))
    imported = Records({'r0001': {**new_region('r0001', '旧区块'), 'parameters': {'旧规则': {'description': '保留限制'}}}})
    assert imported['r0001']['constraints']['旧规则']['description'] == '保留限制'

def test_same_constraint_keeps_independent_execution_when_prior_source_is_withdrawn():
    from tests.test_task_product_storage import records, fact
    from regrow.records.tasks import store_findings as store_findings
    from regrow.records.tasks import invalidate_products as invalidate_products
    from regrow.records.object_store import observation_history as observation_history
    (rs, task) = records()
    control = rs.controls['c0001']
    store_findings(task, [fact()], {'basis': 'explored', 'attempt': 'a0001', 'source_call': '1'})
    store_findings(task, [fact()], {'basis': 'explored', 'attempt': 'a0002', 'source_call': '2'})
    count = len(observation_history(control))
    store_findings(task, [fact()], {'basis': 'explored', 'attempt': 'a0002', 'source_call': '2'})
    assert len(observation_history(control)) == count
    invalidate_products(control, 'a0001', {'source_call': '3'})
    assert control['constraints']['匹配方式']['domain']['values'] == ['完整名称', '部分名称']
    assert {v['attempt'] for v in read(task, 'findings')['匹配方式']['sources']} == {'a0002'}

def test_readiness_audit_does_not_become_another_prompt_history():
    from regrow.records.tasks import describe as describe
    dependency = {'region': '位置选择', 'control': '位置项', 'condition': '已选择保存位置', 'preparation': '选择工作目录', 'permitted': True, 'evidence': '旧判断', 'last_check': {'source_call': '1', 'evidence': 'NOT_READY'}, 'satisfied': {'source_call': '2', 'evidence': 'READY'}, 'scheduled': {'region': 'r0002', 'task': '准备选择'}}
    value = describe(dependency)
    assert value == {k: dependency[k] for k in ('region', 'control', 'condition', 'preparation', 'permitted')}
    (rs, state) = fixture()
    task = rs.tasks['r0001/保存反馈']
    task['prerequisite'] = dependency
    task['deferral'] = {'reason': 'OLD_READY_REASON', 'retry_when': 'observed_prerequisite_satisfied'}
    audit(task)['blocker_history'] = [{'reason': 'RESOLVED', 'resolved_by': '2'}]
    (material, evidence) = history_context.action_context(rs, state, 'r0001', '保存反馈', task)
    assert '已解除的历史阻塞' not in material
    assert all((s not in json.dumps(material) for s in ('NOT_READY', 'READY', 'RESOLVED', 'scheduled')))
    assert evidence['resolved_blockers']

def test_action_material_is_question_target_condition_and_actual_process():
    (rs, state) = fixture()
    task = rs.tasks['r0001/保存反馈']
    task['prerequisite'] = {'condition': '已选择位置', 'satisfied': {'evidence': 'YES'}}
    audit(task)['latest_update'] = {'decision': 'continue', 'reason': 'MANAGEMENT_REASON', 'registration_gap': '尚未看到保存结果'}
    (material, _) = history_context.action_context(rs, state, 'r0001', '保存反馈', task)
    assert material['当前任务'] == {'task': 'r0001/保存反馈', 'control': 'c0001', 'conditions': ['当前文件有改动'], '所需条件': '已选择位置', '未答部分': '尚未看到保存结果'}
    assert 'MANAGEMENT_REASON' not in json.dumps(material) and '若判断answered' not in json.dumps(material)

def test_withdrawn_task_association_is_explicit_in_brief_event_row():
    (rs, state) = fixture()
    task = rs.tasks['r0001/保存反馈']
    audit(task)['ownership_history'] = [{'invalidated_attempt': 'a0002'}]
    rs.actions['a0002']['task'] = 'r0001/另一个问题'
    text = page_history.render(page_history.build(rs, state))
    assert 'a0002' in text and '归属已撤销' in text
    assert '目录不可写' in text

def test_completed_preparation_does_not_expand_its_constraint_catalog():
    (rs, state) = fixture()
    owned_tasks(rs['r0002'])['准备选择'] = {'name': '准备选择', 'control': 'c0002', 'status': 'done', 'task_type': 'control_effect', 'prepares': {'region': 'r0001', 'task': '保存反馈'}}
    rs.controls['c0002']['constraints'] = {'OLD_OPTIONS': {'domain': {'type': 'enum', 'values': ['a', 'b']}}}
    scope = context_scope.select(rs, state)
    assert 'constraints' not in context_scope.control_information(rs['r0002'], 'c0002', scope)

def test_shared_knowledge_meaning_is_sent_for_control_and_task_outputs():
    definition = (ROOT / 'regrow/prompts/共享/任务知识与当前观察.prompt').read_text().split('\n## ', 1)[0].strip()
    from regrow.prompts import output as output_contract
    from regrow.records.task_updates import schema as schema
    q = {'role': 'task_proposal', 'system_prompt': '', 'fixed_parts': [], 'response_schema': schema(['parameter']), 'user_prompt': '{}'}
    sent = output_contract.prepare(q, ROOT)['system_prompt']
    assert '具体未答问题留在任务中' in sent
    assert definition in sent
    assert sent.count('## 功能知识的内容') == 1
    q['response_schema'] = {'type': 'object', 'properties': {'controls': {'type': 'array', 'items': {'type': 'object', 'properties': {'knowledge': {'type': 'string'}}}}}}
    sent = output_contract.prepare(q, ROOT)['system_prompt']
    assert definition in sent

def test_region_summary_receives_the_same_functional_knowledge_definition():
    definition = (ROOT / 'regrow/prompts/共享/任务知识与当前观察.prompt').read_text().split('\n## ', 1)[0].strip()
    from regrow.prompts import output as output_contract
    from regrow.traversal import region_functions as region_functions
    q = {'role': 'function_registration', 'system_prompt': '', 'fixed_parts': [], 'response_schema': region_functions.schema(ROOT), 'user_prompt': '{}'}
    sent = output_contract.prepare(q, ROOT)['system_prompt']
    assert definition in sent
    assert '任务知识的归属' not in sent and '控件知识与外观' not in sent
