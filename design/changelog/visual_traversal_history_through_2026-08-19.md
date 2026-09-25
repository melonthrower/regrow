# 视觉遍历模块历史快照（截至 2026-08-19）

最后更新：2026-08-17

本文保留精简前的完整文档，只用于追溯旧设计、实验和回归原因，不属于默认阅读集合。
当前合同见 `design/modules/visual_traversal.md`；更早的快照见
`design/changelog/visual_traversal_history_through_2026-07-19.md`。

## 1. 模块职责

视觉遍历模块把截图转成可验证的 Page@Variant 图，并在安全条件下持续发现页面：

```text
bootstrap/register
  -> keep the screenshot/VLM-confirmed cursor identity
  -> observe every Region on the active surface
  -> Qwen chooses one current entry from the full screenshot and framework feedback
  -> live rebind and dispatch
  -> register actual landing
  -> verify/commit or quarantine/recover
  -> Qwen chooses the next known interface -> Router realizes that choice
  -> finish and emit completion evidence
```

它不负责旧 A11y 图遍历、业务领域 prerequisite 推断或 M13 多能力任务规划。

### 1.1 当前遍历 Prompt 合同

以下合同取代本文后续仍可能出现的旧 Region inventory、Explorer coverage 和
Transition verdict 描述：

本节和下述 guided 状态机只描述默认 semantic traversal；独立 `--autonomous-agent` 的当前合同见
§4.1，二者互不调用。

- Page map 用一次完整截图调用同时选择唯一 active interaction surface 并返回其中的候选
  Region 目录；不再追加 `semantic_active_region_filter`。
- Page pairwise judge 先检查当前截图中的应用外临时前景内容；命中时返回
  `is_interruption=true + same_page=null`，框架调用现有 InterruptionDismisser 后重新截图并
  重做 Page Identity。只有 `is_interruption=false` 时才返回 `same_page=true|false`；true
  直接复用已登记 State，不再进入 Region 对齐或自动创建 Variant。
- Region locator 保持独立。每次观察或执行都以最新完整截图重新定位 Region bbox；
  Region crop 供 Region-local 使用；Explorer 与 Grounder 都只看最新完整截图。
- Region-local 只返回
  `region_id + function_entries[{entry_id,target}]`。合法空数组即可把
  `region_observation` 标为 `complete`，它只表示入口观察完成。
- 可滚动 Region 的完整长图切片复用同一个 Region-local Prompt、VLM role 和
  `function_entries` schema；长图只改变输入图像范围，不引入另一套控件语义合同。
- 当前 active surface 的待观察 Region 全部完成 Region-local 观察后，Explorer 接收最新完整截图、
  跨 Region 唯一的 `function_entries`、区域描述、先前动作结果和框架失败反馈；可自由返回任一
  `selected_entry_id` 或带理由的 null。框架把有效入口转换为当前平台 CLICK，再独立核验与执行。
- Grounder 保留 `TARGET_GROUNDING_PROMPT`，始终输入最新完整截图并输出相对完整截图的
  `0..1000` 坐标；正式 Region-lazy 路径的语义输入只使用所选 `function_entry.target`，最新 Region
  bbox 只作为整图坐标系中的近似搜索提示。合法几何随后必须由独立 Click Reviewer
  对照未标注完整原图与候选点击点居中的干净局部图确认；明确拒绝时只允许带原因强制重新定位并复核一次。
- Transition Observer 只接收动作前后完整截图和本次可见 `target`，返回最终
  `target + observed_outcome + relation_to_target(related|unrelated|no_relevant_change|uncertain)`；
  名称准确或证据不足时原样返回输入 target，只有截图明确证明原名称错误时才修正；
  不再接收 `control_purpose/expected_immediate_effect`，也不输出七类变化或
  `matched/mismatched`。
- Reverse Edge Explorer 在 verified `A→B` 后、缺少上下文兼容 verified 直接 `B→A` 时，
  用同一个中文两图 Prompt 从“可见 CLICK 目标 / 当前平台返回动作 / null”中选择一个。
  它不读取完整 element candidate 表，不输出 `choice_id`、坐标、`NO_ACTION/DEFER` 或成功判断。
- Region-local 不创建 capability。功能组合发现位于 `completion.json` 之后的可选
  capability enrichment；真实动作、结果验证、恢复和 `verified` 晋升属于采集/M13。

## 2. 当前文件边界

| 位置 | 当前职责 |
|---|---|
| `visual_engine.py` | 依赖装配、兼容 wrapper、共享运行账本和少量编排接口 |
| `runtime/runner.py` | 主状态机协调器 |
| `runtime/autonomous_agent.py` | 主回合共享 adapter、无状态 specialist 调用与显式 Codex CLI 调试 transport；不读取 runtime host |
| `runtime/autonomous_action_execution.py` | 严格动作调用转内部 decision、当前截图坐标转平台 primitive、动作前重复检查及 Region/Entry/Element 来源绑定、Attempt 前后帧、首个动作后 assessment 冻结/同帧冲突拒绝，以及 fresh observation 后的 landing/effect/Entry/route 结算；不调用 Qwen、Reviewer 或 `env.step` |
| `runtime/autonomous_completion.py` | ledger completion gaps、同页 Entry 重查、FINISH 不可达证据校验/退役及接受/拒绝、连续无进展拒绝后的任务暂停/运行停止；不调用 Qwen、Reviewer 或 GUI |
| `runtime/autonomous_context.py` | runtime 账本到 Qwen 的 Page/Region/Entry/probe/最近动作上下文投影；不写图、不调用模型或执行动作 |
| `runtime/autonomous_entry_commit.py` | 已提交 Region 上的 Entry 候选 staging、Reviewer 结果校验、Entry/coverage 提交与回滚；不调用模型或执行 GUI |
| `runtime/autonomous_entry_review.py` | Entry Reviewer 同帧延期记录、临时纠错工具、精确单入口争议复核与显式 Entry 等价结果复用；可调用 Entry specialist，但不删除正式图事实 |
| `runtime/autonomous_loop.py` | 独立 autonomous 截图循环、adapter/runtime 装配、Qwen/Reviewer 阶段编排与 GUI 动作投递 |
| `runtime/autonomous_map.py` | Qwen 已复核的自然 Page/Variant 地图、关系边、代表截图与 route hint；不拥有 Prompt 或动作执行 |
| `runtime/autonomous_page_commit.py` | 已复核 Page update 到正式 Region/Entry/自然地图账本的逐项提交与回滚；不调用模型或执行 GUI |
| `runtime/autonomous_page_update.py` | Page Identity pending/反馈/接受编排、`no_visible_change` 与动作来源 Page/material Variant 的身份矛盾拒绝，以及 Page update 字段规范化、纠错账本和 Region Reviewer 三轮讨论/裁决；可调用 Page/Region specialist，但不执行 GUI |
| `runtime/autonomous_prompt.py` | Qwen 主 Prompt 组装、当前任务历史压缩和 Reviewer/拒绝事实的自然语言投影 |
| `runtime/autonomous_protocol.py` | autonomous 阶段 Prompt、Qwen 工具目录与 pending Page Identity 合同 |
| `runtime/autonomous_qwen.py` | 正式 DashScope-compatible Qwen transport；复用共享 specialist，默认生产后端 |
| `runtime/autonomous_recovery.py` | Android/桌面目标应用前景检查、外部语义终点/无数据重启及临时干扰三轮 specialist 策略；绑定恢复决策但不直接执行 pointer 动作 |
| `runtime/autonomous_runtime.py` | autonomous 运行宿主、Page/Variant State 登记、graph/各 sidecar checkpoint 与恢复、显式 Agent 等价推断边投影及 Local HTML 单目标边验收状态；不调用 Qwen 或执行 GUI |
| `runtime/autonomous_scope_state.py` | 真实观察到的页面交互模式、临时选择成员、模式转换和跨页面应用级状态的最小持久账本；不枚举应用或内容类别 |
| `runtime/autonomous_scheduling.py` | Page survey、Entry exploration 的单任务调度、动态工具目录、精确重复门和阶段推进后的同轮旧动作冻结；不调用 Qwen、Reviewer 或 GUI |
| `runtime/autonomous_schema.py` | Qwen 主回合严格回复 Schema 与按 phase 缩减的 response-format 校验；无运行时状态 |
| `runtime/autonomous_turn.py` | Qwen 主回合值对象、JSON 解析/规范化、共享自然名称 key 与稳定 ExplorationTask key；无图写入 |
| `runtime/autonomous_action_tools.py` / `autonomous_entry_tools.py` / `autonomous_region_tools.py` | autonomous 动作参数校验及 Reviewer 合同、正式 Entry 账本、正式 Region 账本/复核与当前 State 临时几何中的 point 归属 |
| `runtime/bootstrap.py` | 初始页面、resume 和启动登记 |
| `runtime/scheduling.py` | frontier 选择、目标页面调度和 Router 接入 |
| `runtime/execution.py` | 点击前实时绑定、attempt 开始和动作投递 |
| `runtime/landing.py` | 落地登记、效果判断、commit/quarantine/recovery |
| `runtime/recovery.py` | 系统前景确认、启动/Page Identity interruption 有界清理、一次 Back/Esc、有界 relaunch、off-app 动作结算和路由后的恢复 |
| `runtime/region_observation.py` | 新 State 的 Region-only 登记、单 Region 按需观察与重试 |
| `navigation/frontier.py` | 可执行候选过滤和覆盖账本策略 |
| `navigation/router.py` | verified graph 规划、逐跳执行、Back、重规划和 hard reset |
| `state/registration.py` | 新观察登记、Page/Variant 与 capability 更新 |
| `state/resolver.py` | 普通落地与 Router 共用的 KNOWN/NEW/UNRESOLVED 身份入口，以及 guided 动作前当前帧到既有 State 的只读解析；不登记 State |
| `state/map_guided.py` | 点击后有界候选、模板证据和 VLM 页面选择 |
| `state/identity.py` / `state/matching.py` | Variant、元素和观察身份辅助 |
| `stateful.py` | `state_key`/inverse 匹配，以及从持久 transition evidence 重建未闭合 probe 与 active mutation 的纯语义解析 |
| `grounding/` | 感知、滚动、长图、Region 与 below-fold 定位 |
| `live_targeting.py` | 当前帧目标重绑定、Region/overlay 几何门和 locator 合同验收 |
| `visual_resume.py` | schema v3 到显式 collaborator snapshot 的原子重建；Engine 只在完整构建后统一发布引用 |

更细的维护路径见 `design/modules/visual_traversal_file_map.md`。

### 2.1 身份优先与 Region-lazy 感知

正式 semantic 路径采用以下顺序：

1. `state/resolver.py::IdentityResolver` 先对当前完整截图给出
   `known | new | unresolved`。普通 registration 与 Router 共用同一实例和同一
   Page pairwise judge；身份调用不依赖整页控件观察。
   guided 调度需要保存动作前 State 时，复用该模块的
   `identify_existing_frame`；它只读取严格截图、当前 Region 证据和已有 Registry，
   不写图、不登记 State，也不允许元素文字独立决定旧 State。Engine 仅保留薄 wrapper。
2. `known` 复用 State 的 `semantic_blocks`、`region_observation` 和 elements，
   不重新枚举整页控件。pairwise judge 的 `same_page=true` 直接进入本分支；pHash、
   像素差、Region 数量和 Page map 都不再二次判定。当前截图仍作为 Observer 和单目标
   Grounder 的实时证据。
   2026-08-01 的 Calendar 实时运行曾把共享月历背景上的“日历管理下拉菜单”和“应用主菜单”判为
   `same_page`，导致后续在错误菜单里重绑 `Synchronize Calendars`。两图裁判现直接复用共享“当前
   操作界面”定义，并明确只比较两个前景操作界面本身；共同背景不能单独作为同页依据。原错误截图
   的真实模型回放已连续 3 次返回 `same_page=false`。重新部署后的 Calendar 运行在到达该菜单场景前
   因另一项 Grounder crop 坐标换算错误停止，所以仍没有这组菜单的实时验收。
3. `new` 由 `runtime/region_observation.py::register_region_map()` 调用一次 Page map，
   同时选择 active interaction surface 并登记其 Region 目录；不追加二次筛选。
   无效或空 Page map 结果失败关闭，由登记层既有三次预算重试。
   Region 的控件清单初始为空，`observation_status=pending`。
4. 主循环在做下一步选择前依次观察当前 active surface 的全部 pending Region：最新完整截图定位
   Region，`context_crop` 请求只列该 Region 的 `function_entries`。全部 Region 的入口进入同一个
   source-local frontier，Explorer 从最新完整截图和跨 Region 入口表中自主选择一个。
5. 单个 Region 失败最多三次；失败不会清空其他 Region，也不会生成“无控件”结论。
   所有其他工作耗尽后，只要仍有 unresolved Region 就以
   `region_observation_unresolved` 结束。

Page Identity 判定为同页后不会重新运行 Page map，也不会因 Region-local 后续多发现一个
区块而创建新 State。Region-local 只更新已知 State 的观察账本。此后某个目标在当前截图中
定位失败时，直接累计该来源 State 上该目标的普通有界失败次数；不会再次登记同一页面来清空
这次失败。

旧整页 `semantic_inventory` 保留为显式环境回退与 fixture 兼容路径，不再是正式
semantic traversal 的默认首屏/落地感知合同。唯一例外是图中尚无节点的新遍历：bootstrap 在
根页面登记前执行一次有界 interruption 检测，并复用现有 InterruptionDismisser 关闭后重新截图；
有界观察/等待/点击循环属于 `runtime/recovery.py::dismiss_interruptions`，Engine 仅保留调用接口。
已有节点的 resume 与 hard reset 不重复这次启动检测，继续由正常 Page Identity 处理当前截图。

## 3. 主状态机

`runtime.runner.run_traversal()` 是当前唯一主循环：

1. `bootstrap_traversal` 在空图新遍历中先清除 interruption，再登记根页面；已有节点时直接进入
   resume 身份流程。未知/off-app 画面不能成为恢复起点。
2. 每轮沿用最近一次实时 registration 已确认的 cursor；不再用 Region/按钮集合二次改判页面。
3. 当前 active surface 仍有待观察 Region 时，每轮定位并观察一个 Region，直到全部 Region 都有
   complete 或 unresolved 结论，再把整页已观察入口交给 Explorer；持续失败最多三次。
4. `_unvisited_candidates` 从当前 Page@Variant 中去掉已有 landing-verified CLICK 或已终止项，
   生成 source-local 待选入口；Explorer 同时查看当前 active surface 的全部 Region，可选择任一
   `selected_entry_id`，不按列表顺序执行。
5. 当前页没有候选时，Explorer 查看所有仍有 Region/控件工作的已知页面及既有 route 反馈，选择
   下一处页面；Router 使用 verified 图执行该选择。只有没有 route chooser 的 fixture/兼容调用才
   使用原 nearest 选择。
6. `plan_candidate` 建立候选上下文和 stateful probe/restore 约束，但不触碰环境。
7. `execute_candidate` 在当前帧重新定位目标，先写 attempted，再调用环境动作。
8. `process_landing` 登记真实落地，判断效果并 commit，或 quarantine 后恢复源页面。
9. 达到预算、off-app 上限、恢复失败、Region/滚动不完整或 frontier 耗尽时停止。
10. `finish_traversal` 保存图和证据；CLI 另行生成 `completion.json`。

`frontier_empty` 只表示调度器没有更多可执行候选，不能单独解释为 certified。

## 4. Frontier 与 Explorer 合同

本节以 §1.1 为准。旧整页回退的 elements/coverage 描述只适用于
`GUIWALK_REGION_LAZY_INVENTORY=0`，不属于正式 Region-lazy Explorer 输入。

- 正式 Region Inventory 只发现所选 Region 中语义可区分、当前可见的入口。框架在调用 Explorer
  前完成当前 active surface 的全部 Region 观察，并过滤已有 source-local landing-verified CLICK
  或确定终态；未验证的入口仍保持 pending。
- Explorer 接收最新完整截图，以及与当前页面稳定目标相连的事实记录：可见目标、所在 Region、
  `exploration_status`、实际 `attempts`、已观察结果和 `problems`。仍可选择的目标带 prompt-local
  `eN`；已完成、仅观察或确定不可选的目标也保留在输入中，但不带 `eN`。这样模型能利用“哪里已经
  探索、哪里实际失败”的记录，又不能重新选择已结清目标。持久 Region、element、State ID 和框架
  猜测的按钮效果不暴露给模型；每个目标最多给出最近三次实际结果，且不重复附带动作 selector，
  记录顺序也不表示执行顺序。
- Explorer 可选择任意一个输入中的 `selected_entry_id`，也可返回带直接可见理由的 null。这个选择只
  冻结“探索 X”目标，不直接声明动作成功、页面完成、`covered` 或 `semantic_only`；实际操作由同一
  Explorer 后端进入下述目标任务后决定。
- 回复不是合法 JSON、缺少字段、引用未知 `eN`，或首次在仍有候选时返回 null，框架会把具体问题
  反馈给同一 Explorer 模型，用同一张最新截图纠正一次。第二次仍无有效选择时，框架不代选、不伪造覆盖，
  而是暂缓当前页面的这些 Region 并继续其他页面；之后重试仍失败则保留未完成结果并以
  `explorer_unavailable` 停止。
- 动作落地后，Transition Observer 对前后完整截图检查真实结果和目标名称。定位、Reviewer、环境
  投递与落点失败都会进入该入口的后续反馈，供 Qwen 判断是否重试或换入口。
- 当前页面没有本地候选后，Explorer 接收所有仍有待办的已知页面及其人类可读名称、待办入口/Region
  和已有 route 失败，选择 prompt-local `pN`；Router 只负责沿已验证图执行这个方向并记录真实落点。
  只有没有 route chooser 的确定性 fixture/兼容调用才回退原 nearest 选择。
- stateful 事务恢复、安全 veto、预算、off-app 和失败关闭仍由框架强制执行；未闭合 stateful 事务的
  inverse CLICK 是安全恢复，不交给 Explorer。正常返回入口与其他入口一样由 Explorer 模型决定。
- Explorer 只在框架给定的单一目标任务内直接操作环境；全局待办、Region 去重、Router、落点核验和
  完成证据仍由框架管理。
- 每次选择把目标事实记录、实际 Prompt、原始回复和后端运行信息写入 traversal debug 记录。
  `--explorer_codex_model <model>` 只把以上 Explorer 判断交给本机 Codex CLI 指定模型；其余角色和
  运行合同不变，临时输入只保存在本次结果目录下。
- Explorer 按上述合同选择一个 `entry_id` 后，框架启动一个 runtime-only 的短期“探索 X”任务，
  不立刻强制模型点击 X。每一轮输入包含最新完整截图、目标最初所在 Page/Region、压缩页面图、到目标
  来源页的 verified route，以及该任务启动后已经执行的动作和真实结果；不把 X 的旧 attempts 当作
  任务记忆。压缩图按稳定 Page 合并 State，只列页面、少量 Region 角色、verified 页面关系和下一跳，
  不列完整按钮、历史截图或原始 ActionEdge。
- 任务模型先判断当前截图对应已知 `pN`、新页面还是不确定，再返回直接的安全
  `CLICK/SCROLL/BACK/WAIT`（CLICK 自带整图 `point_1000`），或 `CALL_TOOL/FINISH/DEFER`。当前轻量
  工具由 `runtime/agent_tools.py` 的声明式 `ToolSpec` 注册表统一描述和分派：`recall_page` 读取指定
  Page 的 Region/控件记忆，
  `find_route` 查询 verified 路线但不自动执行，`inspect_region` 复用 Region-local 定位与入口观察。
  每项声明同时给出参数 schema、`evidence_mode` 与副作用类型；dispatcher 按调用准备必要的当前整图、
  前后图或 Region 裁剪，原始图片不写回 Prompt/任务历史。工具以统一 `ToolResult` 返回状态、结构化
  数据和账本变化标记，稳定 ID 分配、动作证据和 Page/Edge 图写入不交给模型。任务内直接动作跳过
  独立 Grounder 与 Click Reviewer；execution、动作账本、fresh landing、Page Identity、Transition
  Observer、Router 和 completion 仍沿现有框架执行。任务不再使用固定六步局部预算；完整历史保留，
  Prompt 使用最近十二项、累计进展和重复事实。Agent 每轮判断 `loop_assessment`；同一客观无进展循环
  第一次只提示模型，提示后仍执行同一循环才由框架暂缓。目标元素本身已有
  `transitioned_consistent + landing_verified=true` 后的 defer 按完成结案，也允许一次直接返回/关闭，
  验证回到目标来源 Page 后自动结束，不再
  追加 `element_task_deferred`，而缺少该框架事实的 defer 仍按暂缓处理。Router 的实际移动也追加为
  任务上下文。角色无效、回复非法或动作不安全时 fail closed，不再回退原固定
  CLICK；不新增 Page/Region/ActionEdge schema，也不改变 completion 合同。
- 每条直接 Agent 动作在 ActionAttempt evidence 中保存 `element_agent_direct_action`、模型动作目标、
  动作类型和实际投递像素点，便于把相邻控件误点与模型声称的目标对照；这不改变动作或完成判定。
- route/中间动作使用的 observation-local element carrier 同时提供旧提交链要求的 `id/uid`；它只
  用于本次直接动作的落地与失败账本，不写入稳定按钮 inventory。

### 4.1 独立 Qwen API 自主遍历

- `--autonomous-agent` 默认直接使用仓库现有 DashScope-compatible Qwen API 和 `qwen3.7-plus`，不进入
  guided Explorer/Region/identity/grounding/routing 主链，也不增加第二个功能开关。运行期间框架始终派发一个
  `exploration_task`，只有 `survey_page` 与 `explore_entry` 两类。`survey_page` 负责 Page/Region 身份、区块内
  观察/滚动、不同质入口建账及 Entry Review；它不得执行已登记入口的功能。每个审核通过的入口创建一条归属其
  Page/Region occurrence 的持久 `explore_entry` 子任务，路线、定位、滚动、等待、尝试和结果验证都属于这条精确任务，
  不会在同一区块内顺路执行其他功能按钮。Region 的 `coverage_complete` 与 accepted Entry audit 表示区块调查完成；
  所有子入口都终态后框架才推导区块探索关闭，任何未获 verified/inferred 结果的终态使其为 partial。未完成 owner
  Region 调查或 Entry Review 是入口任务的硬门槛：目标可早期建账，但不会进入可执行候选。调度先按 verified StateGraph
  最短跳数；同一 Page 的每个未完成 Region 分别成为候选，一个无 verified 路线的隐藏 Region 不会遮住当前 State 可见的
  sibling Region；同距离时仅当前 Page 的 Region 调查优先于 ready Entry，再按持久创建顺序，远处未调查 Region 不形成全局
  屏障。旧 Region probe progress 继续保存已结算操作证据及同质参数重复防护，但不再产生自由执行多个内部操作的任务。
  当精确入口因当前截图的可见阻断而延后到另一个精确入口时，前置入口的实际结算不直接证明目标已解锁：真实
  verified 结果、意外的真实结果或真实无可见变化结果只会把目标改为 `recheck_after_prerequisite`。该目标先于普通
  ready 任务恢复，并沿已验证路线返回；同一主 Agent 在最新截图上重新定位和尝试目标。等价 inferred 只复用语义，
  不能当作当前 State 的前置效果；安全阻断、不可达或其他终态跳过会
  形成可追溯的根前置 gap 和受影响目标 gap。目标在一次重新检查后可改指向另一个精确前置，但不能反复指向同一个
  已处理前置。该依赖/重新检查事实进入 checkpoint；resume 不从旧证据猜测条件已经满足。
  主 Agent继续负责观察、页面/浮层理解、实际路线、中间动作、干扰恢复、循环判断和完成提议；该任务复用现有主 Agent、
  Click Reviewer 和动作结算，不新增 specialist 调用。stateless specialist 仍只在 Page Identity、Region、Entry、
  Interruption Handler 或 Click Reviewer 的原有局部边界调用。`--autonomous-backend codex_cli` 仅保留为显式调试路径，
  默认和本轮验证都不调用 Luna。
- Qwen 提交的 Page/Variant、Region/Entry、ActionAttempt 和 effect 先写 raw graph 与
  sidecar。遍历停止后入口会用同一 evidence-only compiler 自动写 `annotated_graph.json` 和
  `capability_graph.json`。compiler 会重新 `StateGraph.load` raw graph、投影
  exact State occurrences、保存并重载 annotated graph，再按其精确字节绑定 digest；
  partial 遍历同样编译当前证据，遍历 gap 与 bundle 编译失败分开报告；任一未闭合都会让 CLI 返回非零。该步骤不调用 Qwen，也不允许
  外部 effect batch 补写语义。
- 独立 Entry Reviewer 只返回一份穷尽的 `independent_entries`：既包含仍成立的原始候选，也包含待审正式 Region
  中页面调查漏掉的新可见入口。runtime 用它与原候选的交集/差集推导保留项和补项，不再要求模型把同一类有效入口
  拆进 `independent_entries` 与 `missed_entries` 两个数组。补项必须与同一 Region 的已有候选明确不同；部分遮挡、
  别名、另一种描述或 `leftmost/rightmost` 等纯位置称呼不能把已有候选重新登记为新 entry。看不清，或有探索价值但因当前可见前置状态暂不可执行的原候选进入
  `deferred_entries`；若遮挡使某个已提交 Region 无法检查是否漏掉未被
  主 Agent 提名的主要入口，则用 `deferred_regions` 保持整个 Region incomplete。明确延期会按 Page/Region 保存当前
  frame id 和证据代；同一证据代不再派发该 Region，只有已验证的界面变化产生新证据代后才复查。保留已有候选仍使用其
  原始 Region/target 对，真实明确漏项继续允许补入。`deferred_regions` 仅能影响本轮
  `coverage_audit_regions`；范围外的保守延期会留下 normalization 轨迹后被忽略，既不改写账本，也不触发相同
  Reviewer 回复的重试循环。请求中的正式区域、候选、`known_entries` 和 `shared_region_entries` 均只包含
  `coverage_audit_regions` 内的数据，完整截图仍用于视觉核对。入口复核器若仍回显其他区域的入口，框架拒绝
  该响应；下一次反馈会点名本轮区域、越界区域和目标，以及非法等价编号的真实所属区域和未出现在共享入口
  清单中的原因，不用通用纠正，也不静默忽略越界已有入口。应用窗口标题栏或
  工具栏中只有最小化、最大化/还原和关闭三类窗口管理控件排除；其他可见可交互控件都必须进入候选检查，
  但不自动保留。Reviewer 只保留服务于应用主要用途、会展开或切换独立功能表面的入口；纯说明、参考或
  非功能元信息不进入功能图。未知容器可先保留，展开后的分支再按该边界裁决。
  当前待审区块若已映射到跨页共享 `region_ref`，请求还包含该区块中本轮前已有的
  `shared_region_entries`。每组只包含当前正式区块的名称、描述和其中已有的入口；页面实例、内部区块编号和证据来源
  继续由框架保存，不重复发送。审核器可用精确 `equivalent_to_entry_id` 把当前可见候选登记为同一规范入口的
  页面状态实例；框架校验该编号来自当前共享区块。代表尚未验证时只共享原 `explore_entry` 任务，
  代表验证后页面实例才同步为推断覆盖；这不会把区块相同或文本相似当作入口相同，也不增加模型调用。
- Local HTML fresh run 可选
  `--autonomous_test_target_edge 'SOURCE_PAGE::VISIBLE_TARGET::EXPECTED_DESTINATION'` 做单边诊断。
  survey 仍由主 Agent 从截图发现 Region 和入口；runtime 只把非目标 discovered/unresolved entry 设为
  本轮不可调度，不改变其观察状态、不伪造 attempt/verified/inferred。精确目标经真实动作验证且落点 Page
  匹配期望值后立即以 `target_edge_verified` 结束；来源 survey 完成但目标缺失或落点错误立即失败。
  scope、排除 ID、目标 entry 与落点写入 autonomous trace；这不是全遍历完成证据。
- `traversal_test_app` 的四个专用脚本默认运行完整 autonomous acceptance，而不是抽取一条目标边。
  运行后 validator 把只保存在 fixture audit 中的真实页面、控件、容器滚动与 Back 恢复，和框架保存的
  自然页面身份、Region occurrence、entry 显式等价关系及 landing-verified ActionEdge 交叉检查。
  `scroll/loop/back/region_merge` 分别要求三个独立滚动容器与隐藏入口、四页闭环及根页身份复用、
  六条直达边逐条返回并恢复滚动位置、以及三页七 occurrence 形成四个稳定语义/显式 entry 等价组。
  结果写入 `quick_acceptance.json`；模型自己提出完成或单独存在完整图均不能替代这些断言。
- 每轮主 Agent 接收最新完整截图、只有自然页面名与 `from/via/to` 联系的页面图、当前任务和任务相关的简短
  记忆。完整历史和动作证据继续写 trace；每条本轮记录在内部绑定产生它的 task 与 Page，但内部 task ID 不进入
  Prompt。Entry Reviewer 的结果在重新调度前绑定触发它的原调查任务，不会错绑到随后选中的 Entry。模型看到当前 task
  的全部模型相关记录，不再按最近条数截断；内部 observation、阶段切换、待观察动作和
  没有反馈的成功账本写入仍过滤。真实动作保留 operation、target、已有 validated arguments、结果、落点和简短原因；
  最新同 task 拒绝单独提升为纠正，旧任务历史和拒绝不会串入新任务。
  Page 路线记忆最多保留四条已知出边；Region 记忆保留覆盖/调查摘要，并按显式等价、异常结果、最近结果的顺序选取
  最多四条同区入口经验。入口任务还收到当前绑定 Page 全部正式 Entry 的自然语言历史，每项说明精确 ID、所属 Region、控件、状态及简短结果；
  `direct_action_backfill`、frame、路径和原始历史 JSON 不回灌。
  `survey_page` 只回传目标页的精简 Region ledger 和一份去重后的 `known_entries`；每项只保留 ID、名称、可选
  Region/来源页/落点/显式代表关系，供 Agent 避免重复登记或引用等价代表。`explore_entry` 回传派发入口的身份、来源、尝试次数、最近结果和已知落点，
  以及上述自然语言 Page 历史，不重复整页结构化按钮记录，并短示所属区块调查是否完成。主 Agent 若仍把精确同
  `(Region,target,control_type)` 的正式 Entry 当作新候选重复提交，runtime 在 Entry Review 前将其归一化为 no-op；
  Reviewer 将同一 known Entry 当作新漏项返回时也不重复写账，但 Region coverage 仍正常复核。旧 capability induction
  证据仍如实保存，但不再驱动遍历的额外 Region 操作复验；已结算 input 的受审核 Element UID 仍会进入
  `covered_operations`，阻止仅更换参数值的同质重复。主响应固定要求当前
  `screen`、非空顶层 `reason` 和可为空的 `action`。Page 身份轮的 `screen` 只含稳定 Page 的
  `name/identity`；下一轮 Variant `screen` 只含 material Variant 的 `name/identity/visible_predicates`；普通阶段才同时回显
  已确认的 Page 与 Variant。顶层 reason 用简短自然语言解释当前判断、阶段结论和本轮选择，保存到结构化 trace；
  框架只检查非空，不用关键词审核真值。
  复核意见不替代主 Agent 对最新截图的直接观察；若两者冲突，主 Agent 先独立说明截图事实，再点名争议对象逐项比较。
  复核器提到但截图中看不到的对象不能被复述成当前可见事实。入口复核器不能以“未显示”剔除清楚可见的候选；
  若用视觉不足解释原候选，结构化结果必须将它延期而不是删除。延期区域和候选保持待办，取得新的清晰截图后再复核，
  不能用 `omitted_regions` 删除或据此关闭覆盖。
  `identity=known` 时内部 matched Page 直接派生为 `screen.name`；主响应中的旧 `matched_page_name` 输入不再
  覆盖这项合同。Page Identity specialist 的独立候选比较和 matched 证据仍走专用结果。
  当前 turn 的内部 Page binding 不再携带恒为空的 Region 数组、恒为 `other` 的 surface kind，也不保留始终等于
  `screen.name` 的第二份 screen summary；临时 `ObservedScene` 也只承载状态 ID、截图、Page 和是否新建，不再
  保存从未被读取的 summary。Region 事实只通过独立 `page_update` 审核并写账；正式图节点摘要直接由图观察写入，
  不依赖临时 scene 字段。Page Identity commit 不会从主响应旁路提交 Region；应用内 dialog/menu 等 surface kind
  和 specialist 确认的页面摘要仍由 Page Identity 的独立证据提交。
  待结算动作只在 `PendingAction.evidence` 保存动作前截图路径；历史记录同步持有可审计路径，不再在
  `PendingAction` 顶层重复一份从未读取的 `before_path`。
  存在待结算真实 GUI 动作时要求 `previous_action` 给出
  `outcome/reason/matches_intent/failure_kind/business_effect`，并可用紧凑 `effects[]` 逐项报告已知区域、页面交互模式和应用级状态的
  `structure/state/value` 影响；`before_value/after_value` 必须是已提供的字符串，可以用 `""` 表示截图中的空值，但二者必须不同。只有结构影响令对应区域覆盖失效，其他影响只保存真实观察。旧 `visible_effect` 仅作兼容范围说明；其中 `business_effect`
  只能报告前后图都可见且能解析到正式 effect Region 的业务变化，否则为 null。存在待审提案时才要求只含
  `decision/reason` 的 `previous_tool_review`；拒绝后的完整修正依据直接写入 reason，不再维护重复的
  `correction` 字段。`page_update` 只在发现页面增量时提交；`task_progress/loop_assessment`
  不再进入响应合同。主 Agent 不能自行改写任务目标，也不再输出全局 `covered/remaining/problems` 功能清单。
- Qwen 主响应的 provider/transport 异常与模型合同错误分开处理。前者的原始异常只写 debug，给 Qwen 固定安全重试；
  后者包括非法 JSON 根对象和 `parse_turn` 已控制的字段、阶段、身份、动作及工具错误，内层第二次请求与同任务外层
  纠正都收到具体错误并只修改被指出内容。runtime 显式传递 `contract/backend` 类型，不信任错误文案前缀；不建立
  逐错误 Prompt 映射表，也不把 raw response、URL、frame/hash、路径或内部状态投影给模型。
  Region 事实由主 Agent 直接写入正式账本；entry 先作为候选进入一次独立 Entry Reviewer 的批量复核，保留项才写入
  入口账本。Reviewer 同时核对主 Agent 理由中的功能结论；这次无状态调用替换原主 Agent 复核回合，因此不增加调用
  总数。当前 task 历史保留全部精简框架记录，最近一次成功 Entry Review 仍是内容完整度例外：下一轮逐类收到全部保留、补充、丢弃、
  延期候选与延期 Region，同时原样收到 Reviewer 理由和 `reason_consistent` 判断，不再把它压缩为候选数量。原始
  debug trace 和 checkpoint history 仍保留完整响应。若该同截图记录仍有延期候选，`survey_page` 动态显示
  `review_entry_record`：主 Agent 可读取临时记录，或按精确 `(Region,target)` 丢弃其中不合理的延期项；工具不改
  正式 Entry、Page、Region 或图边。主 Prompt 由共享角色/事实/安全合同和一段当前任务说明组成；survey、entry 与
  Region probe 的详细规则不会同时进入同一轮。Qwen 的工具目录只保留名称和短说明，参数 schema 只在紧随其后的
  输出结构中出现一次；runtime-only effect/review/GUI 元数据不再重复写入 Prompt。Codex 调试后端仍由
  output schema 约束同一参数合同。
  当前任务之下另有一个模型可见的短阶段合同，只描述当前 `phase` 的视觉目标和完成条件：Page 身份、Variant 身份与各自复核、
  Region 建立与逐区调查、回到目标页或入口来源页、定位派发入口、恢复和完成复核分别使用自己的
  说明，不把全部阶段规则同时写入 Prompt。阶段上下文也分别投影：Page 阶段带不含任何 Variant 字段或值的自然页面图和到达来源；
  Page 确认后，Variant 阶段只带该 Page 的 material Variant，新 Page 的候选为空。路由阶段只带任务的已知自然语言路线与到达上下文，
  Region 阶段只带目标页或目标 Region 的局部 ledger，入口定位带精确 entry 和当前绑定 Page 的自然语言入口历史，恢复/完成阶段才带对应事实。
  若当前回复接受的身份、`page_update` 或上一动作结算使任务/phase 改变，runtime 记录一条 `stage_transition`，
  保存已接受证据，并把同轮附带的工具延后；下一轮根据最新账本生成新阶段 Prompt。phase 未改变时，Agent 仍可
  连续执行同阶段导航、滚动或恢复，不增加每个动作都必须空等一轮的固定门。
  transition 的 `from_stage/to_stage/deferred_tool/deferred_status=not_executed` 只保留在完整 trace，不再回灌下一轮
  精简历史；入口任务中的延期调用仍在 trace 标明没有产生新 attempt。
  `locate_entry` 阶段若精确入口不在当前视口，主 Agent 应留在已确认的来源页，用滚动或与目标 Region 直接相关的
  局部展开继续定位。runtime 不新增目标可见性分类、导航黑名单、字符串门或页面/按钮特例。
  `click.entry_id` 表示本次实际点击的已登记控件，而不是当前任务标签。直接尝试派发入口时绑定该精确 ID；若
  `task.route` 的下一步明确给出一个已验证导航入口的 `entry_id`，该次路线点击也绑定同一 ID。其他普通导航、恢复、
  关闭干扰和未登记顺路动作留空，且不能把当前任务 ID 绑定到另一个控件。
  `page_update` 只在 `record_regions/survey_region` 阶段提交；其他阶段提前返回的结构不写账本，
  runtime 返回 `page_update_outside_stage`，等 Region 阶段携带局部 ledger 后重新观察。身份与途中新页仍可先由
  `screen` 最小登记，避免入口或路由阶段顺手完成尚未获得上下文的页面调查。
  框架不对目标或解释文字做字符串一致性检查。落地轮另附来源页面、触发动作/入口和来源页已知邻接关系；主响应
  报告页面身份和摘要。
- Region 与 Entry 只由主 Agent 的 `page_update` 写入。主 Agent 先扫描可能交互的组件组，再只登记直接结果会显露
  新功能表面或控件组、改变其他 Region 结果，或解决明确交互歧义的操作；进入内容详情、选择或编辑模式、菜单和
  对话框也属于新功能表面。只修改当前组件或待提交表单字段值的增减、文字、开关、选项和选择器是纯参数；打开纯候选值列表也不是新功能表面。这些操作不建任务，关系和理由写入 `survey_memory`；会将整份配置应用到其他 Region 的确认或提交仍符合信息条件。
  当前已可直接输入且最终动作需要 `input_text` 的字段才标记 `control_type=input`；需要先点击显露输入框的目标仍是
  普通控件。`entries=[]` 合法，静态内容不能回退合成为任务。同质 Entry 须由 Agent 显式给出 occurrence
  或已登记代表关系。若当前精确 State 整页没有功能 Region，`record_regions` 中无纠正的 `regions=[]` 会登记该 State
  的空 Region 调查完成；框架不创建占位 Region，随后返回全局任务池。新的 material Variant 不继承这条空结论。框架不按
  名称、控件类型、位置、模板或字符串相似度推断，推断关系也不冒充真实点击证据。
- 同页重复且可各自改变状态的同质实例分别保存为 Region occurrence；后续实例用 `same_group_as` 指向同批较早或
  已有的代表 Region，经 Region Reviewer 接受后共享 `region_ref`，但各自拥有稳定 `occurrence_ref`。Region group
  保存通用局部状态和真实动作转换；Entry 保存 owner Region、代表 occurrence 与可出现的局部状态。结算为
  `owner_structure/owner_state` 时只改变 owner occurrence，并把其他 occurrence 的状态稀疏继承到新 Page State；
  `owner_structure` 只重查 owner Region；`owner_state` 不改变该 Region 的入口结构，因此将源局部状态已审核的 Entry
  可用性继承到目标局部状态。已审核 Entry 在另一个局部等价的 Page State 上真实执行时，该 Page State 同时补入
  Entry occurrence 证据，供最终证据包对接动作。调度先按 Entry 的局部状态要求计算当前可执行性和已验证路线，
  旧账本继续回退到 `source_state_ids`。
  页面交互模式只保存已发现值、当前临时选择成员和真实进入/退出转换，不枚举选择集合组合；非初始模式中发现的入口保存
  模式要求，调度只复用带真实动作证据的转换。应用级状态独立于页面路由持久化，同值跨页面记录只证明最新截图再次观察到
  该状态。已有同质实例若出现明确结构或能力冲突，可用 `split_from_group=true` 提交给既有 Region Reviewer；审核通过后
  才拆组并重新开放受原推断关系关闭的入口，不新增权限或内容类别系统。
- 入口是当前 Page 的可执行出边，不要求控件位于页面主体。应用内全局/顶级导航若会切换到另一独立功能内容，
  仍须作为候选；当前已选中且不会切换内容的导航项不重复登记。这个边界按功能结果定义，不按控件所在外壳
  或 Region 名称定义。
- `page_update` 中首次出现的新 Region 或新的 `equivalent_to_region_ref` 绑定先形成提案。独立 Region Reviewer 接收
  最新完整截图、当前已登记 Region、整份拟议 Region/entry、被引用候选以及主 Agent 顶层 reason，只判断功能组件
  划分和 equivalence；approve 后才写 Region。Reviewer 不逐按钮审核入口覆盖，也不因为漏掉一个按钮要求新增 Region。
  单个控件应归入可见的工具栏、导航组、内容面板或设置组；碎片 Region、无归属的独立功能表面和 reason 矛盾都写入
  `partition_issues`。标题栏中的最小化、最大化/还原、关闭是窗口管理，不构成功能 Region；其他控件是否漏报为入口由
  Entry Reviewer 处理。Reviewer 判 different 时清空 ref 并按独立 Region 写入；等价证据 uncertain、组件边界被遮挡、
  划分不合理或返回结构不匹配时整份新划分不落账并退回 Region 阶段。一次完整 Region 重报经 Reviewer 批准后，会清除同页旧的顶层
  `region_review_rejected` 纠正；后续结构写入产生的逐 Region/entry 错误仍分别保留。
  Reviewer 拒绝后，整份提案、裁决、frame 和审核轮次会作为临时记录反馈给主 Agent。主 Agent重新提交整份
  `page_update` 和回应理由。修订不是和旧版自动做并集合并，但旧版中未被 Reviewer 指出问题的 Region 不能静默消失：
  它必须继续出现在完整提案中，或在 `omitted_regions` 中以原名称给出具体删除/替换理由。无说明的遗漏由框架在再次调用
  Reviewer 前精确拒绝，不消耗审核轮次。明确省略的合法名称来自本轮讨论开始时的正式 Region 集合与上一版提案，不能因
  首份错误提案已经漏掉正式旧 Region 而拒绝其省略说明。下一轮 Reviewer同时收到上一轮完整提案、当前提案、明确省略项
  和上一轮完整裁决，结合最新截图逐项判断修订是否解决争议且没有误删其他组件。裁决是待核对意见；主 Agent先独立陈述
  当前截图事实，再用具体可见证据接受或反驳。从未属于正式旧 Region 或上一版提案的名称必须从 `omitted_regions`
  删除，不能为使声明合法而新建同名 Region；保留 Region 内部摘要或入口的变化直接修订该 Region。初审加两次讨论复核
  最多三次 Reviewer 调用；任一轮
  approve 才落账，第三次仍未 approve 时最终拒绝并停止该讨论，不提供主 Agent 强制接受旁路。
  单个按钮/图标/标签不能作为 missing Region，只能作为某个工具栏、导航组或内容面板缺失的证据。已绑定 Region 的
  功能或动作与同组其他入口不同，也不使这个按钮单独成为 Region；主 Agent收到相反的复核意见时，仍须先按当前截图
  判断它能否归入现有组件组并明确回应。只由一个控件构成、没有独立稳定容器内容的碎片不能通过改名为工具栏或操作区
  变成 Region；同一连续应用栏内的单控件不会因单独占位、视觉分栏或动作不同而拆出。系统通知、桌面或其他应用浮层、窗口管理控件不参与目标应用区域划分；排除它们不算遗漏，遮住区域关系时复核器返回不确定而不猜边界。区域复核提示和响应结构在运行模块中各只保留一份生效定义。
  首次 `record_regions` 提案复用共享“当前操作界面”定义：只划分实际接收用户下一步操作的目标应用界面，不能
  仅凭前景位置、面积或动作来源改变归属。应用内菜单、对话框、抽屉和搜索/命令面板只有实际成为当前操作界面时才
  单独审核；用户可忽略且不产生新操作路径的状态、说明或反馈属于 passive visual information，不进入 Region。
  它若遮挡 proposed Region，只影响本轮能否可靠判断底层组件；看不清时返回 uncertain，不为遮挡物新建 Region。
  短暂出现本身既不能证明、也不能否定 Region；独立出现、消失、替换或滚动只在已经属于当前操作界面后帮助确定
  粗粒度组件边界。同一连续组件中仅按按钮类型、标题、卡片或视觉分栏拆出的碎片合并；主编辑区、画布、列表和
  终端内容区若有稳定应用功能角色可成立。桌面顶栏、Dock/任务栏、IME、其他应用及窗口管理控件排除。
  主 Agent 的 Region schema 和回显事实都不包含 `bbox_1000`。Region 的首次正式登记以稳定功能组件名称、描述、入口及
  其 owner 为准，不产生几何纠正。Reviewer 只根据完整截图和 proposal 的语义组件划分审核，不要求补框或裁框；只有
  proposal 在名称、描述、入口或 active-surface 归属上把桌面、Dock、其他应用或窗口管理控件当成应用功能时才拒绝。
  `partition_issues` 只能要求改变 Region 集合、边界、active-surface 归属或跨页等价；具体 entry 的增删、改名或
  遗漏留给 Entry Reviewer。
  普通 coverage/bbox/survey_memory 更新不调用 Region Reviewer。通过后的 `entries` 仍先暂存为自然语言候选，不分配
  entry ID、不产生探索任务。存在候选，或某个 Region 请求 `coverage_complete=true` 但还没有 accepted
  entry-coverage audit 时，scheduler 下一轮进入 `review_entries`：独立入口复核器查看最新完整截图、精确
  `(Region,operation,subject,target)` 候选、待审 Region、`survey_memory` 和主 Agent 理由。它先独立扫描待审区域的
  交互组件组，再比较候选，只保留符合上述未知功能信息条件的安全操作，并把截图中明确漏报且属于这些 Region 的目标
  写入穷尽的 `independent_entries`。每个原候选还必须显式分到 `independent_entries`、`non_task_entries` 或 `deferred_entries` 之一；runtime 拒绝重复分类、越界的非候选和未分类原候选。`non_task_entries` 只表示已看清且没有后续探索价值的候选；功能有价值但因当前可见前置状态不可执行的候选必须延期。两类记录都只保存精确 Region/target，理由仍由 Reviewer 的简短自然语言 `reason` 按组件组说明，不复制完整入口结构。候选不是可见控件的封闭清单；同一组件的文字与附属图标只有预期直接效果相同才
  合并，不能仅按相邻位置强制合并。runtime 自行区分
  原候选保留项与新增项。提案与裁决一致时，
  普通候选批仍只需首次 Reviewer 调用；若 Reviewer 丢弃了主 Agent 候选，或认为主 Agent 理由与裁决不一致，则进入
  同一份提案的有界讨论，最多再复核两次。无候选 Region 只在请求完成且缺少审计时增加首次调用。
  Entry Reviewer 直接读取最新完整截图、精确正式 Region、主 Agent 候选和已有入口，并逐一审查
  `coverage_audit_regions`；没有候选不是覆盖完成证据。这条自主 Region 路径不接入 OmniParser、本地检测框、SoM 或
  第二套视觉 inventory，也不从这些来源回退生成 Region/entry。
  正式 Region 划分对 Entry Reviewer 只读：它只能使用待审列表中的原 Region name，不能创建、拆分、合并、重命名
  或改绑 Region；认为划分有误时只在 reason 中报告。runtime 要求待审 Region 已同时写入 Region State 和 Registry
  且 ref 一致，未知 owner、未绑定 Region 和 Reviewer 臆造 Region 全部拒绝。正式划分和跨页等价仍只由主 Agent
  提案加 Region Reviewer 批准。
  `page_update` 保持逐项 partial：schema-invalid Region/entry 不会被预处理成合法默认值，也不会污染正式划分；
  同批合法 Region 仍会保存。被拒 entry 的精确纠正保持 pending，并阻止其所属待审 Region 在本轮完成；无 owner 的
  被拒 entry 阻止本轮全部待审 Region 完成。
  只有一致、无延期且没有被拒 Entry 的完整 Region audit 才会关闭该 Region 中旧的
  `new_entry/region_name/unknown_region_reference` owner 纠正；入口名称后来更准确也无需模糊匹配。其他 Region、
  其他错误类型及未完成 audit 的纠正保持不变。
  Region State 写入、Registry bind 和全局 ref remap 以同一内存事务执行；异常时恢复所有 Page 的完整 State（包括
  当前 frame/bbox）及 Registry，不能用会主动丢弃瞬时几何的 resume restore 充当事务回滚。
  每项正式 Entry 用简短 `operation` 表示用户操作、`subject` 表示语义对象，`target` 只保存当前可点击的代表目标。
  共享同一交互模板、用户意图和预期效果且仅内容实例不同的目标，只登记一种操作和一个代表目标；效果不同且符合未知
  功能信息条件的操作保持独立，纯参数差异不建任务。当前模型响应必须提供三个字段；旧 checkpoint 和 fixture
  分别从 `target`、所属 Region 回退 `operation`、`subject`。
  `operation` 和 `subject` 会投影给入口审核器、主 Agent 当前任务、共享 Region 候选、同 Region 待办、点击复核和可读历史。
  共享 Region 覆盖签名精确使用 `operation + subject + control_type + target`，框架不做模糊文字归并；语义相同但入口身份不同的
  可见控件仍分别保留，只有主 Agent 或复核器根据通用同质条件显式裁决后才复用结果。共享 Region 中的入口等价必须同时核对 `operation`、`subject`、控件角色和当前激活上下文；图标、文字、位置或 Page 相同/不同本身都不足以绑定。
  keep/add/non-task/defer 都为空合法。
  补项不能在复核阶段新建 Region。框架不按字符串替 Reviewer 分类，也不逐项调 specialist；但完成检查要求每个
  `coverage_complete=true` Region 在 `autonomous_regions.json.entry_review_audits` 中有 accepted audit。显式正数
  `max_actions` 已耗尽时仍允许完成这次无 GUI 复核，然后再按上限停止。
- 显式 `entry_id` 入口点击已验证产生画面变化、但页面身份仍是来源 Page 时，runtime 安排一次内部标记为
  `same_page_functional_surface_changed` 的增量调查。主 Agent 只收到“入口动作在同一页面显露或改变了功能表面，需补查”
  这类自然语言原因，不接收该内部标记。旧 Region 的完成位和旧入口不重置；主 Agent 只在最新截图上补充新显露或
  明显改变的功能 Region/入口。普通未绑定动作不触发。当前真实 changed-action 证据代中的首份增量划分仍经 Region
  Reviewer；批准后，Entry 协调期间只更新既有 Region coverage/调查记忆的提案复用该裁决，不重复调用 Reviewer，
  并保留本证据代已经批准的 occurrence bbox。新增 Region、新的共享 Region 绑定或新的真实 changed 动作会重新触发
  复核；待办在一致 Entry Review 接受本轮聚焦 Region 的覆盖后关闭，不等待同 Page 中被当前模态遮住、需要返回其
  recorded State 才能调查的 sibling Region。它们随后作为各自 Region 调查继续调度。
- Region 不是天然逐个派发的独立模型任务。`record_regions` 可在一次 `page_update.regions[]` 中批量登记并完成当前
  截图已看清的多个小型/静态 Region；只有需要滚动、展开或仍不确定者保持 incomplete。调查一个未完成 Region 时，
  同屏其他已看清的小 Region 也可在同一 update 中完成；只有不同滚动容器的真实滚动动作需要分别执行。
  但 `survey_region` 已派发 Region A 时，当前 `page_update` 必须实际包含 A。只提交 sibling 的更新整批拒绝，A 的
  correction 与所有正式 Region/entry 账本保持原样，该拒绝计入统一 5-per-task/10-per-run 无进展边界。A 与 sibling
  同批提交仍按上述批量合同处理，不增加逐 Region 强制往返。
  一轮 Region Reviewer 讨论固定使用首次提案的完整截图，主 Agent 修订时也得到该固定证据。第三次拒绝在同一证据代保持 final；只有已验证的界面变化产生新证据代，runtime 才定点移除该页顶层 exhausted Region 讨论、记录 `region_review_discussion_reopened` 并从 attempt 1 重开；其他 Region/entry correction 全部保留。
- 公开协议每轮允许一个 `CALL_TOOL`；若只需报告观察或当前页增量，`action` 可以为 `null`。两类任务共享
  `page_identity/report_record_error/handle_interruption/click/hover/scroll/navigate`；`explore_entry` 另有
  `reuse_entry_result/defer_current_task`，且仅在该精确 Entry 的 `control_type=input` 时开放 `input_text`。
  `defer_current_task` 不向 `survey_page` 暴露；Android 动态增加
  `gesture(long_press|double_tap)`。完成由框架推导，旧 `finish_exploration`、`complete_region_probe`、
  `show_map/recall_page/find_route/compare_page` 和直接 `CLICK/SCROLL/BACK/WAIT/FINISH` 已删除。显式绑定 Entry 的
  功能 pointer action 在 survey 中会以 `survey_does_not_execute_entry` 拒绝；途中陌生页可最小登记，完整 Region
  调查留给随后 survey。Page Identity pending 仍用 `previous_tool_review` 复核；Region 新划分使用独立 Region
  Reviewer，普通既有 Region 更新不增加调用。
- 临时前景层不遮挡或不妨碍当前任务时，主 Agent 直接忽略。确实阻挡时只调用 `handle_interruption`；独立
  Handler 查看最新完整截图和当前任务，在 `ignore/wait/hover/click/back/unresolved` 中选择一个动作，框架绑定其
  精确输出。同一任务最多三轮。桌面 hover 只能指向可见干扰表面并在动作后重新截图；整张通知/横幅/弹窗/卡片
  不能作为自身关闭控件。Handler 的 click 仍经过独立 Click Reviewer，普通页面不会调用 Handler。
  若干扰发生在 Page 或 Variant 尚未登记时，经审核的 wait/hover/click/back 可走预登记恢复路径：阻挡帧不写
  Page@Variant/Region/Entry 图，原落地动作仍保持待结算；重新观察一旦变帧，会清除绑定旧帧的身份提案、暂存 Page、
  current Page/Variant、反馈和冻结评估，在新截图上重走 Page→Variant。该恢复只写 trace/history 并明确
  `semantic_graph_recorded=false`，不伪装成可遍历功能边；`max_actions` 已满时不得借此多执行一次 GUI 动作，
  但最后恢复动作之后的纯身份结算仍会完成。
- 已知路线由 scheduler 直接放入 `task.route`；它仍只是建议，主 Agent 可按最新截图走更短路径，不再另占一轮
  调用只读 `route_to`。同一 Page 内若目标 Region/Entry 只在其他已登记 State 可用而图中暂无转换，任务仍以空
  `task.route` 派给主 Agent，并明确要求根据最新截图逐步发现一个安全局部转换；真实动作继续写入普通动作边，落到任一
  满足目标条件的 State 后重新调度。跨 Page 未验证路线仍保持关闭。
- 框架拒绝工具或动作时，完整 `detail` 留在 trace，下一轮只附
  `rejection={status,code,message}`。主 Agent 先按该事实反馈纠正，
  不原样重试。反馈不会额外改变所属任务的固定工具视图；下一步仍由主 Agent 决定。Click
  Reviewer 拒绝时保留其原始理由，并在短期反馈中带被拒 operation、target 和 `point_1000`，要求不复用该点，
  但不硬编码下一工具；主 Agent 根据理由判断应改点击目标/坐标，还是改用
  scroll、navigate、`page_update` 或其他当轮可用工具。一旦同一 task 后续已经发出真实 CLICK、DOUBLE_TAP 或
  LONG_PRESS，该旧 Reviewer 拒绝只保留在 trace，不再进入模型的最近纠正历史。`finish_exploration` 被拒绝时，具体 `remaining` 缺口清单
  与 rejection 一起进入短期历史，不能只回传笼统的 `completion_evidence_missing`。
- `route_to_source/route_to_page` 中空 `action` 且无稳定进展时，`stage_incomplete_no_action` 会从当前 task 的
  `route_hint` 回传当前 Page、目标 Page 和第一条已知 `from/via/to`；没有路线的同 Page 状态准备则由 task 上下文明确
  当前目标仍未满足。Agent 根据最新截图决定直接执行、先定位，或以 `report_record_error` 质疑记录。框架不自动重放
  动作、不生成坐标、不隐藏工具，也不强制 `action` 非空。
- resume 后的持久化地图不带 current Page/Variant 绑定；主循环先用 live 截图完成身份确认，才调度任务或判断无可运行工作。
- `report_record_error` 的首次调用按原合同保存。若同一 task、同一字节 frame、同一 error kind 已有一条
  `reported` 记录，后续只改 `subject/observed_problem` 的调用以 `duplicate_record_error_same_frame` 拒绝，
  并进入共享 5/10 边界；subject 不参与去重，frame/task/kind 任一变化后重新允许。它不判断报告真假，
  也不把首次合法诊断计为拒绝。
- 身份严格分为两轮。`identify_page` 的 `screen` 只有 Page `name/identity`，Page 上下文不出现 Variant 候选、字段或值；
  Page 选定后，`identify_variant` 的 `screen` 只有 `variant={name,identity,visible_predicates}`，框架只投影该 Page 的
  material Variant，新 Page 使用空候选。runtime 即使收到旧/custom Agent 同轮夹带的 Variant 字段也只保存 Page，
  不允许绕过下一轮 Variant。Page 与 Variant 都确认后才创建 State、结算落地动作或进入后续阶段。
  主 Agent在每一步都可报告 `known|new|uncertain`；视觉证据不足或与账本冲突时调用 `page_identity`。但已知 Page 下的
  `new` material Variant 必须先调用 Variant specialist 比较，不能由主 Agent直接登记。
  Page specialist 只比较各 Page 代表图，Variant specialist 只比较已选 Page 的 Variant 代表图；两者都接收当前整图、
  最近真实动作的 source/before 整图、到达上下文和上次反馈，但不会把其他 Page 的 Variant 混入 Page 判断。
  specialist 提案绑定当前步骤和观察，下一轮由同一主 Agent用 `previous_tool_review=accept|reject|uncertain` 复核。
  known Page 保留已登记的稳定 `summary/surface_kind`；new Page 使用 Page specialist 的元数据，不在 Variant 提交时改写。
  resume/restart 若没有可信 `current_page`，会同时清除旧 `current_variant` 并强制回到 Page 步骤；Variant 步骤若明确质疑
  Page 归属，会清除已选落地 Page 和旧 Variant 提案，再以“待争议 Page”和“可信动作来源 Page”两个事实重开 Page specialist，
  而不会把待争议 Page 错写成来源页。等待复核期间没有执行 GUI 动作，因此动态时间、动画等被动像素变化不会由框架自动
  使身份 pending 失效；主 Agent 对照最新截图决定接受或拒绝。
- 自主 Page Identity 不负责检测或关闭弹窗，返回状态只有 `known|new|uncertain`。Toast、横幅或局部临时
  遮挡不影响身份时忽略；hover、焦点、滚动、时间或被动动态内容不拆 Variant。只有遮挡使 Page 或 Variant
  本身不可判断才返回 `uncertain`。应用自己的菜单、抽屉、功能对话框、查询结果或创建对象在仍由同一稳定
  Page 锚定且会改变后续操作、结果或恢复路径时登记为 material Variant，而不是仅因成为前景表面就另建 Page。
- 主 Agent 可在 Region 阶段的普通响应中提交最小 `page_update={page_name,regions:[{...,entries:[...]}]}`。Region 项只含必需
  `name/coverage_complete` 与可选 `summary/survey_memory/equivalent_to_region_ref/equivalence_reason`。`name`
  是在当前页面与候选邻域中能区分主要功能的稳定自然语言名，不使用通用布局槽位、位置、序号或动态数值。Region 是用于
  全局去重和入口身份复用的稳定功能组件身份，不是矩形范围、通用内容容器或页面中的位置；同一 Region 可在多个 Page 上
  有 occurrence，前提是具体内部主要组件、组件角色和功能入口稳定，使一次探索得到的入口身份和验证结果能可靠复用。
  候选只提供代表 occurrence 的 `canonical_name` 和 `component_signature`；只有主要组件、组件角色和关键入口对应且没有
  关键冲突时，才沿用规范名并引用 `region_ref`。Agent 必须先判断候选入口身份和已验证结果迁移到当前 occurrence 后是否仍
  准确；若只有中心工作区、外层容器或布局槽位相同，而内部功能组件或关键入口已变化，则登记新区块。仅主题、布局或出口
  相似不足以合并；不确定时登记新区块。同一完整 Page 提案内的不同 Region 不得共用一个 `region_ref`。若显式引用或
  动作前后批量映射把已有 ref 指向该提案中另一个 Region，提交层清空冲突引用、保留原 Region 身份，并让新 Region 获得
  独立 ref；对应的批量 coverage 继承同时取消。`survey_memory` 是该 Region 的自由文本累计
  调查记忆，由 Agent 用实际语义锚点、纯参数不建任务的理由、未决交互问题、连续滚动或展开轨迹及仍待检查方向自行压缩。框架保存完整值，
  但只在对应 `survey_region` 或该 Region 的入口任务中回传短摘要；不按顶部/中部/底部、固定段数或滚动次数解释覆盖，
  也不重复完整 entry ledger。
  每个 entry 放在所属 Region 的 `entries` 中，框架从父项自动绑定 Page/Region；entry 只含必需 `target` 与可选
  `bbox_1000/equivalent_to_entry_id/equivalent_occurrences`。新入口 ID 只由框架分配，并通过下一轮最新页面账本或
  入口任务的 `entry_id` 返回；`equivalent_to_entry_id` 只能引用本轮前已存在的代表。入口审核会按当前已提交
  `region_ref` 投影共享区块下的规范入口，包括尚待探索和已经验证的代表；前者只合并任务身份，后者才复用结果。
  精确 `explore_entry` 阶段的 `reuse_entry_result` 仍只投影已验证代表。
  同轮重复实例放在 `equivalent_occurrences`，不提供旧字段兼容层。规范化 Page、Region、target 三项完全一致的
  重放作为幂等命中；已有 ID 仍从最新页面账本返回，不单独回放内部 match 状态；
  不创建新 entry、不推断语义等价，也不匹配近义名称。幂等命中只累计观察并刷新本帧非空 bbox，保留已有
  `status/task_eligible/target/equivalent_occurrences`；仅当 Agent 本轮显式提交等价字段时才更新对应关系。
  同一页面、正式 Region、target 和 `control_type` 完全一致的重复候选本身不触发 Entry Reviewer；新的 target、
  `control_type` 冲突或区块覆盖审计请求仍按原路径复核。
  同 Region 的不同同名控件需要 Agent 给出可区分描述。
- 新 Region 与首次 `equivalent_to_region_ref` 由同一次独立 Region Reviewer 调用复核。Reviewer 对照完整截图、整份
  划分、主 Agent reason、候选规范名、组件签名与 verified entries；返回
  `decision/partition_issues/equivalence_checks/reason`。`partition_issues` 为空、reason 与划分一致且每条 equivalence 都有
  same/different 明确结论时才 approve。same 保留 ref，different 清空 ref 后作为独立 Region，uncertain 或划分问题则不写
  Region/entry/inferred edge。拒绝会把整份提案、Reviewer 裁决、当前 frame 和 `review_attempt` 保存在
  `pending_corrections`。主 Agent下一轮用新的完整 `page_update` 和顶层 reason 回应；框架先比较上一版完整提案，要求未被
  上一轮明确否定的旧 Region 保持存在，或在 `omitted_regions` 中用原名称说明删除/替换理由。静默遗漏会返回精确 Region
  名称，不调用 Reviewer，也不增加审核轮次。Reviewer请求带上上一版完整提案、当前明确省略项、
  `previous_review/review_attempt/review_attempt_limit`，必须针对修订和最新截图逐项重新判断。初审为 attempt 1，最多再讨论
  attempt 2 和 3。同一审核讨论中的修订遵循最小修改原则：只修改框架或 Reviewer 明确指出的问题；未被指出且与最新
  截图不冲突的 Region name、entry target 和归属保持不变。修正 bbox、coverage、summary 等局部字段不能顺带改名或
  改绑；只有最新截图证明原身份或归属错误，或 Reviewer 明确要求改变 Region 集合、身份或归属时才允许修改，并须在
  主 Agent 顶层 reason 中说明具体依据。
  第三次仍未 approve 时写 `region_review_exhausted/review_exhausted=true`，提案最终不落账且后续提交不再
  调用 Reviewer。不存在主 Agent直接写入临时提案的工具。`same` 必须由候选签名与当前截图中同一具体功能的内部组件或
  入口支持；仅以 workspace、container、structural role、位置、主题或同一 Page 为理由无效。候选具体入口被不同功能入口
  取代，或内部主要组件换成另一组控件时判 `different`，即使外层内容槽位保持不变；动态数值、选中状态和同类内容实例可
  不同。已有 occurrence 对其当前 ref
  的普通更新不增加调用。Reviewer 批准的完整划分会替代该 Page 上此前的逐 Region 纠错，包括 Agent 改名后留下的旧键；
  Entry 纠错保持独立，且随后逐项结构校验发现的新 Region 错误仍按当前名称重新登记。同一 `page_update` 中属于本批
  proposed Region 的 Entry 只随 owner 等待 Region 接受和正式绑定，不生成独立 `unknown_region_reference` 纠正，也不进入
  Entry Reviewer；只有 owner 既不在正式划分、也不在本批 Region 提案中时，才作为真正未知 Region 拒绝并保留纠正。旧
  `review_region_equivalence` 阶段只保留给已有 checkpoint 的待纠正状态。
- fresh Clock 已验证当前讨论分支的 reject→修订→approve 控制路径，随后当前精简 Reviewer 的新运行又到达 World、Alarms、
  Stopwatch、Timer 四页。顶部导航 `rg1` 复用和 Timer 首次错误归组的拒绝均正确；但 Reviewer 明知可见内容已从空状态/Add
  按钮变为 Stopwatch 数字与 Start/Lap，仍以“同一中心工作区/容器/空间角色”为由把 World、Alarms、Stopwatch 合并进
  `rg2`。这证明“布局槽位不是组件组”的 equivalence 边界尚未 live 生效，fresh Clock 语义验收失败。
  同次运行中，主 Agent给已有 Modal 条目错误引用无关且未验证的 `ae8/ae9` 后，框架正确拒绝；但 Entry Reviewer 后续
  drop 精确 Cancel 候选没有清除该条旧 correction。每次 Search duplicate 被接受并发生阶段切换，5/10 无进展边界因此没有
  触发，最终形成 `survey_region→review_entries` 活锁。101 次真实调用后手动停止，无 `completion.json`。证据位于
  `artifacts/desktop_clock_region_partition_live_20260808_024427_evidence/`。
- 当前 runtime 的重审数据流已补齐：Entry Reviewer 的结构拒绝以内部 `previous_rejection` 保存，但下一次无状态调用
  只接收说明“上一份回复为什么未被采用、应如何修正”的完整自然语言，不接收错误码、重试 token 或原始状态对象；
  成功重审清除 pending。`review_entry_record(correct)` 只清被显式丢弃候选的精确
  page-update correction，保留其他 correction、正式 Entry、Region、Page 和图边。Region Reviewer 只要求对实际提供的
  Region candidate ref 返回 equivalence check；未知/编造 ref 仍在正式写入时逐项拒绝。
- 采用上述代码的 fresh Clock 到达 World、Alarms、Stopwatch、Timer，14 个 Region 全部 complete 且均有
  `visual_entry_reviewer` audit；最终无 pending correction/review。它仍未生成 `completion.json`：Entry Reviewer 的原始
  reason 明确把 Alarm 的 Repeat/Name 等判为当前功能内部控件，却错误放入 defer/keep，Ring/Snooze dropdown 也被保留为
  独立入口。运行随后扩张到 39 个 Entry，27 verified、2 inferred、9 unresolved，最后 1 个 `Name input field` 仍 eligible；
  该任务 5 次无进展后挂起并触发 `all_remaining_work_suspended`。这证明当前剩余 blocker 是 Entry 语义分类自相矛盾和
  重复入口复用不足，不是 Region bbox/IoU、页面可达性或 Reviewer 拒绝反馈丢失。真实运行共 288 次 backend 调用、
  53 个 GUI actions，未获 completion acceptance；证据在
  `artifacts/clock_review_feedback_live_20260808_210342_evidence/`。
- 精确 Entry 争议现在复用同一个无状态 Entry Reviewer，而不增加 control ledger 或第二套 frontier。主 Agent 只能在当前
  `explore_entry` 的来源 Page 上用 `report_record_error(kind=entry, subject=<当前 entry_id>)` 请求复核；runtime 同时校验
  精确任务、来源 Page、尚未覆盖的 task eligibility，以及 owner Region 的 State/Registry 绑定。Reviewer 请求只含该候选，
  不重新审核整页 coverage，也不补报其他入口。
- 精确复核是建议性争议证据，不是删除或退休正式 Entry 的授权。Reviewer retain/defer/drop、reason 一致或不一致、非法输出、
  不可用或失败都只以完整自然语言返回主 Agent；无生产调用的 `mark_reclassified_non_entry` 已删除，单次 omitted/drop 没有
  状态修改旁路。正式 Entry 只有回到普通 Page Entry 提案、经过最多三轮的协调并取得一致审计，
  或出现新的 GUI 证据后才能改变；点击失败、临时不可用和不可达仍走各自已有边界。
- fresh Clock 现已被 autonomous FINISH 门接受：4 页、13/13 Region complete、13/13 `visual_entry_reviewer` audit complete，
  14 个 Entry 为 13 verified/1 inferred，0 eligible、0 pending correction/review/temporary state、0 finish rejection/suspension，
  `stop_reason=model_finished`、进程退出码 0。autonomous CLI 按设计不写 guided `completion.json`；本 mode 的接受依据是 runtime
  在 `_completion_gaps=[]` 后接受 FINISH。
- 该运行未调用 `report_record_error(kind=entry)`：New Alarm 的 16 个内部控件先被 Reviewer 错误 defer，随后通过空候选重审
  在正式入账前清除。因此 live 验证当前完整路径能够结束，但精确 false-positive Entry 恢复分支仍只有离线调用路径证据。
  运行另暴露 5 个 `direct_action_backfill` 污染项：Cancel 内部控件和四条 `full_screen` 导航副本被保存为 verified Entry。
  它们不再 task-eligible，故未阻塞完成，却使 Entry inventory 不能判为语义洁净。证据在
  `artifacts/clock_entry_reclass_live_20260809_001758_evidence/`。
- 页面 owner 或 `page_name` 不合法时整个 update 拒绝；否则先逐项 Region、再逐项 entry 提交。单个坏项不回滚
  已接受项，也不阻止同轮独立有效 action。内部 `page_update_result` 仍保存结构化提交结果供 trace/debug 使用，
  但模型下一轮不接收 `accepted/partial/error_code` 等内部字段：成功事实只从最新页面账本读取；拒绝只收到包含对象、
  未写入事实、原因和修正方向的自然语言反馈。new entry 可引用既有或
  本批成功新建 Region；未知或被拒 Region 只拒该 entry。若某 Region 本批 entry 被拒且其 Region 项请求
  `coverage_complete=true`，其他字段接受，但该完成位延后并返回 `coverage_completion_deferred`。
  只要最近一次 page update 仍含 rejected item，runtime 就保留当前 `record_regions/survey_region` 阶段；纠正提交
  没有 rejected item 后才按最新 Region/entry 账本重新调度，不能先进入 `completion_ready` 再把正确补交判为阶段外。
- 若既有 Region 在当前完整 PNG 字节帧上的最近观察是 `coverage_complete=false`，同一字节帧不能提供把它改成
  `coverage_complete=true` 的新证据；该项以 `coverage_same_frame_without_new_evidence` 拒绝完成位，并继续保持
  incomplete。目标 Region 上下文同时提供 `distinct_frame_since_incomplete`。首次观察即可完整判断的 Region、或已取得
  不同截图后的完成判断不受此门限制；runtime 不推断滚动到底、固定段数或功能入口数量。
- 最近一次拒绝从普通 `recent_results` 中移出，只在 Prompt 末尾以一个“必须先处理”的自然语言纠正块传回，且不重复
  完整本页事实、错误码或内部记录 ID。Agent 可自行选择重报、换动作或报告 blocker；框架仍只校验结构与已有事实。
- `record_regions` 阶段的模型 Region schema 已删除 `bbox_1000`，Region 账本回显也不再携带它。旧 checkpoint 或内部
  调用的 State-local 几何仍可兼容读取，但不进入 VLM 协议；无当前几何时，语义 Region 和 Entry owner 照常登记，后续
  精确 Region probe 也不以缺框阻塞动作。entry bbox 仍是当前帧观察和执行提示，不进入稳定页面身份。
  `action=null` 的页面登记轮
  不执行 GUI；同轮也可先更新 ledger 再执行独立有效 action，但只限更新后当前阶段仍未改变。若身份、Region
  建立、Region 完成或入口结算使阶段前进，旧阶段动作延后到下一轮重新决定。
- `scroll` 的自治 schema 只含自由文本 `container_hint`、同帧 `point_1000`、`direction/amount`。
  所有 action schema 都不含模型回显的 `frame_id` 或无消费者的 `purpose`，工具目录也不接收帧 ID。
  runtime 在执行前把最新截图 ID 直接写入内部 `ValidatedAction.frame_id`，继续供 before-frame 一致性与
  动作证据使用；这不会把内部哈希暴露给主 Agent。
  `container_hint` 描述截图中实际期望接收滚动的容器，不要求已登记为 Region；point 只需位于全屏 `0..1000`。
  仍拒绝全屏越界与参数格式错误，不再拒绝未知 Region，也不改变 Region 的功能容器定义。
  动作后回传 `container_hint/point_1000/before_frame_id/after_frame_id/moved`；主 Agent
  可继续 `page_update` 或滚动。待结算 scroll 的下一轮另给出精简
  `last_scroll_result={container_hint,direction,point_1000,frame_changed}`；其中 `frame_changed` 只表示前后完整 PNG 字节是否
  不同，不是新内容、边界或失败原因分类。主 Agent 对照两帧判断；完全相同时不能原样重试，可换动作或把已观察主要范围的 Region 报告完成；框架不因
  一次无变化自动关闭 Region。没有 RegionScan、外部滚动请求、scan ID 或暂停/恢复 scan 状态。
  上一真实 scroll 的 before/after frame 完全一致、当前仍是该 after frame、且下一次规范化 scroll 的
  `container_hint/point_1000/direction/amount` 四项逐项完全相同时，runtime 以 `repeat_no_change_action`
  拒绝执行，不增加真实动作数。Agent 仍可改变任一动作字段、换动作或报告 blocker；runtime 不解释无变化原因，
  不使用容器文本相似，不增加页面/控件例外，也不把该防线扩展到 click/gesture。
- `survey_region` 中若内容在容器边缘明显被截断或继续延伸，主 Agent 先对可能容器做一次低风险 scroll 观察再决定
  `coverage_complete=true`；没有可见延续证据时不增加独立查漏阶段。当页所有 Region 完成后直接转入 entry 任务；
  新增或重开 incomplete Region 会自然重新派发 survey。这里不要求物理滚到底，也不使用固定顶部/中部/底部。
- 对持续加载的列表或瀑布流，覆盖对象是不同质 Region 和功能入口类型，不是所有内容实例。若跨滚动观察到实例持续更换、
  但结构和不同质入口不再增加，主 Agent 可在 `survey_memory` 写明观察批次、重复结构和剩余不确定项后完成该 Region；
  同质实例仍由 Agent 显式绑定代表或 occurrence。一次无变化或临时加载停顿不能单独证明动态列表已经覆盖完成。
- `click/input_text/scroll/navigate` 以及 Android `gesture` 自动绑定调用当轮最新截图，不要求 Agent 回显完整哈希或 frame token。普通 `click`
  只含 `target/entry_id/point_1000`；`navigate` 只含 `operation`。完整 before/after frame ID 仍由框架写审计证据，
  不进入下一轮给 VLM 的摘要。
- Android `gesture` 用一个严格二选一 schema：`long_press/double_tap` 携带
  `target/entry_id/point_1000`，与 click 共用独立坐标/目标/安全 Reviewer 和入口结算；`swipe` 只携带方向，
  不绑定按钮入口。三者直接规范化为 MobileWorld 小写顶层原生动作。普通入口仍优先 `click`，Region 内容调查
  仍优先 `scroll`。`input_text` 只含当前可见输入框的 `target/point_1000` 与短的非敏感单行 `text`，不含
  `entry_id`，只在精确输入 Entry 的 `explore_entry` 中开放；它不按 Enter，也不得提交、发送、创建/编辑数据、授权或输入凭证。
  任务上下文会显式标明 `control_type=input`；该任务只有 `input_text` 能以 `entry_attempt` 结算，点击输入框
  只能作为 `locating` 的聚焦或显露步骤，不能完成输入操作。
  Click Reviewer 从完整截图独立判断请求字段用途；清晰的名称或其他表单/数据编辑字段即使拟操作点未落入
  输入框，也会按 input_text operation 不适用拒绝，避免只返回几何错误后重复猜点。
  Enter、Home 和 `open_app` 仍未向自主 Agent 开放。
- 已验证/推断入口若只作普通顺路导航，`click.entry_id` 留空；当前 `task.route` 下一步明确携带精确 ID 时，
  该次路线点击回传同一 ID。短期事实窗口若连续至少两次出现完全相同的工具/结果，给出通用
  `repeat_warning`，但不通过隐藏工具替主 Agent 选择下一步。
- resume 对 pending entry 区分来源：已由 `page_update` 登记、随后以显式 `entry_id` 执行但中断的入口恢复为
  `unresolved/task_eligible`；`direct_action_backfill` 的途中未登记目标只保留动作/图证据，不自动变成框架任务。
  加载旧快照时，所有 direct backfill 的遗留 task flag 都会清除，不因其已 verified 或有 destination 而保留；
  verified/inferred 的 Region entry 也同步清除当前任务资格。它以后仍可由新截图上的 Region observation 正式登记。
- `click/input_text` 及 Android `long_press/double_tap` 使用当前完整截图的 `0..1000` 坐标。普通 point-targeted action 不经过 Grounder；执行前由
  主 Agent 忽略不遮挡、不阻止且不妨碍可靠判断当前阶段目标的临时干扰，不为清理界面主动关闭。只有干扰
  确实影响当前阶段、且最新截图中存在直接属于它的可交互控件时才能请求处理；`target` 必须写实际控件及
  直接可见归属，不能写预期效果、不可见控件或借用其他界面的相似控件。随后
  独立 VLM Click Reviewer 先检查未标注完整截图以判断实际控件或主 Agent 有意选择的可见界面表面及其直接视觉归属，
  再检查以真实操作像素为
  精确中心、用四个小角标包围且不覆盖中心的同帧局部放大图。主 Agent 的顶层探索 reason 不作为 Reviewer
  的控件身份或风险授权，但会连同当前任务的精简摘要传给 Reviewer，用于区分有意选择表面和没有点中控件。
  Reviewer 还接收最新截图、实际 target、点位、purpose、精确 operation、可选正式 Entry 和视觉证据。
  operation 必须是 `click/input_text/long_press/double_tap` 之一；`input_text` 还接收本次实际文本，
  审核点位是否为该输入框以及输入本身是否安全，不根据预期搜索结果放行；不再重复传递可由 operation 完全推导的 `tool_name`。
  完整截图中的真实鼠标光标和 cursor-triggered tooltip 只表示已有 hover 状态，不代表拟点击点；唯一拟点击点始终是
  局部图角标中心。hover 展开的菜单、高亮和显露控件仍是有效状态证据；tooltip 完全遮住中心时返回 uncertain，
  不把 tooltip owner 移植为拟点击目标。
  局部图中心像素已经唯一表示执行点。若主 Agent 声明的是控件，中心在其可见边界外即使只差几像素也属于未命中；
  若主 Agent 明确声明的是界面表面，Reviewer 则核对中心是否确实落在该表面且没有误中相邻控件或遮挡层。
  Reviewer 的 `observed_target` 先描述实际控件或表面及其直接归属，再检查主 Agent 的 target 事实声明；它不能用相似
  功能或类似效果替代实际目标，也不能因安全表面本身不是按钮而拒绝。
  实际目标是否在可见标签、图标、直接归属和可选 requested-entry 证据上
  符合请求 target（`target_matches_request`）、前景是否可操作，以及点击在当前
  discover-only 阶段是否会最终保存配置、完成向导、修改数据、授权或产生外部影响。形状相似但所属窗口、
  弹窗、卡片或行不同，或请求目标不可见时必须拒绝。风险按实际控件而不是请求用途判断，只由独立 Reviewer
  与框架硬边界裁决；主 Agent 响应没有 `safety` 或 `expected_result` 字段，其 reason 也不构成执行授权。
  Reviewer 不能用想象的动作效果替视觉控件命名，也不能凭应用惯例假设删除、提交等动作之后必有确认框或 Undo；
  当前图不能排除本次点击直接产生影响时即 fail closed。Reviewer 不预测安全动作是否会产生 Agent 希望的结果；
  是否生效由动作后的新截图结算。Reviewer 不替
  主 Agent 选目标或改点；Reviewer 还必须按请求的 click/long_press/double_tap 操作本身判断安全，不能把手势
  默认为普通点击。`navigate` 只做 back/wait；wait 重新截图而不伪造环境动作。公开协议不再让普通按钮
  携带临时 bbox、before/after 值或 restore 标志，也不要求 `previous_action.temporary_state`。discover-only
  Prompt 要求避开只改变数值或状态的内部控件。旧 checkpoint 的 temporary-state 账本仅作为只读兼容
  证据：恢复时原样读回，`completion_ready` 会展示相应事实并阻止把旧运行误报为完整；现行 main-turn
  响应和 action tool 都不能新建、更新或关闭该账本，scheduler 也不再生成协议无法执行的
  `restore_state` 任务。后续 checkpoint 仍原样保存这份历史证据。
  `previous_action.business_effect` is a separate capability-evidence field,
  not a revival of the legacy temporary-state restoration contract. On every
  settled public action turn the main Agent returns either null or exactly one
  `state_change`, `object_creation`, `object_removal` or `query_result` with
  `{effect_kind,region_name,capability_name,fact,before_value,after_value,parameter_bindings}`.
  `before_value` and `after_value` are required string fields, but either may
  be `""` when the corresponding frame visibly shows an empty value; missing or
  non-string fields remain invalid, and the normalized before/after values must
  differ.
  Binding names must be portable recipe identifiers and values are concrete
  scalars. The main Agent still reports natural-language facts; the writer does
  not ask it to author placeholders. Offline induction creates a parameter slot
  only when distinct real action values prove one reusable recipe. The arrival
  context exposes exact approved source-Page Region names. Runtime
  appends a supported observation only for an explicit formal Entry or Region
  probe, an approved reported effect Region with a committed `region_ref`, a
  byte-changed screenshot, a matching result and the same canonical Page. The
  action-source Region may differ from the reported effect Region. Navigation,
  menus, dialogs, Region reveals, passive animation and values not visible in
  both frames must use null. This reuses the existing main-Agent before/after
  judgment and adds no VLM call.
- Region 名称、页面标题、说明文字、时间/数值显示与空白背景仍不是功能入口，不能据此建立 Entry 或把静态内容
  结算为入口探索。它们只可作为一次明确的中间点击表面，且 `entry_id` 留空；Reviewer 核对该表面是否为 Agent
  有意选择、点位是否真实命中及动作是否安全，真实效果仍由后图判断。
- 框架只检查结构和可执行事实：JSON 类型/枚举/必需定位键、工具名和参数结构、最新 frame、坐标范围、
  当前页 Region 引用、提交的可选 bbox、Page Identity pending 提案，以及动作是否实际投递和帧是否变化；
  scroll 不把 Region bbox 当作执行边界。页面、Region、按钮与动作
  结果的语义正确性由 VLM 判断。summary/correction 可以为空；主响应顶层 reason、待结算的 `previous_action.reason`、待审的 `previous_tool_review.reason` 以及 Page Identity/Click Reviewer 的 reason 必须非空。这只是可读解释的存在性合同，框架不按字符串判定解释是否正确。动作后返回
  `not_applicable` 时降为 `uncertain` 保存。唯一的前后帧硬冲突是：同一 pending 动作的前图与最新 PNG
  字节完全相同却报告 `changed`。此时返回 `previous_action_frame_conflict`，不执行该轮提出的下一 GUI 动作，
  并要求主 Agent 只根据所附两帧重评最近动作；它不会把更早动作的目标或结果复用到当前 attempt。非完全
  相同帧中的状态栏时钟等无关变化仍由 VLM 判断，不按任意像素差自动宣布功能变化。
- `click.entry_id` 只在本次点击直接尝试框架派发入口或当前页面已登记入口时填写；若当前 `task.route` 下一步明确
  给出一个已验证导航入口的精确 ID，该次路线点击也绑定同一 ID。其他导航、恢复、关闭干扰或尚未登记的顺路动作
  留空。框架只按这个显式 ID 把动作结果结算到入口账本，名称相同也不会自动复用。
  入口 verified 或由 Agent 显式关联为 inferred 后，当前 `explore_entry` 才关闭并重新调度；不再使用
  `intent` 枚举或字符串重复门限制主 Agent 的中间动作。`survey_page` 先登记页面结构和入口，不执行入口功能；
  `explore_entry` 只处理派发入口、必要导航/恢复/干扰，以及途中首次遇到的页面和真实跳转边。与任务无关的
  已知功能留给后续派发。所有已知 survey 和入口均结清后，任务保持为
  `survey_page(phase=completion_ready)`，不存在无任务自由探索阶段，也不主动重做账本中已 verified/inferred
  的功能。若点击
  仍显式绑定已覆盖 entry，runtime 在 Click Reviewer 前返回 `entry_already_covered` 且不执行；当前
  `route_to_page/route_to_source` 路线第一步明确给出的同一精确 `entry_id` 是窄例外，只复用已有验证导航边，
  不会把已覆盖功能重新变成探索任务。其他必要导航使用该可见控件时清空 entry_id。
- `previous_action` 只结算仍 pending 的最后一个真实 GUI 动作，分析工具和审核不算上一动作。若落点要先
  完成 Page Identity，框架冻结第一轮紧邻动作的 VLM 评估，等落点登记后写入同一 attempt；后续工具轮
  不能覆盖。动作目标只来自 pending action 与 Reviewer；主 Agent 不再输出或改写目标名称，只用
  `previous_action.matches_intent` 判断该固定目标的真实结果是否满足绑定 entry。发现阶段没有预设目的地，
  连贯即时跳转属于已确认目标，即使其他入口也到同一 Page；来源 `task.page` 不是落地约束。真实变化只有匹配时
  才完成显式 entry 的验证；不匹配时保留真实动作证据和 unresolved entry，并以
  `action_did_not_match_entry` 反馈给 Agent。框架不按 before/after 像素变化替 Agent 判断是否终止入口。Reviewer 确认精确
  entry/点位/目标/安全后，主 Agent 在非空 `previous_action.reason` 中解释真实结果；`failure_kind=null` 保持入口
  unresolved/task-eligible 并允许继续当前任务。只有主 Agent 明确决定结束该入口时，`failure_kind` 才填写
  `temporarily_unavailable`（真控件但当前不可用）或 `not_interactive`（静态内容误登记）二选一。
  `no_effect` 仍是动作事实，`unreachable` 仍是执行前导航/定位结论，不进入失败分类。非空分类使 entry 保持 unresolved、
  `task_eligible=false`，不生成成功功能边。若一次点击只关闭前景层但未满足入口，主 Agent 可以保持 null 并在最新帧继续，
  不会再被框架强制分类门中断。动作上限只禁止再发新 GUI 动作，不能
  截断最后一个动作的评估、页面审核和边提交。
- pending 动作结算轮的模型视图不输出顶层 `current_page`，因为 runtime 此时绑定的页面仍是动作来源页，
  不是最新截图的已判定身份。来源页只通过 `arrival_context.source_page` 提供，动作本身通过
  `pending_action` 提供；最新页由主 Agent 的 `screen` 报告。动作前实际命中控件由 Reviewer 固定，
  `previous_action` 不再重复目标字段；最新落地页不能反推或改写已执行按钮。
- 同一落地响应只比较所附动作前图和最新图；实际目标或结果不满足绑定入口时，
  即使页面变化也报告 `matches_intent=false`。框架未增加额外 Page Identity/Observer 调用，也不按应用、页面或
  控件名添加 Prompt 特例。`previous_action.reason` 同时解释实际结果；当结果不符合预期时，主 Agent 根据前后图
  说明最可能的环境、状态、前置条件、落点或控件可用性原因。该文字进入 action history、图边 evidence 和入口最近
  结果，不由框架做字符串真值判断。
- 自主身份 map 不建立 screenshot hash 到 Page/Variant 的绑定，也不按当前 PNG 精确命中纠正、短路或合并身份。
  Page 与 material Variant 只由分阶段受限的 `screen` 语义字段，或主 Agent 接受的当前步骤 specialist 提案登记；
  framework 分配内部 `page_id/variant_id/state_id`。每个 Variant 保存自己的代表整图；旧的每 Page 单图缓存已删除。
  内部 frame ID 仅用于动作新鲜度、前后变化审计与防重复，不能决定身份。
  没有待结算动作时，若 Agent 报告的 Page/Variant 与当前语义身份冲突而又没有选择 identity 复核，
  runtime 返回自然语言 `page_identity_conflict` 并不执行同轮动作。真实动作落地可登记另一个 known/new Page；
  `no_visible_change` 与另一 Page 或 Variant 仍构成需要 Agent 重评的矛盾。
- 直接 `page_identity` 与 `report_record_error(kind=page_identity)` 都把最近一次已结算 GUI 动作作为语义到达上下文交给
  当前步骤 specialist；只含来源页、动作类型、目标、落点、是否变帧和可读结果原因，不含内部 frame/hash 值。
  自然语言投影直接读取运行时的 `landed_page/result_reason`，并兼容普通历史记录的 `landed_screen/detail`，不会静默丢掉落点或结果理由。
  Page 复核看全部已登记 Page 候选，Variant 复核只看已选 Page 的 Variant；两者都看当前/候选完整截图与到达上下文，
  同页 scroll 是连续性线索而不是身份硬规则。
  `known/new` 均形成待主 Agent 审核提案，不再因同像素被降级。面向主 Agent 的返回是自然语言结论、理由、关键
  支持/冲突证据和复核要求；`report_id`、单独的 `reported` 及其他不能查询或引用的内部记账字段不进入 Prompt。
  `entry_id` 等为精确绑定对象而必须回传的框架 ID 保留，并由框架先明确提供；Page/Region 当前使用框架给出的
  自然语言名绑定。
- 主循环不再有 `max_actions*6` 的隐藏决策轮上限；当前任务的 attempt_count、最近结果与通用 repeat warning 用于让主 Agent
  识别重复并换路线。`report_record_error` 只登记争议且始终可见。自主模式下
  `--max_actions 0 --max_states 0` 明确关闭运行级紧急上限；正数仍可用于
  有界实验。`max_states` 现在计算真实 graph State；同一 Page 的新 material Variant 会占用一个 State，
  重访同一 Variant 不增加计数。上限停止也
  永远不作为探索完成判据。
- 每个真实 action trace 记录当前内部 `exploration_task_id`。同一任务中，若后续动作的完整 before-frame、
  `tool_name/operation/arguments` 与此前已执行且已观察的真实 GUI 动作完全一致，runtime 在 dispatch 前返回
  `repeat_task_action_on_same_frame`。该 visited state-action 边界覆盖真实 click/scroll/navigate/gesture，排除
  `navigate(wait)` 和分析工具；换任务、换帧或修改规范化动作均不受影响。框架不判断 Back、目标或路线语义。
- `finish_exploration` 是提议。框架只返回页面 survey/Region/entry/restore 的事实缺口；已登记页面
  尚无 Region 且没有精确 State 的空 Region 调查证书时属于明确缺口。主 Agent 根据
  `attempt_count` 与重复真实结果判断某入口已经 `stuck` 后，不再重复同一路线/坐标；它先用
  `report_record_error` 保存争议，再在 `unreachable_evidence` 中提交该任务的精确 `entry_id`。框架只校验
  ID 是否存在、是否属于所声明 Page、是否尚未 covered；通过后入口保持 unresolved 证据但停止调度，其他缺口
  照常返回。页面/Region 级不可达将 `entry_id` 留空，框架不从 subject 文字猜测入口。证据按其声明的已登记
  Page 保存供 debug，不能找到页面归属时作为缺口退回。自主模式保存
  `autonomous_natural_map.json`、`autonomous_regions.json`、
  `autonomous_entries.json`、`autonomous_temporary_states.json`、trace/debug、前后截图和内部 graph，不生成
  或宣称 guided `completion.json`。`autonomous_regions.json` 顶层 v8 中的 Region group v5 为每个 occurrence
  保存 `occurrence_ref`、Page State 到局部 Region 状态的映射、身份延续 `state_ids`、经 Entry Reviewer 确认可见的
  `visible_state_ids`、覆盖版本/来源，并保存 group 状态定义、真实转换和 Entry
  Reviewer 覆盖审计、证据基础和 `entry_review_evidence_generation`；顶层 `empty_region_surveys` 保存无纠正空提案
  确认没有功能 Region 的精确 State；
  `autonomous_entries.json` v6 为稳定 Entry 保存 `operation`、`subject`、owner Region、代表 occurrence、局部
  `required_states` 及兼容
  `source_state_ids`。Region bbox 只在当前运行的同一 State 内临时沿用，
  State 变化或 resume 后不复用；entry bbox/frame 仍只属于当前帧 observation。
  证据代数只在真实 GUI 动作被主 Agent 判为 changed，且动作前后完整 PNG 字节确有变化时增加；动态像素、
  无效果动作和 sibling audit 集合变化不会重置讨论。旧 resume 没有 accepted audit 时不会被误当成完成；
  multi-State 旧 occurrence 缺少 State 归属时也不会被猜测性复用。
- `finish_exploration` 始终可见。finish 被拒后，`remaining` 和结构化 rejection 给出事实缺口；主 Agent 根据
  最新截图、账本和历史决定下一步，框架不通过隐藏 finish 或强制某条路线推进。重复 finish 不再有专用状态机；
  无真实 GUI/Page/Region/entry 进展的任何框架拒绝均进入同一计数器，包括工具统一返回的 `status=rejected`。无待结算动作时，当前任务连续 5 次暂停并
  调度其他任务，跨任务连续 10 次停止遍历；若真实动作已经执行但后验判断连续 5 次未被接受，则不切换任务，
  以 `pending_action_assessment_limit` 停止，把动作保存为 `assessment_unavailable`，将绑定 Entry 结算为
  unresolved/non-eligible 并清空 pending，同时保留 completion gap，避免误报成功或 resume 重复执行。
  一轮至多计一次，真实动作或正式账本提交清零两级计数。只读查询、等待或
  首次 `report_record_error` 不单独清零或增加计数；同 task/frame/kind 的重复报告作为明确拒绝进入计数。
- 自主模式支持对自己的 `graph.json` 使用 `--resume`：恢复内部图、自然语言页面关系、Region、入口、
  Entry Review 待讨论轮次、证据代数、临时状态和最近 8 条 trace，并继续在原目录增量写入。恢复时不沿用旧帧 bbox，当前
  页面也必须由新截图重新报告；旧进程中断时仍 pending 的入口会重新成为任务。旧产物中的历史字符串模板
  只作兼容数据读取，不能在续跑时生成新的同质关系。顶层 `scope_states` 保存页面交互模式和应用级状态的最小真实观察账本；
  旧 v7 快照缺少该字段时按空账本恢复。

## 5. 页面身份

- Region-lazy Page map 在一次整张实时截图调用中选择唯一 active interaction surface 并提出
  其中的候选 Region，不再追加 active-region filter。旧整页回退
  semantic inventory 才在同一次调用内继续枚举 area 与控件；
  overlay 即使只占小区域也优先，背景只作宿主页语义上下文且不得输出。顶层 `surface_kind`
  是整图阶段的唯一结构化结论；block role 只负责组织内容，不能触发 surface 重判或覆盖顶层结论。
  只列下一次点击能触发自身功能的前景控件；被前景层接管的背景控件不得输出。模型不再承担
  `scope/interaction` 分类，旧缓存和 fixture 才兼容读取这些字段。
- Page map 的 Region 分区描述“预计共同呈现的内容”，不是“一个区块只对应一个功能”。
  模型依据当前截图中的容器、视觉边界和呈现关系进行一次观察级划分；可独立出现、消失或
  被替换的部分应当分开。名称和描述只概括可见内容范围与呈现关系，`rN` 只在本次回复中有效。
- Region 是当前操作界面中预计共同呈现的一组内容，可以包含不同功能和只读信息；Region
  本身不以“是否直接可点击”定义。只有其中本帧可直接接收操作的控件进入 Explorer；仍然
  可见、但被前景界面接管的底层栏或面板只作截图上下文，不属于当前 Region 表。
- 无操作入口的信息提示浮层（toast/snackbar/banner/tooltip）不成为 Page、Region 或按钮；若提示
  浮层含 Undo、View、Close、链接等真实入口，只登记该入口而不把提示正文强制变成按钮。此类非阻塞
  提示不遮蔽底层页面，真正接管交互的 dialog/menu 仍按 active surface 处理。
- semantic inventory 顶层 `passive_feedback_present` 只表示当前帧仍有无操作入口的临时提示。
  登记层看到该值为 true 时不登记当前截图，而是有界地重新抓取稳定画面并用
  `force_refresh=True` 重做清单；清除后的截图和元素才进入 Page/Variant 身份、Region 与落地验证。
  两次刷新仍为 true 时失败关闭，避免提示遮挡/消失制造伪状态。
- `page` 名称描述当前最前景功能界面本身，不沿用不可操作的背景标题。同一活跃界面的临时文字、
  数据或命名措辞变化不产生新身份；前景界面新增或移除一组自己的功能入口时才是不同状态。

### 5.1 普通点击后的登记

正式路径由 `IdentityResolver` 统一处理普通落地与 Router；以下
`registration._try_map_guided()` 细节只描述
`GUIWALK_REGION_LAZY_INVENTORY=0` 的旧整页回退兼容路径：

- `Router.expected_destinations()` 构造已验证的一跳候选，顺序为点击标签的已知目标、源页面、
  其他 verified sibling 目标和图前驱；全部候选都会进入第一轮，不按数量截断。
- `confirm_arrival()` 先按稳定 Variant 去重，不使用当前 VLM 临时页面名称做严格相等筛选。
  第一轮使用全部局部邻居，未命中再扩展到全部已登记界面。多个候选先按已登记的可分性文本描述
  选择可能项，再逐张与当前完整截图比较；首选不匹配后继续剩余候选，不能直接判 `NEW`。页面裁判
  不制作候选 atlas，也不接收名称、区块、元素、持久 ID 或动作预期。裁判以最前景
  活跃界面的功能入口及组织为准；临时消息、动态内容、时间、数据和轻微视觉差异不影响匹配。
  两图 Prompt 明确规定同一页面的不同滚动位置仍属于同一界面，即使当前可见条目子集不同；
  新增前景 surface 或改变功能组织仍必须分开。
- Page 名称不参与身份判定。候选筛选应根据全部已登记 Page 描述为新 Page 提出有清楚差异的
  备用名称；框架不按名称字符串完全相同触发额外截图复核、合并或改写旧名称。统一 IdentityResolver
  返回已知 State 后，Router 直接采用该 Page Identity 结果；expected destination、首次进入
  来源 Page 和 route context 都不能二次否决或拆出 source-local 执行 State。进入来源只保存在
  transition attempt 和实时导航栈。`back=true` 的可见返回控件在提交时写
  `return_via_control`；旧图若遗漏该字段，Router 从同一来源 State 的元素身份恢复该语义。
  若旧元素也没有 `back=true`，但已验证点击在当前 route context 中落回该执行 State 的实时
  进入来源或导航栈中的更早祖先，则只在该上下文恢复 `return_via_control`；这覆盖一次关闭多层
  flow 的真实返回，不按控件名称猜测，也不改变其他来源下的动作语义。
- 已知 State 的落点若来自状态型操作并明确要求重新观察，且当前运行有 live inventory provider，
  登记层会在该已知 State 上重新采集当前元素，而不是直接继承旧清单。这使 Local HTML fixture oracle
  与显式旧整页 inventory 能看见开关后的当前状态；普通 Region-lazy 已知页重访仍复用既有 Region
  清单，不额外增加全页观察。
- Reverse probe 的返回身份先比较“返回后的实时完整截图”和“触发本次 `A→B` 的精确操作前完整
  截图”。若 Page Identity 返回 `same_page=true`，直接复用 A；不再拿 A 的 canonical/首屏截图
  二次否决。若未命中，才回到统一 IdentityResolver 识别实际落到的其他已知页或新页。
- VLM 选择旧候选后，普通实时感知只刷新该状态的截图和元素，不允许 Region、名称、
  `surface_kind`、来源上下文或内容规则改判为另一状态。
- `NEW` 才进入普通新 Page 感知/登记路径；确认已知页面时
  可复用其持久身份与稳定元素。stateful、restore 或同页像素变化的落地禁止走纯继承，必须执行
  一次普通实时感知。
- overlay/dialog/menu 的 Region 定义可以跨页面共享；只要它提供自己的一组功能入口，就按该
  活跃界面自身命名并形成独立 Page@Variant 点。返回目标若依赖进入路径，由 source-local
  attempt/route context 记录，不把背景页面写入该活跃界面的身份。
- 已分配的 `page_id` 冻结；revisit 刷新实时截图和 observation，但稳定 Region 表只经节点间
  VLM correspondence 合并，不能由本轮 raw inventory 改名、扩展或重算 Page。
- 页面身份确认后，框架把两个节点各自的稳定 Region 文本表一次性交给 VLM；VLM 只回答两个
  页面内哪些 Region 属于同一个区域，并给出两边最终 Region 表。框架把本次局部标签映射回稳定
  `region_id` 后才允许共享和合并。raw role、raw target wording、临时数组 ID、`category` 或
  UI `type` 都不能直接参与去重、路由或页面合并。

- 该合同在 Page、Region、scroll viewport 和 Router landing 统一为四条规则：框架拥有稳定身份；
  页面以本次完整截图为证据；Region 只在页面身份确定后由 VLM 对齐两边已登记文本表；动作完成后
  若预测错误则以实时落点修正预测边。映射不可用时 fail closed，不得退回字符串同名、按钮集、
  pHash 近似或历史坐标合并。
- 同一来源动作存在旧预测边与后来的 live-corrected 边时，动作账本保留两者；路由视图根据纠正
  attempt 的 `predicted_target`、`actual_target` 和 `prediction_match=false` 隐藏旧预测目标。
  普通前向动作的纠正跨进入上下文生效；只有明确的 Back/return 动作读取 `route_context`，因此
  其他进入上下文的合法返回目标不受影响。
- 复合控件把稳定功能名放在 `name`，把当前子按钮/值/状态放在可选 `action_label`。重访只刷新
  alias 与实时状态，不因 `Sign in`、`Connected` 等文案变化而换 ID；与稳定名相同或属于纯展示
  内容的 alias 会被清理。grounding 与文字回退优先使用 alias，图和 capability 仍使用稳定功能名。
- 单目标 grounding 解析器校验 `found`、`coordinate_space`、规范化整数 bbox、正面积，以及点击点
  位于 bbox 内；Region-map 可见目标使用同一几何合同。几何合法只记为
  `diagnostic.local_validation=locator_schema_validated`，不授权点击。正式 semantic 点击热路径
  随后调用 `AnnotationReviewer.review_target()`，让独立模型同时查看未标注的当前完整截图和
  以候选点击点为正中心的 201×201 干净局部图；靠近屏幕边缘时以中性灰补齐，确保中心像素仍是
  实际候选点击点。Reviewer 从完整截图理解上下文，从局部图判断中心点是否位于目标控件内。
  红色目标框/黑色点击十字只保留为人工诊断 artifact，不进入 Reviewer 输入。只有 `target_review_accepted` 才返回点击点；明确拒绝时把
  Reviewer 原因交给 Grounder，绕过缓存纠正一次并再次复核。Reviewer 不可用、回复非法或第二次
  仍拒绝都 fail closed。fixture oracle 等确定性坐标来源继续跳过该 VLM Reviewer。可用性与安全
  仍由 inventory/frontier 处理，动作效果仍由 fresh landing 独立验证。
- 若 Grounder 回复被格式、坐标、目标确认或前景 surface 检查拒绝，本次不会调用 Reviewer，也不会点击。框架把
  具体状态、原因和已有原坐标写入 `correction_hint`，绕过缓存用完整截图纠正一次；超过 `0..1000`
  明确记为 `coordinate_out_of_range`。纠正后几何合法才进入 Reviewer，第二次仍不合法则失败关闭。
- 2026-08-02 Calendar 实时运行暴露出 Grounder 未遵守 crop 坐标基准并误点 GNOME 顶栏。对同一
  截图和 `+` 目标的真实 A/B 中，Region 裁图为 1/3，完整截图为 3/3；当前运行路径已删除 Grounder
  Region 裁图和坐标回映，统一使用整图坐标，等待实时遍历验收。

#### Region 同现分区后续 TODO

- 用相邻 State 的实际出现/消失证据区分“单次 Page map 抖动”与“Region 生命周期真实拆分或合并”。
- 调整当前 1:N / N:1 分区规范化：确认成员能够独立出现后保留独立 Region，不再强制折回旧的
  单 Region 分区；仅属划分抖动时才复用旧分区。
- 将 Region 同现关系与控件功能等价、Explorer 覆盖结论分开。处于同一 Region 只能提供局部上下文，
  不能让其中一个控件的验证结果自动覆盖其他控件或能够独立变化的 Region。
- 保留 `region_transition.v1` 的 introduced/removed/result binding，使“创建对象后出现的新 Region”
  仍能被后续采集 recipe 可靠引用。
- 在复用旧图或 resume 前记录 Page-map 分区合同版本；旧合同产生的 Region 表不得在没有重新观察证据
  时被解释为新的同现分区。

### 5.2 Router 落地身份

Router 每次计划内跳转、Back 或恢复后都先运行统一 Page 身份流程：

- 规范化像素严格相同且唯一时直接复用 State。否则，框架把全部已登记 State 按稳定
  `page_id` 去重成 Page；同一 Page 只提供一份保存的名称、Page Observation Region
  名称/描述和一张代表截图，不按 State 逐张穷举。
- 候选筛选一次接收当前完整截图、可用时的来源父页面截图、点击入口文字/位置，以及上述
  已登记 Page 描述，按可能性返回一个或最多两个候选 Page。来源父图只帮助理解到达路径和
  生成备用新页名称，不是身份候选；计划 `dst` 也不能替代真实视觉确认。
- 候选筛选与备用命名直接复用 Page Identity 的共享“当前操作界面”定义。备用名称只命名
  按该定义从当前完整截图确定的操作界面，来源父图和点击入口只提供到达上下文，不能改写
  当前截图中的命名对象。其他可见内容不能仅因为由此前动作产生、位于最前方或文字与某项
  功能相关，就改变当前操作界面的身份；不属于当前操作界面的内容不参与 Page 匹配，也不得
  出现在备用名称中。
- 候选筛选同时返回 `proposed_new_page_name`。它只是所有候选均被后续两图裁判排除后的
  新 Page 备用名，不表示筛选模型已经判定 `NEW`。候选筛选看到全部已登记 Page 名称和 Region
  描述，必须给出与这些页面有清楚差异的名称；登记阶段不再按自然语言字符串完全相同追加
  同名扫描或双页面名称消歧。
- 页面裁判每次只接收一张登记截图和一张当前截图；不传 atlas、候选编号、名称、区块、元素列表、
  持久 ID、`surface_kind` 或动作预期。
- 两图页面裁判直接复用候选筛选所用的共享“当前操作界面”定义，并先检查图2当前截图是否有不属于
  目标应用的临时前景内容。命中时只返回
  `is_interruption=true + same_page=null`；登记层立即调用现有 InterruptionDismisser，关闭后
  用新截图从候选筛选和两图裁判重新开始。只有 `is_interruption=false` 时，裁判才分别确定两张
  完整截图中的当前操作界面，只比较这两个界面本身并返回 `same_page=true|false`；共同可见的背景
  只能帮助理解，不能单独证明同页。不解释或判断 Variant。该调用固定
  开启 thinking；调用结束后恢复共享 agent 原有设置，其他 VLM 角色不随之开启 thinking。
  关闭失败、截图未变化或重判仍有 interruption 时返回 `UNRESOLVED`，当前截图不得登记为 State。
- 2026-08-02 Calendar 实时运行暴露了这条清障路径的时序缺口：Page Identity 看见系统更新横幅后，
  横幅在 Dismisser 取得的新截图前已经自然消失；新截图只剩应用自己的 New Event Dialog，Dismisser
  仍选择 `Cancel` 并关闭了真实功能页面。运行在 Page candidate selector 前停止并保留证据；当前
  代码尚未在执行关闭动作前重新确认最新截图中仍存在原应用外 interruption。
- IdentityResolver 不为当前截图先做整页语义感知；候选文字只来自历史 Page 已保存的
  Page Observation 结果。shortlist 排名中的候选按顺序逐一做二分类完整截图验证，首个
  `same_page=true` 即进入同 Page Region 对齐；全部为 false 后才登记新 Page。
- 候选筛选请求失败、JSON 无效、候选为空、标签越界或备用名称缺失时 fail closed：只对第一个
  有序 Page 做一次二分类兜底；若它匹配则复用，若不匹配则返回 `UNRESOLVED`，不得由筛选失败
  直接推导 `NEW`。选中候选的代表截图缺失或两图裁判无有效回复也返回 `UNRESOLVED`。
  旧三分类 Page 回复不再兼容。pHash 不排序、筛选或合并候选。
- 返回实际页面后，Router 才与计划 `dst` 比较；不一致则从实际落点重规划。若局部和全局候选
  都返回未知，同一张实时 on-app 截图进入普通登记路径；登记出的新 State 或重访 State 作为
  实际落点。只有画面缺失/off-app 或普通感知登记也失败时才失败关闭。
- 当前按 `page_id` 去重发生在两图裁判之前，而 `page_id` 仍由备用页面名称生成。真实 Calendar
  运行确认，旧 Prompt 明确允许重复名称时，提醒时间下拉层和事件对话框被写成同名，候选只保留
  下拉层代表截图，事件对话框因而重复建 State。当前 Prompt 已恢复“新 Page 名称与全部已登记
  Page 有清楚差异”，但重新部署后的遍历被上述清障错误提前中止，仍未取得真实候选命名结果；
  它不依赖模型措辞完全一致的事后字符串检测。
- 点击进入外部应用或系统浮层、再由 Back 返回目标应用时，恢复登记把点击前最后一个可信
  State 作为 source-local 候选上下文；真实 relaunch 也先用原 State 的局部邻居。该上下文只
  缩小第一轮候选，未命中仍扩展到全图并采用真实落点，不能把原 State 强制当作恢复结果。
- App focus 只使用虚拟机/设备提供的前台归属：Android 读取 Activity 与前台 task affinity，
  桌面读取启动时绑定的 window ID/PID/transient 关系。它不接收动作前后截图、目标语义或
  Prompt，也不使用 VLM 缓存。系统证据为 false 才进入既有 Back/relaunch 恢复；系统证据
  暂时不可用时稳定后重读一次，仍不可用则以 `focus_unknown` 停止，当前画面不登记。
- Region 比较只发生在页面身份已经确定之后。新节点先登记当前状态下可直接互动的 Region；随后
  将新节点与来源节点的 Region 文本表比较。两个已知节点之间只比较各自已有的 Region 表，不发现
  新 Region。一次调用完成整对节点的对应关系，不逐 Region 调用，也不向 VLM 暴露稳定 ID。

## 6. Router 合同

- `plan_route()` 对 verified 边和共享 Region 上目标唯一的预测边做等权最少 hop BFS；两者没有
  人工权重差。状态型控件由探索事务执行并恢复，不得继承成 Router 中转边；目标未知、共享目标
  有歧义、多步 recipe-only 和隔离边也不进入路由。
- 全局 frontier 选择复用同一套 BFS 语义，一次寻找全部待探索目标，而不是为每个目标重复
  构造和搜索路由图；目标深度优先，同深度按调度器传入的图顺序打破平局。
- 共享预测边只是 `can_execute`，不是 `can_trust`。当前来源没有真实点击证据时不得标为
  verified；预测与实时身份不一致时记录原预测和实际落点。普通前向动作修正该 source-local
  canonical action 后重规划，返回动作则只修正当前进入上下文。
- 每个 hop 都重新定位并执行 selector，然后独立识别实际落地；不得用计划目标兜底。
- Router 从图中读取已映射的稳定 Region 与 canonical action 描述。普通 Region 直接在当前完整
  截图定位；可滚动 Region 使用当前完整截图与首次登记保存的 Region 长图联合定位。不枚举当前
  raw inventory，也不做 raw label/role 字符串匹配。历史节点元素只提供动作语义，不提供可执行
  坐标或固定滚动次数。
- 属于已确认可滚动 Region 的待选目标优先把当前完整截图与首次登记保存的 Region 长图一起交给
  单目标 VLM，输出 `visible|above|below|absent|map_mismatch|uncertain`。`above/below` 每次只执行一个
  区块内有界滚动段，随后立即以新截图和同一长图重判；画面不再移动、达到长图登记安全上限或模型
  无法继续对齐时 fail closed。`absent` 只有长图也不含目标时成立。`map_mismatch/uncertain` 或长图
  缺失时记录本次 occurrence 的定位失败并继续其他候选；不再回退 canonical top +
  `scroll_steps`，任何路径都不得使用历史坐标点击。
- 长图联合定位只在目标完整操作框严格位于当前 Region 的纵向可见边界内时接受 `visible`。
  bbox 接触上边界或下边界分别转为 `above` 或 `below`，使用 Region 中心继续一个滚动段后重判；
  仅露出标题、图标或其他文字不能证明该控件可安全点击。提示合同和 runtime bbox 验收执行同一
  规则，runtime 验收不增加模型调用。目标执行滚动复用采集路径的 Region-relative 手势比例，
  小型独立滚动区块不再按整屏 `0.42` 跨度移动。
- 实际落到另一个已知页面，或未知画面被普通登记为实际 State 时，都从该 State 重规划。
- 已确认 hard-reset 根节点后若实时目标缺失且动作未执行，路由结果仍保留该根节点作为实际落点；
  调度器从根节点继续并临时冷却目标，不把未点击误报成未知落点。
- relaunch/hard reset 后的 on-app 截图同样遵循实际落点规则：候选未命中不终止，而是普通登记为
  重访或新恢复起点；只有 off-app、截图缺失或登记感知失败才停止。状态型动作结果未知仍保持
  fail closed。
- 对视觉相同但返回目标依赖进入路径的页面，attempt evidence 保存 `route_context`；派生路由视图
  暴露 `route_contexts`，Router 优先选当前进入来源已验证的目标。当前入口第一次出现、尚无该
  context 的 verified 返回边时，明确的 Back/return 动作以本次进入来源作为待验证预测目标，而不
  复用旧入口的无上下文返回目标；实际落地仍可纠正并持久化。无上下文且同一 selector 有多个
  verified 目标时 fail closed，不把其中一个目标当全局真值。
- live landing 若从当前 State 回到其已记录的入口父节点，即使控件或 VLM 漏标 `back=true` /
  return effect，也按导航栈结构认定为返回：弹出层/子界面从栈中弹出，父节点保留它原来的进入
  来源。该判断不使用页面类型、控件名称、坐标或应用规则。
- 无 forward path 或动作后无进展时，可以尝试一次 Back；Back 落地被识别后才能记录
  `effect_kind=return|dismiss_overlay` 的虚拟导航边。
- `not_attempted` 或 `dispatch_unknown` 后禁止补偿 Back，避免在不确定是否投递动作时再改变状态。
- 预算内仍失败时可以 relaunch/hard reset，但只采用实际识别的已知落点。
- Router 成功返回后，调度层再次调用正式 registration 核对；若与目标不一致，会记录
  `backtrack_false_arrival` 并把 cursor 调整到实际页面。若实际已知 State 中存在目标的
  同一稳定 Region 与同名语义控件，则该实时 State 已满足本轮 route goal：调度器在这里继续，
  不再要求精确历史 `state_id`。Region role/name 不参与这一判定；同名非 stateful 控件在该
  稳定 Region 上已有 landing-verified CLICK 时，可结案历史 occurrence。
- `route_to()` 返回 `RouteResult`：`arrived|retryable|blocked|dispatch_unknown`，并携带实际落点、
  失败类型、投递状态和尝试次数；两值解包仅作为旧调用兼容层。
- Router 失败后的实际画面若被确认是另一个已知 State，调度器先在本轮冷却目标；若没有其他
  可执行工作，会重试一次。两次仍无法回到目标时，只把目标历史 State 中剩余 occurrence 记录
  为本轮 `route_unavailable`，不写永久 `unreachable`，也不生成成功动作或共享覆盖。失败次数
  按目标 State 独立维护，不使用跨目标累计阈值终止整次遍历。发现新节点会在第二次失败前清空
  冷却和计数。结案循环读取同一 State 后续才释放的 source-local 候选，直到本地 frontier
  全部收敛，避免留下已达到失败上限却不再可调度的目标。
  Router 返回 unknown/off-app 时，调度层先对返回截图执行统一焦点恢复和正式 landing 登记；
  若得到已知 State，就把它作为本次失败的实际落点和后续 cursor。恢复后仍无法确认任何已知
  落点，或 stateful restore 目标不适用该结案，仍以 `routing_incomplete` 或
  `state_restore_failed` 停止。
- graph 保存把 source-local 实时元素状态按 `uid` 回填到节点；没有 `uid` 时只在同一 State 内
  使用唯一元素编号，不跨来源匹配。resume 以通过证据校验的异常账本补正落后的节点快照，因此
  `route_unavailable` 等真实终态不会因进程重启重新进入 frontier；无效或旧式有界失败仍重开。
- 已验证真实正向 `A→B` 后，如果图中没有与本次进入上下文兼容的 verified 直接 `B→A`，
  Reverse Edge Explorer 在普通 frontier 前调用一次；已有间接 route 不能代替这次直接边探查。
  同页普通 Variant、stateful/restore、已经由 Back/Close 产生的正向动作、非 CLICK 或复合开页动作
  不触发。其余是否有必要立即返回、安全性和候选是否适合执行由同一个 Prompt 根据两张截图、
  A/B 描述、刚执行入口和平台判断，不按按钮名、页面名或固定控件类型硬编码。动作入口正常产生、
  仍实际接收操作的当前界面默认继续遍历；不能仅为建立或验证返回路径而离开它。只有必须立即恢复
  来源页时才选择动作，否则 Prompt 返回 null，框架留在当前页面继续遍历。
- Prompt 只输出 `{"action":...}` 或 `{"action":null}`。可见入口为
  `CLICK + target`，由 latest-frame semantic Grounder 定位；没有合适可见入口时才可选择 Android
  `navigate_back` 或桌面 `PRESS Esc`。Region-lazy 与旧整页感知共用这一两图合同，不再构造
  purpose/effect 候选表、`choice_id`、`NO_ACTION/DEFER`、fallback control 或
  `deferred_return`。
- 具体反向动作在 grounding/`env.step()` 前建立 `B→unknown` probe attempt，并用
  `trigger_forward_attempt_id/intended_target` 关联触发它的 forward attempt。Prompt 因无需立即返回、
  无可靠候选或安全原因返回 null 时，只在 forward attempt 记录 `candidate_not_found`。grounding failure、dispatch unknown、
  no-effect、身份未知和 actual landing 原地更新 probe attempt。
- 动作后统一 fresh identity。真实落到 A 写普通 `B→A`，落到 C 写普通 `B→C`，随后从该真实落点
  沿 verified 图恢复 B；`reverse_probe` 只是 provenance/evidence。新边只使用正式
  `peer_navigation|return|dismiss_overlay` effect kind，不引入 ReturnEdge/RecoveryEdge。
  committed 且 landing-verified 的真实落点才能进入 routing view。
- landing-verified 的可见反向目标同时结清 B 上唯一同名的 source-local 控件。控件若在 probe
  当时已经登记则立即结清；若 Region-local observation 稍后才发现它，调度阶段从该 reverse
  attempt 补做结清。普通 Explorer 不再重复执行同一控件。平台 Back/Esc 没有控件 occurrence。
- Router 的实时进入上下文是导航栈关系，不是“最近一次从哪个页面观察到当前 State”。前向动作
  记录目标的父 State；返回动作弹出当前 State，并恢复目标此前的父上下文。否则
  `parent → child → grandchild → child → parent` 会把返回后的 child 错记为从 grandchild
  前向进入，进而制造 source-local 重复 State。同一 source→target 已有 verified 平台返回边时，
  该 source 上落到同一 target 的控件点击可补正为 `return_via_control`；不使用页面或控件名称。
  hard reset 清空实时栈上下文。
- Router 恢复被探测目标成功后，调度层会用恢复后的实时截图再做一次正式 registration，刷新
  reconcile 使用的 live Region/元素证据。探测失败先经一次有界 app 恢复；恢复后的实时画面只要
  能登记，就以其实际 State 继续，不能因预期身份未命中直接终止。
- 返回探测控件若在点击前定位失败，动作尚未投递，框架保留当前目标页、不建边并继续探索；
  它与“动作可能已投递但落点未知”分开处理，后者仍然失败关闭。
- 若返回来源本身是 overlay，关闭后真实落到相同 `page_id` 的裸宿主页属于有效的实际落点；
  Router 记录 overlay→裸宿主页，再从该宿主页重放动作恢复原 overlay，而不是把两张截图当同一 State。
- 表单输入等复合预动作、stateful probe/restore 和非 CLICK 动作不触发 Reverse Edge Explorer；
  截图中的立即返回必要性、风险、不确定性与是否适合执行由同一两图 Prompt 判断并返回 null。
  `--no_return_path_verify` 可在隔离调试时关闭该默认行为。

## 7. 动作与落地事务

- 点击前必须 fresh capture 和 live rebind；存储坐标只作证据，不能直接执行。
- 第一次定位后的点击若被真实帧判为 `no_effect`，第二次定位会携带上次已执行点及“必须选择不同的
  可操作部位”的纠正信息；模型仍可返回 `found=false`。两次均无效果才把该 source-local occurrence
  退休，继续调度其他目标，不把失败扩散为共享覆盖。
- `ActionEdge.attempts[]` 在 `env.step()` 前先写 attempted；动作结果随后更新同一记录。
- 当前点击效果主要由 before/after pHash 与落地身份推导：相同 hash 为 `no_effect`，变化且
  身份一致/变化有解释时为 `transitioned_consistent`；结构化 stateful 证据优先。
- 登记边界同时返回本次 landing 的 live element inventory。节点重访可以继续保留 durable
  element ledger 的历史身份，但 state value、当前功能差异和 inverse selector 只能读取这份
  live inventory；旧节点字段不得覆盖实时截图证据。
- 截图 sidecar 的存在不参与判断 State 是否已登记；权威图中没有该 State 时，同 ID 文件只是
  可能由中断留下的孤儿。新 State 登记会替换它，已知 State 重访则继续保留原 canonical
  screenshot。这样恢复中断不会产生“新元素表配旧截图”的混合节点。
- 已知 State 的普通重访不会因 live inventory 恰好只有一个区块就向 durable ledger 追加目标。
  实时别名映射只服务当前帧的目标对应；真正新增的功能界面必须由通用 Page/Variant/State 身份
  合同表示，不能靠区块数量或布局捷径合并进旧 State。resume 原子重建必须恢复节点的
  `semantic_blocks` 与 `perception_mode`，使重访复用真实持久 Region 表。
- live inventory 中唯一的规范化名称对应可为持久目标提供本帧 enabled/state value，但整页清单
  漏掉图标、只输出父行或发生别名漂移时，不能据此宣告已登记的首屏功能目标不存在。该目标仍交给
  Explorer，执行前由单目标定位在当前整图确认；定位失败走普通 occurrence 重试/退休，不直接点击
  历史坐标。历史明确位于折叠下方的目标必须已有完整 Region 长图才进入 frontier，而且该门对当前
  与远程 State 使用同一条件，不能出现“远程有候选、路由到达后候选消失”的往返。
- stateful 事务在登记 landing 前冻结点击前 `before_value`。revisit merge 可以把 canonical
  element 更新为实时 after 值，但效果判断、mutation 记录和 restore 仍使用冻结的 before，
  防止引用同一可变元素对象时把 `off→on` 错算成 `on→on`。
- probe 还保存执行器专门保留的 pre-click 整屏 pHash，不能把点击后 cursor 当成事务基线。
  restore 的 fresh 结构化值等于 before 即成功；结构化值为 `unknown` 时，只有恢复帧精确匹配
  pre-click 基线才以视觉回环结案。两种证据都不足时以 `state_restore_failed` 停止，且不再次
  点击该非幂等控件。
- probe 只打开确认 surface 时允许暂存 `after_value=unknown`。若随后执行的普通
  deny/dismiss/back 返回原 source State，且本次 fresh inventory 明确看到同一状态轴仍等于
  冻结的恢复候选基线值，则清除 pending mutation，禁止再把原控件当作 inverse 重点击一次。
  清除时把 `restoration_kind=verified_baseline_return`、冻结恢复值和 fresh observation 证据合并到
  触发该最新真实落地的 committed、landing-verified attempt；resume 和 completion 从同一持久
  证据判断事务已闭合。
  对互斥选项组，这个值来自原选中 restore 候选，而不是未选中 probe 候选的 before；旧图缺少
  独立值时，先从 source State 已登记的精确恢复候选推导，再兼容回退到 probe before。返回页、
  fresh 结构化值或 baseline 任一不成立都不会清除事务。
- 同一个确认 surface 再次出现时，dismiss/return 控件可能已经因前一次探索标为 `complete`。
  若当前存在 `after_value=unknown` 的 pending mutation，Router 对该 surface 已保存
  landing-verified CLICK，并按本次到达上下文把它解析为返回事务 source 或 source 当前
  live navigation stack 上的祖先 State，调度器只重开一个 execution-only 副本；原
  occurrence 的 durable completion 不变。该副本仍须在当前截图重新定位并重新验证落地。
  目标不在当前 live stack、缺少 verified return 图证据或控件当前不安全/不可用时 fail closed。
- 可逆 stateful 变化若未增加或移除功能，不创建持久 Variant：未提交的临时观察会被压回源
  节点，并用 live inventory 中的 inverse selector 立即恢复。只有功能集合真实变化时才探索
  新 surface。`stateful_no_effect` 只有在 fresh landing 且 pHash=0 时才能成为完成证据。
- 对同一 `group` 中互斥的可逆状态选项，事务同时保存本次 probe 选项和原选中选项；restore
  重新定位并选择原选项，而不是假定 probe 选项可再次点击恢复。group 只表示功能相同、数据值
  不同的重复备选项，不能合并后果或入口不同的控件。
- `state_key` 的运行时身份统一折叠大小写、空白、下划线和连字符，避免同一状态轴因 VLM 拼写
  漂移而失去 inverse。安全 probe 已经冻结精确 restore selector 后，关闭态把同一控件的
  `effect_scope` 漂成 `data_only` 不会撤销恢复资格；当前控件仍必须明确 stateful、值可见、可逆、
  无风险且无权限阻塞。Router 若到达包含该精确 inverse 的另一实时 Variant，调度器接纳真实
  落点并就地恢复，不再强迫返回旧 Variant。Region role 是实时区块描述，不进入该 selector
  的稳定等价判断；名称、控件类型、group 和 `state_key` 仍须一致。resume 若只持久化了 before
  值的 canonical element，未闭合事务仍优先路由到 mutation host，正式登记当前帧并采用 live
  inverse，不能因普通 frontier 看不到 after 值而提前报 `state_restore_failed`。
- 安全可逆的 stateful probe 若 fresh landing 的像素已变化、但结构化值仍等于 before，
  该结果不是可重试的普通 `uncertain`。运行时把 after 记为 `unknown`，把 probe 控件结为
  `stateful_effect_uncertain`，创建只允许恢复的 active mutation，并在任何其他探索之前选择冻结的
  restore selector。持久化图中的未提交 attempt 只在同时具有 fresh 观测、正 pHash 距离、
  可逆且无风险、已知 before 和明确 restore selector 时，才会在 resume 重建这种事务。
- resume 对持久 `transition_events` 的判断统一由
  `stateful.py::resume_stateful_probe_state` 完成：只恢复已提交的 stateful probe，或满足上述
  安全证据边界的未结算 probe，并以随后匹配的 restore 事件闭合它。`VisualResumeRebuilder`
  负责构造完整 collaborator snapshot；Engine 只在构造成功后一次性发布这些引用，不重复解释
  stateful 事件，也不把部分恢复状态暴露给调度器。
- 只有 consistent、committed、landing-verified 的 attempt 才加入 routing view。
- `transitioned_inconsistent` 会隔离边并尝试 Router 恢复源页面；恢复失败时
  `state_restore_failed` 并停止。
- 新建但未被权威事实引用的 provisional state 可以在严格等价条件下原子回收；既有或已提交
  节点不能删除。

## 8. Back、off-app 与恢复

- 语义 Back 优先使用当前已存元素中明确的 Back/Close，并在当前帧重新定位。
- Android/detail 等无可见返回控件页面可使用平台 Back；桌面回退使用对应键操作。
- Back 是平台虚拟动作，不参与 Region 覆盖或普通 frontier。
- `runtime/recovery.py::ensure_on_app` 在登记前阻止 launcher、其他 App、崩溃画面或空截图成为
  节点；稳定重读后仍确认外跳时先尝试一次 Back/Esc，再允许有限次数 relaunch。Engine 的
  `_ensure_on_app` 只是薄宿主接口；动作后执行直接调用它，不存在另一套 after-action 判断。
- 桌面 `_is_target_app_foreground` 读取入口在应用启动时绑定的 `DesktopWindowOwner`。
  当前 active window ID、同 PID 窗口或绑定窗口的 transient dialog 直接判为应用内；明确的
  其他窗口直接判为 `external_app`；窗口管理器无结果或尚未绑定时返回 `unknown`。Android 使用
  前台 Activity/task ownership。两端都不回退截图 VLM；稳定重读后仍未知便以
  `focus_unknown` 失败关闭，也不执行 Back/relaunch。
- `runtime/recovery.py::dismiss_interruptions` 同时服务空图启动检查和 Page Identity 明确标记的
  临时前景层。它继续使用现有 Perception、InterruptionDismisser、单目标实时重绑和最多三轮
  真实观察/点击；普通 Region-lazy 页面不额外触发该循环。正式 `semantic_inventory` 不再输出旧
  `is_interruption` 字段，因此启动检查不能依赖 `splash`、`loading` 等固定 Prompt 词。
- 桌面 `_refresh_window_crop` 只读取当前真实窗口矩形并更新 grounding crop，不按固定像素宽度
  推断窗口是否缩小，也不改变窗口大小或焦点。应用启动时的显式最大化仍由 lifecycle 负责。
- Android 前台活动检查的 `different_app` 与 VLM focus 的 `external_app` 都结案为 source-local
  `external_app`；它们不建立目标应用内 verified edge，也不会在恢复后重新开放同一 occurrence。
  focus guard 用真实 Back 恢复时，该 Back 只证明外跳已恢复，恢复页面不是控件的应用内落点；
  具有持久化 terminal 证据的动作不会再被 Router 当作直接边或共享目标重放。
- 连续 off-app、总 backtrack 失败、thrash、状态恢复失败都有独立停止原因。

## 9. 滚动与长图

- `grounding/scroll.py` 负责普通视口聚合和 semantic Region 像素采集，
  `grounding/region/scroll.py` 负责旧几何模式的 Region 级稳定与去重，`grounding/stitch.py`
  提供复用的 Region 拼接函数；Region 长图联合定位在 `visual_perception.py`，有界滚动与坐标验收在
  `runtime/execution.py`。
- 新稳定 Region 首次观察后建立一个 `region:<region_id>` 行为审计；审计证明 static，或证明
  到达 bottom 并回到 canonical top。同一稳定 Region 的完整记录可被多个 Variant 复用。
  普通回溯不因旧 State 缺少 ledger 而逐节点重滚；只有明确 `scrollable=true` 或已经开始审计
  的 scope 缺少完成证据时才阻塞。
- block 级 `scrollable=true` 是发送区块内滚动的直接证据；顶层 `surface_scrollable` 只描述整个
  active surface，不能压过一个明确可独立滚动的内部 Region。顶层不是 true 且 block 全 false 时
  直接记录 static；顶层 true 与 block 全 false 的冲突必须经 movement-only 复核确认父视口，并新增
  一个不拥有元素的 `scroll_viewport` 父 Region，否则记录感知不足。短且不可滚动的 dialog/menu
  不对背景页面发送滚动。
- 可滚动 block 的 bbox 首先表示语义功能区，而不是无条件等同于物理滚动容器。首滑后若该 bbox
  不能形成可信纵向连续性，框架用同一对前后帧检查与它纵向相邻的上方 Region；只有更大的候选框
  恢复可信共同位移时才采用该物理视口。这个边界来自图像运动关系，不来自工具栏、列表或某类应用
  的命名规则，也不增加滚动期间 VLM 调用。
- 同一语义 bbox 也可能把固定标题或操作 footer 包在内部移动内容周围。首滑前后若检测到固定上下
  边带，框架仅在去除边带后的内容具有强纵向位移时采用该内部物理视口；长图只拼移动内容，不重复
  固定按钮。检测和验收都来自同一对像素帧，不使用 dialog、表单或控件名称规则。
- 首次 semantic inventory 已同时给出 Region 的 `bbox_1000` 与可滚动性；登记后该位置以
  `viewport_bbox_1000` 保存在稳定 `semantic_blocks` 中，只供同一 State 的滚动复核使用，不参与
  Region 身份或目标点击。滚动循环把动作锚定在
  每个可滚动 Region 内逐一执行，只做截图、Region 裁剪、区块内像素移动/纵向连续性判断、到底检测和恢复
  该区顶部；回顶以该 Region 首屏裁图为证据，允许反向手势移动距离小于采集手势，并检查最后一次有界
  反向手势后的画面；不调用逐帧 semantic inventory、页面裁判或 Region correspondence，也不把每次
  滚动手势记成语义 ActionEdge attempt 或保存成动作前后证据。固定 Region 使用
  首屏 crop；可滚动 Region 正常只把自身 crop 序列交给既有 `stitch_region_crops()`。若已由运动
  证据确认更大的物理视口，则先拼该视口，再按首屏语义 bbox 裁掉上方相邻 Region，最终 Region
  长图仍只包含目标功能区。真实 Android 还会先按已知状态栏/导航栏边界收紧 crop，避免系统手势条
  进入拼接缝。若某区 crop 缺失、宽度不兼容、
  未到底、未恢复顶部或没有形成高于单视口的 composite，则连该区首屏 crop 也不作为长图保存，且
  不回退历史滚动次数；已完成的其他 Region 不受影响。
- 采集与回顶手势长度是目标物理视口高度的固定比例，不是整屏高度的固定比例；这为任意大小的
  独立滚动区保留可拼接重叠。正常结束由连续稳定帧证明物理顶部/底部；统一的高步数上限只防止
  异常页面无限滚动，不估算内容长度，也不因独立 Region 较小而减少可覆盖范围。
- 当前稳定 Region 的首次滚动审计若尚未完成，runner 会在开放该 Region 的控件候选前先以 `WAIT`
  获取新截图，然后直接复用该 State 已登记的 `rN + viewport_bbox_1000`；它只补审当前 incomplete
  Region，不要求同一 State 中尚未观察的其他 Region 已有位置，也不重新运行整页 semantic
  inventory、registration，也不把本轮漂移后的 `bN` 猜回稳定 Region。每个可滚动 Region 先用
  无 VLM 的反向滚动确认物理顶部，再从该顶部补审。补审成功后重启本轮选择；补审仍不完整时记录
  `scroll_audit_deferred` 并保留未完成 ledger，但允许当前截图上的可见目标继续进入 Agent 任务；不会
  把历史长图中的不可见目标判为定位失败，也不会把审计伪装成完成。可见 frontier 最终耗尽后若该
  ledger 仍未闭合，停止原因和 completion 仍为 `scroll_incomplete`。映射到
  同一稳定 Region 的其他 State 直接复用该记录，不单独路由补审。补审生成的完整 Region composite 会覆盖该 State
  原来持久化的首屏 crop，并把完整 inventory 写回该 State 的元素账本、Region registry、原生图节点
  与 capability 候选；只有 `scroll_ledger.complete=true` 的 Region 才允许加载这张图参与联合定位。
- 补审只把已完成 Region 的新 block、元素和长图按稳定 `region_id` 合并回整页账本；没有参与
  本次补审的 Region、元素与 `observation_status` 保持不变。整页元素重新编号后同步刷新所有
  Region 的成员引用，避免局部写回制造不一致。
- 完成长图先切成有重叠、按顺序连续的可读视图，每次最多 4 张交给现有
  `semantic_region_inventory`；短图仍只调用一次，超长图分批后由框架按 `target` 合并去重。
  每批复用 Region-local Prompt 并只返回 `function_entries[{entry_id,target}]`；没有独立
  `region_long_inventory` Prompt/role，也不生成用途、效果、状态、安全分类或 group。任一批请求
  失败或结构无效时，整张长图以 `perception_unavailable` 失败关闭，不保存局部元素或完成 ledger。以后定位
  该 Region 的 target 时，当前整屏与这张长图构成联合定位输入；每次滚动后都以新整屏和同一长图重判，
  不再每滚一步都重复询问目标是否可见。每个有界滚动段是否移动优先比较
  `viewport_bbox_1000` 对应 Region 裁图的像素变化，避免大面积固定界面让整屏 pHash 把真实列表移动
  误报为 `scroll_stalled`。
- 滚动期间若语义 Region 自身出现明显变化却不能与前一裁图形成可信的纵向连续性，先尝试上述
  共同运动的物理视口；该候选仍不能对齐时，先执行一次无 VLM 的等待并重取稳定帧。稳定帧若回到
  前一裁图则作为底部停滞证据，若恢复可信位移则继续拼接；只有仍无法对齐时才丢弃该帧，以
  `surface_changed` 结束审计，并禁止在未确认的页面反向滚动。Region 外固定界面的视觉变化不进入
  最终 Region 长图，也不单独触发换页判定。
- 回顶既可由首屏 Region crop 的精确 pHash 命中证明，也可由物理上界证明：连续反向手势不再产生
  可信的纵向内容位移。首次采集后的回顶至少执行与采集步数相称的有界检查；已知 State 的补审允许
  从当前任意位置一直探测到上界。两者都依赖纵向运动而非整块像素静止，因此动态文字、数值或状态
  小片段持续变化不会单独阻止回顶。
- block 是正式滚动判据：任一明确 `scrollable=true` 的已定位 Region 只滚动自身；若已声明 block
  全部明确为 `scrollable=false` 且顶层不是 true，State 直接以 static 完成且不发送探测滚动。顶层
  true 的冲突复核不确定、block 缺少滚动结论或可滚动 block 缺少定位/裁图时都登记为感知不足。

## 10. 调试隔离

- 正式入口只走 Qwen semantic inventory；旧 YOLO/OCR/SoM 和 Qwen 一次性名称+坐标 inventory
  参数已移除。semantic inventory 空回复会失败关闭，不存在隐式旧管线回退。

- Local HTML 可以在后台运行相同状态机，无需 VM/AVD。
- fixture oracle inventory/grounding 可以分别跳过元素识别和目标定位，专门验证调度、Router、
  登记、图和 completion。
- exact VLM response cache 可以复用完全相同的模型请求；force-refresh 会绕过缓存。
- `--block_first_inventory` CLI 仍是隔离的 saved-frame 三阶段诊断入口；其 Page map、可选
  active-region filter、Region
  localization 和 Region-local inventory 原语同时已被正式 Region-lazy runtime 复用。整图 Page map 只输出 Region 名称和
  描述；显式选择 Region 后，完整截图调用只输出该 Region 的 bbox/可滚动性；随后 Region crop
  调用输出元素名称、简短证据、category/risk、enabled 和可选 state，不输出元素坐标。输出分别为
  `page_map.json`、`region_localization.json`、`selected_region_crop.png` 和
  `region_inventory.json`。无论 Region 的长宽比如何，inventory 只接收一个完整 Region crop；
  `context_crop` 额外提供一张完整页面作上下文，但不会把 Region 自动切成左中右或重叠细节图。
  非法枚举或 category/risk 后果不一致时，仅对 rejected 行追加一次无图片、不得增删改名的合同
  修复；合法行不复核。仍非法的行保留在 rejected 清单并返回 partial。该路径不写 canonical
  ledger；正式 runtime 则由 `runtime/region_observation.py` 将相同合同逐 Region 写入 canonical ledger。
- `--inventory_repair_from` 是隔离的 saved-frame 实验：它读取第一次 `elements.json`，用同一
  整图只补审遗漏、或仅被瞬时状态/动作文字表示的控件，结果写 `inventory_repair.json`。它不
  自动并入 canonical ledger，也不改变正式遍历；先用 oracle 对新增真控件和新增误报分别计数。
- 当前正式首轮 prompt 已要求无文字图标也必须登记，但保存截图复测仍观察到纯图标入口偶发漏检；
  默认路径没有为了召回率固定增加一次全页漏项调用，该边界必须与分类/分组正确性分开报告。
- Local HTML oracle inventory 会保留带 `aria-current=page` 的当前主导航项作为观察事实；
  `selected` 本身不再让 Region 登记或 frontier 自动结案，该 occurrence 与同一稳定 Region 的
  跨界面 verified 结果一起交给 Explorer 判断。fixture 中已知可逆的状态
  控件可作为 navigation 类候选用于遍历逻辑实验；不可逆或高风险控件仍保持浅探测/延期。
- map-guided 身份命中不会授权复用实时内容：stateful/restore 或已知同页像素变化会强制普通
  感知，并把 live inventory 单独交给落地验证。Local HTML 全量回归覆盖 search、mute、favorite
  和 notifications 四个状态轴的变化与恢复。
- resume 以元素的明确探索终态为 frontier 结案真值；只有 verified `action_edges` 不再自动把整个
  控件恢复为完成。旧图的 optimistic `visited` 若没有 `complete|covered|semantic_only|terminal`
  会重新开放；recurring appearance UID 只保留为诊断签名，不跨 State 传播覆盖。
- frontier 把 `category=display` 直接结案为 `semantic_only`；`category=dangerous` 或任何非 `none`
  风险都记录 terminal `blocked`，不送 Explorer，但继续处理同一界面其他候选。category/risk 依据
  当前点击的直接后果和完整 active surface 判断，不按名称匹配：进入普通可观察、可控制的中间界面
  可继续；当前点击会提交高风险后果，或开始高风险流程并进入 OS 保护/其他不可观察界面时，在执行前
  停止。认证相关入口使用 `authentication`；缺失或非法语义按 `dangerous/unknown` 失败关闭。
- 动作后的 observation 无截图时不登记空节点，也不立即把来源控件归为应用崩溃。运行时先执行一次
  平台返回并重新观察；若恢复到目标应用，就把该来源 occurrence 记为
  `unobservable_surface` 并继续其他 frontier；未恢复才使用既有有界 relaunch 和失败关闭。
- Android focus guard uses foreground task ownership, not a package allowlist.
  A delegated Activity remains in scope only when the resumed task is rooted in
  the target app's package/affinity; an Activity in another foreground task is
  off-app. Exact-package screens avoid the extra task dump. Desktop uses bound
  window/PID/transient ownership. Neither platform falls back to screenshot VLM.
- 正式 Page map/Region-local inventory 与旧整页回退都不要求 VLM 判应用归属，也不把固定导航、
  侧栏、标签或位置写成过滤规则。
  它只按当前最前景交互事实列出可直接触发控件；旧格式的 `scope/interaction` 仅用于缓存/fixture
  兼容。密集数据实例只有在截图足以证明同一交互模板、差别仅为数据或选择时才压缩为一个代表；
  共享位置或视觉相似不足以压缩不同用途/效果的控件。
- 既有 Settings 截图的 `qwen3.7-plus` 复放证明最终 `Disable app` 能正确拦截，但首层 `Disable` 被判为
  `dangerous/unknown` 而不是 `navigation/none`；当前实现安全地过度拦截，尚不能把该实例计为两阶段
  风险闭环。
- 2026-07-28 的真实桌面 Clock 运行只保留 `repeat days` 和 `preset duration` 两个重复数据组，
  没有把顶栏标签、菜单项或不同功能合组；但 completion 仍因 Help 窗口中的三个链接缺少权威
  outcome 而失败。运行同时确认窗口管理控件可污染 Router、菜单 State 会重复登记进入它的
  `Menu` occurrence，以及同名顶栏项可能在菜单上下文中重绑定到错误来源。它们属于执行、焦点、
  occurrence 和 Router 合同问题，不能用增加应用名、控件名或固定位置规则修补 inventory prompt。
- 这些路径不验证 Android system chrome、ADB/touch physics、真实设备或未缓存的真实模型。

## 11. 当前验证重点

遍历逻辑的最小聚焦验证应覆盖：

- frontier 过滤、去重和 safe stateful gate；
- Router verified-edge 规划、逐跳身份、偏航重规划、Back 与 hard reset；
- 普通点击候选和 Router 身份候选的区别；
- source mismatch、false arrival、inconsistent landing 与 cursor resync；
- scroll audit、frontier stop reason 和 completion certificate 的分离；
- resume 后 Router、Region、visited、frontier 和 action counter 的一致性。
- 用已知页面截图和 Region 文本表做离线抖动回放：改变 raw role、目标措辞、回复顺序、临时 ID、
  category/type，映射后的 Region、canonical capability 引用和 frontier 候选仍应一致。

本轮最新行为和验证结果记录在 `design/changelog/2026-07.md`。

## 13. 2026-07-21 source-local 结果与 fixture 长页面回放

- verified、Explorer 结案和 abnormal/terminal 都按来源 State occurrence 保存。共享 Region
  只共享稳定结构和可执行关系；另一来源上的 `target_rebind_failed`、外跳或崩溃不参与当前
  occurrence 的 frontier 过滤。resume 会清除旧版本由跨来源污染写入的
  `terminal_observed_outcome` 占位标记。
- fixture-oracle 的 full-surface inventory 在完成真实滚动采集后读取完整页面 DOM 与文档坐标，
  不得在恢复顶部后把当前视口误当完整页面。正式 semantic 路径不读取 fixture 的历史滚动深度。
- fixture inventory 为页面身份保留当前 selected 导航项时，fixture grounding 必须接受同一
  selected DOM occurrence，即使 oracle 的动作清单省略了“跳到当前页”的 no-op 入口；否则同一
  调试后端会制造假的 `target_rebind_failed`。未登记且未 selected 的 filler 仍排除。
- Router native-action 重放若边本身没有 element id，会在来源 State 的稳定 Region 内恢复唯一
  canonical 元素；可滚动目标同样必须通过 Region 长图联合定位。语义有歧义、长图不可用或目标
  未确认时 fail closed，不用 raw inventory 字符串或历史滚动次数猜测。
- Explorer 不再接收或输出 `finished_buttons/DONE`。每个分类和 CLICK 都必须带理由；局部无效的
  `covered/semantic_only` 不会覆盖独立合法的 CLICK，也不会被持久化；同一回复中独立合法的分类
  同样不会因另一个按钮纠正失败而丢失。没有合法 CLICK 时才用同一截图和精简错误上下文局部纠正
  一次；再次不合法只暂缓当前 State/Region，先继续其余 frontier。所有可用工作耗尽后再重试该区，
  bounded retry 仍失败才以 `explorer_unavailable` 停止并保留未完成证书。

## 12. Reverse Edge Explorer（2026-07-30）

- `PageIdentityJudge.choose_return()` 接收动作前后完整截图、A/B 自然语言描述、刚执行入口和平台，
  返回一个规范化 action、可选可见 target，或 `action=None`。
- 可见 CLICK 使用临时 semantic `VisualElement` 进入现有 latest-frame Grounder，不要求 B 已经完成
  Region-local element observation。平台动作仅限 Android `navigate_back` 与桌面 `PRESS Esc`。
- 触发条件是 forward attempt 已 landing-verified 且缺少 context-compatible verified 直接
  `B→A`。探查在本地普通 frontier 前执行；间接 route 不跳过直接边。
- forward attempt 保存是否跳过、null 或 probe attempt 引用；具体动作自身从 pre-dispatch 开始
  拥有独立 ActionEdge attempt。实际落点和所有失败都写回该 attempt，不维护第二份顶层账本。
- 每个语义动作 attempt 在 `action_attempts/` 下保存 `before.png` 与 `after.png`，并把相对路径写入
  `evidence.screenshots`。若 Grounder 为找当前目标先滚动，`before.png` 是滚动完成后、真实点击前的
  最新完整截图。Reverse probe 使用触发它的 forward attempt 的这张操作前截图作为 A 的实时身份锚点；
  原始图片字节不写入 `graph.json`。
- 普通 Router 重放已验证动作时，同样在实际投递前建立该次 ActionEdge attempt。成功落到预期
  State、落回来源 State 的 `no_effect` 和无法确认落点的 `identity_unknown` 都更新同一条 attempt；
  已经保存的 `before/after` 不因该次路由未产生新边而丢失。

## 14. Stateful transaction and evidence-scoped exploration (2026-07-23)

- `navigation/frontier.py` applies the engine's stateful scope after deterministic
  terminal/safety filtering. A function-set probe snapshots the host's semantic
  controls; while it is active, only newly exposed host controls remain eligible.
  Other states are closed until the inverse action restores the original value.
- The retained inverse control bypasses Explorer and prior-click completion. The
  framework emits the ordinary CLICK shape, then current-frame live targeting and
  Landing verification still decide whether restoration succeeded.
- An active transaction may be restored on any registered live Variant that owns
  the unique frozen inverse selector and still satisfies current value,
  reversibility, permission, and risk evidence. The selector preserves the
  control name, type, and normalized group; observation-local Region wording
  and a fresh VLM paraphrase of `state_key` are not stable identity. Ambiguous
  selector matches fail closed. The scheduler never
  borrows the stored inverse object into a different State and never exposes
  unrelated controls on an alternate Variant. For a same-control toggle, a
  historical baseline-valued occurrence is not an inverse and is not clicked.
- A completed return control reopened solely for pending restoration is an
  execution copy. Prior verified-CLICK coverage does not immediately complete
  that copy again; current-frame targeting and landing verification still run,
  while the canonical control remains complete. A reusable surface may have
  been verified under another entry context, so the saved destination may be
  the current mutation source or one of its live navigation-stack ancestors;
  destinations outside that live stack are not eligible restoration evidence.
- If a reusable post-action surface is reachable from more than one source, an
  active transaction routes to its frozen source State before routing to that
  surface. Before the scheduler can re-enter the post-action surface, it
  consumes any fresh source inventory and closes an already-restored baseline;
  otherwise ordinary source candidates stay withheld until restoration closes.
  A route failure on either transaction endpoint fails closed and cannot retire
  unrelated controls on that State.
- Explorer owns the functional-result comparison behind `covered`; the framework
  validates the referenced verified evidence, source choices, self-reference,
  duplicate classifications, and non-empty reasons without imposing name or
  repeated-content-group equivalence. `semantic_only` is judged from the
  screenshot plus factual purpose/effect evidence, not rejected by an internal
  category rule. A valid action can still be used when another classification
  in the same response is invalid.
- The formal inventory no longer asks for `group`; repeated-instance compression
  is a screenshot-grounded inventory judgment, while coverage still requires
  Explorer and actual verified result evidence.
- Active overlays inherit the source Page identity while keeping a distinct State
  and Variant. This preserves host affinity without collapsing dialog or popup
  controls into the background state.
- Completion accepts a committed, landing-verified local change for a `data_only`
  stateful control. A `function_set` control still requires explicit mutation
  evidence and a closed restore transaction.
## Transition Observer

The default navigation-effect check is a compact, read-only
`ObserverAgent.observe_transition` call after landing registration. It receives
the real before/after full screenshots and the selected visible `target` only.
It first returns the final visible `target`, then `observed_outcome` plus
`relation_to_target=related|unrelated|no_relevant_change|uncertain`.
When the current name is accurate or the screenshots are insufficient, it must
echo the input target. It may correct the name only when visible text, the
control itself, or the resulting visible content clearly proves a more accurate
control name. A visibly labelled or symbolic control is not renamed merely to
its destination page.
`related/unrelated/no_relevant_change/uncertain` map to the existing internal
`transitioned_consistent/transitioned_inconsistent/no_effect/uncertain`
attempt evidence. The raw result is retained under
`action_edges[].attempts[].evidence.transition_observer`.
Before the ActionEdge is committed, a proven correction updates the source
element, its semantic block, the State/Region name ledgers, the replay hint, the
portable selector and this attempt's semantic edge. The original name is added
as `transition_observer.original_target`. Earlier attempts under the old name
remain unchanged, and a committed attempt cannot be relabelled.
Identical pHash frames still take the deterministic `no_effect` path without a
VLM call; stateful actions remain governed by structured state and restoration
evidence.

One transition observation may make at most three read-only judgments over the
same before/after frames. The first judgment may use the response cache; later
judgments bypass it so a malformed or stale cached reply is not replayed. No GUI
action is repeated during these judgments. If all three remain `uncertain`, the
attempt stays uncommitted and the source control remains pending, but the runtime
adopts the freshly registered actual landing and continues its local frontier.
That source occurrence is withheld for the rest of the current run rather than
being marked failed, covered, or terminal. If no other work remains, traversal
stops with `observer_unresolved`, never `frontier_empty`. This recovery adds no
model-visible prompt or schema field.

## Same-Page Region evidence for Explorer

Page observation, Region partition, and adjacent Region mapping remain upstream
facts and are not changed by exploration coverage. Explorer normally receives
verified results from the current State and from the same stable Region. It may
also receive a verified result from another State when both States already have
the same non-empty `page_id` and both Regions have the same normalized
human-readable role.

This is an evidence boundary, not automatic equivalence. Explorer must still
compare the actual verified result with the current screenshot and return an
explicit `covered` decision; the framework's review path must accept that
decision. Different Pages or differently named Regions do not share this
evidence. The rule contains no application, control-name, navigation-class, or
position special case.

## Unsafe bound-entry disposition

An independent click-review rejection is normally retryable because it may reflect a bad point or the wrong visible control. The one non-retryable case is a bound entry for which the reviewer confirms that the visible target is the requested entry (`target_matches_request=true`) and that clicking it is unsafe. The entry remains `unresolved` with the reviewer reason as evidence, but `task_eligible=false` prevents the scheduler from dispatching it again. This does not certify the function and does not use target-name string rules.

Click-review input includes the bound entry's Page, Region, target, control type, and current value so the VLM can compare the proposed visible control against the actual ledger task. A same-looking or same-named control elsewhere must not be treated as the bound entry.

Autonomous action, identity, dispute and finish tools remain available in both task types. `reuse_entry_result` appears only for an exact `explore_entry` task because its IDs bind that dispatched entry to one verified peer; it is not a general survey action. Tool visibility is not proof that the current ledger state permits the call: invalid page ownership, Region state or argument structure returns a specific rejection for the Agent to correct. Route advice is embedded in the active task rather than exposed as a read-only tool.

Autonomous Page identity is a stable natural-language functional location.
Material operable conditions inside it are separately registered Variants, each
backed by a private State and representative screenshot. Exact screenshot
digests remain internal evidence for freshness and byte-identical retry checks;
they never create, shortlist or merge Page, Variant or Region identity.

自主区块记忆分为两层：每个页面保存本地可见实例及其覆盖情况，`AutonomousRegionRegistry` 保存跨页共享区块。页面调查时，模型可以引用框架提供的 `region_ref` 并说明合并理由；框架不会根据文字、位置、边界框或截图相似度自动合并。共享关系提交后，入口审核器会收到该精确区块的精简 `shared_region_entries`；每组只包含当前正式区块的名称、描述和其中已有的入口。页面实例、内部区块编号和证据来源继续由框架保存，不重复发送。审核器可用 `equivalent_to_entry_id` 将当前可见候选绑定到本轮前已有的规范入口：尚待探索的代表与当前实例共用一条任务，已验证代表还可以提供推断结果。精确 `explore_entry` 阶段的后备工具 `reuse_entry_result` 仍只接受已验证代表。

精确入口的真实动作等待结算时，主 Agent 会收到同一页面、同一 owner Region、同一控件类型下仍待探索入口的精简
`entry_id/target` 列表。只有动作前后截图确实变化、结果符合入口意图、页面未改变且变化范围为 `owner_state` 时，
动作结算中的 `business_effect` 才能附带同组入口编号和具体理由。框架校验引用项仍是该正式区块中的待办入口，
实际执行项保持 `verified`，未执行项标记为同质推断覆盖并持久化其来源和理由。该推断不会设置
`representative_entry_id`，不会生成 `agent_inferred_equivalence` 图边，也不会伪装成多个真实动作。

每次通过的入口审核都会根据区块内归一化的控件类型和目标签名发布覆盖版本。只有动作前后批量区块映射明确给出一对一延续关系，而且新页面实例报告完全相同的签名时，才继承该版本。签名改变后仍执行普通的本地入口审核并发布新版本；名称相同或普通语义绑定本身不继承覆盖。入口身份共享与已验证结果复用始终是两个独立的显式裁决。

Partially accepted Page updates keep their rejected items as pending corrections while preserving accepted facts. Every entry inherits its owner from the enclosing Region; an entry cannot repeat or override `region_name`. A rejected nested entry can be corrected under the same Region while unrelated accepted facts remain preserved. `completion_ready` still accepts late visible Regions and entries and includes the current Page's compact Region/entry ledger for final visual review. A byte-identical no-change scroll may support the Agent's boundary judgment; the same-frame incomplete-to-complete flip remains rejected without that real scroll evidence. After one Reviewer-confirmed exact Entry action, an explicit `temporarily_unavailable|not_interactive` assessment or a semantic `no_visible_change` with a byte-identical frame records one unresolved terminal no-effect result. A changed frame still requires normal settlement and remains retryable; no success edge is produced from the no-effect result.

Post-action identity settlement also has a narrow staged consistency boundary.
During Page identity, a pending action cannot be reported as `no_visible_change`
while the screenshot is assigned to another Page; during Variant identity the
same check applies to the action-source material Variant. The runtime returns a
concrete conflict before changing ownership. A corrected `changed` landing may
select an existing canonical Page without an already observed edge, but that
selection only stages the owner: no State or action landing is committed until
the following Variant step succeeds. For first registration, `new` names the
independent function content instead of a shell label shared across Pages;
`known` always reuses the registered canonical name so an imperfect old name is
not silently duplicated. The framework does not infer identity from title or
control strings; the Agent may call the current-stage specialist when uncertain,
and a new material Variant under a known Page requires that comparison.
If a Page-stage `known` name is not a Page but uniquely equals one registered
Variant name, runtime normalizes it to that Variant's owning Page and leaves
Variant classification to the next stage. A name shared by Variants under more
than one Page stays ambiguous and is rejected rather than guessed.

Target-application ownership is part of the VLM Region contract. The main Agent omits environment surfaces outside the target application from `page_update`. This is a general model judgment, not an application/control-name blacklist.

The autonomous loop also enforces the harder application boundary with system foreground metadata before a screenshot can reach the Agent or any page/Region registration path. Android reads foreground activity/task ownership; desktop reuses the `DesktopWindowOwner` bound during launch. Two unavailable verdicts still stop as `focus_unknown`. When a real pending entry action gets two non-target verdicts, its external destination is stored as a semantic-only terminal outcome without creating an external Page; the entry is settled, the existing data-preserving relaunch callback reopens and rebinds the target app, and traversal continues from a fresh in-app screenshot. If there is no pending action, or the relaunch cannot produce a screenshot, the run still stops. In-app Android surfaces in the target task and desktop dialogs owned by the bound target process/window remain eligible.

`finish_exploration` treats a Region as complete only when the main Agent explicitly reports `coverage_complete=true`. All Regions complete closes survey automatically; adding an incomplete Region reopens it.

Temporary-state chains retain the first observed `before` value across intermediate controls and aliases. A later model report of `restored` closes that chain only when its reported current value normalizes to the original `before`; returning from one intermediate value to another keeps `needs_restore` and produces factual feedback for the Agent.

On resume, the natural map intentionally starts with no page bound to the fresh screenshot and does not reuse current-frame Region geometry. The Agent reports the current page, refreshes geometry through `page_update`, and may scroll directly without a Region specialist or scan binding.
Entry result memory keeps its terminal classification across the checkpoint
round trip, so the natural explanation for a retired no-effect Entry does not
change after restart.


## Autonomous ownership and completion closure (2026-08-09)

The formal autonomous ledger now has one ownership chain:
`Page -> committed Region occurrence/region_ref -> reviewed Entry`. An Entry is
not completion-eligible merely because its status string is `verified`,
`inferred`, or retired. Completion additionally checks that its owner Region
exists in the current Region state, carries the Registry ref for that exact
Page/Region occurrence, and that any explicit representative resolves to the
same ref. This keeps evidence reuse inside the functional Region identity that
gave the Entry its meaning.

Optional equivalence fields from the model treat JSON `null` as absence. A
non-null value remains subject to string-shape and same-Region validation; this
does not weaken the ownership rule.

Existing reviewed Region identity is stable under ordinary updates. Coverage,
current-frame geometry and cumulative survey memory may change, while non-empty
`summary` and `equivalence_reason` remain unchanged unless a focused Region
Review approves the proposal. When a verified same-Page action reveals a new
surface, the pending resurvey forces one Region Review for that real-action
evidence generation even if the proposal reuses old names. Once accepted,
existing-Region coverage and survey-memory updates reuse the partition verdict
and preserve its accepted occurrence geometry until a new Region, new shared
binding or later real changed action appears. The resurvey remains pending until
a consistent Entry Review accepts the focused coverage audit. It does not wait
for sibling Regions hidden by the current modal; those remain ordinary
State-routed Region work;
`reason_consistent=false` records an `inconsistent` audit and commits neither
selected/missed candidates nor coverage.

Unbound pointer actions are still reviewed and executed, and their before/after
frames and ActionEdge evidence remain in the graph. With empty `entry_id`, they
do not create a formal `direct_action_backfill` Entry. Explicit IDs continue to
settle only the exact registered Entry. Old resumed backfill records are kept
for audit but are returned as completion gaps, so legacy pollution cannot
silently pass the current ledger gate.
The obsolete `begin_direct_action` writer and its always-false pending-action
`backfilled` field have been removed. New pending snapshots contain only the
action ID, exact Entry ID and frame ID. Resume still reads historical snapshot
payloads and identifies a legacy backfill from the persisted Entry
`discovery_source`, so compatibility does not leave a second current writer.
The unused bbox-driven `executable_target`/`begin_registered_action` execution
path has also been removed; current execution always binds an exact Entry ID
and uses the latest Agent action plus Click Review. Entry bbox remains
observation evidence and is intentionally cleared on resume.
The uncalled `agent_reference_view` projection has also been removed. Current
candidate and history views are task-local projections built by the loop from
the formal Entry ledger and Region ownership, not a second ledger-wide view.
The obsolete `AutonomousEntryLedger.inspect_region()` formal writer has also
been removed. Formal Entry creation and observation refresh now have one path:
the persistent main Agent submits reviewed Page Entry fields through
`record_agent_update()`. That writer accepts only the visible target, optional
current-frame bbox, explicit equivalence to a pre-existing verified
representative, and equivalent visible occurrences. Model-supplied Entry IDs,
statuses, control values and equivalence reasons cannot mutate the ledger;
action status, result and destination remain framework-owned facts.


`finish_exploration.unreachable_evidence` is now task-scoped. Runtime accepts
only one exact active `explore_entry` ID, its owning Page, non-empty
subject/evidence, and at least two already recorded executed GUI attempts in the
same task. Unknown, covered, retired, unrelated, duplicate or text-only records
are rejected before the natural map or Entry ledger changes. Accepted evidence
keeps the Entry `unresolved` but removes it from scheduling. Page/Region-level
text and an empty Entry ID cannot close formal work.

WAIT is allowed once to obtain a fresh observation. A second WAIT on the same
byte-identical frame and task returns `repeat_wait_same_frame`, enters the
shared rejection boundary, and cannot loop indefinitely. Ordinary autonomous
runs persist `autonomous_completion.json` v3 after the final checkpoint. It
separates `traversal_status` from `bundle_status`, derives Page/Region/Entry
counts from the ledgers, and attempts bundle compilation for partial runs too.
`ledger_closed` requires a framework/model finish, an empty structural gap list
and a compiled bundle; otherwise status is `incomplete` and the CLI exits 3. This report intentionally
does not claim the guided traversal certificate. Target-edge diagnostic mode
keeps its separate pass/fail exit contract.

`ledger_closed` is intentionally only a structural report. Local real-Qwen
fixture evidence previously showed that Entry Reviewer could return empty
decision arrays while its natural-language reason said the main Agent's
candidate was valid. The bounded reconciliation rule now prevents that one
reply from closing the ledger: the main Agent sees the complete verdict, may
revise the proposal twice, and the third unresolved review fails closed for the
same persisted evidence generation. Focused offline tests cover resume, dynamic
pixels and changing sibling audit scope. No fresh real-Qwen fixture or Clock
traversal has validated this source, so the earlier failed validator artifact
is not retroactively accepted.

## Autonomous material-Variant writer (2026-08-10)

`autonomous_natural_map.v2` stores Page-scoped Variant names, framework-assigned
internal Variant IDs, visible predicates and one representative screenshot per
Variant. `_register_scene` writes a distinct schema-v3 State for every accepted
material Variant and records the Variant name/predicates in
`variant_signature/observed_facts`; ActionAttempt settlement therefore keeps the
real source and landing Variant IDs without a parallel transition ledger.

The main Agent does not write `graph.json`. It submits only the constrained
Page/Variant observation, Region/Entry deltas and normalized action/settlement
fields already consumed by the runtime. The framework validates those fields,
assigns IDs, writes screenshots/Attempts/Edges and serializes StateGraph.
An unreviewed new Variant on a known Page fails closed with
`variant_identity_requires_review`. Existing Variant reuse adds no specialist
call. Resume rebuilds every Variant candidate and representative image from the
saved natural map plus graph States. A pending Entry Review stores the exact
source State and semantic Variant. Resume reuses that binding; an older
checkpoint without it is recovered only when the Page has exactly one State.
An ambiguous multi-State legacy review is discarded for fresh observation
instead of silently binding its Entry evidence to the first Variant.

This closes autonomous multi-Variant State production and the minimum exact
Region/Entry occurrence projection. A Region group occurrence uses `state_ids`
for stable identity continuity and accumulates `visible_state_ids` only when
the independent Entry Reviewer audited that Region as visible in the State. A
repeated stable Entry likewise accumulates `source_state_ids`; its first scalar source
is retained only for the source-local inferred-edge compatibility path.
Re-observing the same identity in another Variant does not create a new stable ID.

For a Qwen-selected point-targeted action, including `input_text`, an exact approved Click Review plus one
formal source Region lets the writer assign the executed control a stable
ActionAttempt identity. Explicit Entry actions reuse
`autonomous-entry:<entry_id>`; ordinary reviewed controls use
`autonomous-element:<digest>` derived from the formal Region ref and normalized
reviewed target. The ActionAttempt top-level `element_id/element_label/region`
is the only stable action-Element record. Click point, bbox and frame remain
attempt evidence, and no Element Agent, extra Qwen call or inventory sidecar is
introduced.

When the current material Variant has no accepted Region occurrence, survey
returns `material_variant_has_no_region_occurrence` and requires
`record_regions` before coverage can continue. The compiler validates Page
ownership and projects each Region/Entry only to its declared States. Legacy
sidecars without State membership remain readable only for a single-State Page;
a multi-State ambiguity fails closed instead of copying an occurrence.

This is still a narrow projection: it covers Entry semantics and controls that
were actually reviewed and acted on. A reviewed `input_text` Attempt now gives
that input a stable action-backed Element identity; unacted input/result/created-object/cleanup
occurrences, effect-object identity, cross-task multi-step
recipe composition, cleanup induction, fully Variant-scoped coverage scheduling
and fresh-Qwen live validation remain open.

### Guided compatibility cleanup boundary

`navigation.frontier` now exports only `FrontierContext` and
`unvisited_candidates`. The legacy category/data-control classifiers and the
matching `VisualTraversalEngine` wrappers had no runtime consumer; candidate
semantics remain with the Agent while the frontier enforces durable coverage,
availability and safety evidence.

The retired legacy Region segmenter returns no Regions, so its post-review
`_retag_healed_regions` chain was a no-op and has been removed. Stable Qwen
Region identity continues through the autonomous Region ledger and projection.

The definition-only `relocate_near` helper has also been removed. Historical
element positions and templates may help bring a target into view, but the
final click coordinate still comes only from reviewed current-frame grounding;
Region visual confirmation continues through `match_region_view` and
`relocate_unique`.

## Autonomous task pool and verified-route scheduling (2026-08-17)

`exploration_task` is a durable assignment, not a one-turn recommendation.
For an exact Entry, verified-route navigation, scroll, locating and interruption
recovery remain part of that task even while intermediate landings change Page.
A pending GUI action is always settled first. The framework reselects from the
global pool only after the exact Entry settles, defers to a prerequisite, or is
explicitly suspended/terminal. A Region internal-operation task is bound to its exact
`Region@Page@state`; it remains open after each settled operation and closes
only when its latest eligible main-Agent round returns `action=null`, with no
pending action and no restoration.

Whenever selection is required, survey, Entry and Region tasks are compared in
one pool by shortest edge count in `StateGraph.routing_graph`. This view contains
only committed landing-verified transitions. Equal distances use the persisted
task creation order and never a task-kind preference. A different Page or
Variant with no verified path has infinite distance: runtime does not hand it
to the Agent as speculative navigation, and reports the missing verified route
as a partial-completion gap. Final autonomous completion is emitted by the
framework, not a model finish call; suspended work and unverified-route work
remain concrete gaps.

A Reviewer-approved exact Entry action that is actually executed and leaves
the frame byte-identical is settled once as an unresolved
`observed_no_visible_change` result. It is not immediately redispatched merely
because the main Agent did not further classify the cause as temporarily
unavailable or non-interactive. A changed frame still requires settlement of
that visible change. Five rejected no-progress turns still suspend one bound
task, but that suspension clears the cross-task rejection streak so the nearest
remaining task can run; the ten-turn run guard applies only when rejections have
no bound task identity.

An incomplete Region survey is routed to one of that Region's independently
reviewed `visible_state_ids`, not merely to an identity-continuity `state_id` or
any State with the same Page name. If the current Variant hides the Region, the
scheduler follows the shortest landing-verified State path before asking for
another survey; without such a path it reports the gap instead of repeatedly
accepting the same current-frame page update. Every incomplete Region on the
Page is evaluated separately, so a hidden Region without a route does not mask
a visible sibling. Legacy snapshots without the new
field recover visibility only from exact coverage-version source States.

### Deferred Entry prerequisites

The main Agent may defer the current `explore_entry` when the latest screenshot
shows one concrete visible prerequisite control, either before an unsafe or
impossible target attempt or after an exact attempt settles as
`no_visible_change`. `defer_current_task` carries only
that prerequisite target and a visual reason. Runtime binds it to exactly one
open formal Entry, rejects empty, ambiguous, self-referential and cyclic links,
and preserves the defer record in the current task history. Deferred tasks do
not participate in nearest-task selection. Once the prerequisite has an
actually settled result, the original Entry returns to the pool and is judged
again on the then-current Page@state. Inferred equivalence does not prove a
current-State prerequisite effect. If the prerequisite is skipped, unsafe or
blocked, completion reports the dependent's named prerequisite gap. A real
exact action that is interactive but visibly has no effect is instead recorded
as `explored_no_visible_effect`; evidence that does not show a concrete
prerequisite cannot create a dependency.

## Autonomous Prompt transport and role split (2026-08-17)

The Qwen main Agent no longer receives one repeated monolithic Prompt. Its
system message is the stable Chinese role/safety prefix plus the active tool
meanings and strict output schema. Its user message contains the current
task/stage, latest screenshot order, the smallest stage-specific ledger view,
corrections and every chronological record belonging to the current task.
History records retain the actual operation parameters, visible outcome,
Action Reviewer result and concrete rejection reason. A pending GUI action
points to that history number and is not duplicated as a second action record.

Page identity and Page-state-version identity use separate stateless
specialists. Region partition and Entry review stay separate because they may
be called independently. The Action Reviewer has one stateless system Prompt
with exactly one mode per call: review a proposed action, or choose a minimal
interruption recovery. Before/after Region comparison is one batch specialist
call over both reviewed Region catalogs; its complete assignment supports
one-to-one, one-to-many, many-to-one and many-to-many groups. The current
Region ledger commits only one-to-one continuity and keeps grouped results as
audit evidence.

The main `page_update` wire form is
`regions[{name,summary,coverage_complete,entries[{operation,subject,target}]}]`;
`target` is the current clickable representative, while `operation` and
`subject` name the user action and semantic object. Page ownership
comes from the current reviewed screenshot. It carries no manual shared-Region
reference fields; cross-page continuity is settled later by the batch
before/after Region mapper. A GUI action separately carries
`purpose` (`navigation`, `locating`, `entry_attempt`,
`interruption_recovery`, `region_survey` or `operation_attempt`).
Region-internal controls are discovered during the owner Region survey and,
after Entry Review, each receives the same durable `explore_entry` task used by
navigation entries. The model-visible `finish_exploration` and
`complete_region_probe` tools are removed; the framework derives Region and run
completion from the ledger, settlement and restoration state.

In ordinary phases with no pending GUI action, Page/Variant ownership is
already a framework fact and `screen` is absent from the main-Agent response
schema. Identity stages still return their own minimal Page-only or
Variant-only shape, and pending-action settlement still reports the real
landing identity. A same-Page Entry is not assumed to exist on every material
Variant: scheduling uses its recorded source State IDs and verified graph
routes, and surveys an unrecorded current Variant before allowing the exact
Entry attempt.
