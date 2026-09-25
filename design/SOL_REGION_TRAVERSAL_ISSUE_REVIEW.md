# Sol Region 遍历问题交接

> 日期：2026-09-05
>
> 用途：交给新对话继续做只读审查。
>
> 重要边界：本文记录的是 Sol 监督试跑和实验提交，不是当前主框架事实，也不是完整验收结果。未经用户逐项批准，不得把实验提交整体并入主框架。

## 1. 当前范围

本轮实际接触了 3 个应用：

| 应用 | 实际工作 | 结果 |
|---|---|---|
| Settings | 300 个 GUI 动作的长跑 | `partial / action_limit`；已有可用 Region 图骨架，但不是完成证书 |
| Chrome | 27 个动作 | partial；已停止，不继续分析或修改 |
| Clock | 0 动作冒烟检查 | 只证明流程能启动和编译，不代表遍历 |

其他应用没有实际遍历。

Settings 主跑得到：25 Pages、67 States、90 Regions、176 Region Variants、593 Canonical Operations、175 Transitions。64/67 个 State 完成清点；从根 State 可到达 65/67 个 State。图已编译，但仍有重复 Region、未完成操作和缺失返回路线。

本轮很慢的直接原因是：300 个动作产生了 803 次 Sol 调用；同时边跑边修框架，形成 15 个本地提交。后续不应继续采用“每一步都由 Sol 高强度推理，同时现场改框架”的方式。

## 2. 证据位置

- 实验工作区：`C:\Users\Admin\.codex\worktrees\1ba0\mywork`
- 实验提交范围：`83d5af18..aee218b1`
- 主框架当前仍在：`83d5af18`
- Settings 主证据：`C:\Users\Admin\.codex\worktrees\1ba0\mywork\artifacts\runs\region_graph_sol_01a06c31_20260904\desktop_setting_full_v3\20260904\setting`
- Settings 详细问题日志：上述目录下 `problem_log.md`
- Settings 图质量报告：上述目录下 `graph_quality_report.md`
- Chrome partial 证据：`C:\Users\Admin\.codex\worktrees\1ba0\mywork\artifacts\runs\region_graph_sol_01a06c31_20260904\desktop_chrome_full_v1\20260905\chrome`

原始回答在 `_modular_debug.jsonl`，确定性事件在 `events.jsonl`，图账本在 `exploration_ledger.json`。保存帧、离线测试、受监督 live pilot 和无监督 live acceptance 必须分开报告。

## 3. 五个最直观的问题

### 3.1 静态信息被当成可操作控件

![Settings About 页面](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_current_source_smoke/20260904/setting/screenshots/frame_00001.png>)

Hardware Model、Memory、Processor 等只是只读信息。真正可进入其他内容的是带箭头的 Device Name 和 Software Updates。

旧清点把只读信息也登记成 Element，却不给它们任何 Operation，导致操作列表被静态文字污染。

实验修改：没有 Operation 的内容不创建 Element，只写进 Region 的自然语言说明。

初步意见：方向合理，建议保留，但审查时要确认当前框架对 Element 的定义确实是“可执行对象”。

### 3.2 打开搜索框后漏报原有 Region

点击前：

![打开搜索前](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a2/before.png>)

点击后：

![打开搜索后](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a2/after.png>)

实际变化只是左上角出现搜索输入框。原来的工具栏、导航和 About 内容仍然存在。Sol 却只登记了新搜索 Region，框架无法判断其他 Region 是保留还是消失。

实验修改：动作后必须用已有 ref 简短说明来源 Region 是保留、变化还是消失；新 State 清单必须包含仍可见的 Region。

初步意见：问题真实，方向合理。需要检查字段是否过多，避免要求模型重复描述全部 Region。

### 3.3 Tooltip 使同一操作反复执行

![Output Device 只出现 tooltip](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a66/after.png>)

目标是打开 Output Device 选择器，但点击后只出现完整设备名称提示，没有出现候选列表。因为画面确实变化，结果被记为 `uncertain`，同一操作最终执行了 6 次，并穿插 6 次清理 tooltip。

实验修改：同一个未完成 Operation 的真实执行次数单独计数，`no_effect` 和 `uncertain` 都受限；建议上限为 3 次。

初步意见：现象真实，但修改后没有相同 live 场景复测，暂缓并入。还要确认固定 3 次是否会过早放弃可恢复的 grounding 错误。

### 3.4 桌面输入把新值追加到旧值后面

输入前为 `4`：

![工作区数量输入前](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a158/before.png>)

第一次输入 `3` 后变成 `43`：

![第一次错误输入](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a158/after.png>)

第二次又变成 `433`：

![第二次错误输入](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a159/after.png>)

根因是桌面端底层 `TYPING` 只输入文本，不使用目标坐标，也不清空旧内容。

实验修改分成两版：

1. 点击输入框，`Ctrl+A`，输入新文本；
2. 后来又改成执行两次 `Ctrl+A`，并要求模型报告最终可见文本，只有与目标完全一致才算完成。

初步意见：输入必须替换旧值，这个原则正确。但第一版只在空搜索框上验证，Chrome 随后仍出现 `weatherweather`。第二版又和另一个 Chrome 修复混在同一提交。应拆分后，在非空数字框和非空文本框上重新 live 验证。

### 3.5 GUI 成功，但框架先写入了未通过检查的 State

![Default Applications 搜索框已正常打开](<C:/Users/Admin/.codex/worktrees/1ba0/mywork/artifacts/runs/region_graph_sol_01a06c31_20260904/desktop_setting_full_v3/20260904/setting/action_attempts/a85/after.png>)

截图中的搜索框正常出现，GUI 动作没有问题。Sol 的结果报告却引用了错误 Region。旧实现先创建新 State，随后才发现报告不合法，于是图中留下一个没有 Region 的空 State，后续纠正又在新旧状态之间来回冲突。

实验修改：位置、Region 清单和动作结算必须一起通过检查后再一次性写入；失败时不提交半成品。

初步意见：这是图账本一致性问题。修改后有同类 live 正例，建议优先审查并保留，但要确认实现没有引入不必要的新持久字段。

## 4. Settings 全部问题简表

| 编号 | 问题 | 当前证据 | 初步审批意见 |
|---|---|---|---|
| P01 | 静态信息被创建为无 Operation 的 Element | 修改后 live 清点中无此类 Element | 建议保留 |
| P02 | 新 State 只报告新增 Region，漏掉仍可见来源 Region | a2 修改后 live 通过 | 建议保留，但检查输出是否过重 |
| P03 | 模型把已消失 Region 报为保留 | 现有合同具体指出错误，纠正时没有重放 GUI | 无需改代码 |
| P04 | 应用消失后恢复到 fresh 目标画面，旧门禁拒绝合法位置登记 | Settings Sound live 通过 | 建议审查后保留 |
| P05 | 已经位于 Sound，仍连续点击已选中的 Sound | 两次 no-effect 后现有上限已停止 | 无需新增规则，保留效率观察 |
| P06 | 稳定工具栏和导航偶尔被重复创建为新 Region | 同一应用再次出现，但没有跨应用证据 | 暂不修改，先改善候选证据 |
| P07 | 软件更新通知遮挡 Settings | hover 显示关闭按钮，再关闭；没有污染图 | 现有机制正确，无需改代码 |
| P08 | Sol 传输重试耗时很久 | 同一 GUI 动作只执行和结算一次 | 不改执行语义；可增加诊断日志 |
| P09 | 返回 Sound 时走了两跳，而不是直接使用当前可见入口 | 路线正确但较慢 | 暂不改，不能牺牲 Region 证据边界 |
| P10 | tooltip 让未完成操作反复执行 | 修改只有离线测试，没有同形 live 复测 | 暂缓 |
| P11 | 路由后使用旧 Variant 的 Element ref | 现有门禁拒绝，随后切到当前 binding 成功 | 无需改代码 |
| P12 | 未通过检查的新 State 被提前写入 | 修改后同类 live 通过 | 建议优先保留 |
| P13 | 已明确告诉模型“替代操作不等于焦点操作”，模型仍重复提案 | 4 次模型纠正后收束，GUI 没有重复 | 无需改代码；仅有调用成本 |
| P14 | known State 纠正信息分两轮给出，模型在两种答案间振荡 | 修改后单轮给全量 expected/received，live 通过 | 建议保留 |
| P15 | resume 反复重报相同 Region，只改措辞 | 结构相同检测后 live 通过 | 两个提交应合并后审查 |
| P16 | 回到已知 Network State 时重复创建三个内容 Region | raw 图仍保留重复 | 未解决；需要独立设计，不能按名称硬合并 |
| P17 | 空 owner 的 recover 点击了真实功能控件，功能没变却记 success | 下一次绑定动作才真正生效 | 未解决；先跨应用观察 |
| P18 | 第一代表项完成后，第二代表项被普通任务插队 | Sound 等页面已有连续代表 live 正例 | 建议保留 |
| P19 | 桌面输入追加旧值 | 第一版 live 证明空字段输入；非空字段仍失败 | 拆分并重新 live 验证 |
| P20 | 普通操作阶段反复提交同一结构，只改文字 | 基本零进展门有 live 证据，精确措辞漂移未复现 | 可保留，但应标注证据边界 |
| P21 | 已登记代表组后，模型再次提交代表组 | 现有门禁挡住，无重复 GUI | 无需改代码 |
| P22 | 已结算代表组后来重复发出 settled 事件 | ledger 只有一组，但事件统计重复 | 暂不改；记录为可观测性问题 |

## 5. Chrome partial 中发现的问题

| 编号 | 问题 | 初步审批意见 |
|---|---|---|
| C01 | 可选代理配置文件缺失；Chrome 能启动，但 Web Store 后来一直加载 | 因果未证明，不改代理和框架 |
| C02 | 更新失败气泡尚未关闭，模型先登记了后方 Region | 本次没有发现图污染；先跨应用观察 |
| C03 | 地址栏已有 `weather`，再次输入后变成 `weatherweather`，模型仍报完成 | 输入修复方向正确，但必须拆分并做非空字段 live 复测 |
| C04 | Web Store 长时间加载，模型连续报告不确定，pending 没有结束 | 新上限只有离线测试，而且来自超出当前 Settings 范围的 Chrome；暂缓 |

Chrome 的 C03 与 C04 被混在同一个提交 `aee218b1` 中，该提交不能原样批准。

## 6. 实验提交清单

主框架尚未包含以下提交。

| 提交 | 内容 | 证据状态 | 初步意见 |
|---|---|---|---|
| `5caace0a` | 拒绝没有 Operation 的 Element | focused test + 后续 Settings live | 建议保留 |
| `07d0e2ee` | 检查新 State 中来源 Region 的可见性 | focused test + Settings a2 live | 建议保留 |
| `5751f11b` | 恢复后只绑定 fresh 页面 | Settings Sound live | 建议保留 |
| `5ea798cb` | 限制同一未完成 Operation 的真实重试次数 | 离线通过，缺同形修改后 live | 暂缓 |
| `c512ca7f` | pending 位置和动作结果一次性提交 | 离线 + Settings a89 live | 建议优先保留 |
| `69312e81` | 记录上一项 live 证据 | 文档 | 与代码提交合并或最后统一整理 |
| `87d472b2` | known State 纠正一次给出完整预期，并限制纠正轮次 | 离线 + Settings a96 live | 建议保留 |
| `b33a4495` | 拒绝 resume 中完全相同的重复报告 | 被措辞变化绕过 | 不单独保留 |
| `22ad2b5b` | 重复报告改按结构判断，不受措辞变化影响 | Settings live 通过 | 与上一提交合并后审查 |
| `c2f533ce` | 记录恢复纠正证据 | 文档 | 最后统一整理 |
| `c19e9c87` | 已开始的代表组优先完成第二代表 | 离线 + Settings Sound 等 live | 建议保留 |
| `0bc33259` | 桌面输入先点击、全选、再输入 | 只证明空字段；非空字段仍失败 | 不单独批准完整性声明 |
| `ab742df2` | 普通 Operation 的重复清单也按结构判断 | 基本 live 通过，精确漂移场景未复现 | 可保留，注明证据边界 |
| `9d802a25` | Settings 图质量审计 | 文档 | 可保留或统一压成一个审计提交 |
| `aee218b1` | 双 `Ctrl+A`、输入值精确检查、uncertain landing 上限 | 只有离线测试；两个问题混在一起 | 必须拆分；输入部分重测，landing 部分暂缓 |

实验工作区当前 tracked files 是 clean，已经暂停，不会继续 GUI、修改、测试或提交。

## 7. 建议审批顺序

建议不要按提交顺序整体合并，而按问题逐组审批：

1. **图账本不能写半成品**：先审 `c512ca7f`。
2. **输入必须替换并验证最终值**：拆分 `0bc33259` 与 `aee218b1` 的输入部分，补非空字段 live。
3. **Region 保留/消失报告**：审 `07d0e2ee`，重点看是否增加了太多模型字段。
4. **恢复后的位置绑定**：审 `5751f11b`。
5. **重复报告与纠正振荡**：合并审查 `87d472b2`、`b33a4495`、`22ad2b5b`、`ab742df2`。
6. **代表项连续探索**：审 `c19e9c87`。
7. **暂缓项**：`5ea798cb` 和 `aee218b1` 的 uncertain landing 部分，等新的 live 证据。
8. 最后统一整理三份文档提交，不把实验描述误写成正式验收。

## 8. 给新对话的审查要求

新对话应当：

1. 先只读比较 `83d5af18..aee218b1`，不要直接 cherry-pick 或合并。
2. 每次只审一个问题组，读取对应截图、事件和最小代码差异。
3. 判断该问题是否真的需要框架修改，还是已有合同已经正确处理。
4. 检查修改是否引入新字段、固定次数、特殊名称、固定坐标或应用专用逻辑。
5. 明确区分离线测试、保存帧、受监督 live 和无监督验收。
6. 每组给出“保留、缩小、拆分、暂缓、撤回”之一，再等待用户批准。
7. 未经用户批准，不修改主框架，不重启 VM，不继续遍历。
