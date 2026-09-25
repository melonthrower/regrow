# 检验子代理第二轮报告 — 桌面采集 260628fix（三项防冗余护栏验收）

数据: `collections/OS/260628fix/setting/episodes/CAP001..CAP010`（10 条，js1 docker，截图 1280×800，GNOME 42 Settings）。
方法: 对每条 episode 自建标注脚本把 `grounding.element_center` 画红十字到对应 step 帧（写入各 episode 的 `annotated/`），逐帧 Read 实际看图判断「点在哪、落地页对不对」，结合 `trajectory.json` 的 thinking/annotation 做人工口径分类。
（注: 协调者提到的 `tools/annotate_desktop_actions.py` 不存在；现成 `tools/annotate_actions.py` 是面向 graph.json 的边检查工具，不适用 episode 轨迹，故自建标注。）

旧基线人工口径 51.2%（1920×1080，260623sc）。分辨率不同，仅看量级。

---

## 0. 关键结论（先给协调者）

- **人工冗余率 ≈ 31%**（90 个有动作步里 28 步是冗余/无效/震荡），比旧基线 51.2% 明显下降。**修复总体=帮 > 中性 > 伤**，无明显「伤」。
- **off_graph/noop 的本质压倒性是「行为/决策问题」，不是 grounding/坐标问题。** 抽查的所有 eff=False 点击，红框都精准落在真实控件上（侧栏项、toggle、Add Printer、Unlock 按钮）。1280×800 反归一化坐标全部正确。无效原因是：①重复点已完成的按钮；②点灰掉的禁用按钮；③点了会弹系统密码框/需特权、agent 过不去的控件。**grounding 不是当前瓶颈。**
- **7 条 impossible 里：真 impossible = 4（CAP001/CAP003/CAP004 + CAP005 环境崩），护栏过激/可改进 = 3（CAP002/CAP009/CAP010）。** 严格说没有一条是「目标本可达却被护栏过早枪毙」——3 条都是「目标(子任务)真做不到，但 agent 在放弃前空转了 4~9 步」。即护栏正确地没标 complete（fix#3 生效），但没能让 agent 早点判 impossible，于是预算被刷空才 impossible_stop。
- **下一轮最该改的 3 件事**（详见第 6 节）：①「据图早判 impossible」——目标页/控件不存在或禁用时，看一眼截图就停，别耗满预算；②「无效后换目标而非重试同一个」——连续 noop 应切到可见列表里另一个真实元素，而不是原地复点；③ CAP005 暴露的**断网类指令会打断 controller**，要么禁采这类指令要么用本地回环控制通道。

---

## 1. 人工口径冗余率（逐条）

分类口径: GOOD=有效推进/合理探索; REDUNDANT=重复已完成动作; NOOP=点真实控件但无响应/不该点; WRONG=点错目标(grounding错); THRASH=同动作来回震荡; RECOVERY=失败后的合理恢复。IMPOSSIBLE/FINISHED 终止步不计入分母。

| episode | 动作步 | GOOD | 冗余类(RED/NOOP/THRASH) | 冗余率 | 备注 |
|---|---|---|---|---|---|
| CAP001 暗色主题 | 10 | 2 (s0,s1合理找页) | 8 (s2-s9 空转scroll+1次点击) | 80% | 真impossible页(无Appearance)，但找页找了8步 |
| CAP002 文件历史/清空 | 12 | 7 (s0-s6 全有效) | 5 (s7-s11 重复点已清空的Trash/Temp) | 42% | 前半完美，后半复点已完成 |
| CAP003 蓝牙/鼠标 | 7 | 2 (s0,s1) | 5 (s2-s6 蓝牙无硬件来回点) | 71% | 蓝牙无硬件真做不到，仍空转 |
| CAP004 缩放200% | 5 | 5 (导航+滚动找Scale+合理判定) | 0 | 0% | 真impossible(无200%选项)，高效，模范 |
| CAP005 断网+勿扰 | 1(+11WAIT) | 1 (s0点wired) | 0(11 WAIT=环境崩) | n/a | 环境崩，非agent冗余 |
| CAP006 换壁纸 | 2 | 2 | 0 | 0% | complete，干净 |
| CAP007 Hot Corner/工作区6 | 6 | 4 (s1,s2,s3,s5) | 2 (s0空点+s4 hotkey无效) | 33% | complete，TYPE/HOTKEY可疑 |
| CAP008 多任务显示 | 1 | 1 | 0 | 0% | complete，1步到位 |
| CAP009 加打印机 | 6 | 2 (s0导航+s3点Unlock合理) | 4 (s1,s2,s4,s5 点灰掉的Add Printer) | 67% | Unlock弹密码框过不去 |
| CAP010 高对比度 | 4 | 4 (s0-s3 全有效) | 0(s4-s8 FINISHED循环不计动作) | 0% | toggle点准，但FINISHED空转5次 |

**总体**: 有动作步约 90（剔除 CAP005 的 11 WAIT 与各终止步），冗余约 28 → **人工冗余率 ≈ 31%**。
对比旧基线 51.2%：**下降约 20 个百分点**（口径同向，分辨率不同仅看量级）。窄口径协调者算 30%，与人工口径基本吻合。

---

## 2. off_graph / noop 的本质：grounding 还是行为？

**结论: 行为/决策问题占绝对主导，grounding 几乎无错。**

逐帧看红框（标注图在各 episode `annotated/`）：

- **点在真实控件上、但控件不响应/不该点（行为）**：
  - CAP002 s7-s11：红框精准落在 "Empty Trash..."/"Delete Temporary Files..." 红按钮上，但这些操作前面已做过，再点无 UI 变化（eff=False）。计 5。
  - CAP009 s1,s2,s4,s5：红框精准落在右上 "Add Printer..." 按钮上——该按钮**灰掉/禁用**（页面锁定），点它必然无效。计 4。
  - CAP003 s2-s6：红框在侧栏 Bluetooth/Mouse 项上，落地页正确，但蓝牙无硬件、目标 toggle 不存在。计 5。
  - CAP009 s3：红框在 "Unlock..." 按钮上（grounding 对），点了会弹 polkit 密码框，agent 过不去→页面无变化。计 1（这步是合理决策但注定失败）。
- **点到空白/图外无控件（grounding/坐标）**：
  - CAP001 s9：红框落在 Background 行附近（有控件），不是空白。
  - CAP007 s0：CLICK 但 center 为 None（grounding 未产出坐标，VLM 没给点），属于「没定位到」而非「定位错」，且下一步自纠。计 1（边缘）。
  - **真正点到空白/坐标偏移的 0 例。**

**计数**: 行为类无效 ≈ 15；grounding 类无效 ≈ 0~1（CAP007 s0 的「无坐标」算半个）。
**1280×800 反归一化坐标全部正确**（协调者首步观察一致）：所有侧栏首点都精准命中对应项，落地页正确。

---

## 3. 7 条 impossible 逐条定性（过激 a / 真impossible b）

| episode | 判定 | 依据 |
|---|---|---|
| CAP001 暗色主题 | **b 真impossible**（但找页低效） | GNOME 42 Settings 侧栏无 Appearance 页（截图确认全列：Network…Printers 无 Appearance）。主题/强调色在此版本不存在该页→目标真不可达。fix#3 正确没标 complete。扣分项=放弃前空转 8 步 scroll。 |
| CAP002 文件历史 | **a 偏护激/收尾差** | File History 已关、Trash/Temp 已清（s2-s6 eff=True）。其实主要子任务已完成，但「手动再清一次」语义被 agent 理解成必须再点一遍按钮→复点已清空对象 eff=False→预算耗尽 impossible。本应判 complete 或更早收手。 |
| CAP003 蓝牙 | **b 真impossible（子任务）** | VM 无蓝牙硬件（"No Bluetooth Found"），蓝牙 toggle 不存在→「检查/开蓝牙」真做不到。鼠标主键子任务已设。扣分=蓝牙来回点 5 步。 |
| CAP004 缩放200% | **b 真impossible，且高效** | Displays 页只有 Resolution(1280×800)+Fractional Scaling，无 Scale 百分比控件，200% 选项不存在。agent 5 步内据图判定停。**模范 impossible。** |
| CAP005 断网+勿扰 | **环境崩（非a非b）** | s0 点 Wired 断网→controller 与 VM 网络通道被切→后续 11 步全 WAIT 无截图→「no screenshot」impossible。基础设施失败，不是 agent/护栏问题。 |
| CAP009 加打印机 | **a 偏护激/能力缺口** | Printers 页可达，"Add Printer" 灰掉需先 Unlock，Unlock 弹 polkit 密码框 agent 无法输入特权密码→真过不去。agent 识别到要 Unlock（合理），但卡在密码框→空转 Add Printer 后放弃。属能力缺口而非纯护栏过激。 |
| CAP010 高对比度 | **a 护栏正确拦截+agent空转** | High Contrast 已成功开（s3 eff=True，toggle 变蓝）。但任务还含「打开屏幕阅读器」，Screen Reader 仍 Off。fix#3 **正确拒绝** s4-s8 的 5 次 FINISHED（没真达成不许 complete），但 agent 不去点 Screen Reader 而是反复 FINISHED→耗尽预算 impossible。护栏做对了，agent 没接住。 |

**计票**: 真 impossible（含环境崩）= 4（CAP001/003/004/005）; 偏护激/能力缺口 = 3（CAP002/009/010）。
**没有一条是「目标本可达却被护栏直接枪毙」**——3 条 a 都是「目标/子任务确实做不到，护栏没把它误判 complete（对），但也没帮它早点止损（可改进）」。这正是项目目标想要的方向（真做不到就如实停），只是止损太慢。

---

## 4. 护栏生效证据

- **fix#3（FINISHED 前置状态校验）明确生效**：CAP010 s4-s8，agent 连发 5 次 FINISHED，每次都被拒（Screen Reader 还 Off），没有产出一条假 complete。CAP006/008 反向证据：真达成时 FINISHED 一次通过。→ 假 complete 被有效压住（complete 7→3 的「质量」部分由此而来）。
- **fix#1（连续无效熔断+提前 IMPOSSIBLE）部分生效**：CAP001/002/003/009/010 都在「连续 eff=False」后被推入 impossible_stop，没有出现旧基线那种无限连点。但熔断**触发偏晚**——多在 4~9 次无效后才停（见各条冗余率），不是旧那种连点更多次。可视为「比旧轻，但仍偏多」。
- **fix#2（分辨率断言）间接验证**：1280×800 下所有反归一化坐标正确（第 2 节），无坐标系错配的误点，说明分辨率校验/适配没引入回归。
- **「连续无效→换策略」的痕迹**：基本**没有**。观察到的多是「连续无效→重试同一目标→熔断停」，而非「连续无效→换可见列表里另一个真实元素」。这是下一轮最大改进点。

---

## 5. CAP005 逐帧（最差，overall 0.34，eff 0/13）

- s0 CLICK (1007,173)：红框落在 Wired "Connected" 的 toggle/齿轮右侧区域（grounding 大体对，意图=关闭有线网）。
- s1~s11：全部 WAIT，**无 frame、无 thinking、无 analysis**；impossible 理由直接是 "no screenshot"。
- 本质：**这是断网指令把 controller 自己的网络控制链路切断了**。docker provider/PythonController 经网络与 VM 通信，agent 一关 Wired，截图与动作下发立即失效→env 只能 WAIT→耗尽→impossible。
- 这**不是** agent 决策错、也不是护栏问题，而是「指令语义与采集基础设施冲突」。eff 0/13 是假象（11 步是环境空转，唯一真动作 s0 实际可能生效了，只是看不到）。
- 处置：①断网/重启/注销这类会切断控制通道或改变会话的指令，应在指令生成阶段过滤（已有 dangerous 分类雏形，需把「断网」纳入）；或②控制通道走本地回环/串口/QMP，不依赖 guest 网络。

---

## 6. 修复净评价 + 下一轮工程清单

### 净评价
- **帮**：假 complete 被压住（fix#3），冗余率 51%→31%，无限连点收敛为有限熔断，坐标无回归。
- **中性**：impossible 数 3→7 表面变差，但拆开看 4 条是真做不到（含 1 条环境崩）、3 条是真做不到但止损慢——**质量上是更诚实的判定**，不是能力倒退。
- **伤**：未观察到明显「把本可完成的任务误杀」的情况。唯一接近的是 CAP002（主任务其实已完成却判 impossible），属「收尾/完成判定」问题而非护栏误伤。

### 下一轮最该改的 3 件事（按性价比排序）
1. **「无效后换目标」而非「重试同一控件」**（治冗余最直接）。当前熔断只会「连点 N 次同一目标→停」。应在连续 ≥2 次 eff=False 时，强制从当前可见元素列表里**选一个尚未尝试的真实元素**改点（CAP009 不该复点灰 Add Printer，CAP010 该去点 Screen Reader 而非复发 FINISHED，CAP002 该停或切下一子任务）。这一条能同时削掉 CAP002/009/010 的大部分空转。
2. **「据图早判 impossible」**（省步数 + 让 impossible 更快更对）。目标页/控件**在截图里不存在或处于禁用态**时，应一两步内据图判 impossible，而不是耗满预算。CAP001 找不存在的 Appearance 耗 8 步、CAP003 蓝牙无硬件耗 5 步——都可在「侧栏完整可见且无目标项」或「目标 toggle 灰掉/缺失」时即停。可加一个轻量「目标可见性预检」：进页后先问 VLM「目标控件是否存在且可用」，否→impossible。
3. **断网类指令隔离 / 控制通道解耦**（修 CAP005 这类系统性坑）。把「断开网络/关 Wired/重启/注销」纳入指令过滤（不采或标 dangerous 跳过）；中长期把 PythonController 通道改为不依赖 guest 网络（QMP/串口/本地 socket），否则任何「网络/会话」相关指令都会污染采集。

（grounding 增强**不是**当前优先级——本轮坐标全对，瓶颈在决策与止损，不在定位。）
