"""Autonomous completion gaps and bounded rejection policy.

This module decides whether ledger-backed exploration work remains and manages
same-page resurvey or repeated framework-rejection suspension. It does not call
Qwen, review a target, execute GUI actions, or introduce another graph writer.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_prompt import (
    _natural_history_result,
    _rejection_feedback,
)
from .autonomous_runtime import AutonomousTraversalRuntime
from .autonomous_scheduling import (
    _task_dependency_status,
    _verified_page_route_hint,
)
from .autonomous_turn import (
    AutonomousDecision,
    ExplorationTask,
    ObservedScene,
    _exploration_task_key,
    _page_key,
)


_TERMINAL_ENTRY_STATUSES = {
    "verified", "inferred", "recorded", "invalidated",
}


TASK_REJECTION_LIMIT = 5
RUN_REJECTION_LIMIT = 10


def _region_exploration_status(
    host: AutonomousTraversalRuntime,
    page_name: str,
    region_name: str,
) -> str:
    """Derive closure of one Region from its survey and owned Entry tasks."""
    state = host.region_states.get(_page_key(page_name))
    region = state.region(region_name) if state is not None else None
    audit = (host.entry_review_audits.get(_page_key(page_name)) or {}).get(
        _page_key(region_name)) or {}
    if (
        region is None
        or not region.get("coverage_complete")
        or audit.get("status") != "complete"
    ):
        return "waiting_survey"
    children = [
        entry for entry in host.entry_ledger.entries
        if entry.discovery_source != "direct_action_backfill"
        and _page_key(entry.page_name) == _page_key(page_name)
        and _page_key(entry.region_name) == _page_key(region_name)
    ]
    if any(
        entry.task_eligible
        and entry.status.value not in _TERMINAL_ENTRY_STATUSES
        for entry in children
    ):
        return "open"
    if any(entry.status.value not in _TERMINAL_ENTRY_STATUSES
           for entry in children):
        return "partial"
    return "complete"


def _request_same_page_resurvey(
    host: AutonomousTraversalRuntime,
    history: List[Dict[str, Any]],
    *,
    page_name: str,
    entry_id: str,
    target: str,
    reason: str,
    region_name: str = "",
    region_ref: str = "",
    occurrence_ref: str = "",
) -> None:
    """Request one delta survey after an entry reveals content on the same Page."""
    page_key = _page_key(page_name)
    if not page_key or page_key in host.pending_page_resurveys:
        return
    record = {
        "page_name": page_name,
        "entry_id": entry_id,
        "target": target,
        "reason": reason,
        "region_name": str(region_name or "").strip(),
        "region_ref": str(region_ref or "").strip(),
        "occurrence_ref": str(occurrence_ref or "").strip(),
    }
    host.pending_page_resurveys[page_key] = record
    if region_name:
        state = host.region_states.get(page_key)
        if state is not None and state.region(region_name) is not None:
            state.set_coverage_complete(region_name, False)
    history.append({
        "kind": "page_resurvey_requested",
        "screen": page_name,
        "entry_id": entry_id,
        "target": target,
        **({"region_name": region_name} if region_name else {}),
        "outcome": "same_page_surface_changed",
        "detail": (
            "The verified entry changed the visible surface without changing "
            "Page identity. Survey only its owning Region when the effect was "
            "localized; otherwise survey the changed Page surface."
        ),
    })


def _completion_gaps(
    host: AutonomousTraversalRuntime,
) -> List[str]:
    gaps: List[str] = []
    gaps.extend(host.scope_state_ledger.completion_gaps())
    reported_prerequisite_roots: set[str] = set()
    for task_key in sorted(host.suspended_task_keys):
        gaps.append(
            f"{task_key}: task is blocked after repeated framework rejections")
    for task_key, dependency in sorted(host.task_dependencies.items()):
        if not isinstance(dependency, dict):
            continue
        status = _task_dependency_status(host, task_key)
        if status == "blocked":
            prerequisite_target = str(
                dependency.get("prerequisite_target") or "前置入口")
            prerequisite_entry_id = str(
                dependency.get("prerequisite_entry_id") or "")
            root_key = prerequisite_entry_id or prerequisite_target
            if root_key not in reported_prerequisite_roots:
                reported_prerequisite_roots.add(root_key)
                result = str(dependency.get("prerequisite_result") or "")
                gaps.append(
                    f"prerequisite root “{prerequisite_target}” failed or was skipped"
                    + (f": {result}" if result else ""))
            gaps.append(
                f"{task_key}: affected by prerequisite root “{prerequisite_target}”; "
                "dependent task cannot run")
        elif status == "deferred":
            gaps.append(
                f"{task_key}: awaits prerequisite “{dependency.get('prerequisite_target')}”")
    if host.pending_page_identity is not None:
        gaps.append("Page Identity proposal still awaits review")
    if host.pending_landing_page is not None:
        gaps.append(
            f"{host.pending_landing_page.page_name}: Variant identity remains "
            "unresolved"
        )
    if host.pending_entry_review is not None:
        gaps.append("Page entry coverage still awaits independent review")
    for page_key, corrections in host.page_update_corrections.items():
        if corrections:
            gaps.append(
                f"{page_key}: {len(corrections)} page-update correction(s) remain")
    for resurvey in host.pending_page_resurveys.values():
        gaps.append(
            f"{resurvey.get('page_name')}: newly revealed functional surface "
            "still needs one page survey")
    for page_name in host.protocol_map.pages:
        page_key = _page_key(page_name)
        state = host.region_states.get(page_key)
        if (
            (state is None or not state.snapshot().get("regions"))
            and not host.empty_region_surveys.get(page_key)
        ):
            gaps.append(f"{page_name}: page survey has no Regions")
    for page_key, state in host.region_states.items():
        snapshot = state.snapshot()
        audits = host.entry_review_audits.get(page_key) or {}
        for region in snapshot.get("regions") or []:
            audit = audits.get(_page_key(region.get("name"))) or {}
            if audit.get("reason_consistent") is False:
                gaps.append(
                    f"{page_key}: Region {region.get('name')} entry review "
                    "disagrees with the main survey reason")
            if not region.get("coverage_complete"):
                gaps.append(
                    f"{page_key}: Region {region.get('name')} has coverage_complete=false")
                continue
            if audit.get("status") != "complete":
                gaps.append(
                    f"{page_key}: Region {region.get('name')} has no accepted "
                    "entry-coverage audit")
    for page_key, state in host.region_states.items():
        for region in state.snapshot().get("regions") or []:
            region_name = str(region.get("name") or "").strip()
            status = _region_exploration_status(host, page_key, region_name)
            if status == "partial":
                gaps.append(
                    f"{page_key}: Region {region_name} exploration is partial; "
                    "at least one owned Entry ended without a verified result")
    for edge in host.graph.action_edges:
        for attempt in edge.get("attempts") or []:
            if attempt.get("outcome") == "assessment_unavailable":
                gaps.append(
                    "an executed GUI action remains unverified because its "
                    "post-action assessment was unavailable")
    for entry in host.entry_ledger.entries:
        owner_state = host.region_states.get(_page_key(entry.page_name))
        owner_region = (
            owner_state.region(entry.region_name)
            if owner_state is not None else None
        )
        owner_ref = host.region_registry.region_ref(
            entry.page_name, entry.region_name)
        if entry.discovery_source == "direct_action_backfill":
            gaps.append(
                f"{entry.page_name}: entry {entry.entry_id} is unreviewed "
                "direct-action evidence, not a formal Entry")
        if (
            owner_region is None
            or not owner_ref
            or owner_ref != str(owner_region.get("region_ref") or "")
        ):
            gaps.append(
                f"{entry.page_name}: entry {entry.entry_id} has no committed "
                f"owner Region {entry.region_name}")
        if entry.representative_entry_id:
            try:
                representative_id = host.entry_ledger.canonical_entry_id(
                    entry.representative_entry_id)
                representative = host.entry_ledger.get(representative_id)
                representative_ref = host.region_registry.region_ref(
                    representative.page_name, representative.region_name)
            except (KeyError, ValueError):
                representative_ref = ""
            if not owner_ref or owner_ref != representative_ref:
                gaps.append(
                    f"{entry.page_name}: entry {entry.entry_id} reuses "
                    "evidence across different Region identities")
        if (
            entry.task_eligible
            and entry.status.value not in _TERMINAL_ENTRY_STATUSES
        ):
            entry_state = (
                _natural_history_result(entry.status.value)
                or "仍未得到可靠验证")
            gaps.append(
                f"{entry.page_name}: 操作 {entry.operation or entry.target} "
                f"（对象：{entry.subject or entry.region_name}；"
                f"代表目标：{entry.target}） {entry_state}")
            if (
                _page_key(entry.page_name)
                != _page_key(host.protocol_map.current_page)
                and not _verified_page_route_hint(host, entry.page_name)
            ):
                gaps.append(
                    f"{entry.page_name}: 操作 {entry.operation or entry.target} "
                    f"（对象：{entry.subject or entry.region_name}；"
                    f"代表目标：{entry.target}）没有从当前页面状态"
                    "出发的已验证图路线")
    for state in host.temporary_states.values():
        if state.get("status") != "restored":
            gaps.append(
                f"{state.get('page_name')}: 旧 checkpoint 记录的临时状态"
                f"“{state.get('control')}”仍未恢复（原值“{state.get('before')}”，"
                f"记录值“{state.get('current')}”）；当前严格协议只保留"
                "这条审计证据，不会自动修改界面"
            )
    return list(dict.fromkeys(str(item)[:300] for item in gaps if str(item)))


def _completion_summary(host: AutonomousTraversalRuntime) -> Dict[str, Any]:
    """Project the Page -> Region -> Entry terminal state without Agent judgment."""
    pages = []
    totals = {
        "complete": 0, "recorded": 0, "invalidated": 0,
        "open": 0, "gap": 0,
    }
    for page_name in host.protocol_map.pages:
        state = host.region_states.get(_page_key(page_name))
        regions = []
        for region in (
            state.snapshot().get("regions") or [] if state is not None else []
        ):
            region_name = str(region.get("name") or "")
            children = [
                entry for entry in host.entry_ledger.entries
                if entry.discovery_source != "direct_action_backfill"
                and _page_key(entry.page_name) == _page_key(page_name)
                and _page_key(entry.region_name) == _page_key(region_name)
            ]
            counts = {
                "complete": sum(
                    entry.status.value in {"verified", "inferred"}
                    for entry in children),
                "recorded": sum(
                    entry.status.value == "recorded" for entry in children),
                "invalidated": sum(
                    entry.status.value == "invalidated" for entry in children),
                "open": sum(
                    entry.task_eligible
                    and entry.status.value not in _TERMINAL_ENTRY_STATUSES
                    for entry in children),
                "gap": sum(
                    not entry.task_eligible
                    and entry.status.value not in _TERMINAL_ENTRY_STATUSES
                    for entry in children),
            }
            for key in totals:
                totals[key] += counts[key]
            regions.append({
                "region": region_name,
                "status": _region_exploration_status(
                    host, page_name, region_name),
                "entries": counts,
            })
        pages.append({
            "page": page_name,
            "status": (
                "complete"
                if (
                    (regions and all(
                        item["status"] == "complete" for item in regions))
                    or (
                        not regions
                        and bool(host.empty_region_surveys.get(
                            _page_key(page_name)))
                    )
                )
                else "partial"
            ),
            "regions": regions,
        })
    return {"pages": pages, "entry_totals": totals}


def _finish_rejection_record(
    host: AutonomousTraversalRuntime,
    *,
    screen_name: str,
    gaps: Sequence[str],
) -> Dict[str, Any]:
    return {
        "kind": "finish_gap",
        "screen": screen_name,
        "outcome": "finish_rejected",
        "detail": "framework evidence gaps remain",
        "remaining": list(gaps),
        "rejection": _rejection_feedback(
            "completion_evidence_missing",
            "framework evidence gaps remain",
            retry_after="listed_gaps_resolved_or_proven_unreachable",
            correction=(
                "The supplied evidence did not clear the returned remaining "
                "gaps. Do not resubmit evidence for an entry absent from "
                "remaining. Take a non-finish GUI or page_update ledger step "
                "toward one listed gap."
            ),
        ),
    }


def _apply_finish_proposal(
    host: AutonomousTraversalRuntime,
    scene: ObservedScene,
    decision: AutonomousDecision,
    history: List[Dict[str, Any]],
) -> bool:
    """Validate one FINISH proposal and close the run only without gaps."""
    raw_unreachable = decision.tool_arguments.get("unreachable_evidence") or []
    unreachable_records = [
        dict(item) for item in raw_unreachable if isinstance(item, dict)
    ]
    evidence_issues: List[str] = []
    accepted_unreachable: List[Dict[str, Any]] = []
    entry_dispositions: List[Dict[str, Any]] = []
    active_task = host.exploration_task
    active_task_id = _exploration_task_key(active_task)
    task_attempt_count = sum(
        1 for item in history
        if item.get("kind") == "action"
        and item.get("exploration_task_id") == active_task_id
        and item.get("action") not in {"WAIT", "FINISH"}
        and item.get("outcome") not in {
            "not_executed", "awaiting_observation", "execution_error",
        }
    )
    accepted_entry_ids: set[str] = set()
    for record in unreachable_records:
        entry_id = str(record.get("entry_id") or "").strip()
        page_name = str(record.get("page_name") or "").strip()
        subject = str(record.get("subject") or "").strip()
        evidence = str(record.get("evidence") or "").strip()
        if not all((page_name, entry_id, subject, evidence)):
            evidence_issues.append(
                "unreachable evidence requires non-empty page_name, "
                "entry_id, subject and evidence")
            continue
        if (
            active_task is None
            or active_task.task_type != "explore_entry"
            or entry_id != active_task.entry_id
        ):
            evidence_issues.append(
                "unreachable evidence may retire only the exact active "
                f"explore_entry task, not {entry_id}")
            continue
        if entry_id in accepted_entry_ids:
            evidence_issues.append(
                f"duplicate unreachable evidence for entry: {entry_id}")
            continue
        try:
            entry = host.entry_ledger.get(entry_id)
        except KeyError:
            evidence_issues.append(
                f"unreachable evidence references unknown entry: {entry_id}")
            continue
        evidence_page = host.protocol_map.canonical_page_name(page_name)
        if evidence_page != entry.page_name:
            evidence_issues.append(
                "unreachable evidence page does not own entry "
                f"{entry_id}: expected {entry.page_name}")
            continue
        if (
            entry.status.value in {"verified", "inferred"}
            or not entry.task_eligible
        ):
            evidence_issues.append(
                "unreachable evidence conflicts with covered or retired "
                f"entry: {entry_id}")
            continue
        if task_attempt_count < 2:
            evidence_issues.append(
                f"unreachable evidence for {entry_id} needs at least "
                "two executed GUI attempts in the active task")
            continue
        accepted_entry_ids.add(entry_id)
        accepted_unreachable.append(record)
    evidence_issues.extend(
        host.protocol_map.record_unreachable_evidence(accepted_unreachable))
    for record in accepted_unreachable:
        entry_id = str(record.get("entry_id") or "").strip()
        retired = host.entry_ledger.mark_unreachable(
            entry_id, evidence=str(record.get("evidence") or ""))
        entry_dispositions.append({
            "entry_id": retired.entry_id,
            "status": retired.status.value,
            "task_eligible": retired.task_eligible,
            "reason": retired.last_result,
        })
    if unreachable_records or evidence_issues:
        history.append({
            "kind": "unreachable_evidence",
            "screen": scene.page_name,
            "records": unreachable_records,
            "accepted_records": accepted_unreachable,
            "issues": evidence_issues,
            "entry_dispositions": entry_dispositions,
        })
    gaps = list(dict.fromkeys(_completion_gaps(host) + evidence_issues))
    if gaps:
        history.append(_finish_rejection_record(
            host, screen_name=scene.page_name, gaps=gaps))
        return False
    history.append({
        "kind": "action",
        "screen": scene.page_name,
        "action": "FINISH",
        "target": decision.target,
        "outcome": "model_finished",
        "detail": decision.reason,
    })
    host.graph.stop_reason = "model_finished"
    return True


def _rejection_progress_token(host: AutonomousTraversalRuntime) -> str:
    """Serialize stable facts; attempts and changing descriptions are not progress."""
    regions = {}
    for page_key, state in sorted(host.region_states.items()):
        snapshot = state.snapshot()
        regions[page_key] = {
            "regions": sorted((
                _page_key(region.get("name")),
                bool(region.get("coverage_complete")),
                str(region.get("region_ref") or ""),
            ) for region in snapshot.get("regions") or []),
        }
    entries = []
    for entry in host.entry_ledger.entries:
        status = entry.status.value
        if entry.task_eligible and status in {
                "discovered", "attempted", "unresolved"}:
            status = "pending"
        entries.append((
            entry.entry_id,
            status,
            entry.representative_entry_id,
            entry.destination_page if status in {"verified", "inferred"} else "",
            bool(entry.task_eligible),
        ))
    payload = {
        "pages": sorted(host.protocol_map.pages),
        "connections": sorted((
            str(edge.get("from") or ""), str(edge.get("via") or ""),
            str(edge.get("action") or ""), str(edge.get("to") or ""),
            str(edge.get("provenance") or ""),
            str(edge.get("entry_id") or ""),
            str(edge.get("equivalent_to_entry_id") or ""),
        ) for edge in host.protocol_map.connections),
        "regions": regions,
        "entries": sorted(entries),
        "temporary_states": {
            key: {
                field: value.get(field) for field in (
                    "status", "before", "current",
                )
            }
            for key, value in sorted(host.temporary_states.items())
        },
        "page_update_corrections": {
            page_key: sorted(items)
            for page_key, items in sorted(
                host.page_update_corrections.items())
        },
        "pending_page_resurveys": deepcopy(host.pending_page_resurveys),
        "empty_region_surveys": {
            page_key: sorted(state_ids)
            for page_key, state_ids in sorted(
                host.empty_region_surveys.items())
            if state_ids
        },
        "pending_entry_review": deepcopy(host.pending_entry_review),
        "entry_review_audits": deepcopy(host.entry_review_audits),
        "region_probe_progress": {
            region_ref: {
                "status": str(value.get("status") or ""),
                "covered_operations": sorted({
                    str(item) for item in value.get("covered_operations") or []
                    if str(item)
                }),
            }
            for region_ref, value in sorted(host.region_probe_progress.items())
        },
        "task_dependencies": deepcopy(host.task_dependencies),
    }
    if isinstance(payload["pending_entry_review"], dict):
        payload["pending_entry_review"].pop("previous_rejection", None)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _record_is_framework_rejection(record: Dict[str, Any]) -> bool:
    rejection = record.get("rejection")
    if isinstance(rejection, dict) and rejection.get("status") == "rejected":
        return True
    if (record.get("kind") == "page_update_result"
            and record.get("status") == "rejected"):
        return True
    if record.get("kind") != "tool":
        return False
    result = record.get("tool_result")
    status = result.get("status") if isinstance(result, dict) else ""
    return status in {
        "rejected",
        "current_page_not_registered", "current_page_mismatch",
        "invalid_arguments", "no_route", "not_found", "unknown_tool",
    }


def _bind_history_records_to_task(
    records: Sequence[Dict[str, Any]],
    task: Optional[ExplorationTask],
) -> None:
    """Bind one turn's trace records without exposing the task ID to the model."""
    if task is None or not task.task_id:
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        record.setdefault("exploration_task_id", task.task_id)
        if task.page_name:
            record.setdefault("exploration_task_page", task.page_name)
        if task.phase:
            record.setdefault("exploration_task_phase", task.phase)


def _update_rejection_boundary(
    host: AutonomousTraversalRuntime,
    history: List[Dict[str, Any]],
    turn_records: Sequence[Dict[str, Any]],
    *,
    progress_made: bool,
    pending_action: bool = False,
) -> bool:
    """Apply one shared 5-per-task / 10-per-run rejection boundary."""
    rejected = any(_record_is_framework_rejection(item) for item in turn_records)
    if progress_made:
        host.task_rejection_streak = 0
        host.run_rejection_streak = 0
        host.rejection_task_key = ""
        return False
    if not rejected:
        return False

    task_key = _exploration_task_key(host.exploration_task) or "unassigned"
    if host.rejection_task_key != task_key:
        host.task_rejection_streak = 0
        host.rejection_task_key = task_key
    host.task_rejection_streak += 1
    host.run_rejection_streak += 1
    counts = {
        "task": host.task_rejection_streak,
        "task_limit": TASK_REJECTION_LIMIT,
        "run": host.run_rejection_streak,
        "run_limit": RUN_REJECTION_LIMIT,
    }
    for record in reversed(turn_records):
        if _record_is_framework_rejection(record):
            record["rejection_streak"] = dict(counts)
            break

    if host.run_rejection_streak >= RUN_REJECTION_LIMIT:
        history.append({
            "kind": "traversal_stopped",
            "outcome": "framework_rejection_limit",
            "detail": (
                f"{RUN_REJECTION_LIMIT} consecutive Agent turns were rejected "
                "without an accepted stable Page/Region/Entry fact"
            ),
            "rejection_streak": counts,
        })
        host.graph.stop_reason = "framework_rejection_limit"
        return True

    if host.task_rejection_streak >= TASK_REJECTION_LIMIT:
        if pending_action:
            history.append({
                "kind": "traversal_stopped",
                "outcome": "pending_action_assessment_limit",
                "detail": (
                    "The current task has an executed GUI action, but "
                    f"{TASK_REJECTION_LIMIT} consecutive Agent turns did not "
                    "produce an accepted stable assessment."
                ),
                "rejection_streak": counts,
            })
            host.graph.stop_reason = "pending_action_assessment_limit"
            return True
        if task_key != "unassigned":
            host.suspended_task_keys.add(task_key)
        history.append({
            "kind": "task_suspended",
            "outcome": "framework_rejection_limit",
            "task": (
                asdict(host.exploration_task)
                if host.exploration_task is not None else None
            ),
            "detail": (
                f"current task was suspended after {TASK_REJECTION_LIMIT} "
                "consecutive rejected turns without progress"
            ),
            "rejection_streak": counts,
        })
        host.exploration_task = None
        host.task_rejection_streak = 0
        if task_key != "unassigned":
            host.run_rejection_streak = 0
        host.rejection_task_key = ""
    return False
