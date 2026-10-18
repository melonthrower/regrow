from regrow.records.tasks import in_scope as _record_in_scope
from regrow.records.tasks import coverage as _record_coverage
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import region_work
'Choose work from committed facts; request renderers do not decide session exits.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.traversal import step_repair as step_repair
from regrow.records.tasks import coverage

def handoff_no_action(run, request, proposal, call, frame):
    """Continue the original work from registered facts, without a fake action."""
    from pathlib import Path
    from regrow.records import page_context as page_context
    from regrow.traversal.work_context import from_request
    if (Path(run) / 'execution_pending.json').exists():
        raise ValueError('未结算的真实动作必须先登记，不能用none跳过')
    (_, records, state) = _record_load(run)
    work = from_request(request, records, state)
    source = request.get('source', {})
    frame = (request.get('screenshots') or request.get('image_refs') or [str(frame)])[0]
    result = {}

    def mutate(records, state, *_):
        from regrow.records import task_settlement as _task_settlement
        from regrow.records import task_updates as _task_updates
        from regrow.records import entry_observation as _entry_observation
        from regrow.traversal import parameter_evidence_review as _parameter_evidence_review
        _task_settlement.reconcile(records)
        task_ref = work.get('task')
        if proposal.get('task_update'):
            if not task_ref:
                raise ValueError('本次没有控件任务，不能伪造task_update')
            owner = records[task_ref['region']]
            task = owned_tasks(owner)[task_ref['name']]
            updates = _task_updates
            evidence = updates.answer_evidence(run, request, owner, task, state)
            observed = bool(evidence)
            basis = {**(evidence or {'basis':'observation_only'}), 'source_call': call}
            updates.store_increment(owner, task, task_ref['name'], proposal['task_update'], records, state, basis, observed=observed)
            if task['status'] != 'pending' and state.get('active_task') == task_ref:
                state.pop('active_task', None)
            result['handoff'] = 'explicit_task_update'
            return
        task = owned_tasks(records.get((task_ref or {}).get('region'), {})).get((task_ref or {}).get('name'), {})
        if task_ref and task.get('status') in ('done', 'record_only', 'blocked'):
            if state.get('active_task') == task_ref:
                state.pop('active_task', None)
            result['handoff'] = 'registered_task_state'
            return
        target = work.get('region') or source.get('working_region') or state.get('working_region')
        if target in records:
            state['working_region'] = target
        if task_ref and task.get('status') == 'pending':
            state['active_task'] = dict(task_ref)
        observation = state.get('observation') or {}
        digest = page_context._digest(Path(run) / frame)
        current = bool(digest and digest == page_context._digest(Path(run) / observation.get('image', '')) and (source.get('observation') == observation.get('id')) and (observation.get('foreground', {}).get('exception', 'none') == 'none'))
        if work.get('kind') == 'navigate' and current and (target in state.get('interactive_regions', [])):
            state.update(next_action_mode='explore', phase='ready_for_next_action')
            state.pop('inspection_region', None)
            state.pop('required_control', None)
            result['handoff'] = 'observed_navigation_target'
            return
        if _entry_observation.request_review(records, state, request, proposal):
            result['handoff'] = 'entry_observation'
            return
        if _parameter_evidence_review.from_no_action(run, records, state, request, proposal, call):
            result['handoff'] = 'parameter_facts'
            return
        state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=frame, discovery_mode='relocate', correction_context='动作选择未执行（来源调用 ' + call + '）；保留原目标核对具体缺口：' + proposal['reason'])
        state.pop('inspection_region', None)
        state.pop('required_control', None)
        result['handoff'] = 'observe_original_work'
    _record_publish(run, 'no-action-' + call, mutate)
    return result

def select_work(records, state, working=None):
    """Return a read-only work decision, without constructing a model request."""
    from regrow.traversal import region_functions as _region_functions
    from regrow.traversal import task_prerequisites as _task_prerequisites
    from regrow.records import task_settlement as _task_settlement
    from regrow.traversal import inventory_scroll as _inventory_scroll
    from regrow.traversal import task_deferral as _task_deferral
    from regrow.traversal import task_routing as _task_routing
    working = working or state.get('working_region')
    mode = state.get('next_action_mode')

    def choice(kind, region=working, **fields):
        return {'kind': kind, 'region': region, 'working_region': working, **fields}
    if mode == 'discover':
        return choice('locate', reason='current observation needs discovery')
    if mode in ('recover', 'recover_scope', 'review_result'):
        return choice('recover', reason='registered foreground requires recovery')
    if mode != 'explore':
        return choice('wait', reason='registered mode does not permit exploration')
    summary = _region_functions.next_ready(records, state)
    if summary:
        return choice('function_registration', summary, reason='summarize completed Region exploration from its accumulated evidence')
    refs = state.get('interactive_regions', [])
    allowed = [rid for rid in refs if rid in records and (not region_work(records[rid]).get('out_of_scope_reason'))]
    active = state.get('active_task') or {}
    owner = active.get('region')
    task = owned_tasks(records.get(owner, {})).get(active.get('name'))
    if not task or task.get('status') != 'pending' or (not _record_in_scope(records[owner], task, records)):
        task = None
    in_progress = bool(task and (task_value(task, 'attempts') or task.get('task_type') == 'parameter' or task.get('control') is None))
    target = _task_settlement.completion_target(records[owner], task) if task else {}
    local_continuation = in_progress and target.get('region') in allowed
    scroll_target = _inventory_scroll.target(records, state)
    if scroll_target and scroll_target not in refs:
        return choice('navigate', scroll_target, reason='reach the pending inventory scroll')
    if local_continuation:
        rid = target['region']
    elif working not in refs and working in records and _task_deferral.runnable(records[working], records):
        if in_progress and allowed:
            rid = allowed[0]
        else:
            return choice('navigate', working, reason='reach in-scope unfinished work')
    else:
        rid = scroll_target or (working if working in allowed else next((ref for ref in allowed if _task_deferral.runnable(records[ref], records)), allowed[0] if allowed else None))
    if rid is not None:
        region = records[rid]
        progress = coverage(region, records)
        if region_work(region).get('task_inventory', {}).get('review', {}).get('kind') in ('parameter_facts', 'entry_observation'):
            return choice('task_proposal', rid, reason='register current evidence before another action')
        continuation = task is not None and (rid == owner or in_progress)
        if continuation:
            return choice('action', rid, task=dict(active), source_regions=list(allowed), reason='continue the existing task on its current surface')
        gap = region_work(region).get('registration_gaps', {}).get('task_proposal', {})
        if not progress['inventory_complete'] and (not progress['pending']) and _task_deferral.inventory_evidence_changed(region):
            return choice('task_proposal', rid, reason='prepare tasks for observed controls')
        pending = [name for name in progress['pending'] if not owned_tasks(region)[name].get('equivalent_to')]
        visible = set((state.get('observation') or {}).get('control_refs', []))
        names = [name for name in pending if not owned_tasks(region)[name].get('equivalent_to') and (owned_tasks(region)[name]['control'] is None or owned_tasks(region)[name]['control'] in visible)]
        names = names or pending
        if names:
            names.sort(key=lambda name: not bool(owned_tasks(region)[name].get('prepares')))
            return choice('action', rid, task={'region': rid, 'name': names[0]}, source_regions=[rid], reason='advance an existing task without requiring a complete inventory')
        if progress['complete']:
            parent = working if working != rid and working in records else _task_routing.parent_region(records, state, rid)
            if parent in records and _task_deferral.runnable(records[parent], records):
                return choice('navigate', parent, reason='resume unfinished work at the observed entry parent')
    frontier = _task_deferral.choose_unfinished(records, {**state, 'working_region': rid or working})
    if frontier:
        other = frontier['region']
        return select_work(records, {**state, 'active_task': None, 'working_region': other}, other)
    return choice('idle', reason='当前无可推进的范围内工作；保留暂挂和登记缺口，不声明全应用完成')

def pending_work(run):
    """Executed evidence takes precedence over proposing another GUI action."""
    from pathlib import Path
    from regrow.records.snapshots import read
    run = Path(run)
    pending = step_repair.pending(run)
    execution = run / 'execution_pending.json'
    if execution.exists():
        attempt = read(execution)['attempt']
        if not (run / 'action_attempts' / attempt / 'commit.json').exists():
            if pending and pending['stage'] != 'update':
                raise step_repair.Paused('execution_unconfirmed', '已投递动作与待纠错阶段冲突；保留证据，禁止重投')
            return {'kind': 'update', 'attempt': attempt, 'pending': pending}
        execution.unlink()
    if pending:
        return {'kind': 'update' if pending['stage'] == 'update' else 'resume', 'attempt': pending.get('attempt'), 'pending': pending}
    return None

def after_round(status, idle_recheck):
    """Session continuation uses explicit runtime outcomes, never prompt fields."""
    if status in ('scope_idle', 'region_complete'):
        return 'stop' if idle_recheck else 'knowledge'
    if status in ('updated', 'paused_after_recovery_discovery', 'task_proposal', 'ready_next_round', 'repair_pending', 'task_deferred'):
        return 'continue'
    return 'stop'

def preview_next(root, run):
    """Read-only post-commit preview; discovery remains a valid next stage."""
    from regrow.traversal.action_proposer import request_from_run
    (_, records, state) = _record_load(run)
    decision = select_work(records, state)
    if decision['kind'] in ('locate', 'recover', 'wait'):
        return {'stage': decision['kind'], 'action_ready': False, 'reason': decision['reason']}
    return request_from_run(root, run, decision=decision)

class Scheduler:

    def __init__(self, root, run, frame, output):
        (self.root, self.run, self.frame, self.output) = (root, run, frame, output)
        self.decisions = []

    def current(self):
        """Reconcile committed work, then choose and render through the components."""
        from regrow.records import task_settlement as _task_settlement
        from regrow.records import coverage_exemption as _coverage_exemption
        from regrow.traversal import traversal_scope as _traversal_scope
        from regrow.traversal import task_prerequisites as _task_prerequisites
        from regrow.traversal import task_result_review as _task_result_review
        from regrow.traversal.action_proposer import request_from_run
        from regrow.records.snapshots import write_json
        if not (self.run / 'execution_pending.json').exists() and (not step_repair.pending(self.run)):
            _task_settlement.reconcile_run(self.run)
        _coverage_exemption.refresh(self.run)
        (_, known, state) = _record_load(self.run)
        _traversal_scope.exclude_known_external(self.run, known, state)
        retire_completed_goal(self.run)
        _task_prerequisites.prioritize(self.run, self.frame)
        (_, known, state) = _record_load(self.run)
        if state.get('reason') == 'verify_prepared_dependency' and state.get('next_action_mode') == 'discover':
            raise step_repair.Paused('ready_next_round', '准备任务已完成；下一轮观察目标是否解锁')
        deferred = _task_result_review.next_deferred(self.root, self.run, self.frame)
        if deferred:
            return deferred
        decision = select_work(known, state)
        self.decisions.append({**decision, 'snapshot': _record_load(self.run)[0].name})
        write_json(self.output / 'scheduling.json', self.decisions)
        return request_from_run(self.root, self.run, decision=decision, frame=self.frame)

def offer_foreground_navigation(records, state, focus, reply):
    """A blocked route entry is not a prerequisite for choosing a navigation action."""
    if reply.get('focus_presence') != 'not_interactive':
        return False
    observation = state.get('observation')
    if not observation or observation.get('image') != state.get('pending_frame'):
        return False
    refs = [r for r in state.get('interactive_regions', []) if r != focus and r in records]
    parents = {records[r].get('parent_region') for r in refs}
    refs = [r for r in refs if r not in parents]
    if not refs:
        return False
    state.update(interactive_regions=refs, next_action_mode='explore', reason='navigation_from_foreground', phase='ready_for_next_action', handoff_summary=reply['foreground'].get('description', ''))
    state['observation'] = {**observation, 'foreground': reply['foreground'], 'uncertainties': reply.get('uncertainties', [])}
    for key in ('inspection_region', 'required_control', 'discovery_mode', 'pending_frame'):
        state.pop(key, None)
    return True

def schedule_local_inspection(records, state):
    from regrow.traversal import action_context as _stepwise_flow
    target = state['working_region']
    refs = state['interactive_regions']
    observation = state.get('observation') or {}
    if target in refs:
        state.pop('inspection_region', None)
        state.pop('required_control', None)
        state.update(next_action_mode='explore', phase='ready_for_next_action')
        return
    route = _stepwise_flow.shortest_known_path(records, state, target, require_control=False)
    if refs and target not in refs and (not route or route[0]['operation'] == 'back'):
        state.pop('inspection_region', None)
        state.pop('required_control', None)
        state.update(next_action_mode='explore', reason='navigation_from_foreground', phase='ready_for_next_action')
        return
    if target in refs:
        state['inspection_region'] = target
        state.pop('required_control', None)
    elif route:
        state['inspection_region'] = route[0]['source_region']
        state['required_control'] = route[0]['source_control']
    elif refs:
        state['inspection_region'] = refs[0]
        state.pop('required_control', None)
    else:
        state.pop('inspection_region', None)
        state.pop('required_control', None)
        state['discovery_mode'] = 'relocate'
    state.update(next_action_mode='discover', reason='locate_local_controls', phase='awaiting_discovery')

def retire_completed_goal(run):
    """Do not navigate back to finished work after leaving its surface."""
    from regrow.traversal import region_tasks as _region_tasks
    from regrow.traversal import task_deferral as _task_deferral
    (_, records, state) = _record_load(run)
    if state.get('next_action_mode') not in ('explore', 'discover'):
        return False
    rid = state.get('working_region')
    if rid not in records:
        return False
    tasks = _region_tasks
    active = state.get('active_task') or {}
    task = owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {})
    if task.get('status') == 'pending':
        return False
    if not _record_coverage(records[rid], records)['complete']:
        scheduling = _task_deferral
        if rid not in state.get('interactive_regions', []) and (not scheduling.runnable(records[rid], records)):
            return bool(scheduling.advance_unfinished(run))
        return False
    return bool(_task_deferral.advance_unfinished(run))
