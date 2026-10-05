# 观察与身份

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

当前图中的区块、控件与历史身份如何对应；前景、模板与控件组匹配。

共享定位由 `image_match.py` 唯一实现原尺寸像素匹配；`control_layout.py` 负责重复外观控件的组内关联，`visual_backtrack.same_surface` 负责整页稳定性。门槛、输入漏识别边界和候选含义见[身份合同](../stepwise_region_identity.md#2026-10-03-重复外观控件的位置关联)，不向地图或Luna增加算法说明。

## 输入、输出与边界

当前截图、历史Region/控件与匹配线索 → 已登记身份、前景范围和观察证据。模板匹配不是当前语义确认，裁图可用也不保证识别正确。

主要接口：`discovery_step.request_from_run / run_stage；region_identity；identity_templates`。详细现行合同见[原模块文档](../stepwise_region_identity.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [discovery_step.py](../../../experiments/clock_manual_20260919/discovery_step.py)
- [discovery_completion.py](../../../experiments/clock_manual_20260919/discovery_completion.py)
- [discovery_inventory.py](../../../experiments/clock_manual_20260919/discovery_inventory.py)
- [foreground_scope.py](../../../experiments/clock_manual_20260919/foreground_scope.py)
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
