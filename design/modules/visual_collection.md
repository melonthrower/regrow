# M13 纯视觉采集执行器

## 2026-09-06 Region 指导模式

同一 CLI 使用 --region-ledger <exploration_ledger.json> 进入 RegionGuidedCollector；
此模式只需 --instruction，不要求 --graph/--node-dir/--capability-graph，也不要求预先执行的 recipe。
--validate-only 在 VM 和模型构造前校验任务 Region 引用及可选来源 ledger digest。
正式执行需 --initial-app；--model-backend 可选 openai_api、codex_cli、qwen_api，
openai_api 复用被忽略的本地 API 配置和原 transport/debug 记录，不输出凭据。

任务使用 before、condition（Region 与问题，或 null）、if_true、if_false、after。
条件在采集当前图中才判定，null 继续观察；条件截图、分支、目标完成截图与实际 primitive 动作使用原 CollectionWriter 保存。
Region 关系只作为有上下文的历史指导；到达目标区块后，Agent 执行当前 goal，未知 State/新控件不要求预先入图。
模型每轮至多一个语义动作并回填前一结果，所有目标完成后再做一次带完成截图的最终核对。
max-turns 是决策预算，不增加逐步反思、固定次数效果复验或路线偏航后的自动完整重采。
新模式记录 executor=RegionGuidedCollector，原 M13 路径与默认 Qwen 行为保留。

本次只做离线链路验证。当前是单应用模式，目标前景丢失或模型无法确认时保存 partial；
尚未增加跨应用业务操作、外部前景自动恢复或预置数据 setup 支持。启动不会调用 env.reset 回滚桌面快照。
以下原 M13 的 State/recipe、前置与重采规则仅适用于未使用 --region-ledger 的路径。


## 按需 SeedPlan 与单任务 scenario delta（离线合同）

Android collection 可选 `--seed-manifest`。它只在 `--android-snapshot-name` 精确绑定的 clean base 上，将 capability
graph authority 固定的可选 `seed_objects` 与 typed scenario delta 形成 `guitraverse.seed_plan.v1`；raw instruction ref
不能指定对象。没有 authority binding 的既有 Capability 保留零对象 SeedPlan（不猜测或全量注入），从而保持旧 graph 的
collection compatibility；需要特定已有数据的 Capability 必须在 authority 中显式绑定。plan 在 `env.reset()` 后、首次
App 激活和任何模型调用前写到 runtime `seed_plan.json`，apply/readback 失败立即停止。该 setup 是环境 provenance，
不加入 GUI step 或 instruction 内容；delta 仍保持下述独立 evaluator 合同。

`src/core/scenario/collection_scenario_delta.py` 定义独立的
`guitraverse.scenario_delta.v1` 小型增量合同。根对象严格限定为
`schema/task_id/base_snapshot/mutations/assertions`；首版只能追加 inbound SMS 或向
`Documents/GUITRAVERSE/...`、`Documents/Markor/GUITRAVERSE/...` 写入 `.txt/.md`；每个
路径 segment 还必须是 `[A-Za-z0-9._-]+`，因此不能把 shell 元字符带入 ADB 参数。
`apply_scenario_delta()` 在精确 snapshot 名称匹配后才执行固定 ADB 参数；text file 会先用
固定 `shell mkdir -p <safe-parent>` 创建由已验证路径推导的父目录，再 push，并对每项使用
`content query --projection address:body` 或 `cat` 读回。SMS 只接受同一 query row 的完整
address 和末尾 body 字段精确相等，body 中的逗号保留为正文。它不生成 GUI step、不调用全量 seed，
也不执行任意 shell/SQL。

`evaluate_scenario_delta()` 只把非空 scalar binding 写成断言期望，独立核查 sent SMS
的 recipient/body 同行证据或文件精确内容。setup report 固定为 `guitraverse.scenario_setup.v1`，
evaluation report 固定为 `guitraverse.scenario_evaluation.v1`；两者都含 task_id、digest、ok、items；
读回或断言不匹配只能报告 `ok=false`，不能被记为成功。此模块的离线 fake-device 测试不构成
emulator 或 GUI 采集验收。

## 定位

旧 `ScenarioExecutor` 已删除。现役 M13 从 capability-backed instruction 和每个应用独立的视觉图开始，在桌面或 Android 的实时截图上执行最少 GUI 操作路径，并输出带图 provenance 的 screenshot-only episode。

旧的 `trajectory_verifier.py` 与 `reward_evaluator.py` 没有接入该入口，已经删除。
现役质量门不是独立的 1–5 分 LLM reward：每个 GUI primitive 都通过 source、
grounding、landing/effect 与 commit gate，轨迹另做确定性 `agent_trajectory_audit`，
整条 instruction 最后再做 fresh screenshot verification。未经过这些门的旧
`action_json + annotation` 轨迹不能作为 M13 质量结果。

核心文件：

- `src/core/scenario/visual_collection_executor.py`：计划、依赖、app 边界、重规划、前置与完成 gate；
- `src/core/scenario/live_visual_collection.py`：复用已 resume 的 `VisualTraversalEngine` 做身份、实时 relocation、动作与 settle；
- `src/core/scenario/visual_prerequisite_agent.py` / `prerequisite_runtime.py`：资源/状态/授权/登录前置与所有权；
- `src/core/scenario/collection_writer.py`：`write_visual_episode()` 落盘；
- `gui_rewalk/run_visual_collection.py`：正式 CLI。

## 输入与 CLI

```powershell
python gui_rewalk/run_visual_collection.py `
  --instruction instruction.json `
  --graph settings=path/to/settings/annotated_graph.json `
  --node-dir settings=path/to/settings/node_artifacts `
  --capability-graph settings=path/to/settings/capability_graph.json `
  --graph calendar=path/to/calendar/graph.json `
  --node-dir calendar=path/to/calendar/node_artifacts `
  --initial-app settings `
  --vm-provider vmware `
  --path-to-vm path/to/machine.vmx `
  --model-backend codex_cli `
  --model-version gpt-5.6-luna
```

`--model-backend` 默认是 `qwen_api`，保持原有 DashScope 行为。`codex_cli`
使用本机已登录的 Codex CLI，以 read-only sandbox、当前 Prompt 和当前截图做无会话隐藏
状态的调用；它不读取 `DASHSCOPE_API_KEY`，也不改变 executor 或动作授权边界。
Android collection 可显式传 `--android-snapshot-name`；环境继续使用既有 read-only/
no-snapshot-save 启动合同。可选 `--seed-manifest` 与 `--scenario-delta` 在启动 GUI 前严格加载并核对
`base_snapshot`，且 delta `task_id` 必须精确等于 instruction ID；只在 `env.reset()` 完成后、
首次 App 激活和截图采集前执行 setup。
setup/evaluation/data bindings 独立写入 episode meta/trajectory 顶层，不伪装成 GUI step。

正式 autonomous 输入是 collection-ready bundle：annotated schema-v3 graph、
独立 `gui_rewalk.capability_graph.v1`、node artifacts 与截图/trace 证据。raw
`graph.json`、autonomous Region/Entry sidecars 和 Attempt 内 effect evidence 只是
induction 的编译输入；M13 不读取这些 sidecar，也不接受任何模型或应用自定义目标图
替代 `StateGraph`。无 gap 的 Qwen autonomous 完成门会在同一 run 目录自动写
`annotated_graph.json` 与 `capability_graph.json`；未完成 run 只保留 raw 账本，
不能冒充 collection-ready 输出。

每个 `app_id` 必须同时有一份可 load、非空 graph 和 node dir。node dir 仍提供实时
识别/定位所需的节点 sidecar。能力权威有两条明确路径：未提供
`--capability-graph` 的历史应用继续从 `*/page_capabilities.json` 联邦 catalog
解析；提供该参数的应用只从独立能力图解析，不回退 sidecar 能力描述。M13 会计算
`--graph` 的 SHA-256，并要求它与能力图的 `source_graph_digest` 完全一致。
从其他机器复制 bundle 时，节点可能仍保存原机器的绝对 `screenshot_path`。若该路径已
失效而 `node-dir/screenshots/<原文件名>` 存在，M13 只在加载后的内存图中重绑定路径；
若 fingerprint 为空，则从该本地截图补算。源 graph 文件不改写，digest 校验仍针对原始
字节。

历史 sidecar 路径接受 `availability_status=discovered|executable|verified`。独立能力图路径接受
`verification_level=discovered|executable|effect_verified|composable`；发现即可尝试采集，不要求历史执行次数。
原证据状态保持不变，不将发现改为 verified。入口仍重新检查能力 ID、入口
Page/Variant/State、formal Region、projected Entry、参数域、完整 observed parameter
tuple、recipe、effects 与 structured success predicate。entry surface 声明 `element_uid` 时，该 UID 必须在
指定 State/Region 下唯一命中一个 projected Element；Entry 还必须精确命中
`uid=autonomous-entry:<entry_id>`，Region probe 等普通已执行控件可以引用
`uid=autonomous-element:<digest>`。`luna_autonomous` 只作为旧图读取兼容。未投影的
raw graph 会在启动 GUI 前失败关闭。历史 bbox/click point 不参与这一校验或运行时定位。
未知状态或缺少执行必需信息的记录仍失败；instruction 自带的
recipe/effects/predicate 不能覆盖能力图事实。

`--validate-only` 验证上述 bundle、任务引用与 digest，不启动 VM、模型或执行动作。
CLI 不接受 credential 参数；现有模型 transport 只从环境读取凭据。

## Instruction / 计划语义

每个 ref 至少包含 `ref_id/app_id/node_id/target_node/name`，并可带 `requires/depends_on/params/action_steps` 及 capability 的 success contract。执行器：

1. 将 ref 间的显式 `depends_on`、requires-to-ref 依赖、顶层 dependencies 与 `fixed_order` 合并成依赖 DAG；
2. 在当前 ready refs 中按 `app switch cost + app 内 route cost + capability action_steps` 选择成本最低者；一个 capability 有多个 `entry_surfaces` 时，route cost 取当前 State 到各有效入口的最小值；
3. app 内 route 使用 edge `action_steps` 的 NetworkX shortest path；无字段按 1；
4. 跨 app switch 是显式 1 GUI step，并记录 `graphs_merged=false`；
5. `fixed_order=true` 时严格保持 ref 顺序，不能为了省一步破坏用户语义。

`cleanup_cycle` 不增加专用执行分支。能力图中的 relation 先由 task synthesis 转成
两个普通 capability ref：source 在前、cleanup 在后，后者显式依赖前者，并设置
`fixed_order=true`。M13 仍按相同 authority hydration 逐一核对两个 capability 的
digest、entry surface、Region/Element、参数域、recipe 与 effect contract，运行时也
分别在 fresh screenshot 上 grounding 和验证。relation 中的历史 State/effect cycle
只证明这两个能力曾形成可恢复关系；`--validate-only` 只证明合同可消费，不证明 fresh
GUI 上已经完成创建、删除或 baseline restoration。
这保证的是**在现有图、已声明成本和依赖约束内**的最少 GUI 操作路径，不声称解决未知 UI 状态上的全局最优控制。

live identity 先接受唯一 byte-identical State；否则用现有 Page 候选卡缩小 Page，再由
`KnownPageStateLocator` 只在该 Page 的已知 State 中比较结构与完整截图。Page 的复杂
Stage 代表图可能与当前简单 Stage 不同，因此 Page shortlist 不是最终身份；精确 State
匹配才是 route/landing 的结论。同一个 GUI 动作事务内只做一次身份识别，直到执行真实
primitive 才失效，防止 `ensure_app/route/perform_action` 重复调用模型。

## 连续采集 workflow

这条 workflow 只在 M13 内使用，不改变遍历阶段。开始时仍用现有 locator 确认一次实机
位置；之后不再为每个已知有向边重新执行全局 Page shortlist、代表图比较和 State 全量
匹配。框架从现有 graph 临时生成自然语言，不新增持久 State 类型。例如：

```text
框架预计当前位置：
s3，Stopwatch 页面；Main Content Area 有 Start button、Lap button

后续路线：
1. 点击 Start，预计到达 s11，Stopwatch 页面；Main Content Area 有 Pause button、Lap button。

最近操作：
- 从 s1 点击 Alarms，已到达 s2。
- 从 s2 点击 Stopwatch，已到达 s3。
```

Agent 每轮只返回截图是否符合预计位置、上一动作是否成功、简短理由，以及可选的下一
安全点击 bbox/point。最近历史最多三步。下一点击必须精确对应框架计划；normalized point
必须在自身 bbox 内，换算后的像素还须在当前活动窗口内。首步、目标不清楚、非 CLICK、
危险/未验证 capability、模型不匹配或几何无效都沿用旧 grounding 和 Reviewer。落地不
匹配时 workflow 不改图，旧 live identity 识别真实 State 后按现有 Router 重规划。

完整 Stage 不匹配时，同一 workflow turn 还可检查“下一条已知 graph edge 所需的一个
Region”。输入仍是自然语言，例如：

```text
如果整个 Stage 对不上，只检查下一步需要的区块：
r1，Top Navigation Bar，包含 World、Alarms、Stopwatch、Timer、Menu
```

仅当该 Region 是当前活动表面、下一目标精确匹配且给出合法当前帧 bbox/point 时，允许
一次 Region-only safe CLICK。框架不把当前画面登记为预计 State：对应 step 的
`arrived_node_id` 为空，只在 `workflow_review/workflow_region_only` 中保存局部证据。
下一动作后必须匹配回一个已知 Stage；若连续第二次仍只能局部匹配，立即调用旧 locator，
无法定位则停止并留下补图需求。该路径不创建 Region、State 或 traversal edge。

离线三步合同中，旧 identity 只在启动时调用一次，后续三个落地各使用一个 workflow
turn；第二和第三个安全点击直接使用前一 turn 的当前帧定位。没有方向性
`desired_outcome` 时，独立 ref/final verifier 不再重复调用；方向性结果仍须报告可见
`observed_outcome` 并沿用原 verifier。该结果只证明离线控制流与 Prompt 投影，尚未进行
新的 VM/Luna live 成本验收。

## 前置资源与解锁

优先尝试到达 ref entry surface；若该 surface 因缺资源不可达但 ref 有 runtime requirement，则先在当前可见表面处理前置，再从真实落点重规划。

- resource：截图可见已有实例时绑定并零 setup；否则选择可行 recipe 中 `estimated_gui_actions` 最小者。创建资源必须有 cleanup，否则在执行前拒绝。
- state：检查现状；缺失时按声明 recipe 设置并截图复查。
- authorization：沙箱允许无密码系统授权；具体 Unlock 仍必须实时 grounding、执行并复查。
- login：应用账号登录以及带 sign-in/login 语义的通用 setup 永不自动执行，返回 `needs_user` 与零 credential action。M13 还有第二道 ref gate：即使 atom 漏写 `requires.kind=login`，只要 capability name 或 `execution_recipe` 明确包含 sign-in/login 语义，也在 app capability grounding 前返回 `needs_user` 与 0 GUI 动作。

运行时只跟踪本轮创建的资源。episode 结束时按创建逆序幂等 cleanup；已存在并绑定的用户资源不删除；部分 cleanup 失败可从未完成动作继续。setup/cleanup 的每个真实 GUI primitive 都进入轨迹并计数。

## 单步事务与 fail-closed

```text
capture before
  → identify current function surface
  → verify expected source
  → live ground/relocate target
  → execute desktop/Android GUI action
  → settle
  → identify arrived surface
  → verify graph landing or capability success
  → commit trajectory step
```

grounding 缺失、source 不符、unknown landing、错误 target、VLM parse/transport failure 或 `complete=false` 都不提交完成。图路由每一跳都用动作后的新截图独立识别实际落点；偏航时记录 predicted/actual/进入上下文、修正地图并从实际落点重规划，最多 `max_replans`。该次 instruction 可以继续走完以发现同一路径上的更多失配，但整条轨迹标记为 `route_tainted`，结束后不进入数据集；执行器默认从修正后的地图完整重采一次，只返回无失配轨迹，连续失配超过 `max_route_correction_retries` 时失败关闭。verified 与共享预测边不增加额外信任权重。capability 有 `execution_recipe` 时，每个 semantic step 都重新 capture、绑定参数槽、实时 ground、执行和 settle；某一步失败立即停止后续步骤，并把已经执行的 primitive 数量/截图作为未提交轨迹保留。每个 capability ref 通过后，整条 instruction 还要做一次截图 VLM final verification。

独立能力图 ref 的 `target_node` 显式为空：动作后仍必须识别出一个真实 State，
但状态设置或对象创建可以落到同一 Page 的新 Variant，而不被错误要求返回源 State。
此时提交由该能力的 effects/success predicate 验收决定。历史 sidecar ref 仍使用
其声明的 `target_node`，因此该规则不会放宽普通图路由或旧 capability 的落点
检查。

## 统一桌面/移动视觉动作边界

`EngineVisualAdapter` 不读取 A11y，也不直接重放 graph 中的历史坐标。graph edge、capability 和 prerequisite pointer action 都必须通过 `engine._live_center_for()` 重新定位，落点若超出源 `region_bbox` 则拒绝。

当前标准动作：

- pointer：`CLICK`, `RIGHT_CLICK/RIGHT_SINGLE`, `DOUBLE_CLICK`, `LONG_PRESS`；
- semantic input：`TYPE/TYPING/input_text` 带 selector 时，先在 fresh screenshot 上按稳定
  Element UID 或 label+formal Region 定位 input，再生成 `CLICK + TYPE`；历史 focus 和坐标均不复用；
- semantic drag：`DRAG`（兼容 `DRAG_DROP/DRAG_AND_DROP`），必须同时给 `source_selector` 与 `target_selector`；二者在同一当前帧独立实时 relocation，起点/终点各自必须落在所属 region bbox；
- direct：没有 selector 的兼容 `TYPE`, `PRESS`, `HOTKEY`, `SCROLL`, `BACK`；
- Android：另支持 `HOME`；
- desktop：`BACK → Alt+Left`，方向 scroll 转为 wheel `dy`。

没有显式 recipe 的文本 capability 可回退 ground 为 `CLICK + TYPE`，实际两步都计入
`gui_action_count`。有 `execution_recipe` 时 selector/参数槽（`{{slot_name}}`）逐步
绑定；autonomous induction 只有在至少两个不同真实值都精确进入原动作
selector/parameters（或 Android `input_text.text`）后才生成该槽，效果说明中的孤立绑定不能授权动作。多个参数还
必须整体命中能力图中的一个 `parameter_examples`；分别落在各自 domain 但从未共同
出现的组合会在 GUI 启动前被拒绝。recipe 中持久化的 x/y/bbox 等 geometry 会被剔除，
pointer 仍只接受实时 element id/label/region grounding。DRAG 也忽略 recipe 坐标，
只从当前可见 source/target 元素生成 `x1/y1/x2/y2`。prerequisite recipe 使用同一
primitive grounder。当前未覆盖自由轨迹、多指手势、不可见拖拽目标以及所有应用专属复合控件。

Autonomous recipe 中的 `region=full_screen` 只表示本步不限制 formal Region，grounder
把它作为全屏语义通配符；它不是一个 Region 身份，也不能携带或恢复历史 bbox。其他
Region 名称/ID 仍按当前截图中的正式 Region 精确约束。

动态 recipe 可以在产生对象的步骤写 `bind_result: "<name>"`，随后在 selector 中写
`region_ref: "<name>"`。M13 在前一步 settle 并识别真实落地后，只从该目标 State 的
verified `region_transition.result_binding` 解析 Region 集合；后续实时 grounding
被限制在该集合。单个 Region 直接绑定，多 Region 候选集只有在目标控件仍唯一时才能
继续；缺少绑定、来源 State 不符或目标不唯一都会失败关闭。因此“创建闹钟后设置铃声”
可指向本轮刚创建对象的 Region，而不是按名称任选一个已有闹钟。

## 输出

```text
collections/<platform>/<date>/<collection_app>/
  manifest.json
  episodes/<instruction_id>_<uid>/
    meta.json
    trajectory.json
    screenshots/
      stepNNN_before.png
      stepNNN_after.png
```

`meta.schema_version="m13.visual_collection.v1"`。meta 保存 apps、final status/success、动作/cleanup/app-switch 计数、完成/失败 refs、final verification 与错误。trajectory 保存 refs/ref results/graph provenance，并为每步保存 kind、app/ref、动作步数、commit、before/after frame、context/arrived node、action spec、grounding 和 verification/evidence。dynamic recipe grounding 还保留 `primitive_actions/recipe_groundings/gui_action_count`；失败时保留 `failed_recipe_index/failure_reason`。没有 A11y 快照和旧 `reverse_*` 字段。

## Directional outcomes without Page/Variant

State-setting refs may carry an explicit `desired_outcome` boolean, string, or
number. Instruction generation asks the model for a per-ref
`desired_outcomes` map and serializes the selected value into the matching ref;
pure navigation refs omit it. Federated/manual composition may provide the
same field directly. This contract does not require a Page/Variant identity.

When `desired_outcome` is present, screenshot verification must return the
visible `observed_outcome` and may return `changed`. A missing observed value or
a value that disagrees with the requested outcome fails the capability closed.
The executor records both values under the capability step's `effect`, runs the
deterministic agent-trajectory audit on capability or explicitly auditable
steps, and exposes `agent_audit` in the in-memory result. Ordinary graph-route
attempts are not audited merely because a successful replan left an earlier
attempt uncommitted.

`CollectionWriter` persists `effect` on each applicable step and writes
`agent_audit` into both `meta.json` and `trajectory.json`. The observed value is
still a screenshot/VLM judgment unless a caller supplies a stronger structured
observer; offline tests do not establish real-device visual accuracy.

## 跨应用边界

应用图始终独立。联邦 instruction 的 ref 用 `app_id` 指向对应图；切 app step 只记录逻辑
boundary provenance，不在 A 图末节点与 B 图初节点之间伪造状态边。当前只实现一个窄的
单标量桥：来源 ref 显式声明 `output_slot`，仍须通过 fresh screenshot 的 ref verifier；
`complete=true` 时必须同时返回非空 scalar `query_result`，框架才写入本轮 blackboard。
全部声明的 output slot 在本轮开始时即保留；prerequisite binding 不能预写或覆盖这些槽位，
只有对应 query ref verifier 可以写入。
目标 ref 以唯一 `{from_slot: "<slot>"}` 参数、显式 `depends_on` 来源 ref 后使用该值。
capability-graph hydration 只对“唯一 string 参数、至少两个真实 observed values、recipe 实际
使用该槽”的能力开放；执行前再次检查 producer、依赖、类型和值。普通结构化参数保持原合同。
这不等于通用 observable dataflow：不支持对象、数组、表达式、隐式依赖或自动跨应用任务合成；
当前只有离线合同验证，首个短信到文档的 live pilot 尚未完成。

## 2026-07-11 离线验证

```powershell
python -B tools/test_prerequisite_runtime.py
python -B tools/test_visual_prerequisite_agent.py
python -B tools/test_live_visual_collection.py
python -B tools/test_visual_collection_writer.py
python -B tools/test_run_visual_collection_cli.py
python -m pytest -q tools/test_federated_capability_catalog.py tools/test_visual_collection_executor.py --basetemp _scratch/pytest_visual_collection
```

全部通过，其中 prerequisite runtime 为 11 tests、visual prerequisite agent 为 12 tests、pytest catalog/executor 合并批次为 18 passed。`test_live_visual_collection.py` 的 “live” 指 traversal-backed adapter 契约测试，仍使用离线 stub，不是 VMware/Android 真机。

## 2026-08-25 Desktop Clock Luna live smoke

本地 VMware `init_state` 上使用 `gpt-5.6-luna` 执行能力
`cap_99175034fa20d269`（click Start button），从 fresh World 空状态出发。M13 从能力的
两个 `entry_surfaces` 选择更近的 s3，而不是主记录 s10；真实轨迹为：

1. s1 World -> s2 Alarms，点击 Alarms；
2. s2 Alarms -> s3 Stopwatch，点击 Stopwatch；
3. s3 -> s11，点击 Start。

episode 位于
`artifacts/clock_luna_collection_48e90d85/collections/desktop/20260825/clocks/episodes/CAP002_start_stopwatch_luna_07/`。
`meta.json` 为 `complete/success=true/3 steps`；逐张检查的最终截图显示计时
`00:00:38.8`、Pause 和可用 Lap。该 run 的角色 ledger 记录 17 次调用、266.266 秒
模型延迟；`_codex_gui_debug.jsonl` 还包含 4 次页内 State locator 与 2 次 ref/final
completion 直调，因此实际为 23 次 Luna 调用。当前 ledger 对这些直调不完备，且 Page
候选仍会先做一次代表图对比；本结果证明链路可运行，不证明调用成本已经最优。未运行
Android M13 或完整框架 certification gate。

## 首批 live 验收

1. Desktop Settings：开关前后功能面、系统 Unlock、复杂网络配置；
2. Desktop VS Code：侧栏/命令面板/设置、键盘动作与复杂控件；
3. Mobile Clock/Alarm：空列表绑定/创建闹钟、详情页与 cleanup；
4. Mobile Calendar：创建资源、详情编辑、日期/表单；
5. Mobile Todo：空/已有任务、创建/查看详情；
6. 每个 app 同时检查 graph quality report、最少 GUI 操作计数、偏航重规划、VLM ref/final verdict 和 episode 截图可解释性。
