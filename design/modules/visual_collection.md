# 当前 Region 图指导采集

维护入口是 `gui_rewalk/run_capability_task_synthesis.py` 与 `gui_rewalk/run_visual_collection.py`，共用 `src/core/scenario/collection_graph.py`。旧 M13 参数、recipe 执行器、scenario delta/SeedPlan 与多模型开关不是这两个入口的当前合同；旧说明保存在 [归档](../archive/2026-10-02-framework-wiring-fix/visual_collection_before_wiring.md)。

## 输入与执行

```sh
python gui_rewalk/run_capability_task_synthesis.py path/to/knowledge_current.json --request '查询指定城市并查看候选，不添加城市' --output new/instruction.json
python gui_rewalk/run_visual_collection.py --instruction new/instruction.json --validate-only
python gui_rewalk/run_visual_collection.py --instruction new/instruction.json --initial-app android_clock --vm-provider android --avd-name YOUR_AVD --android-console-port 5698 --android-grpc-port 8698 --max-turns 14 --output-root collections
```

Android 的 initial-app 使用 config.APP_PACKAGE_MAP 中的应用键（如 android_clock），不是包名。端口和 AVD 必须选择本次拥有的环境；示例不授权附着别人的实例。桌面入口使用 `--vm-provider vmware --path-to-vm <vmx>`。模型由既有本地 API 配置提供，入口没有 `--region-ledger`、`--graph`、`--model-backend` 或 `--headless` 开关。

- 输入可为 ExplorationLedger 或冻结运行的 `knowledge_current.json`。逐步图读取指针指定的 `knowledge_snapshots/.../regions/*/region.json`，原样提供功能、参数条件、未确认事实与任务依据；不会伪造 State 或已验证功能。
- 生成物记录相对 `source_ledger` 和必需的 `source_ledger_digest`；已存在的指令文件拒绝覆盖。逐步摘要覆盖指针、Region JSON 和实际消费的身份图，普通 ledger 摘要覆盖文件本身。
- `--validate-only` 在模型/环境创建前校验任务结构、Region 引用与匹配摘要。它不证明任务可执行、图语义正确或 GUI 成功。
- 普通任务为 `before/after` 目标；条件任务使用 `condition/if_true/if_false`，执行时看图选择分支。关系仅取实际投递、无异常且目标在动作 `interactive_regions` 中的跨区块候选，不把历史路线当必执行脚本。
- 当前活动界面上已有后续目标控件时允许直接使用；业务前置、条件观察与确认不能跳过。模型每轮最多一个语义动作，下一观察回填真实结果，最后核对业务目标截图。click/input_text/long_press/scroll均要求当前点位，输入已聚焦也不能省略；back/wait可无点位。已知target使用控件name，引用字段使用ref；正常解析失败不补造点位或执行动作。

## 视觉核对与记录

逐步图自动构造 `CollectionVisualGuard`。采集启动重新核对图摘要，将消费身份图复制到本次 `graph_images/`，控件仅重定向图片路径，`bbox/click_bbox` 保留区别。已加载记录保留在内存，后续定位使用图片副本。

本次 `matcher/` 固定复制既有 `identity_templates.py/image_match.py/visual_choices.py` 并记录 SHA256；不修改遍历实现。匹配当前身份外观后投影当前点击框，再比较 Luna 点位。明确错位不投递；缺失、歧义或身份不一致进入同一模型传输的当前图确认，不能把“匹配失败”直接判成坐标错误。定位一致不等于动作成功。

旧 ledger 没有逐步双框观察，继续既有视觉执行，不构造该 guard。额外定位调用计入 `model_calls`。`max-turns` 只限制决策回合，不是实际 HTTP 或 GUI primitive 硬额度。普通 CLI 尚未提供这两类独立总额约束；`model_calls` 也不包含实际 HTTP 重试，失败调用可能未计入。有限实机试验需在调用方传输/环境账目中另行记录并强制上限，本次 pilot 如此执行；不向 Luna 提示剩余额度。

每次采集独立保存到 `output-root/runs/<日期-时间-随机ID>/`：配置、matcher、graph_images、grounding、模型记录和原 Writer 的 `<platform>/<date>/<app>/episodes/...`。Writer 的 manifest 也位于本次目录，不覆盖同日旧运行。轨迹记录实际动作、前后帧、定位拒绝、原回执、目标及最终核对；模型/前景失败保留 partial，不将未执行提议写成已执行步骤。

## 验证边界

当前为单应用研究路径，不包含跨应用恢复、任意新任务的可执行证明或完整图认证。真实 Luna 与现场证据及已知失败见 [采集证据](region_function_collection_research.md)；代码及离线接线测试不能代替这些验收。

## 2026-10-05 参数复核边界

生成目录当前只纳入已有非空 functions 的逐步 Region。已记录控件或任务参数、但尚未整理 functions 的区块不会进入生成请求；本次家庭时区 r0010 因此漏出，Cairo 指令生成被正常校验拒绝。不是 Luna 未读懂已提供的时区功能，现有入口也尚无自动筛选参数后重生成任务的流程。

完整冻结图的正常采集入口保存帧小试中，三个请求均保留含 Nairobi 的原任务记忆：模型正确观察 Cairo 可见、Nairobi 当前不可见；固定 Nairobi 且禁止滚动/替代的业务任务保持 partial、无动作。仅证明本例视觉复核与不虚报完成，不证明全列表没有 Nairobi、自动换参或真实设置成功。采集图只读、原回复不编辑；详细证据见同目录 region_function_collection_research.md。
