"""Offline test: SoM box index <-> element record <-> name <-> clickable <->
click-coordinate stay ONE consistent unit through perception/merge and the
deterministic frontier. No emulator, no YOLO/VLM models.

Reproduces the contacts-home mis-bind and proves it is gone after the fix:

  * BUG (pre-fix): the engine's in-node scroll-aggregate concatenates several
    independently-numbered perception frames, so element ``id``s repeat within
    one node (contacts home had ids 2/5/11 twice).
    A detected bottom-nav tab also carried a shaky OCR ``interactive=False`` and
    was pruned from the BFS frontier entirely.

Asserts:
  1. detect_and_name keeps name/clickable/center bound to the SAME box (the row
     the VLM named "5" gets box-5's center, not another box's).
  2. _renumber_unique gives a scroll-aggregated node a UNIQUE id per element
     (no collisions) in stable reading order.
  3. A navigation element with a shaky ``interactive=False`` flag is NOT
     dropped from the deterministic category-driven frontier.
     because OCR/VLM guessed clickable=False (VLM-first clickability).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2

from gui_rewalk.src.core.visual_traversal.visual_perception import (
    VisualPerception, VisualElement)
from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine)
from gui_rewalk.src.core.visual_traversal.visual_agents import ExplorationMemory


def _png(w=1080, h=1920, val=240):
    return cv2.imencode(".png", np.full((h, w, 3), val, np.uint8))[1].tobytes()


class FakeAgent:
    """Returns a canned JSON string from predict_mm (3-tuple like the real one)."""
    def __init__(self, resp):
        self.resp = resp
        self.last_prompt = None
    def predict_mm(self, prompt, images):
        self.last_prompt = prompt
        return self.resp, None, None


# ── 1. perception merge keeps name/clickable/center on the same box ──────────
def test_merge_binding():
    # three synthetic detected boxes (ratio xyxy), each at a distinct place.
    # box0 top-left, box1 middle, box2 a bottom FAB-like corner.
    boxes = [
        {"type": "icon", "bbox": [0.05, 0.05, 0.20, 0.12], "interactivity": True,
         "content": None, "_score": 0.9},
        {"type": "icon", "bbox": [0.40, 0.40, 0.60, 0.50], "interactivity": True,
         "content": None, "_score": 0.8},
        {"type": "icon", "bbox": [0.80, 0.75, 0.95, 0.85], "interactivity": True,
         "content": None, "_score": 0.95},
    ]
    # VLM names each id; deliberately give box2 (the FAB corner) name "Create"
    # and box0 name "Menu" so a shuffle would be detectable by name<->place.
    vlm = ('{"window":[0,0,1,1],"is_modal":false,"modal":null,"elements":['
           '{"id":0,"name":"Menu","type":"button","category":"navigation","interactive":true},'
           '{"id":1,"name":"Body","type":"text","category":"display","interactive":false},'
           '{"id":2,"name":"Create","type":"button","category":"navigation","interactive":true}]}')

    p = VisualPerception(yolo_model=None, agent=FakeAgent(vlm), use_ocr=False)
    p.detect = lambda image: boxes  # bypass real YOLO/OCR; exercise the merge
    els = p.detect_and_name(_png(), apply_filter=False)

    by_name = {e.name: e for e in els}
    assert set(by_name) == {"Menu", "Body", "Create"}, [e.name for e in els]
    # "Create" must carry the FAB corner's center (box2), NOT another box.
    create = by_name["Create"]
    assert create.center[0] > 800 and create.center[1] > 1400, create.center
    # "Menu" must carry the top-left center (box0).
    menu = by_name["Menu"]
    assert menu.center[0] < 250 and menu.center[1] < 250, menu.center
    # clickable flags ride with their own box's VLM verdict.
    assert create.interactive is True and menu.interactive is True
    assert by_name["Body"].interactive is False
    print("[1] merge: each name/clickable/center stays bound to its own box")


# ── 2. _renumber_unique fixes duplicate ids from scroll-aggregate ───────────
def _agg_node_like_contacts():
    """Build an element list shaped like the contacts-home node AFTER scroll-
    aggregate: a top frame (ids 0..3) concatenated with a scrolled frame that
    was independently numbered 0.. again -> COLLIDING ids."""
    def el(eid, name, cx, cy, interactive=True, ss=0):
        return VisualElement(id=eid, name=name, bbox_xywh=[cx - 20, cy - 20, 40, 40],
                             center=[cx, cy], interactive=interactive,
                             category="navigation", scroll_steps=ss)
    return [
        el(0, "Search", 332, 147),
        el(1, "Highlights", 944, 1535),      # the FAB box, mis-NAMED (as observed)
        el(2, "Contacts", 180, 1755),
        el(3, "Fix & manage", 890, 1771, interactive=False),  # tab, OCR Falsed it
        # second (scrolled) frame, numbered from 0 again -> collisions:
        el(1, "Email contacts", 651, 298, ss=1),   # id collides with FAB's id=1
        el(2, "Phone contacts", 203, 297, ss=1),   # id collides with Contacts id=2
    ]


def test_renumber_unique():
    els = _agg_node_like_contacts()
    ids_before = [e.id for e in els]
    assert len(set(ids_before)) < len(els), "fixture must have colliding ids"
    VisualTraversalEngine._renumber_unique(els)
    ids_after = [e.id for e in els]
    assert sorted(ids_after) == list(range(len(els))), ids_after
    assert len(set(ids_after)) == len(els), "ids must be unique after renumber"
    # renumber must NOT touch name/center/clickable — only the id key.
    fab = next(e for e in els if e.name == "Highlights")
    assert fab.center == [944, 1535] and fab.interactive is True
    print(f"[2] renumber: colliding ids {ids_before} -> unique {ids_after}, "
          "binding untouched")


def test_false_clickable_not_pruned():
    els = _agg_node_like_contacts()
    VisualTraversalEngine._renumber_unique(els)
    # assign uids (the engine dedups on uid); just give each a distinct one.
    for i, e in enumerate(els):
        e.uid = f"uid{i}"
        e.visited = False
    engine = object.__new__(VisualTraversalEngine)
    engine._state_data = {"S": {"elements": els}}
    engine._visited_uids = set()
    engine._explored_groups = set()
    engine._abnormal_buttons = set()
    engine.mem = ExplorationMemory()
    engine.review_debug = type(
        "NoDebug", (), {"enabled": False, "record_event": lambda *_a, **_k: None}
    )()
    engine.region_registry = type("NoRegions", (), {})()
    engine.router = type(
        "NoRoutes", (), {"has_direct_edge": lambda *_a, **_k: False}
    )()

    cands = engine._unvisited_candidates("S")
    names = {e.name for e in cands}
    # "Fix & manage" is interactive=False (OCR-Falsed bottom-nav tab) but is a
    # genuinely-detected, named control -> must still reach the frontier.
    assert "Fix & manage" in names, names
    fix = next(e for e in cands if e.name == "Fix & manage")
    assert fix.interactive is False, "fixture: this is the OCR-Falsed tab"
    print("[3] navigation box with interactive=False NOT pruned "
          "('Fix & manage' survives to the deterministic frontier)")


def main():
    test_merge_binding()
    test_renumber_unique()
    test_false_clickable_not_pruned()
    print("ALL PASS — box index <-> record <-> name <-> clickable <-> coordinate "
          "stay one consistent unit; a detected navigation tab is not pruned by "
          "a noisy interactive flag.")


if __name__ == "__main__":
    main()
