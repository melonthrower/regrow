# 采集轨迹质量审查报告 (检验子代理, 2026-06-28)

审查对象: 15 条桌面 (Ubuntu Settings) 采集轨迹
- `collections/OS/260623sc/setting/episodes/` — CAP001..CAP010 (10 条)
- `collections/OS/260623qwen/setting/episodes/` — L001 / L008 / L012 (3 条)
- `collections/OS/260623m2/setting/episodes/` — CAP001M (1 条, 失败样本)
- `collections/OS/260623m3/setting/episodes/` — CAP001M (1 条, 同指令成功样本, 对照组)

方法: 逐 episode 读 `trajectory.json` 拿动作序列, 再用 Read 工具人工查看 before/after PNG 截图, 像人一样判断每个动作是否朝目标推进。`annotation.had_effect=False`(动作未产生像素变化) 作为机器信号, 但每个判定都用截图人工复核(确认无效点击落在禁用按钮/空白区/越界坐标, 而非误判)。

---

## 1. 总记分板

冗余率 = (NOOP + WRONG + THRASH + REDUNDANT 步数) / 非终止动作步数。
终止步 (FINISHED / IMPOSSIBLE / WAIT) 不计入分母。

| episode | 总步 | GOOD | 坏动作(noop/wrong/thrash) | 终止 | 冗余率 | final_status |
|---|---|---|---|---|---|---|
| CAP001_36b04a02 | 14 | 2 | 10 | 2 | **83.3%** | impossible |
| CAP002_1ddf8795 | 12 | 6 | 5 | 1 | 45.5% | impossible |
| CAP003_83eea532 | 3 | 2 | 0 | 1 | 0.0% | complete |
| CAP004_9d40c2c6 | 6 | 3 | 2 | 1 | 40.0% | complete(*假成功) |
| CAP005_715ff9cc | 6 | 5 | 0 | 1 | 0.0% | complete |
| CAP006_1b39bb00 | 3 | 2 | 0 | 1 | 0.0% | complete |
| CAP007_d6ec6e68 | 9 | 3 | 5 | 1 | **62.5%** | complete(*疑) |
| CAP008_70740729 | 2 | 1 | 0 | 1 | 0.0% | complete |
| CAP009_fb376b4f | 7 | 1 | 5 | 1 | **83.3%** | impossible |
| CAP010_5a02353a | 5 | 2 | 2 | 1 | 50.0% | complete |
| L001_39b3d6cb | 4 | 3 | 0 | 1 | 0.0% | complete |
| L008_08d277fd | 3 | 1 | 1 | 1 | 50.0% | complete |
| L012_df7a0b78 | 5 | 1 | 3 | 1 | **75.0%** | incomplete |
| CAP001M_c81a51e5 | 14 | 4 | 9 | 1 | **69.2%** | impossible |
| CAP001M_3f08addd | 7 | 5 | 1 | 1 | 16.7% | complete(对照组) |

### 全局基线
- 非终止动作步合计: **84**
- 坏动作合计: **43**
- **全局冗余动作率 = 51.2%** (43/84)
- 总步数(含终止) = 100, 终止步 15

> 注: 此 51.2% 是保守下界。它只统计了 `had_effect=False` 的无效动作; 还有少量"有效但语义重复/震荡"的步(如 CAP001 s01 反向滚动撤销 s00、CAP002 s04/s05 重开同一对话框)按机器信号算成 GOOD, 实际是 REDUNDANT/THRASH。把这些算进去, 真实冗余率约 **55%+**。一半以上的动作是噪声。

---

## 2. 缺陷分类学 (taxonomy) — 5 个根因模式

### P1. 无效点击不换策略 (dead-click loop) — 占比最高
点了没反应 (`had_effect=False`) 后, 原地重发同一坐标 / 同一被禁用控件, 连点 5 次以上才放弃, 中途从不尝试别的元素或读"为什么没反应"的页面提示。

实例:
- **CAP009 s01-s05**: 连点 (1672,49) "Add Printer..." 按钮 5 次全无效。截图 step01.png 显示该按钮是**灰色禁用态**, 页面顶部明写 "Unlock to Add Printers" + 右侧有 "Unlock..." 按钮 (≈1857,100)。agent 从不点 Unlock, 也不点页面中央可用的 "Add a Printer..." (≈1116,634), 5 连点死按钮后判 impossible。
- **CAP002 s06-s10**: trash 已清空后, 仍连点 "Empty Trash..." (1131,661) 和已消失的对话框确认键 (1116,600) 共 5 次, 全 px=0 无效。
- **CAP001M s08-s12**: 越界坐标 (1302,745) 反复连点 5 次, 全 px=0。

### P2. 坐标空间 / 缩放错配 (off-by-2x grounding) — 移动端/小分辨率特有, 杀伤力最大
PNG 存成 1920x1080, 但 VM 实际渲染内容只占**左上 960x540 象限**(分辨率减半显示在大画布)。grounding 却按 1920x1080 出坐标, 导致控件目标点 (如 workspace 数量步进器、Multi-Monitor 单选) 被打到右下黑边死区。

实例 (用 PIL 确认 PNG=1920x1080, 但 step03 截图内容只到约 x<960):
- **CAP001M_c81a51e5 (m2, impossible) s03-s12**: "Number of Workspaces" 步进器实际在显示坐标 ≈(648,373), agent 反复点 (1298,745)/(1302,746) 越界死区, 9 步无效 → impossible。
- **CAP007 s02-s05**: 同一步进器, agent 点 (1296,744)/(1298,745) 越界, 4 连无效。
- **对照 CAP001M_3f08addd (m3, complete)**: 同指令同页面, 但有效点落在了页内 (s05 点 837,854 px=1177 生效), workspace 成功设为 3。**同一指令两次跑, 一次 14 步失败一次 7 步成功, 差异纯粹是 grounding 坐标这次落对了没** → 说明这是非确定性 grounding bug, 不是任务难度。

### P3. 滚到极限还反复滚 (scroll-at-extreme)
列表已在顶/底, 仍持续发滚动指令 (`had_effect=False`, px=0 或 260 抖动), 不切换到"该项可能不存在"的判断。

实例:
- **CAP001 s02-s12**: 找不存在的 "Appearance" 侧栏项。截图 step00.png 证实该 GNOME Settings 侧栏根本没有 Appearance (Network 已在顶部, A-Z 全可见), 任务客观不可能。但 agent 把侧栏上下滚了 **11 次**(s01 反向撤销 + s02-s12 全无效), 才判 impossible。理想是 1-2 次确认顶部后即停。

### P4. 回退/对话框震荡 (open-confirm thrash)
打开一个对话框 → 又关/重开, A→B→A 来回, 没有在对话框里完成确认就退出再重进。

实例:
- **CAP002 s02→s03→s04→s05**: s02 点 Empty Trash 开确认框 (step03.png 见 "Empty all items from Trash?" 弹窗), s03 点确认 → s04 又点 "Delete Temporary Files..." 开另一个确认框 → s05 点确认。看似在做事, 但 px 高达 188 万(整页重绘=弹窗开关), 且**核心子目标 "关闭 File History 开关" 自始至终没做**(开关一直 ON, step02/step06 截图可见 1375,221 处橙色 ON)。任务被判 impossible, 但其实那个开关就在眼前。

### P5. 假成功 / 子目标漏做 (premature FINISHED)
多子目标指令只完成一部分就 FINISHED, 且 FINISHED 前夹带 1-2 个无效点击充数。`final_status=complete` 不可信。

实例:
- **CAP004 (complete)**: 指令=缩放 200% + 开 Fractional Scaling。step02.png 确认 200% 已选中, 但 **Fractional Scaling 开关仍 OFF (1375,383)**, 且顶部 "Apply Changes?" 从未点 Apply。s03 重点已选中的 200%(NOOP), s04 点空白(NOOP), 然后 FINISHED。两子目标只做一半, 还多 2 个废点击。
- **CAP007 (complete)**: workspace 数量因 P2 坐标越界没真正设成 6, 仍 FINISHED=complete。
- **L012 (incomplete)**: 5 步里 3 步无效, 字号没设成功。

---

## 3. 给工程子代理的可执行改进建议 (scenario_executor.py 护栏)

按根因对应, 全部是采集时即时拦截, 目标把冗余率从 51% 压到 <20%。

### 针对 P1 (无效点击不换策略) —— 最高优先级
- **连续无效熔断**: 维护 `consecutive_noop_count`。当一个动作 `had_effect=False` (changed_pixels < 阈值, 如 <500) 时计数+1; 有效则清零。
  - `count >= 2`: **禁止重发同一坐标±20px / 同一 element_id**, 强制 VLM 换一个候选元素 (在 prompt 里把刚失败的坐标列入黑名单)。
  - `count >= 3`: 触发"页面诊断"提示 —— 把当前截图连同 "上一动作无任何效果, 可能点到了禁用控件; 检查是否需要先 Unlock / 该控件是否可用 / 目标是否在别处" 一起喂给 VLM。
  - `count >= 4`: 强制早停 (`impossible` 或回退一层), 不再让它刷到 5+ 次。
- **禁用控件检测**: 点击前若该 element 的 a11y 属性 `enabled=False`/`sensitive=False`, 直接拒绝并提示先找解锁路径 (CAP009 的 Unlock 场景)。

### 针对 P2 (坐标空间错配) —— 数据可信度最致命, 必须先修
- **采集前断言分辨率一致**: 启动时读 VM 实际分辨率, 与 grounding/截图坐标系对齐。若 PNG 画布 (1920x1080) ≠ 实际渲染区 (960x540), 在 grounding 层统一做 scale 映射, 别让 VLM 在错误坐标系出点。
- **越界坐标拦截**: 点击坐标若落在"截图非空内容包围盒"之外 (右下死区), 直接判为无效并要求重定位, 不发送。这一条单独能消掉 CAP001M(m2)/CAP007 的大半冗余, 并让 m2 这类"非确定性失败"复现成功 (对照 m3 已证明同任务可成)。

### 针对 P3 (滚到极限反复滚)
- **滚动饱和检测**: 连续 2 次滚动 `changed_pixels < 阈值` (列表没动) → 判定已到边界, 禁止同方向再滚, 让 VLM 改为"在当前可见列表里决策"或判该项不存在。已有 Android 端 `_SCROLL_NO_NEW_PATIENCE` 思路, 桌面侧补一份。

### 针对 P4 (对话框震荡)
- **对话框内必须收敛**: 检测到 modal 弹出 (整页大面积重绘 + 焦点变化) 后, 限制只能点该弹窗内的按钮 (Cancel/Confirm), 点完即关闭状态机, 禁止开了 A 框去开 B 框造成 A→B→A。
- **子目标进度跟踪**: 把多子目标指令拆成 checklist (CAP002 = 清历史/关开关/清回收站/删临时), 每个子目标用 reverse-inference 单独判 done; **未全绿不允许 FINISHED**, 也避免漏做核心开关却去做次要操作。

### 针对 P5 (假成功)
- **FINISHED 前置校验**: agent 发 FINISHED 时, 对每条 capability_ref 的目标态做一次 a11y 断言 (如 toggle 应为 ON、scale 应为 200%)。任一未达成 → 拒绝 FINISHED, 标 incomplete 而非 complete, 阻止假成功污染训练集。
- **FINISHED 前剔废动作**: FINISHED 前若紧邻 NOOP 步, 导出时打标剔除, 别让"凑数点击"进最终轨迹。

---

## 4. 关键结论 (给协调者)

1. **全局冗余动作率 51.2%** (43/84 非终止步无效), 真实值约 55%+。超过一半动作是噪声, 数据当前不适合直接当"类人轨迹"训练。
2. **三大失败 episode (CAP001 83%, CAP009 83%, CAP001M-m2 69%) 全是同一类病**: 第一个有效动作之后陷入死点击/越界点击/无效滚动, 5-10 步刷废再放弃。
3. **m2 vs m3 对照是金证据**: 完全相同的指令, m3 7 步成功 / m2 14 步 impossible, 唯一差异是 grounding 坐标这次有没有落进有效区 → 失败主要是 **坐标空间错配 (P2) + 无熔断 (P1)** 的工程 bug, 不是任务真难。
4. **`final_status=complete` 不可信**: CAP004 / CAP007 标 complete 实为子目标漏做的假成功, 需 FINISHED 前置 a11y 校验。

---

## 协调者复核 (小克, 2026-06-28) — 重要更正

逐图复核了检验代理的三条根因, 结论如下:

- **根因 #1 (连续无效点击不换策略 / dead-click loop): 确认成立**。CAP002 step6-10、CAP009 连点禁用按钮、m2 后段瞎点均属实。这是首要抓手, 工程代理正在做"连续无效熔断"。

- **根因 #2 (坐标空间 2x 错配 / 内容只占左上 960×540 象限): 在采样数据中被证伪, 不予采纳为坐标重缩放依据**。直接 Read m2 与 m3 的 step01.png: 两图几乎完全相同, Settings 应用**满屏正常布局**(侧栏在左/内容在右), 坐标 (152,320)/(144,320) 正确落在侧栏项上, **不存在右下死区**。所谓 "m2 vs m3 金证据" 实为: 同一任务 CAP001M, VLM 跑两次, m2 后续无效点击瞎飞 14 步放弃、m3 干净 7 步完成 —— 是 #1 + VLM 非确定性, 非坐标 bug。
  - ⚠️ **禁止据此做坐标 2x 重缩放**(会把本来点对的动作改错)。
  - 保留一个**廉价防御**: 采集启动时断言"截图分辨率 == env 配置 screen_size", 不一致则以实测分辨率为准(应对 js1 docker 历史上的 1280x800 分辨率问题), 但**不做象限重映射**。

- **根因 #3 (FINISHED 假成功 / 子目标未真达成就标 complete): 成立, 值得实现**。CAP004 Fractional Scaling 开关没开、CAP007 workspace 没设成 6 却标 complete。FINISHED 前置 a11y/状态校验有价值。

**下一步**: 工程代理收尾 #1 后, 由协调者经 SendMessage 续派 #2(降级为分辨率断言, 不重缩放) + #3(FINISHED 前置校验), 保持每个 commit 干净内聚。
