# 跨应用能力组合（当前实现）

## 结论

跨应用层现在是**联邦能力目录 + 独立应用图执行**，不是状态图合并：

```text
app A node_artifacts/page_capabilities.json ─┐
                                             ├→ FederatedCapabilityCatalog
app B node_artifacts/page_capabilities.json ─┘      │
                                                     ├→ app-qualified Instruction
app A graph.json ─→ adapter A ──────────────────────┤
app B graph.json ─→ adapter B ──────────────────────┤
                                                     └→ VisualCollectionExecutor
                                                          ├→ app A 内最短路
                                                          ├→ 显式 app switch
                                                          └→ app B 内最短路
```

旧文档曾描述已退役的 `ScenarioExecutor/GraphSupplement/command_planner/TaskComposer`，这些模块不再属于当前框架。现役实现是 `federated_capability_catalog.py`、`visual_collection_executor.py`、`live_visual_collection.py` 与 `run_visual_collection.py`。

## FederatedCapabilityCatalog

输入是 `app_id → node_artifacts directory`。Catalog 分别读取每个目录下的 `*/page_capabilities.json`，但保留原 node namespace 和 source path。

每个 `FederatedCapabilityAtom` 包含：

- `app_id/node_id/target_node/page_name/page_id`
- `capability_id/name/semantic_key/region`
- `param/elements/element_map`
- `requires/effects/success_predicate/observables`
- `execution_recipe/setup_recipe/recovery/cleanup`
- `availability_status/risk_level/action_steps`
- `source_path/source_paths`
- `evidence_variants/entry_variants/source_elements`
- `action_edge_ids/target_pages/target_variants/available_when`

身份有两种稳定拼法：

- `namespaced_id = app_id::capability_id`
- `qualified_name = app_id::page_name::name`

裸 `capability_id` 若跨 app/页面有多个匹配会 fail-closed 为 ambiguous；调用方必须补 `app_id` 或完整 qualified name。

在线遍历会为同一 Page 的每个 `Page@Variant` 写一份 sidecar，因此同一
`app_id::capability_id` 可以在空列表/有数据等多个节点目录中重复出现。Catalog 只在两份记录的
稳定 `page_id` 与 `semantic_key` 同时一致时确定性合并为一个 atom：variant、source element、
action edge 与 target evidence 做排序去重并集，任一记录为 `verified` 时合并结果不降级。
缺少稳定 `page_id`、跨 page 碰撞或 semantic identity 冲突仍 fail-closed；Catalog 不据重复 id
猜测它们是同一个能力。variant-specific 前置保存在
`available_when.requires_by_variant`；只有所有 variant 的 requirement 集合完全相同时，才继续填写
兼容字段 `requires`，blocked 与 available variant 并存时 `requires=[]`，避免把局部 gate 误报成
整个 page capability 的全局前置。

## 组合方式

`compose_instruction(atom_refs, ...)` 按调用方给定顺序确定性组合显式 atoms。`compose_with_vlm(goal, ...)` 可让注入的 VLM 从给定 catalog candidates 中选择/排序，但返回 ref 必须重新在 catalog 中严格解析，模型不能发明 atom 或越过候选集。

输出仍是现役 `Instruction`：

- 每个 `CapabilityRef` 显式携带 `app_id`、图节点、能力 identity、grounding、params、requires/effects/verifier contract 与 `depends_on`；
- 顶层 `apps_involved` 按首次出现顺序去重；
- 多应用自动标 `type="cross_app"`；
- `fixed_order=true`，保证功能函数组合的语义顺序。

Catalog 是语义 union，不创建跨 app state edge，不修改源 artifact，也不负责启动应用。

## M13 如何执行跨应用指令

`VisualCollectionExecutor` 为每个 app 接受一张独立 graph 和一个 adapter。执行时：

1. 在依赖允许的 refs 中，用当前 app、当前节点、图内 shortest path 与 capability action cost 选成本最低者；
2. 若 ref 属于另一 app，调用对应 adapter.activate/switcher，记一个 `action_steps=1` 的 `app_switch` step；
3. 在目标 app 自己的图内按 edge `action_steps` 求最短路；
4. 到 ref entry node 后实时 ground capability 并执行；
5. VLM 验证该 ref，可见成功后才 commit；
6. 所有 refs 完成后再做一次整指令 final verification。

跨 app provenance 明确写 `source_app_id/target_app_id/graphs_merged=false`。这是一条 episode 逻辑边界，不是添加到任一 `graph.json` 的语义边。

## 前置条件与跨应用

每个 app graph 独立规划不妨碍 capability 依赖。ref 的 `depends_on` 或 requires-to-ref 关系形成跨 app 依赖顺序；resource/state/authorization/login 则交 `VisualPrerequisiteAgent` 在该 ref 的 app adapter 上处理。setup 改变页面后，执行器从真实 landing 重新规划。

当前用户目标是“由多个应用的功能函数组合得到跨应用指令，并在采集时分别按各应用图规划”。这一主链已经实现。以下能力**没有**实现，文档不得混淆：

- 通用 `observable(A) → 动态提取值 → 注入 B.input_slot` 数据流；
- 合并 A/B 状态节点或建立持久化跨 app 状态边；
- 跨应用系统级特殊 verifier。当前只有各 ref 与整条指令的普通截图 VLM 完成判定。

`VisualCollectionExecutor` 内的 blackboard 当前用于前置 resolver bindings/world context，不是任意跨应用数据流引擎。

## CLI 装配与校验

`run_visual_collection.py` 要求重复传入匹配的：

```text
--graph APP_ID=GRAPH_JSON
--node-dir APP_ID=NODE_DIR
```

Instruction 的每个 app/ref/node 会在执行前 hydrate/校验。`--validate-only` 覆盖多图、多目录、catalog 与 ref provenance，不启动 VM/VLM。live 模式为每个 app resume 一套 `VisualTraversalEngine` identity runtime，但共享同一个 desktop/Android environment、VLM agent 和 prerequisite ownership runtime；app activation 保留应用数据，不用 reset 清掉刚创建的前置资源。

## 2026-07-12 离线验证

```powershell
python -B tools/test_run_visual_collection_cli.py
python -B tools/test_capability_atom_contract.py
python -m pytest -q tools/test_federated_capability_catalog.py tools/test_visual_collection_executor.py --basetemp _scratch/pytest_crossapp
```

全部通过，pytest catalog/executor 合并批次为 22 passed。验证覆盖 app-qualified identity、同一 Page 的 empty/has-data variant sidecar 合并、blocked/available variant requirement 隔离、page/semantic 冲突拒绝、显式/VLM composition、独立图最短路、app switch provenance、依赖与 CLI static validation。尚未跑真实跨应用 VM/Android episode，不能据此声称首批应用 live 已完成。
