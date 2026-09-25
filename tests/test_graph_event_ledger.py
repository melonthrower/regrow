"""Offline schema-v3 contracts for semantic action edges and nested attempts."""
from __future__ import annotations

import json
import copy
import tempfile
from pathlib import Path
import sys

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.graph.state_graph import StateGraph  # noqa: E402
from gui_rewalk.src.core.graph.graph_quality_agent import GraphQualityAgent  # noqa: E402


def _add_nodes(graph: StateGraph) -> None:
    graph.add_state(
        "empty", [], "empty.png", "clock", page_name="Alarm",
        page_id="alarm_home", variant_id="empty",
        variant_signature={"alarm_exists": False},
        observed_facts={"alarm_exists": False},
        visible_capabilities=["create_alarm"],
    )
    graph.add_state(
        "full", [], "full.png", "clock", page_name="Alarm",
        page_id="alarm_home", variant_id="has_alarm",
        variant_signature={"alarm_exists": True},
        observed_facts={"alarm_exists": True},
        visible_capabilities=["create_alarm", "open_alarm_detail"],
    )
    graph.add_state(
        "detail", [], "detail.png", "clock", page_name="Alarm detail",
        page_id="alarm_detail", variant_id="default",
    )


def test_schema_v3_groups_attempts_without_collapsing_actions() -> None:
    graph = StateGraph("clock")
    _add_nodes(graph)
    graph.capabilities["open_alarm_detail"] = {
        "capability_id": "open_alarm_detail",
        "available_when": {"alarm_exists": True},
        "status": "discovered",
    }
    graph.record_scroll_scope(
        scope_id="region:r-alarm", state_id="full", region_id="r-alarm",
        role="content", classification="scrollable",
        termination="viewport_stable", bottom_reached=True,
        top_restored=True, steps=2, max_steps=16,
    )

    first = graph.add_transition(
        "full", "detail",
        {"action_type": "CLICK", "parameters": {"x": 120, "y": 240}},
        element_id="row-1", element_label="Alarm row", region="content",
        effect_verdict="transitioned_consistent", landing_verified=True,
        target_page_name="Alarm detail",
    )
    failed_retry = graph.record_action_event(
        source="full",
        action={"action_type": "CLICK", "parameters": {"x": 999, "y": 999}},
        element_id="row-1", element_label="Alarm row", region="content",
        outcome="no_effect", landing_verified=False,
    )
    second_action = graph.add_transition(
        "full", "detail",
        {"action_type": "CLICK", "parameters": {"x": 20, "y": 30}},
        element_id="menu-open", element_label="Open details", region="menu",
        effect_verdict="transitioned_consistent", landing_verified=True,
        target_page_name="Alarm detail",
    )
    graph.add_transition(
        "empty", "full",
        {"action_type": "CLICK", "parameters": {"x": 5, "y": 5}},
        element_id="create", element_label="Create alarm", region="toolbar",
        effect_verdict="transitioned", landing_verified=None,
        target_page_name="Alarm",
    )

    assert graph.num_edges == 2, "topology stays compact per source/target pair"
    assert len(graph.action_edges) == 3, "different semantic actions must not collapse"
    row_edge = next(
        edge for edge in graph.action_edges
        if edge["element_id"] == "row-1")
    assert [a["action_index"] for a in row_edge["attempts"]] == [first, failed_retry]
    assert row_edge["attempt_count"] == 2
    assert row_edge["routing_verified"] is True
    assert row_edge["source_page_id"] == "alarm_home"
    assert row_edge["source_variant_id"] == "has_alarm"
    assert row_edge["target_page_id"] == "alarm_detail"
    assert row_edge["target_variant_id"] == "default"
    assert row_edge["action"]["selector"]["element_label"] == "Alarm row"
    assert "element_id" not in row_edge["action"]["selector"]
    topology = graph.graph.edges["full", "detail"]
    assert len(topology["action_edge_ids"]) == 2
    assert graph.routing_graph.has_edge("full", "detail")
    assert not graph.routing_graph.has_edge("empty", "full"), (
        "landing_verified=None is never routable in schema v3")
    assert second_action == 3

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "graph.json"
        graph.save(str(path))
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["graph_schema_version"] == 3
        assert "transition_events" not in raw
        assert len(raw["action_edges"]) == 3
        assert raw["scroll_ledger"][0]["complete"] is True
        encoded = json.dumps(raw["action_edges"], ensure_ascii=False)
        assert '"x"' not in encoded and '"y"' not in encoded
        report = GraphQualityAgent(workspace=temporary).evaluate_data(raw)
        assert report["ledger"]["history_status"] == "complete"
        codes = {item["code"] for item in report["findings"]}
        assert "duplicate_transition_event_ledger" not in codes
        assert "action_edge_without_attempt" not in codes
        assert "route_missing_action_edge" not in codes

        loaded = StateGraph.load(str(path))
        assert loaded.num_transition_events == 4
        assert len(loaded.action_edges) == 3
        assert loaded.pages["alarm_home"]["variants"].keys() == {
            "empty", "has_alarm"}
        assert loaded.capabilities == graph.capabilities
        assert loaded.scroll_ledger["region:r-alarm"]["bottom_reached"] is True
        assert loaded.routing_graph.has_edge("full", "detail")
        assert not loaded.routing_graph.has_edge("empty", "full")
        try:
            loaded.transition_events = []
        except AttributeError:
            pass
        else:
            raise AssertionError("transition_events compatibility view must be read-only")


def test_schema_v2_migrates_events_and_requires_explicit_landing() -> None:
    legacy = nx.DiGraph()
    legacy.add_node("a", state_id="a", page_name="A", elements=[])
    legacy.add_node("b", state_id="b", page_name="B", elements=[])
    legacy.add_node("c", state_id="c", page_name="C", elements=[])
    legacy.add_edge(
        "a", "b", action={"action_type": "CLICK", "parameters": {"x": 1, "y": 2}},
        element_id="one", element_label="First", region="content",
        action_index=1, action_indices=[1, 2], landing_verified=True,
        effect_verdict="transitioned_consistent",
    )
    legacy.add_edge(
        "b", "c", action={"action_type": "CLICK", "parameters": {"x": 3, "y": 4}},
        element_id="next", element_label="Next", region="content",
        action_index=3, action_indices=[3], landing_verified=None,
        effect_verdict="transitioned",
    )
    raw = nx.node_link_data(legacy, edges="edges")
    raw.update({
        "graph_schema_version": 2,
        "app_name": "legacy",
        "action_counter": 3,
        "transition_events": [
            {
                "event_id": "legacy:1", "action_index": 1,
                "source": "a", "target": "b",
                "action": {"action_type": "CLICK", "parameters": {"x": 1, "y": 2}},
                "element_id": "one", "element_label": "First", "region": "content",
                "outcome": "transitioned_consistent", "landing_verified": True,
                "committed": True,
            },
            {
                "event_id": "legacy:2", "action_index": 2,
                "source": "a", "target": "b",
                "action": {"action_type": "CLICK", "parameters": {"x": 9, "y": 9}},
                "element_id": "two", "element_label": "Second", "region": "content",
                "outcome": "no_effect", "landing_verified": False,
                "committed": False,
            },
            {
                "event_id": "legacy:3", "action_index": 3,
                "source": "b", "target": "c",
                "action": {"action_type": "CLICK", "parameters": {"x": 3, "y": 4}},
                "element_id": "next", "element_label": "Next", "region": "content",
                "outcome": "transitioned", "landing_verified": None,
                "committed": True,
            },
        ],
    })

    with tempfile.TemporaryDirectory() as temporary:
        old_path = Path(temporary) / "v2.json"
        new_path = Path(temporary) / "v3.json"
        old_path.write_text(json.dumps(raw), encoding="utf-8")
        graph = StateGraph.load(str(old_path))
        assert len(graph.action_edges) == 3
        assert graph.routing_graph.has_edge("a", "b")
        assert not graph.routing_graph.has_edge("b", "c")
        assert all(
            '"x"' not in json.dumps(edge["action"])
            and '"y"' not in json.dumps(edge["action"])
            for edge in graph.action_edges)
        migrated_a = graph.graph.nodes["a"]
        assert migrated_a["page_identity_version"] == "semantic_page_variant_v1"
        assert graph.pages[migrated_a["page_id"]]["variants"][
            migrated_a["variant_id"]]["state_ids"] == ["a"]

        graph.save(str(new_path))
        migrated = json.loads(new_path.read_text(encoding="utf-8"))
        assert migrated["graph_schema_version"] == 3
        assert "transition_events" not in migrated
        reloaded = StateGraph.load(str(new_path))
        assert reloaded.num_transition_events == 3
        assert reloaded.routing_graph.has_edge("a", "b")
        assert not reloaded.routing_graph.has_edge("b", "c")


def test_failed_attempt_is_adopted_by_later_verified_edge() -> None:
    graph = StateGraph("demo")
    graph.add_state("a", [], "a.png", "demo", page_id="page_a", variant_id="va")
    graph.add_state("b", [], "b.png", "demo", page_id="page_b", variant_id="vb")
    failed = graph.record_action_event(
        source="a", action={"action_type": "CLICK", "parameters": {"x": 1, "y": 2}},
        element_id="open", element_label="Open", outcome="no_effect",
        landing_verified=False,
    )
    succeeded = graph.add_transition(
        "a", "b", {"action_type": "CLICK", "parameters": {"x": 20, "y": 30}},
        element_id="open", element_label="Open",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )
    assert len(graph.action_edges) == 1
    assert [item["action_index"] for item in graph.action_edges[0]["attempts"]] == [
        failed, succeeded]
    assert graph.action_edges[0]["routing_verified"] is True


def test_action_attempt_evidence_merges_independent_observers() -> None:
    graph = StateGraph("demo")
    graph.add_state("a", [], "a.png", "demo", page_id="p", variant_id="v")
    event = graph.record_action_event(
        source="a", action={"action_type": "CLICK"},
        evidence={"execution": {"dispatched": True}},
    )

    graph.merge_action_event_evidence(
        event, {"region_transition": {"introduced_regions": ["r-new"]}})

    evidence = graph.action_attempt(event)["evidence"]
    assert evidence["execution"]["dispatched"] is True
    assert evidence["region_transition"]["introduced_regions"] == ["r-new"]


def test_effect_observation_append_preserves_attempt_truth_and_round_trip() -> None:
    graph = StateGraph("clock")
    graph.add_state("alarm-off", [], "alarm-off.png", "clock")
    graph.add_state("alarm-on", [], "alarm-on.png", "clock")
    existing = {
        "schema_version": "gui_rewalk.effect_observation.v1",
        "capability_name": "",
        "reason": "",
        "effect_kind": "no_effect",
        "observed_changes": [],
        "parameter_bindings": {},
        "predicate_candidate": "",
        "verdict": "supported",
        "observation_index": 0,
    }
    event = graph.record_action_event(
        source="alarm-off",
        action={"action_type": "CLICK", "selector": {"element_label": "Alarm"}},
        evidence={
            "execution": {"dispatched": True},
            "effect_observations": [copy.deepcopy(existing)],
        },
    )
    graph.add_transition(
        "alarm-off", "alarm-on",
        {"action_type": "CLICK", "selector": {"element_label": "Alarm"}},
        effect_verdict="transitioned_consistent", landing_verified=True,
        event_index=event,
    )
    before = copy.deepcopy(graph.action_attempt(event))

    appended = graph.append_effect_observation(event, {
        "capability_name": " Toggle alarm ",
        "reason": " Alarm state changed ",
        "effect_kind": "STATE_CHANGE",
        "observed_changes": [{
            "scope": {"region_ref": " rg-alarm ", "page_id": " alarm "},
            "fact": " alarm.enabled ", "before": False, "after": True,
        }],
        "parameter_bindings": {"enabled": True},
        "predicate_candidate": " Alarm is enabled ",
        "verdict": "SUPPORTED",
    })

    after = graph.action_attempt(event)
    immutable_fields = (
        "action_index", "attempt_id", "action_edge_id", "action", "source",
        "target", "outcome", "landing_verified", "committed",
    )
    assert {key: after[key] for key in immutable_fields} == {
        key: before[key] for key in immutable_fields
    }
    assert after["evidence"]["execution"] == before["evidence"]["execution"]
    assert after["evidence"]["effect_observations"][0] == existing
    assert after["evidence"]["effect_observations"][1] == appended
    assert appended["observation_index"] == 1
    assert appended["capability_name"] == "Toggle alarm"
    assert appended["observed_changes"][0]["scope"] == {
        "region_ref": "rg-alarm", "page_id": "alarm",
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "graph.json"
        graph.save(str(path))
        loaded = StateGraph.load(str(path))
    assert loaded.action_attempt(event) == after


def test_uncommitted_attempt_can_move_to_corrected_semantic_edge() -> None:
    graph = StateGraph("calendar")
    graph.add_state("source", [], "source.png", "calendar")
    graph.add_state("target", [], "target.png", "calendar")
    earlier = graph.record_action_event(
        source="source", action={"action_type": "CLICK"},
        element_id="7", element_label="Date picker",
        semantic_description="Date picker", region="toolbar",
        outcome="no_effect", landing_verified=False,
    )
    current = graph.record_action_event(
        source="source", action={"action_type": "CLICK"},
        element_id="7", element_label="Date picker",
        semantic_description="Date picker", region="toolbar",
    )

    graph.correct_action_event_semantics(
        current,
        action={"action_type": "CLICK", "selector": {
            "element_label": "Manage your calendars",
            "region": "toolbar",
        }},
        element_label="Manage your calendars",
        semantic_description="Manage your calendars",
        region="toolbar",
    )
    graph.add_transition(
        "source", "target",
        {"action_type": "CLICK", "selector": {
            "element_label": "Manage your calendars",
            "description": "Manage your calendars",
            "region": "toolbar",
        }},
        element_id="7", element_label="Manage your calendars",
        semantic_description="Manage your calendars", region="toolbar",
        effect_verdict="transitioned_consistent", landing_verified=True,
        event_index=current,
    )

    old_edge = next(
        edge for edge in graph.action_edges
        if edge["element_label"] == "Date picker")
    corrected_edge = next(
        edge for edge in graph.action_edges
        if edge["element_label"] == "Manage your calendars")
    assert [attempt["action_index"] for attempt in old_edge["attempts"]] == [
        earlier]
    assert [attempt["action_index"] for attempt in corrected_edge["attempts"]] == [
        current]
    assert corrected_edge["routing_verified"] is True
    assert graph.action_attempt(current)["element_label"] == (
        "Manage your calendars")
    assert graph.graph.edges["source", "target"]["element_label"] == (
        "Manage your calendars")


def test_committed_attempt_semantics_cannot_be_rewritten() -> None:
    graph = StateGraph("calendar")
    graph.add_state("source", [], "source.png", "calendar")
    graph.add_state("target", [], "target.png", "calendar")
    event = graph.add_transition(
        "source", "target", {"action_type": "CLICK"},
        element_id="7", element_label="Date picker",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )

    try:
        graph.correct_action_event_semantics(
            event, action={"action_type": "CLICK"},
            element_label="Manage your calendars")
    except ValueError as exc:
        assert "committed" in str(exc)
    else:
        raise AssertionError("committed semantics must remain immutable")


def test_page_variant_refinement_removes_stale_membership() -> None:
    graph = StateGraph("demo")
    graph.add_state(
        "state", [], "state.png", "demo", page_id="page", variant_id="old")
    graph.add_state(
        "state", [], "state.png", "demo", page_id="page", variant_id="new")

    assert graph.graph.nodes["state"]["variant_id"] == "new"
    assert "old" not in graph.pages["page"]["variants"]
    assert graph.pages["page"]["variants"]["new"]["state_ids"] == ["state"]


def test_verified_action_records_only_its_grounded_entry_execution() -> None:
    graph = StateGraph("demo")
    graph.add_state(
        "source", [], "source.png", "demo",
        page_id="source_page", variant_id="source_variant")
    graph.add_state(
        "target", [], "target.png", "demo",
        page_id="target_page", variant_id="target_variant")
    graph.register_capability_candidates("source", [
        {
            "capability_id": "edit_one", "status": "discovered",
            "source_elements": [{
                "variant_id": "source_variant", "element_id": "one",
                "element_label": "Edit", "region": "left",
            }],
        },
        {
            "capability_id": "edit_two", "status": "discovered",
            "source_elements": [{
                "variant_id": "source_variant", "element_id": "two",
                "element_label": "Edit", "region": "right",
            }],
        },
    ])
    graph.add_transition(
        "source", "target", {"action_type": "CLICK"},
        element_id="one", element_label="Edit", region="left",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )

    executed = graph.capabilities["edit_one"]
    assert executed["status"] == "discovered"
    assert executed["action_edge_ids"]
    assert executed["entry_execution_evidence"][0]["landing_verified"] is True
    assert "effects" not in executed and "success_predicate" not in executed
    assert graph.capabilities["edit_two"]["status"] == "discovered"


def test_verified_landing_does_not_create_region_effect_observable():
    graph = StateGraph("clock")
    graph.add_state(
        "empty", [], "empty.png", "clock",
        page_id="alarm", variant_id="empty")
    graph.add_state(
        "populated", [], "populated.png", "clock",
        page_id="alarm", variant_id="populated",
        region_transition={
            "relationship": "same_page_variant",
            "introduced_regions": [{
                "region_id": "new-alarm",
                "name": "New alarm details",
                "introduced_by_attempt_id": "clock:1",
            }],
            "result_binding": {
                "kind": "introduced_region",
                "status": "bound",
                "attempt_id": "clock:1",
                "region_ids": ["new-alarm"],
            },
        },
    )
    graph.register_capability_candidates("empty", [{
        "capability_id": "create_alarm",
        "status": "discovered",
        "source_elements": [{
            "variant_id": "empty",
            "element_id": "create",
            "element_label": "Create alarm",
        }],
    }])

    graph.add_transition(
        "empty", "populated", {"action_type": "CLICK"},
        element_id="create", element_label="Create alarm",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )

    capability = graph.capabilities["create_alarm"]
    assert capability["status"] == "discovered"
    assert capability["entry_execution_evidence"][0]["introduced_regions"][0]["region_id"] == "new-alarm"
    assert "effects" not in capability and "success_predicate" not in capability
    assert "observables" not in capability


def test_portable_selector_disambiguates_same_label_actions() -> None:
    graph = StateGraph("demo")
    graph.add_state("source", [], "s.png", "demo", page_id="p", variant_id="v")
    graph.add_state("target", [], "t.png", "demo", page_id="q", variant_id="w")
    for group in ("primary", "secondary"):
        graph.add_transition(
            "source", "target",
            {
                "action_type": "CLICK",
                "selector": {
                    "element_label": "Open", "region": "content",
                    "group": group,
                },
            },
            element_id=group, element_label="Open", region="content",
            effect_verdict="transitioned_consistent", landing_verified=True,
        )
    matching = [
        edge for edge in graph.action_edges
        if edge["source"] == "source" and edge["target"] == "target"]
    assert len(matching) == 2
    assert {edge["action"]["selector"]["group"] for edge in matching} == {
        "primary", "secondary"}


def test_variant_refinement_cascades_to_edges_and_capabilities() -> None:
    graph = StateGraph("demo")
    graph.add_state(
        "source", [], "s.png", "demo", page_id="page", variant_id="preliminary")
    graph.add_state(
        "target", [], "t.png", "demo", page_id="target", variant_id="default")
    graph.register_capability_candidates("source", [{
        "capability_id": "open_target", "page_id": "page",
        "status": "discovered", "availability_status": "discovered",
        "source_elements": [{
            "state_id": "source", "variant_id": "preliminary",
            "element_id": "open", "element_label": "Open",
        }],
        "entry_variants": ["preliminary"],
        "evidence_variants": ["preliminary"],
        "available_when": {
            "variant_ids": ["preliminary"],
            "facts_by_variant": {"preliminary": {"functions": ["open"]}},
            "availability_by_variant": {"preliminary": "discovered"},
            "requires_by_variant": {"preliminary": []},
        },
    }])
    graph.add_transition(
        "source", "target", {"action_type": "CLICK"},
        element_id="open", element_label="Open",
        effect_verdict="transitioned_consistent", landing_verified=True,
    )
    graph.add_state(
        "source", [], "s.png", "demo", page_id="page", variant_id="complete")

    edge = graph.action_edges[0]
    capability = graph.capabilities["open_target"]
    assert edge["source_variant_id"] == "complete"
    assert capability["source_elements"][0]["variant_id"] == "complete"
    assert capability["entry_variants"] == ["complete"]
    assert capability["available_when"]["variant_ids"] == ["complete"]
    assert "preliminary" not in capability["available_when"]["facts_by_variant"]

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "graph.json"
        graph.save(str(path))
        raw = json.loads(path.read_text(encoding="utf-8"))
        report = GraphQualityAgent(workspace=temporary).evaluate_data(raw)
        codes = {item["code"] for item in report["findings"]}
        assert "action_edge_page_variant_mismatch" not in codes
        loaded = StateGraph.load(str(path))
        assert loaded.action_edges[0]["source_variant_id"] == "complete"


def test_provisional_state_removal_retargets_only_uncommitted_attempt() -> None:
    graph = StateGraph("settings")
    facts = {
        "states": {"bluetooth_enabled": "off"},
        "selected": ["bluetooth"],
    }
    graph.add_state(
        "source", [], "source.png", "settings",
        page_id="bluetooth", variant_id="off",
        observed_facts=facts,
    )
    graph.add_state(
        "jitter", [], "jitter.png", "settings",
        page_id="bluetooth", variant_id="off-jitter",
        observed_facts=facts,
    )
    graph.register_capability_candidates("source", [{
        "capability_id": "toggle_bluetooth", "page_id": "bluetooth",
        "source_elements": [{
            "state_id": "source", "variant_id": "off",
            "element_id": "toggle", "element_label": "Bluetooth",
        }],
        "entry_variants": ["off"], "evidence_variants": ["off"],
        "available_when": {"variant_ids": ["off"]},
    }])
    graph.register_capability_candidates("jitter", [{
        "capability_id": "toggle_bluetooth", "page_id": "bluetooth",
        "source_elements": [{
            "state_id": "jitter", "variant_id": "off-jitter",
            "element_id": "toggle", "element_label": "Bluetooth",
        }],
        "entry_variants": ["off-jitter"],
        "evidence_variants": ["off-jitter"],
        "available_when": {
            "variant_ids": ["off-jitter"],
            "facts_by_variant": {"off-jitter": facts},
        },
    }])
    graph.record_scroll_scope(
        scope_id="state:jitter:page", state_id="jitter",
        classification="static", termination="viewport_stable",
        top_restored=True,
    )
    event_index = graph.record_action_event(
        source="source", target="jitter", action={"action_type": "CLICK"},
        element_id="toggle", element_label="Bluetooth",
        outcome="no_effect", landing_verified=False, committed=False,
    )

    assert graph.remove_uncommitted_state("jitter", alias_to="source") is True
    assert set(graph.graph.nodes) == {"source"}
    _edge, attempt = graph._find_attempt(event_index)
    assert attempt["target"] == "source"
    assert attempt["outcome"] == "no_effect"
    assert attempt["committed"] is False
    assert attempt["landing_verified"] is False
    assert "off-jitter" not in graph.pages["bluetooth"]["variants"]
    assert "state:jitter:page" not in graph.scroll_ledger
    sources = graph.capabilities["toggle_bluetooth"]["source_elements"]
    assert {item.get("state_id") for item in sources} == {"source"}
    assert "off-jitter" not in graph.capabilities[
        "toggle_bluetooth"]["available_when"]["variant_ids"]


def test_provisional_state_removal_is_atomic_when_edge_has_unresolved_history() -> None:
    graph = StateGraph("settings")
    graph.add_state("source", [], "source.png", "settings")
    graph.add_state("jitter", [], "jitter.png", "settings")
    graph.record_action_event(
        source="source", action={"action_type": "CLICK"},
        element_id="toggle", element_label="Bluetooth",
        outcome="execution_error", landing_verified=False,
    )
    graph.record_action_event(
        source="source", target="jitter", action={"action_type": "CLICK"},
        element_id="toggle", element_label="Bluetooth",
        outcome="no_effect", landing_verified=False,
    )
    before = copy.deepcopy(graph.action_edges)

    assert graph.remove_uncommitted_state("jitter", alias_to="source") is False
    assert graph.action_edges == before, "a refused cleanup must be zero-mutation"
    assert "jitter" in graph.graph


def main() -> int:
    test_schema_v3_groups_attempts_without_collapsing_actions()
    test_schema_v2_migrates_events_and_requires_explicit_landing()
    test_failed_attempt_is_adopted_by_later_verified_edge()
    test_effect_observation_append_preserves_attempt_truth_and_round_trip()
    test_uncommitted_attempt_can_move_to_corrected_semantic_edge()
    test_committed_attempt_semantics_cannot_be_rewritten()
    test_page_variant_refinement_removes_stale_membership()
    test_verified_action_records_only_its_grounded_entry_execution()
    test_portable_selector_disambiguates_same_label_actions()
    test_variant_refinement_cascades_to_edges_and_capabilities()
    test_provisional_state_removal_retargets_only_uncommitted_attempt()
    test_provisional_state_removal_is_atomic_when_edge_has_unresolved_history()
    print("PASS graph schema v3 action_edges/attempts + v2 migration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
