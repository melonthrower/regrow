# 任务规划与登记

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

判断值得探索的新问题，维护任务归属、补充和清点状态。

## 输入、输出与边界

当前区块、截图、控件及已有任务 → inventory/evidence/operations。同一区块按控件身份+规范动作去重；任务名仅作说明，同绑定改名也沿用原状态、前置条件和历史；complete表示任务清点，不表示任务已执行。

主要接口：`task_proposer.plan_request / proposal_schema；region_tasks.apply_plan / commit_plan；entry_evidence.disclose`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

任务选择在 [traversal_scheduler](routing.md)，任务树渲染在 task_selection，单步结果结算与参数事实在 [task_settlement](updates.md)。region_tasks.coverage仍只计算已有记录的覆盖状态；region_tasks中的旧公共函数名直接导入唯一实现，不保留第二套逻辑。

## 源码与提示入口

- [task_proposer.py](../../../experiments/clock_manual_20260919/task_proposer.py)

- [region_tasks.py](../../../experiments/clock_manual_20260919/region_tasks.py)
- [entry_evidence.py](../../../experiments/clock_manual_20260919/entry_evidence.py)
- [traversal_scope.py](../../../experiments/clock_manual_20260919/traversal_scope.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [任务/区块探索任务.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/区块探索任务.prompt)
- [任务/任务登记与补全.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务登记与补全.prompt)
- [任务/历史入口与共享复用.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/历史入口与共享复用.prompt)
- [任务/任务粒度与反馈.prompt](../../../experiments/clock_manual_20260919/遍历prompt/任务/任务粒度与反馈.prompt)
- [输出格式/区块探索任务.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/区块探索任务.schema)

## 验证与未完成事项

2026-10-04单例保存帧诊断：Luna看出Add未显示，但complete未纠正地图，并新增跨区块重复目标。此为人工触发复核、1HTTP/0GUI；不是自动纠错成功。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#tasks)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 同绑定复用
同一区块中，同控件同动作沿用旧任务；不同控件或动作仍可有独立探索。参数值和任务名变化不重开任务；record/blocked也不因改名变为explore。需要纠正旧record判断时，报告具体缺口走记录修订，不伪造执行。未增加跨区块语义目标去重。

普通explore按已登记的真实动作更新状态：来源区块、控件、操作、成功投递及观察相符后记为done（已探索）；不再让模型额外判断任务完成。前置准备仍由当前条件观察结束，异常退出仍暂挂。详见[更新合同](updates.md)。

## 当前探索范围：实际功能优先（2026-10-05）

普通任务清点先区分实际功能与辅助说明。没有专门用户目标时，帮助、关于、快捷键列表等仅record；实际主要功能及改变操作方式的设置仍按未知内容探索。不能仅按名称跳过，也不能把推测的目的地写成事实。旧任务不自动删除或改为完成，仍沿已有复核边界。

由`任务/探索范围与退出.prompt`定义，`区块探索任务.prompt`明确优先级；普通/刷新/历史清点共用plan_request，纠错继承原完整要求。schema、登记、动作与更新协议未改。两例原生保存帧：菜单3项record；World五个主要入口explore。只是保存帧模型验收，无GUI；不代表控件错误、模板污染或自动重观察已修复。证据与有限结论见[本批说明](../../archive/current_control_task_scope_20261005/DESIGN.md)。

## 2026-10-06 最小遍历修复
partial/uncertain只描述清点覆盖。当前可信pending优先执行；没有可行动目标再补发现。相关discovery缺口沿原registration_gaps保存并参与inventory_complete，不能把已登记子集当成全清点。改名滚动选择登记后的规范任务；新观察明确提出继续移动时复用同一任务并排除此前尝试，不重开普通功能任务或历史图中的done滚动。

## 旧只记录判断修订
状态转换后的未知交互结构也需代表性探索，自动计数/默认当前时间不派内容任务。普通清点遇旧record遗漏可提出原绑定explore，框架拒绝后沿正常纠错reopen_task；只重开本地未执行record_only，保留旧判断、任务身份、控件/动作和事实，不靠改名重试。已执行及共享任务不重开。

仅数值或选中样式变化不构成新交互结构；缺少点击反馈本身不派探索任务。有具体价值的参数问题或转换后未知控件仍沿原规则调查。


## 连续批次后的滚动归属校验
真实任务提案曾把scroll挂到列表控件；正常滚动以区块control=None登记，无法与该任务结算。apply_plan现拒绝非空control的scroll提案，沿已有Runner纠错修正；不增加prompt、模型阶段或静默迁移旧任务。旧冻结运行保留原提案/错任务，不能称已修正旧图或实机滚动已验收。

## 角色与共享任务边界
TaskProposer拥有提示、schema、历史/控件及共享任务上下文；普通、范围复核、历史清点和纠错刷新沿同一plan_request。region_tasks保留正式任务登记、覆盖计算及较早的选择/结算出口；plan_request和proposal_schema只由task_proposer提供，普通纠错与观察修订直接调用它。
[shared_tasks.py](../../../experiments/clock_manual_20260919/shared_tasks.py)负责已确认共享关系上的任务定义/结果引用及失效清理。shared_controls.refresh先刷新关系再同步任务；shared_control_review.apply随后清理已失效继承。无本地证据的继承任务归档后移除，有本地尝试/发现的保留并阻塞复核，真实动作不迁移。

## 探索与原子操作总结（2026-10-07）
TaskProposer以三类具体信息需求提出探索：打开新入口认识功能、调查功能参数及条件、试操作用途不确定的控件。reason说明未知点、观察方式及拟收集信息；registration_kind标注产物类别，schema的single_action/parameter/scroll继续描述推进方式。区块探索结束后的原子操作总结另由region_functions承担，沿[知识合同](knowledge.md)组织完整用户目的及约束。提示用职责与产出说明两阶段的工作。

## 按探索产物登记结算（2026-10-07）
任务提出器用registration_kind区分entry（入口去向与功能语义）、parameter（参数事实）、control_effect（控件试探反馈）；task_type仍描述执行形式。动作提出与结果更新传递同一登记目标。参数事实沿用findings，入口语义在本次action.entry_registration及对应transition.entry_semantics登记，试探反馈沿用action_result。
结果更新先核对真实动作绑定，再核对本类产物。缺少所需记录且没有明确缺口时走原更新纠错，复用原前后图和回执；registration_gap记录具体信息不足并暂挂任务。next_action仍可据实际观察修正后续绑定，准备动作和异常仍沿原路径。没有新增完成审核调用，也不因补录失败重做GUI。只有本类信息完成登记才写新的completion_basis；模型不输出普通任务done。
入口语义必须对应本次新显露或变化的实际可交互区块；仅同时可见不足以作为去向。无变化且去向未知保留缺口。控件试探可以登记本次无可见变化；该记录不证明已确定功能含义。参数部分选项可以构成有效观察，不要求穷举；本任务明确未知尚未回答时保留registration_gap。结构校验不能保证模型视觉语义正确，需原生证据验收。
新参数record任务也需findings，任务reason不能替代参数目录。旧完成记录不批量重判；未标注registration_kind的旧parameter任务按参数产物处理，其他旧任务沿直接反馈结算，后续正常清点可给未完成任务补充明确类别。参数登记、明确缺口及调度已作有限原生/实机验证；新entry产物分支暂只有离线覆盖，旧入口沿用不能代替该分支验收。具体证据见月度记录。

共享任务传递registration_kind，复用结果同样核对对应登记；旧task_result_review入口不能凭模型done绕过新规则。参数依赖范围按registration_kind识别，保留旧parameter任务的默认解释。

等价任务也须具有相同registration_kind；同为click/single_action不足以替代参数或入口产物。region_tasks.equivalent_source/effective_task集中该判断，覆盖统计、任务树、纠错上下文及进度页共用。旧不一致引用投影为blocked并保留原记录，不继承代表任务done或其观察事实。

## 先探索再记录（2026-10-07）
有价值的未知直接提出探索任务。待完成findings是来源证据，不能作已完成控件知识；正常更新得到结果并结算后，task_knowledge按原任务归属维护control.knowledge。任务清点读取已完成任务知识，复用既有record/探索/暂挂机制；旧record任务不伪造执行，新字段缺失的旧任务不自动提炼稳定含义。
