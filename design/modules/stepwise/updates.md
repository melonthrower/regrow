# 结果更新与登记

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

更新图、任务结果与观察来源，发布完整快照。

## 输入、输出与边界

真实回执、动作前后图和原任务 → 新观察、动作结果、任务结算与快照指针。提交成功不等于视觉语义正确；原始证据和旧快照保留。

主要接口：`result_updater.build_update_request / route_update；register_update.commit_update；task_settlement.settle_task；task_result_review`。详细现行合同见[原模块文档](../stepwise_region_identity.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [result_updater.py](../../../experiments/clock_manual_20260919/result_updater.py)

- [task_settlement.py](../../../experiments/clock_manual_20260919/task_settlement.py)
- [region_evidence.py](../../../experiments/clock_manual_20260919/region_evidence.py)

- [register_update.py](../../../experiments/clock_manual_20260919/register_update.py)
- [update_visibility.py](../../../experiments/clock_manual_20260919/update_visibility.py)
- [registration_diagnostics.py](../../../experiments/clock_manual_20260919/registration_diagnostics.py)
- [task_result_review.py](../../../experiments/clock_manual_20260919/task_result_review.py)
- [parameter_evidence_review.py](../../../experiments/clock_manual_20260919/parameter_evidence_review.py)
- [update_semantic_review.py](../../../experiments/clock_manual_20260919/update_semantic_review.py)
- [knowledge_transaction.py](../../../experiments/clock_manual_20260919/knowledge_transaction.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [流程/03_结果核对.json](../../../experiments/clock_manual_20260919/遍历prompt/流程/03_结果核对.json)
- [更新/动作后观察与状态更新.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/动作后观察与状态更新.prompt)
- [更新/区块变化与字段.prompt](../../../experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt)
- [任务/任务动作登记.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务动作登记.prompt)
- [输出格式/动作后更新.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/动作后更新.schema)

## 验证与未完成事项

更新步允许必要前后/历史图，不把动作步单图约束套到更新。Stopwatch虚报Add及Timer单位推测写实尚未通过验收，不能因Runner完成宣布修好。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#updates)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 绑定动作驱动探索进度（2026-10-05）
普通更新保留地图和action_result，任务部分改为task_update：findings保存本次参数事实；next_action通常为null，只有新观察证明原绑定不合适才给出region/control/action/reason。Luna不输出普通任务done/pending，也不替同次动作逐个判断其他任务。

commit_update先附实际operation与输入回执，再由task_settlement匹配任务并写completion_basis；同一次确认动作可覆盖历史重复名。只有聚焦、对象未确认、其他控件/动作或缺观察不能完成原任务。参数事实保存实际来源；其他对象事实保留在动作层，不冒充任务控件参数。next_action保留旧绑定和历史，不消费修正前动作。

正常续接的reconcile_run只复用已提交同绑定动作，无模型调用；前置准备及有blocker的任务不被历史点击结束。prepares仍由task_prerequisites的本次条件观察结束；unexpected_exit保留既有异常暂挂。暂挂解锁、归属修订及显式历史修复仍有专门入口，普通调度不再发累计完成复核。

旧未完成请求仍保留原schema/原答，登记只读取其中参数事实，不信任旧task_result.status。归档补登记检查可能受影响的任务区块，不用历史后图替代当前位置。

## 回执与补充参数事实
新请求不含exploration_update：程序读取真实receipt，Luna只观察结果。旧保存请求仍按原schema读取，不批量改写；模型复述状态不覆盖执行回执。task_settlement.partition_findings逐条筛选可分离参数事实，坏行记finding_gaps/parameter_gaps并保留reported及原回复；有效事实与真实动作继续登记。普通与纠错wrapper共用此规则，身份、归属、next_action和action_result错误仍拒绝。

区块name/description写稳定结构职责；时分、日期、临时气泡和这次选中状态留在本次foreground/动作观察，不担当长期身份描述。旧证据不批量改写，也不正则删除数字；合法选项/约束与任务相关的真实结果可保留来源。可选模板拒绝不影响独立可靠动作登记，实际前景、点击框与身份冲突仍严格。

## 结果更新组件（2026-10-06）
ResultUpdater.update/resume共用原build_attempt_update/resume_update_request与Runner，
正常更新和中断补账沿同一校验/纠错/register_update/task_settlement。complete在
正式登记成功后保存attempt/commit并清理execution_pending；失败保留pending。
观察判断与正式登记仍是内部两道边界，未合成一次无校验写入。
run_task_step旧同名辅助入口直接导入唯一实现，保存帧工具可继续调用。

ResultUpdater直接持有结果请求/schema和候选校验；调用方统一进入result_updater，旧update_step转发文件已删除。候选路由不正式发布；register_update仍基于真实回执、身份和任务结算写新快照。

## 按探索产物登记结算（2026-10-07）
任务提出器用registration_kind区分entry（入口去向与功能语义）、parameter（参数事实）、control_effect（控件试探反馈）；task_type仍描述执行形式。动作提出与结果更新传递同一登记目标。参数事实沿用findings，入口语义在本次action.entry_registration及对应transition.entry_semantics登记，试探反馈沿用action_result。
结果更新先核对真实动作绑定，再核对本类产物。缺少所需记录且没有明确缺口时走原更新纠错，复用原前后图和回执；registration_gap记录具体信息不足并暂挂任务。next_action仍可据实际观察修正后续绑定，准备动作和异常仍沿原路径。没有新增完成审核调用，也不因补录失败重做GUI。只有本类信息完成登记才写新的completion_basis；模型不输出普通任务done。
入口语义必须对应本次新显露或变化的实际可交互区块；仅同时可见不足以作为去向。无变化且去向未知保留缺口。控件试探可以登记本次无可见变化；该记录不证明已确定功能含义。参数部分选项可以构成有效观察，不要求穷举；本任务明确未知尚未回答时保留registration_gap。结构校验不能保证模型视觉语义正确，需原生证据验收。
新参数record任务也需findings，任务reason不能替代参数目录。旧完成记录不批量重判；未标注registration_kind的旧parameter任务按参数产物处理，其他旧任务沿直接反馈结算，后续正常清点可给未完成任务补充明确类别。参数登记、明确缺口及调度已作有限原生/实机验证；新entry产物分支暂只有离线覆盖，旧入口沿用不能代替该分支验收。具体证据见月度记录。

共享任务传递registration_kind，复用结果同样核对对应登记；旧task_result_review入口不能凭模型done绕过新规则。参数依赖范围按registration_kind识别，保留旧parameter任务的默认解释。

历史参数补录继续由原parameter_evidence_review移交任务提出器，在task.findings登记带来源事实；显式历史复核同时要求真实匹配动作。补录不改写旧action.parameter_findings。准备任务只由dependency_updates条件观察结算，历史done意见也不能代替。

参数事实只记录业务操作可配置输入属性；按钮显隐、运行/暂停等直接反馈保留在action_result或record依据。conditions保存可复用适用规则，evidence保存本次菜单展开、选中状态及未执行边界；source-v7原生初验发现二者混杂，source-v8正常请求/原答登记复验已分开；旧事实保留原证据，不批量改写。

已有实际回执及观察、关联仍unconfirmed且候选明确包含原任务目标的尝试，由正常reconcile转为ownership review缺口，清理active_task后调度其他工作；不赋予确认控件、完成状态或重新投递许可。不同候选、已排除旧尝试、准备任务和异常仍保留原边界。此改动针对Clock已开编辑页但父任务反复none→发现的实机循环，验收见本批日志。

未确认动作关联的ownership缺口当前没有完整自动补录入口；这只解开其他工作的调度，原任务仍未完成。早期reconcile在待更新/导航续接之后、循环检查之前同步记录，避免沿旧pending状态触发无意义循环纠错。

纠错上下文与覆盖统计共用region_tasks.effective_task；等价引用若要求不同登记产物，披露blocked和本任务缺口，不借用代表任务的完成状态/观察。

## 完成任务知识与本次状态（2026-10-07）
task_update.knowledge提供稳定用途/规则，当前值在controls.state及原action_result；所需信息未得到时knowledge为空，沿next_action或registration_gap保留原探索任务。task_settlement完成后才发布控件知识；新格式空knowledge不能只因点击就结算。task_knowledge.refresh由普通发布和动作更新共同调用，Region.current_observation仅存本次语义观察控件，未观察不等于未变化。没有新待确认字段或独立完成审核。


## 2026-10-08 实例共享与动作归属
任务参数登记在store_findings时就分离非枚举样本值与稳定domain；不是等区块总结才清理。原始observations和动作证据保留；同类实例共享只复用知识，不将代表的实际点击和目标区块转移给其他实例。
本批验证状态见2026-10月变更日志；保存帧不代表新增GUI执行。
