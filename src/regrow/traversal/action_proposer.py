from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Render selected work and propose actions through the normal correction/binding path.'
from regrow.records.object_store import owned_controls
from regrow.recognition import identity_templates as templates
from regrow.records.tasks import coverage

def render_work(root, records, state, decision):
    """Build the selected request; no fallback selection or stop decisions here."""
    from regrow.traversal import work_context as _work_context
    from regrow.traversal import region_functions as _region_functions
    from regrow.records import task_settlement as _task_settlement
    from regrow.records import history_context as _task_action_context
    from regrow.traversal import inventory_scroll as _inventory_scroll
    from regrow.records import page_history as _page_history
    from regrow.traversal.action_context import _assemble_local_context
    from regrow.traversal.action_context import assemble_context
    from regrow.traversal.task_proposer import TaskProposer
    (kind, rid) = (decision['kind'], decision['region'])
    working = decision['working_region']
    work = _work_context.select(records, state, kind, rid, task=decision.get('task'))
    state = _work_context.reading_state(state, work)
    if kind in ('task_proposal', 'scope_review'):
        return TaskProposer.request(root, records, state, rid, scope_review=kind == 'scope_review', work=work)
    if kind == 'function_registration':
        q = _region_functions.request(root, records[rid], state, records)
        _work_context.attach(q, records, state, work)
        return q
    if kind == 'navigate':
        q = assemble_context(root, records, state, rid)
        _work_context.attach(q, records, state, work)
        return q
    if kind != 'action':
        return {'stage': 'scope_idle' if kind == 'idle' else kind, 'action_ready': False, 'reason': decision['reason'], 'source': {'region': rid, 'working_region': working}}
    region = records[rid]
    q = _assemble_local_context(root, records, state, rid)
    refs = decision.get('source_regions', [rid])
    if len(refs) > 1:
        q['backend_candidates'] = [{**candidate, 'region_ref': ref} for ref in refs for candidate in _assemble_local_context(root, records, state, ref)['backend_candidates']]
    q['source']['working_region'] = working
    q['pipeline_step'] = 'action'
    selected = decision['task']
    (task_region, name) = (selected['region'], selected['name'])
    task = owned_tasks(records[task_region])[name]
    target = _task_settlement.completion_target(records[task_region], task)
    cid = target['control']
    q['source'].update(task_name=name, task_region=task_region, task_type=_task_settlement.registration_kind(task), task_control=cid, completion_region=target['region'])
    q.update(preparation_allowed=True, allow_scroll=True, allow_input=True, region_target=region['name'], region_image=templates.image(region), region_image_assessment=templates.assessment(templates.latest(region) or {}))
    if rid != task_region:
        q['allow_back'] = True
    (material, q['context_evidence']) = _task_action_context.action_context(records, state, task_region, name, task)
    import json
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(material, ensure_ascii=False, indent=2)
    q['task_progress'] = coverage(region, records)
    if _inventory_scroll.active(records, state, rid):
        _inventory_scroll.restrict(q)
    _work_context.attach(q, records, state, work)
    return _page_history.attach(q, records, state)

def request_from_run(root, run, region_ref=None, task_ref=None, *, decision=None, frame=None):
    from regrow.records import action_candidates as _action_candidates
    from regrow.prompts import target_observation as _target_observation
    from regrow.prompts import prompt_material as _prompt_material
    from regrow.records import page_context as _page_context
    from regrow.prompts import frame_context as _frame_context
    from regrow.records import task_updates as _task_updates
    from regrow.records import task_settlement as _task_settlement
    from regrow.runtime import action_commands as _action_commands
    from regrow.traversal import operation_blocking as _operation_blocking
    from regrow.records.action_evidence import resolve_operations as resolve_action_operations
    from regrow.traversal.traversal_scheduler import select_work
    import json
    from pathlib import Path
    run = Path(run)
    pointer = json.loads((run / 'knowledge_current.json').read_text())
    snapshot = run / pointer['snapshot']
    source = json.loads((snapshot / 'source.json').read_text())
    if source.get('record_format') not in ('region_image_knowledge', 'flat_region_controls'):
        raise ValueError('historical record layout; rebuild saved evidence before reading current knowledge')
    records = object_store.load(snapshot)
    state = json.loads((snapshot / 'runtime_state.json').read_text())
    if state.get('next_action_mode') == 'discover':
        raise ValueError('discovery required before action context')
    if region_ref is None:
        region_ref = state['working_region']
    if task_ref:
        task = owned_tasks(records.get(task_ref['region'], {})).get(task_ref['name'])
        if not task or task.get('status') != 'pending':
            raise ValueError('原动作任务已不可继续，不能切换成其他任务')
        state['active_task'] = dict(task_ref)
        region_ref = task_ref['region']
    if (snapshot / 'recovery.json').exists():
        recovery = json.loads((snapshot / 'recovery.json').read_text())
        if recovery['actions']:
            state['recovery_arrival'] = recovery['actions'][-1]
    resolve_action_operations(records, run)
    for (ref, r) in records.items():
        for v in observation_history(r):
            if v.get('image'):
                v['image'] = str((snapshot / v['image']).resolve())
        for c in owned_controls(r).values():
            for v in observation_history(c):
                for field in ('image', 'icon_image'):
                    if v.get(field):
                        v[field] = str((snapshot / v[field]).resolve())
                if v.get('source_image'):
                    v['source_image'] = str((snapshot / v['source_image']).resolve())
    if state['observation'].get('image'):
        state['observation']['image'] = str((run / state['observation']['image']).resolve())
    if state.get('visual_navigation'):
        from regrow.recognition import visual_backtrack as navigation
        navigation.project(records, state)
    decision = decision or select_work(records, state, region_ref)
    result = render_work(root, records, state, decision)
    _action_candidates.attach_related(result, records, state)
    result = _target_observation.attach(result, records)
    _target_observation.attach_handoff(result, records, state, run)
    if state.get('navigation_handoff') and result.get('action_ready'):
        _prompt_material.assign(result, {'导航与准备交接': state['navigation_handoff']})
    result['source']['snapshot'] = pointer['snapshot']
    if result.get('stage') != 'task_proposal':
        _page_context.attach(result, records, state, run=run)
    if frame is not None and result['stage'] != 'function_registration':
        frames = [str(Path(frame).resolve())]
        result.update(screenshots=frames, image_refs=list(frames))
        _frame_context.label(result, frames[0], '本轮重新截取的当前图；供本步判断，历史观察与动作证据仍以各自来源为准')
        _page_context.refresh(result)
        if result.get('action_ready'):
            result = _target_observation.refresh(result)
    if result.get('action_ready'):
        source = result['source']
        name = source.get('task_name')
        rid = source.get('task_region')
        branches = result['response_schema']['properties']['operation']['anyOf']
        for branch in branches:
            if 'task_update' in branch.get('properties', {}):
                if name:
                    task = owned_tasks(records[rid])[name]
                    kind = _task_settlement.registration_kind(task)
                    update = _task_updates.schema([kind], [_task_updates.reference(rid, name)])
                    branch['properties']['task_update'] = update
        if not name:
            branches[:] = [b for b in branches if 'task_update' not in b.get('properties', {})]
    if result.get('action_ready'):
        result['response_schema'] = _action_commands.selection_schema(result['response_schema'])
    if result.get('action_ready') and result['source'].get('task_name'):
        from regrow.records.object_knowledge import fields
        edits = fields(records, [result['source']['task_region']])
        from regrow.records.function_updates import schema as function_schema, view
        from regrow.prompts.prompt_material import assign
        owner = result['source']['task_region']
        edits['function_updates'] = function_schema([owner])
        task = owned_tasks(records[owner])[result['source']['task_name']]
        refs = task.get('function_refs')
        rows = view(records, owner, refs)
        if rows:
            assign(result, {'当前任务相关功能': rows})
        for branch in result['response_schema'].get('anyOf', []):
            if set(branch.get('properties', {}).get('action', {}).get('enum', [])) & {'complete', 'none'}:
                branch['properties'].update(edits)
    return _operation_blocking.attach(result, records, state)

class ActionProposer:

    def __init__(self, repair):
        self.repair = repair

    def propose(self, request, resumed=None):
        from regrow.runtime import action_commands as _action_commands
        from regrow.prompts import frame_context as _frame_context
        request['role'] = 'action_selection'
        request['response_schema'] = _action_commands.selection_schema(request['response_schema'])
        if request.get('screenshots'):
            _frame_context.label(request, request['screenshots'][0], '本次动作选点依据图；尚未执行所选动作')
        return resumed if resumed and resumed['stage'] == 'action' else self.repair.perform('action', request)
