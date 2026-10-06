# 具体改动定位（实施版）

基线 59ad0bf232c96e3dd2a88063b11410bf25252477；下表为本批实施源码核验行号。最终导出提交及永久链接见交付包FINAL_SOURCE_MAP.md。无新Python模块；update_step.py整文件删除，其原基线1–11行可在Git历史核对。

| 仓库相对路径 | 函数 | 当前行号 | 实施状态与实际行为 | 验收边界 |
|---|---|---|---|---|
| experiments/clock_manual_20260919/discovery_step.py | publish | 30–53 | 邻接保留/调用链受影响：读取/发布仍在本模块；commit直接调用Locator校验和调度器 | 发现请求等价、登记与局部拒绝 |
| experiments/clock_manual_20260919/discovery_step.py | commit | 81–218 | 已修改：读取/发布仍在本模块；commit直接调用Locator校验和调度器 | 发现请求等价、登记与局部拒绝 |
| experiments/clock_manual_20260919/region_tasks.py | apply_plan | 40–113 | 已修改：保留任务登记；schema从TaskProposer取得，删除提议出口 | 任务请求等价、归属与完成依据 |
| experiments/clock_manual_20260919/region_tasks.py | commit_plan | 116–159 | 邻接保留/调用链受影响：保留任务登记；schema从TaskProposer取得，删除提议出口 | 任务请求等价、归属与完成依据 |
| experiments/clock_manual_20260919/repair_stages.py | observe | 458–510 | 已修改：补观察和身份校验直接使用Locator，原Runner登记保留 | 失败补观察留档、同帧续接 |
| experiments/clock_manual_20260919/repair_stages.py | observe_registered | 513–554 | 已修改：补观察和身份校验直接使用Locator，原Runner登记保留 | 失败补观察留档、同帧续接 |
| experiments/clock_manual_20260919/control_observation_repair.py | begin | 86–132 | 已修改：诊断请求直接使用TaskProposer | 全局调用方审计；未单独新做控件迁移模型验收 |
| experiments/clock_manual_20260919/shared_controls.py | refresh | 32–67 | 已修改：refresh同步调用shared_tasks后才由调用方解除成员 | 解除未执行投影、保留本地动作 |
| experiments/clock_manual_20260919/recovery.py | action_defaults | 26–31 | 已修改：不再自动注入已删除的request_task_review默认值 | 原有恢复测试、新Luna原答在基线拒绝而当前正常校验 |
| experiments/clock_manual_20260919/recovery.py | resolve | 48–57 | 邻接保留/调用链受影响：不再自动注入已删除的request_task_review默认值 | 原有恢复测试、新Luna原答在基线拒绝而当前正常校验 |
| experiments/clock_manual_20260919/locator.py | request_from_run | 131–148 | 核对无需改动：唯一发现请求/定位/阶段驱动实现 | 发现请求等价与恢复上下文 |
| experiments/clock_manual_20260919/locator.py | run_stage | 151–161 | 核对无需改动：唯一发现请求/定位/阶段驱动实现 | 发现请求等价与恢复上下文 |
| experiments/clock_manual_20260919/task_proposer.py | proposal_schema | 7–11 | 核对无需改动：唯一任务schema/完整请求实现 | 任务请求等价与只读上下文 |
| experiments/clock_manual_20260919/task_proposer.py | plan_request | 14–71 | 核对无需改动：唯一任务schema/完整请求实现 | 任务请求等价与只读上下文 |
| experiments/clock_manual_20260919/result_updater.py | build_update_request | 24–77 | 核对无需改动：唯一更新候选请求/校验实现，正式发布仍在register_update | 更新请求等价、失败回执、pending续接 |
| experiments/clock_manual_20260919/result_updater.py | route_update | 80–111 | 核对无需改动：唯一更新候选请求/校验实现，正式发布仍在register_update | 更新请求等价、失败回执、pending续接 |

验收：旧接口无生产调用；发现/提议/更新/Android导航/桌面五份完整请求等价；失败回执与pending续接/共享解除不丢事实；恢复click合法回复不再被框架补入的旧字段拒绝；保存帧模型验收止于执行前。已实施、离线通过和模型验证的边界分别见DESIGN.md及月度日志。
