# 修改地图（V2，已实现且有限验证）

基线：[GitHub 822b7c9](https://github.com/melonthrower/regrow/tree/822b7c9f241aaac8dec00bd8e41749b5bb89397f)。以下行号固定指向该提交，不代表候选工作树。实现差异和新冻结hash随审阅包提供；接受后另给固定最终提交的源码地图。

| 文件 / 函数 / 基线行号 | 原行为 | 本批实现与验收 |
|---|---|---|
| experiments/clock_manual_20260919/task_selection.py / attach / 27–37 | 当前排除先于deferred导航保留 | 导航保留先判断目标runnable；排除目标仍停止 |
| experiments/clock_manual_20260919/run_progress_session.py / run_session / 24–70 | 主循环退出后仅整理一次并返回 | 整理回到循环，正常step判推进/空闲；尾段预算、暂停及独立知识账本 |
| experiments/clock_manual_20260919/run_task_step.py / _run_step.current / 163–179 | 既有advance_unfinished及正常请求重建 | 核对复用，无修改；不是新调度器 |
| experiments/clock_manual_20260919/task_deferral.py / choose_unfinished、advance_unfinished / 123–151 | 范围内未完成目标选择 | 核对复用，无修改；snapshot变化不作推进证据 |
| experiments/clock_manual_20260919/run_task_step.py / finalize_knowledge / 369–405 | 有界0GUI正常登记 | 核对复用，无修改；HTTP计入session，不把knowledge_complete当全图完成 |
| tests/test_idle_continuation.py / 新文件 | 无 | 导航范围、收尾续接、无进展停止、多账本及暂停案例 |

现有续接helper：artifacts/tmp_tests/clock_watch_20261006_01/continue_budget.py（本地实验记录，不导出为框架第二入口）。旧会话结算账本汇总后设置run_manifest.session_limits，session_command启动指定冻结源；23→77，只扣一次。新实机验证与整批续跑分开记录，不新增GUI总量上限。
