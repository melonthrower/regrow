# 精确修改地图

基线：`fd8cfa9dac90370a899fa869ba0af7bd06285bc6`。以下均为**修改前**行号；符号名用于辅助定位，变更后须重新出表。路径前缀 `experiments/clock_manual_20260919/`。

| 文件、原行号与函数 | 当前行为 | 拟改法 |
|---|---|---|
| [registration_diagnostics.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/registration_diagnostics.py#L13) L13–23 `collect` | 顶层anyOf错误掩盖内部字段原因 | 提取局部schema诊断辅助函数：递归读取context，依据实例类型选择适用分支；required定位缺字段；保留原诊断作为回退，不修改schema、提案或事实。 |
| [step_repair.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/step_repair.py#L185) L185–192 `Runner.stop` | 普通暂挂失败直接correction_blocked | update带attempt时调用新悬置入口；不适用继续原stop。成功返回原可继续阶段状态；记录停止原因与原/最近诊断，不将原错误覆盖成仅“次数用尽”。 |
| **新增** `update_suspension.py`，无原行号 | 尚无普通update悬置模块 | 设计接口 `suspend(run, job, reason)`：返回已提交悬置描述或None；内部核对可靠回执、对应pending和局部失败适用性，归档原证据、发布未完成状态、安排原发现/调度。发布失败不清pending；重入不重复动作。具体返回合同沿现有Runner状态，不另建并行执行流程。 |
| [branch_switch.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/branch_switch.py#L135) L135–165 `commit` 归档部分 | 保存未结算动作，但按excluded整区冻结 | 将可共用证据归档/原子发布的最小逻辑提取复用；保留原服务/循环入口语义。普通update路径不复用L74–79历史交互集合来决定整区封锁，不新增branch_correction调用。 |
| [task_deferral.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/task_deferral.py#L18) L18–31 `choose`、L110–134 `runnable/choose_unfinished` | 已有当前区块/其他区块调度 | 保留排序和普通导航能力；接收悬置后的未完成状态，只排除已知受影响任务。若现有选择已足够则不改这几处，不为“独立”另写一套调度器。 |
| [stepwise_flow.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/stepwise_flow.py#L308) L308–339 `shortest_known_path`，重点L320 | 同控件任一blocked任务即排除全部对应边 | 将一票否决收窄到与当前导航动作、对象或前景确有关的阻塞；未知具体原因保留明确缺口，不能因另一个操作目标失败删除所有可靠路线。复用悬置模块的影响判定，避免各步骤重复条件。 |
| [task_result_review.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/task_result_review.py#L13) L13–20 `reviewable`、L34–45 `next_deferred`、L105起 `apply` | 普通悬置无明确新证据复核入口 | 对新悬置记录引入针对原缺口的新证据条件；沿现有请求/登记核对，记录已复核证据以止重。复核准入不自动done；未验证效果保持未完成。 |
| [debug_loop.py](https://github.com/melonthrower/regrow/blob/fd8cfa9dac90370a899fa869ba0af7bd06285bc6/experiments/clock_manual_20260919/debug_loop.py#L44) L44–59 `classify/fingerprint`、L254–264调度分支 | 一些局部停止及schedule落到修代码 | 显式区分本轮局部悬置/当前无可执行工作与程序缺陷，并在tick消费该分类，避免只改classify后仍落入修代码。第一阶段保留fingerprint与总预算，不顺带重做服务策略。 |

## 测试改动（全部为拟新增，非现有通过结果）

- `tests/test_update_suspension.py`：成功回执悬置、不重复GUI、发布失败保留pending、同区块继续、缺回执拒绝、旧前图不沿用。
- 现有诊断测试邻接新增nullable anyOf字段定位案例；现有路由/任务复核测试补同控件不同操作和新证据准入。
- 原生模型实验输出保存独立run副本，完整请求/回复/纠错历史及真实截图不改写；不得只用手工回复单测替代验收。

本表是逐处实施计划，不是已经应用的补丁。Astra意见返回前，本设计不宣称任何运行行为已经改变。
