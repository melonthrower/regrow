"""Choose work from committed facts; request renderers do not decide session exits."""
import discovery_step
import step_repair
from region_tasks import helper, coverage


def select_work(records, state, working=None):
    """Return a read-only work decision, without constructing a model request."""
    working = working or state.get('working_region')
    mode = state.get('next_action_mode')
    def choice(kind, region=working, **fields):
        return {'kind':kind, 'region':region, 'working_region':working, **fields}
    if mode == 'discover':
        return choice('locate', reason='current observation needs discovery')
    if mode in ('recover','recover_scope','review_result'):
        return choice('recover', reason='registered foreground requires recovery')
    if mode != 'explore':
        return choice('wait', reason='registered mode does not permit exploration')
    refs = state.get('interactive_regions', [])
    allowed = [rid for rid in refs if rid in records and not records[rid].get('out_of_scope_reason')]
    active = state.get('active_task') or {}
    owner = active.get('region')
    task = records.get(owner, {}).get('tasks', {}).get(active.get('name'))
    if not task or task.get('status') != 'pending' or not helper('task_prerequisites').in_scope(records[owner], task, records):
        task = None
    in_progress = bool(task and (task.get('attempts') or task.get('task_type') in ('parameter','scroll')))
    target = helper('task_settlement').completion_target(records[owner], task) if task else {}
    local_continuation = in_progress and target.get('region') in allowed
    scroll_target = helper('inventory_scroll').target(records, state)
    if scroll_target and scroll_target not in refs:
        return choice('navigate', scroll_target, reason='reach the pending inventory scroll')
    if local_continuation:
        rid = target['region']
    elif working not in refs and working in records and helper('task_deferral').runnable(records[working], records):
        # A parameter task may continue on the child surface it actually opened.
        if in_progress and allowed:
            rid = allowed[0]
        else:
            return choice('navigate', working, reason='reach in-scope unfinished work')
    else:
        rid = scroll_target or (working if working in allowed else next(
            (ref for ref in allowed if helper('task_deferral').runnable(records[ref], records)),
            allowed[0] if allowed else None))
    if rid is not None:
        region = records[rid]
        progress = coverage(region, records)
        if region.get('tasks') and region.get('external_entry_policy') != 'record_only':
            return choice('scope_review', rid, reason='review existing tasks against this run scope')
        continuation = task is not None and (rid == owner or in_progress)
        if continuation:
            return choice('action', rid, task=dict(active), source_regions=list(allowed),
                          reason='continue the existing task on its current surface')
        gap = region.get('registration_gaps', {}).get('task_proposal', {})
        if (not progress['inventory_complete'] and not progress['pending']
                and (not gap or gap.get('recheck_after'))):
            return choice('task_proposal', rid, reason='prepare tasks for observed controls')
        pending = [name for name in progress['pending'] if region['tasks'][name]['handling'] != 'equivalent']
        visible = set((state.get('observation') or {}).get('control_refs', []))
        names = [name for name in pending if region['tasks'][name]['handling'] == 'explore'
                 and (region['tasks'][name]['control'] is None or region['tasks'][name]['control'] in visible)]
        names = names or pending
        if names:
            names.sort(key=lambda name:not bool(region['tasks'][name].get('prepares')))
            return choice('action', rid, task={'region':rid,'name':names[0]}, source_regions=[rid],
                          reason='advance an existing task without requiring a complete inventory')
        if progress['complete']:
            parent = (working if working != rid and working in records
                      else helper('task_routing').parent_region(records, state, rid))
            if parent in records and helper('task_deferral').runnable(records[parent], records):
                return choice('navigate', parent, reason='resume unfinished work at the observed entry parent')
    frontier = helper('task_deferral').choose_unfinished(records, {**state, 'working_region':rid or working})
    if frontier:
        other = frontier['region']
        # The recursive call moves to a different runnable goal; it does not inspect a request stage.
        return select_work(records, {**state, 'active_task':None, 'working_region':other}, other)
    return choice('idle', reason='当前无可推进的范围内工作；保留暂挂和登记缺口，不声明全应用完成')


def pending_work(run):
    """Executed evidence takes precedence over proposing another GUI action."""
    from pathlib import Path
    from register_update import read
    run = Path(run)
    pending = step_repair.pending(run)
    execution = run/'execution_pending.json'
    if execution.exists():
        attempt = read(execution)['attempt']
        if not (run/'action_attempts'/attempt/'commit.json').exists():
            if pending and pending['stage'] != 'update':
                raise step_repair.Paused('execution_unconfirmed', '已投递动作与待纠错阶段冲突；保留证据，禁止重投')
            return {'kind':'update', 'attempt':attempt, 'pending':pending}
        execution.unlink()
    if pending:
        return {'kind':'update' if pending['stage']=='update' else 'resume',
                'attempt':pending.get('attempt'), 'pending':pending}
    return None


def after_round(status, idle_recheck):
    """Session continuation uses explicit runtime outcomes, never prompt fields."""
    if status in ('scope_idle','region_complete'):
        return 'stop' if idle_recheck else 'knowledge'
    if status in ('updated','paused_after_recovery_discovery','task_proposal',
                  'ready_next_round','repair_pending','task_deferred'):
        return 'continue'
    return 'stop'


def preview_next(root, run):
    """Read-only post-commit preview; discovery remains a valid next stage."""
    from action_proposer import request_from_run
    _, records, state = discovery_step.load(run)
    decision = select_work(records, state)
    if decision['kind'] in ('locate','recover','wait'):
        return {'stage':decision['kind'], 'action_ready':False, 'reason':decision['reason']}
    return request_from_run(root, run, decision=decision)


class Scheduler:
    def __init__(self, root, run, frame, output):
        self.root, self.run, self.frame, self.output = root, run, frame, output
        self.decisions = []

    def current(self):
        """Reconcile committed work, then choose and render through the components."""
        from action_proposer import request_from_run
        from register_update import write_json
        if not (self.run/'execution_pending.json').exists() and not step_repair.pending(self.run):
            helper('task_settlement').reconcile_run(self.run)
        helper('coverage_exemption').refresh(self.run)
        _, known, state = discovery_step.load(self.run)
        helper('traversal_scope').exclude_known_external(self.run, known, state)
        discovery_step.retire_completed_goal(self.run)
        helper('task_prerequisites').prioritize(self.run, self.frame)
        _, known, state = discovery_step.load(self.run)
        if state.get('reason')=='verify_prepared_dependency' and state.get('next_action_mode')=='discover':
            raise step_repair.Paused('ready_next_round','准备任务已完成；下一轮观察目标是否解锁')
        decision = select_work(known, state)
        self.decisions.append({**decision, 'snapshot':discovery_step.load(self.run)[0].name})
        write_json(self.output/'scheduling.json', self.decisions)
        if decision['kind']=='idle':
            deferred=helper('task_result_review').next_deferred(self.root,self.run,self.frame)
            if deferred:return deferred
        return request_from_run(self.root, self.run, decision=decision, frame=self.frame)
