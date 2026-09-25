"""Compact visual comparison prompts."""

from __future__ import annotations

import json

from .interface_scope import (
    CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
    REGION_PRESENTATION_DEFINITION_ZH,
)


def build_pair_page_identity_prompt() -> str:
    """Compare one registered page with one current full screenshot."""
    return "\n".join([
        "你是一名擅长识别 GUI 界面层级的专家。",
        "",
        "分别按以下定义确定两张截图中的当前操作界面：",
        CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
        "",
        "图1是已登记截图，图2是当前截图。",
        "",
        "在判断页面身份前，先检查图2是否出现不属于目标应用的临时前景内容。",
        "如果出现，is_interruption=true，same_page=null，暂不判断页面身份。",
        "只有 is_interruption=false 时，才继续比较页面。",
        "",
        "分别确定两张截图中的当前操作界面，只比较这两个当前操作界面本身。",
        "只有两者是同一个当前操作界面时，same_page=true；如果两者不同，same_page=false。",
        "当前操作界面之外共同可见的内容只作为上下文，不能单独作为 same_page 的依据。",
        "同一页面处于不同滚动位置时仍属于同一个页面，不要因为当前可见内容不同而判为不同页面。",
        "",
        "只输出包含以下字段的 JSON：",
        "is_interruption：图2存在应用外临时前景内容时为 true，否则为 false。",
        "same_page：is_interruption=false 时为 true 或 false；否则为 null。",
        "reason：简短的视觉依据。",
    ])


def build_page_candidate_selection_prompt(
    candidates, *, has_source_screenshot: bool = False,
    opening_action=None,
) -> str:
    """Shortlist registered Pages and prepare one distinct fallback name."""
    source_context = (
        "图2是产生当前截图的来源页面，只用于理解到达路径和命名，不是待匹配的候选页面。"
        if has_source_screenshot else
        "本次没有提供来源页面截图。"
    )
    return "\n".join([
        "你是一名擅长识别和命名 GUI 页面层级的专家。",
        "",
        "图1是当前完整截图。",
        source_context,
        "",
        "先按以下定义确定图1中的当前操作界面：",
        CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
        f"从来源页面执行的入口："
        f"{json.dumps(dict(opening_action or {}), ensure_ascii=False)}",
        "",
        "下面列出已登记页面的名称和区块描述。请从中选出最值得与当前截图进一步比较的页面，按可能性排序，优先只选一个；只有确有必要时才选两个。",
        "这里只筛选值得进一步比较的页面，不判断当前截图最终是否与候选属于同一页面。",
        "即使当前截图看起来属于新页面，也必须选择至少一个最值得排除的已登记页面；candidate_page_ids 不得为空。选择候选不表示你认为它与当前截图属于同一页面。",
        "",
        "同时给出一个备用页面名称：仅在所选候选之后均被证明不匹配时，用它命名当前页面。备用名称只命名上述当前操作界面并概括其主要功能；它应当与已登记页面名称有清楚差异，不要依赖时间、具体数据或截图编号。",
        "不属于当前操作界面的任何可见内容不得出现在备用名称中。",
        "",
        f"已登记页面：{json.dumps(list(candidates or []), ensure_ascii=False)}",
        "",
        "只输出 JSON。candidate_page_ids 必须使用上面提供的候选标签，至少一个、最多两个，不得为空：",
        '{"candidate_page_ids":["C1"],"proposed_new_page_name":"...","reason":"简短的视觉依据"}',
    ])


def build_region_correspondence_prompt(
    interface_a: str, regions_a, interface_b: str, regions_b,
) -> str:
    """Compare the already recorded region tables of two interfaces."""
    return "\n".join([
        "你是一名擅长比较 GUI 区块目录的专家。",
        CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
        REGION_PRESENTATION_DEFINITION_ZH,
        "比较两个当前操作界面包含的区块，并判断哪些区块是同一个区块。",
        "只有区块整体的可见内容范围、呈现关系和完整目标集合相互对应时，才属于同一个区块；局部文字或目标重合不足以建立对应。",
        "即使区块只包含一个目标，只要整体完整对应，也可以判为同一个区块。",
        f"界面 A：{json.dumps(str(interface_a or ''), ensure_ascii=False)}",
        f"界面 A 区块：{json.dumps(list(regions_a or []), ensure_ascii=False)}",
        f"界面 B：{json.dumps(str(interface_b or ''), ensure_ascii=False)}",
        f"界面 B 区块：{json.dumps(list(regions_b or []), ensure_ascii=False)}",
        "为每对相同区块分配一个仅在本次请求中使用的标签，例如 S1；未对应区块保留输入标签。",
        "返回相同区块的对应关系，以及两个界面的最终区块列表。每个输入区块必须在所属界面的最终列表中恰好出现一次。",
        '只输出 JSON：{"same_regions":[{"same_region":"S1","interface_a_region":"A1","interface_b_region":"B2"}],"interface_a_final_regions":["A2","S1"],"interface_b_final_regions":["B1","S1"]}',
    ])


def build_region_partition_mapping_prompt(
    interface_a: str, regions_a, interface_b: str, regions_b, *,
    has_screenshots: bool = False, triggering_action: str = "",
) -> str:
    """Map a stable Region partition to one fresh PageMap partition."""
    image_note = (
        ""
        if has_screenshots else
        "\n本次没有截图输入，只在目录文字足以确认同一内容身份时建立对应。\n"
    )
    return f"""
你是一名擅长分析 GUI 界面内容组织变化的视觉分析专家。

图 1 是执行动作前的完整截图。
图 2 是执行动作后的完整截图。
{image_note}
你的任务是结合两张截图、实际执行的动作以及两张截图各自的候选 Region 目录，判断操作前后 Region 集合之间的对应关系。

对应关系只表示同一内容容器或同一对象身份在两次观察中持续存在。

位置相近、覆盖原位置、功能相似或由同一动作触发，都不能单独证明两个 Region 是同一个 Region。

实际执行的动作帮助理解界面为何发生变化。由同一个动作引起的多个视觉变化仍然分别按照各自的内容身份判断对应关系。

一次对应可以包含：

- 一对一；
- 一对多；
- 多对一；
- 多对多。

如果多个操作前 Region 与多个操作后 Region 共同表达同一组完整内容，则把它们放入同一个 match。

操作后出现、并且不属于任何操作前 Region 延续的内容，属于新增 Region。

现有截图和目录不足以确认来源的操作后 Region，属于 unresolved Region。

## 输入

实际执行的动作：

{json.dumps(str(triggering_action or ""), ensure_ascii=False)}

操作前界面：

{json.dumps({"interface_name": str(interface_a or ""), "regions": list(regions_a or [])}, ensure_ascii=False)}

操作后界面：

{json.dumps({"interface_name": str(interface_b or ""), "regions": list(regions_b or [])}, ensure_ascii=False)}

## 输出要求

输出中的 Region 只使用输入目录提供的临时 ID，不重复输出 Region 的名称和描述。

matches 表示已经确认的对应关系：

- known_region_ids：对应的操作前 Region ID 数组；
- current_region_ids：对应的操作后 Region ID 数组；
- reason：建立该对应关系的简短视觉依据。

new_current_region_ids 只包含操作后真正新增的 Region ID。

unresolved_current_region_ids 只包含当前证据不足以确认来源的操作后 Region ID。

每个操作前 Region ID 最多出现在一个 match 中。

每个操作后 Region ID 必须且只能出现在以下一个位置：

- 一个 match 的 current_region_ids；
- new_current_region_ids；
- unresolved_current_region_ids。

只输出 JSON，不输出分析过程或其他文字。

输出格式：

{{
  "matches": [
    {{
      "known_region_ids": ["A1"],
      "current_region_ids": ["B1", "B2"],
      "reason": "简短的视觉依据"
    }}
  ],
  "new_current_region_ids": ["B3"],
  "unresolved_current_region_ids": ["B4"]
}}
""".strip()


__all__ = [
    "build_region_correspondence_prompt",
    "build_region_partition_mapping_prompt",
    "build_page_candidate_selection_prompt",
    "build_pair_page_identity_prompt",
]
