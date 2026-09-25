# 交互式调试器 / 查看器使用手册

GUI-ReWalk 项目的几个网页/可视化工具，本机调试用。
项目根：`C:\Users\Admin\Desktop\GUI agent\mywork`
Python（桌面 guiwalk 环境）：`C:\Users\Admin\miniconda3\envs\guiwalk\python.exe`

> 约定：以下命令都在项目根目录下执行。三个网页工具端口不同，可同时开。
> 连 VM 的工具（调试台）启动慢（约 60–75s 连 VMware + 加载图），不连 VM 的（功能查看器）秒开。

---

## 1. 交互式采集调试台 — `_debug_server.py`

**用途**：实时看实机画面 + 图匹配节点 + 图导航建议（纯动作链）+ VLM 建议动作 +
实机元素列表 + 完整 prompt；可在实机截图上直接点击/滚动/输入操控 VM；可输入自由命令
让 VLM 拆解成多目标并按拓扑/优先级/最短路径调度（命令规划）。**手动模式**：动作后不自动
刷新，点「仅刷新」才抓帧+跑 VLM。

**连 VM**（桌面连 VMware，移动端连模拟器）。

### 桌面启动（连本地 VMware）
```bash
"C:\Users\Admin\miniconda3\envs\guiwalk\python.exe" _debug_server.py ^
  --platform desktop --host 127.0.0.1 --port 5005
```
默认图/节点：`result_setting_qwen_0603_noopfix/...`，app=setting。可用
`--graph` / `--node_dir` / `--app` 覆盖。
访问：浏览器开 **http://127.0.0.1:5005/**

### 移动端启动（js 服务器上连模拟器，需 tmux + 环境变量）
见 `design/modules/mobile_collection_debug.md`（服务器侧 tmux 启动 + 本地 SSH 隧道
5006→5005 + emulator-5554 约束）。要点：
```bash
"<python>" _debug_server.py --platform android ^
  --avd_name Small_Phone --console_port 5554 --grpc_port 8554 ^
  --host 0.0.0.0 --port 5005 ^
  --graph <android图> --node_dir <android节点目录>
```

### 网页区块
①实机画面（可点击/滚轮/输入）②图匹配节点 ③任务 ③'命令规划（VLM拆解+调度）
④图导航建议（动作链）⑤VLM建议 ⑥执行按钮 ⑦实机元素列表（带坐标@(x,y,region)）
⑧完整 prompt

### 常见坑
- 端口被占：先 `powershell "Stop-Process -Id <pid> -Force"`（用
  `Get-NetTCPConnection -LocalPort 5005` 查 pid）。
- 画面全空 / n_elem=0：VM 的 AT-SPI 服务降级（a11y 树全 `<unknown>`）。
  修复：`vmrun revertToSnapshot init_state` + 重启 VM（见下「VM 维护」）。
- 不要同时再起别的脚本连同一个 VM（两个 env 抢连接会互相干扰）。

---

## 2. 功能合成查看器 — `_capability_viewer.py`

**用途**：实时看某图节点的截图 + 喂给 VLM 的元素清单（含 `[屏幕下方-需滚动才可见]`
屏下标注）+ 完整 prompt；点按钮跑 VLM 合成，看提取的功能（name / param / element_id
或"无id视觉提取" / explain）。可下拉换节点。**不连 VM**，秒开。

当前合成逻辑 = 视觉优先 + a11y 辅助屏下（D24）。点「跑 VLM 合成」用最新 prompt 重跑，
**会 force 覆写**该节点的 `page_capabilities.json`。

### 启动
```bash
"C:\Users\Admin\miniconda3\envs\guiwalk\python.exe" _capability_viewer.py ^
  --node_dir result_setting_qwen_0603_noopfix/gen_data/Qwen/0/nodes ^
  --port 5007
```
访问：**http://127.0.0.1:5007/**

### 网页操作
顶部下拉选节点（显示 id/元素数/是否已合成）→「查看」看截图+清单+prompt（有缓存先显示旧的，
标"缓存"）→「▶ 跑 VLM 合成」实时跑新结果。

---

## 3. 单步静态可视化 — `_step_viz.py`

**用途**：抓当前实机一帧 → 图匹配 → 图建议 → 构建 prompt → 调一次 VLM，把全部信息
汇总成一个静态 HTML 报告 `_step_viz.html`（截图并排 + 各文本块）。一次性快照，不交互。
连 VM（不 reset、不重启，抓当前帧）。

### 启动
```bash
"C:\Users\Admin\miniconda3\envs\guiwalk\python.exe" _step_viz.py [target_node]
```
产物：项目根下 `_step_viz.html`，浏览器直接打开。
（目标节点、整体/子目标指令在脚本顶部硬编码，需要改就编辑文件。）

---

## VM 维护（桌面）

VMware 控制：`"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"`
```bash
# 查快照
vmrun -T ws listSnapshots "OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx"
# AT-SPI 坏了 / a11y 全 unknown → 回干净快照
vmrun -T ws stop  "OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx" hard
vmrun -T ws revertToSnapshot "OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx" init_state
vmrun -T ws start "OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx"
```
revert 后约 40–60s 才能连上（等 AT-SPI 起来）；调试台用 reset 按钮可打开+最大化 Settings。

---

## 端口速查

| 工具 | 端口 | 连 VM | 启动速度 |
|------|------|-------|---------|
| `_debug_server.py` 调试台 | 5005 | 是 | 慢(~60s) |
| `_capability_viewer.py` 功能查看器 | 5007 | 否 | 秒开 |
| `_step_viz.py` 静态快照 | 无(出 html) | 是 | 一次性 |
| 移动端调试台(服务器) | 5005→本地5006 隧道 | 是(模拟器) | 慢 |

## 关联文档
- 移动端调试台部署：`design/modules/mobile_collection_debug.md`
- 命令规划器：`design/modules/command_planner.md`
- 功能合成器：`design/modules/capability_synthesizer.md`
- 纯视觉功能提取待办：`design/modules/open_issue_pure_visual_capability.md`
