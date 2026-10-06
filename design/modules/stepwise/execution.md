# 动作选择与执行

2026-10-06最小遍历修复使用下述直接滚动合同。旧冻结运行仍用各自源码；2026-10-05虚报Nairobi的候选图保留，不作为准确图续跑。各项验证范围见本月日志。

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

选择动作、关联控件、检查投递条件并保留实际回执。

## 输入、输出与边界

当前目标、单张执行依据图及候选 → 动作提案、绑定与真实回执。坐标不证明存在或执行成功；参数输入的实际投递独立于文字提案。

主要接口：`run_task_step；stepwise_flow.assemble_current_context；action_binding.bind_action_target；action_commands`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

正常入口由 `run_task_step._run_step` 连接组件：Scheduler 选择工作，ActionProposer 构造请求并经 `Runner.perform('action')` 校验绑定，ActionExecutor 经 `StepwiseFlow.execute` 投递。未被维护路径调用的 `choose_from_run` 已移除；保存图离线适配器 `choose_from_graph` 及其维护测试保留，冻结基线回放仍使用独立冻结源码。

## 区块滚动
滚动由本模块的 `region_scroll.bind` 处理，普通探索与导航共用：Luna 根据当前单张截图选择滑动位置；框架保留任务许可、坐标格式和图内范围检查，不要求预先保存 Region 边界或控件模板。Android 起止点在截图内；桌面起点在截图内，终点表示滚轮方向和幅度。区块位置由模型按当前图判断，绑定通过不证明滚动命中或业务成功。

`run_task_step`、`stepwise_flow`、`repair_stages` 不再因缺少边界缓存插入补定位；`inventory_scroll` 在正常观察确认原前景后可恢复原滚动任务，保留 partial 清点与身份缺口。实际滚动后仍走[结果更新与登记](updates.md)，不改模型输出字段或新增调用角色。

## 源码与提示入口

- [action_binding.py](../../../experiments/clock_manual_20260919/action_binding.py)

- [stepwise_flow.py](../../../experiments/clock_manual_20260919/stepwise_flow.py)
- [run_task_step.py](../../../experiments/clock_manual_20260919/run_task_step.py)
- [action_commands.py](../../../experiments/clock_manual_20260919/action_commands.py)
- [action_evidence.py](../../../experiments/clock_manual_20260919/action_evidence.py)
- [input_target.py](../../../experiments/clock_manual_20260919/input_target.py)
- [attempt_guard.py](../../../experiments/clock_manual_20260919/attempt_guard.py)
- [region_scroll.py](../../../experiments/clock_manual_20260919/region_scroll.py)
- [visual_choices.py](../../../experiments/clock_manual_20260919/visual_choices.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [流程/02_动作选择.json](../../../experiments/clock_manual_20260919/遍历prompt/流程/02_动作选择.json)
- [动作](../../../experiments/clock_manual_20260919/遍历prompt/动作)
- [输出格式/选择探索入口.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/选择探索入口.schema)

## 验证与未完成事项

普通桌面动作及其纠错以当前单图为坐标依据；重复外观、未绑定身份和文字输入仍有未解决案例。运行旧冻结源不会自动使用checkout新改动。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#execution)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 动作组件（2026-10-06）
ActionProposer的request_from_run读取完整原记录，render_work只渲染调度器选定任务
或导航，propose沿原Runner校验、纠错、绑定；stepwise_flow.assemble_current_context
保留为同一实现的公开入口。地图、历史、单图和视觉候选规则复用原模块。
ActionExecutor.execute集中原投递前取图/窗口核对、原纠错交接、完整GUI额度检查、
pending落盘、StepwiseFlow/action_commands执行、原回执、等待、后图与窗口证据。
它拒绝已有未登记投递及不足结果调用额度；只返回attempt目录，不登记观察成功。
预算不足或截图变化时保留原提案及证据；不重投已执行动作。
