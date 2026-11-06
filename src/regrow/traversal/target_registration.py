"""Recall and bounded continuation for one unexecuted action target."""
from copy import deepcopy
from pathlib import Path

from regrow.records.object_store import owned_controls
from regrow.records.observations import frame_observation
from regrow.traversal import work_context


def target_candidates(records, target):
    """Exact labels offer all possible owners; they never establish identity."""
    controls = []
    regions = []
    for rid, region in records.items():
        for cid, control in owned_controls(region).items():
            if target == cid or target == control['name']:
                controls.append(cid)
                regions.append(rid)
    return list(dict.fromkeys(controls)), list(dict.fromkeys(regions))


def context(records, state, request, proposal, call, frame, episode=None):
    task = work_context.from_request(request, records, state).get('task')
    controls, regions = target_candidates(records, proposal.get('target'))
    source = request.get('source', {})
    regions += [source.get('completion_region'), (task or {}).get('region')]
    result = {'call': call, 'episode': episode, 'task': deepcopy(task),
            'target': proposal.get('target'), 'controls': controls,
            'regions': list(dict.fromkeys(r for r in regions if r in records)),
            'frame': frame, 'supplements': 0, 'status': 'pending'}
    origin = request.get('action_source', {})
    if origin.get('call') == call:
        result['source_field'] = origin['field']
    previous = state.get('action_target_registration') or {}
    if (previous.get('task') == task and previous.get('target') == result['target']
            and previous.get('controls') == controls and previous.get('regions') == result['regions']
            and previous.get('frame')):
        from regrow.recognition.visual_backtrack import same_surface
        if same_surface(previous['frame'], frame):
            result['repeat'] = True
    return result


def guidance(target, records):
    names = [owned_controls(r)[target['target']]['name'] for r in records.values()
             if target['target'] in owned_controls(r)]
    label = names[0] if names else target['target']
    return ('上一步拟操作「' + str(label) + '」，但身份尚未关联，动作没有执行。'
            '请在当前截图中核对该目标及其真实所属区块。相关历史身份仅供核对，不表示当前可见。'
            '已有对象核对后复用，新对象按实际归属登记；无法确认则保留未解决。'
            '本轮只补登记身份，不探索功能效果；登记后重新选择动作。')


def reobserve(records, state, frame):
    """Carry identity recall, never old geometry, across an unexecuted repair."""
    from regrow.records.object_store import owned_tasks
    target = state.get('action_target_registration') or {}
    ref = target.get('task') or {}
    task = owned_tasks(records.get(ref.get('region'), {})).get(ref.get('name'), {})
    if (target.get('status') != 'pending' or not ref or state.get('active_task') != ref
            or task.get('status') not in ('pending', 'blocked')):
        return False
    target.update(frame=str(Path(frame).resolve()), supplements=0)
    for key in ('completion_items', 'last_discovery_call', 'repeat'):
        target.pop(key, None)
    return True


def registered(records, target, call, *, run=None, snapshot=None):
    """Only an accepted current observation can resolve the registration goal."""
    matches = set()
    observed = []
    for rid, region in records.items():
        for cid, control in owned_controls(region).items():
            if frame_observation(control, kind='controls', call=call, region=rid):
                observed.append((rid, cid))
            if (cid in target['controls'] or control['name'] == target['target']):
                if frame_observation(control, kind='controls', call=call, region=rid):
                    matches.add(cid)
    if run is None or snapshot is None:
        return len(matches) == 1
    if not observed:
        return False
    # A new object's accepted name can differ from the old unexecuted proposal.
    # Reuse normal binding with only this call's accepted visual identities.
    from regrow.records.calls import action_submission
    from regrow.records.action_candidates import candidate
    from regrow.runtime.action_commands import normalize
    from regrow.traversal.action_binding import bind_action_target
    from regrow.recognition.action_target_review import Conflict
    request, proposal = action_submission(run, target['call'], target.get('source_field'))
    original_frame = (Path(run) / request['screenshots'][0]).resolve()
    if original_frame != Path(target['frame']).resolve():
        # A fresh observation can confirm a known identity, but the old click
        # point cannot identify a renamed/new object on a different frame.
        return len(matches) == 1
    request = deepcopy(request)
    request.pop('action_target_confirmation', None)
    rows = []
    for rid, cid in observed:
        item = deepcopy(candidate(records[rid], cid, None))
        if item is None:
            continue
        if item.get('image'):
            item['image'] = str((Path(snapshot) / item['image']).resolve())
        for appearance in item.get('appearances', []):
            if appearance.get('image'):
                appearance['image'] = str((Path(snapshot) / appearance['image']).resolve())
        rows.append(item)
    request.update(backend_candidates=rows, image_refs=[target['frame']], screenshots=[target['frame']])
    try:
        binding = bind_action_target(request, normalize(proposal))
    except Conflict:
        return False
    return binding.get('status') == 'matched' and binding.get('control_ref') in {cid for _, cid in observed}


def related_gaps(records, target, pending):
    owners = {records[r]['name'] for r in target['regions'] if r in records}
    result = []
    for gap in pending:
        proposal = gap.get('proposal', {})
        if gap['kind'] == 'control':
            related = proposal.get('ref') in target['controls'] or gap.get('name') == target['target']
        else:
            related = proposal.get('ref') in target['regions'] or gap.get('name') in owners
        if related:
            result.append(gap)
    return result


def defer(run, target):
    """Use the original action episode and the existing task/scheduler deferral."""
    from regrow.records.calls import action_submission
    from regrow.records.snapshots import read, publish
    from regrow.traversal import task_deferral
    request, _ = action_submission(run, target['call'], target.get('source_field'))
    episode = target.get('episode')
    if not episode:
        for path in (Path(run) / 'repair_episodes').glob('*/episode.json'):
            saved = read(path)
            if saved.get('stage') == 'action' and saved.get('call') == target['call']:
                episode = str(path.relative_to(run))
                break
    if not episode:
        raise ValueError('目标补登记缺少原动作步骤记录；不能改写其他任务')
    job = {**read(Path(run) / episode), 'stage': 'action', 'request': request,
           'call': target['call'], 'attempt': None}
    reason = '拟操作「' + str(target['target']) + '」仍未可靠关联；保留原问题，先探索其他任务。'
    if target.get('task'):
        decision = task_deferral.defer(run, job, reason, retry_when='target_identity_or_changed_surface')
        if decision is None:
            raise ValueError('目标补登记无法关联原任务；保留记录待核对')

    def finish(records, state, *_):
        state['action_target_registration']['status'] = 'deferred'
        if target.get('last_discovery_call'):
            state['action_target_registration']['last_discovery_call'] = target['last_discovery_call']
        state.pop('pending_frame', None)
        state.pop('correction_context', None)
        state.pop('discovery_mode', None)
        if not target.get('task'):
            state.update(next_action_mode='explore', phase='ready_for_next_action')
    pointer = publish(run, 'target-registration-deferred-' + target['call'], finish)
    if not target.get('task'):
        task_deferral.advance_unfinished(run)
        return read(Path(run) / 'knowledge_current.json')
    return pointer


def advance(run, call, request):
    from regrow.records.snapshots import load, publish, read
    from regrow.recognition import discovery_completion as completion
    snapshot, records, state = load(run)
    target = state.get('action_target_registration') or {}
    if target.get('status') != 'pending':
        return read(Path(run) / 'knowledge_current.json')
    target['last_discovery_call'] = call
    if registered(records, target, call, run=run, snapshot=snapshot):
        def resolved(records, state, *_):
            state['action_target_registration'].update(status='registered', last_discovery_call=call)
            state.update(next_action_mode='explore', phase='ready_for_next_action')
            state.pop('pending_frame', None)
            state.pop('inspection_region', None)
        return publish(run, 'target-registered-' + call, resolved)
    gaps = related_gaps(records, target, (state.get('discovery_completion') or {}).get('pending', []))
    offered = set(request['discovery_context']['region_names'].values())
    additions = set(completion.retrieve(records, [g['proposal'] for g in gaps])) - offered
    if gaps and additions and target['supplements'] == 0:
        def supplement(records, state, *_):
            target = state['action_target_registration']
            target.update(supplements=1, last_discovery_call=call, completion_items=[g['item'] for g in gaps])
            state.update(next_action_mode='discover', phase='awaiting_discovery',
                         pending_frame=target['frame'], reason='action_target_needs_registration',
                         correction_context=guidance(target, records))
            state.pop('inspection_region', None)
        return publish(run, 'target-registration-supplement-' + call, supplement)
    return defer(run, target)


def retry_evidence(run, records, task, call, frame, snapshot):
    """Unrelated re-registration on the same surface cannot release this task."""
    from regrow.records.calls import action_submission
    from regrow.runtime.action_commands import normalize
    from regrow.recognition.visual_backtrack import same_surface
    request, proposal = action_submission(run, task['deferral']['source_call'], task['deferral'].get('source_field'))
    proposal = normalize(proposal)
    target = context(records, {}, request, proposal, task['deferral']['source_call'], frame)
    if registered(records, target, call, run=run, snapshot=snapshot):
        return True
    original = Path(run) / request['screenshots'][0]
    return original.is_file() and Path(frame).is_file() and not same_surface(original, frame)
