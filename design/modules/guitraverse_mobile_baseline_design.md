# GUITRAVERSE 移动端恢复、快照与开发 Seed 设计

日期：2026-08-30

状态：用户已批准目标与命名；v1 已完成六域 live seed 与 read-only 隔离。2026-08-30 又构建了一个
含 16 个第三方 App 的 v2 开发 snapshot，并完成逐 App GUI smoke、shared 六域复验和四类状态的 A/B
隔离。v2 尚缺 tracked APK/assets lock、可重放 App adapter 和正式 certificate，因此当前只可作开发遍历
基线，不能写成已发布的开源 seed。2026-08-31 起正式运行方向改为 clean base + 按需 SeedPlan；旧 v2 不再是
按需 runner 的默认数据基线。修改后框架的多应用完整遍历和无监督 Luna-only acceptance 仍未完成。

第一次 v1 Clock smoke 已运行但失败：系统事实确认
`com.google.android.deskclock/.ScreensaverActivity` 属于目标包，Luna 却连续把系统风格全屏教学提示写成
`external_app`；旧 runtime 丢弃其 `Got it` action 并反复 Back/recover。run 由 Codex 为避免调用浪费而
停止，只有 2 Attempt/1 Transition，无 completion，不能当作遍历证据。对应 system-scope 冲突门禁已完成
离线修复，新的 saved-frame probe 和 live 重跑待执行。

post-fix v1 Clock smoke 已验证该缺口关闭：全屏提示成为 `target_app` 的 p2/s3/r6，`Got it` 是带
before/after 的真实 a3，一次完成 s3->s1；没有 external loop。run 在 20 actions 后以 action_limit/
partial 结束，3 Page、13 State、17 Region、13 Transition、bundle compiled、10 Capability，仍有 13 个
pending/parameter gap，不能作为完整 Clock 遍历。该 run 另暴露 Android 非 ASCII 部分输入被误结算，
已完成 delivery-error 修复；js1 read-only 5612 最小 live probe 返回
`input_text_unsupported_non_ascii` 且前后截图哈希一致，证明没有 tap/clear/部分输入。该 probe 不是
真实文本任务的 Luna 轨迹验收。

## 1. 目标

GUITRAVERSE 的每次应用遍历和每条新指令采集都从同一个可复现、无真实个人数据的完整移动端基线开始。
框架应优先继续探索未被遮挡的可见功能，主动处理能够安全消除的干扰，只在截图明确显示加载、倒计时、
扫描、异步进度或文字要求等待时使用 wait。需要外部身份登录的入口不执行；如果登录阻断主要功能，
运行以 `external_auth_required` gap 停止并提示用户登录后发布新快照版本。

新资产、profile、快照和工具统一使用 `guitraverse` 名称。现有 `gui_rewalk` Python 包、CLI、历史 schema
和已有证据路径不在本次重命名，避免无关迁移破坏历史结果。

## 2. 非目标

- 不复用 MobileWorld/AndroidWorld 官方任务的具体指令、目标对象、评测状态或 evaluator seed。
- 不把 seed 注入步骤写入训练轨迹、用户指令或 Capability evidence。
- 不在普通恢复中执行 `pm clear`；它会同时删除应用数据，不是安全的“只清缓存”。
- 不登录真实账号，不执行购买、上传、分享、发送外部消息或授权外部身份。
- 不要求 Luna 枚举系统 package、ADB 命令或 snapshot 实现细节。

## 3. Interruption 策略

主 Agent 依据最新完整截图把当前干扰归为以下一种临时决策，不新增持久 Page/Region 类型：

| 类型 | 判断 | 行为 |
|---|---|---|
| `nonblocking` | 只遮挡局部，仍有当前任务相关或其他未覆盖可见功能 | 不等待；先探索未遮挡 active surface |
| `dismissible` | 接管输入，但有可见关闭/确认、明确手势或平台 Back | 执行一个有 before/after 的 recover Attempt |
| `explicit_wait` | 明确加载、倒计时、扫描、异步进度或文字要求等待 | 最多两次 bounded wait；无进展后换策略或 gap |
| `external_auth` | Sign in、Add account、身份授权、账号选择或同等外部登录 | 不执行；记录入口；阻断核心功能时停止并报告 |
| `system_intermediate` | 权限控制器、系统选择器、全屏提示等 | 保留来源 pending；按可见安全入口恢复后结算最终 landing |
| `unknown` | 输入层级或后果不清楚 | fail closed，不点背景，不无限 wait |

通用优先级：

```text
继续未遮挡功能
  > 可见安全关闭/确认
  > 界面明确写出的恢复手势
  > 平台 Back
  > 不清数据的 force-stop + relaunch
  > 停止当前 run 并从基线快照重启
```

同一个逻辑 wait 或 recover 在相同 State/frame 上连续 no-effect 时不因改写理由而重置预算。

## 4. 动作预期不符与重做

模型不报告 Task 成功，只报告 owner action 和可见结果。框架按 Operation 的当前 owner、primitive、来源 State
和直接效果结算：

```text
expected direct effect 与 after 一致
  -> verified

expected 有证据且 after 不一致
  -> no_effect / unexpected_landing
  -> 保留 Operation pending
  -> fresh screenshot 重新 grounding，同一 binding 最多重做一次

第二次仍失败
  -> 点位未命中：grounding gap
  -> 点位命中但应用拒绝：parameter/application validation gap
  -> 落到其他表面：unexpected landing gap
  -> 应用消失：environment failure
```

重做不能复用旧坐标。失败 Attempt、before/after 和实际落地全部保留，不能被后一次成功删除。

## 5. Whole-AVD 快照合同

AndroidWorld 的 `app_snapshot` 只复制 `/data/data/<package>`，不能完整恢复系统设置、Contacts/SMS/Calendar
Provider、MediaStore、共享文件和跨 package 状态。因此 GUITRAVERSE 使用完整 AVD 基线：

```text
专用 writable AVD
  -> 完成系统设置、onboarding 与开发 seed
  -> 关闭模拟器并保存版本化 whole-AVD 基线
  -> 发布 guitraverse_mobile_seed_v1

每个 app traversal / 每条 instruction collection
  -> 从同一基线启动新的 read-only 实例或独立 overlay
  -> fresh preflight
  -> 执行与保存证据
  -> 销毁本次实例，不回写基线
```

基线必须记录：AVD 名、系统镜像指纹、profile 版本、manifest digest、seed report、创建时间和验证结果。
更新登录状态或 seed 时发布 `v2` 等新版本，不原地改写 `v1`。

## 6. Clean base、按需 SeedPlan 与 run checkpoint

正式 clean base 使用 `guitraverse_mobile_clean_base_vN` 命名，只含已安装 APK、必要 onboarding/setup 和系统配置，
不含任一 app traversal/collection data。它必须由操作者先创建、列出并显式传给 runner；当前仓库不把一个尚未
现场验证的名字设为默认。每个新 traversal 从它启动，再由 v2 清单生成
`guitraverse.seed_plan.v1`：plan 固定 base snapshot、app、dataset、内部稳定 `seed_id`、用户可见的具体内容、
manifest digest 和自身 digest。遍历选择目标 app 的完整 dataset，且只解开该 app 的必要 shared reference；
collection 只接受 capability authority 固化的 `seed_objects` 和 typed `scenario_delta` 的并集，instruction raw ref
不能自由扩张对象。所有 apply 都在首个 App launch 与 Luna/M13 前完成并 readback；环境 provenance 存在 run 的
`environment/` 下，不进入 Page/Region/Operation、ActionAttempt、Capability、用户指令或训练轨迹。

代码 adapter registry 覆盖 16 个 v2 dataset：Markor/Clipper、Simple Calendar、Tasks、Simple Draw、Audio Recorder、
Pro Expense、Broccoli、OsmAnd、OpenTracks、Joplin、四个 reference-only media/SMS app，以及 MiniWoB 的显式 no-op
presence check。它们分别复用 AndroidWorld SQLite/provider helpers 或确定性文件/媒体注入；任何注入/readback 失败仍
fail closed，不能重用历史全量 v2 snapshot 或重放探索动作。上述范围目前是离线实现/dispatch/readback 契约，尚不构成
clean base 或任何 app 的新 live 验收。

中断恢复只使用 run-owned `guitraverse.run_checkpoint.v1`：每个 checkpoint 保存一个 whole-AVD snapshot 与一个
同 generation 的 ledger copy，二者以 ledger digest、seed-plan digest、最后 settled attempt、app/package version
绑定。只在没有 pending attempt 时创建对，因此崩溃后的恢复不会用更晚 ledger 配更早环境，也不会再次结算 pending
action；只保留最近一到两个一致对，complete 后删除。旧 run 没有该环境对只能视为 partial，不是精确恢复。

## 7. 自有开发 Seed

第一版 manifest 使用固定、合成、可审计数据：

```yaml
schema: guitraverse.mobile_seed.v1
profile: guitraverse_mobile_seed_v1
system:
  airplane_mode: false
  wifi: true
  rotation: portrait
  locale: en-US
contacts:
  - {name: "GUITRAVERSE Seed Alice", number: "5550101"}
  - {name: "GUITRAVERSE Seed Bob", number: "5550102"}
files:
  - Downloads/guitraverse_seed_note.txt
  - Documents/guitraverse_seed_document.pdf
  - Pictures/guitraverse_seed_image.png
  - Music/guitraverse_seed_audio.wav
messages:
  - {from: "5550101", body: "Seed meeting moved to 3 PM"}
  - {from: "5550102", body: "Seed photo received"}
calendar:
  - {title: "GUITRAVERSE Seed Team Meeting", offset_days: 0}
  - {title: "GUITRAVERSE Seed Appointment", offset_days: 1}
  - {title: "GUITRAVERSE Seed Weekend Plan", offset_days: 7}
photos:
  - guitraverse_seed_landscape.jpg
  - guitraverse_seed_receipt.png
  - guitraverse_seed_people.jpg
```

实现可复用 AndroidWorld 的低层机制：onboarding setup、`contacts_utils`、文件/媒体复制、emulator SMS、
Calendar Provider/SQLite 与 media scan；不能调用官方 task `initialize_task()` 直接生成任务状态。

Seed 内容至少覆盖：空/非空列表、搜索、详情、选择、编辑、创建、删除/恢复候选和同质代表。外部发送、
真实账户、敏感权限、真实联系人和不可逆系统操作不进入 seed。

### v2 traversal seed draft 合同

v2 保留 v1 manifest/loader/CLI 的默认和 digest 合同。新的
`data/dev_seed/guitraverse_explore_seed_v2.yaml` 只声明固定的 16 个 AndroidWorld adapter、共享 Contacts/SMS/
Calendar/CallLog/Clock/files-media 代表数据以及各 app 的 shape-tagged 记录；shared pool 当前有 24 个
真实存在的对象，使用 `Documents/GUITRAVERSE`、`Pictures/GUITRAVERSE`、`Music/GUITRAVERSE` 等 Android
标准目录；Gallery、Simple SMS、VLC 和
Retro Music 仅通过 shared seed ID 引用共享对象，MiniWoB 只声明 launcher/built-in-page reachability，未伪造记录。
Clipper APK 实测只提供一个 `clipper.set/get` current-clipboard service，不是十条历史记录管理器，因此 v2
只声明一个结构化 clipboard 值，不再制造十个不可验证对象。
上述 shared/Clipper/Draw/Recorder/OsmAnd/Clock 字段已按 live 事实修正；其余 App dataset 仍是 target
inventory，尚未与当前 snapshot 全量对账或 digest 绑定。逐 App GUI 截图只能证明可达和代表项可见，不能
自动证明 profile 中每个日期、完成态、分类和 shape tag 都已满足。
`tools.guitraverse_seed` 的 v2 loader 严格拒绝未知字段、非保留号码、外部 URL、邮箱、凭据键、计数/shape
不匹配和悬空共享引用；公开返回的 records 均为 frozen tuple 边界。

APK lock 与 asset lock 分开：APK source 只允许官方 AndroidWorld HTTPS GCS，且需已验证的 APK/signer hash、
包/版本/SDK/ABI/许可证/来源字段。v2 的离线 installer 固定 16 个官方对象；VLC live builder 使用并验证
`_13050408`，因此 registry 选择该对象，`_13050407` 只保留为命名 alternate。下载先在临时文件中重新 hash
后原子写缓存，install 前/后分别用
`aapt`/`apksigner` 与 `pm path`/`dumpsys package` fail-closed 核验；它不推断许可证、不会写 APK lock。当前
builder 上已有 16/16 package/version/launcher live 结果，但没有将不完整的许可证和上游字段伪造成 tracked
lock。纯 Java APK 的 ABI lock 值可以为空；若 APK 含 native `lib/*.so`，inspection 仍要求
`aapt` 报出 ABI。asset lock 当前是含 generator provenance 的
`draft` 空 entries，只有 Task 5 的确定性生成后才能变为 `locked`。Certificate readiness 合同要求全部 16 app
的 install/setup/data/GUI evidence、共享域、已保存且 listed 的 v2 snapshot、A/B isolation、无 gap 和
`valid_until`；这些是 fail-closed schema 条件，不是 live 验收。

## 8. 工具与产物

实施阶段新增：

- `data/dev_seed/guitraverse_mobile_seed_v1.yaml`：唯一 seed 真值；
- `tools/guitraverse_mobile_seed.py`：兼容的薄 CLI façade，保留 `plan / apply / verify / snapshot-save / snapshot-load`；
- `tools/guitraverse_seed/`：v1 manifest、ADB、共享 apply/verify、报告和 CLI 实现；package 同时提供
  `load_v1_manifest`、`build_v1_plan`、`apply_v1_seed`、`verify_v1_seed`、snapshot 与 `main` 入口；
- `ops/run_guitraverse_seeded_mobile.ps1`：每次 run 从版本化只读基线启动；
- `artifacts/guitraverse_seed_reports/<version>/`：命令计划、manifest digest、设备查询和验证报告。

`plan` 和 `verify` 默认只读；`apply` 只允许显式 serial、专用 writable AVD 和显式 `--confirm-apply`。
任何 package/AVD/serial 与计划不一致时，在写入前停止。

当前 `tools/guitraverse_mobile_seed.py` 的确认参数必须精确等于
`guitraverse_mobile_seed_v1`，只接受本机 `emulator-<port>` serial，并通过 emulator console 核对
AVD 名为 `guitraverse_mobile_seed`。`apply` 使用系统 Contacts/SMS/Calendar/MediaStore provider 和
精确 `/sdcard` 合成路径；不调用 AndroidWorld task `initialize_task()`，也不执行 `pm clear`。
这些接线目前只有 fake-ADB 边界和真实本地 `plan` 证据；provider 权限、包名和写入结果必须在专用
writable AVD 上逐项 live 验证，失败时不能保存基线 snapshot。

Android 13 fresh AVD 可能不设置 `persist.sys.locale`，但仍以 `ro.product.locale` 提供产品 locale。
preflight 先读 persist，空值时只读回退 product；两者都不等于 manifest 的 `en-US` 才拒绝。工具不会
为了通过守卫去修改 locale。

## 9. 验收

### 离线

- manifest schema、保留号码、路径与唯一名称校验；
- 禁止真实账号、URL、凭据、非测试号码和外部发送动作；
- 生成确定性的命令计划和 digest；
- snapshot runner 不接受未版本化或可写的采集基线；
- interruption Prompt 在 Contacts coachmark、Clock 全屏提示、Photos Backup sheet 上分别选择
  `continue_visible / dismiss / dismiss`，不选择 wait 或登录。

### Live 开发验收

- 在专用实例创建 seed，逐项查询 Contacts、Files、SMS、Calendar、MediaStore 与系统设置；
- 保存 whole-AVD 基线，连续启动两个 read-only run；
- 第一 run 修改网络/联系人/文件后销毁；第二 run 验证所有值恢复到 manifest；
- Clock 全屏提示通过可见 `Got it` 或明确下滑恢复，Back no-effect 不无限重复；
- Photos 外部登录入口保持未执行；若核心功能因此不可达，报告 `external_auth_required`；
- seed/setup/restore 不进入探索 Attempt、Capability 或采集轨迹。

## 10. 实施顺序

1. interruption/wait 与 external-auth Prompt/确定性预算；
2. click expected/actual mismatch 的 fresh-grounding retry；
3. manifest、plan 与离线验证器；
4. ADB seed adapter；
5. whole-AVD snapshot runner；
6. 专用模拟器 live seed + restore 验收；
7. 用新基线重新遍历 Clock、Contacts、Files、Messages、Calendar，再扩展其他应用。

截至 2026-08-30：1-5 已完成离线实现与聚焦测试；遍历 CLI 只有显式
`--android_snapshot_name` 才在 read-only overlay 启动时加载版本化基线，wrapper 的 `-PlanOnly` 不启动
任何环境。6 的 seed/双实例恢复已经用下述 live 报告完成。7 的逐 App 遍历已经开始：Markor 保留为
API 中断前的 partial，Clipper 的静态服务页完成并由 saved live artifact 的离线重编译得到 certified；
Simple Calendar 的首次并发实例在动作 0 前启动超时，等待单实例顺序重试。其余 App 仍待运行，不能把
环境基线、partial 或离线重编译当作整批图或指令采集完成。

## 11. 当前 live 基线证据

js1 新项目位于 `/data/shenghonghui/projects/guitraverse/repo`，专用 AVD 为
`guitraverse_mobile_seed`，snapshot 为 `guitraverse_mobile_seed_v1`，manifest digest 为
`35482990e5290fd3d9bf0e880f35a6436a10a8dd6397cd3cad93ce2f5fa2e94a`。独立 verify 报告
`20260830T080558Z_verify.json` 对 system/contacts/files/messages/calendar/photos 六域均为 true；
`20260830T080616Z_snapshot-save.json` 确认 snapshot listed。

read-only run A 从 v1 启动后六域通过，随后精确删除 synthetic note 并开启 airplane mode，verify 只在
system/files 失败；实例销毁后，run B 从同一 v1 启动，`20260830T080841Z_verify.json` 再次六域全 true，
且 note 恢复、airplane=0。这证明 run overlay 没有回写基线。上述是环境 seed/snapshot 验收，不是 Luna
遍历、图质量、Capability 或指令采集证据。

## 12. v2 开发 snapshot 的 live 结果

js1 专用 AVD `guitraverse_mobile_seed` 已保存并列出 `guitraverse_mobile_seed_v2`，同时保留 v1。16 个
第三方 App 均能解析 launcher 并启动；每个 App 都保存了独立 GUI screenshot。数据侧的重要现场结论是：

- Retro 只展示超过其默认最小时长的媒体，因此 shared audio 改为 10 个带 title/artist 的 MP3，时长
  35–80 秒；VLC 同时可见这 10 个音频和 2 个视频。
- Simple Draw 通过系统文件选择器展示并打开 5 个 `Pictures/GUITRAVERSE/SimpleDraw/*.png`；不能把
  “文件存在”误写成 App 自带图库 DB。
- Audio Recorder 需要 app-owned M4A 与 `records.db` 索引；该版本 duration 列使用微秒，而不是毫秒。
- OsmAnd 读取 marker 时要求 `group_key=NULL`，名称使用其 `PointDescription` 序列化形状
  `location#<name>`；否则 DB 有行但列表仍为空或显示泛化名称。
- MiniWoB 普通 launcher 只能证明包可启动；内置页面 smoke 显式选择 `click-button` 并验证 utterance，
  没有点击任务目标。

run A 从 v2 启动后，精确删除一条 CallLog、删除 `photo_10.png`、开启 airplane mode，并在 Tasks 中勾选
`GUITRAVERSE Seed Review notes`。销毁 A 后从同一 snapshot 启动 run B：CallLog 恢复为 10、图片恢复、
airplane 回到 0，Tasks UI/XML 显示该条目重新为 unchecked；shared verify 报告
`read_only_b/guitraverse_mobile_seed_v2/20260830T130012Z_verify.json` 的 system/contacts/files/messages/
calendar/photos 六域全部为 true。

上述只证明当前 snapshot 的开发可用性和隔离性。因为 App seed 仍含开发期脚本/人工 setup，tracked apps
lock 不存在、assets lock 为 `draft`，也没有 profile/lock/code hash 完整绑定的 certificate，故不标记为
可开源发布完成。每次遍历或采集仍应从这个 snapshot 新建 read-only overlay；setup/seed/恢复证据不得进入
探索 Attempt、Capability 或训练轨迹。

这段 v2 live 结果是历史开发证据。正式 `ops/run_guitraverse_seeded_mobile.ps1` 要求操作者显式给出已经创建的
clean base，并传入 v2 manifest 生成按需 plan；显式 v1/v2 仅用于旧基线复验，不能替代新 run 的 plan apply/readback。
