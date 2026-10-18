from regrow.records.snapshots import read as _record_read
from regrow.records.snapshots import write_json as _record_write_json
from regrow.records.action_evidence import attach_execution as _record_attach_execution
from regrow.records import object_store as object_store
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from regrow.traversal.register_update import rebase

def commit_discovery(root, run, graph_ref):
    """Publish imported discovery/recorded evidence once, using the update schema.

    Also used to explicitly rebuild the historical pre-normalization experiment.
    Current normalized knowledge is never silently replaced by an older graph.
    """
    from regrow.records import region_evidence as _stepwise_flow
    run = Path(run).resolve()
    graph = _record_read(run / graph_ref)
    flow = _stepwise_flow
    digest = hashlib.sha256(json.dumps({'record_format': 'flat_region_controls', 'graph': graph}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    relative = f'knowledge_snapshots/discovery-{digest[:12]}'
    snapshot = run / relative
    current = run / 'knowledge_current.json'
    parent = _record_read(current)['snapshot'] if current.exists() else None
    pointer = {'snapshot': relative, 'sha256': digest}
    if snapshot.exists():
        if parent == _record_read(snapshot / 'source.json').get('parent_snapshot'):
            _record_write_json(run / 'knowledge_current.pending.json', pointer)
            os.replace(run / 'knowledge_current.pending.json', current)
        return pointer
    if parent and _record_read(run / parent / 'source.json').get('record_format') in ('region_image_knowledge', 'flat_region_controls'):
        raise ValueError('discovery already committed; use the update registration')
    records = flow.region_records(graph)
    _record_attach_execution(records, run)
    state = flow.graph_state(graph)
    state.update(update_status='committed', execution_status='not_started', phase='ready_for_next_action')
    if not state['interactive_regions']:
        state['next_action_mode'] = 'review_result'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.pending-', dir=snapshot.parent))
    try:
        object_store.save(rebase(records, run, snapshot), temp, _record_write_json)
        _record_write_json(temp / 'runtime_state.json', state)
        _record_write_json(temp / 'source.json', {'record_format': 'flat_region_controls', 'graph': graph_ref, 'digest': digest, 'parent_snapshot': parent})
        os.replace(temp, snapshot)
        _record_write_json(run / 'knowledge_current.pending.json', pointer)
        os.replace(run / 'knowledge_current.pending.json', current)
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    return pointer
from regrow.records.region_evidence import graph_state
from regrow.records.region_evidence import region_records
from regrow.traversal.action_context import assemble_context

def assemble_region_choice(root, graph, observation_ref, region_ref):
    """Saved-graph replay adapter; uses the same record schema and renderer."""
    state = graph_state(graph, observation_ref)
    if region_ref not in state['interactive_regions']:
        raise ValueError('working Region is not a current observation candidate')
    return assemble_context(root, region_records(graph, observation_ref), state, region_ref)
