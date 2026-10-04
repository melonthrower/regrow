# 当前地图修复：源码定位与拟修改

固定源码：[d98a05971858208ee73402faf821fcdec06faed9](https://github.com/melonthrower/regrow/commit/d98a05971858208ee73402faf821fcdec06faed9)。以下均为该提交已存在的文件与一基行号；全部为拟修改，未实施。路径前缀为experiments/clock_manual_20260919/。

| 文件与函数 | 已核对行号 | 当前行为 → 拟修改 | 验收 |
|---|---|---|---|
| update_visibility.py / locate_retained | 18–33 | 独立模板accepted即返回旧ID → 保留召回资格和来源，作为候选；在此集中当前确认/候选的判断供消费端共用 | A、B、D |
| register_update.py / commit_update | 242–244、309–319 | 旧匹配与当前登记混入control_refs → 保存并区分证据来源，不把匹配直接升级为当前身份 | A、C、D |
| discovery_step.py / locate_task_control、rediscover、run_stage | 376–386、404–417、441–465 | 选定目标视觉匹配同样写control_refs → 保留定位候选；复用已有去重/三轮/纠错边界，禁止无进展重开 | A、C、D |
| visual_backtrack.py / project；stepwise_flow.py / assemble_current_context | 55–65；527–530 | 将历史模板投影为当前visual_only行 → 保留定位用途，禁止晋升语义确认/覆盖本帧确认 | A、C、D |
| coverage_exemption.py / reconcile、augment | 62–78 | 依据定位集合收紧免探索 → 继续使用确认与定位候选的并集保守要求复核，不因确认暂缺而授予豁免 | D、E |
| page_context.py / advances_goal；stepwise_flow.py / shortest_known_path | 435–452；309–340 | 任意visual_navigation阻断目标优先、定位支持已知路线 → 优先级只排除真正回放；候选路线保持建议性质 | D、E、F |
| page_context.py / build、_display | 109–132、217–258 | needs_recheck仍入current_tree且正文省略限定 → 当前树采用确认依据，历史按用途保留，不逐项添加待核对标签 | A、C、E、F |
| region_tasks.py / plan_request、attach | 46–62、242–260 | 同一混合集合支撑“本轮已定位”与优先选目标 → 当前说明/优先级与地图一致，候选不丢失，未知不判不存在 | A、D、F |
| stepwise_flow.py / _assemble_local_context、render_exploration_tree、_assemble_action_context | 244–282、343–358、412–480 | 保存历史外观候选，局部树排序和导航当前判断读control_refs → 保留有用候选并核对所有当前性说明；不借历史扩大前景动作许可 | B、C、D、F |
| 遍历prompt/更新/区块变化与字段.prompt | 34–48 | 保留区块与增量规则交代旧图定位 → 对照新的证据含义调整必要语句，保持未重报不等于消失 | A、D |

附带检查：发现/任务/动作/更新/纠错的实际组合请求、target_observation历史说明、图页的同源page_context。只在发现真实冲突时修改相关提示；若字段职责改变，必须检查所有消费端。现有测试test_current_page_context.py、test_stepwise_update_visibility.py、test_stepwise_region_tasks.py、test_current_region_priority.py及相邻合同按影响选择；不以静态检查代替原生验收。

新文件只包括本目录DESIGN.md和CHANGE_MAP.md（设计文档，不引用旧行号）。本次没有新增框架模块；拟复用现有update_visibility集中逻辑。实施后应重新导出实际源码提交及新版变更图，不能沿用本方案行号冒充最终实现。
