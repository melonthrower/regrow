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
from regrow.records.object_store import owned_controls
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

def commit_update(root, run, call_ref, attempt_ref):
    from regrow.recognition import region_identity as _region_identity
    from regrow.traversal import result_updater as _result_updater
    from regrow.records import snapshots as _knowledge_transaction
    from regrow.recognition import control_identity_review as _control_identity_review
    from regrow.traversal import action_context as _stepwise_flow
    from regrow.traversal import suspended_updates as _suspended_updates
    from regrow.records import region_records as _region_records
    from regrow.recognition import region_candidate_names as _region_candidate_names
    from regrow.records import region_behavior_split as _region_behavior_split
    from regrow.records import registration_diagnostics as _registration_diagnostics
    from regrow.recognition import update_visibility as _update_visibility
    from regrow.recognition import matching as _image_match
    from regrow.records import task_updates as _task_updates
    from regrow.records import control_context as _control_context
    from regrow.traversal import task_prerequisites as _task_prerequisites
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
    ordinary_back = dispatch.get('action', {}).get('action') == 'back'
    ordinary_scroll = dispatch.get('action', {}).get('action') in ('scroll', 'wait', 'key_press', 'hotkey')
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
    pinned = _record_action_source_observation(run, dispatch.get('source_call'), edge['before_observation'], source, control)
    if pinned:
        before = pinned
        _record_write_json(run / f'calls/{call_ref}/source_observation.json', pinned)
    current = run / 'knowledge_current.json'
    payload = {'record_format': 'flat_region_controls', 'graph': graph, 'reply': reply, 'receipt': receipt, 'call': call_ref, 'attempt': attempt_ref}
    payload['edge'] = edge
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
    suspended = _suspended_updates
    historical = suspended.validate_commit(run, attempt_ref, reply, request, binding, snapshot, records)
    coordinate_action = control is None and binding.get('association', {}).get('status') == 'unconfirmed'
    if source not in records or (not coordinate_action and (not ordinary_back) and (not ordinary_scroll) and (control not in owned_controls(records[source]))):
        raise ValueError('action source control is missing from its Region')
    owner = records[source]
    aliases = {old['id']: rid for (rid, r) in records.items() for old in r.get('merged_records', []) if old['id'] not in records}
    working_ref = aliases.get(working_ref, working_ref)
    binding = _region_records.rewrite(binding, aliases)
    working = records[working_ref]
    if ordinary_scroll:
        if control is not None:
            raise ValueError('invalid Region scroll owner')
    elif ordinary_back:
        if control is not None:
            raise ValueError('invalid region-owned return')
    region_changes = []
    for item in reply['previous_regions']:
        r = records[_region_candidate_names.resolve(records, item['ref'], request.get('region_names'))]
        region_changes.append({'region': r['id'], 'state': item['state'], 'evidence': item['evidence']})
        if item.get('task_review_reason', '').strip() and region_work(r).get('task_inventory'):
            region_work(r)['task_inventory']['review'] = {'reason': item['task_review_reason'], 'source_call': call_ref}
    split = reply.get('source_region_split')
    split_payload = None
    split_record = None
    original_source = source
    if split:
        if reply['action_result']['exception'] != 'none' or not edge.get('before_image'):
            raise ValueError('行为分离需要正常动作结果和真实动作前截图')
        splitter = _region_behavior_split
        geometry = splitter.before_objects(records[source], {'control_ref': control, 'observation_ref': edge['before_observation']}, snapshot, run / edge['before_image'])
        split = splitter.bind_geometry(split, geometry)
        (source, control, split_payload) = _region_behavior_split.apply(records, source, split, call_ref, edge['before_observation'], attempt_ref, frame=run / edge['before_image'])
        owner = records[source]
        split_record = deepcopy(owner)
        edge.update(source_region=source, source_control=control)
        for change in region_changes:
            if change['region'] == original_source:
                change['region'] = source
        for (i, p) in enumerate(reply['regions']):
            if p['name'] == split['name']:
                p['ref'] = source
                p['_matched_id'] = source
                for c in reply['controls']:
                    if c['region_index'] == i and (not c.get('ref')):
                        names = [v['name'] for v in owned_controls(owner).values()]
                        if c['name'] in names:
                            c['ref'] = next((cid for (cid, v) in owned_controls(owner).items() if v['name'] == c['name']))
        if working_ref == original_source:
            working_ref = source
    delta_refs = _owner_materialize_regions(records, reply, call_ref, edge['after_observation'], request.get('region_names'), frame=run / edge['after_image'] if edge.get('after_image') else None)
    _registration_diagnostics.check_visibility(reply, delta_refs, region_changes)
    visibility = _update_visibility
    region_refs = visibility.regions(delta_refs, region_changes, reply['action_result']['exception'])
    old_control_refs = visibility.locate_retained(records, [{'region': rid, 'state': 'changed_interactive'} for rid in region_refs], call_ref, snapshot, run / edge['after_image'] if edge.get('after_image') else None, _image_match, observation=edge['after_observation']) if region_refs else []
    association = deepcopy(binding.get('association'))
    a = rebase(_region_evidence.action_record(edge), run, snapshot)
    if split:
        a['association'] = {'status': 'confirmed_by_update', 'source_call': call_ref, 'original_region': original_source, 'original_control': binding.get('control_ref'), 'evidence': split['evidence']}
    elif association:
        a['association'] = association
    a['result'] = deepcopy(reply['action_result'])
    a['evidence'].update(result_call=call_ref, before_regions=before['region_refs'])
    a['interactive_regions'] = region_refs
    a['region_changes'] = region_changes
    if split:
        for (rid, r) in records.items():
            if rid != source:
                owned_actions(r).pop(attempt_ref, None)
    owned_actions(owner)[attempt_ref] = a
    from regrow.records.task_settlement import register_destinations
    for r in records.values():
        r['transitions'] = [e for e in r['transitions'] if e['attempt'] != attempt_ref]
    changed = {p['region'] for p in region_changes if p['state'] == 'changed_interactive'}
    if reply['action_result']['exception'] == 'none':
        for target in region_refs:
            if target != source and (target not in before['region_refs'] or target in changed):
                relation = {'source_control': control, 'target_region': target, 'attempt': attempt_ref, 'relation': 'observed_interactive_candidate'}
                owner['transitions'].append(relation)
    _record_attach_execution(records, run)
    original_task_ref = _task_updates.reference(binding.get('task_region', source), binding.get('task_name', ''))
    if split:
        binding = _control_context.migrate_split_task(records, binding, source, control, attempt_ref)
    effective_binding = {**binding, 'region_ref': source, 'control_ref': control, 'task_update_ref': original_task_ref}
    _task_prerequisites.apply(records, reply, call_ref, request.get('dependency_candidates', []))
    _record_settle_task(records[binding.get('task_region', source)], effective_binding, reply, attempt_ref, records, receipt=receipt, labels=request.get('region_names'), candidates=request.get('task_update_candidates'))
    register_destinations(reply.get('jump_to'), records, delta_refs, reply['controls'], owner, attempt_ref, call_ref)
    binding = effective_binding
    for region in records.values():
        for action in owned_actions(region).values():
            if navigation.contextual_return(action):
                action['destination_behavior'] = 'history_dependent'
                action['navigation_description'] = navigation.navigation_description(action)
        for transition in region['transitions']:
            if navigation.contextual_return(owned_actions(region).get(transition['attempt'], {})):
                transition['destination_behavior'] = 'history_dependent'
    state = {'update_status': 'committed', 'update_digest': digest, 'source_call': call_ref, 'attempt': attempt_ref, 'working_region': working_ref, 'interactive_regions': region_refs, 'last_action_result': {'region': source, 'action': attempt_ref}, 'next_action_mode': branch['next_action_mode'], 'reason': branch['reason'], 'handoff_summary': reply['handoff_summary'], 'phase': 'ready_for_next_action', 'execution_status': 'not_started', 'observation': {'id': edge['after_observation'], 'image': edge.get('after_image'), 'control_refs': [cid for ref in region_refs for (cid, c) in owned_controls(records[ref]).items() if frame_observation(c, kind='controls', call=call_ref, observation=edge['after_observation'])] + old_control_refs, 'foreground': reply['foreground'], 'uncertainties': reply['uncertainties']}}
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
    if reply['action_result']['exception'] == 'none' and reply['regions'] and (not region_refs) and edge.get('after_image'):
        state.update(next_action_mode='discover', phase='awaiting_discovery', discovery_mode='relocate', pending_frame=edge['after_image'], reason='observed_region_interactivity_unconfirmed')
    state['exception'] = reply['action_result']['exception']
    state['recovery_handoff'] = reply['action_result'].get('recovery_handoff', '')
    if historical:
        suspended.complete(records, previous_state, state, historical, call_ref, attempt_ref)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.pending-', dir=snapshot.parent))
    try:
        if split_payload:
            _owner_save_region_images({source: split_record}, [source], split_payload, call_ref, run, edge['before_image'], snapshot, temp, image_tag=call_ref + '/source')
            observation_history(records[source])[0] = observation_history(split_record)[0]
            for (cid, c) in owned_controls(split_record).items():
                observation_history(owned_controls(records[source])[cid])[0] = observation_history(c)[0]
        _owner_save_region_images(records, delta_refs, reply, call_ref, run, edge.get('after_image'), snapshot, temp,
                                  observation=edge['after_observation'], update_images=True,
                                  text_control=control if dispatch.get('action', {}).get('action') == 'input_text' else None)
        from regrow.records.snapshots import commit as commit_snapshot
        source_record = {'record_format': 'flat_region_controls', 'graph': None, 'call': call_ref, 'attempt': attempt_ref, 'digest': digest, 'parent_snapshot': parent_snapshot}
        commit_snapshot(run, temp, snapshot, records, state, source_record, pointer)
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    return pointer
