"""Task-relative views and direct Region coverage, derived from the existing graph."""
from collections import Counter


def region_coverage(ledger, region_id, declaration=None):
    declaration = declaration or {}
    selected = declaration.get('operations')
    restricted = declaration.get('restricted', {})
    conditions = declaration.get('conditions', {})
    groups = {}
    for op in ledger.operations.values():
        if op.region_id == region_id:
            groups.setdefault(op.canonical_operation_id or op.operation_id, []).append(op)
    rows = []
    for ref, bindings in groups.items():
        statuses = {op.status for op in bindings}
        identity = ledger.canonical_operations.get(ref)
        valid_identity = identity is not None and identity.region_id == region_id and all(
            op.operation_id in identity.operation_ids and op.action == identity.action
            and op.scope == identity.scope and op.direction == identity.direction for op in bindings)
        if selected is not None and ref not in selected:
            state, reason = 'out_of_scope', 'Outside this declared direct-operation scope'
        elif ref in restricted:
            state, reason = 'restricted', restricted[ref]
        elif ref in conditions:
            state, reason = 'pending_condition', conditions[ref]
        elif not valid_identity:
            state, reason = 'unknown_identity', 'Region/Operation identity is not confirmed'
        elif 'verified' in statuses:
            state, reason = 'verified', next(op.result for op in bindings if op.status == 'verified')
        elif statuses & {'pending', 'active'}:
            state, reason = 'pending', bindings[0].reason
        elif 'failed' in statuses:
            state, reason = 'failed', next(op.reason for op in bindings if op.status == 'failed')
        elif 'deferred' in statuses:
            # Existing records have natural-language reasons, not a trustworthy
            # condition-vs-permission classifier. Do not guess from control names.
            state, reason = 'blocked_unclassified', next(op.reason for op in bindings if op.status == 'deferred')
        elif 'cancelled' in statuses:
            state, reason = 'restricted', bindings[0].reason
        else:
            state, reason = 'observed_only', bindings[0].reason
        rows.append({'operation_ref': ref, 'target': bindings[0].target, 'status': state,
                     'reason': reason, 'bindings': [op.operation_id for op in bindings]})
    occurrences = [o for o in ledger.occurrences.values() if o.region_id == region_id]
    from .tasks import deferred_inventory_reports
    inventory_gaps = [gap for state, gap in deferred_inventory_reports(ledger).items()
        if gap.get('issue_kind') == 'independent_omission'
        and (region_id in gap.get('region_ids', []) or any(o.state_id == state for o in occurrences))]
    variants = {o.variant_id for o in occurrences}
    surveyed = bool(occurrences) and all(any(ledger.states[o.state_id].survey_complete
        for o in occurrences if o.variant_id == variant) for variant in variants)
    direct_ids = {op.operation_id for bindings in groups.values() for op in bindings}
    pending = any(a.outcome == 'pending' and (a.action.get('operation_ref') in direct_ids
        or (a.task_id in ledger.tasks and ledger.tasks[a.task_id].operation_id in direct_ids))
        for a in ledger.attempts.values())
    counts = Counter(row['status'] for row in rows)
    obligations = [row for row in rows if row['status'] != 'out_of_scope']
    children = {o.region_id for o in ledger.occurrences.values()
        if o.parent_occurrence_id in ledger.occurrences
        and ledger.occurrences[o.parent_occurrence_id].region_id == region_id and o.region_id != region_id}
    for edge in ledger.transitions:
        operation = ledger.operations.get(edge.action.get('operation_ref', ''))
        attempt = ledger.attempts.get(edge.attempt_id)
        if operation and operation.region_id == region_id and attempt and attempt.outcome == 'success':
            children.update(ref for ref in edge.revealed_region_ids if ref != region_id)
    child_refs = sorted(children)
    return {'region_ref': region_id, 'registered': len(rows), 'in_scope': len(obligations),
            **{key: counts[key] for key in ['verified', 'observed_only', 'pending', 'pending_condition',
                'restricted', 'blocked_unclassified', 'failed', 'out_of_scope', 'unknown_identity']},
            'survey_complete': surveyed, 'pending_settlement': pending,
            'inventory_gaps': inventory_gaps, 'missing_operation_count': None if inventory_gaps else 0,
            'direct_complete': surveyed and not pending and not inventory_gaps and not (set(selected or ()) - set(groups))
                and all(row['status'] == 'verified' for row in obligations),
            'operations': rows, 'scope_note': declaration.get('label', 'All discovered direct operations; descendants are separate'),
            'child_region_refs': child_refs,
            'child_regions_unfinished': sum(any(o.status != 'verified' for o in ledger.operations.values() if o.region_id == ref)
                or not any(ledger.states[o.state_id].survey_complete for o in ledger.occurrences.values() if o.region_id == ref)
                for ref in child_refs),
            'unknown_declared_refs': sorted(set(selected or ()) - set(groups))}


def region_signature(ledger, region_id):
    from .partition_review import active_revisits
    revisits = active_revisits(ledger)
    return tuple((o.operation_id, o.status, tuple(o.source_occurrence_ids), o.operation_id in revisits)
                 for o in ledger.operations.values() if o.region_id == region_id)


def environment_view(ledger, region_id, task=None, *, scale='region', declaration=None, pending=False):
    from .status import current_operation_binding
    parents = {}
    for occurrence in ledger.occurrences.values():
        parent = ledger.occurrences.get(occurrence.parent_occurrence_id)
        if parent and parent.region_id != occurrence.region_id:
            parents.setdefault(occurrence.region_id, set()).add(parent.region_id)
    path = [region_id] if region_id else []
    while path and len(parents.get(path[0], ())) == 1:
        parent = next(iter(parents[path[0]]))
        if parent in path: break
        path.insert(0, parent)
    roots = path[:1]
    children = {}
    for child, parent_ids in parents.items():
        for parent in parent_ids: children.setdefault(parent, []).append(child)
    current_state = '' if pending else ledger.current_state_id
    visible = {o.region_id for o in ledger.state_occurrences(current_state)}
    def node(ref, seen):
        region = ledger.regions.get(ref)
        if region is None or ref in seen: return {'region_ref': ref, 'cross_reference': True}
        coverage = region_coverage(ledger, ref, declaration if ref == region_id else None)
        expanded = ref in path
        return {'region_ref': ref, 'name': region.name, 'summary': region.summary, 'current_foreground': ref in visible,
                'status': 'direct_complete' if coverage['direct_complete'] else 'unfinished',
                'expanded': expanded, 'collapsed_details_are_not_complete': not expanded,
                'children': [node(c, seen | {ref}) for c in children.get(ref, [])] if expanded else [],
                'operations': coverage['operations'] if ref == region_id else []}
    branches = []
    for occurrence in ledger.occurrences.values():
        if occurrence.region_id != region_id: continue
        state = ledger.states[occurrence.state_id]
        if scale != 'operation' and state.state_id != current_state: continue
        controls = []
        for element in ledger.variant_elements(occurrence.variant_id):
            observations = [o for o in element.observations if o.get('state_ref') == state.state_id]
            controls.append({'name': element.name, 'observation': observations[-1:],
                'current_owner_ref': element.element_id if state.state_id == current_state else '',
                'operations': [{'action': o.action, 'status': o.status, 'reason': o.reason}
                               for o in ledger.element_operations(element.element_id)]})
        branches.append({'state_ref': state.state_id, 'label': state.name, 'description': state.summary,
                         'current': state.state_id == current_state, 'controls': controls})
    binding = current_operation_binding(ledger, task.operation_id) if task and task.operation_id and not pending else None
    if binding is not None and binding.status == 'deferred': binding = None
    state = ledger.states.get(current_state)
    return {'physical_state_ref': current_state, 'source_state_ref': ledger.current_state_id if pending else '',
            'position_status': 'latest landing awaiting settlement' if pending else 'accepted State; verify against current image',
            'foreground_region_refs': sorted(visible),
            'physical_path': {'page_ref': state.page_id if state else '', 'state_name': state.name if state else '位置待确认',
                'regions': [{'region_ref': ref, 'name': ledger.regions[ref].name} for ref in sorted(visible)]},
            'work_region_ref': region_id, 'work_path': [{'region_ref': r, 'name': ledger.regions[r].name} for r in path],
            'current_subtask': task.reason if task else '', 'task_ref': task.task_id if task else '',
            'current_binding': {'operation_ref': binding.operation_id, 'owner_ref': binding.element_id or binding.region_id} if binding else None,
            'view_scale': scale, 'tree': [node(r, set()) for r in roots],
            'revealed_or_child_work': [{'region_ref': ref, 'name': ledger.regions[ref].name,
                'direct_complete': region_coverage(ledger, ref)['direct_complete'], 'details_collapsed': True}
                for ref in region_coverage(ledger, region_id, declaration)['child_region_refs'] if ref in ledger.regions],
            'observed_condition_states': branches,
            'condition_boundary': 'State labels/descriptions are observations, not inferred selector values or causal dependencies',
            'unobserved_conditions': 'Other values/conditions: names and effects not yet observed',
            'collapsed_condition_count': sum(o.region_id == region_id for o in ledger.occurrences.values()) - len(branches)}


def choose_region_task(scheduler, ledger):
    """Prefer applicable direct obligations; keep bounded return with the same Task."""
    from .status import current_operation_binding
    from .region_routes import plan_region_route
    ref = getattr(scheduler, 'work_region_id', '')
    if not ref or ref not in ledger.regions: return None
    coverage = region_coverage(ledger, ref, scheduler.region_declarations.get(ref))
    in_scope = {row['operation_ref'] for row in coverage['operations'] if row['status'] == 'pending'}
    from .partition_review import active_revisits
    revisits = active_revisits(ledger)
    in_scope.update(row['operation_ref'] for row in coverage['operations'] if row['status'] == 'blocked_unclassified'
        and any(ref in revisits for ref in row['bindings']))
    candidates = [t for t in ledger.tasks.values() if t.kind == 'explore_operation' and t.status in {'active','pending'}
                  and t.operation_id in ledger.operations and ledger.operations[t.operation_id].region_id == ref
                  and (ledger.operations[t.operation_id].canonical_operation_id or t.operation_id) in in_scope]
    held = ledger.current_task()
    def distance(task):
        op = ledger.operations[task.operation_id]
        binding = current_operation_binding(ledger, op.operation_id)
        if binding is not None and binding.status != 'deferred': return 0
        route = plan_region_route(ledger,current_state_id=ledger.current_state_id,
                                  target_region_id=ref,target_operation_id='' if op.operation_id in revisits else op.operation_id)
        return len(route['steps']) if route['status']=='ready' else 10**9
    if candidates:
        exits = scheduler.region_declarations.get(ref, {}).get('exit_operations', ())
        def closing(task):
            return ledger.operations[task.operation_id].canonical_operation_id in exits
        ordinary = [task for task in candidates if not closing(task)]
        choices = ordinary or candidates
        selected = held if held in choices and distance(held) < 10**9 else min(choices,key=lambda t:(distance(t),t.created_seq))
        if distance(selected) == 10**9:
            failed_return = any(a.task_id == selected.task_id and a.source_state_id == ledger.current_state_id
                                and a.outcome in {'no_effect','uncertain'} for a in ledger.attempts.values())
            entered = any(a.outcome=='success' and a.action.get('operation_ref') in ledger.operations
                          and ledger.operations[a.action['operation_ref']].region_id==ref
                          for a in ledger.attempts.values())
            if failed_return or not (entered or ref in scheduler.region_declarations):
                candidates = []
        if candidates:
            if held is not None and held is not selected and held.status=='active':
                held.status='pending'
                old_operation = ledger.operations.get(held.operation_id)
                if old_operation and old_operation.status == 'active': old_operation.status='pending'
                ledger.event('unreachable_focus_parked' if distance(held) == 10**9 else 'region_direct_task_selected', task_id=held.task_id, selected_task_id=selected.task_id,
                             state_id=ledger.current_state_id, reason='Prefer another applicable direct operation in the working Region')
            selected.status='active';ledger.current_task_id=selected.task_id
            return selected
    if held is not None and held.status=='active' and held.operation_id in ledger.operations and ledger.operations[held.operation_id].region_id==ref:
        held.status='pending';ledger.current_task_id=''
    scheduler.closed_region_signatures[ref]=region_signature(ledger,ref)
    scheduler.last_region_exit={'region_ref':ref,'status':'complete' if coverage['direct_complete'] else 'blocked',
                                'declaration': scheduler.region_declarations.get(ref),
                                'coverage':coverage,'reason':'Direct scope covered' if coverage['direct_complete'] else 'No applicable direct task or reliable return; obligations retained'}
    ledger.event('region_work_closed',**scheduler.last_region_exit)
    scheduler.work_region_id=''
    return None
