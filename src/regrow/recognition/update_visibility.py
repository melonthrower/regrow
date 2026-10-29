"""Combine observed unchanged Regions with deltas; old crops remain historical."""
from regrow.records.object_store import observation_history
from regrow.records.observations import frame_observation
from regrow.records.object_store import owned_controls
from pathlib import Path
from regrow.recognition import identity_templates as templates

def has_interactive(reply):
    """Retained name: test whether a foreground Region was observed, not controls."""
    return bool(reply['regions'] or any((p['state'] in ('retained_interactive', 'changed_interactive') for p in reply['previous_regions'])))

def regions(delta_refs, changes, exception):
    if exception != 'none':
        return []
    blocked = {p['region'] for p in changes if p['state'] not in ('retained_interactive', 'changed_interactive')}
    return list(dict.fromkeys([r for r in delta_refs if r not in blocked] + [p['region'] for p in changes if p['state'] in ('retained_interactive', 'changed_interactive')]))

def locate_retained(records, changes, call, snapshot, frame, matcher, *, observation=None):
    """Relocate old controls in foreground Regions, including partially changed ones."""
    refs = []
    if not frame or not Path(frame).is_file():
        return refs
    for change in changes:
        if change['state'] not in ('retained_interactive', 'changed_interactive'):
            continue
        rid = change['region']
        current = []
        for (cid, control) in owned_controls(records[rid]).items():
            row = frame_observation(control, kind='controls', call=call, observation=observation)
            if row.get('evidence', {}).get('source_call') == call and (observation is None or row.get('evidence', {}).get('observation') == observation):
                box = row.get('bbox')
                if box:
                    current.append((cid, [box[k] for k in ('left', 'top', 'right', 'bottom')]))
        for (cid, control) in owned_controls(records[rid]).items():
            observations = observation_history(control)
            if not observations:
                continue
            latest = frame_observation(control, kind='controls', call=call, observation=observation)
            if latest.get('evidence', {}).get('source_call') == call and (observation is None or latest.get('evidence', {}).get('observation') == observation):
                continue
            appearances = [{**row, 'image': str((snapshot / row['image']).resolve())}
                           for row in templates.variants(control) if (snapshot / row['image']).is_file()]
            if appearances:
                from regrow.recognition.matching import match_appearances
                hit = match_appearances(appearances, lambda path: matcher.locate(path, str(frame)))
                if not hit['accepted']:
                    continue
                box = hit.get('box')
                if box and any((other != cid and _same_position(box, area) for (other, area) in current)):
                    continue
                refs.append(cid)
    return refs

def _same_position(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return area > 0 and overlap / area > 0.8
