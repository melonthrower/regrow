# 设计时变更图

固定基线 `c533359112b422e05c8ec96ce586ff8cfe8820d3`；下列为设计时旧行为→拟议修改，实际实施与验收见DESIGN，提交后的实施锚点另见IMPLEMENTED_CHANGE_MAP。新文件 `experiments/clock_manual_20260919/page_history.py`：新增，无既有行号；统一只读动作历史。

| 文件 / 函数 | 基线行号 | 旧行为 → 拟议修改 |
| --- | --- | --- |
| `experiments/clock_manual_20260919/page_context.py` / `build` | [L109–L195](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/page_context.py#L109-L195) | 仅结构/来路并重复最近结果 → 并入分组历史、旧图号限定与候选语义引用 |
| `experiments/clock_manual_20260919/page_context.py` / `attach` | [L312–L318](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/page_context.py#L312-L318) | 仅结构/来路并重复最近结果 → 并入分组历史、旧图号限定与候选语义引用 |
| `experiments/clock_manual_20260919/page_context.py` / `refresh` | [L287–L309](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/page_context.py#L287-L309) | 仅结构/来路并重复最近结果 → 并入分组历史、旧图号限定与候选语义引用 |
| `experiments/clock_manual_20260919/page_context.py` / `_display` | [L198–L256](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/page_context.py#L198-L256) | 仅结构/来路并重复最近结果 → 并入分组历史、旧图号限定与候选语义引用 |
| `experiments/clock_manual_20260919/history_context.py` / `action_context` | [L282–L313](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/history_context.py#L282-L313) | 多处重复尝试 → 动作摘要保留目标/事实，参数事件归图；特殊复核保留 |
| `experiments/clock_manual_20260919/history_context.py` / `task_goal` | [L171–L251](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/history_context.py#L171-L251) | 多处重复尝试 → 动作摘要保留目标/事实，参数事件归图；特殊复核保留 |
| `experiments/clock_manual_20260919/target_observation.py` / `describe` | [L8–L20](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/target_observation.py#L8-L20) | 交接重复动作、状态称本轮 → 仅观察缺口，登记状态需按截图核对 |
| `experiments/clock_manual_20260919/target_observation.py` / `handoff` | [L23–L53](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/target_observation.py#L23-L53) | 交接重复动作、状态称本轮 → 仅观察缺口，登记状态需按截图核对 |
| `experiments/clock_manual_20260919/region_tasks.py` / `plan_request` | [L46–L100](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/region_tasks.py#L46-L100) | 控件结果与任务列表重复 → 单独历史后归图，保留任务/前置条件 |
| `experiments/clock_manual_20260919/region_tasks.py` / `attach` | [L200–L303](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/region_tasks.py#L200-L303) | 控件结果与任务列表重复 → 单独历史后归图，保留任务/前置条件 |
| `experiments/clock_manual_20260919/region_tasks.py` / `render_current` | [L306–L307](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/region_tasks.py#L306-L307) | 控件结果与任务列表重复 → 单独历史后归图，保留任务/前置条件 |
| `experiments/clock_manual_20260919/stepwise_flow.py` / `_assemble_action_context` | [L412–L492](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/stepwise_flow.py#L412-L492) | 导航结果多次展开 → 共同地图顺序，图片和绑定协议不变 |
| `experiments/clock_manual_20260919/stepwise_flow.py` / `assemble_current_context` | [L508–L556](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/stepwise_flow.py#L508-L556) | 导航结果多次展开 → 共同地图顺序，图片和绑定协议不变 |
| `experiments/clock_manual_20260919/run_task_step.py` / `build_attempt_update` | [L53–L114](https://github.com/melonthrower/regrow/blob/c533359112b422e05c8ec96ce586ff8cfe8820d3/experiments/clock_manual_20260919/run_task_step.py#L53-L114) | 来源对比/目标重复结果 → 引用共同历史，保留身份和参数原证据 |

验收例：前景搜索、父目标准备、详情返回、添加结果、返回后内容保持、参数旧事实与本步观察；身份未知、缺记录与不同历史条件另有聚焦检查。

实施中由真实结果发现的补充：更新/区块变化与字段.prompt 的控件清点及返回语义；region_graph.html 的观察来源和未执行记录标题。二者不假装已在原方案中，最终范围及真实锚点见 IMPLEMENTED_CHANGE_MAP。
