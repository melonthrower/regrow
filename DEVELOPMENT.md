# regrow 开发入口

项目名称统一为 **regrow**。`GUI-ReWalk`、`gui_rewalk` 和带日期的目录名保留为历史路径或导入名；后续说明使用 regrow，定位源码仍按现有路径。

[每日开发记录](devlog/README.md)：按日期看当天完成、验证、未解决的问题和下一步；详细批次仍查月度日志。

[全部代码职责与位置](design/modules/stepwise/CODE_MAP.md)：按流程找入口，再按共享能力找唯一实现；改动前沿输入、校验、登记和下一步核对。

当前逐步遍历开发从[三步主流程、异常处理与共享能力](design/modules/stepwise/README.md)进入；先定位问题发生在哪一步，再沿数据连接找到代码、提示、测试与未完成事项。其他框架与采集见[全项目模块索引](design/modules/README.md)。

## 先确认改的是哪一份

- 当前checkout的源码根以 `git rev-parse --show-toplevel` 为准；先保存 `git status --porcelain`，保留已有修改。
- 逐步遍历源码：`experiments/clock_manual_20260919/`。目录名是历史名称，当前不搬迁。
- 冻结运行源码由该run的 `run_manifest.json` / `framework_source` 指定。修改checkout不自动更新正在运行的副本。
- 本地GUI-ReWalk工作区与私有regrow导出可能版本不同。不要在两个checkout交替实现同一修复；本机会话实际开发位置见工作区根的开发入口。
- 工作树里有未验收候选时，不因其文件存在就把功能标为已接受。检查模块、Git差异和最近交付结论。

## 按流程进入

| 要处理的问题 | 从这里开始 |
|---|---|
| 识别当前区块/控件、提出或补充任务 | [第一步：发现与准备任务](design/modules/stepwise/01_discovery.md) |
| 选择已有工作、定位目标、投递操作 | [第二步：选择并执行动作](design/modules/stepwise/02_action.md) |
| 核对动作结果、登记地图、结算与整理 | [第三步：观察结果并更新记录](design/modules/stepwise/03_update.md) |
| 纠错循环、应用异常、记录修订 | [纠错与恢复](design/modules/stepwise/repair.md) |
| 多步共用的地图、身份、存储与运行 | [共享能力及写入边界](design/modules/stepwise/README.md#shared) |

三步是阅读和开发的主线，不是每轮固定三次Luna调用。任务清点、异常复查和功能整理是按需正常子流程；实际调度入口仍为 `run_task_step._run_step`。职责模块保留原位，不按三步复制共享实现。

## 一次改动的最短流程

1. 读[全局合同](design/CURRENT_FRAMEWORK.md)及相关模块；先定位原实现。
2. 在本checkout沿下方连接表定位改动；修改字段时检查所有生产者、消费者及纠错步骤，不只改一段prompt。
3. 从[测试索引](tests/STEPWISE_INDEX.md)选聚焦检查。只改文档可做链接、差异和静态检查；不为导航整理调用Luna或GUI。
4. 行为改动按现行要求走完整原生请求验收；原答经正常校验和登记，检查实际身份、任务与图像。
5. 按改动范围更新模块及月度日志，并补记当天的 `devlog/YYYY-MM-DD.md`；陌生读者先独立阅读再对照意图。只提交本批已验证路径/片段，保留其他候选。
6. 私有源导出只同步本批已验证源码/文档；实验原件不入源仓库。

<a id="change-connections"></a>

## 每批改动的连接核对

把本次涉及的连接及结论写入既有月度变更记录，不另建一套长期清单。每项写明具体文件/函数，以及“已修改”“核对后无需修改”或“未验证”和依据；确实不涉及的连接可注明原因后省略。

| 连接 | 要核对什么 |
|---|---|
| 请求构造 → 实际发送正文 | 任务、地图、历史、截图是否按正常入口到达；不能只看prompt文件 |
| prompt与输出格式 → 原答校验 | 字段含义、可选值及省略规则是否一致 |
| 校验 → 登记保存 | 身份、任务归属、状态由哪个现有入口写入；原证据是否保留 |
| 登记 → 下一步读取 | 下一轮是否读到新快照，地图投影与任务上下文是否采用同一含义 |
| 普通流程 → 纠错/补观察 | 是否重用对应请求和登记规则，图片依据是否符合该阶段 |
| 中断 → 恢复 | 待登记动作、任务状态和原失败是否保留；是否可能重复投递 |
| 实现 → 验收证据 | 对应聚焦检查、原生模型验证和实际GUI分别验证到哪里 |

只核对本次受影响的连接及必要相邻合同，不默认运行全部测试。行为改动还须检查最终登记的身份、任务与图像，以及相关下一步请求；格式通过不等于语义通过。进度按“修改完成／验证完成／未验证或失败”报告，不能以改了多少文件计算完成率。

## 文件放置

| 内容 | 位置 |
|---|---|
| 当前职责、接口与状态 | `design/modules/`；逐步入口在 `stepwise/` |
| 全局入口、跨模块不变量 | `design/CURRENT_FRAMEWORK.md` |
| 每批改动与验证记录 | `design/changelog/YYYY-MM.md` |
| 每天做了什么、结果、未解决问题与下一步 | `devlog/YYYY-MM-DD.md`；入口为 `devlog/README.md` |
| 已取代方案、早期设计 | `design/archive/<主题或日期>/` |
| 维护测试 | `tests/`，保持原文件名与导入路径 |
| 临时脚本、pytest临时输出 | `artifacts/tmp_tests/<唯一名称>/` |
| 真实请求、回复、截图、账本 | 保持原run；新独立实验在 `artifacts/runs/<唯一名称>/` |
| 对外审阅包 | `to_astra/<唯一名称>/`，脱敏、不覆盖旧包 |

历史run可能仍在原实验目录；不要为统一外观移动或删除它们。继续GUI前读[现场交接](design/SERVER_HANDOFF.md)。研究问题与遍历/采集边界见[研究目标](design/RESEARCH_GOAL.md)和[Region对齐](design/REGION_TRAVERSAL_ALIGNMENT.md)。
