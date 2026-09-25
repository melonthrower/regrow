# Luna Region 遍历记录

本次入口：`luna_runs/clock_region_20260919_01/`。与人工比较所在的 `records/` 分开。首轮已完成1次Luna观察，2个Region/7个控件均为模型候选，0动作边。原答与裁剪已落盘，人工意见在records/003_clock_first_luna。程序元数据不冒充模型输出。

|目录/文件|保存内容|
|---|---|
|run_manifest.json|程序记录的环境、运行状态、模型配置引用与计数；不保存凭据或私有端点|
|screenshots/frame_00001.png|每次实际观察的完整原图，命名沿用正式遍历约定；坐标以原图为准|
|calls/0001/|实际system/user/schema、prompt片段快照和哈希、所附截图引用、原始API响应、解析回复、用量；原答不改写|
|observations/o0001.json|这次观察对应的call和原图、Luna报告的可见Region/控件候选及证据；不是Page/State身份|
|regions/r0001/|Region记录及各次出现的观察引用；有可靠框时保存按观察编号命名的真实区块裁剪|
|controls/c0001/|控件记录及逐观察的control.png；能独立定位图标时另存icon.png，文字控件无需伪造图标|
|action_attempts/a0001/|before.png、after.png、真实投递参数及回执；实际执行时才创建。anchor.png按既有点击锚点规则产生，与控件图/图标图区别保存|
|events.jsonl|按序追加模型提案、程序物化、实际动作、身份修正与结果证据的引用|
|graph_snapshots/0001.json|每轮物化后的Region图快照，引用对应原答；不覆盖上一轮|

## 图中记录什么

Region、控件及其可见出现记录；包含关系和同屏关系；从某次观察中某个Region的控件发起的真实动作，以及后续Region出现、消失、更新的结果。一次动作可影响多个Region，不硬压成一条Region到Region边。不创建独立Page/State身份。具体物化字段随逐步试验确定，当前不伪造正式框架兼容schema。

程序分配ID；模型提出功能、区块、身份及效果判断。所有物化条目必须能追溯到call、原答位置、观察与原图。候选、身份待确认、已执行、结果待核对、已核对分开表达，不能把模型叙述当实际动作。没有新调用就不生成模型观察或图快照。

## 图像与来源

每个裁剪配元数据：原图引用/哈希/尺寸、原图像素框[left,top,right,bottom)、边界框来源call/字段、产生方式、是否核对。框缺失、越界或不明确就记录缺口，不编造裁剪；原图始终保留。相同控件在新观察中的外观按观察编号另存，不覆盖旧图。图标相同不自动合并身份。

图中ID可由程序生成，但语义必须来自Luna原答。人工建议、纠正、参考划分仍放在records/；若以后提供给Luna，实际请求明确标明“人工反馈”，原答与修正答分开保存。不偷偷把人工结论补成Luna结果。

## 与现有遍历的对齐范围

沿用 screenshots/、action_attempts/及before/after/anchor证据习惯，并保留完整调用及事件。Region/控件按观察保存图像是本试验补充需求，首轮运行脚本已按模型返回的框自动落盘，脚本保留在本次运行根目录；仅做几何检查，不代表图像语义已验收。当前不调用正式exploration_ledger的Page/State写入器，也不输出modular_completion或冒称兼容旧图加载器。

本目录为长期研究证据，不属于临时测试目录；不提交Git、不清理旧运行、不覆盖旧快照。每轮交付时将原答、图快照、相关图片、人工比较与验证记录一起脱敏打包，保留相对链接。

## Region工作记录

历史region_records/<轮次>/<region_id>.json 为程序从模型候选和动作证据物化的工作视图：含区块本身、控件、出现记录、背景状态提案、transitions和reached_by。transitions归动作控件所属Region；reached_by仅是反向索引，不能据此执行返回。每份工作记录保留source_graph及哈希，旧轮次和原答不覆盖。此视图不冒充Luna的直接原答。

当前登记布局及读取入口以[统一设计第2节](PIPELINE_DESIGN.md)为准。新发现与更新共用Region JSON，名称直达、观察追加、动作效果统一来源；当前历史读取knowledge_current.json，不再读取旧region_records。
