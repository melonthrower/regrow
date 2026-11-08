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
import sys

# Both ordinary CLIs enter through gui_rewalk; the maintained record reader is
# a sibling package. Import it here once, without a second snapshot decoder.
REGROW_SOURCE = Path(__file__).resolve().parents[4] / 'src'
if str(REGROW_SOURCE) not in sys.path:
    sys.path.insert(0, str(REGROW_SOURCE))
from regrow.records import object_store, control_knowledge, function_updates


def read_stepwise_records(snapshot):
    """Use the framework reader and retain the files it consumes in the digest."""
    snapshot = Path(snapshot)
    if (snapshot / 'objects.json').exists():
        store = object_store.load(snapshot)
        records = {rid: object_store.region_state(r) for rid, r in store.items()}
        paths = [snapshot / name for name in ('objects.json', 'runtime_work.json',
                 'tasks.json', 'object_history.json', 'action_log.json', 'task_history.json')
                 if (snapshot / name).exists()]
        run = snapshot.parent.parent
        for name in ('object_history.json', 'action_log.json', 'task_history.json'):
            path = snapshot / name
            if not path.exists():
                continue
            index = json.loads(path.read_text())
            refs = (index['events'] if name == 'object_history.json' else
                    list(index.values()) if name == 'action_log.json' else
                    [ref for fields in index.values() for ref in fields.values()])
            paths.extend(run / ref for ref in refs)
    else:
        paths = sorted(snapshot.glob('regions/*/region.json'))
        # Preserve the existing legacy task/record meanings; only normalize the
        # image base so the shared visual reader can consume either layout.
        records = {p.parent.name: object_store.rebase(json.loads(p.read_text()), p.parent, snapshot) for p in paths}
    if not records:
        raise ValueError('Stepwise snapshot has no registered Regions')
    return records, paths


def region_material(rid, region):
    """The collector's full Region memory; generation selects its own material."""
    controls = []
    for cid, control in region.get('controls', {}).items():
        controls.append({'ref': cid, 'name': control['name'],
                         'knowledge': [{k: v for k, v in row.items() if k != 'parameters'}
                                       for row in control_knowledge.card(control) if row.get('description')],
                         'parameters': control_knowledge.parameter_facts(control),
                         'knowledge_source': control_knowledge.evidence(control),
                         **{key: deepcopy(control[key]) for key in ('description', 'may_open_content', 'needs_exploration', 'jump_to') if key in control}})
    functions = {name: object_store.normalize_parameters(deepcopy(function))
                 for name, function in region.get('functions', {}).items()}
    for function in functions.values():
        if function.get('parameters'):
            function['parameters'] = function_updates.resolved_parameters(region, function)
    return {'region_ref': rid, 'name': region['name'], 'description': region.get('description', ''),
            'functions': functions, 'local_knowledge': deepcopy(region.get('local_knowledge', {})),
            'parameters': control_knowledge.parameter_facts(region), 'controls': controls,
            'list_groups': deepcopy(region.get('list_groups', {})),
            'tasks': deepcopy(region.get('tasks', {})), 'region_role': region.get('region_role'),
            'out_of_scope_reason': region.get('out_of_scope_reason')}


def generation_material(rid, region):
    """Select usage knowledge, without exploration work or recording metadata."""
    def parameters(facts):
        result = deepcopy(facts)
        for fact in result.values():
            for key in ('source', 'sources'):
                fact.pop(key, None)
            for observation in fact.get('observations', []):
                observation.pop('source', None)
        return result

    controls = [
        {'ref': cid, 'source_ref': rid + '.' + cid, 'name': control['name'],
         'description': control.get('description', ''),
         'knowledge': [{'description': row['description']}
                       for row in control_knowledge.items(control.get('knowledge'))
                       if row.get('description')],
         'parameters': parameters(control_knowledge.parameter_facts(control))}
        for cid, control in region.get('controls', {}).items()]
    functions = {}
    for name, function in region.get('functions', {}).items():
        functions[name] = {
            'source_ref': function_updates.reference(rid, name),
            'description': function_updates.description(function),
            'support_controls': [{key: deepcopy(support[key])
                                  for key in ('kind', 'region', 'control', 'name') if key in support}
                                 for support in function.get('support_controls', [])],
            'parameters': parameters(function_updates.resolved_parameters(region, function))}
    return {'region_ref': rid, 'name': region['name'],
            'description': region.get('description', ''), 'functions': functions,
            'local_knowledge': deepcopy(region.get('local_knowledge', {})),
            'parameters': parameters(control_knowledge.parameter_facts(region)),
            'controls': controls}


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
        material = [generation_material(rid, r) for rid, r in self.records.items() if not r.get('out_of_scope_reason')]
        return [row for row in material if row['functions'] or row['local_knowledge'] or row['parameters']
                or any(c['knowledge'] or c['parameters'] for c in row['controls'])]


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
    records, paths = read_stepwise_records(snapshot)
    if any(r.get('id') != rid or not r.get('name') for rid, r in records.items()):
        raise ValueError('Stepwise Region identity does not match its record path')
    from .collection_visual_guard import snapshot_controls
    controls = snapshot_controls(snapshot, records=records)
    dependencies = [source, *paths, *(Path(c['image']) for c in controls.values())]
    hashes = []
    for path in sorted(set(dependencies)):
        path = path.resolve()
        relative = str(path.relative_to(source.parent))
        hashes.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    digest = hashlib.sha256(json.dumps(hashes, ensure_ascii=False).encode()).hexdigest()
    regions = {rid: SimpleNamespace(region_id=rid, name=r['name'],
                memory=json.dumps(region_material(rid, r), ensure_ascii=False)) for rid, r in records.items()}
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
