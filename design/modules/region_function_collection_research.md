# Region-function collection research prototype

## 2026-09-14 旧 VLC 图采集小试（失败如实保留）

用户允许先选旧图已核对功能做小试，取代此前暂停新增生成/采集的阶段限制；不代表全应用遍历完成。
复用现有生成器与RegionGuidedCollector，从coverage_graph旧图的相关6个区块生成“媒体提示Never、自动置前Never并保存”一条指令，实际执行仍使用完整原图。
12HTTP（1生成、11采集/终验）、7GUI。Luna把展开列表误报为第一个设置完成，框架推进目标；自动置前设置成功，Save已点击。
终验正确发现媒体提示仍为When minimized，success=false；1个no_effect动作未committed，SFT整条拒绝、0样本。
原图哈希未变，没有人工救援；阶段完成判断与失败后的恢复仍待解决。详情及逐步截图见[本轮报告](../../artifacts/traversal_goal_20260909/instruction_collection_pilot_20260914_01/REPORT.md)。
正式CLI引用验证、37帧可读性/统计/原图哈希检查与实际导出通过；不是GUI任务成功、持久值重开核验或全框架门禁。
本轮未改框架；运行使用工作区已有未提交采集代码及已保存的环境适配/transport包装，不能当成某个干净提交的整体认证。


已有条件任务正例：`android_collection_20260909_alarm_context_fixed_evidence`包含两次真实执行，
true分支6GUI/12HTTP、false分支3GUI/9HTTP，原帧分别确认振动由开到关、由关到开，且均确认Sep10/2026、7:15和启用。
这是同一任务的两种实际初态接线，不是匹配初态的正式性能比较；原两轮失败均保留。
导出点击历史现保留原action_spec.target，不再只剩CLICK/click类型；不使用事后verification.reason。
条件任务导出9条，连同此前双端各4条共17条不同动作样本，汇总在`artifacts/traversal_goal_20260909/sft_pilot_17/`。
以上为旧试点证据；当前阶段按本页2026-09-14更新执行，训练仍未启动。

后续输入保留已有completed列表的简短Region/goal摘要，避免最近三步动作窗口挤掉已完成分支后再次执行相对指令。
目标完成时，终验同时保留最近成功动作的提交前截图与完成截图；这使确认后被隐藏的年份/参数仍有原始证据，
提交前值不能单独证明已生效，仍结合动作后结果与最终画面核验。未新增模型调用或响应字段。

采集每轮仅执行current_goal；instruction提供整体目的，不允许提前或重复执行其他阶段。
准备目标若要求定位/展开/可见即可按该要求完成，业务目标仍需实际结果；条件观察不通过切换控件来“判断”。
此区分修正了旧“不是只到达区块”提示对条件前准备的误导；原条件任务曾在准备时及日期后续时重复切振动，终验正确拒绝。
两组原帧API复测已不再越权，完整双分支实机验证另记；没有新增角色、Schema或调用。

2026-09-09：Android冻结图生成的秒表任务已实际完成9HTTP/4GUI，四步回执均success，
最终原图保留暂停状态、#1=14.50、#2=12.27、累计26.78秒；仅一次Lap点击，第二行包含后续计时段。
证据`artifacts/android_collection_20260909_segment_evidence/`，不是对原遍历a60缺帧结果的补写。
新实例本轮截图正常，关闭前emulator进程仍存活；原ADB失联原因仍未确证。
SFT导出同时识别Android平铺primitive与桌面parameters格式，动作JSON均原样保留，系统动作说明与其协议一致。
Android实导出4条click并逐项核对原执行记录；双端各4条，共8条样本，尚未训练或评测。

生成器明确“不把导航列为业务目标”不授权生成“禁止导航”或擅自要求已在目标页面；
instruction表达自然业务目标，必要导航和输入实现由实时执行处理。Android原候选误加上述限制，
修正通用提示后的同图候选已消除，原候选保留拒绝理由；无新增Schema或角色。

## 2026-09-09 完整回执实机正例与 SFT 接线

冻结桌面 Clock 图后自动生成启动/记圈/暂停任务，服务器采集实际完成8HTTP、4GUI，
四步（含导航）均有success回执。最终原图显示暂停19.2秒且保留Lap1=9.4秒，来源账本哈希未变。
证据：`artifacts/desktop_collection_20260909_segment_receipts_evidence/`；这是开发监督单任务正例，
不是完整应用遍历、条件任务或正式比较。此前导航none的成功业务轨迹保持原样、不计合格数据。

`tools/export_sft_dataset.py` 现读取 `m13.visual_collection.v1` 的frames和实际primitive；
只接纳终验成功、无errors、每步committed且回执success的episode，每步须有一个primitive和前后帧引用。
含多primitive的步骤缺少中间截图时整条episode暂不导出，不合成截图或拆成虚假样本；旧格式过滤保持。
必要导航保留；图片取before，坐标/参数来自实际执行记录。既有Thought字段仅放原action_spec的purpose/target
意图文本，不称其为完整推理，不使用事后的verification.reason。原始轨迹不改写。
真实导出4条CLICK样本并核对图片可读与primitive完全一致，输出在
`artifacts/traversal_goal_20260909/desktop_sft_verified/`。未执行训练、checkpoint重载或benchmark。

## 2026-09-09 目标完成与来源可见性

采集回执现有两种固定Schema：无待回填GUI时只允许none；有上一步时只允许success/no_effect/uncertain，
导航和恢复同样必须回填。兼容接口仍返回none等非法值时保留原记录并停止，不再继续动作或把它作为合格闭环。
这不把uncertain变成成功；终验与逐步回执仍分别报告。Schema变化的缓存收益/损失只看实际usage，不作保证。

功能完成后，来源Region可能消失或变为结果Region。普通目标根据当前截图的complete判断推进，
不再额外要求来源Region仍可见；仍检查目标App、记录上一步真实结果并执行最终截图核验。
region_visible继续供导航和条件观察使用，条件不清楚仍不是false。本修改不修复跨互斥Region的条件设计。

## 2026-09-08 首条有监督实机采集

`artifacts/runs/region_data_20260908/` 使用现有 Region 采集代码与 Luna API，
初期由 Terra 审核实际输入输出和 GUI 截图、主对话逐次放行；用户随后改为正常遍历、
Terra 旁路检查、遇到问题再暂停和修复。源 Settings 账本保持不变。
生成任务要求选择第三张内置壁纸；采集输入实际包含 `e18/a52` 的共享导航到 Background
关系，新截图下执行导航和选择，共 2 个动作，最终截图核验通过。

这不是合格自主训练轨迹：Luna 对导航动作回报 `previous_action_outcome=none`，
写入器如实保留 `committed=false`；独立监督记录未覆盖原始回填。业务目标成功与逐步记录
合格分开。`tools/export_sft_dataset.py` 实际读取该 episode 后得到 0 条样本，旧导出器仍
不识别当前步骤的 `frames/action_spec/grounding` 结构。未进行 SFT 训练或 benchmark。

本次复用实验脚本暂停机制，并使传输层重试也单独等待批准；没有新增框架模型角色。
框架源码和 CLI 的既有未提交改动均保留，本节不表示这些改动已整体验收。
后续阶段仅做新图遍历，没有插入新的指令采集；按用户最新约定，之后按遍历批次、批量指令、
实机采集三个阶段串行切换。完整本批统计与未结算 a7 见 `final_summary.json`。

## 2026-09-06 可执行入口（离线验证，未实机验收）

本文件原有的 State 图片到达、调用方 branch_taken 辅助类保留为旧原型。
当前新增消费路径位于同一模块：region_function_inventory 从 ledger 导出零动作发现；
design_region_instruction 复用现有模型 transport 生成 Region 目标和可在运行时选择的分支；
RegionGuidedCollector 复用 GUI action 与 CollectionWriter 完成实时循环，不要求未知中间 State 被原图识别。
没有新增独立图真值、插件或执行脚本。

```powershell
python gui_rewalk/run_capability_task_synthesis.py --region-ledger <ledger.json> --request "设计3至5个子操作、带if/else与共同后续的任务" --model-backend openai_api --output <instruction.json>
python gui_rewalk/run_visual_collection.py --region-ledger <ledger.json> --instruction <instruction.json> --validate-only
python gui_rewalk/run_visual_collection.py --region-ledger <ledger.json> --instruction <instruction.json> --initial-app <app> --model-backend openai_api --path-to-vm <vmx> --headless --max-turns 40 --output-root <collection-output>
```

示例命令是入口说明，本轮没有执行 VM 或模型调用。生成器传入已登记功能、参数说明和 Region memory；
允许新的用户目标值，不以历史参数组合为硬门槛，但 Prompt 要求以已观察功能为依据。
这依赖模型语义判断，不能宣称任意生成目标都有可执行证明。
条件不明确时不把它当 false；普通目标以实际完成证据推进，来源区块消失不自动构成失败。
Graph relations 提供候选历史路线，当前截图与任务对象优先；不把 Region BFS 候选标为当前上下文已验证路线。

以下章节描述旧离线辅助 API，不代表上述新模式仍要求预先指定分支或每步已知 State。


## Scope

This is an offline-first research path beside the existing capability and M13
modules. It does not alter traversal, graph persistence, or live collection.
The implementation files are:

- `gui_rewalk/src/core/scenario/region_function_research.py`
- `gui_rewalk/src/core/scenario/function_collection_research.py`
- `gui_rewalk/src/core/scenario/live_state_locator.py`
- `gui_rewalk/src/core/scenario/agent_trajectory_audit.py`

The older helper API has no standalone CLI. Its callers inject VLM-like objects exposing
`predict_mm(prompt, images)` and supply a directed NetworkX routing graph.

## Region function extraction

`read_region_artifacts()` reads existing node directories. It aggregates
`semantic_blocks.json` and `elements.json` by stable `region_id` and records the
node ids where each Region occurs. It prefers `region_<region_id>.png`, retains
`region_<role>.png` as a legacy read fallback, and never substitutes the whole
node `screenshot.png`. An observation without either Region image is omitted
from the VLM input; a Region with no usable image in any node is skipped with a
warning. Missing semantic blocks still fall back to the `region_id` already
stored on elements.

`RegionFunctionExtractor` sends Region role/note, member names/types/
interactivity, locations, and images to the injected VLM. Elements are prompt
context only. Code supplies the authoritative Region and node locations and
normalizes each result to exactly:

```json
{
  "name": "Adjust system volume",
  "description": "Changes the overall system output volume.",
  "region_id": "r-volume",
  "parameters": [
    {"name": "level", "type": "ordinal", "values": ["minimum", "middle", "maximum"]}
  ],
  "locations": ["sound-page"]
}
```

Controls, element ids, fixed user wording, execution hints, and verification
status are not saved. `save_function_inventory()` writes the resulting list as
UTF-8 JSON.

## Instruction and shortest-path planning

`FunctionInstructionDesigner` makes two separate VLM calls:

1. select one to five inventory functions and legal parameter values;
2. after planning, write one natural instruction in the chosen execution order.

References use only `region_id + name`. Conditional selection accepts a caller
supplied `branch_taken` boolean and plans only that branch, while final wording
still describes the complete if/else task. Simple `before` / `after` constraints
can restrict otherwise reorderable functions and remain active when the
coordinator replans the unfinished functions.

`ShortestFunctionPlanner` derives the default start from the one graph node with
an empty `action_path_from_root`, unless the caller supplies an explicit start.
For one to five functions it enumerates function permutations and candidate
locations, computes unweighted directed shortest paths, and never infers a
reverse route. A function `location` is a State-local binding where that
operation is already executable and groundable, so its v1 reveal cost is zero.
An optional positive integer `execution_steps` defaults to one and counts GUI
primitives through the target result; cleanup and recovery are outside v1.

Each leg reports `access_distance`. Each execution row reports
`access_distance`, `execution_steps`, and their sum `completion_cost`; the plan
also reports `total_completion_cost` while retaining `total_hops`. Planning
minimizes total completion cost after directed route feasibility is established.
For a fixed selected set, execution-step cost is constant across permutations,
so existing deterministic function/location/path tie ordering is preserved.

## Collection coordination

`PageArrivalJudge` asks only whether the live screenshot has reached the target
node screenshot. While it returns false, `navigation_guidance` exposes the
planned node route. On arrival the coordinator enters execution and removes all
navigation guidance.

The collector can then act freely. `GoalCompletionJudge` receives only the
target function, parameters, and current screenshot; false keeps execution
active. After true, the caller supplies or re-identifies the current graph node,
and remaining functions are replanned from it. A missing/unknown node, missing
target screenshot, or unavailable directed route fails the small state machine.
The coordinator never executes GUI actions.

`KnownPageStateLocator` is an optional, read-only helper for a future arbitrary
live start. It first restricts candidates to an already confirmed `page_ref`.
A unique byte-identical candidate returns without a model call; otherwise one
`predict_mm(prompt, images)` judgment receives the live frame, State cards, and
candidate screenshots. Only an exact known candidate ref is returned. Missing
evidence, duplicate exact frames, malformed/unknown/new replies and transport
errors return unresolved. The helper never creates, merges, or updates a State.
`FunctionCollectionCoordinator.locate_start_state()` only delegates to this
helper; it does not replace the existing root plan or replan automatically.

## Agent-caused trajectory failure audit

`audit_agent_trajectory()` consumes facts written by the collector rather than
guessing from an action label. It compares actual action ids with the current
expected set, desired and observed outcomes, graph distance, transaction commit
and step verification. Scroll actions are considered agent failures only after
repeated no-progress evidence or after the configured consecutive-scroll budget;
legitimate progressing scrolls on long pages are not rejected.

The audit reports `unexpected_action`, `wrong_outcome`, `route_regression`,
`uncommitted_action`, `verification_failed`, `no_effect_action`,
`repeated_scroll_no_progress`, and `excessive_consecutive_scroll`. Any error-level
issue sets `agent_failure=true`; warning-only evidence lowers the quality score
without declaring the rollout failed. Accurate live use therefore requires the
collector to persist expected action ids and before/after outcome, scroll, graph,
commit, and verification facts.

## Verification and current gap

Focused tests use temporary node artifacts, generated test images, fake VLMs,
and in-memory NetworkX graphs. No VM, device, GUI action, external VLM, or
network call is exercised. A later experiment must connect these helpers to a
collector callback loop and validate real screenshots before claiming live
collection behavior. In particular, arbitrary-State live collection and
fallback/recovery to the reproducible root are not integrated or live-validated.

Verification (offline only): `python -B -m pytest -q
tests/test_region_function_research.py tests/test_function_collection_research.py`
-> `11 passed`; targeted `python -m py_compile` and `git diff --check` both
exited 0. A read-only smoke call to `read_region_artifacts()` on the existing
Android Clock run loaded 6 Regions; it made no VLM or GUI call.

The 2026-08-24 directed-distance, cost, and read-only locator follow-up ran
`tests/test_explore_kernel.py tests/test_function_collection_research.py
tests/test_live_state_locator.py` offline: `104 passed in 1.28s`. Targeted
`py_compile` and `git diff --check` exited 0. No arbitrary-State live
collection, VM, emulator, device, or external VLM was exercised.

Region-image persistence follow-up (offline only): semantic registration now
persists its already-localized transient crops as
`node_artifacts/<state_id>/region_<region_id>.png` for new states, without an
additional VLM call or persisted bbox. `tests/test_region_image_persistence.py`
covers stable-id naming, same-role non-collision, one-call crop mapping, invalid
bbox omission, reader precedence, legacy fallback, no full-page fallback, and
whole-Region skip/warning.

## User-confirmed trajectory attribute extension

Status: design proposal confirmed on 2026-08-01, not implemented. This section
does not change the current offline-only prototype or the live M13 contract.

### Design boundary

Progressive reveal belongs to trajectory generation and online collection, not
to functional traversal enumerating dynamic content instances. Traversal may
discover stable functions and structures such as Search, Results Region, Open
Result, and a scrollable viewport. Posts, products, venues, prices, and other
runtime content must not become persistent Page, State, Region, or capability
identities.

`conditional` and `progressive_reveal` are not mutually exclusive trajectory
types:

- `conditional` describes control flow;
- `progressive_reveal` describes the observation depth required to obtain task
  evidence;
- one trajectory may also be multi-page or cross-app while carrying both.

The current `single / cross_page / conditional` instruction type mixes
composition scope with control flow. Do not add `progressive_reveal` as another
value in that flat enum. The proposed orthogonal attributes are:

| Attribute | Meaning | Initial values |
|---|---|---|
| `composition` | Capability-composition scope | `single / multi_page / cross_app` |
| `control_flow` | Execution control flow | `linear / conditional` |
| `evidence_access` | Observation depth | `single_view / progressive_reveal` |
| `stop_contract` | Evidence authorizing termination | `outcome_verified / coverage_target / end_verified / budget_bound` |

```json
{
  "trajectory_attributes": {
    "composition": "multi_page",
    "control_flow": "conditional",
    "evidence_access": "progressive_reveal",
    "stop_contract": "coverage_target"
  }
}
```

The legacy `type` may remain as a compatibility/display field during a later
migration. Formal dataset statistics and experiments should use the orthogonal
attributes. No schema migration is implemented by this proposal.

### Conditional trajectory evidence

The existing designer accepts caller-supplied `branch_taken`, plans only the
selected branch, and writes the complete if/else instruction. That is an
offline branch-planning contract, not evidence that an Agent observed a live
condition and chose a branch.

A valid live conditional trajectory must persist:

- the complete if/else instruction and both branches' capability refs;
- a condition that is observable and independently verifiable;
- the live observation used to evaluate it;
- `observed_condition` and its screenshot evidence;
- runtime-produced `branch_taken`;
- actions and verification for only the selected branch;
- an audit conclusion that the rejected branch was not executed.

Fixture setup may determine the hidden true condition for evaluation, but it
must not inject the answer into the Agent. In a live collector, `branch_taken`
is an output of condition observation rather than an input to planning.

### Progressive-reveal trajectory evidence

The instruction expresses an information requirement without exposing the GUI
mechanism. For example:

> Find at least 12 distinct wedding venues and provide a name, location or
> price, and post evidence for each.

The first research version may support only an explicit count and required
fields:

```json
{
  "coverage_requirement": {
    "min_unique_items": 12,
    "required_fields": ["name", "location_or_price", "evidence"],
    "region_selector": "search results",
    "max_scrolls": 20,
    "max_seconds": 120
  }
}
```

Do not reinterpret an open-ended instruction such as "recommend some options"
as an exhaustive task. A valid progressive-reveal trajectory records:

- the initial visible item batch;
- every `SCROLL` and `WAIT` action;
- newly revealed unique items after each step;
- each item's first-seen step, visible fields, and screenshot evidence;
- episode-local deduplication;
- loading, terminal, timeout, and surface-change evidence;
- the final stop reason and coverage result.

Fixture item IDs are hidden evaluator truth and must not enter Agent
observation or deduplication. Real-platform item identity is episode-local;
dynamic content is never promoted into the capability graph.

The initial stop outcomes are:

| Outcome | Meaning | Success interpretation |
|---|---|---|
| `target_met` | Required count, fields, and relevance are satisfied | success |
| `end_verified` | An explicit end is visible and loading has settled | exhaustive success only when requested |
| `budget_stop` | Time or action budget is exhausted | bounded, incomplete coverage |
| `plateau_uncertain` | No recent additions but no real end evidence | incomplete |
| `load_timeout` | Dynamic loading did not settle | incomplete |
| `surface_changed` | The target Region cannot be continued | incomplete |

`viewport_stable` is only pixel stability and cannot prove dynamic content
exhaustion. An infinite feed cannot be called complete because it reached a
scroll cap or a temporary plateau.

### Conditional plus progressive reveal

A combined task may first aggregate enough evidence and then branch, for
example: search for wedding venues; if at least five distinct candidates are
within budget, summarize the top three, otherwise expand the search area.

Such a trajectory is valid only when:

1. the condition is not decided from the default viewport alone;
2. the coverage target was met, or bounded stopping is reported honestly;
3. `branch_taken` agrees with the aggregated `observed_condition`;
4. the rejected branch has no executed action;
5. final claims cite items actually present in the evidence ledger.

### Dataset matrix and evaluation

Use a 2x2 matrix rather than a single flat type:

| | `single_view` | `progressive_reveal` |
|---|---|---|
| `linear` | Linear-Static | Linear-Progressive |
| `conditional` | Conditional-Static | Conditional-Progressive |

The corresponding training ablation is Base, Base + Conditional, Base +
Progressive, and Base + both. Conditional metrics include condition accuracy,
branch accuracy, and wrong-branch execution. Progressive metrics include scroll
initiation, reveal/relevant recall, duplicates, premature/valid stops, and
Recall-Action AUC. The combined metric is correct branching after sufficient
evidence acquisition. Report GUI actions, wall time, model calls, and successful
trajectory length for all conditions.

Evaluation instructions do not mention scroll mechanics. An explicit "inspect
100 items" prompt is a strong prompt baseline, and fixed scripted scrolling is
an action upper bound rather than the proposed method.

### Codex-only controlled pilot, 2026-08-01

A one-run-per-condition local pilot used 100 deterministic cards, 20-card lazy
batches, a 1.2-second load delay, stable four-column append, and 14 qualifying
items. The twelfth qualifying item was rank 82. Fresh Codex contexts saw only
successive screenshots and chose `scroll`, `wait`, or `finish`; a mechanical
environment actuator applied the same 600-pixel scroll and 1.35-second wait to
all conditions. This is a visual-policy pilot, not a native Xiaohongshu run.

| Condition | Scrolls | Rendered | Visible | Correct returned | Stop |
|---|---:|---:|---:|---:|---|
| Open-ended "find some" | 2 | 40/100 | 20/100 | 3/14 | self-declared sufficient |
| Find at least 12, no scroll wording | 12 | 100/100 | 84/100 | 12/14 | `target_met` |
| Same target plus explicit scroll/wait | 12 | 100/100 | 84/100 | 12/14 | `target_met` |

All returned items were correct and unique. Therefore this pilot does not
support the strong claim that Codex cannot initiate scrolling: even the
open-ended condition scrolled. It supports the narrower hypothesis that an
open-ended information request permits self-defined early stopping. It also
suggests that the measurable coverage target, rather than mentioning the scroll
mechanism, was the active intervention in this run: the two count-target
conditions had identical actions and outputs.

Do not generalize this single controlled run to most GUI agents or to live
Xiaohongshu, Dianping, or Douyin. Repeated seeds, dynamic-layout variants, a
native Browser/Computer-Use loop, live-platform checks, and downstream training
ablations remain required. The local protocol, event log, oracle, screenshots,
and evaluator are under
`artifacts/experiments/progressive_reveal_codex_20260801/`.

### Claim and implementation boundary

Schema plus deterministic fixtures support only a design/benchmark claim. A
live collector and matched evaluation are required before claiming automatic
generation and verification. Only downstream training ablations on unseen
dynamic pages without scroll instructions can support the claim that the data
teaches autonomous progressive exploration.

The minimal implementation order is:

1. add a deterministic progressive-feed fixture and hidden evaluator without
   changing traversal;
2. add trajectory attributes plus conditional and coverage evidence schemas;
3. make live condition observation produce `branch_taken`;
4. extend the existing collection executor with an episode-local progressive
   controller and item ledger rather than adding a parallel executor;
5. persist the evidence in the existing writer and fail closed in verification;
6. run the 2x2 fixture pilot before live-platform or training claims.

This proposal does not require changes to capability-graph identity,
Region-local function-entry inventory, or the application-level completion
certificate.

## 2026-09-22 独立采集的视觉坐标核对

RegionGuidedCollector 接受采集侧 visual_guard；collection_visual_guard.py 只读冻结图的控件外观与 bbox/click_bbox，复用固定版本 matcher 将点击框映射到当前截图。Luna 的 0..1000 坐标沿原执行器换算；明确错位不投递、不自动改点，反馈后 fresh 重定位。匹配不确定、未登记目标或 target 与已选 ref 名称不一致时，用同一受预算约束的模型传输做当前帧确认。视觉一致只证明定位，不证明任务结果。

启用该路径时，动作意图、下一帧观察和是否达意图分别记录；success 与明确未达意图/缺观察矛盾时降级 uncertain，原报告保留，committed=false。Writer 保存 action_intent。额外定位调用计入 model_calls；实际 HTTP 重试/GUI 额度仍由环境传输层计数。被拦截提议保存在独立 grounding 证据中，不伪造成执行步骤。

接线验证入口为 artifacts/runs/collection_visual_online_20260922_02/pilot.py，显式传入 guard，沿用已有 collector/writer/exporter。通用 run_visual_collection.py 仍消费旧 ledger，本次没有宣称新 stepwise 图已直接兼容该 CLI，也未修改遍历代码、提示词或图。当前单条小试需冻结图和固定视觉实现；未增加 CLI 开关。

两轮分别 10HTTP/4GUI，每轮拦截1个错点，随后完成两项延迟设置并保持自动锁屏开启，分别导出4条 SFT（共8条）；_02为审阅后版本。独立只读值核验及截图一致。16项聚焦pytest和writer脚本通过。此为同应用两轮小试，不是跨应用鲁棒性、真实定时锁屏或训练效果验证。模型同时误认语义和结果仍可能漏检；生成自然目标与执行goal覆盖不足仍待单独处理。报告见 to_astra/collection_visual_online_20260922/REPORT.md；独立盲读与意图对照保留原版。
