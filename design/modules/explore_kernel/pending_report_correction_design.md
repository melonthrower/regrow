# Pending 报告纠正与死锁收束

最后更新：2026-09-09

## 当前提交边界（2026-09-09）

`settle_completed_actions`将可选观察与必需动作事实区分：function_info中的不存在/前后不可见Region
不写memory，仅留下function_note_rejected事件；已知参数Operation的多余parameter_info留下
parameter_info_ignored_not_requested事件，不覆盖来源参数。合法owner动作可继续结算。
错误owner/primitive、unknown操作必需参数和代表项必需的有效Region说明继续拒绝；拒收可选笔记不能绕过这些检查。
这些事件随通过校验的临时账本提交，无效候选内容不进入功能图。新State身份、清单及Region效果校验保持。

下文早期的动作/清单一体提交对未知落点仍有效。已知 State 新增严格例外：
runtime._settle_with_deferred_inventory 在 page_report 错误时独立重做本地结算校验；
仅允许已有 State/Region、已绑定 Operation、合法 owner/primitive/参数/代表回执及有图证支持的 success。
未知 Region 或依赖未确认报告项的效果不放行；重复 report_index 只有明确指向同一已有 region_ref 时可消解。

动作和已知 Region 效果写入账本，坏清单只保留为 inventory_report_deferred 事件，pending 释放，
同轮 action 丢弃。未完成 survey 可 deferred，让其他已有任务继续；未接纳内容始终形成 inventory gap。
后续完整清点及身份审核通过才写 inventory_report_resolved；换页只重置纠正上下文，不消除旧缺口。
未知页面、错误 owner、无效果或不确定动作仍走原三次共享纠正/保守停止路径。

tests/test_explore_observation_boundary.py 覆盖继续合法动作、修复 gap 及不能放行的边界。
原 a4/a6/a7 保存帧在新流程回放后动作结算、清单仍待补；零新 GUI/模型调用，原记录未改写。

状态：2026-09-01 已实现结构化 settlement错误、合同纠正卡、两轮上限和保守释放。新鲜 supervised Clock partial run 中2个 settlement错误都在第一轮纠正后正常结算，0次预算耗尽、0次重复GUI动作；运行因另一 ambiguous Timer重复问题被Codex停止，不能替代完整或无监督验收。

## 目标

一个真实 GUI 动作只能投递一次。Luna 对其 before/after 的报告若不符合合同，框架必须指出精确
错误并只让 Luna 修正报告；同一 pending 不得形成无上限模型循环，也不得重复 GUI 动作。

## 结构化错误

settlement 不再只抛自然语言 `ValueError`。错误包含：

```text
code
field_path
expected
received
message
```

典型错误包括 owner 不在来源 Variant、owner/action 不唯一、primitive 不一致、function Region
不属于来源、参数缺少 completed owner、参数信息缺失或冲突。

runtime 将其投影为只读 `合同纠正卡`：

```text
pending_attempt_ref
error_code
field_path
expected
received
accepted_facts
required_change
forbidden
correction_count / correction_limit
```

纠正轮只修改卡片点名的 `previous_action` 或 `page_report`，不执行新 GUI 动作。
仅在当前清单已通过结构和Element检查、错误落在previous_action.region_effects时，runtime暂存该AgentTurn和后帧。
同一Attempt及完全相同截图的后续效果纠正复用它的位置提案和清单，给主Agent固定Region报告索引；
模型多报的清单改写只留审计。最终Region身份仍由原Reviewer处理，不能把临时清单当已接受图。
截图、Attempt或纠正字段变化、明确uncertain/external、纠正结束/保守释放/restore均清空，不跨观察使用。
不新增模型输出字段或重试计数；其他报告错误继续原路径。

## 本轮观察的提交边界

`bind_screen()` 已返回临时 ledger。runtime 在该副本上暂存动作结算，再检查本轮已提交的清单；
通过后才结束 pending 并执行既有预算收束。任一动作/清单引用或参数检查失败，恢复原图并保存真实
动作的 after 证据；不会把新 State、Region 或 Operation 完成提前保存到 checkpoint。
清单错误使用现有纠正卡，`field_path=page_report` 或其子项；计数仍绑定原 attempt_ref。
Element 审核不确定时，原错误文本现在给出报告位置、控件名称、Region/Variant 和 Reviewer 理由。
同轮提交的外来 Element ref 通过已有查找函数检查，并与未确认候选一起反馈；仍不接受 uncertain。
没有增加角色、输出字段或纠正次数，其他错误格式处理保持原样。
合法的不完整清单允许提交；未附带清单的合法恢复回执仍可先结算，再继续原来的 resume 清点流程。
后续独立的 Region 身份审核和下一动作授权保持原合同，不因下一动作被拒而撤销已接受的观察事实。

`screen.identity=uncertain` 不进入合同纠正计数：保持 pending 并取新截图，仍无法确定时沿用全局
模型轮次上限。模型请求 wait 时只等待并刷新观察，不再投递原功能动作。

## 两轮上限

- Luna 第一次合法 JSON 报告若 settlement 或已提交清单检查失败，返回一张精确纠正卡；
- 下一次报告仍失败时，框架不再调用 Luna；
- parser/schema 自身已有一次内部纠正；两次仍无法解析时直接进入相同收束，不启动新的 runtime 轮。

计数绑定 `attempt_ref`，不因 Luna 改写 reason 或错误文字而重置。

## 超限收束

超限后：

1. 保存 Luna 原始回复、结构化错误和 correction count；
2. 丢弃无法安全绑定的 completed/function/parameter 声明；
3. 用前后图现有保守差异把 Attempt 保存为 `no_effect` 或 `uncertain`；
4. 将本次实际 Operation/Task 标为 failed gap，防止相同动作被另一轮重新投递；
5. 清空 pending，下一轮取得 fresh screenshot 并继续其他任务。

框架不从自然语言 reason 判断成功，不伪造 Operation evidence。

## 2026-09-05 定点实机观察

固定 `e3ed04c1` 的 Settings a303 点击搜索结果后，真实截图已显示 Network，但本次报告仍未被接受。
主 Luna 将左上角实际的搜索图标报成 Back；Element Reviewer 正确返回 uncertain，其他10个候选均复用。
runtime 的第一条反馈只保留 `Element candidate remains uncertain`，未指出具体 Back 候选及模型理由。
下一轮又使用了来源 rv102 的 el1346 作为目标 rv10 中的导航控件，第二次被拒后预算耗尽。

最终 a303 为 uncertain，正式当前位置仍是 Date & Time；真实前后图保留，错误控件未写入正式图。
这证明拒绝与保守释放生效，也暴露了模型看图/引用错误及纠正信息不够具体的问题，不能把 GUI 已到达
当作清单已经合法。该次实机试验只记录证据，没有增加纠正次数或改写结果。证据位于
`artifacts/runs/settings_shared_route_live_e3ed04c1_20260905/route/`。

精确反馈现已用本次真实报告离线重放：同一条错误同时指出错误 Variant 的 ref 和未确认的 Back 候选。
保留旧格式错误处理和原纠正预算；没有新增通用错误处理层，尚未进行新一轮实机验证。

## 验收

- 同一错误报告重复二十次的 fake Luna 最多只被消费两轮；
- 始终只有一个 ActionAttempt，不增加 GUI action；
- 第一轮上下文含具体错误码、字段路径、期望和已接受事实；
- 第二轮后 pending 被释放，Attempt证据保留，实际 Operation形成 failed gap；
- 正确的第二轮报告仍能正常结算，不被强制失败；
- 已有动作拒绝、Page冲突、参数no-effect和Region identity上限保持不变。
