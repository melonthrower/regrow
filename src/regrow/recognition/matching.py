"""Match recorded appearances and resolve repeated visual candidates; matching is not operation success."""
import cv2
import numpy as np
from PIL import Image
MIN_SCORE = 0.9
MIN_GAP = 0.05
MAX_CANDIDATES = 32

def _search(template, scene, scene_gray=None):
    """Recall strong spatial candidates; accept only a clearly unique one."""
    template_gray = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
    if template_gray.std() < 1:
        return {'accepted': False, 'candidates': [], 'reason': 'uninformative_template'}
    if scene_gray is None:
        scene_gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
    (height, width) = template_gray.shape
    if height > scene_gray.shape[0] or width > scene_gray.shape[1]:
        return {'accepted': False, 'candidates': [], 'reason': 'template_outside_surface'}
    scores = cv2.matchTemplate(scene_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    peaks = []
    truncated = False
    for peak in range(MAX_CANDIDATES):
        (_, score, _, (x, y)) = cv2.minMaxLoc(scores)
        if score <= -1 or (peak >= 2 and score < MIN_SCORE):
            break
        peaks.append({'score': float(score), 'box': [x, y, x + width, y + height], 'scale': 1})
        scores[max(0, y - height // 2):y + height // 2 + 1, max(0, x - width // 2):x + width // 2 + 1] = -1
    else:
        truncated = cv2.minMaxLoc(scores)[1] >= MIN_SCORE
    if not peaks:
        return {'accepted': False, 'candidates': [], 'reason': 'no_pixel_candidate'}
    best = peaks[0]
    gap = best['score'] - (peaks[1]['score'] if len(peaks) > 1 else 0)
    candidates = [p for p in peaks if p['score'] >= MIN_SCORE]
    accepted = bool(candidates) and (not truncated) and (gap >= MIN_GAP)
    return dict(best, gap=gap, accepted=accepted, candidates=candidates, candidates_truncated=truncated, reason='matched' if accepted else 'ambiguous_or_changed')

class SceneMatcher:
    """Cache one frame's original-size grayscale pixels for a template batch."""

    def __init__(self, scene_path):
        with Image.open(scene_path) as image:
            self.scene = np.asarray(image.convert('RGB'))
        self.scene_gray = cv2.cvtColor(self.scene, cv2.COLOR_RGB2GRAY)

    def locate_pixels(self, template):
        return _search(template, self.scene, self.scene_gray)

def locate(template_path, scene_path):
    with Image.open(template_path) as image:
        template = np.asarray(image.convert('RGB'))
    return SceneMatcher(scene_path).locate_pixels(template)
from pathlib import Path
from PIL import Image
import numpy as np

def overlap(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union > 0 else 0

def refine(controls, hits, frame, matcher):
    """Return strong individual hits unchanged; ambiguous groups need one allocation."""
    groups = {}
    for c in controls:
        hit = hits.get(c['id'], {})
        source = c.get('source_image')
        if hit.get('accepted') or hit.get('candidates_truncated') or len(hit.get('candidates', [])) < 2 or (not source) or (not Path(source).is_file()) or (not c.get('bbox')):
            continue
        groups.setdefault((c.get('region_ref'), str(Path(source).resolve())), []).append(c)
    result = dict(hits)
    scene = None
    for ((_, source), members) in groups.items():
        components = []
        remaining = list(members)
        while remaining:
            group = [remaining.pop(0)]
            while True:
                connected = [c for c in remaining if any((sum((any((overlap(a['identity_box'], b['identity_box']) >= 0.8 for b in hits[d['id']]['candidates'])) for a in hits[c['id']]['candidates'])) >= 2 for d in group))]
                if not connected:
                    break
                group.extend(connected)
                remaining = [c for c in remaining if c not in connected]
            if len(group) > 1:
                components.append(group)
        for group in components:
            boxes = [[c['bbox'][k] for k in ('left', 'top', 'right', 'bottom')] for c in group]
            if any((overlap(a, b) > 0 for (i, a) in enumerate(boxes) for b in boxes[i + 1:])):
                continue
            with Image.open(source) as im:
                original = np.asarray(im.convert('RGB'))
            valid = True
            for (c, (l, t, r, b)) in zip(group, boxes):
                if not (0 <= l < r <= original.shape[1] and 0 <= t < b <= original.shape[0]):
                    valid = False
                    break
                with Image.open(c['image']) as im:
                    template = np.asarray(im.convert('RGB'))
                if not np.array_equal(original[t:b, l:r], template):
                    valid = False
                    break
            if not valid:
                continue
            bounds = [min((b[0] for b in boxes)), min((b[1] for b in boxes)), max((b[2] for b in boxes)), max((b[3] for b in boxes))]
            (l, t, r, b) = bounds
            if scene is None:
                scene = matcher.SceneMatcher(frame)
            group_hit = scene.locate_pixels(original[t:b, l:r])
            if not group_hit.get('accepted'):
                continue
            current = group_hit['box']
            sx = (current[2] - current[0]) / (r - l)
            sy = (current[3] - current[1]) / (b - t)
            selected = {}
            used = []
            for (c, box) in zip(group, boxes):
                expected = [current[i % 2] + (box[i] - bounds[i % 2]) * (sx if i % 2 == 0 else sy) for i in range(4)]
                candidates = [v for v in hits[c['id']]['candidates'] if overlap(expected, v['identity_box']) >= 0.8]
                if len(candidates) != 1 or any((overlap(candidates[0]['identity_box'], v) > 0.5 for v in used)):
                    break
                selected[c['id']] = candidates[0]
                used.append(candidates[0]['identity_box'])
            if len(selected) != len(group):
                continue
            evidence = {'scope': 'appearance_and_relative_position_only', 'source_image': source, 'source_group_box': bounds, 'current_group_box': current, 'controls': [c['id'] for c in group], 'score': group_hit['score']}
            for c in group:
                candidate = selected[c['id']]
                result[c['id']] = {**hits[c['id']], **candidate, 'accepted': True, 'candidates': [candidate], 'reason': 'confirmed_group_layout', 'layout_evidence': evidence}
    return result
from copy import deepcopy
from pathlib import Path
from regrow.recognition import identity_templates as templates

def matcher():
    from regrow.recognition import matching as m
    return m

def match_control(control, frame):
    """Recall the admitted appearance in the current full screenshot."""
    if not templates.usable(control):
        return {'accepted': False, 'box': None, 'candidates': [], 'reason': 'identity template not admitted'}
    m = matcher()
    hit = m.locate(control['image'], frame)
    hit = {**hit, 'identity_box': hit.get('box'), 'candidates': [{**v, 'identity_box': v.get('box')} for v in hit.get('candidates', [])]}
    return hit

def match_controls(controls, frame):
    from regrow.recognition import matching as control_layout
    hits = {c['id']: match_control(c, frame) for c in controls if c.get('image') and Path(c['image']).is_file()}
    return control_layout.refine(controls, hits, frame, matcher())

def prepare(request):
    q = deepcopy(request)
    q.pop('visual_choices', None)
    frames = q.get('image_refs', [])
    choices = {}
    if len(frames) != 1 or not frames[0] or (not Path(frames[0]).is_file()):
        return q
    for (cid, hit) in match_controls(q.get('backend_candidates', []), frames[0]).items():
        choices[cid] = [hit] if hit.get('accepted') else hit.get('candidates', [])
    q['visual_choices'] = choices
    return q

def describe(request):
    return [{'控件': c['name'], '视觉描述': c.get('icon_description', ''), '目标观察': c.get('target_observation', {}), '候选位置': [v['box'] for v in request.get('visual_choices', {}).get(c['id'], [])]} for c in request.get('backend_candidates', []) if c['id'] in request.get('visual_choices', {})]
