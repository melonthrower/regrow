"""Frame-bound Region ledger for autonomous traversal."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .autonomous_turn import _page_key


REGION_REVIEW_PROMPT = """\
你是独立功能区域复核器。只根据本轮固定完整证据截图整理当前前景交互表面的完整功能区域，并逐项修正输入的已有区域。不判断页面身份，不做跨页面区域映射。

功能区域是共同承担一个稳定功能角色的组件组，不是矩形范围、位置或单个按钮。一个独立功能表面即使只有一个入口也可以是区域，但它必须有独立于该控件本身的稳定内容或容器；不得把只由一个控件构成的碎片改名为工具栏、操作区或其他区域来绕过这条边界。同一连续应用栏中的单个控件即使单独占位或动作不同，仍只是该应用栏的入口。能归入可见导航组、内容面板或设置组的单个按钮同理，不能仅因动作不同或本次漏报就拆成新区域；视觉分栏也不能单独证明它属于另一区域。只审核目标应用的稳定表面。系统通知、桌面或其他应用浮层、窗口管理控件都不是 Region；提案排除它们是正确的，不能据此报遗漏或改变应用区域边界。

输入的已有区域只是主 Agent 提案，不是封闭清单。regions 必须覆盖截图中当前前景交互表面内所有属于目标应用的稳定功能区域，漏项直接补出；常驻、全局、重复出现、可复用、功能简单或没有候选入口都不是省略理由，导航组、工具栏、侧栏和内容区照常登记。系统顶栏、Dock、输入法、其他应用和窗口管理控件与应用栏同排时，只排除这些系统控件，不能省略整条应用栏，也不能把它们写入区域摘要。应用内模态表面位于前景时，后方不接收交互的宿主页只作为上下文，不纳入 regions。

同一页面中重复出现、功能相同但可各自展开或改变状态的实例应保持为多个区域；同质内容条目本身仍归入所属内容区域。

默认保留当前页面已经复核通过的区域划分。位置、外观、普通状态、动态文字或内容数值变化都不是重新划分的理由；只有截图显示功能结构确实改变，或现有划分与可见组件明确矛盾时才修改。滚动或局部展开出现的新内容应作为局部增量处理，不要重新划分整页。

regions 只返回当前成立的稳定功能区域，每项只含稳定 name 和简短 summary。不要枚举区域中的按钮、Entry、候选数量、代表操作或内容实例；这些由区域通过后的 Entry 调查负责。

revisions 必须逐项结算输入的每个已有区域，且每个精确旧名称恰好出现一次：仍成立就 decision=keep，名称保持不变且同名区域必须存在于 regions；单控件、重复实例或其他碎片属于某个当前区域时用 decision=merge，并令 merged_into 精确等于 regions 中存在的目标名称；只有不属于当前应用界面或确实没有功能归属时才用 decision=remove。keep 和 remove 不携带 merged_into。应用内可见内容不能无归属地删除。

若证据不足，保守保留已有区域并在 reason 中说明，不猜测被遮住的边界。只返回 regions、revisions 和整体 reason。
"""

REGION_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "summary": {"type": "string", "minLength": 1},
                },
                "required": ["name", "summary"],
                "additionalProperties": False,
            },
        },
        "revisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "old_region": {"type": "string", "minLength": 1},
                    "decision": {
                        "type": "string",
                        "enum": ["keep", "merge", "remove"],
                    },
                    "merged_into": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["old_region", "decision", "reason"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["regions", "revisions", "reason"],
    "additionalProperties": False,
}


CROSS_PAGE_REGION_REVIEW_PROMPT = """\
你是跨页面功能区域身份复核器。输入是多个已经分别通过页面内区域复核的区域 occurrence 及其对应完整截图。你只判断区域是否属于可复用的同一功能身份，不重新划分页面区域，也不检查按钮或入口清单。

只有区域的稳定功能、所拥有的交互语义和复用含义一致时才组成 shared_groups。相同位置、形状、主题、布局或外层容器不足以证明等价；外观相似但执行不同功能的区域必须保持分开。证据不足时放入 unmatched，不猜测。

每个输入 occurrence_id 必须且只能出现一次：要么属于一个 shared_groups，要么属于一个 separate_groups，要么单独列入 unmatched。shared_groups 至少包含两个跨页面 occurrence；separate_groups 用于明确相似但功能不同、因而不能共享的 occurrence。只返回 shared_groups、separate_groups、unmatched 和整体 reason。
"""


CROSS_PAGE_REGION_REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "shared_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "members": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 2,
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["members", "reason"],
                "additionalProperties": False,
            },
        },
        "separate_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "members": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 2,
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["members", "reason"],
                "additionalProperties": False,
            },
        },
        "unmatched": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "occurrence_id": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["occurrence_id", "reason"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["shared_groups", "separate_groups", "unmatched", "reason"],
    "additionalProperties": False,
}


REGION_MAPPING_PROMPT = """\
你是批量区域映射器。根据动作前后的两张完整截图、实际执行的动作和两份已经复核通过的区域目录，判断动作前后哪些区域属于同一持续存在的内容容器或对象。

你不重新划分区域，不修改区域名称，也不检查功能入口。只能使用输入目录中的临时区域编号。

位置相近、覆盖原位置、外观相似、功能相近或由同一个动作触发，都不能单独证明两个区域相同。只有同一内容容器或同一对象在界面变化中持续存在，才能建立对应关系。

对应关系可以是一对一、一对多、多对一或多对多。只有多个区域共同表示同一个持续存在的完整内容时，才能把它们放入同一个对应组。

新出现的菜单、对话框、抽屉或其他前景表面，不得因为覆盖了原区域的位置，就与后方区域建立对应关系。

动作后明确出现、且不属于任何动作前区域延续的内容，标记为新增。证据不足以确认来源的区域，标记为不确定，不要强行对应。

动作后的每个区域必须且只能出现一次：要么属于一个对应组，要么标记为新增，要么标记为不确定。动作前没有对应结果的区域可以自然消失，不需要单独输出。
"""

REGION_MAPPING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "before": {
                        "type": "array", "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "after": {
                        "type": "array", "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["before", "after", "reason"],
                "additionalProperties": False,
            },
        },
        "new": {"type": "array", "items": {"type": "string"}},
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "after": {"type": "string"},
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["after", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["matches", "new", "uncertain"],
    "additionalProperties": False,
}


class RegionProtocolError(ValueError):
    """A main-Agent Region update does not satisfy the ledger contract."""


class StaleFrameError(RegionProtocolError):
    """A Region update belongs to an older screenshot."""


def screenshot_frame_id(screenshot: bytes) -> str:
    """Create the exact frame identity used by observation and action evidence."""
    if not isinstance(screenshot, bytes) or not screenshot:
        raise RegionProtocolError("screenshot must be non-empty bytes")
    return hashlib.sha256(screenshot).hexdigest()


def _region_for_point(
    state: "AutonomousRegionState",
    point_1000: Optional[Sequence[float]],
) -> str:
    """Resolve one point to the smallest containing Region in the current State."""
    if point_1000 is None:
        return "full_screen"
    x, y = float(point_1000[0]), float(point_1000[1])
    snapshot = state.snapshot()
    names = {
        _page_key(region.get("name")): str(region.get("name") or "")
        for region in snapshot.get("regions") or []
    }
    matches = []
    for key, bound in (snapshot.get("current_bboxes") or {}).items():
        if bound.get("frame_id") != state.current_frame_id:
            continue
        bbox = bound.get("bbox_1000") or []
        if len(bbox) != 4 or not (
                bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
            continue
        matches.append(((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), key))
    if not matches:
        return "full_screen"
    _area, key = min(matches)
    return names.get(key) or "full_screen"


def _text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _key(value: Any) -> str:
    return _text(value, limit=160).casefold()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_bbox_1000(value: Any) -> Optional[List[float]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise RegionProtocolError("bbox_1000 must be [x1,y1,x2,y2]")
    try:
        x1, y1, x2, y2 = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise RegionProtocolError("bbox_1000 values must be numbers") from exc
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise RegionProtocolError("bbox_1000 is outside the 0..1000 full-screen range")
    return [x1, y1, x2, y2]


class AutonomousRegionState:
    """Main-Agent Region facts plus temporary geometry for the current State."""

    def __init__(self) -> None:
        self.current_frame_id = ""
        self.current_state_id = ""
        self._regions: Dict[str, Dict[str, Any]] = {}
        self._current_bboxes: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def from_snapshot(cls, payload: Dict[str, Any]) -> "AutonomousRegionState":
        """Restore durable Region facts while discarding stale geometry."""
        state = cls()
        for raw in payload.get("regions") or []:
            if not isinstance(raw, dict):
                continue
            name = _text(raw.get("name"), limit=160)
            if not name:
                continue
            legacy_observations = raw.get("observations")
            legacy_last_frame = ""
            if (not bool(raw.get("coverage_complete"))
                    and isinstance(legacy_observations, list)
                    and legacy_observations
                    and isinstance(legacy_observations[-1], dict)):
                legacy_last_frame = str(
                    legacy_observations[-1].get("frame_id") or "")
            state._regions[_key(name)] = {
                "name": name,
                "summary": _text(raw.get("summary"), limit=500),
                "survey_memory": _text(
                    raw.get("survey_memory"), limit=1200),
                "region_ref": _text(raw.get("region_ref"), limit=80),
                "equivalence_reason": _text(
                    raw.get("equivalence_reason"), limit=500),
                "last_incomplete_frame_id": _text(
                    raw.get("last_incomplete_frame_id") or legacy_last_frame,
                    limit=128,
                ),
                "coverage_complete": bool(raw.get("coverage_complete")),
                "coverage_version": _nonnegative_int(
                    raw.get("coverage_version")),
                "coverage_basis": _text(
                    raw.get("coverage_basis"), limit=80),
            }
        return state

    def observe_frame(
        self, frame_id: str, state_id: str = "",
    ) -> Dict[str, Any]:
        frame_id = _text(frame_id, limit=128)
        state_id = _text(state_id, limit=160)
        if not frame_id:
            raise RegionProtocolError("frame_id must be non-empty")
        if (
            frame_id == self.current_frame_id
            and state_id == self.current_state_id
        ):
            return {"changed": False}
        state_changed = state_id != self.current_state_id
        self.current_frame_id = frame_id
        self.current_state_id = state_id
        if state_changed:
            self._current_bboxes.clear()
        else:
            for bound in self._current_bboxes.values():
                bound["frame_id"] = frame_id
        return {"changed": True}

    def apply_agent_update(
        self,
        changes: Sequence[Dict[str, Any]],
        *,
        frame_id: str,
    ) -> List[str]:
        """Apply a frame-bound Region delta authored by the main Agent."""
        if self.current_frame_id != str(frame_id or ""):
            raise StaleFrameError("Agent page_update belongs to a stale frame")
        updated: List[str] = []
        for raw in changes:
            if not isinstance(raw, dict):
                raise RegionProtocolError("each page_update Region must be an object")
            region_name = _text(raw.get("name"), limit=160)
            if not region_name:
                raise RegionProtocolError("page_update Region requires name")
            complete = raw.get("coverage_complete")
            if not isinstance(complete, bool):
                raise RegionProtocolError(
                    "page_update Region coverage_complete must be boolean")
            patch = {
                "name": region_name,
                "summary": _text(raw.get("summary"), limit=500),
                "survey_memory": _text(
                    raw.get("survey_memory"), limit=1200),
                "region_ref": _text(raw.get("region_ref"), limit=80),
                "equivalence_reason": _text(
                    raw.get("equivalence_reason"), limit=500),
                "bbox_1000": normalize_bbox_1000(raw.get("bbox_1000")),
                "coverage_complete": complete,
            }
            updated.append(self._merge_patch(patch, frame_id=frame_id))
        return updated

    def _merge_patch(self, patch: Dict[str, Any], *, frame_id: str) -> str:
        region_key = _key(patch["name"])
        region = self._regions.setdefault(region_key, {
            "name": patch["name"],
            "summary": "",
            "survey_memory": "",
            "region_ref": "",
            "equivalence_reason": "",
            "last_incomplete_frame_id": "",
            "coverage_complete": False,
            "coverage_version": 0,
            "coverage_basis": "",
        })
        if patch["summary"]:
            region["summary"] = patch["summary"]
        if patch["survey_memory"]:
            region["survey_memory"] = patch["survey_memory"]
        if patch["region_ref"]:
            region["region_ref"] = patch["region_ref"]
        if patch["equivalence_reason"]:
            region["equivalence_reason"] = patch["equivalence_reason"]
        bbox = patch["bbox_1000"]
        if bbox is not None:
            self._current_bboxes[region_key] = {
                "state_id": self.current_state_id,
                "frame_id": frame_id,
                "bbox_1000": list(bbox),
            }
        region["coverage_complete"] = patch["coverage_complete"]
        if not patch["coverage_complete"]:
            region["coverage_version"] = 0
            region["coverage_basis"] = ""
        region["last_incomplete_frame_id"] = (
            "" if patch["coverage_complete"] else frame_id
        )
        return region["name"]

    def region(self, region_name: str) -> Optional[Dict[str, Any]]:
        region = self._regions.get(_key(region_name))
        return deepcopy(region) if region is not None else None

    def set_coverage_complete(self, region_name: str, complete: bool) -> None:
        """Finalize coverage after same-turn entry items have been processed."""
        region = self._regions.get(_key(region_name))
        if region is None:
            raise RegionProtocolError("unknown Region")
        if not isinstance(complete, bool):
            raise RegionProtocolError("coverage_complete must be boolean")
        region["coverage_complete"] = complete
        if complete:
            region["last_incomplete_frame_id"] = ""
        else:
            region["coverage_version"] = 0
            region["coverage_basis"] = ""

    def set_coverage_evidence(
        self,
        region_name: str,
        *,
        version: int,
        basis: str,
    ) -> None:
        """Attach one reviewed or mapped shared-Region coverage version."""
        region = self._regions.get(_key(region_name))
        if region is None:
            raise RegionProtocolError("unknown Region")
        version = max(0, int(version or 0))
        if not region.get("coverage_complete") or version <= 0:
            raise RegionProtocolError(
                "coverage evidence requires a complete Region and positive version")
        region["coverage_version"] = version
        region["coverage_basis"] = _text(basis, limit=80)

    def set_region_ref(
        self, region_name: str, region_ref: str, *, reason: str = "",
    ) -> None:
        """Bind one Page-local Region occurrence to an Agent-selected group."""
        region = self._regions.get(_key(region_name))
        if region is None:
            raise RegionProtocolError("unknown Region")
        ref = _text(region_ref, limit=80)
        if not ref:
            raise RegionProtocolError("region_ref must be non-empty")
        region["region_ref"] = ref
        if reason:
            region["equivalence_reason"] = _text(reason, limit=500)

    def remap_region_ref(self, old_ref: str, new_ref: str) -> None:
        """Apply one explicit group merge to every local occurrence."""
        old_ref = _text(old_ref, limit=80)
        new_ref = _text(new_ref, limit=80)
        if not old_ref or not new_ref or old_ref == new_ref:
            return
        for region in self._regions.values():
            if region.get("region_ref") == old_ref:
                region["region_ref"] = new_ref

    def snapshot(self) -> Dict[str, Any]:
        regions = deepcopy(list(self._regions.values()))
        for region in regions:
            region["acceptance_status"] = (
                "complete" if region["coverage_complete"] else "partial")
        return {
            "schema": "gui_rewalk.autonomous_regions.v6",
            "current_state_id": self.current_state_id,
            "current_frame_id": self.current_frame_id,
            "regions": regions,
            "current_bboxes": deepcopy(self._current_bboxes),
            "coverage_complete": bool(regions) and all(
                region["coverage_complete"] for region in regions),
        }


class AutonomousRegionRegistry:
    """Agent-authored cross-Page Region groups without visual/text matching."""

    def __init__(self) -> None:
        self._groups: Dict[str, Dict[str, Any]] = {}
        self._occurrences: Dict[Tuple[str, str], str] = {}
        self._next_region = 1
        self._next_occurrence = 1
        self._next_state = 1

    @staticmethod
    def _occurrence_key(page_name: str, region_name: str) -> Tuple[str, str]:
        return _key(page_name), _key(region_name)

    @property
    def refs(self) -> Tuple[str, ...]:
        return tuple(self._groups)

    def has(self, region_ref: str) -> bool:
        return str(region_ref or "").strip() in self._groups

    def region_ref(self, page_name: str, region_name: str) -> str:
        return self._occurrences.get(
            self._occurrence_key(page_name, region_name), "")

    def occurrence_ref(self, page_name: str, region_name: str) -> str:
        region_ref = self.region_ref(page_name, region_name)
        group = self._groups.get(region_ref)
        occurrence = (
            self._occurrence(group, page_name, region_name)
            if group is not None else None
        )
        return str((occurrence or {}).get("occurrence_ref") or "")

    def occurrence_state_ref(
        self, page_name: str, region_name: str, page_state_id: str,
    ) -> str:
        region_ref = self.region_ref(page_name, region_name)
        group = self._groups.get(region_ref)
        occurrence = (
            self._occurrence(group, page_name, region_name)
            if group is not None else None
        )
        if occurrence is None:
            return ""
        state_by_page_state = occurrence.get("state_by_page_state") or {}
        return str(state_by_page_state.get(str(page_state_id or "")) or "")

    def page_state_ids_for_occurrence_states(
        self,
        occurrence_ref: str,
        state_refs: Sequence[str],
    ) -> List[str]:
        wanted = {str(item or "").strip() for item in state_refs if str(item or "").strip()}
        if not wanted:
            return []
        occurrence = self._occurrence_by_ref(occurrence_ref)
        if occurrence is None:
            return []
        return [
            page_state_id
            for page_state_id, state_ref in (
                occurrence.get("state_by_page_state") or {}).items()
            if state_ref in wanted
        ]

    def state_summary(self, region_ref: str, state_ref: str) -> str:
        group = self._groups.get(str(region_ref or "").strip()) or {}
        definition = next((
            item for item in group.get("state_definitions") or []
            if item.get("state_ref") == str(state_ref or "").strip()
        ), None)
        return str((definition or {}).get("summary") or "")

    def _new_state_definition(
        self, group: Dict[str, Any], *, summary: str,
    ) -> str:
        state_ref = f"rs{self._next_state}"
        self._next_state += 1
        group.setdefault("state_definitions", []).append({
            "state_ref": state_ref,
            "summary": _text(summary, limit=500) or "Initial observed state",
            "coverage_version": 0,
            "reviewed_entry_ids": [],
        })
        return state_ref

    def _default_state_ref(self, group: Dict[str, Any]) -> str:
        definitions = group.setdefault("state_definitions", [])
        if definitions:
            return str(definitions[0].get("state_ref") or "")
        return self._new_state_definition(
            group, summary="Initial observed state")

    def _occurrence_by_ref(self, occurrence_ref: str) -> Optional[Dict[str, Any]]:
        occurrence_ref = str(occurrence_ref or "").strip()
        if not occurrence_ref:
            return None
        return next((
            item
            for group in self._groups.values()
            for item in group.get("occurrences") or []
            if item.get("occurrence_ref") == occurrence_ref
        ), None)

    def bind(
        self,
        *,
        page_name: str,
        region_name: str,
        state_id: str = "",
        variant_name: str = "",
        summary: str = "",
        equivalent_to_region_ref: str = "",
        reason: str = "",
    ) -> tuple[str, str]:
        """Bind an occurrence; return ``(kept_ref, merged_old_ref)``."""
        page_name = _text(page_name, limit=160)
        region_name = _text(region_name, limit=160)
        state_id = _text(state_id, limit=160)
        variant_name = _text(variant_name, limit=160)
        if not page_name or not region_name:
            raise RegionProtocolError(
                "Region group binding requires page_name and region_name")
        key = self._occurrence_key(page_name, region_name)
        current_ref = self._occurrences.get(key, "")
        requested_ref = _text(equivalent_to_region_ref, limit=80)
        if requested_ref and requested_ref not in self._groups:
            raise RegionProtocolError(
                f"unknown equivalent_to_region_ref: {requested_ref}")

        merged_old_ref = ""
        if requested_ref:
            region_ref = requested_ref
            if current_ref and current_ref != requested_ref:
                self._merge(requested_ref, current_ref)
                merged_old_ref = current_ref
        elif current_ref:
            region_ref = current_ref
        else:
            region_ref = f"rg{self._next_region}"
            self._next_region += 1
            self._groups[region_ref] = {
                "region_ref": region_ref,
                "representative": {
                    "page_name": page_name,
                    "region_name": region_name,
                },
                "representative_occurrence_ref": "",
                "summary": "",
                "occurrences": [],
                "state_definitions": [],
                "transitions": [],
                "coverage_versions": [],
            }

        group = self._groups[region_ref]
        if summary and not group.get("summary"):
            group["summary"] = _text(summary, limit=500)
        occurrence = {
            "occurrence_ref": "",
            "page_name": page_name,
            "region_name": region_name,
            "representative_variant_name": variant_name,
            "state_ids": [state_id] if state_id else [],
            "visible_state_ids": [],
            "observed_state_ref": "",
            "state_by_page_state": {},
            "inference_source_occurrence_ref": "",
        }
        if reason:
            occurrence["reason"] = _text(reason, limit=500)
        existing = next((
            item for item in group["occurrences"]
            if self._occurrence_key(
                item.get("page_name"), item.get("region_name")) == key
        ), None)
        if existing is None:
            occurrence["occurrence_ref"] = f"ro{self._next_occurrence}"
            self._next_occurrence += 1
            occurrence["observed_state_ref"] = self._default_state_ref(group)
            if state_id:
                occurrence["state_by_page_state"][state_id] = occurrence[
                    "observed_state_ref"]
            representative_ref = str(
                group.get("representative_occurrence_ref") or "")
            if not representative_ref:
                group["representative_occurrence_ref"] = occurrence[
                    "occurrence_ref"]
            else:
                occurrence["inference_source_occurrence_ref"] = representative_ref
            group["occurrences"].append(occurrence)
        else:
            if state_id and state_id not in existing.get("state_ids", []):
                existing.setdefault("state_ids", []).append(state_id)
            if variant_name and not existing.get("representative_variant_name"):
                existing["representative_variant_name"] = variant_name
            if state_id and state_id not in existing.setdefault(
                    "state_by_page_state", {}):
                existing["state_by_page_state"][state_id] = str(
                    existing.get("observed_state_ref")
                    or self._default_state_ref(group))
            if reason:
                existing["reason"] = occurrence["reason"]
        self._occurrences[key] = region_ref
        return region_ref, merged_old_ref

    def mark_state_visible(
        self,
        *,
        page_name: str,
        region_name: str,
        state_id: str,
    ) -> None:
        """Record reviewed evidence that this Region is visible in State."""
        region_ref = self.region_ref(page_name, region_name)
        group = self._groups.get(region_ref)
        if group is None:
            raise RegionProtocolError("visible Region is not a bound occurrence")
        occurrence = self._occurrence(group, page_name, region_name)
        if occurrence is None:
            raise RegionProtocolError("visible Region is not a bound occurrence")
        normalized_state_id = _text(state_id, limit=160)
        if not normalized_state_id:
            raise RegionProtocolError("visible Region requires state_id")
        visible_state_ids = occurrence.setdefault("visible_state_ids", [])
        if normalized_state_id not in visible_state_ids:
            visible_state_ids.append(normalized_state_id)

    def split_occurrence(
        self,
        *,
        page_name: str,
        region_name: str,
        reason: str,
    ) -> tuple[str, str, str]:
        """Detach one observed-conflicting occurrence into a fresh group."""
        key = self._occurrence_key(page_name, region_name)
        old_ref = self._occurrences.get(key, "")
        old_group = self._groups.get(old_ref)
        occurrence = (
            self._occurrence(old_group, page_name, region_name)
            if old_group is not None else None
        )
        if old_group is None or occurrence is None:
            raise RegionProtocolError("group split requires a bound occurrence")
        if len(old_group.get("occurrences") or []) <= 1:
            raise RegionProtocolError("a single occurrence cannot be split")

        moved = deepcopy(occurrence)
        moved["inference_source_occurrence_ref"] = ""
        moved["coverage_version"] = 0
        moved["coverage_basis"] = ""
        if reason:
            moved["reason"] = _text(reason, limit=500)
        referenced_states = {
            str(moved.get("observed_state_ref") or ""),
            *(
                str(item or "")
                for item in (moved.get("state_by_page_state") or {}).values()
            ),
        }
        new_ref = f"rg{self._next_region}"
        self._next_region += 1
        moved_transitions = [
            deepcopy(item)
            for item in old_group.get("transitions") or []
            if str(item.get("evidence_occurrence_ref") or "")
            == str(moved.get("occurrence_ref") or "")
        ]
        self._groups[new_ref] = {
            "region_ref": new_ref,
            "representative": {
                "page_name": _text(page_name, limit=160),
                "region_name": _text(region_name, limit=160),
            },
            "representative_occurrence_ref": str(
                moved.get("occurrence_ref") or ""),
            "summary": str(old_group.get("summary") or ""),
            "occurrences": [moved],
            "state_definitions": [
                deepcopy(item)
                for item in old_group.get("state_definitions") or []
                if str(item.get("state_ref") or "") in referenced_states
            ],
            "transitions": moved_transitions,
            "coverage_versions": [],
        }
        old_group["occurrences"] = [
            item for item in old_group.get("occurrences") or []
            if item is not occurrence
        ]
        old_group["transitions"] = [
            item for item in old_group.get("transitions") or []
            if str(item.get("evidence_occurrence_ref") or "")
            != str(moved.get("occurrence_ref") or "")
        ]
        if old_group.get("representative_occurrence_ref") == moved.get(
                "occurrence_ref"):
            replacement = old_group["occurrences"][0]
            replacement_ref = str(
                replacement.get("occurrence_ref") or "")
            old_group["representative_occurrence_ref"] = replacement_ref
            old_group["representative"] = {
                "page_name": str(replacement.get("page_name") or ""),
                "region_name": str(replacement.get("region_name") or ""),
            }
            replacement["inference_source_occurrence_ref"] = ""
            for sibling in old_group["occurrences"][1:]:
                sibling["inference_source_occurrence_ref"] = replacement_ref
        self._occurrences[key] = new_ref
        return old_ref, new_ref, str(moved.get("occurrence_ref") or "")

    def record_local_transition(
        self,
        *,
        page_name: str,
        region_name: str,
        source_state_id: str,
        destination_state_id: str,
        trigger_entry_id: str,
        effect_text: str,
        effect_kind: str,
        evidence_action_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Record one verified owner-local change and preserve sibling state."""
        region_ref = self.region_ref(page_name, region_name)
        group = self._groups.get(region_ref)
        owner = (
            self._occurrence(group, page_name, region_name)
            if group is not None else None
        )
        source_state_id = _text(source_state_id, limit=160)
        destination_state_id = _text(destination_state_id, limit=160)
        if (
            owner is None
            or not source_state_id
            or not destination_state_id
            or source_state_id == destination_state_id
        ):
            return None
        source_ref = str((owner.get("state_by_page_state") or {}).get(
            source_state_id) or owner.get("observed_state_ref") or "")
        if not source_ref:
            source_ref = self._default_state_ref(group)
            owner.setdefault("state_by_page_state", {})[
                source_state_id] = source_ref
        destination_ref = str((owner.get("state_by_page_state") or {}).get(
            destination_state_id) or "")
        if not destination_ref:
            destination_ref = self._new_state_definition(
                group, summary=effect_text)
            owner.setdefault("state_by_page_state", {})[
                destination_state_id] = destination_ref
        owner["observed_state_ref"] = destination_ref

        page_key = _key(page_name)
        for candidate_group in self._groups.values():
            for occurrence in candidate_group.get("occurrences") or []:
                if occurrence is owner or _key(occurrence.get("page_name")) != page_key:
                    continue
                mapping = occurrence.setdefault("state_by_page_state", {})
                prior_ref = str(mapping.get(source_state_id) or "")
                if not prior_ref:
                    continue
                mapping[destination_state_id] = prior_ref
                if destination_state_id not in occurrence.setdefault(
                        "state_ids", []):
                    occurrence["state_ids"].append(destination_state_id)
        if destination_state_id not in owner.setdefault("state_ids", []):
            owner["state_ids"].append(destination_state_id)

        transition = {
            "from_state_ref": source_ref,
            "trigger_entry_id": _text(trigger_entry_id, limit=80),
            "to_state_ref": destination_ref,
            "effect_text": _text(effect_text, limit=500),
            "effects": [{
                "scope": str(owner.get("occurrence_ref") or ""),
                "kind": str(effect_kind or "state")[:40],
            }],
            "evidence_occurrence_ref": str(
                owner.get("occurrence_ref") or ""),
            "evidence_action_id": _text(evidence_action_id, limit=80),
        }
        transitions = group.setdefault("transitions", [])
        if transition not in transitions:
            transitions.append(transition)
        return deepcopy(transition)

    def record_scoped_transitions(
        self,
        *,
        page_name: str,
        source_state_id: str,
        destination_state_id: str,
        trigger_entry_id: str,
        effects: Sequence[Dict[str, str]],
        evidence_action_id: str,
    ) -> List[Dict[str, Any]]:
        """Record several affected occurrences without treating peers as stable."""
        source_state_id = _text(source_state_id, limit=160)
        destination_state_id = _text(destination_state_id, limit=160)
        if (
            not source_state_id
            or not destination_state_id
            or source_state_id == destination_state_id
        ):
            return []
        affected: List[tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]] = []
        affected_refs: set[str] = set()
        for raw_effect in effects:
            region_name = _text(raw_effect.get("region_name"), limit=160)
            region_ref = self.region_ref(page_name, region_name)
            group = self._groups.get(region_ref)
            occurrence = (
                self._occurrence(group, page_name, region_name)
                if group is not None else None
            )
            occurrence_ref = str(
                (occurrence or {}).get("occurrence_ref") or "")
            if occurrence is None or not occurrence_ref:
                continue
            if occurrence_ref in affected_refs:
                continue
            affected_refs.add(occurrence_ref)
            affected.append((group, occurrence, dict(raw_effect)))
        if not affected:
            return []

        transitions: List[Dict[str, Any]] = []
        for group, occurrence, raw_effect in affected:
            mapping = occurrence.setdefault("state_by_page_state", {})
            source_ref = str(
                mapping.get(source_state_id)
                or occurrence.get("observed_state_ref") or "")
            if not source_ref:
                source_ref = self._default_state_ref(group)
                mapping[source_state_id] = source_ref
            destination_ref = str(mapping.get(destination_state_id) or "")
            if not destination_ref or destination_ref == source_ref:
                destination_ref = self._new_state_definition(
                    group,
                    summary=str(raw_effect.get("effect_text") or ""),
                )
                mapping[destination_state_id] = destination_ref
            occurrence["observed_state_ref"] = destination_ref
            if destination_state_id not in occurrence.setdefault(
                    "state_ids", []):
                occurrence["state_ids"].append(destination_state_id)
            transition = {
                "from_state_ref": source_ref,
                "trigger_entry_id": _text(trigger_entry_id, limit=80),
                "to_state_ref": destination_ref,
                "effect_text": _text(
                    raw_effect.get("effect_text"), limit=500),
                "effects": [{
                    "scope": str(occurrence.get("occurrence_ref") or ""),
                    "kind": _text(
                        raw_effect.get("effect_kind") or "state", limit=40),
                }],
                "evidence_occurrence_ref": str(
                    occurrence.get("occurrence_ref") or ""),
                "evidence_action_id": _text(evidence_action_id, limit=80),
            }
            known = group.setdefault("transitions", [])
            if transition not in known:
                known.append(transition)
            transitions.append(deepcopy(transition))

        page_key = _key(page_name)
        for candidate_group in self._groups.values():
            for occurrence in candidate_group.get("occurrences") or []:
                if (
                    str(occurrence.get("occurrence_ref") or "") in affected_refs
                    or _key(occurrence.get("page_name")) != page_key
                ):
                    continue
                mapping = occurrence.setdefault("state_by_page_state", {})
                source_ref = str(mapping.get(source_state_id) or "")
                if not source_ref:
                    continue
                mapping[destination_state_id] = source_ref
                if destination_state_id not in occurrence.setdefault(
                        "state_ids", []):
                    occurrence["state_ids"].append(destination_state_id)
        return transitions

    def _occurrence(
        self, group: Dict[str, Any], page_name: str, region_name: str,
    ) -> Optional[Dict[str, Any]]:
        key = self._occurrence_key(page_name, region_name)
        return next((
            item for item in group.get("occurrences") or []
            if self._occurrence_key(
                item.get("page_name"), item.get("region_name")) == key
        ), None)

    @staticmethod
    def _entry_signature(values: Sequence[str]) -> List[str]:
        return sorted({
            _text(value, limit=240).casefold()
            for value in values if _text(value, limit=240)
        })

    def publish_coverage(
        self,
        *,
        region_ref: str,
        page_name: str,
        region_name: str,
        state_id: str,
        frame_id: str,
        entry_signature: Sequence[str],
    ) -> int:
        """Publish or reuse one independently reviewed coverage version."""
        group = self._groups.get(str(region_ref or "").strip())
        if group is None:
            raise RegionProtocolError("unknown Region coverage group")
        occurrence = self._occurrence(group, page_name, region_name)
        if occurrence is None:
            raise RegionProtocolError("coverage source is not a bound occurrence")
        self.mark_state_visible(
            page_name=page_name,
            region_name=region_name,
            state_id=state_id,
        )
        signature = self._entry_signature(entry_signature)
        versions = group.setdefault("coverage_versions", [])
        version_record = next((
            item for item in versions
            if item.get("entry_signature") == signature
        ), None)
        if version_record is None:
            version_record = {
                "version": max(
                    [_nonnegative_int(item.get("version"))
                     for item in versions] or [0]
                ) + 1,
                "entry_signature": signature,
                "source": {
                    "page_name": _text(page_name, limit=160),
                    "region_name": _text(region_name, limit=160),
                    "state_id": _text(state_id, limit=160),
                    "frame_id": _text(frame_id, limit=128),
                },
            }
            versions.append(version_record)
        version = int(version_record["version"])
        occurrence["coverage_version"] = version
        occurrence["coverage_basis"] = "visual_entry_reviewer"
        local_state_ref = str((occurrence.get("state_by_page_state") or {}).get(
            _text(state_id, limit=160)) or "")
        for definition in group.get("state_definitions") or []:
            if definition.get("state_ref") == local_state_ref:
                definition["coverage_version"] = version
                break
        return version

    def mapped_coverage_version(
        self,
        *,
        region_ref: str,
        source_page: str,
        source_region: str,
        target_page: str,
        target_region: str,
        entry_signature: Sequence[str],
    ) -> int:
        """Return a reusable version for one exact batch-mapped continuation."""
        group = self._groups.get(str(region_ref or "").strip())
        if group is None:
            return 0
        source = self._occurrence(group, source_page, source_region)
        target = self._occurrence(group, target_page, target_region)
        if source is None or target is None:
            return 0
        version = _nonnegative_int(source.get("coverage_version"))
        signature = self._entry_signature(entry_signature)
        version_record = next((
            item for item in group.get("coverage_versions") or []
            if _nonnegative_int(item.get("version")) == version
            and item.get("entry_signature") == signature
        ), None)
        if version_record is None:
            return 0
        return version

    def inherit_mapped_coverage(
        self,
        *,
        region_ref: str,
        source_page: str,
        source_region: str,
        target_page: str,
        target_region: str,
        entry_signature: Sequence[str],
    ) -> int:
        """Commit coverage reuse after the mapped entries were accepted."""
        version = self.mapped_coverage_version(
            region_ref=region_ref,
            source_page=source_page,
            source_region=source_region,
            target_page=target_page,
            target_region=target_region,
            entry_signature=entry_signature,
        )
        if not version:
            return 0
        group = self._groups[str(region_ref or "").strip()]
        target = self._occurrence(group, target_page, target_region)
        assert target is not None
        target["coverage_version"] = version
        target["coverage_basis"] = "batch_region_mapping"
        return version

    def _merge(self, keep_ref: str, drop_ref: str) -> None:
        if keep_ref == drop_ref:
            return
        keep = self._groups.get(keep_ref)
        drop = self._groups.get(drop_ref)
        if keep is None or drop is None:
            raise RegionProtocolError("Region group merge references unknown group")
        if not keep.get("summary") and drop.get("summary"):
            keep["summary"] = drop["summary"]
        known_state_refs = {
            str(item.get("state_ref") or "")
            for item in keep.setdefault("state_definitions", [])
        }
        for definition in drop.get("state_definitions") or []:
            state_ref = str(definition.get("state_ref") or "")
            if state_ref and state_ref not in known_state_refs:
                keep["state_definitions"].append(deepcopy(definition))
                known_state_refs.add(state_ref)
        known_transitions = keep.setdefault("transitions", [])
        for transition in drop.get("transitions") or []:
            if transition not in known_transitions:
                known_transitions.append(deepcopy(transition))
        version_map: Dict[int, int] = {}
        keep_versions = keep.setdefault("coverage_versions", [])
        for dropped_version in drop.get("coverage_versions") or []:
            old_version = _nonnegative_int(dropped_version.get("version"))
            signature = self._entry_signature(
                dropped_version.get("entry_signature") or [])
            matching = next((
                item for item in keep_versions
                if item.get("entry_signature") == signature
            ), None)
            if matching is None:
                matching = deepcopy(dropped_version)
                matching["version"] = max(
                    [_nonnegative_int(item.get("version"))
                     for item in keep_versions] or [0]
                ) + 1
                matching["entry_signature"] = signature
                keep_versions.append(matching)
            if old_version:
                version_map[old_version] = _nonnegative_int(
                    matching.get("version"))
        known = {
            self._occurrence_key(item.get("page_name"), item.get("region_name")): item
            for item in keep.get("occurrences") or []
        }
        for raw_occurrence in drop.get("occurrences") or []:
            occurrence = deepcopy(raw_occurrence)
            old_version = _nonnegative_int(
                occurrence.get("coverage_version"))
            if old_version in version_map:
                occurrence["coverage_version"] = version_map[old_version]
            key = self._occurrence_key(
                occurrence.get("page_name"), occurrence.get("region_name"))
            if key not in known:
                keep["occurrences"].append(occurrence)
                known[key] = keep["occurrences"][-1]
            else:
                target = known[key]
                for state_id in occurrence.get("state_ids") or []:
                    if state_id and state_id not in target.setdefault(
                            "state_ids", []):
                        target["state_ids"].append(state_id)
                for state_id in occurrence.get("visible_state_ids") or []:
                    if state_id and state_id not in target.setdefault(
                            "visible_state_ids", []):
                        target["visible_state_ids"].append(state_id)
                if (
                    not _nonnegative_int(target.get("coverage_version"))
                    and _nonnegative_int(occurrence.get("coverage_version"))
                ):
                    target["coverage_version"] = occurrence["coverage_version"]
                    target["coverage_basis"] = str(
                        occurrence.get("coverage_basis") or "")
            self._occurrences[key] = keep_ref
        del self._groups[drop_ref]

    def has_state_occurrence(self, page_name: str, state_id: str) -> bool:
        """Return whether one accepted Region occurrence belongs to this State."""
        page_key = _key(page_name)
        state_id = _text(state_id, limit=160)
        return any(
            _key(item.get("page_name")) == page_key
            and state_id in (item.get("state_ids") or [])
            for group in self._groups.values()
            for item in group.get("occurrences") or []
        )

    def candidates(self) -> List[Dict[str, Any]]:
        return [deepcopy(group) for group in self._groups.values()]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "gui_rewalk.autonomous_region_groups.v6",
            "next_region": self._next_region,
            "next_occurrence": self._next_occurrence,
            "next_state": self._next_state,
            "groups": self.candidates(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Dict[str, Any],
        *,
        page_states: Optional[Dict[str, AutonomousRegionState]] = None,
    ) -> "AutonomousRegionRegistry":
        registry = cls()
        max_ref = 0
        for raw in payload.get("groups") or []:
            if not isinstance(raw, dict):
                continue
            region_ref = _text(raw.get("region_ref"), limit=80)
            representative = raw.get("representative") or {}
            if not region_ref or not isinstance(representative, dict):
                continue
            group = {
                "region_ref": region_ref,
                "representative": {
                    "page_name": _text(
                        representative.get("page_name"), limit=160),
                    "region_name": _text(
                        representative.get("region_name"), limit=160),
                },
                "representative_occurrence_ref": _text(
                    raw.get("representative_occurrence_ref"), limit=80),
                "summary": _text(raw.get("summary"), limit=500),
                "occurrences": [],
                "state_definitions": [],
                "transitions": [],
                "coverage_versions": [],
            }
            for raw_definition in raw.get("state_definitions") or []:
                if not isinstance(raw_definition, dict):
                    continue
                state_ref = _text(raw_definition.get("state_ref"), limit=80)
                if not state_ref:
                    continue
                raw_reviewed = raw_definition.get("reviewed_entry_ids") or []
                if not isinstance(raw_reviewed, list):
                    raw_reviewed = []
                group["state_definitions"].append({
                    "state_ref": state_ref,
                    "summary": _text(
                        raw_definition.get("summary"), limit=500),
                    "coverage_version": _nonnegative_int(
                        raw_definition.get("coverage_version")),
                    "reviewed_entry_ids": [
                        _text(item, limit=80) for item in raw_reviewed
                        if _text(item, limit=80)
                    ],
                })
                if state_ref.startswith("rs") and state_ref[2:].isdigit():
                    registry._next_state = max(
                        registry._next_state, int(state_ref[2:]) + 1)
            for raw_transition in raw.get("transitions") or []:
                if not isinstance(raw_transition, dict):
                    continue
                from_ref = _text(
                    raw_transition.get("from_state_ref"), limit=80)
                to_ref = _text(raw_transition.get("to_state_ref"), limit=80)
                if not from_ref or not to_ref:
                    continue
                raw_effects = raw_transition.get("effects") or []
                if not isinstance(raw_effects, list):
                    raw_effects = []
                group["transitions"].append({
                    "from_state_ref": from_ref,
                    "trigger_entry_id": _text(
                        raw_transition.get("trigger_entry_id"), limit=80),
                    "to_state_ref": to_ref,
                    "effect_text": _text(
                        raw_transition.get("effect_text"), limit=500),
                    "effects": [
                        {
                            "scope": _text(item.get("scope"), limit=80),
                            "kind": _text(item.get("kind"), limit=40),
                        }
                        for item in raw_effects if isinstance(item, dict)
                    ],
                    "evidence_occurrence_ref": _text(
                        raw_transition.get("evidence_occurrence_ref"),
                        limit=80),
                    "evidence_action_id": _text(
                        raw_transition.get("evidence_action_id"), limit=80),
                })
            for raw_version in raw.get("coverage_versions") or []:
                if not isinstance(raw_version, dict):
                    continue
                try:
                    version = int(raw_version.get("version") or 0)
                except (TypeError, ValueError):
                    continue
                if version <= 0:
                    continue
                source = raw_version.get("source") or {}
                if not isinstance(source, dict):
                    source = {}
                raw_signature = raw_version.get("entry_signature") or []
                if not isinstance(raw_signature, list):
                    raw_signature = []
                group["coverage_versions"].append({
                    "version": version,
                    "entry_signature": registry._entry_signature(
                        raw_signature),
                    "source": {
                        "page_name": _text(source.get("page_name"), limit=160),
                        "region_name": _text(source.get("region_name"), limit=160),
                        "state_id": _text(source.get("state_id"), limit=160),
                        "frame_id": _text(source.get("frame_id"), limit=128),
                    },
                })
            registry._groups[region_ref] = group
            if region_ref.startswith("rg") and region_ref[2:].isdigit():
                max_ref = max(max_ref, int(region_ref[2:]))
            for occurrence in raw.get("occurrences") or []:
                if not isinstance(occurrence, dict):
                    continue
                page_name = _text(occurrence.get("page_name"), limit=160)
                region_name = _text(occurrence.get("region_name"), limit=160)
                if not page_name or not region_name:
                    continue
                state_ids = []
                raw_state_ids = occurrence.get("state_ids") or []
                if not isinstance(raw_state_ids, list):
                    raw_state_ids = []
                legacy_state_id = _text(
                    occurrence.get("state_id"), limit=160)
                values = (
                    ([legacy_state_id] if legacy_state_id else [])
                    + raw_state_ids
                )
                for value in values:
                    state_id = _text(value, limit=160)
                    if state_id and state_id not in state_ids:
                        state_ids.append(state_id)
                visible_state_ids = []
                raw_visible_state_ids = occurrence.get(
                    "visible_state_ids") or []
                if not isinstance(raw_visible_state_ids, list):
                    raw_visible_state_ids = []
                for value in raw_visible_state_ids:
                    visible_state_id = _text(value, limit=160)
                    if (
                        visible_state_id
                        and visible_state_id not in visible_state_ids
                    ):
                        visible_state_ids.append(visible_state_id)
                occurrence_ref = _text(
                    occurrence.get("occurrence_ref"), limit=80)
                if not occurrence_ref:
                    occurrence_ref = f"ro{registry._next_occurrence}"
                    registry._next_occurrence += 1
                elif occurrence_ref.startswith("ro") and occurrence_ref[2:].isdigit():
                    registry._next_occurrence = max(
                        registry._next_occurrence,
                        int(occurrence_ref[2:]) + 1,
                    )
                state_by_page_state = occurrence.get(
                    "state_by_page_state") or {}
                if not isinstance(state_by_page_state, dict):
                    state_by_page_state = {}
                normalized_mapping = {
                    _text(page_state_id, limit=160): _text(
                        state_ref, limit=80)
                    for page_state_id, state_ref in state_by_page_state.items()
                    if _text(page_state_id, limit=160)
                    and _text(state_ref, limit=80)
                }
                observed_state_ref = _text(
                    occurrence.get("observed_state_ref"), limit=80)
                normalized = {
                    "occurrence_ref": occurrence_ref,
                    "page_name": page_name,
                    "region_name": region_name,
                    "representative_variant_name": _text(
                        occurrence.get("representative_variant_name"),
                        limit=160),
                    "state_ids": state_ids,
                    "visible_state_ids": visible_state_ids,
                    "observed_state_ref": observed_state_ref,
                    "state_by_page_state": normalized_mapping,
                    "inference_source_occurrence_ref": _text(
                        occurrence.get("inference_source_occurrence_ref"),
                        limit=80),
                }
                coverage_version = _nonnegative_int(
                    occurrence.get("coverage_version"))
                if coverage_version:
                    normalized["coverage_version"] = coverage_version
                    normalized["coverage_basis"] = _text(
                        occurrence.get("coverage_basis"), limit=80)
                if occurrence.get("reason"):
                    normalized["reason"] = _text(
                        occurrence.get("reason"), limit=500)
                group["occurrences"].append(normalized)
                registry._occurrences[
                    registry._occurrence_key(page_name, region_name)
                ] = region_ref
            if not group["state_definitions"]:
                default_ref = registry._new_state_definition(
                    group, summary="Initial observed state")
            else:
                default_ref = str(
                    group["state_definitions"][0].get("state_ref") or "")
            for occurrence in group["occurrences"]:
                if not occurrence.get("observed_state_ref"):
                    occurrence["observed_state_ref"] = default_ref
                mapping = occurrence.setdefault("state_by_page_state", {})
                for page_state_id in occurrence.get("state_ids") or []:
                    mapping.setdefault(
                        page_state_id, occurrence["observed_state_ref"])
            if not group.get("representative_occurrence_ref") and group[
                    "occurrences"]:
                group["representative_occurrence_ref"] = str(
                    group["occurrences"][0].get("occurrence_ref") or "")
            representative_occurrence_ref = str(
                group.get("representative_occurrence_ref") or "")
            for occurrence in group["occurrences"]:
                if (
                    occurrence.get("occurrence_ref")
                    != representative_occurrence_ref
                    and not occurrence.get("inference_source_occurrence_ref")
                ):
                    occurrence["inference_source_occurrence_ref"] = (
                        representative_occurrence_ref)
        registry._next_region = max(
            max_ref + 1, int(payload.get("next_region") or 1))
        registry._next_occurrence = max(
            registry._next_occurrence,
            int(payload.get("next_occurrence") or 1),
        )
        registry._next_state = max(
            registry._next_state,
            int(payload.get("next_state") or 1),
        )

        for page_key, state in (page_states or {}).items():
            for region in state.snapshot().get("regions") or []:
                region_name = str(region.get("name") or "").strip()
                region_ref = str(region.get("region_ref") or "").strip()
                if not region_name:
                    continue
                page_name = str(page_key)
                if region_ref and registry.has(region_ref):
                    registry.bind(
                        page_name=page_name,
                        region_name=region_name,
                        summary=str(region.get("summary") or ""),
                        equivalent_to_region_ref=region_ref,
                    )
                elif not registry.region_ref(page_name, region_name):
                    new_ref, _ = registry.bind(
                        page_name=page_name,
                        region_name=region_name,
                        summary=str(region.get("summary") or ""),
                    )
                    state.set_region_ref(region_name, new_ref)
        return registry


__all__ = [
    "AutonomousRegionRegistry",
    "AutonomousRegionState",
    "REGION_MAPPING_PROMPT",
    "REGION_MAPPING_SCHEMA",
    "REGION_REVIEW_PROMPT",
    "REGION_REVIEW_SCHEMA",
    "RegionProtocolError",
    "StaleFrameError",
    "_region_for_point",
    "normalize_bbox_1000",
    "screenshot_frame_id",
]
