# 任务规划与登记

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

判断值得探索的新问题，维护任务归属、补充和清点状态。

## 输入、输出与边界

当前区块、截图、控件及已有任务 → inventory/evidence/operations。现行新增/补充按本区块任务名匹配；complete表示任务清点，不表示任务已执行。

主要接口：`region_tasks.plan_request / apply_plan / commit_plan；entry_evidence.disclose`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [region_tasks.py](../../../experiments/clock_manual_20260919/region_tasks.py)
- [entry_evidence.py](../../../experiments/clock_manual_20260919/entry_evidence.py)
- [traversal_scope.py](../../../experiments/clock_manual_20260919/traversal_scope.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/区块探索任务.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/区块探索任务.prompt)
- [任务/任务登记与补全.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务登记与补全.prompt)
- [任务/历史入口与共享复用.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/历史入口与共享复用.prompt)
- [任务/任务粒度与反馈.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务粒度与反馈.prompt)
- [输出格式/区块探索任务.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/区块探索任务.schema)

## 验证与未完成事项

2026-10-04单例保存帧诊断：Luna看出Add未显示，但complete未纠正地图，并新增跨区块重复目标。此为人工触发复核、1HTTP/0GUI；不是自动纠错成功。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#tasks)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 2026-10-05 讨论中的修改方向（尚未实现）

- 新增任务面向当前图中可辨认的本区块控件；旧任务在控件暂时不可见时保留。
- 给出已有任务的目标、状态、前置条件，以及相关已知目的区块的任务。
- 同控件同动作默认复用；独立的新问题须说明原任务为何不覆盖，参数取值变化通常留在原任务内。
- 入口已知时，其目的区块内部调查归目的区块；不得改名或换owner绕过旧任务的暂挂。
- 仅返回增量；当前控件记录冲突与“任务是否列齐”分开表达。

验收用例：旧任务改名重复、跨区块同目标、暂停条件保留、合法新问题、历史控件暂不可见。当前只完成诊断，未接通这些防重与地图修正措施。
