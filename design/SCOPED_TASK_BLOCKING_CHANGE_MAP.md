# 任务暂挂范围：实现修改地图

对应[设计](SCOPED_TASK_BLOCKING.md)。状态：已实现并完成本页限定验证，未执行新GUI。

源码提交：[`d9588def`](https://github.com/melonthrower/regrow/commit/d9588def6a677f29a2d95344d8406b759ad9d242)。开发基准 `69610badfbbc10089e0a79cc1e92446d3f6b9b8a`；最终冻结源码 source-v4 SHA256 `f4c7822101e8bea5d32ca3456f4e791f30ba7c118d1115c3e9231df7e5f07036`。下表是当前已实现位置，operation_blocking为本批新文件，不是旧版既有函数锚。

| 仓库相对路径 | 已实现函数及行号 | 原行为与修改 |
| --- | --- | --- |
| `experiments/clock_manual_20260919/operation_blocking.py` | `failures` L12–L41；`applicable` L44–L52；`action_conditions` L55–L64；`check_action` L67–L72；`attach` L75–L98 | 新文件；从原退出记录读取实际归属和条件，供三个入口共用，并在普通动作请求披露未知适用性。 |
| `experiments/clock_manual_20260919/task_prerequisites.py` | `enroll` L26–L51 | 已移除任意同控件blocked门禁；保留permitted/范围/去重，拦截已明确适用的退出操作。 |
| `experiments/clock_manual_20260919/stepwise_flow.py` | `shortest_known_path` L135–L167 | 已移除整控件过滤；沿实际路线操作条件筛除明确失败。 |
| `experiments/clock_manual_20260919/action_proposer.py` | `request_from_run` L57–L115 | 当前前景、任务和已披露外层候选的退出证据进入正常动作请求。 |
| `experiments/clock_manual_20260919/repair_stages.py` | `accept_candidate` L75–L120 | 正常动作及纠错接受共用具体失败动作检查。 |

`experiments/clock_manual_20260919/遍历prompt/任务/前置条件与恢复.prompt` L10：暂挂只属于任务，退出限制跟实际动作/条件走；正常任务提出与纠错组合沿用此提示。

`tests/test_scoped_task_blocking.py` 为新维护测试；`tests/test_stepwise_deferral.py` 的 `test_blocked_task_does_not_hide_independent_task_or_valid_route` 更新旧整控件禁令断言。无新字段、schema、CLI开关或额外模型步骤。没有待实施的同批机制；网络传输计数问题另行处理。

## 实际验收范围

67项聚焦检查通过；3项旧失败在开发基准复现并排除。真实Clock全量副本：正常TaskProposer/Runner/commit_plan的0166读取已有前置记录，生成一个c0028准备；原四个blocked保留。随后正常ActionProposer/Runner的0167选择原c0028绿色开始按钮并通过绑定，未投递GUI、未新增控件/完成原任务。实际原答不修改，共2HTTP/0GUI；截图在两次请求中复用，原件未改。

异常同条件拒绝、外层候选失败披露、准备后唤醒及范围/权限反例只有聚焦代码检查，未逐项新增Luna/GUI验证。旧前置文字仍包含最终播放点击，保留原证据，不能称完整准备过程已验收。来源、命令、审阅及失败记录见[月度日志](changelog/2026-10.md)。
