# 单一任务登记变更地图 v3

对应[本批设计](TIMER_TASK_REGISTRATION_V3.md)。基准为已导出提交 [a0792f676c2cdcb7ad47049b3df338024fc1b6d3](https://github.com/melonthrower/regrow/tree/a0792f676c2cdcb7ad47049b3df338024fc1b6d3)；下列既有行锚均经该提交核对，路径相对源码仓库。实现已修改；原生保存帧结果及范围以月度记录为准，不代表 GUI 执行。

除测试外，路径前缀为 `experiments/clock_manual_20260919/`。

| 基准位置 / 函数 | 原行为 → 本批改动与核验 |
| --- | --- |
| `result_updater.py:24` build_update_request、`:122` build_attempt_update | 单任务对象 → 原任务目录及一个 task_update 数组，正常/纠错同 schema；当前任务必回，其他任务只回变化。 |
| `task_updates.py`（新文件）catalog/current/apply/latest_suggestion | 集中目录、显式结算及最近建议；核对本次候选、实际身份/回执/条件，额外答案仅用于同控件用途问题。 |
| `task_settlement.py:150` set_next_action、`:63` require_registration、`:175` settle_task、`:229` reconcile、`:311` validation_reply | 建议覆盖目标和自动同操作完成 → 建议存动作、保留目标，结算及后续对账都尊重显式任务集合；数组 findings 沿原分区规则校验。 |
| `register_update.py:108` commit_update | 单任务 findings → 读取当前项；原事务先真实身份后任务结算，拆分时保留请求引用并映射当前任务。 |
| `history_context.py:246` action_context；`history_selection.py:13` task_attempts | 原目标与最后一次建议分别披露；补读 completion_basis.attempt，回答旧问题的真实动作进入历史。 |
| `task_knowledge.py:15` control_knowledge | 知识来源补上真实完成依据，旧 hover 不冒充 click；条件限制保留。 |
| `suspended_updates.py:74` validate_commit | 读取数组建议与候选任务 owner，沿已有冲突检查拒绝过时历史登记。 |
| `遍历prompt/任务/任务动作登记.prompt:1`；`更新/动作后观察与状态更新.prompt:5`、`更新/区块变化与字段.prompt:39`（均在遍历prompt下） | 同一列表登记变化，说明回答旧用途与准备进展的边界，无 resolved_tasks。 |
| `tests/test_task_update_list.py`（新文件）；`tests/test_task_action_binding.py` | 正向、反例、拆分引用、后续对账、建议失效及原目标不变的聚焦检查。 |

已核对无需修改：ActionProposer 沿 history_context 读原任务与建议；task_proposer 的新任务登记和区块归属不变；function_scope.task_product 已读完成依据。不在本批修改：task_prerequisites、stepwise_flow 导航限制、discovery 缺口和旧图修订。原 165 次调用运行保持冻结。
