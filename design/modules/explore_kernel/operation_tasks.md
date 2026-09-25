# 内部 Operation Task 与探索焦点

2026-09-18 V2：正式恢复可将当前本地、显式co引用且从未尝试的record绑定，按模型新适用依据交给既有`_accept_operation`/`_ensure_operation_task`。其他来源有失败、延期、成功或尝试证据时不走此窄更新。实际点击结算仍按真实owner入账，不把Back或已知导航文字当作目标成功。

2026-09-18：本地资格隔离的Task保持deferred，不进入无条件deferred兜底选择；新的可达路线证据可把原Task唤醒为pending用于复查，Operation仍受限。工作Region保持原硬边界，路线服务复查，显式next_operation_ref不能绕过当前绑定资格。原审核解除后沿同Task/图谱执行，已有成功与未知结果不重写。路径及恢复用例见region_work.md。

2026-09-17 连续范围核对：工作Region的共享coverage已无pending直属义务时，先调用既有choose_region_task记complete/blocked，再保留未完成的子页面survey；不能让子清点把已结束父范围挂住。准备动作的task_result直接使用SettlementResult.task_refs，实际操作成功不冒领焦点完成，别名与代表覆盖沿原结算。

2026-09-17 自主推进衔接：runtime依据pending、fresh位置确认、当前适用绑定与原Region路线给出settle/observe/execute/navigate/prepare阶段，工作Region不由模型重新选择。已有路线优先复用证据点击锚点；没有锚点由主Agent定位程序选定的第一步。相同位置/任务/知识下查询不重复扩展；无绑定时转导航/有界准备，继续查询而无新条件则仅defer当前目标并交回现有同区调度。待结算、位置不可信或仍有报告纠正时不进行这种局部释放；gap保留，不能假complete。

2026-09-17 调度约束补强：选定工作Region后，是否已完整清点当前前景不再决定是否进入全局独立任务选择。未清点时保留本区活动焦点及原有限准备/恢复，必要当前survey仍属于本区工作；无活动焦点也先选择本区适用直属目标。最短路径只用于到达该目标。主Agent的next_operation_ref同时不得越过活动工作Region或声明范围；只有原region_work_closed记录complete/blocked及未完成覆盖后，才允许自动换区。显式exploration_goal且未建立自动工作Region的原语义不变。

2026-09-17：自动探索先在工作Region内选适用的直属Task，复用当前绑定与原Region路线；同区直属操作先于无关旧待办，子前景临时出现不切换工作Region。直属覆盖完成或确实无安全可达待办才结束该轮（complete/blocked分开）。blocked轮未变化时不立即重开，保留原Task及失败/延期事实；已登记未验证仍为缺口。跨轮仍用既有选择与不可达让位。详见[工作范围](region_work.md)。

2026-09-16：自动调度的新选任务与保留中的任务共用同一次返回前的不可达让位检查。当前State已清点、无pending动作、目标无当前绑定且无ready路线，同时存在合法当前pending操作时，立即选择该可见待办；不先把不可达祖先任务交给Agent绕行一轮。旧任务/操作保持pending和原预算、缺口；有可信路线、待结算动作或显式exploration_goal时保持原规则。VLC batch14 a200结算后的原输入离线回放从t86改选t355，未执行新的真实GUI，未证明完整应用持续性。

2026-09-10：显式分区修正通过后，选中控件/local Operation保持ID，已审核配对沿用CanonicalOperation及Task收敛；不清零尝试或伪造本地成功。任务预算包括导航及其他准备动作，耗尽提示明确指“操作探索任务”，不是目标控件执行次数。当前共享绑定存在时，缺owner校验使用它的来源及控件引用，不再只看Task最初来源。

2026-09-10：普通CanonicalOperation现在共用一个探索Task。operation_task优先解析本地记录，再查询同一稳定身份的任务；新State只增加本地绑定，record观察不会关闭另一来源的未完成目标，新的可用绑定可继续原deferred任务。显式代表试验保留各成员的独立试验任务。

身份合并、调度和resume会收敛旧重复Task：保留当前active目标优先，合计尝试计数，改写工作账本中Attempt/History的Task引用并记录operation_tasks_coalesced映射；实际owner、操作、坐标、来源/结果State、前后图及结果不改。原始日志及源checkpoint不改。task_source_states取同一稳定操作的合法来源集合，当前执行仍用当前Variant的真实owner；已验证兄弟的其他本地绑定只记recorded，不伪造verified结果。

同一Task切换实际本地绑定后，可清除旧绑定的即时纠正和执行思路；有pending或共享报告纠正预算时不清除，不重置Task尝试预算。旧图粗区块的自动拆分和语义重归属未因此解决。

2026-09-09：显式exploration_goal下不再自动派发旧Operation待办或替换焦点；保留已选活动任务和必要survey，其余由主Agent按范围用next_operation_ref或实际owner动作选择。无Task时可用当前唯一recorded/verified绑定恢复，仍保留绑定与近重复检查。无动作、无新事实的范围决策以scope_idle/partial结束，不冒充全应用完成。无exploration_goal时沿用原自动调度。

2026-09-09：完成当前State清点且没有未结算Attempt时，若active操作无当前binding、无ready的Region路线，
而另一个pending操作有合法当前binding，则先探索该可见功能。旧Task和active Operation回pending，已有结果不改，
写unreachable_focus_parked事件。新目标独立选择，不认作旧目标身份复用或完成；没有替代项、仍有绑定或路线时保持原焦点。

2026-09-09：独立动作结算后的坏清单可使未完成 survey 暂为 deferred，其他已有任务继续。
deferred_inventory_reports 从既有事件账本派生待补状态，TaskScheduler.gaps 保留 inventory 缺口；
只有后续完整清点与身份审核成功的 inventory_report_resolved 才消除，不新增任务种类或第二张账本。

2026-09-07：重复选择当前 active 操作不改变任务，运行时按普通继续轮校验动作。选择其他任务失败时区分未知 co、无开放任务、非当前 State 和多个匹配，并明确继续当前任务应留空 next_operation_ref；清点期间允许已有调查动作，不要求用任务切换表达滚动。不新增任务类型或拒绝计数器。

## 2026-09-07 当前共享入口可继续旧待办

current_operation_binding 允许未完成来源操作使用同 Region、同 canonical/action/scope/direction 的当前 recorded binding。
recorded 是本地登记/调度状态，不等于禁用。仅解析已有开放待办的当前入口，不新建任务，不把 recorded 自动记为成功。
执行门使用同一解析结果；verified/failed 等终态不因此重开。Settings 原账本回放中，Background 待办直接取得 el32，
不再要求从 Bluetooth 返回 Network。原有用例改为验证此行为，未新增测试文件。


## 2026-09-06 显式改选当前可见待办

TaskScheduler.select_visible_operation 接受主 Agent 的 next_operation_ref 和 strategy。
当前 State 清点完成后，可选择唯一的当前可见 pending/active/deferred 操作；旧 active Task 保留为 pending，
新 Task 为 active。选择不产生动作证据、不结算旧目标，也不把 failed/recorded/verified 操作重开。
不选择时沿用现有 scheduler。模型仍需通过原动作 owner 校验；改向并不解除动作或前景约束。


最后更新：2026-09-05

## 层级与真值

持久图仍是：

```text
Page State -> Region -> RegionVariant -> Element/Region -> local Operation
                                              -> CanonicalOperation identity
```

ElementOperation 的 owner 是具体 Element；RegionOperation 的 owner 是 Region 整体。每个可探索
local Operation保留各自的来源与结果；同一普通CanonicalOperation共用一个内部Task，以其中一个本地Operation为稳定身份锚，执行时解析当前绑定。Task用于尝试预算、失败证据和resume；显式代表试验例外。Task不是
模型协议，也不再由主 Agent提交完成/延期/失败。

`Semantic Exploration Focus` 替代模型看到的长期 Task 卡：它从当前内部 Task、Page/Region 和
Region memory 即时投影自然语言路径与目标。Focus 不分配新 ID、不复制 Operation/Attempt/Transition，
也不改变全局图只有一份的合同。

## 自动结算

模型动作先由 `owner_ref + action + direction` 绑定当前 Variant 的本地 Operation。下一轮模型只报告
该 before/after 直接证明的 completed owner action；框架唯一映射并自动：

1. 把本地 Operation 标为 verified；
2. 关闭其派生 Task；
3. 按现有 CanonicalOperation 身份关闭重复 binding，但保留局部证据；
4. 重算 logical gap 和 completion。

一次动作可顺手完成当前页面的另一个 owner。Attempt/History 归当前 Focus Task，真实 owner 由
`action.operation_ref` 记录；那个 owner 的 Operation Task 可关闭，原 Focus Task 仍 active。旧的
“route 动作只建边、不结算路过控件”模型侧分支已取消；`route` 只保留为框架内部连接分类。
同一前置 owner 在同一 Focus 中执行且没有 State 进展后，相同 operation/action/direction/text 且
点位距离不超过 25/1000 的近重复会被拒绝；明显改变点位仍可用于真实重新定位。绕行动作因此仍受
当前 Focus 的最近动作、拒绝和尝试预算约束。

错误落点、候选外 owner、primitive 不同或 before Variant 中不唯一时不结算。Region memory、reason、
screen identity 和 target 文本都不能替代 owner/action binding。

## 两个代表共同完成一次探索

2026-09-09：普通参数已有形式/可见值时只记录，不固定验证两个值。只有未确认的交互关系确实阻碍功能理解且安全，
才使用下面的既有代表机制。删去主 Prompt 的强制步骤，不删除已有数据合同或执行证据。
尚未执行操作的明确 handling 修正通过 inventory 同步 Task；record 可关闭未执行任务，explore 可重开，
defer 保留缺口，已执行结果不变。只在 reason 中说跳过不会改变待办，主 Agent需提交带当前 owner/co 的增量清单。

提案入口为 `tasks.apply_representative_probe()`，成员校验与登记由 `tasks.register_representative_probe()` 完成。
两者接收当前 ledger、Task 和既有报告，不持有 runtime，也不判断控件的 GUI 含义；
runtime 仍在原动作轮调用入口。此职责搬迁不改变代表项优先级、预算或结算条件。

普通同质项仍只选一个代表。只有一个代表无法回答明确的交互关系时，Luna才在动作前列出当前 Region的
全部同类 Element owner，并从中声明两个代表和一个简短问题。成员可以在首次清点时拥有不同的临时
CanonicalOperation；框架只验证同 Region、同 owner类型、同动作、尚未执行，再把原先 recorded 的第二个
代表恢复为 pending Task。这是现有 Focus 对既有 Operation Task 的组合，不新增 Task 类型，也不自动合并身份。
第一个代表成功后，Scheduler继续派发第二个。

第二个代表的 after 图必须同时给出 `representative_same_kind=true/false` 和对应 Region memory。确认同类后，两个真实
执行的 binding 为 `verified`，其余显式成员的未执行 binding 为 `recorded`；原始 Attempt
仍只有两个。若结果不同或最后一次没有明确结论，框架不批量结算，剩余任务和 gap 保留。没有已登记
Operation 的其他参数值只留在 memory/parameter summary，不为结算补造对象。

## 调度与终态

普通新 State 先清点再派发 Operation。重启后若已有活动操作任务，且当前目标 binding 或已验证 Region 路线起点
已经确认，则不要求全屏清点完成；原调查待办保留，完成度不因此提高。当前 State 清点完成后，Scheduler 从当前 State 沿 verified Transition
反向求祖先 frontier；存在当前/祖先来源任务时，按 `created_seq` 选择最早任务，先闭合较早来源 State，
再深入新显露 State。没有祖先 frontier 时才按已验证有向图距离选择来源。不相关且不可达的旧 State
不会抢占当前可达任务。当前 State 若已有同一 Region/CanonicalOperation 的可执行本地 binding，
active Task 仍优先切换到该 binding。pending 全部处理后再复查 deferred。

每个 Task 的执行前置是目标 local Operation 所属的精确 Region、Variant、Occurrence及其 source State，
不是来源 State 的全部 Region。Add/Save等操作允许正常执行；若它让后续焦点 binding消失，Task保持开放，
Luna根据精确任务卡探索 Back、Cancel、Delete、导航或环境恢复，直到重新到达含该 local binding 的 State。
恢复动作照常进入 Attempt/Transition，不能用相似 Operation反复替代焦点。
同一 canonical Operation 若在当前 State 另有尚未结束的本地 Task，Scheduler 可以切换到该任务；已经
`recorded/verified/failed` 的本地 binding 不能替代来源任务，也不能因当前 Region 可见就跳过返回来源 State。
当前 State 没有开放本地 binding 时，任务卡不显示来源 Variant 的旧 `element_ref`。若截图中目标控件实际可见但
当前 Variant 漏报，Luna可提交空 Element ref 并引用任务卡稳定 `co`，框架补建当前本地 binding 后再切换任务。

若当前不在来源，任务卡从 Region可见性关系规划到目标 Region与目标 canonical binding。精确来源
Variant证据优先；此前未见 State中的新 Variant只有在当前本地 Operation共享 canonical identity，
该 canonical 的已验证 reveal/hide效果签名唯一，且已有 `variant_operation_result_reused` 直接结果复用记录
连接到真实 Transition owner 时才能复用。只有 identity 配对或 verified 状态不足以授权落点。
效果冲突仍保持 ambiguous。2026-09-05 Settings 实机对照暴露的 identity 跨 Variant 错用落点已加此
离线门禁；原真实边保留，尚未实机重跑，见 `region_routing_design.md`。

同一焦点中，一个非焦点 Operation 已有真实 success 后不得再次执行；换坐标或绕回同一表面不绕过。
Luna必须返回精确来源 State、选择另一个尚未成功的准备操作，或如实留下 gap。框架不因替代操作
文字相似而结算焦点。

内部状态保持 `pending / active / deferred / done / failed / cancelled`。模型不能直接写这些状态；
框架通过真实 completed owner、页面清点结果、Scope/active-surface、重复 no-effect、动作拒绝上限、
恢复上限和十二次 Attempt 上限推进。failed 仍是正式 gap，不冒充已验证。
Scheduler 每次选择前还会把 open Task 与其 terminal Operation 对齐：verified/recorded -> done，
failed -> failed，cancelled -> cancelled，并清除指向该 Task 的 current ref。该门禁修复 Region/Variant
合并后可能留下的“Operation 已终态、Task 仍 active”漂移，不改变 Operation 真值。

普通纵向列表的 up/down RegionOperation 初始记录为 recorded；调查滚动绑定该 Region 和方向，由 Luna报告真实完成后验证，
不在清点后逐项重复调度。
参数值不是 Task：选择器入口是一个 Operation，值域和代表行为写 Region memory。明显不同的 Custom
分支可形成一个额外代表入口或显露的新 Region。

## 参数确认调度

v5 参数确认不新增 Task 类型：`unknown + explore` 复用原 `explore_operation`，动作后的
`parameter_info` 与 completed owner 一起结算；`unknown + record` 不创建任务，只产生
`parameter_unknown` logical gap。任一 canonical binding 已有 `none/observed` 即关闭该逻辑参数 gap。
同一 canonical 同时存在 `none` 与 `observed` 时保留投影审计标记，但已有 `observed` 代表值足以关闭
completion gap；框架不删除或改写任一局部报告。
对 v5，逻辑 Operation 的所有 binding 都仍为 `unknown` 时，即使 Operation 已 recorded、任务队列为空，
也不能得到 complete。

## Completion

对外 logical task 和 gap 仍按 `canonical Region + CanonicalOperation` 聚合。任一 binding 有 verified
证据后，重复 binding 不再执行；旧 failed/local Attempt 保留。Focus completion 由范围内 State 已清点、
Operation 已终态、没有 pending Attempt 且子表面闭合或形成明确 gap 推导，Luna 不报告完成。

## 2026-09-08 反馈检查

代表提案反馈给出当前 co、实际 scope、冲突成员；普通动作纠正使用当前 owner 协议，不要求已退役的模型字段。未新增重试计数器。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。

2026-09-11：partition_review_deferred是按State汇总的持久质量gap，不新增可运行Task，不阻止已有任务推进，也不会使未复核图得到complete。另修正旧内部operation_ref兼容路径：空owner且当前解析binding仍为deferred时拒绝执行，要求先核对条件并提供当前action.owner_ref；正例的当前可用绑定仍可用。此旧失败已在改动前HEAD的_validate_action上重现，未将其误归为分区选项引入。
