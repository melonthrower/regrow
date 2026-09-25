# GUI-ReWalk framework history through 2026-07-19

> Archived snapshot of the former all-in-one current-state and change-log file.
> It is historical evidence, not the current source of truth.

鏈€鍚庢洿鏂帮細2026-07-14锛坵orking tree锛\?
鏈枃鍙弿杩板綋鍓嶅彲缁存姢銆佸彲缁х画婕旇繘鐨勬鏋躲€傚甫鏃ユ湡鐨勫疄楠?璇勫鏂囨。鏄巻鍙茶瘉鎹紝涓嶈兘瑕嗙洊鏈枃銆?
## 2026-07-15 repository boundary addendum

Below-fold 定位职责现位于 `grounding/locate.py`：`LocateRuntime` 负责 region map、map servo、OCR/name anchor 与 closed-loop `_scroll_locate`，并通过 `LocateContext` 接收显式依赖；它不反向 import Engine。`visual_engine.py` 保留同名薄 wrapper 和 `SCROLL_MAP_*` 兼容导出，物理长度由 3,257 行降至 2,652 行。通用视口滚动、region scroll 和 stitch 仍分别位于 `grounding/scroll.py`、`grounding/region/scroll.py`、`grounding/stitch.py`。

当前视觉运行时使用四组 canonical package：`visual_traversal/agents/`（VLM roles）、
`grounding/region/`（region registry/scroll）、`navigation/`（frontier/router）和
`prompts/`（有效提示词）。
`visual_engine.py` 只通过显式 `FrontierContext` 把账本与回调交给 frontier policy；canonical
模块不得反向 import Engine。旧 `visual_agents.py`、`region_registry.py`、`visual_router.py`
仅是薄兼容导入。离线测试统一位于 `tests/`；`tools/` 只放正式工具。新 visual traversal
默认输出根为 `artifacts/runs/`，历史根级运行、日志、诊断、压缩包和 scratch 已原地迁到
`artifacts/*/legacy/`。导入图和评测集分别位于 `data/imported/` 与 `data/evaluation/`；
论文工作和历史记录分别位于 `research/paper/` 与 `research/history/`。
`collections/`、`research/`、`issues/` 仍是持久数据/证据。

The desktop lifecycle also supports a repository-owned deterministic Dayline
fixture via the canonical `--app_name dayline`; `--app_name "rewalk fixture"`
remains a compatibility alias.  The maximized Chrome app-mode window uses a
1365x900-oriented desktop layout with sidebar navigation and ordinary document,
activity, weekly-summary, settings, and product copy; fixture/oracle terminology
is not shown in the application UI.  `synthetic_app/` contains the standalone app,
machine-readable Page/Variant/block/control/transition/scroll oracle, an oracle
inspector, current-prompt Qwen-shaped response fixtures, a fixture-specific graph
validator, and reference long-page captures.  Launch installs only the generated
HTML below `/tmp/gui_rewalk_fixture` and uses a dedicated Chrome profile; no
network or host/guest shared folder is required.  This is a test environment, not
a new traversal data contract, graph schema, or production application adapter.

Android lifecycle also supports the repository-owned Mingle communication
fixture through `--app_name mingle`, mapped to
`com.guirewalk.mingle/.MainActivity`. The first launch in an AVD session installs
`synthetic_mobile_app/mingle-debug.apk` with `adb install -r`; later launches in
that session reuse the installation, normal restarts preserve data, and explicit
`--clean_start` may clear Mingle because it is allowlisted. The fixture contains
8 Pages, 42 page controls, 3 long scroll scopes, 3 active surfaces, an inspector,
17 current-prompt Qwen-shaped responses, a graph validator, and reference images.
This adds known Android fixture evidence only; graph schema, prompt, Router, and
completion semantics are unchanged, and offline/APK checks are not live-emulator
or real-Qwen certification.

For fast application-level validation, `--vm_provider local_html --html_path
<file>` runs the unchanged visual engine over a headless Chromium transport.
`LocalHTMLGUIGenEnv` provides only fixed-viewport PNG screenshots and generic
pixel actions by default. Two explicit fixture-only diagnostics are available:
`--fixture_oracle_inventory on` supplies the exact visible block/element
inventory and skips semantic inventory, block localization, and block identity
model calls; `--fixture_oracle_grounding on` supplies exact current-frame click
geometry and skips target grounding and target review. Both default to `off`,
require `vm_provider=local_html`, and do not change Page/Variant identity,
Router, scheduling, scroll, graph, or completion behavior. The backend skips
VM/AVD construction, APK installation, and the desktop 60-second startup wait,
then closes all browser resources at the end. It does not validate Android
system chrome, ADB, touch physics, permission dialogs, or lifecycle.

Visual traversal and single-image perception optionally accept
`--vlm_response_cache <directory>`. This persistent cache is disabled by default
and replays a raw response only for an exact role/model/generation-settings,
prompt, and image-content match. Prompt or screenshot changes therefore miss
automatically. Cache entries contain hashes and the raw model response, not the
prompt text or screenshot bytes; `vlm_calls.json` reports
`persistent_cache_hits` separately. This is a model-call optimization and does
not change graph, Page/Variant, Router, completion, or environment contracts.
Explicit `force_refresh` perception/grounding calls bypass persistent replay so
reviewer-driven correction still obtains a fresh model sample.

滚动相关职责现已按功能进入 `grounding/scroll.py`（通用视口滚动）、
`grounding/region/scroll.py`（区域分割/稳定/去重）和 `grounding/stitch.py`（长图拼接与
tiled perception）；region 身份与覆盖账本位于 `grounding/region/registry.py`。
这些模块只接收显式 context/callback，不反向 import Engine；旧
`visual_stitch.py` 仅保留兼容导入。`visual_engine.py` 保留同名薄 wrapper 与旧常量导出，
当前约 4.6k 行。后续候选是 state identity/resume 与 runtime orchestration。

## 1. 褰撳墠缁撹

妗嗘灦鐜板凡缁熶竴涓虹函鎴浘/VLM 璺嚎锛屽苟琛ラ綈浠庡姛鑳藉浘鍒?M13 瀹炴満閲囬泦鐨勭幇褰逛富閾撅細

```text
鎴浘瑙傚療
  鈫?瑙嗚鎰熺煡涓庤涔?grounding
  鈫?Page/Variant 韬唤 + 鍖哄煙/鍏冪礌/婊氬姩瑕嗙洊璐︽湰
  鈫?鍦ㄧ嚎 portable capability discovery锛坉iscovered锛?  鈫?VisualTraversalEngine + VisualRouter
  鈫?graph.json schema v3 + ActionEdge.attempts + verified routing view
  鈫?fail-closed traversal completion certificate
  鈫?鐪熷疄鍔ㄤ綔涓庤惤鍦伴獙鏀舵檵鍗?verified capability
  鈫?鍙€夌绾?capability 褰掍竴/鏃у浘琛ュ綍
  鈫?鍗曞簲鐢?鑱旈偊 capability-backed instructions
  鈫?VisualCollectionExecutor锛圡13锛? EngineVisualAdapter
  鈫?CollectionWriter.write_visual_episode + 鍙€?VLM 瀹屾垚鍒ゅ畾
```

鏃?A11y 鍥鹃亶鍘嗐€佹棫闅忔満娓歌蛋銆乣ScenarioExecutor`銆佹棫 scenario/atom/chain pipeline 鍙婂叾杩愯鍏ュ彛宸茬粡鍒犻櫎锛屼笉鍐嶆彁渚涘吋瀹瑰眰銆傜幆澧?observation 鍙寘鍚埅鍥惧拰鍙€?terminal锛涘姩浣滀粛閫氳繃 pyautogui/ADB 鎵ц銆?
鍥句娇鐢ㄤ袱绾ц韩浠姐€俙state_id` 鏄?Router 鑳借瘑鍒拰鎵ц鐨勫叿浣?`Page@Variant` 鑺傜偣锛涚ǔ瀹?`page_id` 鑱氬悎鍚屼竴鑱岃矗鍜屾牳蹇冪粨鏋勭殑璇箟椤甸潰锛宍variant_id` 淇濆瓨鎴浘鍙瀵熺殑鍔熻兘/鏁版嵁/鐜鏉′欢銆傝摑鐗欏叧闂笌鎵撳紑銆侀椆閽熺┖鍒楄〃涓庡凡鏈夐椆閽熶粛鏄笉鍚屾墽琛岃妭鐐瑰拰 variant锛屼絾鍒嗗埆褰掑叆鍚屼竴涓?Bluetooth page 鍜?Alarm Home page锛汚larm Home銆丒ditor銆丏etail 淇濇寔涓嶅悓 page銆傚叿浣撻椆閽熸椂闂淬€佸厜鏍囥€乼ooltip銆佹粴鍔ㄤ綅缃瓑瀹炰緥/鐬椂鏁版嵁涓嶅簲鎷?page 鎴?variant銆?
鎴浘銆佸厓绱?bbox 鍜岃瑙?fingerprint 鏄湰娆℃劅鐭ャ€乺esume 涓庤川妫€鐨?sidecar 璇佹嵁锛涙寔涔?`ActionEdge` 鍜?capability recipe 鍙繚瀛樿涔?selector 涓庤繍琛屾椂鍙傛暟锛屼笉渚濊禆鎴浘鏂囦欢鍚嶆垨鍘嗗彶鍧愭爣銆傜湅鍒版帶浠跺彧鑳戒骇鐢?`discovered` 鑳藉姏锛涘彧鏈夌湡瀹炲姩浣滃凡鏈夋槑纭?target 涓?`landing_verified=True` 鎵嶆檵鍗?`verified` 骞惰繘鍏ュ彲璺敱瑙嗗浘銆?
## 2. 褰撳墠鍏ュ彛

| 鍏ュ彛 | 鐘舵€?| 浣滅敤 |
|---|---|---|
| `gui_rewalk/run_visual_traversal.py` | 褰撳墠涓诲叆鍙?| 妗岄潰/Android 绾瑙?capability-driven 閬嶅巻锛涢粯璁や繚鐣?app 鏁版嵁锛宍--clean_start` 鎵嶆竻 app state锛汣reate/Add 鏄櫘閫?frontier锛涙瘡杞啓 `completion.json`锛宍--require_complete` 鍙帴鍙楀畬鎴愯瘉涔︼紱涔熸敮鎸佸崟鍥?perception-only |
| `gui_rewalk/run_capability_synth.py` | 鍙€夌绾垮叆鍙?| 瀵硅瑙夎妭鐐瑰仛鑳藉姏褰掍竴/鍙傛暟鍖栨垨琛ュ綍鏃у浘 `page_capabilities.json`锛涘崟鎴浘榛樿鍙兘寰楀埌 discovered |
| `gui_rewalk/run_graph_quality.py` | 褰撳墠鍙璐ㄦ鍏ュ彛 | 瑙勫垯璐ㄦ榛樿寮€鍚紱`--use-vlm` 鍙鍔犳埅鍥捐涔夎鍒わ紱`--annotated-dir` 涓烘瘡涓?ERROR/WARN 杈撳嚭鏍囨敞 PNG + manifest锛屽潎涓嶆敼婧愬浘/鎴浘 |
| `gui_rewalk/run_visual_collection.py` | 褰撳墠 M13 鍏ュ彛 | 鏍￠獙澶氬簲鐢ㄥ浘/鑳藉姏鐩綍/鎸囦护锛屾寜鍥炬墽琛屽苟鍐?`m13.visual_collection.v1` episode锛沗--validate-only` 涓嶅惎鍔?VM/VLM |
| `run_local_visual.ps1` | 鏈湴閮ㄧ讲鍏ュ彛 | 浠ヤ粨搴撶浉瀵硅矾寰勫惎鍔?VMware 妗岄潰瑙嗚閬嶅巻锛涘嚟鎹彧浠庣幆澧冨彉閲忚鍙?|

鎵€鏈夋寚鍚?`run_random_walker.py`銆乣run_scenario_pipeline.py`銆乣run_capability_collection.py`銆乣run_parallel_collect.py` 鐨勬棫鑴氭湰宸查€€褰广€?
## 3. 娲昏穬妯″潡杈圭晫

### 3.1 鐜涓?VLM

- `env/desktop_gui_gen_env.py`锛氭闈?VM/瀹瑰櫒 reset銆佹埅鍥俱€乼erminal銆佸姩浣滀笌褰曞睆銆?- `env/android_gui_gen_env.py`锛欰ndroid emulator 鐢熷懡鍛ㄦ湡銆佹埅鍥俱€乼erminal 涓庡姩浣溿€?- `env/android_controller.py`锛欰DB/AndroidWorld 鎴浘銆佸姩浣溿€佸簲鐢ㄧ敓鍛藉懆鏈熴€?- `env/osworld_reload.py`锛氭闈?guest HTTP 鎺у埗锛涗笉鍐嶈姹?`/accessibility`銆?- `env/gui_gen_agent.py`锛?20 琛屾埅鍥?only VLM transport锛屽彧淇濈暀 `predict_mm`銆佽秴鏃?閲嶈瘯銆丣SON 瑙ｆ瀽涓?reset銆?- `src/core/app_lifecycle.py`锛氳法骞冲彴鍚姩銆侀噸缃€佺獥鍙ｈ仛鐒︿笌瑁佸壀锛涗笉瑙ｆ瀽 UI 鏍戙€?
### 3.2 鍥鹃亶鍘?
- `src/core/visual_traversal/visual_engine.py`锛氫富寰幆銆乫rontier銆佹粴鍔ㄨ仛鍚堛€佸姩浣滀簨鍔″拰钀藉湴楠屾敹銆?- `visual_perception.py`锛氭埅鍥?grounding銆佸懡鍚嶅拰鍊欓€夋瀯寤恒€?- `visual_state.py`锛氭墽琛岃妭鐐广€佺ǔ瀹?Page銆乂ariant 涓庡厓绱犺韩浠姐€?- `capability_discovery.py`锛氫粠褰撳墠瑙嗚瑙傚療鐢熸垚鍘诲潗鏍囩殑 portable discovered capability銆?- `region_registry.py`锛歯ode 鈫?region 鈫?element 鐨勮鐩栬处鏈€?- `visual_router.py`锛氬彧娌?verified routing view 鍋氬浘鍐呮仮澶?杩斿洖鐩爣鑺傜偣銆?- `visual_resume.py`锛氫粠鎸佷箙鍖栧浘鍘熷瓙鎭㈠杩愯鎬併€?- `visual_cache.py` / `visual_agents.py`锛氭寜瑙掕壊缂撳瓨 VLM 缁撴灉骞舵彁渚涜涔夊垽瀹氬櫒銆?- `graph/state_graph.py`锛歴chema v3 鍥惧瓨鍌紱璐熻矗 Page/Variant 鐩綍銆乧apability銆丄ctionEdge.attempts銆乿erified routing view銆佸紓甯告寜閽€佽瑙?fingerprint銆佸師瀛愪繚瀛樺拰鏃у浘杩佺Щ銆?- `graph/traversal_completion.py`锛氬彧璇汇€佺‘瀹氭€х殑瀹屾垚璇佷功璇勪及鍣紱浠?v3 鍘熷璐︽湰妫€鏌?frontier銆乻croll銆乧ontrol outcome銆佺姸鎬佹仮澶嶃€丳age/Variant銆佽矾鐢卞拰 capability锛屼笉淇′换鍗曠嫭鐨?`visited` 鎴栫紦瀛?route bit銆?- `graph/graph_quality_agent.py`锛氬彧璇昏鍒欒川妫€涓庡彲閫?VLM 璇箟瑁佸垽锛涗笉淇敼婧愬浘鎴栨埅鍥俱€?- `graph/graph_quality_annotations.py`锛氭妸璐ㄦ ERROR/WARN 娓叉煋涓虹ǔ瀹氬懡鍚嶇殑鑺傜偣/杈硅瘉鎹?PNG 涓?manifest锛涚己鍥惧彧璺宠繃璇?finding銆?- `graph/mobile_ops.py`锛欰ndroid lifecycle/foreground 宸ュ叿銆?
`visual_engine.py` 浠嶆槸澶у瀷缂栨帓鍣紝鏄笅涓€杞粨鏋勬€ф媶鍒嗙殑涓昏瀵硅薄锛涗絾涓嶈兘浠ョ牬鍧忓姩浣滀簨鍔°€丳age/Variant 韬唤銆佸湪绾胯兘鍔涙檵鍗囨垨 Router 鐘舵€佷竴鑷存€т负浠ｄ环鏈烘鍒囨枃浠躲€?
当前实时点击目标职责已从 `visual_engine.py` 抽到
`src/core/visual_traversal/live_targeting.py`：该组件显式接收 env、perception
与 reviewer，负责 fresh capture、obs 原位更新、overlay/region 门、实时匹配、
noninteractive/QA fail-closed 和 stateful 几何回填；Engine 保留
`_live_center_for(elem, obs)` 薄兼容入口，M13 调用不变。Engine 仍是大型编排器，
后续拆分不得破坏动作事务、Page/Variant、capability 或 Router 一致性。

### 3.3 鑳藉姏銆佹寚浠ゅ拰閲囬泦鏀拺

- `scenario/capability_synthesizer.py`锛氬彲閫夌绾垮綊涓€/鏃у浘鍏ュ彛锛涘彧璇?`screenshot.png`銆佽瑙?`elements.json` 鍜岃妭鐐瑰厓鏁版嵁锛屽崟鎴浘杈撳嚭榛樿 discovered锛屼笉鑳芥浛浠ｇ湡瀹炲姩浣滈獙璇併€?- `scenario/capability_instruction_gen.py`锛氫粠 capability 鐢熸垚甯?app銆佸浘鑺傜偣銆乬rounding銆佸弬鏁颁笌渚濊禆 refs 鐨勬寚浠ゆ暟鎹紝涓嶅啀杞崲涓烘棫 Scenario銆?- `scenario/prerequisite_runtime.py`锛歁13 鐨?resource/state/authorization/login 鍓嶇疆杩愯鏃讹紱閫夋嫨鏈€灏?GUI 鍔ㄤ綔鐨勫彲琛?setup锛屽苟鍙竻鐞嗘湰杞垱寤虹殑璧勬簮锛屼笉鎺ュ叆鐙珛閬嶅巻 CLI銆?- `scenario/visual_prerequisite_agent.py`锛氭妸鎴浘璇箟鍒ゆ柇銆佸疄鏃?grounding 鍜?`PrerequisiteRuntime` 鎺ヨ捣鏉ワ紱搴旂敤鐧诲綍濮嬬粓杩斿洖 `needs_user`銆?- `scenario/federated_capability_catalog.py`锛氬湪涓嶅悎骞剁姸鎬佸浘鐨勫墠鎻愪笅锛屽姞杞藉涓?app 鐨勮兘鍔涚洰褰曞苟鐢熸垚甯?`app_id` 鐨勮法搴旂敤鎸囦护锛涘悓涓€ Page 鐨?Page@Variant sidecar 鎸夌ǔ瀹?page/capability semantic identity 鍚堝苟璇佹嵁锛屽啿绐佷粛 fail-closed銆?- `scenario/visual_collection_executor.py`锛歁13 璁″垝/鎵ц鍣紱鎸夋瘡涓簲鐢ㄨ嚜宸辩殑鍥惧仛鏈€灏?GUI 鎿嶄綔璺緞銆侀噸瑙勫垝銆佸墠缃鐞嗗拰瀹屾垚鍒ゅ畾銆?- `scenario/live_visual_collection.py`锛氬鐢ㄥ凡 resume 鐨?`VisualTraversalEngine` 鍋氬疄鏃堕〉闈㈣韩浠姐€佸厓绱犻噸瀹氫綅銆佸姩浣滀笌 settle銆?- `scenario/collection_writer.py`锛歚write_visual_episode()` 灏?M13 鍐呭瓨 observation 钀戒负鎴浘涓?JSON-safe 杞ㄨ抗锛涙棫 `write_episode()` 浠嶄粎浣滈仐鐣欐暟鎹吋瀹广€?- `scenario/trajectory_verifier.py`锛氳鍒欒川妫€涓庡彲閫?VLM 璐ㄦ銆?
- `scenario/region_function_research.py`: standalone research reader/extractor
  that groups existing node artifacts by stable Region, gives Region images and
  member summaries to an injected VLM, and saves only function name,
  description, parameters, Region id, and node locations.
- `scenario/function_collection_research.py`: standalone research instruction,
  shortest-function-order, arrival/completion-judge, and callback coordination
  helpers. It performs no GUI action and is not wired into the current M13 CLI.

## 4. 褰撳墠閬嶅巻宸ヤ綔娴?
1. 鐜鍙栧緱鎴浘骞剁‘璁ょ洰鏍囧簲鐢ㄥ浜庡墠鍙般€?2. 鎰熺煡灞傝緭鍑鸿瑙夊厓绱狅細绋冲畾 ID銆佸悕绉般€佺被鍨嬨€乧ategory銆乥box/center銆乺egion銆乻elected/modal/back锛屼互鍙?`enabled/requires_permission/blocked_reason`銆傛椿鍔ㄨ〃闈㈠彟鍒?`page/dialog/popup_menu`锛屽苟鎶?`surface_bbox_xywh/surface_scrollable` 缁戝畾鍒板綋鍓嶈〃闈㈠唴鐨勫厓绱犮€?3. `VisualStateRegistry` 鍏堢敤 region-set銆乻elected navigation銆侀〉闈㈣涔夊拰鍑芥暟绛惧悕鍖哄垎鎵ц鑺傜偣锛屽啀涓哄叾鐧昏绋冲畾 `page_id` 涓庡熀浜?observed facts 鐨?`variant_id`銆傚嚱鏁伴泦鍚堝彉鍖栧彲浠ユ媶 Page@Variant 鎵ц鑺傜偣锛屼絾鍚屼竴璇箟椤甸潰浠嶇敱 `page_id` 鑱氬悎锛涙ā绯婇〉闈㈣韩浠芥墠浜?VLM same-page judge銆?4. 瀵硅瘽妗嗐€佷笅鎷夈€乷verflow/context menu 鍜岄€夐」 popup 閮芥槸 active overlay锛涘彧淇濈暀 bbox 瓒冲钀藉湪璇?surface 鍐呯殑鍏冪礌锛岃儗鏅厓绱犱笉鑳借繘鍏ヨ韩浠界鍚嶆垨鐐瑰嚮 frontier銆傜煭涓旈潪 scrollable 鐨?popup/menu 鐩存帴璁颁负 static scope锛屼笉鎵ц鏁撮〉 swipe/闀垮浘鎷兼帴銆?5. 鐧昏鑺傜偣鏃剁珛鍗充粠褰撳墠鍙氦浜掑厓绱犵敓鎴?`discovered` capabilities锛屽悎骞跺埌 page/variant 鐩綍锛涙埅鍥句笌 geometry 鐣欏湪 node artifact锛宺ecipe 鍙啓璇箟 selector銆?6. 引擎按 node/region/element 覆盖账本筛选 frontier，只允许明确 `category=navigation|nav` 的元素进入可执行候选；感知与账本的稳定顺序就是调度顺序，不再调用 Explorer chooser。`shallow/display/dangerous` 以及分类缺失或未知的元素只保留为 inventory，不能因 button/link/tab/menu/row 等 UI 类型或 stateful 字段重新升级。Create/Add 等入口必须由感知层标为 navigation；安全功能开关还必须同时满足既有 function-set、可逆、无风险与权限条件。disabled/login/permission、安全风险、状态恢复、实时重绑和 probe/restore 门保持不变。7. 鐐瑰嚮鍓嶅繀椤诲瀹炴椂甯ч噸鏂?grounding/缁戝畾锛涘巻鍙插潗鏍囦笉鑳界洿鎺ヤ綔涓烘墽琛屽潗鏍囥€傜粦瀹氬湪 dialog/popup 涓婄殑鍏冪礌鍏堜富鍔?capture 鏈€鏂?observation锛岀鐢?OCR/template 蹇嵎鍛戒腑锛屽苟纭鍚岀被 active overlay 浠嶅瓨鍦ㄣ€乴ive surface bbox 涓庤褰曢噸鍙犱笖鍊欓€変粛鍦ㄥ叾涓紱娴眰娑堝け鍚庤儗鏅笂鐨勫悓鍚嶆爣绛句笉鑳芥帴绠＄偣鍑汇€倀ab-bar 鍚搁檮鍙鍚屼竴鏄惧紡 `tab_bar` region 鐢熸晥锛岃惤鐐瑰繀椤讳粛鍦ㄨ region bbox 鍐呫€?8. 姣忔瀹為檯 GUI 鍔ㄤ綔鍦ㄤ氦缁?`env.step()` 鍓嶅厛鍚戝搴?`ActionEdge.attempts[]` 杩藉姞 `attempted`锛屽啀鐢辨墽琛?focus/effect/landing 鏇存柊鍚屼竴璁板綍锛涜繖鏍峰悗绔湪宸叉姇閫掔偣鍑诲悗鎶涘紓甯告椂浠嶇暀涓?`execution_error`銆傚彧鏈?committed銆乣landing_verified=True` 鐨勬垚鍔?attempt 鎵嶄护杈瑰彲璺敱銆佹彁浜?visited/region/memory锛屽苟鎶婂尮閰?capability 鏅嬪崌 verified銆?9. Create/Add銆佸～鍐欍€佷繚瀛樸€佹墦寮€鏉＄洰鏄櫘閫?frontier 鍔ㄤ綔锛屼腑闂?Page/Variant 鑷劧鐧昏锛涢亶鍘嗕笉鏋勯€犫€滆嫢鏃犺祫婧愬垯鍒涘缓鈥濈殑 domain prerequisite 鍒嗘敮锛屼篃涓嶈皟鐢ㄩ粯璁?resolver銆侻13 浠嶅湪鑳藉姏鎵ц闃舵淇濈暀鐙珛 prerequisite runtime銆?10. 鐐瑰嚮瀵艰嚧鐩爣 app 闂€€鏃惰褰?`app_crash`锛涚‘璁ゆ墦寮€澶栭儴 app 鏃惰褰?`external_app`銆傚け璐ャ€乶o-effect銆乥locked 鍜岀鍦?attempt 鍧囦繚鐣欏湪鍔ㄤ綔杈逛笅锛屼絾涓嶈繘鍏?routing view 鎴?verified capability銆俻ost-click frame 浠嶅厛鐧昏銆佸悗楠屾敹锛涗絾鑻ョ姸鎬佹帶浠剁殑婧?钀藉湴璇箟 page銆佸畬鏁寸粨鏋勫寲 state facts銆乻elected modes 涓庡凡鐭?off/on 鍊奸兘璇佹槑鏈彉鍖栵紝涓旇钀藉湴鑺傜偣鏄叏鏂般€佹棤宸叉彁浜ゆ嫇鎵?verified attempt/寮傚父寮曠敤鐨?provisional state锛屽紩鎿庝細鎶婃湭鎻愪氦 attempt 褰掍竴鍥炴簮鑺傜偣骞跺師瀛愬洖鏀惰 provisional state銆備换浣曡瘉鎹己澶便€侀敊椤点€佹湭鐭ュ€笺€佸凡鎻愪氦寮曠敤鎴栨竻鐞嗕笉鍙橀噺鍐茬獊閮芥嫆缁濆洖鏀跺苟淇濇寔 fail-closed銆?11. 闇€瑕佽繑鍥炲叾浠?frontier 鏃剁敱 `VisualRouter` 鍦?`routing_graph` 涓婅鍒掞紱鏃犲彲闈犺矾寰勬椂鍙?relaunch 鍚庝粠瀹為檯钀界偣閲嶆柊瑙勫垝銆傚凡鏈夊浘鍚姩銆乺elaunch 鍜?Router hard reset 鐨勮瀵熷彧閲囩敤宸茬櫥璁?`state_id` 鍙婂叾鏃㈡湁璺緞锛涙湭鐭ラ〉闈㈣缃?`state_restore_failed`锛屼笉鐧昏鎴愭柊鐨勮捣鐐广€傜┖鍥鹃娆″惎鍔ㄤ笌鏅€氱偣鍑诲彂鐜版柊椤甸潰涓嶅彈姝ら檺鍒躲€?12. 姣忎釜 Page@Variant 鐨勬暣椤垫垨绋冲畾 region 婊氬姩鑼冨洿蹇呴』鎸佷箙鍖栧埌 `scroll_ledger`锛岃瘉鏄?static 鎴栫湡瀹炲埌杈?bottom锛屽苟纭鍥炲埌 canonical top锛涚煭 popup/menu 浠?`classification=static, termination=static, steps=0` 鏄庣‘闂悎锛岃€屼笉鏄悜澶辨椿鑳屾櫙鍒楄〃鍙戦€?swipe銆俬it cap銆乷ff-app銆乪rror銆乽nknown 鎴栨仮澶嶅け璐ュ潎涓嶇畻瀹屾暣銆傚綋鍓嶉〉鍊欓€変负绌轰笖鍑嗗缁撴潫鏃讹紝鑻ュ凡鏈夋湭瀹屾垚 scope 鍙璁¤繃涓€娆★紝鍒欐部鐜版湁 register/revisit 璺緞琛ュ涓€娆★紱琛ュ鍚庝粛涓嶅畬鏁村氨浠?`scroll_incomplete` 鍋滄銆傚凡瀹屾垚 shared region 鍙鐢ㄣ€侫ndroid/touch 闀垮浘鎷兼帴鎶婂浐瀹?status/navigation 甯︿綔涓?sticky 涓嬮檺锛屽洜姝ゅ姩鎬佹椂閽熴€佷俊鍙锋垨 gesture pill 姣忓抚鍙樺寲涔熷彧鍦?composite 椤?搴曚繚鐣欎竴娆★紱鍒嗗潡鎰熺煡鍐嶆寜 `y_map` 鐨勬簮甯ц杩囨护绯荤粺甯︼紝middle tile 涓嶈兘鎶?seam 涓婄殑绯荤粺 UI 鐢熸垚涓哄簲鐢ㄥ厓绱犮€?13. 鍥句笌鑺傜偣浜х墿鍛ㄦ湡鎬у師瀛愪繚瀛橈紝鍙敱 `visual_resume.py` 鎭㈠锛汸age/Variant銆乧apability銆丄ctionEdge attempts銆乺egion/寮傚父/scroll 璐︽湰鍜?action counter 涓€骞舵仮澶嶃€?14. `frontier_empty` 鍙〃绀鸿皟搴?frontier 宸茶€楀敖锛屼笉鍗曠嫭绛変簬閬嶅巻瀹屾垚銆侰LI 鎬诲啓 `completion.json`锛涘彧鏈?8 椤硅瘉涔︽鏌ュ叏閫氳繃鎵嶆槸 `certified`銆傜洰鏍囬噸缁戝け璐ャ€佹墽琛屽紓甯搞€乽ncertain銆乿erification failed 绛変笉鑳介潬寮傚父璁板綍娲楁垚瀹屾垚锛沝isabled/permission/risk/no-effect/external-app/crash 绛夋槑纭瓥鐣ョ粓鎬佸彧鍙棴鍚堝搴旀帶浠躲€傚浜庡悓鏋?navigation group锛屽彧鏈変竴涓湡瀹?`verified_attempt` 浠ｈ〃鍙互瑕嗙洊鍏朵綑鍙傛暟鍖栧埆鍚嶏紱浠ｈ〃鑷韩鐨?abnormal/no-effect銆乻elected/back 鎴?inventory 涓嶈兘鏇垮厔寮熷鑸」缁撴銆?
姝ｅ紡鍏ュ彛鍚姩 `tools/live_status.py` 鏃朵細浼犲叆琚洃鐫ｇ殑閬嶅巻 PID銆傜洃瑙嗗彴涓嶄互
鈥滄棩蹇楅潤榛樷€濈寽娴嬬粨鏉燂紙鍗曟 grounding 鏈€闀垮彲闈欓粯 150 绉掞級锛涜繘绋嬬湡姝ｉ€€鍑哄悗璇诲彇
`graph.json`锛岃緭鍑鸿妭鐐?瀹炴祴杈?宸叉彁浜ゅ姩浣溿€佹渶鏂板尯鍧椾笌瀵艰埅瑕嗙洊銆佸仠姝㈠師鍥犮€侀〉闈㈢ず渚嬶紝
骞舵眹鎬荤寮€搴旂敤/闂€€銆丷outer hard reset銆侀殧绂荤偣鍑?杈广€乂LM/grounding 澶辫触鍜屽叧閿劅鐭?澶辫触銆傚彧鏈夊悓鐩綍 `completion.json` 涓?`certified` 鎵嶆樉绀衡€滈亶鍘嗗凡瀹屾垚鈥濓紱`frontier_empty`銆侀绠楁垨寮傚父閫€鍑轰絾璇佷功鏈€氳繃鏃跺潎鏄剧ず鈥滈亶鍘嗗凡鍋滄鈥濄€?
`preserve_initial_surface=True` 鍙妸璋冪敤鏂归鍏堟墦寮€鐨勬ā鎬佹鐩存帴浣滀负鏍癸紱榛樿鍐峰惎鍔ㄤ粛浼氬厛娓呯悊骞叉壈寮圭獥銆?

启动与中断清理即使使用 `force_first` 询问 dismisser，也只有在结构化结果同时给出 JSON 布尔值 `surface_is_temporary=true` 和 `target_is_close_control=true` 时才允许点击。缺字段、旧格式、非布尔值、异常或不确定结果一律 no-op；正常页面 CTA、通知标题/正文/详情入口不能仅因控件类型或名称被当作关闭目标。

状态登记仍优先使用既有 region-set 判定。只有常规匹配与仲裁均失败、当前截图与已有节点的 pHash 完全相同、selected navigation 与结构化 state token 完全一致、去除 selected/state/availability 后的原始功能 token 重叠率至少为 0.78，且功能面判定不为 `different` 时，才把新 region-set 并入已有节点；近似 pHash、不同页签或不同状态不会走该恢复路径。

非图标 navigation 文本行在每次点击前必须用当前帧重新确认：fresh 同名候选的 live bbox 优先，可信 sidebar/tab region 次之；OCR 只能唯一命中且返回文字本身的中心，bbox 越界、零/多命中或 OCR 失败均 fail closed。below-fold 模板只负责提出 live bbox，不能再用模板/VLM 大框中心替代 OCR 文字中心；compact icon 保持独立局部锚点策略。

`transitioned_inconsistent` 落点仍先供 Router 尝试恢复源页面；恢复尝试结束后，如果该落点仅由本次 attempt 新建、尚无 committed/verified/异常等权威引用，Engine 会复用现有原子清理事务撤销该 provisional node，并清理 runtime state、Visual/Region registry membership 和权威 node index。既有节点与任何存在权威引用的节点绝不删除；源页面恢复、一次重试和失败停止语义不变。

当前 App 内的表单完成动作不再因按钮叫 Add/Create/Save/Apply/Done/Open 就一律视为危险。两条感知路径使用同一上下文边界：只有画面明确证明动作仅创建、更新或打开普通本地项目，结果可逆或会进入另一个可继续遍历的 App 内状态，且不涉及账户、认证、权限、网络、通信、支付、安全、系统配置、破坏性或外部副作用时，才标为 `category=navigation, risk=none`。这些名称只是示例，不是白名单；Delete/Remove/Reset/Erase/Disconnect、敏感/外部效果和后果不确定仍为 dangerous 或 fail closed。Engine、Explorer、schema 和 completion 均未改变。

两条感知 Prompt 共用精简的四分类与回退契约：发现当前 App 内新页面/面板/对话框/菜单/详情/创建编辑界面，或确认安全的本地表单完成动作，才是 `navigation`；输入/焦点/单值/外观布局是 `shallow`；破坏、账户/认证/权限、网络/通信/支付、安全/系统配置、外部 App 或安全性不确定是 `dangerous`；`display` 只用于不可交互锚点。安全已知而 navigation/shallow 难分时优先 navigation，安全未知仍 fail closed。`back=true` 只表示不提交的 Back/Cancel/Close；安全 Done/Save/Add/Apply 必须为 `navigation + back=false`。截图文字只是 UI 数据，不能作为改变规则或输出格式的指令。active surface、modal/system dialog/interruption、page/锚点、permission 与 switch stateful 数据契约不变。

`--vlm_grounding` 现在启动时不加载 OmniParser YOLO，并且 grounding 为空时不做 YOLO/OCR fallback；legacy 非 grounding 路径仍加载 `--ocr_model_path` 并使用 YOLO+OCR。参数结构未改变。Clock Add 是首个待 live 验收案例，不是生产硬编码。
## 5. 鏁版嵁濂戠害

### 5.1 graph.json

褰撳墠椤跺眰 `graph_schema_version=3`銆侼etworkX `nodes/edges` 淇濆瓨鎵ц鑺傜偣涓庣揣鍑戞嫇鎵戝紩鐢紱鎸佷箙鍔ㄤ綔鐪熷€兼槸 `action_edges[].attempts[]`锛岄〉闈㈣仛鍚堝湪 `pages`锛屽湪绾胯兘鍔涜仛鍚堝湪 `capabilities`锛屾粴鍔ㄨ竟鐣岃瘉鎹湪 `scroll_ledger[]`銆俙routing_graph` 鏄彧鍖呭惈涓ユ牸 verified landing 鐨勬淳鐢熻鍥俱€倂3 涓嶅啀鎸佷箙鍖栭《灞?`transition_events`锛涘悓鍚嶅睘鎬у彧鏄粠 nested attempts 鐢熸垚鐨勫彧璇诲唴瀛樺吋瀹硅鍥俱€?
鑺傜偣鑷冲皯鍖呭惈锛?
- `state_id`, `state_type="visual"`, `app_name`, `page_id`, `variant_id`, `page_identity_version`
- `screenshot_path`, `visual_fingerprint`, `elements`
- `action_path_from_root`, `visit_count`, `unreachable`, `page_name`
- `variant_signature`, `observed_facts`, `visible_capabilities`

鍏冪礌鍙寘鍚?`enabled: true|false|null`銆乣requires_permission`銆乣blocked_reason`銆乣selected`銆乣region/region_id/region_bbox`銆乣surface_kind/surface_bbox_xywh/surface_scrollable` 涓?`abnormal_reason/abnormal_detail`銆俿urface geometry 鍙綔鏈瑙傚療鍜屽疄鏃堕噸缁戠殑 sidecar 闂ㄧ锛屼笉杩涘叆 portable ActionEdge/capability recipe銆傛棫鍥剧己灏?availability/surface 瀛楁鏃舵寜鏈煡澶勭悊锛屼笉鑳界敱鍚嶇О鐚滄垚鏄惧紡鎺堟潈鎴栨诞灞傝瘉鎹€?
`pages` 浠ョǔ瀹?`page_id` 涓洪敭锛屾瘡椤靛寘鍚涔夊悕銆乣variants` 鍜?capability 寮曠敤锛泇ariant 淇濆瓨 `variant_id/state_ids/variant_signature/observed_facts/visible_capabilities`銆俙capabilities` 淇濆瓨 page-level portable 鑳藉姏鍙婂叾 `available_when/evidence_variants/source_elements/action_edge_ids/target_pages/target_variants`銆?
姣忎釜 `action_edges[]` 鑷冲皯鍖呭惈锛?
- `action_edge_id`, `source/target`, `source_page_id/source_variant_id`, `target_page_id/target_variant_id`
- `action`锛氬幓闄ゅ潗鏍?bbox/center 鐨勫姩浣滅被鍨嬨€佽涔?selector 鍜岄潪鍑犱綍鍙傛暟
- `element_id`, `element_label`, `semantic_description`, `region`
- `action_steps`, `action_sequence`, `transition_kind`
- `attempts[]`, `attempt_count`, `routing_verified`

姣忎釜 attempt 鑷冲皯鍖呭惈 `event_id/action_index/source/target/action`銆乣outcome/detail`銆乣landing_verified/target_page_name`銆乣committed/timestamp/evidence`銆傛垚鍔熴€佸け璐ャ€乶o-effect銆乸ermission gate銆乷ff-app 涓?crash 閮借拷鍔犲湪瀵瑰簲璇箟鍔ㄤ綔杈逛笅锛涘悓涓€ source/target 鐨勪笉鍚屾寜閽垨鍔ㄤ綔鎷ユ湁涓嶅悓 `action_edge_id`锛屼笉浼氳 `DiGraph` 瑕嗙洊銆傚彧鏈?committed銆乣landing_verified is True` 涓旈潪缁堟€佸け璐?outcome 鐨?attempt 鍙护杈硅繘鍏?`routing_graph`銆?
鍥鹃《灞傝繕淇濆瓨 `app_name/action_counter/stop_reason/abnormal_buttons[]`銆俵oader 鍏煎 NetworkX 鐨?`edges/links` 涓?schema v1/v2锛泇2 椤跺眰浜嬩欢杩佸叆 ActionEdge attempts锛屼繚瀛樺悗鍐?v3 涓斾笉鍐嶈緭鍑?`transition_events`銆傛棫鍥句粠鏈寔涔呭寲鎴栧凡琚?DiGraph 瑕嗙洊鐨勫け璐?閲嶅璇箟鍔ㄤ綔涓嶅彲鎭㈠锛岃縼绉讳笉鑳芥嵁姝ゅ０绉板巻鍙插畬鏁淬€?
鍥鹃《灞傝繕淇濆瓨 `abnormal_buttons[]`锛歚state_id/element_id/element_uid/element_name`銆?`region/region_id`銆乣reason/detail/action`銆侀娆?鏈鏃堕棿涓庡嚭鐜版鏁般€傚搴旀簮鍏冪礌鍐?`abnormal_reason/abnormal_detail` 鍜?`visited=true`锛屼絾 resume 鏄庣‘涓嶆妸瀹冩仮澶嶄负鎴愬姛鐐瑰嚮
璐︽湰锛涘叡浜?region 閫氳繃 `(region_id, normalized-name)` 璺宠繃鍚屼竴寮傚父鎸夐挳锛屾棤绋冲畾 region
鏃堕€€鍖栦负鑺傜偣灞€閮?key銆傚紓甯告寜閽笉浜х敓鐩爣杈广€?
`scroll_ledger[]` 浠?`scope_id` 鏍囪瘑 `state:<id>:page` 鎴栫ǔ瀹?`region:<rid>`锛岃褰曞叧鑱?`state_ids`銆乺ole銆乣classification=static|scrollable`銆乼ermination銆乥ottom/top 璇佹槑銆乻teps/max_steps
鍜?detail銆傚畠涓嶄繚瀛樻埅鍥炬枃浠跺悕锛涘畬鎴愮粨璁虹敱杩欎簺缁撴瀯鍖栬竟鐣岃瘉鎹淳鐢熴€?
鍔ㄤ綔楠屾敹鍓嶄骇鐢熺殑 provisional node 涓嶆槸鐙珛鍘嗗彶浜嬪疄銆傚彧鏈変笂杩颁弗鏍肩瓑浠烽棬婊¤冻鏃讹紝
`StateGraph.remove_uncommitted_state()` 鎵嶅厑璁哥Щ闄ゅ畠锛屽悓鏃舵竻鐞?Page/Variant membership銆?capability source銆乻croll scope 涓?node index锛屽苟淇 Visual/Region registry锛涘凡鍐欒瘖鏂浘鐗囧彲淇濈暀锛?浣嗕笉鍐嶅嚭鐜板湪鏉冨▉ `node_index.json` 鎴栧浘涓€傞€氱敤 API 閬囧埌鍚屼竴 semantic edge 鍚屾椂鍚?unresolved
鍘嗗彶 attempt 涓?provisional-target attempt 鏃跺綋鍓嶄細闆跺彉鏇存嫆缁濓紝涓嶈兘涔愯鍚堝苟銆?
姣忎釜 traversal 杈撳嚭鐩綍鍙﹀啓鍙娲剧敓鐨?`completion.json`锛坰chema
`gui_rewalk.traversal_completion.v1`锛夈€傝瘉涔﹀寘鍚?`certified|incomplete`銆? 椤?checks銆侀€愭帶浠?outcome
涓庤鐩?Page/Variant銆乤ttempt銆乻croll銆乧apability 鐨?SHA-256 evidence digest銆傝瘉涔︾殑澹版槑鑼冨洿浠呮槸
鈥滃綋鍓嶆劅鐭ャ€佸畨鍏ㄧ瓥鐣ヤ笌鐜 fixture 涓嬫墍鏈夊凡鍙戠幇銆佸彲杈惧姛鑳介潰宸查棴鍚堚€濓紝涓嶈兘璇佹槑浠庢湭琚劅鐭ョ殑鍔熻兘涓嶅瓨鍦ㄣ€?
### 5.2 node_artifacts

姣忎釜瑙嗚鑺傜偣鐨勬牳蹇冭瘉鎹細

```text
node_artifacts/<state_id>/
  screenshot.png
  elements.json
  state_meta.json
  page_capabilities.json     # 鍙€夌绾垮綊涓€/鏃у浘琛ュ綍
```

`state_meta.json` 鍚屾淇濆瓨 `page_id/variant_id/page_identity_version/variant_signature/observed_facts/visible_capabilities`銆備笉瀛樺湪 `a11y.xml`銆傛埅鍥俱€佸厓绱?geometry 涓?fingerprint 鏄綋鍓嶈瀵熺殑鎰熺煡/resume/璐ㄦ sidecar锛涗究鎼哄姩浣滃拰 capability 鍙紩鐢ㄨ涔?element/region selector锛屼笉渚濊禆鎴浘鏂囦欢鍚嶆垨鍘嗗彶鍧愭爣銆?
### 5.3 capability/instruction

閬嶅巻鐧昏姣忎釜瑙嗚瑙傚療鏃跺嵆鏃剁敓鎴?portable capability銆傜ǔ瀹?id 鐢?`page_id + semantic_key` 寰楀埌锛涘悓涓€ page 鐨勪笉鍚?variant 璇佹嵁鍚堝苟锛屽苟鍦?`available_when.variant_ids/observed_facts` 涓〃杈炬潯浠躲€傝瀵熸湡鐘舵€佸彧鑳芥槸 `discovered`锛涚湡瀹炲姩浣?鏄庣‘ target+`landing_verified=True` 鎵嶅彉涓?`verified`锛屽苟琛?`action_edge_ids/effects/target_pages/target_variants`銆?
涓嬫父 `FederatedCapabilityCatalog` 鍔犺浇 node sidecar 鏃讹紝浠?`app_id::capability_id` 鑱氬悎銆傚悓涓€ id 鍙湁鍦ㄧǔ瀹?`page_id` 鍜?`semantic_key` 鍧囦竴鑷存椂鎵嶅悎骞?empty/has-data 绛?variant 璁板綍锛屽苟瀵?`evidence_variants/entry_variants/source_elements/action_edge_ids/target_*` 鍋氱‘瀹氭€у苟闆嗭紱浠讳竴璇佹嵁涓?verified 鏃剁粨鏋滀笉闄嶇骇銆倂ariant-specific gate 淇濆瓨鍦?`available_when.requires_by_variant`锛屽彧鏈夋墍鏈?variant requirement 瀹屽叏鐩稿悓鏃舵墠淇濈暀鍏煎 `requires`锛屽惁鍒欑疆绌轰互閬垮厤鍒堕€犲叏灞€鍓嶇疆銆俻age 鎴?semantic identity 鍐茬獊銆佹垨閲嶅璁板綍缂哄皯绋冲畾 `page_id` 鏃朵粛鎷掔粷鍔犺浇锛屼笉鑳戒粎鍑?id 鐚滄祴鍚屼箟銆?
Capability recipe 鍙厑璁稿姩浣滅被鍨嬨€佽瑙夎涔?selector 鍜岃繍琛屾椂鍙傛暟妲姐€傝緭鍏ユ鐢?TYPE+runtime text slot锛屼笅鎷?combobox 鐢?CLICK+runtime option锛屽悓鏋勫垪琛ㄩ€氳繃 runtime visible group 鍙傛暟鍖栵紱鏁板€?slider/range 绂绘暎涓鸿嚜鐒惰瑷€鍙傛暟 `鏈€灏?涓€鍗?鏈€澶锛岀敤 `SET_SLIDER` 鍦ㄥ疄鏃堕噸瀹氫綅鐨勬暣鏉℃粦杞ㄤ笂璁＄畻鐩稿钀界偣锛屼笉鎸佷箙鍖栧潗鏍囷紱鑷敱鎺掑簭/鎷栨斁绫?drag 浠嶆樉寮?`execution_support=unsupported`锛屼笉鑳界敤绌?recipe 鍋囪鍙墽琛屻€傚綋鍓嶅彲鎵ц atom 鍦ㄦ棫 `name/region/param/elements/element_map/explain` 涔嬪杩樺寘鍚細

- 韬唤/鍏ュ彛锛歚app_id`, `capability_id`, `entry_surfaces`
- 鎵ц濂戠害锛歚input_slots`, `requires`, `effects`, `success_predicate`, `observables`
- 鍔ㄤ綔/鍓嶇疆涓庢仮澶嶏細`execution_recipe`, `setup_recipe`, `recovery`, `cleanup`
- 鐘舵€佷笌鎴愭湰锛歚availability_status`, `risk_level`, `action_steps`

`run_capability_synth.py` 鏄彲閫夊綊涓€/鏃у浘鍏ュ彛锛屼笉鏄亶鍘嗗悗鐨勫繀缁忛樁娈碉紱鍗曟埅鍥捐緭鍑洪粯璁?`discovered`锛屾棫 artifact 缂虹姸鎬佹寜 `unknown`锛屼笉鑳藉嚟鎴浘鍗囩骇 verified銆俙Capability.from_raw()` 缁х画鍏煎鍘嗗彶 `action_recipe/actions`銆侷nstruction refs 璁板綍 app銆丳age@Variant銆佽兘鍔涜韩浠姐€乻elector銆佸弬鏁般€佷緷璧栦笌鎵ц濂戠害锛汳13 瀵?recipe 姣忎竴姝ラ噸鏂?capture/ground/settle锛屼笉鎶婅涔夊姝ュ帇鎴愭棫鍧愭爣鍔ㄤ綔銆?
### 5.4 M13 collection

`CollectionWriter.write_visual_episode()` 鍐?`schema_version="m13.visual_collection.v1"`銆俥pisode `meta.json` 鑷冲皯鍖呭惈 apps銆佹渶缁堢姸鎬併€佹垚鍔熸爣蹇椼€丟UI 鍔ㄤ綔/cleanup/鍒?app 璁℃暟銆佸畬鎴?澶辫触 refs 涓庢渶缁?VLM verdict锛沗trajectory.json` 鍙﹀惈 capability refs銆乺ef results銆乬raph provenance 鍜?steps銆傛瘡姝ヤ繚瀛?`kind/app_id/ref_id/action_steps/committed`銆乥efore/after 鎴浘鏂囦欢鍚嶃€佽妭鐐硅韩浠姐€乤ction spec銆佸疄鏃?grounding銆佸浘鏉ユ簮涓庡彲閫?verification/evidence锛沝ynamic recipe grounding 鍙︿繚鐣欏疄闄?primitive銆侀€愭 grounding 鍜屽け璐ヤ綅缃€傝 schema 涓嶅寘鍚棫 A11y 鎴?`reverse_*` 瀛楁銆?
### 5.5 graph quality annotations

`run_graph_quality.py --annotated-dir <dir>` 鍙﹀啓 `gui_rewalk_graph_quality_annotations_v1` manifest锛屽苟涓烘瘡涓?ERROR/WARN 灏藉姏鐢熸垚涓€涓ǔ瀹氬懡鍚?PNG銆傝妭鐐?finding 浣跨敤鍗曞浘锛堝繀瑕佹椂甯?peer锛夛紝杈?finding 浣跨敤 source/target 骞舵帓锛涙湭鎺㈢储鎺т欢缁胯壊銆乻ource element 榛勮壊銆乺egion 闈掕壊銆佸疄闄呮墽琛岀偣娲嬬孩銆俶anifest 瀵规瘡涓?finding 璁板綍 `generated/skipped`銆佸浘鐗囥€佽妭鐐?杈广€佽В閲婂拰 highlights锛涚己鍥?鍧忓浘鍙啓 skip reason銆傝緭鍑鸿矾寰勫仛鐩綍閫冮€?symlink 闃叉姢锛屾簮 graph 涓庢埅鍥惧彧璇汇€?
## 6. VLM 璋冪敤 workflow

閬嶅巻闃舵鎶婅鑹叉媶寮€锛屼絾閫氳繃 `visual_cache.py` 瀵瑰悓甯с€佸悓 role銆佸悓 prompt 澶嶇敤缁撴灉锛歡rounding銆侀〉闈㈣韩浠姐€佽惤鍦伴獙鏀跺拰寮傚父/鐒︾偣鍒ゅ畾鍚勮嚜鎷ユ湁鏇寸獎鐨勮緭鍑哄绾︺€傛媶鍒嗘病鏈夐殣寮忓鍔犳棫 A11y 璋冪敤锛沗GUIGenAgent` 鐜板湪鍙彂閫佹枃鏈拰鎴浘銆?
鍦ㄧ嚎 capability discovery 澶嶇敤宸茬粡 grounded 鐨勮瑙夊厓绱狅紝鍦ㄨ妭鐐圭櫥璁版椂鍐?discovered 鍊欓€夛紝涓嶆柊澧炰竴涓繀缁忕殑閬嶅巻鍚?VLM 闃舵銆傜绾?`CapabilitySynthesizer` 浠呯敤浜庡彲閫夊綊涓€/鍙傛暟鍖栨垨鏃у浘琛ュ綍锛屽崟鎴浘榛樿 discovered銆傜湡瀹炲姩浣滅殑 effect/landing gate 鏄檵鍗?verified 鐨勫敮涓€鍏ュ彛銆?
`VisualPrerequisiteAgent` 鍙湇鍔?M13 鍓嶇疆鎵ц锛歏LM 鎻愪緵鎴浘璇箟鍒ゆ柇/鍊欓€?recipe锛屼弗鏍?schema銆佽祫婧?binding銆佺櫥褰曡竟鐣屻€佸疄鏃?grounding 鍜?setup 鍚庡鏌ヤ粛鐢辫繍琛屾椂 fail-closed gate 鎺у埗銆傞亶鍘?CLI 涓嶆瀯閫犺 resolver銆侻13 瀵规瘡涓?capability ref 鍜屾暣鏉℃寚浠ゅ悇鍋氫竴娆℃樉寮忔埅鍥惧畬鎴愬垽瀹氾紱缂哄皯甯冨皵 verdict銆佽В鏋?transport 澶辫触鎴栨湭鐭ラ〉闈㈠潎涓嶈兘澹扮О瀹屾垚銆?
`GraphQualityAgent` 榛樿鍙繍琛岀‘瀹氭€ц鍒欙紱`--use-vlm` 鎵嶅姞杞?VLM 鍋氳妭鐐?杈硅涔夎鍒ゃ€備綆浜?`min_vlm_confidence` 鐨勭粨鏋滃彧淇濈暀涓鸿瘉鎹紝涓嶈兘瑕嗙洊瑙勫垯缁撹锛沗unsupported` 蹇呴』鏈夊彲瑙佺己澶辫瘉鎹紝鍚﹀垯闄嶄负 `unknown`銆傝川妫€濮嬬粓鍙婧愬浘鍜屾埅鍥撅紝鎶ュ憡鍙﹀啓鏂囦欢锛涘彲閫?annotation exporter 鍙湪娲剧敓鍓湰涓婄敾璇佹嵁銆?
## 7. M13 瑙嗚閲囬泦妗嗘灦

姝ｅ紡璇存槑瑙?`design/modules/visual_collection.md`銆傚綋鍓嶅疄鐜伴伒寰細

1. 浠?capability-backed instruction 鍜岃瑙夊浘寮€濮嬶紝涓嶆帴鏀舵棫 Scenario銆?2. 姣忎釜 app 淇濇寔鐙珛 `StateGraph` 涓?adapter锛涜法 app 鏄樉寮?1-step boundary锛屼笉寤虹珛铏氭瀯鐨勮法鍥捐竟锛屼篃涓嶅悎骞惰妭鐐?namespace銆?3. 鍚屼竴 app 鍐呭彧鍦?schema v3 鐨?verified `routing_graph` 涓婃寜 edge `action_steps` 姹傛渶灏?GUI 鎿嶄綔璺緞锛沜apability 鑷韩鎴愭湰鍜?app switch 鎴愭湰涔熻繘鍏ヨ皟搴︺€傛樉寮忎緷璧栦笌 `fixed_order` 浼樺厛浜庨噸鎺掍紭鍖栥€?4. 瀵艰埅/鑳藉姏/鍓嶇疆鍔ㄤ綔閮戒娇鐢?`before screenshot 鈫?identify 鈫?live ground/relocate 鈫?execute 鈫?settle 鈫?identify/verify 鈫?commit`锛沜apability `execution_recipe` 鐨勬瘡涓?primitive 閫愭閲嶆柊 capture/ground/settle锛屽亸鑸湪棰勭畻鍐呬粠瀹為檯钀界偣閲嶈鍒掋€?5. 鍓嶇疆鏉′欢鍙厛缁戝畾宸叉湁璧勬簮锛屾垨鎵ц鏈€鐭?setup recipe 鍚庨噸瑙勫垝锛涘彧娓呯悊鏈疆鍒涘缓璧勬簮銆俙requires.kind=login`锛屾垨 capability name/execution recipe 鏄庣‘鍚?sign-in/login 璇箟鏃讹紝M13 鍦?grounding 鍓嶇洿鎺ヨ繑鍥?`needs_user` 涓?0 GUI 鍔ㄤ綔锛涘嵆浣?atom 婕忔爣 login 涔熶笉鑷姩鐧诲綍銆?6. 姣忎釜 capability ref 蹇呴』閫氳繃 VLM 鍙鎴愬姛璋撹瘝/鏁堟灉鍒ゅ畾锛屾渶缁?instruction 杩橀渶鐙珛瀹屾垚鍒ゅ畾锛涗换浣曟湭鐭?澶辫触閮?fail-closed銆?7. 閲囬泦杞ㄨ抗鍙繚瀛樻埅鍥俱€佽瑙?grounding銆佸浘鑺傜偣/杈?provenance銆佸姩浣滃拰妯″瀷鍒ゆ柇锛涗笉淇濆瓨鎴栬姹?UI 鏍戙€?8. 褰撳墠 `EngineVisualAdapter` 缁熶竴妗岄潰/绉诲姩瑙嗚鍔ㄤ綔杈圭晫锛氬疄鏃?relocation 鍚庢敮鎸?click/right-click/double-click/long-press銆佽涔?drag锛屼互鍙?type/press/hotkey/scroll/back锛涚Щ鍔ㄧ鍙﹀厑璁?home銆俤rag 蹇呴』鍚屾椂鐢?`source_selector/target_selector` 瀹氫綅褰撳墠甯у彲瑙佽捣缁堢偣锛屾寔涔呭潗鏍囦細琚墺绂汇€傛闈?back 褰掍竴涓?`Alt+Left`锛屾闈㈡柟鍚?scroll 褰掍竴涓?wheel `dy`銆傚綋鍓嶄笉澹版槑鑷敱杞ㄨ抗銆佸鎸囨墜鍔挎垨涓嶅彲瑙佹嫋鎷界洰鏍囧凡瑕嗙洊銆?9. `CollectionWriter` 鏄惤鐩樼粍浠讹紝涓嶆槸鎵ц鍣紱鎵归噺閲囬泦浠嶅繀椤荤敱鍗曞啓鑰呮垨鍙悎骞跺垎鐗囧啓 manifest銆?
## 8. 楠岃瘉闂ㄦ

### Semantic block identity current state (2026-07-17)

With `--semantic_inventory`, block inventory remains bbox-free and uses only
observation-local `b0...` ids. Before page registration and frontier scheduling,
one transient normalized_1000 block-localization call creates crop evidence; one
bounded batch visual judge then aligns all current blocks to prior-frame,
likely-page-roster, and small same-surface app-local candidates. Role is only a
ranking hint: role-label or `identity_anchor` drift cannot alone split identity.
The RegionRegistry mints stable `rN` concepts and owns action coverage. Page
region sets use `region:rN` plus `tab_selected:<name>`, so shared navigation can
retain one block concept while selected pages remain distinct. No block bbox is
persisted in elements, semantic blocks, graph data, or page identity.

For every newly registered semantic state, each successfully localized block
crop is additionally persisted as
`node_artifacts/<state_id>/region_<region_id>.png`. This reuses the existing
single batch localization call and does not persist bbox data. Missing or
out-of-bounds blocks log a warning and receive no image; downstream Region
function extraction never substitutes `screenshot.png`, preferring the stable-id
image and retaining only the historical `region_<role>.png` read fallback.

Page identity is map-guided and frozen after assignment. For a known source and
executed action, the VLM chooses among graph-neighbor Page candidates; only an
explicit `NEW` decision creates a new Page concept. A revisit may enrich semantic
elements, Regions, observed facts, and Variant evidence, but it cannot recompute
or replace the assigned `page_id`. Region screenshots and Region membership are
therefore not Page-identity inputs. Resume installs the persisted Page ID instead
of deriving another identity from the current observation. Legacy
`page_anchor_tokens` are stripped when old graphs are loaded and the former
`hierarchical_page_identity_v1` marker is normalized to
`semantic_page_variant_v1`; new artifacts no longer emit Page-anchor fields.

`block_identity_attempts/` stores optional crop atlases/crops and JSON diagnostics
including descriptors, bounded candidates, raw response, validated mapping, and
created concepts. Persisted concept ids/clicked coverage rehydrate from graph.
Representative crops do not currently rehydrate into the registry, so the first
post-resume visual alignments are intentionally limited and fail closed by
minting concepts until fresh representatives exist. Legacy semantic hash ids
remain loadable; seamless semantic concept matching across resume is not claimed.

Landing failure and physical cursor position are tracked separately. An ordinary
navigation `no_effect` remains an uncommitted failed attempt, but when the
post-click frame is confidently registered as a different pre-existing state,
the next `RunCursor` adopts that state's durable path/replay hints and the live
observation. New/untrusted landings, missing runtime state, stateful actions,
`uncertain`, and `transitioned_inconsistent` retain their existing fail-closed or
source-recovery behavior.

Router keeps shared coverage separate from source-local transition evidence.
Top bars, overflow menus, and other host-relative actions remain
`provenance=shared_pending` with `dst=None`. Explicit peer-navigation regions
(tab bars, bottom navigation, and navigation sidebars) may expose a unique
`peer_inferred` target learned from a verified occurrence or a selected peer.
The inference is only a route hint: Router must execute the live semantic click,
verify the actual landing identity, and then persist a source-local verified
edge. Map-guided registration continues to require `direct_verified` evidence.
The frontier does not let region/global click coverage suppress a peer-navigation
control until that current source owns such a direct edge; a selected control
identifies the current page but is not recorded as click coverage.
Homogeneous `group` collapse applies only to parameterized content rows, never
peer-navigation regions. Tabs, sidebars, bottom navigation, and navigation bars
keep sibling destinations independently explorable; runtime commit, resume, and
completion all exclude those roles from `_explored_groups`/`group_alias`.

Successful natural Back/Close ascents are harvested as verified, regionless
virtual navigation edges with `action_type=BACK`,
`selector.virtual_action=navigate_back`, and
`effect_kind=return|dismiss_overlay`. They carry no visual element id/label or
Region, so they cannot affect Region coverage, capability promotion, grounding,
or normal frontier selection. Router replays them only through its Back
primitive. Normal clicks use `effect_kind=forward|peer_navigation`. Every
inferred or return hop is persisted only after live identity verification.

Router click execution distinguishes `not_attempted`, `dispatch_unknown`, and
`action_dispatched`; compensating Back is forbidden after either of the first
two because an `env.step()` exception cannot prove whether delivery occurred. Under
`--semantic_inventory`, Router click reads one durable source-state element by
stable region/name and performs only target grounding/review. Router identify
uses fresh semantic inventory plus read-only local-`bN` to existing-`rN`
alignment; unresolved/NEW blocks return unknown without mutating RegionRegistry
or graph identity. Semantic touch Back prefers an explicit grounded back/close
control. Android system Back is a special non-grounded Router primitive: when no
visible control exists, or its grounding fails, recovery tries it once and
verifies the landing. If it exits a true root page, existing on-app recovery
remains the fallback. Legacy
`detect_and_name()` still serves non-semantic and not-yet-migrated runtime paths;
this is Router semantic-path isolation, not legacy detector removal.

Verification is selected from the changed contract and its impact. Use the
smallest sufficient tier; historical change-log evidence does not make a test
mandatory for unrelated later work.

| Tier | Trigger | Required evidence |
|---|---|---|
| Tier 1 — documentation or non-behavioral change | No executable behavior or runtime contract changes | Review the rendered/text change and run applicable documentation, diff, or static checks. |
| Tier 2 — module-local behavior change | Behavior is contained within one module and does not alter a shared contract | Run focused tests for the changed behavior, directly affected adjacent-contract tests, and applicable syntax/static checks. |
| Tier 3 — shared framework contract or release-risk change | Shared data contract, entry point, default, schema, Router, resume, completion, cross-module architecture, or release validation changes | Run the framework-contract/release regression gate below. If a command cannot run, record the omitted command, reason, and validation gap. |

The commands below are the **Tier 3 framework-contract/release regression gate**
for schema v3, Page/Variant, and capability-driven traversal. They are not the
default gate for every small or module-local change:

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
python -B tests/test_traversal_completion_certificate.py
python -B tests/test_traversal_failure_ledger.py
python -B tests/test_live_status_summary.py
python -B tests/test_android_env_log_guard.py
python -B tests/test_architecture_boundaries.py
python -B tests/test_capability_atom_contract.py
python -B tests/test_prerequisite_runtime.py
python -B tests/test_visual_prerequisite_agent.py
python -m pytest -q tests/test_federated_capability_catalog.py tests/test_visual_collection_executor.py --basetemp artifacts/scratch/pytest_framework_contracts
python -m compileall -q gui_rewalk/src/core gui_rewalk/env
```

涓婅堪鍩虹闂ㄦ鍦?2026-07-11 鐨勫凡纭绂荤嚎鎵规涓€氳繃锛歊outer 涓?7 passed锛宍PrerequisiteRuntime` 涓?11 tests锛宍VisualPrerequisiteAgent` 涓?12 tests锛宼argeted compile 閫氳繃銆?026-07-12 鍙﹂噸璺?M13 catalog/executor 鍚堝苟鎵规涓?22 passed锛堝惈鍚?Page empty/has-data sidecar 鍚堝苟銆乥locked/available requirement 闅旂涓庡啿绐佹嫆缁濓級锛孧13 CLI銆乧apability atom contract 涓庣浉鍏?`py_compile` 閫氳繃銆傛秹鍙婄湡瀹為亶鍘嗚繕蹇呴』妫€鏌?schema v3 鍙?load銆丳age/Variant 鐩綍闈炵┖銆丄ctionEdge attempts 涓?verified routing 涓€鑷淬€乶ode sidecar 瀹屾暣銆乣stop_reason` 鍚堢悊锛屽苟鐢ㄨ皟璇曞彴/鍥炬煡鐪嬪櫒鏍稿钀藉湴鍜岃兘鍔涙檵鍗囥€?
2026-07-12 瀹屾垚璇佷功鎵规鍙﹁繍琛?`test_traversal_completion_certificate.py`锛坔appy path銆? 绫?fail-closed gate銆丆LI 鍘熷瓙鍐欏叆锛夈€乣test_traversal_failure_ledger.py`锛? 椤癸級銆乣test_live_status_summary.py`銆乣test_graph_quality_agent.py`銆乣test_online_capability_discovery.py`銆乣test_graph_event_ledger.py`銆乣test_stateful_function_surfaces.py`锛? 椤癸級銆乣test_resume_from_graph.py`銆乣test_functional_surface_identity.py`銆乣test_capability_driven_frontier.py`銆乣test_explorer_done_override.py`銆乣test_android_env_log_guard.py`锛? 椤癸級涓?`test_architecture_boundaries.py`锛屽潎閫氳繃锛涚浉鍏?`py_compile` 涓?traversal CLI `--help` 閫氳繃銆備互涓婁粛鏄绾?绾唴瀛橀獙璇侊紝涓嶆浛浠?Settings live 璁よ瘉銆?
**鏈娌℃湁鍚姩 VM銆佹病鏈夎繛鎺?Android emulator銆佹病鏈夎皟鐢ㄧ湡瀹?VLM銆侰lock/Alarm 鐨?empty 鈫?Create 鈫?Editor 鈫?Save 鈫?has_alarm 鈫?Detail 灏氭湭 live 楠屾敹锛涚绾?stub銆佹棫 schema v2 Settings 浜х墿鎴?M13 adapter 娴嬭瘯閮戒笉鑳芥浛浠ｈ闂幆銆?*

## 9. 宸茬煡椋庨櫓

| 浼樺厛绾?| 鐜扮姸 |
|---|---|
| P1 | `visual_engine.py` 浠嶈繃澶э紝婊氬姩銆乫rontier 鍜屽姩浣滀簨鍔￠渶瑕佹寜绋冲畾杈圭晫缁х画鎷嗗垎 |
| P1 | schema v3 Page/Variant銆佸湪绾?discovered鈫抳erified銆丄ctionEdge attempts 鍜?capability-driven frontier 鐩墠鍙畬鎴愮绾?绾唴瀛橀獙璇侊紱Clock empty鈫抎etail銆佹闈?VMware銆丄ndroid emulator 涓庣湡瀹?VLM 鍧囨湭闂幆 |
| P1 | Settings/VS Code 灏氭湭鍙栧緱鏈疆淇鍚庣殑 live `certified`锛氭棦鏈夊け璐ヤ骇鐗╁垎鍒嚭鐜版闈?Settings 4 鑺傜偣/2 鏍?4 涓嶅彲杈俱€乨iscover-only 30 鑺傜偣/4 鏍?30 涓嶅彲杈俱€乂S Code 7 鑺傜偣/3 鏍?7 涓嶅彲杈俱€傛仮澶嶈惤鐐瑰畧鍗笌婊氬姩缁撴潫鍓嶈ˉ瀹＄洰鍓嶅彧鏈夌绾块獙璇侊紱蹇呴』鍦ㄨ祫婧愯幏鎵瑰悗鍏堝仛灏忛绠?fresh/resume 鍐掔儫銆?|
| P1 | 鐙珛閬嶅巻 fresh/resume/off-app 鐨?data-preserving restart 灏氭湭鐢ㄦ櫘閫?Create/Add 璧勬簮鍋氫笓椤?live 楠岃瘉锛涢渶瑕侀殧绂?empty 鐘舵€佹椂蹇呴』鏄惧紡 `--clean_start`锛屼笖 VMware provider reset 浠嶄細鍥炴粴 VM snapshot |
| P1 | M13 铏藉凡绂荤嚎鍏煎 schema v3 verified routing锛屼粛渚濊禆鍥句腑瀛樺湪姝ｇ‘銆佸彲閲嶆斁鐨?app 鍐呰矾寰勫拰 portable capability grounding锛涘浘缂?verified edge/閿?page identity 浼?fail-closed锛屼笉鑳界敱 executor 鐚滄祴琛ヨ矾 |
| P1 | 褰撳墠缁熶竴鍔ㄤ綔杈圭晫宸叉湁鍙 source/target 鐨勮涔?drag锛屼絾涓嶅惈鑷敱杞ㄨ抗銆佸鎸囨墜鍔裤€佷笉鍙鎷栨嫿鐩爣鍙婃墍鏈夊簲鐢ㄤ笓灞炲鍚堣緭鍏ワ紱VS Code 涓庡鏉傜Щ鍔ㄥ簲鐢ㄤ粛闇€ live 楠屾敹杩欎簺鍔ㄤ綔缂哄彛 |
| P1 | 宸ヤ綔鏍戝寘鍚ぇ閲忔湭鎻愪氦鐮旂┒涓庤繍琛屾敼鍔紝璺ㄦ満鍣ㄥ鐜颁粛渚濊禆鍚庣画鏁寸悊鎻愪氦 |
| P2 | schema v1/v2 鍙縼绉诲埌 v3锛屼絾鏃у浘浠庢湭淇濆瓨鎴栬 DiGraph 瑕嗙洊鐨勫け璐?no-effect/off-app/鍚岃妭鐐瑰澶氬姩浣滀笉鍙仮澶嶏紱GraphQuality 浼氭妸杩欑鍘嗗彶鏍囦负涓嶅畬鏁?|
| P2 | page canonicalization銆乿ariant facts銆佸嚱鏁伴泦 Jaccard銆乻elected navigation 涓?permission VLM 瀛楁灏氭湭鍦ㄩ鎵逛簲绫诲簲鐢ㄤ笂鍋氱粺璁℃牎鍑嗭紱浣庣疆淇″害搴斾繚鐣欑嫭绔嬫墽琛岀姸鎬佹垨 unknown/conditional锛屼笉鑳藉己琛屽悎骞?鏅嬪崌 |
| P2 | 鍦ㄧ嚎 discovered capability 鏉ヨ嚜鍙鎺т欢锛屼粛鍙兘鏈夎涔夊懡鍚嶃€佸弬鏁板寲鎴栧悓涔夊悎骞惰宸紱鍙湁 verified action evidence 鍙繘鍏ヨ矾鐢憋紝绂荤嚎 synthesizer 涓嶈兘琛ヤ笟鍔￠獙璇?|
| P2 | GraphQuality 鑳藉彂鐜板綋鍓嶈瘉鎹唴鐨勯敊璇?鏉′欢/闃诲锛屼絾鍗曢潬宸查噰鍥句笉鑳借瘉鏄庡簲鐢ㄤ腑鈥滀粠鏈鍙戠幇鈥濈殑鍔熻兘涓嶅瓨鍦紱`unsupported` 闇€瑕侀澶栧彲瑙佽瘉鎹?|
| P2 | AndroidWorld 鏋勯€犱粛鏄惧紡浼?`install_a11y_forwarding_app=False`锛岃繖鏄樆姝笂娓稿畨瑁呯殑瀹夊叏寮€鍏筹紝涓嶆槸 observation 鏁版嵁閫氶亾 |
| P2 | `popup_menu` active-surface 璇嗗埆鍜屾诞灞傚瓨缁噸缁戝凡鏈夊悎鎴?绾唴瀛樺洖褰掞紝浣嗗皻鏈湪 Android Notifications 鎺掑簭 popup 涓婇噸鏂?live 楠屾敹锛涙ā鍨嬫紡鎶?surface 鏃朵粛浼?fail-closed 鎴栫暀涓嬫湭瀹屾垚璇佷功锛屼笉鑳芥嵁绂荤嚎娴嬭瘯瀹ｇО绉诲姩 Settings 宸蹭慨澶?|

## 10. 淇敼璁板綍瑙勫垯

姣忔鏀瑰彉妗嗘灦琛屼负鏃跺繀椤诲悓鏃讹細

1. 鏇存柊鏈枃鈥滃綋鍓嶇幇鐘垛€濆搴旂珷鑺傘€?2. 鏇存柊鐩稿叧妯″潡鏂囨。銆?3. 鍦ㄤ笅鏂硅拷鍔?changelog锛屽啓鏄庤涓恒€乻chema/CLI銆佽縼绉诲奖鍝嶃€佹枃浠躲€侀獙璇佸懡浠ゅ拰缁撴灉銆?4. 涓嶅緱鎶婁粎鏈夐潤鎬佹鏌ュ啓鎴愮湡鏈?VLM 宸查獙璇併€?
## 11. 鍙樻洿鏃ュ織

### 2026-07-18 — headless local visual backend and Mingle live comparison

- Environment/CLI: added `--vm_provider local_html`, `--html_path`, and
  `LocalHTMLGUIGenEnv`. The adapter launches one headless Chromium context at the
  requested viewport and implements screenshot, pixel click/type/press/scroll/
  drag/Back, reload, and close. `run_visual_traversal.py` no longer imports the
  desktop OSWorld environment on Android/local-HTML paths, and local HTML skips
  desktop/Android lifecycle setup. Mingle defaults to its standalone HTML when
  no path is given. No DOM/oracle information enters the engine.
- Landing fix: before/after pHash equality may be `numpy.bool_`; landing now
  normalizes it with `bool()` before producing the existing evidence. This fixes
  a real Search-click `NoneType` crash without changing verdict, commit, identity,
  Router, schema, or completion semantics.
- Live Mingle evidence: a real DashScope/Qwen run at
  `artifacts/runs/mingle_local_html_20260718/20260718/mingle_210401` completed at
  `stop=max_actions` with 5 States / 16 actions. It registered visible Chats,
  Weekend Plan, Contacts, and Explore surfaces, accurately grounded Search,
  Weekend Plan, bottom navigation and several disabled controls, and persisted
  5 screenshots, 13 action edges, 18 attempts, 8 verified action edges, 5 scroll
  scopes, and 31 capabilities. The completion certificate is correctly
  `incomplete`: frontier exhaustion, control coverage, and routing reachability
  failed. The oracle comparison is also `fail`: 3/8 canonical Pages aligned,
  5 missing Pages, 26 missing controls, 33 missing verified transitions, 3 missing
  surfaces, and 3 incomplete long-page scopes. It also exposed a hallucinated
  `Dark mode toggle` and disabled rows misclassified as actionable navigation.
- Performance: browser/environment startup reached the graph in about 3 seconds,
  but the bounded run still took about 10m41s because 95 logical VLM calls
  accumulated 610.2 seconds of model latency. Removing the emulator therefore
  isolates environment cost but does not solve the dominant model-call volume.
- Verification: `python -m pytest -q tests/test_local_html_env.py
  tests/test_landing_change_evidence.py tests/test_visual_run_state_machine.py
  tests/test_synthetic_mobile_fixture.py tests/test_app_lifecycle_preserve.py
  --basetemp artifacts/scratch/pytest_local_html_final` -> `23 passed, 1 cache
  warning in 2.91s`; targeted `python -m py_compile` and `git diff --check` ->
  exit 0 (line-ending warnings only). The direct validator CLI was
  fixed to import its sibling workspace package and produced
  `oracle_comparison.json`. This is real Qwen and real pixel-action evidence in
  headless Chromium, not Android/ADB/platform validation.

### 2026-07-18 — Mingle deterministic Android communication fixture

- Fixture/UI: added `synthetic_mobile_app/`, a daily-use styled 412x915 Mingle
  chat application with 8 semantic Pages, 42 page controls, 3 long pages, and
  new-chat/attachment/clear-history active surfaces. Its standalone HTML,
  Android WebView asset, inspector, oracle, 17 current-prompt Qwen-shaped
  responses, validator, smoke flow, and reference captures describe the same
  Page/block/control/transition/scroll contract without changing the prompt.
- Lifecycle/config: registered `app_name="mingle"` as
  `com.guirewalk.mingle/.MainActivity`, allowlisted clean data reset, and added a
  first-launch `adb install -r` path for the repository APK. Installation is
  remembered only on the current env, while existing preserve-data restart and
  explicit clean-start semantics remain unchanged for other applications.
- Files: `synthetic_mobile_app/*`, `gui_rewalk/src/config/config.py`,
  `gui_rewalk/src/core/graph/mobile_ops.py`, the focused mobile fixture tests,
  Android/environment module docs, and this current-state/changelog entry.
- Verification: `python -m pytest -q tests/test_synthetic_mobile_fixture.py
  tests/test_synthetic_fixture_app.py tests/test_app_lifecycle_preserve.py
  --basetemp artifacts/scratch/pytest_mingle_mobile_final` -> `8 passed in
  0.78s`; explicit `python -m py_compile` for the new/affected Python files and
  targeted `git diff --check` -> exit 0 (line-ending warnings only);
  `python synthetic_mobile_app/smoke_test.py` ->
  `PASS Mingle mobile navigation/state/overlay/scroll smoke`; reference capture
  regenerated 8 viewport/full-page/surface PNGs. `mingle-debug.apk` was packaged
  successfully on the host and has SHA-256
  `E42DFECC204E5375EA9EFABE8389FDCD7B42B08B96999E963DA2F1B4ED1253EE`.
  `adb devices` listed no connected AVD, so no real Android click, Qwen/VLM call,
  live traversal, or completion certificate is claimed.

### 2026-07-18 — Dayline desktop presentation and canonical VM app name

- Presentation: changed the visible synthetic application from a narrow
  test-oriented surface to a 1365x900-oriented Dayline desktop workspace with a
  persistent sidebar, top toolbar, documents, recent activity, weekly summary,
  settings, product notes, popup, dialog, and three natural long pages.  Internal
  Page/control/action IDs and the 8 Page / 30 block / 43 control contract remain
  unchanged; fixture/oracle/benchmark terminology is no longer visible in the app.
- Lifecycle: canonical launch is now `--app_name dayline`; the maximized Chrome
  app-mode guest installation, `/tmp/gui_rewalk_fixture` path, isolated profile,
  and clean-start boundary are unchanged.  `rewalk fixture` remains a compatible
  alias, and both aliases install the embedded HTML before launch.
- Prompt/oracle: updated the machine oracle, 15 generated Qwen-shaped responses,
  Playwright flows, and reference images to the visible Dayline labels without
  changing `SEMANTIC_INVENTORY_PROMPT`, parser fields, graph schema, Router, or
  completion policy.  Unique identity/surface anchors avoid false merge and
  detached-overlay findings despite repeated sidebar labels.
- Verification: `python -m pytest -q tests/test_synthetic_fixture_app.py
  tests/test_app_lifecycle_preserve.py --basetemp
  artifacts/scratch/pytest_dayline_desktop_final2` -> `4 passed in 1.01s`;
  explicit `python -m py_compile` for affected Python files -> exit 0;
  `python synthetic_app/smoke_test.py` ->
  `PASS Dayline navigation/state/overlay/scroll smoke`; reference capture
  regenerated 7 desktop/full-page PNGs and Home/Documents were visually inspected.
  These are local headless Chromium, offline parser/stub, unit, and static checks.
  The in-app browser could not claim the existing `file://` tab because that URL
  is blocked by its policy.  No VMware guest, real Qwen/VLM call, live traversal,
  or completion-certificate run was performed.

### 2026-07-18 — deterministic fixture app and current-prompt Qwen oracle

- Environment: added repository-owned `app_name="rewalk fixture"`.  Desktop
  launch copies the generated standalone HTML through the existing guest Python
  channel to `/tmp/gui_rewalk_fixture/index.html`, starts Chrome app mode with a
  dedicated `/tmp/gui_rewalk_fixture/profile`, and requires neither network nor
  host/guest file sharing.  `--clean_start` clears only that profile;
  data-preserving restart retains its local state.
- Fixture contract: `synthetic_app/oracle.json` defines 8 semantic Pages, 30
  blocks, 43 controls, 3 long scroll scopes, 2 active overlays, Page/Variant
  expectations, and required transitions.  The inspector and 7 reference images
  expose this truth to humans; `validate_graph.py` aligns opaque runtime Page IDs
  and reports missing/split/merged Pages, controls, direct verified transitions,
  detached overlays, and incomplete long-scroll evidence.
- Prompt reuse: 15 generated Qwen-shaped observation replies use the unchanged
  `SEMANTIC_INVENTORY_PROMPT` field contract and contain no geometry.  Long-page
  replies list only the selected top/bottom viewport; popup/dialog replies exclude
  the inactive background.  `QwenFixtureStub` is explicit offline parser input,
  not screenshot recognition and not live-model evidence.
- Files: `synthetic_app/*`, `gui_rewalk/src/config/config.py`,
  `gui_rewalk/src/core/app_lifecycle.py`, focused tests, environment module docs,
  and this current-state/changelog entry.  Existing graph schema, Router,
  perception prompt, and completion policy are unchanged.
- Verification: `python -m pytest -q tests/test_synthetic_fixture_app.py
  tests/test_app_lifecycle_preserve.py --basetemp
  artifacts/scratch/pytest_fixture_app_final` -> `4 passed in 1.03s`; explicit
  `python -m py_compile` for every new/affected Python file -> exit 0;
  `python synthetic_app/smoke_test.py` ->
  `PASS fixture navigation/state/overlay/scroll smoke`; reference capture
  generated 7 PNGs and Home, Library/Activity long pages, popup, dialog, and the
  oracle inspector were visually inspected.  These are local headless Chromium,
  offline stub, and static/unit checks.  No VMware guest, real Qwen/VLM call,
  live traversal, or completion-certificate run was performed.

### 2026-07-18 — freeze assigned Page identity and remove hierarchical Page anchors

- Identity contract: the map-guided source/action/neighbor decision remains the
  only online authority for selecting an existing Page. A newly created Page ID
  is frozen; revisits may add elements, Regions, facts, and Variant evidence but
  cannot rename or re-hash the Page. Resume uses the persisted Page ID.
- Removed contract B: block `page_identity`, Region-derived Page anchors,
  `page_anchor_tokens`, the hierarchical Page hash/version, and their prompt,
  graph, artifact, and resume plumbing were removed. Element `identity_anchor`
  remains only as Region-member stability evidence and does not identify Pages.
  Loading an old graph drops Page-anchor fields and normalizes the legacy version
  marker without changing its persisted Page ID.
- Transition-viewer audit (read-only): the latest Clock graph has one verified
  root and all seven States are routing-reachable. It stopped because Qwen
  returned invalid semantic-inventory JSON after `Expand alarm`. Independent
  incomplete evidence remains: semantic-inventory runs wrote no scroll-ledger
  scopes, the saved run predates the peer-navigation `group_alias` correction,
  and two `More options` capabilities reference element IDs absent from their
  final revisited node snapshots. No device action was performed by this audit.
- Files: `state/{registry,registration,block_identity}.py`,
  `grounding/region/{registry,scroll,__init__}.py`, `visual_resume.py`,
  `visual_perception.py`, `visual_engine.py`, `prompts/grounding.py`,
  `artifacts.py`, `graph/state_graph.py`, focused tests, and current module docs.
- Verification (offline/static only): targeted `py_compile` for the changed
  production modules -> exit 0; `python -m pytest -q
  tests/test_frozen_page_identity.py tests/test_semantic_block_identity.py
  tests/test_map_guided_identity.py tests/test_resume_from_graph.py --basetemp
  artifacts/scratch/pytest_frozen_page_identity_final` -> `29 passed in 1.05s`;
  `python -m pytest -q tests/test_traversal_completion_certificate.py --basetemp
  artifacts/scratch/pytest_page_completion_final` -> `9 passed in 0.10s`. These
  checks are not live VLM, emulator, or runtime traversal validation.
- Deploy/live smoke: archive SHA-256
  `564f61045c993899086a8256b6af4bf609eaf1434b95510b9f9ced2d2c86ae6c`
  was deployed to deploy-asr after creating
  `/home/shenghonghui/deploy_backups/guiwalk_before_frozen_page_20260718_0156.tgz`.
  The same focused suites passed remotely (`29 passed`, then `9 passed`). Two
  read-only Android/Qwen semantic-inventory traversals were started on ports
  5628/8628 (`android_settings`) and 5630/8630 (`android_clock`). Both completed
  root registration and created a second Page/State (`Your info` and `Alarm`)
  without Page-ID recomputation. Settings then stopped fail-closed with
  `state_restore_failed` (2 States/1 verified action): after Back, both direct
  observation and a data-preserving restart returned
  `unresolved_semantic_block`, so its certificate is incomplete. Clock remained
  active and reached five States; a Back ascent from `ambient_clock` was
  recognized as `Alarm`, routed to the existing Clock node, and the Clock
  revisit merged without changing its Page ID. This is live smoke evidence, not
  a completed two-app certification. The Settings recovery failure is a separate
  strict State/Region re-identification issue, not evidence that frozen Page
  identity failed.

### 2026-07-17 — Clock shared-navigation/return-edge accounting fix

- Root cause: the first Clock state opened on persisted Bedtime. Frontier marked
  its selected Bedtime tab as region-clicked even though no Bedtime click had
  occurred. On Alarm, shared coverage could therefore prune Bedtime before
  Alarm→Bedtime was observed. Bedtime→Alarm already existed; the missing relation
  was the reverse host-local transition.
- Frontier now separates shared exploration coverage from source-local direct
  edge evidence. Selected navigation is not click coverage, and explicit peer
  tabs/sidebars remain eligible on a source until its direct edge is verified.
- Router may plan a unique `peer_inferred` tab/sidebar target from a selected or
  verified occurrence. It still executes the real semantic click, verifies the
  live landing identity, and then records the source-local edge. Host-relative
  top-bar/overflow actions remain `shared_pending`; map-guided registration
  continues to require `direct_verified` evidence.
- Natural successful Back/Close ascent is harvested after identity verification
  into the existing ActionEdge schema with `effect_kind=return` or
  `dismiss_overlay`; replay invokes Back rather than click. Click effects are
  `forward` or `peer_navigation`. No general transition-classification VLM call,
  pre-emptive A→B→A→B validation loop, or separate return-edge schema was added.
- Files: `navigation/router.py`, `navigation/frontier.py`, `visual_engine.py`,
  `state/registration.py`, `graph/state_graph.py`, focused tests, and the current
  visual-traversal/state-graph module documentation. Concurrent Region screenshot
  persistence files were not edited.
- Verification (offline/in-memory/static only): targeted `python -m py_compile`
  on the five changed production modules exited 0;
  `python -m pytest -q tests/test_visual_router.py tests/test_frontier_policy.py
  tests/test_map_guided_identity.py` -> `36 passed`; `python -m pytest -q
  tests/test_visual_run_state_machine.py` -> `19 passed`. No VM, device, real
  Qwen/VLM, or live Clock traversal was run, so this is implementation evidence,
  not live traversal completion.

### 2026-07-17 — Peer-navigation group aliases no longer retire sibling tabs

- Root cause found live: after the region/source-local fix, Clock exploration
  still left Bedtime unclicked because Qwen emitted `group=bottom_nav`. The old
  homogeneous-list policy treated one verified tab as representative of all
  sibling destinations; completion then incorrectly resolved Bedtime as
  `group_alias` of Clock.
- Behavior: homogeneous group collapse remains for parameterized content lists
  such as alarms/apps/songs, but explicitly excludes peer-navigation roles in
  frontier filtering, successful coverage commit, resume reconstruction, and
  completion certification. Alarm/Clock/Bedtime remain separate navigation
  obligations even when they share one region and one VLM group label.
- Files: `navigation/frontier.py`, `visual_engine.py`, `visual_resume.py`,
  `graph/traversal_completion.py`, focused frontier/completion/resume tests,
  `design/modules/visual_traversal.md`, and this file. No graph schema or page
  identity contract changed.
- Verification (offline/static): focused peer-group checks reported `2 passed`;
  the directly affected three-file set reported `17 passed`; targeted production
  and test `py_compile` exited 0 after the final role-set alignment. Re-evaluating
  the live graph with the corrected completion code reports Alarm's Bedtime as
  `outcome=unresolved`, `region=primary_navigation`, `group=bottom_nav`, rather
  than the old false `group_alias`. The preceding live
  Qwen Clock run reached 7 states/11 actions and proved source-local Alarm
  More-options exploration, but stopped incomplete at `perception_unavailable`
  after Qwen returned invalid semantic-inventory JSON for `Expand alarm`. That
  live run exposed the Bedtime alias bug and is not validation of this subsequent
  fix.

### 2026-07-17 — Android system Back fallback for control-less pages

- Recovery: semantic Router Back still prefers an explicit grounded Back/Close
  control, but a touch surface without one now sends one Android system Back and
  verifies the actual landing. A visible control whose live grounding fails also
  falls back to the same system primitive. This fixes fullscreen/detail pages
  that expose no visual return affordance; a true root-page exit remains covered
  by the existing on-app recovery path.
- Files: `visual_engine.py`, focused semantic-grounding test,
  `design/modules/visual_traversal.md`, and this file. No graph schema, frontier,
  page identity, completion, or ordinary click-grounding contract changed.
- Verification (offline/static): `python -m pytest -q
  tests/test_semantic_inventory_grounding.py -k "semantic_touch_page_without_control
  or router_env_error"` -> `2 passed, 17 deselected`; targeted `py_compile` of
  `visual_engine.py` and the focused test exited 0. Live Android Clock validation
  is started separately and is not claimed by these checks.

### 2026-07-17 — Phase-1 semantic Router safety hotfix

- Routing: shared Region occurrences keep inventory and region-keyed coverage,
  but no longer inherit a destination verified on another source. They expose
  `shared_pending` / `dst=None`; a current-source verified direct edge overrides
  them and remains routable with source/region/provenance metadata. This
  temporarily disables all cross-host destination inheritance, including bottom
  navigation and sidebars, until verified pending/absolute sharing lands.
- Execution/recovery: Router click results distinguish `not_attempted`,
  `dispatch_unknown`, and `action_dispatched`; no compensating Back is attempted
  after either of the first two. An `env.step()` exception is dispatch-uncertain,
  never treated as safely dispatched. Semantic click
  resolves one durable source-state element by stable region id and name, then
  uses target-only grounding/review. Semantic identify performs read-only
  existing-concept alignment before state identity; NEW/unresolved blocks fail
  unknown without registry/graph mutation. Semantic touch Back uses an explicit
  grounded back/close control and does not send raw Back on a root page without
  an overlay/control. Legacy `detect_and_name()` remains for non-semantic and
  not-yet-migrated paths; no full removal is claimed.
- Files: `navigation/router.py`, compatibility `visual_router.py`,
  `visual_engine.py`, `state/block_identity.py`, three focused tests, this file,
  and `design/modules/visual_traversal.md`. No CLI, graph schema, page identity,
  completion, ordinary frontier landing, or click-verifier contract changed.
- Verification (offline/static only): `python -B -m pytest -q
  tests/test_visual_router.py tests/test_semantic_block_identity.py
  tests/test_semantic_inventory_grounding.py tests/test_visual_run_state_machine.py
  tests/test_map_guided_identity.py` -> `74 passed, 1 warning` after the final
  dispatch-unknown review correction. Targeted `py_compile` and the Section 8 `compileall` command
  exited 0. The remaining Section 8 commands passed, including catalog/executor
  (`22 passed`), except the architecture script: its visual-engine `<2800` gate
  now passes at 2799 lines, then it stops on a pre-existing dirty-tree
  compatibility gap because `visual_agents.py` does not export the already-added
  `BlockIdentityJudge`. That shim is outside this bounded package, so the gate is
  not claimed fully green. A later bounded Android Clock run with Qwen
  `qwen3.7-plus` at
  `artifacts/runs/mobile_clock_qwen_router_phase1_20260717/20260717/android_clock`
  produced 9 states / 8 actions and stopped normally at `max_states`. It
  registered separate verified direct `More options` edges for Alarm and Clock,
  while the reached Bedtime node had no inherited direct popup edge. Root-page
  recovery also logged `touch_root_without_control` instead of sending raw Back;
  the old `state_restore_failed` crash did not recur. The budget ended immediately
  after Bedtime registration, so physically opening Bedtime's menu remains
  outside this bounded live run.

### 2026-07-17 — known-state no-effect cursor resynchronization

- Behavior: a rejected ordinary navigation `no_effect` still commits no edge,
  coverage, visited state, or capability. When its registered observation is a
  different existing state with runtime data, the cursor now adopts that known
  state's persisted path/replay hints plus the current observation. This fixes
  popup/off-app recovery returning physically to a known base page while the
  logical cursor remained on the popup.
- Safety/scope: new provisional landings, missing runtime state, stateful actions,
  `uncertain`, `transitioned_inconsistent`, and `blocked` behavior are unchanged.
  Page/State identity, Router, grounding, click verification, graph schema,
  completion, entry points, and defaults are unchanged.
- Files: `runtime/landing.py`, `tests/test_visual_run_state_machine.py`, this
  document, and `design/modules/visual_traversal.md`.
- Verification: `python -B -m pytest -q tests/test_visual_run_state_machine.py
  tests/test_map_guided_identity.py` and targeted `py_compile` cover the known
  popup-to-base resync and the untrusted-new-state negative case. These are
  offline in-memory/static checks (`35 passed`). A bounded Android Clock rerun at
  `artifacts/runs/mobile_clock_cursor_resync_noclean_20260717/20260717/android_clock`
  produced 7 states / 6 verified actions and did not repeat the old
  popup-belief/base-frame source mismatch: after Screen saver reached the Android
  full-screen instruction, recovery registered the relaunched Clock frame as the
  existing `76111f90` state and then successfully traversed Alarm, Timer,
  Stopwatch, and Bedtime. That run did not emit `no_effect_cursor_resync` because
  Screen saver was accepted as a real transition, so it is live regression
  evidence around the failure path, not direct live execution of the new branch.
  It stopped incomplete at `state_restore_failed` when Router later attempted to
  reuse the Clock-home `more options` edge directly from Bedtime and recovery
  landed off-app; no traversal-completion claim is made.

### 2026-07-17 — risk-tiered verification policy

- Process only: verification now uses Tier 1 documentation/non-behavioral,
  Tier 2 module-local behavior, and Tier 3 shared framework-contract/release-risk
  triggers. The existing Section 8 command set is the Tier 3 gate, not a default
  for every small edit. Test selection follows the changed contract and impact;
  historical change-log evidence does not automatically expand later scope.
- Sol-to-Terra review reuses complete, credible implementer evidence by default;
  root remains responsible for the final validation judgment and reruns only for
  missing/failed evidence, post-verification changes, important environment
  differences, or risk-driven independent confirmation. No runtime behavior,
  data contract, entry point, default, or schema changed.
- Verification (documentation/static only): `git diff --check -- AGENTS.md
  design/CURRENT_FRAMEWORK.md` passed; targeted `rg` review and `git diff --
  AGENTS.md design/CURRENT_FRAMEWORK.md` confirmed the tier triggers, gate label,
  evidence-reuse rule, and two-file-only implementation scope. No VM/emulator/VLM/live or Tier 3
  regression command was run.

### 2026-07-15 — region package and repository archival boundaries

- Boundary: region identity/coverage now lives in `grounding/region/registry.py`;
  region-aware segmentation and scroll dedup live in `grounding/region/scroll.py`.
  `grounding.region` re-exports the public registry and scroll APIs, while the root
  `region_registry.py` shim preserves import identity. Neither canonical module
  imports `visual_engine.py`; their sizes are 460 and 692 lines.
- Layout: root paper material moved to `research/paper/{plans,generated,references,figures}`
  and dated notes to `research/history/{monitoring,handoffs,sessions,agent_prompts}`.
  Imported graphs/evaluation corpora moved to `data/{imported,evaluation}`; legacy
  diagnostics, upload bundles, scratch demos, and logs moved to category-specific
  `artifacts/*/legacy/` directories. Root Markdown is limited to the four maintained
  entry documents. No dataset or artifact content was rewritten.
- Tools: the three paper inventory/extraction/statistics utilities derive inputs and
  generated outputs from the repository root, with environment overrides for external
  inputs. Generated reports default to `research/paper/generated/`.
- Verification (local static/offline only): post-move checks matched every one of the
  13 pre-move file-count/byte-count pairs and found all old root sources absent;
  targeted `compileall` and RegionRegistry import-identity smoke passed;
  `python -m pytest -q tests/test_architecture_boundaries.py tests/test_repository_layout.py tests/test_scroll_waste.py tests/test_list_content_merge.py tests/test_visual_stitch.py tests/test_stitch_node_integration.py tests/test_modal_candidate_policy.py tests/test_visual_block_membership.py`
  reported `27 passed, 4 warnings`. No VM/emulator, real VLM, live click, or landing
  validation was run.

### 2026-07-17 / online visual semantic-block concepts

- Identity: semantic inventory emits anonymous local `bN` blocks. A separate
  strict normalized_1000 batch localization creates transient crops, and at most
  one bounded crop-atlas VLM call aligns a multi-block observation to
  registry-minted `rN` concepts before page identity/frontier. First observations
  localize and mint without an identity call. Same-surface candidates are ordered
  prior frame, likely page roster, then app-local fallback; same role ranks first
  but role/anchor drift is not identity authority. Malformed, unknown, duplicate,
  uncertain, or failed mapping is NEW with no active click probe.
- Page/coverage: semantic region sets contain stable `region:rN` concepts and
  `tab_selected:<name>` state. Region coverage prunes an already clicked action
  on later occurrences before scheduling. Base-popup-base keeps base concepts,
  adds one popup concept, and resolves to two states in the registry test.
- Page anchors: semantic registration projects stable background/page concepts
  plus canonical `selected:semantic_navigation:<name>` and excludes overlay
  concepts. It no longer consumes VLM `identity_anchor`/`page_identity`; the
  Clock base/popup Page-ID drift found in live evidence is covered offline.
- Audit/backcompat: `block_identity_attempts/` stores transient crops/atlases and
  JSON with descriptors, allowed candidates, bounded raw response, validated
  mapping/reasons, and created concepts. Geometry never enters semantic inventory,
  elements, or graph. Legacy ids and clicked coverage rebuild, but representative
  crops are not rehydrated; post-resume matching is fail-closed and limited until
  new representatives are observed.
- Live Clock evidence: the run at
  `artifacts/runs/mobile_clock_online_block_identity_20260717/20260717/android_clock`
  produced 7 states / 8 actions from 9 semantic observations. Its VLM ledger has
  9 `block_localization` calls and 8 `block_identity` calls: the first observation
  minted `r1-r4` without alignment. The first popup reused `r1-r4` and minted only
  `r5`; the Alarm popup later reused `r5`; a Clock-base revisit mapped exactly
  `r1-r4` and merged the original `76111f90`, so no third Clock home was created.
  Header `r1` and bottom navigation `r4` were reused across tabs while selected
  tokens differentiated states. All 7 `semantic_blocks.json` files had zero bbox
  fields. The run stopped incomplete with `state_restore_failed` from an independent
  off-app/popup cursor misattribution, not block identity; no completion is claimed.
- Page-anchor follow-up: that live run exposed the old label-authority bug because
  Clock base/popup had different Page IDs before the stable-concept projection.
  Offline post-fix projection over the 7 real node artifacts now yields equal
  Clock base/popup anchors, equal Alarm base/popup anchors, and different Clock vs
  Alarm anchors. A post-fix short live rerun did not start because host ADB failed
  with `fdevent interrupt socketpair: no buffer space`; this is an environment
  blocker and is not post-fix live validation.
- Files: `visual_perception.py`, `prompts/navigation.py`, `agents/identity.py`,
  new `state/block_identity.py`, `state/registration.py`,
  `grounding/region/registry.py`, `visual_engine.py`, `visual_resume.py`,
  `artifacts.py`, focused tests, and visual traversal documentation.
- Implementation verification (offline/static): the focused/adjacent pytest command reported
  `65 passed, 1 warning in 5.78s`; targeted `py_compile` and `git diff --check`
  were run after final code edits. The separate live evidence above is an
  incomplete block-identity run; the Page-anchor correction has only the stated
  real-artifact offline projection because the post-fix ADB launch was blocked.
  This documentation-only evidence update was checked with `git diff --check --
  design/CURRENT_FRAMEWORK.md design/modules/visual_traversal.md`.

### 2026-07-16 — region-first visual relocation for desktop

- Current behavior: region-aware registration keeps a runtime-only first-view crop
  and, after scrolling, the stitched region composite. On a later live frame,
  `match_region_view()` confirms the current viewport against that map with ORB
  anchors plus a RANSAC similarity transform; a conservative edge-template path
  covers feature-poor but pixel-stable blocks.
- Element behavior: each runtime element may keep a row/local context patch and
  its centre offset. Context relocation is accepted only when the best template
  peak is separated from the next independent peak by at least `0.08`; repeated
  bare controls therefore fail closed instead of choosing an arbitrary copy.
- Safety/contract: large-region evidence must pass before element visual evidence
  is considered. It supplies only an expected location to current-frame VLM
  grounding. Overlay/region geometry, noninteractive rejection and reviewer QA
  remain the click authority. Visual arrays are process-local and do not alter
  graph schema, page identity, capability, CLI or resume contracts.
- Files: `visual_relocate.py`, `grounding/region/registry.py`,
  `grounding/region/scroll.py`, `live_targeting.py`, `visual_engine.py`, focused
  tests, disposable offline reports, and the visual traversal design module.
- Offline real-Settings evidence: the production matcher accepted 4/4 archived
  views of the same Settings navigation region, rejected 3/3 different same-role
  or wrong-app regions, and matched a real 1053px viewport into a 3212px content
  composite. In the repeated `Unset` example the bare control margin was `0.0011`
  while its row-context margin was `0.3787`.
- Verification before live rollout: targeted `py_compile` passed; focused region,
  live-targeting, popup, scroll, sidebar and ledger suite reported `19 passed`.
  The archived-image command and structured
  results are in `design/icon_phash_report/block_template_offline/`.
- Bounded desktop Settings smoke: four real nodes (About, Network, Bluetooth,
  Background) were registered and the shared navigation remained `region:r1`.
  Three navigation targets were current-frame retargeted and their landings
  succeeded. An unstable `Toggle Bluetooth` was rejected twice and retired with
  `target_rebind_failed` without a click. The run was manually stopped after four
  nodes, so no completion certificate or full-traversal claim is made. It also
  exposed a pre-existing independent issue: incomplete scroll-ledger evidence
  causes the shared navigation to be re-audited on each page.

### 2026-07-15 — grounding scroll/stitch extraction and dead-code retirement

- Boundary: `grounding/scroll.py`, `grounding/region_scroll.py`, and
  `grounding/stitch.py` now own viewport scrolling, region-aware scroll, and
  stitching/tiled perception. They receive explicit contexts and never import
  `visual_engine.py`; `visual_stitch.py` is a compatibility re-export.
- Retirement: traversal discovery seed resolver/setup/cleanup, the old
  `_tabbar_center` geometry path, unused overlay wrappers, resume element wrapper,
  and unused queue helper were removed. M13 prerequisite runtime and current
  region-bound live targeting remain. Older changelog text mentioning an Engine
  seed resolver or `_tabbar_center` describes retired history, not current state.
- Size/compatibility: `visual_engine.py` decreased from about 6.6k to 4.6k lines;
  method wrappers, scroll constants/functions, stitch overrides, and direct buffer
  attributes remain compatible. No threshold, prompt, schema, CLI default, or
  traversal policy was intentionally changed.
- Verification (local offline/static only): focused architecture/run-state/popup/
  scroll/stitch/region suite `45 passed`; targeted `compileall` passed. No
  VM/emulator, real VLM, live click,
  or landing validation was run.
- Full-suite attempt: root-side `python -m pytest -q tests` did not reach runtime
  execution because collection was interrupted by the pre-existing top-level
  `sys.exit(0)` in `tests/test_group_fold_identity.py` and reported 3 collection
  errors. This is recorded separately from the targeted `45 passed`; no full-suite
  pass is claimed for this change.

### 2026-07-15 — repository layout and visual runtime boundaries

- Behavior: no intentional policy/schema change. Effective prompt strings and frontier
  filter order were preserved. Agent roles were mechanically split by responsibility;
  Engine delegates frontier selection through an explicit dependency dataclass.
- Layout: region/router moved to canonical subpackages with old-path shims; 72
  `tools/test_*.py` files moved to `tests/`; visual runs default to `artifacts/runs/`;
  historical root artifacts moved without deletion to `artifacts/*/legacy/`.
- Verification (local offline/static only): targeted compile/import passed; focused agent/
  prompt/frontier/architecture suite `21 passed`; overlay/stateful/permission/frontier/
  router/resume suite `45 passed`. No VM/emulator, real VLM, live click, or landing
  validation was run.

### 2026-07-14 / working-tree — 当前帧 live targeting 组件拆分与临时物清理

- Boundary：新增 `visual_traversal/live_targeting.py`，显式接收 env、perception 与 reviewer，集中负责 bbox 几何、overlay 绑定/存活门、region 门、UID/state_key 实时匹配、noninteractive 诊断、click QA 最多一次强制刷新、stateful 几何回填和 fresh observation 编排；该模块不导入 `visual_engine.py`。`VisualTraversalEngine._live_center_for(elem, obs)` 保留薄兼容 wrapper，M13 `live_visual_collection.py` 调用不变。
- Compatibility：fresh env capture、调用方 obs 原位更新、`_last_live_rebind_observation` 状态语义、overlay kind/bbox、region bbox、`assign_element_uids`、review reject fail-closed 与 stateful 回填保持原契约。`visual_engine.py` 从本工作包开始时的 7073 行降至 6832 行。
- Hygiene：更新活跃 Explorer 陈述与过滤测试措辞；补充 `*.pid`、`.codex_current_*.txt`、`.pytest_cache/` ignore。仅清理根目录 `*.log/.tmp_*.py/*.pid/.codex_current_*.txt`、根 `_scratch/.pytest_cache` 和仓库内 `__pycache__`，不触碰结果、数据、归档、研究材料或其他未跟踪源码。
- Verification（本机离线/静态，非 VM/VLM/live）：targeted `py_compile` exit 0；`test_live_targeting.py`、`test_popup_surface_guard.py`、`test_scroll_locate.py`、`test_visual_run_state_machine.py`（16 PASS）、`test_architecture_boundaries.py`、`test_explorer_done_override.py`、`test_visual_filter_widen.py` 均 exit 0；`pytest -q -p no:cacheprovider tools/test_graph_quality_guards.py -k "qwen_center or reviewer or live_noninteractive or stateful_live_rebind or revisit_topup"` 为 7 passed/3 deselected。完整 `test_graph_quality_guards.py` 在本改动前后均受既有 `test_data_controls_are_node_local` 断言阻塞，本条不宣称全脚本通过。未启动 VM/emulator，未调用真实 VLM，未做 live 点击或落地验收。

### 2026-07-14 / working-tree — 功能入口 Prompt MVP 与 grounding 启动收口

- Behavior：SoM naming 与 direct grounding 共用精简的 feature-entry 分类、上下文本地表单完成、非提交 back 和截图 prompt-injection 边界。Create/Add/Save/Done/Open 不按名称放行或封禁；安全的新 App 内功能表面/本地完成动作是 `navigation`，普通输入/单值/外观是 `shallow`，安全性不确定继续 `dangerous`。保留 active surface、modal/system dialog/interruption、page/关键 display anchors、permission 和 switch stateful 字段；未改 schema、Engine 或调度。
- Startup：`--vlm_grounding` 不再加载未使用的 OmniParser YOLO，空 grounding 继续 fail closed 且不回退；legacy 非 grounding 路径仍加载 YOLO+OCR，`--ocr_model_path` 保留。CLI help 已同步真实行为。
- Scope：Clock/Alarm Add 是第一个验收案例，但实现没有应用名或按钮白名单。修改限于 `visual_perception.py`、`run_visual_traversal.py`、两项专门测试和两份现状文档。
- Verification：本机离线 `python -B -m pytest -q tools/test_stateful_function_surfaces.py tools/test_vlm_grounding_startup.py -p no:cacheprovider --basetemp _scratch/pytest_prompt_mvp` 为 20 passed；capability-driven frontier 3 PASS、architecture boundaries PASS、targeted `py_compile` PASS，任务文件 `git diff --check` exit 0（仅既有 LF/CRLF warning）。另对保存的 Clock New Alarm 截图运行真实 Qwen qwen3.7-plus replay（未启动 VM）：`issues/20260714_clocks_sunday_form/prompt_mvp_vlm_replay/` 中 Add=`navigation, back=false`，Sunday/Ring Duration/Snooze Duration=`shallow`，Cancel=`navigation, back=true`。这证明该截图上的感知根因已修复，但仍不是 live 点击、落地或完整遍历认证。

### 2026-07-14 / working-tree — 当前 App 本地表单完成动作的上下文分类

- Behavior：SoM naming 与 direct grounding 共用一条本地表单完成边界；不按按钮名称放行。仅在完整视觉上下文明确证明动作局限于当前 App 内普通本地项目、可逆或进入可继续遍历状态，且没有账户/认证/权限/网络/通信/支付/安全/系统配置/破坏性/外部副作用时，Add/Create/Save/Apply/Done/Open 类动作才是 `navigation + risk=none`。Delete/Remove/Reset/Erase/Disconnect、敏感或不确定后果继续 dangerous/fail closed。未改 Engine、Explorer、schema、runner 或 completion。
- Evidence：修复前 js1 Clocks New Alarm 的 Add 被感知为 `category=dangerous`，capability 为 `risk_level=high`，navigation-only 调度因此无法完成 empty→create；只读证据位于 `/data/shenghonghui/desktop_accept/20260714_final_afe02594/evidence/clocks_new_alarm_filter/`。该产物是修复前证据，不是修复后 live 验收。
- Files：`gui_rewalk/src/core/visual_traversal/visual_perception.py`、`tools/test_stateful_function_surfaces.py`、`design/modules/visual_traversal.md` 与本文。
- Verification：本机离线 `test_stateful_function_surfaces.py` 为 17 passed，聚焦表单/普通 frontier/风险门为 3 passed，`test_capability_driven_frontier.py` 3 PASS，`test_architecture_boundaries.py` PASS，targeted `py_compile` PASS。因远端截图下载审批被当前工具额度拒绝，保存截图的真实 VLM 重放尚未执行；未启动 VM、容器或 emulator，也未执行修复后 live 点击。

### 2026-07-14 / working-tree — rejected inconsistent landing provisional cleanup

- Behavior: after a `transitioned_inconsistent` landing has been used for the existing source-recovery attempt, a node created by that attempt is removed through the existing fail-closed provisional cleanup transaction. Existing nodes and nodes with authoritative references are preserved; source recovery, one retry, and stop behavior are unchanged. This change intentionally does not handle `no_effect` provisional nodes.
- Files: `visual_engine.py`, `tools/test_visual_run_state_machine.py`, `design/modules/visual_traversal.md`, and this document.
- Verification (offline only, no VM/emulator/VLM): targeted `py_compile` PASS; `python -B tools/test_visual_run_state_machine.py` 16 PASS, including successful and failed source recovery cleanup; `python -B tools/test_graph_event_ledger.py` PASS; `python -B tools/test_resume_from_graph.py` ALL PASS; `python -B -m pytest -q tools/test_visual_router.py -p no:cacheprovider --basetemp _scratch/pytest_wrong_landing_router` 12 passed; targeted `git diff --check` exit 0. The pre-fix mobile artifact is diagnostic evidence only; this change has not had post-fix live validation.

### 2026-07-14 / working-tree — mobile 文本行首击 OCR 中心重绑

- Behavior：非图标、非 stateful 的 `navigation|nav` 文本行在可见与 below-fold 点击前，都要求当前帧 fresh 同名 bbox 或可信 live region 内唯一 OCR 命中，并点击 OCR 文字中心。历史 stitched y、模板中心与 VLM 大框中心不再作为文本行回退；bbox 越界、零/多命中与 OCR 失败直接拒点。compact-icon、scroll 终止、schema、completion 均未改。
- Evidence：修复前 deploy-asr Settings run 中，`Network & internet` 首击 retarget 到 `[540,1857]` 后 no-effect；`All apps` 的历史大框中心 `[540,1421]` 落到 App battery usage；below-fold `Storage` 的模板中心 `[540,1282]` 落到 System。回源/retry 生效，但这些只证明修复前首击偏移，产物位于 `/home/shenghonghui/mobile_accept/20260714_combined_settings_30x100_14085249`，不是修复后 live 验收。
- Files：`gui_rewalk/src/core/visual_traversal/visual_engine.py`、`tools/test_graph_quality_guards.py`、`tools/test_scroll_locate.py`、`design/modules/visual_traversal.md` 与本文。
- Verification（本机离线，非 emulator/VLM/live）：targeted live-rebind 5 PASS；`test_scroll_locate.py` PASS（含 OCR 不唯一禁止 VLM-center 旁路）；`test_visual_run_state_machine.py` 15 PASS；`test_visual_stitch.py`、`test_architecture_boundaries.py` 与 targeted `py_compile` 均 exit 0。完整 `test_graph_quality_guards.py` 的本任务前五项通过，后续旧 `test_data_controls_are_node_local` 因 Explorer 移除后仍期待 `Bookmarks` 而失败，与本补丁无关。

### 2026-07-14 / working-tree — exact-frame region-set 漂移恢复

- Behavior：常规 region-set 匹配失败后，`VisualStateRegistry.register()` 增加严格兜底：仅 exact pHash、selected/state 一致、原始功能 token overlap ≥ 0.78 且功能面不为 `different` 时合并新 rset；不放宽 pHash 距离，不改 `region_set_verdict`、schema、router 或 Engine。
- Evidence：修复前 js1 Clocks 的 World/Alarms 与 Settings Network 出现相同截图被新 region id 拆成重复节点并形成循环；证据位于 `/data/shenghonghui/explorerless_accept/20260714_afabcb23/evidence/{clocks_region_identity_loop,settings_region_identity_loop}`。这些是修复前只读证据，不是修复后 live 验收。
- Files：`gui_rewalk/src/core/visual_traversal/visual_state.py`、`tools/test_functional_surface_identity.py`、`design/modules/visual_traversal.md` 与本文。
- Verification（本机离线，非 VM/VLM/live）：`python -B tools/test_functional_surface_identity.py` PASS；`test_region_click_ledger.py` 与 `test_resume_from_graph.py` 均 ALL PASS；`pytest -q tools/test_visual_router.py` 12 passed；`test_visual_run_state_machine.py` 15 PASS；`test_architecture_boundaries.py` PASS；targeted `py_compile` 与 `git diff --check` exit 0。尚未执行修复后的 VM/VLM/live 遍历。

### 2026-07-14 / working-tree — interruption dismisser 结构化双门 fail-closed

- Behavior：`InterruptionDismisser` 的输出契约新增 `surface_is_temporary` 与 `target_is_close_control`；两者必须严格为 JSON `true` 且 action 为 click、目标编号有效，才返回可执行按钮。`force_first` 仍可询问，但同样经过该门；不新增状态机，也不使用控件名/应用名白名单。
- Evidence：修复前 js1 live 中，Clocks 正常空态 CTA `Add World Clock` 被 force-first dismisser 点击，Settings 软件更新通知正文被当成关闭目标；原始远端证据位于 `/data/shenghonghui/explorerless_accept/20260714_326ae6dd/attempt2/evidence/`。这些是修复前故障证据，不是修复后 live 验收。
- Files：`gui_rewalk/src/core/visual_traversal/visual_agents.py`、`tools/test_interruption_dismisser_guard.py`、`design/modules/visual_traversal.md` 与本文；未改 frontier、schema、router、resume、completion、region 或 stateful。
- Verification（本机离线，非 VM/VLM/live）：targeted `py_compile` exit 0；`test_interruption_dismisser_guard.py` 4 passed；`test_modal_candidate_policy.py + test_modal_surface_bbox_filter.py + test_popup_surface_guard.py` 4 passed；`test_visual_cache.py + test_architecture_boundaries.py` 10 passed。修复后尚未执行真实服务器/VM 点击验收。

### 2026-07-14 / working-tree — 移除 Explorer 主调度链，navigation 确定性调度

- Behavior：`visual_engine.py` 不再 import、构造或调用 `ExplorerAgent`；覆盖账本过滤后按稳定顺序选择首个候选，并以 `frontier_scheduler` 记录决定。只有 `category=navigation|nav` 可执行，非 navigation 元素以 `non_navigation_inventory` 退休；UI 类型和 stateful 字段不能把它们升级为强制点击。
- Safety：disabled/login/permission、安全状态控件风险门、实时重绑、动作事务与恢复门保持不变。安全 function-set 开关只有同时被感知为 navigation 且通过既有结构化安全契约时才可进入 frontier；`GUIWALK_STATEFUL_DISCOVER_ONLY=1` 仍可回退为只记录。
- Evidence：修改前 js1 Clocks 的 `Sunday` 证据保存在 `issues/20260714_clocks_sunday_form/`；它被感知为 `category=shallow`，新调度策略会留作 inventory，不进入重绑或点击。该目录是修改前 live 复现，不是修改后 live 验收。
- Files：`gui_rewalk/src/core/visual_traversal/visual_engine.py`、`tools/test_capability_driven_frontier.py`、`tools/test_explorer_done_override.py`、`tools/test_visual_run_state_machine.py`、`tools/test_resume_from_graph.py`、`tools/test_stateful_function_surfaces.py`、`design/modules/visual_traversal.md` 与本文；`visual_agents.py` 中的兼容类未删除。
- Verification（本机离线/纯内存，非 VM/VLM/live）：`python -m py_compile gui_rewalk/src/core/visual_traversal/visual_engine.py tools/test_capability_driven_frontier.py tools/test_explorer_done_override.py tools/test_stateful_function_surfaces.py tools/test_visual_run_state_machine.py tools/test_resume_from_graph.py` exit 0；`python -B tools/test_capability_driven_frontier.py` 3 PASS；`test_explorer_done_override.py` PASS；`test_stateful_function_surfaces.py` 16 tests passed；`test_visual_run_state_machine.py` 14 PASS；`test_resume_from_graph.py` ALL PASS；`test_architecture_boundaries.py` PASS。修改后桌面 VM、Android emulator 与真实 VLM/live 结果仍须由后续独立运行补充，不能由上述离线结果提前宣称认证。
### 2026-07-14 / working-tree — 紧凑图标实时重绑局部几何门

- Behavior：`icon/glyph/image` 的实时重绑始终以登记时原始 bbox 中心为锚点；局部模板必须同时达到既有高分阈值并落在原 bbox 邻域才可免文字 OCR。后备同名候选还必须与原 bbox 重叠且位于该邻域；若同名候选全部越界，直接 fail closed，不再进入外观匹配旁路。
- Evidence：修复前 Android Settings 的相邻工具栏图标被误绑并打开 overflow；保存证据只用于定位，修改后未操作 AVD/VM。聚焦离线测试覆盖正确局部模板和越界同名邻居拒绝。
- Files：`visual_engine.py`、`tools/test_graph_quality_guards.py`、`design/modules/visual_traversal.md` 与本文。Verification（本机离线，非 VM/VLM/live）：targeted `py_compile`、聚焦紧凑图标重绑、`test_visual_run_state_machine.py`（15 PASS）、`test_visual_stitch.py` 与 `test_architecture_boundaries.py` 均 PASS；完整 graph-quality 脚本随后被并行 frontier 改动下的既有 data-control 断言阻塞，未冒充全通过。

### 2026-07-13 / working-tree 鈥?鎭㈠鍚庢湭鐭ラ〉闈笉寰楃櫥璁版垚鏂拌捣鐐?
- Behavior锛歚visual_engine.py` 鍦ㄥ凡鏈夊浘鍚姩銆乺elaunch 鍜?Router hard reset 鍚庡彧閲囩敤 `graph` 涓?`_state_data` 涓悓鏃跺瓨鍦ㄧ殑宸茬櫥璁拌惤鐐癸紝骞跺鐢ㄥ叾 `path/replay_hints`锛涙湭鐭ラ〉闈㈣缃?`state_restore_failed`锛屼笉璋冪敤 `_register`銆傛垚鍔熼噰鐢ㄥ凡鏈夊浘鐨勫惎鍔ㄨ惤鐐瑰悗鎶婁笂涓€杞寔涔呭寲鐨?`stop_reason` 閲嶇疆涓?`incomplete`锛屽洜姝ゆ湰杞櫘閫氳矾鐢卞け璐ヤ笉浼氳鏃у€艰鍒わ紱鏈煡鍚姩澶辫触涓嶄細娓呮帀鏂板啓鍏ョ殑澶辫触鍘熷洜銆傜┖鍥鹃娆″惎鍔ㄥ強鏅€氱偣鍑诲悗鐨勬柊椤甸潰鐧昏淇濇寔鍘熻涓恒€?- Scope锛氬彧鏀?`visual_engine.py`銆乣tools/test_visual_run_state_machine.py`銆乣design/modules/visual_traversal.md` 涓庢湰鏂囷紱鏈敼 Router銆丷esume銆丷egion Registry銆丼tateGraph銆乧ompletion 鎴?schema锛屼繚鐣?`action_path_from_root`銆?- Verification锛堟湰鏈虹绾?绾唴瀛橈級锛歵argeted `py_compile` 閫€鍑虹爜 0锛涘悎骞舵粴鍔ㄧ敤渚嬪悗鐨?`test_visual_run_state_machine.py` 14 椤归€氳繃锛屽寘鍚棫 `state_restore_failed` 涓嶆薄鏌撴湰杞櫘閫?route 澶辫触鐨勫洖褰掞紱`test_resume_from_graph.py` ALL PASS锛沗test_visual_router.py` 12 passed锛沗test_region_click_ledger.py`銆乣test_graph_event_ledger.py` 涓?`test_traversal_completion_certificate.py` 鍧囬€€鍑虹爜 0銆傛湰娆℃湭杩炴帴 VM銆佹湭璋冪敤鐪熷疄 VLM锛屼笉鏋勬垚 live 璁よ瘉銆?
### 2026-07-13 / working-tree 鈥?褰撳墠椤垫粴鍔ㄥ璁＄粨鏉熷墠琛ユ煡涓€娆?
- Behavior锛氫粎鍦ㄥ綋鍓嶉〉娌℃湁鍊欓€夈€佷篃娌℃湁涓嬩竴鍙矾鐢辫妭鐐广€佸噯澶囩粨鏉熸椂璇诲彇宸叉湁 `scroll_ledger`銆傝嫢褰撳墠椤靛瓨鍦?`complete!=true` 涓?`observations=1` 鐨?scope锛屽鐢ㄧ幇鏈?register/revisit 璺緞琛ュ涓€娆★紱琛ュ鍚庝粛涓嶅畬鏁村垯鍐?`stop_reason=scroll_incomplete` 骞跺仠姝紝涓嶇户缁噸璇曘€?- Compatibility锛氫笉鏀?schema銆乧ompletion evaluator銆丷outer/resume/region identity銆乻tateful 绛栫暐銆佸钩鍙?runner銆佹闈?region scroll 鎴?Android popup/stitch锛涘凡瀹屾垚 shared region 鐨勬棦鏈夊鐢ㄨ涓轰笉鍙樸€?- Files锛歚gui_rewalk/src/core/visual_traversal/visual_engine.py`銆乣tools/test_visual_run_state_machine.py`銆乣design/modules/visual_traversal.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?绾唴瀛橈紝涓嶆槸 VM/VLM/live锛夛細`test_visual_run_state_machine.py` 14 椤?PASS锛沗test_scroll_waste.py`銆乣test_popup_surface_guard.py` 涓?`test_visual_stitch.py` 鍚堣 7 passed锛涙湭鍚姩鎴栬繛鎺?VM/guest锛屼笉鑳芥嵁姝ゅ０绉?live 璁よ瘉銆?
### 2026-07-13 / working-tree 鈥?鐘舵€佹帶浠剁殑搴旂敤鍐呭姛鑳藉叆鍙ｅ垎绫讳笌鍙楁帶鎺㈢储榛樿

- Behavior锛歋oM naming 涓?direct grounding 鍏辩敤鍚屼竴鍒嗙被绾︽潫锛氬彧鏈夎瑙変笂涓嬫枃鍏蜂綋璇佹槑褰撳墠鐩爣 App 鑷韩 UI 鍐呬細鍑虹幇銆侀殣钘忋€佸惎鐢ㄦ垨绂佺敤鍏朵粬浜や簰鎺т欢銆侀潰鏉挎垨瀵艰埅鍏ュ彛鏃讹紝鎵嶆爣璁?`effect_scope=function_set`锛涙櫘閫氬€笺€佷富棰?棰滆壊銆佹闈㈡垨 shell 鍥炬爣銆丏ock/浠诲姟鏍忔樉闅?浣嶇疆/灏哄/甯冨眬浠ュ強涓嶇‘瀹氬悗鏋滃潎淇濇寔 `data_only|unknown`銆傚紩鎿庝繚鐣欏畬鏁寸殑鍏ㄥ眬鍙褰曞洖閫€鍒嗘敮锛屼粎鎶婇粯璁ゅ€兼敼涓哄叧闂紝鍥犳鍚堟牸鍔熻兘鍏ュ彛寮€鍏抽粯璁ょ户缁繘鍏ョ幇鏈夊€欓€夆啋鐘舵€佽酱棰勭畻鈫掔嫭绔嬪叏灞忛闄╅棬鈫抪robe/restore 璺緞锛涙樉寮忚缃?`GUIWALK_STATEFUL_DISCOVER_ONLY=1` 浠嶅彲绱ф€ュ洖鍒板叏閮ㄥ彧璁板綍涓嶇偣鍑汇€傜嫭绔嬮闄╅棬瀵硅繛鎺ラ€氶亾銆佷細璇濄€佹暟鎹€佽处鎴?璁よ瘉/鏉冮檺/瀹夊叏杈圭晫銆佷笉鍙€嗗閮ㄦ晥鏋滃拰涓嶇‘瀹氬悗鏋?fail closed銆傛湭鏀?schema銆佽В鏋愬櫒銆佸畬鎴愯瘉涔︺€丆LI銆乺unner 鎴栫姸鎬佷簨鍔°€?- Files锛歚gui_rewalk/src/core/visual_traversal/visual_engine.py`銆乣gui_rewalk/src/core/visual_traversal/visual_perception.py`銆乣tools/test_stateful_function_surfaces.py`銆乣design/modules/visual_traversal.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?绾唴瀛橈級锛歚python -m pytest -q tools/test_stateful_function_surfaces.py --basetemp _scratch/pytest_stateful_classification_engine_default_final` 涓?16 passed锛沗python -m py_compile gui_rewalk/src/core/visual_traversal/visual_engine.py gui_rewalk/src/core/visual_traversal/visual_perception.py tools/test_stateful_function_surfaces.py` PASS锛涚浉瀵瑰綋鍓嶄富宸ヤ綔鍖洪€愭枃浠?`git diff --no-index --check` 鏃?whitespace error銆傚叾涓礋渚嬭鐩栦富棰樸€侀鑹层€佹闈㈠浘鏍囥€丏ock 涓庡竷灞€鍋忓ソ锛屾渚嬭鐩栫‘瀹炴樉绀哄綋鍓?App 鍐呮柊浜や簰鎺т欢鐨勭姸鎬佽〃闈紱Create/Add/Save/Open 浠嶄繚鐣欎负鏅€?frontier 鍔ㄤ綔銆?- Live/VLM evidence锛堜弗鏍煎垎灞傦級锛氫竴娆¤幏绉熺害鐨?Ubuntu Settings 鈫?Appearance guest 鎴浘涓?HTTP 200 鏈夋晥 PNG锛涗汉宸ュ畨鍏ㄥ垽瀹氫笁涓彲瑙佸瑙?甯冨眬寮€鍏抽兘搴斿彧璁板綍骞惰烦杩囷紝鍥犳 POST `/execute` 涓?0銆傛棫鎻愮ず瀵硅繖寮犲凡淇濆瓨鎴浘璋冪敤鐪熷疄 Qwen 鏃舵妸涓夎€呰鏍囦负 `function_set`锛涘眬閮ㄦ彁绀轰慨姝ｅ悗鍐嶆瀵瑰悓鍥捐皟鐢ㄧ湡瀹?Qwen锛屼笁鑰呭潎涓?`data_only + shallow`銆傝繖涓ゆ鏄€滀繚瀛樻埅鍥句笂鐨勭湡瀹?VLM 鎰熺煡鈥濓紝涓嶆槸 VM 鍔ㄤ綔鎴栧畬鏁?live 閬嶅巻璁よ瘉锛涚偣鍑汇€佺姸鎬佸彉鍖栥€佹仮澶嶃€丄ctionEdge 鍜?variant 鍧囨湭楠岃瘉銆?
### 2026-07-12 / working-tree 鈥?schema v3 resume 鎭㈠鎸佷箙 Variant facts

- Behavior锛氫弗鏍?`semantic_page_variant_v1` 鍥惧湪 resume 鏃剁户缁牎楠屾寔涔?`page_id`锛沗variant_id` 鏀圭敱鍥句腑鏉冨▉ `observed_facts` 閲嶆柊鍝堝笇楠岃瘉骞舵仮澶嶅埌鏂?registry锛屼笉鍐嶄粎浠庢渶缁?`elements` 蹇収閲嶇畻銆傝妭鐐归噸璁跨疮璁＄殑鍒悕/涓嬫姌鍙犲姛鑳藉彲鑳藉彧瀛樺湪浜?`observed_facts`锛屽洜姝ゆ棫绠楁硶浼氭妸鏈夋晥鍥捐鎶ヤ负 variant mismatch銆傛寔涔?facts 涓?variant hash 鐪熷啿绐佹椂浠嶅師瀛愭嫆缁濇暣娆?resume锛屼笉鑳介檷绾т负 fresh run銆?- Compatibility锛氫笉鏀?schema/CLI锛涘彧淇 schema v3 涓ユ牸韬唤鍥剧殑鎭㈠銆傜己澶辨潈濞?facts 鐨勬棫鍥句繚鐣欏師鏈?element-derived 鏍￠獙銆?- Files锛歚gui_rewalk/src/core/visual_traversal/visual_resume.py`銆乣tools/test_resume_from_graph.py`銆乣design/modules/visual_traversal.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?绾唴瀛橈級锛歚python -B tools/test_resume_from_graph.py` ALL PASS锛泃argeted `py_compile` PASS锛涘 `result_discover_only/20260712/setting/graph.json` 鍙鍔犺浇骞堕噸寤哄緱鍒?`REAL_GRAPH_RESUME True nodes 30 actions 37 frontier 30`銆備慨澶嶅墠鐨勭湡瀹?VM resume 宸插惎鍔ㄥ苟绋冲畾澶嶇幇 `184958865ad3` variant mismatch 鍚?fail-closed 閫€鍑猴紱淇鍚庣殑 VM/VLM 缁窇椤诲彟琛屽惎鍔紝涓嶈兘鎶婄绾块噸寤哄啓鎴?live 瀹屾垚銆?
### 2026-07-12 / working-tree 鈥?Android 涓存椂 popup/menu active-surface 闂ㄧ

- Behavior锛歡rounding 椤跺眰鏂板鍙€?`surface_kind=page|dialog|popup_menu`銆乣active_surface` 涓?`surface_scrollable`锛涘簲鐢ㄥ唴 dropdown銆乷verflow/context menu 鍜岄€夐」 popup 涓庡姛鑳藉璇濇涓€鏍峰仠鐢ㄨ儗鏅€俛ctive elements 鍐?`surface_kind/surface_bbox_xywh/surface_scrollable` sidecar锛岃嚦灏?80% bbox 蹇呴』浣嶄簬 active overlay銆?- Scroll/click锛歵ouch 涓婄煭涓旈潪 scrollable 鐨?popup/menu 涓嶅啀鎵ц 3鈥? 娆℃暣椤?swipe/闀垮浘鎷兼帴锛岃€屾槸鍐?`static/static/steps=0/top_restored=true` scroll evidence銆俹verlay-bound 鎺т欢鐐瑰嚮鍓嶄富鍔?capture 鏈€鏂?observation 骞跺己鍒堕噸鏂?grounding锛岃姹傚悓绫绘诞灞備粛娲诲姩銆乻urface bbox 涓庤褰曡嚦灏?60% 灏忔閲嶅彔銆乴ive 鍊欓€変粛鍦ㄨ bbox 鍐咃紱娴眰娑堝け鍚庨〉闈笂鐨勫悓鍚嶆帓搴忔爣绛炬垨鑳屾櫙鍒楄〃琛屼笉鑳借 OCR/template 蹇嵎璺緞鐐瑰嚮銆?- Compatibility锛氫笉鎻愬崌 `graph_schema_version`锛涗笁涓?surface 瀛楁鏄彲閫夊厓绱?sidecar锛屾棫鍥惧彲 load銆傜己灏戠粦瀹氱殑鏃у厓绱犱笉浼氬嚟鍘嗗彶鍑犱綍鑷姩鍗囩骇锛岄渶 fresh/revisit grounding 鎵嶈幏寰楁诞灞傞棬绂侊紱portable edge/capability 浠嶄笉淇濆瓨鍧愭爣銆?- Files锛歚visual_perception.py`銆乣visual_engine.py`銆乣tools/test_popup_surface_guard.py`銆乣design/modules/visual_traversal.md`銆乣design/modules/android_support.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?鍚堟垚锛屼笉鏄?emulator/VLM live锛夛細`python -B tools/test_popup_surface_guard.py` PASS锛坰tructured popup 鎻愬崌涓?active overlay銆佽儗鏅?bbox 杩囨护銆? swipe/static ledger銆佸悓娴眰 live rebind銆佹诞灞傛秷澶?鎹綅鎷掔偣锛夛紱`test_modal_surface_bbox_filter.py`銆乣test_graph_quality_guards.py`銆乣test_scroll_waste.py`銆乣test_visual_cache.py`銆乣test_modal_candidate_policy.py`銆乣test_visual_run_state_machine.py`銆乣test_architecture_boundaries.py` 鍧?PASS锛泃argeted `py_compile` PASS銆傛湭鎿嶄綔 emulator锛屽皻鏈噸璺?Notifications `Most frequent` live landing銆?
### 2026-07-12 / working-tree 鈥?Android 闀垮浘绯荤粺鏍忓幓閲嶄笌 tiled provenance 杩囨护

- Behavior锛欰ndroid/touch stitch 涓嶅啀鍙潬棣?灏惧抚鍍忕礌鐩哥瓑鎺ㄦ柇 sticky 杈圭晫銆侲ngine 鎶婁笌鎰熺煡灞備竴鑷寸殑鍥哄畾 status/navigation 鍍忕礌甯︿紶鍏?`stitch_frames()` 浣滀负鏈€灏?sticky 楂樺害锛涙帹鏂粛鍙粠绯荤粺甯﹀唴渚х户缁墿灞曞埌鐪熷疄 app toolbar銆傚姩鎬佹椂閽?淇″彿/鐢垫睜/gesture pill 鍥犳涓嶄細璁?sticky 妫€娴嬪綊闆讹紝composite 浠呬繚鐣欓甯ч《閮ㄧ郴缁熷甫鍜屾湯甯у簳閮ㄧ郴缁熷甫銆?- Tiled grounding锛歚StitchResult` 鍗曠嫭淇濆瓨 `system_top_h/system_bot_h`锛屼笉鎶?app sticky chrome 璇綋绯荤粺 UI銆俙_perceive_tiled()` 鍦?chunk-local 鍧愭爣鎶洖 composite 鍚庯紝浣跨敤 `y_map -> source in-frame y` 浜屾鎷掔粷绯荤粺甯﹀厓绱狅紱鍥犳鍗充娇娈嬬暀绯荤粺鏍忓嚭鐜板湪 middle tile 鍐呴儴 seam锛屼篃涓嶄細杩涘叆鑺傜偣鍏冪礌/鑳藉姏/frontier銆傜煭 composite 鍚屾牱鍋?provenance 杩囨护銆?- Compatibility锛歚stitch_frames()` 鐨勬柊鍙傛暟榛樿涓?0锛岀幇鏈夐€氱敤/妗岄潰璋冪敤淇濇寔鍍忕礌鎺ㄦ柇琛屼负锛涙柊瀛楁鍙瓨鍦ㄨ繍琛屾椂 `StitchResult`锛屼笉鏀?`graph.json` schema銆?- Files锛歚visual_stitch.py`銆乣visual_engine.py`銆乣tools/test_visual_stitch.py`銆乣tools/test_stitch_node_integration.py`銆乣design/modules/visual_traversal.md`銆乣design/modules/android_support.md`銆乣design/modules/scroll_scheme.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?鍚堟垚锛屼笉鏄?emulator/VLM live锛夛細`python -B tools/test_visual_stitch.py` PASS锛堟棫鎷兼帴銆乼iny-overlap offset銆? 甯у姩鎬?Android 绯荤粺鏍忓彧淇濈暀涓€浠姐€乵iddle tile provenance 杩囨护涓?app 鍏冪礌淇濈暀锛夛紱`python -B tools/test_stitch_node_integration.py` PASS锛堢煭 composite 鐨?arrival+single composite naming锛屼互鍙?5376px tall composite 鐨?2-tile merge/鍧愭爣鍥炴槧锛夛紱`python -B tools/test_system_ui_band.py` ALL PASS锛沗python -B tools/test_architecture_boundaries.py` PASS锛涚浉鍏?`py_compile` PASS銆傛湰鏉℃湭鍚姩 Android emulator锛屾湭璋冪敤鐪熷疄 VLM锛屼笉瀹ｇО live Settings 宸茶璇併€?
### 2026-07-12 / working-tree 鈥?navigation 鍚屾瀯缁勮瘉涔︽敹绱?
- Behavior锛氬畬鎴愯瘉涔︿粛鍏佽鐧藉悕鍗?abnormal/no-effect 閫€浼戝彂鐢熻缁撴灉鐨勫叿浣撴帶浠讹紝浣?navigation group 鐨勫弬鏁板寲 alias 鐜板湪鍙帴鍙楀叿鏈夌湡瀹?`verified_attempt` 鐨勪唬琛ㄣ€傚紓甯搞€佹棤鏁堟灉銆乻elected/back 鎴?inventory 浠ｈ〃鍧囦笉鑳戒负鏈墽琛岀殑鍚岀粍瀵艰埅琛岃儗涔︼紱娣峰悎 category 鐨勮鍒嗙粍涔熷湪 alias 渚у啀娆?fail-closed 妫€鏌ャ€?- Files锛歚gui_rewalk/src/core/graph/traversal_completion.py`銆乣tools/test_traversal_completion_certificate.py`銆乣design/modules/state_graph.md`銆乣design/modules/visual_traversal.md` 涓庢湰鏂囥€?- Verification锛堟湰鏈虹绾?绾唴瀛橈級锛歚python -B tools/test_traversal_completion_certificate.py` 閫氳繃锛岃鐩?verified 浠ｈ〃姝ｅ父鍙傛暟鍖栵紝浠ュ強 `external_app`/`no_effect` 浠ｈ〃鍙兘閫€浼戣嚜韬€佸鑸?alias 淇濇寔 unresolved銆傛湭鍚姩妗岄潰 VM銆丄ndroid emulator 鎴栫湡瀹?VLM锛屼笉鏄?Settings live 璁よ瘉銆?
### 2026-07-12 / working-tree 鈥?鐘舵€佹帶浠舵棤鏁堟灉/闂€€鎭㈠鐨?provisional node 鍥炴敹

- Behavior锛歱ost-click/relaunch 浠嶅厛鐧昏鐪熷疄钀藉湴瑙傚療锛涗粎褰撶粨鏋勫寲 before/after 閮芥槸宸茬煡 off/on 涓旂浉鍚屻€乻emantic `page_id` 鐩稿悓銆佸畬鏁?`observed_facts.states` 涓?selected modes 鐩稿悓銆佽妭鐐逛负鍏ㄦ柊涓斾笉瀛樺湪 committed topology銆乿erified attempt 鎴?abnormal source 鏃讹紝鎵嶆妸 attempt target 褰掍竴鍥炴簮骞跺垹闄?provisional execution node銆傞敊椤点€佹湭鐭ュ€笺€佺湡瀹炰笉涓€鑷磋惤鍦颁笌 restore failure 鍧囦繚鐣欏苟 fail-closed銆?- Cleanup surface锛歚StateGraph` 娓?Page/Variant銆乧apability source銆乻croll membership 涓庢湭鎻愪氦寮曠敤锛沗VisualStateRegistry` 娓呮鍙嶅悜 identity 绱㈠紩锛沗RegionRegistry` 娓?`seen_on`锛岄伩鍏?alias 璇Е shared 闃堝€硷紱Engine 娓?`_state_data`銆丅FS銆佸け璐?闅旂绱㈠紩锛沗ArtifactWriter` 浠?`node_index.json` 绉婚櫎璇ヨ妭鐐逛絾淇濈暀璇婃柇鏂囦欢銆?- Live evidence锛氭闈?GNOME Settings 棣栬疆鐪熷疄杩愯寰楀埌 4 nodes銆? 鏉?verified topology edge銆? 娆?attempts锛屾渶缁?`state_restore_failed`锛宑ompletion 鏈€氳繃 frontier/scroll/control/reachability锛汢luetooth 鐨?no-effect jitter 涓?crash-relaunch recovery 鍦ㄩ杞浘涓婂潎閫氳繃鏂扮瓑浠疯皳璇嶃€傝缁撴灉鏄け璐ヨ瘖鏂紝涓嶆槸瀹屾垚璁よ瘉锛涗慨澶嶅悗鐨?VM/VLM 鍏ㄥ浘澶嶈窇灏氭湭鍦ㄦ湰鏉¤褰曟椂缁撴潫銆?- Files锛歚visual_engine.py`銆乣visual_state.py`銆乣region_registry.py`銆乣artifacts.py`銆乣state_graph.py`銆佸搴?state-machine/graph/identity/region/artifact tests 涓庢湰妯″潡鏂囨。銆?- Verification锛堟湰鏈虹绾?绾唴瀛橈紝涓嶆槸 VM/VLM锛夛細`python -B tools/test_graph_event_ledger.py`銆乣test_visual_run_state_machine.py`銆乣test_functional_surface_identity.py`銆乣test_region_click_ledger.py`銆乣test_architecture_boundaries.py`銆乣test_traversal_completion_certificate.py`銆乣test_scroll_waste.py`銆乣test_visual_stitch.py` 鍧?PASS锛泃argeted `py_compile` 涓?`git diff --check` 閫氳繃銆傜湡瀹炴闈?Android completion certificate 浠嶅緟鍚庣画 live 缁撴灉銆?
### 2026-07-12 / working-tree 鈥?閬嶅巻瀹屾垚璇佷功銆佹粴鍔ㄨ瘉鎹笌 Settings 鍙岀 runner

- Completion evidence锛歴chema v3 鏂板 `scroll_ledger[]`锛岀Щ鍔ㄦ暣椤靛拰妗岄潰绋冲畾 region 鎸佷箙璁板綍 static/scrollable銆乼ermination銆乥ottom銆乼op restore 涓庢鏁帮紱resume/revisit 浼氳ˉ瀹＄己澶?澶辫触 scope锛屽畬鏁?shared region 鍙鐢ㄣ€傛柊澧炵函鍑芥暟 `evaluate_traversal_completion()`锛屼互 8 椤规鏌ヤ粠鍘熷璐︽湰鐢熸垚 `certified|incomplete`锛岃瘉涔﹂檺瀹氫负褰撳墠 fixture/鎰熺煡/瀹夊叏绛栫暐涓嬪凡鍙戠幇鍙揪鍔熻兘闈紝涓嶅绉颁笉鍙鍔熻兘涓嶅瓨鍦ㄣ€?- Completion consumers锛歵raversal CLI 姣忚疆鍘熷瓙鍐?`completion.json`锛宍--require_complete` 涓嶅啀鎺ュ彈鍗曠嫭鐨?`frontier_empty`锛汫raphQuality 鎶ュ憡宓屽叆鍚屼竴璇佷功锛宍tools/live_status.py` 鍙湁璇佷功閫氳繃鎵嶆樉绀哄畬鎴愩€傛闈?绉诲姩 Settings runner 榛樿棰勭畻鎻愰珮鍒?300 states / 1200 actions锛岀Щ鍔ㄥ崟 app timeout 涓?14400 绉掞紝骞舵纭紶鎾?boot/timeout/璁よ瘉澶辫触銆?- Action audit锛欳LICK 鍦ㄨ皟鐢?`env.step()` 鍓嶅垱寤?attempt锛涘悗绔紓甯告洿鏂颁负 `execution_error`锛屼笉浼氫涪澶卞彲鑳藉凡鎶曢€掔殑鐪熷疄鎿嶄綔銆傞噸缁戝け璐ヤ袱娆′細鍐欒妭鐐瑰眬閮?abnormal outcome 浣嗕笉杩涘叆鍏变韩鎴愬姛瑕嗙洊锛涜瘉涔﹀彧鎺ュ彈 disabled/permission/risk/no-effect/external-app/crash 绛夋槑纭粓鎬侊紝target-rebind/action-execution/uncertain/verification-failed 浠嶉樆姝㈣璇併€傜姸鎬佹帶浠跺彧鏈夌粨鏋勫寲 off鈫攐n 鍙樺寲鎵嶆墦寮€ mutation锛岄敊椤垫垨瑙嗚鍙樺寲涓嶅啀璇姤 mutation銆?- Portable capability锛氭枃鏈鍐?TYPE+runtime text slot锛屼笅鎷?combobox 鍐?CLICK+runtime option锛屾櫘閫氭寜閽啓璇箟 CLICK锛涙暟鍊?slider/range 鍙彁渚?`鏈€灏?涓€鍗?鏈€澶 涓変釜鍙噺鍖栭敋鐐瑰苟瀹炴椂鎹㈢畻钀界偣锛岃嚜鐢辨嫋鏀句粛鏍囪 unsupported锛屼换浣曠被鍨嬮兘涓嶅啓鍘嗗彶鍧愭爣銆?- Security锛欰ndroid 绗笁鏂?loader 璋冪敤鏈熼棿涓存椂鎶?absl 鏃ュ織鎻愰珮鍒?WARNING 骞跺湪 `finally` 鎭㈠锛岄槻姝㈠叾 INFO 鏃ュ織杈撳嚭鏁翠釜杩涚▼鐜锛涘巻鍙叉棩蹇楄嫢鏇炬毚闇插嚟鎹粛闇€杞崲鍑嵁骞堕檺鍒?娓呯悊鏃ュ織銆?- Files锛歚state_graph.py`銆乣traversal_completion.py`銆乣visual_engine.py`銆乣capability_discovery.py`銆乣android_gui_gen_env.py`銆乣run_visual_traversal.py`銆乣graph_quality_agent.py`銆乣live_status.py`銆佷袱涓?Settings runner銆佸搴旂绾挎祴璇曞拰妯″潡鏂囨。銆?- Verification锛氭湰鏈虹绾块€氳繃 `test_traversal_completion_certificate.py`銆乣test_traversal_failure_ledger.py`銆乣test_graph_event_ledger.py`銆乣test_online_capability_discovery.py`銆乣test_stateful_function_surfaces.py`銆乣test_resume_from_graph.py`銆乣test_functional_surface_identity.py`銆乣test_graph_quality_agent.py`銆乣test_live_status_summary.py`銆乣test_capability_driven_frontier.py`銆乣test_explorer_done_override.py`銆乣test_android_env_log_guard.py` 涓?`test_architecture_boundaries.py`锛涚浉鍏?`py_compile`銆丆LI `--help`銆丳owerShell parser 鍜?`bash -n` 閫氳繃銆傛鏉″厛璁板綍绂荤嚎楠岃瘉锛涙闈?VMware 涓庣嫭绔?Android emulator 鐨?live 缁撴灉椤诲湪杩愯缁撴潫鍚庡彟琛ワ紝涓嶈兘鎻愬墠瀹ｇО璁よ瘉閫氳繃銆?
### 2026-07-12 / working-tree 鈥?鑱旈偊鐩綍鍚堝苟 Page@Variant 鑳藉姏 sidecar

- Behavior锛歚FederatedCapabilityCatalog` 涓嶅啀鎶婂悓涓€ app 鍐呴噸澶嶇殑 page-scoped `capability_id` 涓€寰嬭涓洪敊璇紱浠呭綋绋冲畾 `page_id` 涓?capability `semantic_key` 鍚屾椂涓€鑷存椂锛屽皢 empty/has-data 绛?Page@Variant sidecar 纭畾鎬у悎骞朵负涓€涓?atom銆倂ariant銆乻ource element銆乤ction edge銆乼arget 涓?source path evidence 鍋氭帓搴忓幓閲嶅苟闆嗭紝verified evidence 姘镐笉琚?discovered 璁板綍闄嶇骇銆倂ariant-specific `requires_by_variant` 淇濈暀鍚勮嚜 gate锛涘彧鏈夊叏閮?variant requirement 瀹屽叏鐩稿悓鎵嶄繚鐣欏吋瀹瑰叏灞€ `requires`锛宐locked+available 骞跺瓨鏃剁疆绌恒€傝法 page銆乻emantic collision 鎴栫己灏戠ǔ瀹?page identity 鐨勯噸澶嶈褰曠户缁?fail-closed銆?- Contract锛歚FederatedCapabilityAtom` 鏂板 `page_id/semantic_key/source_paths/evidence_variants/entry_variants/source_elements/action_edge_ids/target_pages/target_variants/available_when`锛屼繚鐣欏崟涓?representative `node_id/target_node/source_path` 渚涚幇鏈?M13 ref 鍏煎锛涚姸鎬?鍔ㄤ綔璇佹嵁鏇翠赴瀵岀殑 verified variant 琚‘瀹氭€ч€変负 representative锛屼笉鍚堝苟浠讳綍 app 鐘舵€佸浘銆?- Files锛歚gui_rewalk/src/core/scenario/federated_capability_catalog.py`銆乣tools/test_federated_capability_catalog.py`銆乣design/modules/crossapp_composition_design.md` 涓庢湰鏂囥€?- Verification锛氭湰鏈虹绾胯繍琛?`python -m pytest -q tools/test_federated_capability_catalog.py tools/test_visual_collection_executor.py --basetemp _scratch/pytest_catalog_variant_executor` 涓?22 passed锛沗python -B tools/test_run_visual_collection_cli.py` 涓?`python -B tools/test_capability_atom_contract.py` 閫氳繃锛涚浉鍏?`py_compile` 閫氳繃銆傛湭鍚姩 VM/emulator锛屾湭璋冪敤鐪熷疄 VLM銆?
### 2026-07-11 / working-tree 鈥?鑳藉姏鍙戠幇椹卞姩閬嶅巻銆丳age/Variant 涓?schema v3

- Page/Variant identity锛歚state_id` 淇濇寔 Router 鐨勫叿浣撴墽琛岃妭鐐癸紱鏂板绋冲畾 `page_id` 鑱氬悎鍚屼竴璇箟椤甸潰锛宍variant_id` 缂栫爜鎴浘鍙瀵熺殑鍔熻兘鏉′欢銆侭luetooth off/on 涓?Alarm empty/has_alarm 浠嶆媶鎵ц鑺傜偣浣嗗綊鍏ュ悓涓€ page锛涗笉鍚岄椆閽熸椂闂寸瓑瀹炰緥鏁版嵁涓嶆媶璇︽儏 variant銆?- Online capability锛氳妭鐐圭櫥璁版椂鐢?grounded elements 鐩存帴鐢熸垚 portable `discovered` 鑳藉姏锛屾寜 `page_id+semantic_key` 鍚堝苟骞惰褰?`available_when`銆傚彧鏈夌湡瀹炲姩浣溿€佹槑纭?target銆乧ommitted 涓?`landing_verified=True` 鎵嶈ˉ action edge/effect/target provenance 骞舵檵鍗?`verified`銆傛埅鍥?geometry 鍙暀 sidecar锛宺ecipe 浠呬繚鐣欒涔?selector 鍜岃繍琛屾椂鍙傛暟銆?- Graph schema锛歚graph.json` 鍗囦负 `graph_schema_version=3`锛屾柊澧?`pages/capabilities/action_edges[]`锛涙瘡鏉?ActionEdge 鑷甫 append-only `attempts[]`锛屼笉鍚岃涔夊姩浣滀笉鍐嶈鍚屼竴 source鈫抰arget 鐨?DiGraph 灞炴€ц鐩栥€傞《灞?`transition_events` 涓嶅啀鎸佷箙鍖栵紝鍙繚鐣欏彧璇诲唴瀛樺吋瀹硅鍥撅紱v1/v2 鍙縼绉伙紝淇濆瓨鍚庡啓 v3銆俙routing_graph` 鍙惈鑷冲皯涓€娆?verified landing 鐨勮竟銆?- Capability-driven frontier锛氶亶鍘?CLI 绉婚櫎 `--no_discovery_prerequisites` 涓庨粯璁?resolver锛汣reate/Add/Save/Open 璧版櫘閫?coverage frontier锛屼腑闂?Page/Variant 鑷劧鐧昏銆侲xplorer `done` 鍙槸鎺掑簭鎰忚锛屼笉鑳芥妸璐︽湰涓殑鏈墽琛屽€欓€夋爣涓?visited銆侻13 鐨?`PrerequisiteRuntime/VisualPrerequisiteAgent` 淇濈暀涓旂户缁彧娓呯悊鍏舵嫢鏈夌殑 setup 璧勬簮銆?- Offline synthesis/quality锛歚run_capability_synth.py` 闄嶄负鍙€夊綊涓€/鏃у浘琛ュ綍锛屽崟鎴浘榛樿 discovered锛汫raphQuality 鏂板 Page/Variant銆丄ctionEdge attempts銆乿erified routing銆乿erified capability provenance 涓?v3 閲嶅椤跺眰 ledger 妫€鏌ャ€?- Verification锛氭湰鏈虹绾胯繍琛?`test_graph_event_ledger.py`銆乣test_online_capability_discovery.py`銆乣test_functional_surface_identity.py`銆乣test_capability_driven_frontier.py`銆乣test_discovery_seed_runtime.py`銆乣test_visual_run_state_machine.py`銆乣test_resume_from_graph.py`銆乣test_graph_quality_agent.py`銆乣test_architecture_boundaries.py`銆乣test_capability_atom_contract.py`锛屽潎閫氳繃锛沗pytest tools/test_visual_router.py` 涓?7 passed锛沗test_federated_capability_catalog.py + test_visual_collection_executor.py` 涓?18 passed锛沗test_prerequisite_runtime.py` 涓?11 tests锛宍test_visual_prerequisite_agent.py` 涓?12 tests锛泃argeted `compileall` 閫氳繃銆傛湭鍚姩 VM/emulator锛屾湭璋冪敤鐪熷疄 VLM锛孋lock/Alarm empty鈫抎etail 灏氭湭 live 楠屾敹銆?
### 2026-07-11 / working-tree 鈥?鍔熻兘琛ㄩ潰鍥俱€佸墠缃繍琛屾椂銆佸浘璐ㄦ涓?M13 閲囬泦涓婚摼

- Functional identity锛歚VisualStateRegistry` 涓嶅啀鎶婄浉鍚?region-set 鏃犳潯浠跺悎骞讹紱鐩稿悓甯冨眬涓嬫瘮杈?selected navigation token銆侀〉闈㈠悕杈呭姪璇佹嵁涓庡彲鐢ㄥ嚱鏁伴泦銆傝摑鐗欏紑/鍏炽€佺┖/宸叉湁闂归挓銆佸悓鍒楄〃閫変腑涓嶅悓搴旂敤绛夊姛鑳介潰鍙垎瑁傦紝绾暟鎹€间粛鍚堝苟銆傛ā鎬佸厓绱犳敼涓烘暣妗?active-surface containment锛泃ab-bar 鐩爣鍙湪鍚屼竴鏄惧紡 region 鍐呭惛闄勩€?- Availability/safety锛歚VisualElement` 鏂板 `enabled/requires_permission/blocked_reason`銆傛槑纭?disabled銆佸簲鐢ㄧ櫥褰曞拰鏈煡鎺堟潈 gate fail-closed 杩涘叆寮傚父璐︽湰锛涗粎缁撴瀯鍖栫‘璁ょ殑鏃犲瘑鐮佺郴缁?Settings Unlock 鍙嚜鍔ㄦ帰绱€俙external_app` 涓?`app_crash` 鍧囨垚涓轰竴娆℃€х粓鎬侊紝涓嶆薄鏌撶洰鏍?app 鍥捐竟鎴栨垚鍔熻鐩栥€?- Event schema锛歚graph.json` 鍗囦负 `graph_schema_version=2`锛屾柊澧?append-only `transition_events`锛汥iGraph edge 鐢?`action_indices/transition_count` 鍥炴寚鍚屼竴鑺傜偣瀵圭殑鎵€鏈夋垚鍔熶簨浠讹紝骞跺彲淇濆瓨 `action_steps/action_sequence/transition_kind`銆傛棫鍥惧彲 load锛屼絾鍙噸寤哄垢瀛樻垚鍔熶簨浠躲€?- Prerequisites锛氭柊澧?`PrerequisiteRuntime` 涓?`VisualPrerequisiteAgent`锛岀粺涓€ resource/state/authorization/login锛涗紭鍏堢粦瀹氬凡鏈夎祫婧愶紝鍚﹀垯閫夋嫨 GUI 鎴愭湰鏈€浣庣殑鍙 recipe銆傝祫婧?recipe 鏃?cleanup 鏃舵嫆缁濆垱寤猴紱鍙窡韪苟鍙嶅悜骞傜瓑娓呯悊鏈疆鍒涘缓璧勬簮锛涘簲鐢ㄧ櫥褰曞強浠讳綍鐧诲綍璇箟 setup 閮借姹傜敤鎴枫€侲ngine 鏂板 seed resolver 娉ㄥ叆鐐逛笌 setup/cleanup 浜嬩欢锛涚嫭绔嬮亶鍘嗛粯璁ゆ瀯閫?resolver锛坄--no_discovery_prerequisites` 鍙叧闂級锛孧13 鍏ュ彛鍏变韩鍚屼竴涓?ownership runtime銆俧resh/resume/off-app 榛樿浣跨敤 data-preserving restart锛岄伩鍏嶅垹闄ゅ凡鏈夋垨鍒氬垱寤虹殑 fixture锛涘巻鍙叉竻鐘舵€佽涓烘敼涓烘樉寮?`--clean_start`銆?- Capability contract锛歝apability atom 鏂板 app/绋冲畾 id/entry銆乮nputs銆乺equires/effects/success predicate/observables銆乪xecution/setup/recovery/cleanup recipes銆乤vailability/risk/action cost锛涙棫 artifact 淇濇寔鍙銆侷nstruction refs 甯?app/鍥?鎵ц濂戠害涓庝緷璧栥€?- Quality锛氭柊澧炲彧璇?`GraphQualityAgent` 鍜?`gui_rewalk/run_graph_quality.py`銆傝鍒欒鐩栨埅鍥?椤甸潰/鍑芥暟瑕嗙洊鐘舵€併€侀噸澶?杩囧悎骞躲€佽竟璇箟/钀藉湴/妯℃€?retarget銆佹潈闄愪笌 action ledger锛屽苟鏍稿 control 鐨?visited flag 鏄惁鏈?edge/event/terminal outcome 瀵瑰簲锛涙棫鍥惧彧鏈夊瓧绗︿覆鍚彂寮忕殑 permission/crash 鍙粰 possible/WARN锛岄伩鍏嶄吉 ERROR銆傚彲閫?VLM 鍙湪瓒冲缃俊搴︽椂琛ヨ涔夊垽鏂紝鎶ュ憡涓嶈鐩栨簮鍥俱€傛柊澧?`graph_quality_annotations.py` 涓?`--annotated-dir`锛欵RROR/WARN 鐢熸垚鑺傜偣鎴?source/target 骞舵帓璇佹嵁 PNG锛宮anifest 閫?finding 璁板綍鐢熸垚/璺宠繃锛屼笖楠岃瘉婧?graph/鎴浘 hash 涓嶅彉銆?- Cross-app/M13锛氭柊澧?`FederatedCapabilityCatalog`锛屽彧鑱斿悎 app-qualified atom锛屼笉鍚堝苟鐘舵€佸浘锛涙柊澧?`VisualCollectionExecutor`銆乣EngineVisualAdapter` 涓?`gui_rewalk/run_visual_collection.py`銆傛墽琛屽櫒鍦ㄦ瘡涓?app 鍥惧唴鎸?GUI action steps 姹傛渶鐭矾锛屾樉寮忚褰?app switch锛屾敮鎸佸亸鑸噸瑙勫垝銆佸墠缃鐞嗐€侀€?ref/鏈€缁?VLM gate 鍜?cleanup銆俙execution_recipe` 浠?atom 璐┛ ref/catalog锛屽苟鍦ㄥ疄鏃跺抚閫愭鍔ㄦ€?grounding锛涗腑閫斿け璐ヤ繚鐣欏凡鎵ц primitive 鐨勬湭鎻愪氦鍔ㄤ綔璇佹嵁銆傚姩浣滃寘鎷畨鍏ㄨ涔?DRAG锛氬彧鎺ュ彈褰撳墠甯у彲瑙佺殑 source/target selector锛屽巻鍙?geometry 琚墺绂汇€俽ef 鏄庣ず login 鎴?name/recipe 甯︾櫥褰曡涔夋椂锛屾墽琛屽櫒鍦ㄤ换浣?GUI 鍔ㄤ綔鍓嶈繑鍥?`needs_user`銆俙CollectionWriter.write_visual_episode()` 杈撳嚭 `m13.visual_collection.v1` 鎴浘杞ㄨ抗銆?- Verification锛?026-07-11 鏈満渚濇杩愯 `test_graph_event_ledger.py`銆乣test_functional_surface_identity.py`銆乣test_visual_permission_gating.py`銆乣test_modal_surface_bbox_filter.py`銆乣test_tabbar_targeting_guard.py`銆乣test_external_app_terminal.py`銆乣test_discovery_seed_runtime.py`銆乣test_app_lifecycle_preserve.py`銆乣test_capability_atom_contract.py`銆乣test_prerequisite_runtime.py`锛?1 tests锛夈€乣test_visual_prerequisite_agent.py`锛?2 tests锛夈€乣test_graph_quality_agent.py`銆乣test_run_graph_quality_cli.py`銆乣test_graph_quality_annotations.py`銆乣test_live_visual_collection.py`銆乣test_visual_collection_writer.py`銆乣test_run_visual_collection_cli.py`锛屽潎浠ヨ剼鏈绾块€氳繃锛沗test_federated_capability_catalog.py + test_visual_collection_executor.py` 鐢?pytest 鍚堝苟鎵规涓?18 passed銆傛牳蹇?architecture/run-state/router/resume/graph guards/VLM timeout銆佷笁涓?CLI `--help` 涓?active `compileall` 浜﹂€氳繃銆傛湭鍚姩 VM/emulator锛屾湭璋冪敤鐪熷疄 VLM锛屾湭鍋氶鎵瑰簲鐢?live rollout銆?
### 2026-07-10 / local deployment entry

- Entry point: 鏂板 `run_local_visual.ps1`锛岄€氳繃浠撳簱鐩稿璺緞瀹氫綅 OSWorld銆丱mniParser 鏉冮噸鍜?VMware `.vmx`锛涗笉鍐嶅寘鍚湰鏈虹粷瀵硅矾寰勬垨鍐呭祵 API key銆?- Distribution: 鏂板 `DEPLOY_LOCAL.md`锛屾槑纭唬鐮佺敱 Git 鍒嗗彂锛孷M 涓庢ā鍨嬫潈閲嶇敱鐙珛鍒跺搧鍒嗗彂锛涗笉鎶婂疄楠屼骇鐗┿€佸嚟鎹垨澶т簩杩涘埗鏂囦欢鍔犲叆浠撳簱銆?- Verification: PowerShell AST 璇硶妫€鏌ャ€乣run_visual_traversal.py --help`銆乤rchitecture boundaries銆乿isual run-state銆乿isual router銆乺esume銆乬raph quality guards銆乂LM timeout銆乣compileall` 鍜?`git diff --check` 鍧囬€氳繃锛涙湭杩涜 VM/VLM 杩愯鏃堕獙璇併€?
### 2026-07-10 / working-tree 鈥?鐐瑰嚮瀵艰嚧搴旂敤闂€€鏃惰褰曞苟璺宠繃

- Trigger: Settings 瀹炴満缁窇涓?`Sound` 缁忔瘡娆″疄鏃堕噸缁戝悗浠嶄娇鐩爣绐楀彛娑堝け锛孎ocus Guard 閲嶅惎鍚庡€欓€夋湭閫€浼戯紝褰㈡垚鍙嶅 grounding/鐐瑰嚮/閲嶅惎寰幆銆傜敤鎴烽殢鍚庢墜鍔ㄥ叧闂?VM锛涗慨澶嶅悗鏈啀娆″惎鍔?VM銆?- Classification: 澶嶇敤鐜版湁 app-focus VLM 杩斿洖鏂板 `kind`锛屽尯鍒?`target_missing/crash_dialog`銆乣external_app/system_overlay/unknown`锛涘吋瀹规ā鍨嬫紡瀛楁鏃朵粠 reason 褰掍竴銆傚畬鏁?`(on_app, kind, reason)` 杩涘叆鍚屽抚 cache锛屼笉澧炲姞 VLM 璋冪敤銆?- Transaction: 浠?`target_missing/crash_dialog` 鍦?relaunch 璺緞璁板綍 `app_crash`锛涙簮鍏冪礌閫€浼戯紝鍥鹃《灞傚啓 `abnormal_buttons`锛屼笉鍐欒涔夎竟銆佷笉鏍囨垚鍔?region/memory銆傚叡浜尯鍧楀湪鏈疆鍜?resume 鍚庡潎鎸?`region_id+name` 璺宠繃锛岃妭鐐瑰眬閮ㄩ〉闈㈡寜 `state_id+uid/name` 璺宠繃銆?- Observability: live monitor 瀹炴椂鏄剧ず `[寮傚父鎸夐挳]`锛岀粨鏉熸憳瑕佸垪鍑哄紓甯告寜閽悕绉颁笌鍘熷洜銆?- Schema/migration: 鏂板浘鍙惈椤跺眰 `abnormal_buttons`锛屽厓绱犲彲鍚?`abnormal_reason/abnormal_detail`锛涙棫鍥剧己瀛楁鎸夌┖璐︽湰鍔犺浇銆傛牴鎹袱杞棩蹇椾腑 21 娆?Sound鈫掓闈㈣瘉鎹紝褰撳墠 14 鑺傜偣 Settings 鍥惧凡鍥炲～ `Sound/app_crash/r1`锛涚函鍐呭瓨鐪熷疄鍥?resume 纭 Sound 涓嶈繘鍏ュ€欓€変笖娌℃湁琚璁′负 region 鎴愬姛鐐瑰嚮銆?- Verification: `test_visual_cache.py`銆乣test_resume_from_graph.py`銆乣test_visual_run_state_machine.py`銆乣test_live_status_summary.py`銆乤rchitecture boundaries銆乬raph quality guards銆乧andidate breakdown銆丒xplorer done銆乧lick-effect銆乣py_compile` 鍧囬€氳繃銆傚彧楠岃瘉绂荤嚎浜嬪姟涓庢寔涔呭寲锛涙湭瀹ｇО淇鍚庣湡鏈洪棴鐜€?
### 2026-07-10 / working-tree 鈥?璋冭瘯鍙拌繘绋嬬粨鏉熸憳瑕?
- Observability: `run_visual_traversal.py` 鍚姩 live monitor 鏃舵樉寮忎紶鍏ュ綋鍓嶉亶鍘?PID锛涚洃瑙嗗彴绛夊緟杩涚▼鐪熷疄閫€鍑猴紝涓嶄娇鐢ㄦ棩蹇楅潤榛樿秴鏃躲€?- Final report: 缁撴潫鏃朵粠 `graph.json` 璇诲彇鑺傜偣銆佽竟銆佸姩浣滃拰椤甸潰鍚嶏紝骞剁粨鍚堟渶鏂拌繘搴︽棩蹇楁姤鍛婂尯鍧?瀵艰埅瑕嗙洊銆佸仠姝㈠師鍥犲強闂€€銆乭ard reset銆侀殧绂汇€乂LM/grounding銆佹劅鐭ュ紓甯歌鏁般€俙frontier_empty` 涓庢湭瀹屾垚鍋滄浣跨敤涓嶅悓鏍囬銆?- Compatibility: 鎵嬪伐杩愯 `python tools/live_status.py <log>` 浠嶅彲鐢紱鏃?`--pid` 鏃跺彧鏈夋棩蹇楁槑纭嚭鐜扮幆澧冨叧闂俊鍙锋墠閫€鍑恒€傚凡缁忓惎鍔ㄧ殑鏃х洃瑙嗗彴杩涚▼涓嶄細鐑姞杞芥湰娆′唬鐮侊紝涓嬫鍚姩鑷姩鐢熸晥銆?- Verification: `C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -B tools\test_live_status_summary.py` 閫氳繃锛沗py_compile` 涓庣浉鍏?`git diff --check` 閫氳繃銆傛湰椤逛负绂荤嚎/鏃ュ織绾ч獙璇侊紝鏈瓑寰呭綋鍓嶇湡鏈洪亶鍘嗙粨鏉熼獙璇佹柊绐楀彛杈撳嚭銆?
### 2026-07-10 / working-tree 鈥?閫€褰?A11y 涓庢棫閲囬泦杩愯鏃?
- Behavior: 鐜 observation 鏀逛负鎴浘/terminal锛沄LM agent 鏀舵暃涓?screenshot-only `predict_mm`锛汼tateGraph 鏀舵暃涓虹函瑙嗚鎸佷箙鍖栧苟淇 `stop_reason` load銆?- Removed: 14k A11y traversal銆乤pp_filter/completion/memory/logger/scroll 绛夋棫鍥炬ā鍧楋紝ScenarioExecutor 涓?atom/chain/generator/supplement 绛夋棫 scenario 妯″潡锛宺andom walker/reverse inference锛屾棫 prompts銆丄11y converter/璇婃柇鑴氭湰銆佹棫鍏ュ彛鍜屽け鏁?launcher銆?- Retained: visual traversal/router/resume/state銆乤pp lifecycle銆乿isual StateGraph銆乧apability synthesis/instruction schema銆丆ollectionWriter銆乀rajectoryVerifier銆?- Collection migration: 鏃ч噰闆嗗叆鍙ｄ笉鍐嶅彲鐢紱鍚庣画鎸夌 7 鑺傞噸鍐?screenshot-only executor銆?- Size: 褰撳墠 working diff 涓?106 涓?tracked 鏂囦欢琚垹闄わ紝鍚堣绾?44,742 琛岋紱鏈€澶у垹闄ら」鏄?14,359 琛屾棫 traversal 鍜?3,403 琛屾棫 executor銆?- Verification: 19 涓湁鏁堢绾垮洖褰掕剼鏈€氳繃锛宍tools/test_visual_router.py` 涓?6 passed锛涜瑙?鑳藉姏鍏ュ彛 `--help`銆乤ctive `compileall`銆侀潤鎬侀€€浼戠鍙锋绱㈠拰 `git diff --check` 閫氳繃銆備袱涓?live modal 鑴氭湰鐨勬棫 env 鍙傛暟宸茶縼绉伙紝浣嗘湰杞笉閲嶈窇 VM/VLM锛屽洜姝や笉璁′负鐪熸満楠岃瘉銆?
### 2026-07-10 / working-tree 鈥?Settings 鏂板浘鐭▼澶嶆祴鍏ュ彛

- Security/entry: `run_visual_setting.ps1` 鍒犻櫎婧愮爜鍐呭祵 API 鍊硷紝鍙帴鍙楃幆澧冩敞鍏ョ殑 `DASHSCOPE_API_KEY`锛岀己澶辨椂绔嬪嵆鎶ラ敊銆?- Experiment: 鏂板浘浣跨敤鐙珛 result root銆佸喎鍚姩 Settings銆乂LM grounding銆乺egion dedup銆佸鑸惤鍦伴獙鏀跺拰 live monitor锛涘厛浠ュ皬棰勭畻鍙戠幇缁撴瀯鎬ч棶棰橈紝鍐嶅喅瀹氭槸鍚︽墿澶с€?- First-run finding/fix: Background 椤?grounding 杩炵画瓒呮椂鏆撮湶缁熶竴 75 绉?timeout 瀵瑰ぇ缁撴瀯鍖栬緭鍑鸿繃鐭紝浠ュ強 perception retry 脳 transport retry 鐨勬斁澶с€傜幇鍦?grounding 浣跨敤鍗曟 150 绉?role timeout锛堝彲鐢?`GUIWALK_GROUNDING_TIMEOUT` 閰嶇疆锛夛紝涓嶅啀宓屽閲嶈瘯锛涘叾瀹?VLM role 浠嶄娇鐢?75 绉掍笌鍘?retry policy銆?- Graph safety: grounding 涓虹┖涓嶅啀娉ㄥ唽 `0 elements / EMPTY region_set` 鑺傜偣銆俙_register()` 鎶涘嚭 `PerceptionUnavailable`锛屼富寰幆淇濆瓨鏈€鍚庡ソ鍥俱€佽缃?`stop_reason=perception_unavailable` 骞朵繚鐣欐湭 commit 鍊欓€変緵 resume 閲嶈瘯銆?- Artifact fix: `state_meta.json` 涓?`node_index.json` 鏂板鐪熷疄 `page_name`锛涚绾?capability synthesis 涓嶅啀浠呬緷璧栬嚜韬帹鏂〉闈㈠悕銆?- Observability: startup dismisser 鍦ㄦ甯搁〉闈㈣繑鍥?`done` 鏃惰褰曗€渘ormal frame confirmed鈥濓紝涓嶅啀璇啓鈥渋nterruption flagged鈥濄€?- Verification: architecture銆乿isual cache銆乂LM role timeout銆乵odal candidate銆乿isual run-state transaction锛堝惈绌烘劅鐭ヤ笉姹℃煋鍥撅級銆乧ompileall 涓?diff check 閫氳繃銆傚墠涓よ疆鐪熸満绋冲畾澶嶇幇 Background 瓒呰繃 75 绉掞紱绗簩杞繕瀹氫綅鍑虹┖鑺傜偣姹℃煋锛屼慨澶嶅悗绛夊緟绗笁杞獙璇併€?- Third-run result: 鍗曟 150 绉?grounding 涓嬶紝Background 鍦ㄧ害 75.6 绉掓垚鍔熻繑鍥烇紙38 elements锛夛紝璇佹槑鏃?75 绉掗槇鍊间細鍦ㄥ搷搴斿嵆灏嗗畬鎴愭椂璇潃銆? 鍔ㄤ綔鎺㈤拡浜у嚭 Network/Bluetooth/Background 3 鑺傜偣銆? 鏉?`transitioned_consistent + landing_verified` 杈癸紝graph lint 0 error锛沗stop_reason=max_actions` 绗﹀悎鎺㈤拡棰勭畻銆?- Cost evidence: 17 logical calls / 17 transport attempts / 6 cache hits / 256.0s model latency銆俫rounding 3 calls 鍗?201.5s锛堢害 79%锛夊拰 7,396/8,483 completion tokens锛涙甯稿悶鍚愮摱棰堟槸鏁村睆 grounding锛屼笉鏄櫘閫?semantic role 鎴?retry銆?
### 2026-07-10 / working-tree 鈥?瑙嗚閬嶅巻璐ㄩ噺涓庤鐭ラ潰鏀舵暃

- 鎵€鏈夌偣鍑绘敼涓哄疄鏃堕噸缁戯紝瀵艰埅鏁堟灉/钀藉湴楠屾敹澶辫触涓嶆彁浜ゅ浘鐘舵€併€?- 寮曞叆 selected tab 韬唤銆乵odal 鍒濆琛ㄩ潰淇濈暀銆丷outer 鍞竴鍥為€€璺緞銆佸師瀛?resume銆乂LM role cache銆?- 鍒犻櫎閫€浼?`visual_backtrack.py` 鍙婂彧瑕嗙洊鏃у洖閫€瀹炵幇鐨勬祴璇曘€?
### 2026-07-13 / working-tree 鈥?鑷劧璇█鎿嶄綔涓庡彲閲忓寲婊戞潯鍙傛暟

- Capability presentation锛氱绾?VLM 鎻愬彇鎻愮ず鏀逛负鎶婅兘鍔涘啓鎴愪汉绫诲彲鐞嗚В鐨勭畝鍗曟搷浣滐紝涓嶆妸 Python 寮忓嚱鏁板悕銆佹帶浠剁紪鍙锋垨鈥滅偣鍑绘煇鎺т欢鈥濅綔涓哄姛鑳藉悕绉帮紱鍚岄〉鐩镐技鎺т欢浠嶆寜涓氬姟瀵硅薄鍖哄垎銆?- Slider contract锛氭暟鍊?`slider/range` 浠庢ā绯?continuous 鏀逛负鍥哄畾鍙傛暟 `鏈€灏?涓€鍗?鏈€澶锛宲ortable recipe 涓?`SET_SLIDER` + 瀹炴椂璇箟 selector + `level` 鍙傛暟妲姐€傛墽琛岄€傞厤鍣ㄥ彧渚濇嵁褰撳墠鎴浘閲嶅畾浣嶅悗鐨勬暣鏉℃粦杞?bbox 璁＄畻鐩稿钀界偣锛涚枒浼间粎璇嗗埆鍒板皬鎵嬫焺鏃跺け璐ュ叧闂€傛帓搴忓拰鑷敱鎷栨斁浠?unsupported銆?- Verification锛氱绾胯繍琛?`python -m py_compile gui_rewalk/src/core/visual_traversal/capability_discovery.py gui_rewalk/src/core/scenario/live_visual_collection.py gui_rewalk/src/core/scenario/capability_synthesizer.py tools/test_online_capability_discovery.py tools/test_live_visual_collection.py`銆乣python -B tools/test_online_capability_discovery.py`銆乣python -B tools/test_live_visual_collection.py`锛屽潎閫氳繃銆傚皻鏈惎鍔?VM銆佽皟鐢ㄧ湡瀹?VLM 鎴栨墽琛岀湡瀹炴粦鏉¤惤鍦伴獙鏀躲€?

### 2026-07-15 / staged visual traversal runtime and state packages

- Architecture: `visual_engine.py` 从约 4.8k 行降到 3,257 行；`run()`、`_register()`、`_register_landed()` 变为兼容 wrapper。canonical 实体位于 `visual_traversal/runtime/` 和 `visual_traversal/state/`，且不反向 import Engine。
- Runtime: 96 行 `runner.py` 以 RunCursor/StageDirective 串联 bootstrap、scheduling、execution、recovery、landing、completion；`plan_candidate` 成功时返回明确的 `EXECUTION` 指令，runner 显式检查后才执行。CandidateContext 与 AttemptContext 分别承载计划和已执行动作。action event、coverage commit、landing verification、stateful restore、route 延迟和 stop reason 保持原时序。
- State: matching、Page/Variant identity、region-set helper、registry、registration 分离；旧 `visual_state.py` 保持 import identity shim。删除了 registry 内误复制且不可达的第二份 `ElementMatcher`。
- Maintainability: 新增 `design/modules/visual_traversal_file_map.md`，枚举 visual_traversal 下每个 Python 文件的责任、维护入口、输入输出/状态合同和对应测试；architecture test 防止遗漏、反向 Engine import 和重新长成超限文件。
- Verification: `python -m compileall -q gui_rewalk/src/core/visual_traversal gui_rewalk/src/core/graph/state_graph.py` 通过；runtime/state/architecture/identity/resume 第一组 `57 passed, 1 skipped`（`test_button_identity.py` 是需要两张图片参数的手工脚本，无参数 pytest 收集时明确 skip）；repository/scroll/stitch/modal 第二组 `14 passed`；最终 `EXECUTION` 边界和死代码更正后，`python -m pytest -q tests/test_architecture_boundaries.py tests/test_visual_run_state_machine.py` 为 `31 passed`；`python -B tests/test_explorer_done_override.py` 为 `ALL PASS`；`git diff --check` 通过（仅工作区既有 CRLF 提示）。只做离线静态/行为测试，未运行 VM、真实 VLM 或 live rollout。

### 2026-07-15 / GraphQuality `evaluate_data` deterministic-stage split

- Architecture: `GraphQualityAgent.evaluate_data` 从约 1,163 行压缩为 64 行编排壳，内部无 `FunctionDef`。schema-v3 catalog/Page-Variant/ActionEdge/capability-route、stateful mutation、shared control、node、cross-node duplicate、edge 和 summary 审计均是同文件模块级 helper；VLM 段保留为 35 行实例方法 `_apply_vlm_review`。最长新 helper `_audit_edge` 为 243 行，其余更短。
- Compatibility: `evaluate/evaluate_data` 签名、只读输入、报告字段与顺序、finding 顺序/code/severity、score/confidence、prompt/schema/CLI/阈值均未改变。关闭 VLM 后三图 canonical report SHA-256 依次为 `61d0c679603e90228b33a0738c8e1494e69b544c084d1dab0ad76fb8a5330a6f`、`b6388489450c4a0e57541312feb1530089196cb302c723427d575d25de29773a`、`71260988d5f6df3b2b8ebd0fe5756b7e91d9e1918c84da6cd9b5a7e314d9e624`，与拆分前完全一致。
- Verification: `python -m compileall -q gui_rewalk/src/core/graph/graph_quality_agent.py` 通过；`python -B tests/test_graph_quality_agent.py` 输出 `PASS: read-only graph quality rules + structured VLM judge + action ledger audit`；`python -m pytest -q tests/test_graph_quality_guards.py` 为 `9 passed, 1 failed`，唯一失败是不经过 GraphQuality 的 VisualTraversalEngine data-control 候选过滤既有断言，修复将超出本次允许文件和任务边界。目标文件 whitespace/diff 检查通过。未启动 VM，未调用真实 VLM，未执行 live 操作。

### 2026-07-15 / graph and scenario function-length debt ratchet

- Guard: `tests/test_architecture_boundaries.py` 现用 `rglob('*.py')` + `ast.walk`
  扫描 `src/core/graph` 和 `src/core/scenario` 的所有同步/异步函数，包括方法和
  嵌套函数。默认函数必须小于 250 行；仅保留
  `evaluate_traversal_completion<=1267`、`_ground_prerequisite_action<=260`、
  `_resolve_one<=254` 三个只能缩小的历史预算。预算对应函数消失时测试也会
  要求删除 stale 白名单项；`GraphQualityAgent.evaluate_data` 保持在默认门槛内，
  不在白名单。此检查不设文件级行数上限。
- Verification: `python -B -m pytest -p no:cacheprovider -q tests/test_architecture_boundaries.py`
  为 `15 passed in 2.75s`。独立 AST 清单确认全部 `>=250` 函数仅为上述三项，
  实际行数依次为 1267/260/254；`GraphQualityAgent.evaluate_data=64`。
  本轮只运行离线架构和静态检查，未启动 VM，未调用真实 VLM，未执行 live 操作。


### 2026-07-15 / offline Android grounding screenshot collector

- Current entry point: `tools/capture_mobile_screens.py` is the read-only manual
  Android capture tool. It selects an online device from `adb devices` (or
  validates `--serial`) and captures unmodified bytes through
  `adb [-s SERIAL] exec-out screencap -p`; it never clicks, swipes, resets apps,
  changes overlays, or writes device state. The CLI supports `--adb`,
  `--output-root` (default `data/imported/mobile_grounding`), safe `--session`,
  `--settle-seconds`, `--prefix`, and non-interactive `--capture-once [LABEL]`.
- Data contract: each resumable session contains `images/`, `frames/`, and an
  atomically replaced `manifest.json` with schema
  `gui_rewalk.mobile_grounding_capture.v1`. Frame records are ordered and include
  a stable monotonic index, label, relative PNG/sidecar paths, UTC timestamp,
  SHA-256, IHDR width/height, serial, and best-effort foreground
  package/activity. Resume continues after the greatest manifest index, skips
  existing orphan filenames, never overwrites a PNG, and rejects a device-serial
  mismatch. Interactive undo removes only the current manifest's final frame.
- Module documentation: `design/modules/mobile_collection_debug.md` now records
  the official manual-capture workflow, commands, safety boundary, and artifact
  layout.
- Verification (offline only): `python -m pytest -q
  tests/test_capture_mobile_screens.py` -> `15 passed`; `python -m py_compile
  tools/capture_mobile_screens.py tests/test_capture_mobile_screens.py` -> exit
  0; `python tools/capture_mobile_screens.py --help` -> exit 0; `git diff
  --check -- tools/capture_mobile_screens.py tests/test_capture_mobile_screens.py
  design/modules/mobile_collection_debug.md design/CURRENT_FRAMEWORK.md` -> exit
  0. No emulator/physical-device capture was run, so live ADB and device behavior
  are not claimed as validated.

### 2026-07-16 / simple VMware desktop screenshot sorter

- Current entry point: `python tools/simple_emulator_screenshot.py` starts a
  standard-library browser UI on `127.0.0.1:8770`. On each explicit refresh it
  runs argv-only `vmrun -T ws list`; one running VM is selected automatically,
  while zero VMs fail clearly and multiple VMs require `--vmx`. An explicit VMX
  must occur in the running list. It then validates the result of argv-only
  `getGuestIPAddress` as an IP and reads only the canonical OSWorld guest endpoint
  `http://<guest-ip>:5000/screenshot` with a ten-second timeout. The process never
  uses `shell=True`, accepts no client-supplied VM path/URL, and sends no desktop
  input or VM state-changing command.
- Preview/save contract: refresh validates PNG/JPEG magic and dimensions, retains
  the original bytes/content type only in memory, and writes no screenshot file.
  `保存截图` requires that cache and atomically publishes those exact bytes—without
  fetching again—to one radio-selected fixed directory: `正常图片` or `变体`.
  Startup creates both below `--output-dir`; its default `./测试图片` is resolved
  from the launch current working directory. Generated timestamp/process/sequence
  names are collision-safe and retain `.png`/`.jpg`; there is no filename input.
  The UI is loopback-only, has bounded JSON bodies, starts with save disabled, and
  reports VMX/IP/dimensions plus the full saved path. `--vmrun`, `--vmx`,
  `--output-dir`, `--host`, `--port`, and `--no-open` are the complete CLI surface.
- Verification (offline fakes only): `python -m pytest -q
  tests/test_simple_emulator_screenshot.py` -> `1 passed in 0.11s`;
  `python -m py_compile tools/simple_emulator_screenshot.py` -> exit 0. The test
  uses a fake vmrun command runner and fake screenshot fetcher; no real vmrun,
  guest HTTP request, VM input, screenshot save in the workspace, or service
  startup occurred.

### 2026-07-15 / geometry-only mobile state graph annotation workbench

- Entry point and safety: `tools/mobile_graph_annotator.py <session-dir>` serves
  the adjacent self-contained HTML UI through a standard-library HTTP server on
  IPv4 loopback only. Optional `--live-capture` reuses
  `capture_mobile_screens.AdbClient/SessionStore/CaptureApp` for screenshots and
  metadata. Neither the default nor live path taps, scrolls, resets applications,
  changes overlays, or accepts arbitrary client filesystem paths. JSON and PNG
  bodies are bounded; image access is state-ID/canvas-ID based.
  Direct script startup derives trusted `TOOLS_DIR`/`REPO_ROOT` from `__file__`
  and installs both deterministically in `sys.path`; lazy canonical scroll/stitch
  imports therefore do not depend on cwd, `PYTHONPATH`, or environment paths.
- Current interaction: viewport canvases support anonymous button boxes, region
  boxes, and click points; fullpage canvases support region boxes only. The UI
  provides exact responsive coordinate mapping, automatic IDs, selection,
  deletion, undo, explicit autosave state, state navigation, shared-region
  reuse, existing/live click targets, PNG fullpage upload, manual live scroll
  sequences, and a state/edge overview. It contains no annotation text input.
  Browser load selects the latest active state without taking a screenshot. The
  explicit `生成状态` action always appends a capture-backed state, including on
  an empty graph or unchanged pixels; it resolves a staged device action into its
  typed edge or creates an isolated state, without consuming geometry pending-click
  metadata. Empty graphs retain state generation while disabling state-only controls.
  The state panel also creates ID-only undirected `same_page_links` between two
  retained screenshots without inventing an action edge or merging annotations.
  A read-only responsive SVG below the screenshot renders the current state's
  1-hop induced subgraph with screenshot thumbnails, typed/directed action edges,
  dashed same-page links, and keyboard/mouse state navigation. Exactly two
  neighbors are placed left/right of the current state. A read-only relation list
  below the SVG spells out source/type/direction/target and includes click
  coordinates or scroll direction plus anchor, so card overlap cannot obscure the
  transition meaning.
- Data contract: capture manifest/PNGs/sidecars are read-only. All new artifacts
  are below `<session>/annotations/`; atomic `graph.json` uses schema
  `gui_rewalk.manual_grounding_graph.v1`. Capture indices deterministically map to
  `sNNNNNN` states. The additive v1 `capture_floor_index` defaults to zero for old
  graphs and prevents cleared capture indices from being re-imported. Additive
  `same_page_links` canonicalize two distinct valid state IDs by frame order and
  represent a manual same-logical-page declaration, not navigation. Additive
  `pending_device_action` stores at most one targetless click/scroll/Back action
  until explicit generation. Successful later tap/scroll/Back actions atomically
  replace that single slot (latest action wins); generation consumes only that
  final action. Viewport/fullpage metadata, anonymous annotations, click
  edges, shared-region ledgers, and recoverable pending clicks store original
  pixels and `[0,1000]` normalized geometry; recursive `name`/`label` keys are
  rejected. Long-page frames do not become states. Generation calls canonical
  `grounding/stitch.py::stitch_frames/encode_png`, records source/dimension/sticky
  and frame-top metadata, and preserves frames plus the prior fullpage on failure.
- Documentation: `design/modules/mobile_collection_debug.md` records the current
  UI, CLI, graph schema, safety boundary, click/shared-region transactions, and
  long-page workflow.
- Follow-up hardening: `.gitignore` explicitly includes the required adjacent
  HTML runtime asset; shared-region reuse defaults to the latest ID and disables
  itself for an empty ledger; failed fullpage persistence restores the complete
  graph snapshot, annotation pixel geometry, history boundary, and prior PNG.
- Optional VM control (default off): `--live-control` implies live capture but
  requires an explicit `--serial`; its UI checkbox is independently OFF at load.
  Viewport click/wheel actions are serialized and call public integer-argv
  `AdbClient.tap/swipe` and wait bounded `--action-settle-seconds`, then persist
  one `pending_device_action`; each successful later tap/wheel/Back atomically
  overwrites it, so pending does not lock these three device controls. The pending
  UI keeps the VM-control checkbox and Back available and warns that only the
  latest action will be kept. These actions do not capture, append a state, or add
  an edge. Explicit `生成状态` captures once and atomically appends the matching
  click/scroll/Back edge for the final staged action plus clears staging. Existing
  v1 graphs migrate with empty typed-edge ledgers; fullpage actions and
  disabled-control APIs fail with 409. While pending, live capture/refresh and
  manual/automatic long-page workflows still fail with 409. If a later ADB action
  fails, the previous pending action remains; if its staging save fails, graph and
  history roll back to that previous pending action. Action/staging/generation
  failures do not append success edges. Plain click-point annotation and
  `--live-capture` remain non-mutating.
- Android Back: `AdbClient.back()` uses the explicit argv sequence `adb -s
  <serial> shell input keyevent 4`. The independent `虚拟机返回（Back）` button is
  its own authorization and does not depend on the VM-control checkbox. On a
  viewport it shares the action lock, waits the bounded settle interval, and stages
  a coordinate-free Back action; explicit generation later captures and appends
  the `back_edges` source/target record.
  Empty/fullpage/unavailable/busy cases are disabled or return 409; Back/capture
  failures add no edge, and pending-click metadata is preserved. Existing v1
  graphs migrate with an empty `back_edges` ledger.
- Graph reset: the confirmed `清空图` action atomically clears state annotations,
  fullpage links, pending clicks/device actions, click/scroll/back edges, same-page links, shared regions, and scroll
  sequence references, advances `capture_floor_index` to the highest current
  manifest/state index, and empties active states. Source PNGs, manifest, and
  generated fullpage/scroll files remain unchanged on disk; later sync skips the
  hidden indices and the next higher capture becomes the first active state
  without renumbering. A single Undo restores the complete graph/floor. Clear
  shares the real-action lock (busy -> 409) and restores graph plus undo history
  on save failure.
- Automatic fullpage: confirmed `/api/scroll/auto` requires `--live-control` and
  shares the action lock. It lazily imports the canonical touch-scroll constants
  (0.42 fraction, 14-step cap, patience 2, pHash distance 4), captures only
  same-size/on-app nonduplicate frames, and terminates on stability, off-app, or
  hard cap. Every executed down action triggers bounded best-effort 2/3-screen
  restore, including error paths; unconfirmed restore is explicit metadata/UI
  warning. Frames create no states or edges. Versioned run/fullpage files plus
  sequence/fullpage graph references commit as one Undo step and canonical stitch
  remains the compositor. Before any swipe, live and selected-state viewport
  pHashes must match within the canonical threshold; mismatch is a zero-mutation
  409 and successful metadata records `source_match_distance`. While the shared
  action lock is held, all other POST mutations return 409 and the UI freezes all
  mutation/upload controls while retaining read-only navigation. No live automatic
  scroll was executed.
  Automatic scrolling is also rejected while a device action awaits generation
  and never appends graph states.
- Verification (offline fake ADB/browser-free): `python -m pytest -q
  tests/test_capture_mobile_screens.py tests/test_mobile_graph_annotator.py` ->
  `50 passed in 2.05s`; `python -m py_compile tools/capture_mobile_screens.py
  tools/mobile_graph_annotator.py tests/test_mobile_graph_annotator.py` -> exit 0;
  `python tools/mobile_graph_annotator.py --help` -> exit 0; `git diff --check --
  tools/mobile_graph_annotator.py tools/mobile_graph_annotator.html
  tests/test_mobile_graph_annotator.py design/modules/mobile_collection_debug.md
  design/CURRENT_FRAMEWORK.md` -> exit 0. A separate read-only integration smoke
  forwarded a remote ADB server over SSH, captured `emulator-5612`, started the
  loopback UI with live capture/control enabled, and confirmed `/api/graph`
  reported one state plus `live_enabled=true`/`control_enabled=true`; the served
  viewport PNG SHA-256 matched the captured source. No real tap or swipe was sent,
  so device mutation and post-action capture remain unvalidated on a live VM.
  After the clear/automatic-long-page update, the loopback service was restarted
  against the same remote session and reported 13 states, 6 click edges, 6 scroll
  edges, one retained sequence, and live/control enabled; the served HTML included
  both new controls. Neither clear nor automatic scrolling was invoked live.

### 2026-07-16 / active-graph clear and explicit live refresh

- Behavior: `清空图` now empties the active state graph instead of leaving capture
  pages visible. The additive, backward-compatible v1 `capture_floor_index`
  high-water mark prevents `sync_capture_manifest()` from repopulating cleared
  frames while retaining the original manifest and all screenshot/fullpage/scroll
  files. Undo restores states, relations, annotations, and the prior floor; clear
  and undo persistence failures restore both in-memory graph and history.
- UI/live sync: a zero-state graph clears the previous canvas/overlay/nodes/edges
  and disables state-only actions while leaving Undo and `刷新实机画面` usable.
  Initial GET selects the latest state but performs no screenshot. Independent
  `POST /api/live-refresh` shares the action lock, reuses the latest same-size
  viewport within canonical pHash distance 4, or appends a new isolated state;
  it never completes pending-click metadata or creates an edge.
- Verification (local offline/fake capture only): `python -m pytest
  tests/test_mobile_graph_annotator.py -q` -> `41 passed in 2.66s`;
  `python -m py_compile tools/mobile_graph_annotator.py` -> exit 0. These checks
  cover v1 migration, clear/sync/next-frame/undo/save rollback, empty UI/static
  contracts, latest-state load, and live-refresh dedup/change/empty/pending/HTTP/
  disabled/busy behavior. No real-device clear or live-refresh was executed, so
  this entry does not claim runtime VM validation.

### 2026-07-16 / explicit Android Back transition capture

- API/data: public `AdbClient.back()` invokes Android keyevent 4 through an argv
  list. Graph v1 adds backward-compatible `back_edges`; sync prunes edges whose
  states disappear, clear reports and removes the ledger atomically, and Undo/
  save-failure rollback retain the existing transaction behavior.
- Runtime/UI: `back_enabled` is independent of tap/swipe `control_enabled`.
  `POST /api/control/back` and `虚拟机返回（Back）` share the action lock, accept
  viewport states only, perform Back -> bounded settle -> capture -> edge save,
  retain pending clicks, and navigate the UI to the captured viewport. The button
  is disabled for zero states, fullpage, unavailable Back, or busy execution and
  does not require the VM-control checkbox.
- Verification (offline/fake callbacks only): `python -m pytest -q
  tests/test_capture_mobile_screens.py tests/test_mobile_graph_annotator.py` ->
  `63 passed in 3.42s`; `python -m py_compile tools/capture_mobile_screens.py
  tools/mobile_graph_annotator.py` -> exit 0. No real Android Back event was sent.

### 2026-07-16 / undirected same-page state relationship

- Data/API: graph v1 adds backward-compatible `same_page_links`. Each ID-only
  record contains exactly two different valid states, canonicalized by frame
  order. `GraphStore.link_same_page()` is idempotent without an extra Undo entry;
  sync prunes invalid members, clear reports/removes links, and Undo restores them.
  `POST /api/same-page/link` exposes only the two state IDs.
- UI/meaning: the current state can be linked to another existing state while
  preserving both screenshots and annotation sets. Relations render separately
  as `same-page sA ↔ sB`, never as click/scroll/back/navigation edges. Dynamic
  content, time, or ordinary scroll positions may differ; modal/drawer/popup and
  other distinct active surfaces must not be marked as the same page. No text
  annotation or naming input was added.
- Verification (offline only): `python -m pytest -q
  tests/test_capture_mobile_screens.py tests/test_mobile_graph_annotator.py` ->
  `65 passed in 3.76s`; `python -m py_compile tools/capture_mobile_screens.py
  tools/mobile_graph_annotator.py` -> exit 0. No ADB operation was executed.

### 2026-07-16 / standalone annotator lazy-import bootstrap

- Root cause/fix: direct `python tools/mobile_graph_annotator.py ...` startup put
  `tools/` but not the repository root on `sys.path`; delayed imports of
  `gui_rewalk...grounding.scroll/stitch` therefore failed when cwd/PYTHONPATH did
  not add the root incidentally. The tool now derives trusted `REPO_ROOT` from
  `Path(__file__).resolve().parent.parent` and deterministically prepends both the
  tools directory and repository root. It accepts no external import-path input.
- Verification (local/offline): `python -m pytest -q
  tests/test_capture_mobile_screens.py tests/test_mobile_graph_annotator.py` ->
  `66 passed in 4.70s`; `python -m py_compile tools/mobile_graph_annotator.py` ->
  exit 0. `python -m pytest -q tests/test_mobile_graph_annotator.py -k
  lazy_grounding_imports` -> `1 passed, 49 deselected in 0.99s`; that test launches
  isolated Python with `-I`, removes `PYTHONPATH`, uses a repository-external cwd,
  loads the tool by absolute file path, imports real scroll/stitch, and confirms
  canonical stable distance 4. No real ADB action or scrolling was executed.

### 2026-07-16 / current-state screenshot 1-hop graph

- Definition: pure frontend helpers gather all direct neighbors of the current
  state by treating click/scroll/back/same-page endpoints as undirected for
  membership, then induce all stored relations whose endpoints are in that node
  set. This preserves relations between included neighbors and excludes nodes or
  edges reachable only beyond one hop. Stored action direction/type remains
  unchanged; same-page remains undirected.
- Rendering/interaction: a dependency-free responsive SVG below the current
  screenshot draws edges before nodes, uses distinct arrows/colors/labels for
  click, scroll, and Back, and dashed same-page lines. Canonical-pair curve offsets
  separate parallel/reverse relations, with arrow endpoints clipped to thumbnail
  card boundaries. The highlighted center thumbnail is larger; all neighbors are
  retained and the viewBox expands with count. Empty/isolated states are explicit,
  and click or Enter/Space selects a thumbnail's viewport and rerenders.
- Boundary/verification: the panel only reads the in-memory graph and existing
  `/api/image/<state>/viewport` resources; it writes no graph data, captures no
  screenshot, performs no device action, adds no text input, and uses no CDN.
  `python -m pytest -q tests/test_capture_mobile_screens.py
  tests/test_mobile_graph_annotator.py` -> `68 passed in 5.05s`;
  `python -m py_compile tools/mobile_graph_annotator.py` -> exit 0;
  `python -m pytest -q tests/test_mobile_graph_annotator.py -k "local_graph or
  html_static_contract"` -> `3 passed, 49 deselected in 0.37s`. The latter runs
  the extracted pure JS A-E induction/layout assertions with local Node.js and
  checks the complete inline script syntax. Browser visual/interactive validation
  was unavailable, and no ADB operation was executed.

### 2026-07-16 / staged device actions and explicit state generation

- Contract: graph v1 adds backward-compatible `pending_device_action` for one
  targetless click, scroll, or Back action. Tap/wheel/Back now execute exactly one
  device action, wait the settle interval, and persist staging without capture,
  state, edge, or geometry-pending-click mutation. Repeated device actions and
  live/manual/automatic capture workflows return 409 until generation or cancel.
- Generation/UI: `POST /api/state/generate` and `生成状态` always append a new
  capture-backed state, even for unchanged pixels or an empty graph. They atomically
  create the staged typed edge and clear staging, or create an isolated state.
  `取消待生成（不回退设备）` only clears metadata because a sent device action is
  physically irreversible. The UI remains on the source after staging, shows the
  pending action prominently, disables device/long-page controls, and keeps
  generation/cancel available. Browser load never captures; compatibility
  `/api/live-refresh` remains server-only and is not called by the UI. Automatic
  long-page generation still creates no graph states.
- Failure boundary: staging save failure restores graph/history but cannot undo
  the already executed device action. Generation capture/edge/save failure restores
  in-memory graph/history, staging, and success-edge absence; an immutable capture
  frame already appended before a later failure may remain on disk and is not
  deleted. Clear and manifest sync remove invalid staging as specified.
- Verification (offline fake callbacks only): `python -m pytest -q
  tests/test_capture_mobile_screens.py tests/test_mobile_graph_annotator.py` ->
  `71 passed in 5.07s`; `python -m py_compile tools/mobile_graph_annotator.py` ->
  exit 0; `python -m pytest -q tests/test_mobile_graph_annotator.py -k
  "local_graph or html_static_contract"` -> `3 passed, 52 deselected in 0.15s`.
  No real ADB action, screenshot capture, or session mutation was executed.

### 2026-07-16 / latest-action-wins device staging and readable local edges

- Device control: a successful tap, scroll, or Back no longer conflicts with an
  existing `pending_device_action`. It atomically replaces the single slot, so a
  sequence of real operations leaves only its final action for explicit state
  generation. Generation creates exactly one typed edge for that final action.
  The UI keeps VM control and Back available while pending and explains the
  overwrite behavior. Live capture/refresh and manual/automatic long-page flows
  remain blocked until generation or cancel.
- Failure contract: a failed later ADB action preserves the earlier pending value;
  a replacement-save failure restores the previous graph and undo history. The
  separate geometry-only `pending_click` remains unchanged.
- Local graph: exactly two neighbors are arranged left/right instead of vertically.
  A read-only relation list below the SVG explicitly renders source, type,
  direction, target, and available click/scroll geometry, so edge meaning remains
  visible when screenshot cards crowd the drawn curves.
- Verification (focused offline fake/static only): `python -m pytest -q
  tests/test_mobile_graph_annotator.py -k "pending_device_action or
  latest_device_action or local_graph"` -> `5 passed, 52 deselected in 0.36s`;
  `python -m py_compile tools/mobile_graph_annotator.py` -> exit 0. No live ADB
  action, screenshot, state generation, or session mutation was performed.
  Interactive browser visual validation was unavailable.

### 2026-07-16 / hierarchical element-block-Page identity projection

- Grounding contract: the existing element call now returns optional
  `identity_anchor`; only an explicit `false` removes a volatile value from the
  Region member signature. `true`, `null`, and legacy cached elements retain the
  previous identity behavior. Action coverage remains based on
  `element_is_action` and is not filtered by this field.
- Region/Page contract: the existing block-segmentation call now returns optional
  `page_identity`, with strict optional-boolean parsing. Page identity material is
  the sorted set of confirmed `page_identity=true` `region:<rid>` tokens plus
  selected navigation/tab tokens. Region/state-set execution identity is unchanged;
  bbox, role/note/free names, and runtime visual templates never enter the Page
  hash. Without structured anchors, `semantic_page_key` remains the fallback.
- Persistence/resume: `page_anchor_tokens` is additive on graph nodes, live state
  data, and `state_meta.json`; new observations use
  `hierarchical_page_identity_v1`. Resume rebuilds Page identity from those durable
  tokens and validates the persisted page/variant ids. Old
  `semantic_page_variant_v1` graphs remain compatible and use their existing
  semantic reconstruction when no tokens are present.
- Live evidence and correction: read-only inspection of
  `artifacts/runs/local/20260716/setting` found About anchors `r2/r3/r4`, no
  Network anchors, Bluetooth `r11 + selected Bluetooth`, and Background
  incorrectly containing shared sidebar `r1`. Network's final elements did carry
  selected Network in `r1` plus a selected stateful Wired toggle in `r8`; another
  About relocation frame had two sidebar selections (About and Displays).
  Page-region projection now excludes shared navigation/chrome roles. Such
  regions contribute only when exactly one qualified selected navigation member
  exists; stateful, explicitly volatile, or multiple selected observations
  abstain. Tabs use the same single selected-token form rather than a duplicate.
- Final-ledger backfill: optional `region_page_identity` is copied onto assigned
  elements through arrival, scroll, below-fold and retag/heal paths and persists
  through `to_dict`. Before the first graph/state-meta save, registration rebuilds
  anchors from final post-scroll elements. Registry permits empty-to-nonempty and
  strict-subset enrichment, reprojects the Page and removes empty old reverse-map
  entries; conflicting sets remain first-wins. These changes have not yet been
  rerun live, so the archived four-page results are failure evidence, not a claim
  that the correction is live-validated.
- Files: `visual_perception.py`, `prompts/grounding.py`,
  `grounding/region/{registry,scroll}.py`, `visual_engine.py`,
  `state/{registry,registration}.py`, `visual_resume.py`, `artifacts.py`,
  `graph/state_graph.py`, the focused identity test, and visual traversal docs.
- Verification (offline/static only): `python -m pytest -q
  tests/test_hierarchical_page_identity.py tests/test_functional_surface_identity.py
  tests/test_region_click_ledger.py tests/test_region_visual_relocation.py` ->
  `17 passed in 2.19s`; `python tests/test_region_set_verdict.py` -> all six checks
  passed; `python -m pytest -q tests/test_resume_from_graph.py` -> `5 passed`;
  `python -m pytest -q tests/test_graph_event_ledger.py` -> `9 passed`;
  `python tests/test_online_capability_discovery.py` -> PASS; `python -m pytest -q
  tests/test_prompt_catalog.py tests/test_visual_permission_gating.py
  tests/test_vlm_grounding_startup.py` -> `11 passed`; targeted `python -m
  py_compile` for every changed Python module/test -> exit 0; `git diff --check
  -- <changed files>` -> exit 0 (line-ending conversion warnings only). No VM,
  real VLM, live Settings traversal, click, or DPI test was run for the
  correction; the archived four-page run was inspected read-only.

### 2026-07-16 / flag-gated map-guided post-click identity

- Behavior: `GUIWALK_MAP_GUIDED_ID=1` enables a post-click-only fast path. The
  landing runtime scopes `source_id/clicked_label` to exactly one `_register`
  call; `VisualRouter.expected_destinations` returns the verified/replayable
  direct target, source, then stable deduplicated one-hop neighbors. Shared or
  repeated template evidence is filtered; two unique hits may confirm locally,
  otherwise `PageIdentityJudge.which_page` receives current image first and
  ordered candidate images/descriptors, and can explicitly return `NEW`.
- Registration/recovery: a confirmed old state reuses durable elements and
  existing Page/Variant bookkeeping before arrival grounding/region/scroll work.
  A local `NEW` grounds once, reuses that result for global button/page-name
  fallback and the ordinary registration path, and VLM-rejudges a remote
  candidate. The immediately inherited state's first failed live rebind forces
  one map-bypassed full registration; success updates cursor/path without a click
  failure, while failure retains the old fail-closed retry policy and cannot loop.
  Flag-off behavior and the `host._register` monkeypatch seam are unchanged.
- Files: `navigation/router.py`, `agents/identity.py`,
  `prompts/navigation.py`, new `state/map_guided.py`,
  `state/registration.py`, `runtime/{landing,execution}.py`, `visual_engine.py`,
  focused tests, and visual traversal module/file-map documentation.
- Verification (offline/static only): `python -m pytest -q
  tests/test_map_guided_identity.py tests/test_visual_router.py` -> `26 passed`;
  `python -m pytest -q tests/test_visual_run_state_machine.py
  tests/test_resume_from_graph.py` -> `22 passed`; `python -m pytest -q
  tests/test_architecture_boundaries.py -k "not
  runtime_and_state_stage_boundaries"` -> `14 passed, 1 deselected`; the excluded
  boundary test now recognizes `state/map_guided.py` but independently fails on
  a pre-existing dirty-tree `state/registry.py` size of 942 lines versus its
  `<900` assertion (this package did not modify registry.py). `python -m pytest
  -q tests/test_hierarchical_page_identity.py
  tests/test_functional_surface_identity.py tests/test_region_visual_relocation.py`
  -> `13 passed`; `python -m compileall -q
  gui_rewalk/src/core/visual_traversal` -> exit 0; `git diff --check -- <changed
  files>` -> exit 0 with line-ending warnings only. No VM, device, live click,
  external network/API, or real VLM call was run.

### 2026-07-15 / below-fold map and OCR locate runtime split

### 2026-07-17 / flag-gated bbox-free semantic inventory and target-only grounding

- Entry point and precedence: `run_visual_traversal.py --semantic_inventory`
  enables the experiment for full traversal or `--perception-only`; it takes
  priority over `--vlm_grounding` and prevents YOLO/OmniParser loading.
  `--target_element NAME` is perception-only evidence collection for one target.
  Flag-off legacy YOLO/SoM and whole-page VLM grounding behavior is unchanged.
- Perception contract: the new VLM prompt forbids all geometry and returns
  page/surface metadata, semantic blocks, and block members. Stored elements use
  zero geometry sentinels plus `geometry_status=semantic_only`. Blocks use local
  `bN` occurrence ids and online registry-minted visual concepts; content hashes
  are not identity authority.
  `last_semantic_blocks` and `semantic_blocks.json` contain no bbox. Empty or
  malformed inventory fails with `PerceptionUnavailable` and cannot fall back to
  whole-page grounding.
- Registration contract: after map-guided old-state inheritance, semantic mode
  bypasses `detect_and_name`, arrival geometric regions, scroll/stitch, merged
  SoM QA/self-heal, UID crops, and templates. It still builds Page/Variant,
  frontier/capabilities, graph nodes, and artifacts. Graph/state metadata persist
  semantic blocks and `perception_mode=semantic_inventory` /
  `geometry_mode=target_only`; all schema/API additions are optional for old
  graph/load compatibility.
  The pre-click `_frame_state_id` check consumes stable semantic concept and
  selected-navigation tokens
  directly and cannot call geometric arrival segmentation or SoM.
- Execution contract: `ground_target` requests only one named target and accepts
  only `coordinate_space=normalized_1000`, xyxy `bbox_1000`, and
  `click_point_1000`. It strictly validates integer 0..1000 coordinates,
  positive area, and point containment, then deterministically converts to the
  original screenshot's pixel geometry. Diagnostics retain both coordinate
  forms. The target reviewer sees one red box, one blue marker at the exact
  pixel click point, plus target name/category/type/block role, and must verify
  both the enclosure and that the point is on a safe clickable part. A rejected
  review reason is passed as a
  correction hint to exactly one force-refresh retry; terminal diagnostics distinguish `target_not_found`,
  `target_review_rejected`, and `matched`. Live geometry is attempt evidence and
  is never copied back to stored semantic elements. Semantic mode does not create
  a full-page SoM.
- Files: `run_visual_traversal.py`, `prompts/grounding.py`,
  `visual_perception.py`, `live_targeting.py`, `agents/review.py`,
  `state/registration.py`, `visual_engine.py`, `artifacts.py`,
  `graph/state_graph.py`, focused tests,
  and visual traversal documentation.
- Verification (offline/static only): `python -B -m pytest
  tests/test_semantic_inventory_grounding.py tests/test_live_targeting.py
  tests/test_map_guided_identity.py -q` -> `27 passed, 1 warning`;
  `python -m py_compile` on all nine changed Python production files -> exit 0;
  `python gui_rewalk/run_visual_traversal.py --help` -> exit 0 and lists both new
  arguments; targeted `git diff --check` -> exit 0 with line-ending warnings
  only. An additional graph/artifact/architecture run reported `23 passed, 1
  failed`; the failure is the pre-existing dirty-tree `state/registry.py` size
  of 942 lines versus the `<900` architecture assertion, and this change did not
  modify that file. A pre-fix real-Qwen Clock probe returned normalized-looking
  `[19,850,177,950]` / `[98,900]`; the old pixel interpretation drew y=850 and
  the target reviewer rejected it, while deterministic 720x1280 conversion is
  approximately `[14,1088,127,1216]` / `[71,1152]`. This is discovery evidence,
  not a claim of repaired live behavior. No new VM/emulator, network, real VLM,
  live click, Clock traversal, or mobile runtime validation was run after the fix.
- Follow-up bounded live finding (pre-fix, incomplete): Android Clock inventory
  labelled five bottom tabs as stateful `nav_selection`, causing
  `stateful_risk_blocked`; the parser now clears state semantics by control type
  for every tab and the prompt reserves stateful fields for actual
  switch/toggle/checkbox/radio controls. A real switch remains unchanged.
- Map-guided follow-up: in semantic mode an exact clicked action must already
  have a verified direct destination in `node_out_edges(source)` before arrival
  confirmation runs. Unknown More-options therefore bypasses inheritance and
  enters bbox-free semantic registration; known direct destinations keep the
  fast path.
- Landing follow-up: `LandingCommitContext` now carries the source path, replay
  hints, and observation. Same-state committed no-ops retain that source cursor;
  different-state commits adopt the new path/hints/observation, eliminating the
  prior uninitialized-local failure.
- Follow-up verification (offline/static only): `python -B -m pytest
  tests/test_semantic_inventory_grounding.py tests/test_live_targeting.py
  tests/test_map_guided_identity.py tests/test_visual_run_state_machine.py -q`
  -> `48 passed, 1 warning`. The bounded Clock run stopped while exposing the
  blockers and was not rerun after these fixes; it is not a complete traversal
  or post-fix live validation.

### 2026-07-17 / minimal Region-function shortest collection prototype

- Added two standalone research modules under `scenario/`. The first reads
  existing node artifacts by stable Region, supplies Region images and element
  summaries to an injected VLM, and saves only `name`, concise `description`,
  `region_id`, `parameters`, and node `locations`. Elements remain prompt-only;
  traversal artifacts and existing M13 behavior are unchanged.
- The second validates one-to-three Region/name function references and legal
  parameters, enumerates directed unweighted function orders and locations from
  the application start node, honors simple before/after constraints, and asks a
  second VLM to word the instruction only after planning. Conditional tasks plan
  only the caller-selected true or false branch while wording the complete
  if/else instruction. Remaining before/after constraints survive replanning
  after a completed function.
- Added strict arrival/completion VLM wrappers and a callback-only coordinator:
  graph guidance stops after target-page arrival, goal checks repeat while the
  collector acts freely, and completion replans remaining functions from the
  caller-identified current node. No GUI action, VM, network, or existing
  collection entry point is part of this prototype.
- Verification (offline fake VLMs/images/graphs only): `python -B -m pytest -q
  tests/test_region_function_research.py tests/test_function_collection_research.py`
  -> `11 passed`; targeted `python -m py_compile` and `git diff --check` both
  exited 0. A read-only `read_region_artifacts()` smoke check on the existing
  Android Clock node artifacts loaded 6 Regions. No live VLM, VM, device, or GUI
  validation was run.

### 2026-07-17 / auditable semantic target-grounding attempts

- Every semantic `ground_target` call now emits an independent attempt through
  an explicit Engine-to-`LiveTargeting` artifact sink. `ArtifactWriter` stores
  monotonically numbered, safely named directories under
  `target_grounding_attempts/`, each with the byte-identical current-frame
  `input.png`, `result.json`, and (when geometry exists) `overlay.png` containing
  exactly one red bbox plus the blue actual-pixel click marker.
- `result.json` records global sequence, per-target attempt 1/2, accepted,
  rejected, or grounding-failed outcome, semantic target identity/context, the
  complete grounding diagnostic (raw response, normalized coordinates, derived
  pixel geometry, and image size), reviewer result/reason, and grounded click
  geometry. First-pass acceptance, first rejection, retry acceptance/rejection,
  target-not-found, and reviewer-unavailable paths are all recorded. Stored
  semantic elements and graph JSON remain bbox-free and do not carry image
  bytes. Artifact persistence exceptions only log a warning and cannot change
  the grounding/reviewer decision.
- A post-sink bounded Android Clock smoke run at
  `artifacts/runs/mobile_clock_grounding_audit_20260717/20260717/android_clock`
  exited 0 at `stop=max_actions` with 2 states / 1 action. It persisted
  `target_grounding_attempts/000001_more_options/{input.png,overlay.png,result.json}`.
  The raw `bbox_1000=[882,56,1000,117]`, `click_point_1000=[941,86]`, and
  `image_size=[720,1280]` were deterministically converted to
  `bbox_px_xyxy=[635,72,720,150]` and click `[678,110]`. The reviewer accepted
  the single red bbox plus blue click point, and the actual click opened the
  More-options popup as a new semantic state. This validates the live audit path
  as a bounded smoke test, not traversal completion.
- Verification (offline/static only): `python -B -m py_compile` on
  `live_targeting.py`, `visual_engine.py`, `artifacts.py`, `agents/review.py`, and
  `prompts/grounding.py` -> exit 0; `python -B -m pytest
  tests/test_semantic_inventory_grounding.py tests/test_live_targeting.py
  tests/test_map_guided_identity.py tests/test_visual_run_state_machine.py -q`
  -> `50 passed, 1 warning in 8.07s`. These commands remain offline/static;
  live persistence and click-marker behavior are covered separately by the
  bounded Android Clock smoke evidence above.

- Architecture: 18 个 map/OCR/below-fold 方法从 `visual_engine.py` 迁入 canonical `grounding/locate.py`，由 `LocateContext -> LocateRuntime` 接收显式依赖；canonical 模块不反向 import Engine。Engine 保留同签名薄 wrapper 和 `SCROLL_MAP_*` 兼容导出，`ScrollRuntime` 的 `map_to_top=self._map_to_top` seam 不变。
- State/behavior: runtime seed/sync `_region_maps`、`_map_seg_cache`、`_map_anims_off` 与 `_last_live_rebind_observation`。map 常量值、`_map_goto`/`_scroll_locate` 签名和返回值、OCR fail-closed gate、app relaunch 后清缓存重试语义均未改变。Engine 恢复导出 `_reloc=visual_relocate` 模块别名，保留旧调用方和 graph-quality 测试的 monkeypatch seam；canonical 定位实现仍在 locate。`visual_engine.py` 从 3,257 行降至 2,653 行；新 locate 模块 788 行。
- Files: `gui_rewalk/src/core/visual_traversal/visual_engine.py`、`gui_rewalk/src/core/visual_traversal/grounding/locate.py`、`tests/test_scroll_locate.py`、`tests/test_architecture_boundaries.py`、`design/modules/visual_traversal.md`、`design/modules/visual_traversal_file_map.md` 与本文。
- Verification（本机离线/合成，非 VM/VLM/live）：`python -m compileall -q gui_rewalk/src/core/visual_traversal` exit 0；`python -m pytest -q tests/test_architecture_boundaries.py tests/test_visual_run_state_machine.py` 为 `32 passed`；`python -m pytest -q tests/test_graph_quality_guards.py::test_qwen_center_is_only_click_coordinate` 为 `1 passed in 1.02s`，确认 `_reloc` 兼容 seam；`python tests/test_scroll_locate.py` A-D 全部通过；`python tests/test_scroll_waste.py` ALL PASS。未运行 live sidebar VM 脚本，不能宣称真实 sidebar/VLM 验证。

### 2026-07-17 / stable Region-image persistence for semantic traversal

- New semantic states now reuse the existing one-call block-localization crops
  and save each successful crop as
  `node_artifacts/<state_id>/region_<region_id>.png`. The crop bbox remains
  transient and absent from elements, semantic blocks, graph data, and click
  geometry. Invalid or fully out-of-frame boxes create no image and log a
  state/Region warning. Revisit behavior, identity, Router, and GUI actions are
  unchanged; the optional legacy grounded/scroll Phase 2 was not implemented.
- Region-function extraction now prefers the stable-id image, retains the old
  role-named image as a read fallback, and never uses `screenshot.png` as a
  Region image. Missing observations are omitted; a Region with no usable image
  is skipped before any VLM call and emits a warning.
- Files: `state/block_identity.py`, `state/registration.py`, `artifacts.py`,
  `scenario/region_function_research.py`, focused tests, and the visual/Region
  research module documentation.
- Verification (offline/static only): `python -B -m pytest -q
  tests/test_region_image_persistence.py tests/test_region_function_research.py
  tests/test_semantic_block_identity.py tests/test_semantic_inventory_grounding.py
  tests/test_visual_run_state_machine.py -k "not perception_only"` -> `48 passed,
  2 deselected`; targeted `python -m py_compile` on the four changed production
  modules and three focused test modules -> exit 0. Running the same pytest set
  without the filter produced `48 passed, 2 failed`; both failures occurred
  before the changed path because this environment lacks optional `torchvision`
  while importing `gui_rewalk/env/utils.py`. No VM, device, real VLM, live
  traversal, or Region-image visual inspection was run; the user's concurrent
  Clock traversal was not touched.

### 2026-07-17 / regionless virtual Back action

- Router Back is now represented as a platform-level virtual navigation action,
  not a special Region or fabricated visual element. Verified return edges use
  `action_type=BACK`, `selector.virtual_action=navigate_back`, and
  `effect_kind=return|dismiss_overlay`; element id, element label, Region, and
  source Region id remain empty. The internal `__NAVIGATE_BACK__` key exists
  only while Router plans/replays and is not persisted as an element selector.
- This does not add a frontier candidate or a VLM grounding target. It cannot
  mark Region coverage, collapse sibling controls, or promote a discovered
  capability. The edge becomes routable only after the existing live Back
  execution lands on a known, identity-verified state; replay still verifies
  every landing and retains relaunch recovery for unknown/off-app results.
- Files: `navigation/router.py`, `visual_engine.py`, the focused Router test,
  `design/modules/visual_traversal.md`, and this file. Page/Region identity,
  completion, resume, ordinary click grounding, and graph schema version are
  unchanged.
- Verification: `python -B -m pytest -q -p no:cacheprovider --basetemp
  C:\tmp\guiwalk_virtual_back_pytest tests/test_visual_router.py` -> `18 passed`;
  targeted `python -B -m py_compile` for `navigation/router.py` and
  `visual_engine.py` exited 0. The first pytest attempt already had 17 passing
  tests but could not create pytest's default Windows temp directory; it was
  rerun with the explicit writable base temp above. No emulator, device, VLM,
  or live traversal validation was run for this representation-only change.

## 2026-07-18 semantic traversal simplification

- Map-guided identity is enabled by default. The judge receives one current
  screenshot plus at most five text descriptors; candidate screenshots are not
  loaded. Router page identity receives only the current observation and chooses
  among bounded stored-page descriptors or `NEW`; the final navigation target is
  never supplied as an expected or single candidate.
- Semantic Router identify does not run inventory or read-only block alignment.
  Router compares the independently identified landing with its planned target
  only after identity returns.
  Router Back reuses the source state's durable elements and surface metadata.
  Read-only block-alignment APIs were removed; online resolution remains in
  semantic registration only.
- A semantic NEW state can extend inventory through the bounded scroll loop,
  deduplicating bbox-free elements by role/name/category/type. Map-confirmed
  revisits inherit stored inventory. Region sets remain evidence but do not
  authoritatively merge or mint semantic page states.
- Click effect no longer uses a VLM agent/prompt. Equal before/after pHash means
  `no_effect`; otherwise landing state identity yields
  `transitioned_consistent`. Structured stateful checks still override it.
  Semantic artifacts no longer write `geometry_mode`.
- Android focus checks current foreground activity/package before the visual
  focus judge. Semantic interruption handling reuses same-frame inventory.

### Change log — 2026-07-18

Implemented `issues/implementation_plan_20260718.md` at research-prototype scope:
single-image map identity, stored-element Router behavior, semantic scrolling,
local click-effect derivation, Android foreground priority, semantic interruption
reuse, group prompt constraints, and obsolete API removal. No graph schema or
deployment abstraction was added. Verification commands/results are recorded
with the implementation handoff; live Mingle evidence is reported separately.

Added opt-in persistent exact VLM response replay through
`--vlm_response_cache`. `VLMCallLedger` now records/replays raw responses by a
SHA-256 identity covering role, model and response-affecting settings, exact
prompt, and exact image content; it reports `persistent_cache_hits` without
counting replay as a transport attempt. Full traversal and `--perception-only`
share the same behavior. The cache remains disabled by default and stores no
prompt text or screenshot bytes. Focused offline verification:
`python -m pytest -q tests/test_persistent_vlm_response_cache.py
tests/test_local_html_env.py tests/test_landing_change_evidence.py --basetemp
artifacts/scratch/pytest_vlm_response_cache` -> `6 passed in 2.79s`; targeted
`python -m py_compile` for the changed entry point, cache, engine, and test ->
exit 0. These checks used a fake model and local browser contracts only; live
Qwen replay evidence, if run, is reported separately and is not Android/AVD
validation.

After adding the explicit force-refresh bypass, the final focused regression
covering persistent cache, semantic inventory/grounding, run-state, Mingle
fixture, lifecycle, landing normalization, and Local HTML reported `46 passed
in 6.15s`; targeted `py_compile` again exited 0.

Live single-page evidence used the saved synthetic Mingle Contacts screenshot
with Qwen `qwen3.7-plus`. The seed run made one successful HTTP model attempt,
returned 16 elements, and recorded 45.573 seconds of model latency. A new
process with the identical command and cache directory completed in 2.06 seconds
wall time with `transport_attempts=0`, `persistent_cache_hits=1`, and 0.01 seconds
of cache lookup latency; the two `semantic_inventory.json` files had identical
SHA-256 content. Artifacts are under
`artifacts/runs/mingle_cache_probe_{first,replay}` and the opt-in cache under
`artifacts/cache/mingle_qwen_exact`. This validates real Qwen recording/replay
for one saved synthetic page only; it is not full traversal, Android, AVD,
grounding, click, Router, or completion validation.

### 2026-07-18 — opt-in block-first inventory experiment and Qwen pilot

- Added a perception-only experimental sequence: whole-frame block discovery
  returns current active-surface blocks and transient normalized crops without
  elements; a caller-selected block is then cropped and independently enumerated.
  The default traversal and current whole-screen semantic inventory remain
  unchanged. CLI: `--block_first_inventory` and optional `--target_block`.
- Second-stage elements separate shortest stable semantic `name` from exact
  `visual_evidence`; secondary statuses cannot be appended to names, and hidden
  permission/availability cannot be inferred from application knowledge. Both
  stage requests use the persistent exact-response cache; force-refresh remains
  a live bypass.
- Real Qwen `qwen3.7-plus` A/B used saved 412x915 synthetic Mingle Contacts and
  Settings frames. Contacts: required-control recall stayed 6/6, function
  classification stayed 5/6, and exact oracle block roles improved 2/4 -> 4/4;
  the add icon semantic name was weaker (`Add` versus `Add contact`). Settings:
  recall stayed 4/4, function classification improved 2/4 -> 4/4, one duplicated
  interactive control disappeared, and visible oracle block count improved
  2/4 -> 4/4. On-demand Settings latency was 8.545 s discovery plus
  4.520-7.248 s for one selected block versus 34.014 s whole-screen. Enumerating
  every block sequentially is not guaranteed cheaper.
- Evidence: `artifacts/runs/mingle_block_first_ab_20260718/REPORT.md` and the raw
  `mingle_block_first_contacts_*`, `mingle_settings_baseline`, and
  `mingle_settings_block_*` run directories.
- Verification: focused regression command over block-first, persistent cache,
  semantic perception, run-state, fixture, lifecycle, landing, and Local HTML
  reported `49 passed in 11.01s`; targeted `py_compile` exited 0. No VM, AVD,
  Android lifecycle, live click, Router, graph completion, or full traversal was
  exercised. This two-page pilot does not establish a general recognition-rate
  improvement and the experiment remains opt-in.

Follow-up added `--block_image_mode crop|full` to the same perception-only
experiment. Full mode sends the unmodified screenshot and constrains output with
the discovered bbox. Real Qwen preserved correct scope on all four Settings
blocks, but the Contacts contact-list request leaked two adjacent shortcuts and
the top-bar add semantic name did not improve. Full mode was also slightly slower
on the tested averages. Since bbox-free output cannot be deterministically
post-filtered after leakage, crop remains the default and full remains diagnostic
only. Evidence was appended to the block-first A/B report; final focused tests
reported `50 passed in 10.06s` and targeted `py_compile` exited 0. This was still
saved-frame perception only, not full traversal or live interaction.

The final pilot mode, `--block_image_mode context_crop`, sends the full frame as
Image 1 for context and the crop as Image 2 as the only allowed element source.
It removed the two-element Contacts leakage seen in full-only mode and preserved
all tested Settings classifications, but `Add` did not improve to `Add contact`
and latency was slightly higher than crop-only (Settings three-block average
5.540 s versus 5.435 s). Crop therefore remains the default; dual-image is an
explicit fallback and full-only remains diagnostic. The exact cache covers both
ordered images. Final focused regression reported `51 passed in 19.01s` and
targeted `py_compile` exited 0; no full traversal or live action was exercised.

Verification: targeted `python -m py_compile` for the changed entry points and
modules exited 0; `python -m pytest` over map-guided identity, semantic block and
inventory grounding, Router, run-state, prompt, Mingle fixture, and the affected
architecture contracts reported `84 passed`; `python
synthetic_mobile_app/smoke_test.py` reported `PASS Mingle mobile
navigation/state/overlay/scroll smoke`. `adb devices` listed no device, so no
emulator clicks, real VLM calls, live traversal, or completion certificate were
run. The broader architecture suite also exposed two pre-existing unrelated
debt-ratchet failures (graph completion function length and Engine file length);
they were not treated as validation of this behavior change.

### 2026-07-19 — fixture oracle stage switches for traversal-only diagnosis

- Added independent `on|off` CLI inputs `--fixture_oracle_inventory` and
  `--fixture_oracle_grounding`, both defaulting to `off` and restricted to
  `vm_provider=local_html`. Inventory-on supplies only oracle-declared, currently
  visible blocks, controls, and anchors; it skips semantic inventory, block
  localization, and block identity model roles. Grounding-on resolves a stored
  target to one unambiguous visible declared control and skips target grounding
  and target review. Unknown or ambiguous targets fail closed.
- Page/Variant identity, focus checks, frontier policy, action/landing
  transactions, Router/backtracking, scroll aggregation, graph, and completion
  remain unchanged. No graph or output schema changed. Local HTML also now
  converts framework wheel clicks to Playwright pixel deltas; the old eight-pixel
  movement could be below the viewport-pHash threshold and falsely label long
  pages static.
- Files: the traversal CLI, Local HTML environment, semantic perception,
  live-targeting and block-identity modules, focused tests, Mingle README, and
  current module docs.
- Verification: focused Local HTML/live-targeting/semantic inventory/block
  identity tests reported `32 passed in 4.69s`; targeted `py_compile` exited 0;
  CLI help exposes both `{on,off}` inputs.
- Live evidence before the wheel-unit correction: about 133s, 9 states/17
  frontier actions, incomplete control coverage. The VLM ledger contained only
  `app_focus`, `interruption_dismisser`, and `page_identity`: 48 logical calls,
  44 transports, 28 cache hits, and 90.548s model latency. It contained no
  inventory, block localization/identity, target grounding, or target review.
  Oracle validation exposed an Explore/Profile Page merge and incomplete scroll.
- The bounded rerun after the wheel correction finished in about 40s with 4
  states/3 frontier actions, 14 logical calls and 22.796s model latency. Router
  accepted one Back from Chat info as arrival at Chats although the live page was
  Weekend Plan, then marked Chats unreachable and stopped `frontier_empty`; the
  completion failures were `control_coverage` and `routing_reachability`. This is
  a remaining Page-identity/Router defect under correct inventory and grounding,
  not a recognition or coordinate failure. Artifacts:
  `artifacts/runs/mingle_logic_oracle_20260718/20260719/mingle` and
  `artifacts/runs/mingle_logic_oracle_scrollfix_20260718/20260719/mingle`.

### 2026-07-19 — target-independent Router page identity

- Removed the expected-target identity path, including the single-candidate
  `candidate_payloads([expected], ...)` branch. `VisualRouter` now invokes page
  identity with the current observation only after Back, planned hops, and
  derail recovery. Semantic identity judges the actual screenshot against the
  bounded stored-page candidates plus `NEW`; routing compares that result with
  the desired destination afterward.
- This directly addresses the observed false edge where a Back from Chat info
  landed on Weekend Plan but was labeled Chats because Chats was supplied as the
  expected target. Callback behavior changed; graph schema, persisted output,
  grounding, inventory, and final navigation-target selection did not.
- Files: `navigation/router.py`, `visual_engine.py`, focused Router/semantic
  identity tests, `design/modules/visual_traversal.md`, and this file.
- Verification (offline/static): `python -B -m pytest -q -p no:cacheprovider
  --basetemp artifacts/scratch/pytest_router_identity_target_independent
  tests/test_visual_router.py tests/test_semantic_inventory_grounding.py` ->
  `39 passed in 1.82s`; targeted `python -B -m py_compile` -> exit 0; targeted
  `git diff --check` -> exit 0 (only existing LF/CRLF conversion warnings).
  The first pytest attempt produced `34 passed, 5 errors` solely because Windows
  denied creation of the requested `C:\tmp` base directory; rerunning unchanged
  code with the workspace base directory completed. No emulator, device, live
  VLM, or live traversal is claimed by this change.
