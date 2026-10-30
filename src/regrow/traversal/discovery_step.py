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

def await_discovery(run, frame, evidence, handoff=''):
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
        state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=frame, discovery_trigger=evidence, reason='recovery_finished_discovery_required', recovery_handoff=handoff)
    return _record_publish(run, 'await-discovery-' + evidence, mutate)

def commit(root, run, call_ref):
    from regrow.recognition import discovery_completion as _discovery_completion
    from regrow.recognition import locator as _locator
    from regrow.traversal import traversal_scheduler as _traversal_scheduler
    from regrow.recognition import region_identity as _region_identity
    from regrow.recognition import control_identity_review as _control_identity_review
    from regrow.records import registration_diagnostics as _registration_diagnostics
    run = Path(run).resolve()
    call = run / 'calls' / call_ref
    (request, reply) = _owner_submission(run, call_ref)
    ctx = request['discovery_context']
    completion = _discovery_completion
    locator = _locator
    scheduler = _traversal_scheduler
    contract = deepcopy(request.get('response_schema') or locator.schema(root, ctx['mode'], ctx.get('focus') is not None))
    if ctx.get('completion'):
        completion.extend_schema(contract)
    if request.get('dependency_candidates'):
        contract['properties']['dependency_updates'] = request['response_schema']['properties']['dependency_updates']
    jsonschema.validate(reply, contract)
    (prior, known, current) = _record_load(run)
    if _record_read(prior / 'source.json').get('stage') == 'discovery-' + call_ref:
        return _record_read(run / 'knowledge_current.json')
    batch = completion.scoped_batch(known, current.get('discovery_completion') or {})
    if call_ref in batch.get('calls', []):
        return _record_read(run / 'knowledge_current.json')
    if current.get('next_action_mode') != 'discover':
        raise ValueError('not awaiting discovery')
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
    if exception != 'none':
        if reply['regions'] or reply['controls']:
            raise ValueError('exception observation must not register Regions')

        def recover(records, state, snapshot, temp):
            state.pop('handoff_summary', None)
            state.update(source_call=call_ref, next_action_mode='recover', exception=exception, recovery_handoff=reply['foreground'].get('recovery_handoff', ''), interactive_regions=[], observation={'id': 'discovery:' + call_ref, 'image': frame, 'control_refs': [], 'foreground': reply['foreground'], 'uncertainties': reply['uncertainties']})
        return _record_publish(run, 'exception-' + call_ref, recover)
    if batch and ctx['mode'] == 'local' and (reply.get('focus_presence') != 'interactive'):
        raise ValueError('局部补全不能静默改变原观察范围；需重新定位')
    if ctx['mode'] == 'local' and reply.get('focus_presence') != 'interactive':

        def expand(records, state, snapshot, temp):
            if scheduler.offer_foreground_navigation(records, state, ctx['focus'], reply):
                return
            state.update(discovery_mode='relocate', reason='local_position_unconfirmed', interactive_regions=[], observation=None)
        return _record_publish(run, 'expand-discovery-' + call_ref, expand)
    (request, reply, audit) = _region_identity.prepare(run, request, reply)
    _control_identity_review.check_request(run, request, reply)
    ctx = request['discovery_context']
    if audit:
        _record_write_json(call / 'visual_identity.json', {'matches': audit, 'effective_candidate': reply})
    registration_request = {**request, 'response_schema': contract}
    if 'control_refs' in request:
        registration_request.pop('response_schema', None)  # Raw reply was validated before resolving indexes.
    (reply, missing, region_indices, control_indices) = completion.prepare_registration(reply, registration_request, known, batch, _registration_diagnostics)
    locator.validate_identity(reply)
    for r in reply['regions']:
        if r['identity'] == 'same':
            rid = ctx['region_names'].get(r['ref'])
            if rid not in known:
                raise ValueError('unknown candidate Region')
            r['_matched_id'] = rid
    if ctx['mode'] == 'local' and (not (batch and (not reply['regions']))) and (len(reply['regions']) != 1 or reply['regions'][0].get('_matched_id') != ctx['focus']):
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
        from regrow.recognition import visual_region_locator as _visual_region_locator
        from regrow.traversal import task_deferral as _task_deferral
        from regrow.traversal import task_prerequisites as _task_prerequisites
        if stale_batch:
            state.setdefault('discovery_completion_history', []).append(stale_batch)
            state.pop('discovery_completion', None)
        obs = batch.get('observation', 'discovery:' + call_ref)
        retained = {rid: deepcopy(records[rid]) for rid in batch.get('regions', []) if rid in records}
        refs = _owner_materialize_regions(records, reply, call_ref, obs, ctx['region_names'], frame=run / frame)
        from regrow.records.object_knowledge import observed_refs
        all_refs = refs
        refs = observed_refs(reply, refs)
        resolved = _visual_region_locator.resolve_foreground_check(ctx['visual_plan'], run / frame, refs, reply.get('focus_presence'), call_ref, previous=state.get('foreground_resolution'))
        if resolved:
            state['foreground_resolution'] = resolved
        _owner_save_region_images(records, refs, reply, call_ref, run, frame, snapshot, temp)
        new_controls = []
        for rid in refs:
            r = records[rid]
            for c in owned_controls(r).values():
                v = frame_observation(c, kind='controls', call=call_ref, region=rid)
                if v:
                    i = int(v['evidence']['source_field'].split('/')[-1])
                    v['evidence']['source_field'] = f'/controls/{control_indices[i]}'
            frame_observation(r, kind='regions', call=call_ref)['evidence']['source_field'] = f'/regions/{region_indices[all_refs.index(rid)]}'
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
            state['discovery_completion'] = {'frame': str((run / frame).resolve()), 'sha256': completion.fingerprint(run / frame), 'observation': obs, 'regions': refs, 'controls': all_controls, 'pending': missing, 'calls': batch.get('calls', []) + [call_ref], 'request': batch.get('request') or request}
            _record_write_json(temp / 'discovery_receipt.json', {'source_call': call_ref, 'registered_regions': refs, 'registered_controls': all_controls, 'pending': missing, 'region_source_indices': region_indices, 'control_source_indices': control_indices})
        _task_deferral.resume_localized(records, refs, call_ref, foreground=reply['foreground'])
        interactive = list(refs)
        partition = ctx.get('partition_context') or {}
        if ctx['mode'] == 'local' and partition.get('sha256') and (partition['sha256'] == completion.fingerprint(run / frame)):
            interactive = list(dict.fromkeys(interactive + [r['region'] for r in partition.get('regions', []) if r['region'] in records]))
        state.update(source_call=call_ref, interactive_regions=interactive, next_action_mode='explore' if refs else 'review_result', phase='ready_for_next_action', observation={'id': obs, 'image': frame, 'control_refs': all_controls, 'foreground': reply['foreground'], 'uncertainties': reply['uncertainties']})
        _task_prerequisites.apply(records, reply, call_ref, request.get('dependency_candidates', []))
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
            state.setdefault('control_scan', {})[ctx['focus']] = ctx['visual_plan']['next_offset']
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
    return _record_publish(run, 'discovery-' + call_ref, mutate)
