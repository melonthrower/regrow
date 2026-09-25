# GraphQualityAgent — 只读 Page/Variant 能力图质检

路径：

- `gui_rewalk/src/core/graph/graph_quality_agent.py`
- `gui_rewalk/src/core/graph/graph_quality_annotations.py`
- `gui_rewalk/run_graph_quality.py`

## 目标与边界

质检器回答“哪个 Page/Variant、ActionEdge、attempt 或 capability 证据不可信，哪个可见功能未完成或被阻塞”，但不修改 `graph.json`、节点截图、能力目录或覆盖账本。默认 rules-only，不导入/初始化 VLM transport；`--use-vlm` 才增加截图语义裁判。

它不能从已采页面证明应用中所有“从未出现过”的功能不存在。覆盖状态使用 `verified/conditional/blocked/unknown/unsupported`；`unsupported` 只有在有具体可见缺失证据时才能成立，否则必须是 `unknown`。截图是本次观察和质检的 sidecar，不是动作边或 portable capability 的执行依赖。

## schema v3 规则检查

- Page/Variant：每个执行节点必须有 `page_id/variant_id`，且 `page_id` 能在 `pages` 目录中解析；检查稳定页面下的变体归属、selected mode 冲突、页面身份过分裂和语义页面过合并。
- ActionEdge/attempt：每条语义边必须有稳定 id 和至少一次 attempt；同 source/target 的不同动作不能互相覆盖；attempt 索引必须连续且唯一，target、outcome、committed 与 landing 状态必须一致。
- 路由：NetworkX 拓扑引用的 `action_edge_ids` 必须存在；只有 `routing_verified=true` 且含 committed、`landing_verified=True` 的成功 attempt 才可进入路由视图；no-effect、blocked、off-app、crash 与未知 landing 不得成为可执行路径。
- capability：`discovered` 可以只有当前可见入口；`verified` 必须回指至少一个 routing-verified ActionEdge，否则报 `verified_capability_without_verified_action`；检查 `available_when`、variant evidence、source element 与 target page/variant 引用。
- 持久化：schema v3 不得再包含第二份顶层 `transition_events`；发现时报告重复账本。ActionEdge/capability 的去 geometry 由写入层规范化，本地 node sidecar 中的 bbox 仍是合法质检证据。
- 覆盖账本：navigation control 的 visited 状态必须有 edge/attempt/terminal outcome 对应；Explorer 的 `done` 不能把未执行控件静默标成 visited。
- 证据：解析节点 sidecar 截图、尺寸/hash 和元素证据；缺图影响人工/VLM 复核，但不等于 portable action/capability 不可加载。

旧 schema v1/v2 仍按兼容规则读取。缺少 ActionEdge/attempt 或 Page/Variant 目录时会报告历史不完整；旧图名称中出现 permission/crash 词但没有结构化字段，只给 possible/WARN，不升级成确定性 ERROR。

## 可选 VLM 裁判

VLM request/response 都有显式 schema。页面裁判检查 page identity、variant evidence 与 coverage；动作裁判检查 source selector、target screenshot/page、landing、模态和权限语义。低于 `min_vlm_confidence` 或没有 reason/evidence 的结果只记录、不应用；VLM 不能抹掉确定性 ERROR，也不能把规则判定的 blocked/conditional 或只有截图证据的 discovered 直接提升成 verified。

## CLI

```powershell
python gui_rewalk/run_graph_quality.py path/to/graph.json `
  --json-out path/to/graph.quality.json `
  --annotated-dir path/to/quality_evidence `
  --fail-on error
```

增加 `--use-vlm --model ... --model-version ...` 可启用语义裁判。credential 只按指定环境变量读取；rules-only 模式不要求 key。`--json-out` 禁止覆盖源图。退出阈值可选 `none/error/warning`，无效 JSON 总是失败。

报告 `schema_version=gui_rewalk_graph_quality_report_v1`，包含 `status/score/confidence/summary/ledger/nodes/edges/findings`；CLI 另写 evaluation mode 与可选 VLM usage。`ledger` 对 schema v3 展开读取 `action_edges[].attempts`，不会要求顶层 `transition_events`。

## 截图标注证据

`--annotated-dir` 对 report 中每个 ERROR/WARN 生成稳定文件名的 PNG，并写 `manifest.json`（`schema_version=gui_rewalk_graph_quality_annotations_v1`）：

- node finding：单张节点截图；需要比较 Page/Variant 时追加 peer panel；未探索控件标为绿色；
- edge finding：source/target 截图并排；source element 黄色、允许 region 青色、实际执行点洋红；
- 每个 manifest entry 保存 finding key/code/severity/message、节点、动作边、解释、highlights、source screenshots 和 `generated/skipped`；
- 缺失/损坏截图不会中止整个导出，而是写 `skip_reason`；
- 文件名由 finding canonical hash + safe slug 生成；禁止路径逃逸或覆盖 symlink，PNG/manifest 原子写入；源 graph 与截图从不以写模式打开。

## 2026-07-11 修改与验证

- 增加 schema v3 Page/Variant、ActionEdge.attempts、verified routing 和 capability provenance 的确定性检查。
- 明确顶层 `transition_events` 在 v3 中是重复账本错误，verified capability 必须有 verified action evidence。
- 离线运行 `python -B tools/test_graph_quality_agent.py`、`python -B tools/test_graph_event_ledger.py` 与 `python -B tools/test_architecture_boundaries.py`，均通过。
- 未调用真实 VLM，未对 Clock/Alarm live 图或首批应用完整 v3 图做人工对照验收。

## 2026-07-15 `evaluate_data` 结构拆分

`GraphQualityAgent.evaluate_data` 现为 64 行编排壳，只负责深拷贝只读输入、
组装 node/edge/ledger 索引、按原顺序调用各检查维度，以及组装最终报告。
它内部不再定义闭包。确定性责任按功能放在同文件模块级 helper：

- schema v3：`_schema_v3_catalogs`、`_check_schema_v3_pages`、
  `_check_schema_v3_action_edges`、`_check_schema_v3_routes_and_capabilities`、
  `_check_schema_v3_invariants`；
- 状态与 shared control：`_check_open_stateful_mutations`、
  `_check_pending_shared_controls`、`_control_outcome_scope` 及其显式依赖 helper；
- node/edge：`_audit_nodes`、`_audit_cross_node_duplicates`、
  `_build_edge_report`、`_audit_edge`、`_audit_edges`；
- 汇总：`_summarise_findings`。

VLM 复核仍是短实例方法 `_apply_vlm_review`，继续使用原有
`vlm_judge/min_vlm_confidence/_apply_vlm` 合同。所有 finding code/severity、
追加顺序、评分、confidence、报告字段与签名保持不变。关闭 VLM 后，
三份 legacy/schema-v3/stateful 图的 canonical report SHA-256 分别为
`61d0c679603e90228b33a0738c8e1494e69b544c084d1dab0ad76fb8a5330a6f`、
`b6388489450c4a0e57541312feb1530089196cb302c723427d575d25de29773a`、
`71260988d5f6df3b2b8ebd0fe5756b7e91d9e1918c84da6cd9b5a7e314d9e624`，
与拆分前完全一致。

离线验证：`compileall` 通过；`python -B tests/test_graph_quality_agent.py`
通过；`tests/test_graph_quality_guards.py` 中 9 项通过，1 项既有的
VisualTraversalEngine data-control 候选过滤断言失败（本文件不在该调用链，
且修复超出本次允许范围）。未启动 VM，未调用真实 VLM，未执行 live 操作。
