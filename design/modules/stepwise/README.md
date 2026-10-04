# 逐步遍历器：按模块开发

[开发总入口](../../../DEVELOPMENT.md) · [全项目模块](../README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

这里组织当前逐步遍历器的开发导航，代码仍在 `experiments/clock_manual_20260919/`，不因目录带Clock就视为应用专用实现。本次没有搬动源码、prompt、schema或测试。

| 模块 | 负责什么 | 主要代码 |
|---|---|---|
| [观察与身份](identity.md) | 当前图中的区块、控件与历史身份如何对应；前景、模板与控件组匹配。 | `discovery_step.py` |
| [地图与上下文](context.md) | 把已有图、动作和任务记录组织成各步骤输入；不创建执行事实。 | `page_context.py` |
| [任务规划与登记](tasks.md) | 判断值得探索的新问题，维护任务归属、补充和清点状态。 | `region_tasks.py` |
| [调度与前置条件](routing.md) | 选择已有工作、处理前置条件、暂挂与已知导航。 | `task_routing.py` |
| [动作选择与执行](execution.md) | 选择动作、关联控件、检查投递条件并保留实际回执。 | `stepwise_flow.py` |
| [结果更新与登记](updates.md) | 更新图、任务结果与观察来源，发布完整快照。 | `update_step.py` |
| [纠错与异常恢复](repair.md) | 处理失败提案、记录修订、暂挂和应用异常。 | `step_repair.py` |
| [功能知识与完成](knowledge.md) | 整理区块功能，区分清点、任务和图的完成状态。 | `region_functions.py` |
| [运行、环境与进度](runtime.md) | 选择源码与运行，维护传输、预算、冻结副本和进度。 | `launch_traversal.py` |

同一Python文件可能承载紧密相连的多个职责（例如region_tasks的规划和调度）；模块页列出主归属与接口，不据此拆文件或制造第二套实现。新增源码补对应模块页，新增测试补测试索引。

当前代码事实与详细合同按模块页链接查阅；旧PIPELINE_DESIGN已归档，仅用于历史追溯。代码存在、离线通过、保存帧模型验证、真实GUI验证分别记录。每次改动只读总索引和相关模块，不遍历全部历史文档。
