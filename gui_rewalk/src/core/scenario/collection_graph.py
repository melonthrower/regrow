"""Read-only graph inputs shared by instruction generation and collection.

Stepwise records retain their own functions and observed candidate relations;
they are never converted into fabricated exploration States or verified edges.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


@dataclass
class StepwiseCollectionGraph:
    source: Path
    snapshot: Path
    records: dict
    controls: dict
    regions: dict
    digest: str
    dependencies: dict

    def inventory(self):
        return [{'region_ref': rid, 'name': r['name'], 'description': r.get('description', ''),
                 'functions': deepcopy(r.get('functions', {})), 'tasks': deepcopy(r.get('tasks', {})),
                 'region_role': r.get('region_role'), 'out_of_scope_reason': r.get('out_of_scope_reason')}
                for rid, r in self.records.items() if r.get('functions') and not r.get('out_of_scope_reason')]


def load_collection_graph(source):
    """Load a ledger or pinned stepwise snapshot; digest every consumed dependency."""
    source = Path(source).expanduser().resolve()
    raw = source.read_bytes()
    pointer = json.loads(raw)
    if not isinstance(pointer, dict) or 'snapshot' not in pointer:
        from ..explore.ledger import ExplorationLedger
        return ExplorationLedger.load(source), hashlib.sha256(raw).hexdigest()
    snapshot = (source.parent / pointer['snapshot']).resolve()
    snapshot.relative_to(source.parent / 'knowledge_snapshots')
    paths = sorted((snapshot / 'regions').glob('*/region.json'))
    if not paths:
        raise ValueError('Stepwise snapshot has no registered Regions')
    records = {p.parent.name: json.loads(p.read_text(encoding='utf-8')) for p in paths}
    if any(r.get('id') != rid or not r.get('name') for rid, r in records.items()):
        raise ValueError('Stepwise Region identity does not match its record path')
    from .collection_visual_guard import snapshot_controls
    controls = snapshot_controls(snapshot)
    dependencies = [source, *paths, *(Path(c['image']) for c in controls.values())]
    hashes = []
    for path in sorted(set(dependencies)):
        path = path.resolve()
        relative = str(path.relative_to(source.parent))
        hashes.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    digest = hashlib.sha256(json.dumps(hashes, ensure_ascii=False).encode()).hexdigest()
    regions = {rid: SimpleNamespace(region_id=rid, name=r['name'], memory=json.dumps({
        'description': r.get('description', ''), 'functions': r.get('functions', {}),
        'tasks': r.get('tasks', {}), 'controls': [{'ref': cid, 'name': c['name']}
        for cid, c in r.get('controls', {}).items()]}, ensure_ascii=False)) for rid, r in records.items()}
    return StepwiseCollectionGraph(source, snapshot, records, controls, regions, digest, dict(hashes)), digest


def collection_relations(graph):
    if not isinstance(graph, StepwiseCollectionGraph):
        from ..explore.region_routes import region_relations
        return region_relations(graph)
    edges = []
    for rid, region in graph.records.items():
        for edge in region.get('transitions', []):
            action = region.get('actions', {}).get(edge.get('attempt'), {})
            target = edge.get('target_region')
            if (target not in graph.regions or target == rid
                    or target not in action.get('interactive_regions', [])
                    or action.get('delivery') != 'executed_receipt_zero'
                    or action.get('result', {}).get('exception') != 'none'):
                continue
            edges.append({'source_region_ref': rid, 'revealed_region_refs': [target],
                          'source_control': edge.get('source_control'), 'attempt_ref': edge['attempt'],
                          'relation': edge.get('relation', 'observed_interactive_candidate'),
                          'operation': action.get('operation'), 'purpose': action.get('purpose'),
                          'observed_result': deepcopy(action.get('result', {})),
                          'destination_behavior': action.get('destination_behavior'),
                          'navigation_description': action.get('navigation_description')})
    return edges
