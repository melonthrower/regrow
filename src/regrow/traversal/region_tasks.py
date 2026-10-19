from regrow.records.control_records import aliases as control_aliases
"""Register task proposals and hand their accepted results back to traversal."""
from regrow.records.calls import submission as _owner_submission
from regrow.records.tasks import equivalent_source as _record_equivalent_source
from regrow.records.tasks import coverage as _record_coverage
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records import task_settlement as _task_settlement
from regrow.records.object_store import region_work
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import replace_owned_tasks
from regrow.records.object_store import owned_controls

def apply_plan(region, reply, call, scope_review=False, records=None, state=None, reviewed_controls=None):
    from regrow.traversal import task_proposer as _task_proposer
    from regrow.records import shared_controls as _shared_controls
    from regrow.records import task_updates as _task_updates
    from regrow.records import task_settlement as _task_settlement
    from regrow.traversal import parameter_evidence_review as _parameter_evidence_review
    from regrow.records import shared_tasks as _shared_tasks
    import jsonschema
    jsonschema.validate(reply, _task_proposer.proposal_schema())
    if not reply['evidence'].strip():
        raise ValueError('inventory needs evidence')
    records = records or {region['id']: region}
    shared_rows = reply.get('shared_instances', [])
    renamed = _shared_controls.propose_instances(records, region['id'], shared_rows, call, state=state)
    old = owned_tasks(region)
    tasks = dict(old)
    seen = set()
    considered = set(owned_controls(region) if reviewed_controls is None else reviewed_controls)
    considered = {next((cid for cid, c in owned_controls(region).items()
                       if old_id == cid or any(v['id'] == old_id for v in control_aliases(c))), old_id)
                  for old_id in considered}
    if not considered.issubset(owned_controls(region)):
        raise ValueError('本次清点的控件身份已变化，需重新读取问题范围')
    updates = _task_updates
    settlement = _task_settlement
    for row in reply['operations']:
        if 'task' in row:
            matched = [name for name in old if updates.reference(region['id'], name) == row['task']]
            if len(matched) != 1:
                raise ValueError('已有任务增量须引用本区块明确task，不新建或改挂')
            name = matched[0]
            task = tasks[name]
            if name not in _task_proposer.update_names(region, scope_review=bool(scope_review)):
                raise ValueError('本次指定复核只评估原任务；其他旧任务保持原判断与归属')
            if name in seen:
                raise ValueError('同一任务不能重复提交判断')
            if task.get('status') == 'done' and settlement.region_task(task) and (row.get('decision') == 'continue'):
                settlement.refresh_movement(region, task, state)
            if task.get('status') not in ('pending', 'blocked') or task.get('shared_task_ref'):
                raise ValueError('只能更新本次未结束的本地任务')
            seen.add(name)
            review = region_work(region).get('task_inventory', {}).get('review', {})
            observed = updates.observed_control(region, task, state or {}) or bool(review.get('task') == name and review.get('kind') == 'parameter_facts' and review.get('snapshot') and _parameter_evidence_review.evidence_context(region))
            basis = {'basis': 'observation_only', 'source_call': call, 'observation': ((state or {}).get('observation') or {}).get('id')}
            updates.store_increment(region, task, name, row, records, state or {}, basis, observed=observed)
            continue
        row = {**row, 'name': settlement.task_definition(row)['label'],
               'control': renamed.get(row['control'], row['control'])}
        names = [cid for (cid, c) in owned_controls(region).items() if c['name'] == row['control']]
        if not row['control']:
            names = [None]
        if len(names) != 1:
            raise ValueError('新任务须绑定本区块已登记控件或合法区块操作')
        name = row['name'].strip()
        cid = names[0]
        if not name:
            raise ValueError('任务问题缺失')
        task = {**{k: v for (k, v) in row.items() if k not in ('reason', 'remaining_question', 'retry_when')}, 'control': cid, 'status': row.get('status', 'pending'), 'source_call': call, 'attempts': []}
        same = [n for (n, t) in tasks.items() if t.get('control') == cid and settlement.registration_kind(t) == settlement.registration_kind(task)]
        if same:
            if len(same) != 1:
                raise ValueError('该控件有多个历史同类型任务，请引用本轮提供的旧任务')
            prior = same[0]
            existing = tasks[prior]
            seen.add(prior)
            if existing.get('status') in ('done', 'record_only'):
                from regrow.records.tasks import audit
                audit(existing).setdefault('revisions', []).append({'source_call': call, 'previous_status': existing['status'], 'reason': reply['evidence'], 'change': 'selected_for_further_exploration'})
                existing['status'] = 'pending'
            continue
        if name in tasks:
            name = (cid or region['id']) + ' / ' + name
            if name in tasks:
                raise ValueError('已有同对象问题，请引用已有任务')
        seen.add(name)
        if settlement.region_task(task) and state:
            task['navigation_observation'] = (state.get('observation') or {}).get('id')
        tasks[name] = task
    if scope_review:
        missing_review = {n for (n, t) in old.items() if t.get('status') in ('pending', 'blocked')} - seen
        if missing_review:
            raise ValueError('旧任务范围复核遗漏未完成任务：' + '、'.join(sorted(missing_review)))
    for (name, t) in tasks.items():
        if t.get('equivalent_to'):
            canonical = _record_equivalent_source(tasks, t)
            if not canonical or settlement.registration_kind(canonical) != settlement.registration_kind(t) or name == t['equivalent_to']:
                raise ValueError('等价任务须引用同类问题的直接代表；参数、入口语义与普通控件用途不能互相替代')
    replace_owned_tasks(region, tasks)
    _shared_controls.refresh(records)
    tasks = owned_tasks(region)
    region_work(region)['task_inventory'] = {'inventory': reply['inventory'], 'evidence': reply['evidence'], 'controls': sorted(considered), 'source_call': call}

def commit_plan(root, run, call):
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import discovery_step as _discovery_step
    reg = _register_update
    discovery = _discovery_step
    (q, reply) = _owner_submission(run, call)
    rid = q['source']['region']
    if q.get('role') == 'task_correction':
        reply = reply['proposal']

    def mutate(records, state, snapshot, temp):
        from regrow.traversal import historical_inventory as _historical_inventory
        from regrow.records import task_updates as _task_updates
        from regrow.traversal import task_prerequisites as _task_prerequisites
        from regrow.records import tasks as _task_records
        from regrow.records import entry_observation as _entry_observation
        from regrow.traversal import inventory_scroll as _inventory_scroll
        inventory_review = region_work(records[rid]).get('task_inventory', {}).get('review', {})
        fact_review = q['source'].get('parameter_fact_review')
        if fact_review:
            current = region_work(records[rid]).get('task_inventory', {}).get('review', {})
            if current.get('kind') != 'parameter_facts' or any((current.get(k) != v for (k, v) in fact_review.items())):
                raise ValueError('参数事实补登记依据已变化，需刷新原任务清点')
        if q.get('historical_inventory'):
            _historical_inventory.validate(_record_load(run)[1][rid], q)
        elif state['observation']['id'] != q['source']['observation'] or rid not in state['interactive_regions']:
            raise ValueError('task inventory belongs to an old observation')
        apply_plan(records[rid], reply, call, scope_review='task_scope_review' if q.get('task_scope_review') else q.get('external_scope_review', False), records=records, state=None if q.get('historical_inventory') else state, reviewed_controls=q['source'].get('controls'))
        _task_prerequisites.enroll(records, rid, call)
        active = state.get('active_task') or {}
        if active.get('region') == rid and owned_tasks(records[rid]).get(active.get('name'), {}).get('status') == 'done':
            state.pop('active_task', None)
        exception = 'none' if q.get('historical_inventory') else (state.get('observation') or {}).get('foreground', {}).get('exception', 'none')
        if exception in ('blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'unclassified'):
            for task in owned_tasks(records[rid]).values():
                if _task_records.read(task, 'source_call') == call and task['status'] == 'blocked':
                    task['blocker'] = {'condition': 'foreground_exception', 'exception': exception, 'source_call': call}
        region_work(records[rid]).get('registration_gaps', {}).pop('task_proposal', None)
        if _entry_observation.unresolved_review(records[rid], inventory_review, state, q['screenshots'][0], reply['evidence']):
            return
        if reply['inventory'] != 'complete' and (not q.get('historical_inventory')):
            scroll = _inventory_scroll.select(records[rid], reply) if exception == 'none' else None
            if scroll:
                state.update(next_action_mode='explore', phase='ready_for_next_action', active_task={'region': rid, 'name': scroll})
                state.pop('required_control', None)
                return
            if _record_coverage(records[rid], records)['pending']:
                state.update(next_action_mode='explore', phase='ready_for_next_action')
                state.pop('required_control', None)
                return
            state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=q['screenshots'][0], discovery_mode='local', inspection_region=rid, reason='task_inventory_incomplete')
            state.pop('correction_context', None)
            state.pop('required_control', None)
    return _record_publish(run, 'task-plan-' + call, mutate)
