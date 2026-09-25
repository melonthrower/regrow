# Region 业务能力生成与采集设计

日期：2026-08-26

## 目标

利用已经完成的遍历图离线生成用户有意义的业务能力，再组合成单应用采集任务。
遍历仍以按钮级 Operation 完成功能发现和路由建图；按钮不直接成为下游任务。

## 不做

- 不保留 `skeleton/skNNN` 任务层。
- 不从探索历史剪一条固定的“完美轨迹”。
- 不要求业务能力预先包含严格有序 recipe。
- 不在任务设计阶段计算图距离或执行顺序。
- 本阶段不做跨应用组合。

## 三层职责

### 遍历图

保存 Page、State、canonical Region、Region occurrence、Button/Operation、真实 Attempt
和有向 Transition。按钮级任务只服务遍历调度、去重、证据和后续路由。

### 能力图

离线按 canonical Region 及其局部连接归纳高级子任务。一个能力归属于能启动它的
owner Region，但执行过程可以经过其他 Region、State 或 Page。

能力记录只保留有消费者的内容：

- `capability_id/name`：任务设计和执行反馈使用；
- `owner_region_ref/entry_bindings`：实机定位能力入口；
- `operation_refs`：给采集 Agent 提供已知可执行操作，不表示固定顺序；
- `parameters`：生成具体指令并在实机绑定；
- `inputs`：能力需要操作的业务对象；组合器用它匹配上游输出，执行器用它限制目标 Region；
- `outputs`：能力产生或显露的业务对象；执行器在成功落点绑定真实 State/Region；
- `expected_result`：完成验证；
- `missing`：告诉采集 Agent 当前还需要补什么；空数组表示当前信息已闭合；
- `evidence_refs`：人工审计和后续更新。

不增加独立 `complete/incomplete` 状态字段；是否缺信息由 `missing` 直接表达。

### 任务设计

框架从同一应用的能力目录中选择 2–4 个能力和具体参数。选择只考虑覆盖、显式依赖、
效果冲突和参数可用性，不考虑路由成本。无依赖能力不规定执行顺序。

具体参数只能来自能力中已有的观察值/允许值，或数据集明确提供的开放文本 fixture；任务润色
LLM 不能自行发明参数。执行信息不完整不阻止组合，但缺少任何可用参数来源时不能生成具体指令。

LLM 只接收已经选定的能力摘要和参数，并润色自然指令；它不能增加、删除、替换能力或
修改参数。最终任务保存 capability refs、参数和必要依赖，不保存骨架对象。

若一个能力的 `outputs` 与另一个能力的 `inputs` 类型匹配，框架可以建立对象依赖：消费者
`depends_on` 生产者，并把消费者的对象输入绑定到生产者输出。对象依赖决定执行顺序；单纯
Region 相邻或页面相邻不能建立能力关系。

## 离线 Region 能力归纳

每次模型调用只处理一个 owner Region 的局部功能图，不输入整个应用，也默认不输入截图。
输入包括：

- Region 名称、描述和出现的 Page/State；
- 该 Region 的 canonical Operations；
- Operation 直接显露或到达的 State、Region 和已知结果；
- 局部子 Region 的 Operation 摘要；
- 已有能力候选，供增量补充和去重。

归纳器输出高级能力候选及其真实 Region/Operation 引用。框架拒绝不存在、跨应用或不属于
局部功能图的引用。模型可以留下 `missing`，不能用自然语言补造 UI 事实。

共享 Region 只归纳一次能力；不同 State 中的 occurrence 形成多个 `entry_bindings`。
未执行的浅显 Operation 可以支持候选能力，但必须保留相应缺口，实际效果由采集阶段确认。

## 实机采集

1. 识别实机当前 Page/State。
2. 从依赖已满足且尚未完成的 capability refs 中选择最近的可达入口。
3. 使用有向遍历图最短路径路由到 owner Region；路径成本只在此阶段计算。
4. 把当前能力目标、参数、已知 Operation 和 `missing` 交给采集 Agent。
5. Agent 根据实时截图选择操作；每个动作后重新识别 State，并继续绑定当前
   `capability_ref`。
6. 生产者能力成功时，把新出现或明确变化的 Result Region 保存为其 `outputs` 绑定；消费者
   只在该绑定 Region 内定位目标 Operation。
7. `expected_result` 成立时完成该能力；否则记录失败位置和新发现，继续其他独立能力。

完整和不完整能力使用同一执行流程。一条任务可以包含多个不完整能力，因为每次动作和失败
都绑定当前 `capability_ref`。任务可能最终为 partial，但新发现仍进入相应能力的证据。

## 采集反馈与图更新

原始完成遍历图保持只读。采集发现的新 State、Region、Operation 和 Transition 写入同 schema
的增强图，并标明 collection provenance；成功结果、参数和缺口更新进入派生能力图。后续采集
可以使用最新增强图，但原始 run 仍可独立复核。

成功采集同时产出训练轨迹和能力补全；未完成采集只保留真实的新事实与明确缺口，不把预测写成
已观察结果。

## Clock 验收例

### 创建闹钟

当前图应离线归纳出：

- owner：`r4 Main Content Area`；
- entry：`o12 Add Alarm button`；
- 已知参数操作：`r42/o105-o108` 时间、`r43/o109` 重复、`r44/o110` 名称、
  `r45/o111-o112` duration；
- 提交：`r41/o104 Add button`；
- 期望结果：到达 `s18`，出现 `r46 Alarm List Item`。

### 添加世界时钟

当前保留图只能归纳不完整候选：

- owner：`r2 Main Content Area`；
- entry：`o6 Add World Clock button`；
- 已知落点：`s20`，含 `r54/r55`；
- missing：城市文本输入、结果选择、成功 Add 和城市卡片结果。

`city=Tokyo` 可由数据集的开放文本 fixture 提供，不要求它已在探索图中出现；采集结果再决定
该值在当前应用状态下是否可执行。

该候选仍可进入任务设计。采集成功后补齐 Operation 和结果；失败时保留当前能力引用下的新增
事实和缺口。

### 创建后停用闹钟

离线归纳应建立两个业务能力：

- `创建闹钟`：`outputs.alarm_item`；`o104` 的 `s17 -> s18` 落点新增 `r46`，作为实际输出绑定；
- `设置闹钟启用状态`：`inputs.target_alarm`，参数 `enabled`，在目标闹钟 Region 内使用 `o113`。

组合器将 `target_alarm` 绑定到前者的 `alarm_item`，并建立后者依赖前者。自然指令可以是：
“创建一个工作日上午 8:30 的闹钟，再将刚创建的闹钟停用。”其中“定位刚创建的闹钟”属于
对象绑定/grounding，“检查最终状态”属于结果验证，二者不另建业务能力。

## 当前实现边界

当前保存的 `capability_graph.json` 仍主要是按钮级 capability；尚无按 Region 局部功能图生成
上述业务能力的离线归纳器。M13 已支持 capability `depends_on`，也支持一个动态 recipe 内通过
`bind_result` 把新增 Region 交给后续步骤，但还没有跨 capability refs 的 `inputs/outputs` 绑定。
因此本文件描述的是已确认设计，不是当前运行时已通过声明。

## 首轮完成标准

- 删除任务设计中的 skeleton 概念和 `skNNN/start` 合同；
- 用保存的 Clock 图离线生成“创建闹钟”和“添加世界时钟”，前者闭合、后者带缺口；
- 指令润色器只接收框架选定的 capability refs 和参数；
- 从 Clock 图生成“创建闹钟 -> 停用刚创建闹钟”的对象依赖，并在离线合同中把消费者目标
  限制到生产者输出的 `r46`；
- 不完整能力能进入采集准备，且启动前不再因缺少完整 recipe/predicate 被统一拒绝；
- 离线测试明确区分图结构验证、模型归纳和真实 VM/Luna 验收，不能互相替代。
