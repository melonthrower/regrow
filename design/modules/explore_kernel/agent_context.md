# 提示词、模型合同与 Semantic Exploration Focus

2026-09-18：`contracts.HANDLING_GUIDANCE`是主Agent/分区Reviewer的共享语义来源；`submission_contract`生成唯一阶段说明，状态栏及`submission_schema`/解析器共用。编辑阶段只修改缓存，不再同时要求填写screen/previous_action；所有提交字段null仅表示先退出编辑，下一轮按观察合同重判。操作拒绝在真实后续投递后退出当前纠正列表，原事件仍保留。必要输入：主Agent看阶段和实际动作；分区审核看当前组成、父子、observation、handling/reason及框架scope；身份审核保留原父子不可复用约束，不增加范围全文或几何。结果仍依据原动作前后证据，不把预测当现场。

2026-09-17：“推进阶段”由runtime按pending、位置确认、当前本地绑定和已有Region路线生成。navigate提供第一步，prepare要求根据当前前景提出合法有界准备，不能反复寻找不可交互背景owner。查询作用域同时包含位置、目标和已有Region绑定/状态签名；有新适用条件才重开查询。无效引用属于原动作/协议纠正，不能直接冒充查询耗尽。API/GUI预算仍不进入模型Prompt。

2026-09-17：最终主Agent请求新增“工作区块”和“任务相对环境”，共用region_coverage；树仅是图的只读投影。支持operation/region两种展示尺度，保留任务、工作路径、当前本地绑定、折叠兄弟及已观察条件。未知取值不编造，不把State名称推断为因果规则。pending仅呈现来源位置，当前落点/owner留空；deferred当前绑定不作为可用点击owner，适用来源另列。见[工作范围](region_work.md)。

2026-09-10：清单纠正增加短索引卡和page_report_edits。普通轮null，编辑轮旧位置/回执/完整清单/action留null，由框架继承同帧候选并继续原校验；接口规则见report_edits.md。主Prompt仍受8500字符限制，编辑模式新增Schema不等于该字符上限包含Schema或图像。分区预审输入仅保留结构、控件观察和动作目标，去掉与该判断无关的参数/历史文字；编辑不会新增模型角色，但审核及后续纠正照常计HTTP。

2026-09-10：Region/Element数组说明增加输出前容器、直接父区、静态内容及前景归属检查；不固定区块数。内置模型新增review_known_state方法，沿用Region审核角色，专门比较拟复用State的两张图；与主Agent清单纠正及Region/Operation审核分开计实际HTTP。详见location.md。

2026-09-10：通用分区指引补齐静态内容归Region summary、标签优先/无标签用稳定功能对象、数据值和展开态不作Region身份、普通展开保留原区与独立编辑上下文区分、局部纠正保留无关边界。内联独立结果区归可见来源容器；接管输入的弹层仍遵守原前景边界。新Element空动作拒收条件不变，反馈明确可移除误报的静态Element而不编造动作。没有应用名/按钮/坐标特例，没有新增模型角色或固定调用。83项聚焦离线检查通过；11张Settings/Files/Clock保存帧已选定并核对来源，初次启动被自动审批拦截；用户随后明确授权所选及新增截图外发，模型验证已运行，结果与失败分批保留，详见本月日志与general_partition_20260910系列证据。不能据离线检查宣称跨应用准确率。

2026-09-10：历史上下文从“6详情+其余全局索引”改为来源/共享Region邻居和少量文字候选，主要返回具体控件/操作卡，State卡辅助定位；全局索引不再发送。context_query可按标签、功能、区块及明确scope/action补查，pending保持；当前控件/回执/纠正不裁剪。检索历史24000、主Agent动态文本96000 UTF-8字节上限，超限在付费请求前停止，不是计费token保证。名称变化按带证据的历史称呼检索，身份仍由原审核流程维护。详见[本地知识检索](knowledge_retrieval.md)。

2026-09-10：主Prompt强调主体切换时仍保留的导航/工具栏应独立共享，不随主体重建；未添加应用名、坐标或专用按钮规则。当前Task跨State复用，任务卡来源集合由稳定操作的合法本地绑定提供；真实当前绑定变化且无pending/报告纠正时清除旧即时纠正与strategy，历史动作和尝试预算保留。

survey_complete只管当前前景自身的清点；未开子菜单/其他页面留作后续explore任务，不因它们尚未完成而反复清点当前菜单。当前列表的截断或未见选项仍需调查，重启定位仍允许先部分确认。

完整清点且可安全关闭前景时，主Prompt与survey卡允许同轮page_report和无owner的Back。QwenExplorerAgent.decide（API/Luna共用的适配层）不再清空这种Back；仍清空完整清单附带的click、wait、带owner或operation_ref等其他动作，原始raw回复不修改。Runtime按原路径先接受清单/审核，再执行Back、保存新Attempt并在下一帧结算。实际动作须能追溯至该清点主回复，且中间没有新主决策，才算合并生效；单看模型提出Back不算。

动作审计的last_call可能是清点后的Region/Operation审核：需向前定位最近主调用，确认中间没有新主决策，再对照report+Back；不能要求last_call字面等于主回复ID。运行时提供共用ReportCorrections预算时，适配层原样抛出解析异常，保留PAGE_REPORT_INVALID及具体字段，不再包装成丢失字段信息的ValueError；独立调用的原两轮格式重答保持。

待结算时，`status.build_agent_context`将普通任务卡的instruction替换为动作前后时序说明：卡中的位置、当前绑定与路线来自图1，不能覆盖图2的实际落点。主Agent以新图确认已清点State且无增量时用`page_report=null`，可复用卡中已存在的element_ref或对应State的known_source_bindings继续动作。本轮缺引用时先仅结算，下一轮通过current_page_record读取已知目录，不为取编号重新登记。新结构、遗漏、变化和未完成survey仍补清单；重启rediscovering阶段的定位合同保留。不新增整页候选表或模型角色，不把历史路线当实际到达，也不放宽source Variant绑定检查。

参数调查按未知功能、条件和指令所需值域选择；已知值域不重开，已确认关系不重复试验。可能控制子功能显隐或可用性的模式/总开关仍做安全可逆对照并恢复，在现有观察和功能说明中记录前置条件。普通明确控件只登记，未查范围保留未知。这是通用模型指引，不按应用名或按钮词匹配，不保证模型不漏判，也未新增机器可检查的依赖约束。

operations是控件支持的动作目录，不是本轮计划；已选中控件保留动作并record，不重复执行。对应字段说明和空动作纠正反馈同步；不会按选项名称在程序中补click，也不放宽新owner必须有动作的合同。

无owner/operation_ref的Back只恢复前景，不清除此前失败操作的约束。runtime在有/无Task下均向前跨过这些Back，若回到相同来源State且上一实质操作仍为no_effect/uncertain，则复用既有动作/参数/近点判断拒绝原样重试。不同文本、实质不同落点或中间实际执行的其他操作仍可重新判断；不依据应用名或控件文字封禁功能。

2026-09-09：显式exploration_goal下不再自动派发旧Operation待办或替换焦点；保留已选活动任务和必要survey，其余由主Agent按范围用next_operation_ref或实际owner动作选择。无Task时可用当前唯一recorded/verified绑定恢复，仍保留绑定与近重复检查。无动作、无新事实的范围决策以scope_idle/partial结束，不冒充全应用完成。无exploration_goal时沿用原自动调度。

2026-09-09：新Element必须提供至少一种具体动作，不再接纳无动作的新控件占位；容器/组合功能归Region。已知Element可只补observation而不重复operations，历史账本仍可读取。范围卡不再把恢复误导为必须先切换开放Task，当前record控件可直接用于恢复，缺绑定先补。

2026-09-09：删除不分范围的“未知Page必须探索”绝对指引；明确输入的有限探索范围优先于待办派发，临时跨区结构比较不扩展为该区参数遍历。范围外的真实结果保留，不当作本任务覆盖。

2026-09-09：known_graph恢复每个历史State的survey_complete标记，便于关闭临时前景后判断是否需要重报；动态提示明确查该标记。只补上下文事实，不改变清点完成条件或省略新信息。

2026-09-09：主Prompt区分虚拟机/浏览器外壳与目标应用前景窗口；父Region允许无直接控件，以无应用标签的容器行/子组parent_ref例子说明包含。实际Luna层级仍待续测，不把全null报告视为通过。

2026-09-09：删除survey必须完成后才能调查已登记控件的旧门禁。清单首次取得ref后，可用当前合法owner继续点击等调查；动作仍逐次结算，不提前完成survey。同轮清单的候选点击仍留到下一轮。有限参数列表继续观察未见选项，同质数据可以按功能结构收束。

2026-09-09：现有主Agent增加Region.parent_ref和Element.observation输出字段，功能与条件仍以自然语言说明。
current_page_record与known_graph投影父区引用，控件最近观察带State/截图来源，不把它声明为执行时实时状态。
parameter_summary只描述形式、选项和未知范围；形式已见不等于选项完整，是否继续展开按未知功能、条件和必要值域判断。
新选项证据可在已observed操作的parameter_info回填；none参数按钮仍不能被其打开表单的字段覆盖。
Runtime的可选exploration_goal进入探索范围卡，供Luna选择合适任务；没有引入程序按应用文字判断范围的规则。
旧satisfied_operation_refs不再解析或执行；同名字段出现即明确拒绝，实际owner回执机制保留。

2026-09-09：`agent.decide()`在动态输入中附最新原图width/height与现有point_1000换算规则。
有两张pending前后图时，按动作前图尺寸提供上一动作的实际像素落点，不用后图尺寸换算历史动作。
原上下文不修改，系统Prompt/输出Schema/坐标执行协议不变，不新增角色或目标坐标。
两组原始失败请求的保存帧对照均取得目标内落点；这只是离线定位证据，实机效果另验。

2026-09-09：同帧Region效果纠正的“保留的已校验清单”只提供位置和Region索引/引用/名称，控件列表不重发。
主Agent只修region_effects，page_report可空；框架沿用已通过结构/Element检查的部分。若需重判可明确uncertain。
主Prompt补充已有合同：Element内同一种action不得重复，不同点击落点分开；保持原8500字符上限。

2026-09-09：恢复指引明确区分局部Region定位与旧State身份。若复用已完成State，按最新图报告完整Region引用组合，
elements/region_operations留空；需要新局部上下文可用new_state、空state_ref并复用已知Region。
本恢复轮多报控件仅审计，不覆盖已完成State的已有绑定；之后普通清单路径保持。

2026-09-09：survey按功能结构收束，截断只允许调查、不强制遍历全部数据/参数；同质结构已明确则完成并注明范围。
pending上下文中的“已知页面无增量可省略清单”只适用于已完成清点的State；未完成survey仍须提交完成标志。
原滚动证据、Region owner、坐标与前后效果检查保留；新指引不把图中未见值当作已观察。

2026-09-09：延期任务卡明确可用已登记的record操作完成必要安全前置，不要求把前置用next_operation_ref
重新派发或声明代表探针；移除该分支已过时的purpose/current_task_result字段指引。动作与任务选择门禁不变。

2026-09-09：任务精确卡补充本任务在其他已知来源State中的唯一历史owner；仅列该目标操作，
不发送全图Element或坐标，不宣称当前已到达。模型按最新截图确认对应State和控件后才复制，
动作仍通过原source Variant检查。删除“派发即本轮必须执行”的提示，避免为派发而重复已选中入口。

2026-09-09：首次完整清点指新State的首次发现；恢复已有State只确认可见Region并报告实际增量，
已有Element/Operation列表可留空。同质数据只需一个具体可见代表，实例内部的不同功能控件仍分开；
不得把“全部同类按钮”作为一个物理Element。删除重复说明以保持原8500字符上限，Schema不变。

2026-09-09：主Prompt明确移动scroll起点与像素幅度，需避开独立覆盖控件；左右方向与执行器保持一致。
参数observed不要求穷尽边界/步长。none/observed只是同一已确认操作的参数观察标签，允许有证据地修正，
但标签变更不计作新的探索进展。输出Schema不变。

2026-09-09 Region Reviewer补充：组件边界是对比较候选的判断，显露因果是对其独立source_transition的判断；
候选不同不禁止真实来源动作显露当前组件，不要求为满足字段组合改写视觉判断。输出Schema未变。

2026-09-09 目标修正：主 Prompt 删除按搜索/筛选/显示方式一律 record 的限制及普通参数固定两个代表要求，
用未知功能结构/参数决定探索；明确不把本轮 action=null 解释为后续无任务。首次清点覆盖外层功能导航，
界面无法证明对象类型、输入捕获或动作结果时保持不确定。安全限制仍优先于探索需求。
`known_graph()` 给每个 State 附上原始 `state_summary`，不附旧控件或坐标；主 Agent按当前内容核对
已知身份，相同导航不足以认成旧 State。以下“固定 Prompt 不变”只指同日更早的上下文压缩变更。

2026-09-09：固定系统 Prompt/Schema 不变。动态纠正卡只补入错误文本明确提到的 Element 的历史
Region/Variant、来源 State 和合法 co/参数对应表，并明确不证明当前可见或可点击。
已知 State 动态卡强调增量报告，新 State/前景仍完整清点；当前页面卡只去除与探索焦点完全相同的
memory/summary，绑定、状态、参数及证据字段不删。已独立结算但未接纳的清单通过“待补清单”提示，
可修复或先探索其他可靠入口，不重做旧动作。焦点强调页面/Region 功能与必要信息，内部任务类型不变。
缓存收益仍须看实际 cached_tokens/耗时，保存输入投影不是性能实测。

2026-09-08安全补充：主Prompt明确安全优先于任务派发及代表值验证；可能失去可自行恢复控制、开放共享/远程访问、降低保护或破坏数据的操作只记录。增加熄屏1分钟与共享开关反例，说明可逆不等于无人值守可恢复。未改Schema/CLI或添加名称黑名单；旧待办也不能绕过此边界。具体实机例子见REGION_TRAVERSAL_ALIGNMENT.md。

2026-09-08续测：恢复工作卡的“取得当前绑定后即可继续”现与运行时一致；当前区块报告通过后解除恢复阶段，允许通过刚登记的中间控件发现返回路线，不要求路线事先验证。任务目标仍保留，普通动作检查不放宽。

2026-09-07：next_operation_ref 的说明明确区分任务切换与辅助调查，当前任务由框架维护。任务选择拒绝具体指出字段、原因和继续方式；非 pending 清单拒绝不会因下一轮任务切换立刻丢失。Element Reviewer 非法回复直接交回 Reviewer；候选分区不清时交主 Agent 修改。共用失败预算，不新增模型字段。

## 2026-09-07 结果重点与经验

主Agent逐次报告效果、失败原因和限制，不做全局结束判定；Schema不再包含finish。
清单同轮不能用空owner点击；收到缺owner反馈后优先选择另一已绑定可执行待办，保留原候选，不将无效提议当作按钮失败。
恢复清点任务的工作卡明确“确认来源State的可见Region后继续普通清点”，不要求取得Operation binding或本轮完成清点。
全局队列和gap由框架处理，无待办时不追加完成复核调用；若仍有pending，只提供其结算上下文。

不新增输出字段。主 Agent 在已有 target/reason/memory 中选择最能说明功能的结果，region_effects 继续保存实际因果。
动作预测与结果报告只列相关变化，不枚举全部区块存留；保持不变或无关变化可省略，干扰判断/交互时在已有reason简述。
本轮需要记录的效果引用与最终page_report区块划分对齐，各区块分别归因；无需逐项解释所有省略。
Region Reviewer 不把省略视为错误，只在真实动作和前后图支持时补充显露关系，不以先后顺序推断因果。
不完整清单可以无动作取得ref、补充观察或纠正报告；需要更多画面信息时才调查/恢复，不重复提交无新增事实的清单。
经验以适用情境及对后续选择的影响为重点，瞬时状态放在 summary/reason；不要求每轮写新经验。
pending 输入保留一条进入动作前 State 的已有连接，供理解旧区块入口，不自动继承全部显隐结果。
Operation Reviewer 明确：身份可共享而条件结果不同；identity 提议不升级 result。代码原本已有该降级保护。


## 2026-09-06 已实现的最小对齐

- previous_action 新增 region_effects 数组，每项只有 region_ref/report_index、change、cause；
  前两者二选一定位旧 Region 或本轮清单行，后两者表示变化与原因。空数组表示没有可报告的区块变化。
  不重复描述整屏，解释继续使用原 reason；Region/Operation 身份复用仍由原流程处理。
- 原 function_info/memory 明确用于新增经验、失败原因的暂定性、适用上下文与例外修正；不新增反思调用。
  recent_actions 在原六条上限内还可取同一目标 Region 的其他历史焦点结果，不只当前 Task。
- 顶层 next_operation_ref 通常为空；Luna 可依据经验选一个当前可见、开放且唯一的 co。
  原待办回到 pending，新目标使用已有 Task，strategy 保存理由；先结算 pending，未完成普通清点时不改向。
  只有这两个小报告扩展，没有新增持久 Schema 或第二套任务/记忆数据库。
- 这些接线已做离线验证，尚未证明真实 Luna 的探索效率或经验质量提升。


最后更新：2026-09-05

## 当前原则

主 Agent 负责看图、登记界面事实、选择下一次 GUI 动作；框架负责稳定 ID、Operation
binding、Task 状态和完成判断。`action` 不再输出 `purpose/operation_ref`；清单和代表探索只复制
框架给出的稳定 co。模型不输出 `task_result`、`current_task_result` 或 `satisfied_operation_refs`。

静态系统提示只保存 Page/State、Region/Element、Operation、代表参数、前景安全和
before/after 回填合同，不放应用专用规则。OpenAI-compatible 后端把它放在稳定
`instructions`；每轮变化的截图和短上下文仍在 user 输入。真实缓存收益必须单独读取
API `cached_tokens`，不能从消息形状推断。
2026-09-04 将固定说明按“前景和 Region概念 -> Region变化图 -> 清点与引用 -> 功能和参数 ->
动作与结算”重排；故障规则只保留一次，并把普通 survey 任务卡从 506 字缩为 239 字。
概念段使用自然语言，字段名集中在对应输出规则；Page继续只是 Region组合的组织信息。

## 动态输入

实现入口是 `status.build_task_view()` 和 `status.build_agent_context()`，只从传入账本和运行期信息投影字典。
任务切换时清除旧动作纠正、保留未完成的报告纠正、更新当前任务等状态操作仍由 `runtime._context()` 完成，再调用上述投影；
上下文模块不持有第二份 pending、计数器或 ledger。对应测试为 `tests/test_explore_status.py`。

每轮只给主 Agent：

- 最新完整截图；存在 pending Attempt 时再给 before 图；
- 代码生成的短状态栏；
- 有 pending Attempt 时，回显精确 `attempt_ref/kind/owner_ref/target/direction` 和动作前 source Region refs；
  input_text 另回显 Attempt 中已有的 text，供同一次 before/after 结果判断使用；不增加模型输出字段；
  结算时还可更新 after 截图中重新可见的已知 Region，新 Region仍由当前清点写 memory；
- 有 pending Attempt 且保存过主 Agent 原始 reason 时，附“动作前说明（含预测，不是已验证事实）”；
  精确绑定该 Attempt，不使用当前 Task 的新策略替代，旧记录没有说明时不补造；
- `探索焦点`：当前 Page -> Region -> 目标操作的自然语言路径、目标和同 Page Region memory；
- `当前任务精确卡`：目标 Region-owned CanonicalOperation、当前位置、当前可执行 Element/Region
  owner 和必要来源 State；Page/State 只提供可见与路线上下文，不创造新的 Operation；
- `region_route`：以目标 Region和目标 CanonicalOperation为完成条件的最短已验证路线；每跳列当前
  local owner、稳定 Operation、预期 reveal/hide Region与 Transition/Attempt证据；
- 当前页面已登记的 Region、Variant、Element、Operation 和状态；
- 已知 Page/State；只有确实需要返回来源时才带连接；
- 当前焦点最近六条动作回执：每条列焦点 Operation、实际 Region/Element/Operation、
  source/target State、outcome、visible result 和是否精确完成焦点；
- 一个最新合同错误（若有）。
- pending settlement失败时的一张 `合同纠正卡`：精确 error code、field path、期望/收到值、
  已接受事实、禁止动作与 `1/3` 至 `3/3` 的共享计数；
- 当前两个代表共同探索时，`探索焦点`列出问题、全部成员、两个代表和已完成 owner；
  第二个代表的 pending 卡只在需要最终结论时增加 `representative_same_kind_required=true`。

有 pending 动作的双图输入中，图1和待结算动作详情用于结算 `previous_action`；“当前页面已登记内容”为空，
不再发送动作前来源 State 的详细控件清单，page_report 只根据图2清点。输出前逐项确认每个
Element/Operation 在当前最新截图真实可见，其他 Page/State/Variant 或共享 Region 的旧按钮不能作为当前
可见证据。动态状态栏在每个 pending 轮重复这一条，避免页面切换时把来源页清单复制到目标页。

每个已知 State 行均提供 `known_regions` 历史目录，每项只有 Region ref 和名称，不附旧 Element 或坐标。
2026-09-09 删除仅选动作来源/最近入边/既有落点的过滤：真实返回可到其他已知 State，不能让模型认对 State却拿不到区块编号。
即使当前位置已清空，已知 State 的目录仍可用于定位。不遍历全图发送详细控件清单。
主 Agent 先从当前最新截图确认已知 State 与当前可见组件，再复制目录中的 ref。
目录不表示当前可见，不新增模型输出字段、持久字段或召回模型调用；空 Element ref 仍走既有批量审核。

待结算详情和最近回执保留真实 `point_1000`，最近回执也明确实际动作kind；pending scroll附原请求amount。
这些数值只用于核对历史投递和有依据地纠正点位，不可直接作为当前坐标。原先仅含动作前区块的
`allowed_function_region_refs` 更名为 `before_region_refs`，不再暗示它是整个前后观察允许引用的全集。

`Semantic Exploration Focus` 是全局图的 scheduler/context projection，不是第二张图，也不
持久化新的任务类型。它可表达 `Clock -> Alarm -> Alarm Editor -> Repeat selector` 这样的
嵌套语义范围，但所有 Page、Region、Operation、Attempt、Transition 和证据仍只有一份。
第一版从当前内部 Task 和 Region memory 即时投影；Focus completion 由账本终态和 gap 推导，
不由模型报告。

Luna 仍只提交当前截图中的 `owner_ref`。当前页面、任务卡和动作回执只显示 Region-owned
CanonicalOperation；框架执行时才把它解析到当前 Variant 的本地 Operation并保存证据。若当前 owner
属于另一个 CanonicalOperation，回执才显示为另一功能；同一稳定 Operation 的不同本地 binding不再被误报为偏离焦点。

重启时的精确任务卡只要求确认目标或路线起点的可交互 Region 和操作；主 Prompt明确允许不完整
page_report，其他内容未检查时保留 survey_complete=false。取得目标绑定或已验证路线后继续原任务，不要求全屏重新调查。
恢复定位时会先审核该 State 已积累的待审区块，使其有机会接上既有共享路线。恢复解除后清空当前 Task 的
旧策略，防止正常操作卡仍回显“只确认、不执行”的恢复计划；原始模型回复和动作证据保留。
尚未找到区块时允许先做空 owner 的非滚动恢复；恢复结果先正常结算，不必为回填结果补完整清单。
已知 State 的补充事实不再触发文字相似度重判，因而不再发送“候选旧 State 已登记内容”的额外上下文。

## 页面与 Region memory

`page_report` 的Region/Element都提交ref字段。已知State/Variant中的对象复制当前页面卡稳定ref，真正新候选
填空。新Page/State可引用已有region_ref作为复用提示，但来源element_ref必须为空；runtime仍通过Region Reviewer
确认Region延续并为新Variant分配本地Element。已知Variant里的空element_ref进入一次批量Element审核，
模型不能自行分配ID或引用其他Variant的el。每个 Region 除 `summary` 外还必须给一段
简短 `memory`，概括：区块能做什么、当前已见状态、参数值域、已选代表、是否显露不同结构，
以及仍缺的事实。memory 只帮助后续探索和指令生成理解界面，不授权新动作，也不替代
Capability 的前置条件、effect、对象 binding 或成功谓词。

所有图标和文字控件都结合整屏上下文判断功能对象、当前职责和直接效果；不能按操作名称设置共享例外，
也不能把其他 Page/Variant 的对象复制过来。Region Reviewer 从完整截图提出候选，Operation Reviewer明确确认后才共享。
列表成员先区分独立功能入口、重复数据实例和参数选项：功能入口逐项登记，数据实例才选代表，参数值只写参数信息。

参数值不是独立 Operation。选择器入口只登记一个 Operation；普通同质值只选一个代表，
`Custom...` 等明显不同分支可另选一个。框架拒绝同一 Variant 中同一
`owner + action + direction` 的多个 Operation，值域必须进入 Region memory。
一个代表无法判断两个控件间的选择关系时，主 Agent可在动作前用 `representative_probe` 引用第一个代表的
稳定 Operation、全部同类 Element owner和两个代表，并立即执行第一个代表；成员不要求预先共享 canonical
身份，框架只组合任务和覆盖证据。普通轮填 null。第二个代表完成后用
`representative_same_kind` 报告同类与否，并在 `function_info`写下实际机制。未点击成员只能记为
代表覆盖，不能写成真实完成。

v6 的每条 Operation 还必须输出 `parameter_status` 与 `parameter_summary`。`none/observed`
可直接来自当前截图；`unknown` 只表达仍缺证据，不自动授权动作。安全选择器使用
`handling=explore + unknown`，危险或不应执行的入口保持 `record`，参数未知则如实留下 gap。

## 动作请求

模型动作只有 GUI primitive 和 owner：

```json
{
  "kind": "click",
  "owner_ref": "el12",
  "target": "Alarms tab",
  "point_1000": [480, 60],
  "text": null,
  "direction": null,
  "amount": null
}
```

执行已登记 ElementOperation 时 `owner_ref=element_ref`；所有 Region scroll，包括调查和路线滚动，都使用 `region_ref`。
首次不完整清单可先 action=null 取得 ref；非滚动恢复、Back 和 Wait 才使用空 owner。框架在动作执行前，以
`current State -> source Variant -> owner/action/direction` 唯一解析本地 Operation，并把
`operation_ref` 和内部 purpose 写入 ActionAttempt。候选不存在或不唯一时 fail closed。
待结算卡的 `owner_ref` 为空时，模型的 completed owner 数组也必须为空；即使误填，runtime 会丢弃该项。
新 scroll 不能进入空 owner 路径；Luna必须用 region_actions 回填实际 Region 和方向的完成情况。

所有有视觉落点的动作仍使用最新截图的 `point_1000`；只有 Back/Wait 可为空。前景菜单或
模态存在时，背景 owner 即使未被几何遮挡也不可执行。

临时干扰不新增持久类型：无关弹出干扰先清理，不因遮挡较小或其他区域可交互而跳过；
清理轮 page_report=null，暂不填写区块说明，已能确认的上一动作仍正常结算。缺少可见关闭入口时可以先悬停显露，
不能猜坐标；处理后重新截图确认，再继续清点。目标应用主动打开、正在探索的前景不是待清理干扰。
清理优先级高于任务卡、已清点标记和“目标入口可见”；系统前景为 target 不证明全部通知/浮层属于目标应用。
wait 只在截图明确显示加载、倒计时、扫描或异步进度时使用。接管输入的干扰依次考虑前景安全关闭/
确认、界面明确手势和平台 Back。外部登录、添加账号、账号选择和身份授权入口只登记为 `defer`，
绝不执行；阻断核心功能时 Operation reason 写 `external_auth_required`，形成可读 gap，而不是点击登录。

主 Agent 在已有 reason 中逐个预测当前全部应用区块的存留，未变也不省略；另说预计新增的区块名称。
只用区块名称或已有 ref，不预测控件/参数，不提前分配新编号；系统通知等外部干扰单独说明。
runtime 在真实投递动作时将完整 reason 存为 ActionAttempt.agent_reason，并随同一次 pending 的前后截图回传。
下一轮在已有 previous_action.reason 中逐个核对；实际截图优先，预测不符不自动代表点错或失败，预测不写成图事实。
模型输出 Schema 不变，不增加专门预测调用。模型是否确实覆盖全部区块仍属语义观察，不宣称确定性完整性保证。

动态状态栏的 system scope 是应用归属权威信号。`target` 表示顶部 Activity/窗口已经由框架确认属于目标
应用；系统风格全屏教学、screensaver、onboarding 或权限说明不能仅凭外观改报 `external_app`，模型仍须
填写 `target_app` 并处理当前 active surface。`external` 才进入非图恢复。该规则不把外部包白名单化，
也不允许模型用截图覆盖系统包/窗口证据。

Android 参数代表输入优先使用短 ASCII 值。当前 AndroidWorld 输入通道会把非 ASCII 词归一化为空或
丢失字符，因此中文说明文字不能直接当作 action.text。设备 delivery error 后，模型下一轮只能根据 fresh
frame 改用兼容代表值或保留 gap，不能把已出现的 ASCII 前缀当作完整输入。

## pending 回填

模型必须精确回填 `attempt_ref`，但只报告已完成的 owner 动作和功能信息：

```json
{
  "attempt_ref": "a17",
  "element_actions": [
    {"element_ref": "el12", "action": "click", "completed": true}
  ],
  "region_actions": [],
  "function_info": [
    {"region_ref": "r8", "memory": "Alarm Editor 可设置重复、铃声和持续时间。"}
  ],
  "reason": "Alarms 页面已经出现。"
}
```

框架只接受当前 pending Attempt；`completed=true` 必须与实际 primitive 一致、能在 before
Variant 唯一映射，并由 after 截图证明该 Operation 的直接可见效果。动作已投递、鼠标落在附近或只出现
tooltip 时必须填 false。错误落点只可完成实际生效的已登记 owner，不会完成原派发 Operation。
模型必须从 pending 详情复制动作 ref，不能把控件名称、结果区名称或 after 新对象名称当成 ref。
`function_info` 可引用 pending 卡列出的 source Region，或 after 图中重新可见的已知 Region；真正新出现
Region 的 memory 跟随当前 `page_report` 登记。任意不在 before/after 可见 State 的 Region继续拒绝。
当 pending 卡标记 `parameter_confirmation_required=true` 时，`parameter_info` 必须为
`none/observed` 与非空 summary，但仅限 owner 动作 `completed=true`；它由框架绑定 completed owner，
不含 Operation ID。动作未生效时填 `completed=false, parameter_info=null`，参数保持 `unknown`，
Attempt 按 no-effect/retry 结算后再 fresh-frame 重定位。无需参数确认时也为 `null`。
若模型误在全部 completed=false 时附带参数，runtime 会丢弃这项未绑定信息并继续 no-effect
结算，不要求 Luna反复修改同一 pending 报告。
映射成功后框架自动把本地 Operation 标为 verified、关闭其派生 Task，并复用现有
CanonicalOperation 去重合同。一次动作可顺手完成另一个 owner；Attempt/History 仍归当前
Focus Task，实际 owner 由 `action.operation_ref` 保存并关闭它自己的 Operation Task，原 Focus
保持 active。这样当前 Focus 的最近动作、重复检测和尝试预算不会丢失绕行动作。

当前任务的精确 binding不可见时，Luna只执行 `region_route.steps[0]` 在最新截图中的当前 owner。
路线的 evidence Variant只证明关系，不能提供旧坐标；动作后必须核对预期 Region是否出现，再由框架
重新规划。相同 Region中若 canonical effect因 Variant冲突，路线状态为 ambiguous，不允许用同形按钮替代。
当前 State 只有已经结束的同 canonical binding 时，不把它投影成可执行当前 binding；任务卡继续给出
准确来源 State。这样目标页面中已经选中的导航按钮不会被再次点击并误记为 no-effect failure。
当前没有可执行 binding 时，任务卡的 `element_ref` 为空，不泄露其他 Variant 的旧 Element 编号；若目标控件
确实出现在最新截图但当前 Variant 漏报，Luna用增量 `page_report` 提交空 `element_ref` 并复制任务卡的稳定
`operation_ref=co...`，由框架建立本地 binding。

Region identity、Operation identity 和 Operation result 仍分别审核。Region memory 和模型理由
都不能更改 owner/action 真值，也不能把遮挡背景、外部应用或未登记候选写成已验证功能。
Region Reviewer 的候选侧同时携带 Region 的完整 canonical Operation 目录，当前侧列本批实际观察过的
ElementOperation/RegionOperation。普通长页逐帧登记、清点结束后批量审核；Region 和 Operation 的 images
明确标注相应保存帧，不要求它们同时出现在最新截图。来源动作也按各区块首次报告的真实 Attempt 对应，不共用最后一次滚动。目录项标注是否在候选截图 Variant 中可见；不可见项只能
提出 identity 候选，不能复用结果。`shared_operations` 只是候选；仅当本批存在候选时，框架用同一组整屏截图增加一次
批量 Operation Reviewer 调用，并在每对中标注 current_images / known_image。多个复用 Region 共用这一批，
不按 Region 或按钮分别调用；返回已知
Page/State 时读取持久 binding，不重复审核。Operation Reviewer把 element/target/result视为待核对 hint，
结合每张完整截图独立判断same/different/uncertain，只有same才允许共享身份或结果。

输入含 `合同纠正卡` 时，修正点名字段，并同步修正相关 screen/page_report/previous_action.region_effects；action=null。真实动作和 attempt_ref 不可改写，不冻结尚未接受的位置或清单判断。
主 Agent、Element/Region/Operation Reviewer 共用三轮失败预算（首次失败加两次纠正）。错误直接交给能修改它的角色；措辞、排序、任务切换和刷新截图不清零。报告通过检查才结束纠正。耗尽后保留候选、截图和 gap，不再审核同页冲突；位置可信时可沿已有绑定探索其他内容，否则 partial 停止。详见 [报告纠正流程](report_correction_flow.md)。

## 状态栏

状态栏只列当前位置、系统前景、当前探索焦点、pending Attempt、当前焦点尝试数、最新纠正和
拒绝预算。模型切换 Focus 后仍保留未解决的报告纠正；普通旧任务动作反馈清理。上一动作无效果时，状态栏要求改变
可靠点位或做空 owner 的恢复；确定性上限由框架产生 failed gap，不要求模型提交任务终态。
恢复阶段重复清单没有新增绑定或状态时，状态栏的“必须修正”直接带本轮 Region ref，并说明仍无目标绑定或
已验证路线。复用原连续动作拒绝预算；只改描述不清零，真实清单进展或首次解除恢复许可才清零。

## 2026-09-08 反馈检查

contracts 的必填文本/非法枚举和数组项错误带字段位置；status 与格式重答在 correction 存在时不显示旧 strategy 为当前思路，账本历史保留。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。

2026-09-11：可选defer_partition_review通过“分区复核策略”上下文说明允许先记录真实容器和不完整清单，下一轮使用当前合法owner继续；分区待复核不代表完成，不能复制背景/历史控件或依名称合并。默认模式输入不变，无新增模型字段或角色。
