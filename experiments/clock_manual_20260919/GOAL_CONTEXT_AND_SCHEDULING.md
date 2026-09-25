# 目标上下文、暂挂与区块调度

本文件描述临时逐步框架当前行为，原 gui_rewalk 不变。

## 动作步：让模型根据事实选择准备动作

`task_action_context.build()` 从任务的 name/reason/status、运行状态 last_action_result 指向的真实动作及 result.description 生成“当前目标、任务建立时的历史记录、最近尝试、尚未完成”；旧reason不作为当前状态，有解除依据的历史阻塞另行说明。context_evidence 保存来源引用；不把人工建议写成历史事实。

目标控件暂时不在正常前景时，仍进入动作选择，提供本区块当前可定位控件，允许输入、滚动等准备动作。单步任务执行了其他控件或其他操作时，绑定标记 preparatory_action；更新步登记实际效果，原目标保持 pending，不能将准备工作登记为目标完成。控件绑定与坐标检查按 [约束清理记录](PROMPT_CONTRACT_AUDIT.md) 执行：低分不直接否决，明确的位置冲突仍需解决。参数任务跨多个当前可交互区块时继续原目标，合并当前控件候选；不能把目标归属区块写成 return_to 自动回溯要求。

例：清空搜索后候选消失，动态内容披露真实清空结果和未完成的候选选择目标；不在固定 prompt 中规定搜索词或解题动作。

## 暂挂关联实际阻塞

任务的 blocker.condition 区分 foreground_exception、control_not_visible、review_required；原因、来源调用和纠错 episode 保留。纠错回复 blocked_by 显式提供阻塞类别，不解析中文原因猜测。

- blocking_popup / unexpected_exit / external_app：未执行动作的可隔离任务先暂挂，进入已有异常恢复，交接 reason；不切换到被遮挡的后台任务。
- 恢复后回发现步；只有接受了正常前景，并产生该控件本轮新定位图片，才释放 foreground_exception 暂挂。旧阻塞移入 blocker_history。
- control_not_visible 需新定位；review_required 不因重新截图自动解除。已执行未结算的动作仍先结算，不能借暂挂重复执行。
- 旧记录缺少结构化阻塞时，不声称框架能自动理解旧文本。073 中对已人工核实的七项系统弹窗暂挂做了一次有备份的显式迁移。

## 当前区块结束后继续全局调度

`run_task_step.current()` 收到 region_complete 或可隔离的 task_blocked 后，调用 `task_deferral.advance_unfinished()`。从已登记区块中选择仍有工作或尚未清点任务的区块，优先当前可见，其次已有路径，最后未知路径交给 Luna 导航。跳过已完成或仅剩阻塞的区块；不把局部完成当成应用遍历完成。

正常返回父区块的原流程保留。选择新目标只更新 working_region，不伪造跳转；视觉回溯失败后由 Luna 接管，实际动作与结果按原流程登记。

## 验证与历史处理

命令及日志：`artifacts/tmp_tests/stepwise_goal_context_20260921/check6.log`，82 项聚焦离线通过。覆盖事实上下文、准备动作不能完成原任务、弹窗消除后恢复、其他阻塞不误解锁、未清点区块调度及相邻纠错接口。

真实调用/设备证据：`records/073_goal_context_frontier_20260921_01/`；source 与 source_fixed 分别冻结运行源码。Settings 按用户要求从活动任务移除 a0001/a0003/a0005 旧失败关联，保留原任务备份、原动作及不可变快照；没有增加执行方式版本判断。具体调用结果以该目录 REPORT.md 为准。

复现离线检查（项目根目录，guiwalk-android Python）：

```bash
python -m pytest tests/test_stepwise_goal_context.py tests/test_stepwise_task_reactivation.py tests/test_stepwise_region_tasks.py tests/test_stepwise_deferral.py tests/test_shared_step_repair.py tests/test_region_function_inventory.py tests/test_stepwise_resume_route.py tests/test_stepwise_task_correction.py -q --basetemp=artifacts/tmp_tests/stepwise_goal_context_20260921/check6
```

073 最终实测：Clock 保存帧1次实际调用自主选择输入，未执行GUI；Markor关闭弹窗→重新发现→恢复暂挂任务；Settings a0011打开搜索页、a0012输入wifi并显示结果，0058更新接受；Broccoli局部完成后调度到About the app并登记，仍需补当前可用区块定位。Settings中途发现的参数续接/误回溯问题已修正，第二次归档错误重试关联后验证通过。未运行全框架回归；未宣称四应用遍历完成。

## 2026-09-22 已识别前景中的导航准备
局部定位明确not_interactive，且同一截图的上轮观察已有其他区块时，offer_foreground_navigation保留目标，排除不可交互的目标入口区块，优先保留已识别子区块而非其背景父容器，进入普通action_selection。动作上下文说明当前遮挡及必要关闭/返回准备，不要求先定位目标入口；不指定具体点击或把正常菜单归异常。未知前景、不同帧或uncertain仍走发现。动作后仍按更新登记实际落点，不假定返回目的地。
验证：15项no_route_discovery/resume_route/discovery_dispatch测试通过，日志artifacts/tmp_tests/foreground_navigation_20260922/final.log。旧no-route断言同步现有导航约定，dispatch假环境补齐exploration_loop隔离；未放宽实际运行校验。保存0067/0068帧回放生成action_ready且allow_back的菜单导航请求；实机进度单独保存在records/224_foreground_navigation_20260922，不以离线测试代替。

2026-09-22 用户环境保护范围：OSWorld平台prompt禁止修改熄屏/锁屏/睡眠/电源/显示/输入/会话等影响遍历设置，只读查看后取消。旧任务范围复核也能record这些禁止修改；已知自动锁屏任务已按用户指令转record，历史保留。恢复三项已改设置并读回，熄屏Never未变，下一轮重新发现。20项task/desktop测试通过；实机恢复与暂停运行源政策同步见records/225_environment_scope_20260922。当前是模型规则和范围复核，不宣称执行器语义硬拦截已完备。

2026-09-22 环境只读规则改为影响原则与正反例，不再枚举配置清单；DesktopRun.call统一追加到任务提出、动作、更新、恢复等桌面请求，旧任务范围复核保留记录变更权限。暂停运行源的两份prompt同步并保留前版于records/226_environment_examples_20260922。4项desktop检查通过，未恢复遍历或新增模型调用。网页当前paused_by_user且blocker/repair为空；最近错误仍是0088/0091/0092自动锁屏同区块相似开关定位冲突，不能说所属区块筛选已解决同区块消歧。

## 明确禁止的任务不阻塞遍历（2026-09-22）
普通动作回复可用 `action=none, skip_task=true`，reason说明当前任务违反的明确用户/平台限制。框架根据请求的task_region/task_name定位任务，复用record_only保存限制原因、来源调用、原尝试及scope_history，清除该active_task，返回ready_next_round。下一轮原调度选择其他任务/区块，不进入无意义的补观察，不生成GUI尝试，不标done。普通none不带skip_task仍走发现；定位困难不属于禁止。纠错可revise同样的动作回复；已执行未结算的动作不能跳过登记。只有没有剩余可执行工作时才结束，record_only不代表功能验证成功。

验证：`python -m pytest tests/test_stepwise_prohibited_task_skip.py tests/test_stepwise_external_scope.py tests/test_stepwise_visual_backtrack.py tests/test_stepwise_task_correction.py -q --basetemp artifacts/tmp_tests/prohibited_task_skip_20260922/final`，25项离线通过。包含实际快照登记、历史保留、下一待办可调度、普通none保留、执行未结算不可跳过及runner返回继续状态。共用测试fixture移除已废弃entry_name。未调用Luna或执行GUI；日志保存在上述目录。

实机纠正：模型服务严格输出要求properties全部列入required，初版skip_task可选导致0108/0111请求400拒绝（无动作）；现改为每次显式填写布尔值，旧执行回执本地验证默认false。新增严格schema检查，23项相关离线测试通过。两次服务错误触发的10个暂挂任务按确证原因恢复pending，保留错误和解除历史；不更改实际动作记录。续跑证据records/229_settings_continue_20260922。

## 定位/绑定冲突（2026-09-22）
纠错既有blocked_by增加binding_conflict，不新增模型回复字段，也不混入应用异常action_result.exception。动作绑定失败或缺少当前定位由BindingConflict自动标明类别。纠错上下文同时给出实际动作候选（可为空）、匹配位置、模型建议点、框架认定落点、拒绝依据，以及指向目标区块的历史来源按钮；历史入口只作核对材料，不自动授予可交互身份。候选为空不能当作截图中没有按钮。

落点冲突时纠错用既有observe，补观察强制走relocate而非继续信任旧局部区块，随后沿原刷新/动作/更新流程。仅目标或坐标错误可revise；禁止将菜单选项改名为展开按钮。此改动未放开任意坐标强制绑定，也未修复自动回溯的错误落点判定本身。
验证：tests/test_stepwise_binding_conflict.py、test_stepwise_repair_scope.py、test_stepwise_task_correction.py共12项离线通过，覆盖现有字段枚举、空候选说明、图中真实来源入口披露、既有局部上下文不扩大。日志artifacts/tmp_tests/binding_conflict_20260922/green.log。未声称Luna现场纠错已通过。

## 自动回溯点击与落点修复（2026-09-22）
新观察按click_bbox选点击点；旧单框记录读取原动作receipt.executed_steps的实际单步点击点，将其在历史识别图内的相对位置映射到当前匹配图，缺少可靠证据交给Luna，不点击识别框中心。执行后除原整屏核对外，必须匹配历史动作后观察对应的目的Region裁图；未找到则进入已有handoff重新定位，并记navigation_failed_edges避免重复自动重放。当前可交互区块仅采用本次确认的Region，不复制整份历史落点列表。
验证：test_stepwise_visual_backtrack.py与test_stepwise_control_boxes.py共16项离线通过；真实a0023打开菜单图通过、错误回溯闭合图拒绝，旧入口点击点恢复为(1004,221)。日志及重放结果artifacts/tmp_tests/replay_landing_20260922。从新截图恢复r0018因误定位阻塞的原任务，历史未删除，续跑证据records/231_replay_landing_20260922；现场结果以该记录为准。局部视觉仍有误匹配风险，不宣称杜绝所有误判。

## 连续运行不设累计上限（2026-09-22，用户授权）
run_progress_session默认max_http/max_gui_commands/max_rounds为null，累计调用、GUI和轮数不限，仍完整记账；明确数值配置仍按原预算执行。当前Settings manifest已设三项null并恢复自动运行。暂停在本轮登记后生效；单步只执行一轮；已完成/实际阻塞仍停止。单轮调用/动作与纠错限制保留，不因无限累计额度无限重试同一失败步骤；预算计数不进入模型prompt。
验证：tests/test_stepwise_progress.py 13项通过，含超过旧30调用/20轮限制后继续到25轮、150调用/150动作且可暂停，原数值预算和单步行为保留。日志artifacts/tmp_tests/unlimited_session_20260922/green.log。实际启动记录records/232_unlimited_session_20260922；无限模式仅表示允许持续运行，不代表遍历已完成。

## 独立两框与补观察阶段衔接（2026-09-22）
识别框与点击框只要求各自为有效矩形，不要求包含；点击框按识别图位置/尺度映射，侧栏整行可点击范围可以大于文字图标识别框。移除发现/更新prompt的包含要求。已有同屏候选确认与截图范围检查不变。
纠错observe的一次机会代表一次观察流程，不等于一次模型调用；完成全局relocate后，若原发现流程仍需local定位，则复用同一截图继续子发现，最多沿现有三阶段界限，记录每次来源调用。额度暂停后从子任务或已登记supplement恢复，最后才刷新原动作请求；不重复拍图，不丢原任务，不重置纠错次数。
验证：control_boxes、binding_conflict、repair_scope、task_correction共19项离线通过，日志artifacts/tmp_tests/independent_boxes_20260922/green.log。真实0148帧Location Services识别成功，点击框映射为[70,119,312,164]并接受(168,141)。已从原blocked纠错记录恢复observe，保存修改前episode，实机续跑见records/233_independent_boxes_20260922。

## 2026-09-23：失败按任务和阶段隔离
任务失败不自动封禁同控件的所有其他任务；已知自动路线仍遵守原路线证据门禁。function_registration 缺口不排除该区块其他GUI工作。全局候选包含清单未完成、仍有可执行任务的区块；无已知路径时交给普通导航Luna，不编造边。task_proposal失败且无新证据时不立即重提；局部新证据可允许复核。没有独立工作时保留阻塞，不宣称全应用完成。
