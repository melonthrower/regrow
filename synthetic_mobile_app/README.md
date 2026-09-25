# Mingle mobile fixture

Mingle 是一个仓库自带的 Android 通讯应用 fixture。它使用日常聊天应用的视觉和交互形态，同时提供机器可读的页面、区块、控件、跳转、滚动范围和临时浮层真值，用来和 GUI-ReWalk 的实际输出做逐项比较。

## 覆盖范围

- 8 个语义页面：Chats、Weekend Plan、Contacts、Alex Chen、Explore、Me、Settings、Chat info。
- 42 个页面级控件，另有 9 个浮层控件。
- 3 个长页面：聊天列表、会话记录、联系人列表。
- 3 个临时 surface：新建聊天 bottom sheet、附件 bottom sheet、清空聊天确认 dialog。
- 搜索、发送消息、收藏联系人、静音会话和通知开关等可逆状态。
- 17 份与当前 `SEMANTIC_INVENTORY_PROMPT` 结构一致、且不包含几何坐标的 Qwen-shaped 预期回复。

`oracle.json` 是比较基准；`inspector.html` 用于人工查看每一页的区块、控件、目标页和 surface；`validate_graph.py` 用于把实际 `graph.json` 与 oracle 做离线比较。真实遍历仍使用原 prompt 和真实模型，不会把 oracle 喂给模型。

## 本地查看与生成

直接打开 `index.html#/inbox` 可以预览应用，打开 `inspector.html` 可以查看完整契约。

```powershell
python synthetic_mobile_app/build_fixture.py
python synthetic_mobile_app/smoke_test.py
python synthetic_mobile_app/capture_reference.py
```

重新生成 Android debug APK：

```powershell
python synthetic_mobile_app/build_apk.py
```

产物为 `synthetic_mobile_app/mingle-debug.apk`，包名为 `com.guirewalk.mingle`，入口为 `.MainActivity`。

## 在 Android 虚拟器中运行

框架已注册 `app_name=mingle`。第一次启动时，`mobile_ops.launch_app()` 会通过 ADB 执行 `install -r` 安装仓库内 APK；同一个 AVD 会话中不会重复安装。`--clean_start` 会清除 Mingle 的应用数据，普通重启和恢复保留应用数据。

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider android `
  --avd_name Small_Phone `
  --app_name mingle `
  --clean_start `
  --vlm_grounding `
  --stitch_node_image `
  --max_states 50 `
  --max_actions 180 `
  --result_dir artifacts/runs/mingle
```

模型、API 和其他环境参数继续使用你们现有的运行配置。

## 无模拟器后台遍历

若目标是快速验证截图感知、像素 grounding、Router、图结构和 oracle，而不是 Android 系统栏、
ADB、触控惯性或系统权限弹窗，可直接使用 headless Chromium 后端。该模式只把 Playwright 当作
像素截图与输入执行器；框架感知、定位和验证不读取 DOM 或 oracle。

```powershell
python gui_rewalk/run_visual_traversal.py `
  --vm_provider local_html `
  --html_path synthetic_mobile_app/index.html `
  --screen_width 412 `
  --screen_height 915 `
  --app_name mingle `
  --clean_start `
  --no_live_monitor `
  --semantic_inventory `
  --stitch_node_image `
  --vlm_response_cache artifacts/cache/mingle_qwen_exact `
  --max_states 8 `
  --max_actions 16 `
  --result_dir artifacts/runs/mingle_local_html
```

若只想隔离检查遍历逻辑，可在上述命令加入：

```powershell
  --fixture_oracle_inventory on `
  --fixture_oracle_grounding on
```

第一个开关跳过区块/元素识别及区块定位、对齐；第二个开关跳过待点击元素的
坐标模型与坐标复核。两个开关默认均为 `off`，只允许用于仓库自带的
`local_html` fixture。Page/Variant、frontier、Router、点击后落地判断、滚动和
completion 仍走框架原逻辑。

`--vlm_response_cache` 是可选的跨运行精确回复缓存。第一次运行仍会调用真实模型，
随后只有在角色、模型与生成参数、完整 prompt、所有截图像素都一致时才复用原始回复；
修改 prompt、模型、截图或推理参数都会自动 miss 并生成新的记录。缓存默认关闭，目录内
只写请求哈希元数据和模型原始回复，不复制 prompt 文本或截图。每次运行的
`vlm_calls.json` 会单列 `persistent_cache_hits`。若要强制重新采样，省略该参数或换一个
空目录即可。

该模式无需 AVD、Android SDK 或 APK 安装。它验证应用级视觉与交互契约，不能替代最终 Android
平台专项 smoke。

## 比较框架输出

```powershell
python synthetic_mobile_app/validate_graph.py `
  artifacts/runs/mingle/<run-date>/mingle/graph.json `
  --json-out artifacts/runs/mingle/comparison.json
```

比较器会报告页面、区块、控件、跳转、surface 和长页面滚动覆盖的缺失、错误归并和多余项。它检查结构契约，不等同于 completion certificate。

## 验证边界

仓库内 smoke test 使用 headless Chromium 验证导航、状态、浮层和滚动；APK 构建验证 Java/WebView 包装与 Android 打包。若没有连接在线 AVD，这些结果不能宣称真实 Android 点击、真实 Qwen 感知或完整遍历已经通过。

## 区块优先单图实验

第一阶段只发现区块：

```powershell
python gui_rewalk/run_visual_traversal.py `
  --perception-only `
  --image synthetic_mobile_app/reference/settings_viewport.png `
  --block_first_inventory `
  --vlm_response_cache artifacts/cache/mingle_block_first `
  --result_dir artifacts/runs/mingle_block_discovery
```

查看 `block_discovery.json` 后，第二次用 `--target_block b1` 只识别该区块。
它会额外生成 `selected_block_crop.png` 与 `block_inventory.json`。该模式目前只供
保存截图 A/B，不进入默认完整遍历。Contacts/Settings 的真实 Qwen 小样本报告位于
`artifacts/runs/mingle_block_first_ab_20260718/REPORT.md`。

第二阶段默认使用区块裁剪。可加 `--block_image_mode full` 保留整图上下文，但实测
Contacts 联系人列表会串入相邻 shortcuts 元素，因此整图模式只作为诊断选项；裁剪仍是
安全默认值。

`--block_image_mode context_crop` 会依次发送整图和区块裁剪，只允许从第二张图输出。
它在实测中消除了整图模式的串区，但没有提高 `Add` 的语义命名，耗时也略高于单裁剪；
因此适合作为需要页面语境时的回退，而不是默认模式。
