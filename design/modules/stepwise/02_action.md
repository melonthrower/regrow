# 第二步：选择并执行动作

[流程入口](README.md) · [第一步：发现](01_discovery.md) · [第三步：更新](03_update.md) · [测试索引](../../../tests/STEPWISE_INDEX.md#execution)

本页按职责整理后的源码连接调用流程；工作树候选和有限验收边界见[当前索引](../../CURRENT_FRAMEWORK.md)及[详细合同](../stepwise_debug_loop.md)。三步是职责阶段，不是固定三次模型调用；清点、恢复、核对或纠错可能增加调用，也可能本轮不执行动作。

## 读入当前目标，决定是否进入动作

[run_task_step.py](../../../experiments/clock_manual_20260919/run_task_step.py) 的 `run_step / _run_step` 读运行清单、当前知识快照及本轮截图，先续接待修复步骤和待结算动作，再处理发现、恢复或任务清点。

`_run_step.current` 核对前置条件，调用 [stepwise_flow.assemble_current_context](../../../experiments/clock_manual_20260919/stepwise_flow.py)；后者从 `knowledge_current.json` 指向的快照读取 Region、观察和运行状态。
[task_selection.attach](../../../experiments/clock_manual_20260919/task_selection.py) 用清点进度、已有任务和当前可交互区块选择原任务续进、普通导航、任务提出、功能整理或暂停。入口未定位可选择有当前依据的准备动作；历史路线只提供建议，每个新 GUI 动作仍走正常选择、绑定、投递和登记。

`working_region` 是工作目标，`source.region` 是动作请求的来源上下文，`task_region / task_name` 保留任务归属；前景子区块和实际动作对象可与任务 owner 不同。准备动作不能凭相似去向完成原控件任务。调度职责详见[调度与前置条件](routing.md)。

## 组装实际请求与输出合同

`stepwise_flow._assemble_local_context` 通过[02_动作选择.json](../../../experiments/clock_manual_20260919/遍历prompt/流程/02_动作选择.json)加载固定提示及[选择探索入口.schema](../../../experiments/clock_manual_20260919/遍历prompt/输出格式/选择探索入口.schema)；`assemble_current_context` 接上任务目标、控件候选、目标观察与共同地图。
`_run_step.current` 把普通动作的图片替换成本轮 `current.png`，刷新地图、目标观察及滚动边界。历史控件/动作文字提供线索，不证明本图可操作；上下文生产者见[地图与上下文](context.md)。

桌面请求还由 [desktop_transport.prepare_request](../../../experiments/clock_manual_20260919/desktop_transport.py) 调用 [prompt_delivery.desktop_parts](../../../experiments/clock_manual_20260919/prompt_delivery.py) 加入对应平台段落。检查最终发送内容时读取该 call 的 `request.json`，不能只看流程 JSON 或某一张 prompt。

## 校验提案、关联对象，处理无动作

普通运行用 [step_repair.Runner.perform](../../../experiments/clock_manual_20260919/step_repair.py) 的 `action` 阶段调用模型；不是用 `StepwiseFlow.choose` 绕开修复入口。
[repair_stages.accept_candidate](../../../experiments/clock_manual_20260919/repair_stages.py) 读取实际提交，执行请求 schema、`action_commands.validate`、`action_binding.bind_action_target`、观察来源及 `attempt_guard` 检查，返回提案、绑定和来源 call。

绑定用本轮坐标与登记外观候选关联控件；同点竞争等歧义进入 `BindingConflict`。现行路径也允许模型坐标执行但保留 `association.status=unconfirmed`，不能写成已确认身份。观察来源过期时刷新原任务请求，不能悄悄换成另一任务。

- `none + request_task_review`：进入已有任务的累计结果核对，核对结果不由动作步直接宣布。
- 普通 `none`：不投递，保存原因并设置 `next_action_mode=discover`，由第一步补发现。
- `skip_task`：仅按明确范围限制走 `traversal_scope.skip_prohibited`；定位困难不等于可跳过。

普通动作和所有 action 纠错都只附唯一当前选点图，包括投递前画面变化；[step_repair.request](../../../experiments/clock_manual_20260919/step_repair.py) 保留历史文字/路径作审计，不把更新阶段的多图坐标规则搬入动作阶段。
需要补定位时，`repair_stages.observe_registered` 走正常发现登记，再用 `refresh` 重建原任务的单图请求；修复次数和历史保留。纠错接口详见[纠错与恢复](repair.md)。

## 投递、保存回执，交给第三步

`_run_step` 保存 `proposal.json / binding.json / before.png`，投递前再次取图和核对窗口。画面或窗口变化时用 `Runner.reject_action` 保存未执行提案并暂停；续接纠错必须使用新的唯一投递前图。
实际投递由 `StepwiseFlow.execute` 调用本轮 `deliver`：先写 `execution_pending.json` 和 dispatch，再调用 [action_commands.execute](../../../experiments/clock_manual_20260919/action_commands.py)。`commands` 做平台转换，执行器记录实际命令、`executed_steps` 和回执；额度由框架计数。

`input_text` 先聚焦并核对对象，必要时重定位；对象未可靠确认可只留下点击而不发送文字。第三步必须读取 `text_delivered` 及实际步骤，不能把提案里的文字当输入事实。回执 `exit_code=0` 表示投递确认，语义结果仍未验证。

确认投递后保存 `after.png` 和窗口证据，`build_attempt_update` 把原提案、真实回执、绑定、任务及前后图交给 `Runner.perform('update')`；[第三步](03_update.md) 校验结果、登记图和任务并发布快照。
只有更新完成后才写 attempt 的 `commit.json` 并清除执行指针。续跑时，`resume_update_request` 对已确认回执仅补观察/登记；回执缺失或未确认则停在 `execution_unconfirmed`，禁止重复 GUI 投递。

## 改字段或动作时，沿生产者与消费者检查

| 连接内容 | 生产者 → 消费者 | 必须同时核对的异常路径 |
|---|---|---|
| `next_action_mode / observation / interactive_regions / active_task` | 发现、更新及 `task_routing.advance` → `assemble_current_context / task_selection.attach / _run_step` | 待发现、恢复、任务暂挂、无可执行工作；不能以空待办宣布全图完成。 |
| 请求 `source` 的观察、工作区块及任务归属 | `stepwise_flow / region_tasks` → `bind_action_target / attempt_guard` → 第三步 `settle_task / task_routing.advance` | 过期观察刷新必须保留原任务；准备动作与未确认对象不得借用其他控件的完成证据。 |
| `action / target / x / y / text / end_x / end_y` 与无动作标记 | 流程提示/schema、模型提案 → `repair_stages.accept_candidate / action_commands` → 更新的实际动作说明 | `none`、核对申请、范围跳过、平台不支持、坐标歧义；变更须覆盖普通与纠错 proposal。 |
| 当前图、`backend_candidates`、目标观察与滚动边界 | `_run_step.current / assemble_current_context` → 绑定和投递前检查 | 单图动作纠错、补发现后刷新、窗口变化；候选位置不能充当当前身份或动作成功证据。 |
| attempt 的提案、绑定、前后图、回执及执行指针 | `deliver / action_commands.execute` → `build_attempt_update / register_update.commit_update` | 部分输入、投递未确认、更新拒绝与 resume；保留原动作证据，继续结算而非重做 GUI。 |

验证从[动作索引](../../../tests/STEPWISE_INDEX.md#execution)及必要的[调度](../../../tests/STEPWISE_INDEX.md#routing)、[纠错](../../../tests/STEPWISE_INDEX.md#repair)相邻检查选择。本文只做代码连接和文档导航核对，不代表新增 Luna、GUI 或全框架验收。
