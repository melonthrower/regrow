# Dayline desktop fixture

Dayline 是一个外观接近日常知识工作应用、无账号、无网络依赖、状态可复现的桌面 App，
用于给纯视觉遍历框架提供已知真值。应用界面不展示测试术语；oracle 与检查能力保留在开发文件中。

## 覆盖面

- 8 个语义 Page：Home、Documents、Document details、Recent activity、Weekly summary、Settings、About、Done。
- 3 个长页：Documents、Activity、About；底部都有唯一锚点，要求真实到达 bottom 并回到 canonical top。
- 2 种 active overlay：短 `popup_menu` 与 `dialog`；背景控件不应进入当前 active surface 的 frontier。
- 共享桌面 sidebar：4 个一级 Page 之间的 peer navigation 应保留 source-local verified edge。
- 参数化列表：9 个 Document 行属于同一 `record_item` group；不同文档只改实例数据，不应拆成不同 Page。
- 可逆状态：Document reviewed 与 Settings/Daily digest 应拆 Variant，但仍归属于各自唯一 Page。
- 明确不可执行控件：Cloud sync 是 disabled + login-required，不应被当成成功覆盖。
- 普通 forward、peer、return、state-change、open/dismiss overlay 与 terminal flow 都有已知目标。

完整真值在 `oracle.json`。`inspector.html` 会把每个 Page 的 anchors、blocks、controls、variants、scroll contract 和 outgoing transitions 展开，并给出简化关系图。

## 复用当前 Qwen prompt

`qwen_responses.json` 额外给出 15 个典型可见状态的期望回复，包括长页 top/bottom viewport、popup、dialog 与开关前后状态。它严格沿用当前 `SEMANTIC_INVENTORY_PROMPT`：

- 顶层仍是 `page/surface_kind/surface_scrollable/is_system_dialog/is_interruption/blocks`；
- block 仍是 `role/note/scrollable/elements`；
- element 使用当前完整字段集，且完全不含 bbox/point/坐标；
- 长页回复只列当前 viewport 可见元素，不把 oracle 的 below-fold 内容提前泄露给模型；
- popup/dialog 回复只列 active surface，背景元素不混入。

因此真实遍历不需要为 fixture 改 prompt。离线 parser/策略测试可直接用 `QwenFixtureStub` 返回同样的 GUIGenAgent tuple：

```powershell
python synthetic_app/qwen_stub.py --list
python synthetic_app/qwen_stub.py settings.tips_on
```

stub 不做截图识别，也不应接入 live traversal；测试代码先显式选择已知 observation key，再让现有 `VisualPerception.semantic_inventory()` 原样解析即可。

## 本机预览

生成 standalone 页面：

```powershell
python synthetic_app/build_fixture.py
```

启动本地预览：

```powershell
python synthetic_app/serve.py
```

然后打开：

- App: `http://127.0.0.1:8765/`
- Oracle inspector: `http://127.0.0.1:8765/inspector`

页面本身是单文件 HTML；也可以直接打开 `synthetic_app/index.html`。

### 三个独立滚动 Region 页面

直接打开 `http://127.0.0.1:8765/#/workspace`，或从 Home 点击
`Open planning workspace`。`Planning workspace` 的外层页面固定在一个视口内，
包含三个彼此独立的可滚动区域：

- `Research queue`：较浅位置的 `Open interview synthesis`；
- `Delivery board`：中等深度的 `Open release readiness`；
- `Reference shelf`：更深位置的 `Open team field guide`。

三个入口首屏都不可见，滚动对应 Region 后才会出现。入口点击只更新页面顶部的
安全状态说明，不会提交数据、打开外部链接或影响另外两个 Region 的滚动位置。
离线真值位于 `oracle.json` 中 `workspace.scroll.nested_regions`，记录 Region、入口、
深度顺序和确定性结果。该真值只用于 fixture 检查和离线测试；真实截图/VLM 运行
不得把 oracle、inspector 内容或 fixture-oracle inventory/grounding 注入 Agent。

不使用 fixture oracle 的真实 Agent 建议命令：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path synthetic_app/index.html `
  --screen_width 1365 `
  --screen_height 900 `
  --headless `
  --app_name dayline `
  --autonomous-agent `
  --autonomous-backend qwen_api `
  --autonomous-model qwen3.7-plus `
  --fixture_oracle_inventory off `
  --fixture_oracle_grounding off `
  --max_states 20 `
  --max_actions 80 `
  --result_dir artifacts/runs/dayline_three_regions
```

这条命令只是后续真实 Agent 验证入口；fixture 自身的离线测试通过不代表真实 VLM
已经发现、滚动或点击了三个入口。

## 在 GUI-ReWalk 桌面 VM 中运行

推荐的 `app_name` 是 `dayline`，旧名 `rewalk fixture` 仍兼容。生命周期模块会在每次 launch 前把生成好的 `index.html` 通过现有 guest Python 通道写到 `/tmp/gui_rewalk_fixture/index.html`，再用独立 Chrome app profile 启动并最大化。它是 Ubuntu 桌面 VM 中的无地址栏桌面窗口，不是移动端模拟器，也不需要从 VM 访问宿主机或公网。

沿用当前桌面 traversal 的 VM/model 参数，只把应用名换成：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider vmware `
  --path_to_vm <Ubuntu0.vmx> `
  --app_name dayline `
  --clean_start `
  --vlm_grounding `
  --region_dedup `
  --max_states 40 `
  --max_actions 160 `
  --result_dir artifacts/runs/fixture_app
```

`--clean_start` 只删除 `/tmp/gui_rewalk_fixture/profile`，因此不会动普通 Chrome profile。run 内的 data-preserving restart 会保留 Daily digest、reviewed 等 fixture 状态。独立 CLI 的 VMware provider 仍可能回滚 VM snapshot，这一点与现有桌面生命周期一致。

如果改用 `--semantic_inventory`，当前框架契约会跳过 scroll/stitch，因此 validator 应当明确报 3 个 `incomplete_scroll_scope`；这可以用来区分“模式已知限制”与其他 Page/Router 错误。

## 对比框架产物

```powershell
python synthetic_app/validate_graph.py `
  artifacts/runs/fixture_app/<date>/dayline/graph.json `
  --json-out artifacts/runs/fixture_app/fixture_validation.json
```

validator 会语义对齐 opaque runtime Page ID，然后检查：

1. 缺页、同一真值 Page 被错误拆分、多个真值 Page 被错误合并；
2. 页面控件与 homogeneous record group 是否被发现；
3. 真值中要求的 direct verified transition 是否存在；
4. popup/dialog 是否错误脱离 host Page；
5. 3 个长页是否有 `scrollable + bottom_reached + top_restored + complete` 账本证据。

退出码 `0` 表示真值检查全通过，`1` 表示发现框架差异，`2` 表示输入/JSON 错误。这个 validator 是 fixture-specific oracle，不替代正式 `run_graph_quality.py` 或 traversal completion certificate；建议三者一起看。

## 参考图

`capture_reference.py` 使用本机 Playwright 生成 1365×900 desktop viewport 和 full-page 参考图：

```powershell
python synthetic_app/capture_reference.py
```

输出位于 `synthetic_app/reference/`，其中 `library_full.png`、`activity_full.png`、`about_full.png` 是真值长图；另有 popup、dialog、Home viewport 和 oracle inspector 截图。
