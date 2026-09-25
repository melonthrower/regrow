# 模块化探索内核索引

2026-09-17 当前模块补充：[Region工作范围与派生视图](explore_kernel/region_work.md)负责自动探索的直属一层轮次、声明范围与统一覆盖；已有Task、绑定、身份、路由、结算仍为执行主链。

最后更新：2026-09-05

状态：2026-08-29 已在 owner-centered 合同上增加 Operation 参数确认：Luna 只选当前
Element/Region owner、回填 completed owner action、Region memory 与本轮参数信息；框架绑定本地
Operation 并派生 Task/completion。每条新 Operation 同时填 `unknown|none|observed` 与参数说明；
截图已显示参数形式、当前值或代表值即为 observed，只有连这些都不可见的安全 `unknown + explore`
复用原 Operation 动作取证，`record + unknown` 只形成 gap。
Semantic Exploration Focus 只投影全局图，不新增持久图或任务类型。参数合同已有离线聚焦验证；
新的移动 Clock supervised live 重跑已产生 v5 参数证据，但因 emulator disappearance 后 resume
进入 Screensaver external-surface 无动作循环而被 Codex 停止，状态仍是 partial；不能用该 run 或
`d69a7d99` 的旧 v4 证据替代无监督 acceptance。

## 目标

新内核位于 `gui_rewalk/src/core/explore/`，通过 `--modular-explore` 显式启用。旧的
guided、`--autonomous-agent` 和页面会话实验均保留，便于对照和回退；新内核不导入旧遍历循环。
模型后端默认是 `--explore-backend qwen_api`；`--explore-backend codex_cli --explore-model gpt-5.6-luna`
通过仓库已有的 Codex CLI 结构化调用器驱动相同的模块化角色。Codex CLI 必须安装并已认证在
实际运行主机；完整 Prompt 通过 stdin 传给 CLI，不占用 Windows 命令行参数长度。该后端不修改 Prompt、
Region/Operation 数据模型、任务调度或 GUI 动作验证。

`--explore-backend openai_api` 复用同一模块化 Agent、Prompt、严格 Schema、
解析和运行时，只把 specialist 调用换成 OpenAI-compatible `POST <base_url>/responses`。用户文本与每张
完整截图分别编码为 `input_text` 和 PNG/JPEG data URL `input_image`，Schema 放在
`text.format={type: json_schema, strict: true}`，reasoning effort 来自本地 YAML，且 `store=false`。
运行调试记录保存配置模型、服务端响应的 effective model、input/output/cached/reasoning token 计数，
不保存 Authorization header 或 key。当前离线假 HTTP 边界验证只证明请求、解析和 usage
接线；在用户填入本地 key 前，不把它描述为智增增真实接口、图片或严格 Schema 的运行验收。
连接在模型回复返回前异常时，transport 立即重试一次；第二次仍失败就报告环境失败。该重试发生在
GUI action 生成/投递之前，不会重复已执行动作，也不扩展为持续重试策略。

本次重构只保留一个核心原则：

> 主 Agent 判断当前截图中的界面语义、owner 动作和功能信息；框架绑定 Operation、结算内部 Task、
> 保存证据并维护唯一的可验证图。

框架不按应用名、按钮名、控件类型、位置或相似度猜测功能。每个模型字段都必须直接服务于页面清点、
区块复用、操作调度、动作结算或错误修正。

## 模块地图

| 要解决的问题 | 代码 | 当前文档 |
|---|---|---|
| 当前是否仍在目标应用、属于哪个页面状态 | `scope.py`、`location.py` | [位置与页面状态](explore_kernel/location.md) |
| 当前页面是否完整登记了区块和操作 | `inventory.py` | [页面清点](explore_kernel/page_inventory.md) |
| 不同页面中的区块是否为同一稳定组件 | `region_review.py` 组织审核、`agent.py` 调用模型、`regions.py` 合并身份 | [区块身份](explore_kernel/region_identity.md) |
| 新证据表明旧区块过粗，如何摘出已有控件并保留任务/证据 | `region_refinement.py`、`runtime.py` | [显式分区修正](explore_kernel/region_refinement.md) |
| 代表项如何登记、下一项做什么、延期和完成如何保存 | `tasks.py` | [操作任务](explore_kernel/operation_tasks.md) |
| 一个动作是否执行、产生什么真实连接 | `actions.py`、`runtime.py` | [动作与连接](explore_kernel/action_transition.md) |
| pending报告不合法时如何精确纠正且避免模型死锁 | `settlement.py`、`runtime.py` | [Pending报告纠正](explore_kernel/pending_report_correction_design.md) |
| Region如何出现/消失、Page如何分组、未知State如何按Region起步 | `region_routes.py`、`runtime.py` | [Region可见性关系与路由](explore_kernel/region_routing_design.md) |
| Agent 每轮看到什么、提示词是否重复 | `status.py`、`prompts.py`、`contracts.py` | [提示词与状态栏](explore_kernel/agent_context.md) |
| 来源/邻居和控件文字检索、补查、上下文预算 | `knowledge_retrieval.py`、`status.py`、`runtime.py` | [本地知识检索](explore_kernel/knowledge_retrieval.md) |
| 主循环、证据文件、完成结果和正式编译 | `runtime.py`、`artifacts.py`、`bundle.py` | [运行与产物](explore_kernel/runtime_and_artifacts.md) |

从 `runtime.run()` 看处理顺序，再按上表进入对应模块。运行期位置、pending、预算和纠正状态仍由 runtime
持有；模块只接收实际使用的 ledger、Agent、证据读取器或标量，不新增共享上下文对象、基类或第二份账本。
身份审核返回处理后的 ledger，由 runtime 接受；上下文投影返回字典，代表项登记使用现有 Operation/Task。

### 测试入口

原 `tests/test_explore_kernel.py` 的测试函数与参数化用例已按职责搬迁，没有增加或删除用例。
公共图片、账本和 fake Agent/environment 夹具统一在 `tests/explore_fixtures.py`。

| 范围 | 测试文件（均位于 `tests/`） |
|---|---|
| 模型、Prompt、解析和传输 | `test_explore_agent.py`、`test_explore_api_backend.py` |
| 图结构和清点 | `test_explore_ledger.py`、`test_explore_inventory.py` |
| 身份候选与确定性合并 | `test_explore_regions.py` |
| 截图审核调用与审核结果校验 | `test_explore_region_review.py` |
| 调度与 Region 路线 | `test_explore_tasks_routes.py` |
| 任务卡和模型上下文 | `test_explore_status.py` |
| 动作、结算与代表项 | `test_explore_actions.py`、`test_explore_desktop_input.py`、`test_operation_centered_settlement.py` |
| 主循环、报告提交、恢复与范围 | `test_explore_runtime.py`、`test_explore_report_commit.py`、`test_explore_resume.py`、`test_explore_scope.py` |
| 产物和环境 checkpoint | `test_explore_artifacts.py`、`test_run_checkpoint.py` |

旧实验日志和实施计划中的 `test_explore_kernel.py::test_name` 是历史定位；当前可按同一函数名在上述文件查找。
模块整理之后，已按用户批准完成桌面输入替换、pending 新观察及位置/回执/清单的提交边界修复；
输入目前另有空搜索框的实机正例，非空替换及加载等待仍待同形实机验证。同 State Region 候选已修复，并用 Luna 保存帧调用及离线落账验证；
尚未重新进行完整应用遍历。进展判断已覆盖恢复阶段并排除纯措辞变化，沿用原拒绝预算；
Luna 的重复恢复报告可收束为 failed gap。恢复时补齐同 State 待审身份并清除旧策略后，保存帧已能接上
共享路线并提出合法首跳。2026-09-05 实机中 GUI 经搜索到达 Network，但清单纠正失败；人工对照另证明
原两跳计划跨 Variant 复用了不适用的返回落点，详见路由与 pending 纠正文档。独立工作区实验提交没有整体并入。

跨页面清点、Region/Operation identity、Task 物化与 Scheduler 的下一版已批准设计见
[Foreground Region、任务复用与覆盖优先调度设计](explore_kernel/foreground_task_reuse_design.md)。
对应的逐步 TDD 实施方案已归档到
[Foreground Region Task Reuse Implementation Plan](../archive/explore_kernel/foreground_task_reuse_implementation_plan.md)。
这些文档描述待实现合同，不改变本页下方记录的当前运行行为或既有 live 证据。

## 模块文档规则

根索引只负责路由，详细内容按需读取。每个模块文档随实现同步维护五类事实：责任边界、Agent/框架接口、
持有状态、可观测的失败信号、最小验证与真实运行缺口。只有影响多个模块的选择才写全局索引或架构决策，
不在每个文档重复系统提示和历史过程。

## 当前闭环

```text
最新截图
  -> 系统前景归属
  -> 主 Agent 报告 Page/State
  -> runtime 校验主 Agent 的位置报告、已知引用和 State 归属
  -> 新 State 先完成整页清点
  -> 为 occurrence 建立 Region Variant、Element 和本地 Element/Region Operation
  -> 批量复用共享 Region；当前侧列可见操作，候选侧列完整 Region canonical Operation 目录，并把已确认的“来源 Operation 显露当前 Region”写回真实 Transition；合法重构片段先合成同 State Variant
  -> 从 Transition 编译 Page Region分组和带 source Variant/CanonicalOperation条件的 Region reveal/hide关系
  -> 收束 Variant 内重复 Operation，并分级共享跨 Variant CanonicalOperation 身份/结果
  -> 新 State 清点后先按来源 State BFS 闭合祖先 frontier；无祖先候选时再按已验证图距离选择 Task
  -> Task不在精确 binding来源时，按目标 Region/canonical binding规划Region路线并绑定当前local owner
  -> 主 Agent 从当前卡片选择 owner、定位并执行一个动作
  -> 框架把 owner/action 绑定本地 Operation
  -> 下一轮根据 completed owner action 自动结算 Operation/Task
  -> 保存真实连接并继续
```

动态上下文同时投影自然语言 Focus、精确任务 Page/State/Region/Element/Operation refs 和实际动作回执。
同一焦点内已经 success 的非目标 Operation 不允许重复。上述调度和回执都只派生自
Task/Attempt/Transition，不新增持久 Operation 图。
精确任务卡还投影目标 local Operation所属 Region、Variant、Occurrence和可执行 source State；当前 State
只有已经结束的同 canonical binding 时仍返回准确来源，不能用目标页已选中的导航按钮替代。
Add/Save后 binding消失时，恢复该精确 RegionVariant本身就是后续遍历路线，不转化为预先禁止执行的 Operation顺序。

页面清点和操作探索由同一个主 Agent 完成，但由两个任务阶段隔开：首次到达新状态时必须先清点，
清点完成后才能派发操作。动作落地的 Page/State 由查看最新截图的主 Agent 直接报告；
不再有纯文字 Page Resolver。区块身份判断仍是独立的视觉判断调用，只批量回答 shortlist 当前/已知区块是否相同，
不规划动作或审核动作成功。

## Agent 接口

每轮固定报告：

- 当前应用归属；
- 当前 Page/State；
- 一句当前推进思路；
- 若有待结算动作，只报告完成的 Element/Region action 与 Region function info；
- 可选一个动作。

页面清点任务的首帧 `page_report` 只列当前 active surface 的全部可见 Region；接管输入的菜单、
弹层或对话框之后的背景只作截图上下文，不建立当前 binding。普通页面中仍可直接交互的持久导航、
工具栏、侧栏和主要内容继续登记。后续滚动帧只补报新发现或变化的结构。
每个 Region 含 `memory`、`elements[].operations` 和 `region_operations`；前者概括功能、参数值域、
代表行为和 gap，后两者分别属于明确控件与区块整体。Region 可只含一个 Element。`handling` 只有：

- `explore`：待调查/验证义务，不是立即执行授权；
- `record`：只保存观察，不等于已验证或禁用，风险类仍不得探测；
- `defer`：当前条件、资格或本批权威范围不满足，注明具体理由。

模型动作不再携带 purpose 或 Operation ID。`owner_confirmation.v1`允许当前唯一候选经视觉确认后用`@current`，由原绑定器填内部owner；旧owner格式保留。非空 `owner_ref` 由框架在当前 Variant 中按 action/direction
唯一解析；所有 scroll 都绑定当前 Region，空 owner 只用于非滚动恢复、Back 或 Wait。首次不完整清单可先 action=null 取得 ref。
独立功能入口逐项登记，重复数据实例才选代表，参数选项只写参数信息。
页面清单中的 Operation 另带 `operation_ref`：已知当前绑定复制稳定 `co`，真正新功能留空；已知 State
遗漏的当前 Element 可用任务卡 `co` 建立新本地 binding，不复用其他 Variant 的旧 `el`。
动作后新 Region 尚无正式编号，因此主 Agent 不提前猜 `region_ref`。页面清点分配编号后，现有 Region Reviewer
在同一次身份调用中判断来源 Operation 是否显露当前前景 Region；框架把通过精确 Transition 校验的结果保存，
不增加一轮模型调用。

## 真实验收

- Region路由与pending纠正 supervised Clock partial：js1
  `clock_region_route_contract_retry_20260901_080059` 使用commit `73bd096e`，80个真实Attempt、
  265次Luna调用、4 Page、31 State、30 Region、54 Transition；离线编译44条Region关系。
  两个 `FUNCTION_REGION_NOT_IN_SOURCE` 都只用一轮合同纠正并正常结算，0次纠正预算耗尽；
  World城市弹窗到 Add Alarm 的路线为 `Cancel -> Alarms`。运行同时暴露30次动作拒绝、14次无进展
  回复和 Timer ambiguous焦点下同一实际播放Operation三次无效/不确定尝试，随后由Codex监督停止，
  因此只验收对应机制，不是complete或Luna-only acceptance。

- owner-centered Luna Clock（Codex supervised）：
  `runs/luna_clock_task_reconcile_d69a7d99_20260828_214908`，24 动作、48 个主 Agent turn、
  4 Page、13 State、21 Region、127 Element、54 CanonicalOperation/108 local binding、16 Transition，
  `complete/gaps=[]/bundle=compiled`；11 个 Capability，21/21 Region memory 已投影。该 run 验收主框架
  集成，不替代无监督 Luna-only acceptance。

- 桌面 Clock：`desktop_clock_modular_b0038526_20260821_0436`，89 个动作、4 个 Page、20 个 State、
  `gaps=[]`，原 run bundle 编译为 124 个元素、20 个能力。
- 移动 Clock：`android_clock_modular_f0d727e4_20260821_1356`，67 个动作、7 个 Page、21 个 State、
  `gaps=[]`。同一导航 Region 的精确 Operation 去重后，第一轮的 97 条重复 Operation 不再形成开放任务。
- 移动原 run 在遍历闭合后暴露 bundle owner Region 别名错误；`c7ee8cf0` 修正确定性投影后，使用同一只读账本在
  独立目录编译成功：98 个元素、21 个能力。原始 completion 和采集证据没有改写。

## 当前已知边界

- 新账本可用 `--resume <exploration_ledger.json>` 续跑；加载旧账本后一律清空旧位置，不读取或比较旧 State 截图，
  也不调用 Page/State Reviewer。主 Agent 清点最新截图的可见 Region，
  现有 Region Reviewer 全局复核后，用该新 State 的 Region/local binding 规划到目标 Region 的路线。Page 只作语义组织。
- 完成是结构闭合：桌面有 7 个、移动有 1 个 Operation 以 `failed` 终态释放，不能把它们描述为功能验证成功。
- 页面身份由查看最新完整截图的主 Agent 报告；runtime 只校验结构、已知引用和 State 归属。
  Page 分歧不再触发额外模型调用或阻塞待结算动作；Region 身份仍独立复核。
- 本版 owner-centered settlement 与 Region memory 已有 saved/offline 和 Codex-supervised live acceptance；
  尚无固定 Prompt 的无监督 Luna-only 完整 Clock acceptance，两类证据不能合并报告。

## Variant 持久化边界

- 运行时继续使用 Region、RegionVariant、Element、Operation 和 CanonicalOperation 的便捷双向索引。
- `exploration_ledger.json` 的 v5 磁盘真值只保存不可反推的记录及其父引用；Operation 另保存参数
  确认状态、说明和证据 refs，`RegionVariant` 只含
  `variant_id/region_id`。Region、Variant、Element 和 CanonicalOperation 的反向成员列表不重复落盘。
- `ExplorationLedger.load()` 从 Occurrence、Element、Operation 和 CanonicalOperation 的父引用重建反向索引；
  v3 账本可加载并忽略陈旧反向列表。该兼容只覆盖直接前序 v3，不为历史 v1/v2 增加迁移层。
- 公开 Gmail、Spotify、Slack 与 Google Maps 截图只验证结构表达和 parser；其中 Spotify 独立面板与 Maps
  前景 Sheet 的合成 v4 roundtrip 通过，不是 live App、动作或遍历验收。
