"""Offline contracts for role-independent visual block grouping.

No VM, network, or real VLM is used.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.region_registry import (
    RegionRegistry,
    assign_elements_to_regions,
)


def _element(index: int, name: str, center, *, interactive: bool):
    x, y = center
    return SimpleNamespace(
        id=index,
        name=name,
        interactive=interactive,
        bbox_xywh=[x - 5, y - 5, 10, 10],
        center=[x, y],
    )


def test_labels_stabilise_identity_but_never_become_buttons() -> None:
    registry = RegionRegistry()
    rid, _ = registry.register(
        "other",
        ["Bluetooth", "Turned Off", "Device"],
        member_tokens=[
            "display:bluetooth", "display:turned off", "action:device"],
        action_names=["Device"],
        bbox=[100, 100, 500, 800],
        container_bbox=[0, 0, 1000, 1000],
        node_id="page_a",
    )
    assert registry.buttons(rid) == {"device"}
    assert registry.unclicked(rid) == {"device"}
    assert "bluetooth" not in registry.buttons(rid)
    assert "turned off" not in registry.buttons(rid)


def test_role_hint_drift_does_not_split_a_geometry_backed_block() -> None:
    registry = RegionRegistry()
    common = dict(
        names=["Network", "Bluetooth", "Sound"],
        member_tokens=[
            "action:network", "action:bluetooth", "action:sound"],
        action_names=["Network", "Bluetooth", "Sound"],
        bbox=[0, 50, 300, 950],
        container_bbox=[0, 0, 1000, 1000],
    )
    first, is_new = registry.register(
        "nav_sidebar", node_id="page_a", **common)
    second, reused = registry.register(
        "other", node_id="page_b", **common)
    assert is_new is True
    assert reused is False
    assert second == first
    assert registry.regions_of("page_b") == {f"region:{first}"}


def test_explicit_membership_beats_overlapping_block_boxes() -> None:
    left = _element(10, "Title", [100, 100], interactive=False)
    right = _element(20, "Open", [300, 100], interactive=True)
    regions = [
        {"role": "other", "bbox": [0, 0, 400, 200], "member_ids": {10}},
        {"role": "other", "bbox": [0, 0, 400, 200], "member_ids": {20}},
    ]
    assigned = assign_elements_to_regions([left, right], regions)
    assert assigned[0] == [left]
    assert assigned[1] == [right]


if __name__ == "__main__":
    test_labels_stabilise_identity_but_never_become_buttons()
    test_role_hint_drift_does_not_split_a_geometry_backed_block()
    test_explicit_membership_beats_overlapping_block_boxes()
    print("ALL PASS")
