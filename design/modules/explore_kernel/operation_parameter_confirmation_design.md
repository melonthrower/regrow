# Operation 参数确认合同

最后更新：2026-09-02

## 目标

每个新登记的 Operation 都必须显式说明参数是否已经确认。参数确认不等于逐项执行：
无参数操作可由 Luna 直接依据当前截图确认；当前截图已显示参数形式、当前值或至少一个代表值时也可直接确认；
只有连参数形式和代表值都隐藏在选择器或后续应用内表面时，才执行一次现有 Operation 以取得参数证据。

该合同修复当前软 Prompt 的缺口：`Region.memory` 虽要求总结可见值域，但 `recorded`
Operation 可以在参数仍未知时直接成为终态，completion 也无法确定参数是否遗漏。

## 最小数据合同

每个 Variant-local `Operation` 新增三个正向持久字段：

```text
parameter_status = unknown | none | observed
parameter_summary = 非空自然语言
parameter_evidence_refs = 已接受确认所依据的截图引用
```

- `unknown`：当前只看见含义不清的控件，参数形式和代表值都无法确认；summary 写明缺什么。
- `none`：已从截图确认该 Operation 没有调用参数；summary 固定为简短的“无参数”说明。
- `observed`：已确认参数形态、当前值或至少一个代表值；完整范围、步长或长度限制未知可写进 summary，
  但第一版不新增参数类型枚举或 Parameter 对象。

参数状态属于本地 Operation 证据。Completion 和 bundle 按既有 CanonicalOperation
聚合：任一合法 binding 已 `none/observed`，即可满足该 canonical 功能的参数确认；
不同 Variant 的原始字段和 evidence 仍保留，不伪装成每个 Variant 都被观察。

## Agent 输出

`page_report` 中每条 ElementOperation/RegionOperation 必填 `parameter_status` 和
`parameter_summary`。框架自动把接受清单的当前截图加入 `parameter_evidence_refs`
（仅限 `none/observed`）。参数值不是独立 Operation；同质选项仍只记一个代表。

待结算动作的 `previous_action` 新增：

```json
"parameter_info": {
  "status": "observed",
  "summary": "可选 Control volume、Snooze、Dismiss；未逐项执行"
}
```

或 `null`。模型不提交 Operation/Task ID；框架把非空 `parameter_info` 绑定到本轮
completed owner 唯一解析出的 Operation，并把 after screenshot 作为证据。

## 调度与结算

- `none/observed + handling=record`：直接 `recorded`，不执行。
- `none/observed + handling=explore`：沿用现有功能探索 Task。
- `unknown + handling=explore`：Operation 保持 `pending`，复用现有
  `explore_operation` Task；不新增参数 Task 类型。
- `unknown + handling=record`：保持 `recorded`、不授权执行，但 v5 completion 保留
  `parameter_unknown` gap。安全选择器应由 Luna 显式标为 `explore`；危险、外部或不可逆
  操作不能借参数确认扩大动作授权。
- `unknown + handling=defer`：保持 `deferred`，前置恢复后仍须确认。
- 真实 completed owner 对应的 Operation 仍为 `unknown` 时，`parameter_info` 必须为
  `none` 或 `observed`；缺失时拒绝结算，同一 ActionAttempt 保持 pending，Luna 只需
  根据已有 before/after 修正回复，不重复 GUI 动作。
- 已确认参数可重复报告相同结论；局部 `none` 与 `observed` 并存时保留审计标记，不改写原报告。
- 同一 local Operation 的新清单若把已存 `none` 改报 `observed` 或反向改报，inventory不覆盖旧证据，
  也不再抛出未捕获异常。它返回具体 Region/Element/Operation、旧摘要/证据和新摘要，由 runtime保存
  同轮已完成动作后交给 Luna纠正；当前版本没有授权 Luna直接重写旧参数真值。

## Completion 与投影

新运行使用 `modular_exploration.v6`。v3/v4/v5 账本仍可只读加载并保留原 schema；
其历史 Operation 缺字段时按 `unknown` 显示，但不为未执行的旧 binding 追溯生成参数 gap。
新 v5/v6 逻辑 Operation 若全部 binding 都为 `unknown`，completion 增加
`parameter_unknown` gap；不得以 `recorded` 或任务队列为空关闭。
同一 CanonicalOperation 的 binding 若同时出现 `none` 与 `observed`，bundle 保留
`parameter_conflict=true` 供审计；任一可靠 `observed` 已满足逻辑参数覆盖，因此不形成 completion gap。

`current_page_record`、pending card、`modular_entries.json` 和 Region/Entry 上下文显示
参数状态、summary 和证据引用。Capability induction 仍只把真实 ActionAttempt 中出现的
结构化 action 参数当作可执行参数绑定；自然语言参数域是后续指令生成的候选上下文，
不冒充 formal parameter domain 或成功谓词。

## 非目标

- 不逐个执行 enum 值，不枚举连续滑块的所有数值。
- 不新增 Parameter、ParameterTask、子图或应用专用规则。
- 不回写旧 run，不把 saved-frame/offline 验证冒充 live acceptance。
- 不改变 Capability 组合、M13、目标先行任务生成或 cleanup 合同。

## 验收

离线合同至少证明：必填字段解析、explore-only unknown 派发、record unknown 安全 gap、截图直认 none/observed、pending
参数结算、冲突拒绝、canonical 参数 gap、旧账本只读兼容和 bundle 投影。随后使用固定
Prompt 在独立 Android Clock 上运行 Codex-supervised Luna API pilot，单独报告参数覆盖、
真实动作、重复动作、gap、token/cache 和 bundle；它不替代最终无监督 Luna-only acceptance。
