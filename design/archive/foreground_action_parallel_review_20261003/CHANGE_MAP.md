# 具体改动审查图（提案，未实施）

固定已导出源码提交 `19448694bdc1db14aa863b04a378c8c28a93ea65`，行号由该提交源码AST核对。后续若修改源码必须重发版本，不能沿用这些行号。本文是审查范围，不声称每行都须改动。

| 基线文件 | 函数/核实行范围 | 提议改变或核对内容 |
|---|---|---|
| [experiments/clock_manual_20260919/stepwise_flow.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/stepwise_flow.py#L244-L294) | `_assemble_local_context` 244–294 | 保留前景候选；另投影背景冲突，不能简单删候选 |
| [experiments/clock_manual_20260919/stepwise_flow.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/stepwise_flow.py#L412-L492) | `_assemble_action_context` 412–492 | 稳定工作目标/return_to与当前动作对象分开 |
| [experiments/clock_manual_20260919/stepwise_flow.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/stepwise_flow.py#L558-L565) | `bind_action_target` 558–565 | 不把preparatory_action当准入依据 |
| [experiments/clock_manual_20260919/stepwise_flow.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/stepwise_flow.py#L568-L697) | `_bind_action_target` 568–697 | 原关联结果后接统一准入，覆盖matched和unconfirmed |
| [experiments/clock_manual_20260919/foreground_scope.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/foreground_scope.py#L55-L59) | `load` 55–59 | 核对同帧来源；缺缓存不能默许或挪用旧范围 |
| [experiments/clock_manual_20260919/foreground_scope.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/foreground_scope.py#L79-L99) | `audit` 79–99 | 复用已有范围核对；当前仅发现/更新，不称动作已覆盖 |
| [experiments/clock_manual_20260919/target_observation.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/target_observation.py#L77-L105) | `refresh` 77–105 | 换帧同时刷新或失效新准入证据，不只刷新位置 |
| [experiments/clock_manual_20260919/repair_stages.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/repair_stages.py#L75-L122) | `accept_candidate` 75–122 | 正常及纠错共享拒绝/观察去向 |
| [experiments/clock_manual_20260919/repair_stages.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/repair_stages.py#L258-L293) | `refresh` 258–293 | 当前图/原目标/纠错历史一致 |
| [experiments/clock_manual_20260919/step_repair.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/step_repair.py#L147-L221) | `request` 147–221 | 保留单当前图、累计次数及失败理由 |
| [experiments/clock_manual_20260919/step_repair.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/step_repair.py#L112-L130) | `confirmed_dispatch_review` 112–130 | 确认图/调用不等于语义许可，需与新准入衔接 |
| [experiments/clock_manual_20260919/run_task_step.py](https://github.com/melonthrower/regrow/blob/19448694bdc1db14aa863b04a378c8c28a93ea65/experiments/clock_manual_20260919/run_task_step.py#L130-L354) | `_run_step` 130–354 | 投递前按新图检查，不仅写回原绑定 |

建议新文件 `experiments/clock_manual_20260919/action_scope.py`：新文件、无既有行号。只集中证据投影/动作准入职责；名称可由实施方案调整，不新增并行工作流。新增测试文件同样须标新，直接复用现有绑定、前景、单图纠错、投递前复核邻接测试。

接受案例与证据边界见同目录DESIGN.md：原错拒绝/正常纠正，四正例保持可用；缺scope不冒充语义冲突；改名变体是辅助注入，真正新前景对象/展开按钮/变图仍需完整真实证据。状态：0新行为测试、0Luna HTTP、0GUI，只完成只读调查及文档验证。
