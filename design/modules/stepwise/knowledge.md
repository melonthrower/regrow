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

## 本地知识与逐层披露
一个Region可以承载多个用途、多个独立功能；region_role不限制功能数量。local_knowledge保存本区块自己的summary、可配置parameters、带本地任务依据的conditions，functions分别保存独立目的。动态时间、当前选中值等仅保留原任务/动作证据，不写成通用摘要或固定完成条件；旧混合facts仍需模型按证据甄别，不能声称已经全图规范化。

function_scope.disclose按需读取本区块自身知识/functions和直接入口的目标card。card只含目标自身简述与状态，不嵌套目标入口、参数或动作；没有知识/功能记录的区块标not_summarized；有旧知识或functions但签名已失效时标needs_review，保留旧正文并标明待补充状态，不代表新任务已完成。不用动态description冒充稳定摘要。page_context在当前区块展开自身知识，目标只露一级；读知识不证明目标当前可见或可操作。

region_functions正常输入为本地任务登记产物、控件用途标注、紧凑动作结果/入边及缺口、入口一级摘要。原图/动作全量仍在账本；紧凑材料保留实际反馈、失败、未确认归属和来源。function_scope.parameter_support只展开本地参数任务明确到访/打开的目标参数任务及显式事实来源，不递归展开参数子区块，不把普通邻居的全部任务加入引用目录。

每项functions至少有同目的本地支持任务；可选明确外区块参数支持，仍保存原support_tasks/constraints来源，不搬迁控件任务。单区块总结可以有零项、一项、多项功能；参数表面也可仅保留自身参数知识。现行参数目录没有的定义保留缺口，不凭名字补造值域。

完成门槛继续用本地coverage，不等待子区块完成。目标摘要/未采用的邻区细节变化不使父区块重总结；本地任务产物、任务明确attempts关联的探索效果、条件、入口及已采用外部支持改变才触发复核。临时控件text/state不作为摘要刷新依据。实际发送材料的request_signature仍完整核对，拒绝发送后变化的旧答案。

身份细分/合并归档旧local_knowledge并清除当前记录，等待重新总结。只读披露不递归写回父区块，环路不传播知识。新合同验收范围与未接受项见2026-10月日志；未部署到既有活动运行。

参数说明由同次parameter_definitions按已有ref归纳稳定description/conditions；local_knowledge和functions选中的参数必须提供定义，登记使用该说明而不复制旧fact中的当前观察文案。原值域和来源证据保持不变，动态实例仍可能出现在明确标记的历史来源中。该步骤不补造缺失参数、不纠正旧值域，无法确认的映射和范围保留unconfirmed。

总结不输入旧functions名称，避免把旧归组当作新归纳的依据；原记录仍保留在历史快照。多个独立目的可重新命名，本批未引入功能ID迁移层。

## 总结之前的知识登记（2026-10-07）
探索结果已在task_update区分稳定knowledge和当前状态，完成任务知识由task_knowledge归入控件；总结按已有证据组合用途，不再另写local_knowledge.unconfirmed待确认清单。functions.unconfirmed只说明证据边界。旧事实仍可在总结中整理稳定参数说明，不声称旧图已批量转换。


## 2026-10-07 区块任务批次与跨区块前景候选
本区块已有可见控件须完成清点，所有本地探索任务结束后才能总结；后续新增一批任务时保留旧摘要并标needs_review，整批结束后更新，不逐任务总结。已采用的外区块参数支持变化时，也等该来源区块本批工作结束再更新。普通关闭/退出等未增加探索产物的动作仍保留证据，但不使摘要失效；有稳定任务knowledge时不因观察文案改写而失效。入口目标摘要仍按一跳引用读取，不递归重写父区块。明确常识用途record可直接进入知识，不要求额外点击验证。

失效依据仅采用探索任务明确关联的attempts及正式knowledge/参数变化；同一已探索控件后来只作导航，不因动作本身再总结。请求仍披露真实历史结果，发送期间的完整材料由request_signature保护。


## 2026-10-08 实例共享与动作归属
城市名称等试样输入登记为text参数，样本和动态候选写evidence/动作观察；text/time/integer的domain.values不进入稳定事实，原始输入值仍在findings.observations及原答。enum仅保存稳定选项而非搜索返回的数据实例。完成共享任务的控件知识沿shared_result单跳读取真实来源，标记shared/local_execution=false；Region总结可读共享控件知识，不复制实例状态。
本批验证状态见2026-10月变更日志；保存帧不代表新增GUI执行。


## 控件条件知识（2026-10-08）
控件知识及已登记操作带conditions；入口entry_semantics本有条件，历史入口和共享投影也必须披露。共享目的地冲突按同条件比较，不把不同条件下的不同功能自动当作冲突。代理仅同步无本地尝试的条件定义，有本地证据的条件不改写；共享完成仍核对实际动作条件。区块摘要仍只披露一级目标，不递归复制邻居知识。

## 后来动作回答旧问题（2026-10-09）

完成的本地用途知识source附completion_basis，指向真正回答问题的实际动作；旧尝试不改写。已回答任务的conditions采用本次登记条件，有限条件观察不能成为更宽知识。未提交/未回答的任务不生成控件知识，准备动作不生成原输入规则。
