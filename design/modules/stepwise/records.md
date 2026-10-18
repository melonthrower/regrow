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

参数答案不再要求domain；新答案以description保存输入方式、范围和限制，条件并入description，保留框架关联的原来源归属；不再要求Luna重复填写findings.evidence。新文本更新同名综合描述，旧条件分支保留，Luna须保留仍然成立的内容；旧domain原样可读，不批量改写历史。撤回按原来源恢复，身份合并遇到不同描述先报告冲突。功能总结可引用无domain的约束。

新参数事实不再单列conditions，description包含已确认条件与对应行为；旧条件化事实不批量改写，同名旧条件分支保留，新综合描述与其并存，不把缺省字段理解为无使用限制。当前新描述按同名更新；补充时须保留仍成立内容，证据及历史依旧保留。功能总结输出不再要求拆出conditions。

对象观察与知识事件共存时，`observations.frame_observation` 按框架保存的 source_field、调用和观察时点选取对象登记；知识事件不充当本帧可见证据，不遮蔽历史截图。裁图、当前控件引用、入口可见性及历史清点复用此选择。归属复查按字段读取最近有效语义值，保留后来更新的知识。

2026-10-18功能任务与动作目标分离：新任务类型function/parameter，旧entry/control_effect在统一registration_kind读取为function，不改旧任务引用。功能完成产物为knowledge，参数为findings；任务更新不收entry。remaining_question替代输出registration_gap，旧审计通过只读接口保留具体缺口。
动作后更新可选destination={region_index,description}，序号解析到同次regions的新/旧稳定ID；确认实际执行和变化后由store_object_entry写入实际操作对象的既有entries。关联在任务条件处理后保存，但不按父任务控件归属。仍同次事务发布，不将失败回复部分保存为已接受事实。

2026-10-18控件用途分层：识别输出possible_purpose、may_open_content、needs_exploration，后两项boolean/null，登记到控件及观察来源；控件识别不再写knowledge。knowledge由正常任务结算保存，confirmed_information按已接受来源读取，旧未分层用途保留为历史判断。身份合并保留确认知识，不把旧猜测拼成确认结论；导入只接受有明确依据的旧任务答案。上下文通过purpose_text转短句，已有确认功能优先，不重复同义猜测。任务是否未完成与用途判断分开，needs_exploration=false不自动关闭任务。

历史答案核验先确认source.task_region及绑定任务的完整ref，而非比较source任务键与通用task.name；相同“功能探索”标签不意味着同一任务。随后仍核对实际控件、披露的历史动作、回执、观察来源、失败和条件。当前帧观察也不得绕过任务绑定检查。

旧用途读取根据来源区分：匹配到discovery观察的历史描述作为推测；已接受任务知识显示已知功能；缺少确认来源才标注“历史用途（缺少确认依据）”。共享知识说明明确服务后续指令与导航，关联结果只描述实际控件有依据的作用，背景同步变化不当因果。

2026-10-18：destinations替代新输出destination，数组目标为本次region_index及可选control_index（本次controls行号）。正常对象登记后解析稳定目标，entries沿用原存储并增加可选control目标；去重/合并/后读区别同区块不同目标。实际动作来源由框架绑定；访问方式是已验证路线，不要求每次重做。原历史区块entries仍可读取，不迁移旧运行。
