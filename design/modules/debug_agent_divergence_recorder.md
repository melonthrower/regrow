# Debug Agent — 遍历背离记录器 (Traversal Divergence Recorder)

**状态**: **已实现 (2026-07-06, TDD, 6 组单测全绿)**。设计经用户 grill 逐条拍板。
待真机 foldcheck7 验证。
**定位**: 把现有 log-only 的 AnnotationReviewer / ReviewDebugSink 升级成一个**只读诊断仪** ——
精确捕捉"当前探索与预期不符"的点, 结构化落盘供分析脚本 + 人排查。**不改遍历控制流。**
env flag `GUIWALK_REVIEW_DEBUG=1` 开启, 不开则全程 no-op(生产默认)。

## 为什么要它 (动机)

foldcheck6 (2026-07-06) 修好 mis-click 后**仍 4 节点早停**: 主页 37 元素里 **22 个侧栏
navigation 项**被 `_unvisited_candidates` 的 shared-全局-dedup 判成已探→前沿宣告 empty→侧栏
一个没探。**光看图/日志查不出**: 图存的 `visited=False` 是注册时快照, 内存里后来被改成 True 不
回存。→ 需要**运行时**把"谁因什么被丢/哪个动作不对"落盘。这就是本 agent。

## 记录什么 (背离分类)

两种记录类型: **逐节点 snapshot** + **逐动作 event**。

### A. 节点可探元素异常 (snapshot)

- **提早筛选 / 候选丢弃分解**: 每次 `_unvisited_candidates(state_id)` 被调用时拍一张 —— 该
  节点各元素**因什么被丢**(`visited / 通用名 / shared全局已探 / group折叠 / dangerous`)、
  每个被丢元素名字+理由、**还剩几个可探**。分析脚本按节点取最后一张(或 diff 相邻两张看谁被划掉)。
  → foldcheck6 那个 bug 会直接显示成 "root: 22 个 navigation 被 shared-全局-dedup 丢"。
- **识别失败**: 复用 AnnotationReviewer 的 `wrong / missing / duplicate`(已逐节点记录)。

### B. 探索动作异常 (event)

**已算, 只接线**(引擎已检测, 只需 `record_event`):
- `retarget_rejected` —— 点飞被出区块守卫拦(已接 ✓)
- `quarantine` —— 点击时发现当前帧其实是别的已知页, 边被丢(engine `pre_click_id != current_id`)
- `off_app_click` —— 点击后掉出 app / 触发 relaunch
- `backtrack_false_arrival` —— 回溯自称成功却落在兄弟页(`landed_id != nxt`)
- `backtrack_fail` —— 回溯失败累计 / hard-reset mismatch

**新增轻检测**(阈值可调常量, fail-open):
- `repeated_scroll` —— 某区块滚了 N 步却 0 新名字(`_regional_scroll_dedup` 有 steps/new_names)
- `nondeterministic_edge` —— 同一 `(源节点, 按钮名)` 两次点落到不同 dst id

### C. 点击语义核验 (event, 新 VLM 角色)

抓**几何守卫的盲区**: 点 Network 落到 Bluetooth —— 相邻侧栏行, 都在侧栏区块内, 出不了区块→
`retarget_rejected` 抓不到。需**动作感知的语义判断**。

- **第 1 层 · 中立记录(每次点击, 不调 VLM)**: 记 `(源页, 点的元素名, 落地页id, 落地页标题)`。
  "名字=Network / 落地标题=Bluetooth" 一眼露馅, 分析层看出。
- **第 2 层 · `ClickEffectVerifier`(新只读 VLM 角色, debug 模式)**: 吃 `前图 + 在其上点了哪个
  按钮 + 后图`, 出三分类:
  - `no_change` —— 动作没生效, 还在同一页(点空/死点)
  - `transitioned_consistent` —— 跳到新页, 且和"点这个按钮该得到什么"一致
  - `transitioned_inconsistent` —— 跳到了别的页(点偏)
  - prompt 借采集侧 `tools/trajectory_qc.py` 的 `transition_plausible` 判法(已验证)。
  - **`no_change` 子判断委托给 PageIdentityJudge**(复用 same-page 本事, 不重写)。

## 架构 / 组件边界

- **`ReviewDebugSink`**(已建, 扩展): JSONL 落盘器。方法 `record_node` / `record_event` /
  `close`。`path=None` → no-op。UTF-8 `ensure_ascii=False`(中文不糊)。best-effort 不抛进 BFS。
- **`_unvisited_candidates` 就地插桩**(engine): 每个 `continue` 前收集 `(name, reason)` → 交
  sink。**单一真相源**: 记录的理由 = 引擎实际用的理由, 永不漂移。只在 sink 开启时收集。
- **`ClickEffectVerifier`**(新, visual_agents.py): 只读 VLM 角色, 内部调 PageIdentityJudge 做
  no_change 子判断。
- **`analyze_review_debug.py`**(已建, 扩展): 读 JSONL 出一屏"本轮健康报告" —— 节点数 / 早停
  原因 / 各节点候选丢弃分解 / 动作异常 / 点击核验裁决。

## 不做 (out of scope, 明确划走)

- **在线拦截 / 自纠**: 本 agent 只读只记, 不当场丢边/重试/补滚。将来验证核验准了再议(那就不只是
  debug agent)。
- **review consumption(补标)+ reviewer 收窗**: 另一条线(改善 grounding 覆盖), 与本 agent 不同
  件事。收窗 = 给 reviewer 的 SoM 改用过滤后 in-window 的 kept 集重画。
- **替代 PageIdentityJudge**: 查证否决 —— 它管路径无关的去重(核心难点), ClickEffectVerifier 的
  三元组喂不进去重场景, 不能替代; 只复用其 same-page 子能力。
- **前沿策略改 BFS**: 独立议题(见 memory), 不在本 agent 范围。

## 测试

- `ReviewDebugSink`: 已有 `tools/test_review_debug_sink.py`(10 用例, 含 unicode/no-op)。
- 候选丢弃分解: 纯函数, 造 mock 节点 + 各类被丢元素, 断言分解计数正确(离线, 无 VM/无 key)。
- `nondeterministic_edge` / `repeated_scroll`: 纯逻辑, 造边/滚动序列离线测。
- `ClickEffectVerifier`: 离线测解析(mock VLM 返回三分类 JSON → 断言归类); 语义准确性用 network
  节点存档帧(screenshot/som)人工抽验。

## 验收 (下一轮 foldcheck)

跑一轮开 `GUIWALK_REVIEW_DEBUG=1`, `analyze_review_debug.py` 一屏应显示:
1. 早停时**哪些节点还剩几个可探**、被丢的走了哪条理由(定位 22-侧栏 bug 类问题);
2. 每次点偏(`transitioned_inconsistent`)+ 死点(`no_change`)+ 重复滚动 + 非确定边逐条可查;
3. 回溯异常逐条带节点上下文。

## 实现落点 (2026-07-06)

- `visual_agents.py`: `ReviewDebugSink.record_candidate_breakdown` /
  `classify_edge_consistency` / `classify_scroll_waste` / `ClickEffectVerifier`.
- `visual_engine.py`: `_unvisited_candidates` 就地插桩(`_drop` 收集)+ 各异常点
  `record_event`(backtrack_false_arrival / off_app_click / quarantine_edge /
  nondeterministic_edge / repeated_scroll / click_effect)+ `click_verifier` 初始化 +
  pre-click 截图捕获。
- `tools/analyze_review_debug.py`: 一屏健康报告(候选分解 / 点击核验 / 各类动作异常)。
- 单测(离线, 无 VM/无 key): `test_review_debug_sink`(10) / `test_candidate_breakdown`(13) /
  `test_edge_consistency`(7) / `test_scroll_waste`(5) / `test_click_effect_verifier`(9) /
  `test_region_click_guard`(6)。

## 修改历史

- 2026-07-06 立(小克): grill 逐条定稿。Q1 中立记录仪 / Q2 每次 `_unvisited_candidates` 拍 /
  Q3 就地插桩单一真相源 / Q4 动作异常两批 catalog / Q5-6 点击核验 debug-only 只读 /
  ClickEffectVerifier 三输入三分类, 复用 PageIdentityJudge 做 no_change、不替代它。
