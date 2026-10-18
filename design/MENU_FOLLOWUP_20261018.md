# 菜单后续修改：离线验证候选

基线：`df059e9345d7c9bf8d2a9e76ac93b7cdc486c8ac`，分支`codex/traversal-framework-20261018`。这次修正用途材料与局部续接，不重复应用已存在的菜单entries优先补丁。

## 1. 已实现

| 问题 | 修改位置 | 当前行为 |
|---|---|---|
| Help等控件的初步用途被投影为“需要探索”，与任务提出的辅助介绍规则冲突 | records/control_history_context.py::purpose_text；prompts/任务/区块探索任务.prompt | 材料保留推测和已知功能；任务提出先判断本轮允许范围、实际作用和需了解内容，再决定探索。needs_exploration仍存档，不输出调度指令 |
| 无blocker的语义暂挂仅因新crop就生成复核trigger，甚至覆盖已关联的recovery触发 | traversal/task_deferral.py::resume_localized | 只处理范围内任务的control_not_visible或已恢复的foreground_exception，并按completion_target读取本次实际目标crop；归档blocker、排入复核，状态仍blocked且不改原owner |
| 任务仍属A、实际完成控件属B时被owner==source挡住；已确认的右键等目标也被click/tap限制 | traversal/task_routing.py::advance | 复用records/task_settlement.py::completion_target核对B及实际控件，任务保留在A；本次entries优先，其他控件操作也可交接；无明确entries的回退仍限click/tap及来源消失 |

所有源码路径相对于`src/regrow/`。没有增加模块、模型字段、Help名称规则或额外模型调用。

## 2. 保留的边界

- 推测用途不等于确认知识。既有任务、条件、实际失败、未解问题及观察原件保留；needs_exploration=false也不能关闭旧任务。
- 未探索不自动构成值得探索。原范围提示仍允许有价值的应用内未知功能、菜单和参数；辅助介绍默认不另设任务，用户明确要求时除外。
- **暂挂不等于完成或范围排除。**普通defer仍计入coverage.blocked，可能使区域保持未完成；本次不手改旧图、不删除已有Help任务。
- **retry_when仍是自由文本，没有通用自动满足判断。**模型只用文字表示“目标重新出现后再考虑”，但没有结构化定位blocker时，也不会仅因新crop自动复核。需要正常任务清点/显式scope_review按原task提交continue等增量；不能将直接task_result_review.request称为无条件重审入口。普通调度也不会自动识别用户目标文字发生变化。
- 有结构化定位阻碍时，新crop只解除阻碍并请求原结果复核，不直接恢复执行或宣告成功。前置条件要用已披露dependency_updates和目标观察；显式服务重试及已有相关恢复trigger沿原专门路径。
- 交接仍要求任务done、非准备动作、完成目标与动作/绑定控件一致、成功投递和正常结果；明确关联交接的目标必须来自同次已接受entries且在当前观察目标中。无关联分支仍保留前述click/tap来源消失回退。一般interactive_regions策略与总结时机没有扩大。

## 3. 验证结果

| 检查 | 结果 | 证明范围 |
|---|---|---|
| 原有相关基线 | 16 passed | 确认这批相关测试在修改前可运行 |
| 改前新增行为回归 | 19 failed / 30 passed | 重现材料断言、语义暂挂误唤醒、恢复trigger覆盖、跨归属及非click交接缺口 |
| 修改后初轮聚焦检查 | 54 passed | 相关新行为和保留边界的离线代码检查 |
| 相邻对象登记 | 10 passed | 保留正常对象/目标登记合同 |
| 独立审查后的实际目标恢复 | 修订前3 failed/1 passed；最终全部68 passed | 补跨原任务/实际目标的定位恢复，原控件图不能替代目标图，范围外任务不唤醒 |
| CLI、AST、差异检查 | 通过 | 入口可加载、6份变更Python可解析、无差异空白错误 |
| 完整菜单记录的最终请求构造 | 两阶段前后各一份，0模型/0GUI | 任务提出与动作选择均使用原截图和来源，schema前后一致，控件旁的探索断言已移除 |

聚焦命令及日志位置见[月志](changelog/2026-10.md)。测试使用Python 3.12隔离依赖；不运行发布或全框架门禁。

输入ZIP漏带了record_history事件，最初正常加载失败。仅在隔离副本中由其完整after-records.json重新序列化，并按原objects顺序恢复事件顺序；两个当前快照引用的55/59个事件全部匹配原内容哈希，原历史索引、状态、调用原答和图片未改。这个修复只为恢复已有输入，不是新增运行证据。

最终预览经正常preview_next/request_from_run、ActionProposer、桌面prepare_request和ModelTransport构造；在既有0调用预算检查处停止。动作预览复用保存帧，未新截图或执行操作。初步预览的依赖/适配失败与最终材料分别保留。

## 4. 验收状态与下一步

本环境没有原Luna调用配置。**本批为已实现、通过离线检查的候选；没有新Luna原答、模型语义验收或GUI成功证据。**旧模型曾对Help建任务这一事实没有被本次请求预览推翻。

后续在已配置环境中，从完整真实记录正常构造请求，保留Luna原答并经Runner校验、必要纠错和登记，检查：辅助介绍未被无条件要求探索；明确要求时可探索；有价值的未知应用内内容仍保留任务；语义暂挂与真正定位恢复按各自依据推进；跨归属及非click的实际目标交接保持原任务。保存帧和真实GUI结果分开计数。

原始运行与采集框架不改。配套Astra变更地图随交付包固定到本次实际上传提交，行号按该提交验证，不把本页基线SHA冒充实现提交。
