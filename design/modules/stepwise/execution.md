# 动作选择与执行

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

选择动作、关联控件、检查投递条件并保留实际回执。

## 输入、输出与边界

当前目标、单张执行依据图及候选 → 动作提案、绑定与真实回执。坐标不证明存在或执行成功；参数输入的实际投递独立于文字提案。

主要接口：`run_task_step；stepwise_flow.assemble_current_context；action_binding.bind_action_target；action_commands`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

正常入口由 `run_task_step._run_step` 组装请求，经 `Runner.perform('action')` 选择与校验绑定，再由 `StepwiseFlow.execute` 投递。未被维护路径调用的 `choose_from_run` 已移除；保存图离线适配器 `choose_from_graph` 及其维护测试保留，冻结基线回放仍使用独立冻结源码。

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
