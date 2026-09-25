"""Offline regression for conservative modal active-surface filtering."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import MethodType

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.visual_perception import (  # noqa: E402
    VisualElement,
    VisualPerception,
    _bbox_sufficiently_inside_surface,
)


MODAL = [100, 100, 400, 300]


def _element(name: str, bbox: list[int]) -> VisualElement:
    x, y, w, h = bbox
    return VisualElement(
        id=0,
        name=name,
        bbox_xywh=list(bbox),
        center=[x + w // 2, y + h // 2],
        category="navigation",
    )


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 500), "white").save(buf, format="PNG")
    return buf.getvalue()


def _perception(elements, surface=MODAL) -> VisualPerception:
    perception = VisualPerception(yolo_model=None, agent=None)
    perception.use_vlm_grounding = True

    def fake_ground(self, image, image_np, _w, _h, force_refresh=False):
        del force_refresh
        self.last_is_modal = True
        self.last_window_xywh = list(surface) if surface is not None else None
        self.last_som_image = np.asarray(image)
        return list(elements)

    perception._ground_with_vlm = MethodType(fake_ground, perception)
    return perception


def main() -> int:
    inside = _element("Inside", [150, 150, 80, 40])
    slight_jitter = _element("Slight jitter", [90, 230, 100, 40])  # 90% inside
    # Its center (125, 180) is inside the modal, but only 60% of the box is.
    # This is the exact background-leak shape a center-only check accepts.
    center_only_leak = _element("Background sidebar", [0, 160, 250, 40])
    outside = _element("Inactive page", [10, 260, 60, 40])

    assert _bbox_sufficiently_inside_surface(inside.bbox_xywh, MODAL)
    assert _bbox_sufficiently_inside_surface(slight_jitter.bbox_xywh, MODAL)
    assert not _bbox_sufficiently_inside_surface(
        center_only_leak.bbox_xywh, MODAL)
    assert not _bbox_sufficiently_inside_surface(outside.bbox_xywh, MODAL)

    perception = _perception(
        [inside, slight_jitter, center_only_leak, outside])
    kept = perception.detect_and_name(_png_bytes())
    assert [e.name for e in kept] == ["Inside", "Slight jitter"]
    assert [e.name for e in perception.last_all_elements] == [
        "Inside", "Slight jitter"
    ], "inactive background must not pollute modal function identity"

    # A modal label without trustworthy active-surface geometry fails closed.
    unknown_surface = _perception([inside], surface=None)
    assert unknown_surface.detect_and_name(_png_bytes()) == []
    assert unknown_surface.last_all_elements == []

    print("PASS modal filtering requires bbox coverage of the active surface")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
