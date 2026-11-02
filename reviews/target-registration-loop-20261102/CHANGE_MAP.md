# 目标补登记循环：具体变更图

本表固定到本目录所在导出提交；导出父提交91a44df3dcc679e94cf6daab600ae19328af6cb4。链接锚点属于本次tested-source实际文件，不套用正式src的旧行号。新文件仅给出本版新行号，不虚构既有位置。

| 原源码路径 | 本版函数锚点 | 变化 |
|---|---|---|
| src/regrow/recognition/discovery_completion.py | [supplement:145](tested-source/regrow/recognition/discovery_completion.py#L145) · [prepare_registration:216](tested-source/regrow/recognition/discovery_completion.py#L216) | 补充可限定completion_items，登记后仍保留无关pending；普通补全继续要求处理全部给定缺口。 |
| src/regrow/recognition/locator.py | [prepare:54](tested-source/regrow/recognition/locator.py#L54) | 同步目标相关候选、模型材料、ID映射；仅选择本次目标待补项。 |
| src/regrow/recognition/visual_region_locator.py | [plan:47](tested-source/regrow/recognition/visual_region_locator.py#L47) | required_regions可选输入；跨工作区目标允许多区块核对，候选优先级与8项上限。 |
| src/regrow/runtime/action_executor.py | [execute:44](tested-source/regrow/runtime/action_executor.py#L44) | 将原动作episode传给补登记；仍在创建投递记录之前返回。 |
| src/regrow/traversal/discovery_step.py | [commit:49](tested-source/regrow/traversal/discovery_step.py#L49) | 正式登记后按目标状态续接；保持幂等；恢复任务读取本轮落盘裁图。 |
| src/regrow/traversal/observation.py | [retained_action_target:102](tested-source/regrow/traversal/observation.py#L102) · [register_action_target:147](tested-source/regrow/traversal/observation.py#L147) | 保留结构化目标和原动作步骤；同帧补充不被新截图刷新打断；重复未关联目标沿已有暂挂。 |
| src/regrow/traversal/register_update.py | [commit_update:61](tested-source/regrow/traversal/register_update.py#L61) | 结算前保存旧特殊暂挂来源；新裁图后仅复核未被本轮新结算覆盖的旧暂挂。 |
| src/regrow/traversal/task_deferral.py | [defer:104](tested-source/regrow/traversal/task_deferral.py#L104) · [resume_localized:193](tested-source/regrow/traversal/task_deferral.py#L193) | 复用blocked与现有调度；特殊目标暂挂可凭跨区块新证据恢复，普通暂挂不变。 |
| 新增 src/regrow/traversal/target_registration.py | [context:22](tested-source/regrow/traversal/target_registration.py#L22) · [registered:51](tested-source/regrow/traversal/target_registration.py#L51) · [advance:141](tested-source/regrow/traversal/target_registration.py#L141) · [retry_evidence:171](tested-source/regrow/traversal/target_registration.py#L171) | 新增：集中目标上下文、登记后判断、一次有新增候选的补充、暂挂及重试证据。 |

新增tests/test_target_registration_continuation.py覆盖：无视觉命中仍给出相关候选、重名不合并/不伪造可见、目标一次补充后暂挂并选下一任务、跨区块别名新证据解挂、避免覆盖本轮新defer、无关gap不阻塞、补充子集保留其他gap及普通全量补全合同。现有test_action_target_registration.py验证未关联前不投递等相邻合同。共9项通过。

真实验收：Settings候选新增r0007，Night Light新c0036归r0007；Gedit候选新增r0001并复用c0001。两例均通过下一次正常动作选择与绑定。4次HTTP/0GUI，旧任务仍pending；失败/补充/暂挂分支仅辅助检查，不声称全部模型分支通过。
