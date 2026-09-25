"""Pure action-tool contracts for screenshot-led autonomous exploration.

This module declares and validates action requests. It deliberately has no GUI
environment, Grounder, Reviewer, or execution callback.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from numbers import Real
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..action_space import is_android

ACTION_TOOL_NAMES = frozenset({
    "click", "input_text", "hover", "scroll", "navigate", "gesture",
})
SCROLL_DIRECTIONS = frozenset({"up", "down", "left", "right"})
NAVIGATION_OPERATIONS = frozenset({"back", "wait"})
GESTURE_OPERATIONS = frozenset({"double_tap", "long_press"})
POINTER_GESTURE_OPERATIONS = frozenset({"double_tap", "long_press"})
TOOL_REVIEW_DECISIONS = frozenset({"accept", "reject", "uncertain"})


CLICK_REVIEW_PROMPT = """\
你是独立点击复核器，只审核主探索 Agent 已经选择的目标与坐标，不规划下一步，也不替它改坐标。
主 Agent 的 target 是需要核验的事实声明，不是要求你设法完成的意图；不得把功能相近、图标相似或能够达到
类似效果的其他控件解释成请求目标。
图1是最新完整截图，用于判断控件直接属于哪个可见界面。图2是同一截图的局部放大图，四个洋红色角标包围的
精确中心像素是唯一拟点击点；角标不覆盖中心。先根据两张图独立识别中心像素实际落在哪个可交互控件上，
并从完整截图确认该控件直接属于哪个窗口、弹窗、卡片、行或其他可见界面；然后才把实际控件及其归属与
主 Agent 请求的 target 和 requested_entry 比较。确认点击是否明显可能提交、删除、购买、发送、授权、
泄露信息或离开目标应用。若中心像素在控件可见填充或边界之外，
即使只差几像素、中心附近有控件或文字、或点落在包含该控件的卡片/行背景上，`point_matches_target`
也必须为 false 并 reject；请求文本不能覆盖这个几何判断。
必须分别判断“点位落在某个可交互控件上”和“这个控件确实是请求中的 target”。`target_matches_request`
只能依据截图中的可见标签、图标、直接归属和 requested_entry 的已有可靠证据填写。形状或图标相似但直接
归属不同，就是另一个控件；请求所述目标或归属在截图中不可见时，不得根据请求文字补全或臆造，必须令
`target_matches_request=false` 或返回 uncertain。点位落在另一个可点击且安全的控件上时，仍必须填 false
并 reject。`observed_target` 必须描述截图中实际控件及其直接归属，不能复述请求中的 target。
只有中心点位于实际可交互控件内、该控件及其直接归属与请求一致、并且点击实际控件本身安全时，才能
approve；任一条件不成立或 `observed_target` 与匹配结论矛盾，都必须 reject 或 uncertain。
只有目标本身有可交互外观或已有可靠交互证据时才可 approve。Region 名称、页面标题、说明文字、时间/数值显示、
分隔线和空白背景即使点击安全、点位也落在所述区域，仍不是可交互目标，必须 reject；“为了检查/观察区域”
不能把静态区域变成按钮，应由主 Agent 更新 Region ledger 或直接滚动观察。
当前是只发现功能、不执行功能的探索阶段。可以进入普通菜单、选择页或确认页观察，但如果这个点击本身会
最终确认或保存配置、创建或修改用户数据、完成向导、授予权限、发起外部影响，则必须返回 reject/unsafe；
不能因为主 Agent 把它称为“预期功能”或标记为 safe 就放行。按钮文字要结合当前界面和实际所属容器判断，
不按 Done、Continue、Confirm 等单个词机械拒绝。风险必须按截图中实际控件判断，不能按请求声称的用途判断。
不得根据应用惯例猜测点击后“应该还有确认框、Snackbar 或 Undo”。当前视觉证据不能排除本次点击直接
产生删除、提交或其他外部影响时，必须 fail closed；潜在的后续确认或撤销不构成本次点击安全的证据。
看不清或证据冲突返回 uncertain。不要返回新坐标。
"""


CLICK_REVIEW_PROMPT += """

When requested_entry is present, it is the exact ledger entry being attempted.
Use its Page, Region, control type, and current-value semantics as independent
evidence.  A similarly named or similarly shaped control in another Region is
not that entry and must set target_matches_request=false.
Review the exact requested operation. For long_press or double_tap, approve only
when that gesture on the visible target is safe; do not silently review it as an
ordinary click.

The visible physical mouse cursor and any cursor-triggered tooltip describe the
existing hover state; they are never markers for the proposed click point. Ignore
their position when locating the proposal, whose only location is the exact
center between the four magenta corner marks in Fig 2. Do not transfer the
cursor's or tooltip's owner to that center.
Keep hover-expanded menus, hover highlights, and controls revealed by hover as
valid interface-state evidence. If the Fig 2 center remains visibly inside the
requested control, judge that control even when the physical cursor is elsewhere.
If a tooltip fully obscures the exact center so the underlying control cannot be
verified, return uncertain instead of guessing or relocating the point.

For input_text, review the combined focus-and-type action rather than an
ordinary click. The marked center must be inside the requested visible editable
field, and requested_text is the exact text that will be entered. Approve only
short, non-sensitive search, filter, or query text whose entry itself does not
submit, send, create, edit, authorize, or expose user data. Reject password,
credential, message, form-submission, data-editing, and other consequential
fields. Do not assume a later Enter key or confirmation: input_text only focuses
the marked field and enters requested_text.
Classify the visible requested field's purpose from Fig 1 independently of point
geometry. If it is clearly a name or other form/data-editing field, reject the
input_text operation as unsafe even when the marked point misses the field, and
state that operation mismatch in the reason so the next correction changes the
operation or control rather than only guessing another coordinate.
"""


CLICK_REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": [
            "approve", "reject", "uncertain",
        ]},
        "observed_target": {"type": "string"},
        "point_matches_target": {"type": "boolean"},
        "target_matches_request": {"type": "boolean"},
        "risk": {"type": "string", "enum": [
            "safe", "unsafe", "uncertain", "off_app",
        ]},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "decision", "observed_target", "point_matches_target",
        "target_matches_request", "risk", "reason",
    ],
    "additionalProperties": False,
}


INTERRUPTION_REVIEW_PROMPT = """\
你是独立临时干扰处理 Agent。主探索 Agent 只报告一个疑似影响当前任务的前景层；你根据最新完整截图、
当前任务和主 Agent 的观察，判断它是否确实是临时干扰、是否阻挡当前目标，并只选择一种最小恢复策略。

按以下顺序考虑：不影响当前目标就 ignore；可能自行消失就 wait；控件可能只在悬停态显示就 hover 当前
可见干扰表面并重新观察；只有截图中已经显示一个直接属于该干扰的关闭/取消/稍后控件时才 click；只有
明确作用于最前层且不会离开目标应用时才 back；证据不足就 unresolved。这里的常见方法只是候选，不是
必须执行的固定规则。不得按应用惯例补全不可见控件，不得借用应用窗口、其他弹窗或背景页面的相似控件。

hover 的 target 必须是截图中实际可见的干扰表面，point_1000 必须落在该表面内；hover 只用于显露新的
视觉证据，不得声称隐藏控件已经可见。click 的 target 必须是当前截图中实际可见的控件及其直接归属，且
target_is_close_control 必须严格为 true。click 仍会交给另一个独立 Click Reviewer 审核，你不审批自己的
点击。wait/back/ignore/unresolved 的 target 使用空字符串、point_1000 使用 null、
target_is_close_control=false。一次只处理最前层；不规划页面探索或入口执行。看不清时 fail closed。
"""


INTERRUPTION_REVIEW_PROMPT += """\

关键视觉归属规则：
- 桌面端没有看见明确属于干扰表面的关闭控件时，先悬停一次当前可见干扰表面并取得新截图，再考虑点击。
- target_is_close_control 是视觉事实分类，不是授权；整张通知、横幅、对话框或卡片不是其自身的关闭控件。
- 不得猜测点击干扰主体会关闭它、打开可顺便清除它的界面或产生其他便利效果。
"""


INTERRUPTION_REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "surface_is_temporary": {"type": "boolean"},
        "blocks_current_target": {"type": "boolean"},
        "strategy": {"type": "string", "enum": [
            "ignore", "wait", "hover", "click", "back", "unresolved",
        ]},
        "target": {"type": "string"},
        "point_1000": {"anyOf": [
            {
                "type": "array",
                "items": {"type": "number", "minimum": 0, "maximum": 1000},
                "minItems": 2,
                "maxItems": 2,
            },
            {"type": "null"},
        ]},
        "target_is_close_control": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "surface_is_temporary", "blocks_current_target", "strategy",
        "target", "point_1000", "target_is_close_control", "reason",
    ],
    "additionalProperties": False,
}


class ActionValidationError(ValueError):
    """Fail-closed validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreviousToolReview:
    decision: str
    reason: str


@dataclass(frozen=True)
class ValidatedAction:
    """Normalized action proposal; callers still own dispatch and capture."""

    tool_name: str
    operation: str
    frame_id: str
    arguments: Dict[str, Any]
    purpose: str = ""
    previous_tool_review: Optional[PreviousToolReview] = None

    @property
    def env_action(self) -> bool:
        """Whether dispatch must explicitly call the GUI environment."""
        return self.operation != "wait"

    @property
    def reobserve_only(self) -> bool:
        return self.operation == "wait"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "operation": self.operation,
            "frame_id": self.frame_id,
            "arguments": dict(self.arguments),
            "purpose": self.purpose,
            "previous_tool_review": (
                asdict(self.previous_tool_review)
                if self.previous_tool_review is not None else None
            ),
            "env_action": self.env_action,
            "reobserve_only": self.reobserve_only,
        }


@dataclass(frozen=True)
class ActionResult:
    """Capture-backed factual result built by the caller after dispatch."""

    status: str
    tool_name: str
    operation: str
    before_frame_id: str
    after_frame_id: str
    env_action: bool
    container_hint: str = ""
    point_1000: Optional[List[float]] = None
    moved: Optional[bool] = None
    position_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if self.operation != "scroll":
            result.pop("container_hint")
        if self.operation not in POINTER_GESTURE_OPERATIONS | {
                "input_text", "hover", "scroll"}:
            result.pop("point_1000")
        return result


_POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number", "minimum": 0, "maximum": 1000},
    "minItems": 2,
    "maxItems": 2,
}
_ARGUMENT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "click": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "Actual visible control or intentionally selected surface "
                    "and its direct visible owner; do not describe an intended "
                    "effect or an invisible target."
                ),
            },
            "entry_id": {
                "type": "string",
                "description": (
                    "Exact known ledger entry for the visible control actually "
                    "clicked, even during navigation or recovery; leave empty "
                    "for an intentionally selected non-entry surface or when "
                    "the current Page exploration memory has no matching entry."
                ),
            },
            "point_1000": _POINT_SCHEMA,
        },
        "required": ["target", "entry_id", "point_1000"],
        "additionalProperties": False,
    },
    "input_text": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "Actual visible editable field and its direct visible "
                    "owner; do not describe the expected results."
                ),
            },
            "point_1000": _POINT_SCHEMA,
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "description": (
                    "Exact short, non-sensitive, single-line search, filter, "
                    "or query text; this tool never presses Enter."
                ),
            },
        },
        "required": ["target", "point_1000", "text"],
        "additionalProperties": False,
    },
    "hover": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "Actual visible surface to hover for new visual evidence; "
                    "do not name a hidden control or intended effect."
                ),
            },
            "point_1000": _POINT_SCHEMA,
        },
        "required": ["target", "point_1000"],
        "additionalProperties": False,
    },
    "scroll": {
        "type": "object",
        "properties": {
            "container_hint": {
                "type": "string",
                "description": (
                    "Natural-language description of the visible area expected "
                    "to receive the scroll; it need not be a registered Region."
                ),
            },
            "point_1000": _POINT_SCHEMA,
            "direction": {"type": "string", "enum": sorted(SCROLL_DIRECTIONS)},
            "amount": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Normalized distance; 1000 is one viewport.",
            },
        },
        "required": [
            "container_hint", "point_1000", "direction", "amount",
        ],
        "additionalProperties": False,
    },
    "navigate": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": sorted(
                NAVIGATION_OPERATIONS)},
        },
        "required": ["operation"],
        "additionalProperties": False,
    },
}
_GESTURE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": sorted(POINTER_GESTURE_OPERATIONS),
        },
        "target": {"type": "string"},
        "entry_id": {"type": "string"},
        "point_1000": _POINT_SCHEMA,
    },
    "required": ["operation", "target", "entry_id", "point_1000"],
    "additionalProperties": False,
}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionValidationError(
            "invalid_arguments", f"{name} must be a non-empty string")
    return " ".join(value.strip().split())


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ActionValidationError(
            "invalid_arguments", f"{name} must be a string")
    return " ".join(value.strip().split())



def _coordinate(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ActionValidationError(
            "invalid_coordinates", f"{name} values must be finite numbers")
    result = float(value)
    if not math.isfinite(result):
        raise ActionValidationError(
            "invalid_coordinates", f"{name} values must be finite numbers")
    if not 0 <= result <= 1000:
        raise ActionValidationError(
            "coordinates_out_of_bounds", f"{name} must stay within 0..1000")
    return result


def _point(value: Any) -> Tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ActionValidationError(
            "invalid_coordinates", "point_1000 must be [x, y]")
    return (
        _coordinate(value[0], "point_1000"),
        _coordinate(value[1], "point_1000"),
    )




def _review(value: Any) -> Optional[PreviousToolReview]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ActionValidationError(
            "invalid_tool_review", "previous_tool_review must be an object")
    unknown = sorted(set(value) - {"decision", "reason"})
    if unknown:
        raise ActionValidationError(
            "invalid_tool_review",
            f"unknown previous_tool_review fields: {unknown}",
        )
    decision = str(value.get("decision") or "").strip().casefold()
    if decision not in TOOL_REVIEW_DECISIONS:
        raise ActionValidationError(
            "invalid_tool_review",
            "previous_tool_review decision must be accept, reject, or uncertain",
        )
    reason = _text(value.get("reason"), "previous_tool_review.reason")
    return PreviousToolReview(decision=decision, reason=reason)


def action_tool_catalog(
    *, platform: str = "",
) -> List[Dict[str, Any]]:
    """Return compact actions supported by the current platform."""
    descriptions = {
        "click": (
            "点击最新截图中一个当前可见且安全的控件或有意选择的界面表面；target 写实际控件或表面"
            "及其直接可见归属，不能写预期效果或不可见目标；若选择表面，顶层 reason 说明本次动作意图；"
            "point_1000 相对整张截图。"
            "若实际点击控件与‘当前 Page 的既有探索’中某个已登记入口明确对应，填它的精确 entry_id；"
            "只有没有对应项时才留空。干扰处理先调用 "
            "handle_interruption。"
        ),
        "input_text": (
            "聚焦最新截图中一个可见的可编辑输入框，输入准确、简短、非敏感的单行搜索、筛选或查询文本。"
            "此工具不会按回车；不得用于提交、发送、创建、编辑、授权或输入凭据。"
        ),
        "hover": (
            "仅桌面：把鼠标移到最新截图中的可见表面并短暂停留，再保存新截图；"
            "target 不能填写尚未显示的隐藏控件。干扰悬停由 handle_interruption 规划。"
        ),
        "scroll": (
            "在最新截图中滚动一个可见容器；container_hint 用自然语言描述它，"
            "无需是已登记 Region；point_1000 放在实际要滚动的区域内。"
        ),
        "navigate": (
            "请求平台 back 或 wait。可见的应用内返回/关闭按钮优先用 click；"
            "wait 只刷新截图，不执行 GUI 动作。"
        ),
        "gesture": (
            "仅 Android：对最新截图中的目标执行 long_press/double_tap；"
            "普通进入入口仍优先 click，滚动浏览使用 scroll。"
        ),
    }
    catalog = []
    names = ["click", "input_text", "scroll", "navigate"]
    if not is_android(platform):
        names.insert(1, "hover")
    if is_android(platform):
        names.append("gesture")
    for name in names:
        schema = deepcopy(
            _GESTURE_SCHEMA if name == "gesture" else _ARGUMENT_SCHEMAS[name]
        )
        catalog.append({
            "name": name,
            "description": descriptions[name],
            "input_schema": schema,
            "effect": (
                "gui_action" if name != "navigate"
                else "gui_action_or_reobserve"
            ),
            "returns": "动作是否执行，以及真实可见结果或滚动是否移动",
            "requires_review": False,
            "executes_gui": True,
        })
    return catalog


def _arguments(tool_name: str, value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionValidationError(
            "invalid_arguments", f"{tool_name} arguments must be an object")
    schema = (
        _GESTURE_SCHEMA if tool_name == "gesture"
        else _ARGUMENT_SCHEMAS[tool_name]
    )
    allowed = set(schema["properties"])
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ActionValidationError(
            "invalid_arguments", f"unknown {tool_name} arguments: {unknown}")
    missing = [name for name in schema["required"]
               if name not in value]
    if missing:
        raise ActionValidationError(
            "invalid_arguments", f"missing {tool_name} arguments: {missing}")
    return dict(value)




def validate_action_tool_call(
    tool_name: str,
    arguments: Any,
    *,
    latest_frame_id: str,
    previous_tool_review: Any = None,
    platform: str = "",
    purpose: str = "",
) -> ValidatedAction:
    """Validate one explicit action request without dispatching it."""
    name = str(tool_name or "").strip().casefold()
    if name not in ACTION_TOOL_NAMES:
        raise ActionValidationError(
            "not_an_action_tool",
            f"{name or '<empty>'} is not an explicit action tool",
        )
    if name == "gesture" and not is_android(platform):
        raise ActionValidationError(
            "unsupported_platform", "gesture is available only on Android",
        )
    if name == "hover" and is_android(platform):
        raise ActionValidationError(
            "unsupported_platform", "hover is available only on desktop",
        )
    latest = _required_text(latest_frame_id, "latest_frame_id")
    values = _arguments(name, arguments)
    frame_id = latest
    review = _review(previous_tool_review)

    if name == "click":
        target = _required_text(values.get("target"), "target")
        point = _point(values.get("point_1000"))
        entry_id = str(values.get("entry_id") or "").strip()
        normalized = {
            "target": target,
            "entry_id": entry_id,
            "point_1000": list(point),
        }
        operation = "click"
    elif name == "input_text":
        text = values.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ActionValidationError(
                "invalid_text", "text must be a non-empty string")
        if len(text) > 200 or "\n" in text or "\r" in text:
            raise ActionValidationError(
                "invalid_text",
                "text must be a single line no longer than 200 characters",
            )
        normalized = {
            "target": _required_text(values.get("target"), "target"),
            "point_1000": list(_point(values.get("point_1000"))),
            "text": text,
        }
        operation = "input_text"
    elif name == "hover":
        normalized = {
            "target": _required_text(values.get("target"), "target"),
            "point_1000": list(_point(values.get("point_1000"))),
        }
        operation = "hover"
    elif name == "scroll":
        container_hint = _required_text(
            values.get("container_hint"), "container_hint")
        point = _point(values.get("point_1000"))
        direction = str(values.get("direction") or "").strip().casefold()
        if direction not in SCROLL_DIRECTIONS:
            raise ActionValidationError(
                "invalid_direction",
                "direction must be up, down, left, or right",
            )
        amount = values.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or not (
                1 <= amount <= 1000):
            raise ActionValidationError(
                "invalid_amount", "amount must be an integer in 1..1000")
        normalized = {
            "container_hint": container_hint,
            "point_1000": list(point),
            "direction": direction,
            "amount": amount,
        }
        operation = "scroll"
    elif name == "navigate":
        operation = str(values.get("operation") or "").strip().casefold()
        if operation not in NAVIGATION_OPERATIONS:
            raise ActionValidationError(
                "invalid_navigation",
                "navigate operation must be back or wait",
            )
        normalized = {}
    elif name == "gesture":
        operation = str(values.get("operation") or "").strip().casefold()
        if operation not in GESTURE_OPERATIONS:
            raise ActionValidationError(
                "invalid_gesture",
                "gesture operation must be double_tap or long_press",
            )
        normalized = {
            "target": _required_text(values.get("target"), "target"),
            "entry_id": str(values.get("entry_id") or "").strip(),
            "point_1000": list(_point(values.get("point_1000"))),
        }
    return ValidatedAction(
        tool_name=name,
        operation=operation,
        frame_id=frame_id,
        arguments=normalized,
        purpose=str(purpose or "").strip().casefold(),
        previous_tool_review=review,
    )


def build_action_result(
    action: ValidatedAction,
    *,
    before_frame_id: str,
    after_frame_id: str,
    moved: Optional[bool] = None,
    position_hint: str = "",
) -> ActionResult:
    """Build the factual capture result; this function never executes an action."""
    before = _required_text(before_frame_id, "before_frame_id")
    after = _required_text(after_frame_id, "after_frame_id")
    if before != action.frame_id:
        raise ActionValidationError(
            "stale_frame",
            "before_frame_id no longer matches the action's bound frame",
        )
    hint = " ".join(str(position_hint or "").strip().split())
    if action.operation == "scroll":
        if not isinstance(moved, bool):
            raise ActionValidationError(
                "invalid_scroll_result", "scroll result requires moved=true|false")
        if not hint:
            raise ActionValidationError(
                "invalid_scroll_result", "scroll result requires position_hint")
    elif moved is not None or hint:
        raise ActionValidationError(
            "invalid_action_result",
            "moved and position_hint are reserved for scroll results",
        )
    return ActionResult(
        status="reobserved" if action.reobserve_only else "observed",
        tool_name=action.tool_name,
        operation=action.operation,
        before_frame_id=before,
        after_frame_id=after,
        env_action=action.env_action,
        container_hint=(
            str(action.arguments["container_hint"])
            if action.operation == "scroll" else ""
        ),
        point_1000=(
            list(action.arguments["point_1000"])
            if action.operation in POINTER_GESTURE_OPERATIONS | {
                    "input_text", "hover", "scroll"}
            else None
        ),
        moved=moved,
        position_hint=hint,
    )


ACTION_REVIEW_PROMPT = """\
你是独立行动复核器。每次调用只完成请求中指定的一项工作，不判断动作结果，不判断页面身份，也不划分功能区域。

任务一是复核主 Agent 提出的精确界面动作。以最新完整截图为准，先判断主 Agent 声明的目标是可见控件，还是有意选择的可见界面表面，再检查坐标是否确实落在该目标上、是否误落到相邻控件或遮挡层、操作类型是否适合，以及动作本身是否安全。空白背景、画布或控件外表面不是按钮，但主 Agent 明确把它声明为本次点击目标时，不能仅因它不是控件而拒绝。主 Agent 的行动理由用于区分有意选择表面和没有点中控件；它不能覆盖截图中的点位事实，也不能授权危险动作。不要预测动作能否产生预期结果，安全动作执行后是否生效由后续截图判断。只能批准、拒绝或报告不确定；不得替主 Agent 改目标、改坐标或换动作。

任务二是处理疑似临时干扰。先判断该表面是否真的阻挡当前任务；不阻挡就忽略。确实阻挡时，只能从最新截图中选择一个低风险、可恢复且直接可见的关闭、取消或返回动作；看不见合适控件时报告不确定，不得根据其他界面或应用惯例猜坐标。这里提出的恢复动作已经完成行动复核，框架可以直接执行，不再进行第二次复核。

理由必须具体说明截图中的实际目标、直接所属界面、点位关系、任务作用和风险依据，不能只写“目标匹配”或“安全”。
"""

# Click review uses the shared action prompt. Interruption review keeps the
# dedicated bounded-recovery prompt defined above.
CLICK_REVIEW_PROMPT = ACTION_REVIEW_PROMPT
INTERRUPTION_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "surface_is_temporary": {"type": "boolean"},
        "blocks_current_target": {"type": "boolean"},
        "strategy": {
            "type": "string",
            "enum": [
                "ignore", "wait", "hover", "click", "back", "unresolved",
            ],
        },
        "target": {"type": "string"},
        "point_1000": {"anyOf": [_POINT_SCHEMA, {"type": "null"}]},
        "target_is_close_control": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "surface_is_temporary", "blocks_current_target", "strategy",
        "target", "point_1000", "target_is_close_control", "reason",
    ],
    "additionalProperties": False,
}


__all__ = [
    "ACTION_TOOL_NAMES",
    "ACTION_REVIEW_PROMPT",
    "CLICK_REVIEW_PROMPT",
    "CLICK_REVIEW_SCHEMA",
    "INTERRUPTION_REVIEW_PROMPT",
    "INTERRUPTION_REVIEW_SCHEMA",
    "GESTURE_OPERATIONS",
    "NAVIGATION_OPERATIONS",
    "POINTER_GESTURE_OPERATIONS",
    "SCROLL_DIRECTIONS",
    "TOOL_REVIEW_DECISIONS",
    "ActionResult",
    "ActionValidationError",
    "PreviousToolReview",
    "ValidatedAction",
    "action_tool_catalog",
    "build_action_result",
    "validate_action_tool_call",
]
