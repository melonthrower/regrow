from regrow.records.object_store import region_work
'Register visible entry associations without inventing an activation effect.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records.object_store import find_control
from copy import deepcopy

def resolve(value, records, labels=None):
    from regrow.records.task_settlement import entry_schema
    import jsonschema
    jsonschema.validate(value, entry_schema())
    matches = [value['region']] if value['region'] in records else []
    if len(matches) != 1:
        raise ValueError('入口去向需要本轮已登记的区块ID')
    if not value['evidence'].strip():
        raise ValueError('入口关联需要明确用途及观察依据；不能仅凭同时可见推定关联')
    return matches[0]

def register(owner, task, value, knowledge, records, visible, observation, source, labels=None, *, settle=True):
    from regrow.records.task_settlement import registration_kind
    from regrow.records.task_settlement import completion_target
    target = resolve(value, records, labels)
    value = {**value, 'conditions': value.get('conditions', list(task.get('conditions', []))), 'meaning': knowledge}
    control = find_control(owner, task.get('control'))
    current_owner = completion_target(owner, task)['region']
    from regrow.records.observations import frame_observation
    observed = bool(frame_observation(control, kind='controls', observation=observation))
    if registration_kind(task) != 'entry' or task.get('equivalent_to') or task.get('prepares') or task.get('shared_task_ref') or task.get('coverage_exemption') or (task.get('prerequisite') and (not task['prerequisite'].get('satisfied'))) or task.get('blocker', {}).get('exception'):
        raise ValueError('当前入口观察不能替代参数、前置或异常任务的义务')
    if not observation or not observed or current_owner not in visible or (target not in visible):
        raise ValueError('入口去向必须有本帧入口控件的语义观察及可交互目标区块，历史或纯图片匹配不足')
    from regrow.records.control_knowledge import text
    knowledge = text(knowledge)
    if not set(task.get('conditions', [])).issubset(value['conditions']) or not knowledge:
        raise ValueError('入口观察不能丢弃已有用途条件，并须登记稳定knowledge')
    basis = {'basis': 'observation_only', 'observation': observation, **source}
    if set(value['conditions']) != set(task.get('conditions', [])):
        task_audit(task).setdefault('condition_history', []).append({'conditions': list(task.get('conditions', [])), **deepcopy(basis), 'evidence': value['evidence']})
        task['conditions'] = list(dict.fromkeys(value['conditions']))
    from regrow.records.tasks import store_entry
    from regrow.records.tasks import store_knowledge
    store_entry(task, {**deepcopy(value), 'region': target, 'source': basis})
    store_knowledge(task, knowledge, basis)
    if settle:
        task['status'] = 'done'
        task_audit(task).update(result_evidence=value['evidence'], completion_basis={'rule': 'entry_observation_registered', 'region': owner['id'], 'control': task['control'], **basis})

def request_review(records, state, request, proposal):
    """Reuse ordinary task inventory after a no-action entry proposal."""
    from regrow.records.task_settlement import registration_kind
    source = request.get('source', {})
    rid = source.get('task_region', source.get('region'))
    owner = records.get(rid, {})
    task = owned_tasks(owner).get(source.get('task_name'), {})
    observation = state.get('observation') or {}
    observed = any((row.get('evidence', {}).get('observation') == observation.get('id') and (not row.get('visual_only')) for row in observation_history(owned_controls(owner).get(task.get('control'), {}))))
    if registration_kind(task) != 'entry' or proposal.get('action') != 'none' or source.get('observation') != observation.get('id') or (rid not in state.get('interactive_regions', [])) or (task.get('control') not in observation.get('control_refs', [])) or (not observed):
        return False
    region_work(owner).setdefault('task_inventory', {'inventory': 'partial', 'controls': []})['review'] = {'kind': 'entry_observation', 'task': source['task_name'], 'reason': proposal['reason']}
    state['working_region'] = rid
    return True

def unresolved_review(owner, review, state, frame, evidence):
    """An unavailable destination needs discovery, even when pending work remains."""
    task = owned_tasks(owner).get(review.get('task'), {})
    if review.get('kind') != 'entry_observation' or task.get('status') in ('done', 'record_only') or task_value(task, 'latest_update'):
        return False
    state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=frame, discovery_mode='relocate', reason='entry_observation_incomplete', correction_context='入口观察尚未登记，需发现入口及对应目标区块：' + evidence)
    state.pop('inspection_region', None)
    return True
