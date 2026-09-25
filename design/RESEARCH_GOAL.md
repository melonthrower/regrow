# GUI Agent 轨迹构造全局研究目标

2026-09-18 协议修复后新增证据：同一冻结modular核心在Markor实机完成工具栏直属4/4，由原调度自行切到更多菜单Region并打开Settings；8次真实动作均原生success。Android Files导航栏直属3/3，5次动作成功；原Region引用/效果报告仍有纠错。所有GUI均经root只读安全放行，不能称无人监督或全应用完成。跨应用批次与Draw结果见`artifacts/protocol_live_20260918_01/ASTRA_REVIEW.md`。这是局部连续推进的新证据，不自动勾选M1–M6，不替代完整业务原子、指令合成及图引导采集验收。

2026-09-18 小批数据筛选：`artifacts/overhead_data_20260918_01/`复用CollectionWriter导出1条已验证导航子轨迹（2步）及1条仅操作训练样本（1步），来源均为原Clock实跑，标明3次人工安全放行。a9人工接线、a13身份争议及VLC非成功结果单列；完整业务轨迹/功能原子仍为0。原运行谱系与任务族整组留在训练侧，未建立验证集，不拆步骤随机分组。此为历史实机证据再整理，非本轮新采集或自主业务成果。

2026-09-18 V2证据边界：完整功能原子不得用单个导航入口或visible_state谓词冒充。Clock导航区账面覆盖补齐并进入Settings、VLC恢复清单通过，均不替代原子→实际生成指令→图引导采集验收。本批原生图编译候选有来源，完整业务原子、生成指令和采集未通过；旧辅助a9单独标注，不勾选自主Region收尾或下游研究目标。

2026-09-17 当前执行目标更新：取消“VLC通过后才验证Android”的前置。保留modular主链与视觉身份，以同一核心版本先顺序运行不同结构的授权测试应用，再扩展锁定清单。区分应用被实际运行、已发现Region直属范围覆盖、应用内充分探索；未运行/受限/未知保留，不把benchmark任务或启动一次当全应用完成。程序处理观察/结算、执行、导航/准备和局部暂挂；位置或前景不可信时停止相应路径并有界恢复；动作结果未知但当前位置独立核验通过时保留受影响任务缺口，继续其他独立操作。独立健康应用继续。已有Gmail语义分支示例、采集目标不变，未勾选研究成果不因本次接线自动完成。

2026-09-17 当前遍历验收：图仍为底层事实，树用于主Agent理解任务、环境和未探索兄弟；工作Region与当前前景分开。每轮覆盖声明直属一层，保留子区块待办，再实际推进另一Region；不穷举参数组合，不递归等待全子树。Allow/Criteria派生视图及Alarm适用状态的原生用例已通过，Region实机验收仍未通过，不能勾选全应用/跨应用目标。实现边界见[Region工作范围](modules/explore_kernel/region_work.md)，Gmail月报if/else示例及采集语义验收保持原要求。

最后更新：2026-09-09

本文是本项目当前研究方向、贡献边界和验收目标的唯一真值。它回答“我们要验证什么”，
不替代 `design/CURRENT_FRAMEWORK.md` 和 `design/modules/*.md` 中的当前实现合同。
未勾选内容均为目标或待验证设计，不能写成已经实现的框架能力或实验结论。

用户已批准的实验优先级见 [ICLR 2027 实验执行方案](ICLR2027_EXPERIMENT_PLAN.md)。
完整实验待办统一在 [GLOBAL_TODO.md](GLOBAL_TODO.md)：按 paper_v2 保留 Qwen3-VL 微调与 AndroidWorld/OSWorld 主实验，
以及表示、生成和实时采集对照；已有脚本或小规模接通不表示这些实验已经完成。
各阶段不设最迟日期，要求尽快连续推进；已知案例不是全部 bug，实际新阻塞按已有设计做最小修复。
少量直接相关验证通过后尽快回到实验，不扩展硬编码规则；实验未通过时仍保留未完成状态。

## 1. 北极星目标

当前执行约束（2026-09-14用户更新）：允许先选旧 VLC 图中已核对的功能，进行少量指令生成与实机采集试点；不再以完成全部双端遍历作为本次小试的前置。
历史图和轨迹保留。局部试点不代表全应用遍历完成、图质量认证或批量采集验收；遍历仍确认必要参数而不穷举组合。

2026-09-09用户进一步明确目标：先识别可交互前景，再逐层组织容器、Region/子Region、控件与功能；
通过展开有限选项、切换模式和必要滚动补齐功能、参数、互斥及条件子功能。初始分区可依据独立滚动、
固定显示和内容替换等新证据细化，保留历史证据。功能含义、参数及条件优先用简洁自然语言表达，
引用、归属和证据关联保留必要结构。采集时目标Region已在当前前景可见即可直接使用，
不存在因果关系的同屏区块不虚构跳转边，也不因缺少边而强制绕路。详细VLC例子与实现边界见REGION_TRAVERSAL_ALIGNMENT.md。
这部分是待实现/待验证目标，不代表当前扁平Region账本已支持完整的父子层级和事后细化。

本项目研究一种**能力图支撑的目标先行 GUI 轨迹构造方法**：先在实机上尽可能覆盖应用中
不同的功能页面与交互表面，为其中的功能定位 Region，记录必要的功能、参数、条件和真实
Region 跳转关系；遍历批次结束并保存图后，围绕有意义的共同用户目标重组已发现功能，
批量生成复杂指令；最后让执行 Agent 根据图到达目标 Region，并在实时界面完成各项功能、
验证整体业务目标，采集真实的复杂轨迹。

页面探索、Region 功能图、指令组合和实机采集必须服务于同一条方法链。导航通常不是
组合指令的业务目标，但进入未知页面、发现新区块和建立可执行连接是遍历阶段的主要工作，
不能因导航不直接参与业务组合就删去这部分探索。功能确认用于补齐后续组合与执行需要的
信息，不要求先穷举一个区块的参数或验证每个明确控件，才能继续发现其他页面。
优化应减少重复访问、重复清点与无效纠正，不以缩小功能覆盖、丢失必要关系或隐藏失败换取
更少调用。图是支撑发现、组合和执行的中间产物，最终目标是有真实业务结果和证据的复杂轨迹。

核心研究问题是：

> 能否将黑盒 GUI 探索得到的 Page/State、Region、Operation 和真实效果组织为可复用的
> 应用能力图，并由能力图生成比 Screen/trajectory-first 方法更自然、更可执行、更少
> 无效组合且最终结果可验证的任务与实机轨迹？

“能力先行”和“目标先行”描述不同阶段：

- 整体数据构造先探索发现功能并保存已有证据，再设计任务，因此是 capability-first；不要求每项功能先执行；
- 单次任务合成先确定有意义的最终目标，再反推必要能力，因此是 goal-first；
- 指令是目标和能力计划的自然语言表达，不是任意 Operation 列表的事后包装。

已对齐的具体设计及代码位置见 [REGION_TRAVERSAL_ALIGNMENT.md](REGION_TRAVERSAL_ALIGNMENT.md)：
遍历以不同功能与 Region 覆盖为目标，省略同类项、共享区块的重复探索和语义明确的执行；
通过控件动作导致的 Region 出现、消失及局部变化组织图，并区分外部事件与不确定因果。
探索经验应跟随 Region/操作按需提供给 Luna，影响后续探索选择，并能被新证据修正。
采集时图负责指导到达功能 Region，Agent 根据实时界面完成具体操作；未知中间 State 本身不构成失败。
上述因果报告、显式改向、发现目录和 Region 分支采集已完成基本接线与离线验证；真实 Luna 效果和多应用验收仍未完成。

## 2. 当前目标方法链

```text
真实 GUI 视觉探索
  -> Page / State 身份与真实状态连接
  -> canonical Region / Region-owned CanonicalOperation / current RegionVariant-Element binding
  -> before / action / after：区块变化、动作因果及外部事件观察
  -> 按 Region / 操作复用经验，指导后续探索并修正旧结论
  -> 保存界面发现、已观察结果及其证据状态的 Capability Graph
  -> 从可实现效果中提出有意义的最终目标
  -> 按 precondition / effect / object binding 选择必要 Capability
  -> 过滤撤销、冲突、冗余和无共同用户目的的组合
  -> 生成自然用户指令
  -> 将 Capability 映射到目标 Region / CanonicalOperation
  -> 从 Region 关系指导到达功能区块，当前截图确认入口与对象
  -> Agent 根据实时界面执行具体任务，允许未知中间 State，采集新轨迹
  -> 用 success predicate / desired outcome 验证最终结果
  -> 任务成功后独立执行 cleanup；cleanup 不进入用户指令或训练轨迹
```

已知 Region 路线保留真实 Transition/Attempt 和适用上下文，不把前后集合差或外部事件直接写成按钮因果。
采集不必复现每个历史 State；Agent 根据最新截图确认 Region、目标对象和可执行入口，必要时处理图中未枚举的步骤。
不确定的新关系不冒充已验证边。最短关系路径不等于最少总 GUI 动作，也不能替代任务前置和结果判断。

## 3. 当前已验证基础

- [x] 模块化探索账本以 `canonical Region -> Region-owned CanonicalOperation` 表达稳定功能；
  Page State 只组织可见 Region，RegionVariant/Element/local Operation 保存当前可执行绑定与证据。
  已知State增量清点中的Region/Element使用现有ref；新State的旧Region ref只作审核提示，旧Element ref不跨
  Variant借用。空Element ref只作为候选，经当前Variant内批量审核后
  才复用旧el或分配新el。当前有本地合同、Clock故障saved-frame和同一原图89步ref门禁fresh-live证据；
  正式bundle已编译且同Variant精确重复组为0，但空ref候选Reviewer的live触发与complete验收仍待完成。
- [x] Region 身份、Operation 身份和 Operation 结果复用分别判断；Region 相同不自动复用
  其中全部操作或结果。新 Region 批次中的 `shared_operations` 只作为候选；存在候选时由一次独立批量
  Operation Reviewer使用同组完整截图复核，整批无候选和返回已知 Page/State 都不增加调用。当前只有
  本地合同、saved-frame API和一次Clock定点fresh-live接线验证；错误同形`+`的live拒绝正例与Luna-only
  完整验收仍待完成。
- [x] 桌面与移动 Clock 已有连续真实遍历闭合证据，可作为单应用双端 pilot；它不构成
  多应用探索成本或 Region 准确率证明。
- [x] ActionAttempt 保存真实动作及 before/after/observed outcome，显式 effect observation
  可离线归纳独立 Capability Graph。
- [x] Transition 可保存带 source RegionVariant/CanonicalOperation 条件的 Region reveal/hide，
  并派生 Page Region分组和上下文相关 Region路线；当前只有离线与保存账本验证，尚无新鲜 live acceptance。
- [x] 当前 task bridge 能从一个已有 Capability 建立不可篡改骨架，并让模型只负责将该
  骨架润色成自然指令。
- [x] 当前实现会拒绝把任意相邻按钮级 Capability 自动拼成多能力用户任务；这避免把
  结构可连通但语义不成立的组合伪装成自然目标。

## 4. 当前研究目标与状态

### 4.1 Region-centered 低冗余探索

2026-09-10 当前实验：用户明确允许修改通用分区规则、记录方式、反馈和识别流程，以多应用保存帧检验Region、State与控件的跨屏身份。检查包括稳定共享区、不同功能内容不误并、父子容器、静态内容不误建动作及当前物理owner；分别保留首答、纠正与最终映射，并报告漏项/误合并/过分拆分。用户已允许所选及新增截图发送至当前Luna服务。当前完成5应用17张保存图及定点身份重放，12项核心检查通过；Luna-only未达稳定，该轮曾改Sol medium，2026-09-11已按用户成本约束恢复Luna medium。仅支持当前有限样本中的主要识别路径，不勾选多应用独立真值/总体错误率验收；固定规则后仍需未用于纠错的页面对照，保存帧不替代实机动作验收。

- [ ] 在多应用动态 State 序列上建立 Region / Operation 身份人工真值。
- [ ] 证明 Page + Region + Operation 复用在相同独立功能覆盖下减少真实动作、模型调用、
  token、时间或费用。
- [ ] 报告 Region false merge/split、Operation 错误复用、遗漏功能和重复探索。
  2026-08-30 已完成一轮 Codex/Sol 监督的多应用缺陷采样：在同一专属 Android seeded AVD 上顺序尝试
  Clock、Settings、Files、Contacts、Camera、Calendar、Chrome、Dialer、Messages、Photos 共10个应用，
  得到166个真实 Attempt和各自独立账本；全部为 partial/blocked/contaminated，不能勾选本项或当作人工真值。
  主要复现了浮层背景污染、滚动/wait/input循环、State断链、owner漂移、外部组件包恢复丢失、跨应用状态泄漏和
  0..1坐标尺度误用；后续因Luna API HTTP 402停止，Maps及更多应用未运行。
  2026-09-01 桌面Clock在同一原图上resume后运行至`terminal_gaps/partial`：63 Attempt、4 Page、23 State、
  28 Region、92 CanonicalOperation、39 Transition。独立批量Operation Reviewer已获得多Region单调用和
  已知页面0调用live证据，但已知State增量新Operation未复核导致bundle同名歧义，故本项仍未完成。
- [ ] 与 occurrence-level 全量探索、Screen-only 去重以及 SEE 式候选排序/Screen 图比较。
- [ ] 验证经验闭环：利用已有 Region memory、动作证据和反馈，使 Luna 跳过已覆盖内容、探索差异、
  修正失败策略和上下文误用；有 memory 字段或日志不等于已实现有效学习，不增加无必要的逐步反思调用。

### 4.2 目标先行任务合成

- [ ] 从界面已发现的功能、参数与预期效果提出最终目标，不要求先执行或重复验证。
  已观察的效果作为经验，未执行的预期不得标为已验证；采集成功由本次实际结果判断。
  当前 function_inventory 已直接投影 modular 的零动作发现，--region-ledger 生成 Region 目标与分支；
  不依赖旧能力图效果晋升，但业务目标质量与完整实机采集仍待验证。
- [ ] 每个目标具有明确的 success predicate，并描述一个有持续用户价值的最终状态。
- [ ] 每个被选 Capability 都对最终目标有必要的因果贡献。
- [ ] 拒绝立即撤销整个目标的组合，例如“创建后立刻删除”“开启后立刻关闭”。
- [ ] 将 cleanup / 环境复原标为独立执行阶段，不进入用户指令和训练轨迹。
- [ ] 使用前置条件、效果兼容性、参数与对象绑定约束多 Capability 组合。
- [ ] 支持同一对象上的多能力单目标组合；例如创建工作日闹钟并设置时间、标签和铃声。
- [ ] 在上述合同稳定后，再评估并列目标、条件目标和跨应用目标，不提前声明支持。

### 4.3 实机轨迹采集与验证

- [ ] 将选定 Capability 绑定到目标 Region / CanonicalOperation，再绑定当前可执行 RegionVariant / local Operation。
- [ ] 使用带上下文和证据的 Region 关系指导到达功能区块；图缺少具体步骤时允许 Agent 根据实时界面继续，
  不因未知中间 State 停止，也不把未经确认的动作结果写成已验证图关系。
- [ ] 在真实 GUI 环境重新 grounding 和执行，不直接把历史坐标或旧截图路径当作新轨迹。
- [ ] 保存任务动作、路线动作、实际落地 State、对象绑定和最终业务效果。
- [ ] 只有最终 success predicate / desired outcome 得到可见证据时才接受轨迹。
- [ ] cleanup 单独执行、单独审计；cleanup 失败不改写已采集任务的业务结果。
- [ ] 用 typed per-task scenario delta、精确 SeedPlan 和显式单标量 `output_slot/from_slot` 完成首个跨应用 live pilot：
  从 clean base 的按需 overlay 中读取一条合成就餐信息，经已验证依赖传给回复与文档写入能力，并分别用
  SMS Provider 和文件内容确定性验收。当前最小代码与离线测试已完成，但尚无真实 GUI episode，
  不提前声明通用 dataflow 或自动跨应用任务合成。

### 4.4 多目标重组

- [ ] 第一阶段只允许多个 Capability 共同服务于一个统一最终目标。
- [ ] 并列目标必须具有同一用户场景，不能只是两个可达 Operation 的随机拼接。
- [ ] 条件目标必须保存条件观察、实际分支、未选分支和结果证据。
- [ ] 多目标重组必须检查目标间冲突、共享对象、执行顺序和最终可验证性。

### 4.5 Luna 独立控制 harness Prompt 研究

该子目标暂时独立于主框架实现：通过可审计的 teacher-student live pilot，查找低级
API 模型需要什么稳定 Prompt、动态历史、动作空间和确定性门禁，才能独立生成当前
Page / Region / Element / Operation 图。Codex 只充当开发阶段的教师和错误标注器；
最终验收必须由无 Codex 在线纠错的 Luna-only harness 完成。当前不因该子目标修改
`gui_rewalk/`、目标先行任务生成、Capability 组合或 out-of-band cleanup 合同。
完整经验、建议协议、失败转化和下一轮交接统一维护在
`design/LUNA_REGION_HARNESS_DESIGN.md`；该文档是独立研究设计，不代表未勾选项目已经实现。

- [x] 完成桌面 Clock、VS Code 和移动 Google Clock 的 Luna API teacher-student
  bounded pilot；请求记录均确认 effective model 为 `gpt-5.6-luna` 且
  `store=false`，三个 pilot 均产生 `modular_exploration.v4`、`tasks=0` 和 schema-3
  编译产物。这只验证了低级模型可在显式图上下文中探索并生图，不是任一
  应用的完整遍历、Capability 验收或目标任务采集证据。
- [x] 在同屏坐标探针中，Luna 对 `0..1000` 与 raw-pixel 两种明确坐标合同均为
  14/14 目标框命中；移动 Clock 进一步完成 12/12 次独立 fresh-frame
  raw-pixel grounding，0 次纠正。该结果只支持“高层语义选路与坐标定位
  可分离”，不构成跨应用 grounding 准确率结论。
- [x] 移动 Clock 在精确包 `com.google.android.deskclock` 上完成 20 个真实动作、
  6 Page、13 State、72 local Operation 和 18 Transition 的单应用 pilot，并精确清理
  所属模拟器资源。运行仍有 49 个 pending/deferred Operation gap，且只完成一次
  Settings Region 滑动，因此是 bounded pilot，不是完整遍历证书；模拟器资源
  清理也不是目标任务的 out-of-band business cleanup 验收。
- [x] 完成独立 `region_reachability.pilot.v0` 的桌面 Clock / GNOME Settings
  teacher-student live pilot：底层只保存 `RegionState -- Operation/Event --> RegionState`，
  Page 仅作语义宏。规范化 Clock 图包含 12 Region、58 RegionState、80 ActionAttempt、
  109 reachability edges，状态为 `complete_with_policy_exclusions`；Settings 图包含
  59 Region、206 RegionState、145 ActionAttempt、286 reachability edges，但 Sound 分类
  两次正确落点后应用消失，因此验收为 `partial_failed_gap`。该结果只证明 Region 可达图
  能从真实动作构建并形成多跳路径；运行中使用了 Codex 教师反馈，未验证 Luna-only，
  也未验证编译后路线的多步快速重放。
- [x] 主框架 owner-centered 合同完成一次 Codex-supervised fresh Clock live acceptance：
  js1 `runs/luna_clock_task_reconcile_d69a7d99_20260828_214908` 使用 effective
  `gpt-5.6-luna`，24 动作、48 个主 Agent turn、15 次 Page Resolver、9 次 Region Reviewer，
  得到 4 Page、13 State、21 Region、127 Element、54 CanonicalOperation/108 local binding、
  16 Transition，`complete/gaps=[]/bundle=compiled`；11 个 Capability，21/21 Region 有 memory。
  该结果证明主框架集成可闭合，但开发期间使用过 Codex 监督，不能替代最终 Luna-only acceptance。
- [x] js1 `guitraverse_mobile_seed_v1` 上完成一次 20-action Codex-supervised post-fix Clock smoke：
  system target 的全屏教学提示被 Luna 正确登记为目标 Page/Region，`Got it` 形成真实 Attempt/Transition；
  零位移 scroll 三次上限和同图 click `no_effect` 门禁获得 live 正例。run 以 action_limit/partial 结束，
  仍有 13 个 gap，且发现非 ASCII 部分输入误结算；因此只验收对应门禁，不替代完整遍历、图质量或
  无监督 Luna-only acceptance。
- [x] 修正内联展开的 Region 边界：普通被动展开仍是来源 Variant；显露一组共同出现/消失、服务于单一对象且
  可独立完成任务的编辑上下文时建立独立结果 Region，来源 Element/Operation 保持原 owner。Reviewer 的候选输入
  必带进入当前 State 的真实来源 Region/Operation/visible result，不受普通候选 State 上限约束。聚焦测试为
  `131 passed`；移动 Clock `a137` 保存截图 Luna 探针返回
  `separate / trigger_or_result / known_operation_reveals_current`，输入 7,611 tokens。该证据是 saved-frame
  Prompt/接线验证，不是修改后的 live 遍历或多应用验收。
- [x] 形成一份最小稳定 Prompt 合同：只定义 Page/State、共享 Region/当前页面版本、
  Element/Region Operation、`known/new/uncertain`、安全边界、前一动作结算、单步语义
  动作和 bounded finish；不让 Luna 分配 ID 或报告 Task 终态。2026-08-28 主框架严格
  Schema 已改为 owner action + completed owner + Region function info，坐标仍由同一 Luna
  在最新截图直接输出 `point_1000`；本项已有本地合同/API 边界测试和 Codex-supervised live
  acceptance，不代表无监督 Luna-only acceptance。
- [x] 模型协议不依赖独立 Task/TODO：由 Operation 终态、当前 Region 清点
  覆盖和可滚动 Region 的顶部/新内容/到底或同质停止证据驱动下一步与结束；
  内部 Task 只保留为 framework-owned scheduler binding，模型不再输出
  `task_result/current_task_result/purpose=route`。Codex-supervised fresh Clock 已闭合；无监督验收仍待完成。
- [ ] 将教师纠错统一归类为 `missing_context / semantic / schema-owner / grounding /
  action-space / safety-stop`，为每类错误保存 Luna 原始回答、前后截图、最小纠正和
  建议归属；只把可重复的规律沉淀为 Prompt、上下文检索、确定性门禁或定位器规则。
- [x] 在主框架使用 framework-owned CanonicalOperation ID、精确 owner
  binding 和同质 Operation 代表组；禁止依靠自由文本 target 合并。当前 Clock / Settings
  分别产生 221 / 735 条本地 Operation，Settings 还需两条教师 owner correction 才能闭合，
  因此现有文本身份合同未验收。主框架账本已经提供稳定的 `r/rv/co/o` 编号与本地 binding；
  2026-09-01 主 Agent 输入已进一步收束为 Region-owned CanonicalOperation：当前页面、任务卡、路线和
  动作回执只显示稳定 `co`，不同 State 的本地 `o` 只供 runtime 在 before Variant 按当前
  `element_ref/region_ref` 唯一执行和保存证据；新对象仍只由 `page_report` 提交无编号
  候选并由框架分配 ID。已知 State 漏掉的当前 Element 可在增量清单中引用 Region 已有 `co` 建立本地
  binding，runtime 校验 Region/scope/action/direction；真正新功能仍提交空 operation ref。
  同一 `owner + action + direction` 多 Operation 会被拒绝，参数值域写
  Region memory。该实现有本地测试，仍需固定 Prompt 的 Luna-only live 验收。
- [ ] 验证 Operation 参数确认合同：新 v5/v6 run 的每个 Operation 必须显式为
  `none/observed/unknown`；直接可见的无参数、参数形式、当前值或代表值不执行，安全且连参数形式与
  代表值都隐藏的选择器只执行一个入口，
  普通参数值不逐项建立 Operation。`record + unknown` 必须保留参数 gap 且不能扩大动作授权。
  当前实现、离线聚焦测试和一次移动 Clock supervised live 参数审计已完成；live ledger 的 268 个
  CanonicalOperation 中 182 none、51 observed、35 unknown，且发现 2 组 none/observed 冲突。
  run 因环境消失后 resume 的 external-surface 无动作循环被监督停止，仍为 partial，因此本项目不勾选，
  最终 Luna-only acceptance 仍单独保留。
- [x] 用 `Semantic Exploration Focus` 作为 scheduler/context projection：当前 Page、Region、
  目标操作和同 Page Region memory 形成自然语言嵌套焦点；全局图、ID、Operation 和证据仍只有
  一份，不新增持久 Task/子图。Region memory 同时投影到正式 Region bundle，供后续指令生成
  检索，但不替代 Capability 前置条件、effect、对象 binding 或成功谓词。2026-09-04 增加两个代表
  共同回答一个交互问题的窄扩展：任务提出时列出同 Region全部成员和两个代表；成员可保留各自临时 canonical
  身份，只在两次真实动作和最终同类结论齐全时把其他成员记为代表覆盖，且不新增任务类型或图。离线合同、
  Codex-Luna和固定 Prompt API保存帧均已验证闹钟星期项能登记为1个explore代表+6个record成员；24/8动作
  live试跑因调度顺序未执行到 representative_probe，故仍无该机制的live验收。
- [ ] 实现 Region 路线编译快路径：一次规划已验证 RegionEvent 链，每步只从 fresh screenshot
  grounding 下一 Operation；仅在目标缺失、候选边、外部/失败落点和最终结果时调用高层 Luna。
  当前 pilot 的每个动作仍由高层 Luna 逐轮选择，不能作为该快路径的运行证据。主框架已有一条
  更保守的同图点击锚点路线重放：只在完整截图字节相同、首跳已验证且局部锚点唯一时省略当轮
  主 Agent；它可以复用，但尚未验证“编译整条 RegionEvent 路线后逐步 fresh grounding”。
- [ ] 在相同功能覆盖下缩减 Luna 动态上下文并实测成本：当前三个 pilot 的高层
  prompt 峰值分别为 14,117、13,236 和 10,436 input tokens；在未比较覆盖、错误
  率和 API `cached_tokens` 前，不得宣称分阶段 Region 上下文更低成本或更高效。新 Region
  pilot 日志中，高层调用通常只命中稳定系统段（Clock 为 1,291 tokens；Settings 除早期
  Prompt 外也为 1,291），全部 231 次 fresh-grounder 调用均为 0 cache hit；一次完整输入
  与截图相同的重试命中 14,675。随后纯文本探针表明：同一 user 消息内即使拆成多个 content
  block，动态后缀变化仍为 0/5,445 命中；把稳定前缀单独放入前置 developer message 后，
  动态 user 后缀变化可命中 5,442/5,452。该结果只证明当前智增增/Luna transport 的实测
  分段方式。2026-09-04 固定主 Prompt 在 cl100k 估算下从7,017降至约4,275 tokens，Schema约1,336；
  普通 survey动态任务说明从506字降为239字。最终三张固定 Prompt API保存帧输入约6.9k tokens；真实
  24动作 Clock run 的主 Agent输入仍平均11.6k、峰值13.1k，说明当前页面清单和已知图等动态内容已成为
  主要成本，不能仅凭静态压缩宣称端到端成本达标。下一版应把固定路线、稳定 ref 与合同放入独立稳定消息，把最新截图、pending
  结算和当前步骤留在末尾动态消息，并在真实覆盖不变时重新核算 token/费用。新的 supervised
  complete Clock run 中，48 次主 Agent 调用全部有 cache hit，cached tokens 合计 195,024，单次
  input 峰值 10,723；Region Reviewer 9/9 有 cache hit，Page Resolver 0/15。该单 run 尚未构成
  相同覆盖 A/B，故本项仍未完成。
- [ ] 用固定合同先在 Clock、再在 Settings 和 VS Code 运行无 Codex 监督的 Luna-only 验收：
  检查页面/区块身份、重复动作、长页面停止、外部页面污染、grounding 错误恢复、
  未结算 gap 和输入 token；不得在运行中修改 Prompt/harness 或注入教师反馈。新 Region pilot
  的 Clock / Settings 高层 input token 峰值分别为 12,828 / 17,892，Settings 仍为 partial；
  通过干净重跑前，teacher-student pilot 只是 Prompt 设计证据。

本地证据根分别为 `artifacts/oracle_current_graph_clock_20260826/`、
`artifacts/oracle_current_graph_vscode_20260826/`、
`artifacts/oracle_current_graph_mobile_clock_20260826/` 和
`artifacts/luna_coordinate_probe_20260826/`，以及
`artifacts/region_reachability_pilot_20260827/`；主框架 supervised complete 证据位于 js1
`/data/shenghonghui/projects/gui-rewalk/runs/luna_clock_task_reconcile_d69a7d99_20260828_214908/`。
本地 `artifacts/` 被 Git 忽略，因此本地路径不是跨 clone 可用的持久实验数据集。

## 5. 任务质量门

一个任务骨架只有同时满足下列条件才可交给模型润色：

1. **有意义**：目标对应用户可理解且有持续价值的最终结果；
2. **有依据**：功能及参数来自界面发现或图中记录；无需历史成功次数，不编造未观察的功能；
3. **有贡献**：每个 Operation 都是达成最终目标所必需，导航和 cleanup 不写入指令；
4. **无冲突**：前置条件、效果、参数和对象绑定相容，最终目标未被后续操作撤销；
5. **可尝试执行**：有可定位的功能入口；已有路线指导执行，未知步骤由实时观察处理，不伪造已验证边；
6. **可验证**：最终结果具有可观察 success predicate / desired outcome；
7. **安全**：只使用允许采集和重新执行的功能，敏感或不可逆目标不进入自动合成。

任务设计可从已发现功能提出目标值和必要功能组合；一旦确定具体指令，后续润色和执行不得悄悄改换目标、对象或分支含义。
这些约束用于保持任务一致，不要求新增固定模板、禁止合理的新参数值或把语义判断交给确定性词表。

## 6. 相关工作边界

- **OS-Genesis**：trajectory-first / reverse task synthesis；先交互，再从轨迹反向生成任务。
- **SEE**：screen-first；先从 Screen-Element 图采样候选 Screen，生成有序 subgoals 和高层
  指令，再用 BFS 连接 Screen，并在图路径上生成低层描述。
- **BAGEL / instruction-first 方法**：先从初始 observation 或 action space 提出指令，
  但目标不一定由已验证应用能力和效果约束。
- **本项目目标**：capability-graph-grounded goal-first；先从黑盒探索发现的功能及已有经验中
  选择有意义的最终目标，再进行约束组合、实机采集和结果验证。

不得仅以“有图”“先有指令”“存在拓扑关系”或“使用最短路径”声明创新。目标贡献是上述
表示、约束合成与实机验证闭环；是否具有充分新颖性必须通过完整相关工作审计和实验决定。

## 7. 关键实验与验收

本节按 paper_v2 和用户确认的补充统一四条主实验线，完整勾选项见 GLOBAL_TODO：

1. **E1 下游数据价值：**Qwen3-VL Base、等量 −Region/State 数据微调、Full/Region 数据微调，
   在 AndroidWorld 和 OSWorld 以相同协议评测；控制训练与测试信息差异，不能用运行时图指导代替训练消融。
2. **E2 表示与探索：**扁平 State-transition/State-element 与 Region 表示的同预算对照，核对功能覆盖、重复探索、身份错误和成本。
3. **E3 任务生成：**Screen/trajectory-first、单项功能有依据、完整目标先行组合三组；
   保留候选、拒绝和实机结果，比较合理性、冲突、参数/对象绑定及不同复杂度。旧四组口径不再同时强制执行。
4. **E4 实时采集：**相同复杂任务上的无图、State 图、Region 图及相关经验三组；报告业务成功率、失败成本及图复用的摊销成本。

至少报告：

- 指令自然性与用户目标合理性；
- 无效、冲突、撤销和无共同目的组合比例；
- Capability / 参数 / 对象绑定准确率；
- 实机可执行率、最终业务效果成功率和 cleanup 成功率；
- 新组合比例、功能覆盖、真实动作、模型调用、token、时间和费用；
- Region identity、负证据、约束组合和最终验证的消融结果。

### 7.1 当前必做：有限范围的遍历与图指导采集

2026-09-08 用户已批准推进此实验，具体范围和优先级见实验执行方案 M1–M6。
尽早接通真实小图到轨迹，并同步核对 SFT、训练和 benchmark 入口；不把完整连续遍历验收作为检查下游的前置条件。
至少两个应用的 State/Region 小规模对照是诊断起点，不替代 E1–E4 和正式 benchmark。
每应用预先固定 10–20 项安全、可观察核心功能和至少 5 个采集任务，保留全部成功、失败及超时。
图的节点数不是覆盖真值；有限功能覆盖不等于任意应用完整遍历。开发监督数据与正式自主评价分开。

记录功能覆盖、Region/路线正确性、重复探索、各角色调用/token/时间、采集结果和失败原因。
不得为了正结果修改覆盖口径、任务集合或预算；无收益或退化照实记录。
负结果可以完成对照实验，但不能替代连续遍历和端到端功能本身的成功验收。

## 8. 当前最近任务

- [ ] M1：纠正后能够继续，不只证明三轮早停；处理运行中发现的实际阻塞。
- [ ] M2：独立新图连续遍历，并人工核对功能 Region 和真实边。
- [ ] M3：首批图生成指令与实机采集，包含条件分支证据。
- [ ] M4：完成 E1–E4，包含 Qwen3-VL 微调、AndroidWorld/OSWorld 和表示/生成/采集对照。
- [ ] M5：结果、图表、失败分析与论文主张逐项核对。
- [ ] M6：最终材料与实验索引交接；外部提交需用户授权。

以上按依赖顺序尽快推进，不等待日历日期；验收细则见执行方案。其他研究目标保留在第 4、7 节，不以其尚未实现为由
继续扩大本轮工程范围，也不能把最小流水线验收等同于全部研究目标完成。

## 9. 维护规则

- 本文只保留当前研究目标、仍有效的设计和证据边界。
- 只有实现与要求的验证均完成后，才把 `[ ]` 改为 `[x]`；设计完成、代码存在或单个样例
  成功均不足以勾选需要多应用或端到端证据的目标。
- 目标被否决、替代或证伪后，直接从本文删除；不要保留“废弃”“旧方案”章节。
- 历史通过 Git 和 `design/changelog/` 追溯，不把历史讨论重新复制到本文。
- 修改研究问题、贡献主张、任务合成链、Capability schema、实验验收或相关工作边界时，
  必须在同一任务中同步更新本文。
- `design/CURRENT_FRAMEWORK.md` 与模块文档始终是当前可执行框架真值；本文中的未勾选目标
  不能覆盖它们。

2026-09-11成本约束：优先验证Luna与框架的职责缩减，在固定请求预算内报告错误与未确认项，不自动升级Sol。独立保存帧观察原型只覆盖视觉清单和候选合并，尚未接能力、State、动作与正式身份审核；不能与完整遍历按不同工作量宣称成本优势。详见modules/explore_kernel/luna_observation_probe.md。

2026-09-11最新交付优先级：用户同意先实现受限可用的Luna正式探索路径，允许分区质量待复核且不阻塞已登记控件的安全探索；保留身份、当前owner和结果证据边界。--defer-partition-review是显式试运行选项，质量缺口不算完成。先以有限实机菜单导航/展开/返回验收可执行性，不因此勾选多应用区块准确率、成本优越性或全应用完成。指令生成/采集/训练仍未恢复。

2026-09-11用户授权独立重设计试验：新增证据优先内核，以VLC七步例子检验自然语言功能/参数/条件记录。观察和实际动作记录为不可改来源，Region/跨帧关系为可修正候选；未改变功能图支撑任务组合的研究目标。当前已获得值域、样式、滚动和分类切换的有限实机证据，但漏项、前后图误判及人工干预仍存在，尚未验证稳定遍历；完整层级、规范共享身份及下游合成仍未验。用户明确继续独立开发新框架，暂不迁移或替换旧框架。原型记录不能当作完整Region图或论文实验完成。

2026-09-11区块全景试验：用户授权复用早期地图定位式滚动，在新内核实现可选区块建图、一次VLM控件识别、当前视口定位和无模型查找。VLC仅有固定人工ROI下的Media Library定位/点击投递正例，Playlist外观改变时拒绝；不据此勾选全应用覆盖、完整规范图、自动分区或自主语义执行验收。旧框架仍不迁移/替换。

2026-09-11跨桌面/移动区块图像匹配离线检查：19张已有真实图、36对人工标注，严格整图候选17/23正例接受、0/13反例；旧区域裁剪匹配出现同应用不同功能空态误接受。仅支持视觉候选定位，不证明规范身份、当前可操作或整体识别准确率；来源/跳转证据单独保存，不新增GUI边，不勾选全应用或论文验收。

2026-09-11用户明确登记/重识别分工：首次由Luna登记有含义的控件单元（操作框＋最小可读语义上下文）及Region，框架保存身份/图片/关系，视觉负责回访，失败/歧义回退Luna；不采用UIED首次分组。已实现新内核显式已观察click/back导航执行与有预算的定位/落点回退，两次VLC实机完成；未知路径及任意自然语言目标全图规划仍未实现。有限80/80混合定位或14/14上下文样例不满足总体近100%可靠性验收，不勾选全应用/论文指标。

2026-09-11用户进一步明确近期交付应为实机填充各应用遍历图，而非继续无期限优化识别或只整理旧记录。允许以Codex Luna子代理作为采集者，框架保留真实截图/动作/回执、语义目录和未探索待办；重识别优化作为后续加速，不阻塞采集。当前仅有VLC六分类8点击试跑及一张Interface的32可见控件清点，不勾选完整应用图、跨应用准确率或无人值守验收；完整性须按约定范围与未探索入口核对。

## 2026-09-11：可纠正观察 harness 的论文表述边界

用户批准尝试让 Luna API 具备子代理式局部观察、增量登记和反馈工作流。论文可以将系统称为 GUI capability-graph construction harness，但“提供工具调用”本身不是已证明的新颖性或贡献。当前研究主线仍是能力图支撑的目标先行轨迹构造；harness 是支撑可靠功能发现及证据组织的系统方法候选。

已实现仅限独立冻结截图登记回合：模型自主裁图/按 key 更新/提交，框架坐标映射、结构检查、调用预算与原始证据保留。两应用5目标开发样例定位从4/5到5/5，有额外token开销；未证明完整区块划分、状态语义、跨帧身份、完整遍历或整体轨迹质量。它不是“API 与 Codex 相同/更准确”的对照，也未证明近100%可靠性。

- [ ] 在未用于开发的多应用样例做同模型、同预算对照，分别统计控件定位、登记召回、误接纳及区块语义质量。
- [ ] 消融自主裁图、增量保留与反馈检查，测定质量/调用成本贡献；避免将增加预算的收益全部归因 harness。
- [ ] 接入实机观察/执行/后验结果后，衡量有效功能/条件图覆盖、图引导任务执行成功率及成本。

本轮试验只完成保存帧可行性验证，不勾选以上验收项。证据见 `artifacts/traversal_goal_20260909/api_harness_20260911/REPORT.md`；实现合同见 `design/modules/evidence_explore.md`。

2026-09-11请求缩减/子代理对照补充：同三张开发图12目标，批量API与新Codex Luna均定位11/12，误认同一Writer无字图标；减少Writer请求4→2同时失去此前正确定位。扩大邻域、首次全图+网格多图对照仍失败。该负例表明不能将更多工具、更清晰图或子代理包装本身写作可靠性提升；须比较质量保持的成本收益。41离线检查、9保存帧API请求及两新子代理探针，不满足上述留出/同成本/实机图验收条件，研究目标不勾选完成。

2026-09-12有界联合实机证据：VLC首次登记→已知路径视觉回访→Cancel视觉失败后Luna定位→真实退出已执行，总12请求/12点击，最终所有pending为空。导航区复现与内容区替换有证据，底栏漏检、动作目标粒度及回执/登记耦合仍有缺口；Region仅伴随候选审核，没有自动规范身份归并。监督试验和单应用短路径不满足完整遍历、多应用可靠性或论文验收，以上目标保持未完成。原始记录见combined_region_traversal_20260911/REPORT.md。

2026-09-12：有界联合试验后的正式接线已加入独立新框架（显式已知路线后接探索、共享预算/账本、Region候选记录、无效登记中的合法回执隔离），52项离线及CLI仿真验证通过。只执行调用方选定的成功导航路径，不自动规划所有应用的返航路线，不以区域候选自动合并身份。新版首次实机启动被审批拒绝，用户随后授权后完成正式CLI菜单短段2请求/2动作，最终无pending。它验证接线，不替代多应用/完整Region质量验收，不勾选全应用/多应用/论文目标。

2026-09-12用户进一步要求减少root主动干涉。后续自主遍历评估只给初始目标/范围/预算，正常运行不逐动作放行、不人工选恢复路线、不追加补清单或修答案；观察记录，越界或触发停止条件才介入。失败必须保留为自主失败，必要救援单列，不能混入自主成功率。刚完成的settings_traversal_20260912虽取得六类首轮资料，但有root续接、补登记、格式修复和恢复核验，明确是human-assisted，不作为API-alone自主成功证据。该偏好不追溯改变历史实验的角色归属。


### 2026-09-19 Region逐步试验的当前约束

用户确认以Clock人工逐步路径检验冗余设计：不独立识别Page，保留观察证据，以Region/控件及真实动作关系组织候选图；首次观察→选择→核对投递→前后结果/增量为实验基线。先冻结现有框架并保持阶段/提示词与手动过程一致，不把旧审核链重新默认为必经步骤。当前仅1实际动作、3模型调用；源码副本及顺序驱动器离线重放完成，实时适配器统一接线未完成，不替代正式框架合同或全图/采集验收。见experiments/clock_manual_20260919/FLOW_BASELINE.md。
