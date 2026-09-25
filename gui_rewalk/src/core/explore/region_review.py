"""Region/Element/Operation identity review using ledger facts and saved frames.

The caller supplies the current ledger and adopts the returned ledger after a
Region review. This module prepares evidence, calls screenshot reviewers and
validates their identity decisions. It does not select or execute GUI actions.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .artifacts import ArtifactStore
from .contracts import PageReport, ReportCorrections, ReportCorrectionExhausted
from .inventory import _find_element, _validate_report_operations, _validate_report_region_refs, _validate_unique_element_refs
from .ledger import ExplorationLedger
from .models import Operation
from .settlement import SettlementContractError
from .regions import (
    coalesce_complete_region_occurrences,
    merge_region_identity,
    shortlist_region_candidate_occurrences,
)
from .region_routes import refresh_transition_region_effects


def pending_region_reviews(
    ledger: ExplorationLedger, state_id: str,
) -> Dict[str, Any]:
    pending: Dict[str, Any] = {}
    for event in ledger.events:
        payload = event["payload"]
        if payload.get("state_id") != state_id:
            continue
        if event["kind"] == "region_review_batch_finished":
            for region_id in payload["region_ids"]:
                pending.pop(region_id, None)
        elif event["kind"] == "region_review_observed":
            for region_id in payload["new_region_ids"]:
                pending[region_id] = {
                    "observations": [],
                    "source_attempt_ref": payload["source_attempt_ref"],
                    "suggested_region_ids": payload["suggested_region_ids"],
                }
            for region_id, operations in payload["observed_operations"].items():
                if region_id in pending:
                    pending[region_id]["observations"].append({
                        "screenshot_ref": payload["screenshot_ref"],
                        "operation_ids": operations,
                    })
    return {
        region_id: record for region_id, record in pending.items()
        if region_id in ledger.regions
    }


def _region_review_source(
    ledger: ExplorationLedger, state_id: str, attempt_ref: Optional[str] = None,
) -> tuple[Optional[tuple[str, str]], Optional[Dict[str, Any]]]:
    for transition in reversed(ledger.transitions):
        if (transition.target_state_id != state_id
                or (attempt_ref is not None
                    and transition.attempt_id != attempt_ref)):
            continue
        attempt = ledger.attempts.get(transition.attempt_id)
        if attempt is None:
            continue
        operation = ledger.operations.get(
            str(attempt.action.get("operation_ref") or ""))
        if operation is None:
            continue
        source_occurrence = next((
            ledger.occurrences[occurrence_id]
            for occurrence_id in operation.source_occurrence_ids
            if (occurrence_id in ledger.occurrences
                and ledger.occurrences[occurrence_id].state_id
                == attempt.source_state_id)
        ), None)
        if source_occurrence is None:
            continue
        return (operation.region_id, source_occurrence.occurrence_id), {
            "attempt_ref": attempt.attempt_id,
            "source_state_ref": attempt.source_state_id,
            "target_state_ref": state_id,
            "source_region_ref": operation.region_id,
            "operation_ref": operation.operation_id,
            "action": operation.action,
            "target": operation.target,
            "visible_result": (
                attempt.visible_result or transition.visible_result),
        }
    return None, None


def build_region_identity_payload(
    ledger: ExplorationLedger, artifacts: ArtifactStore,
    *,
    state_id: str,
    current_region_ids: Sequence[str],
    current_screenshot: bytes,
    suggested_region_ids: Sequence[str] = (),
    review_records: Optional[Mapping[str, Any]] = None,
    rediscovering: bool = False,
) -> tuple[Dict[str, Any], List[bytes], set[str]]:
    payload: Dict[str, Any] = {
        "current_regions": [],
        "known_region_candidates": [],
        "source_transition": None,
    }
    screenshots = [current_screenshot]
    frame_images: Dict[str, str] = {}

    def frame_image(frame_ref: str) -> str:
        if frame_ref not in frame_images:
            data = artifacts.read(frame_ref)
            if data not in screenshots:
                screenshots.append(data)
            frame_images[frame_ref] = f"图{screenshots.index(data) + 1}"
        return frame_images[frame_ref]

    source_candidates = []
    for occurrence in ledger.state_occurrences(state_id):
        if occurrence.region_id not in current_region_ids:
            continue
        region = ledger.regions[occurrence.region_id]
        record = (review_records or {}).get(region.region_id)
        images: List[str] = []
        operation_images: Dict[str, List[str]] = {}
        if record is not None:
            for observation in reversed(record["observations"]):
                operations = observation["operation_ids"]
                if images and all(item in operation_images for item in operations):
                    continue
                label = frame_image(observation["screenshot_ref"])
                if label not in images:
                    images.append(label)
                for operation_id in operations:
                    operation_images.setdefault(operation_id, []).append(label)
        else:
            images = ["图1"]
        source_candidate, source = _region_review_source(
            ledger,
            state_id, record["source_attempt_ref"] if record is not None else None)
        if source is not None:
            effects = next((event["payload"] for event in reversed(ledger.events)
                            if event["kind"] == "region_effects_reported"
                            and event["payload"]["attempt_ref"] == source["attempt_ref"]), None)
            # An omitted attribution leaves the real incoming action available
            # for screenshot review; it does not establish an action effect.
            if effects is not None and any(
                    item["region_ref"] == region.region_id
                    and item["cause"] in {"external", "uncertain"}
                    for item in effects["changes"]):
                source_candidate, source = None, None
        if source_candidate is not None:
            if source_candidate[0] not in current_region_ids:
                source_candidates.append(source_candidate)
            if record is not None:
                attempt = ledger.attempts[source["attempt_ref"]]
                source["before_image"] = frame_image(attempt.before_ref)
        if review_records is None:
            payload["source_transition"] = source
        payload["current_regions"].append({
            "current_region_ref": region.region_id,
            "parent_region_ref": (ledger.occurrences[occurrence.parent_occurrence_id].region_id
                                  if occurrence.parent_occurrence_id else ""),
            "child_region_refs": [child.region_id for child in ledger.state_occurrences(state_id)
                                  if child.parent_occurrence_id == occurrence.occurrence_id],
            "current_variant_ref": occurrence.variant_id,
            "images": images,
            "source_transition": source,
            "name": occurrence.name,
            "summary": occurrence.summary,
            "operations": [{
                "operation_ref": item.operation_id,
                "canonical_operation_ref": item.canonical_operation_id,
                "images": (operation_images.get(item.operation_id, [])
                           if record is not None else images),
                "action": item.action,
                "target": item.target,
                "scope": item.scope,
                "element": (
                    ledger.elements[item.element_id].name
                    if item.element_id in ledger.elements else ""),
                "direction": item.direction,
                "parameter_status": item.parameter_status,
                "parameter_summary": item.parameter_summary,
                "verified_result": _verified_operation_result(
                    ledger,
                    operation_id=item.operation_id,
                    state_id=state_id,
                ),
            } for item in ledger.occurrence_operations(
                occurrence.occurrence_id)],
        })
    state_image_number: Dict[str, int] = {}
    allowed: set[str] = set()
    shortlisted = shortlist_region_candidate_occurrences(
        ledger,
        state_id=state_id,
        current_region_ids=current_region_ids,
        prefer_same_page=not rediscovering,
    )
    # A known State's pre-existing Regions must be available for an incremental
    # candidate; the cross-State shortlist intentionally excludes them.
    forced_candidates = [
        (item.region_id, item.occurrence_id)
        for item in ledger.state_occurrences(state_id)
        if item.region_id not in current_region_ids
    ]
    for candidate in source_candidates:
        if not any(item[0] == candidate[0] for item in forced_candidates):
            forced_candidates.append(candidate)
    for region_id in dict.fromkeys(suggested_region_ids):
        if any(item[0] == region_id for item in forced_candidates):
            continue
        selected = next((
            item for item in shortlisted if item[0] == region_id
        ), None)
        if selected is not None:
            forced_candidates.append(selected)
            continue
        occurrence = next((
            item for item in ledger.occurrences.values()
            if item.region_id == region_id and item.state_id != state_id
        ), None)
        if occurrence is not None:
            forced_candidates.append((region_id, occurrence.occurrence_id))
    shortlisted = forced_candidates + [
        item for item in shortlisted
        if not any(candidate[0] == item[0] for candidate in forced_candidates)
    ]
    payload["suggested_known_region_refs"] = list(
        dict.fromkeys(suggested_region_ids))
    parentage_pairs = set()
    for child in ledger.occurrences.values():
        parent_id = child.parent_occurrence_id
        visited = set()
        while parent_id and parent_id not in visited:
            visited.add(parent_id)
            parent = ledger.occurrences.get(parent_id)
            if parent is None:
                break
            parentage_pairs.add((child.region_id, parent.region_id))
            parentage_pairs.add((parent.region_id, child.region_id))
            parent_id = parent.parent_occurrence_id
    for current in payload["current_regions"]:
        current["identity_constraints"] = {
            "cannot_reuse_region_refs": sorted(known for child, known in parentage_pairs
                if child == current["current_region_ref"]),
            "reason": "已有父子/祖先归属不能通过身份复用折叠；候选仍可用于控件与来源比较。",
        }
    for region_id, occurrence_id in shortlisted:
        region = ledger.regions[region_id]
        occurrence = ledger.occurrences[occurrence_id]
        candidate_state = ledger.states[occurrence.state_id]
        if candidate_state.state_id not in state_image_number:
            try:
                candidate_image = artifacts.read(
                    candidate_state.screenshot_ref)
            except OSError:
                ledger.event(
                    "region_candidate_screenshot_unavailable",
                    state_id=state_id,
                    candidate_region_id=region_id,
                    candidate_state_id=candidate_state.state_id,
                    explicitly_suggested=region_id in suggested_region_ids,
                )
                continue
            if candidate_image not in screenshots:
                screenshots.append(candidate_image)
            state_image_number[candidate_state.state_id] = (
                screenshots.index(candidate_image) + 1)
        candidate_page = ledger.pages[candidate_state.page_id]
        visible_operations = ledger.occurrence_operations(
            occurrence.occurrence_id)
        visible_operation_ids = {
            item.operation_id for item in visible_operations}
        catalog_operations: List[Operation] = []
        seen_canonical_refs: set[str] = set()
        for item in (
                visible_operations + ledger.region_operations(region_id)):
            canonical_ref = (
                item.canonical_operation_id or item.operation_id)
            if canonical_ref in seen_canonical_refs:
                continue
            seen_canonical_refs.add(canonical_ref)
            catalog_operations.append(item)
        payload["known_region_candidates"].append({
            "known_region_ref": region.region_id,
            "known_variant_ref": occurrence.variant_id,
            "image": f"图{state_image_number[candidate_state.state_id]}",
            "page": candidate_page.name,
            "state": candidate_state.name,
            "name": region.name,
            "summary": region.summary,
            "operations": [{
                "operation_ref": item.operation_id,
                "canonical_operation_ref": (
                    item.canonical_operation_id),
                "action": item.action,
                "target": item.target,
                "scope": item.scope,
                "element": (
                    ledger.elements[item.element_id].name
                    if item.element_id in ledger.elements else ""),
                "direction": item.direction,
                "parameter_status": item.parameter_status,
                "parameter_summary": item.parameter_summary,
                "verified_result": (
                    _verified_operation_result(
                        ledger,
                        operation_id=item.operation_id,
                        state_id=candidate_state.state_id)
                    if item.operation_id in visible_operation_ids else ""),
                "visible_in_candidate_state": (
                    item.operation_id in visible_operation_ids),
            }
                for item in catalog_operations],
        })
        allowed.add(region.region_id)
    ledger.event(
        "region_identity_candidates_shortlisted",
        state_id=state_id,
        current_region_count=len(current_region_ids),
        candidate_region_count=len(payload["known_region_candidates"]),
        candidate_state_count=len(state_image_number),
        candidate_state_limit=2,
        source_candidate_included=bool(source_candidates),
        suggested_region_ids=list(dict.fromkeys(suggested_region_ids)),
    )
    return payload, screenshots, allowed


def _verified_operation_result(
    ledger: ExplorationLedger,
    *,
    operation_id: str,
    state_id: str,
) -> str:
    for attempt in reversed(list(ledger.attempts.values())):
        if (attempt.source_state_id == state_id
                and attempt.purpose == "execute"
                and attempt.outcome == "success"
                and attempt.action.get("operation_ref") == operation_id
                and attempt.visible_result):
            return attempt.visible_result
    return ""


def review_page_report_element_candidates(
    ledger: ExplorationLedger, agent: Any,
    *,
    report: PageReport,
    state_id: str,
    screenshot: bytes,
    corrections: Optional[ReportCorrections] = None,
) -> PageReport:
    _validate_unique_element_refs(report)
    _validate_report_region_refs(ledger, state_id, report)
    _validate_report_operations(ledger, report)
    reviewer = getattr(agent, "review_element_identities", None)
    if not callable(reviewer):
        return report
    state = ledger.states.get(state_id)
    if state is None:
        return report
    page = ledger.pages.get(state.page_id)
    candidates = []
    positions: Dict[int, tuple[int, int, str]] = {}
    variant_contexts: Dict[str, Dict[str, Any]] = {}
    issues = []
    for region_index, region_report in enumerate(report.regions):
        if not region_report.region_ref:
            continue
        occurrence = next((
            item for item in ledger.state_occurrences(state_id)
            if item.region_id == region_report.region_ref
        ), None)
        if occurrence is None:
            continue
        variant = ledger.ensure_occurrence_variant(
            occurrence.occurrence_id)
        variant_contexts.setdefault(variant.variant_id, {
            "region_ref": occurrence.region_id,
            "variant_ref": variant.variant_id,
            "known_elements": [{
                "element_ref": element.element_id,
                "name": element.name,
                "operations": [{
                    "action": operation.action,
                    "target": operation.target,
                    "direction": operation.direction,
                } for operation in ledger.element_operations(
                    element.element_id)],
            } for element in ledger.variant_elements(
                variant.variant_id)],
        })
        for element_index, element in enumerate(region_report.elements):
            if element.element_ref:
                if _find_element(ledger, variant.variant_id, element) is None:
                    issues.append(
                        f"page_report.regions[{region_index}].elements[{element_index}] "
                        f"name={element.name!r} element_ref={element.element_ref!r} "
                        f"does not belong to region_ref={occurrence.region_id} "
                        f"variant_ref={variant.variant_id}")
                continue
            candidate_index = len(candidates)
            positions[candidate_index] = (
                region_index, element_index, variant.variant_id)
            candidates.append({
                "candidate_index": candidate_index,
                "region_ref": occurrence.region_id,
                "variant_ref": variant.variant_id,
                "name_hint": element.name,
                "operation_hints": [asdict(item)
                                    for item in element.operations],
            })
    if issues:
        raise ValueError("; ".join(issues) + "；请主Agent核对候选的区块归属和引用，允许修正清单，不要跨区块借用控件。")
    if not candidates:
        return report
    corrections = corrections or ReportCorrections()
    correction = ""
    while corrections.count < corrections.limit:
        payload = {
            "current_page": page.name if page is not None else state.page_id,
            "current_state": state.name,
            "variant_contexts": list(variant_contexts.values()),
            "candidate_elements": candidates,
        }
        if correction:
            payload["correction"] = correction
            corrections.events.append({"round": corrections.count + 1, "recipient": "element_reviewer", "phase": "delivered", "required_change": correction})
        try:
            reviewed = reviewer(payload=payload, screenshots=[screenshot])
            return _resolve_element_identity_decisions(ledger, report, candidates, positions, reviewed)
        except ElementCandidateConflict:
            raise  # The main Agent can change the proposal; the Reviewer cannot.
        except (TypeError, ValueError) as exc:
            if not corrections.reject(exc, "element_reviewer"):
                raise ReportCorrectionExhausted(str(exc)) from exc
            correction = (
                f"第{corrections.count + 1}/{corrections.limit}轮纠正：你的上次审核回复未通过。{exc} "
                "请核对每个候选自己的region_ref/variant_ref，只选对应版本中的已知引用或new；"
                "若候选分区有疑问，返回uncertain并说明需主Agent修改哪里。")
    raise ReportCorrectionExhausted("本轮清单纠正预算已经用完，不再调用Reviewer。")


class ElementCandidateConflict(ValueError):
    """The main Agent must clarify its proposed partition or target."""


def _resolve_element_identity_decisions(ledger, report, candidates, positions, reviewed):
    issues = []
    if not isinstance(reviewed, Mapping):
        raise ValueError("Element Reviewer 回复必须是包含 decisions 的对象。")
    decisions = reviewed.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Element Reviewer 的 decisions 不是数组；请修正审核回复的结构。")
    expected = set(positions)
    seen = set()
    replacements: Dict[int, str] = {}
    for item in decisions:
        if not isinstance(item, Mapping):
            raise ValueError("Element Reviewer 的 decisions 项不是对象；请修正该审核项；若候选归属本身无法确认，返回uncertain并指出需主Agent核对的分区或控件。")
        candidate_index = item.get("candidate_index")
        if candidate_index not in expected or candidate_index in seen:
            raise ValueError(
                f"Element Reviewer 的 candidate_index={candidate_index!r} 未知或重复；"
                "请只使用本次candidate_index且每项一次。")
        seen.add(candidate_index)
        decision = str(item.get("decision") or "").strip()
        known_ref = str(item.get("known_element_ref") or "").strip()
        variant_id = positions[candidate_index][2]
        if decision == "reuse":
            element = ledger.elements.get(known_ref)
            if element is None or element.variant_id != variant_id:
                raise ValueError(
                    f"Element Reviewer 候选 {candidate_index} 的 known_element_ref={known_ref!r} "
                    f"不属于当前 Variant {variant_id}；请修正该审核项；若候选归属本身无法确认，返回uncertain并指出需主Agent核对的分区或控件。")
            replacements[candidate_index] = known_ref
        elif decision == "new":
            if known_ref:
                raise ValueError(
                    f"Element Reviewer 候选 {candidate_index} 同时返回 new 和 known_element_ref={known_ref!r}；"
                    "审核回复自相矛盾；new对应的known_element_ref应为空。")
            replacements[candidate_index] = ""
        elif decision == "uncertain":
            region_index, element_index, _ = positions[candidate_index]
            candidate = candidates[candidate_index]
            issues.append(
                f"Element candidate remains uncertain: page_report.regions[{region_index}]"
                f".elements[{element_index}] {candidate['name_hint']!r} "
                f"(region_ref={candidate['region_ref']}, variant_ref={variant_id}): "
                f"{item.get('reason') or '(not provided)'}")
        else:
            raise ValueError(
                f"Element Reviewer 候选 {candidate_index} 的 decision={decision!r} 非法；"
                "请修正该审核项；若候选归属本身无法确认，返回uncertain并指出需主Agent核对的分区或控件。")
    if seen != expected:
        raise ValueError(
            f"Element Reviewer 遗漏候选 {sorted(expected - seen)}；"
            "请补齐这些候选的审核决定，不要删除未审核控件。")
    if issues:
        raise ElementCandidateConflict("主Agent可修正候选分区、具体控件描述或引用，再提交page_report；不要强制保持原候选不变。冲突：" + "; ".join(issues))
    regions = list(report.regions)
    for candidate_index, element_ref in replacements.items():
        region_index, element_index, _variant_id = positions[candidate_index]
        elements = list(regions[region_index].elements)
        elements[element_index] = replace(
            elements[element_index], element_ref=element_ref)
        regions[region_index] = replace(
            regions[region_index], elements=tuple(elements))
    resolved = replace(report, regions=tuple(regions))
    try:
        _validate_unique_element_refs(resolved)
    except ValueError as exc:
        raise ValueError(
            "Element Reviewer 应用身份后出现引用冲突：" + str(exc).split("。", 1)[0]
            + "。这不证明两个候选是同一控件；请重新核对reuse/new决定；不能确认身份时返回uncertain并说明冲突，不要为通过检查合并按钮。") from exc
    ledger.event(
        "element_identity_batch_reviewed",
        candidate_count=len(candidates),
        reused_count=sum(bool(item) for item in replacements.values()),
        new_count=sum(not item for item in replacements.values()),
    )
    return resolved


def _review_operation_identity_candidates(
    ledger: ExplorationLedger, agent: Any,
    *,
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
    screenshots: Sequence[bytes],
    state_id: str,
    corrections: Optional[ReportCorrections] = None,
) -> Optional[Dict[tuple[str, str], str]]:
    reviewer = getattr(agent, "review_operation_identities", None)
    if not callable(reviewer):
        return None
    current = {
        str(operation.get("operation_ref") or ""): operation
        for region in payload.get("current_regions") or []
        for operation in region.get("operations") or []
    }
    known = {
        str(operation.get("operation_ref") or ""): (region, operation)
        for region in payload.get("known_region_candidates") or []
        for operation in region.get("operations") or []
    }
    state = ledger.states.get(state_id)
    page = ledger.pages.get(state.page_id if state else "")
    candidates: Dict[tuple[str, str], Dict[str, Any]] = {}
    for decision in result.get("decisions") or []:
        if (not isinstance(decision, Mapping)
                or str(decision.get("decision") or "") != "reuse"):
            continue
        for pair in decision.get("shared_operations") or []:
            if not isinstance(pair, Mapping):
                continue
            key = (
                str(pair.get("current_operation_ref") or "").strip(),
                str(pair.get("known_operation_ref") or "").strip(),
            )
            current_operation = current.get(key[0])
            known_record = known.get(key[1])
            if current_operation is None or known_record is None:
                continue
            known_region, known_operation = known_record
            proposed = str(pair.get("reuse_level") or "").strip()
            if (key in candidates
                    and candidates[key]["proposed_reuse_level"] == "result"):
                proposed = "result"
            candidates[key] = {
                "current_region_ref": str(
                    decision.get("current_region_ref") or ""),
                "known_region_ref": str(
                    decision.get("known_region_ref") or ""),
                "current_page": current_operation.get("source_page", page.name if page is not None else ""),
                "current_state": current_operation.get("source_state", state.name if state is not None else ""),
                "known_page": str(known_region.get("page") or ""),
                "known_state": str(known_region.get("state") or ""),
                "known_image": str(known_region.get("image") or ""),
                "current_images": current_operation.get("images", ["图1"]),
                "current_operation_ref": key[0],
                "known_operation_ref": key[1],
                "action": str(current_operation.get("action") or ""),
                "scope": str(current_operation.get("scope") or ""),
                "direction": str(current_operation.get("direction") or ""),
                "current_element_hint": str(
                    current_operation.get("element") or ""),
                "current_target_hint": str(
                    current_operation.get("target") or ""),
                "known_element_hint": str(
                    known_operation.get("element") or ""),
                "known_target_hint": str(
                    known_operation.get("target") or ""),
                "current_parameter_status": str(
                    current_operation.get("parameter_status") or ""),
                "current_parameter_summary": str(
                    current_operation.get("parameter_summary") or ""),
                "known_parameter_status": str(
                    known_operation.get("parameter_status") or ""),
                "known_parameter_summary": str(
                    known_operation.get("parameter_summary") or ""),
                "known_visible_in_candidate_state": bool(
                    known_operation.get("visible_in_candidate_state", True)),
                "known_verified_result_hint": str(
                    known_operation.get("verified_result") or ""),
                "proposed_reuse_level": proposed,
            }
    if not candidates:
        return {}
    corrections = corrections or ReportCorrections()
    correction = ""
    while corrections.count < corrections.limit:
        try:
            reviewed = reviewer(
                payload={"candidate_pairs": list(candidates.values()), **({"correction": correction} if correction else {})},
                screenshots=screenshots,
            )
            decisions = reviewed.get("decisions")
            if not isinstance(decisions, list):
                raise ValueError("Operation Reviewer.decisions must be an array；未批准任何操作复用，原操作分别保留。")
            expected = set(candidates)
            seen: set[tuple[str, str]] = set()
            approved: Dict[tuple[str, str], str] = {}
            for item in decisions:
                if not isinstance(item, Mapping):
                    raise ValueError(
                        "each Operation identity decision must be an object")
                key = (
                    str(item.get("current_operation_ref") or "").strip(),
                    str(item.get("known_operation_ref") or "").strip(),
                )
                if key not in expected or key in seen:
                    raise ValueError(
                        f"Operation identity decision has an unknown or duplicate pair {key}；"
                        "只复制 candidate_pairs 中的编号，每对报告一次；本批次复用未批准。")
                seen.add(key)
                decision = str(item.get("decision") or "").strip()
                reuse_level = str(item.get("reuse_level") or "").strip()
                if decision == "same":
                    if reuse_level not in {"identity", "result"}:
                        raise ValueError(
                            f"Operation pair {key}: same Operation requires identity or result reuse_level，收到 {reuse_level!r}")
                    approved[key] = (
                        "result"
                        if reuse_level == "result"
                        and candidates[key]["proposed_reuse_level"] == "result"
                        else "identity")
                elif decision in {"different", "uncertain"}:
                    if reuse_level != "none":
                        raise ValueError(
                            f"Operation pair {key}: different or uncertain Operation requires reuse_level=none，收到 {reuse_level!r}")
                else:
                    raise ValueError(f"Operation pair {key}: invalid Operation identity decision {decision!r}；允许 same/different/uncertain。")
            if seen != expected:
                raise ValueError(f"Operation identity response omitted candidate pairs {sorted(expected - seen)}；所有候选对都需报告，未批准本批次复用。")
            ledger.event(
                "operation_identity_batch_reviewed",
                candidate_count=len(expected),
                approved_count=len(approved),
            )
            return approved
        except OSError as exc:
            ledger.event(
                "operation_identity_batch_unresolved",
                candidate_count=len(candidates),
                reason=str(exc)[:500],
            )
            return {}

        except (TypeError, ValueError) as exc:
            if not corrections.reject(exc, "operation_reviewer"):
                raise ReportCorrectionExhausted(str(exc)) from exc
            correction = f"第{corrections.count + 1}/{corrections.limit}轮：上次操作审核未接受。{exc} 请修正对应候选对的decisions，不能确认时用uncertain。"
            corrections.events.append({"round": corrections.count + 1, "recipient": "operation_reviewer", "phase": "delivered", "required_change": correction})
    raise ReportCorrectionExhausted("操作审核已达到本次报告共用上限。")


def review_region_identity(
    ledger: ExplorationLedger, agent: Any, artifacts: ArtifactStore,
    *,
    state_id: str,
    current_region_ids: Sequence[str],
    screenshot: bytes,
    suggested_region_ids: Sequence[str] = (),
    review_records: Optional[Mapping[str, Any]] = None,
    rediscovering: bool = False,
    corrections: Optional[ReportCorrections] = None,
) -> ExplorationLedger:
    if not current_region_ids:
        return ledger
    try:
        payload, screenshots, allowed_known = build_region_identity_payload(
            ledger, artifacts,
            state_id=state_id,
            current_region_ids=current_region_ids,
            current_screenshot=screenshot,
            suggested_region_ids=suggested_region_ids,
            review_records=review_records,
            rediscovering=rediscovering,
        )
    except OSError as exc:
        ledger.event(
            "region_identity_unresolved", state_id=state_id,
            region_ids=list(current_region_ids), reason=str(exc)[:500])
        return ledger
    if not allowed_known and not any(
            item.get("source_transition") for item in payload["current_regions"]):
        return ledger
    baseline = ledger
    correction = ""
    corrections = corrections or ReportCorrections()
    while corrections.count < corrections.limit:
        ledger = baseline.clone()
        try:
            result = agent.correspond_regions(
                payload=payload,
                screenshots=screenshots,
                correction=correction,
            )
            apply_region_identity_result(
                ledger.clone(), result=result, payload=payload,
                allowed_known=allowed_known,
                current_region_ids=current_region_ids,
            )
            reviewed_operation_levels = (
                _review_operation_identity_candidates(
                    ledger, agent,
                    result=result,
                    payload=payload,
                    screenshots=screenshots,
                    state_id=state_id,
                    corrections=corrections,
                )
            )
            ledger = apply_region_identity_result(
                ledger,
                result=result,
                payload=payload,
                allowed_known=allowed_known,
                current_region_ids=current_region_ids,
                reviewed_operation_levels=reviewed_operation_levels,
            )
            return ledger
        except OSError as exc:
            baseline.event("region_identity_unresolved", state_id=state_id,
                           region_ids=list(current_region_ids),
                           reason=f"审核证据或服务读取失败，不要求模型修改分区：{exc}")
            return baseline
        except SettlementContractError:
            raise  # A ledger invariant is not a Reviewer-editable decision.
        except (TypeError, ValueError) as exc:
            ledger = baseline
            issue = str(exc)[:500]
            if corrections.reject(exc, "region_reviewer"):
                baseline.event(
                    "region_identity_response_rejected",
                    state_id=state_id,
                    region_ids=list(current_region_ids),
                    reason=issue,
                )
                correction = (
                    "上次 Region 审核回复未接受，尚未应用该次合并。" + issue
                    + " 请根据原候选编号和截图修正 decisions；不能确认时保留 uncertain，不要编造引用或因果。")
                corrections.events.append({"round": corrections.count + 1, "recipient": "region_reviewer", "phase": "delivered", "required_change": correction})
                continue
            baseline.event(
                "region_identity_unresolved",
                state_id=state_id,
                region_ids=list(current_region_ids),
                reason=issue,
            )
            raise ReportCorrectionExhausted(issue) from exc
    raise ReportCorrectionExhausted("Region审核已达到本次报告共用上限。")


def apply_region_identity_result(
    ledger: ExplorationLedger,
    *,
    result: Dict[str, Any],
    payload: Dict[str, Any],
    allowed_known: set[str],
    current_region_ids: Sequence[str],
    reviewed_operation_levels: Optional[
        Mapping[tuple[str, str], str]] = None,
) -> ExplorationLedger:
    decisions = result.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Region Reviewer.decisions must be an array；按 current_regions 逐项返回审核对象。")
    expected = set(current_region_ids)
    seen: set[str] = set()
    reuse: Dict[str, List[str]] = {}
    reasons: Dict[str, List[str]] = {}
    operation_reuse: Dict[str, Dict[str, str]] = {}
    operation_levels: Dict[str, Dict[str, str]] = {}
    operation_result_texts: Dict[str, Dict[str, str]] = {}
    component_relations: Dict[str, str] = {}
    revealed_by_attempt: Dict[str, List[str]] = {}
    sources = {
        item["current_region_ref"]: item.get(
            "source_transition", payload.get("source_transition"))
        for item in payload["current_regions"]
    }
    current_operation_owner = {
        operation["operation_ref"]: region["current_region_ref"]
        for region in payload["current_regions"]
        for operation in region["operations"]
    }
    known_operation_owner = {
        operation["operation_ref"]: region["known_region_ref"]
        for region in payload["known_region_candidates"]
        for operation in region["operations"]
    }
    known_operation_results = {
        operation["operation_ref"]: str(
            operation.get("verified_result") or "").strip()
        for region in payload["known_region_candidates"]
        for operation in region["operations"]
    }
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("each Region decision must be an object")
        current = str(item.get("current_region_ref") or "").strip()
        decision = str(item.get("decision") or "").strip()
        component_relation = str(
            item.get("component_relation") or "").strip()
        causal_relation = str(
            item.get("causal_relation") or "").strip()
        known = str(item.get("known_region_ref") or "").strip()
        reason = str(item.get("reason") or "").strip()
        shared = item.get("shared_operations")
        if not isinstance(shared, list):
            raise ValueError(f"Region {current}: shared_operations must be an array；不共享时填 []。")
        if current not in expected or current in seen:
            raise ValueError(
                f"Region decision has missing, duplicate, or unknown current ref {current!r}；"
                f"允许的 current_region_ref={sorted(expected)}，每个报告一次。")
        seen.add(current)
        component_relations[current] = component_relation
        if decision == "reuse":
            if component_relation not in {
                    "same_complete_component",
                    "reconstructing_fragment"}:
                raise ValueError(
                    "reuse requires component_relation="
                    "same_complete_component or reconstructing_fragment")
            if causal_relation != "none":
                raise ValueError(
                    "reuse requires causal_relation=none; a Region that "
                    "reveals or is revealed by another surface is separate")
            if known not in allowed_known:
                raise ValueError(f"Region {current}: reuse references an unknown candidate Region {known!r}；"
                                 f"known_region_ref 只能复制 {sorted(allowed_known)}；无法确认同一组件时用 uncertain。")
            reuse.setdefault(known, []).append(current)
            reasons.setdefault(known, []).append(reason)
            mapped = operation_reuse.setdefault(known, {})
            for pair in shared:
                if not isinstance(pair, dict):
                    raise ValueError(
                        "each shared operation must be an object")
                current_operation = str(
                    pair.get("current_operation_ref") or "").strip()
                known_operation = str(
                    pair.get("known_operation_ref") or "").strip()
                reuse_level = str(
                    pair.get("reuse_level") or "").strip()
                if current_operation_owner.get(current_operation) != current:
                    raise ValueError(
                        f"Region {current}: shared operation references an unknown current Operation {current_operation!r}；"
                        f"该编号实际所属区块为 {current_operation_owner.get(current_operation)!r}，请复制本区块候选 operations 的编号。")
                if known_operation_owner.get(known_operation) != known:
                    raise ValueError(
                        f"Region {current} -> {known}: shared operation references an unknown known Operation {known_operation!r}；"
                        f"该编号实际所属区块为 {known_operation_owner.get(known_operation)!r}，请复制所选 known Region 的操作编号。")
                current_record = ledger.operations[current_operation]
                known_record = ledger.operations[known_operation]
                if current_record.action != known_record.action:
                    ledger.event(
                        "shared_operation_pair_ignored",
                        current_region_ref=current,
                        known_region_ref=known,
                        current_operation_ref=current_operation,
                        known_operation_ref=known_operation,
                        reason="动作类型不一致",
                    )
                    continue
                if reviewed_operation_levels is not None:
                    reviewed_level = reviewed_operation_levels.get(
                        (current_operation, known_operation))
                    if reviewed_level is None:
                        ledger.event(
                            "operation_identity_pair_not_approved",
                            current_region_ref=current,
                            known_region_ref=known,
                            current_operation_ref=current_operation,
                            known_operation_ref=known_operation,
                        )
                        continue
                    reuse_level = reviewed_level
                if reuse_level not in {"identity", "result"}:
                    raise ValueError(
                        f"shared operation {current_operation} -> {known_operation}: reuse_level={reuse_level!r} must be identity or result")
                if reuse_level == "result" and not (
                        known_operation_results.get(known_operation)
                        and known_record.status == "verified"):
                    reuse_level = "identity"
                    ledger.event(
                        "shared_operation_result_downgraded",
                        current_region_ref=current,
                        known_region_ref=known,
                        current_operation_ref=current_operation,
                        known_operation_ref=known_operation,
                        reason=(
                            "候选 Variant 没有已验证的真实结果；"
                            "只共享 canonical Operation 身份"),
                    )
                if current_operation in mapped:
                    previous_known = mapped[current_operation]
                    if previous_known != known_operation:
                        raise ValueError(
                            f"current Operation {current_operation} maps "
                            "to multiple known Operations: "
                            f"{previous_known}, {known_operation}")
                    levels = operation_levels.setdefault(known, {})
                    kept_level = (
                        "result"
                        if "result" in {
                            levels[current_operation], reuse_level}
                        else "identity"
                    )
                    levels[current_operation] = kept_level
                    if kept_level == "result":
                        operation_result_texts.setdefault(
                            known, {})[current_operation] = (
                                known_operation_results[known_operation])
                    ledger.event(
                        "duplicate_shared_operation_pair_collapsed",
                        current_region_ref=current,
                        known_region_ref=known,
                        current_operation_ref=current_operation,
                        known_operation_ref=known_operation,
                        kept_reuse_level=kept_level,
                    )
                    continue
                mapped[current_operation] = known_operation
                operation_levels.setdefault(
                    known, {})[current_operation] = reuse_level
                if reuse_level == "result":
                    operation_result_texts.setdefault(
                        known, {})[current_operation] = (
                            known_operation_results[known_operation])
        elif decision not in {"separate", "uncertain"}:
            raise ValueError(f"Region {current}: invalid Region identity decision {decision!r}；允许 reuse/separate/uncertain。")
        elif decision == "separate" and component_relation not in {
                "member_or_subregion", "trigger_or_result",
                "different_component"}:
            raise ValueError(
                f"Region {current}: separate requires component_relation="
                f"member_or_subregion/trigger_or_result/different_component，收到 {component_relation!r}")
        elif (decision == "separate"
              and component_relation == "trigger_or_result"
              and causal_relation not in {
                  "known_operation_reveals_current",
                  "current_operation_reveals_known",
              }):
            raise ValueError(
                f"Region {current}: trigger_or_result requires an explicit causal direction；"
                "有真实动作证据时causal_relation用known_operation_reveals_current或current_operation_reveals_known；无证据时不要保留trigger_or_result。边界明确不同改component_relation=different_component，causal_relation=none或uncertain；身份也不清楚时decision/component_relation/causal_relation都设uncertain。")
        elif (decision == "separate"
              and causal_relation not in {
                  "none", "uncertain", "known_operation_reveals_current",
                  "current_operation_reveals_known",
              }):
            raise ValueError(
                f"Region {current}: invalid causal_relation={causal_relation!r}")
        elif (decision == "uncertain"
              and (component_relation != "uncertain"
                   or causal_relation != "uncertain")):
            raise ValueError(
                "uncertain decision requires both relation fields=uncertain")
        elif shared:
            raise ValueError(
                "separate or uncertain Region cannot share Operations")
        elif known:
            ledger.event(
                "region_identity_comparison_ref_ignored",
                current_region_ref=current,
                decision=decision,
                known_region_ref=known,
                reason=(
                    "分开或不确定结论不使用候选区块编号；"
                    "保留结论并忽略该比较引用。"
                ),
            )
        if causal_relation == "known_operation_reveals_current":
            source_transition = sources.get(current)
            if not isinstance(source_transition, dict):
                raise ValueError(
                    f"Region {current}: revealed Region requires an exact incoming Transition；"
                    "原候选没有可用 source_transition，不能声明该动作显露此区块；"
                    "请保留非因果或 uncertain 结论，不要编造入边。")
            attempt_ref = str(
                source_transition.get("attempt_ref") or "").strip()
            transition = next((
                candidate for candidate in ledger.transitions
                if candidate.attempt_id == attempt_ref
                and candidate.source_state_id == str(
                    source_transition.get("source_state_ref") or "")
                and candidate.target_state_id == str(
                    source_transition.get("target_state_ref") or "")
                and str(candidate.action.get("operation_ref") or "")
                == str(source_transition.get("operation_ref") or "")
            ), None)
            operation = ledger.operations.get(str(
                source_transition.get("operation_ref") or ""))
            if (transition is None or operation is None
                    or operation.region_id != str(
                        source_transition.get("source_region_ref") or "")):
                raise ValueError(
                    f"Region {current}: revealed Region requires an exact incoming Transition；"
                    f"attempt_ref={attempt_ref!r} 未匹配已记录的来源/目标/操作组合；"
                    "请根据原 source_transition 核对，不能确认因果时填 uncertain，不要编造入边。")
            target_region_ids = {
                occurrence.region_id
                for occurrence in ledger.state_occurrences(
                    transition.target_state_id)
            }
            if current not in target_region_ids:
                raise ValueError(
                    f"Region {current}: revealed Region is not in the incoming target State "
                    f"{transition.target_state_id}（已登记 {sorted(target_region_ids)}）；请核对当前区块引用，不能凭时间先后声明显露。")
            revealed_region_ids = revealed_by_attempt.setdefault(attempt_ref, [])
            if current not in revealed_region_ids:
                revealed_region_ids.append(current)
    if seen != expected:
        raise ValueError(f"Region identity response omitted current Regions {sorted(expected - seen)}；每个 current_region_ref 都需报告，无法确认填 uncertain。")
    for known, current_ids in reuse.items():
        relations = [component_relations[item] for item in current_ids]
        if relations == ["same_complete_component"]:
            continue
        if (len(relations) < 2
                or any(item != "reconstructing_fragment"
                       for item in relations)):
            raise ValueError(
                "同一候选 Region 的 reuse 必须是一个完整当前组件，或由至少"
                "两个全部标为 reconstructing_fragment 的当前片段共同重构"
                f"（候选 Region {known}）")
    for known, current_ids in reuse.items():
        complete_variants = {
            item.get("current_variant_ref") for item in payload["current_regions"]
            if item["current_region_ref"] in current_ids
            and component_relations[item["current_region_ref"]] == "same_complete_component"
        }
        complete_states = {
            occurrence.state_id
            for occurrence in ledger.occurrences.values()
            if occurrence.region_id in current_ids
            and occurrence.variant_id in complete_variants
        }
        ledger = merge_region_identity(
            ledger,
            current_region_ids=current_ids,
            known_region_id=known,
            shared_operations=operation_reuse.get(known, {}),
            shared_operation_levels=operation_levels.get(known, {}),
            shared_result_texts=operation_result_texts.get(known, {}),
            reason="；".join(reasons[known]),
        )
        for state_id in sorted(complete_states):
            coalesce_complete_region_occurrences(ledger, known, state_id)
    for attempt_ref, revealed_region_ids in revealed_by_attempt.items():
        incoming_transition = next(
            item for item in ledger.transitions
            if item.attempt_id == attempt_ref)
        for region_id in revealed_region_ids:
            if region_id not in incoming_transition.revealed_region_ids:
                incoming_transition.revealed_region_ids.append(region_id)
    source_attempts = {
        str(source.get("attempt_ref") or "")
        for source in sources.values() if isinstance(source, dict)
    }
    for transition in ledger.transitions:
        if transition.attempt_id in source_attempts:
            refresh_transition_region_effects(ledger, transition)

    return ledger
