"""Experimental single-Agent page exploration loop.

The main Agent owns page-local planning and semantic records.  The framework
keeps stable IDs, executes one safe-declared GUI action, and stores evidence.
This module deliberately does not call semantic reviewers or the task pool.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .autonomous_action_execution import (
    _commit_pending,
    _convert_action_tool,
    _prepare_action_attempt,
)
from .autonomous_action_tools import action_tool_catalog
from .autonomous_recovery import _handle_outside_target_app
from .autonomous_page_session_ledger import PageSessionLedger, _text
from .autonomous_region_tools import AutonomousRegionState, screenshot_frame_id
from .autonomous_runtime import (
    AutonomousTraversalRuntime,
    _checkpoint,
    _register_scene,
)
from .autonomous_turn import (
    AutonomousDecision,
    AutonomousTurn,
    PendingAction,
    PreviousAssessment,
    SurfaceRegistration,
    _page_key,
)


PAGE_SESSION_PROMPT = """\
你是 GUI 应用自主遍历主 Agent。你连续负责当前页面内的观察、待办安排、区域与操作记录、动作选择、结果判断和结束提议。框架不替你判断界面语义，只保存你的结构化记录、执行动作并保留截图证据。

每轮按以下顺序工作：
1. 先识别最新完整截图所属的稳定功能页面和有实质操作差异的页面状态。页面名不携带“空内容、已展开、已选择”等临时状态；这些状态确实影响后续操作时写入 Variant。滚动、悬停、焦点、时间、普通数值变化和短暂遮挡不建立新页面状态。
2. 若附有动作前截图，先根据前后截图报告该动作的真实可见结果。不要把预期效果当成事实。
3. 更新当前页面工作记录：strategy 是下一步短思路；todo 保存仍影响后续决策的事项；Region 是稳定功能组件；operation 是用户可执行的“操作 + 语义目标”。同一组件的重复内容或参数值只保留代表操作。
4. 可同时更新记录并执行一个动作。operation_attempt 必须能按“动作类型 + target”唯一匹配本轮或既有 operation；导航、定位、滚动或恢复可以不匹配操作。只执行当前截图中可见、可逆、无外部提交且你明确判断为 safe 的动作；危险、不可逆或外部效果操作只记录，不执行。操作系统栏、Dock、任务栏和窗口管理按钮不属于目标应用 Region。
5. 当前不可执行但仍有价值的事项标记 deferred 并写具体原因；错误或无命令语义的事项才 cancelled。只有当前页面没有 pending/in_progress 的 todo 和 operation 时才能结束页面；只有所有已知页面都结束后才能提出结束遍历。

简短示例：重复列表中的同一种选择只登记一个代表操作并标记 recorded，不逐个改值；展开一项后若只改变所属区域，就在同一 Region 中补充新操作和待办，不重建整页。

不要编造框架 ID。新增记录的 id 留空；修改已有记录时使用状态栏给出的精确 id。reason 只写本轮证据和选择，不展开长推理。
"""


def _action_schema(catalog: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    variants = []
    for item in catalog:
        variants.append({
            "type": "object",
            "properties": {
                "purpose": {"type": "string", "enum": [
                    "navigation", "locating", "operation_attempt",
                    "interruption_recovery", "region_survey",
                ]},
                "safety": {"type": "string", "enum": ["safe", "uncertain", "dangerous"]},
                "tool_name": {"type": "string", "enum": [item["name"]]},
                "tool_arguments": deepcopy(item["input_schema"]),
            },
            "required": ["purpose", "safety", "tool_name", "tool_arguments"],
            "additionalProperties": False,
        })
    return {"anyOf": [*variants, {"type": "null"}]}


def page_session_response_schema(
    catalog: Sequence[Dict[str, Any]], *, has_previous: bool,
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {
        "app_scope": {"type": "string", "enum": ["target_app", "external_app", "uncertain"]},
        "screen": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "identity": {"type": "string", "enum": ["new", "known", "uncertain"]},
                "summary": {"type": "string", "minLength": 1},
                "surface_kind": {"type": "string", "enum": ["page", "dialog", "menu", "drawer", "other"]},
                "variant": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "identity": {"type": "string", "enum": ["new", "known", "uncertain"]},
                        "visible_predicates": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "identity", "visible_predicates"],
                    "additionalProperties": False,
                },
            },
            "required": ["name", "identity", "summary", "surface_kind", "variant"],
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
        "workspace_update": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "minLength": 1, "maxLength": 240},
                "todos": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "text": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "text", "status", "reason"],
                    "additionalProperties": False,
                }},
                "regions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string", "minLength": 1},
                        "summary": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "name", "summary"],
                    "additionalProperties": False,
                }},
                "operations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "region_name": {"type": "string", "minLength": 1},
                        "operation": {"type": "string", "minLength": 1}, "target": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "enum": ["pending", "recorded", "deferred", "cancelled"]},
                        "reason": {"type": "string"}, "result": {"type": "string"},
                    },
                    "required": ["id", "region_name", "operation", "target", "status", "reason", "result"],
                    "additionalProperties": False,
                }},
                "page_status": {"type": "string", "enum": ["active", "complete"]},
            },
            "required": ["strategy", "todos", "regions", "operations", "page_status"],
            "additionalProperties": False,
        },
        "action": _action_schema(catalog),
        "finish_exploration": {"type": "boolean"},
    }
    required = [
        "app_scope", "screen", "reason", "workspace_update",
        "action", "finish_exploration",
    ]
    if has_previous:
        properties["previous_action"] = {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": ["changed", "no_visible_change", "uncertain"]},
                "matches_intent": {"type": "boolean"},
                "failure_kind": {"anyOf": [
                    {"type": "string", "enum": ["temporarily_unavailable", "not_interactive"]},
                    {"type": "null"},
                ]},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["outcome", "matches_intent", "failure_kind", "reason"],
            "additionalProperties": False,
        }
        required.append("previous_action")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _build_prompt(
    host: AutonomousTraversalRuntime,
    ledger: PageSessionLedger,
    history: Sequence[Dict[str, Any]],
    *,
    pending: Optional[PendingAction],
    correction: str,
    scope_unknown: bool,
) -> str:
    current_page = host.protocol_map.current_page
    recent_actions = []
    for item in history:
        if item.get("kind") != "action":
            continue
        if item.get("outcome") == "awaiting_observation":
            continue
        validated = item.get("validated_action")
        validated = validated if isinstance(validated, dict) else {}
        arguments = validated.get("arguments")
        if not isinstance(arguments, dict):
            arguments = (
                {"target": item.get("target")}
                if item.get("target") not in (None, "") else {}
            )
        action = {
            "page": str(item.get("screen") or ""),
            "purpose": str(
                validated.get("purpose") or item.get("purpose") or ""),
            "operation": str(
                validated.get("operation") or item.get("action") or ""),
            "arguments": dict(arguments),
            "outcome": str(item.get("outcome") or ""),
            "result": _text(item.get("detail"), limit=240),
        }
        if item.get("landed_screen") not in (None, ""):
            action["landed_page"] = item.get("landed_screen")
        recent_actions.append(action)
    payload = {
        "current_location": {
            "last_bound_page": current_page,
            "last_bound_variant": host.protocol_map.current_variant,
            "foreground_owner": "unknown" if scope_unknown else "target_app",
            "actions_used": host.action_count,
            "max_actions": host.max_actions,
        },
        "known_pages": ledger.known_pages_view(),
        "current_page_workspace": ledger.model_view(current_page),
        "known_page_connections": list(host.protocol_map.connections[-12:]),
        "recent_actions": recent_actions[-8:],
        "pending_action": (
            {
                "source_page": pending.source.page_name,
                "operation": (
                    pending.validated_action.operation
                    if pending.validated_action is not None else ""
                ),
                "target": pending.target,
                "bound_operation_id": str(
                    pending.evidence.get("page_session_operation_id") or ""),
            }
            if pending is not None else None
        ),
        "correction": correction,
        "image_order": (
            ["图1：上一动作前完整截图", "图2：当前最新完整截图"]
            if pending is not None else ["图1：当前最新完整截图"]
        ),
    }
    return (
        f"当前应用：{host.app_name}\n运行平台：{host.platform}\n"
        "以下状态由框架从已保存事件确定性生成；若最新截图已经离开 last_bound_page，"
        "先按截图报告真实 screen，不要把旧页面工作记录写到新页面。\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _previous_assessment(payload: Any) -> tuple[Optional[PreviousAssessment], str]:
    if not isinstance(payload, dict):
        return None, "pending action requires previous_action"
    outcome = str(payload.get("outcome") or "").strip().casefold()
    reason = _text(payload.get("reason"), limit=500)
    matches = payload.get("matches_intent")
    failure = str(payload.get("failure_kind") or "").strip().casefold()
    if outcome not in {"changed", "no_visible_change", "uncertain"} or not reason:
        return None, "previous_action requires a valid outcome and concrete reason"
    if not isinstance(matches, bool):
        return None, "previous_action.matches_intent must be boolean"
    if failure not in {"", "temporarily_unavailable", "not_interactive"}:
        return None, "invalid previous_action.failure_kind"
    return PreviousAssessment(
        outcome=outcome,
        reason=reason,
        matches_intent=matches,
        failure_kind=failure,
    ), ""


def _decision(payload: Any, reason: str) -> tuple[Optional[AutonomousDecision], str, str]:
    if payload is None:
        return None, "", ""
    if not isinstance(payload, dict):
        return None, "", "action must be an object or null"
    safety = str(payload.get("safety") or "").strip().casefold()
    if safety != "safe":
        return None, "", "only actions explicitly classified safe are executable"
    tool_name = str(payload.get("tool_name") or "").strip()
    purpose = str(payload.get("purpose") or "").strip().casefold()
    arguments = payload.get("tool_arguments")
    if not tool_name or not isinstance(arguments, dict):
        return None, "", "action requires tool_name and tool_arguments"
    target = str(
        arguments.get("target")
        or arguments.get("container_hint")
        or arguments.get("operation")
        or ""
    ).strip()
    return AutonomousDecision(
        action="CALL_TOOL",
        target=target,
        point_1000=None,
        direction="",
        reason=reason,
        purpose=purpose,
        tool_name=tool_name,
        tool_arguments=dict(arguments),
    ), purpose, ""


def _register_current_scene(
    host: AutonomousTraversalRuntime, screenshot: bytes, screen: Mapping[str, Any],
) -> tuple[Any, str]:
    variant = screen.get("variant")
    if not isinstance(variant, dict):
        return None, "screen.variant must be an object"
    identity = str(screen.get("identity") or "").strip().casefold()
    variant_identity = str(variant.get("identity") or "").strip().casefold()
    if identity not in {"new", "known"} or variant_identity not in {"new", "known"}:
        return None, "screen and variant identity must be resolved before records or actions"
    page_name = _text(screen.get("name"), limit=160)
    summary = _text(screen.get("summary"), limit=500)
    variant_name = _text(variant.get("name"), limit=160)
    predicates = variant.get("visible_predicates")
    if not page_name or not summary or not variant_name or not isinstance(predicates, list):
        return None, "screen requires name, summary, Variant and visible predicates"
    canonical, issue = host.protocol_map.observe(
        name=page_name,
        summary=summary,
        identity=identity,
        matched_page_name=page_name if identity == "known" else "",
        surface_kind=str(screen.get("surface_kind") or "other"),
        regions=[],
        screenshot=screenshot,
        variant_name=variant_name,
        variant_identity=variant_identity,
        visible_predicates=[str(item) for item in predicates],
        commit_regions=False,
    )
    if issue:
        return None, issue
    dummy_turn = AutonomousTurn(
        screen_name=canonical,
        previous=PreviousAssessment("not_applicable", ""),
        decision=AutonomousDecision("NONE", "", None, "", ""),
        registration=SurfaceRegistration(
            identity=identity,
            matched_page_name=(canonical if identity == "known" else ""),
            variant_name=variant_name,
            variant_identity=variant_identity,
            visible_predicates=[str(item) for item in predicates],
        ),
    )
    return _register_scene(host, screenshot, dummy_turn, canonical), ""


def _materialize_page_records(
    host: AutonomousTraversalRuntime,
    ledger: PageSessionLedger,
    page_name: str,
    screenshot: bytes,
    state_id: str,
) -> None:
    page = ledger.pages[_page_key(page_name)]
    frame_id = screenshot_frame_id(screenshot)
    region_state = host.region_states.setdefault(
        _page_key(page_name), AutonomousRegionState())
    region_state.observe_frame(frame_id, state_id)
    region_state.apply_agent_update([
        {
            "name": region["name"],
            "summary": region["summary"],
            "coverage_complete": False,
        }
        for region in page.get("regions") or []
    ], frame_id=frame_id)
    host.protocol_map.upsert_regions(page_name, page.get("regions") or [])
    for region in page.get("regions") or []:
        region_ref, _merged = host.region_registry.bind(
            page_name=page_name,
            region_name=region["name"],
            state_id=state_id,
            variant_name=host.protocol_map.current_variant,
            summary=region["summary"],
            reason="main Agent page-session record",
        )
        region_state.set_region_ref(
            region["name"], region_ref,
            reason="main Agent page-session record",
        )
    discovery_path = host.writer.save_screenshot(state_id, screenshot)
    for operation in page.get("operations") or []:
        if operation.get("status") == "cancelled":
            continue
        region_ref = host.region_registry.region_ref(
            page_name, operation["region_name"])
        occurrence_ref = host.region_registry.occurrence_ref(
            page_name, operation["region_name"])
        delta = host.entry_ledger.record_agent_update(
            page_name=page_name,
            region_name=operation["region_name"],
            frame_id=frame_id,
            source_state_id=state_id,
            owner_region_ref=region_ref,
            representative_occurrence_ref=occurrence_ref,
            discovery_screenshot_path=discovery_path,
            observations=[{
                "operation": operation["operation"],
                "subject": operation["target"],
                "target": operation["target"],
                "control_type": (
                    "input" if _page_key(operation["operation"])
                    == "input_text" else "control"
                ),
                "exploration_policy": (
                    "record_only" if operation.get("status") == "recorded"
                    else "explore"
                ),
            }],
        )
        entry_id = next(iter(delta.added or delta.matched), "")
        if not entry_id:
            entry = next((
                item for item in host.entry_ledger.entries
                if _page_key(item.page_name) == _page_key(page_name)
                and _page_key(item.region_name) == _page_key(operation["region_name"])
                and _page_key(item.operation) == _page_key(operation["operation"])
                and _page_key(item.target) == _page_key(operation["target"])
            ), None)
            entry_id = entry.entry_id if entry is not None else ""
        operation["entry_id"] = entry_id


def _save_checkpoint(
    host: AutonomousTraversalRuntime,
    ledger: PageSessionLedger,
    history: Sequence[Dict[str, Any]],
) -> None:
    _checkpoint(host, history)
    ledger.save(host)


def _settle_page_session_action(
    host: AutonomousTraversalRuntime,
    pending: PendingAction,
    scene: Any,
    assessment: PreviousAssessment,
    history: List[Dict[str, Any]],
) -> None:
    """Commit factual action evidence without invoking old task semantics."""
    _commit_pending(
        host,
        pending,
        scene,
        assessment,
        history,
        actual_target=pending.target,
    )
    if pending.entry_action_id:
        host.entry_ledger.finish_action(
            pending.entry_action_id,
            action_executed=True,
            outcome_verified=(
                assessment.matches_intent
                and assessment.outcome in {"changed", "no_visible_change"}
            ),
            result=assessment.reason,
            destination_page=scene.page_name,
            destination_state_id=scene.state_id,
        )
    if (
        assessment.outcome == "changed"
        and _page_key(pending.source.page_name) != _page_key(scene.page_name)
    ):
        host.protocol_map.connect(
            pending.source.page_name,
            scene.page_name,
            str(pending.primitive.get("action_type") or ""),
            pending.target,
        )


def _completion_summary(ledger: PageSessionLedger) -> Dict[str, Any]:
    return {
        "mode": "page_session_experiment",
        "verification": "agent_declared_not_framework_certified",
        "pages": [{
            "page_name": page["page_name"],
            "status": page.get("status", "active"),
            "todos": len(page.get("todos") or []),
            "operations": len(page.get("operations") or []),
            "verified_operations": sum(
                item.get("status") == "verified"
                for item in page.get("operations") or []
            ),
        } for page in ledger.pages.values()],
    }


def run_page_session_traversal(
    host: AutonomousTraversalRuntime, initial_obs: Dict[str, Any],
):
    """Run the experimental single-Agent current-page notebook controller."""
    observation = initial_obs
    history: List[Dict[str, Any]] = list(host.resume_history)
    ledger = PageSessionLedger.load(os.path.join(
        host.output_root, "autonomous_page_sessions.json"))
    pending: Optional[PendingAction] = None
    correction = ""
    stalled_turns = 0
    backend_errors = 0
    host.audit_fixture(None, "initial")

    while True:
        if stalled_turns >= 5:
            host.graph.stop_reason = "page_session_stalled"
            break
        screenshot = (observation or {}).get("screenshot")
        if not screenshot:
            host.graph.stop_reason = "observation_unavailable"
            break
        if host.max_actions > 0 and pending is None and host.action_count >= host.max_actions:
            host.graph.stop_reason = "max_actions"
            break

        scope_status, recovered = _handle_outside_target_app(
            host, pending, history, screenshot)
        if scope_status == "stopped":
            break
        if scope_status == "recovered":
            observation = recovered or observation
            pending = None
            _save_checkpoint(host, ledger, history)
            continue
        scope_unknown = scope_status == "needs_review"
        catalog = action_tool_catalog(platform=host.platform)
        schema = page_session_response_schema(
            catalog, has_previous=pending is not None)
        prompt = _build_prompt(
            host, ledger, history,
            pending=pending,
            correction=correction,
            scope_unknown=scope_unknown,
        )
        screenshots = (
            [pending.source.screenshot, screenshot]
            if pending is not None else [screenshot]
        )
        try:
            payload = host.decision_agent.invoke_specialist(
                tool_name="page_session_main_agent",
                prompt=prompt,
                screenshots=screenshots,
                response_schema=schema,
                system_prompt=PAGE_SESSION_PROMPT,
            )
        except Exception as exc:
            backend_errors += 1
            correction = f"模型调用失败：{str(exc)[:300]}"
            history.append({
                "kind": "page_session_error",
                "outcome": "backend_error",
                "detail": correction,
            })
            _save_checkpoint(host, ledger, history)
            if backend_errors >= 3:
                host.graph.stop_reason = "agent_backend_error"
                break
            continue
        backend_errors = 0
        if not isinstance(payload, dict):
            correction = "回复必须是结构化对象"
            stalled_turns += 1
            continue
        reason = _text(payload.get("reason"), limit=500)
        if not reason:
            correction = "reason 必须具体说明本轮截图事实与选择"
            stalled_turns += 1
            continue
        app_scope = str(payload.get("app_scope") or "").strip().casefold()
        if app_scope != "target_app":
            classification = (
                app_scope if app_scope in {"external_app", "uncertain"}
                else "uncertain"
            )
            history.append({
                "kind": "app_scope_resolution",
                "frame_id": screenshot_frame_id(screenshot),
                "outcome": classification,
                "detail": reason,
                "semantic_graph_recorded": False,
            })
            correction = "当前画面未确认为目标应用，框架不会登记或执行动作"
            _save_checkpoint(host, ledger, history)
            continue

        old_page = host.protocol_map.current_page
        screen = payload.get("screen")
        if not isinstance(screen, dict):
            correction = "screen 必须是对象"
            stalled_turns += 1
            continue
        scene, identity_issue = _register_current_scene(host, screenshot, screen)
        if scene is None:
            correction = identity_issue
            history.append({
                "kind": "page_session_rejection",
                "outcome": "identity_rejected",
                "detail": identity_issue,
            })
            stalled_turns += 1
            _save_checkpoint(host, ledger, history)
            continue

        assessment = None
        if pending is not None:
            assessment, assessment_issue = _previous_assessment(
                payload.get("previous_action"))
            if assessment is None:
                correction = assessment_issue
                stalled_turns += 1
                _save_checkpoint(host, ledger, history)
                continue
            pending.assessment = assessment
            _settle_page_session_action(
                host, pending, scene, assessment, history)
            operation_id = str(
                pending.evidence.get("page_session_operation_id") or "")
            if operation_id:
                ledger.settle_operation(
                    pending.source.page_name, operation_id, assessment)
            pending = None

        page_name = scene.page_name
        known_revisit_without_workspace = bool(
            old_page and _page_key(old_page) != _page_key(page_name)
            and ledger.has_page(page_name)
        )
        workspace = payload.get("workspace_update")
        action_payload = payload.get("action")
        if known_revisit_without_workspace:
            has_changes = bool(
                isinstance(workspace, dict)
                and any(workspace.get(name) for name in (
                    "todos", "regions", "operations",
                ))
            )
            if has_changes or action_payload is not None:
                correction = (
                    f"已切换到既有页面 {page_name}；本轮只接受身份，"
                    "下一轮读取该页面状态栏后再更新或操作"
                )
                history.append({
                    "kind": "page_session_switch",
                    "screen": page_name,
                    "outcome": "workspace_reload_required",
                    "detail": correction,
                })
                _save_checkpoint(host, ledger, history)
                continue

        staged, update_issue = ledger.apply(
            page_name,
            str(screen.get("summary") or ""),
            workspace if isinstance(workspace, dict) else {},
            reason=reason,
        )
        if staged is None:
            correction = update_issue
            history.append({
                "kind": "page_session_rejection",
                "screen": page_name,
                "outcome": "workspace_rejected",
                "detail": update_issue,
            })
            stalled_turns += 1
            _save_checkpoint(host, ledger, history)
            continue
        ledger = staged
        _materialize_page_records(
            host, ledger, page_name, screenshot, scene.state_id)

        decision, purpose, decision_issue = _decision(action_payload, reason)
        if decision_issue:
            correction = decision_issue
            stalled_turns += 1
            _save_checkpoint(host, ledger, history)
            continue
        bound_operation = None
        if decision is not None:
            action_operation = (
                str(decision.tool_arguments.get("operation") or "")
                if decision.tool_name == "gesture" else decision.tool_name
            )
            bound_operation = ledger.action_operation(
                page_name, action_operation, decision.target)
        if purpose == "operation_attempt" and bound_operation is None:
            correction = (
                "operation_attempt must uniquely match a current-page "
                "operation by operation + target"
            )
            stalled_turns += 1
            continue
        if decision is not None and bound_operation is not None:
            entry_id = str(bound_operation.get("entry_id") or "")
            if decision.tool_name in {"click", "gesture"}:
                arguments = dict(decision.tool_arguments)
                arguments["entry_id"] = entry_id
                decision = AutonomousDecision(
                    action=decision.action,
                    target=decision.target,
                    point_1000=decision.point_1000,
                    direction=decision.direction,
                    reason=decision.reason,
                    purpose=decision.purpose,
                    tool_name=decision.tool_name,
                    tool_arguments=arguments,
                )

        finish = payload.get("finish_exploration") is True
        if finish:
            gaps = ledger.gaps()
            if gaps:
                correction = "不能结束遍历：" + "；".join(gaps[:8])
                stalled_turns += 1
                _save_checkpoint(host, ledger, history)
                continue
            if decision is not None:
                correction = "结束遍历的同一轮不能再执行新动作"
                stalled_turns += 1
                continue
            host.graph.stop_reason = "agent_declared_complete"
            correction = ""
            _save_checkpoint(host, ledger, history)
            break

        if decision is None:
            history.append({
                "kind": "page_session_update",
                "screen": page_name,
                "outcome": "recorded",
                "detail": reason,
            })
            stalled_turns = 0
            correction = ""
            observation = host.fresh_observation(observation)
            _save_checkpoint(host, ledger, history)
            continue

        if host.max_actions > 0 and host.action_count >= host.max_actions:
            history.append({
                "kind": "page_session_limit",
                "screen": page_name,
                "outcome": "new_action_not_executed",
                "detail": "action budget reached after settling the prior action",
            })
            host.graph.stop_reason = "max_actions"
            _save_checkpoint(host, ledger, history)
            break

        converted, convert_issue = _convert_action_tool(
            host, screenshot, decision, None)
        if converted is None:
            correction = convert_issue
            stalled_turns += 1
            _save_checkpoint(host, ledger, history)
            continue
        if converted.action == "WAIT":
            history.append({
                "kind": "action",
                "screen": page_name,
                "action": "WAIT",
                "target": "wait",
                "outcome": "reobserve",
                "detail": reason,
            })
            observation = host.fresh_observation(observation)
            correction = ""
            _save_checkpoint(host, ledger, history)
            continue
        prepared = _prepare_action_attempt(
            host,
            scene,
            converted,
            screenshot,
            history,
            click_review={},
            previous_tool_review=None,
            bound_entry_id=(
                str(bound_operation.get("entry_id") or "")
                if bound_operation is not None else ""
            ),
        )
        if prepared is None:
            correction = str((history[-1] if history else {}).get("detail") or "动作未能准备")
            stalled_turns += 1
            _save_checkpoint(host, ledger, history)
            continue
        if bound_operation is not None:
            prepared.evidence["page_session_operation_id"] = bound_operation["id"]
            ledger.mark_operation_in_progress(page_name, bound_operation["id"])
            host.graph.update_action_event(
                prepared.event_index, evidence=prepared.evidence)
        try:
            observation = host.env.step(prepared.primitive, pause=2.0)
            if not (observation or {}).get("screenshot"):
                observation = host.fresh_observation(observation or {})
            host.graph.update_action_event(prepared.event_index, outcome="executed")
            host.action_count += 1
            pending = prepared
            correction = ""
            stalled_turns = 0
        except Exception as exc:
            detail = str(exc)[:500]
            host.graph.update_action_event(
                prepared.event_index,
                outcome="execution_error",
                detail=detail,
                landing_verified=False,
                committed=False,
                evidence=prepared.evidence,
            )
            history[prepared.history_index].update({
                "outcome": "execution_error",
                "detail": detail,
            })
            if bound_operation is not None:
                ledger.settle_operation(
                    page_name,
                    bound_operation["id"],
                    PreviousAssessment("uncertain", detail, False),
                )
            observation = host.fresh_observation(observation)
            correction = detail
        _save_checkpoint(host, ledger, history)

    if pending is not None:
        host.graph.update_action_event(
            pending.event_index,
            outcome="assessment_unavailable",
            detail="run stopped before the main Agent settled the executed action",
            landing_verified=False,
            committed=False,
            evidence=pending.evidence,
        )
    host.audit_fixture(None, "final")
    host.graph.autonomous_completion_gaps = ledger.gaps()
    host.graph.autonomous_completion_summary = _completion_summary(ledger)
    _save_checkpoint(host, ledger, history)
    return host.graph


__all__ = [
    "PAGE_SESSION_PROMPT",
    "PageSessionLedger",
    "page_session_response_schema",
    "run_page_session_traversal",
]
