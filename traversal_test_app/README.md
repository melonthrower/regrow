# Quick traversal tests

九个独立小页面，一页只测试一种行为：

| 页面 | 直达地址 | 测试内容 |
|---|---|---|
| `scroll.html` | `http://127.0.0.1:8770/scroll.html` | 三个区块独立滚动并查找隐藏入口 |
| `loop.html` | `http://127.0.0.1:8770/loop.html#/1` | Page 1 → 2 → 3 → 4 → 1；Page 2 需要滚动 |
| `back.html` | `http://127.0.0.1:8770/back.html#/1` | 三页全连接；返回到真实来源并恢复进入位置 |
| `region_merge.html` | `http://127.0.0.1:8770/region_merge.html#/overview` | 三页共享并重排 Region；按钮保持相同区内相对位置 |
| `panel_combinations.html` | `http://127.0.0.1:8770/panel_combinations.html#/home` | 四个 Page 共享可独立开关的 Library/Inspector，并在长路径后用不同 Region 组合返回 Home |
| `notion_like_desktop.html` | `http://127.0.0.1:8770/notion_like_desktop.html#/projects` | Notion-like 桌面数据库、Peek、全页条目、Details、Wiki 与 Calendar |
| `gmail_like_desktop.html` | `http://127.0.0.1:8770/gmail_like_desktop.html#/inbox` | Gmail-like Inbox、Compose、邮件线程与 AI 侧栏 |
| `spotify_like_desktop.html` | `http://127.0.0.1:8770/spotify_like_desktop.html#/home` | Spotify-like Home/Search/Library、Player 与 Now Playing |
| `maps_like_mobile.html` | `http://127.0.0.1:8770/maps_like_mobile.html#/explore` | Maps-like 移动地图、结果 Sheet、Directions、Saved 与 Place |

启动：

```powershell
python traversal_test_app/serve.py
```

`index.html` 只是九个入口的简短目录。对框架做快速测试时建议直接把对应文件传给
`--html_path`，避免遍历目录页：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path traversal_test_app/scroll.html `
  --app_name quick-scroll `
  --autonomous-agent `
  --fixture_oracle_inventory off `
  --fixture_oracle_grounding off
```

将 `scroll.html` 换成 `loop.html`、`back.html` 或 `region_merge.html` 即可测试其他环境。
`oracle.json` 仅用于离线检查，不嵌入页面，也不注入 Agent。

## 真实 App UI 模式入口

四个 fixture 不复制品牌、Logo、账号或私有数据；每个 fixture 独立复现一种公开产品的可见结构模式：

```text
Notion-like:  Projects database -> Peek -> full item -> Details -> Wiki preview -> Calendar -> Projects + Peek
Gmail-like:   Inbox -> Compose -> Inbox -> Thread -> AI panel -> Inbox -> Starred -> Inbox -> Chat -> Inbox
Spotify-like: Home -> Now Playing -> Search -> Suggestions -> Library -> Home + Now Playing
Maps-like:    Explore -> Results Sheet -> Place Sheet -> Directions -> Saved -> Place -> Explore + Place Sheet
```

桌面 fixture 的模块化内核运行示例：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path traversal_test_app/notion_like_desktop.html `
  --local_html_start_hash "#/projects" `
  --app_name mosaic-notes `
  --modular-explore `
  --explore-model qwen3.7-plus `
  --screen_width 1365 `
  --screen_height 900 `
  --max_actions 12 `
  --no_live_monitor
```

移动 Maps-like fixture 使用 `--screen_width 430 --screen_height 900`。`window.__fixture` 和 `oracle.json`
只用于动作后的离线真值核对，不进入模型 Prompt。

## Page 与 Region 组合入口

`panel_combinations.html` 模拟主流复杂桌面应用的正交面板：四个主要 Page 共用导航和状态栏，Library 与
Inspector 可独立出现，Analytics 另有前景 Quick Review Sheet。内置可见主路径为：

```text
Home
  -> Records（Library 出现）
  -> Analytics（Inspector 出现）
  -> Analytics + Quick Review Sheet
  -> Settings
  -> Home（Library + Inspector 仍存在）
```

第一次和最后一次 Home 的 Region 组合不同，但 fixture Page truth 都是 `combo.home`。离线 oracle 用于检查
Page 是否被错误拆分、共享导航/面板是否复用、Sheet 是否保持独立；真实模型不读取这些 ID。模块化内核可直接运行：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path traversal_test_app/panel_combinations.html `
  --local_html_start_hash "#/home" `
  --app_name atlas-panel-combinations `
  --modular-explore `
  --explore-model qwen3.7-plus `
  --screen_width 1365 `
  --screen_height 900 `
  --max_actions 40 `
  --no_live_monitor
```

该运行仍是 real-model/Local HTML 证据，不是 Android、桌面 VM 或真实产品 App 验收。

## 四个专用脚本

从仓库根目录直接运行：

```powershell
.\traversal_test_app\scripts\test_scroll.ps1
.\traversal_test_app\scripts\test_loop.ps1
.\traversal_test_app\scripts\test_back.ps1
.\traversal_test_app\scripts\test_region_merge.ps1
```

默认 `acceptance` 模式会让当前 autonomous Agent 完整运行对应环境，随后读取运行产物与离线
`oracle.json`，生成 `quick_acceptance.json`。只有下列模块级条件全部满足才返回零：

- `scroll`：三个独立滚动容器都被真实滚动到底，三个隐藏入口均由已绑定 entry 的真实动作验证；
- `loop`：四条边按环路出现，第二页隐藏入口经滚动到达，回到根页时复用原页面身份；
- `back`：六条直达边均验证，每条边随后通过 Back 回到该次真实来源并恢复进入前滚动位置；
- `region_merge`：三个页面身份互不混淆，七个 Region/entry occurrence 被登记为四个稳定语义组，
  每组至少一条真实动作 verified，其余重复 occurrence 由 Agent 显式等价关系结算。

网页 DOM/oracle 只在运行结束后的验收取证中读取，不进入 Agent Prompt、Page Identity、grounding
或任务调度。保留的旧 guided completion 检查可显式使用 `-Mode guided`。快速逐边诊断使用：

```powershell
.\traversal_test_app\scripts\test_loop.ps1 -Mode edges
```

这会读取 `edge_cases.json`，把该环境的每条按钮边放在独立 fresh autonomous run 中测试，某一条
失败时最终返回非零。也可以先查看或只运行一个 case：

```powershell
.\traversal_test_app\scripts\test_back.ps1 -ListCases
.\traversal_test_app\scripts\test_back.ps1 -Mode edges -CaseId back_notes_recipes
```

脚本默认使用 `qwen3.7-plus`、1365×900 视口，并明确关闭 fixture inventory/grounding。可用
`-Model`、`-MaxActions`、`-MaxStates` 或 `-ResultDir` 覆盖运行参数；脚本不会保存或填写 API key。

## Region 合并入口

`region_merge.html` 的离线真值使用 A/B/C/D 表示四个稳定 Region，但页面可见文字只显示
真实业务名称：

- Today overview：A、B
- Project workspace：C、D、A
- Weekly review：B、C

共享 Region 的标题、内容、按钮和按钮区内相对坐标保持不变，但其卡片在页面中的绝对位置改变。
因此仅按页面坐标匹配会失败，仅按按钮相对位置匹配又会把不同 Region 混在一起。

用默认 autonomous acceptance 测完整 Region 合并：

```powershell
.\traversal_test_app\scripts\test_region_merge.ps1
```

这个入口保持 fixture inventory/grounding 关闭，Region 需要由截图/VLM 自己识别和合并。
若只想独立验证其中一条按钮边，可用目标边模式，例如：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path traversal_test_app/region_merge.html `
  --local_html_start_hash "#/workspace" `
  --app_name edge-merge-inbox-review `
  --autonomous-agent `
  --autonomous_test_target_edge "Project workspace::Open weekly review::Weekly review" `
  --screen_width 1365 `
  --screen_height 900 `
  --no_live_monitor
```

单目标边模式只验证按钮发现、执行和落点，不单独证明跨页面 Region 已合并。完整验收同时检查
Agent 登记的 Region 语义复用、entry 显式等价组、真实点击落点和页面身份映射。

## 一次只测一条边

`edge_cases.json` 列出了 20 条可独立运行的按钮边。目标边模式仍要求模型从截图中发现
目标按钮；同轮发现的其他按钮只保留为事实并从本轮任务队列排除，不会被写成
`verified` 或逐个点击。

例如只测 `Kitchen notes --Browse recipes--> Recipe collection`：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path traversal_test_app/back.html `
  --local_html_start_hash "#/3" `
  --app_name edge-back-notes-recipes `
  --autonomous-agent `
  --autonomous_test_target_edge "Kitchen notes::Browse recipes::Recipe collection" `
  --autonomous_fixture_audit `
  --screen_width 1365 `
  --screen_height 900 `
  --no_live_monitor
```

只有目标入口经过真实动作并被核验为 `verified` 时进程返回 `0`，并以
`target_edge_verified` 结束；落点页面必须与命令中的第三段一致，否则以
`target_edge_wrong_destination` 失败。来源页全部 Region 已调查完成但没登记目标按钮时，以
`target_edge_not_discovered` 结束；其他预算、模型或动作失败同样返回非零。完整范围、
排除的入口 ID 和目标入口证据保存在 `autonomous_trace.json.target_edge_test`，不生成或
冒充全遍历完成证书。

快速验证：

```powershell
python -m pytest tests/test_traversal_test_app.py -q
```
