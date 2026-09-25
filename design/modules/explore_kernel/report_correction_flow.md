# 报告纠正流程

2026-09-19 用户纠正失败范围：未知动作不再一律结束应用。仅在原生已知State/目标前景核验通过、无新清单待审且有活动依赖任务时，沿原scheduler将该任务deferred，保留Attempt.uncertain和覆盖缺口，丢弃同轮下一动作，由下一轮原Region调度选择独立操作。新/未知落点、外部前景、清单纠正未完成、无任务恢复继续原保护；未新增结果协议或重置次数。

2026-09-19：结构重复错误在视觉审核前交主作者，精确operations路径及现有同帧候选供inventory_edits使用；完成整批edits后统一预检，避免临时add/remove顺序误拒绝。Reviewer确认标志矛盾仍先由Reviewer修合同，合法普通负面意见再交作者；无新角色或预算重置。

2026-09-19：修正c33a2d3f的转交接线。Reviewer第一次合同错误计一次失败并精确修复一次，仍非法则将语义理由标为未确认线索，经原清单拒绝路径交作者（第二次失败）；原路径暂存同帧/Attempt的位置、回执和清单，实际主请求进入inventory_edits。编辑后复核成功才发布；第三次失败按原规则停止，不绕过/重置预算。同候选同证据的无效编辑复用拒绝，不再次请求Reviewer。假环境贯穿已覆盖实际请求→parent_ref编辑→复核新候选→登记→投递/结算；不代表实机通过。语义隔离仍只支持原资格/独立遗漏证明，不能靠一句“保留gap”准入任意语义争议。

2026-09-18：阶段提交要求由`contracts.submission_contract`产生，编辑轮不叠加普通结算修法；未知异常标为unclassified，不虚构previous_action字段。分区Reviewer自己的格式/协议/互斥证据错误返回原Reviewer，沿用共享预算；真实视觉拒绝仍交主Agent。编辑应用事实分为整批未应用、已改暂存候选、最终发布，不用“部分接受”代替暂存。替代GUI投递后撤下旧动作提案修正任务，保留历史拒绝和新动作证据。

2026-09-18：新分区协议允许仅独立handling争议在不耗尽纠错前进入受限清单；不使用`_settle_with_deferred_inventory`替新State绕过审核。原State/来源/结算检查照常执行，争议参与pending结果则拒绝；无owner待结算动作无法证明独立时也拒绝。原different及候选保留，旧输出不作新证明。身份、遗漏、归属、结果矛盾继续原有限纠正；Calc真实矛盾回执离线仍uncertain，无新GUI。

2026-09-17：同一当前来源绑定最近结果为uncertain时，fresh位置确认或无owner Back/Wait不能授权原样重投。阶段卡标为observe，动作校验拒绝；合法不同来源/新适用绑定仍可用。旧Attempt结果和次数不改，不新增已settled结果的持久化恢复协议。

2026-09-17 失败分层：已有独立动作结算/清单待补路径继续使用；模型客户端必须已有本次目标State/截图的视觉准入证据，整份分区视觉冲突不能当成独立遗漏绕过。当前动作最终uncertain时停止本应用，不能在同轮投递下一动作或因队列为空报complete；独立应用可继续。查询耗尽仅在位置可信、无pending/纠正时局部defer目标，既有同区/换区规则决定后续，不批量重排失败项。

2026-09-17：a8候选中的“无绑定＋无region_effects＋图片不同即拒绝”已去掉。结算不再以像素变化率兜底success；无绑定动作由已确认的位置改变或动作归因的Region效果支持。有效同尺寸解码像素完全一致仅作无可见变化证据，无法确认效果时保留uncertain，不把差异当身份冲突。原State审核逐区证据缺失/冲突通过原纠正卡交主Agent，修正screen可接受另一已知落点并继续本区；不清零次数、不重放GUI、不修改历史结果。

2026-09-17 Chapter接线修复：格式拒绝不再覆盖同一未修改候选尚未解决的清单意见。原纠正卡内unresolved_inventory绑定Attempt、截图SHA和候选SHA；任一变化不沿用，原分区审核接受后清除。原子编辑、原审核、原纠正上限不变。真实Chapter候选离线红绿及Luna保存帧2请求通过原审核；仅诊断，不追改或重放旧a7。

2026-09-17：pending纠正卡的`required_change`现在附带本轮完整具体错误说明（包括审核指出的遗漏和路径），不再只给field/expected/received；仅用于修正当前报告，不改变安全/动作合同。每次拒绝重建卡片，采用当前候选的最新理由，原三次预算、禁止新GUI、接受后清卡与耗尽退出均不变。原生请求级及相邻回归142通过；VLC a207保存帧保留已有2次拒绝，Luna收到最新详细意见后提交20项增量，但仍漏项，第三次审核拒绝并保守退出。反馈送达已验证，未证明清单修正链已稳定通过；原实机pending与现场未改。

2026-09-10：新清单入账前增加分区视觉预审；已清点State的跨图复用增加视觉核验，均使用现有Region角色和共享纠错预算。新增可空page_report_edits用于同帧字段纠正，严格API字段值用value_json编码。详见[增量纠正](report_edits.md)、page_inventory.md和location.md。普通提示语不能保证模型不改坏正确部分，增量编辑在程序中保留未改内容；仍不保证审核模型不会漏判。

2026-09-08。适用于模块化 Region 遍历主循环；不是对整个仓库所有异常已修复的声明。

## 规则

2026-09-09：已知 State 中独立合法的动作回执可与坏清单分离；候选清单保留为待补 gap，
不要求先修好无关清单字段才能继续其他可靠绑定。新 State/Region、错误 owner 或结果不可靠时仍阻塞。
待补内容在 status 中明确标示，不能成为动作依据；完整修复通过后才消除 gap，失败仍使用共享三次预算。

主 Agent 和 Element、Region、Operation Reviewer 共用三次失败预算：首次失败后最多再纠正两次。正常流程可能包含多个角色调用，因此不等于总 API 调用最多三次。它替代独立 pending 计数；runtime 调用主 Agent 时不再叠加内部格式重试。三次预算本身不新增CLI参数或持久Schema；新增的模型纠正字段见下文。

改写理由、候选排序、切换任务、单纯刷新截图不清零。报告通过检查后结束纠正。耗尽后不重审同页清单；已有真实动作进入不同 State 且画面发生变化时，可开始新报告。画面变化只用于防止无动作重开预算，不用于判断两个 Region 是否相同。

## 错误交给谁

| 触发 | 接收者 | 可以修改什么 | 退出方式 |
| --- | --- | --- | --- |
| 主回复格式错误 | 主 Agent | 指出的格式、字段和值 | 计入共享预算 |
| 主清单直接引用其他 Variant 的 Element | 主 Agent；不先调用 Reviewer | 候选归属、引用或分区 | 同上 |
| Element Reviewer 引用非法、重复、遗漏或结构错误 | Element Reviewer 的下一次输入 | 对应 decisions；不能确认可用 uncertain | 同上 |
| Element Reviewer 不能确认候选归属 | 主 Agent | 分区、具体控件描述和相关效果判断 | 不强制原候选保持不变；同上 |
| Region/Operation 审核回复非法 | 对应 Reviewer | 原候选编号对应的审核决定 | 同上；不提交半批身份合并 |
| pending 结算与清单冲突 | 主 Agent 的合同纠正卡 | 同步修改 screen、page_report、previous_action 的相关判断 | 耗尽保守结算并留下 failed gap |
| Element 审核证据读取失败 | 运行日志/操作者 | 修复证据或服务 | 停止，不让模型反复改清单 |
| Region/Operation 审核证据读取失败 | 运行日志/操作者 | 修复证据或服务 | 沿用已有保守结果，不批准无法验证的复用 |
| RegionVariant 对应多个 State 等账本不变量错误 | 运行日志/操作者 | 修复框架记录 | 停止，不交模型猜测修复 |

纠正期间不执行新GUI动作。清单解析或分区预审失败时，可在同一帧/Attempt内保留结构合法的位置提议和清单候选，供字段增量纠正；它们尚未发布到图，显式uncertain可重新判断位置。Element身份等需要重新判断来源的错误不冻结位置。真实ActionAttempt、attempt_ref和执行证据不能改写。清单/结算检查仍使用临时 ledger；独立身份合并也先校验整批。预算耗尽保留未解决候选、截图、错误和任务缺口；只有可信的已知位置才可继续其他已有绑定，不能宣称图完整。

## 检查与监督

检查路径是“错误产生处 → 捕获处 → 下一次实际输入 → 回复校验 → 停止或继续”，不能仅搜索 raise 后润色文字。主要代码是 `contracts.ReportCorrections`、`runtime._reject_observation_report` / `_handle_pending_report_rejection` / `_end_report_corrections`，以及 `region_review` 的三个审核入口。

监督每次核对：谁收到错误；他能改什么；下一次是否改了对应问题并通过检查；还剩几轮、何时结束。ledger 的 `report_correction`、`report_correction_delivered`、`report_correction_resolved`、`report_correction_exhausted` 记录接收角色、原因和轮数；结合原始回复看具体改动。通过结构检查不证明视觉语义正确，候选被删也不自动证明问题已解决。

离线证据：`tests/test_explore_report_commit.py` 覆盖跨角色共享预算、任务切换、无 pending 格式错误、事务回滚和耗尽后其他已知动作；`tests/test_explore_region_review.py` 覆盖 Reviewer 收到具体纠正及剩余预算；`tests/test_operation_centered_settlement.py` 覆盖 pending 释放。

保存案例重放使用 `artifacts/runs/settings_luna_safety_c68d8c82_20260908/calls/0072` 的主报告及 `0073` 的审核回复、账本和截图：el211 被错误用于 rv23。相同非法回复重复返回三次即退出，第二、三次输入含具体引用纠正；正式账本与原始证据哈希不变。结果见 `artifacts/replays/report_correction_20260908/result.json`。这是离线固定回复重放，零 API 调用、零 GUI 动作，不能证明 Luna 已会自行修正。

2026-09-11：显式--defer-partition-review模式将整页分区质量审核延后，不让该预审产生纠错阻塞或付费调用。接纳清单的质量缺口持久保留；结构/引用/位置/身份/结算错误仍走原纠错预算，不自动放行错误或增加重试。默认严格预审不变。

2026-09-19：同帧/Attempt的编辑轮额外保留最近一次different/uncertain审核意见及当时Region路径/名称/父级。主Agent格式错误不再遮掉待处理语义意见；原意见不是事实，旧路径不当作编辑后的当前索引，应用状态沿用原记录。只取现有审核缓存，不增加角色、次数或持久schema。普通/待结算两条原生格式失败→再编辑→登记路径通过，实机另记。
