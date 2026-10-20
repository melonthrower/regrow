# 早期导出记录 · 2026-10-20

本文以下内容记录四对象接入前的导出；最新状态以[四对象交接说明](OBJECT_PROMPT_HANDOFF_20261020.md)为准。

本分支同步本地活动源码与Prompt审查材料，基于远端bb27a04建立，保留远端原分支和历史。它是本地当前状态的研究快照，不是合并并验收全部远端/本地候选的发布版。

## 本地当前内容

- 活动实现：src/regrow；识别、遍历、记录及运行提示按本地当前工作树导出。
- 控件七字段结构及条件化知识/图片/跳转记录沿当前实现；验证边界以已有模块说明及本次检查为准。
- Prompt审查入口：design/prompt_objects_review/调用审查目录.md。四对象正文和15用途审阅材料尚未接入运行组合。
- 已确认“应用主要功能”的入口措辞目前在候选审阅正文；运行Prompt仍是当前源码中的版本。不要把审阅稿当作已经部署的提示。

## 与远端原分支的关系

原codex/traversal-framework-20261018仍保留bb27a04的菜单后续离线候选。当前本地src不是该候选的语义合并结果；本快照按本地源完整同步，可能替换同路径的远端不同实现。差异和原提交保留，可分别审查，不声称远端修复已经在本地接入。具体路径见本次源码对照表。

## 验证范围

隔离导出聚焦测试69 passed（控件结构、条件知识、引用、对象补登记、参数文本、目标交接六组）；CLI单步帮助入口通过。文件/凭据/依赖边界另经静态审查。没有新Luna/GUI、没有全框架门禁。原本未通过的身份、任务收敛和长遍历问题不因同步而变成已通过。历史测试文件保留，不意味着全部适配当前快照。

## 数据与安全

不上传运行目录、截图、真实请求/回复、密钥、私人端点、模型账户配置、依赖链接或工作台个人笔记。工具需要在本地提供数据与配置。导出副本仅清除行尾空白；Python AST前后一致，运行源码不改。

## 远端菜单候选与本地快照的源差异

- `src/regrow/prompts/任务/区块探索任务.prompt`：本地实现与远端不同；当前分支采用本地版本，未声称语义合并。
- `src/regrow/records/control_history_context.py`：本地实现与远端不同；当前分支采用本地版本，未声称语义合并。
- `src/regrow/traversal/task_deferral.py`：本地实现与远端不同；当前分支采用本地版本，未声称语义合并。
- `src/regrow/traversal/task_routing.py`：本地实现与远端不同；当前分支采用本地版本，未声称语义合并。

## 重现导出检查

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q tests/test_control_current_structure.py tests/test_contextual_controls.py tests/test_control_indexes.py tests/test_update_object_registration.py tests/test_parameter_prose.py tests/test_confirmed_destination_routing.py --basetemp=artifacts/tmp_tests/export_check_20261020/pytest --tb=short
python src step --help
```

导出文件与本地原始散列见[导出清单](TRAVERSAL_EXPORT_20261020.json)。代码来自含未提交内容的本地工作树；local_head仅定位其Git基底，不将该提交号冒充全部运行源码版本。
