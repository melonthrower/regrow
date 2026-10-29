from regrow.records.snapshots import load as _record_load
from regrow.records.object_store import region_work
'Return missing parameter facts to their existing authoring stage, once per evidence set.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
import hashlib
import json
from pathlib import Path

def observable(owner, task, state):
    """Evidence registration cannot discharge preparations or unresolved ownership."""
    from regrow.records import task_settlement as _task_settlement
    from regrow.records import task_updates as _task_updates
    state = state or {}
    return bool(task.get('status') == 'pending' and (not task.get('equivalent_to')) and (_task_settlement.registration_kind(task) == 'parameter') and (not any((task.get(k) for k in ('prepares', 'blocker', 'shared_task_ref', 'coverage_exemption')))) and (not task.get('prerequisite') or task['prerequisite'].get('satisfied')) and _task_updates.observed_control(owner, task, state))

def from_no_action(run, records, state, request, proposal, call):
    """Use the existing fact author after a no-action proposal, preserving real history."""
    from regrow.records import task_settlement as _task_settlement
    source = request.get('source', {})
    rid = source.get('task_region') or source.get('region')
    name = source.get('task_name')
    owner = records.get(rid, {})
    task = owned_tasks(owner).get(name, {})
    if proposal.get('action') != 'none' or not observable(owner, task, state) or source.get('observation') != state['observation']['id'] or region_work(owner).get('task_inventory', {}).get('review'):
        return False
    settlement = _task_settlement
    target = settlement.completion_target(owner, task)
    selected = set(task_value(task, 'attempts', []))
    selected.update((aid for region in records.values() for (aid, action) in owned_actions(region).items() if settlement.recorded_match(region, aid, action, target)))
    for region in records.values():
        for other in owned_tasks(region).values():
            if other.get('prepares') and selected.intersection(task_value(other, 'attempts', [])):
                selected.update(task_value(other, 'attempts', []))
    snapshot = source.get('snapshot') or json.loads((Path(run) / 'knowledge_current.json').read_text())['snapshot']
    evidence = {'snapshot': snapshot, 'attempts': sorted(selected), 'observation': state['observation']['id']}
    key = hashlib.sha256(json.dumps([rid, name, evidence], sort_keys=True).encode()).hexdigest()
    region_work(owner).setdefault('task_inventory', {})['review'] = {'kind': 'parameter_facts', 'task': name, 'key': key, 'source_call': call, **evidence, 'reason': proposal['reason']}
    state.update(working_region=rid, next_action_mode='explore', phase='ready_for_next_action')
    return True

def reviewing(owner, task, name, state):
    review = region_work(owner).get('task_inventory', {}).get('review', {})
    return review.get('kind') == 'parameter_facts' and (not review.get('episode')) and (review.get('task') == name) and observable(owner, task, state)

def evidence_context(region):
    from regrow.records import history_context as _history_context
    review = region_work(region).get('task_inventory', {}).get('review', {})
    base = getattr(getattr(region, 'store', None), 'base', None)
    if base is None:
        raise ValueError('参数历史复核缺少真实快照来源')
    run = Path(base).parent.parent
    (_, records, _) = _record_load(run, review['snapshot'])
    task = owned_tasks(records.get(region['id'], {})).get(review['task'])
    if task is None:
        raise ValueError('原参数任务在引用的快照中不存在')
    return _history_context.task_goal(task, records, run, attempt_refs=review.get('attempts', []))

def augment(request, region):
    review = region_work(region).get('task_inventory', {}).get('review', {})
    if review.get('kind') != 'parameter_facts':
        return request
    dynamic = json.loads(request['user_prompt'])
    dynamic['待补参数事实的原任务证据'] = evidence_context(region)
    request['user_prompt'] = request['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    request['source']['parameter_fact_review'] = {k: review[k] for k in ('task', 'key')}
    return request
