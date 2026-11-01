# 控件身份与代表探索：具体改动

本表对应本目录所在的GitHub提交；外部交付使用固定提交链接。行号属于tested-source，不能套用到默认分支正式src。实际测试完整冻结源保留在本地便携包。

| 原源码路径 | 快照锚点 | 已实现改动 | 验证边界 |
|---|---|---|---|
| src/regrow/prompts/对象/控件.prompt | [control.definition，第3行](tested-source/regrow/prompts/对象/控件.prompt#L3) | 独立对象与分组认识分开；身份不自动产生任务 | File原生独立登记及Files已有任务复用 |
| src/regrow/prompts/对象/控件.prompt | [control.identity，第17行](tested-source/regrow/prompts/对象/控件.prompt#L17) | 独立对象与分组认识分开；身份不自动产生任务 | File原生独立登记及Files已有任务复用 |
| src/regrow/prompts/对象/控件.prompt | [control.registration，第64行](tested-source/regrow/prompts/对象/控件.prompt#L64) | 独立对象与分组认识分开；身份不自动产生任务 | File原生独立登记及Files已有任务复用 |
| src/regrow/prompts/对象/控件.prompt | [control.registration_name，第75行](tested-source/regrow/prompts/对象/控件.prompt#L75) | 独立对象与分组认识分开；身份不自动产生任务 | File原生独立登记及Files已有任务复用 |
| src/regrow/prompts/对象/控件.prompt | [control.list_group，第85行](tested-source/regrow/prompts/对象/控件.prompt#L85) | 独立对象与分组认识分开；身份不自动产生任务 | File原生独立登记及Files已有任务复用 |
| src/regrow/recognition/region_identity.py | [for_request，第10行](tested-source/regrow/recognition/region_identity.py#L10) | 退役旧reuse_list_roles及同名/同组自动ref补写；保留正常显式关联 | 2项聚焦检查及正常保存帧路径 |
| src/regrow/recognition/discovery_completion.py | [prepare_registration，第213行](tested-source/regrow/recognition/discovery_completion.py#L213) | 删除同组第二成员的补交拒绝；正常诊断保留 | 同组第二成员补交：聚焦代码检查；未做模型补全验收 |
| src/regrow/recognition/discovery_completion.py | [supplement，第145行](tested-source/regrow/recognition/discovery_completion.py#L145) | 补全用途改为核对实际对象，引用共享规则 | 静态检查；本批未触发增量补全 |
| src/regrow/prompts/发现手册/增量补全.prompt | [第2行](tested-source/regrow/prompts/发现手册/增量补全.prompt#L2) | 共享用法不能替代独立对象登记 | 文本检查；未做模型补全验收 |
| src/regrow/prompts/发现手册/补登记.prompt | [第2行](tested-source/regrow/prompts/发现手册/补登记.prompt#L2) | 共享用法不能替代独立对象登记 | 文本检查；未做模型补全验收 |

测试文件 `tests/test_control_group_identity.py` 为本批新建，源快照见tested-source/tests；不为新文件编造旧行号。

任务提示/完成标准、调度、图存储、裁图与视觉算法未改。原错误来自Luna原答；旧自动复用函数不是本例已证实原因。补全唯一成员限制由陌生审阅发现后修复并复核。

验收：File24独立命令/真实裁图，入口done及跳转正常；同图24ID保持；Files已有代表任务复用且新增0项。5HTTP/0GUI，含正常补框与1次再观察格式纠错。非关闭重开、全列表知识泛化或全框架验收。
