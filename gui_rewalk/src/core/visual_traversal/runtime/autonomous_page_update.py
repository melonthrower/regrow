"""Qwen autonomous Page-update validation and correction ledger."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_agent import REGION_REVIEW_ATTEMPT_LIMIT
from .autonomous_prompt import _rejection_feedback
from .autonomous_region_tools import screenshot_frame_id
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _register_scene,
)
from .autonomous_turn import (
    AutonomousTurn,
    ObservedScene,
    PageUpdate,
    PendingAction,
    PendingLandingPage,
    PendingPageIdentity,
    _optional_bbox,
    _page_key,
)


def _reject_no_change_identity_conflict(
    pending: Optional[PendingAction],
    turn: AutonomousTurn,
    settlement_page: str,
    reported_variant: str,
    history: List[Dict[str, Any]],
    *,
    compare_variant: bool = True,
) -> bool:
    """Reject no-change when the same turn binds another Page or Variant."""
    if (
        pending is None
        or pending.assessment is None
        or pending.assessment.outcome != "no_visible_change"
        or not settlement_page
    ):
        return False
    source = pending.source
    if (
        _page_key(settlement_page) == _page_key(source.page_name)
        and (
            not compare_variant
            or
            not source.variant_name
            or _page_key(reported_variant) == _page_key(source.variant_name)
        )
    ):
        return False
    if compare_variant:
        detail = (
            "previous_action reports no_visible_change, but the same turn "
            "places the current screenshot on a different Page or material "
            f"Variant: source={source.page_name!r}/{source.variant_name!r}, "
            f"reported={settlement_page!r}/{reported_variant!r}."
        )
        correction = (
            f"Keep screen.name={source.page_name!r} and "
            f"screen.variant.name={source.variant_name!r} when the pending "
            "action produced no visible change. If the source binding is "
            "disputed, report uncertain and call page_identity or report the "
            "identity-ledger error; do not bind a different known/new identity."
        )
    else:
        detail = (
            "previous_action reports no_visible_change, but the Page stage "
            "places the current screenshot on a different Page: "
            f"source={source.page_name!r}, reported={settlement_page!r}."
        )
        correction = (
            f"Keep screen.name={source.page_name!r} when the pending action "
            "produced no visible change. This stage does not judge Variant. "
            "If the Page binding is disputed, report uncertain and call "
            "page_identity or report the identity-ledger error."
        )
    history.append({
        "kind": "previous_action_feedback",
        "screen": turn.screen_name,
        "target": pending.target,
        "outcome": "assessment_rejected",
        "detail": detail,
        "rejection": _rejection_feedback(
            "previous_action_page_conflict",
            detail,
            retry_after="previous_action_and_page_reassessed",
            correction=correction,
        ),
    })
    pending.assessment = None
    return True


def _page_update_item_rejection(
    kind: str,
    index: int,
    raw: Any,
    *,
    error_code: str,
    field_name: str,
    reason: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "kind": kind,
        "index": index,
        "error_code": error_code,
        "field": field_name,
        "reason": reason[:300],
    }
    if isinstance(raw, dict):
        region_name = raw.get("name") if kind == "region" else raw.get(
            "region_name")
        target = raw.get("target") if kind == "new_entry" else None
        if isinstance(region_name, str) and region_name.strip():
            result["region_name"] = region_name.strip()[:160]
        if isinstance(target, str) and target.strip():
            result["target"] = target.strip()[:160]
    return result


def _normalize_page_region_item(
    raw: Any,
    index: int,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_item", field_name="",
            reason="Region item must be an object")
    allowed = {
        "name", "summary", "survey_memory", "bbox_1000",
        "coverage_complete", "equivalent_to_region_ref",
        "equivalence_reason", "same_group_as", "split_from_group",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="unsupported_field",
            field_name=unknown[0],
            reason=f"unsupported field(s): {', '.join(unknown)}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="missing_required",
            field_name="name", reason="name must be a non-empty string")
    summary = raw.get("summary", "")
    if not isinstance(summary, str):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="summary", reason="summary must be a string")
    survey_memory = raw.get("survey_memory", "")
    if not isinstance(survey_memory, str):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="survey_memory",
            reason="survey_memory must be a string")
    equivalent_to_region_ref = raw.get("equivalent_to_region_ref", "")
    if equivalent_to_region_ref is None:
        equivalent_to_region_ref = ""
    if not isinstance(equivalent_to_region_ref, str):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="equivalent_to_region_ref",
            reason="equivalent_to_region_ref must be a string")
    equivalence_reason = raw.get("equivalence_reason", "")
    if not isinstance(equivalence_reason, str):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="equivalence_reason",
            reason="equivalence_reason must be a string")
    same_group_as = raw.get("same_group_as", "")
    if same_group_as is None:
        same_group_as = ""
    if not isinstance(same_group_as, str):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="same_group_as",
            reason="same_group_as must be a string")
    split_from_group = raw.get("split_from_group", False)
    if not isinstance(split_from_group, bool):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="split_from_group",
            reason="split_from_group must be a boolean")
    if split_from_group and same_group_as.strip():
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="conflicting_group_change",
            field_name="split_from_group",
            reason="split_from_group and same_group_as cannot be combined")
    bbox, error = _optional_bbox(raw.get("bbox_1000"), "bbox_1000")
    if error:
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_bbox",
            field_name="bbox_1000", reason=error)
    complete = raw.get("coverage_complete")
    if not isinstance(complete, bool):
        return None, _page_update_item_rejection(
            "region", index, raw, error_code="invalid_type",
            field_name="coverage_complete",
            reason="coverage_complete must be a boolean")
    return {
        "name": name.strip()[:160],
        "summary": summary.strip()[:500],
        "survey_memory": survey_memory.strip()[:1200],
        "equivalent_to_region_ref": (
            equivalent_to_region_ref.strip()[:80]),
        "equivalence_reason": equivalence_reason.strip()[:500],
        "same_group_as": same_group_as.strip()[:160],
        "split_from_group": split_from_group,
        "bbox_1000": bbox,
        "coverage_complete": complete,
    }, None


def _normalize_new_entry_item(
    raw: Any,
    index: int,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_item", field_name="",
            reason="new_entry item must be an object")
    allowed = {
        "region_name", "target", "bbox_1000", "equivalent_occurrences",
        "equivalent_to_entry_id", "equivalence_reason", "control_type",
        "operation", "subject", "exploration_policy",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="unsupported_field",
            field_name=unknown[0],
            reason=f"unsupported field(s): {', '.join(unknown)}")
    region_name = raw.get("region_name")
    target = raw.get("target")
    for field_name, value in (("region_name", region_name), ("target", target)):
        if not isinstance(value, str) or not value.strip():
            return None, _page_update_item_rejection(
                "new_entry", index, raw, error_code="missing_required",
                field_name=field_name,
                reason=f"{field_name} must be a non-empty string")
    bbox, error = _optional_bbox(raw.get("bbox_1000"), "bbox_1000")
    if error:
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_bbox",
            field_name="bbox_1000", reason=error)
    occurrences = raw.get("equivalent_occurrences", [])
    if not isinstance(occurrences, list):
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_type",
            field_name="equivalent_occurrences",
            reason="equivalent_occurrences must be an array")
    normalized_occurrences: List[Dict[str, Any]] = []
    for occurrence_index, occurrence in enumerate(occurrences):
        field_prefix = f"equivalent_occurrences[{occurrence_index}]"
        if not isinstance(occurrence, dict):
            return None, _page_update_item_rejection(
                "new_entry", index, raw, error_code="invalid_item",
                field_name=field_prefix, reason="occurrence must be an object")
        unknown = sorted(set(occurrence) - {"target", "bbox_1000"})
        if unknown:
            return None, _page_update_item_rejection(
                "new_entry", index, raw, error_code="unsupported_field",
                field_name=f"{field_prefix}.{unknown[0]}",
                reason=f"unsupported occurrence field(s): {', '.join(unknown)}")
        occurrence_target = occurrence.get("target")
        if not isinstance(occurrence_target, str) or not occurrence_target.strip():
            return None, _page_update_item_rejection(
                "new_entry", index, raw, error_code="missing_required",
                field_name=f"{field_prefix}.target",
                reason="occurrence target must be a non-empty string")
        occurrence_bbox, error = _optional_bbox(
            occurrence.get("bbox_1000"), f"{field_prefix}.bbox_1000")
        if error:
            return None, _page_update_item_rejection(
                "new_entry", index, raw, error_code="invalid_bbox",
                field_name=f"{field_prefix}.bbox_1000", reason=error)
        normalized_occurrences.append({
            "target": occurrence_target.strip()[:160],
            "bbox_1000": occurrence_bbox,
        })
    equivalent_to_entry_id = raw.get("equivalent_to_entry_id", "")
    if equivalent_to_entry_id is None:
        equivalent_to_entry_id = ""
    if not isinstance(equivalent_to_entry_id, str):
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_type",
            field_name="equivalent_to_entry_id",
            reason="equivalent_to_entry_id must be a string")
    equivalence_reason = raw.get("equivalence_reason", "")
    if equivalence_reason is None:
        equivalence_reason = ""
    if not isinstance(equivalence_reason, str):
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_type",
            field_name="equivalence_reason",
            reason="equivalence_reason must be a string")
    control_type = str(raw.get("control_type") or "control").strip()
    if control_type not in {"control", "input"}:
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_type",
            field_name="control_type",
            reason="control_type must be control or input")
    exploration_policy = str(
        raw.get("exploration_policy") or "explore").strip()
    if exploration_policy not in {"explore", "record_only"}:
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="invalid_type",
            field_name="exploration_policy",
            reason="exploration_policy must be explore or record_only")
    operation = str(raw.get("operation") or target).strip()
    subject = str(raw.get("subject") or region_name).strip()
    if not operation or not subject:
        return None, _page_update_item_rejection(
            "new_entry", index, raw, error_code="missing_required",
            field_name="operation" if not operation else "subject",
            reason="operation and subject must be non-empty strings")
    return {
        "region_name": region_name.strip()[:160],
        "target": target.strip()[:160],
        "operation": operation[:160],
        "subject": subject[:160],
        "bbox_1000": bbox,
        "equivalent_occurrences": normalized_occurrences,
        "equivalent_to_entry_id": equivalent_to_entry_id.strip()[:80],
        "equivalence_reason": equivalence_reason.strip()[:500],
        "control_type": control_type,
        "exploration_policy": exploration_policy,
    }, None


def _page_update_item_key(item: Dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip()
    region_key = _page_key(item.get("region_name"))
    if kind == "region":
        if region_key:
            return f"region:{region_key}"
        return f"invalid_region:{item.get('index', -1)}"
    target_key = _page_key(item.get("target"))
    if kind == "new_entry":
        if region_key and target_key:
            return f"entry:{region_key}:{target_key}"
        return f"invalid_entry:{item.get('index', -1)}"
    if kind == "page_update":
        return "page_update"
    return ""


def _update_page_corrections(
    host: AutonomousTraversalRuntime,
    page_name: str,
    *,
    accepted_keys: Sequence[str],
    rejected_items: Sequence[Dict[str, Any]],
    resolved_keys: Sequence[str] = (),
) -> None:
    page_key = _page_key(page_name)
    pending = dict(host.page_update_corrections.get(page_key) or {})
    for item_key in resolved_keys:
        pending.pop(str(item_key), None)
    for item_key in accepted_keys:
        pending.pop(str(item_key), None)
    accepted_entry_targets = {
        str(item_key).split(":", 2)[2]
        for item_key in accepted_keys
        if str(item_key).startswith("entry:")
        and len(str(item_key).split(":", 2)) == 3
    }
    for item_key, item in list(pending.items()):
        if (
            item.get("kind") == "new_entry"
            and item.get("field") == "region_name"
            and _page_key(item.get("target")) in accepted_entry_targets
        ):
            # A valid replacement for the same entry target closes a rejected
            # Region binding even though the corrected Region changes its key.
            pending.pop(item_key, None)
    for item in rejected_items:
        item_key = _page_update_item_key(item)
        if item_key:
            pending[item_key] = {
                key: item.get(key) for key in (
                    "kind", "region_name", "target", "field",
                    "error_code", "reason", "region_ref", "canonical_name",
                    "proposed_regions", "proposed_entries",
                    "omitted_regions", "baseline_regions",
                    "review", "frame_id", "review_attempt",
                    "review_exhausted", "review_evidence_generation",
                    "fixed_evidence_frame",
                ) if item.get(key) not in (None, "")
            }
    if pending:
        host.page_update_corrections[page_key] = pending
    else:
        host.page_update_corrections.pop(page_key, None)


def _current_resurvey_partition_is_reviewed(
    host: AutonomousTraversalRuntime,
    page_name: str,
) -> bool:
    page_key = _page_key(page_name)
    resurvey = host.pending_page_resurveys.get(page_key) or {}
    return bool(resurvey) and str(
        resurvey.get("region_review_generation") or ""
    ) == str(host.entry_review_evidence_generation)


def _region_review_required(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
) -> bool:
    """Review only new Region partitions or new shared-Region bindings."""
    page_key = _page_key(update.page_name)
    state = host.region_states.get(page_key)
    existing = {
        _page_key(item.get("name")): item
        for item in (state.snapshot().get("regions") if state else []) or []
        if isinstance(item, dict) and item.get("name")
    }
    for index, raw in enumerate(update.regions):
        normalized, rejection = _normalize_page_region_item(raw, index)
        if rejection is not None or normalized is None:
            continue
        current = existing.get(_page_key(normalized.get("name"))) or {}
        requested_ref = str(
            normalized.get("equivalent_to_region_ref") or "").strip()
        same_group_as = str(
            normalized.get("same_group_as") or "").strip()
        split_from_group = bool(normalized.get("split_from_group"))
        if not current:
            return True
        if requested_ref and requested_ref != str(
                current.get("region_ref") or "").strip():
            return True
        if same_group_as or split_from_group:
            return True
    if update.regions and page_key in host.pending_page_resurveys:
        # A same-Page action may reveal a new active surface, so its first
        # partition still needs independent review. Once that partition is
        # accepted, Entry reconciliation may update coverage or current-frame
        # geometry several times without adding visual evidence. Reuse the
        # accepted partition verdict until a real changed action advances the
        # shared evidence generation.
        resurvey = host.pending_page_resurveys.get(page_key) or {}
        if not str(resurvey.get("region_name") or "").strip():
            return not _current_resurvey_partition_is_reviewed(
                host, update.page_name)
    return False


def _reject_misaligned_survey_region_update(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    history: List[Dict[str, Any]],
) -> str:
    """Reject sibling-only writes while one Region survey is assigned."""
    task = host.exploration_task
    if (
        task is None
        or task.task_type != "survey_page"
        or task.phase != "survey_region"
        or not task.region_name
        or _page_key(task.page_name) != _page_key(update.page_name)
    ):
        return ""

    submitted_names = []
    submitted_names.extend(
        str(item.get("name") or "").strip()
        for item in update.regions
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )
    submitted_names.extend(
        str(item.get("region_name") or "").strip()
        for item in update.new_entries
        if isinstance(item, dict)
        and str(item.get("region_name") or "").strip()
    )
    if _page_key(task.region_name) in {
            _page_key(name) for name in submitted_names}:
        return ""

    submitted = ", ".join(dict.fromkeys(submitted_names)) or "no Region"
    reason = (
        f"survey_region currently assigns Region {task.region_name!r}, but "
        f"page_update touched {submitted} and omitted the assigned Region. "
        "No Region or entry facts from this update were written. Include the "
        "assigned Region; same-frame sibling updates may accompany it."
    )
    rejected = {
        "kind": "region",
        "index": -1,
        "region_name": task.region_name,
        "error_code": "survey_region_target_missing",
        "field": "regions",
        "reason": reason[:500],
    }
    history.append({
        "kind": "page_update_result",
        "screen": task.page_name,
        "status": "rejected",
        "accepted_regions": [],
        "created_entries": [],
        "rejected_items": [rejected],
        "rejection": _rejection_feedback(
            "survey_region_target_missing",
            reason,
            retry_after="assigned_region_is_included",
            correction=(
                "Update the Region named by the current survey task. Other "
                "visible Regions may be included only in the same update."
            ),
        ),
    })
    return reason


def _region_review_rejection(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    scene: Optional[ObservedScene],
    history: List[Dict[str, Any]],
    *,
    reason: str,
    review: Optional[Dict[str, Any]] = None,
    review_attempt: int,
    review_screenshot: Optional[bytes] = None,
) -> str:
    page_name = scene.page_name if scene is not None else update.page_name
    page_key = _page_key(page_name)
    pending_record = (
        (host.page_update_corrections.get(page_key) or {}).get("page_update")
        or {}
    )
    baseline_regions = deepcopy(
        pending_record.get("baseline_regions") or []
    )
    if not baseline_regions:
        state = host.region_states.get(page_key)
        baseline_regions = (
            deepcopy(state.snapshot().get("regions") or [])
            if state is not None else []
        )
    exhausted = review_attempt >= REGION_REVIEW_ATTEMPT_LIMIT
    rejected = {
        "kind": "page_update",
        "index": -1,
        "error_code": (
            "region_review_exhausted" if exhausted
            else "region_review_rejected"
        ),
        "field": "regions",
        "reason": str(reason or "Region review rejected the proposal")[:800],
        "proposed_regions": deepcopy(update.regions),
        "proposed_entries": deepcopy(update.new_entries),
        "omitted_regions": deepcopy(update.omitted_regions),
        "baseline_regions": baseline_regions,
        "review": deepcopy(review) if isinstance(review, dict) else {},
        "frame_id": screenshot_frame_id(
            review_screenshot
            or (scene.screenshot if scene is not None else b"")),
        "review_evidence_generation": host.entry_review_evidence_generation,
        "fixed_evidence_frame": True,
        "review_attempt": review_attempt,
        "review_exhausted": exhausted,
    }
    _update_page_corrections(
        host, page_name, accepted_keys=(), rejected_items=[rejected])
    history.append({
        "kind": "region_review_result",
        "screen": page_name,
        "status": "final_rejected" if exhausted else "rejected",
        "review_attempt": review_attempt,
        "review_attempt_limit": REGION_REVIEW_ATTEMPT_LIMIT,
        "detail": rejected["reason"],
        **({"review": deepcopy(review)} if review else {}),
        "rejection": _rejection_feedback(
            rejected["error_code"],
            rejected["reason"],
            retry_after=(
                "none_region_review_final_rejection" if exhausted
                else "main_agent_resubmits_region_partition"
            ),
            correction=(
                "The Region discussion reached its third Reviewer decision, so "
                "this proposal is finally rejected and cannot be committed."
                if exhausted else
                "Use the fixed evidence screenshot and the named Region/revision "
                "feedback above. Resubmit one complete Region partition; keep "
                "unaffected names stable and explain any disputed assignment with "
                "concrete visible evidence."
            ),
        ),
    })
    return rejected["reason"]


def _validate_region_review_result(
    result: Dict[str, Any],
    existing_regions: Sequence[Any],
) -> tuple[List[str], List[Dict[str, str]], List[str]]:
    """Check the Reviewer's exact Region/revision references."""
    errors: List[str] = []
    if set(result) != {"regions", "revisions", "reason"}:
        errors.append(
            "Region Reviewer 必须且只能返回 regions、revisions 和 reason")
    if not isinstance(result.get("reason"), str) or not str(
            result.get("reason") or "").strip():
        errors.append("Region Reviewer 的整体 reason 不能为空")

    raw_regions = result.get("regions")
    region_names: List[str] = []
    if not isinstance(raw_regions, list):
        errors.append("Region Reviewer 的 regions 必须是数组")
        raw_regions = []
    for index, raw in enumerate(raw_regions):
        if not isinstance(raw, dict) or set(raw) != {"name", "summary"}:
            errors.append(
                f"regions[{index}] 必须且只能包含非空 name 和 summary")
            continue
        name = str(raw.get("name") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        if not name or not summary:
            errors.append(
                f"regions[{index}] 必须且只能包含非空 name 和 summary")
            continue
        if name in region_names:
            errors.append(f"当前 regions 重复名称：{name}")
            continue
        region_names.append(name)

    existing_names: List[str] = []
    for raw in existing_regions:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name and name not in existing_names:
            existing_names.append(name)

    raw_revisions = result.get("revisions")
    revisions: List[Dict[str, str]] = []
    revision_counts: Dict[str, int] = {}
    unknown_names: List[str] = []
    if not isinstance(raw_revisions, list):
        errors.append("Region Reviewer 的 revisions 必须是数组")
        raw_revisions = []
    allowed_fields = {"old_region", "decision", "merged_into", "reason"}
    for index, raw in enumerate(raw_revisions):
        if not isinstance(raw, dict) or not set(raw).issubset(allowed_fields):
            errors.append(f"revisions[{index}] 包含不支持的字段或不是对象")
            continue
        old_name = str(raw.get("old_region") or "").strip()
        decision = str(raw.get("decision") or "").strip().casefold()
        revision_reason = str(raw.get("reason") or "").strip()
        target = str(raw.get("merged_into") or "").strip()
        if not old_name or decision not in {"keep", "merge", "remove"} \
                or not revision_reason:
            errors.append(
                f"revisions[{index}] 缺少有效 old_region、decision 或 reason")
            continue
        revision_counts[old_name] = revision_counts.get(old_name, 0) + 1
        if old_name not in existing_names and old_name not in unknown_names:
            unknown_names.append(old_name)
        if decision == "keep":
            if "merged_into" in raw:
                errors.append(f"keep 不得携带 merged_into：{old_name}")
            if old_name not in region_names:
                errors.append(f"keep 名称不存在于 regions：{old_name}")
        elif decision == "merge":
            if not target:
                errors.append(f"merge 缺少 merged_into：{old_name}")
            elif target not in region_names:
                errors.append(f"合并目标不存在：{old_name}→{target}")
        elif "merged_into" in raw:
            errors.append(f"remove 不得携带 merged_into：{old_name}")
        revisions.append({
            "old_region": old_name,
            "decision": decision,
            "merged_into": target,
            "reason": revision_reason[:800],
        })

    missing_names = [
        name for name in existing_names if revision_counts.get(name, 0) == 0
    ]
    duplicate_names = [
        name for name in existing_names if revision_counts.get(name, 0) > 1
    ]
    if missing_names:
        errors.append("revisions 遗漏已有 Region：" + "、".join(missing_names))
    if duplicate_names:
        errors.append(
            "revisions 重复 old_region：" + "、".join(duplicate_names))
    if unknown_names:
        errors.append(
            "revisions 含未知 old_region：" + "、".join(unknown_names))
    return region_names, revisions, errors


def _review_region_proposal(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    scene: Optional[ObservedScene],
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    main_agent_reason: str,
) -> tuple[Optional[PageUpdate], str]:
    """Run at most three independent Region reviews for one discussion."""
    alignment_issue = _reject_misaligned_survey_region_update(
        host, update, history)
    if alignment_issue:
        return None, alignment_issue
    if not _region_review_required(host, update):
        if _current_resurvey_partition_is_reviewed(host, update.page_name):
            # No new screenshot evidence supports moving a partition boundary.
            # Keep the approved occurrence geometry while allowing Entry
            # reconciliation, coverage and survey memory to advance.
            return PageUpdate(
                page_name=update.page_name,
                regions=[
                    ({
                        key: value for key, value in raw.items()
                        if key != "bbox_1000"
                    } if isinstance(raw, dict) else raw)
                    for raw in update.regions
                ],
                new_entries=deepcopy(update.new_entries),
                omitted_regions=deepcopy(update.omitted_regions),
                entry_resolutions=deepcopy(update.entry_resolutions),
            ), ""
        return update, ""
    page_key = _page_key(update.page_name)
    page_corrections = host.page_update_corrections.get(page_key, {}) or {}
    pending_record = page_corrections.get("page_update") or {}
    current_generation = host.entry_review_evidence_generation
    try:
        pending_generation = int(
            pending_record.get("review_evidence_generation"))
    except (TypeError, ValueError):
        pending_generation = -1
    if pending_record.get("review_exhausted") is True:
        if pending_generation != current_generation:
            page_corrections.pop("page_update", None)
            if page_corrections:
                host.page_update_corrections[page_key] = page_corrections
            else:
                host.page_update_corrections.pop(page_key, None)
            history.append({
                "kind": "region_review_discussion_reopened",
                "screen": update.page_name,
                "outcome": "new_visual_evidence",
                "detail": (
                    "A verified changed GUI action produced a new evidence "
                    "generation. Region discussion may restart from the "
                    "latest screenshot."
                ),
            })
            pending_record = {}
            host.region_review_screenshots.pop(page_key, None)
        else:
            return None, str(
                pending_record.get("reason")
                or "Region review discussion is finally rejected"
            )
    elif pending_record and (
        pending_generation != current_generation
        or page_key not in host.region_review_screenshots
    ):
        page_corrections.pop("page_update", None)
        if page_corrections:
            host.page_update_corrections[page_key] = page_corrections
        else:
            host.page_update_corrections.pop(page_key, None)
        history.append({
            "kind": "region_review_discussion_restarted",
            "screen": update.page_name,
            "outcome": (
                "new_visual_evidence"
                if pending_generation != current_generation
                else "fixed_evidence_unavailable"
            ),
            "detail": (
                "The prior Region discussion cannot reuse its fixed screenshot; "
                "review restarts from the current complete screenshot."
            ),
        })
        pending_record = {}
        host.region_review_screenshots.pop(page_key, None)
    previous_attempt = int(pending_record.get("review_attempt") or 0)
    review_attempt = previous_attempt + 1
    previous_review = (
        deepcopy(pending_record.get("review") or {})
        if previous_attempt else {}
    )
    if scene is None:
        return update, ""
    canonical_page = host.protocol_map.canonical_page_name(update.page_name)
    if not canonical_page or _page_key(canonical_page) != _page_key(
            scene.page_name):
        return update, ""
    if not callable(host.region_reviewer):
        reason = "independent Region Reviewer is unavailable"
        review_screenshot = host.region_review_screenshots.setdefault(
            page_key, screenshot)
        rejection = _region_review_rejection(
            host, update, scene, history, reason=reason,
            review_attempt=review_attempt,
            review_screenshot=review_screenshot,
        )
        if review_attempt >= REGION_REVIEW_ATTEMPT_LIMIT:
            host.region_review_screenshots.pop(page_key, None)
        return None, rejection

    review_screenshot = host.region_review_screenshots.setdefault(
        page_key, screenshot)
    existing_regions = deepcopy(update.regions)
    request = {
        "current_screenshot": review_screenshot,
        "fixed_evidence": True,
        "page_name": canonical_page,
        "main_agent_reason": str(main_agent_reason or "").strip(),
        "existing_regions": existing_regions,
        "review_attempt": review_attempt,
        "review_attempt_limit": REGION_REVIEW_ATTEMPT_LIMIT,
        "previous_review": previous_review,
    }
    try:
        result = host.region_reviewer(request)
    except Exception as exc:
        reason = (
            "独立 Region Reviewer 本轮没有返回可用判断；当前 Region 提案和"
            "正式账本均未改变。请根据同一截图重新复核。")
        rejection = _region_review_rejection(
            host, update, scene, history, reason=reason,
            review_attempt=review_attempt,
            review_screenshot=review_screenshot,
        )
        if review_attempt >= REGION_REVIEW_ATTEMPT_LIMIT:
            host.region_review_screenshots.pop(page_key, None)
        return None, rejection
    if not isinstance(result, dict):
        reason = (
            "独立 Region Reviewer 本轮没有给出完整裁决；当前提案未写账。")
        rejection = _region_review_rejection(
            host, update, scene, history, reason=reason,
            review_attempt=review_attempt,
            review_screenshot=review_screenshot,
        )
        if review_attempt >= REGION_REVIEW_ATTEMPT_LIMIT:
            host.region_review_screenshots.pop(page_key, None)
        return None, rejection

    review_reason = str(result.get("reason") or "").strip()
    reviewed_names, revisions, validation_errors = (
        _validate_region_review_result(result, existing_regions)
    )
    proposed_names = [
        str(item.get("name") or "").strip()
        for item in existing_regions
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    reviewer_changed_partition = (
        set(reviewed_names) != set(proposed_names)
        or any(item["decision"] != "keep" for item in revisions)
    )
    approved = not validation_errors and not reviewer_changed_partition
    if not approved:
        details = list(validation_errors[:8])
        if not validation_errors and reviewer_changed_partition:
            removed = [
                name for name in proposed_names if name not in reviewed_names
            ]
            added = [
                name for name in reviewed_names if name not in proposed_names
            ]
            merges = [
                f"{item['old_region']}→{item['merged_into']}"
                for item in revisions if item["decision"] == "merge"
            ]
            removals = [
                item["old_region"]
                for item in revisions if item["decision"] == "remove"
            ]
            details.append("Region Reviewer 返回了需要主 Agent 重报的完整修订")
            if added:
                details.append("当前 regions 新增：" + "、".join(added))
            if removed:
                details.append("当前 regions 不再包含：" + "、".join(removed))
            if merges:
                details.append("合并归属：" + "、".join(merges))
            if removals:
                details.append("移除：" + "、".join(removals))
        if review_reason:
            details.append(f"Reviewer: {review_reason}")
        reason = "；".join(details) or "Region Reviewer 没有返回可采用的完整修订"
        rejection = _region_review_rejection(
            host, update, scene, history, reason=reason, review=result,
            review_attempt=review_attempt,
            review_screenshot=review_screenshot,
        )
        if review_attempt >= REGION_REVIEW_ATTEMPT_LIMIT:
            host.region_review_screenshots.pop(page_key, None)
        return None, rejection

    # Approval covers the current complete Region partition, so it supersedes
    # older Region-item corrections even when the Agent renamed a Region.
    # Entry corrections remain independent, and later runtime validation can
    # add fresh Region corrections using the current proposal names.
    resolved_correction_keys = ["page_update"]
    resolved_correction_keys.extend(
        key for key, item in (
            host.page_update_corrections.get(
                _page_key(canonical_page), {}) or {}
        ).items()
        if item.get("kind") == "region"
    )
    _update_page_corrections(
        host, canonical_page,
        accepted_keys=resolved_correction_keys, rejected_items=(),
    )
    host.region_review_screenshots.pop(page_key, None)
    reviewed_update = PageUpdate(
        page_name=update.page_name,
        regions=deepcopy(update.regions),
        new_entries=deepcopy(update.new_entries),
        omitted_regions=deepcopy(update.omitted_regions),
        entry_resolutions=deepcopy(update.entry_resolutions),
    )
    resurvey = host.pending_page_resurveys.get(page_key)
    if isinstance(resurvey, dict):
        resurvey["region_review_generation"] = str(
            host.entry_review_evidence_generation)
    history.append({
        "kind": "region_review_result",
        "screen": canonical_page,
        "status": "accepted",
        "review_attempt": review_attempt,
        "review_attempt_limit": REGION_REVIEW_ATTEMPT_LIMIT,
        "detail": review_reason[:800],
        "review": deepcopy(result),
    })
    return reviewed_update, ""


def _select_landing_page(
    host: AutonomousTraversalRuntime,
    turn: AutonomousTurn,
) -> str:
    """Validate and hold one Page decision without exposing Variant choices."""
    identity = turn.registration.identity
    requested = str(turn.screen_name or "").strip()
    if identity == "known":
        canonical = host.protocol_map.canonical_page_name(requested)
        if not canonical:
            return f"known page is not registered: {requested}"
        page = host.protocol_map.pages[canonical]
        host.pending_landing_page = PendingLandingPage(
            page_name=canonical,
            identity="known",
            summary=str(page.get("summary") or canonical),
            surface_kind=str(page.get("surface_kind") or "other"),
        )
        return ""
    if identity == "new":
        if host.protocol_map.canonical_page_name(requested):
            return (
                "new page reuses an existing natural name; rename it or "
                "mark it known"
            )
        host.pending_landing_page = PendingLandingPage(
            page_name=requested,
            identity="new",
            summary=requested,
        )
        return ""
    return "page identity remains uncertain; compare before registration"


def _commit_landing_variant(
    host: AutonomousTraversalRuntime,
    turn: AutonomousTurn,
    screenshot: bytes,
) -> tuple[Optional[ObservedScene], str]:
    """Commit Variant only after its owning Page has been resolved."""
    selected = host.pending_landing_page
    if selected is None:
        return None, "variant identity has no resolved Page owner"
    canonical_page, issue = host.protocol_map.observe(
        name=selected.page_name,
        summary=selected.summary or selected.page_name,
        identity=selected.identity,
        matched_page_name=(
            selected.page_name if selected.identity == "known" else ""
        ),
        surface_kind=selected.surface_kind or "other",
        regions=(),
        screenshot=screenshot,
        variant_name=turn.registration.variant_name,
        variant_identity=turn.registration.variant_identity,
        visible_predicates=turn.registration.visible_predicates,
        commit_regions=False,
    )
    if issue:
        return None, issue
    host.pending_landing_page = None
    return _register_scene(host, screenshot, turn, canonical_page), ""


def _pending_identity_view(
    pending: Optional[PendingPageIdentity],
) -> Optional[Dict[str, Any]]:
    if pending is None:
        return None
    return {"feedback": _page_identity_feedback(
        pending.status,
        pending.data,
        pending_review=True,
        stage=pending.stage,
    )}


def _page_identity_feedback(
    status: str,
    data: Dict[str, Any],
    *,
    pending_review: bool,
    stage: str = "combined",
) -> str:
    """Translate a specialist result into one readable message for the Agent."""
    page_name = str(
        data.get("matched_page_name") or data.get("page_name") or ""
    ).strip()
    stage = str(stage or "combined").strip().casefold()
    variant_name = str(data.get("variant_name") or "").strip()
    variant_identity = str(
        data.get("variant_identity") or "uncertain").strip()
    if stage == "variant":
        variant_verdict = {
            "known": f"匹配已登记 Variant“{variant_name}”",
            "new": f"“{variant_name}”是新的 material Variant",
            "uncertain": "Variant 身份仍不确定",
        }.get(variant_identity, "Variant 身份仍不确定")
        parts = [
            f"Page Identity specialist 判断：Page“{page_name}”下的"
            f"{variant_verdict}。"
        ]
    else:
        if status == "known":
            page_verdict = f"当前界面属于已登记 Page“{page_name}”"
        elif status == "new":
            page_verdict = f"当前界面是尚未登记的新 Page“{page_name}”"
        else:
            page_verdict = "目前无法可靠确定当前 Page"
        if stage == "page":
            parts = [f"Page Identity specialist 判断：{page_verdict}。"]
        else:
            variant_verdict = {
                "known": f"并匹配已登记 Variant“{variant_name}”",
                "new": f"其中“{variant_name}”是新的 material Variant",
                "uncertain": "且 Variant 身份仍不确定",
            }.get(variant_identity, "且 Variant 身份仍不确定")
            parts = [
                f"Page Identity specialist 判断：{page_verdict}，"
                f"{variant_verdict}。"
            ]
    reason = str(data.get("reason") or "").strip()
    if reason:
        parts.append(f"理由：{reason}")
    supporting = [
        str(item).strip() for item in data.get("supporting_evidence") or []
        if str(item).strip()
    ][:3]
    conflicting = [
        str(item).strip() for item in data.get("conflicting_evidence") or []
        if str(item).strip()
    ][:3]
    if supporting:
        parts.append("支持证据：" + "；".join(supporting))
    if conflicting:
        parts.append("冲突证据：" + "；".join(conflicting))
    if pending_review:
        pending_object = (
            "Page" if stage == "page"
            else "Variant" if stage == "variant"
            else "Page/Variant"
        )
        parts.append(
            f"该判断尚未写入 {pending_object} 地图；请结合当前截图接受、"
            "拒绝或保留不确定。"
        )
    else:
        parts.append("Page/Variant 地图未作更改。")
    return " ".join(parts)


def _pending_tool_view(
    host: AutonomousTraversalRuntime,
) -> Optional[Dict[str, Any]]:
    return _pending_identity_view(host.pending_page_identity)


def _review_page_identity(
    host: AutonomousTraversalRuntime,
    turn: AutonomousTurn,
    screenshot: bytes,
    history: List[Dict[str, Any]],
) -> tuple[Optional[ObservedScene], str, bool]:
    pending = host.pending_page_identity
    if pending is None:
        return None, "", False
    review = turn.previous_tool_review
    if review is None:
        return None, "pending page_identity requires previous_tool_review", True
    record = {
        "kind": "tool_review",
        "screen": turn.screen_name,
        "tool_name": "page_identity",
        "identity_review": asdict(review),
        "reviewed_result": {
            "status": pending.status,
            "data": dict(pending.data),
        },
    }
    history.append(record)
    if review.decision == "reject":
        host.identity_feedback = {
            "decision": "reject",
            "reason": review.reason,
        }
        host.pending_page_identity = None
        record["outcome"] = "rejected"
        return None, "", True
    if review.decision == "uncertain":
        record["outcome"] = "unresolved"
        return None, "", True

    data = pending.data
    if pending.stage == "page":
        page_name = str(
            data.get("matched_page_name") or data.get("page_name") or ""
        ).strip()
        host.pending_page_identity = None
        if pending.status == "known":
            canonical = host.protocol_map.canonical_page_name(page_name)
            if not canonical:
                issue = f"known page is not registered: {page_name}"
                record.update({"outcome": "commit_rejected", "detail": issue})
                return None, issue, True
            page_name = canonical
            page = host.protocol_map.pages[canonical]
            summary = str(page.get("summary") or canonical)
            surface_kind = str(page.get("surface_kind") or "other")
        elif pending.status == "new":
            if not page_name or host.protocol_map.canonical_page_name(page_name):
                issue = (
                    "new page reuses an existing natural name; rename it or "
                    "mark it known"
                )
                record.update({"outcome": "commit_rejected", "detail": issue})
                return None, issue, True
            summary = str(data.get("summary") or page_name)
            surface_kind = str(data.get("surface_kind") or "other")
        else:
            record["outcome"] = "unresolved"
            return None, "page identity remains uncertain", True
        host.pending_landing_page = PendingLandingPage(
            page_name=page_name,
            identity=pending.status,
            summary=summary,
            surface_kind=surface_kind,
        )
        record["outcome"] = "accepted"
        return None, "", True
    if pending.stage == "variant":
        selected = host.pending_landing_page
        host.pending_page_identity = None
        if selected is None:
            issue = "variant identity has no resolved Page owner"
            record.update({"outcome": "commit_rejected", "detail": issue})
            return None, issue, True
        canonical_page, issue = host.protocol_map.observe(
            name=selected.page_name,
            summary=selected.summary or selected.page_name,
            identity=selected.identity,
            matched_page_name=(
                selected.page_name if selected.identity == "known" else ""
            ),
            surface_kind=selected.surface_kind or "other",
            regions=(),
            screenshot=screenshot,
            variant_name=str(data.get("variant_name") or ""),
            variant_identity=str(
                data.get("variant_identity") or pending.status),
            visible_predicates=list(data.get("visible_predicates") or []),
            commit_regions=False,
        )
        if issue:
            record.update({"outcome": "commit_rejected", "detail": issue})
            return None, issue, True
        host.pending_landing_page = None
        record["outcome"] = "accepted"
        return _register_scene(
            host, screenshot, turn, canonical_page), "", True
    page_name = str(data.get("page_name") or "").strip()
    canonical_page, issue = host.protocol_map.observe(
        name=page_name,
        summary=str(data.get("summary") or turn.screen_name),
        identity=pending.status,
        matched_page_name=str(data.get("matched_page_name") or ""),
        surface_kind=str(data.get("surface_kind") or "other"),
        regions=(),
        screenshot=screenshot,
        variant_name=str(data.get("variant_name") or ""),
        variant_identity=str(data.get("variant_identity") or "uncertain"),
        visible_predicates=list(data.get("visible_predicates") or []),
        commit_regions=False,
    )
    host.pending_page_identity = None
    if issue:
        host.identity_feedback = {
            "decision": "reject",
            "reason": "accepted proposal could not be committed",
            "correction": issue,
        }
        record.update({"outcome": "commit_rejected", "detail": issue})
        return None, issue, True
    record["outcome"] = "accepted"
    return _register_scene(host, screenshot, turn, canonical_page), "", True
