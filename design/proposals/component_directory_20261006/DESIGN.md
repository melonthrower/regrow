# 三步遍历器目录划分提案

状态：**待讨论的目录与职责设计；未迁移源码、未改变运行行为。**
依据已导出提交 `9935aa0291e7d09cda73928108c75f25b7c8e795`；具体旧文件、函数与行号见 [CHANGE_MAP](CHANGE_MAP.md)。本批只验证文档，不把此前五组件验证当作本次目录迁移验收。

## 目标与选择

让主程序的调用顺序、各功能的实现和正式登记入口容易找到，尤其明确“区块身份识别”“跨区块行为共享”“任务复用”的区别。保留发现与准备任务、提出并执行动作、观察并更新三步；五组件按需调用，不增加 Luna 角色、全局完成审核或完整清点前置门槛。

建议按功能分目录，五组件直接放进所属目录。只分 `step1/step2/step3/` 会让跨步骤使用的身份、共享与登记难以归属；另设一个只有转发类的 `components/` 也不能解决内部职责混杂。下面选择功能目录，并保留清楚的主流程。

## 建议目录

以下均为**目标位置**，不是现在已有目录。第一阶段在现有 `experiments/clock_manual_20260919/` 源码根内整理；不同时更名源码根、搬活动 checkout 或运行证据。省略的辅助文件沿所属功能迁入，已有独立实现优先原名保留；不是每个概念都再造一个类。

```text
experiments/clock_manual_20260919/
├── run_progress_session.py       # 保留外部启动入口，转到 workflow/session
├── launch_traversal.py           # 既有启动入口
├── call_model_once.py            # 既有 run-local 传输脚本来源
├── model_reply_parse.py          # 保留既有传输脚本查找的解析入口
├── workflow/                    # 决定做什么，连接组件
│   ├── session.py               # 会话循环、框架预算与停止原因
│   ├── step.py                  # 单轮编排
│   ├── scheduler.py             # 工作选择、待登记优先、继续/停止
│   └── routing.py               # 导航目标、局部检查安排、目标退出
├── observation/                 # 看当前画面
│   ├── locator.py               # Locator 定位器
│   ├── discovery.py             # 发现请求与观察校验
│   ├── visual_region_locator.py # 当前帧的局部定位
│   └── foreground_scope.py      # 前景、遮挡、可交互范围
├── identity/                    # 判断是否已有区块/控件身份
│   ├── region_identity.py       # 复用身份的协议与校验
│   ├── region_records.py        # 已确认身份的合并与引用修订
│   ├── control_records.py       # 控件身份及引用修订
│   ├── records.py               # 区块/控件记录物化，供登记调用
│   ├── history_matching.py      # 历史视觉候选
│   └── identity_templates.py    # 身份图与模板资格
├── sharing/                     # 不同区块间的行为关系
│   ├── relations.py             # 确认、刷新、分离共享关系
│   ├── behavior_split.py        # 实测行为不同的来源区块分离
│   └── review.py                # 关系冲突、复核请求与关系修订
├── tasks/                       # 任务的提出、复用与进度
│   ├── proposer.py              # TaskProposer 任务提出器
│   ├── planning.py              # 自己的上下文、提示、schema、规划校验
│   ├── settlement.py            # 执行后的任务进度与结果
│   ├── shared_reuse.py          # 共享任务投影、结果引用、解除后的任务复核
│   └── task_prerequisites.py    # 必要准备和条件
├── actions/                     # 动作提案与真实投递
│   ├── proposer.py              # ActionProposer 动作提出器
│   ├── executor.py              # ActionExecutor 执行器
│   ├── action_binding.py        # 当前证据下绑定目标
│   └── action_commands.py       # 平台动作转换与发送
├── updates/                     # 看执行效果，形成待登记更新
│   ├── updater.py              # ResultUpdater 结果更新器
│   ├── request.py              # 前后图、回执、历史组成更新请求
│   └── update_visibility.py    # 结果中的可见性约束
├── context/                     # 三步共用的只读上下文
│   ├── request_context.py      # 发送前公共上下文组装，保持原顺序
│   ├── map_prompt.py           # 地图投影
│   └── history_disclosure.py   # 按任务披露历史；相关辅助文件同归此处
├── registration/                # 唯一正式登记路径
│   ├── discovery.py            # 发现记录登记
│   ├── tasks.py                # 任务规划登记与共享复核的任务更新编排
│   ├── updates.py              # 动作结果登记与一致性编排
│   ├── images.py               # 身份图/证据图保存
│   └── snapshots.py            # 加载、重定位引用、原子发布
├── recovery/                    # 各阶段校验失败、纠错、补登记
│   ├── runner.py               # 复用现有 Runner
│   ├── repair_stages.py        # 阶段路由
│   └── suspended_updates.py    # 原动作待补登记与恢复
├── runtime/                     # 框架运行能力
│   ├── model_transport.py      # 请求/原答保存、调用与计数
│   ├── run_source.py           # 源码根选择、哈希、冻结文件清单
│   ├── progress.py             # 运行进度
│   └── desktop_transport.py    # 平台适配；相关捕图/生命周期同归此处
├── 遍历prompt/                  # 保留唯一提示和 schema 资源目录
└── …                            # 既有浏览器、调试、图投影等外围入口先保留
```

`tests/` 继续使用仓库现有测试目录。这个树聚焦遍历核心，不承诺本批迁移所有外围工具；外围导入、冻结和启动连接仍必须随核心迁移更新。`runtime` 不成为新的混合业务目录；平台动作语义属于 `actions`，公共请求内容属于 `context`。

## 三个容易混淆的职责

| 职责 | 输入 → 输出 | 不越过的边界 |
|---|---|---|
| `identity` 身份复用 | 当前观察、旧身份与候选 → 复用/新增/显式修订 | 视觉相似只是候选；不自动证明身份或行为相同 |
| `sharing` 行为共享 | 不同区块的本地控件、实际行为证据 → 确认或待复核的关系 | 不合并本地身份，不复制本地状态、坐标或执行记录 |
| `tasks/shared_reuse` 任务复用 | 已确认关系、各地任务与实际结果 → 本地任务投影、结果来源引用 | 共享结果不伪装成本地已执行；关系冲突时不能据此跳过探索 |

它们是三步共用的功能，不是三个新增的固定模型调用。区块划分、身份候选确认仍使用既有发现/更新/纠错请求；目录名不代表新增独立识别模型。当前 `region_identity.normalize` 也不是自动视觉合并器。

## 数据怎样连接

主程序读取已提交快照，由调度器选择工作：信息不足进入 Locator，需要任务进入 TaskProposer，有可执行任务进入 ActionProposer → ActionExecutor，有已投递待登记动作则直接续接 ResultUpdater。组件返回结果后回到主程序调度。

各组件复用原请求、schema、Runner、动作绑定和回执格式。`updates` 形成并校验观察判断，`registration` 才负责正式发布；发现和任务规划也分别走原有登记语义。沿用现有字典与路径合同，不为目录整理引入消息总线、插件注册表或新事件协议。

正式更新内部仍按原语义顺序处理：身份/来源行为分离、动作证据、任务结算、导航推进、图片保存、共享关系刷新、共享任务同步、范围覆盖核对、原子发布。目录分开后仍是一项登记操作；发现、任务规划与共享复核发布同样必须刷新关系和任务投影，不能只改动作更新一路。

解除共享还有一个事务内的先后依赖：`registration/tasks.py` 编排关系修订 → 关系刷新 → `tasks/shared_reuse` 失效投影 → 撤销/阻塞失效任务、重开清点 → 最终核对与发布。失效投影必须先于任务清理；不能全部拖到发布末尾。沿用原规则：未执行的继承任务留下审计后移除，并清掉对应活动任务；已有本地尝试或findings的保留、阻塞并重新核对，不丢本地执行证据。这段目前混在 `shared_control_review.apply`，未来任务部分归 `tasks/shared_reuse`，关系部分归 `sharing/review`。

`registration` 调用身份、共享和任务函数完成这些步骤。把 `materialize_regions` 等内存记录操作放进 `identity/records.py` 后，`sharing/behavior_split.py` 不再反向导入整个登记器。调度器调用 `workflow/routing` 决定下一项工作；登记时调用其中的状态推进逻辑不等于从登记器启动新一轮执行。

异常仍由现有 Runner、阶段纠错与待登记恢复承担。停止决定归会话与调度器；请求构造函数不因当前区块被排除而结束整个会话。框架预算留在会话/运行计数中，不放进 Luna prompt。

## 必须一起处理的连接

1. **导入和源码选择：** 当前同级文件动态加载、平面导入、测试路径、run-local `call_once.py` 依赖一起核对。普通模块改用明确包导入；从冻结/候选源加载时确保整个模块集来自所选源码根，不借用活动 checkout。只保留已知外部入口，不为每个旧文件都造兼容壳。
2. **资源定位：** 提示与 schema 仍在源码根的 `遍历prompt/`；统一从明确传入/解析出的源码根读取，不能继续用搬迁后文件的父目录当源码根。
3. **冻结与哈希：** 当前 `run_source.source_hash` 和 `debug_loop.freeze` 只覆盖顶层源码及提示。迁移时共享一个明确的源码文件清单，递归覆盖新包、必要资源与入口，拒绝把 run、缓存或依赖链接带入。原冻结 run 与其 manifest 不热替换。
4. **单一发布顺序：** 抽出共享任务同步后，所有原发布入口保持“关系刷新 → 任务同步 → 覆盖核对”的顺序及原子性；共享解除必须在任务清理前先完成失效投影。截图、调用、回执、旧快照仍按原 run 布局保存。

## 建议实施顺序与验收边界

先处理源码根、明确导入、资源与冻结合同，再按上述功能整体搬已有模块；随后逐项抽出 `discovery_step` 的调度/登记、`shared_controls` 的任务同步和 `register_update` 的图片/事务细节。不要同时改任务或共享判断策略；每个小批保持唯一可运行主链。

未来实施的聚焦验收包括：普通任务推进；排除菜单仍可导航离开；已执行待登记只补更新；同身份复用与不同身份共享的区别；冲突关系取消跳过依据；发现/任务/结果三种发布均保留正确引用与图像；冻结副本能够脱离开发目录启动且哈希覆盖子目录变化。具体案例见定位图。

行为修改时按仓库要求再用真实 run 的正常入口、实际 Luna 原答通过完整校验/纠错/登记，区分保存帧与实机。**本次仅交付设计及静态定位核对，0 Luna、0 GUI，没有验证迁移后的运行行为。**
