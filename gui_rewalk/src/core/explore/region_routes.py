"""Derived Page/Region visibility and routing views."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .ledger import ExplorationLedger
    from .models import Transition


def refresh_transition_region_effects(
    ledger: "ExplorationLedger",
    transition: "Transition",
) -> bool:
    """Record canonical Region visibility changes for one settled edge."""
    source = ledger.states.get(transition.source_state_id)
    target = ledger.states.get(transition.target_state_id)
    if (source is None or target is None
            or not source.survey_complete or not target.survey_complete):
        return False
    source_regions = list(dict.fromkeys(
        item.region_id
        for item in ledger.state_occurrences(source.state_id)
    ))
    target_regions = list(dict.fromkeys(
        item.region_id
        for item in ledger.state_occurrences(target.state_id)
    ))
    source_set = set(source_regions)
    target_set = set(target_regions)
    # Visibility differences are observations, not proof of action causality.
    transition.revealed_region_ids = list(dict.fromkeys(
        item for item in transition.revealed_region_ids
        if item in target_set and item not in source_set))
    transition.hidden_region_ids = [
        item for item in transition.hidden_region_ids
        if item in source_set and item not in target_set
    ]
    return True


def record_region_effects(ledger, attempt_id, changes, reported_region_ids, *, region_hints=None):
    """Resolve a compact causal report after inventory assigned its refs."""
    attempt = ledger.attempts[attempt_id]
    source = {x.region_id for x in ledger.state_occurrences(attempt.source_state_id)}
    target = {x.region_id for x in ledger.state_occurrences(attempt.target_state_id)}
    region_hints = region_hints or {}
    resolved = []
    for item_index, item in enumerate(changes):
        path = f"previous_action.region_effects[{item_index}]"
        index = item.get("report_index")
        ref = item.get("region_ref", "")
        if index is not None:
            if (isinstance(index, bool) or not isinstance(index, int)
                    or not 0 <= index < len(reported_region_ids)):
                raise ValueError(f"{path}.report_index={index!r}: use a valid page_report index OR a Region ref；"
                                 f"本轮清单有 {len(reported_region_ids)} 个区块，索引从 0 开始；不要引用动作前清单的位置。")
            if ref and region_hints.get(ref, ref) != reported_region_ids[index]:
                raise ValueError(f"{path}: Region ref and page_report index disagree；"
                                 f"region_ref={ref!r}，report_index={index} 实际对应 {reported_region_ids[index]}；"
                                 "核对最终清单后只保留一种正确引用，不要改变真实效果。")
            ref = reported_region_ids[index]
        change, cause = item.get("change"), item.get("cause")
        if index is None and change != "disappeared":
            ref = region_hints.get(ref, ref)
        if change not in {"appeared", "disappeared", "updated"} or cause not in {
                "action", "external", "uncertain"}:
            raise ValueError(f"{path}: invalid change or cause；收到 change={change!r}, cause={cause!r}；"
                             "change 用 appeared/disappeared/updated，cause 用 action/external/uncertain；无法归因用 uncertain。")
        if (ref not in (source if change == "disappeared" else target)
                or (change == "disappeared" and ref in target)):
            raise ValueError(f"{path}: {ref} does not match the before/after Region visibility；"
                             f"报告 change={change!r}，动作前存在={ref in source}，动作后存在={ref in target}。"
                             "核对动作前引用与本轮清单引用；不要仅为通过检查把变化归因于动作。")
        resolved.append({"region_ref": ref, "change": change, "cause": cause})
    ledger.event("region_effects_reported", attempt_ref=attempt_id, changes=resolved)
    for edge in ledger.transitions:
        if edge.attempt_id != attempt_id:
            continue
        edge.revealed_region_ids = [x["region_ref"] for x in resolved
                                    if x["cause"] == "action" and x["change"] == "appeared"]
        edge.hidden_region_ids = [x["region_ref"] for x in resolved
                                  if x["cause"] == "action" and x["change"] == "disappeared"]
        refresh_transition_region_effects(ledger, edge)


def page_region_refs(
    ledger: "ExplorationLedger",
    page_id: str,
) -> List[str]:
    """Return the stable union of Regions accepted under one Page."""
    result: List[str] = []
    for state in ledger.page_states(page_id):
        for occurrence in ledger.state_occurrences(state.state_id):
            if occurrence.region_id not in result:
                result.append(occurrence.region_id)
    return result


def _state_region_refs(
    ledger: "ExplorationLedger",
    state_id: str,
) -> List[str]:
    return list(dict.fromkeys(
        item.region_id for item in ledger.state_occurrences(state_id)
    ))


def region_relations(
    ledger: "ExplorationLedger",
) -> List[Dict[str, Any]]:
    """Compile evidence-backed Region visibility relations."""
    relations: List[Dict[str, Any]] = []
    aliases = {}
    updates = {}
    for event in ledger.events:
        data = event["payload"]
        if event["kind"] == "regions_reused":
            aliases.update({ref: data["known_region_id"] for ref in data["current_region_ids"]
                            if ref != data["known_region_id"]})
        elif event["kind"] == "region_effects_reported":
            updates[data["attempt_ref"]] = [item["region_ref"] for item in data["changes"]
                                            if item["cause"] == "action" and item["change"] == "updated"]
    for transition in ledger.transitions:
        attempt = ledger.attempts.get(transition.attempt_id)
        if attempt is None or attempt.outcome != "success":
            continue
        operation_ref = str(
            transition.action.get("operation_ref") or "")
        operation = ledger.operations.get(operation_ref)
        if operation is None or not operation.canonical_operation_id:
            continue
        shared_visible = set(_state_region_refs(ledger, transition.source_state_id)) & set(
            _state_region_refs(ledger, transition.target_state_id))
        updated = []
        for ref in updates.get(transition.attempt_id, []):
            while ref in aliases:
                ref = aliases[ref]
            if ref in shared_visible and ref not in updated:
                updated.append(ref)
        if (not transition.revealed_region_ids
                and not transition.hidden_region_ids and not updated):
            continue
        target_variants: Dict[str, List[str]] = {}
        for occurrence in ledger.state_occurrences(
                transition.target_state_id):
            if occurrence.region_id not in transition.revealed_region_ids + updated:
                continue
            target_variants.setdefault(
                occurrence.region_id, []).append(occurrence.variant_id)
        relations.append({
            "source_region_ref": operation.region_id,
            "source_variant_ref": operation.variant_id,
            "local_operation_ref": operation.operation_id,
            "canonical_operation_ref": operation.canonical_operation_id,
            "owner_ref": (
                operation.element_id
                if operation.scope == "element" else operation.region_id
            ),
            "action": operation.action,
            "direction": operation.direction,
            "target": operation.target,
            "source_state_ref": transition.source_state_id,
            "target_state_ref": transition.target_state_id,
            "revealed_region_refs": list(
                transition.revealed_region_ids),
            "hidden_region_refs": list(transition.hidden_region_ids),
            "updated_region_refs": updated,
            "target_region_variant_refs": target_variants,
            "evidence_transition_ref": transition.transition_id,
            "evidence_attempt_ref": transition.attempt_id,
        })
    return relations


def _effect_signature(relation: Dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(relation["revealed_region_refs"]),
        tuple(relation["hidden_region_refs"]),
        tuple(relation.get("updated_region_refs", [])),
    )


def _state_operations(
    ledger: "ExplorationLedger",
    state_id: str,
) -> List[Any]:
    result = []
    seen: set[str] = set()
    for occurrence in ledger.state_occurrences(state_id):
        for operation in ledger.occurrence_operations(
                occurrence.occurrence_id):
            if (operation.operation_id in seen
                    or not operation.canonical_operation_id):
                continue
            seen.add(operation.operation_id)
            result.append(operation)
    return result


def plan_region_route(
    ledger: "ExplorationLedger",
    *,
    current_state_id: str,
    target_region_id: str,
    target_operation_id: str = "",
) -> Dict[str, Any]:
    """Find a shortest verified Region route from the current visible State."""
    from .partition_review import qualification_gaps
    isolated = qualification_gaps(ledger)
    result: Dict[str, Any] = {
        "status": "unreachable",
        "target_region_ref": target_region_id,
        "target_canonical_operation_ref": "",
        "steps": [],
    }
    if not current_state_id or current_state_id not in ledger.states:
        return result
    target_operation = ledger.operations.get(target_operation_id)
    if target_operation_id and (target_operation is None
                                or target_operation.region_id
                                != target_region_id):
        return result
    target_canonical = (
        target_operation.canonical_operation_id
        if target_operation is not None else ""
    )
    result["target_canonical_operation_ref"] = target_canonical

    def goal_reached(state_id: str) -> bool:
        if target_region_id not in _state_region_refs(ledger, state_id):
            return False
        if not target_canonical:
            return True
        return any(
            item.region_id == target_region_id
            and item.operation_id not in isolated
            and item.canonical_operation_id == target_canonical
            and item.status not in {"deferred", "failed", "cancelled"}
            for item in _state_operations(ledger, state_id)
        )

    if goal_reached(current_state_id):
        result["status"] = "arrived"
        return result
    relations = region_relations(ledger)
    result_reuse = {
        (event["payload"]["current_operation_id"], event["payload"]["known_operation_id"])
        for event in ledger.events
        if event["kind"] == "variant_operation_result_reused"
    }
    by_canonical: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for relation in relations:
        by_canonical.setdefault((
            relation["source_region_ref"],
            relation["canonical_operation_ref"],
        ), []).append(relation)

    queue = deque([(current_state_id, [])])
    visited = {current_state_id}
    ambiguous = False
    while queue:
        state_id, path = queue.popleft()
        for operation in _state_operations(ledger, state_id):
            if operation.operation_id in isolated or operation.status in {"deferred", "failed", "cancelled"}:
                continue
            candidates = by_canonical.get((
                operation.region_id,
                operation.canonical_operation_id,
            ), [])
            if not candidates:
                continue
            exact = [
                item for item in candidates
                if item["source_variant_ref"] == operation.variant_id
            ]
            applicable = exact or candidates
            signatures = {
                _effect_signature(item) for item in applicable
            }
            if len(signatures) != 1:
                ambiguous = True
                continue
            if not exact:
                applicable = [
                    item for item in applicable
                    if (operation.operation_id, item["local_operation_ref"]) in result_reuse
                ]
                if not applicable:
                    continue
            relation = applicable[0]
            step = {
                "source_region_ref": operation.region_id,
                "source_variant_ref": operation.variant_id,
                "operation_ref": operation.operation_id,
                "canonical_operation_ref": (
                    operation.canonical_operation_id),
                "owner_ref": (
                    operation.element_id
                    if operation.scope == "element" else operation.region_id
                ),
                "action": operation.action,
                "direction": operation.direction,
                "target": operation.target,
                "expected_revealed_region_refs": list(
                    relation["revealed_region_refs"]),
                "expected_hidden_region_refs": list(
                    relation["hidden_region_refs"]),
                "expected_updated_region_refs": list(
                    relation.get("updated_region_refs", [])),
                "expected_target_state_ref": (
                    relation["target_state_ref"]),
                "evidence_transition_ref": (
                    relation["evidence_transition_ref"]),
                "evidence_attempt_ref": (
                    relation["evidence_attempt_ref"]),
                "evidence_source_variant_ref": (
                    relation["source_variant_ref"]),
            }
            next_path = [*path, step]
            target_state_id = relation["target_state_ref"]
            if goal_reached(target_state_id):
                result["status"] = "ready"
                result["steps"] = next_path
                return result
            if (target_state_id not in visited
                    and target_state_id in ledger.states):
                visited.add(target_state_id)
                queue.append((target_state_id, next_path))
    if ambiguous:
        result["status"] = "ambiguous"
    return result


__all__ = [
    "page_region_refs", "plan_region_route", "refresh_transition_region_effects",
    "region_relations", "record_region_effects",
]
