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

2026-10-20：任务判断next_action显式null清空，continue省略保留先前建议；defer/answered不向后读暴露。新任务与旧判断分属operations/task_update，正常校验、纠错及登记共用新合同。may_open_content新输出只收boolean，历史未确认值不改写。验证范围见本月日志。

2026-10-20身份披露候选：`page_context.refresh` 对身份选择/比较保留内部 `page_context`，不再向正文补入第二份通用地图/历史；这两类角色的展示由冻结 pair/context 和 `prompt_material.identity_view` 负责。原始 provenance、任务/动作绑定及记录格式未改；共享与仅观察来源转为可读使用限制，而不是删除限制。其他角色刷新路径保持。本批只有离线候选检查，未进行原生登记验收。
