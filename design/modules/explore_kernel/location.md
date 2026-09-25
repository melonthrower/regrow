# 位置与页面状态

2026-09-17 a8落点修正：原State审核角色只看最新完整截图，历史Region/控件清单供逐区对照，不再把历史图片与当前图片同时供给以免串图。审核增加region_checks（逐区present/absent/uncertain及当前可见控件）；same缺少完整证据或有缺失区块时进入原主Agent纠正。可复用另一个确有依据的已知State，不强制new_state。图片相同也不证明旧标注正确，只有同一图/候选的已通过审核可使用原缓存。a8保存帧已由Luna纠正s6→s5并经原生结算；真实续跑结果见本轮ASTRA_REVIEW。

`state_review.py` 对拟复用的已清点State沿用modular_region_identity角色核对最新完整图与历史Region/控件组成；不新增模型或外部服务。same且逐区证据完整才允许继续位置绑定，different/uncertain、证据冲突或无效回复进入既有主Agent纠错预算，不先发布位置或执行动作。新State、未完成清点的State不调用该已知复用审核；图片相同不跳过身份审核，同图/候选已有成功审核仍可缓存。旧代表图用于证据来源与缓存标识，缺失时沿用原错误处理，不自动信任历史编号。无review_known_state接口的非模型客户端仍走结构协议，不记视觉通过；内置模型均提供接口。

单纯输入值、时间、选中、同质成员或滚动视口变化允许复用；新独立功能/详情或前景组织变化应重新登记State并保留真正共享的Region。原State代表截图/摘要与历史Element观察不改写，当前Region描述可以记录新值；不能把旧Element观察当作当前值。核验事件带旧新截图来源。不自动从审核结果创建State、搬移owner或生成动作边。当前模型效果正在保存帧验证，不能仅据单测宣称准确。

2026-09-09：`validate_state_composition`同时用于恢复确认和无pending动作的已知State变更。
没有动作不能只凭新编号覆盖已确认位置，必须按最新图给出目标已完成State的完整Region引用组合；
拒绝事件保留旧/新State引用，反馈明确历史任务来源不是当前位置。有完整确认的自然变化仍可接受，且不造动作边。

2026-09-09恢复边界：仅确认一个目标Region不足以复用整个已完成State。runtime在bind_screen前检查本次Region清单
是否声明其完整引用组合；不满足时提供精确反馈，允许改为new_state来保留局部恢复。该检查不分析像素，不能代替真实视觉身份判断。

## 问题

每轮先回答两件事：当前画面是否仍属于目标应用；若属于，它是哪个稳定功能页面和哪个会改变后续操作的状态。
页面身份错误会污染后续全部区块、操作和图边，因此本模块先于页面清点运行。

## 输入和输出

- `scope.py` 读取 Android 前台任务归属或本次桌面运行绑定的窗口归属，只返回 `target / external / unknown`。
- `unknown` 会进入主 Agent 当前轮的状态栏，由主 Agent根据截图判断；不会因最近动作类型硬放行。
- `external` 由框架恢复目标应用，恢复过程不写页面和图边。Android 先返回一次以保留原界面，失败才重新唤起；
  有待结算动作时先让主 Agent观察外部画面并保存真实结果。
- `location.py` 接受主 Agent 的 `new_page / new_state / known / uncertain`。`new_page` 不带任何引用，
  `new_state` 只引用已有 Page，`known` 引用已有 Page 和 State；持久编号只由框架分配。
  若模型把已有 Page/State 的精确编号与 `new_page/new_state` 枚举误配，位置模块优先复用这组精确命中的引用，
  不为枚举格式问题重复调用模型；引用未命中时才按 `new_page/new_state` 新建。这里不按名称或截图做模糊猜测。
  若模型把已知 State 配给错误 Page，纠正会同时给出该 State 的真实 Page 编号和名称，不要求模型自行从长图中反查。
  `new_page` 的规范化名称若与任一已登记 Page 精确相同，位置模块不会凭名称自动合并，也不会再创建同名 Page；
  它会列出冲突的精确编号，要求主 Agent改用 `known`，或为确实不同的主要功能目的地给出可稳定区分的名称。
  这里只拦截精确同名，不做模糊语义匹配。

主要功能目的地是 Page 边界：顶层导航切换到另一主要功能时登记新 Page。同一功能内部打开添加或设置对话框、
弹层、选择器仍属于原 Page；State 只用于这类操作集或功能组织发生变化的情况。

真实动作落地后，查看最新完整截图的主 Agent 直接提交 Page/State 报告。位置绑定仍校验结构、已知引用和State归属；拟复用已清点State时先走上述图像核验，不调用只看文字的Page Resolver。
新 Region 的稳定身份仍由 Region Reviewer 使用当前和候选完整截图复核。

位置绑定返回临时 ledger。runtime 只有在本轮动作回执和已提交清单通过必要检查后才发布该位置；
报告被拒绝时不保存临时 Page/State。合法的不完整清单仍可写入并保留 survey 待办。
位置无法确定时重新取得 observation；若模型请求 wait，沿用已有等待时长后取新图。已有 pending
保持同一 Attempt，不重复原 GUI 动作，也不把真实 uncertain 当作合同错误累计两次即失败。
持续不确定仍由原 model_turn_limit 以 partial/gap 收尾，取图失败沿用 screenshot_unavailable。

同一页面的滚动位置、焦点、悬停、时间和普通数值变化不建立新状态；只有后续可执行操作集合或功能组织实质变化时，
才在已有 Page 下登记新 State。

首次画面之外，新 Page 必须来自上一轮已真实投递动作后的截图。新 State 通常也遵循这一规则；但同一 Page
若因加载完成、异步结果到达等原因自然出现新的可见功能结构，主 Agent 可直接提交该新 State 的完整清单，
不受框架是否已经切换到下一个任务影响。
这条例外必须伴随本轮真实创建的新 State；`known` 精确命中当前 State 时，即使同时重报 `page_report`，
也只是当前清单更新，不构成旧 State 被替代。
操作任务期间无动作地提前报告预期 State，或无动作地报告另一个 Page，框架仍拒绝写账；精确命中已有编号的枚举误写不受影响。

已知 State 的有效增量清单直接进入 Region/Element 的既有审核与登记，不再用名称、摘要或操作文字的
相似度要求主 Agent重判 State，也不因当前是操作任务而提前丢弃清单。是否需要新 State 由看图的主 Agent
判断；框架只校验引用与归属，不用文字分数代替视觉判断。真正没有新增或修改事实的空转仍会收到进展提示。

## 当前限制

2026-09-09：Settings a17 曾仅恢复主导航但保留应用详情，却被错认成 Background。现在已知候选
包含原内容摘要，通用 Prompt要求核对当前内容与 State/Region组合；内容仍在不能因导航切换报消失，
新的功能组合使用新 State。原保存帧主回复已正确识别该新 State并保留详情；单次回复不证明完整runtime接受。
代码仍只验证引用，不新增名称分类器、图像阈值或额外位置模型。多应用视觉误认仍需实机监督与反例检查。

Page 语义仍由主 Agent 提供，可能出现误分或重复；它只用于组织和理解，不应代替 Region 身份与真实动作证据。

## Resume 定位

`--modular-explore --resume <exploration_ledger.json>` 不相信 checkpoint 中的
`current_page_id/current_state_id`。旧ledger加载后一律清空旧位置；加载本身不要求旧截图存在，但随后显式复用已清点State时需要上述代表图核验。
恢复不再先选 Page 或 State：
主 Agent 只需按最新截图报告目标或路线起点的当前可交互 Region 与操作，Page/State 仍作账本组织。
不要求先重新完整清点；其余内容未检查时保留 survey_complete=false。新 Region 候选不按同 Page 优先，
明确引用的旧 Region 不受文字筛选限制，由现有 Region Reviewer 对完整截图复核。
当前目标 binding 或已验证 Region 路线已经明确时即可继续原操作任务；未清点部分保留原调查任务，不假记完成。
没有确认可用目标或路线起点时继续补充当前区块，或通过已有恢复动作取得可用界面。
空 owner 的非滚动恢复动作不要求先交清单；pending 结果先正常结算，再继续区块定位，避免恢复也被清点门禁卡住。

上述定位只在 `ScopeGuard.check()==target` 后运行。若初始前景为 external/unknown，runtime 先调用一次现有
`ScopeGuard.recover()` 并使用恢复后的 fresh observation；再次检查仍非 target 时返回 `resume_scope_unresolved`，不读取
ledger 候选图、不调用 Region Reviewer，也不写 checkpoint。

当前 Region-first resume 只有离线合同验证。它能从一个新登记 State 的已复用 Region/local binding
计算已验证 Region 路线，但尚未在重启容器后的真实 Luna/API 续跑中验收。

## 2026-09-08 反馈检查

新增 State 使用不存在 page_ref 时明确区分复制已有 Page 与 new_page，不编造编号。 逐项清单见 [反馈检查](feedback_review_20260908.md)。218项相关离线检查通过，实机效果另行验证。
