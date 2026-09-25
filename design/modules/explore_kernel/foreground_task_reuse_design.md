# Foreground Region、任务复用与覆盖优先调度设计

日期：2026-08-26

状态：用户已批准，待实现

## 1. 决策摘要

模块化遍历改为以下唯一顺序：

```text
当前 active surface 清点
→ Region Identity
→ Operation Identity
→ 读取 canonical 任务历史
→ 物化新增逻辑任务或增加本地 binding
→ 两阶段最短路径调度
```

核心决策：

1. 只为当前最前景、可直接交互的目标应用 surface 生成 Region 和 Operation。被菜单、弹层或对话框接管的背景只作为截图上下文，不进入当前 State 的任务目录。
2. 新 State 中仍直接可操作的旧 Region 必须先做身份复用，再处理任务；共享 Region 不重复生成逻辑任务。
3. Region Identity 的正常路径只比较当前截图与动作来源的最近稳定截图。文字 shortlist 仅用于远距离补查，不能过滤前后截图候选。
4. 采用方案 A：任务历史由框架依据 canonical Region/CanonicalOperation 管理；Agent 只判断 Identity 后仍然新增的控件是否值得 `explore`。
5. 同一个逻辑任务可有多个 State 本地 binding。第一轮每个逻辑任务只尝试一个 binding；暂时失败后释放任务，继续最短路径上的其他未尝试逻辑任务。所有逻辑任务完成第一轮后，再复查 deferred 任务的其他 binding。
6. 任一 binding 验证成功后，整个逻辑任务完成；失败 binding 的证据继续保留，但不形成重复任务或重复 gap。

## 2. 目标

- 在尽量少的 GUI 动作和模型调用下，覆盖尽量多的不同应用功能。
- 避免同一控件随 State/Stage 变化反复生成任务。
- 避免菜单、弹层等瞬态 surface 为不可操作背景重新生成任务。
- 让共享 Region 在不同 State 复用同一任务历史，同时保留每个 State 的本地执行证据。
- 恢复“前后截图优先继承不变 Region”的视觉身份链，并限制候选图片数量。
- 保持真实 Attempt、before/after、失败、no-effect 和 landing 证据可审计。

## 3. 非目标

- 不增加应用名、页面名、控件名、坐标或截图专用规则。
- 不新增独立 Task Agent、Region 历史数据库、兼容层或第三套遍历模式。
- 不把相同名称、相同位置或相似外观直接当作 Region/Operation 同一性。
- 不把一个 binding 的成功或失败伪装成其他 binding 的本地执行证据。
- 不要求穷尽动态内容、列表数据项、每个同质值或每个应用页面。
- 不在本设计中重跑 Files 或 Terminal；后续 live 验证使用 Calculator 与另一个低风险代表应用。

## 4. 当前问题

### 4.1 Task 生成早于 Identity

当前 `apply_page_report()` 接受 `handling=explore` 后立即建立本地 Operation 和 Task，随后 runtime 才运行 Region Identity。若 Region 或 Operation 后续没有成功复用，重复 Task 已经进入调度池。

Calculator 证据：

```text
s6: r16 / o106 / co106 / Basic 计算器表达式输入框
s7: r19 / o134 / co134 / 计算器表达式输入框
```

两者视觉上是同一输入区，但正式身份未合并，因此 `t27` 只绑定 `s7/o134`。关闭菜单回到 `s6` 后，Scheduler 无法切换到当前本地 binding，转而要求重新路由到 `s7`。

### 4.2 active-surface 合同没有完整进入模块化清点

旧 semantic inventory 明确只登记当前最前景 active surface。当前模块化 Prompt 同时要求“最前景目标应用结构”和“新 State 的全部可见稳定结构”，导致菜单 State 同时写入菜单和仍可见背景。

正确边界：

- 菜单、弹层、对话框接管输入时，只清点该 active surface。
- 背景 Region 不写入当前 State 的 active Region 表，也不生成 binding。
- 新页面中仍可直接操作的持久导航栏、工具栏、侧栏属于当前前景，继续登记 occurrence，但必须先复用 identity。

### 4.3 文字 shortlist 阻断前后截图比较

2026-08-23 为降低候选截图和 Prompt 成本，Region 候选增加了名称、摘要和 Operation target 的文字 shortlist，并限制为两个候选 State。图邻居只影响排序，仍需先通过文字阈值。

Calculator Region 名称连续变化：

```text
s1: 表达式与结果显示区
s2: 计算器显示与输入区
s6: 表达式与结果区
s7: 计算器显示与表达式区
```

Operation target 也在通用、`Advanced`、`Basic` 前缀之间变化。真正对应的输入区和键盘未进入 Reviewer 输入；Reviewer 只收到应用工具栏候选，因此没有机会做视觉复用。

## 5. 概念模型

### 5.1 Canonical Region 与 occurrence

```text
Canonical Region
├─ State A 的 RegionOccurrence / RegionVariant
├─ State B 的 RegionOccurrence / RegionVariant
└─ CanonicalOperation 目录
```

Region 名称以 canonical Region 为权威。Main Agent 每帧名称只是 provisional proposal；Reviewer 确认复用后，当前 occurrence 使用既有 canonical 名称。

### 5.2 逻辑任务与本地 binding

逻辑任务的身份是：

```text
canonical Region + CanonicalOperation
```

本地 binding 是该逻辑任务在一个具体 State/RegionVariant/Element 上的执行位置：

```text
Logical Task L1：输入表达式
├─ B1：s1 / 本地 Operation o10
├─ B2：s6 / 本地 Operation o106
└─ B3：s8 / 本地 Operation o180
```

每个 binding 独立保存：

- 来源 State、RegionVariant、Element 和本地 Operation；
- 本地 `pending/deferred/failed/verified/recorded` 状态；
- Attempt、before/after、目标点、动作结果和失败原因。

逻辑任务汇总：

- 任一 binding `verified`：逻辑任务完成；
- 仍有未尝试或 deferred binding：逻辑任务未完成；
- 所有可用 binding 都终态失败：逻辑任务形成一个 failed gap；
- 多个本地失败不产生多个对外任务或 gap。

现有 Operation、Task、CanonicalOperation 和 bundle `task_bindings` 足以派生该历史，不新增平行持久化模型。

## 6. 前景清点合同

### 6.1 active surface

`page_report` 只包含当前能够直接接收用户交互的目标应用 surface：

- 普通页面：当前导航、工具栏、主内容等可操作 Region；
- 菜单展开：菜单自身；
- 模态对话框：对话框自身；
- 抽屉/命令面板：当前接管交互的抽屉或面板；
- 新页面仍持续可操作的导航栏/工具栏：继续作为当前前景 Region。

以下只作截图上下文：

- 被前景层接管的底层应用内容；
- 操作系统顶栏、Dock、任务栏；
- 宿主窗口管理控件；
- 其他应用、toast、tooltip 和装饰。

关闭/返回前景 surface 使用 `recover/route` 和来源 Transition，不要求为背景建立当前 State binding。

### 6.2 清点与 Task 物化分离

`apply_page_report()` 的事务拆为两个逻辑阶段：

1. **事实 staging**：写入 provisional RegionOccurrence、RegionVariant、Element 和本地 Operation proposal，但不调用 `_ensure_operation_task()`。
2. **Identity 与 task materialization**：完成 Region/Operation Identity 后，再依据 canonical 历史建立或复用任务 binding。

完整报告中的 `handling` 仍是 Agent 对当前可见 Operation 的任务价值建议，但不能绕过 canonical 历史创建重复逻辑任务。

## 7. Region 候选截图方案

### 7.1 第一阶段：前后继承

正常跳转仅提供：

```text
图1：当前完整截图
图2：本次动作的 inheritance source 稳定截图
```

来源 Region 不经过文字阈值过滤。Reviewer 比较当前前景 Region 与来源稳定 State 的所有 canonical RegionCard，确认持续 Region 和新增 Region。

`inheritance source` 选择：

1. 普通跳转使用真实动作的 source State；
2. 若 source State 是瞬态 overlay，沿现有 Transition/ActionAttempt provenance 回到最近的稳定 host State；
3. 优先从现有 attempt/transition 推导，不先增加持久字段；只有 resume 测试证明无法恢复时才考虑持久化 parent State。

### 7.2 第二阶段：远距离补查

只有第一阶段仍未匹配、且可能是历史 Region 的当前前景 Region 才进入补查：

1. 先读取历史 RegionCard 文字目录，不加载图片；
2. 只选择 Top-1 候选 State；
3. 第二次调用只提供当前截图与这一张候选截图；
4. 仍不确定则保持新 Region 或 uncertain，不继续扩展图片集合。

### 7.3 图片预算

| 场景 | 单次调用图片 | 单次跳转不同图片上限 |
| --- | ---: | ---: |
| 普通前后继承 | 当前＋来源，共 2 张 | 2 |
| 需要远距离补查 | 当前＋Top-1 历史候选，共 2 张 | 当前＋来源＋1 张历史图，共 3 张 |

多个未匹配 Region 指向不同历史 State 时，本轮最多处理一个候选 State；其余 Region 保持独立，不为追求合并率增加图片。

### 7.4 名称与候选原则

- 前后继承候选不受 Region 名称、摘要或 target 相似度门控；
- 文字相似度只排序远距离补查候选；
- Reviewer 看完整截图决定 identity；
- `reuse` 后 canonical 名称覆盖 provisional 名称；
- 证据不足保持 separate/uncertain，不能按名称自动合并。

## 8. 方案 A：任务历史与物化

Identity 完成后，框架逐个处理当前本地 Operation：

### 8.1 已有 CanonicalOperation

- 若已有逻辑任务：只增加当前本地 binding，不创建第二个逻辑任务；
- 若已有 binding 已 verified：当前 binding 记为 recorded/done，不调度；
- 若逻辑任务 pending/deferred：当前 binding 加入同一 logical task view；
- 若旧 binding failed：保留失败证据，当前 binding 仍可在第二阶段复查；
- 若历史只有 record、从未生成逻辑任务，而当前 Agent 首次给出有证据的 `explore`：允许创建该 canonical identity 的第一个逻辑任务。

### 8.2 新 CanonicalOperation

- `handling=explore`：创建一个新逻辑任务及当前本地 binding；
- `handling=record`：进入命令目录，不建立可执行任务；
- `handling=defer`：仅在当前确有可见阻挡/前置时建立 deferred binding。

### 8.3 Agent 上下文

正确性不依赖 Agent 记住完整历史。框架拥有去重权威。Agent 正常只接收：

- 当前 logical task；
- 当前可执行 binding；
- 当前 Region 的紧凑 canonical Operation 状态；
- 必要的最近失败原因。

不发送全应用任务历史、原始 attempts 或所有 State 的完整 Region 目录。

## 9. 两阶段最短路径调度

### 9.1 第一阶段：覆盖未尝试逻辑任务

目标：让每个不同逻辑任务至少得到一次真实尝试或明确不可执行事实。

优先级：

```text
未尝试 logical task
→ 当前 State 可执行 binding
→ 最短有向路径
→ 当前新前景 Region
→ 创建顺序
```

一个 binding 产生暂时失败或明确阻挡后：

1. 保存本地 Attempt 和失败/延期证据；
2. 将该 binding 标为 deferred 或 local_failed；
3. 将逻辑任务放入 deferred revisit 池；
4. 释放当前任务，选择最近的下一个未尝试逻辑任务；
5. 第一阶段不立即追逐同一逻辑任务的 B2/B3。

Scheduler 首次选择逻辑任务时仍可按最短已验证路径前往所选 binding；“失败后让路”只约束已经到达或尝试过的 binding。若该 binding 因前景恢复、界面变化或执行失败而不再可用，第一阶段不得为了同一逻辑任务立即重新路由回它或改追另一个 binding。

`no_effect + completed` 若本身已经回答功能问题，逻辑任务正常完成；只有结果仍不充分时才 deferred。

### 9.2 第二阶段：复查 deferred 逻辑任务

所有 pending/unattempted 逻辑任务完成第一轮后：

1. 重新收集每个 deferred 逻辑任务当前全部 binding；
2. 排除已 terminal-failed 的 binding；
3. 按当前图重新计算到每个未尝试 binding 的最短有向距离；
4. 选择最近且最新可见的 binding；
5. 尝试成功则完成整个逻辑任务；失败则保留证据并在以后考虑下一个 binding；
6. 所有 binding 均失败/不可达后，逻辑任务才形成一个 failed gap。

第二阶段优先级：

```text
存在未尝试 binding
→ 最短有向路径
→ 当前/最近可见 binding
→ 旧 deferred binding
→ 已失败 binding 不再执行
```

### 9.3 重复与恢复限制

- 相同 binding 的相同 action/target/direction/point 在 `no_effect` 后没有新 GUI 证据时不得立即重复；
- 瞬态 surface 的 recover 失败后释放任务，不形成开关振荡；
- route/recover 是到 binding 的准备动作，不新建逻辑任务；
- 现有单 Operation 动作预算保留为最终安全上限，但不用于鼓励同任务连续消耗预算。

## 10. 完成与 gap

完成门按逻辑任务计算，不按本地 Task 行数计算：

- 所有前景 State 完成清点；
- 所有 logical task 为 verified、recorded/done 或 terminal failed；
- 无 pending attempt、Identity review 或未结算 action；
- 同一 canonical task 的多个本地失败只形成一个逻辑 gap；
- 一个 binding 成功后，其他 binding 的失败仍可审计，但不阻塞完成。

结构闭合不自动证明首屏语义目录完整；保存帧验收必须另外检查前景 Region/Operation 漏报。

## 11. 失败关闭

- inheritance source 无法确定：不猜测共享，当前 Region 保持 provisional/separate；
- Reviewer 不可用或 uncertain：不合并，不扩展更多候选图片；
- Operation identity 未确认：不共享任务历史；
- 已选择的 binding 在到达/尝试后因 recover 或界面变化失去当前本地 binding：第一阶段释放并 deferred，不强制路由回旧 State；新选中的未尝试逻辑任务仍可按最短路径正常前往其来源 binding；
- 跨应用、危险、不可逆或外部效果：只记录，不执行；
- 中断时保存 ledger、Task/binding 状态、Attempt 和截图，未结算动作不记成功。

## 12. 验证设计

### 12.1 离线单元/合同测试

1. Calculator 菜单 State 只为菜单 active surface 建立 Region/Operation；背景输入区和键盘不生成 binding。
2. Files Home→Desktop 仅用当前＋来源两张截图候选，导航栏和工具栏复用，主内容保持新 Region/Variant。
3. Region 名称和 target 带 `Basic/Advanced` 前缀漂移时，来源 State 仍强制进入 Reviewer，reuse 后保留 canonical 名称。
4. `apply_page_report()` staging 期间不创建 Task；Identity 完成后才 materialize。
5. 同一 CanonicalOperation 多个 State binding 只形成一个逻辑任务。
6. B1 暂时失败后 Scheduler 选择最近的其他未尝试逻辑任务，而不是立即执行 B2。
7. 第一轮结束后 deferred 任务选择最短路径的未尝试 B2；B2 成功关闭整个逻辑任务。
8. B1/B2 失败证据保留，但 completion 只报告一个逻辑 gap。
9. 前后继承调用固定 2 张图；远距离补查最多增加 1 张不同历史图。
10. 所有规则不包含应用名、页面名、控件名或坐标特例。

### 12.2 保存帧验证

- 使用本轮真实 Calculator `s6/s7` 截图验证菜单前景目录与任务去重；
- 使用真实 Files Home/Desktop 截图验证两图继承，但不启动 Files live；
- 使用至少一个名称明显漂移的共享 Region 负例，证明文字 shortlist 不再阻断来源截图比较；
- 保存完整输入、原始输出、期望 identity/task materialization 和图片计数。

### 12.3 Live 验证

1. 受控 Calculator：打开菜单、关闭菜单、返回输入区，不再生成菜单 State 背景输入任务，不出现开关振荡。
2. 低风险代表应用：验证新页面持续导航/工具栏只增加 binding，不重复生成逻辑任务。
3. 监督检查动作总数、logical task 数、本地 binding 数、no-effect、rejection、图片调用数和 VM 清理。

Live 只证明所跑路径；不会表述为所有应用完整覆盖或正式认证。

## 13. 预期涉及模块

- `explore/prompts.py`：恢复 active-surface 清点合同；
- `explore/inventory.py`：拆分事实 staging 与 task materialization；
- `explore/regions.py`：来源 State 强制候选与远距离 Top-1 补查；
- `explore/runtime.py`：编排 staging→identity→materialization；
- `explore/tasks.py`：逻辑任务第一轮/第二轮调度和当前 binding 选择；
- `explore/status.py`、`bundle.py`：按 logical task 汇总完成/gap；
- `tests/test_explore_kernel.py`：合同、调度、图片预算和回归证据。

若实现期间证明现有字段足够，不新增 schema；若 overlay host 在 resume 后无法从 Transition/Attempt 恢复，必须先用失败测试证明，再讨论最小持久字段，不能预先增加。

## 14. 实施边界

- 先完成离线合同和保存帧验证，再启动 live；
- 不同时改 Page Identity、能力归纳、M13 或 API transport；
- 保持 `qwen_api/codex_cli/openai_api` 使用同一 Prompt、Schema 和 runtime；
- 不修改既有 raw 运行产物；新验证写入独立 run root；
- 每个行为变更按项目规则更新当前模块文档、月度 changelog，并创建独立本地提交。
