"""Resume archived result registration using its original execution evidence.

No model calls or GUI dispatch here. Later changes to affected Regions require
review rather than merging an old observation over newer knowledge.
"""
from copy import deepcopy
from pathlib import Path
import step_repair as repair


def context(run, attempt):
    path = Path(run)/'execution_pending.json'
    if not path.exists():return None
    execution = repair.read(path)
    return execution.get('suspended_recovery') if execution.get('attempt') == attempt else None


def restore_next(run, frame):
    run = Path(run)
    execution_path = run/'execution_pending.json'
    if execution_path.exists():
        execution = repair.read(execution_path)
        marker = execution.get('suspended_recovery')
        if not marker:return False
        pending = repair.pending(run)
        if pending and pending['path'] != marker['episode']:
            raise repair.Paused('execution_unconfirmed', '归档动作与活动步骤不一致；先核对原执行证据')
        job = repair.read(run/marker['episode'])
        _activate(run, job, {**marker, 'frame':str(Path(frame).resolve())}, execution)
        return pending is None
    if any((run/name).exists() for name in ('pending_step.json', 'visual_navigation_pending.json')):return False
    # Runtime projections may have been replaced by later updates. The original
    # archive and episode remain the durable source of this unfinished work.
    for pointer in sorted((run/'suspended_steps').glob('*/pending_step.json')):
        episode = repair.read(pointer)['episode']
        job = repair.read(run/episode)
        attempt = job.get('attempt')
        if job.get('stage') != 'update' or not attempt or job.get('status') != 'suspended':continue
        archive = pointer.parent
        evidence = job.get('branch_switch', {})
        if evidence.get('archive') != str(archive.relative_to(run)):continue
        folder = run/'action_attempts'/attempt
        execution_path = archive/'execution_pending.json'
        paths = [folder/name for name in ('receipt.json', 'before.png', 'after.png')]
        if not execution_path.exists() or not all(p.is_file() for p in paths):
            raise repair.Paused('execution_unconfirmed', '原动作执行证据不完整；保留归档，不补拍历史后图或重做GUI')
        execution = repair.read(execution_path)
        frames = job['request'].get('screenshots', [])
        expected = [(folder/name).resolve() for name in ('before.png', 'after.png')]
        if (execution.get('attempt') != attempt or repair.read(paths[0]).get('exit_code') != 0
                or [(run/p).resolve() for p in frames[:2]] != expected):
            raise repair.Paused('execution_unconfirmed', '原动作回执或前后图不匹配；保留执行证据')
        if (folder/'commit.json').exists():continue
        marker = {'episode':episode, 'archive':evidence['archive'], 'frame':str(Path(frame).resolve())}
        _activate(run, job, marker, execution)
        return True
    return False


def _activate(run, job, marker, execution):
    if job['status'] == 'suspended':
        job.setdefault('service_resume_history', []).append({'failure':job.pop('service_failure', None),
            'previous_status':job['status'], 'automatic_archive_resume':True})
        job.update(status='initial', candidate=None)
        job.pop('switch_trigger', None)
    job['suspended_recovery'] = marker
    # If interrupted after the first write, restore_next rejoins THIS episode,
    # including an already completed registration, instead of calling again.
    repair.atomic(Path(run)/'execution_pending.json', {**execution, 'suspended_recovery':marker})
    repair.atomic(Path(run)/job['path'], job)
    repair.atomic(Path(run)/'pending_step.json', {'episode':job['path']})


def validate_commit(run, attempt, reply, request, binding, snapshot, records):
    marker = context(run, attempt)
    if not marker:return None
    reg = repair.helper('register_update')
    baseline = Path(run)/repair.read(Path(run)/marker['archive']/'decision.json')['knowledge']['snapshot']
    if reply.get('source_region_split'):
        raise repair.Paused('historical_update_conflict', '历史补登记涉及来源拆分；保留原动作，需独立核对')
    affected = {binding.get('region_ref'), binding.get('task_region'), binding.get('working_region')}
    names = dict(request.get('region_names', {}))
    for rid, region in records.items():names.setdefault(region['name'], rid)
    for row in reply.get('regions', []) + reply.get('previous_regions', []):
        name = row.get('previous_name') or row.get('name')
        if name in names:affected.add(names[name])
    for row in reply.get('dependency_updates', []):
        rid = names.get(row['region']);affected.add(rid)
        task = records.get(rid, {}).get('tasks', {}).get(row['task'], {})
        affected.add(task.get('prerequisite', {}).get('scheduled', {}).get('region'))
    for rid in affected - {None}:
        path = baseline/'regions'/rid/'region.json'
        if not path.exists() or rid not in records:
            raise repair.Paused('historical_update_conflict', '历史补登记相关区块已变化；保留原结果')
        old = reg.rebase(repair.read(path), path.parent, Path(run))
        current = reg.rebase(records[rid], Path(snapshot)/'regions'/rid, Path(run))
        if old != current:
            raise repair.Paused('historical_update_conflict', '历史补登记相关区块已有后续变化：'+rid+'；不能用旧结果覆盖')
    settled = [[binding.get('task_region') or binding.get('region_ref'), binding.get('task_name')]]
    settled += [[binding.get('region_ref'), row['name']] for row in reply.get('related_task_results', [])]
    return {**marker, 'settled_tasks':settled}


def complete(records, previous, state, marker, call, attempt):
    """Called inside the normal immutable snapshot publication, never after it."""
    episode = marker['episode']
    def owned(value):
        return value.get('episode') == episode and value.get('archive') == marker['archive']
    for region in records.values():
        gaps = region.get('registration_gaps', {})
        if owned(gaps.get('suspended_branch', {})):
            gap = gaps.pop('suspended_branch')
            region.setdefault('registration_gap_history', []).append({**gap, 'resolved_by':call})
        for name, task in region.get('tasks', {}).items():
            if not owned(task.get('deferral', {})):continue
            blocker = task.get('blocker', {})
            if blocker != {'condition':'review_required'}:continue
            task.setdefault('deferral_history', []).append({**task.pop('deferral'), 'resolved_by':call})
            task.setdefault('blocker_history', []).append(task.pop('blocker'))
            if task['status'] == 'blocked':
                if [region['id'], name] in marker.get('settled_tasks', []):
                    task['blocker'] = {'condition':'review_required', 'attempt':attempt,
                        'source_call':call, 'reason':task.get('result_evidence', '结果仍未确认')}
                else:task['status'] = 'pending'
    metadata = {key:state[key] for key in ('update_status', 'update_digest')}
    state.clear();state.update(deepcopy(previous));state.update(metadata)
    queue = state.pop('suspended_updates', [])
    remaining = [item for item in queue if not owned(item)]
    if remaining:state['suspended_updates'] = remaining
    resolved = next((item for item in queue if owned(item)), {'episode':episode, 'archive':marker['archive']})
    state.setdefault('suspended_update_history', []).append({**resolved, 'attempt':attempt,
        'status':'resolved', 'resolved_by':call})
    # Historical facts are committed, but their saved after-image is not a claim
    # about today's position. Preserve the independent goal and reobserve first.
    state.update(next_action_mode='discover', phase='awaiting_discovery', discovery_mode='relocate',
        observation=None, interactive_regions=[], pending_frame=marker['frame'],
        reason='historical_update_registered', execution_status='not_started')
    state.pop('visual_navigation', None)
