"""Offline regression for click rebinding, state-growth and graph-quality gates."""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.graph_lint import (
    check_edge_quality,
    check_run_status,
    check_runtime_unreachable_flags,
)
from gui_rewalk.src.core.graph.state_graph import StateGraph
from gui_rewalk.src.core.visual_traversal.region_registry import RegionRegistry
from gui_rewalk.src.core.visual_traversal.visual_agents import ExplorationMemory
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


class _Debug:
    enabled = False

    def record_event(self, *_args, **_kwargs):
        return None


class _Perception:
    def __init__(self, elements, refreshed=None):
        self.elements = elements
        self.refreshed = refreshed if refreshed is not None else elements
        self.calls = []
        self.last_surface_kind = "page"
        self.last_window_xywh = None

    def detect_and_name(self, _shot, force_refresh=False):
        self.calls.append(bool(force_refresh))
        return self.refreshed if force_refresh else self.elements

    def _get_ocr_reader(self):
        raise AssertionError("OCR must not authorize a click")


class _Reviewer:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def review(self, som, elements):
        assert som is not None
        self.calls.append([(element.id, list(element.center))
                           for element in elements])
        return self.results.pop(0)


def _bare_engine() -> VisualTraversalEngine:
    eng = object.__new__(VisualTraversalEngine)
    eng._visited_uids = set()
    eng._explored_groups = set()
    eng._click_failures = {}
    eng.region_registry = RegionRegistry()
    eng.mem = ExplorationMemory()
    eng.review_debug = _Debug()
    return eng


def _frame(width=400, height=240):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def test_qwen_center_is_only_click_coordinate() -> None:
    eng = _bare_engine()
    fresh = VisualElement(
        0, "Displays", [130, 90, 80, 60], [170, 120],
        el_type="link", category="navigation")
    eng.perception = _Perception([fresh])
    eng.reviewer = _Reviewer([
        {"wrong": [], "missing": [], "duplicate": [], "ok": True},
    ])
    stored = VisualElement(
        3, "Displays", [10, 10, 20, 20], [20, 20],
        el_type="link", category="navigation")
    stored._template = object()

    assert eng._live_center_for(
        stored, {"screenshot": _frame()}) == [170, 120]
    assert eng.perception.calls == [False]
    assert eng.reviewer.calls == [[(0, [170, 120])]]


def test_reviewer_wrong_retries_one_fresh_grounding() -> None:
    eng = _bare_engine()
    first = VisualElement(
        0, "Displays", [70, 50, 80, 40], [110, 70],
        el_type="link", category="navigation")
    corrected = VisualElement(
        0, "Displays", [190, 130, 80, 40], [230, 150],
        el_type="link", category="navigation")
    eng.perception = _Perception([first], refreshed=[corrected])
    eng.reviewer = _Reviewer([
        {"wrong": [0], "missing": [], "duplicate": [], "ok": False},
        {"wrong": [], "missing": [], "duplicate": [], "ok": True},
    ])
    stored = VisualElement(
        7, "Displays", [60, 45, 80, 40], [100, 65],
        el_type="link", category="navigation")

    assert eng._live_center_for(
        stored, {"screenshot": _frame()}) == [230, 150]
    assert eng.perception.calls == [False, True]
    assert eng.reviewer.calls == [
        [(0, [110, 70])],
        [(0, [230, 150])],
    ]


def test_reviewer_second_rejection_fails_closed() -> None:
    eng = _bare_engine()
    first = VisualElement(
        0, "Displays", [70, 50, 80, 40], [110, 70],
        el_type="link", category="navigation")
    second = VisualElement(
        0, "Displays", [75, 55, 80, 40], [115, 75],
        el_type="link", category="navigation")
    eng.perception = _Perception([first], refreshed=[second])
    eng.reviewer = _Reviewer([
        {"wrong": [0], "missing": [], "duplicate": [], "ok": False},
        {"wrong": [], "missing": [], "duplicate": [[0, 1]], "ok": False},
    ])
    stored = VisualElement(
        7, "Displays", [60, 45, 80, 40], [100, 65],
        el_type="link", category="navigation")

    assert eng._live_center_for(stored, {"screenshot": _frame()}) is None
    assert eng.perception.calls == [False, True]

def test_live_noninteractive_reclassification_removes_stale_capability() -> None:
    eng = _bare_engine()
    stored = VisualElement(
        10, "Information icon", [54, 90, 76, 77], [92, 128],
        el_type="icon", interactive=True, category="navigation", uid="info")
    stored._template = None
    fresh = VisualElement(
        13, "Information icon", [54, 90, 76, 77], [92, 128],
        el_type="icon", interactive=False, category="display")
    eng.perception = _Perception([fresh])
    eng._state_data = {"page": {
        "elements": [stored], "page_name": "Pair device",
        "page_id": "pair", "variant_id": "default",
        "observed_facts": {}, "visible_capabilities": ["info"],
    }}
    eng.graph = StateGraph("settings")
    eng.graph.add_state(
        "page", [stored.to_dict()], "page.png", "settings",
        page_id="pair", variant_id="default",
        visible_capabilities=["info"],
    )
    eng.graph.register_capability_candidates("page", [{
        "capability_id": "info", "page_id": "pair",
        "source_elements": [{
            "state_id": "page", "variant_id": "default",
            "element_id": "10", "element_uid": "info",
            "element_label": "Information icon",
        }],
    }])

    assert eng._live_center_for(stored, {"screenshot": b"frame"}) is None
    assert eng._retire_live_noninteractive_reclassification("page", stored)
    assert stored.interactive is False and stored.category == "display"
    assert eng.graph.graph.nodes["page"]["elements"][0]["interactive"] is False
    assert "info" not in eng.graph.capabilities
    assert eng.graph.graph.nodes["page"]["visible_capabilities"] == []
    assert eng._unvisited_candidates("page") == []


def test_stateful_live_rebind_prefers_compact_same_key_widget() -> None:
    eng = _bare_engine()
    stored = VisualElement(
        5, "Allow notification dot", [0, 100, 1080, 134], [540, 167],
        el_type="switch", interactive=True, category="navigation",
        stateful=True, state_key="allow_notification_dot", state_value="on",
        effect_scope="function_set", reversible=True, risk="none")
    stored._template = None
    label = VisualElement(
        14, "Allow notification dot", [50, 100, 700, 120], [400, 160],
        el_type="text", interactive=False, category="display")
    coarse = VisualElement(
        15, "Allow notification dot", [0, 100, 1080, 134], [540, 167],
        el_type="switch", interactive=True, category="navigation",
        stateful=True, state_key="allow_notification_dot", state_value="on",
        effect_scope="function_set", reversible=True, risk="none")
    compact = VisualElement(
        16, "Notification switch", [875, 110, 173, 115], [961, 167],
        el_type="switch", interactive=True, category="navigation",
        stateful=True, state_key="allow_notification_dot", state_value="on",
        effect_scope="function_set", reversible=True, risk="none")
    eng.perception = _Perception([label, coarse, compact])

    assert eng._live_center_for(
        stored, {"screenshot": b"frame"}) == [961, 167]
    assert stored.bbox_xywh == compact.bbox_xywh
    assert stored.center == compact.center


def test_revisit_topup_merges_physical_uid_and_static_correction() -> None:
    stale = VisualElement(
        10, "Information icon", [54, 90, 76, 77], [92, 128],
        el_type="icon", interactive=True, category="navigation", uid="info")
    corrected = VisualElement(
        13, "Information", [55, 91, 76, 77], [93, 129],
        el_type="icon", interactive=False, category="display", uid="info")
    score = VisualTraversalEngine._topup_match_score(stale, corrected)
    assert score is not None
    assert VisualTraversalEngine._merge_topup_observation(stale, corrected)
    assert stale.id == 10 and stale.uid == "info"
    assert stale.interactive is False and stale.category == "display"
    assert stale.visited is True

    # Appearance UIDs alone do not collapse identical icons in different rows.
    other_row = VisualElement(
        14, "Information", [55, 491, 76, 77], [93, 529],
        el_type="icon", interactive=False, category="display", uid="info")
    assert VisualTraversalEngine._topup_match_score(stale, other_row) is None


def test_revisit_topup_prefers_compact_stateful_alias() -> None:
    row = VisualElement(
        5, "Allow notification dot", [0, 100, 1080, 134], [540, 167],
        el_type="switch", interactive=True, category="navigation",
        stateful=True, state_key="allow_notification_dot", state_value="on",
        effect_scope="function_set", reversible=True, risk="none", uid="row")
    compact = VisualElement(
        16, "Notification switch", [875, 110, 173, 115], [961, 167],
        el_type="switch", interactive=True, category="navigation",
        stateful=True, state_key="allow_notification_dot", state_value="on",
        effect_scope="function_set", reversible=True, risk="none", uid="switch")
    assert VisualTraversalEngine._topup_match_score(row, compact) is not None
    assert not VisualTraversalEngine._merge_topup_observation(row, compact)
    assert row.id == 5 and row.uid == "row"
    assert row.bbox_xywh == compact.bbox_xywh
    assert row.center == compact.center


def test_data_controls_are_node_local() -> None:
    eng = _bare_engine()
    toggle = VisualElement(
        0, "Videos", [10, 10, 80, 20], [50, 20], el_type="checkbox",
        category="navigation", uid="toggle")
    tab = VisualElement(
        1, "Bookmarks", [100, 10, 80, 20], [140, 20], el_type="tab",
        category="navigation", uid="tab")
    eng._state_data = {"s": {"elements": [toggle, tab],
                              "is_system_dialog": False}}
    assert [e.name for e in eng._unvisited_candidates("s")] == [
        "Videos", "Bookmarks"]
    assert not toggle.visited


def test_failed_click_is_not_shared_coverage() -> None:
    eng = _bare_engine()
    rid, _ = eng.region_registry.register(
        "nav_sidebar", ["Power", "Displays"], node_id="s")
    elem = VisualElement(
        0, "Displays", [0, 0, 10, 10], [5, 5], el_type="link",
        category="navigation", uid="u", region="nav_sidebar", region_id=rid)
    assert eng._record_click_failure("s", elem, "not_confirmed") == 1
    assert not elem.visited
    assert not eng.region_registry.is_clicked(rid, "Displays")
    assert eng._record_click_failure("s", elem, "not_confirmed") == 2
    assert not elem.visited
    assert not eng.region_registry.is_clicked(rid, "Displays")
    assert eng._record_click_failure("s", elem, "not_confirmed") == 3
    assert elem.visited
    assert not eng.region_registry.is_clicked(rid, "Displays")


def test_graph_schema_and_linter() -> None:
    graph = StateGraph("setting")
    nav = {"id": 1, "uid": "u", "name": "Displays", "category": "navigation",
           "el_type": "link", "back": False, "visited": True, "region": ""}
    graph.add_state("a", [nav], "a.png", "setting", page_name="Network")
    graph.add_state("b", [], "b.png", "setting", page_name="Displays",
                    action_path_from_root=[{"action_type": "CLICK"}])
    graph.add_transition(
        "a", "b", {"action_type": "CLICK"}, element_id="1",
        element_label="Displays", effect_verdict="transitioned_consistent",
        effect_note="landed on Displays", landing_verified=True,
        target_page_name="Displays")
    edge = graph.graph.edges["a", "b"]
    assert edge["landing_verified"] is True
    assert graph.graph.nodes["b"]["page_name"] == "Displays"

    bad = {
        "stop_reason": "max_states",
        "nodes": [
            {"id": "a", "action_path_from_root": [], "elements": [nav]},
            {"id": "b", "action_path_from_root": [{}], "elements": [],
             "unreachable": True},
        ],
        "edges": [
            {"source": "a", "target": "a", "element_id": "1",
             "element_label": "����", "region": "", "landing_verified": None},
        ],
    }
    codes = {x["code"] for x in (
        check_run_status(bad)
        + check_runtime_unreachable_flags(bad)
        + check_edge_quality(bad))}
    assert {"incomplete_run", "flagged_unreachable", "garbled_edge_label",
            "nav_edges_missing_region", "unverified_navigation_edges",
            "self_loop_rate"} <= codes


def main() -> int:
    test_qwen_center_is_only_click_coordinate()
    test_reviewer_wrong_retries_one_fresh_grounding()
    test_reviewer_second_rejection_fails_closed()
    test_live_noninteractive_reclassification_removes_stale_capability()
    test_stateful_live_rebind_prefers_compact_same_key_widget()
    test_revisit_topup_merges_physical_uid_and_static_correction()
    test_revisit_topup_prefers_compact_stateful_alias()
    test_data_controls_are_node_local()
    test_failed_click_is_not_shared_coverage()
    test_graph_schema_and_linter()
    print("PASS: reviewed Qwen rebind + bounded state growth + transactional coverage + lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
