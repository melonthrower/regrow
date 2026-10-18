# 识别

- [locator.py](../../../src/regrow/recognition/locator.py)：构造当前图的发现/再识别请求，核对已有身份，允许补新控件与无控件展示区。
- [matching.py](../../../src/regrow/recognition/matching.py)：外观定位、重复外观的相对位置核对及候选呈现，复用原算法。
- region_identity、control_identity_review：处理复用/新建身份与有依据的身份复核。

识别阶段的运行协调、补观察和原任务保留已迁到 [traversal/observation.py](../../../src/regrow/traversal/observation.py)。接受的对象观察由 records 登记，识别不另维护一套对象表。

身份图仅供认出对象；匹配不是操作许可或成功证据。单张当前图提供动作坐标，两图比较不输出几何。旧场景漏报的调度/语义证据问题仍需单独处理，不能因新目录而称已解决。

2026-10-16：local_partition的同帧材料是已构造的控件候选列表，prompt/errors直接读取该列表；不再错走持久对象的owned_controls接口。旧区块归属与重复判定语义未改。

控件发现输出的possible_purpose是初步用途，may_open_content和needs_exploration是可不确定的判断；不是任务完成证据。新对象必填三项，已登记对象只提交变化。schema和共享身份说明用于发现及动作后对象登记，实际探索结果仍在任务答案knowledge登记。

2026-10-18控件输出引用：Luna在controls中用本轮index复用；新控件不填index，身份不确定写uncertainties，控件输出不再有identity/ref。区块ref/identity、控件region_index不变。control_indexes统一生成调用内映射，在发送前生成wire schema，原答先校验再解析为内部稳定身份；索引不写入控件事实。普通纠错、身份比较及记录修订刷新沿用位置，明确合并后解析到同一稳定对象，未知index不当新增。实际保存原答不改写。

2026-10-18：同一多功能控件按对象延续复用身份，不按用途拆分；同时独立存在的按钮/输入框分别登记。object_registration只补外观资料，单图bbox用于识别裁图，不用于未来操作。无法定位保留缺口；补资料纠错不允许新观察或改旧记录。
