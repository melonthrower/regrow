# 结果更新与登记

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

更新图、任务结果与观察来源，发布完整快照。

## 输入、输出与边界

真实回执、动作前后图和原任务 → 新观察、动作结果、任务结算与快照指针。提交成功不等于视觉语义正确；原始证据和旧快照保留。

主要接口：`update_step.build_update_request；register_update.commit_update；task_settlement.settle_task；task_result_review`。详细现行合同见[原模块文档](../stepwise_region_identity.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [task_settlement.py](../../../experiments/clock_manual_20260919/task_settlement.py)
- [region_evidence.py](../../../experiments/clock_manual_20260919/region_evidence.py)

- [update_step.py](../../../experiments/clock_manual_20260919/update_step.py)
- [register_update.py](../../../experiments/clock_manual_20260919/register_update.py)
- [update_visibility.py](../../../experiments/clock_manual_20260919/update_visibility.py)
- [registration_diagnostics.py](../../../experiments/clock_manual_20260919/registration_diagnostics.py)
- [task_result_review.py](../../../experiments/clock_manual_20260919/task_result_review.py)
- [parameter_evidence_review.py](../../../experiments/clock_manual_20260919/parameter_evidence_review.py)
- [related_task_results.py](../../../experiments/clock_manual_20260919/related_task_results.py)
- [update_semantic_review.py](../../../experiments/clock_manual_20260919/update_semantic_review.py)
- [knowledge_transaction.py](../../../experiments/clock_manual_20260919/knowledge_transaction.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [流程/03_结果核对.json](../../../experiments/clock_manual_20260919/遍历prompt/流程/03_结果核对.json)
- [更新/动作后观察与状态更新.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/动作后观察与状态更新.prompt)
- [更新/区块变化与字段.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt)
- [任务/任务结果核对.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务结果核对.prompt)
- [输出格式/动作后更新.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/动作后更新.schema)

## 验证与未完成事项

更新步允许必要前后/历史图，不把动作步单图约束套到更新。Stopwatch虚报Add及Timer单位推测写实尚未通过验收，不能因Runner完成宣布修好。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#updates)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。
