from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.paths import SOURCE_ROOT
'Settle exploration from bound actions and their requested information records.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from regrow.records.action_evidence import has_observed_result
import json

def action_name(value):
    return 'click' if value == 'tap' else value

def task_key(task):
    from regrow.records.control_context import conditions
    return (task.get('control'), registration_kind(task), task.get('name'), conditions(task))

def registration_kind(task):
    if 'target' in task:
        return None
    kind = task.get('registration_kind') or task.get('task_type')
    return kind if kind in ('parameter', 'region_content') else 'function'

def region_task(task):
    return bool(task) and task.get('control') is None

def task_definition(task):
    if 'target' in task:
        return {'label': task['target'], 'goal': task['target'], 'region_goal': task['target']}
    from regrow.records.task_goals import legacy_definition
    return legacy_definition(registration_kind(task))

def completion_condition(task):
    """Read this task's fixed endpoint without following historical projections."""
    return task.get('target', task.get('completion_condition', ''))


def exploration_goal(task):
    condition = completion_condition(task)
    if 'target' in task:
        return condition
    if condition and not task.get('prepares'):
        return condition + ('\n本次理由：' + task['reason'] if registration_kind(task) == 'region_content' and task.get('reason') else '')
    if task.get('prepares'):
        goal = task.get('reason') or task.get('name', '')
    else:
        definition = task_definition(task)
        goal = definition['region_goal'] if region_task(task) and registration_kind(task) == 'function' else definition['goal']
        if registration_kind(task) == 'region_content' and task.get('reason'):
            goal += '\n本次理由：' + task['reason']
    return goal + ('\n本任务结算条件：' + condition if condition else '')

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

def has_source_call(source):
    if not isinstance(source, dict):
        return False
    if source.get('source_call'):
        return True
    return any(has_source_call(child) for child in source.get('sources', []))


def missing_product_fields(task):
    if 'target' in task:
        return []
    kind = registration_kind(task)
    if kind == 'region_content':
        # The model's explicit task decision and reason record the coverage
        # judgement. No fabricated usage knowledge or scroll-count gate.
        return []
    if kind == 'parameter':
        return [] if task_value(task, 'knowledge') and has_source_call(
            task_value(task, 'knowledge_source')) else ['目标控件有来源的使用知识']
    fields = (('knowledge', '目标对象的用途知识'),)
    return [description for (stored, description) in fields if not task_value(task, stored)]

def registration_requirement(task):
    """Describe the actual missing output, not just an internal task category."""
    if task.get('status') not in ('pending', 'blocked') or task.get('prepares'):
        return {}
    missing = missing_product_fields(task)
    return {'若判断done，尚需登记': missing} if missing else {}

def entry_schema():
    from regrow.records.task_updates import object_schema
    fields = {'region': {'type': 'string', 'minLength': 1}, 'evidence': {'type': 'string', 'minLength': 1}}
    association = object_schema({**fields, 'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}})
    association['required'] = list(fields)
    return {'anyOf': [{'type': 'null'}, association]}

def register_entry(value, records, actual, attempt, labels=None, *, knowledge, reported_destination=False):
    """Resolve observed entry semantics against this action's registered surface."""
    if value is None:
        return
    import jsonschema
    from regrow.records.diagnostics import reject
    jsonschema.validate(value, entry_schema())
    rid = (labels or {}).get(value['region'])
    matches = [rid] if rid in records else [rid for (rid, r) in records.items() if r['name'] == value['region']]
    if len(matches) != 1:
        reject('destination_reference', value['region'],
               {'填写的目标': value['region'], '对应区块': [records[r]['name'] for r in matches]},
               '访问目标对应本轮已登记的唯一完整区块名', field='访问目标区块',
               reason='填写的访问目标未能唯一对应一个已登记区块。')
    target = matches[0]
    action = owned_actions(actual)[attempt]
    changed = {row['region'] for row in action.get('region_changes', []) if row['state'] == 'changed_interactive'}
    before = set(action.get('evidence', {}).get('before_regions', []))
    reached = (reported_destination or target in action['observed_destinations']) if 'observed_destinations' in action else (target not in before or target in changed)
    target_name = records[target]['name']
    if target not in action.get('interactive_regions', []):
        reject('destination_not_current', target_name,
               {'声明到达的目标': target_name, '当前前景区块': [records.get(r, {}).get('name', r)
                for r in action.get('interactive_regions', [])]},
               '声明为本次到达的目标须包含在动作后的当前前景区块中', field='访问目标与当前前景区块',
               reason='你声明本次到达“' + target_name + '”，但当前前景区块中没有包含它。',
               repair='根据动作后图核对访问目标和当前前景区块的引用。')
    if not reached:
        reject('destination_not_reached', target_name,
               {'目标': target_name, '动作前已有区块': [records.get(r, {}).get('name', r) for r in action.get('evidence', {}).get('before_regions', [])],
                '本次确认到达的区块': [records.get(r, {}).get('name', r) for r in action.get('observed_destinations', [])]},
               '访问关系须有本次实际动作到达目标的依据；前后都可见本身不表示到达', field='本次到达依据',
               reason='目标区块可见，但本次动作尚未确认到达该目标。')
    if action.get('result', {}).get('exception') != 'none':
        reject('destination_action_exception', target_name, action.get('result', {}).get('exception'),
               '无异常的本次动作到达结果', field='动作结果',
               reason='本次动作结果仍有异常，不能登记为无异常到达目标。')
    from regrow.records.control_knowledge import text
    knowledge = text(knowledge)
    if not value['evidence'].strip():
        reject('destination_evidence', target_name, value['evidence'],
               '本次实际动作及后图来源', field='访问依据', reason='访问关联的依据为空。')
    entry = {**value, 'region': target, 'attempt': attempt, 'meaning': knowledge, 'conditions': list(dict.fromkeys(action.get('conditions', []) + value.get('conditions', [])))}
    return entry

def register_destinations(values, records, region_refs, controls, actual, attempt, call, *, regions=()):
    """Resolve targets after object materialization, bind to the actual operation."""
    if not values:
        return
    jsonschema = __import__('jsonschema')
    from regrow.records.diagnostics import reject, Rejected
    # Old saved submissions retain their positional contract; new requests
    # carry identities/names directly and never need observation-only rows.
    jsonschema.validate(values, {'type': 'array', 'items': {'anyOf': [
        destination_schema()['items'], _saved_destination_schema()['items']]}})
    from regrow.records.destination_refs import resolve
    action = owned_actions(actual)[attempt]
    if not has_observed_result(action) or action.get('association', {}).get('status') == 'unconfirmed':
        reject('destination_action_source', actual['name'],
               {'动作来源关联': action.get('association', {}).get('status'),
                '投递记录': action.get('delivery'), '已有动作后观察': bool(action.get('evidence', {}).get('after_observation'))},
               '已确认的本次实际动作来源与结果观察', field='访问关联的动作来源',
               reason='本次动作来源或结果观察尚未确认，不能据此保存访问目标。')
    source_control = action.get('control')
    record = owned_controls(actual).get(source_control) if source_control else actual
    if record is None:
        reject('destination_source_control', actual['name'], source_control,
               '已登记的实际操作控件', field='实际操作控件', reason='动作来源控件没有对应登记对象。')
    from regrow.records.tasks import store_object_entry
    for position, value in enumerate(values):
        target, cid = resolve(value, records, region_refs, controls, call, position, regions=regions)
        try:
            entry = register_entry({'region': records[target]['name'], 'evidence': action['evidence']['after_observation'],
                                    'conditions': value.get('conditions', [])},
                                   records, actual, attempt, {records[target]['name']: target},
                                   knowledge='', reported_destination=True)
        except Rejected as error:
            for item in error.report['errors']:
                item['path'] = f'/jump_to/{position}/' + ('region_index' if 'region_index' in value else 'region')
                if item['code'] == 'destination_not_current':
                    item['related_paths'] = ['/current_regions']
            raise
        if cid is not None:
            entry['control'] = cid
        entry['source'] = {**action.get('evidence', {}), 'attempt': attempt, 'basis': 'explored'}
        store_object_entry(record, entry)
        if 'observed_destinations' in action and target not in action['observed_destinations']:
            action['observed_destinations'].append(target)

def destination_schema():
    observed = {'type': 'object', 'properties': {
        'region': {'type': 'string', 'minLength': 1},
        'control': {'type': 'string', 'minLength': 1},
        'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}},
        'required': ['region'], 'additionalProperties': False}
    return {'type': 'array', 'items': observed}


def _saved_destination_schema():
    observed = {'type': 'object', 'properties': {
        'region_index': {'type': 'integer', 'minimum': 0},
        'control_index': {'type': 'integer', 'minimum': 0,
                          'description': '本次controls数组中的位置；不是控件ID。区块目标省略。'},
        'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}},
        'required': ['region_index'], 'additionalProperties': False}
    return {'type': 'array', 'items': observed}


def registered_result(task, action, attempt):
    """Use the question's accepted object products, not copies on the action."""
    from regrow.records.control_context import same_use
    if not same_use(task, action):
        return False
    kind = registration_kind(task)
    if 'target' in task:
        return has_observed_result(action)
    if kind == 'parameter':
        return not missing_product_fields(task)
    return bool(task_value(task, 'knowledge') and has_observed_result(action))

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
    return {'任务区块': owner['name'], '待执行区块': region['name'], '待执行控件': owned_controls(region).get(target['control'], {}).get('name', '区块本身'), '所需登记': registration_kind(task), '适用条件': task.get('conditions', []), '说明': '明确提交pending/done/blocked；框架核验实际绑定、执行或观察来源及所需产物，再登记判断。done回答探索问题，不等于业务操作成功。'}

def recorded_match(region, aid, action, target, receipt=None):
    """A dispatch intention or an unresolved visual candidate is not execution."""
    if target['control'] is None and region['id'] != target['region'] or action.get('control') != target['control'] or aid in target.get('excluded_attempts', []) or not has_observed_result(action) or (action.get('association', {}).get('status') == 'unconfirmed') or (action.get('result', {}).get('exception') == 'unexpected_exit'):
        return False
    operation = action_name(action.get('operation'))
    from regrow.records.function_evidence import region_action
    if target['control'] is None and not region_action({**action, 'operation': operation}):
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
    owns_action = not binding.get('related_assessment')
    if owns_action:
        action.setdefault('task', owner['id'] + '/' + name)
    matched = recorded_match(actual, attempt, action, completion_target(owner, task), receipt)
    source = {'basis': 'explored' if matched else 'observation_only', 'source_call': action.get('evidence', {}).get('result_call'), 'observation': action.get('evidence', {}).get('after_observation'), 'region': actual['id'], 'control': action.get('control'), **({'attempt': attempt} if matched else {'source_attempt': attempt})}
    if matched:
        if owns_action and 'conditions' in task:
            action['conditions'] = list(task['conditions'])
        source.update(operation=action.get('operation'), registration_kind=registration_kind(task))
    if action.get('result', {}).get('exception') == 'unexpected_exit':
        task['blocker'] = {'condition': 'review_required', 'exception': 'unexpected_exit', 'attempt': attempt, 'reason': '实际应用异常退出尚未解决'}
    product = task_product(task)
    updates.decide(task, row, source, product_complete=product, records=records,
                   labels=labels)

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
                claimed_answer = any((row.get('state') == 'done' for row in assessments(task, aid)))
                if aid in target.get('excluded_attempts', []) or not has_observed_result(action) or action.get('result', {}).get('exception') != 'none' or (association.get('status') != 'unconfirmed') or (not (claimed_answer or any((c.get('region') == target['region'] and c.get('control') == target['control'] for c in association.get('candidates', []))))):
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

def store_findings(task, findings, source):
    from regrow.records.tasks import store_findings as store
    (accepted, gaps) = partition_findings(findings, task)
    for gap in gaps:
        item = {**gap, 'source': dict(source)}
        if item not in task.setdefault('finding_gaps', []):
            task['finding_gaps'].append(item)
    if accepted:
        store(task, accepted, source)
