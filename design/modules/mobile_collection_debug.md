# 移动端轨迹采集调试台 (mobile collection debug)

交互式单步调试器，用于在**你看不到服务器实机画面**的情况下，远程实时查看 js 服务器
上 Android 模拟器的画面、图匹配位置、图导航建议、VLM 建议动作，并**手动点击网页上的
a11y 元素 → 服务器模拟器同步点击**。

脚本: `_debug_server.py`（项目根，平台参数化，desktop / android 共用）。

---

## 1. 它解决什么问题

- 你的开发机看不到 js 服务器上 headless 模拟器的屏幕。
- 实机采集时 agent 经常迷路/脱轨，需要一帧一帧看「现在在哪个图节点、图建议点哪、
  VLM 想点哪、实机有哪些元素」再决定下一步。
- 调试台把这些信息全汇总到一个网页，**你点按钮才执行一个动作**，然后自动刷新。

一句话：把 headless 模拟器变成一个你能看、能逐步操控的网页。

---

## 2. 架构 / 数据流

```
你的浏览器 (本地 127.0.0.1:5006)
      │  SSH 端口转发 (-L 5006:127.0.0.1:5005)
      ▼
js 服务器 Flask (_debug_server.py, 0.0.0.0:5005, 跑在 tmux 会话 dbg)
      │  AndroidGUIGenEnv (adb + gRPC)
      ▼
模拟器 emulator-5554 (Small_Phone, -grpc 8554)
```

每次 `/state`：抓实机帧 → `filter_nodes_for_app(a11y, app, full_window=True)` 取元素
→ `StateGraph.match_live_state` 定位图节点 → 算最短路径导航建议 → 构建 prompt 调 VLM
→ 全部打包成 JSON（含 base64 截图）返回网页。

⚠️ `full_window=True` 是采集视角关键：遍历视角只看当前活跃弹层（弹窗只 6 个元素），
采集视角必须看整窗（侧栏导航项），VLM/你才能点旁边的目标。详见 app_filter.md。

---

## 3. 启动步骤（服务器侧）

### 3.1 必须的环境变量
模拟器和 SDK 路径、动态库、模型 key 缺一不可（headless emulator 尤其挑 LD_LIBRARY_PATH）：

```bash
export ANDROID_SDK_ROOT=/data/shenghonghui/android-sdk
export LD_LIBRARY_PATH=/data/shenghonghui/miniconda3/envs/guiwalk-android/lib
export DASHSCOPE_API_KEY=<你的 key>      # 不填 VLM 那块会报错，但画面/元素仍能看
export PYTHONPATH=.:OSWorld
```

### 3.2 确认我们的模拟器在跑
```bash
adb devices            # 应看到 emulator-5554  device
adb -s emulator-5554 shell getprop sys.boot_completed   # =1 表示开机完成
```

> ⚠️ **5556 / 5558 / 5560 是 root 的 docker(knowu_bench) 模拟器，勿动。**
> 只有 **emulator-5554 (Small_Phone)** 是我们的。

### 3.3 用 tmux 起服务（关键：别用 nohup/setsid）
普通 `nohup`/`setsid` 会丢 SSH 会话里 export 的环境变量 → adb 连不上模拟器 →
误以为模拟器没起 → 尝试重启 emulator → SDK 路径崩。**tmux 会保留会话环境**：

```bash
tmux new -s dbg -d
tmux send-keys -t dbg "cd /data/shenghonghui/GUI-ReWalk-mobile" Enter
tmux send-keys -t dbg "export ANDROID_SDK_ROOT=/data/shenghonghui/android-sdk" Enter
tmux send-keys -t dbg "export LD_LIBRARY_PATH=/data/shenghonghui/miniconda3/envs/guiwalk-android/lib" Enter
tmux send-keys -t dbg "export DASHSCOPE_API_KEY=<key>" Enter
tmux send-keys -t dbg "export PYTHONPATH=.:OSWorld" Enter
tmux send-keys -t dbg "python _debug_server.py --platform android \
  --avd_name Small_Phone --console_port 5554 --grpc_port 8554 \
  --host 0.0.0.0 --port 5005 \
  > _debug_android.log 2>&1" Enter
```

日志看到 `READY [android] -> http://0.0.0.0:5005` 即就绪（图加载+连模拟器约 60s）。

查日志：`tail -f _debug_android.log`，正常每次刷新打一行
`[analyze] matched=... conf=... n_elem=... has_Sound=... vlm_eid=...`。

---

## 4. 连接步骤（本地侧）

开 SSH 端口转发（本地 5006 → 服务器 5005）：

```bash
ssh -p 31400 -L 5006:127.0.0.1:5005 shenghonghui@js1.blockelite.cn
```

浏览器打开 **http://127.0.0.1:5006/**。

---

## 5. 网页用法

| 区块 | 内容 |
|------|------|
| ① 当前实机画面 | 模拟器实时截图 |
| ② 图匹配节点 | match_live_state 命中的图节点截图 + 置信度(exact/jaccard/visual/none) |
| ③ 任务 | overall / subgoal / 目标节点，可改后「更新任务」 |
| ④ 图导航建议 | 最短路径 + 下一跳该点哪个元素名 |
| ⑤ VLM 建议动作 | 子代理看截图+元素列表给的 JSON 动作 |
| ⑥ 执行 | 「执行图建议」「执行VLM动作」「仅刷新」「Reset」+ 手动点 id |
| ⑦ 实机元素列表 | 每行一个 a11y 元素，**「点这个」按钮 → 模拟器同步点击** |
| ⑧ 完整 Prompt | 发给 VLM 的全部内容（确认它能看到什么） |

**点网页元素 → 模拟器同步点击**：区块⑦每行的「点这个」调 `/act {type:element, element_id}`，
服务器 `env.step(CLICK, x, y)` 用该元素**实时坐标**点击模拟器，然后重新抓帧刷新。

---

## 6. 常见故障

| 现象 | 根因 | 处理 |
|------|------|------|
| 看不到画面 / `/state` 不返回 | 服务器 `app_filter.py` 旧版无 `full_window` 参数 → `TypeError` 崩在抓帧 | 给服务器 app_filter.py 打补丁（filter 签名 +full_window、两处 explore 调用 +skip_popup、_pick_active_surface 签名 +skip_popup、短路 `if skip_popup: return frame`）。**勿整文件覆盖**（服务器有移动端 D16 改动） |
| adb 连不上 / 想重启模拟器报 SDK 路径 | nohup/setsid 丢了环境变量 | 改用 tmux，在会话内 export 后再起服务 |
| 模拟器崩 `libX11-xcb.so.1 give up` | 缺动态库 | `export LD_LIBRARY_PATH=.../guiwalk-android/lib` |
| env 连 gRPC 超时 | 模拟器没开 gRPC | 启动加 `-grpc 8554`（光 -port 不开 gRPC） |
| ⑤ VLM 报错但①②⑦正常 | 没 export DASHSCOPE_API_KEY | 画面/元素不依赖 VLM，可先调试导航；要 VLM 再补 key |
| matched=未匹配 | 当前页是输入框/弹层，图里本就没有 | 正常，导航交 VLM 自由决策 |

---

## 7. Offline manual screenshot capture (current behavior)

`tools/capture_mobile_screens.py` is the formal, zero-third-party-runtime-dependency
entry point for building screenshot-only Android grounding datasets while a human
manually visits each page. It does not click, swipe, clear application data,
disable overlays, or otherwise mutate device state.

Example:

```powershell
python tools/capture_mobile_screens.py --serial emulator-5554 `
  --session settings-manual-01
```

The default dataset root is `data/imported/mobile_grounding`. A session owns
`images/`, `frames/`, and `manifest.json`; the manifest schema is
`gui_rewalk.mobile_grounding_capture.v1`. Each PNG has a matching JSON sidecar
with its monotonic index, original label, relative image path, UTC capture time,
SHA-256, dimensions, device serial, and best-effort foreground package/activity.
Reusing the same session resumes after its greatest recorded index, skips orphan
filenames instead of overwriting them, and rejects a different device serial.
Manifest replacement is atomic.

At the prompt, Enter or `c [label]` captures, ordinary text captures with that
label, `s` shows status, `u` removes only the last frame recorded by this session,
`h` shows help, and `q` exits. EOF and Ctrl-C also exit safely. For automation,
`--capture-once [LABEL]` captures one frame and returns a process status. Device
selection uses online (`device`) entries from `adb devices`: one device is chosen
automatically; zero or multiple devices fail with a user-facing message unless
`--serial` identifies an online device. Screenshots use raw
`adb [-s SERIAL] exec-out screencap -p` bytes and are rejected unless their PNG
signature and IHDR dimensions are valid.

This entry point is independently configurable through `--adb`, `--output-root`,
`--settle-seconds` (including zero), and `--prefix`. Session names are validated
as single safe directory names; labels and prefixes are reduced to safe filename
components, so they cannot escape the session directory.

## 8. Manual mobile state graph annotation (current behavior)

`tools/mobile_graph_annotator.py` and `tools/mobile_graph_annotator.html` form the
formal local geometry-only annotation workbench for a completed or growing
capture session:

```powershell
python tools/mobile_graph_annotator.py data/imported/mobile_grounding/settings-manual-01
python tools/mobile_graph_annotator.py data/imported/mobile_grounding/settings-manual-01 `
  --live-capture --serial emulator-5554
```

The standard-library HTTP server binds only an IPv4 loopback address (default
`127.0.0.1:8765`). `--no-open` suppresses automatic browser opening. The server
loads the UI from the adjacent HTML file and never accepts a client-supplied
filesystem path. GET routes are read-only; JSON and PNG write routes have body
limits and return structured 4xx errors. State and frame resources are addressed
only by validated IDs.

Direct script startup does not depend on the current working directory or
`PYTHONPATH`. The tool derives `TOOLS_DIR` and `REPO_ROOT` only from its trusted
`__file__`, installs both deterministically in `sys.path`, and keeps the adjacent
`capture_mobile_screens` import at module load. Consequently the lazy canonical
`grounding.scroll` and `grounding.stitch` imports also work when the process was
started from outside the repository. No user-provided import path is accepted.

The source `manifest.json`, viewport PNGs, and capture sidecars remain read-only.
All outputs live below `<session>/annotations/`: the atomic machine-readable
`graph.json`, uploaded/generated `fullpage/<state>.png`, and live long-page source
frames in `scroll_frames/<state>/`. The graph schema is
`gui_rewalk.manual_grounding_graph.v1`. Capture frame indices map deterministically
to state IDs such as `s000001`. Graph records contain viewport/fullpage canvas
metadata, anonymous button/region annotations, click edges, shared regions, and
a recoverable pending click. The additive `pending_device_action` stores at most
one staged click/scroll/Back action with source and geometry but no target. Geometry always stores original-pixel coordinates
plus `[0,1000]` normalized coordinates. The graph rejects `name` and `label`
fields recursively.

The UI provides exactly geometry modes: button box, region box, and click point.
Viewport canvases accept all three; fullpage canvases accept region boxes only.
Button-box annotation follows a foreground-activity convention: annotate buttons
only inside the current foreground/active region, and omit background buttons
that are covered or made inactive by a modal, drawer, or similar surface. When
there is no local foreground region, the whole page is the active region. This
is a human annotation convention only: it remains pure geometry, adds no required
text/category field, and does not block pages that have no region box.
It supports selection, deletion, server-side undo, previous/next state movement,
automatic IDs, clear autosave status, and a state/edge overview with node jumps.
A normal browser reload selects the latest active state and does not capture a
new screenshot. `生成状态` is the explicit state-generation action and is also
available on an empty graph. Every click appends a real capture-backed state even
when pixels are unchanged; its `sNNNNNN` ID continues the capture-manifest index.
With no staged device action it creates an isolated state. With one staged action
it creates exactly the matching click/scroll/Back edge and clears the staging
record. It never consumes the separate geometry-only pending click.

The state panel can also declare the current state and one other state as the
same logical page. `same_page_links` is an undirected, ID-only relationship and
is displayed as `same-page sA ↔ sB`; it is not a click, scroll, Back, navigation,
or action edge. Both screenshots and their independent annotations remain in the
graph. Dynamic content, time, and ordinary scroll position may differ, but modal,
drawer, popup, and other different active surfaces must not be linked as the same
page. The UI offers only existing state IDs and adds no naming/text field.

Below the current screenshot, `当前页局部图（1-hop）` is a read-only frontend
view. It treats click, scroll, Back, and same-page endpoints as undirected only
while collecting direct neighbors of the current state; it then displays every
existing relation whose two endpoints are both in that node set. Thus relations
between two included neighbors remain visible, while a node connected only to a
neighbor but not directly to the center is excluded. Click/scroll/Back retain
their stored direction, arrow, color, and short type label; same-page is an
undirected dashed line. Parallel relations use distinct canonical-pair curve
offsets, and arrows are clipped to target card boundaries so node thumbnails do
not hide direction.

The center screenshot is larger and highlighted, neighbors surround it, and the
SVG viewBox expands with neighbor count rather than truncating nodes. Exactly two
neighbors use a left/right layout instead of the former vertical alignment. A
read-only relation list below the SVG spells out source, type, direction, and
target; click rows include coordinates and scroll rows include direction plus
anchor. This remains readable even when a curve or label is visually crowded by
a screenshot card. Empty and isolated states have explicit renderings. Each
thumbnail is loaded read-only from
`/api/image/<state>/viewport`; mouse click or Enter/Space moves the existing UI
selection to that viewport and recomputes the graph. No graph write, screenshot,
device action, CDN, third-party library, or text input is involved.
A viewport click becomes a pending edge source; it never executes an ADB tap.
The user can complete it against an existing state, or, with `--live-capture`,
manually change the VM and capture a new target state. A capture with no pending
click creates an isolated state and does not invent an edge.

Real VM control is a separate, explicit mode:

```powershell
python tools/mobile_graph_annotator.py <session-dir> --live-control `
  --serial emulator-5554 --action-settle-seconds 0.5
```

`--live-control` implies live capture and requires an explicit online ADB serial;
the server never auto-selects a control target. The browser's "操作虚拟机"
checkbox is still OFF on every load and must be explicitly enabled. While it is
enabled on a viewport, clicking performs an ADB tap at original screenshot pixels,
and the mouse wheel performs an anchored ADB swipe (`deltaY>0`: finger bottom to
top/content browsing down; `deltaY<0`: the inverse). The server serializes actions,
waits the bounded `--action-settle-seconds` interval, then stores one
`pending_device_action`; it does not capture, append a state, or create an edge.
Additional successful tap, scroll, or Back actions atomically replace that slot,
so the user can perform a sequence and keep only its final action as the pending
edge. The UI keeps VM control and Back available while pending and states that
continuing will overwrite the pending record. The user must click `生成状态` to
capture and complete the transition for the final action. Fullpage
canvases reject real actions. Tap/swipe failure never stages an action. The
ordinary "点击点（仅标注）" mode remains metadata-only and never touches ADB.

`虚拟机返回（Back）` is a separate explicit authorization button; it does not
depend on the general VM-control checkbox. When live Back support is available
and a viewport state is selected, it sends the argv-only Android key event
`adb -s <serial> shell input keyevent 4`, waits the same bounded settle interval,
and stages an anonymous Back action. A later `生成状态` capture appends the
`back_edges` source/target entry. It uses the shared action lock, is disabled for an
empty graph/fullpage/unavailable Back/busy service, and never consumes a pending
click. Back failure never stages a success action.

Only one device action is stored, but tap/scroll/Back use latest-action-wins
replacement instead of a queue or a 409 conflict. Capture-as-click-target,
compatibility live refresh, manual long-page capture, and automatic long-page
generation still return 409 while the slot is occupied. A failed later ADB action
leaves the prior pending record intact; if persistence of a successful replacement
fails, graph and undo history roll back to the prior record. Generation creates
exactly one typed edge for the final stored action and clears it.
`取消待生成（不回退设备）` removes only the graph staging record—the already sent
device action cannot be undone. Annotation and read-only navigation may continue.
Staging persistence failure restores graph/history but likewise cannot roll back
the physical device action. Generate capture/edge/save failure restores the
in-memory graph, history, pending action, and success edges; if the capture
manifest was already appended, its immutable file may remain as an unreferenced
artifact and is not deleted.

Focused offline verification for latest-action-wins and local-graph readability:
`python -m pytest -q tests/test_mobile_graph_annotator.py -k
"pending_device_action or latest_device_action or local_graph"` -> `5 passed, 52
deselected in 0.36s`; `python -m py_compile tools/mobile_graph_annotator.py` ->
exit 0. These checks used fake callbacks and static JavaScript contracts only. No
live ADB action, screenshot, state generation, or session mutation was performed;
interactive browser visual validation was unavailable.

For a remote emulator, keep the annotation HTTP server local and forward only the
remote loopback ADB smart socket to a non-default local port. Set
`ADB_SERVER_SOCKET=tcp:127.0.0.1:<local-port>` in the annotator process and still
pass the exact remote serial with `--serial`. This preserves the loopback-only UI
boundary and avoids exposing either ADB or the annotation server publicly. The
SSH target, remote port, and credentials are operator-supplied deployment values;
they are intentionally not source defaults.

`一键生成滚动长图` is a second explicit real-device action and therefore requires
`--live-control`; its own native confirmation is the authorization, so the general
VM-control checkbox may remain off. Under the shared action lock it captures a
live viewport, validates its dimensions and optional foreground package, and uses
the canonical scroll contract loaded lazily from `grounding/scroll.py`:
`STITCH_SCROLL_FRAC=0.42`, `STITCH_MAX_SCROLL_STEPS=14`,
`SCROLL_PATIENCE=2`, and `VIEW_STABLE_DISTANCE=4`. Each 750 ms down gesture stays
inside the Android `h/12` safe band. RGB `imagehash.phash` drops consecutive
duplicate frames; two stable views indicate the bottom, while package change
terminates as `off_app` without accepting that frame and 14 moving steps terminate
as `hard_cap`.

Before the first swipe, the live screenshot must match the selected state's
capture-backed viewport within the same pHash distance threshold. A mismatch
returns 409 with a prompt to restore the VM to that short screenshot, performs
zero swipes, and writes no graph data. Successful metadata includes
`source_match_distance`. While any real action or automatic scroll owns the
action lock, every other POST mutation returns 409; the UI also disables all
annotation, undo, clear, capture, shared-region, upload, manual/automatic long-page,
and VM-control inputs. Read-only navigation and canvas/state viewing remain usable.
Automatic long-page generation never creates graph states and is rejected while
a device action is waiting for state generation.

After every executed down gesture, success and failure paths best-effort restore
the start view with larger 2/3-screen, 400 ms upward navigation gestures, bounded
to `steps+3` attempts and verified against the initial pHash. A failed restore does
not discard an otherwise valid composite: graph/fullpage metadata explicitly says
`top_restored=false` and the UI warns. Frames never become states or graph edges,
and capture manifest/images are untouched. Successful auto frames use a unique
versioned scroll directory and versioned fullpage PNG; graph sequence/fullpage
references commit as one Undo step. Graph-save failure restores the old graph and
old fullpage reference; newly written run frames remain unreferenced diagnostic
artifacts. Stitching still delegates to canonical `stitch_frames/encode_png`.
No live automatic scroll was run during implementation verification.

Only region boxes can enter the shared-region ledger. The reuse control defaults
to the most recently created shared ID and is disabled when the ledger is empty.
Reuse restores the canonical normalized box on another state with the same
available canvas kind and synchronizes membership on deletion. A fullpage may be uploaded as a bounded
PNG, or constructed from a live sequence: the current viewport seeds the
sequence, subsequent screenshots are taken only after the user manually scrolls,
and generation delegates to canonical
`grounding/stitch.py::stitch_frames/encode_png`. Stitch metadata records source
frames, output size, sticky bands, and frame-to-composite positions. A failed
stitch retains its source sequence and does not replace an existing fullpage.
Any fullpage persistence failure restores the complete prior graph (including
annotation pixel boxes) and the prior PNG.

The destructive-looking `清空图` control always requires a native browser
confirmation. One atomic clear removes all annotations, pending click metadata,
pending device actions, click/scroll/back edges, same-page links, shared-region membership, fullpage references, and scroll
sequence references from `graph.json`, and empties its active `states` list. The
v1-compatible `capture_floor_index` records the highest capture index present at
clear time, so later manifest synchronization does not re-import those hidden
states. Original screenshots, the capture manifest, generated fullpage files,
and scroll-frame files remain unchanged on disk. One normal Undo restores the
complete pre-clear graph and floor; the next capture above the floor becomes the
first active state without renumbering. The empty UI clears the previous image,
overlay, nodes, edges, selection, and scroll detail, disables state-dependent
controls, and keeps Undo plus explicit state generation available. Clear uses the same server
lock as real VM actions, returns 409 while an action is active, and rolls back
both graph and undo history if persistence fails. This behavior has only been
tested against temporary offline sessions; no real-device clear or state generation
was run during this change.

The default and `--live-capture` paths only reuse screenshot and metadata behavior
and never mutate device state. Only the separately enabled `--live-control` path
may call argv-only `adb shell input tap/swipe` and `adb shell input keyevent 4`;
it never clears app data or
changes overlays. There are no annotation text fields in the UI.

## 9. 简单 VMware 桌面截图分类器

`tools/simple_emulator_screenshot.py` 是与移动端建图台无关的独立桌面工具。直接从仓库
启动即可；如果 VMware Workstation 只有一个正在运行的虚拟机，不需要填写 VMX：

```powershell
python tools/simple_emulator_screenshot.py
```

默认网页为 `http://127.0.0.1:8770/`，默认保存根目录是**启动命令当前目录**下的
`./测试图片`。启动时固定创建 `正常图片/` 与 `变体/`；网页用单选框选择保存位置，
不接受文件名或任意目录。可用 `--output-dir` 更换根目录、`--no-open` 禁止自动打开浏览器、
`--vmrun` 指定 `vmrun.exe`，或在多个 VM 运行时用 `--vmx` 指定其中一个正在运行的 VMX。

每次点击“刷新桌面画面”，后端以 argv（不经过 shell）执行 `vmrun -T ws list`。没有运行
VM 时失败；多个 VM 时要求 `--vmx`；显式 VMX 不在运行列表时也失败。选定后再执行
`getGuestIPAddress`，严格验证 IP，并只访问固定的 OSWorld guest 截图地址
`http://<validated-ip>:5000/screenshot`，超时为 10 秒。前端不能传入 VM、IP 或 URL。
返回内容必须有合法 PNG/JPEG magic 与尺寸；原始格式和字节保留在内存预览中。

“刷新”绝不落盘。“保存截图”在尚未刷新时禁用；点击后将**当前显示缓存的同一字节**
原子保存到单选分类，不会重新请求 VM，因此保存内容不会与预览错帧。文件名由 UTC
时间戳、进程号和进程内序号生成，碰撞时继续取新名字，后缀保持 `.png` 或 `.jpg`。
成功后网页显示完整保存路径。HTTP 服务只允许 IPv4 loopback，JSON body 有上限；工具
不发送键鼠输入，不暂停、恢复、关闭或修改 VM。

聚焦验证：`python -m pytest -q tests/test_simple_emulator_screenshot.py` ->
`1 passed in 0.11s`；`python -m py_compile tools/simple_emulator_screenshot.py` -> exit 0。
测试只使用 fake vmrun runner、fake HTTP fetcher 和临时目录；未调用真实 vmrun/guest
HTTP，未启动服务，未向桌面发送动作。

## 10. 关联

- 平台参数化脚本: `_debug_server.py`（`--platform desktop|android`）
- 元素过滤（full_window 采集视角）: `design/modules/app_filter.md`
- 图匹配 match_live_state（D19 分层匹配）: `design/modules/state_graph.md`
- 图引导导航/执行: `design/modules/scenario_executor.md`
- 移动端 env: `design/modules/android_support.md`
- 服务器部署细节: 见 MEMORY.md「服务器部署 js1.blockelite.cn」
