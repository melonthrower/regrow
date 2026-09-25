# capability_synthesizer.py — 可选能力归一与旧图入口

路径：

- `gui_rewalk/src/core/visual_traversal/capability_discovery.py`
- `gui_rewalk/src/core/scenario/capability_synthesizer.py`

能力发现的现役主入口已经进入遍历循环。每次视觉观察完成 grounding 后，`capability_discovery.py` 立即从可交互元素生成 portable `discovered` 能力；`StateGraph.register_capability_candidates()` 将其合并到当前 Page/Variant 和全局能力目录。真实动作、目标节点注册与 `landing_verified is True` 只补充 action edge、target page/variant 和入口执行 provenance；观察期 capability 仍为 `discovered`。业务 effect 与业务 `verified` 只能由显式 Phase 1 effect observation 的离线 induction 建立。

```text
grounded visual observation
  → page_id + variant_id + observed facts
  → portable discovered capabilities
  → real action + verified landing
  → action_edge/target/entry-execution provenance (capability remains discovered)
  → optional Phase 1 effect observations → independent capability graph
```

`run_capability_synth.py` 仍保留，但已不是遍历完成后的必经阶段。它用于旧图补录、单节点截图分析和可选的语义归一/参数化：

```text
screenshot.png + elements.json + state_meta.json
  → optional VLM normalization
  → page_capabilities.json
```

离线 synthesizer 不启动 VM、不修改遍历拓扑，也不能仅凭单张截图把能力标为 `verified`。新生成能力默认 `availability_status=discovered`；旧 artifact 缺少状态时按 `unknown` 读取。显式持久化的较新状态可以保留，但不能由截图推断升级。

## 在线 portable capability 契约

观察期能力至少包含：

- `schema_version/capability_id/page_id/name/semantic_key`；
- `status=discovered` 与 `availability_status`；
- `available_when.variant_ids/observed_facts`、`evidence_variants/entry_variants`；
- `source_elements`：执行节点、variant、元素语义、region/group；
- `input_slots/requires/risk_level`；
- `execution_recipe`：仅动作类型、语义 selector 与运行时参数槽；
- `effects/success_predicate/observables`；
- 验证后补充的 `action_edge_ids/target_pages/target_variants`。

当 verified action 的实际落地是同一 Page 的新 Variant，且 Region 映射证明它引入
了新区块时，`region_transition` 只保存动作与 Region 的审计关联。它不会自动生成
`kind=region_introduction` effect、`result_binding` 或 `type=region_ref` observable；
显式 Phase 1 effect observation 与离线 induction 可引用已保存的正式 Region ref。

稳定 `capability_id` 由 `page_id + semantic_key` 生成。同一页面的多个变体观察到同一能力时合并为一条 page-level 能力，并累积 `available_when.variant_ids`；例如 `open_alarm_detail` 可以只在 `has_alarm` 变体可用。具体闹钟时间、联系人名等内容数据不会被写成页面身份或持久参数值，运行时从可见 group/参数槽重新绑定。

resume/load 时，Variant 可用性以 capability 的 grounded
`source_elements[].state_id` 为事实来源：每个来源引用改写为该 State 当前持久
`variant_id`，`entry_variants/evidence_variants/available_when.variant_ids` 重建为这些来源
实际覆盖的 Variant 集合。能力只在一个 Variant 出现就只标记该 Variant；多个 Variant 都有
来源证据才同时标记，旧的悬空 Variant 引用不保留。

看到控件不等于验证业务效果：

- `discovered`：当前视觉观察中存在可交互入口；
- `verified`：只由独立 capability graph 中、具有显式业务 effect observation 的离线 induction 建立；真实 landing 本身不足以晋升；
- `blocked/conditional/unknown`：权限、环境或证据不足，不能冒充 verified。

控件类型到 portable recipe 的当前映射为：

- 文本输入框生成语义 selector 的 `TYPE`，文本值写成运行时 `text` 槽（`{{text}}`），不得固化采集环境中的历史内容；
- `dropdown/combobox` 生成语义 selector 的 `CLICK`，同时声明必需的运行时 `option` 槽；候选选项由执行环境 `discover_at_runtime`，不得固化历史选项值；
- 普通按钮生成语义 selector 的 `CLICK`；
- 数值 `slider/range` 不再暴露模糊连续值，而是离散成自然语言参数 `最小/一半/最大`。portable recipe 使用 `SET_SLIDER` + 语义 selector + `level` 参数槽；执行时必须从实时画面重新识别整条滑轨并按相对位置落点，禁止保存历史坐标。若实时 bbox 小到更像滑块手柄而非滑轨，则失败关闭。自由排序/拖放类 `drag/draggable/drag handle` 仍保持 `execution_recipe=[]`、`execution_support=unsupported`。

所有 recipe 禁止持久化坐标、bbox、DOM/A11y selector 或截图文件名，只保存可重新 grounding 的视觉语义 selector。截图和元素几何仍可留在本次 node artifact 供感知、人工复核和 GraphQuality 使用。遍历中的视觉观察只产生 `discovered`；匹配入口的真实动作、明确目标与 `landing_verified is True` 只补充动作和入口执行证据，不晋升为业务 `verified`。

## 离线 Capability 契约

旧字段继续兼容：

- `name/region/explain`
- `param.{type,current,values,source,slot}`
- `elements` 或参数化 `element_map`

当前执行字段：

- `app_id/capability_id/entry_surfaces`
- `input_slots/requires/effects/success_predicate/observables`
- `execution_recipe/setup_recipe/recovery/cleanup`
- `availability_status/risk_level/action_steps`

自主遍历的最终证据包按 `entry_id + source State + owner Region` 对接正式 Entry occurrence
和真实动作。若一个 Entry 依靠 Region 局部状态等价性在另一 Page State 上通过独立行动复核并真实执行，
执行时会把该 Page State 补入 Entry 的 `source_state_ids`；编译器不需要用动作描述文本猜测它是否为同一入口。

`Capability.from_raw()` 继续读取历史 `action_recipe/actions`，但缺失执行字段时使用空列表或未知状态，不把描述性旧能力凭空升级为已验证能力。`bind_context(app_id,node_id,page_name)` 只补稳定 provenance。`capability_instruction_gen.py` 和联邦 catalog 继续传递上述字段给 M13；M13 的 prerequisite runtime 保留，和遍历期能力发现是不同阶段。

正式 instruction 生成接受已发现功能，不要求先执行。显式 `discovered`、`executable`
和已验证状态均可作为候选，`unknown` 仍不进入。缺少生命周期字段的历史 artifact
沿用既有读取行为；有状态的记录保留原状态，不能因生成指令或进入采集而晋升。

## Current task-eligibility boundary

`capability_instruction_gen.py` now treats an explicit `verification_level` as
authoritative: `discovered`, `executable`, `effect_verified`, and `composable`
enter task candidates without prior execution requirements. Unknown statuses are excluded. Historical page sidecars with neither `status` nor
`availability_status` remain readable only by that legacy generator path. If
any model-cited capability ref is empty or unresolved, the whole candidate is
rejected instead of emitting natural-language work absent from its ref list.

New evidence-backed task production does not project the independent capability
graph back into `page_capabilities.json`. It uses
`capability_task_synthesis.py` directly, and M13 independently rehydrates the
selected ref from the same capability graph. This keeps screenshot-derived
sidecars and effect-verified capability facts as separate authorities.

## 2026-07-11 修改与验证

- 历史旧预期（已由 2026-08 Phase 1 测试替代）：观察即 `discovered`，真实动作与严格 landing 曾被视为 `verified`。当前合同中 landing 只记录入口执行与落点，业务 verified 需要显式 effect observation 的离线 induction。
- 能力与 recipe 改为便携语义 selector；截图路径和历史坐标只作为本地 sidecar 证据。
- 离线 synthesizer 降为可选归一/旧图入口，单截图默认 `discovered`，旧无状态 artifact 按 `unknown`。
- 离线运行 `python -B tools/test_online_capability_discovery.py`、`python -B tools/test_capability_atom_contract.py`、`python -m pytest -q tools/test_federated_capability_catalog.py tools/test_visual_collection_executor.py --basetemp _scratch/pytest_capability_contracts`，均通过；M13 catalog/executor 合并批次为 18 passed。
- 未调用真实 VLM，也未对 Clock/Alarm 等首批应用重新批量归一或 live 验收。

## 2026-07-12 portable recipe 契约验证

- 明确文本框 `TYPE` + runtime `text`、下拉/组合框 `CLICK` + runtime `option`、普通按钮语义 `CLICK` 的映射。
- 数值滑条仅生成 `最小/一半/最大` 三个固定锚点，不生成任意百分比或历史坐标；自由拖放仍显式 unsupported。
- 离线运行 `python -m py_compile gui_rewalk/src/core/visual_traversal/capability_discovery.py gui_rewalk/src/core/scenario/live_visual_collection.py gui_rewalk/src/core/scenario/capability_synthesizer.py tools/test_online_capability_discovery.py tools/test_live_visual_collection.py`、`python -B tools/test_online_capability_discovery.py`、`python -B tools/test_live_visual_collection.py`：均通过。该结果只验证离线能力契约和实时几何换算逻辑，尚未在 VM 中执行真实滑条并做截图落地验收。
- 历史验证命令（其“状态晋升”旧预期已由 2026-08 Phase 1 测试替代）：`python -B tools/test_online_capability_discovery.py` 曾 PASS（`PASS online capability discovery: discovered, portable, variant-aware`）。该结果只验证当时离线数据契约，未进行真实 GUI、VLM 或 live landing 验收。

## 2026-07-10 历史修改

删除 `TaskAtomExtractor` 依赖和旧 Scenario 转换桥；元素表只从视觉 `elements.json` 建立。

## Current 2026-08 contract: landing is not a business effect

In the current contract, `landing_verified` proves only Entry execution and identified landing.
It can supply action-edge and `entry_execution_evidence` provenance while the
observation-time capability remains `discovered`; it must not synthesize
`effects`, `success_predicate`, or a business-effect verification. Those facts
are Phase-1 offline induction input only when explicit append-only effect
observations exist. This screenshot-oriented synthesizer remains separate from
`capability_induction.py`; Phase 1 does not invoke a live VLM or M13 and does not
change Region identity.
