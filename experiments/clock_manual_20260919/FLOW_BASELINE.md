# Region逐步遍历基线

当前用户认可的实验顺序：首次观察→选择一个入口→监督者核对目标/后果→真实执行一次→前后图核对及Region增量→暂停。后续从选择入口继续，不重复首次全页识别。目标和动作由Luna选择，不编码Clock、Timer或菜单顺序。

## 每阶段合同

|阶段|模型输入/输出|程序职责|
|---|---|---|
|observe，首次一次|新图、已确认观察指令；Region/控件候选、排除项、未知|分配ID、原答/图片/裁剪落盘|
|choose|新图、当前候选及相关实际历史；唯一动作建议和目的/影响|保留提议，不提前登记成功边|
|execution，零模型调用|Luna建议，延续本次人工目标/后果核对|先登记pending，再投递一次并保存前后图/回执；失败不自动重放|
|settle|真实前后图、投递记录、相关旧Region；动作结果与Region增量|保存新增/复用候选、动作关系和不确定性，暂停；不自动开始下一动作|

不添加Page/State身份调用、默认Reviewer链、全清单完成门槛、隐式模型重试或自动纠正循环。发现问题先记录并讨论流程变更；单纯拆prompt文件不改变调用次数。预算在程序中记录，不进入Luna提示词。

## 图关系

原图快照的action_edges已有source_region/source_control/attempt/after_interactive_region_proposals，但缺少直接可读的目标字段。stepwise_flow.region_transitions只读投影为每个明确目标一条关系，保留同一个真实attempt和前后观察/图像/调用来源。

本次为 r0001 --c0001 / a0001--> r0003。r0002作为背景变化注释，不产生边；不猜逆向边。关系名称reaches_observed_interactive_candidate表示动作后观察到的可交互候选，不自动证明所有目标都由动作新建、功能因果或模态输入边界。无效投递/结果uncertain不产生已观察跳转；原失败/不确定证据仍在原图中。

## 框架副本与验证边界

framework_copies/region_stepwise_20260919_01/ 保存当前工作树gui_rewalk与tests的Python文件、requirements及实际prompt/脚本，source_manifest记录来源提交、未提交差异与文件hash。没有复制私有配置、数据、缓存、依赖链接；不能把这份副本当作干净提交或完整可部署环境。

stepwise_flow.py是可执行阶段顺序控制器，沿用传入的模型、执行、记录适配器；replay_stepwise_baseline.py 用副本中的驱动器重放3份原始请求/回复和1份真实动作回执，检查没有新增阶段、动作选择未改变、原始证据未改。它不导入API或ADB。

重要限制：完整实时输入构造、跨轮历史选择及旧落盘脚本尚未统一接入这个阶段驱动器；原脚本保留为基线证据，其相对路径不能当独立副本启动入口。下次实机接线必须复用这里的阶段顺序和相同prompt/输出合同，并先核对适配器输入与原实际请求的一致性，不能宣称当前已完成自动遍历引擎迁移。阶段驱动器可重新启动的resume/多轮路由也未实现，本次不加额外功能。

验证：13项聚焦离线测试通过；原3模型调用/1动作离线重放一致；本轮0新HTTP/0新GUI。复制清单逐文件hash一致。新图关系为派生视图，不改旧快照；区域语义不确定性仍保留。

2026-09-20：副本stepwise/已同步本目录维护的登记/上下文实现和prompt；原stepwise源码先存入source_history/before_region_knowledge_20260920_01。初始source_manifest仍表示复制当时的基线，当前stepwise哈希另见current_source.json；副本gui_rewalk基线未变。实际统一登记由该副本执行，结果见records/015_region_knowledge_20260920_01，0新模型/0GUI。
