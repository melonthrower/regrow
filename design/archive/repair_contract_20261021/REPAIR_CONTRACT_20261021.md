# Clock 纠错合同与续接修复

基线：`00914d52391ae6dcb03db9a846f4e0c11bb85d16`（`codex/traversal-framework-20261020`）。本批修改由原50调用Clock证据驱动，不改原运行或模型原答。

## 问题与实现

- 0036纠错披露Add=index12，旧update schema仅0–11；0042/0043披露4/3，旧discovery schema仅0–2。`Runner.sent_request`只在初始调用保存发送合同，导致纠错回复又按旧合同校验。现在普通step_correction从实际落盘请求读取original_request用于后续接收；身份比较/选择仍走原专用衔接，旧编号保留、新身份追加。
- 第43次是未执行动作的发现步骤blocked；正常重新启动可重观察，但会话直接结束。`reobservable_block`复用原生可恢复判据，`run_session`每会话最多自动重观察一次，继续扣原预算；新轮次仍由`reopen_blocked`归档原失败。update、执行/导航待登记、服务拒绝等不走此路径。
- 0046未解问题偏到顶部控件，0048/49又把准备效果写到中央控件知识，0050混淆整个修复defer与任务defer。任务模块明确remaining_question不替换原控件；纠错模块说明用revise完整登记实际动作，同时continue/defer原任务。继续保留错误归属拒绝，不自动改绑、不伪造答案、不手改done。

## 具体变更地图

| 路径 | 责任与改动 |
|---|---|
| `src/regrow/traversal/step_repair.py` | `Runner.sent_request`沿发送的纠错原合同接收；`reobservable_block/reopen_blocked`共用无待登记动作的恢复判据。 |
| `src/regrow/traversal/run_progress_session.py` | `run_session`在correction_blocked时最多自动衔接一次可重观察步骤。 |
| `src/regrow/prompts/对象/任务.prompt` | `task.remaining_question`保持原目标与准备目标分开。 |
| `src/regrow/prompts/纠错/步骤纠正.prompt` | 明确完整结果修订与任务暂挂，不用外层defer跳过已执行动作登记。 |
| `tests/test_repair_sent_contract.py`（新增） | 新编号接收、旧编号/原答不变、未知编号仍拒绝；无动作一次重观察与有动作禁止重观察。 |

当前行号与实现提交在交付包中随最终源码锁定，不把本设计基线号当作修复提交。

## 验收边界

使用原0039发现和0048已执行动作更新的完整真实记录，经项目已有`tools/prompt_review_trace.py`重建、实际Luna原答、正常校验/纠错/登记。保存帧测试禁止GUI；原失败、源快照、请求/原答和账本保留。检查身份无重复、原任务不改绑、实际动作不重复、结果可登记且后读一致。静态测试不能替代此语义验收；实际结果以月志和交付记录为准。

## 讨论后补充与当前限制

- 已确认：功能任务目标与完成块统一一次适用操作的直接结果边界；已知用途仍不补证明任务。新版原0029保存帧已登记中央按钮知识和去向，不扩展非空条件调查。
- 已确认：建议投递与任务完成分开。`task_settlement.settle_task`复用执行匹配，向`task_updates.decide`提供已消耗状态；省略新建议时不继续暴露已经执行的旧建议。新增`tests/test_consumed_task_suggestion.py`覆盖未投递输入、失败、显式新建议与历史保留。
- 仍待讨论：直接使用稳定区块/控件引用替代临时index，以及如何在已有观察/图片条件中记录出现与消失，不另建平行可见性表；未落代码。
- 未解决：原0048场景采用原控件自身a0007历史证据回答时，动作后登记仍拒绝为当前准备动作的知识。候选不可据局部成功标整体接受。实际结果以月志和分版本原始请求/回复为准。
