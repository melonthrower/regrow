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
        if control.get('shared_control_ref'):
            shared += 1
            continue
        path = image(control, rid, snapshot)
        if not path:
            continue
        eligible += 1
        hit = match(path)
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
    (rows, mapping) = names.candidates(records, rows)
    selected = set(mapping.values())
    evidence = [{**row, 'region_ref': mapping[row['ref']]} for row in rows]
    evidence.extend(({'region_ref': rid, 'name': r['name'], '提供原因': ['历史身份索引；未进入本轮视觉或来源候选'], '当前状态': '未定位；仅供身份核对', '披露范围': '仅历史身份索引'} for (rid, r) in records.items() if rid not in selected))
    return names.candidates(records, evidence)

def attach(request, records, ranking, mapping, snapshot=None):
    """Disclose historical identity as text; preserve only the caller’s evidence frames."""
    result = deepcopy(request)
    labels = {rid: label for (label, rid) in mapping.items()}
    dynamic = json.loads(result['user_prompt'])
    rows = []
    for candidate in rank(ranking) if all((r.get('foreground_confirmed') for r in ranking)) else sorted(ranking, key=lambda r: r['region']):
        rid = candidate['region']
        if rid not in labels:
            continue
        r = records[rid]
        if not candidate.get('anchors') and (not candidate.get('matched_controls')):
            continue
        rows.append({'候选': labels[rid], '行为适用上下文': r.get('behavior_context', ''), '前景独立控件命中数': candidate['matched_controls'] if candidate.get('foreground_confirmed') else None, '状态': '已按同帧前景限定' if candidate.get('foreground_confirmed') else '候选位置尚未经前景核对，不是有效票数', '有合格模板的控件数': candidate['eligible_controls'], '历史控件总数': candidate['total_controls'], '共享控件不参与区分': candidate.get('shared_controls', 0), '命中控件': [{'名称': owned_controls(r)[h['control']]['name'], '当前候选位置': h['box']} for h in candidate['anchors']]})
    dynamic['历史匹配对照'] = {'候选匹配线索': rows}
    result['user_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    if 'dynamic_prompt' in result:
        result['dynamic_prompt'] = result['user_prompt']
    return result
