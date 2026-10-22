from regrow.records.object_store import region_work
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_tasks
from regrow.records import object_store as object_store
'Resume archived result registration using its original execution evidence.\n\nNo model calls or GUI dispatch here. Later changes to affected Regions require\nreview rather than merging an old observation over newer knowledge.\n'
from copy import deepcopy
from pathlib import Path
from regrow.traversal import step_repair as repair

def archive_pending(run, name, frame=None):
    """Use the existing suspended-step layout; original execution files stay put."""
    import shutil
    run = Path(run)
    folder = run / 'suspended_steps' / name
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copy2(run / 'pending_step.json', folder / 'pending_step.json')
    if (run / 'execution_pending.json').exists():
        shutil.copy2(run / 'execution_pending.json', folder / 'execution_pending.json')
    if frame is not None:
        shutil.copy2(frame, folder / 'current.png')
    return folder


def defer_result(run, job, reason):
    """Keep an unregistered execution as a gap; resume current-scene discovery."""
    from regrow.records.snapshots import load, publish
    run = Path(run)
    attempt = job.get('attempt')
    execution = run / 'execution_pending.json'
    pointer = run / 'pending_step.json'
    if job['stage'] != 'update' or not attempt or not execution.exists() or not pointer.exists():
        return None
    if repair.read(execution).get('attempt') != attempt or repair.read(pointer).get('episode') != job['path']:
        return None
    folder = run / 'action_attempts' / attempt
    if not all((folder / name).is_file() for name in ('receipt.json', 'binding.json', 'before.png', 'after.png')):
        return None
    binding = repair.read(folder / 'binding.json')
    _, records, _ = load(run)
    rid = binding.get('task_region') or binding['region_ref']
    name = binding.get('task_name')
    if rid not in records:
        return None
    archive = archive_pending(run, 'result-' + Path(job['path']).parent.name)
    evidence = {'episode': job['path'], 'attempt': attempt, 'failed_call': job.get('call'),
                'reason': reason, 'status': 'unresolved', 'archive': str(archive.relative_to(run))}
    def mutate(records, state, *_):
        region_work(records[rid]).setdefault('registration_gaps', {})['suspended_branch'] = evidence
        task = owned_tasks(records[rid]).get(name)
        if task is not None:
            task.update(status='blocked', deferral=evidence,
                        blocker={'condition': 'result_registration_pending'})
        state.setdefault('suspended_updates', []).append(evidence)
        state.update(next_action_mode='discover', discovery_mode='relocate',
                     phase='awaiting_discovery', interactive_regions=[], observation=None,
                     pending_frame=str((folder / 'after.png').relative_to(run)),
                     reason='result_registration_deferred')
        for key in ('active_task', 'inspection_region', 'required_control', 'deferred_routing_target', 'navigation_handoff'):
            state.pop(key, None)
    knowledge = publish(run, 'defer-result-' + Path(job['path']).parent.name, mutate)
    repair.atomic(archive / 'decision.json', {'knowledge': knowledge, 'evidence': evidence})
    # 'deferred' is deliberately not the auto-resumed 'suspended' service state.
    job.update(status='deferred', deferred_result=evidence)
    repair.atomic(run / job['path'], job)
    execution.unlink()
    return {'region': rid, 'task': name, 'stage': 'update', 'reason': reason,
            'archive': evidence['archive'], 'next': {'stage': 'discovery', 'region': rid}}


def context(run, attempt):
    path = Path(run) / 'execution_pending.json'
    if not path.exists():
        return None
    execution = repair.read(path)
    return execution.get('suspended_recovery') if execution.get('attempt') == attempt else None

def restore_next(run, frame):
    run = Path(run)
    execution_path = run / 'execution_pending.json'
    if execution_path.exists():
        execution = repair.read(execution_path)
        marker = execution.get('suspended_recovery')
        if not marker:
            return False
        pending = repair.pending(run)
        if pending and pending['path'] != marker['episode']:
            raise repair.Paused('execution_unconfirmed', '归档动作与活动步骤不一致；先核对原执行证据')
        job = repair.read(run / marker['episode'])
        _activate(run, job, {**marker, 'frame': str(Path(frame).resolve())}, execution)
        return pending is None
    if any(((run / name).exists() for name in ('pending_step.json', 'visual_navigation_pending.json'))):
        return False
    for pointer in sorted((run / 'suspended_steps').glob('*/pending_step.json')):
        episode = repair.read(pointer)['episode']
        job = repair.read(run / episode)
        attempt = job.get('attempt')
        if job.get('stage') != 'update' or not attempt or job.get('status') != 'suspended':
            continue
        archive = pointer.parent
        evidence = job.get('branch_switch', {})
        if evidence.get('archive') != str(archive.relative_to(run)):
            continue
        folder = run / 'action_attempts' / attempt
        execution_path = archive / 'execution_pending.json'
        paths = [folder / name for name in ('receipt.json', 'before.png', 'after.png')]
        if not execution_path.exists() or not all((p.is_file() for p in paths)):
            raise repair.Paused('execution_unconfirmed', '原动作执行证据不完整；保留归档，不补拍历史后图或重做GUI')
        execution = repair.read(execution_path)
        from regrow.prompts.frame_context import primary
        after = primary(job['request'])
        expected = [(folder / name).resolve() for name in ('before.png', 'after.png')]
        if execution.get('attempt') != attempt or repair.read(paths[0]).get('exit_code') != 0 or (not after) or ((run / after).resolve() != expected[1]):
            raise repair.Paused('execution_unconfirmed', '原动作回执或前后图不匹配；保留执行证据')
        if (folder / 'commit.json').exists():
            continue
        marker = {'episode': episode, 'archive': evidence['archive'], 'frame': str(Path(frame).resolve())}
        _activate(run, job, marker, execution)
        return True
    return False

def _activate(run, job, marker, execution):
    if job['status'] == 'suspended':
        job.setdefault('service_resume_history', []).append({'failure': job.pop('service_failure', None), 'previous_status': job['status'], 'automatic_archive_resume': True})
        job.update(status='initial', candidate=None)
        job.pop('switch_trigger', None)
    job['suspended_recovery'] = marker
    repair.atomic(Path(run) / 'execution_pending.json', {**execution, 'suspended_recovery': marker})
    repair.atomic(Path(run) / job['path'], job)
    repair.atomic(Path(run) / 'pending_step.json', {'episode': job['path']})

def validate_commit(run, attempt, reply, request, binding, snapshot, records):
    from regrow.traversal import register_update as _register_update
    marker = context(run, attempt)
    if not marker:
        return None
    reg = _register_update
    baseline = Path(run) / repair.read(Path(run) / marker['archive'] / 'decision.json')['knowledge']['snapshot']
    if reply.get('source_region_split'):
        raise repair.Paused('historical_update_conflict', '历史补登记涉及来源拆分；保留原动作，需独立核对')
    affected = {binding.get('region_ref'), binding.get('task_region'), binding.get('working_region')}
    names = dict(request.get('region_names', {}))
    for (rid, region) in records.items():
        names.setdefault(region['name'], rid)
    for row in reply.get('regions', []) + reply.get('previous_regions', []):
        name = row.get('ref') or row.get('name')
        if name in names:
            affected.add(names[name])
    for row in reply.get('dependency_updates', []):
        rid = names.get(row['region'])
        affected.add(rid)
        task = owned_tasks(records.get(rid, {})).get(row['task'], {})
        affected.add(task.get('prerequisite', {}).get('scheduled', {}).get('region'))
    from regrow.records.task_settlement import completion_target
    for (rid, region) in records.items():
        if any((completion_target(region, t).get('region') == binding.get('region_ref') and completion_target(region, t).get('control') == binding.get('control_ref') for t in owned_tasks(region).values())):
            affected.add(rid)
    updates = reply.get('task_update') or {}
    for row in updates if isinstance(updates, list) else [updates]:
        followup = row.get('next_action')
        if followup:
            affected.add(names.get(followup['region']))
    for row in request.get('task_update_candidates', []):
        affected.add(row['region'])
    baseline_records = object_store.load(baseline)
    for rid in affected - {None}:
        if rid not in baseline_records or rid not in records:
            raise repair.Paused('historical_update_conflict', '历史补登记相关区块已变化；保留原结果')
        old = reg.rebase(baseline_records[rid], baseline, Path(run))
        current = reg.rebase(records[rid], Path(snapshot), Path(run))
        if old != current:
            raise repair.Paused('historical_update_conflict', '历史补登记相关区块已有后续变化：' + rid + '；不能用旧结果覆盖')
    settled = [[binding.get('task_region') or binding.get('region_ref'), binding.get('task_name')]]
    return {**marker, 'settled_tasks': settled}

def complete(records, previous, state, marker, call, attempt):
    """Called inside the normal immutable snapshot publication, never after it."""
    episode = marker['episode']

    def owned(value):
        return value.get('episode') == episode and value.get('archive') == marker['archive']
    for region in records.values():
        gaps = region_work(region).get('registration_gaps', {})
        if owned(gaps.get('suspended_branch', {})):
            gap = gaps.pop('suspended_branch')
            region_work(region).setdefault('registration_gap_history', []).append({**gap, 'resolved_by': call})
        for (name, task) in owned_tasks(region).items():
            if not owned(task.get('deferral', {})):
                continue
            blocker = task.get('blocker', {})
            if blocker != {'condition': 'review_required'}:
                continue
            task_audit(task).setdefault('deferral_history', []).append({**task.pop('deferral'), 'resolved_by': call})
            task_audit(task).setdefault('blocker_history', []).append(task.pop('blocker'))
            if task['status'] == 'blocked':
                task['status'] = 'pending'
    from regrow.records.task_settlement import reconcile
    reconcile(records)
    metadata = {key: state[key] for key in ('update_status', 'update_digest')}
    state.clear()
    state.update(deepcopy(previous))
    state.update(metadata)
    queue = state.pop('suspended_updates', [])
    remaining = [item for item in queue if not owned(item)]
    if remaining:
        state['suspended_updates'] = remaining
    resolved = next((item for item in queue if owned(item)), {'episode': episode, 'archive': marker['archive']})
    state.setdefault('suspended_update_history', []).append({**resolved, 'attempt': attempt, 'status': 'resolved', 'resolved_by': call})
    state.update(next_action_mode='discover', phase='awaiting_discovery', discovery_mode='relocate', observation=None, interactive_regions=[], pending_frame=marker['frame'], reason='historical_update_registered', execution_status='not_started')
    state.pop('visual_navigation', None)
