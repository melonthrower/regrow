# 开发入口

当前逐步遍历开发从[九个模块](design/modules/stepwise/README.md)进入；按模块找到代码、提示、测试与未完成事项。其他框架与采集见[全项目模块索引](design/modules/README.md)。

## 先确认改的是哪一份

- 当前checkout的源码根以 `git rev-parse --show-toplevel` 为准；先保存 `git status --porcelain`，保留已有修改。
- 逐步遍历源码：`experiments/clock_manual_20260919/`。目录名是历史名称，当前不搬迁。
- 冻结运行源码由该run的 `run_manifest.json` / `framework_source` 指定。修改checkout不自动更新正在运行的副本。
- 本地GUI-ReWalk工作区与私有regrow导出可能版本不同。不要在两个checkout交替实现同一修复；本机会话实际开发位置见工作区根的开发入口。
- 工作树里有未验收候选时，不因其文件存在就把功能标为已接受。检查模块、Git差异和最近交付结论。

## 按问题找模块

| 问题 | 从这里开始 |
|---|---|
| 控件误识别、重复图标、前景范围 | [观察与身份](design/modules/stepwise/identity.md) |
| 地图、历史、实际prompt重复 | [地图与上下文](design/modules/stepwise/context.md) |
| 重复任务、归属、清点输出 | [任务规划与登记](design/modules/stepwise/tasks.md) |
| 不执行、暂停后恢复、导航 | [调度与前置条件](design/modules/stepwise/routing.md) |
| 点错、输入没发出、动作绑定 | [动作选择与执行](design/modules/stepwise/execution.md) |
| 执行后登记错、任务误完成 | [更新与登记](design/modules/stepwise/updates.md) |
| 纠错循环、应用异常、记录修订 | [纠错与恢复](design/modules/stepwise/repair.md) |
| 功能归纳、图完成判定 | [知识与完成](design/modules/stepwise/knowledge.md) |
| 启动、模型调用、源码版本、进度 | [运行与环境](design/modules/stepwise/runtime.md) |

## 一次改动的最短流程

1. 读[全局合同](design/CURRENT_FRAMEWORK.md)及相关模块；先定位原实现。
2. 在本checkout修改对应源码和prompt/schema；修改字段时检查所有生产者、消费者及纠错步骤。
3. 从[测试索引](tests/STEPWISE_INDEX.md)选聚焦检查。只改文档可做链接、差异和静态检查；不为导航整理调用Luna或GUI。
4. 行为改动按现行要求走完整原生请求验收；原答经正常校验和登记，检查实际身份、任务与图像。
5. 更新模块及月度日志；陌生读者先独立阅读再对照意图。只提交本批已验证路径/片段，保留其他候选。
6. 私有源导出只同步本批已验证源码/文档；实验原件不入源仓库。

## 文件放置

| 内容 | 位置 |
|---|---|
| 当前职责、接口与状态 | `design/modules/`；逐步入口在 `stepwise/` |
| 全局入口、跨模块不变量 | `design/CURRENT_FRAMEWORK.md` |
| 每批改动与验证记录 | `design/changelog/YYYY-MM.md` |
| 已取代方案、早期设计 | `design/archive/<主题或日期>/` |
| 维护测试 | `tests/`，保持原文件名与导入路径 |
| 临时脚本、pytest临时输出 | `artifacts/tmp_tests/<唯一名称>/` |
| 真实请求、回复、截图、账本 | 保持原run；新独立实验在 `artifacts/runs/<唯一名称>/` |
| 对外审阅包 | `to_astra/<唯一名称>/`，脱敏、不覆盖旧包 |

历史run可能仍在原实验目录；不要为统一外观移动或删除它们。继续GUI前读[现场交接](design/SERVER_HANDOFF.md)。研究问题与遍历/采集边界见[研究目标](design/RESEARCH_GOAL.md)和[Region对齐](design/REGION_TRAVERSAL_ALIGNMENT.md)。
