from regrow.paths import SOURCE_ROOT
'One task-update interface for the active goal and explicitly answered questions.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records.object_store import find_control
from copy import deepcopy
import json
from pathlib import Path

def object_schema(fields):
    return {'type': 'object', 'properties': {k: deepcopy(v) for (k, v) in fields.items()}, 'required': list(fields), 'additionalProperties': False}

def schema(kinds=None, refs=None):
    """Optional increments stay optional; local semantics validate decisions."""
    from regrow.records.task_settlement import entry_schema
    string = {'type': 'string', 'minLength': 1}
    fields = {'task': {'type': 'string', **({'enum': list(refs)} if refs else {})}, 'decision': {'type': 'string', 'enum': ['continue', 'answered', 'defer']}, 'reason': string, 'remaining_question': string, 'retry_when': string, 'next_action': {'anyOf': [{'type': 'null'}, object_schema({'region': string, 'control': {'type': 'string'}, 'action': {'type': 'string', 'enum': ['click', 'double_click', 'long_press', 'input_text', 'scroll', 'key_press', 'hotkey', 'hover', 'right_click', 'drag', 'back', 'wait']}, 'reason': string})]}}
    result = object_schema(fields)
    result['required'] = ['task', 'decision']
    result['properties']['reason']['description'] = '按需补充判断理由；不重复动作结果或已有知识。'
    result['properties']['remaining_question']['description'] = 'decision为continue或defer时必填：原问题尚未回答的具体部分；answered时不填写。'
    result['properties']['retry_when']['description'] = 'decision为defer时必填：何种条件满足后可重新推进；其他decision不填写。'
    result['allOf'] = [
        {'if': {'properties': {'decision': {'enum': ['continue', 'defer']}}, 'required': ['decision']},
         'then': {'required': ['remaining_question']}},
        {'if': {'properties': {'decision': {'const': 'defer'}}, 'required': ['decision']},
         'then': {'required': ['retry_when']}},
    ]
    return result

def validate(row, task, ref=None):
    import jsonschema
    from regrow.records.task_settlement import registration_kind
    jsonschema.validate(row, schema([registration_kind(task)], [ref] if ref else None))
    if 'reason' in row and not row['reason'].strip():
        raise ValueError('任务判断需要具体依据')
    needed = (['remaining_question'] if row['decision'] != 'answered' else [])
    if row['decision'] == 'defer':
        needed.append('retry_when')
    missing = [key for key in needed if not row.get(key, '').strip()]
    if missing:
        raise ValueError('任务 ' + str(row.get('task', ref)) + ' 的字段不能为空：' + '、'.join(missing))
    if row['decision'] == 'answered' and any((k in row for k in ('remaining_question', 'retry_when'))):
        raise ValueError('answered不提交活动缺口、重试条件或下一步建议')
    if row['decision'] != 'defer' and 'retry_when' in row:
        raise ValueError('retry_when只属于defer判断')
    if row['decision'] != 'continue' and row.get('next_action') is not None:
        raise ValueError('next_action只属于continue判断')

def resolve_suggestion(records, value, labels=None):
    if value is None:
        return None
    rid = (labels or {}).get(value['region'])
    refs = [rid] if rid in records else [r for (r, v) in records.items() if v['name'] == value['region'] or r == value['region']]
    if len(refs) != 1:
        raise ValueError('后续建议需引用本轮唯一已登记区块')
    owner = records[refs[0]]
    cids = [cid for (cid, c) in owned_controls(owner).items() if c['name'] == value['control'] or cid == value['control']]
    if not value['control'] and value['action'] in ('scroll', 'back', 'wait', 'key_press', 'hotkey'):
        cids = [None]
    if len(cids) != 1:
        raise ValueError('后续建议目标未登记或不唯一；可不填建议，保留具体定位问题')
    return {**deepcopy(value), 'region': refs[0], 'control': cids[0]}

def hard_block(task):
    blocker = task.get('blocker', {})
    return bool(blocker.get('exception') or blocker.get('condition') not in (None, 'review_required') or (task.get('prerequisite') and (not task['prerequisite'].get('satisfied'))) or (task.get('deferral', {}).get('retry_when') == 'explicit_task_ownership_review'))

def decide(task, row, basis, *, product_complete, records, labels=None, consumed_suggestion=False):
    """Publish an explicit assessment; facts and real execution blockers survive."""
    validate(row, task)
    decision = row['decision']
    blocked = hard_block(task)
    if decision == 'answered' and blocked:
        raise ValueError('任务 ' + row['task'] + ' 仍有已记录的真实执行、身份或前提阻塞；保留已有事实并明确继续/暂挂')
    if decision == 'answered' and (not product_complete):
        from regrow.records.task_settlement import missing_product_fields
        missing = '准备目标的dependency_updates确认' if task.get('prepares') else '、'.join(missing_product_fields(task)) or '目标对象的适用知识'
        raise ValueError('任务 ' + row['task'] + ' 尚不能结算，缺少：' + missing + '。请依据已提供的观察登记所需答案；reason中的说明不会自动写入这些产物。')
    previous = task_value(task, 'latest_update')
    if decision != 'continue':
        suggestion = None
    elif 'next_action' in row:
        suggestion = resolve_suggestion(records, row['next_action'], labels)
    elif consumed_suggestion:
        suggestion = None
    else:
        suggestion = deepcopy((previous or {}).get('next_action'))
    if previous:
        task_audit(task).setdefault('update_history', []).append(deepcopy(previous))
    task_audit(task)['latest_update'] = {**{k: deepcopy(row[k]) for k in ('decision', 'reason', 'remaining_question', 'retry_when') if k in row}, 'next_action': suggestion, 'source': deepcopy(basis)}
    if row.get('reason'):
        task_audit(task)['result_evidence'] = row['reason']
    else:
        task_audit(task).pop('result_evidence', None)
    if not blocked:
        for key in ('blocker', 'deferral'):
            if task.get(key):
                task_audit(task).setdefault(key + '_history', []).append({**task.pop(key), 'resolved_by': deepcopy(basis)})
        task['status'] = {'continue': 'pending', 'answered': 'done', 'defer': 'blocked'}[decision]
    if decision == 'defer' and (not blocked):
        task['status'] = 'blocked'
        task['deferral'] = {**({'reason': row['reason']} if row.get('reason') else {}), 'retry_when': row['retry_when'], 'remaining_question': row['remaining_question'], **deepcopy(basis)}
    if decision == 'answered':
        task_audit(task)['completion_basis'] = {'rule': 'explicit_question_answer_registered', **deepcopy(basis)}
    return task['status']

def store_increment(owner, task, name, row, records, state, basis, *, observed=False, labels=None):
    """An observation answers a question without acquiring another action's owner."""
    from regrow.records.task_settlement import registration_kind
    validate(row, task, reference(owner['id'], name))
    from regrow.records.task_settlement import task_product
    product = task_product(task)
    if task.get('prepares'):
        product = preparation_product(task, row, records, basis)
    return decide(task, row, basis, product_complete=product, records=records, labels=labels)

def store_knowledge(task, knowledge, basis):
    from regrow.records.tasks import store_knowledge as store
    store(task, knowledge, basis)

def current_frame(run, request, owner, task, state):
    """Read the sent frame for the still-bound request, without reusing old semantics."""
    from regrow.prompts.frame_context import primary
    from regrow.records.task_settlement import completion_target
    observation = (state or {}).get('observation') or {}
    if not observation.get('id') or request.get('source', {}).get('observation') != observation['id']:
        return None
    if completion_target(owner, task)['region'] not in state.get('interactive_regions', []) or observation.get('foreground', {}).get('exception', 'none') != 'none':
        return None
    frame = primary(request)
    path = Path(run) / frame if frame else None
    return path.resolve() if path and path.is_file() else None

def answer_evidence(run, request, owner, task, state):
    """Resolve admitted evidence for stable answers, without declaring an old frame current."""
    source = request.get('source', {})
    name = source.get('task_name')
    expected = reference(owner['id'], name) if name else None
    same_task = getattr(task, 'ref', None) == expected if hasattr(task, 'ref') else name in owned_tasks(owner) and owned_tasks(owner)[name] is task
    if source.get('task_region') != owner['id'] or not same_task:
        return None
    frame = current_frame(run, request, owner, task, state)
    current = {'basis':'observation_only','observation':state['observation']['id'],
               'source_image':str(frame)} if frame else None
    from regrow.records.snapshots import load, read
    from regrow.records.task_settlement import completion_target
    # Retain admitted history alongside the current image, not as its replacement.
    if task.get('prepares'):
        return current
    history=request.get('page_context', {}).get('history', {})
    if not history.get('events'):
        return current
    (_, records, _) = load(run)
    target=completion_target(owner, task)
    if target.get('control') is None:
        return current
    invalid={row.get('invalidated_attempt') for row in task_value(task,'ownership_history',[])} | set(task.get('completion_action',{}).get('excluded_attempts',[]))
    supplied=request.get('user_prompt','')
    sources=[];direct=False
    for aid,event in history.get('events',{}).items():
        region=records.get(event.get('region'),{})
        action=owned_actions(region).get(aid,{})
        description=(action.get('result') or {}).get('description')
        if aid in invalid or event.get('缺口') or event.get('归属纠正') or not description:
            continue
        if aid+'：' not in supplied or description not in supplied or event.get('观察') != description:
            continue
        if event.get('control') != action.get('control') or not find_control(region, action.get('control')):
            continue
        if event.get('动作') != action.get('operation') or action.get('association',{}).get('status') == 'unconfirmed':
            continue
        if action.get('delivery') != 'executed_receipt_zero' or event.get('执行') != action.get('delivery'):
            continue
        if action.get('result',{}).get('exception') not in (None,'','none'):
            continue
        if not set(task.get('conditions',[])).issubset(set(action.get('conditions',[]))):
            continue
        evidence=action.get('evidence',{})
        receipt=Path(run)/'action_attempts'/aid/'receipt.json'
        frame=Path(run)/'action_attempts'/aid/'after.png'
        result_call=evidence.get('result_call')
        if not receipt.is_file() or read(receipt).get('exit_code') != 0 or not frame.is_file():
            continue
        if not result_call or not (Path(run)/'calls'/result_call/'response.json').is_file() or not evidence.get('after_observation'):
            continue
        direct |= event['region']==target['region'] and (target.get('control') is None or action.get('control')==target['control'])
        sources.append({'basis':'explored','region':event['region'],'control':action.get('control'),
                        'attempt':aid,'source_call':result_call,'observation':evidence['after_observation']})
    # At least one admitted observation must concern this task's actual target;
    # related actions can support interpretation but do not become this task's executions.
    return {**(current or {'basis':'observation_only'}),'sources':sources} if direct else current


def preparation_product(task, row, records, basis):
    goal = task.get('prepares', {})
    parent = owned_tasks(records.get(goal.get('region'), {})).get(goal.get('task'), {})
    ready = parent.get('prerequisite', {}).get('satisfied') or {}
    if ready.get('source_call') == basis.get('source_call') and ready and (row['decision'] != 'answered'):
        raise ValueError('准备任务判断与本次ready=true前提观察冲突')
    return bool(ready.get('source_call') and ready.get('evidence'))

def observed_control(owner, task, state):
    from regrow.records.task_settlement import completion_target
    from regrow.records.observations import frame_observation
    observation = (state or {}).get('observation') or {}
    target = completion_target(owner, task)
    control = (owner if target['control'] is None else find_control(owner, target['control'])) or {}
    return bool(observation.get('id') and target['region'] in state.get('interactive_regions', []) and (observation.get('foreground', {}).get('exception', 'none') == 'none') and frame_observation(control, observation=observation['id']))

def reference(region, name):
    return region + '/' + name

def related_to_action(task, region, binding):
    """Only unfinished local questions on the actual operated control."""
    return (region == binding['region_ref'] and binding.get('control_ref') is not None
            and task.get('control') == binding['control_ref']
            and task.get('status') in ('pending', 'blocked')
            and not any(task.get(key) for key in ('prepares', 'prerequisite', 'equivalent_to',
                                                 'shared_task_ref', 'coverage_exemption'))
            and not hard_block(task))


def catalog(records, binding):
    from regrow.records.tasks import describe
    'Keep task ownership; disclose local goals, not another pending ledger.'
    from regrow.records.task_settlement import registration_kind, exploration_goal
    rows = []
    provided_knowledge = set()
    scope = {binding['region_ref'], binding.get('task_region', binding['region_ref'])}
    for rid in records:
        region = records[rid]
        for (name, task) in owned_tasks(region).items():
            current = rid == binding.get('task_region', binding['region_ref']) and name == binding.get('task_name')
            related = related_to_action(task, rid, binding)
            goal = task.get('prepares', {})
            preparation = bool(goal.get('region') in scope and task.get('status') in ('pending', 'blocked'))
            if not current and (not related) and (not preparation):
                continue
            row = {'task': reference(rid, name), 'region': rid, 'name': name, 'control': task.get('control'), 'control_name': (find_control(region, task.get('control')) or {}).get('name', '区块本身'), 'status': task.get('status'), 'task_type': registration_kind(task), 'conditions': task.get('conditions', [])}
            if current:
                from regrow.records.history_context import question_state
                row.update(question_state(task))
            identity = task.get('control') or ('region', rid)
            if identity not in provided_knowledge:
                from regrow.records.control_knowledge import card
                if task.get('control'):
                    row['当前控件知识'] = card(find_control(region, task.get('control')) or {})
                elif task_value(task, 'knowledge'):
                    row['目标已知知识'] = task_value(task, 'knowledge')
                provided_knowledge.add(identity)
            if task.get('status') in ('pending', 'blocked'):
                row.update(reason=exploration_goal(task), blocker=task.get('blocker', {}), prerequisite=describe(task.get('prerequisite')))
                from regrow.records.task_settlement import registration_requirement
                row.update(registration_requirement(task))
            if task.get('prepares'):
                goal = task['prepares']
                row['prepares'] = goal
                row['prerequisite_observation'] = describe(owned_tasks(records.get(goal['region'], {})).get(goal['task'], {}).get('prerequisite'))
            rows.append(row)
    return rows

def current(reply, binding):
    value = reply.get('task_update')
    if isinstance(value, list):
        ref = reference(binding.get('task_region', binding['region_ref']), binding.get('task_name', ''))
        return next((row for row in value if row.get('task') == ref), {})
    return value or reply.get('task_result') or {}

def apply(owner, binding, reply, attempt, records, *, receipt, labels, candidates, settle):
    """Called within the normal update transaction after real identity registration."""
    from regrow.records.task_settlement import completion_target
    from regrow.records.task_settlement import recorded_match
    rows = reply['task_update']
    allowed = {row['task']: row for row in candidates or []}
    selected = {}
    active = binding.get('task_update_ref') or reference(owner['id'], binding.get('task_name', ''))
    actual = records[binding['region_ref']]
    action = owned_actions(actual)[attempt]
    for row in rows:
        ref = row['task']
        if ref not in allowed or ref in selected:
            raise ValueError('任务更新须引用本次披露的唯一任务，不得重复或新建任务')
        candidate = allowed[ref]
        region = owner if ref == active else records[candidate['region']]
        task = owned_tasks(region).get(candidate['name'])
        if task is None:
            raise ValueError('任务已迁移或不再存在，不能沿旧候选结算其他任务')
        if task.get('status') not in ('pending', 'blocked') or task.get('equivalent_to') or task.get('shared_task_ref') or task.get('coverage_exemption'):
            raise ValueError('只能更新本次未结束的本地探索任务')
        migrated = ref == active and any((h.get('region') == candidate['region'] and h.get('control') == candidate['control'] and (h.get('attempt') == attempt) for h in task_value(task, 'ownership_history', [])))
        if candidate['control'] != task.get('control') and (not migrated) or candidate['conditions'] != task.get('conditions', []):
            raise ValueError('任务身份或适用条件已变化，需重新核对本次候选')
        if ref != active and (not task.get('prepares')):
            target = completion_target(region, task)
            if not related_to_action(task, region['id'], binding):
                raise ValueError('相关任务必须属于本次实际操作控件，且没有尚未解决的前提或执行阻塞')
            if row.get('entry') or row.get('next_action') is not None:
                raise ValueError('相关任务本步只登记判断和已得知识，不另排后续动作或改写访问关系')
            if target.get('control') is None or not recorded_match(actual, attempt, action, target, receipt) or action.get('result', {}).get('exception') != 'none':
                raise ValueError('旧问题答案必须来自同一已确认实际控件的成功投递与观察')
        selected[ref] = (region, task, row)
    if binding.get('task_name') and active not in selected:
        raise ValueError('更新需保留本轮当前任务的进展，即使本次只是准备动作')
    active_row = selected.get(active, (None, None, {}))[2]
    if active_row:
        settle(owner, binding, {**reply, 'task_update': active_row}, attempt, records, receipt=receipt, labels=labels, explicit=True)
    for (ref, (region, task, row)) in selected.items():
        if ref == active:
            continue
        if not set(task.get('conditions', [])).issubset(set(action.get('conditions', []))):
            raise ValueError('本次动作没有确认旧问题所需适用条件，不能借用其他条件用途的结果')
        related = {**binding, 'task_region': region['id'], 'task_name': allowed[ref]['name'], 'related_assessment': True, 'task_update_ref': ref}
        settle(region, related, {**reply, 'task_update': row}, attempt, records, receipt=receipt, labels=labels, explicit=True)

def latest_suggestion(records, task):
    value = task_value(task, 'latest_update', {})
    if value.get('decision') != 'continue':
        return None
    return deepcopy(value.get('next_action'))
