"""Prompts for model-led traversal decisions."""

from __future__ import annotations

import json


def _entry_rows(context):
    rows = []
    for item in context.get("function_entries") or []:
        if not isinstance(item, dict):
            continue
        row = {
            "target": str(item.get("target") or ""),
            "area": str(item.get("region_name") or ""),
            "exploration_status": str(
                item.get("exploration_status") or "untried"),
            "status_detail": str(item.get("status_detail") or ""),
            "attempts": list(item.get("previous_results") or []),
            "problems": list(item.get("framework_feedback") or []),
        }
        entry_id = str(item.get("entry_id") or "")
        if entry_id:
            row["entry_id"] = entry_id
        rows.append(row)
    return rows


def build_explorer_prompt(context, *, platform: str = "") -> str:
    """Ask the Explorer model to choose the next visible entry."""
    feedback = str(context.get("framework_feedback") or "").strip()
    feedback_section = (
        f"\n框架对上一项意见的反馈：\n{feedback}\n"
        if feedback else ""
    )
    return f"""
你是一名 GUI 应用探索助手。

图 1 是应用的最新完整截图。你的目标是自主决定当前最值得尝试的下一步，以发现尚未观察到的功能界面或功能入口。

应用：{str(context.get("application_name") or "")}
当前界面：{str(context.get("current_interface") or "")}
平台：{platform}

下面是框架此前在当前界面中观察并保存的目标记录：

{json.dumps(_entry_rows(context), ensure_ascii=False)}
{feedback_section}
带 entry_id 的记录是本轮可选入口；没有 entry_id 的记录只说明同一稳定目标此前已经探索或已经遇到问题，不能再次选择。记录不是必须依次执行的指令。它们可能存在命名误差、已经不在当前前景界面，或被新的前景内容遮挡；以图 1 中当前最前方、实际接收操作的界面为准。

你可以自由选择任意一个入口，不必遵循列表顺序。只有当该入口当前可见、可操作，并且尝试它有助于继续了解应用时才选择。

每条记录中的 exploration_status、attempts 和 problems 都来自此前真实执行、定位或核验。请把它们与同一条记录中的 target 和 area 一起理解，据此避免机械重复无效选择；如果一个仍带 entry_id 的目标在当前截图中已经改变并明确支持重试，仍可再次选择。

框架会在你提出选择后独立完成当前帧定位、点击位置核验、动作执行和结果观察，并把成功或失败事实反馈给后续判断。不要输出坐标，也不要假定动作一定成功。

如果截图中没有任何候选可以可靠执行，返回 null 并说明直接可见的原因。不要仅为了建立返回路径而离开仍有可探索内容的当前界面。

只输出以下两种 JSON 之一，不要输出其他文字：

{{"selected_entry_id":"e0","reason":"选择该入口的简短理由"}}
{{"selected_entry_id":null,"reason":"当前不执行任何候选的直接可见原因"}}
""".strip()


def build_route_choice_prompt(context) -> str:
    """Ask the Explorer model which known interface to revisit next."""
    feedback = str(context.get("framework_feedback") or "").strip()
    feedback_section = (
        f"\n框架对上一项意见的反馈：\n{feedback}\n"
        if feedback else ""
    )
    pages = []
    for item in context.get("candidate_pages") or []:
        if not isinstance(item, dict):
            continue
        pages.append({
            "page_id": str(item.get("page_id") or ""),
            "name": str(item.get("name") or ""),
            "pending_entries": list(item.get("pending_entries") or []),
            "pending_regions": list(item.get("pending_regions") or []),
            "previous_route_feedback": list(
                item.get("previous_route_feedback") or []),
        })
    return f"""
你正在自主探索一个 GUI 应用。

图 1 是当前最新完整截图。当前界面的本地入口已经处理完毕，下面这些已知界面仍有待探索内容。请选择下一处继续探索的界面。

应用：{str(context.get("application_name") or "")}
当前界面：{str(context.get("current_interface") or "")}

{json.dumps(pages, ensure_ascii=False)}
{feedback_section}
page_id 只在本次选择中有效。你负责选择探索方向；框架随后使用已有的真实动作边前往该界面，并把实际到达位置或失败原因反馈给你。不要提出坐标或具体返回步骤。

如果这些界面根据现有信息都不适合继续，返回 null 并说明原因。

只输出以下两种 JSON 之一，不要输出其他文字：

{{"selected_page_id":"p0","reason":"选择该界面的简短理由"}}
{{"selected_page_id":null,"reason":"当前不前往任何候选的理由"}}
""".strip()


def build_element_exploration_prompt(context) -> str:
    """Ask one target Agent for identity context and a direct safe action."""
    goal = dict(context.get("goal") or {})
    task_memory = dict(context.get("task_memory") or {})
    if not task_memory and context.get("task_history") is not None:
        task_memory = {
            "events": list(context.get("task_history") or []),
            "older_events_omitted": 0,
        }
    phase_guidance = (
        "目标动作已经由框架验证。不要再次点击目标；可以执行一次直接返回/关闭来发现返回关系，"
        "回到目标来源页后任务会自动结束。若没有合适返回动作，立即 FINISH。"
        if task_memory.get("phase") == "goal_verified_return_optional"
        else "目标尚未验证，继续寻找并执行目标或必要的路线/恢复动作。"
    )
    feedback = str(context.get("framework_feedback") or "").strip()
    feedback_section = (
        f"\n框架对上一份回复的反馈：\n{feedback}\n"
        if feedback else ""
    )
    return f"""
你是 GUI-ReWalk 中负责一个按钮目标的短期探索 Agent。图 1 是当前最新完整截图。

当前任务：探索“{str(goal.get('target') or '')}”。

应用：{str(context.get('application_name') or '')}
当前界面：{str(context.get('current_interface') or '')}
目标最初所在界面：{str(goal.get('source_page') or '')}
目标所在区域：{str(goal.get('region_name') or '')}
当前任务阶段：{str(task_memory.get('phase') or 'seeking_goal')}
阶段要求：{phase_guidance}

本任务没有固定动作步数上限。不要因为步数较多就结束；根据是否取得新页面、新边、新控件、
新 Region 覆盖或更接近目标来判断进展。确认进入重复且无进展的循环时使用 DEFER。

已知页面图：

{str((context.get('page_graph') or {}).get('text') or '')}

页面图只包含页面、少量 Region 特征、折叠后的已验证页面关系和当前路线；不包含完整按钮清单、历史截图或原始 ActionEdge。pN 只在本轮有效。先根据当前截图判断当前页面是已有 pN、new 还是 uncertain，不要根据名称相似强行合并。

本任务近期动作及框架验证结果：

{json.dumps(task_memory, ensure_ascii=False)}

框架提供的客观进展与重复事实：

{json.dumps(dict(context.get("progress_facts") or {}), ensure_ascii=False)}

当前页面已知 Region：

{json.dumps(list((context.get("current_regions") or {}).get("regions") or []), ensure_ascii=False)}

你可以按需调用的轻量工具：

{json.dumps(list(context.get("tool_catalog") or []), ensure_ascii=False)}

{feedback_section}
根据当前截图、页面图、路线提示和任务历史，直接选择下一步原子动作。框架没有预先给你候选坐标，也不强制你本轮点击目标。你可以沿 ROUTE 前往目标来源页、关闭遮挡、使用返回入口、滚动寻找目标，或点击目标本身。
当当前 Region 信息已经足够时直接行动，不要为了确认而重复调用工具。只有缺少页面记忆、verified
路线或某个 Region 尚未观察时才调用相应工具；工具结果会进入下一轮任务记忆。

动作：
- CLICK：point_1000 是相对整张图 1 的 [x,y]，两个值必须在 0..1000 且位于可见目标内部。
- SCROLL：direction 必须是 up/down/left/right；point_1000 可为滚动区域内一点或 null。
- BACK：只有没有更合适的可见返回控件时使用；存在可见 Back/Close 时应 CLICK 它。
- WAIT：界面仍可能加载或变化时使用。
- FINISH：目标已经由任务历史中的真实动作和验证结果完成；只结束当前按钮任务。
- DEFER：身份、定位或安全性无法可靠判断。
- CALL_TOOL：调用 tool_catalog 中的一个工具。tool_name 和 arguments 按工具说明填写；这不是 GUI 动作。

action_role：
- goal：本动作直接操作当前任务目标。
- route：沿已知路线前往目标来源页。
- recovery：处理遮挡、返回或脱离死胡同。
- other：其他必要且安全的任务内动作。

不要递归探索与当前任务无关的新功能；可把当前截图中新发现的 Back、Close、Tab、菜单或功能入口放入 discovered_controls，交给框架稍后调度。连续重复相同动作且没有可见变化时应换方向或 DEFER。
每轮都在 loop_assessment 中判断当前任务是否正在循环。confirmed 表示重复轨迹没有带来任何新事实；
此时目标未完成就 DEFER，目标已经有验证事实才 FINISH。框架只提供重复事实，不替你做语义判断。

不要执行发送、删除、购买、授权、隐私泄露或其他不可逆操作。只有 safety=safe 的 CLICK、SCROLL、BACK 或 WAIT 才会被框架执行。

只输出一个 JSON 对象：

{{
  "current_page": {{"kind":"known|new|uncertain","page_ref":"p0 或 null","proposed_name":"","reason":"截图依据"}},
  "discovered_controls": [{{"target":"Back","area":"top bar","relation":"return|close|navigation|function|other","reason":"发现依据"}}],
  "loop_assessment": {{"status":"not_looping|suspected|confirmed","reason":"判断依据"}},
  "action": {{
    "type":"CLICK|SCROLL|BACK|WAIT|FINISH|DEFER|CALL_TOOL",
    "target":"当前动作目标",
    "point_1000":[500,500],
    "direction":null,
    "safety":"safe|unsafe|uncertain",
    "action_role":"goal|route|recovery|other",
    "reason":"选择依据",
    "expected_result":"预期可见结果或需要工具返回的信息",
    "tool_name":"CALL_TOOL 时填写工具名，否则为空字符串",
    "arguments":{{}}
  }}
}}

非 CLICK 动作可按规则把 point_1000 设为 null；非 SCROLL 动作的 direction 必须为 null。CALL_TOOL 的 point_1000 和 direction 都必须为 null。不要输出 JSON 之外的文字。
""".strip()


__all__ = [
    "build_element_exploration_prompt",
    "build_explorer_prompt",
    "build_route_choice_prompt",
]
