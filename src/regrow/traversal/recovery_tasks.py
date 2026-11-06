"""Keep interrupted questions across recovery; a recovered app is not an answer."""
from copy import deepcopy
from pathlib import Path

from regrow.records.object_store import owned_tasks
from regrow.records.tasks import audit, in_scope, read as task_value
from regrow.records.snapshots import load, publish


def interrupted(records, state):
    """Select the original active question and questions bound to the trigger."""
    active = state.get('active_task') or {}
    attempt = state.get('attempt')
    refs = []
    for rid, region in records.items():
        for name, task in owned_tasks(region).items():
            ref = {'region': rid, 'name': name}
            if ref == active or attempt and attempt in task_value(task, 'attempts', []):
                if task.get('status') in ('pending', 'blocked'):
                    refs.append(ref)
    return refs


def suspend(run, refs, call, reason):
    """Only suspend the interrupted questions; preserve unrelated blockers."""
    if not refs:
        return

    def mutate(records, state, *_):
        for ref in refs:
            task = owned_tasks(records.get(ref['region'], {})).get(ref['name'])
            if task is None or task.get('status') != 'pending' or task.get('blocker'):
                continue
            audit(task)['result_evidence'] = reason
            task.update(status='blocked',
                        blocker={'condition': 'review_required', 'exception': 'unexpected_exit',
                                 'source_call': call, 'reason': reason},
                        deferral={'reason': reason, 'retry_when': 'observed_app_recovery',
                                  'source_call': call})
        if state.get('active_task') in refs:
            state.pop('active_task', None)
    publish(run, 'exit-suspend-' + call, mutate)


def resume(run, episode, call):
    """Requeue only crash-blocked questions after accepted fresh discovery."""
    run = Path(run)
    if any((run / name).exists() for name in ('execution_pending.json', 'pending_step.json')):
        return []
    _, records, state = load(run)
    observation = state.get('observation') or {}
    if (not call or state.get('next_action_mode') != 'explore' or not state.get('interactive_regions')
            or not observation.get('id') or state.get('source_call') != call
            or observation.get('foreground', {}).get('exception') != 'none'):
        return []
    selected = []
    trigger = episode.get('trigger_attempt')
    exit_observed = any(row.get('exception') == 'unexpected_exit' for row in episode.get('actions', []))
    for ref in episode.get('task_refs', []):
        region = records.get(ref['region'], {})
        task = owned_tasks(region).get(ref['name'])
        blocker = (task or {}).get('blocker', {})
        crash = blocker.get('exception') == 'unexpected_exit' and blocker.get('condition') == 'review_required'
        deferral = (task or {}).get('deferral', {})
        interrupted_observation = (not blocker and exit_observed and trigger
            and (trigger in (deferral.get('attempt'), deferral.get('source_attempt'))
                 or trigger in task_value(task, 'attempts', [])))
        if (task and task.get('status') == 'blocked' and in_scope(region, task, records)
                and (crash or interrupted_observation)):
            selected.append(ref)
    if not selected:
        return []

    def mutate(records, state, *_):
        for ref in selected:
            task = owned_tasks(records[ref['region']])[ref['name']]
            history = audit(task)
            for key in ('blocker', 'deferral'):
                previous = task.pop(key, None)
                if previous:
                    history.setdefault(key + '_history', []).append({
                        **deepcopy(previous), 'resolved_by': call,
                        'observation': observation['id'],
                        'evidence': '恢复后的新截图已正常识别登记；原问题仍需继续判断。'})
            task['status'] = 'pending'
        if not state.get('active_task'):
            ready = [ref for ref in selected
                     if owned_tasks(records[ref['region']])[ref['name']]['status'] == 'pending']
            if ready:
                state['active_task'] = dict(ready[0])
        state['recovery_handoff'] = (state.get('recovery_handoff', '')
            + '\n原闪退阻塞已由恢复后的有效观察解除；继续原问题，先核对当前对象及必要准备，不重放旧动作。')
    publish(run, 'recovery-tasks-' + call, mutate)
    return selected
