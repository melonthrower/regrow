from regrow.records.calls import submission as _owner_submission
'Read delivered action types. Never infer an action from a label or screenshot.'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
import json
from pathlib import Path

def resolve_operations(records, run):
    for (rid, region) in records.items():
        for (aid, action) in owned_actions(region).items():
            binding = Path(run) / 'action_attempts' / aid / 'binding.json'
            if binding.is_file():
                value = json.loads(binding.read_text())
                if value.get('task_name'):
                    action['task'] = value.get('task_region', value['region_ref']) + '/' + value['task_name']
                else:
                    action['task'] = None
            if action.get('operation'):
                continue
            path = Path(run) / 'action_attempts' / aid / 'dispatch.json'
            if not path.is_file():
                continue
            dispatch = json.loads(path.read_text())
            if dispatch.get('source_region') != rid or dispatch.get('source_control') != action.get('control'):
                continue
            delivered = dispatch.get('action', {})
            action['operation'] = delivered.get('action') or delivered.get('kind')
    actions = {aid: row for region in records.values() for (aid, row) in owned_actions(region).items()}
    from regrow.records.tasks import audit
    for region in records.values():
        for task in owned_tasks(region).values():
            history = audit(task)
            if 'imported_attempts' in history:
                unresolved = [aid for aid in history['imported_attempts'] if aid not in actions or 'task' not in actions[aid]]
                if unresolved:
                    history['imported_attempts'] = unresolved
                else:
                    history.pop('imported_attempts')
ANSWER_FIELDS = {'knowledge', 'parameter_findings', 'parameter_gaps', 'reported_parameter_findings', 'entry_registration', 'registration_kind', 'remaining_question', 'task_update', 'next_action'}

def compact(records):
    """Import old accepted entry/assessment records, then keep only actual actions."""
    from copy import deepcopy
    from regrow.records.object_store import observation_history
    from regrow.records.object_store import find_control
    from regrow.records.tasks import audit
    from regrow.records.tasks import entry_value
    tasks = [t for r in records.values() for t in owned_tasks(r).values()]
    for region in records.values():
        for (aid, action) in owned_actions(region).items():
            control = find_control(region, action.get('control'))
            entry = action.get('entry_registration')
            if entry and control:
                values = control.setdefault('entries', [])
                if not any(((v['region'], v.get('conditions', [])) == (entry['region'], entry.get('conditions', [])) for v in values)):
                    values.append(entry_value(entry))
                historical = {**deepcopy(entry), 'attempt': entry.get('attempt', aid)}
                history = observation_history(control, create=True)
                if not any((row.get('entry') == historical for row in history)):
                    history.append({'entry': historical, 'evidence': {'attempt': aid, 'source_call': action.get('evidence', {}).get('result_call')}})
            for row in action.get('task_update', []):
                if not isinstance(row, dict):
                    continue
                for task in tasks:
                    refs = {getattr(task, 'ref', None), audit(task).get('original_ref'), *audit(task).get('prior_refs', [])}
                    if row.get('task') not in refs or not row.get('task'):
                        continue
                    row = {('remaining_question' if k == 'registration_gap' else k): v for k, v in row.items()}
                    value = {**{k: deepcopy(row[k]) for k in ('decision', 'reason', 'remaining_question', 'retry_when', 'next_action') if k in row}, 'source': {'source_attempt': aid, 'source_call': action.get('evidence', {}).get('result_call')}}
                    history = audit(task).setdefault('update_history', [])
                    if value not in history:
                        history.append(value)
            for field in ANSWER_FIELDS:
                action.pop(field, None)
        for edge in region.get('transitions', []):
            edge.pop('entry_semantics', None)
    from regrow.records.object_store import owned_controls
    for region in records.values():
        for record in [region, *owned_controls(region).values()]:
            for entry in record.get('entries', []):
                if 'source' in entry or 'evidence' in entry:
                    history = observation_history(record, create=True)
                    if not any((row.get('entry') == entry for row in history)):
                        history.append({'entry': deepcopy(entry), 'evidence': deepcopy(entry.get('source', {}))})
            if 'entries' in record:
                record['entries'] = [entry_value(v) for v in record['entries']]

def entries_for_action(region, aid, control):
    from copy import deepcopy
    from regrow.records.object_store import find_control
    from regrow.records.object_store import observation_history
    from regrow.records.tasks import invalidated
    record = find_control(region, control)
    if aid in invalidated(record):
        return []
    entries = []
    for value in [*record.get('entries', []), *(row['entry'] for row in observation_history(record) if row.get('entry'))]:
        if value.get('attempt') == aid and (not any(((v['region'], v.get('control'), v.get('conditions', [])) == (value['region'], value.get('control'), value.get('conditions', [])) for v in entries))):
            entries.append(deepcopy(value))
    return entries

def assessments(task, attempt):
    """Accepted question decisions associated with this observation or execution."""
    from regrow.records.tasks import read
    rows = [*read(task, 'update_history', []), read(task, 'latest_update', {})]
    return [row for row in rows if attempt in (row.get('source', {}).get('attempt'), row.get('source', {}).get('source_attempt'))]
from copy import deepcopy
from regrow.records.snapshots import read

def attach_execution(records, run):
    for r in records.values():
        for (aid, a) in owned_actions(r).items():
            dispatch = Path(run) / f'action_attempts/{aid}/dispatch.json'
            proposal = Path(run) / f'action_attempts/{aid}/proposal.json'
            binding_path = Path(run) / f'action_attempts/{aid}/binding.json'
            if binding_path.exists():
                binding = read(binding_path)
                if binding.get('task_name'):
                    a['task'] = binding.get('task_region', binding['region_ref']) + '/' + binding['task_name']
                else:
                    a['task'] = None
            data = read(dispatch).get('action', {}) if dispatch.exists() else read(proposal) if proposal.exists() else {}
            if isinstance(data, dict):
                a['operation'] = data.get('action')
                a['purpose'] = data.get('reason', '')
                receipt_path = Path(run) / f'action_attempts/{aid}/receipt.json'
                receipt = read(receipt_path) if receipt_path.exists() else {}
                if data.get('action') == 'input_text' and 'text_delivered' in receipt:
                    a['intended_operation'] = 'input_text'
                    a['text_delivered'] = receipt['text_delivered']
                    a['executed_steps'] = deepcopy(receipt.get('executed_steps', []))
                    a['input_target'] = deepcopy(receipt.get('input_target'))
                    if not receipt['text_delivered'] and receipt.get('exit_code') == 0:
                        a['operation'] = 'click'
                        a['purpose'] += '；文字尚未发送，只执行了点击'

def action_source_observation(run, selection_call, observation, region, control=None):
    """Resolve the immutable source through the dispatched selection request."""
    run = Path(run)
    if not selection_call or not (run / 'calls' / selection_call / 'request.json').exists():
        raise ValueError('dispatched action source request is missing')
    (request, _) = _owner_submission(run, selection_call)
    source = request.get('source', {})
    snapshot = source.get('snapshot')
    if not snapshot:
        raise ValueError('dispatched action source snapshot is missing')
    path = (run / snapshot).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError('action source snapshot is outside this run')
    state = read(path / 'runtime_state.json')
    if source.get('observation') != observation or (state.get('observation') or {}).get('id') != observation:
        raise ValueError('dispatched request and source snapshot observation disagree')
    extra = None
    if region not in state.get('interactive_regions', []):
        candidates = [c for c in request.get('backend_candidates', []) if c.get('region_ref') == region and c.get('id') == control and (c.get('candidate_scope') == 'foreground_entry_trigger')]
        if control is None or len(candidates) != 1:
            raise ValueError('source Region was not interactive and no dispatched related control candidate exists')
        extra = {'region': region, 'control': control, 'scope': candidates[0]['candidate_scope']}
    return {'id': observation, 'region_refs': state['interactive_regions'], 'snapshot': snapshot, 'selection_call': selection_call, **({'related_control': extra} if extra else {})}
