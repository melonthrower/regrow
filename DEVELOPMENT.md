# regrow 当前开发入口

当前逐步框架唯一维护源码是 [src/regrow](src/regrow)。先读 [当前框架](design/CURRENT_FRAMEWORK.md)，再按 [识别、遍历、记录](design/modules/stepwise/README.md) 找代码。

查当前逐步框架时，先在 `src/regrow/`、`tools/`、`tests/` 内搜索。根目录 `.ignore` 排除旧实验、工作树、运行证据和审阅副本；不要用 `rg --no-ignore` 或递归扫描整个仓库来定位当前实现。只有核对指定历史运行时才显式打开其旧路径。`gui_rewalk/` 是独立研究/采集管线，不能当作 regrow 的另一份实现，也不能按废弃副本删除。

- 识别：`src/regrow/recognition/`，当前截图与已有身份 → 对象观察。
- 遍历：`src/regrow/traversal/`，任务、下一步选择、结果核对、恢复与续接。
- 记录：`src/regrow/records/`，对象/任务/动作知识、事务发布、相关历史查询。
- 提示：[统一组成入口](src/regrow/prompts/流程/调用组成.json)；正文、规则和输出呈现均在 `src/regrow/prompts/`。
- 平台与模型：`src/regrow/runtime/`；启动和展示工具在 `src/regrow/tools/`，不决定探索策略。

当前机器验证使用 `/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python`，须先激活 `guiwalk-android` 环境；系统默认没有 `python` 命令。环境激活后正常入口为 `python src step ...`、`python src session ...`；桌面批次使用 `python tools/run_stepwise.py ...`。`python src step --help` 可查看参数。冻结源码保留同一目录结构，直接以 `python <冻结目录> session ...` 执行，不借用宿主的另一个源码版本。

旧 `experiments/clock_manual_20260919/` 不再是开发入口。因原运行清单仍引用它，源码原样保留供历史核对；`.ignore` 将其排除出默认搜索。不要在那里继续修复，也不要把历史回放当作当前运行路径。

先前三部分职责重组的限定验证、旧候选边界和未完成项见 [历史实施记录](design/THREE_PART_FRAMEWORK.md)；本次根目录迁移见 [目录迁移记录](design/ROOT_MIGRATION_20261025.md)。迁移前已有工作不是正确性基准。最新代码未因目录整理成为全框架已验收版本。

长期 Prompt 工作台继续复用 `tools/prompt_review_editor.py`；数据目录、用户笔记与历史原件不变，详见 [工作台说明](tools/prompt_review_editor/README.md)。其他 GUI-ReWalk 研究管线和独立采集原本就在本根目录，保持各自模块入口。

修改代码仍须保留基线、更新对应当前模块与月志、按影响做聚焦验证和陌生读者审阅；有 GUI/Luna 验证时区分保存帧和真实执行，不默认运行全量门禁。

## 2026-10-25 根目录迁移

当前唯一开发目录是 `/data/shenghonghui/projects/GUI-ReWalk`，源码直接位于本目录 `src/regrow/`。原 `artifacts/tmp_tests/function_state_20261025_01/implementation/` 保留为迁移来源，不再修改；其他历史 checkout 和运行冻结源也不是当前入口。源码按原内容迁入，不改变既有候选的验收状态。迁移证据见 `artifacts/runs/root_migration_20261025_01/`。

## Git源码基线（2026-10-29）
当前`src/`及运行需要的Prompt/JSON/页面资源纳入Git；根tools只新增启动、Prompt工作台、运行看板及其依赖资源。研究测试和可选本地工具本批不新增跟踪，文件仍保留；既有已跟踪文件不删除、不取消跟踪。运行产物、截图、凭据与缓存保持本地。此基线是当前研究源码快照，不表示全框架已验收。历史experiments及旧工作树不再作为活动开发入口。
