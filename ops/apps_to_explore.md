# 待探索应用清单（遍历/采集目标）

> 目的：对齐 **android_world**（移动端）+ OSWorld/GNOME（桌面端），作为图遍历与轨迹采集的目标应用集，并跟踪安装/种子进度。
> 图例：✅ 完成 ⬜ 待做 ⚠️ 有问题/受限

---

## 一、移动端（对齐 android_world，共 ~23 个）

**种子机**：deploy-asr 上 AVD `Small_Phone_seeded`（`default_boot` 快照）。
**启动必带 `-feature -Vulkan`**（VLC 用 Vulkan，否则 `adb emu avd snapshot save` 报 `UNSUPPORTED_VK_APP`）。
**关键结论：全部不需要登录、不需要代理**——android_world 故意用本地离线应用，数据由任务运行时现造（我们遍历 UI 即可）。

### 系统应用（7，模拟器自带）
| 应用 | 包名 | 类别 | 安装 | 数据种子 | 备注 |
|---|---|---|---|---|---|
| Settings | com.android.settings | 系统设置 | ✅ | — | 主测对象，长页/滚动多 |
| Files | com.google.android.documentsui | 文件管理 | ✅ | ✅ | 已灌文件 |
| Contacts | com.android.contacts | 联系人 | ✅ | ⚠️ | A13 无头种联系人未通 |
| Dialer | com.android.dialer | 电话 | ✅ | ⬜ | |
| Clock | com.google.android.deskclock | 时钟 | ✅ | ⬜ | 闹钟列表=同质项测试场景 |
| Chrome | com.android.chrome | 浏览器 | ✅ | — | 不登录直接浏览 |
| Camera | com.android.camera2 | 相机 | ✅ | — | 非数据驱动 |

### 第三方应用（16，装 APK，来源 `storage.googleapis.com/gresearch/android_world/`）
| 应用 | 包名 | 类别 | 安装 | 数据种子 | 备注 |
|---|---|---|---|---|---|
| Markor | net.gsantner.markor | Markdown 笔记 | ✅ | ✅ | 已灌笔记 |
| Joplin | net.cozic.joplin | 笔记 | ✅ | ⬜ | 可用 create_note 种 |
| Tasks.org | org.tasks | 待办 | ✅ | ✅ | sqlite add_tasks |
| Simple Calendar Pro | com.simplemobiletools.calendar.pro | 日历 | ✅ | ✅ | 已灌今天/未来一周事件 |
| Simple SMS Messenger | com.simplemobiletools.smsmessenger | 短信 | ✅ | ⚠️ | A13 无头种短信未通 |
| Simple Gallery Pro | com.simplemobiletools.gallery.pro | 相册 | ✅ | ✅ | 已灌图片 |
| Simple Draw Pro | com.simplemobiletools.draw.pro | 画图 | ✅ | ⬜ | |
| Retro Music | code.name.monkey.retromusic | 音乐播放 | ✅ | ✅ | 已灌 mp3 |
| VLC | org.videolan.vlc | 媒体播放 | ✅ | （用音乐） | ⚠️ Vulkan→需 `-feature -Vulkan` |
| Audio Recorder | com.dimowner.audiorecorder | 录音 | ✅ | ⬜ | |
| Pro Expense | com.arduia.expense | 记账 | ✅ | ⬜ | 可用 create_receipt 种 |
| Broccoli | com.flauschcode.broccoli | 菜谱 | ✅ | ⬜ | |
| OpenTracks | de.dennisguse.opentracks | 运动轨迹 | ✅ | ⬜ | 需 GPS 轨迹，难种、收益低 |
| OsmAnd | net.osmand | 离线地图 | ✅ | （自带地图） | 不用种 |
| Clipper | ca.zgrs.clipper | 剪贴板 | ✅ | ⬜ | |
| MiniWoB++ | com.google.androidenv.miniwob | 网页任务 | ✅ | （内置） | webview 内任务 |

### 数据种子状态
- **已种（6）**：Gallery、Markor、Retro Music、Files、Calendar、Tasks
- **可种（android_world 工具现成）**：Joplin（create_note）、Pro Expense（create_receipt）、Broccoli、Contacts（add_contact）
- **难种/低收益**：SMS、Contacts（A13 无头锁死）、OpenTracks（GPS）
- **不用种**：OsmAnd（自带地图）、Camera/Settings/Chrome（非数据驱动）、VLC（用 Music）、MiniWoB（内置）

### MobileWorld 对标集合（与 AndroidWorld 清单分开）

官方 `mw info app` 返回 20 项：15 个 GUI 应用为 Calendar、Camera、Chrome、Clock、Contacts、Docreader、
Files、Gallery、Mail、Maps、Mastodon、Mattermost、Messages、Settings、Taodian；其余
`MCP-Amap/Github/arXiv/jina/stockstar` 是工具服务，不是 GUI 应用，不能计入遍历完成数。
MobileWorld 使用自己的容器镜像、应用后端和快照，不能用本节 AndroidWorld seeded AVD 的同名应用结果替代。

---

## 二、桌面端（OSWorld / GNOME）

**种子**：js1 上 `/tmp/System_seeded.qcow2`（docker provider, 种子 commit 进 base→重启 revert 回种子态）。
**VM 已装全部 OSWorld app（实测 2026-06-30）**：chrome/gimp/thunderbird/vlc/libreoffice/code/firefox/nautilus/gnome-terminal/gnome-control-center 全 ✓ → 无需安装, 只需建图+种子。
**对齐目标 = OSWorld 10 域**（`OSWorld/evaluation_examples/examples/`）：chrome、gimp、libreoffice_calc、libreoffice_impress、libreoffice_writer、vlc、thunderbird、vs_code、os、multi_apps。

| OSWorld 域 | 应用 | 遍历状态 | 种子(固定预制样本) | 备注 |
|---|---|---|---|---|
| chrome | Chrome (google-chrome) | ⬜ 待建图 | 起始页/书签(已灌Chrome书签) | **OSWorld 用 Chrome 非 Firefox** |
| gimp | GIMP | ✅ 有图(本地VMware) | png ✅已验证 | 待在docker种子VM重跑 |
| libreoffice_calc | LibreOffice Calc | ⬜ 待建图 | .xlsx/.csv | **独立域, 之前没单独做** |
| libreoffice_writer | LibreOffice Writer | ✅ 有图(本地) | .docx/.txt | |
| libreoffice_impress | LibreOffice Impress | ✅ 有图(本地) | .pptx ✅已烤入(quarterly_review.pptx, soffice造) | 待docker种子VM重跑 |
| vlc | VLC | ✅ 有图(本地) | 媒体 ✅已烤入(sample_clip.mp4+sample_tone.mp3, ffmpeg造) | 待docker种子VM重跑 |
| thunderbird | Thunderbird | ⬜ 待建图 | ✅已烤入(OSWorld预配profile, 账号anonym-x2024@outlook.com) | profile自动带账号, 直接launch |
| vs_code | VS Code | ✅ 有图(本地) | 打开文件夹(已灌VSCode项目) | |
| os | GNOME Settings | ✅ 本地图(51节点) | — | 左侧栏21项=跨节点共享按钮 |
| os | Files (Nautilus) | ✅ 有图 | 已灌Documents/Pictures | |
| os | Terminal (gnome-terminal) | ⬜ 待建图 | — | os 域含终端 |
| multi_apps | 跨应用组合 | ⬜ 待做(#34) | 多app | calc→todo 类 |

**非 OSWorld(我们多探的 GNOME 工具, 降为 bonus, 对齐时不优先采)**：Calculator、gedit、Firefox(被Chrome取代)、clocks/mines/seahorse/... 等。

**校准结论**：
- **待补齐(对齐缺口)**：Chrome、LibreOffice Calc、Thunderbird、Terminal、multi_apps;
- 已有图都是在**本地 VMware** 建的, 需在 **docker 种子 VM 重跑** 以与采集环境(System_seeded.qcow2)一致;
- 种子一律**固定预制样本**(确定性, 防 hard reset 间漂移); Thunderbird 另需账号。
- **种子进度 (2026-06-30)**: Impress/VLC/Thunderbird 已烤进 System_seeded.qcow2(详见 memory desktop-seeded-baseline 第二轮补种)。三应用 + 已有的 Calc/Writer/GIMP/VSCode/Files/Chrome 种子齐 → 桌面 10 域种子层完成, 剩待办=在 docker 种子 VM 上重跑建图(本地图需迁到种子环境一致)。⚠️ config.py 的 impress/vlc seed 接线仅本地, js1 跑前需部署。

---

## 三、关键约束与接续点
1. **启动模板**：移动端 read-only 遍历实例须带 `-feature -Vulkan`（否则 VLC 致快照不可存；read-only 不存快照但保持一致）。
2. **无登录/无代理**：android_world 应用全本地，验证过 deploy-asr 直连中国服务正常；翻墙那一圈非必需（已放弃）。
3. **接续点**：种完该种的 → 重存 `default_boot` 快照 → 部署最新视觉栈（grounding+按钮身份+共享去重+同质列表去重）→ `--vlm_grounding` 批量遍历采集。
4. 遍历框架去重层级（见 visual_engine）：外观 uid（全局）+ 名字（chrome/共享=全局，普通行=按状态）+ 状态判同忽略列表条数 + 同质列表代表项（待加）。
</content>
