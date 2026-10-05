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

任务选择与前置条件已有实现，父目标接续及暂挂规则有有限案例。同区块同绑定的改名重复已拦住；跨区块语义重复仍未处理。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#routing)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 当前绑定与历史续接
task_selection向动作步提供completion_target（默认原控件/动作，必要时取更新修正的后续绑定）；跨区块修正后的补定位读取completion_region。导航动作仍记录其实际来源，不消费不同对象的原任务。
同区块改名重复由任务模块复用，不绕过blocked。普通续接不调累计结果判断；前置准备不被旧点击结束，当前条件观察仍可解锁主任务。跨区块同业务目标去重未实现。

## 记录缺口与动作许可
已有可信pending/续接任务不等待inventory_complete；局部缺口不撤销可信当前观察。滚动任务允许必要点击、返回、输入等准备动作，准备动作不结束滚动。historical_inventory仅在GUI空闲后的知识整理阶段调度；已执行记录的程序reconcile仍在current执行。
