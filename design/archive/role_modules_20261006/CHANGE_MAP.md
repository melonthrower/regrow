# 角色职责重构：基线与实施改动地图

基线固定到私有regrow导出提交 `49a3b371b92a0c9080889a56be193facb56c09f1`。以下当前行号属于本批待提交源码；提交后的固定链接另随Astra交付包 FINAL_SOURCE_MAP.md 提供。实现已完成；模型验收结论以本批报告为准，不由本地图预先宣布。

新文件：`experiments/clock_manual_20260919/shared_tasks.py`、`tests/test_role_module_contracts.py`（基线不存在，不编造旧行号）。既有角色保留原名/源码根。

| 基线函数与行号 | 当前唯一实现与行号 | 具体改动/保留职责 | 验收案例 |
|---|---|---|---|
| `experiments/clock_manual_20260919/discovery_step.py:59-141` `prepare` | `experiments/clock_manual_20260919/locator.py:46-128` `prepare` | 发现请求/schema/身份历史上下文 | discovery |
| `experiments/clock_manual_20260919/discovery_step.py:151-168` `request_from_run` | `experiments/clock_manual_20260919/locator.py:131-148` `request_from_run` | 完整run发现入口 | discovery |
| `experiments/clock_manual_20260919/discovery_step.py:402-412` `run_stage` | `experiments/clock_manual_20260919/locator.py:151-161` `run_stage` | 发现与恢复共用阶段驱动 | discovery |
| `experiments/clock_manual_20260919/discovery_step.py:465-489` `locate_task_control` | `experiments/clock_manual_20260919/locator.py:195-219` `locate_task_control` | 仅刷新已选任务控件定位 | focused |
| `experiments/clock_manual_20260919/discovery_step.py:379-399` `schedule_local_inspection` | `experiments/clock_manual_20260919/traversal_scheduler.py:166-186` `schedule_local_inspection` | 已识别前景可导航，无完整清单门槛 | focused/navigation |
| `experiments/clock_manual_20260919/discovery_step.py:361-376` `offer_foreground_navigation` | `experiments/clock_manual_20260919/traversal_scheduler.py:148-163` `offer_foreground_navigation` | 同帧前景接续导航 | focused |
| `experiments/clock_manual_20260919/discovery_step.py:446-462` `retire_completed_goal` | `experiments/clock_manual_20260919/traversal_scheduler.py:189-205` `retire_completed_goal` | 退出已结束目标并调度剩余工作 | focused |
| `experiments/clock_manual_20260919/region_tasks.py:17-21` `proposal_schema` | `experiments/clock_manual_20260919/task_proposer.py:7-11` `proposal_schema` | 任务输出合同 | tasks |
| `experiments/clock_manual_20260919/region_tasks.py:48-105` `plan_request` | `experiments/clock_manual_20260919/task_proposer.py:14-71` `plan_request` | 任务控件/历史/共享知识/提示 | tasks |
| `experiments/clock_manual_20260919/update_step.py:20-73` `build_update_request` | `experiments/clock_manual_20260919/result_updater.py:24-77` `build_update_request` | 结果观察请求与schema | update |
| `experiments/clock_manual_20260919/update_step.py:76-107` `route_update` | `experiments/clock_manual_20260919/result_updater.py:80-111` `route_update` | 候选校验；正式写入仍由登记器 | update |
| `experiments/clock_manual_20260919/shared_controls.py:115-194` `synchronize_tasks` | `experiments/clock_manual_20260919/shared_tasks.py:8-88` `synchronize_tasks`（新文件） | 共享任务定义/结果引用及失效撤回 | shared tests |
| `experiments/clock_manual_20260919/shared_controls.py:197-200` `automatic_tasks` | `experiments/clock_manual_20260919/shared_tasks.py:91-94` `automatic_tasks`（新文件） | 披露来源且不声称本地已执行 | shared tests |
| `experiments/clock_manual_20260919/shared_control_review.py:63-114` `apply` | `experiments/clock_manual_20260919/shared_tasks.py:98-114` `reconcile_detached_tasks`（新文件） | 刷新后清理；无本地证据移除、有本地证据保留阻塞 | shared conflict tests |
| `experiments/clock_manual_20260919/discovery_step.py:222-358` `commit` | `experiments/clock_manual_20260919/discovery_step.py:81-217` `commit` | 保留正式身份登记，只改调用归属 | discovery |
| `experiments/clock_manual_20260919/region_tasks.py:184-227` `commit_plan` | `experiments/clock_manual_20260919/region_tasks.py:116-159` `commit_plan` | 保留正式任务登记 | tasks |
| `experiments/clock_manual_20260919/register_update.py:99-364` `commit_update` | `experiments/clock_manual_20260919/register_update.py:99-364` `commit_update` | 保留正式结果登记，调用新候选校验入口 | update |
| `experiments/clock_manual_20260919/repair_stages.py:263-299` `refresh` | `experiments/clock_manual_20260919/repair_stages.py:263-299` `refresh` | 纠错按角色重建请求 | focused |
| `experiments/clock_manual_20260919/historical_inventory.py:72-91` `region_request` | `experiments/clock_manual_20260919/historical_inventory.py:72-91` `region_request` | 历史任务复核接同一提出器 | request comparison |
| `experiments/clock_manual_20260919/recover_loop.py:30-156` `run` | `experiments/clock_manual_20260919/recover_loop.py:30-156` `run` | 恢复后的发现直接接Locator实现 | focused |
| `experiments/clock_manual_20260919/run_task_step.py:30-158` `_run_step` | `experiments/clock_manual_20260919/run_task_step.py:30-158` `_run_step` | 编排保留五角色连接及已执行优先（本批未改） | update main round |
| `experiments/clock_manual_20260919/action_proposer.py:6-52` `render_work` | `experiments/clock_manual_20260919/action_proposer.py:6-52` `render_work` | 复用既有动作提出与TaskProposer连接（本批未改） | navigation/desktop comparison |
| `experiments/clock_manual_20260919/action_executor.py:41-105` `ActionExecutor` | `experiments/clock_manual_20260919/action_executor.py:41-105` `ActionExecutor` | 复用已有投递前检查/回执边界（本批未改） | focused only |

验收：5份完整真实run请求与基线相等；76项聚焦检查（另列旧测试债）。保存帧原生Luna由正常入口/Runner/传输构建、纠错和登记，原答不编辑；不投递GUI。本批不证明安卓长期运行不会中断、旧图语义正确或全应用完成。
