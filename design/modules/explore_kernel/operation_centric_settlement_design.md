# Operation-centered settlement and Region memory design

状态：2026-08-28 已接入主框架并通过本地聚焦测试；提交 `d69a7d99` 在 js1 完成
Codex 监督的 fresh Luna Clock live acceptance：`complete/gaps=[]/bundle=compiled`。固定合同的
无监督 Luna-only acceptance 仍是独立未完成证据。

## 目标

把持久完成真值收敛到当前 Variant 中的 Element/Region Operation。Luna 只报告：

1. 哪些 Element/Region 动作从 before/after 看已经完成；
2. 新发现的 Region、Element 和可执行动作；
3. 当前区块的功能情况、参数值域、代表参数及仍缺的信息，用简短自然语言 Region memory 表达。

框架根据登记时的 `(source Variant, owner ref, action kind, direction)` 唯一映射本地
Operation，自动更新 Operation/Task、Attempt、Transition 和 completion。Luna 不输出
`task_result`、`current_task_result`、`satisfied_operation_refs` 或 `purpose=route`。

## 最小模型接口

首次或增量清点仍使用现有 `page_report`，由框架分配 Page/Region/Variant/Element/Operation ID。
每个 Region 另带一段 `memory`：只概括已接受的界面事实、参数、代表行为、已验证内容和 gap；
它供后续 Luna/context/task proposal 检索，不授权动作或 Capability。

动作请求使用当前页面回显中的 owner：

```json
{
  "kind": "click",
  "owner_ref": "el12",
  "target": "Alarms 标签",
  "point_1000": [480, 60]
}
```

- 非空 `owner_ref` 必须在当前 Variant 唯一找到动作类型和方向一致的本地 Operation；框架在执行前
  把其 `operation_ref` 写入 ActionAttempt。
- Region scroll 使用当前 Region ref 作为 owner；Element scroll 非法。
- 调查滚动绑定 RegionOperation；只有非滚动 recovery/back/wait 使用空 owner，不完成 Operation。
- `route` 仅保留为框架内部 StateGraph 规划概念，不属于 Luna 动作 Schema，也不阻止已绑定
  Operation 结算。

待结算回复：

```json
{
  "attempt_ref": "a17",
  "element_actions": [
    {"element_ref": "el12", "action": "click", "completed": true}
  ],
  "region_actions": [],
  "function_info": [
    {
      "region_ref": "r8",
      "memory": "Alarm Editor 可设置时间、重复规则、标签、铃声和持续时间。Ring Duration 可见值为 1、2、3、5、10 分钟；5 分钟代表选择未显露新 Region。"
    }
  ],
  "reason": "Alarms 已选中并出现 Alarm 页面。"
}
```

框架只接受当前待结算 Attempt。已完成动作必须能在来源 Variant 的 owner/action/direction 中唯一
映射，且主动作实际 primitive 与登记操作一致；候选外 owner、动作类型冲突或歧义 fail closed。
主动作映射成功即自动把对应本地 Operation 标为 verified、关闭派生 Task，并按现有 canonical
身份关闭其他重复 binding。其他 `completed=true` 项只在同一 before/after 直接支持、且能唯一映射
已登记 Operation 时顺手结算。

若派发 Timer owner/action，但 Luna 只报告 Menu owner/action 完成，Timer Operation 保持开放；
已登记 Menu Operation 可由同一次 Attempt 完成，否则 Page/Region 增量先登记实际新表面。框架保存
原始 Attempt，不用 Luna 的自然语言 memory 改写 owner 或 action 真值。

## 参数与代表探索

参数值不是独立 Operation。选择器入口是一个 Operation；Luna 在 Region memory 中记录截图可见值并
选择一个同质代表。代表选择只检查是否显露新 Region/新控件/不同操作集合：没有则完成入口探索；
`Custom...` 等明显不同分支各允许一个代表。框架不逐值生成 Task 或执行计划。

## Semantic Exploration Focus

原设计中的可嵌套语义子图统一称为 Semantic Exploration Focus。Focus 替代 model-facing 的
长期 ExplorationTask：它只给 Luna 一个自然语言高层目标，并投影当前范围相关的全局 Page、Region、
Operation、Region memory 和短历史。例如：

```text
Clock
└─ Alarm
   ├─ Alarm List
   ├─ Alarm Editor
   │  ├─ Repeat selector
   │  └─ Ring Duration selector
   └─ Alarm Detail
```

Focus 是 scheduler/context projection，不是第二张图：不重新分配 ID，不复制 Operation、Attempt、
Transition 或证据；共享导航 Region 可被多个 Focus 引用，跨 Focus 关系仍只写全局图。Luna 可在真实动作
显露独立功能表面时提出子 Focus，框架只在新 Page/Region 已接受且属于父语义范围时建立引用。子 Focus
完成后自然语言 memory 折叠到父 Focus。

第一版只实现当前 Focus 的自然语言目标和 Region memory 投影，不新增持久任务类型；现有 Task 暂时保留为
框架内部调度 binding，并完全由 Operation 状态派生。Focus completion 由无 pending、范围内 Region 已清点、
Operation 已终态、子 Focus 已闭合或形成明确 gap 推导，Luna 不报告 Focus/Task 完成。

## 后续指令生成边界

Region memory 与 App overview 只帮助 LLM理解和检索。前置条件、业务 effect、对象 binding、recipe
与 success predicate 仍由真实 Attempt/effect observation 离线 induction 后写入现有 Capability Graph。
任务生成 LLM只看到按目标投影的简短自然语言功能概览；框架仍用完整 Capability Graph 批准组合，M13
只消费已批准计划并在 fresh screenshot 上重新 grounding、执行和验证。

## 成功标准

1. [x] 旧 `route` 点击改为 owner/action 直接映射并关闭对应导航 Operation；
2. [x] Luna 不再输出或决定 Task 完成；
3. [x] 错误落点不关闭派发 Operation，可完成实际命中的已登记动作；
4. [x] 参数值域只保存可见值和代表行为，不逐值建立 Operation；
5. [x] Region memory 可随新增事实更新，但不能授权图中不存在的 Operation；
6. [x] 当前 Focus 可投影 Page/Region/目标与 Region memory，而全局 ID 和证据保持唯一；
7. [x] 新鲜 Desktop Clock Luna API run 得到 `complete/gaps=[]/bundle=compiled`：24 动作、48 次
   主 Agent、15 次 Page Resolver、9 次 Region Reviewer；证据明确标为 Codex supervised。
