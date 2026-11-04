# 具体代码位置与拟议改动表

公开活动源码基线：[12da7a88](https://github.com/melonthrower/regrow/tree/12da7a88b783ef9b9299f173fdb4dccd47b5e88d)。实际运行文件固定到证据提交[a203bf28](https://github.com/melonthrower/regrow/tree/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7)。本表是讨论用改动地图，**全部拟议修复均未实施**。

|实际运行文件、函数、行号|代码当前行为|拟议讨论/改动范围|
|---|---|---|
|[src/regrow/recognition/named_references.py::_display_owners，78–99](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/recognition/named_references.py#L78-L99)|C1:补丁只为实际来源共享控件选择展示位置；另一个知识修订控件仍可能无位置。|修复调用局部呈现归属与共享引用的兼容；不改全局控件身份。|
|[src/regrow/recognition/named_references.py::encode_objects，167–204](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/recognition/named_references.py#L167-L204)|C1:无region_index时必须得到一个展示位置，否则抛异常。|讨论合法共享知识修订的无唯一展示位置分支；不伪造物理owner。|
|[src/regrow/traversal/register_update.py::commit_update，61–281](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/register_update.py#L61-L281)|C1/C3/C4:动作、知识、功能与任务在同一发布路径；功能更新先于任务结算/快照发布。|先讨论事实登记与附带功能整理的责任；保留真实来源/回执/图身份校验。|
|[src/regrow/records/function_updates.py::apply，91–126](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/records/function_updates.py#L91-L126)|C1:功能增量引用/支持范围校验可抛错。|定位错误引用生成/呈现链；若拆责任，明确失败功能更新如何保留续接。|
|[src/regrow/traversal/attempt_guard.py::check，11–51](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/attempt_guard.py#L11-L51)|C2:同任务和表面内，同入口/动作/文本历史达到阈值即拦。|以已有状态和真实过程区分重复试探与有用恢复；不简单放宽所有重复。|
|[src/regrow/runtime/action_executor.py::ActionExecutor.execute，44–131](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/runtime/action_executor.py#L44-L131)|C2/C3:投递前还会检查目标身份，真实投递另存回执。|核对误拦与真实执行的边界；保持未知动作不重放。|
|[src/regrow/traversal/result_updater.py::build_attempt_update，130–233](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/result_updater.py#L130-L233)|C3/C4:由真实来源/任务和前后图构造请求；0207已供给9999及回执。|参数供给已经存在；讨论模型仍改写后的事实保留、知识文字与登记责任，分开界面显示和参数接受状态。|
|[src/regrow/records/task_updates.py::decide，97–139](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/records/task_updates.py#L97-L139)|C4:检查硬阻塞/产物后，answered可转done并保存判断来源。|对照原completion_condition改进语义判断材料/责任；不是靠任务数或点击数自动完成。|
|[src/regrow/records/task_settlement.py::settle_task，251–285](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/records/task_settlement.py#L251-L285)|C4:处理结果的任务结算入口。|保留原任务归属与实际准备对象分离；以原问题核对答案。|
|[src/regrow/traversal/task_proposer.py::plan_request，41–120](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/task_proposer.py#L41-L120)|C5/C6:构造当前范围的已有认识和任务问题。|提供相关共同用法与候选范围线索；先明确收集目标再改Prompt。|
|[src/regrow/traversal/region_tasks.py::apply_plan，14–124](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/region_tasks.py#L14-L124)|C5:本地同控件同类型任务去重，调用共享实例处理。|检查跨层级共同用法复用；不同实例身份和独立功能保持。|
|[src/regrow/records/shared_tasks.py::synchronize_tasks，10–114](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/records/shared_tasks.py#L10-L114)|C5:同步明确共享关系的任务。|检查既有共享机制能覆盖什么，避免另建重复知识表。|
|[src/regrow/traversal/inventory_scroll.py::select，11–27](https://github.com/melonthrower/regrow/blob/a203bf289d4cd0c6a7c3ee653aa9510df5e812e7/issue_cases/20261104-traversal-design-and-wiring/runtime-source/src/regrow/traversal/inventory_scroll.py#L11-L27)|C6:inventory为partial时选继续的区块任务，跳过带控件的operation；不是候选列表滚动执行器。|调查候选列表能否沿已有动作选择/平台滚动链继续收集；本select不证明该路径已接好，先明确有限候选的未知范围。|

## 验收案例（尚未新跑）

|案例|应验证的行为|
|---|---|
|C1 GIMP0337–0339/Writer共享修订|按正常框架完整上下文接续原回复，真实知识和任务能按确认后的合同登记；不重放GUI，不把坏引用静默写入。|
|C2 VLC0253–0255|允许证据支持的原值恢复；相邻无新依据的原样重复仍能停住。|
|C3 VLC0206–0207|投递9999、界面显示99.000及接受状态未知分别保留；不能再写成本次输入999。|
|C4 GIMP0284|对照原问题，未弄清约束用法时不以一次“不保持比例”错误done；异常事实仍保存。|
|C5 VS0164–0165|已有共同用法的同类目录免重复；真正新条件或独立文件操作仍可探索。|
|C6 Writer0173|有限候选还有未见部分时保留收集问题；连续数值不因此逐值穷测。|
|正常对照 VS0196|保留看到未保存关闭提示即可回答原任务，不扩大成必须选Save并完成整个流程。|

模型行为验收需用原生入口构造完整真实上下文和截图、原答走正常校验/纠错/登记；静态检查只核对本讨论包的文件/链接/锚点，不代替新行为验收。

新增文件：本目录README、DESIGN_DISCUSSION、CHANGE_MAP、VERSION、evidence、graphs、runtime-source均为新讨论/证据文件；不虚构既有行号。当前维护源码路径仍是仓库根src/regrow，不能在runtime-source证据副本上开发。
