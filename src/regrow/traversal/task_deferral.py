from regrow.records.observations import frame_observation
from regrow.records.tasks import in_scope as _record_in_scope
from regrow.records.tasks import coverage as _record_coverage
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
'Isolate local repair gaps using existing blocked tasks and observed routes.'
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path

def pending_tasks(region, records=None):
    if region_work(region).get('out_of_scope_reason') or scope_review_pending(region):
        return []
    return [(n, t) for (n, t) in owned_tasks(region).items() if t.get('status') == 'pending' and (not t.get('equivalent_to')) and _record_in_scope(region, t, records)]

def choose(records, state):
    """Prefer other observed local entries, then shortest verified outbound route."""
    from regrow.traversal import action_context as _stepwise_flow
    if state.get('next_action_mode') != 'explore' or not state.get('observation'):
        return None
    refs = state['interactive_regions']
    active = state.get('active_task') or {}
    if active.get('region') in refs and any(
            name == active.get('name') for name, _ in pending_tasks(records[active['region']], records)):
        return {'region': active['region'], 'task': active['name'], 'route': []}
    ordered = sorted(refs, key=lambda r: r != state.get('working_region'))
    for rid in ordered:
        names = [n for (n, t) in pending_tasks(records[rid], records)]
        if names:
            return {'region': rid, 'task': names[0], 'route': []}
    choices = []
    flow = _stepwise_flow
    for (rid, r) in records.items():
        if rid in refs or not pending_tasks(r, records):
            continue
        path = flow.shortest_known_path(records, state, rid)
        choices.append({'region': rid, 'task': pending_tasks(r, records)[0][0], 'route': path})
    return min(choices, key=lambda c: (not bool(c['route']), len(c['route'] or []))) if choices else None


def yield_pending(run, job):
    """Keep unrelated unexecuted work without occupying the next task."""
    stage = job.get('stage')
    if (stage not in ('action', 'task_proposal', 'function_registration',
                      'task_result_review', 'shared_control_review')
            or job.get('attempt') or (Path(run) / 'execution_pending.json').exists()
            or job.get('status') in ('complete', 'deferred')):
        return False
    if (stage == 'task_result_review' and job.get('status') == 'initial'
            and not job.get('service_failure') and job.get('service_resume_history')
            and job['service_resume_history'][-1].get('explicit_retry')):
        return False
    from regrow.traversal.traversal_scheduler import select_work, reviews_task
    _, records, state = _record_load(run)
    decision = select_work(records, state)
    task = decision.get('task')
    if decision['kind'] != 'action' or not task:
        return False
    if reviews_task(records[task['region']], task):
        return False
    q = job['request']
    if q.get('task_scope_review') or q.get('external_scope_review'):
        return False
    if stage in ('action', 'task_result_review'):
        source = q.get('source', {})
        reviewed = {'region': source.get('task_region') or source.get('region'),
                    'name': source.get('task_name')}
        selected = owned_tasks(records[task['region']])[task['name']]
        dependency = selected.get('prerequisite', {}).get('scheduled', {})
        preparation = selected.get('prepares', {})
        reviewed_task = owned_tasks(records.get(reviewed['region'], {})).get(reviewed['name'], {})
        supports = reviewed_task.get('prepares', {})
        if (reviewed == task or reviewed == {'region': dependency.get('region'), 'name': dependency.get('task')}
                or reviewed == {'region': preparation.get('region'), 'name': preparation.get('task')}
                or task == {'region': supports.get('region'), 'name': supports.get('task')}):
            return False
    elif stage == 'shared_control_review':
        from regrow.records.shared_control_review import relevant
        case = q.get('shared_control_conflict', {})
        group = records.get(case.get('owner'), {}).get('shared_controls', {}).get(case.get('name'))
        scope = {'role': 'action_selection', 'source': {
            'region': decision['region'], 'task_region': task['region'], 'task_name': task['name']}}
        if group and relevant(group, scope, records):
            return False
    from regrow.traversal.step_repair import atomic
    from regrow.runtime.reply_correction import abandon
    reason = '已有可推进任务；其他未执行步骤或复核保留，稍后处理。'
    decision = defer(run, job, reason, selected_task=task)
    if not decision or not decision.get('next'):
        return False
    abandon(run, reason)
    job.update(status='deferred', deferral=decision)
    job.setdefault('history', []).append({'framework': 'yield_pending_to_existing_task', 'reason': reason})
    atomic(Path(run) / job['path'], job)
    (Path(run) / 'pending_step.json').unlink()
    return True

yield_planning = yield_pending

def defer(run, job, reason, *, selected_task=None, retry_when=None):
    """Return None when the failure cannot be isolated without trusting new facts."""
    from regrow.traversal import discovery_step as _discovery_step
    if job['stage'] == 'update' and job.get('attempt'):
        from regrow.traversal.suspended_updates import defer_result
        return defer_result(run, job, reason)
    if job.get('attempt') or (Path(run) / 'execution_pending.json').exists():
        return None
    stage = job['stage']
    if stage not in ('action', 'task_proposal', 'function_registration', 'task_result_review', 'shared_control_review'):
        return None
    if stage == 'shared_control_review' and selected_task is None:
        return None
    discovery = _discovery_step
    (_, records, state) = _record_load(run)
    q = job['request']
    source = q.get('source', {})
    rid = (q.get('shared_control_conflict', {}).get('owner') if stage == 'shared_control_review'
           else source.get('task_region') or source.get('region'))
    obs = state.get('observation') or {}
    visible = state.get('interactive_regions', [])
    if rid not in records:
        return None
    name = source.get('task_name')
    if stage in ('action', 'task_result_review'):
        statuses = ('pending', 'blocked') if stage == 'task_result_review' or selected_task or retry_when else ('pending',)
        if name not in owned_tasks(records[rid]) or owned_tasks(records[rid])[name].get('status') not in statuses:
            return None
    episode = job['path']
    decision = {}
    blocked_by = job.get('blocked_by', 'none')
    blocked_by = state.get('exception') if state.get('exception') not in (None, 'none') else blocked_by
    exception = blocked_by if blocked_by in ('blocking_popup', 'system_error', 'unexpected_exit', 'external_app') else None
    condition = 'foreground_exception' if exception else 'control_not_visible' if blocked_by == 'control_not_visible' or q.get('needs_task_inspection') else 'review_required'

    def mutate(records, state, snapshot, temp):
        region = records[rid]
        evidence = {'reason': reason, 'episode': episode, 'observation': obs.get('id'), 'source_call': job.get('call'), 'stage': stage}
        origin = q.get('action_source', {})
        if origin.get('call') == job.get('call'):
            evidence['source_field'] = origin['field']
        failure = job.get('service_failure')
        if failure:
            evidence.update(source_call=failure['call'], trigger={'kind': 'model_service_error', **deepcopy(failure)})
        if stage in ('action', 'task_result_review'):
            task = owned_tasks(region)[name]
            retained_blocker = None
            if stage == 'task_result_review' or task.get('status') == 'blocked':
                if task.get('blocker', {}).get('condition') not in (None, 'review_required'):
                    retained_blocker = deepcopy(task['blocker'])
                for field in ('blocker', 'deferral'):
                    if task.get(field):
                        task_audit(task).setdefault(field + '_history', []).append(deepcopy(task[field]))
            task.update(status='blocked', deferral={**evidence, 'retry_when': 'explicit_service_retry' if failure else retry_when or 'new_localized_control_observation'}, blocker={'condition': condition, 'source_call': evidence['source_call'], 'episode': episode, **({'exception': exception} if exception else {})})
            if retained_blocker:
                task['blocker'] = retained_blocker
            if state.get('active_task') == {'region': rid, 'name': name}:
                state.pop('active_task', None)
        elif stage != 'shared_control_review':
            if stage == 'function_registration':
                from regrow.traversal.region_functions import signature
                evidence['evidence_digest'] = signature(region, records)
            if stage == 'task_proposal' and scope_review_pending(region):
                evidence['scope_change'] = region_work(region)['task_inventory']['review']['change']
                evidence['controls'] = list(owned_controls(region))
            region_work(region).setdefault('registration_gaps', {})[stage] = evidence
        if exception:
            state.update(next_action_mode='recover', exception=exception, recovery_handoff=reason, source_call=job.get('call'))
            decision.update(region=rid, task=name, stage=stage, next={'stage': 'recovery'}, reason=reason)
            return
        state.update(next_action_mode='explore', phase='ready_for_next_action')
        selection = ({'region': selected_task['region'], 'task': selected_task['name'], 'route': []}
                     if selected_task else choose(records, state) or choose_unfinished(records, state))
        if selection is None:
            local = pending_tasks(region, records)
            selection = {'region': rid, 'task': local[0][0], 'route': []} if local else None
        if selection and not obs.get('id'):
            state.update(next_action_mode='discover', discovery_mode='relocate')
        if selection:
            state['working_region'] = selection['region']
            if selection.get('task'):
                state['active_task'] = {'region': selection['region'], 'name': selection['task']}
            else:
                state.pop('active_task', None)
            if selection['region'] not in state.get('interactive_regions', []):
                state['deferred_routing_target'] = selection['region']
            else:
                state.pop('deferred_routing_target', None)
        decision.update(region=rid, task=name, stage=stage, next=selection, reason=reason)
    _record_publish(run, 'defer-' + Path(episode).parent.name, mutate)
    return decision

def resume_localized(records, refs, call, foreground=None, *, run=None, frame=None, snapshot=None, retry_targets=None):
    """Only a new observation of the task's object can release its repair gap."""
    for rid, region in records.items():
        for name, task in owned_tasks(region).items():
            if task.get('status') != 'blocked':
                continue
            target_retry = task.get('deferral', {}).get('retry_when') == 'target_identity_or_changed_surface'
            if retry_targets is not None and (not target_retry or (rid, name) not in retry_targets
                    or task['deferral'].get('source_call') != retry_targets[rid, name]):
                continue
            if rid not in refs and not target_retry:
                continue
            if task.get('deferral', {}).get('retry_when') == 'explicit_service_retry':
                continue
            blocker = task.get('blocker')
            if blocker:
                if blocker.get('exception') == 'unexpected_exit':
                    continue
                condition = blocker['condition']
                if condition == 'foreground_exception':
                    if not foreground or foreground.get('exception') != 'none':
                        continue
                elif condition != 'control_not_visible' and not (
                        condition == 'review_required' and task.get('deferral', {}).get('stage') in ('action', 'task_result_review')):
                    continue
            elif task.get('equivalent_to') or not task.get('deferral'):
                continue
            if target_retry:
                from regrow.traversal.target_registration import retry_evidence
                if run is None or frame is None or not retry_evidence(run, records, task, call, frame, snapshot):
                    continue
                trigger = {'kind': 'observation', 'source_call': call, 'frame': str(frame)}
            else:
                control = owned_controls(region).get(task.get('control'), {}) if task.get('control') else region
                if not observation_history(control):
                    continue
                latest = frame_observation(control, kind='controls' if task.get('control') else 'regions', call=call)
                if (task.get('deferral', {}).get('stage') in ('action', 'task_result_review')
                        and latest.get('evidence', {}).get('observation') == task['deferral'].get('observation')):
                    continue
                accepted_object = task.get('deferral', {}).get('stage') in ('action', 'task_result_review')
                if not ((latest.get('image') or accepted_object) and latest.get('evidence', {}).get('source_call') == call):
                    continue
                trigger = {'kind': 'observation', 'source_call': call, 'observation': latest.get('evidence', {}).get('observation')}
            task.setdefault('deferral', {})['trigger'] = trigger
            if blocker:
                task_audit(task).setdefault('blocker_history', []).append({**blocker, 'resolved_by': call})
                task.pop('blocker', None)
            if task.get('deferral', {}).get('stage') == 'action':
                task.update(status='pending')

def scope_review_pending(region):
    return region_work(region).get('task_inventory', {}).get('review', {}).get('kind') == 'scope_change'


def inventory_evidence_changed(region):
    from regrow.records.tasks import proposal_gap, new_scope_controls
    gap = proposal_gap(region)
    if not gap:
        return True
    if gap.get('recheck_after'):
        return True
    inventory = region_work(region).get('task_inventory', {})
    if scope_review_pending(region):
        if inventory['review'].get('change') != gap.get('scope_change'):
            return True
        if set(owned_controls(region)) != set(gap.get('controls', [])):
            return True
        return any(str(row.get('evidence', {}).get('source_call') or '') > str(gap.get('source_call') or '')
                   and row.get('evidence', {}).get('observation') != gap.get('observation')
                   for row in observation_history(region))
    if new_scope_controls(region):
        return True
    review = inventory.get('review') or {}
    source = str(gap.get('source_call') or '')
    if review.get('reason') and str(review.get('source_call') or '') > source:
        return True
    from regrow.records.object_store import owned_actions
    return any(str(a.get('evidence', {}).get('result_call') or '') > source
               and a.get('result', {}).get('exception') == 'none'
               for a in owned_actions(region).values())

def runnable(region, records=None):
    """A failed registration stage is not a ban on the Region's other work."""
    if region_work(region).get('out_of_scope_reason'):
        return False
    if scope_review_pending(region):
        return inventory_evidence_changed(region)
    if pending_tasks(region, records):
        return True
    progress = _record_coverage(region, records)
    if progress['inventory_complete']:
        return False
    return inventory_evidence_changed(region)

def choose_unfinished(records, state):
    """Select known unfinished Regions, including those without task inventories."""
    from regrow.traversal import action_context as _stepwise_flow
    if state.get('next_action_mode') not in ('explore', 'discover'):
        return None
    coverage = _record_coverage
    flow = _stepwise_flow
    current = state.get('working_region')
    choices = []
    for (rid, region) in records.items():
        if rid == current or not runnable(region, records):
            continue
        visible = rid in state.get('interactive_regions', [])
        route = [] if visible else flow.shortest_known_path(records, state, rid)
        choices.append({'region': rid, 'route': route, 'rank': (0 if any((t.get('prepares') and t.get('status') == 'pending' for t in owned_tasks(region).values())) else 1, 0 if visible else 1 if route else 2, len(route) if route else 0)})
    return min(choices, key=lambda c: c['rank']) if choices else None

def advance_unfinished(run):
    from regrow.traversal import discovery_step as _discovery_step
    discovery = _discovery_step
    (_, records, state) = _record_load(run)
    selection = choose_unfinished(records, state)
    if not selection:
        return None
    import uuid

    def mutate(records, state, *args):
        target = selection['region']
        state['working_region'] = target
        state.pop('active_task', None)
        state.pop('navigation_handoff', None)
        if state.get('next_action_mode') == 'discover':
            state.pop('inspection_region', None)
            state.pop('required_control', None)
            state['discovery_mode'] = 'relocate'
        if target not in state.get('interactive_regions', []):
            state['deferred_routing_target'] = target
        else:
            state.pop('deferred_routing_target', None)
    _record_publish(run, 'frontier-' + uuid.uuid4().hex, mutate)
    return selection
