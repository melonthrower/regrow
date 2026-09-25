# Phase 1 capability induction

## 2026-09-06 发现目录的直接消费路径

modular bundle 现在同时导出 function_inventory.json，直接投影 Region/CanonicalOperation 与 memory、
参数说明和已观察结果，包含未执行操作。run_capability_task_synthesis.py --region-ledger 使用该投影生成任务，
无需先调用下面的 effect induction。旧能力等级仍描述历史证据，不作为新 Region 任务的准入条件。
下面的效果归纳与 recipe 合同继续用于旧 capability-graph 路径，不应据此限制 Region-guided 采集。


路径：`gui_rewalk/src/core/graph/effect_observation.py`、
`gui_rewalk/src/core/scenario/capability_induction.py`、
`gui_rewalk/run_capability_induction.py`、
`gui_rewalk/src/core/scenario/capability_task_synthesis.py`、
`gui_rewalk/run_capability_task_synthesis.py`

本阶段把真实 `StateGraph.action_edges[].attempts[]` 中已经持久化的
`ActionAttempt` 作为唯一原始动作真值。它不改写 StateGraph 拓扑、Region 或
原始 attempt 的 `outcome`、`landing_verified`、`committed`。

## Evidence boundary

`landing_verified=True` 只证明入口动作实际执行且落地身份已验证。它可作为
routing 和 `entry_execution_evidence` 的来源，但不是用户业务效果，也不会单独
创建或升级 capability。业务效果只能由 append-only
`gui_rewalk.effect_observation.v1` 追加到
`attempt.evidence.effect_observations[]` 后离线读取。支持的业务 effect 为
`state_change`、`object_creation`、`object_removal` 和 `query_result`；单独 navigation 或
region introduction 不创建 capability。

每条 supported business effect 必须有自然语言 capability name/reason、
effect kind、带 formal `scope.region_ref` 的 before/after facts、parameter
bindings、predicate candidate 和 verdict。缺 Region ref、冲突或歧义均 fail
closed。


## Current autonomous producer

Autonomous capability evidence has two formal starts. An `explore_entry` start
persists the exact `entry_id`, its owner `source_region_ref` and discovery
source. A `probe_region` start instead persists the exact assigned
`source_region_ref`, keeps `entry_id` empty and marks only the first committed
action of one probe task as `region_probe_start=true`. Later actions with the
same `probe_id` remain steps in that recipe. Region-internal controls therefore
cannot create or execute formal Entries.

Both paths reuse the normal main-Agent before/after settlement. Its strict
`previous_action.business_effect` field is the current positive live producer.
It accepts one visually grounded `state_change`, `object_creation`,
`object_removal` or `query_result`, including the exact effect Region,
capability name, changed fact, before/after values and concrete parameter
bindings; null means no supported business effect. Runtime appends the observation only when the formal
Entry or Region probe matched its intent, changed the screenshot and remained
on the same canonical Page. It resolves the reported effect Region
independently from the action-source Region, so the two may differ. This adds no
Agent or Reviewer call and does not revive legacy temporary-state fields.

An independently reviewed terminal Entry attempt classified as non-interactive
or temporarily unavailable, and a Reviewer-bound exact Region pointer action
with no visible change, append a refuted `no_effect` observation. Opening a
Page, dialog, menu or Region is not a business effect. The autonomous producer
does not infer any effect from a click, pixel change or landing: missing,
ambiguous, cross-Page or unapproved-Region reports remain absent. The canonical
attempt field is the plural append-only `effect_observations[]`; the obsolete
singular spelling is not read.

## Offline graph

`ProbeEpisode` groups committed formal Entry or Region-probe starts by
`probe_id`; persisted output keeps only the source surface, attempt refs, effect
refs (including observation index) and outcome. Region-probe surfaces retain
the existing `entry_surfaces` v1 field with an empty `entry_id` and non-empty
`region_ref`; no parallel schema is introduced. Entry retries retain the
`entry_retry` role.

Capability recipe 不受 formal task 边界伪分割。如果一个效果 Attempt 能沿同一账本中
实际发生的 committed、`landing_verified` State 链向前连续追溯到最近的正式 Entry，
induction 就用这段真实动作前缀作为 entry surface、recipe 和 attempt evidence。
`query_result` 可以作为中间效果，其已验证参数绑定合入最终 recipe；遇到断裂 State
链、未验证 landing、先前 `state_change/object_creation/object_removal` 或参数冲突
立即停止，不跨越另一个有状态业务效果。没有完整 Entry 前缀时仍保留当前局部
ProbeEpisode。这里不跑 shortest path、不拼推断边，也不把历史坐标重新变成 selector。

`induce_capability_graph()` 输出独立
`gui_rewalk.capability_graph.v1`：capability identity 以 capability name、
effect kind、Region-scoped facts 和 parameter keys 组成。一个 supported probe
为 `discovered`；两个同 portable recipe probe 为 `executable`。分组前，induction
只在真实 action 的 `selector/parameters` 以及 Android `input_text.text` 中把与 Qwen
`parameter_bindings` 精确相等的标量替换成 `{{parameter}}`；同一值歧义对应多个
参数时不替换。一个参数必须在该 recipe 中出现且至少有两个不同真实取值，才进入
`parameters[].domain.values`；只出现在效果说明而没有进入动作的绑定只保留为
`parameter_candidates`。确认参数时同时保存完整、去重且确定排序的
`parameter_examples`，它表示真实共同出现的 tuple，不允许把各参数域当作任意笛卡尔
积。只有两个以上参数化 recipe 与 structured predicate 都一致，才为
`effect_verified`。

`relations` 仍只存在于能力图顶层，不把另一份 recipe 塞回 capability。当前唯一自动
关系是 `cleanup_cycle`：creation 与 removal 必须分别是 `effect_verified`，至少两组
真实 effect evidence 对同一 formal Region/fact 给出精确互逆的 before/after；各自
ProbeEpisode 的每个 committed Attempt 必须形成连续且 `landing_verified` 的路径，
cleanup 路径必须从 effect State 返回 baseline State。如果存在参数，cleanup 参数还
必须唯一对应 creation 参数，并由至少两个共同真实取值证明。任一条件不满足就不写
关系。relation 只保存两个 capability ID、baseline/effect State、参数对应与原始
effect refs，不生成重复的 `cleanup_recipe`。

在线调度不另写一套 capability 判定。开放 Region 的候选排序以
`region_probe_source_ref` 过滤同一纯 induction：`discovered` 表示仍缺一次
同 recipe 复验，`executable` 表示重复执行已有但 predicate 或参数证据仍不稳定，
`effect_verified` 表示不应只为增加次数重复。排序只改变尚未完成 Region 的优先级，
通过现有 task reason/known capabilities 给主 Agent 自然语言反馈；不新增账本、模型
调用或强制完成门槛，已完成 Region 不会重开。


## Autonomous collection projection

Autonomous 的 raw `graph.json`、`autonomous_regions.json`、
`autonomous_entries.json` 与 effect observations 是遍历账本和编译输入，不是
M13 的最终输入。两份 sidecar 同时提供时，`run_capability_induction.py` 在
annotated copy 上完成唯一一条正式投影：

1. 用 Entry 与正式 Region occurrence 给缺失的 ActionAttempt 补
   `source_region_ref`，冲突或歧义立即拒绝；
2. 要求没有 pending Entry action；
3. 从 Region occurrence 的 `state_ids` 与 Entry 的 `source_state_ids` 解析精确 State，
   并校验每个 State 的 Page 归属以及 Entry 的 owner Region 在该 State 确实出现；
4. 只向这些 State 写正式 Region `semantic_blocks` 与 semantic-only Element：
   Entry sidecar occurrence 使用 `uid=autonomous-entry:<entry_id>`；Qwen 已实际选择、
   Click Reviewer 精确批准且能绑定正式 source Region 的 point-targeted ActionAttempt（包括
   `input_text`）使用
   writer 分配的 `uid=autonomous-element:<digest>`。同一稳定身份可在多个 State 有
   occurrence，但保持同一 UID。

投影只携带稳定 Page/Region/Entry/Element 语义，不复制
`temporary_bbox_1000` 或 frame id。semantic-only Entry 同时携带 `operation`、`subject`、`entry_status` 和
`exploration_policy`，供编译器在顶层 `operation_catalog` 区分 `observed_only`、`action_verified`、`inferred` 与 `pending`；
同一 State/Region 中的歧义键使用完整命令身份 `operation_scope + operation + direction + target`。因此同一单元格可同时有
click/double_click，同一滚动表面也可同时有 down/right；只有完整命令身份仍相同而 entry_id 不同时才 fail closed。
其中 `record_only` 只进入 `observed_only` 目录，不生成可执行 recipe，也不冒充动作证据；`invalidated` 入口只留在自主遍历审计账本，不投影为 Element 或操作目录。M13 必须在当前截图上
重新 grounding。ActionAttempt 顶层 `element_id/element_label/region` 是已执行控件的
唯一稳定事实；Click Review 与 `source_region_ref` 只保留为证据，不复制另一套 Element
字段。capability entry surface 与 recipe selector 引用该 UID 和正式 Region ref。
它也不把 Entry 升格为 schema-v3 一等实体。新 writer State 使用模型无关的
`perception_mode=autonomous_vlm`；`luna_autonomous` 只读兼容旧图。旧 sidecar 缺少
State 归属时仅在该 Page 恰有一个 State 时兼容；multi-State 歧义、跨 Page 引用、
Entry 没有 owner Region occurrence 或现有 Element inventory 均 fail closed。

## CLI and scope

`run_capability_induction.py --graph_path ... --output ...` 只读已保存的
ActionAttempt/effect 证据。投影 autonomous Region/Entry inventory 时必须写到不同的
`--annotated_graph_output`，绝不覆盖 raw graph；capability graph 的
`source_graph_digest` 精确绑定这份 annotated graph，同一输入的输出保持确定性。
effect observation 只来自 Qwen 结算后写入 Attempt 的 append-only evidence，不再接受
另一份外部 effect batch 注入。

当 autonomous 完成门关闭且没有 gap 时，`run_visual_traversal.py` 自动调用同一
compiler，在该 run 目录写固定的 `annotated_graph.json` 和
`capability_graph.json`；编译失败会成为 completion gap 并返回非零。离线 CLI
保留用于重编译既有 raw graph，而不是第二套 producer。

compiler 不调用 live VLM、不进入 M13 collection，也不调用 Region bind/merge API；
它只编译 sidecar 已经裁定的正式身份和 Attempt 内的效果。上述在线 producer 只复用
遍历本来就有的 Qwen 主 Agent 结算回复。

## Downstream task bridge

Task composition now uses two read-only views over the same capability graph.
`compose_instruction_drafts()` first makes immutable framework skeletons, then
sends only the requested `start:n` slice to the composition Agent. Each visible
card contains capability ID, natural name, Page, at most three observed
parameter examples (or domain values), fixed parameters, and the short outcome
description. It does not send `execution_recipe`, predicates, evidence refs,
screenshots, raw attempts, or the rest of a large catalog. The Agent returns
only `skeleton_id + instruction`; any model-supplied capability or parameter
rewrite is ignored.

The current skeleton is intentionally one existing capability. The saved Clock
catalog still contains button-level records such as `click Add Alarm button`
and `click Add button`; grouping neighboring cards would create structurally
valid but semantically false tasks. Multi-capability skeletons therefore wait
for a separate evidence-backed business-capability regrouping step. Pagination
solves prompt growth now without pretending that arbitrary Page-local actions
already form one user goal.

When induction has only one unconfirmed value in each `parameter_candidates`
slot, the card labels that tuple as an `observed_example`; it can make a saved
recipe readable (for example `TYPE London`) but is not promoted to a confirmed
parameter domain and cannot authorize an arbitrary new value.

After a draft is selected, `selected_capability_context()` retrieves only those
capabilities and renders their parameter-bound successful steps plus the short
completion description. This is an on-demand Agent context view, not a new
field in the capability graph and not another evidence authority. Recipe-backed
`discovered` records may appear in the drafting catalog so traversal discoveries
can inform task ideas and enter M13 attempts. Discovery status is preserved;
M13 still hydrates the selected graph references and verifies the live result. Raw traversal evidence stays
in the graph bundle and is consulted only through existing debugging or
verification paths.

`capability_task_synthesis.py` consumes the independent capability graph directly.
It admits `discovered`, `executable`, `effect_verified`, and `composable` records.
No prior execution count is required to propose or attempt a task; the source
status and empty evidence references remain unchanged. Unknown status is rejected.
A normal selection emits one single-capability
instruction and chooses one complete `parameter_examples` tuple; a
multi-parameter capability without such evidence fails closed. A `cleanup_cycle`
selection still requires effect-verified/composable members and emits the same existing instruction format with two ordinary
capability refs: source first, cleanup second, `fixed_order=true`, and cleanup
`depends_on` source. It selects a source example whose linked cleanup values form
an observed cleanup tuple; per-field domain membership is insufficient. Each ref
retains its own authoritative structured recipe/effects/
predicate; no relation-specific executor or copied cleanup recipe is added.

The recipe already contains `{{slot}}` where real Qwen actions proved that
binding, so the existing M13 dynamic recipe binder consumes it without another
schema or model call. `run_capability_task_synthesis.py` selects either one exact
`capability_id` or one exact `relation_id` and writes one instruction JSON for
M13. It does not ask an LLM to invent another operation or perform general DAG
composition.

`TYPING/input_text` recipe steps that carry a semantic selector are not replayed
against historical focus. M13 resolves the stable Element UID (or its label plus
formal Region) on the fresh screenshot, verifies an input-like control, and emits
fresh `CLICK -> TYPE`; persisted x/y are ignored. Selector-free legacy `TYPE`
keeps its existing current-focus behavior.

`run_visual_collection.py --capability-graph APP_ID=...` makes that graph the
capability authority for the named app while `--graph` remains the routing truth
and `--node-dir` remains the live visual-artifact source. Before any VM or GUI
action, hydration requires the capability graph digest to equal the exact
`--graph` bytes, rechecks the capability ID, declared Page/Variant/State,
formal source Region and projected Entry, confirmed parameter domains, complete
observed parameter tuple and verification level, then restores the authoritative
recipe, effects and success
predicate. Instruction JSON cannot override those semantic fields, and M13 does
not read autonomous sidecars. A direct capability-graph ref uses an explicit
empty `target_node`: the post-action surface must still be identified, but a
same-Page Variant change is accepted only through per-capability effect
verification rather than forced source-State equality.

The production output is therefore a collection-ready bundle, not one new
application-specific JSON: annotated schema-v3 graph, independent digest-bound
capability graph, and screenshot/trace/node artifacts.

This remains a minimal single-capability handoff plus one evidence-backed cleanup
relation. Autonomous traversal can now
write one Page with multiple material Variants and compile exact Region/Entry
occurrences into those States and can report all four supported business-effect
kinds. A connected observed Entry→query→effect trace can now compile as one
capability recipe without a general DAG. Full visible Element occurrence
inventory, composition not witnessed as one connected trace, an external target
graph that guides autonomous exploration, and fresh-Qwen live trajectory
reliability remain later phases.
The cleanup regressions are offline and must not be cited as a live execution or
baseline-restoration result.

## Target acceptance fixture: Clock World add city

这是通用合同的具体说明和后续验收 fixture，不是 Clock 专用 Prompt/运行时规则，也不是
当前 live 通过声明。目标 Page 为 `page_id=clock.world`，身份锚点是 World 标签选中、
World 标题与城市区域可见。它必须保留四个 material Variant：

| Variant | State | fresh screenshot predicate |
|---|---|---|
| `world.empty` | `s_world_empty_01` | 城市列表为空，Add city 可用 |
| `world.add_dialog` | `s_world_add_dialog_01` | 搜索输入框与 dismiss 控件可见 |
| `world.search_results` | `s_world_results_01` | query 已输入，结果列表至少一项 |
| `world.populated` | `s_world_populated_01` | 城市列表存在本轮创建的目标城市行 |

稳定功能身份与 occurrence 分离：

- `r.world.toolbar / el.world.add_city`：Entry Element，tap 后显露 add-city
  功能内容；
- `r.world.add_dialog / el.world.city_query`：input；同 Region 的
  `el.world.result_row` 是 result item，`el.world.dismiss_dialog` 是 dismiss；
- `r.world.city_list / el.world.city_row`：本轮 created/query result；
  `el.world.delete_city` 是 cleanup action。

Region/Element 是稳定语义身份；各 State 只保存 occurrence/ref。frame id、bbox 与点击点
只属于某次 Attempt 的 before/after evidence，不能成为跨运行 selector。目标动作账本为：

| Edge | Attempt | From -> landing | Effect |
|---|---|---|---|
| `e_open_add` | `a1` tap Add city | `world.empty -> world.add_dialog` | landing verified；只打开 dialog，不是业务效果 |
| `e_query_city` | `a2` type `unique_city_query` | `world.add_dialog -> world.search_results` | `query_result` |
| `e_select_city` | `a3` tap result row | `world.search_results -> world.populated` | `object_creation`，目标城市行在 `r.world.city_list` 可见 |
| `e_delete_city` | `a4` tap delete | `world.populated -> world.empty` | cleanup/recovery；本轮城市行消失 |

目标 `cap.world.add_city` 的 entry surface 是
`clock.world/world.empty/r.world.toolbar/el.world.add_city`。它包含 World 可达、
Add city 可用且目标城市本轮不存在等 preconditions；recipe 为前三条 edge，
参数为 `city_query/selected_result`；desired effect 与 fresh screenshot success
predicate 都要求目标城市行可见；cleanup recipe 引用 `e_delete_city`。evidence refs
引用 `a1..a4` 及各自 before/after frames。只有重复的真实业务效果证据可以把它提升为
`effect_verified`，`a1` 的 landing 单独永远不够。

目标运行时流程是：fresh screenshot 识别 Page+Variant，查询 capability 的 entry surface，
必要时沿 ActionEdge 恢复/路由，在 fresh Region/Element occurrence 上重新 grounding，
逐步执行并追加新 Attempt，验证 landing/effect，再执行 cleanup 并确认 baseline。物理出口是
`annotated_graph.json`、digest-bound `capability_graph.json` 与 Attempt
screenshots/traces/node artifacts。

当前阶段已连通 fixture 的多 Variant identity 与最小 Region/Entry occurrence 投影，
但还不是完整 add-city Capability 验收：

- `tests/test_capability_induction.py::test_world_add_city_multi_variant_projection_uses_exact_occurrences`
  构造上述四个 State、三个稳定 Region 和三个稳定 Entry，并验证每个 identity 只投影到
  声明的 State；同一个 dismiss Entry 可在 dialog/results 两个 Variant 复用同一 UID；
- `tests/test_autonomous_loop.py::test_clock_world_writer_keeps_four_material_variants_and_real_edges`
  已验证同一实际 autonomous writer 能生成 1 Page/4 Variant/4 State、三条真实 ActionEdge，
  持久化带 State membership 的 Region/Entry sidecar，经 `StateGraph.load`、正式投影和
  autonomous resume 后仍保留四个 Variant、各自代表截图与 exact occurrences；
  当前完成门还会用同一 raw graph 和 sidecar 自动生成 collection-ready 文件；若
  `StateGraph.load`、投影、序列化重载或 digest-bound capability induction 任一步
  失败，本次 autonomous 不能以成功退出；
- 新 Variant 若没有自己的 Region occurrence，survey 会返回
  `material_variant_has_no_region_occurrence` 并要求重新 `record_regions`；旧 Page-only
  sidecar 只有单 State 时兼容，多 State 时继续拒绝而不盲目复制；
- 当前 Qwen producer 可将截图中明确可见、Region 可解析的
  `state_change/object_creation/object_removal/query_result` 写入同一 effect ledger，
  并把删除归纳为独立 capability；通用离线回归已能在两轮真实逆向 State/effect 证据
  充分时建立顶层 `cleanup_cycle`，但不会改写 creation capability 或伪造 cleanup recipe；
- Qwen 真正执行并经 Reviewer 确认的 Add/select 类 pointer 控件，以及只在
  `probe_region` 开放的短查询 `input_text` 控件，现在可以成为 action-backed Element；
  输入框不是 Entry，writer 仍只按正式 Region ref、Reviewer observed target 与真实 Attempt
  分配稳定 UID。这不等于枚举整页控件；
- 新的通用 Clock 离线 fixture 用两轮实际 Attempt 形状证明：`Add city`→`TYPE query`→
  `select result` 的连续 State 链可编译成一个三步 `object_creation` recipe；删除不会
  越过先前 creation 被并入同一 recipe；任一链路断裂时 capability 降级且不生成
  cleanup relation。该 fixture 是手写账本证据，不是 fresh Qwen；
- 多参数 recipe 同时保存 `city_query/selected_result` 的真实成对 examples。task
  synthesis 与 M13 validate-only 都拒绝把两个独立合法值拼成未观察组合；
- 当前真实 autonomous writer fixture 已证明 1 Page/4 Variant 的 raw ledger 可自动
  编译、`StateGraph.load` 并从 annotated graph resume；另一个一 Page/一 State 的
  `state_change` 回归证明 digest、task synthesis 与 M13 validate-only 连通，cleanup
  回归证明两个有序 capability ref 可通过同一 M13 入口。尚未用 writer 产生完整
  add-city effect recipe 并通过 M13，不能把这些组合测试冒充为 fresh Clock 端到端结果；
- 因此尚未实际动作的 input/result/created-object/cleanup occurrence、result/effect-object
  身份、真实 writer 产出的完整 add-city collection bundle、M13
  multi-Variant effect validation、fresh cleanup 执行与 fresh Qwen 实跑仍是后续验收，
  不能引用手写账本、投影或 validate-only 测试宣称完整目标已完成。

