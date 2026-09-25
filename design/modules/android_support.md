# Android 纯视觉适配

Android 与桌面共享视觉遍历、视觉 StateGraph、Router、capability 和未来 collection 契约。

2026-09-09：显式x/y的语义scroll以该点为真实触摸起点，不再向外偏移半个手势长度；端点限制在屏幕内。
未给锚点的旧请求保留居中手势，桌面wheel分支不变。模块化动作的amount按截图轴长转为既有frac，
表达一次手势的像素距离，不直接作为底层amount（手势次数）传递。模型仍须避开覆盖目标区块的独立悬浮控件。

## 2026-07-18 foreground 判定

`AndroidController.foreground_package()` 提供当前 activity 对应的 package；
`graph/mobile_ops.is_app_foreground()` 在 activity 信号存在时返回 `True/False`，
不可用时返回 `None`。视觉遍历的初始、settle、Back-dismiss 和 relaunch 检查都先用
这个本地信号，不再回退 VLM。`None` 时等待稳定后重读一次；仍不可用则以
`focus_unknown` 失败关闭，不登记截图，也不据此执行 Back 或 relaunch。

## 当前组件

| 模块 | 职责 |
|---|---|
| `env/android_gui_gen_env.py` | AVD 生命周期、snapshot、截图/terminal observation |
| `env/android_controller.py` | AndroidWorld/ADB 截图、点击、滑动、按键、文本、应用生命周期 |
| `graph/mobile_ops.py` | package/activity 映射、foreground/reset/launch 工具 |
| `ops/run_mobile_queue_traverse.sh` | seeded AVD 并发队列 runner；每 app 独立恢复、预算/超时覆盖、完成证书与失败汇总 |

The retired a11y graph traversal's callback-based `try_back_navigation` helper
is no longer part of this module. Current screenshot traversal emits the
normalized `navigate_back` action and verifies the resulting landing through
its ordinary execution/recovery path.

不再存在 Android UI-tree converter 或 tree observation。`AndroidWorldController(..., install_a11y_forwarding_app=False)` 是显式禁止上游安装辅助 app 的构造开关。

ADB daemon 是本机模拟器控制通道，不是宿主机互联网连接。目标 serial 不在线时，环境启动前会
重建一次 ADB daemon；截图异常时只进行一次有界恢复并重连 controller。该流程不操作网卡、DNS、
代理或模型 HTTP 连接，在线目标也不会在每次启动时被无条件重启。共享服务器运行可设置
`GUI_REWALK_ALLOW_ADB_RESTART=0`：环境仍可连接和精确关闭自己的 emulator serial，但启动/截图恢复
不得执行 `adb kill-server/start-server`，避免影响同账号或其他任务共用的 5037 daemon。

## 状态与动作

- 状态：截图 fingerprint + visual region-set/selected tab。
- 元素：VLM/OCR grounding 的像素 bbox/center。
- 点击/滑动：ADB/AndroidWorld action。
- 应用出现判定：foreground activity/task affinity。
- 系统栏：使用固定 status/navigation crop，不参与页面 hash。touch 长图拼接也把这两个 crop 作为最小 sticky 带，使每帧变化的时钟/信号/gesture pill 只在 composite 外缘出现一次；tiled grounding 按 stitch `y_map` 的源帧行再过滤，middle tile 不能产生系统 UI 元素。推断出的 app toolbar sticky 高度与固定 system band 分开保存，不会把真实 app chrome 剪掉。
- 临时浮层：dropdown/overflow/context menu/选项 popup 使用 `surface_kind=popup_menu` 与 active surface bbox；短非滚动 popup 记 static、0 swipe。其元素点击前主动 capture 最新 observation 并确认同一 overlay 仍存在，不能在 popup 消失后点击背景列表的同名/同位置项。

## Mingle 通讯应用 fixture

`app_name="mingle"` 对应仓库内 Android 包 `com.guirewalk.mingle/.MainActivity`。首次 launch 前，
`graph/mobile_ops.py` 通过当前 env 的 ADB 路径和 serial 执行
`adb -s <serial> install -r synthetic_mobile_app/mingle-debug.apk`；成功后，同一 AVD 会话不重复安装。
Mingle 已加入可清数据白名单，因而 `--clean_start` 清除它的本地状态，而 resume、Focus Guard 和
Router restart 继续使用保留数据的 kill/launch 路径。

fixture 的真值位于 `synthetic_mobile_app/oracle.json`：8 个 Page、42 个页面级 control、3 个长页面、
3 个 active surface，并覆盖聊天列表、长会话、联系人、个人页、设置、新建聊天、附件和确认 dialog。
`inspector.html` 供人工查看，`validate_graph.py` 对比实际图，17 个无坐标 legacy observation 通过
parser 的 block/element 兼容入口测试语义归一化；它们不是当前 live `areas/controls` Prompt 的原始回复。
真实运行不读取 oracle；这些 fixture 工具不改变图 schema、Router、
completion policy 或生产应用适配边界。

## Settings/批量 runner 边界

`ops/run_mobile_queue_traverse.sh` 默认每 app 使用 300 states、1200 actions 和 14400 秒 wall-clock
预算，可由 `GUIWALK_MOBILE_*`、兼容旧环境变量或命令行参数覆盖。每个 app 必须传
`--require_complete`；boot 失败、timeout 或 `completion.json` 未认证都会令对应 worker 及总进程非零。
脚本只有所有 app 都通过时输出 `[ALL CERTIFIED]`，失败汇总只能输出 `[ALL INCOMPLETE]`，不能把
“队列已取空”描述成“遍历完整”。并发实例使用 5612 起的独立偶数端口，不应杀死或复用未纳入本轮的
emulator。

Android controller 连接时，第三方 loader 的 INFO 日志不得输出整个进程环境。当前 env guard 在
`loader.load(config)` 期间临时把 absl verbosity 提升到 WARNING，并在 `finally` 恢复；历史日志若已
暴露凭据仍需轮换凭据并限制/清理日志。

## MobileWorld 外部 ADB 入口

`tools/mobileworld_external_env.py` 是显式实验入口，用于把模块化 Explore Kernel 连接到调用方已经启动的
MobileWorld 容器模拟器。它不创建、停止、清数据或恢复容器/AVD，只控制命令行指定的转发 ADB serial；容器生命周期、
后端和初始快照仍由官方 MobileWorld CLI 所有。Luna transport 在宿主机运行并读取既有 Git-ignored 私有 YAML，
API key 不复制进容器。

该工具只列官方 15 个 GUI 应用；`MCP-Amap/Github/arXiv/jina/stockstar` 是工具服务，不冒充可遍历 GUI 应用。
每个 app 单独输出一个模块化账本和 completion，顺序运行器必须在每个 app 后独立检查 Region/Operation 重复、
owner、Transition、滚动、gap 和 token，不能把“队列跑完”当成全部应用完成。`docreader` 没有官方直接 launcher
映射，必须从 live 镜像解析真实打开路径后才能运行，不能猜包名。

## Local Android web mirror (2026-08-30)

`tools/android_web_mirror.py` is a standalone local inspection/input bridge for
one already-running Android device. It requires an explicit `--adb`, `--serial`,
and `--port`; `--host` defaults to `127.0.0.1` and only accepts that loopback
address or `localhost`. `GET /` serves the single-page mirror, `GET /frame.png`
uses `adb -s <serial> exec-out screencap -p`, and the page refreshes at the
bounded `--refresh-ms` interval.

The mirror fits the full frame inside the available browser width and height,
with a separate toolbar above it. Display scaling preserves aspect ratio;
screenshots retain their original pixels and input coordinates are mapped from
the displayed image bounds back to its natural dimensions.

The browser can submit only JSON integer tap/swipe coordinates and the three
fixed Back/Home/Recents key names. The service rejects malformed, out-of-range,
or extra fields and maps accepted requests to fixed argv ADB commands; it does
not expose a shell, text entry, arbitrary keyevents, authentication, or a
network listener beyond loopback. This convenience tool does not create,
restart, stop, seed, or otherwise own the emulator. Its offline tests do not
prove a live ADB connection, browser input mapping, or emulator behavior.

## 验证

离线边界由 `tests/test_architecture_boundaries.py` 覆盖；loader 日志 guard 由
`python -B tools/test_android_env_log_guard.py` 覆盖（2 tests，OK）。2026-07-12 对 queue runner 运行
`bash -n ops/run_mobile_queue_traverse.sh` 通过；这只是静态语法验证。真机修改还需在调试台核对
screenshot、grounding、动作、落地状态、attempt、commit 与完成证书。

2026-07-12 另运行 `python -B tools/test_visual_stitch.py`，合成回归证明 6 帧动态 Android 系统栏只保留一个 top 和一个 bottom copy、composite seam 中系统 provenance 行为 0，且 middle tile 的人造系统元素被全部过滤而三个 app 元素全保留；`python -B tools/test_stitch_node_integration.py` 也 PASS，覆盖 short/tall 引擎接线、tiled merge 和 viewport 坐标回映。`test_system_ui_band.py`、`test_architecture_boundaries.py` 和相关 `py_compile` 的逐次结果以对应变更日志为准。以上均是本机离线/合成验证，未启动 emulator 或真实 VLM，不能替代 Android Settings live 认证。

2026-07-12 popup 门禁离线运行 `python -B tools/test_popup_surface_guard.py` 通过，覆盖 active-surface 解析/元素绑定、0 swipe static ledger 和点击前 overlay 存续核对；相关 modal/rebind/run-state 测试亦通过。本批次没有操作 emulator，也没有调用真实 VLM，不能替代 Notifications 排序菜单的 live 复测。

2026-07-18 Mingle 验证包括 Android debug APK 编译、headless Chromium 导航/状态/浮层/滚动 smoke、
current-prompt parser fixture、安装生命周期单元测试和 8 张参考图。运行时未发现已连接 AVD，因此没有
执行真实 Android 点击、真实 Qwen/VLM、live traversal 或 completion certificate；不能据离线结果宣称
移动端遍历已认证。

2026-07-19 本机可见 `Small_Phone` AVD 验证了新的 ADB 恢复路径：目标在 daemon 重建后重新上线，
`AndroidGUIGenEnv` 随后取得实时截图；同一时刻模型服务 443 仍可连接。这证明控制通道恢复不会重置
宿主机网络，但不等同于新的完整遍历或真实 VLM 弹窗识别验收。

## AndroidWorld-native traversal actions (2026-07-19)

`AndroidController.execute_gui_action()` now accepts AndroidWorld JSONAction
names directly in addition to the historical common aliases. In particular,
`swipe` preserves AndroidWorld finger-direction semantics, while `scroll`
preserves content-direction semantics. `keyboard_enter`, `navigate_back`,
`navigate_home`, and `open_app` translate to the existing ADB primitives. The
graph keeps the original native action; translation occurs only at dispatch.

Qwen autonomous now exposes `input_text(target, point_1000, text)` only during
`probe_region`. The existing Click Reviewer must approve the visible input field
and exact non-sensitive query text. The writer emits native AndroidWorld
`input_text` with current-frame `x/y`; `AndroidController` taps that point before
typing. It never presses Enter and does not turn the input into an Entry. This is
covered only by offline controller/runtime contracts so far; no fresh emulator
or Qwen acceptance is claimed.
