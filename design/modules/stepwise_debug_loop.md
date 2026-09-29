# 临时逐步遍历器的监督修复闭环

入口：`experiments/clock_manual_20260919/debug_loop.py <apps.json> <output>`，使用现有 guiwalk-android Python。完整当前说明见 [DEBUG_LOOP](../../experiments/clock_manual_20260919/DEBUG_LOOP.md)。这是复制的研究遍历器外围监督，不接入主 `gui_rewalk` 的 Router，也不修改采集模块。

监督器用两个运行槽公平轮转现有 run，每轮复用 `run_progress_session.py step`，同设备互斥、不抢占现有遍历；候选修复串行。STOP请求在当前步骤收尾后生效，取消STOP并重新运行同入口可恢复用户暂停。预算暂停、服务拒绝和needs_attention不自动视为恢复。

框架错误归档后，每应用每 kind＋stage 累计最多三轮隔离候选：代码/提示修复 → 原版失败与候选通过的行为测试 → 陌生读者独立阅读/意图对照 → 实际Luna保存帧 → 语义复核 → 单轮现场试跑。未结算、repair_pending或同一无进展循环不能推广。候选失败撤回源码选择，保留实际动作与图证据，不倒退图。只对验收应用选择新冻结版本，不热更新其他运行。

HTTP与GUI沿原session_limits跨轮累计；候选Luna HTTP同样入账。Codex开发/审核会话的调用与usage另存，不冒充Luna HTTP数量。截图/设备等待不触发代码修改；原图完成、一个区块完成、暂挂以及应用仍待发现必须分开。

该闭环不保证未知入口穷尽，也不创建缺失VM。两个设备若均长期等待截图，会占满运行槽；需暂停相应等待以腾出槽。实际验证范围见当月日志及 `experiments/clock_manual_20260919/records/debug_loop_20260923`，不得将注入错误测试当成正式图现场修改。

本轮修正：错误额度按每应用的 kind＋stage 累计三次，解释措辞变化不另开额度；旧问题计数恢复时合并保留，不清零。进度摘要加入功能复核有效性，并移入 debug_progress.py，由所选候选动态加载。旧冻结版本无此文件时使用监督器模块、仍读取旧任务实现。停滞验收用候选算法同时计算试跑前后，算法改变本身不算进展。常驻 debug_loop.py/debug_candidate.py 不允许自动候选修改，需外部验收重启。保存帧调用显式定位仓库导入依赖。

系统无响应提示按blocking_popup处理，不登记业务区块/控件或任务依赖；Wait后复发且标题确认是非目标系统组件时，可关闭该组件，动作后新图确认再回发现步，不据此声明永久恢复。此次Markor/Tasks各1次GUI恢复、合计4次实际Luna调用，10项恢复邻接测试通过。历史误登记保留供后续审计，未自动清除。

候选保存帧校验区分视觉请求和历史功能整理：有图请求仍须引用原事件截图；无图请求仅在原快照的功能登记缺口指向同阶段、同区块的真实无图请求，且历史正文完全一致时准入。缺少原请求或把视觉阶段改成空图不能通过。准入后仍须实际Luna、语义复核与现场试跑，不能把无图准入当作修复完成。

没有正常可调度工作时，复制遍历器复用累计核对入口，按现有任务字段筛选“探索循环整支暂挂、该任务尚无尝试、review_required且无异常限制”的待办。每次暂挂只复核一次；重新截图不重开复核。独立短提示只允许pending/blocked，不允许done，保留原暂挂原因及blocker_history；恢复后回正常导航和更新步骤，不预先授权后续修改。模型服务失败或闪退等不因这一分支解除。当前入口 task_result_review.next_deferred / run_task_step.current。

2026-09-23（复制遍历器，来源接线修复验证中）：动作更新从 dispatch.source_call 解开有效动作请求，读取该请求固定的 source.snapshot，核对原观察与来源区块当时的可交互性；当前图仅作为追加父版本，不回滚。固定链缺失不能用当前图替代。动作补观察后按原任务重新组装；投递前发现观察过期，使用已登记的新观察刷新原任务并重新选择动作，不再消耗一次GUI补观察。正在完成独立复核及Luna验证，尚未接入真实Settings运行。
该修复已完成陌生读者复核、15项聚焦验证及1次Luna保存帧检验；原Settings动作a0113通过0368真实登记后重启队列。任务按unexpected_exit规则暂挂，恢复应用不表示该任务完成。相邻旧测试套件仍存在失败，未宣称整套通过。

恢复任务上下文：沿触发attempt检索原任务目的、范围和受阻结果；异常清除时保留Luna实际handoff。await_discovery将事实追加到关联任务result_evidence，同一来源不重复，不直接修改任务状态。发现消费临时交接后，任务下事实仍保留。
恢复后复核复用task_result_review/next_deferred，仅新恢复证据关联且无其他blocker的blocked任务进入一次核对；只能pending/blocked，不能done。同一来源不重置复核标记，崩溃与禁止诊断优先。20项聚焦验证通过；原Audio已于本轮验收后切换source-v2并恢复调度。早期保存帧因未提供允许范围而仍拒绝权限；随后明确配置范围的保存帧选择了Only this time，均不是实机授予或录音成功证据。

运行允许范围：复制遍历器读取运行发起者配置的run_manifest.exploration_scope短文本，统一发送入口披露给模型；缺失时不从应用名、模拟器或任务名推断授权。恢复策略允许已配置范围内必需的最小运行时权限，仍遵守环境与外部操作限制；无关或依据不足的权限拒绝/暂挂。模型提出任务不能扩大范围。Audio保存帧请求已独立审查，实际授予与录音反馈仍待实时新观察验证。

复制遍历器的步骤接收与纠错共用calls下实际发送的完整请求，包括发送入口添加的依赖候选和回复格式；成功、解析失败、服务重试均保存该合同。纠错外层请求不覆盖原业务步骤合同；已披露的前置条件候选在同一请求重试时不重新选取。该接线正在保存帧验收，尚未推广运行源。
上述发送合同接线已24项聚焦验证、独立复核及1次Luna保存帧合同验证，部署Calc。该保存帧回复的历史/当前工作表混淆及区域框过大仍未解决，未登记该测试回复，不代表视觉发现验收通过。

同一固定动作来源修复已复用到Markor冻结源，包括过期请求按原task定向刷新配套。原a0035只补登记，不重做GUI；新保存帧回复0186登记后恢复。对话框旧框多覆盖下方背景的定位质量缺陷另列，不能以来源登记通过宣称整图准确。

普通动作投递前变化复核（已在Audio代表动作验收）：整屏差异先进入原纠错，提供旧选择图与最新投递前图；暂停续跑先替换为本轮新图。仅该变化episode第一次revise、blocked_by=none、同一提案、同一新图、本轮新call且实际窗口未换、无待结算动作，才能消费一次确认；不新增模型字段，不修改无模型回溯same_surface。不能保证检测所有同窗口瞬时弹窗；结果仍须真实动作后图确认。

动态画面确认已17项聚焦检查、独立审查及保存帧验证，Audio0182→a0049真实投递→0183更新通过；确认仅解决无效刷新循环，不代替点击效果结论。动作前截图目前仍可能早于实际投递，及c0020身份混并保留为未解决质量缺口。

功能登记请求将本区块已支持的任务名及属性完整键分别放入回复格式的候选范围；属性必须使用“任务 / 属性”完整名称，避免小时等同名属性绑定歧义。空参数功能仍允许；候选存在不代表可设置，语义与来源任务关联仍由原登记器核对。只有登记全部通过后才把原function_registration缺口移入registration_gap_history，保留来源和resolved_by；其他缺口不变。32项聚焦离线验证、陌生读者审查和1次实际Luna无图历史整理通过，隔离副本登记成功；不代表重新验证历史截图或整图质量。

Clock现场0618已以真实新回复登记functions-0618-dc5bd05b067c，原功能登记缺口归档；新增1HTTP/0GUI已记入manifest与queue，原失败次数和其他缺口保留。队列1排空后恢复Clock，Settings因a0204归属纠正循环单独暂停。此为原图文本登记恢复，不是新GUI导航验收。

2026-09-23 代表性调查结束边界：共享任务结束条件区分有限反馈调查与指定效果验证。对象、真实执行及充分后续观察成立时，代表调查可记录“本次未见明确响应”结束，不证明功能有效/永久无效；明确暂停、保存等效果目标仍需对应结果。缺失/遮挡/身份不明不能机械done，继续尝试必须说明新增证据价值。提出、动作、更新、累计核对复用该提示，未新增状态或次数阈值。设计与生成请求已独立读者审查；tests/test_task_history_frames.py 3 passed。两次实际Luna保存证据核对：时间轴代表调查done，尚未点击的暂停任务pending；隔离commit通过。原图登记及恢复另记；旧before时点与c0020误合并尚未修复。证据records/representative_probe_20260923。

Audio原图0193完成代表调查累计登记，旧0192未投递提案保留为superseded_by_task_review；未修改任何旧截图、旧动作或c0020身份。2HTTP/0GUI均已入账。Audio/Retro队列排空后恢复，具体后续GUI效果尚待新观察。

2026-09-23 更新补观察接线（验证中）：repair_stages.observe读取实际发送schema，不用调用前旧schema拒绝发送端合法增加的字段，也不替换原update合同。update的补观察改为step_observation单字段evidence，给原动作后图、稍后补图、具体纠错疑问及原region_names范围内相关owner记录，不沿working_region重新清点或登记。候选名称仅检索，保留跨owner同名歧义；没有迁移权限或新动作。其他阶段保持既有发现。6项聚焦测试及根/冻结源码语法检查通过；生成请求独立审查和实际Luna验证尚在进行，未部署Settings原运行。失败的冻结补丁构建保留source，修正构建source-v2未覆盖它。

补观察保存证据验证结果：source-v4固定使用attempt原before/after及已存补图，相关5个owner展示完整简短控件名。读者复核与Luna能找到旧Cancel候选。完整纠错旧episode.schema缺required controls_complete导致2次HTTP400；恢复真实calls/1039/request.json后服务通过。累计5HTTP/0GUI（另一次相对路径本地读取失败未发HTTP），已入manifest/queue。隔离完整登记仍被跨owner Cancel绑定拒绝，原图/原动作未改，Settings仍暂停；Advanced潜在重复与a0204源owner也未解决。不得称现场恢复或整图通过。证据records/supplement_contract_20260923。

2026-09-23 Terminal累计核对：动作步可在真实尝试后暂无有效新方法时申请累计核对，其理由标为待核实判断交第三步；pending须说明新增证据方法，blocked保留已知事实与缺口。不可见工作区块未完成但已无可运行任务时，沿现有advance_unfinished调度其他区块；完成区块的功能提取保护不变。20项提示邻接检查与31项调度邻接检查、陌生读者和实际保存帧Luna已验证；首次核对仍pending，修订后blocked，隔离提交保留16次尝试并转r0002提出任务。尚未现场恢复，不能称新GUI成功。

Terminal部署补记：保存帧3次实际HTTP/0GUI已全数记入原manifest及queue。0574/0575/0576保留各轮原请求回复，提交0576后旧任务blocked、16次尝试与findings保留；原调度切换r0002，Files/Terminal队列已恢复（监督PID3442753）。现场后续行为仍需新观察验证，不表示图完成。

2026-09-23 Clock动态投递检查移植（验证中）：Clock冻结源仍未接上此前Audio验收的双图确认，星空背景导致a0157–a0162无投递重试。本候选保留Clock原dispatch_surface_unchanged快速检查，接入原有本轮/新图/新调用/同窗口一次确认；原单图回复不追认为授权，恢复须新图再审。保存帧实际Luna及accept/confirmed通过，0GUI；现场恢复另记。冻结双图7项通过；10项发送合同/来源观察邻接在原源与候选均失败，表明旧冻结源未包含这些后续接线，不能声称全版本合同通过。

Clock部署及现场补记：保存帧0601的1HTTP已记账，原a0162无投递episode只补双图证据、保留次数/历史；队列5 PID3816253恢复Clock，Android Settings不动。现场0602重新取图确认，a0163真实点击已打开Stop after选项，未选择新值；本次确认非永久绕过。后续更新登记另看原运行commit，不能把该局部推进称整图完成。

Clock最终局部确认：0603已提交a0163更新，查看停止计时选项任务done，记录六项值域及30分钟当前值，未选择其他值或宣称保存；原拒绝历史保留，后续遍历继续。

Android Settings同类移植：原a0140选择返回时，中央手势演示变化导致same_surface拒绝，未投递。冻结source_observation_v2复用既有双图一次确认，不改原快速比较及键盘动作；独立读者与实际Luna保存帧、完整accept/confirmed通过，1HTTP/0GUI。候选13项通过，原冻结与候选同有4项sent_step_contract失败（尚未移植的已有能力），不声称全套通过。正式恢复及真实后图另记，证据records/settings_dispatch_review_20260923。
Settings现场补记：原监督排空后记账0460并恢复；新现场0461确认、a0141实际点击返回Gestures，0462更新已提交，之后进入下一动作。未修改导航模式，不将返回成功等同目标区块完成；保留原未投递历史与其他缺口。

累计任务原图：已有一次已提交、回执成功且精确绑定同控件的操作，即可附原before/after；两次以上沿原三图策略，仍不将未绑定、失败或未提交动作当确切身份。分支纠错复用history_context.task_goal披露精确任务累计尝试及原目标，避免近几轮只有wait便声称从未点击；此步不结算任务、不增加恢复权限。Tasks冻结候选及原图累计核对正在验证，未据此认定位置保存成功。
Tasks保存帧验收：累计Luna按有限直接反馈done、保留提交/保存未知，原6次尝试及另2项pending不改；分支Luna已不再声称未点击。后者提出Open map的导航/外跳未经验证，旧时点回复仅回归不提交。a0057前后都无加载图标，“较晚图已不见”不等于等待造成消失。两调用0272/0273均入账2HTTP/0GUI，正式只提交0272；队列7监督4007480已恢复Tasks，新现场效果另记。
Tasks现场后续：0274重新发现触发旧区块归属复查，0275给出确认行/已有地点内容的拆分；登记阶段报partition name collides with existing Region，尚未完成该拆分或新增GUI，已由监督器进入独立ownership_review纠错。累计调查结算成功不表示此后遍历无阻塞。

2026-09-23 旧入口暂挂的后续证据核对：保留entry_evidence自动结算门槛，不用不完整before清单的差集推定新目的。原累计核对新增无blocker/deferral的blocked探索型单步任务准入，仅当同控件同操作另有已投递、无异常、非返回历史；Luna核对原前后图和结束条件。旧判断与各次独立历史分开披露，不把相隔多轮的尝试拼成连续因果链。结算保留旧失败history；仍blocked沿原explicit_result_review止重。34项聚焦检查及真实保存帧0642、隔离提交通过，原其他任务/动作不变；1HTTP/0GUI已记账。尚未移植桌面Clock冻结源、未提交现场图或恢复该路。证据records/clock_entry_reuse_20260923。
Clock冻结部署补记：原function_keys源定点移植累计核对及原图/历史投影依赖，补齐自动next_deferred请求的task_result_review分发，避免误读action_ready。候选冻结34项通过，真实分发语句段原版复现KeyError、候选一次核对后0GUI返回；冻结请求逐字段等同已验证0642。部署经陌生读者复审，在设备锁内确认监督/worker已退出、无pending且指针未变后提交0642、保留旧失败与计数，仅Clock恢复（监督4161265），Settings不动。现场0643已发起r0004功能整理，尚无新GUI成功或全图验收声明。
Clock现场结局：0643功能整理已正式提交，blocked由2降为1；随后返回region_complete，仍有Timer小时调节器任务及历史登记缺口，queue1监督退出并needs_attention。没有发生新GUI动作，不是完整图。此次历史入口缺口已结算，但其他缺口恢复仍待后续修复。

## 当前任务跨区导航中的暂挂（2026-09-23）

动作尚未执行、无待结算动作、观察一致且前景无异常时，action纠错可暂挂已明确选中的任务。原task_region若不在当前interactive_regions，只有active_task与原任务精确一致、原请求source.region仍在当前可交互区块时才允许；不必为暂挂重新打开已关闭菜单。其他阶段原条件不变。暂挂保留尝试、findings与未知效果，沿task_deferral.choose选择其他独立待办，不自动完成或清除旧失败。

入口task_deferral.defer及纠错/步骤纠正.prompt。Writer保存帧Luna0871和隔离Runner.stop验证通过，切换r0089，1HTTP/0GUI；真实恢复结果另记，不能宣称数字选项用途已验证。

Writer0871已正式暂挂，原Runner.stop选择r0089、清除原pending；监督260728恢复Writer及原VLC，旧次数不重置。现场结果另记，不表示全图完成。

Writer现场补记：0872→a0208→0873已真实输入Test text，后图可见文字，原更新已提交直接输入反馈任务done，明确未验证保存。随后调用继续增加；此处只确认已离开原数字菜单重复操作，不代表全图完成。

## Chrome 基础能力范围（2026-09-24）

新增运行配置 `experiments/clock_manual_20260919/scopes/chrome_basic.txt`，由启动记录写入 manifest.exploration_scope，经原共同发送入口传入各阶段。以代表性基本能力为边界，网页是测试材料，不展开网站业务、无限实例或高级配置；范围外任务仍用 record/skip_task，不伪称成功。非固定深度截断，也不是 Chrome 全功能覆盖声明。该范围目前仅用于新增 Chrome，其他运行不自动改写。

## 通用能力的探索与整理分离（2026-09-24）

任务提出优先判断是否存在有具体线索、对后续指令有价值的未知。加粗、字号、新建空白文档、前进后退等用途与基本操作明确的通用能力默认record，不因无执行历史或未展开选项派探索/解锁任务。附加输入示例与结束条件服从同一判断。record仍保留能力、可见参数与未验证边界；原区块功能/原子能力生成prompt未改，沿原supported_tasks纳入record_only，不把探索减量变成能力过滤。既有pending任务本次不迁移，冻结运行源不自动更换。

## 2026-09-24 无可执行工作与版本验收

局部任务结束后先调用既有全局调度选择其他可执行区块（无已知路径仍交普通导航）；然后检查可复核暂挂任务。两者都没有且无待结算动作/纠错请求时返回 `scope_idle`。Supervisor 保留覆盖缺口并停止自动修代码；只有图覆盖条件也满足才标 complete。服务、设备、用户暂停、预算错误优先按各自原因处理，不能被 scope_idle 掩盖。完成区块无支持任务也可进入角色/功能整理，导航区允许空功能，但不凭空算功能提取已完成。

本次修改仅在复制框架进行。根源码、保存帧模型验证和实际执行版本分别留存；未通过小规模验证前不向全部应用推广。证据：`experiments/clock_manual_20260919/records/traversal_group_20260924`。

## 2026-09-24 用关系知识决定探索价值

第一步的任务清点仍由region_tasks.plan_request生成；历史帧沿historical_inventory.region_request，不能冒充当前前景清点。独立的任务/参数关系调查.prompt允许用当前界面、领域知识及已有结果判断单选、多选、独立参数和条件联动。已足以指导使用时record；有具体且有价值、需要操作才能回答的未知才explore。无点击历史、旧交接“未确认直接结果”、未测全部组合或边界，不自动成为新探索目标。旧任务不因此伪造done或改写历史。

推断写reason；findings只写界面观察、明确的界面声明或实际历史支持的事实，注明来源与条件，不凭知识补齐未见值、完整范围或保存结果。第三步任务/任务结果核对.prompt按实际前后观察修正推断；一次针对性观察回答原问题后不追加全部选项或两两组合，指定执行目标仍须对应证据。区块探索任务.prompt只增加这一规则的入口说明，第二步、schema、状态和调度均不改。

保存帧原生验收及残留边界见本月日志和artifacts/relation_planning_native_20260924_01。没有恢复正式遍历、执行新GUI或部署旧冻结运行；不能把少量减测案例推为所有有价值关系都会被识别。

## 桌面取图与应用生命周期（2026-09-24）

有desktop.container时，DesktopRun.screenshot及维护入口browser_hub.py直接使用desktop_capture.display_capture读取虚拟机显示，不访问guest /screenshot；取图失败保持原等待/暂停或网页stale提示，不回退到已知泄漏的接口。无容器的桌面transport保留原HTTP路径。browser_hub从旧records启动脚本提升为维护源，应用映射由启动配置注入，旧运行快照不改。

DesktopRun.restart_commands沿用关闭目标/启动目标的两条命令；独立desktop_lifecycle.py使用systemd-run --user的transient service启动，传递桌面环境，检查ActiveState/MainPID并保存启动日志。start_new_session不足以隔离systemd cgroup清理，因此不再使用该方式。当前验证平台为OSWorld Linux，需可用的user服务管理器；失败明确返回，不静默降级到旧启动方式。恢复工具预算及图账本保持原路径。

起因：guest截图接口每次创建Xcursor并XOpenDisplay而不关闭，网页轮询耗尽X连接；osworld.service失败重启时KillMode=control-group连带终止Clocks。此次修复不热改guest依赖库、不重置应用数据、不改变遍历prompt/身份或任务语义。验证记录见records/clock_capture_fix_20260924_01。

## 本轮探索汇总（2026-09-24）

run_progress_session持久start_call/end_call边界，不将此前累计混入本次续跑。recover_external.call在现有额度计数后记录calls/<id>/exploration_context.json，独立exploration_summary保存当时的区块/控件/任务归属；更新优先用execution_pending对应binding，恢复可回溯最近已登记动作的binding；实际控件区块与任务所属区块分开，不能把跨区控件拼到任务区块。每次调用侧记所属session，进程意外退出时按该证据补全，排除其他session调用。监视元数据失败不影响业务调用，缺失时明确未关联，不猜控件。网页progress.json按最新session展示阶段分类与总数，其他包括任务/功能整理及纠错，保证分类之和等于调用总数。

网页“本轮已处理”不是完成证明，另列任务账本状态；运行时最新调用组为“正在处理”。动作决策次数不等于GUI执行次数，失败和等待中请求也计入。无边界的旧session不冒充本轮统计。该功能不增加模型调用、不向prompt写预算、不改身份/任务调度。


2026-09-24 状态显示修复：暂挂后的下一目标可只有区块/阶段，没有具体task。progress_details把next_task投影为null，网页仅显示区块名；不把合法的区块级调度变成/progress.json的503。只改展示，不改任务调度或运行状态。24项聚焦测试通过；网页实测另见本月日志。

## 2026-09-25 常识任务与准备结算（复制遍历器）

任务清点先判断未知内容/具体问题；共享结束条件不能反向授权常识验证。准备只做到目标操作之前的可观察条件，不包含原任务。task_prerequisites 集中处理：新增准备使用 single_action，旧 prepares 不受参数事实门槛；普通 parameter 仍须真实 findings。真实 observation_update 也追加 dependency_updates。当前目标控件已在本次观察确认且 ready=true 时，成对准备按 observed_prerequisite 结束，保留历史/阻塞依据；父任务仅恢复 pending，不虚构执行或参数。跨对象、异常和范围保护保留。

30项聚焦测试通过；真实Clock记录的原生任务清点两案及动作更新一案，各1HTTP/0GUI正常登记，确认常规播放/暂停不新增验证、旧准备能按观察结算。累计核对原报错场景亦1HTTP/0GUI正常登记done，合计4HTTP/0GUI，完整结论见 records/task_settlement_20260925_01/REPORT.md。以上为隔离保存帧，原运行未部署/未续跑。

## 2026-09-29 失败补观察证据保留

`repair_stages.observe` 在收到可解析回复后，先将原回复、截图、调用来源存入 episode.supplements，再做原格式/身份校验。每项 validation 标明 pending、rejected（含原诊断）或 validated；validated 仅表示该阶段适用的补观察校验通过，不表示身份已登记。拒绝仍抛回原纠错，原请求和一次补观察上限不变；下一次 `step_repair.request` 可看到失败补图及原始回复。action/task_proposal/function_registration 的 observe_registered 分流未改，网络/解析失败不属于此修复。

Clock 原生保存帧验证采用实际运行冻结源码加此单项补丁，完整隔离运行及原任务/历史保留。首次新观察0828因输出上限截断，未覆盖新增分支；随后将历史实际0826回复原样重放，补丁保留身份拒绝，新纠错0829明确核对两张图后仍要求观察，正常Runner保持correction_blocked。合计2新HTTP/0GUI；未修改原图或部署原运行。失败证据传递已验证，遮挡取证、同图补全停滞和输出截断仍未解决，不能宣称导航或连续探索成功。记录见 records/supplement_evidence_20260929_01。
