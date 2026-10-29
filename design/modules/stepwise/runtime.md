# 提示、模型和执行支撑

2026-10-25接入验证中：`output.prepare`直接读取`calls.<role>.template`，在主文件明确槽位填入本次字段/平台合同/格式例；退出旧ordered_action和object_blocks.apply。固定来源保留在fixed_parts以供原步骤纠错。16类已配置，正常动作保存帧预览通过；尚未宣称Luna行为接受或实机部署。详情见接入证据目录。

- [prompts/compose.py](../../../src/regrow/prompts/compose.py)：读取唯一组成配置，选择规则和呈现本步材料。
- [prompts/output.py](../../../src/regrow/prompts/output.py)：平台动作和字段合同、可读输出要求；schema 校验仍在程序中。
- [调用组成.json](../../../src/regrow/prompts/流程/调用组成.json)：提示维护入口；本批正文与字段语义保持。
- runtime/model_transport、model_reply_parse：实际发送、回复读取及调用计数。
- runtime/action_executor、action_commands：当前图核对、一次投递、回执及前后帧；更新失败不重做已投递动作。
- runtime/run_source：新入口与源码散列；tools/debug_loop.freeze 复制完整 regrow 包及资源，独立进程读取自己的冻结源码。

入口为 `python src step ...` / `python src session ...`；桌面批次由 `tools/run_stepwise.py` 接入。旧平铺源码不由新入口自动兼容。历史运行、原图、请求/原答和工作台数据均未清理。

预算由框架保存并执行，不进入 Luna 正文。保存帧测试通过复制原帧供读取，禁止投递新 GUI；实际调用和所有失败计入日志，不以流程完成代替语义检查。

Prompt工作台通过tools/prompt_review_trace.py连接真实调用轨迹、完整请求和可编辑模块。预览/测试复制完整原记录及当前源码，正常builder/Runner/transport处理；未勾选的模块保持当前源码。测试最多3次HTTP含纠错、GUI禁用；历史轨迹与候选结果分开。原件和每次trace_jobs均保留。动作提案不执行，也不假借原后图当新效果。

2026-10-16：顶部改为三个代表案例（识别3调用、准备4调用含纠错、结果3调用）；完整34调用保留在原始记录分组。只收拢展示，调用的完整记录、重建和测试入口不删减。完整prompt默认折叠；模块引用随案例切换刷新。上下文正文的人工编辑仍是讨论稿，不自动替换底层记录或进入测试。

## 工作轨迹（2026-10-16）

每个代表案例在原数据目录 working_traces/<案例>/revisions 保留不可覆盖版本，固定选入的模块正文和按步骤编辑的底层记录。页面显示受影响步骤，模块编辑后提示尚未收录；保存不调用模型。编辑上下文保留原截图来源，并标注为编辑案例测试，不能当成未修改真实记录验收。编辑器的自由历史正文仍是讨论稿；工作轨迹编辑的是records/state，经正常builder重新生成请求，不替换最终user字符串。

批量预览和统一测试使用固定版本及同一冻结源码，逐步复用原trace worker；每步最多3调用含纠错、0GUI。预览不调用模型。失败、新动作选择或登记/运行状态变化使下游待更新；不把旧下游当一致的新轨迹。待更新状态保留在工作轨迹中，再次测试前需修改本步上下文或明确采用新的非动作登记。采用结果仅允许紧接下一步且截图一致（无图总结按记录继续），带上新原答/图片/记录依赖，不顺带收录尚未保存的模块。新动作不执行，不能采用旧后图继续。

UI把内部work_context.reason放进“内部调度与调用来源”，任务与本步单独显示；这不篡改历史system/user，也不声称自动改写了所有运行prompt。测试结果与版本历史保留，未保存的上下文另有浏览器恢复稿。入口为tools/prompt_review_work.py，界面worktrace.js；复用tools/prompt_review_trace.py正常构建/校验/纠错/登记。

2026-10-16：默认显示当前工作版本的完整请求，历史system/user与执行记录收进折叠对照。只选同案例/步骤/版本且源码散列仍匹配的预览；模块有未收录改动、版本/源码不符或未生成预览时展示最新模块稿并标明尚未组装，不拿旧请求冒充当前稿。生成0030正常离线预览验证新“动作执行”正文，0 Luna/GUI。证据在工作区artifacts/tmp_tests/current_draft_view_20261016_01。

当前动作调用以`02_动作选择.json.system_order`显式组装，`output.ordered_action`集中输出与示例；普通动作不再展示第二套任务计划。角色及运行范围由run_context统一位于system开头，动态材料从当前任务开始。单层none的部分答案/恢复条件由action_commands.for_request映射既有登记。源版本与失败范围见2026-10月志：Add选择及历史参数答案complete已有限通过，不能称全阶段已精简或自主探索已实现。

2026-10-17参数输出统一删除domain/type/values/min/max结构；共享说明提供月份输入一个正例，description承载已确认范围。正常输出schema、补充校验和参数关系提示同时修改；conditions随后已并入description；findings.evidence已取消，来源由原登记入口关联。

参数说明与schema共用入口更新为name/description；任务提出、动作结算、结果更新及纠错中引用findings的路径共用这一合同。功能总结parameter_definitions同步使用ref/description。仅此共享产物接入，不表示各阶段完整prompt已整理完。

后续按调用职责检查完整请求（计划，未实施）：先完成动作选择中的操作/complete/none输出与材料组织；再查动作后更新的实际动作、前后观察、结论；再查任务提出的已有知识与未知问题；再查发现识别的历史身份/新对象与用途；最后查区块总结及纠错恢复的必要材料。每段先展示正常组装输入输出，用户审阅后按相同规则改生产/校验/登记/后读；不先改调度或扩展字段。findings.evidence已取消；其他结果类型的证据字段尚未调整。

2026-10-18 Settings现场11调用/2GUI发现任务预设“展开指示符”导致已进入应用列表仍追求展开；返回仅改变左侧导航，更新漏记变化。材料齐全，修订任务提出/共享知识/效果描述三处通用措辞，保持未知界面形式开放、据实际行为作答、对比变化与保留部分。未改调度或原答；保存帧5次调用未解除任务预设，候选三处文字已精确撤销，未部署；全部计入本轮50额度。证据artifacts/runs/desktop_settings_20261018_01。

2026-10-18 待验证候选：未完成入口任务有两次同任务、同控件、同条件的成功投递且后图匹配时，复用task_result_review先复核累计证据；不直接判失败/完成。原始最近动作前后两图无几何输出，已复核pair通过既有latest_update.source.related_attempts避免重复触发；准备、失败、排除和不同条件不触发。已有工作台worker补该角色正常请求分支。8项聚焦通过，真实保存帧及部署仍待验证。证据desktop_settings_20261018_01/fix-review。

2026-10-18 按用户新约定，新探索任务仅control/task_type；统一类型目标在调用组成.json的task_goals，框架生成任务标签，动作/更新/复核读取同一目标。原图旧任务引用、状态、历史保留，准备任务仍按原依赖目标；不沿旧标题预设界面形式。选择已有同类型任务复用原记录；已done/record_only被重新选中时保留知识并记录revisions转pending，blocked不因重新选择解除。入口复核与实时结算共用store_action_entry同步条件，补充识别复用正常登记，双图纠错/重试保图。25项聚焦通过；正常保存帧验证及现场部署待完成。新50次额度仅从修复后正式续跑起算，旧现场及诊断分账。

2026-10-18：input_target历史模板未匹配时复用实际聚焦前后same_surface核验；回退不返回target，不提升身份，输入投递仍为unverified，效果交后图判断。3项聚焦和真实保存帧核验通过，独立审阅通过；实际输入验证待本轮续跑。

2026-10-18新图Settings第03轮：49/50调用、11逻辑动作/21GUI命令，剩1次因下一轮至少需2次而停止，无未登记动作。4任务done/18pending；404398tokens含纠错。a0008真实输入和筛选通过、独立审查通过；输入回退模拟回执2分支通过。整体未通过：按钮/输入框身份混用，different移除引用后后续仍用旧控件，14次身份复核，参数结束仍未收敛。证据根artifacts/runs/desktop_settings_20261018_03及to_astra/settings_fresh50_20261018_03，未追加调用。已有未跟踪src重构不能安全隔离提交，未提交/推送。

2026-10-18对象补登记：新增object_registration角色使用原动作后单图，批量补齐本次对象外观；正常Runner计费/纠错/暂停，不执行GUI。语义双图与外观单图原答分别保留，registration_request/candidate仅为带来源的派生提交。最终14项聚焦通过，12调用保存帧结果及限制见月志。

2026-10-19：compose.render仅合并完全同文的任务头部目标，并省略与顶层问题完全相同的分组题头，输出说明/材料及底层structured context保留。观察交接不重复发送history已披露的同文未确认事项，剩余项标“页面观察”；不改历史选取或任务归属。实际完整请求和最终身份Luna原答已有限保存帧核验，详见月志。


2026-10-19：Schema仅在框架本地保存校验；正常call_model_once维持json_object发送，不把Schema上传接口。输出呈现改为本步字段说明、紧随各概念的局部格式/正反例，以及一份从实际Schema生成并本地校验的完整JSON格式例；退役长类型声明与按标题搬走示例。普通识别/更新退出excluded数组；具体补登记排除仍使用原completion_updates。response_example为格式例生产模块，不生成业务判断。

字段说明显式呈现本步maxItems=0的空数组合同；正常纠错的maxItems错误明确是条目数，避免误读为文字长度。旧区块去向局部例及完整例展示ref/state/evidence。保存帧工作台补观察使用frame_context.primary，双图更新保持原动作后图；没有新执行入口。

2026-10-20：四对象Prompt统一标记格式，prompts/object_blocks.py读取稳定ID/依赖并按Schema能力选择原文；输出路径沿现有/片段-ID约定，工作台可追溯文件。旧语义片段在组成入口退出，少量历史/纠错继承材料仍按来源过滤，不另改写对象规则。验证范围见本月日志。

本批新Settings最终48/100因身份语义拒绝阻塞，原图/额度不重置；保存帧10HTTP/0GUI另账。83项聚焦通过仅证明相应程序合同，不表示整体行为接受，此后用户授权同步未完成研究检查点，行为仍未接受。

## 身份材料披露候选（2026-10-20）

基于 `e22481b` 的本地候选，未原生验收。身份选择、比较及重核由 `prompt_material.identity_needs` 声明需要的冻结对象和当前动作；既有 `history_disclosure.project` 统一调用 `identity_view`，再由 `compose.identity_material` 呈现。原请求、原提案、编号映射和证据留在结构化请求中；默认正文不输出动作/调用/观察编号或图片路径。只迁移这两个身份角色，不表示其他阶段已完成语义披露。

历史按真实动作键合并兼容的重复视图，不按文字相似合并不同尝试；冲突版本、当前动作、失败、适用条件、共享/仅观察限制、历史疑点、其他任务归属均单独保留。单图候选和补充观察保持待核对含义；补充引用只解析其自身区块列表，缺少该调用控件映射时明确限制，不借原请求编号表绑定。

对象规则将 `shared.registration` 与通用输出约定分开，身份判断只依赖控件定义与身份正反例。`object_blocks.enabled_fields` 按现有 schema 的输出路径选块，关闭数组不触发子树；`complete/none/answered` 按直属枚举选择。组合分支按路径并集处理，不是任意 JSON Schema 求解器；也不意味着每个保留块内的文字都按字段逐句裁剪。

验证及交付范围见本月日志“身份材料披露候选”。无新模型、GUI 或远端部署；真实原记录、原图、Luna 原答及正常登记的行为验收仍待补齐。


2026-10-22 进度面板：runtime.progress.snapshot补齐owned_controls导入，coverage直接读取Region对象，保留独立work中的任务清点信息，避免展开为dict后丢失。复用既有progress_window显示区块、任务、动作结果与图；实时试跑使用独立展示源码读取冻结运行记录，不热更新遍历。


2026-10-22 面板操作凭据刷新：控制POST遇到403时，只重新读取同源页面取得当前令牌并重试一次；成功、409、服务器错误与网络异常不自动重发。暂停仍走原session标记，已投递动作先保留结果，非即时取消模型请求。


2026-10-22：Prompt回放工具recorded_source对缺source的历史动作更新，从真实截图唯一attempt及dispatch→selection恢复元数据；不编辑原请求/回复，仍走正常结果builder与Runner。多attempt无法唯一确定时拒绝。保存帧仅观察/登记，不执行GUI。

2026-10-22 上下文可读性候选：沿用 prompt_material.view；结果更新只在展示副本中去除内部来源地址、完全重复的动作对象几何及描述，原始记录和身份引用保留。用途文字不附调度指令，任务提出单独呈现历史探索判断。纠错通过 correction_feedback 将诊断映射为对象名和具体问题，不重复验证历史；step_repair 保留最新失败回复，与当前诊断配对。原始失败材料仍在 episode/calls。验证见月志，不代表长跑验收。

2026-10-22：step_repair.request 在update继承单图registration请求时，复用object_registration.semantic_revision恢复原双图及无几何输出合同，保留控件引用和身份核对结果。补外观仍沿原单图子步骤，不增加新调用类型。真实保存帧验证见月志。

2026-10-22 纠错展示按校验器提供的规则、实际值及字段要求生成说明，不按具体控件名称硬编码。对象名称保留所属部分，例如参数发现或控件，避免同名混淆；未知规则保留原始具体原因，不替换成通用格式错误。原始错误位置仅用于程序定位，正文不展示程序路径。

2026-10-24 动作引用展示：ModelTransport在控件映射prepare后，对action_selection及其普通纠错使用target_observation.action_references，发送时跳过全局display；操作候选沿candidate_rows展示名称及原样target。只有schema允许补知识的控件另列controls[].index，仍沿原decode；纠错复用separate_map保持共同地图单份。display本身、其他阶段、schema及绑定器未改。真实0003完整记录改后1次Luna/0GUI，原答target=r0001/c0001经正常绑定得到c0001、matched，无未关联重观察；非GUI效果验证。

### 2026-10-25 联合功能候选（未整体接受）

功能提示的参数引用改为支持对象已有参数知识，不再要求另交 parameter_definitions；任务提出/结果更新/收尾使用同一 function_updates 引用。真实保存帧联合提出1HTTP、状态补图3HTTP、无动作结算1HTTP，均0GUI；功能增量后读及长跑仍待验证。外部支持为既存提示/实现差异，本批未扩展。空条件展示已实现并经正常请求重建与独立静态复审，实际模型结算使用该候选。详见当月日志。

空条件在说明材料中省略，不再显示“适用条件：空列表”；保留原始记录及纠错原JSON。非空条件仍完整展示，其他空列表不受影响。

知识编辑提示候选（Clock已部署，整体未接受）：按schema中controls/regions的实际子字段选择身份说明；控件index引用单列，region_index关联说明仅在字段开放时加载。regions[].local_knowledge的嵌套例仅指已有区块知识更新，并按本步是否开放function_updates说明联合登记。发现/动作后观察的新对象能力不变。真实Clock停点副本2HTTP/0GUI通过语义复审，含一次补知识纠错；实机停点已开始显式原生重试，尚不据副本成功宣称实机恢复。

空集合展示（已部署，整体验收未完成）：普通说明中空list/dict统一显示“无”，避免把“空列表/空对象”当成对象名称或界面事实。拒绝回复仍以原始JSON呈现，数据/schema不变。真实收尾失败案例保存记录1HTTP/0GUI通过，不代表实机GUI验证。

## 2026-10-25 Prompt按调用目的组织（限定保存帧验证，未部署）

固定字段定义由object_modules.sections唯一归位，各调用选择object_order；动作流程显式提供对象说明槽，退出统一平铺到完整示例前的组装。任务目标与完成判断前置，动作、结算、知识、功能增量分节；按本次职责和真实输出能力选块，不依据未来回复删减材料。任务提出专属功能要求回到该流程，知识更新不再继承首次识别及task_update条件写法；动态材料呈现问题和依据，字段要求由最终schema生成。控件知识的参数映射与功能条目的参数引用列表按所属字段解释；材料保留知识编号、推测来源和条件。

本批保留字段/调度/登记合同。inventory表示给定范围已考虑；参数未知、任务未完成或只读限制不自动成为对象登记缺口。纠错说明针对最新原答的具体对象/字段，底层校验合同不变。同源同条件的重复说明去除，来源或时点不同的事实保留。

验证证据位于工作区artifacts/runs/prompt_organization_implementation_20261025_01：19份历史请求保留原schema/图片并完成组装；旧身份选择请求缺ref，另有仅组装重建，不能计为原生验收；shared_control_review无真实样本。两个聚焦测试通过；一次跨区块材料回归通过，旧“同屏即共享”测试在前置基线也失败，未修改其历史策略。累计9次发送尝试、7条有效Luna原答、2次本地连接失败，0GUI。Bookmarks结算最终复验及IPv4任务提出通过正常构造、原答校验/登记和语义审查；IPv4此前格式失败及误将知识未知送去补识别的失败轮次完整保留。特殊调用仅静态审阅，不声称全阶段行为通过；未执行返回导航或全框架门禁。

工作树原有候选完整保留。任务补丁与未提交基线存在依赖，不能安全单独暂存，故未提交、未推送或部署；本批源码diff与每轮实际冻结源分别保存，不以当前文件替代旧轮证据。

## 2026-10-25 角色/范围与Prompt操作入口

角色正文和环境说明由调用组成的shared_context指定，具体范围来自原运行清单；run_context去除源于旧生产路径的副本，再统一置于system。普通动作scope材料槽、身份范围复制和纠错单独去重路径已退役；真实限制理由、原答及历史事实保留。各业务builder、输出schema和登记职责不变。

正式发送与工作台预览共用model_transport.prepare_request；桌面适配仍负责平台材料，退出提前组装的call覆盖。原工作台提供当前文案/组装JSON候选，使用同一冻结版本预览/测试/写回；写回核对源码和选中文件原文并保存备份。原草稿/案例不覆盖，源路径仍由fixed_parts追溯。保存或写回不等于行为已接受。

本批证据位于工作区artifacts/runs/prompt_role_scope_20261025_01：4项聚焦检查通过；20份组装含一份历史身份重建仅作离线检查。两个真实上下文各1次Luna、0GUI，原答正常登记并独立阅读；Bookmarks为观察性结算，IPv4新增4个pending参数问题，未验证后续只读调查路线。统一准备入口后的完整请求与这两份实际发送的system/user/schema/图相同，未重复付费调用。工作台端到端编辑/预览/写回在隔离源码验证，实际工作树不写入测试文案。未运行全框架门禁或现场遍历。

## 2026-10-25 开发位置

运行源码现位于GUI-ReWalk根目录`src/`，根`tools/`按相对位置读取同一源码。长期工作台的原`serve.py`改为读取根`tools/`，数据目录不变。旧运行仍使用其原冻结源码，未改变任何模型/GUI合同。迁移验证见`design/ROOT_MIGRATION_20261025.md`。

2026-10-25 控件知识描述统一：新knowledge项只要求description，必要页面/模式/限制写入正文，不再输出conditions；constraints仍可选，其他对象conditions不变。带知识项index修订，无index新增，完全相同内容复用。旧知识条件在control_knowledge.items读取时并入描述，历史原件保留；旧参数条件保留在其原参数事实以保持来源关联。两个聚焦检查通过，完整真实保存帧预览完成；实际Luna验证待记录。

本批最终验证：tests/test_control_knowledge_description.py 两项聚焦通过（pytest-v4），陌生审查及修订复审完成。正常历史蓝牙更新保存帧共6HTTP/0GUI；知识原答已不含独立conditions，并以description说明情境，身份复核same。但function_updates.supports持续填写非对象引用，正常登记未完成，整例未接受；失败原答和全部补框/纠错链保留。不修相邻功能引用合同，不部署。原活动src及设计文件为既有迁移未提交状态，不能安全单独暂存本批，未commit/push。证据artifacts/runs/control_knowledge_description_20261025_01，交付to_astra/control_knowledge_description_20261025_01。

## 2026-10-26 字段说明可读性

response_example.guide统一按对象分段、表内使用局部字段名，退出逐层重复路径/类型与至少0项；保留必填、条件必填、枚举、数值约束、可空、对象/对象列表分支及按名称取值的map。output.prepare对纠错继承的生成字段表仅按原Schema重新排版，原业务规则、JSON示例及原请求不改；已完整提供的原合同不在外层proposal再次展开。

16类调用共享此入口，动作仅记录补充字段使用该表，平台动作表不变。复用20份既有结构预览作排版检查（包含历史身份重建，非20份原生行为验收）；原0036另给实际前后文档。两个直接聚焦检查通过。正常Settings原0002记录构造1次Luna保存帧、0GUI，原答正常登记两个入口任务和功能，inventory仍partial、任务pending；未声称清点或遍历完成。最终普通请求system/user/schema/图片与实际发送相同，未重复付费；纠错去重仅静态/单测验证。

证据artifacts/runs/field_guide_readability_20261026_01及artifacts/tmp_tests/field_guide_readability_20261026_01，便携包to_astra/field_guide_readability_20261026_01。本批不补业务定义缺失、不改变字段含义和校验、不部署或续跑原20次额度。此前未把最终提示可读性作为检查重点导致遗漏；已记录并以实际完整提示作审阅对象。修订中发现的数组分支标识和元素约束歧义经独立复审修复。

## 2026-10-28 回复额外字段与条件必填

正常调用（含纠错/恢复）的发送脚本在保存 `response.json` 前，依据实际发送 schema 丢弃明确禁止的额外字段；原 HTTP 回复始终保留，发生过滤时另存 `unfiltered_response.json` 和 `ignored_fields.json`。全部登记、断点续接及后读继续消费统一的 `response.json`，不维护第二条接受链。复用现有 schema 诊断的唯一分支选择；分支不明确时不猜，不删除开放字典键。缺字段、类型、引用及语义校验照常执行，不把过滤当作接受。冻结运行脚本不会自动部署此改动。

任务 continue/defer 的剩余问题、defer 的重试条件沿用既有语义，条件必填写进任务 schema；字段缺失由现有具名校验反馈报告，不加具体应用/字段误填预测。验证范围和剩余限制见本月 reply_tolerance 条目。

2026-10-29 精简输出候选：同步主模板、对象定义与schema，移除重复结果/前景说明和固定空字段；字段表及格式示例仍从本轮schema产生。5项聚焦离线检查通过；保存帧10HTTP（含失败）与100现场HTTP分开计数，另3HTTP仅收尾最后已执行动作。现场47次v1、53次v2；v2仅修补观察后退役构造器接线，实际续接通过。1次范围监督干预及质量限制完整保留。

## 2026-10-29 两树展示接点
`region_graph.project` 增加trees.controls/operations/progress；现有region_graph.html与stepwise_dashboard.html用textContent显示。页面上下文沿environment_context.for_request共用控件树；任务提出复用task_inventory_context的“环境位置”，不重复追加页面材料槽；功能总结以“应用操作树”进入调用组成。全目录会增加user上下文，不宣称压缩：样例动作7286→11746字符。原317调用运行未部署、未续跑。8项聚焦测试及3次原生Luna保存帧有限验证，0GUI；报告与完整样例见 artifacts/runs/forest_views_20261029_01/。

2026-10-29现场验证终点：全新Clock100HTTP/27动作批次，两树从0098已提交快照导出9区块28控件11功能。任务提出重复树接点已撤回，0021正常请求与登记验证；操作树本批没有function_registration消费者，仍是已实现导出/总结入口。25动作登记，a0012和a0027未登记；视觉复核发现a0016源身份错绑、a0024变化方向反写，树会继承记录质量问题。仅接受所测目录投影，不接受全图事实可靠性；详细报告、原答/截图/冻结源见clock_forest_fresh100_20261029_01。

2026-10-29：action_target_review继承原已发送schema，model_transport对此角色跳过control_indexes.prepare及ID文本替换，保持原知识引用范围/必填字段；平台动作合同复用，未建立第二套输出规范。action_executor已有窗口/画面检查先行，再按pre_dispatch图匹配；只有同动作且图像像素相同时复用旧确认，不因same_surface近似就跳过新位置冲突。5项辅助检查、Clock原生保存帧最终2调用纠错/1调用对照，0GUI；投递前钩子仅静态/辅助检查，未实机部署。工作台增加中文标签，核对调用不能独立重放，须从原动作完整上下文开始。


2026-10-29 旧提示清理：删除31份当前源码/配置无引用的旧Prompt片段；17份调用主模板、仍被读取的对象定义、工作台历史稿及运行冻结源保留。仅移除不参与当前组装的文件，不改正文、schema或遍历行为。清单和离线检查见 artifacts/tmp_tests/obsolete_prompts_20261029_01/。
旧片段会退出工作台当前可选维护清单；已有dist/sources、dist/modified原稿仍保留。这不表示历史片段仍能从当前编辑列表直接打开。


2026-10-29 普通纠错原格式重答：原步骤字段/格式及普通验收失败默认沿用实际已发送的完整schema、索引、任务/历史和截图，追加最新原答与具名问题；Luna返回完整原格式回复，不再输出resolution/proposal或做局部合并。发送边界不重建这份已绑定合同，calls.submission按原请求读回。结构错误一次汇总；任务提出的可读取控件名称引用独立检查，依赖未通过字段的语义检查明确待查。原次数上限、停点、暂挂和已执行不重放保持。
保留的专门路径：共享关系、身份比较、操作目标核对、投递前画面变化、缺少定位的补观察、task_owner及历史对象冲突/record_edit仍沿原能力处理，不能宣称已替代全部纠错。record_edit由原事务内检查，不用修改前记录提前拒绝修订。新提示维护在纠错/原格式重答.prompt，旧调用/原步骤纠错.prompt仅用于上述仍需修复决策的路径。
验证：9项当前合同聚焦检查通过；真实Settings0192原答不改，经正常build_attempt_update/Runner重放，0193一次新Luna直接完整重答并登记。Remote Desktop知识归c0084（index82），搜索框c0024保持，任务pending；1HTTP/0GUI，无导航成功声明。独立阅读、意图比较、修订复审及实际结果复审均保存于artifacts/runs/direct_reply_correction_20261029_01/。两项旧测试因初始化仍调用5参数commit_update而不可用，替代为当前记录修订分流/事务顺序聚焦检查；未改旧测试。


## 2026-10-29 统一格式接收与重答
所有角色经ModelTransport.call → runtime/reply_correction.call → _call_once：每次实际HTTP照常独立保存和计费，解析失败/全部schema错误先在统一入口处理，通过后再返回原业务模块。重答保持本次实际已发送schema、角色、完整材料和图片，只用纠错/原格式重答.prompt替换最新失败反馈，不套娃。语义检查仍归原模块。
Runner通过上下文借出既有剩余repairs额度；格式尝试在发送前计入同一计数，无Runner调用每个原请求最多2次格式重答。pending_format_reply.json保存未完成调用的原输入/已准备请求/下一请求和已消耗次数；只接受同一请求续接，不能拿旧图答案回答新请求。正常返回后清除，业务暂挂/切换时归档到失败call再释放。服务失败不当作格式失败。
最终request中的format_original_call指向最初实际业务请求，records.calls.business_request恢复业务身份；原答不改。step_repair不再自行处理解析失败。补观察、恢复和归属复查保存未完成请求，续接使用原图片完成原收尾；跨轮旧图动作不直接执行，重新观察再决策。
已删除重复的纠错/回复解析.prompt、纠错/步骤纠正.prompt、纠错/对象识别资料.prompt及加载/旧片段配置。调用/原步骤纠错.prompt仍只负责需要记录修订、观察等能力选择的业务纠错。
限定验证：14项聚焦检查通过；真实上下文的补观察暂停/续接使用模拟回复，0HTTP/0GUI，仅辅助检查。Settings真实0192原答不改重放，0193经统一入口1次新Luna后正常登记，0GUI；原schema/索引及持久读回保持，知识归Remote Desktop c0084而非搜索框，任务pending。特殊纠错自身的格式重试由离线合同检查覆盖，未逐类实机验证。证据artifacts/runs/unified_format_reply_20261029_01/。

补充：pending属于另一请求时Runner保持阻塞，不采用其他业务的待重答请求。最终15项聚焦通过；这项异请求保护仅离线验证，1HTTP保存帧对应c0d56ea5。


2026-10-30 纠错上下文组织：角色/范围与当前修正任务在前，原任务及业务定义作参考，user依次为问题、补充材料、原任务历史、唯一待修正回复。保留原schema/图片/历史，不做自动裁剪。16项聚焦测试通过；正常框架保存帧1次Luna调用、0GUI，缺失recovery_handoff补齐，其余输出值完全相同并正常登记。证据 artifacts/runs/correction_organization_20261030_01/，交付 to_astra/correction_organization_20261030_01/。未覆盖所有专门纠错的模型行为。


2026-10-30 结构占位：缺失对象/列表通过字段占位.json提供固定结构，按实际schema适配容器形状与允许键；已有值不覆盖，不推断业务值。格式纠错和普通业务纠错复用fill_missing，历史修订及视觉路由未改。task_update原两条真实失败各2轮，现在各1HTTP通过，0GUI，task pending、控件c0084正确；18项聚焦检查通过。最终适配实现生成的system/user/schema/screenshots与实测请求完全相同。不是所有动态字段结构的穷举验收。
验证：`PYTHONPATH=src /data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest tests/test_field_placeholders.py tests/test_correction_organization.py tests/test_direct_reply_correction.py tests/test_unified_reply_format.py -q --basetemp=artifacts/tmp_tests/structured_blanks_20261030_01/pytest-v3`；两例`python artifacts/runs/structured_blanks_20261030_01/run_saved.py task_key_chinese`及task_key_plural。首次测试因未创建basetemp父目录出现8个setup错误，已创建后重跑，不忽略失败。独立审查发现并修正task_update对象/列表差异及旧知识结构误用。证据artifacts/runs/structured_blanks_20261030_01/。
