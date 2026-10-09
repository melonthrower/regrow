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
traversal_scheduler选择任务有效目标；action_proposer向动作步提供completion_target（默认原控件/动作，必要时取更新修正的后续绑定）；跨区块修正后的补定位读取completion_region。导航动作仍记录其实际来源，不消费不同对象的原任务。
同区块改名重复由任务模块复用，不绕过blocked。普通续接不调累计结果判断；前置准备不被旧点击结束，当前条件观察仍可解锁主任务。跨区块同业务目标去重未实现。

## 记录缺口与动作许可
已有可信pending/续接任务不等待inventory_complete；局部缺口不撤销可信当前观察。滚动任务允许必要点击、返回、输入等准备动作，准备动作不结束滚动。历史任务补清点仍由空闲知识阶段承接；区块探索结束后的原子操作总结已接入普通调度；已执行记录的程序reconcile仍在current执行。


## 范围排除与离开前景
当前区块被排除只禁止在其中派探索义务。traversal_scheduler.select_work依据范围内剩余工作选择导航目标，无需先有deferred标记；不会派范围外目标的业务动作。随后由动作提出器、当前截图、绑定与投递流程决定怎样离开，不固定返回动作。

## 三步组件的程序调度（2026-10-06）
traversal_scheduler.select_work从已提交records/state选择工作，返回kind、region、
working_region、可选task和reason，不构造prompt。已提交区块的原子操作总结可先以0GUI登记，当前可承接的在途任务随后继续；
排除当前区块不阻止离开，排除目标不派业务动作。多区块时按任务有效目标选择，
不把列表第一项当工作归属。完整区块仍优先回有未完成工作的已观察入口父区块，
然后复用既有frontier；历史一次back无效不永久封禁回程。
无可推进工作返回idle，由请求入口投影为scope_idle，保留缺口，不声明全应用完成。
task_selection.attach仅兼容调用同一select_work/render_work，原render仍渲染进度。
Scheduler.current负责登记后的程序reconcile和选择；请求构造不再反向决定换工作。
pending_work优先续已执行结果；after_round集中会话继续、一次空闲整理和停止解释。

局部检查/导航安排（schedule_local_inspection、offer_foreground_navigation）及已结束目标退出（retire_completed_goal）归traversal_scheduler。discovery_step登记当前观察后调用这些决策；Locator不通过局部完成终止会话。

已有实际回执及观察、关联仍unconfirmed且候选明确包含原任务目标的尝试，由正常reconcile转为ownership review缺口，清理active_task后调度其他工作；不赋予确认控件、完成状态或重新投递许可。不同候选、已排除旧尝试、准备任务和异常仍保留原边界。此改动针对Clock已开编辑页但父任务反复none→发现的实机循环，验收见本批日志。

未确认动作关联的ownership缺口当前没有完整自动补录入口；这只解开其他工作的调度，原任务仍未完成。早期reconcile在待更新/导航续接之后、循环检查之前同步记录，避免沿旧pending状态触发无意义循环纠错。

## 任务暂挂不封整个控件（2026-10-09）
`task_prerequisites.enroll`与`stepwise_flow.shortest_known_path`不再按任意同控件blocked排除准备/路线。`operation_blocking`只复用未解除退出记录的实际操作范围；`action_proposer.request_from_run`披露相关失败，`repair_stages.accept_candidate`在原动作接受阶段拦截明确同用途重试。缺少实际条件不当作无条件禁令；不明适用性交给正常动作上下文判断。原任务不因准备开始而完成，同控件准备可登记；范围、permitted、既有去重和原始证据保留。详见[设计](../../SCOPED_TASK_BLOCKING.md)；保存帧有限验证不等于实机导航或全应用完成。
