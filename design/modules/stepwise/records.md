# 记录

唯一保存格式仍是已有的对象、任务、动作与审计记录，本次不再改一套字段。

- [snapshots.py](../../../src/regrow/records/snapshots.py)：读写、事务指针、加载与正式发布。发现及结果更新调用同一 commit；记录与运行状态同次发布。
- [object_store.py](../../../src/regrow/records/object_store.py)：区块/控件唯一表、稳定编号及归属查询。
- [tasks.py](../../../src/regrow/records/tasks.py)：任务记录、过程审计和只读覆盖/条件查询。
- [observations.py](../../../src/regrow/records/observations.py)：已接受对象变更、身份图与来源。
- [calls.py](../../../src/regrow/records/calls.py)、[action_evidence.py](../../../src/regrow/records/action_evidence.py)：从原调用/纠错及实际投递读取有效回复与来源；不伪造 GUI 效果。
- [history_context.py](../../../src/regrow/records/history_context.py)、context_scope、page_context：按原任务、当前区块和直接准备选择相关材料；原始历史另存，不以未展开表示未发生。

记录保存遍历给出的状态变更，但不自行决定导航或换任务。共享关系、准备归属、条件、未解问题与真实失败保持；source/call 是程序证据，不要求 Luna 重述管理账本。

历史后读、归属、共享等仍有继承自原候选的边界，不能据迁移宣称全部正确。具体新验证见实施记录。

历史答案来源由task_updates.answer_evidence统一解析，预校验与正式保存共用。现有sources结构保存原region/control/attempt/result_call/observation；顶层observation_only表明本轮没有新执行，不把历史准备动作挂为本任务执行。参数约束写入原控件，相关历史仍可追溯；入口关联与无控件移动不走此历史放行。

2026-10-19当前图答案候选：无动作答案不再要求本次截图与旧观察图完整哈希相同，也不要求目标控件在该轮对象输出中重报。answer_evidence接纳仍绑定当前任务/观察上下文的真实请求截图；合格目标历史同时保留，不覆盖本次图来源。source_image保存实际发送图，observation保留请求的记录上下文，不声称两图相同。既有可交互区块和无异常场景门槛保持。知识仍为observation_only，不新建执行、导航关联或对象可见记录。observed_control在其他对象/准备合同中的原用途保留。26项聚焦与原真实回复正常离线登记通过；3次新Luna仅产生操作提案、0GUI，新的完成登记分支仍未原生覆盖，保留未整体验收状态。

参数答案不再要求domain；新答案以description保存输入方式、范围和限制，条件并入description，保留框架关联的原来源归属；不再要求Luna重复填写findings.evidence。新文本更新同名综合描述，旧条件分支保留，Luna须保留仍然成立的内容；旧domain原样可读，不批量改写历史。撤回按原来源恢复，身份合并遇到不同描述先报告冲突。功能总结可引用无domain的约束。

新参数事实不再单列conditions，description包含已确认条件与对应行为；旧条件化事实不批量改写，同名旧条件分支保留，新综合描述与其并存，不把缺省字段理解为无使用限制。当前新描述按同名更新；补充时须保留仍成立内容，证据及历史依旧保留。功能总结输出不再要求拆出conditions；控件知识的适用上下文仍由knowledge.conditions承载，参数规则保存在对应项内。

对象观察与知识事件共存时，`observations.frame_observation` 按框架保存的 source_field、调用和观察时点选取对象登记；知识事件不充当本帧可见证据，不遮蔽历史截图。裁图、当前控件引用、入口可见性及历史清点复用此选择。归属复查按字段读取最近有效语义值，保留后来更新的知识。

2026-10-18功能任务与动作目标分离：新任务类型function/parameter，旧entry/control_effect在统一registration_kind读取为function，不改旧任务引用。功能完成产物为knowledge，参数为findings；任务更新不收entry。remaining_question替代输出registration_gap，旧审计通过只读接口保留具体缺口。
动作后出现/访问关系使用jump_to，序号解析到同次regions/controls的稳定ID；确认实际执行与变化后保存到实际操作对象，同次事务发布，保持实际来源归属，不保存失败回复的部分事实。

历史答案核验先确认source.task_region及绑定任务的完整ref，而非比较source任务键与通用task.name；相同“功能探索”标签不意味着同一任务。随后仍核对实际控件、披露的历史动作、回执、观察来源、失败和条件。当前帧观察也不得绕过任务绑定检查。

出现/访问关系统一为jump_to，输出目标是本次region_index及可选control_index，已有关系可按index修订conditions。登记后转换为稳定ID，区分同区块不同目标。当前关系只保留目标/条件；实际动作、意义与来源留在历史，读者由control_routes查询，不复活旧条件副本。旧entries仅作为历史导入读取，不改写旧运行。

2026-10-19：同类实例的模型材料外层用“用途与依据”，保留known_information内层的已知/推测来源，避免双重已知标签或将推测外标成确认；原事实、任务、条件和参数来源未改。


2026-10-19：观察uncertainties保留在原观察，不再自动复制成task_inventory.review第二份待办。coverage忽略旧版无kind、questions形式的复制项；明确的参数补登记/入口复核及registration_gaps继续阻挡结算。任务清点缺口读取已有task_inventory，退出将其全文复制到correction_context的路径；实际对象/任务纠错仍走原record_edit、校验及事务发布。

`history_context.question_state`统一读取当前任务的已确认参数规则与最新具体未答部分，动作卡和更新catalog共用；不靠模型从动作流水重新推导已接受事实。清点投影保留本区块控件的实际失败、条件与关联边界，不以最后一条动作替代全部记录。

控件持久合同：七项见[object_fields.md](object_fields.md)。参数规则嵌入knowledge，分组属于Region.list_groups，图片列表保存真实状态；来源、旧共享包装和合并别名归既有历史，读者复用control_knowledge/control_records/control_routes。Region可直接引用同一Control，解除一处引用不删除其他引用；任务/实际动作仍保留原区块归属。功能合并按条件保留确认及其他条件猜测，复用有效确认来源，不因参数追加丢失确认。发现登记复用frame_observation按kind/call/region读取真实观察，知识事件不作为裁图来源。实际验收边界见月志。

2026-10-20：任务判断next_action显式null清空，continue省略时仅保留尚未消耗的先前建议；已确认执行的旧建议由task_settlement/decide消耗，显式新建议优先；defer/answered不向后读暴露。新任务与旧判断分属operations/task_update，正常校验、纠错及登记共用新合同。may_open_content新输出只收boolean，历史未确认值不改写。验证范围见本月日志。

2026-10-20身份披露候选：`page_context.refresh` 对身份选择/比较保留内部 `page_context`，不再向正文补入第二份通用地图/历史；这两类角色的展示由冻结 pair/context 和 `prompt_material.identity_view` 负责。原始 provenance、任务/动作绑定及记录格式未改；共享与仅观察来源转为可读使用限制，而不是删除限制。其他角色刷新路径保持。本批只有离线候选检查，未进行原生登记验收。


2026-10-22访问关系提示：`control.jump_base`统一要求已确认实际来源→目标且缺边时填写jump_to，已有关系复用/按原格式修订条件；任务continue/defer与去向登记分开，不因目标相同合并入口身份。原输出合同不变，不为无关变化或仅控件状态变化强制建边。原0029完整保存帧1模型调用/0GUI确认边在任务仍pending时正式登记；非实机或全框架验收，详见月志。

2026-10-22 新识别控件的 knowledge 允许空数组，表示尚无用途知识；已有控件提交空列表不清除旧知识。任务答案的非空合同不变。结构诊断只在联合结构存在唯一适用类型分支时展开子错误，不混合互斥分支。

2026-10-22 字段纠错：更新与纠错校验直接检查原始回复，退出validation_reply提前过滤参数条目的路径，避免把多字段/缺字段/类型错误误报为空列表。登记格式未放宽；错误条目的存储兼容处理仍在store_findings，但不替代原始回复校验。

2026-10-23 暂挂结果沿用suspended_steps和suspended_updates记录；原action_attempts保持原位。关联任务以result_registration_pending阻止重新定位后自动解挂；未解决的suspended_branch不计区块完成。补处理仍须核对原证据，本批不增加自动重试机制。


2026-10-24 parameter结算：missing_product_fields改读目标对象的非空knowledge描述与knowledge_source.source_call（包括来源集合中的source_call），不再要求从constraints提取出findings。constraints为补充结构；answered判断、真实阻塞、准备任务及function分支含义不变。完整结构示例与target/blocked说明见object_fields.md。本次2项聚焦通过；真实0009原答不改，经正常Runner与2次Luna外观/身份补登记后，parameter任务done且知识无constraints。另3次新结果生成均格式失败，未计通过；0GUI，非新遍历验收。

2026-10-24 parameter产物判断统一：missing_product_fields与registered_result共用有来源的对象knowledge判定，source_call可位于多层sources中；不要求constraints或findings非空，也不要求参数事实重复挂到当前attempt。原同用途检查及function逻辑保留。来源检查显式递归，原while遍历本已支持多层，不将本次重构误述为首次支持嵌套。

2026-10-24 首次外观状态说明：外观比较结果不单独发布；register_update在原事务中以精确图片来源匹配旧观察，写入image_conditions及image_conditions_evidence（比较调用与理由），保留原图片和观察evidence。新外观仍由原save_region_images保存，图片列表派生自同一观察历史；比较/定位来源分别保留。两种状态及已有状态复用的保存帧结果见月志。

2026-10-24 补框与确认权威：object_registration.complete补框后直接更新活跃job.request/candidate，registration_submission仅留objects/bbox、registration_sources和schema_extension。已经补齐的活跃请求复用原几何，不重建或恢复旧完整请求缓存。semantic_request保留语义合同，不保存control_identity_reviews；历史request/effective_request/registration_request仍保留审计证据，但不作为下一次复核的最新来源。

### 2026-10-25 功能/状态候选（实跑中，未整体接受）

function_updates.py统一应用功能add/update/remove，先对象知识、再功能、再任务关联；function_refs不改变任务归属/状态或完成门槛。功能object/completion可缺省，参数引用对象知识。Region状态描述写入原observation，沿原来源/截图保存，不新增当前状态副本。原生保存帧已验证联合提出/双标签补图/普通无动作结算；无动作功能增量与长跑未验收。

访问关系若指向未声明本次观察归属的控件回复项，按原归属要求返回具名纠错，不再直接读取缺失region_index导致进程退出。该判断只约束明确的访问目标，不把普通旧控件知识更新的可选region_index变为必填。真实Clock停点副本可修正错位目标并完成登记；实机部署以运行记录为准。

参数引用读写（已部署，整体验收未完成）：功能参数只读解析统一归function_updates.resolved_constraints，功能目录与无scope页面知识披露都从当前控件事实读取；不将读取结果写回持久功能。修订功能时以最终supports/constraints校验，旧副本仅在该功能被修订时转成引用。支持替换不能留下不受支持的参数键；显式清空参数引用仍可用。原生历史整理1HTTP/0GUI验证存储引用及完整后读。

2026-10-25 控件知识描述统一：新knowledge项只要求description，必要页面/模式/限制写入正文，不再输出conditions；constraints仍可选，其他对象conditions不变。带知识项index修订，无index新增，完全相同内容复用。旧知识条件在control_knowledge.items读取时并入描述，历史原件保留；旧参数条件保留在其原参数事实以保持来源关联。两个聚焦检查通过，完整真实保存帧预览完成；实际Luna验证待记录。

本批最终验证：tests/test_control_knowledge_description.py 两项聚焦通过（pytest-v4），陌生审查及修订复审完成。正常历史蓝牙更新保存帧共6HTTP/0GUI；知识原答已不含独立conditions，并以description说明情境，身份复核same。但function_updates.supports持续填写非对象引用，正常登记未完成，整例未接受；失败原答和全部补框/纠错链保留。不修相邻功能引用合同，不部署。原活动src及设计文件为既有迁移未提交状态，不能安全单独暂存本批，未commit/push。证据artifacts/runs/control_knowledge_description_20261025_01，交付to_astra/control_knowledge_description_20261025_01。
参数原事实parameters与只读parameter_view分离，展示保留所属用途而不回写；同名参数按父用途区分，index修订的原观察before/after用于未变参数来源追溯。历史记录不改写，其他对象条件合同不变。

2026-10-28：`tools/repair_graph.py inspect/apply` 提供暂停旧图的功能恢复入口，详见`tools/repair_graph.md`。只恢复祖先快照中的已登记语义，要求支持控件仍在原区块，复用正常功能校验和快照发布；原source_call保留，支持证据从当前记录重建。计划/理由存新快照repair.json，旧证据和任务状态不改。它不修复任意身份/结论，也不自动补登记挂起动作。

2026-10-28 entry_identity判断随原实际动作保存；same经control_records.merge沿用历史控件编号、保留任务/执行历史并修正描述，different/uncertain不合并、不阻断有效异常或来源分离结果。page_history直接读取该判断，不另存摘要。

2026-10-28动作后功能材料候选：function_updates.attach可按refs展开，未选功能仅给名称引用目录；默认任务提出仍全展开。result_updater从实际操作及已披露任务的支持/功能引用选择，不改schema、system、功能写入权限。真实0146预览user9812→8535，默认共享行为对照通过，原生Luna待记录。证据artifacts/runs/update_material_focus_20261028_01。

动作后材料聚焦本批收尾：原0146完整原生保存帧1HTTP/0GUI一次正常登记，无纠错；17区块/Applications三个成员/路线保持，原任务continue。无function_updates原答，不扩大其验收结论。user9812→8535，总23673→22396；task_proposal默认attach对照一致，schema/system不变。原现场未部署；证据artifacts/runs/update_material_focus_20261028_01，交付to_astra/update_material_focus_20261028_01。源码为既有未跟踪迁移，未安全独立commit/push。

2026-10-28任务缺字段反馈：task_updates局部候选给出任务/decision/字段，schema描述条件，未改判定含义。5项相邻检查通过；原0192未改答复重放后1次实际Luna纠错正常登记，0GUI；首版脚本ledger遗漏导致预留193未HTTP，失败保留。用户进一步要求修通用机制而非逐错补丁，当前局部改动不视为通用方案完成/接受，不部署、不commit/push；待对齐统一条件合同与结构化反馈。记录artifacts/runs/task_missing_feedback_20261028_01。

2026-10-29导航任务交接候选：有待办的非当前区块导航改为从当前表面选择原任务动作/必要准备；旧导航none交回待办，不据此改前景或完成状态。参数/入口证据登记优先级保持，无待办纯导航保持原证据门槛。原任务目标历史候选由action_candidates提供，action_source_observation在投递前及登记核对唯一候选与原task_control/completion_region一致；坐标、遮挡和实际效果检查不跳过。8项聚焦通过；旧fixture/路径失效日志保留。原0126完整保存帧1HTTP/0GUI选择back准备关闭菜单，绑定原Open in Software任务；未执行该保存帧动作。现场原a0037待登记优先，新增最多10调用（204→214）运行中；完整结果待补。证据artifacts/runs/navigation_handoff_20261029_01。

2026-10-29 精简输出候选：跳转仅目标与必要条件，登记依据复用实际action_result.description；任务reason可选；参数map不要求重复name，内部由键补齐并保留来源；功能仅用途、支持与参数引用，旧object/completion/unconfirmed独有内容由同一description读取器合并展示。当前观察交接由实际结果/前景派生，不再要求模型重复摘要。原始历史不覆盖。已完成100现场HTTP及3次末动作登记收尾，25动作全登记。0280参数无重复name输入保留来源；旧独有交接可读。功能描述仍可能滞后、部分功能参数引用为空，完整图质量未接受；证据见lean_contract_20261029_01。

## 2026-10-29 控件树与应用操作树
`environment_context.links/structure/forest/local_progress` 是唯一派生入口：使用现有 jump_to 的登记来源和实际动作记录，保留条件与共享目标，已标记返回不画边，Cancel仍为控件。跨归属共享控件注明实际观察来源。目录包含范围外对象并标注；不据目录授权操作。每个区块展开一次，其他边引用，展示父级不等于物理parent_region或路由。操作树读取functions及其已有参数/支持引用，不推导完整业务流程。进度复用tasks.coverage。没有新增树账本或删除记录字段；旧3层/2兄弟截断展示退役。历史返回未标记时仍会误显为向前边，不用名称猜测修图。

2026-10-29：普通动作更新的动作归属与jump_to来源固定由上一步dispatch/binding决定，不再接受回复改选、来源拆分或入口合并。目标regions/controls及其知识由同次Luna更新并正常materialize；原任务归属保留。登记端移除对应改写分支，并拒绝旧来源变更payload。此约定不证明动作选择中的ID和坐标一定一致；该问题在选择/执行关联层，本轮不改。历史已接受快照与原回复不重写。


2026-10-29：格式重答保持业务role/schema，request.format_original_call引用首个实际业务请求；calls.business_request统一恢复业务请求，submission继续用最终未经改写的response登记。最终reply与原schema/索引一致已在Settings保存帧登记核对，1HTTP/0GUI；见runtime模块。


## 2026-10-30 固定任务终点
completion_condition作为Task自身事实随原对象存储保存，不另建条件清单或答案副本。活跃共享任务通过来源引用读取同一条件；解除共享时将该时点来源条件保留为本地任务条件，有本地尝试而存活的任务不会因移除共享引用丢失终点。普通task_update只判断进度，不修改原条件。旧记录不补写推断条件。
