# 当前模块文档地图

[开发入口](../../DEVELOPMENT.md) · [短全局合同](../CURRENT_FRAMEWORK.md) · [完整细节](../CURRENT_FRAMEWORK_DETAILS.md)

当前逐步开发先从[三步主流程、异常与共享能力](stepwise/README.md)定位问题，再查[98 个 Python 文件的主要职责](stepwise/CODE_MAP.md)、对应 prompt 与[测试索引](../../tests/STEPWISE_INDEX.md)。源码目录仍平铺在 `experiments/clock_manual_20260919/`；职责分组不复制共享实现。

| 逐步职责 | 定位文档 | 详细合同 |
|---|---|---|
| 发现与准备任务 | [第一步](stepwise/01_discovery.md)、[任务规划](stepwise/tasks.md) | [增量发现](stepwise_discovery_completion.md) |
| 选择并执行动作 | [第二步](stepwise/02_action.md)、[调度](stepwise/routing.md)、[执行](stepwise/execution.md) | [步骤与运行](stepwise_debug_loop.md) |
| 观察结果并更新记录 | [第三步](stepwise/03_update.md)、[更新](stepwise/updates.md)、[功能知识](stepwise/knowledge.md) | [身份与登记](stepwise_region_identity.md)、[增量/功能](stepwise_discovery_completion.md) |
| 异常、纠错与恢复 | [修复连接](stepwise/repair.md) | [监督合同](stepwise_debug_loop.md) |
| 共用身份、上下文、快照与运行 | [身份](stepwise/identity.md)、[上下文](stepwise/context.md)、[运行](stepwise/runtime.md)、[完整 owner 表](stepwise/CODE_MAP.md) | [身份](stepwise_region_identity.md)、[步骤与运行](stepwise_debug_loop.md) |
| 逐步只读质量检查 | [stepwise_quality](stepwise_quality.md) | `tools/check_stepwise_quality.py`、`tools/stepwise_quality/`；独立输出 |

其他维护路径按自己的实现与合同阅读，不把旧合同套到逐步遍历。

| 模块/源码范围 | 当前文档 |
|---|---|
| `core/visual_traversal/`、guided/autonomous、Router/grounding/scroll/resume | [现行合同](visual_traversal.md)、[逐文件地图](visual_traversal_file_map.md) |
| `graph/state_graph.py`、schema/attempt/completion | [状态图](state_graph.md) |
| 环境/provider/VLM/lifecycle/fixture | [环境与配置](env_and_config.md) |
| `core/explore/` modular explore | [内核总地图](explore_kernel_design.md)，按其 `explore_kernel/` 模块地图下钻 |
| `core/evidence_explore/` 及独立证据/全景入口 | [证据内核](evidence_explore.md)、[全景](evidence_panorama.md)、[登记与回访](evidence_revisit.md) |
| capability synthesis/归一 | [合成](capability_synthesizer.md) |
| capability induction、最小 task synthesis | [归纳](capability_induction.md)；动作语义同读[状态图](state_graph.md) |
| Region 图指导实时采集、冻结逐步图适配、视觉 guard | [采集](visual_collection.md)、[Region 功能研究](region_function_collection_research.md) |
| graph quality 与证据标注 | [图质量](graph_quality_agent.md) |
| 跨 App capability 组合 | [组合设计](crossapp_composition_design.md) |
| 自主区块实例/局部状态/作用域覆盖提案 | [设计提案](autonomous_scope_state_coverage_design.md)，尚未实现 |
| 研究目标、Region/复用/条件任务、跨阶段缺口 | [研究目标](../RESEARCH_GOAL.md)、[Region 对齐](../REGION_TRAVERSAL_ALIGNMENT.md)、[全局待办](../GLOBAL_TODO.md) |

任务直接涉及时才读其他专项设计或审查报告。`design/changelog/` 与 `design/archive/` 保存历史；视觉旧长文在 `changelog/visual_traversal_history_through_2026-08-19.md`，不属于默认阅读集合。框架完整细节仍包含各实现适用的现行合同，不能因为它篇幅长或日期早就当作过时。
