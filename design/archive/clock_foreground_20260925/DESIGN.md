# 已完成入口后的前景待办：独立补丁

基线：`6581a18ef0a2511b0decbe1a07385b775afb6051`。本文件记录已经实现的有限改动；导出包 CHANGE_MAP.md 固定到实际提交并给出验证过的行号。当前合同在 stepwise_debug_loop。

## 问题与范围

0038 的原入口任务已经 done，工作区仍是后方菜单 r0007，当前前景 r0008 有待办。原 attach 将旧 navigation_advice 提前返回，要求返航。入口最后一次实际动作为 ENTER，control_ref=null 且标记为准备动作，旧点击入口交接未覆盖。

本轮只修这条交接链。此前身份拆分、知识有效性、功能调度的工作保存在另一工作区，未纳入本补丁，也不宣布已接受。原污染图保留为故障证据、不续跑，不修整份历史图。

## 已实现

- task_routing：复用已登记的任务完成证据，选择已观察前景内仍有工作的区块。保留 pending 目标、明确导航、异常与准备复核。跨区动作按原任务 owner 识别完成，不能只查实际动作 source。
- region_tasks.attach：交接成立时按新工作区重新组装上下文，再走原任务选择；交接不成立时保留原流程。
- discovery_step.retire_completed_goal：正常续跑安全点通过既有快照事务保存交接；存在 execution_pending.json 时不走新增交接。

没有新增模型调用、prompt、CLI 开关、持久 schema、任务类型或通用优先级系统。任务完成本身由原结算负责；本改动不增加 done、不转移已执行动作。

## 验收与边界

真实 0038 保存记录走正常 assemble_current_context：旧版 return_to=r0007，新版 task_region=r0008。正常 retire_completed_goal 在副本保存 working_region=r0008，原证据未变。此为无模型的正常上下文构建和程序发布回放，不是 Luna 回复或 GUI 验收。

34 项离线检查覆盖已完成入口、键盘准备动作、跨区 owner、pending 连续性、显式导航可见/不可见、异常、待结算和安全点持久化。旧 completed_surface_uses_known_route_instead_of_inventing_return 在基线和补丁均因功能整理请求优先而失败；本次未改功能整理，最终选择中显式排除该项，保留失败日志。不声称全套回归通过。

未验证：实际 Luna 如何选择动作、真实导航与后图、全应用覆盖、任意调度公平性。默认停在离线交付；不接管原桌面，不以旧实验额度授权新运行。
