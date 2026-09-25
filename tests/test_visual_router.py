"""Offline contract tests for :mod:`visual_router`.

No VM, VLM, network, or filesystem fixtures are used.  The tests exercise the
router with an in-memory NetworkX graph and tiny region/execution stubs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.visual_router import (
    RouterClickResult, VisualRouter,
)
from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter
from gui_rewalk.src.core.graph.state_graph import StateGraph


class _Graph:
    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def edge(self, src: str, dst: str, label: str, region: str = "content") -> None:
        self.graph.add_edge(
            src, dst, element_label=label, region=region,
            routing_verified=True, landing_verified=True)


class _Regions:
    def __init__(self, *regions: SimpleNamespace) -> None:
        self._regions = {f"r{i}": region for i, region in enumerate(regions)}


def _region(role: str, names, seen_on) -> SimpleNamespace:
    return SimpleNamespace(role=role, names=set(names), seen_on=set(seen_on))


def _router(graph: _Graph, *, regions=None, identify=None, click=None,
            execute=None, back=None,
            reset=None, budget=3, quarantined=None, state_data=None,
            recorder=None, register_landing=None,
            attempt_recorder=None) -> VisualRouter:
    return VisualRouter(
        graph=graph,
        region_registry=regions or _Regions(),
        state_data=state_data or {},
        identify_fn=identify or (lambda obs: obs),
        click_button_fn=click or (lambda _name, _region, obs: obs),
        execute_action_fn=execute,
        back_fn=back,
        hard_reset_root_fn=reset,
        verified_transition_fn=recorder,
        attempt_outcome_fn=attempt_recorder,
        register_landing_fn=register_landing,
        replan_budget=budget,
        quarantined_edges=quarantined,
    )


def test_clock_tab_target_is_inferred_from_selected_peer_and_verified_on_use() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["bedtime", "alarm"])
    regions = _Regions(_region(
        "tab_bar", {"Bedtime", "Alarm"}, {"bedtime", "alarm"}))
    state_data = {
        "bedtime": {"elements": [
            {"name": "Bedtime", "region_id": "r0", "selected": True}]},
        "alarm": {"elements": [
            {"name": "Alarm", "region_id": "r0", "selected": True}]},
    }
    persisted = []

    router = _router(
        graph, regions=regions, state_data=state_data,
        identify=lambda obs: obs,
        click=lambda *_args: RouterClickResult.action_dispatched("bedtime"),
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
    )

    edge = router.node_out_edges("alarm")["bedtime"]
    assert edge["dst"] == "bedtime"
    assert edge["provenance"] == "peer_inferred"
    ok, obs = router.route_to("alarm", "alarm", "bedtime")
    assert ok is True and obs == "bedtime"
    assert persisted[0][:2] == ("alarm", "bedtime")
    assert persisted[0][2]["effect_kind"] == "peer_navigation"


def test_natural_back_ascent_is_persisted_and_return_edge_replays_back() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["detail", "parent"])
    persisted = []
    router = _router(
        graph,
        identify=lambda obs: obs,
        back=lambda _obs: "parent",
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )
    ok, obs = router.route_to("detail", "detail", "parent")
    assert ok is True and obs == "parent"
    assert persisted == [(
        "detail", "parent",
        {"name": "__NAVIGATE_BACK__", "region": "", "source_region_id": "",
         "effect_kind": "return", "provenance": "natural_return",
         "virtual_action": True})]

    graph.graph.add_edge(
        "detail", "parent", element_label="", region="",
        action={"action_type": "BACK"}, effect_kind="return",
        routing_verified=True, landing_verified=True)
    click_calls = []
    replay = _router(
        graph,
        identify=lambda obs: obs,
        click=lambda *_args: click_calls.append(True),
        back=lambda _obs: "parent",
    )
    assert replay.route_to("detail", "detail", "parent") == (True, "parent")
    assert click_calls == []


def test_legacy_back_control_edge_is_normalized_as_return() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["detail", "parent"])
    graph.graph.add_edge(
        "detail", "parent",
        element_id="7", element_label="Close", region="dialog_actions",
        action={"action_type": "CLICK"},
        effect_kind="", routing_verified=True, landing_verified=True)
    router = _router(
        graph,
        state_data={"detail": {"elements": [{
            "id": 7, "name": "Close", "back": True,
        }]}},
    )

    edge = router.node_out_edges("detail")["close"]
    assert edge["effect_kind"] == "return_via_control"
    assert router.plan_route("detail", "parent")[0][
        "effect_kind"] == "return_via_control"


def test_verified_click_to_live_entry_source_is_contextual_return() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["detail", "parent"])
    graph.graph.add_edge(
        "detail", "parent",
        element_id="7", element_label="Unclassified control",
        region="app_bar", action={"action_type": "CLICK"},
        effect_kind="", routing_verified=True, landing_verified=True)
    router = _router(
        graph,
        state_data={"detail": {"elements": [{
            "id": 7, "name": "Unclassified control", "back": False,
        }]}})

    assert router.node_out_edges("detail")[
        "unclassified control"]["effect_kind"] == "forward"
    contextual = router.node_out_edges("detail", "parent")[
        "unclassified control"]
    assert contextual["dst"] == "parent"
    assert contextual["effect_kind"] == "return_via_control"
    assert router.plan_route(
        "detail", "parent", arrival_source_id="parent")[0][
            "effect_kind"] == "return_via_control"


def test_verified_click_to_live_stack_ancestor_is_contextual_return() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["dialog", "flow", "host"])
    graph.graph.add_edge(
        "dialog", "host",
        element_id="7", element_label="Unclassified control",
        region="dialog_actions", action={"action_type": "CLICK"},
        effect_kind="", routing_verified=True, landing_verified=True)
    router = _router(
        graph,
        state_data={"dialog": {"elements": [{
            "id": 7, "name": "Unclassified control", "back": False,
        }]}})
    router.note_arrival("flow", "host")
    router.note_arrival("dialog", "flow")

    contextual = router.node_out_edges("dialog", "flow")[
        "unclassified control"]

    assert contextual["dst"] == "host"
    assert contextual["effect_kind"] == "return_via_control"
    assert router.plan_route(
        "dialog", "host", arrival_source_id="flow")[0][
            "effect_kind"] == "return_via_control"


def test_nested_return_restores_parent_context_and_reuses_verified_return() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["people", "messages", "conversations"])
    graph.action_edges = [
        {
            "source": "messages", "target": "people",
            "element_id": "7", "element_label": "Header control",
            "region": "app_bar", "action": {"action_type": "CLICK"},
            "effect_kind": "", "routing_verified": True,
        },
        {
            "source": "messages", "target": "people",
            "element_label": "",
            "action": {"action_type": "NAVIGATE_BACK"},
            "effect_kind": "return_native_action", "routing_verified": True,
        },
    ]
    router = _router(
        graph,
        state_data={"messages": {"elements": [{
            "id": 7, "name": "Header control", "back": False,
        }]}})

    router.note_arrival("messages", "people")
    router.note_arrival("conversations", "messages")
    router.note_arrival(
        "messages", "conversations",
        {"effect_kind": "return_native_action",
         "action": {"action_type": "NAVIGATE_BACK"}},
    )

    assert router._arrival_source("messages") == "people"
    edge = router.node_out_edges("messages")["header control"]
    assert edge["dst"] == "people"
    assert edge["effect_kind"] == "return_via_control"


def test_live_parent_landing_is_return_even_when_control_metadata_omits_it() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["root", "host", "overlay"])
    router = _router(graph)

    router.note_arrival("host", "root")
    router.note_arrival("overlay", "host")
    router.note_arrival(
        "host", "overlay",
        {"action": {"action_type": "CLICK"}},
    )

    assert router._arrival_source("host") == "root"
    assert "overlay" not in router._live_entry_sources


def test_engine_persists_virtual_back_without_element_or_region() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    graph = StateGraph("demo")
    graph.add_state("detail", [], "detail.png", "demo")
    graph.add_state("parent", [], "parent.png", "demo")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {"parent": {"page_name": "Parent"}}
    engine._maybe_save = lambda: None

    engine._record_router_verified_transition(
        "detail", "parent", {
            "name": "__NAVIGATE_BACK__",
            "region": "",
            "effect_kind": "return",
            "virtual_action": True,
        })

    edge = graph.graph["detail"]["parent"]
    assert edge["element_label"] == ""
    assert edge["region"] == ""
    assert edge["action"]["action_type"] == "BACK"
    assert edge["action"]["selector"]["virtual_action"] == "navigate_back"
    assert edge["action"]["parameters"] == {
        "scope": "platform_navigation", "virtual": True}


def test_verified_return_control_commits_button_coverage() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    graph = StateGraph("demo")
    graph.add_state("target", [], "target.png", "demo")
    graph.add_state("source", [], "source.png", "demo")
    control = SimpleNamespace(
        id=0, name="Chats", region_id="tabs", region="primary_navigation")
    committed = []
    persisted = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {
        "target": {"elements": [control]},
        "source": {"page_name": "Chats"},
    }
    engine._commit_explored = lambda state, element, seed: committed.append(
        (state, element, seed))
    engine._persist_exploration_state = lambda state: persisted.append(state)
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._maybe_save = lambda: None

    engine._record_router_verified_transition(
        "target", "source", {
            "name": "Chats", "region": "primary_navigation",
            "source_region_id": "tabs", "element_id": 0,
            "effect_kind": "return_via_control",
            "explore_on_verify": True,
        })

    assert committed == [("target", control, False)]
    assert control.exploration_status == "complete"
    assert persisted == ["target"]
    assert graph.graph["target"]["source"]["element_label"] == "Chats"
    assert graph.graph["target"]["source"]["element_id"] == "0"


def test_verified_reverse_control_commits_unique_label_without_element_id() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    graph = StateGraph("demo")
    graph.add_state("timer", [], "timer.png", "demo")
    graph.add_state("world", [], "world.png", "demo")
    control = SimpleNamespace(
        id=2, name="World", region_id="tabs", region="navigation")
    committed = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {
        "timer": {"elements": [control]},
        "world": {"page_name": "World"},
    }
    engine._commit_explored = lambda state, element, seed: committed.append(
        (state, element, seed))
    engine._persist_exploration_state = lambda _state: None
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._maybe_save = lambda: None

    engine._record_router_verified_transition(
        "timer", "world", {
            "name": "World", "element_id": "",
            "effect_kind": "peer_navigation",
            "explore_on_verify": True,
        })

    assert committed == [("timer", control, False)]
    assert control.exploration_status == "complete"


def test_verified_native_return_closes_source_local_back_occurrence() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    graph = StateGraph("demo")
    graph.add_state("pair", [], "pair.png", "demo")
    graph.add_state("connected", [], "connected.png", "demo")
    back = SimpleNamespace(
        id=0, uid="", name="Back", region_id="r6", region="",
        exploration_status="", exploration_reason="", visited=False,
    )
    persisted = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {
        "pair": {"elements": [back]},
        "connected": {"page_name": "Connected devices"},
    }
    engine._click_failures = {}
    engine._persist_exploration_state = lambda state: persisted.append(state)
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._maybe_save = lambda: None

    engine._record_router_verified_transition(
        "pair", "connected", {
            "name": "Back", "region": "",
            "source_region_id": "r6", "element_id": 0,
            "effect_kind": "return_native_action",
            "explore_on_verify": True,
            "action": {"action_type": "NAVIGATE_BACK"},
        })

    assert back.exploration_status == "complete"
    assert back.visited is True
    assert persisted == ["pair"]


def test_router_does_not_replay_historical_scroll_steps() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    target = SimpleNamespace(
        name="View weekly summary", region_id="actions", region="actions",
        scroll_steps=2)
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine._state_data = {"activity": {"elements": [target]}}
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._scroll_to_steps = lambda _steps: (_ for _ in ()).throw(
        AssertionError("historical scroll depth must not be replayed"))
    engine._live_center_for = lambda _target, _obs: None
    engine.env = SimpleNamespace(step=lambda action, pause=0: {
        "screenshot": b"clicked", "action": action})
    engine._settle_enabled = False
    engine._ensure_on_app = lambda obs: (obs, False, True)

    result = engine._router_click_button(
        "activity", "View weekly summary", "actions", "actions",
        {"screenshot": b"top"})
    assert result.status == "not_attempted"
    assert result.reason == "targeting_failed"


def test_router_external_hop_recovered_by_back_is_not_a_transition() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target"])
    graph.edge("source", "target", "Open companion")
    persisted = []
    back_calls = []
    router = _router(
        graph,
        identify=lambda obs: obs,
        click=lambda *_args: RouterClickResult(
            "off_app_recovered", "source", "different_app"),
        back=lambda obs: back_calls.append(obs) or obs,
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )

    result = router.route_to("source", "source", "target")

    assert result.arrived is False
    assert result.failure_kind == "off_app_recovered"
    assert result.action_dispatched is True
    assert back_calls == []
    assert persisted == []


def test_router_excludes_actions_with_durable_terminal_evidence() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target"])
    graph.edge("source", "target", "Open companion")
    graph.abnormal_buttons = [{
        "state_id": "source",
        "element_id": "",
        "element_name": "Open companion",
        "region_id": "",
        "reason": "external_app",
    }]
    router = _router(graph)

    assert "open companion" not in router.node_out_edges("source")


def test_router_native_click_does_not_replay_historical_scroll_steps() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    refreshed = SimpleNamespace(
        id=5, name="View weekly summary", region_id="actions",
        region="actions", scroll_steps=0)
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine._state_data = {"activity": {"elements": [refreshed]}}
    engine._scroll_to_steps = lambda _steps: (_ for _ in ()).throw(
        AssertionError("historical scroll depth must not be replayed"))
    engine._live_center_for = lambda _target, _obs: None
    engine.env = SimpleNamespace(step=lambda action, pause=0: {
        "screenshot": b"clicked", "action": action})
    engine._settle_enabled = False

    result = engine._router_execute_action({
        "source_id": "activity", "source_region_id": "actions",
        "name": "View weekly summary",
        "region": "actions",
        "action": {"action_type": "CLICK", "parameters": {}},
    }, {"screenshot": b"top"})

    assert result.status == "not_attempted"
    assert result.reason == "targeting_failed"


def _reverse_probe_engine_graph() -> tuple[VisualTraversalEngine, StateGraph]:
    graph = StateGraph("clock")
    for state_id, page_name in (
            ("world", "World"), ("alarms", "Alarms"),
            ("settings", "Settings")):
        graph.add_state(
            state_id, [], f"{state_id}.png", "clock",
            page_name=page_name, page_id=f"page-{state_id}",
            variant_id="default")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {
        state_id: {"page_name": page_name, "elements": []}
        for state_id, page_name in (
            ("world", "World"), ("alarms", "Alarms"),
            ("settings", "Settings"))
    }
    engine._maybe_save = lambda: None
    engine._commit_explored = lambda *_args, **_kwargs: None
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    return engine, graph


def test_action_attempt_screenshots_use_readable_attempt_directory(
        tmp_path) -> None:
    writer = ArtifactWriter(str(tmp_path))

    before_path = writer.save_action_attempt_screenshot(
        source_state_id="a1b966d7dbd8",
        page_description="Privacy",
        region_id="r97",
        region_description="Privacy settings",
        element_id="7",
        element_description="Notifications on lock screen",
        attempt_id="android_settings:185",
        phase="before",
        screenshot_bytes=b"before-frame",
    )
    after_path = writer.save_action_attempt_screenshot(
        source_state_id="a1b966d7dbd8",
        page_description="Privacy",
        region_id="r97",
        region_description="Privacy settings",
        element_id="7",
        element_description="Notifications on lock screen",
        attempt_id="android_settings:185",
        phase="after",
        screenshot_bytes=b"after-frame",
    )

    assert before_path == (
        "action_attempts/privacy__state_a1b966d7/"
        "privacy_settings__region_r97/"
        "notifications_on_lock_screen__element_7/"
        "android_settings_185/before.png")
    assert after_path.endswith("/android_settings_185/after.png")
    assert (tmp_path / Path(before_path)).read_bytes() == b"before-frame"
    assert (tmp_path / Path(after_path)).read_bytes() == b"after-frame"


def test_action_attempt_screenshot_paths_are_attached_to_graph_attempt(
        tmp_path) -> None:
    engine, graph = _reverse_probe_engine_graph()
    engine.writer = ArtifactWriter(str(tmp_path))
    engine._state_data["world"].update({
        "semantic_blocks": [{
            "region_id": "tabs",
            "role": "Primary navigation",
        }],
    })
    event_index = graph.record_action_event(
        source="world",
        action={"action_type": "CLICK", "selector": {
            "element_label": "Alarms",
            "region_id": "tabs",
        }},
        element_id="3",
        element_label="Alarms",
    )

    engine._save_action_attempt_screenshot(
        event_index, "before", b"world-before")
    engine._save_action_attempt_screenshot(
        event_index, "after", b"alarms-after")

    screenshots = graph.action_attempt(event_index)["evidence"]["screenshots"]
    assert set(screenshots) == {"before", "after"}
    assert (tmp_path / Path(screenshots["before"])).read_bytes() == \
        b"world-before"
    assert (tmp_path / Path(screenshots["after"])).read_bytes() == \
        b"alarms-after"


def test_reverse_probe_identity_prefers_forward_source_frame() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    comparisons = []
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine.page_judge = SimpleNamespace(
        compare_page=lambda source, current: (
            comparisons.append((source, current)) or True))
    engine.identity_resolver = SimpleNamespace(
        resolve=lambda *_args, **_kwargs: pytest.fail(
            "ordinary identity must not run after the source frame matches"))
    engine._router_diagnostic = lambda *_args, **_kwargs: None

    landed = engine._router_identify(
        {"screenshot": b"returned-privacy"}, source_id="dialog", step={
            "provenance": "reverse_probe",
            "intended_target": "privacy",
            "_source_reference_screenshot": b"privacy-before-click",
        })

    assert landed == "privacy"
    assert comparisons == [
        (b"privacy-before-click", b"returned-privacy")]


def test_reverse_probe_identity_falls_back_after_source_frame_rejection() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine.page_judge = SimpleNamespace(
        compare_page=lambda _source, _current: False)
    engine.identity_resolver = SimpleNamespace(resolve=lambda *_args, **_kwargs:
        SimpleNamespace(
            known=True, state_id="settings", verdict="known",
            reason="matched another registered page", exact=False))
    engine._router_diagnostic = lambda *_args, **_kwargs: None

    landed = engine._router_identify(
        {"screenshot": b"settings"}, source_id="dialog", step={
            "provenance": "reverse_probe",
            "intended_target": "privacy",
            "_source_reference_screenshot": b"privacy-before-click",
        })

    assert landed == "settings"


@pytest.mark.parametrize(
    ("actual_target", "expected_status"),
    [
        ("world", "verified_to_source"),
        ("settings", "landed_elsewhere"),
    ],
)
def test_reverse_probe_reuses_pre_dispatch_attempt_for_actual_landing(
        actual_target, expected_status) -> None:
    engine, graph = _reverse_probe_engine_graph()
    probe_index = graph.record_action_event(
        source="alarms", target="",
        action={"action_type": "CLICK"},
        element_label="顶部导航栏中的 World 标签",
        semantic_description="reverse probe",
        outcome="attempted",
        evidence={"reverse_probe": {
            "status": "attempted",
            "trigger_forward_attempt_id": "clock:1",
            "intended_target": "world",
        }},
    )

    engine._record_router_verified_transition(
        "alarms", actual_target, {
            "source_id": "alarms",
            "name": "顶部导航栏中的 World 标签",
            "dst": actual_target,
            "predicted_target": "world",
            "prediction_match": actual_target == "world",
            "provenance": (
                "reverse_probe" if actual_target == "world"
                else "live_corrected"),
            "effect_kind": "peer_navigation",
            "action": {"action_type": "CLICK"},
            "probe_event_index": probe_index,
            "trigger_forward_attempt_id": "clock:1",
            "intended_target": "world",
        })

    attempts = graph.transition_events
    assert len(attempts) == 1
    assert attempts[0]["target"] == actual_target
    assert attempts[0]["committed"] is True
    assert attempts[0]["landing_verified"] is True
    assert attempts[0]["evidence"]["reverse_probe"]["status"] == \
        expected_status
    assert graph.routing_graph.has_edge("alarms", actual_target)
    if actual_target != "world":
        assert not graph.routing_graph.has_edge("alarms", "world")


def test_reverse_probe_grounding_failure_updates_existing_attempt() -> None:
    engine, graph = _reverse_probe_engine_graph()
    probe_index = graph.record_action_event(
        source="alarms", target="", action={"action_type": "CLICK"},
        element_label="World", outcome="attempted",
        evidence={"reverse_probe": {
            "status": "attempted", "intended_target": "world"}})
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine._live_center_for = lambda *_args: None

    result = engine._router_execute_action({
        "source_id": "alarms",
        "name": "World",
        "action": {"action_type": "CLICK"},
        "probe_event_index": probe_index,
        "intended_target": "world",
    }, {"screenshot": b"alarms"})

    attempt = graph.action_attempt(probe_index)
    assert result.status == "not_attempted"
    assert attempt["outcome"] == "grounding_failed"
    assert attempt["committed"] is False
    assert attempt["landing_verified"] is False
    assert not graph.routing_graph.has_edge("alarms", "world")


def test_reverse_probe_dispatch_unknown_updates_existing_attempt() -> None:
    engine, graph = _reverse_probe_engine_graph()
    probe_index = graph.record_action_event(
        source="alarms", target="",
        action={"action_type": "PRESS", "parameters": {"key": "esc"}},
        outcome="attempted",
        evidence={"reverse_probe": {
            "status": "attempted", "intended_target": "world"}})
    engine.env = SimpleNamespace(step=lambda *_args, **_kwargs: (
        _ for _ in ()).throw(RuntimeError("transport uncertain")))
    engine._settle_enabled = False

    result = engine._router_execute_action({
        "source_id": "alarms",
        "name": "__NATIVE_ACTION__return",
        "action": {"action_type": "PRESS", "parameters": {"key": "esc"}},
        "probe_event_index": probe_index,
        "intended_target": "world",
    }, {"screenshot": b"alarms"})

    attempt = graph.action_attempt(probe_index)
    assert result.status == "dispatch_unknown"
    assert attempt["outcome"] == "dispatch_unknown"
    assert attempt["committed"] is False
    assert attempt["landing_verified"] is False
    assert not graph.routing_graph.has_edge("alarms", "world")


def test_reverse_probe_saves_dispatched_before_and_after_frames(tmp_path) -> None:
    engine, graph = _reverse_probe_engine_graph()
    engine.writer = ArtifactWriter(str(tmp_path))
    probe_index = graph.record_action_event(
        source="alarms", target="",
        action={"action_type": "PRESS", "parameters": {"key": "esc"}},
        outcome="attempted",
        evidence={"reverse_probe": {
            "status": "attempted", "intended_target": "world"}})
    engine.env = SimpleNamespace(step=lambda *_args, **_kwargs: {
        "screenshot": b"world-returned"})
    engine._settle_enabled = False

    result = engine._router_execute_action({
        "source_id": "alarms",
        "name": "__NATIVE_ACTION__return",
        "action": {"action_type": "PRESS", "parameters": {"key": "esc"}},
        "probe_event_index": probe_index,
        "intended_target": "world",
    }, {"screenshot": b"alarms-before-return"})

    screenshots = graph.action_attempt(
        probe_index)["evidence"]["screenshots"]
    assert result.status == "action_dispatched"
    assert (tmp_path / Path(screenshots["before"])).read_bytes() == \
        b"alarms-before-return"
    assert (tmp_path / Path(screenshots["after"])).read_bytes() == \
        b"world-returned"


def test_direct_router_no_effect_keeps_attempt_and_frames(tmp_path) -> None:
    graph = StateGraph("calendar")
    for state_id, page_name in (
            ("dialog", "New Event"), ("calendar", "Calendar")):
        graph.add_state(
            state_id, [], f"{state_id}.png", "calendar",
            page_name=page_name, page_id=f"page-{state_id}",
            variant_id="default")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine.writer = ArtifactWriter(str(tmp_path))
    engine._state_data = {
        "dialog": {
            "page_name": "New Event",
            "elements": [],
            "semantic_blocks": [],
        },
        "calendar": {
            "page_name": "Calendar",
            "elements": [],
            "semantic_blocks": [],
        },
    }
    engine._live_center_for = lambda *_args: (30, 40)
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._settle_enabled = False
    engine._maybe_save = lambda: None
    engine.env = SimpleNamespace(step=lambda *_args, **_kwargs: {
        "screenshot": b"dialog-after"})
    router = VisualRouter(
        graph=graph,
        region_registry=_Regions(),
        state_data=engine._state_data,
        identify_fn=lambda *_args, **_kwargs: "dialog",
        click_button_fn=lambda *_args, **_kwargs:
        pytest.fail("semantic action must use execute_action_fn"),
        execute_action_fn=engine._router_execute_action,
        verified_transition_fn=engine._record_router_verified_transition,
        attempt_outcome_fn=engine._record_router_attempt_outcome,
    )
    step = {
        "source_id": "dialog",
        "dst": "calendar",
        "name": "Cancel",
        "region": "",
        "source_region_id": "",
        "provenance": "direct_verified",
        "effect_kind": "peer_navigation",
        "action": {"action_type": "CLICK"},
    }

    ok, _obs, landed, status = router._run_route(
        [step], {"screenshot": b"dialog-before"})

    assert ok is False
    assert landed == "dialog"
    assert status == "no_effect"
    assert len(graph.transition_events) == 1
    attempt = graph.transition_events[0]
    assert attempt["target"] == "dialog"
    assert attempt["outcome"] == "no_effect"
    assert attempt["committed"] is False
    assert attempt["landing_verified"] is True
    screenshots = attempt["evidence"]["screenshots"]
    assert (tmp_path / Path(screenshots["before"])).read_bytes() == \
        b"dialog-before"
    assert (tmp_path / Path(screenshots["after"])).read_bytes() == \
        b"dialog-after"


def test_direct_router_success_reuses_pre_dispatch_attempt(tmp_path) -> None:
    graph = StateGraph("calendar")
    for state_id, page_name in (
            ("dialog", "New Event"), ("calendar", "Calendar")):
        graph.add_state(
            state_id, [], f"{state_id}.png", "calendar",
            page_name=page_name, page_id=f"page-{state_id}",
            variant_id="default")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine.writer = ArtifactWriter(str(tmp_path))
    engine._state_data = {
        "dialog": {
            "page_name": "New Event",
            "elements": [],
            "semantic_blocks": [],
        },
        "calendar": {
            "page_name": "Calendar",
            "elements": [],
            "semantic_blocks": [],
        },
    }
    engine._live_center_for = lambda *_args: (30, 40)
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._settle_enabled = False
    engine._maybe_save = lambda: None
    engine._commit_explored = lambda *_args, **_kwargs: None
    engine.env = SimpleNamespace(step=lambda *_args, **_kwargs: {
        "screenshot": b"calendar-after"})
    router = VisualRouter(
        graph=graph,
        region_registry=_Regions(),
        state_data=engine._state_data,
        identify_fn=lambda *_args, **_kwargs: "calendar",
        click_button_fn=lambda *_args, **_kwargs:
        pytest.fail("semantic action must use execute_action_fn"),
        execute_action_fn=engine._router_execute_action,
        verified_transition_fn=engine._record_router_verified_transition,
        attempt_outcome_fn=engine._record_router_attempt_outcome,
    )
    step = {
        "source_id": "dialog",
        "dst": "calendar",
        "name": "Cancel",
        "region": "",
        "source_region_id": "",
        "provenance": "direct_verified",
        "effect_kind": "peer_navigation",
        "action": {"action_type": "CLICK"},
    }

    ok, _obs, landed, status = router._run_route(
        [step], {"screenshot": b"dialog-before"})

    assert ok is True
    assert landed == "calendar"
    assert status == "action_dispatched"
    assert len(graph.transition_events) == 1
    attempt = graph.transition_events[0]
    assert attempt["target"] == "calendar"
    assert attempt["outcome"] == "transitioned_consistent"
    assert attempt["committed"] is True
    assert set(attempt["evidence"]["screenshots"]) == {"before", "after"}


def test_reverse_probe_no_effect_stays_out_of_route_view() -> None:
    engine, graph = _reverse_probe_engine_graph()
    probe_index = graph.record_action_event(
        source="alarms", target="",
        action={"action_type": "CLICK"},
        element_label="World", outcome="attempted",
        evidence={"reverse_probe": {
            "status": "attempted", "intended_target": "world"}})

    engine._update_router_probe_attempt(
        {"probe_event_index": probe_index, "intended_target": "world"},
        status="no_effect", outcome="no_effect", target="alarms",
        detail="fresh identity remained on source",
        landing_verified=True, committed=False)

    attempt = graph.action_attempt(probe_index)
    assert attempt["target"] == "alarms"
    assert attempt["outcome"] == "no_effect"
    assert attempt["committed"] is False
    assert not graph.routing_graph.has_edge("alarms", "alarms")


def test_reverse_probe_evidence_survives_graph_save_load(tmp_path) -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _record_forward_reverse_probe,
    )

    engine, graph = _reverse_probe_engine_graph()
    event_index = graph.record_action_event(
        source="world", target="alarms",
        action={"action_type": "CLICK"},
        element_label="Alarms", outcome="transitioned_consistent",
        landing_verified=True, committed=True)
    _record_forward_reverse_probe(engine, event_index, {
        "status": "candidate_not_found",
        "intended_target": "world",
    })
    path = tmp_path / "graph.json"

    graph.save(path)
    loaded = StateGraph.load(path)

    assert loaded.action_attempt(event_index)["evidence"]["reverse_probe"] == {
        "status": "candidate_not_found",
        "intended_target": "world",
    }


def test_router_replay_uses_mapped_stable_action_not_raw_live_inventory() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    stale = SimpleNamespace(
        name="More options", region_id="old-header", region="top_bar",
        scroll_steps=0)
    fresh = SimpleNamespace(
        name="More options", region_id="new-header", region="header",
        scroll_steps=0)
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine._state_data = {"clock": {"elements": [stale]}}
    engine._last_live_observation_state_id = "clock"
    engine._last_live_observation_elements = [fresh]
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    selected = []
    engine._live_center_for = lambda target, _obs: (
        selected.append(target) or [90, 40])
    engine.env = SimpleNamespace(step=lambda action, pause=0: {
        "screenshot": b"menu", "action": action})
    engine._settle_enabled = False
    engine._ensure_on_app = lambda obs: (obs, False, True)

    result = engine._router_click_button(
        "clock", "More options", "old-header", "top_bar",
        {"screenshot": b"clock"})

    assert result.status == "action_dispatched"
    assert selected == [stale]
    assert result.observation["action"]["parameters"]["x"] == 90


def test_router_exact_frame_beats_stale_overlay_page_guess() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine.registry = SimpleNamespace(
        exact_frame_state_ids=lambda _shot: ("home",))
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine.page_judge = SimpleNamespace(
        which_page=lambda *_args, **_kwargs: pytest.fail("VLM judge called"))

    assert engine._router_identify(
        {"screenshot": b"exact-home"}, source_id="about") == "home"


def test_router_exact_page_match_is_not_rejected_by_host_source() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine.registry = SimpleNamespace(
        exact_frame_state_ids=lambda _shot: ("search",))
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._state_data = {
        "all-apps": {"page_id": "page-all-apps"},
        "storage-apps": {"page_id": "page-storage-apps"},
        "search": {
            "page_id": "page-search",
            "entry_source_page_id": "page-all-apps",
        },
    }
    engine.graph = SimpleNamespace(action_edges=[], graph=nx.DiGraph())
    engine.page_judge = SimpleNamespace(
        which_page=lambda *_args, **_kwargs: pytest.fail("VLM judge called"))

    assert engine._router_identify(
        {"screenshot": b"same-search"},
        source_id="storage-apps",
        step={"effect_kind": "forward"},
    ) == "search"
    assert engine._router_identify(
        {"screenshot": b"same-search"},
        source_id="storage-apps",
        step={"effect_kind": "return"},
    ) == "search"
    assert engine._router_identify(
        {"screenshot": b"same-search"},
        source_id="storage-apps",
        step={"effect_kind": "return_via_control"},
    ) == "search"


def test_router_page_shortlist_receives_all_registered_pages_once() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    class Perception:
        use_semantic_inventory = True
        last_surface_kind = ""
        last_page_name = ""

        def semantic_inventory(self, _shot):
            self.last_surface_kind = "page"
            self.last_page_name = "Home"
            return []

    candidate_batches = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = Perception()
    engine.registry = SimpleNamespace(_states={})
    engine._frame_phash = lambda _shot: 0
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._state_data = {
        "about": {"page_name": "About Dayline", "surface_kind": "page"},
        "home-menu": {"page_name": "Home options",
                      "surface_kind": "popup_menu"},
        "home": {"page_name": "Home", "surface_kind": "page"},
    }
    engine._node_descriptor = lambda sid: {
        "name": engine._state_data[sid]["page_name"]}
    engine.router = SimpleNamespace(
        expected_destinations=lambda *_args: ["about", "home-menu"])

    def choose(_shot, candidates, current_observation=None):
        ids = [item["sid"] for item in candidates]
        candidate_batches.append(ids)
        return "home" if "home" in ids else "NEW"

    engine.page_judge = SimpleNamespace(which_page=choose)

    assert engine._router_identify(
        {"screenshot": b"focused-home"}, source_id="about") == "home"
    assert candidate_batches == [["about", "home-menu", "home"]]


def test_router_accepts_same_page_match_as_known_landing() -> None:
    from gui_rewalk.src.core.visual_traversal.state.resolver import (
        IdentityResolution,
    )
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine.identity_resolver = SimpleNamespace(resolve=lambda *_args, **_kwargs: (
        IdentityResolution(
            "known", "stopwatch",
            "same Stopwatch page; only system time changed",
        )
    ))
    engine._state_data = {"stopwatch": {"page_name": "Stopwatch"}}
    engine._router_diagnostic = lambda *_args, **_kwargs: None

    assert engine._router_identify(
        {"screenshot": b"stopwatch with a changed system clock"},
        source_id="stopwatch",
        step={"dst": "world", "effect_kind": "return_native_action"},
    ) == "stopwatch"
def test_router_keeps_page_identity_result_when_route_expected_another_page() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    class Perception:
        use_semantic_inventory = True
        last_page_name = ""

        def semantic_inventory(self, _shot):
            self.last_page_name = "Broccoli app info"
            return []

    candidate_batches = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = Perception()
    engine.registry = SimpleNamespace(
        exact_frame_state_ids=lambda _shot: (),
        known_path=lambda sid: f"{sid}.png",
    )
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._state_data = {
        "all-apps": {"page_name": "All apps"},
        "audio": {"page_name": "Audio Recorder app info"},
        "broccoli": {"page_name": "Broccoli app info"},
    }
    engine.graph = SimpleNamespace(action_edges=[], graph=nx.DiGraph())
    engine._node_descriptor = lambda sid: {
        "name": engine._state_data[sid]["page_name"]}
    engine.router = SimpleNamespace(
        expected_destinations=lambda *_args: ["audio", "broccoli"])

    def choose(_shot, candidates, current_observation=None):
        ids = [item["sid"] for item in candidates]
        candidate_batches.append(ids)
        return "audio"

    engine.page_judge = SimpleNamespace(which_page=choose)

    assert engine._router_identify(
        {"screenshot": b"broccoli-live"},
        source_id="all-apps",
        step={"dst": "broccoli", "effect_kind": "forward"},
    ) == "audio"
    assert candidate_batches == [["audio", "broccoli", "all-apps"]]


def test_shared_region_button_destination_is_pending_and_not_routable() -> None:
    graph = _Graph()
    graph.edge("page_a", "sound", "Sound", region="sidebar")
    regions = _Regions(_region(
        "sidebar", {"Network", "Sound"}, {"page_a", "page_b"}))

    inherited = _router(graph, regions=regions).node_out_edges("page_b")

    assert inherited["sound"] == {
        "label": "Sound", "region": "sidebar", "source_id": "page_b",
        "source_region_id": "r0", "provenance": "shared_pending", "dst": None,
        "action": {"action_type": "CLICK"}}
    assert inherited["network"]["dst"] is None
    assert _router(graph, regions=regions).plan_route("page_b", "sound") is None


def test_shared_button_label_is_scoped_by_region_and_ambiguity_fails_closed() -> None:
    graph = _Graph()
    graph.edge("sidebar_page", "sidebar_target", "Open", region="sidebar")
    graph.edge("toolbar_page", "toolbar_target", "Open", region="toolbar")
    toolbar = _Regions(_region("toolbar", {"Open"}, {"third_page"}))

    inherited = _router(graph, regions=toolbar).node_out_edges("third_page")

    assert inherited["open"]["dst"] is None
    assert inherited["open"]["provenance"] == "shared_pending"

    graph.edge("other_toolbar_page", "other_target", "Open", region="toolbar")
    ambiguous = _router(graph, regions=toolbar).node_out_edges("third_page")
    assert ambiguous["open"]["dst"] is None, (
        "ambiguous shared-region labels must not inherit an arbitrary target")


def test_stable_region_id_wins_when_role_hints_are_identical() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "source_a", "target_a", element_label="Open", region="other",
        source_region_id="r0", routing_verified=True, landing_verified=True)
    graph.graph.add_edge(
        "source_b", "target_b", element_label="Open", region="other",
        source_region_id="r1", routing_verified=True, landing_verified=True)
    regions = _Regions(
        _region("other", {"Open"}, {"source_a", "page_a"}),
        _region("other", {"Open"}, {"source_b", "page_b"}),
    )

    inherited = _router(graph, regions=regions).node_out_edges("page_a")

    assert inherited["open"]["dst"] == "target_a"
    assert inherited["open"]["provenance"] == "shared_predicted"
    assert inherited["open"]["probe_required"] is True
    direct = _router(graph, regions=regions).node_out_edges("source_a")
    assert direct["open"]["dst"] == "target_a"
    assert direct["open"]["provenance"] == "direct_verified"
    assert direct["open"]["source_region_id"] == "r0"


def test_stateful_shared_control_is_not_inherited_as_a_route_hop() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "source", "source", element_id="2", element_label="Search chats",
        region="search", source_region_id="r0",
        routing_verified=True, landing_verified=True)
    regions = _Regions(_region(
        "search", {"Search chats"}, {"source", "duplicate"}))
    state_data = {
        "source": {"elements": [{
            "id": 2, "name": "Search chats", "region_id": "r0",
            "stateful": True,
        }]},
        "duplicate": {"elements": [{
            "id": 8, "name": "Search chats", "region_id": "r0",
            "stateful": True,
        }]},
    }

    inherited = _router(
        graph, regions=regions, state_data=state_data,
    ).node_out_edges("duplicate")["search chats"]

    assert inherited["dst"] is None
    assert inherited["provenance"] == "shared_pending"


def test_stateful_direct_control_is_not_exposed_as_a_route_hop() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "settings", "settings", element_id="2",
        element_label="Message notifications", region="settings",
        source_region_id="r0", routing_verified=True, landing_verified=True)
    state_data = {
        "settings": {"elements": [{
            "id": 2, "name": "Message notifications", "region_id": "r0",
            "stateful": True,
        }]},
    }

    edges = _router(graph, state_data=state_data).node_out_edges("settings")

    assert "message notifications" not in edges


def test_predicted_shared_edge_is_executable_but_live_mismatch_is_corrected() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["host_a", "host_b", "expected", "actual"])
    graph.graph.add_edge(
        "host_a", "expected", element_label="About", region="overflow",
        source_region_id="r0", routing_verified=True, landing_verified=True)
    regions = _Regions(_region(
        "overflow", {"About"}, {"host_a", "host_b"}))
    persisted = []
    router = _router(
        graph, regions=regions, budget=0,
        identify=lambda obs: obs,
        click=lambda *_args: RouterClickResult.action_dispatched("actual"),
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
    )

    result = router.route_to("host_b", "host_b", "expected")

    assert result.arrived is False
    assert result.landed_id == "actual"
    assert persisted[0][0:2] == ("host_b", "actual")
    assert persisted[0][2]["predicted_target"] == "expected"
    assert persisted[0][2]["prediction_match"] is False
    assert persisted[0][2]["provenance"] == "live_corrected"


def test_dispatched_click_that_stays_on_source_is_no_effect_not_correction() -> None:
    graph = _Graph()
    graph.edge("source", "expected", "Open")
    persisted = []
    backs = []
    router = _router(
        graph, budget=0,
        identify=lambda _obs, _source=None: "source",
        click=lambda *_args: RouterClickResult.action_dispatched("same_obs"),
        back=lambda *_args: backs.append(True) or "unexpected_obs",
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
    )

    result = router.route_to("source_obs", "source", "expected")

    assert result.arrived is False
    assert result.failure_kind == "no_effect"
    assert result.action_dispatched is True
    assert persisted == []
    assert backs == []
    assert ("source", "expected") in router._quarantined
    assert router.plan_route("source", "expected") is None


def test_same_visual_state_selects_back_target_by_arrival_context() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "about", "home", element_label="Back", region="content",
        action={"action_type": "BACK"}, effect_kind="return",
        route_contexts=["home_menu"], routing_verified=True,
        landing_verified=True)
    graph.graph.add_edge(
        "about", "documents", element_label="Back", region="content",
        action={"action_type": "BACK"}, effect_kind="return",
        route_contexts=["documents_menu"], routing_verified=True,
        landing_verified=True)
    router = _router(graph)

    assert router.node_out_edges(
        "about", "home_menu")["back"]["dst"] == "home"
    assert router.node_out_edges(
        "about", "documents_menu")["back"]["dst"] == "documents"
    assert "back" not in router.node_out_edges("about"), (
        "without entry context, conflicting verified Back targets must fail closed")


def test_first_back_from_new_entry_context_predicts_live_entry_source() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["pair", "connected", "bluetooth"])
    graph.graph.add_edge(
        "pair", "connected", element_id="1", element_label="Back",
        region="header", routing_verified=True, landing_verified=True)
    router = _router(graph, state_data={
        "pair": {"elements": [{
            "id": "1", "name": "Back", "back": True,
        }]},
        "connected": {},
        "bluetooth": {},
    })
    router.note_arrival("pair", "bluetooth")

    route = router.plan_route("pair", "bluetooth")

    assert route is not None and len(route) == 1
    assert route[0]["dst"] == "bluetooth"
    assert route[0]["route_context"] == "bluetooth"
    assert route[0]["provenance"] == "context_predicted"
    assert route[0]["probe_required"] is True


def test_router_persists_arrival_context_and_prediction_evidence() -> None:
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    graph = StateGraph("demo")
    graph.add_state("about", [], "about.png", "demo")
    graph.add_state("documents", [], "documents.png", "demo")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = graph
    engine._state_data = {"documents": {"page_name": "Documents"}}
    engine._maybe_save = lambda: None

    engine._record_router_verified_transition(
        "about", "documents", {
            "name": "Back", "region": "content",
            "route_context": "documents_menu",
            "predicted_target": "home", "prediction_match": False,
            "provenance": "live_corrected",
        })

    edge = graph.routing_graph["about"]["documents"]
    assert edge["route_contexts"] == ["documents_menu"]
    attempt = graph.action_edges[0]["attempts"][0]
    assert attempt["evidence"] == {
        "route_context": "documents_menu",
        "prediction_provenance": "live_corrected",
        "predicted_target": "home",
        "actual_target": "documents",
        "prediction_match": False,
    }


def test_plan_route_is_fewest_hop_and_skips_quarantined_edge() -> None:
    graph = _Graph()
    graph.edge("a", "b", "A to B")
    graph.edge("b", "target", "B to target")
    graph.edge("a", "c", "A to C")
    graph.edge("c", "d", "C to D")
    graph.edge("d", "target", "D to target")

    direct = _router(graph).plan_route("a", "target")
    assert [step["dst"] for step in direct] == ["b", "target"]

    detour = _router(graph, quarantined={("a", "b")}).plan_route("a", "target")
    assert [step["dst"] for step in detour] == ["c", "d", "target"]


def test_nearest_reachable_target_preserves_depth_then_target_order() -> None:
    graph = _Graph()
    graph.edge("root", "left", "Left")
    graph.edge("root", "right", "Right")
    graph.edge("left", "second", "Second")
    graph.edge("right", "first", "First")
    router = _router(graph)

    assert router.nearest_reachable_target(
        "root", ["first", "second"]) == "first"

    graph.edge("root", "second", "Direct second")
    assert router.nearest_reachable_target(
        "root", ["first", "second"]) == "second"


def test_nearest_unexplored_node_batches_frontier_route_planning() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.graph = SimpleNamespace(graph=nx.DiGraph())
    engine.graph.graph.add_nodes_from(
        ["current", "first", "blocked", "empty", "second"])
    engine._route_blocked_targets = {"blocked"}
    work = {
        state_id: SimpleNamespace(
            uid=state_id, name=state_id, region_id="", region="")
        for state_id in ("first", "blocked", "second")
    }
    engine._unvisited_candidates = lambda state_id: (
        [work[state_id]] if state_id in work else [])
    calls = []

    def nearest(current, targets):
        calls.append((current, list(targets)))
        return "second"

    engine.router = SimpleNamespace(nearest_reachable_target=nearest)

    assert engine._nearest_unexplored_node("current") == "second"
    assert calls == [("current", ["first", "second"])]


def test_live_corrected_edge_supersedes_old_prediction_for_same_context() -> None:
    graph = _Graph()
    graph.edge("settings", "old-apps", "Apps")
    graph.edge("settings", "live-apps", "Apps")
    graph.graph["settings"]["live-apps"]["attempts"] = [{
        "committed": True,
        "landing_verified": True,
        "action_index": 2,
        "evidence": {
            "route_context": "",
            "predicted_target": "old-apps",
            "actual_target": "live-apps",
            "prediction_match": False,
        },
    }]

    edges = _router(graph).node_out_edges("settings")

    assert edges["apps"]["dst"] == "live-apps"
    assert edges["apps"]["provenance"] == "direct_verified"


def test_forward_live_correction_supersedes_old_prediction_across_contexts() -> None:
    graph = _Graph()
    graph.edge("app-permissions", "wrong-app", "Camera")
    graph.edge("app-permissions", "actual-app", "Camera")
    graph.graph["app-permissions"]["actual-app"]["attempts"] = [{
        "committed": True,
        "landing_verified": True,
        "action_index": 2,
        "evidence": {
            "route_context": "first-entry",
            "predicted_target": "wrong-app",
            "actual_target": "actual-app",
            "prediction_match": False,
        },
    }]

    edges = _router(graph).node_out_edges(
        "app-permissions", arrival_source_id="second-entry")

    assert edges["camera"]["dst"] == "actual-app"
    assert edges["camera"]["provenance"] == "direct_verified"


def test_contextual_live_correction_does_not_hide_other_context() -> None:
    graph = _Graph()
    graph.edge("menu", "first-host", "Back")
    graph.edge("menu", "second-host", "Back")
    for target in ("first-host", "second-host"):
        graph.graph["menu"][target].update({
            "action": {"action_type": "BACK"},
            "effect_kind": "return",
        })
    graph.graph["menu"]["second-host"]["attempts"] = [{
        "committed": True,
        "landing_verified": True,
        "action_index": 2,
        "evidence": {
            "route_context": "second-host",
            "predicted_target": "first-host",
            "actual_target": "second-host",
            "prediction_match": False,
        },
    }]

    router = _router(graph)

    assert router.node_out_edges(
        "menu", arrival_source_id="second-host")["back"]["dst"] == "second-host"
    assert router.node_out_edges(
        "menu", arrival_source_id="first-host")["back"]["dst"] == "first-host"


def test_unverified_attempt_is_not_a_route() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "a", "target", element_label="uncertain", region="content",
        routing_verified=False, landing_verified=None,
    )
    assert _router(graph).plan_route("a", "target") is None


def test_router_replays_action_selector_not_semantic_display_label() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "a", "target", element_label="Set Bluetooth on", region="content",
        action={
            "action_type": "CLICK",
            "selector": {"element_label": "Bluetooth", "region": "content"},
        },
        routing_verified=True, landing_verified=True,
    )
    route = _router(graph).plan_route("a", "target")
    assert route == [{
        "source_id": "a", "source_region_id": "", "name": "Bluetooth",
        "region": "content", "dst": "target", "provenance": "direct_verified",
        "action": {
            "action_type": "CLICK",
            "selector": {"element_label": "Bluetooth", "region": "content"},
        }}]


def test_structured_click_receives_source_and_region_metadata() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "a", "target", element_label="Open", region="toolbar",
        source_region_id="r9", routing_verified=True, landing_verified=True)
    calls = []

    def click(source_id, name, region_id, role, obs):
        calls.append((source_id, name, region_id, role, obs))
        return RouterClickResult.action_dispatched("target")

    ok, obs = _router(graph, click=click).route_to("a", "a", "target")

    assert ok is True and obs == "target"
    assert calls == [("a", "Open", "r9", "toolbar", "a")]


def test_unexecuted_or_dispatch_unknown_click_never_calls_back() -> None:
    graph = _Graph()
    graph.edge("a", "target", "Open")
    for result in (
            RouterClickResult.not_attempted("a", "target_missing"),
            RouterClickResult.dispatch_unknown("a", "env_error")):
        back_calls = []
        click = lambda *_args, value=result: value
        ok, obs = _router(
            graph, click=click,
            back=lambda value: back_calls.append(value) or value,
            budget=0).route_to("a", "a", "target")
        assert ok is False and obs == "a"
        assert back_calls == []


def test_compact_topology_cannot_replace_verified_replay_action() -> None:
    graph = StateGraph("demo")
    graph.add_state("a", [], "a.png", "demo", page_id="pa", variant_id="va")
    graph.add_state(
        "target", [], "target.png", "demo", page_id="pt", variant_id="vt")
    graph.add_transition(
        "a", "target", {"action_type": "CLICK"},
        element_id="good", element_label="Good", region="content",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )
    graph.add_transition(
        "a", "target", {"action_type": "CLICK"},
        element_id="unknown", element_label="Unverified", region="content",
        effect_verdict="transitioned", landing_verified=None,
    )

    route = _router(graph).plan_route("a", "target")

    assert route is not None
    assert [step["name"] for step in route] == ["Good"], (
        "router must replay the verified ActionEdge, not compact topology labels")


def test_router_keeps_distinct_actions_on_the_same_stable_button() -> None:
    graph = StateGraph("demo")
    source_elements = [{
        "id": 7, "name": "Document", "region": "content",
        "region_id": "r1",
    }]
    graph.add_state("source", source_elements, "source.png", "demo")
    graph.add_state("opened", [], "opened.png", "demo")
    graph.add_state("menu", [], "menu.png", "demo")
    graph.add_transition(
        "source", "opened", {"action_type": "CLICK"},
        element_id="7", element_label="Document", region="content",
        effect_verdict="transitioned_consistent", landing_verified=True)
    graph.add_transition(
        "source", "menu", {"action_type": "RIGHT_CLICK"},
        element_id="7", element_label="Document", region="content",
        effect_verdict="transitioned_consistent", landing_verified=True)

    edges = list(_router(graph).node_out_edges("source").values())
    document_edges = [edge for edge in edges if edge["label"] == "Document"]

    assert {edge["action"]["action_type"] for edge in document_edges} == {
        "CLICK", "RIGHT_CLICK"}
    assert {edge["dst"] for edge in document_edges} == {"opened", "menu"}


def test_multistep_prerequisite_edge_is_not_fabricated_as_one_click() -> None:
    graph = StateGraph("demo")
    graph.add_state("a", [], "a.png", "demo", page_id="pa", variant_id="va")
    graph.add_state("target", [], "t.png", "demo", page_id="pt", variant_id="vt")
    graph.add_transition(
        "a", "target",
        {"action_type": "SEQUENCE", "steps": [
            {"action_type": "TYPE", "parameters": {"text": "fixture"}},
            {"action_type": "CLICK", "selector": {"element_label": "Save"}},
        ]},
        element_label="Create fixture",
        effect_verdict="transitioned_consistent", landing_verified=True,
        action_steps=2,
        action_sequence=[
            {"action_type": "TYPE", "parameters": {"text": "fixture"}},
            {"action_type": "CLICK", "selector": {"element_label": "Save"}},
        ],
        transition_kind="prerequisite_setup",
    )
    assert graph.routing_graph.has_edge("a", "target"), (
        "verified semantic edge remains evidence for recipe-aware consumers")
    assert _router(graph).plan_route("a", "target") is None, (
        "click-only router must fail closed on a multi-step semantic edge")


def test_state_graph_return_effect_survives_route_view_and_round_trip(tmp_path) -> None:
    graph = StateGraph("demo")
    graph.add_state("detail", [], "detail.png", "demo")
    graph.add_state("parent", [], "parent.png", "demo")
    graph.add_transition(
        "detail", "parent", {"action_type": "BACK"},
        element_label="", region="",
        effect_verdict="transitioned_consistent", landing_verified=True,
        transition_kind="router_verified", effect_kind="return",
    )
    path = tmp_path / "graph.json"
    graph.save(str(path))
    loaded = StateGraph.load(str(path))

    route = _router(loaded).plan_route("detail", "parent")
    assert route is not None
    assert route[0]["effect_kind"] == "return"


def test_route_verifies_every_hop_and_replans_from_known_derailment() -> None:
    graph = _Graph()
    graph.edge("a", "b", "planned first hop")
    graph.edge("b", "target", "planned second hop")
    graph.edge("c", "target", "recover from C")
    landings = {
        "planned first hop": "c",       # known derailment instead of b
        "recover from C": "target",
    }
    clicks = []
    identifies = []

    def click(name, region, obs):
        clicks.append((name, region, obs))
        return f"after:{name}"

    def identify(obs):
        identifies.append(obs)
        return landings[obs.removeprefix("after:")]

    ok, obs = _router(graph, identify=identify, click=click).route_to(
        "start", "a", "target")

    assert ok is True
    assert obs == "after:recover from C"
    assert [name for name, _region_name, _obs in clicks] == [
        "planned first hop", "recover from C"]
    assert identifies == [
        "after:planned first hop", "after:recover from C"]


def test_failed_route_hard_resets_then_routes_from_actual_landing() -> None:
    graph = _Graph()
    graph.edge("a", "wrong", "broken click")
    graph.edge("wrong", "target", "unreached second hop")
    graph.edge("actual_landing", "target", "landing to target")
    clicks = []

    def click(name, _region_name, _obs):
        clicks.append(name)
        if name == "broken click":
            return None
        return "target_obs"

    def execute(step, _obs):
        actions.append(step["action"])
        landing = "source_obs" if step["source_id"] == "target" else "target_obs"
        return RouterClickResult.action_dispatched(landing)

    router = _router(
        graph,
        click=click,
        identify=lambda obs: "target" if obs == "target_obs" else None,
        reset=lambda: ("actual_landing", "reset_obs"),
        budget=0,
    )
    ok, obs = router.route_to("start", "a", "target")

    assert ok is True
    assert obs == "target_obs"
    assert clicks == ["broken click", "landing to target"]


def test_hard_reset_and_unknown_arrival_fail_closed() -> None:
    graph = _Graph()
    graph.edge("actual_landing", "target", "try target")

    unknown_reset = _router(
        graph, reset=lambda: (None, "unknown_reset"), budget=0)
    assert unknown_reset.route_to("start", "nowhere", "target") == (
        False, "unknown_reset")

    unknown_hop = _router(
        graph,
        click=lambda _name, _region_name, _obs: "unidentified_obs",
        identify=lambda _obs: None,
        reset=lambda: ("actual_landing", "reset_obs"),
        budget=0,
    )
    assert unknown_hop.route_to("start", "nowhere", "target") == (
        False, "unidentified_obs")


def test_hard_reset_preserves_known_root_when_live_target_is_missing() -> None:
    graph = _Graph()
    graph.edge("root", "target", "More options")
    router = _router(
        graph,
        click=lambda *_args: RouterClickResult.not_attempted(
            "root_obs", "target_missing"),
        reset=lambda: ("root", "reset_root_obs"),
        budget=0,
    )

    result = router.route_to("root_obs", "root", "target")

    assert result.arrived is False
    assert result.landed_id == "root"
    assert result.failure_kind == "not_attempted"
    assert result.action_dispatched is True


def test_no_forward_path_can_ascend_with_back_and_replan() -> None:
    graph = _Graph()
    graph.edge("parent", "target", "parent to target")
    clicks = []

    def click(name, _region_name, _obs):
        clicks.append(name)
        return "target_obs"

    def identify(obs):
        return {"parent_obs": "parent", "target_obs": "target"}.get(obs)

    ok, obs = _router(
        graph,
        identify=identify,
        click=click,
        back=lambda _obs: "parent_obs",
        budget=1,
    ).route_to("child_obs", "child", "target")

    assert ok is True
    assert obs == "target_obs"
    assert clicks == ["parent to target"]


def test_page_identity_never_receives_final_navigation_target() -> None:
    graph = _Graph()
    graph.edge("parent", "target", "parent to target")
    identity_calls = []

    def identify(*args):
        identity_calls.append(args)
        return {"parent_obs": "parent", "target_obs": "target"}.get(args[0])

    ok, obs = _router(
        graph,
        identify=identify,
        click=lambda *_args: "target_obs",
        back=lambda _obs: "parent_obs",
        budget=1,
    ).route_to("child_obs", "child", "target")

    assert ok is True
    assert obs == "target_obs"
    assert identity_calls == [
        ("parent_obs", "child"),
        ("target_obs", "parent"),
    ]
    assert all(args[1] != "target" for args in identity_calls)


def test_route_failure_exposes_structured_retry_evidence() -> None:
    graph = _Graph()
    graph.edge("source", "target", "Open")
    result = _router(
        graph,
        click=lambda *_args: RouterClickResult.dispatch_unknown(
            "source_obs", "env_error"),
        budget=0,
    ).route_to("source_obs", "source", "target")

    assert result.arrived is False
    assert result.status == "dispatch_unknown"
    assert result.failure_kind == "dispatch_unknown"
    assert result.landed_id == "source"
    assert result.action_dispatched is True


def test_new_page_return_probe_persists_back_and_restores_target() -> None:
    graph = _Graph()
    graph.edge("source", "target", "Open")
    persisted = []
    clicks = []

    def identify(obs, _source=None):
        return {"source_obs": "source", "target_obs": "target"}.get(obs)

    router = _router(
        graph,
        identify=identify,
        click=lambda *_args: clicks.append("Open") or "target_obs",
        back=lambda _obs, _source=None: "source_obs",
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )
    result = router.verify_return_path("target_obs", "source", "target")

    assert result.arrived is True
    assert result.observation == "target_obs"
    assert clicks == ["Open"]
    assert persisted[0][0:2] == ("target", "source")
    assert persisted[0][2]["effect_kind"] == "return"


def test_return_probe_restores_target_from_the_sources_real_entry_context() -> None:
    graph = _Graph()
    graph.graph.add_edge(
        "source", "parent",
        element_label="Back", region="app_bar",
        action={"action_type": "CLICK"},
        effect_kind="return_via_control",
        routing_verified=True, landing_verified=True,
    )
    graph.edge("source", "target", "Open")
    clicks = []

    def click(source_id, name, _region_id, _role, _obs):
        clicks.append((source_id, name))
        landing = "target_obs" if name == "Open" else "parent_obs"
        return RouterClickResult.action_dispatched(landing)

    router = _router(
        graph,
        identify=lambda obs, _source=None: {
            "parent_obs": "parent",
            "source_obs": "source",
            "target_obs": "target",
        }.get(obs),
        click=click,
        back=lambda _obs, _source=None: "source_obs",
        budget=0,
    )
    router.note_arrival("target", "source")

    result = router.verify_return_path("target_obs", "source", "target")

    assert result.arrived is True
    assert result.observation == "target_obs"
    assert clicks == [("source", "Open")]


def test_return_probe_clicks_selected_control_then_restores_target() -> None:
    graph = _Graph()
    graph.edge("source", "target", "Open")
    persisted = []
    clicks = []

    def click(source_id, name, _region_id, _role, _obs):
        clicks.append((source_id, name))
        return RouterClickResult.action_dispatched(
            "source_obs" if source_id == "target" else "target_obs")

    router = _router(
        graph,
        identify=lambda obs, _source=None: {
            "source_obs": "source", "target_obs": "target"}.get(obs),
        click=click,
        back=lambda _obs, _source=None: pytest.fail("Back should not be used"),
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )
    result = router.verify_return_path(
        "target_obs", "source", "target", return_step={
            "source_id": "target", "source_region_id": "tabs",
            "name": "Chats", "region": "primary_navigation",
            "dst": "source", "provenance": "return_probe",
            "effect_kind": "return_via_control", "element_id": "7",
            "explore_on_verify": True,
        })

    assert result.arrived is True
    assert clicks == [("target", "Chats"), ("source", "Open")]
    assert persisted[0][0:2] == ("target", "source")
    assert persisted[0][2]["explore_on_verify"] is True


def test_unattempted_return_control_reports_unchanged_known_target() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target"])
    router = _router(
        graph,
        identify=lambda _obs, _source=None: pytest.fail(
            "identity must not run when the action was not attempted"),
        click=lambda *_args: RouterClickResult.not_attempted(
            "target_obs", "targeting_failed"),
    )

    result = router.verify_return_path(
        "target_obs", "source", "target", return_step={
            "source_id": "target", "source_region_id": "content",
            "name": "Got it", "region": "content", "dst": "source",
            "provenance": "return_probe", "effect_kind": "return_via_control",
        })

    assert result.arrived is False
    assert result.landed_id == "target"
    assert result.failure_kind == "return_control_not_attempted"
    assert result.action_dispatched is False


def test_reverse_probe_reports_no_effect_from_fresh_identity() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target"])
    router = _router(
        graph,
        identify=lambda _obs, _source=None: "target",
        execute=lambda _step, _obs:
        RouterClickResult.action_dispatched("target_obs"),
    )

    result = router.verify_return_path(
        "target_obs", "source", "target", return_step={
            "source_id": "target", "name": "World",
            "dst": "source", "provenance": "reverse_probe",
            "effect_kind": "peer_navigation",
            "action": {"action_type": "CLICK"},
        })

    assert result.arrived is False
    assert result.landed_id == "target"
    assert result.failure_kind == "return_no_effect"
    assert result.action_dispatched is True


def test_reverse_probe_reports_identity_unknown_after_dispatch() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target"])
    router = _router(
        graph,
        identify=lambda _obs, _source=None: None,
        execute=lambda _step, _obs:
        RouterClickResult.action_dispatched("unknown_obs"),
    )

    result = router.verify_return_path(
        "target_obs", "source", "target", return_step={
            "source_id": "target", "name": "World",
            "dst": "source", "provenance": "reverse_probe",
            "effect_kind": "peer_navigation",
            "action": {"action_type": "CLICK"},
        })

    assert result.arrived is False
    assert result.landed_id is None
    assert result.failure_kind == "return_identity_unknown"
    assert result.action_dispatched is True


def test_return_probe_executes_native_swipe_then_restores_target() -> None:
    graph = _Graph()
    graph.edge("source", "target", "Open")
    actions = []
    clicks = []

    def execute(step, _obs):
        actions.append(step["action"])
        landing = ("source_obs" if step["source_id"] == "target"
                   else "target_obs")
        return RouterClickResult.action_dispatched(landing)

    router = _router(
        graph,
        identify=lambda obs, _source=None: {
            "source_obs": "source", "target_obs": "target"}.get(obs),
        click=lambda source_id, *_args: clicks.append(source_id)
        or RouterClickResult.action_dispatched("target_obs"),
        execute=execute,
        budget=0,
    )
    result = router.verify_return_path(
        "target_obs", "source", "target", return_step={
            "source_id": "target", "source_region_id": "", "name": "",
            "region": "", "dst": "source", "provenance": "return_probe",
            "effect_kind": "return_native_action", "element_id": "",
            "action": {"action_type": "swipe", "direction": "down"},
        })

    assert result.arrived is True
    assert actions[0] == {"action_type": "swipe", "direction": "down"}
    assert actions[1]["action_type"] == "CLICK"
    assert clicks == []


def test_return_probe_policy_skips_same_page_variant() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _return_probe_policy,
    )

    host = SimpleNamespace(
        _proactive_return_verification=True,
        _state_data={
            "with-banner": {"page_id": "p-clock"},
            "without-banner": {"page_id": "p-clock"},
        },
    )
    element = SimpleNamespace(risk="none")

    enabled, reason = _return_probe_policy(
        host, is_new=True, source_id="with-banner",
        target_id="without-banner", element=element,
        action={"action_type": "CLICK"}, pre_actions=[],
        is_stateful=False, is_restore=False)

    assert enabled is False
    assert reason == "same_page_variant"


def test_return_probe_policy_does_not_press_back_twice() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _return_probe_policy,
    )

    host = SimpleNamespace(
        _proactive_return_verification=True,
        _state_data={
            "sound": {"page_id": "sound"},
            "alarms": {"page_id": "alarms"},
        },
    )
    element = SimpleNamespace(back=True, risk="none")

    enabled, reason = _return_probe_policy(
        host, is_new=True, source_id="sound", target_id="alarms",
        element=element, action={"action_type": "CLICK"}, pre_actions=[],
        is_stateful=False, is_restore=False)

    assert enabled is False
    assert reason == "opening_action_is_return"


def test_reverse_probe_skips_context_compatible_direct_edge() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _has_verified_direct_reverse,
    )

    host = SimpleNamespace(
        router=SimpleNamespace(node_out_edges=lambda source, context: {
            "world": {
                "dst": "world",
                "source_id": source,
                "route_context": context,
                "provenance": "direct_verified",
            },
        }),
    )

    assert _has_verified_direct_reverse(host, "world", "alarms") is True


def test_reverse_probe_does_not_treat_predicted_edge_as_verified() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _has_verified_direct_reverse,
    )

    host = SimpleNamespace(
        router=SimpleNamespace(node_out_edges=lambda *_args: {
            "world": {
                "dst": "world",
                "provenance": "context_predicted",
            },
        }),
    )

    assert _has_verified_direct_reverse(host, "world", "alarms") is False


def test_reverse_probe_dispatch_unknown_rejects_stale_source_landing() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _known_return_failure_landing,
    )

    host = SimpleNamespace(
        _state_data={
            "alarms": {"path": [], "replay_hints": []},
        },
        _route_blocked_targets=set(),
    )
    result = SimpleNamespace(
        status="dispatch_unknown",
        observation={"screenshot": b"stale-alarms"},
        landed_id="alarms",
        failure_kind="return_dispatch_unknown",
        action_dispatched=True,
    )

    assert _known_return_failure_landing(host, result, "alarms") is None


def test_return_probe_policy_verifies_same_page_overlay_transition() -> None:
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        _return_probe_policy,
    )

    host = SimpleNamespace(
        _proactive_return_verification=True,
        _state_data={
            "clock": {"page_id": "p-clock", "surface_kind": "page"},
            "more-menu": {
                "page_id": "p-clock", "surface_kind": "popup_menu"},
        },
    )
    element = SimpleNamespace(risk="none")

    enabled, reason = _return_probe_policy(
        host, is_new=True, source_id="clock", target_id="more-menu",
        element=element, action={"action_type": "CLICK"}, pre_actions=[],
        is_stateful=False, is_restore=False)

    assert enabled is True
    assert reason == "ordinary_navigation"


def test_return_probe_accepts_bare_host_of_overlay_source() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["home-menu", "home", "about"])
    graph.edge("home", "about", "About Dayline")
    persisted = []
    clicks = []

    def click(source_id, name, _region_id, _role, _obs):
        clicks.append((source_id, name))
        return RouterClickResult.action_dispatched(
            "home_obs" if source_id == "about" else "about_obs")

    router = _router(
        graph,
        state_data={
            "home-menu": {"page_id": "p-home", "surface_kind": "popup_menu"},
            "home": {"page_id": "p-home", "surface_kind": "page"},
            "about": {"page_id": "p-about", "surface_kind": "page"},
        },
        identify=lambda obs, _source=None: {
            "home_obs": "home", "about_obs": "about"}.get(obs),
        click=click,
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )
    result = router.verify_return_path(
        "about_obs", "home-menu", "about", return_step={
            "source_id": "about", "source_region_id": "app-bar",
            "name": "Back", "region": "top_app_bar",
            "dst": "home-menu", "provenance": "return_probe",
            "effect_kind": "return_via_control", "element_id": "1",
        })

    assert result.arrived is True
    assert clicks == [("about", "Back"), ("home", "About Dayline")]
    assert persisted[0][0:2] == ("about", "home")


def test_return_probe_accepts_actual_landing_and_restores_from_it() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target", "other"])
    graph.edge("other", "target", "Open target")
    persisted = []
    clicks = []
    router = _router(
        graph,
        identify=lambda obs, _source=None: {
            "other_obs": "other", "target_obs": "target"}.get(obs),
        click=lambda source_id, *_args: clicks.append(source_id)
        or RouterClickResult.action_dispatched("target_obs"),
        back=lambda _obs, _source=None: "other_obs",
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )
    result = router.verify_return_path("target_obs", "source", "target")

    assert result.arrived is True
    assert result.observation == "target_obs"
    assert clicks == ["other"]
    assert [(source, target) for source, target, _step in persisted] == [
        ("target", "other")]
    corrected = persisted[0][2]
    assert corrected["predicted_target"] == "source"
    assert corrected["prediction_match"] is False
    assert corrected["provenance"] == "live_corrected"


def test_return_probe_registers_unknown_actual_landing_then_restores() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "target", "actual"])
    graph.edge("actual", "target", "Open target")
    persisted = []
    registrations = []
    router = _router(
        graph,
        identify=lambda obs, _source=None: (
            "target" if obs == "target_obs" else None),
        register_landing=lambda obs, source, step: (
            registrations.append((obs, source, step)) or "actual"),
        click=lambda source_id, *_args: RouterClickResult.action_dispatched(
            "target_obs" if source_id == "actual" else "unknown_obs"),
        back=lambda _obs, _source=None: "unknown_obs",
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )

    result = router.verify_return_path("target_obs", "source", "target")

    assert result.arrived is True
    assert result.observation == "target_obs"
    assert registrations[0][0:2] == ("unknown_obs", "target")
    assert [(source, target) for source, target, _step in persisted] == [
        ("target", "actual")]
    assert persisted[0][2]["predicted_target"] == "source"
    assert persisted[0][2]["prediction_match"] is False


def test_forward_route_registers_unknown_actual_landing_and_corrects_edge() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "expected", "actual"])
    graph.edge("source", "expected", "Open")
    persisted = []
    router = _router(
        graph,
        identify=lambda _obs, _source=None: None,
        register_landing=lambda _obs, _source, _step: "actual",
        click=lambda *_args: RouterClickResult.action_dispatched("actual_obs"),
        recorder=lambda source, target, step: persisted.append(
            (source, target, step)),
        budget=0,
    )

    result = router.route_to("source_obs", "source", "expected")

    assert result.arrived is False
    assert result.landed_id == "actual"
    assert result.failure_kind == "identity_mismatch"
    assert [(source, target) for source, target, _step in persisted] == [
        ("source", "actual")]


def test_forward_route_passes_executed_step_to_identity() -> None:
    graph = _Graph()
    graph.graph.add_nodes_from(["source", "expected"])
    graph.edge("source", "expected", "Open")
    observed = []
    router = _router(
        graph,
        identify=lambda obs, source, step: (
            observed.append((obs, source, dict(step))) or "expected"),
        click=lambda *_args: RouterClickResult.action_dispatched("expected_obs"),
        budget=0,
    )

    result = router.route_to("source_obs", "source", "expected")

    assert result.arrived is True
    assert observed[0][0:2] == ("expected_obs", "source")
    assert observed[0][2]["name"] == "Open"
    assert observed[0][2]["dst"] == "expected"


def test_router_actual_landing_only_uses_explicit_fresh_observation_request(
        monkeypatch) -> None:
    from gui_rewalk.src.core.visual_traversal.runtime import landing

    captured = []

    def register(_host, _obs, _path, _hints, transition=None):
        captured.append(dict(transition or {}))
        return SimpleNamespace(state_id="target", is_new=False)

    monkeypatch.setattr(landing, "register_landing", register)
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine._state_data = {
        "target": {"path": [], "replay_hints": []},
    }
    engine.focus_guard = None
    engine._route_blocked_targets = set()
    engine._route_target_failure_counts = {}
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._is_touch = False

    result = engine._router_register_actual_landing(
        {"screenshot": b"same target"}, "target", {
            "action": {
                "action_type": "PRESS",
                "parameters": {"key": "esc"},
            },
            "effect_kind": "return_native_action",
        })

    assert result == "target"
    assert captured[-1]["requires_fresh_observation"] is False
    engine._router_register_actual_landing(
        {"screenshot": b"same Page, other host"}, "target", {
            "action": {"action_type": "CLICK"},
            "effect_kind": "forward",
            "requires_fresh_observation": True,
        })

    assert captured[-1]["requires_fresh_observation"] is True
