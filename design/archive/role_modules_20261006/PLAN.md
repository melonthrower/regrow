# Role Modules Implementation Plan

> Root agent implements and tests inline (standing user requirement); independent unfamiliar-reader reviews the completed batch. Use executing-plans, without implementation delegation.

**Goal:** 让五个角色文件承接真实职责，主程序调用关系清楚且现有运行语义不变。
**Architecture:** 并列角色模块，复用正式登记与身份实现。抽出共享任务逻辑，保留刷新与解除关系的先后。
**Tech Stack:** Existing Python, pytest, JSON/schema and saved-frame Luna transport.
**Spec:** [DESIGN.md](DESIGN.md)

## Global Constraints
- 活动checkout保持原位；root与旧候选修改均不碰。
- 单一实现、旧出口只绑定；不改提示内容/模型角色/预算/证据布局。
- 实际行为验收从完整真实run正常入口构造，原答不编辑；本轮GUI=0。
- 每批产物保留在role_modules_20261006_01；提交仅含精确任务路径，核对后同步私有regrow。

## Review Focus
- 旧函数出口/动态加载不能形成导入环或读错冻结源码。
- 发现补观察仍使用同帧前景和身份上下文。
- 任务schema和提示资源来自同一选定源码根。
- 共享解除先失效投影再撤销/阻塞，本地证据保留。
- 已执行待登记优先；局部空闲不提升为全局完成。

## Task 1: 角色职责与共享连接
- [x] 新增tests/test_role_module_contracts.py，直接从角色模块构造请求/校验结果并检查语义；记录迁移前失败。
- [x] discovery_step的schema/prepare/request_from_run/run_stage/locate_task_control归locator；导航安排/目标退出归traversal_scheduler。旧出口绑定唯一实现。
- [x] region_tasks的proposal_schema/plan_request归task_proposer；更新stepwise/纠错/历史请求调用点，登记不迁移。
- [x] update_step的build_update_request/route_update/known_regions归result_updater；移除角色→旧更新器的反向导入。
- [x] shared_controls的synchronize_tasks/automatic_tasks及shared_control_review中失效任务清理归shared_tasks；原刷新时点不变。
- [x] 聚焦角色、发现、任务、更新、共享解除与调度续接测试，通过后记录Tier3范围，不跑全门禁。

## Task 2: 完整上下文验证与交付
- [x] 复用真实run完整副本，冻结本批源；比较原生构造请求与基线，并保存预览/截图/来源。
- [x] 独立陌生初读代码、请求、图片、合同；保存初读后另给意图对照，修复实质问题并复阅。
- [x] 代表性保存帧Luna调用经过正常校验/纠错/登记，检查身份/任务/图，记录失败与修复，不触碰设备。
- [x] 更新当前模块图、框架索引、Region对齐、每日/月度记录，归档旧提案；生成固定提交定位图。
交付检查点：实施验收后精确暂存/提交、私有同步，并导出脱敏Astra ZIP；最终提交、同步、包校验和工作树状态由交付包VERSION/FINAL_SOURCE_MAP及最终回复记录。
