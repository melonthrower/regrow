"""Immutable accepted observation records, shared across object snapshots.

The current objects contain no observation arrays. One event groups the objects
reported from the same source frame/call; snapshots retain only event references.
Original model replies, frames and execution receipts remain in their run paths.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
PATH_FIELDS = {'crop', 'control_crop', 'icon_crop', 'before_image', 'after_image', 'evidence_dir', 'image', 'source_image', 'icon_image', 'click_image', 'execution_dir'}

def rebase_paths(value, old_base, new_base):
    if isinstance(value, list):
        return [rebase_paths(row, old_base, new_base) for row in value]
    if not isinstance(value, dict):
        return value
    return {key: os.path.relpath(Path(old_base) / item, new_base) if key in PATH_FIELDS and isinstance(item, str) and item else rebase_paths(item, old_base, new_base) for (key, item) in value.items()}

def image_record(original, *, legacy=False):
    """Keep admitted image references, not repeated model quality declarations."""
    value = deepcopy(original)
    for (field, quality) in (('image', 'image_quality'), ('icon_image', 'icon_quality')):
        if (legacy or quality in value) and value.get(quality) != 'clear':
            value.pop(field, None)
        value.pop(quality, None)
    value.pop('image_quality_reason', None)
    return value

def _event(value, run, writer):
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(content.encode()).hexdigest()
    path = run / 'record_history' / (digest + '.json')
    if not path.exists():
        writer(path, value)
    return str(path.relative_to(run))

def write(history, base, temporary, rebase, writer):
    (base, temporary) = (Path(base), Path(temporary))
    run = base.parent.parent if base.parent.name == 'knowledge_snapshots' else base
    groups = {}
    for (ref, rows) in rebase(history, base, run).items():
        for (order, original) in enumerate(rows):
            value = image_record(original)
            header = {}
            if 'source_image' in value:
                header['source_image'] = value.pop('source_image')
            evidence = value.get('evidence', {})
            header['source'] = {key: evidence.pop(key) for key in ('source_call', 'observation') if key in evidence}
            key = json.dumps(header, sort_keys=True, ensure_ascii=False)
            group = groups.setdefault(key, {**header, 'objects': []})
            group['objects'].append({'object': ref, 'order': order, 'value': value})
    refs = []
    for group in groups.values():
        refs.append(_event(group, run, writer))
    writer(temporary / 'object_history.json', {'events': refs})

def write_actions(actions, base, temporary, rebase, writer):
    (base, temporary) = (Path(base), Path(temporary))
    run = base.parent.parent if base.parent.name == 'knowledge_snapshots' else base
    refs = {ref: _event({'action': ref, 'record': row}, run, writer) for (ref, row) in rebase(actions, base, run).items()}
    writer(temporary / 'action_log.json', refs)

def read_actions(snapshot, rebase=rebase_paths):
    snapshot = Path(snapshot)
    run = snapshot.parent.parent if snapshot.parent.name == 'knowledge_snapshots' else snapshot
    refs = json.loads((snapshot / 'action_log.json').read_text())
    return {ref: rebase(json.loads((run / path).read_text())['record'], run, snapshot) for (ref, path) in refs.items()}

def write_tasks(history, base, temporary, rebase, writer):
    (base, temporary) = (Path(base), Path(temporary))
    run = base.parent.parent if base.parent.name == 'knowledge_snapshots' else base
    refs = {ref: {key: _event({'task': ref, 'field': key, 'value': value}, run, writer) for (key, value) in fields.items()} for (ref, fields) in rebase(history, base, run).items()}
    writer(temporary / 'task_history.json', refs)

def read_tasks(snapshot, rebase=rebase_paths):
    snapshot = Path(snapshot)
    run = snapshot.parent.parent if snapshot.parent.name == 'knowledge_snapshots' else snapshot
    refs = json.loads((snapshot / 'task_history.json').read_text())
    return {ref: {key: rebase(json.loads((run / path).read_text())['value'], run, snapshot) for (key, path) in fields.items()} for (ref, fields) in refs.items()}

def read(snapshot, rebase=rebase_paths):
    snapshot = Path(snapshot)
    index = snapshot / 'object_history.json'
    if not index.exists():
        return {}
    run = snapshot.parent.parent if snapshot.parent.name == 'knowledge_snapshots' else snapshot
    result = {}
    for relative in json.loads(index.read_text())['events']:
        event = rebase(json.loads((run / relative).read_text()), run, snapshot)
        for row in event['objects']:
            value = deepcopy(row['value'])
            if 'source_image' in event:
                value['source_image'] = event['source_image']
            if event.get('source'):
                value.setdefault('evidence', {}).update(event['source'])
            result.setdefault(row['object'], []).append((row['order'], value))
    return {ref: [value for (_, value) in sorted(rows, key=lambda row: row[0])] for (ref, rows) in result.items()}
