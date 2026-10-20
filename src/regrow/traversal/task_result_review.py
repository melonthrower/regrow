from regrow.records.calls import submission as _owner_submission
from regrow.records.tasks import in_scope as _record_in_scope
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import write_json as _record_write_json
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
'Update-stage settlement of cumulative evidence, without a new GUI attempt.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
import json
from pathlib import Path

def reviewable(task, observation):
    """An unassessed evidence gap gets one explicit model assessment."""
    from regrow.records.task_updates import hard_block
    if not observation or task.get('status') != 'blocked' or task.get('equivalent_to'):
        return False
    if task.get('shared_task_ref') or task.get('coverage_exemption') or hard_block(task):
        return False
    if task.get('deferral', {}).get('retry_when') == 'explicit_task_ownership_review':
        return False
    latest = task_value(task, 'latest_update')
    if latest:
        trigger = task.get('deferral', {}).get('trigger', {})
        if trigger.get('kind') == 'recovery':
            return str(trigger.get('source_call', '')).removeprefix('recovery-') != latest.get('source', {}).get('recovery_call')
        return bool(trigger.get('kind') == 'observation' and trigger.get('observation') and (trigger['observation'] != latest.get('source', {}).get('observation')))
    return bool(task_value(task, 'attempts') or task_value(task, 'findings') or task.get('deferral', {}).get('trigger'))

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

def later_entry_history(region, task):
    """A legacy blocked entry may have later evidence; this never settles it."""
    from regrow.records import action_owner_correction as _action_owner_correction
    if task.get('status') != 'blocked' or task.get('equivalent_to') or task.get('blocker') or task.get('deferral'):
        return []
    candidates = _action_owner_correction.control_history(region, task)
    return [aid for aid in candidates if aid not in task_value(task, 'attempts', []) and owned_actions(region)[aid].get('result', {}).get('exception') == 'none' and (owned_actions(region)[aid].get('result', {}).get('returns_to_previous') is not True) and (owned_actions(region)[aid].get('text_delivered') is not False)]

def repeated_entry_attempts(run, region, task):
    """Repeated observed entry outcome requests assessment, never completion."""
    from regrow.records.task_settlement import registration_kind
    from regrow.records.action_owner_correction import control_history
    from regrow.recognition.visual_backtrack import same_surface
    if task.get('status') != 'pending' or task.get('prepares') or registration_kind(task) != 'function':
        return []
    history = sorted(control_history(region, task))
    allowed = set(task_value(task, 'attempts', [])) - set(task.get('completion_action', {}).get('excluded_attempts', []))
    valid = [aid for aid in history if aid in allowed and owned_actions(region)[aid].get('conditions', []) == task.get('conditions', []) and owned_actions(region)[aid].get('delivery') == 'executed_receipt_zero'
             and owned_actions(region)[aid].get('result', {}).get('exception') == 'none']
    if len(valid) < 2:
        return []
    pair = valid[-2:]
    latest = task_value(task, 'latest_update', {}).get('source', {})
    if set(pair).issubset(latest.get('related_attempts', [])):
        return []
    folders = [Path(run) / 'action_attempts' / aid for aid in pair]
    if not all((folder / name).is_file() for folder in folders for name in ('before.png', 'after.png')):
        return []
    return pair if same_surface(folders[0] / 'after.png', folders[1] / 'after.png') else []

def next_deferred(root, run, frame):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.records import task_updates as _task_updates
    (_, records, state) = _record_load(run)
    if state.get('next_action_mode') != 'explore' or state.get('exception', 'none') != 'none':
        return None
    observation = (state.get('observation') or {}).get('id')
    for (rid, region) in records.items():
        if region_work(region).get('out_of_scope_reason'):
            continue
        for (name, task) in owned_tasks(region).items():
            if not _record_in_scope(region, task, records):
                continue
            ready = bool(task.get('prepares') and task.get('status') == 'pending' and _task_updates.preparation_product(task, {'decision': 'answered'}, records, {}))
            if reviewable(task, observation) or ready or repeated_entry_attempts(run, region, task):
                return request(root, run, {'task_region': rid, 'task_name': name}, [str(frame)])
    return None

def request(root, run, source, frames):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.records import action_owner_correction as _action_owner_correction
    from regrow.records import history_context as _history_context
    from regrow.prompts import frame_context as _frame_context
    from regrow.records import task_updates as _task_updates
    from regrow.records import task_settlement as _task_settlement
    from regrow.records import coverage_exemption as _coverage_exemption
    from regrow.traversal import work_context as _work_context
    (snapshot, records, state) = _record_load(run)
    rid = source.get('task_region') or source.get('region')
    name = source.get('task_name')
    task = owned_tasks(records.get(rid, {})).get(name)
    later = later_entry_history(records[rid], task) if task is not None else []
    deferred = task is not None and reviewable(task, (state.get('observation') or {}).get('id'))
    if task is None or not (task.get('status') == 'pending' or deferred or later):
        raise ValueError('需要待完成任务或有未复核恢复/循环证据的暂挂任务')
    recovered = bool(recovery_evidence(run, task)[0])
    paths = []  # Unified object blocks are selected from the final output contract.
    parts = [{'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()} for path in paths]
    history = later or _action_owner_correction.control_history(records[rid], task)
    history = [a for a in history if a not in task_value(task, 'attempts', [])]
    goal_history = _history_context.task_goal(task, records, run, attempt_refs=() if later else history)
    goal_history.pop('原任务已有判断', None)
    for event in goal_history.get('相关动作', []):
        if '观察' in event:
            event['原登记结果'] = event.pop('观察')
        if '证据' in event:
            event['原登记依据'] = event.pop('证据')
    dynamic = {'本轮探索任务': _task_settlement.exploration_goal(task), '来源区块': records[rid]['name'], '任务目标与累计证据': goal_history, '说明': '本轮没有执行新动作；本轮观察图反映当前界面，历史事实按动作/调用来源读取。'}
    if later:
        dynamic['独立入口历史'] = [{'动作记录': aid, '直接效果': _history_context.task_goal({'task_type': task['task_type'], 'reason': task.get('reason') or task.get('name', ''), 'attempts': [aid]}, records, run)} for aid in history]
        dynamic['历史间隔'] = '这些是独立尝试的直接前后效果，不是连续操作链；未提供期间全部操作，不能推断状态持续或跨尝试因果。'
        dynamic['本次核对原因'] = '旧任务暂挂后，同一控件另有已执行记录。比较已登记实际结果与原结束条件；历史清单可能不完整，不能仅凭区块集合变化判完成。旧失败不抹去，新的历史也不代表当前界面可操作。'
    if history:
        dynamic['同控件历史复用'] = '额外提供同一已登记控件的既有动作：' + '、'.join(history) + '。它们不是本任务的新执行；核对真实对象、已登记观察及结束条件后才可采用。归属纠正不自动证明任务完成。'
    (recovery_rows, recovery_frames) = recovery_evidence(run, task)
    repeated = repeated_entry_attempts(run, records[rid], task)
    comparison = []
    if repeated:
        # Use only the real latest attempt pair, not two unrelated current frames.
        comparison = [str((Path(run) / 'action_attempts' / repeated[-1] / name).resolve()) for name in ('before.png', 'after.png')]
        dynamic['待复核动作'] = repeated[-1]
        dynamic['说明'] = '本轮没有执行新动作；附图是所列最近一次动作的原始前后图，当前现场以另一次实时观察为准。'
        frames = comparison
        effect_path = '动作/结果核对.prompt'
        parts.insert(0, {'path': effect_path, 'text': (Path(root) / 'regrow/prompts' / effect_path).read_text()})
    frames = list(frames)
    dynamic.update(复核目的='对照本轮类型目标和已提供证据，明确继续、已回答或暂挂。没有新GUI执行。', 原暂挂依据={'blocker': task.get('blocker'), 'deferral': task.get('deferral')})
    if recovery_rows:
        dynamic['直接相关恢复过程'] = recovery_rows
    fields = {'task_update': _task_updates.schema([_task_settlement.registration_kind(task)])}
    fields['task_update']['properties'].pop('task')
    fields['task_update']['required'].remove('task')
    if comparison:
        effect_schema = json.loads((Path(root) / 'regrow/prompts/输出格式/动作后更新.schema').read_text())['properties']['action_result']
        fields = {'action_result': effect_schema, **fields}
    result = {'pipeline_step': 'update', 'stage': 'task_result_review', 'role': 'task_result_review', 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': list(frames), 'fixed_parts': parts, 'response_schema': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}, 'source': {'region': rid, 'task_region': rid, 'task_name': name, 'task_control': task.get('control'), 'observation': (state.get('observation') or {}).get('id'), 'snapshot': str(snapshot.relative_to(Path(run).resolve())), 'review_control_history': history, 'recovery_evidence': recovery_rows}}
    if repeated:
        result['source']['comparison_attempt'] = repeated[-1]
    from regrow.prompts.frame_context import label
    if comparison:
        label(result, frames[0], repeated[-1] + ' 动作前原图')
        label(result, frames[1], repeated[-1] + ' 动作后原图')
    elif frames:
        label(result, frames[0], '本轮观察图')
    result = _coverage_exemption.augment(root, run, result, records, state, rid, name)
    _work_context.attach(result, records, state)
    _frame_context.validate(result)
    return result

def apply(region, state, name, assessment, call, available_history=(), *, records=None, recovery_rows=(), review_attempt=None):
    from regrow.records import task_updates as _task_updates
    from regrow.records import task_settlement as _task_settlement
    records = records or {region['id']: region}
    task = owned_tasks(region)[name]
    row = {**assessment.get('task_update', assessment)}
    row.setdefault('task', _task_updates.reference(region['id'], name))
    updates = _task_updates
    settlement = _task_settlement
    updates.validate(row, task, updates.reference(region['id'], name))
    if task.get('status') not in ('pending', 'blocked') or task.get('shared_task_ref'):
        raise ValueError('只复核未结束的本地任务')
    historical = set(task_value(task, 'attempts', [])) | set(available_history)
    actual = [(rid, aid, a) for (rid, r) in records.items() for (aid, a) in owned_actions(r).items() if aid in historical and settlement.recorded_match(r, aid, a, settlement.completion_target(region, task))]
    observed = updates.observed_control(region, task, state) or bool(actual) or bool(recovery_rows)
    basis = {'basis': 'observation_only', 'source_call': call, 'observation': (state.get('observation') or {}).get('id'), 'related_attempts': sorted(historical)}
    if recovery_rows:
        basis['recovery_call'] = recovery_rows[-1]['recovery_calls'][-1]
    if review_attempt and row.get('entry'):
        from copy import deepcopy
        matches = [(rid, aid, a) for rid, aid, a in actual if aid == review_attempt]
        if len(matches) != 1:
            raise ValueError('入口复核缺少所附前后图对应的有效原任务动作')
        rid, aid, action = matches[0]
        entry = settlement.register_entry(row['entry'], records, records[rid], aid,
                    knowledge=row.get('knowledge') or task_value(task, 'knowledge', ''))
        entry['source'] = {'basis': 'explored', 'attempt': aid, 'region': rid, 'control': action['control'],
                           'source_call': call, 'result_call': action.get('evidence', {}).get('result_call')}
        settlement.store_action_entry(task, entry, action, aid, row['entry']['evidence'])
        row = deepcopy(row)
        row.pop('entry')
    updates.store_increment(region, task, name, row, records, state, basis, observed=observed)
    if task['status'] != 'pending' and state.get('active_task') == {'region': region['id'], 'name': name}:
        state.pop('active_task', None)
    if task['status'] == 'pending':
        state['active_task'] = {'region': region['id'], 'name': name}

def commit(root, run, call):
    from regrow.traversal import discovery_step as _discovery_step
    if (Path(run) / 'execution_pending.json').exists():
        raise ValueError('动作尚未结算，不能无动作复核')
    discovery = _discovery_step
    (q, reply) = _owner_submission(run, call)
    source = q['source']
    (old, _, _) = _record_load(run)
    if str(old.relative_to(Path(run).resolve())) != source['snapshot']:
        raise ValueError('累计证据快照已变化，刷新后重新核对')

    def mutate(records, state, snapshot, temp):
        from regrow.records import action_owner_correction as _action_owner_correction
        from regrow.records import task_updates as _task_updates
        from regrow.records import coverage_exemption as _coverage_exemption
        region = records[source['task_region']]
        if owned_tasks(region)[source['task_name']].get('control') != source['task_control']:
            raise ValueError('任务归属已变化，不能沿用原结果')
        history = source.get('review_control_history', [])
        available = _action_owner_correction.control_history(region, owned_tasks(region)[source['task_name']])
        if any((a not in available for a in history)):
            raise ValueError('同控件历史依据已变化')
        if any((not all(((Path(run) / 'action_attempts' / aid / (when + '.png')).is_file() for when in ('before', 'after'))) for aid in history)):
            raise ValueError('历史复用的原始证据缺失')
        if reply.get('coverage') is not None:
            assessment = reply.get('task_update', {})
            if assessment.get('task', _task_updates.reference(source['task_region'], source['task_name'])) != _task_updates.reference(source['task_region'], source['task_name']) or assessment.get('decision') != 'continue':
                raise ValueError('覆盖豁免保留原任务未实测，不用answered伪造执行')
            refs = source.get('coverage_candidates', [])
            for ref in refs:
                if not all(((Path(run) / 'action_attempts' / ref['attempt'] / (when + '.png')).is_file() for when in ('before', 'after'))):
                    raise ValueError('覆盖复核缺少候选真实前后图')
            _coverage_exemption.apply(records, state, source['task_region'], source['task_name'], reply['coverage'], refs, call)
        else:
            current_recovery = recovery_evidence(run, owned_tasks(region)[source['task_name']])[0]
            if source.get('recovery_evidence', []) != current_recovery:
                raise ValueError('恢复证据已变化，刷新本任务复核')
            review_attempt = source.get('comparison_attempt')
            if review_attempt:
                repeated = repeated_entry_attempts(run, region, owned_tasks(region)[source['task_name']])
                expected = [str((Path(run) / 'action_attempts' / review_attempt / name).resolve()) for name in ('before.png', 'after.png')]
                if not repeated or repeated[-1] != review_attempt or [str((Path(run) / f).resolve()) for f in q['screenshots']] != expected:
                    raise ValueError('入口复核的原动作或前后图来源已变化')
                from copy import deepcopy
                action = owned_actions(region)[review_attempt]
                action['result'] = deepcopy(reply['action_result'])
                action.setdefault('evidence', {})['result_call'] = call
                if 'result_call' in action:
                    action['result_call'] = call
            apply(region, state, source['task_name'], reply, call, history, records=records, recovery_rows=current_recovery, review_attempt=review_attempt)
        _record_write_json(temp / 'task_result_review.json', {'source_call': call, 'task': source, 'result': reply, 'new_gui_action': False})
    return _record_publish(run, 'task-review-' + call, mutate)
