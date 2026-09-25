"""Stage Qwen Entry candidates and commit reviewed Entry decisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_agent import ENTRY_REVIEW_ATTEMPT_LIMIT
from .autonomous_context import _shared_region_entry_candidates
from .autonomous_entry_review import (
    _entry_review_key,
    _entry_review_region_names,
)
from .autonomous_page_commit import _apply_main_agent_page_update
from .autonomous_page_update import (
    _normalize_new_entry_item,
    _normalize_page_region_item,
    _page_update_item_key,
    _page_update_item_rejection,
    _update_page_corrections,
)
from .autonomous_prompt import _rejection_feedback
from .autonomous_region_tools import screenshot_frame_id
from .autonomous_runtime import AutonomousTraversalRuntime
from .autonomous_turn import EntryReview, ObservedScene, PageUpdate, _page_key


def _coverage_entry_signature(items: Sequence[Any]) -> List[str]:
    """Return the exact visible Entry set used by one coverage version."""
    signature = set()
    for item in items:
        if isinstance(item, dict):
            target = item.get("target")
            operation = item.get("operation") or target
        else:
            target = getattr(item, "target", "")
            operation = getattr(item, "operation", "") or target
        operation_key = _page_key(operation)
        target_key = _page_key(target)
        if operation_key and target_key:
            signature.add(f"{operation_key}:{target_key}")
    return sorted(signature)


def _entry_semantic_key(item: Any) -> tuple[str, str]:
    """Return one exact operation plus semantic-target identity."""
    if isinstance(item, dict):
        target = item.get("target")
        operation = item.get("operation") or target
    else:
        target = getattr(item, "target", "")
        operation = getattr(item, "operation", "") or target
    return (
        _page_key(operation),
        _page_key(target),
    )


def _focused_coverage_is_complete(
    snapshot: Dict[str, Any], region_names: Sequence[str],
) -> bool:
    region_keys = {_page_key(name) for name in region_names if _page_key(name)}
    regions = {
        _page_key(item.get("name")): item
        for item in snapshot.get("regions") or []
        if isinstance(item, dict) and item.get("name")
    }
    return bool(region_keys) and all(
        bool((regions.get(region_key) or {}).get("coverage_complete"))
        for region_key in region_keys
    )


def _stage_main_agent_page_update(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    scene: Optional[ObservedScene],
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    allow_same_frame_completion: bool = False,
    region_reviewed: bool = False,
    main_agent_reason: str = "",
    review_region_names: Optional[Sequence[str]] = None,
) -> str:
    """Commit Region facts, then expose only committed Regions for entry review."""
    requested_audit_regions = list(
        review_region_names or _entry_review_region_names(host, update))
    requested_audit_keys = {
        _page_key(name) for name in requested_audit_regions if _page_key(name)
    }
    for resolution in update.entry_resolutions:
        if not isinstance(resolution, dict):
            continue
        region_name = str(resolution.get("region_name") or "").strip()
        region_key = _page_key(region_name)
        if region_key and region_key not in requested_audit_keys:
            requested_audit_regions.append(region_name)
            requested_audit_keys.add(region_key)
    requested_coverage_by_key: Dict[str, bool] = {}
    staged_regions: List[Any] = []
    rejected_entry_inputs: List[Any] = []
    for index, raw in enumerate(update.regions):
        normalized, rejection = _normalize_page_region_item(raw, index)
        if rejection is not None:
            staged_regions.append(raw)
            continue
        assert normalized is not None
        staged = deepcopy(normalized)
        staged_key = _page_key(staged.get("name"))
        if staged_key in requested_audit_keys:
            requested_coverage_by_key[staged_key] = (
                staged.get("coverage_complete") is True)
            staged["coverage_complete"] = False
        staged_regions.append(staged)
    candidates: List[Dict[str, Any]] = []
    for index, raw in enumerate(update.new_entries):
        normalized, rejection = _normalize_new_entry_item(raw, index)
        if rejection is not None:
            rejected_entry_inputs.append(raw)
            continue
        assert normalized is not None
        candidates.append(normalized)
    apply_result: Dict[str, Any] = {}
    issue = _apply_main_agent_page_update(
        host,
        PageUpdate(
            page_name=update.page_name,
            regions=staged_regions,
            new_entries=rejected_entry_inputs,
        ),
        scene,
        screenshot,
        history,
        allow_same_frame_completion=allow_same_frame_completion,
        region_reviewed=region_reviewed,
        result_out=apply_result,
    )
    if issue or scene is None:
        return issue
    mapped_sources = apply_result.get("mapped_region_sources") or {}
    initially_rejected_region_keys = {
        _page_key(item.get("region_name"))
        for item in apply_result.get("rejected_items") or []
        if isinstance(item, dict) and item.get("region_name")
    }
    inherited: Dict[str, Dict[str, Any]] = {}
    for requested_name in requested_audit_regions:
        region_key = _page_key(requested_name)
        source = mapped_sources.get(region_key)
        if (
            requested_coverage_by_key.get(region_key) is not True
            or not isinstance(source, dict)
            or region_key in initially_rejected_region_keys
        ):
            continue
        region_candidates = [
            item for item in candidates
            if _page_key(item.get("region_name")) == region_key
        ]
        signature = _coverage_entry_signature(region_candidates)
        version = host.region_registry.mapped_coverage_version(
            region_ref=str(source.get("region_ref") or ""),
            source_page=str(source.get("source_page") or ""),
            source_region=str(source.get("source_region") or ""),
            target_page=scene.page_name,
            target_region=requested_name,
            entry_signature=signature,
        )
        if version:
            inherited[region_key] = {
                **source,
                "region_name": requested_name,
                "entry_signature": signature,
                "coverage_version": version,
                "candidates": region_candidates,
            }
    if inherited:
        inherited_candidates = [
            item for item in candidates
            if _page_key(item.get("region_name")) in inherited
        ]
        inherited_apply: Dict[str, Any] = {}
        if inherited_candidates:
            issue = _apply_main_agent_page_update(
                host,
                PageUpdate(
                    page_name=update.page_name,
                    regions=[],
                    new_entries=inherited_candidates,
                ),
                scene,
                screenshot,
                history,
                result_out=inherited_apply,
            )
            if issue:
                return issue
        rejected_inherited = {
            _page_key(item.get("region_name"))
            for item in inherited_apply.get("rejected_items") or []
            if isinstance(item, dict) and item.get("region_name")
        }
        state = host.region_states.get(_page_key(scene.page_name))
        page_audits = host.entry_review_audits.setdefault(
            _page_key(scene.page_name), {})
        inherited_keys = set()
        for region_key, record in inherited.items():
            if region_key in rejected_inherited or state is None:
                continue
            version = host.region_registry.inherit_mapped_coverage(
                region_ref=str(record.get("region_ref") or ""),
                source_page=str(record.get("source_page") or ""),
                source_region=str(record.get("source_region") or ""),
                target_page=scene.page_name,
                target_region=str(record.get("region_name") or ""),
                entry_signature=record.get("entry_signature") or [],
            )
            if not version:
                continue
            region_name = str(record.get("region_name") or "")
            host.region_registry.mark_state_visible(
                page_name=scene.page_name,
                region_name=region_name,
                state_id=scene.state_id,
            )
            state.set_coverage_complete(region_name, True)
            state.set_coverage_evidence(
                region_name, version=version, basis="batch_region_mapping")
            page_audits[region_key] = {
                "page_name": scene.page_name,
                "region_name": region_name,
                "frame_id": screenshot_frame_id(screenshot),
                "status": "complete",
                "coverage_basis": "shared_region_mapping",
                "coverage_version": version,
                "source_page": str(record.get("source_page") or ""),
                "source_region": str(record.get("source_region") or ""),
                "mapping_reason": str(record.get("reason") or ""),
                "kept": [{
                    "region_name": item.get("region_name"),
                    "operation": item.get("operation") or item.get("target"),
                    "subject": item.get("subject") or item.get("region_name"),
                    "target": item.get("target"),
                } for item in record.get("candidates") or []],
                "added": [],
                "dropped": [],
                "deferred": [],
                "deferred_regions": [],
            }
            inherited_keys.add(region_key)
            history.append({
                "kind": "shared_region_coverage_inherited",
                "screen": scene.page_name,
                "region_name": region_name,
                "region_ref": str(record.get("region_ref") or ""),
                "coverage_version": version,
                "source_page": str(record.get("source_page") or ""),
                "source_region": str(record.get("source_region") or ""),
                "detail": (
                    "Exact one-to-one batch Region mapping reused a reviewed "
                    "coverage version with the same Entry signature."
                ),
            })
        if inherited_keys:
            candidates = [
                item for item in candidates
                if _page_key(item.get("region_name")) not in inherited_keys
            ]
            requested_audit_regions = [
                name for name in requested_audit_regions
                if _page_key(name) not in inherited_keys
            ]
            requested_audit_keys.difference_update(inherited_keys)
            snapshot = state.snapshot() if state is not None else {}
            host.protocol_map.upsert_regions(
                scene.page_name, snapshot.get("regions") or [])
            if (
                _page_key(scene.page_name) in host.pending_page_resurveys
                and _focused_coverage_is_complete(snapshot, inherited_keys)
            ):
                host.pending_page_resurveys.pop(
                    _page_key(scene.page_name), None)
    existing_entry_by_key = {
        _entry_review_key({
            "region_name": entry.region_name,
            "operation": entry.operation or entry.target,
            "target": entry.target,
        }): entry
        for entry in host.entry_ledger.entries
        if _page_key(entry.page_name) == _page_key(scene.page_name)
    }
    repeated_existing_candidates = []
    filtered_candidates = []
    shared_by_region: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        existing = existing_entry_by_key.get(_entry_review_key(candidate))
        exact_entry: Any = None
        if existing is not None and _entry_semantic_key(candidate) == \
                _entry_semantic_key(existing):
            exact_entry = existing
        if exact_entry is None:
            region_key = _page_key(candidate.get("region_name"))
            if region_key not in shared_by_region:
                shared_by_region[region_key] = _shared_region_entry_candidates(
                    host,
                    scene.page_name,
                    str(candidate.get("region_name") or ""),
                )
            exact_entry = next((
                item for item in shared_by_region[region_key]
                if _entry_semantic_key(item) == _entry_semantic_key(candidate)
            ), None)
        if exact_entry is not None:
            repeated_existing_candidates.append({
                "region_name": candidate.get("region_name"),
                "target": candidate.get("target"),
                "operation": candidate.get("operation") or candidate.get("target"),
                "subject": candidate.get("subject") or candidate.get("region_name"),
                "entry_id": (
                    exact_entry.entry_id
                    if not isinstance(exact_entry, dict)
                    else exact_entry.get("entry_id")
                ),
            })
            continue
        filtered_candidates.append(candidate)
    candidates = filtered_candidates
    if repeated_existing_candidates:
        history.append({
            "kind": "entry_review_scope_normalized",
            "screen": scene.page_name,
            "ignored_existing_entries": repeated_existing_candidates,
            "detail": (
                "Inherited exact formal Entries instead of rediscovering them; "
                "the Reviewer still audits new semantics and Region coverage."
            ),
        })
    if not candidates and not requested_audit_regions:
        return ""

    accepted_region_keys = {
        _page_key(name) for name in apply_result.get("accepted_regions") or []
    }
    pre_rejected_entry_region_keys = {
        _page_key(item.get("region_name"))
        for item in apply_result.get("rejected_items") or []
        if (
            isinstance(item, dict)
            and item.get("kind") == "new_entry"
            and _page_key(item.get("region_name"))
        )
    }
    pre_rejected_entry_all_audits = any(
        isinstance(item, dict)
        and item.get("kind") == "new_entry"
        and not _page_key(item.get("region_name"))
        for item in apply_result.get("rejected_items") or []
    )
    state = host.region_states.get(_page_key(scene.page_name))
    snapshot = state.snapshot() if state is not None else {}
    formal_by_key = {
        _page_key(region.get("name")): region
        for region in snapshot.get("regions") or []
        if isinstance(region, dict) and region.get("name")
    }
    current_bboxes = snapshot.get("current_bboxes") or {}
    review_regions: List[Dict[str, Any]] = []
    coverage_audit_regions: List[str] = []
    coverage_requested: Dict[str, bool] = {}
    invalid_audit_regions: List[str] = []
    for requested_name in requested_audit_regions:
        region_key = _page_key(requested_name)
        region = formal_by_key.get(region_key)
        registry_ref = host.region_registry.region_ref(
            scene.page_name, requested_name)
        if (
            region_key not in accepted_region_keys
            or not isinstance(region, dict)
            or not registry_ref
            or registry_ref != str(region.get("region_ref") or "")
        ):
            invalid_audit_regions.append(str(requested_name))
            continue
        formal = deepcopy(region)
        bbox_record = current_bboxes.get(region_key)
        if isinstance(bbox_record, dict) and bbox_record.get("bbox_1000"):
            formal["bbox_1000"] = deepcopy(bbox_record["bbox_1000"])
        review_regions.append(formal)
        coverage_audit_regions.append(str(region.get("name") or requested_name))
        coverage_requested[region_key] = requested_coverage_by_key.get(
            region_key, False)

    audit_region_keys = {
        _page_key(name) for name in coverage_audit_regions
    }
    proposed_region_keys = {
        _page_key(item.get("name"))
        for item in update.regions
        if isinstance(item, dict) and _page_key(item.get("name"))
    }
    invalid_candidate_regions = sorted({
        str(item.get("region_name") or "")
        for item in candidates
        if _page_key(item.get("region_name")) not in audit_region_keys
    })
    if invalid_audit_regions or invalid_candidate_regions:
        invalid_candidate_keys = {
            _page_key(name) for name in invalid_candidate_regions
        }
        deferred_candidate_keys = (
            invalid_candidate_keys & proposed_region_keys
        )
        rejected_candidate_regions = [
            name for name in invalid_candidate_regions
            if _page_key(name) not in deferred_candidate_keys
        ]
        candidate_rejections = [
            _page_update_item_rejection(
                "new_entry",
                index,
                candidate,
                error_code="unknown_region_reference",
                field_name="region_name",
                reason=(
                    "region_name must reference a Region accepted into this "
                    "entry coverage audit"),
            )
            for index, candidate in enumerate(candidates)
            if _page_key(candidate.get("region_name"))
            in invalid_candidate_keys - deferred_candidate_keys
        ]
        if candidate_rejections:
            _update_page_corrections(
                host, scene.page_name, accepted_keys=(),
                rejected_items=candidate_rejections)
        if candidate_rejections:
            reason = (
                "entry review was not staged because candidate Regions must "
                "already be accepted and bound unless they are proposed in "
                "this page_update; unknown candidates="
                f"{rejected_candidate_regions[:4]}"
            )
            status = "rejected"
        else:
            reason = (
                "entry review was not staged; candidates owned by Regions in "
                "this page_update remain deferred until those Regions are "
                "accepted and bound in the formal partition; "
                f"regions={invalid_audit_regions[:4] or invalid_candidate_regions[:4]}"
            )
            status = "deferred"
        history.append({
            "kind": "entry_review_result",
            "screen": scene.page_name,
            "status": status,
            "detail": reason,
        })
        return reason

    current_audit_region_keys = {
        _page_key(name) for name in coverage_audit_regions if _page_key(name)
    }
    page_audits = host.entry_review_audits.get(
        _page_key(scene.page_name)) or {}
    prior_reviews = []
    for audit in page_audits.values():
        if audit.get("status") not in {"disagreement", "final_disagreement"}:
            continue
        disputed_region_keys = {
            _page_key(item.get("region_name"))
            for item in audit.get("dropped") or []
            if isinstance(item, dict) and _page_key(item.get("region_name"))
        } or {
            _page_key(name)
            for name in audit.get("coverage_audit_regions") or []
            if _page_key(name)
        }
        if (
            disputed_region_keys.intersection(current_audit_region_keys)
            and int(audit.get("discussion_evidence_generation", -1))
            == host.entry_review_evidence_generation
        ):
            prior_reviews.append(audit)
    previous_review = (
        max(
            prior_reviews,
            key=lambda audit: int(audit.get("review_attempt") or 0),
        )
        if prior_reviews else {}
    )
    previous_attempt = int(previous_review.get("review_attempt") or 0)
    if previous_review.get("status") == "final_disagreement":
        reason = (
            "The main Agent and Entry Reviewer already used the three allowed "
            "reviews for this page evidence without reaching one consistent "
            "candidate decision. No Entry or coverage fact was written. Obtain "
            "new GUI evidence before asking for another review."
        )
        history.append({
            "kind": "entry_review_result",
            "screen": scene.page_name,
            "status": "final_disagreement",
            "review_attempt": previous_attempt,
            "review_attempt_limit": ENTRY_REVIEW_ATTEMPT_LIMIT,
            "kept": deepcopy(previous_review.get("kept") or []),
            "added": deepcopy(previous_review.get("added") or []),
            "dropped": deepcopy(previous_review.get("dropped") or []),
            "deferred": deepcopy(previous_review.get("deferred") or []),
            "deferred_regions": deepcopy(
                previous_review.get("deferred_regions") or []),
            "reason_consistent": previous_review.get("reason_consistent"),
            "reviewer_reason": str(
                previous_review.get("reviewer_reason") or ""),
            "detail": reason,
            "rejection": _rejection_feedback(
                "entry_review_discussion_exhausted",
                reason,
                correction=(
                    "Do not resubmit the same page evidence. First perform a "
                    "GUI action that can reveal new evidence, then describe "
                    "what changed in natural language."
                ),
            ),
        })
        return reason

    disputed_by_key = {
        _entry_review_key(item): item
        for item in previous_review.get("dropped") or []
        if isinstance(item, dict) and _entry_review_key(item)
    }
    resolved_previous_drops = []
    review_entry_resolutions: List[Dict[str, Any]] = []
    if disputed_by_key:
        resolutions = [
            item for item in update.entry_resolutions
            if isinstance(item, dict) and _entry_review_key(item)
        ]
        resolution_by_key = {
            _entry_review_key(item): item for item in resolutions
        }
        resolution_keys = set(resolution_by_key)
        missing = set(disputed_by_key) - resolution_keys
        candidate_keys = {
            _entry_review_key(item)
            for item in candidates if isinstance(item, dict)
        }
        unknown = resolution_keys - set(disputed_by_key)
        redundant_keeps = {
            key for key in unknown
            if (
                key in candidate_keys
                and str(
                    resolution_by_key[key].get("decision") or ""
                ).strip().casefold() == "keep"
                and str(resolution_by_key[key].get("reason") or "").strip()
            )
        }
        invalid_unknown = unknown - redundant_keeps
        errors = []
        if len(resolution_by_key) != len(resolutions):
            errors.append("entry_resolutions 含重复候选")
        if missing:
            errors.append(
                "entry_resolutions 遗漏：" + "；".join(
                    f"{disputed_by_key[key].get('region_name')} / "
                    f"{disputed_by_key[key].get('target')}"
                    for key in sorted(missing)
                )
            )
        if invalid_unknown:
            errors.append("entry_resolutions 含非争议候选")
        for key in set(disputed_by_key).intersection(resolution_keys):
            item = resolution_by_key[key]
            decision = str(item.get("decision") or "").strip().casefold()
            if decision not in {"keep", "drop"} or not str(
                    item.get("reason") or "").strip():
                errors.append("entry_resolutions 缺少 keep/drop 或具体理由")
            elif decision == "keep" and key not in candidate_keys:
                errors.append("决定 keep 的候选仍须出现在所属区域 entries")
            elif decision == "drop" and key in candidate_keys:
                errors.append("决定 drop 的候选不能继续出现在所属区域 entries")
            elif decision == "drop":
                resolved_previous_drops.append(
                    deepcopy(disputed_by_key[key]))
        if errors:
            detail = "；".join(dict.fromkeys(errors))
            history.append({
                "kind": "protocol_feedback",
                "screen": scene.page_name,
                "outcome": "not_executed",
                "detail": detail,
                "rejection": _rejection_feedback(
                    "entry_resolution_incomplete",
                    detail,
                    retry_after="every_disputed_entry_is_resolved",
                    correction=(
                        "上一轮每个争议候选都要在 page_update.entry_resolutions "
                        "中恰好出现一次并给出 keep 或 drop 及具体理由；keep 项"
                        "继续放在所属区域 entries，drop 项不再放入。"
                    ),
                ),
            })
            return detail
        if redundant_keeps:
            history.append({
                "kind": "entry_resolution_scope_normalized",
                "screen": scene.page_name,
                "ignored_redundant_keeps": [
                    deepcopy(item) for item in resolutions
                    if _entry_review_key(item) in redundant_keeps
                ],
                "detail": (
                    "Ignored keep resolutions for candidates the Reviewer "
                    "already retained; they do not change the dispute or "
                    "formal Entry facts."
                ),
            })
        review_entry_resolutions = [
            deepcopy(item) for item in resolutions
            if _entry_review_key(item) in disputed_by_key
        ]

    shared_region_entries = []
    for region_name in coverage_audit_regions:
        entries = [{
            key: value for key, value in candidate.items()
            if key not in {"page", "region"}
        } for candidate in _shared_region_entry_candidates(
            host, scene.page_name, region_name,
        )]
        if entries:
            formal_region = formal_by_key.get(_page_key(region_name)) or {}
            shared_region_entries.append({
                "region_name": region_name,
                "description": str(
                    formal_region.get("summary") or "").strip(),
                "entries": entries,
            })
    review_frame_id = screenshot_frame_id(screenshot)
    host.entry_review_screenshot = bytes(screenshot)
    host.pending_entry_review = {
        "page_name": scene.page_name,
        "variant_name": scene.variant_name,
        "state_id": scene.state_id,
        "frame_id": review_frame_id,
        "discussion_evidence_generation": host.entry_review_evidence_generation,
        "review_attempt": previous_attempt + 1,
        "review_attempt_limit": ENTRY_REVIEW_ATTEMPT_LIMIT,
        "previous_review": deepcopy(previous_review),
        "resolved_previous_drops": resolved_previous_drops,
        "entry_resolutions": review_entry_resolutions,
        "regions": review_regions,
        "candidates": candidates,
        "shared_region_entries": shared_region_entries,
        "coverage_audit_regions": coverage_audit_regions,
        "coverage_requested": coverage_requested,
        "pre_rejected_entry_region_keys": sorted(
            pre_rejected_entry_region_keys),
        "pre_rejected_entry_all_audits": (
            pre_rejected_entry_all_audits),
        "main_agent_reason": str(main_agent_reason or "").strip(),
    }
    history.append({
        "kind": "entry_review_pending",
        "screen": scene.page_name,
        "outcome": "coverage_not_certified",
        "candidates": [{
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "subject": item.get("subject") or item.get("region_name"),
            "target": item.get("target"),
        } for item in candidates],
        "coverage_audit_regions": coverage_audit_regions,
        "detail": (
            "Committed Region facts are read-only; entry candidates and "
            "coverage await one independent Entry Reviewer call."
        ),
    })
    return ""


def _apply_entry_review(
    host: AutonomousTraversalRuntime,
    review: Optional[EntryReview],
    scene: Optional[ObservedScene],
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    reviewer_reason: str = "",
    reason_consistent: Optional[bool] = None,
) -> str:
    pending = host.pending_entry_review
    if not isinstance(pending, dict):
        return ""

    audit_region_names = [
        str(name).strip()
        for name in pending.get("coverage_audit_regions") or []
        if str(name).strip()
    ]
    audit_scope_text = "、".join(audit_region_names) or "本轮明确提供的区域"

    def reject(reason: str, *, correction: str = "") -> str:
        exact_correction = correction.strip() or (
            f"本轮只审核区域：{audit_scope_text}。具体错误：{reason}。"
            "只返回这些区域内当前可见的入口；不要重报其他区域的已知入口。"
            "如果本轮区域没有可见交互入口，independent_entries 返回空数组。"
        )
        rejection = _rejection_feedback(
            "entry_review_invalid",
            reason,
            retry_after="candidate_selection_uses_exact_region_and_target",
            correction=exact_correction,
        )
        pending["previous_rejection"] = deepcopy(rejection)
        history.append({
            "kind": "entry_review_result",
            "screen": scene.page_name if scene is not None else "",
            "status": "rejected",
            "detail": reason,
            "rejection": rejection,
        })
        return reason

    if review is None:
        return reject("entry_review is required for the pending candidates")
    if scene is None:
        return reject("entry review requires a registered current Page")
    pending_page = str(pending.get("page_name") or "").strip()
    if _page_key(scene.page_name) != _page_key(pending_page):
        return reject(
            f"entry candidates belong to {pending_page!r}, but the current "
            f"Page is {scene.page_name!r}"
        )
    candidates = [
        item for item in pending.get("candidates") or []
        if isinstance(item, dict)
    ]
    candidate_keys = {_entry_review_key(item) for item in candidates}
    independent_by_key = {
        _entry_review_key(item): deepcopy(item)
        for item in review.independent_entries
    }
    record_only_by_key = {
        _entry_review_key(item): deepcopy(item)
        for item in review.record_only_entries
    }
    shared_ids_by_region: Dict[str, set[str]] = {}
    shared_entries_by_region: Dict[str, List[Dict[str, Any]]] = {}
    shared_entry_by_region_and_id: Dict[
        tuple[str, str], Dict[str, Any]
    ] = {}
    for region_group in pending.get("shared_region_entries") or []:
        if not isinstance(region_group, dict):
            continue
        region_key = _page_key(region_group.get("region_name"))
        if not region_key:
            continue
        for candidate in region_group.get("entries") or []:
            if not isinstance(candidate, dict):
                continue
            entry_id = str(candidate.get("entry_id") or "").strip()
            if entry_id:
                shared_ids_by_region.setdefault(
                    region_key, set()).add(entry_id)
                shared_entry_by_region_and_id[(region_key, entry_id)] = candidate
            shared_entries_by_region.setdefault(region_key, []).append(candidate)
    for item in independent_by_key.values():
        representative_id = str(
            item.get("equivalent_to_entry_id") or "").strip()
        equivalence_reason = str(
            item.get("equivalence_reason") or "").strip()
        if bool(representative_id) != bool(equivalence_reason):
            return reject(
                "entry_review equivalence requires both an exact "
                "equivalent_to_entry_id and a concrete equivalence_reason")
        if (
            representative_id
            and representative_id not in shared_ids_by_region.get(
                _page_key(item.get("region_name")), set())
        ):
            known_entry = next((
                entry for entry in host.entry_ledger.entries
                if entry.entry_id == representative_id
            ), None)
            returned_region = str(item.get("region_name") or "").strip()
            owner_detail = (
                f"它属于区域“{known_entry.region_name}”"
                if known_entry is not None else
                "它不是本轮提供的已知规范入口"
            )
            return reject(
                "entry_review cited an entry that was not exposed as a "
                "canonical Entry for that committed shared Region: "
                f"{representative_id}",
                correction=(
                    f"本轮只审核区域：{audit_scope_text}。你在区域“{returned_region}”"
                    f"返回了入口 {representative_id}，{owner_detail}，且它没有出现在"
                    "本轮 shared_region_entries 中，因此不能填写 "
                    "equivalent_to_entry_id。不要返回该入口或其他审核范围外入口；"
                    "如果当前审核区域没有可见交互入口，independent_entries 返回空数组。"
                ),
            )
        if representative_id:
            region_key = _page_key(item.get("region_name"))
            representative = shared_entry_by_region_and_id.get(
                (region_key, representative_id)) or {}
            if _entry_semantic_key(item) != _entry_semantic_key(representative):
                return reject(
                    "entry_review equivalence must preserve the exact operation "
                    "and semantic target exposed by the cited Entry",
                    correction=(
                        f"入口 {representative_id} 的正式身份是操作“"
                        f"{representative.get('operation') or representative.get('target')}”"
                        f"、控件“{representative.get('target')}”；本轮候选是操作“"
                        f"{item.get('operation') or item.get('target')}”、控件“"
                        f"{item.get('target')}”。两者不精确一致，不能复用该编号。"
                        "请把当前候选作为独立入口审核，或引用动作与控件名都精确一致的编号。"
                    ),
                )
    selected_keys = set(independent_by_key).intersection(candidate_keys)
    recorded_keys = set(record_only_by_key).intersection(candidate_keys)
    deferred_items = [
        item for item in review.deferred_entries if isinstance(item, dict)
    ]
    deferred_keys = {
        _entry_review_key(item) for item in review.deferred_entries
    }
    non_task_items = [
        item for item in (review.non_task_entries or [])
        if isinstance(item, dict)
    ]
    non_task_keys = {
        _entry_review_key(item) for item in non_task_items
    }
    ignored_deferred = [
        deepcopy(item) for item in deferred_items
        if _entry_review_key(item) not in candidate_keys
    ]
    ignored_non_tasks = [
        deepcopy(item) for item in non_task_items
        if _entry_review_key(item) not in candidate_keys
    ]
    if ignored_deferred or ignored_non_tasks:
        history.append({
            "kind": "entry_review_scope_normalized",
            "screen": pending_page,
            "ignored_deferred_entries": ignored_deferred,
            "ignored_non_task_entries": ignored_non_tasks,
            "detail": (
                "Ignored classifications for entries that are not pending in "
                "this review; they cannot change Entry or coverage facts."
            ),
        })
        deferred_keys.intersection_update(candidate_keys)
        non_task_keys.intersection_update(candidate_keys)
    overlap = sorted(
        (set(independent_by_key) & set(record_only_by_key))
        | (set(independent_by_key) & deferred_keys)
        | (set(independent_by_key) & non_task_keys)
        | (set(record_only_by_key) & deferred_keys)
        | (set(record_only_by_key) & non_task_keys)
        | (deferred_keys & non_task_keys)
    )
    if overlap:
        return reject(
            "entry_review cannot classify the same candidate more than once: "
            f"{overlap[:4]}"
        )
    if review.non_task_entries is not None:
        unclassified = sorted(
            candidate_keys - selected_keys - recorded_keys
            - deferred_keys - non_task_keys)
        if unclassified:
            return reject(
                "entry_review did not classify every pending candidate: "
                f"{unclassified[:4]}",
                correction=(
                    "每个原候选必须且只能出现一次：值得探索的写入 "
                    "independent_entries；值得记录但无需专门探索的写入 "
                    "record_only_entries；静态、危险或无命令语义的写入 "
                    "non_task_entries；看不清，或有探索价值但因当前前置"
                    "状态不可执行的写入 deferred_entries。"
                ),
            )
    selected = []
    for item in candidates:
        key = _entry_review_key(item)
        if key not in selected_keys:
            continue
        selected_item = deepcopy(item)
        reviewed_item = independent_by_key[key]
        for field_name in (
            "equivalent_to_entry_id", "equivalence_reason",
        ):
            if reviewed_item.get(field_name):
                selected_item[field_name] = reviewed_item[field_name]
        selected.append(selected_item)
    recorded = []
    for item in candidates:
        key = _entry_review_key(item)
        if key not in recorded_keys:
            continue
        recorded_item = deepcopy(item)
        recorded_item["exploration_policy"] = "record_only"
        recorded.append(recorded_item)
    known_region_keys = {
        _page_key(item.get("name"))
        for item in pending.get("regions") or []
        if isinstance(item, dict) and item.get("name")
    }
    coverage_audit_regions = [
        str(name).strip() for name in pending.get("coverage_audit_regions") or []
        if str(name).strip()
    ]
    unknown_audit_regions = sorted({
        name for name in coverage_audit_regions
        if _page_key(name) not in known_region_keys
    })
    if unknown_audit_regions:
        return reject(
            "entry_review coverage audit included Regions that were not "
            f"exposed for this review: {unknown_audit_regions[:4]}"
        )
    audit_region_keys = {
        _page_key(name) for name in coverage_audit_regions
    }
    unknown_candidate_regions = sorted({
        str(item.get("region_name") or "")
        for item in candidates
        if _page_key(item.get("region_name")) not in audit_region_keys
    })
    if unknown_candidate_regions:
        return reject(
            "entry_review candidates used Regions outside the coverage audit: "
            f"{unknown_candidate_regions[:4]}"
        )
    deferred_region_names = [
        str(name).strip() for name in review.deferred_regions
        if str(name).strip()
    ]
    ignored_deferred_regions = sorted({
        name for name in deferred_region_names
        if _page_key(name) not in audit_region_keys
    })
    if ignored_deferred_regions:
        history.append({
            "kind": "entry_review_scope_normalized",
            "screen": pending_page,
            "ignored_deferred_regions": ignored_deferred_regions,
            "detail": (
                "Ignored conservative Region deferrals outside this focused "
                "coverage audit; they cannot change formal coverage facts."
            ),
        })
        deferred_region_names = [
            name for name in deferred_region_names
            if _page_key(name) in audit_region_keys
        ]
    missed_by_key = {
        key: item for key, item in independent_by_key.items()
        if key not in candidate_keys
    }
    recorded_missed_by_key = {
        key: item for key, item in record_only_by_key.items()
        if key not in candidate_keys
    }
    outside_audit_items = [
        item for item in missed_by_key.values()
        if _page_key(item.get("region_name")) not in audit_region_keys
    ]
    outside_audit_items.extend(
        item for item in recorded_missed_by_key.values()
        if _page_key(item.get("region_name")) not in audit_region_keys
    )
    if outside_audit_items:
        outside_region_names = sorted({
            str(item.get("region_name") or "")
            for item in outside_audit_items
        })
        returned_details = "；".join(
            f"区域“{str(item.get('region_name') or '').strip()}”中的“"
            f"{str(item.get('target') or '').strip()}”"
            for item in outside_audit_items[:4]
        )
        return reject(
            "entry_review added entries under Regions outside this coverage "
            f"audit: {outside_region_names[:4]}",
            correction=(
                f"本轮只审核区域：{audit_scope_text}。你额外返回了{returned_details}；"
                "这些入口不属于本轮审核区域，因此不能出现在 independent_entries 中。"
                "请删除这些越界入口，只返回当前审核区域内的可见入口；如果当前审核区域"
                "没有可见交互入口，independent_entries 返回空数组。"
            ),
        )
    existing_entry_by_key = {
        _entry_review_key({
            "region_name": entry.region_name,
            "target": entry.target,
        }): entry
        for entry in host.entry_ledger.entries
        if _page_key(entry.page_name) == _page_key(pending_page)
        and _page_key(entry.region_name) in audit_region_keys
    }
    ignored_existing_entries = []
    for new_items in (missed_by_key, recorded_missed_by_key):
        for key, item in list(new_items.items()):
            existing = existing_entry_by_key.get(key)
            exact_entry: Any = None
            if existing is not None and _entry_semantic_key(item) == \
                    _entry_semantic_key(existing):
                exact_entry = existing
            if exact_entry is None:
                exact_entry = next((
                    candidate for candidate in shared_entries_by_region.get(
                        _page_key(item.get("region_name")), [])
                    if _entry_semantic_key(candidate)
                    == _entry_semantic_key(item)
                ), None)
            if exact_entry is None:
                continue
            ignored_existing_entries.append({
                "region_name": item.get("region_name"),
                "target": item.get("target"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "entry_id": (
                    exact_entry.entry_id
                    if not isinstance(exact_entry, dict)
                    else exact_entry.get("entry_id")
                ),
            })
            new_items.pop(key, None)
    if ignored_existing_entries:
        history.append({
            "kind": "entry_review_scope_normalized",
            "screen": pending_page,
            "ignored_existing_entries": ignored_existing_entries,
            "detail": (
                "Ignored exact existing Entries returned as new review findings; "
                "no Entry or coverage fact was changed."
            ),
        })
    missed = list(missed_by_key.values())
    recorded_missed = [
        {**deepcopy(item), "exploration_policy": "record_only"}
        for item in recorded_missed_by_key.values()
    ]
    deferred = [
        {
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "subject": item.get("subject") or item.get("region_name"),
            "target": item.get("target"),
        }
        for item in candidates
        if _entry_review_key(item) in deferred_keys
    ]
    dropped_keys = (
        non_task_keys if review.non_task_entries is not None else (
            candidate_keys - selected_keys - deferred_keys)
    )
    dropped = [
        {
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "target": item.get("target"),
        }
        for item in candidates
        if _entry_review_key(item) in dropped_keys
    ]
    deferred_region_keys = {
        _page_key(item.get("region_name")) for item in deferred
    }
    deferred_region_keys.update(
        _page_key(name) for name in deferred_region_names
    )
    state = host.region_states.get(_page_key(pending_page))
    if state is None:
        return reject("entry review lost its committed formal Region state")
    formal_region_by_key = {
        _page_key(item.get("name")): item
        for item in state.snapshot().get("regions") or []
        if isinstance(item, dict) and item.get("name")
    }
    unbound_audit_regions = sorted({
        name for name in coverage_audit_regions
        if (
            _page_key(name) not in formal_region_by_key
            or host.region_registry.region_ref(pending_page, name)
            != str(
                formal_region_by_key.get(_page_key(name), {}).get(
                    "region_ref") or "")
        )
    })
    if unbound_audit_regions:
        return reject(
            "entry review can only audit Regions in the committed formal "
            f"partition: {unbound_audit_regions[:4]}")

    review_consistent = reason_consistent is not False
    review_attempt = max(1, int(pending.get("review_attempt") or 1))
    review_attempt_limit = max(
        review_attempt,
        int(pending.get("review_attempt_limit") or ENTRY_REVIEW_ATTEMPT_LIMIT),
    )
    disputed_region_keys = (
        set(audit_region_keys)
        if not review_consistent else {
            _page_key(item.get("region_name"))
            for item in dropped
            if _page_key(item.get("region_name"))
        }
    )
    disagreement = bool(disputed_region_keys)
    mixed_disagreement = bool(
        disagreement
        and review_consistent
        and disputed_region_keys != audit_region_keys
    )
    if disagreement:
        final_disagreement = review_attempt >= review_attempt_limit
        audit_status = (
            "final_disagreement" if final_disagreement else "disagreement")
        for region_name in coverage_audit_regions:
            if _page_key(region_name) in disputed_region_keys:
                state.set_coverage_complete(region_name, False)
        if deferred_region_keys:
            deferred_frames = host.entry_review_deferred_frames.setdefault(
                _page_key(pending_page), {})
            current_frame_id = screenshot_frame_id(screenshot)
            for region_key in deferred_region_keys:
                deferred_frames[region_key] = current_frame_id
        page_audits = host.entry_review_audits.setdefault(
            _page_key(pending_page), {})
        audit_record = {
            "page_name": pending_page,
            "frame_id": screenshot_frame_id(screenshot),
            "status": audit_status,
            "coverage_basis": "visual_entry_reviewer",
            "coverage_audit_regions": deepcopy(coverage_audit_regions),
            "discussion_evidence_generation": int(
                pending.get("discussion_evidence_generation", 0)),
            "review_attempt": review_attempt,
            "review_attempt_limit": review_attempt_limit,
            "main_agent_reason": str(
                pending.get("main_agent_reason") or "").strip(),
            "kept": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in selected],
            "added": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in missed],
            "recorded": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in [*recorded, *recorded_missed]],
            "dropped": deepcopy(dropped),
            "deferred": deepcopy(deferred),
            "deferred_regions": deepcopy(deferred_region_names),
            "reason_consistent": reason_consistent,
            "reviewer_reason": str(reviewer_reason or "").strip(),
            "ledger_committed": False,
        }
        for region_name in coverage_audit_regions:
            region_key = _page_key(region_name)
            if region_key not in disputed_region_keys:
                continue
            page_audits[region_key] = {
                **deepcopy(audit_record),
                "region_name": region_name,
                "coverage_audit_regions": [region_name],
                "kept": [
                    item for item in audit_record["kept"]
                    if _page_key(item.get("region_name")) == region_key
                ],
                "added": [
                    item for item in audit_record["added"]
                    if _page_key(item.get("region_name")) == region_key
                ],
                "recorded": [
                    item for item in audit_record["recorded"]
                    if _page_key(item.get("region_name")) == region_key
                ],
                "dropped": [
                    item for item in audit_record["dropped"]
                    if _page_key(item.get("region_name")) == region_key
                ],
                "deferred": [
                    item for item in audit_record["deferred"]
                    if _page_key(item.get("region_name")) == region_key
                ],
                "deferred_regions": [
                    name for name in audit_record["deferred_regions"]
                    if _page_key(name) == region_key
                ],
            }
        if not mixed_disagreement:
            host.pending_entry_review = None
            host.entry_review_screenshot = b""
        disagreement_reason = (
            "The Entry Reviewer omitted "
            f"{len(dropped)} candidate"
            f"{'s' if len(dropped) != 1 else ''} submitted by the main Agent"
            if dropped else
            "The Entry Reviewer said its decision did not agree with the main "
            "Agent's explanation"
        )
        if final_disagreement:
            detail = (
                disagreement_reason
                + ". After three reviews under the same GUI evidence, the "
                "candidate proposal remains unresolved. No Entry or coverage "
                "fact was written; new GUI evidence is required."
            )
            correction = (
                "Do not resubmit the same evidence. First perform a GUI action "
                "that can reveal new evidence, then explain the visible change."
            )
        else:
            detail = (
                disagreement_reason
                + ". No Entry or coverage fact was written. Read the complete "
                "Reviewer reason, then revise the candidate list or explain why "
                "the visible control should remain before submitting the full "
                "page update again."
            )
            correction = (
                "Respond to the Reviewer's complete natural-language reason "
                "and resubmit the full page update."
            )
        if not mixed_disagreement:
            history.append({
                "kind": "entry_review_result",
                "screen": scene.page_name,
                **deepcopy(audit_record),
                "detail": detail,
                "rejection": _rejection_feedback(
                    "entry_review_discussion_unresolved",
                    detail,
                    correction=correction,
                ),
            })
            return ""
    frame_id = screenshot_frame_id(screenshot)
    deferred_frames = host.entry_review_deferred_frames.setdefault(
        _page_key(pending_page), {})
    for region_key in deferred_region_keys:
        deferred_frames[region_key] = frame_id
    same_frame_deferred_keys = {
        region_key for region_key, deferred_frame_id
        in deferred_frames.items()
        if deferred_frame_id == frame_id
    }
    entry_apply_result: Dict[str, Any] = {"rejected_items": []}
    if review_consistent and (
            selected or missed or recorded or recorded_missed):
        issue = _apply_main_agent_page_update(
            host,
            PageUpdate(
                page_name=pending_page,
                regions=[],
                new_entries=[
                    *selected, *missed, *recorded, *recorded_missed,
                ],
            ),
            scene,
            screenshot,
            history,
            result_out=entry_apply_result,
        )
        if issue:
            return issue
    rejected_entry_region_keys = {
        _page_key(region_key)
        for region_key in (
            pending.get("pre_rejected_entry_region_keys") or [])
        if _page_key(region_key)
    }
    rejected_entry_region_keys.update({
        _page_key(item.get("region_name"))
        for item in entry_apply_result.get("rejected_items") or []
        if (
            isinstance(item, dict)
            and item.get("kind") == "new_entry"
            and _page_key(item.get("region_name"))
        )
    })
    if (
        pending.get("pre_rejected_entry_all_audits") is True
        or any(
            isinstance(item, dict)
            and item.get("kind") == "new_entry"
            and not _page_key(item.get("region_name"))
            for item in entry_apply_result.get("rejected_items") or []
        )
    ):
        rejected_entry_region_keys.update(audit_region_keys)
    for region_name in coverage_audit_regions:
        region_key = _page_key(region_name)
        if (
            region_key not in same_frame_deferred_keys
            and region_key not in rejected_entry_region_keys
            and region_key not in disputed_region_keys
        ):
            host.region_registry.mark_state_visible(
                page_name=pending_page,
                region_name=region_name,
                state_id=scene.state_id,
            )
    resolved_correction_keys = ([
        _page_update_item_key({
            "kind": "new_entry",
            "region_name": item.get("region_name"),
            "target": item.get("target"),
        })
        for item in dropped
    ] if review_consistent and not disagreement else [])
    resolved_correction_keys.extend([
        _page_update_item_key({
            "kind": "new_entry",
            "region_name": item.get("region_name"),
            "target": item.get("target"),
        })
        for item in pending.get("resolved_previous_drops") or []
        if isinstance(item, dict)
    ])
    requested_raw = pending.get("coverage_requested")
    coverage_requested = {
        _page_key(key): value is True
        for key, value in (
            requested_raw.items() if isinstance(requested_raw, dict) else []
        )
    }
    for region_name in coverage_audit_regions:
        region_key = _page_key(region_name)
        complete = (
            coverage_requested.get(region_key) is True
            and review_consistent
            and region_key not in same_frame_deferred_keys
            and region_key not in rejected_entry_region_keys
            and region_key not in disputed_region_keys
        )
        state.set_coverage_complete(region_name, complete)

    final_snapshot = state.snapshot()
    reviewed_region_by_key = {
        _page_key(item.get("name")): item
        for item in final_snapshot.get("regions") or []
        if isinstance(item, dict) and item.get("name")
    }
    final_reviewed_regions = [
        reviewed_region_by_key[_page_key(region_name)]
        for region_name in coverage_audit_regions
        if _page_key(region_name) in reviewed_region_by_key
    ]
    if final_reviewed_regions:
        host.protocol_map.upsert_regions(
            pending_page, final_reviewed_regions)

    page_audits = host.entry_review_audits.setdefault(
        _page_key(pending_page), {})
    coverage_basis = "visual_entry_reviewer"
    completed_audit_region_keys: set[str] = set()
    coverage_versions: Dict[str, int] = {}
    for region_name in coverage_audit_regions:
        region_key = _page_key(region_name)
        if region_key in disputed_region_keys:
            continue
        reviewed_region = reviewed_region_by_key.get(region_key) or {}
        if reviewed_region.get("coverage_complete") is not True:
            continue
        region_ref = host.region_registry.region_ref(
            pending_page, region_name)
        signature = _coverage_entry_signature([
            entry for entry in host.entry_ledger.entries
            if entry.discovery_source != "direct_action_backfill"
            and _page_key(entry.page_name) == _page_key(pending_page)
            and _page_key(entry.region_name) == region_key
        ])
        version = host.region_registry.publish_coverage(
            region_ref=region_ref,
            page_name=pending_page,
            region_name=region_name,
            state_id=scene.state_id,
            frame_id=frame_id,
            entry_signature=signature,
        )
        state.set_coverage_evidence(
            region_name, version=version, basis=coverage_basis)
        coverage_versions[region_key] = version
    for region_name in coverage_audit_regions:
        region_key = _page_key(region_name)
        if region_key in disputed_region_keys:
            continue
        reviewed_region = reviewed_region_by_key.get(region_key) or {}
        audit_status = (
            "inconsistent" if not review_consistent
            else "deferred" if region_key in same_frame_deferred_keys
            else "complete"
            if reviewed_region.get("coverage_complete") is True
            else "partial"
        )
        if audit_status == "complete":
            completed_audit_region_keys.add(region_key)
        page_audits[region_key] = {
            "page_name": pending_page,
            "region_name": str(
                reviewed_region.get("name") or region_name).strip()[:160],
            "frame_id": frame_id,
            "status": audit_status,
            "coverage_basis": coverage_basis,
            **({"coverage_version": coverage_versions[region_key]}
               if region_key in coverage_versions else {}),
            "reason_consistent": reason_consistent,
            "reviewer_reason": str(reviewer_reason or "").strip()[:800],
            "coverage_audit_regions": [region_name],
            "discussion_evidence_generation": int(
                pending.get("discussion_evidence_generation", 0)),
            "review_attempt": review_attempt,
            "review_attempt_limit": review_attempt_limit,
            "main_agent_reason": str(
                pending.get("main_agent_reason") or "").strip(),
            "kept": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in selected
                if _page_key(item.get("region_name")) == region_key],
            "added": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in missed
                if _page_key(item.get("region_name")) == region_key],
            "recorded": [{
                "region_name": item.get("region_name"),
                "operation": item.get("operation") or item.get("target"),
                "subject": item.get("subject") or item.get("region_name"),
                "target": item.get("target"),
            } for item in [*recorded, *recorded_missed]
                if _page_key(item.get("region_name")) == region_key],
            "dropped": [],
            "deferred": [
                deepcopy(item) for item in deferred
                if _page_key(item.get("region_name")) == region_key
            ],
            "deferred_regions": [
                name for name in deferred_region_names
                if _page_key(name) == region_key
            ],
        }
        if (
            region_key not in deferred_region_keys
            and deferred_frames.get(region_key) != frame_id
        ):
            deferred_frames.pop(region_key, None)
    if coverage_versions:
        refreshed = state.snapshot()
        host.protocol_map.upsert_regions(
            pending_page, refreshed.get("regions") or [])
    if completed_audit_region_keys:
        pending_corrections = host.page_update_corrections.get(
            _page_key(pending_page), {}) or {}
        resolved_correction_keys.extend([
            correction_key
            for correction_key, correction in pending_corrections.items()
            if (
                correction.get("kind") == "new_entry"
                and correction.get("error_code")
                == "unknown_region_reference"
                and correction.get("field") == "region_name"
                and _page_key(correction.get("region_name"))
                in completed_audit_region_keys
            )
        ])
    _update_page_corrections(
        host,
        pending_page,
        accepted_keys=(),
        rejected_items=(),
        resolved_keys=[
            key for key in resolved_correction_keys if key
        ],
    )
    if not deferred_frames:
        host.entry_review_deferred_frames.pop(
            _page_key(pending_page), None)
    completed_resurvey = None
    if (
        review_consistent
        and _page_key(pending_page) in host.pending_page_resurveys
        and _focused_coverage_is_complete(
            final_snapshot, coverage_audit_regions,
        )
    ):
        completed_resurvey = host.pending_page_resurveys.pop(
            _page_key(pending_page), None)
    host.pending_entry_review = None
    host.entry_review_screenshot = b""
    review_detail = (
        f"Entry Reviewer kept {len(selected)} independent function entr"
        f"{'y' if len(selected) == 1 else 'ies'}, recorded "
        f"{len(recorded) + len(recorded_missed)} command-relevant "
        "operations without scheduling traversal, and dropped "
        f"{len(dropped)} internal or non-expanding controls, deferred "
        f"{len(deferred)} visually unresolved candidates and "
        f"{len(deferred_region_names)} visually unresolved Regions, and "
        f"added {len(missed)} visible entries omitted by the survey."
    )
    if not review_consistent:
        review_detail += (
            " The Reviewer disagreed with the main Agent's reason, so no "
            "candidate changes or coverage completion were committed."
        )
    if str(reviewer_reason or "").strip():
        review_detail += f" Reviewer reason: {str(reviewer_reason).strip()}"
    history.append({
        "kind": "entry_review_result",
        "screen": scene.page_name,
        "frame_id": frame_id,
        "status": (
            "partial_disagreement" if mixed_disagreement
            else "accepted" if review_consistent else "inconsistent"
        ),
        "kept": [{
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "subject": item.get("subject") or item.get("region_name"),
            "target": item.get("target"),
        } for item in selected],
        "added": [{
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "subject": item.get("subject") or item.get("region_name"),
            "target": item.get("target"),
        } for item in missed],
        "recorded": [{
            "region_name": item.get("region_name"),
            "operation": item.get("operation") or item.get("target"),
            "subject": item.get("subject") or item.get("region_name"),
            "target": item.get("target"),
        } for item in [*recorded, *recorded_missed]],
        "dropped": dropped,
        "deferred": deferred,
        "deferred_regions": deferred_region_names,
        "coverage_audit_regions": coverage_audit_regions,
        "coverage_basis": coverage_basis,
        "ledger_committed": review_consistent,
        **({"completed_resurvey": completed_resurvey}
           if completed_resurvey else {}),
        "detail": review_detail,
        "reason_consistent": reason_consistent,
        "reviewer_reason": str(reviewer_reason or "").strip(),
    })
    return ""
