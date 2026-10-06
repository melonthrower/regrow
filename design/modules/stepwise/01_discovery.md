# 第一步：发现与准备任务

[三步总览](README.md) · [开发入口](../../../DEVELOPMENT.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

当前截图和已提交知识 → 确认当前区块/控件 → 按需清点探索任务 → 交给第二步选择动作。
这里导航已提交的执行链；工作树地图修复候选仍未接受；同区块同控件/动作复用已实现，跨区块语义目标去重尚未实现。
“三步”是职责顺序，不是固定三次Luna调用：重定位、局部发现、补齐和纠错可能追加调用。

## 何时进入或重新进入

| 条件 | 实际连接 |
|---|---|
| 新run或启动后重新确认位置 | [app_launcher.create_run](../../../experiments/clock_manual_20260919/app_launcher.py)创建空快照，设置`next_action_mode=discover`和首图；续接可调用`await_discovery` |
| 当前状态要求发现 | [run_task_step._run_step](../../../experiments/clock_manual_20260919/run_task_step.py)先处理在途步骤/已执行动作，再由`Locator.discover / locator.run_stage`驱动发现 |
| 定位未确认或全局定位后需要局部控件 | `discovery_step.commit / traversal_scheduler.schedule_local_inspection`保留发现状态，转重定位或局部发现；已确认前景也可转普通导航选择 |
| 动作后登记无法确认可交互区块 | [register_update.commit_update](../../../experiments/clock_manual_20260919/register_update.py)保留已执行结果，转发现重定位，消费动作后图 |
| 任务清点发现控件缺口 | `region_tasks.commit_plan`保留任务，优先已有滚动清点任务，否则转局部发现；`discovery_inventory.supplement`携带缺口 |
| 补观察或异常恢复结束 | `repair_stages.observe / observe_registered`或`recover_loop.run`接回发现；`await_discovery`保留工作并使旧定位失效 |

## 普通请求到登记

1. [locator.request_from_run](../../../experiments/clock_manual_20260919/locator.py)读取`knowledge_current.json`指向的区块记录、运行状态和`pending_frame`，拒绝在非发现状态构造发现请求。
2. `prepare`使用历史视觉线索选择重定位或局部模式，组织当前截图、候选身份、已有工作和恢复交接，`request_from_run`补目标应用；模板匹配只是线索，仍需本轮视觉核对。
3. 固定提示按模式从[任务](../../../experiments/clock_manual_20260919/遍历prompt/任务)、[发现手册](../../../experiments/clock_manual_20260919/遍历prompt/发现手册)与共享段落组合。`schema / prepare`在[首屏观察.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/首屏观察.schema)上扩展身份、前景、控件字段；文件不是最终发送合同的全部。
4. `request_from_run`接入共同地图；地图与历史投影见[地图与上下文](context.md)，身份、前景和裁图资格见[观察与身份](identity.md)。这些共用职责保留在原模块，不在本页另造实现。
5. [step_repair.Runner.perform](../../../experiments/clock_manual_20260919/step_repair.py)调用并保存请求/原答；[repair_stages.accept](../../../experiments/clock_manual_20260919/repair_stages.py)经正常前景与身份检查，调用`discovery_step.commit`。
6. `commit`核对schema、当前状态/截图、身份引用和直接归属；[discovery_completion.prepare_registration](../../../experiments/clock_manual_20260919/discovery_completion.py)处理可登记部分与未解决缺口，未解决项仍进入发现补齐。
7. `commit`复用登记器保存观察及Region/控件图，`publish`发布新`knowledge_snapshots`并切换知识指针，保留旧快照；发现本身不创建GUI动作效果或跳转边。

发现输出包括当前观察、交互区块/控件引用、身份记录与待补缺口。成功局部发现仍不自动宣称控件已清点完整，也不完成已有任务。

## 任务清点是按需子流程

[stepwise_flow.assemble_current_context](../../../experiments/clock_manual_20260919/stepwise_flow.py)读取登记结果，经[traversal_scheduler.select_work](../../../experiments/clock_manual_20260919/traversal_scheduler.py)决定工作，再由action_proposer渲染；任务请求交TaskProposer；仍在`discover`时禁止构造动作上下文。
`attach`仅在当前范围需要任务清点/复核时返回`task_proposal`，不是每轮必调。`run_task_step._run_step`才执行该请求，再重新取得普通上下文。

- `plan_request`输入本区块已登记控件、当前定位与历史区分、已有任务/前置条件及入口证据；固定提示与底稿[区块探索任务.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/区块探索任务.schema)在该函数及`proposal_schema`组合。
- `commit_plan / apply_plan`检查观察归属、任务控件唯一性、动作/类型、已有同名任务一致性和清点覆盖，登记任务及`task_inventory`，通过同一`publish`保存。
- `inventory=complete`表示任务清点完整，任务执行进度由`coverage`另算。当前增补按本区块控件+规范动作复用；跨区块同目标语义去重仍未实现，见[任务规划与登记](tasks.md)。

[第二步](02_action.md)消费已登记身份、当前观察与任务卡，详细职责见[调度与前置条件](routing.md)和[动作选择与执行](execution.md)；得到一张可读地图或一份清单不证明控件、坐标或导航结果正确。

## 纠错、补观察与恢复

- 解析、身份、归属或清点校验失败回`Runner.perform`的原步骤纠错；`step_repair.request`构造纠错请求，`repair_stages.refresh`按正常入口刷新上下文，保留原答和失败历史。
- `observe_registered`为动作/任务清点等补定位，经自己的发现合同和子Runner登记，再回原任务；发现步的`observe`补新图并刷新原发现请求。补观察不是原动作后图，也不是任务完成证明。
- 发现确认异常时不登记Region/控件，转[recover_loop.run](../../../experiments/clock_manual_20260919/recover_loop.py)；恢复结束先`await_discovery`，再走同一`run_stage`，不能直接认定旧位置已恢复。
- 额度暂停、暂挂或未解决纠错保存原步骤；已投递动作先结算，不能因登记失败重做GUI。详细限制见[纠错与异常恢复](repair.md)。

## 改字段时核对跨步连接

| 改动对象 | 生产者 → 消费者 | 同时核对异常路径 |
|---|---|---|
| 身份、观察、前景、图像引用 | `discovery_step.commit` → `assemble_current_context`、动作绑定、[第三步更新](03_update.md) | 局部/重定位、同帧补齐、补观察、恢复后发现 |
| 任务、清点与前置条件 | `region_tasks.apply_plan / commit_plan` → `attach / coverage`、调度、执行后任务结算 | 清点partial、历史清点、原任务刷新、暂挂/恢复 |
| prompt/schema与名字映射 | `prepare / plan_request` → 原答校验、身份登记和任务登记 | 纠错proposal、`refresh`、记录修订后的有效请求 |
| 快照指针与运行状态 | `publish` → `load`、下一轮`_run_step` | pending步骤、旧观察拒绝、恢复/补登记接续 |

从测试索引的[身份](../../../tests/STEPWISE_INDEX.md#identity)、[任务](../../../tests/STEPWISE_INDEX.md#tasks)、[上下文](../../../tests/STEPWISE_INDEX.md#context)与[纠错](../../../tests/STEPWISE_INDEX.md#repair)栏目选择直接相关检查；索引不是全通过声明。文档导航只做链接与静态核对，行为验收另按现行原生请求要求记录。

[返回三步总览](README.md) · [返回开发入口](../../../DEVELOPMENT.md)

## 可调用组件（2026-10-06）
Locator.discover接收当前帧、run及原Runner，持有发现schema、上下文/请求、阶段驱动和局部视觉定位。TaskProposer持有任务schema、提示和历史/共享上下文，request/run交原Runner。discovery_step与region_tasks分别保留发现和任务正式登记；请求与调度调用方直接进入对应角色，原登记模块不再导出这些接口。普通工作及发现后的导航/检查安排归traversal_scheduler，两个组件不自行结束会话，也不是每轮必调。
