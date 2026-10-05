# regrow：地图冲突、任务复用与连续探索设计草案

状态：拟议，未实现、未进行本设计的Luna/GUI验收。仅交付设计；不把工作树中的地图候选或下列字段写为当前合同。固定反例随已有及后续探索积累，不先建设独立反例库。

## 1. 用已经发生的例子说明目标

2026-10-04的Stopwatch真实保存帧没有顶部添加入口。完整任务提出请求0031中，Luna的evidence明确说“添加入口当前未显示”，却返回inventory=complete。region_tasks.commit_plan只在inventory非complete时交回发现，所以错误当前地图保持。
同一原答还新增“观察创建世界时钟后的条目交互结构”；相关目的区块已有“观察添加世界时钟后的条目交互结构”，仍blocked。新任务prerequisite=null，未继承原条件。本次只是人工触发任务复核，天然下一步原为action_selection；不能声称已有自动发现或纠错能力。原报告、请求、回复与真实截图位于task_proposal_visibility_20261004_01审阅包。

目标过程：Luna明确提交当前记录冲突 → 正常登记只保存核对义务，先不接纳这批任务增量 → 单当前图的局部发现核对 → 发布当前观察，保留历史身份和任务 → 刷新任务请求 → 复用旧目标或提出确有新问题的增量 → 正常调度下一项可继续工作。不是从自由文本搜索“未显示”来猜状态，也不是Luna说不在就删除历史控件。

## 2. 最小输出与输入变更（字段名为本草案拟定）

- 任务提案顶层增加control_issues数组：每项只含本轮已给出的control名称及evidence，空数组表示无明确记录冲突。框架用请求绑定的区块、观察和名字映射定位，不让模型填写快照/坐标/预算。它表达待核对意见，不直接宣告控件不存在。inventory仍只表达任务清点是否列齐，两者不能互相代替。
- 顶层增加reuse_tasks字符串数组，只选本轮披露的“区块 / 任务”引用。它只留本次复用审计，不进入operations、不创建当前区块的别名、不参与本区块equivalent_to，不改原owner/status/attempts/前置或暂挂。operations仍为本区块任务增量，只加new_question字符串：新目标有相关旧目标时说明原目标不覆盖的独立问题，否则填空；reason保持依据与最小结束条件。两种输出分开，避免旧任务引用被旧行写入逻辑误当新任务。
- 请求只给当前区块已有任务，以及由已观察入口/来源关系关联的目的区块任务，含状态、目标、条件和结束依据；不铺全图任务。引用通过本次请求中的映射绑定真实owner/name，不根据同名字符串跨区猜测。
- 同控件/动作只是候选比较范围，不足以证明两个业务目标相同。框架校验引用、当前范围、必要差异说明及状态保留；自然语言目标是否相同仍需Luna结合上下文判断，并用实际案例验证，不承诺机械规则消灭所有语义重复。无独立问题的当前入口可按原record规则登记用途，但不能据此完成或豁免所引用的blocked目标。

示意（不是完整可提交schema，更不是实际Luna回复）：地图疑问为“添加入口：本图没有，当前列表却列了它”；任务复用为“添加世界时钟对话框 / 观察添加世界时钟后的条目交互结构”。本案例首轮有地图疑问时，任务增量暂不登记，核对后重建请求让Luna重新判断。

## 3. 模块改动及写入边界

| 职责 | 拟修改入口 | 要形成的合同 |
|---|---|---|
| 任务输入与提案 | region_tasks.proposal_schema / plan_request / apply_plan / commit_plan；registration_diagnostics.collect | 披露相关旧任务、绑定引用；issues的安全校验先于普通任务语义诊断，义务优先保存且不受complete豁免；无冲突才校验/登记任务增量。旧任务不因遗漏而丢失。 |
| 局部核对交接 | discovery_inventory.supplement及其拟增交接函数；discovery_step.request_from_run / commit | 复用正常发现和publish。将待核对的观察、区块、控件引用、原理由保存在现有快照运行态的control_review中，供中断后恢复；进入局部发现时不新建另一张图。 |
| 核对的明确结果 | discovery_step.schema / commit与局部发现prompt | 仅有control_review时附加受争议控件的present/absent/uncertain结果，引用原待核对清单和当前图；present须有对应当前控件观察，absent只修当前集合，uncertain不变成历史删除或当前可操作。仅漏报不能算核对完成。 |
| 当前地图与模板 | update_visibility、page_context、register_update和identity_templates的现有入口 | 发现与更新用同一当前证据含义；历史/匹配候选不自动成为当前确认。只有已核对同一源图、同一观察的错误裁图才撤销该图的模板资格；当前不在不证明旧清晰图失效。历史身份、任务、回执和原图保持。候选中的当前/历史分离先复用，不能因存在候选就称已验收。 |
| 正常调度与纠错 | run_task_step._run_step内current、task_selection.attach、repair_stages.refresh / accept_candidate、discovery_inventory | 控件/交互表面结构变化或显式冲突使相关任务清点需要一次复核；按结构签名而非每次新截图清点，沿task_inventory.review记录。异常核对优先于动作。重复同帧同范围且无新证据的核对不无限重开，交现有暂停/纠错边界。 |
| 任务完成与下一步 | task_settlement.settle_task、task_routing.advance、任务结果核对提示 | 按原目标与真实回执/后图判断：若目标只是打开并看到菜单，该入口可完成，内部清点归菜单区；原目标要求选值或设置完成时，不能只因弹层出现就完成。既有子区交接优先复用，不重写调度器。 |

自然触发须单独证明：采用“已登记的可交互区块与当前控件集合”组成结构签名，对仍可交互但所处表面发生变化的区块标一次review。首次新结构走原任务清点，不额外双调；已核对相同结构、仅值变化不重新提出任务。这个触发不能检测所有被模型漏报的界面变化，需实际观察验证；不能用测试脚本手动设置review冒充自然触发通过。

核对状态记录原观察/帧、被质疑引用和处理结果；原问题帧发生变化时，旧问题只作历史线索，不能据其覆盖新状态。resolved后清理当前义务、留来源审计，不持续把“待核对”字样填进Luna地图。相同义务未解决且没有新证据时保留未解决状态并暂停；本设计不追加无限自动审阅调用。

### 必须补全的三条接线

1. **先接纳疑问，再判断任务增量。** 在accept_candidate及registration_diagnostics的任务分支共同按同一合同先验证JSON/schema、当前请求来源/观察、issues引用范围及非空依据。有合法issues时只发布control_review，不先做operations的完整覆盖/owner语义检查，不应用operations或reuse_tasks；即使受疑控件无旧任务、operations为空，也能保存义务。无issues时才走原任务诊断和登记。坏引用、旧帧或越界不能借issues绕过校验。新增反例必须覆盖“无旧任务的受疑控件＋complete＋空operations”。
2. **引用不等于改写或完成。** reuse_tasks只引用已存在工作；原pending由原task_selection/task_routing规则按可执行性选择，未保证立即抢占其他任务；原blocked仍由原前置/复核路径解锁。若本区块当前入口尚无本地清点记录，可另用普通operations的record行记录该入口用途，理由指出由哪个旧目标调查；它不是重复explore，不豁免远端目标，其进度仍读取旧目标状态。coverage不把reuse_tasks或这条record算作原目标完成。普通同名补充只追加findings；prerequisite为空或内容等同已有值时原状态保持，试图改变前置/暂挂须拒绝并交回已有前置条件或显式任务修订流程。此前同名提案可补前置的旧测试须按新边界更新，并验证真正的新任务仍能登记其初始前置。不能只加引用字段而保留可绕过条件的旧写入分支。
3. **核对后还有一个持久的“重提原区块任务”义务。** 局部核对在同一次publish中登记结果、将原rid的task_inventory.review设为重新清点、control_review转为awaiting_task_plan；即使present且结构没有变化也要重建一次原rid请求。run_task_step.current在历史清点和新准备调度前，task_selection.attach在导航早退前优先处理这项义务；已执行待登记动作/原Runner仍优先结算，不被新复核打断。原区块仍可交互才提案，否则保留review，正常重新定位/暂挂而不冒用别区。只有新观察上的无issues提案正式发布后才清除义务和review；若单轮返回task_proposal留到下一轮，run_progress_session按现有轮次边界继续，不把它当scope_idle或任务完成。重启也读同一义务，不重放GUI。补“原inventory=complete、核对present且结构不变”以及中断恢复案例。

历史清点若返回非空control_issues，拒绝该提案、保留原答，沿历史纠错要求按历史材料表达；不能进入实时control_review。旧历史发现问题的处理另沿现有记录核对边界，不以本设计偷改当前观察。

## 4. 对应模块文档如何更新

实现前保持现行模块合同不变，本草案单独存在。实现并验证后，在原模块页更新下列段落，不另写平行规范：

| 模块页 | 要更新的内容 |
|---|---|
| tasks.md、01_discovery.md | 输入中的相关任务、增量字段、引用与新目标边界；inventory和地图冲突分开；谁负责正式写入。示例同时保留重复与合法新目标。 |
| context.md、identity.md | 当前观察/历史/匹配的来源规则；局部核对前后图投影；不在当前页不删除历史、不否定旧模板。 |
| repair.md | issues到局部发现、结果登记、刷新原任务请求的闭环；帧变化、中断、重复核对的退出边界；已执行动作不得重发。 |
| routing.md、02_action.md | 哪些结构变化触发一次复核，何时复用旧任务，blocked/prerequisite不因改名解除，如何继续其他可运行任务。 |
| updates.md、03_update.md | 入口任务和子区任务的完成边界；例外为原本的多步设置任务；明确哪些跨步消费者需同步。 |
| CURRENT_FRAMEWORK.md、CODE_MAP.md、tests/STEPWISE_INDEX.md | 仅同步真正变化的共享输出合同/路由/接口和测试去向；月日志记录具体命令与通过、失败、未验证范围。 |

## 5. prompt与字段必须联动核对

任务提出的schema文件、proposal_schema动态扩展、普通plan_request及task_correction包装一起改。同步任务登记/历史入口/前置条件提示、局部发现及补登记提示；检查repair_stages.refresh、record_edit后重建schema和实际发送严格字段。schema新增字段的空值与纠错proposal保持一致，旧原始请求/原答不覆写。
历史清点historical_inventory使用历史截图，不能把control_issues当作实时设备冲突或改变当前图；历史提案仅维持原历史清点/事实复用范围。所有新字段生产者与消费者必须列入变更图。
动作选择与更新不必增加同样字段，但要核对它们读取的新地图、任务引用及原完成条件；发现/动作/普通任务核对仍使用对应唯一当前图，更新保留其正常前后图。model_transport、history_disclosure、page_context须检查最终实际请求，而非只检查固定prompt片段。

## 6. 把探索中已有问题落实为验证

不做先行大反例库。下面是本改动必须保护的行为，优先补到已有测试文件，unit只验证接线；行为验收另走真实run的正常完整请求、原Luna回复与登记链。

| 案例与预期 | 现有测试位置（拟补/扩展，不代表已通过） |
|---|---|
| 受疑控件无旧任务、complete+空operations+issues仍进入核对；坏引用被拒；同批任务/前置不提前写入 | test_stepwise_region_tasks.py、test_discovery_inventory_supplement.py |
| 局部核对absent只撤当前确认，旧ID/任务/清晰历史图保持；uncertain或漏报不能算解决；过期帧不能改新图 | test_current_page_context.py、test_identity_template_admission.py |
| 同目标改名/跨区引用不新建explore且保留blocked/prerequisite；同控件确有新问题仍可新增 | test_stepwise_region_tasks.py、test_ownership_and_prerequisites.py |
| 结构变化自然触发一次复核；核对present且结构不变仍重提原rid；中断恢复/历史清点不抢占；无新证据不循环 | test_sent_step_contract.py、test_stepwise_task_loop_handoff.py |
| 打开菜单入口与菜单内部工作交接；原参数任务仅打开弹层仍pending | test_stepwise_task_loop_handoff.py、test_task_settlement_routing.py |
| 新字段贯通普通/纠错/历史清点；历史请求不能写当前地图；空字段及严格schema一致 | test_stepwise_historical_inventory.py、test_stepwise_transport_new_fields.py |

模型验收分开两条：0031的完整副本可保留原人工review入口，专门验证识别/交接，必须标为人工触发；自然调度从未设置review的原始完整上下文通过正常入口进入，独立证明触发，不能拿前者替代后者。首次回复与纠错后结果分开记录。原0031反映的是已发生失败，不能编辑旧回复当新成功。随后从最近真实停止图的独立副本继续5次真实GUI；保留旧图，不从保存帧候选当现场恢复点。不为凑步数重做提交动作。
检查：实际当前身份和图像、任务数量/owner/条件、下一请求地图、原执行回执与结果；schema或Runner complete不算语义成功。错误登记、重复失败或任务跑偏依用户规则暂停。保存帧与GUI证据分别汇报，合法新任务不得为了零重复被全部禁止。

开放边界：结构签名无法识别未报告的变化；自然语言任务相同与视觉存在性仍可能被Luna判断错误。本设计提供明确交接与可检查的登记边界，不声称已解决所有识别问题。当前仅完成源码阅读和设计静态核对。
