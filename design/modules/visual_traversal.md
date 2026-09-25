# 视觉遍历模块当前状态

最后更新：2026-08-19

本文只保存 `gui_rewalk/src/core/visual_traversal/` 当前生效的模块合同。逐次实验、
已替代方案和历史真实运行记录不再追加到本文；需要追溯时再读：

- `design/changelog/2026-08.md`；
- `design/changelog/visual_traversal_history_through_2026-08-19.md`；
- `design/changelog/visual_traversal_history_through_2026-07-19.md`。

跨模块真值以 `design/CURRENT_FRAMEWORK.md` 为入口；精确文件职责在
`design/modules/visual_traversal_file_map.md`。

## 1. 职责与边界

视觉遍历把实时截图转换为可复查的 Page@Variant 图，并在安全条件下执行 GUI 动作、
确认真实落点、保存路线和完成缺口。

当前 CLI 并存三条控制链：

1. 默认语义遍历：框架按 Page、Region 和入口账本驱动 Explorer 与 Router。
2. `--autonomous-agent`：Qwen 主 Agent 按框架派发的唯一当前任务决定局部路线和动作。
3. `--modular-explore`：入口仍复用本文件的环境启动代码，但运行逻辑完全位于独立的
   `core/explore/`，其当前合同以 `design/modules/explore_kernel_design.md` 为准。

两条链共用环境、截图、Page@Variant 图、动作证据与部分定位能力，但不得把一条链的
阶段合同套到另一条链。

本模块不负责：

- 旧 A11y 图遍历和随机游走主链；
- 根据应用名、控件名或业务领域硬编码推断功能；
- 把像素变化直接宣称为业务成功；
- 在遍历未结束时宣称 capability 或 M13 验收完成。

## 2. 代码入口

| 位置 | 当前职责 |
|---|---|
| `run_visual_traversal.py` | CLI 入口、参数、运行目录和最终结果 |
| `../explore/` | `--modular-explore` 的独立模块化内核；不导入本模块的旧主循环 |
| `visual_engine.py` | 依赖装配、共享账本与少量兼容接口 |
| `runtime/runner.py` | 默认语义遍历主循环 |
| `runtime/autonomous_loop.py` | Qwen 自主遍历主循环与阶段编排 |
| `runtime/autonomous_runtime.py` | 自主账本、checkpoint、恢复和 sidecar 持久化 |
| `runtime/autonomous_scheduling.py` | 全局任务池、阶段和工具目录 |
| `runtime/autonomous_page_update.py` | Page/Variant 暂存判断、纠正和 Region 复核讨论 |
| `runtime/autonomous_entry_commit.py` | Entry 候选、覆盖审计和事务写入 |
| `runtime/autonomous_action_execution.py` | 动作绑定、前后帧、落点和 Entry 结算 |
| `runtime/autonomous_completion.py` | 完成缺口、暂停和停止判定 |
| `state/` | Page、Variant、Region 与 State 登记和身份辅助 |
| `navigation/` | frontier 过滤与已验证图路由 |
| `grounding/` | 目标定位、Region 裁剪、滚动与长图 |
| `agents/` 与 `prompts/` | 默认语义链的 VLM 角色和提示 |
| `visual_resume.py` | 从持久证据原子重建运行快照 |

新代码应使用 canonical package；`visual_router.py`、`visual_state.py`、`visual_stitch.py`
等文件只保留旧 import identity。

## 3. 共享不变量

### 3.1 视觉与身份

- 实时完整截图是当前可见事实；旧截图只是历史证据。
- Page 表示稳定功能页，Variant 只表示会实质改变后续可执行操作的页面状态。
- 滚动位置、焦点、悬停、动态文字和普通数值变化不单独创建 Variant。
- 页面身份先于 Region 与 Entry；控件文字不得单独决定 Page 身份。
- 已登记 Page 不因后续 Region 或控件增减静默改名。
- 当前 active surface 可以是应用内菜单、对话框、抽屉或搜索面板；系统通知、桌面和其他应用不是目标应用结构。

### 3.2 几何与动作

- bbox、坐标、模板和视觉指纹是观察 sidecar，不是路由真值。
- 每次点击、悬停、输入或滚动都必须基于当前帧重新定位。
- 旧坐标不得直接复用；路由中保存的是可重新定位的语义目标与真实落点。
- 证据顺序为 `attempted -> executed -> landing_verified -> committed`。缺任一阶段都不是已验证图边。
- 静态、离线或 fixture 结果不得冒充真机、虚拟机或真实 Qwen 验收。

### 3.3 账本与完成

- Page、Variant、Region、Entry、ActionEdge 和 completion gap 各自持久，不以 Prompt 文字替代账本。
- Reviewer 意见是待核对主张，不能覆盖主 Agent 对最新截图的直接观察。
- 框架不按应用名、按钮名、位置、相似布局或主题自动推断功能等价。
- 无可执行候选只是 frontier 耗尽；只有 completion 合同满足才能宣称完成。

## 4. 默认语义遍历

### 4.1 主流程

```text
bootstrap
  -> 确认目标应用与当前 Page@Variant
  -> 新 State 登记 Region 目录
  -> 逐 Region 观察可交互入口
  -> Explorer 从当前页的待办入口中选一个
  -> 当前帧定位与点击复核
  -> 执行一个动作
  -> 识别真实落点并写 ActionEdge attempt
  -> 当前页无本地待办时，Explorer 选下一已知 Page
  -> Router 使用已验证图边到达
  -> 编译完成证据
```

`runtime/runner.py::run_traversal()` 是该链主循环。Engine 只保留依赖和兼容接口，不另造一套调度。

### 4.2 Page 与 Region 观察

- `IdentityResolver` 先返回 `known | new | unresolved`。
- `known` 复用已登记语义账本，但当前可见性与定位几何必须重新观察。
- `new` 用一次 Page map 同时选定 active surface 并登记 Region 目录。
- Region-local 只返回当前 Region 的语义入口；合法空数组可表示已观察且无入口。
- 可滚动 Region 的长图切片复用同一 Region-local 语义合同，不建第二套 inventory。
- 单个 Region 观察连续失败后保留 unresolved，不清空其他 Region 事实。

### 4.3 Explorer 与 Router

- Explorer 只看最新完整截图、本页待办入口、已结算结果和具体失败反馈。
- 已完成或确定终止的入口仍可作为历史事实显示，但不再给可选编号。
- Explorer 可选任一待办入口，不按列表顺序硬执行；无合法候选时必须给出可见理由。
- Router 只使用 committed 且 landing-verified 的图边；预测边不是可信路线。
- 每步路由后都用新截图验证真实落点；落到意外 Page 时记录真实边并重规划。
- 缺少反向边时，Reverse Edge Explorer 只提出一个当前可见的安全返回动作，真实结果仍由后图结算。

## 5. Qwen 自主遍历

### 5.1 角色和 Prompt

主 Agent 是唯一连续的多模态操作者。其他模型角色只在明确边界做无状态复核：

- Page 身份复核器；
- Variant 身份复核器；
- Region 划分复核器；
- Entry 覆盖复核器；
- 干扰处理器；
- 点击复核器。

Prompt 由稳定系统前缀、当前阶段合同、当前任务事实、本任务完整动作/拒绝历史和最新截图组成。
系统前缀先说明能力地图产物，再用四条稳定原则和少量正反例约束证据边界；应用和页面细节留在动态输入。
不同阶段不同时发送无关细则，工具参数 schema 只在输出合同中出现一次。

每个复核意见都必须给具体对象和原因。主 Agent 可根据最新截图接受或反驳；不得只因“复核器说了”就改写可见事实。

### 5.2 任务和阶段

运行期同时只有一个当前任务：

- `survey_page`：确认 Page/Variant，登记或增量调查 Region 和候选入口。
- `explore_entry`：到达一个已登记精确入口，定位、真实执行并结算。

当前阶段由框架计算，主 Agent 不自行跳转。阶段分为：

1. Page 身份：`identify_page`。
2. Variant 身份：`identify_variant`。
3. 身份复核：`review_page_identity` / `review_variant_identity`。
4. Region 登记与调查：`record_regions` / `survey_region`。
5. Entry 复核：`review_entries`。
6. 路由与定位：`route_to_page` / `route_to_source` / `locate_entry`。
7. 完成复核：`completion_ready`。

一份回复中的新证据若使阶段发生变化，框架先写入证据，同轮其他旧阶段动作不执行。
`page_update` 只在 Region 登记与调查阶段写入。

### 5.3 Page 与 Variant

- Page 和 Variant 分两步判断；Page 阶段不输出 Variant。
- 已知 Page 只投影它自己的 Variant 候选；新 Page 的 Variant 候选为空。
- 新 material Variant 必须经 Variant 复核，不能由主 Agent 直接写入。
- 身份输入包含到达来源 Page、触发入口、已知邻接关系和最近真实动作结果，不携带旧坐标。
- resume 若没有可信当前 Page，先重新确认实时帧身份，不先伪调度。

### 5.4 Region 划分

- Region 是共同承担稳定功能角色的可见组件组，不是矩形位置或单个按钮。
- 整页调查和 Region 复核必须登记当前前景交互表面中所有属于目标应用的稳定 Region；常驻、全局、
  重复、可复用、功能简单或暂时没有候选入口都不是省略理由。应用内模态表面位于前景时，后方宿主页
  只作为上下文，不重复登记。
- 可归入工具栏、导航组、内容面板或设置组的按钮只是该 Region 的入口。
- 单个控件只有在拥有独立于它本身的稳定功能内容或容器时，才可能构成 Region。
- 相同位置、相似布局、相近主题或共享内容槽不能证明跨页 Region 等价。
- 同页可独立展开或改变状态的重复实例保持不同 occurrence；只在经复核后共享 `region_ref`。
- 对已绑定 Region 的普通覆盖、调查记忆或临时几何更新不重复调用 Region 复核器。

首次新 Region 或新共享绑定使用一次完整划分提案，由 Region 复核器查看固定的完整证据截图。
复核输入只投影已有 Region 的名称与摘要；输出只含当前 `regions{name,summary}`、逐项
`revisions{old_region,decision,merged_into?,reason}` 和整体理由，不枚举按钮、Entry、候选数量或
代表操作。输入中的每个已有 Region 必须在 `revisions` 中恰好出现一次：`keep` 保持原名且该名
存在于当前 `regions`，`merge` 的目标必须精确存在于当前 `regions`，`remove` 不得携带
`merged_into`。遗漏、重复、未知旧名和不存在的合并目标由框架按具体名称拒绝，不由框架猜测
界面语义。

若复核器给出的完整当前划分改变了主 Agent 提案，框架把具体新增、合并、移除和结构错误返回
现有讨论，主 Agent 重交完整划分；只有当前提案中的 Region 全部被 `keep` 后才写账。因此本合同
不自动迁移已登记 Entry。初审加两次讨论复核最多三次；第三次仍不通过
则终止该讨论，不提供主 Agent 强制写入旁路。区域通过后，现有 Region 调查和 Entry Reviewer
继续负责发现与筛选值得探索的操作。

一个新页面的本页划分通过后，框架对其中尚未绑定身份的新 Region 做一次批量跨页复核。候选池只
包含 Region Registry 中每个 canonical Region 的一个代表 occurrence；`autonomous_region_groups.v6`
在 occurrence 中保存首次绑定时的 `representative_variant_name`，复核只读取该精确 Page@Variant 的
已有完整截图，找不到时跳过候选，不用同 Page 的任意截图替代。输入只投影临时编号、Region 名称、
摘要、所属 Page 和上述完整截图，不投影 Entry。Reviewer 按稳定功能、所拥有的
交互语义和复用含义判断共享；位置、形状、主题或布局相似不足以合并，证据不足保持独立。每个输入
occurrence 必须恰好归入共享组、明确分开组或未匹配项；遗漏、重复、未知引用和不是“一条当前
occurrence 对一条既有代表”的共享组均不写入共享关系。合法共享只令当前 occurrence 复用既有
`region_ref`，原 Page/State occurrence 证据继续保留，不结算、迁移或继承 Entry 任务结果。

动作前后 Region mapper 仍独立执行，用于相邻真实动作中的内容连续性及既有覆盖合同；跨页身份复核
失败或输出无效只让尚未绑定的当前 Region 保持独立，不会抑制或覆盖该 mapper 的结果。普通已绑定
Region 更新不触发跨页复核。

### 5.5 Entry 发现与覆盖

Region 调查先扫描可能交互的组件组，把所有对理解或执行用户命令有意义的操作提交给 Entry Reviewer，再由它区分
“正式记录”和“派发探索”。需要探索的操作至少满足一项：

1. 可能显露新的功能表面、Region 或控件集；
2. 可能改变另一个 Region 的内容或结果；
3. 能解决截图中确实存在且值得为后续遍历确认的交互歧义。

内容详情、阅读界面、选择或编辑模式、菜单和对话框都是新功能表面。已经看清只是选择参数值、调整连续数值、
切换语义清楚选项、移动内容位置或填写待提交表单字段的操作仍正式记录，但不建遍历任务。危险、不可逆或有外部效果但
对用户命令有意义的操作也只记录，记录不授权执行。搜索或筛选输入若会形成可继续操作的结果集合，仍需探索。

候选用简短的 `operation`、`target`、可选 `subject` 和 `control_type` 表达：

- `operation` 是用户操作；
- `target` 是当前截图可指向、带必要功能上下文的语义控件名；
- `subject` 只作可选的可读功能对象说明，不参与入口身份；
- `control_type=input` 只用于当前已可直接输入文字的字段，也不参与入口身份。

同一组重复内容或参数值默认只登记一个代表操作；预期直接效果不同的操作保持独立。
文字和附属图标只在确实属于同一组件且预期直接效果相同时合并，不按相邻位置硬合并。

Entry 复核器查看最新完整截图、待审 Region、主 Agent 候选、已有入口和理由：

- `independent_entries`：需要建立并后续真实执行；
- `record_only_entries`：命令相关且值得正式记录，但直接效果浅显，无需专门遍历；
- `non_task_entries`：静态、装饰、应用外或没有用户命令意义；不能用它表示“无需探索”；
- `deferred_entries`：有价值，但当前可见状态或前置条件使其暂不可执行；
- `deferred_regions`：当前整图不足以审计精确 Region 的覆盖。

复核器可补充待审 Region 中明显漏报的可见入口，但不能新建、合并、拆分、重命名或改绑 Region。
Qwen 适配层会原样保留上述四类入口结果；`record_only_entries` 不会在模型回复与账本提交之间被省略。
每个请求 `coverage_complete=true` 的 Region 必须有 accepted Entry audit 才能完成。

复核器丢弃主 Agent 候选时，批量结果按 Region 分账；只有含争议候选的 Region 保持未完成，无争议 Region 可提交已接受
入口和覆盖。复核器若明确判断主 Agent 整体理由不一致，则本批 Region 都保持争议。后续主 Agent 只收到 `task.region`
的争议项和正式入口；争议期间正式入口附带真实 `entry_id` 供核对，普通调查不增加编号。上一轮本 Region 的每个争议候选
必须在下一份 `page_update.entry_resolutions` 中逐项给出 `keep|drop` 和具体理由；`keep` 项仍在所属 Region 的 `entries`，
`drop` 项不再出现。遗漏、重复、未知引用、跨 Region 结算或仅省略候选都不能结束争议。全局或顶级导航切换到另一稳定功能内容时属于入口；
看到已选中的导航项后，主 Agent 和入口复核器都要逐个扫描同组当前可见的未选中项，不能只记录当前项或导航组两端控件。
当前已选中且点击不会切换内容的导航项不重复登记。
入口复核使用产生候选的固定完整截图，不改用两阶段之间较晚取得的画面；后续临时遮挡只影响任务执行与恢复，不能反向抹去
候选在原始证据中的可见性。
固定发现帧还用于按需纠错：只有精确入口任务回到来源 State、主 Agent 扫描 owner Region 后仍报告目标不存在时，同一
Entry 复核角色才比较发现帧与当前帧。发现帧支持的入口保留，当前仍可见则重试定位，当前缺失则恢复局部状态或延期；
证据不确定时保留缺口。只有主 Agent 的定位失败和独立双图复核共同证明发现帧不支持候选、当前图也缺失时，才标记
`invalidated`。该记录保留审计证据，但不再派发、不阻塞完成，也不投影成能力。
后续讨论只把仍在本轮候选集中的旧裁决交给复核器；已经由主 Agent 显式结算的旧项不再回灌。复核器重报的非候选
`non_task_entries` 或 `deferred_entries` 没有写账能力，框架记录后忽略；越界新增入口仍拒绝。若具体纠正后的状态相关
输出仍与上一份无效回复完全相同，框架不再重复调用，而把当前候选和 Region 推后到新 GUI 证据出现后复查。
主 Agent 若对 Reviewer 已保留且本轮仍存在的候选重复写 `keep`，同样作为无状态影响项忽略；额外 `drop`、未知引用、
遗漏真实争议或把已丢弃项继续放回候选仍拒绝。

共享 Region 的规范入口属于该 Region，而不是某一个 Page occurrence。主 Agent 调查当前 Region 时会看到这份
已有入口精简列表；与其精确同 `operation + target` 的当前项不再写入 `entries`。即使主 Agent
或复核器重复返回，框架也会在写账前继承并移除该重复项。只有本状态中新出现或功能语义改变的操作继续接受入口审核。
复核器引用 `equivalent_to_entry_id` 时，框架同时核对编号、`operation` 和语义 `target`；任一项不同就拒绝复用并返回两边
的具体动作和控件名，不接受自由文本声称同义。
同一语义控件上的不同操作仍是不同入口；相同原始图标或标签若在当前上下文中功能不同，必须使用不同的语义 `target`。
当前选中、禁用或受前置状态阻挡不删除既有入口；该入口真正成为当前任务后，由主 Agent 根据最新截图执行或使用
`defer_current_task` 延后。

### 5.6 同质实例与局部状态

- 同质 Region occurrence 可共享 `region_ref`，但每个可独立展开或改变的实例仍保留 occurrence 身份。
- 代表实例的真实动作为 `verified`；其他同质实例只保存推断来源，不冒充重复点击证据。
- 一个已验证动作只能同时结算同 Page、同 owner Region、同控件类型且同一操作语义的待办入口。
- 看到明确结构或能力冲突时，主 Agent 可提交 `split_from_group=true`；复核通过后拆组并重开受旧推断影响的入口。
- Region 局部状态只保存已观察值和真实转换，不枚举状态组合。
- 页面选择模式只保存已发现模式、当前临时成员和真实进入/退出转换。
- 应用级状态独立于 Page 路由；跨页出现同值只记录新观察，不自动推断业务因果。

### 5.7 全局任务池

调度结构为 Page State -> Region -> Entry。Region 是所属 Entry 的父目标，不再另造一个自由 Region probe 阶段。

- 框架按已验证页面图的距离跳数选择可运行任务。
- 同距离时，优先完成当前 Region 中已建账的 Entry，再切换到其他 Region。
- 其他 Region 的本地任务不应打断已派发的跨页 Entry。中间路由、滚动、定位和恢复都属于同一任务，直到精确入口结算。
- 当前不可执行的入口可用 `defer_current_task` 指向一个已登记前置 Entry。
- 前置 Entry 结算后只使目标进入重查，不伪造“已解锁”。
- 直接结果与预期不符时，保存真实结果和失败原因，然后继续调度其他任务；不因旧预期错误就伪报控件失败。
- 同一导航栏等共享 Region 一旦正式绑定和审核，后续 Page 复用它的入口账本，不重复生成一套任务。

### 5.8 动作执行与结算

工具目录按当前阶段收缩。共享动作包括 `click`、`hover`、`scroll`、`navigate`；精确输入 Entry
再开放 `input_text`；Android 可开放 `long_press` 和 `double_tap`。

- 一轮最多执行一个真实 GUI 动作，且只结算最后一个仍 pending 的动作。
- 正式 Entry 尝试必须绑定当前派发的精确 entry ID；模型不自行伪造 ID。
- 输入 Entry 只能由 `input_text` 完成；点击聚焦只是定位中间步骤。
- `previous_action` 描述动作后的真实可见结果、是否符合固定目标及具体原因。
- `before_value` 和 `after_value` 允许是空字符串，但在宣称值变化时两者必须不同。
- Region 影响分为 `structure | state | value`；只有 `structure` 使对应 Region 覆盖失效，其他两类只保存观察。
- 动作后无可见变化可能是禁用、未激活、点位错误或操作本身无可见效果；必须保存模型给出的具体理由，不把字段变化算作真实进展。

点击复核器接收最新完整截图、拟点局部图、当前任务摘要、主 Agent 完整本轮理由、动作与可选正式 Entry。
它检查主 Agent 是否有意选中自己声明的界面对象、真实点位是否命中及安全性；不预测动作一定成功。
有意点击弹层外的应用内安全空白面可以是合法中间动作，不要求该点本身是按钮。

### 5.9 路由、局部恢复与干扰

- 已知跨 Page 路线由 Router 执行；没有已验证路线时不伪造可达性。
- 当前已在正确 Page，但目标 Region 或 Entry 处于另一未登记局部状态时，主 Agent 根据最新截图逐步找一个安全局部转换。
- 局部恢复动作同样经点击复核、前后图结算并写普通 ActionEdge；不用“返回原状态”假设替代真实目标状态。
- 干扰处理器只处理当前截图中的临时弹层、菜单、系统层或应用外界面；其策略仍受动作安全门限约束。
- 外部临时表面虽不登记为 Region，但只要遮住应用稳定区域的一部分或同组控件，页面调查就不能提交覆盖完成，而应先经
  `handle_interruption` 取得无遮挡截图；处理器可在 `ignore/wait/hover/click/back/unresolved` 中选择有界最小策略。
- 系统前景查询连续两次未知时，不按最近动作类型放行或停止；同一个主 Agent 只比较当前截图与可用的最近确认截图，通过
  `report_app_scope` 给出视觉归属，不能在这轮登记 Page、Region、入口或动作结果。
- 明确进入其他应用或主 Agent 仍无法判断时，桌面优先激活本次运行绑定的窗口，Android 优先唤回原任务；失败才保留数据
  重启。恢复步骤只写运行记录，不生成页面或动作边。
- off-app 或意外 Page 是真实动作结果，必须保存后再恢复，不得直接丢弃 attempt。

### 5.9.1 单主 Agent 页面实验

显式 `--autonomous-page-session` 开关让同一个主 Agent 自主管理当前 Page，而不是接受框架派发的 Region/Entry
任务。每轮输入只有最新截图、可选动作前截图、当前 Page 工作记录、已知 Page 摘要与连接、最近八条按执行次序排列的
已结算动作和动作计数。每条动作直接取主 Agent 已交给框架的目的、操作和参数，再附框架保存的结果及可选落地 Page；
当前待结算动作由独立字段及前后截图提供，不在历史中重复。
主 Agent 可在一轮中同时更新 `strategy/todos/regions/operations` 并选择一个动作；框架给新记录分配 `t/r/o` 稳定编号，
`operation_attempt` 必须按 `operation + target` 唯一命中当前 Page 操作，其他用途的动作若精确命中也自动绑定。

该实验不调用 Page/Variant/Region/Entry/Click specialist，也不运行全局任务池或阶段工具裁剪。框架仍负责动作 schema、
当前帧坐标、一次一动作、前后证据、应用范围恢复、ActionAttempt/ActionEdge、Page@Variant 登记、预算和断点保存。
模型把动作声明为 `safe` 只是执行合同，不是独立安全证明；不确定、危险、不可逆和外部效果操作不得执行。Page 只有在
没有 `pending/in_progress` TODO 或 operation 时才接受 Agent 的完成声明；遍历结束仍标为 Agent 声明，不冒充框架覆盖证书。
记录持久化到 `autonomous_page_sessions.json`，同时把 Region 和操作幂等投影到既有 sidecar，以便部分 bundle 继续编译。
旧自主控制链仍是默认，本实验验证稳定后再决定是否替换并删除旧阶段链。

### 5.10 历史、循环与暂停

- 完整历史保存在 trace/checkpoint；主 Agent 获得当前任务相关的动作、参数、真实结果和具体拒绝理由。
- 动态 Prompt 后部按需显示最多四条当前任务状态，只包含仍会影响下一步的待结算动作、最新未解决拒绝、前置复查、
  最近结果或当前定位。相应信息从普通历史或任务 JSON 中移出，不重复发送；没有有效约束时不显示空栏。
- 主 Agent 每轮用不超过 240 字的 `task_strategy` 改写一句当前推进方法；框架随原有 observation 历史保存，状态栏只显示
  当前任务最新一句，不累积旧策略，也不读取其他任务策略。其余状态仍由框架从现有账本派生，不增加模型调用或独立持久记录。
- 同一任务在同一 before-frame 重复完全相同的已执行动作会在投递前拒绝。
- 连续拒绝或无可写入证据不等于真实进展。
- 当前任务连续无进展后可暂停并调度其他任务；全局持续无进展才停止运行。
- 失败 Entry 保存失败类型和理由后跳过；遇到前置可解的情况使用延期，不伪造完成。

## 6. 滚动与长图

- 滚动必须绑定当前帧的可见容器或明确点位，不按旧 bbox 盲滚。
- 框架分别记录页面滚动与 Region 容器滚动；不同容器的前沿不共用。
- 滚动后用最新截图判断是否真实移动；不移动时增加该方向的终点证据。
- 长图只用于统合已观察的可滚动内容，不绕过实时目标定位或点击复核。
- 达到安全步数上限、截图不再移动或证据无法连续时，保留 partial 而不伪造完整长图。

## 7. 持久化与 resume

默认语义链的权威图与 attempt 证据按现有 graph/artifact 合同写入。

Qwen 自主链的主要 sidecar 为：

- `autonomous_natural_map.json`：自然语言 Page/Variant 关系与已验证路线；
- `autonomous_regions.json`：Region occurrence、共享 ref、覆盖审计与局部状态；
- `autonomous_entries.json`：Entry 语义、owner Region、状态、代表、探索策略与结果；其中 `recorded` 只证明当前截图已观察到操作，
  不进入任务队列，也不等于动作效果已验证；
- `autonomous_temporary_states.json`：旧临时状态兼容账本；
- trace/debug、前后截图和内部图；
- `autonomous_completion.json`：自主模式的最终完成或缺口结果。

resume 先完整重建内存快照，再一次性发布引用。不完整或相互矛盾的 checkpoint 不能半写入活运行。
显式 Android `--resume` 只在当前前台仍是请求 package 时保留当前画面；离开应用、无法确认或检查异常时仍重置并重启目标入口。

## 8. 完成与验证

### 8.1 完成条件

完成至少要求：

- 当前已知 Page/Variant 没有未调查的必需 Region；
- 每个声明完成的 Region 都有 accepted Entry audit；
- 所有可运行 Entry 已验证、推断复用、明确失败、合法延期或保留为具体 gap；
- 没有 pending 动作、未结束 Region/Entry 复核或未处理结构纠正；
- 没有仅因静态图、fixture 或模型预期而宣称的图成功。

预算耗尽、最大动作数、无验证路线、延期前置未满足或无法恢复可以产生 partial/blocked，不得改名为完成。

### 8.2 最小验证

按改动合同选择最小足够层级：

- Prompt/schema 改动：对应协议、解析和一条运行数据路径；
- 单模块行为：直接行为回归、相邻合同和 `py_compile`；
- 共享调度、resume、schema 或 completion：直接共享合同与必要相邻回归；
- 只在发布、基线、认证或用户明确要求时运行全框架门。

文档、离线、fixture、真实 Qwen、真实模拟器/VM 和最终 bundle 必须分别报告，不能互相代替。

## 9. 当前已知风险

- Region 对话中，复核器仍可能对主 Agent 产生锚定，导致工具栏、对话框操作栏或单控件边界判断不稳定。
- Region 复核器提出的合并、删除或改名只会触发主 Agent 完整重报，不自动迁移正式 Region 或
  Entry；若后续需要直接重写已经落账的 Region 身份，仍需另行设计迁移合同。
- Entry 复核器可能把“当前可执行但优先级低”误用为 deferred；延期本应只表示当前不可执行或有可验证前置。
- 跨页共享 Region 和同质 Entry 复用仍依赖模型给出足够精确的语义证据；框架不会为追求去重率而强制合并。
- 旧 guided 兼容路径仍保留部分历史 parser 和 shim；新自主链不得因此重新启用已退役的自由 Region probe。

## 10. 文档维护规则

- 本文只更新当前生效行为、入口、数据合同和已知风险。
- 一次真实运行的时间、提交、截图、模型原始输出和通过/失败结果只追加到 `design/changelog/YYYY-MM.md`。
- 新方案在实现前放专项设计文档；实现后才将实际行为压缩到本文。
- 已替代合同从本文删除，需要追溯时依赖 changelog 和历史快照。
- 本文不再添加按日期命名的实验章节。

模块化CLI可用`--defer-partition-review`显式试运行：只透传给独立explore内核，默认False；延后整页分区预审并保留质量gap。行为边界见explore_kernel/page_inventory.md，不改变旧语义/自主遍历链。
