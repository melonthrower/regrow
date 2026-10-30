# 四个业务对象的字段约定

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

| 字段 | 当前正文含义 |
|---|---|
| operations | 按建议探索次序列本轮新增任务，考虑依赖和离页影响，不是预排GUI动作。范围为给定当前区块及其控件；无新任务为[]，不借此重排已有任务。 |
| operations[].control | 给定完整控件名；仅区块自身问题可为空字符串，不能用空值代指未知控件。 |
| task_type | function调查用途、直接效果或去向；parameter了解可用输入、取值及必要条件。按原问题而非控件外观分类。 |
| completion_condition | 新operations必填的固定结算条件：得到什么直接观察或已有证据即可结束本问题。随task保存；后续只判断是否满足，不以remaining_question改写。缺字段的旧task不补写。 |
| task_update（本步规定的对象/列表） | 对允许更新的已有原任务及实际操作控件相关任务作判断。引用与层级遵循本步格式，不借此改目标、类型或条件。 |
| task | 本轮提供的任务引用；只有程序明确绑定唯一目标时才按该步格式省略。 |
| decision | continue仍有必要问题且无明确推进障碍；defer未回答且有实际障碍；answered原问题已有足够证据。 |
| reason | 判断依据与证据，说明失败、相反观察、障碍或限制对原问题的影响；不重复抄缺口和恢复条件。 |
| remaining_question | continue/defer时尚缺的具体原问题答案。不是下一动作、准备控件用途或“参数未穷尽”。answered不带活动缺口。 |
| retry_when | defer后可重新考虑的、对应实际障碍的可判断条件；不是“下次再试”或操作序列。continue/answered不带活动恢复条件。 |
| next_action | 本步允许时的可选建议，服务原问题；不是执行事实，缺建议不单独构成defer。defer/answered不附非空建议。 |

`blocked`是框架保存的状态，不只来自Luna的`defer`；框架也会因结果待登记、执行未确认等原因设置blocked，这类情况下Luna输出continue也不能直接解除。

任务复用同控件同类型的已有记录；记录复用不预设状态。用途和目标相关内容已知时不因未点击而新建证明任务；入口用途已知但目标内容未知且无任务覆盖时，仍需提出访问目标的任务。同一设置的普通候选不逐项建同类任务，新分支或独立功能另判。

function控件任务：已有对象知识足以回答可直接收口；仍需操作时，必要准备后一次适用操作及直接结果即可，不顺带穷尽目标内部功能。parameter以知道如何使用、获得有据实例及直接结果为界，不自动研究全部字符、取值或整项业务。原问题明确要求仍须回答。准备证据可支持原问题，但准备完成不自动完成原任务；当前所属区块不可见也不单独构成暂挂。

### 后续建议与准备判断

| 字段 | 含义与边界 |
|---|---|
| next_action.region / control | 建议动作实际作用的给定区块和控件，希望到达的地方写reason。可引用本轮允许的其他区块；未知对象不编引用。 |
| next_action.action / reason | 本步合法动作名及具体操作内容、补足的缺口；输入意图按本步协议表达，不自加字段。非空建议须同时具备四项，不输出{}。 |
| next_action=null / 省略 | null明确撤销；省略无新建议。框架消耗已确认执行的旧建议，未执行建议仍须按当前图和原问题核对，不因保留而重复执行。 |
| next_action.control="" | 仅用于本步允许的区块滚动、返回、等待、按键/快捷键等，不代指未知控件。 |
| dependency_updates | 仅更新本轮允许处理的原目标准备条件；不是批量重置不可见目标。 |
| dependency_updates[].region / task | 被准备的原目标引用，不是当前执行准备动作的区块/准备任务。唯一程序绑定时按本步结构省略。 |
| dependency_updates[].ready | true有当前有效证据确认全部必要前提；false尚未确认全部满足，含确实未满足或证据不足，不一律表示已证实不可用。 |
| dependency_updates[].evidence | 原目标前提的实际观察，区分条件未满足与无法核实。投递回执或打开入口不足以证明准备完成。 |

ready=true只表示可以开展原任务，不代表原问题已答；前提变化后旧true也不能直接沿用。准备任务是否answered按其准备目标，原任务独立判断。

### 答案归属与内部状态

当前工作树正文把用途/参数统一写入实际控件knowledge（参数在constraints），区块事实写local_knowledge；task_update只作问题判断，不再要求重复提交knowledge/findings。continue/defer也可记录部分知识；已有适用知识可直接使用。历史findings及旧任务答案仍作为兼容来源保留，不是当前新输出字段。

[task_updates.decide](../../../src/regrow/records/task_updates.py)中，decision在无硬阻塞时映射为pending/done/blocked；answered还核验答案及已有真实执行、身份或前提阻塞，不能把模型字符串当必然完成。pending和blocked均未解决；暂挂不等于取消其他可推进任务。

长期tasks.json按“区块ID/任务名”引用；control绑定全局控件。latest_update保存最近判断、建议与source，update_history保留前次判断，completion_basis保存结算依据；这些经[任务记录接口](../../../src/regrow/records/tasks.py)保留在历史，不另存一套答案。prepares/prerequisite记录准备归属与前提，blocker/deferral记录阻塞与恢复条件；这些是框架记录，不要求Luna自行补字段。

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
| action="none"及reason位置 | 本步不操作。无task_update时理由在外层reason；通过task_update作判断时在task_update.reason，外层不重复。 |

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

2026-10-29：动作结果的description同时承载必要依据，不再分填evidence；foreground不再分填evidence/uncertainty。task_update.reason按需；previous_regions.evidence仅歧义时补充。当前交接从已有结果/前景读取，旧独有交接继续可读，新输出不填handoff_summary。截图与实际投递证据由程序保存。
