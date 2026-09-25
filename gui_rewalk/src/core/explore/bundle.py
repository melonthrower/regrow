"""Deterministic projection from the modular ledger to the formal bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
import json

from .ledger import ExplorationLedger
from .region_routes import (
    page_region_refs,
    refresh_transition_region_effects,
    region_relations,
)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _projected_region_names(ledger: ExplorationLedger) -> Dict[str, str]:
    identities: Dict[Tuple[str, str], set[str]] = {}
    for occurrence in ledger.occurrences.values():
        state = ledger.states[occurrence.state_id]
        page = ledger.pages[state.page_id]
        key = page.name.casefold(), occurrence.name.casefold()
        identities.setdefault(key, set()).add(occurrence.region_id)
    names: Dict[str, str] = {}
    stable_names: Dict[Tuple[str, str], str] = {}
    for occurrence in ledger.occurrences.values():
        state = ledger.states[occurrence.state_id]
        page = ledger.pages[state.page_id]
        key = page.name.casefold(), occurrence.name.casefold()
        projected_name = (
            f"{occurrence.name} [{occurrence.region_id}]"
            if len(identities[key]) > 1 else occurrence.name)
        owner_key = occurrence.region_id, page.page_id
        names[occurrence.occurrence_id] = stable_names.setdefault(
            owner_key, projected_name)
    return names


def _region_snapshot(
    ledger: ExplorationLedger,
    projected_names: Dict[str, str],
) -> Dict[str, Any]:
    groups = []
    for region in ledger.regions.values():
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for occurrence_id in region.occurrence_ids:
            occurrence = ledger.occurrences[occurrence_id]
            state = ledger.states[occurrence.state_id]
            page = ledger.pages[state.page_id]
            projected_name = projected_names[occurrence_id]
            key = page.name.casefold(), projected_name.casefold()
            record = grouped.setdefault(key, {
                "page_name": page.name,
                "region_name": projected_name,
                "state_ids": [],
            })
            if state.state_id not in record["state_ids"]:
                record["state_ids"].append(state.state_id)
        occurrences = list(grouped.values())
        if not occurrences:
            continue
        groups.append({
            "region_ref": region.region_id,
            "memory": region.memory or region.summary,
            "variant_refs": list(region.variant_ids),
            "element_refs": list(region.element_ids),
            "region_operation_refs": [
                item for item in region.operation_ids
                if ledger.operations[item].scope == "region"
            ],
            "capability_operation_refs": list(region.operation_ids),
            "canonical_operation_refs": list(
                region.canonical_operation_ids),
            "representative": occurrences[0],
            "occurrences": occurrences[1:],
        })
    return {
        "schema": "gui_rewalk.autonomous_regions_by_page.v8",
        "region_groups": {
            "schema": "gui_rewalk.autonomous_region_groups.v6",
            "groups": groups,
        },
    }


def _region_route_snapshot(ledger: ExplorationLedger) -> Dict[str, Any]:
    projected = ledger.clone()
    for transition in projected.transitions:
        refresh_transition_region_effects(projected, transition)
    return {
        "schema": "modular_region_routes.v1",
        "page_region_groups": [{
            "page_ref": page.page_id,
            "page_name": page.name,
            "region_refs": page_region_refs(projected, page.page_id),
        } for page in projected.pages.values()],
        "relations": region_relations(projected),
    }


def _entry_snapshot(
    ledger: ExplorationLedger,
    projected_names: Dict[str, str],
) -> tuple[Dict[str, Any], Dict[Tuple[str, str], str]]:
    entries: List[Dict[str, Any]] = []
    lookup: Dict[Tuple[str, str], str] = {}
    for identity in ledger.canonical_operations.values():
        bindings = [
            ledger.operations[item]
            for item in identity.operation_ids
            if item in ledger.operations
        ]
        if not bindings:
            continue
        grouped: Dict[str, Dict[str, Any]] = {}
        for operation in bindings:
            for occurrence_id in operation.source_occurrence_ids:
                occurrence = ledger.occurrences[occurrence_id]
                state = ledger.states[occurrence.state_id]
                page = ledger.pages[state.page_id]
                record = grouped.setdefault(page.page_id, {
                    "page_name": page.name,
                    "region_name": projected_names[occurrence_id],
                    "subjects": [],
                    "state_ids": [],
                    "operation_ids": [],
                    "operation_state_ids": {},
                })
                record["state_ids"].append(state.state_id)
                element = ledger.elements.get(operation.element_id)
                subject = (
                    element.name if operation.scope == "element" and element
                    else projected_names[occurrence_id]
                )
                if subject not in record["subjects"]:
                    record["subjects"].append(subject)
                if operation.operation_id not in record["operation_ids"]:
                    record["operation_ids"].append(operation.operation_id)
                record["operation_state_ids"].setdefault(
                    operation.operation_id, []).append(state.state_id)
        multiple = len(grouped) > 1
        for page_id, record in grouped.items():
            entry_id = (
                f"{identity.canonical_operation_id}_{page_id}"
                if multiple else identity.canonical_operation_id)
            unique_states = list(dict.fromkeys(record["state_ids"]))
            page_bindings = [
                ledger.operations[item] for item in record["operation_ids"]]
            open_status = next((
                status for status in ("active", "pending", "deferred")
                if any(item.status == status for item in page_bindings)
            ), "")
            status = open_status or next((
                status for status in (
                    "verified", "recorded", "failed", "cancelled")
                if any(item.status == status for item in page_bindings)
            ), page_bindings[0].status)
            parameter_status = (
                "observed" if any(
                    item.parameter_status == "observed"
                    for item in page_bindings) else
                "none" if any(
                    item.parameter_status == "none"
                    for item in page_bindings) else "unknown"
            )
            parameter_conflict = (
                {item.parameter_status for item in page_bindings}
                >= {"none", "observed"}
            )
            parameter_summaries = list(dict.fromkeys(
                item.parameter_summary for item in page_bindings
                if item.parameter_summary
            ))
            parameter_evidence_refs = list(dict.fromkeys(
                evidence_ref
                for item in page_bindings
                for evidence_ref in item.parameter_evidence_refs
            ))
            entries.append({
                "entry_id": entry_id,
                "canonical_operation_ref": identity.canonical_operation_id,
                "variant_operation_refs": list(record["operation_ids"]),
                "page_name": record["page_name"],
                "region_name": record["region_name"],
                "operation": identity.action,
                "operation_scope": identity.scope,
                "direction": identity.direction,
                "subject": record["subjects"][0],
                "target": identity.target,
                "control_type": "control",
                "status": status,
                "exploration_policy": (
                    "record" if status == "recorded" else "explore"),
                "source_state_id": unique_states[0],
                "source_state_ids": unique_states,
                "task_eligible": False,
                "parameter_status": parameter_status,
                "parameter_conflict": parameter_conflict,
                "parameter_summaries": parameter_summaries,
                "parameter_evidence_refs": parameter_evidence_refs,
            })
            for operation_id, state_ids in record[
                    "operation_state_ids"].items():
                for state_id in state_ids:
                    lookup[operation_id, state_id] = entry_id
    return {
        "schema": "gui_rewalk.autonomous_entries.v3",
        "next_action": 1,
        "entries": entries,
        "pending_actions": [],
    }, lookup


def _portable_action(raw: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(raw.get("kind") or "").casefold()
    action_type = {
        "click": "CLICK", "double_click": "DOUBLE_CLICK",
        "right_click": "RIGHT_CLICK", "long_press": "LONG_PRESS",
        "input_text": "TYPING", "hover": "HOVER", "scroll": "SCROLL",
        "back": "PRESS", "wait": "WAIT",
    }.get(kind, kind.upper() or "UNKNOWN")
    action: Dict[str, Any] = {
        "action_type": action_type,
        "selector": {"element_label": str(raw.get("target") or "")},
    }
    if kind == "input_text":
        action["text"] = str(raw.get("text") or "")
    if kind == "scroll":
        action["parameters"] = {"direction": str(raw.get("direction") or "")}
    if kind == "back":
        action["parameters"] = {"key": "back"}
    return action


def _effect_observation(
    ledger: ExplorationLedger,
    *,
    source_state_id: str,
    target_state_id: str,
    region_ref: str,
    capability_name: str,
    reason: str,
) -> Dict[str, Any]:
    source = ledger.states[source_state_id]
    target = ledger.states[target_state_id]
    same_page = source.page_id == target.page_id
    if same_page and region_ref:
        return {
            "schema_version": "gui_rewalk.effect_observation.v1",
            "capability_name": capability_name,
            "reason": reason,
            "effect_kind": "state_change",
            "observed_changes": [{
                "scope": {
                    "region_ref": region_ref,
                    "page_id": source.page_id,
                    "state_id": target_state_id,
                },
                "fact": "visible_state",
                "before": source_state_id,
                "after": target_state_id,
            }],
            "parameter_bindings": {},
            "predicate_candidate": f"visible_state == {target_state_id}",
            "verdict": "supported",
        }
    return {
        "schema_version": "gui_rewalk.effect_observation.v1",
        "capability_name": capability_name,
        "reason": reason,
        "effect_kind": "navigation",
        "observed_changes": [],
        "parameter_bindings": {},
        "predicate_candidate": "",
        "verdict": "supported",
    }


def _build_graph(
    ledger: ExplorationLedger,
    *,
    output_root: Path,
    app_name: str,
    entry_lookup: Dict[Tuple[str, str], str],
    stop_reason: str,
) -> Any:
    from gui_rewalk.src.core.graph.state_graph import StateGraph

    graph = StateGraph(app_name)
    graph.stop_reason = (
        "frontier_empty" if stop_reason == "complete"
        else str(stop_reason or "incomplete"))
    for state in ledger.states.values():
        page = ledger.pages[state.page_id]
        graph.add_state(
            state.state_id,
            [],
            str((output_root / state.screenshot_ref).resolve()),
            app_name,
            page_name=page.name,
            page_id=page.page_id,
            variant_id=state.state_id,
            page_identity_version="semantic_page_variant_v1",
            variant_signature={"name": state.name},
            observed_facts={"summary": state.summary},
            perception_mode="autonomous_vlm",
            geometry_mode="fresh_grounding",
        )
    transitions = {item.attempt_id: item for item in ledger.transitions}
    for attempt in ledger.attempts.values():
        transition = transitions.get(attempt.attempt_id)
        operation_ref = str(attempt.action.get("operation_ref") or "")
        operation = ledger.operations.get(operation_ref)
        region_ref = operation.region_id if operation else ""
        entry_id = entry_lookup.get(
            (operation_ref, attempt.source_state_id), "")
        target_state_id = (
            transition.target_state_id if transition else attempt.target_state_id)
        capability_name = " ".join(filter(None, [
            operation.action if operation else "",
            operation.target if operation else str(attempt.action.get("target") or ""),
        ]))
        evidence: Dict[str, Any] = {
            "before_ref": attempt.before_ref,
            "after_ref": attempt.after_ref,
        }
        if transition is not None and transition.revealed_region_ids:
            evidence["revealed_region_refs"] = list(
                transition.revealed_region_ids)
        if transition is not None and transition.hidden_region_ids:
            evidence["hidden_region_refs"] = list(
                transition.hidden_region_ids)
        if attempt.purpose == "execute" and entry_id and region_ref:
            operation_task = ledger.operation_task(operation_ref)
            evidence.update({
                "probe_id": (
                    operation_task.task_id
                    if operation_task is not None else attempt.task_id),
                "explicit_entry_task": True,
                "entry_id": entry_id,
                "source_region_ref": region_ref,
            })
        if (transition is not None and attempt.outcome == "success"):
            evidence["effect_observations"] = [_effect_observation(
                ledger,
                source_state_id=transition.source_state_id,
                target_state_id=transition.target_state_id,
                region_ref=region_ref,
                capability_name=capability_name,
                reason=attempt.visible_result,
            )]
        event_index = graph.record_action_event(
            source=attempt.source_state_id,
            target=target_state_id,
            action=_portable_action(attempt.action),
            element_label=str(attempt.action.get("target") or ""),
            semantic_description=capability_name,
            region=region_ref,
            outcome=attempt.outcome,
            detail=attempt.visible_result,
            landing_verified=(
                attempt.outcome == "success" and bool(target_state_id)),
            target_page_name=(
                ledger.pages[ledger.states[target_state_id].page_id].name
                if target_state_id in ledger.states else ""),
            committed=attempt.outcome != "pending",
            evidence=evidence,
        )
        if transition is not None:
            graph.add_transition(
                transition.source_state_id,
                transition.target_state_id,
                _portable_action(attempt.action),
                element_label=str(attempt.action.get("target") or ""),
                semantic_description=capability_name,
                region=region_ref,
                effect_verdict=attempt.outcome,
                effect_note=attempt.visible_result,
                landing_verified=attempt.outcome == "success",
                target_page_name=ledger.pages[
                    ledger.states[transition.target_state_id].page_id].name,
                event_index=event_index,
                transition_kind=attempt.purpose,
            )
    return graph


def _region_hierarchy_snapshot(ledger: ExplorationLedger) -> Dict[str, Any]:
    return {"schema": "modular_region_hierarchy.v1",
        "scope": "Registered observations; membership does not prove current visibility.",
        "states": [{"state_ref": state.state_id, "regions": [{
            "region_ref": item.region_id, "occurrence_ref": item.occurrence_id,
            "name": item.name,
            "parent_region_ref": (ledger.occurrences[item.parent_occurrence_id].region_id
                                  if item.parent_occurrence_id else ""),
            "parent_occurrence_ref": item.parent_occurrence_id,
        } for item in ledger.state_occurrences(state.state_id)]}
            for state in ledger.states.values()]}


def _function_inventory_snapshot(ledger: ExplorationLedger) -> List[Dict[str, Any]]:
    from ..scenario.region_function_research import region_function_inventory
    rows = region_function_inventory(ledger)
    for row in rows:
        region = ledger.regions[row["region_ref"]]
        row["containment"] = [{"state_ref": occurrence.state_id,
            "parent_region_ref": (ledger.occurrences[occurrence.parent_occurrence_id].region_id
                                  if occurrence.parent_occurrence_id else "")}
            for occurrence in (ledger.occurrences[ref] for ref in region.occurrence_ids)]
        row["control_observations"] = [{"element_ref": element.element_id, "name": element.name,
            "last_observation": dict(element.observations[-1])}
            for element in (ledger.elements[ref] for ref in region.element_ids)
            if element.observations]
        row["observation_scope"] = "参数描述及控件值来自记录的截图，不代表执行时实时状态；当前状态需现场核对。"
        for item in row["operations"]:
            canonical = ledger.canonical_operations[item["operation_ref"]]
            bindings = [ledger.operations[ref] for ref in canonical.operation_ids]
            item["parameter_observations"] = [{"operation_binding": operation.operation_id,
                "description": operation.parameter_summary, "status": operation.parameter_status,
                "screenshot_refs": list(operation.parameter_evidence_refs)}
                for operation in bindings if operation.parameter_summary]
            item["parameter_information"] = ["历史参数观察（非实时状态）：" + text
                                             for text in item["parameter_information"]]
            item["result_observations"] = [{"attempt_ref": attempt.attempt_id,
                "outcome": attempt.outcome, "description": attempt.visible_result,
                "before_ref": attempt.before_ref, "after_ref": attempt.after_ref}
                for attempt in ledger.attempts.values()
                if attempt.action.get("operation_ref") in canonical.operation_ids]
    return rows


def compile_modular_bundle(
    ledger: ExplorationLedger,
    *,
    output_root: str,
    app_name: str,
    stop_reason: str,
) -> Dict[str, Any]:
    from gui_rewalk.src.core.scenario.capability_induction import (
        compile_collection_bundle,
    )

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    graph_path = root / "modular_graph.json"
    entries_path = root / "modular_entries.json"
    regions_path = root / "modular_regions.json"
    region_routes_path = root / "modular_region_routes.json"
    hierarchy_path = root / "modular_region_hierarchy.json"
    annotated_path = root / "annotated_graph.json"
    capability_path = root / "capability_graph.json"
    projected_names = _projected_region_names(ledger)
    entries, lookup = _entry_snapshot(ledger, projected_names)
    _write_json(entries_path, entries)
    _write_json(regions_path, _region_snapshot(ledger, projected_names))
    _write_json(region_routes_path, _region_route_snapshot(ledger))
    _write_json(hierarchy_path, _region_hierarchy_snapshot(ledger))
    _write_json(root / "function_inventory.json", _function_inventory_snapshot(ledger))
    graph = _build_graph(
        ledger,
        output_root=root,
        app_name=app_name,
        entry_lookup=lookup,
        stop_reason=stop_reason,
    )
    graph.save(str(graph_path))
    result = compile_collection_bundle(
        str(graph_path),
        str(capability_path),
        annotated_graph_path=str(annotated_path),
        entries_path=str(entries_path),
        regions_path=str(regions_path),
    )
    result["ledger_path"] = str(root / "exploration_ledger.json")
    result["region_routes_path"] = str(region_routes_path)
    result["region_hierarchy_path"] = str(hierarchy_path)
    return result


__all__ = ["_region_route_snapshot", "compile_modular_bundle"]
