import cv2
import numpy as np

from gui_rewalk.src.core.visual_traversal import visual_relocate as reloc
from gui_rewalk.src.core.visual_traversal.live_targeting import region_context_prior
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _long_region(seed=7):
    rng = np.random.default_rng(seed)
    image = np.full((1400, 520, 3), 238, dtype=np.uint8)
    for row in range(24):
        y = 30 + row * 55
        color = tuple(int(v) for v in rng.integers(35, 190, size=3))
        cv2.circle(image, (35, y), 12, color, 2)
        cv2.putText(image, f"setting row {row:02d}", (65, y + 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        cv2.line(image, (15, y + 25), (500, y + 25), (205, 205, 205), 1)
        if row == 10:
            cv2.fillPoly(image, [np.array([[430, y - 16], [470, y],
                                           [430, y + 16]])], (20, 80, 210))
    return image


def test_scrolled_view_matches_tall_region_and_rejects_other_region():
    stored = _long_region(7)
    live = stored[330:1030].copy()
    hit = reloc.match_region_view(live, stored)
    assert hit["accepted"] is True
    assert hit["inliers"] >= reloc.REGION_MIN_INLIERS
    assert abs(hit["offset_y"] - 330) < 8

    other = np.full((700, 520, 3), 238, dtype=np.uint8)
    for x in range(20, 500, 45):
        cv2.line(other, (x, 20), (x, 680), (30, 70, 180), 3)
    miss = reloc.match_region_view(other, stored)
    assert miss["accepted"] is False


def test_repeated_small_control_fails_uniqueness_but_row_context_passes():
    scene = np.full((420, 760, 3), 245, dtype=np.uint8)
    for idx, label in enumerate(("Alpha archive", "Beta archive", "Zoo archive")):
        y = 55 + idx * 120
        cv2.putText(scene, label, (45, y + 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (30, 30, 30), 2, cv2.LINE_AA)
        cv2.rectangle(scene, (590, y), (700, y + 44), (80, 80, 80), 2)
        cv2.putText(scene, "Unset", (605, y + 29), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (40, 40, 40), 2, cv2.LINE_AA)

    bare = scene[55:99, 590:700].copy()
    context = scene[285:339, 35:705].copy()
    assert reloc.relocate_unique(bare, scene) is None
    assert reloc.relocate_unique(context, scene) is not None


def test_app_context_touching_status_band_is_kept_when_element_is_below_it():
    scene = _long_region(7)[:700]
    saved = reloc.save_context_template(
        scene, [70, 70, 180, 32], [0, 52, 520, 700])
    assert saved is not None


def test_region_context_prior_moves_expected_geometry_without_authorizing_click():
    stored = _long_region(7)
    live = stored[330:1030].copy()
    element = VisualElement(
        id=1, name="setting row 10", bbox_xywh=[250, 575, 150, 34],
        center=[325, 592],
    )
    element.region_bbox = [0, 0, 520, 700]
    element._region_map = stored
    # Row 10 is y=580 in the map, therefore y=250 in this live viewport.
    element._context_template = stored[550:610, 15:505].copy()
    element._context_center_offset = (310, 30)

    prior, evidence = region_context_prior(element, live)
    assert evidence["accepted"] is True
    assert prior is not element
    assert abs(prior.center[1] - 250) < 8
    # The original ledger geometry is untouched; current VLM grounding still
    # has to select and review the actual click target.
    assert element.center == [325, 592]
