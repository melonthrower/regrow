# Luna 与框架的职责缩减试验

2026-09-11，入口 `python -m tools.luna_inventory_probe --manifest <JSON> --output <新目录>`。
这是保存帧观察原型，不是正式探索后端。它不导入 GUI 环境，不写生产 ledger，不生成动作、State、Operation 能力或已验证身份。

## 分工与输出

- Luna 看当前完整截图，只给区块 label/function、直接父区、具体控件 label/function/kind/observation，以及 reuse/source_ref 和未确认项。
- 框架为新候选分配局部 r 编号、解析新父行引用，复制明确复用的未改区块，原子拒绝重复引用、未知父区和循环。省略只移出本帧视图，历史文件保留。
- 原型 ref 只代表模型提出的身份连续性，永远带 `identity_verified=false`。控件尚未分配稳定 ID；不宣称已经完成正式 Region/Element/Operation 去重。
- 名称相同不能自动合并。可用本地 `structural_hints` 提示兄弟区控件结构重复、单区控件增长、不同 ref 的多控件标签相同；这些都是需看图判断的疑点，不是拆分/合并真值，也不自动修改图。
- 主输入只有前一候选视图；本试验没有接邻居检索、真实前后动作或旧图视觉审核。模态背景排除仍由 Luna 视觉判断，程序不保证这一语义判断正确。

## 有限预算与证据

manifest 每行含 name/group/screenshot（绝对路径），不同 group 重置上下文。可选 seed_observation、comparison_observation 用于显式的同帧诊断重放；输入副本和来源路径保留，不能当连续探索。

固定 Luna medium，无自动升级；单批 `--request-limit` 为1..10，默认10。动态输入上限16000 UTF-8字节，单请求输出上限6500 token；超限停止，不静默裁剪。结构错误最多一次纠正且仍消耗总请求预算；传输重试被阻止。相同 group 内字节完全相同截图可复用候选缓存，不把相似图片当等价。

保存 manifest/原图hash、实现快照、每帧 before/after、原始请求/回复、http usage 和终态；不记录鉴权头或连接配置。原图返回缓存不等于新的跨图重识别。complete 是模型观察加未确认项的结果，不是审核通过标志。

## 当前结果边界

本轮 Clock 五帧、Writer 两帧是已有开发样例，不是独立测试集。首轮7次请求产生了可解析的候选，但出现 Alarm 同质成员拆分、展开层级缺失、导航编号漂移、Writer 整个窗口过粗等问题。不能把减少字段/审核调用写成低成本准确性已经达标。

本地配置已按用户成本约束切回 Luna medium；正式探索合同和审核流程未替换为本原型。完整样例、定向纠正结果和 token 计数见 `artifacts/traversal_goal_20260909/luna_boundary_20260911/REPORT.md`。

实际总计10次Luna HTTP（首轮7、纠正3），35028输入/7086输出token，0新GUI，原图hash未变。局部增长提示帮助建立了Alarm编辑子区，但列表过分拆分未修正；Writer通用纠正还引入背景Help。7张首轮图中至少5张有明确问题，不能称错误率可接受。26项离线测试通过；精简观察原型与完整探索任务工作量不同，不能按token直接宣称同等任务节省比例。

## 当前图观察与必答局部判定（第二轮独立试验）

入口 `python -m tools.luna_relation_probe --manifest <JSON> --output <新目录> --request-limit 10`，仍不接正式遍历。

第一次调用只看当前截图，previous为空，不能带历史ref。第二次使用当前图在前、历史图在后，框架为含至少两个控件的区块提出keep/split/uncertain问题，为同父区同控件类型结构提出same_list/keep_separate/uncertain问题，并用至少两个相同标签召回最多两个旧区候选作身份判定。召回阈值只决定候选，不授权合并。

所有问题都是动态Schema的必填字段；控件引用枚举为实际编号，不能填写描述或新增按钮。split只允许本区已有且非排除的控件，框架建立子区并保留其余内容；same_list合并候选兄弟区并保留每个成员和物理控件来源。所有问题有证据才能合成结果；漏答、未知编号或重复归属拒收。foreground无法确定和关系uncertain保留缺口。当前观察中本就漏掉或误认的控件无法仅靠引用校验修复。

身份判定仅写identity_proposals，不改变正式canonical ID或跨帧控件绑定。旧图不补入当前清单。精确原图的已有observe_response可通过observation_source重放，需核对原current.png字节一致；来源与hash记录。每批最多5个样例、10HTTP，预算可调低，动态关系输入24000 UTF-8字节；无重试/升级/GUI。

第二轮初始4HTTP发现接口错误（自由字符串引用及无用groups字段），暂停后改严格枚举，在6HTTP剩余预算内完成4张图。原观察复用，失败原文保留，未执行最初计划的Writer Paper及跨页对照。正例：四个闹钟成员合并后控件保留，两个导航复用判定正确，Writer Device内容子区与前景识别改善。反例：Timer不带历史仍虚构三点菜单，第二次核对也误判可见；展开Alarm没有独立正确编辑子区，且把星期选中未知混入foreground未知。35项离线测试通过，视觉准确性仍未达验收。详见luna_relation_20260911/REPORT.md，不把必答/枚举约束当视觉真值保证。
