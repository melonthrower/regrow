# ReGROW

> **2026-11-07 遍历调用与字段收束。** 两条完整真实保存帧正常登记，0新GUI；长遍历尚未验证。见[快照状态](SNAPSHOT_STATUS.md)。

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

[设计思路入口：字段目的、各环节、源码定位与待实施方案](design/DESIGN_INTENT.md)。

[最新遍历讨论：六类问题的设计/接线边界、真实截图与调用流程](issue_cases/20261104-traversal-design-and-wiring/README.md)。来自独立8应用实验的精选证据；不表示已修复，实验冻结源码与根源码版本分别说明。

## 此前提交的保存帧工作台修复（364bbe8）

底层保存帧重建器会在复制运行或调用模型前拒绝不能直接重建的纠错/目标核对记录，并提示选择对应原业务调用；六类原有业务分支保持。拒绝路径和正常任务提出预览以0模型/0GUI检查，未运行全框架门禁。

此前 364bbe8 提交只包含这一工作台修复及使用说明，未包含当时的遍历/Prompt 候选。当前快照另含后续本地候选，状态以顶部快照说明为准。

[任务合同与动作后完整Action接续](design/proposals/action-continuation-20261106/README.md)。
