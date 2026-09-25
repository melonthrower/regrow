"""Offline regression for the capability-driven frontier gate.

The production scheduler is allowed to execute only ``category=navigation`` or
``category=nav`` candidates.  ``shallow``/``display``/unknown items remain
inventory, even when they happen to be button-like or marked stateful.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


class _Memory:
    def is_explored(self, _name: str) -> bool:
        return False

    def is_explored_in_state(self, _state_id: str, _name: str) -> bool:
        return False


class _Regions:
    def shared_button_names(self):
        return frozenset()

    def is_clicked(self, _region_id: str, _name: str) -> bool:
        return False


def _element(eid: int, name: str, category: str, *, el_type: str = "button",
             stateful: bool = False, effect_scope: str = "",
             reversible: bool | None = None, risk: str = "",
             state_value: str = "", region: str = "",
             group: str = "") -> VisualElement:
    return VisualElement(
        eid,
        name,
        [eid * 20, 0, 20, 20],
        [eid * 20 + 10, 10],
        el_type=el_type,
        interactive=True,
        category=category,
        region=region,
        group=group,
        uid=f"uid-{eid}",
        stateful=stateful,
        state_key="feature" if stateful else "",
        state_value=state_value,
        effect_scope=effect_scope,
        reversible=reversible,
        risk=risk,
    )


def _engine(elements) -> VisualTraversalEngine:
    engine = object.__new__(VisualTraversalEngine)
    engine._state_data = {"settings": {"elements": list(elements)}}
    engine._visited_uids = set()
    engine._explored_groups = set()
    engine._abnormal_buttons = set()
    engine.region_registry = _Regions()
    engine.mem = _Memory()
    engine.router = type(
        "Router", (), {"has_direct_edge": lambda *_args: False})()
    engine.graph = type("Graph", (), {"records": []})()
    engine.review_debug = type(
        "Debug", (), {"enabled": False, "record_event": lambda *a, **k: None}
    )()
    return engine


def test_frontier_leaves_category_interpretation_to_explorer() -> None:
    navigation = _element(1, "Create", "navigation")
    nav_alias = _element(2, "Open", "nav")
    shallow_button = _element(3, "Sunday", "shallow")
    display_row = _element(4, "Version", "display", el_type="text")
    unknown_stateful = _element(
        5,
        "Advanced toggle",
        "",
        el_type="switch",
        stateful=True,
        effect_scope="function_set",
        reversible=True,
        risk="none",
        state_value="off",
    )

    engine = _engine([navigation, nav_alias, shallow_button, display_row,
                      unknown_stateful])
    assert VisualTraversalEngine._unvisited_candidates(
        engine, "settings") == [unknown_stateful]
    unknown_stateful.exploration_status = "complete"
    assert VisualTraversalEngine._unvisited_candidates(
        engine, "settings") == [navigation, nav_alias, shallow_button]
    assert display_row.exploration_status == "semantic_only"


def test_frontier_prioritizes_one_safe_stateful_axis() -> None:
    safe_toggle = _element(
        7,
        "Show advanced controls",
        "shallow",
        el_type="switch",
        stateful=True,
        effect_scope="function_set",
        reversible=True,
        risk="none",
        state_value="off",
    )
    navigation_toggle = _element(
        8,
        "Show advanced controls",
        "navigation",
        el_type="switch",
        stateful=True,
        effect_scope="function_set",
        reversible=True,
        risk="none",
        state_value="off",
    )

    engine = _engine([safe_toggle, navigation_toggle])
    assert VisualTraversalEngine._unvisited_candidates(
        engine, "settings") == [safe_toggle]


def test_peer_navigation_group_does_not_collapse_sibling_destinations() -> None:
    alarm = _element(
        20, "Alarm", "navigation", region="primary_navigation",
        group="bottom_nav")
    clock = _element(
        21, "Clock", "navigation", region="primary_navigation",
        group="bottom_nav")
    bedtime = _element(
        22, "Bedtime", "navigation", region="primary_navigation",
        group="bottom_nav")
    engine = _engine([alarm, clock, bedtime])

    assert VisualTraversalEngine._unvisited_candidates(engine, "settings") == [
        alarm, clock, bedtime,
    ]

    # A persisted legacy group ledger must not prune peer destinations either.
    engine._explored_groups.add(("settings", "bottom_nav"))
    assert VisualTraversalEngine._unvisited_candidates(engine, "settings") == [
        alarm, clock, bedtime,
    ]


def main() -> None:
    tests = [
        test_only_navigation_categories_enter_the_frontier,
        test_stateful_function_set_is_not_promoted_without_navigation_category,
        test_peer_navigation_group_does_not_collapse_sibling_destinations,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS capability-driven frontier")


if __name__ == "__main__":
    main()
