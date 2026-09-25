"""Offline regression for bounded source-local click failures."""

from __future__ import annotations

from types import SimpleNamespace

from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _element(name: str) -> VisualElement:
    return VisualElement(
        id=7,
        name=name,
        bbox_xywh=[10, 10, 40, 20],
        center=[30, 20],
        el_type="link",
        interactive=True,
        category="navigation",
        uid=f"uid-{name.lower()}",
        region="nav_sidebar",
        region_id="r-nav",
        source="region_inventory",
        action_label="e0",
    )


def _engine() -> VisualTraversalEngine:
    engine = object.__new__(VisualTraversalEngine)
    engine._click_failures = {}
    engine._click_failure_history = {}
    engine._targeting_corrections = {}
    engine._last_live_rebind_observation = None
    engine._abnormal_buttons = set()
    engine._visited_uids = set()
    abnormal_buttons = []
    engine.graph = SimpleNamespace(
        abnormal_buttons=abnormal_buttons,
        transitions=[],
        record_abnormal_button=lambda **payload: abnormal_buttons.append(payload),
    )
    engine.region_registry = SimpleNamespace(clicked=set())
    engine.mem = SimpleNamespace(explored=[])
    engine.review_debug = SimpleNamespace(
        record_event=lambda *_args, **_kwargs: None)
    return engine


def test_third_click_failure_is_terminal_but_not_shared_coverage() -> None:
    elem = _element("Unstable target")
    engine = _engine()

    assert engine._record_click_failure(
        "root", elem, "visible_target_not_confirmed") == 1
    assert not elem.visited
    assert engine.graph.abnormal_buttons == []

    assert engine._record_click_failure(
        "root", elem, "visible_target_not_confirmed") == 2
    assert not elem.visited
    assert engine.graph.abnormal_buttons == []

    assert engine._record_click_failure(
        "root", elem, "visible_target_not_confirmed") == 3

    assert elem.visited
    assert elem.uid not in engine._visited_uids
    assert engine.region_registry.clicked == set()
    assert engine.mem.explored == []
    assert engine.graph.transitions == []
    assert len(engine.graph.abnormal_buttons) == 1
    terminal = engine.graph.abnormal_buttons[0]
    assert terminal["state_id"] == "root"
    assert terminal["element_uid"] == elem.uid
    assert terminal["element_name"] == elem.name
    assert terminal["reason"] == "target_rebind_failed"
    assert "without claiming shared coverage" in terminal["detail"]
    assert terminal["evidence"] == {
        "kind": "bounded_local_failure",
        "attempts_used": 3,
        "failure_kind": "visible_target_not_confirmed",
    }
    assert engine._click_failure_history[
        ("root", elem.uid or elem.name)
    ] == {"visible_target_not_confirmed": 3}
    assert engine._abnormal_button_key("root", elem) in engine._abnormal_buttons


def test_scroll_map_not_confirmed_is_a_local_rebind_failure() -> None:
    elem = _element("Below-fold target")
    engine = _engine()

    for _ in range(3):
        engine._record_click_failure(
            "root", elem, "scroll_map_target_not_confirmed")

    assert engine.graph.abnormal_buttons[0]["reason"] == "target_rebind_failed"
    assert engine.region_registry.clicked == set()


def test_invalid_geometry_is_sent_to_the_next_grounding_attempt() -> None:
    elem = _element("Menu icon")
    engine = _engine()
    engine._last_live_rebind_observation = {
        "status": "target_not_found",
        "diagnostic": {
            "status": "invalid_geometry",
            "reason": "outside normalized_1000 range or bbox",
            "bbox_1000": [1113, 196, 1145, 258],
            "click_point_1000": [1129, 227],
        },
    }

    assert engine._record_click_failure(
        "root", elem, "visible_target_not_confirmed") == 1
    correction = engine._targeting_correction_for("root", elem)

    assert "outside normalized_1000 range or bbox" in correction
    assert "bbox_1000=[1113, 196, 1145, 258]" in correction
    assert "click_point_1000=[1129, 227]" in correction
    assert "within 0..1000" in correction
    assert "not source-image pixel coordinates" in correction
