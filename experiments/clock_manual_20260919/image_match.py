"""Conservative original-size pixel localization shared by the stepwise flow.

A match is spatial evidence, not proof of control identity or action success.
Coordinates remain transient; callers keep identity crops and click areas separate.
"""
import cv2
import numpy as np
from PIL import Image

MIN_SCORE = .90
MIN_GAP = .05
MAX_CANDIDATES = 32


def _search(template, scene, scene_gray=None):
    """Recall strong spatial candidates; accept only a clearly unique one."""
    template_gray = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
    if template_gray.std() < 1:
        return {'accepted': False, 'candidates': [], 'reason': 'uninformative_template'}
    if scene_gray is None:
        scene_gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
    height, width = template_gray.shape
    if height > scene_gray.shape[0] or width > scene_gray.shape[1]:
        return {'accepted': False, 'candidates': [], 'reason': 'template_outside_surface'}

    scores = cv2.matchTemplate(scene_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    peaks = []
    truncated = False
    for peak in range(MAX_CANDIDATES):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score <= -1 or (peak >= 2 and score < MIN_SCORE):
            break
        # Keep the spatial runner-up even below MIN_SCORE: .92 versus .89
        # is not unique merely because only .92 is a disclosed candidate.
        peaks.append({'score': float(score), 'box': [x, y, x + width, y + height], 'scale': 1})
        scores[max(0, y - height // 2):y + height // 2 + 1,
               max(0, x - width // 2):x + width // 2 + 1] = -1
    else:
        truncated = cv2.minMaxLoc(scores)[1] >= MIN_SCORE

    if not peaks:
        return {'accepted': False, 'candidates': [], 'reason': 'no_pixel_candidate'}
    best = peaks[0]
    gap = best['score'] - (peaks[1]['score'] if len(peaks) > 1 else 0)
    candidates = [p for p in peaks if p['score'] >= MIN_SCORE]
    accepted = bool(candidates) and not truncated and gap >= MIN_GAP
    return dict(best, gap=gap, accepted=accepted, candidates=candidates,
                candidates_truncated=truncated,
                reason='matched' if accepted else 'ambiguous_or_changed')


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
