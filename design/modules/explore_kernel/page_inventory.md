# 页面清点

2026-09-19 Android Settings实机暴露的合同不一致：普通纵向scroll的record规则现由HANDLING_GUIDANCE向主Agent和Reviewer共同提供；未见内容仍由survey_complete=false与原survey推进，不将普通滚动强改explore。Reviewer operation_checks仍仅接收Element操作，误填Region操作时精确反馈operation_checks[i].path给Reviewer；不扩展隔离合同或替作者修改清单。54项分区/编辑邻接验证通过；段03首次投递前冻结该修复，旧段02不追改。

2026-09-19 因果边界：用户再次明确，非应用交互触发的系统通知不属于应用Region变化，不能成为业务采集路径。主Prompt明确禁止把悬停/清理这种通知归给后方应用Region或伪造空引用；只在恢复reason留痕，未新增结果字段或放宽unknown门禁。段01 Settings a7的原生success含系统通知误归因，单独排除可信应用效果，原始账本保留。

2026-09-19 原断点补齐：整份候选（含全部edits）先复用`inventory.validate_report_structure`检查同物理owner/action/direction重复，再进入视觉审核；`PAGE_REPORT_STRUCTURE`准确指向operations数组，并沿同帧候选修单。不同动作或单动作参数不误拆。独立遗漏遇到无owner Back时，仅在真实route/recover Attempt有前后帧、已知落点、原审核三项确认且消失Region匹配来源/落点/当前清单时进入原结算；不伪造completed owner，不放宽最终Region效果校验。其余无绑定结果仍阻断。Reviewer的controls_confirmed评价已报告控件准确性，完整性由遗漏证明单独表达；false与空blocking的矛盾回原Reviewer，不自动改true。原Files 0013+0016+0017保存证据已原生结算并保留遗漏，非新实机成功。

2026-09-19：分区Reviewer合同只修复一次，仍非法的理由作为未确认线索交作者原edits路径，保留三次共享失败预算；没有候选或证据变化不重新调用Reviewer。普通合法负面意见仍直接交作者，局部准入证明要求不变。

2026-09-19：跨状态动作落地的独立遗漏准入允许真实来源Attempt已完成、来源State/Operation绑定、同Page的新`new_state`清单尚未发布`state_ref`的情况；必须同时有非空页面和状态描述及`previous_action.region_effects`中的动作因果变化。没有来源绑定、动作完成或落地效果证据仍按结果依赖阻断；不接受模型伪造State ID。

2026-09-19：Reviewer合同错误反馈具体指向缺失字段、协议值和类型，责任归Reviewer，不要求主Agent迎合非法审核。独立遗漏不再因存在pending动作一刀切拒绝：程序映射当前已报告动作路径、父Region和依赖，确认与动作/结果无关才局部结算；无法映射或存在依赖仍阻断。离线验证已覆盖无关Region pending正例和同Region依赖反例。

2026-09-18：分区审核协议`partition_qualification.v3`保留原遗漏局部框/依赖校验；输入新增Element及Region操作的reason/handling、运行配置的权威scope和相关声明限制，不恢复bbox/点击坐标/像素评分。reason是待核对解释，scope不是模型自述。explore=待调查义务，record=观察记录而非完成/禁用，defer=当前前提/资格/本批范围不足；风险类仍只记录。eligible表示当前前提及scope内的资格，不能覆盖框架范围/绑定/暂缓门禁。缓存作用域含协议及scope，候选key含reason；新范围不携带旧审核结论。合法视觉拒绝仍交主Agent，审核格式/互斥证据错误在原共享三轮预算内交回Reviewer，不让主Agent迎合非法输出。

2026-09-18：独立遗漏的整屏`box_1000`拒绝现在反馈准确的`omission_checks[i].box_1000`及局部证据缺失原因，不再只转述Reviewer声称可隔离的理由。门禁、原different、候选与纠错次数不变；主Agent仍须据图补清单，程序不伪造局部框。VLC原保存回复在新代码中仍被拒绝；这只证明反馈接线，未证明模型已生成合格局部遗漏证据。

2026-09-18 V2：原分区角色使用`partition_qualification.v2`，另列`omission_checks`，与handling争议分开。仅接纳当前截图摘要、可信Region路径、可见缺项范围、逐操作独立性/依赖引用和可靠已报告退出操作齐全的独立遗漏；有受影响操作、身份/来源/模态冲突、无可靠退出或待结算结果时阻断。原different及候选不变，缺项不生成Operation或坐标。沿`inventory_report_deferred`事件留存缺口及来源，survey暂挂；可信操作可继续。原v1不同意回复不具备新准入证据，缓存按v2隔离。后续完整原审核通过才清除对应清点缺口。

已知完整State恢复仍复用既有目录，但允许精确引用当前Element及co、从未尝试/成功/受限且仅record的操作，凭新的适用依据更新为explore并创建原Task。不是全量record升级；跨来源旧owner、失败/未知动作和资格隔离不因此重开。

2026-09-18：`partition_qualification.v1`沿原分区角色返回前景/分区/控件对应确认、blocking_issues及逐操作path/action/handling资格证据。different仅在剩余争议全为独立操作资格、路径有效且影响范围只含该操作时局部准入；遗漏、身份/归属/落点及pending结果依赖仍阻断。原候选与审核完整保存在事件；隔离只是框架派生defer，不改原模型JSON。旧different缺新证据仍拒绝，缓存含协议、候选、帧、Attempt和缺口上下文。

隔离入账使用现有本地Operation.status与Task、`operation_qualification_isolated`事件，关联State/Variant/Region/canonical、原候选与图证据。普通清单或旧same不能自动解除；显式当前owner/co和新协议eligible=true依据通过后，用`operation_qualification_resolved`关闭资格缺口，实际成功仍须新Attempt原生结算。限制按本地绑定，不删除canonical或成功历史。不更改ledger顶层schema。

2026-09-17后续验证：同一候选由主Agent修正6处视图描述后原审核same；独立测试Attempt可原生入账并结算一次，原a207不改。新VLC短批另有一次真实“反馈→remove后台栏→审核/身份通过→正式结算→选下一待办”，9HTTP/1GUI；尚未验证连续2–3目标全部完成。详见本月记录及view_description_finish_20260917_01证据。

2026-09-17：原分区审核在同一Attempt和图像哈希下可接收最多原纠错上限数量的历史候选/意见，以及本轮实际编辑before/after。审核需复查已修、仍缺与不确定问题，并继续全图检查；未提及不由程序判为已解决。历史索引不作为当前修改路径，换图/Attempt及恢复账本时清空；缓存包含当前候选与编辑事实，重复原样请求仍复用判定。无新角色、模型Schema或持久问题库。当前独立保存帧已验证旧遗漏补齐与原项保留，但最终审核对视图名称仍有拒绝，未进入正式结算/实机。

2026-09-10：主Agent、预审和State核验共用ACTIVE_SURFACE_GUIDANCE，避免预审误要求登记模态背景或系统栏。Schema与预审共用CONTROL_ACTION_GUIDANCE：能力目录不等于当前执行，前景禁用控件保留动作并defer；后台不适用此保留规则。预审保留handling，文字/数值样式本身不证明不可交互，未实测点击语义不能被称为已证实的错误。

2026-09-10：新增入账前视觉分区预审（partition_review.py）。报告含新Region或新Element时，内置模型review_partition使用当前完整图和候选清单，检查明确的前景、父子、同质成员拆分、静态内容和物理控件集合错误。same才继续原流程，different/uncertain通过已有page_report纠正反馈交回主Agent，旧图不先增加State/Region。只要求最小必要修正，不强制唯一分区数，不进行GUI或跨图身份合并。纯已知Region引用确认、只有已有控件观察的更新不额外预审；同图/同提案的审核判定在runtime缓存，不重复付费。无此接口的非模型客户端不记视觉通过，内置模型提供该接口。

这一步增加模型调用：首次有效提案通常1次预审，纠正后提案变化需重新审；与已有State复用核验、Region配对、Operation配对分别计数。原始三份错例（重复数据卡片升格Region、多个导航按钮合成Element、背景Help混入）在保存帧重放均被明确指出，不代表全部页面均通过；完整修正流程另验。

2026-09-10：通用分区指引补齐静态内容归Region summary、标签优先/无标签用稳定功能对象、数据值和展开态不作Region身份、普通展开保留原区与独立编辑上下文区分、局部纠正保留无关边界。内联独立结果区归可见来源容器；接管输入的弹层仍遵守原前景边界。新Element空动作拒收条件不变，反馈明确可移除误报的静态Element而不编造动作。没有应用名/按钮/坐标特例，没有新增模型角色或固定调用。83项聚焦离线检查通过；11张Settings/Files/Clock保存帧已选定并核对来源，初次启动被自动审批拦截；用户随后明确授权所选及新增截图外发，模型验证已运行，结果与失败分批保留，详见本月日志与general_partition_20260910系列证据。不能据离线检查宣称跨应用准确率。

2026-09-10：已知Element报告新名称时，保留其ID和原名称，在observations记录reported_name及State/截图；即使没有新的observation文字也保存名称变化。Region实例改称记录region_name_observed。它们是带来源的模型称呼，不等于OCR原文或身份确认；操作语义/结果不会因此改变，检索只在已有共享身份内利用别名。

survey_complete只衡量当前可交互前景本身的结构/内容调查；未展开子菜单或其他页面由独立explore待办负责，不阻止当前清点完成。当前菜单自身有截断/未见选项时仍继续调查。这一局部清点标志不代表全应用功能已遍历完；主Prompt、字段说明及survey任务卡保持同一含义。

完整清点可与已确认安全的无owner/operation_ref Back同轮提交；它不依赖本轮新分配的控件编号。记录/审核仍先完成，失败时不会执行返回；Back真实结果下一轮核验。新控件点击与其他完整清单动作门禁保留，纠正轮仍action=null。

已清点State正常返回且没有新增事实时不重报清单。主Agent以最新图确认State后复用既有任务来源引用；缺本轮引用时可先仅结算，再读取该State持久目录，不用重报清单索取编号。待结算卡中的位置/路线属于动作前，不能误作动作后的导航要求。不同State的旧owner仍由原绑定检查拒绝；同轮首次清点与点击的限制保留，未清点State仍需调查。

父区未知/越界和循环错误在Element审核前用`PAGE_REPORT_INVALID`反馈，字段指向实际参与错误的`page_report.regions[i].parent_ref`，附有效引用形式；不再把父区错误笼统归到elements，也不自动修改语义分组。父子关系与事务拒绝规则未放宽。

operations登记控件支持的动作能力，不是本轮执行计划。已选中的独立控件仍保留支持的动作并用record，不为验证选中状态重复点击；空动作的新Element仍拒收。主Prompt、字段说明和对应纠正提示统一这一点，容器仍归Region，不按控件文字自动补动作。

2026-09-09：新Element必须提供至少一种具体动作，不再接纳无动作的新控件占位；容器/组合功能归Region。已知Element可只补observation而不重复operations，历史账本仍可读取。范围卡不再把恢复误导为必须先切换开放Task，当前record控件可直接用于恢复，缺绑定先补。

2026-09-09：删除survey必须完成后才能调查已登记控件的旧门禁。清单首次取得ref后，可用当前合法owner继续点击等调查；动作仍逐次结算，不提前完成survey。同轮清单的候选点击仍留到下一轮。有限参数列表继续观察未见选项，同质数据可以按功能结构收束。

2026-09-09：报告支持Region.parent_ref：整数引用本报告0起始父行，字符串引用当前State的父Region，
null保留旧归属/新建根节点，空字符串明确设为根。持久化为RegionOccurrence.parent_occurrence_id，
不把全局共享Region锁定到单一父节点。未知/越界父引用、自环、循环及跨State父引用均拒绝，原账本不变。
父子链接在Element付费审核前预检；身份合并后再次检查，实例合并同步重指向孩子。
Element.observation写本帧取值、选中/可用性或不确定性，按State、截图和记录顺序保存；参数定义仍在Operation。
当前支持新增子区及新State中的层级重绑定；不会静默把旧Region的全部控件和任务搬到新子区。

2026-09-09：同Page新State与其清单已触发旧survey被取代时，后续来源检查不再回滚这一接替。
清理临时前景后可调查真实新状态，不反复恢复已经消失的旧提示；旧State/图片与cancelled原因保留。

2026-09-09：同 owner/action 重复与不存在的 operation_ref 在 Element Reviewer 前按原结构规则预检。
反馈列明冲突目标，区分参数值与独立落点；显式 owner 的错误 co 给出其合法绑定。坏清单仍不入库。
若页面、Region 与动作回执都可独立确认，runtime 可只结算动作、保留待补 gap；未知落点保持原保护。

2026-09-07：operation_ref 拒绝反馈列出实际所属 Region、scope/action/direction 的期望与收到值，或本地绑定的稳定 co；明确新操作留空、不同控件先纠正 Element，禁止为迁就旧编号改变界面事实。校验条件未放宽。

## 问题

框架必须知道一个页面状态中有哪些稳定区块，以及每个区块有哪些对用户命令有意义的操作，才能谈覆盖率。
清点不等于逐个点击；它只建立完整目录。

## 合同

2026-09-09：同一已确认owner的none/observed参数分类可由新报告修正，保存parameter_observation_revised
事件中的旧标签/摘要与新截图；不因这两个已知标签的差异阻塞遍历，也不重写Operation执行结果。
unknown到已知仍是信息进展；none/observed来回改标在runtime进展比较中归一为known，不刷新空转预算。
未穷尽范围、步长或所有值不等于unknown；形式或代表值可见时记录observed，未观察细节在摘要说明。

2026-09-09：`_validate_report_region_refs()` 在 Element付费审核和清单写账前检查当前 State归属；
跨State引用会得到精确 `page_report.regions[i].region_ref` 错误、该State可用ref/名称及空Element候选用法。
不让结构上已非法的整份清单先做部分语义审核。新State的旧Region提示仍由既有准备步骤先转换为候选，规则未改。

同一清单的不同Element条目不得共用非空element_ref；同一控件的操作合在一个Element内，多个新候选仍可留空。
该检查与Element审核共用inventory.py::_validate_unique_element_refs，失败时保留原账本。

首次到达新 State 时，主 Agent 先提交首帧 `page_report`，覆盖当前 active surface 中全部可见稳定结构。
重启定位只需先确认目标或路线起点 Region 和当前操作；可以提交不完整清单，取得当前 binding 后继续原任务，
其余未清点内容仍为待办，不必为了恢复原任务先重新完整调查整屏。
active surface 是当前最前景且能直接接收用户交互的目标应用表面；菜单、弹层、对话框、抽屉、
选择器或底部面板接管输入时，只清点该表面，背景只作为截图上下文，不进入当前 State 的
Region/Element/Operation 目录，也不生成本地 binding。没有表面接管输入时，仍可直接交互的持久
导航栏、工具栏、侧栏和主要内容继续登记。该边界按输入层级判断，不要求背景变暗，也不按遮挡面积判断。
`screen` 始终描述最新截图。同一调查的后续滚动帧改为增量合并：只补报新发现或发生变化的 Region、Element 和
Operation；已登记但本轮离屏的事实不必复制，省略也不表示删除。真实动作显露菜单、弹层、面板、展开区或选择模式时，
即使 Page 不变也先登记为新 State，再从该 State 的首帧完整清点。操作系统栏、Dock、任务栏和其他应用不登记。

Region 是共享局部上下文和变化边界的功能组件；Element 是 Region 中有明确交互落点的控件。Region 边界由功能对象、稳定应用槽和
共同显示/隐藏、替换、滚动、展开或聚焦的变化范围决定，不由面积、边框或控件数量决定。一个页面只有一个按钮时，该按钮是单个
Element，它所属的主要功能表面仍是完整 Region。相反，列表中无独立边界的某个重复成员通常只是列表 Region 的 Element，不单独抬升为平级
Region。toast、tooltip、一次性提示和装饰不登记。Region 名称描述跨 Variant 稳定的功能槽，不使用展开态、选中态或当前数据值。
共同编辑同一对象的表单可作为父Region，其不同功能组可形成子Region；每个控件只归一个直接区块。
视觉分栏或标题本身不足以决定层级，应结合功能对象及显隐、替换、滚动和交互范围；不固定套用三段布局。
列表代表项的普通展开若只增加被动信息、同质字段或原有操作，仍属于列表 Region 的 Variant；若展开后显露一组
共同出现/消失、服务于该对象并可独立完成用户任务的完整编辑或详情上下文，即使它内联显示在列表成员内部，也必须
登记为独立结果 Region。触发展开的 Element 继续属于来源列表 Region，两者通过真实 ActionAttempt/Transition 和
Region Reviewer 的 `trigger_or_result` 因果关系连接，不能把新结果 Region 的内部 Operation 挂回来源列表。
内容截断或滚动条只说明允许有依据的调查，不要求穷举到底。`survey_complete`表示功能结构已清点；
同质数据列表的结构、代表控件和操作已明确时即可完成；有限参数列表仍有未见选项时继续观察，
在coverage_note记录实际范围。确认选项不要求逐个应用参数值。
仍有异质功能或未知结构时继续调查。首份不完整清单允许action=null取得引用，随后用已登记且可见的Region滚动；
不同功能入口必须逐项登记，不能因列表样式相同而省略。无新增控件不阻止提交survey_complete来收束已完成的调查。
已有清单后，重复提交相同不完整清单且没有调查或恢复动作会被拒绝。确认覆盖充分时提交 `survey_complete=true` 和
`action=null`，不等待框架替 Luna判断。
每次清单接受后，框架记录本帧实际报告的 Region/Operation 与截图引用。普通调查的新 Region 累计到清点完成后
一起做身份复核，包括更早帧中已滚出屏幕的区块；只补元素不会重复触发 Region 审核。中断后累计记录随原账本恢复。
滚动 `direction` 描述希望查看的内容方向：`down` 查看视口下方内容，`up` 查看上方内容，与触摸手势方向相反。
同一调查在同一 Region 连续三次向同一方向滚动都没有可见效果时，runtime 拒绝第 4 次同方向动作，并要求换方向、换区域或完成清点；
改变坐标但保持同一无效方向不算新调查策略。
单次滚动的结算与继续调查理由分开：before/after 没有内容位移、新内容或滚动条变化时，本次 Attempt
必须为 `no_effect`，不能因为仍有截断而记 success；截断或延伸证据仍可支持换可靠落点或幅度做 bounded retry。
提交完整清单的同一轮不执行功能操作；框架写账并在下一轮派发精确 Operation。
若主 Agent 仍夹带非空 `owner_ref` 的功能动作，清单保留，动作被拒绝并收到具体纠正。
新控件先取得owner绑定，下一轮即可调查未知项；尚未覆盖的内容继续保留survey缺口。
清点完成只表示目录覆盖充分，不要求先执行全部explore；调查动作成功也不自动完成清点。
状态栏已经派发具体 Operation 且当前结构未变时不重复提交 `page_report`；真实动作落地新 State 后再提交新清单。
已知 State 的增量清单不再因为当前派发 Operation 而提前丢弃；有效的新区块、控件、操作和参数事实正常进入
既有审核与登记。没有动作或结算的重复清单，按已有 Page/State、Region/Variant、Element/Operation 引用、
绑定、动作/方向、操作和参数状态及清点完成标记检查进展；恢复阶段同样使用这条门禁。
名称、summary、memory、target、reason、result、参数说明与截图引用的改写不会单独刷新进展资格，文字更新仍保存。
代码不判断两段自然语言是否语义相同；参数仍为 observed 时只改写值域说明，也不单独重置无进展预算。
新增绑定、unknown 到 observed 等参数状态变化或首次解除恢复许可正常接受，并清除原连续拒绝次数。
恢复尚未找到目标绑定或已验证路线时，反馈点名本轮重复的 Region ref，要求实际导航/恢复或补充其他入口。
沿用现有动作拒绝预算；清单经过临时账本提交后，耗尽处理使用正式账本的 Task 对象，避免只发 failed 事件却留下 active Task。
清单同轮不执行功能动作的规则不变。
加载或异步结果使同一 Page 的功能结构自然变化时，也可登记新 State 并提交该状态的完整清单；即使清点刚结束并已切换任务也适用。
此时已不可见的旧状态清点任务以 `cancelled` 保留，不再阻塞新状态的覆盖结算。
只有位置模块本轮确实新建了另一个 State 才会发生该替代；对当前已知 State 重复报告清单不会把它误记为自然状态变化，
也不会取消后重新打开同一调查任务。
一份 `survey_complete=true` 的完整清单被接受后立即关闭当前 State 的清点任务；同一 Agent、同一截图不再重复确认。
后续真实动作或异步加载显露新结构时，再按新 State 补清单。已完成 State 若因新的可见证据重报，仍只能补充遗漏事实，
不能在尚未执行时静默降级已有 Operation，也不能把 `survey_complete` 改回 false 重新开启调查。框架将这类报告按增量事实
合并，保持原调查任务 `done` 并记录 `survey_completion_preserved` 事件。
真实动作待结算时，新增 Region/Element/Operation 不再触发额外 State 重判；动作照常结算，新事实由既有审核登记。
主 Agent仍应根据当前前景结构决定是否新建 State，框架不根据文字差异替它作该判断。
单个页面调查累计十二次真实观察动作仍未完成时，框架如实把该调查记为 `failed` 并继续其他任务；已经保存的区块、
截图和动作证据保留。该终态不表示页面已经清点完整，也不把无效观察算作覆盖。

主 Agent 不创造结构编号。真正的新Region/Element候选使用空`region_ref/element_ref`；已知State/Variant中的
对象必须复制当前页面卡已有ref。新Page/State若认为已有Region延续，可携带其region_ref作为复用提示；runtime
不会直接接受，而是清空为临时Region候选并交给既有Region Reviewer，来源element_ref同时清空。
明确引用的旧 Region 提示随候选保存，进入批量审核时不受文字分数或普通 shortlist 数量限制。
返回已知 State 时，可从 pending 输入的历史 Region ref/名称目录取回引用，再按最新截图确认可见性。
仍提交空 Region ref 而产生新候选时，既有 Reviewer 必带该 State 原有 Region；只有其明确确认完整组件
相同才复用并收束同 State 重复 occurrence，不按名称或截图相似度自动决定身份。
普通不完整清单不因这类提示立即加一次审核；重启定位提前批量处理当前 State 已积累的全部待审区块，
使用既有观察记录，不让当轮只重报一个局部区块阻塞其他区块的共享身份和路线。
实际落账时，非空region_ref必须属于当前State occurrence，非空
element_ref必须属于该Region当前Variant，跨State/Variant引用fail closed。
已知Variant中的空element_ref不直接创建：框架把本批候选与该Variant已有Element连同当前完整截图交给一次
Element Reviewer。改名、分组方式变化或重复报告时复用旧el；真正独立的新交互落点才分配新el；证据不足
保持unresolved。多个Region候选合并为同一批，不按按钮逐次调用。
每条 Operation 同时带 `operation_ref`：当前卡片已有操作复制稳定 `co`；已知 State 当前 Variant 漏掉焦点
Element 时，Element ref 留空而 Operation 复制任务卡 `co`，runtime 校验该 `co` 属于当前 Region 且
scope/action/direction 一致后建立本地 binding。真正新功能和新 Page/State 首帧的 operation ref 留空。
`elements[].operations` 保存必须从具体 Element 发起的 `click/input_text/hover/long_press/double_click/right_click`；
`region_operations` 保存直接作用于 Region 整体、没有唯一离散控件落点的 `scroll`，并强制携带 `up/down/left/right`。
普通纵向列表的 `up/down` scroll 先以 `recorded` 能力写账；实际调查滚动绑定当前 Region 和方向，
Luna用 `region_actions` 报告真实完成后可验证该 RegionOperation，不在清点完成后重复派发。横向翻卡/分页若会改变可见功能结构，仍可作为
`explore` RegionOperation 单独调度；`defer` 的当前阻挡语义也保留。
若模型在普通纵向 Region scroll 上写出 `handling=survey`，解析器将其归一为 `record`；该归一只兼容
旧保存输入，不表示当前模型动作还输出 purpose。left/right 和其他非法 handling 仍拒绝。
登记或真实执行 survey scroll 都必须由最新截图中的内容截断、滚动条、连续内容延伸或部分相邻内容支持；完整静态视图
不登记猜测性的隐藏 scroll，并在首帧完成清点。`survey_complete=true` 的报告同轮不带动作；首次不完整报告先分配 ref，
后续未完成报告可带已登记 Region owner 的调查滚动或非滚动恢复动作。
适配器对完整清点报告上残留的同轮动作做安全归零，原始模型输出仍保存在调试记录中；清单事实继续正常入账，动作不执行。
已知 Operation 的 `none/observed` 与本轮报告冲突时，inventory保持事务原子并返回具体
Region/Element/Operation、旧状态/证据和新报告，不让异常退出主循环。同一 pending 的位置、动作结果和
已提交清单属于一次临时处理：清单不合法时不发布本轮位置或 Operation 完成，真实动作及截图仍保存。
沿原两轮 pending 纠正预算修 page_report，保留原位置与动作报告；没有 pending 的清单错误只返回具体
问题并保持原图。合法的 survey_complete=false 清单照常接受，不要求先完成全部探索。
冲突仍不能靠文字相似或新措辞自动覆盖。
ElementOperation 不复制到 `region_operations`；Region 的整体能力由框架聚合其子 ElementOperation 和 RegionOperation。跨 Page/State 的共享 Region 只有经过区块身份调用明确配对后，
才让两个本地 Operation 指向同一个 Region 级 `CanonicalOperation`；不会因为另一页面存在同名控件就自动共享身份或结果。
动作类型直接使用运行时可执行值（如 `click`、`input_text`），功能语义放在控件名中：

- `explore`：有待调查/验证的义务，不是立即执行授权；
- `record`：保存观察，语义清楚或风险规范仅允许记录，不算已验证，也不推导物理禁用；
- `defer`：仍欠验证，但当前条件、资格或本批范围不满足；可见启用也可因范围暂缓，说明具体原因。

2026-09-09：handling 是后续探索决策，不是当前这轮是否执行。安全的未知功能页、菜单、表单和参数入口
应建立 explore 待办；搜索、筛选、排序或模式切换按是否有未观察的功能结构判断，不按控件类别一律跳过。
清单中的图标或名称不足以证明业务对象时保留未知；外层独立导航也是首帧清点范围。

已有操作尚无 Attempt 时，有效增量报告可通过明确的当前 owner 和稳定 operation_ref 修正 handling，
记录 `operation_handling_revised` 并同步原 Task；record 结束待办但不表示验证成功，改回 explore 可重开尚未执行的 Task。
defer 保留缺口。无显式 co 的普通清单不会覆盖旧决策；原 unknown 参数确认更新规则保留。
有 Attempt 或 verified/failed/cancelled 的操作不允许靠重报 handling 改写；未新增模型字段或文本意图分类器。

会解锁或改变后续操作集合的代表前置操作属于 `explore`；仅翻页、筛选、切换显示方式或选择同质值且不会改变
操作集合时通常属于 `record`。已显示为可输入字段时使用 `input_text`，只有点击后才出现输入表面时才登记 `click`。
值选择器可用一个入口操作 `explore` 来发现选项；普通选项本身只记录，不能只因关闭选择器或改变显示值而逐项探索。
每个 Region 另保存一段自然语言 `memory`，概括功能、当前状态、可见值域、选过的同质代表、是否出现
不同结构及仍缺事实。参数值不建立独立 Operation；普通同质值只选一个代表，`Custom...` 等不同分支
可另选一个。为保证 owner 结算唯一，同一 Variant 的同一 `owner + action + direction` 只能有一个
Operation；重复登记会被框架拒绝并要求把值域写入 memory。
同一状态中多个独立控件若已有可见证据证明通往同一功能表面，全部保留，但只选一个代表 `explore`，其余
`record` 并注明代表；证据不足时不猜测等价。

Operation 的 target 保留区分命令身份所需的最小功能对象。所有图标和文字控件都结合整屏上下文判断；
操作名称、相同位置或图标不决定共享。只有截图 Reviewer 确认功能对象、当前职责和直接效果一致，才共享 canonical 身份。

列表、网格或分组先区分独立功能入口、重复数据实例和参数选项。独立功能入口必须逐项登记，不能概括成“其他”；
同一操作模式下的重复数据实例才使用代表 Element；参数选项只写参数信息，不逐项创建 Operation。
代表 target 写稳定角色而不是本轮样本值，其余同质数据项不逐个登记为 `defer`。
只在部分项出现且效果不同的操作仍单独登记；不同动作也仍分开，例如同一对象的点击和长按。
同一可见控件在状态推进后承担不同下一步时，不属于重复内容。例如分步选择器的同一网格
先选开始值、再选结束值，两个 State 应分别使用带当前角色的 target。这两条本地 Operation 和 canonical 身份都保持独立，
但它们所属的稳定 Region 仍可复用。相反，翻月或 Cancel 等直接职责不随步骤变化的操作可由 Reviewer 跨 Variant 配对。
`defer` 不是低优先级分类：当前可用但不值得探索的命令应使用 `record`。

## 参数确认

每条 Operation 必填 `parameter_status=unknown|none|observed` 与非空说明。截图可直接证明
无参数时填 `none`；已经显示参数形式、当前值或至少一个代表值时填 `observed`，框架把本轮清单截图
作为证据，不要求点击。完整范围、步长或长度限制未知写入说明，不形成 gap。
连参数形式和代表值都无法确认时才填 `unknown`；安全入口若需要打开确认还必须明确
`handling=explore`。`record + unknown` 保持不执行并留下参数 gap，危险、外部或不可逆入口
不会因参数确认获得新授权。参数选项仍不建立独立 Operation。

## 写入规则

同一 State 的后续调查帧只做加性合并：本轮未重报的旧 Region、Element 或 Operation 保留；结构真的物质变化仍由位置模块登记新 State。
操作任务期间的已知 State 同样接受有效增量；用非空 `operation_ref` 为当前 Variant 补充缺失 binding，
或用空 ref 提出新候选，都进入既有审核与加性合并，不先丢弃，也不要求重判 State。
若某 owner 在旧、新报告中都只有一条同动作与同方向操作，允许同质代表 target 更新。同一 owner
不再接受多个同动作 target；语义不同的可点击目标必须登记为不同 Element，参数实例则写入 Region memory。
同一Variant内已知控件通过element_ref绑定；只改写名称不会创建新Element。空ref候选只有审核为new才进入
加性合并，因此真实新增/首次漏报按钮仍可登记，但“单个按钮”与“按钮组代表”不会直接形成两个owner。

## 2026-09-08 反馈检查

清单错误带 Region/Element/Operation 索引或实际引用；未接受清单与已保存清单区分，缺少调查信息时不引导虚报完成。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。

## 2026-09-11 可选延后分区预审

正式CLI的`--modular-explore --defer-partition-review`或`ExplorationRuntime(defer_partition_review=True)`延后新清单的整页视觉分区预审，默认仍为严格预审。模型仍须报告当前真实前景/控件，边界不确定可先使用截图上确实存在的容器，后续通过既有region_refinement修正；框架不自动猜测或合并区块。

只跳过partition_review调用；清单解析/引用/父子检查、已知State视觉核验、Element/Region/Operation身份审核和真实动作结算保持。正常不完整清单取得owner后可继续，不能把观察登记当操作已验证。每份成功接纳的非空区块清单记录partition_review_deferred，TaskScheduler.gaps按State汇总质量缺口；不阻塞可执行任务，不成为新的重试任务。本版保守保留缺口，不因运行结束、resume或后续严格模式自动清除，不能宣称分区完整验收。

2026-09-19：分区审核scope加入运行时指定的target_app/platform并进入原缓存键；Reviewer据截图确认当前前景，不从后方窗口名称猜测本次目标。Terminal真实失败中原请求缺少目标名称，Reviewer将后方GIMP当目标、作者随后迎合；目标补齐不等于所有视觉判断通过，实机结果单独记录。
