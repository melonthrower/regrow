# 具体改动表（候选，尚未实现）

源码导出基线：[fceb3b74da9a86c3202de71f86d12c0ab80a09d6](https://github.com/melonthrower/regrow/tree/fceb3b74da9a86c3202de71f86d12c0ab80a09d6)，冻结目录 external_app_judgement_20261103_02/source-v8。以下同时列出该提交冻结源和当前工作副本行锚；当前未提交差异只是拟议基线，不作为已接受源码。candidate/ 只有候选 Prompt，不含实现。

|仓库路径/函数|导出基线锚点|当前锚点|拟修改|
|---|---|---|---|
|src/regrow/recognition/named_references.py|wire_schema L89；encode_objects L143；prepare L183；decode L314|wire_schema L89；encode_objects L143；prepare L183；decode L314|取消新合同父字段/编码/报错；旧已发合同读取按原合同机制保留，不把纯知识修订改成归属变更|
|src/regrow/recognition/discovery_completion.py|partition L38；resolve_gaps L89|partition L38；resolve_gaps L89|撤销祖先未确认的级联暂缓，保留区块自身身份和控件归属要求|
|src/regrow/recognition/discovery_delta.py|schema L10|schema L10|删除父字段的特殊豁免，实际新schema无该字段|
|src/regrow/recognition/ownership_review.py|父级引用 L620|父级引用 L620|independent_target：目标接纳只检查直接实际区块，不再沿物理祖先链|
|src/regrow/records/observations.py|materialize_regions L20|materialize_regions L20|取消parent_index检查和parent_region写入|
|src/regrow/records/region_evidence.py|new_region L30；region_records L48|new_region L30；region_records L48|新对象不建父字段；旧导入不恢复父级|
|src/regrow/records/object_store.py|Region L42|Region L42|Region加载边界忽略退役parent_region，历史原件不改|
|src/regrow/records/registration_diagnostics.py|parent_cycles L167；collect L198|parent_cycles L167；collect L198|删除父级合法性/环/仅依父子关系的重复归属检查；身份防重仍保留|
|src/regrow/records/page_context.py|build L90|build L90|当前区块平列，保留当前控件与实际访问来路，不凭包含构树|
|src/regrow/records/region_records.py|父级引用 L10|父级引用 L10|取消parent_region作为活动Region引用字段的维护|
|src/regrow/records/region_behavior_split.py|apply L91|apply L91|取消父级约束，真实来源/新身份检查保留|
|src/regrow/traversal/object_registration.py|required_paths L52；remap_gaps L202|required_paths L52；remap_gaps L202|只跟随控件到所属区块，不追溯物理父级|
|src/regrow/traversal/proposal_revision.py|_references L143|_references L143|取消父区块索引重映射，控件/访问目标引用重映射保留|
|src/regrow/traversal/traversal_scheduler.py|select_work L111；offer_foreground_navigation L273|select_work L111；offer_foreground_navigation L273|不按物理父级剔除前景；原任务和实际来路继续决定推进|
|src/regrow/traversal/task_routing.py|parent_region L35|parent_region L35|仅将访问来路命名改清楚，不删除有证据的路径行为|
|src/regrow/traversal/action_context.py|render_exploration_tree L84|render_exploration_tree L84|取消按持久parent_region附加子区块清单，访问路径不改|
|src/regrow/traversal/correction_prompts.py|父级引用 L62|父级引用 L62|删除退役父级错误代码|
|src/regrow/prompts/prompt_material.py|相关规则 L588,589|相关规则 L588,589|取消活动关系材料中的包含它的区块；历史原答原件保留|
|src/regrow/prompts/区块识别/功能区块划分.prompt|相关规则 L2|相关规则 L2|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/对象/区块.prompt|相关规则 L31,91,92,93,194,195,196|相关规则 L31,91,92,93,194,195,196|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/共享/区块身份复用.prompt|相关规则 L3|相关规则 L3|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/共享/行为差异分离.prompt|相关规则 L15|相关规则 L15|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/任务/清点输出约定.prompt|相关规则 L25,27|相关规则 L25,27|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/纠错/组织原则.md|相关规则 L37|相关规则 L37|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/输出格式/首屏观察.schema|相关规则 L39,44,84|相关规则 L39,44,84|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/输出格式/动作后更新.schema|相关规则 L24,29,73|相关规则 L24,29,73|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/输出格式/动作后Region增量.schema|相关规则 L24,29,77|相关规则 L24,29,77|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/流程/调用组成.json|相关规则 L171,605,607,659,962,1281,1283,1335,1820,2245|相关规则 L171,605,607,659,962,1281,1283,1335,1820,2245|见 PROMPT_REVIEW.md 完整对照|
|src/regrow/prompts/纠错/字段占位.json|相关规则 L98|相关规则 L98|见 PROMPT_REVIEW.md 完整对照|

相邻合同与验收见 DESIGN.md。新增文件仅为本审阅包，不虚构源码旧行号。后续实现改变源码后必须重新给行号与差异，不能沿用本表宣称验收。

补充直接消费者（以下均当前源/冻结源共同锚点）：

- src/regrow/prompts/target_observation.py：冻结 L122,123；当前 L122,123。现有可选 children 遍历兼容平列输入，列为相邻合同核对；不强制改写。region_scroll 仅“当前区块树”提示改“当前区块列表”；不改控件 ID/当前图坐标合同。
- src/regrow/traversal/region_scroll.py：冻结 L13,14,15,30；当前 L13,14,15,30。现有可选 children 遍历兼容平列输入，列为相邻合同核对；不强制改写。region_scroll 仅“当前区块树”提示改“当前区块列表”；不改控件 ID/当前图坐标合同。

历史合同接收：named_references.py 的 wire_schema/encode_objects/decode 父字段转换与 proposal_revision._references 索引处理，仅在实际旧合同需要时保留；不恢复持久边。代码实施后必须列实际保留条件及原生验收结果，不能按设计稿宣称已可续接。

page_context.build/page_context._display 内的 tree（L187/L227） 的具体接口：现有 current_tree 包装键保留，平列 Region 节点不再输出 children；page_context._display 内的 tree（L187/L227） 退出对必有 children 的假定，原已发上下文的可选 children 仍可呈现。这是当前材料的投影格式，不恢复持久包含边，不引入另一个区块清单。
