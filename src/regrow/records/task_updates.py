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
from regrow.records.diagnostics import reject

def object_schema(fields):
    return {'type': 'object', 'properties': {k: deepcopy(v) for (k, v) in fields.items()}, 'required': list(fields), 'additionalProperties': False}

def schema(kinds=None, refs=None):
    string = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    result = object_schema({'task': {'type': 'string', **({'enum': list(refs)} if refs else {})},
                            'state': {'type': 'string', 'enum': ['done', 'pending', 'blocked']}})
    result['properties']['remaining_question'] = deepcopy(string)
    result['allOf'] = [
        {'if': {'properties': {'state': {'enum': ['pending', 'blocked']}}, 'required': ['state']},
         'then': {'required': ['remaining_question']},
         'else': {'properties': {'remaining_question': False}}}]
    return result


def assessment(row):
    """Read a saved old judgement without enabling the old output contract."""
    if 'state' in row or 'decision' not in row:
        return row
    return {**{k: v for k, v in row.items() if k not in ('decision', 'reason', 'next_action')},
            'state': {'answered': 'done', 'continue': 'pending', 'defer': 'blocked'}[row['decision']]}


def validate(row, task, ref=None):
    import jsonschema
    # Saved replies may still contain the retired field; new requests never do.
    value = {k: v for k, v in assessment(row).items() if k != 'retry_when'}
    jsonschema.validate(value, schema(refs=[ref] if ref else None))


def registration_review_sources(task):
    """An old unpublished attempt does not invalidate later accepted knowledge."""
    if task.get('blocker', {}).get('condition') != 'result_registration_pending':
        return []
    failed = str(task.get('deferral', {}).get('failed_call', ''))
    if not failed.isdigit():
        return []
    from regrow.records.tasks import target, source_attempts
    from regrow.records.control_knowledge import evidence
    record = target(task)
    if record is None or not record.get('knowledge'):
        return []
    rejected_attempt = task.get('deferral', {}).get('attempt')
    def accepted(source):
        if not isinstance(source, dict):
            return []
        call = str(source.get('source_call', ''))
        result = [call] if (call.isdigit() and int(call) > int(failed)
                           and rejected_attempt not in source_attempts(source)) else []
        return result + [value for row in source.get('sources', []) for value in accepted(row)]
    return sorted(set(accepted(evidence(record))))


def hard_block(task):
    blocker = task.get('blocker', {})
    condition = blocker.get('condition')
    pending_result = condition == 'result_registration_pending' and registration_review_sources(task)
    return bool(blocker.get('exception') or (condition not in (None, 'review_required', 'prerequisite') and not pending_result) or (task.get('deferral', {}).get('retry_when') == 'explicit_task_ownership_review'))

def decide(task, row, basis, *, product_complete, records, labels=None):
    """Publish Luna's assessment while retaining real execution blockers."""
    row = assessment(row)
    validate(row, task)
    state = row['state']
    blocked = hard_block(task)
    review_sources = registration_review_sources(task)
    if review_sources:
        basis = {**basis, 'registration_gap_evidence': review_sources}
    if state == 'done' and blocked:
        reject('task_unresolved_blocker', row['task'],
               {'提交的进展': state, '仍未解决的阻塞': blocked}, '没有未解决的真实执行、身份或前提阻塞',
               field='任务进展', reason='该任务仍有未解决的真实阻塞，不能直接结算完成。')
    if state == 'done' and not product_complete:
        from regrow.records.task_settlement import missing_product_fields
        missing = '、'.join(missing_product_fields(task))
        reject('task_missing_result', row['task'], {'提交的进展': state, '尚缺登记内容': missing},
               '原任务完成所需的登记内容已提供', field='任务进展',
               reason='该任务的完成登记仍缺少：' + missing + '。')
    previous = task_audit(task).get('latest_update')
    if previous:
        task_audit(task).setdefault('update_history', []).append(deepcopy(previous))
    task_audit(task)['latest_update'] = {**deepcopy(row), 'source': deepcopy(basis)}
    task_audit(task).pop('result_evidence', None)
    if not blocked:
        for key in ('blocker', 'deferral'):
            if task.get(key):
                task_audit(task).setdefault(key + '_history', []).append({**task.pop(key), 'resolved_by': deepcopy(basis)})
        task['status'] = state
    if state == 'blocked' and not blocked:
        task['deferral'] = {'remaining_question': row['remaining_question'],
                            'trigger': {'kind': 'observation', 'observation': basis.get('observation')},
                            **deepcopy(basis)}
    if state == 'done':
        task_audit(task)['completion_basis'] = {'rule': 'explicit_question_answer_registered', **deepcopy(basis)}
    from regrow.records.task_assessments import resolved
    resolved(task, basis.get('source_call'))
    return task['status']

def store_increment(owner, task, name, row, records, state, basis, *, observed=False, labels=None):
    """An observation answers a question without acquiring another action's owner."""
    from regrow.records.task_settlement import registration_kind
    validate(row, task, reference(owner['id'], name))
    from regrow.records.task_settlement import task_product
    product = task_product(task)
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
        from regrow.records.action_evidence import has_observed_result
        if aid in invalid or event.get('缺口') or event.get('归属纠正') or not has_observed_result(action):
            continue
        if aid not in supplied:
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


def observed_control(owner, task, state):
    from regrow.records.task_settlement import completion_target
    from regrow.records.observations import frame_observation
    observation = (state or {}).get('observation') or {}
    target = completion_target(owner, task)
    control = (owner if target['control'] is None else find_control(owner, target['control'])) or {}
    return bool(observation.get('id') and target['region'] in state.get('interactive_regions', []) and (observation.get('foreground', {}).get('exception', 'none') == 'none') and frame_observation(control, observation=observation['id']))

def new_evidence(task, observation):
    """Reconsider a deferred question once for each newly accepted observation."""
    if not observation or task.get('status') != 'blocked' or hard_block(task):
        return False
    latest = task_value(task, 'latest_update', {}) or {}
    previous = latest.get('source', {}).get('observation') or task.get('deferral', {}).get('observation')
    return bool(previous != observation)

def needs_evidence_review(region, observation):
    from regrow.records.object_store import region_work
    inventory = region_work(region).get('task_inventory', {})
    return bool(observation and inventory.get('observation') != observation and any(
        new_evidence(task, observation) for task in owned_tasks(region).values()))


def retire_preparations(records, state=None):
    """Keep legacy preparation records as history; continue the original question."""
    from regrow.records.object_store import region_work
    from regrow.records.tasks import detached
    for rid, region in records.items():
        for name, task in list(owned_tasks(region).items()):
            if task.get('prepares'):
                region_work(region).setdefault('preparation_history', []).append({
                    'name': name, 'record': detached(task)})
                del owned_tasks(region)[name]
            elif task.get('prerequisite'):
                task_audit(task).setdefault('prerequisite_history', []).append(task.pop('prerequisite'))
                if task.get('blocker', {}).get('condition') == 'prerequisite':
                    for key in ('blocker', 'deferral'):
                        value = task.pop(key, None)
                        if value:
                            task_audit(task).setdefault(key + '_history', []).append(value)
                    task['status'] = 'pending'
    if state is not None:
        active = state.get('active_task') or {}
        if active and active.get('name') not in owned_tasks(records.get(active.get('region'), {})):
            state.pop('active_task', None)

def reference(region, name):
    return region + '/' + name

def related_to_action(task, region, binding, observed_regions=()):
    """Offer local questions from the action, original goal and observed surfaces."""
    scope = {binding['region_ref'], binding.get('task_region'), binding.get('working_region'),
             *observed_regions}
    return (region in scope and task.get('status') in ('pending', 'blocked')
            and not task.get('equivalent_to') and not hard_block(task))


def catalog(records, binding, observed_regions=()):
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
            related = related_to_action(task, rid, binding, observed_regions)
            if not current and not related:
                continue
            row = {'task': reference(rid, name), 'region': rid, 'name': name, 'control': task.get('control'), 'control_name': (find_control(region, task.get('control')) or {}).get('name', '区块本身'), 'status': task.get('status'), 'task_type': registration_kind(task), 'conditions': task.get('conditions', [])}
            if 'target' in task:
                row.pop('task_type', None)
                row['target'] = task['target']
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
            reject('task_update_reference', ref,
                   {'填写的任务': ref, '本次是否已提交': ref in selected}, list(allowed),
                   field='任务更新引用', reason='该任务没有随本次披露，或在本次回复中被重复提交。')
        candidate = allowed[ref]
        region = owner if ref == active else records[candidate['region']]
        task = owned_tasks(region).get(candidate['name'])
        if task is None:
            reject('task_update_reference', ref, candidate, '本次候选对应的现存原任务',
                   field='任务更新引用', reason='候选对应的原任务已迁移或不再存在。')
        if task.get('status') not in ('pending', 'blocked') or task.get('equivalent_to'):
            reject('task_update_scope', ref,
                   {'当前进展': task.get('status'), '等价任务引用': task.get('equivalent_to')},
                   '本次未结束的本地探索任务', field='任务更新范围', reason='该任务已结束或是等价任务，不能按本次本地任务更新。')
        migrated = ref == active and any((h.get('region') == candidate['region'] and h.get('control') == candidate['control'] and (h.get('attempt') == attempt) for h in task_value(task, 'ownership_history', [])))
        if candidate['control'] != task.get('control') and (not migrated) or candidate['conditions'] != task.get('conditions', []):
            reject('task_update_context', ref,
                   {'候选控件': candidate['control'], '当前控件': task.get('control'),
                    '候选条件': candidate['conditions'], '当前条件': task.get('conditions', [])},
                   '候选任务与当前任务的控件和适用条件一致', field='任务身份与条件',
                   reason='任务的控件或适用条件已变化，需要核对本次候选。')
        if ref != active:
            target = completion_target(region, task)
            from regrow.records.action_evidence import has_observed_result
            visible = target['region'] in action.get('interactive_regions', [])
            if row['state'] == 'done' and (hard_block(task) or not has_observed_result(action) or not visible or action['result']['exception'] != 'none'):
                reject('related_task_result', ref,
                       {'提交的进展': row['state'], '未解决阻塞': hard_block(task),
                        '本次动作结果已确认': has_observed_result(action), '目标在动作后前景中': visible,
                        '动作异常': action.get('result', {}).get('exception')},
                       '相关任务完成须有本次后图的目标观察且无未解决阻塞或异常', field='相关任务进展',
                       reason='该相关任务的本次完成依据尚不满足要求。')
        selected[ref] = (region, task, row)
    if binding.get('task_name') and active not in selected:
        reject('active_task_update_missing', binding['task_name'], [row['task'] for row in rows],
               active, field='当前任务进展', reason='本次回复没有提供当前任务的进展；准备动作也需要保留该判断。')
    active_row = selected.get(active, (None, None, {}))[2]
    if active_row:
        settle(owner, binding, {**reply, 'task_update': active_row}, attempt, records, receipt=receipt, labels=labels, explicit=True)
    for (ref, (region, task, row)) in selected.items():
        if ref == active:
            continue
        related = {**binding, 'task_region': region['id'], 'task_name': allowed[ref]['name'], 'related_assessment': True, 'task_update_ref': ref}
        settle(region, related, {**reply, 'task_update': row}, attempt, records, receipt=receipt, labels=labels, explicit=True)


def recovery_evidence(run, task):
    """Read episodes linked by real interrupted attempts; no name-based linkage."""
    rows = []
    frames = []
    attempts = set(task_value(task, 'attempts', []))
    for path in sorted((Path(run) / 'recovery_episodes').glob('*/episode.json')):
        episode = json.loads(path.read_text())
        if not any((row.get('触发动作') in attempts for row in episode.get('interrupted_tasks', []))):
            continue
        if episode.get('exception') != 'none' or not episode.get('actions'):
            continue
        actions = episode['actions']
        if not all((a.get('delivery') == 'executed_receipt_zero' for a in actions)):
            continue
        if actions[-1].get('observed_result', {}).get('exception') != 'none':
            continue
        calls = list(dict.fromkeys((c for row in actions for c in (row.get('source_call'), row.get('observed_result', {}).get('source_call')) if c)))
        if not all(((Path(run) / 'calls' / c / 'request.json').is_file() for c in calls)):
            continue
        for call in calls:
            request = json.loads((Path(run) / 'calls' / call / 'request.json').read_text())
            for f in request.get('screenshots', []):
                fp = Path(run) / f
                if fp.is_file() and str(fp.resolve()) not in frames:
                    frames.append(str(fp.resolve()))
        rows.append({'episode': str(path.relative_to(run)), 'source_call': episode.get('source_call'), 'actions': actions, 'handoff': episode.get('handoff'), 'recovery_calls': calls})
    return (rows, frames)
