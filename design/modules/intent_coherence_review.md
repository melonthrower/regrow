# 意图连贯检验报告 (Intent-Coherence Review)

审查代理: 意图连贯检验代理 (小克)
日期: 2026-06-28
方法: 人类式逐步意图承接检查 (非结果分桶)。逐对读 thinking/reverse_sub_instruction + action_json + 前后截图 (截图均用 Read 实际看)。
**不采信任何既往 review 结论，全部从轨迹重判。**

截图语义说明: 本数据集 `stepNN.png` 记录的是**执行该步动作之前**的屏幕状态。因此判断某步是否"用了上一步建立的 affordance"，要看**下一帧**的屏幕。

---

## 协议给出的 NAMED 缺陷模式

- **abandoned-affordance（放弃式建立）**: 上一步打开了菜单/搜索/对话框/聚焦输入框，这一步却不用它转去别处。
- **intent-action 矛盾**: thinking 说做 A，动作做 B。
- **plan 抖动/绕路**: 相邻步意图跳跃、无谓往返。
- **冗余确认/空操作**: 对已完成的事再点、无推进的 WAIT/HOTKEY。
- **silent-subtask-drop（本次新增命名）**: 整条计划里某个明确子任务被零动作、零承认地丢弃，却仍标 complete。这是 plan 级的 intent-action 矛盾。

---

## CAP006 — 换壁纸（连贯参照样本）

**任务**: 把桌面背景换成"绿色田野风景"预设图。
**最小人类计划 (2 步)**: ① 侧栏点 Background ② 点绿色田野缩略图。

| step | action | thinking | 截图核对 |
|---|---|---|---|
| 0 | CLICK Background | "Click 'Background' in left sidebar" | step01 显示 Background 页已打开，缩略图网格出现，绿色田野在底排 ✓ |
| 1 | CLICK 绿色田野缩略图 (449,621) | "Click the green field landscape thumbnail" | step02 顶部预览变成绿色田野+蓝天，缩略图橙框选中绿色田野 ✓ |
| 2 | FINISHED | "all sub-tasks satisfied" | 确实已完成 |

**像人程度: 连贯。** 每一步意图直接承接上一步建立的页面，无绕路、无放弃 affordance、无空操作。**这就是"连贯长什么样"的基准**: thinking→动作→屏幕结果三者一致，且每步都把上一步的产物用掉。

---

## CAP007 — Hot Corner + 工作区固定6个（明显不像人，含搜索绕路）

**任务 (conditional)**: 看 Hot Corner 是否关着，关着就开；把工作区模式改成固定数量并设为 6。
**最小人类计划 (3 步)**: ① 侧栏点 Multitasking ② 看 Hot Corner（实际已 ON→无需动作；Fixed 也已选中→无需动作）③ 把 Number of Workspaces 改成 6（点字段→选中→输 6）。即一个老练用户约 3-4 个有效动作。

实际 7 步:

| step | action | thinking | 实况 |
|---|---|---|---|
| 0 | WAIT (grounding_failed) | "Click the Search toggle button... to open the search field." | 定位失败，空操作 |
| 1 | CLICK (91,50) | "Click the Search toggle button... to open the search field." | step02 证实: 顶栏搜索框已打开、光标在内，"Settings"标题被搜索框替换 |
| 2 | CLICK Multitasking (205,369) | "Click the Multitasking entry in the sidebar..." | 进入 Multitasking 页 |
| 3 | CLICK 数字字段 (992,744) | "Click the 'Number of Workspaces' input showing '4' to focus" | step04: 字段聚焦，光标可见 |
| 4 | HOTKEY ctrl+a | "select all existing text" | 选中 |
| 5 | TYPE "6" | "type '6' to set the fixed workspace count" | step06/final: 值=6 ✓ |
| 6 | FINISHED | "field shows 6 and Fixed selected, task complete" | 正确 |

**NAMED 缺陷:**
- **abandoned-affordance @ s1→s2**: s1 thinking 明说目的是"打开搜索框"，step02 也确认搜索框被打开+聚焦——然后 s2 **完全不在搜索框输入任何查询**，转头去点侧栏 Multitasking。建立了"搜索"这个 affordance 却整个抛弃。这正是协调者预告的搜索绕路。**本协议独立抓到了它**（不是靠既往结论；靠的是"s1 建立搜索→s2 抛弃搜索"的承接断裂 + step02 截图证据）。
- **intent-action 矛盾 @ s0/s1（深层）**: 任务第一子目标是"切换 Hot Corner"，但 s0/s1 的 thinking 都是"打开搜索框"，与子目标无任何语义关系。打开搜索本应是为了搜"Hot Corner"或"Multitasking"，但从未输入→意图与任务脱节。
- **冗余/空操作 @ s0**: WAIT，grounding_failed，零推进。
- **未验证 conditional 条件**: 任务要求"看 Hot Corner 是否关着"。Hot Corner 实际已 ON（step03 橙色），所以无需开——这点结果上没错，但轨迹**从未对 Hot Corner 做任何观察性/确认性步骤**，s3 直接跳到调工作区数量。人类至少会在 Multitasking 页停一拍确认。属轻微 plan 抖动。

**相对最小计划多走的步**: s0（空 WAIT）+ s1（开搜索）= 2 步纯绕路 + 思维错位。有效部分 s2-s5 是连贯且正确的。

**像人程度: 明显不像人**（前 2 步搜索绕路 + 意图与子任务脱节）。

> 既往检验#2 把 s0/s1 解释成"没定位到/自纠"而放过——本协议判定这不是自纠，而是**意图错位 + 放弃式建立**: s1 是成功打开了搜索（had_effect=True），不是定位失败，所以不能用"没定位到"洗白；而"自纠"应表现为下一步去用搜索或显式撤销，s2 既不用也不撤、直接换路，是绕路不是纠错。

---

## CAP008 — 多显示器显示模式 + 关 Active Screen Edges（明显不像人，silent-subtask-drop）

**任务 (sequential, 两个子任务)**: ① 把"多显示器工作区显示模式"改为"在所有显示器上显示"；② 关闭 Active Screen Edges 防误触。
**最小人类计划**: ① 进 Multitasking ② 找到多显示器显示模式控件并选"all displays" ③ 关 Active Screen Edges。

实际 2 步:

| step | action | thinking | 实况 |
|---|---|---|---|
| 0 | CLICK Multitasking (151,321) | "Click 'Multitasking'... to access workspace display mode settings" | step01: 进入 Multitasking 页 |
| 1 | FINISHED | "Active Screen Edges toggle is already off (gray)... sub-task complete" | final: ASE 确为灰/关 ✓ |

**NAMED 缺陷:**
- **silent-subtask-drop @ 整条**: 第一个、也是 instruction 里排第一的子任务"多显示器工作区显示模式→all displays"**完全没被处理**。读截图 step01/final 可证: 该 Multitasking 页根本没有"Workspaces on primary display only / on all displays"这种多显示器单选项（本 VM 单显示器，控件不存在）。轨迹既未尝试、也未在任何 thinking 里承认"找不到该选项"，直接 FINISHED 并标 complete。
- **intent-action 矛盾 @ s0→s1**: s0 thinking 明说进 Multitasking 是"to access workspace display **mode** settings"（为第一子任务），但 s1 一字未提该子任务，只对第二子任务（ASE 已关）拍板完成。承接断裂。
- **冗余确认成分 @ s1**: ASE 本就是关的，FINISHED 把"无需动作"当成"已完成"——结果不错但属未做事即收尾。

**相对最小计划**: 漏了 1 个核心子任务（多显示器模式），且无说明。

**像人程度: 明显不像人。** 人类遇到"页面上没有该选项"会显式反馈（"此机无多显示器"或"找不到该设置"），而非静默 FINISHED 标 complete。这是比 CAP007 更严重的连贯缺陷——CAP007 至少把主要工作做了，CAP008 把排第一的子任务整个吞掉。

---

## Round3 抽审（同任务复发性验证）

- **CAP007_r3a (88d1228e)**: 同样 6 步。s0 thinking="Click the Search toggle button... to navigate to the Search settings page"——**错误心智模型**: 把顶栏搜索切钮当成"会跳到 Search 设置页"，s1 才发现"Hot Corner is not on this Search page"再改道 Multitasking。**同款搜索绕路 + intent-action 矛盾复发**（且这版连"搜索切钮的行为"都理解错）。
- **CAP008_r3a (e3a92b9a)**: 与 fix 版**逐字相同**的 2 步——进 Multitasking → 立刻 FINISHED，只提 ASE，**silent-subtask-drop 复发**。

→ 这两类缺陷不是偶发，是**跨轮稳定复现的结构性问题**。搜索绕路集中在"任务起点不确定→先去搜索"的错误起手式；silent-drop 集中在"页面缺少所需控件时静默收尾"。

---

## 像人程度汇总

| Episode | 最小人类步数 | 实际有效/总步 | 像人程度 | 主要 NAMED 缺陷 |
|---|---|---|---|---|
| CAP006 (fix) | 2 | 2/3 | **连贯** | 无（参照样本） |
| CAP007 (fix) | 3-4 | 4/7 | **明显不像人** | abandoned-affordance(s1→s2), intent-action矛盾(s0/s1), 空WAIT(s0) |
| CAP008 (fix) | 3 | 1/2 | **明显不像人** | silent-subtask-drop(整条), intent-action矛盾(s0→s1) |
| CAP007 (r3a) | 3-4 | -/6 | 明显不像人 | 同 fix + 搜索切钮心智模型错误 |
| CAP008 (r3a) | 3 | -/2 | 明显不像人 | silent-subtask-drop（与 fix 逐字相同） |

---

## 意图连贯协议 vs 结果分桶：多抓到了什么

1. **抓到 CAP007 搜索绕路（结果分桶漏判）**: s1 had_effect=True（确实开了搜索）、非图回退、最终任务也算达成，结果指标全绿。只有"s1 建立搜索 affordance → s2 抛弃它"这条承接检查 + step02 截图，才能判它不像人。**本协议独立复现了协调者预告的这个 case，未依赖既往结论。**

2. **抓到 CAP008 silent-subtask-drop（结果分桶完全看不见）**: 这条最危险。它 num_steps=2、每步 had_effect 看着合理、scenario_success=true、final_status=complete——结果分桶会把它当成"高效完成的干净样本"收进训练集。但它实际**把 instruction 排第一的子任务整个吞掉且不承认**。这种"少做了一半还自称完成"的样本若进训练数据，会教模型"遇到做不了的子任务就静默跳过并谎称完成"——比绕路更有害。

3. **区分了"自纠" vs "绕路"**: 结果分桶（及既往 review）倾向把"开了搜索又换路"宽容解释为自纠。意图连贯协议用"下一步是否使用/撤销上一步产物"做硬判据: 用了/撤销=自纠，既不用也不撤直接换路=绕路。CAP007 s2 属后者。

4. **暴露错误心智模型（r3a CAP007）**: thinking 显式说"搜索切钮会跳到 Search 页"，与真实行为（开内联搜索框）不符。这类"agent 对 UI 的世界模型错误"只能靠读 thinking 语义抓，结果分桶无入口。

**结论**: 三条 complete 中，CAP006 真干净；CAP007、CAP008 均被既往判为干净 complete 但实含意图不连贯，且两类缺陷在 Round3 跨轮稳定复发。建议: ①数据导出前增加意图连贯闸门（承接断裂 + silent-drop 检测）；②CAP008 型 silent-subtask-drop 应直接拒收或降级，不可作为 complete 训练样本。
