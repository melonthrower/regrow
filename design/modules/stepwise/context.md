# 地图与上下文

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

把已有图、动作和任务记录组织成各步骤输入；不创建执行事实。

## 输入、输出与边界

已提交图、当前观察与任务 → 当前树、来源关系、相关历史和实际发送正文。同一事实保持来源，历史不自动代表当前可操作。

主要接口：`page_context.build / attach / refresh；page_history；prompt_delivery.desktop_parts`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

正常发送由 `model_transport.ModelTransport.call`（RecoveryRun继承，DesktopRun沿原父类调用） 在平台、范围与截图说明组装后调用 `history_disclosure.project`，统一排版普通与纠错上下文。动作事实由 `task_action_context.build → history_context.action_context → findings` 提供；保留 `known_findings` 证据字段。已移除无人调用的同名转接函数与旧的更新专用排版函数，相关保真断言归入现行发送投影测试。

## 源码与提示入口

- [page_context.py](../../../experiments/clock_manual_20260919/page_context.py)
- [page_history.py](../../../experiments/clock_manual_20260919/page_history.py)
- [map_prompt.py](../../../experiments/clock_manual_20260919/map_prompt.py)
- [history_context.py](../../../experiments/clock_manual_20260919/history_context.py)
- [history_disclosure.py](../../../experiments/clock_manual_20260919/history_disclosure.py)
- [task_action_context.py](../../../experiments/clock_manual_20260919/task_action_context.py)
- [task_attempt_context.py](../../../experiments/clock_manual_20260919/task_attempt_context.py)
- [target_observation.py](../../../experiments/clock_manual_20260919/target_observation.py)
- [prompt_delivery.py](../../../experiments/clock_manual_20260919/prompt_delivery.py)
- [render_region_context.py](../../../experiments/clock_manual_20260919/render_region_context.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [探索树阅读.prompt](../../../experiments/clock_manual_20260919/遍历prompt/历史上下文/探索树阅读.prompt)

历史正文主要由上述Python模块动态投影；同目录的其他早期提示不能因位置相邻就并入请求，按提示入口索引核对实际组装引用。

## 验证与未完成事项

地图投影和普通/纠错共用历史已有实现及有限保存帧验证；当前可见控件误报仍是开放问题。地图可读不等于身份正确。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#context)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 当前状态与历史努力（2026-10-06）
目标观察卡与共同地图不复述旧控件文字/数值/选中状态；本轮截图决定当前状态。历史保留目的、实际执行、结果依据和未解决问题，已验证参数范围/选项保留其来源。原始观察、截图和回复不改写；身份外观参考仍可用，但不成为当前状态证明。发现/更新提示不要求记录与本次验证无关的自然变化数字；不为旧数字增加补观察或纠错门槛。

## 每轮相关性投影（2026-10-06）
`history_selection`集中选择当前任务、明确准备和来源证据；`page_history`渲染目的/实际投递/直接反馈/缺口，原坐标和回执仅存后台，异常纠错按需要读取。两次引用之间的时间邻近不构成因果关联，不机械补整个区间；没有展开的动作不能当作没有发生。`region_candidate_names`只展开相关候选的控件角色与进入入口，其余历史只列唯一名称索引；旧页面description不再担当每轮身份正文。同名标签采用确定的可读序号，后台映射不变。普通动作的`target_observation`只展开绑定目标及明确导航入口，其他准备对象仍从整图判断，后台候选保留。

共同地图中的needs_recheck按“历史外观候选；本轮身份未确认”展示，不与本帧新确认对象混称事实。历史播放图标仍可能召回到当前开始按钮；没有当前身份确认时只保留候选，不称已解决所有视觉误匹配，也不强制为清理旧数字重观察。

任务清点的其他区块只列历史名称索引，不重新带入无关旧description。无已知导航路线时navigation_path可为空；目标卡仍保留当前绑定目标及当前图，路线参考为空不阻断正常看图导航。

没有活动任务的任务清点只展开清点区块的局部努力与最近可信进入记录、最近实际动作；同屏其他区块不因此展开其全部旧任务。独立历史和共同地图共用此选择，当前地图身份候选及原存档不删。

新选中任务尚未写入runtime active_task时，history_selection.for_request从正常请求source读取有效任务，供两处历史投影共用；只生成本轮读取视图，不改运行态或提早登记任务执行。

实际最近动作确实跨面到达或返回本轮前景时，不展开其他历史进入支路；同一对话框内搜索等动作不说明其原来路，仍保留原known_entries作为未连接的待核对线索，不能因正文收起就删除返回证据。

共享参数提示与历史投影共用状态/努力边界：使用新提示的正常任务清点和更新不把自动时钟、计数或按当前时刻填入的默认值提炼成findings；纠错继承原请求，历史请求不自动换成新提示；主动输入及有意义参数调查保留来源。原始观察/回复不删，不以按应用关键词过滤历史代替共享规则。旧图中既有瞬时参数事实不批量改写，新运行从初始图开始。

上述findings规则不改变控件清点：承载瞬时值的字段和独立按钮仍分别登记，同构选项沿用既有分组，不因分别登记就逐个试点。新增边界集中为共享参数提示的三句，不加模型阶段；完整编辑器更新同时保留业务控件并去掉自动时刻findings。

## 当前状态与稳定知识的读取（2026-10-07）
Region.current_observation按本次观察汇总控件text/state，只有同帧动作选择正文标为本次状态；换帧、动作前更新地图和纯视觉定位均不沿用其状态。当前控件附完成任务的紧凑knowledge；区块地图正文保留自身摘要、一级入口和紧凑条件/参数/功能完成边界及约束，省略重复来源与位置记录。后台完整记录及必要历史证据保留，不用固定条数截断任务失败。
