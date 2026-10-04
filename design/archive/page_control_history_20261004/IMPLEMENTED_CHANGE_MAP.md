# 已实施变更图（提交固定）

批准导出源码提交：[0a1a802c448d5f7b095a3b8915f364269f75ae81](https://github.com/melonthrower/regrow/commit/0a1a802c448d5f7b095a3b8915f364269f75ae81)。所有源码锚点读取该Git对象，非浮动工作树；原提案基线为 `c533359112b422e05c8ec96ce586ff8cfe8820d3`，见 PROPOSED_CHANGE_MAP。本文随后的文档提交不会改变这些源码锚点。

用户意图、设计与失败修订见 DESIGN。下表均为已实施行为；原提案不是待执行清单，当前没有额外批准的新功能计划。网页调整仅显示语义；Luna提示仍要求按当前图核对旧观察，任务状态取真实任务账本。

| 仓库路径 / 函数 | 此提交行号 | 已实施行为 |
| --- | --- | --- |
| `experiments/clock_manual_20260919/page_history.py` / `build`（新增文件，无旧行号） | [L40–L130](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_history.py#L40-L130) | 新增：只读复用账本，单份事件、分组与顺序、未确认/执行缺口及参数语义；身份候选引用同源正文。 |
| `experiments/clock_manual_20260919/page_history.py` / `event_text`（新增文件，无旧行号） | [L142–L153](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_history.py#L142-L153) | 新增：只读复用账本，单份事件、分组与顺序、未确认/执行缺口及参数语义；身份候选引用同源正文。 |
| `experiments/clock_manual_20260919/page_history.py` / `render`（新增文件，无旧行号） | [L171–L190](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_history.py#L171-L190) | 新增：只读复用账本，单份事件、分组与顺序、未确认/执行缺口及参数语义；身份候选引用同源正文。 |
| `experiments/clock_manual_20260919/page_history.py` / `attach`（新增文件，无旧行号） | [L193–L213](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_history.py#L193-L213) | 新增：只读复用账本，单份事件、分组与顺序、未确认/执行缺口及参数语义；身份候选引用同源正文。 |
| `experiments/clock_manual_20260919/page_history.py` / `link_incoming`（新增文件，无旧行号） | [L228–L237](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_history.py#L228-L237) | 新增：只读复用账本，单份事件、分组与顺序、未确认/执行缺口及参数语义；身份候选引用同源正文。 |
| `experiments/clock_manual_20260919/page_context.py` / `build` | [L109–L196](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_context.py#L109-L196) | 地图并入历史；目标参数摘要保留，旧图号有历史限定，接入单独历史后去重复。 |
| `experiments/clock_manual_20260919/page_context.py` / `_display` | [L199–L258](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_context.py#L199-L258) | 地图并入历史；目标参数摘要保留，旧图号有历史限定，接入单独历史后去重复。 |
| `experiments/clock_manual_20260919/page_context.py` / `attach` | [L322–L353](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/page_context.py#L322-L353) | 地图并入历史；目标参数摘要保留，旧图号有历史限定，接入单独历史后去重复。 |
| `experiments/clock_manual_20260919/history_context.py` / `action_context` | [L282–L299](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/history_context.py#L282-L299) | 普通动作上下文保留目标/条件/状态，事件正文归图；task_goal及特殊复核不删历史。 |
| `experiments/clock_manual_20260919/target_observation.py` / `describe` | [L8–L20](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/target_observation.py#L8-L20) | 仅观察概要/缺口；重复动作交接引用共享历史，不称旧登记为当前事实。 |
| `experiments/clock_manual_20260919/target_observation.py` / `handoff` | [L23–L33](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/target_observation.py#L23-L33) | 仅观察概要/缺口；重复动作交接引用共享历史，不称旧登记为当前事实。 |
| `experiments/clock_manual_20260919/region_tasks.py` / `plan_request` | [L46–L100](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/region_tasks.py#L46-L100) | 普通清点接同一历史，普通摘要不重复动作；任务身份与结束条件不变。 |
| `experiments/clock_manual_20260919/region_tasks.py` / `render_current` | [L306–L307](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/region_tasks.py#L306-L307) | 普通清点接同一历史，普通摘要不重复动作；任务身份与结束条件不变。 |
| `experiments/clock_manual_20260919/region_tasks.py` / `attach` | [L200–L303](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/region_tasks.py#L200-L303) | 普通清点接同一历史，普通摘要不重复动作；任务身份与结束条件不变。 |
| `experiments/clock_manual_20260919/stepwise_flow.py` / `_assemble_action_context` | [L412–L479](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/stepwise_flow.py#L412-L479) | 导航顺序/结果读取共享历史，正常组装接回执证据，执行协议不改。 |
| `experiments/clock_manual_20260919/stepwise_flow.py` / `assemble_current_context` | [L495–L543](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/stepwise_flow.py#L495-L543) | 导航顺序/结果读取共享历史，正常组装接回执证据，执行协议不改。 |
| `experiments/clock_manual_20260919/run_task_step.py` / `build_attempt_update` | [L53–L115](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/run_task_step.py#L53-L115) | 结果步接实际来源/工作/任务owner，原参数历史进入地图；保留正常Runner路径。 |
| `experiments/clock_manual_20260919/region_graph.html` / `pageMap` | [L20–L52](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/region_graph.html#L20-L52) | 网页显示同源历史；顶部统一说明观察新旧，无对应登记观察依据的状态不显示；旧登记状态可显示但限定来源。记录包含未执行情况，不从未知行为新建任务。 |
| `experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt` / 提示段落 | [L9–L9](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt#L9-L9) | 控件清点与原任务完成分开；具体可见但交互未知整体不得只因内部文字静态而被遗漏。 |
| `experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt` / 提示段落 | [L65–L65](https://github.com/melonthrower/regrow/blob/0a1a802c448d5f7b095a3b8915f364269f75ae81/experiments/clock_manual_20260919/遍历prompt/更新/区块变化与字段.prompt#L65-L65) | 返回标记描述恢复先前页面；添加/保存业务结果独立保留。 |

验收映射：

| 合同 | 直接验证 | 范围 |
| --- | --- | --- |
| 按控件分组、未确认归属、事件顺序、参数与精确去重 | test_page_control_history、test_current_page_context、直接相邻测试 | 69项聚焦含2浏览器；7旧失败基线复现不计通过 |
| 父目标准备、单图选择和导航绑定 | v3 search/discovery/navigation，4HTTP | 原正常请求/原答/绑定，0GUI，未受后续更新提示影响 |
| 添加结果、返回、参数历史及身份裁图 | v5 update_add/update_return/parameter，3HTTP | 原正常更新/原答登记；v3/v4 Add语义失败保留并拒绝 |
| 观察来源说明、隐藏无依据状态、未执行历史与折叠 | 最终HTML两项浏览器复查及真实登记副本只读预览 | 不改变模型请求，不是现场部署 |

最终采用6案例7HTTP，所有候选共15HTTP/0GUI。完整保存帧记录按原上下文恢复，不是连续新GUI导航。v3→v5仅更新提示改变；当前源码相对v5仅HTML显示。清点/动作1图，更新2图，参数更新4图。原始研究记录不删除、不回写旧现场。没有全门禁、完整Clock、跨应用或普遍可靠性结论。

源与证据：`to_astra/page_control_history_20261004_01/REPORT.md`、`VERSION.json`、`verification/final-source-delta.json`、`verification/final-audit.json`及各版本完整案例；Git导出只含已验源码/测试/设计，运行记录和截图仅在脱敏便携包。设计之后的改动必须更新版本/锚点，不能继续沿用本表。
