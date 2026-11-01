# 具体变更位置

这些文件在本评审分支是新建的只读源码快照；下面行号属于包内实际文件，对应源码路径仅用于定位。不是对默认分支同名文件的未标注覆盖。

导出基线：`f18f2f404c342da5ed4ed17e269d03596cf1a90e`。当前文件与测试冻结源逐字一致；changes.patch仅本轮相对开始前的差异。测试基线已有的其他文本未借本次发布宣告验收。上传完成后，交付链接固定到本次 GitHub 提交。

| 原实现位置 | 快照锚点/行号 | 本轮变化 |
| --- | --- | --- |
| `src/regrow/prompts/对象/任务.prompt` | [task.definition](tested-source/regrow/prompts/对象/任务.prompt#L11)，11–18 | 用户四条原则，逐字正文 |
| `src/regrow/prompts/对象/任务.prompt` | [task.completion_condition](tested-source/regrow/prompts/对象/任务.prompt#L20)，20–24 | 围绕原问题与足够证据，不自动调查全部功能 |
| `src/regrow/prompts/对象/任务.prompt` | [task.operations](tested-source/regrow/prompts/对象/任务.prompt#L37)，37–46 | 必要独立未知按需提出，已有用途可直接登记 |
| `src/regrow/prompts/对象/任务.prompt` | [task.update](tested-source/regrow/prompts/对象/任务.prompt#L48)，48–55 | 按原问题结算，历史追加疑问不自动扩充条件 |
| `src/regrow/prompts/调用/提出探索任务.prompt` | [本步任务](tested-source/regrow/prompts/调用/提出探索任务.prompt#L1)，1–10 | 删除将内部未知一律移交的重复句；其余是测试基线原有内容 |

正常框架入口（本批未修改）：任务提出由 action_proposer.request_from_run 构造，结算由 task_result_review.request 构造，发送前由 model_transport.prepare_request 组装；step_repair.Runner.perform 使用实际回复校验和登记。人工任务修订复用 snapshots.publish，模型不代改原图。

当前未接受点和验收案例见README。没有给尚未实施的修复捏造行号。
