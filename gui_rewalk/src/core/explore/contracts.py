"""Small model-facing response contract and parser."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


ACTIVE_SURFACE_GUIDANCE = '当前可交互前景是无需先关闭、退出或完成其他界面，就能直接执行其自身功能的目标应用内容；它可以同时包含多个 Region。page_report 只清点当前最前景且能直接接收用户交互的目标应用 surface。菜单、弹层、对话框、抽屉、选择器或底部面板接管输入时，被该 surface 接管的背景只作为截图上下文，不登记为当前 State 的 Region、Element 或 Operation；点击背景只能关闭前景，不表示背景正在执行自己的功能。判断依据是输入职责，不是变暗程度、面积或位置。没有 surface 接管输入时，仍可直接交互的持久导航栏、工具栏或侧栏继续登记。只登记目标应用；系统栏、键盘、桌面、虚拟机/浏览器外壳和其他应用不是Region；目标应用前景窗口可以是父容器。'


CONTROL_ACTION_GUIDANCE = (
    "operations登记控件支持的能力，不是本轮执行计划。新控件至少一种动作；"
    "当前前景内的禁用控件仍保留支持的动作并用defer，已选中用record，不执行；被模态接管的背景不适用此规则。"
    "不能要求禁用的新控件把operations删为空；只有已有控件补观察可省略动作。"
    "明确静态内容写Region summary，不建Element或编造动作。"
)


REFINEMENT_SCHEMA = {
    'description': '可选的观察工具，普通轮null。新证据证明旧区块过粗时，从分区修正候选卡引用occurrence_ref及完整具体element_refs，提取同一独立功能组件；必须含当前State，首项为跨State身份基准。原区块保留为父容器，其余内容不动，历史证据不改。仅已确认当前位置且无pending可用，screen可为null沿用位置，若填写必须known且与当前位置一致；同轮action/page_report/previous_action=null，next_operation_ref为空。不能因名称相似强拆或借修正重置预算。历史目录不证明当前可交互。',
    'type': ['object', 'null'],
    'properties': {
        'name': {'type': 'string'}, 'summary': {'type': 'string'},
        'reason': {'type': 'string'},
        'sources': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'occurrence_ref': {'type': 'string'},
                'element_refs': {'type': 'array', 'items': {'type': 'string'}},
            }, 'required': ['occurrence_ref', 'element_refs'], 'additionalProperties': False,
        }},
    }, 'required': ['name', 'summary', 'reason', 'sources'], 'additionalProperties': False,
}

APP_SCOPES = frozenset({"target_app", "external_app", "uncertain"})
SCREEN_IDENTITIES = frozenset({
    "new_page", "new_state", "known", "uncertain",
})
OPERATION_HANDLING = frozenset({"explore", "record", "defer"})
HANDLING_GUIDANCE = (
    "可见/启用是视觉事实，不等于获准执行。explore是待调查义务，不是立即投递授权；"
    "record只保存观察，不算交互验证，也不表示禁用；安全规范禁止探测的风险操作仍只记录。"
    "defer是仍欠验证但当前前提、资格或本批范围不满足，须给具体reason；可见启用也可暂缓。"
    "reason是待核对解释，框架scope才是权威范围；理由不能自行增加禁令或扩大权限。"
    "eligible是当前前提及范围内的执行资格，审核true不覆盖门禁。"
    "普通纵向up/down scroll登记为record；仍有未见内容由survey_complete=false及清点任务表达，可继续安全调查滚动，不要求改为explore。"
    "横向翻卡或分页改变功能结构才可explore。"
    "重启/换图/新路线不解除限制。验证必须有真实动作与结果证据。"
)
EDIT_NULL_FIELDS = ("screen", "previous_action", "page_report", "action",
                    "region_refinement", "representative_probe")
EDIT_EMPTY_FIELDS = ("context_query", "next_operation_ref", "current_task_result")


def submission_contract(pending_attempt_id="", *, edits=False, correction_field=""):
    if edits:
        return {"phase": "inventory_edits", "null_fields": list(EDIT_NULL_FIELDS),
                "empty_fields": list(EDIT_EMPTY_FIELDS),
                "instruction": "本轮只提交page_report_edits；app_scope=target_app，screen/previous_action/page_report/action=null，不查询或切换任务。"
                    "位置、回执和清单仅暂存，尚未最终准入。路径只按当前候选。"
                    "若位置或回执也需重判，先用全部提交字段null（含page_report_edits）、reason说明退出编辑；"
                    "框架切换到重新观察阶段，下一轮再提交位置/回执。",
                "executed_attempt": pending_attempt_id}
    return {"phase": "settlement" if pending_attempt_id else "observe_act",
            "instruction": "本轮没有可编辑的同帧候选，page_report_edits=null；清单有误时提交完整修正page_report。"
                "app_scope=target_app时screen描述最新观察；" + (
                f"previous_action必须结算{pending_attempt_id}，不得重放已执行动作。"
                if pending_attempt_id else "没有待结算动作，previous_action必须为null。") + (
                "纠正报告时action=null，只修改当前错误及直接依赖。" if correction_field else ""),
            "executed_attempt": pending_attempt_id}


def validate_edit_submission(raw):
    conflicts = {key: raw[key] for key in EDIT_NULL_FIELDS if raw.get(key) is not None}
    conflicts.update({key: raw[key] for key in EDIT_EMPTY_FIELDS if raw.get(key) not in (None, "")})
    edits = raw.get("page_report_edits")
    if raw.get("app_scope") != "target_app":
        conflicts["app_scope"] = raw.get("app_scope")
    if edits is not None and (not isinstance(edits, list) or not 1 <= len(edits) <= 64):
        conflicts["page_report_edits"] = edits
    if conflicts:
        from .settlement import SettlementContractError
        raise SettlementContractError(code="PAGE_REPORT_EDIT_CONTRACT", field_path="page_report_edits",
            expected=submission_contract(edits=True)["instruction"],
            received=json.dumps({key: {'type': type(value).__name__, 'value': repr(value)[:120]}
                                 for key, value in conflicts.items()}, ensure_ascii=False),
            message="冲突字段=" + ", ".join(conflicts) + "；整批编辑未应用，缓存候选未变化")
PARAMETER_STATUSES = frozenset({"unknown", "none", "observed"})
ACTION_KINDS = frozenset({
    "click", "double_click", "right_click", "long_press", "input_text",
    "hover", "scroll", "back", "wait",
})
ACTION_PURPOSES = frozenset({"survey", "execute", "route", "recover"})
ACTION_OUTCOMES = frozenset({"success", "no_effect", "failed", "uncertain"})
TASK_RESULTS = frozenset({"completed", "retry", "deferred", "failed", "unchanged"})
CURRENT_TASK_RESULTS = frozenset({"deferred", "failed"})


class ReportCorrectionExhausted(ValueError):
    """The current report and its reviewers have used their correction budget."""


@dataclass
class ReportCorrections:
    count: int = 0
    required_report: bool = False
    events: List[Dict[str, Any]] = field(default_factory=list)
    limit: int = field(default=3, init=False)

    def reject(self, error: Exception, recipient: str) -> bool:
        if self.count < self.limit:
            self.count += 1
            self.events.append({"round": self.count, "limit": self.limit,
                                "recipient": recipient, "required_change": str(error),
                                "resolved": False, "phase": "rejected"})
        return self.count < self.limit

    def reset(self) -> None:
        self.count = 0
        self.required_report = False
        self.events.clear()


def _text(value: Any, *, required: bool = False, limit: int = 600, name: str = "text") -> str:
    text = " ".join(str(value or "").split()).strip()
    if required and not text:
        raise ValueError(f"{name}: required text is empty；请补充该字段，不要修改其他已确认事实。")
    return text[:limit]


def _array(value: Any, name: str) -> List[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


@dataclass(frozen=True)
class ScreenReport:
    identity: str
    page_ref: str
    page_name: str
    page_summary: str
    state_ref: str
    state_name: str
    state_summary: str


@dataclass(frozen=True)
class OperationReport:
    action: str
    target: str
    handling: str
    reason: str
    direction: str = ""
    parameter_status: str = "unknown"
    parameter_summary: str = ""
    operation_ref: str = ""


@dataclass(frozen=True)
class ElementReport:
    name: str
    operations: Sequence[OperationReport]
    element_ref: str = ""
    observation: str = ""


@dataclass(frozen=True)
class RegionReport:
    name: str
    summary: str
    elements: Sequence[ElementReport]
    region_operations: Sequence[OperationReport]
    memory: str = ""
    region_ref: str = ""
    parent_ref: str | int | None = None


@dataclass(frozen=True)
class PageReport:
    regions: Sequence[RegionReport]
    survey_complete: bool
    coverage_note: str


@dataclass(frozen=True)
class RepresentativeProbe:
    operation_ref: str
    goal: str
    member_owner_refs: Sequence[str]
    representative_owner_refs: Sequence[str]


@dataclass(frozen=True)
class CompletedElementAction:
    element_ref: str
    action: str
    completed: bool


@dataclass(frozen=True)
class CompletedRegionAction:
    region_ref: str
    action: str
    completed: bool
    direction: str = ""


@dataclass(frozen=True)
class FunctionInfoUpdate:
    region_ref: str
    memory: str


@dataclass(frozen=True)
class ParameterInfoUpdate:
    status: str
    summary: str


@dataclass(frozen=True)
class PreviousActionReport:
    attempt_ref: str
    reason: str
    element_actions: Sequence[CompletedElementAction] = ()
    region_actions: Sequence[CompletedRegionAction] = ()
    function_info: Sequence[FunctionInfoUpdate] = ()
    parameter_info: Optional[ParameterInfoUpdate] = None
    outcome: str = ""
    task_result: str = ""
    visible_result: str = ""
    corrected_target: str = ""
    representative_same_kind: Optional[bool] = None
    region_effects: Optional[Sequence[Mapping[str, Any]]] = None


@dataclass(frozen=True)
class ActionRequest:
    kind: str
    purpose: str
    target: str
    point_1000: Optional[Sequence[float]]
    text: str
    direction: str
    amount: int
    operation_ref: str
    owner_ref: str = ""


@dataclass(frozen=True)
class AgentTurn:
    app_scope: str
    strategy: str
    screen: Optional[ScreenReport]
    previous_action: Optional[PreviousActionReport]
    page_report: Optional[PageReport]
    action: Optional[ActionRequest]
    current_task_result: str
    reason: str
    representative_probe: Optional[RepresentativeProbe] = None
    next_operation_ref: str = ""
    region_refinement: Optional[Dict[str, Any]] = None
    context_query: str | Dict[str, str] = ""
    page_report_edits: Optional[Sequence[Mapping[str, Any]]] = None


def _parse_context_query(raw: Any) -> str | Dict[str, str]:
    if raw is None or isinstance(raw, str):
        return _text(raw, limit=200)
    if not isinstance(raw, Mapping):
        raise ValueError("context_query must be a string or structured query")
    result = {}
    for key in ("label", "function", "region", "action", "state_ref", "region_ref"):
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"context_query.{key} must be a string")
        result[key] = _text(value, limit=200 if key in {"label", "function", "region"} else 40)
    if result["action"] and result["action"] not in ACTION_KINDS:
        raise ValueError("context_query.action must be a supported action or empty")
    return result if any(result.values()) else ""


def _parse_screen(raw: Any) -> Optional[ScreenReport]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("screen must be an object or null")
    identity = _text(raw.get("identity"), required=True, limit=30, name="screen.identity").casefold()
    if identity not in SCREEN_IDENTITIES:
        raise ValueError(f"screen.identity={identity!r} is invalid；请使用 {sorted(SCREEN_IDENTITIES)}。")
    report = ScreenReport(
        identity=identity,
        page_ref=_text(raw.get("page_ref"), limit=40),
        page_name=_text(raw.get("page_name"), required=True, limit=160, name="screen.page_name"),
        page_summary=_text(raw.get("page_summary"), required=True, name="screen.page_summary"),
        state_ref=_text(raw.get("state_ref"), limit=40),
        state_name=_text(raw.get("state_name"), required=True, limit=160, name="screen.state_name"),
        state_summary=_text(raw.get("state_summary"), required=True, name="screen.state_summary"),
    )
    if identity == "known" and (not report.page_ref or not report.state_ref):
        raise ValueError("known screen requires page_ref and state_ref")
    if identity == "new_state" and not report.page_ref:
        raise ValueError("new_state requires page_ref")
    return report


def _parse_page_report(raw: Any) -> Optional[PageReport]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("page_report must be an object or null")
    regions: List[RegionReport] = []
    for region_index, region_raw in enumerate(_array(raw.get("regions"), "page_report.regions")):
        region_path = f"page_report.regions[{region_index}]"
        if not isinstance(region_raw, Mapping):
            raise ValueError(f"{region_path}: each Region must be an object")
        if "region_ref" not in region_raw:
            raise ValueError(f"{region_path}.region_ref is required；已知区块复制已有 r，新候选填空字符串。")
        parent_ref = region_raw.get("parent_ref")
        if (parent_ref is not None and (isinstance(parent_ref, bool)
                or not isinstance(parent_ref, (str, int))
                or isinstance(parent_ref, int) and parent_ref < 0)):
            raise ValueError(f"{region_path}.parent_ref must be a Region ref, report index, or null")
        def parse_operation(
            operation_raw: Any,
            *,
            owner: str,
            path: str,
        ) -> OperationReport:
            if not isinstance(operation_raw, Mapping):
                raise ValueError(f"{path}: each operation must be an object")
            if "operation_ref" not in operation_raw:
                raise ValueError(f"{path}.operation_ref is required；已知操作复制已有 co，新候选填空字符串。")
            action = _text(
                operation_raw.get("action"), required=True, limit=30,
                name=f"{path}.action",
            ).casefold()
            direction = _text(
                operation_raw.get("direction"), limit=20,
            ).casefold()
            handling = _text(
                operation_raw.get("handling"), required=True, limit=30,
                name=f"{path}.handling",
            ).casefold()
            if (owner == "region"
                    and action == "scroll"
                    and direction in {"up", "down"}
                    and handling == "survey"):
                handling = "record"
            if handling not in OPERATION_HANDLING:
                raise ValueError(f"{path}.handling={handling!r} is invalid；请使用 {sorted(OPERATION_HANDLING)}。")
            if not _text(operation_raw.get("parameter_status")):
                raise ValueError(f"{path}.parameter_status is required；未确认参数时填 unknown。")
            if not _text(operation_raw.get("parameter_summary")):
                raise ValueError(f"{path}.parameter_summary is required；填写已观察的参数信息或明确尚未确认，不要编造值域。")
            parameter_status = _text(
                operation_raw.get("parameter_status"), limit=30,
            ).casefold()
            if parameter_status not in PARAMETER_STATUSES:
                raise ValueError(f"{path}.parameter_status={parameter_status!r} is invalid；请使用 {sorted(PARAMETER_STATUSES)}，未观察到值域时用 unknown。")
            if action not in ACTION_KINDS:
                raise ValueError(f"{path}.action={action!r} is invalid；请使用 {sorted(ACTION_KINDS)}。")
            if owner == "element" and action in {"scroll", "back", "wait"}:
                raise ValueError(
                    f"{path}: Element operation must start from the Element; "
                    "scroll/back/wait are not Element operations")
            if owner == "region":
                if action != "scroll":
                    raise ValueError(
                        f"{path}.action={action!r}: Region operation currently supports only scroll；控件动作应放在所属 Element 的 operations 中。")
                if direction not in {"up", "down", "left", "right"}:
                    raise ValueError(
                        f"{path}.direction={direction!r}: Region scroll operation requires a valid direction，请使用 up/down/left/right。")
            return OperationReport(
                action=action,
                target=_text(operation_raw.get("target"), required=True, limit=200, name=f"{path}.target"),
                handling=handling,
                reason=_text(operation_raw.get("reason"), required=True, name=f"{path}.reason"),
                direction=direction,
                parameter_status=parameter_status,
                parameter_summary=_text(
                    operation_raw.get("parameter_summary"),
                    required=True,
                    name=f"{path}.parameter_summary",
                ),
                operation_ref=_text(
                    operation_raw.get("operation_ref"), limit=40),
            )

        elements: List[ElementReport] = []
        for element_index, element_raw in enumerate(_array(
                region_raw.get("elements"), f"{region_path}.elements")):
            element_path = f"{region_path}.elements[{element_index}]"
            if not isinstance(element_raw, Mapping):
                raise ValueError(f"{element_path}: each Element must be an object")
            if "element_ref" not in element_raw:
                raise ValueError(f"{element_path}.element_ref is required；已知控件复制已有 el，新候选填空字符串。")
            element_operations = [
                parse_operation(item, owner="element", path=f"{element_path}.operations[{index}]")
                for index, item in enumerate(_array(
                    element_raw.get("operations"), f"{element_path}.operations"))
            ]
            element_ref = _text(element_raw.get("element_ref"), limit=40)
            if not element_ref and not element_operations:
                from .settlement import SettlementContractError
                raise SettlementContractError(
                    code="PAGE_REPORT_INVALID", field_path=f"{element_path}.operations",
                    expected="new control with at least one action", received="empty operations",
                    message="新控件须登记支持的动作，不表示本轮执行；已选中控件保留动作并用record，不重复点击。容器或组合功能写Region，独立落点分Element；若为静态文字或读数，移入所属Region summary并移除此新Element，不编造动作，不改无关分区")
            elements.append(ElementReport(
                name=_text(
                    element_raw.get("name"), required=True, limit=200, name=f"{element_path}.name"),
                operations=element_operations,
                element_ref=element_ref,
                observation=_text(element_raw.get("observation")),
            ))
        region_operations = [
            parse_operation(item, owner="region", path=f"{region_path}.region_operations[{index}]")
            for index, item in enumerate(_array(
                region_raw.get("region_operations"),
                f"{region_path}.region_operations",
            ))
        ]
        regions.append(RegionReport(
               name=_text(region_raw.get("name",
           ), required=True, limit=160, name=f"{region_path}.name"),
            summary=_text(region_raw.get("summary"), required=True, name=f"{region_path}.summary"),
            elements=elements,
            region_operations=region_operations,
            memory=_text(region_raw.get("memory")),
            region_ref=_text(region_raw.get("region_ref"), limit=40),
            parent_ref=parent_ref,
        ))
    survey_complete = raw.get("survey_complete")
    if not isinstance(survey_complete, bool):
        raise ValueError("page_report.survey_complete must be boolean")
    return PageReport(
        regions=regions,
        survey_complete=survey_complete,
        coverage_note=_text(raw.get("coverage_note"), required=True, name="page_report.coverage_note"),
    )


def _parse_previous(raw: Any) -> Optional[PreviousActionReport]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("previous_action must be an object or null")
    if "satisfied_operation_refs" in raw:
        raise ValueError("previous_action.satisfied_operation_refs is retired；仅回填实际执行的element_actions/region_actions，不能批量给其他任务记功。")
    if any(key in raw for key in (
            "element_actions", "region_actions", "function_info")):
        element_actions: List[CompletedElementAction] = []
        for item_index, item in enumerate(_array(
                raw.get("element_actions", []),
                "previous_action.element_actions")):
            item_path = f"previous_action.element_actions[{item_index}]"
            if not isinstance(item, Mapping):
                raise ValueError(f"{item_path}: each completed Element action must be an object")
            action = _text(item.get("action"), required=True, limit=30, name=f"{item_path}.action").casefold()
            if action not in ACTION_KINDS - {"scroll", "back", "wait"}:
                raise ValueError(f"{item_path}.action={action!r}: completed Element action is invalid；请使用待结算动作的真实 kind，不要把滚动报成 Element 动作。")
            completed = item.get("completed")
            if not isinstance(completed, bool):
                raise ValueError(f"{item_path}: completed Element action requires boolean completed")
            element_actions.append(CompletedElementAction(
                element_ref=_text(
                    item.get("element_ref"), required=True, limit=40, name=f"{item_path}.element_ref"),
                action=action,
                completed=completed,
            ))
        region_actions: List[CompletedRegionAction] = []
        for item_index, item in enumerate(_array(
                raw.get("region_actions", []),
                "previous_action.region_actions")):
            item_path = f"previous_action.region_actions[{item_index}]"
            if not isinstance(item, Mapping):
                raise ValueError(f"{item_path}: each completed Region action must be an object")
            action = _text(item.get("action"), required=True, limit=30, name=f"{item_path}.action").casefold()
            direction = _text(item.get("direction"), limit=20).casefold()
            if action != "scroll" or direction not in {
                    "up", "down", "left", "right"}:
                raise ValueError(f"{item_path}: completed Region action must be a directed scroll；收到 action={action!r}, direction={direction!r}，请与待结算动作的 scroll 和方向一致。")
            completed = item.get("completed")
            if not isinstance(completed, bool):
                raise ValueError(f"{item_path}: completed Region action requires boolean completed")
            region_actions.append(CompletedRegionAction(
                region_ref=_text(
                    item.get("region_ref"), required=True, limit=40, name=f"{item_path}.region_ref"),
                action=action,
                completed=completed,
                direction=direction,
            ))
        function_info: List[FunctionInfoUpdate] = []
        for item_index, item in enumerate(_array(
                raw.get("function_info", []),
                "previous_action.function_info")):
            item_path = f"previous_action.function_info[{item_index}]"
            if not isinstance(item, Mapping):
                raise ValueError(f"{item_path}: each function_info item must be an object")
            function_info.append(FunctionInfoUpdate(
                region_ref=_text(
                    item.get("region_ref"), required=True, limit=40, name=f"{item_path}.region_ref"),
                memory=_text(item.get("memory"), required=True, name=f"{item_path}.memory"),
            ))
        parameter_info_raw = raw.get("parameter_info")
        parameter_info = None
        if parameter_info_raw is not None:
            if not isinstance(parameter_info_raw, Mapping):
                raise ValueError(
                    "previous_action.parameter_info must be an object or null")
            status = _text(
                parameter_info_raw.get("status"), required=True, limit=30,
                name="previous_action.parameter_info.status",
            ).casefold()
            if status not in {"none", "observed"}:
                raise ValueError(
                    f"previous_action.parameter_info.status={status!r} is invalid；仅填写 none 或 observed；尚未确认参数时 parameter_info 留 null。")
            parameter_info = ParameterInfoUpdate(
                status=status,
                summary=_text(
                    parameter_info_raw.get("summary"), required=True, name="previous_action.parameter_info.summary"),
            )
        if "region_effects" in raw and any(not isinstance(item, Mapping) for item in
                _array(raw["region_effects"], "previous_action.region_effects")):
            raise ValueError("previous_action.region_effects must contain objects")
        representative_same_kind = raw.get("representative_same_kind")
        if (representative_same_kind is not None
                and not isinstance(representative_same_kind, bool)):
            raise ValueError(
                "previous_action.representative_same_kind must be boolean "
                "or null")
        return PreviousActionReport(
            attempt_ref=_text(raw.get("attempt_ref"), required=True, limit=40, name="previous_action.attempt_ref"),
            reason=_text(raw.get("reason"), required=True, name="previous_action.reason"),
            element_actions=tuple(element_actions),
            region_actions=tuple(region_actions),
            function_info=tuple(function_info),
            parameter_info=parameter_info,
            representative_same_kind=representative_same_kind,
            region_effects=(tuple(_array(raw["region_effects"], "previous_action.region_effects"))
                            if "region_effects" in raw else None),
        )

    # Legacy parser support for saved fixtures. The live schema no longer
    # exposes these task-centric fields to the model.
    outcome = _text(raw.get("outcome"), required=True, limit=30, name="previous_action.outcome").casefold()
    task_result = _text(
        raw.get("task_result"), required=True, limit=30,
        name="previous_action.task_result",
    ).casefold()
    if outcome not in ACTION_OUTCOMES:
        raise ValueError(f"previous_action.outcome={outcome!r} is invalid；旧记录仅接受 {sorted(ACTION_OUTCOMES)}。")
    if task_result not in TASK_RESULTS:
        raise ValueError(f"previous_action.task_result={task_result!r} is invalid；旧记录仅接受 {sorted(TASK_RESULTS)}。")
    if (task_result == "completed"
            and outcome not in {"success", "no_effect"}):
        raise ValueError(
            "previous_action.task_result=completed requires outcome=success "
            "or conclusive no_effect evidence"
        )
    return PreviousActionReport(
        attempt_ref=_text(raw.get("attempt_ref"), required=True, limit=40, name="previous_action.attempt_ref"),
        outcome=outcome,
        task_result=task_result,
        visible_result=_text(raw.get("visible_result"), required=True, name="previous_action.visible_result"),
        corrected_target=_text(raw.get("corrected_target"), limit=200),
        reason=_text(raw.get("reason"), required=True, name="previous_action.reason"),
    )


def _parse_representative_probe(raw: Any) -> Optional[RepresentativeProbe]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("representative_probe must be an object or null")
    member_refs = [
        _text(item, required=True, limit=40, name="representative_probe.member_owner_refs[]")
        for item in _array(
            raw.get("member_owner_refs"),
            "representative_probe.member_owner_refs",
        )
    ]
    if (not 2 <= len(member_refs) <= 32
            or len(set(member_refs)) != len(member_refs)):
        raise ValueError(
            "representative_probe requires 2..32 distinct member refs")
    owner_refs = [
        _text(item, required=True, limit=40, name="representative_probe.representative_owner_refs[]")
        for item in _array(
            raw.get("representative_owner_refs"),
            "representative_probe.representative_owner_refs",
        )
    ]
    if len(owner_refs) != 2 or len(set(owner_refs)) != 2:
        raise ValueError(
            "representative_probe requires exactly two distinct owner refs")
    if not set(owner_refs).issubset(member_refs):
        raise ValueError(
            "representative owners must belong to member_owner_refs")
    return RepresentativeProbe(
        operation_ref=_text(
            raw.get("operation_ref"), required=True, limit=40, name="representative_probe.operation_ref"),
        goal=_text(raw.get("goal"), required=True, name="representative_probe.goal"),
        member_owner_refs=tuple(member_refs),
        representative_owner_refs=tuple(owner_refs),
    )


def _parse_action(raw: Any) -> Optional[ActionRequest]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("action must be an object or null")
    kind = _text(raw.get("kind"), required=True, limit=30, name="action.kind").casefold()
    purpose = _text(raw.get("purpose"), limit=30).casefold()
    if kind not in ACTION_KINDS:
        raise ValueError(f"action.kind={kind!r} is invalid；请使用 {sorted(ACTION_KINDS)}。")
    if purpose and purpose not in ACTION_PURPOSES:
        raise ValueError(f"action.purpose={purpose!r} is invalid；当前协议不需要填写 purpose，由框架推导。")
    point = raw.get("point_1000")
    if point is not None:
        if (not isinstance(point, list) or len(point) != 2
                or not all(isinstance(value, (int, float))
                           and 0 <= float(value) <= 1000 for value in point)):
            raise ValueError("action.point_1000 must be [x,y] in 0..1000 or null")
        point = [float(point[0]), float(point[1])]
        if (max(point) <= 1.0
                and any(value not in {0.0, 1.0} for value in point)):
            raise ValueError(
                f"action.point_1000={point!r} uses an ambiguous 0..1 coordinate scale；请按整张最新截图的 0..1000 尺度填写 [x,y]，不是像素或 0..1 比例。")
    targeted = kind in {
        "click", "double_click", "right_click", "long_press", "input_text",
        "hover", "scroll",
    }
    if targeted and point is None:
        raise ValueError(f"{kind} requires point_1000")
    direction = _text(raw.get("direction"), limit=20).casefold()
    if kind == "scroll" and direction not in {"up", "down", "left", "right"}:
        raise ValueError(f"action.direction={direction!r}：scroll requires a valid direction，请填 up/down/left/right。")
    amount_raw = raw.get("amount")
    if amount_raw is None:
        amount_raw = 650
    if not isinstance(amount_raw, int) or not 1 <= amount_raw <= 1000:
        raise ValueError("action.amount must be an integer in 1..1000")
    return ActionRequest(
        kind=kind,
        purpose=purpose,
        target=_text(raw.get("target"), limit=200),
        point_1000=point,
        text=str(raw.get("text") or "")[:200],
        direction=direction,
        amount=amount_raw,
        operation_ref=_text(raw.get("operation_ref"), limit=40),
        owner_ref=_text(raw.get("owner_ref"), limit=40),
    )


def parse_turn(
    raw: Mapping[str, Any],
    *,
    has_pending_action: bool,
    pending_attempt_id: str = "",
    submission: Optional[Mapping[str, Any]] = None,
) -> AgentTurn:
    if not isinstance(raw, Mapping):
        raise ValueError("response must be one JSON object")
    app_scope = _text(raw.get("app_scope"), required=True, limit=30, name="app_scope").casefold()
    if app_scope not in APP_SCOPES:
        raise ValueError(f"app_scope={app_scope!r} is invalid；请使用 {sorted(APP_SCOPES)}。")
    edits = raw.get("page_report_edits")
    if edits is not None and submission is not None and submission.get('phase') != 'inventory_edits':
        from .settlement import SettlementContractError
        raise SettlementContractError(code='PAGE_REPORT_EDIT_UNAVAILABLE', field_path='page_report',
            expected=submission['instruction'], received='page_report_edits without a current repair candidate',
            message='本轮未提供可编辑候选；不要改成交纯edits，提交完整修正报告及本轮要求的位置/真实回执')
    if (submission or {}).get("phase") == "inventory_edits":
        validate_edit_submission(raw)
        if edits is None:
            return AgentTurn(app_scope=app_scope,
                strategy=_text(raw.get("strategy"), required=True, limit=240, name="strategy"),
                screen=None, previous_action=None, page_report=None, action=None, current_task_result="",
                reason=_text(raw.get("reason"), required=True, name="reason"))
    if edits is not None:
        validate_edit_submission(raw)
        normalized_edits = []
        from .settlement import SettlementContractError
        for index, edit in enumerate(edits):
            if not isinstance(edit, dict):
                raise SettlementContractError(code='PAGE_REPORT_EDIT_TYPE', field_path=f'page_report_edits[{index}]',
                    expected='edit object', received=repr(edit), message='整批编辑未应用')
            item = {"op": edit.get("op"), "path": edit.get("path")}
            if item["op"] != "remove":
                try:
                    item["value"] = json.loads(edit.get("value_json"))
                except (TypeError, ValueError) as exc:
                    raise SettlementContractError(code='PAGE_REPORT_EDIT_VALUE', field_path=f'page_report_edits[{index}].value_json',
                        expected='JSON encoded value', received=repr(edit.get('value_json'))[:300],
                        message='整批编辑未应用，候选未变化') from exc
            normalized_edits.append(item)
        return AgentTurn(app_scope=app_scope,
            strategy=_text(raw.get("strategy"), required=True, limit=240, name="strategy"),
            screen=None, previous_action=None, page_report=None, action=None, current_task_result="",
            reason=_text(raw.get("reason"), required=True, name="reason"), page_report_edits=normalized_edits)
    current_task_result = _text(
        raw.get("current_task_result"), limit=30,
    ).casefold()
    if current_task_result and current_task_result not in CURRENT_TASK_RESULTS:
        if current_task_result == "completed":
            raise ValueError(
                "current_task_result 不能填 completed；当前协议由框架根据真实动作结算任务。"
                "请移除此字段；有待结算动作时用 previous_action 报告实际效果，"
                "没有待结算动作时 previous_action=null。不要为修正报告重复执行 GUI 动作。"
            )
        raise ValueError("current_task_result 只允许 deferred/failed")
    previous_action = _parse_previous(raw.get("previous_action"))
    action = _parse_action(raw.get("action"))
    if (has_pending_action
            and current_task_result
            and previous_action is not None
            and current_task_result == previous_action.task_result
            and action is None):
        current_task_result = ""
    strategy = _text(raw.get("strategy"), required=True, limit=240, name="strategy")
    screen = _parse_screen(raw.get("screen"))
    try:
        page_report = _parse_page_report(raw.get("page_report"))
    except (TypeError, ValueError) as exc:
        if app_scope == "target_app" and screen is not None and screen.identity != "uncertain":
            # Preserve a parsed proposal, not an accepted location. Runtime
            # still checks its references and binds it only after correction.
            exc.screen_candidate = screen
            exc.page_report_candidate = deepcopy(raw.get("page_report"))
            exc.previous_action_candidate = previous_action
        raise
    turn = AgentTurn(
        app_scope=app_scope,
        strategy=strategy,
        screen=screen,
        previous_action=previous_action,
        page_report=page_report,
        action=action,
        current_task_result=current_task_result,
        reason=_text(raw.get("reason"), required=True, name="reason"),
        next_operation_ref=_text(raw.get("next_operation_ref"), limit=40),
        representative_probe=_parse_representative_probe(
            raw.get("representative_probe")),
        region_refinement=raw.get("region_refinement"),
        context_query=_parse_context_query(raw.get("context_query")),
    )
    if turn.context_query:
        if (turn.app_scope != "target_app" or turn.previous_action is not None
                or turn.action is not None or turn.page_report is not None
                or turn.region_refinement is not None or turn.next_operation_ref
                or turn.representative_probe is not None or turn.current_task_result):
            raise ValueError("context_query is read-only: no action, settlement, inventory, refinement or task switch")
        return turn
    if has_pending_action != (turn.previous_action is not None):
        expected = "an object" if has_pending_action else "null"
        raise ValueError(f"previous_action must be {expected} this round")
    if (turn.previous_action is not None
            and pending_attempt_id
            and turn.previous_action.attempt_ref != pending_attempt_id):
        raise ValueError(
            "previous_action.attempt_ref must equal pending "
            f"{pending_attempt_id}, got {turn.previous_action.attempt_ref}"
        )
    if turn.current_task_result and has_pending_action:
        raise ValueError(
            "current_task_result requires no pending action; settle "
            "previous_action first"
        )
    if turn.current_task_result and turn.action is not None:
        raise ValueError("current_task_result requires action=null")
    if turn.app_scope == "target_app" and turn.screen is None and turn.region_refinement is None:
        raise ValueError("target_app requires a screen report")
    if turn.app_scope != "target_app" and turn.page_report is not None:
        raise ValueError("non-target screen cannot submit page_report")
    if turn.region_refinement is not None:
        if (not isinstance(turn.region_refinement, dict)
                or turn.app_scope != "target_app"
                or (turn.screen is not None and turn.screen.identity != "known")
                or has_pending_action or turn.action is not None
                or turn.page_report is not None or turn.next_operation_ref
                or turn.representative_probe is not None or turn.current_task_result):
            raise ValueError("region_refinement is an observation-only tool: known target screen, no pending/action/page_report/task switch")
    return turn


__all__ = [
    "ACTION_KINDS", "ACTION_PURPOSES", "CURRENT_TASK_RESULTS", "AgentTurn", "ActionRequest",
    "CompletedElementAction", "CompletedRegionAction", "FunctionInfoUpdate",
    "ParameterInfoUpdate",
    "ElementReport", "OperationReport", "PageReport", "PreviousActionReport", "RegionReport",
    "ScreenReport", "parse_turn",
]
