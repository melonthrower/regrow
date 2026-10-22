from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.paths import SOURCE_ROOT
'Settle exploration from bound actions and their requested information records.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json

def action_name(value):
    return 'click' if value == 'tap' else value

def task_key(task):
    from regrow.records.control_context import conditions
    return (task.get('control'), registration_kind(task), task.get('name'), conditions(task))

def registration_kind(task):
    return 'parameter' if (task.get('registration_kind') or task.get('task_type')) == 'parameter' else 'function'

def region_task(task):
    return bool(task) and task.get('control') is None

def task_definition(task):
    from regrow.prompts.object_blocks import task_definition as definition
    return definition(registration_kind(task), SOURCE_ROOT)

def exploration_goal(task):
    if task.get('prepares'):
        return task.get('reason') or task.get('name', '')
    definition = task_definition(task)
    return definition['region_goal'] if region_task(task) and registration_kind(task) == 'function' else definition['goal']

def store_action_entry(task, entry, action, attempt, evidence):
    """Persist the original action relation and synchronize its use conditions."""
    from regrow.records.tasks import store_entry
    store_entry(task, entry)
    conditions = entry['conditions']
    if conditions != task.get('conditions', []):
        task_audit(task).setdefault('condition_history', []).append({'conditions': task.get('conditions', []), 'attempt': attempt, 'evidence': evidence})
        task['conditions'] = conditions
        action['conditions'] = list(conditions)

def task_product(task):
    """Required information by question kind, independent of strategy/status."""
    return not missing_product_fields(task)

def missing_product_fields(task):
    kind = registration_kind(task)
    fields = (('findings', 'findings'),) if kind == 'parameter' else (('knowledge', 'knowledge'),)
    return [output for (output, stored) in fields if not task_value(task, stored)]

def registration_requirement(task):
    """Describe the actual missing output, not just an internal task category."""
    if task.get('status') not in ('pending', 'blocked') or task.get('prepares'):
        return {}
    missing = missing_product_fields(task)
    return {'若判断answered，尚需登记': missing} if missing else {}

def entry_schema():
    from regrow.records.task_updates import object_schema
    fields = {'region': {'type': 'string', 'minLength': 1}, 'evidence': {'type': 'string', 'minLength': 1}}
    association = object_schema({**fields, 'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}})
    association['required'] = list(fields)
    return {'anyOf': [{'type': 'null'}, association]}

def register_entry(value, records, actual, attempt, labels=None, *, knowledge):
    """Resolve observed entry semantics against this action's registered surface."""
    if value is None:
        return
    import jsonschema
    jsonschema.validate(value, entry_schema())
    rid = (labels or {}).get(value['region'])
    matches = [rid] if rid in records else [rid for (rid, r) in records.items() if r['name'] == value['region']]
    if len(matches) != 1:
        raise ValueError('入口去向需要本轮已登记的唯一完整区块名')
    target = matches[0]
    action = owned_actions(actual)[attempt]
    changed = {row['region'] for row in action.get('region_changes', []) if row['state'] == 'changed_interactive'}
    before = set(action.get('evidence', {}).get('before_regions', []))
    if target not in action.get('interactive_regions', []) or (target in before and target not in changed) or action.get('result', {}).get('exception') != 'none':
        raise ValueError('入口去向必须对应本次新出现或发生变化的前景区块，可为展示区；仅同时可见不足以证明跳转')
    from regrow.records.control_knowledge import text
    knowledge = text(knowledge)
    if not knowledge or not value['evidence'].strip():
        raise ValueError('入口关联需要已登记用途和前后变化依据')
    entry = {**value, 'region': target, 'attempt': attempt, 'meaning': knowledge, 'conditions': list(dict.fromkeys(action.get('conditions', []) + value.get('conditions', [])))}
    return entry

def register_destinations(values, records, region_refs, controls, actual, attempt, call):
    """Resolve targets after object materialization, bind to the actual operation."""
    if not values:
        return
    jsonschema = __import__('jsonschema')
    jsonschema.validate(values, destination_schema())
    from regrow.records.object_store import observation_history
    action = owned_actions(actual)[attempt]
    if action.get('delivery') != 'executed_receipt_zero' or action.get('association', {}).get('status') == 'unconfirmed':
        raise ValueError('目标关联缺少已确认的实际动作来源')
    source_control = action.get('control')
    record = owned_controls(actual).get(source_control) if source_control else actual
    if record is None:
        raise ValueError('实际操作对象未登记，不能保存目标关联')
    from regrow.records.tasks import store_object_entry
    from regrow.records.control_routes import update_conditions
    update_conditions(record, values, action, call)
    for value in values:
        if 'index' in value:
            continue
        index = value['region_index']
        if not 0 <= index < len(region_refs):
            raise ValueError('jump_to.region_index必须引用本次regions')
        target = region_refs[index]
        entry = register_entry({'region': records[target]['name'], 'evidence': value['description'],
                                'conditions': value.get('conditions', [])},
                               records, actual, attempt, {records[target]['name']: target},
                               knowledge=value['description'])
        if 'control_index' in value:
            ci = value['control_index']
            if not 0 <= ci < len(controls) or controls[ci]['region_index'] != index:
                raise ValueError('目标控件必须属于所给目标区块')
            matches = [cid for cid,c in owned_controls(records[target]).items()
                       if any(o.get('evidence', {}).get('source_call') == call and
                              o['evidence'].get('source_field') == f'/controls/{ci}'
                              for o in observation_history(c))]
            if len(matches) != 1:
                raise ValueError('目标控件尚未唯一登记')
            entry['control'] = matches[0]
        entry['source'] = {**action.get('evidence', {}), 'attempt': attempt, 'basis': 'explored'}
        store_object_entry(record, entry)

def destination_schema():
    observed = {'type': 'object', 'properties': {
        'region_index': {'type': 'integer', 'minimum': 0},
        'control_index': {'type': 'integer', 'minimum': 0,
                          'description': '本次controls数组中的位置；不是历史控件index。区块目标省略。'},
        'description': {'type': 'string', 'minLength': 1},
        'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}},
        'required': ['region_index', 'description', 'conditions'], 'additionalProperties': False}
    existing = {'type': 'object', 'properties': {
        'index': {'type': 'integer', 'minimum': 0},
        'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}},
        'required': ['index', 'conditions'], 'additionalProperties': False}
    return {'type': 'array', 'items': {'anyOf': [observed, existing]}}


def registered_result(task, action, attempt):
    """Use the question's accepted object products, not copies on the action."""
    from regrow.records.control_context import same_use
    from regrow.records.tasks import source_attempts
    if not same_use(task, action):
        return False
    kind = registration_kind(task)
    if kind == 'parameter':
        return any((attempt in source_attempts(source) for fact in task_value(task, 'findings', {}).values() for source in fact.get('sources', [fact.get('source', {})])))
    return bool(task_value(task, 'knowledge') and action.get('result', {}).get('description'))

def completion_target(owner, task):
    target = dict(task.get('completion_action') or {'region': owner['id'], 'control': task.get('control')})
    target.pop('action', None)
    if target.get('control') and hasattr(owner, 'store'):
        matches = [rid for (rid, r) in owner.store.items() if target['control'] in owned_controls(r)]
        if len(matches) == 1:
            target['region'] = matches[0]
    return target

def refresh_movement(owner, task, state):
    """A new viewport proposal reuses a movement task, excluding earlier attempts."""
    observation = (state or {}).get('observation') or {}
    if not region_task(task) or task.get('status') != 'done' or (not observation.get('id')) or (task.get('navigation_observation') == observation['id']):
        return
    task_audit(task).setdefault('navigation_history', []).append({'observation': task.get('navigation_observation'), 'completion_basis': task_value(task, 'completion_basis')})
    target = dict(completion_target(owner, task))
    target['excluded_attempts'] = list(owned_actions(owner))
    task.update(status='pending', navigation_observation=observation['id'], completion_action=target)
    task_audit(task).pop('completion_basis', None)

def task_object_context(records, binding):
    owner = records[binding.get('task_region', binding['region_ref'])]
    task = owned_tasks(owner)[binding['task_name']]
    target = completion_target(owner, task)
    region = records[target['region']]
    return {'任务区块': owner['name'], '待执行区块': region['name'], '待执行控件': owned_controls(region).get(target['control'], {}).get('name', '区块本身'), '所需登记': registration_kind(task), '适用条件': task.get('conditions', []), '说明': ('这是前置准备，按已知准备目标推进；条件是否满足由本次观察的dependency_updates登记，不因入口点击而结束。' if task.get('prepares') else '') + '明确提交continue/answered/defer和本轮依据；框架核验实际绑定、执行或观察来源及所需产物，再登记判断。answered回答探索问题，不等于业务操作成功。'}

def recorded_match(region, aid, action, target, receipt=None):
    """A dispatch intention or an unresolved visual candidate is not execution."""
    if target['control'] is None and region['id'] != target['region'] or action.get('control') != target['control'] or aid in target.get('excluded_attempts', []) or (action.get('delivery') != 'executed_receipt_zero') or (action.get('association', {}).get('status') == 'unconfirmed') or (action.get('result', {}).get('exception') == 'unexpected_exit') or (not action.get('result', {}).get('description')):
        return False
    operation = action_name(action.get('operation'))
    if target['control'] is None and operation not in ('scroll', 'back', 'wait', 'key_press', 'hotkey'):
        return False
    if receipt is not None:
        if receipt.get('exit_code') != 0:
            return False
        if not any((action_name(s.get('action')) == operation for s in receipt.get('executed_steps', []))):
            return False
    if operation == 'input_text':
        delivered = (receipt or action).get('text_delivered')
        if delivered is not True:
            return False
    return True

def settle_task(owner, binding, reply, attempt, records=None, *, receipt=None, labels=None, candidates=None, explicit=False):
    from copy import deepcopy
    from regrow.records import task_updates as updates
    records = records or {owner['id']: owner}
    if isinstance(reply.get('task_update'), list):
        return updates.apply(owner, binding, reply, attempt, records, receipt=receipt, labels=labels, candidates=candidates, settle=settle_task)
    name = binding.get('task_name')
    task = owned_tasks(owner).get(name)
    if task is None:
        return
    row = reply.get('task_update') or {}
    updates.validate(row, task)
    actual = records[binding['region_ref']]
    action = owned_actions(actual)[attempt]
    owns_action = not binding.get('answered_related_task') and (not binding.get('related_assessment'))
    if owns_action:
        action.setdefault('task', owner['id'] + '/' + name)
    matched = recorded_match(actual, attempt, action, completion_target(owner, task), receipt)
    if binding.get('answered_related_task'):
        matched = True
    source = {'basis': 'explored' if matched else 'observation_only', 'source_call': action.get('evidence', {}).get('result_call'), 'observation': action.get('evidence', {}).get('after_observation'), 'region': actual['id'], 'control': action.get('control'), **({'attempt': attempt} if matched else {'source_attempt': attempt})}
    if matched:
        if owns_action and 'conditions' in task:
            action['conditions'] = list(task['conditions'])
        source.update(operation=action.get('operation'), registration_kind=registration_kind(task))
    new_knowledge = bool(row.get('knowledge'))
    if new_knowledge:
        updates.store_knowledge(task, row['knowledge'], source)
    if row.get('findings'):
        if not matched and (not updates.observed_control(owner, task, {'interactive_regions': action.get('interactive_regions', []), 'observation': {'id': source['observation'], 'foreground': action.get('result', {})}})):
            raise ValueError('原参数事实需有原控件的真实语义观察；准备动作本身不是原参数的执行')
        (valid, gaps) = partition_findings(row['findings'], task)
        if gaps or not valid:
            raise ValueError('任务参数事实存在具体缺口，不能据不合法事实结算')
        store_findings(task, valid, {'task_region': owner['id'], 'task': name, **source})
    observed = updates.observed_control(owner, task, {'interactive_regions': action.get('interactive_regions', []), 'observation': {'id': source['observation'], 'foreground': action.get('result', {})}})
    if new_knowledge and (not matched) and (not observed):
        raise ValueError('准备动作的效果不能直接变成原任务知识；新增事实需原控件的真实语义观察')
    if action.get('result', {}).get('exception') == 'unexpected_exit':
        task['blocker'] = {'condition': 'review_required', 'exception': 'unexpected_exit', 'attempt': attempt, 'reason': '实际应用异常退出尚未解决'}
    if task.get('prepares'):
        product = updates.preparation_product(task, row, records, source)
    else:
        product = task_product(task)
    suggestion = (task_value(task, 'latest_update') or {}).get('next_action')
    consumed = bool(owns_action and suggestion
                    and action_name(suggestion['action']) == action_name(action.get('operation'))
                    and recorded_match(actual, attempt, action, suggestion, receipt))
    updates.decide(task, row, source, product_complete=product, records=records,
                   labels=labels, consumed_suggestion=consumed)

def reconcile(records):
    """Retain unresolved real action ownership without guessing completion."""
    changed = False
    for owner in records.values():
        for (name, task) in owned_tasks(owner).items():
            if task.get('status') != 'pending' or task.get('equivalent_to') or task.get('blocker') or task.get('prepares'):
                continue
            target = completion_target(owner, task)
            region = records.get(target['region'], {})
            for aid in reversed(task_value(task, 'attempts', [])):
                attempts = [owned_actions(r)[aid] for r in records.values() if aid in owned_actions(r)]
                if len(attempts) != 1:
                    continue
                action = attempts[0]
                association = action.get('association', {})
                from regrow.records.action_evidence import assessments
                claimed_answer = any((row.get('decision') == 'answered' for row in assessments(task, aid)))
                if aid in target.get('excluded_attempts', []) or action.get('delivery') != 'executed_receipt_zero' or action.get('result', {}).get('exception') != 'none' or (not action.get('result', {}).get('description')) or (association.get('status') != 'unconfirmed') or (not (claimed_answer or any((c.get('region') == target['region'] and c.get('control') == target['control'] for c in association.get('candidates', []))))):
                    continue
                reason = '已有实际投递及观察，但目标控件归属未确认；保留原尝试，需显式核对关联后再推进原任务'
                task_audit(task)['result_evidence'] = action.get('result', {}).get('description', '')
                task.update(status='blocked', blocker={'condition': 'review_required', 'reason': reason, 'attempt': aid}, deferral={'reason': reason, 'retry_when': 'explicit_task_ownership_review', 'attempt': aid})
                changed = True
                break
    return changed

def reconcile_run(run):
    from regrow.traversal import discovery_step as _discovery_step
    discovery = _discovery_step
    (_, records, _) = _record_load(run)
    if not reconcile(records):
        return False

    def mutate(records, state, *_):
        reconcile(records)
        active = state.get('active_task') or {}
        if owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {}).get('status') in ('done', 'blocked'):
            state.pop('active_task', None)
    import uuid
    _record_publish(run, 'bound-actions-' + uuid.uuid4().hex, mutate)
    return True

def partition_findings(findings, task=None):
    """Separate supplementary facts; never relax identity or action validation."""
    import jsonschema
    schema = json.loads((SOURCE_ROOT / 'regrow/prompts/输出格式/参数发现.schema').read_text())
    accepted = []
    gaps = []
    if not isinstance(findings, list):
        return ([], [{'reported': findings, 'reason': 'parameter findings must be an array'}])
    for fact in findings:
        try:
            jsonschema.validate(fact, schema)
            if not fact['name'].strip() or not fact['description'].strip():
                raise ValueError('parameter name or description missing')
        except (jsonschema.ValidationError, ValueError) as error:
            gaps.append({'reported': fact, 'reason': error.message if isinstance(error, jsonschema.ValidationError) else str(error)})
            continue
        accepted.append(fact)
    return (accepted, gaps)

def validation_reply(reply, task=None):
    from copy import deepcopy
    result = deepcopy(reply)
    for field in ('task_update', 'task_result'):
        value = result.get(field)
        for row in value if isinstance(value, list) else [value]:
            if isinstance(row, dict) and 'findings' in row:
                row['findings'] = partition_findings(row['findings'], task)[0]
    return result

def store_findings(task, findings, source):
    from regrow.records.tasks import store_findings as store
    (accepted, gaps) = partition_findings(findings, task)
    for gap in gaps:
        item = {**gap, 'source': dict(source)}
        if item not in task.setdefault('finding_gaps', []):
            task['finding_gaps'].append(item)
    if accepted:
        store(task, accepted, source)
