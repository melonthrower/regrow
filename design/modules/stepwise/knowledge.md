# 功能知识与完成

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

整理区块功能，区分清点、任务和图的完成状态。

## 输入、输出与边界

Region、任务及有效执行证据 → 可复用功能、条件和覆盖说明。无待办、record_only或同类覆盖不等于所有功能已实测。

主要接口：`region_functions.request；function_evidence；coverage_exemption；region_graph`。详细现行合同见[原模块文档](../stepwise_discovery_completion.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [region_functions.py](../../../experiments/clock_manual_20260919/region_functions.py)
- [function_evidence.py](../../../experiments/clock_manual_20260919/function_evidence.py)
- [coverage_exemption.py](../../../experiments/clock_manual_20260919/coverage_exemption.py)
- [region_graph.py](../../../experiments/clock_manual_20260919/region_graph.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/区块功能登记.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/区块功能登记.prompt)
- [功能识别](../../../experiments/clock_manual_20260919/遍历prompt/功能识别)
- [输出格式/区块功能登记.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/区块功能登记.schema)
- [更新/重复入口覆盖复核.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/重复入口覆盖复核.prompt)

## 验证与未完成事项

功能整理和共享依据有保存帧验证；完整遍历、跨应用鲁棒性与研究目标未据此全部通过。指令合成/轨迹采集独立消费冻结图。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#knowledge)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 区块探索结束后总结原子操作
traversal_scheduler.select_work通过region_functions.next_ready选择已结束探索且总结证据已变化的区块，沿现有function_registration请求、Runner纠错和commit登记。无需全会话空闲或返回该区块；已投递未登记、发现及恢复继续保持优先。一次小步最多整理一个区块，必要时下一轮继续，HTTP计入原预算、总结本身0GUI。

沿用region_tasks.coverage：已有控件清点完整、无有效pending或blocked时可总结，record_only无需执行；这是已有清点范围，未发现功能不据此声称完整。新增任务或事实使原摘要过期，任务结束后再更新；同一证据不重复调用。功能登记失败仍沿原registration_gaps局部暂挂，其他工作可继续。

探索任务按新入口功能探索、功能参数探索、不确定控件试探组织信息需求。原子操作总结按最小完整用户目的组织对象、完成结果、支持任务、可配置参数和条件；一个目的可有多个控件步骤。参数表面保留事实及支持说明，可以没有独立原子操作。region_role描述表面用途，functional/mixed也可有空functions；navigation仍为空。现有任务、参数来源、控件身份及真实图边保持原归属。

historical_inventory和auto空闲阶段复用同一next_ready，并继续承接历史任务补清点；无需新增信息充分性审核。离开区块或会话预算结束均不等于全应用完成。真实模型与GUI验证范围见本月日志。

## 主区块与跨区块依据
原子操作仍存于业务主区块functions。function_scope.related_regions提供真实直接连接、任务到访和参数来源；沿明确参数任务关联递归取得多级支持材料，不以首次进入树推定业务后代。Luna按共同对象和最小完整目的选择支持事实，图连接仍是上下文候选。

请求提供相关区块任务状态、控件、参数和动作结果；仅done/record_only的有效本地支持任务进入引用目录。本区块引用沿用任务名，相关区块为“region / task”，参数为“region / task / fact”。register核对来源任务与参数对应，functions.support_tasks保存全部结构化region/task，task_refs保留主区块本地任务名，locations保存各自实际位置。远端任务/控件/动作不迁移，本区块事实、可引用任务/参数及实际采用的远端(region,task)内容、控件语义和相关动作变化参与证据签名刷新；未采用远端的单纯导航动作不触发重算。未完整探索的相关区块按实际状态披露，未知约束保留待确认。

现有历史findings未记入的参数不会凭控件名称自动成为constraints；此限制须与能力描述和后续事实补登记分开报告。

每项原子操作至少引用一项主区块本地支持任务；相关区块可补充同一目的的步骤、参数和结果。提示要求本地任务实际参与同一业务目的，不用无关任务凑引用。全部支持来自外区块时，register沿原纠错入口拒绝，尚未写入目录。结构门槛仍不能自动证明业务语义，真实总结须核对。旧v12把添加对话框操作挂列表区的原答保留为失败证据。

请求提交单独核对完整发送证据的request_signature，避免回复新增采用的远端依据已改变却漏检；摘要是否重算使用选择性signature。非当前区块的总结纠错刷新读取已登记知识，不要求重新进入该区块。

总结控件语义统一取semantic_observation的最新正式观察，忽略visual_backtrack追加的visual_only临时定位行；本地、相关区块与已采用远端支持共用。临时位置仍供动作请求使用，不改变语义来源和总结签名；正式新观察仍使摘要失效。
