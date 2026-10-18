"""Scope unresolved crashes to their actual operation, never to a task's control.

Task status is scheduling information. Only the existing explicit crash blocker
and its executed action establish a reusable operation restriction.
"""
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from regrow.records.object_store import find_control
from regrow.records.control_context import conditions
from regrow.records.task_settlement import action_name
from regrow.records.task_settlement import completion_target

def failures(records):
    seen = set()
    for (owner, region) in records.items():
        for (name, task) in owned_tasks(region).items():
            blocker = task.get('blocker') or {}
            if task.get('status') != 'blocked' or blocker.get('exception') != 'unexpected_exit':
                continue
            attempt = blocker.get('attempt')
            rows = [(rid, owned_actions(r)[attempt]) for (rid, r) in records.items() if attempt and attempt in owned_actions(r)]
            (rid, action) = rows[0] if len(rows) == 1 else (owner, {})
            cid = action.get('control')
            confirmed = bool(find_control(records[rid], cid)) and action.get('association', {}).get('status') != 'unconfirmed' and (action.get('delivery') == 'executed_receipt_zero') and (action.get('result', {}).get('exception') == 'unexpected_exit') and bool(action.get('operation'))
            scope = conditions(action) if confirmed and 'conditions' in action else None
            if confirmed and scope is None and 'conditions' in task and (not task.get('prepares')):
                target = completion_target(region, task)
                if (target['region'], target['control']) == (rid, cid):
                    scope = conditions(task)
            key = (rid, attempt) if confirmed else (owner, name)
            if key in seen:
                continue
            seen.add(key)
            yield {'region': rid, 'control': cid if confirmed else None, 'operation': action_name(action.get('operation')) if confirmed else None, 'conditions': list(scope) if scope is not None else None, 'attempt': attempt, 'confirmed': confirmed, 'task_region': owner, 'task': name, 'evidence': action.get('result', {}).get('description') or blocker.get('reason', '')}

def applicable(records, rid, cid, operation, use_conditions=None):
    """Unknown current conditions do not establish a conditional match."""
    for failure in failures(records):
        if not failure['confirmed'] or (failure['region'], failure['control'], failure['operation']) != (rid, cid, action_name(operation)):
            continue
        if failure['conditions'] is None:
            continue
        prior = set(failure['conditions'])
        if not prior or (use_conditions is not None and prior <= set(use_conditions)):
            return failure
    return None

def action_conditions(records, binding, proposal):
    owner = binding.get('task_region', binding.get('region_ref'))
    region = records.get(owner, {})
    task = owned_tasks(region).get(binding.get('task_name'))
    if not task or task.get('prepares') or 'conditions' not in task:
        return None
    target = completion_target(region, task)
    if (target['region'], target['control']) == (binding.get('region_ref'), binding.get('control_ref')):
        return conditions(task)
    return None

def check_action(records, binding, proposal):
    failure = applicable(records, binding.get('region_ref'), binding.get('control_ref'), proposal.get('action'), action_conditions(records, binding, proposal))
    if failure is None:
        failure = next((f for f in failures(records) if f['confirmed'] and f['conditions'] is None
                        and (f['region'], f['control'], f['operation']) == (binding.get('region_ref'), binding.get('control_ref'), action_name(proposal.get('action')))
                        and (f['task_region'], f['task']) == (binding.get('task_region', binding.get('region_ref')), binding.get('task_name'))), None)
    if failure:
        raise ValueError('该实际控件的同一操作及适用条件仍有未解除的应用退出记录：' + str(failure['attempt']) + '。保留原失败，选择其他有依据的操作；普通疑问任务不构成整控件禁令。')

def attach(request, records, state):
    """Give ordinary action selection ambiguous crash scope without a new call."""
    if not request.get('action_ready'):
        return request
    refs = set(state.get('interactive_regions', []))
    refs.update((request.get('source', {}).get(k) for k in ('region', 'task_region', 'working_region')))
    refs.update((c.get('region_ref') for c in request.get('backend_candidates', [])))
    rows = []
    for f in failures(records):
        if f['region'] not in refs and f['task_region'] not in refs:
            continue
        r = records[f['region']]
        rows.append({'原任务': records[f['task_region']]['name'] + ' / ' + f['task'], '实际区块': r['name'] if f['confirmed'] else None, '实际控件': owned_controls(r).get(f['control'], {}).get('name'), '动作': f['operation'], '适用条件': f['conditions'], '实际尝试': f['attempt'], '结果': f['evidence'], '实际操作归属明确': f['confirmed']})
    if rows:
        from regrow.prompts.prompt_material import assign
        assign(request, {'未解除的应用退出记录': rows})
    return request
