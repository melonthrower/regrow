# 旧入口与重复测试清退

基线 59ad0bf232c96e3dd2a88063b11410bf25252477；实施状态：已改代码，验证结果见本月日志与独立交付包。最终导出提交的精确行号由包内 FINAL_SOURCE_MAP.md 固定。

调用方直接使用 locator、task_proposer、result_updater、traversal_scheduler 和 shared_tasks；删除 update_step 纯转发文件，以及 discovery_step/region_tasks/shared_controls 上的对应旧出口。保留原发现、任务和结果正式登记；共享关系刷新仍先同步任务再清理脱离成员。较早的 selection/settlement 出口不在此轮范围。

发现恢复 action_defaults 仍注入已从共享 schema 删除的 request_task_review=False，合法恢复动作因此被拒绝；清退该默认字段。沿用现有恢复测试，不另建测试文件；使用真实恢复前快照与保存帧，从正常恢复入口发一次新 Luna 请求，GUI额度为0，只验收回复和决策。

删测依据：

| 删除/合并 | 保留的实际保障 |
|---|---|
| test_role_module_contracts.py 四项 | 恢复上下文检查移入 recovery_discovery；任务只读上下文、失败回执和范围外导航断言合并入原模块测试 |
| test_unresolved_action_cannot_complete_other_control | 原 provenance 测试直接收集，使用真实形状的动作记录验证错控件不完成任务 |
| test_navigation_precedes_foreground_task_inventory | 删除旧 attach 返回同一对象的断言；保留调度优先和无完整清点也可离开的检查 |
| test_task_stage_then_return_with_no_control_and_no_fake_edge | 删除已废弃串行清点门槛；正常发现驱动测试保留 back 无控件绑定及读请求不改图。旧非正式重复back记录不再作为该测试合同 |

净减少6个测试函数。只改旧入口的测试同步调用方；不因历史测试失败而删除其有价值的目标。选取受影响连接检查，不运行全框架门禁。原运行、原答、冻结源码和历史测试记录不清除。
