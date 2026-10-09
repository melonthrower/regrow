# Region边界修改地图

源码版本：[`5e890bb555a6dd0ab55b88178f5f3883bf72f179`](https://github.com/melonthrower/regrow/commit/5e890bb555a6dd0ab55b88178f5f3883bf72f179)（私有 melonthrower/regrow，分支 codex/regrow-initial）；候选冻结源码 hash `bd86c1b0d29328c42be74cf7aeb556b10b6d73a1573496c47417e8e2c4e26fac`。下列是已实现的改动及核对后保留的连接，不是待实施方案。设计见[Region边界与可交互范围](REGION_BOUNDARY_SCOPE.md)。

| 仓库相对路径与行范围 | 函数 | 当前行为 |
| --- | --- | --- |
| `experiments/clock_manual_20260919/foreground_scope.py:7-17` | `guidance` | 说明区块留白与输入接管不同，不要求矩形包含 |
| `experiments/clock_manual_20260919/foreground_scope.py:84-111` | `audit` | Region框只检查非空、未倒置和原图范围，控件检查保留 |
| `experiments/clock_manual_20260919/foreground_scope.py:114-134` | `remember` | 同帧按已确认可交互身份保存边界，局部清点保留其他分区 |
| `experiments/clock_manual_20260919/registration_diagnostics.py:31-41` | `region_surface` | 按真实原图判断边界资格；缺图不作控件归属几何证明 |
| `experiments/clock_manual_20260919/registration_diagnostics.py:44-188` | `collect` | 发现图1、更新图2或显式frame用于原归属诊断 |
| `experiments/clock_manual_20260919/repair_stages.py:75-121` | `accept_candidate` | 解析run相对的更新图2，传入正常接受检查 |
| `experiments/clock_manual_20260919/register_update.py:385-433` | `materialize_regions` | 登记重检保留同一来源图 |
| `experiments/clock_manual_20260919/register_update.py:436-482` | `save_region_images` | 仅Region模板跳过foreground包含检查 |
| `experiments/clock_manual_20260919/register_update.py:108-382` | `commit_update` | 普通更新图2和来源拆分图1传到登记 |
| `experiments/clock_manual_20260919/discovery_step.py:82-222` | `commit` | 发现当前帧传到登记 |
| `experiments/clock_manual_20260919/region_behavior_split.py:62-100` | `apply` | 来源区块拆分的图1传到同一登记器 |
| `experiments/clock_manual_20260919/visual_region_locator.py:46-90` | `plan` | 核对后未修改：读取同帧缓存进入local |

固定提示 `experiments/clock_manual_20260919/遍历prompt/共享/身份图准入.prompt:7` 同步说明区块留白；未新增模型字段/CLI开关。新文档 `design/REGION_BOUNDARY_SCOPE.md` 为本批新建，无历史行号。

验证：102项聚焦检查通过；6项无关旧失败在be80240复现后排除。真实0013发现与0017更新原答完整回放通过。新Luna原生完整保存帧2HTTP/0GUI：0100的Region底边2310、foreground底边2290仍进入正常local，0101复用Security/Privacy原控件；无新身份、任务未改、原答未编辑、下一步为action_selection。修订独立复审通过，具体证据与边界见月度日志。

尚未验证：新桌面模型案例、实际GUI续跑或全门。本批未修复旧遍历暂挂；Privacy身份/图标裁图截断，不能作为合格模板；Security标题轻微切边。控件裁图质量缺陷未解决，本批不是通用模板质量验收。两轮旧Settings冻结源未换版，统计与覆盖限制见SERVER_HANDOFF。
