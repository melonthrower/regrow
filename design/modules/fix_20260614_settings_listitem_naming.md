# 修复：移动端 Settings 列表项漏遍历（命名 → uid 塌缩）

日期：2026-06-14
分支：`feat/aliyun-provider`
改动文件：`gui_rewalk/env/android_a11y_converter.py`（`_first_descendant_name`）

## 现象
手机端遍历 AOSP Settings 主页时，Connected devices、Battery 等按钮没有被
探索到。最初怀疑是"没有下滑、滚动发现失效"。

## 根因（基于真实产物 `_android_check/full/0/nodes/dfc53e48b07d70b5/a11y.xml` 实测）

不是滚动问题——这些按钮**就在第一屏、在 a11y 树里、`showing="true"`**。

真正的因果链：

1. **命名（病根）**：Settings 行的结构是
   `list-item > [icon_frame, text_frame > (title, summary)]`。
   converter 的 `_first_descendant_name` 用深度优先取「第一个有名子孙」，
   而 `icon_frame`（name="icon frame"）排在 `text_frame/title` 之前，
   于是每一行的 name 都被取成 **"icon frame"**，真实标题
   （"Connected devices" 等，在 `android:id/title` label 上）被忽略。

2. **uid 塌缩（放大器）**：`compute_global_uid` 的 identity = name。
   5 行 name 全是 "icon frame"、role 全是 list-item，只剩粗粒度 zone
   （3×3 横向分区）区分 → 5 行塌成 **2 个 global_uid**。

3. **去重跳过（表现）**：`exploration_memory` 按 global_uid 去重，遍历器
   认为只有 2 个不同按钮 → Connected devices/Battery 被当作 Network/Apps
   的重复项跳过 → "漏遍历"。

## 为什么不用 VLM 命名修
- 真实标题已是 a11y ground truth，无需用截图 OCR 近似重新获取。
- `_apply_vlm_semantic_overrides` 注释明确：「附加语义标签但**不改变可执行
  a11y 身份**」——它只加 `vlm_semantic_name` 字段，**不重算 global_uid**。
  且 uid 在 VLM override **之前**就已算好并完成去重塌缩。所以 VLM 命名再准
  也改不了遍历行为，只改显示标签。
- VLM 命名保留给「a11y 确实无文本」的纯图标元素兜底，不用于此 bug。

## 修复
重写 `_first_descendant_name` 为三级取名（forest / uiautomator 两条转换
路径共用此函数，一处修复同时覆盖）：
1. 优先 `:id/title` label（AOSP 精确命中）。
2. 否则取第一个**非结构容器**的 label/text（跳过 resource-id 末段为
   icon_frame/text_frame/... 或 name 为 "icon frame" 等的结构节点）——
   不绑死 `android:id/title` 字面量，对第三方 app 也有泛化兜底。
3. 都没有 → 退回原「第一个有名子孙」行为（纯图标行不回归）。

只取 title，**不拼 summary**：summary 易变（"100%"、SSID、配对状态），
拼进 name 会让 uid 跨 run 漂移。

## 验证（离线、不开虚拟机）
脚本对 `_android_check` 下 25 个真实 `a11y.xml` 跑修复后的取名 + uid：
- 97 个 list-item，**0 个**仍为结构容器名（修复前 13 个页面中招）。
- dfc53e48：**2 → 7 个唯一 uid**，7 行（含原 showing=false 的 Storage）
  全部得到真实标题与独立身份。
- RESULT: PASS。

## 未做 / 后续
- **uid 算法加固**（同名时纳入行序）：本次**未做**。命名修复后 97 行已自然
  唯一，无塌缩实证；改 uid 会让历史 run 的 explored 记录全失配（blast
  radius 大）。等实际遍历再观察到同名塌缩，用真实案例针对性改。
- **物理滚动发现**（真·屏外、第二屏外的元素）：与本修复正交，仍待做。
  根因 = a11y 捷径对 uiautomator dump 无效（只 dump 当前视口）+
  `android_controller._scroll` 只认 dy/dx、对 `direction/amount` 是 no-op。
  需开 AVD 验证，单列为下一个任务。
