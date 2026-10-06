# 逐步遍历器：按主流程开发

[完整代码职责表](CODE_MAP.md) · [开发总入口](../../../DEVELOPMENT.md) · [全项目模块](../README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

阅读主线：**发现与准备任务 → 选择并执行动作 → 观察结果并更新记录 → 下一轮**。异常处理贯穿三步，共享能力供各步骤调用。

| 流程入口 | 输入与输出 | 下钻到职责模块 |
|---|---|---|
| [第一步：发现与准备任务](01_discovery.md) | 当前截图与原记录 → 区块/控件观察及按需任务增量 | [观察与身份](identity.md)、[任务规划与登记](tasks.md) |
| [第二步：选择并执行动作](02_action.md) | 当前任务与执行依据 → 动作提案、绑定和实际回执 | [调度与前置条件](routing.md)、[动作选择与执行](execution.md) |
| [第三步：观察结果并更新记录](03_update.md) | 实际动作与前后观察 → 更新记录、任务结果及后续整理 | [结果更新与登记](updates.md)、[功能知识与完成](knowledge.md) |
| [异常处理与恢复](repair.md) | 原步骤、失败和证据 → 修正、补观察、恢复或暂停 | 各步通过原Runner连接；已执行动作先结算 |

实际入口是 [run_task_step.py](../../../experiments/clock_manual_20260919/run_task_step.py) 的 `_run_step`。这张表用于组织职责，不是严格每轮1→2→3的调用序列：已有观察可跳过发现，缺口会回到发现；任务清点、异常复查、功能整理是按需正常子流程，可在动作前调度。三步不等于三次Luna调用。

<a id="shared"></a>

## 共享能力及写入边界

| 共享职责 | 唯一定位入口与边界 |
|---|---|
| 地图、历史与prompt上下文 | [地图与上下文](context.md)：从既有账本投影，三步及纠错共用；投影不新增执行事实 |
| 身份、前景、模板与控件组 | [观察与身份](identity.md)：发现、动作绑定、更新共同使用；候选位置不证明当前存在或身份正确 |
| 记录保存与快照 | [更新与登记](updates.md)、[discovery_step.publish](../../../experiments/clock_manual_20260919/discovery_step.py)、[knowledge_transaction.py](../../../experiments/clock_manual_20260919/knowledge_transaction.py)：各阶段沿已有登记入口发布，不能让prompt投影直接改图 |
| 源码选择、传输、预算与进度 | [运行与环境](runtime.md)：与业务步骤分开；冻结run不会随checkout自动更新 |

每次修改沿[连接核对表](../../../DEVELOPMENT.md#change-connections)检查输入、校验、保存、下一步和相关异常路径；[测试索引](../../../tests/STEPWISE_INDEX.md)按流程选相邻检查。流程页只说明连接，原九份职责页保留源码/prompt清单和当前缺口，详细合同按其链接读取，避免复制出多套规则。

源码仍在 `experiments/clock_manual_20260919/`；已将任务选择、任务结算、模型发送、动作绑定及证据记录构造提取到独立文件。原公共函数名直接绑定唯一实现，唯一实现位置见[代码职责表](CODE_MAP.md)。源码位置与运行证据未搬动；普通任务进度现按[控件/动作绑定](tasks.md)维护，prompt/schema已同步。工作树原有地图候选仍未接受，不能据本批任务修复一并验收。代码存在、离线通过、保存帧模型验证、真实GUI验证分别报告。

## 按角色定位当前代码

| 原步骤 | 角色文件 | 正式记录入口 |
|---|---|---|
| 发现与准备任务 | locator.py、task_proposer.py | discovery_step.commit、region_tasks.commit_plan |
| 提出并执行动作 | action_proposer.py、action_executor.py | 原请求/绑定、attempt与receipt |
| 观察并更新 | result_updater.py | register_update.commit_update、task_settlement |

traversal_scheduler选择及续接工作；run_task_step连接角色。共享识别沿region_identity/history_matching，跨Region行为沿shared_controls，任务复用沿shared_tasks。角色文件直接持有主要逻辑，原动态加载/资源根/运行证据保持原位。
