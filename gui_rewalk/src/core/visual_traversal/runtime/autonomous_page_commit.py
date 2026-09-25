"""Formal Page/Region/Entry commit for Qwen autonomous page updates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from .autonomous_context import _region_state
from .autonomous_page_update import (
    _normalize_new_entry_item,
    _normalize_page_region_item,
    _page_update_item_rejection,
    _update_page_corrections,
)
from .autonomous_region_tools import (
    AutonomousRegionRegistry,
    RegionProtocolError,
    screenshot_frame_id,
)
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _apply_target_edge_scope,
    _record_agent_inferred_edges,
)
from .autonomous_turn import ObservedScene, PageUpdate, _page_key


def _validate_cross_page_region_review(
    result: Any,
    occurrence_ids: List[str],
) -> tuple[Dict[str, str], List[str]]:
    """Validate complete occurrence coverage and return exact shared pairs."""
    if not isinstance(result, dict):
        return {}, ["跨页面 Region Reviewer 必须返回对象"]
    allowed_fields = {
        "shared_groups", "separate_groups", "unmatched", "reason",
    }
    errors: List[str] = []
    if set(result) != allowed_fields:
        errors.append("跨页面 Region Reviewer 返回字段不完整或含额外字段")
    if not str(result.get("reason") or "").strip():
        errors.append("跨页面 Region Reviewer 缺少整体 reason")
    expected = set(occurrence_ids)
    counts: Dict[str, int] = {}
    shared_pairs: Dict[str, str] = {}
    for field_name in ("shared_groups", "separate_groups"):
        groups = result.get(field_name)
        if not isinstance(groups, list):
            errors.append(f"{field_name} 必须是数组")
            continue
        for index, group in enumerate(groups):
            if not isinstance(group, dict) or set(group) != {"members", "reason"}:
                errors.append(f"{field_name}[{index}] 结构无效")
                continue
            members = group.get("members")
            if (not isinstance(members, list) or len(members) < 2
                    or not str(group.get("reason") or "").strip()):
                errors.append(f"{field_name}[{index}] 缺少成员或具体 reason")
                continue
            normalized_members = [str(item or "").strip() for item in members]
            if any(not item for item in normalized_members):
                errors.append(f"{field_name}[{index}] 含空 occurrence_id")
                continue
            for occurrence_id in normalized_members:
                counts[occurrence_id] = counts.get(occurrence_id, 0) + 1
            if field_name == "shared_groups":
                current = [item for item in normalized_members
                           if item.startswith("N")]
                known = [item for item in normalized_members
                         if item.startswith("K")]
                if len(normalized_members) != 2 or len(current) != 1 \
                        or len(known) != 1:
                    errors.append(
                        f"shared_groups[{index}] 必须是一个当前 Region 与一个已知 Region")
                else:
                    shared_pairs[current[0]] = known[0]
    unmatched = result.get("unmatched")
    if not isinstance(unmatched, list):
        errors.append("unmatched 必须是数组")
    else:
        for index, item in enumerate(unmatched):
            if (not isinstance(item, dict)
                    or set(item) != {"occurrence_id", "reason"}):
                errors.append(f"unmatched[{index}] 结构无效")
                continue
            occurrence_id = str(item.get("occurrence_id") or "").strip()
            if not occurrence_id or not str(item.get("reason") or "").strip():
                errors.append(f"unmatched[{index}] 缺少 occurrence_id 或 reason")
                continue
            counts[occurrence_id] = counts.get(occurrence_id, 0) + 1
    unknown = sorted(set(counts) - expected)
    missing = sorted(expected - set(counts))
    duplicate = sorted(
        occurrence_id for occurrence_id, count in counts.items() if count > 1)
    if unknown:
        errors.append("引用未知 occurrence_id：" + "、".join(unknown))
    if missing:
        errors.append("遗漏 occurrence_id：" + "、".join(missing))
    if duplicate:
        errors.append("重复 occurrence_id：" + "、".join(duplicate))
    return ({} if errors else shared_pairs), errors


def _apply_cross_page_region_review(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    scene: ObservedScene,
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    region_reviewed: bool,
) -> PageUpdate:
    """Batch-review new local Regions against prior Page representatives."""
    if not region_reviewed or not callable(host.cross_page_region_reviewer):
        return update
    state = host.region_states.get(_page_key(scene.page_name))
    existing_keys = {
        _page_key(item.get("name"))
        for item in (state.snapshot().get("regions") if state else []) or []
        if isinstance(item, dict) and item.get("name")
    }
    current_items = [
        (index, item) for index, item in enumerate(update.regions)
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and _page_key(item.get("name")) not in existing_keys
        and not str(item.get("equivalent_to_region_ref") or "").strip()
    ]
    if not current_items:
        return update

    occurrences: List[Dict[str, Any]] = []
    current_by_id: Dict[str, int] = {}
    for occurrence_index, (region_index, item) in enumerate(current_items, 1):
        occurrence_id = f"N{occurrence_index}"
        current_by_id[occurrence_id] = region_index
        occurrences.append({
            "occurrence_id": occurrence_id,
            "page": scene.page_name,
            "region": str(item.get("name") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "image": "图1",
        })

    candidate_screenshots: List[bytes] = []
    candidate_image_by_page: Dict[str, str] = {}
    candidate_pages: List[tuple[str, str]] = []
    known_by_id: Dict[str, Dict[str, str]] = {}
    for group in host.region_registry.candidates():
        representative = group.get("representative") or {}
        page_name = str(representative.get("page_name") or "").strip()
        region_name = str(representative.get("region_name") or "").strip()
        region_ref = str(group.get("region_ref") or "").strip()
        representative_ref = str(
            group.get("representative_occurrence_ref") or "").strip()
        representative_occurrence = next((
            item for item in group.get("occurrences") or []
            if str(item.get("occurrence_ref") or "") == representative_ref
        ), {})
        variant_name = str(
            representative_occurrence.get("representative_variant_name")
            or "").strip()
        if (not page_name or not region_name or not region_ref
                or not variant_name
                or _page_key(page_name) == _page_key(scene.page_name)):
            continue
        page_key = _page_key(page_name)
        image_label = candidate_image_by_page.get(page_key, "")
        if not image_label:
            evidence = host.protocol_map.representative_screenshot(
                page_name, variant_name)
            if not evidence:
                continue
            candidate_screenshots.append(evidence)
            image_label = f"图{len(candidate_screenshots) + 1}"
            candidate_image_by_page[page_key] = image_label
            candidate_pages.append((page_name, image_label))
        occurrence_id = f"K{len(known_by_id) + 1}"
        known_by_id[occurrence_id] = {
            "region_ref": region_ref,
            "page": page_name,
            "region": region_name,
        }
        occurrences.append({
            "occurrence_id": occurrence_id,
            "page": page_name,
            "region": region_name,
            "summary": str(group.get("summary") or "").strip(),
            "image": image_label,
        })
    if not known_by_id:
        return update

    request = {
        "current_screenshot": screenshot,
        "candidate_screenshots": candidate_screenshots,
        "occurrences": occurrences,
        "image_order": [
            "图1：当前页面完整截图",
            *[f"{label}：已通过页面内复核的 {page} 完整截图"
              for page, label in candidate_pages],
        ],
    }
    try:
        result = host.cross_page_region_reviewer(request)
        shared_pairs, errors = _validate_cross_page_region_review(
            result, [item["occurrence_id"] for item in occurrences])
    except Exception:
        result = {}
        shared_pairs, errors = {}, ["跨页面 Region Reviewer 未返回可用结果"]
    if errors:
        history.append({
            "kind": "cross_page_region_review_result",
            "screen": scene.page_name,
            "status": "invalid",
            "detail": "；".join(errors[:8]),
        })
        return update

    revised = deepcopy(update.regions)
    applied: List[Dict[str, str]] = []
    for current_id, known_id in shared_pairs.items():
        candidate = known_by_id[known_id]
        region_index = current_by_id[current_id]
        region = revised[region_index]
        assert isinstance(region, dict)
        group = next(
            item for item in result["shared_groups"]
            if current_id in item["members"] and known_id in item["members"])
        region["equivalent_to_region_ref"] = candidate["region_ref"]
        region["equivalence_reason"] = str(group.get("reason") or "")[:500]
        applied.append({
            "current_region": str(region.get("name") or ""),
            "shared_with_page": candidate["page"],
            "shared_with_region": candidate["region"],
            "region_ref": candidate["region_ref"],
        })
    history.append({
        "kind": "cross_page_region_review_result",
        "screen": scene.page_name,
        "status": "accepted",
        "applied": applied,
        "detail": str(result.get("reason") or "")[:800],
    })
    return PageUpdate(
        page_name=update.page_name,
        regions=revised,
        new_entries=deepcopy(update.new_entries),
        omitted_regions=deepcopy(update.omitted_regions),
        entry_resolutions=deepcopy(update.entry_resolutions),
    )


def _apply_batch_region_mapping(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
    scene: ObservedScene,
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    mapping_out: Optional[Dict[str, Dict[str, str]]] = None,
) -> PageUpdate:
    """Apply only exact one-to-one identities from one validated batch map."""
    context = host.pending_region_mapping_context
    if not isinstance(context, dict) or not callable(host.region_mapper):
        return update
    if (
        context.get("after_screenshot") != screenshot
        or _page_key(context.get("after_page")) != _page_key(scene.page_name)
    ):
        host.pending_region_mapping_context = None
        return update
    before_regions = [
        item for item in context.get("before_regions") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    after_region_items = [
        (index, item)
        for index, item in enumerate(update.regions)
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    after_regions = [item for _index, item in after_region_items]
    if not before_regions or not after_regions:
        host.pending_region_mapping_context = None
        return update
    request = {
        **context,
        "after_regions": deepcopy(after_regions),
    }
    try:
        mapping = host.region_mapper(request)
    except Exception as exc:
        history.append({
            "kind": "region_mapping_result",
            "screen": scene.page_name,
            "outcome": "uncertain",
            "detail": (
                "Batch Region mapping returned no valid complete assignment; "
                "the reviewed after Regions remain new identities."
            ),
        })
        host.pending_region_mapping_context = None
        return update
    mapped_regions = deepcopy(update.regions)
    applied: List[Dict[str, str]] = []
    for match in mapping.get("matches") or []:
        before_ids = list(match.get("before") or [])
        after_ids = list(match.get("after") or [])
        if len(before_ids) != 1 or len(after_ids) != 1:
            continue
        try:
            before_index = int(before_ids[0][1:]) - 1
            after_index = int(after_ids[0][1:]) - 1
            before_region = before_regions[before_index]
            mapped_index = after_region_items[after_index][0]
            after_region = mapped_regions[mapped_index]
        except (ValueError, IndexError, TypeError):
            continue
        if not isinstance(after_region, dict):
            continue
        region_ref = str(before_region.get("region_ref") or "").strip()
        if not region_ref:
            region_ref = host.region_registry.region_ref(
                str(context.get("before_page") or ""),
                str(before_region.get("name") or ""),
            )
        if not region_ref:
            continue
        after_region["equivalent_to_region_ref"] = region_ref
        after_region["equivalence_reason"] = str(
            match.get("reason") or "").strip()[:800]
        applied.append({
            "before": before_ids[0],
            "after": after_ids[0],
            "region_ref": region_ref,
        })
        if mapping_out is not None:
            mapping_out[_page_key(after_region.get("name"))] = {
                "region_ref": region_ref,
                "source_page": str(context.get("before_page") or ""),
                "source_region": str(before_region.get("name") or ""),
                "reason": str(match.get("reason") or "").strip()[:800],
            }
    history.append({
        "kind": "region_mapping_result",
        "screen": scene.page_name,
        "outcome": "mapped",
        "matches": deepcopy(mapping.get("matches") or []),
        "new": list(mapping.get("new") or []),
        "uncertain": deepcopy(mapping.get("uncertain") or []),
        "applied_one_to_one": applied,
        "detail": (
            "The batch mapper classified every after Region exactly once. "
            "Only exact one-to-one continuity was applied to the current "
            "one-Region-one-ref ledger; grouped matches remain audit evidence."
        ),
    })
    host.pending_region_mapping_context = None
    return PageUpdate(
        page_name=update.page_name,
        regions=mapped_regions,
        new_entries=deepcopy(update.new_entries),
        entry_resolutions=deepcopy(update.entry_resolutions),
    )


def _apply_main_agent_page_update(
    host: AutonomousTraversalRuntime,
    update: Optional[PageUpdate],
    scene: Optional[ObservedScene],
    screenshot: bytes,
    history: List[Dict[str, Any]],
    *,
    allow_same_frame_completion: bool = False,
    region_reviewed: bool = False,
    result_out: Optional[Dict[str, Any]] = None,
) -> str:
    if update is None:
        return ""
    rejected_items: List[Dict[str, Any]] = []
    accepted_regions: List[str] = []
    created_entries: List[Dict[str, str]] = []
    matched_entries: List[Dict[str, str]] = []
    reopened_entries: List[str] = []
    region_equivalence_feedback: List[str] = []
    accepted_correction_keys: set[str] = set()

    def reject_page(error_code: str, reason: str) -> str:
        rejected = {
            "kind": "page_update",
            "index": -1,
            "error_code": error_code,
            "field": "page_name",
            "reason": reason[:300],
        }
        _update_page_corrections(
            host,
            scene.page_name if scene is not None else update.page_name,
            accepted_keys=(),
            rejected_items=[rejected],
        )
        result = {
            "kind": "page_update_result",
            "screen": scene.page_name if scene is not None else update.page_name,
            "status": "rejected",
            "accepted_regions": [],
            "created_entries": [],
            "rejected_items": [rejected],
        }
        history.append(result)
        if result_out is not None:
            result_out.update(deepcopy(result))
        return reason

    if scene is None:
        return reject_page(
            "unregistered_current_page",
            "page_update requires a registered current page",
        )
    canonical_page = host.protocol_map.canonical_page_name(update.page_name)
    if not canonical_page:
        return reject_page(
            "invalid_page_owner",
            f"page_update references an unregistered page: {update.page_name}",
        )
    if _page_key(canonical_page) != _page_key(scene.page_name):
        return reject_page("invalid_page_owner", (
            f"page_update belongs to {canonical_page!r}, but the latest screenshot "
            f"is registered as {scene.page_name!r}"
        ))

    mapped_region_sources: Dict[str, Dict[str, str]] = {}
    update = _apply_batch_region_mapping(
        host, update, scene, screenshot, history,
        mapping_out=mapped_region_sources)
    update = _apply_cross_page_region_review(
        host, update, scene, screenshot, history,
        region_reviewed=region_reviewed)

    state = _region_state(host, canonical_page)
    frame_id = screenshot_frame_id(screenshot)
    if update.regions:
        state.observe_frame(frame_id, scene.state_id)
    elif state.current_frame_id:
        frame_id = state.current_frame_id
    existing_regions = {
        _page_key(region.get("name")): str(region.get("name") or "")
        for region in state.snapshot().get("regions") or []
    }
    existing_region_records = {
        _page_key(region.get("name")): region
        for region in state.snapshot().get("regions") or []
    }
    proposed_region_names = {
        _page_key(region.get("name")): str(region.get("name") or "").strip()
        for region in update.regions
        if isinstance(region, dict) and str(region.get("name") or "").strip()
    }
    proposed_ref_requests: Dict[str, set[str]] = {}
    for region in update.regions:
        if not isinstance(region, dict):
            continue
        region_key = _page_key(region.get("name"))
        requested_ref = str(
            region.get("equivalent_to_region_ref") or "").strip()
        if region_key and requested_ref:
            proposed_ref_requests.setdefault(requested_ref, set()).add(
                region_key)
    accepted_region_keys: Dict[str, str] = {}
    rejected_region_keys = set()
    completion_candidates: List[Dict[str, Any]] = []
    raw_entry_region_keys = {
        _page_key(raw.get("region_name"))
        for raw in update.new_entries
        if isinstance(raw, dict) and isinstance(raw.get("region_name"), str)
    }
    preexisting_region_refs = set(host.region_registry.refs)
    preexisting_entry_ids = {
        entry.entry_id for entry in host.entry_ledger.entries
    }
    preexisting_region_names = {
        str(group.get("region_ref") or "").strip(): str(
            (group.get("representative") or {}).get("region_name") or ""
        ).strip()
        for group in host.region_registry.candidates()
        if isinstance(group, dict)
        and isinstance(group.get("representative"), dict)
    }

    for index, raw in enumerate(update.regions):
        normalized, rejection = _normalize_page_region_item(raw, index)
        if rejection is not None:
            rejected_items.append(rejection)
            region_name = rejection.get("region_name")
            if region_name:
                rejected_region_keys.add(_page_key(region_name))
            continue
        assert normalized is not None
        requested_complete = bool(normalized["coverage_complete"])
        region_key = _page_key(normalized["name"])
        same_group_as = str(
            normalized.get("same_group_as") or "").strip()
        same_group_key = _page_key(same_group_as)
        existing_region = existing_region_records.get(region_key) or {}
        last_observation_frame = str(
            existing_region.get("last_incomplete_frame_id") or "")
        if (
            requested_complete
            and existing_region
            and not bool(existing_region.get("coverage_complete"))
            and last_observation_frame == frame_id
            and not allow_same_frame_completion
        ):
            rejected_items.append(_page_update_item_rejection(
                "region", index, raw,
                error_code="coverage_same_frame_without_new_evidence",
                field_name="coverage_complete",
                reason=(
                    "This Region was already left incomplete on the same "
                    "byte-identical frame. No distinct visual frame has been "
                    "observed since then, so coverage_complete=true was not "
                    "accepted. Obtain a new visual observation and reassess."
                ),
            ))
            rejected_region_keys.add(region_key)
            continue
        requested_region_ref = str(
            normalized.get("equivalent_to_region_ref") or "").strip()
        homogeneous_grouping = bool(same_group_as)
        split_from_group = bool(normalized.get("split_from_group"))
        if split_from_group:
            existing_region_ref = str(
                existing_region.get("region_ref") or "").strip()
            existing_group = next((
                group for group in host.region_registry.candidates()
                if str(group.get("region_ref") or "") == existing_region_ref
            ), None)
            if (
                not existing_region_ref
                or existing_group is None
                or len(existing_group.get("occurrences") or []) <= 1
            ):
                rejected_items.append(_page_update_item_rejection(
                    "region", index, raw,
                    error_code="invalid_group_split",
                    field_name="split_from_group",
                    reason=(
                        "split_from_group requires an existing Region with "
                        "multiple explicitly grouped occurrences"),
                ))
                rejected_region_keys.add(region_key)
                continue
            if not region_reviewed:
                rejected_items.append(_page_update_item_rejection(
                    "region", index, raw,
                    error_code="region_review_required",
                    field_name="split_from_group",
                    reason=(
                        "An observed homogeneous-group conflict requires the "
                        "focused Region review before inferred work is reopened"),
                ))
                rejected_region_keys.add(region_key)
                continue
            requested_region_ref = ""
            normalized["equivalence_reason"] = (
                str(normalized.get("equivalence_reason") or "").strip()
                or "Latest reviewed observation conflicts with the prior grouping."
            )
        if homogeneous_grouping:
            if same_group_key == region_key:
                rejected_items.append(_page_update_item_rejection(
                    "region", index, raw,
                    error_code="invalid_same_group_reference",
                    field_name="same_group_as",
                    reason="same_group_as cannot reference the Region itself",
                ))
                rejected_region_keys.add(region_key)
                continue
            same_group_name = (
                accepted_region_keys.get(same_group_key)
                or existing_regions.get(same_group_key)
                or ""
            )
            requested_region_ref = host.region_registry.region_ref(
                canonical_page, same_group_name)
            if not same_group_name or not requested_region_ref:
                rejected_items.append(_page_update_item_rejection(
                    "region", index, raw,
                    error_code="invalid_same_group_reference",
                    field_name="same_group_as",
                    reason=(
                        "same_group_as must name an existing or earlier accepted "
                        "Region on this Page"),
                ))
                rejected_region_keys.add(region_key)
                continue
            if not region_reviewed:
                rejected_items.append(_page_update_item_rejection(
                    "region", index, raw,
                    error_code="region_review_required",
                    field_name="same_group_as",
                    reason=(
                        "A first same-Page homogeneous grouping requires the "
                        "focused Region review"),
                ))
                rejected_region_keys.add(region_key)
                continue
            normalized["equivalence_reason"] = (
                "Accepted as a repeated independently stateful instance of "
                f"{same_group_name!r}."
            )
        if (requested_region_ref
                and requested_region_ref not in preexisting_region_refs
                and not homogeneous_grouping):
            rejected_items.append(_page_update_item_rejection(
                "region", index, raw,
                error_code="invalid_region_ref",
                field_name="equivalent_to_region_ref",
                reason=(
                    "equivalent_to_region_ref must cite a Region candidate "
                    "that existed before this page_update"
                ),
            ))
            rejected_region_keys.add(region_key)
            continue
        canonical_region_name = preexisting_region_names.get(
            requested_region_ref, "")
        existing_region_ref = str(
            existing_region.get("region_ref") or "").strip()
        all_pending_region_reviews = {
            key: item
            for key, item in (
                host.page_update_corrections.get(
                    _page_key(canonical_page), {}) or {}
            ).items()
            if item.get("error_code") == "region_equivalence_review_required"
        }
        pending_reviews_for_ref = {
            key: item for key, item in all_pending_region_reviews.items()
            if requested_region_ref
            and str(item.get("region_ref") or "").strip()
            == requested_region_ref
        }
        pending_reviews_for_name = {
            key: item for key, item in all_pending_region_reviews.items()
            if _page_key(item.get("region_name")) == region_key
        }
        is_new_region_binding = (
            bool(requested_region_ref)
            and existing_region_ref != requested_region_ref
        )
        if (
            is_new_region_binding
            and not region_reviewed
            and not pending_reviews_for_ref
            and not homogeneous_grouping
        ):
            rejected = _page_update_item_rejection(
                "region", index, raw,
                error_code="region_equivalence_review_required",
                field_name="equivalent_to_region_ref",
                reason=(
                    f"The proposed binding to {requested_region_ref} "
                    f"({canonical_region_name!r}) is a new shared Region "
                    "relationship and has not been committed. Reassess the "
                    "current visible components against that candidate in the "
                    "focused Region-equivalence review; screen position or "
                    "container role is not equivalence evidence."
                ),
            )
            rejected["region_ref"] = requested_region_ref
            if canonical_region_name:
                rejected["canonical_name"] = canonical_region_name
            rejected_items.append(rejected)
            rejected_region_keys.add(region_key)
            continue
        if (
            requested_region_ref
            and canonical_region_name
            and region_key != _page_key(canonical_region_name)
            and not region_reviewed
            and not homogeneous_grouping
        ):
            rejected = _page_update_item_rejection(
                "region", index, raw,
                error_code=(
                    "region_equivalence_review_required"
                    if pending_reviews_for_ref
                    else "region_canonical_name_conflict"
                ),
                field_name="name",
                reason=(
                    f"Region {normalized['name']!r} cites "
                    f"{requested_region_ref}, whose canonical name is "
                    f"{canonical_region_name!r}. This is an unresolved "
                    "Region-identity decision, not a request to rename merely "
                    "to satisfy the schema. Reuse the canonical name only when "
                    "the focused component comparison says they are the same; "
                    "otherwise keep the distinct name and leave "
                    "equivalent_to_region_ref empty."
                ),
            )
            if pending_reviews_for_ref:
                rejected["region_ref"] = requested_region_ref
                rejected["canonical_name"] = canonical_region_name
            rejected_items.append(rejected)
            rejected_region_keys.add(region_key)
            continue
        conflicting_region_names = {
            proposed_region_names.get(other_key, other_key)
            for other_key, record in existing_region_records.items()
            if other_key != region_key
            and other_key in proposed_region_names
            and str(record.get("region_ref") or "").strip()
            == requested_region_ref
        }
        conflicting_region_names.update(
            proposed_region_names.get(other_key, other_key)
            for other_key in proposed_ref_requests.get(
                requested_region_ref, set())
            if other_key != region_key
        )
        if (
            requested_region_ref
            and conflicting_region_names
            and not homogeneous_grouping
        ):
            conflicting_names = ", ".join(sorted(conflicting_region_names))
            region_equivalence_feedback.append((
                f"Region {normalized['name']!r} stayed independent because "
                f"{requested_region_ref} is also assigned to a different "
                f"Region in this same Page proposal ({conflicting_names}). "
                "Two co-present formal Regions cannot share one Region "
                "occurrence identity."
            )[:800])
            mapped_region_sources.pop(region_key, None)
            requested_region_ref = ""
            normalized["equivalence_reason"] = (
                "Kept as an independent Region because the proposed shared "
                "identity already belongs to another Region in this Page "
                "proposal."
            )
        applied = dict(normalized)
        applied.pop("equivalent_to_region_ref", None)
        applied.pop("same_group_as", None)
        applied.pop("split_from_group", None)
        applied["region_ref"] = (
            requested_region_ref
            or str(existing_region.get("region_ref") or "")
        )
        preserved_identity_fields: List[str] = []
        if existing_region and not region_reviewed:
            for field_name in ("summary", "equivalence_reason"):
                current_value = str(
                    existing_region.get(field_name) or "").strip()
                proposed_value = str(
                    applied.get(field_name) or "").strip()
                if (
                    current_value
                    and proposed_value
                    and proposed_value != current_value
                ):
                    applied[field_name] = current_value
                    preserved_identity_fields.append(field_name)
        if preserved_identity_fields:
            region_equivalence_feedback.append((
                f"Region {normalized['name']!r} kept its reviewed stable "
                "identity fields ("
                + ", ".join(preserved_identity_fields)
                + "); ordinary coverage, bbox and survey-memory updates "
                "cannot rewrite Region identity."
            )[:800])
        if requested_complete and region_key in raw_entry_region_keys:
            applied["coverage_complete"] = False
        region_states_before = deepcopy(host.region_states)
        registry_before = host.region_registry.snapshot()
        entry_ledger_before = deepcopy(host.entry_ledger)
        try:
            updated_name = state.apply_agent_update(
                [applied], frame_id=frame_id)[0]
        except (RegionProtocolError, ValueError) as exc:
            host.region_states = region_states_before
            state = host.region_states[_page_key(canonical_page)]
            rejected_items.append(_page_update_item_rejection(
                "region", index, raw, error_code="region_update_rejected",
                field_name="", reason=str(exc)))
            rejected_region_keys.add(region_key)
            continue
        try:
            if split_from_group:
                _old_ref, region_ref, occurrence_ref = (
                    host.region_registry.split_occurrence(
                        page_name=canonical_page,
                        region_name=updated_name,
                        reason=str(applied.get("equivalence_reason") or ""),
                    )
                )
                reopened_entries.extend(
                    host.entry_ledger.reopen_occurrence_after_group_conflict(
                        occurrence_ref=occurrence_ref,
                        new_region_ref=region_ref,
                        reason=str(applied.get("equivalence_reason") or ""),
                    )
                )
                merged_old_ref = ""
            else:
                region_ref, merged_old_ref = host.region_registry.bind(
                    page_name=canonical_page,
                    region_name=updated_name,
                    state_id=scene.state_id,
                    variant_name=host.protocol_map.current_variant,
                    summary=str(applied.get("summary") or ""),
                    equivalent_to_region_ref=requested_region_ref,
                    reason=str(applied.get("equivalence_reason") or ""),
                )
            state.set_region_ref(
                updated_name,
                region_ref,
                reason=str(applied.get("equivalence_reason") or ""),
            )
            if merged_old_ref:
                for region_state in host.region_states.values():
                    region_state.remap_region_ref(
                        merged_old_ref, region_ref)
        except (RegionProtocolError, ValueError) as exc:
            host.region_states = region_states_before
            state = host.region_states[_page_key(canonical_page)]
            host.region_registry = AutonomousRegionRegistry.from_snapshot(
                registry_before)
            host.entry_ledger = entry_ledger_before
            rejected_items.append(_page_update_item_rejection(
                "region", index, raw,
                error_code="region_group_binding_rejected",
                field_name="equivalent_to_region_ref",
                reason=str(exc),
            ))
            rejected_region_keys.add(region_key)
            continue
        deferred_frames = host.entry_review_deferred_frames.get(
            _page_key(canonical_page), {})
        if (requested_complete
                and deferred_frames.get(region_key)
                and deferred_frames.get(region_key) != frame_id):
            deferred_frames.pop(region_key, None)
            if not deferred_frames:
                host.entry_review_deferred_frames.pop(
                    _page_key(canonical_page), None)
        accepted_regions.append(updated_name)
        accepted_region_keys[region_key] = updated_name
        accepted_correction_keys.add(f"region:{region_key}")
        resolved_region_reviews = (
            pending_reviews_for_ref if requested_region_ref
            else pending_reviews_for_name
        )
        for correction_key in resolved_region_reviews:
            accepted_correction_keys.add(correction_key)
        if resolved_region_reviews:
            review = next(iter(resolved_region_reviews.values()))
            candidate_ref = str(review.get("region_ref") or "").strip()
            candidate_name = str(review.get("canonical_name") or "").strip()
            reason = str(normalized.get("equivalence_reason") or "").strip()
            if requested_region_ref:
                message = (
                    f"Region comparison resolved: {updated_name!r} was confirmed "
                    f"equivalent to {candidate_ref} ({candidate_name!r}) and the "
                    "shared Region relationship was committed."
                )
            else:
                message = (
                    f"Region comparison resolved: {updated_name!r} remains "
                    f"distinct from {candidate_ref} ({candidate_name!r}) and was "
                    "recorded as an independent Region."
                )
            if reason:
                message += f" Agent reason: {reason}"
            region_equivalence_feedback.append(message[:800])
        if requested_complete and region_key in raw_entry_region_keys:
            completion_candidates.append({
                "index": index, "name": updated_name, "key": region_key,
            })

    snapshot = state.snapshot()
    updated_regions = [
        region for region in snapshot.get("regions") or []
        if _page_key(region.get("name")) in accepted_region_keys
    ]
    if updated_regions:
        host.protocol_map.upsert_regions(canonical_page, updated_regions)

    source_state_id = scene.state_id
    discovery_screenshot_path = ""
    regions_with_rejected_entries = set()
    for index, raw in enumerate(update.new_entries):
        normalized, rejection = _normalize_new_entry_item(raw, index)
        if rejection is not None:
            rejected_items.append(rejection)
            region_name = rejection.get("region_name")
            if region_name:
                regions_with_rejected_entries.add(_page_key(region_name))
            continue
        assert normalized is not None
        region_name = str(normalized["region_name"])
        region_key = _page_key(region_name)
        equivalent_to_entry_id = str(
            normalized.get("equivalent_to_entry_id") or "").strip()
        if (equivalent_to_entry_id
                and equivalent_to_entry_id not in preexisting_entry_ids):
            rejected_items.append(_page_update_item_rejection(
                "new_entry", index, raw,
                error_code="invalid_entry_ref",
                field_name="equivalent_to_entry_id",
                reason=(
                    "equivalent_to_entry_id must cite a verified entry candidate "
                    "that existed before this page_update"),
            ))
            regions_with_rejected_entries.add(region_key)
            continue
        region_is_available = (
            region_key in accepted_region_keys
            or (
                region_key in existing_regions
                and region_key not in rejected_region_keys
            )
        )
        if not region_is_available:
            rejected_items.append(_page_update_item_rejection(
                "new_entry", index, raw,
                error_code="unknown_region_reference",
                field_name="region_name",
                reason="region_name must reference an existing or accepted Region",
            ))
            regions_with_rejected_entries.add(region_key)
            continue
        canonical_region_name = (
            accepted_region_keys.get(region_key)
            or existing_regions.get(region_key)
            or region_name
        )
        owner_ref = host.region_registry.region_ref(
            canonical_page, canonical_region_name)
        owner_occurrence_ref = host.region_registry.occurrence_ref(
            canonical_page, canonical_region_name)
        required_state_ref = host.region_registry.occurrence_state_ref(
            canonical_page, canonical_region_name, source_state_id)
        if not owner_ref:
            rejected_items.append(_page_update_item_rejection(
                "new_entry", index, raw,
                error_code="unknown_region_reference",
                field_name="region_name",
                reason=(
                    "region_name must reference a Region with a committed "
                    "framework identity"),
            ))
            regions_with_rejected_entries.add(region_key)
            continue
        if equivalent_to_entry_id:
            try:
                representative_id = host.entry_ledger.canonical_entry_id(
                    equivalent_to_entry_id)
                representative = host.entry_ledger.get(representative_id)
            except (KeyError, ValueError) as exc:
                rejected_items.append(_page_update_item_rejection(
                    "new_entry", index, raw,
                    error_code="invalid_entry_ref",
                    field_name="equivalent_to_entry_id",
                    reason=str(exc),
                ))
                regions_with_rejected_entries.add(region_key)
                continue
            representative_ref = host.region_registry.region_ref(
                representative.page_name, representative.region_name)
            if (
                not owner_ref
                or not representative_ref
                or owner_ref != representative_ref
            ):
                rejected_items.append(_page_update_item_rejection(
                    "new_entry", index, raw,
                    error_code="entry_region_scope_mismatch",
                    field_name="equivalent_to_entry_id",
                    reason=(
                        "equivalent_to_entry_id can reuse evidence only "
                        "inside the same committed Region identity; current "
                        f"owner ref={owner_ref or '<unbound>'}, "
                        f"representative ref={representative_ref or '<unbound>'}"
                    ),
                ))
                regions_with_rejected_entries.add(region_key)
                continue
        try:
            delta = host.entry_ledger.record_agent_update(
                page_name=canonical_page,
                region_name=canonical_region_name,
                frame_id=frame_id,
                observations=[normalized],
                source_state_id=source_state_id,
                owner_region_ref=owner_ref,
                representative_occurrence_ref=owner_occurrence_ref,
                discovery_screenshot_path=discovery_screenshot_path,
                required_state_ref=required_state_ref,
                required_page_modes=(
                    host.scope_state_ledger.current_page_mode_requirements(
                        canonical_page)
                ),
            )
            host.region_registry.bind(
                page_name=canonical_page,
                region_name=canonical_region_name,
                state_id=source_state_id,
                variant_name=host.protocol_map.current_variant,
                equivalent_to_region_ref=owner_ref,
            )
            if delta.added and not discovery_screenshot_path:
                discovery_screenshot_path = (
                    host.writer.save_entry_discovery_frame(screenshot))
                for entry_id in delta.added:
                    host.entry_ledger.get(
                        entry_id).discovery_screenshot_path = (
                            discovery_screenshot_path)
        except (KeyError, ValueError) as exc:
            rejected_items.append(_page_update_item_rejection(
                "new_entry", index, raw, error_code="entry_update_rejected",
                field_name="", reason=str(exc)))
            regions_with_rejected_entries.add(region_key)
            continue
        for entry_id in delta.added:
            entry = host.entry_ledger.get(entry_id)
            created_entries.append({
                "entry_id": entry.entry_id,
                "target": entry.target,
                "operation": entry.operation or entry.target,
                "subject": entry.subject or entry.region_name,
                "region_name": entry.region_name,
                "status": entry.status.value,
                "exploration_policy": entry.exploration_policy,
            })
        for entry_id in delta.matched:
            if any(item["entry_id"] == entry_id for item in matched_entries):
                continue
            entry = host.entry_ledger.get(entry_id)
            matched_entries.append({
                "entry_id": entry.entry_id,
                "target": entry.target,
                "operation": entry.operation or entry.target,
                "subject": entry.subject or entry.region_name,
                "region_name": entry.region_name,
                "match": "duplicate_entry_exact",
                "status": entry.status.value,
                "exploration_policy": entry.exploration_policy,
            })
        accepted_correction_keys.add(
            f"entry:{region_key}:{_page_key(normalized['target'])}")

    for candidate in completion_candidates:
        if candidate["key"] in regions_with_rejected_entries:
            rejected_items.append({
                "kind": "region",
                "index": candidate["index"],
                "region_name": candidate["name"],
                "error_code": "coverage_completion_deferred",
                "field": "coverage_complete",
                "reason": (
                    "coverage_complete deferred because an entry for this "
                    "Region was rejected"
                ),
            })
        else:
            state.set_coverage_complete(candidate["name"], True)

    if accepted_region_keys:
        snapshot = state.snapshot()
        host.protocol_map.upsert_regions(canonical_page, [
            region for region in snapshot.get("regions") or []
            if _page_key(region.get("name")) in accepted_region_keys
        ])
        empty_surveys = host.empty_region_surveys.get(
            _page_key(canonical_page))
        if empty_surveys is not None:
            empty_surveys.discard(scene.state_id)
            if not empty_surveys:
                host.empty_region_surveys.pop(
                    _page_key(canonical_page), None)
    if created_entries:
        _record_agent_inferred_edges(host)
    scope_delta = _apply_target_edge_scope(host)

    accepted_regions = list(dict.fromkeys(accepted_regions))
    if rejected_items:
        status = "partial" if accepted_regions or created_entries else "rejected"
    else:
        status = "accepted"
    task = host.exploration_task
    empty_region_survey_completed = bool(
        status == "accepted"
        and not update.regions
        and not update.new_entries
        and not state.snapshot().get("regions")
        and not host.page_update_corrections.get(_page_key(canonical_page))
        and task is not None
        and task.task_type == "survey_page"
        and task.phase == "record_regions"
        and _page_key(task.page_name) == _page_key(canonical_page)
    )
    if empty_region_survey_completed:
        host.empty_region_surveys.setdefault(
            _page_key(canonical_page), set()).add(scene.state_id)
        host.pending_page_resurveys.pop(_page_key(canonical_page), None)
    if update.regions and not rejected_items:
        accepted_correction_keys.update(
            key for key in (
                host.page_update_corrections.get(
                    _page_key(canonical_page), {}) or {}
            )
            if key.startswith("invalid_region:")
            or key.startswith("invalid_entry:")
        )
    _update_page_corrections(
        host,
        canonical_page,
        accepted_keys=accepted_correction_keys,
        rejected_items=rejected_items,
    )
    result = {
        "kind": "page_update_result",
        "screen": canonical_page,
        "status": status,
        "accepted_regions": accepted_regions,
        "created_entries": created_entries,
        **({"reopened_entries": list(dict.fromkeys(reopened_entries))}
           if reopened_entries else {}),
        **({"matched_entries": matched_entries} if matched_entries else {}),
        "rejected_items": rejected_items,
        **({"feedback": " ".join(region_equivalence_feedback)}
           if region_equivalence_feedback else {}),
        **({"target_edge_scope": scope_delta} if scope_delta else {}),
        **({"mapped_region_sources": mapped_region_sources}
           if mapped_region_sources else {}),
        **({"empty_region_survey_completed": scene.state_id}
           if empty_region_survey_completed else {}),
    }
    history.append(result)
    if result_out is not None:
        result_out.update(deepcopy(result))
    return ""
