# GUITRAVERSE Traversal Seed v2 Design

日期：2026-08-30
状态：已获得用户方向批准；已有 live-validated v2 snapshot prototype，但 tracked replay/lock/certificate
尚未闭合，不能称为开源发布完成。

## 1. 目标

构建可开源、可审计、可重放的 `guitraverse_mobile_seed_v2`，专门服务黑盒 GUI 完整遍历。
它从现有 v1 whole-AVD 基线派生，安装 AndroidWorld 的 16 个第三方应用，处理稳定 onboarding 和权限，
并为数据驱动应用注入约 10 条具有不同形态的合成数据。每个应用必须分别通过安装、数据和 GUI
可见性验收；全部必需项通过后才发布新的 immutable whole-AVD snapshot。

Traversal seed 的职责是显露列表、详情、搜索、筛选、编辑、参数选择、删除候选和同质代表等 GUI
结构，不承载某一条用户任务或跨应用故事。统一人物/会议故事保留为后续 collection scenario delta，
不进入本轮实现，也不写入 v2 baseline。

## 2. 非目标与边界

- 不调用 AndroidWorld 官方任务的 `initialize_task()`、`tear_down()`、evaluator 或具体任务参数。
- 不导入 MobileWorld/OSWorld 的官方任务对象、指令、成功条件、轨迹或评测资产。
- 不把 seed setup、数据查询、GUI smoke 或 snapshot restore 写入探索 Attempt、Capability 或采集轨迹。
- 不登录真实账号，不产生真实短信、邮件、上传、分享、购买或外部授权。
- 不为每个探索任务保存 whole-AVD snapshot；v2 只有一个发布基线，运行使用 read-only overlay。
- 不在公开仓库或发布镜像中直接再分发许可证不明确的第三方 APK。
- 不在本轮实现 persona/scenario delta、桌面 seed adapter 或 benchmark eval seed。

## 3. 参考工作的取舍

### 3.1 AndroidWorld

复用：分应用 setup 思路、官方 APK 文件名/来源、低层 permission/onboarding 经验、合成文件与媒体生成、
emulator 入站 SMS、provider 查询和 SQLite 只读验证。

不复用：默认 `pm clear`、整表 DELETE、全盘 `/sdcard` 清理、单包 `/data/data` app snapshot、任务
initialize/teardown，以及无 SHA/signature/version 核验的下载缓存。官方 onboarding 若只抛 warning 也不能
在 GUITRAVERSE 中被视为通过。

### 3.2 MobileWorld

复用“设备基线 + 独立后端/数据基线 + 小型 task delta”的分层思想，以及数据库/本地存储/callback
多路验证。当前 v2 没有自托管后端，因此只实现设备与应用数据基线；未来含后端应用时再增加 backend lock。

### 3.3 OSWorld / OSWorld 2.0

复用“共享 base snapshot + 可重放 setup”与不可变 release manifest：发布结果必须固定代码提交、镜像、
任务/资产版本和实际 provider。开发 traversal seed 与正式 benchmark eval seed 永久隔离。

## 4. 总体架构

```text
apps.lock.yaml
  + traversal_seed_v2.yaml
  + synthetic asset generators
  + app adapters
        -> inspect
        -> plan
        -> install/setup/seed
        -> verify_data
        -> verify_gui
  + whole-AVD publisher
        -> seed certificate
        -> guitraverse_mobile_seed_v2
```

### 4.1 文件布局

```text
data/dev_seed/guitraverse_mobile_apps_v2.lock.yaml
data/dev_seed/guitraverse_mobile_assets_v2.lock.yaml
data/dev_seed/guitraverse_explore_seed_v2.yaml
tools/guitraverse_seed/
  contracts.py
  installer.py
  orchestrator.py
  reports.py
  adapters/
tools/guitraverse_mobile_seed.py
tests/test_guitraverse_seed_*.py
artifacts/guitraverse_seed_reports/guitraverse_mobile_seed_v2/
```

现有 `tools/guitraverse_mobile_seed.py` 保留为薄 CLI 入口，v1 读取与 verify 继续兼容；实现移到小型 package，
避免 16 个应用继续堆入一个脚本。v2 不修改 `gui_rewalk` 探索账本或 Capability schema。

## 5. 锁文件与开源发布

`apps.lock.yaml` 的每个 APK 条目必须包含：

- adapter ID、应用显示名；
- 官方 GCS object/URL；
- APK SHA-256 与字节数；
- package、versionName、versionCode；
- signer certificate SHA-256；
- ABI 与最低/目标 SDK；
- 上游项目、源码 tag/commit；
- SPDX license、再分发状态、商标或修改版要求；
- AndroidWorld 参考文件名与本项目核验时间。

下载顺序为 `download -> size/hash -> aapt/apksigner metadata -> install -> pm/dumpsys recheck`。任何字段不匹配
都在 onboarding 和 seed 前停止。若一个应用有 ABI fallback，lock 明确列出候选及当前 x86_64 选中项。

开源仓库发布 downloader、lock、adapter、生成器和 certificate schema；无明确再分发权的 APK 由用户本地
下载。顶层 Apache-2.0 不能替代每个应用的独立许可证判断。

`assets.lock.yaml` 固定每个下载资产或生成器的来源、许可证、SHA-256、生成参数和工具版本。音频/视频
不依赖构建主机偶然安装的 ffmpeg；使用固定版本的本地生成工具或锁定 digest 的 media-generator 容器，
输出文件再逐项 hash。这样 Retro/VLC 的标题、艺术家、时长和视频编码可复现，服务器缺少 ffmpeg 时也
不会在首条设备写入后才失败。

## 6. Adapter 合同

每个应用 adapter 实现同一职责边界：

```text
inspect(context) -> AppInspection
plan(profile, inspection) -> AppPlan
install(plan, confirmation) -> InstallReport
setup(plan, confirmation) -> SetupReport
seed(plan, confirmation) -> SeedReport
verify_data(profile) -> DataVerification
prepare_runtime(profile) -> RuntimePreconditionReport
verify_gui(profile, screenshot) -> GuiVerification
```

公共 context 固定 serial、专用 AVD 名、系统镜像 fingerprint、emulator/ADB 版本、SDK、locale、profile、
manifest digest 和 release ID。所有写操作要求 confirmation 精确等于 `guitraverse_mobile_seed_v2`。

Adapter 必须幂等：第二次 apply 不增加重复 seed-owned rows。仅在全新安装、发布 snapshot 之前，允许对该
新安装 package 精确执行一次初始 `pm clear`；遍历、resume、普通恢复、task delta 和 snapshot 发布后均禁止。

Provider/files/media 只 upsert 带稳定 seed ID 的对象。SQLite 仅用于没有稳定 Provider 的固定 APK，且要求：

- package/version/schema fingerprint 完全匹配；
- force-stop 后操作；
- 备份 DB 及存在的 WAL/SHM；
- 只修改 seed-owned rows，不整表 DELETE；
- 写后查询、重新启动 App、GUI smoke；
- 失败时恢复备份并保持 v2 未发布。

Onboarding 可以使用 out-of-band AndroidWorld controller/UI selector，但必须按 package + version + SDK 注册，
每一步保存前图、动作、后图和后置条件。固定 sleep 不能单独证明成功；异常和缺失 selector 都是失败。

### 6.1 平台独占角色

默认短信、电话和浏览器等系统角色同一时刻只能绑定一个 App。v2 baseline 固定 Google Messages、Google
Dialer 和 Chrome 为默认角色，certificate 保存实际 role holder。Simple SMS 等需要独占角色才能显示完整
数据的应用，不在 baseline 中永久抢占；其 adapter 的 `prepare_runtime()` 只在该 App 的 read-only GUI
smoke/遍历 overlay 中切换角色并验证，实例销毁后 v2 自动恢复。该 precondition 是环境证据，不进入探索
Attempt 或用户指令。

## 7. 应用范围与数据目标

### 7.1 AndroidWorld 16 个第三方应用

| Adapter | Package | Traversal seed 目标 | 数据验证 |
|---|---|---|---|
| Markor | `net.gsantner.markor` | 10 个 Markdown/TXT 笔记，分目录、长短和 checklist | 精确文件 + GUI 列表 |
| Clipper | `ca.zgrs.clipper` | 1 个结构化 current clipboard 值；该 APK 不提供历史列表 | `clipper.get` + GUI |
| Simple Calendar | `com.simplemobiletools.calendar.pro` | 10 个过去/今天/未来/重复事件 | 固定 schema DB + GUI |
| Tasks.org | `org.tasks` | 10 个完成/未完成、优先级、due/无 due 任务 | 固定 schema DB + GUI |
| Simple Draw | `com.simplemobiletools.draw.pro` | 5 个不同尺寸/颜色 PNG | 系统 picker 可见 + 代表项可打开 |
| Simple Gallery | `com.simplemobiletools.gallery.pro` | 共享 10 张照片，多个目录/尺寸 | MediaStore + GUI 相册 |
| Simple SMS | `com.simplemobiletools.smsmessenger` | 共享 10 条入站短信和多个会话；overlay 中临时切换默认 SMS | SMS Provider + GUI |
| Audio Recorder | `com.dimowner.audiorecorder` | 5 个不同长度的 app-owned M4A | `records.db` 索引 + GUI |
| MiniWoB++ | `com.google.androidenv.miniwob` | 使用内置任务页面，不注入伪记录 | launcher + 内置页面 smoke |
| Pro Expense | `com.arduia.expense` | 10 条不同日期、金额、分类、备注的支出 | 固定 schema DB + GUI |
| Broccoli | `com.flauschcode.broccoli` | 10 个不同分类/收藏/食材长度的菜谱 | 固定 schema DB + GUI |
| OsmAnd | `net.osmand` | 官方离线地图 + 10 个本地 marker | nullable group key + serialized description + GUI |
| OpenTracks | `de.dennisguse.opentracks` | 3–5 条不同距离/时长的合成轨迹 | 固定 schema DB + GUI |
| VLC | `org.videolan.vlc` | 共享 10 个音频及 2 个视频 | MediaStore/VLC scan + GUI |
| Joplin | `net.cozic.joplin` | 3 个 folder 中 10 个 note/todo | 固定 schema DB + GUI |
| Retro Music | `code.name.monkey.retromusic` | 共享 10 个带稳定标题/艺术家的音频 | MediaStore + GUI |

“约 10 条”是数据型应用的覆盖目标，不强迫 MiniWoB、Draw、Recorder 或 OpenTracks 制造十条低价值同质项。

### 7.2 已有 Google/系统应用

- Contacts：扩展到 10 个 reserved-number 联系人；
- Messages：扩展到 10 条入站短信，与 Simple SMS 共享 Provider；
- Google Calendar：10 个系统 Provider 事件，包含每周重复项，降低日期老化；
- Files/Photos：共享 24 个对象：2 个文档、10 张图片、10 个带标签 MP3 和 2 个视频；
- Dialer：10 条合成 call-log 记录，并验证联系人关联；
- Clock：显式建立 07:15、18:40 两个闹钟和 London 世界时钟，不能再依赖 snapshot 隐含数据；
- Chrome：完成 onboarding，使用本地稳定页面/书签做少量展示数据，不依赖真实账号；
- Settings/Camera：固定系统状态并完成基础 GUI smoke，不为凑数量制造对象。

## 8. 数据形态，而非数量打卡

每个约 10 条的数据域至少覆盖适用形态：

- 已完成/未完成、普通/高优先级；
- 过去/今天/未来/周期重复；
- 短文本/长文本/checklist；
- 多目录、多分类、收藏与非收藏；
- 同质列表成员和明显不同的分支对象；
- 可搜索、可打开详情、可编辑、可安全删除的代表项；
- 一个空子目录/空分类或可产生无结果的搜索词；
- 稳定 ASCII seed ID 与自然显示名分开保存。

Traversal seed 允许媒体在 Files/Photos/Gallery/VLC/Retro 之间共享，短信在 Google Messages/Simple SMS 之间
共享，但不构造“会议故事”或预期跨应用任务。共享只减少重复数据并显露真实平台连接。

## 9. 构建流程

```text
v1 immutable snapshot
  -> 新的 writable v2 builder AVD
  -> preflight 系统/磁盘/serial/AVD/image
  -> 下载并锁定 16 个 APK
  -> 安装并验证 16 个 package/launcher/version/signer
  -> 分应用 setup onboarding/permissions/defaults
  -> apply core shared provider/files/media seed
  -> apply 16 个 app adapter seed
  -> read-only data verification
  -> 逐 App GUI smoke
  -> whole-device verification
  -> save guitraverse_mobile_seed_v2
  -> 两个 read-only overlay 隔离验收
  -> 发布 certificate
```

安装、setup、seed、verify 的每一步都可 resume，但 resume 必须从 report 判断准确阶段，不能重复 destructive
setup。任一 mandatory App 失败时 v2 状态为 draft/partial，不保存或覆盖正式 v2 snapshot。

## 10. 验收与 Certificate

### 10.1 安装验收

- 16/16 APK 下载 hash/size 匹配；
- 16/16 package、version、signer、ABI 匹配；
- 16/16 launcher 可解析并启动；
- 版本化 onboarding/permission 后置条件通过。

### 10.2 数据验收

每个 adapter 输出 `expected_count/observed_count/seed_ids/query_evidence`。必须区分：

- `installed`；
- `setup_complete`；
- `data_verified`；
- `gui_verified`；
- `snapshot_verified`；
- `partial_reason`。

总数量不能掩盖单应用失败；provider/DB/file 成功不能冒充 GUI 可见。

### 10.3 GUI smoke

逐 App 从同一 builder 状态启动，保存首帧和进入主数据列表后的截图，确认：

- 当前包/Activity 正确；
- onboarding、权限、默认应用选择不再阻挡；
- 至少一个 seed 代表在真实 UI 可见；
- 搜索/详情/分类等关键数据形态可到达；
- 无外部登录依赖。

需要默认应用/独占 role 的 GUI smoke 从独立 read-only overlay 执行 `prepare_runtime()`；报告必须同时保存
切换前 role、切换后 role 和新实例恢复的 baseline role。不能为了让第二个短信 App 通过而永久改变 v2。

GUI smoke 是环境证据，不写探索图。完整 Luna 遍历在 v2 发布后另起 run，并继续按 saved-frame、teacher-
supervised live、unsupervised Luna-only 分开报告。

### 10.4 Snapshot 隔离

read-only run A 至少修改：一个共享 Provider、一个 `/sdcard` 文件、一个 app-private DB 和一个系统设置；
销毁后 run B 从 v2 启动，逐项 verify 全部恢复。v1 和 v2 都保留，v2 不原地升级。

### 10.5 Release Certificate

Certificate 固定：

- release ID、代码 commit、manifest/lock hash；
- Android image fingerprint、emulator/ADB 版本、renderer flags；
- AVD 名、snapshot 名、snapshot list 与保存时间；
- 每 App 安装/setup/data/GUI 状态及证据路径；
- seed generator version、PRNG seed、展开后的实际对象；
- APK/assets provenance 与许可证；
- run A/run B 隔离结果；
- 已知 gap 与 v2 的 `valid_until`。

## 11. 安全与证据边界

- 所有手机号使用保留号段，姓名、地点、内容均为合成数据；
- SMS 仅 emulator inbound，不产生真实外发；
- 不保存 API key、Authorization、真实账号或私有 endpoint；
- 下载只允许 lock 中的 HTTPS GCS object；重定向目标和最终 hash 必须匹配；
- 文件删除只作用于精确 seed-owned 路径；DB 删除只作用于 seed-owned primary keys；
- Snapshot 保存前必须 data verify + GUI verify 全通过；
- 初始化失败单独归为 environment/seed failure，不计作 Agent 或探索失败；
- traversal dev seed 与 AndroidWorld/MobileWorld/OSWorld 正式 eval 状态永久隔离。

## 12. 实施成功标准

本轮实现只有同时满足以下条件才完成：

1. v2 manifest、apps lock、adapter contract 和 certificate schema 通过离线测试；
2. 16 个第三方应用在专用 builder AVD 安装并通过 metadata/launcher 验证；
3. 数据型 adapter 达到约定数量和形态，全部 read-only verify 通过；
4. 16/16 GUI smoke 有独立截图和结构化结果；
5. `guitraverse_mobile_seed_v2` 保存并 listed；
6. 两个 read-only overlay 隔离验收通过；
7. v1、用户密钥、旧 run 和其他 qemu 未被修改；
8. 代码、文档、测试和验证记录形成可分离的本地 Git 提交，不自动 push。
