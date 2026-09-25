# 环境、VLM 与应用生命周期

2026-09-19：Android环境初始化（含attach）和reset后统一写入并读回show_ime_with_hard_keyboard=0；失败明确报错，不静默沿用允许软键盘的设置。仅抑制有硬键盘环境的默认弹出，不卸载/禁用输入法，不修改历史截图或图。授权实例5690/5692本次均由1改为0并读回确认；默认AVD已为hw.keyboard=yes。

## 专用VLC实验的前景重绘

2026-09-10 full batch8/9再次出现Simple标题/选中状态和旧Advanced内容混合。root xrefresh未使实际客户窗口完整重绘；独立All→Simple诊断中，等待3秒和root刷新后仍见同一旧内容。对`_NET_ACTIVE_WINDOW`指向的X11客户窗口执行`clear_area(exposures=True)`、同步、关闭Display后等待0.5秒，正确Simple内容恢复；又一次往返最终PNG与起始相同。证据位于artifacts/traversal_goal_20260909/preferences_simple_timing_probe、preferences_client_expose_probe和preferences_client_repaint_validation。

此措施仅进入run_vlc_full_live_batch10.py的AttachedDesktop实验采样准备，没有修改DesktopGUIGenEnv默认、应用设置、通用Prompt或图片像素。4次操作员模式点击单独记录、0模型调用、不计遍历。Luna随后真实恢复Native并打开Force window style菜单，保存后图保留三个菜单项；其他前景和长时稳定性仍须实际验证。它和下述X11连接泄漏修复是不同问题，不能用连接数量稳定证明图像内容已正确。

## OSWorld X11 请求连接释放

`ops/fix_osworld_x11_connections.py <guest-server/main.py>`为Linux尺寸和截图光标两条路径释放每次请求创建的连接：get_screen_size使用finally Display.close，capture_screen_with_cursor在复制光标像素后finally XCloseDisplay。空光标连接不进入本地X11调用。工具先验证目标代码块、编译补丁并备份原文件，已修复块不重复修改；未匹配时拒绝。

2026-09-10首次仅修复尺寸接口，20次尺寸请求7→7 socket，但未覆盖截图路径；之后截图中的Xcursor对象再次累计235个连接而达到Xorg上限。工具已从原尺寸专用脚本更名并补齐截图释放，当前worker15102在20次截图+20次尺寸联合验证中socket7→7，20张PNG均有效，VLC PID5630和暂停现场保留。证据x11_cursor_and_size_validation.json。两次均由Werkzeug自动重载worker，未重启VM、VLC或整个systemd服务组。

这是当前guest的修复工具，不代表其他OSWorld镜像自动修复；其它未用端点的连接生命周期及完整内存使用未在此任务验证。

## 当前 observation

桌面与 Android 环境只返回：

```python
{"screenshot": bytes, "terminal": str | None}
```

环境不请求、不转换、不返回 accessibility tree。

### Android loader 日志安全边界

第三方 `android_env.loader` 不得通过 INFO 日志输出整个进程环境；进程环境可能包含 API key、token、
密码或私有端点，不能把上游日志实现视为可信的凭据边界。`AndroidGUIGenEnv._connect_controller()`
在调用 `loader.load(config)` 期间临时把 `absl.logging` verbosity 提升到 `WARNING`，并在 `finally`
中恢复进入 loader 前的原始 verbosity；因此正常返回和 loader 抛出异常两条路径都不会遗留全局日志级别修改。
该 guard 只保护当前及后续受控运行，不会追溯清除已经写入的历史日志。若历史运行曾记录进程环境，
必须轮换可能暴露的凭据，并限制相关日志访问、按组织的数据保留规则清理副本。

## 桌面截图传输完整性

`env/osworld_reload.py` 不再把任意 HTTP 200 当成可用截图。每次响应先用 PIL `Image.verify()`
验证 payload 是完整可解码图像；空响应、HTML、截断 PNG 或其他损坏内容会在既有重试预算内重取，
只有有效图才更新连接成功状态。全部失败时返回 `None`，上层以 `perception_unavailable` fail-closed，
不得把坏 payload 注册成空页面或伪造边。日志只写 attempt、字节数和 content-type，不写 payload。

现场根因是 guest `/screenshot` 使用固定 PNG 文件，并发请求可能在写入尚未完成时读取。controller
校验解决的是恢复与隔离，不等于消除 guest 端竞争；同一 VM 上仍应避免遍历和人工监控并发抓图。
`tools/test_screenshot_payload_recovery.py` 覆盖 valid、empty/HTML/truncated、corrupt→valid 重试和全坏返回 `None`。

## gui_gen_agent.py

当前是约 220 行 screenshot-only VLM transport：

- `predict_mm(text, images)`
- `predict_mm_with_policy(text, images, max_attempts, timeout_seconds)`：按角色设置尝试数与 timeout；grounding 当前为单次 150 秒，普通语义 role 保持默认 75 秒
- 每请求显式 timeout，client 内部 retry 关闭，由外层做 3s/6s 有界退避
- Ark 与 DashScope-compatible backend
- `parse_json()` 与 `reset()`

旧 screenshot+A11y/A11y-only/SoM observation 分支和对应 prompts 已删除。默认 Qwen/Ark transport 的凭据只从环境变量读取；源码没有可用默认 key。

### 模块化探索的本地 OpenAI-compatible 配置

`--modular-explore --explore-backend openai_api` 是独立显式后端，只读取仓库根目录
`.guiwalk.local.yaml`。该文件以 `/.guiwalk.local.yaml` 精确规则被 Git 忽略，当前合同为：

```yaml
version: 1
explore_api:
  base_url: https://api.zhizengzeng.com/v1
  api_key: ""
  model: gpt-5.6-luna
  reasoning_effort: medium
  timeout_seconds: 300
```

`api_key` 由用户只在本机明文填写；它不会写入 Prompt、调试 JSONL、文档默认值、源码或环境变量。
loader 要求 version 1、HTTPS base URL、非空 key/model、受支持的 reasoning effort 和正整数 timeout；
任何缺失或非法值都在 live monitor、VM、模拟器和目标 App 启动前返回。有效配置只作为当前进程内的私有
`args` 值传给模块化 runtime，不读取或修改 CC Switch、`~/.codex`、`CODEX_HOME`、`OPENAI_API_KEY`
或 `OPENAI_BASE_URL`。明文文件仍可被同一机器上有权限的其他进程读取，Git ignore 只防止误提交，
不构成操作系统级密钥保护。

## app_lifecycle.py

提供桌面/Android 统一的 launch、wait、reset、foreground、window bbox、cache clear。桌面启动
先用 `wmctrl` 拉起目标窗口，再把实际 active X11 窗口 ID/PID 绑定为本次运行的
`DesktopWindowOwner`；后续通过 `_NET_ACTIVE_WINDOW`、PID 和 `WM_TRANSIENT_FOR` 判断窗口
归属，不解析 UI 树。只有窗口管理器证据不可用或首次绑定无法确认时才调用截图 appear checker，
并在其确认后绑定当前窗口。首次绑定最多进行 3 次系统轮询，以覆盖窗口尚未列出或已被
`wmctrl` 抬起但 active-window 属性尚未更新的短暂竞态。桌面窗口拉起使用 `wmctrl -lx`
同时匹配 WM_CLASS 与标题，因此 Files 的 `Home`、Terminal 的 shell 路径等通用标题仍可通过
既有 `APP_WINDOW_NAME_MAP` 类名绑定、激活和最大化。Android 使用 foreground
activity/task ownership。

启动语义必须区分：

- `startup_reset_app()`：kill + 清缓存/应用状态 + launch；只在全新遍历显式传 `--clean_start` 时使用。桌面端可传现行可选 `desktop_window_owner`，让 launch/wait 绑定并核验目标应用窗口。
- `restart_app_preserving_data()`：kill + launch，不调用 cache clear；用于普通续跑启动、Focus Guard/off-app 恢复和 Router hard reset，保留当前运行中普通创建或保存动作产生的数据，使后续页面状态仍可到达。显式续跑 Android 时，若系统前台证据确认请求包仍在前台，入口跳过会返回主屏幕的环境 reset，并直接保留当前操作界面，不执行 kill/launch；前台不属于请求包或证据不可用时仍按原 reset 与重启路径恢复。

独立遍历不再构造 domain prerequisite resolver，也没有 `--no_discovery_prerequisites` 开关。Create/Add 是普通 frontier 控件，创建、编辑、保存和删除等中间页面逐个登记；遍历不会预先生成“若资源不存在则创建”的任务分支。`--clean_start` 只控制 fresh traversal 是否先清目标 app 数据，默认保留已有数据以暴露更多页面变体。

M13 app switch 也只 launch/foreground，不清应用数据。M13 仍保留独立的 `PrerequisiteRuntime`/`VisualPrerequisiteAgent`，可为待执行 capability 绑定或创建前置资源并只清理本轮拥有的资源；这不是遍历 CLI 的默认行为。

### Dayline desktop fixture

桌面环境提供仓库自带的确定性应用，推荐入口为 `app_name="dayline"`，旧名
`app_name="rewalk fixture"` 仅作兼容。它不是生产应用适配，
而是纯视觉框架的已知真值 fixture：8 个语义 Page、30 个 block、43 个 control、3 个长页、
共享桌面 sidebar、参数化列表、可逆状态、popup 与 dialog 都有机器可读 oracle。面向用户的
Dayline UI 使用 1365×900 宽屏工作区、左侧导航和日常文档/活动/周报/设置文案，不显示测试术语。
Oracle 的 block ID 必须与页面运行时 `data-block` 完全一致；当前详情页和周报页 app bar 分别为
`record_detail.app_bar` 与 `coverage_report.app_bar`。fixture 构建器会把这组真值同步到单文件应用、
inspector 和 Qwen-shaped 回复，图验证器再独立核对页面、控件与跳转覆盖。

`launch_app()` 在启动前读取 `synthetic_app/index.html`，经现有 guest Python 执行通道写入
`/tmp/gui_rewalk_fixture/index.html`，然后用最大化的 Chrome app mode 和独立
`/tmp/gui_rewalk_fixture/profile` 启动。该路径不依赖公网或 host→guest 文件共享。
`--clean_start` 只删除 fixture profile；同一 run 的 data-preserving restart 保留其 localStorage
状态。普通 Chrome profile 和其他应用数据不在此清理范围内。

`synthetic_app/qwen_responses.json` 保存 15 个无坐标的 legacy block/element 回复；每个 block 明确
`scope=target_app` 和 `interaction=direct`，通过现有 parser 的兼容入口测试语义归一化与 active-surface
排除。它不是当前 live `areas/controls` Prompt 的预期原始输出。真实运行仍调用原 prompt/模型，不读取
oracle；`QwenFixtureStub` 只供显式选择已知 observation 的离线 parser 测试，不能冒充 live Qwen 验证。

### Mingle Android fixture

Android 环境另提供仓库自带的通讯应用 `app_name="mingle"`，包名
`com.guirewalk.mingle`，入口 `.MainActivity`。`synthetic_mobile_app/mingle-debug.apk` 是 WebView
包装的离线 APK；`mobile_ops.launch_app()` 在当前 AVD 会话第一次启动 Mingle 前执行
`adb install -r`，成功后在该 env 上记忆已安装状态。普通 restart 保留应用数据；由于 Mingle 在
`ANDROID_CLEAR_DATA_APPS` 白名单内，显式 `--clean_start` 可执行 `pm clear`。

`synthetic_mobile_app/` 同时保存 8 Page、42 个页面控件、3 个长滚动范围、3 个 active surface 的
oracle、人工 inspector、17 个无坐标 legacy parser 回复、graph validator、Playwright
smoke/reference capture 与 Android 工程。真实遍历继续调用当前 `areas/controls` prompt/模型，不读取 oracle；APK 编译、
headless 浏览器和离线 parser 测试不能替代已连接 emulator 上的真实 Qwen、点击与完成证书验证。

### Local HTML visual backend

`--vm_provider local_html --html_path <file>` 使用 `LocalHTMLGUIGenEnv` 在 headless Chromium 中直接
承载仓库内 HTML fixture。`--local_html_start_hash '#/<route>'` 可显式选择初始路由，默认保持
`#/inbox`；非法或带空白的 hash 在浏览器启动前失败关闭。该环境只向引擎提供固定视口 PNG、像素
click/type/press/scroll/drag/back、重载和关闭；Playwright 不参与 DOM 感知、元素定位、Page 身份、
Router 或 oracle 比较。Mingle 推荐显式传 `--screen_width 412 --screen_height 915`，未传
`--html_path` 且 `app_name=mingle` 时使用 `synthetic_mobile_app/index.html`。

`--autonomous_test_target_edge 'SOURCE_PAGE::VISIBLE_TARGET::EXPECTED_DESTINATION'` 只在
`--autonomous-agent + local_html` 的 fresh run 中可用。它不向模型注入 DOM/oracle，也不替模型发现或
定位按钮；只在 Agent 登记入口后把非目标入口从本轮调度中排除，并用真实 verified 动作和已登记落点
给出单边通过/失败。该诊断不生成全遍历完成证书。

`--autonomous_fixture_audit` 是另一条仅用于仓库 fixture 的运行后取证通道。它兼容
`window.__mingle.snapshot()` 与四个快测页的 `window.__fixture.snapshot()`，在每个真实动作前后记录
真实 fixture Page、命中的 `data-action-id`、外层/独立容器滚动位置、访问序列和 Back 来源状态。
这些字段只写入 `autonomous_trace.json.fixture_audit`，不进入截图、Prompt、Page Identity、Region
登记、grounding 或调度。`traversal_test_app/scripts/test_*.ps1` 的 `acceptance` 模式在运行结束后
用这些真值与框架的 Page/Region/entry/ActionEdge 账本交叉生成 `quick_acceptance.json`。

此后端不构造 Desktop/OSWorld 或 AndroidWorld 环境，不启动 VM/AVD，也跳过桌面 60 秒启动等待和
应用生命周期安装。它用于快速隔离验证 screenshot/VLM、像素 grounding、StateGraph、Router、滚动
账本与 completion；不验证 Android 系统栏、ADB、触控惯性、权限弹窗或平台生命周期，因此不能替代
最终移动平台 smoke。`env.close()` 会关闭 page、context、browser 和 Playwright driver，不留后台实例。

`traversal_test_app/panel_combinations.html` 是 Page/Region 组合压力 fixture：四个主要 Page 共用导航和
状态栏，Library 与 Inspector 可独立显示，Analytics 另有前景 Quick Review Sheet；可见主路径在途中
逐步增加这些 Region，经过 Records、Analytics、Settings 后以不同 Region 组合返回同一个 Home Page。
`window.__fixture` 与 `oracle.json` 只供运行后的离线真值检查，不进入截图、Prompt、Page/Region 身份、
grounding 或调度。该 fixture 用于诊断 Page 误拆分、共享 Region 复用、前景 Surface 独立性和长距离旧 Page
重识别，不包含任何应用专用 Prompt 规则。

Local HTML 默认仍是 screenshot/pixel-only。调试时可独立设置
`--fixture_oracle_inventory on|off` 与
`--fixture_oracle_grounding on|off`（默认均为 `off`）。前者提供当前可见的
fixture 真值区块/元素并跳过 semantic inventory、block localization、block
identity；后者提供当前帧真值点击坐标并跳过 target grounding 与 target
reviewer。Page/Variant、Router、frontier、scroll ledger 和 completion 仍走框架
原逻辑。oracle inventory 为每个实际可见区块提供当前视口内的归一化 bbox；普通
navigation/input/stateful 控件默认是 `risk=none`，只有显式 dangerous 且未给出
risk 的控件保持 `unknown`。完成真实滚动 sweep 后，诊断路径可请求已扫过 surface
的完整控件清单及文档坐标，但这不会替代滚动、截图或完成证据。两个开关用于其他
provider 时 fail closed。Local HTML 将框架 `dx/dy`
滚轮格数按每格 100 Playwright 像素换算，避免 8px 小位移被误判为 static。

### VMware provider 生命周期边界

应用级 `data-preserving restart` 与 VM provider reset 是两层语义。普通 fresh 和旧模式 resume 仍执行
`env.reset()`；模块化 resume 若能把当前 active desktop window 精确绑定为目标应用，则跳过 snapshot reset 和 app relaunch，
保留当前 surface。绑定失败时仍走原 reset 加 data-preserving restart，随后只按真实新截图定位 State，不猜测旧位置。
VMware provider 对需要 reset 的已使用环境先回滚 `init_state` 快照。入口 `finally` 调用 `env.close()` 并停止 VM。
`--clean_start` 只决定回滚后的 app cache/data

视觉入口可选 `--vlm_response_cache <directory>`。该目录属于模型调用层，不属于
Local HTML、Android 或桌面环境状态；默认关闭。开启后仅精确复用角色、模型参数、完整
prompt 和截图像素全部一致的原始回复，因此 prompt 修改会自然失效，不需要手工清缓存。
是否清理，不控制快照回滚；当前没有 `--no-revert` 或 `--keep-vm-running` CLI。因此不能把“保留 app data”
描述成跨独立 CLI 调用保留 VM 当前 delta。Router/focus 在同一 run 内的 restart 才共享该 run 的状态。

## config.py

保留应用二进制、窗口别名、Android package/activity、裁剪和种子数据配置。`APP_WINDOW_NAME_MAP` 只表示桌面窗口/进程别名。
桌面 `APP_SEED_FILE` 是 best-effort：guest 生成脚本必须在 controller 输出中明确返回 `seed_ok`，生命周期才把种子路径附加到
启动命令；`seed_fail`、空输出或不支持的文件类型都回退为只启动应用本体，不能把不存在的路径传给应用并制造错误页。

## GUITRAVERSE 移动开发基线

`data/dev_seed/guitraverse_mobile_seed_v1.yaml` 是当前合成移动 seed 真值，
`tools/guitraverse_mobile_seed.py` 提供 `plan/apply/verify/snapshot-save/snapshot-load`。工具只接受
`emulator-<port>` 和专用 `guitraverse_mobile_seed` AVD；写操作的确认串必须与版本化 profile/snapshot
完全一致。它在写入前核对 boot、locale 和 required package；普通遍历恢复仍只使用
`restart_app_preserving_data()`，不会调用该 seed 工具或 `pm clear`。

seed 报告写到 `artifacts/guitraverse_seed_reports/<profile>/`，不进入 traversal run root、Attempt、
Capability 或指令轨迹。当前只有 manifest/fake-ADB/plan 的离线验证；真实 provider 写入和 whole-AVD
恢复仍须单独 live 验收。

2026-08-30 已在 js1 专用 `guitraverse_mobile_seed` AVD 发布
`guitraverse_mobile_seed_v1`：manifest digest
`35482990e5290fd3d9bf0e880f35a6436a10a8dd6397cd3cad93ce2f5fa2e94a`，system/contacts/files/
messages/calendar/photos 独立 verify 全 true。read-only run A 的 airplane/file 扰动在 run B 中完全恢复。
该证据只验收 out-of-band 环境基线和 overlay 隔离，不计入 GUI trajectory 或 Capability evidence。

`run_visual_traversal.py --android_snapshot_name <name>` 显式把 whole-AVD snapshot 传给
`AndroidGUIGenEnv(snapshot_name=..., boot_from_snapshot=True)`。环境只在该 opt-in 模式给 emulator 添加
`-snapshot <name>`，空 snapshot 仍保持旧的 cold/default 选择语义；两种模式都继续使用
`-read-only -no-snapshot-save`。如果指定
console port 已有设备，或新设备启动后，环境都会通过 `adb emu avd name` 核对精确 AVD，错误/空结果
均在 controller attach 前失败。`ops/run_guitraverse_seeded_mobile.ps1` 固定上述只读组合，`-PlanOnly`
可在不启动 emulator、模型或应用的情况下审计完整 argv。
Android read-only 实例统一增加 `-feature -Vulkan`（禁用 Vulkan feature），与 seed 保存时的 renderer
合同一致，避免 VLC/snapshot 因 Vulkan 状态不一致而不可保存或加载；软件 GPU 仍为
`swiftshader_indirect`。
Named-snapshot run 现在要求目标 serial 启动前未被占用；ADB 列表中 `device/offline/unauthorized` 等任一
状态都算占用。同名 AVD 已在线也不复用，因为框架无法证明它
仍处于请求的 snapshot 基线。该 run 自己启动的 read-only emulator 在 `close()` 时始终终止；启动超过
`boot_timeout` 仍未 ready 时也先 terminate、必要时 kill 自己的 `Popen` 子进程再抛环境错误。普通未指定
snapshot 的 run 继续沿用“默认保留 emulator，显式 `GUI_REWALK_KILL_EMULATOR=1` 才关闭”的旧行为。
Named-snapshot `close()` 是幂等的；丢失 owned Popen 句柄后不退回按 serial 终止。这保证逐 App遍历/
逐 instruction collection 从 fresh overlay 开始，同时不会按名称终止其他 QEMU。
同一 owned read-only overlay 在 controller attach 后安装并选择仓库锁定的 Appium Settings v7.1.3
`UnicodeIME`；APK SHA-256 固定为
`16af5bb042573f300755ce09c84811ef9f2ffc585a3ed0b930a44c599df2fa32`，缺失、hash 不符、安装失败或默认
IME 未切换都会让环境启动失败。helper 状态随 QEMU overlay 销毁，不写回 named snapshot，也不影响普通未指定
snapshot 的 Android run。文本仍由现有 AndroidWorld ADB request 注入；helper 不创建输入视图。

Android `input_text` 在 controller 投递前拒绝非 ASCII，且不先 tap、clear 或输入前缀；错误码
`input_text_unsupported_non_ascii` 随本次 `env.step()` observation 返回给模块化 runtime。ASCII 输入、
默认 clear-before-replace 与其他平台输入路径不变。
`AndroidGUIGenEnv.is_soft_keyboard_visible()` 只读调用 `dumpsys input_method`，仅解析当前
`mInputShown/mInputViewShown/mIsInputViewShown` boolean flag；无法取得支持的 flag 时返回 unknown，不猜测。
当前方法为 pinned `UnicodeIME` 时，即使 Android 内部 `mInputShown=true` 也按无可见键盘处理，因为该 IME 不创建
input view；其他 IME 仍按 shown flag 判断。模块化 runtime 只在明确有可见键盘时阻止 scroll，查询本身不隐藏键盘、
不执行 GUI 动作。
`has_active_text_input()` 同时读取当前 `mServedInputConnection`；named-snapshot controller 用它决定 input_text
是否可跳过 tap，以及 tap 后能否继续 clear/type。焦点状态 unavailable 或 tap 后仍非 active 时 fail closed。
js1 最小 live probe 在 v1 read-only 实例上请求非 ASCII input，收到该错误码且 before/after screenshot
SHA-256 相同；该证据只验证投递前拒绝，不证明应用内任意 Unicode 输入需求已得到替代支持。

## Local deployment entry

`run_local_visual.ps1` is the portable Windows launcher for the active desktop
visual traversal. It derives the repository, OSWorld, OmniParser, and VM paths
relative to itself; it requires `DASHSCOPE_API_KEY` from the current process
environment and has no credential or machine-specific path default. The VM and
model weights remain external artifacts; see `DEPLOY_LOCAL.md`.

## Remote run evidence retrieval

`ops/pull_remote_run_evidence.ps1` is the Windows entry for copying completed
remote-run evidence into local `artifacts/`. It packages only `results/` plus
root-level `*.log`, `*.exit_code`, `*.started_at`, and `*.finished_at` files.
Before transfer it rejects symbolic links in `results/`, enforces a default
5 GiB uncompressed/archive limit, and checks local free-space headroom. It never
uses recursive SCP and never includes the remote `repo/`, `OSWorld/`, or source
archives. This prevents a remote runtime symlink from dereferencing VMware data
or a self-referential `OSWorld/OSWorld` link during evidence collection.

`run_visual_traversal.py` also exposes the opt-in, perception-only experiment
`--block_first_inventory [--target_block <id-or-role>]`. With no target it writes
`block_discovery.json`; with a unique target it additionally writes
`selected_block_crop.png` and `block_inventory.json`. It is not accepted as a
full-traversal mode and does not change desktop, Android, Local HTML, lifecycle,
graph, or completion behavior.

The optional `--block_image_mode full` sends the complete screenshot for the
second stage and writes `selected_block_full.png`; `crop` is the default. This is
an input experiment, not an environment capture mode or production traversal
default.

`--block_image_mode context_crop` sends the complete screenshot followed by the
selected crop and writes both `selected_block_context_full.png` and
`selected_block_crop.png`. The mode affects only the experimental model request;
it does not change environment screenshots or graph artifacts.

## 2026-07-10 修改

- 从旧 traversal 抽出 lifecycle 后，进一步删除兼容 re-export 和所有 UI-tree fallback。
- 删除 Android tree converter/forwarder 安装逻辑；AndroidWorld 上游构造显式传 `install_a11y_forwarding_app=False`，用于阻止安装。
- `tools/test_architecture_boundaries.py` 检查 active env 源码没有 `accessibility_tree/get_accessibility_tree`。

## 2026-07-11 修改

新增 data-preserving restart，并将独立遍历的 fresh/resume/异常恢复与 M13 app activation 从“可能清状态”的 reset 语义分离。`run_visual_traversal.py` 默认保留已有资源，只有 `--clean_start` 显式清 app state。离线 `python -B tools/test_app_lifecycle_preserve.py` 验证调用顺序只有 kill/sleep/launch/wait/maximize。

同日补充 HTTP-200 截图内容校验与恢复测试，并真实运行 Settings fresh/resume 小预算遍历。现场确认 provider 会回滚 `init_state` 且 CLI 结束停 VM；app-preserving restart 本身尚未做“预置资源跨 relaunch 保留”的独立专项 live 验收，Android 生命周期也仍待 live 验证。

## 2026-07-11 修改

- 遍历 CLI 移除 discovery prerequisite flag 和默认 resolver；Create/Add 改为普通能力覆盖 frontier。M13 的 prerequisite runtime 保持独立并继续可用。
- `--clean_start` 帮助文本改为“显式清 app 数据；默认保留已有数据以观察额外 Page/Variant”，不再暗示遍历会执行任务式 prerequisite recipe。
- 离线运行 `python -B tools/test_capability_driven_frontier.py`、`python -B tools/test_discovery_seed_runtime.py`、`python -B tools/test_architecture_boundaries.py`、`python -B tools/test_prerequisite_runtime.py` 与 `python -B tools/test_visual_prerequisite_agent.py`，均通过；后两者分别为 11 tests 和 12 tests。
- 本次未启动 VM、Android emulator 或真实 VLM；普通 Create/Add 资源跨 relaunch 的 Clock/Alarm live 验收尚未完成。

## 2026-07-12 修改

- 为 Android controller 连接增加第三方 loader 日志 guard：`loader.load(config)` 期间临时将
  `absl.logging` verbosity 提升到 `WARNING`，并通过 `finally` 恢复原值，禁止上游 INFO 日志泄露整个进程环境。
- 离线运行 `python -B tools/test_android_env_log_guard.py`，共 2 tests，结果 `OK`；另以
  `python -m py_compile gui_rewalk/env/android_gui_gen_env.py tools/test_android_env_log_guard.py`
  完成静态语法验证并通过。
- 本轮没有启动 Android emulator、真实 Android Settings 或 VLM，以上结果不是 live/runtime 验收；
  历史日志若曾暴露凭据，仍需轮换凭据并限制访问、清理日志副本。

## 2026-07-18 修改

- 新增 `rewalk fixture` 桌面应用生命周期配置与 guest 内单文件安装；新增独立 profile 清理边界，
  不改变现有应用 launch/reset/restart 语义。
- 新增 `synthetic_app/`：App、oracle inspector、Qwen-shaped expected responses、离线 stub、
  graph validator、Playwright smoke/reference capture 与使用说明。
- 验证：`python -m pytest -q tests/test_synthetic_fixture_app.py
  tests/test_app_lifecycle_preserve.py --basetemp artifacts/scratch/pytest_fixture_app_qwen`
  -> `4 passed in 1.03s`；对新增/受影响 Python 文件的显式 `python -m py_compile ...` -> exit 0；
  `python synthetic_app/smoke_test.py` ->
  `PASS fixture navigation/state/overlay/scroll smoke`；`capture_reference.py` 成功生成 7 张参考图，
  并人工检查 Home、Library/Activity 长图、popup、dialog 与 oracle inspector。
- 以上是本机 headless Chromium、离线 stub 与静态/单元验证；未启动 VMware、未执行真实 Qwen/VLM、
  未跑 live traversal，也未宣称 fixture graph 已通过 completion certificate。

## 2026-07-18 修改（Dayline 桌面外观）

- 将应用可见层改为 Dayline 日常桌面工作区：宽屏 sidebar、顶部工具栏、文档列表、活动流、周报、
  设置和产品说明；内部 Page/control/action ID、数量和覆盖结构保持不变。
- 新增推荐生命周期入口 `app_name="dayline"`，窗口识别使用 `Dayline`；旧
  `rewalk fixture` 入口、相同 guest 安装目录与独立 profile 清理边界继续兼容。
- oracle、15 份 Qwen-shaped 回复、Playwright 流程和参考图同步到新的可见文字，未修改
  `SEMANTIC_INVENTORY_PROMPT` 或 parser contract。
- 验证：`python -m pytest -q tests/test_synthetic_fixture_app.py
  tests/test_app_lifecycle_preserve.py --basetemp artifacts/scratch/pytest_dayline_desktop_final2`
  -> `4 passed in 1.01s`；受影响 Python 文件显式 `py_compile` -> exit 0；
  `python synthetic_app/smoke_test.py` -> `PASS Dayline navigation/state/overlay/scroll smoke`；
  `capture_reference.py` 重新生成 7 张 1365×900/全页参考图并人工检查 Home 和 Documents 长页。
  未启动 VMware，未调用真实 Qwen/VLM，也未执行 live traversal/completion certificate。

## OSWorld-native return actions (2026-07-19)

The desktop `gen_data` controller accepts native OSWorld `computer_13`
spellings used by return verification, including `RIGHT_CLICK`, `DOUBLE_CLICK`,
`DRAG_TO`, `TYPING`, and `SCROLL` with `dx/dy`, while retaining older aliases.
Native recipes are stored on verified graph edges and translated only by the
environment adapter at execution time.

## Mingle fixture state semantics (2026-07-23)

Mingle stateful controls declare `effect_scope` in the oracle. The Local HTML
adapter passes that field through and uses `unknown` when it is absent; it does
not classify every stateful control as `function_set`. Search is currently
`function_set`, while favorite, message notifications, and mute are `data_only`.

Fixture inventory retains read-only identity anchors, Regions that are scrollable
but contain no interactive control, and explicit oracle group/state/effect fields.
After a real Region sweep, the matching full-surface fixture inventory can be used
without a VLM long-image inventory call. These behaviors are diagnostic fixture
truth and do not change the formal screenshot/VLM inventory contract.
