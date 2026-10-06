# 三步组件改动地图 V1

已导出起点：[melonthrower/regrow @ 513cc565fa72853d796197edd2441af7b7845a4a](https://github.com/melonthrower/regrow/tree/513cc565fa72853d796197edd2441af7b7845a4a)。
下表基线锚点固定上述提交；新文件无基线行号。实施锚点经AST核对，固定已导出提交 [6c6345d067a672bf8d80386d155fbdce5e667019](https://github.com/melonthrower/regrow/tree/6c6345d067a672bf8d80386d155fbdce5e667019)。便携包FINAL_SOURCE_MAP.md逐函数链接到该提交，不随后续文档提交改变。
冻结验收源码hash：`c7754f7a536d1e2045a57c71df23a30ff6d48c1f6034a41475b18872bdce9f37`。

设计见[DESIGN.md](DESIGN.md)。状态：下表修改已实施；验证范围见月度日志。没有待实施的新架构分支。

| 仓库相对路径 / 函数 | 基线位置与职责 | 实施位置 / 修改 | 验收对应 |
|---|---|---|---|
| `experiments/clock_manual_20260919/traversal_scheduler.py`<br>select_work, pending_work, after_round, preview_next, Scheduler | 新文件；无基线行号 | select_work 7–76, pending_work 79–96, after_round 99–106, preview_next 109–116, Scheduler 119–144；统一工作选择/续登记优先/会话续接，原请求不再选择另一项工作 | 排除前景离开、多区块在途归属、partial任务、空闲再调度 |
| `experiments/clock_manual_20260919/locator.py`<br>Locator | 新文件；无基线行号 | Locator 6–19；复用现有发现与视觉定位，无新模型角色 | 发现调度与已有观察续接 |
| `experiments/clock_manual_20260919/task_proposer.py`<br>TaskProposer | 新文件；无基线行号 | TaskProposer 6–15；复用region_tasks/traversal_scope请求、原Runner校验登记 | 原生任务准备路径与范围合同 |
| `experiments/clock_manual_20260919/action_proposer.py`<br>render_work, request_from_run, ActionProposer | 新文件；无基线行号 | render_work 6–52, request_from_run 55–111, ActionProposer 115–121；从已选工作构造完整上下文、原Runner动作校验绑定 | 真实安卓导航/桌面条目请求，原答不编辑 |
| `experiments/clock_manual_20260919/action_executor.py`<br>ActionExecutor | 新文件；无基线行号 | ActionExecutor 41–105；集中投递检查、先写pending、真实回执及截图；拒绝未登记重投 | 额度/前后图/实际2GUI短批 |
| `experiments/clock_manual_20260919/result_updater.py`<br>build_attempt_update, resume_update_request, ResultUpdater | 新文件；无基线行号 | build_attempt_update 9–65, resume_update_request 68–79, ResultUpdater 83–108；集中原更新请求和正常/中断登记，正式提交后清pending | 真实历史a0007仅补登记，0GUI |
| `experiments/clock_manual_20260919/run_task_step.py`<br>_run_step, run_step | _run_step 132–350, run_step 354–366；原职责在主函数/请求选择中 | _run_step 30–158, run_step 162–174；原主函数改为连接组件；会话/Runner/恢复及暂停边界保留 | 129聚焦及原生短批 |
| `experiments/clock_manual_20260919/stepwise_flow.py`<br>assemble_current_context | assemble_current_context 329–376；原职责在主函数/请求选择中 | assemble_current_context 329–332；公开请求入口调用唯一action_proposer实现 | 正常完整保存帧请求与后继 |
| `experiments/clock_manual_20260919/task_selection.py`<br>attach | attach 5–115；原职责在主函数/请求选择中 | attach 4–7；兼容入口调用唯一选择/渲染，不再另行调度 | 既有调用与多区块回归 |
| `experiments/clock_manual_20260919/run_progress_session.py`<br>run_session | run_session 10–81；原职责在主函数/请求选择中 | run_session 11–83；用after_round解释继续/有界知识整理/停止，账本仍在原会话 | 空闲续接、预算尾段、暂停 |

## 保留的连接
region_tasks.plan_request/commit_plan、discovery_step、visual_region_locator、step_repair.Runner、action_binding、action_commands、update_step、register_update与task_settlement保留原实现。不存在新增登记schema、完整性前置门槛、独立完成审核或API/GUI预算入prompt。

## 验证证据与限制
新测试test_traversal_scheduler/test_action_executor_component及直接相邻合同见本批final-focused-command.json与日志。独立初读、意图对照、保存帧语义审查分别保存。保存帧是完整真实run副本；移动导航及桌面选择为0GUI，补登记使用原真实回执。实机短批另记，不能用有限案例声称全应用、全地图或长期稳定。
原工作树已有候选未混入此源导出。7项与本次无关的旧测试失败在固定基线复现并保留，未运行全框架门禁。
