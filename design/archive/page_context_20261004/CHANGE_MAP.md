# 变更图 v1：拟实施

来源固定于私库 melonthrower/regrow 导出提交 `6996f285be7950bd89ddaf300de6576c0dcd6c02`；下面既有锚点须在该提交核对。本文是拟改范围，不是已验证行为。运行依据另为Clock冻结候选18207fe2，不等于批准源。

| 文件（仓库相对路径） | 函数/锚点 | 当前行为与拟改 | 验收 |
| --- | --- | --- | --- |
| experiments/clock_manual_20260919/page_context.py | 新文件，无既有行号 | 派生当前结构、真实来路、父页面分支、工作目标；帧来源与缺口显式化 | 树无持久副本，背景/缺口/循环/换帧及来路不混淆 |
| experiments/clock_manual_20260919/stepwise_flow.py | assemble_current_context:508；render_exploration_tree:343 | 原局部树只围绕当前目标；在正常请求最终任务选择后附加完整环境上下文 | 工作目标在背景时仍显示前景和父页面 |
| experiments/clock_manual_20260919/target_observation.py | refresh:77 | 当前重算控件位置；同步刷新树的帧适用状态 | 新图不沿用旧树的当前声明 |
| experiments/clock_manual_20260919/historical_inventory.py | request:12 | 同工作区或指定返回导航优先；加入有证据的父目标跨前景续接 | 首先清点/操作实际前景，旧历史任务保持 |
| tests/test_current_page_context.py | 新文件，无既有行号 | 可维护结构/来路与原生请求集成回归 | 明确行为断言，不镜像实现 |
| tests/test_current_region_priority.py | 既有当前工作优先测试 | 父目标续接及反例 | 无来路/错误目标/审核时不越级 |
| design/modules/stepwise_debug_loop.md、stepwise_region_identity.md | 新增当前合同说明 | 已实现与实际验收分开更新 | 仅报告真实验证范围 |
| design/CURRENT_FRAMEWORK.md、REGION_TRAVERSAL_ALIGNMENT.md、changelog/2026-10.md | 新增索引/对齐/验证记录 | 保留原研究目标，说明本批边界 | 不将树等同完整覆盖或导航成功 |

实现后另出v2，引用实际导出代码提交和重新核对的函数行号。不同版本不覆盖历史证据。
