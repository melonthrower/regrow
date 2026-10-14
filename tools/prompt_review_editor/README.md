# Prompt 调试工作台

这是本项目长期复用的人工调试工具。提示正文、真实请求的上下文/历史、对应原图、修改意见和工作笔记在同一工作区；候选改动不自动进入运行框架。

在活动源码目录启动：

```bash
python3 tools/prompt_review_editor.py <审阅数据目录>
```

默认地址为 `http://127.0.0.1:45663/editor`。本工作区现有数据目录是相对 GUI-ReWalk 根的 `artifacts/prompt_review/20261012_01/`，其中 `serve.py` 是指向本工具的本地启动入口。源码位置按项目 `DEVELOPMENT.md` 定位；关闭浏览器不清空数据，机器重启后用同一目录启动。

| 内容 | 数据目录内的位置 |
|---|---|
| 候选正文与术语 | `dist/modified/`、`dist/drafts/` |
| 用户修改、段落想法与选文说明 | `user_edits/state.json`、`user_edits/history/` |
| 跨材料工作记录与历史版本 | `user_edits/worklog.md`、`user_edits/worklog_history/` |
| 真实请求原件、原始系统提示及附图 | `context_sources/`、`context_cases.json` |
| 固定审查快照 | `user_edits/submissions/` |

这些是长期工作资料，不是临时测试输出。不要为了重新启动、生成页面或开始下一轮审阅而删除/覆盖它们。工作记录以项目文件为主，浏览器保存独立恢复副本；冲突时让用户选择，不静默覆盖。

载入新历史材料时，使用 `prompt_review_editor.import_context(review_root, run_dir, call_number, title)` 从真实 `calls/<编号>/` 导入。程序核对 `user.prompt`、`system.prompt` 与 `request.json` 一致，按请求的截图列表复制原图并记录散列；不用手填例子冒充真实历史。上下文候选另存，不能当作正常框架验收请求。

选择历史后，页面显示“本次审查附带历史”（可取消额外附带，已修改历史仍随修改提交）；即使没有修改该上下文，也可将它与原图随快照提交。关联提示链接保留这份历史。准备快照后，把生成的请求发回对话：读者先独立看正文、上下文和图，再看想法及工作记录。按钮不会自动启动代理或调用 Luna。
