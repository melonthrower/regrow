# 当前 Region 图指导采集

## 指令与采集字段为什么这样组织（2026-11-04）

此节解释现有接口，不改生成/采集Prompt或字段合同。[遍历对象字段](stepwise/object_fields.md)归原对象说明；这里仅说明下游任务和执行字段。遍历task是待解决的探索问题，生成的instruction是用户业务目标，不能把遍历待办原样当用户指令。

|字段/材料|设计目的|生产与消费|
|---|---|---|
|source_ledger；source_ledger_digest|把指令绑定到实际消费的冻结图及依赖，防止指令与后来另一图混用|生成CLI写来源；采集CLI校验版本。摘要一致仅证明输入版本一致，不证明图语义或业务成功|
|instruction|以有意义的用户目标组织能力，而非随机拼接已出现按钮|region_instruction生成，后续Collector围绕目标执行|
|region_ref；goal；source_refs|为每个目标指出承载区块、预期业务结果和支撑材料，避免无来源能力|生成使用给定目录；validator核对引用；有效引用不是可执行性证明|
|before；condition；if_true/if_false；after|表达条件前目标、需要现场判断的问题、互斥分支及共同后续|Collector按实时观察选分支；不是截图before/after文件，也不是固定点击轨迹|
|setup.assets[].name/kind/content|把必要素材准备与正式任务分开，避免应用缺少对象时功能禁用|当前实现只支持image/text；image为标准1080×1440 PNG加文字标签，text为UTF-8文本，不是任意文档/图层生成|
|setup.open_file；setup.initial_state|指定准备后打开哪个素材、正式业务开始前应看到什么|准备模块生成/投放/打开并用collection_seed_check观察；文件存在不等于应用已准备好，也不提前执行目标修改|
|visible_region_refs；region_visible；condition_value|让执行依赖当前场景，而非复现所有历史State|执行模型看当前图判断；图提供关系和记忆，不能把历史可见当当前可操作|
|action.kind/target/owner_ref/point_1000/text等|把目标推进转成当前表面的一个实际操作|按采集schema输出；point_1000是整屏归一化点位，与遍历常用像素坐标区分，投递前转换/核对|
|previous_action_outcome；previous_action_observation；previous_action_matches_intent|把上一步实际结果回填，防止只有提议动作却声称已执行|下一观察/真实回执与模型说明配合保存；不补造未发生步骤|
|complete；region_collection_final|区分单步看起来完成和最终业务目标的观察核对|终验使用目标前后证据；不是schema通过、成功提交或入口打开就算任务完成|
|graph_images、matcher、grounding与轨迹记录|保留后续执行用到的身份材料、点位核对及真实操作过程|复制只读匹配实现及身份图用于本次采集；不回写遍历图，也不修改遍历代码来修采集|

生成目录由collection_graph.generation_material选择用途、参数、条件和支撑引用；采集记忆region_material目前仍较完整，包含任务材料。二者职责不同，不能因为方便共用整块JSON就宣称上下文已经按目标收窄。

|模型调用|负责的问题|当前实现|
|---|---|---|
|region_instruction|根据图材料提出业务指令、目标引用和必要初态|function_collection_research.design_region_instruction|
|collection_seed_check|正式任务前初态是否满足|collection_seed.prepare_collection_seed；有初态要求时调用|
|region_collection|当前一步如何推进目标/条件及解释上一动作|RegionGuidedCollector.execute|
|collection_grounding|点位/目标证据不足时当前图确认|CollectionVisualGuard.check；不是每步固定额外调用|
|region_collection_final|完整业务结果是否满足|RegionGuidedCollector.execute的最终核对|

当前素材准备主要支持桌面，Android及复杂业务样本不能从schema字段存在推断已支持。图的访问关系是建议：当前已有可操作后续目标时允许直接使用，但不跳过业务前置或条件观察。max_turns只限制决策回合，当前普通CLI的model_calls也不完整包含HTTP重试；不能将其宣传为已统一执行的HTTP/GUI硬额度。已有局部验证见下文，不能外推成完整新图业务采集通过。源码锚点统一见[流程地图](stepwise/CODE_MAP.md)。


维护入口是 `gui_rewalk/run_capability_task_synthesis.py` 与 `gui_rewalk/run_visual_collection.py`，共用 `src/core/scenario/collection_graph.py`。旧 M13 参数、recipe 执行器、scenario delta/SeedPlan 与多模型开关不是这两个入口的当前合同；旧说明保存在 [归档](../archive/2026-10-02-framework-wiring-fix/visual_collection_before_wiring.md)。

## 输入与执行

2026-11-02中间记录候选：正常生成的instruction.json新增每个子目标的source_refs（给定功能/控件或区块引用，不是点击顺序）和setup。setup.assets支持标准1080×1440 PNG测试图及UTF-8 txt/md；content是图片文字标签或完整文本。open_file引用其中一个文件或null；initial_state说明正式任务开始前应满足的可观察状态，不包含目标修改结果。无素材时assets为空。旧任务缺setup保持原路径，未批量改写。

`collection_seed.initialize_collection_environment`是普通采集入口和实机小试共用的准备入口。指定open_file时直接用应用命令打开该文件，绕过旧launch_app的默认示例文件；其余仍沿原启动逻辑。先复用已有Seed图片生成器生成本次文件，经现有设备上传接口投放并读回核对，等待应用/文件加载后，用正常模型传输和真实截图检查初态。窗口标题只帮助等待，不是ready证据；ready=false不进入Collector。非空文件Seed第一版仅支持桌面，Android已有SeedPlan未接到此新记录，不能据此宣称移动端同样可用。

准备记录保存于本次run的environment/setup.json、assets/、report.json、initial.png；report绑定instruction_id和source_ledger_digest。Collector得到本次素材设备路径及初态要求，正式步骤仍使用其原执行流程；Writer复用scenario_setup/data_bindings记录准备报告与实际路径，准备不进入正式steps，初态检查调用计入总model_calls。正式任务结果另行验证。source_refs目前完成生成/保存/合法性检查，采集目录尚未据此收窄。

```sh
python gui_rewalk/run_capability_task_synthesis.py path/to/knowledge_current.json --request '查询指定城市并查看候选，不添加城市' --output new/instruction.json
python gui_rewalk/run_visual_collection.py --instruction new/instruction.json --validate-only
python gui_rewalk/run_visual_collection.py --instruction new/instruction.json --initial-app android_clock --vm-provider android --avd-name YOUR_AVD --android-console-port 5698 --android-grpc-port 8698 --max-turns 14 --output-root collections
```

Android 的 initial-app 使用 config.APP_PACKAGE_MAP 中的应用键（如 android_clock），不是包名。端口和 AVD 必须选择本次拥有的环境；示例不授权附着别人的实例。桌面入口使用 `--vm-provider vmware --path-to-vm <vmx>`。模型由既有本地 API 配置提供，入口没有 `--region-ledger`、`--graph`、`--model-backend` 或 `--headless` 开关。

- 输入可为 ExplorationLedger 或冻结运行的 `knowledge_current.json`。本地读取候选已支持统一 objects.json 及引用的历史记录，旧 regions/*/region.json 继续只读。生成目录选择功能、控件知识、参数条件及未确认内容；Collector 的区块记忆仍包含完整任务材料，尚未按生成目标筛选。不会伪造 State 或已验证功能。
- 生成物记录相对 `source_ledger` 和必需的 `source_ledger_digest`；已存在的指令文件拒绝覆盖。逐步摘要覆盖指针、实际消费的对象/任务记录及历史依赖、身份图（旧布局为 Region JSON），普通 ledger 摘要覆盖文件本身。
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

instruction_seed_bridge_20261102_01：GIMP真实冻结图正常生成裁剪800×1000目标和图片setup；独立桌面设备两轮准备均观察到1080×1440原图且未裁剪。最终轮使用维护中的initialize_collection_environment，来源字段落盘、窗口绑定通过。15项聚焦检查包含CLI向Collector/Writer交接的辅助验证。累计4HTTP请求（1次schema拒绝、1次生成、2次初态检查），0正式GUI动作；文件上传/应用打开属于实际程序准备，不是无环境操作。未执行裁剪、完整采集或Android Seed。首次设备因dnsmasq inotify资源不足失败并清理；第二实例使用镜像已有用户网络与显式端口转发，未修改宿主限制或原设备。


## 2026-11-02 新图读取与生成材料的验证边界

先前失败保存在 artifacts/runs/all_apps_latest_20261102_01/collection-read-check：旧读取器报无Regions，且functions为空的已知控件会被目录过滤。后续 collection_knowledge_bridge_20261102_01 候选复用维护中的对象读取器，正常读取完整冻结 GIMP 图；不能使用缺少 record_history 的早期不完整副本。摘要包含实际消费的对象/任务/历史索引、历史事件及身份图片。52个历史外观可读取，缺失click_bbox仍为未知，不以身份框代替点击区域。

generation_material_20261102_01进一步分开生成目录与采集记忆，11项聚焦检查及1次正常Luna生成通过，0GUI。当前 Collector 的整块记忆和全图视觉目录未收窄，新图实机采集未验收。读取器仍导入活动src/regrow中的只读实现；仅冻结数据不等于固定所有源码依赖。详见[生成与采集证据](region_function_collection_research.md)。
