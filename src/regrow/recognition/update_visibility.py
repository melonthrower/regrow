"""Resolve the reported foreground; retain old visibility rules for saved replies."""
from regrow.records.object_store import observation_history
from regrow.records.observations import frame_observation
from regrow.records.object_store import owned_controls
from pathlib import Path
from regrow.recognition import identity_templates as templates

def has_interactive(reply):
    """Retained name: test whether a foreground Region was observed, not controls."""
    if 'current_regions' in reply:
        return bool(reply['current_regions'])
    return bool(reply.get('regions') or any(p['state'] in ('retained_interactive', 'changed_interactive')
                                          for p in historical_changes(reply)))

def historical_changes(reply, records=None, names=None):
    """Read archived pre-current_regions replies; new replies never use this field."""
    if 'current_regions' in reply:
        return []
    from regrow.recognition.region_candidate_names import resolve
    return [{'region': resolve(records, row['ref'], names) if records is not None else row['ref'],
             'state': row['state'], **({'evidence': row['evidence']} if row.get('evidence') else {})}
            for row in reply.get('previous_regions', [])]

def selected_indices(reply, names=None):
    """Rows explicitly selected as current, including rows selected by stable ref."""
    if 'current_regions' not in reply:
        return set(range(len(reply.get('regions', []))))
    names = names or {}
    refs = {names.get(row['ref'], row['ref']) for row in reply['current_regions'] if row.get('ref')}
    indexes = {row['region_index'] for row in reply['current_regions'] if type(row.get('region_index')) is int}
    indexes.update(i for i, row in enumerate(reply.get('regions', []))
                   if row.get('name') in refs or row.get('ref')
                   and (row.get('_matched_id') or names.get(row['ref'], row['ref'])) in refs)
    return indexes

def current_refs(reply, records, delta_refs, names=None):
    """Preserve membership positions for evidence; callers may deduplicate IDs."""
    from regrow.recognition.region_candidate_names import resolve
    return [delta_refs[row['region_index']] if 'region_index' in row
            else resolve(records, row['ref'], names) for row in reply['current_regions']]

def regions(delta_refs, changes, exception):
    if exception != 'none':
        return []
    blocked = {p['region'] for p in changes if p['state'] not in ('retained_interactive', 'changed_interactive')}
    return list(dict.fromkeys([r for r in delta_refs if r not in blocked] + [p['region'] for p in changes if p['state'] in ('retained_interactive', 'changed_interactive')]))

def locate_retained(records, region_refs, call, snapshot, frame, matcher, *, observation=None):
    """Relocate old controls in foreground Regions, including partially changed ones."""
    refs = []
    if not frame or not Path(frame).is_file():
        return refs
    for rid in region_refs:
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
