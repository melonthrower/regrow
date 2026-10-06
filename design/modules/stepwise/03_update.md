# 第三步：观察结果并更新记录

[流程总览](README.md) · [上一步：选择并执行动作](02_action.md) · [返回发现与准备任务](01_discovery.md)

**实际回执与动作前后图 → 更新请求 → 校验/纠错 → 发布快照 → 下一轮读取**。本页按当前调用链导航；工作树的当前地图候选仍未接受。

## 从实际动作到更新请求

[run_task_step._run_step](../../../experiments/clock_manual_20260919/run_task_step.py) 调用 ActionExecutor 保存真实回执、`after.png` 和同期窗口证据，再交 ResultUpdater.update；已执行待登记则优先 ResultUpdater.resume。

- [result_updater.build_attempt_update](../../../experiments/clock_manual_20260919/result_updater.py) 读取原 `binding.json`、`proposal.json`、`receipt.json`、前后截图及当前快照，提供工作区块、实际来源、实际执行步骤、任务绑定和共同地图历史。
- 输入文字未发送时，回执中的 `text_delivered` 与 `executed_steps` 保留实际点击事实；动作意图不能冒充已经输入。`task_region`、实际来源区块和 `working_region` 可以不同。
- [result_updater.build_update_request](../../../experiments/clock_manual_20260919/result_updater.py) 从[结果核对流程](../../../experiments/clock_manual_20260919/遍历prompt/流程/03_结果核对.json)组合 prompt 和[动作后更新 schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/动作后更新.schema)，仅为有任务的更新增补task_update（findings、next_action）。
- 原前后图在前；必要的历史身份对照随后附入，历史图不代表当前状态。最终请求保存到本次 attempt 的 `update_request.json`，固定文件不是完整发送上下文。
- [page_context.attach](../../../experiments/clock_manual_20260919/page_context.py)补共同地图与历史。地图是账本的只读投影，不是另一个事实写入者；共享输入详见[地图与上下文](context.md)。

## 从原答到正式记录

1. [step_repair.Runner.perform](../../../experiments/clock_manual_20260919/step_repair.py)以 `update` 阶段保存 episode、原请求、原答和失败历史；[repair_stages.accept_candidate](../../../experiments/clock_manual_20260919/repair_stages.py)连接身份准备、登记诊断和正式登记。
2. [result_updater.route_update](../../../experiments/clock_manual_20260919/result_updater.py)核对 schema 与真实回执；身份、归属、可见性、裁框和任务结果继续由登记路径检查。格式有效不证明视觉语义正确。
3. [register_update.commit_update](../../../experiments/clock_manual_20260919/register_update.py)从原 binding/dispatch 及选择请求的快照固定实际动作来源，登记观察、动作结果、变化和可观察关系；不会用模型标签改写执行事实。
4. [task_settlement.settle_task](../../../experiments/clock_manual_20260919/task_settlement.py)读取已附实际操作的动作记录，按区块/控件/动作更新已探索状态并保存参数事实；不另判业务效果成功。准备义务及异常仍按相应观察机制处理。
5. 完整 Region 记录、图像及 `runtime_state.json/source.json`先写入新 `knowledge_snapshots/`，再原子切换 `knowledge_current.json`；旧快照与原动作证据保留。

校验失败回原 update 纠错，可修提案、按证据修记录、补一次观察或保留缺口暂停；已执行动作只能修复登记。纠错仍保留原前后图，补图不能替换原动作后图，细节见[纠错与恢复](repair.md)。调用方可接入登记前语义审阅，但普通入口不默认启用自动审阅。

## 下一轮及按需整理

登记完成后，ResultUpdater.complete 写入 attempt 的 `commit.json`并清除 `execution_pending.json`；traversal_scheduler.preview_next 提供只读下一步预览。会话由 after_round 解释结果，再次进入正常单轮选择。

- **原子操作总结**：区块有效探索任务结束后，traversal_scheduler.select_work通过region_functions.next_ready安排现有request / commit。读取控件、任务、属性及实际动作证据，整理完整用户目的及约束；其他区块继续探索。auto空闲时仍可补历史清点，复用相同登记入口。
- 普通任务通过task_settlement.reconcile_run复用旧绑定动作，不发模型复核；异常暂挂仍可复查。知识整理完成后回正常单轮，再次空闲则停止；功能整理是按需子流程；功能/任务账面完成不等于全图实测完成。详细边界见[更新与登记](updates.md)、[知识与完成](knowledge.md)及[原功能合同](../stepwise_discovery_completion.md)。

## 修改字段时核对这些连接

| 字段或职责 | 生产者 → 消费者 | 相关纠错或恢复路径 |
|---|---|---|
| 实际执行、动作结果和来源 | 回执/binding → `build_attempt_update` → `commit_update` → 下轮地图/历史 | `resume_update_request`、update 原答纠错及 `suspended_updates`归档续登记；不重发已执行 GUI |
| 绑定探索进度、参数事实 | 实际动作+task_update → `settle_task` → 任务选择、功能证据 | 核对实际区块/控件/操作；显式异常复查保留，普通进度不发累计判断 |
| 观察、身份与图像 | 前后图/更新提案 → 身份/登记校验 → Region 快照 → 下轮发现/绑定 | `repair_stages`记录修订、补观察及归属复查；历史图保留时点 |
| 异常与下一阶段 | `action_result` + 回执 → `route_update`/运行状态 → 发现或恢复 | `recover_loop`读取已登记异常；恢复不自动完成原任务 |

改 prompt/schema、字段含义或保存方式时，同时检查上述生产者、消费者及异常路径；详细原合同见[身份与更新](../stepwise_region_identity.md)和[流程与修复](../stepwise_debug_loop.md)，不在导航页复制多套规则。

## 缺失结果的续接与当前边界

- 读取普通pending前，`_run_step`先调用 [suspended_updates.restore_next](../../../experiments/clock_manual_20260919/suspended_updates.py)，从`suspended_steps`恢复符合条件的原update episode及归档执行记录。原回执/前后图不完整时暂停，不能补拍历史后图或重做GUI。恢复后仍沿原Runner登记；`suspended_updates.validate_commit`在相关区块已有后续变化或涉及来源拆分时暂停；`suspended_updates.complete`在发布中保留当前工作，并标记`historical_update_registered`，下一轮以当前新图回到发现。归档恢复不是另一次动作执行，也不能用历史后图证明当前位置。
- 有 `pending_step.json`先恢复原 episode；有已确认回执而未 commit 的 `execution_pending.json`时，[result_updater.resume_update_request](../../../experiments/clock_manual_20260919/result_updater.py)复用原请求/后图，缺后图才补取，再进入原 update 登记，不重新执行动作。
- 已有 `commit.json`清理待执行指针；回执缺失或执行未确认则暂停，禁止重复投递。相同更新快照重放也不会回退较新的当前指针。
- 同区块同控件同动作复用已接入[任务模块](tasks.md)，保留blocked；没有实现跨区块语义目标去重。
- 当前地图误报及 Timer 单位推测仍按[更新模块的未接受状态](updates.md)保留。此次角色整理不改变探索进度合同；离线、保存帧和实机验证分别记录，不据此宣称地图误报已修好。

聚焦检查从[更新测试](../../../tests/STEPWISE_INDEX.md#updates)、[功能测试](../../../tests/STEPWISE_INDEX.md#knowledge)及[纠错测试](../../../tests/STEPWISE_INDEX.md#repair)选择；索引是定位入口，不是本轮运行或全通过声明。

2026-10-07候选将探索结算与具体产物登记衔接：参数findings、入口entry_registration、试探action_result；registration_gap保存未回答问题，正常纠错不重做已执行GUI。细节及旧证据边界见design/modules/stepwise/updates.md，尚待原生模型和实际续跑验证。
