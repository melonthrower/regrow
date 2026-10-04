# 功能知识与完成

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

整理区块功能，区分清点、任务和图的完成状态。

## 输入、输出与边界

Region、任务及有效执行证据 → 可复用功能、条件和覆盖说明。无待办、record_only或同类覆盖不等于所有功能已实测。

主要接口：`region_functions.request；function_evidence；coverage_exemption；region_graph`。详细现行合同见[原模块文档](../stepwise_discovery_completion.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [region_functions.py](../../../experiments/clock_manual_20260919/region_functions.py)
- [function_evidence.py](../../../experiments/clock_manual_20260919/function_evidence.py)
- [coverage_exemption.py](../../../experiments/clock_manual_20260919/coverage_exemption.py)
- [region_graph.py](../../../experiments/clock_manual_20260919/region_graph.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/区块功能登记.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/区块功能登记.prompt)
- [功能识别](../../../experiments/clock_manual_20260919/遍历prompt/功能识别)
- [输出格式/区块功能登记.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/区块功能登记.schema)
- [更新/重复入口覆盖复核.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/重复入口覆盖复核.prompt)

## 验证与未完成事项

功能整理和共享依据有保存帧验证；完整遍历、跨应用鲁棒性与研究目标未据此全部通过。指令合成/轨迹采集独立消费冻结图。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#knowledge)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。
