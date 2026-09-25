"""Qwen autonomous Prompt assembly and compact natural-language history."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_protocol import (
    available_tool_catalog,
    protocol_prompt_for,
)


AUTONOMOUS_PROMPT = """\
你是 GUI 应用自主遍历主 Agent。你的产物是一份可复核的应用能力地图：页面、功能区域、用户可执行的操作，以及每项操作已经获得的证据。

遵守四条原则：
1. 以最新完整截图和当前任务为准。历史只用于理解已走路线、失败原因和仍有效约束；例如菜单打开后应按新截图定位，不能继续点击旧坐标。
2. 区分“值得记录”和“需要探索”。对以后理解或执行用户命令有意义的操作都应登记；只有可能显露新功能表面、影响其他功能区域，或解决有价值交互歧义时，才需要真实探索。例如上一项、下一项应登记但通常不必逐个试按；打开详情或编辑界面需要探索。静态文字不登记。
3. 区分观察事实和验证事实。截图只能证明控件存在及其可见语义；真实操作和结果复核才能证明效果、路线或能力。例如看见“下一项”可以登记该操作，不能据此声称已经验证切换成功。
4. 复核意见用于证据讨论，不替代视觉判断。先说明最新截图中具体看见的事实，再接受或纠正意见；不得把复核器提到但截图中看不到的对象复述成当前事实。

本轮只推进框架提供的当前任务和当前阶段。阶段完成后停止操作。证据不足时保留不确定或延期，不猜测。reason 只说明当前证据与选择；task_strategy 用一句可执行短句保存当前任务接下来的推进思路，不复述完整历史。

不要请求执行不可逆、外部提交、敏感或明显危险的操作；若它对用户命令有意义，只登记为待复核的只记录操作。临时表面只有确实阻止当前任务时才处理，也不能登记为目标应用功能。
"""


def build_system_prompt(
    *,
    app_name: str,
    platform: str,
    task_type: str,
    phase: str,
    has_pending_action: bool,
    pending_identity: bool,
    tool_catalog: Sequence[Dict[str, Any]],
) -> str:
    """Return one stable prefix for an exact main-Agent stage profile."""
    tool_definitions = _tool_prompt_view(
        tool_catalog,
        include_input_schemas=False,
    )
    return (
        AUTONOMOUS_PROMPT
        + "\n以下是主 Agent 可用工具的固定语义定义。具体参数和回复字段以本 system "
          "消息末尾的 JSON Schema 为准。\n"
        + json.dumps(tool_definitions, ensure_ascii=False)
    )


def _entry_review_feedback_text(record: Dict[str, Any]) -> str:
    """Render one complete Entry-review decision for another Agent."""

    def pairs(field_name: str) -> str:
        rendered = []
        for item in record.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            region_name = str(item.get("region_name") or "").strip()
            target = str(item.get("target") or "").strip()
            if region_name and target:
                rendered.append(f"{region_name} / {target}")
        return "；".join(rendered) if rendered else "无"

    deferred_regions = [
        str(name).strip() for name in record.get("deferred_regions") or []
        if str(name).strip()
    ]
    reason_consistent = record.get("reason_consistent")
    consistency = (
        "一致" if reason_consistent is True
        else "不一致" if reason_consistent is False
        else "未说明"
    )
    reviewer_reason = str(
        record.get("reviewer_reason")
        or record.get("reason")
        or "未提供理由"
    ).strip()
    lines = [
        "Entry Reviewer 的待核对意见如下；它不是最新截图的最终真值：",
        f"- 建议保留为独立入口：{pairs('kept')}",
        f"- 建议补充的漏报入口：{pairs('added')}",
        f"- 建议只记录、不派发探索：{pairs('recorded')}",
        f"- 建议丢弃：{pairs('dropped')}",
        f"- 建议延期：{pairs('deferred')}",
        "- 建议延期的 Region："
        + ("；".join(deferred_regions) if deferred_regions else "无"),
        f"- Reviewer 对主 Agent 理由的一致性判断：{consistency}",
        f"- Reviewer 原始理由：{reviewer_reason}",
    ]
    if pairs("deferred") != "无" or deferred_regions:
        lines.append(
            "- 延期表示当前证据不足，或目标有功能价值但正因可见前置条件而不可执行；保留相应 Region 和候选待办，取得真实新证据后再复核，不能据此关闭覆盖。"
        )
    status = str(record.get("status") or "")
    if status in {"disagreement", "final_disagreement"}:
        lines.append(
            "- 当前处理：双方尚未形成一致结论，因此上述候选和覆盖均未写入正式账本。"
        )
        if status == "final_disagreement":
            lines.append(
                "- 后续处理：同一可见证据下的讨论已经结束；取得新的 GUI 证据后再重新判断。"
            )
        else:
            lines.append(
                "- 下一步：先独立描述最新截图中的争议对象，再逐项回应 Reviewer；同意时修订候选，不同意时用具体可见证据说明并保留相应候选，然后重新提交完整 page_update。"
            )
    return "\n".join(lines)


def _natural_rejection_text(value: Any) -> str:
    """Project an internal rejection as prose without machine-only labels."""
    if not isinstance(value, dict):
        return str(value or "").strip()
    feedback = str(
        value.get("message")
        or value.get("reason")
        or value.get("feedback")
        or ""
    ).strip()
    correction = str(value.get("correction") or "").strip()
    if correction and correction.casefold() not in feedback.casefold():
        feedback = f"{feedback} 建议修正：{correction}".strip()
    return feedback


def _model_page_correction_text(item: Dict[str, Any]) -> str:
    """Describe a pending ledger correction without exposing runtime codes."""
    subject = str(
        item.get("target")
        or item.get("region_name")
        or item.get("field")
        or "这项页面信息"
    ).strip()
    reason = str(
        item.get("reason")
        or "当前证据不足以把这项信息写入正式页面账本"
    ).strip()
    lines = [f"{subject} 尚未写入正式账本：{reason}"]
    review = item.get("review")
    if isinstance(review, dict):
        issues = [
            str(value).strip()
            for value in (
                review.get("issues") or review.get("partition_issues") or []
            )
            if str(value).strip()
        ]
        if issues:
            lines.append("Reviewer 提出的待核对划分问题：" + "；".join(issues))
        reviewer_reason = str(review.get("reason") or "").strip()
        if reviewer_reason:
            lines.append("Reviewer 的待核对理由：" + reviewer_reason)
    proposed_regions = [
        str(region.get("name") or "").strip()
        for region in item.get("proposed_regions") or []
        if isinstance(region, dict) and str(region.get("name") or "").strip()
    ]
    if proposed_regions:
        lines.append("上一份提案中的 Region：" + "；".join(proposed_regions))
    if item.get("fixed_evidence_frame") is True:
        lines.append(
            "本次区域讨论若附有固定证据截图，区域划分只依据该图；当前最新"
            "截图仅用于判断是否出现了需要另行处理的临时变化。"
        )
    lines.append(
        "请先独立说明当前截图中的相关可见事实，再逐项接受或反驳 Reviewer "
        "意见，并重新提交完整提案。"
    )
    return "\n".join(lines)


def _model_region_record(item: Any) -> Dict[str, Any]:
    """Expose Region facts to a VLM without internal acceptance/hash fields."""
    if not isinstance(item, dict):
        return {}
    view = {
        key: deepcopy(item.get(key))
        for key in (
            "name", "summary", "survey_memory", "region_ref",
            "equivalence_reason",
        )
        if item.get(key) not in (None, "", [], {})
    }
    view["coverage"] = (
        "框架已有完成入口覆盖的记录"
        if item.get("coverage_complete") is True
        else "当前仍需检查主要功能入口覆盖"
    )
    return view


SAFE_CONTRACT_CORRECTION_PREFIX = "上一份回复违反了当前响应合同："


def _model_retry_correction(
    error: Any,
    *,
    contract_error: bool = False,
) -> str:
    """Return specific parser feedback without exposing backend diagnostics."""
    generic = (
        "上一份回复没有形成可执行、可解析的本轮判断。请根据同一截图重新检查"
        "本轮必填内容、可用工具和自然语言理由，不要沿用未验证的结论。"
    )
    text = " ".join(str(error or "").split())
    if not text:
        return generic
    if not contract_error:
        if text == generic:
            return text
        if "previous_action" in text.casefold():
            return (
                "上一份回复没有完整、可靠地说明前一 GUI 动作的可见结果。"
                "请重新比较动作前截图和当前截图，再填写本轮要求的前序动作判断。"
            )
        return generic
    if text.startswith(SAFE_CONTRACT_CORRECTION_PREFIX):
        return text[:1000]
    return (
        f"{SAFE_CONTRACT_CORRECTION_PREFIX}{text[:500]}。"
        "请只修正这个字段或当前阶段要求，保留未被指出且仍与截图一致的内容。"
    )


def _history_summary(
    history: Sequence[Dict[str, Any]],
    *,
    current_task_id: str = "",
) -> Dict[str, Any]:
    def page_update_feedback(record: Dict[str, Any]) -> str:
        page_name = str(record.get("screen") or "current page").strip()
        problems: List[str] = []
        for item in list(record.get("rejected_items") or [])[:6]:
            if not isinstance(item, dict):
                continue
            subject = str(
                item.get("target")
                or item.get("region_name")
                or item.get("field")
                or item.get("kind")
                or "page information"
            ).strip()
            reason = str(
                item.get("reason")
                or "the framework could not safely place this information in the current page ledger"
            ).strip()
            problems.append(f"{subject}: {reason}")
        if not problems:
            problems.append(
                "the framework could not safely place the submitted information "
                "in the current page ledger"
            )
        return (
            f"The following information was not written to page {page_name}: "
            f"{' | '.join(problems)}. Correct only these items; already accepted "
            "page facts are available in the latest page ledger."
        )[:1000]

    def compact(record: Dict[str, Any]) -> Dict[str, Any]:
        if (
            record.get("kind") == "entry_review_result"
            and record.get("status") in {
                "accepted", "inconsistent", "disagreement",
                "final_disagreement",
            }
        ):
            return {"entry_review_feedback": _entry_review_feedback_text(record)}
        if (
            record.get("kind") == "tool"
            and record.get("tool_name") == "review_entry_record"
            and isinstance(record.get("tool_result"), dict)
            and isinstance(record["tool_result"].get("data"), dict)
            and record["tool_result"]["data"].get("feedback")
        ):
            return {
                "entry_review_feedback": str(
                    record["tool_result"]["data"]["feedback"])
            }
        if (
            record.get("kind") == "page_update_result"
            and record.get("rejected_items")
        ):
            return {"feedback": page_update_feedback(record)}
        view = {
            key: record.get(key) for key in (
                "kind", "screen", "action", "target", "outcome", "status",
                "landed_screen", "accepted_regions", "created_entries",
                "matched_entries", "rejected_items", "remaining", "feedback",
            ) if record.get(key) not in (None, "", [], {})
        }
        validated_action = record.get("validated_action")
        if (
            record.get("kind") == "action"
            and isinstance(validated_action, dict)
            and isinstance(validated_action.get("arguments"), dict)
            and validated_action["arguments"]
        ):
            view["parameters"] = validated_action["arguments"]
            if validated_action.get("purpose"):
                view["purpose"] = validated_action["purpose"]
        action_review = record.get("action_review")
        if isinstance(action_review, dict) and action_review:
            view["review"] = {
                key: action_review.get(key)
                for key in ("decision", "observed_target", "risk", "reason")
                if action_review.get(key) not in (None, "")
            }
        if record.get("tool_name"):
            view["tool"] = record["tool_name"]
        tool_result = record.get("tool_result")
        if isinstance(tool_result, dict):
            data = tool_result.get("data")
            if isinstance(data, dict) and data.get("feedback"):
                return {"feedback": str(data["feedback"])[:1000]}
            else:
                result_view: Dict[str, Any] = {
                    "status": tool_result.get("status"),
                }
                if isinstance(data, dict):
                    kept = {
                        key: data.get(key) for key in (
                            "from", "to", "steps", "reported_current_page",
                            "framework_current_page", "reason",
                            "prerequisite_target", "status",
                        ) if data.get(key) not in (None, "", [], {})
                    }
                    if kept:
                        result_view["data"] = kept
                view["result"] = result_view
        rejection = record.get("rejection")
        if isinstance(rejection, dict):
            rejection_text = str(
                rejection.get("feedback")
                or rejection.get("message")
                or rejection.get("reason")
                or "The requested operation was not executed."
            )[:1000]
            rejection_text = _natural_rejection_text(rejection)
            subject = str(
                record.get("target") or record.get("screen") or ""
            ).strip()
            if subject and subject.casefold() not in rejection_text.casefold():
                rejection_text = f"{subject}: {rejection_text}"
            rejected_view: Dict[str, Any] = {
                "feedback": rejection_text[:1000],
            }
            for key in ("action", "target", "parameters"):
                if view.get(key) not in (None, "", [], {}):
                    rejected_view[key] = view[key]
            for key in ("remaining", "rejected_items"):
                if record.get(key) not in (None, "", [], {}):
                    rejected_view[key] = record[key]
            return rejected_view
        elif record.get("detail"):
            view["detail"] = str(record.get("detail"))[:800]
        return view

    scoped_history = list(history)
    task_id = str(current_task_id or "").strip()
    if task_id:
        scoped_history = [
            record for record in scoped_history
            if str(record.get("exploration_task_id") or "").strip()
            == task_id
        ]

    useful = [
        record for record in scoped_history
        if record.get("kind") != "stage_transition"
    ]
    numbered = [
        {"history_number": index, **compact(record)}
        for index, record in enumerate(useful, start=1)
    ]
    active_rejection = None
    if useful:
        latest = useful[-1]
        latest_status = str(latest.get("status") or "")
        tool_result = latest.get("tool_result")
        active_rejection = bool(
            isinstance(latest.get("rejection"), dict)
            or latest.get("rejected_items")
            or latest_status == "rejected"
            or (
                latest.get("kind") == "entry_review_result"
                and latest_status in {
                    "inconsistent", "disagreement", "final_disagreement",
                }
            )
            or (
                latest.get("kind") == "tool"
                and isinstance(tool_result, dict)
                and str(tool_result.get("status") or "") not in {
                    "", "accepted", "ok", "success",
                }
                and isinstance(tool_result.get("data"), dict)
                and tool_result["data"].get("feedback")
            )
        )
    summary: Dict[str, Any] = {
        "recent_results": numbered[:-1] if active_rejection else numbered,
    }
    latest_strategy = next((
        str(record.get("task_strategy") or "").strip()
        for record in reversed(scoped_history)
        if str(record.get("task_strategy") or "").strip()
    ), "")
    if latest_strategy:
        summary["task_strategy"] = latest_strategy[:240]
    if active_rejection:
        summary["active_rejection"] = numbered[-1]
    return summary


_NATURAL_HISTORY_RESULTS = {
    "accepted": "已经采用",
    "changed": "界面发生了可见变化",
    "complete": "已经完成",
    "deferred": "当前截图不足以可靠判断，暂时保留",
    "finish_accepted": "框架确认当前探索可以结束",
    "finish_rejected": "框架发现仍有未解决的探索事实",
    "inferred": "根据已验证的等价入口复用了结果",
    "entry_reviewer_reclassified": "独立复核认为它只是当前功能的内部控件",
    "not_independent_entry": "它不是需要单独探索的功能入口",
    "not_interactive": "该可见对象没有表现为可交互的功能入口",
    "no_visible_change": "界面没有出现可见变化",
    "discovered": "已经登记但尚未探索",
    "not_applicable": "本轮没有可复核的前序动作",
    "not_executed": "本次请求没有执行",
    "partial": "只完成了部分调查",
    "rejected": "本次提案没有被采用",
    "restored": "临时改动已经恢复",
    "temporarily_unavailable": "它在当前界面状态下暂时无法使用",
    "uncertain": "当前证据不足以可靠判断",
    "unreachable": "当前证据表明无法到达该入口",
    "unresolved": "这项入口仍未得到可靠结论",
    "unsafe": "当前证据不足以安全执行",
    "verified": "已经由实际界面结果验证",
}


def _natural_history_result(value: Any) -> str:
    """Translate runtime result labels before they enter a model prompt."""
    label = str(value or "").strip()
    if not label:
        return ""
    return _NATURAL_HISTORY_RESULTS.get(label.casefold(), "")


def _history_action_context(record: Dict[str, Any]) -> str:
    action = str(record.get("action") or "").strip()
    if not action:
        return ""
    target = str(record.get("target") or "").strip()
    context = " ".join(item for item in (action, target) if item)
    purpose = str(record.get("purpose") or "").strip()
    if purpose:
        context += f" purpose={purpose}"
    parameters = record.get("parameters")
    if isinstance(parameters, dict) and parameters:
        context += " parameters=" + json.dumps(
            parameters, ensure_ascii=False, separators=(",", ":"))
    return context


def _history_memory_text(records: Sequence[Dict[str, Any]]) -> str:
    """Render compact model-facing memory without ledger-shaped JSON."""
    lines: List[str] = []
    for record in records:
        prefix = f"{record.get('history_number', len(lines) + 1)}. "
        entry_review_feedback = str(
            record.get("entry_review_feedback") or ""
        ).strip()
        if entry_review_feedback:
            lines.append(prefix + entry_review_feedback)
            continue
        feedback = str(record.get("feedback") or "").strip()
        if feedback:
            context = _history_action_context(record)
            lines.append(
                prefix + (f"{context}: {feedback[:500]}" if context
                          else feedback[:500])
            )
            continue
        subject = _history_action_context(record) or str(
            record.get("target")
            or record.get("tool")
            or record.get("screen")
            or record.get("kind")
            or "上一事项"
        ).strip()
        outcome = _natural_history_result(
            record.get("outcome") or record.get("status"))
        detail = str(
            record.get("detail") or record.get("result_reason") or ""
        ).strip()
        review = record.get("review")
        if isinstance(review, dict) and review:
            review_text = "，".join(
                str(review.get(key) or "").strip()
                for key in ("decision", "observed_target", "risk", "reason")
                if str(review.get(key) or "").strip()
            )
            if review_text:
                detail = (
                    f"行动复核：{review_text}"
                    + (f"；{detail}" if detail else "")
                )
        landed = str(
            record.get("landed_screen") or record.get("landed_page") or ""
        ).strip()
        parts = [subject]
        if outcome:
            parts.append(outcome)
        if landed:
            parts.append(f"到达 {landed}")
        if detail:
            parts.append(detail[:500])
        if len(parts) == 1:
            parts.append("框架记录了这项结果，详情请结合当前截图判断")
        lines.append(prefix + "：".join(parts))
    return "\n".join(lines) if lines else "当前任务尚无历史记录。"


def _rejection_memory_text(record: Dict[str, Any]) -> str:
    entry_review_feedback = str(record.get("entry_review_feedback") or "").strip()
    if entry_review_feedback:
        return entry_review_feedback
    feedback = _natural_rejection_text(record)
    lines: List[str] = []
    context = _history_action_context(record)
    if context:
        lines.append(context)
    lines.append(
        feedback[:500] if feedback else "当前请求未被执行，请按反馈修正。")
    remaining = [
        str(item).strip() for item in record.get("remaining") or []
        if str(item).strip()
    ][:4]
    if remaining:
        lines.append("仍缺：" + "；".join(remaining))
    return "\n".join(lines)


def _task_status_lines(
    model_map: Dict[str, Any],
    active_rejection: Optional[Dict[str, Any]],
    task_strategy: str = "",
) -> List[str]:
    """Move active decision constraints out of repeated task/history fields."""

    def one_line(value: Any, limit: int = 320) -> str:
        return "；".join(str(value or "").splitlines()).strip()[:limit]

    lines: List[str] = []
    pending_action = model_map.pop("pending_action", None)
    if isinstance(pending_action, dict):
        history_number = int(pending_action.get("history_number") or 0)
        reference = f"历史第 {history_number} 条" if history_number else "最近一次"
        lines.append(
            f"待结算：{reference}真实动作；先根据动作前后图报告结果，不能跳过。")
    if isinstance(active_rejection, dict):
        rejection = one_line(_rejection_memory_text(active_rejection))
        if rejection:
            lines.append(f"当前纠正：{rejection}；不要原样重交。")

    task = model_map.get("task")
    if not isinstance(task, dict):
        return lines[:4]
    prerequisite = task.pop("前置重新检查", None)
    if isinstance(prerequisite, dict):
        target = one_line(prerequisite.get("目标"), 100)
        result = one_line(prerequisite.get("真实结果"), 180)
        detail = f"前置“{target}”已处理" if target else "前置任务已处理"
        if result:
            detail += f"，真实结果：{result}"
        lines.append(
            detail + "；当前目标仍须按最新截图重新确认，不能视为自动可用。")

    progress: List[str] = []
    strategy = one_line(task_strategy, 240)
    if strategy:
        progress.append(f"当前策略：{strategy}")
    last_result = one_line(task.pop("last_result", None), 220)
    if last_result:
        progress.append(f"最近结论：{last_result}")
    route_status = one_line(task.pop("route_status", None), 240)
    if route_status:
        progress.append(f"当前定位：{route_status}")
    region_survey = str(task.pop("region_survey", "") or "").strip()
    if region_survey and region_survey != "已完成":
        progress.append("所属区域调查尚未完成")
    if progress:
        lines.append("任务进展：" + "；".join(progress))
    return lines[:4]


def _rejection_feedback(
    reason_code: str,
    reason: str,
    *,
    suggested_next_tool: str = "",
    retry_after: str = "",
    correction: str = "",
) -> Dict[str, str]:
    """Return only the factual rejection needed for the next correction."""
    message = str(
        reason or "The requested operation was not executed.")[:500]
    feedback = message
    if correction:
        feedback += f" 建议修正：{str(correction)[:500]}"
    elif retry_after:
        feedback += " 请先满足上述条件或取得新的可见证据，再重试。"
    if suggested_next_tool:
        feedback += (
            f" 可考虑使用 {str(suggested_next_tool)[:120]} 完成这一步。")
    result = {
        "status": "rejected",
        "code": str(reason_code or "framework_rejected")[:120],
        "message": message,
        "feedback": feedback[:1000],
    }
    if correction:
        result["correction"] = str(correction)[:500]
    if retry_after:
        result["retry_after"] = str(retry_after)[:300]
    if suggested_next_tool:
        result["suggested_next_tool"] = str(suggested_next_tool)[:120]
    return result


def _stage_incomplete_no_action_detail(
    host: "AutonomousTraversalRuntime",
    *,
    stage_name: str,
    current_page: str,
) -> str:
    task = host.exploration_task
    if (
        stage_name in {"route_to_source", "route_to_page"}
        and task is not None
        and task.route_hint
    ):
        first_step = task.route_hint[0]
        route_from = str(first_step.get("from") or current_page).strip()
        route_via = str(first_step.get("via") or "visible route control").strip()
        route_to = str(first_step.get("to") or task.page_name).strip()
        return (
            f"{stage_name} stalled: current Page '{current_page}', target Page "
            f"'{task.page_name}', first known step '{route_from}' --"
            f"{route_via}--> '{route_to}'; no action was requested. If this "
            "step is visible, execute it; otherwise locate it from the current "
            "screenshot or use report_record_error if the route fact is wrong."
        )
    return (
        f"{stage_name} did not advance: no GUI action or new stable Page, "
        "Region, Entry, settlement, or restore fact was accepted."
    )


def _invalid_turn_correction(
    *,
    model_error: str,
    model_error_kind: str = "",
) -> str:
    if str(model_error_kind).strip() != "contract":
        return (
            "Return one valid turn using a declared tool and its argument schema, "
            "or action=null when only reporting a page_update or observation. "
            "If the previous call was rejected, use its factual reason and retry "
            "condition instead of repeating the same request."
        )
    safe_error = _model_retry_correction(
        model_error,
        contract_error=True,
    )
    return (
        "Previous model turn was rejected. "
        f"Use this factual reason: {safe_error} "
        "Return one valid turn using a declared tool and its argument schema, "
        "or action=null when only reporting a page_update or observation. "
        "If the previous call was rejected, use its factual reason and retry "
        "condition instead of repeating the same request."
    )


def _tool_prompt_view(
    tool_catalog: Sequence[Dict[str, Any]],
    *,
    include_input_schemas: bool,
) -> List[Dict[str, Any]]:
    """Keep execution metadata out of the model-facing tool explanation."""
    keys = ["name", "description"]
    if include_input_schemas:
        keys.insert(2, "input_schema")
    return [{key: item[key] for key in keys if key in item}
            for item in tool_catalog]


def _requires_entry_review(
    exploration_map: Optional[Dict[str, Any]],
) -> bool:
    task = (
        (exploration_map or {}).get("task")
        or (exploration_map or {}).get("exploration_task")
        or {}
    )
    return str(task.get("phase") or "").strip() == "review_entries"


def build_prompt(
    history: Sequence[Dict[str, Any]],
    *,
    app_name: str,
    platform: str,
    actions_used: int = 0,
    max_actions: int = 0,
    correction: str = "",
    exploration_map: Optional[Dict[str, Any]] = None,
    image_labels: Sequence[str] = (),
    continuation: bool = False,
    pending_identity: Optional[Dict[str, Any]] = None,
    tool_catalog: Optional[Sequence[Dict[str, Any]]] = None,
    include_tool_input_schemas: bool = True,
    include_static_prefix: bool = True,
    include_task_instructions: bool = True,
    include_app_context: bool = True,
    include_tool_catalog: bool = True,
    tool_names_only: bool = False,
) -> str:
    task = (
        (exploration_map or {}).get("task")
        or (exploration_map or {}).get("exploration_task")
        or {}
    )
    task_type = str(
        task.get("type") or task.get("task_type") or "survey_page")
    phase = str(task.get("phase") or "")
    task_instructions = protocol_prompt_for(
        task_type,
        "review_identity" if pending_identity else phase,
        has_pending_action=bool(
            (exploration_map or {}).get("pending_action")),
    )
    instructions = (
        "继续遵守本会话首轮的自主探索、事实归属和安全协议。先读取本轮任务、事实记录与图片顺序，"
        "不要依赖猜测补写页面身份或动作结果。\n" + task_instructions
        if continuation else AUTONOMOUS_PROMPT + task_instructions
    )
    if not continuation and not include_static_prefix:
        instructions = task_instructions if include_task_instructions else ""
    current_task_id = str(task.get("task_id") or "").strip()
    history_view = _history_summary(
        history, current_task_id=current_task_id)
    active_rejection = history_view.pop("active_rejection", None)
    task_strategy = str(history_view.pop("task_strategy", "") or "").strip()
    model_map = deepcopy(exploration_map or {})
    pending_action = model_map.get("pending_action")
    pending_operation = (
        str(pending_action.get("operation") or "").strip().casefold()
        if isinstance(pending_action, dict) else ""
    )
    if isinstance(pending_action, dict):
        pending_history_number = next((
            int(item.get("history_number") or 0)
            for item in reversed(history_view.get("recent_results") or [])
            if item.get("outcome") == "awaiting_observation"
            or "awaiting_observation" in str(item.get("detail") or "")
        ), 0)
        model_map["pending_action"] = {
            "history_number": pending_history_number,
        }
    task_status = _task_status_lines(
        model_map, active_rejection, task_strategy)
    model_task = model_map.get("task")
    page_history = ""
    if isinstance(model_task, dict):
        page_history = str(model_task.pop("page_history", "") or "").strip()
        for redundant_key in (
                "type", "phase", "resume_phase", "task_id"):
            model_task.pop(redundant_key, None)
    prompt = instructions
    if include_app_context:
        prompt += (
            f"\n当前应用：{app_name or '未知'}"
            f"\n运行平台：{platform or '未知'}"
        )
    prompt += (
        "\n\n自然语言全局地图（页面和页面联系，不含内部编号）：\n"
        + json.dumps(model_map, ensure_ascii=False)
        + "\n\n当前任务历史（按时间顺序）：\n"
        + _history_memory_text(history_view.get("recent_results") or [])
    )
    if pending_operation == "scroll":
        prompt += (
            "\n\n本次待结算操作是滚动。请根据动作前后截图判断实际内容是否移动、"
            "是否出现新的相关内容，以及这次滚动是否推进了当前阶段。"
            "单纯的像素变化不代表任务取得进展。"
        )
    if include_tool_catalog:
        prompt += (
            "\n\n本轮动态可用工具目录：\n"
            + json.dumps(
                [str(item.get("name") or "") for item in (
                    list(tool_catalog) if tool_catalog is not None
                    else available_tool_catalog(pending_identity=False)
                )]
                if tool_names_only else _tool_prompt_view(
                    list(tool_catalog) if tool_catalog is not None
                    else available_tool_catalog(pending_identity=False),
                    include_input_schemas=include_tool_input_schemas,
                ),
                ensure_ascii=False,
            )
        )
    if page_history:
        prompt += "\n\n当前页面的既有探索：\n" + page_history
    if task_status:
        prompt += (
            "\n\n当前探索任务状态（只列仍影响下一步的结论）：\n"
            + "\n".join(f"- {line}" for line in task_status)
        )
    if image_labels:
        prompt += "\n\n本轮所附图片按顺序为：\n" + json.dumps(
            list(image_labels), ensure_ascii=False)
    if correction:
        prompt += f"\n\n上一次回复无法执行：{correction}\n请根据同一截图重新判断。"
    if pending_identity:
        prompt += (
            "\n\n待复核 Page Identity（尚未登记）：\n"
            + json.dumps(pending_identity, ensure_ascii=False)
            + "\n本轮用 previous_tool_review.decision 接受、拒绝或保留不确定；"
              "框架先处理复核，再执行本轮工具。"
        )
    return prompt
