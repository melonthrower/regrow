"""Focused offline contract for phase-1 effect-observation induction."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.graph.state_graph import StateGraph  # noqa: E402
from gui_rewalk.run_capability_induction import main as run_capability_induction  # noqa: E402
from gui_rewalk.src.core.graph.effect_observation import (  # noqa: E402
    EFFECT_OBSERVATION_SCHEMA,
    EffectObservationValidationError,
    append_effect_observation,
    normalize_effect_observation,
)
from gui_rewalk.src.core.scenario.capability_induction import (  # noqa: E402
    CAPABILITY_GRAPH_SCHEMA,
    AUTONOMOUS_ELEMENT_UID_PREFIX,
    attach_source_region_refs,
    project_autonomous_inventory,
    induce_capability_graph,
    load_capability_graph,
    save_capability_graph,
)
from gui_rewalk.src.core.scenario.capability_task_synthesis import (  # noqa: E402
    synthesize_cleanup_cycle_instructions,
)




def observation(value="07:30", *, region_ref="r:alarm-list:form", bindings=None):
    return {
        "schema_version": EFFECT_OBSERVATION_SCHEMA,
        "capability_name": "Create alarm",
        "reason": "Save created an alarm shown in the list.",
        "effect_kind": "object_creation",
        "observed_changes": [{
            "scope": {"region_ref": region_ref}, "fact": "alarm.time",
            "before": None, "after": value,
        }],
        "parameter_bindings": bindings or {},
        "predicate_candidate": "The alarm list shows the saved time.",
        "verdict": "supported",
    }


def attempt(
    index, label, *, entry=False, effect=None, probe="probe:1",
    committed=True, outcome="executed", action=None,
):
    evidence = {"probe_id": probe}
    if entry:
        evidence.update({
            "explicit_entry_task": True, "entry_id": "add-alarm",
            "source_region_ref": "r:alarm-list:toolbar",
        })
    if effect is not None:
        evidence["effect_observations"] = [effect]
    return {
        "action_index": index, "attempt_id": f"a{index}", "action_edge_id": f"e{index}",
        "source": "alarm-list", "committed": committed, "outcome": outcome,
        "action": action or {
            "action_type": "CLICK",
            "selector": {"element_label": label, "x": 100}},
        "evidence": evidence,
    }


def graph_for(attempts):
    graph = StateGraph("clock")
    graph.add_state(
        "alarm-list", [], "alarm-list.png", "clock",
        page_id="alarms", variant_id="empty",
    )
    graph.action_edges = [
        {"action_edge_id": item["action_edge_id"], "attempts": [item]}
        for item in attempts
    ]
    return graph


def test_object_removal_is_a_supported_induced_capability() -> None:
    removed = observation(
        "absent", region_ref="r:notes:list", bindings={"title": "Draft A"})
    removed.update({
        "capability_name": "Delete quick note",
        "reason": "The selected Draft A row disappeared from the notes list.",
        "effect_kind": "object_removal",
        "observed_changes": [{
            "scope": {"region_ref": "r:notes:list"},
            "fact": "note.title",
            "before": "Draft A",
            "after": "absent",
        }],
        "predicate_candidate": "The notes list no longer shows Draft A.",
    })

    normalized = normalize_effect_observation(removed)
    result = induce_capability_graph(graph_for([
        attempt(1, "Delete", entry=True, effect=removed),
    ]))

    assert normalized["effect_kind"] == "object_removal"
    assert [item["name"] for item in result["capabilities"]] == [
        "Delete quick note"]
    capability = result["capabilities"][0]
    assert capability["effects"][0]["kind"] == "object_removal"
    assert capability["execution_recipe"][0]["selector"]["element_label"] == (
        "Delete")


def test_distinct_real_values_form_one_parameterized_recipe() -> None:
    created_a = observation(
        "Draft A", region_ref="r:notes:list", bindings={"title": "Draft A"})
    created_b = observation(
        "Draft B", region_ref="r:notes:list", bindings={"title": "Draft B"})
    for created in (created_a, created_b):
        created.update({
            "capability_name": "Create quick note",
            "reason": "The typed title appeared as a new note row.",
            "effect_kind": "object_creation",
            "observed_changes": [{
                "scope": {"region_ref": "r:notes:list"},
                "fact": "note.title",
                "before": "absent",
                "after": created["parameter_bindings"]["title"],
            }],
            "predicate_candidate": "The notes list shows the new title.",
        })
    create_graph = graph_for([
        attempt(1, "Add", entry=True, probe="create-a"),
        attempt(
            2, "Title", effect=created_a, probe="create-a",
            action={"action_type": "TYPE", "parameters": {"text": "Draft A"}}),
        attempt(3, "Add", entry=True, probe="create-b"),
        attempt(
            4, "Title", effect=created_b, probe="create-b",
            action={"action_type": "TYPE", "parameters": {"text": "Draft B"}}),
    ])

    created = induce_capability_graph(create_graph)["capabilities"][0]

    assert created["verification_level"] == "effect_verified"
    assert created["execution_recipe"][1]["parameters"]["text"] == "{{title}}"
    assert created["parameters"] == [{
        "name": "title", "domain": {"values": ["Draft A", "Draft B"]}}]
    assert created["effects"][0]["changes"][0]["value"] == {
        "value_from_parameter": "title"}

    def removed(title: str) -> dict:
        value = observation(
            "absent", region_ref="r:notes:list", bindings={"title": title})
        value.update({
            "capability_name": "Delete quick note",
            "reason": "The selected note row visibly disappeared.",
            "effect_kind": "object_removal",
            "observed_changes": [{
                "scope": {"region_ref": "r:notes:list"},
                "fact": "note.title",
                "before": title,
                "after": "absent",
            }],
            "predicate_candidate": "The notes list no longer shows the title.",
        })
        return value

    removal_graph = graph_for([
        attempt(
            1, "Draft A", entry=True, effect=removed("Draft A"),
            probe="remove-a"),
        attempt(
            2, "Draft B", entry=True, effect=removed("Draft B"),
            probe="remove-b"),
    ])
    removed_capability = induce_capability_graph(
        removal_graph)["capabilities"][0]

    assert removed_capability["verification_level"] == "effect_verified"
    assert removed_capability["execution_recipe"][0]["selector"][
        "element_label"] == "{{title}}"
    assert removed_capability["parameters"][0]["domain"]["values"] == [
        "Draft A", "Draft B"]


def test_effect_only_binding_is_not_an_executable_parameter() -> None:
    graph = graph_for([
        attempt(1, "Add", entry=True, effect=observation(
            "07:30", bindings={"time": "07:30"}), probe="p1"),
        attempt(2, "Add", entry=True, effect=observation(
            "08:00", bindings={"time": "08:00"}), probe="p2"),
    ])

    capability = induce_capability_graph(graph)["capabilities"][0]

    assert capability["verification_level"] == "executable"
    assert "parameters" not in capability
    assert capability["parameter_candidates"] == {
        "time": ["07:30", "08:00"]}


def test_parameter_bindings_require_portable_scalar_values() -> None:
    invalid_name = observation(bindings={"city query": "Tokyo"})
    try:
        normalize_effect_observation(invalid_name)
    except EffectObservationValidationError as exc:
        assert "portable identifiers" in str(exc)
    else:
        raise AssertionError("non-portable parameter name must fail closed")

    structured_value = observation(bindings={"query": {"text": "Tokyo"}})
    try:
        normalize_effect_observation(structured_value)
    except EffectObservationValidationError as exc:
        assert "non-null JSON scalars" in str(exc)
    else:
        raise AssertionError("structured parameter value must fail closed")


def test_object_creation_recipe_uses_observed_entry_and_query_prefix() -> None:
    graph = StateGraph("clock")
    for state_id, variant_id in (
        ("world-empty", "empty"),
        ("world-dialog", "add_dialog"),
        ("world-results", "search_results"),
        ("world-populated", "populated"),
    ):
        graph.add_state(
            state_id, [], f"{state_id}.png", "clock",
            page_name="World", page_id="clock.world",
            variant_id=variant_id,
        )

    def business(
        kind: str, name: str, fact: str, before: str, after: str,
        bindings: dict,
    ) -> dict:
        return {
            "schema_version": EFFECT_OBSERVATION_SCHEMA,
            "capability_name": name,
            "reason": f"{fact} visibly changed.",
            "effect_kind": kind,
            "observed_changes": [{
                "scope": {"region_ref": "r.world.city_list"},
                "fact": fact,
                "before": before,
                "after": after,
            }],
            "parameter_bindings": bindings,
            "predicate_candidate": f"{fact} is {after}.",
            "verdict": "supported",
        }

    events = []

    def action(
        index: int, source: str, target: str, primitive: dict,
        evidence: dict,
    ) -> None:
        event = {
            "action_index": index,
            "attempt_id": f"attempt-{index}",
            "action_edge_id": f"edge-{index}",
            "source": source,
            "target": target,
            "committed": True,
            "landing_verified": True,
            "outcome": "observed_change",
            "action": primitive,
            "evidence": evidence,
        }
        events.append(event)

    index = 0
    for suffix, query, city in (
        ("a", "z", "Alpha"),
        ("b", "a", "Zulu"),
    ):
        index += 1
        action(index, "world-empty", "world-dialog", {
            "action_type": "CLICK",
            "selector": {"element_label": "Add city"},
        }, {
            "probe_id": f"entry-{suffix}",
            "explicit_entry_task": True,
            "entry_id": "add-city",
            "source_region_ref": "r.world.toolbar",
        })
        index += 1
        action(index, "world-dialog", "world-results", {
            "action_type": "TYPE",
            "selector": {"element_label": "City query"},
            "parameters": {"text": query},
        }, {
            "probe_id": f"query-{suffix}",
            "region_probe_task": True,
            "region_probe_start": True,
            "entry_id": "",
            "source_region_ref": "r.world.add_dialog",
            "effect_observations": [business(
                "query_result", "Search cities", "city.query",
                "empty", query, {"city_query": query})],
        })
        index += 1
        action(index, "world-results", "world-populated", {
            "action_type": "CLICK",
            "selector": {"element_label": city},
        }, {
            "probe_id": f"create-{suffix}",
            "region_probe_task": True,
            "region_probe_start": True,
            "entry_id": "",
            "source_region_ref": "r.world.add_dialog",
            "effect_observations": [business(
                "object_creation", "Add city", "city.row",
                "absent", city, {"selected_result": city})],
        })
        index += 1
        action(index, "world-populated", "world-empty", {
            "action_type": "CLICK",
            "selector": {"element_label": city},
        }, {
            "probe_id": f"remove-{suffix}",
            "region_probe_task": True,
            "region_probe_start": True,
            "entry_id": "",
            "source_region_ref": "r.world.city_list",
            "effect_observations": [business(
                "object_removal", "Delete city", "city.row",
                city, "absent", {"selected_result": city})],
        })
    graph.action_edges = [{
        "action_edge_id": event["action_edge_id"],
        "attempts": [event],
    } for event in events]

    induced = induce_capability_graph(graph)
    created = next(
        item for item in induced["capabilities"]
        if item["name"] == "Add city")
    queried = next(
        item for item in induced["capabilities"]
        if item["name"] == "Search cities")
    removed = next(
        item for item in induced["capabilities"]
        if item["name"] == "Delete city")

    assert created["verification_level"] == "effect_verified"
    assert created["entry_surfaces"][0]["state_id"] == "world-empty"
    assert [step["action_type"] for step in created["execution_recipe"]] == [
        "CLICK", "TYPE", "CLICK"]
    assert created["execution_recipe"][1]["parameters"]["text"] == (
        "{{city_query}}")
    assert created["execution_recipe"][2]["selector"]["element_label"] == (
        "{{selected_result}}")
    assert [item["name"] for item in created["parameters"]] == [
        "city_query", "selected_result"]
    assert len(created["evidence_refs"]) == 6
    assert created["parameter_examples"] == [
        {"city_query": "a", "selected_result": "Zulu"},
        {"city_query": "z", "selected_result": "Alpha"},
    ]
    assert len(induced["relations"]) == 1

    cleanup_task = synthesize_cleanup_cycle_instructions(induced)[0].to_dict()
    assert cleanup_task["capability_refs"][0]["params"] == {
        "city_query": "a", "selected_result": "Zulu"}
    assert cleanup_task["capability_refs"][1]["params"] == {
        "selected_result": "Zulu"}


    assert queried["entry_surfaces"][0]["state_id"] == "world-empty"
    assert [step["action_type"] for step in queried["execution_recipe"]] == [
        "CLICK", "TYPE"]
    assert removed["entry_surfaces"][0]["state_id"] == "world-populated"
    assert [step["action_type"] for step in removed["execution_recipe"]] == [
        "CLICK"]

    events[5]["target"] = "world-dialog"
    broken = induce_capability_graph(graph)
    broken_created = next(
        item for item in broken["capabilities"]
        if item["name"] == "Add city")
    assert broken_created["verification_level"] == "discovered"
    assert broken["relations"] == []


def test_inverse_effects_and_state_cycle_induce_cleanup_relation() -> None:
    graph = StateGraph("notes")

    for state_id, variant_id in (
        ("notes-empty", "empty"),
        ("notes-populated", "populated"),
    ):
        graph.add_state(
            state_id, [], f"{state_id}.png", "notes",
            page_name="Notes", page_id="notes.main",
            variant_id=variant_id,
        )

    def effect(kind: str, title: str) -> dict:
        created = kind == "object_creation"
        return {
            "schema_version": EFFECT_OBSERVATION_SCHEMA,
            "capability_name": (
                "Create quick note" if created else "Delete quick note"),
            "reason": (
                "The note row appeared." if created
                else "The note row disappeared."),
            "effect_kind": kind,
            "observed_changes": [{
                "scope": {"region_ref": "r:notes:list"},
                "fact": "note.title",
                "before": "absent" if created else title,
                "after": title if created else "absent",
            }],
            "parameter_bindings": {"title": title},
            "predicate_candidate": (
                "The note row is visible." if created
                else "The note row is absent."),
            "verdict": "supported",
        }

    def event(
        index: int, *, title: str, create: bool, probe: str,
        target: str = "",
    ) -> dict:
        source = "notes-empty" if create else "notes-populated"
        destination = target or (
            "notes-populated" if create else "notes-empty")
        evidence = {
            "probe_id": probe,
            "source_region_ref": (
                "r:notes:toolbar" if create else "r:notes:list"),
            "effect_observations": [effect(
                "object_creation" if create else "object_removal", title)],
        }
        if create:
            evidence.update({
                "explicit_entry_task": True,
                "entry_id": "create-note",
            })
        else:
            evidence.update({
                "region_probe_task": True,
                "region_probe_start": True,
                "entry_id": "",
            })
        return {
            "action_index": index,
            "attempt_id": f"attempt-{index}",
            "action_edge_id": f"edge-{index}",
            "source": source,
            "target": destination,
            "committed": True,
            "landing_verified": True,
            "outcome": "observed_change",
            "action": {
                "action_type": "CLICK",
                "selector": {"element_label": title},
            },
            "evidence": evidence,
        }

    events = [
        event(1, title="Draft A", create=True, probe="create-a"),
        event(2, title="Draft A", create=False, probe="remove-a"),
        event(3, title="Draft B", create=True, probe="create-b"),
        event(4, title="Draft B", create=False, probe="remove-b"),
    ]
    graph.action_edges = [{
        "action_edge_id": item["action_edge_id"],
        "attempts": [item],
    } for item in events]

    induced = induce_capability_graph(graph)

    assert len(induced["relations"]) == 1
    relation = induced["relations"][0]
    assert relation["relation_type"] == "cleanup_cycle"
    assert relation["baseline_state_id"] == "notes-empty"
    assert relation["effect_state_id"] == "notes-populated"
    assert relation["parameter_links"] == [{
        "source_parameter": "title",
        "cleanup_parameter": "title",
        "values": ["Draft A", "Draft B"],
    }]
    assert len(relation["evidence_refs"]) == 2
    capabilities = {
        item["capability_id"]: item for item in induced["capabilities"]}
    assert capabilities[relation["source_capability_id"]][
        "effects"][0]["kind"] == "object_creation"
    assert capabilities[relation["cleanup_capability_id"]][
        "effects"][0]["kind"] == "object_removal"

    events[-1]["target"] = "notes-populated"
    graph.action_edges[-1]["attempts"] = [events[-1]]
    assert induce_capability_graph(graph)["relations"] == []


def test_induction_ignores_obsolete_singular_effect_observation() -> None:
    old_attempt = attempt(1, "Add", entry=True)
    old_attempt["evidence"]["effect_observation"] = observation()

    result = induce_capability_graph(graph_for([old_attempt]))

    assert result["capabilities"] == []


def test_reviewed_region_action_projects_stable_element_and_recipe_ref() -> None:
    graph = StateGraph("clock")
    graph.add_state(
        "stopwatch-running", [], "stopwatch.png", "clock",
        page_name="Stopwatch", page_id="clock.stopwatch",
        variant_id="running", perception_mode="autonomous_vlm",
    )
    element_uid = AUTONOMOUS_ELEMENT_UID_PREFIX + "start-stopwatch"
    effect = observation(region_ref="rg-stopwatch")
    effect.update({
        "capability_name": "Start stopwatch",
        "effect_kind": "state_change",
        "observed_changes": [{
            "scope": {"region_ref": "rg-stopwatch"},
            "fact": "stopwatch.status",
            "before": "stopped",
            "after": "running",
        }],
        "predicate_candidate": "The stopwatch visibly reads running.",
    })
    graph.record_action_event(
        source="stopwatch-running",
        action={"action_type": "CLICK"},
        element_id=element_uid,
        element_label="Start",
        region="Stopwatch controls",
        committed=True,
        evidence={
            "probe_id": "probe:stopwatch:1",
            "region_probe_task": True,
            "region_probe_start": True,
            "source_region_ref": "rg-stopwatch",
            "click_review": {
                "decision": "approve",
                "observed_target": "Start",
                "point_matches_target": True,
                "target_matches_request": True,
                "risk": "safe",
            },
            "effect_observations": [effect],
        },
    )
    regions = {"region_groups": {"groups": [{
        "region_ref": "rg-stopwatch",
        "representative": {
            "page_name": "Stopwatch",
            "region_name": "Stopwatch controls",
            "state_ids": ["stopwatch-running"],
        },
        "occurrences": [],
    }]}}

    capability_graph = induce_capability_graph(graph)
    capability = capability_graph["capabilities"][0]
    surface = capability["entry_surfaces"][0]
    assert surface["entry_id"] == ""
    assert surface["element_uid"] == element_uid
    assert capability["execution_recipe"][0]["selector"] == {
        "element_id": element_uid,
        "element_label": "Start",
        "region": "Stopwatch controls",
        "region_ids": ["rg-stopwatch"],
    }

    assert project_autonomous_inventory(
        graph, {"entries": [], "pending_actions": []}, regions) == 1
    elements = graph.graph.nodes["stopwatch-running"]["elements"]
    assert elements == [{
        "id": 0,
        "name": "Start",
        "bbox_xywh": [0, 0, 1, 1],
        "center": [0, 0],
        "el_type": "control",
        "interactive": True,
        "category": "shallow",
        "source": "autonomous_action_evidence",
        "uid": element_uid,
        "region": "Stopwatch controls",
        "region_id": "rg-stopwatch",
        "geometry_status": "semantic_only",
    }]


def test_reviewed_android_input_projects_input_element_and_parameterized_text(
) -> None:
    graph = StateGraph("clock")
    graph.add_state(
        "city-search", [], "city-search.png", "clock",
        page_name="World", page_id="clock.world",
        variant_id="search", perception_mode="autonomous_vlm",
    )
    element_uid = AUTONOMOUS_ELEMENT_UID_PREFIX + "city-query"
    effect = {
        "schema_version": EFFECT_OBSERVATION_SCHEMA,
        "capability_name": "Search cities",
        "reason": "Typing Oslo revealed a matching result row.",
        "effect_kind": "query_result",
        "observed_changes": [{
            "scope": {"region_ref": "rg-city-search"},
            "fact": "city.search_results",
            "before": "empty",
            "after": "Oslo result visible",
        }],
        "parameter_bindings": {"query": "Oslo"},
        "predicate_candidate": "The result list visibly contains Oslo.",
        "verdict": "supported",
    }
    graph.record_action_event(
        source="city-search",
        action={
            "action_type": "input_text",
            "x": 500,
            "y": 300,
            "text": "Oslo",
        },
        element_id=element_uid,
        element_label="City search field",
        region="Search panel",
        committed=True,
        evidence={
            "probe_id": "probe:city-search:1",
            "region_probe_task": True,
            "region_probe_start": True,
            "source_region_ref": "rg-city-search",
            "click_review": {
                "decision": "approve",
                "observed_target": "City search field",
                "point_matches_target": True,
                "target_matches_request": True,
                "risk": "safe",
            },
            "effect_observations": [effect],
        },
    )
    regions = {"region_groups": {"groups": [{
        "region_ref": "rg-city-search",
        "representative": {
            "page_name": "World",
            "region_name": "Search panel",
            "state_ids": ["city-search"],
        },
        "occurrences": [],
    }]}}

    capability = induce_capability_graph(graph)["capabilities"][0]

    assert capability["execution_recipe"] == [{
        "action_type": "INPUT_TEXT",
        "text": "{{query}}",
        "selector": {
            "element_id": element_uid,
            "element_label": "City search field",
            "region": "Search panel",
            "region_ids": ["rg-city-search"],
        },
    }]
    assert project_autonomous_inventory(
        graph, {"entries": [], "pending_actions": []}, regions) == 1
    element = graph.graph.nodes["city-search"]["elements"][0]
    assert element["uid"] == element_uid
    assert element["el_type"] == "input"
    assert element["category"] == "input"


def test_record_only_entry_projects_to_the_operation_catalog() -> None:
    graph = StateGraph("reader")
    graph.add_state(
        "reading", [], "reading.png", "reader",
        page_name="Reading", page_id="reader.reading",
        variant_id="default", perception_mode="autonomous_vlm",
    )
    entries = {
        "schema": "gui_rewalk.autonomous_entries.v7",
        "entries": [{
            "entry_id": "ae-next",
            "page_name": "Reading",
            "region_name": "Content controls",
            "target": "Next item",
            "operation": "activate",
            "subject": "Current content",
            "status": "recorded",
            "exploration_policy": "record_only",
            "task_eligible": False,
            "source_state_id": "reading",
            "source_state_ids": ["reading"],
        }],
        "pending_actions": [],
    }
    regions = {"region_groups": {"groups": [{
        "region_ref": "rg-content-controls",
        "representative": {
            "page_name": "Reading",
            "region_name": "Content controls",
            "state_ids": ["reading"],
        },
        "occurrences": [],
    }]}}

    assert project_autonomous_inventory(graph, entries, regions) == 1
    element = graph.graph.nodes["reading"]["elements"][0]
    assert element["operation"] == "activate"
    assert element["entry_status"] == "recorded"
    assert element["exploration_policy"] == "record_only"

    catalog = induce_capability_graph(graph)["operation_catalog"]
    assert catalog == [{
        "entry_id": "ae-next",
        "operation": "activate",
        "subject": "Current content",
        "target": "Next item",
        "region_ref": "rg-content-controls",
        "page_id": "reader.reading",
        "exploration_policy": "record_only",
        "evidence_level": "observed_only",
        "state_ids": ["reading"],
    }]


def test_same_region_target_allows_distinct_operation_types() -> None:
    graph = StateGraph("calc")
    graph.add_state(
        "sheet", [], "sheet.png", "calc",
        page_name="Sheet", page_id="calc.sheet",
        variant_id="default", perception_mode="autonomous_vlm",
    )
    entries = {
        "entries": [
            {
                "entry_id": "cell-click",
                "page_name": "Sheet",
                "region_name": "Grid",
                "target": "Any visible cell",
                "operation": "click",
                "source_state_ids": ["sheet"],
            },
            {
                "entry_id": "cell-double-click",
                "page_name": "Sheet",
                "region_name": "Grid",
                "target": "Any visible cell",
                "operation": "double_click",
                "source_state_ids": ["sheet"],
            },
            {
                "entry_id": "grid-scroll-down",
                "page_name": "Sheet",
                "region_name": "Grid",
                "target": "Spreadsheet grid",
                "operation": "scroll",
                "operation_scope": "region",
                "direction": "down",
                "source_state_ids": ["sheet"],
            },
            {
                "entry_id": "grid-scroll-right",
                "page_name": "Sheet",
                "region_name": "Grid",
                "target": "Spreadsheet grid",
                "operation": "scroll",
                "operation_scope": "region",
                "direction": "right",
                "source_state_ids": ["sheet"],
            },
        ],
        "pending_actions": [],
    }
    regions = {"region_groups": {"groups": [{
        "region_ref": "rg-grid",
        "representative": {
            "page_name": "Sheet",
            "region_name": "Grid",
            "state_ids": ["sheet"],
        },
        "occurrences": [],
    }]}}

    assert project_autonomous_inventory(graph, entries, regions) == 4
    assert {
        item["operation"] for item in graph.graph.nodes["sheet"]["elements"]
    } == {"click", "double_click", "scroll"}


def test_invalidated_entry_is_not_projected_as_an_operation() -> None:
    graph = StateGraph("reader")
    graph.add_state(
        "reading", [], "reading.png", "reader",
        page_name="Reading", page_id="reader.reading",
        variant_id="default", perception_mode="autonomous_vlm",
    )
    entries = {
        "schema": "gui_rewalk.autonomous_entries.v8",
        "entries": [{
            "entry_id": "ae-hallucinated",
            "page_name": "Reading",
            "region_name": "Content controls",
            "target": "Imagined icon",
            "status": "invalidated",
            "task_eligible": False,
            "source_state_id": "reading",
            "source_state_ids": ["reading"],
        }],
        "pending_actions": [],
    }
    regions = {"region_groups": {"groups": [{
        "region_ref": "rg-content-controls",
        "representative": {
            "page_name": "Reading",
            "region_name": "Content controls",
            "state_ids": ["reading"],
        },
        "occurrences": [],
    }]}}

    assert project_autonomous_inventory(graph, entries, regions) == 0
    assert graph.graph.nodes["reading"]["elements"] == []


def test_world_add_city_multi_variant_projection_uses_exact_occurrences(
    tmp_path,
):
    graph = StateGraph("clock")
    variants = (
        ("s_world_empty_01", "world.empty"),
        ("s_world_add_dialog_01", "world.add_dialog"),
        ("s_world_results_01", "world.search_results"),
        ("s_world_populated_01", "world.populated"),
    )
    for state_id, variant_id in variants:
        graph.add_state(
            state_id, [], f"{state_id}.png", "clock",
            page_name="World", page_id="clock.world",
            variant_id=variant_id,
            perception_mode="autonomous_vlm",
        )
    entries = {
        "schema": "gui_rewalk.autonomous_entries.v4",
        "entries": [
            {
                "entry_id": "ae-world-add-city",
                "page_name": "World",
                "region_name": "World Toolbar",
                "target": "Add city",
                "control_type": "button",
                "source_state_id": "s_world_empty_01",
                "source_state_ids": ["s_world_empty_01"],
            },
            {
                "entry_id": "ae-world-dismiss",
                "page_name": "World",
                "region_name": "Add City Dialog",
                "target": "Dismiss dialog",
                "control_type": "button",
                "source_state_id": "s_world_add_dialog_01",
                "source_state_ids": [
                    "s_world_add_dialog_01", "s_world_results_01"],
            },
            {
                "entry_id": "ae-world-delete-city",
                "page_name": "World",
                "region_name": "World City List",
                "target": "Delete city",
                "control_type": "button",
                "source_state_id": "s_world_populated_01",
                "source_state_ids": ["s_world_populated_01"],
            },
        ],
        "pending_actions": [],
    }
    regions = {
        "schema": "gui_rewalk.autonomous_regions_by_page.v5",
        "region_groups": {
            "schema": "gui_rewalk.autonomous_region_groups.v2",
            "groups": [
                {
                    "region_ref": "r.world.toolbar",
                    "representative": {
                        "page_name": "World",
                        "region_name": "World Toolbar",
                    },
                    "occurrences": [{
                        "page_name": "World",
                        "region_name": "World Toolbar",
                        "state_ids": ["s_world_empty_01"],
                    }],
                },
                {
                    "region_ref": "r.world.add_dialog",
                    "representative": {
                        "page_name": "World",
                        "region_name": "Add City Dialog",
                    },
                    "occurrences": [{
                        "page_name": "World",
                        "region_name": "Add City Dialog",
                        "state_ids": [
                            "s_world_add_dialog_01",
                            "s_world_results_01",
                        ],
                    }],
                },
                {
                    "region_ref": "r.world.city_list",
                    "representative": {
                        "page_name": "World",
                        "region_name": "World City List",
                    },
                    "occurrences": [{
                        "page_name": "World",
                        "region_name": "World City List",
                        "state_ids": [
                            "s_world_empty_01",
                            "s_world_populated_01",
                        ],
                    }],
                },
            ],
        },
    }

    assert project_autonomous_inventory(graph, entries, regions) == 3
    elements = {
        state_id: graph.graph.nodes[state_id]["elements"]
        for state_id, _variant_id in variants
    }
    blocks = {
        state_id: {
            item["region_id"]
            for item in graph.graph.nodes[state_id]["semantic_blocks"]
        }
        for state_id, _variant_id in variants
    }
    assert blocks == {
        "s_world_empty_01": {"r.world.toolbar", "r.world.city_list"},
        "s_world_add_dialog_01": {"r.world.add_dialog"},
        "s_world_results_01": {"r.world.add_dialog"},
        "s_world_populated_01": {"r.world.city_list"},
    }
    assert [item["name"] for item in elements["s_world_empty_01"]] == [
        "Add city"]
    assert elements["s_world_add_dialog_01"][0]["uid"] == (
        "autonomous-entry:ae-world-dismiss")
    assert elements["s_world_results_01"][0]["uid"] == (
        "autonomous-entry:ae-world-dismiss")
    assert all(
        item["name"] != "Add city"
        for state_id in elements if state_id != "s_world_empty_01"
        for item in elements[state_id]
    )
    page_id = next(iter(graph.pages))
    assert len(graph.pages[page_id]["variants"]) == 4

    path = tmp_path / "annotated_graph.json"
    graph.save(str(path))
    loaded = StateGraph.load(str(path))
    assert len(loaded.pages[page_id]["variants"]) == 4
    assert loaded.graph.nodes["s_world_results_01"]["elements"][0]["uid"] == (
        "autonomous-entry:ae-world-dismiss")


def test_multi_variant_projection_rejects_legacy_page_only_region():
    graph = StateGraph("clock")
    for state_id, variant_id in (
        ("s_world_empty_01", "world.empty"),
        ("s_world_populated_01", "world.populated"),
    ):
        graph.add_state(
            state_id, [], f"{state_id}.png", "clock",
            page_name="World", page_id="clock.world",
            variant_id=variant_id,
            perception_mode="luna_autonomous",
        )
    entries = {
        "entries": [{
            "entry_id": "ae-world-add-city",
            "page_name": "World",
            "region_name": "World Toolbar",
            "target": "Add city",
            "source_state_id": "s_world_empty_01",
        }],
        "pending_actions": [],
    }
    regions = {
        "region_groups": {
            "groups": [{
                "region_ref": "r.world.toolbar",
                "representative": {
                    "page_name": "World",
                    "region_name": "World Toolbar",
                },
                "occurrences": [],
            }],
        },
    }

    try:
        project_autonomous_inventory(graph, entries, regions)
    except ValueError as exc:
        assert "needs explicit State occurrence membership" in str(exc)
        assert "found 2 candidate States" in str(exc)
    else:
        raise AssertionError(
            "multi-Variant legacy Region evidence must fail closed")



def main() -> int:
    raw = observation()
    normal = normalize_effect_observation(raw)
    assert normal["schema_version"] == EFFECT_OBSERVATION_SCHEMA
    appended = append_effect_observation([], raw)
    assert len(appended) == 1 and raw == observation()
    try:
        normalize_effect_observation(observation(region_ref=""))
    except EffectObservationValidationError:
        pass
    else:
        raise AssertionError("supported observations must fail closed without region_ref")

    for field, value in (("observed_changes", {}), ("parameter_bindings", [])):
        malformed = observation()
        malformed[field] = value
        try:
            normalize_effect_observation(malformed)
        except EffectObservationValidationError:
            pass
        else:
            raise AssertionError(f"{field} must fail closed on a wrong type")

    graph = graph_for([attempt(1, "Add", entry=True)])
    graph.action_edges[0]["attempts"][0]["evidence"]["effect_observations"] = {}
    try:
        graph.append_effect_observation(1, observation())
    except ValueError:
        pass
    else:
        raise AssertionError("non-list effect_observations must fail closed")

    graph = graph_for([
        attempt(1, "Add", entry=True),
        attempt(2, "Time"),
        attempt(3, "Save", effect=observation()),
    ])
    result = induce_capability_graph(graph, "digest")
    assert result["schema_version"] == CAPABILITY_GRAPH_SCHEMA
    assert len(result["capabilities"]) == 1
    capability = result["capabilities"][0]
    assert [step["selector"]["element_label"] for step in capability["execution_recipe"]] == ["Add", "Time", "Save"]
    assert all("x" not in step["selector"] for step in capability["execution_recipe"])
    assert capability["entry_surfaces"][0]["region_ref"] == "r:alarm-list:toolbar"
    assert capability["verification_level"] == "discovered"
    assert "relations" not in capability

    navigation = observation()
    navigation["effect_kind"] = "navigation"
    assert induce_capability_graph(graph_for([attempt(1, "Open", entry=True, effect=navigation)]))["capabilities"] == []

    missing_region = observation(region_ref="")
    assert induce_capability_graph(graph_for([attempt(1, "Save", entry=True, effect=missing_region)]))["capabilities"] == []


    region_probe = attempt(
        1, "Start", effect=observation(), probe="probe:region:1")
    region_probe["evidence"].update({
        "region_probe_task": True,
        "region_probe_start": True,
        "source_region_ref": "r:stopwatch:controls",
        "entry_id": "",
    })
    region_capability = induce_capability_graph(
        graph_for([region_probe]))["capabilities"][0]
    assert region_capability["entry_surfaces"][0]["entry_id"] == ""
    assert region_capability["entry_surfaces"][0]["region_ref"] == (
        "r:stopwatch:controls")

    other_region_probes = []
    for index in (2, 3):
        item = attempt(
            index, "Start", effect=observation(),
            probe=f"probe:other:{index}",
        )
        item["evidence"].update({
            "region_probe_task": True,
            "region_probe_start": True,
            "source_region_ref": "r:other:controls",
            "entry_id": "",
        })
        other_region_probes.append(item)
    scoped_graph = graph_for([region_probe, *other_region_probes])
    scoped_once = induce_capability_graph(
        scoped_graph,
        region_probe_source_ref="r:stopwatch:controls",
    )["capabilities"][0]
    scoped_twice = induce_capability_graph(
        scoped_graph,
        region_probe_source_ref="r:other:controls",
    )["capabilities"][0]
    assert scoped_once["verification_level"] == "discovered"
    assert scoped_twice["verification_level"] == "effect_verified"

    two_runs = graph_for([
        attempt(1, "Add", entry=True, probe="p1"),
        attempt(2, "Time", probe="p1", action={
            "action_type": "TYPE", "parameters": {"text": "07:30"}}),
        attempt(3, "Save", effect=observation(
            "07:30", bindings={"time": "07:30"}), probe="p1"),
        attempt(4, "Add", entry=True, probe="p2"),
        attempt(5, "Time", probe="p2", action={
            "action_type": "TYPE", "parameters": {"text": "08:00"}}),
        attempt(6, "Save", effect=observation(
            "08:00", bindings={"time": "08:00"}), probe="p2"),
    ])
    promoted = induce_capability_graph(two_runs)["capabilities"][0]
    assert promoted["verification_level"] == "effect_verified"
    assert promoted["parameters"][0]["name"] == "time"
    assert promoted["parameters"][0]["domain"]["values"] == ["07:30", "08:00"]
    assert promoted["execution_recipe"][1]["parameters"]["text"] == "{{time}}"
    assert promoted["effects"][0]["changes"][0]["value"] == {"value_from_parameter": "time"}

    incomplete_parameter = graph_for([
        attempt(1, "Add", entry=True, probe="p1"), attempt(2, "Save", effect=observation("07:30", bindings={"time": "07:30"}), probe="p1"),
        attempt(3, "Add", entry=True, probe="p2"), attempt(4, "Save", effect=observation("08:00", bindings={"time": "07:30"}), probe="p2"),
    ])
    candidate = induce_capability_graph(incomplete_parameter)["capabilities"][0]
    assert candidate["verification_level"] == "executable"
    assert candidate["parameter_candidates"] == {"time": ["07:30"]}

    retry = graph_for([
        attempt(1, "World Clock", entry=True, probe="ae2"),
        attempt(2, "Alarms", entry=True, effect=observation(), probe="ae2"),
    ])
    retry_result = induce_capability_graph(retry)
    assert len(retry_result["probe_episodes"]) == 1
    episode = retry_result["probe_episodes"][0]
    assert set(episode) == {"probe_id", "entry_surface", "attempt_refs", "effect_refs", "outcome"}
    assert [item["role"] for item in episode["attempt_refs"]] == ["entry", "entry_retry"]

    failed_observation = {
        "schema_version": EFFECT_OBSERVATION_SCHEMA,
        "effect_kind": "no_effect",
        "observed_changes": [],
        "parameter_bindings": {},
        "verdict": "refuted",
    }
    negative_retry = induce_capability_graph(graph_for([
        attempt(1, "Broken Add", entry=True, effect=failed_observation,
                probe="retry-negative", outcome="no_effect"),
        attempt(2, "Retry Add", entry=True, effect=observation(), probe="retry-negative"),
    ]))
    assert len(negative_retry["probe_episodes"]) == 1
    episode = negative_retry["probe_episodes"][0]
    assert episode["outcome"] == "supported"
    assert [item["role"] for item in episode["attempt_refs"]] == ["entry", "entry_retry"]
    retried_capability = negative_retry["capabilities"][0]
    assert [step["selector"]["element_label"] for step in retried_capability["execution_recipe"]] == ["Retry Add"]
    assert [item["attempt_id"] for item in retried_capability["evidence_refs"]] == ["a1", "a2"]

    bridged = graph_for([attempt(1, "Add", entry=True)])
    del bridged.action_edges[0]["attempts"][0]["evidence"]["source_region_ref"]
    entries_snapshot = {
        "entries": [{"entry_id": "add-alarm", "page_name": "Alarms", "region_name": "Toolbar"}],
    }
    regions_snapshot = {"region_groups": {"groups": [{
        "region_ref": "rg1", "representative": {
            "page_name": "Alarms", "region_name": "Toolbar"}, "occurrences": [],
    }]}}
    assert attach_source_region_refs(bridged, entries_snapshot, regions_snapshot) == 1
    assert bridged.action_edges[0]["attempts"][0]["evidence"]["source_region_ref"] == "rg1"
    for bad_entries, bad_regions in (({"entries": {}}, regions_snapshot), (entries_snapshot, {"groups": {}})):
        try:
            attach_source_region_refs(graph_for([attempt(1, "Add", entry=True)]), bad_entries, bad_regions)
        except ValueError:
            pass
        else:
            raise AssertionError("formal snapshot list types must fail closed")
    try:
        attach_source_region_refs(graph_for([attempt(1, "Add", entry=True)]),
                                  entries_snapshot, regions_snapshot)
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting formal source Region ref must fail closed")
    duplicate_regions = {"groups": [
        {"region_ref": "rg1", "representative": {"page_name": "Alarms", "region_name": "Toolbar"}},
        {"region_ref": "rg2", "representative": {"page_name": "Alarms", "region_name": "Toolbar"}},
    ]}
    try:
        attach_source_region_refs(graph_for([attempt(1, "Add", entry=True)]),
                                  entries_snapshot, duplicate_regions)
    except ValueError:
        pass
    else:
        raise AssertionError("ambiguous Region occurrence must fail closed")
    entry_conflict_regions = {"groups": [
        {"region_ref": "rg1", "representative": {"page_name": "Alarms", "region_name": "Toolbar"}},
        {"region_ref": "rg2", "representative": {"page_name": "Alarms", "region_name": "Content"}},
    ]}
    try:
        attach_source_region_refs(bridged, {
            "entries": [
                {"entry_id": "duplicate", "page_name": "Alarms", "region_name": "Toolbar"},
                {"entry_id": "duplicate", "page_name": "Alarms", "region_name": "Content"},
            ],
        }, entry_conflict_regions)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate entry_id with different Region refs must fail closed")

    projection_entries = {
        "entries": [{
            "entry_id": "ae1",
            "page_name": "Alarms",
            "region_name": "Toolbar",
            "target": "Add",
            "control_type": "button",
            "status": "discovered",
            "source_state_id": "alarm-list",
            "temporary_bbox_1000": [10, 20, 40, 60],
            "bbox_frame_id": "observation-only",
            "representative_entry_id": "",
            "task_eligible": True,
        }],
        "pending_actions": [],
    }
    projection_regions = {"region_groups": {"groups": [
        {
            "region_ref": "rg1",
            "representative": {
                "page_name": "Alarms", "region_name": "Toolbar"},
            "occurrences": [],
        },
        {
            "region_ref": "rg2",
            "representative": {
                "page_name": "Alarms", "region_name": "Alarm List"},
            "occurrences": [],
        },
    ]}}
    projected = StateGraph("clock")
    projected.add_state(
        "alarm-list", [], "alarm-list.png", "clock",
        page_name="Alarms", page_id="alarms", variant_id="empty",
        observed_facts={"summary": "Alarms"},
        perception_mode="autonomous_vlm",
    )
    assert project_autonomous_inventory(
        projected, projection_entries, projection_regions) == 1
    projected_node = projected.graph.nodes["alarm-list"]
    projected_element = projected_node["elements"][0]
    assert projected_element["uid"] == "autonomous-entry:ae1"
    assert projected_element["region_id"] == "rg1"
    assert projected_element["geometry_status"] == "semantic_only"
    assert projected_element["bbox_xywh"] == [0, 0, 1, 1]
    assert "temporary_bbox_1000" not in projected_element
    assert "bbox_frame_id" not in projected_element
    assert projected_element.get("region_bbox") is None
    assert {
        block["region_id"] for block in projected_node["semantic_blocks"]
    } == {"rg1", "rg2"}

    test_multi_variant_projection_rejects_legacy_page_only_region()
    differing_after = graph_for([
        attempt(1, "Add", entry=True, probe="u1"), attempt(2, "Save", effect=observation("07:30"), probe="u1"),
        attempt(3, "Add", entry=True, probe="u2"), attempt(4, "Save", effect=observation("08:00"), probe="u2"),
    ])
    assert induce_capability_graph(differing_after)["capabilities"][0]["verification_level"] == "executable"

    with tempfile.TemporaryDirectory() as temporary:
        path = str(Path(temporary) / "capability_graph.json")
        save_capability_graph(path, result)
        assert load_capability_graph(path) == result

        source = Path(temporary) / "source.json"
        entries_path = Path(temporary) / "autonomous_entries.json"
        regions_path = Path(temporary) / "autonomous_regions.json"
        annotated_a = Path(temporary) / "annotated_a.json"
        annotated_b = Path(temporary) / "annotated_b.json"
        output_a = Path(temporary) / "output_a.json"
        output_b = Path(temporary) / "output_b.json"
        cli_graph = StateGraph("clock")
        cli_graph.add_state(
            "alarm-list", [], "list.png", "clock",
            page_name="Alarms", page_id="alarms", variant_id="empty",
            observed_facts={"summary": "Alarms"},
            perception_mode="autonomous_vlm")
        cli_graph.record_action_event(
            source="alarm-list", action={"action_type": "CLICK", "selector": {"element_label": "Add"}},
            committed=True, evidence={"probe_id": "cli", "explicit_entry_task": True,
                                      "entry_id": "ae1", "source_region_ref": "rg1"})
        cli_graph.record_action_event(
            source="alarm-list", action={"action_type": "CLICK", "selector": {"element_label": "Save"}},
            committed=True, evidence={
                "probe_id": "cli",
                "effect_observations": [observation()]})
        cli_graph.save(str(source))
        source_bytes = source.read_bytes()
        entries_path.write_text(
            json.dumps(projection_entries), encoding="utf-8")
        regions_path.write_text(
            json.dumps(projection_regions), encoding="utf-8")
        args = [
            "--graph_path", str(source), "--entries_path", str(entries_path),
            "--regions_path", str(regions_path),
            "--annotated_graph_output", str(annotated_a), "--output", str(output_a)]
        assert run_capability_induction(args) == 0
        assert source.read_bytes() == source_bytes
        collection_graph = StateGraph.load(str(annotated_a))
        assert collection_graph.graph.nodes["alarm-list"]["elements"][0][
            "uid"] == "autonomous-entry:ae1"

        args[args.index(str(annotated_a))] = str(annotated_b)
        args[args.index(str(output_a))] = str(output_b)
        assert run_capability_induction(args) == 0
        saved = json.loads(output_a.read_text(encoding="utf-8"))
        assert saved["source_graph_digest"] == hashlib.sha256(annotated_a.read_bytes()).hexdigest()
        assert output_a.read_bytes() == output_b.read_bytes()
        assert run_capability_induction([
            "--graph_path", str(source), "--entries_path", str(entries_path),
            "--regions_path", str(regions_path),
            "--annotated_graph_output", str(annotated_a), "--output", str(annotated_a),
        ]) == 2
    print("PASS capability induction: Qwen attempt evidence and immutable source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
