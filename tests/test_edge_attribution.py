"""State-identity preconditions for safe visual edge attribution.

The historical edge corruption happened when two sibling tabs had high SSIM but
different semantic content.  The current runtime protects the edge source with
``VisualStateRegistry.identify``.  This file keeps the synthetic sibling-tab
fixture and verifies the registry side of that contract without VM, A11y or VLM.
"""

from __future__ import annotations

import os
import sys
import tempfile

import cv2
import imagehash
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.graph.state_graph import StateGraph
from gui_rewalk.src.core.reverse.image_ssim_calculator import get_image_ssim
from gui_rewalk.src.core.visual_traversal.visual_state import VisualStateRegistry


W, H = 300, 600


def _tab(glyph_xy, data_seed=None):
    """Mostly shared chrome plus one small page-specific content block."""
    image = np.full((H, W, 3), 18, np.uint8)
    image[0:40] = 30
    image[H - 60:H] = 28
    for index in range(5):
        cv2.circle(image, (30 + index * 55, H - 30), 10, (80, 80, 80), -1)
    x, y = glyph_xy
    cv2.rectangle(image, (x, y), (x + 70, y + 90), (160, 160, 160), -1)
    if data_seed is not None:
        patch = np.random.RandomState(data_seed).rand(20, 55, 3) * 80 + 90
        image[y + 5:y + 25, x + 5:x + 60] = patch.astype(np.uint8)
    return image


def _buf(image):
    return cv2.imencode(".png", image)[1].tobytes()


def _save(image):
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.write(_buf(image))
    handle.close()
    return handle.name


ALARM = _tab((60, 150))
TIMER = _tab((170, 330))
ALARM_DRIFT = _tab((60, 150), data_seed=9)
_tmp_files = []


def _persist(image):
    path = _save(image)
    _tmp_files.append(path)
    return path


def _cleanup():
    for path in _tmp_files:
        try:
            os.unlink(path)
        except OSError:
            pass


def _phash(image):
    return imagehash.hex_to_hash(StateGraph.compute_visual_state_id(_buf(image)))


def test_world_reproduces_failure_shape():
    alarm_path = _persist(ALARM)
    timer_path = _persist(TIMER)
    drift_path = _persist(ALARM_DRIFT)
    sibling_ssim = get_image_ssim(alarm_path, timer_path)
    same_ssim = get_image_ssim(alarm_path, drift_path)
    sibling_distance = _phash(ALARM) - _phash(TIMER)
    same_distance = _phash(ALARM) - _phash(ALARM_DRIFT)
    threshold = VisualStateRegistry().phash_threshold

    print(
        f"[world] sibling SSIM={sibling_ssim:.3f} pHash={sibling_distance} | "
        f"same SSIM={same_ssim:.3f} pHash={same_distance}"
    )
    assert sibling_ssim >= 0.85
    assert sibling_distance > threshold
    assert same_ssim >= 0.85
    assert same_distance <= threshold


def test_registry_identify_uses_strict_frame_hash_not_near_phash():
    registry = VisualStateRegistry()
    alarm_id, is_new = registry.register(
        _buf(ALARM), _persist(ALARM), judge=None
    )
    assert is_new and alarm_id
    assert registry.identify(_buf(ALARM), _persist(ALARM)) == alarm_id
    assert registry.identify(
        _buf(ALARM_DRIFT), _persist(ALARM_DRIFT)
    ) is None
    assert registry.identify(_buf(TIMER), _persist(TIMER)) is None
    assert len(registry._states) == 1, "identify must not mint a state"


def main():
    try:
        test_world_reproduces_failure_shape()
        test_registry_identify_uses_strict_frame_hash_not_near_phash()
        print("ALL PASS - sibling tabs remain distinct and identify is read-only")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
