# 实现变更地图 v1

基线 `6fa0814c1cf7455e1128f7e4f09b7ff8cca37ecb`；实现源码提交：`87d6e3302fe113fdc0d7d5fe92781ebd399d5e92`。以下均为已实现；提案/原生验收与未验范围以 DESIGN 和月日志为准。

| 文件 / 函数 | 基线行 | 实现行 | 当前改动 |
| --- | --- | --- | --- |
| `experiments/clock_manual_20260919/prompt_delivery.py` / `effective_role` | 新文件 | 22–26 | 纠错继承原步骤，别名统一，未知阶段保留全量。 |
| `experiments/clock_manual_20260919/prompt_delivery.py` / `desktop_parts` | 新文件 | 29–42 | 新文件，无基线行号；集中规则分段与同源完整手册引用。 |
| `experiments/clock_manual_20260919/prompt_delivery.py` / `original_rules` | 新文件 | 45–62 | 新文件，无基线行号；集中规则分段与同源完整手册引用。 |
| `experiments/clock_manual_20260919/desktop_transport.py` / `prepare_request` | 50–58 | 50–58 | 由全量平台手册改为调用统一规则投影。 |
| `experiments/clock_manual_20260919/history_disclosure.py` / `project` | 40–69 | 40–72 | 纠错保留原专属规则，共用段落引用当前system。 |
| `experiments/clock_manual_20260919/history_context.py` / `task_goal` | 171–251 | 171–253 | 参数解码仅在实际参数事实存在时提供。 |
| `experiments/clock_manual_20260919/page_context.py` / `attach` | 393–424 | 393–427 | 历史图号/参数基准说明随实际内容提供，不改事件正文。 |
| `experiments/clock_manual_20260919/遍历prompt/平台/桌面悬停观察.prompt` | 1–18 | 5–26 | 按职责分段，保留必要的遮挡、裁图、完整性和菜单维持规则。 |
| `experiments/clock_manual_20260919/遍历prompt/任务/任务登记与补全.prompt` | 26 | 26 | 就地澄清多控件准备，不复制任务；真实错绑仍需证据。 |

验收：正常框架六类完整请求，schema/真实截图保留；精确去重保留权限及不同版本规则；无参数/有参数说明；v3规划不再重复旧准备。实际模型8次，失败及普通动作重试限制原样保留；不以Runner complete替代语义验收。

新测试 `tests/test_prompt_task_scope.py`：步骤与纠错规则路由、精确完整段落引用、不丢独有内容、参数说明条件和二次构造。其余为直接相邻测试。无新CLI、GUI、schema或后台身份变更。
