from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import networkx as nx

from gui_rewalk.run_visual_traversal import (
    _prepare_environment_for_launch,
    _preserve_android_resume_surface,
    _preserve_desktop_resume_surface,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_action_execution import (
    _apply_scope_effects,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_entry_tools import (
    AutonomousEntryLedger,
    EntryStatus,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_region_tools import (
    AutonomousRegionRegistry,
    AutonomousRegionState,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_scope_state import (
    AutonomousScopeStateLedger,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_scheduling import (
    _entry_source_route,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_schema import (
    RESPONSE_SCHEMA,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_turn import (
    ObservedScene,
    ObservedScopeEffect,
    PendingAction,
    PreviousAssessment,
    parse_turn,
)


def _pending() -> PendingAction:
    return PendingAction(
        source=ObservedScene("s1", b"before", "Page"),
        event_index=0,
        primitive={"action_type": "click"},
        target="change",
        reason="test",
        history_index=0,
        evidence={},
    )


def test_scope_effect_parser_accepts_multiple_generic_scopes() -> None:
    payload = {
        "screen": {
            "name": "Page", "identity": "known",
            "variant": {
                "name": "changed", "identity": "known",
                "visible_predicates": [],
            },
        },
        "reason": "The attached frames show two scoped effects.",
        "previous_action": {
            "outcome": "changed",
            "reason": "Two known Regions changed.",
            "matches_intent": True,
            "failure_kind": None,
            "business_effect": None,
            "effects": [
                {
                    "scope_type": "region", "scope_name": "First",
                    "change_kind": "value", "before_value": "",
                    "after_value": "2",
                },
                {
                    "scope_type": "app_state", "scope_name": "session",
                    "change_kind": "state", "before_value": "idle",
                    "after_value": "active",
                },
            ],
        },
        "action": None,
    }
    turn, error = parse_turn(payload, has_previous=True)

    assert error == ""
    assert turn is not None
    assert [effect.scope_type for effect in turn.previous.effects] == [
        "region", "app_state"]
    assert turn.previous.effects[0].before_value == ""
    effect_properties = RESPONSE_SCHEMA["properties"]["previous_action"][
        "properties"]["effects"]["items"]["properties"]
    assert "minLength" not in effect_properties["before_value"]
    assert "minLength" not in effect_properties["after_value"]

    unchanged_payload = deepcopy(payload)
    unchanged_payload["previous_action"]["effects"][0]["after_value"] = ""
    unchanged_turn, unchanged_error = parse_turn(
        unchanged_payload, has_previous=True)
    assert unchanged_turn is None
    assert unchanged_error == (
        "previous_action.effects[0] requires distinct before/after values")


def test_only_structure_effects_invalidate_the_named_regions() -> None:
    state = AutonomousRegionState()
    state.observe_frame("f1", "s1")
    state.apply_agent_update([
        {"name": "First", "summary": "first", "coverage_complete": True},
        {"name": "Second", "summary": "second", "coverage_complete": True},
    ], frame_id="f1")
    registry = AutonomousRegionRegistry()
    for name in ("First", "Second"):
        region_ref, _ = registry.bind(
            page_name="Page", region_name=name, state_id="s1")
        state.set_region_ref(name, region_ref)
    host = SimpleNamespace(
        region_states={"page": state},
        region_registry=registry,
        scope_state_ledger=AutonomousScopeStateLedger(),
        pending_page_resurveys={},
        graph=SimpleNamespace(action_attempt=lambda _index: {"attempt_id": "a1"}),
    )
    assessment = PreviousAssessment(
        outcome="changed",
        reason="A value changed and another Region revealed controls.",
        effects=[
            ObservedScopeEffect("region", "First", "value", "1", "2"),
            ObservedScopeEffect(
                "region", "Second", "structure", "closed", "open"),
        ],
    )
    history: list[dict] = []

    recorded = _apply_scope_effects(
        host, _pending(), ObservedScene("s2", b"after", "Page"),
        assessment, history)

    assert len(recorded) == 2
    assert state.region("First")["coverage_complete"] is True
    assert state.region("Second")["coverage_complete"] is False
    assert host.pending_page_resurveys["page"]["region_name"] == "Second"
    assert history[-1]["kind"] == "scope_effects"


def test_multiple_region_state_effects_preserve_only_unaffected_occurrences() -> None:
    registry = AutonomousRegionRegistry()
    for name in ("First", "Second", "Third"):
        registry.bind(page_name="Page", region_name=name, state_id="s1")

    transitions = registry.record_scoped_transitions(
        page_name="Page", source_state_id="s1", destination_state_id="s2",
        trigger_entry_id="ae1", evidence_action_id="a1",
        effects=[
            {"region_name": "First", "effect_text": "changed", "effect_kind": "state"},
            {"region_name": "Second", "effect_text": "changed", "effect_kind": "structure"},
        ],
    )

    assert len(transitions) == 2
    for name in ("First", "Second"):
        assert registry.occurrence_state_ref("Page", name, "s2") != (
            registry.occurrence_state_ref("Page", name, "s1"))
    assert registry.occurrence_state_ref("Page", "Third", "s2") == (
        registry.occurrence_state_ref("Page", "Third", "s1"))


def test_page_modes_do_not_enumerate_variants_and_app_state_persists() -> None:
    ledger = AutonomousScopeStateLedger()
    ledger.record_page_mode(
        page_name="Page", scope_name="selection", before_value="normal",
        after_value="active", selected_occurrence_refs=["ro1"],
        evidence_action_id="a1", trigger_entry_id="ae1")
    assert ledger.current_page_mode_requirements("Page") == {
        "selection": "active"}
    assert ledger.completion_gaps()
    ledger.record_page_mode(
        page_name="Page", scope_name="selection", before_value="active",
        after_value="normal", selected_occurrence_refs=[],
        evidence_action_id="a2", trigger_entry_id="ae2")
    assert ledger.completion_gaps() == []
    ledger.record_app_state(
        scope_name="session", before_value="active", after_value="active",
        page_name="Other Page", state_id="s3", evidence_action_id="a3")
    restored = AutonomousScopeStateLedger.from_snapshot(ledger.snapshot())
    assert restored.app_states["session"]["current_value"] == "active"
    assert restored.app_states["session"]["observations"][0][
        "page_name"] == "Other Page"


def test_entry_discovered_in_page_mode_uses_observed_transition_to_prepare() -> None:
    entries = AutonomousEntryLedger()
    trigger_id = entries.record_agent_update(
        page_name="Page", region_name="Controls", frame_id="f1",
        observations=[{
            "target": "Enter mode", "operation": "enter", "subject": "mode",
        }],
    ).added[0]
    trigger_action = entries.begin_explicit_action(
        trigger_id, frame_id="f1", page_name="Page")
    entries.finish_action(
        trigger_action.action_id, action_executed=True, outcome_verified=True)
    target_id = entries.record_agent_update(
        page_name="Page", region_name="Controls", frame_id="f2",
        observations=[{
            "target": "Mode action", "operation": "act", "subject": "selection",
        }],
        required_page_modes={"selection": "active"},
    ).added[0]
    ledger = AutonomousScopeStateLedger()
    ledger.record_page_mode(
        page_name="Page", scope_name="selection", before_value="normal",
        after_value="active", selected_occurrence_refs=[],
        evidence_action_id="a1", trigger_entry_id=trigger_id)
    ledger.record_page_mode(
        page_name="Page", scope_name="selection", before_value="active",
        after_value="normal", selected_occurrence_refs=[],
        evidence_action_id="a2")
    graph = nx.DiGraph()
    graph.add_node("auto_state_v1")
    host = SimpleNamespace(
        protocol_map=SimpleNamespace(
            current_page="Page", current_variant="default",
            page_id=lambda _page: "p1", variant_id=lambda _page, _variant: "v1",
        ),
        graph=SimpleNamespace(graph=graph, routing_graph=graph),
        scope_state_ledger=ledger,
        entry_ledger=entries,
        region_registry=AutonomousRegionRegistry(),
    )

    ready, route = _entry_source_route(host, entries.get(target_id))

    assert ready is False
    assert route[0]["entry_id"] == trigger_id
    assert route[0]["to"] == "active"


def test_reviewed_group_conflict_splits_and_reopens_inferred_entry() -> None:
    registry = AutonomousRegionRegistry()
    original_ref, _ = registry.bind(
        page_name="Page", region_name="First", state_id="s1")
    registry.bind(
        page_name="Page", region_name="Second", state_id="s1",
        equivalent_to_region_ref=original_ref)
    second_occurrence = registry.occurrence_ref("Page", "Second")

    entries = AutonomousEntryLedger()
    first = entries.record_agent_update(
        page_name="Page", region_name="First", frame_id="f1",
        observations=[{"target": "Open", "operation": "open", "subject": "item"}],
        owner_region_ref=original_ref,
        representative_occurrence_ref=registry.occurrence_ref("Page", "First"),
    ).added[0]
    action = entries.begin_explicit_action(
        first, frame_id="f1", page_name="Page")
    entries.finish_action(
        action.action_id, action_executed=True, outcome_verified=True)
    second = entries.record_agent_update(
        page_name="Page", region_name="Second", frame_id="f1",
        observations=[{
            "target": "Open", "operation": "open", "subject": "item",
            "equivalent_to_entry_id": first,
            "equivalence_reason": "same reviewed operation",
        }],
        owner_region_ref=original_ref,
        representative_occurrence_ref=second_occurrence,
    ).added[0]
    assert entries.get(second).status is EntryStatus.INFERRED

    _old_ref, new_ref, occurrence_ref = registry.split_occurrence(
        page_name="Page", region_name="Second",
        reason="Latest reviewed controls conflict with the group")
    reopened = entries.reopen_occurrence_after_group_conflict(
        occurrence_ref=occurrence_ref, new_region_ref=new_ref,
        reason="Latest reviewed controls conflict with the group")

    assert reopened == (second,)
    assert entries.get(second).status is EntryStatus.DISCOVERED
    assert entries.get(second).task_eligible is True
    assert entries.get(second).owner_region_ref == new_ref


def test_android_resume_preserves_only_a_confirmed_foreground_surface() -> None:
    env = object()
    assert _preserve_android_resume_surface(
        env=env, app_name="target", resume_graph_path="graph.json",
        is_android=True, is_local_html=False,
        foreground_check=lambda actual_env, app: (
            actual_env is env and app == "target"),
    ) is True
    assert _preserve_android_resume_surface(
        env=env, app_name="target", resume_graph_path="graph.json",
        is_android=True, is_local_html=False,
        foreground_check=lambda *_args: None,
    ) is False
    assert _preserve_android_resume_surface(
        env=env, app_name="target", resume_graph_path=None,
        is_android=True, is_local_html=False,
        foreground_check=lambda *_args: True,
    ) is False

    class Env:
        reset_count = 0

        def reset(self):
            self.reset_count += 1

    kept = Env()
    assert _prepare_environment_for_launch(
        env=kept, app_name="target", resume_graph_path="graph.json",
        is_android=True, is_local_html=False,
        foreground_check=lambda *_args: True,
    ) is True
    assert kept.reset_count == 0
    restarted = Env()
    assert _prepare_environment_for_launch(
        env=restarted, app_name="target", resume_graph_path="graph.json",
        is_android=True, is_local_html=False,
        foreground_check=lambda *_args: False,
    ) is False
    assert restarted.reset_count == 1


def test_desktop_resume_preserves_only_a_bound_target_surface() -> None:
    env = object()

    class Owner:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def bind_active(self, app_name):
            self.calls.append(app_name)
            return self.result

    kept_owner = Owner(True)
    assert _preserve_desktop_resume_surface(
        env=env, app_name="clocks", resume_graph_path="ledger.json",
        is_android=False, is_local_html=False,
        desktop_window_owner=kept_owner,
    ) is True
    assert kept_owner.calls == ["clocks"]

    class Env:
        reset_count = 0

        def reset(self):
            self.reset_count += 1

    restarted = Env()
    assert _prepare_environment_for_launch(
        env=restarted, app_name="clocks", resume_graph_path="ledger.json",
        is_android=False, is_local_html=False,
        desktop_window_owner=Owner(False),
        preserve_desktop_resume=True,
    ) is False
    assert restarted.reset_count == 1

    legacy = Env()
    assert _prepare_environment_for_launch(
        env=legacy, app_name="clocks", resume_graph_path="graph.json",
        is_android=False, is_local_html=False,
        desktop_window_owner=Owner(True),
        preserve_desktop_resume=False,
    ) is False
    assert legacy.reset_count == 1
