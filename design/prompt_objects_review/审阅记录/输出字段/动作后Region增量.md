# 动作后Region增量字段底稿

这是静态Schema的字段展开，正常调用可能按模式、任务和已有对象进一步收窄；不是最终请求字段表。

| 字段路径 | 原合同 |
|---|---|
| `$.foreground` | 必填；object |
| `$.foreground.description` | 必填；string |
| `$.foreground.evidence` | 必填；string |
| `$.foreground.uncertainty` | 必填；string |
| `$.regions` | 必填；array |
| `$.regions[].name` | 必填；string |
| `$.regions[].parent_index` | 必填；['integer', 'null'] |
| `$.regions[].description` | 必填；string |
| `$.regions[].bbox` | 可选；按分支 |
| `$.regions[].bbox/anyOf1.left` | 必填；integer |
| `$.regions[].bbox/anyOf1.top` | 必填；integer |
| `$.regions[].bbox/anyOf1.right` | 必填；integer |
| `$.regions[].bbox/anyOf1.bottom` | 必填；integer |
| `$.regions[].source_ref` | 必填；string；取值 ["", "r0001", "r0002"] |
| `$.controls` | 必填；array |
| `$.controls[].region_index` | 必填；integer |
| `$.controls[].bbox` | 可选；按分支 |
| `$.controls[].bbox/anyOf1.left` | 必填；integer |
| `$.controls[].bbox/anyOf1.top` | 必填；integer |
| `$.controls[].bbox/anyOf1.right` | 必填；integer |
| `$.controls[].bbox/anyOf1.bottom` | 必填；integer |
| `$.controls[].source_ref` | 必填；string；取值 ["", "c0001", "c0002", "c0003", "c0004", "c0005", "c0006", "c0007"] |
| `$.controls[].description` | 可选；string |
| `$.uncertainties` | 必填；array |
| `$.action_result` | 必填；object |
| `$.action_result.status` | 必填；string；取值 ["observed_effect", "no_effect", "uncertain"] |
| `$.action_result.evidence` | 必填；string |
| `$.previous_regions` | 必填；array |
| `$.previous_regions[].region_ref` | 必填；string；取值 ["r0001", "r0002"] |
| `$.previous_regions[].state` | 必填；string；取值 ["retained_interactive", "changed_interactive", "visible_background_blocked", "not_visible", "uncertain"] |
| `$.previous_regions[].evidence` | 必填；string |
