# 运行与产物

2026-09-20：收尾时的新帧回到既有observe阶段。目标应用前景已确认、已知State有清单但最新帧尚未确认时，不再直接以foreground_inventory_unconfirmed退出；先识别当前前景，已知且无变化无需重报清单，新控件按原路径登记后继续调度。未知位置沿原3轮纠正，耗尽不重新发观察机会；缺口与旧Attempt不改。无新增模型字段、状态枚举或Reviewer。空白页被伪清点为非空Region的问题仍未解决。79项聚焦离线通过，尚无此次修改后的新模型/GUI实机验收。

2026-09-19：无待办的两个结束入口共用`_completion_reason`：当前系统归属、已确认位置/帧来源与非空Region清单不齐时为`foreground_inventory_unconfirmed`/partial，不能因空白清单而complete。帧字节一致只检查本次接受证据来源，不判语义身份。结构预检拒绝记`page_report_structure_rejected`，原编辑整体应用事件和预算继续保留。

2026-09-18 V2：执行器成功返回后，沿原Attempt保存后帧并追加`action_delivery_returned`事件，绑定动作、前后帧摘要、投递错误和前景归属。正式restore仅保留最后一个仍pending、证据完整、尚未进入报告纠错且未被结算/放弃的动作供原审核补结算；已开始纠错的中断保守转unknown，不通过恢复重置次数。截图摘要只校验文件来源，不判断身份或成功。补结算使用原投递帧，禁止新GUI；通过后清空现场绑定，fresh观察再恢复。缺少可靠投递证据仍uncertain，不复活旧a9或脚本放弃后的结果。不扩展为投递前持久化或环境配对存档系统。

2026-09-10：增量清单候选与合法位置缓存均为runtime内存态，绑定截图/Attempt，恢复后不沿用。page_report_edits_applied记录当前frame_ref、编辑以及当时published=false；partition_correction_screen_retained保留原提议与被忽略的改写。新增字段/路径与回执索引保护见report_edits.md，不将缓存变更或预审通过视作正式提交。

2026-09-10：partition_visually_confirmed / partition_visual_review_rejected保存新清单入账前的审核理由和当前帧；role仍为modular_region_identity，输入前缀“新清单分区核验”区分于“已知State复用核验”和Region配对。拒绝不发布新的位置/目录或执行动作，已投递pending仍等待纠正后结算。直接接口缺失的非模型客户端不产生视觉批准事件。

2026-09-10：known_state_visually_confirmed记录State、旧/新截图引用及视觉理由；known_state_visual_reuse_rejected记录未通过的State/当前帧和纠正原因。审核调用仍标记modular_region_identity，其user输入以“已知State复用核验”区分于Region配对。核验通过不表示GUI执行或State内所有操作成功；原历史截图不改写，runtime只缓存当前已通过的图对/结构，缓存不写入账本，新建runtime恢复时不沿用。

2026-09-10：context_query只读补查可与未结算pending共存，但不能同轮提交结果/清单/动作/分区修正；原pending与before不变，补查后刷新当前截图。每观察最多2个不同查询，超限或重复以context_lookup_exhausted停止；历史检索或主动态文本超字节预算以context_budget_exceeded在付费请求前停止，不静默删必要证据。相应事件保存查询/拒绝及截图来源。

2026-09-10：可选region_refinement在已确认位置、无pending的观察轮处理；screen可省略沿用confirmed位置，若提供须与当前已知Page/State一致。不与普通清单、GUI动作或任务切换混用。原子修正通过后checkpoint并刷新上下文；拒绝沿共享报告纠正预算，原图不部分修改。新增region_refinement_applied/rejected事件记录候选、映射、证据及失败；无新GUI覆盖。详见[分区修正](region_refinement.md)。

2026-09-09：显式exploration_goal下不再自动派发旧Operation待办或替换焦点；保留已选活动任务和必要survey，其余由主Agent按范围用next_operation_ref或实际owner动作选择。无Task时可用当前唯一recorded/verified绑定恢复，仍保留绑定与近重复检查。无动作、无新事实的范围决策以scope_idle/partial结束，不冒充全应用完成。无exploration_goal时沿用原自动调度。

2026-09-09：删除survey必须完成后才能调查已登记控件的旧门禁。清单首次取得ref后，可用当前合法owner继续点击等调查；动作仍逐次结算，不提前完成survey。同轮清单的候选点击仍留到下一轮。有限参数列表继续观察未见选项，同质数据可以按功能结构收束。

2026-09-09：新的清点写入v7账本，旧v3-v6仍可只读加载，接受新清单后升级输出版本；未知参数缺口在v7继续保留。
新增modular_region_hierarchy.json按State列出父子归属；它表示登记结构，不证明全部成员当前同时可见。
编译function_inventory.json补充containment、control_observations、parameter_observations和result_observations。
旧参数信息明确标为历史观察，保留来源截图；不把旧取值与新结果作为同一时刻事实。该投影位于bundle.py，
未修改用户正在编辑的region_function_research.py；直接调用其基础函数的下游入口尚未统一采用此增强投影。
ExplorationRuntime可传exploration_goal作为自然语言范围，原始模型请求可追溯其实际输入。没有额外模型角色或预算。

2026-09-09：恢复提交Region清单前，复用已完成State需满足`location.validate_state_composition`的完整Region引用集合检查。
没有pending动作却要求换到另一已完成State时也运行同一检查；在确认前不把错误位置提交到ledger。
局部目标Region仍可通过new_state记录；未完成State的补充和无清单的非图恢复不受此完整集合门限制。
这是声明一致性检查，主Agent仍必须按最新图核对实际组合。已完成State恢复的Element/Operation附带报告
写入resume_known_state_inventory_ignored审计并排除出本轮清单，沿用其已有目录，不污染旧Variant；
新State/普通非恢复清单仍严格审核。原始回复和拒收内容均保留，不把忽略的候选记为已发现新功能。

2026-09-09：`prepare_resume_region_rediscovery`按中断Attempt的action.operation_ref归因，
不再把非焦点动作的不确定性记给attempt.task_id所指的未执行操作。实际绑定没有旧Task时用同一Task模型
登记failed gap；已有verified/failed/cancelled终态保留。原焦点active恢复pending，当前位置仍清空重识别。
原a43快照离线回放中，未执行Lap保留pending、实际Resume留下不确定/failed；原始快照不改，非新实机证据。

2026-09-09：清单预检抛出的既有结构化合同错误保留其field_path/expected/received，不再统一错标为Element错误。
对应事件为 `page_report_precheck_rejected`；普通Element审核错误仍记录 `element_identity_batch_unresolved`。
两者仍交主Agent纠正，使用原三轮预算，不新建重试机制，不放行跨State引用。

2026-09-08续测：恢复定位完成的判据是当前最新截图非空Region报告通过，而非survey_complete或已验证目标路线。此前中间返回控件虽登记仍无法执行，与工作卡及拒绝反馈冲突。现在只解除旧位置恢复标志，保留原Task、未完成清点和正常owner/action校验；没有新字段或计数器。

2026-09-07：同一当前任务的 next_operation_ref 在选择后归为空，继续经过正常无进展/动作绑定检查；非 pending 清单拒绝复用 last_context_task_id 的现有保留方式，将页面纠正传入下一轮。普通任务切换清理旧动作纠正；当前报告纠正跨任务保留，现行上限见报告纠正流程。

## 2026-09-06 当前增量

pending 的 Region 归因在位置/清单的临时 ledger 中解析，校验通过后再按原机制结算；
InventoryResult.reported_region_ids 仅是运行期的清单行到框架 ref 映射，不写入持久 Schema。
同一 Region 更新与外部事件写入 events，不从可见集合差自动生成因果。
每次 bundle 编译另导出 function_inventory.json（Region、已有操作、参数说明、memory 与位置），
包括零 Attempt 的已发现操作；它是账本派生视图，不取代原独立能力图和原始证据。
execute_action 与 Region 采集共享桌面点击/一次全选/纯文本输入执行方式，不复用历史坐标。


## 主循环职责

`runtime.py` 只编排固定顺序：前景检查、选择内部 Task、投影 Semantic Exploration Focus、调用主 Agent、
在临时 ledger 中处理 Page/State、上一动作结果和已提交清单，检查通过后发布并释放 pending，再按需调用
区块身份判断、绑定并投递一个动作、保存 checkpoint。语义判断不散落在循环分支中。

任务卡和完整模型输入由 `status.py` 构造；Region/Element/Operation 身份审核的候选、保存帧与模型结果
处理由 `region_review.py` 负责；代表提案的校验和 Task 登记位于 `tasks.py`。
runtime 保留任务切换、pending、位置和纠正状态，通过显式参数调用模块并接受返回的 ledger。
模块归位本身不改变行为；后续输入、新观察和报告提交边界的当前合同如下。

桌面 input_text 的 CLICK、一次 Ctrl+A 与无坐标 TYPING（空值用 Backspace）只占一个 Attempt。
位置未确定时保存同一 pending 的 after 证据，模型请求 wait 时沿原等待时长后重新取图；不计新增 GUI
动作，不强迫确定身份。长期不确定仍由原模型轮次上限返回 partial，缺截图则明确停止。
位置、动作结果和已提交清单的必要检查通过前不保存临时图或释放 pending；报告失败只保留动作证据、
原图与纠正事件。合法不完整清单可提交，无清单的恢复回执仍正常结算。
普通观察和合同纠正轮均可无动作提交合法的不完整清单，不要求为了提交报告而执行GUI动作。
不完整不表示完成，字段错误仍走既有纠正上限；无进展的模型循环由已有轮次预算停止并保留partial/gap。
提交page_report的同轮click统一留到下一轮，空owner也不能绕过；合法清单保留，未执行的点击不创建Attempt、不把候选记失败。
缺owner时返回具体反馈，优先由Luna用现有next_operation_ref改选另一当前可见且可执行的绑定；不做名称匹配或黑名单。
该反馈属于页面登记，不因旧任务刚结算、新任务接替而清空。单独恢复点击仍使用page_report=null。
resume接替清点任务时，接受其来源State的可见Region报告即可结束恢复定位；不等待一个不存在的Operation binding。
这只清除恢复阶段标记，不将survey_complete或清点任务改为完成，之后继续普通清点。

模型动作的非空 `owner_ref` 在当前 State 的 Variant 中唯一解析本地 Operation；解析后的
`operation_ref` 和内部 purpose 只写 ActionAttempt，不回显为模型决策字段。待结算时 runtime 校验模型报告的
completed Element/Region action 与真实 primitive 一致，再关闭实际 Operation 的派生 Task。一次动作可完成另一个
owner，但原 Focus Task 不会被错误释放；不再召回或接收模型侧 `satisfied_operation_refs`。

主 Agent 发起的真实动作保存完整 ActionAttempt.agent_reason，下一轮只回传该 pending 的动作前说明。
它是原始预测/动机，不是结果；不改变 owner 结算、Transition 或 Region 身份。旧记录缺失时默认空串，
自动路线重放没有主 Agent 理由时也不补造；动作前后说明分别保存，不相互覆盖，模型输出 Schema 不变。

当前 Task 刚结束、下一项尚未派发时，可以执行空 owner/operation 的非滚动 recover；
ActionAttempt.task_id 为空但 before/action/after、pending 精确结算与总动作预算仍照常记录。
不创建假 Task，也不增加已完成 Task 的尝试数。功能操作和滚动的绑定要求保持原样。
连续两次无任务 recover 均 no_effect 时，写 taskless_recovery_exhausted，停止本轮并报告
recovery_no_effect_budget_exhausted/partial 与恢复 gap；不会执行同轮第三次动作或忽略恢复缺口。
有任务恢复继续使用原有任务预算/Android 保留数据重启逻辑，未扩大此路径的修改范围。

待结算动作的 Page/State 报告由查看最新完整截图的主 Agent 直接提交。runtime 只校验
结构、已知引用和 State 归属，不再另调纯文字 Page Resolver，也不因第二个模型的 Page 分歧
阻塞 ActionAttempt 结算。Region 身份仍由查看当前与候选完整截图的 Region Reviewer 独立复核。

模块化 resume 复用原 run 目录。`ArtifactStore` 初始化时扫描已有 `frame_*.png`，从最大编号继续写，不覆盖旧截图；
ledger 的 counter 继续生成新的 State/Region/Operation/Task/Attempt/Event 编号。旧 `modular_completion.json` 在成功定位后
按序归档为 `modular_completion.pre_resume_NNN.json`，新 completion 只描述续跑后的总账本。
帐本加载和完整性检查使用临时对象，不先写回 checkpoint。成功后，未结算 pending attempt 保留原 before evidence、改记
`uncertain`。实际绑定非空 `operation_ref` 的中断只对该绑定产生 failed gap（已有终态保留），不失败未执行的焦点；未绑定 Operation 的
`route/recover/survey` 中断不代表功能 Operation 已执行，原 task/local Operation 回到 pending。其他没有 pending action 的
active task/local Operation 同样回到 pending。历史终态和真实边不重开。
resume 一律应用上述中断归一化，不绑定旧 Page/State，也不读取或比较旧 State 截图；主循环下一轮
以加载后的旧图和空当前位置处理 fresh screenshot，登记当前可见 Region，再由 Region Reviewer 做全局身份复核。
Resume 的前景归属门位于 ledger load/location 之前；外部 Settings 等画面只能触发现有非图恢复或
`resume_scope_unresolved`，不能进入候选调用。账本完整性失败前旧 `exploration_ledger.json/events.jsonl/completion` 均保持原样。
随后，若一个已完成 known State 收到材料上不同的完整 Region 组合，runtime 先拒绝该重复清单并触发一次 State Identity
重判；重判上下文按需附带候选旧 State 的持久 Region/Element/Operation 记录。再次确认 `known` 时丢弃新分块并复用旧
State，确认 `new_state` 时才接受新清单。这条保护只防止 State 被加性污染，不以 Region 差异
直接决定 State，也不代替 Region Reviewer。

区块身份调用先用文字/操作结构把候选限制到最多两个代表 State，再把当前和 shortlist occurrence 所属的
`RegionVariant`、本地 Operation 及完整截图交给 Reviewer；候选代表 State 中
已由真实 `execute` 成功结算的 `ActionAttempt.visible_result` 另投影为最小 `verified_result`，不复制整段动作历史。
Reviewer 的显式配对可用 `reuse_level=identity` 先共享 Region 级 canonical Operation，而不继承任务或结果；
`reuse_level=result` 才要求候选本地 Operation 已是 `verified` 且 `verified_result` 非空。缺少结果时 runtime 降级为
`identity` 并记录事件，不把结果写成已验证。
Reviewer 已确认 Region 相同后，Operation 仍只接受截图 Reviewer 的明确配对；runtime 不按名称、
精确文本签名或特定单词补配，也不按同 Page 同名 Element 自动关闭不同 canonical 任务。
Reviewer 还必须给出组件结构关系。runtime 对整批回复做原子校验：一个候选只能接收一个完整当前组件，或接收至少两个
共同重构片段；触发器/结果表面和成员/完整容器不能复用。首轮不合法时恢复原账本，把具体错误交回 Reviewer 重试一次；
第二轮仍不合法则记录 unresolved，不保留半批结果。合法的同 State 重构片段随后合成一个 RegionVariant，并收束其中
已明确配到同一 canonical 身份的无证据重复 Operation。
多片段重构在合并前多一道窄审计：只传相关 proposal 和两张完整截图。审计必须返回
`confirm/same_component_repartition`；`trigger_or_result`、成员关系、不同组件或不确定一律让首轮提案失败并回到原 Reviewer
纠正。这样候选操作的 `verified_result` 可以作为“点击后才出现”的因果反证，而不会被反向当作 Region 身份证据。

首份不完整 page_report 允许 action=null，先分配 Region/Operation ref。后续调查滚动必须绑定当前 Region owner，
由框架解析对应方向的 RegionOperation；同一 State 后续增量清点可继续携带已登记 Region 的调查滚动。
已有清单后，重复不完整报告且没有观察动作会被拒绝。Luna确认覆盖充分时提交完整 page_report，不重复空转。
整屏像素变化不能证明目标操作成功；同尺寸像素一致也不能单独证明点击或滚动无效果。runtime 仅依据交付错误、结构化动作回执和现有落点审核结算；证据不足时保留 `uncertain`。
live schema 不要求模型输出 outcome。Region scroll 的 completed 由主 Agent根据前后图和结构化落点报告；框架不以像素比例覆盖结算结果。原“completed=false 但画面有变化”的隔离分支已删除，其余结果和当前观察由 Luna判断。
Android 每次 scroll 投递前另用系统 `input_method` shown flag 做只读检查；软键盘仍显示时拒绝 scroll，要求先 Back
隐藏键盘并基于 fresh frame 从应用内容区重新定位，防止 Gboard 把滑动解释为 glide typing。
调查滚动按“要查看的内容方向”解释 `direction`。同一调查在同一 Region 最近三次同方向滚动若都为 `no_effect`，第 4 次
会在生成 ActionAttempt 前被拒绝；点位变化不绕过该限制，反方向或不同 Region 会结束这段连续计数。
若观察或恢复动作离开了尚未清点完成的来源 State，runtime 保留原调查任务并允许 `route` 返回；当前位置的
`page_report` 会以具体的来源/当前位置编号拒绝，防止同一已完成清单被反复写入而原任务永远不结束。
页面调查和操作任务各自最多使用十二次真实动作；最后一次仍先保存前后图并正常结算，任务若仍未结束才记录为
`failed`、释放当前任务并继续调度。失败不会删除已经保存的部分清单或动作证据，并会保留为完成 gap。
全局 `max_actions` 达到后，若最后一个 ActionAttempt 已完成结算且账本已有 State，runtime 在下一轮调用主 Agent 前直接以
`action_limit` 收尾，避免让模型再提出一个确定不会执行的动作。`max_actions=0` 仍允许一次首屏 inventory；首次 State 写账后
才按同一规则停止，因此可用于 Terminal/Thunderbird 等零动作只读图生成。
操作任务若连续四轮收到动作合同拒绝且没有真实动作或账本进展，则无需等待全局模型轮数耗尽：runtime 将该任务记为
`failed`、保存拒绝次数和最后原因并调度下一项；拒绝理由改写不重置同一任务的计数。被拒轮不生成
ActionAttempt、截图动作证据或连接。
Scheduler 每次选择前还会对齐 open Task 与 terminal Operation：verified/recorded -> done，
failed -> failed，cancelled -> cancelled，并清除 current ref。这样 Region/Variant 合并或拒绝收束后
不会留下“Operation 已终态、Task 仍 active”的 orphan gap。
runtime 用 `last_context_task_id` 清理旧任务动作反馈；尚未结束的报告纠正与共享计数跨任务保留，不能借调度清零。
当前位置已属于某 Operation 的来源 State时，模型直接填写当前卡片的 owner；框架自动绑定本地 Operation。
已完成清点的已知 State 在操作任务期间重报 `page_report` 时仍只忽略清单；但若同轮也没有前一动作结算或 action，
runtime 会把它作为无进展合同拒绝并复用上述四次收束，防止“重复清单、等待下一轮”无限空转。
活动 Operation 的其余回复也使用同一进展不变量：没有前一动作结算、账本新增、GUI 动作和任务结算的轮次一律拒绝，
不通过关键词或应用状态猜测模型意图。
全局结束由runtime决定，不再请求主Agent的completion_check，输出Schema和AgentTurn已删除finish。
任务调度无可执行项、无pending动作且当前定位/恢复已完成时，已有gaps为空则complete，否则terminal_gaps/partial。
同轮新报告仍先校验和登记，新任务继续调度；最后一个动作的结果必须结算，不因队列暂时为空跳过。
初次清点和resume的fresh定位不被自动结束跳过。complete只表示已登记范围闭合，不能证明未知入口不存在。
同一任务连续两次真实 `recover + no_effect` 时，runtime 在第二次 ActionAttempt 正常落盘后将该任务置为 `failed`，
不再等待第三个恢复提案。failed 任务纳入 `gaps`；其余任务继续调度，无可执行项时自动以
`stop_reason=terminal_gaps`、`status=partial` 结束。该路径不调用额外模型，也不使用像素变化决定真实 State。

状态栏中的待结算动作是框架已经真实执行的事实。主 Agent 必须比较 before/after 并只回填实际完成的
Element/Region action 和 Region function info；不能跳过结算直接提出下一动作。框架按 owner/action 唯一映射
Operation，并从真实绑定自动更新 Task/completion。绑定 Operation 的动作没有 completed owner 时只保存
`no_effect/uncertain` 证据，不让模型用自然语言批准 Task。新 scroll 必须绑定 Region，不能再走空 owner 的像素成功路径；
非滚动空 owner 和旧账本中的空 owner 动作仍可保守结算，但不验证 Operation。
`completed=true` 表示 after 截图已证明 Operation 的直接可见效果，不表示 controller 仅投递了 primitive；
落点偏移、只出现 tooltip 或界面无相应效果时必须为 false，并继续使用 fresh screenshot 重新定位。
需要参数确认的 owner 若 `completed=false`，`parameter_info` 必须为 null；runtime 保留
`parameter_status=unknown` 并先结算 no-effect/retry，不能用“参数确认必须绑定 completed owner”把
同一 pending Attempt 留在无限纠正循环中。
模型误填参数时，runtime 在 Operation settlement 前确定性清空未绑定的 `parameter_info`，保存
`parameter_info_ignored_without_completed_owner` 事件；不从自然语言 reason 推断参数或成功。
主 Agent、Element/Region/Operation Reviewer 共用三轮失败预算（首次失败加两次纠正）。错误直接交给能修改它的角色；措辞、排序、任务切换和刷新截图不清零。报告通过检查才结束纠正。耗尽后保留候选、截图和 gap，不再审核同页冲突；位置可信时可沿已有绑定探索其他内容，否则 partial 停止。详见 [报告纠正流程](report_correction_flow.md)。
结构化错误点名字段、期望和收到值。可同步修改相关位置、分区和效果判断，不缓存冻结的 AgentTurn；真实 Attempt 不可改写。纠正期不执行新动作或自动路线，耗尽后 pending 保守释放；不存在独立 pending 两轮或 Agent 内层两轮重试。
框架不再按同 Page、同名 Element 或相同 target 自动结算其他 canonical Operation。重复任务关闭只依赖已经由截图 Reviewer
确认的 CanonicalOperation 身份，不依赖操作名称词表。

Android 前景归属优先比较当前 Activity 的真实包名。其他包即使由目标应用启动、仍位于目标任务栈内，也属于外部界面：
若有待结算动作，主 Agent仍可依据前后图描述入口效果，但外部画面不能登记为目标应用 Page/State；框架随后返回目标应用，
返回失败才重新唤起。只有真实包名不可得时才退回任务归属判断并把不可判定情况交给主 Agent。
若尚无待结算动作且目标应用连续三次恢复后仍不能进入前景，runtime 写
`external_surface_recovery_exhausted` 并以 `scope_recovery_exhausted/partial` 收尾；不会无限 relaunch，也不会调用模型判断明确的
包归属失败。任一次真实回到目标包会清零计数。

目标应用仍在前景、但同一任务的两个真实 recover Attempt 均无可见效果时，Android runtime 会安排一次
out-of-band data-preserving process restart。该动作复用入口注入的 `restart_app_preserving_data()`，所以
实际顺序是 force-stop、launch、等待前景，不执行 `pm clear`。重启不计探索动作、不创建 State/Transition，
也不写 Capability；旧 Task/Operation 与失败 Attempt 保留，下一轮只清 confirmed-frame 绑定并使用重启后的
fresh screenshot。相同任务至多使用一次这种进程重启。

若 system scope 已为 `target`、模型却上报 `external_app`，runtime 不执行模型 action，也不把当前画面
送入 external recovery；它保存 `model_external_scope_conflict_rejected` 并要求下一轮按目标应用 active
surface 重报。连续三次仍冲突则以 `model_scope_conflict_exhausted/partial` 有界停止，避免同一截图持续
调用模型。真正的 system scope `external` 保持既有恢复合同。

Android controller 的确定性投递失败通过 observation `action_error` 进入同一 pending Attempt。runtime
在 settlement 前以 `action_delivery_error_overrode_completion` 覆盖模型 completed owner，并清空该
Attempt 的完成数组；失败不是新 State/Transition，也不改写为 grounding success。该字段只属于当前
真实动作，下一动作开始时 controller 重置，不污染后续 observation。

## 当前产物

- `exploration_ledger.json`：`modular_exploration.v6` 页面、状态、带自然语言 memory 的 canonical Region、薄 Region Variant、Element、occurrence、
  Region 级 CanonicalOperation、Element/Region owner 的 Variant 本地 Operation、任务、动作和连接。磁盘中的 Variant
  只保存 `variant_id/region_id`；可由父引用反推的反向列表在加载后重建。loader 兼容直接前序 v3 并忽略其反向列表，
  不改写历史文件；
  v6 Operation 继续保存 `parameter_status/parameter_summary/parameter_evidence_refs`；CanonicalOperation
  可选保存一次两个代表探索的目标、全部显式成员、两个代表 Operation ref 和同类结论；成员可以保留
  各自 canonical 身份，代表探索不自动合并 Operation；v3/v4/v5 旧账本保留原
  schema，只读加载时缺字段显示为 unknown，但不追溯生成历史参数 gap；
  Transition 可选保存 `revealed_region_ids/hidden_region_ids`，表示真实动作后新出现/消失的规范前景 Region；
  旧 v5 记录缺少该字段时按空列表加载；
- `events.jsonl`：按序保存结构更新、动作和恢复事实；
- `screenshots/`：每轮完整截图；
- `action_attempts/<attempt>/before.png|after.png`：动作证据；
- `action_attempts/<attempt>/anchor.png`：首次真实落点周围的候选点击锚点；账本同一 ActionAttempt 保存
  `anchor_ref/anchor_offset_px`，只有成功 Transition 才可消费；
- `_modular_debug.jsonl`：Qwen 输入、原始输出和 token 使用；
- `modular_completion.json`：`modular_completion.v3` 完成状态、Region/Variant/Element/canonical/local 数量、gap 和 bundle 状态；
  `tasks` 按 State survey 与 canonical Operation 逻辑任务计数，`task_bindings` 保留本地 Task 数，`gaps` 对同一 canonical
  Region/Operation 的跨 Stage binding 只显示一次。已验证 binding 会关闭该逻辑 gap，但不删除其他 Stage 的失败证据。
- `modular_graph.json`、`modular_entries.json`、`modular_regions.json`：新账本到正式编译器的确定性投影；
  `modular_entries.json` 按 canonical entry 聚合参数状态、说明和截图证据引用；这些自然语言候选不改写
  capability induction 的 formal parameter binding 规则；none/observed 并存时另写
  `parameter_conflict=true` 供审计，但任一 observed 已满足逻辑参数覆盖，completion 不保留冲突 gap；
  `modular_regions.json` 的每个 Region group 另带自然语言 `memory`，供后续指令生成检索；
- `modular_region_routes.json`：派生 Page Region分组，以及带 source Variant、CanonicalOperation、
  reveal/hide和 Transition/Attempt证据的Region关系；不分配新图ID，也不修改annotated/capability schema；
- 完整 modular run 的 `stop_reason=complete` 在正式图中投影为 completion certificate 使用的
  `frontier_empty`；partial 原因保持原值，不会被伪装为完整。State 的
  `page_identity_version` 固定为当前 `semantic_page_variant_v1`，ledger schema 只保留在
  `exploration_ledger.json`，不再误用为 Page/Variant identity version；
- `annotated_graph.json`、`capability_graph.json`：正式编译器生成的采集图和能力图。

runtime 会在已确认帧上先尝试已验证路线的唯一锚点重定位。命中时直接投递首跳并跳过本轮主 Agent；下一轮仍把 before/after
交给主 Agent 结算和确认落地。该快路径目前只减少重复路线入口的定位轮，不减少首次 Page/State 清点、跨页 Region Reviewer
或动作结果 VLM；不能把一次命中折算成全局 token 降幅。新 Operation 身份主链使用 Reviewer 的
`identity/result` 分级；旧 `reuse_candidate_operation_id` 与双边视觉变化比较只保留为已有候选的兼容核对路径。

当前完成报告只证明新账本闭合，不冒充旧 `completion.json`。最终产物即使编译成功，也不能替代桌面端和
移动端 Clock 的真实遍历验收。

运行结束时无论遍历完整或部分完成，都会先保存账本，再调用既有正式编译器。编译成功写
`bundle_status=compiled` 及产物摘要；失败写 `bundle_status=compile_failed` 和简短错误，不把部分遍历冒充完整。
投影不调用模型，也不从应用名称推断能力：ElementOperation 的 `subject` 投影为 Element，RegionOperation 的 `subject` 投影为 Region，
Region 组同时列出 `element_refs`、`region_operation_refs` 和聚合后的 `capability_operation_refs`，不复制原始 Operation；真实成功动作才写入动作边。
若 Transition 含已确认显露关系，同一个正式 action attempt 的 evidence 另含 `revealed_region_refs`；来源 Region
继续使用动作 Operation owner，不创建平行 Region 边账本。
同页且有前后状态的已验证功能操作可形成可见状态变化证据，跨页跳转只作为导航证据。
若同一 Page 的不同规范 Region 在不同 State 中使用了相同显示名，投影只在编译快照中追加各自 `region_ref` 以保持 occurrence 唯一；
不会据此合并 Region，也不会改写探索账本或 VLM 上下文。
同一 `CanonicalOperation` 在同一 Page 的多个 Variant 出现时，入口清单只输出一条并汇总全部来源 State，同时写出
`variant_operation_refs` 追溯各本地 Operation；页面内 occurrence 名称变化先归一为该 canonical Region 在该 Page 的
稳定投影名。跨 Page 出现时仍各自保留页面级入口引用。`modular_completion.json` 的 `operations` 计数 canonical
Operation，另用 `operation_bindings` 和 `region_variants` 报告本地证据规模；任务同样以 `tasks/task_bindings`
分别报告逻辑任务和本地 binding 规模。

## 当前真实结果

- 2026-09-03 Settings 集成监督短跑：最终提示下4个真实动作，通知清理、进入 Keyboard 与预测精确回传已观察；
  无任务恢复和两次无效果停止仅离线验证。重复清单将同一 click 参数确认从 none 改为 observed 后，inventory 抛异常而未回传纠正，
  a30 的本轮结算也未落盘，仍 pending；没有第二次滚动或完整遍历结果。该参数冲突和结算保存边界尚待处理。

- owner-centered Luna Clock（Codex supervised，提交 `d69a7d99`）：24 动作、48 个主 Agent turn、
  15 次 Page Resolver、9 次 Region Reviewer；4 Page、13 State、21 Region、127 Element、
  54 CanonicalOperation/108 local binding、16 Transition，`complete/gaps=[]/bundle=compiled`。
  21/21 Region group 含 memory，正式 bundle 产生 11 个 Capability。该证据不等于无监督 Luna-only run。

- 桌面 Clock 连续遍历：89 个动作、4 个 Page、20 个 State、`gaps=[]`，原 run bundle 编译成功。
- 移动 Clock 连续遍历：67 个动作、7 个 Page、21 个 State、`gaps=[]`；原 run 在遍历闭合后的 bundle 阶段发现
  owner Region 状态别名错误。修复后对同一只读账本做独立重编译，得到 98 个元素和 21 个能力。
- 上述移动派生 bundle 与原始 run 分目录保存；不回写 `modular_completion.json`，因此可区分 live 遍历结论和离线编译修复。

## 2026-09-08 反馈检查

动作拒绝注明本轮未执行，清单拒绝注明未接受；同轮已保存清单的纠正跨下一次调度保留。未知内部错误明确无法定位子字段。run_checkpoint.latest 报告候选摘要/末次结算/快照不匹配原因，存档恢复不交给模型猜测。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。

2026-09-11：CLI新增--defer-partition-review，透传到模块化run/ExplorationRuntime，默认False。成功接受非空区块清单后写partition_review_deferred事件，payload含state_id、screenshot_ref、region_ids及未复核原因；不产生partition_visually_confirmed。事件持久化并由TaskScheduler.gaps汇总，保证有任务时仍可继续、无任务时结果仍partial。既有State/身份/动作检查不跳过；恢复不会丢失质量缺口。模式不新增持久schema，不自动清除旧deferred质量记录。
