# 提示审阅：逐项接线图

对应[持续清单](prompt_review_backlog.md)。本图只定位已知影响面，未实现项不能按表直接视为已接受接口。

版本：本文版本由所在 Git 提交固定。代码行号核对的是 2026-10-13 活动工作树：基础提交 b1ed1499f4410d7b5a826b922d46012dc80423e6 加既有未提交候选。下列源码 SHA-256 固定实际字节；文档提交不包含这些未验收候选，也不宣称远端同名源码等于该工作树。后续源码改变时更新本图与证据，不沿用旧行号。

源码路径统一前缀：experiments/clock_manual_20260919/。

| 文件 | 函数与已核对行范围 | 对应项 | 当前依赖及待接入点 |
|---|---|---|---|
| `task_proposer.py` | proposal_schema:7–24；plan_request:54–103 | P09–P16 | 旧inventory/evidence/operations/shared_instances与必填action/conditions；待统一新输出。question_type与回答产物/派生执行形式的映射见U07，不把分类改名直接当作实现 |
| `region_tasks.py` | coverage:30–50；apply_plan:53–141；commit_plan:144–192 | P11–P15；U01–U04 | 旧定义、共享、旧更新在同一事务；85行按action/registration_kind派生task_type，覆盖依赖inventory。待改登记/派生/去重/覆盖并保持原归属、失败及完整性 |
| `task_settlement.py` | task_key:10–12；completion_target:90–92；recorded_match:122–145；partition_findings:271–292；store_findings:306–327；missing_product_fields:25–29 | P13–P14；U01/U05 | 任务键/完成目标依赖action；missing_product_fields按registration_kind要求产物；参数校验/合并直接索引domain。P10/U07与P14须同步，不得静默推断 |
| `task_updates.py` | schema:11–27；decide:66–93 | P11/P13/P14 | 共用参数schema和显式回答检查；保留产物、来源及真实阻碍门槛 |
| `task_knowledge.py` | control_knowledge:20–63 | P11–P13；U02/U04 | 既有知识由任务/共享来源读取；直接知识写入后必须有正常后读，不伪造本地执行 |
| `region_functions.py` | catalog:58–62；register:244–319 | P11/P13；U02/U05 | 参数目录和总结依赖任务支持与domain；直接事实引用、语义参数合并需先定案 |
| `prompt_rules.py` | parts:60–70 | P01–P03/P19 | task_proposal固定清单已只有三份；复用该入口，不机械再删已经不存在的固定片段 |
| `output_contract.py` | prepare:98–146 | P02/P11–P15/P19 | prepare按输出字段追加任务动作登记/知识/参数片段；新字段接入后需消除旧必填规则，纠错沿同一合同 |
| `step_questions.py` | render:112–204 | P01/P09–P16 | 任务问题与render中仍引用operations/inventory/shared_instances；最终问题、材料、输出必须同版 |
| `traversal_scheduler.py` | handoff_no_action:6–65；select_work:68–143 | P09/P12/P14；U03 | 选择工作与none交接包含旧覆盖及类型启发式；先明确触发，不以新观察/无新增推断功能完成 |
| `shared_controls.py` | propose_instances:120–153 | P12；U04 | 当前共享可由清点提案建立；移出任务输出需指定对象层确认入口并保留独立实例 |
| `shared_tasks.py` | synchronize_tasks:8–104 | P12；U04 | 继承依赖已确认对象关系及代表任务；不复制真实执行，不覆盖独立任务 |
| `task_inventory_context.py` | project:112–176 | P01/P09/P11/P12 | 按关联投影任务、知识和历史；移除重复说明及占位但保留来源、具体缺口和真实限制 |
| `action_proposer.py` | render_work:6–62 | P14；U01 | render_work把任务动作写入source.task_action；任务不预设动作后需同步请求内容与来源绑定 |
| `action_binding.py` | bind_action_target:4–11 | P14；U01 | bind_action_target依任务动作及completion_target区分preparatory_action；不能因删字段把目标操作误归准备 |
| `control_context.py` | migrate_split_task:31–64 | P14；U01 | migrate_split_task在对象拆分迁移时读取完成目标与操作；须保留原任务及实际执行归属 |
| `traversal_scope.py` | record_only:14–20；review_request:23–41；exclude_known_external:44–64 | P16/P21；U08 | 当前按真实external_app结果作record_only并复核旧任务；P16移除常驻类别策略时须与本轮范围一致，不只改提示。 |
| `model_transport.py` | with_run_scope:42–50；with_environment_scope:26–38 | P16/P21；U08 | with_run_scope读取run_manifest.exploration_scope，with_environment_scope加入环境约束；复用原来源把范围清楚交给任务提出，不添加第二份配置。 |
| `prompt_delivery.py` | environment_part:30–36 | P16/P21；U08 | environment_part按角色选择真实环境限制；删范围特例不删除有效的本轮操作约束。 |

## 提示文字的实际生产入口

网页由 artifacts/prompt_review/20261012_01/build_review_data.py 生成。共享术语取 dist/drafts/术语定义-历史权衡稿.prompt.txt；其余取 dist/modified/ 下对应提示。原版取 dist/sources/，不能把原版或历史草稿重新拼回新请求。网页分组不是实际发送顺序。本轮把范围判断放到任务提出段、knowledge说明放到首例之前；旧范围文件的修改稿仅保留准备与暂挂，名称暂留原位，避免改出第二条维护路径。

本次与运行 遍历prompt/ 不同的 9 份：

- `共享/术语定义.prompt`
- `共享/当前前景.prompt`
- `发现手册/列表代表项.prompt`
- `任务/区块探索任务.prompt`
- `任务/探索范围与退出.prompt`
- `任务/清点输出约定.prompt`
- `任务/区块功能登记.prompt`
- `共享/参数观察值.prompt`
- `纠错/登记修订.prompt`

参数公共结构仍由 遍历prompt/输出格式/参数发现.schema 定义；修改时覆盖任务提出与旧任务更新所有引用者。动作执行协议本轮没有删除 action。发现引用/几何分工的已实现候选另见现行身份、执行模块；不能以任务字段讨论稿覆盖它。

## 接入核对与证据

- 请求：正常构造完整真实记录，核对固定提示、问题模块、实际字段说明及相关历史，纠错不重新带回旧字段。
- 登记：同控件不同问题不因去掉action被误合并；明确知识不强制操作，准备事实不改原归属；保留失败/条件/未解边界。
- 后读：知识与参数进入原目录及总结；{}不虚假完成，身份缺口及暂挂继续可读；共享事实不冒充本实例执行。
- 验收：保存实际原答与全部纠错/失败，检查身份、任务、知识、图像和下一请求；报告正文、调用总数及总成本，保留未调试检查例。只做静态文档检查时不填行为通过。

本清单及接线图持续维护。本轮更新任务提出网页稿与此处待接入记录，Tier 1 静态检查及陌生读者审阅；0 Luna、0 GUI，无运行代码或运行提示变更。详情在工作区根 artifacts/tmp_tests/prompt_integration_ledger_20261013_01/，其中 source-map.json/source/ 固定本图审计源码，prompt-state.json 固定38份文字对照。没有额外ZIP或截图外传。本轮可读性与范围前置的前态、差异及补充源码定位在 artifacts/tmp_tests/task_proposal_readability_20261013_01/。

## 本图代码字节基准

| 文件 | SHA-256 |
|---|---|
| `task_proposer.py` | `32bc42897eee450fcf675fa227115ca506b04cac0e236d30b2c531d32b95104e` |
| `region_tasks.py` | `e32b6d1498da23fd5c244adc7833cb403d63e1cba3f73b0d98fbbef557683e59` |
| `task_settlement.py` | `e3c6a4e7dad0307f44804a055b27684518d3be6ebe20f4a5ef2fa5f591b504b6` |
| `task_updates.py` | `a251568920a935acd0cf6e0349a0988893ebec4b9b2aac3d8a23f052580cb8a7` |
| `task_knowledge.py` | `fa7eaf74f7f07d12abb623f083637d5b3a4ed508b9c3e476994d69baccadb274` |
| `region_functions.py` | `24035c12ebcbc90be0445d435fd3dc0064aaccaab4496e8a7ac9c1d7a9b5d242` |
| `prompt_rules.py` | `4c765ae76d5fc0448cf8c53ce5971fc7a5af95e123f05dcc1b51b056bf3e9930` |
| `output_contract.py` | `ad4823664c72a22e0494c2c746de60518d740460d31333e379ef65036ed5060b` |
| `step_questions.py` | `b8139ea3518f7d3a1cfbe9390d6a62cee771b6f7a8bb003058b9b754bcb5be62` |
| `traversal_scheduler.py` | `8e61765f0c3eb93da764d573e7ee7a2c99615b262da2789eb814956d5f126703` |
| `shared_controls.py` | `cb79e9be765a045b011c8efa151fdfa4221ddabf090f6ab681afc226b872bce8` |
| `shared_tasks.py` | `3639132b94cdbadbbe08543cddf893bd7030187ec2dd0e1c28844e0bee973068` |
| `task_inventory_context.py` | `efbad464e71000ad5bd4a7bddf20a5c7e2f5ec9583a4bffd4775717a77d372ce` |
| `action_proposer.py` | `c70d3985372f973de698cb39c717234f0bd3b0d24cbc8ffda99c7274b8b57389` |
| `action_binding.py` | `4c9337c9c62b2e8d3d003c8639004054063813f6ec4e74898b2c1c1a708152fc` |
| `control_context.py` | `2921e42e817dad2285edf556b9699b10b868330de42377d2de2483cf08760c38` |
| `traversal_scope.py` | `01cf7ed5d2e5354c649d6442223c72d3a221a9f5ee774c57e26992c41ac17a26` |
| `model_transport.py` | `90cbc7626a522b5c9d102e2ffa7276742a0b90cb935bfcb90a6664aa582a6e48` |
| `prompt_delivery.py` | `9e282016fae3c50dbd04fc722838dbf24f9c447cfe1b7d3836107c65640615bb` |
