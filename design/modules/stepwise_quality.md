# 逐步遍历质量检查 v1

入口：`tools/check_stepwise_quality.py`；实现：`tools/stepwise_quality/`。
读取 `region_image_knowledge` 快照，不替换旧 Page/Variant `GraphQualityAgent`。
这是框架可调用的独立、只读检查入口；没有自动挂到遍历每次登记或后台常驻运行。
本轮不检查采集轨迹，不改变遍历源码、提示、图或历史证据。

## 质量合同

判定为 reasonable / refine / problem / insufficient，未调用模型另记未检查。
区块和任务没有唯一划分；新证据导致细分不倒推早期错误。refine必须说明新证据。
引用不存在、框超出原图是结构问题；缺图/缺结果依据是证据不足，不自动推为功能错误。
裁图、原图、点击区域分开显示。结构检查无错误不等于语义检查通过，无总体质量分。
调用级证据仅使用该调用实际请求/回复，以及明确 source.call/source.stage 关联快照的 parent 差异；
没有关联快照显示未知，不凭当前图推断旧登记或把它当被拒绝。

Codex 可自动检查单次登记和图对象，Luna 只检查图对象；Luna 每请求最多一张原图，
不把拼图冒充单图。单图无法证明跨帧身份、跳转因果或未提供裁图质量，提示保留证据不足。
视觉判断未经本轮实测，不承诺准确率；模型原结论不是裁判真值。

## 使用

从仓库根目录，使用已有含 Pillow/jsonschema/requests/PyYAML 的框架 Python：

```sh
python tools/check_stepwise_quality.py build RUN OUTPUT --calls 0806:0827
python tools/check_stepwise_quality.py serve OUTPUT
python tools/check_stepwise_quality.py review OUTPUT luna --budget 10
python tools/check_stepwise_quality.py review OUTPUT codex --budget 2 --item call:0817 --item call:0819
```

`build` 不调用模型/GUI；固定当前快照并复制引用图片，输出必须在源run之外且不存在。
`--calls` 仅选择逐调用检查范围；整图对象全部列出。`--item`选择校准对象，不是算法开关。
Codex用本机已安装`codex exec`、只读sandbox及JSON schema；继承本机模型配置。
Codex额度是进程调用次数，不是HTTP/token上限；本轮只以替身进程验证CLI协议。
Luna复用 `.guiwalk.local.yaml` 的配置读取和框架回复解析，不复制凭据；单请求、无自动重试。
额度完全独立：started为预留/尝试数，http_started为真正进入HTTP投递的记录数。
失败保留原回复/失败类型并占额度，不算通过；配置缺失等本地失败不虚报HTTP。
同一个输出/backend仅运行一次，拒绝重复启动以防重置预算；新批显式创建新输出。
运行中断时可从每请求http_started.json核对实际投递，不自动重试未确定请求。

## 页面与产物

`report.json` 含区块、控件、任务、功能、跳转、逐次调用；`assets/`保存原始图片字节。
`index.html` 可携带离线查看；服务模式支持将人类认可/否定/仍不确定追加到报告。
离线页面导出 `human-feedback.json`，可用 `feedback OUTPUT FILE` 导入。
`reviews/<backend>/` 保留预算、请求、原回复、usage与错误；源run不写入。
人类意见独立于自动结论，不修改图。仅凭结构规则发现的问题与模型检查结果分开。
源码/配置含端点和凭据字段从导出数据中脱敏；用户截图与业务内容仍属研究证据，
不自动推送GitHub。CLI仅在显式review时调用外部模型，serve不能触发付费检查。

## 验证边界

以 `tests/test_stepwise_quality.py` 聚焦测试、真实Clock离线生成和本地HTTP检查验收。
用户明确要求本轮零付费调用：没有实际Luna/Codex模型校准，没有新GUI或全框架门禁。
旧图缺失原图、身份登记不一致等只作为检查结果，不在此任务自动修复。
