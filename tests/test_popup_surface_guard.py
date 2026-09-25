"""Offline regression for transient Android popup/menu active surfaces.

The test intentionally models the Notifications sort menu failure: a short
option popup is displayed above a long application list, then a same-named label
is still visible on the background after the popup disappears.  The traversal
must neither scroll the popup nor click that background look-alike.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.graph.state_graph import StateGraph  # noqa: E402
from gui_rewalk.src.core.visual_traversal.visual_engine import (  # noqa: E402
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import (  # noqa: E402
    ACTIVE_SURFACE_PAGE,
    ACTIVE_SURFACE_POPUP_MENU,
    VisualElement,
    VisualPerception,
    _parse_vlm_json,
)
from gui_rewalk.src.core.visual_traversal.visual_resume import (  # noqa: E402
    element_from_dict,
)


SCREEN = (1080, 1920)
POPUP = [560, 190, 450, 390]


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", SCREEN, "white").save(buf, format="PNG")
    return buf.getvalue()


def _changed_png_bytes() -> bytes:
    rng = np.random.RandomState(42)
    pixels = rng.randint(0, 256, (SCREEN[1], SCREEN[0], 3), dtype=np.uint8)
    image = Image.fromarray(pixels, mode="RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _element(name: str, bbox: list[int], *, surface: bool = False) -> VisualElement:
    x, y, width, height = bbox
    return VisualElement(
        id=0,
        name=name,
        bbox_xywh=list(bbox),
        center=[x + width // 2, y + height // 2],
        el_type="button",
        interactive=True,
        category="navigation",
        surface_kind=(ACTIVE_SURFACE_POPUP_MENU if surface else ""),
        surface_bbox_xywh=(list(POPUP) if surface else None),
        surface_scrollable=(False if surface else None),
    )


class _NoScrollEnv:
    def __init__(self) -> None:
        self.steps = 0

    def step(self, *_args, **_kwargs):
        self.steps += 1
        raise AssertionError("a short popup/menu must not receive a page swipe")


class _SnapshotEnv:
    def __init__(self, screenshot: bytes) -> None:
        self.screenshot = screenshot
        self.captures = 0

    def _get_obs(self):
        self.captures += 1
        return {"screenshot": self.screenshot}


class _LivePerception:
    def __init__(self, elements, *, popup: bool, bbox=None) -> None:
        self.elements = list(elements)
        self.popup = popup
        self.bbox = list(bbox or POPUP)
        self.last_is_modal = popup
        self.last_surface_kind = (
            ACTIVE_SURFACE_POPUP_MENU if popup else ACTIVE_SURFACE_PAGE)
        self.last_window_xywh = list(self.bbox if popup else [0, 0, *SCREEN])
        self.last_surface_scrollable = False if popup else None

    def detect_and_name(self, _shot):
        self.last_is_modal = self.popup
        self.last_surface_kind = (
            ACTIVE_SURFACE_POPUP_MENU if self.popup else ACTIVE_SURFACE_PAGE)
        self.last_window_xywh = list(
            self.bbox if self.popup else [0, 0, *SCREEN])
        return list(self.elements)


def test_parser_promotes_structured_popup_to_active_overlay() -> None:
    raw = json.dumps({
        "window": [0, 0, 1000, 1000],
        # Model drift seen in practice: kind is correct but is_modal is omitted or
        # false.  A popup claim must still deactivate the background.
        "is_modal": False,
        "surface_kind": "dropdown",
        "active_surface": [520, 100, 980, 360],
        "surface_scrollable": False,
        "elements": [{"name": "Most frequent"}],
    })
    parsed, meta = _parse_vlm_json(raw)
    assert parsed and parsed[0]["name"] == "Most frequent"
    assert meta["is_modal"] is True
    assert meta["surface_kind"] == ACTIVE_SURFACE_POPUP_MENU
    assert meta["modal"] == meta["active_surface"]
    assert meta["surface_scrollable"] is False


def test_popup_elements_are_bound_to_active_surface() -> None:
    option = _element("Most frequent", [600, 240, 330, 80])
    background = _element("Android System", [30, 700, 1020, 130])
    perception = VisualPerception(yolo_model=None, agent=None)
    perception.use_vlm_grounding = True

    def fake_ground(self, image, _image_np, _w, _h, force_refresh=False):
        del force_refresh
        self.last_is_modal = True
        self.last_surface_kind = ACTIVE_SURFACE_POPUP_MENU
        self.last_surface_scrollable = False
        self.last_window_xywh = list(POPUP)
        self.last_som_image = np.asarray(image)
        return [option, background]

    perception._ground_with_vlm = MethodType(fake_ground, perception)
    kept = perception.detect_and_name(_png_bytes())
    assert [element.name for element in kept] == ["Most frequent"]
    assert kept[0].surface_kind == ACTIVE_SURFACE_POPUP_MENU
    assert kept[0].surface_bbox_xywh == POPUP
    assert kept[0].surface_scrollable is False
    assert [element.name for element in perception.last_all_elements] == [
        "Most frequent"]
    restored = element_from_dict(kept[0].to_dict(), VisualElement)
    assert restored.surface_kind == ACTIVE_SURFACE_POPUP_MENU
    assert restored.surface_bbox_xywh == POPUP
    assert restored.surface_scrollable is False


def test_short_popup_is_static_and_receives_zero_swipes() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = True
    engine._stitch_node_image = True
    engine._scroll_node_local_functions = []
    engine.perception = type("P", (), {
        "last_is_modal": True,
        "last_surface_kind": ACTIVE_SURFACE_POPUP_MENU,
        "last_surface_scrollable": False,
        "last_window_xywh": list(POPUP),
        "last_node_local_functions": [],
    })()
    engine.env = _NoScrollEnv()
    engine.graph = StateGraph("settings")
    option = _element("Most frequent", [600, 240, 330, 80], surface=True)
    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [option], state_id="sort-popup")
    assert result == [option]
    assert engine.env.steps == 0
    assert engine._last_scroll_frames == []
    scope = engine.graph.scroll_ledger["state:sort-popup:page"]
    assert scope["classification"] == "static"
    assert scope["termination"] == "static"
    assert scope["top_restored"] is True
    assert scope["steps"] == 0
    assert scope["complete"] is True


def test_explicit_non_scrollable_page_receives_zero_swipes() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = True
    engine._stitch_node_image = False
    engine._scroll_node_local_functions = []
    engine.perception = type("P", (), {
        "use_semantic_inventory": True,
        "last_is_modal": False,
        "last_surface_kind": ACTIVE_SURFACE_PAGE,
        "last_surface_scrollable": False,
        "last_page_name": "screen saver",
        "last_node_local_functions": [],
    })()
    engine.env = _NoScrollEnv()
    engine.graph = StateGraph("clock")
    time_display = _element("09:46", [240, 600, 600, 240])
    time_display.surface_kind = ACTIVE_SURFACE_PAGE
    time_display.surface_scrollable = False

    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [time_display], state_id="screen-saver")

    assert result == [time_display]
    assert engine.env.steps == 0
    scope = engine.graph.scroll_ledger["state:screen-saver:page"]
    assert scope["classification"] == "static"
    assert scope["termination"] == "static"
    assert scope["top_restored"] is True


def test_unknown_semantic_scrollability_receives_zero_swipes() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = True
    engine._stitch_node_image = False
    engine._scroll_node_local_functions = []
    engine.perception = type("P", (), {
        "use_semantic_inventory": True,
        "last_is_modal": False,
        "last_surface_kind": ACTIVE_SURFACE_PAGE,
        "last_surface_scrollable": None,
        "last_page_name": "Clock",
        "last_node_local_functions": [],
    })()
    engine.env = _NoScrollEnv()
    engine.graph = StateGraph("clock")
    clock = _element("Add clock", [240, 600, 600, 240])

    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [clock], state_id="clock")

    assert result == [clock]
    assert engine.env.steps == 0


def test_semantic_scroll_registers_one_complete_surface_after_bottom(
        monkeypatch) -> None:
    class Env:
        def __init__(self):
            self.steps = 0
            self.actions = []

        def step(self, action, pause=0.0):
            del pause
            self.steps += 1
            self.actions.append(action)
            if action.get("parameters", {}).get("direction") == "up":
                return {"screenshot": _png_bytes()}
            return {"screenshot": _changed_png_bytes()}

    fresh = _element("More options", [240, 600, 600, 240])
    fresh.region_id = "local-b0"
    revealed = _element("Below-fold action", [240, 700, 600, 240])
    revealed.region_id = "local-b0"

    class Perception:
        use_semantic_inventory = True
        last_is_modal = False
        last_surface_kind = ACTIVE_SURFACE_PAGE
        last_surface_scrollable = True
        last_page_name = "Clock"
        last_node_local_functions = []
        last_semantic_blocks = [{
            "region_id": "r1", "element_names": ["More options"],
            "scrollable": True}]

        def semantic_inventory(self, _shot):
            self.last_semantic_blocks = [{
                "local_id": "b0", "scrollable": True}]
            return [fresh, revealed]

    calls = []

    def resolve(**kwargs):
        fresh.region_id = "r2"
        revealed.region_id = "r2"
        kwargs["blocks"][0]["region_id"] = "r2"
        calls.append("block")
        return {}, {"r2": b"current-crop"}

    def compare(**kwargs):
        assert kwargs["state_a"]["semantic_blocks"] == [{
            "region_id": "r1", "element_names": ["More options"],
            "scrollable": True}]
        calls.append("region")
        return {"status": "mapped"}, {"r2": "r1"}

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.state.block_identity."
        "resolve_semantic_blocks", resolve)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.state.block_identity."
        "compare_state_regions", compare)

    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = True
    engine._stitch_node_image = False
    engine._scroll_node_local_functions = []
    engine.perception = Perception()
    engine.env = Env()
    engine.focus_guard = None
    engine.graph = StateGraph("clock")
    class SamePage:
        def same_page(self, *_args):
            calls.append("page")
            return True

    engine.page_judge = SamePage()
    class Judge:
        last_raw_response = "mapped"

    engine.block_identity_judge = Judge()
    engine.region_registry = type("Regions", (), {
        "merge_semantic_concepts": lambda _self, keep, drop: (
            keep == "r1" and drop == "r2"),
    })()
    engine.writer = type("Writer", (), {
        "save_block_identity_attempt": lambda *_args, **_kwargs: None,
        "save_fullpage": lambda *_args, **_kwargs: None,
    })()
    full_source = _element("More options", [240, 600, 600, 240])
    full_source.region_id = "r2"
    full_revealed = _element("Below-fold action", [240, 700, 600, 240])
    full_revealed.region_id = "r2"

    def build_complete_surface(runtime, _top):
        runtime._last_scroll_frames = []
        runtime._last_scroll_offsets = []
        return [full_source, full_revealed], b"full-surface", None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.grounding.stitch."
        "StitchRuntime._build_stitched_node", build_complete_surface)
    # Initial registration has allocated the State id but has not populated its
    # durable Region table when the first scroll audit begins.
    engine._state_data = {"clock": {}}
    engine._pending_transition = None
    engine._frame_phash = lambda shot: (
        0 if shot == _png_bytes() else 10)
    engine._scroll_back_to_top = lambda *_args: True
    source = _element("More options", [240, 600, 600, 240])
    source.region_id = "r1"

    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [source], state_id="clock")

    assert result == [full_source, full_revealed]
    assert calls == ["page", "block", "region", "block", "region"]
    assert sum(
        action.get("parameters", {}).get("direction") == "down"
        for action in engine.env.actions) == 3


def test_semantic_stitch_reuses_existing_inventory_and_target_grounding(
        monkeypatch) -> None:
    from gui_rewalk.src.core.visual_traversal.grounding.stitch import (
        StitchContext, StitchRuntime,
    )

    calls = []
    top = _element("Top action", [0, 0, 0, 0])
    bottom = _element("Bottom action", [0, 0, 0, 0])

    class Perception:
        use_semantic_inventory = True

        def semantic_inventory(self, _shot):
            calls.append("inventory")
            return [top, bottom]

        def ground_target(self, _shot, target, force_refresh=False):
            assert force_refresh is False
            calls.append(target.name)
            if target is top:
                return _element(target.name, [100, 100, 200, 80])
            return _element(target.name, [100, 850, 200, 80])

    result = SimpleNamespace(
        image=np.zeros((1200, 800, 3), dtype=np.uint8),
        composite_y_to_scroll=lambda y: (
            (0, y) if y < 600 else (1, y - 600)),
    )
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.grounding.stitch.stitch_frames",
        lambda *_args, **_kwargs: result)
    runtime = StitchRuntime(StitchContext(
        perception=Perception(), is_touch=False,
        screen_wh=lambda _obs: (800, 600),
        frames=[_png_bytes(), _changed_png_bytes()],
        offsets=[None, None],
    ))

    built = runtime._build_stitched_node(_png_bytes())

    assert built is not None
    elements, _composite, _som = built
    assert calls == ["inventory", "Top action", "Bottom action"]
    assert [element.scroll_steps for element in elements] == [0, 1]


def test_explicit_non_scrollable_desktop_page_receives_zero_wheel_events() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = False
    engine._stitch_node_image = False
    engine._scroll_node_local_functions = []
    engine.perception = type("P", (), {
        "use_semantic_inventory": True,
        "last_is_modal": False,
        "last_surface_kind": ACTIVE_SURFACE_PAGE,
        "last_surface_scrollable": False,
        "last_page_name": "Timer",
        "last_node_local_functions": [],
    })()
    engine.env = _NoScrollEnv()
    engine.graph = StateGraph("clocks")
    timer = _element("Timer", [240, 100, 600, 240])
    timer.surface_kind = ACTIVE_SURFACE_PAGE
    timer.surface_scrollable = False

    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [timer], state_id="timer")

    assert result == [timer]
    assert engine.env.steps == 0
    scope = engine.graph.scroll_ledger["state:timer:page"]
    assert scope["classification"] == "static"
    assert scope["termination"] == "static"
    assert scope["top_restored"] is True


def test_scroll_discards_frame_when_semantic_page_identity_changes() -> None:
    class ShiftEnv:
        def __init__(self) -> None:
            self.steps = []

        def step(self, action, pause=0.0):
            del pause
            self.steps.append(action)
            return {"screenshot": _changed_png_bytes()}

    class ShiftPerception:
        use_semantic_inventory = True
        last_is_modal = False
        last_surface_kind = ACTIVE_SURFACE_PAGE
        last_surface_scrollable = True
        last_page_name = "screen saver"
        last_node_local_functions = []

        def semantic_inventory(self, _shot):
            self.last_page_name = "Clock"
            return [_element("Add alarm", [900, 1500, 120, 120])]

    engine = object.__new__(VisualTraversalEngine)
    engine._is_touch = True
    engine._stitch_node_image = False
    engine._scroll_node_local_functions = []
    engine.perception = ShiftPerception()
    engine.env = ShiftEnv()
    engine.focus_guard = None
    engine.graph = StateGraph("clock")
    engine.page_judge = SimpleNamespace(same_page=lambda *_args: False)
    source = _element("09:46", [240, 600, 600, 240])
    source.surface_kind = ACTIVE_SURFACE_PAGE
    source.surface_scrollable = True

    result = engine._scroll_aggregate(
        {"screenshot": _png_bytes()}, [source], state_id="screen-saver")

    assert result == [source]
    assert len(engine.env.steps) == 1, "must not swipe the destination page"
    scope = engine.graph.scroll_ledger["state:screen-saver:page"]
    assert scope["termination"] == "surface_changed"
    assert scope["top_restored"] is False
    assert scope["complete"] is False
    assert "full-screenshot VLM" in scope["detail"]


def test_click_requires_same_live_overlay_not_background_label() -> None:
    shot = _png_bytes()
    stored = _element("Most frequent", [600, 240, 330, 80], surface=True)
    stored._template = None

    # The option moved slightly but remains on the same live popup: rebinding is
    # allowed and uses the current popup coordinate.
    live_option = _element("Most frequent", [610, 250, 320, 80], surface=True)
    engine = object.__new__(VisualTraversalEngine)
    engine.env = _SnapshotEnv(shot)
    engine.perception = _LivePerception([live_option], popup=True)
    center = engine._live_center_for(stored, {"screenshot": shot})
    assert center == live_option.center
    assert engine.env.captures == 1, "overlay guard must capture a fresh frame"

    # Popup disappeared.  The page still exposes the current sort label and a
    # background list row, but neither may satisfy an overlay-bound selector.
    background_label = _element("Most frequent", [560, 100, 450, 100])
    background_row = _element("Android System", [20, 700, 1040, 130])
    engine.perception = _LivePerception(
        [background_label, background_row], popup=False)
    assert engine._live_center_for(stored, {"screenshot": shot}) is None
    assert engine.env.captures == 2
    assert engine._last_live_rebind_observation["status"] == "surface_missing"

    # A different popup at another anchor is not the original active surface.
    engine.perception = _LivePerception(
        [live_option], popup=True, bbox=[20, 1100, 450, 390])
    assert engine._live_center_for(stored, {"screenshot": shot}) is None
    assert engine.env.captures == 3


def main() -> int:
    test_parser_promotes_structured_popup_to_active_overlay()
    test_popup_elements_are_bound_to_active_surface()
    test_short_popup_is_static_and_receives_zero_swipes()
    test_click_requires_same_live_overlay_not_background_label()
    print("PASS popup surface isolation + zero-scroll + live-overlay click guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
