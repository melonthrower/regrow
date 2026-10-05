# 结果更新与登记

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

更新图、任务结果与观察来源，发布完整快照。

## 输入、输出与边界

真实回执、动作前后图和原任务 → 新观察、动作结果、任务结算与快照指针。提交成功不等于视觉语义正确；原始证据和旧快照保留。

主要接口：`update_step.build_update_request；register_update.commit_update；task_settlement.settle_task；task_result_review`。详细现行合同见[原模块文档](../stepwise_region_identity.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [task_settlement.py](../../../experiments/clock_manual_20260919/task_settlement.py)
- [region_evidence.py](../../../experiments/clock_manual_20260919/region_evidence.py)

- [update_step.py](../../../experiments/clock_manual_20260919/update_step.py)
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
