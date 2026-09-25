"""Offline synthetic unit test for visual_stitch.stitch_frames.

Builds a tall synthetic "page": a fixed top app-bar, a fixed bottom nav-bar, and
a CONTENT band of N distinct horizontal rows (each row a unique solid colour with
a unique marker). Renders M overlapping viewport crops as if the page were
scrolled top→bottom (sticky bars re-pasted on every crop, content slid up by a
varying per-step amount to mimic non-deterministic fling). Feeds the crops to the
stitcher and asserts:

  1. the composite reconstructs the full page height within tolerance;
  2. EVERY unique content row appears exactly once (no overlap duplication);
  3. the sticky top + bottom bars appear exactly once (not M times);
  4. the composite-y -> (scroll_step, viewport-y) map round-trips: the frame it
     names really does contain that row at the y it names.

No VM, no model, no network — pure numpy. Run:
    PYTHONPATH=.:OSWorld python tests/test_visual_stitch.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui_rewalk.src.core.visual_traversal import visual_stitch as vs
from gui_rewalk.src.core.visual_traversal.grounding.scroll import (
    REGION_SCROLL_SAFETY_MAX_STEPS,
    ScrollContext,
    ScrollRuntime,
    _crop_normalized_region,
    _expanded_physical_scroll_bbox,
    _inferred_inner_scroll_bbox,
    _region_scroll_fraction,
    _region_scroll_max_steps,
    _stitch_semantic_region_frames,
    _trim_physical_scroll_composite,
)


def _png_bytes(array: np.ndarray) -> bytes:
    import io
    output = io.BytesIO()
    Image.fromarray(array.astype(np.uint8)).save(output, format="PNG")
    return output.getvalue()


def _rgb(payload: bytes) -> np.ndarray:
    import io
    return np.asarray(Image.open(io.BytesIO(payload)).convert("RGB"))


def test_region_scroll_uses_local_stride_but_boundary_driven_safety_budget():
    compact_region = [0, 108, 1000, 545]

    assert round(_region_scroll_fraction(compact_region), 5) == 0.18354
    assert _region_scroll_max_steps(compact_region) == (
        REGION_SCROLL_SAFETY_MAX_STEPS)
    assert _region_scroll_max_steps([0, 0, 1000, 1000]) == (
        REGION_SCROLL_SAFETY_MAX_STEPS)


def test_boundary_driven_region_scroll_can_exceed_legacy_distance_budget():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    height, width, step = 100, 120, 10
    content_h = height + 22 * step
    rng = np.random.default_rng(23)
    content = rng.integers(0, 255, (content_h, width, 3), dtype=np.uint8)

    def frame(offset):
        return _png_bytes(content[offset:offset + height])

    class Env:
        provider_name = "test_touch"
        def __init__(self):
            self.offset = 0
        def step(self, action, pause=0):
            del pause
            if action["action_type"] == "WAIT":
                return {"screenshot": frame(self.offset)}
            if action["parameters"]["direction"] == "down":
                self.offset = min(content_h - height, self.offset + step)
            else:
                self.offset = max(0, self.offset - step)
            return {"screenshot": frame(self.offset)}

    class FrameHash:
        def __init__(self, payload):
            self.payload = payload
        def __sub__(self, other):
            return 0 if self.payload == other.payload else 64

    evidence = []
    long_inventory_calls = []
    shot0 = frame(0)
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_surface_scrollable=True,
        last_semantic_blocks=[{
            "local_id": "b0", "region_id": "r1", "role": "long_list",
            "scrollable": True, "element_names": ["First row"],
        }],
        inventory_scrollable_region=lambda image, block, region_id: (
            long_inventory_calls.append((image, block, region_id)) or []),
        last_region_long_inventory={"status": "ok"},
    )
    runtime = ScrollRuntime(ScrollContext(
        env=Env(), perception=perception, focus_guard=None,
        page_judge=None, block_identity_judge=None,
        region_registry=object(), writer=object(), state_data={},
        pending_transition=None, is_touch=True, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={"r1": shot0},
        semantic_scroll_seed_region_bboxes={"r1": [0, 0, 1000, 1000]},
        frame_phash=lambda payload: FrameHash(payload),
        screen_wh=lambda _obs: (width, height),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    visible = VisualElement(
        0, "First row", [0, 0, 0, 0], [0, 0],
        region_id="r1", geometry_status="semantic_only")

    runtime._scroll_aggregate(
        {"screenshot": shot0}, [visible], state_id="state")

    assert evidence[-1]["termination"] == "viewport_stable"
    assert evidence[-1]["steps"] > 14
    assert evidence[-1]["bottom_reached"] is True
    assert evidence[-1]["top_restored"] is True
    assert runtime.env.offset == 0
    assert len(long_inventory_calls) == 1
    assert long_inventory_calls[0][1]["_viewport_height_px"] == height


def test_semantic_region_map_stitches_only_the_scrollable_crop():
    """A full-width stitch must not supply pixels to a Region long map."""
    crop0 = np.full((80, 100, 3), (245, 245, 245), dtype=np.uint8)
    crop0[:40] = (60, 90, 180)
    crop0[40:] = (80, 130, 90)
    crop1 = np.full((80, 100, 3), (245, 245, 245), dtype=np.uint8)
    crop1[:40] = (80, 130, 90)
    crop1[40:] = (190, 90, 70)
    selected = _stitch_semantic_region_frames(
        frames_by_region={
            "r_scroll": [_png_bytes(crop0), _png_bytes(crop1)],
        },
        shifts_by_region={"r_scroll": [0, 40]},
    )

    scroll_map = _rgb(selected["r_scroll"])
    assert scroll_map.shape == (120, 100, 3)
    assert np.all(scroll_map[:40] == (60, 90, 180))
    assert np.all(scroll_map[40:80] == (80, 130, 90))
    assert np.all(scroll_map[80:] == (190, 90, 70))


def test_collapsing_header_expands_physical_viewport_then_trims_to_region():
    rng = np.random.default_rng(7)
    content = rng.integers(0, 255, (180, 100, 3), dtype=np.uint8)
    before = content[0:100]
    after = content[60:160]
    semantic_bbox = [0, 500, 1000, 1000]
    region_bboxes = {
        "r_header": [0, 0, 1000, 500],
        "r_list": semantic_bbox,
    }

    physical_bbox = _expanded_physical_scroll_bbox(
        semantic_bbox, region_bboxes)
    lower_before = before[50:]
    lower_after = after[50:]
    lower_shift, lower_score = vs.estimate_shift(
        lower_before, lower_after, 0, 0)
    physical_shift, physical_score = vs.estimate_shift(
        before, after, 0, 0)

    assert physical_bbox == [0, 0, 1000, 1000]
    assert lower_shift < vs.MIN_SHIFT_PX or lower_score < vs.SHIFT_MATCH_MIN
    assert physical_shift == 60
    assert physical_score >= vs.SHIFT_MATCH_MIN

    composite = _stitch_semantic_region_frames(
        {"r_list": [_png_bytes(before), _png_bytes(after)]},
        {"r_list": [0, physical_shift]},
    )["r_list"]
    trimmed = _rgb(_trim_physical_scroll_composite(
        composite, physical_bbox, semantic_bbox,
        viewport_height_px=before.shape[0]))

    assert trimmed.shape == (110, 100, 3)
    assert np.array_equal(trimmed[0], content[50])
    assert np.array_equal(trimmed[-1], content[159])


def test_fixed_form_footer_infers_inner_scroll_viewport():
    """A pinned action footer must not hide coherent motion or enter the map."""
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    height, width = 180, 120
    top_h, bottom_h = 20, 45
    viewport_h = height - top_h - bottom_h
    content_h, step = 330, 45
    rng = np.random.default_rng(17)
    content = rng.integers(0, 255, (content_h, width, 3), dtype=np.uint8)
    header_color = np.asarray((31, 47, 63), dtype=np.uint8)
    footer_color = np.asarray((211, 219, 227), dtype=np.uint8)

    def frame(offset):
        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:top_h] = header_color
        image[top_h:height - bottom_h] = (
            content[offset:offset + viewport_h])
        image[height - bottom_h:] = footer_color
        return _png_bytes(image)

    before = _rgb(frame(0))
    after = _rgb(frame(step))
    inferred = _inferred_inner_scroll_bbox(
        before, after, [0, 0, 1000, 1000])
    assert inferred == [0, 111, 1000, 750]

    class Env:
        provider_name = "test_touch"
        def __init__(self):
            self.offset = 0
        def step(self, action, pause=0):
            del pause
            if action["action_type"] == "WAIT":
                return {"screenshot": frame(self.offset)}
            if action["parameters"]["direction"] == "down":
                self.offset = min(
                    content_h - viewport_h, self.offset + step)
            else:
                self.offset = max(0, self.offset - step)
            return {"screenshot": frame(self.offset)}

    class FrameHash:
        def __init__(self, payload):
            self.payload = payload
        def __sub__(self, other):
            return 0 if self.payload == other.payload else 64

    long_inventory_calls = []
    evidence = []
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_surface_scrollable=True,
        last_semantic_blocks=[{
            "local_id": "b0", "region_id": "r1", "role": "form",
            "scrollable": True, "element_names": ["Visible field"],
        }],
        inventory_scrollable_region=lambda image, block, region_id: (
            long_inventory_calls.append((image, block, region_id)) or [
                VisualElement(
                    1, "Below-fold field", [0, 0, 0, 0], [0, 0],
                    region_id=region_id, geometry_status="semantic_only")
            ]),
        last_region_long_inventory={"status": "ok"},
    )
    shot0 = frame(0)
    runtime = ScrollRuntime(ScrollContext(
        env=Env(), perception=perception, focus_guard=None,
        page_judge=None, block_identity_judge=None,
        region_registry=object(), writer=object(), state_data={},
        pending_transition=None, is_touch=True, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={"r1": shot0},
        semantic_scroll_seed_region_bboxes={"r1": [0, 0, 1000, 1000]},
        frame_phash=lambda payload: FrameHash(payload),
        screen_wh=lambda _obs: (width, height),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    visible = VisualElement(
        0, "Visible field", [0, 0, 0, 0], [0, 0],
        region_id="r1", group="repeated_item",
        geometry_status="semantic_only")
    result = runtime._scroll_aggregate(
        {"screenshot": shot0}, [visible], state_id="state")

    assert [element.name for element in result] == [
        "Visible field", "Below-fold field"]
    assert len(long_inventory_calls) == 1
    assert long_inventory_calls[0][1]["known_groups"] == [{
        "group": "repeated_item", "examples": ["Visible field"],
    }]
    composite = _rgb(runtime._state_data["state"][
        "_semantic_scroll_region_crops"]["r1"])
    assert composite.shape[0] >= content_h
    assert not np.any(np.all(composite == footer_color, axis=2))
    assert evidence[-1]["classification"] == "scrollable"
    assert evidence[-1]["termination"] == "viewport_stable"
    assert evidence[-1]["top_restored"] is True

    runtime.env.offset = 3 * step
    restored, _observation = runtime._restore_semantic_region_to_top(
        {"screenshot": frame(runtime.env.offset)},
        [0, 0, 1000, 1000],
        {"action_type": "SCROLL", "parameters": {"direction": "up"}},
        minimum_swipes=0, max_swipes=10)
    assert restored is True
    assert runtime.env.offset == 0


def test_incomplete_scroll_retry_rebinds_local_blocks_to_stable_regions():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        retry_semantic_scroll_audit,
    )
    from gui_rewalk.src.core.visual_traversal.visual_perception import (
        VisualElement,
    )

    screenshot = _png_bytes(np.full((100, 100, 3), 220, dtype=np.uint8))
    # A later VLM partition may merge previously separate Regions. Retry must
    # ignore it and reuse the durable State geometry.
    live_blocks = [{
        "local_id": "b0", "bbox_1000": [0, 0, 1000, 1000],
        "element_ids": ["0", "1"], "scrollable": True,
    }]
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_semantic_blocks=live_blocks,
    )
    captured = {}
    host = SimpleNamespace(
        env=SimpleNamespace(step=lambda action, pause=0: {
            "screenshot": screenshot}),
        perception=perception,
        _scroll_aggregate_enabled=True,
        _last_live_observation_elements=[
            VisualElement(0, "Header", [0, 0, 0, 0], [0, 0]),
            VisualElement(1, "List row", [0, 0, 0, 0], [0, 0]),
        ],
        _state_data={"state": {"semantic_blocks": [
            {"region_id": "r16", "element_names": ["Header"],
             "scrollable": False,
             "viewport_bbox_1000": [0, 0, 1000, 500]},
            {"region_id": "r17", "element_names": ["List row"],
             "scrollable": True,
             "viewport_bbox_1000": [0, 500, 1000, 1000]},
        ], "elements": [
            VisualElement(
                0, "Header", [0, 0, 0, 0], [0, 0], region_id="r16"),
            VisualElement(
                1, "List row", [0, 0, 0, 0], [0, 0], region_id="r17"),
        ]}},
    )

    def aggregate(_obs, elements, state_id=""):
        captured["state_id"] = state_id
        captured["bboxes"] = dict(
            host._semantic_scroll_seed_region_bboxes)
        captured["crops"] = set(
            host._semantic_scroll_seed_region_crops)
        captured["blocks"] = [
            dict(block) for block in host.perception.last_semantic_blocks]
        captured["element_regions"] = [
            element.region_id for element in elements]
        captured["force_top"] = host._semantic_scroll_force_top
        return elements

    host._scroll_aggregate = aggregate

    assert retry_semantic_scroll_audit(
        host, {"screenshot": screenshot}, "state") is True
    assert captured["state_id"] == "state"
    assert captured["bboxes"] == {
        "r16": [0, 0, 1000, 500],
        "r17": [0, 500, 1000, 1000],
    }
    assert captured["crops"] == {"r16", "r17"}
    assert [block["region_id"] for block in captured["blocks"]] == [
        "r16", "r17"]
    assert captured["element_regions"] == ["r16", "r17"]
    assert captured["force_top"] is True
    assert perception.last_semantic_blocks is live_blocks


def test_scrollable_region_retry_allows_a_valid_empty_function_inventory():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        retry_semantic_scroll_audit,
    )

    screenshot = _png_bytes(np.full((100, 100, 3), 220, dtype=np.uint8))
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_semantic_blocks=[],
    )
    captured = {}
    host = SimpleNamespace(
        env=SimpleNamespace(step=lambda action, pause=0: {
            "screenshot": screenshot}),
        perception=perception,
        _scroll_aggregate_enabled=True,
        _last_live_observation_elements=[],
        _state_data={"state": {
            "semantic_blocks": [{
                "region_id": "r-empty",
                "element_names": [],
                "scrollable": True,
                "viewport_bbox_1000": [0, 0, 1000, 1000],
            }],
            "elements": [],
        }},
    )

    def aggregate(_obs, elements, state_id=""):
        captured["state_id"] = state_id
        captured["elements"] = list(elements)
        captured["blocks"] = list(host.perception.last_semantic_blocks)
        return elements

    host._scroll_aggregate = aggregate

    assert retry_semantic_scroll_audit(
        host, {"screenshot": screenshot}, "state") is True
    assert captured["state_id"] == "state"
    assert captured["elements"] == []
    assert captured["blocks"][0]["region_id"] == "r-empty"


def test_registered_semantic_block_preserves_observation_viewport_geometry():
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        _refresh_semantic_block_members,
    )
    from gui_rewalk.src.core.visual_traversal.visual_perception import (
        VisualElement,
    )

    blocks = [{
        "local_id": "b0", "region_id": "r3", "scrollable": True,
        "bbox_1000": [0, 240, 1000, 1000],
    }]
    elements = [
        VisualElement(
            0, "Action", [0, 0, 0, 0], [0, 0], region_id="r3"),
    ]

    _refresh_semantic_block_members(blocks, elements)

    assert blocks == [{
        "region_id": "r3", "scrollable": True,
        "viewport_bbox_1000": [0, 240, 1000, 1000],
        "element_ids": [0], "element_names": ["Action"],
    }]


def test_scroll_retry_scheduler_does_not_reinventory_known_state():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
        prepare_current_scroll_audit,
    )

    record = {
        "state_ids": ["state"], "complete": False, "observations": 1,
    }
    graph = SimpleNamespace(
        scroll_ledger={"state:state:page": record}, stop_reason="")
    host = SimpleNamespace(
        graph=graph,
        _register=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("known-State scroll retry must not re-inventory")),
    )

    def retry(_observation, _state_id):
        record["complete"] = True
        return True

    host._retry_incomplete_scroll_audit = retry
    outcome = prepare_current_scroll_audit(
        host, "state", {"screenshot": b"frame"}, [], [], 0)

    assert outcome is not None
    assert outcome.stop is False


def test_failed_scroll_retry_defers_audit_but_keeps_visible_frontier_open():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
        prepare_current_scroll_audit,
    )

    record = {
        "scope_id": "region:state:r0", "state_ids": ["state"],
        "complete": False, "observations": 1,
    }
    events = []
    host = SimpleNamespace(
        graph=SimpleNamespace(
            scroll_ledger={"region:state:r0": record}, stop_reason=""),
        review_debug=SimpleNamespace(
            record_event=lambda event, **payload: events.append(
                (event, payload))),
        _retry_incomplete_scroll_audit=lambda *_args: record.update(
            observations=2),
    )

    first = prepare_current_scroll_audit(
        host, "state", {"screenshot": b"frame"}, [], [], 0)
    second = prepare_current_scroll_audit(
        host, "state", {"screenshot": b"frame"}, [], [], 0)

    assert first is not None and first.stop is False
    assert second is None
    assert host.graph.stop_reason == ""
    assert record["complete"] is False
    assert events == [("scroll_audit_deferred", {
        "node": "state", "scopes": ["region:state:r0"],
        "reason": "bounded retry remained incomplete",
    })]


def test_engine_passes_seed_region_crops_into_scroll_runtime():
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.env = engine.perception = engine.region_registry = engine.writer = object()
    engine.focus_guard = engine.page_judge = engine.block_identity_judge = None
    engine._state_data = {}
    engine._pending_transition = None
    engine._is_touch = True
    engine._stitch_node_image = False
    engine._last_scroll_frames = []
    engine._last_scroll_offsets = []
    engine._semantic_scroll_seed_region_crops = {"r2": b"seed-crop"}
    engine._frame_phash = lambda _shot: 0
    engine._screen_wh = lambda _obs: (100, 100)
    engine._record_scroll_evidence = lambda **_payload: None
    engine._map_to_top = lambda *_args, **_kwargs: None
    engine._begin_node_local_accumulation = lambda: None
    engine._accumulate_node_local_functions = lambda: None
    engine._collected_node_local_functions = lambda values: values

    runtime = VisualTraversalEngine._new_scroll_runtime(engine)
    assert runtime._semantic_scroll_seed_region_crops == {"r2": b"seed-crop"}


def test_all_declared_static_regions_complete_without_scroll_probe():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    class Env:
        provider_name = "android"

        def step(self, *_args, **_kwargs):
            raise AssertionError("static Regions must not receive a scroll probe")

    evidence = []
    runtime = ScrollRuntime(ScrollContext(
        env=Env(),
        perception=SimpleNamespace(
            use_semantic_inventory=True,
            last_semantic_blocks=[
                {"region_id": "r1", "scrollable": False},
                {"region_id": "r2", "scrollable": False},
            ],
        ),
        focus_guard=None, page_judge=None, block_identity_judge=None,
        region_registry=object(), writer=object(), state_data={},
        pending_transition=None, is_touch=True, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={}, semantic_scroll_seed_region_bboxes={},
        frame_phash=lambda _shot: 0, screen_wh=lambda _obs: (100, 100),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    element = VisualElement(0, "Action", [0, 0, 0, 0], [0, 0])

    assert runtime._scroll_aggregate(
        {"screenshot": _png_bytes(np.zeros((20, 20, 3), dtype=np.uint8))},
        [element], state_id="state",
    ) == [element]
    assert evidence == [
        {
            "scope_id": "region:r1",
            "state_id": "state",
            "region_id": "r1",
            "role": "region",
            "classification": "static",
            "termination": "static",
            "bottom_reached": False,
            "top_restored": True,
            "steps": 0,
            "max_steps": 0,
            "detail": "all declared Regions are non-scrollable",
        },
        {
            "scope_id": "region:r2",
            "state_id": "state",
            "region_id": "r2",
            "role": "region",
            "classification": "static",
            "termination": "static",
            "bottom_reached": False,
            "top_restored": True,
            "steps": 0,
            "max_steps": 0,
            "detail": "all declared Regions are non-scrollable",
        },
    ]


def test_surface_scroll_conflict_fails_closed_instead_of_certifying_static():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    evidence = []
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_surface_scrollable=True,
        last_semantic_blocks=[
            {"region_id": "r1", "scrollable": False},
            {"region_id": "r2", "scrollable": False},
        ],
    )
    runtime = ScrollRuntime(ScrollContext(
        env=SimpleNamespace(provider_name="android"),
        perception=perception,
        focus_guard=None, page_judge=None, block_identity_judge=None,
        region_registry=object(), writer=object(), state_data={},
        pending_transition=None, is_touch=True, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={}, semantic_scroll_seed_region_bboxes={},
        frame_phash=lambda _shot: 0, screen_wh=lambda _obs: (100, 100),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    element = VisualElement(0, "Action", [0, 0, 0, 0], [0, 0])

    assert runtime._scroll_aggregate(
        {"screenshot": _png_bytes(np.zeros((20, 20, 3), dtype=np.uint8))},
        [element], state_id="state",
    ) == [element]
    assert evidence[-1]["classification"] == "unknown"
    assert evidence[-1]["termination"] == "perception_unavailable"


@pytest.mark.parametrize("inventory_status", ["ok", "request_failed"])
def test_semantic_region_scroll_uses_no_vlm_between_first_frame_and_long_map(
        inventory_status):
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    height, fixed_w, region_w = 160, 50, 150
    content_h, step = 340, 60
    content = np.full((content_h, region_w, 3), 245, dtype=np.uint8)
    for index in range(17):
        y0 = index * 20
        content[y0:y0 + 20] = (
            30 + (index * 31) % 190,
            35 + (index * 47) % 185,
            40 + (index * 67) % 180,
        )
        content[y0 + 5:y0 + 15, 10 + index * 5:25 + index * 5] = 5

    def frame(offset, fixed_value=22, dynamic_value=0):
        image = np.full(
            (height, fixed_w + region_w, 3),
            (fixed_value, 26, 38), dtype=np.uint8)
        image[:, fixed_w:] = content[offset:offset + height]
        if dynamic_value:
            # A changing status/value inside the scroll Region must not prevent
            # physical upper-boundary detection after the content reaches top.
            image[2:14, fixed_w + 2:fixed_w + 14] = (
                dynamic_value % 255,
                (dynamic_value * 3) % 255,
                (dynamic_value * 7) % 255,
            )
        return _png_bytes(image)

    class Env:
        vm_platform = "android"
        def __init__(self):
            self.offset = 0
            self.actions = []
            self.bottom_bounce_emitted = False
        def step(self, action, pause=0):
            self.actions.append((action, pause))
            if action["action_type"] == "WAIT":
                return {"screenshot": frame(
                    self.offset, fixed_value=22 + len(self.actions) * 17)}
            direction = action["parameters"]["direction"]
            if direction == "down":
                was_bottom = self.offset == content_h - height
                self.offset = min(content_h - height, self.offset + step)
            else:
                was_bottom = False
                # Return gestures can travel less than collection gestures.
                # The final bounded gesture must still be observed and checked.
                self.offset = max(0, self.offset - 25)
            # The fixed outer surface may legitimately react to scrolling.
            # Region continuity, not unrelated outer pixels, owns the long map.
            screenshot = frame(
                self.offset, fixed_value=22 + len(self.actions) * 17,
                dynamic_value=(
                    31 + len(self.actions) * 19
                    if direction == "up" else 0))
            if (direction == "down" and was_bottom
                    and not self.bottom_bounce_emitted):
                transient = _rgb(screenshot).copy()
                transient[:, fixed_w:] = np.flip(
                    transient[:, fixed_w:], axis=0)
                screenshot = _png_bytes(transient)
                self.bottom_bounce_emitted = True
            return {"screenshot": screenshot}

    long_inventory_calls = []
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        # A fixed outer surface must not suppress its independently scrollable block.
        last_surface_scrollable=False,
        last_semantic_blocks=[{
            "local_id": "b0", "region_id": "r2", "role": "content_list",
            "note": "rows", "scrollable": True,
            "element_names": ["Row 01"],
        }],
        semantic_inventory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("scroll loop must not call semantic inventory")),
        inventory_scrollable_region=lambda image, block, region_id: (
            long_inventory_calls.append((image, block, region_id)) or [
                VisualElement(1, "Row 17", [0, 0, 0, 0], [0, 0],
                              region_id=region_id, geometry_status="semantic_only")
            ]),
        last_region_long_inventory={"status": inventory_status},
    )
    env = Env()
    evidence = []

    class FrameHash:
        def __init__(self, payload): self.payload = payload
        # Simulate transient rendering that prevents an exact match with the
        # initial crop even after the Region physically reaches its top edge.
        def __sub__(self, other): return 64

    bbox = [250, 0, 1000, 1000]
    shot0 = frame(0)
    runtime = ScrollRuntime(ScrollContext(
        env=env, perception=perception, focus_guard=None,
        page_judge=SimpleNamespace(same_page=lambda *_args: (_ for _ in ()).throw(
            AssertionError("scroll loop must not call page judge"))),
        block_identity_judge=None, region_registry=object(), writer=object(),
        state_data={}, pending_transition=None, is_touch=True,
        stitch_node_image=False, last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={
            "r2": _crop_normalized_region(shot0, bbox)},
        semantic_scroll_seed_region_bboxes={"r2": bbox},
        frame_phash=lambda payload: FrameHash(payload),
        screen_wh=lambda _obs: (fixed_w + region_w, height),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    first = [VisualElement(
        0, "Row 01", [0, 0, 0, 0], [0, 0], region_id="r2",
        geometry_status="semantic_only")]
    result = runtime._scroll_aggregate(
        {"screenshot": shot0}, first, state_id="state")

    assert [element.name for element in result] == (
        ["Row 01", "Row 17"] if inventory_status == "ok" else ["Row 01"])
    assert len(long_inventory_calls) == 1
    assert env.bottom_bounce_emitted is True
    if inventory_status == "ok":
        composite = _rgb(runtime._state_data["state"][
            "_semantic_scroll_region_crops"]["r2"])
        assert composite.shape[1] == region_w
        assert composite.shape[0] > height
    else:
        assert "_semantic_scroll_region_crops" not in runtime._state_data.get(
            "state", {})
    assert all(action["parameters"]["x"] == 125
               for action, _pause in env.actions)
    assert all(pause >= 1.0 for action, pause in env.actions
               if action["parameters"]["direction"] == "up")
    assert evidence[-1]["termination"] == (
        "viewport_stable"
        if inventory_status == "ok" else "perception_unavailable")
    assert evidence[-1]["top_restored"] is True
    assert evidence[-1]["bottom_reached"] is (inventory_status == "ok")


def test_semantic_region_scroll_scales_gesture_to_small_viewport():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    screen_h, screen_w = 200, 120
    region_top, region_bottom = 20, 100
    viewport_h = region_bottom - region_top
    # The same physical travel budget must still reach the bottom after the
    # gesture is shortened to preserve overlap inside this small viewport.
    content_h = 600
    content = np.random.default_rng(41).integers(
        0, 255, size=(content_h, screen_w, 3), dtype=np.uint8)

    def frame(offset):
        image = np.full((screen_h, screen_w, 3), 232, dtype=np.uint8)
        image[:region_top] = (30, 34, 40)
        image[region_top:region_bottom] = content[
            offset:offset + viewport_h]
        # A fixed input surface below the independently scrollable viewport.
        image[region_bottom:] = (210, 214, 224)
        return _png_bytes(image)

    class Env:
        vm_platform = "android"

        def __init__(self):
            self.offset = 0
            self.actions = []

        def step(self, action, pause=0):
            self.actions.append(action)
            if action["action_type"] == "WAIT":
                return {"screenshot": frame(self.offset)}
            params = action["parameters"]
            span = max(1, round(screen_h * float(params["frac"])))
            delta = span if params["direction"] == "down" else -span
            self.offset = max(
                0, min(content_h - viewport_h, self.offset + delta))
            return {"screenshot": frame(self.offset)}

    class FrameHash:
        def __init__(self, payload):
            self.payload = payload

        def __sub__(self, other):
            return 0 if self.payload == other.payload else 64

    bbox = [0, 100, 1000, 500]
    shot0 = frame(0)
    calls = []
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_surface_scrollable=False,
        last_semantic_blocks=[{
            "region_id": "r1", "role": "results", "scrollable": True,
        }],
        inventory_scrollable_region=lambda image, block, region_id: (
            calls.append((image, block, region_id)) or [VisualElement(
                1, "Bottom result", [0, 0, 0, 0], [0, 0],
                region_id=region_id, geometry_status="semantic_only")]),
        last_region_long_inventory={"status": "ok"},
    )
    evidence = []
    env = Env()
    runtime = ScrollRuntime(ScrollContext(
        env=env, perception=perception, focus_guard=None,
        page_judge=None, block_identity_judge=None, region_registry=object(),
        writer=object(), state_data={}, pending_transition=None, is_touch=True,
        stitch_node_image=False, last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={
            "r1": _crop_normalized_region(shot0, bbox)},
        semantic_scroll_seed_region_bboxes={"r1": bbox},
        frame_phash=lambda payload: FrameHash(payload),
        screen_wh=lambda _obs: (screen_w, screen_h),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))

    result = runtime._scroll_aggregate(
        {"screenshot": shot0}, [VisualElement(
            0, "Top result", [0, 0, 0, 0], [0, 0], region_id="r1")],
        state_id="state")

    assert [element.name for element in result] == [
        "Top result", "Bottom result"]
    assert len(calls) == 1
    assert evidence[-1]["termination"] == "viewport_stable"
    assert evidence[-1]["bottom_reached"] is True
    assert evidence[-1]["top_restored"] is True
    scroll_fracs = [
        action["parameters"]["frac"]
        for action in env.actions if action["action_type"] == "SCROLL"]
    assert scroll_fracs
    assert all(0.16 <= frac <= 0.17 for frac in scroll_fracs)


def test_semantic_region_scroll_captures_multiple_independent_regions():
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    height, width, step = 90, 200, 30
    content_h = 150

    def content(seed):
        image = np.full((content_h, width // 2, 3), 245, dtype=np.uint8)
        for index, y0 in enumerate(range(0, content_h, 15)):
            image[y0:y0 + 12] = (
                (seed + index * 31) % 220,
                (seed + index * 47) % 220,
                (seed + index * 67) % 220,
            )
            image[y0 + 3:y0 + 9, 5 + index:15 + index] = 5
        return image

    left = content(30)
    right = content(90)

    def frame(left_offset, right_offset):
        image = np.zeros((height, width, 3), dtype=np.uint8)
        image[:, :100] = left[left_offset:left_offset + height]
        image[:, 100:] = right[right_offset:right_offset + height]
        return _png_bytes(image)

    class Env:
        vm_platform = "android"

        def __init__(self):
            self.offsets = {"r1": 0, "r2": 0}
            self.actions = []

        def step(self, action, pause=0):
            self.actions.append(action)
            if action["parameters"]["x"] < 10:
                return {"screenshot": frame(
                    self.offsets["r1"], self.offsets["r2"])}
            region_id = "r1" if action["parameters"]["x"] < 100 else "r2"
            delta = step if action["parameters"]["direction"] == "down" else -step
            self.offsets[region_id] = max(
                0, min(content_h - height, self.offsets[region_id] + delta))
            return {"screenshot": frame(
                self.offsets["r1"], self.offsets["r2"])}

    calls = []
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_surface_scrollable=False,
        last_semantic_blocks=[
            {"region_id": "r1", "role": "left_list", "scrollable": True},
            {"region_id": "r2", "role": "right_list", "scrollable": True},
            {"region_id": "r3", "role": "static_misclassification",
             "scrollable": True},
        ],
        inventory_scrollable_region=lambda image, block, region_id: (
            calls.append(region_id) or [VisualElement(
                len(calls) + 10, f"Bottom {region_id}", [0, 0, 0, 0], [0, 0],
                region_id=region_id, geometry_status="semantic_only")]),
        last_region_long_inventory={"status": "ok"},
    )

    class FrameHash:
        def __init__(self, payload): self.payload = payload
        def __sub__(self, other): return 0 if self.payload == other.payload else 64

    env = Env()
    evidence = []
    shot0 = frame(0, 0)
    bboxes = {
        "r1": [0, 0, 500, 1000],
        "r2": [500, 0, 1000, 1000],
        "r3": [0, 0, 20, 1000],
    }
    runtime = ScrollRuntime(ScrollContext(
        env=env, perception=perception, focus_guard=None,
        page_judge=None, block_identity_judge=None, region_registry=object(),
        writer=object(), state_data={}, pending_transition=None, is_touch=True,
        stitch_node_image=False, last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={
            region_id: _crop_normalized_region(shot0, bbox)
            for region_id, bbox in bboxes.items()},
        semantic_scroll_seed_region_bboxes=bboxes,
        frame_phash=lambda payload: FrameHash(payload),
        screen_wh=lambda _obs: (width, height),
        record_scroll_evidence=lambda **row: evidence.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    first = [
        VisualElement(0, "Top r1", [0, 0, 0, 0], [0, 0], region_id="r1"),
        VisualElement(1, "Top r2", [0, 0, 0, 0], [0, 0], region_id="r2"),
    ]

    result = runtime._scroll_aggregate(
        {"screenshot": shot0}, first, state_id="state")

    assert calls == ["r1", "r2"]
    assert [element.name for element in result] == [
        "Top r1", "Top r2", "Bottom r1", "Bottom r2"]
    maps = runtime._state_data["state"]["_semantic_scroll_region_crops"]
    assert set(maps) == {"r1", "r2"}
    assert all(_rgb(maps[region_id]).shape[0] > height for region_id in maps)
    assert {row["region_id"] for row in evidence} == {"r1", "r2", "r3"}
    assert all(row["top_restored"] is True for row in evidence)
    assert {action["parameters"]["x"] for action in env.actions} == {2, 50, 150}


def test_android_semantic_region_excludes_known_system_bands(monkeypatch):
    from types import SimpleNamespace
    from gui_rewalk.src.core.visual_traversal.grounding import scroll as scroll_module
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    height, width = 2400, 1080
    shot = _png_bytes(np.full((height, width, 3), 240, dtype=np.uint8))
    captured = []
    cropped_bboxes = []
    real_crop = scroll_module._crop_normalized_region
    monkeypatch.setattr(
        scroll_module, "_crop_normalized_region",
        lambda payload, bbox: (
            cropped_bboxes.append(list(bbox)) or real_crop(payload, bbox)))

    class Env:
        provider_name = "android"
        vm_platform = "android"

        def step(self, _action, pause=0):
            return {"screenshot": shot}

    class FrameHash:
        def __sub__(self, _other): return 0

    runtime = ScrollRuntime(ScrollContext(
        env=Env(), perception=SimpleNamespace(
            use_semantic_inventory=True,
            last_surface_scrollable=True,
            last_semantic_blocks=[{
                "region_id": "r1", "role": "settings_list", "scrollable": True,
            }],
            inventory_scrollable_region=lambda *_args: []),
        focus_guard=None, page_judge=None, block_identity_judge=None,
        region_registry=object(), writer=object(), state_data={},
        pending_transition=None, is_touch=True, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={"r1": b"unclipped-seed"},
        semantic_scroll_seed_region_bboxes={"r1": [0, 0, 1000, 1000]},
        frame_phash=lambda _payload: FrameHash(),
        screen_wh=lambda _obs: (width, height),
        record_scroll_evidence=lambda **row: captured.append(row),
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))

    runtime._scroll_aggregate(
        {"screenshot": shot}, [VisualElement(
            0, "Network & internet", [0, 0, 0, 0], [0, 0], region_id="r1")],
        state_id="state")

    assert captured[-1]["termination"] == "viewport_stable"
    assert cropped_bboxes[0] == [0, 33, 1000, 980]


# ── synthetic page construction ─────────────────────────────────────────────
W = 320                  # page / viewport width
TOP_H = 40               # sticky top app-bar height
BOT_H = 56               # sticky bottom nav-bar height
ROW_H = 24               # content row height
N_ROWS = 60              # number of distinct content rows
VIEWPORT_H = 480         # one screen
CONTENT_H = N_ROWS * ROW_H
PAGE_H = TOP_H + CONTENT_H + BOT_H


def _unique_color(i: int) -> tuple:
    """A distinct, well-separated colour per row index (deterministic)."""
    r = (37 * (i + 1)) % 200 + 30
    g = (91 * (i + 1)) % 200 + 30
    b = (53 * (i + 1)) % 200 + 30
    return (r, g, b)


def build_page() -> np.ndarray:
    """The full tall ground-truth page (RGB)."""
    page = np.zeros((PAGE_H, W, 3), dtype=np.uint8)
    # sticky top bar — a constant teal with a white title stripe
    page[:TOP_H] = (10, 120, 120)
    page[TOP_H // 2 - 3:TOP_H // 2 + 3, 20:W - 20] = (255, 255, 255)
    # content rows — each a unique colour + a unique black marker block whose
    # x-position encodes the row index (so a duplicated row is detectable and a
    # mis-stitched row is visually obvious in debugging)
    for i in range(N_ROWS):
        y0 = TOP_H + i * ROW_H
        col = _unique_color(i)
        page[y0:y0 + ROW_H] = col
        mx = 10 + (i * 5) % (W - 30)
        page[y0 + 4:y0 + ROW_H - 4, mx:mx + 14] = (0, 0, 0)
    # sticky bottom bar — constant dark with 4 evenly spaced "tab" chips
    page[TOP_H + CONTENT_H:] = (30, 30, 40)
    for t in range(4):
        cx = int(W * (t + 0.5) / 4)
        page[TOP_H + CONTENT_H + 12:PAGE_H - 12, cx - 12:cx + 12] = (200, 200, 60)
    return page


def render_scrolled_frames(page: np.ndarray, scroll_steps: list) -> list:
    """Render viewport crops as if scrolled.

    Each frame = sticky top bar (fixed) + a CONTENT window taken at the running
    content offset + sticky bottom bar (fixed). ``scroll_steps`` gives the
    increment (px) the content slides up at each step (varying = fling jitter).
    The first frame is at content offset 0 (page top).
    """
    top_bar = page[:TOP_H].copy()
    bot_bar = page[TOP_H + CONTENT_H:].copy()
    content = page[TOP_H:TOP_H + CONTENT_H]
    win_h = VIEWPORT_H - TOP_H - BOT_H  # visible content rows per frame

    frames = []
    offset = 0
    offsets = [0]
    for inc in scroll_steps:
        offset = min(offset + inc, CONTENT_H - win_h)
        offsets.append(offset)
    for off in offsets:
        frame = np.zeros((VIEWPORT_H, W, 3), dtype=np.uint8)
        frame[:TOP_H] = top_bar
        frame[TOP_H:TOP_H + win_h] = content[off:off + win_h]
        frame[TOP_H + win_h:] = bot_bar
        frames.append(frame)
    return frames, offsets, win_h


# ── row-identity helpers (ground truth) ─────────────────────────────────────
def row_signature(row_block: np.ndarray) -> tuple:
    """A compact signature of a content row: its dominant colour + marker x."""
    # dominant colour = the colour of the leftmost 6px column band (markers avoid
    # the far left for low indices, but use a robust median over the whole row)
    med = tuple(int(v) for v in np.median(row_block.reshape(-1, 3), axis=0))
    return med


def expected_row_sigs() -> list:
    page = build_page()
    sigs = []
    for i in range(N_ROWS):
        y0 = TOP_H + i * ROW_H
        sigs.append(row_signature(page[y0 + 2:y0 + ROW_H - 2]))
    return sigs


# ── the test ────────────────────────────────────────────────────────────────
def main() -> int:
    page = build_page()
    win_h = VIEWPORT_H - TOP_H - BOT_H
    # non-uniform scroll increments (fling jitter); chosen so consecutive frames
    # OVERLAP (inc < win_h) and the page is fully covered.
    incs = [200, 240, 180, 260, 220, 200, 240, 200, 260, 240, 200, 240, 200, 200]
    frames, offsets, _ = render_scrolled_frames(page, incs)
    print(f"page={PAGE_H}px  viewport={VIEWPORT_H}px  content_win={win_h}px  "
          f"frames={len(frames)}  offsets={offsets}")

    res = vs.stitch_frames(frames, debug=True)
    assert res is not None, "stitch returned None"
    comp = res.image
    print(f"composite: {comp.shape[0]}x{comp.shape[1]}  "
          f"sticky_top={res.sticky_top_h}  sticky_bot={res.sticky_bot_h}")

    failures = []

    # ── (A) sticky bars detected at ~the right heights ──
    if not (TOP_H - 4 <= res.sticky_top_h <= TOP_H + 4):
        failures.append(f"sticky_top {res.sticky_top_h} != ~{TOP_H}")
    if not (BOT_H - 4 <= res.sticky_bot_h <= BOT_H + 4):
        failures.append(f"sticky_bot {res.sticky_bot_h} != ~{BOT_H}")

    # ── (B) full-page height reconstructed within tolerance ──
    # tolerance: a couple of rows (overlap math is px-exact but the last frame may
    # clamp at the page bottom, and sticky detection can be ±a few px).
    tol = 2 * ROW_H
    if abs(comp.shape[0] - PAGE_H) > tol:
        failures.append(f"composite height {comp.shape[0]} vs page {PAGE_H} "
                        f"(tol {tol})")

    # ── (C) every unique content row appears EXACTLY once ──
    exp = expected_row_sigs()
    # scan the composite's CONTENT region (between sticky bars) row by row and
    # count, for each expected row signature, how many ROW_H-tall bands match it.
    body = comp[res.sticky_top_h: comp.shape[0] - res.sticky_bot_h]
    found_counts = {i: 0 for i in range(N_ROWS)}
    y = 0
    # walk in ROW_H steps but align to detected row boundaries by sampling the
    # middle of each candidate band; tolerate a small global offset by scanning
    # every 2px and de-duping consecutive identical hits.
    last_hit = None
    step = 2
    while y + 4 < body.shape[0]:
        sig = row_signature(body[y:y + min(ROW_H - 4, body.shape[0] - y)])
        # nearest expected row by colour distance
        best_i, best_d = -1, 1 << 30
        for i, es in enumerate(exp):
            d = sum((sig[c] - es[c]) ** 2 for c in range(3))
            if d < best_d:
                best_i, best_d = i, d
        if best_d <= 300:  # confident colour match
            if best_i != last_hit:
                found_counts[best_i] += 1
                last_hit = best_i
        else:
            last_hit = None
        y += step

    missing = [i for i, c in found_counts.items() if c == 0]
    duped = [(i, c) for i, c in found_counts.items() if c > 1]
    if missing:
        failures.append(f"{len(missing)} content rows MISSING from composite: "
                        f"{missing[:8]}{'...' if len(missing) > 8 else ''}")
    if duped:
        failures.append(f"{len(duped)} content rows DUPLICATED (overlap not "
                        f"removed): {duped[:8]}{'...' if len(duped) > 8 else ''}")

    # ── (D) sticky bars appear exactly ONCE (not per-frame) ──
    # The teal top-bar colour (10,120,120) must occupy ~TOP_H rows total in the
    # composite, NOT TOP_H * n_frames. Count rows whose median ≈ the bar colour.
    def _count_rows_like(color, tolerance=20):
        cnt = 0
        for yy in range(comp.shape[0]):
            med = np.median(comp[yy], axis=0)
            if all(abs(int(med[c]) - color[c]) <= tolerance for c in range(3)):
                cnt += 1
        return cnt

    top_rows = _count_rows_like((10, 120, 120))
    if top_rows > TOP_H + 8:
        failures.append(f"sticky TOP bar appears {top_rows}px (>~{TOP_H}) — "
                        f"duplicated across frames")
    # bottom bar base colour (30,30,40)
    bot_rows = _count_rows_like((30, 30, 40))
    if bot_rows > BOT_H + 8:
        failures.append(f"sticky BOTTOM bar appears {bot_rows}px (>~{BOT_H}) — "
                        f"duplicated across frames")

    # ── (E) y-map round-trips: the named frame really shows that row at that y ──
    rng = np.random.default_rng(0)
    rt_fail = 0
    samples = 0
    for _ in range(200):
        cy = int(rng.integers(res.sticky_top_h,
                              comp.shape[0] - res.sticky_bot_h - 1))
        fi, vy = res.composite_y_to_scroll(cy)
        if not (0 <= fi < len(frames)):
            rt_fail += 1
            continue
        if not (0 <= vy < frames[fi].shape[0]):
            rt_fail += 1
            continue
        # the pixel the map points at must match the composite pixel (the stitch
        # painted composite[cy] FROM frames[fi][vy]) — exact equality expected.
        comp_px = comp[cy, W // 2].astype(np.int16)
        frame_px = frames[fi][vy, W // 2].astype(np.int16)
        samples += 1
        if np.abs(comp_px - frame_px).max() > 2:
            rt_fail += 1
    if rt_fail > 0:
        failures.append(f"y-map round-trip: {rt_fail}/{samples} samples did not "
                        f"match the source frame pixel")

    # ── verdict ──
    print("\n--- row coverage ---")
    print(f"  rows found exactly once : {sum(1 for c in found_counts.values() if c == 1)}/{N_ROWS}")
    print(f"  rows missing            : {len(missing)}")
    print(f"  rows duplicated         : {len(duped)}")
    print(f"  sticky-top px in comp   : {top_rows} (bar={TOP_H})")
    print(f"  sticky-bot px in comp   : {bot_rows} (bar={BOT_H})")
    print(f"  y-map round-trip        : {samples - rt_fail}/{samples} ok")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nPASS: full-page reconstructed, no overlap dup, sticky bars de-duped, "
          "y-map round-trips.")
    return 0


# ── element-anchored offset path (tiny-overlap fling) ────────────────────────
# The pixel template-match (estimate_shift) is unreliable on a real scroll exactly
# where the prototype broke: the PRODUCTION large fling advances ~2/3 of the
# viewport per swipe, so only ~1 row of overlap survives — the prev-frame bottom
# probe-strip has scrolled OFF, and the matcher latches onto a repeated-ish region
# returning a CONFIDENTLY-WRONG shift (HIGH score, WRONG value). That collapses the
# composite (each step under-advances → rows duplicated / page truncated). The
# engine, though, matches the SAME control across the two frames (ElementMatcher)
# and measures its y-delta; fed as ``element_offsets`` it overrides the wrong
# pixel value. This test reproduces that tiny-overlap regime and asserts:
#   * pixel-only stitch is WRONG (composite height far from the page);
#   * element-offset stitch reconstructs the full page and the y-map round-trips;
#   * a bogus element offset is bounded (not blindly trusted).

FLAT_W = 320
FLAT_TOP_H = 36
FLAT_BOT_H = 48
FLAT_ROW_H = 30
FLAT_N_ROWS = 60
FLAT_VIEWPORT_H = 480
FLAT_CONTENT_H = FLAT_N_ROWS * FLAT_ROW_H
FLAT_PAGE_H = FLAT_TOP_H + FLAT_CONTENT_H + FLAT_BOT_H


def build_list_page() -> np.ndarray:
    """A plain list page: faint chrome bars + distinct (matchable) content rows.
    Rows are individually distinguishable (so element matching is strong) but the
    page is repetitive enough that, under a tiny-overlap fling, the strip NCC
    mis-locks (high score, wrong shift) — the very failure element offsets fix."""
    page = np.full((FLAT_PAGE_H, FLAT_W, 3), (235, 236, 238), dtype=np.uint8)
    page[:FLAT_TOP_H] = (210, 212, 216)
    for i in range(FLAT_N_ROWS):
        y0 = FLAT_TOP_H + i * FLAT_ROW_H
        col = ((37 * (i + 1)) % 160 + 40, (91 * (i + 1)) % 160 + 40,
               (53 * (i + 1)) % 160 + 40)
        page[y0:y0 + FLAT_ROW_H] = col
    page[FLAT_TOP_H + FLAT_CONTENT_H:] = (210, 212, 216)
    return page


def render_flat_frames(page, scroll_steps):
    top_bar = page[:FLAT_TOP_H].copy()
    bot_bar = page[FLAT_TOP_H + FLAT_CONTENT_H:].copy()
    content = page[FLAT_TOP_H:FLAT_TOP_H + FLAT_CONTENT_H]
    win_h = FLAT_VIEWPORT_H - FLAT_TOP_H - FLAT_BOT_H
    offsets = [0]
    off = 0
    for inc in scroll_steps:
        off = min(off + inc, FLAT_CONTENT_H - win_h)
        offsets.append(off)
    frames = []
    for off in offsets:
        fr = np.zeros((FLAT_VIEWPORT_H, FLAT_W, 3), dtype=np.uint8)
        fr[:FLAT_TOP_H] = top_bar
        fr[FLAT_TOP_H:FLAT_TOP_H + win_h] = content[off:off + win_h]
        fr[FLAT_TOP_H + win_h:] = bot_bar
        frames.append(fr)
    return frames, offsets, win_h


def test_element_anchored_offset() -> int:
    print("\n=== element-anchored offset (tiny-overlap fling) ===")
    page = build_list_page()
    win_h = FLAT_VIEWPORT_H - FLAT_TOP_H - FLAT_BOT_H
    # LARGE per-step shifts close to the content window (~16px overlap) = the
    # production amount=1 fling; this is where the pixel strip-match mis-locks.
    incs = [380, 370, 385, 375, 380, 380, 380]
    frames, offsets, _ = render_flat_frames(page, incs)
    # element_offsets[i] = content shift from frame i-1 -> i (offsets diff) — what
    # the engine derives from matched element y-positions (median delta).
    elem_offsets = [None]
    for i in range(1, len(offsets)):
        elem_offsets.append(float(offsets[i] - offsets[i - 1]))

    failures = []

    # (1) pixel-only: the strip mis-locks under tiny overlap -> wrong composite
    #     height (the page is NOT correctly reconstructed).
    res_px = vs.stitch_frames(frames, debug=True)
    assert res_px is not None
    px_h = res_px.image.shape[0]

    # (2) element-anchored: full page reconstructed within ~a row of tolerance.
    res_el = vs.stitch_frames(frames, debug=True, element_offsets=elem_offsets)
    assert res_el is not None
    el_h = res_el.image.shape[0]
    print(f"  composite height: pixel-only={px_h}px  element-anchored={el_h}px  "
          f"(page={FLAT_PAGE_H}px)")

    tol = 2 * FLAT_ROW_H
    if abs(el_h - FLAT_PAGE_H) > tol:
        failures.append(f"element-anchored composite {el_h} != page {FLAT_PAGE_H} "
                        f"(tol {tol}) — offsets not used / wrong")
    # the pixel-only path must be DEMONSTRABLY worse (the whole reason for offsets):
    # its height should miss the page by more than the element-anchored path does.
    if abs(px_h - FLAT_PAGE_H) <= abs(el_h - FLAT_PAGE_H):
        failures.append(f"pixel-only composite ({px_h}) is not worse than "
                        f"element-anchored ({el_h}) vs page {FLAT_PAGE_H} — the "
                        f"tiny-overlap pixel failure was not reproduced, so the "
                        f"test does not exercise the offset path")

    # (3) y-map of the element-anchored composite round-trips.
    rng = np.random.default_rng(1)
    rt_fail = samples = 0
    for _ in range(200):
        cy = int(rng.integers(res_el.sticky_top_h,
                              el_h - res_el.sticky_bot_h - 1))
        fi, vy = res_el.composite_y_to_scroll(cy)
        if not (0 <= fi < len(frames)) or not (0 <= vy < frames[fi].shape[0]):
            rt_fail += 1
            continue
        samples += 1
        comp_px = res_el.image[cy, FLAT_W // 2].astype(np.int16)
        frame_px = frames[fi][vy, FLAT_W // 2].astype(np.int16)
        if np.abs(comp_px - frame_px).max() > 2:
            rt_fail += 1
    if rt_fail > 0:
        failures.append(f"element-anchored y-map round-trip: {rt_fail}/{samples} "
                        f"samples mismatched the source frame pixel")
    print(f"  y-map round-trip (element-anchored): {samples - rt_fail}/{samples} ok")

    # (4) a bogus (huge) element offset must be REJECTED (clamped to one band, not
    #     blindly used) — guards against a mis-matched anchor poisoning the stitch.
    bogus = [None] + [99999.0] * (len(frames) - 1)
    res_bogus = vs.stitch_frames(frames, element_offsets=bogus)
    assert res_bogus is not None
    if res_bogus.image.shape[0] > FLAT_PAGE_H + 4 * FLAT_ROW_H:
        failures.append(f"bogus huge offset not bounded: composite "
                        f"{res_bogus.image.shape[0]} >> page {FLAT_PAGE_H}")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: element-anchored offset reconstructs the tiny-overlap page the "
          "pixel match got wrong, y-map round-trips, bogus offsets are bounded.")
    return 0


# ── Android dynamic system-bar regression ────────────────────────────────────────
def test_dynamic_android_system_bands() -> int:
    """Dynamic clock/gesture pixels must not defeat sticky-band removal.

    The old detector scanned identical rows from y=0 / y=H-1. One changing
    status-bar or gesture row therefore returned a zero-height sticky band and
    pasted a navigation pill at every seam. This fixture changes *every* system
    bar between frames while keeping an adjacent app toolbar stable.
    """
    print("\n=== dynamic Android system bars (fixed geometry) ===")
    w, h = 260, 620
    sys_top, app_top, sys_bot = 30, 46, 26
    row_h, n_rows = 34, 52
    content_h = row_h * n_rows
    win_h = h - sys_top - app_top - sys_bot

    content = np.full((content_h, w, 3), 244, dtype=np.uint8)
    for i in range(n_rows):
        y0 = i * row_h
        content[y0:y0 + row_h] = _unique_color(i)
        x0 = 8 + (i * 13) % (w - 42)
        content[y0 + 6:y0 + row_h - 6, x0:x0 + 22] = (4, 4, 4)

    offsets = [0]
    while offsets[-1] < content_h - win_h:
        offsets.append(min(offsets[-1] + 250, content_h - win_h))
    frames = []
    for i, off in enumerate(offsets):
        fr = np.zeros((h, w, 3), dtype=np.uint8)
        # Deliberately dynamic platform status bar (clock/signal/battery proxy).
        fr[:sys_top] = ((31 * i + 17) % 255, (67 * i + 43) % 255,
                        (97 * i + 71) % 255)
        fr[4:sys_top - 4, 8 + 7 * i:28 + 7 * i] = (255, 255, 255)
        # Stable *app* toolbar immediately below the dynamic status bar. The
        # fixed system minimum must let inferred sticky detection extend over it.
        fr[sys_top:sys_top + app_top] = (20, 112, 150)
        fr[sys_top + 15:sys_top + 21, 24:w - 24] = (245, 245, 245)
        y0 = sys_top + app_top
        fr[y0:y0 + win_h] = content[off:off + win_h]
        # Deliberately dynamic gesture/nav strip and moving pill.
        fr[h - sys_bot:] = ((83 * i + 11) % 255, (29 * i + 23) % 255,
                            (47 * i + 37) % 255)
        pill_x = 52 + (i * 19) % (w - 104)
        fr[h - 9:h - 5, pill_x:pill_x + 52] = (250, 250, 250)
        frames.append(fr)

    elem_offsets = [None] + [float(offsets[i] - offsets[i - 1])
                             for i in range(1, len(offsets))]
    res = vs.stitch_frames(
        frames,
        element_offsets=elem_offsets,
        system_top_h=sys_top,
        system_bot_h=sys_bot,
        debug=True,
    )
    assert res is not None
    failures = []

    if res.system_top_h != sys_top or res.system_bot_h != sys_bot:
        failures.append(
            f"system metadata {(res.system_top_h, res.system_bot_h)} != "
            f"{(sys_top, sys_bot)}")
    if not (sys_top + app_top - 2 <= res.sticky_top_h
            <= sys_top + app_top + 2):
        failures.append(
            f"sticky top {res.sticky_top_h} did not extend over adjacent app "
            f"toolbar (~{sys_top + app_top})")
    if not (sys_bot <= res.sticky_bot_h <= sys_bot + 2):
        failures.append(f"sticky bottom {res.sticky_bot_h} != ~{sys_bot}")

    expected_h = sys_top + app_top + content_h + sys_bot
    if abs(res.image.shape[0] - expected_h) > row_h:
        failures.append(
            f"composite height {res.image.shape[0]} != ~{expected_h}")

    # The y-map is the strongest seam assertion: exactly one top system band and
    # one bottom system band may survive. Any old repeated pill seam contributes
    # extra rows whose source in-frame y is inside a system band.
    sys_rows = []
    interior_sys_rows = []
    for cy, (_fi, in_y) in enumerate(res.y_map):
        in_y = int(in_y)
        is_sys = in_y < sys_top or in_y >= h - sys_bot
        if is_sys:
            sys_rows.append(cy)
            if not (cy < sys_top or cy >= res.image.shape[0] - sys_bot):
                interior_sys_rows.append(cy)
    if len(sys_rows) != sys_top + sys_bot:
        failures.append(
            f"system provenance occupies {len(sys_rows)} rows, expected exactly "
            f"{sys_top + sys_bot} (one exterior copy)")
    if interior_sys_rows:
        failures.append(
            f"{len(interior_sys_rows)} system rows remain at composite seams: "
            f"{interior_sys_rows[:8]}")
    if not np.array_equal(res.image[:sys_top], frames[0][:sys_top]):
        failures.append("composite top is not the first frame's single status bar")
    if not np.array_equal(res.image[-sys_bot:], frames[-1][-sys_bot:]):
        failures.append("composite bottom is not the last frame's single gesture bar")

    if failures:
        print("FAIL:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"PASS: {len(frames)} dynamic system-bar frames -> one top + one "
          f"bottom copy; 0 interior system rows; sticky app toolbar preserved.")
    return 0


def test_tiled_system_band_provenance_filter() -> int:
    """Middle tiles cannot emit system UI, even for a deliberately bad composite.

    This directly exercises ``VisualTraversalEngine._perceive_tiled`` with an
    old-style composite containing three full Android frames concatenated. The
    middle tile is told ``system_band=none`` by design, so only y-map provenance
    can reject its repeated clock/pill candidates.
    """
    print("\n=== tiled perception system-row provenance filter ===")
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    frame_h, w, n_frames = 500, 240, 3
    sys_top, sys_bot = 22, 22
    comp_h = frame_h * n_frames
    image = np.full((comp_h, w, 3), 232, dtype=np.uint8)
    markers = {}

    def paint(name, cy, color, mode, size=32):
        x0, y0 = 88, cy - size // 2
        image[y0:y0 + size, x0:x0 + size] = color
        mid = size // 2
        if mode == "v":
            image[y0 + 3:y0 + size - 3, x0 + mid:x0 + size - 3] = (2, 2, 2)
        elif mode == "h":
            image[y0 + mid:y0 + size - 3, x0 + 3:x0 + size - 3] = (2, 2, 2)
        else:
            image[y0 + 3:y0 + mid, x0 + 3:x0 + mid] = (2, 2, 2)
            image[y0 + mid:y0 + size - 3, x0 + mid:x0 + size - 3] = (2, 2, 2)
        markers[tuple(color)] = (name, [x0, y0, size, size], [x0 + 16, cy])

    app_colors = [(190, 40, 40), (40, 170, 70), (40, 80, 200)]
    for fi in range(n_frames):
        base = fi * frame_h
        paint(f"system_top_{fi}", base + 8,
              (250, 210 - 20 * fi, 30 + 30 * fi), "h", size=14)
        paint(f"app_{fi}", base + 250, app_colors[fi], ("v", "h", "d")[fi])
        paint(f"system_bottom_{fi}", base + frame_h - 8,
              (210 - 20 * fi, 30 + 30 * fi, 245), "v", size=14)

    ymap = np.empty((comp_h, 2), dtype=np.int32)
    for cy in range(comp_h):
        ymap[cy] = (cy // frame_h, cy % frame_h)
    res = vs.StitchResult(
        image=image,
        y_map=ymap,
        sticky_top_h=sys_top,
        sticky_bot_h=sys_bot,
        frame_h=frame_h,
        frame_top_in_composite=[0, frame_h, 2 * frame_h],
        system_top_h=sys_top,
        system_bot_h=sys_bot,
    )

    class MarkerPerception:
        def __init__(self):
            self.last_som_image = None
            self.calls = []

        def detect_and_name(self, shot, system_band="both"):
            from PIL import Image
            import io
            arr = np.asarray(Image.open(io.BytesIO(shot)).convert("RGB"))
            self.calls.append(system_band)
            self.last_som_image = arr
            out = []
            for color, (name, _bbox, _center) in markers.items():
                mask = np.all(arr == np.asarray(color, dtype=np.uint8), axis=-1)
                yy, xx = np.where(mask)
                if not len(xx):
                    continue
                x0, x1 = int(xx.min()), int(xx.max()) + 1
                y0, y1 = int(yy.min()), int(yy.max()) + 1
                out.append(VisualElement(
                    id=len(out), name=name,
                    bbox_xywh=[x0, y0, x1 - x0, y1 - y0],
                    center=[(x0 + x1) // 2, (y0 + y1) // 2],
                    el_type="icon", interactive=True,
                    category="navigation", source="synthetic"))
            return out

    engine = object.__new__(VisualTraversalEngine)
    engine.perception = MarkerPerception()
    engine.STITCH_TILE_OVERLAP_PX = 80
    elements, _som, calls = engine._perceive_tiled(
        res, vs.encode_png(image), cap=650)
    names = {e.name for e in elements}
    failures = []
    leaked = sorted(name for name in names if name.startswith("system_"))
    if leaked:
        failures.append(f"system UI leaked from tiled perception: {leaked}")
    missing_apps = sorted({f"app_{i}" for i in range(n_frames)} - names)
    if missing_apps:
        failures.append(f"real app markers were over-filtered: {missing_apps}")
    if "none" not in engine.perception.calls:
        failures.append(
            f"fixture did not exercise a middle tile: {engine.perception.calls}")
    if calls != len(engine.perception.calls) or calls < 3:
        failures.append(
            f"unexpected tile call accounting: returned={calls}, "
            f"seen={engine.perception.calls}")

    if failures:
        print("FAIL:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"PASS: calls={engine.perception.calls}; middle tile emitted 0 system "
          f"elements and preserved {sorted(names)}.")
    return 0


if __name__ == "__main__":
    rc = main()
    rc |= test_element_anchored_offset()
    rc |= test_dynamic_android_system_bands()
    rc |= test_tiled_system_band_provenance_filter()
    sys.exit(rc)
