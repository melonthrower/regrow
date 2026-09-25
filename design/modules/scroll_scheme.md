# 滚动方案设计:地图定位式滚动(Scroll-by-Map)

> 2026-07-02 提出。背景:§6 回归暴露"滚动后落点漂移点错行 + About 召回抖动"两类病,
> 根源都是开环滚动("滚 N 步 + 信注册时的坐标")。本方案换骨架:**不预测位移,测量位置**。

## 0. 一句话

每页先拼出像素级全页长图(地图,已有积木);元素地址 = 长图绝对坐标 `(x, y_global)`;
之后任何时刻用**当前帧对长图做模板匹配**得到视口位置 `y_view`(毫秒级 cv2,零 VLM),
伺服式滚到目标进视口再点 `(x, y_global − y_view)`。
执行器(fling/滚轮)只需"大致可控",精度由**测量闭环**保证,不再依赖执行器确定性。

## 1. 现状为什么难(病根盘点)

| 病 | 根源 |
|---|---|
| 落点漂移(About 点成 Removable Media / Power) | 滚动位移不可复现:移动 fling 惯性、桌面 GTK 动画合并/行吸附/边界截断 → "滚3步"两次落点差一两行 |
| About 召回抖动(3 轮 1 中) | 聚合期**逐帧** VLM 命名,每帧都掷一次骰子;漏一帧=漏一个元素 → 元素集不稳 → 身份不稳 |
| 核名保险网弱 | OCR 对小字/主题敏感;VLM 兜底本身随机;(盲点旧坐标保底已删,CHANGE 17) |
| 慢 + 随机性放大 | 每页重滚重认侧栏 chrome,而侧栏全 app 不变 |

补丁(模板匹配、OCR 核名、VLM 兜底、patience)都是在救开环,救不完。

## 2. 核心思想(SLAM 类比)

- **建图一次**:滚到底采帧,`stitch_region_crops` 拼像素级长图(CHANGE 13,单测 SAD 0.00);
- **Android 系统带只留一份**:touch 整屏 stitch 用固定 status/navigation 像素带作 sticky 下限，避免动态时钟/手势 pill 打断像素推断后被重复贴到 seam；`y_map` 源行在 tiled grounding 再做一次系统 UI 门禁，app sticky toolbar 与 system band 分开;
- **定位每帧**:当前截图在长图里 matchTemplate → 直接读出视口偏移,不数步数;
- **按图导航**:目标在图上的绝对坐标是稳定地址,伺服环"测量→滚一步→再测量"收敛到可见。

执行器的不确定性(惯性、动画、吸附)全部无所谓——每步之后重新测量,误差不累积。

## 3. 设计

### 3.1 执行器规范(先把随机性砍到最低,但不指望它为零)
- **桌面**:`startup_reset` 时发 `gsettings set org.gnome.desktop.interface enable-animations false`
  (VM 每次 revert 还原,故每次 reset 重发,~0.2s);滚动 = 光标停区内(CHANGE 4)+ `vscroll(±8)`;
- **移动**:引擎所有滚动切 `_scroll_action(frac=0.5, slow=True)`(原语已有,STITCH 在用),
  端点停顿再抬手 → fling 归零;
- **settle-wait(新增,关键小件)**:每次滚动后轮询截图,直至**连续 2 帧相同**再采集
  (上限 ~1.5s)——保证采到的永远是动画结束后的稳定帧,位移测量才精确;
- **顶/底 = 吸收态**:`scroll_to_top` = 向上滚至帧不变×2(自终止,不计数,天然可复现)。

### 3.2 建图(每区一次)
```
scroll_to_top(region)
frames = [capture()]
while not 吸收态(帧不变×2):        # 判底,About 的像素必然进图
    scroll_down_one_step(); settle-wait; frames.append(capture())
long_img = stitch_region_crops(frames)      # 像素级拼接(已有)
elements = ground_once(long_img)            # 长图一次 grounding;过高平铺(c44274ed 已有)
每元素记: (x, y_global, crop←取自长图)      # crop 与长图同源渲染
scroll_to_top()                             # 离开时归位规范态
```
- **chrome 区只建一次**:侧栏经 RegionRegistry 全 app 建一次(CHANGE 7/14,§9 已验),
  每页只建 content 区 → VLM 调用从"每页×每帧"降到"每页 1 次"。

### 3.3 点击定位(伺服环,零 VLM)
```
scroll_to_top(region)
loop:
    y_view = localize(当前帧, long_img)     # 条带中值匹配(见 §6 抗高亮)
    if y_global ∈ [y_view, y_view+H): break
    按差值方向滚一步; settle-wait           # 可上可下,天然处理过冲
点击前核验: 点位处 live crop vs 长图 crop(SAD/pHash 紧阈值,同源渲染,不再用 OCR)
不过 → fail-closed 跳过(CHANGE 17 外壳保留)
```

### 3.4 身份
state_id 改用长图 content 区的一次-grounding 完整元素集签名(不再逐帧并集)
→ 同页两次注册天然同集,身份稳定性与召回问题一起消掉。

## 4. 痛点 → 消解对照

| 今天的痛 | 新方案里去哪了 |
|---|---|
| fling/动画位移不可复现 | 不依赖位移预测,每步测量(3.3) |
| About 召回抖动 | 判底=吸收态 ⇒ 像素必在图里;grounding 一次可平铺/重试;命名即使漏,像素还在图上可后补 |
| 落点漂移点错行 | 地图绝对坐标 + 同源像素核验,错位则拒点 |
| OCR 核名弱 | 同源 crop 像素比对(同一渲染,阈值可以紧) |
| 每页重滚侧栏 | region-once(3.2) |
| scroll_steps 语义漂移 | 字段废弃,改 y_global |

## 5. 已有积木(大头都在,新增只有三小件)

已有:stitch_region_crops 像素级拼接(CHANGE 13);STITCH_NODE_IMAGE 长图+perceive-once
(commit 1491e64c,flag);长图过高平铺(c44274ed);RegionRegistry 区块跨节点匹配(§9 PASS);
光标停区(CHANGE 4);fail-closed 点击(CHANGE 17);滚轮-diff 判可滚(§4 PASS)。

**新增**:① settle-wait;② `localize(帧→长图)` 条带中值匹配;③ 伺服环替换 `_scroll_locate` 内核。

## 6. 已知风险与对策

- **选中高亮/动态行使 帧≠图**:localize 用多条水平条带各自匹配取**中值偏移**
  ——单行变化(高亮移动、一个新 Wi-Fi 行)不影响中值;定位分数骤降 = 页面真变了
  → 触发该区**重建图**(自愈,而非报错)。
- **懒加载长列表(移动)**:吸收态判底已覆盖;长图可增量续拼。
- **横向滚动**:同构,换 x 轴。
- **误判可滚性**:前置现有滚轮-diff 检测(§4)。

## 7. 分步落地(每步可独立用 §3-§6 回归)

1. 执行器层:settle-wait + 桌面关动画(reset 时重发)+ 移动聚合滚动切 slow/frac;
2. `scroll_to_top` 吸收态化,替换各处"计数回顶"(含 §6 harness 的滚轮×6);
3. `localize` + 伺服环替换 `_scroll_locate` 内核(CHANGE 17 fail-closed 外壳保留);
4. 元素账本/身份切 `y_global`,废弃 `scroll_steps`;
5. region-once 默认开(侧栏全 app 一次)。

步骤 1-2 半天量级、纯执行器层零算法风险;3 是核心件(一个 cv2 函数+一个循环);
4-5 是账本/开关切换。全程 flag-guarded,与现行为可并存对比。

## 8. 原型验证(2026-07-02,`_scratch/_scrollmap_probe.py`,8 轮迭代,未动引擎)

**终局(第 8 轮): 5/5 落点全对**——About×3 / Network / Date & Time,序列判定由落点页
标题 OCR 模糊匹配。About 三进三中(§6 一直不稳的回溯动作),单次 goto 19-34s。
关动画后桌面滚动位移**完全确定**(每步恰 179px,轨迹 0→179→358→537→623 分毫不差);
建图 5 帧→240×1128 像素级自洽(底部偏移+视口高=图高);全点击链路**零 VLM**
(建图后目标坐标全由地图 OCR 提供,ground-once 3.1s)。

**八轮实测修正(引擎接入时照抄)**:
1. 地图上的目标坐标 **OCR 为主**——VLM 对瘦长图降采样失真(About 标到 y=1151,超出 1128
   图外;三轮 y 漂 1054/1054/1127);OCR 是像素真值。VLM 只兜 icon-only。
2. OCR 需**同行框合并**(y 差≤12px 拼一行)——多词标签(Date & Time)拆框后单框谁都不匹配。
3. 点击前闸门 = **期望位置行 OCR 读名**(模糊匹配容忍误读),不是生像素比对——
   选中高亮会重涂整行底色,像素比对 0.15~0.72 全崩;像素匹配降级为点位微调(非闸门)。
4. 落点判定同样要模糊匹配(OCR 把 About 读成 'AboU'、Network 读成 'NelWoTk')。
5. **窗口几何每次 goto 前重钉**(wmctrl 重设)——面板会自己改窗口最小高度(About 撑大
   窗口→底部偏移 623→604、步长 179→183,伺服靠测量自动适应,但光标停靠点需重算)。
6. **app 存活守卫必须在定位之前**——GNOME 42 About 面板偶发崩掉整个 gnome-control-center
   (轮5/7 复现,截图 500 是崩溃伴生症状),崩后 wheel 全落壁纸;探针用 wmctrl 查窗口 +
   detach 重拉恢复(引擎侧即 _ensure_on_app,已有)。
7. localize 置信门要严: 条带匹配 ≥0.75 且 ≥3 条带偏移一致(±3px)——0.6 阈值会被
   弱纹理壁纸假匹配(报出坐标 457 的教训)。
8. 底/顶吸收态时放宽进视口边距(row 在视口边缘也可点),否则底部行永远"差 23px 不可达"。

## 9. 与图/执行的关系(2026-07-02 用户定调,最重要的一节)

**坐标在实机采集时大概率已经变了(几何/动态内容/设备都不同)。图的职责不是存坐标,
而是提供"名字级路线先验"——根据已知图推断"怎样到达并点到功能相关的目标按钮"。
回溯(崩溃后从恢复的主页回到出事页面)与指令执行是同一个原语:**
> route = 图上的路径(当前节点→目标节点),每跳 = (区块, 按钮名字);
> 运行时逐跳"现场解析名字→当下坐标(地图OCR/模板,VLM兜底)→点击→验证落点身份",
> 验证不过 fail-closed(换路/重建图),坐标只作 hint 永不作真值。

Demo 实证(`_scrollmap_sound_demo.py`, ALL PASS): 最大化图的语义地址(Sound页→
Alert Sound区→'Sonar')在 1000x560 小窗里全程零 VLM 兑现——侧栏图过期自动重建
(多了 Appearance 行,+45px),Network 从 OCR 误读 'Nelwork' 受约束模糊认回,
内容区现建图(883px)找到滚动后才可见的 Sonar 并点中(按钮选中态像素变化+仍在 Sound 页)。

**新地雷(引擎接入必带)**: 区域滚动的光标停靠点不能在吃滚轮的控件上——Sound 页
内容区中心是滑块,滚轮被拿去调值,页面根本不滚(map 只有 555px)。对策:停标签列/
留白;或通用检测"滚后 diff 只集中在光标附近=事件被控件吃了→换停靠点"。
现引擎 `_desktop_regional_scroll` 停区中心,同样会踩。

## 10. 引擎接入记录(CHANGE 18,2026-07-02)

Track A 桌面已接入 `visual_engine.py`(flag `GUIWALK_SCROLL_MAP` 默认关;B1 tile分带
真bug修复无flag即时生效)。验收 `_scratch/_test_map_recover.py` **3/3 ALL PASS**:
下半屏goto/点错后靠地图恢复(用户点名场景)/清缓存自动重建。接入期新增两条教训:
- **分区矩形宽度不能用 0.45 分割线当边界**——框进静止内容区会把拼接带偏成残图;
  宽度从节点元素簇 bbox 推导(0.45 只判 side),兜底 0.30 窗宽。VLM 分区(§7/CHANGE 8)
  作为再上一级来源待接。
- **帧断供宽限**:guest server 段错误重启(~10s)会截断建图并吃掉重建机会;
  `_map_settle_crop` 断供最多等 12s+恢复后重置 settle 预算;外加残图检测
  (目标在下半屏但图高<视口+40 → 再建一次)。
Track B 移动端(B2-B5)未做,见计划。

**§10.1 seg-first 定稿(2026-07-02 深夜,run8 3/3)**:几何来源候选链=
**VLM 分区第一**(用户架构方向)→ 元素簇 bbox → 分数兜底;裁决=名字解析+行OCR闸门。
seg 可靠化的两处结构修复:①**输入喂窗口裁剪**(dock 幻觉消失;app 崩→裁剪退化→零分区=
天然拒绝,壁纸分区问题从输入端根除);②**seg 只管列切分(x0/x1),纵向统一窗口带**
(滚动面板纵向必然贯穿窗口;信 seg 的 y 曾把最后一行 About 在图底切成半行)。
勘误:早前"seg 方差大"的证据大部分被 About 崩溃污染(seg 当时在给壁纸分区),
唯一干净失败(run4 1002px 图)根因即 ②。

## 11. 图路由器:最短路径回到目标按钮(2026-07-03 grilling 定稿,用户逐条拍板)

> 用户终局要求:"探索/采集都要能根据已知信息(遍历图),按最短路径到目标按钮"。
> 回溯与阶段4指令执行是同一原语,共用同一份图数据。

**Q1 优化目标**:遍历图上**跳数最短**(附带:失败点最少→轨迹最干净)。
平局裁决:边的实测成功率;**采集模式**额外偏好前向点击边(轨迹更像人类操作)。

**Q2 边模型(用户给出的统一形态)**:基本边 = **按钮 → 节点**。
按钮属于区块,区块属于≥1个节点;**节点出边 = 其全部区块内已知按钮边的并集**。
- 桌面:导航区被 ~20 节点共享 ⇒ 一条 "Sound"→Sound 边全体继承,图天然稠密非树;
- 模态:由入口按钮(如 New Profile)的普通边到达,无特例;
- 移动端:区块≈整页,退化为纯 按钮→状态 = 现有遍历图本身。
目标寻址 = (节点, 区块, 按钮名);最后一跳是区块内动作(CHANGE 18 原语)。

**Q4 硬件 BACK/ESC**:虚拟按钮 `__BACK__`,但**不存无条件边**,三层:
①默认规则=逆活栈(current_path)最后一跳(搜索进入 vs 按钮进入自然区分);
②**条件例外边**=仅当实测违反规则时记 `(节点,栈前驱)--BACK-->实测落点`,规划时优先;
③每跳落点验证(registry identify)兜一切。守规则的 BACK 不产生存储。

**Q5 dest 语义**:一对多(观测到的目的节点集+capability 挂载);规划用最常见 dest;
未点过的按钮无边(探索是 BFS 的职责);**崩溃绝不产边/节点**(现有 focus-guard 铁律:
off-app 不记边不注册;延迟崩溃不回溯污染已验证的边),崩溃计入按钮失败统计(平局用)。

**Q6 接管结构(主干方案)**:
```
0. identify(当前帧)→当前节点; 认不出→BACK×1 再试→硬重置(~20s)
1. "已在目标"短路(保留)
2. 图路由 BFS(当前→目标) 逐跳执行:
     按钮跳 = CHANGE 18 原语(区块内名字解析+闸门+点击)
     BACK 跳 = 逆活栈规则+条件例外
     每跳 identify 验证; 走偏→从实际节点重规划(预算≤3)
3. 无路/超限 → 硬重置 + 从 root 路由(旧 Tier2 "重放 action_path" 被吸收:
   action_path 本就是图上 root→目标的一条路,路由器找到它或更短的)
旧 Tier0(盲BACK爬)/Tier1(VLM找返回控件)不再独立:前者=BACK跳特例,
后者产出的返回控件改记为按钮边喂图。成败均回写边统计。
```

**Q7 持久化**:节点↔区块归属、区块按钮表(名字→dest集+成功/崩溃统计+capability)、
条件例外边——**全部并入图 JSON**(新增 regions 段),schema 一步到位。
动机(用户):阶段4采集就按"载图→最短路径"导航,与回溯同数据同原语。

**Q8 当前范围**:平台无关 `visual_router.py` 由 Engine 始终构造，桌面/移动共用；
`GUIWALK_GRAPH_ROUTER` 旧 flag 与 off-path 已删除，`VisualBacktracker` 源文件也已在 2026-07-10 删除。
**M1**=遍历内回溯(验收三段:Applications子页→Sound 二跳路由/中途点歪重规划/中途崩溃
重置后 root 路由);**M2**=未来视觉采集执行器复用图路由;
移动端各里程碑冒烟(deploy-asr),不单开轨道。

**入场门禁(用户确认的两大担忧,升格为 M1 前置)**:
- **G1 身份反转**(=任务#43):按钮集/内容签名当主判,pHash/SSIM 降为候选门;
  验收加"身份混淆探针"(图内全节点截图互跑 identify,零高置信误认)。
  同布局异功能页误并是路由器最大单点风险(js1 实录 settings 缩成3节点)。
- **G2 区块数据轮**:开区块标注(窗口裁剪版 seg)跑本地 settings 遍历,
  产出 节点↔区块↔按钮 数据;验收=侧栏在≥90%节点认成同一区块+按钮表覆盖率。
  (区块标注现锁在 region_dedup 开关后,生产未开——无此数据路由器无图可路。)
滚动侧不设门禁(fail-closed+重规划容错),B2/B5桌面 与 M1 同批,B4/B5移动 排移动冒烟前;
每类跳成功率进日志,低于阈值亮灯。

**遗留优化(接入时做)**: 每步 SCROLL 的 guest 侧固定 2s sleep 占了 goto 时间大头,
引擎接入应换 settle-wait 轮询;伺服可用"测得的步长(179px/3格)一跳到位再微调"减少步数。
产物: `_scrollmap_long.png`(侧栏长图)/`_scrollmap_annotated.png`(目标标注)/
`_scrollmap_run1..8.log`(迭代全记录)。

## 12. G2 区块去重:第一步删 visited + 按钮身份方案定稿(2026-07-03,用户逐轮拍板)

### 12.1 G2 根因(区块认识 ≠ 按钮探过)
`_regional_scroll_dedup` 判"区块已知(shared)"后把区块内**所有当前可见按钮**盖 `visited=True`
(visual_engine.py:1031-1032 旧代码)→ 把"见过这个区块"错当"区块里按钮都点过了"→
新面板侧栏的新按钮(Display/Sound/Power)连坐 → BFS 饿死 → settings 缩成 3 节点。

关键区分(多轮确认):
- 挡"重复滚动旧区块"的是同分支的 `continue`(:1036),**不是** visited。
- 按钮探没探,本该由**下游按钮级去重**(`_actionable_elements` :2573-2602:shared/chrome 全局
  name 去重,普通行 per-`(state,name)`)决定,而非"区块一认识就一刀切盖章"。

### 12.2 第一步(已落地):删 visited
删 :1031-1032 两行,**保留 `continue`**。旧区块 → 不重滚(continue),但可见按钮流入下游
按钮级去重:探过的按名字跳、没探的照常入队。
- **不重复滚动**:continue 兜底。
- **不重复点击(收敛后)**:shared 按钮进 `common_buttons`(≥4节点且≥50%,visual_state.py:446)
  后走全局 name 去重;早期几次有界重复(点的是真功能页,和普通按钮收敛行为一致)。

### 12.3 按钮去重身份(第二步定稿目标)
现状两套身份都脆:
- `uid`(visual_state.py:92-128)= 归一化外观 pHash。**不含绝对位置**(D16 已去),但脆在:
  ①**外观撞车**——无文字图标按钮同款 pHash 相同 → 误合并;②**外观漂移**——同按钮换状态
  (toggle 关灰/开蓝、选中高亮)→ pHash 变 → 误分裂;③`occurrence` 序号在同屏多同款时随滚动重编。
- `name`(全局 chrome/shared → 纯 name;否则 per-state)。全局纯 name 有**同名不同区块冲突**
  (office 菜单 Insert/Options 等高频词)。

**定稿方案** = `region_id + (name 优先 / 无名图标退外观 pHash)`,全部 **region-scoped**,
用现成 `region_registry.clicked` 账本(region_registry.py:101-112,天然 `region_id::button` 粒度):
- 文本按钮 → `region_id + name`:name 不随状态漂(治 uid 漂移),region 隔离(治同名冲突);
- 图标按钮 → `region_id + 外观 pHash`:region 把撞车面从全局缩到同区块内;
- 一次解决 uid 撞车、uid 漂移、同名冲突、早期重复点四件事。
**前置**:region_id 需先稳(区块残缺/污染修好),否则拿漂移 id 做 key 反而重复探 → 归第二步。

### 12.4 蓝牙式状态门控页(边界记录,非 bug)
关(仅文字/toggle)↔ 开(设备列表/配对)= **两个 state,由 toggle 边连**,符合节点-区块-边,
是正确图。探索链已查实:toggle 不在 DANGER_WORDS(visual_perception.py:29-33,仅关机/格式化类),
`category=dangerous` 引擎层不硬过滤(仅 explorer prompt 提示行),explorer prompt 允许点
"可逆、可揭示子页"的元素(visual_agents.py:330-335)→ 大概率会点 → 开态作新 state 探索。
真实边界:①点不点是 explorer 软决策(不确定);②纯文字关态若 toggle 漏检 → candidates 空 →
done 成叶子 → 开态永不可达;③toggle 关→开 uid 漂移(=12.3 病②,指向第二步身份方案)。

### 两步分工小结
第一步(现在)= 删 visited 解饿死;第二步 = `region_id::button` 账本(等 region 稳)顺带治
uid 脆弱 / 同名冲突 / 早期重复。
