# 代码变更图

本图对应包含本文件的提交；基线efbf87d8c46ff3ed7ef9080306b2ba4e78e905c8。正式源码在src/，行号对本次导出逐行核定。GitHub提交URL将在本地交付版本说明固定。

|文件/函数|本提交行号|原行为→已实施行为|验证|
|---|---|---|---|
|src/regrow/prompts/history_disclosure.py / replace_presentation|15–22|新增可信展示改写入口；原关联有效才更新已有展示校验，内部源不变|2项原有聚焦检查、真实原件回放；本次原生保存帧及GIMP实机|
|src/regrow/recognition/named_references.py / render|262–269|user_prompt直接赋值→通过上述入口；其他展示字段保持原转换|本次GIMP File动作实际投递、观察及登记|
|tests/test_named_presentation_restore.py|新导出测试文件|覆盖名称展示后内部ID/图保留及人工编辑失配保护|既有2 passed；本次未重复运行|

未实施：Characters补充请求合同修复、生成/采集新图适配、跨应用业务任务支持。表中运行结论只限上述真实案例，非全框架认证。
