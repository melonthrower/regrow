"""Code-derived exploration status bar and compact Agent context."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from .ledger import ExplorationLedger
from .contracts import submission_contract
from .models import OPEN_OPERATION_STATES, Operation, Task
from .region_routes import plan_region_route
from .tasks import deferred_inventory_reports, directed_state_distances, task_source_states


def operation_identity_ref(
    ledger: ExplorationLedger,
    operation_id: str,
) -> str:
    """Return the Region-owned identity exposed to the main Agent."""
    operation = ledger.operations.get(operation_id)
    if operation is None:
        return operation_id
    return operation.canonical_operation_id or operation.operation_id


def current_operation_binding(
    ledger: ExplorationLedger,
    operation_id: str,
    *,
    state_id: str = "",
) -> Optional[Operation]:
    """Resolve one stable Region Operation to its current local owner."""
    source = ledger.operations.get(operation_id)
    current_state_id = state_id or ledger.current_state_id
    if source is None or not current_state_id:
        return None
    stable_ref = operation_identity_ref(ledger, source.operation_id)
    matches: List[Operation] = []
    from .partition_review import qualification_gaps
    isolated = qualification_gaps(ledger)
    seen: set[str] = set()
    for occurrence in ledger.state_occurrences(current_state_id):
        if occurrence.region_id != source.region_id:
            continue
        for candidate in ledger.occurrence_operations(
                occurrence.occurrence_id):
            if (candidate.operation_id in seen or candidate.operation_id in isolated
                    or operation_identity_ref(
                        ledger, candidate.operation_id) != stable_ref
                    or candidate.action != source.action
                    or candidate.scope != source.scope
                    or candidate.direction != source.direction
                    or not (candidate.status in OPEN_OPERATION_STATES
                            or (candidate.status == "recorded"
                                and source.status in OPEN_OPERATION_STATES))):
                continue
            seen.add(candidate.operation_id)
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _task_text(ledger: ExplorationLedger, task: Optional[Task]) -> str:
    if task is None:
        if not ledger.current_state_id:
            return "首次识别并完整清点当前页面"
        return "当前未选择操作"
    if task.kind == "survey_page":
        state = ledger.states.get(task.state_id)
        page = ledger.pages.get(state.page_id) if state else None
        if ledger.current_state_id != task.state_id:
            return (
                f"先导航回待清点状态 {page.name if page else task.state_id} / "
                f"{state.name if state else task.state_id}，再完成页面清点"
            )
        return f"清点页面 {page.name if page else task.state_id} / {state.name if state else ''}"
    source_operation = ledger.operations.get(task.operation_id)
    if source_operation is None:
        return f"探索未知操作 {task.operation_id}"
    current_binding = current_operation_binding(ledger, task.operation_id)
    operation = current_binding or source_operation
    region = ledger.regions.get(operation.region_id)
    element = ledger.elements.get(operation.element_id)
    owner = (
        f"Element“{element.name}”" if element is not None
        else "Region 整体"
    )
    direction = f" direction={operation.direction}" if operation.direction else ""
    if (current_binding is None
            and ledger.current_state_id not in task_source_states(ledger, task)):
        return (
            f"先导航到操作来源，再探索 {region.name if region else operation.region_id} "
            f"的 {owner} 中“{operation.action}{direction} {operation.target}”"
        )
    verb = "确认参数" if operation.parameter_status == "unknown" else "探索"
    return (
        f"{verb} {region.name if region else operation.region_id} 的 {owner} 中“"
        f"{operation.action}{direction} {operation.target}”"
    )


def render_status_bar(
    ledger: ExplorationLedger,
    task: Optional[Task],
    *,
    system_scope: str,
    pending_attempt_id: str = "",
    correction: str = "",
    rejection_count: int = 0,
    rejection_limit: int = 0,
    submission: Optional[Mapping[str, Any]] = None,
) -> str:
    page = ledger.pages.get(ledger.current_page_id)
    state = ledger.states.get(ledger.current_state_id)
    lines = ["探索状态栏："]
    lines.append(
        "- 当前位置：" + (
            f"{page.page_id}（{page.name}） / {state.state_id}（{state.name}）"
            if page and state else "尚未登记"
        )
    )
    lines.append(f"- 系统前景判断：{system_scope}")
    lines.append(f"- 当前探索焦点：{_task_text(ledger, task)}")
    contract = submission or submission_contract(pending_attempt_id)
    lines.append("- 本轮提交合同：" + contract["instruction"])
    if task and task.strategy and not correction:
        lines.append(f"- 当前思路：{task.strategy}")
    if pending_attempt_id:
        lines.append(
            f"- 待结算动作：{pending_attempt_id} 已由框架真实执行；"
            "真实动作与前后观察保留，不重复执行。"
        )
    if task and task.attempt_count:
        lines.append(f"- 当前任务已执行尝试：{task.attempt_count} 次")
    if (task is not None
            and task.kind == "explore_operation"
            and not pending_attempt_id
            and task.status == "active"):
        last_attempt = next((
            item for item in reversed(list(ledger.attempts.values()))
            if item.task_id == task.task_id
        ), None)
        if last_attempt is not None and last_attempt.outcome == "no_effect":
            actual_owner = str(
                last_attempt.action.get("owner_ref") or "").strip()
            actual_owner_note = (
                f"上次实际 owner_ref={actual_owner}；"
                if actual_owner else "上次动作没有绑定 owner_ref；"
            )
            lines.append(
                f"- 当前决策约束：{last_attempt.attempt_id} 已结算为 no_effect；"
                "没有待结算动作，previous_action 必须为 null。"
                f"{actual_owner_note}当前操作任务仍未结束；不要原样重复。"
                "若最新截图仍显示该 owner，可显著改变可靠点位重试一次；"
                "否则用空 owner_ref 的恢复动作；"
                "达到确定性上限后框架会保留 failed gap。"
            )
    if correction:
        lines.append(f"- 必须修正：{correction}")
    if rejection_count and rejection_limit:
        lines.append(
            f"- 当前任务动作拒绝：{rejection_count}/{rejection_limit} 次；"
            "达到上限会如实记为失败并继续其他任务"
        )
    return "\n".join(lines)


def current_page_record(
    ledger: ExplorationLedger,
    *,
    state_id: str = "",
) -> Dict[str, Any]:
    state = ledger.states.get(state_id or ledger.current_state_id)
    page = ledger.pages.get(state.page_id if state else "")
    if page is None or state is None:
        return {}
    regions: List[Dict[str, Any]] = []
    for occurrence in ledger.state_occurrences(state.state_id):
        region = ledger.regions[occurrence.region_id]
        variant = ledger.ensure_occurrence_variant(occurrence.occurrence_id)
        elements = []
        for element in ledger.variant_elements(variant.variant_id):
            elements.append({
                "element_ref": element.element_id,
                "name": element.name,
                "last_observation": (dict(element.observations[-1])
                                     if element.observations else None),
                "operations": [{
                    "operation_ref": operation_identity_ref(
                        ledger, operation.operation_id),
                    "action": operation.action,
                    "target": operation.target,
                    "status": operation.status,
                    "reason": operation.reason,
                    "result": operation.result,
                    "parameter_status": operation.parameter_status,
                    "parameter_summary": operation.parameter_summary,
                    "parameter_evidence_refs": list(
                        operation.parameter_evidence_refs),
                } for operation in ledger.element_operations(
                    element.element_id)],
            })
        regions.append({
            "region_ref": region.region_id,
            "parent_region_ref": (
                ledger.occurrences[occurrence.parent_occurrence_id].region_id
                if occurrence.parent_occurrence_id else ""),
            "variant_ref": occurrence.variant_id,
            "name": occurrence.name,
            "summary": occurrence.summary,
            "memory": region.memory or occurrence.summary,
            "elements": elements,
            "region_operations": [{
                "operation_ref": operation_identity_ref(
                    ledger, operation.operation_id),
                "action": operation.action,
                "target": operation.target,
                "direction": operation.direction,
                "status": operation.status,
                "reason": operation.reason,
                "result": operation.result,
                "parameter_status": operation.parameter_status,
                "parameter_summary": operation.parameter_summary,
                "parameter_evidence_refs": list(
                    operation.parameter_evidence_refs),
            } for operation in ledger.variant_operations(variant.variant_id)
              if operation.scope == "region"],
        })
        bound = {operation_identity_ref(ledger, operation.operation_id)
                 for operation in ledger.variant_operations(variant.variant_id)}
        missing = [{"operation_ref": operation.canonical_operation_id,
                    "action": operation.action, "target": operation.target,
                    "scope": operation.scope, "direction": operation.direction}
                   for operation in ledger.canonical_operations.values()
                   if operation.region_id == region.region_id
                   and operation.canonical_operation_id not in bound]
        if missing:
            regions[-1]["unbound_known_operations"] = missing
            regions[-1]["unbound_operations_note"] = (
                "仅为此Region的历史功能身份，不证明当前可见。若新图确认存在，"
                "用这些co补登记当前独立控件与动作；不能把co当owner或复制旧控件坐标。")
    return {
        "page_ref": page.page_id,
        "page_name": page.name,
        "page_summary": page.summary,
        "state_ref": state.state_id,
        "state_name": state.name,
        "state_summary": state.summary,
        "survey_complete": state.survey_complete,
        "regions": regions,
    }


def semantic_exploration_focus(
    ledger: ExplorationLedger,
    task: Optional[Task],
) -> Dict[str, Any]:
    """Project a compact semantic focus from the one persistent graph."""
    operation = (
        ledger.operations.get(task.operation_id)
        if task is not None and task.kind == "explore_operation" else None
    )
    source_state = ledger.states.get(task.state_id if task is not None else "")
    page = ledger.pages.get(
        source_state.page_id if source_state is not None
        else ledger.current_page_id
    )
    region = ledger.regions.get(operation.region_id if operation else "")
    identity = (
        ledger.representative_probe_identity(operation.operation_id)
        if operation is not None else None
    ) or ledger.canonical_operations.get(
        operation.canonical_operation_id if operation else "")
    path = [item for item in (
        page.name if page else "",
        region.name if region else "",
        operation.target if operation else "",
    ) if item]
    region_memories: List[Dict[str, str]] = []
    seen: set[str] = set()
    if page is not None:
        for state_id in page.state_ids:
            for occurrence in ledger.state_occurrences(state_id):
                if occurrence.region_id in seen:
                    continue
                seen.add(occurrence.region_id)
                item = ledger.regions[occurrence.region_id]
                region_memories.append({
                    "region_ref": item.region_id,
                    "name": item.name,
                    "memory": item.memory or item.summary,
                })
    representative_probe = None
    if identity is not None and identity.representative_operation_ids:
        representative_probe = {
            "operation_ref": identity.canonical_operation_id,
            "goal": identity.representative_goal,
            "member_owner_refs": [
                ledger.operations[item].element_id
                for item in (
                    identity.representative_member_operation_ids
                    or identity.representative_operation_ids)
            ],
            "representative_owner_refs": [
                ledger.operations[item].element_id
                for item in identity.representative_operation_ids
            ],
            "completed_owner_refs": [
                ledger.operations[item].element_id
                for item in identity.representative_operation_ids
                if ledger.operations[item].status == "verified"
            ],
        }
    result = {
        "path": path,
        "goal": (
            f"了解“{operation.target}”支持的功能，必要时进入其页面/区块，"
            "定位 Region 并收集必要参数和真实连接；不以重复验证按钮或穷举参数为目标。"
            if operation is not None else
            f"定位 {page.name} 的 Region，记录可用于后续指令组合的功能与必要信息。" if page is not None else
            "识别当前功能页面并定位 Region，逐步扩展应用功能覆盖。"
        ),
        "region_memories": region_memories,
        "representative_probe": representative_probe,
    }
    return result


def pending_action_record(
    ledger: ExplorationLedger,
    attempt_ref: str,
) -> Dict[str, Any]:
    """Echo the exact model-facing owner facts for one pending Attempt."""
    attempt = ledger.attempts.get(attempt_ref)
    if attempt is None:
        return {}
    action = attempt.action
    operation = ledger.operations.get(str(action.get("operation_ref") or ""))
    identity = (
        ledger.representative_probe_identity(operation.operation_id)
        if operation is not None else None
    ) or ledger.canonical_operations.get(
        operation.canonical_operation_id if operation else "")
    representative_same_kind_required = bool(
        operation is not None
        and identity is not None
        and operation.operation_id in identity.representative_operation_ids
        and all(
            item == operation.operation_id
            or ledger.operations[item].status == "verified"
            for item in identity.representative_operation_ids
        )
    )
    result = {
        "attempt_ref": attempt.attempt_id,
        "kind": str(action.get("kind") or ""),
        "owner_ref": str(action.get("owner_ref") or ""),
        "target": str(action.get("target") or ""),
        "point_1000": list(action["point_1000"]) if action.get("point_1000") else None,
        "direction": str(action.get("direction") or ""),
        "parameter_confirmation_required": bool(
            operation is not None
            and operation.parameter_status == "unknown"),
        "parameter_status": (
            operation.parameter_status if operation is not None else ""),
        "parameter_summary": (
            operation.parameter_summary if operation is not None else ""),
        "before_region_refs": [
            occurrence.region_id
            for occurrence in ledger.state_occurrences(
                attempt.source_state_id)
        ],
    }
    if representative_same_kind_required:
        result["representative_same_kind_required"] = True
    if action.get("kind") == "scroll":
        result["amount"] = action.get("amount")
    if action.get("kind") == "input_text":
        result["text"] = str(action.get("text") or "")
    return result


def known_graph(ledger: ExplorationLedger) -> Dict[str, Any]:
    distances = directed_state_distances(ledger, ledger.current_state_id)
    states = []
    for state in ledger.states.values():
        page = ledger.pages[state.page_id]
        states.append({
            "page_ref": page.page_id,
            "page_name": page.name,
            "state_ref": state.state_id,
            "state_name": state.name,
            "state_summary": state.summary,
            "survey_complete": state.survey_complete,
            "known_regions": [
                {"region_ref": item.region_id, "name": item.name,
                 "parent_region_ref": (ledger.occurrences[item.parent_occurrence_id].region_id
                                       if item.parent_occurrence_id else "")}
                for item in ledger.state_occurrences(state.state_id)
            ],
            "distance": distances.get(state.state_id),
        })
    connections = [{
        "from": item.source_state_id,
        "to": item.target_state_id,
        "action": item.action.get("target") or item.action.get("kind"),
    } for item in ledger.transitions]
    return {"states": states, "connections": connections}


def compact_known_graph(
    ledger: ExplorationLedger, task: Optional[Task], pending: Any,
    task_view: Mapping[str, Any], *, needs_route: bool, rediscovering: bool,
    query: str = "",
) -> Dict[str, Any]:
    from .knowledge_retrieval import retrieve_knowledge
    return retrieve_knowledge(ledger, task, pending, task_view, query=query,
                              needs_route=needs_route, rediscovering=rediscovering)


def recent_actions(
    ledger: ExplorationLedger,
    *,
    task_id: str,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    task = ledger.tasks.get(task_id)
    focus_operation_ref = (
        operation_identity_ref(ledger, task.operation_id)
        if task is not None and task.kind == "explore_operation" else ""
    )
    focus_region = (ledger.operations[task.operation_id].region_id
                    if task is not None and task.operation_id in ledger.operations else "")
    relevant = [
        item for item in ledger.attempts.values()
        if item.task_id == task_id
        or (focus_region and item.action.get("operation_ref") in ledger.operations
            and ledger.operations[item.action["operation_ref"]].region_id == focus_region)
    ]
    result = []
    for item in relevant[-limit:]:
        actual_local_ref = str(item.action.get("operation_ref") or "")
        actual_operation_ref = operation_identity_ref(
            ledger, actual_local_ref)
        result.append({
            "attempt_ref": item.attempt_id,
            "kind": str(item.action.get("kind") or ""),
            "point_1000": (list(item.action["point_1000"])
                           if item.action.get("point_1000") else None),
            "focus_operation_ref": focus_operation_ref,
            "actual_operation_ref": actual_operation_ref,
            "actual_region_ref": (
                ledger.operations[actual_local_ref].region_id
                if actual_local_ref in ledger.operations else ""
            ),
            "actual_element_ref": (
                ledger.operations[actual_local_ref].element_id
                if actual_local_ref in ledger.operations else ""
            ),
            "source_state_ref": item.source_state_id,
            "target_state_ref": item.target_state_id,
            "outcome": item.outcome,
            "visible_result": item.visible_result,
            "completed_focus": bool(
                focus_operation_ref
                and actual_operation_ref == focus_operation_ref
                and item.outcome == "success"),
        })
    return result


def build_task_view(
    ledger: ExplorationLedger,
    task: Optional[Task],
    *,
    rediscovering: bool = False,
) -> Dict[str, Any]:
    if rediscovering:
        result: Dict[str, Any] = {
            "kind": "resume_region_rediscovery",
            "instruction": (
                "这是重启后的最新截图，不沿用旧位置。只需在 page_report "
                "确认目标或路线起点的当前可交互 Region 和操作；若认为是"
                "已知区块，引用其 region_ref 供审核。局部观察不能证明整个旧State相同："
                "复用已完成State时按新图确认全部Region引用，elements/region_operations留空，"
                "沿用该State已有控件；唯一增量是：原来仅record且从未尝试的入口，当前已不选中、合法适用且没有真实成功证据时，"
                "可引用本State已有element_ref和稳定co补报handling=explore及新适用依据，交给原任务调度。其他多报控件只留审计。"
                "只确认局部或组合不同时用new_state且state_ref为空，仍可复用Region。"
                "其余内容未清点时保持 survey_complete=false，"
                "提交清单时 action=null，取得当前 binding 后即可继续原任务。"
                "找不到目标或路线起点时，可先用空 owner 的非滚动恢复动作；"
                "恢复结果正常结算，之后再根据新截图确认区块。"
            ),
        }
        if task is not None:
            result["task_ref"] = task.task_id
            result["resume_task_kind"] = task.kind
            if task.kind == "survey_page":
                result["instruction"] = (
                    f"这是重启后的最新截图。请确认清点任务来源 {task.state_id} 的"
                    "当前可见 Region，提交 page_report 且 action=null；不要求本轮"
                    "完成清点。确认来源区块后框架退出恢复定位，继续普通清点任务。"
                    "若尚未回到来源，先根据当前截图使用已有恢复路线。"
                )
            operation = ledger.operations.get(task.operation_id)
            if operation is not None:
                result.update({
                    "target_region_ref": operation.region_id,
                    "target_operation_ref": operation_identity_ref(
                        ledger, operation.operation_id),
                    "target_action": operation.action,
                    "target": operation.target,
                })
        return result
    if task is None:
        if not ledger.current_state_id:
            return {
                "kind": "survey_page",
                "instruction": "首次识别当前 Page/State，并提交完整 page_report",
            }
        return {
            "kind": "no_task",
            "instruction": (
                "当前没有可执行待办；如有待结算动作，仅报告其实际结果。"
                "框架根据账本决定结束状态，不要求你判断全局完成。"
            ),
        }
    result: Dict[str, Any] = {
        "task_ref": task.task_id,
        "kind": task.kind,
        "source_state_ref": task.state_id,
        "current_page_ref": ledger.current_page_id,
        "current_state_ref": ledger.current_state_id,
        "attempt_count": task.attempt_count,
    }
    source_state = ledger.states.get(task.state_id)
    source_page = (
        ledger.pages.get(source_state.page_id)
        if source_state is not None else None
    )
    if source_page is not None:
        result["source_page_ref"] = source_page.page_id
        result["source_page_name"] = source_page.name
    if (task.kind == "survey_page"
            and ledger.current_state_id != task.state_id):
        result["instruction"] = (
            "当前已经离开本调查任务的来源状态。不要重复提交当前位置的 "
            "page_report；先令 page_report=null，但 screen 仍须按最新截图报告"
            "当前位置的 known Page/State。根据截图和已知页面图用 purpose=route "
            "返回 source_state_ref，operation_ref 留空；真实到达后再完成清点。"
        )
    elif task.kind == "survey_page":
        inventory_hint = (
            "本 State 已有清单；只补新增、变化或先前遗漏，不要重列未变化的控件。"
            if source_state is not None and source_state.inventory_passes else
            "对当前可交互前景做首帧完整清点。"
        )
        result["instruction"] = (
            inventory_hint + "只清点当前前景；未开子菜单/其他页交给explore待办，不阻止当前完成。"
            "已登记控件可调查缺失信息，不必先把清点标完整；同轮新清单的点击留到下一轮。"
            "普通纵向scroll记record。同质数据结构明确即可收束；有限参数列表仍有未见选项时继续查看，"
            "不逐项试值。survey_complete记录实际覆盖；完整且可安全关闭前景时可同轮back，否则action=null。"
        )
    if task.kind == "explore_operation":
        source_operation = ledger.operations.get(task.operation_id)
        source_states = sorted(task_source_states(ledger, task))
        current_binding = current_operation_binding(
            ledger, task.operation_id)
        unavailable_sources = {state_id for state_id in source_states
            if (candidate := current_operation_binding(ledger, task.operation_id, state_id=state_id)) is not None
            and candidate.status == 'deferred'}
        source_states = [state_id for state_id in source_states if state_id not in unavailable_sources]
        if current_binding is not None and current_binding.status == 'deferred':
            result['current_binding_unavailable'] = current_binding.reason
            current_binding = None
        operation = current_binding or source_operation
        region = ledger.regions.get(
            source_operation.region_id) if source_operation else None
        element = (
            ledger.elements.get(operation.element_id)
            if operation else None
        )
        result.update({
            "operation_ref": operation_identity_ref(
                ledger, task.operation_id),
            "region_ref": (
                source_operation.region_id if source_operation else ""),
            "element_ref": (
                operation.element_id
                if operation is not None
                and (current_binding is not None
                     or ledger.current_state_id in source_states)
                else ""),
            "region": region.name if region else "",
            "scope": operation.scope if operation else "",
            "element": element.name if element else "",
            "action": operation.action if operation else "",
            "direction": operation.direction if operation else "",
            "target": operation.target if operation else "",
            "known_reason": operation.reason if operation else "",
            "parameter_status": (
                operation.parameter_status if operation else ""),
            "parameter_summary": (
                operation.parameter_summary if operation else ""),
            "parameter_confirmation_required": bool(
                operation is not None
                and operation.parameter_status == "unknown"),
        })
        result["source_state_refs"] = source_states
        if unavailable_sources:
            result['conditional_source_state_refs'] = sorted(unavailable_sources)
        source_bindings = []
        for state_id in source_states:
            if state_id == ledger.current_state_id:
                continue
            binding = current_operation_binding(
                ledger, task.operation_id, state_id=state_id)
            if binding is not None:
                source_bindings.append({
                    "state_ref": state_id, "region_ref": binding.region_id,
                    "owner_ref": (binding.element_id if binding.scope == "element"
                                  else binding.region_id),
                })
        if source_bindings:
            result["known_source_bindings"] = source_bindings
            result["source_binding_note"] = (
                "仅列本任务在已知来源State的历史owner，不证明当前可见。"
                "最新截图确认到达对应State且该控件可交互后才复制其owner；"
                "尚未到达不能使用，不借用另一State的同名按钮。")
        result["required_region_ref"] = (
            source_operation.region_id if source_operation else "")
        region_route = plan_region_route(
            ledger,
            current_state_id=ledger.current_state_id,
            target_region_id=(
                source_operation.region_id if source_operation else ""),
            target_operation_id=(
                source_operation.operation_id if source_operation else ""),
        )
        region_route["steps"] = [_agent_region_route_step(
            step) for step in region_route.get("steps", [])]
        result["region_route"] = region_route
        binding_instruction = ""
        if current_binding is not None:
            owner_ref = (
                current_binding.element_id
                if current_binding.scope == "element"
                else current_binding.region_id
            )
            binding_instruction = (
                f"目标操作归属于 Region {current_binding.region_id}；"
                f"当前 State 已有同一稳定 Operation 的可执行 owner_ref="
                f"{owner_ref}。只使用这个当前绑定和最新截图定位；"
                "Page/State 只提供可见上下文，不创建新的操作身份。"
                "当前目标已确认，不必为执行它重新完整清点当前页面。"
            )
        if (current_binding is None
                and ledger.current_state_id not in source_states):
            result["required_source_state_ref"] = (
                task.state_id if task.state_id in source_states
                else source_states[0] if source_states else task.state_id)
            region_route = result["region_route"]
            if (region_route.get("status") == "ready"
                    and region_route.get("steps")):
                first = region_route["steps"][0]
                result["instruction"] = (
                    "当前目标 Region binding 不在前景；Region 路线第一跳是 "
                    f"{first['source_region_ref']} 中的稳定 Operation "
                    f"{first['operation_ref']}（{first['target']}），当前可执行 "
                    f"owner_ref={first['owner_ref']}。"
                    "当前路线起点已确认，不必为导航重新完整清点整个页面。"
                    "只在最新截图确认该 owner 可交互时执行；动作后必须"
                    "验证 expected_revealed_region_refs，再重新规划，不能"
                    "沿用旧坐标或用同 Region 的其他上下文按钮替代。"
                )
                return result
            if region_route.get("status") == "ambiguous":
                result["instruction"] = (
                    "当前 Region 的同一命令在不同 Variant 有冲突效果，"
                    "不能猜测路线。请先依据最新截图清点或导航到有直接"
                    "Transition 证据的 Variant。"
                )
                return result
            result["instruction"] = (
                "当前 State 不能完成这个操作任务；先根据截图和已知页面图"
                "导航到准确的来源 State，确认该任务的本地 owner 可见后再执行。"
                "同一 Region 在其他 State 中已经结束或已经选中的按钮，不能"
                "替代当前任务。"
            )
        elif operation is not None and operation.status == "deferred":
            result["instruction"] = (
                binding_instruction +
                "其他可用任务已完成，现在重新检查这个曾被推后的操作。"
                "若已可执行就直接执行；若缺少可安全完成的前置，先用当前可见的"
                "已登记owner执行必要准备，再执行原操作。前置操作已record也可"
                "用于准备，不必用next_operation_ref请求派发或声明代表探针。"
                "若仍受阻，在reason说明实际前置和证据，不输出Task结果。"
            )
        elif (operation is not None
                and operation.parameter_status == "unknown"):
            result["instruction"] = (
                binding_instruction +
                "当前 Operation 的参数形式或代表值尚未确认。本轮只执行这一个已登记"
                " owner 来打开选择器或参数表面；下一轮根据 before/after 在 "
                "previous_action.parameter_info 填 none 或 observed 及简短自然语言"
                "说明。普通同质参数只记录值域和一个代表，不逐项执行。"
            )
        else:
            result["instruction"] = (
                binding_instruction +
                "本任务用于发现未知功能及必要连接；派发不要求重复点击已选中入口"
                "或验证已知结果。先在最新截图中确认精确目标可见且能直接"
                "接收交互。若打开的菜单或模态弹层仍在前景，不执行其后的背景控件，"
                "即使控件未被几何遮挡；先用 route/recover 关闭临时层。否则满足时"
                "用 purpose=execute，不可见时先准备，不能沿用旧 State 的坐标。"
            )
    return result


def _agent_region_route_step(
    step: Mapping[str, Any],
) -> Dict[str, Any]:
    """Hide local binding identity from the Region-led Agent view."""
    projected = dict(step)
    projected["operation_ref"] = str(
        projected.pop("canonical_operation_ref", "")
        or projected.get("operation_ref") or "")
    projected.pop("source_variant_ref", None)
    return projected


def _correction_reference_rows(
    ledger: ExplorationLedger, card: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Supply exact historical bindings for elements named by the correction."""
    text = json.dumps(card, ensure_ascii=False)
    rows = []
    for ref, element in ledger.elements.items():
        if not re.search(r"(?<![A-Za-z0-9_-])" + re.escape(ref) + r"(?![A-Za-z0-9_-])", text):
            continue
        rows.append({
            "element_ref": ref, "name": element.name,
            "region_ref": element.region_id, "variant_ref": element.variant_id,
            "source_state_refs": list(dict.fromkeys(
                ledger.occurrences[item].state_id
                for item in element.source_occurrence_ids if item in ledger.occurrences)),
            "operations": [{
                "operation_ref": operation_identity_ref(ledger, operation.operation_id),
                "action": operation.action, "target": operation.target,
                "direction": operation.direction,
                "parameter_status": operation.parameter_status,
                "parameter_summary": operation.parameter_summary,
            } for operation in ledger.element_operations(ref)],
        })
    return rows


def build_agent_context(
    ledger: ExplorationLedger,
    task: Optional[Task],
    system_scope: str,
    *,
    app_name: str,
    platform: str,
    pending_attempt_id: str,
    correction: str,
    rejection_count: int,
    rejection_limit: int,
    pending_report_correction: Optional[Mapping[str, Any]] = None,
    rediscovering: bool = False,
    exploration_goal: str = "",
    context_query: str = "",
    submission: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    submission = submission or submission_contract(pending_attempt_id)
    pending = ledger.attempts.get(pending_attempt_id)
    needs_route = bool(
        task is not None
        and not (task.kind == "explore_operation"
                 and current_operation_binding(
                     ledger, task.operation_id) is not None)
        and ledger.current_state_id not in task_source_states(
            ledger, task)
    )
    task_view = build_task_view(ledger, task, rediscovering=rediscovering)
    graph = compact_known_graph(ledger, task, pending, task_view,
                                needs_route=needs_route, rediscovering=rediscovering, query=context_query)
    status_bar = render_status_bar(
        ledger,
        task,
        system_scope=system_scope,
        pending_attempt_id=pending_attempt_id,
        correction=correction,
        rejection_count=rejection_count,
        rejection_limit=rejection_limit,
        submission=submission,
    )
    if pending_attempt_id and submission['phase'] != 'inventory_edits':
        status_bar += (
            "\n- 页面清点证据：page_report 只根据图2；图1只用于"
            "结算，动作前页面的详细控件清单已省略。"
            "若图2为已完成清点的已知State且无增量，page_report=null；"
            "尚未完成的survey在功能结构已明确时仍须提交page_report.survey_complete=true，"
            "即使没有新增控件，也要据此结束调查。"
            "首次发现的State/前景才完整清点；关闭菜单返回时，查已知页面图的"
            "survey_complete。已完成且无增量就不重报控件。"
        )
    if pending_attempt_id or rediscovering:
        status_bar += (
            "\n- 已知页面图的 known_regions 只是历史引用目录，不证明当前可见；"
            "根据当前最新截图确认已知 State 和可见组件后，才复制对应 Region ref。"
        )
    context = {
        "图片": (
            ["图1：待结算动作前完整截图", "图2：当前最新完整截图"]
            if pending_attempt_id else ["图1：当前最新完整截图"]
        ),
        "目标应用": app_name,
        "平台": platform,
        "状态栏": status_bar,
        "本轮提交合同": submission,
        "探索焦点": semantic_exploration_focus(ledger, task),
        "当前任务精确卡": task_view,
        "当前页面已登记内容": (
            {} if pending_attempt_id else current_page_record(
                ledger)),
        "已知页面图": graph,
        "当前焦点动作回执": recent_actions(
            ledger, task_id=task.task_id if task else ""),
    }
    if exploration_goal:
        if task is None:
            context["探索焦点"]["goal"] = exploration_goal
            if ledger.current_state_id and not rediscovering:
                context["当前任务精确卡"] = {"kind": "no_task", "instruction":
                    "当前未自动派发功能；按探索范围和最新截图选择需要的owner动作。"
                    "若选择开放操作，框架会将真实动作绑定到该待办；record控件也可用于必要恢复。"
                    "缺当前绑定先补清单，有pending先回填，不必为执行恢复控件创建新任务。"}
        context["探索范围"] = {"goal": exploration_goal,
            "instruction": "按给定范围选择调查。已登记入口不等于本次都要执行；范围外可保留记录并说明。"
                           "当前焦点不合范围时先恢复或改选。恢复可直接使用当前record控件的owner_ref，不必先派新Task；缺当前绑定先补清单。next_operation_ref只用于改选已有开放待办。"
                           "临时试验恢复后再结束；发现子表面需据实际图登记，不复制旧值为当前事实。"}
    deferred = deferred_inventory_reports(ledger).get(ledger.current_state_id)
    if deferred is not None:
        context["待补清单"] = {
            "state_ref": ledger.current_state_id, "reason": deferred["reason"],
            "instruction": "这份清单未入库，原动作已经结算，不要重做。可据最新图补报，"
                           "也可先沿已确认绑定探索其他页面；不得使用被拒绝候选作为执行依据。",
            "已登记引用": _correction_reference_rows(ledger, {"reason": deferred["reason"]}),
        }
    # Remove only exact text duplicates; every binding and parameter stays intact.
    focus_memories = {item["region_ref"]: item["memory"]
                      for item in context["探索焦点"]["region_memories"]}
    for region in context["当前页面已登记内容"].get("regions", []):
        shared_memory = focus_memories.get(region["region_ref"])
        for field in ("memory", "summary"):
            if shared_memory and region.get(field) == shared_memory:
                region.pop(field)
    correction_card = dict(
        pending_report_correction or {})
    if (correction_card
            and correction_card.get("pending_attempt_ref")
            == pending_attempt_id):
        references = _correction_reference_rows(ledger, correction_card)
        if references:
            correction_card["已登记引用"] = references
            correction_card["引用说明"] = (
                "仅供核对纠正中明确提到的 Element 及其历史绑定，不证明当前可见或可点击。"
                "先依据最新截图确认同一控件，再复制对应 el/co；不是该控件则修正描述，新候选留空。")
        context["合同纠正卡"] = correction_card
    if pending_attempt_id:
        context["待结算动作详情"] = pending_action_record(
            ledger, pending_attempt_id)
        if submission['phase'] == 'inventory_edits':
            context['当前任务精确卡'] = {'instruction': '任务不变；实际动作已投递。本轮只编辑暂存候选，提交方式见本轮提交合同。'}
        elif not rediscovering:
            context["当前任务精确卡"]["instruction"] = (
                "本卡位置、当前绑定与路线来自图1，不代表图2落点。先按图2结算实际动作；"
                "若已返回已清点State且无新事实，page_report=null。图2确认任务控件可交互时，"
                "可用本卡element_ref或对应State的known_source_bindings继续，不再导航或重报。"
                "本轮缺所需引用时可先action=null结算，下一轮读取该State已有目录；"
                "确有新功能、遗漏或变化才补清单，未完成survey仍需调查。"
                "意外落点按实际图定位，不因历史路线或旧编号假定已到达。")
        attempt = ledger.attempts.get(pending_attempt_id)
        if attempt is not None and attempt.agent_reason:
            context["动作前说明（含预测，不是已验证事实）"] = attempt.agent_reason
    if not pending_attempt_id and not rediscovering:
        from .region_refinement import refinement_context
        context["分区修正候选"] = refinement_context(ledger, task)
    return context


__all__ = [
    "build_agent_context", "build_task_view",
    "current_operation_binding", "current_page_record", "known_graph",
    "operation_identity_ref", "pending_action_record", "recent_actions",
    "render_status_bar", "semantic_exploration_focus",
]
