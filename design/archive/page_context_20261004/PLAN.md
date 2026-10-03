# 当前页面与父页面上下文 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans；根代理实施，陌生读者独立审核。

**Goal:** 让正常逐步遍历请求同时保留当前结构、真实父页面来路与原目标，减少树维护错误及无关历史摘要抢占。

**Architecture:** page_context从唯一原始账本即时派生；原观察、任务、动作和身份不迁移。正常请求构造和换帧刷新共用该模块，调度只消费已核对的目标/来路条件。

**Tech Stack:** 现有Python、pytest、正常Luna发送/Runner，无新依赖。

**Spec:** DESIGN.md

## Global Constraints

完整原生请求及原样Luna回复；坐标单当前图；原运行/设备不改；测试产物集中本任务artifacts/tmp_tests、真实调用集中artifacts/runs；不上传凭据/私人端点；已有用户修改不纳入提交。

## Review Focus

历史父页面当当前页、同名控件串owner、循环/多入口来路猜测、换图未重观察、折叠兄弟误算完成。每类由下面聚焦用例约束。

## 一个连贯实现批次

- [x] 写tests/test_current_page_context.py：真实形状records/state测试父页面与当前弹窗同时存在、关闭弹窗后当前树移除、历史兄弟折叠但未完成、相同控件外貌不改ID、循环/断链明确缺口、换帧降为历史；观察红测。
- [x] 实现page_context.build/attach/refresh/advances_goal；接入assemble_current_context和target_observation.refresh；不会改原账本。
- [x] 加tests/test_current_region_priority.py父目标前景续接测试及无来路/错误目标反例；接入historical_inventory.request，保留强制审核优先。
- [x] 运行本批与任务/请求/单图/帧来源相邻测试，AST及diff检查；失败定位并复现基线，记录影响边界。
- [x] 陌生Astra先独立读代码和正常生成请求/真实图，再比对用户意图，处理发现并聚焦复核。
- [x] 完整真实run隔离副本构造三种状态，先正常Luna小样本及原答登记，再按结果补例；检查身份、目标、来路和图，不以schema通过代替语义验收。
- [x] 更新必要模块/索引/历史对齐和日志，保存证据、失败轮与独立审阅。
- [ ] 交付收尾：Astra ZIP、精确提交、私库同步及固定到导出代码提交的v2变更图。此处是提交前计划快照，不预先勾选；实际交付以最终REPORT/VERSION及v2变更图为准。

执行授权来自用户“能实现一下吗…请你试试”，随后补充必须包含父页面来路；按仓库默认根代理执行，不重复要求批准同一实现方向。随后追加的三步共享、实机同步、新Clock短批以及取消自动业务回放按DESIGN_V2.md一并实施；完整应用遍历不由短批替代。

结果：见2026-10月日志与本批交付包。v1初期101项及最终相关63项/图页5项为不同范围，不能相加冒充独立总数；保存帧10HTTP/0GUI，实机25HTTP/8GUI。中间源、失败调用、投递前故障与监督恢复均保留。
