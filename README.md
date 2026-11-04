# ReGROW 当前开发源码（三阶段）

本分支同步 2026-11-04 的当前开发目录，包含遍历、指令生成、轨迹采集及其共享依赖。它是研究开发快照，不是已验收发布；同步不会使未确认 Prompt 草稿获得批准，也不代表应用遍历或完整业务采集已通过。直接更新现有默认分支 `codex/regrow-initial`，旧有限验证版本保留在 Git 提交历史中。

|阶段|入口|职责|
|---|---|---|
|遍历|`src/__main__.py`，`python src step --help`|发现与复认区块/控件、探索任务、执行及结果登记|
|指令生成|`gui_rewalk/run_capability_task_synthesis.py`|只读已冻结图中的功能、控件知识、参数及条件，生成指令|
|轨迹采集|`gui_rewalk/run_visual_collection.py`|读取指令及其冻结图，准备必要素材，依据实时界面执行并记录轨迹|

生成、采集复用 `gui_rewalk/src/core/scenario/collection_graph.py` 读取图；该读取器又依赖本仓库 `src/regrow/records`。因此应克隆整个仓库，不能仅复制 `gui_rewalk/`。生成材料与采集记忆的选择职责分开，必要图片素材准备位于 `collection_seed.py`。这些入口及默认行为以当前源码为准。

```bash
python src step --help
python gui_rewalk/run_capability_task_synthesis.py --help
python gui_rewalk/run_visual_collection.py --help
```

## 状态与边界

- 当前开发目录含尚未批准的 Prompt 草稿，具体路径见 [版本说明](SOURCE_VERSION.json)。本分支原样保存它们供审阅；实际运行仍使用各自冻结源码，没有将本分支部署到活动运行。
- 取消 Region 父子关系仍是设计候选，未实施；不要把前面的讨论当成代码现状。动作点位核对与共享控件纠错另有已知问题。
- 当前图读取、知识生成材料和素材准备已有局部验证，完整新图实机采集、任意任务可执行性及全框架质量均未由本同步认证。
- 不含 API Key、其他凭据、私有端点、运行图/截图/账本、虚拟机或外部依赖副本。少量旧调试工具的私有端点沿既有导出规则保留占位值，真实配置仍仅在本地。
- 本次准确版本以本分支 Git commit 和 `SOURCE_VERSION.json` 为准。根目录 `SOURCE_MANIFEST.json`、`SHA256SUMS` 为历史导出文件，不代表此次快照。

[开发导航](DEVELOPMENT.md) · [当前框架](design/CURRENT_FRAMEWORK.md) · [生成与采集现状](design/modules/visual_collection.md) · [本次同步说明](reviews/source-sync-20261104/SYNC.md)

本仓库此前的根说明保存在 [原说明](reviews/source-sync-20261104/PREVIOUS_README.md)。模型、Android/OSWorld 与系统依赖须自行配置，凭据使用本地环境或受忽略的配置文件提供。
