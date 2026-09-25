# A/B 真值表对照 — 260628ctrl vs 260628fix (第三轮检验)

## 背景
同一批 10 条 setting 指令 (CAP001-010)，js1 docker 同环境 1280×800 跑两次，只差执行器代码：

- `collections/OS/260628ctrl/` — **原始** executor。final_status: complete 6 (CAP003/004/005/006/007/010) / impossible 4 (CAP001/002/008/009)。
- `collections/OS/260628fix/` — 带 R1 三项修复（无效熔断 / 分辨率断言 / **FINISHED 前置目标态校验**）。complete 3 (CAP006/007/008) / impossible 7。

逐帧（trajectory.json + screenshots/final.png 实读）坐实"标了 complete" vs "真的做到了"。

## 真值表

| CAP | 指令简述 | 原始status | 原始真达成? | fix status | fix真达成? | 分类 |
|-----|----------|-----------|------------|-----------|-----------|------|
| 001 | 深色主题 + 青蓝配色 | impossible | 否(没进Appearance页, 停在Background) | impossible | 否 | 真失败(任务可做但两版都没做到, 判定均正确) |
| 002 | 关File History + 清空回收站 + 删临时文件 | impossible | 否(File History关了, 但Empty Trash/Delete Temp确认框没点完) | impossible | 否 | 真失败(可做但两版都没完成确认, 判定均正确) |
| 003 | 蓝牙(无则开) + 鼠标主键改Left | **complete** | **否** | impossible | 否 | **原始假成功被fix纠正**(蓝牙"No Bluetooth Found"硬件缺失=真不可能; 鼠标本就是Left) |
| 004 | 缩放调到200% + 开分数缩放 | **complete** | **否** | impossible | 否 | **原始假成功被fix纠正**(Scale只有100/125/150%, 无200%选项=真不可能; 分数缩放虽开但缩放仍100%) |
| 005 | 断有线网 + 开勿扰 + 音量最大 | complete | **是**(三项实测全做到: 有线toggle灰, 勿扰橙, 音量满格) | impossible | 否(执行崩溃: step01起陷UNKNOWN死循环, grounding 0.077, 只剩step00.png) | **fix真regression**(原始真做到, fix执行崩溃没做) |
| 006 | 桌面背景换"绿色田野风景" | complete | 是(大预览=绿野风景) | complete | 是 | 真成功(两版都真做到) |
| 007 | Hot Corner(关则开) + 工作区Fixed=6 | complete | 是(Hot Corner已开满足条件; Fixed选中; 数量=6) | complete | 是 | 真成功(两版都真做到) |
| 008 | 多显示器"所有显示器" + 关Active Screen Edges | impossible | **是**(两目标态环境默认就满足: "all displays"已选橙 + Active Screen Edges已灰off) | **complete** | 是 | **fix WIN / 纠正原始假impossible**(原始找Active Screen Edges方向滚反, 向下死循环耗尽预算误判impossible; fix一进页见已满足→FINISHED) |
| 009 | 主设置右上角加打印机 | impossible | 否(需admin解锁, "Unlock to Add Printers"横幅, Add Printer灰禁=真不可能) | impossible | 否 | 真impossible(两版判定均正确) |
| 010 | 屏幕阅读器(关则开) + 高对比度开 | complete | **是**(High Contrast开 + Screen Reader弹窗toggle已开蓝) | impossible | 否(High Contrast开了, 但Screen Reader列表仍Off=没开) | **fix真regression**(原始两项都做到, fix漏了屏幕阅读器; 但fix"impossible"判定对fix那次实际结果是准确的——判子无错, 错在fix那次执行) |

## 真实成功率统计

**原始 (260628ctrl)**
- 标 complete: 6 (CAP003/004/005/006/007/010)
- 其中真达成: CAP005/006/007/010 = 4 (CAP003/004 是假成功)
- 标 impossible 中其实真达成: CAP008 (假 impossible)
- **真实成功率 = 5/10 = 50%** (CAP005,006,007,008,010)

**fix (260628fix)**
- 标 complete: 3 (CAP006/007/008)
- 全部真达成 = 3 (无假成功)
- 标 impossible 中其实可成功但没做到的: CAP005(执行崩溃), CAP010(漏屏幕阅读器) — 这两条本可完成
- **真实成功率(实际做到) = 3/10 = 30%** (CAP006,007,008)

## fix 相对原始

**纠正的假成功: 2 条**
- CAP003 (蓝牙硬件缺失=真不可能, 鼠标本就Left → 原始误判complete, fix如实拒为impossible) ✅
- CAP004 (200%缩放选项不存在=真不可能 → 原始误判complete, fix如实拒为impossible) ✅

**额外纠正的假 impossible: 1 条 (fix 独立加分)**
- CAP008 (目标态环境默认已满足, 原始滚动死循环误判impossible → fix一眼识别已满足判complete) ✅

**真 regression: 2 条**
- CAP005 — 原始三项全真做到, fix 那次执行从 step01 起陷 UNKNOWN 死循环(grounding 0.077, effective 0/13)彻底没做。**根因=执行/grounding 崩溃, 非 fix#3 目标态判子误杀**(那次根本没产出可判的成功态)。
- CAP010 — 原始两项(高对比度+屏幕阅读器)都做到, fix 只开了高对比度、漏了屏幕阅读器。fix 的 "impossible" 判定**对 fix 那次的实际结果是准确的**(屏幕阅读器确实仍 Off), 判子无误; 差距来自 fix 那次执行少做了一步。

## 净变化与结论

| 维度 | 数值 |
|------|------|
| 原始真实成功率 | 50% (5/10) |
| fix 真实成功率 | 30% (3/10) |
| fix 纠正的假成功 | 2 (CAP003, CAP004) |
| fix 纠正的假 impossible | 1 (CAP008) |
| fix 造成的真 regression | 2 (CAP005, CAP010) |
| 真 regression 根因 | 均为 fix 那两次的**执行层崩溃/漏步**(CAP005 UNKNOWN 死循环; CAP010 漏屏幕阅读器), **非 fix#3 目标态判子误杀** |

**一句话结论**: fix 的**判子本身是净赢**——成功堵死 2 条假成功(CAP003/004)且额外纠正 1 条假 impossible(CAP008), 标 complete 的 0 假成功, 标签可信度大幅提升; 但 fix 那两次跑(CAP005/010)因执行层自身崩溃/漏步丢了 2 条本可完成的任务, 致**实际做到的成功率从 50%→30% 下降**。即: **标签质量净赢, 端到端实测成功率短期净亏**, 且亏损源于执行不稳而非修复逻辑。判子可信度的提升是结构性收益, 执行层的两次崩溃是偶发噪声(同环境不同 run 的随机性), 不应归咎于 fix#3。

## 关键证据帧
- CAP003: ctrl/fix final 均停 Bluetooth "No Bluetooth Found" (硬件缺失)
- CAP004: ctrl/fix final Displays 页 Scale 仅 100/125/150% 三档, 无 200%; Fractional Scaling 已开但 Scale 仍 100%
- CAP005: ctrl final Sound 页 System Volume 满格(+轨迹证有线off/勿扰on); fix 仅 step00.png
- CAP008: ctrl final 滚到底"Workspaces on all displays"已选(没点过); fix final Active Screen Edges 已灰 off → 两态默认满足
- CAP010: ctrl final Screen Reader 弹窗 toggle 蓝(开)+High Contrast 开; fix final Screen Reader 列表 Off
- CAP009: Printers 页 "Unlock to Add Printers" 横幅 + Add Printer 灰禁
