"""Register task proposals and hand their accepted results back to traversal."""
from regrow.records.calls import submission as _owner_submission
from regrow.records.tasks import coverage as _record_coverage
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records import task_settlement as _task_settlement
from regrow.records.object_store import region_work
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls

def apply_plan(region, reply, call, scope_review=False, records=None, state=None, reviewed_controls=None, request=None):
    from regrow.traversal.task_proposer import proposal_schema
    from regrow.records import task_assessments, task_plans, shared_controls
    from regrow.records.object_knowledge import apply as apply_knowledge
    from regrow.records.function_updates import apply_for_request
    from regrow.recognition.control_references import decode
    records = records or {region['id']: region}
    request = request or {'response_schema': proposal_schema()}
    task_assessments.envelope(reply, request['response_schema'])
    reply = decode(request, reply)
    basis = {'source_call': call, 'basis': 'observation_only', 'observation': (state or {}).get('observation', {}).get('id')}
    apply_knowledge(records, reply, basis)
    apply_for_request(records, request, reply, basis)
    renamed = shared_controls.propose_instances(records, region['id'], reply.get('shared_instances', []), call, state=state)
    assessment = task_plans.apply(region, reply, call, records=records, state=state,
        request=request, reviewed_controls=reviewed_controls, scope_review=scope_review, bindings=renamed)
    shared_controls.refresh(records)
    return assessment

def commit_plan(root, run, call):
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import discovery_step as _discovery_step
    reg = _register_update
    discovery = _discovery_step
    (q, reply) = _owner_submission(run, call)
    rid = q['source']['region']
    if q.get('role') == 'task_correction':
        reply = reply['proposal']

    assessments = {}
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
        from regrow.traversal import task_deferral
        assessments.update(apply_plan(records[rid], reply, call, scope_review='task_scope_review' if q.get('task_scope_review') else q.get('external_scope_review', False), records=records, state=None if q.get('historical_inventory') else state, reviewed_controls=q['source'].get('controls'), request=q))
        _task_prerequisites.enroll(records, rid, call)
        active = state.get('active_task') or {}
        if active.get('region') == rid and owned_tasks(records[rid]).get(active.get('name'), {}).get('status') == 'done':
            state.pop('active_task', None)
        exception = 'none' if q.get('historical_inventory') else (state.get('observation') or {}).get('foreground', {}).get('exception', 'none')
        if exception in ('blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'unclassified'):
            for task in owned_tasks(records[rid]).values():
                if _task_records.read(task, 'source_call') == call and task['status'] == 'blocked':
                    task['blocker'] = {'condition': 'foreground_exception', 'exception': exception, 'source_call': call}
        if _entry_observation.unresolved_review(records[rid], inventory_review, state, q['screenshots'][0], reply['evidence']):
            return
        state.update(next_action_mode='explore', phase='ready_for_next_action')
        state.pop('required_control', None)
    pointer = _record_publish(run, 'task-plan-' + call, mutate)
    from regrow.records.snapshots import write_json
    from pathlib import Path
    write_json(Path(run) / 'calls' / call / 'task_assessments.json', assessments)
    return {**pointer, 'task_assessments': assessments}
