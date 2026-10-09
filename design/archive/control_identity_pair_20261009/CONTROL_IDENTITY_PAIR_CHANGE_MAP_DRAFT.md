# 两图复核草稿修改地图

基准：私有 melonthrower/regrow 已导出提交 `084235cecd82b1d5c6bc55553996957877e4bcf9`。下列既有行号核对自该提交；草稿尚未导出，无已接受新提交。设计见 [草稿](CONTROL_IDENTITY_PAIR_DRAFT.md)。

| 文件（仓库相对） | 基准入口 | 草稿变更及状态 |
| --- | --- | --- |
| experiments/clock_manual_20260919/region_identity.py | for_request，13–24 | 原观察归一/列表角色复用之后调用控件冲突检查；发现/更新及直接提交共用。已编码、仅辅助验证。 |
| experiments/clock_manual_20260919/step_repair.py | request，218–221；Runner.perform，394–398、430–439 | 错误保留一对候选；纠错附原场景和临时决定；保存 effective_request 再校验/登记。已编码、仅辅助验证。 |
| experiments/clock_manual_20260919/control_identity_review.py | 新文件，无既有行号 | candidates/unique_pairs 限同 Region 原始候选；check 拒绝一对一新建冲突；attach/reviewed_request 复用正常纠错、绑定证据与决定。 |
| experiments/clock_manual_20260919/遍历prompt/纠错/控件身份两图复核.prompt | 新文件，无既有行号 | same/different/uncertain 的场景判断与登记方式，不额外点击。 |
| tests/test_control_identity_review.py | 新文件，无既有行号 | 15 项局部及 Runner 辅助检查；不替代真实上下文原生 Luna 验收。 |

验收待办：唯一正例正确复用、真实不同对象保留、同屏重复不引发逐对调用、更新未决不伪造身份/重放 GUI、发现 partial 与中断续接。原 Timer 多候选样本是否纳入、如何纳入，等用户确定规则；当前不能称该例修好。

证据/命令/失败：外层 artifacts/tmp_tests/control_identity_pair_20261009_01。原 Luna 样本位于 artifacts/runs/task_update_luna_20261009_01/prepare-v4；只读，不改原回复和历史图。
