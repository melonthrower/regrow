# 服务失败后的分支切换

临时框架；原 gui_rewalk 不变。

- `step_repair.Runner` 捕获模型子进程失败且有 `http_error.json` 的情况，保存服务错误；向纠错 Luna 发起一次 `branch_correction`。不修改或重发被拒请求。纠错请求失败不递归纠错，下次也不重新发送原请求。
- 固定手册：`遍历prompt/纠错/暂挂分支并切换.prompt`。动态内容：失败阶段/服务返回/已执行动作、相关工作任务、暂挂范围、独立区块候选及待办、观察截图。回复 `decision/next_region/reason`。
- 候选来自已有图；排除源区块、工作区块、本次入口历史上已验证的目的区块、已有登记缺口、没有待办的已清点区块；没有任务清单的区块仍可作为待发现目标。同名不唯一不直接选。历史目的仅用于暂挂范围，不证明本次动作结果。
- 接受 switch 后保存原 pending 指针副本和截图到 `suspended_steps/<纠错调用>/`；旧请求、回执、episode、快照保留。相关 pending 任务 blocked，登记 suspended_branch 缺口。未生成动作 commit 或成功结果。
- 当前活动指针释放，工作区块改为模型选择，当前位置置未知，进入发现步。后续定位、导航仍用原三步流程；选择目标不等于到达。
- 投递回执未知/非零不通过此接口切换。纠错无合适目标或调用失败时保留原待处理记录。普通校验纠错继续原 defer 路径；不是所有异常都被此模块捕获。

## 验证边界

聚焦测试包含执行后更新暂挂、未确认投递保护、无目标不改写、服务错误自动接入、纠错失败不重发、失败入口目的排除。真实模型保存帧调用和独立账本登记见 records/203、204；未以保存帧测试代替设备导航验收。

首轮真实回复选择了原菜单：原实现只排除源/工作区块，遗漏入口已知目的。已根据图排除，不以 Clock 名称特判。原错误回复保留，不能算有效切换。

本轮验证：29项聚焦测试通过（`tests/test_stepwise_branch_switch.py tests/test_stepwise_deferral.py tests/test_stepwise_repair_scope.py`），日志 `artifacts/tmp_tests/branch_switch_20260922/final2.log`；两模块 py_compile 通过。真实调用0691服务接受但选择原菜单，修正候选后0692服务接受并选择“Stopwatch 页面内容”；独立账本登记成功。2 HTTP、0 GUI，当前实际运行账本未被回放更改；未验证自动导航到 Stopwatch。原始证据分别保存在 records/203_branch_correction_20260922、records/204_branch_correction_candidates_20260922。

## 2026-09-22：整支切换触发约束与循环接线

整支暂挂/切换只接受两种框架证据：实际调用目录的 HTTP 错误回执，或 `exploration_loop.json` 中当前成立的三次重复路径。请求生成与登记均核对触发证据；模型不能通过自由文本创建授权条件。既有普通纠错的局部 defer 未扩展成此能力。

`run_task_step` 在处理已有 pending 更新、视觉回溯之后，在新一轮发现/动作之前执行 `exploration_loop.observe`。最近九个轮次内，同一工作区块和任务，路径长度1/2/3连续重复三遍，且进展指纹不变时调用同一分支纠错入口。进展指纹包含区块/控件集合、任务状态与结果说明、去重后的动作目的关系、最新控件值状态；截图路径/调用号/重复动作编号不算进展。参数变化、任务推进重置重复判定。存在待处理步骤、待更新动作、待结算视觉回溯或正在恢复时不触发。重复轮次号不重复采样。

这是保守的无进展检测：超过三步的长环、不断误造新身份、观察描述持续漂移可能漏检，不声称识别所有循环。当前在轮次边界检测，不把任意单次识别失败归为循环。

纠错可以 switch 或 stop；只暂挂、不完成/删除任务。切换进入发现步，后续导航仍由原流程执行。纠错服务失败保留待处理记录，不递归请求。

验证：35项聚焦测试通过，命令为 `python -m pytest tests/test_stepwise_exploration_loop.py tests/test_stepwise_branch_switch.py tests/test_stepwise_deferral.py tests/test_stepwise_repair_scope.py -q --basetemp artifacts/tmp_tests/branch_trigger_20260922/final`；日志同目录 final.log。包含检测→纠错调用→暂挂→发现的假环境接线；本次0新增模型调用、0 GUI，不代表实机循环恢复已验证。上一轮0692真实服务调用结论保持。

## 2026-09-23：补充当前行为（覆盖上文旧限制）
普通请求遇429/500/502/503/504只重试一次原模型请求，不重放GUI；402不自动重发。功能整理服务失败沿局部defer，仅记该整理阶段缺口，其他GUI任务保留。
循环纠错增加resume：必须有具体新办法、无待结算执行；框架显式记resolved_loop、保存旧判断并回发现步。相同工作目标和知识只允许一次resume，其余仍switch/stop。零动作多轮停滞也值得处理，但不能说成反复点击。
