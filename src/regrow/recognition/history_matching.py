"""Read-only historical identity recall: unique control votes and model evidence."""
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path
import json
from regrow.recognition import identity_templates as templates
from regrow.recognition import region_candidate_names as names

def image(item, rid=None, snapshot=None):
    path = templates.image(item)
    if path and snapshot is not None:
        path = str((Path(snapshot) / path).resolve())
    return path

def match_region(rid, region, match, frame, snapshot=None, scope=None):
    """One eligible template per control, one vote per distinct current position."""
    hits = []
    eligible = 0
    shared = 0
    for (cid, control) in owned_controls(region).items():
        records = getattr(region, 'store', {rid: region})
        from regrow.records.shared_controls import view
        if view(records, rid, cid):
            shared += 1
            continue
        appearances = [{**row, 'image': str((Path(snapshot) / row['image']).resolve()) if snapshot is not None else row['image']}
                       for row in templates.variants(control)]
        if not appearances:
            continue
        eligible += 1
        from regrow.recognition.matching import match_appearances
        hit = match_appearances(appearances, match)
        if hit.get('accepted'):
            hits.append({'control': cid, **hit})
    unique = []
    for hit in sorted(hits, key=lambda h: -h.get('score', 0)):
        (l, t, r, b) = hit['box']
        (x, y) = ((l + r) / 2, (t + b) / 2)
        if not any((abs(x - (h['box'][0] + h['box'][2]) / 2) < 8 and abs(y - (h['box'][1] + h['box'][3]) / 2) < 8 for h in unique)):
            unique.append(hit)
    return {'region': rid, 'whole': {'accepted': False, 'reason': 'control_votes_only'}, 'anchors': unique, 'bounds': None, 'strong': False, 'matched_controls': len(unique), 'eligible_controls': eligible, 'total_controls': len(owned_controls(region)), 'shared_controls': shared, 'foreground_confirmed': False}

def rank(rows):
    return sorted(rows, key=lambda r: (-r['matched_controls'], r['region']))

def scan(records, snapshot, frame, scope=None):
    """Recall appearances on the current full frame; semantic foreground stays separate."""
    from regrow.recognition.matching import SceneMatcher
    from PIL import Image
    import numpy as np
    scenes = {}
    cache = {}

    def match(path, scene=frame):
        key = (str(path), str(scene))
        if key not in cache:
            try:
                if str(scene) not in scenes:
                    scenes[str(scene)] = SceneMatcher(scene)
                with Image.open(path) as image:
                    template = np.asarray(image.convert('RGB'))
                cache[key] = scenes[str(scene)].locate_pixels(template)
            except (FileNotFoundError, OSError):
                cache[key] = {'accepted': False, 'reason': 'missing_image'}
        return cache[key]
    return rank([match_region(rid, r, match, frame, snapshot, scope) for (rid, r) in records.items()])

def with_history(records, rows):
    """Only disclose identities selected by the caller's current question."""
    return names.candidates(records, rows)

def attach(request, records, ranking, mapping, snapshot=None):
    """Disclose historical identity as text; preserve only the caller’s evidence frames."""
    result = deepcopy(request)
    labels = {rid: label for (label, rid) in mapping.items()}
    dynamic = json.loads(result['user_prompt'])
    # Matching details belong to the same candidate, not a second catalog.
    slots = [dynamic.get(key, []) for key in ('本次身份候选', '程序匹配候选', '已知区块')]
    selected = {r['region']: r for r in ranking}
    for rows in slots:
        for row in rows:
            rid = mapping.get(row.get('ref'), row.get('ref'))
            candidate = selected.get(rid)
            if candidate and candidate.get('anchors'):
                row['本图外观线索'] = [owned_controls(records[rid])[h['control']]['name'] for h in candidate['anchors']]
    result['matching_audit'] = deepcopy(ranking)
    result['user_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    if 'dynamic_prompt' in result:
        result['dynamic_prompt'] = result['user_prompt']
    return result
