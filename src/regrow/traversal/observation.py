from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import hashlib
import json
from pathlib import Path
from regrow.recognition import identity_templates as templates
from regrow.recognition.locator import request_from_run

def run_stage(root, run, call, repair=None):
    """Share the same stage driver after recovery or another lost-location event."""
    from regrow.traversal import repair_stages as _repair_stages
    from regrow.traversal import discovery_step as _discovery_step
    for _ in range(3):
        request = request_from_run(root, run)
        if repair is not None:
            pointer = repair.perform('discovery', request)['result']
        else:
            (ref, reply) = call(request)
            pointer = _repair_stages.accept(root, run, {'stage': 'discovery', 'request': request, 'call': ref, 'candidate': reply})
        if _record_load(run)[2]['next_action_mode'] != 'discover':
            return pointer
    raise ValueError('discovery remains unresolved; inspect saved evidence')

def focus_task(records, state, q):
    """Carry the bound task into observation, independently of batch scan progress."""
    from regrow.traversal import work_context as _work_context
    source = q.get('source', {})
    rid = source.get('region')
    work = _work_context.from_request(q, records, state)
    state['active_task'] = work.get('task')
    if rid not in records:
        return
    region = records[rid]
    task = owned_tasks(region).get(source.get('task_name'), {})
    cid = task.get('control')
    state['inspection_region'] = rid
    state.pop('discovery_mode', None)
    if cid in owned_controls(region):
        state['required_control'] = cid
        state['correction_context'] = '请定位原任务「' + source['task_name'] + '」的控件「' + owned_controls(region)[cid]['name'] + '」，核对是否可见并登记当前定位。'
    else:
        state.pop('required_control', None)

def rediscover(run, q, reason):
    """One inspection per unchanged frame/Region/action; guard survives resume."""
    from regrow.traversal import discovery_step as _discovery_step
    (_, _, state) = _record_load(run)
    frame = str((Path(run) / q['screenshots'][0]).resolve())
    rid = q['source']['region']
    key = hashlib.sha256(Path(frame).read_bytes() + json.dumps([rid, state.get('last_action_result')], sort_keys=True).encode()).hexdigest()
    if key in state.get('task_reinspection', []):
        return False

    def mutate(records, state, snapshot, temp):
        state.setdefault('task_reinspection', []).append(key)
        state.update(next_action_mode='discover', phase='awaiting_discovery', pending_frame=frame, inspection_region=rid, reason='task_registration_needs_observation', correction_context=reason)
        focus_task(records, state, q)
    _record_publish(run, 'task-inspection-' + key[:12], mutate)
    return True

def locate_task_control(run, q, frame):
    """Refresh only the chosen task's missing control, using current visual evidence."""
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.recognition import matching as _image_match
    source = q.get('source', {})
    cid = source.get('task_control')
    rid = source.get('completion_region') or source.get('task_region')
    if not cid or not rid:
        return False
    (snapshot, records, state) = _record_load(run)
    obs = state.get('observation') or {}
    if rid not in state.get('interactive_regions', []):
        return False
    if any((c.get('id') == cid for c in q.get('backend_candidates', []))):
        return False
    control = owned_controls(records.get(rid, {})).get(cid, {})
    row = templates.latest(control)
    if not row:
        return False
    path = (snapshot / row['image']).resolve()
    if not path.is_file():
        return False
    match = _image_match.locate(str(path), str(frame))
    if not match['accepted']:
        return False
    import uuid

    def mutate(records, state, *args):
        state['observation']['control_refs'] = list(dict.fromkeys([*obs.get('control_refs', []), cid]))
        proof = state.setdefault('visual_navigation', {'observation': obs['id'], 'controls': {}})
        if proof.get('observation') != obs['id']:
            proof = {'observation': obs['id'], 'controls': {}}
            state['visual_navigation'] = proof
        proof.setdefault('controls', {})[cid] = rid
        proof.setdefault('task_matches', {})[cid] = {'frame': str(frame), 'match': match}
    _record_publish(run, 'task-location-' + uuid.uuid4().hex, mutate)
    return True

class Locator:

    def __init__(self, root, run, frame, call, repair):
        (self.root, self.run, self.frame) = (root, run, frame)
        (self.call, self.repair) = (call, repair)

    def discover(self):
        from regrow.traversal import discovery_step as _discovery_step
        from regrow.recognition import discovery_completion as _discovery_completion
        discovery = _discovery_step
        state = _record_load(self.run)[2]
        batch = state.get('discovery_completion') or {}
        if batch.get('pending') and batch.get('sha256') != _discovery_completion.fingerprint(self.frame):
            discovery.await_discovery(self.run, str(self.frame), 'fresh-discovery-' + self.frame.parent.name)
        return run_stage(self.root, self.run, self.call, repair=self.repair)

    def locate_control(self, request):
        return locate_task_control(self.run, request, self.frame)
