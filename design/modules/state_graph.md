# state_graph.py — Page/Variant 能力图与动作尝试

路径：`gui_rewalk/src/core/graph/state_graph.py`

该模块只负责纯视觉图数据与 JSON 持久化，不负责页面匹配、导航、元素解析或前置条件规划。当前 `graph.json` 为 schema v3：`state_id` 是可执行的 `Page@Variant` 节点，稳定 `page_id` 聚合同一语义页面的多个 `variant_id`；持久动作真值是 `action_edges[]`，每条语义动作边拥有 append-only `attempts[]`。

## 接口

- `set_visual_crop(top_px, bottom_px)`：配置截图 fingerprint 的系统栏裁剪。
- `compute_visual_state_id(bytes)` / `compute_visual_fingerprint(bytes)`：生成观察帧的视觉召回与诊断证据。
- `add_state(...)`：登记执行节点，并同步其 `page_id/variant_id/observed_facts/visible_capabilities` 到页面目录。
- `register_capability_candidates(state_id, candidates)`：把当前视觉观察得到的 `discovered` 能力合并到页面、变体和全局能力目录。
- `record_action_event(...) -> action_index`：在真实 GUI 动作交给环境前，把 `outcome=attempted` 的 attempt 追加到对应语义 `ActionEdge`；环境返回、抛错和落地验收只更新这一条 attempt。名称为 schema v2 API 兼容，不再创建顶层事件账本。
- `update_action_event(action_index, ...)`：补充同一 attempt 的 target、outcome、landing、evidence 与 committed 状态。
- `correct_action_event_semantics(action_index, ...)`：只在 attempt 尚未 committed 时，用动作后截图已经
  确认的最终 target 替换该 attempt 的 portable selector、元素标签和语义描述，并把它移到对应
  `ActionEdge`；不会修改同一旧边上的其他历史 attempt。
- `merge_action_event_evidence(action_index, evidence)`：把 Region transition、Observer
  等独立事实合并进同一 attempt，不覆盖此前已经记录的执行或状态证据。
- `add_transition(...) -> action_index`：提交真实落地动作，更新对应 `ActionEdge`；`landing_verified is True` 只记录入口执行与路由引用，不晋升业务 effect 或 capability。
- `routing_graph` / `routing_view()`：派生只含 `routing_verified=true` 动作边的 NetworkX `DiGraph`，供 Router 与 M13 使用。
- `transition_events`：从 `action_edges[].attempts` 生成的只读 schema v2 兼容视图；不能赋值，也不会写入 v3 JSON。
- `record_abnormal_button(...)`、`mark_unreachable(...)`：保存终态异常与可达性，不伪造成功路由。
- `save(path)` / `load(path)`：原子写入 schema v3；加载 schema v1/v2 时迁移页面身份、事件和边引用。

## Router effect kinds (2026-07-17)

Schema v3 keeps the existing `ActionEdge` structure and adds optional
`effect_kind` metadata. Current values are `forward`, `peer_navigation`,
`shared_action`, `return`, and `dismiss_overlay`. `add_transition()` writes it to the semantic
action edge and compact topology; `routing_graph` carries the verified
representative's value; save/load preserves it. Router uses the field to replay
return/dismiss edges through Back and all other eligible edges through live
semantic click grounding. No separate return-edge schema or node type was added.

Verified Router/collection attempts may store `route_context`,
`predicted_target`, `actual_target`, and `prediction_match` under `evidence`.
`routing_graph` derives `route_contexts` from successful committed attempts.
This keeps visually identical Page@Variant nodes stable while allowing Back or
Close to have different verified targets for different entry sources. A shared
prediction never becomes routing evidence until live landing identity succeeds.
For ordinary forward actions, a committed live correction supersedes the old
predicted target for that source-local canonical action across entry contexts.
Only actions identified as Back/return semantics use `route_context` to retain
several valid destinations.
The live navigation stack also treats a landing on the current State's recorded
entry parent as a return when action metadata omitted that classification. This
pops the child and preserves the parent's previous entry source instead of
recording the child as a new parent context.
When the current entry source has no verified return edge yet, an explicit
Back/return action predicts that live entry source and probes it; it does not
fall back to an older context-free return target.
If that verified return was explicitly bound to a visible source control with
`explore_on_verify`, the same committed landing evidence marks the uniquely
matched source-local occurrence `complete` and persists it. A later revisit
therefore does not send the already verified Back/Close control to Explorer
again. Virtual platform Back remains edge-only because it has no visual control
occurrence.

Region-lazy discovery may register the visible control after the reverse probe.
Before exposing frontier work, scheduling matches a committed,
landing-verified reverse attempt to the unique source-local control label and
marks that occurrence complete. It reuses the original ActionEdge and does not
create a second ordinary Explorer edge.

Reverse Edge Explorer does not add another edge class or top-level traversal
ledger. A null model result is stored on the triggering forward attempt under
`evidence.reverse_probe`. Once a concrete action on B is accepted, a separate
`B→unknown` ActionEdge attempt is created before grounding and dispatch, with
`trigger_forward_attempt_id` and `intended_target`. Grounding failure,
not-attempted, dispatch-unknown, no-effect, identity failure, and the actual
landing update that same attempt. Only a committed, landing-verified actual
landing enters `routing_graph`; landing elsewhere changes the ordinary target
rather than inventing the intended `B→A` edge.

Each semantic action attempt may store relative
`evidence.screenshots.before|after` paths. The image bytes live under
`action_attempts/`, not in `graph.json`; the graph remains the audit index.
Reverse probing links back to its triggering forward attempt and compares the
fresh returned frame with that forward attempt's exact pre-action frame before
ordinary Page identity fallback. Internal Region scroll gestures used for
inventory, stitching, or target search are not semantic ActionEdge attempts.

Focused offline verification: `tests/test_visual_router.py` includes a
schema-v3 save/load route-view round trip for `effect_kind=return`. This is not
VM, VLM, device, or live traversal validation.

## Frozen Page identity (2026-07-18)

The graph persists the Page ID assigned by map-guided registration. Re-observing
a State may merge new elements, Regions, facts, or Variant material, but
`add_state()` does not derive a replacement Page ID from those observations.
Likewise, grounded Region sets and folded element wording do not select an old
State: only a unique strict-frame match or an accepted Page Identity result may
reuse one.
Resume installs the persisted Page ID and validates the remaining Variant
materials. New nodes and `state_meta.json` no longer contain
`page_anchor_tokens`, and the graph no longer emits
`hierarchical_page_identity_v1`. Loading an older graph removes that obsolete
field and normalizes the legacy version marker to
`semantic_page_variant_v1` without changing its persisted Page ID.

Foreground interfaces retain one reusable Region/function definition and receive
their own Page@Variant point when they expose a distinct set of functional entry
points. Their identity is centered on the active interface rather than an inactive
host. Path-dependent return destinations remain source-local action evidence;
they are not encoded into the foreground interface identity.

Human-readable page names are retrieval labels, not graph ids. A new observation
that collides with an existing label is compared against every same-name canonical
full screenshot. A visual match reuses the existing stable State; the source page
or return destination does not split a shared foreground interface. Only when every
candidate differs may the two-full-screenshot VLM assign distinct functional labels.
If the proposed label collides again, the same visual-candidate loop repeats. Existing
state, page, and variant ids remain frozen; label changes propagate to the in-memory
node, graph node, registry, and node metadata.

## schema v3

顶层包含：

- `graph_schema_version: 3`
- NetworkX 节点/紧凑拓扑 `nodes[]/edges[]`
- `pages`：按稳定 `page_id` 聚合的页面目录，每页包含 `variants`、页面语义名和能力引用；
- `capabilities`：跨观察合并的 portable 能力目录；
- `action_edges[]`：语义动作边及其 `attempts[]`；
- `scroll_ledger[]`：页面或稳定 region 的滚动边界与回顶证据；
- `app_name/action_counter/stop_reason/abnormal_buttons[]`。

执行节点至少包含 `state_id/page_id/variant_id/page_identity_version`，以及 `page_name/observed_facts/variant_signature/visible_capabilities`。同一 `page_id` 下可以有多个 `variant_id`；例如闹钟空列表与已有闹钟、蓝牙关闭与打开分别是同一页面的不同变体。`state_id` 仍是 Router 执行时识别和落地的具体节点，不是页面级聚合 id。

autonomous writer 现在把 accepted material Variant 写成同一 `page_id` 下不同的
framework-owned `variant_id/state_id`。`autonomous_natural_map.v2` 保存自然 Variant 名、
可见谓词与每 Variant 代表截图；节点的 `variant_signature/observed_facts` 保存相同语义，
resume 会恢复 Page 的全部 Variant，而不是折叠回单 State。当前每个 autonomous Variant
仍只对应一个 State，新 writer 使用 `perception_mode=autonomous_vlm`，raw 节点的
`elements/semantic_blocks/visible_capabilities` 仍为空。

Region group sidecar 为 occurrence 保存其真实 `state_ids`，Entry sidecar 保存
`source_state_ids`。Qwen point-targeted action（包括受限 `input_text`）经 Click Reviewer 精确批准并绑定正式 Region 后，
writer 还会在 ActionAttempt 顶层保存稳定 `element_id/element_label/region`；Entry 动作复用
`autonomous-entry:<entry_id>`，普通已执行控件使用 `autonomous-element:<digest>`。
collection compile 在 annotated copy 中只向这些精确 State 投影正式 Region
`semantic_blocks`、Entry Element 和 action-backed Element，不改变
Page/Variant/State 或 ActionEdge/Attempt；同一稳定身份可在多个 State 复用同一
Element UID。旧 sidecar
缺少 State membership 时仅在 Page 恰有一个 State 时兼容，multi-State 歧义 fail closed。
Entry 仍不是 schema-v3 一等实体；未实际动作的 input/result/object/cleanup、非 pointer
输入与效果对象 occurrence 也尚未由该窄投影补齐。

resume 将 `page_identity_version=external` 的 Page/Variant ID 视为 producer-issued opaque
identity；投影后新增的 semantic Element 不会触发 Variant 重算。严格
`semantic_page_variant_v1` / `hierarchical_page_identity_v1` 身份仍按持久 facts 校验，
因此这不是对普通图身份一致性的放宽。

一个 `ActionEdge` 至少包含：

- 稳定 `action_edge_id`；
- `source/target` 执行节点和对应的 `source_page_id/source_variant_id/target_page_id/target_variant_id`；
- 去坐标的 `action`：动作类型、语义 `selector` 和非几何参数；
- 元素/region 归因、语义描述；
- `action_steps/action_sequence/transition_kind`：多 primitive 动作的真实 GUI 成本与组成；
- `attempts[]/attempt_count/routing_verified`。

一个 attempt 至少记录 `action_index/source/target/outcome/detail/landing_verified/committed/timestamp/evidence`。成功、失败、no-effect、permission gate、off-app、crash 都追加到所属动作边，不维护第二份顶层日志。早期 target 未知的失败可以先挂在未解析语义边上；后续同一 selector 成功落地时，该边原地补 target，历史失败不会丢失。同一 source/target 的不同按钮或动作拥有不同 `action_edge_id`；同一稳定控件上的 `CLICK`、`RIGHT_CLICK` 等不同原生动作也分别保存，不会再被 `DiGraph` 或“按钮已访问”压缩。

动作后截图若明确纠正了本次按钮名称，框架可在 commit 前调用
`correct_action_event_semantics`：当前 attempt 保留相同 `action_index/attempt_id` 和已有截图、执行、
落地证据，只替换语义 action 并移动到修正后的 `ActionEdge`。旧名称写入
`evidence.transition_observer.original_target`；旧边上更早的失败或成功 attempt 不被覆盖。
committed attempt 的语义保持不可变。

Reverse Edge Explorer 的无动作结果只更新触发它的 forward attempt；接受具体动作后则在
grounding 前创建独立的 target-unknown attempt。两者通过
`probe_action_attempt_id/trigger_forward_attempt_id` 互相引用，不新增顶层账本。probe 的
`intended_target` 只是探索意图，`actual_target` 与 committed topology 始终来自 fresh landing
identity。

同页新变体的节点可保存 `region_partition_mapping` 与 `region_transition`。后者的
`introduced_regions[].introduced_by_attempt_id` 是“哪个真实动作引入了哪个 Region”
的审计事实；同一结构也合并到该 attempt 的 `evidence.region_transition`。它不会仅凭
landing 自动把 `introduced_region` 变成 capability 的 `region_ref` observable；业务 effect
必须由显式 Phase 1 effect observation 与离线 induction 另行建立。

真实 CLICK 的 attempt 必须先于 `env.step()` 入账；调用返回后先更新为 `executed`，随后再补 target、effect 和 landing。若后端抛错，即使点击可能已经送达，原 attempt 也保留并更新为 `execution_error`、`landing_verified=false`，不能因异常丢失真实操作，也不能进入路由。

持久动作和 capability recipe 会递归剥离坐标、bbox、center 等观察期 geometry，只保留可在另一环境重新 grounding 的语义 selector。截图、元素 bbox 和视觉 fingerprint 仍保存在节点 sidecar/节点证据中，但不是便携动作契约。

模型回复中的元素顺序和临时 ID 不写成图身份。元素先按 Page/surface、Region、规范化标签、group
和 state key 映射到 framework-owned canonical ID；category/type 只作为可更新判断。capability
的 `source_element_id/source_element_uid` 只能引用 canonical ledger。完成证书核对该引用时，
除 ID/UID 外还要求双方已有标签一致，避免抖动回复把旧 ID 错绑到另一元素后仍通过完整性检查。

`routing_graph` 只纳入同时满足以下条件的动作边：存在明确 target；至少一个 attempt 已 committed；`landing_verified is True`；outcome 不是 no-effect、blocked、off-app、crash 等非路由终态。`landing_verified=None` 不能进入最短路径。

`tools/transition_viewer.py` 展示视觉图时优先读取 `action_edges[]`，而不是会压缩平行动作的 NetworkX
`edges[]`。Viewer 仅把当前 source State 的 verified action 显示为可跳转；元素 `visited=true` 但无本地
边时显示为策略覆盖，disabled/blocked/selected/非 navigation 显示为跳过，只有剩余可执行 navigation
才是待补点。若 Region-lazy 元素的持久 bbox 为空，Viewer 从相邻
`target_grounding_attempts/*/result.json` 中读取 accepted grounding，并以精确输入帧或
同名元素的持久 center 绑定实际 bbox。没有 durable element 的 label-only verified action
仍会出现在来源 State，并使用同帧 grounding 画框；同名 source/target verified 边不会被删除，
而是在列表中显示真实数量。旧 `transitions.ndjson` 和无 `action_edges` 的旧图继续使用兼容入口。

## scroll_ledger 与补审

`scroll_ledger` 以稳定 `scope_id` 保存页面或 region 的滚动穷尽证据。每条记录包含 `state_ids/region_id/role/classification/termination/bottom_reached/top_restored/steps/max_steps/detail/observations/complete`。移动端页级 scope 使用 `state:<state_id>:page`；桌面稳定区块使用 `region:<region_id>`，同一共享 region 可覆盖多个 `state_id`。
补审期间的请求局部 `bN` 必须先映射回该 State 已登记的稳定 `rN`；局部 block id 不写入 ledger。

- `classification=static` 只有在 termination 为 `static` 或 `viewport_stable` 且已回到 canonical top 时完成；
- `classification=scrollable` 必须真实到达 bottom、以稳定底部终止并恢复 canonical top；
- hard cap、error、off-app、budget、timeout 或未知终止都不是完成证据；
- 已完成的共享 region 不会被后续 reuse/skip 记录降级；失败或截断记录则保留到一次新的真实滚动补齐 bottom 与 top 证据。

新 Region 首次观察后建立一次有界行为审计；移动端显式页级 scope 与桌面稳定 Region scope
若已开始但 `complete!=true`，仍须补齐。桌面共享 Region 复用已完成记录，普通重访与历史
静态 State 不因 ledger 缺失而逐节点重滚。证书要求所有已开始的 scope 完整，并要求
`scrollable=true` 的 Region 有完整证据；它不再要求每个 Page@Variant 各自拥有重复 scope。

恢复时 `graph.json` 的 State 集合高于截图 sidecar：权威图中没有的同 ID 截图不能把一次新登记
变成重访。新 State 会覆盖这类中断孤儿截图；已知 State 的正常重访仍保留首次 canonical
screenshot。

## 遍历完成证书

`gui_rewalk/src/core/graph/traversal_completion.py` 的 `evaluate_traversal_completion(graph_or_data)` 是纯函数、fail-closed，并且只从持久证据得出 `certified|incomplete`。旧 schema、缺字段、容器损坏或证据含糊都返回 incomplete；不会由 `visited`、缓存的 `routing_verified` 或节点数量乐观推断。八项检查必须同时通过：

1. `schema_materials`：原生 schema v3 的 nodes/pages/variants/capabilities/action edges/attempts/scroll ledger 等材料完整且引用、id 和类型一致，不并存旧顶层 `transition_events`；
2. `frontier_exhaustion`：持久 `stop_reason=frontier_empty`；
3. `scroll_exhaustion`：每个已开始的 scope 证明 static/bottom 边界和回顶，且所有明确
   `scrollable=true` 的稳定 Region 均有完整 scope；同一 Region 证据可覆盖多个 Variant；
4. `control_coverage`：每个交互控件有真实 verified attempt、允许的终态、显式 back、Explorer 的 `semantic_only` 结案、由真实 verified attempt 支撑的 `covered` 代表、合格同构 group 代表或非导航/非 stateful 的 grounded inventory capability；`covered` 代表可以来自当前 State，也可以由 `covered_by_state + covered_by` 指向同一稳定 Region 的另一 State，但它只证明 Explorer 覆盖关系，不成为当前来源的 verified attempt；单独 `selected=true` 或 `visited=true` 不算证据；navigation group alias 只允许由真实 `verified_attempt` 代表覆盖，代表自身的 abnormal/no-effect、back 或 inventory 只能关闭自身，不能替同组未执行导航项结案；
5. `state_restoration`：每个 stateful probe 都有同 `mutation_id` 的真实、已验证逆操作并回到原值；
6. `page_variant_consistency`：node、page、variant 与 ActionEdge 的身份和双向引用一致；
7. `routing_reachability`：恰有一个根，所有节点都由 raw verified attempts 可达，且没有标记为 unreachable 的节点；
8. `capability_integrity`：capability 的 page/variant/source/target/action-edge 引用均落地，verified capability 还必须有 verified edge、observable effect 和 success predicate。

`frontier_empty` 只是第 2 项，绝不单独等于“遍历完成”。对
`perception_mode=region_lazy` 的节点，`control_coverage` 还要求持久化
`region_observation` 非空且每个 Region 都是 `complete`；`pending`、`retry` 或
`unresolved` 都产生 `region_inventory_incomplete`，即使当前没有已登记按钮也不能据此
认证“没有功能”。证书的限定 scope 是：**当前应用/环境 fixture 中，在当前视觉感知与安全策略下已经发现且可达的功能表面**。它不能证明从未被感知、被安全策略排除、受另一权限/账户/硬件/数据状态约束的功能不存在，也不能外推到另一 OS、应用版本、locale 或 fixture。

控件 ID 允许为数值 `0`；完成证书会把它规范化为字符串 `"0"`，不会把合法的首个控件误判为
缺少身份。恢复覆盖只认 source-local verified action attempt；element 快照中的 optimistic
`visited` 和跨 State recurring UID 都不能代替动作证据。

同一 State、同一稳定 Region 的非 stateful、可执行、无风险同组项可以引用其中一个 source-local
committed、landing-verified CLICK 代表并保存为 `covered`；inventory 仍保留每个 occurrence。
stateful、危险、不可用、权限受限或跨 State/Region 项不能走这条确定性 group 覆盖。

若 pending mutation 通过 fresh source landing 明确观察到冻结的恢复候选基线而关闭，运行时会把
`purpose=restore`、`restoration_kind=verified_baseline_return`、`restore_before_value` 和 fresh
observation 证据合并到触发该落地的最新 committed、landing-verified attempt。resume 与
`state_restoration` 都从该持久证据识别事务已经闭合；仅清理内存状态而没有 attempt 证据不算恢复。

以下终态 abnormal reason 可直接关闭 source-local 控件覆盖：`disabled`、`permission_blocked`、`blocked`、`no_effect`、`stateful_no_effect`、`stateful_risk_blocked`、`external_app`/`external_app_*`、`app_crash`/`app_crash_*`。`target_rebind_failed`、`action_execution_failed`、`action_verification_failed` 只有在记录包含 `bounded_local_failure`、至少两次尝试和具体失败类型时才可结案；`route_unavailable` 还必须证明至少两次路由恢复落到图中另一个已知 State。缺少结构化证据的旧记录会在 resume 时重新开放。`stateful_verification_failed`、`uncertain` 与 `transitioned_inconsistent` 仍不能颁证。

## 兼容与迁移

schema v1/v2 仍可加载。v2 顶层 `transition_events[]` 会迁移为对应 `action_edges[].attempts[]`，旧拓扑边会重建动作边引用；保存后写 schema v3，且不再输出顶层 `transition_events`。旧图被 `DiGraph` 覆盖的重复语义边或从未记录的失败仍不可恢复，迁移结果必须保留历史不完整语义，不能声称补齐了未持久化证据。

## 边界

- 页面/变体身份判定属于 `visual_state.py`；在线候选生成属于 `capability_discovery.py`；路径规划属于 `visual_router.py`。
- `action_edges[].attempts` 是动作审计真值；NetworkX `edges` 是紧凑拓扑和动作边引用；`routing_graph` 是严格验证后的派生视图，三者不能互相替代。
- M13 的 prerequisite setup/cleanup 仍可产生动作证据，但前置规划不属于遍历图存储职责。
- 默认 `state_type` 为 `visual`。

## 2026-07-11 修改与验证

- 图升级为 schema v3；新增 Page/Variant 目录、在线 capability 目录和一等 `ActionEdge.attempts`。
- 移除持久化顶层 `transition_events`，保留只读内存兼容视图；新增 v2→v3 迁移。
- 动作持久化改为语义 selector 并剥离历史 geometry；`routing_graph` 只保留真实且 `landing_verified=True` 的边。
- 离线运行 `python -B tools/test_graph_event_ledger.py`、`python -B tools/test_online_capability_discovery.py`、`python -B tools/test_visual_run_state_machine.py`、`python -B tools/test_resume_from_graph.py`、`python -m pytest -q tools/test_visual_router.py` 与 `python -B tools/test_graph_quality_agent.py`，均通过；Router 批次为 7 passed。
- 未启动 VM、Android emulator 或真实 VLM；Clock/Alarm 从 empty 到 detail 的 live 闭环尚未验收。

## 2026-07-12 scroll/完成证书修改与验证

- schema v3 新增 `scroll_ledger`，并明确静态/底部吸收态、回顶和 resume 补审语义。
- 新增八项 fail-closed 完成证书；`frontier_empty` 只证明 frontier 穷尽，不能替代完整认证。
- CLICK attempt 改为 `env.step()` 前入账，后端异常更新同一 attempt 为 `execution_error`。
- 本轮离线运行 `python -B tools/test_traversal_completion_certificate.py`、`python -B tools/test_graph_event_ledger.py`、`python -B tools/test_visual_run_state_machine.py`、`python -B tools/test_resume_from_graph.py`、`python -B tools/test_graph_quality_agent.py` 与 `python -B tools/test_live_status_summary.py`，六项均以退出码 0 通过；未启动桌面 VM、Android emulator 或真实 VLM，未做任何 live GUI/landing 验收。
- 证书后续收紧 navigation 同构组：只有 verified attempt 代表能参数化 sibling aliases；同一测试脚本新增 `external_app`/`no_effect` 代表不能背书 alias 的回归并离线通过，未据此声明任何 live Settings 完成。

## 2026-07-12 provisional execution state 回收

`StateGraph.remove_uncommitted_state(state_id, alias_to=source)` 只服务于动作验收前的临时落地节点。它要求节点没有 topology 入/出边、没有 abnormal source、没有以它为 source 的 attempt，且所有指向它的 attempt 都未 committed、未 `landing_verified=True`；否则返回 `False` 且不改图。允许回收时同步处理 action attempt target、Page/Variant membership、capability source/action-edge refs、scroll scope 与目录 projection。

## Source-local terminal evidence（2026-07-21）

`abnormal_buttons[]` 中的每条记录由 `state_id + stable element token` 定位；Region id 和元素名只在
该来源节点内帮助找到 occurrence，不能形成跨 State 的终止键。共享 Region 的失败结论不传播，
completion 也只接受同一来源上的实际终态记录。旧版运行若留下没有对应来源异常记录的
`terminal_observed_outcome`，resume 会把该 occurrence 恢复为待探索。

Engine 的正常 no-effect/relaunch 路径先完成页面和结构化状态等价证明、在 attempt target 仍 unresolved 时回收节点，再把 attempt target 写成 canonical source，避免 mixed historical attempts 的重定向歧义。通用图 API 若发现一个 target edge 同时带 unresolved 与 provisional-target attempts，当前明确零变更拒绝；调用方不能据此声称节点已合并。

离线验证：`python -B tools/test_graph_event_ledger.py` 覆盖成功回收与 mixed-history 原子拒绝；`test_visual_run_state_machine.py` 覆盖 stateful no-effect、crash-relaunch unchanged 与 unknown fail-closed。桌面首轮 live 图只用于确认两个 Bluetooth jitter 落点满足新等价谓词；未因此声明 live Settings 已完成。

## 2026-07-10 历史修改

删除旧 UI-tree hash/match/serializer/path helper，同时修复 load 未恢复 `stop_reason`。`tools/test_architecture_boundaries.py` 覆盖 round-trip。

## Phase 1 effect-observation and induction boundary (2026-08-09)

`landing_verified=True` is only a verified Entry execution/landing fact. It may
populate source capability `entry_execution_evidence` and routing provenance, but
it never proves a business effect or upgrades a capability on its own.

`ActionAttempt` remains the only raw action ledger. The public
`append_effect_observation(action_index, observation)` normalizes and appends a
`gui_rewalk.effect_observation.v1` record at
`attempt.evidence.effect_observations[]`; it leaves `outcome`,
`landing_verified`, and `committed` unchanged. The raw graph stores no derived
Phase-1 capability graph and Region/Entry sidecars remain their traversal ledgers.
The induction CLI may compile those already-approved identities into a separate
annotated graph copy by adding semantic Region blocks and Entry Elements and by
filling a missing source Region ref. It never overwrites the raw graph or invokes
Region bind/merge. Exact Region `state_ids` and Entry `source_state_ids` may
legitimately target multiple States on one Page; conflicting Page ownership,
missing owner Region occurrences and legacy multi-State ambiguity fail closed.
