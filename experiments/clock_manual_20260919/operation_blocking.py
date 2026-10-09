"""Scope unresolved crashes to their actual operation, never to a task's control.

Task status is scheduling information. Only the existing explicit crash blocker
and its executed action establish a reusable operation restriction.
"""
import json

from control_context import conditions
from task_settlement import action_name, completion_target


def failures(records):
    seen = set()
    for owner, region in records.items():
        for name, task in region.get('tasks', {}).items():
            blocker = task.get('blocker') or {}
            if task.get('status') != 'blocked' or blocker.get('exception') != 'unexpected_exit':continue
            attempt = blocker.get('attempt')
            rows = [(rid, r['actions'][attempt]) for rid, r in records.items()
                    if attempt and attempt in r.get('actions', {})]
            rid, action = rows[0] if len(rows) == 1 else (owner, {})
            cid = action.get('control')
            confirmed = (cid in records[rid].get('controls', {})
                         and action.get('association', {}).get('status') != 'unconfirmed'
                         and action.get('delivery') == 'executed_receipt_zero'
                         and action.get('result', {}).get('exception') == 'unexpected_exit'
                         and bool(action.get('operation')))
            scope = conditions(action) if confirmed and 'conditions' in action else None
            if confirmed and scope is None and not task.get('prepares'):
                target = completion_target(region, task)
                if (target['region'], target['control'], action_name(target['action'])) == (rid, cid, action_name(action['operation'])):
                    scope = conditions(task)
            key = (rid, attempt) if confirmed else (owner, name)
            if key in seen:continue
            seen.add(key)
            yield {'region': rid, 'control': cid if confirmed else None,
                   'operation': action_name(action.get('operation')) if confirmed else None,
                   'conditions': list(scope) if scope is not None else None,
                   'attempt': attempt, 'confirmed': confirmed,
                   'task_region': owner, 'task': name,
                   'evidence': action.get('result', {}).get('description') or blocker.get('reason', '')}


def applicable(records, rid, cid, operation, use_conditions=None):
    """Unknown current conditions do not establish a conditional match."""
    for failure in failures(records):
        if not failure['confirmed'] or (failure['region'], failure['control'], failure['operation']) != (rid, cid, action_name(operation)):continue
        if failure['conditions'] is None:continue
        prior = set(failure['conditions'])
        if not prior or (use_conditions is not None and prior <= set(use_conditions)):
            return failure
    return None


def action_conditions(records, binding, proposal):
    owner = binding.get('task_region', binding.get('region_ref'))
    region = records.get(owner, {})
    task = region.get('tasks', {}).get(binding.get('task_name'))
    if not task or task.get('prepares'):return None
    target = completion_target(region, task)
    if (target['region'], target['control'], action_name(target['action'])) == (
            binding.get('region_ref'), binding.get('control_ref'), action_name(proposal.get('action'))):
        return conditions(task)
    return None


def check_action(records, binding, proposal):
    failure = applicable(records, binding.get('region_ref'), binding.get('control_ref'),
                         proposal.get('action'), action_conditions(records, binding, proposal))
    if failure:
        raise ValueError('该实际控件的同一操作及适用条件仍有未解除的应用退出记录：'+
                         str(failure['attempt'])+'。保留原失败，选择其他有依据的操作；普通疑问任务不构成整控件禁令。')


def attach(request, records, state):
    """Give ordinary action selection ambiguous crash scope without a new call."""
    if not request.get('action_ready'):return request
    refs = set(state.get('interactive_regions', []))
    refs.update(request.get('source', {}).get(k) for k in ('region', 'task_region', 'working_region'))
    refs.update(c.get('region_ref') for c in request.get('backend_candidates', []))
    rows = []
    for f in failures(records):
        if f['region'] not in refs and f['task_region'] not in refs:continue
        r = records[f['region']]
        rows.append({'原任务': records[f['task_region']]['name']+' / '+f['task'],
                     '实际区块': r['name'] if f['confirmed'] else None,
                     '实际控件': r.get('controls', {}).get(f['control'], {}).get('name'),
                     '动作': f['operation'], '适用条件': f['conditions'],
                     '实际尝试': f['attempt'], '结果': f['evidence'],
                     '实际操作归属明确': f['confirmed']})
    if rows:
        text = ('\n\n未解除的应用退出记录（原任务目标不等于实际失败控件）：\n'+
                json.dumps(rows, ensure_ascii=False)+'\n普通知识缺口、无提示和前置未满足只暂挂相应任务，不禁止同控件其他用途。'
                '以上失败仅限制对应的实际动作及适用条件；准备和导航也不能借新任务名重复该失败操作。'
                '条件不同的已有用途可继续；是否适用尚不明确时结合当前截图和原历史判断，不能把空条件当作已证实条件不同，'
                '也不能把归属不明的退出归咎于原目标控件。没有足够依据时说明具体缺口，沿原观察/纠错处理。')
        request['user_prompt'] = request['dynamic_prompt'] = request['user_prompt']+text
    return request
