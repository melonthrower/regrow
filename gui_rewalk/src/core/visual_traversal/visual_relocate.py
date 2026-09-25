"""Fast, a11y-free element RE-LOCATION by OpenCV template matching.

Pairs with PageIdentityJudge (which answers "did I get back to this page?") to
answer the other half — "WHERE is the button I need to click, on the screen
right now?" — without re-running the slow VLM/YOLO perception or replaying
fragile fixed coordinates.

On first visit we already have each element's bbox; we crop its appearance and
keep it. On revisit/backtrack we ``cv2.matchTemplate`` that crop into the current
screenshot to find its current pixel position, then click there. Validated on
the dark Settings list: 14/14 self-relocate (0px), 11/11 ACROSS a relaunch
(score ~1.0), and clean separation from a different page (real buttons scored
0.25-0.64 there) — so a 0.8 threshold reliably tells "present" from "absent".
~80ms per match vs seconds for the VLM, so it is the fast path; the VLM stays as
the fallback when the score is below threshold.

Guardrails (learned from the prototype):
  * skip tiny crops and the status-bar band (clock/battery match everywhere);
  * a generic/near-uniform crop (low variance) is rejected — it false-matches;
  * below-the-fold targets must be scrolled into view first (caller's job).
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Match score (TM_CCOEFF_NORMED, -1..1) at/above which we trust the relocation.
MATCH_THRESHOLD = 0.80
# Ignore the top status-bar band (clock/battery/icons change & match anywhere).
STATUS_BAR_FRAC = 0.06
# A crop smaller than this (px) or flatter than this (pixel std) is unreliable.
MIN_CROP_PX = 10
MIN_CROP_STD = 12.0
REGION_MIN_INLIERS = 18
REGION_MIN_INLIER_RATIO = 0.28
UNIQUE_MATCH_MARGIN = 0.08


def _bgr(shot) -> Optional["np.ndarray"]:
    """Accept PNG bytes / path / ndarray → BGR uint8 ndarray for cv2."""
    import cv2
    if isinstance(shot, np.ndarray):
        return shot if shot.ndim == 3 else cv2.cvtColor(shot, cv2.COLOR_GRAY2BGR)
    if isinstance(shot, (bytes, bytearray)):
        arr = cv2.imdecode(np.frombuffer(bytes(shot), np.uint8), cv2.IMREAD_COLOR)
        return arr
    if isinstance(shot, str):
        return cv2.imread(shot)
    return None


def is_reliable_template(crop: "np.ndarray", scene_h: int, top_y: int) -> bool:
    """Reject templates that would false-match (status bar / blank / generic)."""
    if crop is None or crop.size == 0:
        return False
    h, w = crop.shape[:2]
    if h < MIN_CROP_PX or w < MIN_CROP_PX:
        return False
    if top_y < scene_h * STATUS_BAR_FRAC:          # inside the status-bar band
        return False
    if float(crop.std()) < MIN_CROP_STD:           # near-uniform → matches anywhere
        return False
    return True


def relocate(template, scene, threshold: float = MATCH_THRESHOLD
             ) -> Optional[Tuple[int, int, float]]:
    """Find ``template`` in ``scene``. Return (center_x, center_y, score) if the
    best match scores >= threshold, else None. Inputs may be ndarray/bytes/path.
    """
    import cv2
    t = _bgr(template); s = _bgr(scene)
    if t is None or s is None:
        return None
    th, tw = t.shape[:2]; sh, sw = s.shape[:2]
    if th >= sh or tw >= sw or th < 1 or tw < 1:
        return None
    try:
        res = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
    except Exception as e:
        logger.debug("template match failed: %s", e)
        return None
    if maxv < threshold:
        return None
    return maxl[0] + tw // 2, maxl[1] + th // 2, float(maxv)


def crop_element(screenshot, bbox_xywh: List[int]) -> Optional["np.ndarray"]:
    """Crop an element's appearance from a screenshot (for later relocation)."""
    s = _bgr(screenshot)
    if s is None:
        return None
    x, y, w, h = [int(v) for v in bbox_xywh[:4]]
    sh, sw = s.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(sw, x + w), min(sh, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return s[y0:y1, x0:x1].copy()


def save_template(screenshot, bbox_xywh: List[int]) -> Optional["np.ndarray"]:
    """Crop an element AND keep it only if it is a reliable template."""
    s = _bgr(screenshot)
    if s is None:
        return None
    crop = crop_element(s, bbox_xywh)
    if crop is None:
        return None
    if not is_reliable_template(crop, s.shape[0], int(bbox_xywh[1])):
        return None
    return crop


def crop_region(screenshot, bbox_xyxy: List[int]) -> Optional["np.ndarray"]:
    """Crop an x0/y0/x1/y1 region from a screenshot."""
    s = _bgr(screenshot)
    if s is None or not bbox_xyxy or len(bbox_xyxy) != 4:
        return None
    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox_xyxy]
    except (TypeError, ValueError):
        return None
    sh, sw = s.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(sw, x1), min(sh, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return s[y0:y1, x0:x1].copy()


def save_context_template(
    screenshot,
    bbox_xywh: List[int],
    region_bbox_xyxy: Optional[List[int]] = None,
) -> Optional[Tuple["np.ndarray", Tuple[int, int]]]:
    """Save an element with row/local context and its centre offset."""
    s = _bgr(screenshot)
    if s is None or not bbox_xywh or len(bbox_xywh) != 4:
        return None
    try:
        x, y, w, h = [int(round(float(v))) for v in bbox_xywh]
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    sh, sw = s.shape[:2]
    left, top, right, bottom = 0, 0, sw, sh
    if region_bbox_xyxy and len(region_bbox_xyxy) == 4:
        try:
            left, top, right, bottom = [
                int(round(float(v))) for v in region_bbox_xyxy]
        except (TypeError, ValueError):
            return None
        left, top = max(0, left), max(0, top)
        right, bottom = min(sw, right), min(sh, bottom)
    pad_x = max(120, 5 * w)
    pad_y = max(18, h)
    x0, y0 = max(left, x - pad_x), max(top, y - pad_y)
    x1, y1 = min(right, x + w + pad_x), min(bottom, y + h + pad_y)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = s[y0:y1, x0:x1].copy()
    # The context may be clipped up to an app-region edge near the status bar;
    # judge the actual element top, not the padded context top.
    if not is_reliable_template(crop, sh, y):
        return None
    return crop, (x + w // 2 - x0, y + h // 2 - y0)


def _width_normalize(image: "np.ndarray", width: int) -> "np.ndarray":
    import cv2
    if image.shape[1] == width:
        return image.copy()
    scale = width / float(image.shape[1])
    height = max(1, int(round(image.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(image, (width, height), interpolation=interpolation)


def match_region_view(candidate, stored_map) -> Dict[str, Any]:
    """Confirm a current region viewport against a stored (possibly tall) map."""
    import cv2
    c = _bgr(candidate)
    m = _bgr(stored_map)
    rejected: Dict[str, Any] = {"accepted": False, "method": "region_orb"}
    if c is None or m is None or min(c.shape[:2] + m.shape[:2]) < 12:
        return rejected
    if float(c.std()) < MIN_CROP_STD or float(m.std()) < MIN_CROP_STD:
        return rejected
    c = _width_normalize(c, m.shape[1])
    cgray = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    mgray = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=2500, fastThreshold=12)
    ckp, cdesc = orb.detectAndCompute(cgray, None)
    mkp, mdesc = orb.detectAndCompute(mgray, None)
    if cdesc is not None and mdesc is not None and len(ckp) >= 8 and len(mkp) >= 8:
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(cdesc, mdesc, k=2)
        good = [a for a, b in pairs if a.distance < 0.76 * b.distance]
        if len(good) >= 8:
            src = np.float32([ckp[x.queryIdx].pt for x in good]).reshape(-1, 1, 2)
            dst = np.float32([mkp[x.trainIdx].pt for x in good]).reshape(-1, 1, 2)
            matrix, mask = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0,
                maxIters=3000, confidence=0.995)
            inliers = int(mask.sum()) if mask is not None else 0
            ratio = inliers / max(1, len(good))
            if matrix is not None:
                scale = float(np.hypot(matrix[0, 0], matrix[0, 1]))
                rotation = float(np.degrees(np.arctan2(matrix[0, 1], matrix[0, 0])))
                accepted = bool(
                    inliers >= REGION_MIN_INLIERS
                    and ratio >= REGION_MIN_INLIER_RATIO
                    and 0.94 <= scale <= 1.06
                    and abs(rotation) <= 2.0)
                evidence = {
                    "accepted": accepted, "method": "region_orb",
                    "matches": len(good), "inliers": inliers,
                    "inlier_ratio": ratio, "scale": scale,
                    "rotation": rotation,
                    "offset_y": float(matrix[1, 2]),
                }
                if accepted:
                    return evidence
                rejected.update(evidence)
    if c.shape[0] <= m.shape[0] and c.shape[1] <= m.shape[1]:
        ce = cv2.Canny(cgray, 60, 160)
        me = cv2.Canny(mgray, 60, 160)
        if float(ce.std()) >= 4.0:
            response = cv2.matchTemplate(me, ce, cv2.TM_CCOEFF_NORMED)
            _mn, score, _ml, loc = cv2.minMaxLoc(response)
            if score >= 0.82:
                return {"accepted": True, "method": "region_edge",
                        "score": float(score), "offset_y": float(loc[1])}
            rejected.update({"edge_score": float(score)})
    return rejected


def relocate_unique(
    template, scene, *, threshold: float = 0.72,
    margin: float = UNIQUE_MATCH_MARGIN,
) -> Optional[Tuple[int, int, float, float]]:
    """Relocate only when the best peak is distinct from another occurrence."""
    import cv2
    t = _bgr(template)
    s = _bgr(scene)
    if t is None or s is None:
        return None
    th, tw = t.shape[:2]
    if th >= s.shape[0] or tw >= s.shape[1]:
        return None
    try:
        response = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
        _mn, best, _ml, loc = cv2.minMaxLoc(response)
        masked = response.copy()
        x, y = loc
        masked[max(0, y - th):min(masked.shape[0], y + th + 1),
               max(0, x - tw):min(masked.shape[1], x + tw + 1)] = -1.0
        second = float(cv2.minMaxLoc(masked)[1]) if masked.size else -1.0
    except Exception as exc:
        logger.debug("unique template match failed: %s", exc)
        return None
    separation = float(best) - second
    if best < threshold or separation < margin:
        return None
    return loc[0], loc[1], float(best), separation
