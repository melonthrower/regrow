# 旧图修复

`repair_graph.py` 是暂停运行后的人工修复入口。目前仅支持：任务引用的功能丢失，但祖先快照中仍有已登记功能，且全部支持控件仍在原区块。它不是自动猜测/清空坏图的工具。

```bash
python tools/repair_graph.py inspect /绝对路径/run /新目录/plan.json
python tools/repair_graph.py apply /新目录/reviewed-plan.json
```

先审阅 plan 的 missing、restore、unresolved。核对历史功能是否误删、支持对象是否仍有效，将选定条目的一句话修复理由写入 reason，并另存 reviewed-plan.json。没有理由不能发布；不要改历史 function 内容。若还有未解决引用，正常全图引用校验会阻止发布，不能靠移除计划条目绕过。

apply 复用 function_updates 的知识/支持/参数校验和 snapshots.publish。恢复历史语义与原 source_call，支持证据及位置由当前对象记录重建；计划保存在新快照 repair.json，原快照、任务状态、动作回执不覆盖。运行未停、图已变化、候选不在祖先链、支持迁移或功能已存在时拒绝。区块级支持、没有历史候选、身份或完成结论错误需另行语义核对，本工具不自动修复。

修复后用 inspect 确认引用，再沿正常框架续跑验证；零悬空引用不代表全图语义正确，也不等于挂起动作已补登记。不要重放已执行动作。
