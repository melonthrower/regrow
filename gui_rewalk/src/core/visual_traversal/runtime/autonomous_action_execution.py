"""Translate and settle Qwen autonomous GUI actions.

This module owns deterministic action conversion, pre-dispatch Attempt
preparation, and post-observation effect, Entry and route settlement. It does
not call Qwen, review a target, choose the next task, or dispatch the GUI
environment; those decisions remain in the autonomous loop.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import os
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image

from ...scenario.capability_induction import (
    AUTONOMOUS_ELEMENT_UID_PREFIX,
    AUTONOMOUS_ENTRY_UID_PREFIX,
)
from ..action_space import (
    is_android as platform_is_android,
    normalize_native_action,
)
from .autonomous_action_tools import (
    ActionValidationError,
    PreviousToolReview,
    build_action_result,
    validate_action_tool_call,
)
from .autonomous_completion import _request_same_page_resurvey
from .autonomous_context import _region_probe_ref, _region_state
from .autonomous_prompt import _rejection_feedback
from .autonomous_region_tools import _region_for_point, screenshot_frame_id
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _record_agent_inferred_edges,
)
from .autonomous_scheduling import (
    _covered_region_probe_operation_issue,
    _region_probe_has_started,
    _record_region_probe_attempt,
    _repeat_no_change_scroll_issue,
    _repeat_task_frame_action_issue,
)
from .autonomous_turn import (
    AutonomousDecision,
    AutonomousTurn,
    ObservedScene,
    PendingAction,
    PreviousAssessment,
    _page_key,
    _reviewed_pending_target,
)


def _apply_scope_effects(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    scene: ObservedScene,
    assessment: PreviousAssessment,
    history: List[Dict[str, Any]],
    *,
    entry_record: Any = None,
) -> List[Dict[str, Any]]:
    """Commit model-reported effects only after binding them to known scopes."""
    if not assessment.effects:
        return []
    source_page = pending.source.page_name
    source_state = host.region_states.get(_page_key(source_page))
    action_attempt = host.graph.action_attempt(pending.event_index)
    evidence_action_id = str(
        action_attempt.get("attempt_id") or pending.event_index)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    structure_regions: List[tuple[str, str, str]] = []
    transition_effects: List[Dict[str, str]] = []

    for effect in assessment.effects:
        if effect.scope_type in {"owner_region", "region"}:
            if _page_key(source_page) != _page_key(scene.page_name):
                rejected.append({
                    "scope_type": effect.scope_type,
                    "scope_name": effect.scope_name,
                    "reason": (
                        "source-Page Region effect cannot be confirmed after "
                        "leaving its Page"),
                })
                continue
            region_name = (
                str(getattr(entry_record, "region_name", "") or "")
                if effect.scope_type == "owner_region"
                else effect.scope_name
            )
            region = (
                source_state.region(region_name)
                if source_state is not None and region_name else None
            )
            region_ref = host.region_registry.region_ref(
                source_page, region_name)
            occurrence_ref = host.region_registry.occurrence_ref(
                source_page, region_name)
            if region is None or not region_ref or not occurrence_ref:
                rejected.append({
                    "scope_type": effect.scope_type,
                    "scope_name": effect.scope_name,
                    "reason": "effect does not bind to a known source-Page Region",
                })
                continue
            if (
                effect.change_kind in {"structure", "state"}
                and effect.before_value != effect.after_value
                and _page_key(source_page) == _page_key(scene.page_name)
            ):
                transition_effects.append({
                    "region_name": region_name,
                    "effect_text": (
                        f"{effect.scope_name}: {effect.before_value} -> "
                        f"{effect.after_value}"
                    ),
                    "effect_kind": effect.change_kind,
                })
            if effect.change_kind == "structure":
                source_state.set_coverage_complete(region_name, False)
                structure_regions.append(
                    (region_name, region_ref, occurrence_ref))
            accepted.append({
                "scope_type": effect.scope_type,
                "scope_name": region_name,
                "scope_ref": occurrence_ref,
                "change_kind": effect.change_kind,
                "before_value": effect.before_value,
                "after_value": effect.after_value,
            })
            continue

        if effect.scope_type == "page_mode":
            if _page_key(source_page) != _page_key(scene.page_name):
                rejected.append({
                    "scope_type": effect.scope_type,
                    "scope_name": effect.scope_name,
                    "reason": "page mode cannot be observed after leaving its Page",
                })
                continue
            selected_refs: List[str] = []
            unknown_selected: List[str] = []
            for region_name in effect.selected_region_names:
                occurrence_ref = host.region_registry.occurrence_ref(
                    source_page, region_name)
                if occurrence_ref:
                    selected_refs.append(occurrence_ref)
                else:
                    unknown_selected.append(region_name)
            if unknown_selected:
                rejected.append({
                    "scope_type": effect.scope_type,
                    "scope_name": effect.scope_name,
                    "reason": (
                        "selected_region_names contains unknown source-Page "
                        f"Regions: {unknown_selected}"
                    ),
                })
                continue
            host.scope_state_ledger.record_page_mode(
                page_name=source_page,
                scope_name=effect.scope_name,
                before_value=effect.before_value,
                after_value=effect.after_value,
                selected_occurrence_refs=selected_refs,
                evidence_action_id=evidence_action_id,
                trigger_entry_id=str(
                    getattr(entry_record, "entry_id", "") or ""),
                trigger_operation=str(
                    getattr(pending.validated_action, "operation", "")
                    or pending.primitive.get("action_type") or "click"),
            )
            accepted.append({
                "scope_type": effect.scope_type,
                "scope_name": effect.scope_name,
                "change_kind": effect.change_kind,
                "before_value": effect.before_value,
                "after_value": effect.after_value,
                "selected_occurrence_refs": selected_refs,
            })
            continue

        host.scope_state_ledger.record_app_state(
            scope_name=effect.scope_name,
            before_value=effect.before_value,
            after_value=effect.after_value,
            page_name=scene.page_name,
            state_id=scene.state_id,
            evidence_action_id=evidence_action_id,
        )
        accepted.append({
            "scope_type": effect.scope_type,
            "scope_name": effect.scope_name,
            "change_kind": effect.change_kind,
            "before_value": effect.before_value,
            "after_value": effect.after_value,
            "observed_page": scene.page_name,
        })

    if transition_effects:
        host.region_registry.record_scoped_transitions(
            page_name=source_page,
            source_state_id=pending.source.state_id,
            destination_state_id=scene.state_id,
            trigger_entry_id=str(
                getattr(entry_record, "entry_id", "") or ""),
            effects=transition_effects,
            evidence_action_id=evidence_action_id,
        )
    if structure_regions and _page_key(source_page) == _page_key(scene.page_name):
        unique_regions = list(dict.fromkeys(structure_regions))
        focused = unique_regions[0] if len(unique_regions) == 1 else ("", "", "")
        _request_same_page_resurvey(
            host,
            history,
            page_name=source_page,
            entry_id=str(getattr(entry_record, "entry_id", "") or ""),
            target=_reviewed_pending_target(pending) or pending.target,
            reason=assessment.reason,
            region_name=focused[0],
            region_ref=focused[1],
            occurrence_ref=focused[2],
        )
    history.append({
        "kind": "scope_effects",
        "screen": scene.page_name,
        "outcome": "recorded" if accepted else "rejected",
        "effects": accepted,
        "rejected_effects": rejected,
        "detail": assessment.reason,
    })
    return accepted


def _action_element_uid(region_ref: str, target: str) -> str:
    region_ref = str(region_ref or "").strip()
    target_key = _page_key(target)
    if not region_ref or not target_key:
        return ""
    identity = f"{region_ref}\0{target_key}".encode("utf-8")
    return (
        AUTONOMOUS_ELEMENT_UID_PREFIX
        + hashlib.sha256(identity).hexdigest()[:16])


def _convert_action_tool(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    decision: AutonomousDecision,
    review: Optional[PreviousToolReview],
) -> tuple[Optional[AutonomousDecision], str]:
    """Validate one action tool call and convert it to an internal decision."""
    if decision.action != "CALL_TOOL" or decision.tool_name not in {
            "click", "input_text", "hover", "scroll", "navigate",
            "gesture"}:
        return decision, ""
    try:
        validated = validate_action_tool_call(
            decision.tool_name,
            dict(decision.tool_arguments),
            latest_frame_id=screenshot_frame_id(screenshot),
            previous_tool_review=(asdict(review) if review else None),
            platform=host.platform,
            purpose=decision.purpose,
        )
    except ActionValidationError as exc:
        return None, f"{exc.code}: {str(exc)}"
    task = host.exploration_task
    if (
        validated.tool_name != "input_text"
        and decision.purpose == "entry_attempt"
        and task is not None
        and task.task_type == "explore_entry"
        and task.entry_id
    ):
        try:
            task_entry = host.entry_ledger.get(task.entry_id)
        except KeyError:
            task_entry = None
        if task_entry is not None and task_entry.control_type == "input":
            return None, (
                "input_entry_requires_input_text: Input Entry "
                f"{task.entry_id} requires tool_name=input_text for "
                "purpose=entry_attempt. A click may use purpose=locating "
                "to focus or reveal the field, but it cannot settle the "
                "input operation."
            )
    if validated.tool_name == "click":
        return AutonomousDecision(
            action="CLICK",
            target=str(validated.arguments["target"]),
            point_1000=list(validated.arguments["point_1000"]),
            direction="",
            reason=f"click visible target {validated.arguments['target']}",
            purpose=decision.purpose,
            tool_name="click",
            tool_arguments=dict(decision.tool_arguments),
        ), ""
    if validated.tool_name == "input_text":
        entry_purpose = (
            "entry_attempt"
            if task is not None
            and task.task_type == "explore_entry"
            and task.entry_id
            else decision.purpose
        )
        return AutonomousDecision(
            action="INPUT_TEXT",
            target=str(validated.arguments["target"]),
            point_1000=list(validated.arguments["point_1000"]),
            direction="",
            reason=(
                "enter reviewed query text in visible target "
                f"{validated.arguments['target']}"
            ),
            purpose=entry_purpose,
            tool_name="input_text",
            tool_arguments=dict(decision.tool_arguments),
        ), ""
    if validated.tool_name == "hover":
        return AutonomousDecision(
            action="HOVER",
            target=str(validated.arguments["target"]),
            point_1000=list(validated.arguments["point_1000"]),
            direction="",
            reason=f"hover visible surface {validated.arguments['target']}",
            purpose=decision.purpose,
            tool_name="hover",
            tool_arguments=dict(decision.tool_arguments),
        ), ""
    if validated.tool_name == "scroll":
        return AutonomousDecision(
            action="SCROLL",
            target=str(validated.arguments["container_hint"]),
            point_1000=list(validated.arguments["point_1000"]),
            direction=str(validated.arguments["direction"]),
            reason="inspect more content in the described scroll container",
            purpose=decision.purpose,
            tool_name="scroll",
            tool_arguments=dict(decision.tool_arguments),
        ), ""
    if validated.tool_name == "gesture":
        return AutonomousDecision(
            action=validated.operation.upper(),
            target=str(validated.arguments["target"]),
            point_1000=list(validated.arguments["point_1000"]),
            direction="",
            reason=(
                f"{validated.operation} visible target "
                f"{validated.arguments['target']}"
            ),
            purpose=decision.purpose,
            tool_name="gesture",
            tool_arguments=dict(decision.tool_arguments),
        ), ""
    action = "BACK" if validated.operation == "back" else "WAIT"
    return AutonomousDecision(
        action=action,
        target=validated.operation,
        point_1000=None,
        direction="",
        reason="navigate within the assigned traversal task",
        purpose=decision.purpose,
        tool_name="navigate",
        tool_arguments=dict(decision.tool_arguments),
    ), ""


def _pixel_point(
    screenshot: bytes,
    point_1000: Sequence[float],
) -> List[int]:
    width, height = Image.open(io.BytesIO(screenshot)).size
    return [
        round(float(point_1000[0]) * max(0, width - 1) / 1000.0),
        round(float(point_1000[1]) * max(0, height - 1) / 1000.0),
    ]


def _is_android(host: AutonomousTraversalRuntime) -> bool:
    return platform_is_android(host.platform)


def _primitive(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    decision: AutonomousDecision,
) -> Optional[Dict[str, Any]]:
    """Convert an approved internal decision to the platform primitive."""
    if decision.action == "CLICK" and decision.point_1000 is not None:
        x, y = _pixel_point(screenshot, decision.point_1000)
        if _is_android(host):
            return {"action_type": "click", "x": x, "y": y}
        return {
            "action_type": "CLICK",
            "parameters": {"x": x, "y": y, "button": "left"},
        }
    if decision.action == "INPUT_TEXT" and decision.point_1000 is not None:
        x, y = _pixel_point(screenshot, decision.point_1000)
        text = decision.tool_arguments.get("text")
        if not isinstance(text, str):
            return None
        if _is_android(host):
            return {
                "action_type": "input_text", "x": x, "y": y,
                "text": text,
            }
        return {
            "action_type": "TYPING",
            "parameters": {"x": x, "y": y, "text": text},
        }
    if decision.action == "HOVER" and decision.point_1000 is not None:
        x, y = _pixel_point(screenshot, decision.point_1000)
        return {
            "action_type": "HOVER",
            "parameters": {"x": x, "y": y, "dwell_ms": 700},
        }
    if (decision.action in {"DOUBLE_TAP", "LONG_PRESS"}
            and decision.point_1000 is not None
            and _is_android(host)):
        x, y = _pixel_point(screenshot, decision.point_1000)
        action, _error = normalize_native_action({
            "action_type": decision.action.casefold(), "x": x, "y": y,
        }, platform=host.platform)
        return action
    if decision.action == "SWIPE" and _is_android(host):
        action, _error = normalize_native_action({
            "action_type": "swipe", "direction": decision.direction,
        }, platform=host.platform)
        return action
    if decision.action == "SCROLL":
        direction = decision.direction
        requested_amount = decision.tool_arguments.get("amount", 670)
        try:
            normalized_amount = max(1, min(1000, int(requested_amount)))
        except (TypeError, ValueError):
            normalized_amount = 670
        if _is_android(host):
            action: Dict[str, Any] = {
                "action_type": "scroll", "direction": direction,
            }
            if decision.point_1000 is not None:
                action["x"], action["y"] = _pixel_point(
                    screenshot, decision.point_1000)
            return action
        wheel_amount = max(1, round(normalized_amount / 125))
        dx, dy = {
            "up": (0, wheel_amount), "down": (0, -wheel_amount),
            "left": (-wheel_amount, 0), "right": (wheel_amount, 0),
        }[direction]
        parameters: Dict[str, Any] = {
            "dx": dx, "dy": dy, "direction": direction,
            "amount": 1, "frac": normalized_amount / 1000.0,
        }
        if decision.point_1000 is not None:
            parameters["x"], parameters["y"] = _pixel_point(
                screenshot, decision.point_1000)
        return {"action_type": "SCROLL", "parameters": parameters}
    if decision.action == "BACK":
        if _is_android(host):
            return {"action_type": "navigate_back"}
        return {"action_type": "PRESS", "parameters": {"key": "esc"}}
    return None


def _save_attempt_frame(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    phase: str,
    screenshot: bytes,
) -> str:
    phase = str(phase or "").strip().casefold()
    if phase not in {"before", "after"} or not screenshot:
        return ""
    directory = os.path.join(
        host.output_root, "action_attempts", f"{pending.event_index:06d}")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{phase}.png")
    with open(path, "wb") as stream:
        stream.write(screenshot)
    return os.path.relpath(path, host.output_root).replace(os.sep, "/")


def _capture_pending_assessment(
    pending: Optional[PendingAction],
    turn: AutonomousTurn,
    screenshot: bytes,
    history: List[Dict[str, Any]],
) -> bool:
    """Bind the first Qwen post-action assessment or reject a frame conflict."""
    if pending is None or pending.assessment is not None:
        return True
    if (
        pending.source.screenshot == screenshot
        and turn.previous.outcome == "changed"
    ):
        detail = (
            "The latest screenshot is byte-identical to the pending action's "
            f"before frame, but previous_action reports changed for "
            f"{pending.target!r}."
        )
        history.append({
            "kind": "previous_action_feedback",
            "screen": turn.screen_name,
            "target": pending.target,
            "outcome": "assessment_rejected",
            "detail": detail,
            "rejection": _rejection_feedback(
                "previous_action_frame_conflict",
                detail,
                retry_after="previous_action_reassessed_from_attached_frames",
                correction=(
                    f"Reassess only the pending action {pending.target!r}. "
                    "The before and latest frames are identical, so report "
                    "no_visible_change and do not reuse an earlier action's "
                    "target or result. The next proposed GUI action from this "
                    "turn was not executed."
                ),
            ),
        })
        return False
    purpose = str(
        pending.validated_action.purpose
        if pending.validated_action is not None else ""
    ).strip().casefold()
    if turn.previous.failure_kind and purpose != "entry_attempt":
        detail = (
            "failure_kind is valid only for a settled entry_attempt; the "
            f"pending action purpose is {purpose or 'unspecified'}."
        )
        history.append({
            "kind": "previous_action_feedback",
            "screen": turn.screen_name,
            "target": pending.target,
            "outcome": "assessment_rejected",
            "detail": detail,
            "rejection": _rejection_feedback(
                "failure_kind_outside_entry_attempt", detail),
        })
        return False
    pending.assessment = turn.previous
    pending.evidence["first_model_assessment"] = asdict(turn.previous)
    return True


def _prepare_action_attempt(
    host: AutonomousTraversalRuntime,
    scene: ObservedScene,
    decision: AutonomousDecision,
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    click_review: Dict[str, Any],
    previous_tool_review: Optional[PreviousToolReview],
    bound_entry_id: str = "",
) -> Optional[PendingAction]:
    """Validate and persist one approved action before GUI dispatch."""
    primitive = _primitive(host, screenshot, decision)
    if primitive is None:
        history.append({
            "kind": "action",
            "screen": scene.page_name,
            "action": decision.action,
            "target": decision.target,
            "outcome": "not_executed",
            "detail": "the model action could not be converted",
            "rejection": _rejection_feedback(
                "action_conversion_failed",
                "the model action could not be converted",
                suggested_next_tool=decision.tool_name,
                retry_after="action_arguments_corrected",
                correction=(
                    "Correct the operation and arguments using the current "
                    "tool descriptor."
                ),
            ),
        })
        return None

    validated_action = None
    if decision.tool_name in {
            "click", "input_text", "hover", "scroll", "navigate",
            "gesture"}:
        validated_action = validate_action_tool_call(
            decision.tool_name,
            dict(decision.tool_arguments),
            latest_frame_id=screenshot_frame_id(screenshot),
            previous_tool_review=(
                asdict(previous_tool_review)
                if previous_tool_review else None
            ),
            platform=host.platform,
            purpose=decision.purpose,
        )
    repeat_scroll_issue = _repeat_no_change_scroll_issue(
        history, validated_action, screenshot_frame_id(screenshot))
    if repeat_scroll_issue:
        history.append({
            "kind": "action",
            "screen": scene.page_name,
            "action": decision.action,
            "target": decision.target,
            "outcome": "not_executed",
            "detail": repeat_scroll_issue,
            "rejection": _rejection_feedback(
                "repeat_no_change_action", repeat_scroll_issue),
        })
        return None

    task_id = (
        host.exploration_task.task_id
        if host.exploration_task is not None else ""
    )
    task_phase = (
        host.exploration_task.phase
        if host.exploration_task is not None else ""
    )
    repeat_task_action_issue = _repeat_task_frame_action_issue(
        history, validated_action, task_id, task_phase)
    if repeat_task_action_issue:
        history.append({
            "kind": "action",
            "screen": scene.page_name,
            "action": decision.action,
            "target": decision.target,
            "outcome": "not_executed",
            "detail": repeat_task_action_issue,
            "exploration_task_id": task_id,
            "exploration_task_phase": task_phase,
            "rejection": _rejection_feedback(
                "repeat_task_action_on_same_frame",
                repeat_task_action_issue,
            ),
        })
        return None

    evidence = {
        "autonomous": True,
        "model": host.decision_agent.model,
        "decision": asdict(decision),
        "click_review": click_review,
    }
    if task_id:
        evidence["exploration_task_id"] = task_id
    probe_task = host.exploration_task
    if (task_id and probe_task is not None
            and probe_task.task_type == "explore_region"
            and probe_task.phase == "explore_region"):
        source_region_ref = _region_probe_ref(
            host, probe_task.page_name, probe_task.region_name)
        if source_region_ref:
            evidence.update({
                "region_probe_task": True,
                "region_probe_start": not _region_probe_has_started(
                    host, task_id),
                "probe_id": task_id,
                "source_page": probe_task.page_name,
                "source_region": probe_task.region_name,
                "source_region_ref": source_region_ref,
            })

    entry_action_id = ""
    source_element_uid = ""
    source_element_name = decision.target
    if decision.action in {
            "CLICK", "INPUT_TEXT", "DOUBLE_TAP", "LONG_PRESS"}:
        explicit_entry_id = str(
            bound_entry_id
            or decision.tool_arguments.get("entry_id")
            or ""
        ).strip()
        if (
            not explicit_entry_id
            and decision.action == "INPUT_TEXT"
            and host.exploration_task is not None
            and host.exploration_task.task_type == "explore_entry"
        ):
            explicit_entry_id = host.exploration_task.entry_id
        region_state = _region_state(host, scene.page_name)
        region_name = _region_for_point(region_state, decision.point_1000)
        evidence["explicit_entry_task"] = bool(explicit_entry_id)
        if not evidence.get("source_region"):
            evidence["source_region"] = region_name
        if (not evidence.get("source_region_ref")
                and region_name != "full_screen"):
            source_region_ref = host.region_registry.region_ref(
                scene.page_name, region_name)
            if source_region_ref:
                evidence["source_region_ref"] = source_region_ref
        if explicit_entry_id:
            try:
                entry_attempt = host.entry_ledger.begin_explicit_action(
                    explicit_entry_id,
                    frame_id=screenshot_frame_id(screenshot),
                    page_name=scene.page_name,
                    source_state_id=scene.state_id,
                )
            except (KeyError, ValueError) as exc:
                detail = str(exc)[:500]
                history.append({
                    "kind": "action",
                    "screen": scene.page_name,
                    "action": decision.action,
                    "target": decision.target,
                    "outcome": "not_executed",
                    "detail": detail,
                    "rejection": _rejection_feedback(
                        "entry_binding_rejected",
                        detail,
                        retry_after="entry_id_corrected_or_cleared",
                        correction=(
                            "Use the exploration_task or current page-memory "
                            "entry_id only when this pointer action directly "
                            "attempts it; otherwise leave entry_id empty."
                        ),
                    ),
                })
                return None
            entry_action_id = entry_attempt.action_id
            entry_record = host.entry_ledger.get(entry_attempt.entry_id)
            evidence["source_region"] = entry_record.region_name
            evidence["discovery_source"] = entry_record.discovery_source
            source_region_ref = host.region_registry.region_ref(
                entry_record.page_name, entry_record.region_name)
            if source_region_ref:
                evidence["source_region_ref"] = source_region_ref
            evidence["entry_action_id"] = entry_action_id
            evidence["entry_id"] = entry_attempt.entry_id
        source_region_ref = str(
            evidence.get("source_region_ref") or "").strip()
        reviewed_target = str(
            click_review.get("observed_target") or "").strip()
        if source_region_ref and reviewed_target:
            if explicit_entry_id:
                source_element_uid = (
                    AUTONOMOUS_ENTRY_UID_PREFIX + entry_attempt.entry_id)
                source_element_name = entry_record.target
            else:
                source_element_uid = _action_element_uid(
                    source_region_ref, reviewed_target)
                source_element_name = reviewed_target

    probe_operation_key = ""
    if (evidence.get("region_probe_task") is True
            and validated_action is not None
            and source_element_uid):
        probe_operation_key = (
            f"{validated_action.operation}:{source_element_uid}"
        )
        covered_probe_issue = _covered_region_probe_operation_issue(
            host, probe_operation_key)
        if covered_probe_issue:
            history.append({
                "kind": "action",
                "screen": scene.page_name,
                "action": decision.action,
                "target": decision.target,
                "outcome": "not_executed",
                "detail": covered_probe_issue,
                "exploration_task_id": task_id,
                "exploration_task_phase": task_phase,
                "rejection": _rejection_feedback(
                    "covered_region_probe_operation",
                    covered_probe_issue,
                ),
            })
            return None
        evidence["region_probe_operation_key"] = probe_operation_key

    frame_id = screenshot_frame_id(screenshot)
    evidence.update({
        "before_frame_id": frame_id,
        "validated_action": (
            validated_action.to_dict() if validated_action else None
        ),
    })
    event_index = host.graph.record_action_event(
        source=scene.state_id,
        action=primitive,
        element_id=source_element_uid,
        element_label=source_element_name,
        semantic_description=decision.reason,
        region=str(evidence.get("source_region") or "full_screen"),
        outcome="attempted",
        committed=False,
        evidence=evidence,
    )
    fixture_before = host.audit_fixture(
        primitive, "before", event_index=event_index)
    if fixture_before:
        evidence["fixture_audit_before"] = fixture_before
    prepared = PendingAction(
        source=scene,
        event_index=event_index,
        primitive=primitive,
        target=decision.target,
        reason=decision.reason,
        history_index=-1,
        evidence=evidence,
        entry_action_id=entry_action_id,
        before_frame_id=frame_id,
        validated_action=validated_action,
    )
    before_path = _save_attempt_frame(
        host, prepared, "before", screenshot)
    evidence["before_screenshot"] = before_path
    host.graph.update_action_event(event_index, evidence=evidence)
    history.append({
        "kind": "action",
        "screen": scene.page_name,
        "action": decision.action,
        "target": decision.target,
        "reason": decision.reason,
        "outcome": "awaiting_observation",
        "before_screenshot": before_path,
        "exploration_task_id": task_id,
        "exploration_task_phase": task_phase,
        "validated_action": (
            validated_action.to_dict() if validated_action else None),
        "action_review": deepcopy(click_review) if click_review else {},
    })
    prepared.history_index = len(history) - 1
    return prepared


def _commit_pending(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    scene: ObservedScene,
    assessment: PreviousAssessment,
    history: List[Dict[str, Any]],
    *,
    actual_target: str,
    record_transition: bool = True,
) -> None:
    """Settle an executed attempt from fresh observed landing evidence."""
    action_attempt = host.graph.action_attempt(pending.event_index)
    source_element_uid = str(
        action_attempt.get("element_id") or "").strip()
    source_element_name = str(
        action_attempt.get("element_label") or "").strip()
    source_region = str(
        action_attempt.get("region") or "full_screen").strip()
    corrected_target = source_element_name or actual_target or pending.target
    if corrected_target != pending.target:
        host.graph.correct_action_event_semantics(
            pending.event_index,
            action=pending.primitive,
            element_label=corrected_target,
            semantic_description=pending.reason,
            region=source_region,
        )
    after_path = _save_attempt_frame(
        host, pending, "after", scene.screenshot)
    pixel_changed = pending.source.screenshot != scene.screenshot
    outcome = {
        "changed": "observed_change",
        "no_visible_change": "no_visible_change",
        "uncertain": "uncertain",
    }[assessment.outcome]
    evidence = dict(pending.evidence)
    evidence.update({
        "after_screenshot": after_path,
        "pixel_changed": pixel_changed,
        "model_assessment": asdict(assessment),
        "initial_target": pending.target,
        "corrected_target": corrected_target,
    })
    if not record_transition:
        host.graph.update_action_event(
            pending.event_index,
            target=scene.state_id,
            outcome=outcome,
            detail=assessment.reason,
            landing_verified=True,
            target_page_name=scene.page_name,
            committed=True,
            evidence=evidence,
        )
    elif assessment.outcome == "uncertain":
        host.graph.update_action_event(
            pending.event_index,
            target=scene.state_id,
            outcome=outcome,
            detail=assessment.reason,
            landing_verified=False,
            target_page_name=scene.page_name,
            committed=False,
            evidence=evidence,
        )
    else:
        host.graph.update_action_event(
            pending.event_index, evidence=evidence)
        host.graph.add_transition(
            pending.source.state_id,
            scene.state_id,
            pending.primitive,
            element_id=source_element_uid,
            element_label=corrected_target,
            semantic_description=pending.reason,
            region=source_region,
            effect_verdict=outcome,
            effect_note=assessment.reason,
            landing_verified=True,
            target_page_name=scene.page_name,
            event_index=pending.event_index,
            transition_kind="autonomous_observed",
            effect_kind=(
                "transition" if assessment.outcome == "changed"
                else "no_effect"
            ),
        )
    history[pending.history_index].update({
        "target": corrected_target,
        "outcome": outcome,
        "detail": assessment.reason,
        "landed_screen": scene.page_name,
        "pixel_changed": pixel_changed,
        "after_screenshot": after_path,
    })


def _settle_pending_action(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    scene: ObservedScene,
    fallback_assessment: PreviousAssessment,
    history: List[Dict[str, Any]],
    *,
    identity_issue: str,
) -> bool:
    """Commit one pending action after Qwen observes its fresh landing."""
    assessment = pending.assessment or fallback_assessment
    source_page = pending.source.page_name
    action_name = str(pending.primitive.get("action_type") or "")
    reviewed_target = _reviewed_pending_target(pending)
    action_target = reviewed_target or pending.target
    visible_effect = str(
        getattr(assessment, "visible_effect", "") or "").strip().casefold()
    owner_local_effect = visible_effect in {
        "owner_structure", "owner_state",
    }
    owner_state_effect = any(
        effect.scope_type == "owner_region"
        and effect.change_kind == "state"
        for effect in assessment.effects
    )
    explicit_region_effects = bool(assessment.effects) and all(
        effect.scope_type in {"owner_region", "region"}
        for effect in assessment.effects
    )
    owner_local_effect = owner_local_effect or any(
        effect.scope_type == "owner_region"
        and effect.change_kind in {"structure", "state"}
        for effect in assessment.effects
    )
    exact_no_effect_probe = bool(
        pending.entry_action_id
        and pending.validated_action is not None
        and pending.validated_action.purpose == "entry_attempt"
        and reviewed_target
        and assessment.outcome == "no_visible_change"
        and not assessment.matches_intent
        and (
            pending.source.screenshot == scene.screenshot
            or assessment.failure_kind in {
                "temporarily_unavailable", "not_interactive",
            }
        )
    )
    region_probe_action = bool(
        pending.evidence.get("region_probe_task") is True
        and str(pending.evidence.get("source_region_ref") or "")
    )
    exact_region_no_effect = bool(
        region_probe_action and reviewed_target
        and assessment.outcome == "no_visible_change"
    )
    settled_no_change_scroll = bool(
        pending.validated_action is not None
        and pending.validated_action.operation == "scroll"
        and assessment.outcome == "no_visible_change"
        and pending.source.screenshot == scene.screenshot
    )
    if (
        assessment.outcome == "changed"
        and pending.source.screenshot != scene.screenshot
    ):
        host.entry_review_evidence_generation += 1
        host.region_review_screenshots.clear()
        before_region_state = host.region_states.get(_page_key(source_page))
        before_regions = (
            before_region_state.snapshot().get("regions") or []
            if before_region_state is not None else []
        )
        if before_regions and not (
            pending.entry_action_id
            and (owner_local_effect or explicit_region_effects)
            and _page_key(source_page) == _page_key(scene.page_name)
        ):
            host.pending_region_mapping_context = {
                "before_screenshot": pending.source.screenshot,
                "after_screenshot": scene.screenshot,
                "before_page": source_page,
                "after_page": scene.page_name,
                "before_regions": deepcopy(before_regions),
                "action": {
                    "purpose": (
                        pending.validated_action.purpose
                        if pending.validated_action is not None else ""
                    ),
                    "operation": (
                        pending.validated_action.operation
                        if pending.validated_action is not None else action_name
                    ),
                    "target": action_target,
                    "parameters": (
                        dict(pending.validated_action.arguments)
                        if pending.validated_action is not None else {}
                    ),
                },
                "event_index": pending.event_index,
            }
    _commit_pending(
        host, pending, scene, assessment, history,
        actual_target=action_target,
        record_transition=not exact_no_effect_probe,
    )
    if region_probe_action:
        _record_region_probe_attempt(host, pending)
    if exact_no_effect_probe or exact_region_no_effect:
        host.graph.append_effect_observation(
            pending.event_index, {
                "effect_kind": "no_effect",
                "observed_changes": [],
                "parameter_bindings": {},
                "verdict": "refuted",
                "reason": assessment.reason,
            })
    elif assessment.business_effect is not None:
        business_effect = assessment.business_effect
        source_region_ref = str(
            pending.evidence.get("source_region_ref") or "").strip()
        source_region_state = host.region_states.get(_page_key(source_page))
        effect_region = (
            source_region_state.region(business_effect.region_name)
            if source_region_state is not None else None
        )
        effect_region_ref = host.region_registry.region_ref(
            source_page, business_effect.region_name)
        if (
            (pending.entry_action_id or region_probe_action)
            and _page_key(scene.page_name) == _page_key(source_page)
            and source_region_ref
            and effect_region_ref
            and effect_region is not None
            and str(effect_region.get("region_ref") or "")
            == effect_region_ref
            and assessment.matches_intent
            and assessment.outcome == "changed"
            and pending.source.screenshot != scene.screenshot
        ):
            host.graph.append_effect_observation(
                pending.event_index, {
                    "capability_name": business_effect.capability_name,
                    "reason": assessment.reason,
                    "effect_kind": business_effect.effect_kind,
                    "observed_changes": [{
                        "scope": {"region_ref": effect_region_ref},
                        "fact": business_effect.fact,
                        "before": business_effect.before_value,
                        "after": business_effect.after_value,
                    }],
                    "parameter_bindings": business_effect.parameter_bindings,
                    "predicate_candidate": (
                        f"{business_effect.fact} visibly changed from "
                        f"{business_effect.before_value} to "
                        f"{business_effect.after_value}."
                    ),
                    "verdict": "supported",
                })
    if pending.validated_action is not None:
        moved = pending.source.screenshot != scene.screenshot
        result = build_action_result(
            pending.validated_action,
            before_frame_id=(
                pending.before_frame_id
                or screenshot_frame_id(pending.source.screenshot)
            ),
            after_frame_id=screenshot_frame_id(scene.screenshot),
            moved=(moved if pending.validated_action.operation == "scroll"
                   else None),
            position_hint=(
                "frame_changed" if moved else "no_frame_change"
            ) if pending.validated_action.operation == "scroll" else "",
        )
        history[pending.history_index]["action_tool_result"] = result.to_dict()
    if pending.entry_action_id:
        entry_record = host.entry_ledger.finish_action(
            pending.entry_action_id,
            action_executed=True,
            outcome_verified=(
                assessment.matches_intent
                and not exact_no_effect_probe
                and assessment.outcome in {
                    "changed", "no_visible_change",
                }
            ),
            result=assessment.reason,
            destination_page=scene.page_name,
            destination_state_id=scene.state_id,
        )
        _apply_scope_effects(
            host, pending, scene, assessment, history,
            entry_record=entry_record,
        )
        same_operation_ids = (
            list(assessment.business_effect.same_operation_entry_ids)
            if assessment.business_effect is not None else []
        )
        if same_operation_ids:
            same_operation_issue = ""
            business_effect = assessment.business_effect
            source_region_ref = str(
                pending.evidence.get("source_region_ref") or "").strip()
            source_region_state = host.region_states.get(
                _page_key(source_page))
            effect_region = (
                source_region_state.region(business_effect.region_name)
                if source_region_state is not None else None
            )
            effect_region_ref = host.region_registry.region_ref(
                source_page, business_effect.region_name)
            if not (
                entry_record.status.value == "verified"
                and assessment.outcome == "changed"
                and assessment.matches_intent
                and pending.source.screenshot != scene.screenshot
                and pending.evidence.get("explicit_entry_task") is True
                and _page_key(source_page) == _page_key(scene.page_name)
                and (visible_effect == "owner_state" or owner_state_effect)
                and _page_key(business_effect.region_name)
                == _page_key(entry_record.region_name)
                and source_region_ref
                and source_region_ref == entry_record.owner_region_ref
                and effect_region_ref == source_region_ref
                and effect_region is not None
                and str(effect_region.get("region_ref") or "")
                == effect_region_ref
            ):
                same_operation_issue = (
                    "same-operation coverage requires one verified changed "
                    "entry result confined to its owner Region"
                )
            else:
                try:
                    covered_entries = host.entry_ledger.cover_same_operation(
                        entry_record.entry_id,
                        entry_ids=same_operation_ids,
                        reason=business_effect.same_operation_reason,
                    )
                except (KeyError, ValueError) as exc:
                    same_operation_issue = str(exc)
                else:
                    history.append({
                        "kind": "same_operation_coverage",
                        "screen": scene.page_name,
                        "region_name": entry_record.region_name,
                        "source_entry_id": entry_record.entry_id,
                        "covered_entry_ids": [
                            item.entry_id for item in covered_entries
                        ],
                        "outcome": "inferred",
                        "detail": business_effect.same_operation_reason,
                    })
            if same_operation_issue:
                history.append({
                    "kind": "same_operation_coverage",
                    "screen": scene.page_name,
                    "region_name": entry_record.region_name,
                    "source_entry_id": entry_record.entry_id,
                    "covered_entry_ids": same_operation_ids,
                    "outcome": "rejected",
                    "detail": same_operation_issue,
                })
        local_transition = None
        if (
            not assessment.effects
            and
            owner_local_effect
            and assessment.matches_intent
            and assessment.outcome == "changed"
            and pending.source.screenshot != scene.screenshot
            and _page_key(source_page) == _page_key(scene.page_name)
        ):
            action_attempt = host.graph.action_attempt(pending.event_index)
            local_transition = host.region_registry.record_local_transition(
                page_name=source_page,
                region_name=entry_record.region_name,
                source_state_id=pending.source.state_id,
                destination_state_id=scene.state_id,
                trigger_entry_id=entry_record.entry_id,
                effect_text=assessment.reason,
                effect_kind=(
                    "structure" if visible_effect == "owner_structure"
                    else "state"),
                evidence_action_id=str(
                    action_attempt.get("attempt_id")
                    or pending.event_index),
            )
            if local_transition is not None:
                if visible_effect == "owner_state":
                    host.entry_ledger.inherit_region_state_entries(
                        region_ref=entry_record.owner_region_ref,
                        source_state_ref=str(
                            local_transition.get("from_state_ref") or ""),
                        destination_state_ref=str(
                            local_transition.get("to_state_ref") or ""),
                    )
                history.append({
                    "kind": "region_state_transition",
                    "screen": scene.page_name,
                    "entry_id": entry_record.entry_id,
                    "region_name": entry_record.region_name,
                    "outcome": visible_effect,
                    "detail": assessment.reason,
                })
        if exact_no_effect_probe:
            no_effect_classification = (
                assessment.failure_kind or "observed_no_visible_change"
            )
            entry_record = host.entry_ledger.mark_no_effect_probe(
                entry_record.entry_id,
                result=(
                    assessment.reason
                    or "The requested target was activated, but the visible "
                       "interface did not change."
                ),
                classification=no_effect_classification,
            )
            history.append({
                "kind": "entry_probe",
                "screen": scene.page_name,
                "entry_id": entry_record.entry_id,
                "target": action_target,
                "outcome": "no_effect_observed",
                "classification": no_effect_classification,
                "detail": entry_record.last_result,
            })
        elif (
            assessment.outcome == "no_visible_change"
            and assessment.matches_intent
        ):
            history.append({
                "kind": "entry_probe",
                "screen": scene.page_name,
                "entry_id": entry_record.entry_id,
                "target": action_target,
                "outcome": "explored_no_visible_effect",
                "detail": entry_record.last_result,
            })
        elif not assessment.matches_intent:
            detail = (
                f"Reviewer-confirmed target {action_target!r} was executed "
                f"for entry {entry_record.entry_id}, but the main Agent "
                "judged that the visible result did not satisfy the entry. "
                "The real action evidence was kept, but this entry remains "
                "unresolved."
            )
            history.append({
                "kind": "previous_action_feedback",
                "screen": scene.page_name,
                "target": entry_record.target,
                "entry_id": entry_record.entry_id,
                "outcome": "entry_not_verified",
                "detail": detail,
                "rejection": _rejection_feedback(
                    "action_did_not_match_entry",
                    detail,
                    retry_after=(
                        "the entry description or visible target has been "
                        "corrected"
                    ),
                    correction=(
                        "Keep the Reviewer-bound target fixed. Reassess "
                        "whether the visible result was caused by and "
                        "satisfies that target. During discovery, an unknown "
                        "or shared destination is not a mismatch; do not "
                        "predict a destination from the target name or infer "
                        "another activated control from the landing Page."
                    ),
                ),
            })
        elif (
            assessment.outcome == "changed"
            and pending.source.screenshot != scene.screenshot
            and pending.evidence.get("explicit_entry_task") is True
            and _page_key(source_page) == _page_key(scene.page_name)
        ):
            if not assessment.effects and visible_effect != "owner_state":
                _request_same_page_resurvey(
                    host,
                    history,
                    page_name=scene.page_name,
                    entry_id=entry_record.entry_id,
                    target=action_target,
                    reason=assessment.reason,
                    region_name=(
                        entry_record.region_name
                        if visible_effect == "owner_structure" else ""),
                    region_ref=(
                        entry_record.owner_region_ref
                        if visible_effect == "owner_structure" else ""),
                    occurrence_ref=(
                        entry_record.representative_occurrence_ref
                        if visible_effect == "owner_structure" else ""),
                )
        _record_agent_inferred_edges(host)
    elif assessment.effects:
        _apply_scope_effects(
            host, pending, scene, assessment, history,
            entry_record=None,
        )
    if assessment.outcome == "changed" and source_page != scene.page_name:
        if identity_issue:
            host.pending_connection = {
                "source": source_page,
                "action": action_name,
                "control": action_target,
            }
        else:
            host.protocol_map.connect(
                source_page, scene.page_name, action_name, action_target)
    return settled_no_change_scroll


def _close_unverified_pending_action(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    history: List[Dict[str, Any]],
    *,
    detail: str,
) -> None:
    """Preserve an executed action whose assessment could not be accepted."""
    host.graph.update_action_event(
        pending.event_index,
        outcome="assessment_unavailable",
        detail=detail,
        landing_verified=False,
        committed=False,
    )
    if 0 <= pending.history_index < len(history):
        history[pending.history_index].update({
            "outcome": "assessment_unavailable",
            "detail": detail,
        })
    if pending.entry_action_id:
        entry_record = host.entry_ledger.finish_action(
            pending.entry_action_id,
            action_executed=True,
            outcome_verified=False,
            result=detail,
        )
        entry_record.task_eligible = False
    history.append({
        "kind": "pending_action_unverified",
        "screen": pending.source.page_name,
        "action": str(pending.primitive.get("action") or ""),
        "target": pending.target,
        "outcome": "assessment_unavailable",
        "detail": detail,
        "entry_action_id": pending.entry_action_id or None,
    })
