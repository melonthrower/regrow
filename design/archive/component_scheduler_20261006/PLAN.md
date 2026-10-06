# 三步组件与集中调度 Implementation Plan

> 本批由 root 按 executing-plans 直接实现；陌生代理仅作独立审查。

**Goal:** 消除请求构造与主循环重复决定工作/停止，保留原三步执行证据链。
**Architecture:** 一个程序调度模块输出工作决定，五个可调用组件复用原模块。
**Tech Stack:** 现有 Python、pytest、原生 Luna/设备适配器，无新依赖。
**Spec:** [DESIGN.md](DESIGN.md)。

## 约束与复审重点
冻结原 run，只在新副本验证。排除与导航分离；多区块顺序不改变合法续接；
可信 pending 不等待全清点；执行不重复；预算/暂停/纠错边界沿用。
测试和日志保存至本批 artifacts，便携交付含源/diff和验证范围。

## 实施
- [x] 1. 新建 tests/test_traversal_scheduler.py，先证明无标记导航、多区块续接、
  无可推进工作及 pending 优先用例失败；运行直接相邻测试建立基线。
- [x] 2. 新建 traversal_scheduler.py：select_work(records,state,working=None) 返回
  kind/region/working_region/task/reason；运行选择和会话续接由同模块解释。
  task_selection.attach 仅兼容调用同一选择和渲染；不保留第二调度实现。
- [x] 3. 新建 locator.py、task_proposer.py、action_proposer.py、action_executor.py、
  result_updater.py，把原 _run_step 的对应职责迁入；主程序连接组件。
  保留原 Runner/登记器/执行适配器；正常与 pending 共用结果更新。
- [x] 4. 聚焦新调度、续接、恢复、投递检查及预算测试；语法与差异检查。
- [x] 5. 生成完整真实请求；陌生读者先独立理解再对照意图。
  修订后聚焦复审；原生 Luna 回复不编辑，经正常登记与后继检查。
- [x] 6. 更新模块/索引/日志，形成设计和源码定位图；切换开发导航，保留原工作树。
- [x] 7. 生成并校验脱敏便携ZIP，精确提交并同步私有regrow；以实际交付/提交回执确认。

实施提交 `6c6345d067a672bf8d80386d155fbdce5e667019` 已同步私有regrow；便携包 `to_astra/component_scheduler_20261006_01.zip` 已通过相对链接、脱敏与ZIP校验。源码自原生验收source-v3后未改，旧候选状态和diff逐字节保留；本次仅补固定提交定位和完成回执。
