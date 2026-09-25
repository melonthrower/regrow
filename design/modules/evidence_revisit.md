# 新证据内核：语义登记与已知导航复用

仅作用于evidence_explore，旧探索框架不迁移/替换。普通未知探索使用Luna进行首次登记、语义判断及纠正；CLI显式选择已知路线时由RouteRuntime执行确定步骤并按需回退。

## 登记与身份

CONTROL.box为实际操作位置，context_box为包含控件和可读标签/必要标题的最小语义范围，都是0..1000整图坐标。复选框不能只用裸方框代表功能。context_box必须包含box并处于surface_box内；records.accept在分配观察帧前拒绝非法语义几何，普通runtime将错误保存在对应calls目录并按已有两次界限反馈。原始回复不改写。历史无context_box目录仍能读取，但不声称它具有完整语义登记。

框架保留原图、source frame/control refs、Region父子关系及实际动作边；不按名称自动合并身份。route memory/catalog.json复制所需帧和图片；confirmed_N.json及corrections.json保留已确认落点和定位修正来源。修正外观是候选，不代表无条件全局共享身份；完整任意Region规范图仍未完成。

## 视觉定位

reidentify.locate_control在已知前景范围搜索。显式context_box存在时用语义整体定位并映射操作框；旧目录使用紧框/周边图像补充，小面积通用图形必须有可区分上下文。采用有限尺度边缘模板、独立候选差、局部双向边缘核验；多种证据冲突则拒绝。可传入明确提供的多外观，不自动把未验证模型输出晋升为可靠模板。

locate_region由至少2个且>=60%已登记子控件支持，拒绝多个子对象指向同一位置；只返回支持范围，boundary_verified=false，不将其当作完整区块边界或跨状态身份合并许可。首次分区不使用UIED。XFeat只做离线对照，未成为运行依赖。

## 已知路线入口

`python -m gui_rewalk.run_evidence_explore --app <app> --server-port <port> --goal <本次已授权导航目标> --output <新目录> --known-records <records.json> --route-attempts a3,a4,a5 --supervised`

两个新参数须一起提供，表示明确选择可重复的导航动作；不是将任意已成功业务操作自动标为可重放。KnownRoute仅接纳observed/intent=met/outcome=changed的click/back边，参考图片哈希、owner、输入层和相邻落点均须合法。重复采样观察可通过严格同视图连接。无需模型重新决定下一步；全图自动规划和滚动路线尚未接入。

RouteRuntime执行：当前App检查→已知源视图/前景确认→视觉定位→若不确定，单次Luna ground→现有EvidenceStore动作校验→监督后重新截图防旧点→真实投递→预期落点视觉确认，失败则Luna confirm。未知目标、背景目标、失败落点、预算耗尽均保留明确停止状态，不能绕过pending或宣称成功。Luna刚确认的落点可在同一未变化画面继续复用，控制外观仍需核验。Back只在已知来源执行；未知来源不猜测Back。

known-route模式允许max_calls=0，普通探索仍要求1..16；动作预算0..12。零调用无法确认意外落点时保留pending。CLI沿用固定Luna及单HTTP/调用禁重试限制。未知探索仍每轮调用Luna；不是默认让所有普通探索都不调用模型。

## 证据

2026-09-11：登记7个语义控件，1次定点纠正；在另2个同布局图上14/14定位、14消失/受阻反例无接受。旧参考周边增强从63/80→74/80，6次实际Luna回退补齐到80/80，另2反例拒绝。有限相关开发样例，不代表总体100%。导航子区12/12；任意展开/内容区未全面验证。

VLC Audio→Video→Interface→Cancel两次实机各3动作，首次2请求、复用刚保存记录1请求，均完成无pending。相对原一帧一请求的3步+末次观察机制可少50%/75%请求，但没有重跑旧框架费用基准。合计本任务13HTTP、6 Agent GUI＋4操作员准备动作；最后登记几何反馈分支只做离线验证。52项相关测试、编译和CLI help通过，未跑全门禁。证据位于artifacts/traversal_goal_20260909/revisit_runtime_20260911/REPORT.md、audit.json和live/。

## 公开新应用截图压力检查（2026-09-11）

3应用8张Commons公开缩略图（Calculator三模式、Writer带提示条/About、Firefox两网页）新增试验，算法未改。首次选定21控件中Writer居中语义位置错，全图再纠正仍错，人工选工具栏放大后Luna才正确；首轮不能计为全对。纠正登记后原样图正确13/23正例、0错误正例位置，但1/14背景/不存在反例误接受（View→About正文）；按已知缩略比例调整参考后15/23正确，同时2错误正例位置和1反例误接受。两条件不是新独立样例。

实际Luna回退10未定位正例仅8正确，数字3/等号的2个错误点仍通过几何gate；另主动核验View反例正确拒绝，但这不是失败才回退机制自动触发。区块子控件支持3/6正例、0/3反例，未验证完整边界。来源整体视图检查可使Writer About进入Luna，不能据纯匹配假阳性断言真实已点击；本轮0GUI。16HTTP、来源/缩略尺寸/人工标注/错误/纠正均在artifacts/traversal_goal_20260909/public_apps_20260911/REPORT.md。这些低分辨率/布局变化证据明确限制此前80/80的外推，既有新模式保持显式启用，未扩大自动执行或宣布通用近100%。

## VLC 登记/视觉回访/回退联合实机试验（2026-09-11～12）

复用现有EvidenceRuntime/RouteRuntime，以临时伴随记录脚本检查Region；没有修改正式默认流程，也没有把冻结截图tool harness接入实机。首次主窗口→Tools→首选项Interface→Audio→Video→Interface→Cancel完成6点击/8请求。原Tools回执因混入远期Preferences目标记not_met，保留不改；重开Tools用1点击/3请求，正确回执被错误控件框阻塞，后从已有回复本地分离原回执入账并隔离登记，留派生来源。

后五步已知导航中，前四步纯视觉执行/确认，0请求；Cancel视觉拒绝后先停下，用户明确允许截图外发，再用1次Luna定位、1次点击并视觉确认回到主窗口。总12模型HTTP/12GUI，52074输入/10384输出token，所有阶段当前pending为空，无设置修改/保存。监督只核对目标并放行，没有改落点；这不是无人干预或全应用完成。

跨分类导航区3/3匹配，变化内容区3/3拒绝；回到Interface可匹配原导航及内容，底栏漏检。底栏跨分类仅1/3通过，部分失败框内像素完全相同，仍是视觉算法问题。已知页回访16/22区块实例检查接受（含重复观察/单锚点菜单，非准确率）；候选boundary_verified/identity_verified均false，不用于自动身份归并或动作授权。证据、图、原始失败/本地修复/恢复结果见 `artifacts/traversal_goal_20260909/combined_region_traversal_20260911/REPORT.md`。生产代码不变；实机证据计数、回执及落点核对通过，未重跑无关回归或全门禁。

## 正式接线：已知路线后继续探索（2026-09-12）

新增 `--explore-after-route`，必须同时提供已有的 `--known-records` 与 `--route-attempts`。`hybrid.py::HybridRuntime` 先执行显式选择且已确认成功的导航路线；只有 route_complete 才进入 EvidenceRuntime，使用 `--goal` 继续有限探索。两阶段共用同一个EvidenceStore、帧/动作编号、实际调用/动作总预算和监督回调，不重置限额。路线失败/落点不确定/pending未结算时不进入探索；路线结束已耗尽请求预算则 `call_limit_after_route`，不虚报探索完成。普通探索与纯已知路线的CLI行为不变，未迁移旧框架。

```
python -m gui_rewalk.run_evidence_explore --app <app> --server-port <port> --goal <到达后的探索目标> --output <新目录> --known-records <records.json> --route-attempts a1,a2 --explore-after-route --max-calls 8 --max-actions 6 --supervised
```

混合模式的路线阶段原生保存 `region_revisit/fN.json`（region_revisit.py），由已登记子控件的context_box作锚点；整体输入层不匹配、少于两个锚点或算法歧义均拒绝候选。Region候选不负责动作授权/身份归并，错误单独记录，不阻塞已通过控件/输入层核验的导航。只比较已知路线期待页面，尚未把跨分类共享/拆分变成canonical身份更新。原始纯RouteRuntime可通过构造参数record_regions开启，CLI纯路线默认保持原行为。

混合模式继续探索时启用两项边界：监督后重截图，不允许旧点在输入层变化后执行；若已有唯一pending且新的控件context_box不合法，仅在原回执枚举/描述/输入层几何合法时本地分离回执，隔离全部控件/Region/claim/link，记录原回复来源到frames/fN/derivation.json，不增加模型请求。原动作是stop可结束，否则只observe并携带登记错误等待下次观察；不执行被隔离登记附带的点击。无pending或非法回执不采用此恢复。它不能纠正Luna的语义误认或目标粒度错误。

产物仍为evidence_explore.v1，增加phases/route.json、phases/explore.json（实际启动时）和合计status.json；未改变旧帧身份或自动将任意历史业务动作加入路线。未知目标的自动路线检索/规划、全应用调度仍未接线，节省主要适用于显式已知导航，不能把局部试验的请求比例外推到完整遍历。

验证：52项聚焦及相邻测试通过，含真实CLI参数/transport包装的离线仿真（无网络），预算耗尽/路线失败/帧改变/回执隔离及Region候选失败检查。首次计划的实机启动因新菜单截图外发审批被拒，未产生HTTP/GUI；用户随后明确允许实机验证。新版正式CLI完成Tools已知路线（0请求）→Luna记录三个菜单项→Back→确认主窗口，2实际请求/2动作，8852输入/1146输出token，4帧/2连续动作编号，pending/gaps/errors均空，阶段预算连续。原始证据见 `artifacts/traversal_goal_20260909/hybrid_integration_20260912/REPORT.md`。这只覆盖短段接线；回执隔离、可变布局和多锚点区块分支本版仍主要由离线检查覆盖，不冒充完整遍历验收。
