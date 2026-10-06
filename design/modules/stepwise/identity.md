# 观察与身份

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

当前图中的区块、控件与历史身份如何对应；前景、模板与控件组匹配。

共享定位由 `image_match.py` 唯一实现原尺寸像素匹配；`control_layout.py` 负责重复外观控件的组内关联，`visual_backtrack.same_surface` 负责整页稳定性。门槛、输入漏识别边界和候选含义见[身份合同](../stepwise_region_identity.md#2026-10-03-重复外观控件的位置关联)，不向地图或Luna增加算法说明。

## 输入、输出与边界

当前截图、历史Region/控件与匹配线索 → 已登记身份、前景范围和观察证据。模板匹配不是当前语义确认，裁图可用也不保证识别正确。

主要接口：`discovery_step.request_from_run / run_stage；region_identity；identity_templates`。详细现行合同见[原模块文档](../stepwise_region_identity.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

Region 位置与模板资格分开：`region_evidence.region_observation` 保存原回复 `bbox`；`register_update.save_region_images` 仍只为 clear 且有理由的框保存模板。`foreground_scope.audit/remember` 校验普通发现/更新顶层 Region 框并关联登记身份；`visual_region_locator.plan` 只消费同帧缓存进行局部发现，换帧重新定位。受挡控件的身份框与点击范围仍独立，未确认边界保持空；不从前景大框补全。

## 源码与提示入口

- [discovery_step.py](../../../experiments/clock_manual_20260919/discovery_step.py)
- [discovery_completion.py](../../../experiments/clock_manual_20260919/discovery_completion.py)
- [discovery_inventory.py](../../../experiments/clock_manual_20260919/discovery_inventory.py)
- [foreground_scope.py](../../../experiments/clock_manual_20260919/foreground_scope.py)
- [region_evidence.py](../../../experiments/clock_manual_20260919/region_evidence.py)
- [local_partition.py](../../../experiments/clock_manual_20260919/local_partition.py)
- [region_identity.py](../../../experiments/clock_manual_20260919/region_identity.py)
- [region_records.py](../../../experiments/clock_manual_20260919/region_records.py)
- [control_records.py](../../../experiments/clock_manual_20260919/control_records.py)
- [control_layout.py](../../../experiments/clock_manual_20260919/control_layout.py)
- [identity_templates.py](../../../experiments/clock_manual_20260919/identity_templates.py)
- [image_match.py](../../../experiments/clock_manual_20260919/image_match.py)
- [history_matching.py](../../../experiments/clock_manual_20260919/history_matching.py)
- [visual_region_locator.py](../../../experiments/clock_manual_20260919/visual_region_locator.py)
- [source_region_candidates.py](../../../experiments/clock_manual_20260919/source_region_candidates.py)
- [region_candidate_names.py](../../../experiments/clock_manual_20260919/region_candidate_names.py)
- [shared_controls.py](../../../experiments/clock_manual_20260919/shared_controls.py)
- [region_behavior_split.py](../../../experiments/clock_manual_20260919/region_behavior_split.py)
- [control_history_context.py](../../../experiments/clock_manual_20260919/control_history_context.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/工作区块定位.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/工作区块定位.prompt)
- [任务/当前区块重定位.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/当前区块重定位.prompt)
- [发现手册/证据与坐标.prompt](../../../experiments/clock_manual_20260919/遍历prompt/发现手册/证据与坐标.prompt)
- [共享/身份图准入.prompt](../../../experiments/clock_manual_20260919/遍历prompt/共享/身份图准入.prompt)
- [输出格式/首屏观察.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/首屏观察.schema)

## 验证与未完成事项

当前地图候选修复仍未接受：已区分部分匹配候选与当前观察，但Luna虚报控件可能通过登记；遮挡与模板资格的案例结论见原身份模块，不推广为通用稳定。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#identity)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## partial发现
身份未确认项沿discovery_completion及原图保存，可信区块/控件继续交给任务步。区块内未确认控件同时记registration_gaps.discovery，不升级为new/same，也不虚报清点完整。新帧重新发现，原同帧缺口留history；原回复及快照不改写。

## 可选模板与真实前景分开（2026-10-06）
`foreground_scope.audit`严格检查声明前景和当前点击范围；可选Region/控件身份框异常只记template_rejections，不缓存坏边界。`identity_templates.crop_rejection`与`register_update.save_region_images`按真实来源图拒绝越界、前景外、分离或纯色身份模板，原观察/原答与点击证据保留；不以补模板为理由否定已执行动作。身份/归属冲突仍沿原纠错。`update_visibility.locate_retained`不将旧角色的匹配图标再次列到本帧已确认的不同控件位置；不合并或删除旧记录，不能因此宣称全部视觉身份可靠。

归属诊断只有合格的当前Region范围才能对真实click_bbox提出几何矛盾；现代记录的click_bbox=null不退回可选身份框。被拒绝的可选框也不能用于排除另一历史角色。历史地图正文中的旧共同地图编号会明确限定为原请求编号，不在新稀疏列表按同号寻址。

共享身份图提示明确：业务区块止于真实表面分界，不因背景颜色相同延伸入系统状态栏、导航或手势区；不能确认则uncertain。没有机械扣除重叠excluded框的新规则；图像清晰性和语义边界仍分别核对，不将本提示当作全应用几何保证。
