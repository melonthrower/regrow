# 待解决问题：桌面端滚动导致的同页分裂（结构身份的桌面侧）

日期：2026-06-15
状态：**已确认存在，方案未定，待处理**（移动端先行，见 design_decisions.md D16）
关联：D16（结构化元素身份）、D11（发现型 SCROLL）、D15（移动端物理滚动发现）

## 问题

`compute_global_uid`（`gui_rewalk/src/core/graph/exploration_memory.py:53`）
用 `app_name|role|name|z{3×3屏幕网格zone}` 做有名元素的身份。zone 含纵向
行分量 → 元素被滚动推过网格行边界时 uid 漂移 → 同一逻辑页面分裂成多个
state id。

**这不是移动端专属。** 桌面端真正会滚动的应用同样中招：

- GNOME Settings（`result_setting_qwen_0603_noopfix`，49 节点 1427 元素）：
  **0 撞 uid** —— 但这是因为它用分页/侧边栏导航、几乎不滚动，是特例。
- VS Code（`result_vscode_0611_fix`，27 节点；Extensions / Keybindings /
  编辑器都是长滚动列表）：`tools/probe_desktop_split.py` 实测
  **34 对疑似同页分裂**，`258f89a0` vs `cc03107a` 元素名集合 **jaccard=0.99**。

## 为什么不能照搬移动端方案

移动端（D16）的结构锚是 **resource-id 容器链**（uiautomator 提供，
如 `com.android.settings:id/settings_homepage_container`）。

桌面端 **没有 resource-id**（GTK 和 VS Code 实测均为 0）。可用的结构锚是
**命名容器 tag + name**：
- `list = Extensions`、`list = Keybindings`
- `page-tab-list = Active View Switcher`
- `tool-bar`（12 个中 9 个有 name）
- list-item 36 个全部有 name

思路与移动端一致（"元素在哪个命名容器内"），但锚来源不同，需要桌面专属的
容器链提取 + **单独验证该锚对滚动是否真的稳定**（移动端已验证，桌面端未验证）。

## 待办（落地前）

1. 找到 VS Code 同一滚动列表"滚动前/滚动后"的两个真实节点对（或新跑一轮带
   滚动的桌面遍历），验证"命名容器 tag+name"锚在滚动前后是否产出一致 sig。
   —— 移动端是用 `4ea30233`(8元素) vs `a8a82dd7`(21元素) 验证的，桌面端需要
   等价的滚动前后样本。
2. 注意桌面端 D15 目前走 a11y `include_offscreen` 捷径、**不做物理滚动聚合**，
   所以现存档里的"分裂"可能来自别的滚动触发（编辑器滚动、面板展开），
   需确认分裂的具体触发链，不要想当然。
3. 设计 `compute_global_uid` 的桌面分支：`app_name|role|命名容器tag+name|name`，
   同名同容器时 fallback 坐标 zone（与移动端同构的分层兜底）。

## 验证脚本（read-only，已存）

- `tools/probe_desktop_split.py` —— 检测同页分裂（jaccard>0.8 不同 state id）
- `tools/probe_structural_identity.py` / `_v2.py` —— 移动端结构身份验证（可改造
  成桌面版：把"resid 链"换成"命名容器 tag+name 链"）

## 优先级

在移动端 D16 落地、跑通一轮验证之后再做。桌面端遍历当前以 GTK 桌面应用为主，
分裂虽确认存在但尚未阻塞主线；VS Code 这类滚动重的应用扩展时优先处理。
