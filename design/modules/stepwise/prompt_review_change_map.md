# 提示审阅：逐项接线图

对应[持续清单](prompt_review_backlog.md)。先调整各部分提示，组合与路由之后再统一设计。本图仅保留已知待接入位置，不授权本轮先改流程；未实现项不是已接受接口。

版本：本文版本由所在 Git 提交固定。代码行号核对的是 2026-10-13 活动工作树：基础提交 b1ed1499f4410d7b5a826b922d46012dc80423e6 加既有未提交候选。下列源码 SHA-256 固定实际字节；文档提交不包含这些未验收候选，也不宣称远端同名源码等于该工作树。后续源码改变时更新本图与证据，不沿用旧行号。

源码路径统一前缀：experiments/clock_manual_20260919/。

| 文件 | 函数与已核对行范围 | 对应项 | 当前依赖及待接入点 |
|---|---|---|---|
| `task_proposer.py` | proposal_schema:7–24；plan_request:54–103 | P09–P16 | 旧inventory/evidence/operations/shared_instances与必填action/conditions；任务提出稿现仅tasks，发现/更新分别承担用途与结果；待统一输入输出。question_type与回答产物/派生执行形式的映射见U07，不把分类改名直接当作实现 |
| `region_tasks.py` | coverage:30–50；apply_plan:53–141；commit_plan:144–192 | P11–P15；U01–U04 | 旧定义、共享、旧更新在同一事务；85行按action/registration_kind派生task_type，覆盖依赖inventory。待改登记/派生/去重/覆盖并保持原归属、失败及完整性 |
| `task_settlement.py` | task_key:10–12；completion_target:90–92；recorded_match:122–145；partition_findings:271–292；store_findings:306–327；missing_product_fields:25–29 | P13–P14；U01/U05 | 任务键/完成目标依赖action；missing_product_fields按registration_kind要求产物；参数校验/合并直接索引domain。P10/U07与P14须同步，不得静默推断 |
| `task_updates.py` | schema:11–27；decide:66–93 | P11/P13/P14 | 共用参数schema和显式回答检查；保留产物、来源及真实阻碍门槛 |
| `task_knowledge.py` | control_knowledge:20–63 | P11–P13；U02/U04 | 既有知识由任务/共享来源读取；发现/更新控件knowledge的登记与后读待接，不伪造本地执行 |
| `region_functions.py` | catalog:58–62；register:244–319 | P11/P13；U02/U05 | 参数目录和总结依赖任务支持与domain；直接事实引用、语义参数合并需先定案 |
| `prompt_rules.py` | parts:60–70 | P01–P03/P19 | task_proposal固定清单已只有三份；复用该入口，不机械再删已经不存在的固定片段 |
| `output_contract.py` | prepare:98–146 | P02/P11–P15/P19 | prepare按输出字段追加任务动作登记/知识/参数片段；新字段接入后需消除旧必填规则，纠错沿同一合同 |
| `step_questions.py` | render:112–204 | P01/P09–P16 | 任务问题与render中仍引用operations/inventory/shared_instances；最终问题、材料、输出必须同版 |
| `traversal_scheduler.py` | handoff_no_action:6–65；select_work:68–143 | P09/P12/P14；U03 | 选择工作与none交接包含旧覆盖及类型启发式；先明确触发，不以新观察/无新增推断功能完成 |
| `shared_controls.py` | propose_instances:120–153 | P12；U04 | 当前共享可由清点提案建立；移出任务输出需指定对象层确认入口并保留独立实例 |
| `shared_tasks.py` | synchronize_tasks:8–104 | P12；U04 | 继承依赖已确认对象关系及代表任务；不复制真实执行，不覆盖独立任务 |
| `task_inventory_context.py` | project:112–176 | P01/P09/P11/P12 | 按关联投影任务、知识和历史；移除重复说明及占位但保留来源、具体缺口和真实限制 |
| `action_proposer.py` | render_work:6–62 | P14；U01 | render_work把任务动作写入source.task_action；任务不预设动作后需同步请求内容与来源绑定 |
| `action_binding.py` | bind_action_target:4–11 | P14；U01 | bind_action_target依任务动作及completion_target区分preparatory_action；不能因删字段把目标操作误归准备 |
| `control_context.py` | migrate_split_task:31–64 | P14；U01 | migrate_split_task在对象拆分迁移时读取完成目标与操作；须保留原任务及实际执行归属 |
| `traversal_scope.py` | record_only:14–20；review_request:23–41；exclude_known_external:44–64 | P16/P21；U08 | 当前按真实external_app结果作record_only并复核旧任务；P16移除常驻类别策略时须与本轮范围一致，不只改提示。 |
| `model_transport.py` | with_run_scope:42–50；with_environment_scope:26–38 | P16/P21；U08 | with_run_scope读取run_manifest.exploration_scope，with_environment_scope加入环境约束；复用原来源把范围清楚交给任务提出，不添加第二份配置。 |
| `prompt_delivery.py` | environment_part:30–36 | P16/P21；U08 | environment_part按角色选择真实环境限制；删范围特例不删除有效的本轮操作约束。 |

## 提示文字的实际生产入口

网页由 artifacts/prompt_review/20261012_01/build_review_data.py 生成。共享术语取 dist/drafts/术语定义-历史权衡稿.prompt.txt；其余取 dist/modified/ 下对应提示。原版取 dist/sources/，不能把原版或历史草稿重新拼回新请求。网页分组不是实际发送顺序。 `?compare=responsibilities` 使用 `dist/previous.js` 固定的上一轮稿作左侧，只显示本轮7份变化；默认入口仍对照最初原文与当前候选。两种视图共用同一修改稿；前态不是已接受基准。本轮任务提出稿只保留新任务；明确用途说明随发现，参数与任务结果在更新部分审阅，准备放动作部分。网页分组只为逐段阅读，不代表运行组合/路由已经修改。

前一轮38份稿件全量审查保存在 prompt_full_readability_20261014_01/audit.json。此前7份候选的前态、差异和复审在 prompt_responsibility_preview_20261014_01/，本轮5份发现片段的精简另存 discovery_mainline_preview_20261014_01/。当前38份均与运行源码不同，差异不代表运行已经切换。
参数公共结构仍由 遍历prompt/输出格式/参数发现.schema 定义；修改时覆盖任务提出与旧任务更新所有引用者。动作执行协议本轮没有删除 action。发现引用/几何分工的已实现候选另见现行身份、执行模块；不能以任务字段讨论稿覆盖它。

## 陌生读者讨论的接入点

对应清单D01–D03，均为待确认提案。D01–D02已在7份网页候选稿展示前后变化；D03既有按需段保持，未修改以下源码或运行prompt。新增行号于2026-10-14在活动工作树核对；文档基于862e8c91220550ede68ee1a66421e91b88af45b2，表中源码含既有未验收候选，不宣称与该提交导出的同名源码一致。本版文档由其所在导出提交固定，后续修改须随提交更新映射。

| 取舍 | 文件、函数和行号（沿用前缀） | 当前行为 → 拟改范围 | 后续验收案例（本轮未执行） |
|---|---|---|---|
| D01 新对象省略空旧引用 | `discovery_delta.py` schema:8–22；`locator.py` schema:11–29、validate_identity:32–35 | 当前必填previous_name；拟仅在明确new且无冲突时规范化为空，不能把任意省略当new；同步发现/更新合同与纠错 | new省略引用仍为新身份；省略identity或冲突引用不能自动接受 |
| D01 旧控件省略未变归属 | `region_candidate_names.py` control_candidates:63–96；`discovery_delta.py` resolve:41–80；`discovery_step.py` commit:123–140；`register_update.py` materialize_regions:417–420 | 当前已有唯一候选label→cid，但仍依赖region_index取owner；拟从唯一旧引用和本轮已确认owner恢复下标，保留显式冲突检查，不把历史owner补成当前前景 | regions重排仍绑定原控件；同名控件不混合；owner未确认、归属冲突、新对象仍留缺口或走原纠错；原答保留 |
| D02 区块角色保留并澄清 | `region_functions.py` review_current:187–188、register:244–266、317；`task_routing.py` destination_work:30–39；知识模块knowledge.md:41、46 | role参与总结有效性、navigation约束及导航排序；参数支持区可functional且functions为空。拟补清语义；role_evidence按需须同时修改目前非空校验，不按functions长度猜角色 | 已知纯参数/展示区不因无functions变undetermined；纯导航不获得目标业务；混合区不丢本地用途 |
| D02 旧区块状态保留，区分变化与转换依据 | `register_update.py` commit_update:222–227、292–302；`task_settlement.py` register_entry:47–65；`region_evidence.py` region_records:144–153 | changed参与候选转换和入口目标检查；不能只删枚举或将所有变化自动等同导航。拟统一提示观察尺度，另核对已有action_result/entry及真实边后读能否承担转换依据，不新增平行结果字段 | 无关计数变化如实保留但不单独确认为导航；原已可见区块切换内容的真实结果不丢；背景/不可见仍分别登记 |
| D03 条件字段保留，按材料提供 | `region_identity.py` extend_schema:29–51；`register_update.py` commit_update:226–227、325；`discovery_step.py` commit:114–116；`traversal_scheduler.py` offer_foreground_navigation:215–226、schedule_local_inspection:233–240；`region_functions.py` register:253–270 | 完整性、指定目标、补清点、交接和参数归纳均有消费者。拟只在相关材料可用时提供判断要求；必要来源、真实失败、未知与清除语义保持。参数已有定义可直接引用需修改stable_fact的强制重写 | 无指定目标不填focus；未核对控件不自动完整；未知用途引发补清点但仅值变化不自动重提任务；已有参数不重复改写且条件/反证保留 |

普通回复、纠错、登记及下一次读取需成套接入；上表不是运行改动已完成的列表，也不将现有入口当成新设计的唯一触发点。

新增源码散列（其余见本图原表）；完整只读快照与核对记录在工作区根`artifacts/tmp_tests/prompt_responsibility_discussion_20261014_01/source-map.json`。

| 文件 | SHA-256 |
|---|---|
| `region_candidate_names.py` | `34e8dd6e83599277f2c4ad5d40019a77fd568dd0397101090fef57ef730be9f9` |
| `discovery_delta.py` | `a4b0970a72fc04bdb0c58d03ca52aecf7f78dfa413474ec0867a39b0dadb59c4` |
| `locator.py` | `a6cbb893119e6e356199960bee4cb2b9444ab2ad89d309c1b094f0428de2b21f` |
| `discovery_step.py` | `d976ec2e0c0def87d84640a9fb1819461ac11f308f8bafee8160e22bb2abe1de` |
| `register_update.py` | `0b6a5a1680a22b61bc63c3dca6a15698eecff751eb3be0f439c2bba5498ee8d9` |
| `task_routing.py` | `17622cbe8eeda502cf25eb92273dc47b412c1956302e8822129d9a34fa0d66da` |
| `region_evidence.py` | `a5a005addf072a2c337cb9611de367422be9aaae593a3857d4f482b2a8922eb0` |
| `region_identity.py` | `5fe110a1304e417d1e852767fe2ed0b02ea70f33aba2f0725da8413eb9911ed2` |

## 发现与识别主线精简（D04）

本轮5份网页候选精简，运行源码与最终请求组合均未修改。入口稿分别表达整前景/指定区块范围；共同登记只在已有共享片段中维护。对应的文件仍是`任务/当前区块重定位.prompt`、`任务/工作区块定位.prompt`、`共享/区块身份复用.prompt`、`共享/当前前景.prompt`、`共享/身份图准入.prompt`，此处指网页副本，不是运行路径已切换。

- `prompt_rules.py` STAGES:10–15、parts:60–70：后续两种发现范围须配共同登记/前景/裁图说明，不能只复制短入口；更新亦使用共享身份片段，接入时检查其与更新字段说明的重复。
- `locator.py` schema:11–29、`discovery_delta.py` schema:8–23：旧引用已有稀疏合同，但新对象仍继承原必填state等字段；须同步可读输出要求、schema与纠错，不能仅删正文。已有新对象裁图/null及质量边界保留。
- `region_evidence.py` control_observation:56–61：state属于有来源的观察；省略不能补旧帧状态。保留旧对象的新用途和实际有用观察，不把“只认身份”误写成禁止补充事实。
- `register_update.py` materialize_regions:389–414：parent_index登记为parent_region，表达区块包含关系；已有关系未变可保留，当前身份/归属缺口仍核验。新层级说明不引入新的父子枚举。

本表复用上表同一源码字节，未产生新代码；文档版本由本次导出提交固定。后续验收应覆盖：旧对象仅引用；新对象无状态问题时不强填启用；同屏新区域/控件；真包含关系与独立相邻区；未知/遮挡；旧对象新确认用途。上述行为验收尚未执行，本轮仅文字、示例、前后展示和静态核对。证据位于工作区根`artifacts/tmp_tests/discovery_mainline_preview_20261014_01/`。

## 接入核对与证据

- 请求：正常构造完整真实记录，核对固定提示、问题模块、实际字段说明及相关历史，纠错不重新带回旧字段。
- 登记：同控件不同问题不因去掉action被误合并；明确知识不强制操作，准备事实不改原归属；保留失败/条件/未解边界。
- 后读：知识与参数进入原目录及总结；{}不虚假完成，身份缺口及暂挂继续可读；共享事实不冒充本实例执行。
- 验收：保存实际原答与全部纠错/失败，检查身份、任务、知识、图像和下一请求；报告正文、调用总数及总成本，保留未调试检查例。只做静态文档检查时不填行为通过。

本清单及接线图持续维护。本轮更新各阶段职责的网页稿与此处待接入记录，Tier 1 静态检查及陌生读者审阅；0 Luna、0 GUI，无运行代码或运行提示变更。详情在工作区根 artifacts/tmp_tests/prompt_integration_ledger_20261013_01/，其中 source-map.json/source/ 固定本图审计源码，prompt-state.json 固定38份文字对照。没有额外ZIP或截图外传。可读性与范围前置前态在 artifacts/tmp_tests/task_proposal_readability_20261013_01/；本轮职责拆分前态、差异及静态审阅在 artifacts/tmp_tests/task_prompt_responsibilities_20261014_01/。控件knowledge替代possible_operation仍需未来同步发现、更新、登记及后读；本轮不新增固定调用顺序。

## 本图代码字节基准

| 文件 | SHA-256 |
|---|---|
| `task_proposer.py` | `32bc42897eee450fcf675fa227115ca506b04cac0e236d30b2c531d32b95104e` |
| `region_tasks.py` | `e32b6d1498da23fd5c244adc7833cb403d63e1cba3f73b0d98fbbef557683e59` |
| `task_settlement.py` | `e3c6a4e7dad0307f44804a055b27684518d3be6ebe20f4a5ef2fa5f591b504b6` |
| `task_updates.py` | `a251568920a935acd0cf6e0349a0988893ebec4b9b2aac3d8a23f052580cb8a7` |
| `task_knowledge.py` | `fa7eaf74f7f07d12abb623f083637d5b3a4ed508b9c3e476994d69baccadb274` |
| `region_functions.py` | `24035c12ebcbc90be0445d435fd3dc0064aaccaab4496e8a7ac9c1d7a9b5d242` |
| `prompt_rules.py` | `4c765ae76d5fc0448cf8c53ce5971fc7a5af95e123f05dcc1b51b056bf3e9930` |
| `output_contract.py` | `ad4823664c72a22e0494c2c746de60518d740460d31333e379ef65036ed5060b` |
| `step_questions.py` | `b8139ea3518f7d3a1cfbe9390d6a62cee771b6f7a8bb003058b9b754bcb5be62` |
| `traversal_scheduler.py` | `8e61765f0c3eb93da764d573e7ee7a2c99615b262da2789eb814956d5f126703` |
| `shared_controls.py` | `cb79e9be765a045b011c8efa151fdfa4221ddabf090f6ab681afc226b872bce8` |
| `shared_tasks.py` | `3639132b94cdbadbbe08543cddf893bd7030187ec2dd0e1c28844e0bee973068` |
| `task_inventory_context.py` | `efbad464e71000ad5bd4a7bddf20a5c7e2f5ec9583a4bffd4775717a77d372ce` |
| `action_proposer.py` | `c70d3985372f973de698cb39c717234f0bd3b0d24cbc8ffda99c7274b8b57389` |
| `action_binding.py` | `4c9337c9c62b2e8d3d003c8639004054063813f6ec4e74898b2c1c1a708152fc` |
| `control_context.py` | `2921e42e817dad2285edf556b9699b10b868330de42377d2de2483cf08760c38` |
| `traversal_scope.py` | `01cf7ed5d2e5354c649d6442223c72d3a221a9f5ee774c57e26992c41ac17a26` |
| `model_transport.py` | `90cbc7626a522b5c9d102e2ffa7276742a0b90cb935bfcb90a6664aa582a6e48` |
| `prompt_delivery.py` | `9e282016fae3c50dbd04fc722838dbf24f9c447cfe1b7d3836107c65640615bb` |

## 本轮字段必要性审查（P25–P28）

本表是候选接口取舍；先审阅文字，组合/路由后续统一。不改变旧证据的实际归属或验收状态。

| 字段组 | 本轮取舍 | 理由及接入边界 |
|---|---|---|
| previous_name、name、identity、region_index、parent_index | 保留 | 模型需根据画面选择身份和归属，框架分配稳定ID；引用不是让模型复述整个账本。 |
| text、state、knowledge | 保留增量 | 本帧状态与可复用用途含义不同；已有任务答案随task_update提交，其他用途随控件记录。 |
| exception | 保留明确none | 是否有阻塞是视觉语义判断，缺字段不能直接当作无异常；不配套生成空理由。 |
| uncertainty、uncertainties、handoff、recovery_handoff、handoff_summary | 有内容才填 | 保留真实未知与未满足条件；清除旧疑问需明确空值，省略不冒充已经解决。 |
| focus_presence、controls_complete、out_of_scope_reason、context_matches | 材料相关时填 | 无指定区块/条件时不返占位；未核对清单不冒充本帧已清点。 |
| bbox、icon_bbox、image_quality、icon_quality、image_quality_reason | 保留必要几何/质量 | 新对象仍须报告裁图或null；非空裁图需质量。只有clear进入有效模板，准入代码本轮不变。常规清晰不再写理由。 |
| reason、evidence、identity_evidence、role_evidence | 保留有用依据，去同义复述 | 说明为何判断、看到什么及尚未确认什么；没有额外信息不反复改写description或已知归属。 |
| list_group | 需要分组才填 | 区分同类数据与不同功能；独立控件不填空分组。 |
| control、question_type、name；conditions按需 | 保留 | 对象、问题类型、问题及适用情境；已去掉预设action和混合知识登记。 |
| action、target、reason、坐标/文本参数 | 保留所选动作所需字段 | 坐标/输入由当前图与平台定义；无关参数不返回null。 |
| task、decision、reason、retry_when | 保留核心判断/恢复条件 | reason承担回答依据、未答内容或实际障碍；retry_when仅暂挂需要。 |
| registration_gap、next_action | 本稿取消 | 具体缺口并入reason；下一步操作由动作阶段选择。不删除历史失败或未验证限制。 |
| knowledge、findings、entry | 按结论选用 | 用途、参数及图中目标引用不同，不能全合成无关联的自由文本；不要求每项都填。 |
| dependency_updates.ready及引用/依据 | 仅给出依赖目标时保留 | 选择准备操作属于动作；确认目标状态属于观察，不用回执成功替代可用性。 |
| region_role、local_knowledge、functions及支持引用 | 保留语义组织 | 区分导航、参数支持与完整业务目的；参数引用/功能支持关系保留。 |
| parameter_definitions | 确需整理时才填 | 已有定义可直接引用；确有临时观察需整理成稳定规则时仍允许补充，不盲删语义整理。 |
| source_region_split字段族 | 保留专用接口、普通情况省略 | 其职责/结构差异仍需语义判断；原动作前材料不可缺。更细的复制字段压缩留组合时核对，不凭字段名盲删。 |
| resolution、proposal、record_edit、reason | 保留 | 完整重答与正式记录修订分开；revise可同时附必要record_edit，未选字段省略。 |
| record_edit.before、from_region、from_control | 本稿交框架 | 来自本轮提供的原记录快照，由框架做版本核验并写审计，不让模型复抄。 |
| blocked_by | 本稿不要求回传旧诊断 | 已知分类由诊断器保留，新障碍写reason；后续路由消费和新障碍分类仍须一起设计，不能只从schema删键。 |
| region/control/task、attempt、field、after/to_* | 保留选择与新值 | 模型需要指定修正对象；唯一对象能否省略引用留统一合同决定。已执行/有事实依赖的对象修订资格由程序核验。 |
| action_result、previous_regions、returns_to_previous | 保留结果；返回判断按材料提供 | 真实变化和旧区块去向需要模型判断，不能从命令成功推断。returns_to_previous仅在有进入前材料时判断，省略不能当作已确认返回。 |
| excluded、unresolved、task_review_reason | 有相应对象或目录时保留 | 解释可见对象为何不登记；回应明确的待补项；仅有相关任务目录时指出尚未覆盖的新问题。不得由未执行或未定位直接推出新任务；具体触发路由仍待统一。 |

输入按发现、任务、动作、更新、总结、恢复、纠错分别选择；逐角色材料清单及38份逐项审查见工作区根 artifacts/tmp_tests/prompt_full_readability_20261014_01/audit.json。本批仅改审阅网页和维护记录；未改runtime builder/schema/路由。当前 step_repair 仍要求before/blocked_by，task_updates仍读取registration_gap/next_action，region_functions仍要求参数定义，接入时必须处理对应消费者。
