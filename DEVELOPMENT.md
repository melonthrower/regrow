# regrow 当前开发入口

当前逐步框架唯一维护源码是 [src/regrow](src/regrow)。先读 [当前框架](design/CURRENT_FRAMEWORK.md)，再按 [识别、遍历、记录](design/modules/stepwise/README.md) 找代码。

- 识别：`src/regrow/recognition/`，当前截图与已有身份 → 对象观察。
- 遍历：`src/regrow/traversal/`，任务、下一步选择、结果核对、恢复与续接。
- 记录：`src/regrow/records/`，对象/任务/动作知识、事务发布、相关历史查询。
- 提示：[统一组成入口](src/regrow/prompts/流程/调用组成.json)；正文、规则和输出呈现均在 `src/regrow/prompts/`。
- 平台与模型：`src/regrow/runtime/`；启动和展示工具在 `src/regrow/tools/`，不决定探索策略。

正常命令入口为 `python src step ...`、`python src session ...`；桌面批次继续使用 `python tools/run_stepwise.py ...`。`python src step --help` 可查看参数。冻结源码保留同一目录结构，直接以 `python <冻结目录> session ...` 执行，不借用宿主的另一个源码版本。

旧 `experiments/clock_manual_20260919/` 不再是开发入口。因原运行清单仍引用它，源码原样保留供历史核对；`.ignore` 将其排除出默认搜索。不要在那里继续修复，也不要把历史回放当作当前运行路径。

当前迁移的限定验证、旧候选边界和未完成项见 [实施记录](design/THREE_PART_FRAMEWORK.md)。迁移前已有工作不是正确性基准。最新代码未因目录整理成为全框架已验收版本。

长期 Prompt 工作台继续复用 `tools/prompt_review_editor.py`；数据目录、用户笔记与历史原件不变，详见 [工作台说明](tools/prompt_review_editor/README.md)。其他 GUI-ReWalk 研究管线和独立采集仍按各自模块维护，本次未迁移它们。

修改代码仍须保留基线、更新对应当前模块与月志、按影响做聚焦验证和陌生读者审阅；有 GUI/Luna 验证时区分保存帧和真实执行，不默认运行全量门禁。
