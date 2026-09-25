"""Offline contracts for the engine-independent frontier policy."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from gui_rewalk.src.core.visual_traversal.navigation import frontier
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


class _Element:
    def __init__(self, name: str, category: str, *, selected: bool = False,
                 region: str = "content"):
        self.name = name
        self.category = category
        self.selected = selected
        self.el_type = "button"
        self.visited = False
        self.interactive = True
        self.enabled = True
        self.requires_permission = False
        self.blocked_reason = ""
        self.stateful = False
        self.back = False
        self.group = ""
        self.region_id = "r1"
        self.region = region

    def is_safe_stateful_surface(self) -> bool:
        return False

    def is_dangerous(self) -> bool:
        return False


class _Regions:
    def __init__(self):
        self.clicked = []

    def shared_button_names(self):
        return frozenset()

    def mark_clicked(self, region_id, name):
        self.clicked.append((region_id, name))

    def is_clicked(self, region_id, name):
        return False


class _Memory:
    def is_explored(self, name):
        return False

    def is_explored_in_state(self, state_id, name):
        return False


class _Debug:
    enabled = True

    def __init__(self):
        self.records = []

    def record_candidate_breakdown(self, state_id, *, kept, dropped):
        self.records.append((state_id, kept, dropped))


def test_frontier_has_no_engine_back_import() -> None:
    source = inspect.getsource(frontier)
    assert "visual_engine" not in source
    assert "self." not in source


def test_frontier_does_not_filter_on_semantic_attributes() -> None:
    nav = _Element("Network", "navigation")
    inventory = _Element("Theme", "shallow")
    selected = _Element("Current", "navigation", selected=True)
    regions = _Regions()
    debug = _Debug()
    context = frontier.FrontierContext(
        state_data={"state": {"elements": [nav, inventory, selected]}},
        region_registry=regions,
        memory=_Memory(),
        explored_groups=set(),
        debug_sink=debug,
        stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda state_id, element: False,
        stateful_scope_candidates=lambda state_id, elements: elements,
        is_generic_name=lambda name: False,
        is_chrome_name=lambda name: False,
    )

    assert frontier.unvisited_candidates("state", context) == [
        nav, inventory, selected]
    assert inventory.visited is False
    assert selected.visited is False
    assert regions.clicked == [], (
        "being selected identifies the current page; it is not click coverage")
    assert debug.records[-1][1] == ["Network", "Theme", "Current"]


def test_frontier_applies_stateful_transaction_scope_last() -> None:
    existing = _Element("Existing destination", "navigation")
    exposed = _Element("New advanced action", "navigation")
    calls = []

    def scope(state_id, elements):
        calls.append((state_id, list(elements)))
        return [exposed]

    context = frontier.FrontierContext(
        state_data={"settings": {"elements": [existing, exposed]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=_Debug(), stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=scope,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
    )

    assert frontier.unvisited_candidates("settings", context) == [exposed]
    assert calls == [("settings", [existing, exposed])]


def test_current_frontier_keeps_registered_top_viewport_targets() -> None:
    current = _Element("Minute dial (00-55)", "shallow")
    stale = _Element("Hour dial (1-12)", "shallow")
    duplicate_a = _Element("Preset", "shallow")
    duplicate_b = _Element("Preset", "shallow")
    live_current = _Element("Minute dial (00-55)", "shallow")
    live_duplicate_a = _Element("Preset", "shallow")
    live_duplicate_b = _Element("Preset", "shallow")
    debug = _Debug()
    context = frontier.FrontierContext(
        state_data={"time": {"elements": [
            current, stale, duplicate_a, duplicate_b]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=debug, stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
        live_observation_state_id="time",
        live_observation_elements=[
            live_current, live_duplicate_a, live_duplicate_b],
    )

    assert frontier.unvisited_candidates("time", context) == [
        current, stale, duplicate_a, duplicate_b]
    assert stale.visited is False
    assert duplicate_a.visited is False
    assert duplicate_b.visited is False
    assert not any(
        reason == "absent_from_live_inventory"
        for _name, reason in debug.records[-1][2])


def test_current_frontier_keeps_offscreen_target_only_with_complete_region_map() -> None:
    below_fold = _Element("Below-fold action", "navigation")
    below_fold.scroll_steps = 1
    debug = _Debug()

    def candidates(has_map):
        below_fold.visited = False
        context = frontier.FrontierContext(
            state_data={"settings": {"elements": [below_fold]}},
            region_registry=_Regions(), memory=_Memory(),
            explored_groups=set(), debug_sink=debug,
            stateful_discover_only=False,
            record_abnormal_button=lambda *args, **kwargs: None,
            is_abnormal_button=lambda *_args: False,
            stateful_scope_candidates=lambda _state, elements: elements,
            is_generic_name=lambda _name: False,
            is_chrome_name=lambda _name: False,
            live_observation_state_id="settings",
            live_observation_elements=[],
            has_complete_region_map=lambda state_id, element: has_map,
        )
        return frontier.unvisited_candidates("settings", context)

    assert candidates(False) == []
    assert candidates(True) == [below_fold]


def test_noncurrent_frontier_also_rejects_offscreen_target_without_map() -> None:
    below_fold = _Element("Below-fold action", "navigation")
    below_fold.scroll_steps = 1
    context = frontier.FrontierContext(
        state_data={"settings": {"elements": [below_fold]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=_Debug(), stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
        live_observation_state_id="another-state",
        live_observation_elements=[],
        has_complete_region_map=lambda _state_id, _element: False,
    )

    assert frontier.unvisited_candidates("settings", context) == []


def test_complete_region_map_requires_ledger_and_persisted_image() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    element = _Element("Below-fold action", "navigation")
    element.region_id = "r25"
    engine.graph = SimpleNamespace(scroll_ledger={
        "scope": {
            "region_id": "r25",
            "classification": "scrollable",
            "complete": True,
            "state_ids": ["settings"],
        },
    })
    payloads = {}
    engine.writer = SimpleNamespace(
        load_region_image=lambda state_id, region_id: payloads.get(
            (state_id, region_id)))

    assert not engine._has_complete_region_map_target("settings", element)
    payloads[("settings", "r25")] = b"long-region-map"
    assert engine._has_complete_region_map_target("settings", element)
    engine.graph.scroll_ledger["scope"]["complete"] = False
    assert not engine._has_complete_region_map_target("settings", element)


def test_current_frontier_uses_live_availability_without_terminalizing() -> None:
    durable = _Element("Dependent option", "navigation")
    live = _Element("Dependent option", "navigation")
    live.enabled = False
    abnormal = []
    debug = _Debug()
    context = frontier.FrontierContext(
        state_data={"settings": {"elements": [durable]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=debug, stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: abnormal.append(args),
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
        live_observation_state_id="settings",
        live_observation_elements=[live],
    )

    assert frontier.unvisited_candidates("settings", context) == []
    assert durable.visited is False
    assert getattr(durable, "exploration_status", "") != "terminal"
    assert abnormal == []
    assert ("Dependent option", "disabled_in_live_inventory") in (
        debug.records[-1][2])

    live.enabled = True
    durable.enabled = False
    assert frontier.unvisited_candidates("settings", context) == [durable]


def test_noncurrent_frontier_keeps_durable_pending_occurrences() -> None:
    durable = _Element("Hour dial (1-12)", "shallow")
    context = frontier.FrontierContext(
        state_data={"time": {"elements": [durable]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=_Debug(), stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
        live_observation_state_id="another-state",
        live_observation_elements=[],
    )

    assert frontier.unvisited_candidates("time", context) == [durable]


def test_shared_peer_navigation_stays_local_frontier_until_source_edge_exists() -> None:
    bedtime = _Element("Bedtime", "navigation", region="tab_bar")
    regions = _Regions()
    regions.is_clicked = lambda _rid, _name: True
    regions.shared_button_names = lambda: frozenset({"bedtime"})
    memory = _Memory()
    memory.is_explored = lambda _name: True

    def candidates(has_direct):
        bedtime.visited = False
        return frontier.unvisited_candidates(
            "alarm",
            frontier.FrontierContext(
                state_data={"alarm": {"elements": [bedtime]}},
                region_registry=regions,
                memory=memory,
                explored_groups=set(),
                debug_sink=_Debug(),
                stateful_discover_only=False,
                record_abnormal_button=lambda *args, **kwargs: None,
                is_abnormal_button=lambda _state, _element: False,
                stateful_scope_candidates=lambda _state, elements: elements,
                is_generic_name=lambda _name: False,
                is_chrome_name=lambda _name: False,
                has_direct_edge=lambda *_args: has_direct,
            ),
        )

    assert candidates(False) == [bedtime]
    assert candidates(True) == [bedtime]
    assert bedtime.visited is False


def test_shared_host_relative_action_stays_local_until_source_edge_exists() -> None:
    more = _Element("More options", "navigation", region="top_app_bar")
    regions = _Regions()
    regions.is_clicked = lambda _rid, _name: True
    regions.shared_button_names = lambda: frozenset({"more options"})
    memory = _Memory()
    memory.is_explored = lambda _name: True

    def candidates(has_direct):
        more.visited = False
        return frontier.unvisited_candidates(
            "documents",
            frontier.FrontierContext(
                state_data={"documents": {"elements": [more]}},
                region_registry=regions,
                memory=memory,
                explored_groups=set(),
                debug_sink=_Debug(),
                stateful_discover_only=False,
                record_abnormal_button=lambda *args, **kwargs: None,
                is_abnormal_button=lambda _state, _element: False,
                stateful_scope_candidates=lambda _state, elements: elements,
                is_generic_name=lambda _name: False,
                is_chrome_name=lambda _name: True,
                has_direct_edge=lambda *_args: has_direct,
            ),
        )

    assert candidates(False) == [more]
    assert candidates(True) == [more]
    assert more.visited is False


def test_frontier_closes_button_only_after_terminal_exploration_status() -> None:
    button = _Element("More options", "navigation", region="top_app_bar")
    button.exploration_status = "complete"
    context = frontier.FrontierContext(
        state_data={"home": {"elements": [button]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=_Debug(), stateful_discover_only=False,
        record_abnormal_button=lambda *args, **kwargs: None,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
    )

    assert frontier.unvisited_candidates("home", context) == []
    assert button.visited is True


def test_frontier_closes_display_and_danger_but_continues_safe_dialog_work() -> None:
    display = VisualElement(
        0, "Explanation", [0, 0, 10, 10], [5, 5],
        interactive=False, category="display", risk="none")
    cancel = VisualElement(
        1, "Cancel", [10, 0, 10, 10], [15, 5],
        category="navigation", risk="none")
    confirm = VisualElement(
        2, "Confirm action", [20, 0, 10, 10], [25, 5],
        category="dangerous", risk="destructive")
    blocked = []

    def record_abnormal(state_id, element, reason, detail, action=None):
        element.visited = True
        element.exploration_status = "terminal"
        blocked.append((state_id, element.name, reason, action))

    context = frontier.FrontierContext(
        state_data={"dialog": {"elements": [display, cancel, confirm]}},
        region_registry=_Regions(), memory=_Memory(), explored_groups=set(),
        debug_sink=_Debug(), stateful_discover_only=False,
        record_abnormal_button=record_abnormal,
        is_abnormal_button=lambda *_args: False,
        stateful_scope_candidates=lambda _state, elements: elements,
        is_generic_name=lambda _name: False,
        is_chrome_name=lambda _name: False,
    )

    assert frontier.unvisited_candidates("dialog", context) == [cancel]
    assert display.exploration_status == "semantic_only"
    assert display.exploration_reason == "read-only display element"
    assert blocked == [("dialog", "Confirm action", "blocked", None)]
    assert cancel.visited is False
