"""Inspect dangling function links and restore reviewed historical functions.

Usage: python tools/repair_graph.py inspect RUN OUTPUT.json
       python tools/repair_graph.py apply PLAN.json
Only restores selected, previously registered functions; never replays GUI actions.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from regrow.records import snapshots, object_store, function_updates
from regrow.tools.debug_loop import device_lock, live_run


def ancestry(run, snapshot):
    seen = set()
    while snapshot:
        path = (run / snapshot).resolve()
        if not path.is_relative_to(run / 'knowledge_snapshots') or path in seen:
            raise ValueError('Invalid snapshot ancestry')
        seen.add(path)
        yield path
        snapshot = snapshots.read(path / 'source.json').get('parent_snapshot')


def restored_update(records, rid, name, historical):
    supports = historical.get('support_controls', [])
    if not supports or any(s.get('region') != rid or s.get('control') not in
                           object_store.owned_controls(records[rid]) for s in supports):
        raise ValueError('Historical supports no longer belong to this Region; requires semantic review')
    row = {k: deepcopy(historical[k]) for k in
           ('description', 'object', 'completion', 'unconfirmed') if k in historical}
    row.update(name=name, supports=[s['control'] for s in supports],
               parameters=list(historical.get('parameters', {})))
    return {'region': rid, 'add': [row]}


def inspect(run):
    run = Path(run).resolve()
    pointer = snapshots.read(run / 'knowledge_current.json')
    _, records, _ = snapshots.load(run)
    missing = {}
    for rid, region in records.items():
        for name, task in object_store.owned_tasks(region).items():
            for ref in task.get('function_refs', []):
                try:
                    function_updates.resolve(records, ref, rid)
                except ValueError:
                    missing.setdefault(ref, []).append({'region': rid, 'task': name,
                                                       'status': task.get('status')})
    candidates = {}
    for path in ancestry(run, pointer['snapshot']):
        if len(candidates) == len(missing):
            break
        old = object_store.load(path)
        for ref in missing.keys() - candidates.keys():
            rid, _, name = ref.partition('/')
            historical = old.get(rid, {}).get('functions', {}).get(name)
            if historical is not None:
                candidates[ref] = {'ref': ref, 'snapshot': str(path.relative_to(run)),
                                   'function': historical, 'reason': ''}
    return {'run': str(run), 'expected_pointer': pointer, 'missing': missing,
            'restore': list(candidates.values()),
            'unresolved': sorted(missing.keys() - candidates.keys())}


def apply(plan):
    run = Path(plan['run']).resolve()
    with device_lock(run):
        if live_run(run):
            raise ValueError('Stop traversal before repairing its graph')
        if snapshots.read(run / 'knowledge_current.json') != plan['expected_pointer']:
            raise ValueError('Graph changed after inspection; inspect again')
        ancestors = set(ancestry(run, plan['expected_pointer']['snapshot']))
        if not plan['restore']:
            raise ValueError('No selected restoration')
        for item in plan['restore']:
            if not item.get('reason', '').strip():
                raise ValueError('Each restoration needs a reviewed reason')
            path = (run / item['snapshot']).resolve()
            if path not in ancestors:
                raise ValueError('Candidate is not an ancestor of the current graph')
            rid, _, name = item['ref'].partition('/')
            original = object_store.load(path)[rid]['functions'][name]
            if original != item['function']:
                raise ValueError('Historical function was edited; restoration must preserve its content')
        tag = 'graph-repair-' + uuid.uuid4().hex

        def mutate(records, state, snapshot, temp):
            updates = [restored_update(records, *item['ref'].split('/', 1), item['function'])
                       for item in plan['restore']]
            # The normal add checks current knowledge, support and parameter references.
            # Apply all selected restorations together so cross-links validate together.
            function_updates.apply(records, updates, {})
            for item in plan['restore']:
                rid, name = item['ref'].split('/', 1)
                records[rid]['functions'][name]['source_call'] = item['function'].get('source_call')
            snapshots.write_json(temp / 'repair.json', plan)

        return snapshots.publish(run, tag, mutate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inspect'); p.add_argument('run', type=Path); p.add_argument('output', type=Path)
    p = sub.add_parser('apply'); p.add_argument('plan', type=Path)
    args = parser.parse_args()
    if args.command == 'inspect':
        if args.output.exists():
            raise ValueError('Do not overwrite an earlier repair plan')
        result = inspect(args.run)
        snapshots.write_json(args.output, result)
        print(f"Dangling links: {len(result['missing'])}; historical candidates: {len(result['restore'])}")
    else:
        import json
        print(json.dumps(apply(snapshots.read(args.plan)), ensure_ascii=False))


if __name__ == '__main__':
    main()
