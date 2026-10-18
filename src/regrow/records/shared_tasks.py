from regrow.records.object_store import region_work
'Reuse shared task definitions/results and withdraw invalid projections.\n\nLocal attempts and control identities always remain with their actual owners.\n'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from copy import deepcopy

def synchronize_tasks(records):
    """Project one shared task definition onto local controls, without copying acts."""
    from regrow.records.action_owner_correction import effective_attempts
    from regrow.records.shared_controls import view
    from regrow.records.control_context import same_use
    active = set()
    for owner in records.values():
        for group in owner.get('shared_controls', {}).values():
            if group['status'] != 'confirmed':
                continue
            origin = group['members'][0]
            (rr, cc) = (origin['region'], origin['control'])
            source = records[rr]
            for (name, definition) in list(owned_tasks(source).items()):
                if definition.get('control') != cc or definition.get('shared_task_ref'):
                    continue
                if definition.get('equivalent_to'):
                    continue
                key = (rr, name)
                active.add(key)
                members = [(rr, name, definition)]
                for member in group['members'][1:]:
                    (rid, cid) = (member['region'], member['control'])
                    region = records[rid]
                    tasks = owned_tasks(region, create=True)
                    local = next(((n, t) for (n, t) in tasks.items() if t.get('control') == cid and (t.get('shared_task_ref') or {}).get('region') == rr and ((t.get('shared_task_ref') or {}).get('task') == name)), None)
                    if local is None:
                        label = name if name not in tasks else name + '（共享：' + owned_controls(region)[cid]['name'] + '）'
                        if label in tasks:
                            continue
                        t = {k: deepcopy(definition[k]) for k in ('task_type', 'reason', 'conditions') if k in definition}
                        t.update(name=label, control=cid, status='pending', equivalent_to='', shared_task_ref={'region': rr, 'task': name, 'control': cc})
                        if definition.get('prerequisite'):
                            t['prerequisite'] = {k: deepcopy(v) for (k, v) in definition['prerequisite'].items() if k not in ('scheduled', 'satisfied', 'last_check', 'recheck_requested')}
                        tasks[label] = t
                        local = (label, tasks[label])
                    if 'conditions' in definition and not task_value(local[1], 'attempts') and (not same_use(local[1], definition)):
                        task_audit(local[1]).setdefault('condition_history', []).append({'conditions': local[1].get('conditions', []), 'source_task': name})
                        local[1]['conditions'] = deepcopy(definition.get('conditions', []))
                    local[1]['shared_task_active'] = True
                    from regrow.records.task_settlement import registration_kind
                    local[1]['task_type'] = registration_kind(definition)
                    members.append((rid, *local))
                winner = None
                from regrow.records.task_settlement import registered_result
                from regrow.records.task_settlement import task_product
                for (rid, n, t) in members:
                    if t.get('status') != 'done' or not same_use(t, definition):
                        continue
                    evidence = [aid for aid in effective_attempts(t) if owned_actions(records[rid]).get(aid, {}).get('control') == t.get('control') and owned_actions(records[rid])[aid].get('delivery') == 'executed_receipt_zero' and (owned_actions(records[rid])[aid].get('result', {}).get('exception') == 'none') and registered_result(t, owned_actions(records[rid])[aid], aid)]
                    if evidence:
                        winner = {'region': rid, 'task': n, 'attempts': evidence}
                        break
                    if not t.get('shared_result') and task_value(t, 'latest_update', {}).get('decision') == 'answered' and task_product(t) and (task_value(t, 'completion_basis', {}).get('basis') == 'observation_only') and (not t.get('blocker')) and (not t.get('prepares')):
                        winner = {'region': rid, 'task': n, 'observation_only': True}
                        break
                for (rid, n, t) in members:
                    if (rid, n) == (rr, name) or (t.get('status') == 'done' and (not t.get('shared_result'))):
                        continue
                    if not same_use(t, definition):
                        t.pop('shared_result', None)
                        if t.get('shared_prior_state'):
                            t.update(t.pop('shared_prior_state'))
                        continue
                    t.pop('shared_result', None)
                    if winner:
                        t.setdefault('shared_prior_state', {'status': t['status']})
                        t.update(status='done', shared_result=deepcopy(winner))
                    elif definition.get('status') == 'done' and task_value(definition, 'completion_basis', {}).get('basis') == 'observation_only' and task_product(definition) and (not definition.get('shared_result')):
                        t.setdefault('shared_prior_state', {'status': t['status']})
                        t.update(status='done', shared_result={'region': rr, 'task': name, 'observation_only': True})
                    elif t.get('shared_prior_state'):
                        t.update(t.pop('shared_prior_state'))
                    if definition.get('reason'):
                        t['reason'] = definition['reason']
                if not winner and definition.get('shared_origin_state'):
                    definition.update(definition.pop('shared_origin_state'))
                    definition.pop('shared_result', None)
                if winner and (winner['region'], winner['task']) != (rr, name) and (definition.get('status') != 'done' or definition.get('shared_result')):
                    definition.setdefault('shared_origin_state', {'status': definition['status']})
                    definition.update(status='done', shared_result=deepcopy(winner))
    for (rid, r) in records.items():
        for t in owned_tasks(r).values():
            ref = t.get('shared_task_ref')
            origin = t.get('shared_origin_state')
            valid = False
            if ref:
                group = view(records, rid, t['control'])
                valid = (ref['region'], ref['task']) in active and bool(group and group['status'] == 'confirmed' and any((m['region'] == ref['region'] and m['control'] == ref['control'] for m in group['members'])))
                if not valid:
                    if t.get('shared_task_active', True):
                        task_audit(t).setdefault('shared_history', []).append({'reference': deepcopy(ref), 'result': t.get('shared_result')})
                    t['shared_task_active'] = False
                    t.pop('shared_result', None)
                    if t.get('shared_prior_state'):
                        t.update(t.pop('shared_prior_state'))
            if origin:
                group = view(records, rid, t['control'])
                if not group or group['status'] != 'confirmed':
                    t.update(t.pop('shared_origin_state'))
                    t.pop('shared_result', None)

def automatic_tasks(region, cid):
    return [{'任务': n, '结束条件': t.get('reason') or t.get('name', ''), '状态': t['status'], '知识来源': '历史共享成员；名称和描述中的选中/当前值不是本图状态', '适用条件': t.get('conditions', []), '说明': '框架引用共享知识，本地未执行' if t.get('shared_result') else '共享任务尚未完成，仍需探索'} for (n, t) in owned_tasks(region).items() if t.get('control') == cid and t.get('shared_task_ref') and t.get('shared_task_active', True)]

def reconcile_detached_tasks(records, state, affected, member, call):
    """After relation refresh, archive invalid inheritance; retain local evidence."""
    for (rid, region) in records.items():
        for (name, task) in list(owned_tasks(region).items()):
            if (rid, task.get('control')) not in affected:
                continue
            if not task.get('shared_task_ref') or task.get('shared_task_active', True):
                continue
            control = owned_controls(region)[task['control']]
            from regrow.records.tasks import detached
            control.setdefault('shared_task_history', []).append({'name': name, 'record': detached(task), 'source_call': call})
            if task_value(task, 'attempts') or task_value(task, 'findings'):
                task.update(status='blocked', reason='共享已解除；保留本地尝试，重新核对任务定义')
                task.pop('shared_task_ref', None)
            else:
                del owned_tasks(region)[name]
                if state.get('active_task') == {'region': rid, 'name': name}:
                    state.pop('active_task', None)
            region_work(region).setdefault('task_inventory', {})['review'] = {'kind': 'shared_behavior', 'reason': '共享关系已解除，按本地控件重新清点任务', 'source_call': call}
    region_work(records[member['region']]).setdefault('task_inventory', {})['review'] = {'kind': 'shared_behavior', 'reason': '控件已独立，核对本地任务', 'source_call': call}
