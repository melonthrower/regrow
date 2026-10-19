# 存储组织审查：具体连接图

2026-10-14。与[审查说明](storage_organization_audit.md)一起阅读。**下表全部是已定位的后续修改面，不是已经实现的改动。**本轮只新增审查文档及导航记录，运行存储/代码/prompt/网页均未改。

文档以其所在导出提交固定；完整提交号在本轮Astra包的VERSION中。函数行锚依据活动工作树逐一核对，该工作树含原有未验收修改，不声称与同名Git导出源码一致。实际核对源码及SHA-256保存在本轮证据目录的current-source与source-map.json。首次平铺对象优先复用既有加载/发布入口，不新增数据库、通用实体层或长期双写兼容路线。

| 环节 | 文件、函数与核对行号 | 当前行为 | 拟改范围 | 后续验收案例（本轮未执行） |
|---|---|---|---|---|
| 读写与发布 | `experiments/clock_manual_20260919/discovery_step.py` load:23–27；publish:30–54；commit:82–239 | 读多个区块文件并维护嵌套records；发现/任务/总结共用发布。 | 加载和发布必须支持同一份独立controls，不能再保持第二套可写嵌套副本。 | 同一编号、一次发布、一致的当前指针；失败不发布半张图。 |
| 动作后发布与图片 | `experiments/clock_manual_20260919/register_update.py` commit_update:108–377；materialize_regions:380–429；save_region_images:432–475；rebase:51–59 | 另有动作后发布；分配全局cid，按区块保存裁图和相对路径。 | 控件分配/定位改读全局表；核对删除/合并后不复用已发放编号；图片来源基准明确，旧原件保留。 | 旧控件复认、新建、无裁图、受挡旧图保留；原动作只登记一次。 |
| 底层记录和索引 | `experiments/clock_manual_20260919/region_evidence.py` new_region:41–44；control_observation:56–61；index_actions:84–87 | 初始化嵌套容器；控件观察保存来源，动作反向索引派生。 | 只在主入口改变记录形状；观察字段先保留，索引通过唯一实现计算。 | 省略字段不伪造当前状态，索引仍指真实动作。 |
| 身份候选和历史 | `experiments/clock_manual_20260919/region_candidate_names.py` candidates:6–51；control_candidates:63–96 | 按区块遍历控件，名字映射cid；来源描述来自旧观察。 | 从独立controls按region选择；既有候选歧义、原引用和来源合同保持。 | 同名不同对象不混；无控件纯展示区仍可识别。 |
| 发现与定位 | `experiments/clock_manual_20260919/locator.py` prepare:57–156；request_from_run:159–176 | 查询focus及其控件、全局历史身份和当前观察。 | 读入口统一，不把当前可见性写成稳定归属。 | 全局/局部真实上下文均能找到同一cid。 |
| 任务登记与引用 | `experiments/clock_manual_20260919/region_tasks.py` apply_plan:53–141；commit_plan:144–192 | 任务位于区块，按同用途键拒重复定义，重建task_refs。 | 控件查找改独立表；裸task_refs需明确原任务owner或按主任务派生。任务独立化及无预设action去重单独定案。 | 原任务状态/条件/尝试不因控件存储变化而重置。 |
| 任务与实际操作归属 | `experiments/clock_manual_20260919/task_settlement.py` task_key:10–12；completion_target:90–92；settle_task:148–208 | task_key仍含action；结算区分原任务与实际动作来源。 | 保持两种归属；不以控件当前region替代动作当时绑定。 | 跨区块准备保持原任务，观察所得知识不变成目标点击成功。 |
| 知识与当前观察 | `experiments/clock_manual_20260919/task_knowledge.py` control_knowledge:20–63；current:66–81；refresh:84–89 | 从任务/共享投影知识，按本帧观察投影text/state。 | 统一向独立控件提供知识；可重算投影是否持久化另议。 | 条件、来源、失败、未解问题及观察/执行区别保持。 |
| 共享 | `experiments/clock_manual_20260919/shared_controls.py` link:10–29；refresh:32–70；propose_instances:120–153 | 共享组挂代表区块；控件存组引用，结果按成员重算。 | 首批统一控件查找；组独立化要保留原组引用和关系依据。 | 代表与成员可查，实例不凭共享获得本地执行记录。 |
| 共享任务 | `experiments/clock_manual_20260919/shared_tasks.py` synchronize_tasks:8–104 | 成员任务以shared_task_ref/shared_result引用代表，保留本地独立任务。 | 任务不因新存储再复制尝试；失效共享仍能解除。 | 代表结果撤回后成员不继续显示已完成。 |
| 合并、改归属 | `experiments/clock_manual_20260919/control_records.py` merge:32–46；remove:49–58 | 按rid查控件，合并观察及动作/任务引用。 | 全局控件操作与归属查找一致，保留原来源和alias。 | 同名但不同实例不自动合并；已引用对象不能无痕删除。 |
| 区块合并 | `experiments/clock_manual_20260919/region_records.py` merge:22–85；rewrite:12–19 | 合并容器并重写区域引用，图片相对路径随归属调整。 | 统一对象关系与路径；避免重新复制一份全局控件。 | 合并前后原动作/任务引用可追溯。 |
| 拆分与任务目标 | `experiments/clock_manual_20260919/control_context.py` migrate_split_task:31–64 | 确有拆分时迁移目标或保存completion_action；准备任务仍归原问题。 | 独立控件当前归属与任务既有归属分开处理。 | 改归属只影响获准的目标，不重写历史尝试。 |
| 请求与后读 | `experiments/clock_manual_20260919/page_context.py` build:110–217；attach:414–464 | 从嵌套记录投影共同地图、任务与相关历史。 | 使用统一对象读取，按本步问题选择材料；不在每处重建旧嵌套。 | 真实发现、任务、动作、更新请求关联一致，必要来源没有遗漏。 |
| 范围与历史选择 | `experiments/clock_manual_20260919/context_scope.py` select:95–126；identity:145–168；map_knowledge:204–226 | 选择区块/控件/任务的关联视图。 | 控件读取改变，范围语义不顺带改变。 | 不同任务不串历史，直接准备过程仍可提供。 |
| 功能总结 | `experiments/clock_manual_20260919/region_functions.py` summary_projection:114–133；register:244–319；request:322–338 | 读任务、动作、控件、支持事实并登记功能与参数。 | 保留完整功能结构与支持关系；一段description不能替代总结。 | 总结时机不变；参数条件和未验证范围进入下一步。 |
| 纠错与复合事务 | `experiments/clock_manual_20260919/repair_stages.py` accept_with_edits:41–72；preserve_repair_aliases:22–31 | 纠错可改登记再刷新请求，保留旧名字映射。 | 同一事务中更新独立对象与受影响引用。 | 纠错失败不半发布；原答保持，已执行动作不重新投递。 |
| 原子指针 | `experiments/clock_manual_20260919/knowledge_transaction.py` pointer:9–12；transaction:16–26 | 复合修订暂存当前指针，成功后替换。 | 保留已有事务语义，不把平铺变成多文件非原子写。 | 中断后当前指针仍指完整版本。 |
| 图与图片展示 | `experiments/clock_manual_20260919/region_graph.py` asset:21–31；project:34–67 | 直接读区块文件、嵌套控件与相对图片路径。 | 改读同一个新格式，不能只让模型链能读。 | 同一版本的名称/图像/任务/动作展示一致。 |
| 冻结图下游 | `gui_rewalk/src/core/scenario/collection_graph.py` load_collection_graph:31–60；collection_relations:63–84 | 按知识指针读区块文件，携带功能/任务与导航关系。 | 后续迁移须单独评审冻结图读入边界，本轮不修改采集实现。 | 冻结旧图保留，指令生成和采集不误读当前状态或伪造边。 |
| 下游身份图 | `gui_rewalk/src/core/scenario/collection_visual_guard.py` snapshot_controls:87–103 | 按区块路径读取控件，构造rid.cid复合引用。 | 新对象查找不能静默丢下游复合引用；固定图适配独立验证。 | 身份图与点击范围分别可追溯，不以图像匹配证明操作效果。 |
| 审计工具 | `tools/stepwise_quality/evidence.py` snapshot:51–54；graph_items:116–169 | 质量检查直接读取旧目录和控件观察。 | 检查工具随新格式识别，不将读不到记录当不存在。 | 缺图/未决项仍明确，原审计证据不丢。 |
| 动作请求 | `experiments/clock_manual_20260919/action_proposer.py` request_from_run:65–134 | 原任务与当前动作目标分别绑定，读取区块内控件及候选。 | 统一独立控件读取；保留当前任务和准备来源。 | 完整真实请求仍包含正确任务/控件/历史。 |
| 结果请求与原动作 | `experiments/clock_manual_20260919/result_updater.py` build_attempt_update:121–202；rebuild_retained:205–222 | 按原执行绑定重建更新，并处理保留的旧请求。 | 从新快照查对象，已执行动作仍使用原绑定/后图。 | 中断续接不串任务、不重做动作。 |
| 历史字段读取 | `experiments/clock_manual_20260919/control_history_context.py` last_reported:3–5；describe:23–42；comparison:45–64 | 从历次观察选择最近明确字段、未决疑问与实际证据。 | 原图标映射正确，保留写读对应；独立控件不能仅取最后一行而丢未重报字段。 | 图标描述、旧疑问及其来源可供下一次识别。 |
| 导航读取 | `experiments/clock_manual_20260919/stepwise_flow.py` shortest_known_path:139–169 | 沿区块transitions、actions和controls找已观察路径。 | 对象查找变更后保持实际执行/前景/条件判断。 | 不能因控件不嵌套就丢边或把旧可见性当当前。 |
| 最终发送与原件 | `experiments/clock_manual_20260919/model_transport.py` call:114–173 | 落盘最终request、字段合同并调用原模型传输。 | 卡片或新存储不新增调用账；正常构造、校验和留存链保持。 | 保存完整请求/原答，含纠错和失败。 |
| 区块拆分新身份 | `experiments/clock_manual_20260919/region_behavior_split.py` before_objects:17–33；apply:103–141 | 从动作前对象创建新区块/控件；登记separated_from/distinct_regions并建立必要共享链接。 | 全局表中分配新身份，明确与原对象的差异及原帧来源；不能只迁移任务目标。 | 新旧身份不误并，原图/来源/共享关系完整，后续再次识别仍区分。 |
| 动作有效归属修订 | `experiments/clock_manual_20260919/action_owner_correction.py` apply:24–90；request:93–130 | 更改登记动作的有效归属、相关边及来源；撤回旧任务失效的完成依据，保留审计。 | 同步动作有效归属、独立控件及原任务引用；动作是否独立保存另议，原投递回执不改写。 | 已执行动作不重新投递；旧错误完成不继续传播，原归属修订可追溯。 |

普通动作请求/结果请求还分别由action_proposer.request_from_run、result_updater.build_attempt_update承接；它们及任务清点依赖上述对象与任务视图。共享schema里的region_index/previous_name与内部存储形状不是同一个合同：本轮不因物理平铺就自动改输出协议。需改输出时再一起处理正常校验、纠错、登记和后读。

下一批实现的最小验收应覆盖：旧身份复认/新对象、同名不同控件、纯展示区、跨区块准备、共享实例、原图/裁图路径、异常后已执行待登记、功能总结与正常下一步请求。使用正常入口与完整真实记录；原Luna回复走原校验/纠错/登记。当前三份记录只用于结构审查，不是这些行为案例已通过。测试量按实际改动合同确定，不把全套回归当本次文档要求。

只读字面引用搜索还保存了91个文件中的665行候选入口供导航（含重复语句与非独立行为）。它不是“665处必须手工修改”的统计，也不代替上述实际路径核对。
