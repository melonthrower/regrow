2026-11-08 同一对象允许多条登记补充：已有对象用本次给定ID/名称，新对象用登记名称及所属区块定位；请求条目数量不代表对象数量。独立字段补充，相同内容去重，新增知识追加；同一已有知识引用可补充不同参数，单值字段不同赋值或修改/删除冲突须指出对象、两处原字段及值。已有Control的纯知识更新不改变归属；含当前外观的知识仍依赖原观察身份验收，通过后再按ID合并写一次。当前沿用原回复格式，尚未引入新请求类型/请求ID协议。原0061正常离线登记、原0043仅解码/格式、冲突标记本地通过；0新模型/GUI，原运行停61，额外假设案例未执行。

> 2026-11-07 新输出合同：Task仅state与必要remaining_question，不再输出retry_when；action_result只保留exception/recovery_handoff，真实动作/回执/后图仍在；focus_presence、uncertainties、dependency_updates及returns_to_previous退出。已知准备动作服务原Task，旧准备/共享/coverage代理不再提供完成效力。functions的唯一写入仍为function_updates，现只接正常任务提出与动作更新。旧字段在历史只读材料出现不等于新输出要求。

2026-11-01最终任务定义逐字采用用户四条原则，未加入本批应用特定示例；最终原文版尚待模型验收。

2026-11-01任务目标边界由任务正文统一维护：completion_condition围绕一个明确目标，可包含必要多步与跨对象操作；独立新问题不自动追加。task_type/schema及稳定归属不变。原图11个Calc菜单条件按用户授权由操作员修订，原值进入revisions；状态、真实障碍及原始模型答复保留，模型不代改这些旧任务。

# 四个业务对象的字段约定

## 字段的设计动机与责任（2026-11-04）

本节补充“为什么需要、谁判断和保存、后续怎样使用”，不修改字段定义、schema或Prompt。完整含义仍维护在本页原有对象章节及其链接的对象Prompt；本节不是第二套术语表。运行内部所有键不都属于业务字段。

**读法：内部稳定身份、当次模型呈现、持久记录是三层。** 当前调用可通过名称或给定编号引用，框架沿本次name_contract等映射解析为稳定ID；旧controls.index、当前ref、知识条目index和本次数组位置不能混用。下文保留的日期记录并不都代表最新外部格式，每次必填/可写字段以正常builder生成的实际schema为准。

|字段或字段组|设计目的|判断、写入与主要消费|
|---|---|---|
|name；控件description|让人和模型辨认对象，避免把一次输入值当身份；用途单独保存|Luna观察；框架存对象；发现、动作与纠错读取|
|id/ref；本次index、candidate_index、region_index、control_index|把跨调用稳定身份与本次材料位置分开，修订不会因列表重排串对象|框架分配稳定ID、解析当次引用；Luna使用给定引用；旧合同原样解码|
|controls；shared_instances；list_group/list_groups|组织成员与复用同一物理身份；共同用法分组不合并不同对象|Luna判断关系；records保存身份及引用；任务提出和两树复用|
|identity、identity_evidence、context_matches|表达新旧对象与适用上下文的依据，避免同名/相似外观自动合并|Luna判断语义；识别与记录检查引用和观察；疑点不自动变新身份|
|bbox、image、add_image、image_conditions；已有click_bbox|保留辨认外观及状态，不把裁剪当完整点击区域；已有点击区域供采集投影|模型给当前图定位/条件；框架裁图存来源；匹配是证据，不证明可操作或成功|
|knowledge[].description|保存已有用途、操作方式、适用条件与不确定性，减少重复探索|Luna观察/解释；框架按对象和来源保存；任务、功能整理、生成读取|
|knowledge[].constraints|把已知参数、候选及限制归到对应用途，避免大量取值变成独立控件|Luna按证据说明；框架保存；生成和执行取所需参数；部分候选不冒充完整范围|
|local_knowledge.add/update/delete|表达区块整体配合方式；修订被推翻内容而非留下互相矛盾的段落|Luna给有据增量；框架保留未涉及条目和来源；任务/生成复用|
|functions.name/description/supports/constraints；parameter_definitions|把对象认识整理成可复用业务目的，并保留支持与参数来源|Luna在允许更新的调用中整理；框架检查引用；functions为空不等于控件知识为空|
|jump_to及region/control/conditions；transitions|保存真实操作支持的访问关系，供后续找入口；不是物理包含或自动双向返回|框架固定实际来源；Luna判断动作后可访问目标与条件；导航/目录/采集读取|
|parent、parent_index、parent_region|现代码表达/保存包含关系，并非访问来路|旧设计与现实现仍在；取消方向已有讨论，完整候选待确认及实施，不能写成已删|
|may_open_content；needs_exploration|分开“是否通向有价值内容”和“控件自身还有具体未知”|Luna结合界面与知识判断；任务提出复用；入口用途已知不代表目标内容已知|
|operations、control、task_type、completion_condition|保存单个待解决问题及终点，而非事先枚举GUI动作|Luna提出；框架保留归属和目标。当前有function/parameter/region_content，准备不是新task_type|
|task_update；decision/reason/remaining_question/retry_when|表达原问题进展、缺口和实际障碍，防止准备或新问题替换原目标|Luna判断；records结合真实阻塞登记pending/done/blocked；blocked不妨碍其他可推进任务|
|action=complete/none；next_action|部分动作调用用complete/none承载已知答案或暂挂；建议不是已执行事实|action_commands.for_request等转入正常任务登记；不要求每个角色都输出同样task_update包装|
|dependency_updates.ready/evidence；preparatory_action；task_region/source_region|区分原问题归属、实际操作来源与准备是否满足；恢复不虚构业务成功|Luna给准备观察；框架保留原任务及真实动作，准备完成只使原问题可继续|
|inventory/evidence；controls_complete等范围材料|说明本次范围是否考虑过，不再另造一套必须清零的未知清单|设计约定由tasks承载未知；当前coverage仍有inventory、缺口和已考虑控件检查，本批不删除这些实现|
|foreground、current_regions/current、focus_presence；interactive_regions|区分当前表面、指定区块位置、原任务及历史候选，供本步理解|Luna观察；框架维护观察状态。目标语义不是操作白名单，但当前调度/候选仍有名单限制|
|exception/recovery_handoff|让被中断的步骤把真实异常交恢复，避免继续登记外部业务|模型报告异常，框架先恢复。必要系统选择器如何界定仍有已知问题，不靠新白名单掩盖|
|action/target及平台点位、文本、按键等参数|让语义意图落到当前界面的一个真实操作；坐标不是旧身份记录的固定位置|Luna选动作；绑定/投递代码核实并执行；参数以当次桌面/Android schema为准|
|action_result、returns_to_previous；回执semantic_result|区分执行回执、看到的变化、返回事实和原问题是否回答|平台记实际投递；Luna解释前后观察；exit_code=0、无异常、登记均不自动等于业务成功|
|source_call、attempt、evidence；latest_update/history/revisions|保留事实来源与修订过程，给后续调用选择必要材料|框架写来源/历史；Luna只判断披露证据。目标是一份事实源多种投影；历史选材仍有待收口路径|

### 同名字段不能跨层理解

knowledge.constraints是用途下的参数说明；区块constraints是参数目录；functions.constraints是已有参数引用。动作建议的target、实际绑定的control_ref、任务归属task_region和来源source_region也不是同一件事。具体定义继续看下面原有字段表，不把本节当作可直接发送的统一JSON。

### 哪些不是已经完成的设计

候选值完整收集与同质实例复用的尺度仍需落到登记和读取；当前代表项提示尚有未确认草稿。取消父子关系及共享控件纠错/点位核对的候选见[方案入口](../../DESIGN_INTENT.md#待实施方案)。本节只澄清职责与缺口，不借文档补充更改字段语义或扩大任务完成门槛。


2026-10-30累计合并：当前唯一字段语义来源为四份对象 Prompt，实际输出权限/必填由本次 schema 决定，17 类配方选入所需语义。区块不等于单一功能；控件是实际操作对象，具体身份与共同用法分组分开。completion_condition 按“足以使用，同流程选代表”，knowledge 保存用途和必要条件；同类数据不必逐项登记。下文较早带日期说明保留历史含义，现行组合与验证状态以 CURRENT_FRAMEWORK 为准。 本轮19项聚焦与40份离线呈现核对、两份真实记录离线预览通过；0新Luna/GUI，行为仍待验证，详见当月日志。

本页是控件、区块、任务、动作及其附属字段的统一讨论入口。2026-10-24按当前工作树四份对象 Prompt 补齐字段含义；这是现有正文的整理，不是一次新的语义批准，也不代表工作树候选已经实现验收。只有控件六项明确标为本轮已确认。代码、Prompt、Schema及历史记录均未因本次文档整理而改变。

## 阅读与来源

- [控件正文](../../../src/regrow/prompts/对象/控件.prompt)：`control.*`，以及`shared.output_contract / shared.registration / shared.conditions`。
- [区块正文](../../../src/regrow/prompts/对象/区块.prompt)：`region.*`。
- [任务正文](../../../src/regrow/prompts/对象/任务.prompt)：`task.*`。
- [动作正文](../../../src/regrow/prompts/对象/动作.prompt)：`action.*`；平台参数另见[桌面](../../../src/regrow/prompts/平台/桌面执行.prompt)、[Android](../../../src/regrow/prompts/平台/Android执行.prompt)。

下文按对象汇总正文中全部字段及其直接嵌套项；调用输出、长期保存、输入材料中的状态分开标注。字段是否必填、合法结构及本步允许更新的对象，仍由本次输出格式决定；这不是让每轮输出全部字段。未把运行日志的每个内部键扩充成业务对象字段。

新对象按本步格式登记。旧对象按要求引用身份，只更新有实质变化的属性；省略不表示删除，空数组、null、false依具体字段解释。编号照给定材料填写，本次输出数组从0开始；不同层级的index不共用编号空间。只有明确说明增量更新的字段采用该语义。

## 控件

控件是承载操作的界面对象，禁用或暂不可操作不改变身份。纯说明文字可以辅助辨认，但不单独登记为控件。全局稳定ID对应一份控件记录，多个区块可直接引用它；同名、同图标或同位置不足以合并身份，值、标题、模式或用途变化也不足以新建身份。

### 本体字段与本轮确认

2026-10-24已确认：name、description、knowledge、conditions、image、jump_to。conditions属于附属条目，不新增为控件顶层字段。2026-10-29候选已改为：控件description只在名称不足以辨认时补充外观，本批已有真实新控件登记的限定验证。 其余条目按现有正文整理，不声称进行了新的行为验收。

| 字段 | 含义与边界 |
|---|---|
| name | 稳定、便于引用的简短名称，可带用途，如“音量滑块”。本次输入“北京”不把搜索框改名。改名不等于换身份。 |
| description | 本轮确认仅描述用于辨认控件的稳定外观，如“扬声器图标旁的水平滑块”。用途、作用对象、使用规则归knowledge；当前值和临时状态归观察。本条不改变其他对象或知识条目中的同名字段。 |
| knowledge | 可复用的用途、作用对象、使用方式和规则列表。识别推测与确认事实都可保存，按实际来源区分；修订或出现在结果回复中不自动成为验证。空知识不等于无用途；旧对象提交空列表不清空原知识。 |
| image | 已登记身份外观的path/conditions列表；path由框架生成。用于辨认，不是点击范围，也不证明当前可操作或操作成功。无图时为空列表。 |
| jump_to | 实际来源控件到可访问目标的已验证关系，目标可为区块或独立控件；用途猜测不构成路线。长期保存region、可选control和conditions，控件目标仍带所属区块引用。实际过程与来源留在历史。 |
| may_open_content | 是否能打开或展开本次应用主要功能相关、有探索价值的内容。当前新输出为boolean：有依据当作此类入口填true，否则false；初识可据用途推测，不等于已验证路线。探索过或暂禁用不自动改false。历史null可保留，不是新输出要求。 |
| needs_exploration | 控件自身是否有具体且值得探索的未知：true有，false没有，null材料不足。不是目标区块完成状态，也不是操作许可；true不强制重复建任务，false不免除访问尚未知目标内容。 |

例如顶部“＋”可为may_open_content=true、needs_exploration=false：入口用法已知，目标内容仍可未知。输入框不打开内容但使用规则未知时，两者可分别为false、true。

### 知识及条件

来源块：`control.knowledge_base / knowledge_initial / knowledge_result / knowledge_revision / knowledge_constraints`、`shared.conditions`。

| 字段 | 含义与更新方式 |
|---|---|
| knowledge[].description | 该知识项的用途和作用对象说明，不是外观描述。记录“调整播放音量”，不将“当前50%”当通用用途。必要的不确定性与适用边界保留。 |
| knowledge[].description（当前输出） | 用途、使用方式及必要的页面、模式、限制、不确定性写在同一描述中；不再输出独立conditions。旧知识条件读取为描述的一部分，原历史不改写。 |
| knowledge[].index | 修订本控件已提供知识列表的条目编号；新增项不填，独立内容分别保留，完全相同内容不重复保存。未列出的旧项保留；修订保留仍成立的用途、条件、参数规则，不仅追加一个有条件新项而留下冲突的无条件旧项。 |
| knowledge[].constraints | 该用途下有依据的参数规则和已知候选，可省略；不是必须穷尽测试的清单。结构为map：key是参数名，value是{description}定义对象，见下方完整示例。 |
| constraints中的description | 参数键给出名称，description写具体要求。保留条件、已知选项及限制，不从一次成功输入7推断完整范围或“只能为7”。 |
| image[].conditions / image_conditions | 图片适用的可见外观或有依据状态，如“显示暂停图标”；不凭图标推断尚未确认的业务状态。 |
| jump_to[].conditions | 路线适用的标签页、模式等条件；不把目标内部偶然落点当入口必要条件。 |

`knowledge[].constraints` 的具体结构如下（用户2026-10-24指定示例）：

```json
{
  "constraints": {
    "振动时长": {
      "description": "1分钟、5分钟、10分钟、15分钟、20分钟、30分钟。"
    },
    "贪睡时长": {
      "description": "1分钟、5分钟、10分钟、15分钟、20分钟、30分钟；当前显示10分钟。"
    }
  }
}
```

`constraints` 可省略；`knowledge[].description` 有内容且有来源证据（`source_call`存在）时，parameter任务可直接结算，不以constraints非空为前提。它是补充结构，不是结算门槛；任务仍须判断原问题已回答，既有真实阻塞仍按原合同处理。示例中的“当前显示10分钟”是本次状态，不能当作固定值或通用约束。

Luna根据截图与历史提出语义，框架保留来源和引用。知识归实际对象；入口打开的目标内部规则归目标。只补已有控件知识时，controls项只填写index和knowledge；不同时填写may_open_content、needs_exploration、region_index等对象观察字段，否则进入对象观察及归属核验。只有知识的修订不应被解释为本次又观察或操作了该对象；当前候选的具体接线和验收边界见[记录模块](records.md)。

### 身份、外观与本次关系输出

来源块：`control.references / identity / visual_scope / action_availability / bbox / add_image`。

| 字段 | 含义与边界 |
|---|---|
| controls[].index | 引用输入材料中的已有控件编号；明确新对象不填，候选不确定时不猜编号或另建副本。 |
| controls[].region_index | 关联本次regions数组的区块位置，不是稳定ID，不表示删除其他区块关联。 |
| uncertainties | 本步提供该字段时记录具体身份候选与疑点；不是新身份或任务的自动判据，其他已确认工作可继续。 |
| bbox | 指定原图中的身份辨认范围，含必要辅助标签；无法可靠裁图为null，不等于对象不存在。旧对象普通复认可按本步要求省略。 |
| bbox.left / top / right / bottom | 原图整数像素边界，右下不包含，满足left<right、top<bottom且位于原图内；不是宽高、归一化值或操作框。 |
| add_image | 动作后主动判断值得保留的状态变化；已有状态复用，不以模板匹配失败为前提。仅有的旧模板状态未注明时允许提议追加，先比较历史原图与当前原图：同外观复用，不同则分别说明状态并补定位。省略/false不清空旧图；仅缺说明、位置或输入文字变化不足以追加。 |
| image_conditions | 本次新增外观的条件，通用图为[]；路径由框架生成，不由Luna编造。按调用可能先请求再单图补范围。 |
| controls[].list_group | 所属区块内同类交互分组，转换为区块list_groups，不保存在控件本体。详细含义见区块节。 |

身份图可以包括不可点击的说明标签，操作坐标必须依据当前图中的实际交互区域。前景、遮挡、焦点和禁用状态影响本次可操作性；识别或匹配成功不保证业务结果。

### 访问关系更新

来源块：`control.jump_base / jump_new / jump_revision`。

动作后回复的jump_to位于顶层，与controls并列，不写controls[].jump_to；框架按实际操作保存到对应控件。长期记录归控件与本步输出层级不同。

| 字段 | 含义与边界 |
|---|---|
| jump_to[].region_index | 本次新增目标所属regions数组位置。 |
| jump_to[].control_index | 目标是独立控件时，引用本次controls数组位置，且与目标区块一致；不是该控件的历史index。区块目标不填。 |
| jump_to[].conditions | 仅有适用条件时填写；通用新路线省略，修订旧路线时明确给出条件列表。 |
| jump_to[].index | 仅定位“已有跳转”列表中的旧路线以修订conditions，不是控件/知识编号，不表示本次到达目标。 |

确认实际操作产生访问效果且缺少关系时登记，已有关系复用；仅状态或输入值变化不自动建目标边。无更新时按本步省略或填[]，不删除旧路线。原任务continue/defer也保留已确认关系；目标已可访问时不要求重演路线。

## 区块

区块是具有稳定用途的界面区域，包括操作、导航和信息展示区；不要求含控件或独立业务功能。稳定用途描述区域，但相同用途不足以证明同一身份。

### 身份、成员与分组

来源块：`region.common / identity / list_group / shared_instances`，几何形状补充参照[首屏格式](../../../src/regrow/prompts/输出格式/首屏观察.schema)。

| 字段 | 含义与边界 |
|---|---|
| id（长期记录） / ref（调用引用） | 框架的稳定区块身份；旧区块用材料给定ref，不把本轮行号当ID。 |
| name / description | 稳定名称及区块用途、职责说明，如“城市选择对话框”。控件description仅外观的新约定不扩展到这里。 |
| identity / identity_evidence | 按本步格式声明新旧身份；不确定时identity="uncertain"，不绑定ref，填写name/description并在identity_evidence说明候选和缺口。 |
| parent_index / parent_region | 前者是本次regions中物理包含父区块的位置，无父级按格式为null；后者保存对应关系。都不是进入来路。 |
| bbox；image / icon_image | bbox为身份裁图范围（left/top/right/bottom或null）；长期图引用来自接受的观察，可缺省。身份图不等于操作区域，当前未删除区块图片读取。 |
| out_of_scope_reason | 整个区块确实超出本轮允许范围时的原因，不因暂不可见而填写。 |
| controls | 长期成员引用全局控件ID；同ID可被多个区块引用，不复制控件。 |
| list_group / list_groups | 模型在controls成员上填写分组名；框架在区块保存“分组名→控件ID列表”。普通控件省略。 |
| shared_instances | 声明本区块成员与材料中来源控件是同一身份；要求该字段而无确认复用时为[]。不是外观相似或功能共享声明。 |
| shared_instances[].control | 本区块待复用身份的控件。 |
| shared_instances[].source_region / source_control | 材料已提供的来源区块及对应控件，不猜来源。 |
| shared_instances[].reason | 支持同一身份的具体依据；复用后实际任务/动作归属及知识适用条件仍保留。 |

list_group允许多个已辨认成员分别登记，保存独立ID；共同交互方式可以选代表探索，不表示其他成员已操作，也不合并身份。是否值得进一步探索取决于目标的新能力、对象、条件和流程，不仅看列表外形；有独立功能的入口保留必要未知，已知方式下的同类实例不重复建任务。分组本身不创建或结算任务。

### 区块知识与功能目录

来源块：`region.function / registration / local_knowledge / target_summary / parameter_definitions / functions / evidence / exploration_status`。其中`exploration_status`是提示说明块ID，不是模型输出或长期记录中的业务字段。

| 字段 | 含义与边界 |
|---|---|
| local_knowledge | 按用途分段的稳定展示内容、操作方式、条件和限制；保留控件配合、依赖、互斥及仍相关未解问题。当前值和一次过程放证据。 |
| local_knowledge.update[].id / text | 指定已有段落及完整替换正文，保留仍成立内容。 |
| local_knowledge.add / delete | add新增正文、框架分配编号；delete列出已被完整替代或确认错误的段落编号。未涉及段落保留。 |
| parameter_definitions[].ref | 逐字引用给定参数完整键，不造来源；functions.constraints引用的每项参数都须有定义。 |
| parameter_definitions[].description | 参数稳定含义、已知选项/格式/范围/限制及条件，不把样本值当规则或把部分候选当全部范围。 |
| functions | 按独立业务目的整理的能力条目，可为空；共同实现同一目的的操作合为一项，独立目的分别登记。 |
| functions[].name | 简短、明确的业务目的，不绑定本次值，如“创建条目”。 |
| functions[].description | 功能用途、主要操作及必要条件与限制；不另填object/completion/unconfirmed。旧独有说明合并呈现，原证据不覆盖。 |
| functions[].supports | 支持结论的给定控件/区块知识引用；每项功能至少有一个真正支持该目的的本地对象。外部来源须有已提供关联。 |
| functions[].constraints | 相关参数的完整键，须有parameter_definitions且来源对象列入supports；不是当前取值，不为补引用新建任务。 |
| evidence | 解释材料支持什么及实际来源、条件、失败和边界；supports提供引用，evidence提供事实，引用本身不是成功证明。 |
| observed_link_only（输入状态） | 只按材料所说明的关联事实理解，不等于已确认导航用途，更不支持补造触发控件或目标全部能力。 |
| done（输入状态） | 相应探索信息已登记，不表示业务执行成功；选项可见、数值回显不能证明保存或重启持久。 |

业务功能归实际承载目的的区块。仅提供入口、参数或辅助结果的区块不因此拥有整项业务。信息展示区可仅有local_knowledge，不补造功能或任务。新的同问题、同条件证据可解决旧疑问；其他条件的失败与相反证据不能因新回复更晚而删除。

### 既有保存及纠正字段

以下保留既有记录说明，不新增模型必填项：transitions记录实际动作后区块去向；区块jump_to用于区块自身操作的访问关系，控件操作的关系仍归控件；区块constraints是参数定义目录，不能与functions.constraints的引用列表混淆。

behavior_context为行为上下文，distinct_regions为确认不同的区块，separated_from为分离来源，partition_children为拆分结果，merged_records为旧编号/名称别名记录。历史shared_controls保存旧行为共享组，不新增该包装或shared_control_ref，不自动转成同一身份。

## 任务

来源：[任务正文](../../../src/regrow/prompts/对象/任务.prompt)全部`task.*`块。任务围绕控件或区块的原问题组织调查，是待解决探索问题的清单；准备任务服务给定原目标，不新增一种task_type。原问题对象、实际操作对象、操作后目标分别保持归属。

### 提出与更新字段

| 字段 | 当前合同 |
|---|---|
| new_tasks | 本轮为给定区块新增的独立问题，按探索次序排列；没有新问题填[]。 |
| new_tasks[].control | 本轮给定控件引用；同答新控件须先被对象登记接受。空字符串表示区块自身。 |
| new_tasks[].target | 固定原问题及涉及对象/范围，按原文保存；后续剩余问题不能替换它。 |
| task_update | 本轮允许判断的已有任务；普通更新/提出为数组，单任务复核保持单对象。 |
| task_update.task | 使用本轮给定任务引用，不新建或改绑任务。 |
| task_update.state | done原问题已有明确答案；pending仍可继续；blocked受到具体条件限制。 |
| remaining_question | pending/blocked必填的剩余问题；done省略。 |
| retry_when | blocked必填的恢复条件；pending/done省略。 |

新任务不生成task_type、模板、reason或completion_condition；同所属区块、同control、完整target相同才确定为冗余。语义重复由Luna结合已有任务判断。知识归控件knowledge或区块local_knowledge，不复制任务答案。

旧任务仍读取原completion_condition及历史类型目标，不批量改题。旧answered/continue/defer只读映射为done/pending/blocked，原调用、原答及审计原件保留。新target任务不套旧function的用途知识产物门槛；真实执行、身份、未结登记和准备阻塞继续由task_updates.decide核验，不能直接将模型state写成任务状态。

### 下一动作与准备判断

`next_action` 属于动作后更新的调用根，与task_update并列；它不是Task字段。它直接采用公共可执行Action，包含实际动作所需target、坐标、文本、终点及reason；不包含complete/none。省略表示本次没有接续候选，不继承旧建议。

只为当前原任务提供一步动作，依据本次动作后图。主结果、对象知识和任务判断先独立登记；坏动作单独进入正常动作纠错。登记成功后，runtime.pending_action仅保存真实更新call/next_action、已接受后图的observation/snapshot和原任务引用。

下个小步先恢复与调度，再核验任务仍pending、无真实阻塞、任务未切换、观察仍适用；消费指针后交原action job及执行账本接管。暂停作业也在正常调度后恢复并重查；投递前仍使用当前新图核对，不把原坐标改称来自新图。历史复核、历史补登记、任务提出与对象补登记不开放next_action。旧任务建议仅保留历史阅读，不再执行。

| 准备字段 | 含义 |
|---|---|
| dependency_updates[].region / task | 本轮给定的被准备原任务；不是准备动作自身。 |
| dependency_updates[].ready / evidence | 有新观察依据才更新是否满足原前提；ready=true不表示原问题完成。 |

prepares/prerequisite保留准备归属；blocker/deferral保留真实阻塞与恢复条件。tasks.json及审计接口仍为唯一任务来源，latest_update只保存判断和source，update_history保留前次原判断。

## 动作

来源：[动作正文](../../../src/regrow/prompts/对象/动作.prompt)全部`action.*`块及本步平台声明。操作提案、实际执行尝试、观察结果分开；不把提案或其他控件的选中状态写成已执行事实。

### 提案及平台参数

| 字段 | 含义与边界 |
|---|---|
| action | 本步合法操作类型；complete与none是协议结论/不操作分支，不是已经执行的GUI动作。 |
| target | 拟直接操作对象，不必等于原任务对象。已确认对应当前图的已登记控件使用给定region/control；不把准备动作改绑成原任务。 |
| target的短描述 | 当前图中拟操作控件未给身份时准确指认。此类点击/输入先由框架识别登记对象和归属，尚不执行；登记后重新选择。不套用其他编号。 |
| reason | 为什么现在选这一步、补原问题哪项信息；准备/导航/返回说明必要前提，不另造已知准备操作的探索问题。 |
| x / y | 需要点位时的当前指定截图整数像素坐标；键盘/全局动作按本步协议，不沿用未经确认的旧坐标。 |
| end_x / end_y | 桌面drag为拖动终点；桌面scroll为方向和幅度编码，不是拖动终点；Android scroll为滑动终点。 |
| text | input_text的替换文本，当前协议为可打印ASCII、空串清空；key_press为键名；桌面hotkey为以+连接的组合键。不等于已投递文字。 |

桌面click/double_click/long_press/right_click/hover对应点位操作，hover仅移动指针；input_text全选替换；scroll查看下方时end_x=x且end_y<y，查看上方时end_y>y。Android滑动两点在同一可滚动内容区。桌面back发送Esc以取消或关浮层，不等同浏览器后退；Android back为系统返回。wait等待观察，不代表任务完成。Android没有hover/right_click/hotkey/鼠标drag，键名范围亦按平台声明，不通用化。

已登记控件的`target`填写`region稳定ID/控件稳定ID`，如`r0001/c0001`；不填`控件[index=N]`格式，那是对象更新时的另一套引用，不通用于动作target。

反例：`target="r0001/控件[index=0] 顶部新增按钮"`混用了对象更新编号和动作引用，并附加名称；应逐字使用材料给定的`target="r0001/c0001"`。

### 结果、回执与结论

| 字段 | 含义与边界 |
|---|---|
| action_result.description | 概括本次尝试后可确认的直接变化、反馈或失败，保留重要不确定性。没看到相关变化不自动等于失败，部分已知不能被整体“未知”覆盖。 |
| text_delivered（回执输入） | 提供的文字投递事实，不从截图反推。false只说文字未发送，不代表点击/聚焦也没发生；true或回显不证明保存成功。 |
| action_result.returns_to_previous | 本次真实关闭/退出并返回对应进入记录的来源表面才true；身份/落点符合，不要求值和滚动位置完全相同。false是未确认该返回，不一定证明绝无返回。 |
| action="complete"及reason | 原探索问题已充分回答；按本轮要求同层补缺少答案，已有充分答案不无谓重报。不代表业务一定成功。 |
| action="none"及reason位置 | 本步不操作，reason保留在动作层；complete同样使用动作层reason。task_update只提交state及对应的remaining_question/retry_when，不提交reason。 |

点击“设置”后“常规”标签已选中，可记录当前内容关系，但实际动作归“设置”，不能编成已点击“常规”。回到曾访问页面、看见下层或仅知道可返回，不足以returns_to_previous=true。

框架保留实际动作来源、原任务引用、回执与观察；来源区块source_region和任务归属不可混写。结果登记失败的已投递动作应续登记，不能为了修记录重做GUI。本节是字段解释，不证明当前候选已通过真实执行验证。

## 历史字段与当前讨论边界

控件possible_purpose、顶层constraints、list_group、icon_image、shared_control_ref、merged_records已退出控件七项本体；知识、分组、图片和别名分别按上述位置维护。旧记录及来源不批量改写。历史任务findings不是当前新答案入口；区块functions.constraints仍是参数引用，不能与knowledge.constraints的参数规则混为一谈。

当前整理覆盖四对象Prompt中的业务字段及直接附属项；平台参数作必要补充。foreground等整步场景材料、纠错专用协议及全部内部账本键不冒充四对象本体。现有工作树含前置未提交候选；这里说明其当前正文，不提升实现或验收状态。description按辨认需要填写的约定已同步当前Prompt；本批实际验证与尚存质量问题见2026-10月志。

## 任务与本轮进度

任务存在 tasks.json，以“区块 ID / 任务名”为键，控件字段引用全局 ID；不在区块中复制任务。实际动作仍有唯一 source_region 和原任务引用。同一控件在其他区块发生的动作可作为历史，但上下文标明来源，不宣称当前区块已经执行。

runtime_work.json 以区块 ID 保存下列本轮字段（与区块功能知识分开）：

- task_inventory：本次已考虑哪些控件、清点是否完整、具体待复核项；不是任务列表。
- function_inventory：上次功能总结来源及材料摘要，用于材料变化后重新总结。
- out_of_scope_reason：本次运行范围为何排除该区块。
- registration_gaps、registration_gap_history：登记缺口与处理历史。
- support_review_key：功能支持复核标记。
- partition_review：区块拆分的未分配项/冲突。
- control_observation_revisions：控件观察纠正历史。
- prior_local_knowledge、prior_partition_functions：区块合并/拆分前保留的旧总结。

runtime_state.json 保存当前区块、活动任务、观察等调度状态。object_history/action_log/task_history 及原调用保存程序来源与历史；不作为普通提示全文展开，也不新增一套平行事实。

2026-10-29：动作结果的description同时承载必要依据，不再分填evidence；foreground不再分填evidence/uncertainty。当时task_update.reason按需；现已由2026-11-06的state合同替代，旧原答只读；previous_regions.evidence仅歧义时补充。当前交接从已有结果/前景读取，旧独有交接继续可读，新输出不填handoff_summary。截图与实际投递证据由程序保存。


## 2026-11-01 具名对象与嵌套控件（候选，验收进行中）
模型边界统一由 `recognition/named_references.py` 将本次披露对象显示为可读名称；同名按所属区块限定，规范化/唯一末尾区字变体仅解析引用，不推断历史身份。发现和动作后更新将控件置于所属 `regions[].controls`；更新以 `regions[].current=true` 明确当前前景，历史知识行不自动入前景；跳转及物理父级用名称引用。内部依然沿用稳定ID、既有扁平登记合同和已接受的任务/操作边界。旧调用按其保存合同读取。
原始请求/回复与 `interpreted_request.json`、`interpreted_response.json` 分别保存；Runner及记录消费者复用统一内部解释，不重写原答。具名局部纠错沿用对象修订合并，省略对象/字段保留，明确撤回与关系核对仍有效。功能名称与对象名称按字段区分，复合功能/参数引用恢复其内部前缀，知识内容不改写。此为协议接线候选，不表示100次遍历已通过。验证与失败见 `artifacts/runs/named_nested_20261101_01/` 与本月日志。
