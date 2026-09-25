"""Runtime-ledger projection for Qwen autonomous context."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ...scenario.capability_induction import induce_capability_graph
from .autonomous_prompt import (
    _model_page_correction_text,
    _natural_history_result,
)
from .autonomous_region_tools import AutonomousRegionState
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _current_page_state_id,
)
from .autonomous_turn import (
    PendingAction,
    _page_key,
    _reviewed_pending_target,
)


def _region_state(
    host: AutonomousTraversalRuntime,
    page_name: str,
) -> AutonomousRegionState:
    key = _page_key(page_name) or "__unbound__"
    state = host.region_states.get(key)
    if state is None:
        state = AutonomousRegionState()
        host.region_states[key] = state
    return state


def _arrival_context_view(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction],
    history: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    bound_page = host.protocol_map.current_page
    source_page = pending.source.page_name if pending is not None else bound_page
    context = {
        "source_page": source_page,
        "via_action": (
            str(pending.primitive.get("action_type") or "")
            if pending is not None else ""
        ),
        "via_control": pending.target if pending is not None else "",
        "source_neighbors": [{
            key: edge.get(key) for key in ("from", "via", "to")
        } for edge in host.protocol_map.neighboring_connections(source_page)],
    }
    source_region_state = host.region_states.get(_page_key(source_page))
    if source_region_state is not None:
        source_regions = [{
            "name": region.get("name"),
            **({"summary": str(region.get("summary") or "")[:180]}
               if region.get("summary") else {}),
        } for region in source_region_state.snapshot().get("regions") or []
            if region.get("name")]
        if source_regions:
            context["source_regions"] = source_regions
    if pending is None:
        recent_action = _latest_gui_action_context(history)
        if recent_action:
            context["recent_action"] = recent_action
    return context


def _probe_attempt_count(record: Dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("completed_attempts") or 0))
    except (TypeError, ValueError):
        return 0


def _region_probe_ref(
    host: AutonomousTraversalRuntime, page_name: str, region_name: str,
) -> str:
    state = host.region_states.get(_page_key(page_name))
    region = state.region(region_name) if state is not None else None
    registry_ref = host.region_registry.region_ref(page_name, region_name)
    if (region is None or not registry_ref
            or str(region.get("region_ref") or "") != registry_ref):
        return ""
    return registry_ref


def _region_probe_capability_evidence(
    host: AutonomousTraversalRuntime, region_ref: str,
) -> List[Dict[str, Any]]:
    """Return the canonical capability levels induced for one probe Region."""
    capability_graph = induce_capability_graph(
        host.graph, region_probe_source_ref=region_ref)
    return [
        {
            "name": str(item.get("name") or ""),
            "effect": str(item.get("predicate_description") or ""),
            "verification_level": str(
                item.get("verification_level") or "discovered"),
        }
        for item in capability_graph.get("capabilities") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _identity_stage(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction] = None,
) -> str:
    identity = host.pending_page_identity
    if identity is not None and identity.stage in {"page", "variant"}:
        return identity.stage
    if host.pending_landing_page is not None:
        return "variant"
    if not host.protocol_map.current_page:
        return "page"
    task = host.exploration_task
    if pending is not None or (
        task is not None and task.phase == "identify_page"
    ):
        return "page"
    return ""


def _current_stage_name(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction] = None,
) -> str:
    if host.pending_page_identity is not None:
        if host.pending_page_identity.stage == "page":
            return "review_page_identity"
        if host.pending_page_identity.stage == "variant":
            return "review_variant_identity"
        return "review_identity"
    if host.pending_landing_page is not None:
        return "identify_variant"
    if not host.protocol_map.current_page:
        return "identify_page"
    if pending is not None:
        return "identify_page"
    task = host.exploration_task
    if task is None:
        return "identify_page"
    if task.phase:
        return task.phase
    if task.task_type == "survey_page":
        return "record_regions"
    if task.task_type == "explore_region":
        return "explore_region"
    return "locate_entry"


def _stage_signature(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction] = None,
) -> tuple[str, ...]:
    task = host.exploration_task
    return (
        _current_stage_name(host, pending),
        str(task.task_type if task is not None else ""),
        str(task.task_id if task is not None else ""),
        str(task.page_name if task is not None else ""),
        str(task.region_name if task is not None else ""),
        str(task.entry_id if task is not None else ""),
    )


def _shared_region_entry_candidates(
    host: AutonomousTraversalRuntime,
    page_name: str,
    region_name: str,
    *,
    exclude_entry_id: str = "",
    verified_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return canonical Entries from one committed shared Region."""
    region_ref = host.region_registry.region_ref(page_name, region_name)
    if not region_ref:
        return []
    group = next((
        item for item in host.region_registry.candidates()
        if item.get("region_ref") == region_ref
    ), None)
    if group is None:
        return []
    occurrence_keys = {
        (_page_key(item.get("page_name")), _page_key(item.get("region_name")))
        for item in group.get("occurrences") or []
        if isinstance(item, dict)
    }
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in host.entry_ledger.entries:
        if entry.entry_id == exclude_entry_id:
            continue
        if (_page_key(entry.page_name), _page_key(entry.region_name)) \
                not in occurrence_keys:
            continue
        try:
            representative_id = host.entry_ledger.canonical_entry_id(
                entry.entry_id)
            representative = host.entry_ledger.get(representative_id)
        except (KeyError, ValueError):
            continue
        if (representative.entry_id == exclude_entry_id
                or representative.entry_id in seen
                or representative.discovery_source == "direct_action_backfill"
                or (
                    verified_only
                    and representative.status.value != "verified"
                )):
            continue
        seen.add(representative.entry_id)
        candidate: Dict[str, Any] = {
            "entry_id": representative.entry_id,
            "page": representative.page_name,
            "region": representative.region_name,
            "target": representative.target,
            "operation": representative.operation or representative.target,
            "subject": representative.subject or representative.region_name,
            "control_type": representative.control_type or "control",
            "last_result": _entry_memory_line(representative),
        }
        if representative.destination_page:
            candidate["destination"] = representative.destination_page
        result.append(candidate)
    return result


def _entry_equivalence_candidates(
    host: AutonomousTraversalRuntime,
    current: Any,
) -> List[Dict[str, Any]]:
    """Expose peer outcomes only for the currently dispatched exact entry."""
    return _shared_region_entry_candidates(
        host,
        current.page_name,
        current.region_name,
        exclude_entry_id=current.entry_id,
        verified_only=True,
    )


def _memory_clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + "…"


def _entry_memory_line(entry: Any) -> str:
    latest = (
        entry.recent_results[-1]
        if getattr(entry, "recent_results", None) else {}
    )
    outcome = str(
        latest.get("classification")
        or latest.get("outcome")
        or getattr(getattr(entry, "status", None), "value", "")
        or ""
    ).strip()
    destination = str(
        latest.get("destination_page")
        or getattr(entry, "destination_page", "")
        or ""
    ).strip()
    result = _memory_clip(latest.get("result") or "", 100)
    target = str(getattr(entry, "target", "") or "入口").strip()
    operation = str(
        getattr(entry, "operation", "") or target).strip()
    subject = str(
        getattr(entry, "subject", "")
        or getattr(entry, "region_name", "")
        or "当前对象"
    ).strip()
    parts = [f"{operation}（对象：{subject}；代表目标：{target}）"]
    natural_outcome = _natural_history_result(outcome)
    if natural_outcome:
        parts.append(natural_outcome)
    if destination:
        parts.append(f"到达 {destination}")
    if result:
        parts.append(result)
    return "：".join(parts)


def _page_memory_summary(
    host: AutonomousTraversalRuntime,
    page_name: str,
) -> str:
    """Return a few durable outgoing Page routes."""
    page_key = _page_key(page_name)
    if not page_key:
        return ""
    lines: List[str] = []
    seen: set[tuple[str, str]] = set()
    for edge in host.protocol_map.connections:
        if _page_key(edge.get("from")) != page_key:
            continue
        via = str(edge.get("via") or "").strip()
        target = str(edge.get("to") or "").strip()
        signature = (_page_key(via), _page_key(target))
        if not via or not target or signature in seen:
            continue
        seen.add(signature)
        lines.append(_memory_clip(f"通过“{via}”到“{target}”", 120))
        if len(lines) >= 4:
            break
    return _memory_clip("；".join(lines), 520)


def _page_entry_history(
    host: AutonomousTraversalRuntime,
    page_name: str,
) -> str:
    """Describe every registered Entry on one Page in natural language."""
    page_key = _page_key(page_name)
    if not page_key:
        return ""
    status_labels = {
        "discovered": "已登记、尚未验证",
        "recorded": "已观察并记录、不派发探索",
        "attempted": "正在尝试",
        "verified": "已验证",
        "unresolved": "尚未解决",
        "inferred": "已推断",
    }
    lines: List[str] = []
    for entry in host.entry_ledger.entries:
        if (
            _page_key(entry.page_name) != page_key
            or entry.discovery_source == "direct_action_backfill"
        ):
            continue
        status = str(getattr(entry.status, "value", entry.status) or "")
        line = (
            f"{entry.entry_id} 是 {entry.region_name or '未绑定 Region'} 中的"
            f"“{entry.operation or entry.target}”操作，对象是"
            f"“{entry.subject or entry.region_name}”，代表目标为“{entry.target}”，"
            f"{status_labels.get(status, status or '状态未知')}"
        )
        if entry.representative_entry_id:
            line += f"，等价代表为 {entry.representative_entry_id}"
        if entry.same_operation_source_entry_id:
            line += (
                "，由同质操作 "
                f"{entry.same_operation_source_entry_id} 覆盖"
            )
        if entry.destination_page:
            line += f"，已知结果到达 {entry.destination_page}"
        if entry.last_result:
            line += f"；最近结果：{_memory_clip(entry.last_result, 140)}"
        lines.append(line + "。")
    if not lines:
        return ""
    return (
        f"当前 Page“{page_name}”之前已登记的入口如下：\n"
        + "\n".join(lines)
    )


def _region_memory_summary(
    host: AutonomousTraversalRuntime,
    page_name: str,
    region_name: str,
    *,
    current_entry_id: str = "",
) -> str:
    """Summarize one Region's survey and entry outcomes for task reuse."""
    page_key = _page_key(page_name)
    region_key = _page_key(region_name)
    if not page_key or not region_key:
        return ""
    lines: List[str] = []
    state = host.region_states.get(page_key)
    if state is not None:
        snapshot = state.snapshot()
        region = next((
            item for item in snapshot.get("regions") or []
            if _page_key(item.get("name")) == region_key
        ), None)
        if region is not None:
            lines.append(
                "主要范围已观察" if region.get("coverage_complete")
                else "主要范围仍在观察"
            )
            survey_memory = _memory_clip(region.get("survey_memory") or "", 140)
            if survey_memory:
                lines.append(survey_memory)
    current_canonical = ""
    if current_entry_id:
        try:
            current_canonical = host.entry_ledger.canonical_entry_id(
                current_entry_id)
        except (KeyError, ValueError):
            current_canonical = ""
    ranked: List[tuple[int, int, Any]] = []
    for index, entry in enumerate(host.entry_ledger.entries):
        if (
            _page_key(entry.page_name) != page_key
            or _page_key(entry.region_name) != region_key
            or entry.entry_id == current_entry_id
        ):
            continue
        if not entry.recent_results:
            continue
        try:
            entry_canonical = host.entry_ledger.canonical_entry_id(
                entry.entry_id)
        except (KeyError, ValueError):
            entry_canonical = ""
        latest = entry.recent_results[-1]
        outcome = str(latest.get("outcome") or "").strip().casefold()
        classification = str(
            latest.get("classification") or "").strip().casefold()
        if current_canonical and entry_canonical == current_canonical:
            priority = 0
        elif classification in {
                "not_interactive", "temporarily_unavailable"} or outcome in {
                "no_visible_change", "unresolved", "unsafe", "unreachable"}:
            priority = 1
        else:
            priority = 2
        ranked.append((priority, -index, entry))
    for _priority, _neg_index, entry in sorted(ranked)[:4]:
        lines.append(_memory_clip(_entry_memory_line(entry), 150))
    return _memory_clip("；".join(lines), 760)


def _region_probe_effect_memory(
    host: AutonomousTraversalRuntime, region_ref: str,
) -> List[Dict[str, Any]]:
    """Return compact, actionable effect evidence for one Region."""
    remembered: List[Dict[str, Any]] = []
    for item in _region_probe_capability_evidence(host, region_ref):
        evidence = (
            "This operation type is covered for traversal. Its separate "
            f"evidence level is {item['verification_level']}; do not repeat "
            "the same control solely to upgrade that level."
        )
        remembered.append({
            "name": item["name"],
            "effect": item["effect"],
            "evidence": evidence,
        })
    return remembered[-6:]


def _exploration_map_view(
    host: AutonomousTraversalRuntime,
    pending: Optional[PendingAction],
    current_screenshot: bytes = b"",
) -> Dict[str, Any]:
    """Project only the graph or local ledger needed by the current stage."""
    bound_page = host.protocol_map.current_page
    task = host.exploration_task
    task_type = task.task_type if task is not None else "survey_page"
    phase = _current_stage_name(host, pending)
    # While an action is pending, the bound Page is its source rather than the
    # identity of the latest screenshot. Calling it current_page anchors the
    # model to the before-action frame and can corrupt landing settlement.
    view: Dict[str, Any] = (
        {} if pending is not None else {"current_page": bound_page}
    )
    if (
        pending is None
        and phase not in {"identify_page", "review_page_identity"}
    ):
        view["current_variant"] = host.protocol_map.current_variant
    natural_pages = host.protocol_map.prompt_view()["pages"]
    page_candidates = [{
        key: value for key, value in page.items() if key != "variants"
    } for page in natural_pages]

    if phase in {"identify_page", "review_page_identity", "review_identity"}:
        view["pages"] = page_candidates
        view["connections"] = [{
            key: edge.get(key) for key in ("from", "via", "to")
        } for edge in host.protocol_map.connections]
    if phase in {"identify_variant", "review_variant_identity"}:
        selected = host.pending_landing_page
        if selected is not None:
            view["selected_page"] = {
                "name": selected.page_name,
                "identity": selected.identity,
            }
            selected_page = next((
                page for page in natural_pages
                if _page_key(page.get("name")) == _page_key(
                    selected.page_name)
            ), None)
            view["variant_candidates"] = (
                list(selected_page.get("variants") or [])
                if selected_page is not None and selected.identity == "known"
                else []
            )
    if phase in {
        "identify_page", "identify_variant", "review_page_identity",
        "review_variant_identity", "review_identity", "route_to_page",
        "route_to_source",
    } or pending is not None:
        view["arrival_context"] = _arrival_context_view(host, pending)

    if pending is not None and pending.assessment is None:
        validated = pending.validated_action
        view["pending_action"] = {
            "history_number": pending.history_index + 1,
            "operation": (
                str(validated.operation)
                if validated is not None
                else str(pending.primitive.get("action_type") or "")
            ),
            "target": pending.target,
            "source_page": pending.source.page_name,
        }
        if (
            task is not None
            and task.task_type == "explore_entry"
            and task.entry_id
            and pending.entry_action_id
            and pending.evidence.get("explicit_entry_task") is True
        ):
            source_entry_id = str(
                pending.evidence.get("entry_id") or "").strip()
            try:
                source_entry = host.entry_ledger.get(source_entry_id)
            except KeyError:
                source_entry = None
            same_region_pending_entries = []
            if (
                source_entry is not None
                and source_entry.entry_id == task.entry_id
                and source_entry.owner_region_ref
            ):
                same_region_pending_entries = [
                    {
                        "entry_id": entry.entry_id,
                        "operation": entry.operation or entry.target,
                        "subject": entry.subject or entry.region_name,
                        "target": entry.target,
                    }
                    for entry in host.entry_ledger.entries
                    if (
                        entry.entry_id != source_entry.entry_id
                        and _page_key(entry.page_name)
                        == _page_key(source_entry.page_name)
                        and _page_key(entry.region_name)
                        == _page_key(source_entry.region_name)
                        and entry.owner_region_ref
                        == source_entry.owner_region_ref
                        and _page_key(entry.control_type)
                        == _page_key(source_entry.control_type)
                        and entry.task_eligible
                        and entry.status.value in {"discovered", "unresolved"}
                        and not entry.representative_entry_id
                        and not entry.same_operation_source_entry_id
                        and entry.discovery_source
                        != "direct_action_backfill"
                    )
                ]
            if same_region_pending_entries:
                view["pending_action"][
                    "source_region"] = source_entry.region_name
                view["pending_action"][
                    "same_region_pending_entries"
                ] = same_region_pending_entries
        if validated is not None and getattr(validated, "purpose", ""):
            view["pending_action"]["purpose"] = validated.purpose
        if phase not in {"identify_page", "review_page_identity"}:
            view["pending_action"]["source_variant"] = (
                pending.source.variant_name)
        reviewed_target = _reviewed_pending_target(pending)
        if reviewed_target:
            view["pending_action"]["reviewed_target"] = reviewed_target
        if (
            validated is not None
            and validated.operation == "input_text"
        ):
            view["pending_action"]["text"] = str(
                validated.arguments.get("text") or "")
    if phase in {
        "identify_page", "identify_variant", "review_page_identity",
        "review_variant_identity", "review_identity",
    }:
        identity_task: Dict[str, Any] = {
            "type": task_type,
            "phase": phase,
        }
        if (
            task is not None
            and task.task_type == "explore_entry"
            and task.entry_id
        ):
            try:
                identity_entry = host.entry_ledger.get(task.entry_id)
            except KeyError:
                identity_entry = None
            if identity_entry is not None:
                identity_task.update({
                    "entry_id": identity_entry.entry_id,
                    "page": identity_entry.page_name,
                    "region": identity_entry.region_name,
                    "operation": (
                        identity_entry.operation or identity_entry.target),
                    "subject": (
                        identity_entry.subject or identity_entry.region_name),
                    "target": identity_entry.target,
                })
        if phase.startswith("review_") and task is not None:
            identity_task["resume_phase"] = task.phase
        view["task"] = identity_task
        return view
    if phase == "completion_ready":
        temporary_states = [
            {
                key: state.get(key) for key in (
                    "page_name", "control", "before", "current",
                ) if state.get(key) not in (None, "")
            }
            for state in host.temporary_states.values()
            if state.get("status") == "needs_restore"
        ]
        if temporary_states:
            view["temporary_states"] = temporary_states
    if task_type == "explore_entry" and task is not None and task.entry_id:
        task_view: Dict[str, Any] = {
            "task_id": task.task_id,
            "type": task.task_type,
            "entry_id": task.entry_id,
            "page": task.page_name,
            "region": task.region_name,
            "target": task.target,
            "phase": phase,
        }
        owner_state = host.region_states.get(_page_key(task.page_name))
        owner_region = (
            owner_state.region(task.region_name)
            if owner_state is not None else None
        )
        owner_audit = (
            host.entry_review_audits.get(_page_key(task.page_name)) or {}
        ).get(_page_key(task.region_name)) or {}
        task_view["region_survey"] = (
            "已完成"
            if owner_region is not None
            and owner_region.get("coverage_complete")
            and owner_audit.get("status") == "complete"
            else "未完成"
        )
        dependency = host.task_dependencies.get(task.task_id) or {}
        if dependency.get("status") == "recheck_after_prerequisite":
            task_view["前置重新检查"] = {
                "目标": str(
                    dependency.get("prerequisite_target") or ""),
                "真实结果": str(
                    dependency.get("prerequisite_result") or ""),
                "注意": "按最新截图重新判断当前目标；前置已处理不等于条件已满足。",
            }
        if phase in {
            "review_identity", "review_page_identity",
            "review_variant_identity",
        }:
            task_view["resume_phase"] = task.phase
        if task.route_hint and phase == "route_to_source":
            task_view["route"] = [{
                key: edge.get(key) for key in ("from", "via", "to")
            } for edge in task.route_hint]
        elif (
            phase == "route_to_source"
            and _page_key(task.page_name) == _page_key(bound_page)
        ):
            task_view["route_status"] = (
                "当前页面已经是入口所属页面，但当前状态尚不满足入口定位条件，"
                "且没有已验证的状态转换路线；请根据最新截图寻找一个安全的可见步骤。"
            )
        try:
            entry = host.entry_ledger.get(task.entry_id)
        except KeyError:
            pass
        else:
            task_view["operation"] = entry.operation or entry.target
            task_view["subject"] = entry.subject or entry.region_name
            task_view["target_condition"] = (
                f"使“{entry.operation or entry.target}”（对象："
                f"{entry.subject or entry.region_name}）在“{entry.region_name}”"
                "区域中重新清楚可见并可定位。"
            )
            if entry.control_type == "input":
                task_view["control_type"] = "input"
            page_modes = host.scope_state_ledger.page_mode_context(
                task.page_name)
            if page_modes:
                task_view["page_modes"] = [{
                    "name": record.get("scope_name"),
                    "current": record.get("current_value"),
                    "selected_count": len(
                        record.get("selected_occurrence_refs") or []),
                } for record in page_modes]
            if entry.required_page_modes:
                task_view["required_page_modes"] = dict(
                    entry.required_page_modes)
            if host.scope_state_ledger.app_states:
                task_view["application_states"] = [{
                    "name": record.get("scope_name"),
                    "current": record.get("current_value"),
                } for record in host.scope_state_ledger.app_states.values()]
            if entry.recent_results:
                task_view["last_result"] = _entry_memory_line(entry)
            equivalent_candidates = _entry_equivalence_candidates(host, entry)
            if equivalent_candidates:
                task_view["equivalent_entry_candidates"] = (
                    equivalent_candidates)
        page_memory = _page_memory_summary(host, task.page_name)
        if page_memory:
            task_view["page_memory"] = page_memory
        page_history = _page_entry_history(
            host, bound_page or task.page_name)
        if page_history:
            task_view["page_history"] = page_history
        region_memory = _region_memory_summary(
            host,
            task.page_name,
            task.region_name,
            current_entry_id=task.entry_id,
        )
        if region_memory:
            task_view["region_memory"] = region_memory
        view["task"] = task_view
        return view

    if task is not None:
        task_view = {
            "task_id": task.task_id,
            "type": task.task_type,
            "page": task.page_name,
            "phase": phase,
        }
        if task.reason == "same_page_functional_surface_changed":
            task_view["reason"] = (
                "最近一次操作没有切换到新的 Page，但当前 Page 显露或改变了"
                "一个可独立调查的功能表面；只补充这次新出现的 Region 和入口。")
        elif task.task_type == "explore_region" and task.reason:
            task_view["reason"] = task.reason
        if phase in {
            "review_identity", "review_page_identity",
            "review_variant_identity",
        }:
            task_view["resume_phase"] = task.phase
        if task.region_name:
            task_view["region"] = task.region_name
            task_view["target_condition"] = (
                f"使“{task.region_name}”区域重新完整可见并可调查；"
                "任一真实满足该条件的页面状态均可。"
            )
        page_modes = host.scope_state_ledger.page_mode_context(
            task.page_name)
        if page_modes:
            task_view["page_modes"] = [{
                "name": record.get("scope_name"),
                "current": record.get("current_value"),
                "selected_count": len(
                    record.get("selected_occurrence_refs") or []),
            } for record in page_modes]
        if host.scope_state_ledger.app_states:
            task_view["application_states"] = [{
                "name": record.get("scope_name"),
                "current": record.get("current_value"),
            } for record in host.scope_state_ledger.app_states.values()]
        if task.route_hint and phase == "route_to_page":
            task_view["route"] = [{
                key: edge.get(key)
                for key in ("from", "via", "to", "entry_id")
                if edge.get(key) not in (None, "")
            } for edge in task.route_hint]
        elif (
            phase == "route_to_page"
            and _page_key(task.page_name) == _page_key(bound_page)
        ):
            task_view["route_status"] = (
                "当前页面名称已经符合任务，但目标区域在当前状态下尚不可完整调查，"
                "且没有已验证的状态转换路线；请根据最新截图寻找一个安全的可见步骤。"
            )
        page_memory = _page_memory_summary(host, task.page_name)
        if page_memory:
            task_view["page_memory"] = page_memory
        if task.region_name:
            region_memory = _region_memory_summary(
                host, task.page_name, task.region_name)
            if region_memory:
                task_view["region_memory"] = region_memory
        if task.task_type == "explore_region":
            region_ref = _region_probe_ref(
                host, task.page_name, task.region_name)
            progress = host.region_probe_progress.get(region_ref) or {}
            known_capabilities = _region_probe_effect_memory(
                host, region_ref)
            if known_capabilities:
                task_view["known_capabilities"] = known_capabilities
        view["task"] = task_view

    if phase == "review_entries":
        pending_review = host.pending_entry_review
        if isinstance(pending_review, dict):
            view["pending_entry_review"] = {
                "page_name": pending_review.get("page_name"),
                "regions": [
                    {
                        "name": item.get("name"),
                        **({"summary": _memory_clip(
                            item.get("summary"), 180)}
                           if item.get("summary") else {}),
                        **({"survey_memory": _memory_clip(
                            item.get("survey_memory"), 240)}
                           if item.get("survey_memory") else {}),
                    }
                    for item in pending_review.get("regions") or []
                    if isinstance(item, dict) and item.get("name")
                ],
                "candidates": [
                    {
                        "region_name": item.get("region_name"),
                        "operation": item.get("operation") or item.get("target"),
                        "subject": item.get("subject") or item.get("region_name"),
                        "target": item.get("target"),
                    }
                    for item in pending_review.get("candidates") or []
                    if isinstance(item, dict)
                ],
            }
        return view

    if phase not in {
        "record_regions", "review_region_equivalence", "survey_region",
        "completion_ready",
    }:
        return view

    page_name = (
        task.page_name if task is not None and task.page_name else bound_page)
    if not page_name:
        return view
    state = _region_state(host, page_name)
    snapshot = state.snapshot()
    regions = []
    for region in snapshot.get("regions") or []:
        if (phase == "survey_region" and task is not None
                and task.region_name
                and _page_key(region.get("name")) != _page_key(task.region_name)):
            continue
        item = {
            "name": region.get("name"),
            "complete": bool(region.get("coverage_complete")),
        }
        if region.get("summary"):
            item["summary"] = _memory_clip(region.get("summary"), 180)
        if region.get("survey_memory"):
            item["survey_memory"] = _memory_clip(
                region.get("survey_memory"), 240)
        if phase == "survey_region" and not item["complete"]:
            last_frame_id = str(
                region.get("last_incomplete_frame_id") or "")
            item["distinct_frame_since_incomplete"] = bool(
                last_frame_id
                and last_frame_id != str(snapshot.get("current_frame_id") or "")
            )
        regions.append(item)
    page_entries = [
        entry for entry in host.entry_ledger.entries
        if _page_key(entry.page_name) == _page_key(page_name)
        and (
            phase != "survey_region"
            or task is None
            or not task.region_name
            or _page_key(entry.region_name) == _page_key(task.region_name)
        )
    ]
    shared_entries: List[Dict[str, Any]] = []
    if phase == "survey_region" and task is not None and task.region_name:
        shared_entries = _shared_region_entry_candidates(
            host, page_name, task.region_name)
    view["survey_page_fact"] = {
        "regions": regions,
    }
    active_region_dispute = False
    if phase == "survey_region" and task is not None and task.region_name:
        region_audit = (
            host.entry_review_audits.get(_page_key(page_name)) or {}
        ).get(_page_key(task.region_name)) or {}
        active_region_dispute = (
            region_audit.get("status") in {"disagreement", "final_disagreement"}
            and int(region_audit.get("discussion_evidence_generation", -1))
            == host.entry_review_evidence_generation
        )
    pending_corrections = list(
        (host.page_update_corrections.get(_page_key(page_name)) or {}).values())
    model_corrections = [
        _model_page_correction_text(item)
        for item in pending_corrections if isinstance(item, dict)
    ]
    if model_corrections:
        view["survey_page_fact"]["pending_corrections"] = model_corrections
    known_entries = []
    known_signatures: set[tuple[str, str]] = set()
    for record in page_entries:
        item = {
            "target": record.target,
            "operation": record.operation or record.target,
            "subject": record.subject or record.region_name,
        }
        if active_region_dispute:
            item["entry_id"] = record.entry_id
        if record.region_name:
            item["region"] = record.region_name
        if record.destination_page:
            item["destination"] = record.destination_page
        known_entries.append(item)
        known_signatures.add((
            _page_key(item["operation"]),
            _page_key(item["target"]),
        ))
    for record in shared_entries:
        signature = (
            _page_key(record.get("operation") or record.get("target")),
            _page_key(record.get("target")),
        )
        if signature in known_signatures:
            continue
        item = {
            "target": record.get("target"),
            "operation": record.get("operation") or record.get("target"),
            "subject": record.get("subject") or task.region_name,
            "region": task.region_name,
        }
        if active_region_dispute and record.get("entry_id"):
            item["entry_id"] = record["entry_id"]
        if record.get("destination"):
            item["destination"] = record["destination"]
        known_entries.append(item)
        known_signatures.add(signature)
    if known_entries:
        view["survey_page_fact"]["known_entries"] = known_entries
    return view


def _latest_gui_action_context(
    history: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return compact semantic context for the latest settled GUI action."""
    for record in reversed(history):
        if record.get("kind") != "action":
            continue
        result = record.get("action_tool_result")
        if not isinstance(result, dict):
            continue
        before_frame = str(result.get("before_frame_id") or "")
        after_frame = str(result.get("after_frame_id") or "")
        if not before_frame or not after_frame:
            continue
        validated = record.get("validated_action")
        arguments = (
            validated.get("arguments")
            if isinstance(validated, dict)
            and isinstance(validated.get("arguments"), dict)
            else {}
        )
        return {
            "source_page": str(record.get("screen") or ""),
            "operation": str(
                result.get("operation")
                or (validated or {}).get("operation")
                or record.get("action")
                or ""
            ).casefold(),
            "target": str(
                record.get("target")
                or arguments.get("container_hint")
                or arguments.get("target")
                or ""
            ),
            "landed_page": str(record.get("landed_screen") or ""),
            "frame_changed": before_frame != after_frame,
            "result_reason": str(record.get("detail") or "")[:500],
        }
    return None
