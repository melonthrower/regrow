# 本轮导出检查

仅离线源码/入口/模块检查，不代表Luna语义或GUI成功。3入口 --help、25项相关测试通过；Python AST数见 SOURCE_VERSION.json。以下为便携复跑命令，在完整仓库根目录、依赖已安装的Python环境执行，PYTHONPATH包含仓库根及src。为便携性把测试临时目录改为包内 artifacts/tmp_tests；实际执行参数保存在 ACTUAL_COMMAND.json。

```bash
python src step --help
python gui_rewalk/run_capability_task_synthesis.py --help
python gui_rewalk/run_visual_collection.py --help
python -m pytest -q -p no:cacheprovider tests/test_recovery_task_resume.py tests/test_collection_object_snapshot.py tests/test_collection_seed_bridge.py tests/test_stepwise_collection_graph.py tests/test_collection_visual_guard.py tests/test_run_visual_collection_cli.py --basetemp artifacts/tmp_tests/source_sync_review/pytest
```

实际日志为 `focused-tests.log` 和 `focused-tests-final-export.log`。后者用于确认缩小测试导出范围后，独立导出包依赖仍完整。没有调用Luna/真实GUI，没有运行全框架门禁。
