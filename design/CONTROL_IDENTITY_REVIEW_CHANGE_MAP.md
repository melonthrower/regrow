# 控件身份复核修改地图

对应[设计](CONTROL_IDENTITY_REVIEW.md)。既有行锚核对自已导出的 `084235cecd82b1d5c6bc55553996957877e4bcf9`；本批实现已获下述有限保存帧验收，待导出固定最终源码锚。新文件不冒用既有行号。

| 仓库相对文件 | 基准入口/行号 | 已实施修改 |
| --- | --- | --- |
| experiments/clock_manual_20260919/control_identity_review.py | 新文件 | candidates/check_request 限已确认 Region 内的原始历史匹配；selection_request/selected_pair 只选一个；attach/reviewed_request 保留完整上下文、附选中历史原图并核对身份决定 |
| experiments/clock_manual_20260919/discovery_step.py | commit:82 | 已提交调用先幂等返回；新发现登记前检查新建冲突，未确认项沿原 partial 路径 |
| experiments/clock_manual_20260919/register_update.py | commit_update:108 | 已有快照幂等返回之后、写事务之前检查；不重复执行动作 |
| experiments/clock_manual_20260919/step_repair.py | submission:91、request:147、Runner.perform:307 | 持久保存候选→选择→一对复核；复用原纠错额度；直接提交从实际请求和原答重算决定，不依赖可变 effective_request |
| experiments/clock_manual_20260919/prompt_delivery.py | effective_role:22 | 选择角色沿原观察/更新平台规则，不无端加入动作手册 |
| experiments/clock_manual_20260919/history_disclosure.py | project:40 | 选择请求保留原纠错的任务、历史、范围和规则投影 |
| experiments/clock_manual_20260919/遍历prompt/纠错/控件身份候选选择.prompt | 新文件 | 当前场景只选一个候选或 null，选择不是身份确认 |
| experiments/clock_manual_20260919/遍历prompt/纠错/控件身份两图复核.prompt | 新文件 | 两个原场景核对，原结果图仍用于动作登记；未决不另建身份 |
| tests/test_control_identity_review.py | 新文件 | 区块范围、重复位置、多候选、证据、直接提交、纠错续接和发送层边界 |

验收案例：真实 Timer 删除后的旧新建回复应复用开始按钮而非继续按钮，原输入目标保持 pending；之后正常局部发现应复用稳定身份。重复位置跳过、无法选择/复核未决、different 不冒充 same、直接提交及幂等边界由聚焦检查辅助验证。实际结果和未验证范围见设计及月度日志，不能以 schema 通过代替身份/任务语义接受。

已验证：完整原生0168选择→0169纠错→正式登记，以及0170普通局部发现；c0028复用、c0034原输入目标pending、0新控件/0GUI，实际任务与帧审计见月度日志。same复用与正常重复按钮重识别已具模型证据；different/uncertain等边界只有辅助检查，不列为原生通过。
