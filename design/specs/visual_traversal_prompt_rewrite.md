# Visual Traversal Prompt 重写与流程设计

状态：逐步确认中

建立日期：2026-07-28

本文用途：新流程和 Prompt 的讨论真值，不以当前运行代码中的旧 Prompt 或临时实验为准。

## 1. 工作方式

- 每次只讨论、修改并提交一个调用。
- 已确认 Prompt 保留完整原文；未确认调用只记录目的、输入、输出和待解决问题。
- 新 Prompt 从调用目标重新设计，不从旧 Prompt 自动复制文字。
- 运行代码只在对应调用确认后映射，不在映射时追加应用特例、控件类别特例或额外模型调用。
- 保存截图实验只验证模型在给定截图上的表现，不等同于真实遍历通过。

## 2. 总体改动目标

旧流程把页面范围判断、区块划分、控件枚举、过滤和探索决策混在少数长 Prompt 中。一次观察出错会污染后续所有候选，重复调用也会重复支付整页观察成本。

目标流程按事实职责拆分：

```text
平台前台归属检查
  -> 页面身份判断
  -> 当前交互界面与候选 Region 目录
  -> 与历史 Region 做集合映射
  -> Region 调度
  -> 只观察当前选中的 Region
  -> Explorer 选择目标
  -> Grounder 在实时截图中定位
  -> 执行动作
  -> Observer 记录实际结果
  -> 更新 State / Region / ActionEdge 证据后继续
```

整体原则：

- 完整截图负责页面身份、当前交互界面和上下文判断。
- Region 首先是候选观察单元，不代表每个 Region 都必须立刻或完整探索。
- 区块发现保持较高召回；调度阶段决定先探索哪个，证据阶段决定何时完成。
- `defer` 只表示稍后处理；`covered` 必须来自真实观察、动作结果或已经验证的重复映射。
- 框架保存身份、历史、去重、路线和证据；VLM 负责当前截图中的语义观察与选择。

## 3. 当前进度

| 调用 | 状态 | 当前结论 |
|---|---|---|
| 平台前台归属 | 已确认不调用 VLM | 桌面只使用窗口 ID/PID/transient，移动端只使用顶层 Activity/task；系统证据持续不可用时 `focus_unknown` 失败关闭 |
| 页面身份判断 | 已确认并映射运行时代码 | Page 级候选筛选后，以开启 thinking 的两图二分类确认同页；不让 VLM 判断 State/Variant |
| 当前交互界面与候选 Region 目录 | Prompt 已确认并完成保存截图实验 | 菜单背景隔离有效；允许多报少量候选 Region |
| 相邻页面 Region 集合映射 | Prompt 已确认并完成保存截图实验 | 对应关系只基于持续存在的同一内容容器或同一对象身份，支持集合映射 |
| Region 调度与筛选 | 原则已确认，Prompt 未写 | 延后与完成必须分开；不按区块名称或控件数量硬编码 |
| Region 内部观察 | Prompt 候选已确认并完成保存截图实验 | 只输出选中 Region 中明显可用的功能入口，不枚举当前功能内部控件 |
| Explorer 决策 | Prompt 候选已确认并完成保存截图实验 | 当前 Region 内解除明显限制的入口优先，否则按已排序入口选择第一项 |
| Grounder 定位 | 已完成整图坐标 A/B 并映射运行时代码 | 始终使用完整截图和整图 `0..1000` 坐标；Region bbox 只作搜索提示 |
| 动作结果 Observer | Prompt 已确认并完成保存截图实验 | 输出可见变化事实及其与实际目标的直接关系，不再输出变化类型或 matched |
| 功能组合观察 | 移出遍历，归入 completion 后可选 enrichment | 候选发现可离线补充；真实动作、验证、恢复与 verified 晋升属于采集/M13 |

## 4. 已确认 Prompt：当前界面候选 Region 目录

调用目的：从一张完整截图中识别当前唯一的 active interaction surface，并建立该 surface 内的候选 Region 目录。

输入：

- 当前完整截图，不裁剪。

输出：

- `interface_name`
- `regions[].region_id`
- `regions[].name`
- `regions[].description`

确认版本：

```text
你是一名 GUI Agent 的视觉交互分析专家。

你的任务不是分析整个屏幕的视觉布局，而是识别当前 GUI 中用户真正可以探索和操作的交互空间。

你需要从截图中确定：

1. 当前唯一的 active interaction surface
2. 该 surface 内部的功能区域 regions

不要输出屏幕中所有可见区域。
只输出当前交互上下文中具有功能意义的区域。

---

# Step 1: Determine active interaction surface

active interaction surface 指：

当前决定用户下一步可执行动作的交互上下文。

判断依据：

不是视觉层级。
不是面积大小。
不是颜色突出程度。
不是是否覆盖在其他内容之上。

判断标准：

如果某个区域出现后：

- 改变了用户当前可以执行的操作集合；
- 成为了用户下一步操作的主要目标；
- 用户需要先与该区域交互才能继续当前任务；

则该区域形成新的 active interaction surface。

如果不存在这种变化，则当前主要应用页面保持为 active interaction surface。

---

# Step 2: Distinguish active surface from passive visual information

视觉上位于前景的内容不一定属于 active interaction surface。

如果某个区域：

- 只是解释当前页面已有功能；
- 只是展示状态变化；
- 只是提供辅助说明；
- 用户忽略它后仍然可以继续完成当前页面操作；
- 不产生新的操作路径；

则它属于 passive visual information。

passive visual information:

- 不创建新的 active interaction surface；
- 不作为 region 输出。

不要因为某个区域：
- 有明显背景；
- 有边框；
- 有文字；
- 位于前景；
- 视觉面积较大；

就认为它是新的交互界面。

---

# Step 3: Active surface selection rule

当前截图只能存在一个 active interaction surface。

如果发现某个区域形成新的 active interaction surface：

则：

- 只分析该 surface；
- 其他内容视为 inactive background；
- inactive background 不允许出现在 regions 中。

背景页面即使仍然可见，也不属于当前 region。

---

# Step 4: Region extraction

在 active interaction surface 内划分 regions。

Region 表示：

一个具有稳定功能意义的交互区域。

Region 是功能容器，不是单个操作目标。

正确粒度：

应该将：
- 服务于同一个功能目标的多个交互元素；
- 属于同一个视觉和语义区域的内容；

组合为一个 region。

不要将以下情况拆分为独立 region：

- 单个按钮；
- 单个文本；
- 单个菜单选项；
- 单个输入框；
- 单个可点击对象。

如果多个操作目标共同组成一个功能区域，
应合并为一个 region。

---

# Step 5: Region validation

输出前检查每个 region：

## Check 1
该 region 是否属于 active interaction surface？

如果不是：
删除。

## Check 2
如果 active interaction surface 消失，
该 region 是否仍然存在？

如果仍然存在：
说明它属于背景，不输出。

## Check 3
该 region 是否只是描述、解释或提示另一个功能？

如果是：
删除。

## Check 4
该 region 是否只是一个单独 action target？

如果是：
尝试与附近相关内容合并。

---

# Step 6: Output

按照视觉阅读顺序编号：

r0, r1, r2 ...

只输出 JSON。

不要输出解释过程。

格式：

{
  "interface_name": "...",
  "regions": [
    {
      "region_id": "r0",
      "name": "...",
      "description": "..."
    }
  ]
}
```

## 5. 页面观察 Prompt 验证记录

保存截图、真实 `qwen3.7-plus`、temperature 0 的结果：

| 截图 | 结果 |
|---|---|
| Settings 小菜单 | 只返回菜单 Region，排除侧栏和 Network 内容 |
| Clock 大菜单 | 只返回菜单 Region，排除闹钟列表和底部导航 |
| Settings 普通页 | 返回搜索、侧栏和三个网络功能候选区 |
| Clock 普通页 | 返回两个闹钟卡片、Add 入口和底部导航 |

结果位于 `artifacts/user_region_prompt_eval_v2_20260728/`。

已确认的运行解释：

- 页面观察负责选择唯一 active interaction surface，并同时给出候选 Region 目录。
- Settings 和 Clock 的菜单背景污染在本轮保存截图中已消失。
- 普通页面可能返回单独 Search Bar、Add Alarm 或重复闹钟卡片；这些候选允许保留，后续 Region 调度决定探索顺序和是否需要继续观察。
- 未被调度的候选保持 pending/defer，不因本次目录粒度而自动视为 covered。
- 当前仍需补测被动提示、状态反馈层和复杂对话框；这些验证缺口不改变 Prompt 已确认状态。

## 6. 已确认 Prompt：相邻页面 Region 集合映射

状态：已确认

调用目的：动作产生新截图后，比较前后两个界面各自经页面观察得到的 Region 目录，吸收相邻状态中的区块划分抖动，并区分延续、新增和暂时无法确认的 Region。

职责边界：

- 页面观察负责发现截图中实际存在的 Region。
- Region 映射只处理输入目录中已经存在的临时 ID，不补造 Region。
- 操作后未进入任何 `match` 的旧 Region 可由框架根据集合差值推导为当前不可见；Prompt 不重复输出该派生集合。

输入：

- 图 1：操作前完整截图
- 图 2：操作后完整截图
- 实际执行的动作
- 图 1 的 Region 目录
- 图 2 的 Region 目录

```text
你是一名擅长分析 GUI 界面内容组织变化的视觉分析专家。

图 1 是执行动作前的完整截图。
图 2 是执行动作后的完整截图。

你的任务是结合两张截图、实际执行的动作以及两张截图各自的候选 Region 目录，判断操作前后 Region 集合之间的对应关系。

对应关系只表示同一内容容器或同一对象身份在两次观察中持续存在。

位置相近、覆盖原位置、功能相似或由同一动作触发，都不能单独证明两个 Region 是同一个 Region。

实际执行的动作帮助理解界面为何发生变化。由同一个动作引起的多个视觉变化仍然分别按照各自的内容身份判断对应关系。

一次对应可以包含：

- 一对一；
- 一对多；
- 多对一；
- 多对多。

如果多个操作前 Region 与多个操作后 Region 共同表达同一组完整内容，则把它们放入同一个 match。

操作后出现、并且不属于任何操作前 Region 延续的内容，属于新增 Region。

现有截图和目录不足以确认来源的操作后 Region，属于 unresolved Region。

## 输入

实际执行的动作：

{action_json}

操作前界面：

{known_region_catalog_json}

操作后界面：

{current_region_catalog_json}

## 输出要求

输出中的 Region 只使用输入目录提供的临时 ID，不重复输出 Region 的名称和描述。

matches 表示已经确认的对应关系：

- known_region_ids：对应的操作前 Region ID 数组；
- current_region_ids：对应的操作后 Region ID 数组；
- reason：建立该对应关系的简短视觉依据。

new_current_region_ids 只包含操作后真正新增的 Region ID。

unresolved_current_region_ids 只包含当前证据不足以确认来源的操作后 Region ID。

每个操作前 Region ID 最多出现在一个 match 中。

每个操作后 Region ID 必须且只能出现在以下一个位置：

- 一个 match 的 current_region_ids；
- new_current_region_ids；
- unresolved_current_region_ids。

只输出 JSON，不输出分析过程或其他文字。

输出格式：

{
  "matches": [
    {
      "known_region_ids": ["A1"],
      "current_region_ids": ["B1", "B2"],
      "reason": "简短的视觉依据"
    }
  ],
  "new_current_region_ids": ["B3"],
  "unresolved_current_region_ids": ["B4"]
}
```

当前设计候选已完成真实 `qwen3.7-plus`、temperature 0 保存截图验证：

- Clock 闹钟卡片展开：四组 Region 均正确一对一延续，无新增或 unresolved。
- Settings 标题栏菜单展开：菜单 Region 被判为新增，没有错误映射到背景页面。
- Ubuntu Clocks 空 Alarms 页面点击 `Add Alarm`：连续三次均将 `Dialog Actions`、`Time Selection` 和 `Alarm Configuration` 判为新增，没有把旧导航栏映射到对话框动作栏。
- 五次调用均满足“每个操作后 ID 恰好归类一次”的输出契约。

验证结果位于：

- `artifacts/region_mapping_prompt_candidate_20260729/result.json`

上述两句替代此前宽泛的身份定义，作为后续统一映射源码时的设计真值，不再复测
旧文档 Prompt。

当前运行时 `build_region_partition_mapping_prompt()` 尚未改动。一次隔离对照发现，
如果只把这两句加入现有运行时包装、同时保留其中额外的共享界面定义和另一套映射说明，
New Alarm 样例连续三次仍发生错误对应。因此代码映射阶段必须用本节完整 Prompt
替换现有运行时包装，不能只追加两句。该源码替换按当前调试顺序推迟到所有 Prompt
逐段确认完成之后统一执行。

## 7. Region 探索账本与确定性调度

状态：原则已确认，不调用 VLM

页面观察得到的 Region 目录是当前界面的候选表。Region 映射将本次临时 ID 对应到稳定 Region 身份后，框架为每个稳定 Region 保存实际观察、动作尝试和结果证据。

调度由框架根据账本确定性完成：

1. 只保留当前 active interaction surface 中仍然可达的 Region。
2. 有完成证据的 Region 直接跳过。
3. 没有完成证据的 Region 保持待探索；一次观察、一次选择或一次失败都不会自动将其标记为完成。
4. 动作或模型调用因临时故障失败时，按调用所属步骤的重试预算处理；预算耗尽后暂时跳过该 Region，继续其他候选，但保留未完成事实。
5. 从剩余候选中优先选择从当前状态可达距离最近的 Region；距离相同时使用稳定的视觉阅读顺序。
6. 已知 State 重访时复用稳定 Region 账本，不重复执行整页观察和滚动。

Region 内部观察返回空 `function_entries` 只说明没有需要进入、切换、展开或解除限制的
功能入口，不能单独作为 Region 完成证据。Region 可能已经直接呈现具体操作界面，其内部
功能仍需由后续功能组合观察处理。重复结构的结果只有在代表成员的真实探索结果足以支持
共享时才传播，不能仅凭名称或外观相似跳过其他成员。

只有当前页面的全部可达 Region 都具有完成证据时，才能判定该页面的 Region 探索完成。因持续故障而暂时不可用的 Region 不计为完成，应在运行结果中保留未完成原因。

## 8. Region 内部观察

状态：Prompt 候选已确认，已完成保存截图实验，尚未映射运行时代码

### 8.1 调用目的

只观察一个已选中的 Region，输出其中当前明显可用的功能入口。

这里的功能入口只包括：

- 进入或切换到另一项独立功能内容的入口；
- 展开一组此前隐藏、可继续操作的功能内容的入口；
- 解除一组功能当前受到的限制的入口。

如果 Region 已经是某项功能的具体操作界面，其中用于执行当前功能、填写字段、选择
参数、改变数值或切换状态的控件不在本次输出中。它们留给后续功能组合观察，不在这里
枚举。

因此本调用不再输出 `region_state`、`availability`、`access_entries` 或功能描述，也不
建立跨 Region 前置关系。Unlock 等解除限制入口与其他功能入口统一放入
`function_entries`。

### 8.2 输入

- 图 1：当前完整截图，用于保留页面上下文；
- 图 2：目标 Region 的当前截图，用于限定观察范围；
- 目标 Region 元数据：`region_id`、`name`、`description`。

当前保存截图实验一次只观察一个 Region。批量输入未在本轮验证，不作为已确认合同。

### 8.3 输出

```json
{
  "region_id": "r0",
  "function_entries": [
    {
      "entry_id": "e0",
      "target": "Add Alarm"
    }
  ]
}
```

`target` 只标识截图中的可见入口。有文字标签时使用该标签；没有文字标签时使用图形特征
和所属对象。模型不复述证据，不描述入口打开后的功能；截图本身由框架作为原始视觉证据
保存。

空数组只表示当前 Region 没有本调用定义的功能入口。例如 Calculator 工作区和已经展开
的 New Alarm 配置表单都应返回空数组，但这不表示它们没有功能或已经完成。

### 8.4 确认 Prompt

```text
你是一名 GUI 界面观察助手。

图 1 是当前完整截图，图 2 是目标 Region。

请判断目标 Region 中是否存在当前可见且可使用的功能入口。

如果目标 Region 已经是某项功能的具体操作界面，其中的字段、选项和操作控件共同用于完成当前功能，则返回空数组，不输出这些内部控件。

只显示空状态、结果、列表或对象摘要的 Region 不属于上述具体操作界面；其中的功能入口仍需输出。

其他情况下，只输出符合以下任一条件的入口：

- 进入或切换到另一项独立功能内容；
- 展开一组此前隐藏、可继续操作的功能内容；
- 解除一组功能当前受到的限制。

只在当前 Region 内执行当前功能、改变数值或切换状态的控件不是功能入口。

明显灰显、禁用或是否可用无法确认的入口不输出。

只根据截图中可见的信息判断。如果没有符合条件的入口，返回空数组。

target 只标识截图中要操作的可见入口：有文字标签时使用该标签；没有文字标签时描述其图形特征和所在对象。

只输出 JSON，不要输出解释：

{
  "region_id": "<输入中的 region_id>",
  "function_entries": [
    {
      "entry_id": "e0",
      "target": ""
    }
  ]
}
```

### 8.5 保存截图实验

实验使用 `qwen3.7-plus`、`temperature=0.0`，输入完整截图与目标 Region 裁图。原始 Prompt、
裁图和逐次模型输出保存在：

`artifacts/region_local_entry_prompt_eval_20260729/`

确认版 `prompt_v13.txt` 的结果：

| 样例 | 预期与实际结果 |
|---|---|
| Clock 空闹钟区 | 只输出 `Add Alarm`；5/5 一致 |
| New Alarm 配置表单 | 返回空数组，不输出 Repeat、Name、Ring Duration、Snooze Duration；5/5 一致 |
| Calculator 工作区 | 返回空数组，不枚举数字键和运算键；5/5 一致 |
| Settings 打印机管理 | 输出 `Unlock...` 与 `Additional Printer Settings...`，不输出灰显的 `Add a Printer...`；5/5 一致 |
| Settings 应用菜单 | 只输出 `Keyboard Shortcuts` 与 `Help`；5/5 一致 |
| Android 闹钟卡片 | 只输出卡片右上角向下箭头，不输出启停开关；5/5 一致 |
| Settings Connectivity Checking | 返回空数组，不把当前设置开关当功能入口；5/5 一致 |
| Android Clock 底部导航 | 输出 `Clock`、`Timer`、`Stopwatch`、`Bedtime`，不输出当前已选中的 `Alarm`；5/5 一致 |

以上只是保存截图 Prompt 验证，不等同于真实遍历、运行时接线或完成证明。运行时代码仍
保留旧 Region-local 合同，待全部 Prompt 逐段确认后统一替换。

## 9. Explorer 决策

状态：Prompt 候选已确认，已完成保存截图实验，尚未映射运行时代码

### 9.1 调用目的

从当前 Region 的待探索 `function_entries` 中选择一个入口。

输入数组必须已经按照目标 Region 中从上到下、从左到右的视觉顺序排列。Explorer 不再
重新恢复视觉顺序，也不判断普通功能的重要性。只有当截图明确显示某个入口用于解除当前
限制、并会使更多功能可用时，才允许越过顺序优先选择该入口；否则选择数组第一项。

本调用只选择一个 `entry_id`，不输出坐标、动作类型、功能描述、`covered`、
`semantic_only` 或完成结论。已经执行或已经具有完成证据的入口由框架在调用前从输入中
移除。

当前候选只覆盖一个 Region。另一个 Region 中的解除限制入口不会被本调用跨区选择；它在
自身 Region 被调度后按同一规则处理。该设计可能推迟解锁，但不增加新的全页规划调用。

### 9.2 输入

- 图 1：当前完整截图；
- 图 2：目标 Region 的当前截图；
- 目标 Region 元数据；
- 按视觉顺序排列的待探索 `function_entries`。

### 9.3 输出

```json
{
  "selected_entry_id": "e0"
}
```

### 9.4 确认 Prompt

```text
你是一名 GUI 界面探索助手。

图 1 是当前完整截图，图 2 是目标 Region。

下面给出了目标 Region 中当前待探索的功能入口。入口已经按照截图中的视觉顺序排列。

如果某个入口明显用于解除当前限制，并会使更多功能可用，选择该入口。

否则选择列表中的第一个入口，不再判断功能重要性。

只能返回输入中已有的 entry_id。

只输出 JSON，不要输出解释：

{
  "selected_entry_id": "e0"
}
```

### 9.5 保存截图实验

实验使用 `qwen3.7-plus`、`temperature=0.0`，原始 Prompt、裁图和输出保存在：

`artifacts/function_entry_explorer_prompt_eval_20260729/`

确认版 `prompt_v3.txt` 的四类结果各重复十次：

| 样例 | 预期与实际结果 |
|---|---|
| Clock 单一 `Add Alarm` | 选择唯一入口；10/10 一致 |
| Settings 打印机管理 | 输入故意把 `Unlock...` 放在第二项，仍优先选择它；10/10 一致 |
| Settings 应用菜单 | 选择视觉顺序第一项 `Keyboard Shortcuts`；10/10 一致 |
| Android Clock 底部导航 | 选择视觉顺序第一项 `Clock`；10/10 一致 |

一次反向实验把菜单和导航候选数组打乱，再要求模型从截图恢复视觉顺序，底部导航出现
1/5 漂移；进一步强调视觉顺序后反而稳定地机械选择数组第一项。这说明视觉排序应由
Region-local 输出顺序和框架共同保证，不应在 Explorer 中重复判断。

## 10. Grounder 定位

状态：现有 Prompt 完成保存截图复核，不需要重写；新数据合同尚未映射运行时代码

### 10.1 调用目的

在当前实时截图中定位 Explorer 选中的单一 `target`，返回目标框与可点击点。一次调用只
定位一个目标，不枚举其他控件。找不到唯一目标、目标被遮挡或无法确认可点击点时返回
`found=false`。

历史坐标只能作为诊断证据，不能直接作为本次点击真值。

### 10.2 输入与输出

当前运行时始终使用完整截图，并在同一个整图坐标系中提供近似
`region_bbox_1000`。确认目标输入由 `function_entry.target` 构造，不依赖旧
Region-local inventory 的 `name/purpose/expected_immediate_effect` 等字段。

成功输出：

```json
{
  "found": true,
  "coordinate_space": "normalized_1000",
  "bbox_1000": [0, 0, 1000, 1000],
  "click_point_1000": [500, 500],
  "reason": "..."
}
```

失败输出：

```json
{
  "found": false,
  "reason": "..."
}
```

### 10.3 保留的现有 Prompt

当前源码 `gui_rewalk/src/core/visual_traversal/prompts/grounding.py` 中的
`TARGET_GROUNDING_PROMPT` 保留。它已经明确：

- 只定位一个目标；
- 只返回 `normalized_1000` 坐标；
- 目标框与点击点必须在目标 Region 内；
- 目标缺失、歧义、被遮挡或没有可靠点击点时返回 `found=false`；
- 不枚举其他控件。

### 10.4 保存截图实验

实验直接调用现有 `TARGET_GROUNDING_PROMPT`，使用 Region-local v13 的四类目标，原始
输出与人工目标框保存在：

`artifacts/function_entry_grounder_eval_20260729/`

| 样例 | 人工验收 |
|---|---|
| Clock `Add Alarm` | 5/5 点击点落在按钮内 |
| Settings `Unlock...` | 5/5 点击点落在按钮内 |
| Settings `Keyboard Shortcuts` | 5/5 点击点落在菜单项内 |
| Android 闹钟卡片向下箭头 | 5/5 点击点落在图标内 |

上述 2026-07-29 实验只验证 Region 裁图中的当前可见目标，没有覆盖真实 GUI 点击。2026-08-02
Calendar 真实误点后，使用同一错误截图和 `+` 目标进行正式 `qwen3.7-plus` 3+3 次 A/B：Region
裁图为 1/3，完整截图为 3/3。当前正式路径因此改为始终使用完整截图；证据位于
`artifacts/grounder_full_frame_ab_20260802_015459/`。

## 11. Observer 与图反馈

状态：Transition Observer Prompt 已确认，完成保存截图实验，尚未映射运行时代码

### 11.1 调用目的

比较操作前截图和操作后的最新截图，记录本次操作后实际出现的可见变化。

新的 Region-local 输出不再预测入口的目的页或立即效果，因此 Observer 不再接收
`control_purpose` 或 `expected_immediate_effect`，也不输出 `matched/mismatched` 或
`new_surface/content_changed/state_changed` 等变化类型。它只根据两张截图与本次可见
`target` 记录主要可见变化，并判断变化是否与目标具有直接对应关系。

### 11.2 输出

```json
{
  "observed_outcome": "",
  "relation_to_target": "related|unrelated|no_relevant_change|uncertain"
}
```

- `related`：变化中出现与目标本身直接对应的可见文字、控件或内容；
- `unrelated`：明确发生变化，但变化对应其他可见内容；
- `no_relevant_change`：没有观察到目标相关的明显变化，或只有时间、光标、动画等无关变化；
- `uncertain`：截图证据不足。

`observed_outcome` 和 `relation_to_target` 都不直接生成完成、覆盖、成功、失败或能力结论。

### 11.3 确认 Prompt

```text
你是一名 GUI 操作结果观察助手。

图 1 是执行操作前的完整截图，图 2 是执行操作后的最新完整截图。

本次实际操作的可见目标是：

{target}

请比较两张截图，记录图 2 相对于图 1 出现的主要可见变化。

observed_outcome 只描述截图中直接可见的事实。
优先依据界面中可见的文字、控件、内容、提示，以及它们的出现、消失或状态变化。
如果没有明显变化，填写“未观察到明显视觉变化”。

不要判断操作是否成功，不要判断目标是否达成，不要推测截图中没有显示的原因，也不要判断 Page 或 Region identity。
不要描述“目标被点击”等截图无法直接证明的动作过程。

然后判断观察到的变化与目标之间的关系。relation_to_target 只能选择以下一种：

- related：观察到的变化中出现了与目标本身直接对应的可见文字、控件或内容。
- unrelated：截图明确显示发生了变化，但变化对应其他可见内容，与目标没有直接对应关系。
- no_relevant_change：没有观察到与目标相关的明显变化，或者只有时间、光标、动画等无关变化。
- uncertain：截图证据不足，无法可靠判断。

不要根据 relation_to_target 推测原因。不要判断是否点错目标，也不要判断目标理解是否错误。

只输出 JSON，不要输出解释或 Markdown：

{
  "observed_outcome": "",
  "relation_to_target": "related|unrelated|no_relevant_change|uncertain"
}
```

### 11.4 保存截图实验

实验使用 `qwen3.7-plus`、`temperature=0.0`，原始 Prompt 与结果保存在：

`artifacts/transition_observer_prompt_eval_20260729/`

| 样例 | 预期与实际结果 |
|---|---|
最终确认前对严格 `related` 定义与扩展“对象/空间连续性”定义做了 A/B。两版各对四组
图片重复三次，关系标签均为 12/12：

| 样例 | 预期与严格版实际结果 |
|---|---|
| Clock `Add Alarm` 后出现 New Alarm 对话框 | `related`；3/3 一致 |
| Settings 标题栏菜单展开 | `related`；3/3 一致 |
| Android 闹钟卡片展开 | `related`；3/3 一致 |
| `Add Alarm` 前图与 World 页面后图的合成错配负例 | `unrelated`；3/3 一致 |

扩展定义没有带来可见收益，因此保留更简单的严格定义。严格版菜单样例有一次把
“按钮被点击”写入 `observed_outcome`，最终 Prompt 已明确禁止描述截图无法证明的动作过程。
完整 A/B 结果位于
`artifacts/transition_observer_prompt_eval_20260729/result_relation_ab_r3.json`。

本轮没有覆盖真实动作执行，也没有为 `no_relevant_change` 或 `uncertain` 新增 A/B 样例；
此前相同截图的 `no_visible_change` 保存帧实验仅作为旧 Prompt 证据，不冒充新合同验证。

动作后使用新截图记录真实可见结果。模型调用失败可以重试，但重试不重复 GUI 动作。
持续无法判断的尝试保持 unresolved，并继续其他可探索工作；不能伪装成成功、覆盖或遍历
完成。

## 12. 功能组合观察

状态：移出视觉遍历主链，归入 `completion.json` 之后的可选 capability enrichment

Region-local 合法返回空 `function_entries` 后，可以把本次 `region_observation` 标记为
complete；空数组表示该 Region 没有本调用定义的进入、切换、展开或解除限制入口，不要求
遍历阶段继续枚举当前功能内部的字段、选项和操作控件。

Calculator 工作区、New Alarm 配置表单和 Connectivity Checking 等直接呈现的具体操作界面，
可以在遍历完成后通过可选功能组合观察发现 operation/discovered capability 候选。该候选发现
不阻塞 `completion.json`。后续真实动作、结果验证、状态恢复以及从 discovered 晋升 verified
全部属于采集/M13，不属于视觉遍历 Prompt 链。

下一步先确认：

- 本调用只发现可见操作组合，还是直接形成 Capability 候选；
- 如何表示一组共同完成同一操作目的的控件，同时避免逐个枚举数字键等重复控件；
- 哪些结果必须等待真实动作证据后才能写入 Capability；
- 当 Region 既没有功能入口、也没有可组合功能时，框架如何获得完成证据。

在这些边界确认前，不先冻结输出 schema。

## 13. 当前代码与目标设计的差距

截至 2026-07-28，运行工作树仍包含未提交的历史修改和临时实验，本节只做盘点，不表示确认：

- `PAGE_MAP_PROMPT` 在工作树中仍是此前的短版中文 Prompt，尚未映射为第 4 节的正式页面观察 Prompt。
- `BlockFirstInventoryExperiment.discover()` 仍包含额外的 `semantic_active_region_filter` 调用。第 4 节正式 Prompt 已在同一次调用中负责 active surface 和候选 Region，因此该额外调用不属于目标流程。
- `prompts/interface_scope.py` 及其在身份、Region 映射 Prompt 中的复用仍是未确认实验，其中包含我们决定不继续叠加的共享硬定义。
- 页面身份、Region 集合映射、Region-local 观察和 Observer 的部分代码已经存在，但 Prompt 与数据契约尚未按本文逐段重新核对。
- 当前没有一轮基于本文完整流程的 Settings、Clock 或 Calc 真实遍历结果。

代码映射阶段必须逐项对照本文，删除被新流程替代的旧调用；不能在保留旧调用的同时再追加一层补丁。

## 14. 完成目标

本轮 Prompt 和流程重写完成时应满足：

1. 菜单、对话框和应用页面能够稳定选择正确的当前交互界面，被动提示不会错误接管页面。
2. Region 目录保持高召回，并通过相邻状态集合映射吸收划分抖动。
3. 只有被调度的 Region 才触发局部观察，重访不重复支付已经稳定的观察成本。
4. Region 延后、重复覆盖和完成都有可审计依据，不靠名称、位置、面积或控件类型硬编码。
5. Explorer 看到足够的当前截图、Region 上下文和真实动作结果，但不接收无关的全局图文字。
6. Grounder 对每次动作使用实时截图，Observer 把实际结果反馈回图。
7. Settings、Clock 和 Calc 的保存截图 Prompt 检查通过后，再进行真实 VM 遍历验证；保存截图测试不冒充真实遍历完成。

## 15. 讨论顺序

第 6 节“相邻页面 Region 集合映射”的设计候选已确认并记录，运行时代码留到全部
Prompt 完成后统一映射。第 7 节 Region 调度是确定性框架逻辑，不调用 VLM。

第 8 节“Region 内部观察”和第 9 节“Explorer 决策”已完成保存截图 Prompt 验证，第
10 节 Grounder 现有 Prompt 已完成新目标合同的保存截图复核，第 11 节 Transition
Observer 已完成保存截图验证。第 12 节功能组合观察已移出遍历主链。用户已经授权把截至
第 11 节的确认结果一次性映射进运行时代码。Page Identity 的候选筛选和两图二分类此前
已经确认并接入，因此不重复审查；至此正常 Region-lazy 遍历主链没有尚未逐段确认的 VLM
Prompt。统一接线完成后继续审查了恢复辅助调用 `return_path`：它仍依赖旧 Region 元素的
`purpose/expected_immediate_effect`，且历史 Android overflow-menu 试返曾把预期权限列表
错落到更上一级 App-info 页面。正式 Region-lazy 已删除该 VLM 调用，改由框架在既有安全
策略允许时选择 Android `navigate_back` 或桌面 `Esc`，再由 Router 与 Page Identity 验证
真实落点；旧整页回退保留原调用。
