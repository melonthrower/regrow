"""Shared semantic definitions used by visual-traversal prompts."""

CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH = (
    "当前操作界面是截图中最前方、实际接收用户下一步操作的界面。"
    "先观察当前截图是否已经呈现一个拥有独立容器边界和功能入口、"
    "并覆盖其他内容的交互层。若已呈现，当前操作界面就是这个交互层，"
    "无论它占据多大面积、是否模态或是否位于应用窗口内部；"
    "其他可见内容只作为理解上下文。"
    "其他可见内容不能仅因为由此前动作产生、位于最前方或文字与某项功能相关，"
    "就改变当前操作界面的身份；不属于当前操作界面的内容不参与页面匹配或命名。"
    "若未呈现这样的交互层，当前操作界面就是承载当前可见内容和功能入口的完整应用页面。"
    "尚未展开的入口只按截图中当前可见的控件理解。"
)

REGION_PRESENTATION_DEFINITION_ZH = (
    "一个区块表示当前操作界面中一组预计在同一界面状态下共同呈现的内容，"
    "其中可以包含不同功能。预计共同出现、共同消失的内容归入同一区块；"
    "能够独立出现、消失或被替换的部分分别识别为不同区块。"
)


__all__ = [
    "CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH",
    "REGION_PRESENTATION_DEFINITION_ZH",
]
