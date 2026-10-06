# regrow 角色模块重构

用户在核对 Go-Browse、GUI-ReWalk、Agent-S 后要求按角色组织实施。本版替代此前11个功能目录的提案，采用现有源码根内并列的五个真实职责文件，主程序与调度器连接，公共身份/共享/登记模块保留唯一实现。不搬源码根或运行证据，不改prompt内容、schema语义、预算或探索策略。

| 角色入口 | 本批承接的真实职责 | 保留的公共连接 |
|---|---|---|
| locator.py / Locator | 发现schema、上下文、请求、按需观察和局部控件定位 | discovery_step负责正式发现登记/快照；身份与匹配沿原模块 |
| task_proposer.py / TaskProposer | 任务schema、历史/控件/共享上下文、提示组装和规划请求 | region_tasks负责规划校验/登记和覆盖状态；Runner连接纠错 |
| action_proposer.py / ActionProposer | 已选任务/导航的动作请求与提案 | 复用现有动作绑定，不另建actor转发壳 |
| action_executor.py / ActionExecutor | 投递前检查、真实执行、pending、回执与后图 | 保持原执行顺序与平台适配 |
| result_updater.py / ResultUpdater | 更新schema/请求/候选校验、正常和中断补登记 | register_update正式登记；观察判断不直接发布 |

run_task_step/run_progress_session保留主程序入口。发现文件中的导航/局部检查安排和目标退出移到traversal_scheduler；控件聚焦/重新观察仍属Locator。共享关系保留shared_controls；任务投影与解除关系后的任务处理集中shared_tasks。关系刷新后立即同步任务，再清理失效任务，不能延后到最终发布才同步；本地attempt和findings不复制、不丢失。

现有旧函数出口直接绑定到新唯一实现，供已知调用方使用；正常构造/纠错路径转到角色模块。避免互相导入角色入口产生环：角色不调用旧请求出口；正式读写仍依赖原登记模块。互相依赖的角色/登记模块使用原延迟加载机制。冻结/候选加载继续绑定所选源码目录；本批仍是顶层Python文件，原冻结和资源布局可直接覆盖，需用冻结副本验证而非推定。

验收：源码职责确已迁移；代表性完整真实run构造的新旧请求等价；聚焦角色/发现/任务/共享解除/更新/续接测试；独立陌生初读后实际Luna原答经正常Runner与登记检查。保存帧0GUI，不称导航实机成功；不重复此前无关全门禁。原范围外菜单可离开、partial可信任务继续、已投递不重做合同仍需相邻检查。

基线49a3b371b92a0c9080889a56be193facb56c09f1。实施/验证状态及精确定位另见CHANGE_MAP与月度日志，不能将本设计文字当验收结果。
