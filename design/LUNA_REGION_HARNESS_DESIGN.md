# Luna 独立遍历 Harness：经验总结与下一版设计

最后更新：2026-08-27

## 0. 新任务快速入口

本文是当前 Luna 遍历研究的交接文档。新任务开始时先读：

1. `design/RESEARCH_GOAL.md`：全局研究目标与证据边界；
2. 本文：独立 Luna harness 的经验、建议合同和下一步；
3. `design/CURRENT_FRAMEWORK.md`：只有准备复用或修改主框架时才继续读对应模块文档。

当前最小下一步不是重写主框架，而是为独立 harness 接入 framework-owned
`Region / CanonicalOperation / local Operation` 编号和消息分层，然后做一次固定合同、
无 Codex 在线纠错的 Luna-only Clock run。通过后再依次验证 Settings 和 VS Code。

## 1. 研究定位与边界

这项工作回答：

> 在没有 Codex 在线监督的最终运行中，怎样用最小 Prompt、稳定图上下文、动作空间和
> 确定性门禁，引导 API 方式调用的 Luna 完整探索 GUI，并生成与当前框架兼容的
> Page / Region / Element / Operation 图？

当前研究暂时独立于主框架：

- Luna 负责语义观察、选择需要探索的逻辑操作、解释真实前后变化；
- harness 负责分配稳定 ID、保存前后截图、校验 owner、执行动作、管理 pending、去重、
  路线重放、安全和完成判定；
- 独立 grounder 只根据最新截图定位已经选定的语义目标，不参与规划和图身份判断；
- Codex 只在开发期作为教师，记录低级模型错误并给出最小纠正；
- 最终验收必须在 Prompt/harness 固定后由 Luna-only 运行完成，途中不能再注入教师答案。

本研究不直接改变目标先行任务生成、Capability 组合、M13 或 cleanup 合同，也不以当前
teacher-student pilot 宣称主框架迁移成功、遍历优越性或论文贡献已经得到证明。

## 2. 已有实验证据

### 2.1 早期独立 pilot

- 桌面 Clock、VS Code 和移动 Google Clock 已完成 bounded teacher-student pilot；请求均
  确认 effective model 为 `gpt-5.6-luna`、`store=false`，并能产生当前框架格式的图。
- 这些结果只证明 Luna 能在显式图上下文中探索和生图，不是完整遍历证书。
- 同屏坐标探针中，Luna 的 `0..1000` 与 raw-pixel 明确坐标合同均为 14/14 命中；移动
  Clock 又完成 12/12 次 fresh-frame raw-pixel grounding、0 次纠正。因此高层语义选路与
  最新帧定位可以拆开，不能据此宣称跨应用定位准确率。
- 移动 Clock pilot 完成 20 个真实动作、6 Page、13 State、72 local Operation、18
  Transition，但仍有 49 个 pending/deferred gap，Settings 长页面只做了一次滑动，不能称为完整探索。

### 2.2 Region 可达图 desktop pilot

底层表示为：

```text
RegionState -- CanonicalOperation / RegionEvent --> RegionState
```

Page 只作为便于理解和检索的语义宏，不是底层路由节点。

| 应用 | 验收状态 | 真实动作 | Region | RegionState | 本地 Operation | 可达边 |
|---|---|---:|---:|---:|---:|---:|
| GNOME Clocks | `complete_with_policy_exclusions` | 80 | 12 | 58 | 221 | 109 |
| GNOME Settings | `partial_failed_gap` | 145 | 59 | 206 | 735 | 286 |

Clock 图的已观测路由节点属于一个弱连通分量，最长已观测最短路径为 9 个 Region hop。
Settings 最大弱连通分量包含 174 个路由节点，最长已观测最短路径为 19 hop。这证明
Region 可达图能够表达菜单、弹窗、选择器、侧栏分类和多面板变化，但尚未验证编译路线的
多步快速重放，因为 pilot 中每一个动作仍由高层 Luna 重新选择。

Settings 的 Sound 分类在两次 fresh-frame 正确落点后都导致 Settings 窗口消失。该事件是
`environment/app_disappeared`，不是 grounding error；运行保留失败边并以 partial 收尾。

### 2.3 稳定编号与缓存探针

- 保存截图稳定编号探针为 2/2：Clock Shortcuts 返回 `r2/co2/o2`，Settings Never 菜单
  返回 `r11/co11/o11`。它只证明候选完备时 Luna 能遵守 harness-owned ref 和 owner。
- 高层 Region pilot 通常只命中稳定系统段 1,291 cached tokens；231 次 fresh-grounder
  调用全部为 0；一次完整用户输入与截图相同的重试命中 14,675。
- 纯文本缓存探针中，同一 user message 内拆 content block 不能复用变化前的长文本；把
  稳定前缀单独放进前置 developer message 后，动态 user 后缀变化时命中
  5,442/5,452 tokens，完全相同请求命中 5,449/5,452。

## 3. 最重要的经验

### 3.1 图可以 Region-centered，但 Page 不应删除

GUI 中有意义的局部变化通常可以描述为：对一个 Region 内的控件执行操作，随后一个或多个
Region 出现、消失或改变。因此底层路线使用 RegionState 和 RegionEvent 更自然，尤其适合
桌面端的侧栏、工作区、弹窗、菜单和详情面板。

Page 仍有三个实际用途：

- 给移动端整屏跳转和用户可理解的主要目的地命名；
- 限制 Region 候选召回和历史噪声；
- 作为路线、截图和报告的语义宏。

结论不是“Region 替代 Page”，而是“RegionState 是底层变化和路由节点，Page 是上层语义宏”。
不要求把若干 Region 拼成一张历史上真实出现过的完整界面；路线只依赖已验证的 RegionEvent。

### 3.2 语义子图适合作为工作集，不适合作为刚性真值

Alarm、Timer、World、VS Code Editor、Source Control 等语义范围可以作为探索工作集：只投影
当前范围相关 Region、操作和历史，从而降低上下文和导航成本。子图可以嵌套，例如
`Clock -> Alarm -> Alarm editor -> Repeat selector`。

但子图不应强迫真实 GUI 形成互斥分区：

- 一个共享导航 Region 可以同时服务多个语义子图；
- 一个设置弹窗可能从多个功能入口到达；
- 跨范围关系仍保存在全局 RegionEvent 图中；
- 子图只是 scheduler/context projection，不重新分配 Region ID，不复制 Operation 和证据。

这避免了在 VS Code 等密集界面中一次提出过多任务，也避免为复杂交叉关系设计难以维护的树。

### 3.3 模型不能分配稳定 ID

主框架已经有：

| ref | 含义 |
|---|---|
| `rN` | 跨状态稳定的逻辑 Region |
| `rvN` | Region 在当前布局/状态中的可见版本 |
| `coN` | 跨 Variant 稳定的逻辑操作 |
| `oN` | 当前 Variant 中可执行的本地 binding |

独立 harness 应直接复用这一思想：

- 已知对象：Luna 只能引用输入中存在的 ref；
- 新对象：Luna 返回 `status=new` 和候选语义，不填 ID；
- harness 审核后分配 ID，并在下一轮作为已知 ref 返回；
- `coN` 必须声明 owner `rN`，执行时必须绑定当前可见的 `oN`；
- 未知 ref、错误 owner、背景遮挡 binding 和跨 Variant 陈旧 binding 都由程序拒绝。

稳定 ID 的目的不是让模型记住数字，而是让模型无法用近似文本偷偷创建第二份同一对象。

### 3.4 Region 相同不代表其中全部 Operation 相同

Operation 去重的建议逻辑键是：

```text
canonical Region
+ action type
+ semantic control role
+ direct effect
+ acted object type
```

具体规则：

- 同一个控件在多个 RegionVariant 中出现，只保留一个 `coN`，每个 Variant 保留自己的 `oN`；
- Timer 的 Start、Pause、Reset 是三个操作；同一个 minus 控件连续点击五次，仍是一个操作和
  五条 ActionAttempt；
- 同一选择器的 Never/Automatic/Manual 优先保存为一个参数化操作的值域，不把每个值都扩张成
  独立能力；若直接效果或安全性不同，可保留不同本地候选，但仍由同一控件和参数域组织；
- 重复列表项共享操作机制，通过 object binding 区分作用对象，不为每一行复制能力定义；
- 普通滚动按 Region + axis/direction 保留一个 RegionOperation，多次滚动作为尝试，直到顶部、
  新内容、底部或同质停止得到证据。

去重的是逻辑图，不能删除原始 before/action/after、失败、重试和教师纠错记录。

### 3.5 RegionState、Event 和历史也要去重

- RegionState：只有功能内容、可用控件或直接语义状态变化才新建。鼠标悬停、背景变暗、自然时间
  跳动和无功能影响的焦点变化不新建。
- 前景层：弹窗出现时新增前景 Region；背后的 Region 保持原状态，只标记
  `blocked_by_foreground`。不能为所有灰色背景复制一套 State 和 Operation。
- RegionEvent：相同来源状态、`coN`、直接效果和目标 RegionState 集只保留一条逻辑边；多次
  ActionAttempt 挂在该边下。
- Page macro：同一主要目的地上的临时菜单和弹窗不自动生成新 Page。
- Prompt history：发送一个 canonical 操作卡、当前终态和尝试计数，不重复发送所有本地 binding
  和完整旧理由。

### 3.6 Task/TODO 不是完整性的基础

Task/TODO 可以帮助低级模型聚焦，但不应成为图真值或完成判定。更稳定的控制依据是：

- 每个已发现 canonical Operation 有一个明确终态；
- 当前 Region 的可见控件清点完成；
- 可滚动 Region 有顶部/新内容/底部或同质停止证据；
- 没有未结算 pending action；
- 没有未恢复的临时改变；
- 不安全、外部、不可达和环境失败均有明确 gap/exclusion，而不是静默跳过。

语义子图任务只决定当前工作集。完成一个 Alarm 子图后再调度 Timer，可以减少路由和历史长度，
但全局完成仍由共享账本事实推导。

## 4. 建议的下一版 Harness

### 4.1 总体调用链

```text
最新截图
  -> 高层 Luna：观察/更新 Region，选择 canonical Operation 或提出结束
  -> harness：校验 ref、owner、安全、当前可见 binding
  -> fresh-frame grounder：只定位已经选定的 oN，返回 raw pixel
  -> executor：执行一次动作，保存 before/action/after
  -> 高层 Luna 或窄 observer：结算真实结果并更新 RegionEvent
  -> scheduler：根据 canonical Operation、scroll 和 gap 选择下一工作集
```

对于已经验证的多步路线，改为：

```text
1 次高层规划：选择目标和已验证 co 路线
N 次 Grounder：每一步都在最新截图上重新定位当前 oN
1 次高层验证：确认最终 Region/业务效果
```

页面或 Region 变化要求重新 grounding，但不要求重新高层规划。只有以下情况重新调用高层 Luna：

- 预期目标在最新截图中不存在或不唯一；
- 出现未记录的前景层、外部页面或应用消失；
- 实际落地与已验证路线不一致；
- 动作 no-effect 且不能由已有终态解释；
- 到达路线末端，需要最终语义验证。

主框架已有更保守的点击锚点重放：完整截图字节相同、成功首跳和局部锚点唯一时可省略当轮
主 Agent。下一版独立 harness 可以复用该能力，但 fresh screenshot 不同就必须重新定位，不能
盲点历史坐标。

### 4.2 高层 Luna 的最小输入

稳定 developer message：

- Page / Region / RegionVariant / canonical/local Operation 的简短定义；
- `known/new/uncertain` 合同；
- owner、前景、安全、pending 和 bounded finish 规则；
- 当前语义工作集内稳定的 Region/Operation ref 卡；
- 已编译路线及允许动作空间；
- 固定结构化输出 schema。

动态 user message：

- 最新完整截图；必要时附当前 Region crop；
- 当前 Page macro、可见 Region ref 和当前步骤；
- 唯一待结算 ActionAttempt 的 before/after；
- 上一轮新增事实的短 diff；
- 具体错误反馈，不重复全历史。

不要把不断增长的整图、全部历史、全部候选和所有原始理由放进每一轮 Prompt。

### 4.3 建议的高层输出

```json
{
  "previous_action": {
    "attempt_ref": "a17",
    "outcome": "success|no_effect|failed|uncertain",
    "observed_region_effects": [],
    "reason": ""
  },
  "region_updates": [
    {
      "status": "known|new|uncertain",
      "region_ref": "r3",
      "candidate": null,
      "visible_state_summary": ""
    }
  ],
  "next_action": {
    "canonical_operation_ref": "co8",
    "operation_ref": "o21",
    "purpose": "execute|route|recover",
    "reason": ""
  },
  "finish_proposal": {
    "finish": false,
    "remaining_gaps": []
  }
}
```

约束：

- 已知对象必须引用已有 ref；`new` 候选不带伪造 ref；
- `execute` 必须同时带当前本地 `oN`，`route/recover` 不冒充功能证据；
- 一轮最多一个动作；pending 未结算前不能提出下一动作；
- 坐标不属于高层输出。

### 4.4 Grounder 合同

输入：

- 最新截图或安全的 Region crop；
- raw width/height；
- `oN` 的语义目标、owner Region、动作类型；
- 可选的历史 anchor/crop，只作为检索提示。

输出：

```json
{
  "target_visible": true,
  "identity_matches": true,
  "unique": true,
  "safe": true,
  "x": 1310,
  "y": 214,
  "reason": ""
}
```

Grounder 不判断下一步、不改变图、不使用旧坐标作为答案。定位失败记录为 `grounding_error`，
不让高层 Luna反复选择同一目标，也不把错误点击结果写成 Operation 语义证据。

### 4.5 确定性门禁

harness 至少负责：

1. ref 存在性和 owner/binding 一致性；
2. 前景 Region 可执行性；
3. 操作安全策略和应用范围；
4. pending attempt 一次且仅一次结算；
5. `no_effect/failed` 后禁止立即重复同一逻辑操作；
6. canonical Operation、RegionState、Event 和 scroll 去重；
7. finish 的 operation/scroll/pending/restore/gap 闭合；
8. 应用可见性，而不是仅相信启动命令返回成功；
9. 原始模型回答、最小纠正和前后图的可审计保存。

## 5. 缓存与上下文组织

当前 OpenAI-compatible 请求把固定 `instructions` 放在前面，但把整份动态图、历史和当前任务
合并成一个 user input_text。服务只稳定命中系统段；user 内容即使有很长的字符公共前缀，
只要该消息变化就不会稳定复用。

下一版采用：

```text
developer message: 固定基础合同 + 本次工作集/路线内保持不变的 ref 卡和计划
user message: 最新截图、当前步骤、pending 结果和短 diff
```

路线或工作集切换时允许重建一次稳定段；随后 N 个 grounding/执行步骤复用它。不要为了达到缓存
门槛给 Grounder 填充无用文字。Grounder 成本应通过 Region crop、较小图像和更短语义目标降低。

任何缓存收益必须同时报告功能覆盖、错误率、`cached_tokens`、`cache_write_tokens`、总 input
tokens、调用次数和费用；不能只看命中数。

## 6. Codex 教师经验如何转化

教师纠错不应作为最终运行能力，而应转化为以下四类机制之一：

- Prompt 规则：跨应用都需要的稳定语义原则；
- 上下文检索：模型缺少某个已有 Region/Operation 候选；
- 确定性门禁：ID、owner、pending、重复、finish、安全等程序可以判定的错误；
- Grounder/执行器规则：坐标、可见性、应用范围和实际落地问题。

每条开发期错误保存：

```text
原始 Luna 回答
+ before/after screenshot
+ 错误分类
+ Codex 给出的最小纠正
+ 最终应该归入 Prompt / retrieval / gate / grounder 的位置
```

教师语义错误分类沿用：

- `missing_context`
- `semantic`
- `schema-owner`
- `grounding`
- `action-space`
- `safety-stop`

真实执行另行记录 `unexpected_landing / app_disappeared / environment_failure`，不能误写为 grounding。

本轮已转化的实例：

| 现象 | 根因 | 应进入 harness 的修法 |
|---|---|---|
| 弹窗后背景 RegionState 暴增 | 把 dimming 当功能变化 | 前景层关系，背景 identity 不变 |
| Never 同时归属菜单和 Diagnostics | 自由文本 owner 漂移 | framework-owned `co/o` 与 owner 校验 |
| Mail no-effect 后立即重试 | 没有逻辑操作终态 | no-effect terminal + immediate-repeat gate |
| 每个 Timer 数值都执行 | 把参数实例当新操作 | 参数域/同质代表组 |
| pending 恢复后重复结算 | 中断状态不唯一 | 单一 pending ref，一次结算后立即清除 |
| Sound 正确落点后应用消失 | 环境或应用失败 | failed edge、app visibility recovery、partial gap |
| Prompt 越跑越长 | 全局图和历史重复投影 | 语义工作集、短 diff、稳定消息分层 |
| 每步都调用高层 Luna | 未消费已验证路线 | plan once + fresh-ground N + final verify |

## 7. 下一轮验收顺序

### 阶段 A：离线合同

1. 为独立 harness 加入 `r/rv/co/o`，Luna 不能分配 ID；
2. owner、unknown ref、背景 binding、重复 Operation、pending 和 finish 建立确定性测试；
3. 用保存截图覆盖弹窗、菜单、重复标签、长列表和 app-disappeared 负例；
4. 验证稳定 developer + 动态 user 消息的真实 cache telemetry。

这些是 schema/harness 证据，不是 live traversal。

### 阶段 B：Luna-only Clock

从干净环境启动，固定 Prompt/harness 后不再修改：

- 覆盖 World、Alarm、Stopwatch、Timer、菜单、选择器和滚动；
- 每个 canonical Operation 只有一个逻辑终态；
- 无错误 owner、未知 ref 和直接重复 no-effect；
- 路线至少完成一次 `1 planner + N grounder + 1 verifier` 的多步重放；
- 没有 pending/restore/gap 时才能闭合；
- 报告动作、调用、token、cached/write token、时间和费用。

### 阶段 C：Settings

重点验证：

- 侧栏共享 Region 和大量内容 Region 不重复；
- 菜单/选择器 owner；
- 长页面真正滚动到顶部、新内容、底部或同质停止；
- Sound/app-disappeared 不形成无限重试；
- 安全延期不会被伪装成已验证功能。

### 阶段 D：VS Code

重点验证：

- 密集同屏 Region 不一次生成不可管理的大任务集；
- Editor、Activity Bar、Side Bar、Panel、Command Palette、Settings 等语义工作集可嵌套投影；
- 共享外壳不复制 Operation；
- 外部窗口、通知和系统弹窗不会污染目标应用图。

### 阶段 E：移动 Clock 回归

重点补齐当前 49 个 gap 和 Settings 长页面滚动；移动端整屏 Page macro 保留，但底层仍用
RegionState/Event 和 stable Operation ref。只有连续滚动和操作闭合后才可称完整遍历。

## 8. 成功标准与不允许的结论

最小可行性成功需要：

- 无 Codex 在线纠错的 Luna-only live run；
- Prompt/harness 在运行前固定；
- stable ref/owner 合同无未处理违规；
- Operation、scroll、pending、restore 和 gap 闭合；
- 每个动作都有 fresh before/action/after 和实际落地；
- 多步编译路线至少一次成功运行；
- 成本与错误指标可从 API/runtime 日志复算。

在此之前不能声称：

- Region 图已经优于 PageState 图；
- Clock 单应用 pilot 证明多应用完整遍历；
- saved-frame 2/2 证明 live owner 正确；
- graph/bundle 编译成功等于真实功能覆盖；
- `tasks=0`、`frontier empty` 或 Luna 自报 finish 等于框架完成；
- 缓存命中增加必然降低总费用或提高探索质量。

## 9. 证据与代码入口

- 全局目标：`design/RESEARCH_GOAL.md`
- 当前主框架：`design/CURRENT_FRAMEWORK.md`
- Region pilot 总结：`artifacts/region_reachability_pilot_20260827/analysis.md`
- 交互图查看器：`artifacts/region_reachability_pilot_20260827/viewer.html`
- 规范化 Clock 图：`artifacts/region_reachability_pilot_20260827/clock/region_graph.normalized.json`
- 规范化 Settings 图：`artifacts/region_reachability_pilot_20260827/settings/region_graph.normalized.json`
- 稳定 ref 探针：`artifacts/region_reachability_pilot_20260827/stable_ref_probe.json`
- 缓存分段探针：`artifacts/region_reachability_pilot_20260827/cache_prefix_probe.json`
- Clock 前景弹窗案例：`artifacts/region_reachability_pilot_20260827/clock/action_attempts/attempt_0007/after.png`
- Settings 菜单 owner 案例：`artifacts/region_reachability_pilot_20260827/settings/action_attempts/attempt_0142/after.png`
- Settings Sound 失败案例：`artifacts/region_reachability_pilot_20260827/settings/action_attempts/attempt_0120/before.png`
  和 `artifacts/region_reachability_pilot_20260827/settings/action_attempts/attempt_0120/after.png`

相关本地提交：

- `f59336d1`：记录 Region reachability pilot 证据；
- `0afd34bc`：记录稳定 ref 与缓存探针证据。

`artifacts/` 被 Git 忽略，上述 live-run 路径只存在于当前工作区。新任务不得把它们描述成
跨 clone 的正式数据集；需要共享时应另行打包明确的派生证据，而不是上传整个运行根。

## 10. 给新任务的建议起始语

> 请先读取 `design/RESEARCH_GOAL.md` 和 `design/LUNA_REGION_HARNESS_DESIGN.md`。继续独立
> Luna harness 研究，不修改主框架目标。第一步为独立 harness 接入 framework-owned
> `r/rv/co/o` 和稳定 developer/dynamic user 消息分层，先做离线合同与保存截图验证；不要
> 启动完整遍历。完成后说明证据边界，再等待我决定是否开始 Luna-only Clock live run。

## 11. 2026-08-28 独立 harness 的最小实现与 teacher-student 试跑

新增的 `tools/luna_region_harness.py` 是独立研究工具，不导入或修改主框架的
`ExplorationRuntime`。它当前实现了：framework-shaped `r/rv/co/o/a/e` 分配；Luna 的
ref-only 已知选择和无编号新候选；owner、精确 pending、no-effect、前景安全和 false-finish
确定性门；稳定 developer/ref workset 与动态 user screenshot/before-after 的消息分层；fresh
grounder；controller-owned before/action/after；以及 Prompt/retrieval/gate/grounder 归因日志。
`back/wait` 不经 Grounder，符合主框架的无坐标动作合同。`tests/test_luna_region_harness.py`
覆盖 ref/owner、pending、候选分配、消息分层、路线帧新鲜性、teacher evidence、false-finish、
safety defer 与 Back 的离线行为。

该版本仍只是 Phase-A protocol harness：它的 `luna_region_harness_graph.v1` 保存稳定 ref 和
局部证据，尚未生成或编译正式 `modular_exploration.v4` bundle；也尚未接入完整 RegionEvent
多跳编译路线。不得把它写成主框架已迁移或正式图产物已兼容。

一次实际 `gpt-5.6-luna` teacher-student Clock 开发试跑使用了独立 controller，运行前后均无
Codex/Luna-only 混淆：Luna 首次把 `status=new` 的必填 `region_ref` 写成 `"unknown"`，harness
拒绝并回传“新候选必须空 ref”的最小修正；随后它真实打开 application menu，before/action/after
由 controller 保存。试跑还暴露并转化了三项规则：同轮精确结算 pending 后可计划下一动作；
false finish 必须回退继续；安全拒绝应 defer 当前 `oN` 并继续其他 binding。一个 8-action 段以
前景菜单中的 Back 被错误送去 Grounder 而 `partial/grounding_replan_budget` 结束；修复后，最终
1-action 段验证 Back 直接执行并在局部已登记图上得到 `complete/gaps=[]`。所有这些 run 都是
`teacher_student_live_pilot`，不是 Luna-only 验收、完整 Clock 遍历或成本结论；controller 已关闭
且 Ubuntu0 VM 已释放。
