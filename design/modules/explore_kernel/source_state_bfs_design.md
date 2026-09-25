# 来源 State 优先的 BFS 探索与精确动作回执

最后更新：2026-09-01

状态：2026-09-01 已实现来源 BFS、Region-owned Operation与当前 binding投影、动作回执和非目标防重复，并通过离线聚焦回归与保存帧 Luna API探针；新鲜 live Clock验收待执行。

## 目标

模块化探索在首次离开一个仍有未完成 Operation 的来源 State 后，先清点新 State，再返回较早来源完成同层入口，避免深挖新表面后让旧入口消失。Luna 每轮看到稳定 Region/CanonicalOperation和当前可执行 Element/Region owner；Page/State只用于可见性和路线。

## 不新增的内容

- 不建立第二张持久 Operation 拓扑图；
- 不改变 Page、Region、Operation、Task、Attempt 或 Transition schema；
- 不让 Luna 自己填写实际 `operation_ref`；
- 不按应用名、按钮名、坐标或文本相似度判断等价；
- 不改变 Capability、M13、cleanup 或 Seed 合同。

## BFS 调度

复用 `Task.state_id`、`created_seq` 和 verified `Transition`：

1. 当前 State 的 `survey_page` 始终先完成；
2. 从当前 State 沿 Transition 反向求祖先 State；
3. 若 pending/deferred 候选中存在来源为当前或祖先 State 的任务，按 `created_seq` 选择最早任务；
4. 没有祖先 frontier 时，才沿用当前 verified 有向距离选择；
5. active Task 和同一 Region/CanonicalOperation 的当前可执行 binding 仍沿用现有规则。

因此入口探索为：

```text
s1: o1, o6
o1 -> s2
survey s2
返回 s1
执行 o6
s1 frontier 闭合后再深入 s2 的 Operation
```

第一次执行未知入口仍被允许；新 State 清点后，调度优先回到较早来源继续探索，但这只是选任务顺序，
不是禁止 Add/Save/Delete 的执行门。数据变化后的真实落地和返回路线照常记录。

## Region-owned Operation 与恢复拓扑

稳定 Operation 归属于 Region；不同 State 只提供当前可执行 owner binding：

```text
Region -> CanonicalOperation
current State -> Region occurrence -> current Element/Region owner
```

现有 local Operation、Variant和Occurrence仍由框架内部保存执行与证据，不迁移 schema，也不暴露成另一项
模型功能。相同 Region 在当前 State 若存在同一 CanonicalOperation 的唯一 binding，任务直接使用当前 owner；
没有 binding 才走 Region路线。不同标签页中作用对象不同的加号必须属于不同 CanonicalOperation，不能因外观合并。

Add/Save/Delete 等 Operation 可以正常执行，不按名称或预测风险预先阻止。若它使后续任务的精确
Region binding 不再可见，任务保持开放，Luna根据任务卡中的目标 Region与来源 State探索恢复：

- 使用当前可见 Back/Cancel/Delete/导航等 Operation；
- 每个恢复动作照常保存 Attempt和真实 Transition；
- 到达任一含目标 local binding 的 source State 后执行焦点 Operation；
- 无法恢复时保留 gap，不用相似 Operation反复替代。

因此探索拓扑不是 Operation先后约束，而是：

```text
Task -> Region-owned CanonicalOperation
current State -> verified/探索中的 Region Transition -> executable Region binding
```

后续高级目标的前置条件则由到达最终目标 Region所需的 Region链、Capability entry surface、recipe和
precondition组成。例如 `Alarm列表 Region -> Alarm编辑 Region -> Ring Duration选择器 Region`。
这属于现有 Capability/采集阶段，不反向变成在线 Operation排序规则。

## 精确任务卡和动作回执

动态上下文增加一个代码派生的精确任务卡：

- 当前 `task_ref`；
- 目标 `region_ref/operation_ref`，其中 Operation ref 为稳定 CanonicalOperation；
- 当前可执行 `element_ref/region_ref` owner；
- 当前 `page_ref/state_ref`；
- 全部精确来源 State；
- 当前没有 binding 时的来源 State和Region路线。

当前焦点最近动作改为 Attempt 回执：

- `attempt_ref`；
- 焦点稳定 `operation_ref`；
- 实际 `region_ref/element_ref` 与稳定 `operation_ref`；
- source/target State；
- outcome 和 visible result；
- 是否精确完成焦点。

Luna 仍只提交最新截图中的 `owner_ref`。框架解析后把本地 Operation写入Attempt；下一轮只向Luna回显其
Region-owned CanonicalOperation和实际 owner。

## 非目标 Operation 防重复

同一焦点内，若一个 `actual_operation_ref != focus_operation_ref` 已有一次真实 `success`，再次请求同一个实际 Operation 时，在执行前确定性拒绝，不允许靠换点位、绕一圈或重复进入同一表面规避。Luna必须：

- 返回焦点来源 State 执行精确 Operation；或
- 选择另一个尚未成功的准备/导航 Operation；或
- 如实让当前任务形成 gap。

框架不因为替代操作相似就结算焦点，也不新增模型侧 `task_result`。

## 验收

- 离开 s1 到 s2 并完成 s2 survey 后，较早的 s1 Operation 优先于 s2 新 Operation；
- 不相关且不可达的旧 State 不抢占当前可达任务；
- `o91` 在焦点 `o68` 中成功一次后，第二次执行 `o91` 被拒绝；
- 每张精确任务卡列出目标 Region-owned Operation、当前可执行 owner或必要来源 State；
- Add/Save 后目标 binding消失时，Luna能根据精确前置 refs探索恢复路线，不重复替代 Operation；
- Agent上下文对焦点和实际动作只显示稳定 Operation与当前 owner；
- 现有 current canonical binding、survey优先和 verified route测试保持通过；
- 新鲜桌面 Clock Luna run 不再出现同一焦点下 `o15` 或 `o91/o92` 多次成功执行。
