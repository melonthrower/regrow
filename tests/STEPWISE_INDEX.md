# 逐步遍历测试导航

[开发入口](../DEVELOPMENT.md) · [模块职责](../design/modules/stepwise/README.md) · [所有测试约定](README.md)

这是测试定位表，不是必跑清单或通过率。范围：Git维护且直接引用逐步目录或常用逐步测试加载器的测试；未提交候选测试不纳入已维护索引。仅运行改动涉及的测试及必要相邻合同；实机/模型验收仍按AGENTS要求独立记录。

同一测试涉及多个模块时在相应栏目均列出；这是共用检查，不复制测试实现。无法从直接模块引用归类的文件放在综合栏目，按实际修改再检查依赖。

## 代码整理的连接检查

[test_stepwise_module_boundaries.py](test_stepwise_module_boundaries.py)检查新模块的独立导入、旧公共入口指向同一实现及正常冻结源码包含拆出的文件；[发送合同测试](test_stepwise_transport_new_fields.py)保留正常知识快照依赖。它们不替代模型语义或GUI验收。

## 先按流程选择相关栏目

| 修改位置 | 本步检查入口 | 需要时补相邻连接 |
|---|---|---|
| [第一步：发现与准备任务](../design/modules/stepwise/01_discovery.md) | [身份](#identity)、[任务](#tasks) | [上下文](#context)、[调度](#routing)、[纠错](#repair) |
| [第二步：选择并执行动作](../design/modules/stepwise/02_action.md) | [调度](#routing)、[执行](#execution) | [身份](#identity)、[上下文](#context)、[更新](#updates)、[纠错](#repair) |
| [第三步：观察结果并更新记录](../design/modules/stepwise/03_update.md) | [更新](#updates)、[知识与完成](#knowledge) | [任务](#tasks)、[上下文](#context)、[纠错](#repair) |
| [异常处理与恢复](../design/modules/stepwise/repair.md) | [纠错](#repair)及失败原步骤 | [运行](#runtime)中的中断/恢复，以及恢复后的消费步骤 |
| [共享能力](../design/modules/stepwise/README.md#shared) | 对应职责栏目 | 实际受影响的三步生产者/消费者；不默认全跑 |

选择用例时沿[变更连接核对](../DEVELOPMENT.md#change-connections)确认覆盖关系；下面保留原测试路径和职责分组，不因增加流程导航复制测试或声明通过。

<a id="identity"></a>

## 观察与身份

- [test_action_correction_single_frame.py](test_action_correction_single_frame.py)
- [test_action_source_observation.py](test_action_source_observation.py)
- [test_blocked_entry_history_review.py](test_blocked_entry_history_review.py)
- [test_control_identity_only.py](test_control_identity_only.py)
- [test_control_observation_repair.py](test_control_observation_repair.py)
- [test_coverage_exemption.py](test_coverage_exemption.py)
- [test_discovery_incremental.py](test_discovery_incremental.py)
- [test_discovery_inventory_supplement.py](test_discovery_inventory_supplement.py)
- [test_failed_supplement_evidence.py](test_failed_supplement_evidence.py)
- [test_foreground_scope.py](test_foreground_scope.py)
- [test_history_identity_index.py](test_history_identity_index.py)
- [test_history_matching.py](test_history_matching.py)
- [test_identity_entry_context.py](test_identity_entry_context.py)
- [test_identity_template_admission.py](test_identity_template_admission.py)
- [test_region_position_evidence.py](test_region_position_evidence.py)：Region 位置、模板资格、同帧范围与无效边界。
- [test_local_partition_context.py](test_local_partition_context.py)
- [test_local_region_discovery.py](test_local_region_discovery.py)
- [test_partial_sharing.py](test_partial_sharing.py)
- [test_recovery_discovery.py](test_recovery_discovery.py)
- [test_recovery_task_context.py](test_recovery_task_context.py)
- [test_region_scroll.py](test_region_scroll.py)
- [test_registration_fault_recovery.py](test_registration_fault_recovery.py)
- [test_shared_control_conflict_repair.py](test_shared_control_conflict_repair.py)
- [test_shared_step_repair.py](test_shared_step_repair.py)
- [test_stepwise_anchor_candidate_ranking.py](test_stepwise_anchor_candidate_ranking.py)
- [test_stepwise_control_boxes.py](test_stepwise_control_boxes.py)
- [test_stepwise_diagnostics.py](test_stepwise_diagnostics.py)
- [test_stepwise_discovery_manual.py](test_stepwise_discovery_manual.py)
- [test_stepwise_equivalent_context.py](test_stepwise_equivalent_context.py)
- [test_stepwise_fault_campaign.py](test_stepwise_fault_campaign.py)
- [test_stepwise_function_support_handoff.py](test_stepwise_function_support_handoff.py)
- [test_stepwise_historical_inventory.py](test_stepwise_historical_inventory.py)
- [test_stepwise_identity_provenance.py](test_stepwise_identity_provenance.py)
- [test_stepwise_list_role_reuse.py](test_stepwise_list_role_reuse.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_match_batch.py](test_stepwise_match_batch.py)
- [test_stepwise_pixel_matching.py](test_stepwise_pixel_matching.py)：原尺寸像素、阈值下竞争者、无纹理拒绝与整页检查；重复控件另见 [test_control_layout_matching.py](test_control_layout_matching.py)。
- [test_stepwise_no_route_discovery.py](test_stepwise_no_route_discovery.py)
- [test_stepwise_pipeline_unblock.py](test_stepwise_pipeline_unblock.py)
- [test_stepwise_recovery_continuation.py](test_stepwise_recovery_continuation.py)
- [test_stepwise_region_merge.py](test_stepwise_region_merge.py)
- [test_stepwise_region_recall.py](test_stepwise_region_recall.py)
- [test_stepwise_screen_coordinates.py](test_stepwise_screen_coordinates.py)
- [test_stepwise_shared_controls.py](test_stepwise_shared_controls.py)
- [test_stepwise_shared_region_identity.py](test_stepwise_shared_region_identity.py)
- [test_stepwise_source_region_candidates.py](test_stepwise_source_region_candidates.py)
- [test_supplement_sent_contract.py](test_supplement_sent_contract.py)
- [test_task_closure.py](test_task_closure.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)
- [test_unified_map_prompt.py](test_unified_map_prompt.py)
- [test_update_history_frame_identity.py](test_update_history_frame_identity.py)

<a id="context"></a>

## 地图与上下文

- [test_action_correction_single_frame.py](test_action_correction_single_frame.py)
- [test_action_owner_correction.py](test_action_owner_correction.py)
- [test_action_source_observation.py](test_action_source_observation.py)
- [test_control_layout_matching.py](test_control_layout_matching.py)
- [test_current_page_context.py](test_current_page_context.py)
- [test_history_context_module.py](test_history_context_module.py)
- [test_history_disclosure.py](test_history_disclosure.py)
- [test_identity_template_admission.py](test_identity_template_admission.py)
- [test_page_control_history.py](test_page_control_history.py)
- [test_prompt_map_dedup.py](test_prompt_map_dedup.py)
- [test_prompt_review_consistency.py](test_prompt_review_consistency.py)
- [test_prompt_task_scope.py](test_prompt_task_scope.py)
- [test_stepwise_entry_evidence.py](test_stepwise_entry_evidence.py)
- [test_stepwise_hover_guidance.py](test_stepwise_hover_guidance.py)
- [test_stepwise_identity_provenance.py](test_stepwise_identity_provenance.py)
- [test_stepwise_prompt_semantics.py](test_stepwise_prompt_semantics.py)
- [test_stepwise_region_graph_browser.py](test_stepwise_region_graph_browser.py)
- [test_task_context_diagnostics.py](test_task_context_diagnostics.py)
- [test_task_history_frames.py](test_task_history_frames.py)
- [test_unified_map_prompt.py](test_unified_map_prompt.py)
- [test_update_history_projection.py](test_update_history_projection.py)

<a id="tasks"></a>

## 任务规划与登记

- [test_clock_registration_provenance.py](test_clock_registration_provenance.py)
- [test_control_layout_matching.py](test_control_layout_matching.py)
- [test_debug_loop.py](test_debug_loop.py)
- [test_local_region_discovery.py](test_local_region_discovery.py)
- [test_page_control_history.py](test_page_control_history.py)
- [test_parameter_evidence_review.py](test_parameter_evidence_review.py)
- [test_partial_sharing.py](test_partial_sharing.py)
- [test_prompt_review_consistency.py](test_prompt_review_consistency.py)
- [test_shared_step_repair.py](test_shared_step_repair.py)
- [test_stepwise_entry_evidence.py](test_stepwise_entry_evidence.py)
- [test_stepwise_equivalent_context.py](test_stepwise_equivalent_context.py)
- [test_stepwise_hover_guidance.py](test_stepwise_hover_guidance.py)
- [test_stepwise_pipeline_unblock.py](test_stepwise_pipeline_unblock.py)
- [test_stepwise_shared_controls.py](test_stepwise_shared_controls.py)
- [test_task_closure.py](test_task_closure.py)
- [test_task_context_diagnostics.py](test_task_context_diagnostics.py)
- [test_task_settlement_routing.py](test_task_settlement_routing.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)
- [test_unified_map_prompt.py](test_unified_map_prompt.py)

<a id="routing"></a>

## 调度与前置条件

- [test_scoped_task_blocking.py](test_scoped_task_blocking.py)：普通暂挂/同控件准备、实际退出归属与条件、正常动作接受、父任务唤醒边界。

- [test_coverage_exemption.py](test_coverage_exemption.py)
- [test_function_evidence_projection.py](test_function_evidence_projection.py)
- [test_function_scope.py](test_function_scope.py)
- [test_local_knowledge_disclosure.py](test_local_knowledge_disclosure.py)：多用途、本地条件、一跳披露及选择性刷新。
- [test_identity_template_admission.py](test_identity_template_admission.py)
- [test_region_scroll.py](test_region_scroll.py)
- [test_sent_step_contract.py](test_sent_step_contract.py)
- [test_stepwise_historical_inventory.py](test_stepwise_historical_inventory.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_navigation_cycle.py](test_stepwise_navigation_cycle.py)
- [test_stepwise_prompt_semantics.py](test_stepwise_prompt_semantics.py)
- [test_stepwise_task_loop_handoff.py](test_stepwise_task_loop_handoff.py)
- [test_stepwise_visual_backtrack.py](test_stepwise_visual_backtrack.py)
- [test_task_settlement_routing.py](test_task_settlement_routing.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)

<a id="execution"></a>

## 动作选择与执行

- [test_action_correction_single_frame.py](test_action_correction_single_frame.py)
- [test_action_source_observation.py](test_action_source_observation.py)
- [test_control_layout_matching.py](test_control_layout_matching.py)
- [test_discovery_incremental.py](test_discovery_incremental.py)
- [test_identity_template_admission.py](test_identity_template_admission.py)
- [test_local_region_discovery.py](test_local_region_discovery.py)
- [test_partial_sharing.py](test_partial_sharing.py)
- [test_pointer_action_binding.py](test_pointer_action_binding.py)
- [test_recovery_discovery.py](test_recovery_discovery.py)
- [test_region_registration.py](test_region_registration.py)
- [test_region_scroll.py](test_region_scroll.py)
- [test_region_stepwise_context.py](test_region_stepwise_context.py)
- [test_shared_control_conflict_repair.py](test_shared_control_conflict_repair.py)
- [test_stepwise_control_boxes.py](test_stepwise_control_boxes.py)
- [test_stepwise_desktop.py](test_stepwise_desktop.py)
- [test_stepwise_discovery_dispatch.py](test_stepwise_discovery_dispatch.py)
- [test_stepwise_fault_campaign.py](test_stepwise_fault_campaign.py)
- [test_stepwise_hover_guidance.py](test_stepwise_hover_guidance.py)
- [test_stepwise_identity_provenance.py](test_stepwise_identity_provenance.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_navigation_cycle.py](test_stepwise_navigation_cycle.py)
- [test_stepwise_resume_route.py](test_stepwise_resume_route.py)
- [test_stepwise_return_semantics.py](test_stepwise_return_semantics.py)
- [test_stepwise_task_loop_handoff.py](test_stepwise_task_loop_handoff.py)
- [test_stepwise_visual_choices.py](test_stepwise_visual_choices.py)
- [test_stepwise_wait_receipt.py](test_stepwise_wait_receipt.py)
- [test_task_closure.py](test_task_closure.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)

<a id="updates"></a>

## 结果更新与登记

- [test_action_correction_single_frame.py](test_action_correction_single_frame.py)
- [test_action_owner_correction.py](test_action_owner_correction.py)
- [test_action_source_observation.py](test_action_source_observation.py)
- [test_blocked_entry_history_review.py](test_blocked_entry_history_review.py)
- [test_clock_registration_provenance.py](test_clock_registration_provenance.py)
- [test_control_identity_only.py](test_control_identity_only.py)
- [test_correction_crop_feedback.py](test_correction_crop_feedback.py)
- [test_coverage_exemption.py](test_coverage_exemption.py)
- [test_deferred_task_review.py](test_deferred_task_review.py)
- [test_discovery_incremental.py](test_discovery_incremental.py)
- [test_identity_template_admission.py](test_identity_template_admission.py)
- [test_parameter_evidence_review.py](test_parameter_evidence_review.py)
- [test_prompt_review_consistency.py](test_prompt_review_consistency.py)
- [test_recovery_task_context.py](test_recovery_task_context.py)
- [test_region_registration.py](test_region_registration.py)
- [test_registration_fault_recovery.py](test_registration_fault_recovery.py)
- [test_shared_step_repair.py](test_shared_step_repair.py)
- [test_stepwise_control_boxes.py](test_stepwise_control_boxes.py)
- [test_stepwise_diagnostics.py](test_stepwise_diagnostics.py)
- [test_stepwise_fault_campaign.py](test_stepwise_fault_campaign.py)
- [test_stepwise_hover_guidance.py](test_stepwise_hover_guidance.py)
- [test_stepwise_identity_provenance.py](test_stepwise_identity_provenance.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_navigation_disclosure.py](test_stepwise_navigation_disclosure.py)
- [test_stepwise_operation_review.py](test_stepwise_operation_review.py)
- [test_stepwise_pipeline_unblock.py](test_stepwise_pipeline_unblock.py)
- [test_stepwise_related_results.py](test_stepwise_related_results.py)
- [test_stepwise_return_semantics.py](test_stepwise_return_semantics.py)
- [test_stepwise_shared_region_identity.py](test_stepwise_shared_region_identity.py)
- [test_stepwise_source_region_candidates.py](test_stepwise_source_region_candidates.py)
- [test_stepwise_transport_new_fields.py](test_stepwise_transport_new_fields.py)
- [test_stepwise_update_exception.py](test_stepwise_update_exception.py)
- [test_task_closure.py](test_task_closure.py)
- [test_task_review_diagnostic.py](test_task_review_diagnostic.py)
- [test_update_history_frame_identity.py](test_update_history_frame_identity.py)
- [test_update_history_projection.py](test_update_history_projection.py)
- [test_update_region_visibility_conflict.py](test_update_region_visibility_conflict.py)
- [test_update_semantic_review.py](test_update_semantic_review.py)

<a id="repair"></a>

## 纠错与异常恢复

- [test_action_correction_single_frame.py](test_action_correction_single_frame.py)
- [test_action_dispatch_review.py](test_action_dispatch_review.py)
- [test_action_owner_correction.py](test_action_owner_correction.py)
- [test_action_source_observation.py](test_action_source_observation.py)
- [test_chrome_basic_scope.py](test_chrome_basic_scope.py)
- [test_control_observation_repair.py](test_control_observation_repair.py)
- [test_correction_crop_feedback.py](test_correction_crop_feedback.py)
- [test_correction_prompt_modules.py](test_correction_prompt_modules.py)
- [test_discovery_incremental.py](test_discovery_incremental.py)
- [test_exploration_summary.py](test_exploration_summary.py)
- [test_failed_supplement_evidence.py](test_failed_supplement_evidence.py)
- [test_history_disclosure.py](test_history_disclosure.py)
- [test_parameter_evidence_review.py](test_parameter_evidence_review.py)
- [test_prompt_task_scope.py](test_prompt_task_scope.py)
- [test_recovery_discovery.py](test_recovery_discovery.py)
- [test_recovery_stall_action.py](test_recovery_stall_action.py)
- [test_recovery_task_context.py](test_recovery_task_context.py)
- [test_region_registration.py](test_region_registration.py)
- [test_region_scroll.py](test_region_scroll.py)
- [test_sent_step_contract.py](test_sent_step_contract.py)
- [test_shared_control_conflict_repair.py](test_shared_control_conflict_repair.py)
- [test_shared_control_text_prompt.py](test_shared_control_text_prompt.py)
- [test_stepwise_diagnostics.py](test_stepwise_diagnostics.py)
- [test_stepwise_environment_scope.py](test_stepwise_environment_scope.py)
- [test_stepwise_equivalent_context.py](test_stepwise_equivalent_context.py)
- [test_stepwise_fault_campaign.py](test_stepwise_fault_campaign.py)
- [test_stepwise_frame_context.py](test_stepwise_frame_context.py)
- [test_stepwise_function_support_handoff.py](test_stepwise_function_support_handoff.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_pipeline_unblock.py](test_stepwise_pipeline_unblock.py)
- [test_stepwise_progress.py](test_stepwise_progress.py)
- [test_stepwise_prompt_semantics.py](test_stepwise_prompt_semantics.py)
- [test_stepwise_recovery_continuation.py](test_stepwise_recovery_continuation.py)
- [test_stepwise_region_merge.py](test_stepwise_region_merge.py)
- [test_stepwise_resume_route.py](test_stepwise_resume_route.py)
- [test_stepwise_transport_new_fields.py](test_stepwise_transport_new_fields.py)
- [test_stepwise_visual_choices.py](test_stepwise_visual_choices.py)
- [test_supplement_sent_contract.py](test_supplement_sent_contract.py)
- [test_task_closure.py](test_task_closure.py)
- [test_unified_map_prompt.py](test_unified_map_prompt.py)
- [test_update_semantic_review.py](test_update_semantic_review.py)

<a id="knowledge"></a>

## 功能知识与完成

- [test_coverage_exemption.py](test_coverage_exemption.py)
- [test_debug_loop.py](test_debug_loop.py)
- [test_function_evidence_projection.py](test_function_evidence_projection.py)
- [test_page_control_history.py](test_page_control_history.py)
- [test_partial_sharing.py](test_partial_sharing.py)
- [test_prompt_map_dedup.py](test_prompt_map_dedup.py)
- [test_shared_step_repair.py](test_shared_step_repair.py)
- [test_stepwise_diagnostics.py](test_stepwise_diagnostics.py)
- [test_stepwise_fault_campaign.py](test_stepwise_fault_campaign.py)
- [test_stepwise_function_support_handoff.py](test_stepwise_function_support_handoff.py)
- [test_stepwise_historical_inventory.py](test_stepwise_historical_inventory.py)
- [test_task_context_diagnostics.py](test_task_context_diagnostics.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)

<a id="runtime"></a>

## 运行、环境与进度

- [test_chrome_basic_scope.py](test_chrome_basic_scope.py)
- [test_debug_loop.py](test_debug_loop.py)
- [test_deferred_task_review.py](test_deferred_task_review.py)
- [test_manual_prompt_assembly.py](test_manual_prompt_assembly.py)
- [test_prompt_task_scope.py](test_prompt_task_scope.py)
- [test_recovery_discovery.py](test_recovery_discovery.py)
- [test_region_registration.py](test_region_registration.py)
- [test_region_scroll.py](test_region_scroll.py)
- [test_region_stepwise_context.py](test_region_stepwise_context.py)
- [test_stepwise_desktop.py](test_stepwise_desktop.py)
- [test_stepwise_environment_scope.py](test_stepwise_environment_scope.py)
- [test_stepwise_hover_guidance.py](test_stepwise_hover_guidance.py)
- [test_stepwise_local_failures.py](test_stepwise_local_failures.py)
- [test_stepwise_progress.py](test_stepwise_progress.py)
- [test_stepwise_prompt_semantics.py](test_stepwise_prompt_semantics.py)
- [test_supervised_step_review.py](test_supervised_step_review.py)
- [test_traversal_scope_chain.py](test_traversal_scope_chain.py)

<a id="integration"></a>

## 综合与入口测试

- [test_debug_replay_evidence.py](test_debug_replay_evidence.py)
- [test_desktop_lifecycle.py](test_desktop_lifecycle.py)
- [test_region_stepwise_flow.py](test_region_stepwise_flow.py)
- [test_stepwise_capture_pipeline.py](test_stepwise_capture_pipeline.py)
- [test_stepwise_launcher.py](test_stepwise_launcher.py)
- [test_stepwise_region_graph.py](test_stepwise_region_graph.py)
- [test_system_error_recovery.py](test_system_error_recovery.py)

## 绑定动作与探索进度
- [test_task_action_binding.py](test_task_action_binding.py)：同绑定执行、错对象/操作、未发送输入、改绑、参数回填、清点去重及新schema。
- [test_stepwise_related_results.py](test_stepwise_related_results.py)：同次动作复用与历史续接；不再依赖模型related_task_results。
- 相邻路由、归档恢复、前置条件：test_task_settlement_routing、test_suspended_update_recovery、test_ownership_and_prerequisites、test_prerequisite_runtime。

本批跨阶段最小遍历回归：[test_minimal_traversal.py](test_minimal_traversal.py)，覆盖partial可信动作、缺口保留、移动续接及参数局部缺口；具体通过范围见月度日志。

上下文相关性：`tests/test_context_relevance.py`核对身份轻量索引/普通目标卡/显式努力引用/原证据不变/可选模板拒绝与点击范围严格分界；`tests/test_history_current_state.py`核对当前状态看本轮图。


本批局部退出/空闲续接：[test_idle_continuation.py](test_idle_continuation.py)，覆盖范围内deferred导航、收尾后正常单步、再次空闲停止、独立知识账本和暂停；相邻预算见test_session_budget_tail.py。此索引不把原有其他测试视为全通过。

## 集中调度与组件交接
- [test_traversal_scheduler.py](test_traversal_scheduler.py)：范围、无标记导航、多前景续接、
  任务与请求分离、已执行待登记优先。
- [test_action_executor_component.py](test_action_executor_component.py)：投递证据顺序、
  已投递禁止重放、结果额度预留（离线适配器）。
- 相邻test_idle_continuation、test_session_budget_tail、test_stepwise_capture_pipeline、
  test_stepwise_discovery_dispatch、test_suspended_update_recovery、test_routed_task_constraints。

角色入口与连接： [test_recovery_discovery.py](test_recovery_discovery.py)、[test_stepwise_region_tasks.py](test_stepwise_region_tasks.py)、[test_stepwise_discovery_dispatch.py](test_stepwise_discovery_dispatch.py)、[test_shared_control_conflict_repair.py](test_shared_control_conflict_repair.py)。旧测试债和本批实际通过范围以月度日志为准。

本轮清退角色转发测试文件：独有的恢复上下文检查归入恢复测试，其余职责断言合并到任务、更新回执及导航测试；重复包装和旧串行清点门槛测试删除，净减少6个测试函数。测试数量不是执行门槛，只按改动合同选择检查。

任务后知识与状态：`tests/test_task_knowledge_flow.py`；相邻合同为`test_task_action_binding.py`、`test_preparation_completion.py`、`test_current_page_context.py`与区块总结测试。

- 桌面批次固定入口：[test_batch_entry.py](test_batch_entry.py)；相邻预算与初始化：test_session_budget_tail、test_stepwise_launcher。实机/保存帧验收另见月度日志。


控件条件用途：`tests/test_control_context.py`覆盖条件去重、跨条件不结算、结果收紧、真实拆分及引用/知识归属、共享条件与最终发送身份目录；相邻检查为`test_stepwise_behavior_split`、`test_stepwise_region_tasks`、`test_task_settlement_routing`、`test_task_knowledge_flow`、`test_instance_knowledge`、`test_shared_control_conflict_repair`、`test_shared_control_text_prompt`。


只读任务看板：`test_dashboard_task_focus.py`覆盖当前任务/工作区块分离、清点阶段不冒用旧任务、上一round隔离、投递与登记区分及证据路径；`test_stepwise_dashboard.py`覆盖累计/进行中计账。界面行为另用真实run的只读HTTP及浏览器检验，不能替代遍历验收。

`test_task_update_list.py`：局部任务数组、同控件旧问题显式回答、条件边界、准备保留目标、遗漏项续接不自动结束及拆分引用。与task_action_binding/task_knowledge_flow/control_context/suspended_update_recovery/history_context_module按影响选择。

控件新建冲突：`test_control_identity_review.py`覆盖仅同Region、同屏重复不复核、同位置多历史候选、原场景/完整上下文、same/different/uncertain、直接提交与Runner续接。相邻合同选`test_history_disclosure.py`、`test_stepwise_update_region_matching.py`及`test_control_layout_matching.py`；旧坐标落点绑定测试与现行动作显式候选合同不符，不以其旧断言恢复已删除行为。
