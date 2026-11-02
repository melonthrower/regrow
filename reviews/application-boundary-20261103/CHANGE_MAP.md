# 具体改动表

固定源码提交：[fceb3b74](https://github.com/melonthrower/regrow/tree/fceb3b74da9a86c3202de71f86d12c0ab80a09d6)。这是本轮已实现、有限验证的研究快照，不表示全量门禁或全应用完成。源码固定为source-v8；其他待审Prompt与运行图不在导出中。

| 文件与函数（实际行号） | 当前实现／退役逻辑 |
|---|---|
| `src/regrow/traversal/application_judgement.py`：[extend_schema L7–29](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/application_judgement.py#L7-L29)；[prepare L32–46](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/application_judgement.py#L32-L46)；[accept L49–76](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/application_judgement.py#L49-L76)；[action_payload L79–81](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/application_judgement.py#L79-L81) | 新增文件：统一本次应用材料、当前任务/动作合同与异常交接。没有旧文件行号。 |
| `src/regrow/runtime/model_transport.py`：[prepare_request L104–167](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/runtime/model_transport.py#L104-L167) | 正常发送复用目标应用槽；保留已发纠错合同。 |
| `src/regrow/runtime/action_commands.py`：[selection_schema L17–50](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/runtime/action_commands.py#L17-L50)；[for_request L52–71](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/runtime/action_commands.py#L52-L71) | 新增异常分支，正常GUI载荷剥离判断元数据。 |
| `src/regrow/traversal/task_proposer.py`：[plan_request L41–120](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/task_proposer.py#L41-L120) | 动态裁剪完成后扩展当前合同；历史调用不扩展。 |
| `src/regrow/traversal/historical_inventory.py`：[request L14–68](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/historical_inventory.py#L14-L68)；[region_request L70–88](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/historical_inventory.py#L70-L88) | 历史图保留原任务合同，不用旧图决定当前恢复。 |
| `src/regrow/traversal/repair_stages.py`：[accept L44–53](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/repair_stages.py#L44-L53)；[accept_candidate L99–200](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/repair_stages.py#L99-L200) | 异常在业务改写前交接；任务记录修订保留原新字段。 |
| `src/regrow/traversal/run_task_step.py`：[_run_step L51–241](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/run_task_step.py#L51-L241) | 任务提出/动作选择后先接恢复。 |
| `src/regrow/traversal/result_updater.py`：[route_update L99–128](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/traversal/result_updater.py#L99-L128) | 原异常拒收改为具体可读说明，决策规则保留。 |
| `src/regrow/recognition/action_target_review.py`：[accept L149–161](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/recognition/action_target_review.py#L149-L161) | 继承的异常原答无动作返回原action接受入口；不确认动作。 |
| `src/regrow/prompts/compose.py`：[action_material L123–162](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/prompts/compose.py#L123-L162) | 动作调用将目标应用材料就近显示。 |
| [src/regrow/prompts/异常处理/异常识别.prompt L1](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/prompts/异常处理/异常识别.prompt#L1) | 替换此前未接入的长手册为用户批准的通用判断，正常目标应用材料读这一份。 |
| [src/regrow/prompts/调用/异常恢复.prompt L4](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/prompts/调用/异常恢复.prompt#L4) | 恢复必须确认回到目标应用。 |
| [src/regrow/prompts/对象/区块.prompt L198](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/prompts/对象/区块.prompt#L198) | 同步异常词项、外部业务不登记与原任务受阻进展职责；新增两字段异常分支说明。 |
| [src/regrow/prompts/流程/调用组成.json L2109](https://github.com/melonthrower/regrow/blob/fceb3b74da9a86c3202de71f86d12c0ab80a09d6/src/regrow/prompts/流程/调用组成.json#L2109) | 五类主调用及继承动作合同的目标核对同步组成；更新异常说明不再依赖退役controls字段。 |

验收：8项当前合同聚焦通过；六例真实保存帧最终7HTTP/0GUI正常接受，另6HTTP失败原件保留。36HTTP实机小窗、9框架GUI命令及另1操作员窗口准备分别计账。Calc恢复有人工准备，不能称全自动；Writer a0030登记纠错仍未解决而停审；GIMP/VLC重复探索保持停止。

目标核对异常分支已有聚焦检查；本批实机未声称触发它的external分支。当前队列只放行14个benchmark目标、最大4路、100调用停审；其中12旧run续接、2首次run仍需正常首屏核对。

提案与实现：用户先审完整正文/字段后授权；本表描述已实现行为。更广的候选完整收集、历史清理泛化、自动窗口恢复和任务难度调整均未实现。
