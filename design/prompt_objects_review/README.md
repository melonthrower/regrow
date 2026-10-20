# 对象Prompt审查入口

四份正文现已统一格式并接入正常运行，唯一维护位置：

- [控件](../../src/regrow/prompts/对象/控件.prompt)
- [区块](../../src/regrow/prompts/对象/区块.prompt)
- [任务](../../src/regrow/prompts/对象/任务.prompt)
- [动作](../../src/regrow/prompts/对象/动作.prompt)

每块使用稳定ID和requires依赖；调用按实际字段选择，同一块内容不因调用改写。标记与依赖不发送给Luna。原附件、讨论稿和来源索引仍在审阅记录中，仅作历史依据。实际验证状态见design/changelog/2026-10.md；接入不等于全框架验收。

[调用审查目录](调用审查目录.md)保留此前清单供对照，旧源片段不是当前对象字段真值；当前组成以src/regrow/prompts/流程/调用组成.json为准。
