# 当前模块文档索引

当前逐步开发进入[逐步模块目录](stepwise/README.md)，关联源码、prompt与测试；工作方式见[开发入口](../../DEVELOPMENT.md)。下表保留其他实现及研究模块的现行文档，不是逐步遍历器的替代入口。

修改框架代码时，先读 `design/CURRENT_FRAMEWORK.md`，再按下表读取相关当前文档。
`design/changelog/` 仅用于追溯历史，不属于默认阅读集合。

| 模块 | 当前文档 |
|---|---|
| 视觉遍历、Router、grounding、scroll、resume | `visual_traversal.md`（现行合同） |
| 视觉遍历逐文件职责 | `visual_traversal_file_map.md` |
| StateGraph、schema、attempt、completion | `state_graph.md` |
| 环境、provider、VLM、生命周期、fixture | `env_and_config.md` |
| capability synthesis | `capability_synthesizer.md` |
| Region 图指导实时采集（旧 M13 说明已归档） | `visual_collection.md` |
| graph quality | `graph_quality_agent.md` |
| Region-function 研究 | `region_function_collection_research.md` |
| 跨 App capability 组合 | `crossapp_composition_design.md` |
| 探索内核重新设计（新 fork，待实现） | `explore_kernel_design.md` |
| 自主遍历区块实例、局部状态与作用域覆盖（提案，待实现） | `autonomous_scope_state_coverage_design.md` |

其他 `design/modules/*.md` 多为专项设计、审查报告或待解决问题。只有任务直接涉及相应主题
时才需要读取。
精简前的视觉遍历长文在 `design/changelog/visual_traversal_history_through_2026-08-19.md`，
只用于追溯，不属于默认阅读集合。
