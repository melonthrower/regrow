"""Entry-review discussion state and non-committing dispute tools."""

from __future__ import annotations

from copy import deepcopy
import os
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_context import _entry_equivalence_candidates
from .autonomous_page_update import (
    _page_update_item_key,
    _update_page_corrections,
)
from .autonomous_protocol import ToolEvidence
from .autonomous_region_tools import screenshot_frame_id
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _record_agent_inferred_edges,
)
from .autonomous_turn import PageUpdate, _page_key, _parse_entry_review


def _entry_review_key(item: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        _page_key(item.get("region_name")),
        _page_key(item.get("operation") or item.get("target")),
        _page_key(item.get("target")),
    )


def _current_entry_review_record(
    history: Sequence[Dict[str, Any]],
    *,
    page_name: str,
    frame_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the latest same-frame review with unresolved deferred entries."""
    review_index = -1
    review: Optional[Dict[str, Any]] = None
    for index in range(len(history) - 1, -1, -1):
        record = history[index]
        if (
            record.get("kind") == "entry_review_result"
            and record.get("status") == "accepted"
            and _page_key(record.get("screen")) == _page_key(page_name)
            and str(record.get("frame_id") or "") == str(frame_id or "")
            and record.get("deferred")
        ):
            review_index = index
            review = record
            break
    if review is None:
        return None
    resolved_keys = set()
    for record in history[review_index + 1:]:
        if (
            record.get("kind") != "tool"
            or record.get("tool_name") != "review_entry_record"
        ):
            continue
        result = record.get("tool_result")
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            continue
        if (
            str(data.get("review_frame_id") or "") != str(frame_id or "")
            or _page_key(data.get("page_name")) != _page_key(page_name)
        ):
            continue
        resolved_keys.update(
            _entry_review_key(item)
            for item in data.get("dropped_deferred_entries") or []
            if isinstance(item, dict)
        )
    pending = [
        deepcopy(item) for item in review.get("deferred") or []
        if isinstance(item, dict)
        and _entry_review_key(item) not in resolved_keys
    ]
    if not pending:
        return None
    current = deepcopy(review)
    current["deferred"] = pending
    return current


def _review_entry_record(
    host: AutonomousTraversalRuntime,
    arguments: Dict[str, Any],
    screenshot: bytes,
    history: Sequence[Dict[str, Any]],
) -> ToolEvidence:
    page_name = host.protocol_map.current_page
    frame_id = screenshot_frame_id(screenshot)
    review = _current_entry_review_record(
        history, page_name=page_name, frame_id=frame_id)
    if review is None:
        return ToolEvidence("unavailable", {
            "feedback": (
                "当前 Page 和截图没有可检查或纠正的 Entry Reviewer 临时延期记录；"
                "正式入口和图账本未修改。"
            ),
        })
    operation = str(arguments.get("operation") or "").strip().casefold()
    reason = str(arguments.get("reason") or "").strip()
    requested = arguments.get("drop_deferred_entries")
    if operation not in {"inspect", "correct"} or not reason:
        return ToolEvidence("invalid_arguments", {
            "feedback": "operation 必须为 inspect/correct，且 reason 不能为空。",
        })
    if not isinstance(requested, list) or not all(
            isinstance(item, dict) for item in requested):
        return ToolEvidence("invalid_arguments", {
            "feedback": "drop_deferred_entries 必须是精确 Region/operation/target 的数组。",
        })
    normalized_requested = []
    for item in requested:
        region_name = str(item.get("region_name") or "").strip()
        entry_operation = str(
            item.get("entry_operation") or item.get("target") or "").strip()
        target = str(item.get("target") or "").strip()
        if not region_name or not entry_operation or not target:
            return ToolEvidence("invalid_arguments", {
                "feedback": (
                    "每个待丢弃项都必须提供非空 region_name、"
                    "entry_operation 和 target。"),
            })
        normalized_requested.append({
            "region_name": region_name,
            "operation": entry_operation,
            "target": target,
        })
    if operation == "inspect" and normalized_requested:
        return ToolEvidence("invalid_arguments", {
            "feedback": "inspect 不修改记录，drop_deferred_entries 必须为空。",
        })
    if operation == "correct" and not normalized_requested:
        return ToolEvidence("invalid_arguments", {
            "feedback": "correct 至少需要一个精确的 deferred entry。",
        })
    pending_by_key = {
        _entry_review_key(item): deepcopy(item)
        for item in review.get("deferred") or []
        if isinstance(item, dict)
    }
    requested_keys = [_entry_review_key(item) for item in normalized_requested]
    if len(set(requested_keys)) != len(requested_keys):
        return ToolEvidence("invalid_arguments", {
            "feedback": "drop_deferred_entries 不能重复引用同一候选。",
        })
    unknown = [
        item for item, key in zip(normalized_requested, requested_keys)
        if key not in pending_by_key
    ]
    if unknown:
        return ToolEvidence("invalid_arguments", {
            "feedback": (
                "只能纠正当前同截图 Reviewer 记录中的精确 deferred entry；"
                f"以下项不在该记录中：{unknown}"
            ),
        })
    dropped = (
        [pending_by_key[key] for key in requested_keys]
        if operation == "correct" else []
    )
    dropped_keys = set(requested_keys) if operation == "correct" else set()
    remaining = [
        deepcopy(item) for key, item in pending_by_key.items()
        if key not in dropped_keys
    ]
    if operation == "correct":
        explicit_deferred_regions = {
            _page_key(name) for name in review.get("deferred_regions") or []
        }
        page_frames = host.entry_review_deferred_frames.get(
            _page_key(page_name), {})
        affected_region_keys = {
            _page_key(item.get("region_name")) for item in dropped
        }
        remaining_region_keys = {
            _page_key(item.get("region_name")) for item in remaining
        }
        for region_key in affected_region_keys:
            if (
                region_key not in remaining_region_keys
                and region_key not in explicit_deferred_regions
                and page_frames.get(region_key) == frame_id
            ):
                page_frames.pop(region_key, None)
        if not page_frames:
            host.entry_review_deferred_frames.pop(
                _page_key(page_name), None)
        resolved_correction_keys = [
            _page_update_item_key({
                "kind": "new_entry",
                "region_name": item.get("region_name"),
                "target": item.get("target"),
            })
            for item in dropped
        ]
        page_key = _page_key(page_name)
        correction_keys_before = set(
            host.page_update_corrections.get(page_key, {}))
        _update_page_corrections(
            host,
            page_name,
            accepted_keys=(),
            rejected_items=(),
            resolved_keys=[
                key for key in resolved_correction_keys if key
            ],
        )
        correction_keys_after = set(
            host.page_update_corrections.get(page_key, {}))
        cleared_correction_keys = sorted(
            correction_keys_before - correction_keys_after)
    else:
        cleared_correction_keys = []
    def render(items: Sequence[Dict[str, Any]]) -> str:
        return "；".join(
            f"{item.get('region_name')} / {item.get('target')}"
            for item in items
        ) or "无"
    feedback = (
        "已读取最近一次同截图 Entry Reviewer 临时记录。"
        if operation == "inspect" else
        "已从临时 Reviewer 延期记录中丢弃主 Agent 明确纠正的候选；"
        "正式 Entry、Page、Region 和图边均未删除或改写。"
    )
    feedback += (
        f" 已丢弃：{render(dropped)}。仍延期：{render(remaining)}。"
        f" Reviewer 原始理由：{str(review.get('reviewer_reason') or '').strip()}"
    )
    return ToolEvidence(
        "inspected" if operation == "inspect" else "corrected",
        {
            "page_name": page_name,
            "review_frame_id": frame_id,
            "deferred_entries": deepcopy(review.get("deferred") or []),
            "deferred_regions": deepcopy(
                review.get("deferred_regions") or []),
            "reason_consistent": review.get("reason_consistent"),
            "reviewer_reason": str(
                review.get("reviewer_reason") or "").strip(),
            "dropped_deferred_entries": dropped,
            "remaining_deferred_entries": remaining,
            "cleared_page_update_corrections": cleared_correction_keys,
            "formal_graph_unchanged": True,
            "reason": reason,
            "feedback": feedback,
        },
    )


def _entry_review_region_names(
    host: AutonomousTraversalRuntime,
    update: PageUpdate,
) -> List[str]:
    """Return Regions whose entry coverage needs the focused reviewer."""
    page_key = _page_key(update.page_name)
    state = host.region_states.get(page_key)
    existing = {
        _page_key(item.get("name")): item
        for item in (state.snapshot().get("regions") if state else []) or []
        if isinstance(item, dict) and item.get("name")
    }
    audits = host.entry_review_audits.get(page_key) or {}
    formal_entry_keys = {
        (
            _page_key(entry.region_name),
            _page_key(entry.target),
            _page_key(entry.operation or entry.target),
            _page_key(entry.subject or entry.region_name),
            str(entry.control_type or "control").strip().casefold(),
        )
        for entry in host.entry_ledger.entries
        if (
            _page_key(entry.page_name) == page_key
            and entry.discovery_source != "direct_action_backfill"
        )
    }
    candidate_region_keys = {
        _page_key(item.get("region_name"))
        for item in update.new_entries
        if isinstance(item, dict)
        and str(item.get("region_name") or "").strip()
        and str(item.get("target") or "").strip()
        and (
            _page_key(item.get("region_name")),
            _page_key(item.get("target")),
            _page_key(item.get("operation") or item.get("target")),
            _page_key(item.get("subject") or item.get("region_name")),
            str(item.get("control_type") or "control").strip().casefold(),
        ) not in formal_entry_keys
    }
    resurvey = host.pending_page_resurveys.get(page_key) or {}
    resurvey_region_key = _page_key(resurvey.get("region_name"))
    needs_page_resurvey = bool(resurvey) and not resurvey_region_key
    names: List[str] = []
    seen_region_keys: set[str] = set()
    for raw in update.regions:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        region_key = _page_key(name)
        if not name or not region_key:
            continue
        needs_review = region_key in candidate_region_keys
        if raw.get("coverage_complete") is True:
            current = existing.get(region_key) or {}
            prior_audit = audits.get(region_key) or {}
            needs_review = needs_review or needs_page_resurvey or (
                not current
                or current.get("coverage_complete") is not True
                or prior_audit.get("status") != "complete"
            )
            if resurvey_region_key == region_key:
                needs_review = True
        if needs_review and region_key not in seen_region_keys:
            names.append(name[:160])
            seen_region_keys.add(region_key)
    return names


def _review_registered_entry_dispute(
    host: AutonomousTraversalRuntime,
    arguments: Dict[str, Any],
    screenshot: bytes,
    screen_name: str,
) -> Dict[str, Any]:
    """Re-review only the exact dispatched Entry; preserve its evidence."""

    def result(
        verdict: str,
        feedback: str,
        *,
        ledger_changed: bool = False,
        reviewer_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "verdict": verdict,
            "ledger_changed": ledger_changed,
            "feedback": feedback,
        }
        if reviewer_output is not None:
            payload["reviewer_output"] = reviewer_output
        return payload

    task = host.exploration_task
    entry_id = str(arguments.get("subject") or "").strip()
    observed_problem = str(
        arguments.get("observed_problem") or "").strip()
    problem_type = str(
        arguments.get("problem_type") or "semantic_mismatch"
    ).strip().casefold()
    if task is None or task.task_type != "explore_entry" or not task.entry_id:
        return result(
            "not_reviewed",
            "Entry dispute was recorded, but no exact explore_entry task is "
            "active; the ledger is unchanged.",
        )
    if entry_id != task.entry_id:
        return result(
            "not_reviewed",
            f"Entry dispute was recorded, but the active task is "
            f"{task.entry_id}, not {entry_id or '<empty>'}; the ledger is "
            "unchanged.",
        )
    try:
        entry = host.entry_ledger.get(entry_id)
    except KeyError as exc:
        return result("not_reviewed", f"{str(exc)}; the ledger is unchanged.")
    if not entry.task_eligible or entry.status.value in {"verified", "inferred"}:
        return result(
            "not_reviewed",
            "The exact Entry is already covered or retired; the ledger is "
            "unchanged.",
        )
    current_page = host.protocol_map.current_page or str(screen_name or "")
    if _page_key(current_page) != _page_key(entry.page_name):
        return result(
            "not_reviewed",
            f"Entry {entry_id} belongs to {entry.page_name!r}, but the current "
            f"Page is {current_page!r}. Reach the source Page before asking "
            "for a visual Entry re-review.",
        )
    if not observed_problem:
        return result(
            "not_reviewed",
            "Entry dispute needs a concrete visual and functional reason; "
            "the ledger is unchanged.",
        )

    state = host.region_states.get(_page_key(entry.page_name))
    snapshot = state.snapshot() if state is not None else {}
    formal_region = next((
        item for item in snapshot.get("regions") or []
        if isinstance(item, dict)
        and _page_key(item.get("name")) == _page_key(entry.region_name)
    ), None)
    registry_ref = host.region_registry.region_ref(
        entry.page_name, entry.region_name)
    if (
        not isinstance(formal_region, dict)
        or not registry_ref
        or registry_ref != str(formal_region.get("region_ref") or "")
    ):
        return result(
            "not_reviewed",
            "The Entry's owning Region is not bound to the committed formal "
            "partition, so the dispute cannot change scheduling.",
        )
    review_region = deepcopy(formal_region)
    bbox_record = (snapshot.get("current_bboxes") or {}).get(
        _page_key(entry.region_name))
    if isinstance(bbox_record, dict) and bbox_record.get("bbox_1000"):
        review_region["bbox_1000"] = deepcopy(bbox_record["bbox_1000"])

    if problem_type == "target_not_found":
        current_state_id = str(
            getattr(state, "current_state_id", "") or "").strip()
        source_state_ids = {
            str(state_id or "").strip()
            for state_id in [entry.source_state_id, *entry.source_state_ids]
            if str(state_id or "").strip()
        }
        if not current_state_id or current_state_id not in source_state_ids:
            return result(
                "not_reviewed",
                "The target-not-found claim was recorded, but the current "
                "State is not one of this Entry's accepted source States. "
                "Restore an accepted source State before comparing visual "
                "presence.",
            )
        discovery_path = str(
            entry.discovery_screenshot_path or "").strip()
        if discovery_path and not os.path.isabs(discovery_path):
            discovery_path = os.path.join(host.output_root, discovery_path)
        if not discovery_path or not os.path.isfile(discovery_path):
            return result(
                "not_reviewed",
                "This Entry predates fixed discovery-frame evidence, so the "
                "framework cannot safely decide whether it was hallucinated. "
                "The original Entry remains unchanged.",
            )
        presence_reviewer = host.entry_presence_reviewer
        if not callable(presence_reviewer):
            return result(
                "not_reviewed",
                "The independent two-frame Entry reviewer is unavailable; "
                "the original Entry remains unchanged.",
            )
        try:
            with open(discovery_path, "rb") as stream:
                discovery_screenshot = stream.read()
            reviewer_output = presence_reviewer({
                "discovery_screenshot": discovery_screenshot,
                "current_screenshot": screenshot,
                "entry": {
                    "entry_id": entry.entry_id,
                    "region_name": entry.region_name,
                    "operation": entry.operation or entry.target,
                    "target": entry.target,
                },
                "owner_region": {
                    "name": review_region.get("name") or entry.region_name,
                    "summary": review_region.get("summary") or "",
                },
                "main_agent_observation": observed_problem,
            })
        except Exception:
            return result(
                "not_reviewed",
                "The independent two-frame Entry reviewer did not return a "
                "usable judgment; the original Entry remains unchanged.",
            )
        if not isinstance(reviewer_output, dict):
            return result(
                "not_reviewed",
                "The independent two-frame Entry reviewer returned invalid "
                "output; the original Entry remains unchanged.",
            )
        discovery_presence = str(
            reviewer_output.get("discovery_presence") or "").strip()
        current_presence = str(
            reviewer_output.get("current_presence") or "").strip()
        reviewer_reason = str(
            reviewer_output.get("reason") or "").strip()
        if (
            discovery_presence not in {
                "supported", "unsupported", "uncertain",
            }
            or current_presence not in {"present", "missing", "uncertain"}
            or not reviewer_reason
        ):
            return result(
                "not_reviewed",
                "The independent two-frame Entry reviewer returned invalid "
                "fields; the original Entry remains unchanged.",
                reviewer_output=deepcopy(reviewer_output),
            )
        if (
            discovery_presence == "unsupported"
            and current_presence == "missing"
        ):
            host.entry_ledger.mark_invalidated(
                entry.entry_id,
                reason=(
                    "The accepted discovery frame did not visually support "
                    "the registered target, and the exact source State still "
                    f"does not show it. Reviewer reason: {reviewer_reason}"
                ),
            )
            return result(
                "invalidated_hallucination",
                "The exact Entry was retired as a hallucinated discovery: "
                "the main Agent failed to locate it in an accepted source "
                "State, and the independent two-frame review found no support "
                f"in either screenshot. Reviewer reason: {reviewer_reason}",
                ledger_changed=True,
                reviewer_output=deepcopy(reviewer_output),
            )
        if current_presence == "present":
            verdict = "localization_retry"
            feedback = (
                "The target remains visible in the current source State. "
                "Keep the Entry and retry localization once using the current "
                f"visual evidence. Reviewer reason: {reviewer_reason}"
            )
        elif discovery_presence == "supported":
            verdict = "state_changed"
            feedback = (
                "The discovery screenshot supports the Entry, but the current "
                "source-State screenshot does not show it. Keep the Entry and "
                "restore the relevant local UI condition or defer the task. "
                f"Reviewer reason: {reviewer_reason}"
            )
        else:
            verdict = "presence_uncertain"
            feedback = (
                "The two screenshots do not support safe invalidation. Keep "
                "the Entry as unresolved evidence and move on after recording "
                f"the gap. Reviewer reason: {reviewer_reason}"
            )
        return result(
            verdict,
            feedback,
            reviewer_output=deepcopy(reviewer_output),
        )

    reviewer = host.entry_reviewer
    if not callable(reviewer):
        return result(
            "not_reviewed",
            "The independent Entry Reviewer is unavailable; the dispute was "
            "recorded and the ledger is unchanged.",
        )
    candidate = {
        "region_name": entry.region_name,
        "target": entry.target,
        "operation": entry.operation or entry.target,
        "subject": entry.subject or entry.region_name,
    }
    request = {
        "current_screenshot": screenshot,
        "page_name": entry.page_name,
        "main_agent_reason": observed_problem,
        "regions": [review_region],
        "candidates": [candidate],
        "entry_dispute": {
            "entry_id": entry.entry_id,
            "page_name": entry.page_name,
            "region_name": entry.region_name,
            "target": entry.target,
            "operation": entry.operation or entry.target,
            "subject": entry.subject or entry.region_name,
            "observed_problem": observed_problem,
        },
        "known_entries": [
            {
                "entry_id": known.entry_id,
                "region_name": known.region_name,
                "target": known.target,
                "operation": known.operation or known.target,
                "subject": known.subject or known.region_name,
            }
            for known in host.entry_ledger.entries
            if _page_key(known.page_name) == _page_key(entry.page_name)
        ],
        "coverage_audit_regions": [],
        "previous_rejection": {},
    }
    try:
        raw_output = reviewer(request)
    except Exception as exc:
        return result(
            "not_reviewed",
            "独立 Entry Reviewer 本轮没有返回可用判断；争议已记录，但原有 "
            "Entry 及其证据均未改变。",
        )
    review_payload = ({
        "independent_entries": raw_output.get("independent_entries"),
        "record_only_entries": raw_output.get("record_only_entries", []),
        "deferred_entries": raw_output.get("deferred_entries"),
        "deferred_regions": raw_output.get("deferred_regions"),
    } if isinstance(raw_output, dict) else raw_output)
    if isinstance(raw_output, dict) and "non_task_entries" in raw_output:
        review_payload["non_task_entries"] = raw_output.get(
            "non_task_entries")
    review, parse_issue = _parse_entry_review(review_payload)
    reviewer_output = deepcopy(raw_output) if isinstance(raw_output, dict) else {
        "raw": str(raw_output)[:800],
    }
    if parse_issue or review is None:
        return result(
            "not_reviewed",
            "The independent Entry Reviewer returned invalid output; the "
            f"ledger is unchanged: {parse_issue or 'entry review missing'}",
            reviewer_output=reviewer_output,
        )

    exact_key = _entry_review_key(candidate)
    independent_keys = {
        _entry_review_key(item) for item in review.independent_entries
    }
    record_only_keys = {
        _entry_review_key(item) for item in review.record_only_entries
    }
    deferred_keys = {
        _entry_review_key(item) for item in review.deferred_entries
    }
    non_task_keys = {
        _entry_review_key(item) for item in (review.non_task_entries or [])
    }
    unexpected_keys = sorted(
        (independent_keys | record_only_keys | deferred_keys | non_task_keys)
        - {exact_key})
    if unexpected_keys:
        return result(
            "not_reviewed",
            "Exact Entry dispute review cannot classify other Entries; "
            "the ledger is unchanged.",
            reviewer_output=reviewer_output,
        )
    classifications = sum(
        exact_key in keys
        for keys in (
            independent_keys, record_only_keys, deferred_keys, non_task_keys,
        )
    )
    if classifications > 1:
        return result(
            "not_reviewed",
            "The reviewer classified the exact Entry more than once; the "
            "ledger is unchanged.",
            reviewer_output=reviewer_output,
        )
    if review.non_task_entries is not None and classifications == 0:
        return result(
            "not_reviewed",
            "The reviewer did not classify the exact Entry; the ledger is "
            "unchanged.",
            reviewer_output=reviewer_output,
        )
    unknown_deferred_regions = [
        name for name in review.deferred_regions
        if _page_key(name) != _page_key(entry.region_name)
    ]
    if unknown_deferred_regions:
        return result(
            "not_reviewed",
            "Exact Entry dispute review deferred an unrelated Region; the "
            "ledger is unchanged.",
            reviewer_output=reviewer_output,
        )
    if raw_output.get("reason_consistent") is not True:
        return result(
            "retained_entry",
            "The independent reviewer did not confirm the main Agent's "
            "non-entry reason; the original Entry remains scheduled.",
            reviewer_output=reviewer_output,
        )
    reviewer_reason = str(raw_output.get("reason") or "").strip()
    if exact_key in independent_keys:
        return result(
            "retained_entry",
            "The independent reviewer retained the exact candidate as a "
            "function entry; the original Entry remains scheduled. "
            f"Reviewer reason: {reviewer_reason}",
            reviewer_output=reviewer_output,
        )
    if exact_key in record_only_keys:
        return result(
            "needs_reconciliation",
            "The reviewer considered the exact candidate command-relevant "
            "but not worth another traversal task. One dispute review cannot "
            "retire an existing formal Entry; reconcile it through the "
            "ordinary page Entry review. Reviewer reason: "
            f"{reviewer_reason}",
            reviewer_output=reviewer_output,
        )
    if (
        exact_key in deferred_keys
        or any(
            _page_key(name) == _page_key(entry.region_name)
            for name in review.deferred_regions
        )
    ):
        return result(
            "deferred",
            "The independent reviewer could not classify the exact Entry "
            "from this screenshot; the original Entry remains scheduled. "
            f"Reviewer reason: {reviewer_reason}",
            reviewer_output=reviewer_output,
        )
    return result(
        "needs_reconciliation",
        "The reviewer considered the exact candidate an internal control, but "
        "one omitted candidate is not enough to retire a formal Entry. The "
        "original Entry and all of its evidence remain unchanged and scheduled. "
        "Resolve the disagreement through the ordinary page Entry review or "
        "obtain new GUI evidence before changing the ledger. Reviewer reason: "
        f"{reviewer_reason}",
        reviewer_output=reviewer_output,
    )
def _reuse_entry_result(
    host: AutonomousTraversalRuntime,
    arguments: Dict[str, Any],
) -> ToolEvidence:
    """Apply one exact, Agent-authored entry-equivalence proposal."""
    entry_id = str(arguments.get("entry_id") or "").strip()
    representative_id = str(
        arguments.get("representative_entry_id") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    task = host.exploration_task
    if (task is None or task.task_type != "explore_entry"
            or not task.entry_id):
        return ToolEvidence("rejected", {
            "feedback": (
                "No exact explore_entry task is active, so no entry result was "
                "reused. Continue the current task."
            ),
        })
    if entry_id != task.entry_id:
        return ToolEvidence("rejected", {
            "feedback": (
                f"The active task is {task.entry_id}, not {entry_id or '<empty>'}. "
                "Reuse can update only the exact dispatched entry."
            ),
        })
    try:
        current = host.entry_ledger.get(entry_id)
    except KeyError as exc:
        return ToolEvidence("rejected", {"feedback": str(exc)})
    candidate_ids = {
        str(item.get("entry_id") or "")
        for item in _entry_equivalence_candidates(host, current)
    }
    if representative_id not in candidate_ids:
        return ToolEvidence("rejected", {
            "feedback": (
                f"{representative_id or '<empty>'} is not one of the current "
                "shared-Region candidates. Directly explore this entry or cite "
                "one candidate shown in the task."
            ),
        })
    if not reason:
        return ToolEvidence("rejected", {
            "feedback": (
                "No semantic-equivalence reason was supplied. Compare the visible "
                "control and the candidate's recent real results, then explain "
                "why the outcome is stable or explore it directly."
            ),
        })
    try:
        record = host.entry_ledger.declare_equivalence(
            entry_id,
            representative_entry_id=representative_id,
            reason=reason,
        )
    except (KeyError, ValueError) as exc:
        return ToolEvidence("rejected", {
            "feedback": f"Entry result was not reused: {str(exc)[:500]}",
        })
    _record_agent_inferred_edges(host)
    destination = record.destination_page or "the representative result"
    return ToolEvidence("accepted", {
        "feedback": (
            f"The current entry was linked to the cited verified entry because "
            f"the Agent judged its semantics stable. Its inferred destination is "
            f"{destination}. No GUI action was executed."
        ),
    })
