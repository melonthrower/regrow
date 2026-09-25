# Region工作范围与派生视图

2026-09-19 用户纠正失败范围：未知动作不再一律结束应用。仅在原生已知State/目标前景核验通过、无新清单待审且有活动依赖任务时，沿原scheduler将该任务deferred，保留Attempt.uncertain和覆盖缺口，丢弃同轮下一动作，由下一轮原Region调度选择独立操作。新/未知落点、外部前景、清单纠正未完成、无任务恢复继续原保护；未新增结果协议或重置次数。

2026-09-18 V2：直属覆盖共用现有清点gap。独立遗漏显示`inventory_gaps`，未知缺项数量为null而非0；即使所有已登记直属操作已验证，也不据此宣布区块完成。缺口通过原events保存恢复，既有survey暂挂与同区任务选择继续使用原调度，不新增漏项对象或队列。

2026-09-18：局部资格缺口保留在原直属分母中，其他合法直属操作继续，剩缺口记blocked。事件派生的资格限制同时约束绑定查询、显式选目标、路线及投递；已有可信新路线的源State/目标State/操作组合可唤醒原deferred Task返回复查，Operation仍deferred。相同路线的重复Attempt、重启和截图变化不唤醒。正常工作Region不被补探抢占；到达后原分区审核确认新的可执行资格，才解除并按当前owner投递。失败复查再次暂挂，事件记已用路线，不无限回访。普通恢复保留这些事件和成功记录；实验声明仍由原配置重建。

原生假环境贯穿用例在`test_explore_partition_review.py`：R的A/B成功、C隔离，S真实假GUI推进取得新路线；checkpoint/restore和声明重建后沿图返回R，重新审核绑定，C成功使2/3→3/3。反例保持C受阻、没有投递、不因恢复或相同路线无限唤醒。该用例证明程序接线，不证明模型或实机补探成功。

2026-09-17 调度约束补强：选定工作Region后，是否已完整清点当前前景不再决定是否进入全局独立任务选择。未清点时保留本区活动焦点及原有限准备/恢复，必要当前survey仍属于本区工作；无活动焦点也先选择本区适用直属目标。最短路径只用于到达该目标。主Agent的next_operation_ref同时不得越过活动工作Region或声明范围；只有原region_work_closed记录complete/blocked及未完成覆盖后，才允许自动换区。显式exploration_goal且未建立自动工作Region的原语义不变。

2026-09-17。实现：`core/explore/region_work.py`，接入TaskScheduler、runtime上下文和既有进度gaps。唯一主入口仍为`run_visual_traversal.py --modular-explore`。

- `region_coverage`按Region直属canonical操作聚合合法本地绑定。区分verified、observed_only、pending、pending_condition、restricted、blocked_unclassified、failed、unknown_identity、out_of_scope。延期自然语言不自动归因为权限或条件。
- 默认范围是已发现直属操作；内部`declare_region`可预先声明canonical集合、条件/限制及退出操作，活动轮不得缩小声明。不是新CLI或模型回复字段。覆盖完成需要范围内全部verified、相关variant已有survey、无待结算/未知声明引用；队列为空不等于完成。此判断不证明尚未发现的控件已经穷尽。
- 子Region来源为已有containment与真实成功边的revealed关系，单列保留；父完成不递归等子完成。选择、上下文计数与已关闭轮次的进度缺口共用覆盖函数。
- 轮内选当前适用绑定或原路由可达的直属Task，保留现有动作检查。有限返回只用于有已进入证据或明确声明的工作范围；已有no_effect/uncertain返回不无条件重试。无安全可达目标记blocked，未改变签名不立即重开；不批量重排失败任务。
- `environment_view`展示工作路径、当前前景、目标、本地owner、直属操作与折叠兄弟；operation尺度显示已观察条件，region尺度折叠历史条件。来源标签是观察，未知选项名称/依赖关系不猜。pending不声称来源就是当前落点。
- 轮次与声明为调度器瞬态；恢复清空活动轮和封闭签名，实验从保存配置重新声明。关闭事件保留声明及覆盖审计，不新增ledger顶层schema/迁移。精确恢复任意实验声明不属于本补丁承诺。

离线：286项聚焦回归通过；Allow/Criteria、父子分离、范围不缩水、返回后同区继续、另区调度、条件限制、Alarm适用来源均有原生用例。真实VLC账本的最终主请求亦保存。

实机限制：`artifacts/region_work_20260917_01/live`在Media声明3项中沿用已验证1项，尚未增加；一次Back后主Agent和State审核误认仍有Chapter子菜单而停止。没有完成一个Region再转区的实机证据。该停止后补齐的deferred任务卡只做了离线验证，实际运行代码另存frozen_source。
