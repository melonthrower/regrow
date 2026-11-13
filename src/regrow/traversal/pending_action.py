"""One-use Action source from an accepted after-image, consumed by normal work."""
from copy import deepcopy
from pathlib import Path
import uuid

from regrow.records.object_store import owned_tasks
from regrow.records.snapshots import load, publish, write_json
from regrow.records.task_updates import hard_block


def retain(state, records, request, reply, binding, call, snapshot, *, historical=False):
    name = binding.get('task_name')
    rid = binding.get('task_region', binding['region_ref'])
    task = owned_tasks(records.get(rid, {})).get(name, {})
    if (historical or 'next_action' not in request['response_schema'].get('properties', {})
            or 'next_action' not in reply or task.get('status') != 'pending' or hard_block(task)
            or state.get('next_action_mode') != 'explore' or state.get('exception') != 'none'):
        return
    state['pending_action'] = {'call': call, 'field': 'next_action', 'snapshot': snapshot,
                               'observation': state['observation']['id'],
                               'task_region': rid, 'task_name': name,
                               'image': state['observation']['image']}


def applicable(source, records, state, request):
    selected = request.get('source', {})
    task = owned_tasks(records.get(source['task_region'], {})).get(source['task_name'], {})
    return (request.get('action_ready') and state.get('next_action_mode') == 'explore'
            and state.get('exception', 'none') == 'none'
            and task.get('status') == 'pending' and not hard_block(task)
            and (selected.get('task_region'), selected.get('task_name')) ==
                (source['task_region'], source['task_name'])
            and (state.get('observation') or {}).get('id') == source['observation'])


def peek(run, request):
    _, records, state = load(run)
    source = state.get('pending_action')
    return source if source and applicable(source, records, state, request) else None


def discard_changed_work(run, request=None):
    _, records, state = load(run)
    if request is None:
        from regrow.traversal.traversal_scheduler import select_work
        decision = select_work(records, state)
        task = decision.get('task') or {}
        request = {'action_ready': decision['kind'] == 'action',
                   'source': {'task_region': task.get('region'), 'task_name': task.get('name')}}
    source = state.get('pending_action')
    if source and not applicable(source, records, state, request):
        publish(run, 'discard-action-' + uuid.uuid4().hex,
                lambda records, state, *_: state.pop('pending_action', None))
    from regrow.traversal.step_repair import pending, atomic
    job = pending(run)
    origin = (job or {}).get('request', {}).get('action_source')
    if job and job['stage'] == 'action' and origin and not applicable(origin, records, state, request):
        reason = '接续动作的原任务或动作后观察已不可继续；保留未投递记录，回到正常调度。'
        job.update(status='superseded')
        job.setdefault('history', []).append({'framework': 'discard_changed_continuation', 'reason': reason})
        atomic(Path(run) / job['path'], job)
        (Path(run) / 'pending_step.json').unlink(missing_ok=True)
        from regrow.runtime.reply_correction import abandon
        abandon(run, reason)


def _new_target_refs(run, source, request, reply):
    """Read IDs assigned to this call's declared new names, without visual recall."""
    from regrow.records.snapshots import read
    from regrow.records.object_store import load as load_objects, observation_history
    declared = {}
    indexes = request.get('registration_source_indices', {})
    for kind in ('regions', 'controls'):
        for index, row in enumerate(reply.get(kind, [])):
            if row.get('name') and not row.get('ref'):
                original = indexes[kind][index] if kind in indexes else index
                declared.setdefault(row['name'], set()).add(f'/{kind}/{original}')
    if not declared:
        return {}
    snapshot = Path(run) / source['snapshot']
    records = load_objects(snapshot)
    parent = read(snapshot / 'source.json').get('parent_snapshot')
    previous = read(Path(run) / parent / 'objects.json') if parent else {}
    previous_ids = set(previous.get('regions', {})) | set(previous.get('controls', {}))
    matches = {name: set() for name in declared}
    for ref, record in [*records.items(), *records.controls.items()]:
        name = record['name']
        if name not in declared:
            continue
        observed = any(row.get('evidence', {}).get('source_call') == source['call']
                       and row['evidence'].get('source_field') in declared[name]
                       for row in observation_history(record))
        if ref not in previous_ids or observed:
            matches[name].add(ref)
    return {name: next(iter(refs)) for name, refs in matches.items() if len(refs) == 1}


def _archived_aliases(run, request, source):
    """Older calls without a map can only use identities from before the reply."""
    from regrow.records.object_store import load as load_objects
    from regrow.records.snapshots import read
    manifest = Path(run) / source['snapshot'] / 'source.json'
    if not manifest.is_file():
        return {}
    parent = read(manifest).get('parent_snapshot')
    if not parent:
        return {}
    path = Path(run) / parent
    if not (path / 'objects.json').is_file():
        return {}
    records = load_objects(path)
    material = request.get('user_prompt', '')
    names = {}
    for ref, record in [*records.items(), *records.controls.items()]:
        name = record.get('name')
        if name and name in material:
            names.setdefault(name, set()).add(ref)
    return {name: next(iter(refs)) for name, refs in names.items() if len(refs) == 1}


def take(run, request):
    """Drop before saving an action job; a crash may lose only this optimization."""
    _, records, state = load(run)
    source = state.get('pending_action')
    if not source:
        return None
    valid = applicable(source, records, state, request)
    publish(run, 'consume-action-' + uuid.uuid4().hex,
            lambda records, state, *_: state.pop('pending_action', None))
    if not valid:
        return None
    from regrow.records.calls import submission
    original, reply = submission(run, source['call'])
    q = deepcopy(request)
    q['action_source'] = deepcopy(source)
    q['source'].update(snapshot=source['snapshot'], observation=source['observation'])
    frame = str((Path(run) / source['image']).resolve())
    q.update(screenshots=[frame], image_refs=[frame])
    from regrow.runtime.action_commands import executable_operation_schema, platform_request
    q['response_schema'] = executable_operation_schema()
    from regrow.records.snapshots import read
    platform = read(Path(run) / 'run_manifest.json').get('platform', 'android')
    q = platform_request(q, platform)
    proposal = deepcopy(reply['next_action'])
    contract = original.get('sent_name_contract')
    if not contract:
        from regrow.records.calls import business_request
        sent = business_request(run, read(Path(run) / 'calls' / source['call'] / 'request.json'))
        contract = sent.get('sent_name_contract', {})
    if original.get('next_action_wire_schema') and contract.get('typed_fields'):
        q['next_action_wire_schema'] = original['next_action_wire_schema']
        q['sent_name_contract'] = contract
    elif original.get('control_reference_style') == 'id_name':
        q['received_control_labels'] = original['control_reference_names']
        q['received_region_labels'] = original.get('region_reference_names', {})
    else:
        aliases = contract.get('aliases') or _archived_aliases(run, original, source)
        q['received_legacy_aliases'] = {name: ref for name, ref in aliases.items()
                                        if ref in records or ref in records.controls}
    new_refs = _new_target_refs(run, source, original, reply)
    if new_refs:
        q['received_new_targets'] = new_refs
    write_json(Path(run) / 'calls' / source['call'] / 'next_action_context.json', q)
    write_json(Path(run) / 'calls' / source['call'] / 'next_action_candidate.json', proposal)
    return q, proposal, source['call']
