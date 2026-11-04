# ReGROW

用于探索应用功能、生成指令并采集 GUI 轨迹的研究框架。当前为开发源码，部分 Prompt 和行为尚未验收；见 [已知问题](KNOWN_ISSUES.md)。

|阶段|入口|
|---|---|
|遍历|`src/regrow/`；`python src step --help`|
|指令生成|`python gui_rewalk/run_capability_task_synthesis.py --help`|
|轨迹采集|`python gui_rewalk/run_visual_collection.py --help`|

生成与采集依赖本仓库的 `src/regrow/records` 读取冻结图，应克隆完整仓库。必要提示、schema、页面与素材生成代码随源码保留。模型凭据、OSWorld/Android 环境需自行配置；不要把 API Key 写入源码。

公开仓库保留源码、运行资源和使用/问题说明。测试、验证日志、审阅报告、日常工作记录及旧导出包保留在本地开发目录，不随源码同步上传；过去提交仍可从 Git 历史查看。

[开发入口](DEVELOPMENT.md) · [本地部署](DEPLOY_LOCAL.md) · [当前问题](KNOWN_ISSUES.md) · [源码状态](SOURCE_VERSION.json)

[区块与动作问题案例：截图、应用树、逐次调用](issue_cases/20261104-regions-and-actions/README.md)。仅公开用户指定的相关证据，验证原件仍在本地维护。
