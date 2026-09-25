# 新遍历流程的重组方向

当前统一设计见 [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md)。本文保留重组过程与验证记录，不再并行维护下一阶段设计。

这次不是让旧ExplorationRuntime逐步兼容新协议。旧框架副本作为可查来源；新遍历流程只继承已证明需要的部分，不默认接上旧Page/State身份、任务池、路由与多层Reviewer。

## 责任边界

- 基础设施：复用模拟器/虚拟机连接、截图、点击/滑动/按键、模型通信、实际预算与请求日志。它们不解释Region身份或决定探索顺序。
- 遍历流程：首次观察→选择→目标/后果核对与一次投递→前后结果及Region增量→暂停；后续从选择继续。阶段驱动器已存在，实时适配器统一接线尚未完成。
- Region工作记录：每个Region含区块信息、控件、出现记录、背景状态提案、从该区块出发的transitions。目标Region的reached_by只记录来源索引，不等于可执行返回边。
- 原始证据：截图、模型请求/原答、动作投递和前后图保持不可改写；工作记录由其物化。提示词按职责独立维护。

当前没有理由原样继承：独立Page/State身份调用、默认多Reviewer串联、先完成全清单才能继续、每步重登旧内容，以及多种并行探索模式。它们若以后确有作用，应从具体缺陷和对照结果重新引入，而不是默认带入。

明确保留：前景按输入职责定义，系统/被接管背景不当当前功能；独立控件归属；真实操作前后证据；未知与失败记录；Region/控件视觉材料；历史相关内容复用；动作前的目标与后果核对。安全范围、实际预算、证据保存不因精简调用而取消。

## 本次已经落地

stepwise_flow.region_records 从真实graph_snapshots/0002物化region_records/0002/r0001.json等三份文件。r0001.transitions包含c0001/a0001→r0003；r0002只有背景状态提案，无transition；r0003.reached_by引用r0001，transitions为空。图与动作语义未经人工暗改，原模型不确定性保留。

这只是新内核中的工作记录视图和已有阶段顺序，并非已完成新运行内核；模型输入构造、跨轮历史、GUI执行和物化尚未统一到一个实机入口。下一次流程接线以实际3份模型请求/原答及1次动作的基线为准，不能无声明改变模型任务或插入调用。返回、Region复用、滚动等行为等待逐步实走后设计，不先重写庞大调度器。

## 2026-09-20 区块历史请求组装

已实现 `stepwise_flow.assemble_region_choice`，`StepwiseFlow.choose_from_graph` 在选择阶段调用它并保存 choose_request，再进入原 choose。独立入口 `render_region_context.py <graph> <observation> <region> <new-output>` 调用同一个组装函数，离线导出固定片段、动态历史、完整请求、原回复schema、进度、来源图和截图；无API/GUI。本次真实图输出在 records/008_region_context_20260920_01。

固定提示复用证据边界、单步动作建议、选择探索入口，新增独立的历史上下文/区块探索披露.prompt。动态内容来自指定观察的直属控件、截止该观察的动作、进入边、动作结果及不确定性原文。初版使用回复引用表；现已按下节修改为后台关联，旧请求快照保留。它读取本试验图合同，不支持旧modular账本；未统一实机适配器。

进度只统计本观察已登记入口：有执行回执、有模型可见变化、有未确认尝试、所提供图无记录。不同状态计数可能重叠；重复动作不重复计算入口。动作记录未提供时无记录数为null，无法确定进度。区块完成始终未评估；功能/目标区块完成未实现，不能据计数宣称全覆盖。清单外、其他观察未可见控件不在当前分母。不会替用户虚构三个菜单项已探索的历史。

验证：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py -q --basetemp artifacts/tmp_tests/region_context_20260920_01/green2`，12 passed。首次测试暴露夹具只增加区块而未声明控件在本次观察可见，修正夹具后通过；保留各轮日志。保存图实际组装得菜单5入口/0有执行回执/5无动作记录。仅离线执行，不是模型效果或实机遍历验收。

## 2026-09-20 发现与动作阶段分离

用户确认动作选择不需要模型返回编号。固定片段按遍历prompt/流程三份清单组织：发现、动作选择、结果核对。首屏和动作选择组装器实际读取对应清单；程序执行不调用模型；结果清单供下一结果步使用，未宣称完整实时适配器已接线。

动作选择删去编号说明/动态引用表及schema中的control_ref、region_ref；名称、位置、理由与后果仍保留。choose_from_graph只向model传stage/system/user/schema/image_refs，内部候选不发送；模型原答不改写，action_binding单独保存来源编号。当前只实现描述精确匹配且位置唯一落入已知框的后台关联；同名重叠、文本和坐标矛盾、文字框外点击均暂停，不猜最近控件。它只是记录关联，不替代动作前最新图核查。图标自由改述与行空白点击仍待实际案例完善，不能宣称通用语义匹配已解决。

验证：tests/test_region_stepwise_context.py、test_region_stepwise_flow.py、test_manual_prompt_assembly.py 聚焦离线测试（结果见本轮verification日志）；同一真实图导出records/010_action_prompt_stages_20260920_01。本轮无新Luna或GUI；旧call0004的Help建议与schema原样保留，未重写为新合同回复。

本轮验证命令：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py tests/test_manual_prompt_assembly.py -q --basetemp artifacts/tmp_tests/action_prompt_stages_20260920_01/final`，23 passed；真实图离线组装成功，task-owned diff检查通过。

保存注意：仓库通用忽略规则排除了新增JSON流程清单；首次提交未包含这三份依赖。已明确按源配置补入后续提交，后续提交前逐一核对新增配置是否被忽略，不能只检查已暂存列表。

## 2026-09-20 控件名称原样输出验证

动作选择任务prompt仅增加有文字入口的target保留原语言和拼写、不翻译改写；无文字时仍描述图标。沿用现有后台关联，没有为通过样例放宽规则。call0005使用新鲜frame_00006，1次Luna medium调用（HTTP200，5.50秒），原样输出Privacy policy，tap(700,650)，bind_action_target唯一关联r0003/c0010。编号没有发送或由模型返回；本轮0GUI，没有验证实际跳转或返回，同名/纯图标泛化未验证。图、旧原答及进度未更改。

验证：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python experiments/clock_manual_20260919/luna_runs/clock_region_20260919_01/calls/0005/verify.py`，schema、原样名称、模型输入输出无ID、后台匹配与源图不变断言全部通过，详情同目录verification.json。只改prompt，复用上轮已通过的匹配实现；未机械重跑未改代码的离线测试。

## 2026-09-20 更新prompt验证（不推进下一动作）

新增独立固定片段 更新/动作后观察与状态更新.prompt 和 输出格式/动作后更新.schema。复用证据边界、前景、区块、控件、裁剪指令；替代候选不拼接动作选择/返回指令，不追加额外流水线阶段。既有03结果清单暂未切换：先验证更新内容，再讨论统一接线，不能将旧结果物化器宣称为已支持新字段。

call0007重放a0002真实前后图、实际回执和动作前graph0002历史；未提供call0006结论或验收答案，未执行新动作。Luna输出external_app、goal_status=unverified、保留溢出菜单、Privacy policy已执行，其余4入口待探、region_completion=incomplete；regions/controls为空，交接摘要无下一步建议。界面范围与工作区块分开；不可见不删除历史，不把外部前景空清单当完成。更新候选使用名称而非持久ID，旧节点匹配仍需后台接线；同名歧义不在本次验收范围。

验证命令：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python experiments/clock_manual_20260919/luna_runs/clock_region_20260919_01/calls/0007/verify.py`。schema、实际动作、4个剩余入口、名称、原始证据不变与外部区块隔离断言通过；人工核对截图/原答支持所述结论且无下一动作建议。新增1模型HTTP（200，10.15秒）、0GUI，累计7调用/2动作。没有重复生成观察或动作边，旧graph0003及call0006原样保留，新答仅保存为更新候选。单个应用外样例通过，不代表同应用更新、返回、同名或完整pipeline验证。当前继续停在更新步。

## 2026-09-20 动作结果异常字段与分支候选

统一设计已改为action_result.exception（none/external_app/uncertain）＋description＋evidence，删除独立current_context和goal_status以及重复status字段。none不代表成功；目标是否显示与未确认内容写描述。03清单切换到当前更新prompt/schema，update_step.build_update_request为维护的组装入口，不再依赖某次call的独立片段列表。旧真实请求不改写。

新增update_step.route_update：schema及一致性检查通过后输出分支候选；external_app→recover_scope，uncertain→review_result，none且目标区块可用→explore，none空清单→review_result；回执未确认→review_execution，不以模型异常覆盖执行事实。无效格式/缺字段不默认none；剩余入口与complete矛盾、外部前景与目标清单矛盾拒绝。候选不会提交运行状态或执行GUI，统一落盘与激活恢复尚未接线。

验证命令：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_stepwise_update_exception.py tests/test_region_stepwise_context.py -q --basetemp artifacts/tmp_tests/update_exception_20260920_01/green`，20 passed；修改行为前新测试因缺少实现失败，日志保留。实模型call0008复用a0002原图/回执和动作前历史，不提供旧回复；1请求HTTP200，13.35秒，0GUI。实际输出external_app、描述保留内容未确认、4入口待探索，route_update生成validated_candidate/recover_scope；verify.py所有断言通过。旧graph与截图不变，没有重复登记观察/动作。本run累计8调用/2动作，仍停在更新候选验证，不声明完整pipeline或恢复已验收。

## 2026-09-20 无模型的更新登记

新增register_update.py：从原图及动作来源/回执接受更新回复，校验名称唯一关联并写每Region一份JSON；actions保存实际效果，controls.action_refs索引尝试，transitions/reached_by记录候选正向关系；不可见保留历史，外部结果无内部目标。新控件/区块可靠框保存真实裁剪；函数/任务无证据不编造。原始图和回复不改。支持新动作直接从binding/dispatch/receipt/更新请求图登记，无需先造图边。

写入knowledge_snapshots/<更新>/regions/*/region.json及runtime_state.json后原子替换knowledge_current.json。相同输入重复提交不增加动作或历史；新回复可重评同一动作，旧版本保留；旧提交重放不回滚当前指针。测试曾发现快照完成而指针写入中断后重试不发布的问题，已用来源父快照检查修复并测试。不加并发/数据库泛化。

验证：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_region_registration.py tests/test_stepwise_update_exception.py tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py -q --basetemp artifacts/tmp_tests/region_registration_20260920_01/final3`，38 passed。真实保存数据登记命令为 `python register_update.py luna_runs/clock_region_20260919_01 graph_snapshots/0003.json 0008 a0002`（cwd为实验目录，使用同一guiwalk-android Python）。records/014_registration_20260920_01/verify.py重读并重复提交验证通过：3区块12控件2动作，原内部边保留，无新内部边，原图哈希与证据路径通过，重复提交字节不变。

本轮0API/0GUI，不机械重跑模型。runtime_state已提交recover_scope且execution_status=not_started；统一实机循环及恢复动作尚未接线。内部联系、新裁剪、歧义/失败拒绝和重复更正仅离线夹具验证，不冒称实机新功能遍历。源码与结果一同交付到to_astra/region_registration_20260920_01。

## 2026-09-20 统一区块知识登记与读取

仅更新实验框架及先前副本stepwise入口，原框架不动。发现和更新使用name/description/observations/controls/functions/actions/transitions/exploration/history同一结构；控件观察追加，去掉proposal与重复尝试索引；动作结果及region_changes同源更新。ID留作后台身份，模型上下文用名称；同名控件按位置关联，纯名称歧义拒绝。历史读当前快照，旧图仅离线导入；不可交互区块不生成点击请求。

修复过程：新测试先复现字段未整理、旧观察被覆盖、缺少当前读取入口；连续新动作测试还发现来源观察依赖旧图，已改为使用当前已提交观察，重评读取动作原来源。环境只有python3/显式guiwalk-android Python，首次裸python命令未运行，后续均用明确路径。旧源/数据不覆盖。

验证：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_region_registration.py tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py tests/test_stepwise_update_exception.py -q --tb=short --basetemp artifacts/tmp_tests/region_knowledge_20260920_01/green4`，46 passed。日志保留所有轮次。副本实际执行records/015_region_knowledge_20260920_01/rebuild_verify.py通过，3区块12控件2动作，37图片引用有效，初次发现2区块7控件，旧证据不变、重复提交不变、最新上下文无ID。0新模型/0GUI；恢复及自动实机循环未接通。

## 2026-09-20 精简持久知识，区分动作与复核

删除Region JSON中的bbox/icon_bbox、顶层history/exploration；裁剪只读当轮原回复框，图片及原始证据保留。动作结果包含一次采用的区块变化，进度按action_refs/actions即时计算，不列持久未探索清单、不判整区完成。修正此前将复核事件展开为探索历史的混淆：0006是结果观察，0007/0008是同一a0002保存图上的prompt复核；当前仍2真实动作，没有外部run知识导入。

复用原副本reidentify.py的_search/_agreement视觉算法为实验image_match.py，后台按名称和控件图匹配所附帧位置，重复图案/缺图不猜。与旧框关联完全切换，未改原gui_rewalk。当前更新prompt/schema取消剩余入口和整区完成字段；旧call按自身冻结schema读取，新prompt本轮未调用模型。

验证：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_region_registration.py tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py tests/test_stepwise_update_exception.py -q --tb=short --basetemp artifacts/tmp_tests/region_slim_20260920_01/green1`，48 passed（先有2项红测复现旧字段和旧坐标依赖）。records/016_region_slim_20260920_01/verify.py实际从副本入口重建通过，3区块/12控件/2动作、37有效图片引用、旧证据及重复登记不变。5个菜单模板在保存菜单图接受，在Chrome图均拒绝；不是实机新截图或新动作。0模型/0GUI，恢复未执行。原stepwise源已归档到source_history/before_region_slim_20260920_01。

## 2026-09-20 外部应用恢复分支

新增单一恢复prompt和recovery.py策略；Luna可back或主动restart_app，连续两次返回后的更新仍external_app则程序自动重启，最多一次，保留数据。recover_external.py串行复用call_once/ADB，先记pending/预算后投递，再调用原更新步，成功或不确定即暂停；已有执行账本阻止盲重跑。恢复使用独立recovery.json，不绑控件、不制造内部边。common commit_update支持该分支，正常区域更新/裁剪仍复用原路径。原框架未改。

验证命令：`/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_stepwise_recovery.py tests/test_region_registration.py tests/test_region_stepwise_context.py tests/test_region_stepwise_flow.py tests/test_stepwise_update_exception.py -q --tb=short --basetemp artifacts/tmp_tests/external_recovery_20260920_01/final`，56 passed。实机从副本recover_external.py启动：call0009选择back，a0003一次返回，call0010观察并登记回Clock主界面；2HTTP/1GUI，episode=recovered，无重启。实机后发现普通上下文未披露恢复落点，新增回归先红后修复，当前reader读取recovery.json最后动作；此最后读取改动仅离线/保存实机结果验证，没有重复执行。执行时源码单独冻存在records/017_external_recovery_20260920_01/executed_source。
