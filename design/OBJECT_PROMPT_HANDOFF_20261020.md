# 四对象Prompt与身份阻塞：Astra接手说明

这是用户明确授权同步的未完成研究检查点，不是发布或整体验收版本。四对象已经接入正常调用，不再只是design目录的审阅稿。

## 维护入口

- `src/regrow/prompts/对象/控件.prompt`、`区块.prompt`、`任务.prompt`、`动作.prompt`是唯一正文。统一BEGIN_PROMPT_BLOCK、稳定id和requires依赖；调用选择同文模块，不另写字段定义。
- `src/regrow/prompts/流程/调用组成.json`的object_modules配置负责选择；`prompts/object_blocks.py`负责加载/依赖/组装，`prompts/output.py`接入正常调用。
- `design/prompt_objects_review/README.md`仅作链接入口，附件原稿为历史资料。

## 已实施改动

任务提出operations仅新任务，task_update处理已有任务；任务类型目标从task.type读取。建议省略保留、显式清空、defer/answered清除旧建议。补充必填/条件必填及数组项类型展示。schema错误不误转功能支持复核。身份选择及比较引用统一control.identity。

## 验证与未完成

83项聚焦检查通过；正常真实记录保存帧10次Luna、0GUI，五类阶段各自验证，非连续端到端。正式全新Settings运行48/100停止，52次未用，9GUI命令、8已登记动作，3任务完成/1待完成。整体语义未接受。运行原件和截图保留本地，不随源码上传。

## 主要阻塞及检查方向

同一个快捷键搜索框连续输入，窗口由Shortcuts变为Search Results。0044身份比较未接统一定义并判different；0045沿用旧身份被拒，0046改报新对象又撞同名，0047补图后阻塞。修接线后0048仍以标题不同判different，尽管实际system已明说标题/模式/输入变化不能单独新建身份，且提供了连续操作历史。

复核材料中既有“先前判断待复核”，又保留旧错误消息“该旧控件引用已被否定…不重复提交同一复用引用”。这是待检查的上下文干扰，不是已证明的根因。不要再默认对象定义没写清楚；先核对review_material、attach及history呈现，区分历史判断与本次指令。

a0010输入已经执行但尚未登记，pending保留。不得重投GUI、编辑模型原答、强制same、重置100总预算或普通纠错次数。额外一次同证据规则复核已用，普通repairs保持2，最终blocked。

其他未接受现象：参数探索持续追加问题；空数组呈现“空列表”进入知识；设备当前状态混入知识。不要扩展成未经讨论的新框架或叠加禁令。

## 验收要求

用正常框架入口从真实运行记录构建完整任务/历史/图上下文，实际Luna原答走正常校验、纠错、登记。静态或schema通过不能替代语义接受；保存帧验证不能宣称新GUI成功。当前没有完成全框架门禁。

## 当前源码定位

- `src/regrow/prompts/object_blocks.py:9` — `catalog`。
- `src/regrow/prompts/object_blocks.py:90` — `select`。
- `src/regrow/prompts/object_blocks.py:111` — `apply`。
- `src/regrow/recognition/control_identity_review.py:202` — `review_material`。
- `src/regrow/recognition/control_identity_review.py:280` — `attach`。
- `src/regrow/recognition/control_identity_review.py:370` — `recheck_request`。
- `src/regrow/recognition/control_identity_review.py:390` — `queue_recheck`。
- `src/regrow/prompts/output.py:157` — `prepare`。
- `src/regrow/traversal/step_repair.py:398` — `perform`。

导出副本验证：上述七组聚焦测试83 passed，git diff --check通过；仅源码同步验证，没有新增Luna或GUI。用户于2026-10-20明确授权将此未完成状态提交并推送供Astra处理。
