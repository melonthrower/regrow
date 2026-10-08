历史提案，登记接口已被[单一任务更新 v3](../../TIMER_TASK_REGISTRATION_V3.md)取代；未实施范围见新文档。

# Timer具体接线变更地图 v2

**提议，未实现。** 对应[实施方案](TIMER_TASK_PROGRESS_IMPLEMENTATION_V2.md)。基准为已导出的[3ed4cef11832357feae74c10d4701f40fef3aaa5](https://github.com/melonthrower/regrow/tree/3ed4cef11832357feae74c10d4701f40fef3aaa5)；下列路径均位于`experiments/clock_manual_20260919/`，行锚据该提交核对。两份v2文档为新文件，无既有行号。

| 路径、函数及行锚 | 当前行为 → 拟修改与接受点 |
| --- | --- |
| `task_settlement.py:150` set_next_action、`:175` settle_task、`:80` completion_target | 下一步覆盖完成目标 → 建议存本次动作，准备保持原问题和pending；合法身份/滚动目标仍保留。旧问题采用其他动作证据的结算与显式修订共用。 |
| `action_proposer.py:6` render_work；`history_context.py:172` task_goal、`:246` action_context | 使用覆盖目标及历史 → 原目标与最近尝试建议分别披露，null不复活删除建议。 |
| `result_updater.py:122` build_attempt_update、`:24` build_update_request | 当前任务状态及本任务产物 → 披露同一实际控件的旧用途问题；有候选才加resolved_tasks schema及提示，普通/纠错共用，无业务任务的导航也适用。 |
| `遍历prompt/任务/任务动作登记.prompt:9`、`:14` | 下一步兼有改绑定含义 → 仅推进建议，相关旧问题可由本次结果回答，无须原试探方式产生反馈。 |
| `register_update.py:108` commit_update | 实际动作身份登记 → 同一事务先动作、后旧问题回答关联；控件/条件不符不能采用。 |
| `task_knowledge.py:15` control_knowledge；`history_selection.py:13` task_attempts；`history_context.py:172` task_goal | 知识/历史主要取旧attempts → 共用选择器补读completion_basis.attempt，task_goal与page_history同时获得真实回答动作；知识来源显式披露。`function_scope.py:85` task_product已读取basis，核对后复用。 |
| `task_prerequisites.py:26` enroll，门禁`:42`；`stepwise_flow.py:135` shortest_known_path，门禁`:147` | 任意同控件blocked禁止准备及路线 → 两处共用窄限制判断，普通阻塞不禁边，自身前置不足允许准备；明确unexpected_exit及permitted/范围限制继续生效。 |
| `discovery_step.py:82` commit，旧缺口`:167`；`register_update.py:108` commit_update；`repair_stages.py:303` edit_record | 旧缺口处理只在发现阶段 → 提取并复用同一登记函数，接入发现/更新/历史修订事务，沿明确来源及身份解除对应项，无关缺口保留。 |
| `task_record_repair.py:5` apply；`step_repair.py:147` request；`repair_stages.py:303` edit_record | 原修订不能采用后来回答或恢复这类已尝试任务 → 连通schema、上下文、路由及正式发布，共用正常证据登记。原图保留，输入只恢复pending。 |

实施后更新直接受影响的任务、更新、执行/上下文、身份/发现合同与月度日志；共享更新/结算合同变化时同步CURRENT_FRAMEWORK和Region对齐说明。当前仅文档核对，原生保存帧及实机接受均未进行；源码变化后出新地图，不沿用本版行锚。
