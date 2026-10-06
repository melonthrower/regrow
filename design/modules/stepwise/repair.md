# 纠错与异常恢复

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

处理失败提案、记录修订、暂挂和应用异常。

## 输入、输出与边界

失败原答、诊断、当前任务与证据 → 修正/补观察/记录修订或暂停。已执行动作先结算，不因登记失败重做GUI。

主要接口：`step_repair.Runner / request；repair_stages；recover_loop`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 从哪一步进入，回到哪里

三步中的发现、任务清点、动作选择和结果更新，其正常请求和纠错沿 `step_repair.Runner.perform` 及 `repair_stages.accept` 接受/登记；修正回复不另建一套写入器。具体刷新与补观察按stage分流，不保证所有步骤都采用同一种截图或同一重建方式；应用恢复另由下表的 `recover_loop.run` 驱动。

| 入口 | 核对与恢复连接 | 不可混淆的边界 |
|---|---|---|
| [第一步](01_discovery.md)发现/任务清点被拒绝 | `repair_stages.refresh` 回到发现或任务请求；接受后调用 `discovery_step.commit` / `region_tasks.commit_plan` | 补充发现可更新观察；清点complete不等于探索完成 |
| [第二步](02_action.md)动作提案/定位失败 | action分支校验与绑定，必要时刷新请求或补观察；投递前变化由 `Runner.reject_action` 保留原提案并纠错 | 普通动作和动作纠错坐标以唯一当前图为依据；提案被接受仍不是已执行 |
| [第三步](03_update.md)结果登记失败 | update分支重审原动作结果；`run_task_step.resume_update_request` 补齐待登记证据，经 `register_update.commit_update` 写入 | 保留attempt与原回执；不能因为登记失败重发GUI |
| 已归档的结果待登记 | `suspended_updates.restore_next` 恢复原episode → 原Runner → `validate_commit / complete` → 新图发现；详见[第三步续接](03_update.md#缺失结果的续接与当前边界) | 相关区块后续变化时暂停，不用旧结果覆盖新记录，不重做GUI |
| 应用异常/离开范围/受阻 | `recover_loop.run` 按当前状态处理，恢复后的发现沿 `discovery_step.await_discovery` 接回主流程 | 有新观察才可确认恢复；不会自动完成原任务 |

记录修订见 `repair_stages.edit_record`；补观察见 `observe / observe_registered`，更新步的补图还有独立 `update_observation_request`。改动某一步时检查对应分支、共享地图上下文及重启后的pending读取，不把普通路径通过当作这些连接都已验证。

累计结果核对、功能整理本身是正常子流程；它们的请求失败才进入纠错。具体调用与返回位置见[第三步](03_update.md)。连接核对结论写入本批变更记录，格式见[开发入口](../../../DEVELOPMENT.md#change-connections)。

## 源码与提示入口

- [step_repair.py](../../../experiments/clock_manual_20260919/step_repair.py)
- [repair_stages.py](../../../experiments/clock_manual_20260919/repair_stages.py)
- [correction_prompts.py](../../../experiments/clock_manual_20260919/correction_prompts.py)
- [correction_crop_feedback.py](../../../experiments/clock_manual_20260919/correction_crop_feedback.py)
- [model_reply_parse.py](../../../experiments/clock_manual_20260919/model_reply_parse.py)
- [recovery.py](../../../experiments/clock_manual_20260919/recovery.py)
- [recover_external.py](../../../experiments/clock_manual_20260919/recover_external.py)
- [recover_loop.py](../../../experiments/clock_manual_20260919/recover_loop.py)
- [recovery_stall.py](../../../experiments/clock_manual_20260919/recovery_stall.py)
- [branch_switch.py](../../../experiments/clock_manual_20260919/branch_switch.py)
- [suspended_updates.py](../../../experiments/clock_manual_20260919/suspended_updates.py)
- [ownership_review.py](../../../experiments/clock_manual_20260919/ownership_review.py)
- [action_owner_correction.py](../../../experiments/clock_manual_20260919/action_owner_correction.py)
- [control_observation_repair.py](../../../experiments/clock_manual_20260919/control_observation_repair.py)
- [task_record_repair.py](../../../experiments/clock_manual_20260919/task_record_repair.py)
- [shared_control_review.py](../../../experiments/clock_manual_20260919/shared_control_review.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [纠错](../../../experiments/clock_manual_20260919/遍历prompt/纠错)
- [异常处理](../../../experiments/clock_manual_20260919/遍历prompt/异常处理)
- [监督](../../../experiments/clock_manual_20260919/遍历prompt/监督)

## 验证与未完成事项

原纠错/恢复链已存在，格式通过不证明身份或导航成功。重复失败、错误登记或任务跑偏需暂停讨论；缺证据时不堆叠新重试。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#repair)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 任务判断修订与预算停止
发现/任务清点纠错的task编辑能力增加reopen_task：before为原控件名，after为具体未知内容目标，evidence说明旧判断遗漏。原任务留revisions，不迁移执行历史。正常清点与改名提案同样诊断旧record变explore，沿已有事务校验登记。HTTP/GUI额度不足为budget_limit，待登记回执与pending保留；真实投递故障仍是interrupted，不能用预算状态遮蔽。
