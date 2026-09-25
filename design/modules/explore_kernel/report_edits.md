# 同帧清单的增量纠正

2026-09-19：纠正卡预览逐操作列出`handling`、`reason`、`operation_ref`、`parameter_status`和`parameter_summary`，并明确新增/整项替换必须提交完整操作对象；只改字段时使用字段路径，避免简写对象覆盖既有必填字段。编辑解析失败仍保留已物化但未发布候选，并区分整批未物化、暂存候选已应用和正式发布。本轮仅离线合同验证。

2026-09-18：运行时从当前帧/Attempt的缓存生成`inventory_edits`合同，主请求system/user/Schema、状态栏、纠正卡及解析共用。非法混填按实际非null字段、类型和值摘要反馈，不再默认previous_action。路径非法整批不应用；编辑成功但候选解析失败时保存新候选并明确“已应用到暂存候选、未发布”。退出编辑用所有提交字段null并说明reason，先撤下缓存，下一轮重判；不能在edits轮填写screen.identity=uncertain。

2026-09-17后续验证：同一候选由主Agent修正6处视图描述后原审核same；独立测试Attempt可原生入账并结算一次，原a207不改。新VLC短批另有一次真实“反馈→remove后台栏→审核/身份通过→正式结算→选下一待办”，9HTTP/1GUI；尚未验证连续2–3目标全部完成。详见本月记录及view_description_finish_20260917_01证据。

`report_edits.py` 提供候选清单内部的 JSON Pointer 编辑，`contracts.py` 解析，`runtime.py` 管理同帧缓存和提交。它不编辑已提交账本，也不替代 region_refinement。

## 触发与输入

新清单解析失败或入账前分区预审拒绝时，若位置提议的结构和引用合法，runtime暂存该位置、清单候选及原回执候选。位置尚未发布。主Agent收到“清单增量纠正”卡，包含区块/控件/动作索引、名称、控件observation和必要父引用，不重复完整参数和历史图。补缺项时先保留当前正确条目，真正的集合控件才拆分，原条目错误才有依据地replace/remove；程序不根据名称自动决定哪项正确。

主回复新增可空`page_report_edits`；普通轮为null。编辑轮仅填写非空编辑数组、app_scope/strategy/reason，screen、previous_action、page_report、action为null，不混用检索、分区修正、代表探针或任务切换。严格API Schema要求根字段存在，但旧回复解析仍允许省略。

每项为`op=add|replace|remove`、`path`、`value_json`。add/replace的值编码为JSON字符串，例如字符串值编码为`"新名称"`；对象/数组也编码为JSON。remove的value_json为null。内部解析为普通JSON值后操作候选副本。

- 仅允许`/regions/...`、`/survey_complete`、`/coverage_note`；不允许整体替换`/regions`或更改位置/动作/回执。
- 新控件可追加到`/regions/i/elements/-`；新区块追加到`/regions/-`。数组删除从大到小，父行引用仍须正确。
- 一轮最多64项；批次路径错误不修改原候选。编辑成功但字段仍非法时保留编辑后的未提交候选，下一轮反馈与索引基于该版本。
- 未被编辑的内容逐字保留，避免补一个控件时重写导航或其他正确分区。新增控件仍需完整字段，完整合成清单仍过解析、分区、身份及结算校验；纠正中删掉新控件后也不能作为纯旧引用确认而跳过预审。

## 证据和边界

缓存绑定当前截图字节和pending Attempt；换帧、换Attempt、恢复或纠正通过后失效。先退出编辑阶段，下一轮才可用uncertain重新判断位置。位置保留只适用于清单解析/分区预审错误，不冻结Element身份审核中需要重新判断的来源。

缓存回执只是一份原候选，仍须原结算校验。增量不能继承缺失或其他Attempt的回执。会移动或替换回执`report_index`所指Region行的编辑被拒绝；需要这种更改时先退出编辑，再提交同步纠正的完整清单与回执，不能默默改因果归属。

`page_report_edits_applied`记录当前截图、实际编辑和`published=false`；只有后续正常提交才形成正式图记录。`partition_correction_screen_retained`同时保存被忽略的位置改写与保留提议。原模型回复与图片不修改，不生成GUI动作或虚构边。

2026-09-17：`apply_report_edits`可收集逐项before/after事实；路径按每项编辑执行当时解析，整批失败不发布半份trace。runtime仅把本轮成功物化的trace传给原分区审核，不改变编辑结果，也不自动补回被删条目。审核收到同图/Attempt的有界旧候选与原意见，旧路径仅解释历史对象，最新反馈仍须指向当前候选。独立Luna诊断补齐既有遗漏并保留原项，但最终因列表/卡片表述争议仍被拒绝；不是a207已结算或实机恢复证据。

已完成离线事务、未改内容保留、帧/Attempt隔离、严格API Schema与pending引用检查。Luna保存帧已实际使用字段增量添加控件，但Luna-only的复杂页三轮纠正仍有失败；模型配置和最终识别效果须查本次实验报告，不把接口接线当作准确率验收。

2026-09-19：无同帧修单基底时，运行时提交合同的提示、Schema和解析器统一禁用page_report_edits，要求完整纠正报告及当前位置/真实回执；误交edits不再提示改交纯edits。有缓存时沿用原编辑/退出合同，不自动暂存身份未确认的候选，也不改变引用检查。原生运行时覆盖普通清单引用拒绝→误交edits→正确反馈→完整修正→原生结算，实机证据另记。

编辑阶段Schema同时限定app_scope=target_app，与既有validate_edit_submission一致；需要重判应用归属时沿既有全null退出，再在下一观察轮提交新位置，不允许把external_app与edits混交。
