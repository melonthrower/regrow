# regrow 当前框架索引

2026-10-06最小遍历修复采用当前单图直接滚动、partial可信动作及程序回执合同；本轮任务/清点范围决定历史披露，独立复审遗漏已补。2026-10-05虚报Nairobi的候选图保留，不作为准确图续跑；其他地图候选仍未接受。旧冻结运行不自动切换，有限验证见本月日志。

[开发入口](../DEVELOPMENT.md) · [三步主流程](modules/stepwise/README.md) · [逐文件职责](modules/stepwise/CODE_MAP.md) · [完整细节](CURRENT_FRAMEWORK_DETAILS.md)

本文只保存全局入口、共用边界与验证导航。具体行为读对应模块；日期批次、旧实现仍适用的合同和证据限制完整保留在细节参考，不统一归为过时。研究目标以 [RESEARCH_GOAL](RESEARCH_GOAL.md) 为准，未完成目标不代表当前能力。

<a id="1-当前主链"></a>

## 1. 开发范围与主线

当前逐步开发源码在 `experiments/clock_manual_20260919/`，按发现与准备任务 → 选择并执行动作 → 观察结果并更新记录阅读；异常贯穿三步，共享模块由各步调用。实际编排入口是 `run_task_step._run_step`，三步不是每轮固定三次模型调用。
源码保持原位；本批把任务选择、任务结算、模型发送、动作关联和证据记录拆为五个职责文件，旧入口直接绑定或继承唯一实现。Python 文件及脚本、页面、prompt、测试连接见 [CODE_MAP](modules/stepwise/CODE_MAP.md)。

其他实现仍分别维护：guided/autonomous 在 `core/visual_traversal/`，modular explore 在 `core/explore/`，evidence explore 在 `core/evidence_explore/`。它们并存，不用同名概念推定合同相同；[完整主链](CURRENT_FRAMEWORK_DETAILS.md#1-当前主链)保留各自范围。

## 2. 当前入口

多应用只读进度投影：`tools/stepwise_dashboard.py <config.json>`，同页显示框架最近真实观察、累计预算及区块/控件/任务树；复用每批冻结源的原投影，不启动遍历。配置与验证见[运行模块](modules/stepwise/runtime.md#多应用只读浏览器投影)。

| 入口 | 职责与阅读位置 |
|---|---|
| `experiments/clock_manual_20260919/启动遍历.sh` → `launch_traversal.py` | 当前逐步浏览器/应用入口；[运行](modules/stepwise/runtime.md) |
| 同目录 `run_progress_session.py` → `run_task_step.py` | 原有会话驱动与单轮编排；[三步导航](modules/stepwise/README.md) |
| 同目录 `debug_loop.py` | 原有隔离候选与监督闭环；[监督合同](modules/stepwise_debug_loop.md) |
| `gui_rewalk/run_visual_traversal.py` | guided、autonomous、modular explore 与 perception-only，按对应模式合同读取 |
| `gui_rewalk/run_evidence_explore.py` / `run_region_panorama.py` | 独立证据内核与全景工具 |
| `gui_rewalk/run_capability_synth.py` / `run_capability_induction.py` | 可选离线归一/补录与真实 attempt/effect 归纳 |
| `gui_rewalk/run_capability_task_synthesis.py` | 从账本或冻结逐步图生成 Region 目标/分支，固定来源摘要 |
| `gui_rewalk/run_visual_collection.py` | Region 图指导实时采集，独立输出，逐步图自动接视觉 guard |
| `gui_rewalk/run_graph_quality.py` / `tools/check_stepwise_quality.py` | 对应图格式的只读质量检查 |
| `run_local_visual.ps1` / `ops/run_guitraverse_seeded_mobile.ps1` | 既有桌面/版本化 whole-AVD 环境入口 |
| `ops/pull_remote_run_evidence.ps1` | 白名单回收结果/日志，拒绝链接与 `repo/OSWorld` |

环境支持桌面、Android/ADB、Docker/OSWorld 与诊断用 Local HTML；fixture 不代表真实应用验收。平台、provider、seed/readback、前台归属与生命周期细节见 [环境模块](modules/env_and_config.md)及[原入口合同](CURRENT_FRAMEWORK_DETAILS.md#2-当前入口)。

## 3. 模块文档地图

| 修改范围 | 修改前读取 |
|---|---|
| 逐步框架、prompt、浏览器与会话 | [三步入口](modules/stepwise/README.md) → [完整 owner 表](modules/stepwise/CODE_MAP.md) → 相关职责页 |
| guided/autonomous、Router、grounding、scroll、resume | [视觉遍历合同](modules/visual_traversal.md)与[文件地图](modules/visual_traversal_file_map.md) |
| StateGraph/schema/attempt/completion | [状态图](modules/state_graph.md) |
| 环境/provider/模型传输/生命周期/fixture | [环境与配置](modules/env_and_config.md) |
| modular explore / evidence explore | [探索内核地图](modules/explore_kernel_design.md) / [证据内核](modules/evidence_explore.md) |
| 生成、归纳、采集、质量检查与研究设计 | [全项目模块地图](modules/README.md)；遍历/采集边界还读 [Region 对齐](REGION_TRAVERSAL_ALIGNMENT.md) |

完整旧模块地图与 Phase 1 归纳细节仍见[细节参考第 3 节](CURRENT_FRAMEWORK_DETAILS.md#3-模块文档地图)。

## 4. 跨模块不变量

- 区块可承载多个用途与独立功能。local_knowledge维护自身稳定用途、参数和条件；入口目标仅一层只读披露，不递归复制知识。有效本地探索结束后总结，子区块新细节不自动重写父区块；显式采用的支持变化仍复核。合同见[知识模块](modules/stepwise/knowledge.md)，本批保存帧验收与局限见月度日志。

- 稳定身份由框架分配；截图、框、中心点、模板和匹配位置是观察证据，不能直接证明当前身份、可操作性或成功。
- 逐步 Region 观察的 `bbox` 保存该帧已确认边界；`image_quality` 独立控制新模板资格。受挡但边界明确可有位置、无模板；后续局部定位只读绑定同一截图的前景缓存，不跨帧使用历史框。详见[身份模块](modules/stepwise/identity.md)。
- 区块滚动使用当前单图中的模型坐标，不以同帧区块边界缓存为执行前提；普通与导航滚动共用校验，结果仍按真实前后图登记，详见[动作模块](modules/stepwise/execution.md#区块滚动)。
- 动作提案、实际投递回执、观察结果、任务结算与功能知识分别记录；像素变化、落点识别或 schema 合法都不能独自证明业务效果。
- 每次动作使用当前证据；历史图/路线只提供参考。已执行未登记动作优先结算，不因登记失败重做 GUI；中断恢复保留原请求、回复、回执和纠错历史。
- 地图与历史投影读取已提交账本，不增加执行事实；正式写入沿各实现已有登记入口，保留旧快照与原始证据。
- 图中已发现工作闭合不证明未感知功能不存在。清点完整、任务完成、功能整理、结构闭合与语义验收不能互相替代。
- 逐步任务清点默认专注实际功能；未被专门要求的帮助、关于、快捷键列表等辅助说明只记录，实际功能设置仍探索。旧任务不自动删除/完成；详见[任务范围](modules/stepwise/tasks.md)。
- API/GUI 预算由框架计数和强制执行，不把剩余额度计数放进 Luna prompt；范围与安全授权不由任务生成扩大。
- 指令生成和采集独立消费冻结只读图及固定视觉实现，不修改遍历、其 prompts、活动运行或来源图；本次采集仍检查实际结果。

<a id="41-页面元素与动作"></a>
<a id="42-遍历与恢复"></a>
<a id="43-数据与输出"></a>

Page/Variant、verified routing、stateful 恢复、旧 M13 和各模型协议的精确合同见[原第 4 节](CURRENT_FRAMEWORK_DETAILS.md#4-跨模块不变量)。原 §4 明确适用于 `visual_traversal`；其他内核按各自模块，不把其细则提升为所有实现的共同规则。

## 5. 当前调试开关

逐步流程的共享视觉定位现用原尺寸灰度像素匹配（无边缘提取、缩放或OCR），保留控件组关联；按严格门槛允许漏识别，不能宣称无误识别。默认与相邻输入/整页检查边界见[身份合同](modules/stepwise_region_identity.md#2026-10-03-重复外观控件的位置关联)。旧冻结运行不会自动切换。

本批不新增 CLI 开关或第二条默认执行路径。guided/autonomous/modular 的模型默认、显式实验模式与 fixture 开关见[原第 5 节](CURRENT_FRAMEWORK_DETAILS.md#5-当前调试开关)及对应模块；当前逐步模型配置按[运行模块](modules/stepwise/runtime.md)核对，不沿用其他内核的默认值。
新运行通常在 `artifacts/runs/`；真实旧 run 保留原位，源码由 `run_manifest.json/framework_source` 指定。临时验证在 `artifacts/tmp_tests/<唯一任务>/`，审阅包在 `to_astra/<唯一名称>/`；冻结源不会随 checkout 自动更新。

## 6. 当前全局风险

Clock续跑发现已投递但控件关联unconfirmed的旧父任务会重复none/发现。当前实现将匹配的未确认尝试保留为ownership缺口，继续其他前景工作；此类归属补录尚无完整自动恢复入口，不能宣称原任务已补齐。验证状态见本月日志。Clock末批仍保留r0007/r0008旧摘要登记缺口，不能把修复代码已验称为这些旧失败已补齐。

跨区块总结要求同一目的的本地支持任务，全部外区块支持不能登记为本区块操作；世界时钟列表反例在完整保存帧及实际补录通过；r0016全外区块提案也由正常纠错撤回。结构门槛仍不能自动证明所选本地任务语义相关，不能当作可组合能力质量认证。

当前地图修复候选仍未接受：Stopwatch 虚报 Add、Timer 单位推测、历史控件被列为当前可操作及裁图/归属缺口仍需实际证据核对。本批结构整理不把这些候选、跨区块任务语义重复或已暂停运行变为已通过；具体范围见[身份](modules/stepwise_region_identity.md)、[监督](modules/stepwise_debug_loop.md)和[任务](modules/stepwise/tasks.md)。
各内核还保留模型身份误判、前景/控件漏报、导航/恢复、异常生命周期与大文件职责债务；[原风险表](CURRENT_FRAMEWORK_DETAILS.md#6-当前全局风险)保留对应范围和反例，不以历史测试数宣称当前全图或跨应用稳定。最新机器、源码与停止点读 [SERVER_HANDOFF](SERVER_HANDOFF.md)。

## 7. 验证策略

按现行 AGENTS 选择最小充分层级：Tier 1 文档/非行为检查链接、结构和差异；Tier 2 模块行为与直接相邻合同；Tier 3 受影响共享入口/schema/Router/resume/completion及必要相邻检查。测试从[逐步索引](../tests/STEPWISE_INDEX.md)或相关模块选择，不默认全跑。
行为/prompt 验收使用真实 run 的正常入口构建完整请求，原 Luna 回复不编辑，经过正常校验、纠错和登记，再检查身份、任务与图片。独立陌生读者先阅读、再对照意图；offline、fixture、保存帧模型验证、真实 GUI 分别报告。

<a id="8-文档维护"></a>

模块行为更新对应文档，每批行为变更记录月度日志；全局入口/默认/共享合同/输出/平台/风险变化更新本文。旧 §8 文档维护及其他长文标题由[完整细节](CURRENT_FRAMEWORK_DETAILS.md#8-文档维护)继续承接；普通修改不必读全长文或历史日志。

## 8. 显式全框架回归门

只有用户明确要求，或准备发布、基线、认证、正式外部结果时，运行[显式全框架回归门的 19 条命令](CURRENT_FRAMEWORK_DETAILS.md#explicit-framework-regression-gate)。共享合同改动本身不自动触发全门禁。命令集合保留原 Section 8 历史清单；其中 `tests/test_visual_run_state_machine.py` 当前缺失，不能按原清单直接执行全门禁。本批仅核对路径，未执行或重新确认全框架覆盖；运行目录按现行 AGENTS 实例化为唯一临时目录，保存命令/日志，记录明确要求时的漏跑项、原因与验证缺口。门禁通过不代替原生模型与真实 GUI 语义验收。

## 逐步任务进度补充（2026-10-05）
逐步explore任务以区块内控件+动作复用。2026-10-07进一步按registration_kind要求参数事实、入口语义或试探反馈；动作已执行与所需信息已登记分开，done不能当作业务成功。普通更新用task_update（findings、可空next_action、信息缺口及按类别提供的entry），不要求task_result状态或独立累计完成核对。前置准备的条件观察、异常暂挂、身份修订和真实地图登记仍保留；详见[任务](modules/stepwise/tasks.md)与[更新](modules/stepwise/updates.md)。当前地图的其他未接受候选不因任务进度修改获验收。

## 2026-10-06 最小遍历合同
本批实现：清点缺口不阻挡无关可信pending；区块内缺口仍参与完整性。滚动按当前单图选点，规范任务复用且允许必要准备。新结果schema删模型投递状态复述，可分离参数坏行局部留缺口。区块探索结束后的原子操作总结接入普通调度，历史补清点保留在auto会话GUI空闲之后，预算仍计入框架；旧冻结源及无关地图候选不自动切换。验证结论见本月日志与交接，未验证能力不算接受。

状态依据：目标卡及共同地图不复述旧控件显示值/状态；本轮最新截图决定当前状态。历史保存实际探索努力和结果证据，具体合同见[上下文](modules/stepwise/context.md)。

每轮模型正文按任务相关性披露：相关身份详细、其他身份轻量索引，旧页面描述不作当前状态；当前任务努力与明确来路/准备保留，原回执/坐标在后台。可选身份模板异常局部拒绝，不重复已投递动作；实际点击范围、前景与身份冲突保持严格。当前相邻视觉误绑定风险仍未全面接受。

最终235聚焦检查及代表性原生/两端短批证据按源版本记录；最新source-v14相关性修订为保存帧验收，实机末批source-v11。原始数值/状态不改写，旧裁图与前景排除几何的开放边界保留；不声称全地图或全应用接受。

2026-10-06连续批次修订：本地未执行record_only可沿原纠错reopen_task保留旧判断后探索；状态转换未知结构与自动瞬时值边界在共享提示定义。auto尾段额度由原入口限额执行，人工审查放在会话结束；详见任务、纠错、上下文与运行模块。旧冻结批次不热替换。


2026-10-06空闲续接：当前范围外区块不截断通往范围内未完成目标的既有导航；auto收尾后重进原单步调度，再次空闲则停止。连续知识段保存knowledge、knowledge-0002等独立账本，仍合计HTTP、0GUI；局部结束和知识整理完成均不声明全应用完成。有限验证与开放边界见本月日志及运行/调度模块。

## 2026-10-06 三步组件与集中程序调度
traversal_scheduler统一普通工作选择、pending优先及会话结果解释；Locator、
TaskProposer、ActionProposer、ActionExecutor、ResultUpdater分别复用原发现/任务、
动作绑定、投递和更新登记。主入口仍为run_task_step/run_progress_session，
不新增Luna角色或完成审核。round/scheduling.json保存程序决定和来源快照。
范围外前景可离开；范围外目标不派业务探索；局部空闲不当全应用完成。
当前批次验证范围见月度日志，不接纳原工作树的其他地图候选或宣称跨应用稳定。

2026-10-06角色职责归位：locator持有发现请求/schema及定位；task_proposer持有任务提示/schema/上下文；result_updater持有更新请求及候选校验。发现后的导航/局部检查和目标退出归调度器，shared_tasks独立承接任务共享与失效清理。正式登记仍用discovery_step、region_tasks、register_update；调用方直接进入角色模块，update_step及本轮角色转发出口已清退。原平铺源码根与运行入口不变，较早的11目录方案已归档。验证范围见本月日志。

2026-10-07探索与总结：任务提示按新入口功能、功能参数、不确定控件三类说明探索目的；区块有效探索任务结束后，由调度器安排原子操作总结，沿用region_functions及原校验登记。region_role描述表面用途，参数表面可为functional且functions为空；完整业务目的及其约束才进入原子操作目录。详细合同见[知识模块](modules/stepwise/knowledge.md)，验证范围见本月日志。

原子操作可跨相关区块，仍挂业务主区块：function_scope组织图上的证据候选，region_functions提供跨区块任务/参数引用并校验登记。support_tasks保留结构化region/task来源；本地task_refs、任务身份和真实动作归属保持原合同。相关证据变化触发更新，图连接不自动等于业务归属。

2026-10-07登记结算：TaskProposer指定registration_kind，ResultUpdater沿正常更新登记对应产物，task_settlement据真实绑定与已登记信息结算；缺口保存并暂挂，原动作不重放。旧完成记录不追溯重判。参数登记、缺口保留、跨区块总结与调度已有有限原生/实机证据；新entry产物分支尚未原生验收，详见任务/更新模块及本月日志。

2026-10-07任务后知识：普通结果更新提供稳定knowledge，原任务完成后才归入控件；区块current_observation维护当前帧状态，换帧不沿用。未知交由已有任务推进/暂挂，local_knowledge不另维护unconfirmed清单。请求与保存连接见[任务后知识设计](TASK_KNOWLEDGE_FLOW.md)及任务/更新/上下文模块；验收范围见月度日志。

2026-10-07前景简化：删除未用于范围判定的excluded_areas输出字段；发现/更新共用interactive_areas作为当前可交互范围。前景归属、背景接管、点击和模板校验边界不变。验收见月度日志。
