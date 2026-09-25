"""Qwen adapter for the explorer, Page relation, and Region identity roles."""

from __future__ import annotations

from pathlib import Path
from io import BytesIO
from typing import Any, Dict, Mapping, Optional, Sequence
import base64
import json

import requests
from PIL import Image

from .actions import _pixel_point
from .contracts import AgentTurn, ReportCorrections, parse_turn
from .prompts import (
    MAIN_SYSTEM_PROMPT,
    RESPONSE_SCHEMA,
    build_user_prompt,
    schema_instruction,
)
from ..visual_traversal.runtime.autonomous_agent import CodexAutonomousAgent


REGION_IDENTITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "current_region_ref": {"type": "string", "minLength": 1},
                "decision": {"type": "string", "enum": [
                    "reuse", "separate", "uncertain"]},
                "component_relation": {"type": "string", "enum": [
                    "same_complete_component",
                    "reconstructing_fragment",
                    "member_or_subregion",
                    "trigger_or_result",
                    "different_component",
                    "uncertain",
                ]},
                "causal_relation": {"type": "string", "enum": [
                    "none",
                    "known_operation_reveals_current",
                    "current_operation_reveals_known",
                    "uncertain",
                ]},
                "known_region_ref": {"type": "string"},
                "shared_operations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "current_operation_ref": {
                            "type": "string", "minLength": 1},
                        "known_operation_ref": {
                            "type": "string", "minLength": 1},
                        "reuse_level": {
                            "type": "string",
                            "enum": ["identity", "result"],
                        },
                    },
                    "required": [
                        "current_operation_ref", "known_operation_ref",
                        "reuse_level"],
                    "additionalProperties": False,
                }},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": [
                "current_region_ref", "decision", "component_relation",
                "causal_relation", "known_region_ref", "shared_operations",
                "reason"],
            "additionalProperties": False,
        }},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["decisions", "reason"],
    "additionalProperties": False,
}


REGION_IDENTITY_PROMPT = """\
父容器相同或占据同一内容槽，只能作为召回线索，不能单独证明子区身份。若两个子区承担不同具体功能组，字段与控件职责整体改变，应separate；不能用共同父级的宽泛业务目标代替子区自身的功能上下文。数据列表仅更换成员且浏览/选择职责与结构不变时，仍可共享列表Region的不同Variant，不要求具体数据标签相同。

包含层级与身份复用分别判断。current_regions中的parent_region_ref/child_region_refs表示本次观察的父子关系，父区与子区不能合并为同一身份。子区可以是在共同容器内的不同功能组；不要求子区拥有整个父窗口，也不能仅因子区缺少父区其他控件而将其自身判断为不完整。应比较同一功能槽和边界，避免把同一父区的不同子功能按reconstructing_fragment合并。

你判断本批观察到的 Region 是否与候选截图中的 Region 属于同一个全局 Region。图1是最新完整截图，但本批区块可能来自不同滚动位置，并不同时可见。每个当前 Region 的 images 列出其实际观察图，Operation 的 images 列出该操作真实可见的图；必须按这些图核对，不能假定都在图1。候选侧 image 指明旧 State 的截图。每个当前 Region 的 source_transition 是它首次登记时对应的真实动作及来源 Region，before_image 是该动作前图；只用于该区块的显露因果判断，不把最后一次滚动套给整批区块。文字表给出名称、摘要、本地 Operation 和候选侧真实 verified_result。每个 current_region_ref 必须恰好判断一次，不修改或创造编号。

source_transition 只说明进入当前 State 的真实动作，不证明截图中的变化都由它造成，也不自动证明两个 Region 应合并或分开。主 Agent 可以省略无关变化；未报告本身不是错误，不要求补齐全部画面变化。只审核本批已提供的区块；仅在真实动作及前后截图支持因果时补充显露关系，不能仅凭“点击后出现”补边，明确的外部或不确定归因不能通过补漏覆盖。无因果用none，证据不足沿用uncertain。必须比较前后完整截图中功能对象、可交互范围以及共同出现、消失或替换的边界。新内容与来源组件可以同时存在：新内容拥有自己的交互上下文和独立可见性边界时，将它与仍然存在的来源 Region 分开；只在同一组件边界内替换成员、选中状态或局部内容时，才复用该 Region 并建立 Variant。不按屏幕位置或控件类型决定，也不按动作名称猜测边界。

Region 是目标应用中共享局部上下文和变化边界的功能组件；Element 是 Region 内拥有明确交互落点的控件。边界由功能对象、稳定应用槽和共同显示/隐藏、替换、滚动、展开或聚焦的变化范围决定，不由面积、边框或控件数量决定。一个只有单个按钮的功能表面仍可是完整 Region；“单成员”不是否决条件。但列表中一个无独立边界的重复成员、表单中一个局部字段，通常只是更大 Region 的 Element；重复列表项共同组成一个列表 Region。同一组件的展开、选中、滚动位置和普通数据变化通常只形成 RegionVariant。若代表项展开后显露一组共同出现/消失、服务于该对象且可独立完成用户任务的完整任务上下文，即使内联显示在列表成员内部，也属于新的结果 Region；触发展开的 Element 仍属来源列表 Region。菜单、对话框、抽屉、选择器或底部面板显露后，若形成独立交互上下文，也属于新 Region。操作系统栏、键盘、桌面、宿主窗口、其他应用、toast、tooltip 和装饰不属于目标应用 Region。Region 名称必须描述跨 Variant 稳定的功能槽，不能使用 Expanded、Selected、当前数据值或某个成员名称。

component_relation 只报告表面边界：单个当前完整表面与候选满足上述同一性时用 same_complete_component；当前清点若把候选截图中已经完整存在的同一功能表面拆成至少两个列表成员、表单分区或其他局部片段，而这些片段合起来覆盖该表面，就全部用 reconstructing_fragment；只有单个成员或当前片段集合仍未覆盖候选完整表面时用 member_or_subregion；入口相对它显露的新表面用 trigger_or_result；其余用 different_component 或 uncertain。不要为了迁就当前名称而把局部片段解释成完整组件，也不要把同类应用栏、列表、表单或对话框一概视为同一个功能对象。causal_relation 独立报告跨表面因果：候选 Operation 显露当前表面用 known_operation_reveals_current，反向用 current_operation_reveals_known，没有跨表面显露用 none，看不清用 uncertain。verified_result 只作为因果证据。

reuse 只允许 same_complete_component 或一组共同指向同一候选的 reconstructing_fragment，并且 causal_relation 必须为 none；单个片段不能复用完整组件。trigger_or_result 必须 separate 并给出显露方向。无source_transition时不报告trigger_or_result：边界明确不同可用separate/different_component及causal_relation=none或uncertain；身份也不清楚才将decision、component_relation、causal_relation全设uncertain。组件与比较候选不同，不排除另一个 source_transition 的实际操作显露该组件：separate 的表面边界判断和来源动作因果分别依据各自证据，不为满足字段组合改写视觉判断。known_operation_reveals_current 必须有精确 source_transition 及前后图支持；没有因果证据用 none，看不清用 uncertain。身份本身证据不足时 decision、component_relation 和 causal_relation 都用 uncertain。separate/uncertain 的 shared_operations 必须为空，known_region_ref 留空。

Region reuse 不自动合并 Operation。当前侧只列本批保存帧实际观察到的 ElementOperation 与 RegionOperation，是否可见以各项 images 为准；候选 Region 的 operations 是该 Region 已登记的完整 canonical Operation 目录，不只限于候选截图所在 Variant。每项都有 canonical_operation_ref；visible_in_candidate_state=false 表示该 Operation 属于同一 Region 的其他 Variant，不能据此补画当前截图中不存在的控件，但可以与当前截图中明确可见、功能对象一致的 Operation 提出 identity 候选。Region Reviewer 根据当前完整截图和目录提出 shared_operations；不同 provisional canonical_operation_ref 只是框架尚未合并的临时编号，不是“不共享”的证据。shared_operations 只作为候选，后续独立的批量 Operation Reviewer 才决定是否落账。候选只列“owner scope + 动作 + direction”一致，并按“动作 + 作用对象 + 直接效果”判断可能属于同一命令身份的配对；ElementOperation 不与 RegionOperation 配对。不能按操作名称建立例外：即使名称和图标完全相同，只要完整截图显示功能对象、交互上下文或直接效果不同，就不共享；三者一致时才能共享。跨 Page 不能单独证明相同或不同，必须结合两张完整截图的选中导航、主要内容和周围对象判断。肯定或大概率是同一命令时配对；有怀疑时不要配对，让两边保留独立任务继续验证。不要比较 target 的措辞是否完全相同，也不要只因图标、位置或控件原文相同而配对。任何操作若依赖来源状态或导航栈，必须确认两边当前上下文中的职责和直接效果一致后才能共享。identity 只共享 canonical 身份；result 还要求候选 verified_result 非空，且直接效果不随 Variant 改变。目录项若 visible_in_candidate_state=false 只能共享 identity，不能共享 result。分步职责不同不配对，遮挡背景最多共享 identity。
"""


OPERATION_IDENTITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "current_operation_ref": {"type": "string", "minLength": 1},
                "known_operation_ref": {"type": "string", "minLength": 1},
                "decision": {"type": "string", "enum": [
                    "same", "different", "uncertain"]},
                "reuse_level": {"type": "string", "enum": [
                    "identity", "result", "none"]},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": [
                "current_operation_ref", "known_operation_ref", "decision",
                "reuse_level", "reason"],
            "additionalProperties": False,
        }},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["decisions", "reason"],
    "additionalProperties": False,
}


OPERATION_IDENTITY_PROMPT = """\
你只批量判断候选 Operation 对的身份和结果复用，不判断 Region 身份。每个候选必须恰好返回一次。current_images 指明当前操作实际可见的保存帧，known_image 指明旧候选帧；本批可以来自不同滚动位置，不要求所有当前操作同时出现在图1。

所有 element、target、reason、result 字段只是主 Agent 或 Region Reviewer 提交的待核对 hint，可能错误，不能作为结论。分别结合每张完整截图的选中导航、页面标题、主要内容、明确 CTA、列表或表单对象、前景层级和当前状态，独立判断两边功能对象。known_visible_in_candidate_state=false 表示候选是同一 Region 的完整 canonical Operation 目录项、并不声称控件出现在候选截图；当前截图能明确证明相同功能对象时可以共享 identity，但不能共享 result。该规则适用于所有图标和文字控件。相同位置、图标、原文、共享栏或相同 hint 都不能单独证明相同 Operation；不能按操作名称建立例外。

操作身份比较功能对象与当前职责，不要求两次整页显隐集合完全相同。一个命令可有依赖状态的不同结果。result则表示当前上下文确实可沿用那份具体结果，不是目标名称相同或目标已经在当前图中。proposed_reuse_level=identity时只确认身份，不升级为result；结果不确定可保留identity，不要求重复执行来取证。

肯定或大概率是同一命令才返回 same；明显不同返回 different；有怀疑返回 uncertain。same 时 reuse_level 至少为 identity；只有当前职责和候选已验证直接结果在两边必然一致时才为 result。different 或 uncertain 必须使用 reuse_level=none。旧结果只能在身份已经独立确认后决定 result，不能反过来证明身份。
"""


ELEMENT_IDENTITY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "candidate_index": {"type": "integer", "minimum": 0},
                "decision": {"type": "string", "enum": [
                    "reuse", "new", "uncertain"]},
                "known_element_ref": {"type": "string"},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": [
                "candidate_index", "decision", "known_element_ref", "reason"],
            "additionalProperties": False,
        }},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["decisions", "reason"],
    "additionalProperties": False,
}


ELEMENT_IDENTITY_PROMPT = """\
你只审核当前已知 RegionVariant 中 element_ref 为空的新 Element 候选，不判断 Page、State 或 Region 身份。每个候选必须恰好返回一次。

结合当前完整截图、候选名称与操作，以及该 RegionVariant 已登记的 Element ref 和操作，判断候选是否只是同一控件的改名、分组方式变化或重复报告。若是同一可交互落点，返回 reuse 和精确 known_element_ref；只有截图中确实存在一个与所有已知 Element 不同、可独立接收该操作的新控件时才返回 new；证据不足返回 uncertain。候选把单个按钮改写成“按钮组”不自动构成新 Element，应找到真正发起该 Operation 的现有按钮。不要按列表顺序、名称相似度或 target 字符串直接猜测。
同类控件不等于同一个控件：不同的可交互落点不能共享Element身份。同一报告的不同Element条目不得复用同一个known_element_ref；同一控件的重复描述应合为一条。已知项若只是多个控件的概括，不能因为候选属于该类别就复用它；应判断候选自己的实际落点。同类代表覆盖属于Operation层，不在这里把不同按钮合并。
"""


class QwenExplorerAgent:
    def __init__(
        self,
        *,
        transport: Any,
        model: str,
        output_root: str,
        timeout: int = 120,
    ) -> None:
        self.transport = transport
        self.model = str(model or "").strip()
        self.timeout = int(timeout)
        self.debug_path = Path(output_root) / "_modular_debug.jsonl"
        if hasattr(self.transport, "model_version"):
            self.transport.model_version = self.model

    def _debug(self, payload: Mapping[str, Any]) -> None:
        self.debug_path.parent.mkdir(parents=True, exist_ok=True)
        with self.debug_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _call(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        screenshots: Sequence[bytes],
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if response_schema is not None:
            user_prompt += "\nJSON Schema: " + json.dumps(response_schema, ensure_ascii=False)
        raw, prompt_tokens, completion_tokens, attempts = (
            self.transport.predict_mm_with_policy(
                user_prompt,
                list(screenshots),
                max_attempts=1,
                timeout_seconds=float(self.timeout),
                system_prompt=system_prompt,
            )
        )
        parsed = self.transport.parse_json(raw)
        self._debug({
            "role": role,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": str(raw or ""),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "transport_attempts": attempts,
            "prompt_tokens_details": dict(getattr(
                self.transport, "last_prompt_tokens_details", {}) or {}),
        })
        if not isinstance(parsed, dict):
            raise ValueError("模型回复不是一个有效 JSON 对象")
        return parsed

    def decide(
        self,
        *,
        context: Dict[str, Any],
        screenshots: Sequence[bytes],
        has_pending_action: bool,
        pending_attempt_id: str = "",
        corrections: Optional[ReportCorrections] = None,
    ) -> AgentTurn:
        if screenshots:
            with Image.open(BytesIO(screenshots[-1])) as image:
                width, height = image.size
            geometry = {
                "width": width, "height": height,
                "point_1000": (
                    "最新整屏各轴独立归一化到0..1000：左上[0,0]、右下[1000,1000]。"
                    "不是像素或Region局部坐标。像素点(px,py)应转换为"
                    "[1000*px/(width-1),1000*py/(height-1)]。"),
            }
            pending = context.get("待结算动作详情") or {}
            if len(screenshots) == 2 and pending.get("point_1000") is not None:
                with Image.open(BytesIO(screenshots[0])) as image:
                    geometry["pending_image_size"] = list(image.size)
                geometry["pending_action_pixel"] = list(
                    _pixel_point(screenshots[0], pending["point_1000"]))
            context = {**context, "截图坐标": geometry}
        correction = ""
        error = ""
        for _attempt in range(1 if corrections is not None else 2):
            from .prompts import submission_schema
            schema = submission_schema(context.get('本轮提交合同'))
            user_prompt = build_user_prompt(context, correction=correction)
            from .knowledge_retrieval import check_dynamic_budget
            check_dynamic_budget(user_prompt)
            try:
                raw = self._call(
                    role="modular_main_agent",
                    system_prompt=(MAIN_SYSTEM_PROMPT
                                   + schema_instruction(schema)),
                    user_prompt=user_prompt,
                    screenshots=screenshots,
                    response_schema=schema,
                )
                if (raw.get("type") == "object"
                        and isinstance(raw.get("properties"), Mapping)):
                    raw = dict(raw["properties"])
                page_report = raw.get("page_report")
                report_action = raw.get("action")
                ownerless_back = (
                    isinstance(report_action, Mapping)
                    and report_action.get("kind") == "back"
                    and not report_action.get("owner_ref")
                    and not report_action.get("operation_ref"))
                if (isinstance(page_report, Mapping)
                        and page_report.get("survey_complete") is True
                        and report_action is not None and not ownerless_back):
                    raw = dict(raw)
                    raw["action"] = None
                return parse_turn(
                    raw,
                    has_pending_action=has_pending_action,
                    pending_attempt_id=pending_attempt_id,
                    submission=context.get("本轮提交合同"),
                )
            except (TypeError, ValueError) as exc:
                if corrections is not None:
                    raise
                error = str(exc)[:500]
                correction = "请只修正这个具体问题：" + error
        raise ValueError(error or "主 Agent 两次回复都不符合合同")

    def correspond_regions(
        self,
        *,
        payload: Dict[str, Any],
        screenshots: Sequence[bytes],
        correction: str = "",
    ) -> Dict[str, Any]:
        user_prompt = "输入：\n" + json.dumps(
            payload, ensure_ascii=False, indent=2)
        if str(correction or "").strip():
            user_prompt += (
                "\n\n上一回复未通过运行时合同。只修正以下问题并重新输出完整"
                " decisions：\n" + str(correction).strip()
            )
        result = self._call(
            role="modular_region_identity",
            system_prompt=(REGION_IDENTITY_PROMPT
                           + schema_instruction(REGION_IDENTITY_SCHEMA)),
            user_prompt=user_prompt,
            screenshots=screenshots,
        )
        properties = result.get("properties")
        if (not isinstance(result.get("decisions"), list)
                and result.get("type") == "object"
                and isinstance(properties, Mapping)
                and isinstance(properties.get("decisions"), list)):
            return dict(properties)
        return result

    def review_partition(self, *, payload: Dict[str, Any],
                         screenshots: Sequence[bytes]) -> Dict[str, Any]:
        from .partition_review import PROMPT, SCHEMA
        return self._call(role="modular_region_identity",
            system_prompt=PROMPT + schema_instruction(SCHEMA),
            user_prompt="新清单分区核验：\n" + json.dumps(payload, ensure_ascii=False),
            screenshots=screenshots, response_schema=SCHEMA)

    def review_known_state(self, *, payload: Dict[str, Any],
                           screenshots: Sequence[bytes]) -> Dict[str, Any]:
        from .state_review import PROMPT, SCHEMA
        return self._call(role="modular_region_identity",
            system_prompt=PROMPT + schema_instruction(SCHEMA),
            user_prompt="已知State复用核验：\n" + json.dumps(payload, ensure_ascii=False),
            screenshots=screenshots, response_schema=SCHEMA)

    def review_region_refinement(
        self, *, payload: Dict[str, Any], screenshots: Sequence[bytes],
    ) -> Dict[str, Any]:
        from .region_refinement import REVIEW_PROMPT, REVIEW_SCHEMA
        return self._call(
            role="modular_region_identity",
            system_prompt=REVIEW_PROMPT + schema_instruction(REVIEW_SCHEMA),
            user_prompt="输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2),
            screenshots=screenshots, response_schema=REVIEW_SCHEMA,
        )

    def review_operation_identities(
        self,
        *,
        payload: Dict[str, Any],
        screenshots: Sequence[bytes],
    ) -> Dict[str, Any]:
        result = self._call(
            role="modular_operation_identity",
            system_prompt=(OPERATION_IDENTITY_PROMPT
                           + schema_instruction(OPERATION_IDENTITY_SCHEMA)),
            user_prompt="输入：\n" + json.dumps(
                payload, ensure_ascii=False, indent=2),
            screenshots=screenshots,
        )
        properties = result.get("properties")
        if (not isinstance(result.get("decisions"), list)
                and result.get("type") == "object"
                and isinstance(properties, Mapping)
                and isinstance(properties.get("decisions"), list)):
            return dict(properties)
        return result

    def review_element_identities(
        self,
        *,
        payload: Dict[str, Any],
        screenshots: Sequence[bytes],
    ) -> Dict[str, Any]:
        result = self._call(
            role="modular_element_identity",
            system_prompt=(ELEMENT_IDENTITY_PROMPT
                           + schema_instruction(ELEMENT_IDENTITY_SCHEMA)),
            user_prompt="输入：\n" + json.dumps(
                payload, ensure_ascii=False, indent=2),
            screenshots=screenshots,
        )
        properties = result.get("properties")
        if (not isinstance(result.get("decisions"), list)
                and result.get("type") == "object"
                and isinstance(properties, Mapping)
                and isinstance(properties.get("decisions"), list)):
            return dict(properties)
        return result

class CodexExplorerAgent(QwenExplorerAgent):
    """Use the existing structured Codex CLI caller for modular roles."""

    def __init__(
        self,
        *,
        model: str,
        output_root: str,
        timeout: int = 300,
    ) -> None:
        self.model = str(model or "").strip()
        self.timeout = int(timeout)
        self.debug_path = Path(output_root) / "_modular_debug.jsonl"
        self.backend = "codex_cli"
        self.codex = CodexAutonomousAgent(
            self.model, output_root, timeout=self.timeout)

    def _call(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        screenshots: Sequence[bytes],
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        schemas = {
            "modular_main_agent": RESPONSE_SCHEMA,
            "modular_region_identity": REGION_IDENTITY_SCHEMA,
            "modular_operation_identity": OPERATION_IDENTITY_SCHEMA,
            "modular_element_identity": ELEMENT_IDENTITY_SCHEMA,
        }
        response_schema = response_schema or schemas.get(role)
        if response_schema is None:
            raise ValueError(f"unsupported modular Codex role: {role}")
        result = self.codex.invoke_specialist(
            tool_name=role,
            prompt=user_prompt,
            screenshots=list(screenshots),
            response_schema=response_schema,
            system_prompt=system_prompt,
        )
        self._debug({
            "role": role,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": json.dumps(result, ensure_ascii=False),
            "prompt_tokens": (getattr(
                self, "_last_api_usage", {}) or {}).get("input_tokens"),
            "completion_tokens": (getattr(
                self, "_last_api_usage", {}) or {}).get("output_tokens"),
            "transport_attempts": 1,
            "prompt_tokens_details": dict((getattr(
                self, "_last_api_usage", {}) or {}).get(
                    "input_tokens_details") or {}),
            "output_tokens_details": dict((getattr(
                self, "_last_api_usage", {}) or {}).get(
                    "output_tokens_details") or {}),
            "backend": self.backend,
            "model": self.model,
            "effective_model": (
                str(getattr(self, "_last_effective_model", "") or "").strip()
                or self.model),
        })
        return result


class OpenAIAPIExplorerAgent(CodexExplorerAgent):
    """Call an OpenAI-compatible Responses endpoint for modular roles."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        reasoning_effort: str,
        output_root: str,
        timeout: int = 300,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.reasoning_effort = str(reasoning_effort or "medium").strip()
        self.timeout = int(timeout)
        self.debug_path = Path(output_root) / "_modular_debug.jsonl"
        self.backend = "openai_api"
        self.codex = self
        self._last_api_usage: Dict[str, Any] = {}
        self._last_effective_model = ""

    def invoke_specialist(
        self,
        *,
        tool_name: str,
        prompt: str,
        screenshots: Sequence[bytes],
        response_schema: Dict[str, Any],
        system_prompt: str,
    ) -> Dict[str, Any]:
        content: list[Dict[str, Any]] = [{
            "type": "input_text",
            "text": prompt,
        }]
        for screenshot in screenshots:
            image = bytes(screenshot)
            mime_type = (
                "image/jpeg" if image.startswith(b"\xff\xd8") else "image/png")
            encoded = base64.b64encode(image).decode("ascii")
            content.append({
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded}",
            })
        payload = {
            "model": self.model,
            "instructions": system_prompt,
            "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"format": {
                "type": "json_schema",
                "name": tool_name,
                "schema": response_schema,
                "strict": True,
            }},
            "store": False,
        }
        response = None
        for request_attempt in range(2):
            try:
                response = requests.post(
                    self.base_url + "/responses",
                    headers={
                        "Authorization": "Bearer " + self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                break
            except requests.RequestException as exc:
                if request_attempt == 0:
                    continue
                raise RuntimeError(
                    "Responses API request failed: " + type(exc).__name__
                ) from None
        if response is None:
            raise RuntimeError("Responses API request failed")
        try:
            response.raise_for_status()
        except requests.RequestException:
            raise RuntimeError(
                f"Responses API request failed: HTTP {response.status_code}"
            ) from None
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("Responses API returned invalid JSON") from None
        if not isinstance(body, Mapping):
            raise RuntimeError("Responses API returned an invalid response object")
        output_text = body.get("output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            parts = []
            for item in body.get("output") or []:
                if not isinstance(item, Mapping):
                    continue
                for block in item.get("content") or []:
                    if (isinstance(block, Mapping)
                            and block.get("type") == "output_text"
                            and isinstance(block.get("text"), str)):
                        parts.append(block["text"])
            output_text = "".join(parts)
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("Responses API response has no output_text")
        try:
            result = json.loads(output_text)
        except json.JSONDecodeError:
            raise RuntimeError("Responses API output_text is not valid JSON") from None
        if not isinstance(result, dict):
            raise RuntimeError("Responses API output_text is not a JSON object")
        usage = body.get("usage")
        self._last_api_usage = dict(usage) if isinstance(usage, Mapping) else {}
        self._last_effective_model = str(body.get("model") or "").strip()
        return result

__all__ = [
    "CodexExplorerAgent",
    "ELEMENT_IDENTITY_SCHEMA",
    "OpenAIAPIExplorerAgent",
    "OPERATION_IDENTITY_SCHEMA",
    "QwenExplorerAgent",
    "REGION_IDENTITY_SCHEMA",
]
