# 调度与前置条件

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

选择已有工作、处理前置条件、暂挂与已知导航。

## 输入、输出与边界

任务状态、当前前景、已观察跳转关系 → 下一个工作目标或导航/准备义务。进入目的区块不自动完成原目标；旧暂挂不得因重新命名而解除。

主要接口：`task_routing.advance；task_prerequisites；task_selection.attach；region_tasks.coverage`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [task_selection.py](../../../experiments/clock_manual_20260919/task_selection.py)

- [task_routing.py](../../../experiments/clock_manual_20260919/task_routing.py)
- [task_prerequisites.py](../../../experiments/clock_manual_20260919/task_prerequisites.py)
- [task_deferral.py](../../../experiments/clock_manual_20260919/task_deferral.py)
- [inventory_scroll.py](../../../experiments/clock_manual_20260919/inventory_scroll.py)
- [historical_inventory.py](../../../experiments/clock_manual_20260919/historical_inventory.py)
- [visual_backtrack.py](../../../experiments/clock_manual_20260919/visual_backtrack.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/前置条件与恢复.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/前置条件与恢复.prompt)
- [动作/探索导航路线.prompt](../../../experiments/clock_manual_20260919/遍历prompt/动作/探索导航路线.prompt)
- [更新/暂挂任务复核.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/暂挂任务复核.prompt)

## 验证与未完成事项

任务选择与前置条件已有实现，父目标接续及暂挂规则有有限案例。重复新任务可能绕过原前置条件，是规划与调度的接口缺口。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#routing)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。
