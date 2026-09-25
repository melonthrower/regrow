# 怀疑者验证报告：三能力真伪交叉核验

> 方法：对每个能力做三方交叉 —— ①图节点原始 a11y 观测（遍历当时实机抓的 a11y.xml + elements.json）②合成能力 page_capabilities.json ③实机 episode 截图（260628ctrl / 260628fix）。observation 与 inference 分栏。不采信任何已有 review 结论，从原始数据重判。
>
> 数据根：`result_setting_qwen_0603_noopfix/gen_data/Qwen/0/nodes/<node>/`
> Episodes：`collections/OS/260628ctrl/setting/episodes/CAP00X*/`

---

## 能力 1：显示缩放 200%（Displays 页 Scale）

### 观测到的事实
- **源头①（原始 a11y）** `nodes/fdb2c8f336745875/a11y.xml`：grep 命中
  - `<radio-button name="100 %" st:checked="true" ...>`
  - `<radio-button name="200 %" st:enabled="true" ...>`
  - 全文搜 `Fractional`/`Scaling` → **0 命中**（原始树里这个 toggle 没有可读 name）。
- **源头①** `nodes/fdb2c8f336745875/elements.json`（33 元素）：
  - `'100 %'` radio-button id `9a8388f0`
  - `'200 %'` radio-button id `aecbd03c`
  - `''`（空名）toggle-button id `fc4f55ba` ← 即被合成解释为 Fractional Scaling 的开关
- **源头①截图** `nodes/fdb2c8f336745875/screenshot.png`：Displays 页，**Fractional Scaling 开关处于 OFF（灰）**，Scale 只有两格 **100% / 200%**；Resolution 1920×1080。
- **源头②（合成）** `page_capabilities.json`：`选择显示缩放比例` enum，values `["100%","200%"]`，element_map `100%→9a8388f0 / 200%→aecbd03c`。另有 `开启/关闭Fractional Scaling功能` boolean，element fc4f55ba，current=off。合成与原始一一对得上。
- **源头③（实机 episode CAP004_06d73c7b）**：step04 / final.png 等所有帧 Displays 页 **Fractional Scaling 开关 ON（绿）**，Scale 三格 **100% / 125% / 150%**，**完全没有 200%**；分辨率 1280×800。

### 为证伪做的尝试
- 专门对照「分数缩放关 vs 开」两种状态：图节点（OFF）截图 → 100/200；episode（ON）截图 → 100/125/150。GNOME 已知行为复现：Fractional Scaling 开会把 Scale 切成分数档并隐藏 200%。
- 看了 CAP004 step00（Network 页）、step04（150% 选中）、final（150%）多帧，排除「只看一帧误判」。

### 推测/解释（置信度）
- 200% 是 GNOME 真实控件，仅在 Fractional Scaling **关闭** 时出现。（置信度 高）
- CAP004 episode 永远到不了 200%，根因是**指令自相矛盾**：它要求「调到 200% 且开启分数缩放」——一开分数缩放，200% 档就消失。这是指令合成的逻辑冲突，不是 200% 不存在。（置信度 高）
- `fc4f55ba`（空名 toggle）被合成标成 Fractional Scaling 属合理推断（截图位置吻合），但 a11y 无 name 支撑，是合成补名而非原始抄录。（置信度 中高）

### 最终判定：**状态依赖（真实）**
- 前置条件：**Displays 页 Fractional Scaling 必须为 OFF**，Scale 才显示 100%/200%。
- 关键证据：原始 a11y.xml 实抓到 `radio-button name="200 %"`，且图节点截图（分数缩放 OFF）亲眼可见 100%/200% 两格 —— 不是造假；episode 因分数缩放被打开（同指令要求）故看不到 200%。

---

## 能力 2：Appearance（外观）面板

### 观测到的事实
- 能力对象节点 = **CAP001 target `ddfcaef6986c76c0`**（page_breakdown 自述「本页是系统外观设置页面」）。
- **源头①（原始 a11y）** `nodes/ddfcaef6986c76c0/a11y.xml`：grep 命中 `Appearance` ×6、`Light` ×4、`Dark` ×2、`Default` ×4、`Blue` ×8（accent 色名）。
- **源头①** `elements.json`：侧栏 `'Appearance' label`（两处：导航项 + 标题），页内 `'Light' label 19300424`、`'Dark' label 35119bd9`、3 个 toggle-button + 1 slider（Dock 设置控件）。
- **源头①截图** `nodes/ddfcaef6986c76c0/screenshot.png`：标准 Ubuntu 外观面板 —— Style(Light/Dark 缩略图)、Color(一排 accent 色块)、Desktop Icons、Dock(Auto-hide/Panel mode/Icon size/Position)。侧栏 Appearance 高亮。
- **侧栏入口在别处也实抓到**：200% 节点 `fdb2c8f336745875/elements.json` 有 `'Appearance' label dfe3c0d9`；Bluetooth 节点 `1aba47bfc201820c/elements.json` 有 `'Appearance' label 8c265faa`。多节点侧栏一致存在该入口。
- **源头②（合成）** `page_capabilities.json`：`切换系统主题` enum element_map `Light→19300424 / Dark→35119bd9`，与原始 elements.json 完全一致（抄录，非编造）。CAP001 caprefs 另有 `选择系统强调色` enum，element_map 为空（accent 色块当时未取到 id）。
- **源头③（实机 episode CAP001_ae8ee7bb，status=impossible）**：final.png 停在 **Background 页**（agent 跑偏），未停在 Appearance；该 episode VM（1280×800 态）侧栏下半段未见 Appearance 项（但属同一窗口滚动位置差异，且 episode VM 与图捕获时刻为不同状态）。

### 为证伪做的尝试
- 查「侧栏有入口 ≠ 功能可用」：直接看了 Appearance 页**实机渲染截图**（图节点），页面内容完整可交互，非空壳。
- 跨 3 个不同节点（appearance / displays / bluetooth）核对侧栏，Appearance 入口稳定存在，排除单帧偶然。
- 查 CAP001 为何 impossible：episode 跑偏到 Background，且指令里「青蓝色（teal）强调色」这一具体取值未必在 accent 色块里直接可选 —— 是任务执行/取值问题，不是面板不存在。

### 推测/解释（置信度）
- Appearance 面板真实存在且功能完整。（置信度 高）
- CAP001 被判 impossible 的真因是 episode agent 导航失败（落到 Background）+「青蓝色」具体 accent 取值匹配难，与面板存在性无关。（置信度 中高）

### 最终判定：**真实**
- 关键证据：图节点 `ddfcaef6986c76c0` 原始 a11y 实抓 `Appearance`/`Light`/`Dark`/accent 色名，截图为完整标准 Ubuntu 外观面板（Style+Color+Dock），合成的 Light/Dark element id 与原始 elements.json 逐一吻合。

---

## 能力 3：蓝牙（Bluetooth）设置

### 观测到的事实
- 能力对象节点 = **`1aba47bfc201820c`**（page_breakdown 自述「当前页面为蓝牙设置页，仅提供蓝牙总开关控制功能，当前蓝牙处于关闭状态」），亦是 CAP003 / CAP005 链路涉及节点。
- **源头①（原始 a11y）** `nodes/1aba47bfc201820c/a11y.xml`：grep 命中 `Bluetooth` ×12、`Turn` ×16、`Connected` ×2、`devices` ×6、`Switch`/`toggle`。
- **源头①** `elements.json`：标题/侧栏 `'Bluetooth' label`，页内 `'' toggle-button 75d21e65`（蓝牙总开关，无 name）。
- **源头①截图** `nodes/1aba47bfc201820c/screenshot.png`：标题「Bluetooth」，header 右上**有电源 toggle（OFF）**，正文「**Bluetooth Turned Off** — Turn on to connect devices and receive file transfers」。即**有可用蓝牙界面 + 开关**。
- **源头②（合成）** `page_capabilities.json`：`切换蓝牙开关` boolean。如实抄录开关存在。CAP003 meta 还引该节点 `开启/关闭蓝牙` boolean。
- **源头③（实机 episode CAP003_9f608ef3，status=complete True）**：step01.png Bluetooth 页显示「**No Bluetooth Found — Plug in a dongle to use Bluetooth**」，**header 无 toggle**。即 episode 运行时 **无蓝牙适配器**，开关不存在。

### 为证伪做的尝试
- 严格区分「无硬件 vs 有界面要分清」：
  - 图捕获时刻（Jun 4）：界面是 "Bluetooth Turned Off" + 有开关 → 当时**有适配器**，开关可用。
  - episode 时刻（Jun 28）：界面是 "No Bluetooth Found" + 无开关 → 当时**无适配器**。
- 查 CAP003 虽 complete True，但其蓝牙子目标在 episode 实机其实**无法执行**（无 toggle）；该 episode 同时含「鼠标主键改左手」子任务，complete 多半来自后者，蓝牙子目标被空过。
- 查侧栏：Bluetooth 入口在 appearance/displays/bluetooth 多节点 elements.json 均存在，入口稳定。

### 推测/解释（置信度）
- 蓝牙能力的**界面**真实存在；其**可用性（开关是否出现）依赖运行时是否存在蓝牙适配器**。图捕获态有适配器→开关在；episode 态无适配器→开关消失成提示页。（置信度 高）
- 合成把「切换蓝牙开关」当无条件能力，未编码「需有适配器」前置 —— 这是合成漏掉前置条件，但开关本身在捕获态是真控件，非凭空造假。（置信度 高）

### 最终判定：**状态依赖（真实，但运行时易失效）**
- 前置条件：**系统须存在蓝牙适配器**，header toggle 才出现、才能开关；无适配器时蓝牙页降级为 "No Bluetooth Found" 无可操作开关。
- 关键证据：图节点原始 a11y 实抓 `toggle-button 75d21e65` + "Bluetooth Turned Off"（有适配器态）；同一蓝牙页 episode 截图为 "No Bluetooth Found" 无 toggle（无适配器态）—— 两态对照证明是状态依赖而非造假。

---

## 三能力判定汇总

| 能力 | 判定 | 一句关键证据 |
|---|---|---|
| 显示缩放 200% | **状态依赖（真实）** | 图节点 a11y 实抓 `radio-button name="200 %"`，截图分数缩放 OFF 时见 100%/200%；episode 分数缩放 ON 故只剩 100/125/150。前置=Fractional Scaling 关。 |
| Appearance 面板 | **真实** | 节点 `ddfcaef6986c76c0` a11y 实抓 Appearance/Light/Dark/accent 色名，截图为完整外观面板；合成 Light/Dark id 与原始 elements.json 逐一吻合。 |
| 蓝牙设置 | **状态依赖（真实）** | 图节点 a11y 实抓蓝牙开关 toggle + "Bluetooth Turned Off"（有适配器）；同页 episode 截图 "No Bluetooth Found" 无 toggle（无适配器）。前置=系统有蓝牙适配器。 |

> 三者均**非合成造假**：每个声称的控件/取值都能回溯到原始 a11y.xml / elements.json。两个为状态依赖（200%←分数缩放关；蓝牙←有适配器），一个为真实。所有 episode 失败/未达成都源于运行时状态错配或指令逻辑冲突（200% 指令自带矛盾），而非能力本身不存在。
