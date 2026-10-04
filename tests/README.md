# 测试入口

当前逐步测试按职责查[STEPWISE_INDEX.md](STEPWISE_INDEX.md)；其他实现从[全项目模块索引](../design/modules/README.md)定位。维护测试保留原文件名和导入路径。

从checkout根运行所需测试。例如仅选择任务诊断：

```sh
python -m pytest tests/test_task_context_diagnostics.py -q -p no:cacheprovider --basetemp=artifacts/tmp_tests/<唯一验证名>/pytest
```

将 `<唯一验证名>` 替换为本轮名称，确认目录不属于旧证据。部分历史测试为脚本入口，先看文件说明。聚焦测试按风险选择；索引不表示全部通过，也不自动要求全框架门禁。

真实Luna/GUI记录放在独立run，不当pytest临时目录。文档整理只做Tier 1检查；行为验收与完整门禁条件以AGENTS和全局合同为准。
