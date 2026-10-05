# Region 遍历、经验复用与图指导采集：设计对齐及代码位置

2026-10-05 Region 观察保存当前 bbox，模板资格仍由 image_quality 独立控制；受挡但边界明确时可供既有同帧局部定位使用。历史框不跨帧定位，不改变 Region 身份、任务完成或 Gmail if/else 条件与冻结图采集边界。接口与验证范围见[身份模块](modules/stepwise/identity.md)。

2026-10-04 局部遮挡提示统一按当前任务所需信息判断，允许真实适用历史辅助识别，受挡模板仍不可入清晰身份图；认识入口不代表观察了内部。6HTTP/0GUI保存帧有限通过已知菜单身份复用、入口续进与状态简化，首次受挡目标的持久动作绑定/执行尚未验收。Region归属、Gmail if/else业务条件和冻结图采集合同不变，源码位置及证据见stepwise_region_identity/debug_loop。

2026-10-04 共同prompt的局部图直接排列已有账本：当前登记区块/控件、实际上一动作、记录的进入动作和控件结果引用；不再把内部访问链/父页待办解释输出为额外地图类别。origin仍用于原调度，图来源不授权当前动作或补业务条件。Gmail月报if/else、Region任务及冻结图采集合同未改。6HTTP/0GUI有限保存帧验证地图语义；纠错defer后Runner以correction_blocked暂停（未登记正式任务暂挂）、裁图及前景质量缺口见stepwise_debug_loop，非全应用验收。

2026-10-04 控件历史投影：三步共同地图及图页按实际来源区块/确认控件展示单份历史结果；未确认控件不补身份、不借历史结果结算任务，参数与业务前置证据保留。最终6个完整保存帧场景取v3未受影响三例和v5三个更新有限通过；v3/v4添加语义失败保留，未执行新GUI。Region直属任务、Gmail月报if/else及图指导采集合同不变；原图与采集冻结源只读。

2026-10-04 逐步遍历路径落实共享树：`experiments/clock_manual_20260919/page_context.py` 从原Region图及实际观察即时派生，三步prompt与实时图页共用；当前包含结构、进入来路、工作目标分开，不将更早访问页当包含父级。原父目标经当前子区可推进时优先，但只读历史来路不授权点击或业务提交；新GUI统一登记效果。现有Gmail月报if/else例子的业务前置条件、条件观察、确认和采集边界不变；本批没有指令生成/采集或全应用覆盖声明。

2026-10-03 动作定位：当前候选披露owner及观察来源，重复外观仅凭同组外观/相对布局确认历史位置对应，不把它升级为单位、功能或业务效果。正常动作及纠错换帧更新候选；70离线与7HTTP/0GUI保存帧有限接受，含监督新增中列加号目标，未执行点击。Region直属归属、Gmail if/else条件观察及采集合同不变；采集冻结源与原图未改。

2026-10-03 功能整理事实传递：function_evidence从当前区块账本投影全部已执行且已有结果的动作，任务引用/身份是否确认独立限定；入边、导航与业务效果保持原归属，不按结果出现的位置迁移能力。来源和历史时态进入正常function_registration；42离线、6HTTP/0GUI两批保存记录中最后三个案例有限接受，早期失败保留。旧现场图及采集/指令生成均未改，不据此勾选研究目标或宣称完整遍历。

2026-10-02 当前接线：region_tasks.settle_task／累计核对决定原任务是否完成，task_routing.advance只交接已done任务；entry_evidence不自动完成新目标，历史结果不被目的区块摘要替代。collection_graph直接投影冻结逐步functions与实际可交互候选关系，普通生成→load_region_task→visual_guard→RegionGuidedCollector→Writer已接通。Clock London查询单功能实机通过，图/条件事实保留；Gmail月报if/else示例及其业务前置、条件观察、分支和共同后续要求不变，尚无该例新增验收。

2026-10-02：复制遍历器局部请求提供同帧已确认区块划分及只读跨owner控件参照，越界和争用位置走原纠错；导航结算保留实际任务反馈，功能整理读取原动作和有出处的观察。身份仍由视觉与语义核对确认，不按尺寸/SHA自动合并，不改变Gmail条件任务、业务完成边界或采集器。入口和候选验证范围见stepwise_discovery_completion/stepwise_region_identity与本月日志。

2026-09-24：复制遍历器区块身份改由前景独立控件召回与 Luna 文字核对；移除整块图自动覆盖。局部定位仅复用同帧已登记边界，原始观察保留；见 stepwise_region_identity“控件级历史身份核对”。

2026-09-24 复制逐步遍历器将历史身份文字候选与合格视觉模板分离：无合格图不再隐藏旧身份，重定位/补全及更新沿原登记核对；局部范围、任务历史和模板门槛保留。3个原生Luna保存帧案例通过，非连续实机或全图去重；当前合同见stepwise_region_identity“历史身份与模板资格分离”。

2026-09-20：收尾时的新帧回到既有observe阶段。目标应用前景已确认、已知State有清单但最新帧尚未确认时，不再直接以foreground_inventory_unconfirmed退出；先识别当前前景，已知且无变化无需重报清单，新控件按原路径登记后继续调度。未知位置沿原3轮纠正，耗尽不重新发观察机会；缺口与旧Attempt不改。无新增模型字段、状态枚举或Reviewer。空白页被伪清点为非空Region的问题仍未解决。79项聚焦离线通过，尚无此次修改后的新模型/GUI实机验收。

2026-09-19 用户纠正失败范围：未知动作不再一律结束应用。仅在原生已知State/目标前景核验通过、无新清单待审且有活动依赖任务时，沿原scheduler将该任务deferred，保留Attempt.uncertain和覆盖缺口，丢弃同轮下一动作，由下一轮原Region调度选择独立操作。新/未知落点、外部前景、清单纠正未完成、无任务恢复继续原保护；未新增结果协议或重置次数。

2026-09-19：当前准备阶段明确桌面back实际投递Esc、Android为系统返回；点击可见返回按钮必须采用当前绑定click，不能按“返回”名称推断等价。原Settings a6未知结果保留、不重放。结构预检、无owner导航独立遗漏结算及空前景完成保护见page_inventory/runtime_and_artifacts；不改变直属一层调度、分母或Gmail条件任务和下游业务验收标准。

2026-09-18 协议接线：`contracts`维护handling和唯一阶段提交规范；`partition_review.verify_partition`按角色接收reason/权威范围；`runtime._known_action_candidate/_bind_action`复用原绑定器处理唯一候选的当前视觉确认。父子身份不折叠检查保持原路径。不改变下方Gmail条件任务、完整业务原子及图引导采集目标；假环境通过不等于Luna已可靠完成Region或全应用。

2026-09-18 V2核验：恢复时仅record且从未尝试的精确当前绑定可按新适用依据进入原Task；独立漏项沿清点gap留存，未知数量不能视为0。Clock真实新增Bedtime/Clock点击并继续到Settings，r3账面5/5含旧辅助a9，不宣称“先自主complete再切区”。当前真实图的原生能力编译仍只产出到达画面的候选，不等于完整业务原子；本批生成指令/采集均0。功能粒度及Gmail if/else示例保持原要求，见`artifacts/traversal_v2_20260918_01/ASTRA_REVIEW.md`。

2026-09-18：现有modular链补齐局部资格隔离、事件持久缺口、新可信路线触发原Task回访、恢复声明与重新审核绑定。实现位于partition_review/inventory/tasks/region_work/runtime，不新增补探内核。贯穿假环境2/3→3/3不代表实机完成；未知结果不归为未执行缺口重放，Gmail月报if/else任务及采集验收仍保持原边界。

2026-09-17 当前执行目标更新：取消“VLC通过后才验证Android”的前置。保留modular主链与视觉身份，以同一核心版本先顺序运行不同结构的授权测试应用，再扩展锁定清单。区分应用被实际运行、已发现Region直属范围覆盖、应用内充分探索；未运行/受限/未知保留，不把benchmark任务或启动一次当全应用完成。程序处理观察/结算、执行、导航/准备和局部暂挂；安全/位置/结果未知停相应应用，独立健康应用继续。已有Gmail语义分支示例、采集目标不变，未勾选研究成果不因本次接线自动完成。

2026-09-17 当前遍历验收：图仍为底层事实，树用于主Agent理解任务、环境和未探索兄弟；工作Region与当前前景分开。每轮覆盖声明直属一层，保留子区块待办，再实际推进另一Region；不穷举参数组合，不递归等待全子树。Allow/Criteria派生视图及Alarm适用状态的原生用例已通过，Region实机验收仍未通过，不能勾选全应用/跨应用目标。实现边界见[Region工作范围](modules/explore_kernel/region_work.md)，Gmail月报if/else示例及采集语义验收保持原要求。

2026-09-17：修正预览保留原控件observation，原审核接收逐项编辑事实和同图/Attempt的有界历史候选/意见；只呈现证据，不按名称自动补项或合并身份。独立Luna诊断补齐此前5组缺项且保留旧条目，最终仍因卡片/列表表述被拒，原a207未恢复。详见[增量纠正](modules/explore_kernel/report_edits.md)；Gmail分支目标与状态不变。

2026-09-17：补通pending审核的具体拒绝理由到主Agent纠正卡，保留当前候选对应的路径及原预算/安全限制；不扩展新的纠错或身份系统。a207保存帧验证确认模型按意见增量修单，但仍漏项并耗尽剩余纠正，未继续实机；详见[报告纠正](modules/explore_kernel/report_correction_flow.md)。Gmail分支示例与采集合同未变。

2026-09-16：`TaskScheduler.choose` 将既有不可达焦点让位检查覆盖到新选任务，避免结算后先派发无绑定/无可信路线的旧目标、下一轮才考虑眼前待办。保留身份、路线、未完成目标与预算；batch14原输入离线回放及假环境续探通过，尚无修后实机持续性证据。详见[操作任务](modules/explore_kernel/operation_tasks.md)。本次不改变Gmail分支采集目标或实现状态。

2026-09-11：独立evidence内核的登记使用操作box＋最小语义context_box；reidentify.py回访控件及由子控件支持Region，route.py按显式已观察导航边执行并回退Luna。已有来源图片/关系及定位纠正可持久保存，未迁移旧canonical图。Gmail月报if/else例子的条件判断、业务结果仍属于语义阶段，不能因导航落点图像匹配就认定分支或任务成功；本次仅验证VLC选定click/back路径，未实现该例子的自动全图规划。详见modules/evidence_revisit.md。

2026-09-10：通用分区/前景/能力合同统一；新清单与已知State复用增加视觉核验，同帧page_report_edits保留未改候选内容，原证据不变。恢复邻居锚点和父子候选补充已接线。5应用17张保存图中，Clock导航及展开子区/返回、Contacts值变化、Files数据网格、Writer相同容器/不同字段组的12项定点检查通过；这是开发迭代与同源账本重放，不是一次独立benchmark或真实遍历。Luna-only未达稳定，本仓库openai_api配置改Sol medium；标题栏关闭按钮归属仍可漂移，截图不证明所有点击效果，未恢复采集/训练。详细图与名称见artifacts/traversal_goal_20260909/general_partition_20260910/REPORT.md。

2026-09-10：通用分区指引补齐静态内容归Region summary、标签优先/无标签用稳定功能对象、数据值和展开态不作Region身份、普通展开保留原区与独立编辑上下文区分、局部纠正保留无关边界。内联独立结果区归可见来源容器；接管输入的弹层仍遵守原前景边界。新Element空动作拒收条件不变，反馈明确可移除误报的静态Element而不编造动作。没有应用名/按钮/坐标特例，没有新增模型角色或固定调用。83项聚焦离线检查通过；11张Settings/Files/Clock保存帧已选定并核对来源，初次启动被自动审批拦截；用户随后明确授权所选及新增截图外发，模型验证已运行，结果与失败分批保留，详见本月日志与general_partition_20260910系列证据。不能据离线检查宣称跨应用准确率。

2026-09-10：按用户确认方向，历史检索主要返回具体控件/操作卡，State卡仅辅助定位；来源及共享Region邻居优先，名称/功能/所属区块分开作为检索线索，明确scope/action才过滤。Region身份候选采用不同控件锚点的一对一匹配和覆盖门槛，区块名称仅5%权重；最终视觉审核不变。已知ID的新称呼按来源保存，别名不新建身份或证明功能相同。batch15有父菜单复用、新子菜单独立、已知返回的有限实机正例，旧检索误判保留，尚无总体错误率保证。

2026-09-10：已新增可选region_refinement修正提议，允许已确认位置上的显式控件提取，旧父区保留，既有Region/Operation角色按需审核后原子更新归属与共享Task。保存VLC案例s57/r106和s24/r53各8个菜单入口已通过，202次动作原始字段不变，未选r86仍待修正；这是保存帧验证，不是实机连续验收。详细接口和限制见[分区修正](modules/explore_kernel/region_refinement.md)。

2026-09-10 Astra续跑诊断：VLC batch14成功结算源a200，7HTTP/2新GUI后因用户指出绕行异常而STOP，pending空。旧Tools任务t86累计12次焦点动作，但目标o238实际执行0次；其余为返回/导航和其他功能。当前Playlist Tools已有a119/a168成功证据，却归r106/co548，未与旧r53/co237及播放器r86/co421共享；这是已有粗区块归属缺口的具体反例。可见当前入口不应被旧来源要求阻塞；没有语义身份确认也不能按名称强合并主体或把旧任务伪结算。防循环Task预算包含导航，耗尽不证明目标功能被点击失败。下一步修复归属/共享链，非增加重试；停止点和完整证据见SERVER_HANDOFF最新章节及batch14/supervisor/final_audit.json。

2026-09-10：普通共享操作已改为一个Task、多State本地绑定；真实操作仍归其执行时owner/State，不把兄弟绑定直接标verified。旧Task引用在工作账本收敛并留映射，raw不改。候选召回可依据多个控件名称跨描述差异提供视觉比较。该改动已离线及有界实跑验证；持久导航独立分区目前仍依赖模型，历史粗区块的完整自动重归属尚未实现，不能宣称全部共享问题已修复。

2026-09-10：编码菜单已由真实滚动查看到底（Subtitles batch2/0013），原页面“仍有未见选项”是首帧摘要未同步，不能据此判为未探索。后续Subtitles batch3取得字号/描边选项并恢复原值。该批虽两次在清点中提出Back，适配器却静默清空，实际仍另调主Agent；已修正为保留无owner/operation_ref Back，合并效果以实际投递来源call核验。完整VLC遍历继续，未覆盖项与概括记录的质量问题分别保留。

2026-09-10：已知页面正常返回复用已有任务来源引用，不附加整页候选表；`status.build_agent_context`明确pending卡的位置/绑定/路线来自动作前，新图确认已到达后不用重复导航或登记。本轮缺引用可先结算，下一轮读取持久目录，不能为索取编号重报；历史路线不是实际落点证据。模式/总控的可用性前置关系和必要值域仍探索。

Subtitles两次返回实测page_report=null，无额外身份审核，各两次主调用继续下一控件。首帧6Region/25控件一次通过，但编码菜单把多个参数行合成el170/el171两个不可具体定位的owner，监督暂停；该页不是完整验收，OSD/字幕总控条件未验证。不得将这些类别owner用于后续任务或轨迹的有效绑定依据。

2026-09-10主要有限页对齐实证：Luna已取得VLC Video的层级、五组有限选项、总控禁用/恢复及目录选择器/取消结果，最终回原始s1；
共享区块和分类内容替换也有实图。允许纠正与安全绕行；这不是零漂移、完整应用或跨应用验收，未选待办仍保留。

2026-09-09：显式exploration_goal下不再自动派发旧Operation待办或替换焦点；保留已选活动任务和必要survey，其余由主Agent按范围用next_operation_ref或实际owner动作选择。无Task时可用当前唯一recorded/verified绑定恢复，仍保留绑定与近重复检查。无动作、无新事实的范围决策以scope_idle/partial结束，不冒充全应用完成。无exploration_goal时沿用原自动调度。

2026-09-09：新Element必须提供至少一种具体动作，不再接纳无动作的新控件占位；容器/组合功能归Region。已知Element可只补observation而不重复operations，历史账本仍可读取。范围卡不再把恢复误导为必须先切换开放Task，当前record控件可直接用于恢复，缺绑定先补。

2026-09-09：删除不分范围的“未知Page必须探索”绝对指引；明确输入的有限探索范围优先于待办派发，临时跨区结构比较不扩展为该区参数遍历。范围外的真实结果保留，不当作本任务覆盖。

2026-09-09：主Prompt区分虚拟机/浏览器外壳与目标应用前景窗口；父Region允许无直接控件，以无应用标签的容器行/子组parent_ref例子说明包含。实际Luna层级仍待续测，不把全null报告视为通过。

2026-09-09：删除survey必须完成后才能调查已登记控件的旧门禁。清单首次取得ref后，可用当前合法owner继续点击等调查；动作仍逐次结算，不提前完成survey。同轮清单的候选点击仍留到下一轮。有限参数列表继续观察未见选项，同质数据可以按功能结构收束。

日期：2026-09-09。设计于 2026-09-05 对齐；代码位置已随本次实现更新。

本文整理本轮用户已确认的设计思路，回答框架想做什么，以及相关功能目前在哪里。
研究目标仍以 [RESEARCH_GOAL.md](RESEARCH_GOAL.md) 为总入口；当前实现索引为
[CURRENT_FRAMEWORK.md](CURRENT_FRAMEWORK.md)。本文的目标描述不表示已经实现或实机验证。
代码位置表区分已有机制、部分实现、旧离线原型和缺口；行号按当前工作区核对，后续优先按函数名定位。
Gmail 场景是简化示例，不假定产品固定布局，也不是应用专用规则。

## 1. 整体目标与职责

当前实验按2026-09-14用户更新，先用旧 VLC 图中已核对的功能做少量生成/采集试点；全应用遍历尚未完成，局部试点不代表批量图质量验收。已有产物保留，本次不启动训练。

当前主线是：实机尽可能覆盖不同功能页面 → 定位 Region、收集功能并保存真实跳转关系 →
遍历批次结束后重组功能、批量设计复杂指令 → Agent 依据图到达各目标 Region，在实时界面
完成各项功能并验证、记录复杂轨迹。页面数本身不是唯一目标，必要的功能覆盖与可执行关系必须保留。

导航为发现页面和连接 Region 服务，不能因为它通常不是业务目标就取消通往未知内容的探索。
恢复后的必要导航和连续有效滚动可以重复已成功操作，不要求先证明整条路线；此前走过不等于当前已到达目标，每步仍需实际结果核验。
任务生成同样不能因省略导航子目标而擅自禁止必要导航，或添加用户未要求的起始页面条件。
采集中的准备目标按其观察/展开要求完成后交回框架，再判断条件并执行选中分支；总指令不授权每轮重做后续业务动作。
已完成目标摘要不随最近动作窗口滚出；终验保留成功提交前与完成后的配对证据，不能只看到结果摘要就丢失参数值依据。
减少导航按钮的重复验证，不等于减少页面探索；参数确认也不能扩展成阻止继续发现其他页面的穷举任务。
共享身份、增量报告、缓存与纠正机制均应服务于这条主线，不取代它成为框架的主要工作。

### 2026-09-09 用户明确的层级探索目标（尚未完整实现）

详细例证及用户七步原话见[VLC探索组织例子](VLC_EXPLORATION_EXAMPLE.md)。新对话先用该例子核对“分区/控件与功能/必要探索/关系/共享/实机采集”的理解；不要把例子当成VLC特例规则或已完成验收。

- 先识别当前可交互前景。以VLC为例，Simple Preferences是前景容器，可组织为分类导航、设置内容及底部设置/提交区；
  Interface Settings下再组织Look and feel、Playlist and Instances、Privacy / Network Interaction等功能子区。
  这些是用户给出的界面解释目标，实际归属和边界要用当前截图、滚动及切换结果验证，不编码应用名或标题规则。
- 控件保持独立物理owner，功能、参数、互斥和条件子功能优先用自然语言表达，并引用相关owner和证据。
  如“设置媒体切换提示显示时机：Never、When minimized、Always”；该选项集由用户提供，尚待本轮原图展开核对。
  多个控件可共同表达一个选择功能，但不能因此合并可分别点击的owner。功能层级不要求每层各派一次模型任务。
- 有限下拉框需要展开调查选项；看到当前值不等于已经确认取值范围。观察选项不要求逐个应用这些值或穷举组合。
  单选式/模式式入口也可能显露不同配置内容，需要有目的地切换、确认关系与分支，不能一律作为普通值跳过。
- Look and feel可作为稳定父区，保留两种样式的选择入口；Native设置与Custom skin配置作为条件子内容组织。
  当前已保存的一次切换证据支持Native取消选中、Custom选中及皮肤文件控件出现；互斥及条件的语义推断与观测依据分别说明。
- 发现内容区未展示完整时，滚动补齐尚未观察的功能。顶部/底部不随内容滚动是区分组件边界的证据；
  底部Show settings、Reset Preferences、Save、Cancel单独组织，同一显示模式的参数也要调查其可见选项与内容变化。
- 新证据应允许修正初始粗分区：如切换Audio后，保留分类导航与底部区，把Interface内容替换为Audio内容。
  包含、条件依赖、动作显隐因果及同屏可见性分别表达；不能让一次粗分区永久锁定后续表示。
  细化须保存旧观察与控件/任务引用的对应关系，不能通过改写原始Attempt掩盖过去的错误分区。
- 采集先识别当前可见的目标Region并就地操作。例如Audio操作后底部Show settings已可见，就直接使用；
  不需要Audio Settings到这个固定底栏的因果边。只有目标不在当前可交互前景时才借助图导航。

当前代码边界：`explore/models.py`/`inventory.py`已支持本State实例父子归属和带来源的控件观察，
`status.py`和身份审核可读层级，`bundle.py`已导出层级及带证据的功能目录，均有离线合同验证。
新State中的父引用会重新绑定；已有粗区块全部控件/任务的自动重分配、统一的下游消费及实机持续效果仍待完成。
功能条件保持自然语言，没有新建递归任务调度器或专用互斥求解器；以上实现状态不替代Luna实机验收。

2026-09-09：真实采集的每个GUI动作（含导航/恢复）都需回填结果。有pending动作的输出Schema不含none，
没有上一步时才允许none；不能用最终目标成功掩盖中间回执缺失，原不合格记录保留。
该合同已有桌面Clock三目标任务4步success实机正例，并用实际before/primitive导出4条SFT样本；
不把目标Region当成每一步实际控件的owner真值，不将该接线正例当作条件任务或双端完整遍历。

2026-09-09：采集的功能结果可能使来源Region消失（如启动后切换为运行控制），普通目标依据结果确认完成，
不再为保持来源可见而回退；最终截图核验保留。条件观察仍要求有效观察位置，互斥Region条件候选须单独验证。

2026-09-09：修正新State调查接替的内部冲突，已按同Page可见结构变化取消的旧survey，不再被“必须回原State”检查恢复。
这使清理一次性提示后的实际功能表面能被清点；旧临时观察不是已覆盖功能，不删除其证据。

2026-09-09：纠正Region效果时保留同一Attempt/同一后帧中已通过结构与Element检查的清单，只要求修错误字段。
临时保留不提前提交图或跳过最终Region身份审核；新帧/新动作/其他纠正不沿用，防止为修因果而破坏已经正确的物理owner。

2026-09-09：局部Region恢复不自动证明整个已完成State身份。`location.validate_state_composition`检查声明的完整Region组合；
不完整的本次观察可以用新State组织并复用Region，不改变旧State。复用完整State时不重建控件目录，多报候选仅留审计。
这保留Region优先恢复，同时防止把有/无独立卡片的场景仅凭相同底栏合并。新State和普通清单的owner校验保持。
同一检查现覆盖无pending动作的已知State改写；历史任务的source_state不能替代最新位置，完整确认可支持自然界面变化。

2026-09-09：`TaskScheduler.choose()`在当前目标无绑定/已验证路线、无pending回执、当前State已清点时，
可先处理其他具有当前合法binding的pending功能。旧目标保留待办及证据，不以反复进入已验证替代入口强行完成它。
这只改变暂时不可达目标的调度优先级；身份、owner、路线及真实结果检查保持。

2026-09-09：功能清点不等于数据清点，滚动条/截断不强制穷举全部同质值；结构、代表控件与操作已明确时
用survey_complete和coverage_note收束，异质功能及未知结构继续调查。指令生成不能把“未穷举”改写成全值覆盖。

2026-09-09：`resume.prepare_resume_region_rediscovery()`将中断不确定性归给真正投递的操作，
保留未执行focus待办与既有verified历史；不把route过程中另一动作的未结算状态写成目标功能失败。
必要前置可用已登记record owner直接准备，不需另派任务或代表实验。旧开发图中的错误归因未自动消除。

2026-09-09：`status.build_task_view()`为当前任务补足已知来源State的历史owner，避免到达后只能看到
上一State的同名owner而再次走无绑定恢复。引用不证明可见，仍由最新图定位与原动作归属校验决定执行。
删除任务卡“已派发就必须本轮执行”措辞；不改变Task完成条件或已有执行结果。

2026-09-09：`settlement.settle_completed_actions()`拒收可选的错引用功能笔记和未请求参数说明，
保留审计而不阻塞已独立校验的动作；不会把结果表单参数赋给来源按钮。必需owner/参数/代表证据不放宽。
恢复图只补实际增量，同质数据的一个代表必须有具体物理owner。a38保存帧原生回放确认进入Select time，
可作为明确标注离线重验来源的续跑图副本；不是新动作、闹钟创建或完整覆盖，恢复仍须fresh截图定位。

2026-09-09：动作到Android触摸保持模型在Region内选择的真实起点，滚动幅度不再被忽略或当作次数；
同一owner的参数none/observed分类可按新观察修正并保留来源，改标签不算进展。两项均为通用执行/记录修复，不识别应用名或按钮名。

2026-09-09补齐执行信息：已知State均带简短Region引用目录，待结算和近期回执保留实际投递点位；
它们是历史证据，不证明当前可见。`inventory._validate_report_region_refs()` 提前拦截跨State清单并给出所选State的精确合法目录，
runtime保留准确纠正字段；空Element候选由既有审核解决，不用旧Variant编号凑绑定。

2026-09-09：`region_review.apply_region_identity_result()` 不再把与候选组件不同强制解释为无动作因果。
组件身份比较和 source_transition 的来源显露分别校验，实际来源与落点检查保留；没有增加角色或输出字段。

2026-09-09 实现：`prompts.py` 按未知功能结构决定 explore，不再把搜索/筛选/显示方式一律跳过，也不为普通参数
固定做两个代表。`status.known_graph()` 提供已有 State 的内容摘要供视觉核对，导航相同不证明内容相同；
`inventory._accept_operation()` 接受明确当前 owner/co 对尚未执行操作的决策修正，沿用原 Task并保留修正事件。
已有 Attempt、verified/failed/cancelled 结果不会被覆盖。原 a17 保存帧身份回复已纠正，双端实机验证尚在进行；
Gmail遗漏与Calendar对象误判仍有反例，不把图中条目数称为功能覆盖率。

### 安全反例：可逆设置使无人值守遍历失去控制

2026-09-08实机中，Agent打开Screen Blank菜单后实际选择了1 minute（a131）；随后画面显示设置值为1分钟，并最终进入密码界面。监督仅确认了点位和代表值任务，没有考虑模型等待期间的延迟熄屏/锁屏风险。证据：[设置为1分钟](../../artifacts/runs/settings_luna_resume_c9c1fc1f_20260908/actions/0119/before.png)、[最终密码界面](../../artifacts/runs/settings_luna_resume_c9c1fc1f_20260908/final.png)。

正确处理是安全打开菜单、记录功能和值域，不实际选择可能让Agent失去可自行恢复控制的值；可逆不等于Agent可自行恢复。启用共享/远程访问等可能对外开放数据或控制的开关也不能当普通开关试验。风险按动作后果判断，不在框架中按这些名称或坐标写特例。旧图中的危险待办也不构成执行授权；只保留发现事实与安全跳过原因，不伪造效果验证。

恢复实验属于显式环境准备：保持原图和原始证据，在副本中标注安全跳过；先恢复可控制桌面，关闭误启用的共享服务并防止自动锁屏/休眠中断，再由新截图确认位置。环境准备不算Agent自主遍历动作。

恢复定位只要求确认当前实际区块，不要求先证明整条返回路线；刚登记的中间控件可在下一轮帮助发现路线。此修正对应 `runtime.py` 的 `resume_region_rediscovery_completed` 分支，未改变任务完成或真实动作证据要求。

2026-09-08：纠正轮不再把旧strategy展示为当前思路；contracts定位具体字段，settlement保留已有期望/收到值，runtime按真实执行阶段反馈。旧逐项文字检查见 [反馈检查](modules/explore_kernel/feedback_review_20260908.md)；当前接收角色、允许修改范围和共用三轮退出规则见 [报告纠正流程](modules/explore_kernel/report_correction_flow.md)。GUI按钮是否相同仍由最新截图和视觉判断确定，不能按名称硬编码；Gmail等例子仍只是设计说明。

通过低重复的 GUI 探索尽量发现不同功能，以 Region 及动作造成的 Region 变化组织图，
积累功能、可达关系和经验；根据发现的功能生成用户目标，再指导 Agent 到达功能区块，
由 Agent 根据实时界面完成目标并采集新轨迹。

```text
观察界面、发现功能与 Region
  -> 对未知功能结构做必要探索
  -> 判断组件身份和动作因果，复用已知部分、补充差异
  -> 保存图、证据和有用经验
  -> 根据功能目录设计指令及条件分支
  -> 图指导到达相关 Region
  -> Agent 根据实时截图完成具体任务
  -> 保存实际分支、动作、截图和结果，验证本次任务
```

- Luna 判断界面语义、组件身份、操作职责、变化原因以及值得继续探索的内容。
- 框架分配稳定引用、绑定当前 owner、执行动作、维护事实和待办，保存真实证据并检查结果。
- 图提供功能分布、到达关系和相关经验，不要求列出未来任务的所有按钮步骤或截图状态。
- 不把应用名、按钮名、坐标、某个反例的处理步骤写成通用判定规则。
- 本文不是新增 Prompt 字段、Schema、模型角色、重试计数器或记忆系统的要求。优先复用现有机制。
- 任务选择由 `tasks.TaskScheduler.select_visible_operation` 校验，`runtime._context` / `status.build_agent_context` 传递具体纠正。`next_operation_ref` 只用于切换开放待办；辅助滚动用已有 `action.owner_ref`，重复选择当前任务不拒绝动作。反馈明确字段、原因及改法，不根据按钮文字猜测意图。2026-09-07 此调整已做离线验证，尚未实机重跑。

## 2. 发现完整功能，省略重复执行

| 内容 | 预期处理 |
| --- | --- |
| 语义明确的输入框、简单操作 | 记录功能及可见参数，不为了验证存在而执行 |
| 内部功能未知的菜单、选择器、设置入口 | 打开观察，补充隐藏信息 |
| 同一操作模式的重复数据项 | 选代表；不逐项执行，不把不同功能误当同类 |
| 参数选项与普通取值 | 为补未知功能、条件或指令所需值域展开；已知值域不重开，未查范围保留未知；不逐值执行业务或穷举组合 |
| 可能影响子功能显隐或可用性的模式/总控 | 安全可逆对照、记录前置条件并恢复；已确认关系不重复试验 |
| 会显露不同功能结构的特殊分支 | 单独探索 |
| 已确认的共享 Region | 复用已知知识，补充当前新增功能、限制或差异 |

省略点击不等于删除功能目录。一次成功探索可供后续任务参考；发现功能也可以直接设计指令，
不要求先执行或收集两份匹配效果。未执行的预期不能标为实测结果。

完整遍历针对本次可探索范围内的独立功能、Region 和必要关系，不针对所有数据实例、参数组合或像素画面。
未知结构应探索或保留明确缺口；不能因为任务队列暂时为空，就宣称任意应用的全部功能已经发现。
当前实机迭代优先证明可从已有图继续发现功能并保存真实关系，暂不要求所有待办清零。
合法的不完整清单可无动作补充或纠正，不强制每轮执行GUI；保持未完成状态，已有预算耗尽时保留缺口。
重启后的恢复定位与清点完成分开：清点任务确认自己的来源State和可见Region后即可退出恢复，随后继续未完成的清点。
清单提交与click分轮，空owner点击不会绕过此边界。被阻止后保留候选，由Luna通过已有next_operation_ref优先改选另一可见绑定。
实现位于runtime.py::run的已有same_turn_operation_rejected分支；不新增字段/计数器，也不按按钮文字或坐标自动匹配owner。
全局结束由框架根据已有任务与gap判定：还有可执行任务则继续，pending动作先结算，无可执行项时按有无gap返回partial/complete。
主Agent在执行当下报告效果、失败原因及限制，不要求最后统一复核缺口，也不需要看到全部待办。
已移除finish输出及completion_check调用；实现位于runtime.py::run、status.py::build_task_view、contracts.py::AgentTurn和prompts.py::RESPONSE_SCHEMA。
该结束判定已有离线检查；complete仍仅指已发现范围闭合，不替代实际覆盖评估。

## 3. Region、共享组件与页面去重

Region 是共享局部交互上下文、具有共同变化边界的功能组件，不按面积、边框或控件数量划分。
共同编辑并提交一个对象的字段可属于一个 Region；同质列表成员通常不是各自独立的 Region。
列表成员打开的完整编辑面板若有独立交互边界，则与来源列表分开，通过动作关系连接。

判断同一组件时，Luna 比较功能职责、作用对象或对象类别、交互上下文、组件边界及差异性质。
同名、同图标、同位置和相似布局仅能帮助寻找候选，不能由代码直接证明身份相同。
Element身份必须对应同一个可交互落点；多个独立按钮不能因属于同类而共用一个ref。同一报告的非空Element引用现由代码校验唯一性，语义判断仍由既有Reviewer完成。
共同显隐帮助判断边界，但整页一起消失的不同组件不能据此合并。不确定时不强行共享。

```text
Network 页面：导航 r1 + Network 内容 r2
Sound 页面：  导航 r1 + Sound 内容 r3
```

两页引用同一个 r1，复用功能与经验，同时保留 r1 在当前页面出现以及当前可用控件的事实。
当前选中项、数据和控件位置可不同；不能把各历史版本的控件并集当成当前可点集合。
共享导航可以作为当前路线起点，不必绕回第一次发现它的页面。

| 去重层次 | 合并或复用什么 | 不能丢失什么 |
| --- | --- | --- |
| Page / State | 已知主要功能目的地及符合当前结构的状态 | 当前新结构、遗漏功能、真实进入关系 |
| Region | 跨页面的稳定功能组件身份和知识 | 当前形态、出现位置、可用操作与上下文差异 |
| 同类项 / Operation | 相同模式、已确认的命令职责和适用经验 | 不同对象范围、例外和实际结果 |

Page 组织主要功能目的地；State 记录观察时的区块组合和功能结构。截图变了不等于新 Page；
页面已知也不等于里面所有功能都探索过。不同页面允许局部 Region 共享。

## 4. 按钮功能与带上下文的 Region 变化

按钮不是一个图标字符串加一个固定目标页面。要理解它属于哪个 Region、作用于什么对象或范围、
承担什么职责，以及已观察结果适用于什么上下文。具体任务对象和落点由实时界面确定。

例如列表工具区的归档作用于选中邮件，阅读区的归档作用于当前邮件；不能因图标相同就直接共享全部绑定与结果。
同一返回职责也不能固定成“永远回收件箱”：从搜索结果打开邮件后返回，可能恢复搜索结果列表；
二级设置的箭头还可能只恢复上级导航，而不改变右侧内容。必要进入历史是判断依据，
但不能把“返回一定沿最近来路逆走”写成通用规则。

```text
来源 Region 中的 owner + 动作 + 必要上下文
  -> 动作导致哪些 Region 出现
  -> 动作导致哪些 Region 消失
  -> 哪些已有 Region 保留或内部内容发生变化
```

前后截图保存证据，局部 Region 变化描述图中的动作作用。出现可以是已知 Region 再次显露，
不代表必须创建新 Region 或重新探索全部功能。

仅比较 Region 集合差还不够：搜索前后同一个邮件列表可能只是换成搜索结果，
打开另一封邮件可能只是替换阅读区的对象。应保留“搜索影响列表”“打开所选对象”这类功能和经验，
不按每个搜索词、邮件标题或普通字段值建立全局 Region，也不强行制造显露/隐藏边。
如何用已有操作结果、memory 和图关系表达这类更新仍需实现对齐，本文不预设新的持久字段。

## 5. 动作效果与外部事件必须分开

| 点击编辑后的观察 | 应如何处理 |
| --- | --- |
| 编辑面板出现 | 确认由点击造成后写入动作边 |
| 闹钟提醒同时出现 | 若是独立定时事件，不写成编辑按钮效果 |
| 原内容被提醒遮挡 | 遮挡变化归因于提醒，不能归因给编辑 |
| 编辑结果被挡住，看不清 | 保持不确定，处理干扰后继续观察，避免直接重做动作 |

同一 after 图可以同时包含动作效果、独立事件和不确定变化。
Luna 根据实际动作、前后图和必要近期上下文判断因果；同一个应用内部也可能发生与本次动作无关的事件。
观察记录与可复用动作关系分开：有变化不等于有该按钮的因果边。
主 Agent 的预测和region_effects只列相关、需记录的变化，保持不变或无关变化可省略；妨碍判断/交互时用已有reason简述。
本轮效果引用须与最终区块清单一致，多个相关结果区块分别归因；不强制每个区块都填写cause或解释省略。
Reviewer只审核已有区块，省略不构成错误，不能仅凭先后出现补因果。两处说明位于
`prompts.py::MAIN_SYSTEM_PROMPT`、`agent.py::REGION_IDENTITY_PROMPT`；已做离线合同检查，未新增模型实测。

2026-09-07 已批准并实现：主 Luna 漏报区块的动作归因时，现有 Region Reviewer 可根据真实进入动作和
前后截图补齐显露关系；明确 external/uncertain 不被这条补充路径覆盖。实现位于
`region_review.py::build_region_identity_payload`，落账沿用 `apply_region_identity_result`，无新字段或调用。
Settings 实例：主 Luna 已分别登记通知总开关和应用通知列表，却只归因前者；保存的原 Reviewer 回复
回放后可同时连接两者。此修正已通过离线回放与针对性测试，尚未进行修正后的新 Luna 实测。

待对齐细节：背景仍可见但被模态阻止交互时，“保留”“不可交互”和“消失”不能未经定义就混用。
当前清点偏向 active surface，本轮没有确定新的表示或改动该合同。

## 6. 经验怎样改变后续探索

循环是：实际观察 -> 总结有用结论 -> 在相关情境取出 -> 改变探索选择 -> 根据新证据修正。

| 观察 | 有用经验 | 后续方向 |
| --- | --- | --- |
| 普通邮件采用相同阅读结构 | 同类实例可复用 | 不逐封打开，寻找未覆盖功能 |
| 带附件邮件多出独立操作区 | 存在原代表未覆盖的结构 | 探索附件区 |
| 某次点击只出现 tooltip | 尚未取得预期结果，原因未定 | 重新观察目标，不把它当成功或永久禁用 |
| 返回恢复搜索结果列表 | 结果依赖进入上下文 | 不推广为固定回收件箱 |
| 闹钟遮挡动作结果 | 独立事件干扰了观察 | 恢复后再结算原动作 |

经验区分 Region 可共享知识、特定上下文的操作结果、原因未明的单次观察。
一次失败不等于功能不可用；一次代表成功不证明不存在例外。新证据可缩小或修正旧结论，原动作证据保留。

优先使用现有 Region memory、Attempt/History、策略与错误反馈：在原有结算轮更新真正新增的经验；
选择动作时提供当前/目标 Region 的相关知识、必要近期动作和未解决问题，不每轮回放全图日志。
暂不增加每步独立反思调用、第二份经验数据库或运行时修改模型权重。

经验必须实际影响“跳过什么、探索哪个差异、补什么前置、怎样恢复、何时转移区块”。
若 scheduler 始终锁定原任务，即使 memory 正确也可能继续空转；有字段不等于已经形成有效经验学习。

## 7. Gmail 分支指令与实时采集示例

假设图已发现搜索、邮件列表、阅读/附件、回复、标签和归档功能，且“报表待核对”标签已经存在。
目标是处理财务月报并整理到后续核对的位置。不要悄悄增加创建标签或其他无依据的子任务。

| 逻辑节点 | 内容 |
| --- | --- |
| A | 目标邮件是否包含附件 |
| B：A 成立 | 回复“已收到附件，谢谢。” |
| C：A 不成立 | 回复“邮件中没有看到附件，请补发，谢谢。” |
| D：共同后续 | 添加“报表待核对”标签 |
| E：共同后续 | 归档 |

共五个逻辑节点，每条实际路径是条件观察和三个业务操作，不按鼠标点击数计子操作。
完整自然指令：

> 在 Gmail 中找到财务发来的、主题为“六月报表”的邮件。如果邮件包含附件，回复“已收到附件，谢谢。”；
> 否则回复“邮件中没有看到附件，请补发，谢谢。”。回复后，为该邮件添加“报表待核对”标签，再将其归档。

```text
共享导航 / 搜索区
  -> 邮件列表（可能是搜索结果，同一列表组件的数据变化）
  -> 打开匹配邮件，出现阅读区
       -> A：查看当前邮件的附件信息
          -> 有附件：进入回复区，发送确认收到的回复
          -> 无附件：进入回复区，发送请求补发的回复
       -> 进入标签选择区，给同一邮件添加“报表待核对”
       -> 回到可用邮件操作区，归档同一邮件
```

这些导航、填写和发送可能分布在不同页面、弹层或内联区块，不要求恰好五次点击。
切换搜索结果或邮件内容不能造成无数新 Region；共享导航保持同一组件身份。
如果发送后回到列表，应重新核对目标邮件，而不是在相似列表中误操作另一封。
二级设置返回按钮与邮件返回按钮即使外观相同，也不能按名称共享固定落点。
从搜索结果进入邮件后的返回，应结合进入上下文和实际后图判断，不能预设总回收件箱。
任务途中闹钟响起，不把提醒的出现挂到回复或标签按钮的动作边。

下面用示意 Region ref 展示新入口可消费的结构。这些 ref 不是实际 Gmail 运行数据；真实任务必须使用所选 ledger 的编号。

```json
{
  "instruction": "找到六月报表邮件；有附件则回复确认收到，否则请求补发；然后加报表待核对标签并归档。",
  "before": [{"region_ref": "r_read", "goal": "找到财务发来的六月报表邮件并打开，核对发件人和主题"}],
  "condition": {"region_ref": "r_read", "goal": "当前这封目标邮件是否包含附件？"},
  "if_true": [{"region_ref": "r_reply", "goal": "向该邮件发送回复：已收到附件，谢谢。"}],
  "if_false": [{"region_ref": "r_reply", "goal": "向该邮件发送回复：邮件中没有看到附件，请补发，谢谢。"}],
  "after": [
    {"region_ref": "r_labels", "goal": "为同一目标邮件添加已存在的报表待核对标签"},
    {"region_ref": "r_mail_actions", "goal": "将同一目标邮件归档"}
  ]
}
```

before 包含条件判定前的准备目标；业务核心仍是 A/B/C/D/E。动作数、模型轮数与逻辑目标数分别记录。
生成阶段检查功能依据、共同目标、对象一致、分支互斥和后续依赖；不提前决定真实分支。

图指导到达搜索区、列表、阅读区、回复区和标签区。采集时根据最新截图判断 A：
没加载完或看不清不是 false；可以继续观察。B、C 只执行一条，D、E 针对同一目标邮件。
回复框已展开时不必重复打开；发送后若回到列表，重新核对任务对象；未知中间状态本身不构成失败。
到达 Region 只是这一段导航完成，Agent 仍须完成具体任务并核对对象、参数和前置条件。
记录条件依据、所选分支、真实动作和最终结果，未执行分支不能伪造成功或失败证据。

## 8. 当前实现对照

以下链接给出文件和函数，已有代码不等于已通过新设计的实机验收。

| 功能 | 文件位置与符号 | 当前状态 / 差距 |
| --- | --- | --- |
| 图的数据对象 | [explore/models.py](../gui_rewalk/src/core/explore/models.py#L37) 第 37 行，`Region` | 已有 Region/Variant/Occurrence/Element/CanonicalOperation/Transition；这些是记录基础，不代表身份判断一定正确。 |
| 编号与事件 | [explore/ledger.py](../gui_rewalk/src/core/explore/ledger.py#L31) 第 31 行，`ExplorationLedger` | 已有唯一账本和事件记录，避免第二份图真值。 |
| 页面与状态 | [explore/location.py](../gui_rewalk/src/core/explore/location.py#L26) 第 26 行，`bind_screen` | 已有位置报告绑定和引用校验；页面语义由主 Agent 判断。 |
| 清点与省略 | [explore/inventory.py](../gui_rewalk/src/core/explore/inventory.py#L287) 第 287 行，`apply_page_report` | 已有功能登记、handling、参数、memory 和增量合并；只记录功能不必执行。 |
| 主 Agent 指导 | [explore/prompts.py](../gui_rewalk/src/core/explore/prompts.py#L1) 第 1 行 | 现有主提示包含 Region 边界、同类代表和探索范围；尚未按本文全部对齐。 |
| 身份审核提示 | [explore/agent.py](../gui_rewalk/src/core/explore/agent.py#L1) 第 1 行 | REGION_IDENTITY_PROMPT / OPERATION_IDENTITY_PROMPT；模型判断组件、操作和因果，不能当成确定性真值。 |
| 候选与截图 | [explore/region_review.py](../gui_rewalk/src/core/explore/region_review.py#L94) 第 94 行，`build_region_identity_payload` | 已有相关旧 Region、来源动作和观察截图输入；shortlist 不证明相同。 |
| 组件与因果判断落账 | [explore/region_review.py](../gui_rewalk/src/core/explore/region_review.py#L681) 第 681 行，`apply_region_identity_result` | 已有明确身份配对及 known_operation_reveals_current；不等于每个显隐变化都经过因果过滤。 |
| 共享身份合并 | [explore/regions.py](../gui_rewalk/src/core/explore/regions.py#L473) 第 473 行，`merge_region_identity` | 已有共享 Region/操作处理及当前局部记录保留；同一组件不自动继承全部结果。 |
| 同 State 重复区块 | [explore/regions.py](../gui_rewalk/src/core/explore/regions.py#L439) 第 439 行，`coalesce_complete_region_occurrences` | 已有经审核的 occurrence 收束，不按名字自动合并。 |
| 当前动作 owner | [explore/settlement.py](../gui_rewalk/src/core/explore/settlement.py#L118) 第 118 行，`resolve_action_operation` | 已有当前 Variant 的 owner/action 绑定；避免名称或旧坐标替代身份。 |
| 结果与经验写入 | [explore/settlement.py](../gui_rewalk/src/core/explore/settlement.py#L216) 第 216 行，`settle_completed_actions` | 已有完成动作、参数和 Region memory 更新；memory 仍依赖模型报告质量。 |
| 显隐集合差：已确认偏差 | [explore/region_routes.py](../gui_rewalk/src/core/explore/region_routes.py#L13) 第 13 行，`refresh_transition_region_effects` | 已改为仅校验显式因果声明；record_region_effects 消费主 Agent 的变化归因，外部/不确定变化不进入动作边。 |
| Region 路线 | [explore/region_routes.py](../gui_rewalk/src/core/explore/region_routes.py#L196) 第 196 行，`plan_region_route` | 已有目标 Region/操作路线，精确上下文或明确结果复用；不是对任意新情境的通用保证。 |
| 代表项 | [explore/tasks.py](../gui_rewalk/src/core/explore/tasks.py#L14) 第 14 行，`register_representative_probe` | 已有明确同类成员和代表机制；不要求所有普通功能做两次。 |
| 探索方向 | [explore/tasks.py](../gui_rewalk/src/core/explore/tasks.py#L310) 第 310 行，`TaskScheduler.choose` | 新增 select_visible_operation：主 Agent 可明确改选当前可见开放 co，旧 Task 保留；默认调度继续可用，实机效率未验证。 |
| 完成与缺口 | [explore/tasks.py](../gui_rewalk/src/core/explore/tasks.py#L467) 第 467 行，`TaskScheduler.gaps` | 已有失败及参数缺口；逻辑闭合不证明任意应用全覆盖。 |
| 取出 Region 经验 | [explore/status.py](../gui_rewalk/src/core/explore/status.py#L236) 第 236 行，`semantic_exploration_focus` | 已有 Region memory 投影；同区块近期证据及显式改向已接入，真实经验质量仍待验证。 |
| 近期操作经验 | [explore/status.py](../gui_rewalk/src/core/explore/status.py#L381) 第 381 行，`recent_actions` | 近期窗口还可包含同一 Region 的其他任务结果；不增加历史窗口大小或反思调用。 |
| 组装 Luna 上下文 | [explore/status.py](../gui_rewalk/src/core/explore/status.py#L650) 第 650 行，`build_agent_context` | 已有截图以外的任务、图、路由和反馈输入；可复用，不必新建记忆系统。 |
| 动作、观察、恢复协调 | [explore/runtime.py](../gui_rewalk/src/core/explore/runtime.py#L1711) 第 1711 行，`ExplorationRuntime.run` | 现有主循环、pending、预算与纠正；报告与身份审核共用三轮失败预算，保留原 GUI 动作预算。 |
| 证据文件 | [explore/artifacts.py](../gui_rewalk/src/core/explore/artifacts.py#L13) 第 13 行，`ArtifactStore` | 已有截图、Attempt 前后帧、checkpoint 和 completion 落盘。 |
| 导出采集资料 | [explore/bundle.py](../gui_rewalk/src/core/explore/bundle.py#L393) 第 393 行，`compile_modular_bundle` | 另导出 function_inventory.json；从已登记 Region/操作直接生成含零动作功能的目录，不依赖效果晋升。 |
| 从效果归纳能力 | [scenario/capability_induction.py](../gui_rewalk/src/core/scenario/capability_induction.py#L1166) 第 1166 行，`induce_capability_graph` | 旧效果归纳保留为证据视图；新 Region 任务生成直接用 region_function_inventory，不经过此晋升门槛。 |
| 主线指令骨架 | [scenario/capability_task_synthesis.py](../gui_rewalk/src/core/scenario/capability_task_synthesis.py#L387) 第 387 行，`synthesize_single_capability_instructions` | 8d18dd2a 已允许 discovered/executable；主要是单能力骨架，仍要求 recipe 等信息。 |
| 指令文案与按需上下文 | [scenario/capability_task_synthesis.py](../gui_rewalk/src/core/scenario/capability_task_synthesis.py#L155) 第 155 行，`compose_instruction_drafts` | 模型润色固定骨架；同文件 selected_capability_context 只取已选功能信息，不是完整分支生成采集。 |
| Region 功能提取原型 | [scenario/region_function_research.py](../gui_rewalk/src/core/scenario/region_function_research.py#L227) 第 227 行，`RegionFunctionExtractor` | 离线原型：从 Region 图像和成员信息提取功能；没有自动接入 modular 主链。 |
| 条件任务原型 | [scenario/function_collection_research.py](../gui_rewalk/src/core/scenario/function_collection_research.py#L291) 第 291 行，`FunctionInstructionDesigner.select` | 旧辅助 API 仍接受调用方 branch_taken；新 design_region_instruction/RegionGuidedCollector 在同文件中独立处理生成与实机条件判断。 |
| 到达后自由执行原型 | [scenario/function_collection_research.py](../gui_rewalk/src/core/scenario/function_collection_research.py#L413) 第 413 行，`FunctionCollectionCoordinator` | 旧 State 协调器保留；同文件 RegionGuidedCollector 已接 GUI 循环，不要求未知中间 State 命中图节点。 |
| 旧采集控制 | [scenario/visual_collection_executor.py](../gui_rewalk/src/core/scenario/visual_collection_executor.py#L1364) 第 1364 行，`VisualCollectionExecutor._plan_route` | 此函数仍用于旧 M13；--region-ledger 选择 RegionGuidedCollector，Region 关系是历史指导，Agent 根据当前界面执行。 |
| 轨迹保存 | [scenario/collection_writer.py](../gui_rewalk/src/core/scenario/collection_writer.py#L390) 第 390 行，`CollectionWriter.write_visual_episode` | 已有实际步骤、截图和结果落盘，可作为后续采集基础。 |
| 正式采集入口 | [gui_rewalk/run_visual_collection.py](../gui_rewalk/run_visual_collection.py#L778) 第 778 行，`prepare_collection` | 同文件 run_region_collection 是新 --region-ledger 入口；prepare_collection 保留旧能力图路径。validate-only 不启动 VM 或模型。 |

| 主 Agent 变化归因 | [gui_rewalk/src/core/explore/region_routes.py](../gui_rewalk/src/core/explore/region_routes.py#L44) 第 44 行，`record_region_effects` | 将本轮清单序号解析为框架 ref；独立事件和 updated 进 events，只有已归因显隐进入动作边。 |
| 显式探索改向 | [gui_rewalk/src/core/explore/tasks.py](../gui_rewalk/src/core/explore/tasks.py#L286) 第 286 行，`TaskScheduler.select_visible_operation` | 只选择另一个当前可见开放目标；保留旧待办，非法或重复选择沿用原拒绝预算。 |
| 零动作功能目录 | [gui_rewalk/src/core/scenario/region_function_research.py](../gui_rewalk/src/core/scenario/region_function_research.py#L202) 第 202 行，`region_function_inventory` | 包含已登记操作和只读 Region 信息，不要求历史 Attempt。 |
| 新分支任务生成 | [gui_rewalk/src/core/scenario/function_collection_research.py](../gui_rewalk/src/core/scenario/function_collection_research.py#L586) 第 586 行，`design_region_instruction` | 同一调用从发现目录生成 Region 目标、条件与共同后续，不预先选择分支。 |
| 新 Region 采集 | [gui_rewalk/src/core/scenario/function_collection_research.py](../gui_rewalk/src/core/scenario/function_collection_research.py#L604) 第 604 行，`RegionGuidedCollector` | 根据最新截图完成目标，运行时判断条件；结果、分支和完成截图进入原 writer。 |
| 新采集 CLI | [gui_rewalk/run_visual_collection.py](../gui_rewalk/run_visual_collection.py#L1277) 第 1277 行，`run_region_collection` | --region-ledger 选择新模式；validate-only 不创建环境或模型，来源 digest 可核对。 |
| 共用 GUI 动作 | [gui_rewalk/src/core/explore/actions.py](../gui_rewalk/src/core/explore/actions.py#L115) 第 115 行，`execute_action` | 探索和采集共用 fresh 坐标、桌面单次全选替换输入；记录已投递 primitive。 |

## 9. 当前遍历状态（2026-09-07）

优先跑通完整遍历，跨页面功能归纳和未完成清理暂停。入口、页面、Region 身份不为复用而强行合并。
按钮功能由有意义的关键效果描述：进入功能看显露，关闭面板看消失，内容变化看更新；具体条件结果不必相同。
未完成的 Background 操作可使用 Bluetooth 页共享导航中的 el32，recorded 不再被等同于控件不可用。
同 Region 的已归因 updated 变化可用于到达新操作的状态；从已有事件派生，不新增模型字段。

上次监督结论已纠正：原输入先提出 identity，Operation Reviewer 返回 result 后，框架实际仍只批准 identity；
o30 保持 recorded，不安排重复点击 Bluetooth。没有发生该结果复用污染。后续监督应先看框架处理后的记录，
已丢弃的提案不当作实际动作；真正危险的 GUI 动作仍须执行前检查。
回放证据：artifacts/settings_review_replay_20260907；修复后的任务卡与同区块路线见 artifacts/settings_traversal_fix_20260907。
70 项相关离线检查通过（1.94秒），未因此宣称新鲜实机遍历成功。旧 CLI 清理未提交，下面代码定位中的旧原型条目待清理任务恢复时更新。

### 2026-09-07 Settings 续跑记录

基于86ad3c30从旧账本恢复，16次真实Luna调用、1个新GUI动作。Luna直接使用当前el32从Bluetooth进入Background，
没有绕回Network，共享绑定修复取得实机正例。随后region_effects在身份合并前将共享r1误认为after不存在，
两份报告被拒绝，a2保存为uncertain。停止后已补上原始清单ref到临时ID的对应，33项相关离线检查通过；
尚未重新验证修正后的实机结算，不能写为完整遍历成功。Add Picture提案未执行，VM已soft stop。
证据与逐步监督：artifacts/runs/settings_luna_resume_86ad3c30_20260907/supervisor/summary.md。

### 2026-09-06 基础接线


已接通：主 Agent 的 region_effects 将变化分为 action/external/uncertain，清单行在运行期解析为 ref；
显隐集合差不再自动填入动作边。updated 与独立事件进入已有 events；身份合并保持现有机制。
Luna 可用 next_operation_ref 改选当前可见的开放待办，旧待办保留；同区块历史结果进入既有近期上下文。
这些字段已有消费者，不增加逐步反思调用或持久任务类型。

已接通：账本中的零动作操作可进入 function_inventory；生成器通过 --region-ledger 生成 Region 目标、
条件和共同后续；同一采集 CLI 的 --region-ledger 模式由 Agent 实时选分支，允许未知中间 State。
图关系提供候选历史指导，不能当成当前情境已经验证的自动执行路线。
条件截图、目标完成截图、实际 primitive、分支和最后一次结果核对都使用原轨迹 writer 落盘。

新模式目前是单应用；失去目标前景时保留 partial，不包含跨应用业务动作、外部前景自动恢复或 seed/delta setup。
旧 M13 State/recipe 模式和旧 FunctionCollectionCoordinator/FunctionInstructionDesigner 辅助 API 仍保留，
其限制不应误写成新 Region 模式的要求。原历史图不回写，也不宣称旧自动生成边全部满足新因果合同。

验证仅为离线：141 项直接相关测试通过，原 CLI 与 writer 脚本通过；另强化原子提交用例后 9 项通过。
真实 Settings 保存账本可导出 52 个 Region / 330 个操作并通过新 CLI validate-only；没有 API/VM/GUI 动作。
尚未验收：真实 Luna 归因准确率、经验驱动效率、完整 Gmail 两条分支、跨应用泛化和论文比较实验。

后续相关代码修改必须同步更新本文流程、完整例子、代码位置与证据状态；维护要求已写入 AGENTS.md。
保持最小可用实现，不因要投 ICLR 就把开发变成生产级防御工程，也不把离线结果说成实机成功。

## 10. 相关当前模块文档

- [页面清点与探索范围](modules/explore_kernel/page_inventory.md)
- [Region 和操作身份](modules/explore_kernel/region_identity.md)
- [位置与页面状态](modules/explore_kernel/location.md)
- [Region 关系与路线](modules/explore_kernel/region_routing_design.md)
- [探索任务与调度](modules/explore_kernel/operation_tasks.md)
- [Luna 上下文及 Region memory](modules/explore_kernel/agent_context.md)
- [现役 M13 采集](modules/visual_collection.md)
- [Region-function 离线原型](modules/region_function_collection_research.md)

本轮完成代码接线和离线验证；没有运行 VM、模型 API 或 GUI 实验，不据此新增 live 成功声明。

2026-09-11：成本试验把Luna观察候选与框架确定性引用维护分开，代码位于tools/luna_inventory_probe.py，未接正式Region遍历。框架的结构重复/控件增长提示只是候选证据，不替代模型视觉边界判断；观察器没有Operation、State或因果边。已恢复本地Luna配置，不能把缩减观察工作量的token当完整方法链收益。

2026-09-11：正式ExplorationRuntime增加显式defer_partition_review策略。真实当前容器/控件可先登记，整页分区预审延后并保存质量gap，其他身份及动作结果审核保留。既有region_refinement负责后续细化，不添加按应用名自动拆分规则；这只是当前可用性试运行，不改变包含、因果和同屏关系的区别，也不授予未确认的共享身份。

2026-09-11独立实验：core/evidence_explore及run_evidence_explore.py不经过旧State/Task链；当前图和动作证据不可变，Region/自然功能记录与跨帧候选关系单独校验。VLC七步例子中参数下拉和一次Native→Custom条件观察已真实产生相似记录，滚动与Audio替换现已实测并输出关系候选；记录仍有漏项与时序误判，不能算规范共享身份验收，后续就地采集未执行。本版没有规范化身份合并，不把同屏和因果混为一谈；详细代码/边界见modules/evidence_explore.md。

2026-09-11：新内核panorama.py/panorama_runtime.py及run_region_panorama.py实现区块全景工具，控件地址为地图内像素框+来源，执行用当前图测视口再定位，不以滚动次数当位置。它是单区块已知目标查找原语，不建立无证据跨区因果边，尚未自动接入Region路线与指令采集；VLC一目标拒绝、另一目标定位投递已记录。

## 2026-09-11 API 观察 harness 的当前接线边界

`gui_rewalk/src/core/evidence_explore/observation_harness.py` 提供独立冻结截图的局部观察及控件/Region key 增量登记；`gui_rewalk/run_observation_harness.py` 是有限API试验入口。它可以在同一草稿重写区块成员和 parent，但未做旧图拆分迁移、身份合并或 GUI 跳转边更新；不能将 schema/引用检查通过当功能区域正确。保存帧结果不写入真实动作账本。VLC/Gmail 等既有因果遍历例子的目标设计保持不变，实机共享预算、回执与变化后重定位接线尚未实现。两应用局部定位开发对照和成本见 `api_harness_20260911/REPORT.md`，非完整遍历验收。

2026-09-12联合VLC试验：现有EvidenceRuntime首次登记三个设置分类、RouteRuntime回访，并伴随locate_region子控件语义锚点检查。导航跨分类复用候选和内容替换拒绝有实际截图；底栏仍漏检。最后Cancel在视觉拒绝后由Luna定位并实际退出，组合试验完成；共12请求/12点击，非全图自主遍历。区块匹配未接自动canonical身份归并，仍不将同屏包含当因果边。Tools当前动作/远期目标混淆及登记错误阻塞回执均留原始证据，后者只有实验本地分离恢复，未成为默认修复。详见modules/evidence_revisit.md及combined_region_traversal_20260911/REPORT.md。

2026-09-12正式混合接线：`evidence_explore/hybrid.py` 将显式KnownRoute与EvidenceRuntime接在同一EvidenceStore和调用/动作预算中；`region_revisit.py` 保存期待页面的Region子控件视觉候选，不据名称/相似外观升级canonical身份。路线失败不继续探索，区域候选异常不覆盖输入层/控件动作门禁。混合模式本地回执隔离保留原回复来源，不把未投递动作或远期目标写成成功。52项离线检查及新版正式CLI菜单短段实机2请求/2动作通过，最终无pending；完整跨Region自动规划、共享身份与分支任务采集仍未因此完成。

2026-09-12 settings实跑的Input滚动出现额外缓存策略变化：同一轮既露出HTTP代理字段，也把Custom变为Normal；取消后重开已核对恢复Custom。不能将此边标成“纯观察且无状态副作用”，也不能把未计划的缓存变化当业务任务成功。当前区域位置/滚动落点检查不足以保证滚动只改变视口；原图/动作/值变化及人工恢复核验完整保留。该轮root参与调度和补登记，后续自主评估须按用户最新要求隔离干预。


### 2026-09-19 无Page身份的逐步探索对照

Clock实验以一次观察的可交互Region集合和实际控件动作记录关系；已执行r0001.c0001→r0003菜单，背景r0002不生成共现跳转或逆向边。观察ID不是Page/State身份。冻结源码副本与阶段驱动器已离线重放3调用/1动作；真实适配器接线、长期复用/路由未完成，正式runtime未修改。代码/边界见experiments/clock_manual_20260919/stepwise_flow.py与FLOW_BASELINE.md。

### 2026-09-22 采集定位与结果分开验证

collection_visual_guard.py 从冻结图外观定位当前控件，再映射点击区域核对 Luna 坐标；function_collection_research.py 显式启用后将错位提议留作证据、纠正后才投递，未知/失配目标可重新视觉确认。动作意图与实际观察分开，矛盾success不提交。未修改遍历、图身份或关系。Gmail月报if/else示例及目标不变：控件定位通过仍不能代替条件判断、分支效果和共同后续验收。本轮仅Settings两项参数两轮实机通过，非该Gmail示例验收；详见采集模块及本轮报告。

2026-09-23 临时逐步遍历器：外观共享可被后续实际功能差异推翻。更新步报告来源分离，程序建立独立未探索控件，仅归入当次实测动作；同一开关值变化和返回不同来源不拆分。实现与验证边界见 [共享区块行为分离](modules/stepwise_region_identity.md)。不改变主框架与采集边界。

2026-09-24 复制遍历器候选：入口去向被其他入口的直接执行证据覆盖时，可在累计复核中免重复探索；原入口不记已执行、不判等价，不用于虚增功能验证。空列表中央添加 vs 顶部添加为说明案例，不是应用专用规则。实现coverage_exemption/task_result_review；发现及正常更新发布、调度、功能提取、前置任务已接线；25项聚焦及2次保存帧模型验证、隔离提交通过，未部署或实机执行。Gmail等组合目标仍不得用打开入口替代业务条件满足。

部分共享候选（2026-09-24）：Clock 在 Timer 上的“＋”若实测打开 New Timer，分离当前工具栏及该按钮；独立稳定的导航控件可以继续引用旧行为证据。来源分离在 region_behavior_split.py，成员关系在 shared_controls.py，任务由 shared_controls.synchronize_tasks 根据已确认控件关系自动关联；任务清点仅补非共享控件，不让模型重复选择共享依据。本地身份/位置/执行/当前参数值不继承，历史任务知识保留来源引用。仅保存帧及离线验证，未部署。

2026-09-24 复制遍历器共享纠错：独立action_evidence及shared_control_review模块接入原Runner与历史任务清点；共享冲突先撤回派生支持，再核对保留或解除。成员本地动作不迁移，错误继承任务不继续执行；经验共享不是本地业务成功。未改变Gmail组合任务及采集边界，验证范围见stepwise_region_identity对应节。

2026-09-24 前景历史匹配候选：history_matching集中去重计票及文字/图片身份线索，foreground_scope接发现/更新同轮范围；背景与遮挡控件不参与确认票数。票数不能替代行为上下文或强制同屏仅一身份，首次范围未定只给候选位置，回复后重算。Gmail if/else目标与采集边界不变；保存帧验证不代表新GUI执行，具体证据见stepwise_region_identity前景历史匹配节。

2026-09-24 关系规划规则：任务清点允许用界面和已有知识判断关系并省略常识验证，推断记在reason；事实仍按观察来源与条件登记。第三步用真实动作后观察核对原问题，不扩大成组合穷举。第一步task_proposal及历史清点复用独立参数关系prompt，第二步不变。Gmail if/else等组合任务仍须观察实际业务条件与结果，不能用关系推断替代分支条件或最终成功证据。保存帧范围见stepwise_debug_loop对应节。

2026-09-24 任务生成提示落实发现优先：明确导航用途不免除未知应用内功能内容的发现；已见区块内部常识效果可record，具体未知仍可探索，不穷举同类数据。主任务与参数关系提示同步；原有Gmail条件采集示例、任务接口及旧记录未改变。保存帧验证边界见stepwise_region_identity“任务生成先发现功能内容”。

2026-09-25 复制遍历器候选：准备状态与业务完成分开，task_prerequisites 以本次目标可用观察结算成对准备，父任务仍待办；常识用途仅记录，未知功能内容仍探索。4项原生保存帧已登记，非新GUI执行；原运行未部署。当前合同见 stepwise_debug_loop。Gmail条件任务与下游采集验收不变。

2026-09-29 复制遍历器等价边界：region_tasks.attach新任务候选只取非equivalent真实义务，不因成员可见而替换代表控件。原对象证据结算和单向coverage不变，成员不伪造执行。保存帧选择已核验，未执行或结算新动作；见stepwise_debug_loop末节。Gmail条件任务及下游采集验收不变。


2026-10-02 首次对象/运行态的内容发现：复制遍历器普通任务提示在创建、启动或选择确认将产生尚未观察的交互结构时，保留一个代表状态的发现目标。仅为数值/文案/同类实例变化不重复创建，明确效果仍可record；旧任务结束条件不扩大成用户权限。旧完整清单不自动重审，已有task_inventory.review可承接监督覆盖复核。真实后续观察前不生成新Region/控件、不算业务成功。Gmail月报if/else仍必须实际观察分支条件并验证业务结果，不能以建立任务替代。代码入口region_tasks.plan_request/commit_plan，历史复核用historical_inventory.region_request或实际检查点正常assemble_current_context；保存帧及失败边界见stepwise_debug_loop。
