"""Model-led screenshot exploration without the guided traversal pipeline."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import asdict, replace
from typing import Any, Dict, List, Optional

from .autonomous_agent import (
    ENTRY_REVIEW_ATTEMPT_LIMIT,
    CodexAutonomousAgent,
)
from .autonomous_qwen import QwenAutonomousAgent
from .autonomous_recovery import (
    _handle_outside_target_app,
    _interruption_plan,
)

from .autonomous_action_execution import (
    _capture_pending_assessment,
    _close_unverified_pending_action,
    _convert_action_tool,
    _prepare_action_attempt,
    _primitive,
    _settle_pending_action,
)
from .autonomous_region_tools import screenshot_frame_id
from .autonomous_context import (
    _arrival_context_view,
    _exploration_map_view,
    _identity_stage,
    _latest_gui_action_context,
    _region_state,
    _stage_signature,
)
from .autonomous_entry_review import (
    _entry_review_key,
    _entry_review_region_names,
    _reuse_entry_result,
    _review_entry_record,
    _review_registered_entry_dispute,
)
from .autonomous_entry_commit import (
    _apply_entry_review,
    _stage_main_agent_page_update,
)
from .autonomous_page_commit import _apply_main_agent_page_update
from .autonomous_page_update import (
    _commit_landing_variant,
    _page_identity_feedback,
    _pending_tool_view,
    _reject_no_change_identity_conflict,
    _review_page_identity,
    _region_review_required,
    _review_region_proposal,
    _select_landing_page,
)
from .autonomous_prompt import (
    _invalid_turn_correction,
    _rejection_feedback,
    _stage_incomplete_no_action_detail,
)
from .autonomous_protocol import available_tool_catalog
from .autonomous_completion import (
    _bind_history_records_to_task,
    _completion_gaps,
    _completion_summary,
    _rejection_progress_token,
    _update_rejection_boundary,
)
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _apply_target_edge_scope,
    _checkpoint,
    _current_page_state_id,
    _register_scene,
    _target_edge_terminal_result,
)
from .autonomous_scheduling import (
    _complete_region_task_from_no_action,
    _covered_entry_click_issue,
    _defer_current_task,
    _defer_action_after_stage_transition,
    _dynamic_tool_catalog,
    _region_probe_action_issue,
    _repeat_task_frame_record_error_issue,
    _repeat_wait_issue,
    _survey_entry_click_issue,
    _sync_exploration_task,
)

from .autonomous_turn import (
    AutonomousDecision,
    AutonomousTurn,
    EntryReview,
    ObservedScene,
    PageUpdate,
    PendingAction,
    PendingPageIdentity,
    _exploration_task_key,
    _page_key,
    _parse_entry_review,
)


def _normalize_variant_named_page(
    host: AutonomousTraversalRuntime,
    turn: AutonomousTurn,
    history: List[Dict[str, Any]],
    *,
    identity_stage: str,
) -> AutonomousTurn:
    """Map one uniquely known Variant name back to its owning Page."""
    if (
        identity_stage != "page"
        or turn.registration.identity != "known"
    ):
        return turn
    requested = str(
        turn.registration.matched_page_name or turn.screen_name or ""
    ).strip()
    if not requested or host.protocol_map.canonical_page_name(requested):
        return turn
    owner = host.protocol_map.unique_variant_owner(requested)
    if not owner:
        return turn
    history.append({
        "kind": "page_identity_normalized",
        "screen": owner,
        "outcome": "variant_name_mapped_to_owner_page",
        "reported_name": requested,
        "detail": (
            f"Known Variant {requested!r} uniquely belongs to Page {owner!r}; "
            "the Page stage kept the registered Page/Variant layers separate."
        ),
    })
    return replace(
        turn,
        screen_name=owner,
        registration=replace(
            turn.registration,
            matched_page_name=owner,
        ),
    )


logger = logging.getLogger(__name__)


def _active_previous_entry_review(
    pending: Dict[str, Any],
) -> Dict[str, Any]:
    """Project prior discussion only for candidates still under review."""
    previous = pending.get("previous_review")
    if not isinstance(previous, dict) or not previous:
        return {}
    active_keys = {
        _entry_review_key(item)
        for item in pending.get("candidates") or []
        if isinstance(item, dict)
    }
    projected = deepcopy(previous)
    retained = False
    for field_name in ("kept", "added", "dropped", "deferred"):
        items = [
            deepcopy(item) for item in previous.get(field_name) or []
            if isinstance(item, dict)
            and _entry_review_key(item) in active_keys
        ]
        projected[field_name] = items
        retained = retained or bool(items)
    return projected if retained else {}


def _entry_review_decision_payload(payload: Any) -> Any:
    """Return only state-bearing Reviewer output for direct retry comparison."""
    if not isinstance(payload, dict):
        return deepcopy(payload)
    return {
        field_name: deepcopy(payload.get(field_name))
        for field_name in (
            "independent_entries", "record_only_entries",
            "non_task_entries", "deferred_entries", "deferred_regions",
            "reason_consistent",
        )
        if field_name in payload
    }


def _review_pending_entries(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    history: List[Dict[str, Any]],
) -> str:
    """Replace the main review turn with one stateless Entry Reviewer call."""
    pending = host.pending_entry_review
    if not isinstance(pending, dict):
        return ""
    reviewer = host.entry_reviewer
    if not callable(reviewer):
        reason = "independent Entry Reviewer is unavailable"
        history.append({
            "kind": "entry_review_result",
            "screen": str(pending.get("page_name") or ""),
            "status": "rejected",
            "detail": reason,
            "rejection": _rejection_feedback(
                "entry_reviewer_unavailable",
                reason,
                retry_after="entry_reviewer_is_available",
            ),
        })
        return reason
    page_name = str(pending.get("page_name") or "").strip()
    state_id = str(pending.get("state_id") or "").strip()
    variant_name = str(pending.get("variant_name") or "").strip()
    state_node: Dict[str, Any] = {}
    if state_id and state_id in host.graph.graph:
        state_node = dict(host.graph.graph.nodes[state_id])
    if not state_id:
        page_states = [
            (str(candidate_id), dict(node))
            for candidate_id, node in host.graph.graph.nodes(data=True)
            if _page_key(node.get("page_name")) == _page_key(page_name)
        ]
        if len(page_states) != 1:
            reason = (
                "Pending Entry review cannot identify the exact source "
                f"Page Variant: Page {page_name!r} has "
                f"{len(page_states)} candidate States. The stale review was "
                "discarded; re-observe that Page Variant before surveying "
                "its entries again."
            )
            host.pending_entry_review = None
            host.entry_review_screenshot = b""
            history.append({
                "kind": "entry_review_result",
                "screen": page_name,
                "status": "rejected",
                "detail": reason,
                "rejection": _rejection_feedback(
                    "entry_review_source_variant_ambiguous",
                    reason,
                    retry_after="page_variant_is_reobserved",
                ),
            })
            return reason
        state_id, state_node = page_states[0]
    if not variant_name:
        observed_facts = state_node.get("observed_facts") or {}
        variant_signature = state_node.get("variant_signature") or {}
        variant_name = str(
            observed_facts.get("variant_name")
            or variant_signature.get("variant_name")
            or ""
        ).strip()
        canonical_page = host.protocol_map.canonical_page_name(page_name)
        page = host.protocol_map.pages.get(canonical_page) or {}
        page_variants = list((page.get("variants") or {}).keys())
        if not variant_name and len(page_variants) == 1:
            variant_name = str(page_variants[0])
    coverage_audit_regions = [
        str(name).strip()
        for name in pending.get("coverage_audit_regions") or []
        if str(name).strip()
    ]
    audit_region_keys = {
        _page_key(name) for name in coverage_audit_regions
    }

    def in_current_audit(region_name: Any) -> bool:
        return (
            not audit_region_keys
            or _page_key(region_name) in audit_region_keys
        )

    expected_frame_id = str(pending.get("frame_id") or "").strip()

    def is_expected_frame(candidate: Any) -> bool:
        return bool(
            expected_frame_id
            and isinstance(candidate, bytes)
            and candidate
            and screenshot_frame_id(candidate) == expected_frame_id
        )

    review_screenshot = host.entry_review_screenshot
    if not is_expected_frame(review_screenshot):
        representative = host.protocol_map.representative_screenshot(
            page_name, variant_name)
        if is_expected_frame(representative):
            review_screenshot = representative
        elif is_expected_frame(screenshot):
            review_screenshot = screenshot
        else:
            reason = (
                "Pending Entry review lost the exact screenshot that produced "
                "its candidates; the stale review was discarded so the Region "
                "can be surveyed again."
            )
            host.pending_entry_review = None
            host.entry_review_screenshot = b""
            history.append({
                "kind": "entry_review_result",
                "screen": page_name,
                "status": "rejected",
                "detail": reason,
                "rejection": _rejection_feedback(
                    "entry_review_evidence_unavailable",
                    reason,
                    retry_after="region_is_resurveyed",
                ),
            })
            return reason

    request = {
        "current_screenshot": review_screenshot,
        "page_name": pending.get("page_name") or "",
        "main_agent_reason": pending.get("main_agent_reason") or "",
        "regions": deepcopy([
            item for item in pending.get("regions") or []
            if isinstance(item, dict)
            and in_current_audit(item.get("name"))
        ]),
        "candidates": deepcopy([
            item for item in pending.get("candidates") or []
            if isinstance(item, dict)
            and in_current_audit(item.get("region_name"))
        ]),
        "shared_region_entries": deepcopy([
            item for item in pending.get("shared_region_entries") or []
            if isinstance(item, dict)
            and in_current_audit(item.get("region_name"))
        ]),
        "known_entries": [
            {
                "entry_id": entry.entry_id,
                "region_name": entry.region_name,
                "target": entry.target,
                "operation": entry.operation or entry.target,
                "subject": entry.subject or entry.region_name,
            }
            for entry in host.entry_ledger.entries
            if _page_key(entry.page_name) == _page_key(pending.get("page_name"))
            and in_current_audit(entry.region_name)
        ],
        "coverage_audit_regions": deepcopy(coverage_audit_regions),
        "review_attempt": int(pending.get("review_attempt") or 1),
        "review_attempt_limit": int(
            pending.get("review_attempt_limit") or ENTRY_REVIEW_ATTEMPT_LIMIT),
        "previous_review": _active_previous_entry_review(pending),
        "previous_rejection": deepcopy(
            pending.get("previous_rejection") or {}),
    }
    retry_identity = {
        "page_name": page_name,
        "frame_id": expected_frame_id,
        "candidates": deepcopy(request["candidates"]),
        "coverage_audit_regions": deepcopy(coverage_audit_regions),
    }
    try:
        payload = reviewer(request)
    except Exception as exc:
        reason = (
            "独立 Entry Reviewer 本轮没有返回可用判断；候选 Entry 和覆盖"
            "状态均未写入正式账本。请根据同一截图重新复核。")
        history.append({
            "kind": "entry_review_result",
            "screen": str(pending.get("page_name") or ""),
            "status": "rejected",
            "detail": reason,
            "rejection": _rejection_feedback(
                "entry_reviewer_failed",
                reason,
                retry_after="entry_reviewer_returns_valid_output",
            ),
        })
        return reason
    decision_payload = _entry_review_decision_payload(payload)
    if (
        pending.get("previous_rejection")
        and getattr(host, "_last_rejected_entry_review", None) == {
            "identity": retry_identity,
            "decision": decision_payload,
        }
    ):
        host._last_rejected_entry_review = None
        history.append({
            "kind": "entry_review_retry_stopped",
            "screen": page_name,
            "status": "deferred",
            "detail": (
                "The Entry Reviewer repeated the same state-bearing invalid "
                "response after concrete feedback. The current candidates "
                "were deferred until new GUI evidence instead of retrying "
                "the unchanged request again."
            ),
        })
        scene = ObservedScene(
            state_id=state_id,
            screenshot=review_screenshot,
            page_name=page_name,
            variant_name=variant_name,
            is_new=False,
        )
        return _apply_entry_review(
            host,
            EntryReview(
                independent_entries=[],
                non_task_entries=[],
                deferred_entries=deepcopy(request["candidates"]),
                deferred_regions=deepcopy(coverage_audit_regions),
            ),
            scene,
            review_screenshot,
            history,
            reviewer_reason=(
                "复核器在收到具体纠正后仍重复同一无效分类；框架未写入入口或覆盖，"
                "只将当前候选推后到出现新界面证据时再审。"
            ),
            reason_consistent=True,
        )
    review_payload = ({
        "independent_entries": payload.get("independent_entries"),
        "record_only_entries": payload.get("record_only_entries"),
        "deferred_entries": payload.get("deferred_entries"),
        "deferred_regions": payload.get("deferred_regions"),
    } if isinstance(payload, dict) else payload)
    if isinstance(payload, dict) and "non_task_entries" in payload:
        review_payload["non_task_entries"] = payload.get("non_task_entries")
    review, parse_issue = _parse_entry_review(review_payload)
    if parse_issue:
        issue = _apply_entry_review(
            host, None, None, review_screenshot, history)
        if issue and host.pending_entry_review is pending:
            host._last_rejected_entry_review = {
                "identity": retry_identity,
                "decision": decision_payload,
            }
        return issue
    scene = ObservedScene(
        state_id=state_id,
        screenshot=review_screenshot,
        page_name=page_name,
        variant_name=variant_name,
        is_new=False,
    )
    issue = _apply_entry_review(
        host,
        review,
        scene,
        review_screenshot,
        history,
        reviewer_reason=str(payload.get("reason") or ""),
        reason_consistent=bool(payload.get("reason_consistent")),
    )
    if issue and host.pending_entry_review is pending:
        host._last_rejected_entry_review = {
            "identity": retry_identity,
            "decision": decision_payload,
        }
    elif not issue:
        host._last_rejected_entry_review = None
    return issue


def _dispatch_tool_call(
    host: AutonomousTraversalRuntime,
    turn: AutonomousTurn,
    screenshot: bytes,
    screen_name: str,
    history: List[Dict[str, Any]],
    *,
    page_identity_context: Optional[Dict[str, Any]] = None,
) -> None:
    decision = turn.decision
    identity_stage = str(
        (page_identity_context or {}).get("identity_stage") or "combined"
    ).strip().casefold()
    feedback = (
        host.identity_feedback if decision.tool_name == "page_identity" else None
    )
    if decision.tool_name == "reuse_entry_result":
        evidence = _reuse_entry_result(host, decision.tool_arguments)
    elif decision.tool_name == "review_entry_record":
        evidence = _review_entry_record(
            host,
            decision.tool_arguments,
            screenshot,
            history,
        )
    else:
        evidence = host.protocol_map.call_tool(
            decision.tool_name,
            decision.tool_arguments,
            screenshot,
            page_identity_resolver=host.identity_resolver,
            identity_feedback=feedback,
            page_identity_context=page_identity_context,
        )
    pending_review = evidence.status in {"known", "new"}
    if decision.tool_name == "report_record_error":
        current_page = host.protocol_map.current_page or screen_name
        evidence.data["current_page_unchanged"] = current_page
        error_kind = str(
            decision.tool_arguments.get("kind") or ""
        ).strip().casefold()
        if error_kind == "entry":
            entry_review = _review_registered_entry_dispute(
                host, decision.tool_arguments, screenshot, screen_name)
            evidence.data["entry_review"] = entry_review
            evidence.data["feedback"] = (
                str(evidence.data.get("feedback") or "").strip()
                + " " + str(entry_review.get("feedback") or "").strip()
            ).strip()
        if (
            error_kind == "page_identity"
        ):
            challenge_context = dict(page_identity_context or {})
            reopened_from_variant = bool(
                challenge_context.pop("_reopened_from_variant", False))
            disputed_staged_page = str(
                challenge_context.pop("_disputed_staged_page", "")
                or ""
            ).strip()
            dispute_context = {
                "observed_problem": str(
                    decision.tool_arguments.get("observed_problem") or ""),
            }
            if disputed_staged_page:
                dispute_context.update({
                    "disputed_staged_page": disputed_staged_page,
                    "trusted_source_page": current_page,
                })
                evidence.data["disputed_staged_page"] = disputed_staged_page
            else:
                dispute_context["framework_current_page"] = current_page
            challenge_context["page_identity_dispute"] = dispute_context
            recent_action = _latest_gui_action_context(history)
            if recent_action:
                challenge_context["recent_action"] = recent_action
            identity_arguments = {
                "suspected_pages": list(host.protocol_map.pages),
                "proposed_new_name": (
                    turn.screen_name
                    if (
                        not reopened_from_variant
                        and _page_key(turn.screen_name)
                        != _page_key(current_page)
                    )
                    else ""
                ),
                "reason": str(
                    decision.tool_arguments.get("observed_problem") or ""
                ),
            }
            identity_evidence = host.protocol_map.call_tool(
                "page_identity",
                identity_arguments,
                screenshot,
                page_identity_resolver=host.identity_resolver,
                page_identity_context=challenge_context,
            )
            identity_pending = identity_evidence.status in {"known", "new"}
            evidence.data["identity_review"] = {
                "status": identity_evidence.status,
                "data": dict(identity_evidence.data),
                "pending_review": identity_pending,
            }
            specialist_feedback = _page_identity_feedback(
                identity_evidence.status,
                identity_evidence.data,
                pending_review=identity_pending,
                stage=identity_stage,
            )
            evidence.data["feedback"] = (
                str(evidence.data.get("feedback") or "").strip()
                + " " + specialist_feedback
            ).strip()
            pending_review = identity_pending
            if identity_pending:
                host.pending_page_identity = PendingPageIdentity(
                    status=identity_evidence.status,
                    data=dict(identity_evidence.data),
                    arguments=identity_arguments,
                    stage=identity_stage,
                )
    if decision.tool_name == "page_identity":
        host.identity_feedback = None
        evidence.data["feedback"] = _page_identity_feedback(
            evidence.status,
            evidence.data,
            pending_review=evidence.status in {"known", "new"},
            stage=identity_stage,
        )
        if evidence.status in {"known", "new"}:
            host.pending_page_identity = PendingPageIdentity(
                status=evidence.status,
                data=dict(evidence.data),
                arguments=dict(decision.tool_arguments),
                stage=identity_stage,
            )
    host.tool_images = list(evidence.images)
    host.tool_image_labels = list(evidence.image_labels)
    history.append({
        "kind": "tool",
        "screen": screen_name,
        "frame_id": screenshot_frame_id(screenshot),
        "tool_name": decision.tool_name,
        "tool_arguments": dict(decision.tool_arguments),
        "tool_result": {
            "status": evidence.status,
            "data": evidence.data,
            "attached_images": list(evidence.image_labels),
            "pending_review": pending_review,
        },
        "exploration_task": (
            asdict(host.exploration_task) if host.exploration_task else None),
        "exploration_task_id": (
            host.exploration_task.task_id if host.exploration_task else ""),
        "outcome": evidence.status,
    })


def _review_click(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    decision: AutonomousDecision,
) -> tuple[bool, Dict[str, Any]]:
    if not callable(host.click_reviewer):
        return True, {"status": "not_configured", "offline_only": True}
    request = {
        "current_screenshot": screenshot,
        "target": decision.target,
        "point_1000": list(decision.point_1000 or []),
        "purpose": decision.purpose,
        "agent_reason": decision.reason,
        "operation": str(
            decision.tool_arguments.get("operation")
            or decision.action
            or "click"
        ).strip().casefold(),
    }
    task = host.exploration_task
    if task is not None:
        request["current_task"] = {
            "task_type": task.task_type,
            "page_name": task.page_name,
            "region_name": task.region_name,
            "target": task.target,
            "goal": task.goal,
            "phase": task.phase,
        }
    if decision.action == "INPUT_TEXT":
        request["requested_text"] = str(
            decision.tool_arguments.get("text") or "")
    entry_id = str(decision.tool_arguments.get("entry_id") or "").strip()
    if entry_id:
        try:
            entry = host.entry_ledger.get(entry_id)
        except KeyError:
            pass
        else:
            request["requested_entry"] = {
                "page_name": entry.page_name,
                "region_name": entry.region_name,
                "target": entry.target,
                "operation": entry.operation or entry.target,
                "subject": entry.subject or entry.region_name,
                "control_type": entry.control_type,
                "current_value": entry.current_value,
            }
    try:
        result = host.click_reviewer(request)
    except Exception as exc:
        return False, {
            "decision": "uncertain",
            "risk": "uncertain",
            "reason": "独立 Click Reviewer 本轮没有返回可用判断，因此没有批准点击。",
        }
    if not isinstance(result, dict):
        return False, {
            "decision": "uncertain", "risk": "uncertain",
            "reason": "click reviewer returned a non-object result",
        }
    if not str(result.get("reason") or "").strip():
        return False, {
            "decision": "uncertain", "risk": "uncertain",
            "reason": "click reviewer returned no non-empty reason",
        }
    decision_name = str(result.get("decision") or "").strip().casefold()
    risk = str(result.get("risk") or "").strip().casefold()
    approved = (
        decision_name == "approve"
        and result.get("point_matches_target") is True
        and result.get("target_matches_request") is True
        and risk == "safe"
    )
    return approved, dict(result)


def _execute_pre_registration_interruption(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    decision: AutonomousDecision,
    history: List[Dict[str, Any]],
    *,
    pending: Optional[PendingAction],
    screen_name: str,
    source_page: str,
) -> Optional[Dict[str, Any]]:
    """Execute reviewed recovery without registering the obstructed frame."""
    click_review: Dict[str, Any] = {}
    if decision.action == "CLICK":
        approved, click_review = _review_click(host, screenshot, decision)
        if not approved:
            detail = str(
                click_review.get("reason")
                or "independent click review rejected the interruption target"
            )
            history.append({
                "kind": "click_review",
                "screen": screen_name,
                "action": decision.action,
                "target": decision.target,
                "outcome": "not_executed",
                "detail": detail,
                "review": click_review,
                "pre_registration_recovery": True,
                "rejection": _rejection_feedback(
                    "click_review_rejected", detail),
            })
            return None
    primitive = _primitive(host, screenshot, decision)
    if primitive is None:
        history.append({
            "kind": "action",
            "screen": screen_name,
            "action": decision.action,
            "target": decision.target,
            "outcome": "not_executed",
            "detail": "the interruption action could not be converted",
            "pre_registration_recovery": True,
        })
        return None
    try:
        observation = host.env.step(primitive, pause=2.0)
        if not (observation or {}).get("screenshot"):
            observation = host.fresh_observation(observation or {})
    except Exception as exc:
        history.append({
            "kind": "action",
            "screen": screen_name,
            "action": decision.action,
            "target": decision.target,
            "outcome": "execution_error",
            "detail": str(exc)[:500],
            "pre_registration_recovery": True,
        })
        return None
    frame_changed = bool(
        (observation or {}).get("screenshot")
        and observation["screenshot"] != screenshot
    )
    if frame_changed:
        host.pending_page_identity = None
        host.pending_landing_page = None
        host.identity_feedback = None
        host.protocol_map.current_page = ""
        host.protocol_map.current_variant = ""
        if pending is not None:
            pending.assessment = None
            pending.evidence.pop("first_model_assessment", None)
    host.action_count += 1
    history.append({
        "kind": "action",
        "screen": screen_name,
        "source_page": source_page,
        "action": decision.action,
        "target": decision.target,
        "purpose": decision.purpose,
        "reason": decision.reason,
        "outcome": "executed",
        "pre_registration_recovery": True,
        "obstructed_frame_registered": False,
        "frame_changed": frame_changed,
        "semantic_graph_recorded": False,
        "click_review": click_review,
    })
    return observation


def run_autonomous_traversal(
    host: AutonomousTraversalRuntime,
    initial_obs: Dict[str, Any],
):
    """Let the model observe, assess and choose from full screenshots."""
    observation = initial_obs
    history: List[Dict[str, Any]] = list(host.resume_history)
    pending: Optional[PendingAction] = None
    decisions = 0
    rejection_history_cursor = len(history)
    rejection_progress_token = _rejection_progress_token(host)
    host.audit_fixture(None, "initial")

    while True:
        screenshot = (observation or {}).get("screenshot")
        if not screenshot:
            host.graph.stop_reason = "observation_unavailable"
            break
        turn_records = history[rejection_history_cursor:]
        _bind_history_records_to_task(
            turn_records, host.exploration_task)
        current_progress_token = _rejection_progress_token(host)
        should_stop = _update_rejection_boundary(
            host,
            history,
            turn_records,
            progress_made=(current_progress_token != rejection_progress_token),
            pending_action=pending is not None,
        )
        rejection_history_cursor = len(history)
        rejection_progress_token = current_progress_token
        if should_stop:
            if pending is not None:
                _close_unverified_pending_action(
                    host,
                    pending,
                    history,
                    detail=(
                        "The GUI action was executed, but repeated rejected "
                        "Agent turns left its landing unverified."
                    ),
                )
            break
        app_scope_status, recovered_observation = _handle_outside_target_app(
            host, pending, history, screenshot)
        if app_scope_status == "stopped":
            break
        if app_scope_status == "recovered":
            observation = recovered_observation or observation
            pending = None
            host.pending_landing_page = None
            _checkpoint(host, history)
            continue
        if app_scope_status == "needs_review":
            task = host.exploration_task
            task_view = {
                "task_id": task.task_id if task is not None else "",
                "type": task.task_type if task is not None else "survey_page",
                "phase": "resolve_app_scope",
            }
            if task is not None:
                task_view.update({
                    "page": task.page_name,
                    "region": task.region_name,
                    "entry_id": task.entry_id,
                    "target": task.target,
                })
            scope_view: Dict[str, Any] = {
                "task": task_view,
                "app_scope_check": {
                    "system_result": "窗口归属暂时无法确认",
                    "question": "当前前景是否仍属于目标应用？",
                },
            }
            reference_images: List[bytes] = []
            reference_labels: List[str] = []
            if (
                pending is not None
                and pending.source.screenshot
                and pending.source.screenshot != screenshot
            ):
                reference_images.append(pending.source.screenshot)
                reference_labels.append(
                    "最近一次已确认属于目标应用的动作前完整截图"
                )
                scope_view["app_scope_check"]["recent_action"] = {
                    "operation": (
                        pending.validated_action.operation
                        if pending.validated_action is not None
                        else str(pending.primitive.get("action_type") or "")
                    ),
                    "target": pending.target,
                }
            scope_catalog = [
                item for item in available_tool_catalog(
                    pending_identity=False)
                if item.get("name") == "report_app_scope"
            ]
            scope_turn = host.decision_agent.decide(
                screenshot,
                history,
                app_name=host.app_name,
                platform=host.platform,
                actions_used=host.action_count,
                max_actions=host.max_actions,
                exploration_map=scope_view,
                tool_images=reference_images,
                tool_image_labels=reference_labels,
                tool_catalog=scope_catalog,
            )
            decisions += 1
            classification = "uncertain"
            reason = str(
                getattr(host.decision_agent, "last_error", "")
                or "主 Agent 没有返回可用的窗口归属判断。"
            )[:500]
            if (
                scope_turn is not None
                and scope_turn.decision.action == "CALL_TOOL"
                and scope_turn.decision.tool_name == "report_app_scope"
            ):
                classification = str(
                    scope_turn.decision.tool_arguments.get(
                        "classification") or "uncertain"
                ).strip().casefold()
                reason = scope_turn.decision.reason
                if classification not in {
                    "target_app", "target_app_obstructed",
                    "external_app", "uncertain",
                }:
                    classification = "uncertain"
            history.append({
                "kind": "app_scope_resolution",
                "frame_id": screenshot_frame_id(screenshot),
                "outcome": classification,
                "detail": reason,
                "exploration_task_id": (
                    task.task_id if task is not None else ""
                ),
                "semantic_graph_recorded": False,
            })
            _checkpoint(host, history)
            continue
        current_frame_id = screenshot_frame_id(screenshot)
        current_region_key = _page_key(host.protocol_map.current_page) or "__unbound__"
        for page_key, state in list(host.region_states.items()):
            if page_key != current_region_key:
                continue
            state.observe_frame(
                current_frame_id, _current_page_state_id(host))
        if (host.max_actions > 0
                and pending is None
                and host.pending_entry_review is None
                and not _identity_stage(host, pending)
                and host.action_count >= host.max_actions):
            host.graph.stop_reason = "max_actions"
            break
        identity_required = bool(_identity_stage(host, pending))
        if pending is None and not identity_required:
            _sync_exploration_task(host)
        if (
            pending is None
            and host.graph.stop_reason == "all_remaining_work_suspended"
        ):
            history.append({
                "kind": "traversal_stopped",
                "outcome": "all_remaining_work_suspended",
                "detail": (
                    "every remaining survey, Entry, or Region-probe task "
                    "reached the shared per-task rejection limit"
                ),
            })
            break
        if (
            pending is None
            and host.exploration_task is None
            and not identity_required
        ):
            gaps = _completion_gaps(host)
            history.append({
                "kind": "framework_completion",
                "outcome": "complete" if not gaps else "partial",
                "remaining": gaps,
                "detail": (
                    "The framework found no open exploration task."
                    if not gaps else
                    "No runnable task remains, but evidence gaps are still open."
                ),
            })
            host.graph.stop_reason = (
                "framework_complete" if not gaps else "framework_partial"
            )
            break
        identity_stage = _identity_stage(host, pending)
        stage_before_turn = _stage_signature(host, pending)
        if stage_before_turn[0] == "review_entries":
            decisions += 1
            review_task = host.exploration_task
            review_history_start = len(history)
            _review_pending_entries(host, screenshot, history)
            _bind_history_records_to_task(
                history[review_history_start:], review_task)
            _sync_exploration_task(host)
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        tool_catalog = _dynamic_tool_catalog(
            host,
            screenshot,
            history,
            identity_stage=identity_stage,
        )
        exploration_view = _exploration_map_view(
            host, pending, current_screenshot=screenshot)
        previous_screenshot = (
            pending.source.screenshot
            if pending is not None and pending.assessment is None else None
        )

        turn_tool_images = list(host.tool_images)
        turn_tool_image_labels = list(host.tool_image_labels)
        current_page_key = _page_key(host.protocol_map.current_page)
        fixed_region_review = host.region_review_screenshots.get(
            current_page_key)
        if (
            fixed_region_review
            and fixed_region_review != screenshot
            and "page_update" in (
                host.page_update_corrections.get(current_page_key) or {})
        ):
            turn_tool_images.append(fixed_region_review)
            turn_tool_image_labels.append(
                "本次区域讨论首次提案的固定完整证据截图；区域修订以此图为准"
            )

        turn = host.decision_agent.decide(
            screenshot,
            history,
            app_name=host.app_name,
            platform=host.platform,
            actions_used=host.action_count,
            max_actions=host.max_actions,
            previous_screenshot=previous_screenshot,
            exploration_map=exploration_view,
            tool_images=turn_tool_images,
            tool_image_labels=turn_tool_image_labels,
            pending_identity=_pending_tool_view(host),
            tool_catalog=tool_catalog,
        )
        if turn is not None:
            host.tool_images = []
            host.tool_image_labels = []
        decisions += 1
        if turn is None:
            model_error = str(
                getattr(host.decision_agent, "last_error", "")
                or "The model did not return a valid Agent turn."
            )[:500]
            model_error_kind = str(
                getattr(host.decision_agent, "last_error_kind", "")
                or ""
            )[:40]
            correction = _invalid_turn_correction(
                model_error=model_error,
                model_error_kind=model_error_kind,
            )
            history.append({
                "kind": "model_error",
                "decision": decisions,
                "outcome": "invalid_agent_turn",
                "detail": model_error,
                "rejection": _rejection_feedback(
                    "invalid_agent_turn",
                    model_error,
                    retry_after="response_matches_current_tool_catalog",
                    correction=correction,
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        if not _capture_pending_assessment(
                pending, turn, screenshot, history):
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        turn = _normalize_variant_named_page(
            host, turn, history, identity_stage=identity_stage)

        decision = turn.decision
        interruption_call = (
            decision.action == "CALL_TOOL"
            and decision.tool_name == "handle_interruption"
        )
        reported_page = host.protocol_map.canonical_page_name(
            turn.registration.matched_page_name)
        reported_variant = (
            host.protocol_map.canonical_variant_name(
                reported_page, turn.registration.variant_name)
            if turn.registration.variant_identity == "known"
            else turn.registration.variant_name
            if turn.registration.variant_identity == "new"
            else ""
        )
        settlement_page = (
            reported_page
            or (
                turn.screen_name
                if turn.registration.identity in {"known", "new"} else ""
            )
        )
        if not interruption_call and _reject_no_change_identity_conflict(
            pending,
            turn,
            settlement_page,
            reported_variant,
            history,
            compare_variant=identity_stage != "page",
        ):
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        identity_tool_call = (
            decision.action == "CALL_TOOL"
            and decision.tool_name == "page_identity"
        )
        identity_dispute_call = (
            decision.action == "CALL_TOOL"
            and decision.tool_name == "report_record_error"
            and str(decision.tool_arguments.get("kind") or "")
            .strip().casefold() == "page_identity"
        )
        identity_resolution_call = identity_tool_call or identity_dispute_call
        registration_deferral_call = (
            identity_resolution_call
            or (interruption_call and identity_stage in {"page", "variant"})
        )
        current_page = host.protocol_map.current_page
        current_variant = host.protocol_map.current_variant
        unreviewed_variant_proposal = bool(
            host.pending_page_identity is None
            and turn.registration.identity == "known"
            and turn.registration.variant_identity == "new"
            and not registration_deferral_call)
        semantic_identity_conflict = bool(
            not identity_stage
            and pending is None
            and host.pending_page_identity is None
            and current_page
            and not registration_deferral_call
            and (
                turn.registration.identity != "known"
                or reported_page != current_page
                or turn.registration.variant_identity != "known"
                or _page_key(reported_variant) != _page_key(current_variant)
            )
        )
        if unreviewed_variant_proposal:
            detail = (
                f"The current Page is known as {reported_page!r}, but "
                f"{turn.registration.variant_name!r} is proposed as a new "
                "material Variant. The proposal was not registered and no GUI "
                "action was executed. Call page_identity so the specialist can "
                "compare the current screenshot with every registered Variant "
                "of this Page; then review its natural-language evidence."
            )
            history.append({
                "kind": "variant_identity_feedback",
                "screen": reported_page or turn.screen_name,
                "outcome": "not_executed",
                "detail": detail,
                "rejection": _rejection_feedback(
                    "variant_identity_requires_review",
                    detail,
                    retry_after="page_identity_compares_registered_variants",
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        scene, identity_issue, page_review_handled = _review_page_identity(
            host, turn, screenshot, history)
        if semantic_identity_conflict:
            detail = (
                "No GUI action changed the current identity after the framework "
                f"last knew it as {current_page!r}/{current_variant!r}, but this "
                f"turn reports {turn.screen_name!r}/"
                f"{turn.registration.variant_name!r}. The framework did not "
                "change Page/Variant ownership or execute the proposed action. "
                "If this is the same identity, reuse both registered names; "
                "if it is genuinely different, call page_identity or report a "
                "page_identity record error with the visual reason."
            )
            history.append({
                "kind": "page_identity_feedback",
                "screen": current_page,
                "outcome": "not_executed",
                "detail": detail,
                "rejection": _rejection_feedback(
                    "page_identity_conflict",
                    detail,
                    retry_after="page_identity_reassessed_from_visual_context",
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        if (scene is None and not page_review_handled
                and not registration_deferral_call):
            if identity_stage == "page":
                identity_issue = _select_landing_page(host, turn)
                page_review_handled = True
            elif identity_stage == "variant":
                scene, identity_issue = _commit_landing_variant(
                    host, turn, screenshot)
            else:
                known_page = host.protocol_map.canonical_page_name(
                    turn.registration.matched_page_name
                )
                page_facts = (
                    host.protocol_map.pages.get(known_page, {})
                    if turn.registration.identity == "known"
                    else {}
                )
                canonical_page, identity_issue = host.protocol_map.observe(
                    name=turn.screen_name,
                    summary=str(
                        page_facts.get("summary") or turn.screen_name),
                    identity=turn.registration.identity,
                    matched_page_name=turn.registration.matched_page_name,
                    surface_kind=str(
                        page_facts.get("surface_kind") or "other"),
                    regions=(),
                    screenshot=screenshot,
                    variant_name=turn.registration.variant_name,
                    variant_identity=turn.registration.variant_identity,
                    visible_predicates=turn.registration.visible_predicates,
                    commit_regions=False,
                )
                if not identity_issue:
                    scene = _register_scene(
                        host, screenshot, turn, canonical_page)
        if (scene is not None and not identity_issue
                and host.pending_connection):
            host.protocol_map.connect(
                host.pending_connection["source"], scene.page_name,
                host.pending_connection["action"],
                host.pending_connection["control"],
            )
            host.pending_connection = None
        history.append({
            "kind": (
                "observation" if scene is not None
                else "observation_unregistered"
            ),
            "decision": decisions,
            "screen": scene.page_name if scene is not None else turn.screen_name,
            "summary": turn.screen_name,
            "reason": turn.decision.reason,
            "task_strategy": turn.task_strategy,
            "state_id": scene.state_id if scene is not None else "",
            "registration": asdict(turn.registration),
            "exploration_task": (
                asdict(host.exploration_task) if host.exploration_task else None),
            "identity_issue": identity_issue,
            "identity_review": (
                asdict(turn.previous_tool_review)
                if turn.previous_tool_review else None
            ),
        })
        settled_no_change_scroll = False
        if pending is not None and scene is not None:
            settled_no_change_scroll = _settle_pending_action(
                host,
                pending,
                scene,
                pending.assessment or turn.previous,
                history,
                identity_issue=identity_issue,
            )
            pending = None

        page_update_issue = ""
        stage_name_before = stage_before_turn[0]
        if (turn.page_update is not None
                and stage_name_before not in {
                    "record_regions", "review_region_equivalence",
                    "survey_region", "completion_ready",
                }):
            page_update_issue = (
                f"page_update is deferred during {stage_name_before}; "
                "finish the current stage and submit it after the framework "
                "provides the Region stage context"
            )
            history.append({
                "kind": "stage_context_feedback",
                "outcome": "page_update_deferred",
                "detail": page_update_issue,
                "rejection": _rejection_feedback(
                    "page_update_outside_stage",
                    page_update_issue,
                    retry_after="current_stage_advances_to_region_work",
                    correction=(
                        "Keep the current page identity or route result only. "
                        "The next Region-stage prompt will include the local "
                        "ledger needed for page_update."
                    ),
                ),
            })
        elif turn.page_update is not None:
            region_reviewed = _region_review_required(
                host, turn.page_update)
            reviewed_update, page_update_issue = _review_region_proposal(
                host,
                turn.page_update,
                scene,
                screenshot,
                history,
                main_agent_reason=turn.decision.reason,
            )
            if not page_update_issue and reviewed_update is not None:
                review_region_names = _entry_review_region_names(
                    host, reviewed_update)
                if (
                    reviewed_update.new_entries
                    or reviewed_update.entry_resolutions
                    or review_region_names
                ):
                    page_update_issue = _stage_main_agent_page_update(
                        host, reviewed_update, scene, screenshot, history,
                        allow_same_frame_completion=settled_no_change_scroll,
                        region_reviewed=region_reviewed,
                        main_agent_reason=turn.decision.reason,
                        review_region_names=review_region_names,
                    )
                else:
                    page_update_issue = _apply_main_agent_page_update(
                        host, reviewed_update, scene, screenshot, history,
                        allow_same_frame_completion=settled_no_change_scroll,
                        region_reviewed=region_reviewed,
                    )
        if page_update_issue:
            logger.debug("page_update rejected: %s", page_update_issue)

        task_before_sync = host.exploration_task
        _bind_history_records_to_task(
            history[rejection_history_cursor:], task_before_sync)

        if (
            decision.action == "NONE"
            and pending is None
            and task_before_sync is not None
            and task_before_sync.task_type == "explore_region"
            and task_before_sync.phase == "explore_region"
            and not page_update_issue
            and not any(
                state.get("status") == "needs_restore"
                for state in host.temporary_states.values()
            )
            and _complete_region_task_from_no_action(
                host, reason=turn.decision.reason)
        ):
            history.append({
                "kind": "region_operation_task",
                "screen": task_before_sync.page_name,
                "region": task_before_sync.region_name,
                "outcome": "complete",
                "detail": turn.decision.reason,
                "exploration_task_id": task_before_sync.task_id,
            })

        _apply_target_edge_scope(host)
        target_edge_result = _target_edge_terminal_result(host)
        if target_edge_result is not None:
            history.append({
                "kind": "target_edge_test_result",
                **target_edge_result,
            })
            host.graph.stop_reason = str(target_edge_result["stop_reason"])
            break

        identity_pending_after_observation = bool(
            _identity_stage(host, pending))
        if not identity_pending_after_observation:
            _sync_exploration_task(host)
        if (
            pending is None
            and host.exploration_task is None
            and not identity_pending_after_observation
        ):
            gaps = _completion_gaps(host)
            history.append({
                "kind": "framework_completion",
                "outcome": "complete" if not gaps else "partial",
                "remaining": gaps,
                "detail": (
                    "The framework found no open exploration task."
                    if not gaps else
                    "No runnable task remains, but evidence gaps are still open."
                ),
            })
            if not gaps:
                host.graph.stop_reason = "framework_complete"
            elif not host.graph.stop_reason:
                host.graph.stop_reason = "framework_partial"
            break
        stage_after_observation = _stage_signature(host, pending)
        decision = _defer_action_after_stage_transition(
            history,
            task_before_sync,
            decision,
            stage_before_turn,
            stage_after_observation,
        )

        if (host.max_states > 0
                and scene is not None
                and scene.is_new
                and host.graph.graph.number_of_nodes() > host.max_states):
            host.graph.stop_reason = "max_states"
            break
        if (host.max_actions > 0
                and pending is None
                and host.pending_entry_review is None
                and not _identity_stage(host, pending)
                and host.action_count >= host.max_actions):
            host.graph.stop_reason = "max_actions"
            break

        converted, action_tool_issue = _convert_action_tool(
            host,
            screenshot,
            decision,
            turn.previous_tool_review,
        )
        if converted is None:
            issue_prefix = str(action_tool_issue).partition(":")[0].strip()
            issue_code = (
                issue_prefix
                if issue_prefix.replace("_", "").isalnum()
                else "invalid_tool_call"
            )
            history.append({
                "kind": "protocol_feedback",
                "screen": scene.page_name if scene is not None else turn.screen_name,
                "outcome": "not_executed",
                "detail": action_tool_issue,
                "tool_name": decision.tool_name,
                "rejection": _rejection_feedback(
                    issue_code,
                    action_tool_issue,
                    retry_after="tool_arguments_corrected",
                    correction=(
                        "Use the returned fact mismatch and latest screenshot "
                        "to decide whether to correct this call or choose a "
                        "different tool."
                    ),
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        decision = converted

        if decision.action == "NONE":
            no_stage_progress = (
                _stage_signature(host, pending) == stage_before_turn
                and _rejection_progress_token(host) == current_progress_token
            )
            record = {
                "kind": "agent_observation_only",
                "screen": scene.page_name if scene is not None else turn.screen_name,
                "outcome": (
                    "entry_review_recorded" if turn.entry_review is not None
                    else "page_update_recorded" if turn.page_update is not None
                    else "no_gui_action_requested"
                ),
                "exploration_task": (
                    asdict(host.exploration_task)
                    if host.exploration_task else None
                ),
            }
            if no_stage_progress:
                stage_name = stage_before_turn[0] or "current_stage"
                detail = _stage_incomplete_no_action_detail(
                    host,
                    stage_name=stage_name,
                    current_page=(
                        scene.page_name if scene is not None
                        else turn.screen_name
                    ),
                )
                record.update({
                    "outcome": "stage_incomplete_no_action",
                    "detail": detail,
                    "rejection": _rejection_feedback(
                        "stage_incomplete_no_action", detail),
                })
            history.append(record)
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        if decision.action == "CALL_TOOL":
            exposed_names = {str(item.get("name") or "")
                             for item in tool_catalog}
            if decision.tool_name not in exposed_names:
                history.append({
                    "kind": "protocol_feedback",
                    "screen": (
                        scene.page_name if scene is not None
                        else turn.screen_name
                    ),
                    "outcome": "not_executed",
                    "detail": "tool is not exposed in the current turn",
                    "tool_name": decision.tool_name,
                    "rejection": _rejection_feedback(
                        "tool_not_available",
                        "tool is not exposed in the current turn",
                        correction=(
                            "Choose one tool from the current dynamic catalog: "
                            + ", ".join(sorted(exposed_names))
                        ),
                    ),
                })
                observation = host.fresh_observation(observation)
                _checkpoint(host, history)
                continue
            task_id = (
                host.exploration_task.task_id
                if host.exploration_task is not None else ""
            )
            frame_id = screenshot_frame_id(screenshot)
            if decision.tool_name == "defer_current_task":
                defer_issue = _defer_current_task(
                    host,
                    decision.tool_arguments,
                    assessment=turn.previous,
                )
                dependency = deepcopy(host.task_dependencies.get(task_id) or {})
                history.append({
                    "kind": "tool",
                    "screen": (
                        scene.page_name if scene is not None else turn.screen_name
                    ),
                    "frame_id": frame_id,
                    "tool_name": "defer_current_task",
                    "tool_arguments": dict(decision.tool_arguments),
                    "target": str(
                        decision.tool_arguments.get("prerequisite_target") or ""),
                    "exploration_task_id": task_id,
                    "outcome": "deferred" if not defer_issue else "rejected",
                    "tool_result": {
                        "status": "deferred" if not defer_issue else "rejected",
                        "data": dependency if not defer_issue else {
                            "feedback": defer_issue,
                        },
                    },
                    "detail": (
                        str(dependency.get("reason") or "")
                        if not defer_issue else defer_issue
                    ),
                    **({} if not defer_issue else {
                        "rejection": _rejection_feedback(
                            "invalid_task_defer", defer_issue,
                            retry_after="latest_exact_entry_attempt_has_visible_prerequisite_evidence",
                        ),
                    }),
                })
                observation = host.fresh_observation(observation)
                _checkpoint(host, history)
                continue
            if decision.tool_name == "report_record_error":
                repeat_report_issue = _repeat_task_frame_record_error_issue(
                    history,
                    task_id=task_id,
                    frame_id=frame_id,
                    error_kind=str(
                        decision.tool_arguments.get("kind") or ""
                    ).strip().casefold(),
                )
                if repeat_report_issue:
                    history.append({
                        "kind": "protocol_feedback",
                        "screen": (
                            scene.page_name if scene is not None
                            else turn.screen_name
                        ),
                        "outcome": "not_executed",
                        "detail": repeat_report_issue,
                        "tool_name": decision.tool_name,
                        "exploration_task_id": task_id,
                        "rejection": _rejection_feedback(
                            "duplicate_record_error_same_frame",
                            repeat_report_issue,
                        ),
                    })
                    observation = host.fresh_observation(observation)
                    _checkpoint(host, history)
                    continue
            if decision.tool_name == "handle_interruption":
                planned_action = _interruption_plan(
                    host,
                    screenshot,
                    (
                        scene.page_name if scene is not None
                        else host.protocol_map.current_page or turn.screen_name
                    ),
                    decision.tool_arguments,
                    history,
                )
                if planned_action is None:
                    observation = host.fresh_observation(observation)
                    _checkpoint(host, history)
                    continue
                decision = planned_action
                if (
                    identity_stage in {"page", "variant"}
                    and decision.action == "WAIT"
                ):
                    host.pending_page_identity = None
                    host.identity_feedback = None
                    if pending is not None:
                        pending.assessment = None
                        pending.evidence.pop("first_model_assessment", None)
                if (
                    scene is None
                    and identity_stage in {"page", "variant"}
                    and decision.action in {"CLICK", "HOVER", "BACK"}
                ):
                    if (
                        host.max_actions > 0
                        and host.action_count >= host.max_actions
                    ):
                        history.append({
                            "kind": "action",
                            "screen": turn.screen_name,
                            "action": decision.action,
                            "target": decision.target,
                            "outcome": "not_executed",
                            "detail": (
                                "the action budget is exhausted; only the "
                                "pending landing may still be settled"
                            ),
                            "pre_registration_recovery": True,
                            "rejection": _rejection_feedback(
                                "max_actions_reached",
                                "the action budget is exhausted",
                            ),
                        })
                        observation = host.fresh_observation(observation)
                        _checkpoint(host, history)
                        continue
                    recovered = _execute_pre_registration_interruption(
                        host,
                        screenshot,
                        decision,
                        history,
                        pending=pending,
                        screen_name=turn.screen_name,
                        source_page=(
                            pending.source.page_name
                            if pending is not None
                            else host.protocol_map.current_page
                        ),
                    )
                    observation = (
                        recovered
                        if recovered is not None
                        else host.fresh_observation(observation)
                    )
                    _checkpoint(host, history)
                    continue
            else:
                disputed_staged_page = ""
                if (
                    identity_stage == "variant"
                    and decision.tool_name == "report_record_error"
                    and str(decision.tool_arguments.get("kind") or "")
                    .strip().casefold() == "page_identity"
                ):
                    if host.pending_landing_page is not None:
                        disputed_staged_page = (
                            host.pending_landing_page.page_name)
                    host.pending_landing_page = None
                    host.pending_page_identity = None
                    host.identity_feedback = None
                    identity_stage = "page"
                page_identity_context = _arrival_context_view(
                    host, pending, history)
                page_identity_context["identity_stage"] = identity_stage
                if disputed_staged_page:
                    page_identity_context.update({
                        "_reopened_from_variant": True,
                        "_disputed_staged_page": disputed_staged_page,
                    })
                if host.pending_landing_page is not None:
                    page_identity_context["selected_page"] = {
                        "page_name": host.pending_landing_page.page_name,
                        "identity": host.pending_landing_page.identity,
                    }
                if pending is not None:
                    page_identity_context["source_screenshot"] = (
                        pending.source.screenshot)
                _dispatch_tool_call(
                    host,
                    turn,
                    screenshot,
                    (
                        scene.page_name if scene is not None
                        else host.protocol_map.current_page or turn.screen_name
                    ),
                    history,
                    page_identity_context=page_identity_context,
                )
                observation = host.fresh_observation(observation)
                _checkpoint(host, history)
                continue
        wait_task_id = _exploration_task_key(host.exploration_task)
        wait_frame_id = screenshot_frame_id(screenshot)
        if decision.action == "WAIT":
            repeat_wait_issue = _repeat_wait_issue(
                history,
                task_id=wait_task_id,
                frame_id=wait_frame_id,
            )
            if repeat_wait_issue:
                history.append({
                    "kind": "action",
                    "screen": (
                        scene.page_name if scene is not None
                        else turn.screen_name
                    ),
                    "action": "WAIT",
                    "target": decision.target,
                    "outcome": "not_executed",
                    "detail": repeat_wait_issue,
                    "frame_id": wait_frame_id,
                    "exploration_task_id": wait_task_id,
                    "rejection": _rejection_feedback(
                        "repeat_wait_same_frame", repeat_wait_issue),
                })
                observation = host.fresh_observation(observation)
                _checkpoint(host, history)
                continue
        if scene is None:
            unresolved_reason = (
                identity_issue
                or "page identity is unresolved"
            )
            history.append({
                "kind": "action",
                "screen": turn.screen_name,
                "action": decision.action,
                "target": decision.target,
                "frame_id": wait_frame_id,
                "exploration_task_id": wait_task_id,
                "outcome": (
                    "reobserve" if decision.action == "WAIT"
                    else "not_executed"
                ),
                "detail": (
                    decision.reason if decision.action == "WAIT"
                    else unresolved_reason
                ),
                **({} if decision.action == "WAIT" else {
                    "rejection": _rejection_feedback(
                        "page_context_missing",
                        unresolved_reason,
                        retry_after="current_page_reported",
                        correction=(
                            "Report the current screenshot as a registered known "
                            "page or a clearly named new page. If identity is "
                            "genuinely uncertain, you may use page_identity."
                        ),
                    ),
                }),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue
        if decision.action == "WAIT":
            history.append({
                "kind": "action",
                "screen": scene.page_name,
                "action": "WAIT",
                "target": decision.target,
                "frame_id": wait_frame_id,
                "exploration_task_id": wait_task_id,
                "outcome": "reobserve",
                "detail": decision.reason,
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        region_probe_issue = _region_probe_action_issue(
            host, scene.page_name, decision)
        if region_probe_issue:
            history.append({
                "kind": "action",
                "screen": scene.page_name,
                "action": decision.action,
                "target": decision.target,
                "outcome": "not_executed",
                "detail": region_probe_issue,
                "rejection": _rejection_feedback(
                    "region_probe_binding_rejected",
                    region_probe_issue,
                    retry_after="the_action_targets_the_assigned_region",
                    correction=(
                        "Probe a safe visible internal operation inside the "
                        "assigned Region with entry_id empty, or close this "
                        "Region probe with a concrete visual reason."
                    ),
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue


        survey_click_issue = _survey_entry_click_issue(host, decision)
        if survey_click_issue:
            history.append({
                "kind": "action",
                "screen": scene.page_name,
                "action": decision.action,
                "target": decision.target,
                "outcome": "not_executed",
                "detail": survey_click_issue,
                "rejection": _rejection_feedback(
                    "survey_does_not_execute_entry",
                    survey_click_issue,
                    retry_after="the_framework_dispatches_explore_entry",
                    correction=(
                        "Continue the assigned page survey. Use entry_id empty "
                        "only for necessary navigation, return, or interference "
                        "handling; do not probe a registered function now."
                    ),
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        covered_issue = _covered_entry_click_issue(
            host, scene.page_name, decision)
        if covered_issue:
            history.append({
                "kind": "action",
                "screen": scene.page_name,
                "action": decision.action,
                "target": decision.target,
                "outcome": "not_executed",
                "detail": covered_issue,
                "rejection": _rejection_feedback(
                    "entry_already_covered",
                    covered_issue,
                    retry_after="a_new_task_or_uncovered_entry_is_selected",
                    correction=(
                        "Do not probe this verified/inferred function again. "
                        "If its visible control is needed only for navigation, "
                        "leave entry_id empty."
                    ),
                ),
            })
            observation = host.fresh_observation(observation)
            _checkpoint(host, history)
            continue

        click_review: Dict[str, Any] = {}
        if decision.action in {
                "CLICK", "INPUT_TEXT", "DOUBLE_TAP", "LONG_PRESS",
        }:
            approved, click_review = _review_click(
                host, screenshot, decision)
            if not approved:
                review_reason = str(
                    click_review.get("reason")
                    or "independent click review rejected the point"
                )
                rejected_operation = str(
                    decision.tool_arguments.get("operation")
                    or decision.action
                    or "click"
                ).strip().casefold()
                rejected_point = list(decision.point_1000 or [])
                rejected_request = (
                    f"Rejected {rejected_operation} request for target "
                    f"{decision.target!r} at point_1000={rejected_point}. "
                    f"Reviewer: {review_reason}"
                )
                entry_disposition: Dict[str, Any] = {}
                entry_id = str(
                    decision.tool_arguments.get("entry_id") or "").strip()
                exact_entry = (
                    entry_id
                    and str(click_review.get("decision") or "").casefold()
                    == "reject"
                    and click_review.get("point_matches_target") is True
                    and click_review.get("target_matches_request") is True
                )
                risk = str(click_review.get("risk") or "").casefold()
                if exact_entry and risk == "unsafe":
                    try:
                        record = host.entry_ledger.mark_unsafe_to_execute(
                            entry_id,
                            reason=str(
                                click_review.get("reason")
                                or "independent click review rejected the target"
                            ),
                        )
                    except KeyError:
                        pass
                    else:
                        entry_disposition = {
                            "entry_id": record.entry_id,
                            "status": record.status.value,
                            "task_eligible": record.task_eligible,
                            "reason": record.last_result,
                        }
                history.append({
                    "kind": "click_review",
                    "screen": scene.page_name,
                    "action": decision.action,
                    "target": decision.target,
                    "outcome": "not_executed",
                    "detail": review_reason,
                    "review": click_review,
                    "entry_disposition": entry_disposition,
                    "rejection": _rejection_feedback(
                        "click_review_rejected",
                        rejected_request,
                        retry_after="review_reason_addressed",
                        correction=(
                            "Do not reuse the rejected point. Re-read the latest "
                            "screenshot and reviewer reason. If the requested "
                            "operation or field is disallowed, choose a different "
                            "safe operation or control; otherwise choose a visibly "
                            "different point inside the requested control."
                        ),
                    ),
                })
                observation = host.fresh_observation(observation)
                _checkpoint(host, history)
                continue

        prepared = _prepare_action_attempt(
            host,
            scene,
            decision,
            screenshot,
            history,
            click_review=click_review,
            previous_tool_review=turn.previous_tool_review,
        )
        if prepared is None:
            fresh_observation = host.fresh_observation(observation)
            fresh_screenshot = (fresh_observation or {}).get("screenshot")
            if (
                decision.action == "WAIT"
                and identity_stage in {"page", "variant"}
                and fresh_screenshot
                and fresh_screenshot != screenshot
            ):
                host.pending_page_identity = None
                host.pending_landing_page = None
                host.identity_feedback = None
                host.protocol_map.current_page = ""
                host.protocol_map.current_variant = ""
            observation = fresh_observation
            _checkpoint(host, history)
            continue
        event_index = prepared.event_index
        primitive = prepared.primitive
        evidence = prepared.evidence
        fixture_before = evidence.get("fixture_audit_before")
        history_index = prepared.history_index
        entry_action_id = prepared.entry_action_id
        try:
            observation = host.env.step(primitive, pause=2.0)
            if not (observation or {}).get("screenshot"):
                observation = host.fresh_observation(observation or {})
            host.graph.update_action_event(event_index, outcome="executed")
            fixture_after = host.audit_fixture(
                None, "after", event_index=event_index)
            if fixture_after:
                evidence["fixture_audit_after"] = fixture_after
                history[history_index]["fixture_audit"] = {
                    "before": fixture_before, "after": fixture_after,
                }
                host.graph.update_action_event(event_index, evidence=evidence)
            host.action_count += 1
            pending = prepared
            host.pending_landing_page = None
        except Exception as exc:
            detail = str(exc)[:500]
            host.graph.update_action_event(
                event_index,
                outcome="execution_error",
                detail=detail,
                landing_verified=False,
                committed=False,
                evidence=evidence,
            )
            history[history_index].update({
                "outcome": "execution_error", "detail": detail,
            })
            if entry_action_id:
                host.entry_ledger.finish_action(
                    entry_action_id,
                    action_executed=False,
                    outcome_verified=False,
                    result=detail,
                )
            observation = host.fresh_observation(observation)
        _checkpoint(host, history)
    _bind_history_records_to_task(
        history[rejection_history_cursor:], host.exploration_task)
    host.audit_fixture(None, "final")
    host.graph.autonomous_completion_gaps = _completion_gaps(host)
    host.graph.autonomous_completion_summary = _completion_summary(host)
    _checkpoint(host, history)
    return host.graph


def run(
    env: Any,
    app_name: str,
    output_root: str,
    initial_obs: Dict[str, Any],
    *,
    model: str = "qwen3.7-plus",
    backend: str = "qwen_api",
    transport_agent: Any = None,
    max_states: int = 50,
    max_actions: int = 200,
    fixture_audit: Any = None,
    identity_resolver: Any = None,
    target_edge_scope: Optional[Dict[str, str]] = None,
    resume_path: str = "",
    relaunch_fn: Any = None,
    desktop_window_owner: Any = None,
    page_session: bool = False,
):
    backend_name = str(backend or "").strip().casefold()
    if backend_name == "qwen_api":
        if transport_agent is None:
            from gui_rewalk.env.gui_gen_agent import GUIGenAgent
            transport_agent = GUIGenAgent(
                model="Qwen", model_version=model,
                enable_thinking=False,
            )
        decision_agent = QwenAutonomousAgent(
            model, output_root, transport_agent)
    elif backend_name == "codex_cli":
        decision_agent = CodexAutonomousAgent(model, output_root)
    else:
        raise ValueError(f"unknown autonomous backend: {backend}")
    runtime = AutonomousTraversalRuntime(
        env=env, decision_agent=decision_agent, app_name=app_name,
        output_root=output_root, max_states=max_states, max_actions=max_actions,
        fixture_audit=fixture_audit,
        identity_resolver=identity_resolver,
        target_edge_scope=target_edge_scope,
        relaunch_fn=relaunch_fn,
        desktop_window_owner=desktop_window_owner,
    )
    if str(resume_path or "").strip():
        runtime.restore(str(resume_path))
    if page_session:
        from .autonomous_page_session import run_page_session_traversal
        return run_page_session_traversal(runtime, initial_obs)
    return run_autonomous_traversal(runtime, initial_obs)
