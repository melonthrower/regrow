# 区块、路由任务与复杂任务设计

本文件维护Clock逐步实验的当前设计；实现只在本实验及既有framework_copies副本中，不替代原gui_rewalk框架。入口为run_task_step.py，整体流程见[PIPELINE_DESIGN.md](PIPELINE_DESIGN.md)。

## 1. 为什么菜单和子区块使用同一个返回规则

进入新区块不等于立即返回。菜单有待探索入口时继续菜单；子区块的基础探索完成后恢复来源区块；菜单完成后才恢复主页。

```text
主页 --点击菜单--> 菜单 --入口动作--> 子区块
                    ↑                │
                    └--完成后尝试退出─┘
主页 <---菜单完成后尝试退出--- 菜单
```

运行状态region_path保存实际进入链。更新后只有一个已确认落点时，进入新落点追加，落到链中已有区块截回该处。首次读取旧记录时，沿有真实回执的reached_by恢复来源；不从名称或视觉包含关系猜父子。该链是任务恢复依据，不是返回路线证据；Back执行后更新才能登记真实返回边。多前景/未知位置不擅自选一个父区块。

working_region保留既有工作标记，调度不再把它当所有子区块唯一返回目标。实际来源父区块由task_routing.parent_region计算，因此菜单本身是working_region也仍可在完成后返回主页。

## 2. 路由任务的三种基础目标

路由任务是调度单位，挂在Region.tasks下，由Luna提出、框架验证和派发。task_type区分：

| 类型 | 归属 | 完成依据 |
| --- | --- | --- |
| single_action | 控件 | 执行一次指定操作并观察目标结果；投递回执不直接完成任务 |
| parameter | 控件/该功能的来源区块 | 获得目标所需选项、输入范围或条件，允许跨子区块多步，不穷举组合 |
| scroll | 区块，control=null | 调查指定范围未见内容并登记结果；滑动成功不代表调查完成 |

导航是到达任务位置的服务动作，不是第四种功能。active_task保存原任务区块和名称；参数/滚动任务跨区块后继续原目标，不为每个落点复制同一任务。执行binding分开保存实际region_ref/control_ref与task_region/task_name。更新把真实动作登记在实际来源，参数知识和任务结果登记在原任务。

沿用原框架的handling与canonical-operation原则：已显示的同目标入口、明确基础操作可record；含义不明的设置/菜单不可因外观常见而跳过。只有相同对象、操作、类型和效果有依据才equivalent；共享任务结果，不伪造其他入口的执行记录。defer/blocked保留缺口，不能作为完成。

任务清点complete、没有遗漏的新控件、全部探索任务done，才判定本区基础探索完成。部分清点或任务发现未登记控件时回到发现步。此完成只覆盖已声明的任务范围，不表示证明应用没有其他功能。

## 3. 三步流程中的触发位置

| 环节 | 路由任务 | 功能登记 |
| --- | --- | --- |
| 发现与登记 | 先确认区块及当前控件；任务清单缺失或出现新控件时，task_proposal提出single_action / parameter / scroll任务并去重。当前有跨区任务时继续原目标，不把落点自动变成新业务目标。 | 直接可见的参数可随任务findings登记。基础任务全部完成且功能依据尚未整理时，function_registration整理功能目录。它是第一步的登记子环节，无GUI动作。 |
| 动作 | 从待办中派发一个基础任务，必要时导航；每轮仅执行一步。 | 功能目录不进入动作队列，不执行组合功能，不挑选具体目标值。 |
| 更新 | 根据真实前后图登记效果、参数发现和pending / done / blocked；框架重新计算探索进度。 | 新事实使原功能目录摘要过期，下一轮第一步重新整理；不每个动作额外调用功能整理。 |

运行入口run_task_step.py依次处理必要的发现、任务清点、功能整理，再执行至多一个动作并更新后暂停。三步请求以pipeline_step=discovery / action / update标识；stage区分其内部子环节。位置未知或有异常时，先处理原发现/异常分支，不能越过门禁整理或执行。更新已登记且可信的区块清单不必再次拍图重报。

发现与登记的两个子调用不强制同时发生：有待办就直接进入动作；任务全部完成才整理功能。纯导航区可以登记空functions并写明依据；完全没有任务的区块不为凑目录发模型调用。相同依据不重复整理，之后按实际来源链恢复待办。没有把功能目录缺失解释为需要创建一个业务实例来验证。

## 4. 物理存储：参数事实与区块功能

仍为每区一个region.json：

```text
region.json
  controls[控件].task_refs
  tasks[路由任务名]
    task_type / control / handling / status / reason
    attempts / visited_regions
    findings[参数名]
      description / domain / conditions
      source / sources
  functions[功能名称]
    description / object / completion / region / task_refs
    locations: [{region, control}]
    constraints[任务名 / 参数名]
      name / description / domain / conditions
      locations: [{region, control}]
      sources
    unconfirmed / source_call
  function_inventory: evidence / evidence_digest / source_call
```

findings由两种已有观察取得：任务清点时的截图直接观察，或更新步的task_result.findings。前者引用source_call，不生成attempt；后者引用实际动作及所在区块/控件。两者共用参数校验，不能从名称推断范围。类型支持enum、integer、time（已观察HH:MM输入能力）、text。同条件枚举分批合并并保留来源，不同类型/条件要求分别命名。

Luna整理functions时，输出功能名称、描述、作用对象object、完成边界completion、支持它的任务名、参数事实名、未确认事项。框架从引用复制约束的类型/值域/条件和来源，生成真实所在区块/控件索引；禁止未知引用，不要求模型重写ID或值域。支持同一功能关联多个控件以及参数位于子区块。明确可见而handling=record的能力也可入功能目录，不需要先执行。record表示直接观察，不等于效果验证。

功能目录保存可组合的材料，没有goal、选定value、待执行status或复杂任务队列。依据摘要包含任务及参数记录，新增事实后必须重新整理才可把目录当作当前版本读取；旧快照、请求/回复仍保留。图的跳转边依然只来自真实动作更新，功能整理不新增边。

## 5. 单区块任务粒度与之后的指令重组、采集的边界

一般规则及成对正反例见[BENCHMARK_TASK_GRANULARITY.md](BENCHMARK_TASK_GRANULARITY.md#通用判定规则与正反例)，同文保留Benchmark来源。功能登记专用的判定规则prompt采用相同六条规则：用户结果、单区块完整目的、完成边界、约束槽位、与步骤数无关、证据边界。当前functions的单位是一个功能区块中可实现的用户任务能力，有明确对象和结果；不是“输入文本”“点击按钮”等通用技能。一项设置修改可以是完整任务，不以动作数量决定粒度。参数弹层位置可关联，但不把多个独立业务区块协作称为单区块任务。

object和completion是Luna基于已有证据登记的语义描述，框架检查非空及任务/参数引用，不用关键词黑名单声称已经证明任务语义正确。缺少结果依据保留unconfirmed或不登记该功能；当前尚无新版prompt的Luna实测。

遍历记录“设置闹钟”及其可设置约束：

| 约束 | 本阶段保存 | 所在位置 |
| --- | --- | --- |
| 时间 | 输入类型、已观察格式/范围 | 实际时间设置区块与控件 |
| 周期 | 已观察周期选项 | 实际周期选择区块与控件 |
| 振动 | 已观察开关选项及条件 | 振动控件所在区块 |
| 标签 | 已观察文本输入能力 | 标签编辑区块与控件 |

上表说明结构，不是本轮Clock实测数据。遍历阶段不构造“每周六07:00振动闹钟，标签早饭”。后续指令重组才选择目标及合法约束值、组合功能；采集再使用所在区块和真实图关系定位，执行具体任务。参数可设置不证明组合兼容或业务已生效，unconfirmed保留提交行为、条件等缺口。

沿用原记录的分层：design/modules/region_function_collection_research.md的功能目录与FunctionInstructionDesigner相互分离；当前原实现region_function_inventory也包含未执行操作的parameter_information、结果和locations。本实验复用这一语义边界，不移植原Page/State账本或启动下游生成器。此次纠正撤下上一轮具体复杂任务生成代码与prompt；历史副本与Git保留。

## 6. 动作边界和实现

普通探索与恢复使用同一个Android动作合同：click、double_click、long_press、input_text、scroll、back、wait，none仅表示不投递；输入附text，滚动附end_x/end_y。旧tap证据可读，新请求只输出click。动作后等2秒截图，ASCII输入限制不变。功能目录的文本能力记录不等于执行适配器已支持所有文字，也不需要为登记而实际输入。

- region_tasks.py：任务清点、续接、覆盖计算、参数事实；按进度触发功能登记。
- region_functions.py：引用已有任务/参数整理functions，附上位置及来源；不生成指令。
- task_routing.py：实际进入链，分开任务所属与实际动作区块。
- run_task_step.py：将task_proposal / function_registration接入第一步，后续仍为动作和更新。
- 固定prompt：任务/区块探索任务.prompt、任务/任务结果核对.prompt、任务/区块功能登记.prompt；参数发现.schema作为独立格式片段复用。

验证及合成记录见records/035_function_inventory_20260920_01/REPORT.md。本轮只进行离线合同与模拟运行入口验证，没有Luna/设备执行，不宣称已获得Clock闹钟功能目录。

## 7. 两类登记的独立prompt与调用时机

路由任务：识别区块/控件后，task_proposal仅加载任务/区块探索任务.prompt，在动作前登记；动作后的更新步结算任务并积累参数事实。新控件使清点不完整时先补路由任务，保留旧功能记录作为历史。

功能任务能力：基础探索完成且依据未整理时，function_registration顺序加载任务/区块功能登记.prompt（职责/字段）、功能识别/单区块任务判定规则.prompt、功能识别/单区块任务正反例.prompt，组合为本次system_prompt；区块实际知识进入user_prompt，输出结构仍用区块功能登记.schema。fixed_parts保存实际加载路径和文本，便于检查。路由清点和动作请求均不加载功能规则与正反例。

两个登记都是第一步的子环节，但位于探索前后不同时间。request和register均要求基础探索完整，pending、blocked、部分清点、未覆盖新控件均不能提前整理。无待办的明确record项可直接进入功能整理，不为了凑动作而执行。依据不变不重复调用。本次接线检查见records/037_registration_timing_20260920_01/REPORT.md。

## 8. 区块用途与统一异常恢复（当前合同）

功能登记在同一次回复中提供region_role与role_evidence，取navigation / functional / mixed / undetermined；navigation须为空functions；functional/mixed描述业务或参数用途，可在仅支持参数步骤时返回空functions并说明。用途不作为提前跳过路由探索的依据，也不修改Region身份或跳转。新事实可修订分类，尚未确认不能算纯导航。

发现foreground、更新action_result使用exception=none / blocking_popup / unexpected_exit / external_app / unclassified，并提供recovery_handoff。旧uncertain仅用于读取历史，不在新请求枚举中。明确异常时regions/controls为空，保留原图，进入recover；更新仍登记原控件真实动作及异常，不造外部目的地边。unexpected_exit表示异常退出现象，不能归因于虚拟机或断言崩溃根因；其来源任务由框架暂挂，不由恢复成功解除。

恢复调用只接收固定规则、当前截图、中断工作、交接和本次历史。decision区分act / resume_exploration / stop；action嵌入与普通探索完全相同的选择探索入口.schema，framework_tool单独允许restart_app。restart是保留数据的框架工具，不是benchmark原生GUI动作。普通探索及恢复的GUI命令都由action_commands.execute投递并计数。当前实现限Android，沿用原框架动作语义；不把桌面hover伪装成Android支持，也不宣称完整实现所有benchmark扩展动作。

临时恢复回合统一由recover_loop.py执行；旧外部恢复CLI只保留入口与传输适配，转入同一个循环。恢复动作后等2秒取得新截图，直接交给下一次恢复调用，不识别业务区块、不调用业务更新。history记录模型判断与实际回执；新交接是上下文，不能覆盖固定规则。非阻塞提示可resume，但随后发现步仍需确认可交互范围。

框架每次有界调用最多6HTTP/6GUI命令、每恢复episode最多4动作及1次重启；两次返回后仍确认外部应用可自动重启保底。同目标同动作仍报同类阻塞时停止盲重试；投递异常/中断保持review_execution，重新进入也不重放。恢复历史保存在run/recovery_episodes/<episode>/episode.json及配套截图/回执，与Region图分开。只有resume后进入原发现与登记，不假定返回旧位置；未知/受阻任务不被恢复成功改成完成。

固定prompt分别为异常处理/异常识别.prompt（发现与更新共用）、异常处理/恢复当前探索.prompt（单一恢复调用）。未发布的清理系统提示专用分支已撤下，不与共享循环并存。验证证据见records/040_unified_recovery_20260920_01/REPORT.md。

补充执行边界：普通/恢复动作均输出target、action、x、y、reason、text、end_x、end_y；后三项仅输入/滚动时使用，其余填null，保持结构化接口格式固定。任务提案统一click/scroll，旧tap任务重识别时保留进度。恢复回复exception=none时，框架强制resume_exploration，不执行回复中附带的动作；屏保等应用内显示不能仅因没有控件就作为异常退出。

本轮验证：123项离线检查通过；实机6次HTTP（1次400、5次成功）、2次GUI。关闭Got it成功，但旧循环随后多执行了返回，未登记屏保；新增none门禁已用call0024真实回复离线回放验证，尚未重新进行实机恢复。当前已回Clock主界面并完成发现，菜单工作未完成。详情及限制见上述records/040报告。

## 控件识别框与点击框（2026-09-22）

同一次控件观察保存 `bbox`（身份识别框，含必要标签）与 `click_bbox`（实际操作框），均为来源整屏坐标；`image` 裁识别图，`click_image` 裁操作区域，随观察证据保存在对应Region中。独立图标仅作外观附件，不充当点击区域。识别图匹配当前屏幕后，框架按匹配位置与尺度映射操作框；普通动作候选、自动回溯和输入框重定位使用操作框。两框独立，无包含关系要求：例如侧栏用图标加文字识别、整行点击。扩大识别框不会自动扩大可点击范围。不能确定操作框时填null，不以标签区域代替。

发现与更新使用相同两框说明；历史单框记录不改写，后续重新观察补齐。框不参与持久身份编号判定，也不是当前实时坐标；当前动作仍使用当前整屏坐标。本次只实现两框保存与消费，未改变视觉候选对模型动作的既有绑定规则。

验证：`tests/test_stepwise_control_boxes.py`、`test_stepwise_visual_choices.py`、`test_stepwise_visual_backtrack.py`、`test_stepwise_input_target.py` 共26项离线通过。修正回溯测试中漏隔离的探索循环观察器（旧模拟knowledge指针为空，与本次两框无关）。原Settings截图手工提供两框重放，正确匹配Automatic Screen Lock行和对应开关；测试与日志在 `artifacts/tmp_tests/control_two_boxes_20260922/`。未调用Luna、未执行GUI、未证明模型两框输出准确率。

## 完成区块的功能补整理（2026-09-22）

探索覆盖完成与功能整理完成分别判断。`historical_inventory.request` 每轮检查所有已完成且有任务证据的区块，补充未整理、事实变化或固定提取规则变化后的功能登记；不要求区块当前可见，不改变当前 GUI 任务或观察。已有 function_registration 暂挂缺口继续保留，不无限重试。连续多个功能待办每轮处理一个，返回 ready_next_round，自动遍历不会因下一个仍是功能登记而退出。

`region_functions` 请求附已观察控件的名称、状态、用途和不确定项；签名包含实际使用的三个固定 prompt 内容。明确可见的设置能力允许登记，修改效果未验证写 unconfirmed；当前值不冒充完整值域。禁止执行的环境设置仍可只读建档。参数菜单保留参数事实及用途，完整用户目的才登记为原子操作；纯导航不挂目的区块功能。

验证：49 个聚焦测试通过，语法与 diff 检查通过。Settings calls 0194–0199 为真实 Luna 补提取，6 HTTP、0 GUI：Screen 5 条、Connectivity 1 条、三个参数菜单各 1 条，Privacy 导航返回空并撤下旧误挂功能；旧快照保留。仍有当前 Applications 菜单关闭动作绑定阻塞，本修改不处理该执行问题。证据 records/234_function_backfill_20260922/。

## 模型坐标执行与控件关联分离（2026-09-22）

普通点击和文本输入仍尝试名称/图片关联，但候选缺失、图片冲突或对象不唯一不再否决模型坐标。整图坐标、动作格式及平台约束继续校验；没有目标描述或越界仍拒绝。匹配明确时保留原控件关联；否则 source_control=null，binding/action.association 保存目标、坐标、候选与未确认原因，不猜最近控件。未关联输入不使用历史输入路线推断。

未关联动作先保存在实际前景来源区块下，前后图和执行回执照常记录；第三步同区块明确重报同名控件且新点击框包含动作坐标时补关联，否则保留缺口。菜单外空白关闭可长期为区块动作，无需虚构控件。投递前画面变化仍要求重新观察；图片匹配不能改写模型坐标。关联为空的不同目标/位置不合并为重复点击。缺少历史控件定位也不强制先走纠错，允许普通动作调用选择必要准备动作。

Settings 的共享菜单仍为 r0003：r0001/c0002、r0010/c0049、r0022/c0081 的实际入边共享同一控件及任务记录，不重置完成状态。该改动不取消区块共享，也不把菜单关闭混作重新探索菜单项目。

验证与实跑证据：records/235_coordinate_execution_20260922/REPORT.md。

连续功能补整理的 evidence_digest 变化算实际进展，循环检测不再把这些无GUI回合当作重复动作；相同摘要仅换调用号不算新进展。可视化不再把单纯缺少历史控件定位显示为阻塞，真正的待纠错/执行异常仍显示。

进度页将历史控件当前未定位显示为蓝色“观察提示 · 不阻塞遍历”，与真实阻塞卡分开。后端 localization_notice 提供当前工作任务缺少的控件名称；网页即使收到仍驻留旧服务返回的 task_control_unlocated，也按信息提示呈现，不显示旧暂停指引。真实 pending_step_repair 等错误仍保留。更新 HTML 后重新加载页面即可，无须为展示更新打断遍历。验证：16个进度测试、3个JS渲染场景及JS语法检查通过，实服务HTTP确认已提供新HTML。证据 records/236_display_notice_20260922/。

## 模型回复解析错误（2026-09-22）

临时框架在 `call_model_once` 的调用适配层逐条读取完整 message；同一 message 内文本片段拼接，多个 message 各自解析。JSON 对象内容相同则去重；冲突、空、损坏、非对象或服务标记不完整的回复保存 `parse_error.json`，错误代码 `model_response_parse_error`。保留原 `raw_response.json`，不任取最后一条，不执行多个提案。

三步及其任务/功能登记在现有 Runner 中转入原步骤纠错；补观察解析错误也回原步骤。使用既有 blocked_by 字段，保持两次纠错上限，原请求、截图、已执行 attempt 不变；更新失败只修登记，不重发动作。新运行清单记录 framework_source，复制的调用脚本读取匹配来源的解析器。

范围：独立异常恢复与分支切换等不经 Runner.perform 的调用可使用同一解析器去重，但损坏回复尚未接入阶段纠错；不宣称全通道自动恢复。14项解析/纠错测试、7项启动器测试通过；其中一条旧展示断言同步为“未定位只作提示”。真实0238保存回复离线解析成功，未新增模型或GUI动作。陌生读者首次发现补观察漏接与已执行动作测试缺口，补齐后复核通过。运行冻结源码与call_once已备份更新，当前仍停在旧断点，未重新启动遍历。证据：records/237_model_reply_parse_20260922/。

## 全Prompt审查后的六项修复（2026-09-22）

导航固定模块、准备动作、目标命名与多跳动态路线统一：截图中目标及作用可靠时可操作未登记目标；不能辨认时才请求发现。桌面scroll不承担拖动面板。恢复嵌套动作包含skip_task=false，共享跳任务说明仅适用普通探索；无允许恢复办法时按原恢复stop合同处理。

视觉回溯运行时投影不再将历史语义冒充本轮识别：投影保留semantic_source并标visual_only，目标观察明确本轮仅匹配外观，文字/状态/实例沿用历史。原观察不修改；新模型观察仍可声明本轮识别。任务清点说明区块描述来源与实例核对，登记名实例与截图冲突时partial披露归属缺口，不把新对象任务绑旧实例。本次没有迁移或人为改写旧图身份。

循环纠错动态上下文将位置/工作区块映射成名称，用实际摘要比较披露进展；内部hash保留后台。新循环记录保存最近登记动作的目标、操作及结果，旧记录缺摘要明确未知；不伪造每轮执行动作。触发与暂挂判定不变。

验证：49项聚焦离线测试通过；覆盖来源投影、动作/纠错共用观察、视觉回溯、多跳动态路线、循环分支、恢复示例及阶段纠错。修正相邻旧测试中的缺skip_task、旧entry_name、忽略返回请求副本、仍要求拒绝未登记坐标等过时断言，未据此改变执行器。陌生读者复核发现的多跳内联规则、目标命名与实例绑错风险已补齐，并复核通过。真实保存记录离线组装3类完整请求，分支展示单独转换，多跳另用明确标记的合成图。无新模型/GUI验证；证据records/239_prompt_fixes_20260922/，测试日志artifacts/tmp_tests/prompt_fixes_20260922/final.log。

## 2026-09-22 前置条件与截图传输
任务清点与动作选择先区分疑似前置条件及允许范围。准备动作允许时沿动作→更新观察是否解锁，不将灰色外观当作已验证依赖；受限且无允许替代办法时，动作none/skip_task沿现有任务登记defer/blocked。原因保存在deferral和blocker，包含依赖、依据、限制、未验证之处；保留尝试，清除活动任务，继续其他待办。review_required不会因重新定位自动解除，不把依赖缺口计为record_only或完成。任务清点阶段本来就禁止的操作仍可record；旧范围复核不得将前置条件受限的任务当作目标本身禁止。此轮不回写历史Sharing判定。
桌面截图读取的断流、连接失败和超时纳入既有三次读取机会，记录失败类别；不重试GUI投递。实跑0406在a0101/pre_dispatch截图前断流，点击未投递。历史搜索退出证据0239/0240、a0053：点击Applications返回按钮，侧栏恢复主导航，右侧详情保留。
验证：40项聚焦离线测试通过，包含受限任务暂挂、其他待办可调度、重观察不自动解除、截图断流恢复和耗尽。测试日志artifacts/tmp_tests/prerequisites_20260922/green.log；不等同于Luna前置条件判断的实机验证。

## 2026-09-22 截图临时故障持续等待
桌面截图断流、连接超时/临时连接失败、502/503/504和无效PNG持续重取，不消耗模型/GUI额度，不重复投递动作；间隔从1秒增至最多5秒。配置错误、证书错误、其他HTTP错误继续明确报告。既有网页阶段详情展示失败次数及等待时间，保存capture.json当前状态与capture.jsonl逐次记录，损坏响应保留首个样本。正常取图恢复后继续原调用栈。
截图等待检查现有会话pause文件，退出为paused_by_user而非interrupted；保留execution_pending及已记账动作，下一次沿原恢复路径继续。单次HTTP读取中需等待返回或15秒超时，退避等待每0.25秒检查暂停。未在设备执行层重试动作。
前置条件陌生读者复核补齐：任务复核动态上下文提供暂挂原因/恢复条件，网页不再对review_required声称重新定位会恢复。当前前置依赖变化仍需显式复核，尚无自动解除该类暂挂的路径；不将此能力描述为已实现。报告artifacts/tmp_tests/screenshot_retry_20260922/review.md。
验证：53项聚焦离线测试通过，含连续5次断流/坏图后恢复、暂停保留投递记录与会话额度、配置错误不重试，以及依赖说明披露和网页恢复提示。日志artifacts/tmp_tests/screenshot_retry_20260922/final.log；未进行新Luna前置条件实机试验。
补充验证：本地注入4次截图断流后读取真实VM截图成功，0 GUI/0模型调用；并非实机故障重现。运行副本同步与证据位于records/246_screenshot_retry_20260922/。读者复核两项披露修正通过，自动解除暂挂仍为明确的未实现边界。

2026-09-22 Clock截图500遗漏：Clock首段完成28次HTTP、10次GUI后，在下一轮current.png读取收到HTTP500而中断（上一动作已更新，无pending投递）。截图重试范围补入500；仅影响只读截图端点，执行命令仍不重试。25项desktop/progress离线测试通过，日志artifacts/tmp_tests/clock_capture500_20260922/green.log。后续真实取图200但仅桌面，进程探针未见Clocks；原因未证实，不能从截图接口恢复推断应用未退出。先前口头“没有退出”判断已纠正。证据records/249_clock_capture500_20260922/；恢复仍由现有遍历观察/恢复流程处理。

## 2026-09-22 恢复重启后的反馈与停止原因
恢复请求动态披露重启工具是否已用，附已执行启动回执。重复请求已用的重启工具时，首次不投递、不立即停止，而是反馈限制并重新取图交给Luna选择等待/退出概览/切回窗口等允许操作；再次无视同一反馈则明确停止，原动作与HTTP预算保留。仍不是无限重启。所有恢复停止结果带reason，网页会话状态优先展示具体原因。
桌面重启以独立会话启动目标、断开stdin，保留短启动诊断（PID、两秒后的退出码及末尾日志），避免把shell成功解释成应用已恢复；最终仍由截图观察确认。Clock历史进程消失根因未证实，不能声称此改动已经根治退出。诊断人工启动与原自主恢复分开记录；原stopped episode备份后显式重新开放，让Luna看新图继续恢复。
验证：34项desktop/progress/unified recovery离线测试通过，包含重复重启反馈后的恢复、只发一次重启、执行回执披露。日志artifacts/tmp_tests/clock_recovery_20260922/green.log，现场证据records/251_clock_recovery_20260922/。没有改变Settings运行中副本。
实机后续：诊断性启动后的现场中，0035由Luna点击系统概览窗口缩略图，0036确认Clocks前景并resume_exploration，0037进入发现。验证了恢复提示能指导替代操作与三步流程衔接；不等同于新启动命令独立完成整个故障恢复，也未证明原应用退出根因。

2026-09-23 前景辅助读取断线：Clock已完成0051更新后，下一轮foreground_window的只读execute连接重置，尚无新GUI投递。DesktopRun只将此读取的临时连接失败/超时/断流返回为窗口信息未知并附错误类型，继续截图核验；不把未知写为目标应用确认，不重试动作，配置/证书错误仍报告。27项desktop/progress局部离线通过，日志artifacts/tmp_tests/foreground_read_20260922/green.log；证据records/253_clock_foreground_read_20260922。仅部署Clock暂停副本后续跑，Settings运行副本未热改。

## 2026-09-23 框架取图、网页缓存与已投递断点
框架独立采集截图；progress_window的/frame.png只读当前run的live_frame.png（尚无缓存时读取initial.png），不再代理VM截图。页面明确显示最近缓存观察而非实时投屏；关闭浏览器不改变取图或调度。Android/桌面采集成功后原子发布缓存，缓存写失败不使已取得的动作观察失效。
桌面manifest.desktop.container登记目标本地OSWorld容器名/ID，configure保留manifest；guest截图连续三次临时故障后，通过该容器QEMU监视器读取显示帧，保持完整原图像素，不发送GUI动作。成功后run/capture_backend.json记住备用来源，后续轮次直接使用；两种取图都失败仍等待并允许暂停。新取图模块desktop_capture.py；每张图的source.json记录来源。容器关联必须来自实际创建/连接记录，不按应用名推断。没有容器配置时保留guest重试，不能宣称已有备用接线。
已投递动作有成功receipt但缺after.png/update_request时，resume_update_request只补截图并复用build_attempt_update构造更新请求，再进入原第三步；普通执行也调用同一构造函数。缺成功回执仍不重发。既有after图和窗口证据保留；旧图缺同期窗口证据时标未知，不拿当前窗口混配旧图。
陌生读者查出configure漏传manifest、旧窗口证据覆盖、网页回调仍称实时三项，均修正后复核通过。47项聚焦离线测试通过（capture_pipeline、desktop、progress、resume_route、unified recovery）。实机Settings原接口真实3次超时后52.4秒取得QEMU显示帧，网页字节与缓存一致；Clock备用显示读取同样通过。证据records/255_capture_pipeline_20260923/，审查与测试日志artifacts/tmp_tests/capture_pipeline_20260923/。后续真实断点更新结果另记。
实机断点验证完成：Settings a0132补采后进入更新并提交，pending解除，action_attempts数量保持132、receipt哈希未变，本轮0GUI；Clock普通轮2HTTP/1GUI成功updated。辅助前台读取单独限时5秒，临时失败保持unknown，GUI投递仍90秒；独立读者对此复核通过。两路旧观察服务器已替换为缓存读取服务器，原端口不变，均未启动额外的VM截图轮询线程。

## 2026-09-22 正常前景导航与循环诊断
发现步已确认正常前景但历史路径required_control未在局部观察出现时，保留working_region，进入explore/navigation_from_foreground，不再转review_result触发应用恢复。历史路径仅作建议，允许从当前标签或菜单寻找入口。导航提示区分途经菜单与无关遮挡，并从动作账本披露最近六次成功投递的实际结果；不把单次未跳转解释为入口永久失效。
无活动任务的导航/恢复循环使用稳定清单、任务状态和动作关系比较，忽略观察措辞、参数显示与功能摘要改写；活动任务包括父任务在子编辑器操作仍保留参数进展。恢复阶段不再跳过循环观察，有未结算投递仍不触发。重复一至三步位置三次后沿原纠错/切换分支处理，不自动写完成。纠错说明同步披露此判据。
验证：44项局部测试通过，日志artifacts/tmp_tests/navigation_loop_20260922/final2.log；Settings原0533回复在隔离副本真实commit回放进入explore。陌生读者指出跨编辑器参数进展误伤，已限定无active_task并补测试。保存帧实际Luna调用：Settings选择Security；Clock首测仍关菜单，补最近动作披露后二测选择双击Keyboard Shortcuts。schema和动作解析通过；未发送GUI动作，未证明实际到达目标。全部原运行保持暂停。证据records/257_navigation_loop_20260922/。

## 2026-09-22 导航动作空间与普通执行共用
导航使用现有共享ACTIONS/schema/平台执行器（click、double_click、long_press、input_text、scroll、back、wait、none），不再因缺独立输入任务拒绝input_text；导航scroll由当前整图坐标核验，不依赖历史Region裁图匹配。仍检查文本类型、截图存在、坐标边界与滚动位移，环境保护规则保留。固定导航提示同步加入搜索输入正例，删除一律关闭前景和不允许提前输入的冲突表述。未增加benchmark中尚未实现的新动作类型，不宣称覆盖全部benchmark。
验证30项局部通过（resume_route、prompt_semantics、input_target、list_input），日志artifacts/tmp_tests/navigation_actions_20260922/final.log。Clock原0190回复现在通过绑定流程，仍如实保留控件关联未确认，由更新补登记；执行器生成点击、Ctrl+A、写入World，离线未投递GUI。证据records/259_navigation_actions_20260922。Settings实机a0136已进入Security，视觉回放打开Cipher列表，a0137进入后续更新；并非本次输入改动的GUI验证。

## 2026-09-22 标签内容分区与合并后历史清点
发现/更新共用身份提示区分公共导航/操作与职责不同的标签内容，先分区后复认。旧整窗候选不能限定本轮只有一个区块，也不能被拆出的公共区冒用；发现new/null与更新空字符串按各自schema说明。全局定位目标只用于focus_presence，目标未出现仍报告当前前景，不将当前正常窗口全部排除；局部模式保持原契约。
本次重复控件来源确认：r0052合并到r0042时两套不同ID控件均被保留。显式区块合并后仅对同名、同源截图、同bbox、同裁图的重复条目自动归并；证据不足标duplicate_controls待核对，不以同名或同图标猜身份。显式控件合并完成后清理该缺口，其他缺口保留。
纠错并未忽略revise中的record_edit：原来合并后历史digest变化导致任务提交回滚。现先在事务内验证原历史请求仍有效，再应用显式修订，刷新同一历史截图的清点请求/digest，最后任务验收，失败不发布指针。原图、原回复保留，未绕过并发旧记录保护。
40项聚焦测试通过（region_merge、historical_inventory、task_correction、prompt_semantics、local_region_discovery、shared_region_identity）。扩展旧test_region_registration有8项失败；用修改前3个模块的隔离副本对照同样8项失败，主要旧entry_name格式不兼容，未作为此次通过项。日志artifacts/tmp_tests/region_partition_20260922/。
陌生读者查出同图标误合并风险和发现/更新空值冲突，修正并复核。真实Luna分区首测及后续失败均保留：第4版General/Security各输出公共区与当前内容区、均new；schema、身份标准化、登记预演通过。新Luna纠错在副本成功26->14控件、14任务清点完成。证据records/261_region_partition_20260922/。无GUI投递；未将旧整窗54控件/历史动作自动迁移至新内容区，原活动图不改，预演不是完整历史迁移完成。后续应按各控件历史截图核对迁移，不凭名字或编号范围猜测。独立读者+真实Luna验证偏好记入根AGENTS.md，作为以后遍历开发的持续要求。

## 2026-09-22 活动任务中的恢复循环
存在活动任务也可能反复进入恢复分支。连续重复的恢复/探索周期按稳定任务状态、控件清单和动作关系判断进展，不因观察措辞改写重置；任务 findings 的 domain/conditions 新增仍算进展。普通探索继续保留可见参数变化判据。检测后沿现有纠错切换路径处理，不将暂挂写成完成。
验证：17 项局部测试通过（artifacts/tmp_tests/recovery_cycle_20260922/green2.log）；Joplin 保存的真实账本重放识别两步周期重复三次。陌生读者通过；Luna 只读历史也判定任务未完成、应停止重复 Wait。未投递新的 GUI 动作。证据 records/263_desktop_batch_20260922/joplin_recovery_loop/。运行中的冻结源码未覆盖。

## 2026-09-22 批次初始化顺序与窗口恢复

2026-09-22 启动等待超时：批次 `records/267_launch_observation_retry_20260922/prepare_android.py` 对已发送的 `am start -W` 等待超时保存原始部分回执，再沿原前景/权限归属和截图核验继续；不重发启动、不将超时算作成功。其他命令失败和明确启动 Error 保持拒绝。四例模拟探针通过（`artifacts/tmp_tests/android_launch_observation_20260922/probe.py`、`green.log`），陌生读者审查通过。SMS 实机确实发生 wait_timeout，后续识别到同任务内的权限请求，并完成两次 Luna 回复；但系统无响应弹窗期间再次发生投递前目标变化而停止，尚未正常进入主界面。证据 `records/267_launch_observation_retry_20260922/live_observation_validation.json`。此次只更改批次初始化脚本，已运行应用的冻结源不变。
本轮批次脚本 `records/264_startup_retry_20260922/prepare_android.py` 在清理目标应用前等待 Android 用户为 RUNNING_UNLOCKED，避免在用户解锁阶段启动目标。Broccoli 的原日志明确记录启动后被 clearApplicationUserData 停止；同一已解锁实例按新顺序重置启动后，前景和截图确认进入食谱主页。冷启动等待路径仍待后续补跑核验，不能外推其他启动失败的原因。
桌面 `prepare.py` 对匹配目标但异常小的窗口只请求一次最大化，随后重新观察尺寸才准入。Calc 原窗口24×26，实机最大化后已显示完整表格；正常尺寸窗口不改。两项各自的局部模拟检查及陌生读者复核通过；证据分别在 artifacts/tmp_tests/android_unlock_20260922、tiny_window_20260922，以及本批 broccoli_unlock_probe、libreoffice_calc/startup_diagnostic。这些是初始化验证，不是应用遍历完成；补跑使用新记录，旧失败和现场证据保留。

## 2026-09-22 循环历史区分登记轮次和新动作
循环账本为最近动作保存后台动作引用；纠错上下文只在引用改变时说明有新动作。同一引用且摘要不变折叠为“本轮没有新增”；同一动作后续结果修订仍披露新结果，并说明不是新执行。旧账本缺引用时明确无法确认执行次数，不按轮次推算点击次数。未修改循环检测阈值；停止与区块完成仍分开。
验证：28项局部测试通过（artifacts/tmp_tests/loop_action_history_20260922/final.log）；陌生读者指出的同动作结果更新遗漏已补齐并复核通过。真实Android Clock 0186保存请求重组后，Luna保存帧测试明确不再把三行Cancel记录推断为三次点击，回复schema通过；未发送GUI动作。证据records/266_loop_action_disclosure_20260922。运行中冻结源码保持原样。


## 2026-09-22 桌面与安卓共用环境只读规则
环境只读规则从桌面执行提示移至 `遍历prompt/平台/遍历环境只读.prompt`，由共享 `RecoveryRun.call` 在保存与发送请求前加入；桌面同样通过该入口。发现、任务提出、动作、更新、恢复和纠错均收到规则。系统显示/输入等支撑遍历的配置仅观察；文档缩放、绘图尺寸等业务内容参数仍可验证。已有修改任务通过 none + skip_task 暂挂，不改写历史为未执行；这是提示约束，不是执行器硬拦截。
实际旧故障：Android Settings 0164 调节亮度，后续观察46%，原先83%；已暂停并保留0165更新，不猜测原始系统值、不伪造恢复。原因是安卓未收到只在桌面添加的环境限制。运行中的冻结源码未热改。
验证：43项聚焦测试通过（test_stepwise_environment_scope、test_stepwise_desktop、test_recovery_discovery、test_stepwise_frame_context、test_unified_stepwise_recovery）；补齐旧恢复测试回复缺失的必填 skip_task。记录在 artifacts/tmp_tests/shared_environment_scope_20260922/final_result.txt。陌生读者复核通过；Luna独立读取0163/0164原截图和加入规则后的请求，分别输出record及none/skip_task，两份schema通过。证据 records/268_shared_environment_scope_20260922。保存帧测试未执行GUI，尚非新规则实机遵守证明。

实机续跑补充：records/269_settings_scope_resume_20260922 从暂停的Settings原图续跑，旧manifest备份，新冻结源仅更新本次规则；其他三路未热改。0166–0170实际发送请求含共享规则；0168自主修复功能约束引用。0169尝试点击Display size and text，0170仅确认亮度浮层消失、仍在Display，不能说已到达目标页。当前证明接线和续跑正常，尚未遇到新修改任务验证实机跳过。旧亮度修改事实完整保留。

后续实机反例：0173按规则跳过Display size滑块，但0174仍点击开启系统Bold text，0175观察到系统文字加粗。已再次请求暂停并保留现场（records/269_settings_scope_resume_20260922/bold_text_scope_pause.json、bold_text_after.png）。提示接线正确不等于范围限制可靠；该风险未解决，不能声明环境修改已完全杜绝。

## 2026-09-22 功能约束诊断披露真实歧义
`region_functions.register` 汇总约束引用错误，逐条标明功能、原引用、短名歧义/不存在/来源任务未引用及可核对的完整属性名；明确tasks是任务、constraints是属性，不放松原校验，不自动选候选或修改历史。真实Files0095的“搜索匹配模式”对应两条属性，旧泛化错误使纠错把属性错改成任务名。
验证：新增多错误披露及失败不写入测试；功能登记、诊断和可用相邻纠错测试42通过。另5项shared_step_repair既有fixture失败，用HEAD原region_functions重跑仍为相同5项，基线日志保留于artifacts/tmp_tests/function_constraint_diagnostics_20260922/baseline_adjacent.log；不声称相邻套件全绿。陌生读者通过。原Files请求仅替换真实新诊断后，Luna保存请求重答的schema及真实register均通过，得到4项功能；未操作设备或写入原图。证据records/270_function_constraint_diagnostics_20260922。运行中冻结源未热改，Files尚未部署续跑。


## 2026-09-22 更新步按动作披露任务证据
`history_context.task_goal` 接收当前登记图与运行目录，生成最新参数摘要及按动作排序的历史观察，包含所引动作之间的其他已登记动作和真实执行回执；原始 findings、sources、observations 不改写。观察只省略与同名摘要相同的字段，原观察缺失字段明确保留为未知，来源身份保留；缺失或非唯一动作明确标记，不补造因果。后台控件绑定未确认与执行投递分开解释。
更新提示区分本次动作效果与累计任务完成：先前有效动作及后续观察可满足原目标，但不得将旧成功归因于本次。findings 仅填新增或修正事实；按任务/实际动作选择参数滚动、单步入口、输入确认示例。发现和更新身份字段示例以及补查理由说明同步对齐；未改变校验标准或完成器。
验证：45项聚焦测试通过（artifacts/tmp_tests/update_history_20260922/review_green.log）。两位读者分别复核实现和真实发送格式的保存请求；修复观察缺失字段继承与来源丢失风险，读者对130条观察及来源复原核对一致。保存请求由 DesktopRun.call 在发送前截取，未发 HTTP 或 GUI。Files0305同案文本估算59666→50811 tokens，仍含71条相关/期间动作；不是接口实际计费量，历史近义事实增长问题尚未解决。证据 records/275_update_history_replay_20260922/，运行中冻结源未热改。

Luna保存帧首轮未达预期：仍pending且将原有搜索状态写为开始；原回复保留。随后明确先核对累计链、历史适用对象/条件/时点以及前后状态比较，经陌生读者复核无阻断。最终Luna引用a0040→a0041→a0042真实历史判原任务done，同时保留本次a0112选中结果未知，findings为空；真实schema、route_update和settle_task内存预演通过（luna_response_final_validation.json）。最终提示相关13项测试通过（final_prompt.log），完整本次聚焦45项结果见final.log。未做HTTP服务调用、实机续跑或原图登记；不代表循环检测及长历史问题已全部解决。

## 2026-09-23 局部无进展、纠错与继续调度
重复动作拦截先进入既有步骤纠错，不直接暂挂。纠错上下文补最近两次真实提案、回执和前后图，逐图标注历史用途；允许纠错在同一可比失败现场提出一次新的定位点，仍需动作后核验。活跃任务循环指纹不再由结果措辞、控件状态描述或功能复核摘要变化重置；参数domain/conditions与登记结构变化仍保留为进展线索，命中交纠错而非宣称任务完成。暂挂后复用原调度，允许转到没有已知图路线的其他已知未完成区块，由正常导航寻找，不补造路线。
input_text保留聚焦核验和全选路径，空字符串执行删除；Android与桌面回执均保留text=""，投递成功不证明界面已清空。前置条件提示要求区分当前入口适用性与待验证属性，允许则正常动作满足并观察，否则保留依赖；不擅删已有内容或提交受限表单。
更新请求同名区块以“历史名—描述”提供临时可区分名称，后台保存同一映射用于previous_regions、previous_name校验及登记；临时名称不改持久身份，不按同名自动合并。恢复不再按总引导页数停止；重复画面触发停滞，预算不足沿原会话续接，已执行动作与未知投递保留保护。仅修复制的实验框架，原图、活动冻结源码不改。活跃任务的结构指纹重复后，还比较保存的实际画面，真实准备操作改变画面不按纯措辞循环处理；恢复停滞仅计有成功投递回执的动作，不计纯观察。
验证：109项聚焦测试通过；名称枚举修改后另27项直接相关测试通过。陌生读者先独立阅读，再单独对照意图；补充可读性审查发现候选约束作用域与动作/任务语义混淆，提示已澄清并复核。6次保存帧Luna API调用，GUI动作0；GIMP纠正提案及Markor下一动作通过离线合同核验。Expense空串工具合同通过不代表额外清空符合原任务结束条件；原pending的自动重核出口仍有缺口。Writer最后一次结构与投递/任务区分通过，但当时无法核对所选历史身份的依据，未予语义验收；仅正文变化不证明不同Region，见后续精确候选修复。当时未部署或续跑，不宣称全部修复。完整原始请求/回复、失败、读者记录及语义复核在artifacts/tmp_tests/traversal_repair_20260923/。


## 2026-09-23 原结束条件结算与同名候选证据
第三步按任务reason中的明确结束条件结算，标题或旧pending不能追加必填提交、完整取值范围等要求；未要求验证的属性保留未知。不新增每轮复核调用，本轮不扩展旧pending的无动作自动重核出口。
视觉匹配的region_ref贯穿候选筛选和临时名称映射，匹配原因仅属于实际命中的记录；已知清单与视觉清单使用同一可读标签。模型无需输出后台ID。同名无ID旧线索只能在唯一身份时恢复匹配归属，歧义时不传播命中证据。
发现与更新共用身份提示：对当前确已识别的旧对象，previous_name引用候选、name填写按稳定职责区分的正式名称；身份、任务和边不改变。发现登记也传递候选映射，原样回填的临时标签不落成正式名称。动态文档内容不用于强拆区块；未见历史对象不为改名冒充当前可见。复用一个身份不会自动合并历史重复；身份不确定沿既有补观察/纠错，不直接发布uncertain。
验证：61项聚焦测试通过（artifacts/tmp_tests/settlement_identity_20260923/final.log），包含同名命中不串证据、记录顺序独立、发现/更新改名保留ID和动作任务、临时标签不落盘。陌生读者先审方案，再核对实际prompt与截图，未发现本轮阻塞。两次真实Luna保存帧调用：Expense原a0104更新判done并保留必填未验证；Writer原a0098判关闭executed、滚动pending，引用精确匹配候选。schema、route_update、materialize_regions与settle_task内存预演通过，GUI=0。真实模型请求/回复保存在records/settlement_identity_20260923。原运行图及冻结运行源码保持只读，未宣称实机续跑通过；有差异度的正式改名已接原登记路径并局部测试，模型样例没有强行给同一编辑区改名。


## 2026-09-23 更新步历史紧凑展示
`history_context.task_goal`继续保留完整相关动作区间、期间其他动作、属性观察、缺失字段与来源身份；每项最新属性增加最后来源动作，未提供时为null。各属性摘要不是当前截图中的同时状态。最近8条连续动作优先展示，其余历史完整放在此前动作段；两段各按时间正序，阅读窗口不代表完整因果或成功保证。
当时更新步使用 `history_context.compact_update_prompt` 排版；该历史实现已于2026-10-05清理。当前 `RecoveryRun.call` 在平台、环境、运行范围及截图说明组装后统一调用 `history_disclosure.project`，按role处理普通与纠错请求，保留完整事实与截图后缀。现行合同见 [地图与上下文](../../design/modules/stepwise/context.md)；以下数字与结论仅对应2026-09-23实验，不是本次清理的验收。
Files保存案例自动生成59666→41844文本token估算（o200k_base，约30%，非接口计费量），71历史动作全部保留；更短的人工关键链样例未部署。33项聚焦与相邻平台测试通过。首轮Luna仍忽略历史且误判搜索状态新出现，未予语义验收；随后调整最近连续链的披露顺序。陌生读者、后续Luna保存帧验证与实际续跑结果见records/compact_update_20260923及验收记录。

本次布局单独对同份内容为52171→41844文本token估算（约20%）；与早期原始请求比较的约30%包含此前历史投影贡献。更新输出顺序与手册对齐：task_result先于action_result，schema字段内容与必填集合不变；本步描述规则明确只作用于action_result。
验证结果：33项聚焦测试通过，陌生读者复核无阻断；3次真实Luna保存帧调用均通过结构核验，但仍忽略累计完成证据并错误归因Searching状态，语义验收未通过，不能宣称历史理解问题解决。已冻结records/compact_update_20260923/source，从Files原检查点单路自动续跑，无数据重置；a0113停止搜索，a0114重新打开日期筛选，0312更新引用a0109→a0111历史并正式登记原任务done，随后继续调度。该实跑进展不抹去保存帧失败；其余应用本轮未启动。原始请求、失败回复、运行版本、读者审查、预算及检查结果保留在records/compact_update_20260923。由于上述语义验收缺口，本轮暂不创建通过验收的Git提交。

## 2026-09-23 任务归属与历史使用订正
普通任务清点区分新增与补充：新目标使用新名称；旧任务沿用名称、控件、动作、类型与处理方式，只补充findings。没有新增task_type或持久字段。普通清点不自动改挂；显式纠错现可改绑无历史依赖的pending任务，有历史则暂挂原记录并补建独立任务。原范围复核例外保留。任务结果校验分别报告缺对象、名称不匹配、缺观察依据，不再统一报missing actual task outcome；名称冲突展示原名及回复名，不自动改绑。
动作上下文优先展示当前任务全部已关联尝试（含其他区块的步骤），随后提供同入口最近记录和已有属性。pending不是再次点击的依据；是否还需操作由任务结束条件与证据判断。无新证据的循环继续复用exploration_loop检测及分支纠错，不增加新循环控制器。
功能属性动态目录按来源任务分组，每项完整引用名及事实保持不变；唯一短名仍兼容，同名多来源需完整引用。配套正反例位于原任务、动作、功能和纠错prompt模块。验证记录见records/task_context_fixes_20260923；保存帧验证不表示已执行GUI或完成全应用验收。

当时审查曾发现none只有回发现分支及record_edit缺少归属修订能力；现由下述“任务归属纠正与累计结果核对”补齐，验证边界见该节。

本轮最终验证：60项聚焦测试通过，8次Luna保存帧调用、0次GUI。纠错名称修正（0004）、功能属性来源及固定清除能力（0007）、动作依据累计历史返回none（0008）在对应样例通过。任务清点（0005）仍沿用六个绑定Recent的旧侧栏任务并误报complete，虽然apply_plan接受但语义未通过。不自动迁移历史归属，不自动结算none，未部署或续跑。证据与陌生读者报告见records/task_context_fixes_20260923；不能推广为全应用通过。

## 2026-09-23 未登记控件反馈复用发现主线
任务清点以partial/uncertain报告未完成时，evidence应说明具体可见对象、位置及登记缺口。commit_plan将原文附带来源区块写入已有correction_context；request_from_run通过已有“待核对问题”交给下一轮发现Luna，使用原截图和局部观察范围。发现按图核对，复用已有控件身份后补登记；反馈不自动生成控件、改绑旧任务或证明完成。无新回复字段、无新增纠错调用。历史清点historical_inventory仍保留原分支，不凭旧图触发当前定位。验证见records/missing_controls_feedback_20260923。
本轮验证：17项聚焦测试通过；gpt-6-luna实际清点返回partial并指出6个未登记入口，原文透传后发现调用在隔离图补3项，受已有8控件上限保留另外3项缺口。3次HTTP中2次成功、1次测试绕过正式输出格式补齐被400拒绝，随后使用正式RecoveryRun.call修正；无GUI，原运行图不改、旧任务归属不改，不宣称全部清点完成。

### 2026-09-23：任务归属纠正与累计结果核对
- 发现/任务清点纠错复用 record_edit：task_control 仅改绑 pending 且无尝试、事实、结论及依赖的任务，目标必须是本轮披露的唯一已登记控件；同步控件 task_refs。suspend_task 保留原归属与历史，暂挂并要求正常任务清点补建独立任务。显式归属暂挂不被入口复用或等价任务完成覆盖。
- 动作回复 request_task_review=true 仅与 none、skip_task=false 共用，请求第三步 task_result_review 核对原结束条件和累计事实。false 的 none 仍交回发现。不新增设备动作或任务类型。
- 累计核对只更新指定任务状态和结果依据，不新增 Attempt、图边或参数事实；done/blocked 释放活动任务供原调度继续。核对失败沿现有纠错、暂挂、恢复流程；不是每轮固定额外调用。
- 验证：39项聚焦离线通过。共享纠错旧测试5项失败，在改动前文件副本同样复现；没有宣称全回归通过。真实 gpt-6-luna 保存帧核对见 records/task_closure_20260923：首次副本缺执行回执返回pending，补齐原回执后返回done且原动作/尝试不变。没有执行GUI或修改源图。纠错保存帧验证另见 records/task_closure_repair_20260923。

### 2026-09-23：续跑时当前区块与旧合并编号冲突
更新步改写历史Region引用时，只映射当前记录已不存在的旧编号；当前实际存在的区块优先，避免其任务被错移至历史合并目标。Settings 的 a0141/0569 隔离回放：改前复现任务 KeyError，改后正确结算到当前 IPv4 区块；没有重放动作。历史编号复用的整体治理不在本次修复内。


## 2026-09-23 停止应用检修：轮内额度与功能整理进展

分支纠错尚未调用而本轮HTTP额度耗尽时，返回既有 repair_pending，保留原请求到下一轮，不登记 correction_blocked、不消耗纠错尝试。功能目录 evidence_digest 的变化同时计入导航及任务进展；仅 function_inventory.source_call/evidence 文本变化、evidence_digest 不变时不算进展。旧循环账本不自动迁移：Writer 本次人工恢复保留原 episode 和账本，以对应不可变快照重算确认旧误判后解除该 pending；没有重放 GUI 动作。

验证：23项聚焦测试通过；Writer真实旧记录重算由循环变为非循环。GIMP Luna 0436成功选择独立分支，Writer Luna0380完成下一个功能整理，均0 GUI；不代表导航成功。证据：records/stopped_apps_repair_20260923 和 artifacts/tmp_tests/stopped_apps_20260923。VLC反复前景核对、Impress旧恢复次数耗尽，以及Android设备暂停/恢复退出仍未修复。

## 2026-09-23 归属复查、结果导向任务与前置条件

发现旧控件拟改归属，或 Luna 明确报告 `region_ownership_review` 时，在登记前保存原提案并转入实地归属复查；不凭一个标签页迁移其他标签内容。公共标签导航与不同标签内容区分别登记。复查每轮沿用共享动作、保存动作及后续截图，只迁移已观察且无冲突的控件、任务、动作及成对引用；旧快照保留，未确认部分留在原区块。最多六次导航后先观察最后结果，再保留缺口交回发现。该分支在复制的逐步遍历器中实现，不改主框架。

任务以可判断的功能结果为目标：终端可调查只读命令输入、提交、输出与提示符恢复，不能仅因输入文字就登记命令执行成功。新增共享 `key_press` 动作使用现有 text 字段表达 ENTER/TAB/ESC/BACKSPACE；与其他动作同样经过执行、观察、登记。它不负责选择键盘焦点。

任务 `prerequisite` 记录条件、准备控件与区块、依据及是否允许。允许且能唯一关联已登记准备控件时，生成普通准备任务并优先路由；不允许或位置未知则保留依赖、暂挂，不臆造操作。准备成功不会自动唤醒消费者；发现/更新的 `dependency_updates` 必须附当前观察到目标控件已解锁的证据。闪退入口不因应用重启或重新定位自动恢复。未知准备位置、未解决归属冲突仍是明确缺口，不算完成。

验证证据：`records/ownership_dependencies_20260923/`。本次使用真实保存帧调用 Luna；没有执行复查点击、终端命令或 Sharing 开关，也没有迁移活动运行图。离线测试与模型结果详见该目录的验证记录及月度变更日志。

### 2026-09-23 同次分区目标复用修复
首次遇到一个目的区块时才核对旧同名区块并建立目标；同次迁移中后续控件复用已确定目标，不再将本次刚创建的区块误判为外部同名冲突。无关同名旧区块仍拒绝合并。真实Settings旧提案的隔离重放将14控件迁入3区块（3/9/2），两个未确认控件保留原区块；原运行图未改。16项聚焦测试通过，未继续GUI遍历。

## 2026-09-23：功能证据的区块归属
功能tasks只引用本区块已登记操作。其他区块的入边结果补充回显依据，不把来源控件名变成本区块任务；例如格式侧栏控制画布，格式能力属于侧栏，画布仅有滚动任务时可undetermined/空functions。
真正存在本区块已观察控件却缺任务依据时，功能登记失败可交回原任务提出步骤，按历史截图和动作补record/必要explore；不自动制造任务或点击。历史补清点不代表当前位置，不改当前活动GUI任务。

2026-10-07候选将探索结算与具体产物登记衔接：参数findings、入口entry_registration、试探action_result；registration_gap保存未回答问题，正常纠错不重做已执行GUI。细节及旧证据边界见design/modules/stepwise/updates.md，尚待原生模型和实际续跑验证。
