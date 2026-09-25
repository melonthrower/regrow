# 长任务意图连贯检验报告 (260628lc, 5能力长链)

审查对象: 3 条 `final_status=impossible` 的长任务 (Accessibility 无障碍设置, 每条 5 个能力子目标)。
方法: meta.instruction + capability_refs → 推最小人类计划; 逐步读 thinking/action_json/前后截图(实际 Read 看图); 标 NAMED 缺陷; 定位崩点; 每子目标判达成/silent-drop/尝试失败; 横向比短任务多出的崩法。
**重要约定: 本批 trajectory 的 `frame: stepNN.png` 是该步动作的 *前置(BEFORE)截图*** (即 step N 决策时的画面), 故"动作效果"看 step N+1 的截图。

---

## 共性最小人类计划 (5 子目标)
LC014: ①HC开 ②屏幕键盘开 ③鼠标键开 ④光标大小=Maximum(开对话框选最大那个图标) ⑤双击延迟拉到最右。约 9-11 步(2 步进页 + 5 个设置, 各含必要滚动)。
LC005: ①进 Accessibility ②HC开 ③大字体开 ④屏幕键盘开 ⑤定位指针开 + 双击延迟最右(注: capability_refs 实际是 6 个 ref, "调延迟"是第6个, 但指令含 6 个动作)。约 9-11 步。

---

## LC014_788021a6 (19 步)
子目标状态:
- ①High Contrast: **达成** (step2 CLICK, toggle 变蓝, 主题切高对比)。
- ②屏幕键盘: **达成** (step3 CLICK, toggle 变蓝)。
- ③鼠标键(Mouse Keys): **达成** (step6 CLICK, 变蓝; 终态 step18 仍 ON)。
- ④光标大小=Maximum: **尝试失败 / abandoned-affordance**。step8 点开 Cursor Size 对话框 (step09.png 实拍: 5 个由小到大光标图标的模态框已打开, 最右=最大正是目标)。step9 thinking 直接写 "Close the Cursor Size dialog to access the Double-Click Delay setting behind it" → 点 X(946,335) 把框关掉, **没选任何尺寸**。终态 Cursor Size = Default。
- ⑤双击延迟最长: **达成** (step12 DRAG 至最右, step18.png 实拍 slider 在最右端)。

崩点: **step8→step9 (第4子目标)**。前 3 个子目标+第5个都干净达成, 唯独第4个把正确的对话框打开后又关掉。
崩后行为: step13-17 连发 **5 次 FINISHED** (thinking 全是复读"DCD slider already at max"——只盯着已完成的第5子目标, 完全忘了第4子目标没做), step18 IMPOSSIBLE。
NAMED 缺陷:
- **abandoned-affordance** (step9): 打开正确对话框却关闭不选。
- **intent-action 矛盾 + 错误心智模型** (step18 IMPOSSIBLE reason): 理由文本 "High Contrast toggle not visible (likely above scroll)... Cursor Size setting is not on screen" — HC 明明 step2 已成功开启, 这是 **幻觉式自证不能**; agent 不知道自己做过什么 (无完成记忆), 用"当前屏幕看不到"反推"没做成"。
- **plan 抖动** (step13-17): 5 次空 FINISHED 后才 IMPOSSIBLE, 纯烧预算。
像人程度: 中下。前段操作很像人 (滚动定位+点 toggle 利落), 但在唯一难点(对话框选项)上做出反人类动作(开了就关), 且结尾陷入"复读已完成项→不能"的死循环, 完全暴露无状态记忆。

## LC014_4cc4bee6 (17 步, 同指令另一次跑)
**几乎逐帧复刻 788021a6**:
- ①HC step2 达成 / ②屏幕键盘 step3 达成 / ③鼠标键 step6 达成 / ⑤双击延迟 step11 DRAG 达成 (终态 step16.png slider 最右)。
- ④光标大小: **同样 abandoned-affordance** — step8 开 Cursor Size 对话框, step9 thinking 一字不差 "Close the Cursor Size dialog to access the Double-Click Delay setting behind it" → 关框不选。
崩点: 同样 step8→step9 第4子目标。
崩后: step12-15 四次 FINISHED + step16 IMPOSSIBLE, 理由同款幻觉 ("High Contrast not visible / Cursor Size not on screen")。
两次跑同一缺陷 → **可复现的系统性失败**, 不是随机抖动: 模型把"光标大小对话框"误判为挡路的弹窗而非任务目标本身。

## LC005_f64d77fd (15 步) — 最严重: 任务其实做完了却判 impossible
子目标状态 (全部达成):
- ①进 Accessibility: **达成** (step0 滚 + step1 CLICK)。
- ②High Contrast: **达成** (step2)。
- ③大字体 Large Text: **达成** (step3, toggle 变蓝, 字体变大)。
- ④屏幕键盘: **达成** (step5)。
- ⑤定位指针 Locate Pointer: **达成** (step7 CLICK; step09.png 实拍 Locate Pointer 蓝)。
- (双击延迟最长): **达成** (step8 DRAG 至最右; step09.png slider 在最右端)。
崩点: **没有真正的执行崩点 —— 5/5 + 延迟全部完成**。失败发生在 *终止判定*。
崩后行为: step9 FINISHED → **step10 多余 DRAG** (起点 1065,776 在 slider 最右端外, 终点 1267,776 拖进右侧空白/导航区, step10.png 显示页面零变化, 纯无效动作) → step11-13 三次 FINISHED → step14 IMPOSSIBLE。
NAMED 缺陷:
- **false-impossible (完成态误判不能)**: 这是本批最严重缺陷。一条本该 success 的轨迹被标 impossible+agent_failure, 直接污染成功率统计 (excluded_from_agent_stats=false → 被计入)。
- **错误心智模型 / intent-action 矛盾** (step14 reason): "High Contrast and Large Text toggles are not visible... so their ON state cannot be verified" — 二者 step2/step3 确已开启, agent 因当前滚动位置看不到就判"无法确认→不能"。**把"看不见"等同于"没做成"**, 同 LC014 同根。
- **plan 抖动 / 多余动作** (step10): 已完成还重复拖一次 slider (且拖飞)。
像人程度: 中。前 9 步非常像人, 一步到位全部设好; 但结尾人类会确认"都设好了→FINISHED 成功", 它却滚不回去验证就自我否定, 像一个有严重短时记忆缺陷+不信任自己操作的人。

---

## 横向: 长任务相比短任务多出的崩法

1. **无完成记忆 → 误差/遗忘累积到结尾集中爆发 (长链特有, 三条全中)**
   短任务子目标少, "当前屏幕"基本覆盖全部进度; 长链有 5-6 子目标, 单屏放不下, agent **没有"已完成子目标"的持久记忆**, 只能用"当前截图能否看到目标处于目标态"来判断完成。一旦目标项滚出视野(HC/大字体在顶部, 已设好但看不见), 就判"无法确认→不能"。→ 产生 **false-impossible** (LC005 整条) 和 **幻觉式 IMPOSSIBLE reason** (LC014 两条都说"HC not visible"暗示没做, 实则做了)。这是短任务几乎不会出现的崩法。

2. **terminal-flailing: 结尾大量空 FINISHED / 多余动作烧预算 (三条全中)**
   LC014 各 4-5 次连发 FINISHED, LC005 还插一次拖飞的 DRAG。短任务到点就 FINISHED; 长任务因为"覆盖不全→不敢真 FINISHED 又不知道还差啥", 在终态附近空转直到预算耗尽转 IMPOSSIBLE。约 1/4~1/3 的步数(19步里 6步, 17步里 5步, 15步里 6步) 是这种零价值尾巴。

3. **唯一真实子目标失败被无关复读掩盖 (LC014 两条)**
   光标大小对话框 abandoned-affordance 是真失败, 但崩后 thinking 全在复读已完成的"双击延迟" → agent **注意力锚在最后一个子目标**, 对中间漏掉的子目标零回顾。短任务只有一个目标不会出现"盯错子目标"。

4. **状态依赖前置基本没问题**
   本批不是"前置没做导致后续无法进行"型崩法 —— 进页/各 toggle 都按序做了, 顺序也对。长链的瓶颈不在 plan 排序, 而在 **(a) 单个交互模式难点(对话框选项 vs toggle/slider)** 和 **(b) 终止判定缺记忆**。

---

## 结论: 长任务采集效果 & 提成功率优先级

- **3 条全部是 agent_failure 误判/可救, 没有一条是真 impossible**:
  - LC005 是 **假 impossible (其实成功)** → 标注层 bug, 白白丢一条好数据还污染统计。
  - LC014 两条 **只差 1/5 子目标(光标大小对话框选项)**, 其余 4 个+延迟都成功 → 属"差一点"而非"做不到"。
- **提成功率应先治 (按杠杆排序)**:
  1. **加"已完成子目标"持久记忆 / 完成态台账**: 让 agent 不靠当前截图、而靠"我点过 HC 且当时变蓝"来判完成。直接消除 false-impossible(LC005) 和幻觉式 IMPOSSIBLE reason(LC014×2)。**最高杠杆, 一招救 3 条全部**。
  2. **对话框/选项类交互的探查策略**: 教 agent "打开的对话框=要从里面选, 不是要关掉"。专治 LC014 两条唯一真失败点 (abandoned-affordance)。
  3. **终止判定收尾**: 检测连续无效 FINISHED/零变化动作时, 主动滚动复查各子目标再决定 FINISHED/IMPOSSIBLE, 而非空转烧预算。消除 terminal-flailing。
- **数据可信度警示**: LC005 这类"已完成却 impossible_cause=agent_failure 且 excluded_from_agent_stats=false"会**高估 agent 失败率**; 现有 QC/标注组件未捕获"完成态误判不能", 建议给整轨判定加一道"终态核对各子目标实际状态"的复核(可对终态截图滚动重扫各 toggle/slider)。
