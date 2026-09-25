# 瑙嗚涓诲閬嶅巻妯″潡 (visual_traversal)

## 鍔熻兘璇存槑

褰撳墠瑙嗚涓诲閬嶅巻锛氳緭鍏ョ函鎴浘锛岀敤 VLM + OmniParser 璇嗗埆骞跺懡鍚嶆寜閽紝
浠?region-set/椤甸潰璇箟璇嗗埆绋冲畾 Page銆佷互鍙瀵熶簨瀹炲尯鍒?Variant锛屽湪鐧昏鑺傜偣鏃跺湪绾跨敓鎴?portable `discovered` 鑳藉姏锛屽疄鏃堕噸瀹氫綅鍚庢墽琛屽儚绱?閿洏鍔ㄤ綔锛?*鍏ㄧ▼涓嶄緷璧?A11y 鏍?*銆?
杩欐槸褰撳墠鍞竴鐨勫浘閬嶅巻杩愯鏃讹紝鍏变韩绾瑙?`StateGraph` 鍜?`app_lifecycle.py`銆傛棫 UI-tree traversal 宸蹭簬 2026-07-10 閫€褰广€?
## 璁捐鍔ㄦ満

鏃╂湡瀹炵幇渚濊禆 UI tree锛屾棤娉曠ǔ瀹氳鐩栨棤鍚嶇О鍥炬爣銆佸姩鎬佸唴瀹逛笌妯℃€佽〃闈€?褰撳墠瀹炵幇浠ユ埅鍥句腑鐨勫彲瑙佽瘉鎹綔涓哄敮涓€韬唤銆乬rounding 鍜岄獙鏀舵潵婧愩€?
## 鏂囦欢缁撴瀯

```
src/core/visual_traversal/
├── __init__.py             # public traversal exports
├── agents/                 # canonical VLM roles by responsibility
├── grounding/
│   ├── region/
│   │   ├── __init__.py     # public region API exports
│   │   ├── registry.py     # canonical region identity/coverage ledger
│   │   └── scroll.py       # region-aware segmentation/scroll dedup
│   ├── locate.py           # below-fold map/OCR/closed-loop location
│   ├── scroll.py           # viewport scrolling and restore
│   └── stitch.py           # canonical stitching/tiled perception
├── navigation/
│   ├── frontier.py         # executable frontier policy
│   └── router.py           # verified-graph routing
├── prompts/
│   ├── grounding.py        # grounding/review prompts
│   └── navigation.py       # identity/effect/risk prompts
├── visual_perception.py    # screenshot grounding -> VisualElement
├── visual_state.py         # Page/Variant and element identity
├── capability_discovery.py # online portable capability discovery
├── visual_cache.py         # semantic cache and VLM ledger
├── visual_resume.py        # atomic resume rebuild
├── visual_relocate.py      # live visual relocation helpers
├── live_targeting.py       # fresh-frame rebind and click QA
├── visual_filter.py        # candidate filtering
├── visual_engine.py        # traversal orchestrator and compatibility wrappers
├── visual_agents.py        # compatibility shim -> agents/
├── region_registry.py      # compatibility shim -> grounding/region/registry.py
├── visual_router.py        # compatibility shim -> navigation/router.py
├── visual_stitch.py        # compatibility shim -> grounding/stitch.py
└── artifacts.py            # StateGraph-compatible artifact writer

run_visual_traversal.py     # visual traversal CLI
run_visual_calculator.ps1   # launcher
```

## 澶嶇敤鐨勭幇鏈夋帴鍙ｏ紙import-only锛屼笉淇敼锛?
| 鑳藉姏 | 鏉ユ簮 |
|---|---|
| YOLO妫€娴?鍘婚噸鍙?caption | `gui_rewalk.env.utils`: `predict_yolo` / `remove_overlap_new` / `get_parsed_content_icon` / `get_yolo_model` |
| 鐘舵€佸浘 | `StateGraph.add_state/add_transition/save`锛坄state_type="visual"`锛屽師鐢熸敮鎸?`visual_fingerprint`锛墊
| 瑙嗚鍝堝笇 | `StateGraph.compute_visual_state_id`锛坧Hash锛? `compute_visual_fingerprint` |
| SSIM | `gui_rewalk.src.core.reverse.image_ssim_calculator.get_image_ssim` |
| VLM | `GUIGenAgent.predict_mm(prompt, [ndarray])` |
| VM I/O | `DesktopGUIGenEnv.step(action_dict, pause)` / `_get_obs()` / `controller.get_screenshot()` |

## 鍏抽敭璁捐

- **鍛藉悕 = VLM 缁熶竴鍛藉悕**锛氭娴嬫鐢?SoM 缂栧彿 鈫?鏁村浘浜?VLM 鈫?杩斿洖 JSON
  `[{"id","name","type","interactive"}]`锛沄LM 娌¤鐩栧埌鐨勬鐢?Florence-2 caption 鍏滃簳銆?- **鎵ц鍧愭爣鏄灛鏃跺€?*锛歚execute_gui_action` 浠嶆妸褰撳墠甯у疄鏃跺畾浣嶅緱鍒扮殑 `(x,y)` 浜ょ粰 pyautogui/ADB锛涙寔涔?ActionEdge/capability 浼氬墺绂诲潗鏍囧拰 bbox锛屽彧淇濆瓨涓嬩竴鐜鍙噸鏂?grounding 鐨勮涔?selector銆?- **Page/Variant 涓ょ骇韬唤**锛歚state_id` 鏄?Router 鍙墽琛岀殑鍏蜂綋 Page@Variant 鑺傜偣锛涚ǔ瀹?`page_id` 鑱氬悎鍚屼竴璇箟椤甸潰锛宍variant_id` 淇濆瓨绌?闈炵┖銆佸紑/鍏炽€侀€変腑妯″紡绛夊彲瑙傚療鍔熻兘鏉′欢銆傚嚱鏁伴泦鍚堝彉鍖栧彲浠ユ媶鎵ц鑺傜偣/variant锛屼絾涓嶅啀鎶婂悓涓€椤甸潰鍗囩骇涓轰笉鍚?page銆?- **鍦ㄧ嚎鑳藉姏鍙戠幇**锛氭瘡涓柊瑙傚療鍦ㄥ啓 node artifact 鐨勫悓鏃剁敓鎴?`discovered` 鑳藉姏锛涘彧鏈夌湡瀹炲姩浣溿€佹槑纭?target 涓?`landing_verified=True` 鎵嶆檵鍗囦负 `verified`銆?- **鍏冪礌韬唤**锛歚compute_element_uid` = 鍏冪礌鍖哄煙 pHash + 3脳3 缃戞牸 zone锛屾浛浠?a11y `global_uid`銆?- **鍗遍櫓鍏冪礌**锛歏LM category 璐熻矗鍗遍櫓鏈€缁堝姩浣滐紱鏃犳ā鍨嬪畨鍏ㄧ綉鍙瑙勮寖鍖栧悗鐨勭洿鎺ヤ細璇濈粓姝?鎭㈠鍑哄巶鍚嶇О鍋氱簿纭尮閰嶏紝鏅€?Reset/Delete 瀛愰〉鍏ュ彛涓嶈兘琚娉涘瓙涓查潤榛樺壀鎺夈€?- **瀹炴椂鐩爣缁戝畾**锛氬巻鍙插潗鏍囦笉鑳界洿鎺ョ偣鍑伙紱姣忔 pointer action 閮戒粠瀹炴椂甯ф寜 element/region 閲嶆柊瀹氫綅锛岃惤鐐硅秴鍑?region bbox 鏃?fail-closed銆?- **鎭㈠/璺敱**锛氱幇褰?`VisualRouter` 鍙 schema v3 鐨?verified `routing_graph`锛屼娇鐢ㄦ渶灏?hop銆侀€愯烦韬唤鏍稿銆佸亸鑸噸瑙勫垝銆佽涔?BACK 涓庡繀瑕佹椂 hard reset銆傚凡鏈夊浘鍚姩銆乺elaunch 鍜?hard reset 鍙噰鐢ㄥ凡鐧昏钀界偣锛涙湭鐭ラ〉闈㈠仠姝㈡仮澶嶏紝涓嶇櫥璁版垚鏂扮殑璧风偣銆傛棫 `visual_backtrack.py` 宸插垹闄ゃ€?
### 当前帧实时目标边界

`live_targeting.py` 负责点击前的主动 capture、observation 原位更新、实时
grounding、overlay/region 几何门、稳定 UID/state_key 匹配、noninteractive
诊断、最多一次 reviewer 强制刷新以及 stateful 几何回填。
`VisualTraversalEngine._live_center_for()` 仅保留兼容 wrapper；M13
`live_visual_collection.py` 的调用契约不变。该组件显式接收 env、perception
和 reviewer，不依赖或反向导入 `visual_engine.py`。

### 2026-07-16 区块优先的视觉重定位

桌面 region-aware 路径现在为每个已登记区块保留运行时视觉证据：首帧区块裁剪，
以及存在滚动时的长区块 composite。`visual_relocate.match_region_view()` 先用
ORB 局部锚点、RANSAC 相似变换和保守 edge fallback，确认“当前视窗属于这个
区块”；只有通过后，才允许元素的行/邻域 context template 为实时重绑定提供
位置先验。重复的小按钮或图标还必须通过独立峰值 margin，撞车时放弃模板先验。

这条链路不直接点击，也不替代页面身份：`live_targeting.py` 仍然进行当前帧 VLM
grounding、region/overlay 几何门和 reviewer 复核。视觉证据只改变候选的预期位置；
区块不匹配、上下文不唯一或证据缺失时回退到原有 live grounding。视觉数组目前
只存在于进程内，不进入 graph schema、portable capability 或 resume 合同。

### 2026-07-18 元素可稳定区块，但区块不再锚定 Page

现有 grounding 调用现在为元素附带可选 `identity_anchor`。明确为 `false` 的
时间、计数、IP、实例数据和瞬态提示不再进入区块成员身份；`true` 与旧缓存的
`null` 仍按原有 typed member token 参与区块匹配。该过滤只影响区块身份，
interactive action coverage、Router 候选和点击账本不受影响。

Page 身份不再由区块、截图、锚点 token 或观察哈希计算。已知 source + 已执行 action
限定图中邻居候选，VLM 只能选择已有 Page 或明确返回 `NEW`；新 Page 一旦获得
`page_id` 就冻结。后续 revisit 仍可增加元素、Region、observed facts 和 Variant
证据，但不能改变 Page ID。因而 Region 漏检、区块内容变化或语义 inventory 扩充不会
再造成 Page 改名或分裂。

新图不再保存 `page_anchor_tokens`，也不再输出 `hierarchical_page_identity_v1`。
resume 直接安装图中持久化的 `page_id`，加载旧图时只清除遗留 Page-anchor 字段并把
旧版本标记规范为 `semantic_page_variant_v1`，不会根据当前观察重算 Page 身份。
元素 `identity_anchor` 仍可用于过滤区块中的瞬态成员，但它只影响 Region 身份。

随后对 `artifacts/runs/local/20260716/setting` 的四个真实 Settings 节点做了只读
核查：About 得到 `r2/r3/r4`，Bluetooth 得到 `r11 + selected Bluetooth`；Network
因注册前 segmentation 为空而没有锚点，Background 又把共享侧栏 `r1` 错当成身份块。
修订后的投影因此明确排除 `nav_sidebar/sidebar/tab_bar/toolbar/chrome` 等共享
navigation/chrome 整块；它们只能由同一 region 中恰好一个、非 stateful、非
`identity_anchor=false` 的 selected navigation 成员贡献 `selected:<role>:<name>`。
多个 selected（例如 About 与 Displays 同时误标）会 abstain，tab 也只产生这一种
selected token，不再同时生成 `tab_selected`。

分块的 `page_identity` 观察现在以可选 `region_page_identity` 附着到每个元素并随
`to_dict()` 持久化；arrival、scroll、below-fold、retag/heal 都维护该字段。完成滚动
和最终元素合并后，registration 会在首次 graph/state_meta 保存之前从 final elements
重建锚点。这样即使 Network 的早期 segmentation 为空，最终 `r1` 中唯一 selected
Network 仍可把 Page 从语义 fallback 升级成结构身份，而 stateful 的 Wired toggle
不会成为 selected Page 锚点。Registry 只允许空到非空或严格子集到超集的单调丰富，
冲突集合仍保持 first-wins，并同步清理旧 Page reverse mapping。本修订仍需重新运行
真实 Settings 才能确认效果，现有四页 artifact 只证明了修订前的失败模式。

## 2026-07-15 当前代码边界

- `agents/` 按 identity、focus、memory、interruption、review、effects、diagnostics
  划分 VLM agent 角色；`common.py` 只放共享图像/JSON/名称辅助函数。根层
  `visual_agents.py` 仅兼容旧 import。
- `grounding/region/registry.py` 是 region 身份与覆盖账本的唯一实现；
  `grounding/region/scroll.py` 负责 region-aware 分割、稳定与滚动去重；package
  `grounding.region` 继续导出旧公共 API，根层 `region_registry.py` 仅兼容旧 import。
- `grounding/locate.py` 是 below-fold region map、map servo、OCR/name anchor 与
  closed-loop `_scroll_locate` 的唯一实现。`LocateContext` 显式注入 env、perception、
  四项可变状态与五个回调；canonical 模块不反向 import Engine。
- `navigation/router.py` 是 verified graph 路由实现，`navigation/frontier.py`
  是可执行 frontier 策略。Frontier 只接收 `FrontierContext` 中声明的依赖，不反向
  import Engine；Engine 保留薄 wrapper。
- `prompts/grounding.py` 统一拥有 grounding/命名/block/review 提示；
  `prompts/navigation.py` 统一拥有页面身份、焦点、干扰关闭、点击效果和风险提示。
- `tests/` 是离线回归测试目录，`tools/` 只保留正式工具。视觉遍历默认输出到
  `artifacts/runs/`。

本次只移动实现边界与文件位置，不改变 prompt 有效字符串、frontier 判定顺序、Router
行为、graph schema 或 resume 数据合同。离线验证：agent/prompt/frontier/architecture
聚焦套件 21 passed；overlay/stateful/permission/frontier/router/resume 回归 45 passed。
未启动 VM/emulator，未调用真实 VLM，不能据此宣称 live 验收。

四个 canonical grounding 模块各自维护独立功能边界：

- `grounding/scroll.py` 负责一般视口滚动聚合与回顶；
- `grounding/region/scroll.py` 负责 region-aware 分割、稳定和滚动去重；
- `grounding/stitch.py` 负责长图拼接、分块感知和坐标映射；
- `grounding/locate.py` 负责 below-fold region map、OCR/name anchor 与闭环定位。

Engine 通过 `ScrollContext`、`RegionScrollContext`、`StitchContext`、`LocateContext`
显式提供 env/perception/账本回调及兼容 buffer，
不把 Engine 对象传入 canonical 模块；`visual_stitch.py` 只做旧路径 re-export。
本轮未改变滚动阈值、region 语义、prompt、输出 schema 或 CLI 默认值。后续候选只剩
state identity/resume 与 runtime orchestration。

### 2026-07-15 滚动/拼接模块化与过时代码退役

- `visual_engine.py` 从约 6.6k 行降至约 4.6k 行；保留同名 wrapper、旧常量与函数导入。
- 删除无生产调用的 traversal discovery prerequisite hook/cleanup、旧 tabbar 几何吸附、
  旧 overlay 几何 wrapper、元素恢复 wrapper 与未使用 queue helper；M13 prerequisite
  runtime 仍保留。
- 离线验证：聚焦 scroll/stitch/region/architecture/run-state 套件 45 passed；
  `compileall` 通过。未启动 VM、
  emulator 或真实 VLM，不能据此宣称 live 验收。

当前实现不再包含 Engine discovery seed resolver/setup/cleanup 或
`_tabbar_center`。前置条件编排只属于 M13 runtime；tab 点击由当前 region-bound live
targeting 处理。下方带日期的旧记录若仍提及这些符号，只是历史快照，不能覆盖本节现状。

### 2026-07-15 below-fold 定位模块化

- 18 个 map/OCR/below-fold 方法迁入 `grounding/locate.py`；Engine 保留同签名薄
  wrapper，并同步 `_region_maps`、`_map_seg_cache`、`_map_anims_off` 与
  `_last_live_rebind_observation`。
- `SCROLL_MAP_*` 的 canonical 定义迁入 locate，Engine 继续兼容导出且数值不变；
  `ScrollRuntime(map_to_top=self._map_to_top)` seam 保持不变。
- Engine 继续导出 `_reloc` 模块别名，保留旧测试和调用方通过
  `visual_engine._reloc` monkeypatch 像素 relocation helper 的兼容 seam；定位实现仍在
  canonical `grounding/locate.py`。
- `visual_engine.py` 从 3,257 行降至 2,653 行；`grounding/locate.py` 为 788 行，
  其中 `_map_goto`、`_scroll_locate` 的签名、返回值、fail-closed OCR 门与重试语义未改。
- 验证均为本机离线/合成检查：`compileall` 通过；architecture + run-state 为
  32 passed；`test_scroll_locate.py` A-D 与 `test_scroll_waste.py` 均 ALL PASS。
  未运行 VM、真实 VLM 或 live rollout。

## 2026-07-12 褰撳墠濂戠害

### 鎵ц鑺傜偣涓?Page/Variant

`VisualStateRegistry` 浠嶄互 region-set銆佸姛鑳界鍚嶃€乻elected navigation銆侀〉闈㈠悕鍜屽繀瑕佹椂鐨?same-page VLM judge 鍖哄垎鍙墽琛岀姸鎬侊紝浣嗙櫥璁板悗涓烘瘡涓?`state_id` 琛ュ厖涓ょ骇璇箟韬唤锛?
- `page_id` 鐢辩ǔ瀹氶〉闈㈣涔夌敓鎴愶紝鑱氬悎鐩稿悓鑱岃矗鍜屾牳蹇冪粨鏋勭殑椤甸潰锛?- `variant_id` 鐢?`page_id + observed_facts` 鐢熸垚锛屼繚瀛?`states/present_groups/selected_modes` 绛夋埅鍥惧彲瑙傚療鏉′欢锛?- `state_id` 鏄叿浣撴墽琛岃妭鐐癸紝鍙互缁х画淇濈暀涓嶅悓 variant 鐨勬埅鍥俱€佸厓绱犺处鏈拰钀藉湴璺緞銆?
鍥犳 Bluetooth off/on銆丄larm Home empty/has_alarm 浠嶆槸涓や釜鎵ц鑺傜偣锛屼絾鍏变韩涓€涓?`page_id`銆佹嫢鏈変笉鍚?`variant_id`銆侫larm Home銆丄larm Editor 涓?Alarm Detail 鐨勮亴璐ｄ笉鍚岋紝淇濇寔涓嶅悓 page銆備笉鍚屽叿浣撻椆閽熸椂闂寸殑璇︽儏鍙敼鍙樺疄渚嬫暟鎹紝涓嶆媶 page 鎴?variant銆傜己澶辩殑閲嶈椤甸潰鍚嶄笉鑳借鐩栧凡寤虹珛鐨?page mapping銆?

region segmentation 偶尔会给完全相同的页面分配一组全新的 region id。常规 region-set 匹配与 VLM 仲裁均失败后，registry 只对 pHash 完全相同的帧做一次严格恢复：selected navigation 和结构化 state token 必须一致，去除 selected/state/availability 后的原始功能 token overlap 必须至少为 0.78，且功能面判定不能为 `different`。命中时把新 rset 并入既有节点；近似 pHash、不同页签、不同状态或明显不同功能面仍保持独立节点。

移动端列表的 VLM/stitched element bbox 可能覆盖整行甚至相邻行，因此文本 navigation 不再把“历史模板附近存在目标文字”仅作为布尔门后点击大框中心。非图标、非 stateful 文本 navigation 必须在当前帧 fresh 同名 bbox（优先）或可信 sidebar/tab region 中取得唯一 OCR 标签，并直接返回该文字中心；live bbox 越界、零/多命中或 OCR 失败均拒点。below-fold 模板命中同样只提供 OCR 搜索 bbox，不能绕到未经 OCR 唯一确认的 VLM center；compact icon 继续使用自身 bbox 内的局部锚点。
### 鍔熻兘闆嗗悎鐘舵€佹帶浠讹紙搴旂敤鏃犲叧锛?
鐘舵€佹帶浠朵笉鍐嶄粎鎸?`switch/toggle/checkbox` 绫诲瀷涓€鍒€鍒囥€俙VisualElement` 浣跨敤姝ｄ氦瀛楁
`stateful/state_key/state_value/effect_scope/reversible/risk` 鎻忚堪鍏跺綋鍓嶇姸鎬佸拰鍥犳灉浣滅敤锛?
- `effect_scope=data_only` 浠嶆槸鑺傜偣鍐呭彇鍊硷紝涓嶅弬涓?page/variant 韬唤锛涗富棰?棰滆壊銆佹闈㈡垨 shell 鍥炬爣銆丏ock/浠诲姟鏍忔樉闅?浣嶇疆/灏哄/甯冨眬绛夋櫘閫氬瑙傚亸濂介兘灞炰簬璇ョ被锛?- 鍙湁瑙嗚涓婁笅鏂囧叿浣撹瘉鏄庡綋鍓嶇洰鏍?App 鑷韩 UI 鍐呬細鍑虹幇銆侀殣钘忋€佸惎鐢ㄦ垨绂佺敤鍏朵粬浜や簰鎺т欢銆侀潰鏉挎垨瀵艰埅鍏ュ彛锛屼笖缁撴瀯鍖栫粨鏋滀负 `effect_scope=function_set + reversible=true + risk=none + enabled!=false`銆佹病鏈?permission/login gate锛屾墠榛樿杩涘叆鍙楁帶鎺㈢储锛涙櫘閫氬儚绱犲彉鍖栥€佸彲閫嗘€ф湰韬垨涓嶇‘瀹氬悗鏋滈兘涓嶈冻浠ユ帹鏂姛鑳介泦鍚堝彉鍖栵紱
- `signature_names()` 涓?observed facts 涓?`function_set` 淇濈暀鐘舵€佸€硷紝浣夸笉鍚屽姛鑳藉彲杈剧姸鎬佺櫥璁颁负鍚?page 涓嬬殑涓嶅悓 variant锛涙櫘閫氭暟鎹€间笉杩涘叆韬唤锛?- 鍏ㄥ眬鍙褰曞垎鏀拰鐜鍥為€€鑳藉姏浠嶅畬鏁翠繚鐣欙紝浣嗛粯璁ゅ叧闂紱鏄惧紡璁剧疆 `GUIWALK_STATEFUL_DISCOVER_ONLY=1` 鏃讹紝鎵€鏈夊悎鏍肩姸鎬佹帶浠跺彧鐧昏 capability 鑰屼笉鐐瑰嚮銆傛甯搁粯璁よ矾寰勫湪姣忔棣栨 probe 鍓嶅彟鐢?`StatefulRiskGuard` 鐪嬫暣椤靛拰鎵ц鐜鍋氱嫭绔嬪洜鏋滈闄╄鍐炽€傝鍐虫寜鈥滄槸鍚︿細鐮村潖 automation transport/control channel銆佷細璇濄€佹暟鎹€佽处鎴?璁よ瘉/鏉冮檺/瀹夊叏杈圭晫鎴栦骇鐢熶笉鍙€嗗閮ㄦ晥鏋溾€濆垽鏂紝涓嶄娇鐢ㄥ叿浣?app/page/control 鍚嶇О鐧藉悕鍗曪紱璋冪敤澶辫触銆佺粨鏋滀笉鍙В鏋愭垨鍚庢灉涓嶇‘瀹氬潎鎷掔粷锛?- Engine 鍚屾椂鍙睍寮€涓€涓姸鎬佽酱锛涢粯璁ゆ瘡鑺傜偣鏈€澶?2 涓€佸叏灞€鏈€澶?20 涓?probe锛屽苟涓洪€嗘搷浣滈鐣欐渶鍚庝竴涓?GUI action銆傜姸鎬佽酱婵€娲绘椂鏆傜紦鍏变韩 sidebar/tab 鍜屽叾浠栫嫭绔嬬姸鎬佽酱锛屽厛鎺㈢储鏂版毚闇茬殑鍐呭鍖哄姛鑳斤紝鍐嶅疄鏃堕噸缁戝悓 `state_key` 鐨勯€嗘帶浠讹紱
- probe 涓?restore 閮藉繀椤绘槸瀹為檯 GUI 鍔ㄤ綔骞惰繘鍏ュ悓涓€ `mutation_id` 鐨?ActionEdge attempts锛屾垚鍔熻竟鏍?`transition_kind=stateful_surface`銆侽FF鈫扥N 涓嶈兘鎺ㄦ柇鍑?ON鈫扥FF锛涘彧鏈夊疄闄呴€嗘搷浣溿€佺姸鎬佺炕杞拰钀藉湴楠屾敹鎴愬姛鎵嶆竻闄?mutation锛?- no-effect銆侀敊椤点€佺 app 鎴栨棤娉曟仮澶嶄笉鍐欐垚鍔熻竟銆備袱娆＄‘瀹氭€?no-effect 璁颁负 `stateful_no_effect` 缁堟€侊紱閬嶅巻缁撴潫浠嶆湁 open mutation 鏃?`stop_reason=state_restore_failed`銆俽esume 浼氱敱 probe/restore 閰嶅鎭㈠鏈棴鍚?mutation锛汫raphQuality 灏嗘湭鎭㈠ probe 鎶ヤ负 ERROR銆?
杩欏绛栫暐鐨勫垽鏂璞℃槸鈥滃姛鑳藉彲杈鹃泦鍚堜笌鍔ㄤ綔鍚庢灉鈥濓紝涓嶆槸 Settings 鎴栨煇涓紑鍏炽€傛闈㈢鍜岀Щ鍔ㄧ鍏变韩鍚屼竴瀛楁銆侀闄╅棬銆佷簨鍔¤处鏈拰鐘舵€佽韩浠借鍒欍€?
2026-07-13 鐨勫彈鎺ц瘉鎹垎涓夊眰锛歡uest HTTP 鐪熷疄鎴浘纭 Ubuntu Settings 鈫?Appearance 褰撳墠鍙鐨勪釜浜烘枃浠跺す銆丏ock 鑷姩闅愯棌鍜岄潰鏉垮竷灞€寮€鍏抽兘鍙敼鍙樺瑙?甯冨眬锛屽洜姝ゅ綋杞?0 鐐瑰嚮锛涙棫鎻愮ず鍦ㄤ繚瀛樼殑 live 鎴浘涓婅皟鐢ㄧ湡瀹?VLM 鏃舵妸涓夎€呰鍒や负鍔熻兘鎵╁睍锛屽眬閮ㄦ敹绱?SoM naming 涓?direct grounding 鐨勫悓涓€搴旂敤鍐呬氦浜掑叆鍙ｈ竟鐣屽悗锛屽悓鍥剧湡瀹?VLM 澶嶆祴涓夎€呭潎涓?`data_only + shallow`銆傝繖璇佹槑鍒嗙被鎻愮ず宸茬籂姝ｈ鎴浘鐨?skip 缁撴灉锛屼絾娌℃湁缁忚繃 probe/restore銆丄ctionEdge銆乵utation 鎴?variant live 楠屾敹锛屼笉鑳藉鎺ㄤ负瀹屾暣鐘舵€佷簨鍔¤璇併€?
### 鍙敤鎬с€佹潈闄愪笌 active surface

`VisualElement` 的 `enabled: true|false|null`、`requires_permission` 和 canonical `blocked_reason` 是可执行 frontier 的前置门。明确 disabled 或授权/登录 gate 保留在 node artifact，并由 Engine 以 `disabled/permission_blocked` 写入 terminal abnormal ledger，不进入确定性调度。唯一自动例外同时要求 `enabled=true`、`requires_permission=true`、`blocked_reason=system_settings_unlock`、`category=navigation` 与 button/link；该判断不读取按钮名称。应用登录及未知 permission context 不自动点击。
active surface 缁熶竴鍒嗕负 `page/dialog/popup_menu`銆傚簲鐢ㄥ唴瀵硅瘽妗嗐€乨ropdown銆乷verflow/context menu 鍜岄€夐」 popup 閮戒細鍋滅敤鑳屾櫙锛涘叾 active elements 瑕佹眰 bbox 鑷冲皯 80% 钀藉湪 `active_surface`锛屼粎涓績鐐硅惤鍏ャ€佷富浣撲粛灞炰簬鑳屾櫙/sidebar/list 鐨勬浼氳鍓旈櫎锛屼笉鑳芥薄鏌撳嚱鏁扮鍚嶆垨鍊欓€夈€傛瘡涓繚鐣欏厓绱犲悓鏃跺啓 `surface_kind/surface_bbox_xywh/surface_scrollable` sidecar銆?
overlay-bound 鍏冪礌鐐瑰嚮绂佺敤 OCR/template 蹇嵎鍛戒腑锛屽繀椤诲厛涓诲姩 capture 鏈€鏂?observation 鍐嶉噸鏂?grounding锛氫粛鏄悓绫?overlay銆乴ive surface 涓庤褰?bbox 鑷冲皯鏈?60% 灏忔閲嶅彔銆佸€欓€?bbox 浠嶄綅浜?live surface锛屼笁椤归兘婊¤冻鎵嶈繑鍥炵偣鍑讳腑蹇冦€傜敓浜х幆澧冩棤娉曞彇寰?fresh screenshot 鏃剁洿鎺ユ嫆鐐广€傚洜姝?Android 鎺掑簭 popup 娑堝け鍚庯紝鑳屾櫙椤典粛鏄剧ず鐨勫綋鍓嶆帓搴忔爣绛惧拰搴旂敤鍒楄〃琛岄兘涓嶈兘鍐掑厖 popup option銆倀ab-bar segment 鍚搁檮浠嶅彧鍏佽鏄惧紡 `region=tab_bar` 鐨勫悓 region peers锛屾渶缁堢偣蹇呴』浠嶅湪璇?region bbox銆?

中断清理的 `force_first` 只表示启动首帧也会询问，并不直接授权点击。`InterruptionDismisser` 只有在模型结构化输出同时严格给出 `surface_is_temporary=true` 与 `target_is_close_control=true` 时才返回按钮；旧格式、异常、缺字段、不确定判断，以及正常页面 CTA 或通知正文均 no-op。该守卫不按控件名、应用名或 UI 类型猜测关闭按钮。修复前 js1 Clocks/Settings 的 CTA 与通知正文误点只作为故障证据；当前仅通过离线 guard/modal/popup/architecture 回归，尚无修复后 live 结论。
### 鍦ㄧ嚎 capability lifecycle

鏂拌瀵熷畬鎴?grounding銆丳age/Variant 鐧昏鍚庯紝`discover_capabilities()` 浠庡綋鍓嶅彲浜や簰鍏冪礌鐩存帴鐢熸垚 portable 鍊欓€夛細

- 鍚屼竴 `page_id + semantic_key` 浣跨敤绋冲畾 capability id锛?- `available_when` 璁板綍鍙 variant 涓?observed facts锛涘悓涓€ page 鐨勫 variant 璇佹嵁澧為噺鍚堝苟锛?- recipe 鍙惈鍔ㄤ綔绫诲瀷銆佸厓绱?label/type銆乺egion/group 鍜岃繍琛屾椂鍙傛暟妲斤紱鎴浘璺緞銆佸潗鏍囧拰 bbox 涓嶈繘鍏ヤ究鎼哄绾︼紱
- drag/slider 鑻ユ病鏈夎涔夌洰鏍囷紝涓嶇敤鍘嗗彶璧风粓鐐逛吉閫犲彲鎵ц recipe锛?- 瑙傚療鍙兘寰楀埌 `discovered`锛涚湡瀹炲姩浣?鏄庣‘ target+`landing_verified=True` 鎵嶈ˉ action edge/effect/target 骞舵檵鍗?`verified`銆?
### ActionEdge attempts 涓庣鍦虹粓鎬?
鐪熷疄 CLICK 鍦ㄨ皟鐢?`env.step` **涔嬪墠**鍏堣皟鐢ㄥ吋瀹瑰悕 `record_action_event()`锛屾妸 `outcome=attempted` 鐨?attempt 杩藉姞鍒拌涔?`ActionEdge.attempts[]`锛涚幆澧冭繑鍥炲悗鏇存柊涓?`executed`锛宖ocus/effect/landing 缁х画鏇存柊鍚屼竴 attempt銆傝嫢 `env.step` 鎶涢敊锛屽悓涓€ attempt 鏇存柊涓?`execution_error`銆乣landing_verified=false`銆傝繖鏍峰嵆浣垮悗绔湪閫佽揪鐐瑰嚮鍚庢墠鎶涢敊锛岀湡瀹炴搷浣滀篃涓嶄細浠庤处鏈秷澶便€俙graph.json` 涓嶅啀鎸佷箙鍖栭《灞?`transition_events`锛岃灞炴€у彧鏄粠 attempts 鐢熸垚鐨勫彧璇诲唴瀛樺吋瀹硅鍥俱€?
鍙湁 committed銆乣landing_verified=True` 涓?outcome 鍙矾鐢辩殑 attempt 鎵嶄护 ActionEdge 鎴愪负 `routing_verified`锛屽苟杩涘叆 Router 鐨勬淳鐢?`routing_graph`銆俙external_app`銆乣app_crash`銆乶o-effect銆佷覆椤甸殧绂汇€乸ermission gate 鍜屾劅鐭ュけ璐ヤ繚鐣?attempt/寮傚父璇佹嵁锛屼絾涓嶅啓 verified route锛屼篃涓嶆檵鍗?capability銆?
涓ゆ澶辫触鍙細鎶婂綋鍓嶈妭鐐瑰€欓€夐€€浼戯紝涓嶄細鎶婂け璐ヤ吉瑁呬负鎴愬姛瑕嗙洊銆傚畬鎴愯瘉涔﹀彲鎺ュ彈鐨?terminal abnormal reason 浠呬负 `disabled`銆乣permission_blocked`銆乣blocked`銆乣no_effect`銆乣stateful_no_effect`銆乣stateful_risk_blocked`銆乣external_app`/`external_app_*` 鍜?`app_crash`/`app_crash_*`銆傞噸缁戝け璐ャ€佹墽琛屽け璐ャ€侀獙鏀跺け璐ャ€乣stateful_verification_failed`銆乣uncertain` 鎴?`transitioned_inconsistent` 閮藉繀椤讳繚鎸佹湭瑙ｅ喅锛屽洜姝ゅ嵆浣胯皟搴﹀眰宸插皢鍏冪礌鏍囦负 visited锛屼篃涓嶈兘棰佸彂瀹屾垚璇佷功銆?
### scroll_ledger 涓?resume 琛ュ

Engine 鍦ㄦ粴鍔ㄨ仛鍚?鍖哄煙瀹¤鏃跺悓姝ュ啓 `StateGraph.scroll_ledger`銆傞〉绾?scope 涓?`state:<state_id>:page`锛岀ǔ瀹氭闈㈠尯鍧?scope 涓?`region:<region_id>`锛涜褰?`classification/termination/bottom_reached/top_restored/steps/max_steps/detail/observations/complete` 鍜屾墍瑕嗙洊鐨?`state_ids`銆?
- static surface 蹇呴』浠?`static`/`viewport_stable` 缁撴潫骞跺洖鍒?canonical top锛?- touch 涓婄煭涓?`surface_scrollable!=true` 鐨?`popup_menu` 涓嶆墽琛?swipe/stitch锛岀洿鎺ヤ互 `static/static/steps=0/top_restored=true` 璁板綍锛涚揣鍑?legacy modal 涔熶娇鐢ㄥ悓涓€淇濆畧闂紝閬垮厤婊氬姩浜嬩欢绌块€?鍏抽棴娴眰鍚庢妸鑳屾櫙鍒楄〃骞跺叆 popup锛?- scrollable surface 蹇呴』鐪熷疄鍒拌揪 bottom銆佷互绋冲畾杈圭晫缁撴潫骞跺洖鍒?top锛?- hard cap銆乪rror銆乷ff-app銆乥udget銆乼imeout 鍜屾湭鐭ョ粓姝㈤兘淇濈暀涓轰笉瀹屾暣璇佹嵁锛?- 褰撳墠椤靛€欓€変负绌恒€佷篃娌℃湁涓嬩竴鍙矾鐢辫妭鐐广€佸噯澶囩粨鏉熸椂锛岃嫢宸叉湁鏈畬鎴?scope 鐨?`observations=1`锛屽鐢ㄥ悓涓€ register/revisit 璺緞琛ュ涓€娆★紱琛ュ鍚庝粛涓嶅畬鏁村氨浠?`scroll_incomplete` 鍋滄锛屼笉鍐嶉噸璇曪紱
- 宸叉湁鑺傜偣閲嶈鏃讹紝绉诲姩绔彧鍦ㄩ〉绾?scope 缂哄け/鏈畬鎴愭椂閲嶆柊鑱氬悎锛涙闈㈠叡浜?region 鍙鐢?`complete=true` 鐨勮瘉鎹紝缂哄け/鏈畬鎴愮殑 region 浼氶噸鏂版粴鍔ㄨˉ瀹°€?
鍥犳 scroll 灏鹃儴琚绠楁埅鏂悗鍙互鐢?`--resume` 淇鍘熷浘锛岃€屼笉鏄洜涓鸿妭鐐瑰凡缁忔敞鍐屽氨姘镐箙璺宠繃锛涘凡瀹屾垚鍏变韩 region 涔熶笉浼氳鍚庣画 reuse 璁板綍闄嶇骇銆?
### Android/touch 闀垮浘鐨勭郴缁熸爮杈圭晫

Android 鐘舵€佹爮鍜?gesture/navigation 鏍忔槸鍥哄畾骞冲彴鍑犱綍锛屼絾鍏跺儚绱犱細鍥犳椂閽熴€佷俊鍙枫€佺數姹犲拰鎵嬪娍鎻愮ず鍔ㄧ敾鑰岄€愬抚鍙樺寲銆俙_build_stitched_node()` 鐜板湪鎶婃劅鐭ュ眰鐨勫浐瀹?top/bottom band 鎹㈢畻鎴愭簮甯у儚绱犻珮骞朵紶缁?`visual_stitch.stitch_frames()`銆傚畠浠槸 sticky 楂樺害涓嬮檺锛氱郴缁熷甫鏈韩鍙繚鐣欓《/搴曚竴浠斤紝鍚屾椂鍍忕礌鎺ㄦ柇鍙粠璇ヤ笅闄愬唴渚х户缁墿灞曞埌绋冲畾 app toolbar锛屼笉浼氭妸 app chrome 绛夊悓浜?system UI銆?
`StitchResult` 淇濆瓨鐙珛鐨?`system_top_h/system_bot_h` 鍙婂師鏈?`y_map`銆傜煭 composite 鍜?tiled composite 閮藉湪鍏冪礌鍧愭爣鎶洖鍚庢煡 `composite_y -> (frame, in_frame_y)`锛涗换浣曟簮琛岃惤鍦ㄥ浐瀹氱郴缁熷甫鐨勫厓绱犻兘琚嫆缁濄€傝繖鏄?middle tile 鐨勯槻寰℃€ч棬绂侊細瀹冧笉鍐嶄粎渚濊禆鈥滅郴缁熸爮搴旇鍙湪 composite 澶栫紭鈥濈殑鍋囪锛屽嵆浣垮潖闀垮浘鍦?seam 娈嬬暀 pill/鏃堕挓锛屼篃涓嶄細鐢熸垚 app element銆乧apability 鎴?frontier銆俙stitch_frames()` 鏂板弬鏁伴粯璁や负 0锛岄潪 touch 璋冪敤淇濇寔鏃х殑鍍忕礌 sticky 鎺ㄦ柇銆?
绂荤嚎鍚堟垚楠岃瘉锛歚python -B tests/test_visual_stitch.py` 鍚屾椂瑕嗙洊鏃ф嫾鎺?tiny-overlap銆? 甯ф瘡甯т笉鍚岀殑 Android 绯荤粺鏍忓幓閲嶏紝浠ュ強鏁呮剰鎶婁笁甯х郴缁熸爮鐣欏湪涓棿 seam 鐨?tiled provenance 鍥炲綊锛岀粨鏋?PASS锛沗python -B tests/test_stitch_node_integration.py` PASS锛岃鐩栫幇褰瑰己鍒?arrival grounding 鍚庣殑鍗曟 short-composite naming锛屼互鍙?5376px 闀垮浘鐨?2-tile merge/鍧愭爣鍥炴槧锛沗test_system_ui_band.py`銆乣test_architecture_boundaries.py` 涓庣浉鍏?`py_compile` 閫氳繃銆傛湭鍚姩 emulator锛屾湭璋冪敤鐪熷疄 VLM锛屼笉灞炰簬 live 楠屾敹銆?
### fail-closed 瀹屾垚璇佷功

`traversal_completion.py` 鍙鍙栨寔涔?schema v3 璇佹嵁锛屽叓椤规鏌ュ叏閮ㄩ€氳繃鎵嶈繑鍥?`status=certified`锛歚schema_materials`銆乣frontier_exhaustion`銆乣scroll_exhaustion`銆乣control_coverage`銆乣state_restoration`銆乣page_variant_consistency`銆乣routing_reachability`銆乣capability_integrity`銆傛帶浠惰鐩栧繀椤昏兘褰掑洜鍒?verified attempt銆佺櫧鍚嶅崟 terminal abnormal銆乻elected/back銆佸悎鏍煎悓鏋?group 浠ｈ〃锛屾垨闈?navigation/stateful 鎺т欢鐨?grounded inventory capability锛沗visited=true` 鏈韩涓嶆槸鎵ц鎴栫粓鎬佽瘉鎹€俷avigation 鍚屾瀯缁勫彧鏈夌湡瀹?`verified_attempt` 浠ｈ〃鑳借鐩栧弬鏁板寲 aliases锛沘bnormal/no-effect 浠ｈ〃鍙€€浼戣嚜韬紝涓嶈兘鎺╃洊浠嶆湭鎵ц鐨勫厔寮熷鑸」銆?
`stop_reason=frontier_empty` 鍙弧瓒?`frontier_exhaustion` 涓€椤癸紝**涓嶇瓑浜庡畬鏁存帰绱?*銆傛甯歌繑鍥炵殑 CLI 鏃犺鏄惁甯?`--require_complete` 閮藉師瀛愬啓 `<output_root>/completion.json`锛涘甫璇ュ弬鏁版椂鍙湁璇佷功涓?`certified` 鎵嶈繑鍥炴垚鍔燂紝鍚﹀垯閫€鍑虹爜 3銆俙GraphQualityAgent` 宓屽叆鍚屼竴涓?evaluator锛宨ncomplete 浜х敓 graph-level ERROR锛沗tools/live_status.py` 涔熷鐢ㄥ畠锛屽彧鏈?certified 鎵嶆樉绀衡€滈亶鍘嗗凡瀹屾垚鈥濄€備笁澶勪笉鍐嶇淮鎶ゅ悇鑷紓绉荤殑瀹屾垚瀹氫箟銆?
璇佷功鐨勯檺瀹?scope 鏄細**褰撳墠 app/鐜 fixture 涓紝鍦ㄥ綋鍓嶈瑙夋劅鐭ヤ笌瀹夊叏绛栫暐涓嬪凡缁忓彂鐜颁笖鍙揪鐨勫姛鑳借〃闈?*銆傚畠涓嶈瘉鏄庝粠鏈嚭鐜板湪鎰熺煡缁撴灉涓殑鍔熻兘涓嶅瓨鍦紝涔熶笉瑕嗙洊瀹夊叏绛栫暐鎷掔粷鐨勫嵄闄╂搷浣滐紝涓嶈兘澶栨帹鍒板彟涓€鏉冮檺銆佽处鎴枫€佺‖浠躲€佹暟鎹姸鎬併€乴ocale銆佸簲鐢?OS 鐗堟湰銆傛闈?Settings 涓庣Щ鍔?Settings 鐨勨€滃畬鏁粹€濋兘蹇呴』鐩稿浜庢槑纭?fixture/matrix 闄堣堪銆?
### Shared peer navigation and harvested returns (2026-07-17)

- Selected/current navigation supplies page/target evidence only; it no longer
  writes shared Region click coverage.
- Region/global coverage may suppress repeated host-relative work, but an
  explicit tab/sidebar peer remains in a source frontier until that source owns
  a verified direct edge.
- A unique peer target can be inferred from a selected or verified occurrence.
  Router performs the real click, verifies the landing, and persists the local
  edge; top-app-bar and overflow destinations remain pending.
- Successful Back ascent is persisted as `return` or `dismiss_overlay` and is
  replayed with the Back primitive. Map-guided semantic identity still accepts
  only `direct_verified`, never `peer_inferred`, as direct expectation evidence.
- Verification was focused offline only: Router/frontier/map-guided contracts
  `36 passed`; adjacent run-state contracts `19 passed`; targeted `py_compile`
  exit 0. No Clock VM/VLM traversal was rerun in this change.

### capability-driven frontier

閬嶅巻 CLI 宸茬Щ闄?discovery prerequisite 寮€鍏冲拰榛樿 resolver銆侰reate/Add銆佸～鍐欍€佷繚瀛樸€佹墦寮€鏉＄洰閮芥槸鏅€?frontier 鍔ㄤ綔锛屼腑闂?Page/Variant 閫愬抚鐧昏锛涢亶鍘嗛樁娈典笉鏋勯€犫€滆嫢娌℃湁闂归挓鍒欏厛鍒涘缓鈥濈殑棰嗗煙鍒嗘敮銆侻13 浠嶅彲鍦ㄥ悗缁兘鍔涚粍鍚?閲囬泦闃舵浣跨敤鐙珛 prerequisite runtime銆?
覆盖账本决定候选是否完成；Engine 不再调用 Explorer chooser。过滤后只有明确 `category=navigation|nav` 的未执行元素进入 executable frontier，并按感知与账本的稳定顺序确定性选择首项。`shallow/display/dangerous` 以及分类缺失或未知的元素只保留为 inventory，不能因 button/link/tab/menu/row 等 UI 类型或 stateful 字段重新升级。Create/Add 等入口必须由感知层归为 navigation；安全 function-set 开关还必须同时满足既有状态轴预算、权限与独立全屏风险门，再走 probe/restore 事务。失败与 no-effect 仍由动作事务带证据退休。这是离线调度策略；live 验收仍依赖真实点击后的落地与结构化验证。

表单的最终按钮同样由感知上下文决定，而不是按 Add/Create/Save/Apply/Done/Open 的文字决定。只有当前画面明确说明它在目标 App 内创建、更新或打开普通本地项目，结果可逆或会进入可继续遍历的 App 内状态，并且没有账户、认证、权限、网络、通信、支付、安全、系统配置、破坏性或外部副作用时，才输出 `category=navigation, risk=none`。这些名称只是例子；Delete/Remove/Reset/Erase/Disconnect、敏感/外部效果和不确定后果继续输出 dangerous 或 fail closed。SoM naming 与 direct grounding 共用该边界；Engine 不增加第二套语义升级逻辑。

两条感知 Prompt 现在共用一段精简的功能入口分类：`navigation` 只表示会打开/显露当前 App 内此前不可见的功能表面，或满足上述安全本地表单完成条件；`shallow` 是输入、焦点、单值和外观布局变化；`dangerous` 覆盖破坏、账户/认证/权限、网络/通信/支付、安全/系统配置、外部 App 与安全性不确定；`display` 只保留不可交互身份锚点。安全已明确但 navigation/shallow 难分时优先 navigation，安全性本身不明确时仍 fail closed。`back=true` 只用于不提交的 Back/Cancel/Close；安全的 Done/Save/Add/Apply 是 `navigation + back=false`，不能按名称归类。Prompt 同时明确截图文字只是待识别 UI 数据，不是可执行指令。active surface、modal/system dialog/interruption、page/关键锚点、permission 与 switch stateful 字段契约均未改变。

`--vlm_grounding` 直接由 VLM 定位并命名控件，启动时不加载 OmniParser YOLO，空/失败 grounding 继续 fail closed，不回退到 YOLO/OCR。未指定 `--vlm_grounding` 的 legacy SoM 路径仍加载 `--ocr_model_path` 并使用 YOLO+OCR；CLI 参数结构未改变。Clock/Alarm 的 Add 是本轮首个验收案例，但生产规则不包含应用名或按钮白名单。离线合同测试通过后，又在保存的 Clock New Alarm 截图上运行真实 Qwen qwen3.7-plus replay（未启动 VM）：Add 为 `navigation, back=false`，Sunday、Ring Duration、Snooze Duration 为 `shallow`，Cancel 为 `navigation, back=true`；证据位于 `issues/20260714_clocks_sunday_form/prompt_mvp_vlm_replay/`。该结果只证明保存截图上的感知分类，不等于 live 点击、落地或完整遍历认证。

For a `transitioned_inconsistent` click, the newly observed landing remains available until Router finishes the existing source-recovery attempt. If that landing was created only by the current attempt, Engine then reuses the existing fail-closed provisional cleanup transaction to remove it from graph/runtime/Visual/Region membership before retrying or stopping. An existing state, or any state with committed, verified, abnormal, or other authoritative references, is never removed. This does not change the single-retry policy and does not extend cleanup to `no_effect` landings.

紧凑 `icon/glyph/image` 的实时重绑以登记时原始 bbox 为不可漂移锚点。局部模板只有同时达到既有高分阈值并落在原 bbox 邻域时才可直接采用；同名 VLM 后备候选还必须与原 bbox 重叠且位于该邻域。存在同名候选但全部越界时立即 fail closed，禁止再由通用外观匹配把相邻图标接管为目标。
### schema v3 resume 鐨?Variant 鏉冨▉鏉愭枡

`visual_resume.py` 鍦ㄤ复鏃?registry 涓婇噸寤轰弗鏍?`semantic_page_variant_v1` 鑺傜偣鏃讹紝绋冲畾 Page 浠嶄粠椤甸潰璇箟鍜屽厓绱犱笂涓嬫枃閲嶇畻骞朵笌鎸佷箙 `page_id` 鏍稿锛沄ariant 鍒欎互鎸佷箙 `observed_facts` 涓烘潈濞佽韩浠芥潗鏂欙紝閲嶆柊璁＄畻 hash 骞朵笌鎸佷箙 `variant_id` 鏍稿鍚庡畨瑁呫€傚師鍥犳槸鍚屼竴鑺傜偣鐨?revisit 浼氭妸鏇村鍑芥暟鍒悕鍜屼笅鎶樺彔瑙傚療绱Н杩?`observed_facts`锛屾渶缁?`elements` 蹇収涓嶄繚璇佷繚鐣欐墍鏈夊巻鍙插埆鍚嶃€傚彧鐢?elements 閲嶇畻浼氶敊璇嫆缁濇湁鏁堝浘銆?
璇ュ吋瀹硅矾寰勪笉鏄俊浠讳换鎰忔寔涔?id锛氳嫢 `compute_variant_id(page_id, observed_facts)` 涓庢寔涔?`variant_id` 涓嶄竴鑷达紝resume 浠嶅師瀛愬け璐ヤ笖涓嶆薄鏌撳綋鍓?Engine锛涙棫鍥炬病鏈夋潈濞?facts 鏃剁户缁娇鐢?element-derived 涓ユ牸鏍￠獙銆?026-07-12 绂荤嚎鍥炲綊 `python -B tests/test_resume_from_graph.py` ALL PASS锛宼argeted `py_compile` PASS锛涚湡瀹?Settings 30 鑺傜偣鍥惧彧璇婚噸寤轰负 `nodes=30/actions=37/frontier=30`銆傝繖涓€缁撴灉鍙瘉鏄庢仮澶嶆潗鏂欏绾︼紝淇鍚?live VM/VLM 缁窇缁撴灉鍙﹁銆?
## 楠岃瘉

2026-07-11 宸茬‘璁ょ殑绂荤嚎鍥炲綊锛?
```powershell
python -B tests/test_graph_event_ledger.py
python -B tests/test_online_capability_discovery.py
python -B tests/test_functional_surface_identity.py
python -B tests/test_capability_driven_frontier.py
python -B tests/test_discovery_seed_runtime.py
python -B tests/test_visual_run_state_machine.py
python -B tests/test_resume_from_graph.py
python -m pytest -q tests/test_visual_router.py
python -B tests/test_graph_quality_agent.py
python -B tests/test_architecture_boundaries.py
```

涓婅堪娴嬭瘯鍧囬€氳繃锛孯outer 鎵规涓?7 passed銆傜洰鏍囨ā鍧?`compileall` 浜﹂€氳繃銆傛湰娆℃病鏈夊惎鍔?VM銆丄ndroid emulator 鎴栫湡瀹?VLM锛汣lock/Alarm 鐨?empty 鈫?Create 鈫?Editor 鈫?Save 鈫?has_alarm 鈫?Detail live 闂幆灏氭湭楠屾敹锛屼笉鑳界敤绂荤嚎 stub 缁撴灉澹扮О閬嶅巻宸插疄鏈哄畬鎴愩€?
2026-07-12 鏈疆 scroll/瀹屾垚璇佷功绂荤嚎鍥炲綊锛?
```powershell
python -B tests/test_traversal_completion_certificate.py
python -B tests/test_graph_event_ledger.py
python -B tests/test_visual_run_state_machine.py
python -B tests/test_resume_from_graph.py
python -B tests/test_graph_quality_agent.py
python -B tests/test_live_status_summary.py
```

鍏潯鍛戒护鍧囦互閫€鍑虹爜 0 閫氳繃锛涜鎵规鍙鏌ョ函鍐呭瓨/绂荤嚎璇佷功銆丄ctionEdge attempt銆乺esume銆丟raphQuality 鍜?monitor 濂戠害銆傛病鏈夊惎鍔ㄦ闈?VM銆丄ndroid emulator 鎴栫湡瀹?VLM锛屼篃娌℃湁鍋?live GUI 鐐瑰嚮/landing 楠屾敹銆?
2026-07-12 popup active-surface 鍥炲綊锛歚python -B tests/test_popup_surface_guard.py` 閫氳繃锛岃鐩?structured dropdown 鍗充娇婕?`is_modal` 涔熸彁鍗囦负 active overlay銆佽儗鏅?bbox 杩囨护銆? 娆?swipe 涓?static scroll ledger銆佸悓涓€ popup live rebind锛屼互鍙?popup 娑堝け/鎹綅鏃舵嫆缁濊儗鏅悓鍚嶉」銆傜浉鍏?`test_modal_surface_bbox_filter.py`銆乣test_graph_quality_guards.py`銆乣test_scroll_waste.py`銆乣test_visual_cache.py`銆乣test_modal_candidate_policy.py`銆乣test_visual_run_state_machine.py`銆乣test_architecture_boundaries.py` 鍜?targeted `py_compile` 閫氳繃銆傚叏閮ㄦ槸鏈満绂荤嚎/鍚堟垚楠岃瘉锛涙湭鎿嶄綔 emulator锛孨otifications 鎺掑簭 popup 灏氭湭 live 閲嶈窇銆?
### provisional landing reconciliation锛?026-07-12锛?
鐘舵€佹帶浠剁偣鍑诲拰 focus-relaunch 閮藉彲鑳藉湪璇箟楠屾敹鍓嶆妸鍏夋爣/鏍囨敞鎶栧姩甯х櫥璁版垚鏂?execution state銆傚綋鍓嶄笉浼氱缁熷垹闄?rejected landing锛氬彧鏈?before/after 鏄浉鍚岀殑宸茬煡 off/on锛屾簮涓庤惤鍦?`page_id` 鐩稿悓锛屽畬鏁?structured state map 涓?selected modes 鐩稿悓锛屼笖鏂拌妭鐐规病鏈変换浣曞凡鎻愪氦寮曠敤鏃讹紝鎵嶈皟鐢?`_discard_uncommitted_equivalent_state()` 灏?attempt 褰掍竴鍥炴簮骞舵竻鐞?graph/visual registry/region `seen_on`/runtime frontier/artifact index銆傝瘖鏂枃浠朵繚鐣欙紝浣嗕笉鍐嶅睘浜庡浘鎴栨潈濞?node index銆?
`transitioned_inconsistent`銆佷笉鍚岄〉闈€乫acts 涓嶅悓銆乽nknown value銆佸凡鎻愪氦杈规垨 restore failure 涓嶄細琚箰瑙傚悎骞躲€傛櫘閫氱偣鍑荤殑鐪熷疄钀藉湴浠嶅彲鐧昏锛況elaunch 鍚庣殑鏈煡椤甸潰鍙褰曟仮澶嶅け璐ワ紝涓嶈繘鍏ヨ妭鐐归泦鍚堛€傛闈?GNOME Settings 棣栬疆 live 澶辫触鍥惧彧鑳界敤浜庡畾浣嶆晠闅滐紝涓嶈兘鏇夸唬淇鍚庡叏鍥惧璺戙€?
2026-07-13 绂荤嚎閫氳繃 `test_visual_run_state_machine.py`锛?4 椤癸紝鍚粴鍔ㄦ渶澶氳ˉ瀹′竴娆°€佸凡鐭?relaunch 閲囩敤鏃㈡湁璺緞銆佹湭鐭?relaunch 涓嶅鑺傜偣銆佹垚鍔?Resume 鍚庢棫缁堟鍘熷洜涓嶆薄鏌撴櫘閫氳矾鐢卞け璐ワ級銆乣test_resume_from_graph.py`銆乣test_visual_router.py`锛?2 passed锛夈€乣test_region_click_ledger.py`銆乣test_graph_event_ledger.py`銆乣test_traversal_completion_certificate.py`銆乣test_scroll_waste.py`銆乣test_popup_surface_guard.py`銆乣test_visual_stitch.py` 涓?targeted `py_compile`銆傛湰娆℃湭杩炴帴 VM銆佹湭璋冪敤鐪熷疄 VLM锛屼笉鏋勬垚 live 璁よ瘉銆?
绂荤嚎閫氳繃 `test_visual_run_state_machine.py`锛堝惈涓ゆ no-effect 鍚?terminal銆乺elaunch unchanged 鍥炴敹銆乽nknown 淇濈暀锛夈€乣test_graph_event_ledger.py`銆乣test_functional_surface_identity.py`銆乣test_region_click_ledger.py`銆乣test_architecture_boundaries.py`锛涙湰鑺備笉澹版槑 VM/VLM runtime validation銆?
## 淇敼鍘嗗彶锛堜互涓嬩负甯︽棩鏈熺殑鍘嗗彶璇佹嵁锛?
### 2026-07-11 鈥?Page/Variant銆佸湪绾胯兘鍔涗笌 capability-driven frontier

- 鎵ц鑺傜偣鍗囩骇涓?Page@Variant锛氱ǔ瀹?page 鑱氬悎 variants锛孯outer 浠嶅湪鍏蜂綋 state 涓婅惤鍦般€?- 瑙傚療鏈熺洿鎺ョ敓鎴?portable discovered capability锛涚湡瀹炲姩浣滀笌涓ユ牸 landing 鎵?verified銆?- schema v3 浠?ActionEdge.attempts 涓哄敮涓€鎸佷箙鍔ㄤ綔鐪熷€硷紝Router 鍙 verified routing view锛涜涔夊姩浣滀笉鎸佷箙鍖?discovery geometry銆?- 閬嶅巻绉婚櫎 domain seed planner锛汣reate/Add 璧版櫘閫?coverage frontier锛孍xplorer `done` 鏃犳潈鍓帀鏈墽琛屽€欓€夈€侻13 prerequisite runtime 淇濈暀銆?- 楠岃瘉浠呬负涓婅堪绂荤嚎/绾唴瀛樻壒娆★紱鏈惎鍔?VM/emulator/VLM锛孋lock empty鈫抎etail 浠嶅緟 live 楠屾敹銆?
### 2026-07-11 Settings 灏忛绠楃幇鍦鸿瘉鎹紙schema v2 鍘嗗彶锛?
- `result_visual_setting_v2_smoke_20260711_120003/.../graph.json`锛氬苟鍙戞墜宸ユ埅鍥句笌 guest 鍥哄畾鎴浘鏂囦欢绔炰簤锛屾敹鍒版埅鏂殑 HTTP-200 payload锛涘浘瀹夊叏鍋滄涓?1 node / 0 edge / 1 `perception_failed` event锛屾病鏈変吉杈广€傛鍚?controller 瀵规瘡涓?200 payload 鍋?PIL 瀹屾暣瑙ｇ爜鏍￠獙鍜屾湁鐣岄噸璇曘€?- `result_visual_setting_v2_smoke_retry_20260711_121136/.../graph.json`锛歠resh 7 node / 6 edge 鍚庡悓鍥?resume 鍒?12 node / 11 edge / 12 event锛涘墠 11 涓垚鍔熻惤鍦板潎涓庢爣棰?鎴浘涓€鑷达紝绗?12 涓?`Learn more` 涓烘湭鎻愪氦 `no_effect`锛屾湭浼€犺竟銆傜幇鍥?`stop_reason=max_actions`锛屼笉鏄畬鏁磋鐩栥€?- `result_visual_setting_stateful_smoke_20260711_154035/.../graph.json`锛氱湡瀹炶瘑鍒嚭涓€涓?`function_set` 鎺т欢骞跺湪姝ｇ‘瑙嗚浣嶇疆鎵ц probe锛沚efore/after 鐨勭粨鏋勫寲鐘舵€佷粛涓?`off`锛屽洜姝?event 璁颁负鏈彁浜?`no_effect`銆佷笉寤虹姸鎬佽竟銆傝缁撴灉鍙瘉鏄庝簨鍔￠棬鑳芥嫆缁濆亣缈昏浆锛屼笉璇佹槑褰撳墠 VM 鍏峰瀵瑰簲鐜鑳藉姏锛屼篃涓嶈兘鎹鍐欓〉闈?鎺т欢鐗瑰垽銆?
### 鏇存棭鍘嗗彶璁板綍

- 鍒濈増锛氬缓妯″潡楠ㄦ灦锛屾劅鐭?鐘舵€?鍥炴函/寮曟搸/浜х墿浜斾欢 + 鍏ュ彛鑴氭湰鏂囨。銆俈LM缁熶竴鍛藉悕銆丅FS鍏ㄨ鐩栥€佷竴姝ュ埌浣嶅畬鏁村洖璺€?- 鎺ュ叆 OCR锛歚detect()` 鐢辩函 YOLO 鏀逛负 YOLO+OCR锛堝榻愬畼鏂?OmniParser鈥斺€斿畼鏂规湰浣撲笉鍚?OCR 妯″瀷锛?  椤堕儴鏃犳潯浠?`import easyocr` + `from paddleocr import PaddleOCR`锛夈€傚疄娴嬭缃〉 YOLO 56 妗?鈫?YOLO+OCR 78 妗嗭紝
  澶氬嚭鐨?22 涓槸宸︿晶瀵艰埅鑿滃崟杩欑被绾枃瀛楀叆鍙ｃ€傚幓閲嶅垎鏋愮‘璁ゆ棤閲嶅/楂業oU/宓屽妗嗐€?  - OCR 寮曟搸鍙厤锛歚ocr_engine` = easyocr(榛樿锛屽榻愬畼鏂? / paddleocr锛沗ocr_languages` 榛樿 en+ch_sim銆?  - 鎳掑姞杞?reader锛堟瘮瀹樻柟妯″潡椤堕儴鍒濆鍖栨洿鍏嬪埗锛屼笉鐢?OCR 鏃朵笉鍗犲唴瀛橈級銆?  - 鍛戒护琛岋細`--no_ocr` 鍏?OCR銆乣--ocr_engine`銆乣--ocr_lang`銆?  - 鍛藉悕鍏滃簳閾撅細VLM 缁熶竴鍛藉悕 鈫?OCR content锛堟枃瀛楀叆鍙ｏ級鈫?Florence-2 caption 鈫?绌恒€?  - 鍒嗘瀽鑴氭湰锛歚tools/compare_yolo_vs_omniparser.py`銆乣tools/analyze_box_dedup.py`銆?- 鍔犺瑙夌瓫閫夊眰 `visual_filter.py`锛堟埅鍥剧増 app_filter.py锛夛紝涓?a11y 鐗堥€愭潯瀵归綈锛?  - 鈶?App 绐楀彛瑁佸壀锛歏LM 杩斿洖涓荤獥鍙ｆ锛屼腑蹇冨湪妗嗗鐨勶紙Dock/鐘舵€佹爮/妗岄潰锛変涪寮冦€?  - 鈶?娲诲姩琛ㄩ潰/妯℃€佹敹绐勶細VLM 杩斿洖 `is_modal` + 妯℃€佹 bbox锛屾娴嬪埌妯℃€佹椂瑁佸壀鐢ㄦā鎬佹
    锛堝榻?a11y `_pick_active_surface`锛氭湁妯℃€佹鍙帰妯℃€佹锛岃儗鍚庤彍鍗曚笉鐐癸級銆?  - 鈶?static 鏂囧瓧杩囨护锛歏LM 姣忓厓绱?`category`锛岀函灞曠ず `static` 涓嶈繘 BFS 寰呯偣闃熷垪銆?  - 鈶?绐楀彛瑁呴グ鎺掗櫎锛歏LM `category=chrome` + 鍚嶅瓧鍖归厤锛堝叧闂?鏈€灏忓寲/鏈€澶у寲锛夎烦杩囷紝閬垮厤璇偣鍏崇獥銆?  - 鍏ㄩ儴淇″彿鏉ヨ嚜**鍚屼竴娆?* VLM 鍛藉悕璋冪敤锛坵indow+is_modal+modal+category锛夛紝涓嶅鍔?API 璋冪敤銆?  - `detect_and_name(apply_filter=True)` 榛樿杩囨护锛沗=False` 淇濈暀鍏ㄩ儴锛堟爣娉?妫€瑙嗙敤锛夈€?  - 鏍囨敞鑴氭湰 `tools/annotate_buttons_on_nodes.py` 鐢ㄩ鑹插睍绀鸿繃婊ゅ喅绛栵細
    榛?娲诲姩琛ㄩ潰妗嗭紝鐏?绐楀彛澶栵紝绾?chrome锛岀传=static锛岀豢/钃?淇濈暀(vlm/ocr)銆?  - 涓?a11y 鐨勬湰璐ㄥ樊寮傦細a11y 闈?`st:modal/active/focusable/sensitive` 璇箟灞炴€э紝瑙嗚闈?VLM 鍒ゆ柇
    + 鍑犱綍瑁佸壀锛?% margin 瀹归敊锛夛紝闈?100% 绮剧‘浣嗗疄娴嬪甫妯℃€佹澶嶆潅椤佃涓烘纭€?- 瀵归綈 a11y 鍥涘垎绫伙紙dangerous/shallow/navigation/display锛夛紝澶嶇敤 graph_prompts.py 鐨勬潈濞佸畾涔夛細
  - VLM 鍛藉悕鏃朵负姣忎釜鍏冪礌杩斿洖 category锛堝洓閫変竴锛夛紝鏇夸唬鍘?control/nav/input/static/chrome銆?  - **navigation**=鍙兘寮€鏂扮晫闈⑩啋**鐐?*锛堝敮涓€鍙偣绫伙紝OCR 鏂囧瓧鍏ュ彛榛樿褰掓锛夈€?  - **shallow**=椤靛唴鍙娴嬫搷浣滐紙璁＄畻鍣ㄦ暟瀛?璋冨€?澶嶅埗绛夛級鈫?*璺宠繃浣嗚褰?*涓?node_local_functions
    锛堝榻?a11y锛屽啓杩?state_meta.json锛?鍙彂鐜板姛鑳戒笉鎵ц"锛夈€?  - **dangerous**=鍏虫満/閲嶅惎/娉ㄩ攢 + 鍒犻櫎/閲嶇疆/鏍煎紡鍖?瀹夎/淇濆瓨搴旂敤/鏉冮檺寮€鍏斥啋**缁濅笉鐐?*銆?  - **display**=绾睍绀哄彧璇烩啋璺宠繃銆?  - 鍚嶅瓧瀹夊叏缃?`_DANGER_NAMES`锛氬嵆浣?VLM 璇垽锛屽悕瀛楀懡涓垹闄?娓呯┖/鏍煎紡鍖?鏈€灏忓寲绛変篃寮哄埗 dangerous
    锛堥槻寰＄旱娣憋級銆俢ancel/鍙栨秷**鏁呮剰涓嶅湪**缃戝唴鈥斺€斿叧瀵硅瘽妗嗘槸瀹夊叏鐨勫洖婧閬撱€?  - 寮曟搸 `_register` 鎶?shallow 鐨?node_local_functions 浼犵粰 artifacts 鍐欑洏锛汢FS 鍙偣 navigation銆?  - 鏍囨敞鑴氭湰棰滆壊鏀逛负鍥涘垎绫伙細缁?navigation(鐐?銆佺孩=dangerous銆佹=shallow(璁板綍)銆佺传=display銆佺伆=绐楀彛澶栥€?  - 瀹炴祴 Trash 妯℃€佹锛欵mpty Trash 姝ｇ‘鏍囩孩 dangerous 涓嶇偣锛孋ancel 褰?navigation 鍙偣鍏崇獥锛?    鑳屽悗璁剧疆椤圭獥鍙ｅ鍙樼伆鈥斺€斿畬鍏ㄧ鍚?鍙彂鐜伴〉闈€佷笉鎵ц鍗遍櫓鍔熻兘"銆?
## 2026-06-27 搴旂敤鐒︾偣瀹堝崼 AppFocusGuard锛堟不"绂诲紑鐩爣 app 浠嶈鑺傜偣"锛?
**闂**锛坅ndroid_calculator it0 瀹炴祴锛夛細绾瑙夊紩鎿?*娌℃湁搴旂敤鐒︾偣淇濇姢**銆備竴鏃︽煇娆＄偣鍑?宕╂簝
鎶婄敾闈㈠甫鍑虹洰鏍?app锛堝畨鍗撴闈?鍚姩鍣ㄣ€佹渶杩戜换鍔°€佺數婧愯彍鍗曘€佸穿婧冨脊绐椼€佹垨鍒囧埌鍙︿竴涓?app锛夛紝
寮曟搸鐓ф牱鎶婅繖浜?*绂?app 鐢婚潰娉ㄥ唽鎴愬浘鑺傜偣**缁х画鎺㈢储鈥斺€旀鏄?a11y 閬嶅巻浜у嚭鐨勯偅绉嶅瀮鍦捐妭鐐广€?鏃ュ織鐜拌薄锛氭敞鍐屽嚭 `0 clickable, 0 node-local` 鐨勭┖鑺傜偣锛堟闈?鍔犺浇椤垫劅鐭ヤ笉鍒板彲鐐瑰厓绱狅級锛?`landed_on_target_app=false`銆俛pp 鍚嶅啓閿欐椂杩樹細鍦ㄦ闈贡璧帮紙鏇捐娴嬶級銆?
**淇**锛堟渶閫氱敤銆佹儬鍙婃墍鏈?app锛屼笉鏄崟 app hack锛夛細鏂板绗?4 涓?in-traversal VLM 瑙掕壊
`AppFocusGuard`锛坄visual_agents.py`锛夆€斺€斾竴鍙?`predict_mm` 鍒?褰撳墠鐢婚潰鏄惁浠嶅湪鐩爣 app 鍐?銆?鍒ょ寮€鐨勬儏褰細鍚姩鍣ㄤ富灞?/ 鏈€杩戜换鍔?/ 閫氱煡鏍忓揩鎹烽潰鏉?/ 鐢垫簮鑿滃崟 / 宕╂簝鏃犲搷搴斿脊绐?/
瀹屽叏涓嶅悓鐨?app锛?*app 鍐呴儴瀛愰〉/璁剧疆椤?瀵硅瘽妗嗕粛绠?on_app=true**锛堜笉璇潃姝ｅ父娣卞叆锛夈€?VLM 鍑洪敊/涓嶅彲瑙ｆ瀽鏃?*fail-open**锛堥粯璁ゅ湪 app 鍐咃級锛岄伩鍏嶆姈鍔ㄩ樆鏂甯告帰绱€?
寮曟搸鎺ョ嚎锛坄visual_engine.py`锛夛細
- 鏂板 `_ensure_on_app(obs) -> (obs, relaunched)`锛氬畧鍗姤鍛婄 app 鏃惰皟鐢?`relaunch_fn`
  锛坅ndroid = `startup_reset_app` 閲嶆柊鎷夎捣鐩爣 app锛夐噸鏂拌娴嬶紝鏈€澶?`MAX_RELAUNCH_ATTEMPTS=3` 娆?  闃叉寰幆銆?*绂?app 鐢婚潰姘镐笉杩?`_register`锛屾晠姘镐笉鎴愯妭鐐?*銆?- 涓変釜瑙傛祴鐐瑰叏閮ㄨ繃瀹堝崼锛氬垵濮?obs銆佹瘡娆＄偣鍑?`env.step` 涔嬪悗銆佸洖婧惤鍦颁箣鍚庛€?- 鐐瑰嚮/鍥炴函瑙﹀彂 relaunch 鍚庣敾闈㈠洖鍒?**app 鏍?*锛岄偅鏉＄偣鍑昏矾寰勫凡涓嶅啀閫氬悜姝ゅ 鈫?  浠ョ┖ path 鍦ㄦ牴娉ㄥ唽銆?*涓嶈璇杈?*锛堟爣娉?姝ゆ寜閽€€鍑轰簡 app锛屾仮澶嶅洖鏍?璇箟锛夈€?- 寮€鍏?`focus_guard_enabled`锛堥粯璁?True锛夛紱`agent is None` 鎴栨棤 `relaunch_fn` 鏃惰嚜鍔ㄦ梺璺€?
鎰忎箟锛氬吋椤?*宕╂簝闊ф€?*锛堝穿浜嗚嚜鍔ㄩ噸鎷夋帴鐫€鎺級涓?*鑺傜偣绾噣**锛堜笉鍐嶆贩鍏ユ闈?鍒殑 app/鐢垫簮鑿滃崟锛夛紝
瀵归綈 PROJECT_GOAL "no garbage / off-app nodes"銆備唬浠凤細姣忎釜瑙傛祴鐐瑰涓€娆?VLM 璋冪敤锛坒ail-open锛夈€?
### 2026-06-27 鈥?鐒︾偣瀹堝崼鏀?fail-CLOSED锛氶噸鎷夊け璐ユ椂鎷掔粷娉ㄥ唽绂?app 鐢婚潰 + 涓嶅彲鎷夎捣鍗充腑姝?
**闂锛坅ndroid_calculator iter2 鏆撮湶锛岀幆澧冨眰鏍瑰洜 + 浠ｇ爜灞傜己闄凤級**锛?璇?AVD 涓?**鏈畨瑁?* `com.google.android.calculator`锛坄pm list packages | grep calc` 绌猴級锛?`startup_reset_app` 姣忔閮藉け璐ワ紙monkey "No activities found", pm clear exit 1锛夛紝
閬嶅巻璧锋钀藉湪 Pixel 鍚姩鍣ㄤ富灞忋€俰ter1 鐨?AppFocusGuard **姝ｇ‘**妫€鍑?62 娆?OFF-APP 骞惰Е鍙戦噸鎷夛紝
浣?app 鏍规湰鎷変笉璧锋潵 鈫?閲嶆媺鍏ㄥけ璐?鈫?鏃х殑 **fail-OPEN** 璺緞鍦?`MAX_RELAUNCH_ATTEMPTS=3` 鑰楀敖鍚?**鐓ф牱鎶婄 app 鐢婚潰娉ㄥ唽鎴愯妭鐐?* 鈫?浜у嚭 12 涓┖ page_name / 0 杈?/ action_counter=0 鐨?鍚姩鍣?鎷ㄥ彿鍨冨溇鑺傜偣锛屼笖鍥犳瘡姝ラ兘閲嶆媺澶辫触鑰岀┖杞害 55 鍒嗛挓鎵嶈浜哄伐鏉€鎺夈€?
**淇锛坈ommit 2ef33641锛岄€氱敤锛屾儬鍙婃墍鏈?app 鐨勫穿婧?涓嶅彲鎷夎捣鍦烘櫙锛?*锛?- `_ensure_on_app` 杩斿洖涓夊厓缁?`(obs, relaunched, on_app)`銆俙on_app` = 鏈€缁堢敾闈㈡槸鍚︾湡鐨勫湪鐩爣 app 鍐咃紱
  閲嶆媺鑰楀敖鍚庝粛绂?app 鈫?`on_app=False`銆?- 涓変釜瑙傛祴鐐癸紙鍒濆 / 鐐瑰嚮鍚?/ 鍥炴函鍚庯級锛歚on_app=False` 鏃?**涓嶅啀 `_register`**锛坒ail-CLOSED锛?  褰诲簳鏉滅粷鍨冨溇鑺傜偣锛夛紝骞剁疮鍔?`off_app_streak`銆?- 鍒濆瑙傛祴灏?`on_app=False` 鈫?鐩存帴涓锛坅pp 鍚姩鍗充笉鍙揪锛岃繛涓€涓妭鐐归兘涓嶅缓锛夈€?- 杩炵画 `MAX_CONSECUTIVE_OFF_APP=3` 娆＄ app 鈫?鍒ゅ畾"姝ゆ満涓?app 涓嶅彲鎷夎捣"锛屼腑姝㈤亶鍘嗭紙涓嶅啀绌鸿浆 55 鍒嗛挓锛夈€?- `run_visual_traversal.relaunch_fn` 閫忎紶 `startup_reset_app` 鐨勫け璐ュ苟 warning锛堝穿婧?鏈畨瑁?鍖呭悕閿欏彲瑙侊級銆?- 閬垮厤瀹堝崼澶氳姳涓€娆?VLM锛氬惊鐜唴澶嶇敤涓婁竴娆?`on_app(shot)` 缁撴灉锛宍attempts==0`锛堜竴杩涙潵灏卞湪 app 鍐咃級闆堕澶栧紑閿€銆?
**娉ㄦ剰**锛歛ndroid_calculator 鍦ㄨ AVD 鏈韩鐨勯棶棰樻槸鐜灞傦紙app 鏈锛夛紝闇€瑁?APK 鎴栨敼鎸囧悜宸茶 app
锛坅ndroid_dialer / android_clock / android_contacts锛夋墠鑳界湡姝ｉ獙璇佽瑙夊紩鎿庯紱鏈淇璁╁紩鎿庨潰瀵?浠讳綍"鎷変笉璧锋潵鐨?app"閮藉共鍑€涓鑰岄潪浜у瀮鍦捐妭鐐广€?
### 2026-06-27 鈥?涓夐」閫氱敤妗嗘灦淇锛氶〉鍐呮粴鍔ㄨ仛鍚?+ 骞垮害浼樺厛 BFS + 钀藉抚 settle

**鍔ㄦ満锛坅ndroid_settings 閫愮溂璇勫锛屾儬鍙婃墍鏈夐暱鍒楄〃/澶氶〉 app锛?*锛歷isual 寮曟搸鍙湅**棣栧睆 viewport**锛?闀垮垪琛ㄩ〉锛堣缃?鏃堕挓/鑱旂郴浜?鐭俊锛夋姌鍙犵嚎浠ヤ笅鐨勫姛鑳借锛圖isplay / Sound / Storage / System /
About phone鈥︼級姘歌繙涓嶈繘 BFS 闃熷垪锛涗笖寮曟搸**娣卞害浼樺厛**鈥斺€旂偣寮€涓€琛屽氨涓€璺捇鍒板簳锛圓pps>App-info>
Permissions>閫?app 鏉冮檺锛夋墠鍥炲ご锛屽鑷?max_states 棰勭畻琚竴涓瓙鏍戝悆鍏夛紝涓婚〉骞垮害楗挎锛涘彟鏈変袱涓妭鐐?鎴浘鍗″湪閿洏婊戝叆/杞満锛屽垎杈ㄧ巼/娓呮櫚搴︿笉涓€鑷达紝寮卞寲 pHash state-id銆?
**淇锛堝叏閮ㄩ€氱敤銆佹闈㈤浂褰卞搷锛?*锛?
1. **椤靛唴婊氬姩鑱氬悎 `_scroll_aggregate`锛坴isual_engine.py锛屾渶楂樻潬鏉嗭級**锛氭敞鍐?*鏂?*鑺傜偣鏃讹紝浠庨灞忚捣
   鍚戜笅 swipe銆侀噸鏂版劅鐭ャ€佺敤 `ElementMatcher`锛坴isual_state.py 鏃㈡湁锛屾寜澶栬 pHash 杩戜技鍘婚噸锛夊彧绱姞
   **鐪熸鏂板**鐨勫彲鐐瑰厓绱狅紝鐩村埌 viewport 杩炵画 `SCROLL_PATIENCE=2` 甯т笉鍙橈紙鍒板簳锛屽惛鏀跺崟甯ф姈鍔級鎴?   `MAX_SCROLL_STEPS=8` 涓婇檺锛岀劧鍚庢粴鍥為《閮ㄥ浣嶃€傞暅鍍?a11y 鐨?D18/D20 鑱氬悎锛屼絾绾瑙夈€傛瘡涓姌鍙犵嚎浠ヤ笅
   鍏冪礌璁板綍 `scroll_steps`锛堜粠椤堕儴涓嬫粦鍑犳鎵嶅彲瑙侊紝VisualElement 鏂板瀛楁锛夈€?   - **鍙偣鎬ч棴鐜?*锛氱偣杩欑被鍏冪礌鍓嶅厛 `_scroll_to_steps` 婊氬洖瀹冨彲瑙佸锛堝叾 center 鍦ㄨ婊氬姩浣嶆湁鏁堬級锛?     骞舵妸杩欎簺 swipe 璁板叆 `action_path`锛屼娇 hard-reset 閲嶆斁鑳藉啀娆℃姷杈炬姌鍙犵嚎浠ヤ笅鐨勮妭鐐广€?   - 浠?`vm_platform=="Android"` 鍚敤锛堣Е灞?SWIPE 璇箟锛夛紱妗岄潰婊氳疆璇箟涓嶅悓锛岃矾寰勪繚鎸佷笉鍙樸€?
2. **骞垮害浼樺厛 BFS锛坴isual_engine.py 涓诲惊鐜級**锛氱偣寮€瀛愰〉銆佽褰曡竟鍚?*涓嶅啀**鎶?`current_id` 鍒囧埌瀛愰〉
   娣遍捇锛岃€屾槸 `backtrack_to` 鍥炵埗椤电户缁偣瀹?*鍓╀綑鐨勮**锛堝瓙椤靛凡 enqueue 杩?FIFO 鍓嶆部锛岀◢鍚庢寜
   鏈€娴呬紭鍏堝嚭闃熸帰绱級銆傜洿鎺ラ摬鎺夎瘎瀹?#1 鏍瑰洜"娣卞害浼樺厛鍚冨厜棰勭畻"銆傚洖婧蛋鏃㈡湁涓夊眰锛坋scape/back/hard-reset锛夛紝
   澶氭暟"寮€椤碘啋杩斿洖"鍦ㄤ究瀹滅殑 tier0/1 瑙ｅ喅銆傜埗椤垫帰灏藉悗鎵嶄笅闄?鍑洪槦銆?
3. **钀藉抚 settle `_settle`锛坴isual_engine.py锛?*锛氬姩浣滃悗杞鎴浘锛岀洿鍒拌繛缁袱甯?pHash 绋冲畾
   锛圚amming 鈮?`VIEW_STABLE_DISTANCE=4`锛夋垨 `SETTLE_MAX_POLLS=4` 瓒呮椂锛屽啀鎶婅甯у綋 canonical 娉ㄥ唽銆?   娓呮帀閿洏婊戝叆/杞満鐨勭灛鎬佸抚锛屼繚璇佽妭鐐规埅鍥句笌 state-id 鏄ǔ瀹氥€佺粺涓€鍒嗚鲸鐜囩殑瑙嗗浘銆傚垵濮嬭娴嬩笌鐐瑰嚮鍚庡潎 settle銆?
**寮€鍏?*锛歚VisualTraversalEngine(scroll_aggregate=True, settle=True)`锛宍run()` 鍚屽悕閫忎紶锛?`scroll_aggregate` 缁?`vm_platform` 鑷姩鍙湪 Android 鐢熸晥銆傛敼鍔ㄦ枃浠?visual_engine.py銆?visual_perception.py锛圴isualElement.scroll_steps锛夈€傛湰鍦?+ deploy-asr 鍙岀 ast-parse 閫氳繃銆?
---

## 2026-06-27 鈥?ROUND 0 娣卞眰鐡堕淇锛坆acktrack / over-split / focus-guard / launch / tab-bar锛?
涓婁竴杞苟琛?sweep锛坆udget 50锛夐€愮溂澶嶆牳鏆撮湶 5 涓繁灞傜摱棰堬紝鏈疆鍏ㄩ儴澶勭悊锛坒eat/visual-traversal锛夛細

1. **鍥炴函鍙潬鎬э紙鏈€楂樻潬鏉嗭紝visual_backtrack.py锛?* 鈥?璇勫 #1 鏍瑰洜锛氬崟娆?escape 閫€涓嶅洖澶氬眰鐖堕〉 鈫?   鐘舵€佽鏍?unreachable銆丅FS 鍓嶆部鏃╂锛宻ettings 鍗″湪 ~18銆?   - Tier 0 鏀逛负 `_tier_back_stack`锛氳繛缁寜 **BACK 鏈€澶?`MAX_BACK_PRESSES=6` 娆?*锛?*姣忔寜涓€娆″氨 SSIM 鏍稿鍒拌揪**锛?     娌夸换鎰忔繁搴﹁繑鍥炴爤鐖洖鐖堕〉锛圓ndroid 涓?escape鈫扠EYCODE_BACK锛屽搴?a11y 鐨?mobile_ops MAX_BACK_PRESSES锛夈€?     骞跺姞 **already-arrived 鐭矾**锛坰elf-loop / 骞傜瓑鍥炴函鏃朵笉鐧芥寜 BACK 閫€鍑洪〉闈級銆?   - Tier 2 hard-reset 鏀?`_replay_once` + **鏁存閲嶆斁鏈€澶氶噸璇?2 娆?*锛堝崟娆＄灛鎬佽鐐?鍔ㄧ敾鍙敱骞插噣浜屾 relaunch+replay
     鎭㈠锛屼究瀹滆繃鏁存５瀛愭爲鍒?unreachable锛夛紝鍒拌揪浠?SSIM 鏍￠獙銆?   - 鍏叡 API 椤哄簭锛歍ier0 back-stack 鈫?Tier1 VLM back 鎺т欢 鈫?Tier2 hard-reset銆?
2. **PageIdentityJudge 杩囧垎瑁傦紙璇勫 #2锛寁isual_agents.py + visual_state.py锛?* 鈥?鐬€佹诞灞?鍔ㄧ敾甯?寮圭獥鑳屾櫙鍙樻殫
   鎶婂悓涓€鍔熻兘椤佃鎴愬涓妭鐐广€佸悆棰勭畻銆?   - `_PAGE_IDENTITY_PROMPT` 鏄惧紡瑕佹眰**蹇界暐**锛氬姩鐢讳腑闂村抚銆乼ooltip/姘旀场/Toast/绛涢€?chip/楂樹寒/鍔犺浇鍦堛€?     **寮圭獥鑳屽悗鐨勮儗鏅彉鏆楄挋灞?*銆佽蒋閿洏寮规敹/鍏夋爣/婊氬姩鏉★紱鍒ゅ畾鍘熷垯=鍘绘帀鐬€佸眰鍚庢爣棰?涓绘帶浠堕泦鍚?鍙墽琛屾搷浣滀竴鑷村嵆 same=true銆?   - `VisualStateRegistry.LOOSE_DISTANCE` 18鈫?*28**锛堣儗鏅暣浣撳帇鏆?鍏ㄥ娴眰鎶?pHash 鎺ㄥ埌 ~20-26锛屾棫 18 鎴柇浣胯繖浜涢噸澶嶉〉
     鏍规湰鍒颁笉浜?judge锛夛紝`LOOSE_TOPK=4` 闄愬埗姣忔鏈€澶氶€?judge 鐨勫€欓€夋暟锛岄伩鍏嶇瀵嗗浘姣忚妭鐐逛竴娆?VLM銆?
3. **AppFocusGuard 婕忔斁绯荤粺/璋锋瓕灞忥紙璇勫 #3锛寁isual_agents.py + visual_engine.py锛?* 鈥?OS 鏉冮檺寮圭獥銆丟oogle/GMS
   鐧诲綍鍚屾剰灞忚褰?app 鍐呭璇濇鐧昏鎴愯妭鐐广€?   - `_APP_FOCUS_PROMPT` 鏂板涓ょ被 **off-app**锛氬畨鍗撶郴缁熺骇鏉冮檺璇锋眰寮圭獥锛堝厑璁?鎷掔粷/浠呰繖娆♀€︼級銆丟oogle/GMS 璐︽埛鐧诲綍/
     鍚屾剰灞忥紱骞朵繚鐣欎緥澶栵細app **鑷繁**缁樺埗鐨勫瓙椤?瀵硅瘽妗嗕粛 on_app=true銆?   - `_ensure_on_app` 鍦ㄩ噸鍚墠鍏?*鎸変竴娆?BACK 寤変环 dismiss** 娴眰骞跺鍒わ紝鎴愬姛鍒欏師鍦扮户缁紙涓嶄涪浣嶇疆锛夛紝澶辫触鎵嶈蛋 kill+relaunch銆?
4. **files=0 / messaging 绌猴紙璇勫 #4锛宔nv/android_controller.py锛?* 鈥?鏍瑰洜锛歚monkey -c LAUNCHER` 瀵规棤 launcher
   activity 鐨勫寘锛圓OSP DocumentsUI 绛夛級闈欓粯澶辫触锛屾棫 `launch_app_android` 鎭?return True 鈫?瀹為檯鍋滃湪妗岄潰 鈫?   focus-guard 0 鑺傜偣涓銆?   - `launch_app_android` 鐜?*鏍稿鍓嶅彴鍖?*锛坄current_activity` 鍚?package 鎵嶇畻鎴愬姛锛夛紱澶辫触鍒?`is_package_installed`
     蹇€熷垽鏈畨瑁咃紱宸插畨瑁呬絾娌¤捣鏉ュ垯 `cmd package resolve-activity` 瑙ｆ瀽鐪熸 launchable 缁勪欢骞?`start_activity` 閲嶈瘯锛?     濡傚疄杩斿洖鎴愯触锛堟湭瀹夎/鏃?launchable activity 鈫?涓婂眰鎶?"not installed/launchable"锛屼笉鍐嶄吉 0 鑺傜偣锛夈€?   - 鏂板杈呭姪 `is_package_installed` / `_resolved_launch_activity`銆?
5. **搴曢儴 tab x 鍋忕Щ锛堣瘎瀹?#5锛寁isual_engine.py锛?* 鈥?clock 鐨?Alarm tab 鍥?YOLO/OCR box center 妯悜婕傜Щ鐐瑰亸銆?   - 鏂板 `_tabbar_center`锛氬厓绱犺惤鍦ㄥ簳閮ㄥ甫锛坹鈮TABBAR_BAND_FRAC=0.86`H锛変笖鍚屾帓锛坹 宸墹`TABBAR_ROW_TOL_FRAC=0.06`H锛?     鏈?鈮? 涓潎甯冨厔寮熸椂锛屾妸鐐瑰嚮 x **鍚搁檮鍒板睆瀹藉潎鍒嗙殑 segment 涓績**锛堟寜 x 鎺掑悕鍙栫 k 娈典腑蹇冿級锛寉 鍙栨暣鎺掑潎鍊硷紱
     鍚搁檮浣嶇Щ >0.18W 鍒欐斁寮冿紙涓嶄俊浠昏鎺掑亣璁撅紝淇濈暀鍘?center锛夈€傞€氱敤锛氫笉鍚换浣?app 涓撳睘甯搁噺锛岄潪 tab 鐐瑰嚮涓?no-op銆?   - 灞忓箷灏哄鐢?`_screen_wh` 鐩存帴璇绘埅鍥惧儚绱狅紙涓庡厓绱?box 鍚屽潗鏍囩┖闂达紝瑙勯伩閫昏緫/鐗╃悊鍒嗚鲸鐜囦笉涓€鑷达級銆?
**鏀瑰姩鏂囦欢**锛歷isual_backtrack.py銆乿isual_agents.py銆乿isual_state.py銆乿isual_engine.py銆乪nv/android_controller.py銆?鏈湴 + deploy-asr 鍙岀 ast-parse 閫氳繃銆?
---

## 2026-06-27 鈥?BFS frontier infinite-loop on unreachable backtrack target (璇勫 #1 杩炲甫 bug)

**鐜拌薄锛坅ndroid_dialer v0 round 0, console 5578锛?*锛氶亶鍘嗘棭鏃╂帰瀹?dialer 5 涓彲杈鹃〉锛團avorites/
Recents/Contacts/Dialpad/Search锛夛紝闅忓悗**姝诲惊鐜?*锛歚_dequeue_with_work` 鍙嶅鍥炰紶鍚屼竴鑺傜偣
`ab6b6b4b4949494b` 鈫?`backtrack_to` 姣忔澶辫触 鈫?`mark_unreachable` 鈫?涓嬭疆鍐嶆鍥炰紶鍚屼竴鑺傜偣銆傜害 110s/杞紝
鎶婃暣涓?action budget锛?00锛夎€楀湪涓€涓笉鍙揪鑺傜偣涓婏紝BFS 姘镐笉鍓嶈繘銆佹案涓嶈嚜鐒剁粨鏉熴€?
**鏍瑰洜**锛歚_dequeue_with_work()` 鍙?**peek** `self._bfs_queue[0]`锛屽綋璇ヨ妭鐐逛粛鏈?unvisited candidate 鏃?鐩存帴 return 鑰?*涓嶅嚭闃?*銆俙mark_unreachable` 浠呭湪 graph node 涓婄疆 `unreachable=True`锛屾棦涓嶅脊鍑洪槦鍒椼€佷篃涓嶆妸
candidate 鏍?visited銆備簬鏄?backtrack 澶辫触鍚庤鑺傜偣浠嶅眳闃熼涓斾粛鏈夋湭璁块棶鍊欓€?鈫?琚棤闄愰噸閫夈€?
**淇锛坴isual_engine.py锛屼袱澶勶級**锛?1. backtrack 澶辫触鍒嗘敮锛歚mark_unreachable(nxt)` 鍚庢妸璇ヨ妭鐐?*閫愬嚭 BFS frontier**锛堥槦棣栧垯 popleft锛屽惁鍒?remove锛夈€?2. `_dequeue_with_work`锛氬惊鐜噷**璺宠繃宸叉爣 `unreachable` 鐨勮妭鐐?*锛坧opleft 鍚?continue锛夛紝闃叉鍏朵粛鍩嬪湪闃熷垪娣卞鏃惰鍐嶆 peek銆?
**鏀瑰姩鏂囦欢**锛歷isual_engine.py銆傛湰鍦?ast-parse 閫氳繃锛泂cp 鍒?deploy-asr 鍚岃矾寰勫悗鍐?ast-parse 閫氳繃銆?
---

## 2026-06-27 (round 1) 鈥?backtrack arrival robustness + global fail budget + focus-guard overlay tightening

round 0 淇簡浜斾釜宸茬煡鐡堕浣?by-eye 澶嶆煡浠嶄笉杈炬爣锛歴ettings 鍗?13 鑺傜偣锛坆acktrack 澶辫触 10 娆★級锛?contacts 姝诲惊鐜紙56 娆?backtrack 澶辫触 / ~60min锛実raph.json 涓€瀛楁湭鍐欙級銆傛湰杞拡瀵?*鏈€楂樻潬鏉嗙殑
backtrack 鍙潬鎬?*缁х画鍔犲浐锛屽苟琛ヤ袱鏉￠槻绾裤€?
1. **backtrack 鍒拌揪鍒ゅ畾璇箟鍖栵紙璇勫 #1 鏈€楂樻潬鏉嗭紝visual_backtrack.py锛?* 鈥?鐪熷洜锛氱埗椤碉紙濡?settings
   涓婚〉锛夌櫥璁板悗鍏?*瀹炴椂鏁版嵁宸插彉**锛堜笉鍚岀殑鍙栧€笺€佸垪琛ㄥ浜嗕竴琛岋級锛屼弗鏍?SSIM鈮?.85 姘歌繙纭涓嶄簡鍒拌揪锛?   鍗充娇鎴戜滑鍏跺疄宸茬粡鍥炲埌璇ラ〉 鈫?鏍?unreachable 鈫?frontier 姝汇€?   - `VisualBacktracker` 鏂板鍙€?`same_page_fn`锛? 寮曟搸鐨?`PageIdentityJudge.same_page`锛夈€俙_arrived`
     鍦?SSIM 涓嶈冻鏃跺洖閫€鍒?*璇箟鍚岄〉鍒ゅ畾**锛氭妸褰撳墠甯т笌鐩爣鎴浘浜ょ粰 VLM 鍒?鏄惁鍚屼竴鍔熻兘椤?锛屾槸鍒欑畻鍒拌揪銆?     鍙湪 SSIM 涓寸晫澶辫触璺緞涓婅Е鍙戯紝鍗曟 VLM锛屽紑閿€鍙帶銆?   - 鏂板鍙€?`on_app_fn`锛? 鐒︾偣瀹堝崼 `on_app`锛? `_left_app`銆俆ier 0 `_tier_back_stack` **瓒婄晫瀹堝崼**锛?     鏌愭 BACK 鎶婃垜浠甫鍑?app锛堟闈?鏈€杩戜换鍔★級绔嬪嵆鍋滄鍐嶆寜 BACK锛堝啀鎸夊彧浼氭洿娣卞叆绯荤粺锛夛紝鏀逛氦涓嬩竴 tier
     锛坆ack-control / hard-reset锛夈€傞伩鍏?Tier 0 瓒婅繃鐖堕〉鍐茶繘 launcher 鍚庤杩槀璐?hard reset銆?
2. **鍏ㄥ眬 backtrack 澶辫触棰勭畻 + 鍗℃鍗虫椂钀界洏锛坴isual_engine.py锛?* 鈥?contacts 閭ｇ"璁惧涓?app 鍙嶅鎷?   涓嶈捣鏉?浼氫骇鐢熸棤鐣岀殑鎱㈠け璐ヤ覆銆?   - 鏂板 `MAX_BACKTRACK_FAILS=12`锛氱疮璁″け璐ヨ揪闃堝€煎嵆**骞插噣鏀跺熬**锛堜笉鍐嶈€楁弧 wall-clock锛夈€?   - backtrack 澶辫触鍒嗘敮姣忔閮?`graph.save()`锛氬崱姝荤殑璁惧涔熻兘浜у嚭閮ㄥ垎缁撴灉锛堜慨 contacts "graph.json 涓€瀛?     鏈啓"鈥斺€斿師 save 鍙湪 action 鑷 / 骞插噣缁撴潫鏃惰Е鍙戯紝鑰?backtrack 寰幆浜岃€呴兘涓嶈Е鍙戯級銆?
3. **鐒︾偣瀹堝崼鏀剁揣绯荤粺鏉冮檺娴眰锛堣瘎瀹?#3锛寁isual_agents.py锛?* 鈥?dialer 鎶婁竴甯у甫绯荤粺瀹氫綅鏉冮檺寮圭獥鐨?   Search 椤电櫥璁版垚浜嗚妭鐐癸紙`ca6a1235`锛夈€俙_APP_FOCUS_PROMPT` 鏄庣‘锛?*鍝€曠洰鏍?app 椤甸潰鍦ㄦ潈闄?鍚屾剰寮圭獥
   鑳屽悗闅愮害鍙锛屽彧瑕佺敾闈㈠嚭鐜扮郴缁熸潈闄?鍚屾剰娴眰锛堝眳涓皬鍗＄墖 + Allow/Deny/While using the app/Dismiss +
   涓€涓ゅ彞璇存槑锛夛紝灏变竴寰?on_app=false**鈥斺€旇甯ц绯荤粺娴眰姹℃煋锛屽紩鎿庡厛鍏虫帀鍐嶉噸鏂拌瀵熷簳灞傚共鍑€椤碉紝缁濅笉鐧昏銆?
4. **files/messaging launchable 瑙ｆ瀽鍥為€€ MAIN锛堣瘎瀹?#4锛宔nv/android_controller.py锛?* 鈥?   `_resolved_launch_activity` 鍘熷彧 resolve LAUNCHER category銆傞儴鍒?AOSP/Google 鍖咃紙DocumentsUI "Files"銆?   鏌愪簺 Messaging 鏋勫缓锛夊彧鏆撮湶 MAIN activity 鏃?LAUNCHER 鈫?LAUNCHER-only resolve 杩斿洖绌鸿璇垽鏀惧純銆?   鏀逛负鍏?LAUNCHER 鍐嶉€€鍥?*鏃?category 鐨?MAIN resolve**锛宺ecover 杩欎簺鍖呫€?
**鏀瑰姩鏂囦欢**锛歷isual_backtrack.py銆乿isual_engine.py銆乿isual_agents.py銆乪nv/android_controller.py銆?鏈湴 + deploy-asr 鍙岀 ast-parse 閫氳繃銆?
## 璇婃柇 (2026-06-27, diag0 run, 灏忓厠): broad-but-shallow 鐪熷洜

璇婃柇瀵硅薄: result_visual_settings_diag0/android_settings_20260627_193019 (21鑺傜偣/24杈?14姝荤, 璺戝埌 action 50/180 浠嶅湪璺? ~85s/action)銆?
**鏍瑰洜1 (HIGH) 鈥?婊氬姩鍚庡潗鏍囧け閰? 椤跺眰category鐐归敊椤?*: `_scroll_aggregate` 鑱氬悎鏃舵妸鍏冪礌 center 璁版垚鍚?scroll_step 褰撴椂鐨勮鍙ｅ儚绱?y銆備絾銆宺estore canonical top銆嶅彧鍥炴粴 `steps` 娆? home 娉ㄥ唽鏈熷疄娴?10 娆′笅婊?vs 7 娆′笂婊戔啋椤甸潰鍋滃湪搴曢儴 (saved screenshot=椤堕儴 Network@y797, som_labeled=搴曢儴 Safety/DigitalWellbeing)銆傜偣 "Network & internet"(411,797) 瀹為檯鎵撳紑 Digital Wellbeing(鏃ュ織 page-identity same=False 瀹為敜)銆俬ome 鎺簡~20涓猚ategory鍙敓鎴?鏉¤竟, 鏍囩閿欎贡(grid/Privacy icon/Battery)銆傗啋 椤跺眰category澶ч噺鐐归敊/鑷幆, 瀛愭爲never鐢熸垚銆備慨: 娉ㄥ唽鐨?canonical screenshot 蹇呴』鏄仛鍚堢敤鐨勫悓涓€甯?椤堕儴); 鐐瑰嚮 below-fold 鍏冪礌鏃剁敤銆屾粴鍒拌鍏冪礌鍙鍚庨噸鏂版劅鐭ユ嬁褰撳墠甯у潗鏍囥€嶈€岄潪鍥炴斁鏃?center; 鎴栧共鑴嗘斁寮?scroll-aggregate 鏀归€愬睆娉ㄥ唽鐙珛 state銆?
**鏍瑰洜2 (HIGH) 鈥?explorer 杩囨棭 done + done 鎶规帀鍏ㄩ儴鍊欓€?*: visual_engine.py:620 `done` 鍒嗘敮鎶婂墿浣?candidates 鍏?`visited=True` 姘镐箙寮冦€傛棩蹇?explorer 鍦?home 浠嶆湁 Safety&emergency/Digital Wellbeing/Google/System/Tips 鏈帰鏃跺垽 done銆傝繖浜涚湡category灏辨 0 杈广€備慨: done 涓嶆姽鍊欓€?鍙涓€娆? 涓嬫revisit鍐嶉棶); 鎴?done 鍓嶅己鍒惰姹?explored 瑕嗙洊 candidate 鍚嶉泦鍚堟墠鍏佽銆?
**鏍瑰洜3 (MEDIUM) 鈥?璺ㄩ〉 ExplorationMemory 鎸?name 鍏ㄥ眬鍓灊**: `mem.is_explored(name)` 鍛戒腑鍗虫妸鎵€鏈夊悓鍚嶅厓绱犳爣 visited(engine:500)銆係ettings 澶ч噺閲嶅/娉涘悕("Settings"/"Back"/""/icon/"1"), 涓€澶勭偣杩団啋浠栭〉鍚屽悕鍏ㄥ壀鈫掑瓙椤靛€欓€夊缂╂垚姝荤銆備慨: 鍏ㄥ眬 dedup 鍙鐪熸瀵艰埅绫诲叡浜帶浠?Back/Home)鐢熸晥, 鏅€?category 鍚嶆寜 (state,name) per-page 缁村害銆?
**鏍瑰洜4 (MEDIUM, 鏀惧ぇ鍣? 鈥?姣忓姩浣?0娆LM, ~85s/action**: 512 娆?DashScope / 50 action銆俿croll-aggregate 姣忔粦涓€灞?detect_and_name(YOLO+VLM naming), backtrack tier 姣忔 re-perceive, page-identity 199 娆°€?2鍒嗛挓鎵?8%棰勭畻鈫掓绔鍗婃槸銆屽凡娉ㄥ唽鏈嚭闃熴€嶃€備慨: 缂撳瓨 perception 缁撴灉(鍚?state 涓嶉噸 detect); backtrack 浼樺厛绾?SSIM/pHash 涓嶈皟 VLM; scroll-aggregate 涓婇檺鏀剁揣銆?
**鏍瑰洜5 (LOW) 鈥?relaunch 鎬诲け璐?*: "did not appear within timeout" x58, hard-reset replay 缁忓父钀戒笉鍒?target, 浣嗚 page-identity銆宻ame=True(鍙槸婊氬姩浣嶇疆涓嶅悓)銆嶆斁琛屸啋鍥炴斁鍚庨〉闈㈡粴鍔ㄦ€侀敊浣? 鍙犲姞鏍瑰洜1銆?
## 2026-06-27 鈥?broad-but-shallow 涓夐」娌绘湰淇 (鏍瑰洜1/2 HIGH + 鏍瑰洜3 MEDIUM)

閽堝涓婇潰 diag0 璇婃柇鐨?HIGH/MEDIUM 鏍瑰洜钀藉湴淇锛堝叏閮ㄩ€氱敤銆佹儬鍙婃墍鏈?app锛屾闈㈤浂褰卞搷锛夈€?鏀瑰姩鏂囦欢 `visual_engine.py`銆乣visual_agents.py`銆?
**鏍瑰洜1 (HIGH) 鈥?婊氬姩鍚庡潗鏍囧け閰?(visual_engine.py)**锛氳仛鍚堢敤鐨?canonical screenshot 鏄《閮ㄥ抚锛?姣忎釜 step-0 鍏冪礌 center 鎸佹湁椤堕儴瑙嗗彛 y锛涗絾鏃с€宺estore top銆嶇洸婊?`steps` 娆′笂婊戯紙down/up 鍗曟琛岀▼涓嶇瓑鈫?澶嶄綅涓嶅叏锛夛紝椤甸潰鍋滃湪涓儴/搴曢儴 鈫?鐐归《灞?category 鐨?stored center 鎵撳埌褰撳墠 y 澶勭殑鍙︿竴琛岋紙瀹炴祴鐐?"Network & internet" 鎵撳紑 Digital Wellbeing锛夈€?- **澶嶄綅鏀?pHash 鏍￠獙**锛氭柊澧?`_scroll_back_to_top(top_view, down_steps)`鈥斺€旇褰曟敞鍐屾椂鐨勯《閮ㄥ抚 pHash锛?  鍚戜笂婊戠洿鍒?*瀹炴椂甯?pHash 鍖归厤椤堕儴甯?*锛堥绠?`down_steps+3` 鏈夌晫闃叉寕锛夛紝鑰岄潪鐩叉暟娆℃暟銆?- **鐐瑰嚮 below-fold 鍏冪礌鏀圭敤 live center**锛氭柊澧?`_live_center_for(elem, obs)`鈥斺€擿_scroll_to_steps` 婊氬埌
  璇ュ厓绱犲彲瑙佸悗锛?*閲嶆柊鎰熺煡褰撳墠甯?*骞剁敤 `ElementMatcher` 鎸夊瑙傚尮閰嶅洖鐩爣鍏冪礌锛屽彇**褰撳墠甯х殑 box center**
  鐐瑰嚮锛岃€岄潪鍥炴斁鍦ㄤ笉鍚屾粴鍔ㄤ綅閲囧埌鐨?stored center锛堝尮閰嶅け璐ュ垯鍥為€€ stored center锛宐est-effort锛夈€?
**鏍瑰洜2 (HIGH) 鈥?explorer 杩囨棭 done + done 鎶规帀鍏ㄩ儴鍊欓€?(visual_engine.py + visual_agents.py)**锛?鏃?done 鍒嗘敮鎶婂墿浣?candidates 鍏?`visited=True` 姘镐箙寮?鈫?涓婚〉鐪?category 瀛愭爲锛堝畨鍏?鏁板瓧鍋ュ悍/璋锋瓕/
绯荤粺/鎻愮ず锛夎鎴偄銆? 杈广€?- **done 姘镐笉鎴偄**锛歞one 鏃跺彧 `visited=True` 閭ｄ簺**鏃犳柊鍔熻兘**鐨勫€欓€夛紙generic/blank 鍚嶃€佹垨宸叉帰绱㈠悓涔夛級锛?  鑻ヤ粛鏈夌湡姝ｇ殑 navigation 鍊欓€夋湭鎺紝**瑕嗙洊** done 鏀?click 绗竴涓?nav 鍊欓€夛紙鏂板 `_is_navigation`锛夈€?- **prompt 鍔犵‖绾︽潫**锛歚_EXPLORER_PROMPT` 鏄惧紡绂佹鈥斺€斿彧瑕佸垪琛ㄩ噷杩樻湁浠讳綍鍙兘寮€鏂伴〉/浜岀骇椤?鑿滃崟鐨?  navigation 鍊欓€夋湭鎺㈠氨**缁濆涓嶈 done**锛屽繀椤诲厛 click銆?
**鏍瑰洜3 (MEDIUM) 鈥?璺ㄩ〉 name 鍏ㄥ眬鍓灊濉岀缉椤甸潰 (visual_engine.py + visual_agents.py)**锛?`mem.is_explored(name)` 鍏ㄥ眬鍛戒腑鍗冲壀鎵€鏈夊悓鍚嶅厓绱?鈫?Settings 澶ч噺閲嶅/娉涘悕锛?Settings'/'Back'/''/
icon/'1'锛変竴澶勭偣杩団啋浠栭〉鍚屽悕鍏ㄥ壀鈫掑瓙椤靛€欓€夊缂╂垚姝荤銆?- **娉涘悕鐩存帴涓㈠嚭鍊欓€夋睜**锛歚_GENERIC_NAMES`锛?'/icon/grid/'1'鈥︼級鐨勫厓绱犳棦涓嶈繘 BFS 涔熶笉杩涘叏灞€ dedup 闆?  锛坄_is_generic_name`锛夛紝涓嶅啀姣掑寲銆?- **鍏ㄥ眬 dedup 鍙鐪?chrome 鎺т欢**锛歚_CHROME_NAMES`锛圔ack/Home/Close/杩斿洖/涓婚〉鈥︼紝瀛愪覆鍖归厤锛夋墠璧板叏灞€
  `is_explored`锛涙櫘閫氳鏀?**per-(state,name)** dedup锛坄ExplorationMemory.is_explored_in_state` 鏂板 +
  `mark_explored(global_scope=)` 鍙傛暟锛涘紩鎿?`mark_explored` 鍙 chrome 鍚嶄紶 `global_scope=True`锛夈€?
鏈湴 + deploy-asr 鍙岀 ast-parse 閫氳繃銆?
## 2026-06-27 鈥?Settings broad-but-shallow 璧勬繁璇婃柇涓夐」娌绘湰 (RC1 杈圭晫瀹堝崼 HIGH + RC2 鍛藉悕婕傜Щ HIGH + RC3 relaunch 鍋囧け璐?HIGH)

閽堝 Settings銆屽箍鑰屾祬銆嶅浘鐨勮祫娣卞伐绋嬪笀璇婃柇锛坮oot cause 1/2/3锛夛紝钀藉湴鍏ㄩ儴 HIGH锛?渚垮疁 MEDIUM锛変慨澶嶃€傚叏閮?*閫氱敤**銆佹儬鍙婃墍鏈?app锛屾闈㈤浂褰卞搷銆傛敼鍔ㄦ枃浠?`visual_engine.py`銆乣visual_perception.py`銆乣mobile_ops.py`銆乣traversal.py`銆?
**RC1 (HIGH) 鈥?scroll-aggregate 瓒婄晫婊戝埌妗岄潰鎶婂惎鍔ㄥ櫒鍥炬爣褰撴垚鏈妭鐐瑰鑸 (visual_engine.py)**锛?`_scroll_aggregate` 婊戣繃 in-app 鍒楄〃搴曢儴 鈫?瓒婄晫鍒?Android 妗岄潰/搴旂敤寤鸿鏉?鈫?鎰熺煡鍒?Phone/Gmail/Camera/Maps/YouTube 绛夊惎鍔ㄥ櫒鍥炬爣 鈫?褰撴垚鏈妭鐐?navigation 琛?append銆俙added==0` patience 姘镐笉瑙﹀彂锛堟瘡甯ц秺鐣岄兘闇插嚭 NEW off-app 鍏冪礌锛夛紝姘歌繙鎾?`MAX_SCROLL_STEPS=8`銆傝繖浜涘够褰辫鎴愪簡 root 鐨?12 鏉″嚭杈癸紝鐐逛簡鍏ㄩ儴 off-app 姝荤銆?- **鐜唴杈圭晫瀹堝崼**锛氭瘡娆′笅婊戝悗銆乤ppend 鍓嶅厛璺?`focus_guard.on_app(frame)`锛?*涓€鏃﹀垽瀹氱寮€ app 绔嬪嵆 STOP 骞朵涪寮冭甯у厓绱?*锛坄steps -= 1` 涓嶈璇ュ抚锛夈€傝繖鏄敮涓€鑳芥尅浣忋€宖ooter 鍏ㄦ槸鏂?off-app 鍥炬爣銆嶇殑鍒ゆ嵁锛坧Hash/added 閮芥尅涓嶄綇锛夈€?- **鎾?raw cap 瑙嗕负鍙枒**锛氭粦婊?`MAX_SCROLL_STEPS` 鑰?patience/bottom 淇″彿鏈Е鍙?鈫?`hit_cap=True` 鈫?WARNING 鏃ュ織鎻愮ず灏鹃儴琛屽彲鑳芥槸瓒婄晫鍨冨溇銆?
**RC2 (HIGH) 鈥?鎰熺煡 VLM 鐨?SoM-id鈫抧ame 鏄犲皠鍦ㄥ瘑闆嗘埅鍥句笂婕傜Щ锛岃竟鏍囩/鍘婚噸閿敊涔?(visual_perception.py + visual_engine.py)**锛?瀵嗛泦锛?0+ 妗嗭級鎴浘涓?VLM 鎶婄湡瀹炶鍚?*缁戝埌閿欒鐨勬**锛圫ettings 琛屼笂鎸備簡鍚姩鍣?app 鍚嶏級銆傛棩蹇楀疄閿わ細`explorer: click 'YouTube' (鐐瑰嚮 'Sound & Vibration' 杩涘叆鈥?`鈥斺€攔eason 璇村浜嗙湡琛屻€乪lem.name 鏄棤鍏?app 鍚嶏紱graph 杈瑰洜姝ゆ爣閿欙紙c1cc9594鈫抏0380e0f 鏍?'YouTube'锛夈€?- **OCR 鍑犱綍鍥炵粦 (perception)**锛歄CR 鏂囨湰鍑犱綍缁戝畾鍒?*鏈**銆佷笉浼氳法 SoM 鏄犲皠婕傜Щ銆傚綋璇ユ鏈夎嚜宸辩殑 OCR 鏂囨湰涓?VLM name 涓庝箣**闆?token 閲嶅悎**锛坄_shares_token`锛屾媺涓佹寜璇嶃€丆JK 鎸夊瓧锛夆啋 VLM name 鏄缁?鈫?鏀圭敤 OCR 鏍囩锛坄source="ocr_rebind"`锛夈€傚畬鍏ㄥ尮閰嶅垯淇濈暀 VLM name銆?- **杈规爣绛剧敤 explorer 鐨勭洰鏍囨弿杩?(engine)**锛欵xplorerAgent 鐪嬬湡鎴浘銆乺eason 鎻忚堪浜嗙湡姝ｆ墦寮€鐨勮锛屾瘮婕傜Щ鐨勬劅鐭?name 鍙潬銆俙_edge_label(elem, reason)`锛歯ame 涓烘硾鍚?绌烘椂鐢?explorer reason锛屽惁鍒欎繚鐣欏叿浣?name銆傝竟 `element_label`/`semantic_description` 閮芥敼鐢ㄥ畠锛実raph 杈瑰弽鏄犵湡瀹炵偣鍑荤洰鏍囥€?
**RC3 (HIGH) 鈥?Android relaunch 姘歌繙鍋囧け璐ャ€宒id not appear銆嶇儳鍏?wall-clock (traversal.py + mobile_ops.py)**锛?`wait_for_app` 闈?a11y 鏍?`filter_nodes_for_app` 闈炵┖鍒ゅ畾銆屽簲鐢ㄥ嚭鐜般€嶃€備絾绾瑙夋ā鎷熷櫒 accessibilityforwarder 宕╂簝 鈫?a11y 鏍戞亽绌?鈫?璇ュ垽鎹?*姘歌繙瓒呮椂** 鈫?姣忔 relaunch/startup_reset 閮借鎶ュけ璐ワ紙鏃ュ織 41 娆?"did not appear" 鑰屽悓杞槑鏄庢敞鍐屼簡 System/Gestures/Network 娣卞眰椤碉級鈫?鏁磋疆 wall-clock 鐑у湪鍋囧け璐ョ殑 relaunch 瓒呮椂涓婏紝56min 鍙埌 ~25 state銆?- **Android 鏀瑰墠鍙板寘鍚嶅垽鎹?*锛氭柊澧?`mobile_ops.wait_for_app`鈥斺€旇疆璇?`current_activity()`锛岃惤鍦ㄧ洰鏍囧寘锛堝惈鍚?app 鍐呭祵瀛愬寘 settings.intelligence锛夊嵆瑙嗕负鍑虹幇锛屼笌 a11y 瀹屽叏瑙ｈ€︺€俙traversal.wait_for_app` 鍦?`is_android_env` 鏃跺鎵樺畠锛堟闈?a11y 璺緞涓嶅彉锛夈€?
鏈湴 + deploy-asr 鍙岀 ast-parse 閫氳繃銆?
**杩愯鐜淇 (deploy-asr 鏈嶅姟鍣? 2026-06-27)**锛氳窇 android_contacts 瑙嗚閬嶅巻鏃?`ImportError: cannot import name 'APP_SEED_FILE' from config`銆傛牴鍥?鏈嶅姟鍣ㄤ粨搴撳仠鍦?`feat/aliyun-provider` 鍒嗘敮锛堥潪 `feat/visual-traversal`锛変笖甯﹀ぇ閲忔湭鎻愪氦鏀瑰姩锛屽叾 `traversal.py` 宸插紩鐢?`APP_SEED_FILE`锛坙ine 72 import / 13671 浣跨敤锛変絾 `config.py` 缂鸿瀹氫箟銆備慨娉曪細鍦ㄦ湇鍔″櫒 `config.py` 鐨?`APP_A11Y_NAME_MAP` 瀹氫箟鍓嶈ˉ鍥?`APP_SEED_FILE` 闈欐€?dict锛堜笌鏈湴 visual-traversal 鍒嗘敮涓€鑷达級锛屾湭鍔ㄥ叾瀹冩湭鎻愪氦鏀瑰姩銆傛湇鍔″櫒 ast-parse + `from ...config import APP_SEED_FILE` 鍙岄獙閫氳繃锛岄亶鍘嗘甯稿惎鍔紙VLM page-identity/app-focus/visual_filter/backtrack 鍚勫眰婵€娲伙級銆?
**ZeroDivisionError 淇 (`gui_rewalk/env/utils.py` `remove_overlap_new.is_inside`, 2026-06-27)**锛歛ndroid_messaging 瑙嗚閬嶅巻璺戝埌 backtrack 闃舵 `detect_and_name 鈫?detect 鈫?remove_overlap_new 鈫?is_inside` 宕?`ZeroDivisionError: float division by zero`锛坲tils.py:249锛夈€傛牴鍥?閫€鍖栫殑闆堕潰绉锛圷OLO/OCR 鍋跺彂浜у嚭 0 瀹芥垨 0 楂?bbox锛夎繘鍏?`is_inside`锛宍intersection / box_area(box1)` 闄ら浂锛涘悓鏂囦欢 `IoU` 宸插闆堕潰绉姞瀹堝崼锛坙ine 239锛夛紝鍞嫭 `is_inside` 婕忎簡銆備慨娉曪細`is_inside` 寮€澶?`a1 = box_area(box1); if a1 <= 0: return False`锛堥浂闈㈢Н妗嗕笉鍙兘"鍦ㄤ换浣曟鍐呴儴"锛屼笖鐭矾闄ら浂锛夈€傛湰鍦?+ deploy-asr 鍙岀 ast-parse 閫氳繃銆?
## 2026-06-28 鈥?VLM 涓诲浜旈」娌绘湰锛堝幓纭紪鐮佽鍒欙紝鎻愯鐩?闄嶅崟姝ユ垚鏈?琛ヨ繛閫氾級

閽堝璧勬繁璇勫 5 椤癸紙鎸変紭鍏堢骇锛夛紝鎶娿€屼汉鐪嬫埅鍥惧氨鑳藉垽銆嶇殑鑴嗗急瀛楃涓?鍑犱綍瑙勫垯鎹㈡垚 VLM-prompt 鍒ゆ柇锛屽粔浠风‘瀹氭€ф鏌ュ彧浣?VLM 鍓嶇殑蹇瓫銆傚叏閮ㄩ€氱敤銆佹闈㈤浂褰卞搷銆傛敼鍔ㄦ枃浠?`visual_filter.py`銆乣visual_perception.py`銆乣visual_agents.py`銆乣visual_engine.py`銆乣visual_backtrack.py`銆佹柊澧?`visual_cache.py`銆傜绾挎祴璇?`tools/test_visual_filter_widen.py`銆乣test_explorer_done_override.py`銆乣test_visual_cache.py`銆乣test_replay_closed_loop.py` 鍏ㄧ豢锛堟棤闇€妯℃嫙鍣級銆?
**P1 (鏈€澶ц鐩栨潬鏉? 鈥?keep/drop 浠庝竴娆℃€?category tag 绉讳氦 ExplorerAgent 鐪嬬湡鎴浘 + danger 缃戞敹绐勫埌"鐐逛笅绔嬪嵆涓嶅彲閫?**锛?鏃ц矾寰勫湪鎰熺煡灞?*纭涪** display/shallow锛圫ettings 涓婚〉鍙暀 2/9銆佸瓙椤?2/10銆?/27銆?/30锛岀粷澶у鏁扮湡瀵艰埅琛岃璇爣 display 闈欓粯涓㈠け锛屼笉鍙仮澶嶏級锛屼笖 `_DANGER_NAMES` 瀛愪覆缃戞妸鏁翠釜 Reset/Erase/Delete-account 瀛愭爲鍦ㄤ换浣?VLM 鐪嬩箣鍓嶆姽鎺夛紙0 琛屽垢瀛橈級銆?- `visual_filter._DANGER_NAMES` 鏀剁獎鍒?shutdown/reboot/power off/log out/sign out/factory reset锛?CJK 鍏虫満/閲嶅惎/娉ㄩ攢/鐧诲嚭/鎭㈠鍑哄巶锛夆€斺€斿彧鐣欑偣涓€涓嬪氨涓嶅彲閫嗚惤鍦扮殑銆俽eset/delete/remove/erase/format/uninstall 绉诲嚭缃戯紝浜?explorer 鍒わ紙鐐硅繘瀛愰〉鎺㈢储浣嗕笉鐐规渶缁堢‘璁わ級銆?- 鏂板 `is_enqueueable`锛堝彧鎺掗櫎 dangerous锛? `candidate_priority`锛坣av=0 < unknown=0 < shallow=2 < display=3锛岀函**鎺㈢储椤哄簭**鎻愮ず锛岄潪 keep/drop锛夈€俙VisualElement.priority` 鏂板瓧娈点€?- `detect_and_name` 涓嶅啀纭涪 display/shallow锛氶櫎 dangerous/瓒婄晫澶栧叏淇濈暀浜?explorer锛宻hallow 浠嶈 node-local銆?- `_EXPLORER_PROMPT` 鎵╁睍锛氬€欓€夊甫浼樺厛绾э紝鍏堢偣 0/1 瀵艰埅锛屽啀鐪嬫埅鍥惧垽 2/3 浣庝紭鍏堥」鏄惁鍏跺疄寮€鏂伴〉锛涘嵄闄╃‘璁ゆ寜閽槑纭?鍙偣杩涘瓙椤垫帰绱€佺粷涓嶇偣绔嬪嵆涓嶅彲閫嗙殑鏈€缁堢‘璁?銆俙ExplorerAgent.decide` 鎸?priority 鍗囧簭灞曠ず鍊欓€夈€?
**P2 (鍘荤蹇岃鍒? 鈥?鍒?`_is_navigation` 绌虹被鍒?done-override锛屼俊浠?ExplorerAgent 鐨?done + 涓€鍙ュ粔浠风‘璁?*锛?`_is_navigation` 姝ｆ槸 standing directive 绂佹鐨?瑙勫垯瑕嗙洊 VLM"锛屼笖鍦ㄧ湡 app 涓婄伨闅撅細瀹冨己鐐硅蒋閿洏/杈撳叆娉曢敭锛堣〃鎯?GIF/璇煶/?123锛夆€斺€攅xplorer 宸叉纭垽涓洪潪鍔熻兘鈥斺€旀瘡娆″己鐐?off-app 鈫?鎱?hard-reset+replay锛坈alendar 鐑у厜棰勭畻銆佺湡瑙嗗浘鍒囨崲鎶藉眽娌℃帰锛夈€?- 鍒?`visual_engine._is_navigation` 鍙?done-override 鍧椼€俙_EXPLORER_PROMPT` 鏀逛负 done 鏃剁敱 VLM **鑷繁鍒楀嚭鎴浘涓婁粛鍙銆佹湭鎺㈢储鐨勭湡鍔熻兘鍏ュ彛**锛坄unexplored` 瀛楁锛? 涓€鍙?杞敭鐩?杈撳叆娉曢敭姘歌繙涓嶆槸鍔熻兘鍏ュ彛锛屽彧鍓╄繖浜涘氨 done"銆傚紩鎿庡彧鍦?`unexplored` 闈炵┖鏃惰鐩?done锛屼笖鍙偣 VLM 鐐瑰悕鐨勯偅浜涒€斺€旀棤瀛楃涓茬櫧鍚嶅崟銆?
**P3 (娣卞簲鐢ㄦ渶澶ч檺鍒? 鈥?Tier-2 hard-reset replay 鏀归棴鐜細閫愭妯℃澘閲嶅畾浣?+ 涓€鍙?same-page 闂紝涓嶅啀鐩瞨eplay鏈鎵嶉獙**锛?鏃?replay 鐢ㄥ彟涓€婊氬姩鍋忕Щ涓嬫姄鐨勫儚绱犲潗鏍囩洸鐐癸紙`_replay_once`锛夛紝绗?k 姝ラ敊鐐广€佸悗缁繛閿侊紝3 鍒嗛挓鍚庢湯绔墠鍙戠幇锛圫ettings 12 澶辫触涓?142 琛?12 鑺傜偣锛夈€?- `_replay_once` 姣忎釜 CLICK 鐢?`visual_relocate.relocate` 鎶婂厓绱犲瓨鐨勫瑙傛ā鏉垮尮閰嶅埌**瀹炴椂甯?*鐐瑰疄鏃朵腑蹇冿紙~80ms锛屾棤 VLM锛夛紱姣忔鐢ㄤ竴鍙?`PageIdentityJudge.same_page`锛堝瓨鐨勬鍚庢埅鍥?vs 瀹炴椂甯э級褰?tripwire锛屼笉鍚岄〉鍗虫棭鍋滆繑 `derailed=True`锛屽洖閫€鑰岄潪璺戝畬宸茶劚杞ㄧ殑閾俱€?- `_relaunch_with_retry`锛氶娆?relaunch 鏃犲彲鐢ㄥ抚鏃堕噸璇曚竴娆★紙"app did not appear"锛夈€?- replay hints 缁?`_register(path, replay_hints)` 涓?path 骞宠瀛橈紙姣?CLICK `{template, post_shot, scroll_steps}`锛宻croll/press 涓?None锛夛紝`backtrack_to(replay_hints=)` 閫忎紶锛涘紩鎿庡湪鐐瑰嚮鏃舵瀯寤哄苟闅?`current_hints` 缁存姢銆傛棤 hints 鏃堕€€鍖栧洖鏃?raw replay锛堝悜鍚庡吋瀹癸級銆?
**P4 (鍗曟鎴愭湰鍗宠鐩栭檺鍒? 鈥?鍥涗釜 VLM 瑙掕壊鍔?pHash 鍐呭瀵诲潃缂撳瓨 + page-identity 鍓嶇瓫 top-K + 婊氬姩鍐?on_app 闄嶉**锛?鍗曟 ~85s锛岄绠楀厛浜?frontier 鑰楀敖銆侾ageIdentityJudge 鍗犲叏閮?VLM 璋冪敤 38%锛?55/921锛変笖闆剁紦瀛橈紝鍗曟 register 鍐呭閿欏€欓€夎繛鍙?6 娆★紱on_app 姣忔瑙傛祴鍚瘡婊氬姩甯э紙~296 娆★級銆傚悓 pHash 甯у氨鏄悓灞忥紝鍐呭瀵诲潃缂撳瓨鏄?*绮剧‘**闈炶繎浼笺€?- 鏂板 `visual_cache.VLMRoleCache`锛坧er-run LRU锛夛細`on_app`/naming 鎸夊崟甯?pHash 閿紝`same_page` 鎸?*鏈夊簭** pHash 瀵归敭銆傚紩鎿庢瀯閫犳椂寤哄疄渚嬪苟娉ㄥ叆 page_judge/focus_guard/perception锛涘紩鎿?per-app 鏂板缓=澶╃劧 per-run 娓呯┖銆?- `PageIdentityJudge`/`AppFocusGuard` 鍔?`cache=` 璧扮紦瀛橈紱`VisualPerception._name_with_vlm` 鎸夋簮甯?pHash 缂撳瓨鍛藉悕缁撴灉锛圷OLO 妗嗙‘瀹氭€ч噸绠楋紝id鈫抧ame 琛ㄥ鍚屽抚浠嶆湁鏁堬級銆?- top-K 鍓嶇瓫宸插瓨鍦紙`VisualStateRegistry.LOOSE_TOPK=4`锛屾渶杩戜紭鍏堬紝鏉€ 6鈫? 鍫嗗彔锛夈€?- scroll-aggregate 鍐?`on_app` 鍙湪**鎻ず浜嗘柊鍏冪礌鐨勫抚**涓婅窇锛堣秺鐣屽瀮鍦惧彧鍦ㄨ繃浜嗙湡搴曢儴鎵嶅啋鍑猴級锛屼笉鍐嶆瘡涓腑娈垫粦鍔ㄩ兘鏌モ€斺€旂渷璋冪敤鍙堜繚鐣欒秺鐣屽畧鍗€?
**P5 (鍥捐繛閫? 鈥?relaunch 閲嶈繛瀛ゅ効瀛愭爲锛氳惤鍦伴〉 re-register 鍒版棦鏈?state 鏃惰鍥炲叾瀛樼殑鐖惰矾寰勶紝涓嶅啀鐢ㄧ┖ path**锛?鏃х爜 relaunch 鍚庣敤**绌?path** re-register 钀藉湴椤靛苟璺宠繃杈癸紝Settings 鍥剧鎴?4 涓?indegree-0 鏍癸紙System銆丯etwork&internet 鏁存潯 Hotspot/VPN/SIMs/Data-Saver 鍒嗘敮鏃犲叆杈癸級锛屽鑳藉姏鍥剧洰鏍囦笉鍙敤銆?- 鏂板 `_register_landed(obs, parent_id, parent_action, parent_label)`锛氳惤鍦伴〉鑻?re-register 鍒版棦鏈?state_id锛?*閲囩敤鍏跺瓨鐨?`action_path_from_root`** 鑰岄潪 []锛屼娇浠庢澶勫缓鐨勫悗浠ｈ竟涓嶆偓绌猴紱鑻ユ湁鍦ㄩ€旂偣鍑昏竟鐪熷疄鍙戠敓鍒欒ˉ鍥?`parent鈫抣anded` 杈广€備袱澶?relaunch 鍒嗘敮锛堢┖鍊欓€?backtrack / 鐐瑰嚮 off-app锛夋敼鐢ㄥ畠锛堢偣鍑?off-app 鍒嗘敮涓嶉噸杩炵偣鍑昏竟鈥斺€斿畠纭疄 off-app 浜嗭紝浣嗕粛璁ゅ洖鏍硅矾寰勪繚杩為€氾級銆?
鏈湴 py_compile 鍏ㄨ繃锛沝eploy-asr import 楠岃瘉瑙侀儴缃茶妭銆?
## 妗岄潰绔彛閫傞厤 (2026-06-30, 灏忓厠) 鈥?瑙嗚寮曟搸璺戞闈?(run_visual_traversal --vm_provider docker)
瑙嗚寮曟搸 `require_a11y_tree=False` 鍦ㄦ闈㈢涓€鏍锋垚绔?鈫?妗岄潰閬嶅巻涔?a11y-free(涓嶄緷璧?AT-SPI,a11y 鍧忎簡鏃犲奖鍝?銆備笁澶勫钩鍙伴€傞厤(鍏?`self._is_touch` 闂ㄦ帶,绉诲姩绔?a11y traversal.py 瀹屽叏涓嶅姩):
- **scroll 鍚敤**(鍘?`_scroll_aggregate_enabled = scroll_aggregate and is_touch` 绂佺敤浜嗘闈?:妗岄潰婊氳疆婊氱殑鏄?*榧犳爣搴曚笅閭ｅ潡**,鎵€浠?`_scroll_aggregate` 妗岄潰鍒嗘敮鍏?`MOVE_TO` 鍐呭鍖轰腑蹇?灞忓箷 1/2 楂?閬垮紑椤堕儴鑿滃崟鏍?,鍐嶆瘡姝?`SCROLL {dy:-DESKTOP_WHEEL_CLICKS}`(pyautogui.vscroll 璐?涓?;patience/viewport-unchanged 寰幆骞冲彴鏃犲叧澶嶇敤;缁撴潫婊氳疆涓婃粴澶嶄綅銆傚叏 try/except,鍑洪敊閫€鍥為《灞忎笉宕┿€?- **STITCH 浠呯Щ鍔ㄧ**:`stitching = _stitch_node_image and _is_touch`(灏弒wipe overlap 鏄畨鍗撹皟鐨?銆?- **鐘舵€佹爮鏉″甫妗岄潰绂佺敤**:`run_visual_traversal.py` 妗岄潰鍒嗘敮 `visual_filter.SYSTEM_UI_BAND_ENABLED=False`(妗岄潰椤堕儴鏄彍鍗曟爮=鐪烾I,鍒)銆?妗岄潰 SCROLL 璧?`osworld_reload.execute_gui_action`(`pyautogui.vscroll(dy)`,闇€ dy;鍘?`_scroll_action` 鍙甫鏂瑰悜浼氭姤閿?鏁呮闈㈢敤 dy 鍔ㄤ綔)銆傜粨鏋滃瓨 `vlm_graphs_desktop/`銆?
## 涓夊眰瀹屾垚搴︽ā鍨嬄风2灞?鍖哄潡绾ц鐩栬处鏈?鎺ョ嚎 (2026-07-08, 灏忓厠)
**鐥呮牴(鍏变韩渚ф爮閲嶅鐐圭殑鏃跺簭娲?**:绗竴椤?A 渚ф爮 `seen_on={A}`(=1)灏氭湭璁ゅ畾鍏变韩 鈫?鐐?A銆岀綉缁溿€嶆椂 `_is_shared_button` 涓?False 鈫?鍙寜 **per-state** 璁拌繘 `mem`(闈?global)銆傝繘绗簩椤?B,娉ㄥ唽鍚庝晶鏍?`seen_on={A,B}`(=2)姝ゅ埢鎵嶅叡浜?鈫?B 涓娿€岀綉缁溿€嶆煡 `mem.is_explored`(global)鈫?褰撳垵娌¤ global 鈫?杩?False 鈫?**鍐嶇偣涓€娆?*銆倁id 涔熸嫤涓嶄綇(B 鐨勩€岀綉缁溿€嶆槸鍙︿竴寮犳埅鍥捐鍓?uid 涓嶅悓)銆?**淇硶(鍖哄潡绾ц处鏈粠姝讳唬鐮佽浆姝?**:`RegionRegistry.clicked`/`unclicked()` 鍘熸槸姝讳唬鐮?鏃犲鍐欒)銆傛柊澧?`mark_clicked(rid,name)`/`is_clicked(rid,name)`(鍚嶅瓧缁?`_norm` 褰掍竴)銆傜粰鍏冪礌鎵?*绋冲畾 region id**(`VisualElement.region_id`,`_regional_scroll_dedup` 鍦?top-frame `register` 鍚?+ below-fold CHANGE 14 鎵撴爣鐐瑰悇璧?`e.region_id=rid`)銆傜偣鍑绘椂 `mark_clicked(elem.region_id, elem.name)`(闈?seed);`_unvisited_candidates` 寮€澶?visited 妫€鏌ヤ箣鍚?鍏堟煡 `is_clicked` 鈫?鍛戒腑鍗充涪(reason=`region_clicked`)銆傚洜 region id **棣栨娉ㄥ唽鍗冲浐瀹氥€佽法椤电敱 name-set 閲嶅彔(鈮?.6)璁ゅ洖**,A 鐐硅繃 B 褰撳満涓?**鏃?`seen_on>1` 棰勭儹寤惰繜**銆傜函鍔犳硶:`region_id` 绌哄(绉诲姩绔?妗岄潰鏃?dedup / 韬唤璁＄畻璺緞)鍏ㄨ嚜鍔?no-op銆俙region_id` 鏄?dataclass 瀛楁 鈫?`to_dict()` 鑷姩甯﹁繘 graph 渚涜川妫€銆傚崟娴?`tools/test_region_click_ledger.py`(鏃犻渶 key,3/3 PASS:棰勭儹娲炲叧闂?褰掍竴涓€鑷?鏈煡 region no-op)銆傝妭鐐圭骇(鍊欓€夎€楀敖鎵嶇Щ鍔?+鎸夐挳绾?visited/uid/mem)鏈凡鍦?姝や负琛ヤ笂涓棿灞傘€?
## 鏂偣缁窇:鍦ㄦ棦鏈?graph.json 涓婄户缁亶鍘?(2026-07-08, 灏忓厠)
**缂哄彛**:`graph.save/load` 鍙瓨鑺傜偣+杈?elements 宸插甫 `region_id/visited/name/group`銆乶ode 甯?`action_path_from_root`+`visual_fingerprint`(pHash)+`screenshot_path`);浣?4 濂楀幓閲?韬唤璐︽湰(`RegionRegistry`銆乣VisualStateRegistry`銆乣_visited_uids`銆乣_explored_groups`銆乣mem`)绾唴瀛樸€侀€€鍑哄嵆涓?鈫?閲嶈窇浼氶噸鎺€?**鏂规(浠?graph.json 閲嶅缓,涓嶅姞 sidecar)**:寮曟搸鏂板 `resume_from_graph(graph)`(best-effort,澶辫触杩?False 鈫?璋冪敤鏂瑰洖閫€鍏ㄦ柊璺?銆俙_rebuild_from_graph` 閫愯妭鐐归噸寤?鈶燻_state_data`(dict鈫抈VisualElement`,`_template`/hints 鏈簭鍒楀寲=None/绌?璧拌繍琛屾椂鍏滃簳);鈶VisualStateRegistry`(pHash 浠?fingerprint 鐩存帴 `hex_to_hash` 鍏嶈鍥?+ `set_buttons` 濉韩浠?瑕嗙洊闆?+ `_region_sets` 鐜扮畻 + `_clicked`);鈶RegionRegistry` 鎸?`region_id` 鍒嗙粍閲嶅缓姣忎釜 `Region`(names/seen_on/clicked,`rebuild_region` 鍐呭綊涓€ + 椤?`_n` 璁℃暟鍣ㄩ槻鏂?region 鎾?id);鈶_visited_uids`/`_explored_groups`/`mem`(global-vs-per-state **闀滃儚鐐瑰嚮鐐?* `_is_chrome_name or _is_shared_button`);鈶_bfs_queue`=鍏ㄨ妭鐐广€?*鍏抽敭**:`_region_set_from_elements` 涓ユ牸闀滃儚 `_arrival_region_set`(璺?`_IDENTITY_CHROME_ROLES`銆乣<2 鍚峘闂ㄦ),閲嶅惎 app 钀藉湴椤垫墠鑳?region-set 璁ゅ洖鏃㈡湁鑺傜偣(鑷姩 MERGE,涓嶆柊寤?root)銆俙_action_count` 缁?`graph._action_counter`銆?**鍏ュ彛**:`run_visual_traversal.py --resume <graph.json>` 鈫?output_root 鎸囧悜璇ュ浘鐩綍(鍐欏洖鍚屼竴浠?涓嶅姞 _HHMMSS);`visual_engine.run(resume_path=)` 閫忎紶銆傚崟娴?`tools/test_resume_from_graph.py`(鏃犻渶 key,dummy stub 鏋勯€犲紩鎿?2/2 PASS:璐︽湰閲嶅缓+椤礏宸茬偣渚ф爮椤广€愬紓 uid銆戜粛琚?region 璐︽湰涓?鏈偣椤逛繚鐣?鍧忓浘 fail-safe 杩?False)銆?*鏈疄鏈洪獙**:瀵瑰啋鐑熷浘 `--resume` 璧蜂竴杞湅钀藉湴椤佃鍥?鏃ュ織 "rset=... SAME as <root> -> MERGE")+ 宸叉帰渚ф爮涓嶅啀鐐广€?*鏈仛**:涓嶅簭鍒楀寲 `_template`/replay_hints(鐜扮畻/閫€鍖栧厹搴?;涓嶅仛 UI 鍙樻洿澧為噺 diff銆?
## 2026-07-10 鈥?鎸囧畾璧峰妯℃€佹鐨勭湡瀹為亶鍘嗛棴鐜?
瀹炴満澶嶇幇琛ㄦ槑鎰熺煡灞傝兘姝ｇ‘寰楀埌 `modal=True`銆佹ā鎬佽竟鐣屽強 Identity/IPv4/IPv6/Security 鍥涗釜椤电锛屼絾 `VisualTraversalEngine.run()` 鍦ㄦ牴鑺傜偣鐧昏鍓嶇敤 `force_first=True` 璋冪敤 interruption dismisser銆傜己灏戔€滃綋鍓嶆ā鎬佹灏辨槸寰呮祴鐩爣鈥濈殑浠诲姟涓婁笅鏂囨椂锛宒ismisser 浼氶€夋嫨 Cancel锛屽鑷存牴鑺傜偣閫€鍥?Settings 涓婚〉銆備慨澶嶄负鏄惧紡鍚姩绛栫暐锛歚preserve_initial_surface=True` 鏃跺綋鍓嶇敾闈㈢洿鎺ユ垚涓烘牴鑺傜偣骞惰褰?startup policy锛涢粯璁?`False`锛屽喎鍚姩娓?welcome/update 鐨勮涓轰笉鍙樸€備究鎹?`visual_engine.run(...)` 宸查€忎紶锛屾寮?CLI 鏆傛湭鏆撮湶銆?
椤电闂幆鍚屾椂淇涓夊锛?
- `VisualElement.selected` 鐢?VLM grounding/naming 缁撴瀯鍖栬繑鍥炪€傚綋鍓嶆縺娲婚〉绛惧湪 `_regional_scroll_dedup` 涓洿鎺ュ啓鍏?region 鐐瑰嚮璐︽湰锛沗_unvisited_candidates` 涔?fail-safe 鎺掗櫎 selected銆俙back=True` 鐨?Cancel/Close 鍙暀缁?Router 鎭㈠锛屼笉鍙備笌鏅€氭帰绱€?
## 2026-07-10 鈥?Settings 鏂板浘鐭祴锛歡rounding 閲嶈瘯鍘绘斁澶т笌椤甸潰鍚嶈惤鐩?
- 鐪熸満 Background 椤佃繛缁崱鍦?75 绉掕竟鐣岋紝Network/Bluetooth 鍒欓渶绾?53鈥?9 绉掞紝璇存槑鏁村睆 grounding 鐨勫ぇ缁撴瀯鍖栬緭鍑轰笉閫傚悎缁熶竴鐭?timeout銆俫rounding 鐜颁娇鐢ㄥ崟娆?150 绉?role timeout锛堝彲閰嶇疆锛夛紝涓嶅啀宓屽閲嶈瘯锛涘叾瀹冭涔?role 淇濇寔 75 绉掍笌鍘?transport policy銆?- 绌?grounding 鏄灛鏃舵劅鐭ュけ璐ワ紝涓嶆槸鍚堟硶椤甸潰銆俙_register()` 鐜板湪 fail-closed 鎶涘嚭 `PerceptionUnavailable`锛涗富寰幆淇濆瓨宸叉湁鍥俱€佹爣璁?`perception_unavailable`銆佷笉鍐欑┖鑺傜偣/杈逛笖涓?commit 鍊欓€夛紝鍚庣画 resume 鍙噸璇曘€?- `ArtifactWriter.save_node()` 鏂板 `page_name`锛屽悓姝ュ啓鍏?`state_meta.json` 涓?`node_index.json`銆?- startup dismisser 瀵规甯搁〉鐨?`done` 缁撴灉浣跨敤鏄庣‘鏃ュ織锛屼笉鍐嶆妸 force-first 妫€鏌ュ啓鎴愨€渋nterruption flagged鈥濄€?- 绂荤嚎楠岃瘉瑕嗙洊 role timeout銆乤rtifact page name銆乧ache銆乵odal candidate銆佺┖鎰熺煡鍜屽姩浣滀簨鍔★紱鍓嶄袱杞湡鏈轰骇鐗╀粎浣滃け璐ヨ瘉鎹紝涓嶄綔涓哄彲鎺ュ彈鍥俱€?- 绗笁杞?2-action Settings 鎺㈤拡纭 Background 鍦?75.6s 鎴愬姛锛? 鑺傜偣/2 鏉¤惤鍦伴獙鏀惰竟銆乴int 0 error銆俈LM ledger 鏄剧ず grounding 鍗犵害 79% 妯″瀷寤惰繜涓庣害 87% completion tokens锛屽悗缁甯告彁閫熷簲浼樺寲 grounding 杈撳叆/杈撳嚭鑼冨洿锛岃€屼笉鏄户缁皟 retry銆?- `_arrival_region_set` 瀵?tab bar 澧炲姞 `tab_selected:<normalized-name>`銆侷Pv4 涓?IPv6 鍗充娇鍏变韩鍚屼竴涓?tab bar 鍜岃繎浼?form body锛屼篃浼氬洜涓や釜婵€娲?token 鍙戠敓鏇挎崲锛坰ymmetric diff=2锛夎€岀櫥璁颁负涓嶅悓鑺傜偣锛涜韩浠借川妫€涓嶅啀鎶婅繖绉嶆樉寮?sibling-tab 宸紓璇姤璀︿负杩囧害鍒嗚銆?- reviewer 鐨勬ā鎬佹 self-heal 鍙兘鎹㈡垚涓€鎵瑰叏鏂板厓绱犮€傛柊 `_retag_healed_regions` 澶嶇敤鍚屽抚 segmentation cache锛屾妸 `region/region_id/region_bbox` 涓?selected coverage 閲嶆柊缁戝畾锛岄伩鍏嶆柊鍏冪礌缁曡繃 region 鐐瑰嚮璐︽湰骞堕噸澶嶇偣鍑诲凡瑕嗙洊椤电銆?
鏂板 `tools/test_live_modal_traversal.py`锛氬彧闄勭潃杩愯涓殑 VM锛屼笉 reset/relaunch/close锛涘惎鍔?`tools/live_status.py` 璋冭瘯鍙帮紝鎵撳紑 review/region-match debug锛屼繚瀛橀妫€銆佹瘡娆℃劅鐭ャ€佺嫭绔嬫埅鍥俱€佸浘涓庢渶缁?JSON 鎶ュ憡銆俙tools/test_modal_candidate_policy.py` 绂荤嚎楠岃瘉 selected/back 鍊欓€夈€佽嚜鎰堥噸缁戝拰 sibling-tab 韬唤銆?
楠岃瘉锛圵indows + VMware Ubuntu Settings 鈥淣ew Profile鈥濓紝Qwen `qwen3.7-plus`锛夛細

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -B tools/test_modal_candidate_policy.py
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -B tools/test_live_modal_traversal.py --expect-tab Identity --expect-tab IPv4 --expect-tab IPv6 --expect-tab Security --max_actions 3 --max_states 8
```

缁撴灉锛氱绾?PASS锛涘疄鏈?4 states / 3 actions锛屽垵濮?IPv4锛屼笁鏉¤竟 Identity銆両Pv6銆丼ecurity锛屾渶缁堝洓椤电鍏ㄨ鐩栵紝missing=[]銆乶o_effect=0銆乮nconsistent=0銆乵odal_closed=False銆傛姤鍛婏細`_scratch/modal_traversal_20260710_114716_8692/modal_test_report.json`銆傚凡鐭ョ己鍙ｆ槸琛ㄥ崟瀛楁 grounding 浠嶆湁 reviewer 鍛婅锛屾湰杞病鏈夊～鍐?鎻愪氦琛ㄥ崟锛涗袱娆?VLM timeout 鐢辨棦鏈夐噸璇曡嚜鍔ㄦ仮澶嶃€?
## 2026-07-10 鈥?鏃?Settings 鍥捐川閲忛棶棰樼殑鐢熶骇绾ч棴鐜?
瀵?`result_visual_setting/20260708/setting/graph.json` 鐨勬埅鍥惧鏍哥‘璁わ細鏃х偣鍑婚棴鐜彧鍦?`scroll_steps>0` 鐨勫睆涓嬪厓绱犱笂杩愯锛涘綋鍓嶅彲瑙佷晶鏍忓厓绱犵洿鎺ユ部鐢ㄨ妭鐐圭櫥璁版椂鐨勪腑蹇冦€傜獥鍙?甯冨眬绾?20鈥?0px 婕傜Щ鍚庯紝`Displays` 鐨勬棫涓績钀藉埌 `Power`锛宍Removable Media` 钀藉埌 `Printers`锛宍Color` 钀藉埌 `Removable Media`銆傚悓鏃?`ClickEffectVerifier` 鍙湪 review debug 涓褰曪紝閿欒杈逛粛鍏堝啓杩涘浘锛泂witch/toggle 鍙堣 explorer 鐐瑰嚮骞舵墿鎴愮姸鎬侊紝Search Locations 涓夐〉绛捐啫鑳€涓哄叚鑺傜偣锛屾渶缁堝湪 `max_states` 鍓嶈€楁帀棰勭畻銆?
淇鍒嗗洓灞傦細

1. **鎵€鏈夌偣鍑诲疄鏃堕噸缁?*锛歚_live_center_for` 鍦ㄥ疄鏃跺抚閲嶆柊瀹氫綅锛涘 `nav_sidebar/tab_bar` 鐨勬枃瀛楁帶浠讹紝VLM 鍙彁渚涜涔夊悕绉帮紝鏈€缁堢偣鍑荤偣鐢卞尯鍩熷唴 OCR 绮剧‘閿氬畾鏂囧瓧涓績锛岄伩鍏?VLM 鍚嶇О姝ｇ‘浣?bbox 閿欑粦鐩搁偦琛屻€傚叾浠栨帶浠跺啀鎸夊綋鍓?grounding 鐨勫綊涓€鍚嶇О/region 鎴栨ā鏉垮尮閰嶃€俙scroll_steps=0` 涔熷己鍒舵墽琛岋紝鎵句笉鍒版垨鍑?region 鍗?fail-closed銆?2. **浜嬪姟寮忚鐩栨彁浜?*锛氫笉鍐嶅湪瀹氫綅/鎵ц鍓嶅啓 visited銆乽id銆乺egion clicked銆乬roup銆乵emory銆傚け璐ラ噸璇曚竴娆★紱杩炵画澶辫触鍙€€浼戝綋鍓嶈妭鐐瑰€欓€夛紝涓嶅啓鍏变韩璐︽湰锛屽叾浠栭〉闈笂鐨勫悓涓€渚ф爮椤逛粛鍙皾璇曘€?3. **瀵艰埅璇箟楠屾敹鎴愪负鐢熶骇 gate**锛氶粯璁ゅ navigation/nav_sidebar/tab_bar 鐐瑰嚮鎵ц before/after verifier銆俙no_effect` 鎴?`transitioned_inconsistent` 涓嶅啓鐩爣璇箟杈癸紝骞舵妸鐗╃悊钀藉湴鐘舵€侀殧绂?閲嶅悓姝ャ€傚彲鐢?`--no_navigation_effect_verify` 鏄惧紡鍏抽棴锛屼絾璐ㄩ噺浼氶檷绾с€?4. **鏁版嵁鐘舵€佷笉鎵╁浘**锛歩nput/checkbox/radio/switch/toggle/slider/combobox 绛夐粯璁や繚鐣欏湪鍏冪礌/鑳藉姏娓呭崟骞惰涓?node-local锛涘敮涓€鍙楁帶渚嬪鏄粨鏋勫寲纭銆佸畨鍏ㄥ彲閫嗕笖浼氭敼鍙樺姛鑳藉彲杈鹃泦鍚堢殑 `function_set` 鐘舵€佹帶浠躲€傝渚嬪涓€娆″彧灞曞紑涓€涓姸鎬佽酱骞跺疄闄呮仮澶嶏紝閬垮厤閰嶇疆鍊肩瑳鍗″皵绉尋鍗犻〉闈㈤绠椼€?
鏂板浘璇佹嵁 schema锛氳妭鐐瑰啓 `page_name`锛涜竟鍐?`effect_verdict/effect_note/landing_verified/target_page_name`銆俙graph_lint.py` 鏂板鎴柇銆佽繍琛屾椂 unreachable銆佽嚜鐜巼銆佸鑸竟 region銆佹湭楠屾敹瀵艰埅杈瑰拰寮傚父 effect 妫€鏌ャ€傚鏃?41 鑺傜偣 Settings 鍥剧幇鎶ュ憡 7 WARN锛堟棫鐗堟槸 0 WARN锛夛紝鍖呮嫭 `max_states`銆? 涓?unreachable銆?4 鏉℃棤 region 瀵艰埅杈广€?8 鏉℃湭楠屾敹瀵艰埅杈瑰拰 25.7% 鑷幆銆?
绂荤嚎鍥炲綊锛歚tools/test_graph_quality_guards.py`銆乣test_edge_attribution.py`銆乣test_region_click_guard.py`銆乣test_region_click_ledger.py`銆乣test_overlay_split.py`銆乣test_modal_candidate_policy.py`銆乣test_resume_from_graph.py`銆乣test_click_effect_verifier.py`銆乣test_explorer_done_override.py` 鍧囬€氳繃銆傛柊澧?`tools/test_live_sidebar_rebind.py` 闄勭潃褰撳墠 VM 骞跺惎鐢ㄨ皟璇曞彴锛氱涓€杞垚鍔熷鐜?`Displays` 琚偣鍒?`Mouse & Touchpad`锛寁erifier 鍒ら敊骞舵嫆缁濊涔夎竟锛涗慨澶嶅悗灏嗕汉涓哄亸绉?45px 鐨勫潗鏍囩簿纭洖缁戝埌 `[140,687]`锛?px 璇樊锛夛紝钀介〉鍒や负 `transitioned_consistent`锛屾姤鍛婂湪 `_scratch/sidebar_rebind_20260710_132127_6408/sidebar_rebind_report.json`锛孷M 鏈?reset/close銆?
姝ｅ紡鍏ュ彛褰撴椂鏂板浜嗗彧鐪?`stop_reason` 鐨勫垵鐗?`--require_complete` 闂ㄧ锛涘綋鍓嶅疄鐜板凡鐢卞叓椤硅瘉涔︽浛浠ｏ細CLI 鎬诲啓 `completion.json`锛岃鍙傛暟鍙帴鍙?`status=certified`锛宍frontier_empty` 鍗曠嫭涓嶅啀绛変簬瀹屾垚銆係ettings 鍚姩鑴氭湰褰撴椂浠?40 states/150 actions 鎻愰珮鍒?80/300銆備粛涓嶈兘鐢ㄢ€滆妭鐐瑰緢澶氣€濇垨鍗曠嫭 `graph_lint.py --strict` 浠ｆ浛褰撳墠瀹屾垚璇佷功銆?
## 2026-07-10 鈥?VLM 璋冪敤鍘婚噸涓庢垚鏈彲瑙傛祴鎬э紙绗竴闃舵锛?
鏈樁娈靛彧娑堥櫎璐ㄩ噺绛変环鐨勯噸澶嶈皟鐢紝涓嶄慨鏀?Explorer 鍐崇瓥鍜屽鑸?click-effect 闂ㄧ锛?
1. `VLMCallLedger` 鍖呰绾瑙夌洰褰曞唴鍏ㄩ儴 `predict_mm`锛屽啓 `vlm_calls.json`銆傛寜 grounding銆乺egion segmentation銆乵erged/annotation review銆丒xplorer銆乸age identity銆乤pp focus銆乮nterruption銆乧lick effect 绛夎鑹茬粺璁?logical calls銆乼ransport attempts銆乧ache hits銆乪rror銆佽€楁椂鍜?token銆?2. VLM grounding 瀵规埅鍥?exact MD5 缂撳瓨**鍘熷鍝嶅簲**锛涘懡涓悗閲嶆柊瑙ｆ瀽骞舵瀯閫犳柊鍏冪礌锛岄伩鍏?visited/region/id/template 绛夎繍琛屾€佽法瑙傚療鍏变韩銆傛櫘閫氶噸澶嶈瀵熷鐢紱reviewer 鐨?`force_refresh` 蹇呴』鐪熻皟鐢ㄦā鍨嬨€?3. 寮哄埛鍝嶅簲鍏堜笉杩涘叆 canonical cache銆傛ā鎬?reviewer 鍦ㄦ渶澶氫袱娆″己鍒蜂腑閫夋嫨 wrong 鏈€灏戣€咃紝闅忓悗鍚屾椂鎭㈠鑾疯儨鍏冪礌銆丼oM銆乸age/window/modal/system/interruption銆乤ll-elements銆乶ode-local 涓?raw response锛屽苟鍙彁鍗囪 winner銆傜┖/澶辫触 grounding 涓嶈礋缂撳瓨銆?4. Region segmentation 澧炲姞 exact-MD5 LRU锛涘己鍒风┖缁撴灉淇濈暀姝ゅ墠鎴愬姛鍒嗗尯锛屼笉鐢ㄧ灛鏃惰秴鏃舵瘨鍖栬韩浠姐€傛瘡娆?`_arrival_region_set` 鍏ュ彛娓呯┖涓婁竴甯?region 鎻忚堪銆?5. merged QA 鍙湁鍦ㄥ厓绱?id/name/bbox 涓?SoM exact digest 閮戒竴鑷存椂锛屾墠鑳戒綔涓烘ā鎬?self-heal 鐨勭涓€娆?verdict锛涙渶缁?debug 璁板綍 winner 鐨?review锛屼笉璁板綍琚窐姹扮殑鍘熷 verdict銆?
`tools/test_visual_cache.py` 瑕嗙洊 exact grounding fresh-object銆乫orce bypass銆乼entative 涓嶆薄鏌?canonical銆乺egion 绌哄己鍒蜂繚鐣欍€乺egion 鎻忚堪鏃╅€€娓呯┖銆丼oM-bound review signature銆亀inner 鍏冩暟鎹?鍝嶅簲鎻愬崌鍜?ledger 钀界洏銆傜浉鍏虫棦鏈?modal/region/overlay/effect/edge/resume/timeout 鍥炲綊鍧囬€氳繃銆?
瀹炴満鍙楁帶 A/B锛歚tools/test_live_sidebar_rebind.py --target Network --stale-offset-y 45` 鍦ㄥ悓涓€甯ф晠鎰忛噸澶?grounding锛屽苟娓呴櫎鍗曢」 region cache 鍚庨噸璁裤€傜粨鏋滀负 3 logical calls锛坓rounding/region/click-effect 鍚?1锛? 2 cache hits锛涙棤缂撳瓨鐨勫悓涓€鍙楁帶搴忓垪闇€ 5 calls锛屽嵆鏈牱鏈噺灏?40%銆傚鑸粛绮剧‘钀藉埌 Network锛屾姤鍛?`_scratch/sidebar_rebind_20260710_140207_25708/sidebar_rebind_report.json`銆傝鏁板瓧涓嶆槸瀹屾暣 Settings 鍥剧粨璁猴紱涓嬩竴闃舵闇€鍏堣窇鍏ㄥ浘鏀堕泦瑙掕壊鍒嗗竷锛屽啀璇勪及 Explorer 姣忕姸鎬佽鍒掑拰鏉′欢寮?verifier銆?
## 2026-07-10 鈥?绾瑙変富閾鹃€€鍑?legacy traversal import 鍥?
- 鏂板鍏变韩 `src/core/app_lifecycle.py` 鍚庯紝`run_visual_traversal.py` 鐨?startup/relaunch 涓?`visual_engine.py` 鐨?window bbox/surface 鍧囩洿鎺ヤ緷璧栬 529 琛屾ā鍧楋紝涓嶅啀瀵煎叆 13k+ 琛岀殑 A11y `graph/traversal.py`銆?- `StateGraph` 鐨?`UIElement` 渚濊禆鏀逛负 `TYPE_CHECKING`锛涚函瑙嗚瀵煎叆鍥惧眰涓嶄細椤哄甫鍔犺浇 `app_filter`銆傛棤 a11y 鐨勭獥鍙ｈ仛鐒﹁矾寰勪篃鍙湪鐪熺殑鎷垮埌 a11y tree 鏃舵墠鍔犺浇 parser銆?- 鍖呭叆鍙ｄ笉鍐嶉粯璁?import/export 宸查€€浼戠殑 `VisualBacktracker`锛涘巻鍙?`visual_backtrack.py` 浠嶅彲鏄惧紡瀵煎叆锛屽綋鍓?Router 琛屼负涓嶅彉銆傛鍓嶈 `.gitignore` 鐨?`_*.py` 璇悶鐨勬湰鍖?`__init__.py` 澧炲姞绮剧‘渚嬪锛屽叾浠栦复鏃惰剼鏈粛淇濇寔蹇界暐銆?- 鏂板 `tools/test_architecture_boundaries.py` 鍥哄寲 import銆佸吋瀹?re-export銆乥box銆佸惎鍔ㄨ皟鐢ㄩ『搴忎笌鍏冪礌 schema銆傜浉鍏宠瑙夌绾垮洖褰掗€氳繃锛涙湰娆＄函缁撴瀯璋冩暣鏈繍琛?VM/VLM銆?- 涓嬩竴鎷嗗垎浼樺厛绾т笉鏄户缁埗閫犲皬鏂囦欢锛氬厛鍔犱富寰幆琛ㄥ緛娴嬭瘯锛屽啀鎶?resume銆佸疄鏃?targeting銆佹粴鍔?region 涓変釜鑱岃矗宀涳紱鏈€鍚庢墠鎷?670 琛?`run()` 鐨勪簨鍔￠樁娈点€?
## 2026-07-10 鈥?鍘熷瓙 resume銆乺un/Router 琛ㄥ緛涓庨€€褰瑰洖閫€鍣ㄥ垹闄?
- 鏂板 `visual_resume.py`锛氫粠鍥鹃噸寤哄厓绱犮€佽韩浠姐€乺egion銆乵emory銆乿isited/group銆乫rontier 鍜?action count 鏃跺彧浣跨敤鍏ㄦ柊涓存椂瀵硅薄锛涙垚鍔熷悗 Engine 鎵嶄竴娆℃€т氦鎹㈠苟閲嶇粦 Router/Explorer銆俙None` 鎴栧悗缁潖鑺傜偣涓嶆薄鏌撳綋鍓?runtime锛屼篃涓嶄慨鏀硅緭鍏ュ浘 hook銆?- 鏂板 `test_visual_run_state_machine.py`锛岀洿鎺ヨ窇鐪熷疄 `VisualTraversalEngine.run()` 鐨勭函鍐呭瓨杈圭晫锛岄攣瀹氣€滄墽琛?鈫?璁℃暟 鈫?鐧昏钀界偣 鈫?璇箟楠屾敹 鈫?鎻愪氦瑕嗙洊 鈫?鍐欒竟鈥濋『搴忥紝骞惰鐩栦覆椤垫潵婧愰殧绂汇€侀噸缁戦噸璇曞拰璺敱鍚庝笅涓€杞啀鐐瑰嚮銆?- 鏂板 `test_visual_router.py` 6 涓幇褰瑰绾︼細shared-region 缁ф壙銆丅FS 鏈€灏?hop銆乹uarantine 缁曡銆佸凡鐭ュ亸鑸噸瑙勫垝銆丅ACK 涓婃函銆佺‖閲嶇疆鐪熷疄钀界偣涓?unknown fail-closed銆?- 鍒犻櫎宸叉棤浠讳綍鐢熶骇 import 鐨?`visual_backtrack.py` 鍜?5 涓棫 replay/LCA/arrival 娴嬭瘯銆備粛鏈変环鍊肩殑 pHash cache 鎶栧姩銆佸€欓€夐〉浣滅敤鍩熴€侀敭鐩樻姂鍒躲€佸厔寮熼〉韬唤涓庣湡瀹?edge-source 闅旂宸茶縼鍒扮幇褰规祴璇曘€傚彟鍒犻櫎浠嶅鍏ュ凡閫€褰?`signature_verdict` 鐨勫兊灏告祴璇曞拰纭紪鐮佹棫鎵规鐨?`verify_signature_identity.py`锛岀幇褰硅韩浠界敱 region-set銆乥utton containment銆乴ist/overlay 濂戠害瑕嗙洊銆傚寘杈圭晫娴嬭瘯瑕佹眰鏃ф枃浠跺拰 import spec 閮戒笉瀛樺湪銆?- 鎵╁ぇ鍥炲綊鍚屾淇浜嗘祴璇曟湰韬殑濂戠害婕傜Щ锛歜ox-binding shim 琛?review/region/data-control锛宻croll-locate 鐢ㄧ函 stub 鏄庣‘妯℃嫙 OCR 鍚嶇О纭锛宻ystem-UI 娴嬭瘯鏀逛负 canonical 鍖呭鍏ワ紝鎵嬪伐鍥剧墖 probe 鏃犲弬鏃剁粰鍑?usage銆傝繖浜涗慨姝ｄ笉鏀圭敓浜х瓥鐣ワ紝浣嗚娴嬭瘯閲嶆柊鐪熸鎵ц鐜板焦鏂规硶銆?- 鍏ㄩ儴涓?Windows 鏈湴绂荤嚎/绾唴瀛橀獙璇侊紝鏈搷浣?VM锛屾湭璋冪敤 VLM銆俽esume 浠嶉渶涓€娆＄湡瀹炶惤鍦伴〉缁窇闂幆銆?
## 2026-07-10 鈥?鍗遍櫓鍚嶇О瀹夊叏缃戝疄鐜板榻?
`visual_filter.effective_category()` 鏃╁凡鎸夎璁″彇娑堝悕绉板瓙涓插己鍒跺垎绫伙紝浣?Engine 鍚庣画鐨?`VisualElement.is_dangerous()` 浠嶄繚鐣欐棫瀹借〃锛屽鑷?`Restart tour`銆乣Format SD card` 绛変粛鍦ㄥ€欓€夐樁娈佃闈欓粯鍓帀銆傜幇鏀逛负瑙勮寖鍖栧悗鐨勭洿鎺ヤ細璇濈粓姝㈠悕绉扮簿纭尮閰嶏細`Restart`銆乣Shut down`銆乣Log out`銆乣Factory reset` 绛変粛浣滀负鏃犳ā鍨嬭皟鐢ㄧ殑鏈€灏忓畨鍏ㄧ綉锛屽甫鏇撮暱涓婁笅鏂囩殑瀛愰〉鍏ュ彛浜ょ粰 VLM category 鍜?Explorer 鏈€缁堢‘璁ょ鐐硅鍒欍€俙test_visual_filter_widen.py` 鐩存帴閿佸畾 Engine 瀹為檯璋冪敤鐨?`is_dangerous()`锛屼笉鍐嶆祴璇曞凡涓嶅瓨鍦ㄧ殑 filter 瀛愪覆瑕嗗啓銆傛湰鏀瑰姩涓嶆柊澧?VLM 璋冪敤锛屼粎鍋氱绾块獙璇併€?
## 2026-07-10 鈥?live monitor 杩涚▼缁撴潫鎽樿

`run_visual_traversal.py` 鐜板湪浠?`--pid <traversal-pid>` 鍚姩 `tools/live_status.py`銆?缁撴潫鍒ゅ畾缁戝畾鐪熷疄杩涚▼瀛樻椿鐘舵€侊紝涓嶆妸闀挎椂闂存棤鏃ュ織鐨?grounding 璇垽涓洪€€鍑恒€傝繘绋嬬粨鏉熷悗锛?鐩戣鍙颁紭鍏堣鍙栨棩蹇椾腑 `graph output -> ...` 鎸囧悜鐨?`graph.json`锛屾姤鍛婅妭鐐广€佸疄娴嬭竟銆佸凡鎻愪氦
鍔ㄤ綔銆侀〉闈㈢ず渚嬶紱鏈€鏂?`[杩涘害]` 琛岃ˉ鍏呭尯鍧楁暟銆佸鑸鐩栧拰浠嶆湁鍊欓€夌殑鑺傜偣鏁般€傛棩蹇椾晶绱
off-app/闂€€锛堝苟褰掑洜鏈€杩戠偣鍑伙級銆丷outer hard reset銆侀殧绂荤偣鍑?杈广€乂LM/grounding 澶辫触鍜?鍏抽敭鎰熺煡澶辫触銆傚巻鍙?monitor 鍒濈増鏇炬妸 `stop_reason=frontier_empty` 鐩存帴鏄剧ず涓衡€滈亶鍘嗗凡瀹屾垚鈥濓紱
褰撳墠瀹炵幇宸叉敼涓鸿鍙栧悓涓€ fail-closed 瀹屾垚璇佷功锛屽彧鏈?`completion_status=certified` 鎵嶆樉绀哄畬鎴愶紝
鍏朵綑鍧囨樉绀哄仠姝㈠苟鍒楀嚭澶辫触 check锛宍frontier_empty` 鍙綔涓哄仠姝㈠師鍥犺鏄庛€?
鍏煎鍏ュ彛 `python tools/live_status.py <log>` 淇濈暀锛涙棤 PID 鏃跺繀椤昏瀵熷埌鏄庣‘鐨勭幆澧冨叧闂棩蹇?鎵嶇粨鏉燂紝涓嶉噰鐢ㄩ潤榛橀槇鍊笺€傜绾垮洖褰?`tools/test_live_status_summary.py` 瑕嗙洊瀹屾暣缁撴潫涓庨绠楀仠姝?涓ょ被鎽樿锛屽彟閫氳繃 `py_compile` 鍜?`git diff --check`锛涘皻鏈瓑寰呮鍦ㄨ繍琛岀殑鏃х洃瑙嗗彴瀹炰緥缁撴潫锛?鍥犳鏈妭涓嶅０鏄庡綋鍓嶇獥鍙ｅ凡鐪熸満楠岃瘉锛堟棫杩涚▼涓嶄細鐑姞杞芥柊鏂囦欢锛夈€?
## 2026-07-10 鈥?闂€€鎸夐挳鎴愪负鍙寔涔呭寲鐨勭粓鎬?
Settings 100/200 resume 瀹為獙鍦?14 鑺傜偣鍚庡弽澶嶇偣鍑?`Sound`锛氬潗鏍囨瘡杞兘鍦ㄥ疄鏃跺抚閲嶆柊瀹氫綅锛?浣嗙偣鍑诲悗鐩爣绐楀彛娑堝け涓烘闈紝Focus Guard relaunch 鍥?Network锛涙棫浠ｇ爜鏃笉鎻愪氦鎴愬姛瑕嗙洊锛屼篃
涓嶇疮璁¤ off-app 澶辫触锛屾墍浠ュ€欓€夋案杩滀繚鎸?pending銆傚疄楠岀敱鐢ㄦ埛鍏抽棴 VM锛屽浘淇濇寔 14 鑺傜偣/
14 瀹炴祴杈癸紱浠ヤ笅淇鍙仛绂荤嚎楠岃瘉銆?
`AppFocusGuard` 鐨勬棦鏈夊崟娆″垽鏂柊澧炵粨鏋勫寲 `kind`锛歚target_missing`銆乣crash_dialog`銆?`external_app`銆乣system_overlay`銆乣unknown/on_app`銆傚畬鏁?verdict/kind/reason 杩涘叆鍘?app-focus
cache锛岃皟鐢ㄦ暟涓嶅彉锛涙ā鍨嬫紡 kind 鏃朵粠 reason 鍏煎褰掍竴銆侲ngine 鍙妸鍓嶄袱绫昏涓烘寜閽鑷寸殑
`app_crash`锛岄伩鍏嶆妸 `Learn more` 鎵撳紑 Chrome 璇О涓哄簲鐢ㄩ棯閫€銆?
宕╂簝浜嬪姟涓嶈皟鐢?`_commit_explored()`锛氭簮鍏冪礌鍐?`visited/abnormal_reason/abnormal_detail`锛?`StateGraph.abnormal_buttons` 璁板綍 state/element/region/reason/detail/action/timestamps锛屼笖涓嶇敓鎴?杈广€佷笉鍐欐垚鍔?region clicked 鎴?memory銆傝繍琛屾椂寮傚父 ledger 瀵圭ǔ瀹氬叡浜尯鍧椾娇鐢?`(region_id, normalized button)`锛屽洜姝ゅ叾瀹冭妭鐐逛笂鐨勫悓涓€渚ф爮鎸夐挳涔熻烦杩囷紱鏃?region_id 鏃剁敤
`(state_id, uid/name)`锛岄伩鍏嶆妸鍏跺畠椤甸潰鐨勫悓鍚嶆櫘閫氭寜閽鏉€銆俙visual_resume.py` 鍘熷瓙閲嶅缓璇?ledger锛屽苟鍦ㄦ仮澶?registry/region/memory 鏃舵槑纭帓闄ゅ紓甯稿厓绱犵殑鈥滄垚鍔熻鐩栤€濄€傛棫鍥炬棤瀛楁鎸夌┖
璐︽湰鍏煎銆?
`tools/live_status.py` 澧炲姞 `[寮傚父鎸夐挳]` 浜嬩欢鍜岀粨鏉熸憳瑕佸瓧娈点€傜绾块獙璇佽鐩?target-missing 涓?external-app 鍒嗙被/cache銆佺湡瀹?run-loop 鐨勪竴娆＄偣鍑烩啋relaunch鈫掕褰曗啋鏃犺竟鈫掍笉鍐嶉噸璇曘€佸叡浜?region 鐨勮法鑺傜偣 resume 璺宠繃锛屼互鍙?graph/monitor round-trip锛涚浉鍏崇幇褰瑰洖褰掑拰 `py_compile`
閫氳繃锛屽皻鏈仛淇鍚?VM 澶嶈窇銆備袱杞疄鏈烘棩蹇楀叡鍚?21 娆?Sound鈫掓闈紙鍙︽湁涓€娆?Learn more
鎵撳紑 Chrome锛屾湭璁′綔 crash锛夛紱褰撳墠 14 鑺傜偣/14 杈?Settings 鍥惧凡鍥炲～鍞竴
`Sound/app_crash/r1` 寮傚父璁板綍銆傚姞杞借繖浠界湡瀹炲浘鍋氱函鍐呭瓨 resume 鍚庯紝Sound 鍊欓€変负 False銆?`region_registry.is_clicked(r1, Sound)` 涓?False锛岃鏄庘€滆烦杩団€濇病鏈変吉瑁呮垚鎴愬姛瑕嗙洊銆?

## 2026-07-15 staged runtime/state boundary

当前 canonical 边界如下：

- `runtime/bootstrap.py`：启动、on-app、settle、resume/root adoption。
- `runtime/scheduling.py`：无候选、scroll audit、route/backtrack，以及候选的 stateful-before/risk 计划。
- `runtime/execution.py`：live scroll/rebind、action event、env.step；不处理 landing。
- `runtime/landing.py`：path/hints、落点登记、stateful-after、effect/quarantine 和 verified transition/coverage/stateful commit。
- `runtime/recovery.py`：route/relaunch observation 与 unknown landing fail-closed。
- `runtime/completion.py`：stop reason、graph/VLM ledger 保存和 debug close。
- `runtime/runner.py`：以 RunCursor/StageDirective 串联 bootstrap、scheduling、execution、recovery、landing 和 completion；候选计划仅在返回明确的 `EXECUTION` 指令时进入执行。
- `state/matching.py`、`identity.py`、`regions.py`、`registry.py`：分别负责元素匹配、Page/Variant、region-set 纯函数和状态账本。
- `state/registration.py`：新节点/revisit 的登记事务、artifact 和 capability 写入。
- `state/map_guided.py`：flag-gated post-click 一跳候选确认；从 durable elements
  读取模板，以唯一模板证据或 current-first 多图 VLM（含显式 `NEW`）判定旧状态。

`GUIWALK_MAP_GUIDED_ID=1` 时，landing 只在一次 post-click `_register` 调用期间
传入 `source_id/clicked_label`。Router 从 verified/replayable view 依次给出直接目标、
source 和稳定排序的一跳邻居。确认旧状态后 registration 复用其 elements 与
Page/Variant 账本，跳过 arrival grounding、region segmentation 和 scroll aggregate；
不确定时保持现有完整登记。局部 VLM 判 `NEW` 后只 ground 当前帧一次，并复用结果做
全局 button/page-name 候选重判。继承后的第一个 live target 若无法重绑定，execution
清除继承标记并强制一次 map-bypass 完整登记；恢复成功不记 click failure，且不会循环。
未设置 flag 时上述 judge/template/transition 快速路径均不运行。

Landing rejection keeps action success separate from physical position. For an
ordinary navigation `no_effect`, no transition, coverage, visited state, or
capability is committed. If post-click registration nevertheless identifies the
current frame as a different state that was already registered, runtime adopts
that known state's persisted path/replay hints and the current observation for
the next `RunCursor`. A newly created landing, missing runtime state, stateful
action, `uncertain`, or `transitioned_inconsistent` result does not use this
shortcut; its existing fail-closed/recovery policy remains authoritative.

Router separates shared discovery coverage from source-local transition proof.
Host-relative top-bar/overflow actions stay `shared_pending` with `dst=None`.
Only explicit peer-navigation regions (tabs, bottom navigation, navigation
sidebars) may borrow a unique `peer_inferred` destination from a verified or
selected occurrence. The route still performs the real click, verifies the live
landing per hop, and persists a source-local `direct_verified` edge. Until that
edge exists, region/global coverage cannot prune the peer control on that source;
selected/current is page identity evidence, not click coverage. Semantic
map-guided registration does not trust `peer_inferred` as a direct expectation.
Homogeneous `group` collapse is limited to parameterized content rows. Peer
navigation regions (`tab_bar`, `primary_navigation`, sidebars, bottom nav, and
navigation bars) never enter `_explored_groups`: sibling destinations such as
Alarm, Clock, and Bedtime each require their own source-local transition evidence.
Resume preserves the same rule, and completion cannot certify one peer tab as a
`group_alias` of another.

Natural Router Back/Close ascents are persisted after identity verification as
regionless virtual navigation actions: `action_type=BACK`,
`selector.virtual_action=navigate_back`, and
`effect_kind=return|dismiss_overlay`. They have no element id/label or Region,
never enter Region coverage, capability promotion, target grounding, or normal
frontier selection, and replay only through the injected Back primitive. Click
edges use `forward|peer_navigation`. This harvests recovery work already
performed and introduces no pre-emptive A→B→A→B validation loop or general VLM
transition classifier.

Router clicks return a structured result that distinguishes `not_attempted`,
`dispatch_unknown`, and `action_dispatched`. A target-resolution failure and an
`env.step()` exception can replan or hard reset but must never trigger
compensating Back, because the latter cannot prove whether input was delivered.
In semantic mode, Router click resolves
exactly one durable element by source state, stable region id, and normalized
name, then uses target-only grounding/reviewer. Router identify inventories the
fresh frame and read-only-aligns every local `bN` block to existing `rN`
concepts before state identity; NEW/unresolved blocks return unknown without
minting, observing, marking seen, updating representatives, or writing registry
identity. Semantic Back inventories explicit back/close controls and target-
grounds one. Android system Back remains a special non-grounded Router primitive:
when no visible control exists, or grounding that control fails, touch recovery
tries system Back once and verifies the landing. If it exits a true root page,
the existing on-app recovery remains the fallback. Legacy
`detect_and_name()` remains available to non-semantic runtime paths; this phase
does not claim full old-detector removal.

Offline verification after the final edits: the focused Router/block/grounding/
run-state/map-guided command reported `74 passed, 1 warning` after the final
dispatch-unknown correction; targeted
`py_compile`, framework `compileall`, and all other Tier-3 gate commands passed.
The architecture script passed the updated Engine `<2800` line gate (2799) and
then stopped on a pre-existing dirty-tree compatibility gap: `visual_agents.py`
does not export the already-added `BlockIdentityJudge`. A later bounded Android
Clock run with Qwen `qwen3.7-plus` at
`artifacts/runs/mobile_clock_qwen_router_phase1_20260717/20260717/android_clock`
produced 9 states / 8 actions and stopped normally at `max_states`. Alarm and
Clock each retained their own verified direct `More options` popup edge; the
reached Bedtime node had no inherited direct popup edge. Root-page recovery
logged `touch_root_without_control` instead of sending raw Back, and the old
`state_restore_failed` crash did not recur. The budget ended immediately after
Bedtime registration, so physically opening Bedtime's menu remains outside this
bounded live run.

A bounded Android Clock rerun is stored at
`artifacts/runs/mobile_clock_cursor_resync_noclean_20260717/20260717/android_clock`.
It produced 7 states / 6 verified actions without repeating the earlier
popup-belief/base-frame source mismatch: recovery merged the relaunched Clock
frame into known state `76111f90`, then Alarm, Timer, Stopwatch, and Bedtime were
traversed successfully. Screen saver was classified as a real transition to the
Android full-screen instruction, so this run did not execute or emit the new
`no_effect_cursor_resync` branch; the exact branch remains covered by the offline
state-machine regression. The live run eventually stopped incomplete at
`state_restore_failed` because Router tried to reuse the Clock-home `more options`
edge from Bedtime and recovery landed off-app. This is a separate routing/shared-
region replay issue and is not traversal-completion evidence.

### 2026-07-17: bbox-free semantic inventory experiment

`run_visual_traversal.py --semantic_inventory` selects an experimental,
fail-closed perception contract. It takes precedence over `--vlm_grounding` and
does not load OmniParser. A new observation is described as page/surface
metadata plus semantic blocks and their elements. Neither block nor element
inventory accepts geometry. Compatibility `VisualElement` objects carry
`bbox_xywh=[0,0,0,0]`, `center=[0,0]`, and
`geometry_status=semantic_only`. Inventory blocks receive observation-local
`b0...` ids only; a content hash is no longer authoritative cross-frame block
identity.

Before page identity/frontier construction, semantic registration makes one
strict `normalized_1000` batch block-localization call. The resulting boxes are
used only to crop anonymous block images and never enter elements,
`semantic_blocks.json`, or graph geometry. A bounded online resolver considers
prior-frame concepts first, matching-page roster concepts when available, then
a small app-local fallback. One batch `BlockIdentityJudge` call aligns the
current crop atlas to a candidate atlas. SAME means the same persistent,
visually adjacent functional cohort; selection/enabled state, badges, dynamic
values, theme, partial overlays, and fallible role-label drift are allowed.
Incompatible surface families or materially different visual/function cohorts
are NEW. Unknown, duplicate, malformed, uncertain, or failed mappings fail
closed to registry-minted new `rN` concepts. `identity_anchor` is descriptive
metadata only and cannot mint/split identity.

For each newly registered semantic state, the same already-localized crop is
also written to `node_artifacts/<state_id>/region_<region_id>.png`. This adds no
VLM call and does not persist the transient bbox. Missing, invalid, or fully
out-of-bounds localizations produce no Region image and log a warning; they are
never replaced with the whole node screenshot. Legacy role-named Region
composites remain readable but are not rewritten by this path.

Registration enters this branch after map-guided inheritance and before legacy
whole-page detection. It skips arrival region segmentation, scroll/stitch
aggregation, whole-page SoM review/self-heal, UID crops, and relocation
templates. Page/Variant identity, selected-navigation facts, frontier,
capability discovery, graph state, and node artifacts continue to be produced
from semantic names and the semantic block set. Empty inventory raises
`PerceptionUnavailable`; there is no fallback to bbox-producing perception.
Revisit inventory may add new semantic elements but never creates templates.
The pre-click `_frame_state_id` check consumes stable `region:rN` values plus
`tab_selected:<name>` state tokens directly and therefore cannot re-enter
geometric segmentation or SoM. This keeps a shared navigation block stable
while selected destinations remain distinct page states. Region-keyed clicked
coverage immediately prunes an action on later occurrences before scheduling.

Page identity is independent of the semantic inventory's Region set. The
map-guided source/action/neighbor decision selects an existing Page or creates a
new one, after which its Page ID is immutable. A base surface and an overlay can
still be separate executable States/Variants while sharing the already assigned
Page; a selected peer-navigation destination reaches another Page through a
verified transition rather than by hashing its selected token. Resume consumes
the persisted Page ID. It does not rebuild identity from inventory or Region
tokens.

Click geometry is observation-local. `VisualPerception.ground_target()` receives
one stored target plus its block/state/sibling context and accepts only
`coordinate_space=normalized_1000` with a positive xyxy `bbox_1000` and an
in-box `click_point_1000`. After strict 0..1000 validation, code deterministically
converts that geometry to the original screenshot's pixel dimensions.
`LiveTargeting` then uses the target-specific reviewer, whose image contains
exactly one red box and one blue crosshair/circle at the actual pixel click
point, and whose prompt names the intended target. Acceptance requires both the
box to enclose the target and the point to lie on a safe clickable part. A review
rejection reason is supplied as a correction hint to one force-refresh target
call and one more review;
failure is closed as `target_not_found` or `target_review_rejected`. The live
geometry is never written back to the bbox-free stored element, including for
stateful controls. Whole-page SoM remains unchanged for legacy modes and is not
generated or reviewed in semantic mode.

Perception-only mode writes `semantic_inventory.json` and `elements.json`.
`--target_element NAME` additionally writes `target_grounding.json` and, when a
candidate exists, `target_overlay.png`. Node artifacts add
`semantic_blocks.json`; graph/state metadata record
`perception_mode=semantic_inventory` and `geometry_mode=target_only`. New
arguments and persisted fields are optional so old graphs and callers remain
compatible. During live traversal, every semantic target call is also written
to a monotonically numbered directory under `target_grounding_attempts/`.
`input.png` is the original current frame; `overlay.png` exists when a candidate
does and contains one red bbox plus the blue actual-click marker; `result.json`
contains the semantic target context, local attempt number, full raw/normalized/
pixel/image-size diagnostic, grounded geometry, and reviewer result/reason.
Rejected, accepted, grounding-failed, and reviewer-unavailable attempts remain
distinct. The sink is diagnostic-only: an IO failure logs a warning but cannot
approve, reject, or otherwise change a click outcome, and no bytes are inserted
into graph/observation JSON. A pre-fix real-Qwen Clock probe returned
`bbox=[19,850,177,950], click=[98,900]`: interpreting it as pixels placed the
box at y=850, while normalized conversion on 720x1280 points to the bottom bar
near `[14,1088,127,1216]` / `[71,1152]`; the target reviewer correctly rejected
the pixel interpretation. This is failure evidence that motivated the contract,
not a post-fix live validation. Dense/scrolling-page recall and repaired mobile
Clock behavior remain to be measured.

Every online block resolution also writes a best-effort numbered directory
under `block_identity_attempts/` with current/candidate atlases, current crops,
and UTF-8 `result.json` containing descriptors, bounded allowed candidates,
the bounded raw model response, parsed verdict, validated mapping/reasons, and
newly minted concepts. Artifact IO failures do not change the verdict. Resume
rehydrates persisted concept ids and clicked coverage from graph elements, so
legacy semantic hash ids remain loadable. Representative crops are currently
runtime/audit evidence and are not rehydrated into `RegionRegistry`; after a
fresh resume, visual concept matching is therefore intentionally limited and
fails closed by lazily minting concepts until new representatives exist. This
is a known validation gap, not seamless semantic-identity resume.

Live Clock evidence is available at
`artifacts/runs/mobile_clock_online_block_identity_20260717/20260717/android_clock`.
The incomplete run produced 7 states / 8 actions and 9 semantic observations;
the VLM ledger records 9 block-localization calls and 8 block-identity calls,
confirming that the first frame minted `r1-r4` without alignment. The first
overflow popup reused `r1-r4` and minted only `r5`, the later Alarm popup reused
`r5`, and the Clock base revisit mapped exactly `r1-r4` and merged the original
`76111f90` rather than creating a third Clock home. Shared header `r1` and bottom
navigation `r4` survived tab changes, with selected tokens separating states.
All seven persisted `semantic_blocks.json` files had zero bbox hits.

The run stopped incomplete at `state_restore_failed` because of an independent
off-app/popup cursor misattribution; it is block-identity evidence, not traversal
completion. It also exposed the pre-fix semantic Page-anchor drift: Clock base
and popup had different Page IDs because VLM anchor labels changed. The subsequent
stable-concept Page-anchor fix was projected offline over these seven real node
artifacts: Clock base equals Clock popup, Alarm base equals Alarm popup, and Clock
differs from Alarm. A short post-fix live rerun never started because host ADB
reported `fdevent interrupt socketpair: no buffer space`; therefore no post-fix
live Page-anchor or completion claim is made.

A bounded Android Clock run then exposed three pre-fix runtime blockers. First,
the VLM described bottom navigation tabs as `stateful=true`; the inventory
contract now states that tab selection is represented only by `selected`, and
the parser clears state semantics for every `type=tab` while preserving real
switch/toggle controls. Second, semantic map-guided arrival is bypassed unless
the exact normalized clicked label already has a verified direct destination;
an unexplored More-options popup therefore reaches semantic NEW/merge
registration instead of being inherited as its source page. Third, landing
commit now receives the source cursor explicitly: a same-state committed no-op
keeps source path/hints/observation, while a different state adopts the new
ones. A post-sink bounded Android Clock smoke run at
`artifacts/runs/mobile_clock_grounding_audit_20260717/20260717/android_clock`
exited 0 at `stop=max_actions` with 2 states / 1 action and persisted
`target_grounding_attempts/000001_more_options/{input.png,overlay.png,result.json}`.
Its raw `bbox_1000=[882,56,1000,117]`, `click_point_1000=[941,86]`, and
`image_size=[720,1280]` converted to `bbox_px_xyxy=[635,72,720,150]` and click
`[678,110]`. The reviewer accepted the one red bbox plus blue actual-click
marker, and the click opened the More-options popup as a new semantic state.
This validates the live audit path as a bounded smoke test, not traversal
completion.

`visual_engine.py` 只保留依赖装配、共享运行能力及薄 `run/_register/_register_landed` wrapper；`visual_state.py` 是旧 import 兼容 shim。runtime/state canonical 文件不得反向 import Engine。运行阶段继续通过 `host._register`，因此离线 monkeypatch seam 不变。逐文件维护入口见 [visual_traversal_file_map.md](visual_traversal_file_map.md)。

上述 2026-07-15 runtime/state 模块化工作没有修改当时的 prompt、阈值、graph
schema、action event 顺序、landing verification、stateful restore 或 CLI/output
合同；后续 map-guided 功能已新增独立的多候选 identity prompt。离线验证命令和结果
记录在 `design/CURRENT_FRAMEWORK.md`；未运行 VM、真实 VLM 或 live 点击。

## 2026-07-18 当前语义遍历路径

Map-guided identity 默认开启，VLM 只看当前截图与候选文字描述。Router identify
不调用 inventory/block alignment；Router Back 从 source state 读取已存元素和
surface_kind。只有进入 semantic registration 的 NEW 页面才解析 block，并可用
现有 bounded scroll loop 补齐多屏 inventory；bbox-free 元素按
role/name/category/type 去重。semantic region_set 仅保留为证据，不主导状态合并。

点击效果由 before/after pHash 与注册后的 state identity 本地推导；已删除
ClickEffectVerifier 及 prompt。stateful structured facts 仍可覆盖通用结论。
interruption 在 semantic 模式只用 semantic inventory，并优先复用同帧缓存。
Android 路径先读 foreground activity/package，信号不可用时才调用 VLM focus
guard。legacy SoM 分支由 registration 的显式 early return 隔离。
# Local HTML transport and landing hash normalization (2026-07-18)

The visual engine can run unchanged over `vm_provider=local_html`: by default the
environment supplies only viewport screenshots and generic pixel actions, while
semantic inventory, live target grounding/review, Page/Region identity, Router,
graph artifacts, scroll ledger, and completion remain canonical.

Two fixture-only diagnostics isolate traversal from perception cost.
`--fixture_oracle_inventory on` injects exact current-visible semantic blocks and
elements, registers Region concepts deterministically, and skips semantic
inventory, block localization, and block identity. `--fixture_oracle_grounding
on` resolves a stored target to one visible declared control and skips target
grounding and target review. Missing or ambiguous targets fail closed. Both
switches default off and are rejected outside `local_html`; Page/Variant identity,
frontier policy, landing, Router, backtracking, scroll, completion, and graph
schemas remain unchanged.

Landing before/after pHash equality may be a Python `bool` or `numpy.bool_`.
`runtime/landing.py` now normalizes either through `bool()` before creating the
existing `no_effect` / `transitioned_consistent` evidence. `None` remains
unclassified. This fixes a post-click `NoneType` crash without changing verdicts,
state identity, attempt commitment, or completion policy.

# Persistent exact VLM response replay (2026-07-18)

`run_visual_traversal.py` now accepts the opt-in
`--vlm_response_cache <directory>` for both full traversal and
`--perception-only`. `VLMCallLedger` computes a SHA-256 request identity from the
role, agent/model identity, response-affecting generation settings, exact UTF-8
prompt, and exact image array contents. A hit returns the stored raw response
without transport attempts. Any prompt, image, model, temperature, token limit,
top-p, or thinking-mode change creates a different key automatically.

The cache is disabled by default. Each cache entry stores request hashes and the
raw response, but not prompt text or screenshot bytes. `vlm_calls.json` preserves
logical-call accounting and adds `persistent_cache_hits` at total and per-role
levels; cached transport attempts and tokens are zero. This cache is distinct
from the existing per-run pHash LRUs: those tolerate same-view jitter inside one
traversal, while persistent replay requires byte-exact request evidence across
runs. Explicit semantic inventory, block localization, target grounding, and
legacy grounding `force_refresh` calls bypass persistent replay so reviewer
correction/resampling semantics remain live.

Focused live evidence on the saved synthetic Mingle Contacts page used Qwen
`qwen3.7-plus`: the seed made one transport attempt with 45.573 seconds model
latency; an identical new-process replay used zero transport attempts, one
persistent hit, 0.01 seconds cache latency, and 2.06 seconds wall time. Both
parsed inventory artifacts were SHA-256 identical. This is a one-page saved-frame
record/replay check, not a full traversal or Android-device result.

Final focused regression after the force-refresh boundary:
`python -m pytest -q tests/test_persistent_vlm_response_cache.py
tests/test_semantic_inventory_grounding.py tests/test_visual_run_state_machine.py
tests/test_synthetic_mobile_fixture.py tests/test_app_lifecycle_preserve.py
tests/test_landing_change_evidence.py tests/test_local_html_env.py --basetemp
artifacts/scratch/pytest_vlm_cache_force_final2` -> `46 passed in 6.15s`;
targeted `py_compile` -> exit 0.

## 2026-07-19 Router 页面身份不接收导航目标

Router 的页面身份回调现在只接收当前 observation。每次 Back、计划内跳转或
偏航恢复后，语义身份判断都从当前截图面对至多五个已有页面描述和 `NEW`，独立返回
实际落地页面；最终导航目标不再作为 expected 候选或单候选提示传入。Router 随后才把
实际身份与计划目标比较并决定成功、重规划或失败。这样不会因为“希望到达 Chats”而把
实际的 Weekend Plan 截图判成 Chats。

# Opt-in block-first inventory pilot (2026-07-18)

`--perception-only --block_first_inventory` now exposes a research-only
two-stage path. `semantic_block_discovery` receives the full frame and returns
page/surface metadata plus all current active-surface blocks with transient
`bbox_1000`, but no elements. `--target_block <local_id-or-unique-role>` then
crops exactly one discovered block and calls `semantic_block_inventory`, which
returns only that block's bbox-free elements. The normal traversal and existing
`SEMANTIC_INVENTORY_PROMPT` remain unchanged.

The second-stage contract separates the shortest stable semantic `name` from
`visual_evidence`, prohibits secondary status text in the name, and treats
hidden permission/availability as unknowable unless visibly established. Both
stages use the exact persistent response cache independently; prompt or crop
changes miss automatically.

Real-Qwen saved-frame A/B on Mingle Contacts and Settings is recorded in
`artifacts/runs/mingle_block_first_ab_20260718/REPORT.md`. Contacts retained 6/6
usable required-control recall and improved oracle block roles from 2/4 to 4/4,
but did not improve function classification (5/6 in both); the add icon's
semantic label remained weaker than the whole-screen baseline. Settings retained
4/4 recall, improved required-control function classification from 2/4 to 4/4,
removed one duplicate interactive control, and split 4/4 visible oracle blocks
instead of 2/4. A selected block cost discovery 8.545 s plus 4.520-7.248 s versus
34.014 s whole-screen on Settings. These are two saved synthetic pages, not a
general benchmark or live traversal result.

Verification: `python -m pytest -q tests/test_block_first_inventory.py
tests/test_persistent_vlm_response_cache.py tests/test_semantic_inventory_grounding.py
tests/test_visual_run_state_machine.py tests/test_synthetic_mobile_fixture.py
tests/test_app_lifecycle_preserve.py tests/test_landing_change_evidence.py
tests/test_local_html_env.py --basetemp artifacts/scratch/pytest_block_first_final`
-> `49 passed in 11.01s`; targeted `py_compile` -> exit 0.

## Full-frame selected-block input follow-up

The experiment additionally supports `--block_image_mode full`. The model sees
the unmodified complete screenshot while the prompt supplies the selected
block's `bbox_1000` and requires every returned element center to stay inside.
The actual model input is saved as `selected_block_full.png`; crop remains the
default.

Real Qwen follow-up did not support promoting full mode. Contacts top-app-bar
semantic naming stayed `Add` rather than `Add contact`, while contact-list output
leaked `New friends` and `Groups` from the adjacent shortcuts block. Settings
obeyed all four block scopes and preserved correct classifications. Contacts
full mode was slower for both tested blocks; Settings average inventory latency
was 6.198 s full versus 5.884 s cropped. Because the response has no geometry,
neighbor leakage cannot be deterministically post-filtered. Full mode remains an
explicit diagnostic option; crop remains the safer default. Final focused
regression: `50 passed in 10.06s`; targeted `py_compile` -> exit 0.

## Full-context plus crop input follow-up

`--block_image_mode context_crop` sends two ordered images: the complete frame
for page context, then the selected crop as the sole allowed element source. The
cache key covers both images and the mode-specific prompt. Artifacts save
`selected_block_context_full.png` and `selected_block_crop.png`, while
`block_inventory.json` records `image_mode=context_crop` and
`input_image_count=2`.

Real Qwen recovered strict scope: the Contacts list no longer leaked adjacent
shortcuts and all tested Settings blocks remained correct. It did not improve
the icon semantic name (`Add` remained `Add`) or any required-control metric.
Contacts calls were slower than crop-only; three Settings content blocks averaged
5.540 s dual-image versus 5.435 s crop-only. Consequently crop remains default,
context+crop is a diagnostic/fallback for context-sensitive blocks, and full-only
remains the least safe mode. Final focused regression: `51 passed in 19.01s`;
targeted `py_compile` -> exit 0.
