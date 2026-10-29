from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Read-only Region graph projection from a single committed knowledge snapshot.'
from regrow.records.object_store import owned_controls
import json
from pathlib import Path
from urllib.parse import urlencode
from regrow.records.tasks import coverage
from regrow.records.navigation import contextual_return
from regrow.records.navigation import navigation_description
from regrow.records import page_context as page_context

def read(path):
    return json.loads(Path(path).read_text())

def snapshot(run, version=None):
    run = Path(run).resolve()
    version = version or read(run / 'knowledge_current.json')['snapshot']
    base = (run / version).resolve()
    base.relative_to(run / 'knowledge_snapshots')
    return (run, base, version)

def asset(run, version, rid, cid=None):
    (run, base, _) = snapshot(run, version)
    records = object_store.load(base)
    if rid not in records:
        raise ValueError('Unknown region')
    record = records[rid]
    item = owned_controls(record)[cid] if cid else record
    row = next((x for x in reversed(observation_history(item)) if x.get('image')), None)
    if not row:
        raise ValueError('No saved crop')
    path = (base / row['image']).resolve()
    path.relative_to(run)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('Not an image')
    return path

def project(run):
    (run, base, version) = snapshot(run)
    records = object_store.load(base)
    state = read(base / 'runtime_state.json')
    nodes = []
    edges = {}

    def picture(rid, cid=None):
        try:
            asset(run, version, rid, cid)
        except (OSError, ValueError, KeyError):
            return None
        args = {'snapshot': version, 'region': rid}
        if cid:
            args['control'] = cid
        return '/graph-image?' + urlencode(args)
    for (rid, r) in records.items():
        controls = []
        for (cid, c) in owned_controls(r).items():
            actions = [{'attempt': aid, 'operation': a.get('operation'), 'description': navigation_description(a), 'exception': a.get('result', {}).get('exception', 'none'), 'delivery': a.get('delivery')} for (aid, a) in owned_actions(r).items() if a.get('control') == cid]
            controls.append({'id': cid, 'name': c['name'], 'description': c.get('description') or c.get('icon_description', ''), 'image': picture(rid, cid), 'actions': actions, 'tasks': [{'name': n, 'status': t.get('status'), 'reason': t.get('reason', '')} for (n, t) in owned_tasks(r).items() if t.get('control') == cid]})
        nodes.append({'id': rid, 'name': r['name'], 'description': r.get('description', ''), 'image': picture(rid), 'current': rid in state.get('interactive_regions', []), 'working': rid == state.get('working_region'), 'progress': coverage(r, records), 'controls': controls})
        for t in r.get('transitions', []):
            aid = t.get('attempt')
            a = owned_actions(r).get(aid, {})
            dest = t.get('target_region')
            cid = t.get('source_control')
            if dest == rid or dest not in records or a.get('delivery') != 'executed_receipt_zero':
                continue
            if dest not in a.get('interactive_regions', []) or a.get('result', {}).get('exception', 'none') != 'none':
                continue
            op = a.get('operation', 'click')
            key = (rid, cid, dest, op)
            if key not in edges:
                edges[key] = {'source': rid, 'target': dest, 'control': cid, 'control_name': owned_controls(r).get(cid, {}).get('name', '未绑定具体控件') + ('（返回目标依赖进入路径）' if contextual_return(a) else ''), 'operation': op, 'attempts': [], 'description': navigation_description(a)}
            if aid not in edges[key]['attempts']:
                edges[key]['attempts'].append(aid)
    from regrow.records.environment_context import forest, local_progress
    trees = {'controls': forest(records, view='controls', focus=state.get('working_region')),
             'operations': forest(records, view='operations', focus=state.get('working_region')),
             'progress': local_progress(records, state.get('working_region'))}
    return {'trees': trees, 'snapshot': version, 'app': read(run / 'run_manifest.json').get('app', run.name), 'working': state.get('working_region'), 'nodes': nodes, 'edges': list(edges.values()), 'page_context': page_context.live(records, state, run)}
