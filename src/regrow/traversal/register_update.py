"""Coordinate a real dispatched action result; records owns materialization and publication."""
from regrow.records import navigation
from regrow.records import region_evidence as _region_evidence
from regrow.records.calls import submission as _owner_submission
from regrow.records.observations import materialize_regions as _owner_materialize_regions
from regrow.records.observations import save_region_images as _owner_save_region_images
from regrow.records.observations import frame_observation
from regrow.records.task_settlement import settle_task as _record_settle_task
from regrow.records.snapshots import read as _record_read
from regrow.records.snapshots import write_json as _record_write_json
from regrow.records.action_evidence import action_source_observation as _record_action_source_observation
from regrow.records.action_evidence import attach_execution as _record_attach_execution
from regrow.paths import SOURCE_ROOT
from regrow.records.object_store import region_work
from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
from regrow.records.object_store import owned_controls, owned_tasks
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

def rebase(value, old_base, new_base):
    """Only path-bearing evidence fields; never rewrite descriptive text."""
    return object_store.rebase(value, old_base, new_base)


def gap_owner(run, records, request, reply, region_refs, gap, call_ref):
    """Resolve a gap through the array in its own saved call, never a later one."""
    if gap.get('kind') != 'control':
        return None
    index = gap.get('proposal', {}).get('region_index')
    if type(index) is not int:
        return None
    origin = gap.get('source_call') or call_ref
    if origin == call_ref:
        indexes = request.get('registration_source_indices', {}).get('regions', list(range(len(reply.get('regions', [])))))
        return region_refs[indexes.index(index)] if index in indexes else None
    try:
        original, candidate = _owner_submission(run, origin)
    except (OSError, ValueError):
        return None
    rows = candidate.get('regions', [])
    indexes = original.get('registration_source_indices', {}).get('regions', list(range(len(rows))))
    if index not in indexes:
        return None
    row = rows[indexes.index(index)]
    ref = original.get('region_names', {}).get(row.get('ref'), row.get('ref'))
    if ref in records:
        return ref
    # A new Region had no stable ID before the corrected update was committed.
    # Only one same-named Region in this accepted result can supply its owner.
    matches = [rid for rid in region_refs if row.get('name') and records[rid]['name'] == row['name']]
    return matches[0] if len(matches) == 1 else None

def commit_update(root, run, call_ref, attempt_ref):
    from regrow.recognition import region_identity as _region_identity
    from regrow.traversal import result_updater as _result_updater
    from regrow.records import snapshots as _knowledge_transaction
    from regrow.recognition import control_identity_review as _control_identity_review
    from regrow.traversal import action_context as _stepwise_flow
    from regrow.traversal import suspended_updates as _suspended_updates
    from regrow.records import region_records as _region_records
    from regrow.recognition import region_candidate_names as _region_candidate_names
    from regrow.records import registration_diagnostics as _registration_diagnostics
    from regrow.recognition import update_visibility as _update_visibility
    from regrow.recognition import matching as _image_match
    from regrow.records import task_updates as _task_updates

    from regrow.traversal import task_routing as _task_routing
    (root, run) = (Path(root), Path(run).resolve())
    graph = {'action_edges': [], 'observations': []}
    (request, reply) = _owner_submission(run, call_ref)
    receipt = _record_read(run / f'action_attempts/{attempt_ref}/receipt.json')
    saved_schema = run / f'calls/{call_ref}/response.schema.json'
    branch = _result_updater.route_update(root, reply, receipt, schema=request.get('response_schema') or (_record_read(saved_schema) if saved_schema.exists() else None))
    if branch['status'] != 'validated_candidate':
        raise ValueError('execution is not confirmed; no exploration update committed')
    if (run / 'knowledge_current.json').exists():
        (reply, identity_audit) = _region_identity.for_request(run, request, reply)
        if identity_audit:
            _record_write_json(run / f'calls/{call_ref}/visual_identity.json', {'matches': identity_audit, 'effective_candidate': reply})
    dispatch_path = run / f'action_attempts/{attempt_ref}/dispatch.json'
    dispatch = _record_read(dispatch_path) if dispatch_path.exists() else {}
    if dispatch.get('recovery'):
        raise ValueError('recovery actions must not use business update registration')
    binding = {}
    binding = _record_read(run / f'action_attempts/{attempt_ref}/binding.json')
    dispatch = _record_read(run / f'action_attempts/{attempt_ref}/dispatch.json')
    images = [str(Path('action_attempts') / attempt_ref / (when + '.png')) for when in ('before', 'after')]
    from regrow.prompts.frame_context import primary
    sent = primary(request)
    if binding.get('status') != 'matched' or len(images) < 2 or dispatch.get('source_region') != binding['region_ref'] or (dispatch.get('source_control') != binding['control_ref']) or (not sent) or ((run / sent).resolve() != (run / images[1]).resolve()):
        raise ValueError('action binding, dispatch and update images do not agree')
    if not all(((run / p).is_file() for p in images)):
        raise ValueError('missing action evidence image')
    edge = {'attempt': attempt_ref, 'source_region': binding['region_ref'], 'source_control': binding['control_ref'], 'before_observation': binding['observation_ref'], 'after_observation': f'update:{call_ref}', 'before_image': images[0], 'after_image': images[1], 'selection_call': dispatch['source_call'], 'result_call': call_ref, 'delivery': 'executed_receipt_zero'}
    (source, control) = (edge['source_region'], edge['source_control'])
    working_ref = binding.get('working_region', source)
    pinned = _record_action_source_observation(run, dispatch.get('source_call'), edge['before_observation'], source, control,
                                              source_field=dispatch.get('source_field'))
    if pinned:
        before = pinned
        _record_write_json(run / f'calls/{call_ref}/source_observation.json', pinned)
    current = run / 'knowledge_current.json'
    payload = {'record_format': 'flat_region_controls', 'graph': graph, 'reply': reply, 'receipt': receipt, 'call': call_ref, 'attempt': attempt_ref}
    payload['edge'] = edge
    if request.get('registration_gaps'):
        payload['registration_gaps'] = request['registration_gaps']
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    snapshot_ref = f'knowledge_snapshots/{attempt_ref}-{call_ref}-{digest[:12]}'
    snapshot = run / snapshot_ref
    pointer = {'snapshot': snapshot_ref, 'update_call': call_ref, 'attempt': attempt_ref, 'sha256': digest}
    current = run / 'knowledge_current.json'
    parent_snapshot = _record_read(current)['snapshot'] if current.exists() else None
    if snapshot.exists():
        if _record_read(snapshot / 'runtime_state.json')['update_digest'] != digest:
            raise ValueError('snapshot collision')
        saved_parent = _record_read(snapshot / 'source.json').get('parent_snapshot')
        if parent_snapshot == saved_parent:
            tmp_pointer = run / 'knowledge_current.pending.json'
            _record_write_json(tmp_pointer, pointer)
            os.replace(tmp_pointer, _knowledge_transaction.pointer(current))
        return pointer
    if current.exists():
        _control_identity_review.check_request(run, request, reply)
    if not current.exists():
        raise ValueError('current record snapshot is required before registering an action')
    prior = run / _record_read(current)['snapshot']
    records = rebase(object_store.load(prior), prior, snapshot)
    from regrow.records.control_images import label_appearances
    label_appearances(records, snapshot, request.get('appearance_labels', []))
    suspended = _suspended_updates
    historical = suspended.validate_commit(run, attempt_ref, reply, request, binding, snapshot, records)
    coordinate_action = control is None and binding.get('association', {}).get('status') == 'unconfirmed'
    from regrow.records.function_evidence import region_action
    region_owned = region_action({'control': control, 'operation': dispatch.get('action', {}).get('action'),
                                 'association': binding.get('association')})
    if source not in records or (not coordinate_action and not region_owned and control not in owned_controls(records[source])):
        raise ValueError('action source control is missing from its Region')
    owner = records[source]
    aliases = {old['id']: rid for (rid, r) in records.items() for old in r.get('merged_records', []) if old['id'] not in records}
    working_ref = aliases.get(working_ref, working_ref)
    binding = _region_records.rewrite(binding, aliases)
    working = records[working_ref]
    region_changes = _update_visibility.historical_changes(reply, records, request.get('region_names'))
    delta_refs = _owner_materialize_regions(records, reply, call_ref, edge['after_observation'], request.get('region_names'), frame=run / edge['after_image'] if edge.get('after_image') else None)
    _registration_diagnostics.check_visibility(reply, delta_refs, region_changes, request.get('region_names'))
    visibility = _update_visibility
    from regrow.records.object_knowledge import observed_refs
    if 'current_regions' in reply:
        members = visibility.current_refs(reply, records, delta_refs, request.get('region_names'))
        region_refs = list(dict.fromkeys(members))
        from regrow.records.observations import observe_current_regions
        observe_current_regions(records, members, call_ref, edge['after_observation'])
    else:
        region_refs = visibility.regions(observed_refs(reply, delta_refs), region_changes, reply['action_result']['exception'])
    if not historical:
        # Release old observation gaps before this reply settles tasks anew.
        from regrow.traversal.task_deferral import resume_localized
        target_retries = {(rid, name): task['deferral'].get('source_call')
                          for rid, region in records.items() for name, task in owned_tasks(region).items()
                          if task.get('status') == 'blocked'
                          and task.get('deferral', {}).get('retry_when') == 'target_identity_or_changed_surface'}
        resume_localized(records, region_refs, call_ref, foreground=reply['foreground'],
                         run=run, frame=run / edge['after_image'] if edge.get('after_image') else None, snapshot=snapshot)
    for rid in region_refs:
        gap = region_work(records[rid]).get('registration_gaps', {}).get('task_proposal')
        if gap:
            gap['recheck_after'] = call_ref
    old_control_refs = visibility.locate_retained(records, region_refs, call_ref, snapshot, run / edge['after_image'] if edge.get('after_image') else None, _image_match, observation=edge['after_observation']) if region_refs else []
    association = deepcopy(binding.get('association'))
    a = rebase(_region_evidence.action_record(edge), run, snapshot)
    if association:
        a['association'] = association
    a['result'] = deepcopy(reply['action_result'])
    a['evidence'].update(result_call=call_ref, before_regions=before['region_refs'])
    a['interactive_regions'] = region_refs
    a['region_changes'] = region_changes
    if 'current_regions' in reply:
        a['observed_destinations'] = []
    owned_actions(owner)[attempt_ref] = a
    from regrow.records.task_settlement import register_destinations
    for r in records.values():
        r['transitions'] = [e for e in r['transitions'] if e['attempt'] != attempt_ref]
    changed = {p['region'] for p in region_changes if p['state'] == 'changed_interactive'}
    if 'current_regions' not in reply and reply['action_result']['exception'] == 'none':
        for target in region_refs:
            if target != source and (target not in before['region_refs'] or target in changed):
                relation = {'source_control': control, 'target_region': target, 'attempt': attempt_ref, 'relation': 'observed_interactive_candidate'}
                owner['transitions'].append(relation)
    _record_attach_execution(records, run)
    original_task_ref = _task_updates.reference(binding.get('task_region', source), binding.get('task_name', ''))
    effective_binding = {**binding, 'region_ref': source, 'control_ref': control, 'task_update_ref': original_task_ref}

    from regrow.records.function_updates import apply_for_request
    apply_for_request(records, request, reply, {'source_call':call_ref, 'attempt':attempt_ref})
    settlement_reply = reply
    if request.get('task_update_candidates') == [] and 'task_update' not in request['response_schema'].get('properties', {}):
        settlement_reply = {**reply, 'task_update': []}
    if historical:
        suspended.release_result_block(records, historical, call_ref, attempt_ref)
    _record_settle_task(records[binding.get('task_region', source)], effective_binding, settlement_reply, attempt_ref, records, receipt=receipt, labels=request.get('region_names'), candidates=request.get('task_update_candidates'))
    destinations = _region_records.rewrite(reply.get('jump_to'), aliases)
    register_destinations(destinations, records, delta_refs, reply['controls'], owner, attempt_ref, call_ref,
                          regions=reply['regions'])
    navigation.bind_return(records, source, attempt_ref)
    for target in a.get('observed_destinations', []):
        if target != source:
            owner['transitions'].append({'source_control': control, 'target_region': target,
                'attempt': attempt_ref, 'relation': 'observed_interactive_candidate'})
    binding = effective_binding
    for region in records.values():
        for action in owned_actions(region).values():
            if navigation.contextual_return(action):
                action['destination_behavior'] = 'history_dependent'
                action['navigation_description'] = navigation.navigation_description(action)
        for transition in region['transitions']:
            if navigation.contextual_return(owned_actions(region).get(transition['attempt'], {})):
                transition['destination_behavior'] = 'history_dependent'
    state = {'update_status': 'committed', 'update_digest': digest, 'source_call': call_ref, 'attempt': attempt_ref, 'working_region': working_ref, 'interactive_regions': region_refs, 'last_action_result': {'region': source, 'action': attempt_ref}, 'next_action_mode': branch['next_action_mode'], 'reason': branch['reason'], 'phase': 'ready_for_next_action', 'execution_status': 'not_started', 'observation': {'id': edge['after_observation'], 'image': edge.get('after_image'), 'control_refs': [cid for ref in region_refs for (cid, c) in owned_controls(records[ref]).items() if frame_observation(c, kind='controls', call=call_ref, observation=edge['after_observation'])] + old_control_refs, 'foreground': reply['foreground']}}
    if old_control_refs:
        state['visual_navigation'] = {'observation': edge['after_observation'], 'controls': {cid: rid for rid in region_refs for cid in old_control_refs if cid in owned_controls(records[rid])}, 'evidence': 'retained controls matched against current after-image'}
    previous_state = _record_read(prior / 'runtime_state.json') if current.exists() else {}
    if previous_state.get('discovery_completion_history'):
        state['discovery_completion_history'] = deepcopy(previous_state['discovery_completion_history'])
    batch = previous_state.get('discovery_completion')
    if batch and batch.get('pending'):
        state.setdefault('discovery_completion_history', []).append(deepcopy(batch))
    if not historical:
        _task_routing.advance(records, previous_state, state, source, binding, attempt_ref)
        for key in ('suspended_updates', 'suspended_update_history'):
            if key in previous_state:
                state[key] = deepcopy(previous_state[key])
    if (reply['action_result']['exception'] == 'none' and not region_refs and edge.get('after_image')
            and (reply['regions'] or any(gap.get('kind') == 'region' for gap in request.get('registration_gaps', [])))):
        state.update(next_action_mode='discover', phase='awaiting_discovery', discovery_mode='relocate', pending_frame=edge['after_image'], reason='observed_region_interactivity_unconfirmed')
    state['exception'] = reply['action_result']['exception']
    state['recovery_handoff'] = reply['action_result'].get('recovery_handoff', '')
    if historical:
        suspended.complete(records, previous_state, state, historical, call_ref, attempt_ref)
    from regrow.traversal.pending_action import retain
    retain(state, records, request, reply, binding, call_ref, snapshot_ref, historical=bool(historical))
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.pending-', dir=snapshot.parent))
    try:
        observed_regions = list(dict.fromkeys(delta_refs + region_refs)) if 'current_regions' in reply else delta_refs
        _owner_save_region_images(records, observed_regions, reply, call_ref, run, edge.get('after_image'), snapshot, temp,
                                  observation=edge['after_observation'], update_images=True,
                                  text_control=control if dispatch.get('action', {}).get('action') == 'input_text' else None)
        indexes = request.get('registration_source_indices', {})
        from regrow.records.observations import restore_source_indices
        restore_source_indices(records, observed_regions, indexes, call_ref, edge['after_observation'])
        if not historical and target_retries:
            # New control crops now exist. Only revisit old target gaps still
            # unchanged by this reply's task settlement; never undo a new defer.
            resume_localized(records, region_refs, call_ref, foreground=reply['foreground'],
                             run=run, frame=run / edge['after_image'] if edge.get('after_image') else None,
                             snapshot=temp, retry_targets=target_retries)
        for gap in request.get('registration_gaps', []):
            owner_ref = gap_owner(run, records, request, reply, delta_refs, gap, call_ref) or source
            work = region_work(records[owner_ref])
            saved = work.setdefault('registration_gaps', {}).setdefault('discovery', {'pending': []})
            saved['pending'].append({'source_call': call_ref, 'source_observation': edge['after_observation'],
                                     'source_frame': edge['after_image'], **deepcopy(gap)})
            saved.update(source_call=call_ref, observation=edge['after_observation'], frame=edge['after_image'])
        from regrow.records.snapshots import commit as commit_snapshot
        source_record = {'record_format': 'flat_region_controls', 'graph': None, 'call': call_ref, 'attempt': attempt_ref, 'digest': digest, 'parent_snapshot': parent_snapshot}
        commit_snapshot(run, temp, snapshot, records, state, source_record, pointer)
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    return pointer
