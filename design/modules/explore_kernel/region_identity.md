# 区块身份

2026-09-18：Region身份回复先在账本副本通过既有引用、关系组合及合并/父子不变量检查，才调用依赖它的Operation Reviewer；副本结果不提交，正式操作身份仍需原审核。候选输入增加由已有祖先链派生的`identity_constraints.cannot_reuse_region_refs`，保留父区作为上下文候选，不能将子区折叠为父区。原Clock `calls/0007`与`clock2/calls/0013`离线回放均提前拒绝非法提案，避免各一次无效后续审核；原次数/结算不改。77项相关测试及1项合法片段合并回归通过；真实Luna是否据此正确保留子区、继续探索仍待新批验证。

2026-09-10：父容器或内容槽相同只支持召回。不同具体功能字段组仍保持独立，不能以宽泛父级业务目标替代子区功能；数据列表仅更换成员且浏览职责/结构一致时允许Region复用，具体对象的操作另审。保存帧反例先将Paper/Device内容区误合并，修正后保留共同父容器/页签/操作区并将两个字段组分开；Files网格正例仍通过。旧错误判定保留，不改写为通过。

2026-09-10：候选标签可用组内共同描述词归一化补足改称召回，详见knowledge_retrieval。审核中无source_transition不使用trigger_or_result；边界明确不同可用separate/different_component及none或uncertain因果，身份也不明时三项皆uncertain。反馈明确字段组合，避免仅修改causal_relation而反复重审。Writer保存帧旧版三轮关系错误保留，修正后一次身份审核复用属性窗口父容器、页签和按钮区，Paper/Device主体区分开；仅为保存帧开发对照。

2026-09-10：普通身份复用仍不静默重分配旧owner；新增独立的可选分区修正提议，复用本Region审核角色判断提取边界，再用既有Operation角色审核配对。只对明确来源和选定控件更新工作图，旧父区保留、原证据不改；不新增每轮审核。详见[分区修正](region_refinement.md)。

2026-09-10：Region候选按不同控件锚点一对一比较，重复名称/同控件多动作不重复计票。多控件候选需至少2个匹配、覆盖较大一侧至少一半；单控件可用1个匹配。分数为5%区块名、20%区块/父容器说明、75%归一化锚点，不再让同名“导航栏”或单个重叠操作直接通过。邻居优先在候选截断前应用；最终视觉审核及明确引用流程不变。保存VLC例中，同一菜单换通用名仍召回，播放器菜单与首选项分类同名不通过，Tools r111仍召回r64。详见knowledge_retrieval.md。

2026-09-09：身份审核输入携带本次父区及子区引用。子区可以是父容器内的功能组，不要求拥有整个父窗口。
父子关系不等于身份相同，不能以reconstructing_fragment把不同子功能合回父区。程序拒绝祖先/后代身份塌缩。
完整实例合并时孩子重指向保留实例；被合并控件的观察按记录顺序保留，原参数/动作证据不改写。

主 Agent、Element/Region/Operation Reviewer 共用三轮失败预算（首次失败加两次纠正）。错误直接交给能修改它的角色；措辞、排序、任务切换和刷新截图不清零。报告通过检查才结束纠正。耗尽后保留候选、截图和 gap，不再审核同页冲突；位置可信时可沿已有绑定探索其他内容，否则 partial 停止。详见 [报告纠正流程](report_correction_flow.md)。

## 问题

同一个顶部栏、底部导航或工具区会出现在多个页面。若每页重复登记，会重复派发操作；错误合并又会把功能不同的区块混在一起。

## 当前方法

2026-09-09：比较候选与真实动作来源可能是不同 Region。`separate + different_component/member_or_subregion`
不再强制 causal_relation=none；与比较候选不同，不排除 source_transition 中另一操作显露当前组件。
显露仍逐项验证真实 Attempt、来源/目标 State、Operation/来源 Region和目标区块存在性；来源无效不能补边。
reuse仍不得同时声明跨组件显露，trigger_or_result仍要求明确方向；没有共享依据仍不合并 Operation。
Android Timer原0033/0034两份回复已在新校验下原样离线通过，无新模型/GUI；这不替代视觉准确性评估。

实现分为两处：`region_review.py` 从 ledger 和保存截图准备候选，调用现有 Agent 的身份审核接口，
校验结果并返回处理后的 ledger；`regions.py` 负责引用与已批准身份的确定性合并。
`runtime.py` 只决定何时调用和接受返回账本，不把整个运行对象传入审核模块。
审核条件、候选排序和批量方式沿用现有机制；非法回复向对应 Reviewer 反馈，共享报告失败预算。
Reviewer Prompt 明确允许主 Agent 省略无关变化，不要求补齐整屏；仅审核已提供区块，真实进入动作不单独证明因果。
显露补充仍须前后图和动作支持；明确外部/不确定归因不通过补漏覆盖。此说明未增加字段或调用。
对应测试是 `tests/test_explore_region_review.py` 与 `tests/test_explore_regions.py`。
同一page_report内，非空Element ref必须唯一；直接引用与Reviewer补出的引用统一检查，重复则拒绝、不写入合并结果。
Element Reviewer区分同类与同一个可交互落点，不将具体控件复用到多控件概括上；同类覆盖不合并Element身份。

主 Agent仍逐帧登记：引用旧 Region 补元素，或提出新区块。普通调查期间先累计本 State 尚未复核的新区块，
在 survey_complete=true 时统一送入现有 Region Reviewer，不只取完成当轮的 new_region_ids。
已完成 State 后续又出现新区块时，同样在该轮处理；只补旧 Region 的元素不重审 Region 身份。
重启定位会提前批量处理当前 State 已积累的全部待审区块，不要求当轮再次逐项重报或完成整页调查。
这些区块已有观察帧和操作目录；仍由现有 Reviewer 看保存帧决定身份。历史区块完成身份审核不表示其控件
在当前帧全部可交互，执行仍依赖当前 owner 和最新截图。其他 State 的待审核记录不进入本批。

待审核清单从既有 ledger.events 的 region_review_observed / region_review_batch_finished 推导。
观察事件保存新 Region 编号、本帧实际报告的 Operation 编号、已有截图引用、明确旧 Region 提示和该轮已结算 Attempt 引用；
事件随 checkpoint 保存，读取账本后仍能找回早先候选。batch_finished 只表示这批尝试已处理，不宣称模型判断必然正确。
无旧候选且无来源关系可审时不调用模型；审核失败/不确定仍保留独立记录与既有问题事件，不强行共享。
Region 合并会同步改写 ActionAttempt、Transition 和 HistoryItem 中引用被合并 Region 的 owner；HistoryItem
按数据记录的 `parameters` 字段访问，不按字典 `.get()` 读取。2026-09-04 的 Clock live 在第3动作后真实
触发了旧访问错误，修复后从原账本续跑未再出现。

1. 先按已验证图邻居、同一 Page 早期 State、其余全局 State 建立召回顺序，再用 Region 名称、摘要和本地 Operation
   的精确结构做文字 shortlist。每个当前 Region 最多保留两个候选，整轮候选最多来自两个代表 State；
   操作名称只用于候选排序，不再按特定操作词过滤。候选入选不代表 Region 或 Operation 相同。
   同一个 canonical Region 若在多个候选 State 都有 occurrence，最终只发送一个 Variant，并按已选 State 的
   邻居/同 Page 优先级选择，而不让编号更早的跨 Page Variant 在同分时覆盖它。
   当前区块首次报告的 Attempt 若有对应真实 Transition，该 Operation 的来源 Region/Occurrence 不受上述
   两个代表 State 上限约束。每个当前区块分别携带 source_transition 与 before_image，不把整批都归给最后一条边；
   来源区块已在本批当前侧时不重复列作旧候选。来源关系用于显露因果判断，不表示来源与结果应复用。
   观察动作没有对应 Transition 时保留 source_transition=null，不能借更早的进入动作冒充其直接来源。
   主 Agent 未在 region_effects 中列出的区块仍保留该真实来源供 Reviewer 看图补充显露判断；
   明确 external/uncertain 的区块不提供此补充来源。未报告不等于外部事件，来源存在也不自动证明因果。
   主 Agent在新 State 清单中明确填写的旧 region_ref 同样是必带候选，不受文字分数、每区块数量或两个
   代表 State 的上限过滤。文字检索只补充其他候选，不作为阻塞清单或判定身份的门禁。
   明确引用只表示待核对，仍由 Reviewer 看图决定是否复用；历史截图缺失时记录具体候选/State 的
   region_candidate_screenshot_unavailable，不凭编号或文字自动合并。
   已知 State 中补报新区块时，该 State 原有且不在本批待审侧的 Region 同样是必带候选；
   跨 State shortlist 仍只补充其他 State，不再让其排除同 State 的正确旧候选。本批新区块不互作旧候选。
2. 输入本批区块实际出现过的完整截图、shortlist 候选的代表截图，以及两边名称、Variant 编号和摘要。
   当前 Region 的 images 指明其观察图，每条 Operation 的 images 指明该操作可见的图；图1只是最新帧，不代表整批同时可见。
   从后向前选择足以覆盖待审区块和已见操作的观察帧；完全相同的图片只传一次，不拼接长图，也不复制历史全图。
   当前侧列这批保存帧观察到的 ElementOperation/RegionOperation；候选侧列该 Region 已登记的完整 canonical
   Operation 目录，并标注每项是否在代表截图 Variant 中可见。候选操作若在该代表 State 有一次真实成功的 `execute`，清单另附该次前后图结算出的简短
   `verified_result`；没有该 State 的真实结果就留空。文字 shortlist 只控制 Reviewer 看什么，不自行决定 Region 身份。
3. 每个当前区块先报告 `component_relation` 和独立的 `causal_relation`，再得到 `reuse / separate / uncertain`：一个完整当前组件用
   `same_complete_component`；共同重构旧完整组件的多个当前片段都用 `reconstructing_fragment`；单个成员/子区域、
   触发器/结果表面、不同组件和证据不足分别使用其明确关系。选择 `reuse` 时另外列出确实共享的当前/已知本地
   Operation 配对，并为每对选择 `reuse_level=identity|result`。
4. 只有模型明确 `reuse` 才复用既有 `region_ref`；证据不足保持独立。区块复用本身不自动复用其中的操作。

Region 合并会同步改写 ActionAttempt、Transition 和派生 History 参数中的 Region owner_ref，避免先调查滚动、后复用 Region 时留下临时编号；原始截图与原始模型日志不改写。

上述稳定判断原则与输出合同放在该角色的系统提示中；每轮用户消息只携带本次区块表和截图，避免重复静态规则。
Reviewer 与主 Agent 都把 Region 定义为共享局部上下文和变化边界的功能组件。控件数量、面积、边框和留白都不是硬判据；
单按钮功能表面可以是完整 Region。“成员”只在它确实依属更大可见组件且没有独立变化边界时才否决；例如无独立边界的重复列表项仍只是列表 Region 的 Element。
Region 名称中的展开、折叠、选中或具体数据只描述 Variant，不证明新的全局身份。
普通展开只显示更多被动内容时遵守该原则；代表项展开若显露一组共同出现/消失、服务于该对象并可独立完成用户任务的
完整任务上下文，即使内联显示，也属于新的结果 Region。Reviewer 应结合 `source_transition` 返回
`separate / trigger_or_result / known_operation_reveals_current`，来源列表与结果编辑表面的 Operation 不配对。
`source_transition` 本身不决定合并或分开。新内容可与来源组件同时存在：新内容有独立交互上下文和可见性边界时，
登记独立结果 Region，同时保留仍存在的来源 Region；只有同一组件边界内的成员或状态变化才复用 Variant。
不按屏幕位置、控件类型或动作名称决定边界。

位置、形状、主题、相似布局和部分同名操作都不能单独证明相同。多个当前小区块若只是把一个已知完整组件拆开，
只有它们合起来确实重构该完整组件时才可共同复用；单个片段不能借此复用完整组件，代码随后合并合法组的 occurrence。
同一候选 Region 的合法结构只能是一个 `same_complete_component`，或至少两个全部为 `reconstructing_fragment` 的当前区块；
混合关系、单片重构或多个完整当前组件会拒绝整批落账，并把具体合同错误交给 Reviewer 在共享预算内纠正。耗尽时不做半批身份合并，保留未解决记录。
runtime 不再追加第二个窄审计调用。Reviewer 在同一次完整截图判断中同时报告因果方向：Region 复用要求
`causal_relation=none`；`trigger_or_result` 必须 `separate` 并明确是候选 Operation 显露当前表面，还是反向显露。
非因果的 `separate` 必须使用 `none`，不确定结论的两个关系字段都必须为 `uncertain`。这些组合由 runtime 原子校验，
非法整批带具体错误在共享预算内纠正；耗尽时不应用本批合并。
若方向是进入当前 State 的已验证来源 Operation 显露当前 Region，runtime 还会核对 Reviewer 输入中的精确
Transition 与当前前景 Region 集合，再把该 Region 记到 Transition；Reviewer 不需要也不能在页面清点前猜新编号。
该记录只表达“这个真实操作使该 Region 可见”，不表示目标 Region 的内部 Operation 已验证。
同批可以对应多条已有 Transition，每个区块仍独立校验其来源。此改动不新增同 State 调查滚动的 Transition，
也不改变既有 State 集合差推导 Region 显隐的规则；保留滚动观察证据不等于已创建滚动显露边。
全局导航/应用栏可以在复用同一区块时新增页面上下文操作；但不同主要功能对象的内容区不能因共用空状态/添加模板而合并。
反过来，相同功能对象也不证明区块相同：概览或入口卡片与详情、编辑面板、弹层属于不同交互表面，
按钮或子区域与完整栏、容器也不是同一组件。它们之间的关联由真实动作连接表达，不由 Region 身份合并表达。
候选操作的 `verified_result` 只证明点击后的因果效果，不能反过来证明触发器 Region 与被显露的菜单、详情或弹层是同一组件。

## 操作复用

账本把三层事实分开：

- `Region` 是跨 Page/State 的全局功能组件身份；
- `RegionVariant` 是该 Region 在一个具体可见状态中的结构形态；
- `Element` 属于一个 Variant，保存明确交互落点及它的 ElementOperation；
- 本地 `Operation` 的 owner 是 Element 或 Region 整体，保存该处自己的任务、状态、方向、结果和来源 occurrence；
- `CanonicalOperation` 属于 Region，表示多个 Variant 本地 Operation 共同的命令身份。

每个新 occurrence 初始建立自己的 Variant 和本地 Operation。区块确认相同后，仍只有同一次完整截图判断明确配对、且代码校验
`scope + action + direction` 一致的本地 Operation 才可指向同一个 `CanonicalOperation`；ElementOperation 不与 RegionOperation 配对。具体样本名与代表名可以不同，例如
“5:00 PM 闹钟的展开箭头”可与“任一闹钟的展开箭头”共享命令身份；canonical 名称保留已知代表，框架不按文字相似度猜测。
未配对的页面专属菜单、添加或设置入口继续拥有不同 canonical 身份。

Reviewer 配对跨不同 Page 的操作时，从两张完整截图、选中标签、周围对象、动作和直接效果判断功能是否相同，
不比较 target 的自由文本是否完全一致。肯定或大概率相同时配对；有怀疑时不配对，让两边本地任务分别探索。
相同名称或图标不证明共享；不同名称也不自动证明不同。所有操作都从完整截图判断功能对象、当前职责和直接效果。
runtime 只校验 Reviewer 给出的引用、owner scope、动作和 direction，不再用名称字符串覆盖语义结论。
Region reuse 与同一 Page 中的 Variant binding 不受影响；Page只提供当前功能对象的上下文，不成为 Operation owner。

主 Agent 只提交当前 Variant 的本地 Operation 事实；两边不同的 provisional `canonical_operation_ref` 只表示框架
尚未合并，不能作为拒绝共享的理由。Region Reviewer 按动作、作用对象和直接效果填写 `shared_operations` 候选；
不按操作名称建立候选例外；效果依赖来源状态或导航栈时，必须确认两边当前职责和直接效果一致。
若本批至少有一个候选，独立 Operation Reviewer用同一组完整截图一次批量复核所有复用 Region 的候选；
每对的 current_images 指向该操作真正可见的保存帧，known_image 指向旧候选帧，不能把最新一帧当作所有控件的当前图。它不判断
Region身份，逐对输出same/different/uncertain。只有same落账，其他结论保留本地Operation；整批无候选则不调用。
runtime只校验明确配对和结构引用，不再按singleton或精确字符串签名自动补配。
每个当前本地 Operation 正常只出现一次。若 Reviewer 对完全相同的当前/旧 Operation 配对重复填写
`identity` 与 `result`，runtime 确定性收束为一条并保留 `result`，因为结果复用已经包含身份复用；
同一当前 Operation 指向不同旧 Operation 仍是语义冲突，runtime 拒绝并把具体编号交回 Reviewer 重报。

若多个 `reconstructing_fragment` 位于同一 State 并复用同一 Region，runtime 把其 occurrence 与本地 Operation 移入该
State 的同一个 RegionVariant。两个片段里的本地 Operation 若已由 Reviewer 配到同一 `CanonicalOperation`，且待删除项
尚无真实 ActionAttempt，则只保留一个代表本地 Operation、合并来源 occurrence，并删除重复任务；不同 canonical 身份的
状态专属操作继续留在该 Variant。不同 State 的 Variant 不做这种物理收束，只共享 canonical 命令身份。

若 Reviewer 明确以 `same_complete_component` 复用同 State 原有 Region，保留一个 occurrence，并改写
Element/Operation 的来源引用。只处理本次被审核 Variant 所在的 State，不把本帧判断传播到其他 State；
`separate/uncertain` 不收束，片段重构沿用原规则。删除已确认重复且没有真实 Attempt 的 Operation 后，
若其 Element 已无 Operation，一并移除这个空 Element；不借此清理其他历史对象。

`reuse_level=identity` 只共享命令身份。两个 Variant 的本地 Operation 都保留；一边 `verified` 后，调度器把另一边尚未执行的
任务终止为 `done`，并将该局部 Operation 标成 `recorded`，但不复制结果。这保证同一 canonical 功能只真实执行一次，
同时不把另一 Variant 的直接效果伪装成已验证。若 canonical 中还没有任何真实验证，各局部任务仍保持原状态；先失败或延期
不会关闭其他入口。

命令身份按完整截图中的“动作 + 作用对象 + 直接效果”判断，不按控件原文、通用交互模板或操作词表判断。
框架不按相同 Page、Element 名或 Operation 文本自动关闭不同 canonical 的任务；只有已确认共享的 canonical binding
才按既有结算规则关闭重复任务。

`reuse_level=result` 允许当前本地 Operation 直接继承候选 Variant 的已验证结果并关闭本地任务。它要求候选
`verified_result` 非空，而且 Reviewer 必须从两张完整截图、控件职责、选中状态、当前步骤和前景层级确认直接效果不可能因
Variant 改变。候选没有真实结果时，runtime 确定性降级为 `identity`；不会撤销 Region 复用，也不会把没有证据的结果写成已验证。
这条视觉充分证据路径用于稳定全局导航、翻月、Cancel 等直接职责明确的操作，不要求当前 Variant 再点击一次。

同一控件在状态推进后直接职责改变时，如日期格先选开始日期、再选结束日期，Region 可以复用，但两个 Operation 不配对。
同一顶栏的加号在 World 页面添加世界时钟、在 Timer 页面添加计时器时也必须分开。模态层后的背景导航即使仍可见，也不是
当前可直接接收交互的 Operation；Reviewer 不应把它作为结果可复用项。动作类型不一致时 runtime 只忽略该 Operation 配对，
不撤销整个 Region 判断。

2026-09-01 的 commit `d3022978` fresh live 证明原合并 Reviewer 会过度相信主 Agent target：Alarms截图中的
`+` 被错写为“添加世界时钟”，随后与 World `+` 以result级别共享；同轮Stopwatch已不再虚构不存在的 `+`。
在该错误输入和两张完整截图上，仅加强原Region Prompt为0/3正确，中和错误hint为1/3；独立单对Operation审核
为3/3，正式批量六对Operation审核也3/3拒绝错误`+`并保留四个导航与菜单。该结果支持拆分审核，但仍只是
saved-frame API证据。新接线的定点fresh live中首次Alarms/Stopwatch/Timer各触发一次批量Operation审核，返回
已知World不重审；Alarms本轮漏报顶部`+`，所以live只验证接线和调用门槛，尚未直接复现并拒绝错误`+`候选。
同一原图随后resume并运行到terminal gaps：一个Timer State中后来增量补报的`co167`与既有`co25`同为
`1 m 预设倒计时`，但已知State增量清点没有重新进入Region身份批次，因而也没有触发Operation Reviewer，
最终bundle以同State同Region入口歧义失败。这说明“已知Region不重审”不能等同于“新Operation不审核”。

主 Agent 每轮只看到当前 occurrence 所属 Variant 中当前可见的 Element 和 Region Operation，并使用稳定
`CanonicalOperation` 编号；Region Reviewer 的候选侧另看该 Region 的完整 canonical Operation 目录，避免选中
一个代表 Variant 后漏掉其他 Variant 已发现的操作。目录项不代表控件在候选截图中可见。
bundle 按 `CanonicalOperation` 投影入口，同时保留
`variant_operation_refs` 追溯各 State 的本地证据。

### 持久化边界

`RegionVariant` 是局部结构身份，不保存名称、摘要、截图、bbox、动态值或完整界面描述。v5 磁盘记录只含
`variant_id/region_id`；Occurrence、Element 和 Operation 各自保存所属 Variant/Region 的父引用，真实动作证据仍在
ActionAttempt 和 State screenshot 中。运行时需要的 `occurrence_ids/element_ids/operation_ids` 以及 Region 和
CanonicalOperation 的反向集合由 loader 统一重建，避免合并后多份反向列表漂移。Variant 仍不可删除：它隔离不同
State 中的本地 Operation 可用性和结果，防止 Running 的 Pause 与 Paused 的 Resume 等职责被扁平合并。

## 程序视觉边界

局部图标或 Region crop 只能作为已验证入口的重定位证据，不能决定跨页 Region、Variant 或 Operation 身份。
相同三点图标只说明局部外观相同；身份与结果复用都由 Region Reviewer 比较完整截图和文字合同。
旧的双边 before/after 程序比较只保留为已有待验证候选的兼容核对路径，不再是新 canonical Operation 身份的唯一入口。
锚点重定位仍 fail-closed：重复图标、低纹理、状态栏、低分、多峰、尺度不一致都返回未匹配。

2026-08-22 的桌面 Clock 真实运行暴露了同一区块内的语义过度合并：New Alarm 与 New Timer 的 Dialog Header 可以复用，
但 Reviewer 曾把两边同名 `Add` 一并映射到创建闹钟的 canonical Operation。修正后的正式 Prompt 在同一对保存完整截图上
连续三次都复用 Header、只配对 Cancel，并拒绝配对两个 Add。该截图重放证明了判断边界，不等于修改后完整桌面遍历验收。
随后另一轮桌面运行又把空列表及其入口与点击后出现的对话框误判为重构。当前单次 Reviewer 合同把表面边界与显露因果
分开；在该故障 run 的两张保存完整截图上连续三次都返回 `separate / trigger_or_result /
known_operation_reveals_current`。这是保存截图合同证据，不等于修改后完整遍历验收。

2026-08-22 的移动 Clock 真实试跑中，Qwen 在菜单截图里把 Top App Bar、背景 Alarm List、FAB 和底部导航复用为原 Region，
同时保持 Overflow Menu 独立；在展开截图里把“展开 Work 条目”和“其余折叠条目”都判为 Alarm List 的
`reconstructing_fragment`。账本随后产生一次 `region_variants_coalesced` 和一次 `variant_operations_merged`，
并通过 `(Region, State)` Variant 唯一性、Variant 内 canonical Operation 唯一性及 owner 引用审计。该 run 后续仍为 partial。

最新主 Agent Prompt 依据 32 个 App、33 张保存截图的离线 taxonomy 改用上述完整表面判定式，并加入主要内容槽、稳定命名和
输出前归并。三次保存截图探针中，Clock 首屏均把浮动按钮归回主内容，Pro Expense 均保留独立底部面板；Chrome 输出
3、3、4 个 Region。移动展开列表最终有 2/3 输出单一稳定 `Alarm List`，另 1/3 仍拆成展开成员与折叠列表，而且该两图
上下文中的 Add 按钮仍 3/3 被单列。该结果证明 Prompt 改善但仍有不稳定边界，不能写成准确合并或 live 验收。

2026-08-24 的桌面 Clock Luna 短跑在 6 个动作时主动停止：World 与 Alarms 首次比较时，Reviewer 先显式配对导航和菜单、
并正确拒绝把 Add World Clock 与 Add Alarm 共享；但同一 canonical 应用栏的候选 occurrence 在同分时选到了较早的 World
Variant，而不是同 Page 的 Alarms Variant。Reviewer 因而看不到旧 Add Alarm，运行连续三次打开 New Alarm 并创建两个闹钟。
shortlist 现已在同一 canonical Region 的历史 occurrence 间优先已选的邻居/同 Page State，离线回归通过。修复后的
Clock 短跑在 World 添加流程中复用了同 Page 对话框 Variant，并从新 World State 直接执行当前本地 Alarms binding、没有
route 回旧 State；但进入 New Alarm 后陷入 Ring Duration 菜单的三次无效 recover，在到达两闹钟前停止。因此通用当前 State
binding 已有 live 正例，Alarm Add 的精确去重仍未 live 验收。

## 2026-09-08 反馈检查

审核结构/引用错误给出具体候选或操作对；审核应用后重复 el 不证明两个按钮相同。底层合并失败显示对应引用和值，不改变复用条件。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。
