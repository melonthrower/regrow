# Prompt 完整修改对照（候选，尚未写入源码）

公开阅读副本：diff代码块的空白上下文行以空行排版；精确正文见before/和candidate/，代码块不作为直接应用补丁。原审阅稿保留本地。

本稿仅取消区块父子结构；其他既有草稿原样保留，不表示获确认。通用新增正反例不使用具体应用。schema/组成文件只删除父级字段与对应组合项，格式化差异不属于拟议行为。动态材料同时退出“已登记子区块”和包含树，改为当前区块列表与控件引用；访问来路及访问目录保留。

## src/regrow/prompts/区块识别/功能区块划分.prompt

```diff
--- 当前
+++ 候选
@@ -1,4 +1,6 @@
 Region 是共享局部交互上下文、围绕共同功能组织的组件。结合功能职责、作用对象、容器关系和可见布局提出划分；显隐、替换或滚动边界只有经过相应观察才能确认。
-不要按面积、小标题、单个按钮或固定数量机械拆分。持久导航与可替换内容可以分开；有明确容器关系时保留父子层级，不虚构父容器，也不为每个区块强加父级。
-同一列表中仅数据不同、交互结构相同的成员通常属于同一 Region。不同功能入口不能因为外观都是列表项就合并。展开后若出现独立编辑上下文，可以提出子 Region；普通选中、数值变化不自动产生新 Region。
-一个物理控件只归一个直接 Region，父区不重复登记子区控件。边界暂不明确时给出当前最合理的划分与疑问，后续允许依据真实操作修正。
+不要按面积、小标题、单个按钮或固定数量机械拆分。持久导航与可替换内容可以分开。
+同一列表中仅数据不同、交互结构相同的成员通常属于同一 Region。不同功能入口不能因为外观都是列表项就合并。展开后若出现独立编辑上下文，可以提出独立 Region；普通选中、数值变化不自动产生新 Region。
+按当前区块的功能范围登记控件；已有控件复用原身份，不因在不同区块中出现而重复新建。边界暂不明确时给出当前最合理的划分与疑问，后续允许依据真实操作修正。
+正例：两个区域共同编辑同一个对象，可以属于同一区块；展开后出现独立操作上下文，可以登记为另一区块。
+反例：不能仅因某区域位于另一区域内部就建立区块层级，也不能因两个区块同时可见就推断存在跳转。
```

完整候选见 [文件](candidate/src/regrow/prompts/区块识别/功能区块划分.prompt)；未修改的正文保持当前内容。

## src/regrow/prompts/对象/区块.prompt

```diff
--- 当前
+++ 候选
@@ -28,7 +28,7 @@
 <!-- END_PROMPT_BLOCK id="region.update_registration" -->

 <!-- BEGIN_PROMPT_BLOCK id="region.local_registration" requires="" -->
-本次局部识别中，regions 仅填写本轮定位区块，controls 仅填写它直属的必要控件。
+本次局部识别中，regions 仅填写本轮定位区块，controls 仅填写该区块功能范围内的必要控件。
 正例：本轮定位搜索区时，登记搜索区及其搜索框、提交按钮。
 <!-- END_PROMPT_BLOCK id="region.local_registration" -->

@@ -88,9 +88,6 @@
 正例：新出现的格式选择菜单有独立用途，未对应已有区块时登记为 new。
 <!-- END_PROMPT_BLOCK id="region.registration_identity" -->

-<!-- BEGIN_PROMPT_BLOCK id="region.parent_index" requires="" -->
-parent_index：物理包含它的父区块在本次 regions 数组中的位置，从 0 开始；没有父区块时按本节格式留空。
-<!-- END_PROMPT_BLOCK id="region.parent_index" -->

 <!-- BEGIN_PROMPT_BLOCK id="region.state_description" requires="" -->
 state_description 写这次可见的状态，description 保留稳定职责。
@@ -191,9 +188,6 @@
 current 为 true 表示本次确认该区块处于当前前景；只标记当前实际看见的区块。省略或 false 表示本次没有作前景确认，不新增“已消失”的历史事实。补历史区块知识不需要 current:true。没有可确认的当前区块时，不标记任何区块为 true。
 <!-- END_PROMPT_BLOCK id="region.current" -->

-<!-- BEGIN_PROMPT_BLOCK id="region.parent" requires="" -->
-parent 填物理包含它的父区块名称；没有父区块时省略或填 null。这里不是访问来路。
-<!-- END_PROMPT_BLOCK id="region.parent" -->

 <!-- BEGIN_PROMPT_BLOCK id="region.application_exception" requires="region.exception_values,region.recovery_handoff" -->
 先报告本次观察到的 exception。没有异常时继续填写本步业务字段；有异常时只填写 exception 和 recovery_handoff，交给恢复流程，不登记任务、知识或探索动作。
```

完整候选见 [文件](candidate/src/regrow/prompts/对象/区块.prompt)；未修改的正文保持当前内容。

## src/regrow/prompts/共享/区块身份复用.prompt

```diff
--- 当前
+++ 候选
@@ -1,6 +1,6 @@
 ## 对象身份与归属 → regions / controls
 同一对象的位置、输入值、选中或禁用状态变化不产生新身份。已有区块用ref引用，已有控件用材料中的index引用，只补必要变化。区块身份不确定时不绑定ref，填写name、description、identity="uncertain"，在identity_evidence中点名候选及具体缺口；控件尚不能对应时写入uncertainties。
-对应字段：ref是旧区块编号；index是材料中的旧控件序号；region_index是所属区块在本次regions数组的位置，从0开始；parent_index只用于真实物理包含，不把进入来路当包含父级。
+对应字段：ref是旧区块编号；index是材料中的旧控件序号；region_index是所属区块在本次regions数组的位置，从0开始。
 局部字段例（假设材料中的ref="c0008"属于r0080，不是完整回复）：
 ```json
 {
```

完整候选见 [文件](candidate/src/regrow/prompts/共享/区块身份复用.prompt)；未修改的正文保持当前内容。

## src/regrow/prompts/共享/行为差异分离.prompt

```diff
--- 当前
+++ 候选
@@ -12,7 +12,7 @@
 通常为 null。仅来源区块本身结构或职责确实不同，无法解释为原控件的条件用途时填写：
 - name、description：新来源的名称与职责。
 - context、original_context：区块级区别；evidence：结构与职责依据。
-- region、controls：取自动作前记录的实际来源；ref 为空，parent_index=null，region_index=0。
+- region、controls：取自动作前记录的实际来源；ref 为空，region_index=0。
 - acted_control：动作前记录中实际执行的控件，不能按字段要求猜造。
 - shared_controls：仅引用其他有真实历史行为支持的稳定控件；未知项留空。
 动作后新表面仍走普通 regions/controls，不填进动作前来源。来源被接管时，previous_regions 按原名报告背景。
```

完整候选见 [文件](candidate/src/regrow/prompts/共享/行为差异分离.prompt)；未修改的正文保持当前内容。

## src/regrow/prompts/任务/清点输出约定.prompt

```diff
--- 当前
+++ 候选
@@ -22,6 +22,6 @@
 complete表示本次提供的控件已考虑，必要未知已有对应任务；任务尚待执行、参数问题尚未回答或受本轮范围限制不能调查，不影响本次考虑范围的完整性。
 partial仅用于具体未登记对象或尚未解决的归属/覆盖缺口；uncertain用于无法判断本次提供范围。evidence写具体缺口，不能以参数尚未穷尽、名称变化或没有反复验证为理由延长清点。
 正例：已考虑当前三个控件，输入未知交给已有参数任务后清点可complete。只读范围内无法试验某个参数时，保留该未知及范围限制；它不是未登记对象或归属缺口。
-反例：因没有试完所有查询、没有进入全部子区块，就宣布当前清点仍partial。区块功能总结整理已有证据，不要求先穷举参数或全子树。
+反例：因没有试完所有查询、没有探索其他区块，就宣布当前清点仍partial。区块功能总结整理已有证据，不要求先穷举参数或完成其他区块。

-清点只针对当前范围：历史另一状态出现但本图未出现的对象，不单独构成遗漏；已由子区块登记的对象不在父区块重复登记。正例：全集列表中的Show All在当前搜索结果中未显示，保留其历史与待办，当前无其他缺口时可complete。反例：因此反复在同一搜索结果图中寻找它。当前明确可见却未登记的清除按钮，应在evidence说明具体缺口，交后续识别补齐；本步不登记新对象。
+清点只针对当前范围：历史另一状态出现但本图未出现的对象，不单独构成遗漏；已有对象复用原身份，不为当前清点重复新建。正例：全集列表中的Show All在当前搜索结果中未显示，保留其历史与待办，当前无其他缺口时可complete。反例：因此反复在同一搜索结果图中寻找它。当前明确可见却未登记的清除按钮，应在evidence说明具体缺口，交后续识别补齐；本步不登记新对象。
```

完整候选见 [文件](candidate/src/regrow/prompts/任务/清点输出约定.prompt)；未修改的正文保持当前内容。

## src/regrow/prompts/纠错/组织原则.md

```diff
--- 当前
+++ 候选
@@ -34,7 +34,7 @@

 ## 错误类型与处理入口

-缺字段、错误引用、重复登记、列表分组和本次归属/父子结构冲突，只需改当前回复时均使用原格式重答；各业务模块继续负责检查并提供错误原因。填错值保留在原答中，缺失值才补占位。功能/参数引用的部分诊断仍是文字异常，不妨碍进入同一重答步骤，但不等于都已有统一字段路径。
+缺字段、错误引用、重复登记、列表分组和本次控件归属冲突，只需改当前回复时均使用原格式重答；各业务模块继续负责检查并提供错误原因。填错值保留在原答中，缺失值才补占位。功能/参数引用的部分诊断仍是文字异常，不妨碍进入同一重答步骤，但不等于都已有统一字段路径。

 若冲突涉及历史记录的修订、补观察或身份/操作目标视觉判断，保留原专门处理能力。规则只能识别其覆盖的结构或引用冲突，不能自动发现所有语义归属错误。

```

## src/regrow/prompts/输出格式/首屏观察.schema

```diff
--- 当前
+++ 候选
@@ -35,13 +35,6 @@
         "properties": {
           "name": {
             "type": "string"
-          },
-          "parent_index": {
-            "type": [
-              "integer",
-              "null"
-            ],
-            "description": "本轮regions数组0起始父行号；无父级为null。不是跨图身份ID。"
           },
           "description": {
             "type": "string"
@@ -81,7 +74,6 @@
         },
         "required": [
           "name",
-          "parent_index",
           "description"
         ],
         "additionalProperties": false
```

## src/regrow/prompts/输出格式/动作后更新.schema

```diff
--- 当前
+++ 候选
@@ -21,13 +21,6 @@
           "name": {
             "type": "string"
           },
-          "parent_index": {
-            "type": [
-              "integer",
-              "null"
-            ],
-            "description": "本轮regions数组0起始父行号；无父级为null。不是跨图身份ID。"
-          },
           "description": {
             "type": "string"
           },
@@ -70,7 +63,6 @@
         },
         "required": [
           "name",
-          "parent_index",
           "description",
           "ref"
         ],
```

## src/regrow/prompts/输出格式/动作后Region增量.schema

```diff
--- 当前
+++ 候选
@@ -21,13 +21,6 @@
           "name": {
             "type": "string"
           },
-          "parent_index": {
-            "type": [
-              "integer",
-              "null"
-            ],
-            "description": "本轮regions数组0起始父行号；无父级为null。不是跨图身份ID。"
-          },
           "description": {
             "type": "string"
           },
@@ -74,7 +67,6 @@
         },
         "required": [
           "name",
-          "parent_index",
           "description",
           "source_ref"
         ],
```

## src/regrow/prompts/流程/调用组成.json

```diff
--- 当前
+++ 候选
@@ -165,12 +165,6 @@
                 "block": "region.current",
                 "when_paths": [
                   "regions.current"
-                ]
-              },
-              {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
                 ]
               },
               {
@@ -602,12 +596,6 @@
                 ]
               },
               {
-                "block": "region.parent_index",
-                "when_any_paths": [
-                  "regions.parent_index"
-                ]
-              },
-              {
                 "block": "region.state_description",
                 "when_any_paths": [
                   "regions.state_description"
@@ -653,12 +641,6 @@
                 "block": "region.current",
                 "when_paths": [
                   "regions.current"
-                ]
-              },
-              {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
                 ]
               },
               {
@@ -959,12 +941,6 @@
                 ]
               },
               {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
-                ]
-              },
-              {
                 "block": "control.registration",
                 "when_paths": [
                   "regions.controls"
@@ -1278,12 +1254,6 @@
                 ]
               },
               {
-                "block": "region.parent_index",
-                "when_any_paths": [
-                  "regions.parent_index"
-                ]
-              },
-              {
                 "block": "region.state_description",
                 "when_any_paths": [
                   "regions.state_description"
@@ -1329,12 +1299,6 @@
                 "block": "region.current",
                 "when_paths": [
                   "regions.current"
-                ]
-              },
-              {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
                 ]
               },
               {
@@ -1817,12 +1781,6 @@
                 ]
               },
               {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
-                ]
-              },
-              {
                 "block": "control.registration",
                 "when_paths": [
                   "regions.controls"
@@ -2239,12 +2197,6 @@
                 "block": "region.current",
                 "when_paths": [
                   "regions.current"
-                ]
-              },
-              {
-                "block": "region.parent",
-                "when_paths": [
-                  "regions.parent"
                 ]
               },
               {
```

## src/regrow/prompts/纠错/字段占位.json

```diff
--- 当前
+++ 候选
@@ -95,7 +95,6 @@
   "observed_assignments": "<填写本次观察到的控件归属>",
   "operations": "<填写待探索任务列表>",
   "out_of_scope_reason": "<填写超出探索范围的原因>",
-  "parent_index": "<填写父区块在本次列表中的位置>",
   "path": "<填写给定对象的位置标识>",
   "previous_regions": [
     {
```

## 动态材料与纠错说明对照（同样属于本次待确认内容）

|当前位置|当前文字/输出|候选|
|---|---|---|
|traversal/action_context.py render_exploration_tree|已登记子区块（独立探索，详情折叠）：…；另有 N 个子区块折叠。|删除这两条层级说明；其他区块仍通过已有访问目录和任务材料提供|
|prompts/prompt_material.py 的区块观察条目|包含它的区块：…|删除该条；对象名称和观察信息保留|
|traversal/region_scroll.py bind|滚动 target 请填写当前区块树中实际要滚动的区块 ID|滚动 target 请填写当前区块列表中实际要滚动的区块 ID|
|records/page_context.py 当前区块材料|按物理父级嵌套 Region，再嵌套其 controls|所有当前 Region 平列，每个 Region 内仍列 controls；访问来路与证据说明保留|
|named_references.py / registration_diagnostics.py|父级未知、父子环和仅依父子关系的重复归属错误说明|新合同删除这些退役说明；旧已发请求仍按原合同处理必需的格式/引用错误，不将历史父级重新保存|

不增加“无父区块”占位输出，不让 Luna 每轮重申退役字段，不增加新的任务完成条件。旧原件中的层级文字不批量替换。
