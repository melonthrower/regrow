# 语义作用域探索实验设计

日期：2026-08-26

## 1. 目标

在现有 `--modular-explore` 运行链上增加一个显式实验开关，用语义上相关的功能作用域组织探索任务和历史。实验首先在电脑端 GNOME Clocks 上验证：Agent 能否在 World、Alarm、Stopwatch、Timer 等功能范围内持续探索，离开后恢复局部历史，并避免一个局部循环消耗全部动作预算。

本实验只证明工程可行性，不比较其他图方法，不声称提高全局覆盖率，也不替代现有完成证书。

## 2. 设计原则

1. **全局事实保持唯一。** Page、State、Region、Operation、Attempt 和 Transition 仍只保存在 `ExplorationLedger`；语义作用域只引用这些事实。
2. **去重职责不变。** 共享 Region 和 CanonicalOperation 继续决定跨 State/页面的身份与操作去重；作用域不得合并 Region、复用 Operation 结果或结算动作。
3. **作用域是上下文和调度单位。** 它决定当前集中探索哪些任务、向主 Agent 展示哪些跨页面历史，以及何时暂停一个局部范围去探索其他范围。
4. **语义分类允许不完整。** 无法合理归类的成员留在根作用域；作用域可暂定。第一版只支持创建、复用、改名和重挂父级，且这些调整不得改写原始证据；自动合并/拆分留待后续实验。
5. **实验默认关闭。** 不带实验开关时，Prompt、Schema、任务选择、账本和产物必须与当前 `--modular-explore` 完全一致。

## 3. 不在第一版范围内

- 不实现独立的第二张执行图。
- 不重写 Page/Region/Operation schema。
- 不让作用域决定真实路由、Region 身份、Operation 身份、安全审核或完成证明。
- 不要求所有页面、Region 和 Operation 都进入非根作用域。
- 不实现跨应用作用域。
- 不自动合并或拆分已有作用域。
- 不为 VS Code 的 Command Palette 等开放式列表设计通用穷尽算法；第一版只保留“同质内容代表性记录”的现有原则。
- 不把本次 Clock 运行称为全框架认证或与旧方法的性能对比。

## 4. 运行模型

```text
ExplorationLedger（唯一事实）
  Page / State / Region / Operation / Attempt / Transition
                         │ refs
                         ▼
SemanticScopeLedger（实验性语义视图）
  root
  ├─ World
  ├─ Alarm
  ├─ Stopwatch
  └─ Timer
                         │ active scope
                         ▼
Scope-aware Scheduler + Context Builder
```

### 4.1 SemanticScope

每个作用域包含：

- `scope_id`
- `name`
- `summary`
- `parent_scope_id`，根作用域为空
- `page_refs`
- `state_refs`
- `region_refs`
- `operation_refs`
- `status = active | parked | sufficiently_explored | partial`
- `created_seq` / `updated_seq`
- `reason`：模型对语义归类的简短解释

成员引用可以重叠，但每个任务只有一个 `primary_scope_id`。共享导航等跨功能 Region 可由多个作用域引用，真实 Region 仍只有一份。

`parent_scope_id` 从第一版开始持久化并校验无环，因此数据结构允许嵌套；电脑端 Clock 验收不要求模型必须创建子作用域。

### 4.2 SemanticScopeLedger

作用域账本作为独立 sidecar 保存，不改变 `exploration_ledger.json` schema：

- `semantic_scopes.json`：作用域、成员引用、状态和当前活动作用域；
- `semantic_scopes.json` 同时保存 `task_primary_scopes`，把 survey Task 绑定到 State 的主要作用域，把 Operation Task 绑定到该 Operation 的主要作用域；
- `semantic_scope_events.jsonl`：创建、复用、重挂、激活、暂停和状态变化事件；
- 原始动作历史继续只保存在正式探索账本，scope event 只保存其引用。

第一版支持同一次连续运行中的保存；resume 合同暂不扩展。若使用 `--resume` 同时开启实验开关，CLI 应明确拒绝并说明该实验尚不支持恢复，不能静默丢失作用域历史。

## 5. 语义作用域产生

当一个新 Page/State 完成 inventory，或已知 State 出现材料上新增的 Region 组合后，运行时调用一个只读 `Scope Organizer`：

输入仅包含：

- 当前 Page/State 的名称与摘要；
- 当前 Region 与 Operation 的紧凑文字卡；
- 已有作用域的名称、摘要、父级和少量成员名称；
- 当前活动作用域及导致本次落地的动作摘要。

它不接收全量历史，不执行 GUI 动作，也不判断 Region/Operation 身份。输出为严格结构：

- 复用已有作用域，或创建新作用域；
- 当前 State 的主要作用域；
- 当前 Region/Operation 到作用域的引用；
- 可选父作用域；
- 一句语义归类理由。

运行时只验证引用存在、父级无环和一个任务只有一个 primary scope。模型无法自洽或输出非法时，当前成员进入 `root`，探索继续，不重试 Organizer。

## 6. 作用域内调度

实验开关打开时，`TaskScheduler` 保留现有硬优先级：

1. 未结算的真实动作；
2. 已激活且必须继续的当前任务；
3. 当前 State 未完成的 survey。

需要选择新任务时才应用作用域策略：

1. 当前活动的叶子作用域仍有 pending/deferred 任务时，只在其中使用现有图距离与 Region 顺序选任务；父作用域只提供摘要与嵌套关系，不直接与子作用域争抢同一任务；
2. 当前作用域没有可运行任务时，将其标为 `sufficiently_explored` 或 `partial`；
3. 再按到各候选作用域最近任务的已验证图距离选择下一个作用域；
4. 无法归类的根作用域任务最后正常调度，不能永久饿死。

作用域只改变“从哪些候选任务中选择”，不改变任务本身的状态、Operation binding 或路线验证。

## 7. 作用域化上下文

主 Agent 每轮仍收到最新截图、待结算动作和当前精确任务。实验模式下，将全局上下文替换为：

- 当前活动作用域的名称、摘要、状态和成员概要；
- 当前 Page/State 中属于当前作用域的详细 Region/Operation；
- 当前任务的原有最近动作；
- 当前作用域最近的跨任务动作引用和简短结果；
- 父作用域摘要；
- 兄弟作用域的一行状态；
- 当前路由需要经过的 State/Transition；
- 当前截图上的共享 Region，以及它们现有的 CanonicalOperation 状态。

不发送其他作用域的详细 Region、Operation 和动作历史。当前 Page 上未归类但正在前景接管交互的临时 Region 必须保留，避免上下文过滤后点击背景控件。

## 8. 局部历史与停止

作用域历史来自真实 `HistoryItem` / Attempt 引用，不由模型自由改写。发送给 Agent 时分为：

- 当前任务最近动作；
- 当前作用域最近的关键动作；
- 更早事实的结构化状态摘要。

一个任务因现有拒绝、recover-no-effect 或动作预算合同失败时，只把当前作用域标为 `partial`；若该作用域还有其他可运行任务，继续局部探索，否则切换兄弟作用域。作用域不得把 failed Task 改成 done。

所有语义上不同、可安全执行的功能入口仍进入任务；同质枚举只保留代表操作的现有规则。第一版不新增基于应用名称或控件名称的 Clock 特例。

## 9. CLI 与产物

新增实验开关：

```text
--semantic-scope-experiment
```

约束：

- 仅与 `--modular-explore` 一起使用；
- 默认关闭；
- 与 `--resume` 同用时第一版明确报错；
- 使用与主探索相同的 `--explore-backend` 和 `--explore-model` 调用 Scope Organizer；
- `modular_completion.json` 保持现有含义，只增加可选的 sidecar 路径和作用域统计，不把 `sufficiently_explored` 解释为全局完成。

## 10. 预计代码边界

- 新增 `gui_rewalk/src/core/explore/semantic_scopes.py`：作用域记录、sidecar 持久化、Organizer 输入输出校验、作用域投影。
- `runtime.py`：在 inventory 提交后调用 Organizer；组装作用域化上下文；记录活动作用域事件。
- `tasks.py`：在选择新任务时增加 opt-in 的作用域候选过滤，保留现有任务优先级和距离排序。
- `status.py`：提供紧凑 scope context 与作用域历史投影。
- `run_visual_traversal.py`：增加实验 CLI 参数与不支持 resume 的明确校验。
- 聚焦测试覆盖作用域创建/复用/嵌套无环、调度局部性、根任务不饿死、前景临时 Region 不被过滤、默认关闭完全不变和 sidecar 输出。

不修改当前用户已有的 `gui_rewalk/src/core/scenario/live_state_locator.py` 与 `tests/test_live_state_locator.py` 工作树改动。

## 11. 验证与电脑端 Clock 实验

### 11.1 离线验证

按 Tier 3 运行直接受影响的探索内核测试、CLI 测试与语法检查。无需运行全框架回归门。

### 11.2 真实试跑

在本地电脑端 GNOME Clocks 启动一次新运行，使用现有安全、截图、Reviewer、Region/Operation 与动作结算合同，仅打开语义作用域实验开关。

可行性验收：

1. 形成 World、Alarm、Stopwatch、Timer 四个合理的顶层作用域，或留下有证据的不同合理分类；
2. 同一功能范围内的列表、对话框和运行状态能够共享作用域历史；
3. 调度在当前作用域仍有可运行任务时不无理由跳到兄弟作用域；
4. 作用域切换后再次进入时能恢复该作用域已有结果和未解决事项；
5. 共享导航 Region 与 CanonicalOperation 的既有去重结果不被改变；
6. 单个作用域出现 failed gap 后，其他作用域仍能继续；
7. 产出 `semantic_scopes.json` 和 `semantic_scope_events.jsonl`，引用均能解析到原账本；
8. 最终报告如实区分 `complete/partial`、bundle 状态和语义作用域状态。

本次不要求动作数、token 或完成率优于旧运行。若运行因 VM、模型服务、外部权限或现有 Region/Operation 错误失败，应按实际根因报告，不能把失败或成功都归因于语义作用域。
