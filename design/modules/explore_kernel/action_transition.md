# 动作、自动结算与连接

2026-09-18：`owner_confirmation.v1`沿用owner_ref，唯一可信当前任务/路线候选用`@current`表示Luna在现有请求中的视觉确认；kind/target/direction须与候选一致，程序填owner/Operation/purpose。输入文字等缺少确定参数的分支不提供该候选。绑定时重查任务、State、帧、真实图关联和唯一性，随后走原平台、范围、前景及动作检查；模型选其他owner不会被替换。原回复与生成绑定事件分别保存，旧owner格式及历史动作不改。Operation误填owner时反馈真实类型及适用图关联，不按数字后缀推导；替代动作真实投递后旧错误只留历史，当前只结算新Attempt。

2026-09-09：显式exploration_goal下不再自动派发旧Operation待办或替换焦点；保留已选活动任务和必要survey，其余由主Agent按范围用next_operation_ref或实际owner动作选择。无Task时可用当前唯一recorded/verified绑定恢复，仍保留绑定与近重复检查。无动作、无新事实的范围决策以scope_idle/partial结束，不冒充全应用完成。无exploration_goal时沿用原自动调度。

最后更新：2026-09-09

已成功的准备操作可以再次以当前合法owner实际执行；不再以“同Focus曾成功”禁止必要导航、连续滚动或参数准备，
也不要求先有到最终目标的完整路线。历史成功不证明本次效果，每次仍保存并核对before/action/after。
无效果/不确定近重复、错误绑定与原12次Task尝试预算保留；成功的局部变化不因State编号未变而被视为无进展。

Android scroll的point_1000现在对应实际触摸起点；amount为期望像素距离，通过frac交给controller，
端点受屏幕范围限制，不把amount误作多次手势。此前居中展开手势可能把列表内点位移到底部导航，
即使owner正确也无法滚动。方向统一指希望查看的内容方向，left看左/right看右，手指方向相反。
真实起点落在覆盖控件上仍可能无效，这属于需要按fresh截图纠正的grounding问题，不能因转换正确就宣称GUI成功。

## 模型动作与内部动作

主 Agent 每轮最多提出一个 primitive。桌面支持 click、double click、right click、hover、
input、scroll、Back 和 Wait；Android 支持 click、long press、input、scroll、Back 和 Wait。
有视觉落点的动作必须使用最新截图中的 `point_1000`，空输入字符串合法。两个坐标都位于 `0..1`
且含小数时视为误用了归一化尺度并 fail closed，不自动放大。Android `input_text` 默认以
`clear_text=true` 清空当前字段后输入完整目标值，避免非空字段把代表输入追加到旧文本。
named-snapshot overlay 会安装并选择仓库锁定的 Appium Settings `UnicodeIME`。该 Apache-2.0 helper 不创建
输入视图；controller 仍通过 AndroidWorld 的 ADB text request 输入。若系统已有 active served input connection，`input_text` 跳过模型坐标、
直接清空并注入；没有焦点时才 tap 一次，并在 clear/type 前重新读取 input connection。tap 后仍无焦点则返回
`input_text_target_not_focused`，不输入任何文本。

桌面 `input_text` 在一个语义 Attempt 内执行当前点位 CLICK、一次 Ctrl+A、仅含 text 的 TYPING；
最终 TYPING 不携带坐标，避免 controller 再次点击取消全选。目标为空字符串时最后执行 Backspace，
真实清空选择内容。任一步返回 action_error 就停止后续步骤，最后取得的截图交给原 pending 结算；
Task、Operation 和全局动作预算仍各记一次。pending 卡只在输入动作回显已有目标 text，Luna 用新截图
核对结果；不新增模型输出字段或独立视觉检查。Android 输入合同保持不变。

模型不填写 purpose 或 Operation ID，只填写 `owner_ref`：

- ElementOperation：当前卡片中的 `element_ref`；
- RegionOperation scroll：当前卡片中的 `region_ref` 和登记方向；
- 调查和路线中的 scroll 同样使用当前 Region 的 owner；
- 非滚动恢复、Back、Wait：空 owner。

runtime 在投递前用当前 State 的 Variant 唯一解析 `owner + action + direction`，把本地 Operation
与内部 purpose 写入 ActionAttempt；当前 State 调查中的 Region scroll 使用 `survey`，仍有精确 Operation binding。
非滚动空 owner 根据内部 route/recover 状态分类。`route` 不是 Luna 可选择的免结算标签。

## before / action / after

每次真实动作保存 `before.png`，下一轮把 before 和最新 after 同时交给主 Agent。
`previous_action.attempt_ref` 必须精确等于当前 pending Attempt。模型回填：

- `element_actions`：after 截图直接证明已产生预期可见效果的已登记 Element 动作；
- `region_actions`：实际完成的 Region scroll 及方向；
- `function_info`：更新动作前来源 Region，或动作后重新可见的既有 Region 的自然语言 memory；
- `parameter_info`：仅在 pending 卡要求参数确认时，以 `none/observed + summary` 更新本次
  completed owner；框架自动绑定 Operation 和 after screenshot；
- `reason`：短的可见依据。

动态上下文同时回显该 pending Attempt 的精确 `kind/owner_ref/target/direction` 和 source Region refs。
模型复制动作 ref，不从控件名称重新猜；after 图重新可见的已知 Region也可更新 memory，新 Region仍由
当前页面清点登记，任意 before/after 都不可见的 Region拒绝。

框架校验 completed action 与 Attempt primitive 一致，并在 before Variant 中唯一映射；`completed=true`
还要求 after 截图证明该 Operation 的直接可见效果。动作已投递、鼠标落在附近或只出现 tooltip
仍填 false。候选外 owner、错误 action、方向冲突和歧义都 fail closed。模型不报告 Task 是否完成。映射成功即由框架
把本地 Operation 标为 verified、关闭其派生 Task；CanonicalOperation 已有真实证据时，继续使用
现有合同关闭重复 binding 并保留原始证据。
scroll 是否完成由主 Agent比较 before/after 判断。框架只在变化像素比例不超过保守的 0.01% 门限时，
覆盖为 `no_effect`；其余变化不由框架判为成功，也不因 Luna填写 false 而隔离新观察。
当前仍有截断只支持后续换落点或幅度的 bounded retry，不能倒推本次 success。
click 的完成报告也不能覆盖完全相同的应用内容证据：变化比例不超过保守门限时，runtime 清空本轮
completed owner，把 Attempt 记为 `no_effect`，Operation 保持 active。下一次必须使用 fresh screenshot
重新定位并显著改变点位。动态状态栏明确回显已结算的 Attempt、`previous_action=null` 和上次真实
`owner_ref`，避免模型在来源 Variant 的旧 owner 与当前 binding 之间来回切换。同一任务、同一来源 State
中，焦点 Operation 或其已确认 CanonicalOperation binding 第二次真实执行仍无效果时，以 grounding 或
应用校验 failed gap 收束；切换到真实不同 State 后重新计数。两次失败 Attempt 的 before/action/after 都保留。
平台动作投递错误同样先于 owner settlement。Android `input_text` 若含当前输入通道不支持的非 ASCII，
controller 在点击/清空/输入前拒绝，environment 把 `action_error` 随 after observation 返回；runtime 清空
completed owner 并把 Attempt 记为 `no_effect/retry`，Operation 保持 active。下一次可用 fresh frame 和
ASCII 代表值重做；第二次同 Operation 仍失败沿用 no-effect gap 上限，不能把部分输入写成 success。
严格焦点检查的 unavailable/miss 使用相同 delivery-error 通道。runtime 在 Page/State bind 前结算该 Attempt，
隔离 after landing 的 page report 和同轮 action；错误 tap 即使打开选择器或其他目标应用 surface，也不能登记为
输入 Operation 的目标 State。

一次动作如果点击了另一个已登记 owner，Attempt/History 仍归当前 Focus Task，真实 owner 由
`action.operation_ref` 保存；实际 Operation 可被顺手结算，原 Focus Task 保持 active。正式 bundle
从 operation_ref 反查实际 Operation Task 作为 probe owner。若派发 Timer 但实际打开 Menu，只能完成
Menu 的已登记 click，Timer 不会因为自然语言理由被关闭。
相同 Page、Element 名或 Operation 文本不自动关闭其他操作。只有已经由截图 Reviewer 确认共享
CanonicalOperation 的 binding，才沿既有 canonical 结算规则关闭重复任务。

同一 Focus 中某个前置 owner 已执行且结果为no_effect/uncertain、`source_state == target_state`时，若下一次仍是相同
operation/action/direction/text 且点位距离不超过 25/1000，就视为近重复并拒绝；模型必须显著改变
grounding、改用其他可见 owner、恢复动作或继续目标 Operation。该规则既阻止 1 像素抖动绕过，又允许
明显改变点位的真实重新定位，并让 route/detour 进入当前 Focus 的最近动作和尝试预算。

非滚动的空 owner route/recover 不绑定 Operation；旧账本中已有的空 owner survey 记录仍可保守结算，
但新 scroll 在投递前必须绑定 Region。误填 completed owner 会被丢弃并记录
`unbound_action_completed_owners_ignored`，这些结论不验证任何 Operation。原 scroll mismatch quarantine 已删除。
重复 no-effect、恢复和总尝试预算仍由框架收束为 failed gap。
未知参数的 Operation 即使 completed owner 正确，也必须先通过参数确认再结算；报告缺失或冲突时
保留同一 pending Attempt，下一轮只修正报告，不重新执行真实动作。
若参数入口没有产生可见效果，模型必须填 `completed=false, parameter_info=null`；框架将 Attempt
结算为 no-effect/retry，Operation 参数保持 `unknown`，再基于 fresh screenshot 重新定位。不能要求
模型为未生效的点击猜填参数，也不能把同一 pending 报告留在纠正循环中。
即使模型违反该约束，只要本轮没有任何 completed owner，runtime 也会丢弃无法绑定的
`parameter_info`，记录 `parameter_info_ignored_without_completed_owner` 后继续保守结算。

owner settlement错误使用结构化 `code/field_path/expected/received`。动作结果和本轮提交的清单先在
临时 ledger 中处理，通过必要检查才发布位置、清单和动作结果并释放 pending。错误时回到正式账本，
保留真实 before/action/after。纠正卡允许同步修改尚未接受的位置、分区和效果判断，action=null，不重放真实动作。
主 Agent、Element/Region/Operation Reviewer 共用三轮失败预算（首次失败加两次纠正）。错误直接交给能修改它的角色；措辞、排序、任务切换和刷新截图不清零。报告通过检查才结束纠正。耗尽后保留候选、截图和 gap，不再审核同页冲突；位置可信时可沿已有绑定探索其他内容，否则 partial 停止。详见 [报告纠正流程](report_correction_flow.md)。
pending 耗尽时用真实证据保存 no_effect/uncertain，将实际 Operation/Task 保留为 failed gap 并释放 pending。


Android 同一任务连续两次 `recover` 均无可见效果时，不直接执行第三次 Back/点击恢复。框架先通过
既有 data-preserving lifecycle 执行一次 `force-stop + launch`，不调用 `pm clear`，也不生成图边或
Capability evidence；随后只根据 fresh screenshot 重新定位。重启后仍进入同一无效恢复序列才形成
failed gap。桌面端维持原有两次无效恢复后收束行为。

## Transition

只有真实 Attempt 已结算、落地 State 已确定、来源与目标不同且动作成功时才写 Transition。
Transition 的 action 使用 ActionAttempt 中的真实本地 Operation binding；Region memory 不生成边。
`execute/route/survey/recover` 中任一真实成功动作只要产生并接受了不同 State，都保存关联同一
`attempt_ref` 的 Transition；purpose 只描述动作在当时任务中的角色，不决定连接是否存在。
外部应用画面不登记为目标 Page/State。ScopeGuard 仍负责恢复，应用消失应报告为环境/前景失败，
不能改写成 grounding error。

新 State 完成前景 Region 清点后，现有 Region Reviewer 会同时判断触发器与结果表面的显露关系。
`known_operation_reveals_current` 只有在 Reviewer 所见 `source_transition` 与账本中的
`attempt_ref/source_state/target_state/operation_ref/source Region` 全部一致，且目标 Region 确实属于
目标 State 时，才追加到该 Transition 的 `revealed_region_ids`。来源与目标清点完成后，runtime 还用
规范 Region 集合补齐 `target-source` 的 revealed 和 `source-target` 的 `hidden_region_ids`；未完成清点
时不猜测。Region 后续确认复用时同步改写两组引用，以及 ActionAttempt/Transition/History 中的 Region owner_ref。正式 bundle 把它投影为原
action attempt 的 `evidence.revealed_region_refs`，来源仍由 Operation owner 反查，所以没有第二套动作边或图真值。

待结算动作的 Page/State 由查看最新完整截图的主 Agent 报告。runtime 不再调用纯文字
Page Resolver，因此 Page 文字分歧不会丢弃 completed owner、阻止 Operation 验证或中断 Transition 写入。
结构、引用归属、Region 身份和真实前后图证据的原有校验仍保留。

## 已验证点击锚点

普通 click 投递时仍保存局部 `anchor.png`。只有已有成功 Transition、当前完整截图与已确认帧字节
一致、局部灰度/边缘匹配唯一时，runtime 才可重放已验证路线首跳。重放仍在 fresh frame 上重定位，
下一轮仍需 before/after 和最终落地验证；锚点不决定 Page、Region、Operation result 或安全边界。

## 2026-09-08 反馈检查

SettlementContractError 转为文本仍保留 field_path/expected/received；新动作 action.owner_ref、回填 previous_action 的实际数组字段、代表提案引用分别定位。反馈不建议重复真实动作，原校验边界保留。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。
