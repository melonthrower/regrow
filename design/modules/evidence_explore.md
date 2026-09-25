# 独立证据优先探索内核

入口：`python -m gui_rewalk.run_evidence_explore --app <当前桌面应用> --server-port <控制端口> --goal <范围> --output <新目录> --supervised`。位于`gui_rewalk/src/core/evidence_explore/`，不经过旧ExplorationRuntime、State分类、CanonicalOperation或Task调度。复用现有Luna API transport、桌面控制器和GUI primitive投递；当前只提供桌面接入，不是旧内核的默认替换。

## 最小合同

- protocol.py：一次调用报告当前surface/controls、唯一pending的结果、下一动作，以及可选regions/claims/links。控件及区块使用本轮语义key；不让模型计算数组编号或回填动作编号。图片按时间排列：有两图时before/比较图在前，CURRENT在最后；单图就是当前。纠正回执时仍保留真正原before，同时发送最新错误，不被中间错误帧替换。
- records.py：框架分配f:c/r、a编号；截图/原回复不可变。planned、delivered、observed分别写文件；投递异常记delivery_unknown并停止，不写成动作成功。唯一pending由框架自动绑定回执，changed仅表示模型报告观察到变化；receipt.intent用met/not_met/uncertain独立描述动作意图是否达成，旧数据缺失时保留uncertain，不把changed当成功。
- 点击point以0..1000表示，框架在本帧控件box中唯一匹配owner；surface_kind区分page/dialog/popup/unknown，surface_box只描述当前接管输入层；控件框任何部分越出输入层、落点在前景之外、多个box重叠、disabled/unknown都会拒绝。输入层unknown或缺失时不能click/scroll，仍可观察或Back恢复。框架提供实际图宽高与归一化说明。几何通过不能证明模型没看错按钮，尤其模态背景仍依赖视觉识别，当前实机采用开发者监督。
- Region父引用、控件归属或claim/link引用错误仅隔离对应notes，不丢弃观察/合法回执、不阻塞其他可定位动作。重复语义key的引用不可靠，但唯一落点对应的物理控件仍可操作。历史Region key严格在输入比较帧内解析成全限定ref，不按相似名称自动合并。
- claims区分visible/action/hypothesis，action须有当前已投递动作及changed回执支持，否则降为hypothesis；其文字仍是模型结论，不是独立真值审核。未知控件引用的claim保留raw并从接纳notes隔离。links始终identity_verified=false，尚不构成跨帧共享控件/操作或因果任务图。
- 每帧一调用，不强制第二审核器。动态上下文仅比较帧的区块摘要（不再复制旧控件清单）、最近12动作意图/结果摘要与12条带帧来源的事实，上限24000 UTF-8字节；每回复最多32控件、10区块、6条claim/6条link，未清点部分须保留未知。API输出6500 token；最多16调用/12动作，最后一次调用不再投递动作以预留回执。连续两个本地动作/回执错误停止，不无限格式重答。相邻两次已观察动作均未确认意图达成时，第三次同click/scroll、同方向且距两次落点均不超过25归一化单位的请求被拒绝；可改变目标或Back恢复，不复用跨帧owner编号推断同一控件。

## 产物与边界

records.json及RECORDS.md包含逐帧区块、物理控件、自然语言功能/参数/条件、关系候选与动作回执；原始API响应（脱敏）、每轮原图、raw回复、各阶段动作文件分别保留。状态使用stopped_by_model/action_limit/local_correction_limit等，不宣称全应用complete。CLI拒绝复用输出目录；本版未实现实时resume、复杂任务合成/采集、规范化跨屏身份或自动经验去重。

--repaint-active复用专用桌面实验的active-client重绘准备，解决既有VLC残影问题，不是按应用名修改识别规则。--supervised每次实际动作前等待本运行actions/aN/approved；STOP阻止未投递动作。设备HTTP与模型HTTP分开计数，模型自动重试/升级不允许。现有用户会话保留，不关闭VM。

## 2026-09-11证据

新内核在VLC Simple Preferences完成有限实机记录：实际展开Show media change popup并观察Never/When minimized/Always；首次点击Custom只收起下拉，下一点击才切换，记录Native取消选中及Skin resource file/Choose出现；Cancel退出。有效批v5为5调用/4动作，最终pending为空。操作员另做一次打开首选项准备、两次重开/关闭检查，确认Native和原媒体弹窗值恢复，单独记账。

全开发16HTTP/5个Agent GUI动作（含一次早期无效果导航）/3个操作员GUI动作，预算未超。失败也保留：v2输出近上限未解析且原transport body未保存；v3旧动作编号回填反复失败；v4数组控件编号错位被几何检查拒绝。最终代码去除这些编号责任，并使用语义key和唯一落点。源码及原文在evidence_core_vlc_20260911_v2..v5；基于v5原始证据的derived_final_parser是零调用/零GUI的派生视图，不改原记录。

仍有语义错误：v5 f2把实际展开的下拉说成已收起，且把背景首选项控件当可交互；可见值域记录本身正确。部分父子层级不足，互斥/条件主要是快照和动作描述，未编译成独立约束。滚动固定底栏、Audio分类复用和下游任务执行未验证。不得把一次changed或引用校验当准确率验收。完整报告见artifacts/traversal_goal_20260909/evidence_core_vlc_20260911_v5/REPORT.md。

## 恢复与滚动/分类试验

2026-09-11：新增上述输入层、意图与重复失败边界，并修正反馈及双图时序。VLC实际滚动、Audio、返回Interface、Cancel四动作已执行，记录了内容替换与导航/底栏保留候选。但模型漏掉滚动后新增metadata控件，Cancel已成功却误读旧图为当前并请求重复，a5被监督阻止，仅为planned。最终无pending；尚未无监督稳定。

后续精简历史和调整before→current顺序的保存帧复测正确识别关闭后主窗口、metadata和展开中的popup；旧“仅收起菜单”图被区分为changed/not_met。最新时序/上下文修正仅保存帧验证，未重跑全段GUI，不能据有限开发样例证明总体错误率或把改进全部归因单一因素。合计11HTTP、53614输入/17091输出token、4 Agent GUI+1操作员准备；56测试通过。证据见evidence_scroll_live_20260911/REPORT.md与audit.json。旧探索内核保持不变，无迁移/替换。

## Responses答复阶段与连续路径复验

2026-09-11新增response.py，仅新CLI调用：从完整completed响应中选择唯一phase=final_answer消息；单个无phase消息或仅output_text的旧形状可用。commentary不拼成动作JSON；多份final、只有commentary、多份无phase、incomplete或非单JSON对象均拒绝。原始transport_response保留，选择过程另记response_selection，不改旧explore/agent.py。新CLI设置text.verbosity=low，Prompt要求只在final输出一次JSON，不模拟尚未投递动作。

冻结旧版的首次请求因commentary/commentary/final三份JSON被拼接而失败，不是长度超限；阶段读取修正后的下一请求因10段commentary达到6500输出上限而incomplete。两次均0GUI。随后最终输出约束+低详细度的修复批次6调用/5动作完成Interface滚动→Audio→Video→Interface→Cancel，无待结算或错误动作重试；合计8HTTP/5 Agent GUI+1操作员准备，仍是监督开发正例而非原冻结版本通过。

可见metadata被写进功能描述但该帧缺独立控件；Audio部分禁用/底部控件遗漏；返回Interface时父/子区重复拥有控件，notes被隔离但Cancel仍可执行。规范共享身份和完整覆盖未验。结果见evidence_finalonly_live_20260911/REPORT.md。

用户提出批量像素锚点，已仅读取现有anchors.py做零调用/零GUI可行性检查：人工选Clock导航文字点，15次跨屏匹配10接受且位置正确、5拒绝（主要选中样式变化）；固定布局/分辨率样本，非总体准确率。新框架尚未批量存储或执行锚点，不把参考图像匹配当作前景可交互或动作成功证明。

新内核可选区块全景工具已接入run_region_panorama.py（build/recognize/goto），不自动替换普通逐帧循环。目录、映射、一次识别及无模型定位边界见[evidence_panorama.md](evidence_panorama.md)。已有当前目标可通过持久map+控件key查找，但本版未自动连接状态图路线或批量创建所有区域地图。

## 语义上下文登记与已知路线（2026-09-11）

CONTROL新增context_box，描述包含操作box和可读标签的最小语义单元；几何错误在普通runtime中可按既有纠错界限反馈。显式--known-records/--route-attempts走独立RouteRuntime，以视觉复用确定导航、按需Luna grounding/落点确认；普通未知探索仍采用上文每帧一调用流程。框架保存源ID/图片/关系及纠正来源，不采用首次视觉分组。合同、预算、状态和验证见[evidence_revisit.md](evidence_revisit.md)。

## Codex Luna实机采集旁路试验（2026-09-11）

用户明确授权Luna子代理。它通过临时服务器接口适配器复用EvidenceStore，以原图像素报告，由桥换算坐标、核对前景、投递并保存回执；当前工具列表没有原生computer工具，未改变正式CLI/default。8次真实点击完成Tools→Preferences六分类→Cancel，最终pending为空，6分类关键截图由root核对。跨进程pending别名恢复及反馈字段曾由开发修复，3个被拒观察报告保留，不算GUI动作，不宣称无人干预稳定。

首轮“主要控件”清点明显不足；明确全量任务并逐区复核后，同一Interface图给出32可见控件/8区块、唯一直接归属。原始Close语义框越过前景2px被现有gate拒绝，派生裁边版本入账通过；未修改原文/实机历史。当前值仍部分嵌入label，隐藏内容/值域/条件未探索，非全应用完成。证据artifacts/traversal_goal_20260909/codex_luna_probe_20260911/REPORT.md及live/observed_graph.json。该阶段0私有模型API，Codex自身模型用量未知，不宣称免费或优于API模型。

## API 自主局部观察 harness（2026-09-11，有界保存帧试验）

独立入口 `python -m gui_rewalk.run_observation_harness --image <PNG> --goal <登记范围> --output <新目录> [--max-calls 4] [--one-shot]`，实现位于 `observation_harness.py`。仅用于冻结截图登记，不接实机动作、pending、旧账本或普通探索默认路径。与上文逐帧一调用路径分开。

- 原生 Responses function tools：`inspect_region(view_id,box)` 返回自主选择的局部图；`update_inventory(view_id,patch_json,commit)` 按控件/区块 key upsert，其他指定字段替换，未指定项保留；提交和更新可同次完成。一个 upsert 必须携带该控件/区块的完整字段，不支持删除。
- 所有视图为保留比例的 1000×1000 画布，灰色补边禁止登记。框架保存视图到原图映射并转换 box/context_box；全局 surface 只能由 v0 指定。错误 schema/枚举/几何 patch 原子拒绝；提交另查引用、父环、唯一直接归属及前景包含。检查通过不证明模型语义正确。
- 冻结源图不可变，所有视图都来自此图；无 refresh/stale-view 跨帧机制。receipt 必须 null、action 必须 stop，禁止制造动作证据/旧帧 links。不直接调用真实 EvidenceStore.accept，避免将保存帧冒充新 GUI 观察。
- 每次回传 function_call_output 与原 call_id，新局部图作为工具观察消息送回。显式保留当轮消息和服务端输出（含可回传 reasoning 项），store=false。默认最多4请求、硬范围1..8、每次最多6500输出token；没有隐藏重试/升级。单次对照只暴露 update_inventory。源码配置固定 Luna medium。
- 产物包含原图、view PNG/映射、原始请求/脱敏响应、完整工具历史、每次 mapped patch、当前 draft、submitted/result 和 HTTP usage。提交错误可保留未接纳草稿供后续改正；无成功提交则 result 不能用于登记。预算约束只限此观察回合，尚未接跨帧共享调用预算。

同模型/同图两应用5目标试验：单次定位4/5，harness5/5；Writer居中从误认其他按钮变为正确，主动3次裁图+1次提交；计算器两组均1次。共7次成功模型HTTP，另1次沙箱连接失败无响应，0新GUI。输入/输出token：单次合计5226/1311，harness24860/3367，不能称省成本或总体100%。指标是操作框中心落入人工标注目标，非完整登记/Region语义准确率；无字图标label填写及等号selected状态仍有疑点。37项局部/相邻测试通过，未实机接入或全门禁。原始证据及详细边界：`artifacts/traversal_goal_20260909/api_harness_20260911/REPORT.md`。

### 批量观察降调用及 Codex Luna 对照（2026-09-11）

新增显式 `--batch-inspection`：`inspect_regions` 一次请求1..3个独立局部图，整批先查几何再分配视图；默认调用预算仅在此模式为2（普通模式仍4），每轮明确 remaining_calls，最后一轮只暴露 update_inventory。`--batch-context` 仅搭配前者，额外返回每个请求框宽高扩大一倍、裁至源图范围的邻域，context_for保存对应关系；每批最多6张局部图。批内框只能引用请求前已存在的视图。不改变旧/实机内核、账本或默认模型；均为可选实验，非已验证的质量保持优化。

同3张图12目标，批量API与全新Luna medium子代理均定位11/12，Writer居中误认相同；VLC七目标定位及native/custom/fullscreen/enqueue状态正例，非全页/重识别验收。Writer原串行4请求正确→批量2请求错误，Calculator原1→2请求；邻域扩展及首次固定网格多图也未修好Writer。网格只保留临时探针，未接CLI。不能写成子代理更准或降调用已保持质量。原始答复、人工目标/坐标审核和成本见 `artifacts/traversal_goal_20260909/api_harness_batch_20260911/REPORT.md`；本轮9成功API请求，47071输入/4466输出token，0GUI；两次新子代理内部请求/token未知。41项模块/相邻测试通过，未跑实机/全门禁。

## 2026-09-12 与已知导航共用执行流程

显式 `--explore-after-route` 使用HybridRuntime，已知路线完成后在同一账本和总预算下进入普通探索；启用回执与无效登记分离及监督后的新鲜截图检查。原每帧一调用路径不变，循环按剩余总预算判断，接续时比较图来自已确认末帧。混合模式的区块候选、阶段产物、停止状态及离线/短段实机验证边界见[evidence_revisit.md](evidence_revisit.md)。冻结截图工具harness仍是独立实验，没有借这次接线替换首次观察协议。

## 2026-09-12 设置首轮实跑与自主性边界

settings_traversal_20260912访问Simple Preferences六类，展开媒体提示3项/音频输出8项，滚动Input页补HTTP代理字段；本轮未改框架。首批Preferences框越界重试耗尽，由root选择已知入口续接。Interface/Audio初始8/17项遗漏，root另用已采集截图补成31/23项，Interface无动作stop.point格式做带来源的本地规范化；这些不能计为agent自救。Input滚动使缓存Custom→Normal，root安排取消/重开核对恢复Custom，再退出。复查中的合法回执隔离由新runtime自动完成。总21API/17GUI，99706输入/21837输出token，最终无pending、主窗口、无保存。

此为有人调度/逐动作放行/补登记/恢复核验的监督首轮，不是自主遍历成功。高级设置、未展开值域、条件变化及快捷键未见行仍未覆盖；页内控件计数含公共导航/列表抽象，非全局唯一数或准确率。用户随后要求减少主动干涉：后续自主评估仅给范围和预算，运行中不人工选恢复路径或补清单，失败原样保留。来源和角色拆分见 `artifacts/traversal_goal_20260909/settings_traversal_20260912/REPORT.md`。
