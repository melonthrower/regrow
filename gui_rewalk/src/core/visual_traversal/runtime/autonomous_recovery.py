"""Temporary-interruption planning and target-app recovery for autonomous traversal."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from ...app_lifecycle import restart_app_preserving_data
from ...graph.mobile_ops import focus_app_window, is_app_foreground
from ..action_space import is_android as platform_is_android
from .autonomous_agent import INTERRUPTION_ROUND_LIMIT
from .autonomous_region_tools import screenshot_frame_id
from .autonomous_runtime import AutonomousTraversalRuntime
from .autonomous_turn import (
    AutonomousDecision,
    PendingAction,
    _exploration_task_key,
)


def _handle_outside_target_app(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction],
    history: List[Dict[str, Any]],
    current_screenshot: bytes = b"",
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Keep external platform-owned frames out of the autonomous map."""
    is_android = platform_is_android(host.platform)
    desktop_window_owner = getattr(host, "desktop_window_owner", None)
    if not is_android and desktop_window_owner is None:
        return "inside", None
    verdicts: List[Optional[bool]] = []
    for _attempt in range(2):
        try:
            verdicts.append(
                is_app_foreground(host.env, host.app_name)
                if is_android else desktop_window_owner.is_foreground()
            )
        except Exception:
            verdicts.append(None)
        if verdicts[-1] is True:
            return "inside", None
    stop_reason = "left_target_app" if any(
        item is False for item in verdicts) else "focus_unknown"
    if stop_reason == "focus_unknown":
        frame_id = (
            screenshot_frame_id(current_screenshot)
            if current_screenshot else ""
        )
        visual_classification = ""
        if frame_id:
            for record in reversed(history):
                if (
                    record.get("kind") == "app_scope_resolution"
                    and record.get("frame_id") == frame_id
                ):
                    visual_classification = str(
                        record.get("outcome") or "").strip().casefold()
                    break
        if visual_classification in {
            "target_app", "target_app_obstructed",
        }:
            return "inside", None
        if visual_classification == "external_app":
            stop_reason = "left_target_app"
        elif visual_classification != "uncertain":
            return "needs_review", None
    platform_name = "Android" if is_android else "Desktop"
    detail = (
        f"{platform_name} foreground ownership is outside target app "
        f"{host.app_name!r}; "
        "the visible system/other-app frame was not registered."
        if stop_reason == "left_target_app"
        else (
            f"{platform_name} foreground ownership was unavailable after two system "
            "queries; the visible frame was not registered."
        )
    )
    if pending is not None:
        evidence = dict(pending.evidence)
        evidence["app_scope_violation"] = {
            "status": stop_reason,
            "foreground_verdicts": verdicts,
        }
        semantic_terminal = stop_reason == "left_target_app"
        if semantic_terminal:
            evidence["semantic_only_terminal"] = True
        host.graph.update_action_event(
            pending.event_index,
            target="",
            outcome=stop_reason,
            detail=detail,
            landing_verified=semantic_terminal,
            target_page_name="",
            committed=semantic_terminal,
            evidence=evidence,
        )
        if 0 <= pending.history_index < len(history):
            history[pending.history_index].update({
                "outcome": stop_reason,
                "detail": detail,
                "landing_verified": semantic_terminal,
                "committed": semantic_terminal,
                "semantic_only_terminal": semantic_terminal,
            })
        if pending.entry_action_id:
            host.entry_ledger.finish_action(
                pending.entry_action_id,
                action_executed=True,
                outcome_verified=semantic_terminal,
                result=detail,
            )
    history.append({
        "kind": "app_scope_violation",
        "outcome": stop_reason,
        "detail": detail,
        "app_name": host.app_name,
        "foreground_verdicts": verdicts,
        "event_index": pending.event_index if pending is not None else None,
    })
    recovered_observation: Dict[str, Any] = {}
    activated = False
    try:
        if is_android:
            activated = bool(focus_app_window(host.env, host.app_name))
        else:
            activate = getattr(desktop_window_owner, "activate", None)
            activated = bool(activate()) if callable(activate) else False
    except Exception:
        activated = False
    if activated:
        recovered_observation = host.fresh_observation({}) or {}
    if (recovered_observation or {}).get("screenshot"):
        history.append({
            "kind": "app_scope_recovery",
            "outcome": "reactivated_target_app",
            "detail": (
                "The run-bound target app was brought back to the foreground "
                "without registering the intervening frame or a recovery edge."
            ),
            "event_index": pending.event_index if pending is not None else None,
            "semantic_graph_recorded": False,
        })
        host.graph.stop_reason = "incomplete"
        return "recovered", recovered_observation

    try:
        relaunch_fn = getattr(host, "relaunch_fn", None)
        if callable(relaunch_fn):
            recovered_observation = relaunch_fn() or {}
            restarted = bool(recovered_observation.get("screenshot"))
        elif desktop_window_owner is None:
            restarted = restart_app_preserving_data(
                host.env, host.app_name)
        else:
            restarted = restart_app_preserving_data(
                host.env,
                host.app_name,
                desktop_window_owner=desktop_window_owner,
            )
    except Exception as exc:
        restarted = False
        detail = f"{detail} Data-preserving app restart failed: {str(exc)[:300]}"
    if restarted and not recovered_observation:
        recovered_observation = host.fresh_observation({})
    if (recovered_observation or {}).get("screenshot"):
        host.protocol_map.current_page = ""
        host.protocol_map.current_variant = ""
        host.pending_connection = None
        host.pending_page_identity = None
        host.pending_landing_page = None
        history.append({
            "kind": "app_scope_recovery",
            "outcome": "restarted_target_app",
            "detail": (
                "The target app could not be reactivated in place and was "
                "reopened without registering the intervening frame or a "
                "recovery edge."
            ),
            "event_index": pending.event_index if pending is not None else None,
            "semantic_graph_recorded": False,
        })
        host.graph.stop_reason = "incomplete"
        return "recovered", recovered_observation
    history.append({
        "kind": "app_scope_recovery",
        "outcome": "target_app_recovery_failed",
        "detail": detail,
        "event_index": pending.event_index if pending is not None else None,
        "semantic_graph_recorded": False,
    })
    host.graph.stop_reason = stop_reason
    return "stopped", None


def _interruption_plan(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    screen_name: str,
    arguments: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Optional[AutonomousDecision]:
    """Ask one specialist for a bounded strategy and bind its exact action."""
    task_key = _exploration_task_key(host.exploration_task) or "unassigned"
    if host.interruption_task_key != task_key:
        host.interruption_task_key = task_key
        host.interruption_rounds = 0
    if host.interruption_rounds >= INTERRUPTION_ROUND_LIMIT:
        history.append({
            "kind": "tool",
            "screen": screen_name,
            "frame_id": screenshot_frame_id(screenshot),
            "tool_name": "handle_interruption",
            "tool_arguments": dict(arguments),
            "tool_result": {
                "status": "round_limit",
                "data": {
                    "feedback": (
                        "Interruption handling already used its three bounded "
                        "rounds for this task. Continue by another visible route, "
                        "wait as an ordinary observation when justified, or leave "
                        "the exact task unresolved; do not guess another close."
                    ),
                },
                "attached_images": [],
                "pending_review": False,
            },
            "exploration_task_id": (
                host.exploration_task.task_id
                if host.exploration_task else ""
            ),
            "outcome": "round_limit",
        })
        return None

    host.interruption_rounds += 1
    round_number = host.interruption_rounds
    raw: Any = None
    error = ""
    if not callable(host.interruption_reviewer):
        error = "interruption specialist is unavailable"
    else:
        try:
            raw = host.interruption_reviewer({
                "current_screenshot": screenshot,
                "platform": host.platform,
                "current_page": screen_name,
                "current_task": (
                    asdict(host.exploration_task)
                    if host.exploration_task else {}
                ),
                "main_agent_observation": dict(arguments),
                "handling_round": round_number,
                "handling_round_limit": INTERRUPTION_ROUND_LIMIT,
            })
        except Exception as exc:
            error = (
                "独立临时干扰处理 Agent 本轮没有返回可用判断；当前界面和任务"
                "均未改变。")

    result = dict(raw) if isinstance(raw, dict) else {}
    reason = str(result.get("reason") or error).strip()
    strategy = str(result.get("strategy") or "unresolved").strip().casefold()
    allowed = {"ignore", "wait", "hover", "click", "back", "unresolved"}
    if not reason:
        reason = "interruption specialist returned no non-empty reason"
        strategy = "unresolved"
    if strategy not in allowed:
        reason = "临时干扰处理 Agent 选择了当前协议不支持的处理方式。"
        strategy = "unresolved"

    surface_is_temporary = result.get("surface_is_temporary") is True
    blocks_current_target = result.get("blocks_current_target") is True
    target_is_close_control = result.get("target_is_close_control") is True
    target = str(result.get("target") or "").strip()
    suspected_surface = str(
        arguments.get("suspected_surface") or ""
    ).strip()
    raw_point = result.get("point_1000")
    point: Optional[List[float]] = None
    if isinstance(raw_point, (list, tuple)) and len(raw_point) == 2:
        values: List[float] = []
        for value in raw_point:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                values = []
                break
            number = float(value)
            if not 0 <= number <= 1000:
                values = []
                break
            values.append(number)
        if len(values) == 2:
            point = values

    action_strategy = strategy in {"hover", "click", "back"}
    if action_strategy and not (
            surface_is_temporary and blocks_current_target):
        reason = (
            "The specialist did not strictly confirm both a temporary surface "
            "and current-target obstruction; no recovery action is authorized. "
            + reason
        )[:800]
        strategy = "unresolved"
    if strategy == "click" and (not target or point is None):
        reason = (
            f"The {strategy} strategy did not bind a visible target and valid "
            "point; no action was executed."
        )
        strategy = "unresolved"
    if strategy == "hover" and (not target or point is None):
        reason = (
            "The hover strategy did not bind a visible temporary surface and "
            "valid point; no action was executed."
        )
        strategy = "unresolved"
    if strategy == "click" and not target_is_close_control:
        reason = (
            "The specialist did not strictly confirm that the visible target "
            "is a close control owned by the interruption; no click was authorized."
        )
        strategy = "unresolved"
    if (strategy == "click" and suspected_surface
            and " ".join(target.casefold().split())
            == " ".join(suspected_surface.casefold().split())):
        reason = (
            "The specialist named the whole suspected interference surface as "
            "its close control; no click was authorized."
        )
        strategy = "unresolved"

    planned = strategy in {"wait", "hover", "click", "back"}
    feedback = (
        f"Interruption specialist selected {strategy}"
        + (f" on {target}" if target else "")
        + f" (round {round_number}/{INTERRUPTION_ROUND_LIMIT}): {reason}"
    )[:1000]
    history.append({
        "kind": "tool",
        "screen": screen_name,
        "frame_id": screenshot_frame_id(screenshot),
        "tool_name": "handle_interruption",
        "tool_arguments": dict(arguments),
        "tool_result": {
            "status": "planned" if planned else strategy,
            "data": {
                "surface_is_temporary": surface_is_temporary,
                "blocks_current_target": blocks_current_target,
                "strategy": strategy,
                "target": target if strategy in {"hover", "click"} else "",
                "point_1000": point if strategy in {"hover", "click"} else None,
                "target_is_close_control": (
                    target_is_close_control if strategy == "click" else False
                ),
                "reason": reason,
                "handling_round": round_number,
                "feedback": feedback,
            },
            "attached_images": [],
            "pending_review": False,
        },
        "exploration_task": (
            asdict(host.exploration_task) if host.exploration_task else None
        ),
        "exploration_task_id": (
            host.exploration_task.task_id if host.exploration_task else ""
        ),
        "outcome": "planned" if planned else strategy,
    })

    common = {
        "direction": "",
        "reason": reason,
        "purpose": "interruption_recovery",
    }
    if strategy == "wait":
        return AutonomousDecision(
            action="WAIT",
            target="",
            point_1000=None,
            tool_name="navigate",
            tool_arguments={"operation": "wait"},
            **common,
        )
    if strategy == "hover":
        return AutonomousDecision(
            action="HOVER",
            target=target,
            point_1000=point,
            tool_name="hover",
            tool_arguments={"target": target, "point_1000": point},
            **common,
        )
    if strategy == "click":
        return AutonomousDecision(
            action="CLICK",
            target=target,
            point_1000=point,
            tool_name="click",
            tool_arguments={
                "target": target, "entry_id": "", "point_1000": point,
            },
            **common,
        )
    if strategy == "back":
        return AutonomousDecision(
            action="BACK",
            target=strategy,
            point_1000=None,
            tool_name="navigate",
            tool_arguments={"operation": strategy},
            **common,
        )
    return None
