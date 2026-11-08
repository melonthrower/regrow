from regrow.recognition.identity_templates import appearance_box
from regrow.records import region_evidence as _region_evidence
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Investigate disputed control ownership on device before publishing a partition.'
from regrow.records.object_store import owned_controls
from copy import deepcopy
import json
from pathlib import Path
import uuid

def review_scope(episode, source, *, run=None):
    """Use the reported dispute; an old review is not a new full inventory."""
    if 'disputed_controls' in episode:
        ids = episode['disputed_controls']
        region_wide = episode.get('region_wide', False)
    else:
        reason = episode.get('reason')
        errors = [row for row in reason.get('errors', [])
                  if row.get('code') == 'region_ownership_review'] if isinstance(reason, dict) else []
        if not errors and run is not None and episode.get('source_episode'):
            from regrow.records.snapshots import read
            try:
                job = read(Path(run) / episode['source_episode'])
            except (OSError, ValueError):
                return None
            if job.get('stage') == 'discovery' and not job.get('attempt'):
                candidate = deepcopy(job.get('candidate') or {})
                # Older wire replies imply an existing identity through ref.
                # Recover only those explicit objects, without matching images.
                for control in candidate.get('controls', []):
                    if control.get('ref'):
                        control.setdefault('identity', 'same')
                report = conflict(job.get('request', {}), candidate,
                                  {source['id']: source}, all_rows=True)
                errors = report['errors'] if report else []
        if not errors:
            return None
        region_wide = any(not row.get('actual', {}).get('control_id')
                          and row.get('actual', {}).get('region_id') == source['id'] for row in errors)
        ids = [row.get('actual', {}).get('control_id') for row in errors
               if row.get('actual', {}).get('control_id')]
        if not region_wide and not ids:
            return None
    controls = list(owned_controls(source))
    return {'region_wide': bool(region_wide),
            'disputed_controls': controls if region_wide else [cid for cid in controls if cid in ids]}


def check_action(run, binding):
    """Only the actually selected disputed control needs ownership repair."""
    from regrow.records.snapshots import read
    from regrow.records.observations import frame_observation
    from regrow.traversal.repair_stages import BindingConflict
    cid = binding.get('control_ref')
    if not cid:
        return
    run = Path(run)
    _, records, _ = _record_load(run)
    for source in records.values():
        if cid not in owned_controls(source):
            continue
        work = region_work(source)
        gaps = [work.get('registration_gaps', {}).get('ownership_review')]
        gaps.extend(gap for gap in work.get('registration_gap_history', [])
                    if str(gap.get('episode', '')).startswith('ownership_reviews/'))
        seen = set()
        for gap in gaps:
            if not gap or 'controls' in gap and cid not in gap['controls']:
                continue
            reference = gap.get('episode', '')
            if reference in seen:
                continue
            seen.add(reference)
            path = run / reference
            try:
                episode = read(path) if path.is_file() else None
            except (OSError, ValueError):
                episode = None
            scope = review_scope(episode, source, run=run) if episode else None
            disputed = gap.get('controls', scope['disputed_controls'] if scope else [])
            if cid not in disputed:
                continue
            if episode and cid in episode.get('assignments', {}) and cid not in episode.get('conflicts', {}):
                target = assignment_target(episode['assignments'][cid], records, {source['name']: source['id']})
                if episode.get('status') == 'resolved' or target.get('ref') == source['id']:
                    continue
            dispute_call = gap.get('source_call')
            if not dispute_call and episode and episode.get('source_episode'):
                source_job = run / episode['source_episode']
                if source_job.is_file():
                    dispute_call = read(source_job).get('call')
            observed = frame_observation(owned_controls(source)[cid], kind='controls',
                observation=binding.get('observation_ref'), region=source['id'])
            evidence = observed.get('evidence', {})
            current_call = evidence.get('source_call')
            if (binding.get('observation_ref') and binding.get('region_ref') == source['id']
                    and evidence.get('region') == source['id']
                    and isinstance(dispute_call, str) and dispute_call.isdigit()
                    and isinstance(current_call, str) and current_call.isdigit()
                    and int(current_call) > int(dispute_call)):
                # A newly accepted observation explicitly confirms this control
                # and its current owner; the old disputed partition stays in history.
                continue
            raise BindingConflict('实际操作控件 ' + cid + ' 仍有未解决的归属争议；'
                                  '先修正该对象的归属，或选择不依赖它的准备动作。原复查：'
                                  + str(gap.get('episode', '未保留')))


def resume_independent_target(root, run, episode, episode_path):
    """Finish only the independent target in an existing unexecuted review."""
    from regrow.records.snapshots import read
    from regrow.traversal.step_repair import atomic
    from regrow.records.observations import frame_observation
    from regrow.traversal.discovery_step import commit
    import jsonschema
    run = Path(run)
    finishing = episode.get('status') == 'deferred' and episode.get('independent_registration')
    if (not finishing and episode.get('status') not in ('blocked', 'pending') or episode.get('actions')
            or (run / 'execution_pending.json').exists()):
        return None
    try:
        job_path = run / episode['source_episode']
        job = read(job_path)
        if job.get('stage') != 'discovery' or job.get('attempt'):
            return None
        if finishing:
            if episode['independent_registration'] != job['call'] or job.get('status') != 'complete':
                return None
            result = read(run / 'knowledge_current.json')
        else:
            result = commit(root, run, job['call'], ownership_episode=episode_path)
        snapshot, records, _ = _record_load(run)
        receipt = read(snapshot / 'discovery_receipt.json')
        accepted = receipt.get('independent_target', {})
        if (read(snapshot / 'source.json').get('stage') != 'discovery-' + job['call']
                or accepted.get('episode') != episode_path):
            return None
        target_path = '/controls/' + str(accepted.get('control_index'))
        observations = [frame_observation(c, kind='controls', call=job['call'], region=rid)
                        for rid, region in records.items() for c in owned_controls(region).values()]
        if not any(row and row.get('evidence', {}).get('source_field') == target_path for row in observations):
            return None
        source = records[episode['source_region']]
        gap = region_work(source).get('registration_gaps', {}).get('ownership_review') or {}
        if gap.get('episode') == episode_path and 'controls' in gap:
            scope = review_scope({**episode, 'disputed_controls': gap['controls'], 'region_wide': False}, source)
        else:
            scope = review_scope(episode, source, run=run)
        if scope is None:
            return None
        # The caller saves this same episode before removing the active pointer.
        episode.update(scope)
    except (OSError, ValueError, jsonschema.ValidationError):
        return None
    entry = {'framework': 'independent_target_registered', 'ownership_review': episode_path}
    if entry not in job.setdefault('history', []):
        job['history'].append(entry)
    job.update(status='complete', result=result)
    atomic(job_path, job)
    return {'status': 'ready_next_round', 'reason': '当前目标已登记；其他归属争议保留，下一步重新选动作',
            'calls': [], 'registration_call': job['call']}


def yield_unrelated(run, episode, episode_path):
    """Retain an unexecuted dispute while an already observed task proceeds."""
    from regrow.records.snapshots import read
    from regrow.records.task_settlement import completion_target
    from regrow.traversal.traversal_scheduler import select_work, reviews_task
    from regrow.traversal.work_context import from_request
    from regrow.traversal.step_repair import atomic
    from regrow.runtime.reply_correction import abandon
    run = Path(run)
    if (episode.get('actions') or (run / 'execution_pending.json').exists()
            or episode.get('status') not in ('pending', 'blocked', 'deferred')):
        return None
    job = read(run / episode['source_episode'])
    if job.get('stage') != 'discovery' or job.get('attempt') or job.get('status') == 'complete':
        return None
    _, records, state = _record_load(run)
    scope = review_scope(episode, records[episode['source_region']], run=run)
    if not scope or scope['region_wide'] or not scope['disputed_controls']:
        return None
    observation = state.get('observation') or {}
    if (not observation.get('id') or not observation.get('image')
            or observation.get('foreground', {}).get('exception', 'none') != 'none'
            or state.get('next_action_mode') not in ('discover', 'explore')):
        return None
    # The suspended discovery executed nothing. Its retained accepted observation
    # can select work; the normal action path still binds against the fresh frame.
    decision = select_work(records, {**state, 'next_action_mode': 'explore'})
    selected = decision.get('task')
    if decision['kind'] != 'action' or not selected:
        return None
    owner = records[selected['region']]
    task = owned_tasks(owner)[selected['name']]
    target = completion_target(owner, task)
    disputed = set(scope['disputed_controls'])
    dependency = task.get('prerequisite') or {}
    if (reviews_task(owner, selected) or target.get('control') in disputed
            or not dependency.get('satisfied') and dependency.get('control') in disputed
            or target.get('region') not in state.get('interactive_regions', [])
            or target.get('control') and target['control'] not in observation.get('control_refs', [])):
        return None
    if (state.get('reason') == 'action_target_needs_registration'
            and from_request(job['request'], records, state).get('task') == selected):
        # Re-selecting the same task can repeat its still-unregistered preparation.
        # Independent-target recovery above handles that original action instead.
        return None
    format_pointer = run / 'pending_format_reply.json'
    if format_pointer.exists() and read(format_pointer).get('original', {}).get('role') != 'ownership_review':
        return None
    reason = '当前任务的操作对象已登记；其他控件的归属争议保留，继续该任务。'
    gap = {'reason': reason, 'episode': episode_path, 'controls': list(scope['disputed_controls']),
           'source_call': job.get('call'), 'deferred_to': deepcopy(selected)}
    old = region_work(records[episode['source_region']]).get('registration_gaps', {}).get('ownership_review')
    if old != gap:
        def mutate(records, state, *_):
            work = region_work(records[episode['source_region']])
            previous = work.setdefault('registration_gaps', {}).get('ownership_review')
            if previous and previous != gap:
                work.setdefault('registration_gap_history', []).append(deepcopy(previous))
            work['registration_gaps']['ownership_review'] = deepcopy(gap)
            state.update(active_task=deepcopy(selected), working_region=decision['region'],
                         next_action_mode='explore', phase='ready_for_next_action',
                         reason='unrelated_ownership_review_deferred')
            for key in ('inspection_region', 'required_control', 'discovery_mode',
                        'pending_frame', 'correction_context'):
                state.pop(key, None)
        _record_publish(run, 'ownership-yield-' + Path(episode_path).parent.name, mutate)
    episode.update(status='deferred', yielded_to=deepcopy(selected))
    job.update(status='deferred', deferral={'reason': reason, 'ownership_review': episode_path,
                                           'next': deepcopy(selected)})
    entry = {'framework': 'unrelated_ownership_review_deferred', 'task': deepcopy(selected)}
    if entry not in job.setdefault('history', []):
        job['history'].append(entry)
    atomic(run / episode['source_episode'], job)
    atomic(run / episode_path, episode)
    abandon(run, reason)
    (run / 'ownership_review.json').unlink(missing_ok=True)
    return {'status': 'ready_next_round', 'continue_current': True, 'reason': reason, 'calls': []}


def begin(run, job, report):
    """Only unexecuted discovery conflicts enter this branch; updates stay unsettled."""
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import step_repair as _step_repair
    errors = report.get('errors', []) if isinstance(report, dict) else []
    if job['stage'] != 'discovery' or job.get('attempt') or (not any((e['code'] == 'region_ownership_review' for e in errors))):
        return False
    run = Path(run)
    if (run / 'execution_pending.json').exists():
        return False
    d = _discovery_step
    (_, records, state) = _record_load(run)
    ids = {e['actual'].get('control_id') for e in errors if e['code'] == 'region_ownership_review'}
    owners = {rid for (rid, r) in records.items() if ids.intersection(owned_controls(r))}
    owners.update((e['actual']['region_id'] for e in errors if e['code'] == 'region_ownership_review' and e['actual'].get('region_id') in records))
    if len(owners) != 1:
        return False
    rid = next(iter(owners))
    key = uuid.uuid4().hex
    relative = 'ownership_reviews/' + key + '/review.json'
    episode = {'exception': 'region_ownership_review', 'status': 'pending', 'source_region': rid, 'source_episode': job['path'], 'proposed_regions': job['candidate']['regions'], 'reason': report, 'observations': [], 'actions': [], 'assignments': {}, 'conflicts': {}, 'original_working_region': state.get('working_region')}
    scope = review_scope(episode, records[rid])
    if scope is None:
        return False
    episode.update(scope)
    atomic = _step_repair.atomic
    atomic(run / relative, episode)
    atomic(run / 'ownership_review.json', {'episode': relative})
    job.update(status='ownership_review', ownership_review=relative)
    atomic(run / job['path'], job)
    (run / 'pending_step.json').unlink(missing_ok=True)
    return True

def request(root, run, episode, frame):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.runtime import action_commands as _action_commands
    (_, records, _) = _record_load(run)
    source = records[episode['source_region']]
    scope = review_scope(episode, source)
    if scope is None:
        raise ValueError('原归属复查未保留具体争议对象，不能扩大为全部控件复查')
    refs = scope['disputed_controls']
    string = {'type': 'string', 'minLength': 1}
    common = {'control': {'type': 'string', 'enum': refs}, 'evidence': string}
    assignment = {'oneOf': [
        {'type': 'object', 'properties': {**common, 'ref': {'type': 'string', 'enum': list(records)}},
         'required': ['control', 'ref', 'evidence'], 'additionalProperties': False},
        {'type': 'object', 'properties': {**common, 'name': string, 'description': string},
         'required': ['control', 'name', 'description', 'evidence'], 'additionalProperties': False}]}
    action = _action_commands.execution_schema()
    schema = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['continue', 'resolved', 'defer']}, 'reason': {'type': 'string'}, 'observed_assignments': {'type': 'array', 'items': assignment}, 'action': {'anyOf': [action, {'type': 'null'}]}}, 'required': ['status', 'reason', 'observed_assignments', 'action'], 'additionalProperties': False}
    schema['allOf'] = [{'if': {'properties': {'status': {'const': 'continue'}}},
                        'then': {'properties': {'action': deepcopy(action)}},
                        'else': {'properties': {'action': {'type': 'null'}}}}]
    path = '纠错/区块归属复查.prompt'
    text = (Path(root) / 'regrow/prompts' / path).read_text()
    from regrow.prompts.object_blocks import catalog
    _, blocks = catalog(root)
    parts = [{'path': path, 'text': text}]
    parts.extend({k: blocks[name][k] for k in ('path', 'text')}
                 for name in ('region.ownership_status', 'region.observed_assignments'))
    dynamic = {'原区块': {'ref': source['id'], '名称': source['name'], '描述': source['description']}, '待核对历史控件': [{'ref': cid, '名称': c['name'], '最近登记观察': {k: next((row[k] for row in reversed(observation_history(c)) if k in row and not row.get('visual_only')), '') for k in ('icon_description', 'knowledge', 'possible_operation', 'uncertainty')}} for cid, c in owned_controls(source).items() if cid in refs], '待核对的划分建议': episode['proposed_regions'], '已观察归属': {cid: item for cid, item in episode['assignments'].items() if cid in refs}, '归属冲突': {cid: item for cid, item in episode['conflicts'].items() if cid in refs}, '本次复查动作': episode['actions'][-6:], '说明': '核对列出对象的归属；无法确认的对象保留疑点，不要求补齐其他控件。'}
    from regrow.records.environment_context import forest
    dynamic['控件树'] = forest(records, view='controls', focus=source['id'], control_regions={source['id']})
    request = {'pipeline_step': 'recovery', 'stage': 'ownership_review', 'role': 'ownership_review', 'system_prompt': '\n\n'.join(part['text'] for part in parts), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [str(frame)], 'fixed_parts': parts, 'response_schema': schema}
    from regrow.prompts.frame_context import label
    from regrow.recognition.named_references import prepare
    return prepare(run, label(request, request['screenshots'][0], '本次区块归属复查观察图'))

def assignment_target(item, records, existing_targets=None):
    """One canonical target; only archived callers may still provide region."""
    if 'ref' in item:
        if item['ref'] not in records:
            raise ValueError('归属目标区块已不存在，请重新核对引用')
        return {'ref': item['ref']}
    if 'name' in item:
        return {'name': item['name'], 'description': item['description']}
    old = item['region']
    matches = [old] if old in records else []
    if (existing_targets or {}).get(old):
        matches = [existing_targets[old]]
    if len(matches) > 1:
        raise ValueError('旧归属目标同名，需明确已有区块ID')
    return {'ref': matches[0]} if matches else {'name': old, 'description': item['description']}

def record_observation(episode, reply, call, frame, records):
    source = records[episode['source_region']]
    scope = review_scope(episode, source)
    if scope is None:
        raise ValueError('归属复查缺少可核对的对象范围')
    refs = scope['disputed_controls']
    seen = set()
    for row in reply['observed_assignments']:
        cid = row['control']
        if cid not in owned_controls(source): raise ValueError('归属复查须引用原控件ID')
        if cid not in refs:
            # A saved older request may have asked about the whole Region.
            # Its raw reply remains in calls; unrelated rows do not move owners.
            if 'region' in row:
                continue
            raise ValueError('控件不在本次明确待复查范围')
        target = assignment_target(row, records, {source['name']: source['id']})
        if cid in seen or not all(value.strip() for value in [row['evidence'], *target.values()]):
            raise ValueError('duplicate or empty ownership evidence')
        seen.add(cid)
        item = {'control': cid, **target, 'evidence': row['evidence'], 'call': call, 'frame': str(frame)}
        old = episode['assignments'].get(cid)
        if cid in episode['conflicts']:
            episode['conflicts'][cid].append(item)
        elif old and assignment_target(old, records, {source['name']: source['id']}) != target:
            episode['conflicts'][cid] = [old, item]
        else:
            episode['assignments'][cid] = item
    episode['observations'].append({'call': call, 'frame': str(frame), 'status': reply['status'],
                                    'reason': reply['reason'], 'observed_assignments': deepcopy(reply['observed_assignments'])})

def repartition(records, state, episode, snapshot, *, existing_targets=None, merge_controls=()):
    """Move confirmed identities and owned tasks/actions; retain unresolved old scope."""
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import action_context as _stepwise_flow
    reg = _register_update
    flow = _stepwise_flow
    source = records[episode['source_region']]
    source_id = source['id']
    scope = (review_scope(episode, source) if episode.get('source_episode')
             else {'disputed_controls': list(episode['assignments'])})
    if scope is None:
        raise ValueError('归属复查缺少可核对的对象范围')
    refs = scope['disputed_controls']
    targets = {}
    moved = {}
    task_moves = {}
    action_moves = {}
    created_targets = set()
    source_plan = deepcopy(region_work(source).get('task_inventory', {}))
    for (cid, item) in episode['assignments'].items():
        if cid not in refs or cid in episode['conflicts']:
            continue
        if item.get('region') == source['name']:
            continue  # Archived replies may still name their original owner.
        target = assignment_target(item, records, existing_targets)
        if target.get('ref') == source_id:
            continue
        name = target.get('ref') or target['name']
        if name not in targets:
            if 'name' in target and (name in records or any(r['name'] == name for r in records.values())):
                raise ValueError('partition name collides with existing Region; use its ref')
            rid = target.get('ref') or (records.allocate('region') if isinstance(records, object_store.Records) else 'r' + str(max([int(r[1:]) for r in records] + [0]) + 1).zfill(4))
            if rid not in records:
                records[rid] = _region_evidence.new_region(rid, name, target['description'])
                created_targets.add(rid)
            targets[name] = rid
        elif 'name' in target and records[targets[name]]['description'] != target['description']:
            raise ValueError('同一新区块的职责描述不一致，请核对归属')
        rid = targets[name]
        dest = records[rid]
        owned_tasks(dest, create=True)
        collisions = {key for (key, c) in owned_controls(dest).items() if c['name'] == owned_controls(source)[cid]['name']}
        if cid in owned_controls(dest) or (collisions and (rid, cid, frozenset(collisions)) not in merge_controls):
            raise ValueError('目标区块已有同名控件，先核对是否重复身份')
        from regrow.records.control_records import group_name, set_group
        list_group = group_name(source, cid)
        control = owned_controls(source).pop(cid)
        owned_controls(dest)[cid] = reg.rebase(control, snapshot, snapshot)
        if list_group:
            set_group(dest, cid, list_group)
        owned_controls(dest)[cid]['ownership_evidence'] = {'previous_region': source_id, **item}
        moved[cid] = rid
        # Task coverage belongs to the reviewed identities, not their old owner.
        plan = region_work(dest).get('task_inventory')
        if plan is None and source_plan.get('source_call'):
            plan = {'evidence': source_plan.get('evidence', ''), 'controls': []}
            if rid in created_targets:
                plan['source_call'] = source_plan['source_call']
            region_work(dest)['task_inventory'] = plan
        if plan is not None and cid in source_plan.get('controls', []):
            plan['controls'] = list(dict.fromkeys([*plan.get('controls', []), cid]))
        for (name, task) in list(owned_tasks(source).items()):
            if task.get('control') != cid:
                continue
            if name in owned_tasks(dest):
                raise ValueError('task name collision in partition')
            owned_tasks(dest)[name] = owned_tasks(source).pop(name)
            task_moves[name] = rid
        for (aid, action) in list(owned_actions(source).items()):
            if action.get('control') == cid:
                owned_actions(dest)[aid] = reg.rebase(owned_actions(source).pop(aid), snapshot, snapshot)
                action_moves[aid] = rid
        links = [t for t in source['transitions'] if t.get('source_control') == cid]
        dest['transitions'].extend(links)
        source['transitions'] = [t for t in source['transitions'] if t.get('source_control') != cid]
    if not moved:
        return {}

    def rewrite(value):
        if isinstance(value, list):
            for v in value:
                rewrite(v)
        elif isinstance(value, dict):
            cid = value.get('control') or value.get('control_ref') or value.get('source_control')
            task = value.get('task') or value.get('task_name')
            aid = value.get('attempt') or value.get('action')
            target = (moved.get(cid) if isinstance(cid, str) else None) or (action_moves.get(aid) if isinstance(aid, str) else None)
            task_target = task_moves.get(task) if isinstance(task, str) else None
            if task_target and value.get('task_region') == source_id:
                value['task_region'] = task_target
            if task_target and value.get('region') == source_id and isinstance(value.get('task'), str):
                value['region'] = task_target
            if target:
                for key in ('region', 'region_ref', 'source_region'):
                    if value.get(key) == source_id:
                        value[key] = target
            for v in value.values():
                rewrite(v)
    for r in records.values():
        rewrite(r)
        for task in owned_tasks(r).values():
            rewrite(task)
        for action in owned_actions(r).values():
            rewrite(action)
    rewrite(state)
    invalid_functions = []
    for rid in {source_id, *moved.values()}:
        r = records[rid]
        if r.get('functions'):
            region_work(r).setdefault('prior_partition_functions', []).append(deepcopy(r['functions']))
        # A moved control invalidates only functions which depended on it.
        removed = [name for name, function in r.get('functions', {}).items()
                   if not function.get('support_controls') or any(
                       support.get('region') != rid or
                       support.get('control') not in owned_controls(r)
                       for support in function['support_controls'])]
        if removed:
            invalid_functions.append({'region': rid, 'remove': [
                {'ref': rid + '/' + name, 'reason': '区块归属调整后原功能支持不再属于本区块'}
                for name in removed]})
        if removed:
            region_work(r).pop('function_inventory', None)
        for task in owned_tasks(r).values():
            if task.get('equivalent_to') and task.get('equivalent_to') not in owned_tasks(r):
                task.update(status='blocked', equivalent_to='', blocker={'condition': 'review_required', 'reason': '区块细分后等价任务需要复核'})
    from regrow.records.function_updates import apply as update_functions
    update_functions(records, invalid_functions, {})
    source['partition_children'] = list(dict.fromkeys(source.get('partition_children', []) + list(targets.values())))
    unresolved = [cid for cid in refs if cid not in episode['assignments'] or cid in episode['conflicts']]
    region_work(source)['partition_review'] = {'status': 'partial' if unresolved else 'assigned', 'unassigned_controls': unresolved, 'conflicts': {cid: deepcopy(item) for cid, item in episode['conflicts'].items() if cid in refs}}
    active = state.get('active_task') or {}
    if active.get('region') == source_id and active.get('name') in task_moves:
        active['region'] = task_moves[active['name']]
    return moved

def run(root, transport, out, call):
    from regrow.traversal import step_repair as _step_repair
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.runtime import action_commands as _action_commands
    import jsonschema
    run = Path(transport.run)
    atomic = _step_repair.atomic
    pointer = json.loads((run / 'ownership_review.json').read_text())
    path = run / pointer['episode']
    episode = json.loads(path.read_text())
    resumed = resume_independent_target(root, run, episode, pointer['episode'])
    if resumed:
        episode.update(status='deferred', independent_registration=resumed['registration_call'])
        atomic(path, episode)
        (run / 'ownership_review.json').unlink()
        return resumed
    if episode.get('status') == 'deferred' and episode.get('independent_registration'):
        return {'status': 'correction_blocked', 'reason': '恢复登记回执与当前记录不对应；保留原断点待核对'}
    _, records, _ = _record_load(run)
    scope = review_scope(episode, records[episode['source_region']], run=run)
    if scope is None:
        return {'status': 'correction_blocked', 'reason': '旧归属复查缺少具体争议对象；保留原记录，不扩大核对范围'}
    episode.update(scope)
    atomic(path, episode)
    yielded = yield_unrelated(run, episode, pointer['episode'])
    if yielded:
        return yielded
    if episode.get('status') == 'blocked':
        return {'status': 'correction_blocked', 'reason': episode['reason']}
    if episode['actions'] and episode['actions'][-1]['status'] == 'dispatching':
        return {'status': 'execution_unconfirmed', 'reason': '归属复查动作投递结果待核对，不重复执行'}
    resumed_reply = bool(episode.get('pending_request'))
    if resumed_reply:
        q = episode['pending_request']
        frame = Path(q['screenshots'][0])
    else:
        frame = Path(out) / 'ownership-current.png'
        transport.screenshot(frame)
        q = request(root, run, episode, frame)
        episode['pending_request'] = q
        atomic(path, episode)
    from regrow.runtime.reply_correction import Failed
    try:
        (ref, reply) = call(q)
    except Failed as error:
        episode.update(status='blocked', reason=str(error))
        episode.pop('pending_request', None)
        atomic(path, episode)
        return {'status': 'correction_blocked', 'reason': str(error)}
    episode.pop('pending_request', None)
    from regrow.recognition.named_references import internal_request
    jsonschema.validate(reply, internal_request(q)['response_schema'])
    if not reply['reason'].strip():
        raise ValueError('ownership review needs reason')
    (_, records, _) = _record_load(run)
    record_observation(episode, reply, ref, frame, records)
    atomic(path, episode)
    if resumed_reply and reply['status'] == 'continue':
        return {'status': 'ready_next_round', 'reason': '原图归属观察已补齐，建议动作未执行；下一轮按当前截图继续复查'}
    if reply['status'] in ('resolved', 'defer'):
        if reply['action'] is not None:
            raise ValueError('finishing ownership review cannot execute an action')

        def mutate(records, state, snapshot, temp):
            if reply['status'] == 'resolved':
                repartition(records, state, episode, snapshot)
                unresolved = [cid for cid in scope['disputed_controls']
                              if cid not in episode['assignments'] or cid in episode['conflicts']]
                gaps = region_work(records[episode['source_region']]).setdefault('registration_gaps', {})
                if unresolved:
                    gaps['ownership_review'] = {'reason': reply['reason'], 'episode': pointer['episode'], 'controls': unresolved}
                elif gaps.get('ownership_review', {}).get('episode') == pointer['episode']:
                    gaps.pop('ownership_review')
            else:
                unresolved = [cid for cid in scope['disputed_controls']
                              if cid not in episode['assignments'] or cid in episode['conflicts']
                              or assignment_target(episode['assignments'][cid], records).get('ref') != episode['source_region']]
                region_work(records[episode['source_region']]).setdefault('registration_gaps', {})['ownership_review'] = {'reason': reply['reason'], 'episode': pointer['episode'], 'controls': unresolved}
            state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=str(frame), discovery_mode='relocate')
            state['correction_context'] = {'复查状态': reply['status'], '结论': reply['reason'], '本轮确认归属': reply['observed_assignments'], '依据截图': str(frame), '边界': '这是刚完成的复查结论；结合当前截图使用，不代表其他页面或未来观察永久成立。'}
        _record_publish(run, 'ownership-' + ref, mutate)
        episode.update(status=reply['status'], closing_call=ref)
        atomic(path, episode)
        (run / 'ownership_review.json').unlink()
        return {'status': 'ready_next_round', 'reason': '归属复查已保存；重新发现当前区块', 'calls': [ref]}
    if len(episode['actions']) >= 6:
        episode.update(status='deferred', reason='归属复查已观察第六步结果仍未完成；保留缺口')
        atomic(path, episode)

        def defer(records, state, *args):
            region_work(records[episode['source_region']]).setdefault('registration_gaps', {})['ownership_review'] = {'reason': episode['reason'], 'episode': pointer['episode']}
            state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=str(frame), discovery_mode='relocate')
        _record_publish(run, 'ownership-limit-' + ref, defer)
        (run / 'ownership_review.json').unlink()
        return {'status': 'ready_next_round', 'reason': episode['reason']}
    proposal = reply['action']
    if proposal is None:
        raise ValueError('继续实地复查需要一个导航或等待动作')
    _action_commands.validate(proposal, platform=getattr(transport, 'platform', 'android'))
    proposal = _action_commands.normalize(proposal)
    if proposal['action'] == 'none':
        raise ValueError('复查没有可执行动作时应填写 defer')
    if proposal.get('task_update') or proposal.get('request_task_review'):
        raise ValueError('归属复查动作不修改普通任务状态')
    row = {'call': ref, 'proposal': proposal, 'status': 'dispatching'}
    episode['actions'].append(row)
    atomic(path, episode)
    receipt = _action_commands.execute(transport, proposal, path.parent / ('action-' + ref))
    row.update(status='executed' if receipt.get('exit_code') == 0 else 'unconfirmed', receipt=receipt)
    atomic(path, episode)
    import time
    time.sleep(2)
    after = path.parent / ('after-' + ref + '.png')
    transport.screenshot(after)
    row['after'] = str(after)
    atomic(path, episode)
    return {'status': 'ready_next_round' if row['status'] == 'executed' else 'execution_unconfirmed', 'calls': [ref], 'reason': '归属复查动作已保存，下一轮核对新截图'}

def conflict(q, p, records, *, all_rows=False):
    ctx = q.get('discovery_context', {})
    errors = []
    if p.get('foreground', {}).get('exception') == 'region_ownership_review':
        rid = ctx.get('focus')
        if rid in records:
            return {'errors': [{'code': 'region_ownership_review', 'actual': {'region_id': rid}, 'reason': p['foreground'].get('recovery_handoff') or p['foreground'].get('description')}], 'unchecked': []}
    for index, c in enumerate(p.get('controls', [])):
        cid = ctx.get('control_names', {}).get(c.get('ref'), c.get('ref'))
        owners = [rid for (rid, r) in records.items() if cid and cid in owned_controls(r)]
        i = c.get('region_index')
        if len(owners) != 1 or not isinstance(i, int) or (not 0 <= i < len(p.get('regions', []))):
            continue
        dest = p['regions'][i]
        target = ctx.get('region_names', {}).get(dest.get('ref'), dest.get('ref'))
        if c.get('identity') == 'same' and target != owners[0]:
            errors.append({'code': 'region_ownership_review', 'path': f'/controls/{index}',
                           'actual': {'control_id': cid, 'region_id': owners[0]},
                           'reason': '拟划分区块改变旧控件归属，需要实地核对'})
            if not all_rows:
                return {'errors': errors, 'unchecked': []}
    return {'errors': errors, 'unchecked': []} if errors else None


def independent_target(run, q, p, pending, report):
    """Exclude disputed non-target rows; never move owners or execute a proposal."""
    from regrow.prompts.frame_context import primary
    frame = (Path(run) / primary(q)).resolve()
    if (frame != Path(pending['frame']).resolve()
            or q.get('discovery_context', {}).get('completion')
            or p.get('foreground', {}).get('exception', 'none') != 'none'):
        return None
    proposal = pending['proposal']
    x, y = proposal.get('x'), proposal.get('y')
    if type(x) not in (int, float) or type(y) not in (int, float):
        return None
    disputed = set()
    for error in report.get('errors', []):
        path = error.get('path', '').split('/')
        if len(path) != 3 or path[1] != 'controls' or not path[2].isdigit():
            return None
        disputed.add(int(path[2]))
        if proposal.get('target') == error['actual']['control_id']:
            return None
    targets = [i for i, control in enumerate(p['controls']) if appearance_box(control)
               and appearance_box(control)['left'] <= x < appearance_box(control)['right']
               and appearance_box(control)['top'] <= y < appearance_box(control)['bottom']]
    if len(targets) != 1 or targets[0] in disputed:
        return None
    target = p['controls'][targets[0]]
    from PIL import Image
    with Image.open(frame) as image:
        width, height = image.size
    b = appearance_box(target)
    if not (0 <= b['left'] < b['right'] <= width and 0 <= b['top'] < b['bottom'] <= height):
        return None
    ri = target.get('region_index')
    if target.get('identity') not in ('same', 'new') or type(ri) is not int:
        return None
    seen = set()
    while ri is not None:
        if isinstance(ri, str) and ri in _record_load(run)[1]:
            break  # An existing physical parent is not another proposal row.
        if type(ri) is not int or ri in seen or not 0 <= ri < len(p['regions']):
            return None
        seen.add(ri)
        owner = p['regions'][ri]
        if owner.get('identity') not in ('same', 'new'):
            return None
        ri = owner.get('parent_index')
    keep = [i for i in range(len(p['controls'])) if i not in disputed]
    accepted = deepcopy(p)
    accepted['controls'] = [accepted['controls'][i] for i in keep]
    return accepted, keep, targets[0]
