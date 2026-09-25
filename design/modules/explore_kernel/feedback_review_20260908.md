# Region 遍历报错逐项检查（2026-09-08）

> 历史静态检查：以下数量和源码片段对应 f6c67048，不是当前纠正链路已验证的证明。后续真实运行暴露了错误接收角色和重试问题，现行实现与离线证据见 [报告纠正流程](report_correction_flow.md)。

## 结论与边界

当前模块化 Region 内核共检查 259 处显式 raise、issue、非空 correction 和动作校验返回位置。
这个数量包含重复转发及旧兼容分支，不代表259种独立故障，也不代表所有分支都做过真实GUI验证。
范围为 `gui_rewalk/src/core/explore/*.py` 当前主链；旧 autonomous/guided、采集流水线及第三方库源码不混入本次修改。
外部 API、环境和文件系统异常只保留可观察的异常类型/状态/文件位置，不能由框架臆断底层原因。

## 已实施

- 当前纠正存在时不展示旧 task.strategy 为“当前思路”；格式重答也去掉这行，账本历史不删除。
- 38处必填文本检查带字段名；清单及完成动作字段带数组位置；非法枚举带收到值与允许值。
- 已有 SettlementContractError 转为文本时保留 field_path/expected/received，不增加协议字段。
- 动作拒绝注明本轮动作未执行；清单拒绝注明本轮未接受；同轮清单已保存的反馈保留到下轮。
- 纠正不再要求主Agent输出已退役的 purpose、内部 operation_ref 或 current_task_result，不再建议为修正报告重做真实动作。
- Region效果错误给出具体行、ref/index冲突、动作前后存在性；因果不确定仍由Luna判断。
- 身份审核错误带候选/操作对编号；审核应用后重复el明确不证明两个按钮相同，不诱导合并独立按钮。
- 存档无可恢复配对时给出各候选的摘要、末次动作或环境快照不匹配原因，不伪造可恢复状态。

## 不能凭代码补出的信息

1. 坐标实际指向哪个按钮：编号绑定合法不证明视觉落点正确。需要现有视觉监督提供具体反证，不按按钮名/坐标硬编码。
2. 两个区块语义上是否同一组件、变化是否由动作引发：Reviewer可返回uncertain；代码只校验引用与证据边界。
3. 未分类异常的具体错误子字段：保留原异常并明确无法定位，不能把猜测字段当成纠正结论。
4. API无正文、系统前景查询失败、存档损坏等外部问题：Luna无法修复服务、驱动或磁盘，不能要求它重写GUI事实来通过。

## 本次 Settings 的具体监督纠正

该实验动态反馈应明确：Default Applications 是 el322/co24，Applications 是 el336/co9，两者为独立导航按钮；
此前坐标指向后者却引用前者，点击未执行。若继续寻找前者，按最新截图滚动 r1，next_operation_ref 留空。
这些名称/ref只属于保存截图与该账本的现场证据，不进入通用Prompt或代码规则。

## 验证

离线：10个直接相关测试文件共218 passed in 3.81s；续测恢复修正的47项检查通过（1.66s），覆盖解析字段、实际下一轮输入、动作绑定、清单事务、身份/因果、任务和存档。
未运行全框架发布门禁、第三方故障注入或穷举GUI测试。实机效果必须由本次提交后续跑单独验证。

## 逐项位置

“补充”表示本轮修改了该位置；“保留”表示条件/类型/字段本身可定位，或属于保留原异常的转发/内部检查。
对于不能确定语义的错误，准确反馈是承认未知并保留证据，不是给出猜测的按钮答案。
行号为本次修改后的工作区位置；函数名为稳定查找入口。

### actions.py

主Agent动作纠正；primitive异常交运行维护。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| validate_for_platform:30 | 补充（action_guard） | `f'action.kind={action.kind}：当前 Android 执行器不支持该动作；请根据截图选择支持的 click/long_press/scroll/back 等动作，不能直接套用桌面交互。'` |
| validate_for_platform:33 | 保留（action_guard） | `'桌面端 long_press 应改用 right_click 或普通 click'` |
| validate_for_platform:35 | 补充（action_guard） | `f'action.owner_ref={action.owner_ref!r} 未解析出执行绑定；请复制当前实际控件或区块的 owner_ref；新控件先补清单，不要手填内部 purpose/operation_ref。'` |
| to_primitive:72 | 补充（raise） | `ValueError(f'action.point_1000: {action.kind} requires a point；请填写最新整屏 0..1000 尺度的 [x,y]。')` |
| to_primitive:100 | 保留（raise） | `ValueError(f'unsupported action kind: {action.kind}')` |

### agent.py

格式错进既有重答；API/角色错误交运行维护。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _call:215 | 保留（raise） | `ValueError('模型回复不是一个有效 JSON 对象')` |
| decide:255 | 保留（raise） | `ValueError(error or '主 Agent 两次回复都不符合合同')` |
| _call:364 | 保留（raise） | `ValueError(f'unsupported modular Codex role: {role}')` |
| invoke_specialist:472 | 保留（raise） | `RuntimeError('Responses API request failed: ' + type(exc).__name__)` |
| invoke_specialist:476 | 保留（raise） | `RuntimeError('Responses API request failed')` |
| invoke_specialist:480 | 保留（raise） | `RuntimeError(f'Responses API request failed: HTTP {response.status_code}')` |
| invoke_specialist:486 | 保留（raise） | `RuntimeError('Responses API returned invalid JSON')` |
| invoke_specialist:488 | 保留（raise） | `RuntimeError('Responses API returned an invalid response object')` |
| invoke_specialist:502 | 保留（raise） | `RuntimeError('Responses API response has no output_text')` |
| invoke_specialist:506 | 保留（raise） | `RuntimeError('Responses API output_text is not valid JSON')` |
| invoke_specialist:508 | 保留（raise） | `RuntimeError('Responses API output_text is not a JSON object')` |

### api_config.py

启动者；不发给Luna，不回显密钥或地址值。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _required_text:31 | 保留（raise） | `ValueError(f'explore_api.{field_name} must be a non-empty string')` |
| _https_base_url:39 | 保留（raise） | `ValueError('explore_api.base_url must be an HTTPS URL')` |
| _reasoning_effort:46 | 保留（raise） | `ValueError('explore_api.reasoning_effort must be one of: ' + ', '.join(sorted(_REASONING_EFFORTS)))` |
| _timeout_seconds:57 | 保留（raise） | `ValueError('explore_api.timeout_seconds must be a positive integer')` |
| load_explore_api_config:66 | 保留（raise） | `ValueError(f'explore API config is unavailable: {config_path}')` |
| load_explore_api_config:72 | 保留（raise） | `ValueError('explore API config is not valid YAML')` |
| load_explore_api_config:74 | 保留（raise） | `ValueError('explore API config root must be a mapping')` |
| load_explore_api_config:76 | 保留（raise） | `ValueError('explore API config version must be 1')` |
| load_explore_api_config:79 | 保留（raise） | `ValueError('explore_api must be a mapping')` |

### contracts.py

主Agent既有格式纠正；旧字段只作兼容。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _text:28 | 补充（raise） | `ValueError(f'{name}: required text is empty；请补充该字段，不要修改其他已确认事实。')` |
| _array:34 | 保留（raise） | `ValueError(f'{name} must be an array')` |
| _parse_screen:168 | 保留（raise） | `ValueError('screen must be an object or null')` |
| _parse_screen:171 | 补充（raise） | `ValueError(f'screen.identity={identity!r} is invalid；请使用 {sorted(SCREEN_IDENTITIES)}。')` |
| _parse_screen:182 | 保留（raise） | `ValueError('known screen requires page_ref and state_ref')` |
| _parse_screen:184 | 保留（raise） | `ValueError('new_state requires page_ref')` |
| _parse_page_report:192 | 保留（raise） | `ValueError('page_report must be an object or null')` |
| _parse_page_report:197 | 补充（raise） | `ValueError(f'{region_path}: each Region must be an object')` |
| _parse_page_report:199 | 补充（raise） | `ValueError(f'{region_path}.region_ref is required；已知区块复制已有 r，新候选填空字符串。')` |
| parse_operation:207 | 补充（raise） | `ValueError(f'{path}: each operation must be an object')` |
| parse_operation:209 | 补充（raise） | `ValueError(f'{path}.operation_ref is required；已知操作复制已有 co，新候选填空字符串。')` |
| parse_operation:227 | 补充（raise） | `ValueError(f'{path}.handling={handling!r} is invalid；请使用 {sorted(OPERATION_HANDLING)}。')` |
| parse_operation:229 | 补充（raise） | `ValueError(f'{path}.parameter_status is required；未确认参数时填 unknown。')` |
| parse_operation:231 | 补充（raise） | `ValueError(f'{path}.parameter_summary is required；填写已观察的参数信息或明确尚未确认，不要编造值域。')` |
| parse_operation:236 | 补充（raise） | `ValueError(f'{path}.parameter_status={parameter_status!r} is invalid；请使用 {sorted(PARAMETER_STATUSES)}，未观察到值域时用 unknown。')` |
| parse_operation:238 | 补充（raise） | `ValueError(f'{path}.action={action!r} is invalid；请使用 {sorted(ACTION_KINDS)}。')` |
| parse_operation:240 | 保留（raise） | `ValueError(f'{path}: Element operation must start from the Element; scroll/back/wait are not Element operations')` |
| parse_operation:245 | 保留（raise） | `ValueError(f'{path}.action={action!r}: Region operation currently supports only scroll；控件动作应放在所属 Element 的 operations 中。')` |
| parse_operation:248 | 保留（raise） | `ValueError(f'{path}.direction={direction!r}: Region scroll operation requires a valid direction，请使用 up/down/left/right。')` |
| _parse_page_report:271 | 补充（raise） | `ValueError(f'{element_path}: each Element must be an object')` |
| _parse_page_report:273 | 补充（raise） | `ValueError(f'{element_path}.element_ref is required；已知控件复制已有 el，新候选填空字符串。')` |
| _parse_page_report:303 | 保留（raise） | `ValueError('page_report.survey_complete must be boolean')` |
| _parse_previous:315 | 保留（raise） | `ValueError('previous_action must be an object or null')` |
| _parse_previous:324 | 补充（raise） | `ValueError(f'{item_path}: each completed Element action must be an object')` |
| _parse_previous:327 | 补充（raise） | `ValueError(f'{item_path}.action={action!r}: completed Element action is invalid；请使用待结算动作的真实 kind，不要把滚动报成 Element 动作。')` |
| _parse_previous:330 | 补充（raise） | `ValueError(f'{item_path}: completed Element action requires boolean completed')` |
| _parse_previous:343 | 补充（raise） | `ValueError(f'{item_path}: each completed Region action must be an object')` |
| _parse_previous:348 | 补充（raise） | `ValueError(f'{item_path}: completed Region action must be a directed scroll；收到 action={action!r}, direction={direction!r}，请与待结算动作的 scroll 和方向一致。')` |
| _parse_previous:351 | 补充（raise） | `ValueError(f'{item_path}: completed Region action requires boolean completed')` |
| _parse_previous:365 | 补充（raise） | `ValueError(f'{item_path}: each function_info item must be an object')` |
| _parse_previous:375 | 保留（raise） | `ValueError('previous_action.parameter_info must be an object or null')` |
| _parse_previous:382 | 保留（raise） | `ValueError(f'previous_action.parameter_info.status={status!r} is invalid；仅填写 none 或 observed；尚未确认参数时 parameter_info 留 null。')` |
| _parse_previous:391 | 保留（raise） | `ValueError('previous_action.region_effects must contain objects')` |
| _parse_previous:395 | 保留（raise） | `ValueError('previous_action.representative_same_kind must be boolean or null')` |
| _parse_previous:418 | 补充（raise） | `ValueError(f'previous_action.outcome={outcome!r} is invalid；旧记录仅接受 {sorted(ACTION_OUTCOMES)}。')` |
| _parse_previous:420 | 补充（raise） | `ValueError(f'previous_action.task_result={task_result!r} is invalid；旧记录仅接受 {sorted(TASK_RESULTS)}。')` |
| _parse_previous:423 | 保留（raise） | `ValueError('previous_action.task_result=completed requires outcome=success or conclusive no_effect evidence')` |
| _parse_previous:435 | 保留（raise） | `ValueError('previous_action.satisfied_operation_refs accepts at most 3 refs')` |
| _parse_previous:438 | 保留（raise） | `ValueError('previous_action.satisfied_operation_refs contains duplicates')` |
| _parse_representative_probe:455 | 保留（raise） | `ValueError('representative_probe must be an object or null')` |
| _parse_representative_probe:465 | 保留（raise） | `ValueError('representative_probe requires 2..32 distinct member refs')` |
| _parse_representative_probe:475 | 保留（raise） | `ValueError('representative_probe requires exactly two distinct owner refs')` |
| _parse_representative_probe:478 | 保留（raise） | `ValueError('representative owners must belong to member_owner_refs')` |
| _parse_action:493 | 保留（raise） | `ValueError('action must be an object or null')` |
| _parse_action:497 | 补充（raise） | `ValueError(f'action.kind={kind!r} is invalid；请使用 {sorted(ACTION_KINDS)}。')` |
| _parse_action:499 | 补充（raise） | `ValueError(f'action.purpose={purpose!r} is invalid；当前协议不需要填写 purpose，由框架推导。')` |
| _parse_action:505 | 保留（raise） | `ValueError('action.point_1000 must be [x,y] in 0..1000 or null')` |
| _parse_action:509 | 保留（raise） | `ValueError(f'action.point_1000={point!r} uses an ambiguous 0..1 coordinate scale；请按整张最新截图的 0..1000 尺度填写 [x,y]，不是像素或 0..1 比例。')` |
| _parse_action:516 | 保留（raise） | `ValueError(f'{kind} requires point_1000')` |
| _parse_action:519 | 补充（raise） | `ValueError(f'action.direction={direction!r}：scroll requires a valid direction，请填 up/down/left/right。')` |
| _parse_action:524 | 保留（raise） | `ValueError('action.amount must be an integer in 1..1000')` |
| parse_turn:545 | 保留（raise） | `ValueError('response must be one JSON object')` |
| parse_turn:548 | 补充（raise） | `ValueError(f'app_scope={app_scope!r} is invalid；请使用 {sorted(APP_SCOPES)}。')` |
| parse_turn:554 | 保留（raise） | `ValueError('current_task_result 不能填 completed；当前协议由框架根据真实动作结算任务。请移除此字段；有待结算动作时用 previous_action 报告实际效果，没有待结算动作时 previous_action=null。不要为修正报告重复执行 GUI 动作。')` |
| parse_turn:559 | 保留（raise） | `ValueError('current_task_result 只允许 deferred/failed')` |
| parse_turn:583 | 保留（raise） | `ValueError(f'previous_action must be {expected} this round')` |
| parse_turn:587 | 保留（raise） | `ValueError(f'previous_action.attempt_ref must equal pending {pending_attempt_id}, got {turn.previous_action.attempt_ref}')` |
| parse_turn:592 | 保留（raise） | `ValueError('current_task_result requires no pending action; settle previous_action first')` |
| parse_turn:597 | 保留（raise） | `ValueError('current_task_result requires action=null')` |
| parse_turn:599 | 保留（raise） | `ValueError('target_app requires a screen report')` |
| parse_turn:601 | 保留（raise） | `ValueError('non-target screen cannot submit page_report')` |

### inventory.py

主Agent清单纠正；原图回滚到本轮基线。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _validate_unique_element_refs:53 | 保留（raise） | `ValueError(f'Element ref {ref} 重复用于 {seen[ref]} 和 {path}。同一控件只报告一个Element，把其操作合在operations中；不同控件应使用不同ref，未确认的新控件留空供审核。')` |
| _accept_operation:194 | 保留（raise） | `ValueError(f'operation_ref {report.operation_ref} 不存在。已知操作复制当前区块的稳定 co；新操作将 operation_ref 留空供框架登记，不要编造编号。')` |
| _accept_operation:198 | 保留（raise） | `ValueError(f'operation_ref {report.operation_ref} 不属于当前 Region {occurrence.region_id}，而属于 {reported_identity.region_id}。请引用当前区块的操作；新操作留空，不要跨区块复制 co。')` |
| _accept_operation:206 | 保留（raise） | `ValueError(f'operation_ref {report.operation_ref} 的 scope/action/direction 应为 {reported_identity.scope}/{reported_identity.action}/{reported_identity.direction!r}，当前报告为 {scope}/{report.action}/{report.direction!r}。核对当前控件的操作引用；不同操作留空登记，不要为匹配旧编号改写界面事实。')` |
| _accept_operation:214 | 保留（raise） | `ValueError(f'operation_ref {report.operation_ref} 与当前本地 Operation {operation.operation_id} 不一致；该绑定的稳定引用是 {operation.canonical_operation_id}。若仍是这个控件操作，请复制此 co；若是另一控件，请先修正 Element 引用，不要改绑已有操作。')` |
| _accept_operation:270 | 保留（raise） | `ValueError(f"Region {occurrence.region_id} / Element {element_id or '<region>'} / Operation {operation.operation_id} parameter conflict: saved {operation.parameter_status} ({operation.parameter_summary or 'no summary'}; evidence={operation.parameter_evidence_refs or []}), reported {report.parameter_status} ({report.parameter_summary or 'no summary'}). Recheck whether the visible value belongs to the action's input parameter; do not replace saved evidence by wording.")` |
| apply_page_report:323 | 补充（issue） | `f'未知页面状态 {state_id}；清单未写入，请先用 screen 确认已有 State 或报告真实的新 State。'` |
| apply_page_report:327 | 保留（issue） | `str(exc)` |
| apply_page_report:339 | 保留（issue） | `f'region_ref {region_report.region_ref} 不属于当前 State {state_id}；请使用当前 State 中实际对应的 Region 引用，未确认的新区块留空供审核，不要复制其他 State 的引用。'` |
| apply_page_report:381 | 保留（issue） | `f'element_ref {element_report.element_ref} 不属于当前 RegionVariant {variant.variant_id}；请复制当前区块实际控件的 el，新候选留空供审核，不要用名称相近的其他控件编号。'` |
| apply_page_report:403 | 保留（issue） | `f'区块 {region_report.name} 的 Element {element_report.name} 为同一 owner/action 登记了多个 Operation。参数值应写入 Region memory，并只保留一个代表动作。'` |
| apply_page_report:416 | 保留（issue） | `f'区块 {region_report.name} 的 Element {element_report.name} 重复报告操作“{operation_report.action} {operation_report.target}”。'` |
| apply_page_report:436 | 保留（issue） | `str(exc)` |
| apply_page_report:444 | 保留（issue） | `f'区块 {region_report.name} 为同一 owner/action/direction 登记了多个 RegionOperation。只保留一个代表动作。'` |
| apply_page_report:456 | 保留（issue） | `f'区块 {region_report.name} 重复报告区域操作“{operation_report.action} {operation_report.direction}”。'` |
| apply_page_report:475 | 保留（issue） | `str(exc)` |

### ledger.py

存档读取者；不让模型猜测修复存档。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| load:390 | 保留（raise） | `ValueError('unsupported modular exploration ledger schema')` |

### location.py

主Agent位置纠正；保留未绑定状态。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| bind_screen:36 | 保留（issue） | `'当前页面身份仍不确定；请根据截图与已知页面记录明确复用或新建，不要在身份未定时登记区块或执行功能动作。'` |
| bind_screen:54 | 保留（issue） | `f'未知页面编号 {screen.page_ref}；请使用状态栏中存在的编号。'` |
| bind_screen:57 | 保留（issue） | `f'未知状态编号 {screen.state_ref}；请使用状态栏中存在的编号。'` |
| bind_screen:64 | 保留（issue） | `f'状态 {screen.state_ref} 属于页面 {owner_text}，不是 {screen.page_ref}；若当前截图是该状态，请改用正确的 page_ref。'` |
| bind_screen:73 | 保留（issue） | `f'screen.page_ref={screen.page_ref}：要新增状态的页面编号不存在；同一页面的新状态请复制已知 page_ref，真正的新页面用 identity=new_page，不要编造 Page 编号。'` |
| bind_screen:85 | 保留（issue） | `f'拟新增页面名称“{screen.page_name}”与已登记页面 {existing} 精确同名。框架不会仅凭名称自动合并，也不会再建立同名 Page；若当前截图属于其中一个页面，请改用 identity=known 及其精确 page_ref/state_ref；若确实是不同主要功能页面，请给出能稳定区分功能目的地的页面名称。'` |

### region_review.py

Region审核既有重答 / Element清单重提 / Operation保留不复用。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| review_page_report_element_candidates:395 | 保留（raise） | `ValueError('; '.join(issues))` |
| review_page_report_element_candidates:408 | 保留（raise） | `ValueError('Element Reviewer 的 decisions 不是数组；原候选清单保持不变重新提交以重做审核，action 留空。')` |
| review_page_report_element_candidates:414 | 保留（raise） | `ValueError('Element Reviewer 的 decisions 项不是对象；原候选保持不变重新提交以重做审核，action 留空。')` |
| review_page_report_element_candidates:417 | 保留（raise） | `ValueError(f'Element Reviewer 的 candidate_index={candidate_index!r} 未知或重复；原候选保持不变重新提交以重做审核，action 留空，不要修改控件身份来迁就审核回复。')` |
| review_page_report_element_candidates:427 | 保留（raise） | `ValueError(f'Element Reviewer 候选 {candidate_index} 的 known_element_ref={known_ref!r} 不属于当前 Variant {variant_id}；原候选保持不变重新提交以重做审核，action 留空。')` |
| review_page_report_element_candidates:433 | 保留（raise） | `ValueError(f'Element Reviewer 候选 {candidate_index} 同时返回 new 和 known_element_ref={known_ref!r}；审核回复自相矛盾，原候选保持不变重新提交，action 留空。')` |
| review_page_report_element_candidates:446 | 保留（raise） | `ValueError(f'Element Reviewer 候选 {candidate_index} 的 decision={decision!r} 非法；原候选保持不变重新提交以重做审核，action 留空。')` |
| review_page_report_element_candidates:450 | 保留（raise） | `ValueError(f'Element Reviewer 遗漏候选 {sorted(expected - seen)}；原候选保持不变重新提交以重做审核，action 留空，不要删除未审核控件。')` |
| review_page_report_element_candidates:454 | 保留（raise） | `ValueError('; '.join(issues))` |
| review_page_report_element_candidates:467 | 补充（raise） | `ValueError('Element Reviewer 应用身份后出现引用冲突：' + str(exc).split('。', 1)[0] + '。这不证明两个候选是同一控件；请保留真实独立控件，重新提交候选审核，action 留空，不要为通过检查合并按钮。')` |
| _review_operation_identity_candidates:570 | 补充（raise） | `ValueError('Operation Reviewer.decisions must be an array；未批准任何操作复用，原操作分别保留。')` |
| _review_operation_identity_candidates:576 | 保留（raise） | `ValueError('each Operation identity decision must be an object')` |
| _review_operation_identity_candidates:583 | 保留（raise） | `ValueError(f'Operation identity decision has an unknown or duplicate pair {key}；只复制 candidate_pairs 中的编号，每对报告一次；本批次复用未批准。')` |
| _review_operation_identity_candidates:591 | 保留（raise） | `ValueError(f'Operation pair {key}: same Operation requires identity or result reuse_level，收到 {reuse_level!r}')` |
| _review_operation_identity_candidates:600 | 保留（raise） | `ValueError(f'Operation pair {key}: different or uncertain Operation requires reuse_level=none，收到 {reuse_level!r}')` |
| _review_operation_identity_candidates:603 | 补充（raise） | `ValueError(f'Operation pair {key}: invalid Operation identity decision {decision!r}；允许 same/different/uncertain。')` |
| _review_operation_identity_candidates:605 | 补充（raise） | `ValueError(f'Operation identity response omitted candidate pairs {sorted(expected - seen)}；所有候选对都需报告，未批准本批次复用。')` |
| apply_region_identity_result:715 | 补充（raise） | `ValueError('Region Reviewer.decisions must be an array；按 current_regions 逐项返回审核对象。')` |
| apply_region_identity_result:748 | 保留（raise） | `ValueError('each Region decision must be an object')` |
| apply_region_identity_result:759 | 补充（raise） | `ValueError(f'Region {current}: shared_operations must be an array；不共享时填 []。')` |
| apply_region_identity_result:761 | 保留（raise） | `ValueError(f'Region decision has missing, duplicate, or unknown current ref {current!r}；允许的 current_region_ref={sorted(expected)}，每个报告一次。')` |
| apply_region_identity_result:770 | 保留（raise） | `ValueError('reuse requires component_relation=same_complete_component or reconstructing_fragment')` |
| apply_region_identity_result:774 | 保留（raise） | `ValueError('reuse requires causal_relation=none; a Region that reveals or is revealed by another surface is separate')` |
| apply_region_identity_result:778 | 补充（raise） | `ValueError(f'Region {current}: reuse references an unknown candidate Region {known!r}；known_region_ref 只能复制 {sorted(allowed_known)}；无法确认同一组件时用 uncertain。')` |
| apply_region_identity_result:785 | 保留（raise） | `ValueError('each shared operation must be an object')` |
| apply_region_identity_result:794 | 保留（raise） | `ValueError(f'Region {current}: shared operation references an unknown current Operation {current_operation!r}；该编号实际所属区块为 {current_operation_owner.get(current_operation)!r}，请复制本区块候选 operations 的编号。')` |
| apply_region_identity_result:798 | 保留（raise） | `ValueError(f'Region {current} -> {known}: shared operation references an unknown known Operation {known_operation!r}；该编号实际所属区块为 {known_operation_owner.get(known_operation)!r}，请复制所选 known Region 的操作编号。')` |
| apply_region_identity_result:827 | 保留（raise） | `ValueError(f'shared operation {current_operation} -> {known_operation}: reuse_level={reuse_level!r} must be identity or result')` |
| apply_region_identity_result:846 | 保留（raise） | `ValueError(f'current Operation {current_operation} maps to multiple known Operations: {previous_known}, {known_operation}')` |
| apply_region_identity_result:879 | 补充（raise） | `ValueError(f'Region {current}: invalid Region identity decision {decision!r}；允许 reuse/separate/uncertain。')` |
| apply_region_identity_result:883 | 保留（raise） | `ValueError(f'Region {current}: separate requires component_relation=member_or_subregion/trigger_or_result/different_component，收到 {component_relation!r}')` |
| apply_region_identity_result:892 | 保留（raise） | `ValueError(f'Region {current}: trigger_or_result requires an explicit causal direction；causal_relation 用 known_operation_reveals_current 或 current_operation_reveals_known；证据不足改 uncertain，不要猜方向。')` |
| apply_region_identity_result:898 | 保留（raise） | `ValueError('non-causal separate Regions require causal_relation=none')` |
| apply_region_identity_result:903 | 保留（raise） | `ValueError('uncertain decision requires both relation fields=uncertain')` |
| apply_region_identity_result:906 | 保留（raise） | `ValueError('separate or uncertain Region cannot share Operations')` |
| apply_region_identity_result:922 | 保留（raise） | `ValueError(f'Region {current}: revealed Region requires an exact incoming Transition；原候选没有可用 source_transition，不能声明该动作显露此区块；请保留非因果或 uncertain 结论，不要编造入边。')` |
| apply_region_identity_result:943 | 保留（raise） | `ValueError(f'Region {current}: revealed Region requires an exact incoming Transition；attempt_ref={attempt_ref!r} 未匹配已记录的来源/目标/操作组合；请根据原 source_transition 核对，不能确认因果时填 uncertain，不要编造入边。')` |
| apply_region_identity_result:953 | 保留（raise） | `ValueError(f'Region {current}: revealed Region is not in the incoming target State {transition.target_state_id}（已登记 {sorted(target_region_ids)}）；请核对当前区块引用，不能凭时间先后声明显露。')` |
| apply_region_identity_result:960 | 补充（raise） | `ValueError(f'Region identity response omitted current Regions {sorted(expected - seen)}；每个 current_region_ref 都需报告，无法确认填 uncertain。')` |
| apply_region_identity_result:968 | 保留（raise） | `ValueError(f'同一候选 Region 的 reuse 必须是一个完整当前组件，或由至少两个全部标为 reconstructing_fragment 的当前片段共同重构（候选 Region {known}）')` |

### region_routes.py

主Agent效果报告纠正；不自动猜因果。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| record_region_effects:58 | 补充（raise） | `ValueError(f'{path}.report_index={index!r}: use a valid page_report index OR a Region ref；本轮清单有 {len(reported_region_ids)} 个区块，索引从 0 开始；不要引用动作前清单的位置。')` |
| record_region_effects:61 | 补充（raise） | `ValueError(f'{path}: Region ref and page_report index disagree；region_ref={ref!r}，report_index={index} 实际对应 {reported_region_ids[index]}；核对最终清单后只保留一种正确引用，不要改变真实效果。')` |
| record_region_effects:70 | 补充（raise） | `ValueError(f'{path}: invalid change or cause；收到 change={change!r}, cause={cause!r}；change 用 appeared/disappeared/updated，cause 用 action/external/uncertain；无法归因用 uncertain。')` |
| record_region_effects:74 | 补充（raise） | `ValueError(f'{path}: {ref} does not match the before/after Region visibility；报告 change={change!r}，动作前存在={ref in source}，动作后存在={ref in target}。核对动作前引用与本轮清单引用；不要仅为通过检查把变化归因于动作。')` |

### regions.py

身份审核或内部调用者；不提交失败的合并。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _merge_variant_operation:295 | 保留（raise） | `ValueError(f'cannot merge a same-Variant Operation after it has action evidence: {duplicate_id} -> {representative_id}；保留独立记录及真实 Attempt，不要覆盖历史。')` |
| _coalesce_region_variants_by_state:384 | 保留（raise） | `ValueError(f'a RegionVariant must belong to exactly one Page State: {variant_id} 当前关联 {sorted(state_ids)}；属于图结构问题，不能由模型猜测删除 occurrence。')` |
| merge_region_identity:493 | 保留（raise） | `ValueError(f'unknown known Region: {known_region_id}')` |
| merge_region_identity:514 | 补充（raise） | `ValueError(f'shared operation references an unknown current Operation: {sorted(set(operation_pairs) - current_operation_ids)}；请修正当前区块操作映射，未提交合并。')` |
| merge_region_identity:516 | 补充（raise） | `ValueError(f'shared operation references an unknown known Operation: {sorted(set(operation_pairs.values()) - known_operation_ids)}；请修正所选历史区块操作映射，未提交合并。')` |
| merge_region_identity:521 | 补充（raise） | `ValueError(f'{current_id} -> {known_id}: shared Operations must have exact action；收到 {current_operation.action!r} / {known_operation.action!r}，应取消这对复用，不要改写实际动作。')` |
| merge_region_identity:523 | 补充（raise） | `ValueError(f'{current_id} -> {known_id}: shared Operations must have exact owner scope；收到 {current_operation.scope!r} / {known_operation.scope!r}，应取消这对复用。')` |
| merge_region_identity:525 | 补充（raise） | `ValueError(f'{current_id} -> {known_id}: shared RegionOperations must have exact direction；收到 {current_operation.direction!r} / {known_operation.direction!r}，应取消这对复用。')` |
| merge_region_identity:527 | 补充（raise） | `ValueError(f'shared Operation {current_id}: level={levels.get(current_id)!r} must be identity or result')` |
| merge_region_identity:533 | 保留（raise） | `ValueError(f'unknown current Region: {current_region_id}')` |
| merge_region_identity:572 | 保留（raise） | `ValueError(f"Operation {operation_id}: result reuse requires verified result text；候选状态={representative.status}，已提供结果文本={bool(result_texts.get(operation_id, '').strip())}；证据不足时仅复用 identity，不能写成 verified。")` |
| merge_operation_identity:673 | 补充（raise） | `ValueError(f'operation reuse references an unknown Operation or the same Operation: {current_operation_id} -> {known_operation_id}；请核对两个独立的已登记操作。')` |
| merge_operation_identity:675 | 补充（raise） | `ValueError(f'verified Operations must share one canonical Region: {current_operation_id} 属于 {current.region_id}，{known_operation_id} 属于 {known.region_id}；保留独立结果。')` |
| merge_operation_identity:677 | 补充（raise） | `ValueError(f'verified Operations must have exact action: {current_operation_id}={current.action}, {known_operation_id}={known.action}；取消该结果复用。')` |
| merge_operation_identity:679 | 补充（raise） | `ValueError(f'verified Operations must have exact owner scope: {current_operation_id}={current.scope}, {known_operation_id}={known.scope}；取消该结果复用。')` |
| merge_operation_identity:681 | 补充（raise） | `ValueError(f'verified RegionOperations must have exact direction: {current_operation_id}={current.direction}, {known_operation_id}={known.direction}；取消该结果复用。')` |
| merge_operation_identity:683 | 补充（raise） | `ValueError(f'both Operations must be verified before reuse: {current_operation_id}={current.status}, {known_operation_id}={known.status}；此入口复用已验证结果，不能用身份相同代替结果证据。')` |

### run_checkpoint.py

运行恢复者；缺失快照/摘要不可由Luna伪造。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| __init__:21 | 保留（raise） | `ValueError('run checkpoints retain one or two pairs')` |
| __init__:24 | 保留（raise） | `ValueError('run checkpoint needs a safe run id')` |
| save:46 | 保留（raise） | `ValueError('checkpoint app_id must be non-empty')` |
| save:53 | 保留（raise） | `ValueError('checkpoint package_versions must be non-empty')` |
| latest:113 | 补充（raise） | `ValueError('no complete matching run checkpoint pair exists；' + ('；'.join(issues) if issues else f'{self.directory} 中没有 checkpoint 文件') + '。请恢复匹配的图与环境快照，不要单独修改摘要或伪造已结算动作。')` |
| _validate_record:164 | 保留（raise） | `ValueError('run checkpoint fields do not match schema v1')` |
| _validate_record:166 | 补充（raise） | `ValueError(f"run checkpoint identity mismatch: expected schema={SCHEMA}, run_id={self.run_id}; received schema={record['schema']}, run_id={record['run_id']}；请选正确运行的存档。")` |
| _validate_record:168 | 补充（raise） | `ValueError(f"run checkpoint generation={record['generation']!r} is invalid；应为正整数，请恢复有效存档，不要手改代次。")` |
| _validate_record:171 | 保留（raise） | `ValueError(f'run checkpoint {field} is invalid')` |
| _validate_record:175 | 保留（raise） | `ValueError('run checkpoint package_versions is invalid')` |
| _last_settled_attempt:181 | 保留（raise） | `ValueError('checkpoint ledger attempts must be a list')` |
| _last_settled_attempt:185 | 保留（raise） | `ValueError('checkpoint ledger attempt is invalid')` |
| _last_settled_attempt:191 | 保留（raise） | `ValueError('checkpoint settled attempt has no id')` |
| _read_json:199 | 保留（raise） | `ValueError('checkpoint JSON must be an object')` |
| _digest_text:220 | 保留（raise） | `ValueError(f'{label} must be a lowercase SHA-256 digest')` |

### runtime.py

主Agent既有纠正/停机记录；按实际执行阶段区分。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _force_release_pending_report:316 | 保留（correction） | `'上一 pending 报告纠正达到上限，框架已保守保存证据并释放；不得重复该 GUI 动作。请根据 fresh screenshot 继续其他任务。'` |
| _reject_observation_report:343 | 补充（correction） | `f'本轮 page_report 未接受，未执行新动作。{error}'` |
| _handle_pending_report_rejection:404 | 保留（correction） | `f"待结算报告字段 {fields['field_path']} 未通过：期望 {fields['expected']}，收到 {fields['received']}。只修正 {correction_target}；action 必须为 null，其余报告保持不变。"` |
| _validate_opportunistic_satisfaction:510 | 保留（action_guard） | `'顺路完成任务只接受 outcome=success 的真实动作证据。'` |
| _validate_opportunistic_satisfaction:512 | 保留（action_guard） | `'本轮更正了实际 target，不能再用旧 target 顺路完成其他任务。'` |
| _validate_opportunistic_satisfaction:519 | 保留（action_guard） | `'satisfied_operation_refs 只能引用本轮提供的顺路候选；候选外编号：' + '、'.join(unknown)` |
| _perform_requested_restart:969 | 保留（correction） | `'连续恢复动作无效，框架已关闭目标应用进程并在保留数据的情况下重新打开；请只根据这张 fresh screenshot 重新识别当前位置。'` |
| _record_action_rejection:1102 | 补充（correction） | `f'本轮提议的动作未执行。{issue}'` |
| _validate_action:1425 | 保留（action_guard） | `issue` |
| _validate_action:1435 | 保留（action_guard） | `'Android 软键盘仍可见，不能执行 scroll；请先用 back 隐藏键盘，取得 fresh screenshot 后再从目标应用内容区域选择滚动点。'` |
| _validate_action:1442 | 保留（action_guard） | `'scroll 必须绑定当前可见 Region 的 region_ref 和对应方向 RegionOperation；不允许空 owner 滚动。'` |
| _validate_action:1450 | 保留（action_guard） | `'当前没有可运行任务，只能执行不绑定功能操作的恢复动作'` |
| _validate_action:1462 | 保留（action_guard） | `f'同一任务已连续 {repeated} 次以完全相同参数执行且均无可见效果，不能再次原样投递。请改变点位、方向或幅度等可验证参数；达到确定性尝试上限后，框架会自动保留 failed gap。'` |
| _validate_action:1485 | 保留（action_guard） | `f'页面调查已连续 {repeated_direction} 次向 {action.direction} 滚动且都无可见效果，不能继续只改点位重复同一方向。direction 表示要查看的内容方向：查看视口下方用 down，查看上方用 up。请改用 direction={opposite}、改变调查区域，或在现有证据足够时提交 survey_complete=true。'` |
| _validate_action:1502 | 保留（action_guard） | `f'当前调查任务属于 {task.state_id}，当前位置是 {self.ledger.current_state_id}；请用当前可见且已登记的 owner 逐步返回来源状态，再提交完整 page_report。'` |
| _validate_action:1507 | 保留（action_guard） | `'页面清点任务不能执行功能或导航操作。若当前页面已经清点完整，请提交 page_report.survey_complete=true 且 action=null；框架保存清单后会在下一轮派发已登记操作。若仍未完整，只能执行 已登记 Region owner 的调查滚动或非滚动恢复。'` |
| _validate_action:1516 | 保留（action_guard） | `f'页面清点任务 {task.task_id} 只能绑定调查滚动的 RegionOperation，不能使用 {action.operation_ref} 执行功能。'` |
| _validate_action:1524 | 补充（action_guard） | `f'action.owner_ref={action.owner_ref} 没有映射到当前 Variant 的 Operation （绑定结果 {action.operation_ref!r}）；请核对当前已登记 owner，缺少操作时先补清单。'` |
| _validate_action:1527 | 补充（action_guard） | `f'action.kind={action.kind} 与 owner_ref={action.owner_ref} 映射的 Operation {operation.operation_id} 动作 {operation.action} 不一致；请使用该 owner 已登记的动作或补充真实的新操作。'` |
| _validate_action:1531 | 补充（action_guard） | `f'action.direction={action.direction} 与 owner_ref={action.owner_ref} 映射的 RegionOperation 方向不一致（期望 {operation.direction}）；核对该方向的区块操作，缺少时先补清单。'` |
| _validate_action:1547 | 保留（action_guard） | `f'当前 State 中的同类 Operation {action.operation_ref} 已经结束，不能完成当前焦点 {task.operation_id}。请先导航到该焦点的来源 State。'` |
| _validate_action:1568 | 保留（action_guard） | `f'实际 Operation {action.operation_ref} 已在当前焦点中成功执行，但没有完成焦点 Operation {task.operation_id}；不得再次执行同一替代操作。请返回来源 State {required_source} 后执行精确焦点，或选择尚未成功的准备/导航操作。'` |
| _validate_action:1587 | 保留（action_guard） | `'同一前置 owner 已在当前 Focus 中执行但没有产生 State 进展，不能立即原样重复。请改用其他当前可见 owner、恢复动作，或继续目标 Operation。'` |
| _validate_action:1604 | 保留（action_guard） | `f'当前已在操作 {task.operation_id} 的来源状态；若正在执行派发的“{operation.action} {operation.target}”，请使用 action.owner_ref={operation.element_id or operation.region_id}。不要填写内部 purpose/operation_ref，框架会根据 owner 绑定；坐标仍须依据最新截图。'` |
| _validate_action:1615 | 保留（action_guard） | `f"当前任务 {task.operation_id}（{operation_text}）仍未结束，本轮却提交 {action.operation_ref or '空值'}。请移除内部 purpose/operation_ref，改用当前真实动作对象的 action.owner_ref；前置动作不等于目标任务已完成，是否完成由真实结果结算。"` |
| _validate_action:1623 | 保留（action_guard） | `f'当前任务只验证“{operation.action} {operation.target}”，不能用 {action.kind} 替换。若目标仍成立，请提交 kind={operation.action}、action.owner_ref={operation.element_id or operation.region_id}；不要填写内部 purpose/operation_ref。若实际是另一控件或操作，先修正清单，不能伪报完成。'` |
| _validate_action:1634 | 保留（action_guard） | `f"当前 RegionOperation 只验证 direction={operation.direction}，不能改为 {action.direction or '空值'}。请按登记方向执行，或在最新截图显示需要另一方向时，先补充该区块对应方向的操作，再引用该区块执行。"` |
| _validate_action:1641 | 保留（action_guard） | `'当前 State 没有该任务可执行的本地 Operation binding；请用当前可见且已登记的 action.owner_ref 逐步到达目标；不要填内部 purpose=route。'` |
| run:1797 | 保留（correction） | `str(exc)[:500]` |
| run:1836 | 保留（correction） | `'app_scope 与系统窗口归属冲突：系统确认目标应用在前台，本轮应填 target_app。这不证明所有可见浮层都属于目标应用；若截图有无关通知或遮挡，先用安全恢复动作清理，page_report=null，不要将无关浮层登记为应用区块。'` |
| run:1874 | 保留（correction） | `'系统已确认上一画面属于外部应用；已尝试恢复目标应用，外部画面没有登记为 Page/State，请重新识别当前画面'` |
| run:1881 | 保留（correction） | `'当前系统归属不能直接证明目标应用；请根据截图明确 target_app 或 external_app。uncertain 不能登记页面或执行动作。'` |
| run:1911 | 保留（correction） | `f'动作投递返回 {delivery_error}；框架已把本次结算为 no_effect/retry，并隔离异常 landing 的 page_report 和同轮 action，未登记新 State。请基于 fresh screenshot 先恢复到来源状态；输入动作只有在目标字段获得真实编辑焦点后才能重试。'` |
| run:1928 | 保留（correction） | `location.issue` |
| run:1930 | 保留（correction） | `'当前落点尚未确定，下一轮使用新截图继续观察；只有新图支持时才报告 known/new，未稳定时可保持 uncertain。不得重复原动作。'` |
| run:1959 | 保留（correction） | `'当前没有待结算动作，不能把预期结果提前登记为新 Page/State；同一 Page 若自然出现了新的可见结构，可提交该新 State 及完整 page_report；否则请先执行动作，再根据真实结果新建。'` |
| run:2017 | 保留（correction） | `f'当前任务要清点 {task.state_id}，但当前位置是 {self.ledger.current_state_id}；不能用当前位置的重复清单结算另一个状态。请令 page_report=null，并用当前可见 owner 逐步返回来源状态。'` |
| run:2147 | 保留（correction） | `'重启后请先根据最新截图提交目标或路线起点 Region 的 page_report；不要求完整清点，也不要求恢复旧 Page/State。确认当前区块和操作前，不能沿用旧位置执行或结束遍历。'` |
| run:2213 | 保留（correction） | `'本次点击未执行：缺少 owner_ref。清单已保存；请先选择当前页面其他已绑定、可执行的待办，用 next_operation_ref 改选，并使用该控件的 owner_ref 点击。原操作保留，不记失败；清点尚未完成时先补充所需观察。单独的恢复点击请令 page_report=null。'` |
| run:2223 | 保留（correction） | `'页面清单已保存，但不能在提交 page_report 的同一轮执行功能操作。请下一轮从当前页面卡片填写 owner_ref。'` |
| run:2228 | 保留（correction） | `'本轮 page_report 仍标记 survey_complete=false，页面调查尚未完成，框架不会派发功能操作。请继续使用 已登记 Region owner 滚动或非滚动恢复取得缺失证据；确认清单完整时提交 survey_complete=true 且 action=null。清点不要求先点击已列操作；不能仅为了放行点击把未完成的调查标为完整。'` |
| run:2247 | 保留（correction） | `str(exc)[:500]` |
| run:2273 | 保留（correction） | `'page_report 缺少本轮所需清点信息；请补充当前截图中的新事实，或用已登记 Region 的 action.owner_ref 滚动观察。不要为了继续而虚报 survey_complete=true。'` |
| run:2353 | 保留（correction） | `'current_task_result 只能结算当前 active 的操作任务'` |
| _build_explorer_agent:2489 | 保留（raise） | `ValueError('openai_api requires validated local API config')` |
| _build_explorer_agent:2498 | 保留（raise） | `ValueError(f'unknown modular explore backend: {backend}')` |

### settlement.py

主Agent绑定或结果纠正；保留已有字段、期望及收到值。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| _element_operation:61 | 保留（raise） | `SettlementContractError(code='ELEMENT_NOT_IN_SOURCE_VARIANT', field_path=owner_path, expected=f'Element in State {state_id} source Variants {sorted(_source_variants(ledger, state_id))}', received=f'{element_ref} ({element.name}, {element.variant_id})' if element else element_ref, message=f'Element {element_ref} is not in the Attempt source Variant；请引用对应截图中已登记的实际控件，不要借用另一个 State 的 owner；新控件先提交清单取得引用')` |
| _element_operation:76 | 保留（raise） | `SettlementContractError(code='ELEMENT_OPERATION_NOT_UNIQUE', field_path=owner_path, expected=f'one {action} Operation in the source Variant', received=f'{element_ref} -> {len(matches)} matches', message=f'Element {element_ref} action {action} is not unique in source Variant（匹配 {matches}）；请核对这个控件已登记的动作；没有对应操作时先补清单，不要替换成另一控件编号')` |
| _region_operation:109 | 保留（raise） | `SettlementContractError(code='REGION_OPERATION_NOT_UNIQUE', field_path=owner_path, expected=f'one {action}/{direction} RegionOperation in the source Variant', received=f'{region_ref} -> {len(matches)} matches', message=f'Region {region_ref} action {action}/{direction} is not unique in source Variant（State {state_id}，匹配 {matches}）；请核对区块及滚动方向，没有对应操作时先补该区块的 region_operations')` |
| resolve_action_operation:136 | 保留（raise） | `SettlementContractError(code='ELEMENT_DIRECTION_NOT_ALLOWED', field_path='direction', expected='empty direction for an Element action', received=direction, message='Element action cannot carry a Region direction；Element 动作将 direction 留空；滚动应引用所属 Region')` |
| resolve_action_operation:159 | 保留（raise） | `SettlementContractError(code='UNKNOWN_OWNER', field_path=owner_path, expected='known Element or Region in the current source Variant', received=owner_ref, message=f'unknown owner {owner_ref} in current source Variant；owner_ref 只能引用实际控件 el 或区块 r，不能填 co、任务编号或名称；新控件先提交 page_report 取得引用')` |
| settle_completed_actions:237 | 保留（raise） | `SettlementContractError(code='COMPLETED_PRIMITIVE_MISMATCH', field_path=f'previous_action.element_actions[{item_index}].action', expected=dispatched, received=item.action, message='completed Element action does not match the dispatched primitive')` |
| settle_completed_actions:262 | 保留（raise） | `SettlementContractError(code='COMPLETED_PRIMITIVE_MISMATCH', field_path=f'previous_action.region_actions[{item_index}]', expected=dispatched, received=f'{item.action}/{item.direction}', message='completed Region action does not match the dispatched primitive')` |
| settle_completed_actions:291 | 保留（raise） | `SettlementContractError(code='FUNCTION_REGION_NOT_VISIBLE', field_path='previous_action.function_info[].region_ref', expected='Region visible before or after the Attempt', received=item.region_ref, message=f'function_info Region {item.region_ref} is not visible before or after the Attempt')` |
| settle_completed_actions:306 | 保留（raise） | `SettlementContractError(code='REPRESENTATIVE_OWNER_MISMATCH', field_path='previous_action.representative_same_kind', expected='one completed representative owner', received=f'completed operations {list(unique_refs)}', message='representative result must settle one declared owner')` |
| settle_completed_actions:319 | 保留（raise） | `SettlementContractError(code='REPRESENTATIVE_PROBE_NOT_FOUND', field_path='previous_action.representative_same_kind', expected='an active representative probe', received=str(representative_same_kind).lower(), message='representative result has no matching probe')` |
| settle_completed_actions:333 | 保留（raise） | `SettlementContractError(code='REPRESENTATIVE_RESULT_TOO_EARLY', field_path='previous_action.representative_same_kind', expected='all declared representatives completed', received=f'completed representatives {sorted(completed_after)}', message='representative result was reported before both probes')` |
| settle_completed_actions:343 | 保留（raise） | `SettlementContractError(code='REPRESENTATIVE_MEMORY_REQUIRED', field_path='previous_action.function_info', expected=f'a function summary for Region {representative_identity.region_id}', received='no matching function_info', message='same-kind decision requires a Region function summary')` |
| settle_completed_actions:366 | 保留（raise） | `SettlementContractError(code='REPRESENTATIVE_RESULT_REQUIRED', field_path='previous_action.representative_same_kind', expected='same_kind true or false after the final representative', received='null', message='the final representative needs an explicit same-kind result')` |
| settle_completed_actions:375 | 保留（raise） | `SettlementContractError(code='PARAMETER_WITHOUT_COMPLETED_OWNER', field_path='previous_action.parameter_info', expected='exactly one completed owner', received=f'{len(unique_refs)} completed owners', message='parameter confirmation requires exactly one completed owner')` |
| settle_completed_actions:387 | 保留（raise） | `SettlementContractError(code='PARAMETER_INFO_REQUIRED', field_path='previous_action.parameter_info', expected='none or observed parameter information', received='null', message='parameter confirmation is required before settling this Operation')` |
| settle_completed_actions:398 | 保留（raise） | `SettlementContractError(code='PARAMETER_INFO_CONFLICT', field_path='previous_action.parameter_info.status', expected=operation.parameter_status, received=info.status, message='parameter confirmation conflicts with saved evidence')` |

### tasks.py

主Agent任务/代表选择纠正；保留原任务事实。

| 位置 | 处理 | 实际错误或转发内容 |
| --- | --- | --- |
| register_representative_probe:22 | 保留（raise） | `ValueError(f'representative_probe.operation_ref {proposal.operation_ref} 不存在；请复制当前焦点的稳定 co，不要填 el 或内部 Task 编号。')` |
| register_representative_probe:26 | 保留（raise） | `ValueError(f'representative_probe.operation_ref={proposal.operation_ref} 的 scope={identity.scope}；representative_probe 只能引用 ElementOperation，区块滚动不适用此提案。')` |
| register_representative_probe:36 | 保留（raise） | `ValueError(f"representative_probe.operation_ref={proposal.operation_ref} 必须属于当前探索焦点的稳定 Operation {(focus_operation.canonical_operation_id if focus_operation else '(当前无操作焦点)')}；继续当前任务用其 co，不适用代表探索时 representative_probe=null。")` |
| register_representative_probe:54 | 保留（raise） | `ValueError(f'同类成员 {owner_ref} 与 {proposal.operation_ref} 的 Region/owner/action/direction 不一致。')` |
| register_representative_probe:59 | 保留（raise） | `ValueError(f'同类成员 {owner_ref} 已执行、失败、延期或结束，不能在事后加入代表探索。')` |
| register_representative_probe:70 | 保留（raise） | `ValueError('代表探索必须在任一代表动作执行前提出。')` |
| register_representative_probe:78 | 补充（raise） | `ValueError(f'representative_probe：当前稳定 Operation {identity.canonical_operation_id} 已有另一项代表探索 {identity.representative_operation_ids}；先完成已登记代表，不要覆盖提案，普通动作轮填 null。')` |
| apply_representative_probe:121 | 保留（raise） | `ValueError('representative_probe 必须在无待结算动作、无 page_report 的独立动作轮提出。')` |
| apply_representative_probe:125 | 保留（raise） | `ValueError('representative_probe 必须同时执行第一个代表动作。')` |
| apply_representative_probe:128 | 保留（raise） | `ValueError('本轮 action.owner_ref 必须是已声明的两个代表控件之一。')` |
| select_visible_operation:303 | 保留（raise） | `ValueError(f'next_operation_ref={canonical_ref}：当前 State 清点尚未完成，不能切换探索任务。' + continuation)` |
| select_visible_operation:324 | 保留（raise） | `ValueError(f'next_operation_ref={canonical_ref}：{detail}' + continuation)` |

## 无独立显式错误出口的模块

anchors、artifacts、bundle、models、resume、scope、status、prompts 也纳入检查：
ScopeGuard用unknown/last_reason保留前景查询失败，恢复失败由runtime记录；anchors读图/匹配失败回退，不能推断语义；
artifacts/bundle文件异常由调用者记录，models为数据结构，resume保留重新观察要求。
status/prompts属于纠正输出端，本次已修正旧思路冲突。它们没有另外新增错误系统或模型调用。
