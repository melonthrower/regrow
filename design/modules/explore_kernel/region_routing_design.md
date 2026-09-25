# Region 可见性关系与路由

2026-09-17：goal_reached与路径扩展排除deferred/failed/cancelled本地操作，避免“当前有同一canonical但此状态不适用”被当作到达。Task卡同时不发布deferred当前owner。Alarm用例保留已选中时的no_effect，通过已有World Clock适用绑定/路线，原生假环境导航→Alarm执行→结算成功；无可信路线则保持阻塞，不伪造导航边。

2026-09-09：已成功的准备/导航不因同Focus旧记录被禁止重做；完整路线尚不明确时可按当前合法绑定逐步探索。
每次仍用fresh截图投递、结算实际落点，不从未知或歧义路线继承结果；近重复无效果与任务预算仍受限。

## 2026-09-07 实机后的清单引用修正

新 State 中复用旧 Region 的报告，在身份审核前可能先取得临时 Region ID。
region_effects 现在使用本轮原始 region_ref 到已分配 ID 的临时映射，避免把保留的 r1 误判为 after 不可见。
同时填写 ref/index 时，只要两者指向同一清单对象就接受；不一致仍拒绝。disappeared 仍按 before ref 校验。
该映射不证明身份相同，后续 Region Reviewer 仍决定共享；没有新增模型字段。
Settings 中 Background 点击实际成功，但旧解析在该步骤拒绝了两份报告；本修正已有离线检查，尚未重跑该实机结算。

## 2026-09-07 同 Region 的功能状态变化

region_relations 从已有 region_effects_reported 事件提取 action/updated，按 regions_reused 事件解析已合并 ref。
只有前后均存在的稳定 Region 才作为 updated 关系，保留真实 Transition/Attempt 及前后 State。
派生路线可经此关系到达含新目标操作的状态，不把普通字段值更新制造成新 Region。
updated_region_refs 仅在派生关系/路线视图中出现，没有新增模型输出字段或持久模型字段。
按钮身份仍按功能职责判断；具体结果可依状态不同，不能为了继承入边强行合并页面。


最后更新：2026-09-05

状态：2026-09-02 已实现 Transition reveal/hide、Page Region并集、上下文相关 Region BFS、精确任务卡、`modular_region_routes.json`
和 Region-first resume 离线合同。resume 一律清空旧位置，不比较旧 State 截图或经过 Page/State Reviewer，而是由主 Agent 清点当前 Region、
Region Reviewer 全局复核后作为路线起点。已有保存帧与2026-09-05定点实机试跑，尚未通过完整恢复验收；风险见下文。先前 supervised Clock partial run
中出现40个 ready、34个 ambiguous 与23个 unreachable Region 路线输入，不是完整验收。

## 目标

路由目标从“到达某个已知 Page/State”提升为“到达目标 Region”。即使当前界面从未探索，
只要其中一个 Region 与它的当前本地 Operation 已有真实路线证据或明确的结果复用授权，框架也能从已验证关系中
选择下一跳；每一步仍基于 fresh screenshot 定位并验证真实落地。

## 唯一图真值

不新增第二份持久 Region 图。现有对象各自保存一种事实：

- `Page`：Region 的逻辑分组；同一全局 Region 可属于多个 Page；
- `PageState`：当前截图真正可见的 RegionOccurrence 集合；
- `Transition`：一次真实成功动作连接的来源/目标 State；
- `Operation`：动作所属 Region、Variant、Element 与 CanonicalOperation；
- `Transition.revealed_region_ids/hidden_region_ids`：这次动作后新出现/消失的全局 Region。

`RegionRoutingView` 只从上述事实编译，不分配新的 Region/Operation ID，不复制截图或证据。

## Page 与 State

`Page` 的 Region 集合是其全部已接受 State 中 RegionOccurrence 的并集，表示“逻辑上属于
这个 Page”，不保证每张截图都可见或可交互。`PageState` 的 occurrence 才是当前可见集合。
弹窗、滚动和遮挡只改变 State 可见集合；共享导航 Region 可以同时属于多个 Page。

## Region 可见性关系

成功 Transition 的 Region 关系为：

```text
source RegionVariant/local Operation
  -> revealed RegionVariant(s)
  -> hidden Region(s)
  -> target State
```

2026-09-06：前后 Region 集合差不再自动写为动作效果。主 Agent 在原 pending 回复的
`region_effects` 中列变化，使用 `appeared/disappeared/updated` 和 `action/external/uncertain`。
已知区块用 region_ref；当前清单新区块用从 0 开始的 report_index，框架在清单登记后解析为稳定 ref。
报告在原临时 ledger 中校验；失败沿用 pending 纠正，正式图不接收半份结果。

- 只有 action 原因的 appeared/disappeared 写入 Transition 已有的 revealed/hidden 字段。
- updated、external、uncertain 保留在既有 ledger.events 的 region_effects_reported 事件中；不制造导航边。
- refresh_transition_region_effects 只检查已有声明与可见集合的一致性，不从集合差补因果。
- 明确归为 external/uncertain 的区块不通过 Region Reviewer 补为动作效果；未报告的区块仍提供真实
  source_transition 和已有前后截图，由本次 Reviewer 判断是否显露。提供来源本身不创建因果边。
  缺少该字段的历史报告仍可走已有 Reviewer 显露判断，原始运行不回写。
- 相同组件的数据/参数更新用 updated 和 memory 表达，不按每个值建立全局 Region。

一次 Operation 可以显露或隐藏多个 Region。关系保存真实 `attempt_ref/source_state/target_state`
证据；失败或不确定 Attempt 不生成可路由关系。新报告只引用已实际登记的局部区块，不必等待整页所有内容清点完才保存观察。

## 上下文相关按钮

Region 路由边不能只用 `Region + click`。每条关系必须保留：

```text
source_region_ref
source_variant_ref
local_operation_ref
canonical_operation_ref
source_state_ref
target_state_ref
revealed_region_refs
hidden_region_refs
attempt_ref
```

例如同一主导航 Region：

```text
World Variant / Add World Clock -> 添加世界时钟 Region
Alarms Variant / Add Alarm      -> 新建闹钟 Region
Timer Variant / Add Timer       -> 新建计时器 Region
```

Operation 是否共享由完整截图中的功能对象、当前职责和直接效果决定，不按名称设置例外。跨 Variant
共享 canonical identity、Operation 的 verified 状态或唯一已观测 reveal/hide 签名都不单独授权落点复用。
没有当前 Variant 的直接证据时，还必须有已有 `variant_operation_result_reused` 记录，
直接将当前 Operation 的结果授权指向该真实 Transition 的源 Operation；两者仍须属于同一 Region 和 canonical。
即使已有 result 授权，同 canonical 的已观测效果签名冲突时仍返回 ambiguous，不猜测。

## 路由

输入为当前 State 的可见 occurrence 和目标 `region_ref`。若目标已可见则返回空路线。否则：

1. 枚举当前可见 Variant 的本地 Operation；
2. 查找同 Region、同 CanonicalOperation 的已验证 Region 关系；
3. 精确 Variant 优先；没有精确证据时，只允许复用效果签名唯一、且有当前本地 Operation 直接 result 授权的真实关系；
4. 第一跳可从新登记、此前未见的 State 发出；其后的目标 State 与 occurrence 来自真实证据；
5. BFS 以目标 Region 是否可见为完成条件，返回每跳的本地 owner、目标 Region 和证据；
6. runtime 把路线投影到任务卡，Luna仍在每张 fresh screenshot 中重新定位当前 owner；
7. 实际落地没有出现预期 Region、按钮不唯一或前景改变时，停止路线并重新规划。

Page 不作为路由节点，只提供候选 Region 分组与语义上下文。

## 已确认问题与当前修复边界

2026-09-05 固定 `e3ed04c1` 的 Settings 试验中，保存帧生成的路线为 Applications -> 返回 -> Network。
第二跳实际借用旧 a28：Privacy/Connectivity 的 o317 返回后确实出现 Network。旧 ev256 仅把
o317 与 Applications 的 o279 以 identity 级别共享。当时路由没有区分该授权与 result 共享，因同 co
只有一个已观测效果签名，便将 Privacy 的完整落点用于 Applications Variant。

本机人工控制的两次点击证明：从 Date & Time 搜索界面进入 Applications/Accerciser，再点击返回，
只恢复了 Settings 主导航，Applications 仍选中，右侧 Accerciser 内容保留，没有出现 Network。
这是与 Luna 自主试跑分开的因果检查；没有回滚原 VM 快照，结论限定为该计划在当前环境不成立。
原 a28 的截图和边本身正确，不应删除或改写；需要审查的是跨 Variant 的效果复用范围。

共享 Region、共享命令身份以及未观察到冲突，都不能单独证明某个具体落点可复用。2026-09-05 的修复
使用既有 result 复用事件限制跨 Variant 路线；原 a28 仍作为其真实来源 Variant 的有效边。
本次只保留 identity 不得借用落点、明确 result 授权仍可使用路线的关键回归；沿用已有冲突检查。
该修复尚未实机重跑，不代表完整恢复验收通过。原故障证据见
`artifacts/runs/settings_shared_route_live_e3ed04c1_20260905/` 的 controlled 图组、summary.json 与原 a28 图。

## 输出

正式模块化 bundle 增加派生文件 `modular_region_routes.json`：

- `page_region_groups`：Page 到全局 Region 的逻辑成员关系；
- `relations`：带 Variant/CanonicalOperation 条件和证据的 Region 可见性关系。

现有 `annotated_graph`、Capability、M13 和 cleanup 合同不改变。

## 验收

- World/Alarms/Timer 共用主导航 Region，但三个 Add 只能使用各自 Variant 与 CanonicalOperation；
- 从一个新 State 以明确 result 授权复用既有真实 canonical effect 时能得到第一跳；仅 identity 共享不得借用落点；
- canonical effect 冲突时新 Variant 不得到路线；
- 一个动作可同时 reveal/hide 多个 Region；
- Page 分组是 Region 并集，State 仍保留真实可见子集；
- ledger save/load、Region merge 和 bundle 保留所有关系；
- 现有 State Router、Task、Capability 与 owner settlement 聚焦测试保持通过。

## 2026-09-08 反馈检查

region_effects 错误指出数组行、ref/index矛盾及前后可见性，不将集合变化自动归因于动作。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。
