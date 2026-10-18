"""Control recall; local scans reuse only same-frame model-confirmed boundaries."""
from regrow.records.object_store import owned_controls
from pathlib import Path
import hashlib
CONTROL_BATCH = 8
CANDIDATES = 8
from regrow.recognition import identity_templates as templates
from regrow.recognition import history_matching as history
from regrow.recognition import local_partition as local_partition

def matcher():
    from regrow.recognition import matching as m

    def locate(template, scene):
        if not isinstance(scene, tuple):
            return m.locate(template, scene)
        from PIL import Image
        import numpy as np
        (path, box) = scene
        with Image.open(template) as im:
            reference = np.asarray(im.convert('RGB'))
        with Image.open(path) as im:
            surface = np.asarray(im.convert('RGB').crop(box))
        result = m._search(reference, surface)
        for item in [result, *result.get('candidates', [])]:
            if item.get('box'):
                item['box'] = [v + box[i % 2] for (i, v) in enumerate(item['box'])]
        return result
    return locate

def image(item):
    return templates.image(item)

def resolve_foreground_check(plan, frame, interactive_regions, focus_presence, call, previous=None):
    """Consume an answered containment suspicion, never infer coexistence from pixels."""
    check = plan.get('foreground_check')
    focus = plan.get('focus')
    if not check or focus_presence != 'interactive' or (not {focus, check['region']} <= set(interactive_regions)):
        return None
    fingerprint = hashlib.sha256(Path(frame).read_bytes()).hexdigest()
    frame_path = str(Path(frame).resolve())
    previous = previous or {}
    checks = list(previous.get('checks', [])) if previous.get('focus') == focus and previous.get('frame_sha256') == fingerprint and (previous.get('frame_path') == frame_path) else []
    checks = [c for c in checks if c['region'] != check['region']] + [{'region': check['region'], 'source_call': call}]
    return {'checks': checks, 'frame_path': frame_path, 'status': 'resolved', 'conclusion': '两个区块均处于当前前景；矩形包含不构成遮挡，本次前景归属核对已解决。操作能力仍须另判。', 'focus': focus, 'region': check['region'], 'frame_sha256': hashlib.sha256(Path(frame).read_bytes()).hexdigest(), 'source_call': call}

def plan(records, focus, frame, *, force_relocate=False, required_control=None, offset=0, locate=None, foreground_resolution=None, foreground=None):
    locate = locate or matcher()
    cache = {}
    attempts = []
    scoped = {r['region']: r for r in history.scan(records, None, frame, scope=foreground)} if foreground is not None else {}

    def match(path, scene=frame):
        if not path:
            return {'accepted': False, 'reason': 'missing_image'}
        key = (str(path), str(scene))
        if key not in cache:
            try:
                cache[key] = locate(path, scene)
            except (FileNotFoundError, OSError):
                cache[key] = {'accepted': False, 'reason': 'missing_image'}
            attempts.append({'image': str(path), 'scene': str(scene), 'result': cache[key]})
        return cache[key]

    def region(rid):
        return scoped[rid] if rid in scoped else history.match_region(rid, records[rid], match, frame)
    local = region(focus) if focus in records and (not force_relocate) else None
    foreground_check = None
    confirmed = (foreground or {}).get('region_bounds', {}).get(focus)
    if local and focus in (foreground or {}).get('regions', (foreground or {}).get('region_bounds', {})):
        local = {**local, 'strong': True, 'bounds': confirmed, 'basis': 'same_frame_model_identity'}
    if local and local['strong'] and (not foreground_check):
        ids = list(owned_controls(records[focus]))
        chosen = [required_control] if required_control in ids else ids[offset:offset + CONTROL_BATCH]
        surface = frame
        controls = [{'control': cid, 'match': match(image(owned_controls(records[focus])[cid]), surface)} for cid in chosen]
        return {'mode': 'local', 'focus': focus, 'focus_status': 'candidate', 'regions': [local], 'controls': controls, 'next_offset': offset + len(chosen), 'unchecked_controls': max(0, len(ids) - offset - len(chosen)), 'attempts': attempts, 'partition_context': local_partition.build(records, focus, frame, foreground, scoped)}
    candidates = []
    weak = []
    focus_candidate = None
    for rid in records:
        candidate = local if local and rid == focus else region(rid)
        if rid == focus:
            focus_candidate = candidate
        if candidate['strong'] or candidate['anchors']:
            candidates.append(candidate)
        elif 'score' in candidate['whole']:
            weak.append(candidate)
    candidates = history.rank(candidates) if foreground is not None else sorted(candidates, key=lambda c: c['region'])
    weak.sort(key=lambda c: -c['whole'].get('score', 0))
    if focus_candidate:
        candidates = [c for c in candidates if c['region'] != focus]
        candidates.insert(0, focus_candidate)
    weak = [c for c in weak if c['region'] != focus]
    candidates.extend(weak[:min(3, max(0, CANDIDATES - len(candidates)))])
    return {'foreground_check': foreground_check, 'mode': 'relocate', 'focus': focus, 'focus_status': 'unconfirmed', 'regions': (history.rank(candidates) if foreground is not None else candidates)[:CANDIDATES], 'controls': [], 'omitted_candidates': max(0, len(candidates) - CANDIDATES), 'attempts': attempts}
