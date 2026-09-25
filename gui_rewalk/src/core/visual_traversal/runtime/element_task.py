"""Short-lived memory for one framework-selected exploration goal."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


TASK_PROMPT_HISTORY_LIMIT = 12


def active_element_task(host) -> Optional[Dict[str, Any]]:
    task = getattr(host, "_element_exploration_task", None)
    return task if isinstance(task, dict) and task.get("status") == "active" else None


def start_element_task(host, state_id: str, element) -> Dict[str, Any]:
    graph = getattr(host, "graph", None)
    action_edges = list(getattr(graph, "action_edges", []) or [])
    scroll_ledger = getattr(graph, "scroll_ledger", {}) or {}
    task = {
        "task_id": (
            f"{state_id}:{getattr(element, 'id', '')}:"
            f"{getattr(host, '_action_count', 0) + 1}"
        ),
        "status": "active",
        "goal_state_id": str(state_id),
        "goal_element_id": str(getattr(element, "id", "") or ""),
        "goal_target": str(getattr(element, "name", "") or ""),
        "goal_region": str(getattr(element, "region", "") or ""),
        "goal_element": element,
        "history": [],
        "actions_used": 0,
        "tool_calls_used": 0,
        "phase": "seeking_goal",
        "start_facts": {
            "pages": len(getattr(host, "_state_data", {}) or {}),
            "controls": sum(
                len((data or {}).get("elements") or [])
                for data in (getattr(host, "_state_data", {}) or {}).values()
            ),
            "verified_edges": sum(
                1 for edge in action_edges
                if isinstance(edge, dict)
                and edge.get("routing_verified") is True
            ),
            "complete_scroll_regions": sum(
                1 for record in scroll_ledger.values()
                if isinstance(record, dict) and record.get("complete") is True
            ),
        },
    }
    host._element_exploration_task = task
    host.review_debug.record_event(
        "element_task_started",
        task_id=task["task_id"],
        node=str(state_id),
        goal=task["goal_target"],
        region=task["goal_region"],
    )
    return task


def finish_element_task(host, status: str, reason: str) -> None:
    task = active_element_task(host)
    if task is None:
        return
    task["status"] = str(status)
    task["reason"] = str(reason)
    host.review_debug.record_event(
        "element_task_finished",
        task_id=task.get("task_id", ""),
        verdict=str(status),
        reason=str(reason)[:240],
        actions_used=int(task.get("actions_used", 0)),
        history=list(task.get("history") or []),
    )
    host._element_exploration_task = None


def task_goal_resolved(task: Dict[str, Any]) -> bool:
    element = task.get("goal_element")
    return str(getattr(element, "exploration_status", "") or "") in {
        "complete", "covered", "semantic_only", "terminal",
    }


def task_goal_action_verified(task: Dict[str, Any]) -> bool:
    return any(
        event.get("goal_action") is True
        and event.get("outcome") == "transitioned_consistent"
        and event.get("landing_verified") is True
        for event in list(task.get("history") or [])
    )


def task_memory_for_prompt(task: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the complete ledger while bounding only the repeated prompt text."""
    history = list(task.get("history") or [])
    prompt_events = []
    for source in history[-TASK_PROMPT_HISTORY_LIMIT:]:
        event = dict(source)
        if event.get("tool_result") is not None:
            event["detail"] = "tool result is stored in tool_result"
        prompt_events.append(event)
    return {
        "events": prompt_events,
        "older_events_omitted": max(
            0, len(history) - TASK_PROMPT_HISTORY_LIMIT),
        "total_actions": int(task.get("actions_used", 0)),
        "total_tool_calls": int(task.get("tool_calls_used", 0)),
        "phase": str(task.get("phase") or "seeking_goal"),
    }


def task_progress_facts(host, task: Dict[str, Any]) -> Dict[str, Any]:
    """Expose objective progress/repetition facts; the Agent judges a loop."""
    graph = getattr(host, "graph", None)
    action_edges = list(getattr(graph, "action_edges", []) or [])
    scroll_ledger = getattr(graph, "scroll_ledger", {}) or {}
    current = {
        "pages": len(getattr(host, "_state_data", {}) or {}),
        "controls": sum(
            len((data or {}).get("elements") or [])
            for data in (getattr(host, "_state_data", {}) or {}).values()
        ),
        "verified_edges": sum(
            1 for edge in action_edges
            if isinstance(edge, dict) and edge.get("routing_verified") is True
        ),
        "complete_scroll_regions": sum(
            1 for record in scroll_ledger.values()
            if isinstance(record, dict) and record.get("complete") is True
        ),
    }
    start = dict(task.get("start_facts") or {})
    deltas = {
        key: int(value) - int(start.get(key, 0) or 0)
        for key, value in current.items()
    }
    actions = [
        event for event in list(task.get("history") or [])
        if str((event.get("action") or {}).get(
            "action_type") or "").upper() != "TOOL"
    ]
    signatures = [(
        str(event.get("source_page") or ""),
        str(event.get("selected_target") or ""),
        str((event.get("action") or {}).get("action_type") or ""),
        str(event.get("landing_page") or ""),
        str(event.get("outcome") or ""),
    ) for event in actions]
    repeated_last_action = 0
    if signatures:
        last = signatures[-1]
        for signature in reversed(signatures):
            if signature != last:
                break
            repeated_last_action += 1
    pages = [str(event.get("landing_page") or "") for event in actions]
    page_cycle = bool(
        len(pages) >= 4
        and pages[-4] == pages[-2]
        and pages[-3] == pages[-1]
        and pages[-4] != pages[-3]
    )
    no_progress_outcomes = {
        "no_effect", "no_visible_change", "recovered_without_landing",
        "execution_not_completed", "execution_stopped", "recovery_stopped",
    }
    if (
        repeated_last_action >= 3
        and signatures
        and str(actions[-1].get("outcome") or "").casefold()
        in no_progress_outcomes
    ):
        guard_signature = "repeat:" + "|".join(signatures[-1][:4])
    else:
        guard_signature = ""
    return {
        "since_task_start": deltas,
        "repeated_last_action": repeated_last_action,
        "recent_page_cycle": page_cycle,
        "loop_warning": bool(guard_signature),
        "guard_signature": guard_signature,
        "instruction": (
            "这些是框架提供的客观重复/进展事实；由你判断是否形成死循环。"
        ),
    }


def record_element_task_tool(host, tool_call: Dict[str, Any],
                             result: Dict[str, Any], error: str,
                             *, page_name: str) -> None:
    task = active_element_task(host)
    if task is None:
        return
    task.setdefault("history", []).append({
        "step": len(task.get("history") or []) + 1,
        "selected_target": f"tool:{tool_call.get('tool_name') or ''}",
        "goal_action": False,
        "action": {
            "action_type": "TOOL",
            "tool_name": str(tool_call.get("tool_name") or ""),
            "arguments": dict(tool_call.get("arguments") or {}),
        },
        "source_page": str(page_name or ""),
        "outcome": "tool_error" if error else "tool_result",
        "detail": str(error or json.dumps(
            result, ensure_ascii=False, separators=(",", ":")))[:2000],
        "landing_page": str(page_name or ""),
        "landing_verified": None,
        "tool_result": dict(result or {}),
    })
    task["tool_calls_used"] = int(task.get("tool_calls_used", 0)) + 1


def finish_resolved_goal(host, task: Dict[str, Any]) -> None:
    status = str(getattr(
        task.get("goal_element"), "exploration_status", "") or "")
    if status == "terminal":
        finish_element_task(
            host, "terminal", "framework closed the goal with a terminal fact")
    else:
        finish_element_task(host, "complete", "framework resolved the goal")


def task_route_guidance(host, current_state_id: str,
                        task: Dict[str, Any]) -> Dict[str, Any]:
    goal_state_id = str(task.get("goal_state_id") or "")
    current_state_id = str(current_state_id)
    state_data = getattr(host, "_state_data", {})
    current_page = str((state_data.get(current_state_id) or {}).get(
        "page_name") or "")
    goal_page = str((state_data.get(goal_state_id) or {}).get(
        "page_name") or "")
    if current_state_id == goal_state_id:
        return {
            "status": "at_goal_source",
            "current_page": current_page,
            "goal_page": goal_page,
            "steps": [],
        }
    route = host.router.plan_route(current_state_id, goal_state_id)
    if route is None:
        return {
            "status": "no_verified_route",
            "current_page": current_page,
            "goal_page": goal_page,
            "steps": [],
        }
    steps = []
    for step in route:
        destination = str(step.get("dst") or "")
        steps.append({
            "destination_state_id": destination,
            "element_id": str(step.get("element_id") or ""),
            "target": str(step.get("name") or ""),
            "area": str(step.get("region") or ""),
            "action": dict(step.get("action") or {}),
            "reaches": str((state_data.get(destination) or {}).get(
                "page_name") or destination),
        })
    return {
        "status": "verified_route",
        "current_page": current_page,
        "goal_page": goal_page,
        "steps": steps,
    }


def compact_page_graph(host, current_state_id: str,
                       task: Dict[str, Any],
                       route_guidance: Dict[str, Any]) -> Dict[str, Any]:
    """Build a prompt-local page directory and sparse verified relations."""
    state_data = getattr(host, "_state_data", {}) or {}
    page_rows: Dict[str, Dict[str, Any]] = {}
    state_pages: Dict[str, str] = {}
    for state_id, data in state_data.items():
        if not isinstance(data, dict):
            continue
        page_key = str(data.get("page_id") or state_id)
        state_pages[str(state_id)] = page_key
        row = page_rows.setdefault(page_key, {
            "name": str(data.get("page_name") or "Unknown page"),
            "regions": [],
        })
        if row["name"] == "Unknown page" and data.get("page_name"):
            row["name"] = str(data["page_name"])
        for block in data.get("semantic_blocks") or []:
            if not isinstance(block, dict):
                continue
            role = str(block.get("role") or block.get("name") or "").strip()
            if role and role not in row["regions"]:
                row["regions"].append(role)

    current_state_id = str(current_state_id)
    goal_state_id = str(task.get("goal_state_id") or "")
    current_page_key = state_pages.get(current_state_id, current_state_id)
    goal_page_key = state_pages.get(goal_state_id, goal_state_id)
    for page_key, fallback in (
        (current_page_key, str((state_data.get(current_state_id) or {}).get(
            "page_name") or "Current page")),
        (goal_page_key, str((state_data.get(goal_state_id) or {}).get(
            "page_name") or "Goal page")),
    ):
        if page_key and page_key not in page_rows:
            page_rows[page_key] = {"name": fallback, "regions": []}

    aliases = {
        page_key: f"p{index}"
        for index, page_key in enumerate(page_rows)
    }
    state_ids_by_ref = {
        aliases[page_key]: [
            str(state_id) for state_id, state_page_key in state_pages.items()
            if state_page_key == page_key
        ]
        for page_key in page_rows
    }
    links = set()
    for edge in list(getattr(getattr(host, "graph", None),
                             "action_edges", []) or []):
        if not isinstance(edge, dict) or edge.get("routing_verified") is not True:
            continue
        source_key = state_pages.get(str(edge.get("source") or ""))
        target_key = state_pages.get(str(edge.get("target") or ""))
        if (not source_key or not target_key or source_key == target_key
                or source_key not in aliases or target_key not in aliases):
            continue
        links.add((aliases[source_key], aliases[target_key]))

    route_refs = []
    current_ref = aliases.get(current_page_key, "")
    if current_ref:
        route_refs.append(current_ref)
    for step in list(route_guidance.get("steps") or []):
        destination = str(step.get("destination_state_id") or "")
        page_key = state_pages.get(destination, destination)
        page_ref = aliases.get(page_key, "")
        if page_ref and (not route_refs or route_refs[-1] != page_ref):
            route_refs.append(page_ref)

    page_lines = []
    for page_key, row in page_rows.items():
        regions = list(row.get("regions") or [])[:4]
        description = (
            "Regions: " + ", ".join(regions)
            if regions else "known page"
        )
        page_lines.append(
            f"{aliases[page_key]} | {row.get('name') or 'Unknown page'} | "
            f"{description}"
        )
    link_lines = [
        f"{source} -> {target}"
        for source, target in sorted(links)
    ] or ["(none verified yet)"]
    route_lines = " -> ".join(route_refs) if route_refs else "(no verified route)"
    steps = list(route_guidance.get("steps") or [])
    if steps:
        first = steps[0]
        next_hint = (
            f"Use the visible entry '{first.get('target') or ''}' to reach "
            f"{first.get('reaches') or 'the next page'}."
        )
    elif current_page_key == goal_page_key:
        next_hint = "Already on the goal source page; explore the task target."
    else:
        next_hint = "No verified route is available; use the current screenshot safely."

    text = "\n".join([
        f"CURRENT: {current_ref or 'unknown'}",
        f"GOAL_SOURCE: {aliases.get(goal_page_key, 'unknown')}",
        "",
        "PAGES:",
        *page_lines,
        "",
        "LINKS:",
        *link_lines,
        "",
        "ROUTE:",
        route_lines,
        "",
        "NEXT_HINT:",
        next_hint,
    ])
    return {
        "text": text,
        "page_refs": list(aliases.values()),
        "current_page_ref": current_ref,
        "goal_page_ref": aliases.get(goal_page_key, ""),
        "route": route_refs,
        "state_ids_by_ref": state_ids_by_ref,
    }


def record_element_task_action(host, plan, source_cursor, result_cursor,
                               attempt=None, *, stage: str) -> None:
    task = active_element_task(host)
    if task is None:
        return
    if str(getattr(plan, "exploration_task_id", "") or "") != str(
            task.get("task_id") or ""):
        return
    event = {}
    event_index = getattr(attempt, "event_index", None) if attempt else None
    if event_index is not None and hasattr(host.graph, "action_attempt"):
        try:
            event = dict(host.graph.action_attempt(event_index) or {})
        except (KeyError, ValueError):
            event = {}
    landing_state = str(getattr(result_cursor, "state_id", "") or "")
    source_state = str(getattr(source_cursor, "state_id", "") or "")
    source_page = str((getattr(host, "_state_data", {}).get(
        source_state) or {}).get("page_name") or "")
    landing_page = str((getattr(host, "_state_data", {}).get(
        landing_state) or {}).get("page_name") or "")
    action = dict(event.get("action") or getattr(plan, "action", {}) or {})
    plan_element = getattr(plan, "element", None)
    goal_element = task.get("goal_element")
    goal_action = (
        source_state == str(task.get("goal_state_id") or "")
        and (
            plan_element is goal_element
            or (
                str(getattr(plan_element, "id", "") or "")
                == str(task.get("goal_element_id") or "")
            )
        )
    )
    goal_was_verified = task_goal_action_verified(task)
    task.setdefault("history", []).append({
        "step": len(task.get("history") or []) + 1,
        "selected_target": str(getattr(
            plan_element, "name", "") or ""),
        "goal_action": goal_action,
        "action": action,
        "source_page": source_page,
        "outcome": str(event.get("outcome") or stage),
        "detail": str(event.get("detail") or "")[:240],
        "landing_page": landing_page,
        "landing_verified": event.get("landing_verified"),
    })
    task["actions_used"] = int(task.get("actions_used", 0)) + 1
    goal_source_data = getattr(host, "_state_data", {}).get(
        str(task.get("goal_state_id") or "")) or {}
    landing_data = getattr(host, "_state_data", {}).get(landing_state) or {}
    goal_page_id = str(
        goal_source_data.get("page_id") or task.get("goal_state_id") or "")
    landing_page_id = str(landing_data.get("page_id") or landing_state)
    if (
        goal_was_verified
        and landing_page_id == goal_page_id
        and event.get("landing_verified") is True
    ):
        finish_element_task(
            host, "complete", "verified optional return reached the goal source")
        return
    if task_goal_action_verified(task):
        task["phase"] = "goal_verified_return_optional"
        task["goal_verified_landing_state_id"] = landing_state
        return
    if task_goal_resolved(task):
        finish_resolved_goal(host, task)
        return
    if task.get("agentic") is False:
        finish_element_task(
            host, "fallback_complete",
            "task agent was unavailable; retained the original one-click path",
        )
        return


def record_element_task_route(host, source_state_id: str,
                              landing_state_id: str, status: str) -> None:
    task = active_element_task(host)
    if task is None:
        return
    state_data = getattr(host, "_state_data", {})
    landing_page = str((state_data.get(str(landing_state_id)) or {}).get(
        "page_name") or "")
    task.setdefault("history", []).append({
        "step": len(task.get("history") or []) + 1,
        "selected_target": "framework verified route",
        "action": {"action_type": "ROUTE"},
        "outcome": str(status),
        "detail": f"{source_state_id} -> {landing_state_id}",
        "landing_page": landing_page,
        "landing_verified": str(status).startswith("arrived"),
    })


__all__ = [
    "active_element_task", "compact_page_graph", "finish_element_task",
    "finish_resolved_goal",
    "record_element_task_action", "record_element_task_route",
    "record_element_task_tool",
    "start_element_task",
    "task_goal_action_verified", "task_goal_resolved",
    "task_memory_for_prompt", "task_progress_facts",
    "task_route_guidance",
]
