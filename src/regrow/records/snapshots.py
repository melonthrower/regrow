"""Transactional record I/O and the single snapshot publication path."""
import json
from pathlib import Path

def read(path):
    from regrow.records import snapshots as _knowledge_transaction
    return json.loads(_knowledge_transaction.pointer(Path(path)).read_text())

def write_json(path, value):
    path = pointer(Path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import os
import uuid
_active = ContextVar('stepwise_knowledge_transaction', default=None)

def pointer(path):
    path = Path(path)
    active = _active.get()
    if active and path.resolve() == active[0]:
        return active[1]
    return path

@contextmanager
def transaction(run):
    original = Path(run).resolve() / 'knowledge_current.json'
    staged = original.with_name('.knowledge-' + uuid.uuid4().hex + '.json')
    staged.write_bytes(original.read_bytes())
    token = _active.set((original, staged))
    try:
        yield
        os.replace(staged, original)
    finally:
        _active.reset(token)
        staged.unlink(missing_ok=True)
from pathlib import Path
import hashlib, os, shutil, tempfile

def commit(run, temporary, snapshot, records, state, source, pointer):
    from regrow.records import object_store
    'One publication path for observations, action results and corrections.'
    from regrow.records import shared_controls
    from regrow.records import coverage_exemption
    from regrow.records import task_knowledge
    from regrow.records.snapshots import pointer as transaction_pointer
    (run, temporary, snapshot) = (Path(run), Path(temporary), Path(snapshot))
    shared_controls.refresh(records)
    coverage_exemption.reconcile(records, state)
    task_knowledge.refresh(records, state)
    object_store.save(records, temporary, write_json)
    write_json(temporary / 'runtime_state.json', state)
    write_json(temporary / 'source.json', source)
    os.replace(temporary, snapshot)
    pending = run / 'knowledge_current.pending.json'
    write_json(pending, pointer)
    os.replace(pending, transaction_pointer(run / 'knowledge_current.json'))
    return pointer

def load(run, snapshot=None):
    from regrow.records import object_store
    from regrow.records import action_evidence
    run = Path(run)
    snapshot = run / (snapshot or read(run / 'knowledge_current.json')['snapshot'])
    records = object_store.load(snapshot)
    action_evidence.resolve_operations(records, run)
    return (snapshot, records, read(snapshot / 'runtime_state.json'))

def publish(run, tag, mutate):
    from regrow.records import object_store
    'Atomic read-modify-publish; old evidence and snapshots remain immutable.'
    run = Path(run).resolve()
    (prior, records, state) = load(run)
    digest = hashlib.sha256((str(prior) + tag).encode()).hexdigest()
    relative = f'knowledge_snapshots/{tag}-{digest[:12]}'
    snapshot = run / relative
    if snapshot.exists():
        raise ValueError('checkpoint already exists; do not replay publication')
    records = object_store.rebase(records, prior, snapshot)
    temp = Path(tempfile.mkdtemp(prefix='.pending-', dir=snapshot.parent))
    try:
        mutate(records, state, snapshot, temp)
        state.update(update_digest=digest, update_status='committed')
        if (prior / 'recovery.json').exists():
            write_json(temp / 'recovery.json', object_store.rebase(read(prior / 'recovery.json'), prior, snapshot))
        pointer = {'snapshot': relative, 'sha256': digest}
        source = {'record_format': 'flat_region_controls', 'parent_snapshot': str(prior.relative_to(run)), 'digest': digest, 'stage': tag}
        return commit(run, temp, snapshot, records, state, source, pointer)
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
