# 最小遍历修复设计与执行计划

依据用户提供的 `ReGROW_minimal_traversal_review_20261006.md`，基线 `4d30c44`。root 实现与测试，陌生读者独立审阅。保留已有候选；仅单独采用评审指明的直接滚动片段。原运行、原答不改写。

目标：可信当前动作不等待无关记录完整；执行事实由程序回执确定。已投递未登记只恢复结果处理。普通任务按控件/动作去重，移动任务仍能到达新视口。

1. 滚动：复用 `region_scroll.bind` 当前单图坐标校验，删除边界 attach；`inventory_scroll.select` 读登记后的任务。允许关闭遮挡等准备动作。新观察明确提议继续滚动时复用旧任务、排除此前移动尝试，不以一次 done 代表所有视口。
2. partial：`discovery_step.commit` 保留可信对象及不确定缺口；`region_tasks.commit_plan` 与 `task_selection.attach` 优先已有 pending。缺口补充仍需原帧；换帧把旧缺口留作历史，使用新帧正常发现，禁止旧帧锁阻塞无关动作。
3. 更新：从新 schema/prompt 删除 `exploration_update`。旧请求仍按原格式读取；回执确定投递，后图确定结果。`task_settlement` 共用参数事实逐条验证，错误事实保存缺口并不入确认知识；不可分离的身份、绑定、结果错误仍拒绝整笔更新。
4. 整理：`task_selection` 不在离开已探索区块前要求 functions；`run_task_step.current` 不优先历史整理。`run_progress_session` 在当前 GUI 无可执行工作后调用原知识登记入口整理，预算与 pending 仍由框架维护，不加线程、队列或开关。
5. 验证：先红测复现，逐项修复后做受影响 Tier 3 聚焦检查。基于干净已接受源构建冻结候选，以正常入口、完整真实 Clock run、原 Luna 回复及正常 Runner 登记做保存帧验收；再各端短批实际遍历，检查后图、身份、任务与恢复，无语义错误才扩大。

评审重点：改名滚动、同帧无进展重复、成功回执未登记恢复、防旧帧补全锁、准备动作不完成滚动、局部参数缺口不污染确认知识、历史 schema 保留、结束后的整理不增加 GUI。

代码定位：`experiments/clock_manual_20260919/{region_scroll,action_binding,inventory_scroll,region_tasks,task_selection,discovery_step,discovery_completion,run_task_step,stepwise_flow,repair_stages,update_step,registration_diagnostics,task_settlement,register_update,run_progress_session}.py`；对应 schema/prompt；测试放 `tests/`。不改采集、来源图或旧运行源码。

运行位置：活动 checkout 见 DEVELOPMENT；日志/初始状态/失败探针在 `artifacts/tmp_tests/minimal_fix_20261006_01`，真实证据在 `artifacts/runs/minimal_fix_20261006_01`，便携包在 `to_astra/minimal_fix_20261006_01`。全门禁及全应用覆盖不在本批验收范围。

进度与逐次命令保存在上述任务目录的 ledger；实现、保存帧与 GUI 实测分别记录。最终变更图使用实际导出提交锚点，未验证代码不提交为已接受结果。

2026-10-06用户补充：当前状态看最新截图，历史用于记探索努力。共用target_observation、control_history_context及page_context只投影身份/职责与尝试结果，不把旧显示文字/状态反复带入目标卡和地图。观察提示省略与验证无关的自然变化数字，动作效果的必要数值和已验证参数事实仍作为有来源的历史证据。验收包含正常请求携带新图、努力历史保留、旧值字段消失及原答/账本未改写。

最终实现/证据：本设计所列改动已落到对应原模块，引用选择集中history_selection，无新摘要模型/队列/开关。235聚焦检查通过；完整真实run原生请求/原答正常登记及12步实际GUI分别按冻结版本报告。独立复审补齐正常清点旧描述回流、空路线、同屏历史全集、新任务未写active时的目标丢失。最终source-v14的最后旧支路修订为安卓保存帧1HTTP/0GUI，前版相关性两端2HTTP另存，实机末批source-v11；不混称实时执行。明确旧裁图/前景重叠及空闲尾部整理实测限制，见交付REPORT。具体文件/函数与验收案例见独立CHANGE_MAP，锚定实际导出GitHub提交，原版本设计和失败不覆盖。
