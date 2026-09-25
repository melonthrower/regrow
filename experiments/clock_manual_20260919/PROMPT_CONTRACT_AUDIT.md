# Prompt 与执行约束清理（2026-09-21）

范围：逐步遍历临时框架及其运行副本；原 gui_rewalk 不变。

## 已修改

|冲突/多余要求|当前行为|
|observe补定位，却要求blocked_by必须none|原因与处理独立，observe可说明control_not_visible；只有defer/blocked按异常原因转恢复|
|匹配是参考，代码却以低分直接否决|唯一登记目标、模型坐标落在低分候选范围内且说明位置依据时可接受，记录model_grounded；强匹配坐标冲突/多身份仍需核对。自动回溯保持原视觉条件|
|工作区块已由框架维护，却要求模型准确复述|新更新schema和prompt不要求working_context；登记直接沿用执行绑定的working_region。历史原回复不改写|
|允许补观察，却要求当前region和return_to不变|仅保留原任务及任务归属；新观察可纠正当前位置和路线|
|click附带无用text、back标签不同就报错|执行前归一化非本动作参数；back显示标签不作门禁，后台规范为系统返回。必要坐标/文本和动作空间仍检查|
|允许记录修订，但控件只能改名，其他字段报目标不唯一|控件支持name/description；对象歧义与字段不支持分别报错，描述原值在纠错上下文披露；不能覆盖历史观察|
|动作手册要求只走给定路径第一步，导航规则允许捷径|统一为参考路径，可选截图中更直接入口，一轮一步|
|普通返回需要预先allow_back，模型不能自行导航|普通动作可提出back；不要求机械target文字，保留任务目标与授权范围|

低分放宽不是任意坐标都能通过。必须仍落在匹配候选内；投递前如画面变化，重新判断。候选表缺对象仍需发现登记，不能给实际动作编造来源。拒绝原因现在分别说明缺候选、缺图片、位置差异或多个对象，不再只给笼统的“三者不一致”。

## 保留与未扩展

保留动作必要参数、坐标边界、真实来源与历史证据、待结算动作不重投、调用/GUI预算。没有把未知输入能力设为必须先验证成功；输入工具进入未知新界面时仍先结束已发生点击，由发现和后续动作续接。

本次未修改每个纠错episode的次数上限、参数事实同名不同条件的组织方式；这两项需要分别调整流程/记录结构，不能单删校验而丢失旧证据。也未把候选名称匹配改成模糊匹配。首轮未处理Broccoli可交互区块为空的问题，后续处理及验证边界见下节。

## 验证

115项针对性离线测试通过。离线检查：`artifacts/tmp_tests/contract_cleanup_20260921/final2.log`，命令见同目录commands.txt。包含observe携带定位原因的真实纠错→补观察→更新登记测试、跨区块任务归属、描述修订保留身份、无关参数归一化、坐标冲突反例、正常回溯相邻检查。

保存帧证据：`records/075_contract_cleanup_20260921_01/`。用Markor原0047请求、回复和截图运行新绑定器，原坐标直接通过；Clock0133的组合限制已删除，补观察执行由离线集成测试验证。0新增HTTP、0GUI；没有重写四路历史或重置失败次数。

## 第二轮：组合后的语义一致性

- task.reason作为“任务建立时的记录（历史，不代表当前状态）”披露，目标用任务名。blocker_history已有resolved_by且当前无blocker时，明确说明历史阻塞已解除；不解析旧中文句子改写历史事实。
- 增量对象与当前可交互集合分开：regions/controls只提交变化；previous_regions的retained_interactive/changed_interactive也组成当前可交互集合。不可见/背景区块不继承，异常前景不继承业务区块。原区块图片不伪造为新观察；retained区块的旧控件裁剪只有在当前帧重新匹配成功才加入当前控件候选，changed区块未重新报告的控件不沿用旧定位。
- 普通动作none（不仅导航动作）进入发现步，保留任务并传递缺口原因；不新增GUI动作。模型不需要在普通动作schema里填写observe/defer。
- “任务目标”与“本次控件”分开，允许准备动作；input_text手册只说明选择对象/文本以及可能只完成聚焦，底层跨界面输入条件留在执行器。

验证：82项聚焦离线通过，日志与命令见artifacts/tmp_tests/prompt_coherence_20260921/。修正旧返回测试中同一Menu同时报可见和not_visible的矛盾夹具。Broccoli原0089在独立账本副本回放，不改原回复：三个区块重新进入interactive_regions、五个控件当前帧匹配成功，next_action_mode=explore，正常动作请求为退出已完成顶部导航区块、继续来源菜单工作。这里只证明不再误进位置未知恢复，不宣称整个调度循环已实机消失。证据records/076_prompt_coherence_20260921_01；0 HTTP、0 GUI，原四路暂停状态不变。

## 第三轮：独立接口审核后的修复

- 纠错分别披露任务目标与被拒操作对象；相关记录保留原任务控件及实际操作控件，不再把后台可绑定候选裁成原任务控件。准备动作保留原动态任务上下文；记录编辑仍限相关对象。
- wait允许画面变化；back复用已有same_surface视觉相似性检查，不再要求逐像素相等。这是视觉近似判断，不声称能证明语义前景一致。
- 普通none交接接受请求实际使用的最新截图；补观察后不倒退为轮次初始截图。
- 已接受匹配只展示实际采用的位置；未确认匹配保留候选，明确不唯一。

验证：41项聚焦离线测试通过，包含准备对象纠错、补观察后none交接、微小像素变化与整屏替换反例；命令及日志在artifacts/tmp_tests/review_fixes_20260921/。4个源码文件已同步运行副本并核对哈希；0新增HTTP、0GUI，未改历史运行账本。

审核口径：此前独立代理是带源码背景的接口一致性审核；本轮另由不继承对话的陌生读者只读076的两份动作步文字请求。能正确复述任务，但仍有候选框坐标格式缺定义、混入其他阶段术语、缺完整JSON示例和重复说明。其报告FRESH_READER_REVIEW.md保存在上述目录。样本没有可用截图，且未覆盖发现/更新/恢复流程，不能宣称全流程prompt通过。除了候选位置矛盾，其余阅读建议本轮未修改。

## 第四轮：全模块陌生读者审核（未实施修复）

三名不继承会话、不看源码或设计的代理，逐文件审43个prompt、7份静态schema，再审当前组装器生成的60份请求（发现/任务/功能20，动作/更新21，恢复/纠错19）。根代理检查组装入口、核对实现并排除离线夹具错误。完整报告与来源/哈希/逐项清单：`artifacts/tmp_tests/full_prompt_review_20260921/REPORT.md`。

确认优先问题：任务指令要求input_text但最终schema仅click/scroll；更新禁止identity却拼入使用same的列表规则。另有历史/当前控件混合清点、增量引用旧父区块规则缺失、无定位对象必填focus_presence、静态标题混入可设置约束、恢复异常标签/未登记按钮命名歧义。8个旧prompt未找到当前临时Python/流程配置的直接引用，其内部冲突单列，不冒认主链已调用。

验证：14项schema/文字矛盾检查命中；`finalize_review.py`核对60份请求均在分工报告中列明，43prompt/7schema清点通过。这是只读静态与离线请求组装，不是模型成功率/真实遍历验收；0新增GUI、0框架HTTP。部分分支使用明确标注的合成情境，真实帧与合成帧分开；生成样本的三处初稿问题已修正并保存旧稿，未当作框架缺陷。本轮未修改执行代码或prompt。

## 第五轮：审核问题修复（离线验证）

- 任务schema与可用于控件探索的click/double_click/long_press/input_text/scroll一致。任务清点只需补充新任务或参数；登记器和诊断器均合并已有任务计算覆盖，不要求重报旧任务，不改变其状态/历史。上下文逐控件标记当前定位或历史未定位。
- 列表共用规则只描述沿用对象，具体身份字段归各阶段；更新明确允许为归属引用而重列旧Region，并给出索引示例。无指定定位区块时focus_presence明确为null；发现匹配只披露采用位置，不把备选并列为唯一。
- 功能输入将原属性目录标为待甄别事实，不再预先宣称全是可设置参数。功能模型依据操作/界面证据选constraints，排除只读事实；程序不按标题关键词筛选、不改写旧事实，也不声称离线验证了语义分类成功率。
- 不阻塞提示统一填none后交回发现；异常恢复目标允许直接用截图按钮文字/外观，不要求先登记。明确关闭提示与关闭所指应用的区别。补齐动作、none、恢复嵌套回复、补观察与描述修订例子；候选框坐标格式已解释。
- 遍历prompt/README.md列当前装配入口、独立保存帧入口和8个未接入旧模块；保留文件与原历史，不将旧规则混入当前请求。

验证：83项针对性离线测试通过；8份基于原保存记录的当前请求重组通过，原始运行账本不变。日志、复现脚本、请求、运行副本备份与哈希位于artifacts/tmp_tests/prompt_audit_fixes_20260921/。未进行新的Luna回答或GUI遍历，未重跑全框架门禁；此结论限合同、登记和请求披露的离线验证。

## 第六轮：四路真实续跑077

冻结c22cbadb及既有工作区修改，原5690/5692/5694/5696实例与账本继续；每路30HTTP/30GUI上限，监督器在小段后请求轮次结束暂停。实际39HTTP/10GUI，8个新动作均已登记，另2GUI为已知导航回放；全部停止，无已投递待结算动作。Settings进入Wi-Fi hotspot详情，Markor进入设备文件选择器但未导入；后者搜索任务缺候选暂挂后确能继续其他入口。Settings一次参数事实条件冲突由纠错修复。

仍有问题：Clock旧耗尽纠错直接阻断，0新调用；Broccoli已完成About顶部栏仍作为工作目标导致抽屉/页面往返；0097/0098将不同功能导航项当同类数据代表，后续重发现不抹去中间错误。不能声称prompt全面修复后已无阻塞。报告、逐步真实截图、请求/回复引用、冻结源码与用量见records/077_prompt_fixes_live_20260921_01/REPORT.md。本轮无框架代码修改或历史清理。

## 2026-09-21：阻塞后的流程衔接

- 新一轮启动时，未投递的 blocked 提案保留原 episode/计数/错误，转为当前截图发现；有投递未结算的步骤仍先结算，不重做动作。
- 动作纠错的补观察刷新请求后，允许一次正常动作提案；不重置纠错计数、观察次数或预算。blocked_by 对 observe 同样保存。
- 动作任务选定后，只匹配该任务缺失的控件图片；匹配成功才补当前候选。匹配失败仍允许普通准备动作，不要求未知编辑能力先被证明。
- 已完成区块退出后不再作为未完成目标导航返回；已知回溯到 return_to 后工作目标切换到来源区块。未完成参数任务保持归属。
- 同类列表校验明确区分数据成员与不同功能入口；允许依据证据清空错误 list_group，保留控件与历史。

验证：`tests/test_stepwise_pipeline_unblock.py` 与 shared_step_repair、visual_backtrack、task_correction、deferral、prompt_audit_fixes、region_tasks、resume_route，共79项通过；日志 `artifacts/tmp_tests/pipeline_unblock_20260921/final.log`。四路实机验证另存 records/078_pipeline_unblock_20260921_01，不以这些离线测试宣称实机已恢复。

实跑078进一步定位：retained_interactive图片匹配后只加入control_refs，未向动作绑定披露对应观察证据，造成“已定位但候选为空”。现将已匹配证据交给同一运行期视觉投影；目标补匹配也以实际backend候选为准。补观察自身的登记失败改走发现步纠错，使用原发现schema，接受后返回原任务，避免用动作schema修复发现错误。子步骤有独立持久指针但共享HTTP预算，暂停可续接；不重发GUI。目标调度同时清理过期导航交接。
追加验证112项通过，日志 `artifacts/tmp_tests/pipeline_unblock_20260921/final3.log`；含补观察错误归属与保留区块匹配证据传递测试。

079实跑：补观察可在发现格式下纠正，Broccoli已探索Demo recipe并完成外部恢复。Clock/Markor的更新纠错提出正确list_group字段修改，却被误送已入库记录接口；现将对象、原值与被拒提案唯一匹配的name/description/list_group修订先应用于待接受提案，保存effective_candidate及effective_request，原始回复不改。完整提案仍走原登记校验；不能据此改写动作历史。已blocked且上一回复为这种可解析修订时，无新增模型调用直接恢复accept，保留原计数。提示明确区分待接受提案与已入库记录。114项聚焦检查通过；Clock0145、Markor0078实际回复离线回放后完整诊断errors/unchecked均为空（`artifacts/tmp_tests/pipeline_unblock_20260921/replay_real_edits.py`），真实续跑另记080。

080现场检查（2026-09-21T15:37:31.051232+00:00）：四路均已越过上一段阻塞并继续自动运行，Clock原a0015与Markor原a0008均由既有纠错回复补结算，无重发GUI；Clock继续Timer/Stopwatch，Settings继续热点配置，Markor进入文件搜索，Broccoli继续Legal入口并完成外部恢复。仍在运行中的动作按原结算链处理，不宣称全应用完成或没有后续未知问题。每路本段30HTTP/30GUI上限。实时证据与截图见 `records/080_pipeline_unblock_20260921_03/REPORT.md`，交接时状态另存handoff_status.json；078/079失败现场均保留。

## 2026-09-21：用户限定应用内探索，完成区块继续调度

有具体可见或历史线索表明可能打开外部应用的入口只记录、不试探。任务清点prompt提供正反例；动作共享原则同步范围。普通未知应用内功能仍可探索，意外外跳仍按恢复→发现处理。

新增traversal_scope：有实际external_app结果的未完成任务自动转record_only，保留attempts/findings与原处理方式scope_history，删除活动待办引用；不伪造done。旧任务首次来到本区块时用原任务清点格式复核范围，只允许带依据将原对象/动作/类型不变的未完成任务改为record；其他旧任务仍不得任意重分类。新清点记external_entry_policy，避免逐轮重复复核。

Clock调度：工作区块完成后即使当前仍可见，也可选择其他未完成区块；return_blocked同样先调度其他区块。消除“已完成底部导航必须先退出”的停止条件，保留无路可走时的真实缺口。清理current()中重复组装调用。

验证：73项聚焦测试通过，命令与日志在artifacts/tmp_tests/external_entry_policy_20260921。实机records/081_external_entry_policy_20260921_01：Clock第一轮复核/导航交接，第二轮发现Bedtime内容→任务清点→点击溢出菜单→a0020结果登记成功，共5HTTP/1GUI；Broccoli将Privacy policy三条历史外跳对应待办改为record_only，未再次点击该入口，2HTTP/1GUI通过已有导航返回应用内许可区。两路已按step模式暂停，0待结算投递。未续跑Settings/Markor，也不宣称全应用探索完成。

## 2026-09-21：只读区块跳转图

现有progress_window增加/graph与进度页链接，/graph.json从同一个已提交knowledge快照投影区块、控件、任务状态及跳转。只展示有零退出码执行回执、目标在动作后interactive_regions内且无异常的正式transitions，合并同来源控件/动作/目标的多次证据；箭头表示执行后观察到目标可交互，不另推断Page身份或补造路径。外部跳转只在控件历史结果中展示。

左图点击区块、右栏查看登记截图和控件；选控件高亮对应边，目标按钮可继续查看关联区块；支持搜索、缩放、原图预览及每10秒读取最新快照。截图接口只按已登记对象解析，限定运行目录内图片，不接受任意文件路径。图操作不执行GUI、模型调用或修改知识。当前启动入口记录在records/082_region_graph_viewer_20260921_01/service.json。

验证：region_graph/progress/launcher三组20项测试通过；真实Chromium对当前Clock图验证区块选择、控件筛选、沿边导航、搜索和图片加载，10节点19关系，0页面异常。证据在artifacts/tmp_tests/region_graph_20260921/browser_result.json与graph.png；未新增遍历动作。

## 2026-09-21 更新步复用区块视觉身份

- `run_task_step` 在动作后截图中调用既有 `image_match`，把区块裁图候选名称、当前位置、分数放入更新动态上下文。位置用于定位，不比较历史整屏或绝对位置。
- `update_region_matching` 在更新校验与登记前把唯一、像素完全一致的新区块提案改为复用旧区块；同名唯一控件复用旧控件。原始 Luna 回复不改，派生匹配依据及有效提案写入调用目录 `visual_identity.json`。近似匹配仅给 Luna 判断；多个历史身份完全一致时不任意选取。
- 修复根因：此前更新步只使用名称判断身份，视觉匹配没有接入，导致同一菜单在不同标签页被重复登记。
- Clock 的 `r0010` 合并回 `r0003`，五项控件引用同步映射、跳转去重；新快照保存修复依据，旧快照和原回复全部保留。证据：`records/083_menu_visual_reuse_20260921/`。本轮没有模型或 GUI 动作；用实际 0166 回复/截图回放登记并检查实时图网页。
- 不需要重启模拟器、应用或图服务。图读取新快照；当前停止状态下下次启动遍历进程加载新代码。已经运行中的遍历进程需要先暂停再启动，才会加载代码更新。
- 验证：`python -m pytest -q tests/test_stepwise_update_region_matching.py tests/test_region_registration.py tests/test_stepwise_update_visibility.py tests/test_shared_step_repair.py tests/test_stepwise_pipeline_unblock.py --basetemp artifacts/tmp_tests/update_region_matching_20260921/pytest_final`：59 passed。真实浏览器检查9节点/17条边，控件、跳转、图片加载正常；未启动新一轮 GUI 遍历。

## 2026-09-21 发现与更新共用身份登记

- 将 `update_region_matching.py` 收拢为 `region_identity.py`。发现/更新的接受校验与正式提交均调用同一归一化逻辑。发现步自动匹配成功时，同步建立派生候选引用并将identity改为same；原始请求/回复不覆盖。两步都保存 `visual_identity.json`。
- 自动复用的第二种证据：两次均明确完整的可见控件清单，文字/图标/名称集合一一对应，并由既有视觉算法确认区块外观及控件相对布局。整屏绝对位置不是条件。仅同名按钮、局部批次、代表项、未知完整性、不同布局不能自动合并；普通近似候选仍由Luna判断。
- 两步共用 `共享/区块身份复用.prompt`。区块可选字段 `controls_complete` 默认false，写入对应观察；不会从控件数量或空清单推断完整性，也不把旧记录追认为完整。此标记不是探索任务完成状态。
- 旧记录仍可按像素匹配复用。控件集合分支需要后续真实完整观察，不能靠补写历史标记激活。原始历史与当前图本轮均不变；没有新增模型调用或设备动作。
- 验证：共享身份、原更新匹配、恢复发现、局部发现、登记、纠错、更新可见性、发现派发与手册共9组测试72 passed（命令与日志 `artifacts/tmp_tests/shared_region_identity_20260921/final.log`）；实际Clock 0166截图/回复离线回放复用菜单及五控件，见 `records/084_shared_region_identity_20260921/`。未执行新Luna调用或GUI遍历。

## 2026-09-21：区块跳转图聚焦与动画

`region_graph.html` 改为中心登记截图＋直接入向/出向邻居；无关区块隐藏，自环保留在详情而不画外围节点。出向实线从中心控件卡片（含已有控件裁图）连至目标区块，入向虚线落在中心边框。点击邻居复用节点，用约650ms插值同步移动、缩放及更新连线；旧邻居退出、新邻居进入，连续选择从当前动画位置继续。搜索、详情、自动读取快照及原图查看沿用原入口；减少动态效果系统偏好下立即切换。

验证：`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/data/shenghonghui/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome /data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python -m pytest -q tests/test_stepwise_region_graph_browser.py tests/test_stepwise_region_graph.py tests/test_stepwise_progress.py tests/test_stepwise_launcher.py --basetemp artifacts/tmp_tests/region_focus_20260921/verified_routes`：21 passed。Chromium读取现有Clock的9节点/17关系快照，检查截图、移动、双向边、控件选择、图片预览和窄屏，0页面异常；未新增模型调用或应用GUI遍历，未跑全框架门禁。日志/录屏/截图在`artifacts/tmp_tests/region_focus_20260921/`，交付在`to_astra/region_focus_20260921_02/`。

本轮纠正：SVG百分比高度参与父容器尺寸计算会使画布在切换时变高，改为在固定画布内定位；区块聚焦回归同时检查实际移动与边端点，而非只检查节点数量。环境使用既有guiwalk-android Python，系统python/python3不具备所需浏览器依赖。

## 2026-09-21 返回目的地依赖进入路径

- 系统 back 自动识别为历史依赖返回。界面点击返回由更新回复可选 `action_result.returns_to_previous=true` 标明，不凭控件名称/箭头猜测；普通固定目的地点击不受影响。原始动作结果描述保留。
- 正式动作记录与其已观察跳转边标记 `destination_behavior=history_dependent`，动作另存 `navigation_description`：返回进入此界面前的位置，目标取决于进入路径；后接本次实际观察。图的控件入口标签、边描述和局部探索树同样披露。
- `shortest_known_path` 不把这类历史边作为固定路由；`visual_backtrack` 对已有请求路径也检查，不能绕过此规则自动执行。普通动作步仍可选择返回，更新步照常确认实际落点。没有落点时沿原空落点核对/发现流程，不用旧目标补边。
- 本版保守地不自动回放历史依赖返回，尚未实现进入栈条件匹配。旧系统返回即使无新字段，也按operation识别；历史可见按钮点击没有语义证据时不回填猜测。
- 验证：`python -m pytest -q tests/test_stepwise_return_semantics.py tests/test_stepwise_visual_backtrack.py tests/test_region_registration.py tests/test_stepwise_region_graph.py tests/test_stepwise_no_route_discovery.py tests/test_shared_step_repair.py --basetemp artifacts/tmp_tests/return_semantics_20260921/final`，55 passed，日志见同目录final.log。本轮仅离线聚焦测试，没有新模型调用或GUI动作，不改现有运行快照。

## 2026-09-21 关闭浮层也是上下文依赖返回

- 同一 `returns_to_previous` 语义包含关闭溢出菜单/对话框后恢复下方界面，覆盖关闭按钮、菜单按钮切换和点浮层外部；以观察结果识别，不按按钮名称猜测。不新增平行异常流程或字段。
- 共用返回登记、边描述与自动路径排除规则：记录本次恢复的区块，不把它当永久目的地。删除内容、折叠组件、固定跳首页不据此标记。普通动作和结果核对仍可执行关闭。
- 085四路续跑已请求轮次边界暂停，原冻结源及调用证据保留；新提示用于后续新进程，不改写已发送请求。
- 实跑暴露严格输出Schema要求新字段列入required：085四路HTTP 400，属于本次接线遗漏，不是Luna识别错误。发送层对新请求副本补齐controls_complete/returns_to_previous的required，保留旧请求及接受合同，续接未结算动作不重发GUI；086冻结源执行补结算。
- 验证：56项聚焦通过，日志 `artifacts/tmp_tests/dismiss_semantics_20260921/verified.log`；086真实续接6HTTP/0GUI，三路结果补结算、Markor纠错后ready_next_round，四路均暂停且0待结算动作。Clock真实a0021为系统返回关闭菜单，0169已登记history_dependent。点外部关闭尚未实机验收。报告 `records/086_dismiss_and_schema_resume_20260921/REPORT.md`。

## 2026-09-21 纠错嵌套输出格式与实跑087/088

- 085格式修复遗漏纠错proposal.anyOf内嵌的发现/更新Schema，087 Markor0121及Broccoli0160再次HTTP 400。发送层现递归处理这两个新增字段的required，覆盖普通与嵌套请求副本，原始请求不改。没有放宽登记校验或重置纠错次数。
- 验证：`python -m pytest -q tests/test_stepwise_transport_new_fields.py tests/test_shared_step_repair.py --basetemp artifacts/tmp_tests/nested_strict_20260921/pytest`，14 passed。088两路真实纠错各1HTTP、0GUI成功补结算；087/088合计38HTTP、11GUI，四路暂停、0待结算。实际截图及结果 `records/087_four_continue_20260921/REPORT.md`。
- 遍历仍有重复无进展：Clock开关同一菜单，Settings重复点击共享对象卡片未变化。本轮未修改任务去重/无进展调度，不宣称遍历已无阻塞或已完成应用。

## 2026-09-21 单步入口交接与重复点击暂挂

- 已投递的single_action入口点击，确认唯一目标区块且来源不再交互时，结算入口任务并切工作区块至目标；保留模型原始结果，框架completion_basis引用实际attempt/目标。目的区块独立清点任务。参数/滚动、准备动作、异常不套用此规则。旧Clock停点通过同一task_routing.advance发布派生快照，未重复GUI。
- 重复检查覆盖click/tap/double_click，同任务、同控件在相同前后画面已有至少两次未完成尝试时，不因更换控件内坐标放行。结构化RepeatedAttempt直接走既有task_deferral，不再消耗纠错去反复观察同一入口；blocked保留尝试事实，不算完成，调度其他可见待办。input_text原规则保留。
- 更新报告区块但实际交互清单因uncertain为空、有动作后截图时，回到发现步，不以region_history直接结束。
- 提示补充单步入口任务范围与正反例，不把整个子区块探索挂到父按钮。
- 验证：任务交接/重复拦截与自动暂挂、区块任务、纠错、登记、返回语义及deferral共85项聚焦通过；命令为 `python -m pytest -q tests/test_stepwise_task_loop_handoff.py tests/test_stepwise_region_tasks.py tests/test_stepwise_task_correction.py tests/test_region_registration.py tests/test_stepwise_return_semantics.py tests/test_shared_step_repair.py tests/test_stepwise_deferral.py --basetemp artifacts/tmp_tests/task_loops_20260921/confirmed`。同步更正旧测试中“back是固定路径”的过时断言。
- 实跑089 Clock确实清点菜单任务并点击Screen saver；090 Settings将共享对象卡片暂挂，转去显示身份，打开名称编辑框。Clock仍有独立卡点：屏保投递前画面变化使Back未执行，随后发现边界框超出原图引发纠错；没有将该动作记成功。完整证据保留records/089_task_handoff_continue_20260921和090_no_progress_resume_20260921。

## 2026-09-21 已观察入口结果复用
- 同控件已有确认执行、无异常且唯一目的区块的点击结果时，新命名的单步入口任务复用该证据；目的区块内部任务不因此完成。参数、返回、异常及目的区块不一致不自动完成。
- 任务生成披露已验证入口；动作上下文披露同控件历史，不因新任务名称丢失。任务完成后清除对应活动任务。
- 验证：`python -m pytest -q tests/test_stepwise_entry_evidence.py tests/test_stepwise_region_tasks.py tests/test_stepwise_task_loop_handoff.py tests/test_stepwise_task_correction.py`，27通过（guiwalk-android）；日志 `artifacts/tmp_tests/clock_goal_20260921/tests-final.log`。0181真实回复离线回放：Screen saver复用a0005，Settings保持pending，0模型/0GUI。
- 实际知识库发布独立快照，原动作/回复保留；屏保重新发现已启动，证据 `records/091_entry_reuse_20260921/`，尚未据此宣称连续遍历通过。

## 2026-09-21 原图尺寸动态披露
- 实跑091使用5次HTTP、0次GUI后停在发现步：0193猜1080×2400、0195猜1080×2376，实际原图1080×2340，造成越界与无效纠错。
- 统一发送入口逐张读取实际图片尺寸，追加原图坐标范围；不缩放坐标、不更改原请求，不再依赖Luna从显示图猜分辨率。发现、动作、更新、纠错共用。
- 验证：`python -m pytest -q tests/test_stepwise_frame_context.py tests/test_stepwise_transport_new_fields.py`，3通过，日志 `artifacts/tmp_tests/clock_goal_20260921/frame-verified.log`。实机效果待后续续跑，不声称本次已解决所有阻塞。

## 2026-09-21 动态外观下的身份候选召回
- 实跑092的0198正确使用1080×2340；0199清点为空。0200却被调度从当前Screen saver前往另一个同名Screen saver，选择wait；0201更新又遭遇同名身份冲突。尺寸修正有效，但整体遍历未通过。
- 原全局定位过滤所有未达定位阈值的图片，动态内容变化时旧身份不向模型披露。现保留按图片分数排序最多3个弱候选，总上限仍8；它们保持未确认，不构成本地定位、自动合并或控件操作依据。无图片证据仍不补造位置。
- 验证：`python -m pytest -q tests/test_stepwise_region_recall.py tests/test_local_region_discovery.py tests/test_stepwise_screen_coordinates.py tests/test_recovery_discovery.py`，16通过，日志 `artifacts/tmp_tests/clock_goal_20260921/recall-adjacent.log`。新召回策略尚待后续实跑；既有重复区块与wait回执歧义待处理。

## 2026-09-21 wait执行事实回执
- 092实跑0201–0203把wait视为未执行：执行器实际sleep(2)，但executed_steps为空。现在sleep成功后保存wait/seconds=2，仍不宣称界面产生预期效果；不计为ADB输入，等待中断不写成功回执。旧回执不改写。
- 验证：`python -m pytest -q tests/test_stepwise_wait_receipt.py tests/test_stepwise_input_target.py tests/test_stepwise_list_input.py`，结果见 `artifacts/tmp_tests/clock_goal_20260921/wait-adjacent.log`。当前运行已停止，新的wait回执尚未实跑。
- 未解决：0203纠错请求区块merge_into，而现有修订能力仅支持控件合并；重复区块尚未合并，原pending结果必须先处理，不能重执行已发生动作。

## 2026-09-21 纠错区块合并
- merge_into的control为空时按区块处理；同名重复区块在纠错上下文完整披露，由Luna给出同物理区块证据。保留当前动作来源，迁移观察、动作、任务、功能、结构化区块引用及图片路径；旧快照和原始调用不改。不同的同键任务/功能不能静默覆盖，整批修改失败不发布。
- 复用083菜单修复的结构化引用迁移方式，新增region_records模块；更新登记解析被合并工作区块引用，已执行来源仍保留。不是基于名称自动认定相同区块。
- 验证：`python -m pytest -q tests/test_stepwise_region_merge.py tests/test_stepwise_task_correction.py tests/test_region_registration.py`，33通过；日志 `artifacts/tmp_tests/clock_goal_20260921/merge-final.log`。
- 应用0203已提供的合并编辑，真实库5个Screen saver变为1个，working_region与interactive_regions一致；0模型、0GUI，原回复保留。证据 `records/093_region_merge_20260921/result.json`。旧wait更新仍pending，未声称恢复连续遍历。

## 2026-09-21 动态画面中的系统返回
- 0204使用原a0029前后图和执行器核查说明完成旧wait登记；未重做动作。093/settled.json保留结算结果。094实跑0205正确选择back，却被屏保时间/位置变化的整屏检查拒绝。
- 返回无点坐标：动作轮开始读取Android前景窗口身份，投递前同一窗口时允许动态像素变化；窗口变化拒绝，无法获取窗口身份沿原视觉检查。普通坐标动作定位核验、历史视觉回溯均不改变。
- 验证：`python -m pytest -q tests/test_stepwise_review_fixes.py tests/test_stepwise_task_loop_handoff.py`，10通过，日志 `artifacts/tmp_tests/clock_goal_20260921/back-window.log`。095正在单步实机验证，尚未声称退出成功。

## 2026-09-21 工作区块始终参与身份核对
- 095实跑0207的弱候选排序仍遗漏当前Screen saver，Luna明确因候选缺少而报new，整轮5HTTP/0GUI停下。弱匹配召回不能取代工作区块记忆。
- 全局定位优先保留本轮focus区块为待核对候选，再加入强匹配和有限弱候选；不提高匹配置信度，不直接认定在场，总数上限8不变。
- 验证：`python -m pytest -q tests/test_stepwise_region_recall.py tests/test_local_region_discovery.py tests/test_stepwise_screen_coordinates.py`，9通过，日志 `artifacts/tmp_tests/clock_goal_20260921/recall-focus-final.log`。该补充尚待实跑。

## 2026-09-21 静态项与未知参数范围
- 098实跑0216遗漏已登记静态标题触发coverage纠错；0217又被后台integer上下限非空约束拒绝，0218清空所有findings才通过。随后0219点击加号、0220观察7:00→7:15并完成代表性任务；共5HTTP/1GUI。
- 新共享交互控件范围prompt接发现与更新：纯装饰标题属于区块描述，具有交互线索但功能未知的对象仍登记。旧静态项用record覆盖，不派发点击。
- integer未知min/max按原schema允许null，仅已知倒置范围拒绝，不强迫模型虚构范围或删去所有观察事实。
- 验证：参数、任务、纠错及发现相关28测试通过；发现/更新提示组装24测试通过。日志 `artifacts/tmp_tests/clock_goal_20260921/{parameter-contract,static-contract}.log`。新提示效果尚待实跑。

## 2026-09-21 未完成清点保持局部归属
- 100实跑0230因列表底部未滚动标partial，commit_plan清空inspection_region后，0231错误核对了上层Bedtime，再0232回到声音页，徒增发现调用。
- partial重新发现固定使用本次清点区块，保留工作目标；当前可见项有任务且未见内容有scroll任务时，提示明确允许inventory=complete，不与区块完成混淆。
- 验证：任务、纠错与区块发布23测试通过；日志 `artifacts/tmp_tests/clock_goal_20260921/partial-owner.log`。冻结的100运行已申请轮末暂停，新逻辑尚未实跑。

## 2026-09-21 参数条件变化保留为观察
- 真正失败对象是YouTube Music任务的“声音来源入口”事实：conditions由[]补充“不探索可能的应用外跳转”；旧错误仅说different conditions，0235/0236误修铃声事实。
- 同名同类型事实允许不同条件，按observations保留每次条件、范围、描述及来源；不同条件的枚举不合并成通用取值。不同类型仍拒绝，错误明确任务及事实名；更新诊断同步放开条件文字变化。
- 验证：参数、诊断、任务和纠错31测试通过，日志 `artifacts/tmp_tests/clock_goal_20260921/fact-conditions.log`。真实0236回复在不重调用模型、不执行GUI下成功登记，清点缺口清除，证据 `records/101_fact_conditions_20260921/replay.json`；连续实跑已恢复。

## 2026-09-21 可能外跳入口阈值
- 0239将Help列为explore，理由“未证明必然外跳”，与用户的可能外跳排除范围矛盾。提示补充外部服务线索的判断标准与正反例，不按名称在执行器硬编码跳过。
- 0243使用0239原截图的单次Luna验证：隐藏入口保持explore；三安装入口、反馈和Help全部record。0GUI且未将回放冒充现场；随后只对已有未执行Help任务发布范围复核快照。证据 `records/102_scope_probe_20260921/{result,applied}.json`。
- 实跑101两轮6HTTP/2GUI：打开声音菜单、隐藏YouTube Music；后者一次列表代表项纠错后登记成功。未执行任何外部入口。

## 2026-09-21 单步入口外跳直接结算范围
- 0244点击Add new，0245正确识别文件选择器external_app，但后台因task_result.done拒绝；0246改pending才通过。0247/0248一次系统返回恢复目标应用。
- 当前任务自身的非准备单步入口出现已观察external_app时，框架直接转record_only并关联真实Attempt，保留scope_history；不代表导入等外部流程完成，不让它留作重试入口。不适用于别的控件的导航或跨区块参数任务。
- 验证：外跳结算、任务及入口接手22测试通过，日志 `artifacts/tmp_tests/clock_goal_20260921/external-result.log`。103实跑使用旧冻结源，尚未实机触发新结算规则；恢复返回已验证。

## 2026-09-21 代表性滚动与执行归属
- 0255仅因下一同类数据行部分可见而保持scroll pending；随后invalid Region scroll owner来自结果标签“Device sounds列表”不等于绑定区块名称，误导纠错新建子区块。滚动/系统返回现在只用执行绑定确定区块归属，不重复校验模型描述名称。
- 任务提出与结果提示统一：同类数据代表性滚动确认交互结构后可完成，明确未穷尽条目；不同设置结构或明确底部功能线索仍调查。
- 更新阶段已确认区块中的唯一同名列表角色可复用，显示值改变不要求新建控件；只适用明确list_group的更新，不按名称合并普通控件、不绕过发现身份核对。
- 验证：登记/任务/列表角色41测试通过，日志 `artifacts/tmp_tests/clock_goal_20260921/scroll-role.log`。0258在原0255保存图上实际Luna验证报告done并限定代表性调查；a0042原滚动结果成功结算，0额外GUI，证据 `records/104_scroll_probe_20260921/settled.json`。

## 2026-09-21 纠错上下文披露等价任务的实际状态
- 105实跑0261将等价任务的原始pending误当独立待办，a0043重复选择Carbon。repair_stages此前未披露handling/equivalent_to，也未继承代表任务结果；现按所属区块完整记录披露代表状态、覆盖任务与对应尝试事实，不改写原记录。
- 验证：`python -m pytest -q tests/test_stepwise_equivalent_context.py tests/test_stepwise_task_correction.py tests/test_stepwise_diagnostics.py`，16通过；日志artifacts/tmp_tests/clock_goal_20260921/equivalent-tests.log。真实0260请求离线组装结果equivalent-real-context.json显示done及Silent已选中的证据。尚未进行新Luna或GUI验证。
- 未解决：旧音乐推荐弹窗无任务清单，被全局前沿重新选为目的区块；105已确认进程退出，轮末暂停。不能据此宣称整体重复探索已解决。

## 2026-09-21 先补已访问区块清单，再决定是否回访
- 参数任务跨入新区块时也先清点该区块任务，避免关闭后留下无清单区块，再被当作未知目标回访。保留父任务，不将子区块任务混入父入口。
- 新模块historical_inventory：工作目标已离开、没有清单但有已执行动作和完整区块观察时，复用保存帧调用原任务清点；明确为历史材料。登记核验区块证据摘要，不改当前落点；partial保留缺口，不反复历史清点或把旧帧冒充新观察。补齐后可直接进行已有功能整理，再按正常完成逻辑调度。
- 106实跑0263用历史截图补清单，Dismiss复用已观察关闭结果，无GUI。但模型仍把带下载图标的推荐行列为探索；提示补充整行安装线索的正反例。107保存帧范围复核0265改为record并发布新快照（无GUI）；原回复未修改。修复历史登记时当前observation为None的访问错误，复用0265提交，未重发模型。
- 108实跑0266/0267重新发现当前声音页面，0268整理旧提示区块，无GUI；工作目标已从r0017切到r0016，清除回访目标。新增可见“设备声音预览”尚待清点，不声称遍历完成。历史清点是任务生成，不证明当前可见或执行成功。
- 验证：历史清点、任务、交接、纠错28测试通过；日志artifacts/tmp_tests/clock_goal_20260921/history-tests.log；三个修改模块py_compile通过。现场调用/截图/冻结源分别在records/106_historical_inventory_20260921、107_popup_scope_review_20260921、108_after_inventory_20260921。

## 2026-09-21 按观察目标结算，不强求推测效果成功
- 109实跑a0044预览图标消失、a0045等待无变化、a0046点击Carbon后图标出现；旧更新将听不到音频当作必须继续的缺口，7HTTP/2点击/1等待后监督暂停。
- 更新手册明确：单步观察任务可按已观察界面反馈完成，同时保留音频等未验证限制；明确音频验证目标但缺少渠道时应blocked。不是无证据确认功能成功，也不放宽参数/输入目标的证据要求。
- 110保存帧0276仍pending，证实动态“准备动作必须pending”覆盖新规则。改为准备标签只说明选择时意图，更新按实际目标及结果判定；取消settle_task对preparatory_action的无条件done拒绝，仍保留异常与参数事实校验。111保存帧0277判done且明确音频未验证，经既有commit_update重评a0046；原调用、截图和快照不改，0GUI。
- 探索树等价任务沿用代表任务的结果，不再同时显示已完成与尚未执行；对应旧多区块参数测试更新为先清点再继续父任务。
- 验证：`python -m pytest -q tests/test_stepwise_equivalent_context.py tests/test_stepwise_goal_context.py tests/test_stepwise_region_tasks.py tests/test_stepwise_task_loop_handoff.py`，26通过，artifacts/tmp_tests/clock_goal_20260921/preview-tests.log。保存帧证据见records/110_preview_result_20260921和111_preview_reassess_20260921；尚未据此证明全部实跑高效。

## 2026-09-21 导航保留局部更新外的可见入口与已知效果
- 112实跑目标已为r0015，0279却再次点击预览：更新只披露变化控件，changed_interactive区块未匹配旧返回箭头；导航文本也省略已有控件结果。该轮3HTTP/1GUI后暂停。
- update_visibility对仍可交互的变化区块也重新匹配旧控件；register_update将全部当前交互区块（含regions增量）送匹配，不凭历史直接判可见。导航候选附最近两条不同的真实结果，并明确动作应推进导航，不能重新测试局部效果。
- 113无模型/无GUI保存帧匹配恢复c0055返回、c0056菜单、c0070列表。原0280重放因不可变快照已存在正确未覆盖；另用publish发布匹配观察，保存refreshed.json。
- 114实跑0281点击返回箭头、0282确认到达Bedtime唤醒闹钟设置，2HTTP/1GUI/0纠错。实际动作a0048；不再选择已完成预览。
- 验证：导航披露、路径、更新登记34测试通过，artifacts/tmp_tests/clock_goal_20260921/nav-tests.log；三模块py_compile通过。修改仅临时框架；其他区块尚未完成，持续遍历目标仍在进行。

## 2026-09-21 同次操作结算已验证的关联单步任务
- 115实跑7轮17HTTP/7点击/0纠错：振动切换、Skip进入睡前引导、时间入口打开选择器、小时字段无变化后改选12、分钟选05、AM切换。原参数任务完成，但同控件的小时/分钟刻度盘单步任务仍pending，存在重做风险，轮末暂停。
- 新模块related_task_results只提取本次实际控件上pending/explore/click的其他single_action任务，更新动态上下文提供名称与目标；有候选才加入related_task_results输出及独立手册prompt。Luna逐项给出同一动作已满足目标的证据，可返回空列表；框架验证所属控件、任务类别、候选名称与无异常后关联同一attempt，保留单独任务身份，不增加GUI动作。
- 不把参数任务或其他控件任务按名称相似自动结算；原参数结算仍要求对应事实。此机制接在原更新登记事务中，无额外常规模型调用。
- 116保存帧0300/0301分别复核a0053/a0054，确认小时11→12及分钟00→05也完成对应刻度盘反馈任务。仅发布关联任务结果的新快照，不回滚当前12:05 AM落点、不覆盖旧回复，2HTTP/0GUI。实时新路径尚待后续出现关联候选时验证。
- 验证：关联结果、登记、交接、纠错41测试通过，日志artifacts/tmp_tests/clock_goal_20260921/related-tests.log；候选缺失、异常及参数任务误归类均不结算。当前仍需探索键盘输入等任务，整体目标未完成。

## 2026-09-21 已有控件的新操作方式触发补充任务清点
- 117实跑0303确认时间选择器切换字段输入，旧清单按控件ID判断完整，0304整理功能后0305/0306关闭对话框，漏掉实际输入验证；5HTTP/2GUI后暂停。
- 发现/更新共享task_review_reason：模型必须指出有依据的新操作方式，值变化/选中变化不触发。materialize_regions将理由写入task_inventory.review；coverage暂不认为清单完整，保留已完成任务，下一次plan补新任务后清除review。独立prompt带正反例；更新动态提供来源区块已有任务，供判断是否已覆盖。已有历史区块的review可走保存帧清点，避免只为清单回访。
- 118调用0307因新增字段漏入API必填清单返回400，无模型结果、无GUI；已修复生成请求的required列表并补测试。119保存帧0308识别字段输入新能力，仅登记review不改变当前落点；120调用0309通过框架历史任务清点补出小时input_text、分钟input_text和切回刻度盘任务，保留旧任务完成状态。均无GUI；新任务实机待继续验证。
- 验证：操作方式复核、登记、区块任务、历史清点、恢复发现55测试通过，日志artifacts/tmp_tests/clock_goal_20260921/mode-tests.log。旧登记测试按新增输出字段补空字符串；所有原始失败/成功请求与预算保留在records/118_operation_review_20260921至120_input_task_inventory_20260921。

## 2026-09-21 区块匹配去除重复计算
- 121实跑减号、加号、星期选择与打开Reminder notification共9HTTP/4GUI；0317将同类提醒选项重复登记，0318纠错一次成功，原动作未重做。轮末暂停检查每轮动作后截图至更新请求约45秒的开销。
- 固定a0061动作后真实截图与同一快照测量：旧region_identity.candidates耗时49.208秒、96次匹配。100张区块图只有68种不同像素。
- 同一区块完全相同的像素只检查一次；不同区块身份和不同像素图不丢弃。已命中的区块停止解码旧样本。image_match.SceneMatcher复用同一帧的像素与边缘，原locate也走同一算法；缩放、阈值和几何候选算法不变。
- 相同快照和截图对照：28.471秒、64次匹配，约减少42%；候选名称、坐标、分数与旧结果严格相等。证据artifacts/tmp_tests/clock_goal_20260921/region-match-baseline.json、region-match-after.json及对应profile。仅这一保存帧测量，不泛化为所有页面速度。
- 验证：批次匹配、区块复用、合并、列表角色13测试通过，日志artifacts/tmp_tests/clock_goal_20260921/match-tests.log。接下来实跑继续检查整体调用链。

## 2026-09-21 同类选项组的图像范围不再限于第一行
- 122实跑任务正确要求选择未选中的30分钟，但0320被旧15分钟单行crop拒绝；0321补观察，0322再次重复登记两行，0323纠错改代表到30分钟。0324耗尽轮内模型余量未投递，下一轮0325重新选择，0326完成：共8HTTP/1GUI。这是代表项范围与参数选值冲突，不是控件不可操作。
- 重写共享“列表代表项”手册：同一数据/参数交互组只登记一个稳定控件，bbox与保存crop覆盖当前可见同组成员，单独的Cancel等入口不混入。text/state描述组内值与选择状态，操作语义不锁定第一行；不同功能导航仍分开。未改匹配阈值或动作命中门禁。
- 123保存帧0327一次得到一个五行单选组和独立Cancel；整组bbox=[160,887,827,1475]，原30分钟动作(500,1048)通过原bind_action_target，指向Cancel的同名动作被拒绝。证据result.json、group.png、binding_check.json；无GUI、未把旧截图登记为当前落点。后续实跑按新prompt生成图像，现存历史crop不批量重写。
- 仍待处理：纯Cancel被旧任务清点列为explore，可能导致为验证退出而回访；预算耗尽后已选动作下一轮重新询问也有额外开销。未宣称完整高效遍历已完成。

## 2026-09-21 纯退出服务任务不制造重访

- 清点提示明确关闭/取消/返回的服务用途与保存提交等业务效果的区别，补正反例；不为验证纯退出而重开已离开的弹窗。未执行效果仍未验证。
- 范围复核复用既有任务清点调用，新增请求标记task_scope_review，允许有证据的未完成服务任务改为record；保存scope_history、attempts，状态record_only而非done。旧external_scope_review请求仍可读取；实际外跳自动排除保持原政策。
- 验证：`python -m pytest -q tests/test_stepwise_external_scope.py tests/test_stepwise_region_tasks.py tests/test_stepwise_historical_inventory.py --basetemp artifacts/tmp_tests/clock_goal_20260921/service-tests`，22通过；日志同目录service-tests.log。服务复核测试先失败后通过。
- 真实模型0328读取历史提醒弹窗截图，将Cancel待办改为record，0GUI；发布新快照，保留30分钟参数任务完成证据，不更改实际落点。请求、回复、预算和提交指针见records/124_service_scope_20260921。连续实跑125另存证据，不能把此历史复核称为当前屏幕重识别。
- 实跑125完成2轮、5HTTP/2GUI并暂停，未重开Reminder验证Cancel；0330/a0063点击Bedtime mode，0332/a0064返回Clock。发现新范围缺口：round-0002/selection_window.json明确前台为com.google.android.apps.wellbeing，而0331把它登记成应用内区块；更新请求未披露动作后前台包名。当前已回Clock，外部误登记尚待纠正，此轮不能认定高效遍历整体完成。证据完整保留records/125_after_service_scope_20260921。

## 2026-09-21 更新步披露实际前台应用

- 动作后截图紧接着读取现有mCurrentFocus，保存after_window.json，并向更新步披露窗口、实际包名、与目标一致性；失败保持未知。异常提示解释完整其他应用页面与系统权限/键盘覆盖层的区别，不按包名机械判异常，不硬编码应用名称。
- 验证：`python -m pytest -q tests/test_stepwise_foreground_evidence.py tests/test_stepwise_review_fixes.py tests/test_region_registration.py --basetemp artifacts/tmp_tests/clock_goal_20260921/foreground-tests-ok`，32通过。最初验证命令误用不存在的test_stepwise_update.py，未执行测试；更正后上述测试通过，日志均保留。新增测试先缺少实现失败，再通过。
- 历史实图0334模型复核：使用0331原截图和实际返回前保存的Wellbeing窗口证据，正确给出external_app、空regions/controls，0GUI。records/126_foreground_scope_20260921保存完整过程。通过显式新快照纠正a0063结果、单步任务改record_only，移出0331产生的4个外部区块及关联导航边；返回后的0333观察不回滚，a0064原始回执和旧快照保留。此为历史证据复核，不冒称动作后新采样实测。后续实跑127单独验证新采样接线。
- 实跑127：0335/a0065点击Skip，新增after_window.json实际确认仍为Clock，0336更新正常进入Bedtime主页面；新采样接线已实机验证。共5HTTP/1GUI、3轮后主动暂停，无外部入口重试。另发现task_routing.advance仅len(interactive_regions)==1交接，新内容区+底部导航两区块时仍保留旧工作区，触发一次0GUI失败回溯并重新发现0337/0338、导航功能整理0339；此多区块交接效率缺口待修复，不能宣称遍历已高效完成。

## 2026-09-21 单步入口的多区块交接

- task_routing.advance不再要求恰好一个交互目的区块；来源退出、实际单步入口执行且无异常时，保留全部destination_regions，并优先选择未完成区块，再优先非导航区块继续。选择工作区不是证明唯一跳转，已有真实边不改写为唯一目的边。参数/滚动及准备动作继续原规则。
- 验证：`python -m pytest -q tests/test_stepwise_task_loop_handoff.py tests/test_stepwise_region_tasks.py tests/test_region_registration.py --basetemp artifacts/tmp_tests/clock_goal_20260921/multi-tests`，47通过。多区块用例修改前失败、修改后通过；同样覆盖参数不交接。
- 实际a0065证据重算选择r0022 Bedtime主页面内容，保留r0002导航同时可见的事实，0模型/0GUI；旧快照和失败回溯保留。当前已在发现步，只更正工作目标并清除过时导航目标，仍要求局部发现当前控件；未回滚旧观察。证据records/128_multi_handoff_20260921，续跑129独立保存。
- 129实跑已在目标Bedtime内容区局部发现0340、清点0341并点击新菜单a0066，未回旧引导；多区块交接续跑路径有效。0343菜单含8项，比原5项增加三个Hide入口，合理登记为不同菜单。但0344清点没有看到其他区块Screen saver的历史，0345/a0067再次点击屏保，0346更新后暂停。共7HTTP/2GUI。跨区块相似入口历史披露仍缺失，不能因本轮交接修复宣称已消除重复探索；原始证据见records/129_after_multi_handoff_20260921。

## 2026-09-21 跨区块同名入口历史披露

- 任务清点控件项新增“其他区块的同名入口历史”，来自已确认执行、无异常、直接目的区块的实际动作；携带来源区块描述和结果，不自动转移状态、动作或合并控件。重复相同描述去重，冲突结果保留供判断；无执行证据不披露为已知。
- 清点提示增加适用性规则及正反例：相同通用用途且无新语义可record；仅名字相同、不同对象或冲突结果不足以跳过。通用屏保与新增Hide项分开处理，不整体合并不同菜单。
- 验证：`python -m pytest -q tests/test_stepwise_entry_evidence.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/clock_goal_20260921/cross-entry-tests`，19通过；新增用例修改前缺少实现失败，修改后通过。历史菜单0344输入使用点击前快照重建为0347，0GUI、未发布当前图；完整请求与校验后记录见records/130_cross_entry_history_20260921。
- 0347返回Screen saver=record，明确参考旧菜单真实结果；Settings及三个Hide入口仍explore。未把历史重放替换到当前已执行过a0067的任务，避免抹掉真实重复动作。当前屏保完成状态保留，续跑131独立保存。
- 131实跑前三轮：0348/a0068返回Bedtime；视觉回溯0HTTP重新打开已知菜单；0350/a0069进入Clock Settings，0351确认前台SettingsActivity并结算入口。已结算4HTTP/3GUI（含视觉导航），尚在运行；没有再次点击Screen saver。新的同名跨区块跳过结论来自0347历史快照实验，不能把本次已完成Screen saver任务的跳过算作独立验证。后续Settings局部清点0352起另在同一run留证。

## 2026-09-21 同次动作结算关联参数目标

- 复用related_task_results，候选扩展为实际控件上同动作的单步/参数任务，披露任务类型和已有参数事实；点击/tap与输入按动作类别匹配，不把其他控件或当前主任务加入候选。更新输出每项附findings，历史单步回复仍可读取。
- 参数目标仅在模型明确报告完成证据、已有或新增参数事实充分且无异常时结算。沿用store_findings保留来源；所有项目先在副本校验后更新，失败不部分结算。关联记录引用原attempt，不新增GUI执行。
- 验证：`python -m pytest -q tests/test_stepwise_related_results.py tests/test_region_registration.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/clock_goal_20260921/related-param-tests-ok`，46通过。测试暴露无关联项、旧区块无tasks时的KeyError，已修为无项目不写任务；失败和通过日志均保留。
- 0368使用a0073原前后截图复核，明确返回样式菜单选择/切换任务的完成证据及条件事实；通过新快照只补关联任务与原动作a0073，不回滚当前0367观察，不重新点击。records/132_related_parameter_20260921保存请求/回复/指针，0GUI。续跑133另存实跑证据。
- 实跑133四轮后主动暂停（4HTTP/4GUI）。未重开Style；但“显示秒数”任务仍要求查看Clock主页面反馈。0369/a0075返回Bedtime后，框架两次0HTTP视觉回溯打开菜单、回Settings，0371/a0076又返回Bedtime，0372仍pending。新发现任务归属与验证路径冲突：工作区仍为Settings导致自动回溯抵消模型的跨区块核验意图。此循环尚待修复，不称本轮连续遍历完全成功；records/133_after_related_parameter_20260921保留证据。

## 2026-09-21 进行中的目标不被自动回溯到归属区块

- region_tasks.attach先识别进行中的任务，再决定是否沿视觉回溯返回工作区。已有attempt且pending的单步任务，以及参数/滚动续接任务，可在当前一个或多个交互区块继续选择动作；归属仍留在原区块，结算不转移。未开始的单步任务继续导航到入口，未改真实边与回溯投递校验。
- 当前候选合并可见区块控件，任务上下文说明归属不是返回指令；保留最近操作及结果，不生成新的目标字段或模型调用。
- 验证：`python -m pytest -q tests/test_stepwise_goal_context.py tests/test_stepwise_region_tasks.py tests/test_stepwise_resume_route.py tests/test_stepwise_task_loop_handoff.py --basetemp artifacts/tmp_tests/clock_goal_20260921/continuation-tests`，33通过。新增用例修改前失败、修改后通过；未启动任务仍返回原导航请求。
- 134真实图生成请求：任务仍属于Settings r0024，但实际动作来源为当前Bedtime，候选包含Clock和其他当前入口，navigation_advice/path均不提供自动回原区块指令。保存request.json/user.prompt；尚需后续实跑证明模型导航结果。
- 实跑135：0373/a0077直接选择当前底部Clock，0374确认进入Clock而非被自动带回Settings；任务仍挂原Settings，Analog页面没有数字秒数，因此结果保留pending，未虚报秒数效果。随后0376拟查看Clock菜单，名称改写导致0377纠错后投递；此名称绑定开销仍待处理。修复已验证跨区块动作路径，不宣称完整核验完成；135仍运行，证据独立保存。

## 2026-09-21 点击名称差异按唯一可靠图像定位绑定

- 普通click/tap/double_click/long_press在target非空但未逐字命中登记名称时，检查当前候选图像；仅可靠匹配且模型坐标落在唯一登记对象内才绑定。已有明确名称仍以其身份为准，不转绑另一个坐标对象；弱匹配、空白区域、多对象重叠继续拒绝。输入不使用这个名称兜底，投递前复核保留。
- 验证：`python -m pytest -q tests/test_stepwise_name_independent_binding.py tests/test_stepwise_resume_route.py tests/test_stepwise_screen_coordinates.py tests/test_stepwise_review_fixes.py --basetemp artifacts/tmp_tests/clock_goal_20260921/name-binding-tests`，16通过。更新旧“任意改写名称必须拒绝”的断言，同时保留空白点拒绝检查。
- 136保存历史回复原样回放：0363“时钟样式选项 Analog”直接绑定c0115，0模型/0GUI；0376菜单仍有两个登记对象同时符合，按歧义拒绝，未任意挑选。尚无新代码实机投递，原135冻结源不含本次改动。
- 135续跑0382再次准备从Settings返回核验秒数，已请求轮末暂停。检查请求确认跨区块尝试历史已完整披露，并非缺失历史；持续核验Analog秒数的策略仍有循环风险，需另修实际无进展处理。不能归因为模型没收到历史。

## 2026-09-21 重复导航核对与验证策略

- 发现原attempt_guard只检查前后画面相同的无效点击，不覆盖成功跳页但原任务仍未完成的重复固定入口。新增相同任务、入口、动作、起始画面、历史目的区块至少两次一致时的纠错诊断；由现有纠错流程改策略或defer，不自动登记成功。history_dependent/returns_to_previous及系统back不套用固定目的检查，避免把不同进入路径的返回误判循环。
- 动作手册补充“先区分已知事实与缺口”，优先能产生新证据的等待比较或有依据的新条件，避免只查看已知开关。没有添加应用名称规则。
- 验证：`python -m pytest -q tests/test_stepwise_navigation_cycle.py tests/test_stepwise_task_loop_handoff.py tests/test_stepwise_goal_context.py tests/test_stepwise_return_semantics.py --basetemp artifacts/tmp_tests/clock_goal_20260921/nav-cycle-tests-final`，21通过；人工构造的固定入口重复用例先失败后通过。137历史a0080返回回放不拦截；不是实机重复导航拦截验收。
- 更正此前135暂停时判断：最终0383已将显示秒数任务done，明确只确认开关切换和Analog界面反馈，数字秒数文本未验证；当前task无active_task。前两次返回Bedtime，a0080返回Clock，历史相关返回不应合并成同一固定循环。原始记录和早先result.json保留，137/return_replay.json记录修正后回放。后续从其他待办继续。

## 2026-09-21 区块完成不把来路当系统返回路径

- 完成分支优先继续实际工作目标，否则参考来源区块；调用已有_assemble_action_context提供真实已知有向路径，不再直接生成“退出当前区块回来源”的指令。无路径时仍由普通导航提示说明未知并让模型找路；已有失败返回且无其他路径继续原return_blocked行为。
- 验证：`python -m pytest -q tests/test_stepwise_goal_context.py tests/test_stepwise_region_tasks.py tests/test_stepwise_resume_route.py tests/test_stepwise_return_semantics.py --basetemp artifacts/tmp_tests/clock_goal_20260921/completion-route-tests`，32通过。测试最初夹具遗漏icon_description，补齐后旧行为断言失败、新行为通过，日志保留。
- 实跑138旧冻结代码0387误把Clock的来源Settings写成退出目标，a0081系统返回到了OpenTracks；0388正确识别外部前景并不登记业务区块。恢复流程0389–0394重新打开Clock并重新发现，最终暂停，11HTTP/5GUI。139生成真实当前请求仍先要求功能目录复核，故不能宣称已经发出了新导航请求；后续140实跑验证完成后的导航。
- 140实跑0399/a0082已实际点击Clock右上角菜单并成功展开，替代旧“退出Clock”指令；原图action_attempts/a0082/after.png。尚在运行，不声明已回到Settings。恢复后0395、0398再次整理功能目录，以及视觉回溯失配后0396/0397重定位产生额外开销；这部分仍需优化。

## 2026-09-21 导航交接目标与旧任务范围复核

- 140实跑a0082打开菜单后，自动回溯转模型导航丢失visual_navigation标记，任务附加器用菜单未开始的Send feedback任务覆盖前往Settings的目标，a0083误入反馈服务。保留navigation_advice目标；已有执行中的核验任务仍按原连续任务处理，不用路过区块的任务替换导航。
- 显式旧任务范围复核使用独立提示，要求逐项处理未完成任务；普通增量清点仍允许省略已有项。相同任务所属区块的后续前景观察由运行状态提供，避免仅凭较早权限弹窗结果判断范围。保留旧动作及原始回复，不伪造恢复成功。
- 验证：guiwalk-android Python运行tests/test_stepwise_goal_context.py、tests/test_stepwise_region_tasks.py、tests/test_stepwise_external_scope.py、tests/test_stepwise_resume_route.py，32通过；日志artifacts/tmp_tests/clock_goal_20260921/nav-scope-tests-final.log。141/0406遗漏复核，142/0407仅排除Help，143/0408结合后续观察排除Send feedback；均保存帧复核、0GUI。新导航行为实跑待144验证。
- 144实跑完成13HTTP/4GUI、5轮后监督暂停（进程已退出）：0409返回反馈页→0410确认Clock→0411/0412发现，0417/a0084打开菜单，视觉回溯进入Settings，再0420/a0085关闭Automatic home clock，0421登记Home time zone随之禁用及任务done。没有重试Screen saver/反馈入口。仍有开销缺口：0413与0416重复整理Clock功能目录；历史整屏样式变化触发自动回溯转发现。记录在records/144_after_navigation_scope_20260921；本轮验证导航目标和恢复连续性，不代表整体高效遍历完成。

## 2026-09-21 描述改写不触发功能目录重整

- 144的0413与0416功能请求仅区块描述措辞不同（加号入口/添加按钮）；任务、结果与属性相同。region_functions.signature移除观察描述，其余名称、控件身份、任务、结果、清点信息仍参与变化判定。不是忽略新的探索事实。
- 验证：tests/test_region_function_inventory.py、tests/test_stepwise_goal_context.py、tests/test_stepwise_region_tasks.py，41通过，日志artifacts/tmp_tests/clock_goal_20260921/function-description-final.log；新回归修改前失败。旧runner测试补全已有只读窗口查询的模拟，仍禁止GUI操作。真实functions-0413和discovery-0415快照在新算法下签名相等，0HTTP/0GUI、不改当前记录；见records/145_function_description_20260921。旧算法目录下次整理一次后沿新签名复用，不伪改历史签名。

## 2026-09-21 当前观察用于首步视觉回溯

- 已识别当前可交互来源区块及控件，且最新观察整屏仍与投递前帧一致时，复用当前观察作为来源依据；控件仍须按历史图像及相对位置唯一匹配。该检查复用于路径第一步及后续捷径，投递前再次核验；不放宽落点确认、不自动操作未识别背景入口。路径来源旧结果沿用现有路由认可的observed_effect语义，不伪补exception字段。
- 验证：tests/test_stepwise_navigation_shortcut.py、tests/test_stepwise_visual_backtrack.py、tests/test_stepwise_resume_route.py，25通过；日志artifacts/tmp_tests/clock_goal_20260921/fresh-nav-final2.log。新增首步测试修改前失败，覆盖缺少控件观察/画面变化拒绝。旧导航测试补齐interactive_regions状态。records/147_observed_navigation_20260921以144实际失败帧和当时0413快照匹配成功，依据current_observed_surface_and_control，0HTTP/0GUI，不改图；尚未实机投递该新分支。
- 146实跑9HTTP/4GUI、4轮后监督暂停，进程退出：a0086开启Automatic home clock用于解除Home time zone禁用，a0087打开时区列表，0426将同类选项登记为一个代表性选择任务及滚动任务（非逐项探索）。a0088向后滚动后，0429/a0089反向滚回，理由是补全GMT−5之前范围；0429上下文仅有最近范围及动作概述，未披露0426已登记GMT−11至GMT−5枚举。此处是新的任务事实披露缺口，待修复；完整记录在records/146_after_function_dedup_20260921。

## 2026-09-21 动作上下文披露已知参数事实

- task_action_context补充当前任务及当前可交互区块各任务已保存的findings（描述、domain、conditions），标明历史观察不代表完整范围；不披露其他不可见区块无关任务，不增加模型字段或假定观察完毕。后台context_evidence保留对应region/task/finding来源便于追溯。
- 验证：tests/test_stepwise_update_visibility.py、tests/test_stepwise_entry_evidence.py、tests/test_stepwise_goal_context.py，20通过，日志artifacts/tmp_tests/clock_goal_20260921/fact-context-final2.log。新披露测试修改前失败；旧runner模拟补齐只读前台查询。records/148_fact_context_20260921从真实a0088/0428快照生成上下文，包含首屏Midway/Hawaii及后续Greenland，0HTTP/0GUI，不改图。模型行为改善待后续实跑。
- 149实跑4HTTP/2GUI、2轮后监督暂停并确认进程退出：0431/a0090选择Pacific Time，0432观察设置值更新并结算子区块代表性选择任务；父参数任务却以未确认完整枚举保持pending，0433/a0091再次打开选择器，0434登记返回列表。补历史已接入真实动作请求，但不能据此宣称消除重复：同类列表滚动已有代表性终止规则，父参数任务的非穷举完成边界仍缺失，下一步需统一该规则。证据records/149_after_fact_context_20260921。

## 2026-09-21 参数调查的代表性完成边界

- 任务生成与结果核对统一：通用同类枚举任务确认选择方式、代表值反馈和适用条件即可done，保存已见值并说明未穷尽；不默认搜集全部名称。明确数值边界、不同交互类型或尚未取得的选择反馈仍需验证，不能套用提前结束。
- 验证：tests/test_stepwise_region_tasks.py、tests/test_region_function_inventory.py，33通过；日志artifacts/tmp_tests/clock_goal_20260921/parameter-boundary-tests.log。records/150_parameter_boundary_20260921重用a0090真实选择前后截图调用Luna0435，输出parameter done；框架仅以a0090证据结算所属参数任务，保留当前0434观察和全部实际动作，没有回滚UI位置，1HTTP/0GUI。

## 2026-09-21 设备级设置入口的范围线索

- 151实跑7HTTP/3GUI、3轮后暂停：a0092取消时区选择器，a0093打开Change date & time进入com.android.settings；0439正确external_app且不登记外部区块，0440返回、0441确认恢复Clock Settings、0442发现。旧任务生成漏掉设备级作用范围线索，未能避免这次外跳。
- 任务提示补充设备级时间/网络/权限/默认应用与应用对象局部配置的区别，按用途与说明判断，不按关键词拦截。records/152_device_scope_20260921使用首次Settings任务请求0352及旧截图，Luna0443将Change date & time=record，同时保留Style/Home time zone/Silence after/Snooze/volume探索，1HTTP/0GUI，不覆写当前图。测试tests/test_stepwise_external_scope.py通过，日志artifacts/tmp_tests/clock_goal_20260921/device-scope-tests.log。

## 2026-09-21 Settings连续参数实跑

- 153完成19HTTP/8GUI、8轮后监督暂停，进程已退出。a0094/95展开并选择Silence after=15 minutes，0448同时结算父子参数任务；a0096展开Snooze，a0097滚动一次，a0098选30 minutes，0455同时结算父子任务。未重开上述已完成选择器。
- a0099滚动Settings发现闹钟渐增音量、音量键、周起始日、计时器声音与计时器渐增音量，新增控件仍归r0024并区分两个同名渐增音量用途。a0100调低Alarm volume有明确滑块移动，但0460因缺少数值/范围/步进/音频判pending；a0101调高后0462以同类滑块位移证据判done并保留无数值/音频限制。两次核对完成标准不一致，多一次代表性调整；下一步应在生成/核对提示里明确无数值滑块的观察边界，不虚构数值范围。截图、调用与冻结源码均在records/153_after_device_scope_20260921对应run。

## 2026-09-21 无数值滑块的完成标准

- 任务生成/结果核对明确：无数值滑块的一次代表性调节取得可见位移即可完成该观察目标，精确范围、步进、音频效果作为未确认限制；不以坐标换算虚构参数，不替代明确数值/声音目标所需证据。
- 验证：records/154_slider_boundary_20260921复用a0100真实前后帧及0460动态材料，新固定提示下Luna0463输出done，范围/步进/声音保持未确认，schema和更新路由校验通过，1HTTP/0GUI且未提交当前图；git diff --check通过。本次仅提示改变，未重复无关运行测试。旧a0101及0462真实记录保留。

## 2026-09-21 更新步按当前动作披露历史

- run_task_step不再输出全部已知区块。update_step.known_regions保留来源、工作/任务所属、当前交互、最近路径区块，以及实际来源同控件历史去向和本帧视觉召回；仍对全图做底层视觉匹配/身份登记，不删除历史。previous_regions提示仅核对本轮相关候选，避免逐项列举全图not_visible。
- 验证：tests/test_stepwise_update_context_scope.py、tests/test_stepwise_update_visibility.py、tests/test_stepwise_region_tasks.py，22通过；日志artifacts/tmp_tests/clock_goal_20260921/update-context-final2.log。新测试修改前失败，覆盖无关控件去向排除。records/156_update_context_20260921对0481 Timer sound真实请求复算，28区块降至2，保留Settings和视觉召回Alarm sound；0HTTP/0GUI。实际模型及新分支续跑待157，不将离线缩减视为实时延迟改善。
- 155实跑21HTTP/8GUI、8轮后暂停，进程退出：闹钟渐增音量、Volume buttons、Start week on正常代表值选择并结算；0465重复同名单选组由0466一次纠正，无重复GUI。Timer sound正常打开应用内声音选择页，未闪退；后续结果保存在同一冻结运行目录。

## 2026-09-21 唯一约束名称由框架补全

- 0497功能整理回复仅写“时钟样式”，原校验要求完整任务/属性路径，触发0498额外纠错。region_functions.register现在在函数已声明的支持任务内按属性原名称查找；唯一时规范化为完整键，歧义/未知仍拒绝。保留原模型回复，不改变事实来源，不跨无关任务猜测。
- 验证：tests/test_region_function_inventory.py、tests/test_stepwise_goal_context.py，28通过（含唯一补全及同名歧义拒绝），日志artifacts/tmp_tests/clock_goal_20260921/constraint-name-final.log，新测试修改前失败。records/158_constraint_name_20260921复用0497原回复和0496实际快照，在内存登记成功、约束为完整键，0HTTP/0GUI、不改当前图；新分支尚未实时触发。

## 2026-09-21 返回语义只判断刚执行的动作

- 159实跑13HTTP/4GUI、5轮后监督暂停，进程退出：Settings完成后调度Timer sound，a0117导航进入，a0118打开菜单，a0119关闭；Send feedback/Help未点击。0512把打开菜单误报returns_to_previous=true，导致固定打开边被排除自动导航。原文已有关闭规则，但缺少“以后可关闭不等于本次返回”的方向对照。
- 更新手册及同字段schema说明统一补充打开false/关闭true的前后图例；不按控件名称硬编码。160保存帧Luna0516/0517分别重放0512打开、0515关闭，返回false/true，schema/路由校验通过，2HTTP/0GUI。独立派生快照只修正a0118返回标记和对应边，保留原0512回复、当前观察和任务。
- 验证：guiwalk-android Python运行`-m pytest -q tests/test_stepwise_return_semantics.py --basetemp artifacts/tmp_tests/clock_goal_20260921/return-direction-tests`，结果见records/160_return_direction_20260921/tests.log。本轮为真实保存帧复核，不是新GUI打开/关闭验收；连续遍历仍未完成。

## 2026-09-21 自有媒体导入的外跳线索

- 161实跑7HTTP/3GUI、3轮后暂停并确认进程退出：旧0482任务令a0120点击Add new进入DocumentsUI；0519记录external_app，0520/0521返回Clock并确认，0522重新发现，a0121仅选择一个Argon，0524以勾选变化结算代表性选择。没有探索文件列表。外跳真实事实及旧任务均保留。
- 任务手册补充从设备导入自有媒体可能使用系统选择器，因此无应用内流程证据时record；与应用内新建对象、选择已列出声音区分，不按Add new字样硬编码。
- 验证：162使用首次0482任务请求及原图，Luna0525将添加新声音record，同时设备声音代表性选择及滚动保持explore，1HTTP/0GUI且不提交历史回复到当前图。`python -m pytest -q tests/test_stepwise_external_scope.py --basetemp artifacts/tmp_tests/clock_goal_20260921/import-scope-tests`，6通过；日志及复核结果在records/162_import_scope_20260921。仅保存帧范围复测，新提示未来实跑效果继续观察。

## 2026-09-21 已有任务重定位不重复清点

- 163实跑8HTTP/3GUI、3轮后暂停，进程退出：a0122滚动一次同类声音列表即done；a0123滚回Argon准备已有预览任务；a0124点击预览图标后图标消失且选中保留，任务done，音频未确认。0530却把已有任务对象重新可见作为task_review_reason，额外触发0531任务清点；0533又把该任务的完成反馈作为重新清点原因。
- 更新手册与region_identity输出字段说明明确：本轮已有任务对象重新可见或待反馈不等于缺少任务；仅未覆盖的新操作方式才请求清点。未改校验或按名称忽略模型报告。
- 验证：164保存帧复核0530→Luna0534，task_review_reason为空且任务pending；0533→0535，review为空且任务done；两例均通过schema和更新路由校验，2HTTP/0GUI。仅移除当前0533这条有复核依据的多余review，独立派生快照保留所有动作、任务和UI观察，Timer sound登记任务完成。9项聚焦通过：`python -m pytest -q tests/test_stepwise_update_visibility.py tests/test_stepwise_region_recall.py --basetemp artifacts/tmp_tests/clock_goal_20260921/task-review-tests`；日志在records/164_task_review_20260921。新提示尚待后续真实连续运行验证，整体遍历未完成。

## 2026-09-21 父任务滚动同步核对来源区块滚动任务

- 165完成Timer sound功能整理后调度Home time zone的未完成滚动任务，a0125先返回Settings；3HTTP/1GUI、1轮后监督暂停。历史a0088/a0089已在该时区列表为父参数任务滚动，但related_task_results原来仅支持有控件的click/tap/input_text，来源区块滚动待办未被披露核对，形成无必要重访。
- 共用关联任务机制扩展到实际来源区块的scroll候选；更新提交传入真实dispatch动作，校验来源区块、无控件归属、任务类型和动作一致。仍由Luna逐项报告观察证据，不按存在任意滚动自动完成，其他控件任务不受影响。
- 验证：新增回归先失败（滚动候选为空）后通过；`python -m pytest -q tests/test_stepwise_related_results.py tests/test_stepwise_update_visibility.py tests/test_region_registration.py --basetemp artifacts/tmp_tests/clock_goal_20260921/related-scroll-green`，40通过，日志在records/166_related_scroll_20260921。真实a0088保存帧Luna0539复核确认后续同类结构、无新增入口，schema/路由/关联登记校验通过，1HTTP/0GUI；只发布这项滚动任务的结算，不改当前UI、其他任务或原动作回复。新分支未来现场执行仍待观察。

## 2026-09-21 未操作过的完整历史区块也可先清点

- 167调度无任务清单的Analog Clock小组件提示，a0126从Settings返回Clock后提示不在；视觉回溯未投递，0543/0544重新发现，0545提出滚动找提示但未执行。7HTTP/1GUI、3轮后监督暂停并确认进程退出。historical_inventory错误要求已有actions，排除了完整观察但从未点击的提示区块，导致先导航再判断是否需探索。
- 删除已有动作这个前提，复用原历史清点机制；仍要求最后观察controls_complete、可用截图、无登记缺口，既有清单沿原规则不重报。历史材料不改变当前定位，部分清单不能冒充完整。
- 验证：新增无历史动作/不完整观察对照回归，修改前失败；`python -m pytest -q tests/test_stepwise_historical_inventory.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/clock_goal_20260921/unacted-green`，19通过。168调用实际新机制，使用0374真实历史图，Luna0547将Try now按添加Home screen小组件的外跳线索record；1HTTP/0GUI，经原commit_plan登记且保持当前观察。无需新增针对应用名称规则或删除历史区块。新路径完整自动调度效果继续实跑，不宣称全图完成。

## 2026-09-21 发现阶段也退休已完成工作目标

- 168历史清点完成r0027后，运行状态仍为discover/locate_local_controls。169旧retire_completed_goal只接受explore，继续0548/0549定位已完成的提示；这不是提示任务未结算，而是调度阶段门槛遗漏。
- 完成目标退休及未完成区块选择允许discover；切目标时清除旧inspection_region/required_control并采用全局重定位，仍保持discover、当前观察未知及待观察帧，不凭旧位置执行动作。恢复/异常阶段不受影响，尚有执行中任务或功能整理未完成仍保留原门槛。
- 验证：新增真实快照结构回归修改前失败，修改后保留未知位置并切换到未完成区块；`python -m pytest -q tests/test_stepwise_external_scope.py tests/test_stepwise_deferral.py tests/test_stepwise_historical_inventory.py --basetemp artifacts/tmp_tests/clock_goal_20260921/completed-discovery-green`，31通过，日志records/170_completed_discovery_20260921。当前为离线调度验证，加载后的实跑另记。

## 2026-09-21 范围限制先于未知入口探索

- 171实跑5HTTP/2GUI、2轮后监督暂停：a0128打开Wake-up底部面板并交接为r0035，a0129打开唤醒时间选择器；0557正确保留父参数任务pending，尚未取得设置反馈。0555却无证据宣称Bedtime mode settings链接是应用内入口并派发点击，尚未执行该链接。
- 先补充设备模式/屏幕管理作用范围，172保存帧0558仍以“无执行记录”为由explore，失败记录保留。继而明确范围过滤优先于未知入口探索，不能因入口在应用内就认定目的地也在应用内；未加入名称分支。相同0555材料复测0559将系统模式链接record，同时时间、开关、星期保持explore，未扩大为跳过所有设置。
- 两次保存帧共2HTTP/0GUI；仅以0559范围依据将原链接任务改record_only，保留scope_history、当前时间选择器观察和其他待办，不宣称链接已执行或实际外跳。`python -m pytest -q tests/test_stepwise_external_scope.py --basetemp artifacts/tmp_tests/clock_goal_20260921/device-mode-scope`，7通过；静态diff检查通过。新范围提示实时泛化仍待继续观察，不将一次成功视为彻底解决。

## 2026-09-21 参数修改需要新值反馈

- 173完成0560时间选择器任务清点后，0561/a0130未修改07:15即点击OK；0562将父“时间选择与设置反馈”参数任务done，实际仅确认对话框关闭、原值保留。3HTTP/1GUI后暂停并确认进程退出；输入子任务仍待办，后续会产生重开。
- 动作目标手册与任务结果核对统一：需要验证修改且无对应历史证据时，先改一个有效代表值再按需确认；原值确认可以完成确认按钮单步任务，但不能证明参数修改生效。仅查看选项/取消任务不被强制修改。
- 174保存帧复核：0563对原0561请求选择input_text=08；0564对原0562前后图判父参数pending，并保留关联确认按钮完成。2HTTP/0GUI，更新schema/路由通过；仅派生修正父任务结算、恢复该待办，当前观察及真实确认动作保持。21项测试通过：`python -m pytest -q tests/test_stepwise_related_results.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/clock_goal_20260921/parameter-change`。日志与原始回复均保留，修正版实机输入待后续续跑。

## 2026-09-21 跨区块参数任务披露当前区块探索树

- 175实跑6HTTP/5个设备命令、3轮后监督暂停，进程退出。a0131重新打开时间选择器；a0132点击/全选/输入08，0568完成小时输入关联任务；a0133确认后0570观察面板8:15 AM，父参数done，验证实际修改反馈。尚未穷尽分钟、AM/PM及输入模式任务。
- 0569动作上下文在时间选择器内仍渲染父Wake-up面板任务树，遗漏当前可见编辑器的剩余任务，促使过早关闭再重访。region_tasks.attach现渲染当前interactive_regions的树，父目标/事实与任务归属保留；后台引用不进模型。动作提示允许先做同一编辑目标兼容且无额外导航的待办再提交，不强制绕做无关任务。
- 验证：新增上下文回归修改前失败，`python -m pytest -q tests/test_stepwise_goal_context.py tests/test_stepwise_region_tasks.py tests/test_stepwise_related_results.py --basetemp artifacts/tmp_tests/clock_goal_20260921/current-tree-green`，30通过。176用0568真实快照经同一render_current生成树替换0569原请求的父树，固定提示同步更新，Luna0571选择分钟input_text=30而非立即OK，1HTTP/0GUI、不登记假设动作；原框架直接attach的行为由回归覆盖。新选择策略尚待现场后续验证，旧a0133已实际确认不回滚。

## 2026-09-21 重复列表身份纠错

- 177实跑17HTTP/7GUI、7轮后监督暂停并退出：唤醒开关、星期、Sunrise Alarm、Sound选择Argon及返回、Vibrate均取得新反馈；0581纠错虽确认两个旧控件覆盖同一声音选择列表，却仅清空第二项list_group，留下重复身份。
- 纠错手册补充：同一列表同一操作的旧身份用已有merge_into迁移历史，同时修订提案只保留一个代表；不同操作误分组才清空list_group。用搜索结果列表举例，没有编码Clock名称或新接口。
- 原0581输入仅刷新固定提示，Luna0589提出合并“设备声音列表项”到“设备声音选项”且提交单一代表提案，1HTTP/0GUI。以已有control_records.merge发布独立快照，所有动作ID及当前观察保持；未重新登记旧0580动作后画面。证据records/179_duplicate_list_repair_20260921。
- 验证：`python -m pytest -q tests/test_stepwise_list_input.py tests/test_stepwise_diagnostics.py tests/test_stepwise_repair_scope.py --basetemp artifacts/tmp_tests/duplicate_list_20260921/merge`，21通过。额外shared_step_repair+repair_scope为11通过5失败；恢复原HEAD提示复验同样5失败，属于现有测试/实现不一致，未声称广泛回归通过。首次测试因临时父目录未创建而失败，随后创建目录再跑，原失败日志保留；后续运行前先建立basetemp父目录。

## 2026-09-21 回溯当前观察图片路径

- 180实跑5HTTP/1GUI、2轮：0590整理Wake-up功能后，自动回溯时间选择器未投递，0591/0592重新定位、0593/a0141打开时间选择器、0594更新后监督暂停。该入口用于继续未完成子任务，没有作为未知入口重验。
- 保存帧探针证实：当前8:15亮色时间与旧7:15、8:15灰色控件裁图均不匹配（分数0.24–0.27），所以这次需要Luna重定位，不能宣称路径修复能消除此调用。另查到visual_backtrack.shortcut_match把运行目录相对观察图片交给cwd读取；原相对路径匹配false，正确解析后同一保存帧true。
- 修正当前观察图按snapshot所属run解析；绝对路径保持原义，控件匹配、前景身份、当前控件清单及投递前再核验条件不变。
- 验证：新增相对路径测试修改前失败；`python -m pytest -q tests/test_stepwise_navigation_shortcut.py tests/test_stepwise_visual_backtrack.py --basetemp artifacts/tmp_tests/navigation_path_20260921/green`全部通过，具体数量见records/181_navigation_source_probe_20260921/tests.log。未声称新路径分支已实机命中；探针不执行GUI。

## 2026-09-21 输入框聚焦样式容忍

- 182实跑0595/a0142选择输入分钟30，执行器只点击便停止：所属对话框匹配成功0.86，控件因蓝色边框及光标新增降到0.78而拒绝，0596正确保留pending、text_delivered=false。2HTTP/1GUI，监督暂停并退出。
- input_target.locate沿用完整匹配优先；区块仍匹配但控件全图失败时，用控件中央一半内容再走现有图片匹配及相对位置检查。未降低全局阈值，未加入Clock字段名称，未放开未知页面直接输入。纯色/无足够边缘或内容改变仍不能作为匹配依据。
- 保存原a0142前后图回放：首次内缩15%仍失败，中央一半匹配通过，确认相同r0036/c0145。未修改原执行回执、未冒充曾输入成功。证据records/183_input_focus_20260921；replay.json为失败，replay-confirmed.json为最终通过。
- 验证：新增焦点边框变化正例修改前失败；不同内容反例保留。`python -m pytest -q tests/test_stepwise_input_target.py tests/test_stepwise_list_input.py --basetemp artifacts/tmp_tests/input_focus_20260921/confirmed`，17通过。当前设备分钟框已聚焦，随后实跑输入不能单独证明新焦点切换分支命中，需与保存帧验证区分。

## 2026-09-21 编辑值与保存值的证据位置

- 184实跑9HTTP/6GUI、4轮后监督暂停：a0143输入分钟30，0598完成；a0144切PM，0600完成；a0145转刻度盘，0602复用原区块；0603仅增加新分钟刻度盘任务；a0146点击25，0605完成，没有重建输入/AMPM任务。原分钟输入已聚焦，所以不将a0143冒称为新增焦点容忍分支实机命中。
- 0598的一个finding错误声称背景唤醒时间也变为08:30，实际背景仍8:15。更新提示增加数值变化必须对应实际控件/区域，编辑反馈不自动证明保存或背景摘要更新；输入反馈任务仍可完成，不增加保存要求。
- 原0598输入仅刷新固定提示，0606明确Minute从15变30、仅编辑框反馈，不再声称背景更新，status仍done。1HTTP/0GUI，Schema校验通过。用已有store_findings补正最新事实及task.result_evidence，保留旧观察、原始回复、任务状态/尝试和当前运行位置；同义事实名对齐原“分钟输入反馈”，没有重放旧更新。证据records/186_draft_value_evidence_20260921。

## 2026-09-21 功能整理补充后续动作证据

- 187实跑3HTTP/1GUI后监督暂停：0607整理时间编辑能力仍引用a0130“确认后7:15”早期任务，遗漏服务父任务的a0133“确认08:15后面板8:15”；0608/a0147取消当前08:25编辑，0609返回面板。取消属于导航退出，没有重做时间输入。
- region_functions动态上下文增加同区块、已完成/record任务控件上已执行且尚未被这些任务attempts覆盖的动作结果；不传未执行提案。补充结果纳入signature，有新证据才刷新，无额外证据时保留原签名形状。已有功能只披露名称供复用，不将旧completion/unconfirmed结论重新当证据；固定提示解释连续修改→确认回显可以合并理解，但不宣称持久保存。
- 当前图由框架生成三次Luna功能请求，均0GUI：0610补充动作仍保留旧疑问；0611仅补连续证据解释仍失败；0612去掉旧总结后正确登记编辑并确认、面板回显，持久化未确认。使用region_functions.commit原入口登记0612，没有人工重写模型结论。原请求/失败回复保留，证据records/188_function_action_context_20260921。
- 验证：新增后续同控件动作披露测试修改前失败；覆盖未投递排除、已被任务覆盖结果不重复、旧总结不污染请求及签名更新。`python -m pytest -q tests/test_region_function_inventory.py tests/test_stepwise_diagnostics.py --basetemp artifacts/tmp_tests/function_action_context_20260921/final`，31通过。后续自动调度仍需实跑观察。

## 2026-09-21 导航准备允许当前区块滚动

- 189实跑0613提出在Wake-up面板内向下拖动以露出Bedtime菜单，被bind_action_target以scroll outside routed task拒绝；0614纠错转none，额外发现后0617选择系统返回。问题是导航请求未设置allow_scroll/region_image，而普通区块任务已允许这种准备动作。
- _assemble_action_context导航分支补当前来源区块的图片、名称和allow_scroll，沿用原图片定位、双端点位于区块内及非零位移检查，来源仍为当前区块、working_region仍为目标区块。导航提示解释寻找入口/收起面板可用scroll，不必先建滚动任务。没有编码面板名称、方向或坐标。
- 验证：新导航滚动正例在改前unresolved，改后matched，越界仍拒绝；`python -m pytest -q tests/test_stepwise_resume_route.py tests/test_stepwise_navigation_shortcut.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/navigation_scroll_20260921/green`，33通过。原0613图和知识快照由框架重组请求，绑定r0035、目标r0023通过，0HTTP/0GUI；这不是已实际执行拖动。证据records/190_navigation_scroll_20260921。首次测试误用了不存在的bind_action，改为真实bind_action_target后才确认红绿结果，日志分别保留。

## 2026-09-21 权限提示不应阻塞单步入口结算

- 191实跑7HTTP/3GUI后stopped：已知菜单视觉回放0HTTP/1GUI；a0149隐藏近期活动、0620完成并登记新事件卡片；0621清点、a0150点击Continue后出现系统日历权限提示。0623正确报blocking_popup且单步入口done，被旧settle_task拒绝；0624为通过校验改成none；0625恢复又因授权选择stop。原证据保留。
- 任务结算允许来源/控件与任务相符、非准备动作、确已执行的single_action在blocking_popup下done；参数任务/准备动作/其他异常仍不套用。异常保持blocking_popup独立进入恢复，不要求伪写none。任务提示同步澄清“任务目标依赖的异常”和入口直接结果。
- 恢复提示明确：无必须授予的新权限请求，优先明确拒绝/暂不/取消以继续遍历，不擅自Allow，不撤销已有权限；无法确认拒绝影响时保留stop。
- 30项相关测试通过（tests/test_stepwise_region_tasks.py、tests/test_stepwise_external_scope.py、tests/test_recovery_discovery.py，basetemp artifacts/tmp_tests/permission_recovery_20260921/green）。原0625截图仅刷新固定提示，0626选择Don’t allow，1HTTP/0GUI。原0623由commit_update重新接受，入口done、异常blocking_popup、mode=recover，区块/动作ID集合不变，旧0624及停止episode保留。证据records/192_permission_recovery_20260921。实际拒绝与恢复效果待下一实跑确认。

## 2026-09-21 导航控件登记与探索任务分开
- 实跑193的0634将Sleep sounds返回箭头作为“导航”排除；0647正常选择该箭头却不能绑定，0648额外纠错改用系统Back，0649确认回到Bedtime。193已暂停并确认进程退出，共23HTTP/8GUI。
- 修改发现/更新共同使用的发现手册/交互控件范围.prompt：应用内可见返回、关闭、取消仍登记；是否需要试点交给既有任务清点，纯返回仅record；系统导航不虚构为应用控件。不增加动作或数据字段。
- 验证：原0634请求保存帧重测0651登记返回箭头，0GUI、不发布图。0650是在确认活动模板前进行的原提示重测，也登记了箭头；因此仅证明新提示本例可用，不能宣称统计改善或旧提示必然失败。两次共2HTTP，证据records/195_navigation_control_registration_20260921。
- 邻接离线检查：python -m pytest -q tests/test_region_registration.py tests/test_stepwise_region_tasks.py --basetemp artifacts/tmp_tests/navigation_registration_20260921/pytest，41通过。尚未在新现场独立验证返回控件绑定闭环。

## 2026-09-21 功能摘要不再混入已完成任务的最初动机
- 196实跑0666将任务最初“菜单尚未观察”的reason误写进最新功能角色说明，虽然同条已有完成证据。region_functions.request删除重复的“说明”投影，继续提供result_evidence；record_only无完成结果时保留其限制理由。底层任务及历史不改写。
- 新测试先复现旧动机泄漏，再验证结果依据优先、记录用途的限制不丢及输入记录不变。首次绿轮测试夹具把status改为record_only但漏改handling，修正夹具后运行 tests/test_region_function_inventory.py tests/test_stepwise_diagnostics.py，32通过；日志artifacts/tmp_tests/function_completed_evidence_20260921/confirmed.log。
- 从原0666前task-plan-0665快照由框架重建请求，0669未再声称菜单未观察；1HTTP/0GUI、未发布目录，证据records/197_function_result_evidence_20260921。仍缺重新进入区块的相关历史披露；0669仍将离开后保留选择写作未确认，不能宣称这部分已解决。
- 196已暂停、进程退出：17HTTP/6GUI。0664复用声音选择区并补返回箭头，0665仅为新增箭头record，0667/a0163直接绑定执行返回播放器，0668登记成功，无纠错；实际导航控件修正闭环见同run导航监视记录。

## 2026-09-21 功能摘要披露已有入边结果
- region_functions从reached_by关联来源区块actions，提供已执行且无异常的进入结果、证据和来源名称；不新建跳转，不把当前选中自动推断为持久化。重复相同结果去重；自己区块内动作仍使用既有结果通道。请求、摘要新鲜度、提交校验均使用同一入边投影，发现收尾、历史整理和纠错重建同步传入records。
- 发现新增重访证据时允许重新整理能力；没有新增结果不因截图措辞变化重调。提示要求分开已经验证的重访回显和未验证的重启/其他环境，不复述过时未知。
- 测试新用例先失败，再通过真实入边披露、未投递排除及签名刷新检查。聚焦 tests/test_region_function_inventory.py tests/test_stepwise_diagnostics.py tests/test_stepwise_historical_inventory.py tests/test_stepwise_task_loop_handoff.py 45通过；py_compile通过。日志artifacts/tmp_tests/function_revisit_20260921/confirmed.log。首次命令误写历史测试文件名未运行测试，已更正并留日志。
- 原0666前快照框架重建：0670引用了入边却仍在unconfirmed捆绑“离开/重启”；补清条件边界后0671正确说明从播放器重访仍选中，仅保留重启/跨环境等未验证条件。共2HTTP/0GUI，未发布历史快照，records/198_function_revisit_evidence_20260921。连续实机由后续独立run验证。

## 2026-09-22 显式共享控件行为关系
- shared_controls.py提供显式link/view/refresh/disclose，规范记录存在首成员region.json的shared_controls，成员持有shared_control_ref。只共享已执行动作的行为证据；本地观察、图像、任务完成、动作、跳转不传播。同控件观察仍沿用原identity，不把跨区共享等同于合并。
- 所有现有记录发布入口中的增量发布/动作更新刷新规范结果；任务清点与动作探索树披露共享关系。不同目的地/异常/缺失成员标needs_review并保留证据，不能由同名自动关联或自动授予本地完成。
- 57项聚焦离线通过：tests/test_stepwise_shared_controls.py tests/test_stepwise_entry_evidence.py tests/test_region_registration.py tests/test_stepwise_region_tasks.py tests/test_stepwise_task_loop_handoff.py；日志artifacts/tmp_tests/shared_controls_20260922/final.log。新测试覆盖单一存储、结果更新共享、状态隔离、任务不复制、冲突、未执行拒绝及同区观察不冒充跨区关系。
- records/200_shared_controls_20260922/register_links.py基于a0005/a0067真实同目的地证据，监督显式关联r0003.c0008与r0023.c0095，发布shared-controls-menu-20260922独立快照；所有原任务/动作结果/跳转及a0165待更新停点未变。0HTTP/0GUI。真实样例与生成上下文在该目录。不是Luna自动关系判定，也未解决服务拒绝或Hide/Show自动对应。
- 当前物理设计、接口及未覆盖范围见SHARED_CONTROLS.md。

## 2026-09-22：服务失败后的纠错分支切换

模型服务错误不再只能重试原步骤：有明确HTTP错误证据时，调用一次专用纠错手册选择独立区块，暂挂未完成更新并回发现步。旧动作不得重投或伪结算。候选还排除该入口已验证目的，避免换名后仍留在失败分支。合同与测试边界见 `BRANCH_SWITCH.md`。

2026-09-22 补充：整支切换限制为有回执的模型服务错误或框架检测的三次无进展循环。每轮自动检测短路径循环后调用纠错，普通首次失败/返回/参数变化不触发。请求与登记双向核验证据；35项离线聚焦测试通过，本次无实机调用。详见 BRANCH_SWITCH.md。

## 2026-09-22：前景挡住目标时交给正常导航动作

修正发现流程中的调度绕圈：重定位已经确认可交互前景、目标不在其中、且没有已知点击路线或下一步是系统返回时，直接进入原动作导航，不再强制清点前景全部控件。局部前景识别完成后也保留这个导航优先级；不先给遮挡区块生成业务探索任务。已知路线需要点击时仍先定位控件。

动作导航手册增加关闭菜单/面板的正反例；系统返回无需控件图或预先登记返回任务，点击关闭键仍遵守定位规则。框架不硬编码菜单名称/坐标，不自动认定关闭成功，原工作任务保留，实际结果进入更新步。

29项聚焦离线测试通过：`tests/test_local_region_discovery.py tests/test_recovery_discovery.py tests/test_stepwise_resume_route.py tests/test_stepwise_task_loop_handoff.py`；命令/结果日志 `artifacts/tmp_tests/foreground_navigation_20260922/green.log`。实跑单独保存在 records/206_foreground_navigation_20260922，运行结果另记。

实机局部结果：0696完成当前菜单识别；0697由Luna自行提出back，a0167实际回执成功，动作后截图确认菜单关闭并露出Alarm内容。没有监督者代按返回。结果更新仍在运行时，不能仅凭本记录宣称整轮或闹钟探索完成；持续状态见 records/206 的session账本。

## 2026-09-22：统一历史披露及Alarm误归属修复

历史选择、来源投影、文字表达集中到history_context.py；旧接口保留薄适配。去除同屏无关任务属性，结构化入口结算改为历史语气，更新身份候选明确纳入原因及非当前状态。局部匹配先核对已知独立目的区块是否覆盖目标，命中则重新分区，避免后台区块吞入菜单控件。合同、边界与数据修复说明见HISTORY_CONTEXT.md；旧证据不覆写。

## 2026-09-22：陌生读者复审后的四项一致性修复

- controls_complete说明与实际API必填schema对齐，删去“省略也按false”；旧账本读取/离线兼容没有新增拒绝条件。
- 共用`共享/参数观察值.prompt`定义values为四种类型均可记录的已见字符串值，不等于完整范围/输入成功/保存成功。任务清点与结果核对同时引用；旧观察不改写。
- record不是统一禁止操作：纯关闭/返回服务可用于必要导航；应用外、对外发送、破坏性禁止试探规则保留。
- 重复组诊断直接读取`发现手册/列表代表项.prompt`，统一一组一控件、整组可见范围、探索时选择代表值，不再另写“其余excluded”歧义规则。

验证：28项聚焦测试通过，日志artifacts/tmp_tests/prompt_review_fix_20260922/final3.log；三Python模块语法检查通过。五类保存输入通过现有构造器/固定片段重组，保留原实际API schema和截图，位于records/212_revised_prompt_review_20260922；无新增GUI或模型调用。陌生读者代理仅看重组prompt/schema/真实截图，结论另存同目录FRESH_REVIEW.md。当前210持续运行使用其冻结旧版本，本次改动没有热替换它。

复审结果：五份当前实例未发现确定阻塞，四类修订规则均可理解且与本次schema相容。仍有更新任务“修改反馈”是否包含保存反馈的目标歧义、当前未触发的focus_presence空值说明分支差异、equivalent_to空字符串说明缺口、旧纠错历史建议优先级说明缺口；本轮未宣称这些已解决。完整逐项证据见上述FRESH_REVIEW.md。

## 2026-09-22：复审剩余四项修补

更新目标加入图中已有result_evidence，任务提出明确编辑/保存反馈边界；更新说明历史判断如何核对，不能把编辑器新值当原对象已保存。发现手册明确focus_presence随本轮schema裁剪（原实现无定位时已使用null schema）；任务清点说明非equivalent时equivalent_to为空字符串；纠错历史保留原文但不是本轮规则。

31项聚焦测试通过，日志artifacts/tmp_tests/prompt_followup_20260922/green.log；history_context.py/run_task_step.py语法检查通过。复审使用213目录五类重组请求及原截图，更新目标来自动作前不可变快照，不是手工填充。未改变当前运行或历史记录，无新增模型/GUI操作。陌生读者结果见同目录FRESH_REVIEW.md。

213陌生读者结论：五份输入均可形成合法、有据回复，未见现行规则/schema硬冲突；独立将主时间任务判pending，依据是编辑器变化不等于保存后卡片反馈。复审还指出旧关联小时任务“指针更新”目标仍有歧义，只能登记实际小时字段变化及转分钟盘，不能虚构小时指针帧；本轮不改写旧任务/被拒提案，也未将这些历史内容误报成新prompt冲突。

## 2026-09-22：按调查目的定义最小结束条件

共用共享/任务结束条件.prompt接入任务清点、动作选择、结果更新。reason明确未知问题及足够观察；入口去向、选项调查、实际效果验证区分，parameter不再默认要求改值。当前已知事实可record；目的区块任务不延长父入口。删去任务/结果手册中枚举调查一律代表选择的措辞。没有新增任务字段、动作或无动作完成协议；动作建议仍不直接写完成，正常流程由打开后的更新结算。既有done/旧任务原文不批量改写。

22项聚焦测试通过（artifacts/tmp_tests/task_end_20260922/green2.log），包含只观察选项即可由既有settle_task完成parameter任务；两模块语法检查通过。测试首次临时目录缺失及一次误填测试文件名均保留日志，之后更正通过。保存帧模型验证见records/215_task_end_probe_20260922，模型结果另记，不冒充新GUI轨迹。

215保存帧实模型：5HTTP/0GUI。0001自然提出只查看选项、不切换保存的parameter任务；0002/0003测试样例名称不一致，不计端到端通过。修正样例后0004只查看选项done、0005明确切换目标pending，均经既有settle_task内存结算接受，schema通过。未改真实图、未验证持续实跑。

## 2026-09-22：空图首次发现的null合同闭环
216新Clock首次发现0001按发送schema输出focus_presence=null，却被commit和registration_diagnostics各自重建的string schema拒绝，纠错0002/0003受原null schema约束无法修复，0探索GUI后停止。schema工厂现在统一接收focus_present，发送、commit、聚合诊断使用相同条件；不是让模型猜一个不存在的定位区块。17项聚焦测试通过，含create_run空图→请求→原提交→登记的贯穿用例，日志artifacts/tmp_tests/empty_discovery_20260922/green2.log。Clock旧失败保留；用户改为先跑OSWorld Settings，未恢复Clock。

## 2026-09-22：OSWorld Settings同流程接入
平台适配与边界见DESKTOP_EXECUTION.md。公共动作说明不再宣称所有运行都为Android；桌面prompt说明Esc/滚轮/替换输入及目标范围，Settings自身系统项不按第三方应用的设备设置外跳规则跳过。30项聚焦离线测试及语法检查通过。217首次全局发现已按null合同成功登记，后续实跑状态单独留存。

217桌面实机：首三轮均updated，a0001搜索入口出现输入框并登记；运行继续，非全图完成。发现VM缺xdotool，窗口归属原样未知；当前源码改用已存在的xprop，独立实机读回Settings归属，运行冻结版未热替换。最终30项测试通过，记录final.log及window_probe_fixed.json。
