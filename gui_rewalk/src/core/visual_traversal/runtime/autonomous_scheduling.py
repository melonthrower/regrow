"""Autonomous exploration task scheduling and repeat-action policy.

This module owns survey, Entry and Region-operation task selection, the dynamic
tool set, exact same-frame repeat guards and old-stage action deferral after
accepted evidence advances the phase. It does not call Qwen, review a target,
execute GUI actions, or commit graph transitions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import networkx as nx

from .autonomous_action_tools import action_tool_catalog
from .autonomous_agent import INTERRUPTION_ROUND_LIMIT
from .autonomous_context import (
    _probe_attempt_count,
    _region_probe_capability_evidence,
    _region_probe_ref,
    _region_state,
)
from .autonomous_entry_review import _current_entry_review_record
from .autonomous_protocol import (
    TOOL_NAMES,
    available_tool_catalog,
)
from .autonomous_region_tools import _region_for_point, screenshot_frame_id
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _current_page_state_id,
)
from .autonomous_turn import (
    AutonomousDecision,
    ExplorationTask,
    PendingAction,
    PreviousAssessment,
    _exploration_task_key,
    _page_key,
)


SURVEY_TASK_TOOL_NAMES = set(TOOL_NAMES) - {
    "reuse_entry_result", "defer_current_task", "input_text",
    "report_app_scope",
}
EXPLORE_TASK_TOOL_NAMES = {
    "page_identity", "report_record_error",
    "reuse_entry_result", "defer_current_task",
    "handle_interruption", "click", "hover", "scroll", "navigate",
    "gesture",
}
PROBE_TASK_TOOL_NAMES = {
    "page_identity", "report_record_error",
    "handle_interruption", "click", "hover",
    "input_text", "scroll", "navigate", "gesture",
}


def _covered_entry_click_issue(
    host: AutonomousTraversalRuntime,
    page_name: str,
    decision: AutonomousDecision,
) -> str:
    if decision.tool_name not in {"click", "gesture"}:
        return ""
    if host.exploration_task is not None:
        try:
            task_record = host.entry_ledger.get(
                host.exploration_task.entry_id)
        except KeyError:
            task_record = None
        if (task_record is not None
                and task_record.status.value not in {"verified", "inferred"}):
            return ""
    entry_id = str(decision.tool_arguments.get("entry_id") or "").strip()
    if not entry_id:
        return ""
    try:
        record = host.entry_ledger.get(entry_id)
    except KeyError:
        return ""
    if record.status.value not in {"verified", "inferred"}:
        return ""
    task = host.exploration_task
    if (
        task is not None
        and task.phase in {"route_to_page", "route_to_source"}
        and task.route_hint
        and str(task.route_hint[0].get("entry_id") or "").strip() == entry_id
    ):
        return ""
    return (
        f"entry {entry_id} is already {record.status.value}; no exploration_task "
        "requires another functional probe"
    )


def _survey_entry_click_issue(
    host: AutonomousTraversalRuntime,
    decision: AutonomousDecision,
) -> str:
    """Keep page survey from consuming an entry task it only registered."""
    if (decision.tool_name not in {"click", "gesture"}
            or host.exploration_task is None
            or host.exploration_task.task_type != "survey_page"):
        return ""
    entry_id = str(decision.tool_arguments.get("entry_id") or "").strip()
    if not entry_id:
        return ""
    return (
        f"survey_page only registers entry {entry_id}; its functional probe "
        "must wait for a later explore_entry task"
    )


def _region_probe_action_issue(
    host: AutonomousTraversalRuntime,
    page_name: str,
    decision: AutonomousDecision,
) -> str:
    """Bind Region-probe pointer actions to the exact assigned Region."""
    task = host.exploration_task
    if (task is None or task.task_type != "explore_region"
            or task.phase != "explore_region"):
        return ""
    entry_id = str(decision.tool_arguments.get("entry_id") or "").strip()
    if entry_id:
        return (
            "explore_region performs internal operations without creating or "
            f"executing Entry {entry_id}; leave entry_id empty"
        )
    if (
        decision.tool_name in {"click", "input_text", "gesture"}
        and decision.purpose != "operation_attempt"
    ):
        return (
            "an internal Region control must use purpose=operation_attempt; "
            f"received {decision.purpose or '<empty>'}"
        )
    if _page_key(page_name) != _page_key(task.page_name):
        return (
            f"explore_region is assigned to Page {task.page_name!r}, not "
            f"{page_name!r}"
        )
    if decision.point_1000 is None:
        return ""
    region_state = _region_state(host, page_name)
    region_bbox = (region_state.snapshot().get("current_bboxes") or {}).get(
        _page_key(task.region_name)
    )
    if not isinstance(region_bbox, dict) or not region_bbox.get("bbox_1000"):
        return ""
    region_name = _region_for_point(region_state, decision.point_1000)
    if _page_key(region_name) != _page_key(task.region_name):
        return (
            f"the pointer is inside Region {region_name!r}, but the assigned "
            f"capability probe is restricted to {task.region_name!r}"
        )
    return ""


def _page_survey_needs(
    host: AutonomousTraversalRuntime,
    page_name: str,
    state_id: str = "",
) -> List[tuple[str, str, str]]:
    """Return every independently runnable survey need for one Page."""
    pending_entry_review = host.pending_entry_review
    if (
        isinstance(pending_entry_review, dict)
        and _page_key(pending_entry_review.get("page_name"))
        == _page_key(page_name)
    ):
        return [("entry_review_pending", "", "review_entries")]
    pending_corrections = host.page_update_corrections.get(
        _page_key(page_name)) or {}
    if pending_corrections:
        if any(
            item.get("error_code") == "region_equivalence_review_required"
            for item in pending_corrections.values()
        ):
            return [(
                "region_equivalence_review_pending",
                "",
                "review_region_equivalence",
            )]
        first = next(iter(pending_corrections.values()))
        region_name = str(first.get("region_name") or "").strip()
        state = host.region_states.get(_page_key(page_name))
        known_region = (
            state.region(region_name) if state is not None and region_name
            else None
        )
        return [(
            "page_update_correction_pending",
            region_name if known_region is not None else "",
            "survey_region" if known_region is not None else "record_regions",
        )]
    resurvey = host.pending_page_resurveys.get(_page_key(page_name)) or {}
    if resurvey:
        region_name = str(resurvey.get("region_name") or "").strip()
        return [(
            "same_page_functional_surface_changed",
            region_name,
            "survey_region" if region_name else "record_regions",
        )]
    empty_state_ids = host.empty_region_surveys.get(
        _page_key(page_name), set())
    if state_id and state_id in empty_state_ids:
        return []
    if (
        state_id
        and not host.region_registry.has_state_occurrence(
            page_name, state_id)
    ):
        return [("material_variant_has_no_region_occurrence", "", "record_regions")]
    state = host.region_states.get(_page_key(page_name))
    if state is None:
        return [("page_has_no_region_map", "", "record_regions")]
    snapshot = state.snapshot()
    regions = list(snapshot.get("regions") or [])
    if not regions:
        if empty_state_ids:
            return []
        return [("page_has_no_region_map", "", "record_regions")]
    needs: List[tuple[str, str, str]] = []
    page_audits = host.entry_review_audits.get(_page_key(page_name)) or {}
    for region in regions:
        if not region.get("coverage_complete"):
            region_name = str(region.get("name") or "")
            audit = page_audits.get(_page_key(region_name)) or {}
            try:
                audit_generation = int(
                    audit.get("discussion_evidence_generation", -1))
            except (TypeError, ValueError):
                audit_generation = -1
            if (
                audit.get("status") == "deferred"
                and audit_generation == host.entry_review_evidence_generation
            ):
                continue
            occurrence_state_ids = _region_probe_state_ids(
                host, page_name, region_name)
            needs.append((
                "region_has_not_been_fully_inspected",
                region_name,
                (
                    "route_to_page"
                    if (
                        state_id
                        and occurrence_state_ids
                        and state_id not in occurrence_state_ids
                    ) else "survey_region"
                ),
            ))
    return needs


def _page_survey_need(
    host: AutonomousTraversalRuntime,
    page_name: str,
    state_id: str = "",
) -> tuple[str, str, str]:
    """Return the first incomplete Page-survey need for compatibility."""
    needs = _page_survey_needs(host, page_name, state_id)
    return needs[0] if needs else ("", "", "")


def _survey_task(
    host: AutonomousTraversalRuntime,
    page_name: str,
    *,
    reason: str,
    region_name: str,
    phase: str,
) -> ExplorationTask:
    target_state_ids = (
        _region_probe_state_ids(host, page_name, region_name)
        if region_name else []
    )
    return ExplorationTask(
        task_type="survey_page",
        task_id=f"survey:{page_name or 'current_visible_page'}",
        page_name=page_name,
        region_name=region_name,
        target=region_name or page_name or "current visible page",
        goal="discover_page_entries",
        phase=phase,
        reason=reason,
        route_hint=(
            _region_probe_state_route_hint(host, target_state_ids)
            if target_state_ids else (
                _verified_page_route_hint(host, page_name)
                if page_name else []
            )
        ),
    )


def _region_probe_evidence_priority(
    host: AutonomousTraversalRuntime, region_ref: str,
) -> int:
    evidence = _region_probe_capability_evidence(host, region_ref)
    return 0 if not evidence else 1


def _region_probe_reason(
    host: AutonomousTraversalRuntime, region_ref: str,
) -> str:
    evidence = _region_probe_capability_evidence(host, region_ref)
    if evidence:
        names = ", ".join(str(item["name"]) for item in evidence[:3])
        return (
            f"{names} already demonstrates its operation type for traversal "
            "coverage. Its separate evidence-verification level does not "
            "require another GUI action. Do not repeat the same control with "
            "different homogeneous values; probe a distinct safe visible core "
            "operation, or close this Region when none remains."
        )
    return (
        "This formal Region has no supported business-effect observation yet. "
        "Probe one safe visible core operation or close it with a concrete "
        "visual reason when none exists."
    )


def _region_probe_state_ids(
    host: AutonomousTraversalRuntime,
    page_name: str,
    region_name: str,
) -> List[str]:
    region_ref = _region_probe_ref(host, page_name, region_name)
    group = next((
        item for item in host.region_registry.candidates()
        if str(item.get("region_ref") or "").strip() == region_ref
    ), None)
    occurrence = next((
        item for item in (group or {}).get("occurrences") or []
        if _page_key(item.get("page_name")) == _page_key(page_name)
        and _page_key(item.get("region_name")) == _page_key(region_name)
    ), None)
    visible_state_ids = {
        str(state_id).strip()
        for state_id in (occurrence or {}).get("visible_state_ids") or []
        if str(state_id).strip()
    }
    if not visible_state_ids:
        visible_state_ids = {
            str(source.get("state_id") or "").strip()
            for version in (group or {}).get("coverage_versions") or []
            if isinstance(version, dict)
            for source in [version.get("source") or {}]
            if isinstance(source, dict)
            and _page_key(source.get("page_name")) == _page_key(page_name)
            and _page_key(source.get("region_name")) == _page_key(region_name)
            and str(source.get("state_id") or "").strip()
        }
    if visible_state_ids:
        return sorted(visible_state_ids)
    return sorted({
        str(state_id).strip()
        for state_id in (occurrence or {}).get("state_ids") or []
        if str(state_id).strip()
    })


def _region_probe_state_route_hint(
    host: AutonomousTraversalRuntime,
    target_state_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    current_state_id = _current_page_state_id(host)
    if not current_state_id or current_state_id in target_state_ids:
        return []
    graph = host.graph.routing_graph
    paths: List[List[str]] = []
    for target_state_id in target_state_ids:
        try:
            paths.append(nx.shortest_path(
                graph, current_state_id, str(target_state_id)))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
    if not paths:
        return []
    path = min(paths, key=lambda item: (len(item), item[-1]))

    def state_name(state_id: str) -> str:
        node = graph.nodes[state_id]
        page_name = str(node.get("page_name") or "current page").strip()
        facts = node.get("observed_facts") or {}
        signature = node.get("variant_signature") or {}
        variant_name = str(
            facts.get("variant_name")
            or signature.get("variant_name")
            or ""
        ).strip()
        return (
            f"{page_name} ({variant_name})" if variant_name else page_name
        )

    route: List[Dict[str, Any]] = []
    for source_state_id, target_state_id in zip(path, path[1:]):
        edge = graph[source_state_id][target_state_id]
        element_id = str(edge.get("element_id") or "").strip()
        entry_id = (
            element_id.split(":", 1)[1]
            if element_id.startswith("autonomous-entry:") else ""
        )
        if entry_id:
            try:
                entry = host.entry_ledger.get(entry_id)
            except KeyError:
                entry_id = ""
            else:
                if entry.status.value not in {"verified", "inferred"}:
                    entry_id = ""
        action = edge.get("action") or {}
        selector = action.get("selector") or {}
        step = {
            "from": state_name(source_state_id),
            "via": str(
                edge.get("element_label")
                or selector.get("element_label")
                or edge.get("semantic_description")
                or "visible verified route control"
            ).strip(),
            "action": str(action.get("action_type") or "CLICK").strip(),
            "to": state_name(target_state_id),
            "provenance": "landing_verified",
        }
        if entry_id:
            step["entry_id"] = entry_id
        route.append(step)
    return route


def _can_discover_same_page_route(
    host: AutonomousTraversalRuntime,
    task: ExplorationTask,
) -> bool:
    """Let the Agent discover a missing local state transition from fresh pixels."""
    return bool(
        task.phase in {"route_to_page", "route_to_source"}
        and task.page_name
        and _page_key(task.page_name) == _page_key(host.protocol_map.current_page)
        and _current_page_state_id(host)
    )


def _verified_page_route_hint(
    host: AutonomousTraversalRuntime,
    page_name: str,
) -> List[Dict[str, Any]]:
    """Return a shortest route on committed, landing-verified graph edges only."""
    current_state_id = _current_page_state_id(host)
    if not current_state_id or _page_key(host.protocol_map.current_page) == _page_key(
            page_name):
        return []
    target_state_ids = [
        str(state_id)
        for state_id, node in host.graph.routing_graph.nodes(data=True)
        if _page_key(node.get("page_name")) == _page_key(page_name)
    ]
    return _region_probe_state_route_hint(host, target_state_ids)


def _entry_source_route(
    host: AutonomousTraversalRuntime,
    entry: Any,
) -> tuple[bool, List[Dict[str, Any]]]:
    """Return whether the Entry is at a known source State and a route to one."""
    current_state_id = _current_page_state_id(host)
    on_source_page = (
        _page_key(host.protocol_map.current_page)
        == _page_key(getattr(entry, "page_name", ""))
    )
    required_page_modes = dict(
        getattr(entry, "required_page_modes", {}) or {})
    if on_source_page and required_page_modes:
        mode_records = {
            _page_key(record.get("scope_name")): record
            for record in host.scope_state_ledger.page_mode_context(
                getattr(entry, "page_name", ""))
        }
        for mode_name, required_value in required_page_modes.items():
            record = mode_records.get(_page_key(mode_name)) or {}
            current_value = str(record.get("current_value") or "")
            if current_value == str(required_value):
                continue
            transition = next((
                item for item in record.get("transitions") or []
                if str(item.get("from") or "") == current_value
                and str(item.get("to") or "") == str(required_value)
                and str(item.get("trigger_entry_id") or "")
            ), None)
            if transition is None:
                return False, []
            trigger_id = str(transition.get("trigger_entry_id") or "")
            try:
                trigger = host.entry_ledger.get(trigger_id)
            except KeyError:
                return False, []
            if trigger.status.value not in {"verified", "inferred"}:
                return False, []
            return False, [{
                "from": current_value,
                "via": trigger.target,
                "action": str(
                    transition.get("trigger_operation") or "click"
                ).upper(),
                "to": str(required_value),
                "entry_id": trigger.entry_id,
                "provenance": "observed_page_mode_transition",
            }]
    required_states = list(
        getattr(entry, "required_states", ()) or ())
    occurrence_ref = str(
        getattr(entry, "representative_occurrence_ref", "") or "").strip()
    if required_states and occurrence_ref and current_state_id:
        current_region_state = host.region_registry.occurrence_state_ref(
            getattr(entry, "page_name", ""),
            getattr(entry, "region_name", ""),
            current_state_id,
        )
        if current_region_state in required_states:
            return True, []
        target_state_ids = host.region_registry.page_state_ids_for_occurrence_states(
            occurrence_ref, required_states)
        if target_state_ids:
            return False, _region_probe_state_route_hint(
                host, target_state_ids)
    source_state_ids = []
    for raw_state_id in (
        [getattr(entry, "source_state_id", "")]
        + list(getattr(entry, "source_state_ids", ()) or ())
    ):
        state_id = str(raw_state_id or "").strip()
        if state_id and state_id not in source_state_ids:
            source_state_ids.append(state_id)
    if source_state_ids and current_state_id:
        if current_state_id in source_state_ids:
            return True, []
        return False, _region_probe_state_route_hint(host, source_state_ids)
    return on_source_page, (
        [] if on_source_page
        else _verified_page_route_hint(host, getattr(entry, "page_name", ""))
    )


def _task_dependency_status(
    host: AutonomousTraversalRuntime,
    task_key: str,
) -> str:
    """Refresh one prerequisite, without claiming that it unlocked its child."""
    dependency = host.task_dependencies.get(task_key)
    if not isinstance(dependency, dict):
        return "ready"
    prerequisite_id = str(dependency.get("prerequisite_entry_id") or "")
    try:
        prerequisite = host.entry_ledger.get(prerequisite_id)
    except KeyError:
        dependency["status"] = "blocked"
        dependency["failure_kind"] = "missing_prerequisite"
        return "blocked"
    if (
        dependency.get("status") == "recheck_after_prerequisite"
        and dependency.get("rechecked_prerequisite_entry_id")
        == prerequisite.entry_id
    ):
        return "ready"
    if prerequisite.status.value == "inferred":
        # An equivalent Entry reuses a semantic result.  It never proves that
        # this occurrence changed the current State, so a dependent cannot
        # treat it as an unlock.
        dependency["status"] = "blocked"
        dependency["failure_kind"] = "inferred_not_current_state_effect"
        dependency["prerequisite_result"] = prerequisite.last_result[:500]
        return "blocked"
    if prerequisite.status.value == "verified":
        dependency["status"] = "recheck_after_prerequisite"
        dependency["recheck_count"] = int(
            dependency.get("recheck_count") or 0) + 1
        dependency["rechecked_prerequisite_entry_id"] = prerequisite.entry_id
        dependency["prerequisite_result"] = _entry_dependency_result(
            prerequisite)
        dependency["prerequisite_release_consumed"] = False
        return "ready"
    latest = _entry_dependency_result(prerequisite)
    if (
        prerequisite.status.value == "unresolved"
        and getattr(prerequisite, "attempt_count", 0) > 0
        and _entry_latest_outcome(prerequisite) == "unresolved"
    ):
        # The exact prerequisite action happened but its own expected outcome
        # was wrong.  Preserve that unresolved work, yet let the dependent
        # inspect the fresh target once because the original dependency theory
        # may have been wrong too.
        dependency["status"] = "recheck_after_prerequisite"
        dependency["recheck_count"] = int(
            dependency.get("recheck_count") or 0) + 1
        dependency["rechecked_prerequisite_entry_id"] = prerequisite.entry_id
        dependency["prerequisite_result"] = latest
        dependency["prerequisite_release_consumed"] = False
        return "ready"
    if (
        not prerequisite.task_eligible
        and _entry_latest_outcome(prerequisite) == "no_visible_change"
    ):
        # The prerequisite was really tried and did not visibly change the
        # frame.  The original hypothesis may have been wrong, so give the
        # dependent exactly one fresh observation rather than fabricate a
        # satisfied condition.
        dependency["status"] = "recheck_after_prerequisite"
        dependency["recheck_count"] = int(
            dependency.get("recheck_count") or 0) + 1
        dependency["rechecked_prerequisite_entry_id"] = prerequisite.entry_id
        dependency["prerequisite_result"] = latest
        dependency["prerequisite_release_consumed"] = False
        return "ready"
    if not prerequisite.task_eligible:
        dependency["status"] = "blocked"
        dependency["failure_kind"] = "prerequisite_terminal_skip"
        dependency["prerequisite_result"] = latest
        return "blocked"
    dependency["status"] = "deferred"
    return "deferred"


def _entry_latest_outcome(entry: Any) -> str:
    results = getattr(entry, "recent_results", ()) or ()
    latest = results[-1] if results else {}
    return str(latest.get("outcome") or "").strip().casefold()


def _entry_dependency_result(entry: Any) -> str:
    """Keep the one factual prerequisite result needed for a child recheck."""
    results = getattr(entry, "recent_results", ()) or ()
    latest = results[-1] if results else {}
    outcome = _entry_latest_outcome(entry)
    result = str(latest.get("result") or getattr(entry, "last_result", "") or "")
    parts = [str(getattr(entry, "target", "") or "前置入口").strip()]
    if outcome:
        parts.append(outcome)
    if result:
        parts.append(result.strip())
    return "：".join(part for part in parts if part)[:500]


def _entry_owner_survey_status(
    host: AutonomousTraversalRuntime,
    entry: Any,
) -> str:
    """Return whether an Entry's owning Region has a completed survey/audit."""
    page_name = str(getattr(entry, "page_name", "") or "")
    region_name = str(getattr(entry, "region_name", "") or "")
    state = host.region_states.get(_page_key(page_name))
    region = state.region(region_name) if state is not None else None
    if region is None or not region.get("coverage_complete"):
        return "waiting_region_survey"
    audit = (host.entry_review_audits.get(_page_key(page_name)) or {}).get(
        _page_key(region_name)) or {}
    if audit.get("status") != "complete":
        return "waiting_entry_review"
    return "ready"


def _entry_owner_is_ready(
    host: AutonomousTraversalRuntime,
    entry: Any,
) -> bool:
    """An exact Entry cannot run before its owner Region survey is accepted."""
    return _entry_owner_survey_status(host, entry) == "ready"


def _refresh_task_dependencies(host: AutonomousTraversalRuntime) -> None:
    for task_key in sorted(host.task_dependencies):
        _task_dependency_status(host, task_key)


def _entry_released_a_dependent(
    host: AutonomousTraversalRuntime,
    entry_id: str,
) -> bool:
    released = False
    for dependency in host.task_dependencies.values():
        if (
            isinstance(dependency, dict)
            and dependency.get("status") == "recheck_after_prerequisite"
            and dependency.get("rechecked_prerequisite_entry_id") == entry_id
            and not dependency.get("prerequisite_release_consumed")
        ):
            dependency["prerequisite_release_consumed"] = True
            released = True
    return released


def _defer_current_task(
    host: AutonomousTraversalRuntime,
    arguments: Dict[str, Any],
    *,
    assessment: PreviousAssessment,
) -> str:
    """Defer a blocked Entry until one exact open Entry is explored."""
    task = host.exploration_task
    target = str(arguments.get("prerequisite_target") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    if (
        task is None
        or task.task_type != "explore_entry"
        or task.phase != "locate_entry"
        or not task.entry_id
    ):
        return "defer_current_task is only valid for the visible assigned Entry"
    if not target or not reason:
        return "defer_current_task requires a concrete prerequisite target and reason"
    settled_without_visible_effect = (
        assessment.outcome == "no_visible_change"
        and not assessment.matches_intent
        and not assessment.failure_kind
    )
    blocked_before_attempt = (
        assessment.outcome == "not_applicable"
        and not assessment.failure_kind
    )
    if not settled_without_visible_effect and not blocked_before_attempt:
        return (
            "defer_current_task requires either a visible blocker before the "
            "exact Entry attempt or a latest exact attempt with no visible "
            "result and failure_kind=null"
        )
    current_key = _exploration_task_key(task)
    matching_entries = [
        entry for entry in host.entry_ledger.entries
        if _page_key(entry.target) == _page_key(target)
    ]
    previous_dependency = host.task_dependencies.get(current_key) or {}
    if (
        len(matching_entries) == 1
        and str(previous_dependency.get("status") or "")
        == "recheck_after_prerequisite"
        and str(previous_dependency.get("rechecked_prerequisite_entry_id") or "")
        == matching_entries[0].entry_id
    ):
        return (
            "the same prerequisite was already handled for this Entry; use the "
            "fresh target evidence to name a different concrete prerequisite"
        )
    candidates = [
        entry for entry in matching_entries
        if entry in host.entry_ledger.task_candidates()
    ]
    if len(candidates) != 1:
        return (
            "prerequisite_target must identify exactly one currently open Entry; "
            f"found {len(candidates)} matches for {target!r}"
        )
    prerequisite = candidates[0]
    prerequisite_key = f"explore:{prerequisite.entry_id}"
    if prerequisite_key == current_key:
        return "an Entry cannot defer itself to itself"
    cursor = prerequisite_key
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor == current_key:
            return "prerequisite dependency would create a cycle"
        seen.add(cursor)
        next_dependency = host.task_dependencies.get(cursor) or {}
        cursor = str(next_dependency.get("prerequisite_task_id") or "")
    host.task_dependencies[current_key] = {
        "prerequisite_task_id": prerequisite_key,
        "prerequisite_entry_id": prerequisite.entry_id,
        "prerequisite_target": prerequisite.target,
        "reason": reason[:500],
        "status": "deferred",
        "previous_prerequisite_entry_id": str(
            previous_dependency.get("rechecked_prerequisite_entry_id") or ""),
        "recheck_count": 0,
        "prerequisite_release_consumed": False,
    }
    return ""


def _region_probe_task(
    host: AutonomousTraversalRuntime, candidate: Dict[str, Any],
) -> ExplorationTask:
    region_ref = str(candidate["region_ref"])
    page_name = str(candidate["page_name"])
    region_name = str(candidate["region_name"])
    current_state_id = _current_page_state_id(host)
    target_state_ids = _region_probe_state_ids(
        host, page_name, region_name)
    needs_state_route = bool(
        current_state_id
        and target_state_ids
        and current_state_id not in target_state_ids
    )
    route_hint = (
        _region_probe_state_route_hint(host, target_state_ids)
        if needs_state_route
        else _verified_page_route_hint(host, page_name)
    )
    return ExplorationTask(
        task_type="explore_region",
        task_id=f"explore-region:{region_ref}",
        page_name=page_name,
        region_name=region_name,
        target=region_name,
        goal="discover_region_capabilities",
        phase=(
            "explore_region"
            if _page_key(host.protocol_map.current_page) == _page_key(page_name)
            and not needs_state_route
            else "route_to_page"
        ),
        reason=_region_probe_reason(host, region_ref),
        route_hint=route_hint,
    )


def _region_probe_candidates(
    host: AutonomousTraversalRuntime, *, include_suspended: bool = False,
) -> List[Dict[str, Any]]:
    bound = _page_key(host.protocol_map.current_page)
    _refresh_task_dependencies(host)
    best_by_ref: Dict[str, Dict[str, Any]] = {}
    for page_order, page_name in enumerate(host.protocol_map.pages):
        state = host.region_states.get(_page_key(page_name))
        audits = host.entry_review_audits.get(_page_key(page_name)) or {}
        if state is None:
            continue
        for region_order, region in enumerate(state.snapshot().get("regions") or []):
            region_name = str(region.get("name") or "").strip()
            if (not region_name or not region.get("coverage_complete")
                    or (audits.get(_page_key(region_name)) or {}).get("status")
                    != "complete"):
                continue
            region_ref = _region_probe_ref(host, page_name, region_name)
            progress = host.region_probe_progress.get(region_ref) or {}
            if not region_ref or progress.get("status") == "complete":
                continue
            task_id = f"explore-region:{region_ref}"
            if not include_suspended and task_id in host.suspended_task_keys:
                continue
            candidate = {
                "region_ref": region_ref,
                "page_name": page_name,
                "region_name": region_name,
                "task_id": task_id,
                "evidence_priority": _region_probe_evidence_priority(
                    host, region_ref),
                "local": 0 if _page_key(page_name) == bound else 1,
                "distance": len(host.protocol_map.route_hint(page_name)) or 10**6,
                "page_order": page_order,
                "region_order": region_order,
            }
            prior = best_by_ref.get(region_ref)
            sort_key = lambda item: (
                item["evidence_priority"], item["local"], item["distance"],
                item["page_order"], item["region_order"],
            )
            if prior is None or sort_key(candidate) < sort_key(prior):
                best_by_ref[region_ref] = candidate
    return sorted(best_by_ref.values(), key=lambda item: (
        item["evidence_priority"], item["local"], item["distance"],
        item["page_order"], item["region_order"],
    ))


def _region_probe_has_started(
    host: AutonomousTraversalRuntime, task_id: str,
) -> bool:
    return any(
        attempt.get("committed") is True
        and isinstance(attempt.get("evidence"), dict)
        and attempt["evidence"].get("region_probe_task") is True
        and str(attempt["evidence"].get("exploration_task_id") or "") == task_id
        for edge in host.graph.action_edges if isinstance(edge, dict)
        for attempt in edge.get("attempts") or [] if isinstance(attempt, dict)
    )


def _defer_action_after_stage_transition(
    history: List[Dict[str, Any]],
    task_before_sync: Optional[ExplorationTask],
    decision: AutonomousDecision,
    before_stage: Sequence[str],
    after_stage: Sequence[str],
) -> AutonomousDecision:
    """Freeze an action chosen for a stage that accepted evidence just closed."""
    if tuple(after_stage) == tuple(before_stage):
        return decision
    requested_tool = decision.tool_name if decision.action == "CALL_TOOL" else ""
    history.append({
        "kind": "stage_transition",
        "outcome": "stage_advanced",
        "from_stage": before_stage[0],
        "to_stage": after_stage[0],
        "deferred_tool": requested_tool,
        "deferred_status": "not_executed" if requested_tool else "",
        "deferred_entry_attempt_created": (
            False
            if requested_tool
            and task_before_sync is not None
            and task_before_sync.task_type == "explore_entry"
            else None
        ),
        "detail": (
            "The current observation completed or changed the stage; the "
            "requested tool in this response was not executed and created no "
            "new entry attempt. The next stage will receive a fresh prompt "
            "before any new tool executes."
            if requested_tool else
            "The current observation completed or changed the stage; the next "
            "stage will receive a fresh prompt before any new tool executes."
        ),
    })
    return AutonomousDecision(
        action="NONE",
        target="",
        point_1000=None,
        direction="",
        reason="stage changed after accepted evidence",
    )


def _sync_exploration_task(host: AutonomousTraversalRuntime) -> None:
    """Choose the graph-nearest open task, independent of task category."""
    _refresh_task_dependencies(host)
    bound_state_id = _current_page_state_id(host)
    pages = list(host.protocol_map.pages)
    if not pages:
        initial_task = _survey_task(
            host,
            "",
            reason="initial_page_identity_and_structure_are_unknown",
            region_name="",
            phase="identify_page",
        )
        if _exploration_task_key(initial_task) in host.suspended_task_keys:
            host.exploration_task = None
            host.graph.stop_reason = "all_remaining_work_suspended"
        else:
            host.exploration_task = initial_task
        return

    bound = _page_key(host.protocol_map.current_page)

    # A task is not a one-turn suggestion: route, scroll, locating and recovery
    # remain intermediate work toward the same exact target. A new global choice
    # happens only after that target settles, the task becomes dependent, or it
    # is explicitly suspended.
    current = host.exploration_task
    current_key = _exploration_task_key(current)
    if (
        current is not None
        and current.task_type == "explore_entry"
        and _entry_released_a_dependent(host, current.entry_id)
    ):
        # A real prerequisite result, even one that contradicted its own
        # expected outcome, gives its dependent one fresh recheck before this
        # prerequisite is retried.
        host.exploration_task = None
        current = None
        current_key = ""
    if (
        current is not None
        and current_key not in host.suspended_task_keys
        and _task_dependency_status(host, current_key) == "ready"
    ):
        if current.task_type == "explore_entry":
            try:
                record = host.entry_ledger.get(current.entry_id)
            except KeyError:
                record = None
            if (
                record is not None
                and record.task_eligible
                and not record.representative_entry_id
                and record.status.value not in {"verified", "inferred"}
                and _entry_owner_is_ready(host, record)
            ):
                on_source_state, route_hint = _entry_source_route(host, record)
                phase = "locate_entry" if on_source_state else "route_to_source"
                refreshed = ExplorationTask(
                    task_type="explore_entry",
                    task_id=current.task_id,
                    entry_id=record.entry_id,
                    page_name=record.page_name,
                    region_name=record.region_name,
                    target=record.target,
                    goal=current.goal,
                    phase=phase,
                    reason=current.reason,
                    route_hint=route_hint,
                )
                if (
                    phase == "locate_entry"
                    or refreshed.route_hint
                    or _can_discover_same_page_route(host, refreshed)
                ):
                    host.exploration_task = refreshed
                    host.graph.stop_reason = ""
                    return
        elif current.task_type == "survey_page":
            target_page = current.page_name or host.protocol_map.current_page
            if target_page:
                needs = _page_survey_needs(
                    host,
                    target_page,
                    state_id=(
                        bound_state_id
                        if _page_key(target_page) == bound else ""),
                )
                selected_need = next((
                    need for need in needs
                    if current.region_name
                    and _page_key(need[1]) == _page_key(current.region_name)
                ), needs[0] if needs else None)
                if selected_need is not None:
                    reason, region_name, phase = selected_need
                    refreshed = _survey_task(
                        host,
                        target_page,
                        reason=reason,
                        region_name=region_name,
                        phase=(
                            phase if _page_key(target_page) == bound
                            else "route_to_page"
                        ),
                    )
                    if (
                        refreshed.phase != "route_to_page"
                        or refreshed.route_hint
                        or _can_discover_same_page_route(host, refreshed)
                    ):
                        host.exploration_task = refreshed
                        host.graph.stop_reason = ""
                        return
        host.exploration_task = None

    candidates: List[Dict[str, Any]] = []
    all_task_keys: List[str] = []
    deferred_task_keys: List[str] = []
    blocked_task_keys: List[str] = []
    def add(task: ExplorationTask) -> None:
        task_key = _exploration_task_key(task)
        all_task_keys.append(task_key)
        if task_key not in host.task_creation_order:
            host.task_creation_order[task_key] = host.next_task_creation_order
            host.next_task_creation_order += 1
        discover_same_page_route = _can_discover_same_page_route(host, task)
        route_distance = (
            len(task.route_hint)
            if task.route_hint else (1 if discover_same_page_route else 10**6)
        )
        distance = (
            0
            if task.phase not in {"route_to_page", "route_to_source"}
            else route_distance
        )
        dependency_status = _task_dependency_status(host, task_key)
        if dependency_status == "deferred":
            deferred_task_keys.append(task_key)
            return
        if dependency_status == "blocked":
            blocked_task_keys.append(task_key)
            return
        if (
            task_key not in host.suspended_task_keys
            and distance < 10**6
        ):
            candidates.append({
                "dependency_priority": (
                    0 if (
                        host.task_dependencies.get(task_key, {}).get("status")
                        == "recheck_after_prerequisite"
                    ) else 1
                ),
                "distance": distance,
                "order": host.task_creation_order[task_key],
                "task": task,
            })

    for page_name in pages:
        needs = _page_survey_needs(
            host,
            page_name,
            state_id=(
                bound_state_id if _page_key(page_name) == bound else ""),
        )
        for reason, region_name, phase in needs:
            add(_survey_task(
                host,
                page_name,
                reason=reason,
                region_name=region_name,
                phase=(
                    phase
                    if _page_key(page_name) == bound else "route_to_page"
                ),
            ))

    all_entry_candidates = list(host.entry_ledger.task_candidates())
    for entry in all_entry_candidates:
        on_source_state, route_hint = _entry_source_route(host, entry)
        entry_task = ExplorationTask(
            task_type="explore_entry",
            task_id=f"explore:{entry.entry_id}",
            entry_id=entry.entry_id,
            page_name=entry.page_name,
            region_name=entry.region_name,
            target=entry.target,
            goal="explore_function",
            phase="locate_entry" if on_source_state else "route_to_source",
            reason="registered_entry_awaits_real_function_probe",
            route_hint=route_hint,
        )
        # Keep the durable child task known to completion, but its owning Region
        # survey/audit is a hard execution gate rather than a soft priority.
        if not _entry_owner_is_ready(host, entry):
            task_key = _exploration_task_key(entry_task)
            all_task_keys.append(task_key)
            if task_key not in host.task_creation_order:
                host.task_creation_order[task_key] = host.next_task_creation_order
                host.next_task_creation_order += 1
            continue
        add(entry_task)

    if candidates:
        selected = min(candidates, key=lambda item: (
            item["dependency_priority"],
            item["distance"],
            # At equal graph distance, finish an incomplete Region survey on
            # the current Page before leaving through a ready child Entry.
            0 if (
                item["task"].task_type == "survey_page"
                and _page_key(item["task"].page_name) == bound
            ) else 1,
            item["order"],
        ))
        host.exploration_task = selected["task"]
        host.graph.stop_reason = ""
        return

    if all_task_keys and all(
            task_key in host.suspended_task_keys for task_key in all_task_keys):
        host.exploration_task = None
        host.graph.stop_reason = "all_remaining_work_suspended"
        return
    if all_task_keys and blocked_task_keys and len(blocked_task_keys) == len(
            all_task_keys):
        host.exploration_task = None
        host.graph.stop_reason = "prerequisite_blocked"
        return
    if all_task_keys and deferred_task_keys and len(deferred_task_keys) == len(
            all_task_keys):
        host.exploration_task = None
        host.graph.stop_reason = "prerequisite_pending"
        return
    if all_task_keys:
        host.exploration_task = None
        host.graph.stop_reason = "unverified_route_remaining"
        return
    host.exploration_task = None


def _dynamic_tool_catalog(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    history: Sequence[Dict[str, Any]] = (),
    *,
    identity_stage: str = "",
) -> List[Dict[str, Any]]:
    if str(identity_stage or "").strip().casefold() in {"page", "variant"}:
        return [
            item for item in available_tool_catalog(pending_identity=False)
            if item.get("name") in {
                "page_identity", "report_record_error", "handle_interruption",
            }
        ]
    task_type = (
        host.exploration_task.task_type
        if host.exploration_task is not None else "survey_page"
    )
    if task_type == "survey_page":
        allowed_names = SURVEY_TASK_TOOL_NAMES
    else:
        allowed_names = EXPLORE_TASK_TOOL_NAMES
    catalog = [
        item for item in available_tool_catalog(pending_identity=False)
        if item.get("name") in allowed_names
    ]
    if _current_entry_review_record(
        history,
        page_name=host.protocol_map.current_page,
        frame_id=screenshot_frame_id(screenshot),
    ) is None:
        catalog = [
            item for item in catalog
            if item.get("name") != "review_entry_record"
        ]
    catalog.extend(
        item for item in action_tool_catalog(platform=host.platform)
        if item.get("name") in allowed_names)
    if task_type == "explore_entry" and host.exploration_task is not None:
        try:
            entry = host.entry_ledger.get(host.exploration_task.entry_id)
        except KeyError:
            entry = None
        if entry is not None and entry.control_type == "input":
            catalog.extend(
                item for item in action_tool_catalog(platform=host.platform)
                if item.get("name") == "input_text")
    task_key = _exploration_task_key(host.exploration_task) or "unassigned"
    if (
        host.interruption_task_key == task_key
        and host.interruption_rounds >= INTERRUPTION_ROUND_LIMIT
    ):
        catalog = [
            item for item in catalog
            if item.get("name") != "handle_interruption"
        ]
    return catalog


def _repeat_no_change_scroll_issue(
    history: Sequence[Dict[str, Any]],
    validated_action: Any,
    current_frame_id: str,
) -> str:
    """Reject only an exact scroll repeat on its unchanged result frame."""
    if (validated_action is None
            or validated_action.operation != "scroll"):
        return ""
    previous: Optional[Dict[str, Any]] = None
    for record in reversed(history):
        if (record.get("kind") == "action"
                and isinstance(record.get("action_tool_result"), dict)):
            previous = record
            break
    if previous is None:
        return ""
    result = previous["action_tool_result"]
    if (result.get("status") != "observed"
            or result.get("operation") != "scroll"
            or result.get("moved") is not False
            or result.get("before_frame_id") != result.get("after_frame_id")
            or result.get("after_frame_id") != current_frame_id):
        return ""
    previous_action = previous.get("validated_action")
    if not isinstance(previous_action, dict):
        return ""
    previous_arguments = previous_action.get("arguments")
    if (previous_action.get("operation") != "scroll"
            or not isinstance(previous_arguments, dict)):
        return ""
    current_arguments = validated_action.arguments
    fields = ("container_hint", "point_1000", "direction", "amount")
    if any(previous_arguments.get(field) != current_arguments.get(field)
           for field in fields):
        return ""
    return (
        "The identical normalized scroll was already executed on this "
        "byte-identical frame and produced no frame change. Change "
        "container_hint, point_1000, direction, or amount; choose another "
        "action; or report a concrete blocker."
    )


def _repeat_task_frame_action_issue(
    history: Sequence[Dict[str, Any]],
    validated_action: Any,
    task_id: str,
    task_phase: str,
) -> str:
    """Reject a real GUI state-action pair already visited in this phase."""
    if (validated_action is None
            or not validated_action.env_action
            or not task_id
            or not task_phase):
        return ""
    current = validated_action.to_dict()
    for record in reversed(history):
        if (record.get("kind") != "action"
                or record.get("exploration_task_id") != task_id
                or record.get("exploration_task_phase") != task_phase):
            continue
        result = record.get("action_tool_result")
        if (not isinstance(result, dict)
                or result.get("status") != "observed"
                or not result.get("env_action")):
            continue
        previous = record.get("validated_action")
        if not isinstance(previous, dict):
            continue
        if all(previous.get(field) == current.get(field) for field in (
                "tool_name", "operation", "frame_id", "arguments")):
            return (
                "This exact normalized GUI action was already executed from "
                "this byte-identical frame during the current exploration "
                "phase. Choose a different action or point, wait for genuinely "
                "new state, or report a concrete blocker."
            )
    return ""


def _covered_region_probe_operation_issue(
    host: AutonomousTraversalRuntime,
    operation_key: str,
) -> str:
    """Reject a settled value-input operation already covered in this Region."""
    task = host.exploration_task
    if (not operation_key or task is None
            or task.task_type != "explore_region"
            or task.phase != "explore_region"):
        return ""
    region_ref = _region_probe_ref(host, task.page_name, task.region_name)
    progress = host.region_probe_progress.get(region_ref) or {}
    if operation_key not in (progress.get("covered_operations") or []):
        return ""
    return (
        "This reviewed input operation is already covered for traversal. "
        "Changing only its input value is another homogeneous example, not a "
        "new core operation. Choose a different visible operation, or return "
        "action=null when none remains."
    )


def _repeat_task_frame_record_error_issue(
    history: Sequence[Dict[str, Any]],
    *,
    task_id: str,
    frame_id: str,
    error_kind: str,
) -> str:
    """Reject rewording the same diagnostic without new task/frame evidence."""
    if not task_id or not frame_id or not error_kind:
        return ""
    for record in reversed(history):
        if (record.get("kind") != "tool"
                or record.get("tool_name") != "report_record_error"
                or record.get("outcome") != "reported"):
            continue
        arguments = record.get("tool_arguments")
        if not isinstance(arguments, dict):
            continue
        if (
            record.get("exploration_task_id") == task_id
            and record.get("frame_id") == frame_id
            and str(arguments.get("kind") or "").strip().casefold()
            == error_kind
        ):
            return (
                f"A {error_kind} record error was already saved for task "
                f"{task_id!r} on this byte-identical frame. Changing its "
                "subject or wording is not new evidence. Choose another "
                "available action or tool, or report again after the frame, "
                "task, or error kind changes."
            )
    return ""


def _repeat_wait_issue(
    history: Sequence[Dict[str, Any]],
    *,
    task_id: str,
    frame_id: str,
) -> str:
    """Reject WAIT when neither the task nor screenshot has changed."""
    if not task_id or not frame_id:
        return ""
    for record in reversed(history):
        if record.get("kind") != "action":
            continue
        if record.get("exploration_task_id") != task_id:
            continue
        if record.get("action") != "WAIT":
            break
        if record.get("frame_id") == frame_id:
            return (
                "WAIT was already requested for this task on the same "
                "byte-identical frame. Choose an available action or tool, "
                "or report a concrete blocker."
            )
        break
    return ""


def _complete_region_task_from_no_action(
    host: AutonomousTraversalRuntime,
    *,
    reason: str,
) -> bool:
    """Close the exact active Region task after one no-action main round."""
    task = host.exploration_task
    if (task is None or task.task_type != "explore_region"
            or task.phase != "explore_region"):
        return False
    if _page_key(host.protocol_map.current_page) != _page_key(task.page_name):
        return False
    region_ref = _region_probe_ref(host, task.page_name, task.region_name)
    if not region_ref:
        return False
    current_state_id = _current_page_state_id(host)
    occurrence_states = _region_probe_state_ids(
        host, task.page_name, task.region_name)
    if (
        current_state_id
        and occurrence_states
        and current_state_id not in occurrence_states
    ):
        return False
    progress = host.region_probe_progress.setdefault(region_ref, {})
    progress.update({
        "status": "complete",
        "page_name": task.page_name,
        "region_name": task.region_name,
        "reason": str(reason or "").strip()[:800],
    })
    progress.setdefault("completed_attempts", 0)
    return True


def _record_region_probe_attempt(
    host: AutonomousTraversalRuntime, pending: PendingAction,
) -> None:
    evidence = pending.evidence
    if evidence.get("region_probe_task") is not True:
        return
    region_ref = str(evidence.get("source_region_ref") or "").strip()
    task_id = str(evidence.get("exploration_task_id") or "").strip()
    if not region_ref or not task_id:
        return
    progress = host.region_probe_progress.setdefault(region_ref, {})
    if progress.get("last_completed_event_index") == pending.event_index:
        return
    progress.update({
        "status": "open",
        "page_name": str(evidence.get("source_page") or ""),
        "region_name": str(evidence.get("source_region") or ""),
        "completed_attempts": _probe_attempt_count(progress) + 1,
        "last_completed_task_id": task_id,
        "last_completed_event_index": pending.event_index,
    })
    operation_key = str(
        evidence.get("region_probe_operation_key") or "").strip()
    if operation_key:
        covered = progress.setdefault("covered_operations", [])
        if operation_key not in covered:
            covered.append(operation_key)
