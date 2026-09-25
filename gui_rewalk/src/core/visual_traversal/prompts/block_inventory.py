"""Prompts for the opt-in page-map -> Region-crop inventory experiment."""

from __future__ import annotations

import json
from typing import Any, Dict

PAGE_MAP_PROMPT = r"""
你是一名 GUI Agent 的视觉交互分析专家。

你的任务不是分析整个屏幕的视觉布局，而是识别当前 GUI 中用户真正可以探索和操作的交互空间。

你需要从截图中确定：

1. 当前唯一的 active interaction surface
2. 该 surface 内部的功能区域 regions

不要输出屏幕中所有可见区域。
只输出当前交互上下文中具有功能意义的区域。

---

# Step 1: Determine active interaction surface

active interaction surface 指：

当前决定用户下一步可执行动作的交互上下文。

判断依据：

不是视觉层级。
不是面积大小。
不是颜色突出程度。
不是是否覆盖在其他内容之上。

判断标准：

如果某个区域出现后：

- 改变了用户当前可以执行的操作集合；
- 成为了用户下一步操作的主要目标；
- 用户需要先与该区域交互才能继续当前任务；

则该区域形成新的 active interaction surface。

如果不存在这种变化，则当前主要应用页面保持为 active interaction surface。

---

# Step 2: Distinguish active surface from passive visual information

视觉上位于前景的内容不一定属于 active interaction surface。

如果某个区域：

- 只是解释当前页面已有功能；
- 只是展示状态变化；
- 只是提供辅助说明；
- 用户忽略它后仍然可以继续完成当前页面操作；
- 不产生新的操作路径；

则它属于 passive visual information。

passive visual information:

- 不创建新的 active interaction surface；
- 不作为 region 输出。

不要因为某个区域：
- 有明显背景；
- 有边框；
- 有文字；
- 位于前景；
- 视觉面积较大；

就认为它是新的交互界面。

---

# Step 3: Active surface selection rule

当前截图只能存在一个 active interaction surface。

如果发现某个区域形成新的 active interaction surface：

则：

- 只分析该 surface；
- 其他内容视为 inactive background；
- inactive background 不允许出现在 regions 中。

背景页面即使仍然可见，也不属于当前 region。

---

# Step 4: Region extraction

在 active interaction surface 内划分 regions。

Region 表示：

一个具有稳定功能意义的交互区域。

Region 是功能容器，不是单个操作目标。

正确粒度：

应该将：
- 服务于同一个功能目标的多个交互元素；
- 属于同一个视觉和语义区域的内容；

组合为一个 region。

不要将以下情况拆分为独立 region：

- 单个按钮；
- 单个文本；
- 单个菜单选项；
- 单个输入框；
- 单个可点击对象。

如果多个操作目标共同组成一个功能区域，
应合并为一个 region。

应用自身提供的导航栏、工具栏或操作栏，只要包含可探索的应用功能入口，也属于 active interaction surface，应按其中的应用功能划入 region。

不要把桌面面板、Dock、系统状态栏，以及最小化、最大化、关闭等通用窗口管理控件划为 region。若应用功能入口与通用窗口管理控件位于同一栏，只描述和保留应用自身的功能入口。

---

# Step 5: Region validation

输出前检查每个 region：

## Check 1
该 region 是否属于 active interaction surface？

如果不是：
删除。

## Check 2
如果 active interaction surface 消失，
该 region 是否仍然存在？

如果仍然存在：
说明它属于背景，不输出。

## Check 3
该 region 是否只是描述、解释或提示另一个功能？

如果是：
删除。

## Check 4
该 region 是否只是一个单独 action target？

如果是：
尝试与附近相关内容合并。

---

# Step 6: Output

按照视觉阅读顺序编号：

r0, r1, r2 ...

只输出 JSON。

不要输出解释过程。

格式：

{
  "interface_name": "...",
  "regions": [
    {
      "region_id": "r0",
      "name": "...",
      "description": "..."
    }
  ]
}
""".strip()


def build_region_localization_prompt(context: Dict[str, Any]) -> str:
    """Build the complete-frame prompt that locates one selected Region."""
    safe_context = {
        "interface_name": str(context.get("interface_name") or ""),
        "region_id": str(context.get("region_id") or ""),
        "name": str(context.get("name") or ""),
        "description": str(context.get("description") or ""),
    }
    return f"""
You are the visual-grounding specialist of a screenshot-only GUI agent, acting
as its GUI Region locator. Locate exactly one previously registered semantic
Region in the attached complete screenshot. Do not inspect or describe its
controls.

Selected Region:
{json.dumps(safe_context, ensure_ascii=False, sort_keys=True)}

Return found=false when the Region is absent or cannot be identified uniquely.
When found, return its complete visible bbox_1000=[x0,y0,x1,y1] using integer
coordinates from 0 through 1000. The box must cover the Region container, not an
individual control. Fit the box to the selected container's visible outer
boundary. A separator, background change, spacing break, or alignment break ends
the Region; do not extend across that boundary into an adjacent container even
when the two containers have related functions. Also decide whether content
inside this exact Region can scroll independently.

Do not enumerate, name, classify, or locate elements. Do not return neighboring
containers, hidden content, or operating-system UI.

Return JSON only:
{{"region_id":"{safe_context['region_id']}","found":true,"bbox_1000":[0,0,1000,1000],"scrollable":false,"reason":"short visual evidence"}}
""".strip()


def build_region_inventory_prompt(context: Dict[str, Any], *,
                                  image_mode: str = "crop") -> str:
    """Build the confirmed function-entry prompt for one located Region."""
    safe_context = {
        "interface_name": str(context.get("interface_name") or ""),
        "region_id": str(context.get("region_id") or ""),
        "name": str(context.get("name") or ""),
        "description": str(context.get("description") or ""),
        "bbox_1000": context.get("bbox_1000"),
        "scrollable": context.get("scrollable"),
    }
    if image_mode == "full":
        scope = (
            "附图是完整截图。只观察所选 Region bbox 内的可见内容。"
        )
    elif image_mode == "long_region":
        scope = (
            "附图按顺序展示同一个目标 Region 的连续滚动视图，相邻图片可能重叠。"
            "把这些图片共同视为该 Region 在本次输入范围内的连续可见内容；"
            "同一个物理入口只输出一次。"
        )
    elif image_mode == "context_crop":
        scope = (
            "图 1 是完整界面上下文，图 2 是所选 Region 的完整裁图。"
            "只从图 2 判断功能入口，图 1 仅帮助理解其界面语境。"
        )
    else:
        scope = (
            "附图只包含一个所选 Region，并且是功能入口的唯一视觉来源。"
        )
    return f"""
你是一名 GUI 界面观察助手。

{scope}

目标 Region 元数据：
{json.dumps(safe_context, ensure_ascii=False, sort_keys=True)}

请判断目标 Region 中是否存在当前可见且可使用的功能入口。

如果目标 Region 已经是某项功能的具体操作界面，其中的字段、选项和操作控件共同用于完成当前功能，则返回空数组，不输出这些内部控件。

只显示空状态、结果、列表或对象摘要的 Region 不属于上述具体操作界面；其中的功能入口仍需输出。

其他情况下，只输出符合以下任一条件的入口：

- 进入或切换到另一项独立功能内容；
- 展开一组此前隐藏、可继续操作的功能内容；
- 解除一组功能当前受到的限制。

只在当前 Region 内执行当前功能、改变数值或切换状态的控件不是功能入口。

明显灰显、禁用或是否可用无法确认的入口不输出。

只根据截图中可见的信息判断。如果没有符合条件的入口，返回空数组。

target 只标识截图中要操作的可见入口：有文字标签时使用该标签；没有文字标签时描述其图形特征和所在对象。

只输出 JSON，不要输出解释：

{{
  "region_id": "{safe_context['region_id']}",
  "function_entries": [
    {{
      "entry_id": "e0",
      "target": ""
    }}
  ]
}}
""".strip()


__all__ = [
    "PAGE_MAP_PROMPT",
    "build_region_localization_prompt",
    "build_region_inventory_prompt",
]
