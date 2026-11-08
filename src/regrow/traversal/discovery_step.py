from regrow.records.calls import submission as _owner_submission
from regrow.records.observations import materialize_regions as _owner_materialize_regions
from regrow.records.observations import save_region_images as _owner_save_region_images
from regrow.records.observations import frame_observation
from regrow.records.tasks import coverage as _record_coverage
from regrow.records.snapshots import publish as _record_publish
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import read as _record_read
from regrow.records.snapshots import write_json as _record_write_json
from regrow.records.object_store import region_work
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import replace_observation_history
'First-stage observation and registration, also used after recovery.\n\nNo action effects or graph edges are created by this stage. Image persistence and\nRegion/control materialization are shared with ordinary action updates.\n'
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path
import jsonschema

def await_discovery(run, frame, evidence, handoff='', *, retain_target=False):
    """Recovery exit: retain work, invalidate old location; register no Regions."""
    if not (Path(run) / frame).is_file():
        raise ValueError('missing recovery frame')

    def mutate(records, state, snapshot, temp):
        if handoff and state.get('attempt'):
            note = '恢复观察（' + evidence + '）：' + handoff
            for region in records.values():
                for task in owned_tasks(region).values():
                    if state['attempt'] in task_value(task, 'attempts', []) and note not in task_value(task, 'result_evidence', ''):
                        task_audit(task)['result_evidence'] = task_value(task, 'result_evidence', '') + '\n' + note
                        prior = task.get('deferral', {})
                        if task.get('status') == 'blocked' and task.get('blocker', {}).get('exception') != 'unexpected_exit':
                            if prior.get('trigger', {}).get('source_call') != evidence:
                                if prior:
                                    task_audit(task).setdefault('deferral_history', []).append(prior)
                                task['deferral'] = {'trigger': {'kind': 'recovery', 'source_call': evidence}, 'reason': handoff, 'retry_when': 'explicit_result_review'}
        batch = state.pop('discovery_completion', None)
        if batch and batch.get('pending'):
            state.setdefault('discovery_completion_history', []).append(batch)
        state.pop('handoff_summary', None)
        from regrow.traversal.target_registration import reobserve
        retained = retain_target and reobserve(records, state, frame)
        if not retained and state.get('action_target_registration', {}).get('status') == 'pending':
            state['action_target_registration']['status'] = 'superseded'
        state.update(next_action_mode='discover', phase='awaiting_discovery', discovery_mode='relocate', interactive_regions=[], observation=None, pending_frame=frame, discovery_trigger=evidence, reason='recovery_finished_discovery_required', recovery_handoff=handoff)
    return _record_publish(run, 'await-discovery-' + evidence, mutate)

def commit(root, run, call_ref, *, ownership_episode=None):
    from regrow.recognition import discovery_completion as _discovery_completion
    from regrow.recognition import locator as _locator
    from regrow.traversal import traversal_scheduler as _traversal_scheduler
    from regrow.recognition import region_identity as _region_identity
    from regrow.records import registration_diagnostics as _registration_diagnostics
    run = Path(run).resolve()
    call = run / 'calls' / call_ref
    (request, reply) = _owner_submission(run, call_ref)
    raw_task_controls = deepcopy(reply.get('controls', []))
    ctx = request['discovery_context']
    completion = _discovery_completion
    locator = _locator
    scheduler = _traversal_scheduler
    contract = deepcopy(request.get('response_schema') or locator.schema(root, ctx['mode'], ctx.get('focus') is not None))
    if ctx.get('completion'):
        completion.extend_schema(contract)
    (prior, known, current) = _record_load(run)
    if _record_read(prior / 'source.json').get('stage') == 'discovery-' + call_ref:
        if current.get('action_target_registration', {}).get('status') == 'pending':
            from regrow.traversal.target_registration import advance
            return advance(run, call_ref, request)
        return _record_read(run / 'knowledge_current.json')
    if current.get('action_target_registration', {}).get('last_discovery_call') == call_ref:
        return _record_read(run / 'knowledge_current.json')
    batch = completion.scoped_batch(known, current.get('discovery_completion') or {})
    if batch.get('pending'):
        batch = completion.with_contract(run, batch)
    if call_ref in batch.get('calls', []):
        return _record_read(run / 'knowledge_current.json')
    if current.get('next_action_mode') != 'discover':
        raise ValueError('not awaiting discovery')
    from regrow.traversal.object_registration import isolate_schema, remap_gaps
    request, reply = isolate_schema({**request, 'response_schema': contract}, reply)
    schema_gaps = deepcopy(request.get('registration_gaps', []))
    schema_indices = request.get('registration_source_indices', {})
    if schema_gaps and not reply['regions'] and not batch:
        raise ValueError('本批没有可独立登记的区块，保留原答继续核对')
    recovery_target = None
    review = None
    if ownership_episode:
        from regrow.traversal.observation import retained_action_target
        pointer = _record_read(run / 'ownership_review.json')
        review = _record_read(run / ownership_episode)
        job = _record_read(run / review['source_episode'])
        if (pointer.get('episode') != ownership_episode or job.get('call') != call_ref
                or job.get('stage') != 'discovery' or job.get('attempt')
                or review.get('status') not in ('blocked', 'pending') or review.get('actions')):
            raise ValueError('原归属复查与未执行的发现步骤不对应')
        recovery_target = retained_action_target(run, prior, known, current)
        if recovery_target is None:
            raise ValueError('未找到对应原图和未执行目标')
    frame = current['pending_frame']
    if (run / request['screenshots'][0]).resolve() != (run / frame).resolve():
        raise ValueError('discovery frame changed')
    if ctx.get('completion') and batch.get('pending') and (not completion.same_frame(batch, run / frame)):
        raise ValueError('补全截图已变化，不能使用旧回执')
    excluded_gaps = batch.get('excluded_gaps', [])
    stale_batch = batch if not ctx.get('completion') and batch.get('pending') else None
    if not ctx.get('completion'):
        batch = {}
    exception = reply['foreground'].get('exception', 'none')
    if ownership_episode and (exception != 'none' or ctx.get('completion')
           ):
        raise ValueError('当前复查不能独立登记操作目标')
    if exception != 'none':
        if reply['regions'] or reply['controls']:
            raise ValueError('exception observation must not register Regions')

        def recover(records, state, snapshot, temp):
            state.pop('handoff_summary', None)
            state.update(source_call=call_ref, next_action_mode='recover', exception=exception, recovery_handoff=reply['foreground'].get('recovery_handoff', ''), interactive_regions=[], observation={'id': 'discovery:' + call_ref, 'image': frame, 'control_refs': [], 'foreground': reply['foreground']})
        return _record_publish(run, 'exception-' + call_ref, recover)
    continuation_request = {**deepcopy(request), 'response_schema': deepcopy(contract)}
    (request, reply, audit) = _region_identity.prepare(run, request, reply)
    original_region_sources = schema_indices.get('regions', list(range(len(reply['regions']))))
    original_control_sources = schema_indices.get('controls', list(range(len(reply['controls']))))
    original_control_indices = list(range(len(reply['controls'])))
    deferred_controls = {}
    target_index = None
    if ownership_episode:
        from regrow.recognition import ownership_review
        report = ownership_review.conflict(request, reply, known, all_rows=True)
        split = ownership_review.independent_target(run, request, reply, recovery_target, report) if report else None
        if split is None:
            raise ValueError('当前目标或其所属区块仍需归属复查')
        reply, original_control_indices, target_index = split
        for error in report['errors']:
            actual = error['actual']
            deferred_controls.setdefault(actual['region_id'], []).append(actual['control_id'])
    ctx = request['discovery_context']
    if audit:
        _record_write_json(call / 'visual_identity.json', {'matches': audit, 'effective_candidate': reply})
    registration_request = {**request, 'response_schema': contract}
    if 'control_refs' in request:
        registration_request.pop('response_schema', None)  # Raw reply was validated before resolving indexes.
    (reply, missing, region_indices, control_indices) = completion.prepare_registration(reply, registration_request, known, batch, _registration_diagnostics)
    control_indices = [original_control_indices[i] for i in control_indices]
    if ownership_episode and target_index not in control_indices:
        raise ValueError('原目标未通过正常登记检查')
    if ownership_episode or schema_indices:
        previous = {'regions': original_region_sources,
                    'controls': [original_control_sources[i] for i in original_control_indices]}
        # Completion replies have their own retained gaps and never enter the
        # schema split above. Native ownership recovery likewise uses one reply.
        remap_gaps(missing, previous)
        region_indices = [original_region_sources[i] for i in region_indices]
        control_indices = [original_control_sources[i] for i in control_indices]
        if target_index is not None:
            target_index = original_control_sources[target_index]
    missing = schema_gaps + missing
    locator.validate_identity(reply)
    for r in reply['regions']:
        if r['identity'] == 'same':
            rid = ctx['region_names'].get(r['ref'])
            if rid not in known:
                raise ValueError('unknown candidate Region')
            r['_matched_id'] = rid
    from regrow.records.object_knowledge import region_only
    observed_regions = [row for row in reply['regions'] if not region_only(row)]
    if ctx['mode'] == 'local' and (not (batch and (not observed_regions))) and (len(observed_regions) != 1 or observed_regions[0].get('_matched_id') != ctx['focus']):
        raise ValueError('local discovery changed focus; relocate first')
    for c in reply['controls']:
        from regrow.records.object_knowledge import control_only
        if control_only(c):
            continue
        if not 0 <= c['region_index'] < len(reply['regions']):
            raise ValueError('invalid control owner index')
        if c['identity'] == 'same':
            cid = ctx['control_names'].get(c['ref'], c['ref'] if c['ref'] in request.get('control_refs', []) else None)
            rid = reply['regions'][c['region_index']].get('_matched_id')
            from regrow.records.object_store import control_record
            if control_record(known, cid) is None:
                raise ValueError('unknown candidate control')
            c['_matched_id'] = cid

    def mutate(records, state, snapshot, temp):
        from regrow.traversal import task_deferral as _task_deferral

        for rid, controls in deferred_controls.items():
            work = region_work(records[rid])
            gap = {'reason': '其他控件的归属争议保留在原复查记录中', 'episode': ownership_episode,
                   'controls': list(controls), 'source_call': call_ref}
            old = work.setdefault('registration_gaps', {}).get('ownership_review')
            if old and old != gap:
                work.setdefault('registration_gap_history', []).append(deepcopy(old))
            work['registration_gaps']['ownership_review'] = gap
        if stale_batch:
            state.setdefault('discovery_completion_history', []).append(stale_batch)
            state.pop('discovery_completion', None)
        obs = batch.get('observation', 'discovery:' + call_ref)
        retained = {rid: deepcopy(records[rid]) for rid in batch.get('regions', []) if rid in records}
        refs = _owner_materialize_regions(records, reply, call_ref, obs, ctx['region_names'], frame=run / frame)
        from regrow.records.object_knowledge import observed_refs
        all_refs = refs
        refs = observed_refs(reply, refs)
        _owner_save_region_images(records, refs, reply, call_ref, run, frame, snapshot, temp)
        from regrow.records.observations import restore_source_indices
        restore_source_indices(records, refs, {'regions': region_indices, 'controls': control_indices}, call_ref, obs)
        new_controls = []
        for rid in refs:
            r = records[rid]
            if rid in retained:
                old = retained[rid]
                for (k, v) in old.items():
                    if k not in ('controls', 'out_of_scope_reason', 'scope_history', 'scope_evidence'):
                        r[k] = v
                region_work(r).update({k: deepcopy(v) for (k, v) in region_work(old).items() if k != 'out_of_scope_reason'})
                replace_observation_history(r, deepcopy(observation_history(old)))
                for (cid, c) in owned_controls(old).items():
                    if cid in batch.get('controls', []):
                        owned_controls(r)[cid] = c
            new_controls.extend((cid for (cid, c) in owned_controls(r).items() if frame_observation(c, kind='controls', call=call_ref, region=rid)))
        refs = list(dict.fromkeys(batch.get('regions', []) + refs))
        all_controls = list(dict.fromkeys(batch.get('controls', []) + new_controls))
        for rid in refs:
            pending = [g for g in missing if g.get('owner') == records[rid]['name']]
            old = region_work(records[rid]).get('registration_gaps', {}).get('discovery')
            if old:
                confirmed = {c['name'] for c in owned_controls(records[rid]).values() if frame_observation(c, kind='controls', call=call_ref, region=rid)}
                addressed = {g['item'] for g in batch.get('pending', [])}
                pending = [g for g in old['pending'] if g['item'] not in addressed and g.get('name') not in confirmed] + pending
                pending = list({g['item']: g for g in pending}.values())
            if old:
                region_work(records[rid]).setdefault('registration_gap_history', []).append(deepcopy(old))
            if pending:
                region_work(records[rid]).setdefault('registration_gaps', {})['discovery'] = {'pending': [{**deepcopy(g), 'source_frame': g.get('source_frame', frame), 'source_observation': g.get('source_observation', obs), 'source_call': g.get('source_call', call_ref)} for g in pending], 'source_call': call_ref, 'observation': obs, 'frame': frame}
            else:
                region_work(records[rid]).get('registration_gaps', {}).pop('discovery', None)
        if excluded_gaps:
            state.setdefault('scope_excluded_discovery_gaps', []).extend((g for g in excluded_gaps if g not in state.get('scope_excluded_discovery_gaps', [])))
        if not missing and (not batch):
            state.pop('discovery_completion', None)
        if missing or batch:
            state['discovery_completion'] = {'frame': str((run / frame).resolve()), 'sha256': completion.fingerprint(run / frame), 'observation': obs, 'regions': refs, 'controls': all_controls, 'pending': missing, 'calls': batch.get('calls', []) + [call_ref], 'request': batch.get('request') or continuation_request}
        if missing or batch or ownership_episode:
            _record_write_json(temp / 'discovery_receipt.json', {'source_call': call_ref, 'registered_regions': refs, 'registered_controls': all_controls, 'pending': missing, 'region_source_indices': region_indices, 'control_source_indices': control_indices})
            if ownership_episode:
                receipt = _record_read(temp / 'discovery_receipt.json')
                receipt['independent_target'] = {'episode': ownership_episode,
                    'action_call': recovery_target['call'], 'control_index': target_index}
                _record_write_json(temp / 'discovery_receipt.json', receipt)
        _task_deferral.resume_localized(records, refs, call_ref, foreground=reply['foreground'], run=run, frame=run / frame, snapshot=temp)
        interactive = list(refs)
        partition = ctx.get('partition_context') or {}
        if ctx['mode'] == 'local' and partition.get('sha256') and (partition['sha256'] == completion.fingerprint(run / frame)):
            interactive = list(dict.fromkeys(interactive + [r['region'] for r in partition.get('regions', []) if r['region'] in records]))
        state.update(source_call=call_ref, interactive_regions=interactive, next_action_mode='explore' if refs else 'review_result', phase='ready_for_next_action', observation={'id': obs, 'image': frame, 'control_refs': all_controls, 'foreground': reply['foreground']})

        state['observation']['scope'] = ctx['mode']
        state.pop('discovery_mode', None)
        state.pop('correction_context', None)
        state.pop('exception', None)
        state.pop('recovery_handoff', None)
        if not state.get('working_region') and refs:
            state['working_region'] = refs[0]
        if ctx['mode'] == 'relocate' and refs:
            if not (missing and any((_record_coverage(records[rid], records)['pending'] for rid in refs))):
                scheduler.schedule_local_inspection(records, state)
        elif ctx['mode'] == 'local':
            state['control_inventory_status'] = 'partial'
            if not state['observation']['control_refs']:
                state.update(next_action_mode='explore', reason='local_inventory_requires_task_review')
            if state.get('required_control') and state['required_control'] not in state['observation']['control_refs']:
                state.update(next_action_mode='explore', reason='navigation_from_foreground')
            if not owned_controls(records[ctx['focus']]) and any((g.get('kind') == 'control' and g.get('owner') == records[ctx['focus']]['name'] for g in missing)):
                state.update(next_action_mode='discover', phase='awaiting_discovery', inspection_region=ctx['focus'], reason='local_control_identity_unresolved')
            else:
                state.pop('inspection_region', None)
            state.pop('required_control', None)
        if ctx['mode'] == 'local' and state['next_action_mode'] == 'explore' and (state.get('working_region') not in state['interactive_regions']):
            state['reason'] = 'navigation_from_foreground'
        state.pop('handoff_summary', None)
        if state['next_action_mode'] != 'discover':
            state.pop('pending_frame', None)
        if (ctx['mode'] == 'local' and not ctx.get('completion')
                and ctx['focus'] in refs and 'new_tasks' in contract.get('properties', {})):
            from regrow.records.task_plans import apply_observation
            assessment = apply_observation(records, state, request, reply, call_ref, raw_task_controls)
            _record_write_json(temp / 'task_assessments.json', assessment)
    pointer = _record_publish(run, 'discovery-' + call_ref, mutate)
    if current.get('action_target_registration', {}).get('status') == 'pending':
        from regrow.traversal.target_registration import advance
        return advance(run, call_ref, request)
    return pointer
