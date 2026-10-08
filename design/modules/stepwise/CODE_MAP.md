# 逐步遍历源码职责地图

[开发入口](../../../DEVELOPMENT.md) · [三步流程](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md) · [提示入口](../../../experiments/clock_manual_20260919/遍历prompt/README.md)

源码在 `experiments/clock_manual_20260919/`。下面按职责列出顶层 Python 文件，每个文件只有一个主要 owner；其他步骤调用它时沿同一接口复用。按三步、异常和共享职责阅读，不机械创建三份实现。表内“主要接口”是定位线索，精确合同在相应模块页。

桌面批次入口：`tools/run_stepwise.py → batch_launch → batch_runtime → run_source.session_command`，随后与原生会话汇合。

浏览器入口连接：`启动遍历.sh → launch_traversal.main → run_source.session_command → run_progress_session.run_session → run_task_step._run_step`。单轮由traversal_scheduler先处理已执行待登记与pending，再选择发现/任务清点、动作或异常复核；三步不等于固定三次 Luna 调用。

| 主体 | 职责及交接 |
|---|---|
| `run_task_step` | 跨三步的编排；驱动 Runner、实际投递、后图取证及下一轮，不归为仅第二步 |
| `locator / task_proposer` | 发现和任务请求，分别交 discovery_step / region_tasks 正式登记；地图/模板/完整清单不证明可操作或任务完成 |
| `traversal_scheduler / action_proposer / action_executor` | 选择工作、提出并绑定动作、投递前检查及真实执行 |
| `result_updater / register_update / task_settlement` | 原回执和前后图进入更新、正式登记与原任务结算，发布后由下轮读新快照 |
| `region_evidence` | 单份证据记录构造和保存图投影，供请求、登记与图页复用；最终写入仍归登记器 |
| `step_repair / repair_stages` | 各 stage 同一纠错/接受边界；已执行动作只修登记，不重新投递 |
| `model_transport` | 正常/恢复、Android/桌面共用 ModelTransport.call；范围、图像、历史、请求保存和额度保持原顺序 |

本批新增 `task_selection / task_settlement / model_transport / action_binding / region_evidence` 五个职责文件；旧 `region_tasks / recover_external / desktop_transport / stepwise_flow` 的入口直接导入或继承同一实现，保留现有调用者。目录平铺、动态 sibling 加载、prompt 相对根和冻结 run 的 `framework_source` 不变。
本地图说明当前实现结构与定位；不把源码整理、离线检查或保存图读取写成地图准确、导航成功或模型语义验收。当前地图修复候选与跨区块语义任务去重仍按原未接受/未实现状态。

## 第一步：发现与准备任务（5 文件）

详细职责：[模块页](01_discovery.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [discovery_step.py](../../../experiments/clock_manual_20260919/discovery_step.py) | 发现观察/身份正式登记、快照读取与发布；定位请求由 locator 直接提供。 | `load / commit / publish / await_discovery` |
| [discovery_completion.py](../../../experiments/clock_manual_20260919/discovery_completion.py) | 同帧增量登记、历史身份召回与未解决缺口补齐。 | `prepare_registration / supplement` |
| [discovery_inventory.py](../../../experiments/clock_manual_20260919/discovery_inventory.py) | 把任务清点缺口交给本区局部发现，不批量改其他 owner。 | `supplement` |
| [region_tasks.py](../../../experiments/clock_manual_20260919/region_tasks.py) | 任务增量登记及覆盖计算；提议请求/schema由 task_proposer 直接提供。 | `apply_plan / commit_plan / coverage` |
| [entry_evidence.py](../../../experiments/clock_manual_20260919/entry_evidence.py) | 披露已观察的入口效果，为规划和累计核对保留来源。 | `disclose / related` |

## 第二步：选择已有工作与前置条件（7 文件）

详细职责：[模块页](routing.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [task_selection.py](../../../experiments/clock_manual_20260919/task_selection.py) | 兼容入口委托唯一调度器及请求组件，保留任务进度渲染。 | `attach / render / render_current` |
| [task_routing.py](../../../experiments/clock_manual_20260919/task_routing.py) | 依据已观察进入链推进原工作目标，来源链不自动成为返回边。 | `advance / destination_work` |
| [task_prerequisites.py](../../../experiments/clock_manual_20260919/task_prerequisites.py) | 登记有证据的前置条件、准备任务与范围内唤醒。 | `augment / apply / complete_preparation` |
| [task_deferral.py](../../../experiments/clock_manual_20260919/task_deferral.py) | 保留局部暂挂和已观察路线，选择独立可继续工作。 | `defer / runnable / resume_localized` |
| [inventory_scroll.py](../../../experiments/clock_manual_20260919/inventory_scroll.py) | 清点 incomplete 时调度明确的本区滚动并保留缺口。 | `select / resume_after_region_observation` |
| [historical_inventory.py](../../../experiments/clock_manual_20260919/historical_inventory.py) | 用已访问表面的实际历史做任务清点，避免仅为清点重复导航。 | `request / region_request` |
| [visual_backtrack.py](../../../experiments/clock_manual_20260919/visual_backtrack.py) | 比较表面、交接旧导航记录，恢复旧 pending；新导航仍走正常主链。 | `handoff / resume_pending / project` |

## 第二步：动作请求、关联与投递（8 文件）

详细职责：[模块页](execution.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [stepwise_flow.py](../../../experiments/clock_manual_20260919/stepwise_flow.py) | 组装当前动作上下文及已有图的阅读视图，保留 StepwiseFlow 阶段/execute 适配器；关联与证据由专责模块导入。 | `assemble_current_context / StepwiseFlow.execute` |
| [action_binding.py](../../../experiments/clock_manual_20260919/action_binding.py) | 把本轮提案与当前视觉候选关联，保留冲突及未确认身份；绑定不等于动作成功。 | `bind_action_target / _bind_action_target` |
| [action_commands.py](../../../experiments/clock_manual_20260919/action_commands.py) | 共用动作 schema、校验、平台转换与实际执行；恢复复用同一合同。 | `schema / validate / commands / execute` |
| [action_evidence.py](../../../experiments/clock_manual_20260919/action_evidence.py) | 从投递回执读取实际动作类型，不由标签或截图推断。 | `resolve_operations` |
| [input_target.py](../../../experiments/clock_manual_20260919/input_target.py) | 只对可靠视觉确认的记录输入对象继续发送文字。 | `locate / resolve` |
| [attempt_guard.py](../../../experiments/clock_manual_20260919/attempt_guard.py) | 相同失败尝试进入既有纠错边界，避免无依据重复执行。 | `check` |
| [region_scroll.py](../../../experiments/clock_manual_20260919/region_scroll.py) | 校验当前图中的模型滚动坐标，保留 Region 动作归属。 | `bind` |
| [visual_choices.py](../../../experiments/clock_manual_20260919/visual_choices.py) | 提供本轮外观匹配备选，明确身份裁图与点击区域不同。 | `prepare / match_controls / click_box` |

## 第三步：结果更新与登记（8 文件）

详细职责：[模块页](updates.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [register_update.py](../../../experiments/clock_manual_20260919/register_update.py) | 固定原动作来源、保存观察/动作/图像及正式快照；不调用模型或 GUI。 | `commit_update / commit_discovery / materialize_regions` |
| [task_settlement.py](../../../experiments/clock_manual_20260919/task_settlement.py) | 由已登记绑定动作计算探索进度、修正后续绑定并保存参数事实。 | `completion_target / settle_task / reconcile_run / store_findings` |
| [region_evidence.py](../../../experiments/clock_manual_20260919/region_evidence.py) | 构造/投影 Region、控件、动作和保存图状态，不推断成功或反向路线。 | `region_transitions / region_records / graph_state；new_region / region_observation / control_observation / control_name / action_record / index_actions` |
| [update_visibility.py](../../../experiments/clock_manual_20260919/update_visibility.py) | 合并本轮明确未变的区块与变化，旧框与裁图保持历史资格。 | `regions / locate_retained` |
| [registration_diagnostics.py](../../../experiments/clock_manual_20260919/registration_diagnostics.py) | 在发布前集中收集独立错误、身份/归属/可见性诊断。 | `collect / check` |
| [task_result_review.py](../../../experiments/clock_manual_20260919/task_result_review.py) | 异常暂挂和显式历史修复；普通流程不再申请累计完成复核。 | `request / apply / commit` |
| [parameter_evidence_review.py](../../../experiments/clock_manual_20260919/parameter_evidence_review.py) | 参数事实缺失时只按证据集交接一次，回原规划作者补登记。 | `request_review / augment` |
| [update_semantic_review.py](../../../experiments/clock_manual_20260919/update_semantic_review.py) | 发布前接受调用方的证据绑定监督结论，不默认提供自动语义正确性。 | `check` |

## 第三步：功能知识与覆盖（3 文件）

详细职责：[模块页](knowledge.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [region_functions.py](../../../experiments/clock_manual_20260919/region_functions.py) | 从已有控件、任务、属性和实际动作提取本区功能知识。 | `next_ready / request / commit / evidence_projection` |
| [function_scope.py](../../../experiments/clock_manual_20260919/function_scope.py) | 本地知识与入口目标一级摘要只读披露；按明确参数任务读取支持，不递归传播。 | `disclose / entries / parameter_support` |
| [function_evidence.py](../../../experiments/clock_manual_20260919/function_evidence.py) | 只读整理本区执行结果和观察来源，独立于任务是否可调度。 | `action_results / incoming_results` |
| [coverage_exemption.py](../../../experiments/clock_manual_20260919/coverage_exemption.py) | 保存有依据的非执行覆盖决定，未验证缺口保留；不借另一控件成功。 | `apply / reconcile / refresh` |

## 异常：纠错、修订与恢复（16 文件）

详细职责：[模块页](repair.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [step_repair.py](../../../experiments/clock_manual_20260919/step_repair.py) | 持久有界 Runner、失败诊断、纠错请求和暂停/续接；不投递 GUI。 | `Runner.perform / request / resume_service_failure` |
| [repair_stages.py](../../../experiments/clock_manual_20260919/repair_stages.py) | 按原 stage 校验接受、刷新证据、补观察或窄范围修订，复用正常登记。 | `accept / accept_candidate / refresh / observe_registered / edit_record` |
| [correction_prompts.py](../../../experiments/clock_manual_20260919/correction_prompts.py) | 按阶段、结构化诊断和证据选公共/专项纠错提示。 | `select / parts` |
| [correction_crop_feedback.py](../../../experiments/clock_manual_20260919/correction_crop_feedback.py) | 展示被拒裁框的派生证据，不把裁图当新观察。 | `attach` |
| [model_reply_parse.py](../../../experiments/clock_manual_20260919/model_reply_parse.py) | 按完整单份模型消息解析最终决定，拒绝拼接多段决定。 | `parse` |
| [recovery.py](../../../experiments/clock_manual_20260919/recovery.py) | 恢复策略、原任务交接与共用动作请求。 | `build_request / resolve / restart_commands` |
| [recover_external.py](../../../experiments/clock_manual_20260919/recover_external.py) | Android 恢复运行适配器；模型发送沿共享 ModelTransport。 | `RecoveryRun / main` |
| [recover_loop.py](../../../experiments/clock_manual_20260919/recover_loop.py) | 有界恢复循环，恢复动作间不登记业务 Region。 | `run` |
| [recovery_stall.py](../../../experiments/clock_manual_20260919/recovery_stall.py) | 按实际恢复回执识别重复，不用整屏相似度当成功。 | `repeated_attempt` |
| [branch_switch.py](../../../experiments/clock_manual_20260919/branch_switch.py) | 服务失败时保留证据、暂挂当前工作并转独立工作/新观察。 | `request / commit / correct` |
| [suspended_updates.py](../../../experiments/clock_manual_20260919/suspended_updates.py) | 用原 episode、回执和前后图续登记归档结果，禁止重发 GUI。 | `restore_next / validate_commit / complete` |
| [ownership_review.py](../../../experiments/clock_manual_20260919/ownership_review.py) | 在争议 owner 发布前复查观察、分区与证据。 | `begin / request / repartition / run` |
| [action_owner_correction.py](../../../experiments/clock_manual_20260919/action_owner_correction.py) | 显式纠正一笔已执行动作的有效对象，原投递证据不改。 | `apply / request` |
| [control_observation_repair.py](../../../experiments/clock_manual_20260919/control_observation_repair.py) | 按观察来源窄范围重归属，不做整控件自动合并。 | `begin / apply / validate_scope` |
| [task_record_repair.py](../../../experiments/clock_manual_20260919/task_record_repair.py) | 窄范围纠正任务 owner，已执行证据不跟着迁移。 | `apply` |
| [shared_control_review.py](../../../experiments/clock_manual_20260919/shared_control_review.py) | 共享行为冲突的证据、独立纠错请求、原子成员修订与重新清点。 | `build_request / apply / run_pending` |

## 共享：身份、前景、视觉匹配与任务复用（16 文件）

详细职责：[模块页](identity.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [foreground_scope.py](../../../experiments/clock_manual_20260919/foreground_scope.py) | 同轮前景范围、几何检查及本帧复用资格。 | `validate / validate_control_boxes / audit` |
| [local_partition.py](../../../experiments/clock_manual_20260919/local_partition.py) | 为局部发现提供同帧分区上下文及发布检查。 | `build / errors` |
| [region_identity.py](../../../experiments/clock_manual_20260919/region_identity.py) | 发现和更新共用 Region 身份准备；屏幕位置不是身份。 | `prepare / extend_schema` |
| [region_records.py](../../../experiments/clock_manual_20260919/region_records.py) | 显式合并重复 Region，保留原始证据和图链接。 | `merge / rewrite` |
| [control_records.py](../../../experiments/clock_manual_20260919/control_records.py) | 稳定控件角色、代表项及显式记录修订。 | `validate / merge / rewrite / remove` |
| [control_layout.py](../../../experiments/clock_manual_20260919/control_layout.py) | 原控件组图像唯一重匹配后按相对布局分配重复外观。 | `refine` |
| [identity_templates.py](../../../experiments/clock_manual_20260919/identity_templates.py) | 独立判断身份模板准入与资格，不从观察存在推定可匹配。 | `usable / assessment / check_control_crop` |
| [image_match.py](../../../experiments/clock_manual_20260919/image_match.py) | 共用外观匹配算法，返回临时候选位置与歧义；不写 Region 知识。 | `SceneMatcher / locate` |
| [history_matching.py](../../../experiments/clock_manual_20260919/history_matching.py) | 读取历史身份、独立控件票数及限定前景候选。 | `scan / attach` |
| [visual_region_locator.py](../../../experiments/clock_manual_20260919/visual_region_locator.py) | 控件召回与局部视觉定位，只复用本帧模型确认的边界。 | `plan / resolve_foreground_check` |
| [source_region_candidates.py](../../../experiments/clock_manual_20260919/source_region_candidates.py) | 动作来源候选及有来源时态的历史身份文字。 | `recall / attach` |
| [region_candidate_names.py](../../../experiments/clock_manual_20260919/region_candidate_names.py) | 把本轮名字与已登记候选明确对应。 | `candidates / resolve` |
| [shared_controls.py](../../../experiments/clock_manual_20260919/shared_controls.py) | 显式跨 Region 行为关联；本地观察身份仍本地保存。 | `link / refresh / view` |
| [shared_tasks.py](../../../experiments/clock_manual_20260919/shared_tasks.py) | 共享任务定义/结果引用、失效撤回与解除后的审计清理；不复制本地执行。 | `synchronize_tasks / automatic_tasks / reconcile_detached_tasks` |
| [region_behavior_split.py](../../../experiments/clock_manual_20260919/region_behavior_split.py) | 按更新原答证据撤销行为不同来源的共享。 | `apply` |
| [control_history_context.py](../../../experiments/clock_manual_20260919/control_history_context.py) | 短身份线索摘要，历史名字不直接证明控件角色。 | `describe` |

## 共享：地图、历史与发送正文（11 文件）

详细职责：[模块页](context.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [page_context.py](../../../experiments/clock_manual_20260919/page_context.py) | 从已登记记录只读构造当前区块/控件树、原动作进入关系和共同地图。 | `build / attach / refresh` |
| [page_history.py](../../../experiments/clock_manual_20260919/page_history.py) | 地图、清点与动作共用的 Region/控件动作历史及出处。 | `build / reference` |
| [map_prompt.py](../../../experiments/clock_manual_20260919/map_prompt.py) | 只为同源同值事实做共同地图引用，避免删独有证据。 | `current_task / task_view / receipt` |
| [history_context.py](../../../experiments/clock_manual_20260919/history_context.py) | 组织身份、动作、任务、findings 与必要原图历史，保留时态。 | `action_context / findings / disclose` |
| [history_disclosure.py](../../../experiments/clock_manual_20260919/history_disclosure.py) | 模型发送边界的统一历史排版与共用规则引用。 | `project` |
| [history_selection.py](../../../experiments/clock_manual_20260919/history_selection.py) | 按当前任务及明确前置/来路选择历史证据，不以时间相邻代替相关性。 | `for_request / task_attempts / related_tasks` |
| [task_action_context.py](../../../experiments/clock_manual_20260919/task_action_context.py) | 渲染探索目标及原尝试，历史披露委托已有共用模块。 | `build / history` |
| [task_attempt_context.py](../../../experiments/clock_manual_20260919/task_attempt_context.py) | 任务历史适配器，披露规则沿 history_context。 | `describe / history` |
| [target_observation.py](../../../experiments/clock_manual_20260919/target_observation.py) | 动作及纠错共用当前目标观察/交接，候选不证明当前可操作。 | `attach / refresh / handoff` |
| [prompt_delivery.py](../../../experiments/clock_manual_20260919/prompt_delivery.py) | 按桌面步骤提供同源手册规则及纠错固定段落引用。 | `desktop_parts / original_rules` |
| [render_region_context.py](../../../experiments/clock_manual_20260919/render_region_context.py) | 离线渲染当前提交知识，供阅读诊断。 | `main` |

## 共享：快照事务与只读图页（2 文件）

详细职责：[模块页](updates.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [knowledge_transaction.py](../../../experiments/clock_manual_20260919/knowledge_transaction.py) | 组合修订期间隐藏中间知识指针，仅在完整事务成功后发布。 | `transaction` |
| [region_graph.py](../../../experiments/clock_manual_20260919/region_graph.py) | 从一个已提交快照读取图和图片引用，提供只读浏览器投影。 | `snapshot / project` |

## 共享：运行允许范围（1 文件）

详细职责：[模块页](tasks.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [traversal_scope.py](../../../experiments/clock_manual_20260919/traversal_scope.py) | 沿运行授权复核任务范围及禁止动作，不擦除真实尝试。 | `review_request / skip_prohibited` |

## 共享：运行、模型、设备与进度（24 文件）

详细职责：[模块页](runtime.md)。

| 文件 | 主要职责 | 主要接口 |
|---|---|---|
| [run_task_step.py](../../../experiments/clock_manual_20260919/run_task_step.py) | 贯穿三步及恢复/续登记的单轮编排入口，连接调度器、组件、原Runner及会话预算。 | `_run_step / run_step / build_attempt_update / resume_update_request` |
| [launch_traversal.py](../../../experiments/clock_manual_20260919/launch_traversal.py) | 浏览器、已安装应用与保存/新运行的统一维护入口。 | `main` |
| [app_launcher.py](../../../experiments/clock_manual_20260919/app_launcher.py) | 应用与设备选择、模型配置读取和空 run 创建。 | `create_run / Device / ApplicationHub` |
| [batch_launch.py](../../../experiments/clock_manual_20260919/batch_launch.py) | 桌面固定CLI、新建配置、持久服务及只读状态；tools/run_stepwise.py调用。 | `main / launch / status` |
| [batch_environment.py](../../../experiments/clock_manual_20260919/batch_environment.py) | 实际服务内有界预检、支持的应用数据备份重置及新图准备。 | `preflight / clear_clock_data / prepare_new` |
| [batch_runtime.py](../../../experiments/clock_manual_20260919/batch_runtime.py) | 设备锁、冻结源/依赖核验、原总预算续接、原生子进程及退出记录。 | `execute` |
| [run_source.py](../../../experiments/clock_manual_20260919/run_source.py) | 浏览器与监督会话共用源码选择、冻结源核对和启动命令。 | `resolve_source / source_hash / session_command` |
| [run_progress_session.py](../../../experiments/clock_manual_20260919/run_progress_session.py) | 反复驱动原有单轮，正常轮结算后再暂停。 | `run_session` |
| [model_transport.py](../../../experiments/clock_manual_20260919/model_transport.py) | 正常步骤与恢复共用最终范围/截图/历史投影、请求保存、预算和模型发送。 | `ModelTransport.call / with_environment_scope / with_run_scope / with_frame_context` |
| [debug_loop.py](../../../experiments/clock_manual_20260919/debug_loop.py) | 监督运行、停止分类与隔离候选试验的原有闭环。 | `live_run / classify` |
| [debug_candidate.py](../../../experiments/clock_manual_20260919/debug_candidate.py) | 构建与分层核对隔离修复候选，实际 GUI 试验由调用方控制。 | `workspace / assert_scope / pytest_run` |
| [debug_progress.py](../../../experiments/clock_manual_20260919/debug_progress.py) | 候选可加载的图进度投影，不做调度或 GUI。 | `graph_summary` |
| [desktop_transport.py](../../../experiments/clock_manual_20260919/desktop_transport.py) | OSWorld/桌面设备与回执适配器，模型发送继承共用路径，不自动重试动作。 | `DesktopRun / prepare_request` |
| [desktop_capture.py](../../../experiments/clock_manual_20260919/desktop_capture.py) | 从 VM 显示取图及发布帧，保留截图来源。 | `display_capture / publish_frame` |
| [desktop_lifecycle.py](../../../experiments/clock_manual_20260919/desktop_lifecycle.py) | 在控制服务清理范围之外启动应用，保留进程生命周期边界。 | `start` |
| [browser_hub.py](../../../experiments/clock_manual_20260919/browser_hub.py) | 同一浏览器来源组合控制/投屏/进度面板，按需取设备帧。 | `backend / SharedRunner / Handler` |
| [progress.py](../../../experiments/clock_manual_20260919/progress.py) | 只读进度视图及原有小范围执行状态/暂停钩子。 | `round_status / request / check_capture_pause` |
| [progress_details.py](../../../experiments/clock_manual_20260919/progress_details.py) | 只读投影纠错 episode 和跨 Region 缺口。 | `details` |
| [progress_window.py](../../../experiments/clock_manual_20260919/progress_window.py) | 进度/运行控制网页与可选应用选择，调用既有 runner。 | `RoundRunner / server` |
| [exploration_summary.py](../../../experiments/clock_manual_20260919/exploration_summary.py) | 按 session 边界统计真实模型尝试及所属对象，不进模型 prompt。 | `record / summarize` |
| [exploration_loop.py](../../../experiments/clock_manual_20260919/exploration_loop.py) | 根据结算后的记录识别重复无进展，不增加模型调用。 | `detect / correct` |
| [call_model_once.py](../../../experiments/clock_manual_20260919/call_model_once.py) | 单次模型调用并保存/解析原答；不运行遍历或 GUI。 | `NoRetry / post` |
| [assemble.py](../../../experiments/clock_manual_20260919/assemble.py) | 保存帧 prompt 组装诊断，使用独立流程01，不是正常发现入口。 | `assemble` |
| [replay_stepwise_baseline.py](../../../experiments/clock_manual_20260919/replay_stepwise_baseline.py) | 读取独立冻结源码和冻结原答回放，不调用模型或设备。 | `main` |

## 其他文件与跨模块连接

| 内容 | 位置与边界 |
|---|---|
| 浏览器启动脚本 | [启动遍历.sh](../../../experiments/clock_manual_20260919/启动遍历.sh)，保持唯一维护入口 |
| 图/进度页面 | [region_graph.html](../../../experiments/clock_manual_20260919/region_graph.html)、[progress_window.html](../../../experiments/clock_manual_20260919/progress_window.html)；设备后图与提交图记录分别显示 |
| prompt、流程与基础 schema | [遍历prompt/README.md](../../../experiments/clock_manual_20260919/遍历prompt/README.md)；程序按阶段扩展 schema 与动态上下文，实际发送以 `calls/<编号>/request.json` 为准 |
| 维护测试 | [tests/STEPWISE_INDEX.md](../../../tests/STEPWISE_INDEX.md)；按受影响合同选择，不把导航索引当必跑门禁 |
| 独立质量检查 | [tools/check_stepwise_quality.py](../../../tools/check_stepwise_quality.py)、[tools/stepwise_quality/](../../../tools/stepwise_quality/)、[质量合同](../stepwise_quality.md)；输出独立，源码图只读 |
| 指令/采集消费者 | [collection_graph.py](../../../gui_rewalk/src/core/scenario/collection_graph.py)、[collection_visual_guard.py](../../../gui_rewalk/src/core/scenario/collection_visual_guard.py)；[采集模块](../visual_collection.md)说明冻结图/固定 matcher 和输出边界 |
| 运行证据 | 原 run 的 `run_manifest.json`、`knowledge_current.json → knowledge_snapshots/`、`calls/`、`action_attempts/`、pending/纠错账本；保留旧证据，不随目录整理搬走 |
| 临时验证/审阅交付 | `artifacts/tmp_tests/<唯一任务>/` / `to_astra/<唯一名称>/`；冻结源与当前源明确区分、脱敏、不覆盖旧版本 |

修改时沿 [连接核对表](../../../DEVELOPMENT.md#change-connections)核对请求→原答校验→登记→下轮读取以及受影响纠错/恢复。共享模块的主要 owner 不排除其他步骤使用；同一事实只能由既有登记路径发布，地图和浏览器投影不能成为第二份事实写入器。

当前最小遍历连接：discovery_completion保留逐项缺口出处；task_settlement.partition_findings负责补充事实局部化，refresh_movement只读新观察重开原移动任务；region_functions.next_ready把区块总结接入普通调度；run_task_step.finalize_knowledge在GUI空闲后补历史清点，复用相同总结选择。

- `history_selection.py`：当前任务、明确准备、completion/findings及旧scroll努力的引用选择；由history_context/page_history共用，禁止用时间区间补无关动作。
- `region_candidate_names.entry_summary`：必要历史入口职责，完整进入动作仍在function_evidence后台。
- `identity_templates.crop_rejection`：可选模板几何资格；register_update只拒绝该模板，foreground_scope保留严格点击/前景边界。

## 三步组件与程序调度（2026-10-06）

| 文件 | 真实职责 | 可调用接口 |
|---|---|---|
| traversal_scheduler.py | 已提交状态选工作、pending优先、局部观察/导航安排及目标退出、续接/停止 | select_work / schedule_local_inspection / retire_completed_goal / Scheduler.current |
| locator.py | 发现schema、上下文/请求、阶段驱动及局部控件定位 | schema / prepare / request_from_run / Locator.discover / locate_control |
| task_proposer.py | 任务schema、提示、历史/共享上下文；普通/范围/历史/纠错请求共用 | proposal_schema / plan_request / TaskProposer.request / run |
| action_candidates.py（新增） | 本地候选与当前前景直接入边外层触发控件；已有合格图标及原点击范围复用 | candidate / attach_related / use_recorded_icon |
| action_proposer.py | 已选任务/导航的完整上下文、原动作校验绑定 | request_from_run / render_work / ActionProposer.propose |
| action_executor.py | 投递前核对、真实执行及回执/前后图 | ActionExecutor.execute |
| result_updater.py | 结果请求、候选校验、正常与中断观察；正式写入仍归register_update | build_update_request / route_update / ResultUpdater.update / resume |

普通调用：调度决定→对应组件→原登记发布→重新调度。组件数不等于模型调用数。
源码路径仍在experiments/clock_manual_20260919，原辅助模块不复制。

2026-10-07候选接线：task_proposer.proposal_schema/plan_request → region_tasks.apply_plan保存registration_kind → action_proposer/history_context传递目标 → result_updater.build_attempt_update/build_update_request → register_update.commit_update → task_settlement.register_entry/require_registration/settle_task。function_evidence向总结披露已登记入口语义和信息缺口。

`task_knowledge.py`：`control_knowledge/current/refresh`，由已完成任务维护控件知识，由本帧语义观察维护区块状态；两个发布入口共用，任务与地图读取复用。


控件条件用途：`control_context.py`（新增）集中条件集合比较及真实拆分任务目标迁移；`task_settlement`/`region_tasks`分别调用结算与去重，`shared_controls`/`shared_tasks`保留共享条件，`region_candidate_names`保留最终发送的历史图标及条件。
