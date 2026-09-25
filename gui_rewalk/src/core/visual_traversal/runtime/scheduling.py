"""Frontier scheduling, routing, and no-candidate recovery."""
from __future__ import annotations

import copy
import io
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from PIL import Image

from ..action_space import (
    action_is_targeted, is_android, normalize_native_action,
)

from .contracts import (
    CandidateContext, PerceptionUnavailable, RunCursor, StageDirective,
    TraversalRuntimeHost,
)
from .element_task import (
    active_element_task, finish_element_task, finish_resolved_goal,
    compact_page_graph, start_element_task,
    record_element_task_route, record_element_task_tool,
    task_goal_action_verified, task_goal_resolved,
    task_memory_for_prompt, task_progress_facts, task_route_guidance,
)
from .agent_tools import (
    ToolContext, current_region_directory, execute_agent_tool, tool_catalog,
)
from .landing import (
    _clear_mutation_on_verified_baseline_return,
    _record_restore_on_latest_verified_landing,
    _refresh_verified_return_landing,
)
from .recovery import recover_route_observation
from ..stateful import normalize_state_key

logger = logging.getLogger(__name__)

MAX_TARGET_ROUTE_FAILURES = 2
MAX_EXPLORER_REGION_FAILURES = 2


def _direct_task_element(target: str, action_type: str):
    """Create an observation-local label carrier for a direct Agent action."""
    element_id = f"agent-{target}"
    return SimpleNamespace(
        id=element_id, uid=element_id, name=str(target or action_type),
        region="agent_direct", region_id="", center=[0, 0],
        interactive=True, enabled=True, category="navigation",
        el_type="button", back=(action_type == "BACK"), selected=False,
        stateful=False, state_key="", state_value="", effect_scope="",
        reversible=None, risk="none", exploration_status="pending",
        is_safe_stateful_surface=lambda: False,
    )


def _direct_task_action(platform: str, screenshot: bytes,
                        payload: Dict[str, Any]):
    action_type = str(payload.get("type") or "").strip().upper()
    point = payload.get("point_1000")
    pixel_point = None
    if isinstance(point, list) and len(point) == 2:
        try:
            image = Image.open(io.BytesIO(screenshot))
            pixel_point = [
                round(float(point[0]) * max(0, image.width - 1) / 1000.0),
                round(float(point[1]) * max(0, image.height - 1) / 1000.0),
            ]
        except (OSError, TypeError, ValueError):
            return None, "current screenshot cannot resolve point_1000"
    mobile = is_android(platform)
    if action_type == "CLICK" and pixel_point is not None:
        requested = (
            {"action_type": "click", "x": pixel_point[0], "y": pixel_point[1]}
            if mobile else
            {"action_type": "CLICK", "parameters": {
                "x": pixel_point[0], "y": pixel_point[1], "button": "left"}}
        )
    elif action_type == "SCROLL":
        direction = str(payload.get("direction") or "").strip().casefold()
        if mobile:
            requested = {"action_type": "scroll", "direction": direction}
            if pixel_point is not None:
                requested.update({"x": pixel_point[0], "y": pixel_point[1]})
        else:
            dx, dy = {
                "up": (0, 8), "down": (0, -8),
                "left": (-8, 0), "right": (8, 0),
            }.get(direction, (0, 0))
            requested = {"action_type": "SCROLL", "parameters": {
                "dx": dx, "dy": dy, "direction": direction, "amount": 1}}
            if pixel_point is not None:
                requested["parameters"].update({
                    "x": pixel_point[0], "y": pixel_point[1]})
    elif action_type == "BACK":
        requested = (
            {"action_type": "navigate_back"}
            if mobile else
            {"action_type": "PRESS", "parameters": {"key": "esc"}}
        )
    elif action_type == "WAIT":
        requested = (
            {"action_type": "wait"}
            if mobile else {"action_type": "WAIT", "parameters": {}}
        )
    else:
        return None, f"unsupported direct task action: {action_type}"
    return normalize_native_action(requested, platform=platform)


def _active_restore_candidate(host, active, element) -> bool:
    matcher = getattr(host, "_is_active_restore_candidate", None)
    if callable(matcher):
        return bool(matcher(active, element))
    return (
        bool(getattr(element, "is_safe_stateful_surface", lambda: False)())
        and normalize_state_key(getattr(element, "state_key", ""))
        == normalize_state_key((active or {}).get("state_key", ""))
    )


def _adopt_stateful_restore_landing(host, state_id: str):
    """Keep restoration local when Router reaches an equivalent live variant."""
    active = getattr(host, "_active_state_mutation", None)
    if not active or state_id not in getattr(host, "_state_data", {}):
        return None
    source_state = str(active.get("source_state") or "")
    mutated_state = str(active.get("mutated_state") or "")
    if state_id == source_state and source_state != mutated_state:
        return None
    live_elements = (
        list(getattr(host, "_last_live_observation_elements", None) or [])
        if str(getattr(
            host, "_last_live_observation_state_id", "") or "") == str(state_id)
        else []
    )
    candidates = live_elements + list(
        (host._state_data.get(state_id) or {}).get("elements", []))
    inverse = next((
        element
        for element in candidates
        if _active_restore_candidate(host, active, element)
    ), None)
    if inverse is None:
        return None
    previous = str(active.get("mutated_state") or "")
    active["mutated_state"] = str(state_id)
    active["inverse_element"] = inverse
    getattr(host, "_route_blocked_targets", set()).discard(str(state_id))
    host.review_debug.record_event(
        "stateful_restore_landing_adopted",
        previous_state=previous,
        live_state=str(state_id),
        element=str(getattr(inverse, "name", "") or ""),
        mutation_id=str(active.get("mutation_id") or ""),
    )
    logger.info(
        "stateful mutation %s adopted live inverse on %s instead of routing "
        "back to stale variant %s",
        active.get("mutation_id", "?"), str(state_id)[:8],
        previous[:8],
    )
    return inverse


@dataclass
class SchedulingOutcome:
    stop: bool
    state_id: str
    path: List[Dict[str, object]]
    replay_hints: List[Optional[Dict[str, object]]]
    observation: Dict[str, object]
    off_app_streak: int


def _incomplete_scroll_records(host: TraversalRuntimeHost, target_state=None):
    records = [
        record for record in getattr(host.graph, "scroll_ledger", {}).values()
        if isinstance(record, dict) and record.get("complete") is not True
    ]
    if target_state is None:
        return records
    target_regions = {
        str(block.get("region_id") or "")
        for block in (
            getattr(host, "_state_data", {}).get(str(target_state), {})
            .get("semantic_blocks") or [])
        if str(block.get("region_id") or "")
    }
    return [
        record for record in records
        if (
            str(target_state) in {
                str(item) for item in (record.get("state_ids") or [])
            }
            or (
                str(record.get("region_id") or "")
                and str(record.get("region_id") or "") in target_regions
            )
        )
    ]


def _explorer_region_failure_key(state_id: str, element) -> tuple[str, str]:
    return str(state_id), _region_key(element)


def _verified_pending_mutation_return(
        host: TraversalRuntimeHost, state_id: str):
    """Reopen one verified return control solely for pending restoration.

    A reusable confirmation surface can already have every control marked
    complete.  Completion remains durable coverage, but an unresolved mutation
    still needs a previously verified dismiss/return action to restore its
    source.  Reopen a copy so canonical exploration status is not changed.
    """
    active = getattr(host, "_active_state_mutation", None)
    router = getattr(host, "router", None)
    if (
        not active
        or str(active.get("mutated_state") or "") != str(state_id)
        or str(active.get("after_value") or "").strip().lower() != "unknown"
        or router is None
        or not callable(getattr(router, "node_out_edges", None))
    ):
        return None
    source_id = str(active.get("source_state") or "")
    if not source_id:
        return None
    edges = router.node_out_edges(
        str(state_id), arrival_source_id=source_id)
    elements = list(
        (getattr(host, "_state_data", {}).get(str(state_id)) or {}).get(
            "elements") or [])
    for edge in edges.values():
        action = edge.get("action") if isinstance(
            edge.get("action"), dict) else {}
        destination = str(edge.get("dst") or "")
        is_live_ancestor = (
            callable(getattr(router, "_is_live_stack_ancestor", None))
            and router._is_live_stack_ancestor(source_id, destination)
        )
        if (
            str(action.get("action_type") or "").strip().upper() != "CLICK"
            or not (destination == source_id or is_live_ancestor)
            or str(edge.get("provenance") or "") not in {
                "direct_verified", "context_predicted",
            }
            or str(edge.get("effect_kind") or "").casefold() not in {
                "return", "return_via_control", "return_native_action",
                "dismiss_overlay",
            }
        ):
            continue
        edge_id = str(edge.get("element_id") or "")
        edge_label = " ".join(
            str(edge.get("label") or "").casefold().split())
        edge_region = str(edge.get("region") or "")
        for element in elements:
            element_id = str(getattr(element, "id", ""))
            element_label = " ".join(
                str(getattr(element, "name", "") or "").casefold().split())
            id_matches = bool(edge_id and element_id == edge_id)
            label_matches = bool(
                not edge_id and edge_label and element_label == edge_label
                and (
                    not edge_region
                    or str(getattr(element, "region", "") or "") == edge_region
                )
            )
            if not (id_matches or label_matches):
                continue
            dangerous = getattr(element, "is_dangerous", None)
            if (
                getattr(element, "interactive", True) is False
                or getattr(element, "enabled", None) is False
                or getattr(element, "requires_permission", False)
                or bool(getattr(element, "blocked_reason", ""))
                or (callable(dangerous) and dangerous())
            ):
                continue
            reopened = copy.copy(element)
            reopened.visited = False
            reopened.back = True
            reopened.exploration_status = "deferred_return"
            reopened.exploration_reason = (
                "reused landing-verified return for pending state restoration")
            reopened._pending_restore_execution = True
            return reopened
    return None


def available_unvisited_candidates(
        host: TraversalRuntimeHost, state_id: str):
    """Return pending controls outside regions deferred after an invalid decision."""
    if _apply_verified_reverse_control_coverage(host, state_id):
        persist_status = getattr(host, "_persist_exploration_state", None)
        if callable(persist_status):
            persist_status(state_id)
    if _apply_verified_stable_control_coverage(host, state_id):
        persist_status = getattr(host, "_persist_exploration_state", None)
        if callable(persist_status):
            persist_status(state_id)
    if _apply_verified_group_coverage(host, state_id):
        persist_status = getattr(host, "_persist_exploration_state", None)
        if callable(persist_status):
            persist_status(state_id)
    active = getattr(host, "_active_state_mutation", None)
    if (
        active
        and str(getattr(
            host, "_last_live_observation_state_id", "") or "") == str(state_id)
    ):
        _clear_mutation_on_verified_baseline_return(
            host,
            str(state_id),
            list(getattr(host, "_last_live_observation_elements", None) or []),
            observation_fresh=True,
            record_restore=lambda evidence: (
                _record_restore_on_latest_verified_landing(
                    host, str(state_id), evidence)),
        )
        active = getattr(host, "_active_state_mutation", None)
    if (
        active
        and str(state_id) == str(active.get("source_state") or "")
        and str(active.get("source_state") or "")
        != str(active.get("mutated_state") or "")
    ):
        return []
    deferred = getattr(host, "_explorer_deferred_regions", set())
    observer_unresolved = getattr(
        host, "_observer_unresolved_controls", set())
    pending = [
        element for element in host._unvisited_candidates(state_id)
        if _explorer_region_failure_key(state_id, element) not in deferred
        and (state_id, element.uid or element.name) not in observer_unresolved
    ]
    if pending:
        return pending
    verified_return = _verified_pending_mutation_return(host, state_id)
    return [verified_return] if verified_return is not None else []


def _deferred_explorer_work(host: TraversalRuntimeHost):
    work = []
    deferred = getattr(host, "_explorer_deferred_regions", set())
    for state_id, region_key in sorted(deferred):
        if state_id not in getattr(host, "_state_data", {}):
            continue
        if any(
                _region_key(element) == region_key
                for element in host._unvisited_candidates(state_id)):
            work.append((state_id, region_key))
    return work


def _unresolved_observer_work(host: TraversalRuntimeHost):
    work = []
    unresolved = getattr(host, "_observer_unresolved_controls", set())
    for state_id, control_key in sorted(unresolved):
        if state_id not in getattr(host, "_state_data", {}):
            continue
        if any(
                (element.uid or element.name) == control_key
                for element in host._unvisited_candidates(state_id)):
            work.append((state_id, control_key))
    return work


def _frontier_state_candidates(host: TraversalRuntimeHost, current_id: str):
    """Return known remote States that still contain factual pending work."""
    from .region_observation import pending_region_ids

    result = []
    graph = getattr(getattr(host, "graph", None), "graph", None)
    if graph is None:
        return result
    nodes = getattr(graph, "nodes", None)
    if callable(nodes):
        state_ids = list(nodes())
    else:
        state_ids = list(getattr(getattr(host, "graph", None), "nodes", []))
    for state_id in state_ids:
        state_id = str(state_id)
        if (
            state_id == str(current_id)
            or state_id in getattr(host, "_route_blocked_targets", set())
        ):
            continue
        pending_regions = pending_region_ids(host, state_id)
        pending_entries = available_unvisited_candidates(host, state_id)
        if not pending_regions and not pending_entries:
            continue
        result.append((state_id, pending_regions, pending_entries))
    return result


def _qwen_frontier_choice(host: TraversalRuntimeHost, current_id: str,
                          observation):
    """Let Qwen select the next known State; Router only realizes the route."""
    choices = _frontier_state_candidates(host, current_id)
    if not choices:
        return None, False
    explorer = getattr(host, "explorer", None)
    choose_route = getattr(explorer, "choose_route", None)
    if not callable(choose_route):
        return None, False
    state_by_prompt_id = {}
    rows = []
    route_failures = getattr(host, "_route_failures", {}) or {}
    for index, (state_id, pending_regions, pending_entries) in enumerate(
            choices):
        prompt_id = f"p{index}"
        state_by_prompt_id[prompt_id] = state_id
        feedback = []
        for (source, target), failure in route_failures.items():
            if str(target) != state_id or not isinstance(failure, dict):
                continue
            feedback.append({
                "from": str((host._state_data.get(str(source)) or {}).get(
                    "page_name") or source),
                "status": str(failure.get("status") or ""),
                "failure_kind": str(failure.get("failure_kind") or ""),
                "actual_landing": str(
                    (host._state_data.get(str(
                        failure.get("landed_id") or "")) or {}).get(
                            "page_name")
                    or failure.get("landed_id") or ""),
            })
        state_data = host._state_data.get(state_id) or {}
        region_names = []
        for region_id in pending_regions:
            block = next((
                item for item in state_data.get("semantic_blocks") or []
                if str(item.get("region_id") or "") == str(region_id)
            ), {})
            region_names.append(str(
                block.get("role") or block.get("description")
                or "unobserved area"))
        rows.append({
            "page_id": prompt_id,
            "name": str(state_data.get("page_name") or ""),
            "pending_entries": [
                str(getattr(element, "name", "") or "")
                for element in pending_entries
            ],
            "pending_regions": region_names,
            "previous_route_feedback": feedback,
        })
    current_data = host._state_data.get(str(current_id)) or {}
    decision = choose_route(
        (observation or {}).get("screenshot"),
        {
            "application_name": str(getattr(host, "app_name", "") or ""),
            "current_interface": str(current_data.get("page_name") or ""),
            "candidate_pages": rows,
        },
    )
    selected = str((decision or {}).get("selected_page_id") or "")
    target = state_by_prompt_id.get(selected)
    if target is None:
        reason = str(getattr(explorer, "last_reason", "") or
                     (decision or {}).get("reason") or
                     "Qwen did not choose a pending interface")
        host.review_debug.record_agent(
            "explorer_route", node=current_id,
            step=host._action_count + 1, verdict="NO_SELECTION",
            reason=reason[:200],
            candidate_pages=rows,
            prompts=list(getattr(explorer, "last_prompts", []) or []),
            backend_runs=list(getattr(
                explorer, "last_backend_runs", []) or []),
            raw_responses=list(getattr(
                explorer, "last_raw_responses", []) or []),
        )
        host.graph.stop_reason = "explorer_unavailable"
        return None, True
    host.review_debug.record_agent(
        "explorer_route", node=current_id,
        step=host._action_count + 1, verdict=target,
        reason=str((decision or {}).get("reason") or "")[:200],
        selected_page=str(
            (host._state_data.get(target) or {}).get("page_name") or ""),
        candidate_pages=rows,
        prompts=list(getattr(explorer, "last_prompts", []) or []),
        backend_runs=list(getattr(
            explorer, "last_backend_runs", []) or []),
        raw_responses=list(getattr(
            explorer, "last_raw_responses", []) or []),
    )
    return target, False


def _normalized_control_name(element) -> str:
    return " ".join(
        str(getattr(element, "name", "") or "").casefold().split())


def _stable_control_binding(
        host: TraversalRuntimeHost, target_state_id: str, live_state_id: str):
    """Find a live occurrence of target work inside the same mapped Region."""
    target_pending = list(host._unvisited_candidates(str(target_state_id)))
    live_elements = list(
        (getattr(host, "_state_data", {}).get(str(live_state_id)) or {}).get(
            "elements") or [])
    for target in target_pending:
        target_region = str(getattr(target, "region_id", "") or "")
        target_name = _normalized_control_name(target)
        if not target_region or not target_name:
            continue
        target_matches = [
            candidate for candidate in target_pending
            if (
                str(getattr(candidate, "region_id", "") or "")
                == target_region
                and _normalized_control_name(candidate) == target_name
            )
        ]
        live_matches = [
            live for live in live_elements
            if (
                str(getattr(live, "region_id", "") or "") == target_region
                and _normalized_control_name(live) == target_name
                and getattr(live, "interactive", None) is not False
                and getattr(live, "enabled", None) is not False
                and not bool(getattr(live, "blocked_reason", ""))
            )
        ]
        if len(target_matches) == 1 and len(live_matches) == 1:
            return target, live_matches[0]
    return None


def _retire_currently_unreachable_target(
    host: TraversalRuntimeHost,
    target_id: str,
    route_result,
) -> bool:
    """Close one historical State after bounded, known live route failures."""
    attempts = int(getattr(route_result, "attempts_used", 0) or 0)
    landed_id = str(getattr(route_result, "landed_id", "") or "")
    failure_kind = str(getattr(route_result, "failure_kind", "") or "")
    if (
        not landed_id
        or landed_id == str(target_id)
        or landed_id not in getattr(host, "_state_data", {})
        or (
            getattr(host, "_active_state_mutation", None)
            and str(target_id) in {
                str(host._active_state_mutation.get("source_state") or ""),
                str(host._active_state_mutation.get("mutated_state") or ""),
            }
        )
    ):
        return False
    failure_counts = getattr(host, "_route_target_failure_counts", None)
    if failure_counts is None:
        failure_counts = {}
        host._route_target_failure_counts = failure_counts
    failure_counts[target_id] = int(failure_counts.get(target_id, 0)) + 1
    attempts = max(attempts, failure_counts[target_id])
    if attempts < MAX_TARGET_ROUTE_FAILURES:
        return False
    evidence = {
        "kind": "route_unavailable",
        "attempts_used": attempts,
        "failure_kind": failure_kind,
        "landed_state_id": landed_id,
    }
    retired = 0
    seen = set()
    while True:
        candidates = []
        for element in host._unvisited_candidates(target_id):
            key = (
                str(getattr(element, "uid", "") or ""),
                str(getattr(element, "id", "") or ""),
                str(getattr(element, "region_id", "") or ""),
                str(getattr(element, "name", "") or ""),
            )
            if key not in seen:
                seen.add(key)
                candidates.append(element)
        if not candidates:
            break
        for element in candidates:
            host._record_abnormal_button(
                target_id,
                element,
                "route_unavailable",
                (
                    f"bounded route replay landed on known state {landed_id}; "
                    "retired for this run without claiming the control absent"
                ),
                evidence=evidence,
            )
            retired += 1
    if not retired:
        return False
    host.review_debug.record_event(
        "route_target_retired_for_run",
        target=target_id,
        landed=landed_id,
        attempts_used=attempts,
        failure_kind=failure_kind,
        controls=retired,
    )
    logger.warning(
        "route to %s repeatedly landed on known state %s; retired %d "
        "source-local target(s) for this run",
        target_id, landed_id, retired,
    )
    return True


def prepare_current_scroll_audit(
        host: TraversalRuntimeHost, state_id, observation,
        path, replay_hints, off_app_streak):
    """Finish the current state's first scroll audit before its controls run."""
    deferred = getattr(host, "_scroll_audit_deferred_states", set())
    if str(state_id) in deferred:
        return None
    incomplete = _incomplete_scroll_records(host, state_id)
    if not incomplete:
        return None

    if any(
            int(record.get("observations", 0) or 0) == 1
            for record in incomplete):
        logger.warning(
            "retrying incomplete first scroll audit for %s",
            state_id[:8])
        try:
            retry_scroll = getattr(
                host, "_retry_incomplete_scroll_audit", None)
            if callable(retry_scroll):
                retry_scroll(observation, state_id)
        except PerceptionUnavailable as exc:
            logger.warning("scroll audit retry failed: %s", exc)
        incomplete = _incomplete_scroll_records(host, state_id)
        if not incomplete:
            return SchedulingOutcome(
                False, state_id, list(path), list(replay_hints),
                observation, off_app_streak,
            )

    logger.warning(
        "scroll audit still incomplete for %s; preserving the incomplete "
        "ledger and continuing visible target exploration", state_id[:8])
    deferred.add(str(state_id))
    host._scroll_audit_deferred_states = deferred
    record_event = getattr(
        getattr(host, "review_debug", None), "record_event", None)
    if callable(record_event):
        record_event(
            "scroll_audit_deferred",
            node=str(state_id),
            scopes=[str(record.get("scope_id") or "") for record in incomplete],
            reason="bounded retry remained incomplete",
        )
    return SchedulingOutcome(
        False, state_id, list(path), list(replay_hints),
        observation, off_app_streak,
    )


def schedule_frontier(host: TraversalRuntimeHost, state_id, observation,
                      path, replay_hints, off_app_streak):
    current_id = state_id
    current_obs = observation
    current_path = path
    current_hints = replay_hints
    def outcome(stop):
        return SchedulingOutcome(
            stop, current_id, list(current_path), list(current_hints),
            current_obs, off_app_streak,
        )

    from .region_observation import (
        observe_next_region, pending_region_ids)
    if (
        pending_region_ids(host, current_id)
        and not available_unvisited_candidates(host, current_id)
    ):
        observe_next_region(host, current_id, current_obs)
        # One Region-local observation is one scheduling stage.  Re-enter the
        # scheduler so newly discovered controls participate in the ordinary
        # Explorer frontier before another Region is opened.
        return outcome(False)

    active = getattr(host, "_active_state_mutation", None)
    if (
        active
        and str(current_id) == str(active.get("source_state") or "")
        and str(getattr(
            host, "_last_live_observation_state_id", "") or "")
        == str(current_id)
    ):
        _clear_mutation_on_verified_baseline_return(
            host,
            str(current_id),
            list(getattr(
                host, "_last_live_observation_elements", None) or []),
            observation_fresh=True,
            record_restore=lambda evidence: (
                _record_restore_on_latest_verified_landing(
                    host, str(current_id), evidence)),
        )
        active = getattr(host, "_active_state_mutation", None)
    source_target = str((active or {}).get("source_state") or "")
    mutation_target = str((active or {}).get("mutated_state") or "")
    if active:
        if mutation_target == str(current_id):
            if _adopt_stateful_restore_landing(host, current_id) is not None:
                return outcome(False)
            nxt = None
        elif str(current_id) != source_target:
            if (
                source_target in getattr(host, "_state_data", {})
                and source_target not in getattr(
                    host, "_route_blocked_targets", set())
            ):
                nxt = source_target
            else:
                nxt = None
        elif (
            mutation_target in getattr(host, "_state_data", {})
            and mutation_target not in getattr(
                host, "_route_blocked_targets", set())
        ):
            nxt = mutation_target
        else:
            nxt = None
    else:
        element_task = active_element_task(host)
        task_target = str((element_task or {}).get("goal_state_id") or "")
        if element_task is not None and task_target == str(current_id):
            finish_element_task(
                host, "deferred",
                "no framework-approved action remained on the goal source",
            )
            element_task = None
            task_target = ""
        if (
            task_target
            and task_target != str(current_id)
            and task_target in getattr(host, "_state_data", {})
            and task_target not in getattr(host, "_route_blocked_targets", set())
        ):
            nxt = task_target
        else:
            nxt = None
        if nxt is None:
            nxt, qwen_stopped = _qwen_frontier_choice(
                host, current_id, current_obs)
            if qwen_stopped:
                return outcome(True)
        if nxt is None:
            # Compatibility for deterministic fixtures or callers without a
            # Qwen route chooser.  The normal live engine always has one.
            nxt = host._nearest_unexplored_node(current_id)
    if nxt is None:
        if host._active_state_mutation:
            logger.error(
                "stateful mutation %s cannot be restored: inverse "
                "control is not reachable",
                host._active_state_mutation.get("mutation_id", "?"))
            host.graph.stop_reason = "state_restore_failed"
            return outcome(True)
        if host._stateful_budget_blocked:
            logger.error(
                "safe stateful frontier remains but its explicit "
                "probe/action budget is exhausted")
            host.graph.stop_reason = "stateful_probe_budget"
            return outcome(True)
        incomplete_scroll = _incomplete_scroll_records(host, current_id)
        if incomplete_scroll:
            logger.error(
                "scroll audit still incomplete for %s", current_id[:8])
            host.graph.stop_reason = "scroll_incomplete"
            return outcome(True)
        retryable_scroll_states = sorted({
            str(state)
            for record in _incomplete_scroll_records(host)
            if int(record.get("observations", 0) or 0) == 1
            for state in (record.get("state_ids") or [])
            if str(state) != current_id
            and str(state) in getattr(host, "_state_data", {})
            and str(state) not in getattr(host, "_route_blocked_targets", set())
        }, key=lambda state: (
            len((host._state_data.get(state) or {}).get("path") or []),
            state,
        ))
        if retryable_scroll_states:
            nxt = retryable_scroll_states[0]
            logger.warning(
                "routing to %s for its incomplete first scroll audit",
                nxt[:8])
        else:
            remaining_scroll = _incomplete_scroll_records(host)
            if remaining_scroll:
                logger.error(
                    "%d scroll audit scope(s) remain incomplete",
                    len(remaining_scroll))
                host.graph.stop_reason = "scroll_incomplete"
                return outcome(True)
            blocked_work = [
                state for state in getattr(host, "_route_blocked_targets", set())
                if state in getattr(host, "_state_data", {})
                and host._unvisited_candidates(state)
            ]
            if blocked_work:
                retryable = [
                    state for state in blocked_work
                    if 0 < int(getattr(
                        host, "_route_target_failure_counts", {}
                    ).get(state, 0)) < MAX_TARGET_ROUTE_FAILURES
                ]
                if retryable:
                    nxt = sorted(retryable, key=lambda state: (
                        len((host._state_data.get(state) or {}).get(
                            "path") or []),
                        state,
                    ))[0]
                    host._route_blocked_targets.discard(nxt)
                    logger.warning(
                        "retrying route to temporarily unavailable target %s "
                        "once before retiring its source-local controls",
                        nxt[:8])
                else:
                    logger.error(
                        "frontier still has %d temporarily route-blocked "
                        "target(s)", len(blocked_work))
                    host.graph.stop_reason = "routing_incomplete"
                    host.review_debug.record_event(
                        "routing_incomplete", targets=sorted(blocked_work),
                        fail_count=host._backtrack_fail_count)
                    return outcome(True)
            else:
                deferred_work = _deferred_explorer_work(host)
                if deferred_work:
                    failure_counts = getattr(
                        host, "_explorer_region_failure_counts", {})
                    retryable = [
                        key for key in deferred_work
                        if int(failure_counts.get(key, 0))
                        < MAX_EXPLORER_REGION_FAILURES
                    ]
                    if retryable:
                        state_key = sorted(retryable, key=lambda key: (
                            len((host._state_data.get(key[0]) or {}).get(
                                "path") or []),
                            key,
                        ))[0]
                        host._explorer_deferred_regions.discard(state_key)
                        nxt = state_key[0]
                        host.review_debug.record_event(
                            "explorer_region_retry",
                            node=nxt,
                            region=state_key[1],
                            failed_rounds=int(
                                failure_counts.get(state_key, 0)),
                        )
                        logger.warning(
                            "retrying deferred Explorer region %s/%s after "
                            "other available frontier work",
                            nxt[:8], state_key[1])
                        if nxt == current_id:
                            return outcome(False)
                    else:
                        logger.error(
                            "%d frontier region(s) remain unresolved after "
                            "bounded Explorer retries",
                            len(deferred_work))
                        host.graph.stop_reason = "explorer_unavailable"
                        host.review_debug.record_event(
                            "explorer_unavailable",
                            regions=[list(key) for key in deferred_work],
                            failed_rounds={
                                f"{key[0]}:{key[1]}":
                                int(failure_counts.get(key, 0))
                                for key in deferred_work
                            },
                        )
                        return outcome(True)
                else:
                    observer_work = _unresolved_observer_work(host)
                    if observer_work:
                        logger.error(
                            "%d control(s) remain pending because transition "
                            "observation stayed uncertain",
                            len(observer_work))
                        host.graph.stop_reason = "observer_unresolved"
                        host.review_debug.record_event(
                            "observer_unresolved",
                            controls=[list(key) for key in observer_work],
                        )
                        return outcome(True)
                    from .region_observation import unresolved_region_ids
                    unresolved_regions = unresolved_region_ids(host)
                    if unresolved_regions:
                        logger.error(
                            "%d Region(s) remain unresolved after bounded "
                            "observation retries", len(unresolved_regions))
                        host.graph.stop_reason = "region_observation_unresolved"
                        host.review_debug.record_event(
                            "region_observation_unresolved",
                            regions=unresolved_regions)
                        return outcome(True)
                    logger.info("BFS frontier empty; traversal complete")
                    host.graph.stop_reason = "frontier_empty"  # clean, fully explored
                    host.review_debug.record_event(
                        "frontier_empty",
                        n_nodes=host.graph.graph.number_of_nodes(),
                        n_actions=host._action_count)
                    return outcome(True)
    host._moves_without_new += 1
    if host._moves_without_new > host.MAX_MOVES_WITHOUT_NEW:
        logger.error(
            "no new node in %d consecutive frontier moves for '%s' — "
            "frontier unproductive (thrash guard); ending cleanly with "
            "%d states collected",
            host._moves_without_new, host.app_name,
            host.graph.graph.number_of_nodes())
        host.graph.stop_reason = "thrash_guard"  # frontier unproductive
        host.graph.save(host.graph_save_path)
        return outcome(True)
    try:
        _tc = host._unvisited_candidates(nxt)
        logger.info("[目标] 下一步: 前往 %s 点「%s」(账本还剩 %d 个候选)",
                    nxt[:8], _tc[0].name if _tc else "?", len(_tc))
    except Exception:
        pass
    target_path = host._state_data[nxt]["path"]
    target_hints = host._state_data[nxt].get("replay_hints") or None
    route_result = host.router.route_to(current_obs, current_id, nxt)
    if hasattr(route_result, "arrived"):
        ok = route_result.arrived
        obs = route_result.observation
        route_status = route_result.status
        failure_kind = route_result.failure_kind
        landed_hint = route_result.landed_id
    else:
        ok, obs = route_result
        route_status = "arrived" if ok else "retryable"
        failure_kind = "legacy_route_failure"
        landed_hint = None
    if (
        not ok
        and obs is not None
        and landed_hint not in getattr(host, "_state_data", {})
    ):
        recovered = recover_route_observation(host, obs)
        if recovered.on_app and recovered.observation is not None:
            recovered_id, _path, _hints, _is_new = \
                host._register_landed(recovered.observation)
            if recovered_id is not None:
                obs = recovered.observation
                landed_hint = recovered_id
                route_result = SimpleNamespace(
                    attempts_used=getattr(route_result, "attempts_used", 0),
                    action_dispatched=getattr(
                        route_result, "action_dispatched", False),
                    failure_kind=failure_kind,
                    landed_id=recovered_id,
                )
                logger.info(
                    "route failure recovered actual known landing %s",
                    recovered_id)
    if (
        not ok
        and obs is not None
        and landed_hint in getattr(host, "_state_data", {})
        and _stable_control_binding(host, nxt, str(landed_hint)) is not None
    ):
        ok = True
        route_status = "arrived_equivalent_region"
        failure_kind = ""
        host.review_debug.record_event(
            "route_target_rebound",
            target=nxt,
            landed=str(landed_hint),
            basis="stable_region_and_control",
        )
        logger.info(
            "route target %s rebound to live state %s because the same "
            "mapped Region exposes the target control",
            nxt[:8], str(landed_hint)[:8],
        )
    if (
        not ok
        and obs is not None
        and landed_hint in getattr(host, "_state_data", {})
        and nxt == mutation_target
        and _adopt_stateful_restore_landing(host, str(landed_hint)) is not None
    ):
        landed = host._state_data[str(landed_hint)]
        current_id = str(landed_hint)
        current_path = list(landed.get("path", []))
        current_hints = list(landed.get("replay_hints", []) or [])
        current_obs = obs
        host.graph.save(host.graph_save_path)
        return outcome(False)
    if not ok or obs is None:
        if host.graph.stop_reason == "state_restore_failed":
            logger.error(
                "router recovery landed on an unknown page; stopping "
                "without changing the persisted nodes or paths")
            return outcome(True)
        host._backtrack_fail_count += 1
        host._route_blocked_targets.add(nxt)
        retired = _retire_currently_unreachable_target(
            host, nxt, route_result)
        target_fail_count = int(getattr(
            host, "_route_target_failure_counts", {}
        ).get(nxt, 0))
        host._route_failures[(current_id, nxt)] = {
            "status": route_status,
            "failure_kind": failure_kind,
            "landed_id": landed_hint,
            "count": target_fail_count,
            "total_count": host._backtrack_fail_count,
        }
        if retired:
            landed = host._state_data[landed_hint]
            current_id = landed_hint
            current_path = list(landed.get("path", []))
            current_hints = list(landed.get("replay_hints", []) or [])
            current_obs = obs
            host.graph.save(host.graph_save_path)
            return outcome(False)
        host.review_debug.record_event(
            "route_target_cooled_down", source=current_id, target=nxt,
            status=route_status, failure_kind=failure_kind,
            landed=landed_hint, fail_count=target_fail_count)
        logger.warning(
            "route to %s failed (%d/%d, %s:%s); cooling it down for "
            "this run without marking it unreachable",
            nxt, target_fail_count, MAX_TARGET_ROUTE_FAILURES,
            route_status, failure_kind)
        if (
            host._active_state_mutation
            and nxt in {
                str(host._active_state_mutation.get("source_state") or ""),
                str(host._active_state_mutation.get("mutated_state") or ""),
            }
        ):
            logger.error("cannot route through stateful restoration node %s; "
                         "stopping before collecting polluted state",
                         str(nxt)[:8])
            host.graph.stop_reason = "state_restore_failed"
            host.graph.save(host.graph_save_path)
            return outcome(True)
        if landed_hint in host._state_data:
            landed = host._state_data[landed_hint]
            current_id = landed_hint
            current_path = list(landed.get("path", []))
            current_hints = list(landed.get("replay_hints", []) or [])
            current_obs = obs
        host.graph.save(host.graph_save_path)
        return outcome(False)
    recovered = recover_route_observation(host, obs)
    obs, relaunched, on_app = (
        recovered.observation, recovered.relaunched, recovered.on_app)
    if not on_app:
        off_app_streak += 1
        current_obs = obs
        return outcome(False)
    off_app_streak = 0
    if relaunched:
        current_id, current_path, current_hints, _is_new = \
            host._register_landed(obs)
        if current_id is None:
            return outcome(True)
        current_obs = obs
        return outcome(False)
    # Router already identified this live landing. Pin that stable identity
    # while refreshing current evidence; unconstrained registration here can
    # split the same old page into a duplicate node.
    confirmed_id = str(landed_hint or nxt)
    landed_id, landed_path, landed_hints = _refresh_verified_return_landing(
        host, obs, confirmed_id)
    adopted_inverse = (
        _adopt_stateful_restore_landing(host, str(landed_id))
        if nxt == mutation_target else None
    )
    equivalent_frontier = (
        landed_id != nxt
        and _stable_control_binding(host, nxt, str(landed_id)) is not None
    )
    if landed_id != nxt and not equivalent_frontier:
        if adopted_inverse is not None:
            current_id = landed_id
            current_path = list(landed_path)
            current_hints = list(landed_hints)
            current_obs = obs
            host.graph.save(host.graph_save_path)
            return outcome(False)
        host._backtrack_fail_count += 1
        observed_route_result = SimpleNamespace(
            attempts_used=getattr(route_result, "attempts_used", 0),
            action_dispatched=getattr(route_result, "action_dispatched", False),
            failure_kind="identity_mismatch",
            landed_id=landed_id,
        )
        retired = _retire_currently_unreachable_target(
            host, nxt, observed_route_result)
        target_fail_count = int(getattr(
            host, "_route_target_failure_counts", {}
        ).get(nxt, 0))
        host.review_debug.record_event(
            "backtrack_false_arrival", target=nxt, landed=landed_id,
            fail_count=target_fail_count)
        host._route_blocked_targets.add(nxt)
        host._route_failures[(current_id, nxt)] = {
            "status": "false_arrival", "failure_kind": "identity_mismatch",
            "landed_id": landed_id, "count": target_fail_count,
            "total_count": host._backtrack_fail_count,
        }
        if retired:
            landed = host._state_data.get(landed_id)
            current_id = landed_id
            current_path = list(landed.get("path", [])) if landed else []
            current_hints = list(
                landed.get("replay_hints", []) or []) if landed else []
            current_obs = obs
            host.graph.save(host.graph_save_path)
            return outcome(False)
        logger.warning(
            "route to %s reported success but landed on %s; cooling %s "
            "down for this run without deleting it from the frontier (%d/%d)",
            nxt, landed_id, nxt, target_fail_count,
            MAX_TARGET_ROUTE_FAILURES)
        landed = host._state_data.get(landed_id)
        current_id = landed_id
        current_path = list(landed.get("path", [])) if landed else []
        current_hints = list(landed.get("replay_hints", []) or []) if landed else []
        current_obs = obs
        host.graph.save(host.graph_save_path)
        return outcome(False)
    if equivalent_frontier:
        host.review_debug.record_event(
            "route_target_rebound",
            target=nxt,
            landed=landed_id,
            basis="stable_region_and_control",
        )
        logger.info(
            "accepted live state %s for historical target %s because its "
            "mapped Region exposes the same target control",
            landed_id[:8], nxt[:8],
        )
    host._route_blocked_targets.discard(nxt)
    getattr(host, "_route_target_failure_counts", {}).pop(nxt, None)
    route_source_id = current_id
    current_id = landed_id
    current_path = list(landed_path)
    current_hints = list(landed_hints or [])
    current_obs = obs
    record_element_task_route(
        host, str(route_source_id), str(current_id), str(route_status))
    return outcome(False)


@dataclass
class CandidatePlanOutcome:
    directive: StageDirective
    candidate: Optional[CandidateContext] = None


def _region_key(element) -> str:
    return (str(getattr(element, "region_id", "") or "")
            or f"role:{str(getattr(element, 'region', '') or 'surface')}")


def _element_attempts(host, state_id: str, element) -> List[Dict[str, Any]]:
    """Read action history by framework-owned source and element identity."""
    element_id = str(getattr(element, "id", ""))
    rows = []
    for edge in getattr(getattr(host, "graph", None), "action_edges", []) or []:
        if str(edge.get("source") or "") != str(state_id):
            continue
        if str(edge.get("element_id") or "") != element_id:
            continue
        action = edge.get("action") if isinstance(edge.get("action"), dict) else {}
        for attempt in edge.get("attempts") or []:
            target = str(attempt.get("target") or edge.get("target") or "")
            evidence = attempt.get("evidence") \
                if isinstance(attempt.get("evidence"), dict) else {}
            observer = evidence.get("transition_observer") \
                if isinstance(evidence.get("transition_observer"), dict) else {}
            rows.append({
                "action": dict(action),
                "outcome": str(attempt.get("outcome") or ""),
                "detail": str(attempt.get("detail") or ""),
                "actual_result": str(
                    attempt.get("target_page_name")
                    or ((host._state_data.get(target) or {}).get("page_name")
                        if target else "")
                    or ""),
                "observed_outcome": str(
                    observer.get("observed_outcome") or ""),
                "relation_to_target": str(
                    observer.get("relation_to_target") or ""),
                "verified": bool(
                    attempt.get("committed") is True
                    and attempt.get("landing_verified") is True),
            })
    return rows


def _element_failures(host, state_id: str, element) -> List[Dict[str, Any]]:
    """Expose bounded framework failures as optional Explorer context."""
    key = (
        str(state_id),
        str(getattr(element, "uid", "") or getattr(element, "name", "") or ""),
    )
    history = getattr(host, "_click_failure_history", {}) or {}
    reason_counts = history.get(key) or {}
    latest_feedback = str(
        (getattr(host, "_targeting_corrections", {}) or {}).get(key, "")
        or "")
    return [
        {
            "failure_kind": str(reason),
            "attempts": int(count),
            **({"latest_feedback": latest_feedback}
               if latest_feedback else {}),
        }
        for reason, count in sorted(reason_counts.items())
        if str(reason) and int(count) > 0
    ]


def _explorer_entry_record(host, state_id: str, element, *,
                           entry_id: str = "") -> Dict[str, Any]:
    """Describe one stable target using only recorded exploration facts."""
    state_data = host._state_data.get(str(state_id)) or {}
    element_region_id = str(getattr(element, "region_id", "") or "")
    element_region_role = str(getattr(element, "region", "") or "")
    region_block = next((
        block for block in state_data.get("semantic_blocks") or []
        if (
            element_region_id
            and str(block.get("region_id") or "") == element_region_id
        ) or (
            not element_region_id
            and element_region_role
            and str(block.get("role") or "") == element_region_role
        )
    ), {})
    attempts = [{
        key: value for key, value in attempt.items() if key != "action"
    } for attempt in _element_attempts(host, state_id, element)[-3:]]
    problems = _element_failures(host, state_id, element)
    raw_status = str(
        getattr(element, "exploration_status", "") or "").strip()
    if raw_status in {"complete", "covered"}:
        status = "explored"
    elif raw_status == "semantic_only":
        status = "observed_without_action"
    elif raw_status == "terminal":
        status = "not_selectable"
    elif attempts or problems:
        status = "available_with_previous_problem"
    else:
        status = "untried"
    detail = str(
        getattr(element, "exploration_reason", "")
        or getattr(element, "abnormal_reason", "")
        or getattr(element, "blocked_reason", "")
        or ""
    )
    record = {
        "target": str(getattr(element, "name", "") or ""),
        "region_name": str(
            region_block.get("role") or element_region_role),
        "exploration_status": status,
        "status_detail": detail,
        "previous_results": attempts,
        "framework_feedback": problems,
    }
    if entry_id:
        record["entry_id"] = entry_id
    return record


def _apply_verified_stable_control_coverage(
        host: TraversalRuntimeHost, state_id: str) -> bool:
    """Reuse an exact non-stateful control result after VLM Region mapping."""
    pending = list(host._unvisited_candidates(str(state_id)))
    if not pending:
        return False
    changed = False
    for element in pending:
        region_id = str(getattr(element, "region_id", "") or "")
        name = _normalized_control_name(element)
        if (
            not region_id
            or not name
            or bool(getattr(element, "stateful", False))
            or bool(getattr(element, "requires_permission", False))
            or bool(getattr(element, "is_dangerous", lambda: False)())
        ):
            continue
        representative = None
        representative_state = ""
        for source_state_id, source_data in getattr(
                host, "_state_data", {}).items():
            if str(source_state_id) == str(state_id):
                continue
            source_matches = [
                candidate for candidate in source_data.get("elements") or []
                if (
                    str(getattr(candidate, "region_id", "") or "")
                    == region_id
                    and _normalized_control_name(candidate) == name
                    and not bool(getattr(candidate, "stateful", False))
                )
            ]
            if len(source_matches) != 1:
                continue
            candidate = source_matches[0]
            if any(
                    attempt.get("verified")
                    and str((attempt.get("action") or {}).get(
                        "action_type") or "").casefold() == "click"
                    for attempt in _element_attempts(
                        host, str(source_state_id), candidate)
            ):
                representative = candidate
                representative_state = str(source_state_id)
            if representative is not None:
                break
        if representative is None:
            continue
        _complete_element(
            element,
            "covered",
            covered_by=str(getattr(representative, "id", "")),
            covered_by_state=representative_state,
            reason=(
                "the same semantic control in this VLM-mapped stable Region "
                "already has a landing-verified CLICK"),
        )
        changed = True
    return changed


def _apply_verified_reverse_control_coverage(
        host: TraversalRuntimeHost, state_id: str) -> bool:
    """Close a control discovered after its reverse probe was verified."""
    pending = list(host._unvisited_candidates(str(state_id)))
    if not pending:
        return False
    changed = False
    for edge in getattr(getattr(host, "graph", None), "action_edges", []) or []:
        if str(edge.get("source") or "") != str(state_id):
            continue
        action = edge.get("action") if isinstance(
            edge.get("action"), dict) else {}
        if str(action.get("action_type") or "").casefold() != "click":
            continue
        verified_reverse = any(
            attempt.get("committed") is True
            and attempt.get("landing_verified") is True
            and isinstance((attempt.get("evidence") or {}).get(
                "reverse_probe"), dict)
            for attempt in edge.get("attempts") or []
        )
        if not verified_reverse:
            continue
        label = " ".join(
            str(edge.get("element_label") or "").casefold().split())
        matches = [
            element for element in pending
            if _normalized_control_name(element) == label
        ]
        if label and len(matches) == 1:
            _complete_element(
                matches[0], "complete",
                reason="landing-verified reverse action",
            )
            pending.remove(matches[0])
            changed = True
    return changed


def _complete_element(
        element, status: str, *, covered_by: str = "",
        covered_by_state: str = "", reason: str = "") -> None:
    element.exploration_status = status
    element.covered_by = str(covered_by or "")
    element.covered_by_state = str(covered_by_state or "")
    element.exploration_reason = str(reason or "")
    element.visited = status in {
        "complete", "covered", "semantic_only", "terminal",
    }


def _apply_verified_group_coverage(
        host: TraversalRuntimeHost, state_id: str) -> bool:
    """Fold non-stateful data alternatives after one local verified click.

    Perception's non-empty ``group`` means that controls are instances of the
    same function/detail template.  Keep every occurrence in the inventory, but
    do not route back and execute every instance once this State already has a
    source-local, landing-verified representative.  Stateful groups remain
    explicit because their alternatives can encode distinct persisted values.
    """
    elements = list(
        (getattr(host, "_state_data", {}).get(str(state_id)) or {}).get(
            "elements") or [])
    grouped: Dict[tuple[str, str], List[Any]] = {}
    for element in elements:
        group = " ".join(
            str(getattr(element, "group", "") or "").casefold().split())
        region_id = str(getattr(element, "region_id", "") or "")
        if (
            group
            and region_id
            and getattr(element, "interactive", None) is not False
        ):
            grouped.setdefault((region_id, group), []).append(element)

    changed = False
    for (_region_id, group), members in grouped.items():
        if len(members) < 2 or any(
            any((
                bool(getattr(member, "stateful", False)),
                bool(getattr(member, "requires_permission", False)),
                getattr(member, "enabled", None) is False,
                bool(getattr(member, "blocked_reason", "")),
                bool(getattr(member, "is_dangerous", lambda: False)()),
            ))
            for member in members
        ):
            continue
        representative = next((
            member for member in members
            if any(
                attempt.get("verified")
                and str((attempt.get("action") or {}).get(
                    "action_type") or "").casefold() == "click"
                for attempt in _element_attempts(host, state_id, member))
        ), None)
        if representative is None:
            continue
        if str(getattr(
                representative, "exploration_status", "") or "") not in {
                    "complete", "covered",
                }:
            _complete_element(
                representative,
                "complete",
                reason=(
                    "source-local landing-verified CLICK exhausted the "
                    "representative action space"),
            )
            changed = True
        for member in members:
            if member is representative:
                continue
            if str(getattr(member, "exploration_status", "") or "") in {
                    "complete", "covered", "semantic_only", "terminal",
                }:
                continue
            _complete_element(
                member,
                "covered",
                covered_by=str(getattr(representative, "id", "")),
                covered_by_state=str(state_id),
                reason=(
                    f"the verified representative establishes non-stateful "
                    f"group '{group}' as one repeated function template"),
            )
            changed = True
    return changed


def plan_candidate(host: TraversalRuntimeHost, cursor: RunCursor, candidates):
    """Build the next executable candidate without touching the environment."""
    region_candidates = list(candidates)
    candidate_region_keys = list(dict.fromkeys(
        _region_key(element) for element in region_candidates))
    active_region_key = candidate_region_keys[0]
    platform = "android" if getattr(host, "_is_touch", False) else "desktop"
    active_mutation = getattr(host, "_active_state_mutation", None)
    if active_mutation:
        inverse = next((
            element for element in region_candidates
            if _active_restore_candidate(host, active_mutation, element)
        ), None)
        if inverse is not None:
            action = {"action_type": "CLICK", "parameters": {}}
            mutation_id = str(active_mutation.get("mutation_id") or "")
            restore_source_value = str(
                active_mutation.get("after_value")
                or inverse.state_value
                or "unknown"
            ).strip().lower()
            restore_target_value = str(
                active_mutation.get("before_value")
                or host._stateful_target_value(inverse)
                or "unknown"
            ).strip().lower()
            evidence = {
                "mutation_id": mutation_id, "purpose": "restore",
                "stateful": True, "state_key": inverse.state_key,
                "before_value": restore_source_value,
                "expected_after_value": restore_target_value,
                "effect_scope": inverse.effect_scope,
                "reversible": inverse.reversible, "risk": inverse.risk,
                "probe_candidate_key": str(
                    active_mutation.get("probe_candidate_key") or ""),
                "restore_candidate_key": str(
                    active_mutation.get("restore_candidate_key") or ""),
                "restore_before_value": str(
                    active_mutation.get("restore_before_value") or ""),
            }
            host.review_debug.record_event(
                "stateful_restore_select", node=cursor.state_id,
                step=host._action_count + 1, element=inverse.name,
                mutation_id=mutation_id)
            return CandidatePlanOutcome(
                StageDirective.EXECUTION,
                CandidateContext(
                    element=inverse,
                    decision_reason="restore the active stateful transaction",
                    is_seed=False, is_stateful=True, is_restore=True,
                    mutation_id=mutation_id, stateful_evidence=evidence,
                    active_mutation=active_mutation,
                    pre_click_id=(
                        cursor.state_id
                        if bool(getattr(
                            getattr(host, "perception", None),
                            "use_semantic_inventory", False))
                        else host._frame_state_id(
                            cursor.observation, candidates)),
                    action=action, targeted=True,
                    exploration_task_id=str((
                        active_element_task(host) or {}).get("task_id") or ""),
                ),
            )
    # The current Explorer contract exposes CLICK only.  A source-local,
    # landing-verified CLICK therefore exhausts this button's complete action
    # space and must not be sent back to the model for another decision.
    completed_from_graph = False
    for element in region_candidates:
        if bool(getattr(element, "_pending_restore_execution", False)):
            continue
        attempts = _element_attempts(host, cursor.state_id, element)
        if any(
                attempt.get("verified")
                and str((attempt.get("action") or {}).get(
                    "action_type") or "").casefold() == "click"
                for attempt in attempts):
            _complete_element(
                element, "complete",
                reason="source-local landing-verified CLICK exhausted the action space")
            completed_from_graph = True
    if completed_from_graph:
        persist_status = getattr(host, "_persist_exploration_state", None)
        maybe_save = getattr(host, "_maybe_save", None)
        if callable(persist_status):
            persist_status(cursor.state_id)
        elif callable(maybe_save):
            maybe_save()
    region_candidates = [
        element for element in region_candidates
        if str(getattr(element, "exploration_status", "") or "")
        not in {"complete", "covered", "semantic_only", "terminal"}
    ]
    if not region_candidates:
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    restoration_return = next((
        element for element in region_candidates
        if bool(getattr(element, "_pending_restore_execution", False))
    ), None)
    if restoration_return is not None:
        action, action_error = normalize_native_action(
            {"action_type": "click"}, platform=platform)
        if action_error or action is None:
            host.graph.stop_reason = "state_restore_failed"
            return CandidatePlanOutcome(StageDirective.STOP)
        host.review_debug.record_event(
            "stateful_restore_return_select", node=cursor.state_id,
            step=host._action_count + 1, element=restoration_return.name)
        return CandidatePlanOutcome(
            StageDirective.EXECUTION,
            CandidateContext(
                element=restoration_return,
                decision_reason=(
                    "execute the verified return required to restore the "
                    "active stateful transaction"),
                is_seed=False, is_stateful=False, is_restore=False,
                mutation_id="", stateful_evidence={},
                active_mutation=active_mutation,
                pre_click_id=(
                    cursor.state_id
                    if bool(getattr(
                        getattr(host, "perception", None),
                        "use_semantic_inventory", False))
                    else host._frame_state_id(
                        cursor.observation, candidates)),
                action=action, targeted=True,
                exploration_task_id=str((
                    active_element_task(host) or {}).get("task_id") or ""),
            ),
        )
    pending_ids = {
        id(element): f"e{index}"
        for index, element in enumerate(region_candidates)
    }
    pending_buttons = []
    state_data = host._state_data.get(cursor.state_id) or {}
    for element in region_candidates:
        choice_id = pending_ids.get(id(element), "")
        if choice_id:
            pending_buttons.append(_explorer_entry_record(
                host, cursor.state_id, element, entry_id=choice_id))
    pending_object_ids = {id(element) for element in region_candidates}
    for element in state_data.get("elements") or []:
        if id(element) in pending_object_ids:
            continue
        status = str(getattr(element, "exploration_status", "") or "")
        if status not in {"complete", "covered", "semantic_only", "terminal"}:
            continue
        pending_buttons.append(_explorer_entry_record(
            host, cursor.state_id, element))
    by_choice = {
        pending_ids[id(element)]: element for element in region_candidates
    }
    explorer = getattr(host, "explorer", None)
    maybe_save = getattr(host, "_maybe_save", None)
    unresolved = [
        candidate for candidate in region_candidates
        if str(getattr(candidate, "exploration_status", "") or "")
        not in {"complete", "covered", "semantic_only", "terminal"}
    ]
    if not unresolved:
        for region_key in candidate_region_keys:
            failure_key = (str(cursor.state_id), region_key)
            getattr(host, "_explorer_deferred_regions", set()).discard(
                failure_key)
            getattr(host, "_explorer_region_failure_counts", {}).pop(
                failure_key, None)
        host.review_debug.record_agent(
            "explorer", node=cursor.state_id, step=host._action_count + 1,
            verdict="DONE", reason="framework resolved the current region")
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    task = active_element_task(host)
    if (
        task is not None
        and task_goal_resolved(task)
        and not task_goal_action_verified(task)
    ):
        finish_resolved_goal(host, task)
        task = None
    if task is None:
        decision = {}
        if explorer is not None:
            decision = explorer.choose(
                cursor.observation.get("screenshot"),
                {
                    "application_name": str(
                        getattr(host, "app_name", "") or ""),
                    "current_interface": str(
                        state_data.get("page_name") or ""),
                    "function_entries": pending_buttons,
                },
                platform=platform,
            )
        next_action = decision.get("next_action")
        goal_choice_id = str((next_action or {}).get("choice_id") or "") \
            if isinstance(next_action, dict) else ""
        goal_element = by_choice.get(goal_choice_id)
        if goal_element is None:
            reason = str(getattr(explorer, "last_reason", "") or
                         "Explorer did not select an exploration goal")
            host.review_debug.record_agent(
                "explorer", node=cursor.state_id,
                step=host._action_count + 1, verdict="ERROR",
                reason=reason[:200], target_records=pending_buttons,
                prompts=list(getattr(explorer, "last_prompts", []) or []),
                backend_runs=list(getattr(
                    explorer, "last_backend_runs", []) or []),
                raw_responses=list(getattr(
                    explorer, "last_raw_responses", []) or []))
            deferred = getattr(host, "_explorer_deferred_regions", set())
            counts = getattr(host, "_explorer_region_failure_counts", {})
            for region_key in candidate_region_keys:
                key = (str(cursor.state_id), region_key)
                counts[key] = int(counts.get(key, 0)) + 1
                deferred.add(key)
            host._explorer_deferred_regions = deferred
            host._explorer_region_failure_counts = counts
            host.review_debug.record_event(
                "explorer_state_deferred",
                node=cursor.state_id,
                regions=candidate_region_keys,
                failed_rounds={
                    key[1]: counts[key]
                    for key in deferred if key[0] == str(cursor.state_id)
                },
                reason=reason[:200],
            )
            if callable(maybe_save):
                maybe_save()
            return CandidatePlanOutcome(StageDirective.CONTINUE)
        host.review_debug.record_agent(
            "explorer", node=cursor.state_id,
            step=host._action_count + 1,
            verdict=str(getattr(goal_element, "name", "") or ""),
            reason=str((next_action or {}).get("reason") or "")[:200],
            selected_entry_id=goal_choice_id,
            target_records=pending_buttons,
            prompts=list(getattr(explorer, "last_prompts", []) or []),
            backend_runs=list(getattr(
                explorer, "last_backend_runs", []) or []),
            raw_responses=list(getattr(
                explorer, "last_raw_responses", []) or []),
        )
        task = start_element_task(host, cursor.state_id, goal_element)
        task["goal_reason"] = str(
            (next_action or {}).get("reason") or "")

    route_guidance = task_route_guidance(host, cursor.state_id, task)
    page_graph = compact_page_graph(
        host, cursor.state_id, task, route_guidance)
    region_directory = current_region_directory(host, cursor.state_id)
    progress_facts = task_progress_facts(host, task)
    guard_signature = str(progress_facts.get("guard_signature") or "")
    if guard_signature:
        warned_signature = str(task.get("loop_warning_signature") or "")
        warned_action_count = int(
            task.get("loop_warning_action_count", -1) or -1)
        if (
            warned_signature == guard_signature
            and int(task.get("actions_used", 0)) > warned_action_count
        ):
            goal = task.get("goal_element")
            record_failure = getattr(host, "_record_click_failure", None)
            if goal is not None and callable(record_failure):
                record_failure(
                    str(task.get("goal_state_id") or ""), goal,
                    "element_task_loop_unresolved")
            finish_element_task(
                host, "deferred",
                "model continued a framework-reported no-progress loop",
            )
            if callable(maybe_save):
                maybe_save()
            return CandidatePlanOutcome(StageDirective.CONTINUE)
        task["loop_warning_signature"] = guard_signature
        task["loop_warning_action_count"] = int(task.get("actions_used", 0))
    element_decision = {}
    explore_target = getattr(explorer, "explore_target", None)
    if callable(explore_target):
        element_decision = explore_target(
            cursor.observation.get("screenshot"),
            {
                "application_name": str(
                    getattr(host, "app_name", "") or ""),
                "current_interface": str(
                    state_data.get("page_name") or ""),
                "goal": {
                    "target": str(task.get("goal_target") or ""),
                    "region_name": str(task.get("goal_region") or ""),
                    "source_page": str((host._state_data.get(
                        str(task.get("goal_state_id") or "")) or {}).get(
                            "page_name") or ""),
                },
                "route_guidance": route_guidance,
                "page_graph": page_graph,
                "task_memory": task_memory_for_prompt(task),
                "progress_facts": progress_facts,
                "current_regions": {
                    "regions": list(region_directory.get("regions") or []),
                },
                "tool_catalog": tool_catalog(),
            },
        )
    element_reason = str(
        (element_decision or {}).get("reason")
        or getattr(explorer, "last_reason", "")
        or "element task agent unavailable")
    element_verdict = str(
        (element_decision or {}).get("decision") or "fallback")
    next_direct_action = dict(
        (element_decision or {}).get("next_action") or {})
    if element_verdict == "defer":
        host.review_debug.record_agent(
            "element_explorer", node=cursor.state_id,
            step=host._action_count + 1, verdict="defer",
            reason=element_reason[:200],
            goal=str(task.get("goal_target") or ""),
            route_guidance=route_guidance,
            page_graph=page_graph,
            task_history=list(task.get("history") or []),
            current_page=(element_decision or {}).get("current_page"),
            discovered_controls=(
                element_decision or {}).get("discovered_controls"),
            prompts=list(getattr(explorer, "last_prompts", []) or []),
            backend_runs=list(getattr(
                explorer, "last_backend_runs", []) or []),
            raw_responses=list(getattr(
                explorer, "last_raw_responses", []) or []),
        )
        if task_goal_action_verified(task):
            finish_element_task(
                host, "complete",
                "model deferred after a framework-verified goal action",
            )
            if callable(maybe_save):
                maybe_save()
            return CandidatePlanOutcome(StageDirective.CONTINUE)
        goal = task.get("goal_element")
        record_failure = getattr(host, "_record_click_failure", None)
        if goal is not None and callable(record_failure):
            record_failure(
                str(task.get("goal_state_id") or ""), goal,
                "element_task_deferred")
        finish_element_task(host, "deferred", element_reason)
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    if element_verdict == "finish":
        if task_goal_action_verified(task) or task_goal_resolved(task):
            finish_element_task(
                host, "complete", "model finished a verified goal task")
        else:
            finish_element_task(
                host, "invalid", "model finished before a verified goal action")
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    if element_verdict == "tool" and next_direct_action:
        result = execute_agent_tool(
            ToolContext(
                host=host,
                state_id=str(cursor.state_id),
                observation=cursor.observation,
                page_graph=page_graph,
                region_directory=region_directory,
                task=task,
            ),
            next_direct_action,
        )
        tool_result = result.to_dict()
        tool_error = (
            result.message
            if result.status in {"error", "missing_evidence"}
            else ""
        )
        logger.info(
            "element agent tool %s -> %s (observation_changed=%s, "
            "ledger_changed=%s)",
            result.tool, result.status, result.observation_changed,
            result.ledger_changed,
        )
        record_element_task_tool(
            host, next_direct_action, tool_result, tool_error,
            page_name=str(state_data.get("page_name") or ""),
        )
        host.review_debug.record_agent(
            "element_explorer", node=cursor.state_id,
            step=host._action_count + 1,
            verdict=f"tool_{result.status}",
            reason=str(tool_error or element_reason)[:200],
            goal=str(task.get("goal_target") or ""),
            tool_call=next_direct_action,
            tool_result=tool_result,
            current_page=(element_decision or {}).get("current_page"),
            prompts=list(getattr(explorer, "last_prompts", []) or []),
            backend_runs=list(getattr(
                explorer, "last_backend_runs", []) or []),
            raw_responses=list(getattr(
                explorer, "last_raw_responses", []) or []),
        )
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    if element_verdict != "act" or not next_direct_action:
        goal = task.get("goal_element")
        record_failure = getattr(host, "_record_click_failure", None)
        if goal is not None and callable(record_failure):
            record_failure(
                str(task.get("goal_state_id") or ""), goal,
                "element_task_deferred")
        finish_element_task(host, "invalid", element_reason)
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    if str(next_direct_action.get("safety") or "") != "safe":
        finish_element_task(
            host, "deferred",
            f"model safety={next_direct_action.get('safety')}: {element_reason}")
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    task["agentic"] = True
    direct_action_type = str(
        next_direct_action.get("type") or "").strip().upper()
    action_role = str(
        next_direct_action.get("action_role") or "").strip().casefold()
    requested_target = " ".join(str(
        next_direct_action.get("target") or "").casefold().split())
    goal_target = " ".join(str(
        task.get("goal_target") or "").casefold().split())
    current_page_id = str(state_data.get("page_id") or cursor.state_id)
    goal_state = host._state_data.get(str(task.get("goal_state_id") or "")) or {}
    goal_page_id = str(
        goal_state.get("page_id") or task.get("goal_state_id") or "")
    goal_action = (
        action_role == "goal" and current_page_id == goal_page_id
        and requested_target == goal_target
    )
    if goal_action and task_goal_action_verified(task):
        finish_element_task(
            host, "complete",
            "model repeated an already verified goal instead of returning",
        )
        if callable(maybe_save):
            maybe_save()
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    elem = (
        task.get("goal_element")
        if goal_action else
        _direct_task_element(
            str(next_direct_action.get("target") or direct_action_type),
            direct_action_type,
        )
    )
    requested_action, action_error = _direct_task_action(
        platform, cursor.observation.get("screenshot"), next_direct_action)
    if action_error or requested_action is None:
        finish_element_task(host, "invalid", str(action_error))
        return CandidatePlanOutcome(StageDirective.CONTINUE)
    host.review_debug.record_agent(
        "element_explorer", node=cursor.state_id,
        step=host._action_count + 1,
        verdict=direct_action_type,
        reason=element_reason[:200],
        goal=str(task.get("goal_target") or ""),
        route_guidance=route_guidance,
        page_graph=page_graph,
        task_history=list(task.get("history") or []),
        current_page=(element_decision or {}).get("current_page"),
        discovered_controls=(
            element_decision or {}).get("discovered_controls"),
        next_action=next_direct_action,
        prompts=list(getattr(explorer, "last_prompts", []) or []),
        backend_runs=list(getattr(
            explorer, "last_backend_runs", []) or []),
        raw_responses=list(getattr(
            explorer, "last_raw_responses", []) or []),
    )
    action = requested_action
    action_type = str(action.get("action_type") or "")
    targeted = action_is_targeted(platform, action_type)
    decision_reason = (
        f"Explore {task.get('goal_target')}: {element_reason}")
    active_region_key = _region_key(elem)
    failure_key = (str(cursor.state_id), active_region_key)
    getattr(host, "_explorer_deferred_regions", set()).discard(failure_key)
    getattr(host, "_explorer_region_failure_counts", {}).pop(
        failure_key, None)
    host.review_debug.record_event(
        "navigation_frontier_select", node=cursor.state_id,
        step=host._action_count + 1, element=elem.name,
        remaining=len(region_candidates),
    )
    is_seed = False
    is_stateful = targeted and elem.is_safe_stateful_surface()
    active_mutation = getattr(host, "_active_state_mutation", None)
    is_restore = bool(
        is_stateful and active_mutation
        and _active_restore_candidate(host, active_mutation, elem)
    )
    mutation_id = ""
    evidence = {}
    if is_stateful:
        baseline_elements = list(
            (host._state_data.get(cursor.state_id) or {}).get(
                "elements") or [])
        probe_candidate_key = host._stateful_candidate_key(elem)
        wanted_state_key = normalize_state_key(elem.state_key)
        selected_peer = next((
            candidate for candidate in baseline_elements
            if candidate is not elem
            and bool(getattr(candidate, "selected", False))
            and normalize_state_key(getattr(candidate, "state_key", ""))
            == wanted_state_key
            and host._stateful_candidate_key(candidate) != probe_candidate_key
        ), None)
        restore_candidate_key = (
            host._stateful_candidate_key(selected_peer)
            if selected_peer is not None else probe_candidate_key
        )
        restore_before_value = str(
            getattr(
                selected_peer if selected_peer is not None else elem,
                "state_value",
                "",
            ) or "unknown"
        ).strip().lower()
        mutation_id = (
            str(active_mutation.get("mutation_id") or "")
            if is_restore else
            f"{host.app_name}:{host._action_count + 1}:"
            f"{elem.state_key}:{elem.state_value}"
        )
        evidence = {
            "mutation_id": mutation_id,
            "purpose": "restore" if is_restore else "probe",
            "stateful": True, "state_key": elem.state_key,
            "before_value": elem.state_value,
            "expected_after_value": host._stateful_target_value(elem),
            "effect_scope": elem.effect_scope,
            "reversible": elem.reversible, "risk": elem.risk,
            "probe_candidate_key": probe_candidate_key,
            "restore_candidate_key": restore_candidate_key,
            "restore_before_value": restore_before_value,
            "baseline_candidates": [
                host._stateful_candidate_key(candidate)
                for candidate in baseline_elements
                if bool(getattr(candidate, "interactive", True))
            ],
        }
    if is_stateful and not is_restore:
        guard = getattr(host, "stateful_risk_guard", None)
        guard_result = (
            guard.assess(cursor.observation.get("screenshot"), elem)
            if guard is not None else
            {"allow": False, "risk": "unknown",
             "reason": "stateful risk guard unavailable"}
        )
        host.review_debug.record_agent(
            "stateful_risk_guard", node=cursor.state_id,
            step=host._action_count + 1,
            verdict=("allow" if guard_result.get("allow") else "deny"),
            reason=str(guard_result.get("reason") or "")[:160],
            risk=str(guard_result.get("risk") or "unknown"),
            state_key=elem.state_key, state_value=elem.state_value,
        )
        if not guard_result.get("allow"):
            host._record_abnormal_button(
                cursor.state_id, elem, "stateful_risk_blocked",
                (f"risk={guard_result.get('risk', 'unknown')}: "
                 f"{guard_result.get('reason', 'risk not cleared')}"),
                action=None,
            )
            return CandidatePlanOutcome(StageDirective.CONTINUE)
    host.review_debug.record_agent(
        "frontier_scheduler", node=cursor.state_id,
        step=host._action_count + 1,
        verdict=(getattr(elem, "name", "") or ""),
        reason=decision_reason, action=str(action.get("action_type") or ""),
    )
    context = CandidateContext(
        element=elem, decision_reason=decision_reason, is_seed=is_seed,
        is_stateful=is_stateful, is_restore=is_restore,
        mutation_id=mutation_id, stateful_evidence=evidence,
        active_mutation=active_mutation,
        # Semantic registration already mapped this live screenshot to the
        # stable cursor identity. Do not re-guess it from transient block or
        # element descriptions immediately before the click.
        pre_click_id=(
            cursor.state_id
            if bool(getattr(
                getattr(host, "perception", None),
                "use_semantic_inventory", False))
            else host._frame_state_id(cursor.observation, candidates)),
        action=action, targeted=targeted,
        direct_action=True,
        exploration_task_id=str(task.get("task_id") or ""),
    )
    return CandidatePlanOutcome(StageDirective.EXECUTION, context)
