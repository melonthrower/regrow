"""Compact read-only Observer prompts."""

from __future__ import annotations

import json
from typing import Any, Dict


def _short(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _short_list(values) -> list[str]:
    return [_short(value, 80) for value in list(values or [])[:12]]


def build_transition_observer_prompt(context: Dict[str, Any]) -> str:
    """Validate the target name and record visible before/after facts."""
    target = _short(
        context.get("target") or context.get("activated_control"), 160)
    return f"""
你是一名 GUI 操作结果观察助手。

图 1 是执行操作前的完整截图，图 2 是执行操作后的最新完整截图。

本次实际操作的可见目标是：

{target}

先根据两张截图检查这个目标名称是否准确。

任务：
1. target：先独立识别图 1 中被操作的控件，再结合图 2 的直接结果，返回该控件最终应采用的语义。
2. observed_outcome：概括图 2 相对图 1 的主要可见变化。
3. relation_to_target：判断该变化与最终 target 的直接关系。

关系标签：

- related：观察到的变化中出现了与目标本身直接对应的可见文字、控件或内容。
- unrelated：截图明确显示发生了变化，但变化对应其他可见内容，与目标没有直接对应关系。
- no_relevant_change：没有观察到与目标相关的明显变化，或者只有时间、光标、动画等无关变化。
- uncertain：截图证据不足，无法可靠判断。

约束：
- 当前 target 只是待校验候选，不是可信事实，也不具有保留优先级。
- 先依据截图独立确定控件语义；若与该控件直接对应的可见文字或功能结果提供了更明确的名称，以该证据修正 target。
- target 描述控件本身的功能，不把无关结果页面的名称当作控件名称。
- 截图中有与控件直接对应的明确可见文字时，target 原样使用该文字，不添加或改写控件类型。
- 证据不足以确认更准确的名称时，target 原样返回“{target}”。
- observed_outcome 只写图 2 相对图 1 的可见差异，不复述操作过程；无明显变化时填写“未观察到明显视觉变化”。
- 不描述“目标被点击”等截图无法证明的过程，不判断操作成功或目标达成，不推测不可见原因。
- relation_to_target 必须基于最终 target，不据此反推原因或判断是否点错控件。

仅输出 JSON，不要解释或使用 Markdown：

{{
  "target": "",
  "observed_outcome": "",
  "relation_to_target": "related|unrelated|no_relevant_change|uncertain"
}}
""".strip()


def build_coverage_observer_prompt(context: Dict[str, Any]) -> str:
    """Judge whether a pending control matches one verified actual result."""
    evidence = {
        "current_interface": _short(context.get("current_interface"), 120),
        "pending_control": _short(context.get("pending_control"), 120),
        "pending_purpose": _short(context.get("pending_purpose"), 160),
        "pending_expected_effect": _short(
            context.get("pending_expected_effect"), 200),
        "representative_control": _short(
            context.get("representative_control"), 120),
        "representative_actual_results": _short_list(
            context.get("representative_actual_results")),
    }
    return "\n".join([
        "You are the read-only Observer. Decide whether the pending control and "
        "the verified representative establish the same functional result. "
        "Do not choose an action.",
        "Exact wording is not required: differently named controls may converge. "
        "However, shared placement or navigation-bar membership does not "
        "establish equivalence. Distinct tabs, destinations, or effects are "
        "different results.",
        "Compare the operation mechanism, the kind of interface or state change, "
        "and the subsequent functional space. When those are the same, a "
        "different parameter value or data instance is still the same functional "
        "result; the literal resulting value alone does not make it different.",
        "Use same_result only when the screenshot context and the representative's "
        "actual verified result establish convergence. Use different_result when "
        "they identify different destinations or effects, and uncertain when the "
        "evidence is insufficient.",
        "Evidence:",
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        "Return JSON only:",
        '{"verdict":"same_result|different_result|uncertain",'
        '"reason":"one short evidence-based reason"}',
    ])


__all__ = [
    "build_coverage_observer_prompt",
    "build_transition_observer_prompt",
]
