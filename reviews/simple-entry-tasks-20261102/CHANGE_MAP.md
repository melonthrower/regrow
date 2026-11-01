# 入口任务完成条件：具体改动

本表绑定本目录所在的GitHub提交；外部交付使用该提交的固定链接。以下行号已按tested-source实际文件核对，不能套用到仓库正式src或其他运行源。

| 源码位置 | 实际快照位置 | 已实现改动 | 实际验证 |
|---|---|---|---|
| src/regrow/prompts/对象/任务.prompt | [task.completion_condition，20–25行](tested-source/regrow/prompts/对象/任务.prompt#L20) | 入口以观察到打开目标内容为终点；内部未知后续探索 | 11个菜单任务不再预加子菜单调查 |
| 同上 | [task.update，49–55行](tested-source/regrow/prompts/对象/任务.prompt#L49) | 打开后登记直接内容及有证据关系，即可结算入口任务 | 原样生成的File条件被结算done，知识和跳转已登记 |
| src/regrow/prompts/调用/提出探索任务.prompt | [本步任务，第4行](tested-source/regrow/prompts/调用/提出探索任务.prompt#L4) | 简短提醒以打开为终点，取消固定口语句式 | 正常提出请求实际装配 |

四条原则task.definition（11–18行）保持任务开始前原文。task_type、schema、调度与旧任务条件不改。changes.patch是本轮相对开始前工作树的增量；tested-source包含先前必要上下文，不据此宣告这些旧改动全部通过。

正常入口未修改：action_proposer.request_from_run → model_transport.prepare_request → step_repair.Runner.perform；动作后使用result_updater.build_attempt_update及ResultUpdater.complete。验证完整复制新提出后的图与依赖，再使用原真实动作证据。未新增运行时调用或修改模型原答。

边界：仅入口条件与File登记/结算有限通过；不同菜单功能代表化问题未接受，未覆盖新GUI、遮挡、业务结果或后续子任务。独立审阅先读提示再看意图和真实输出，文档修订后复核通过。完整原件保留本地便携包。
