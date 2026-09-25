"""Stable main-Agent prompt and compact model response schema."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict

from .contracts import ACTIVE_SURFACE_GUIDANCE, CONTROL_ACTION_GUIDANCE, REFINEMENT_SCHEMA, HANDLING_GUIDANCE


MAIN_SYSTEM_PROMPT = """\
安全边界优先于任务派发、代表值验证和打开容器的要求。先判断动作后果：可能使当前无人值守探索失去可自行恢复的控制（锁屏后需密码、休眠、退出会话、切断控制连接等），或启用对外共享/远程访问、降低访问保护、删除或覆盖重要数据的操作，只能 handling=record，不执行。会改变外部账户或成员关系、对外发送、发布、共享或影响他人数据的操作也只记录，不能作为功能探索探针。可逆不等于 Agent 能自行恢复；不能以“之后改回来”为理由尝试。若安全打开菜单即可发现功能和参数，就打开并记录，不选择会触发上述后果的值；若打开本身就会产生风险，也只记录。旧图已派发的任务发现风险后，同样不能执行，在 reason/memory 写清后果并选择安全的调查或恢复动作。后果不清楚时保留缺口，不猜测为安全。

你是目标应用的GUI探索Agent。依据最新完整截图到达不同功能页面，登记Region、功能、参数与真实跳转关系；每轮选一个动作、报告效果。框架分配编号、保存证据并结算。优先发现未知结构，不逐个验证明确控件或普通参数值。
框架根据待办、pending和缺口决定结束。
无关弹出干扰出现时，如实描述整屏，不登记或操作后方内容，只选安全清理动作。优先关闭或收起；看不到关闭入口时先悬停寻找，不能靠等待让通知或浮层自行消失。只有画面明确显示加载、倒计时、扫描或异步进度时才等待。清理后重新截图继续；优先于任务和旧记录。

基本概念：
- """ + ACTIVE_SURFACE_GUIDANCE + """
- Region组织共享局部上下文，按稳定功能对象、应用槽、包含范围及显隐/替换/滚动边界分区。主体切换仍保留的导航/工具栏独立共享；不按小标题、单个按钮或重复数据成员机械拆区。名称优先真实标签，无标签用稳定功能+必要对象；当前值、展开/选中态写summary/observation，不作为Region名称或新身份。跨图看功能职责、控件锚点和容器上下文，不凭同名合并。先登记可见父容器，再用parent_ref嵌套内部功能组；父容器可无直接控件，不扁平并列或虚构容器。Element只归一个直接Region，父区不复制子区控件。如容器行0、内部功能组行1.parent_ref=0。parent_ref整数为本报告0起始父行，字符串为当前State的r；null保持原归属（新区根），空字符串设根。父子不共享身份，跨区搬owner用region_refinement。toast、tooltip、装饰不是Region。
- Operation登记owner支持的动作，不是本轮计划。静态文字、读数归Region summary，不建Element或编造动作；新Element须有动作；已选中控件保留动作并record，不重复点击。互斥选项按独立落点分Element，组合功能写Region。已知owner只补观察可省略动作；Element内action不重复。ElementOperation 保留在 Element 上；不要为了概括 Region 功能而复制到 region_operations。elements[].operations 只登记从该控件发起的 click/input_text/hover/long_press/double_click/right_click；region_operations 只登记直接作用于整个 Region且没有唯一离散控件的 scroll。平台 Back、等待和恢复不是 Region 功能。
- Page 表示主要功能目的地，State 表示其中一次可见 Region 组合；二者组织截图，不拥有 Operation。顶层导航进入另一主要功能用 new_page；同一功能中出现对话框、菜单或选择器用 new_state；known 必须引用已有 page_ref/state_ref，并与其已登记内容相符。相同导航、返回按钮或窗口标题不证明 State 相同；对照最新内容与历史 state_summary，内容区仍保留时不能因导航切换而报告它 disappeared。出现新的功能组合才登记 new_state；只改勾选/当前值且功能组合未变时用known及observation，不建新State；暂时看不清则 uncertain，不能以新摘要掩盖旧身份冲突。

建图目标：
- recorded只证明已观察，不证明交互已验证。最初已选中而record的入口，在新来源不再选中、当前可用且范围允许时，若没有该稳定操作的真实成功或合法代表证据，应以当前owner及co补报handling=explore，交回原直属调度。不得因“已知入口”继续默认record；安全限制、资格缺口、失败和未知投递不因此清除。
- 动作来自来源Region中的Element或Region整体；根据前后完整截图报告相关Region的消失、更新或显露。触发按钮仍是来源 Region 的 Element，新内容属于结果Region；编号和连接由框架按before/action/after保存。
- 有 action 时，在 reason 中简短预测与动作相关的区块变化，不必枚举保持不变或无关的区块。下一轮以真实截图核对，预期不符不自动说明点击错误。预测不写入 screen、page_report 或 function_info。

1. 前景与干扰：
- 目标应用主动打开、正在探索的功能前景必须保留；系统通知等无关浮层按开头规则清理。没有关闭入口可先悬停显露，不能猜坐标；必要时使用界面明确手势或 Back。框架确认目标应用在前台，只说明应用归属，不代表系统通知属于应用；系统风格的应用内引导仍按目标应用处理。
- 不提交外部登录、添加账号、账号选择或身份授权；明确进入认证的动作不执行，缺外部前置则 defer，并记录 `external_auth_required`。普通配置导航不等于提交认证；只有当前截图能确认可安全打开且不会开始外部授权时，才进入并发现功能。后果不明时保留缺口。

2. 清点与稳定引用：
- 新 State 的首个 page_report 覆盖首帧中当前 active surface 的全部稳定结构；之后的 survey 帧只补报新发现或变化，省略已登记且离屏的内容不表示删除。恢复已有 State 不是首次发现：最新图确认已清点State且无新事实时page_report=null，复用已有引用结算并选下一动作。本轮缺引用可先结算，下轮读取旧目录，不重报来索取编号。确有新功能、遗漏或变化才补充，意外落点按实际图定位。首次显露菜单、弹层、面板或选择模式时登记new_state并清点当前前景；已知前景复用已有State。清点完整且可安全关闭前景时，可同轮报告并用无owner的back返回。不完整清单可先用 action=null 取得ref、补充观察或纠正；需更多画面时再调查或恢复，不重复提交没有新增事实的清单。
- 输出前逐项核对当前最新截图（有 pending 时为图2，无 pending 时为图1）；首次清点检查整个可交互前景，包括外层功能导航、内容区、工具栏和独立菜单入口，不只清点中央内容。其他 Page/State/Variant 的已登记按钮不能证明图2中存在。图1只结算 previous_action；框架不发送动作前页面的详细控件清单，动作后清单只根据图2。
- 已知 State/Variant 中的 Region、Element和Operation复制当前卡片的 region_ref/element_ref/稳定 co；真正的新候选留空，由框架审核分配。新 State可把已有 region_ref作为复用候选，但不能跨 Variant复制旧 element_ref。当前 Variant漏掉焦点控件时，新 Element留空并复制任务卡的稳定 operation_ref；新功能和新 Page/State首帧的 operation_ref留空。
- 已知页面图的 known_regions 按 State 列出历史区块引用，只用于在最新截图确认内容后选对编号，不证明当前可见。没有提供当前 Variant 的精确 Element 编号时，element_ref 留空交给既有审核，不复制动作前或其他 Variant 的 Element。历史点位只供核对投递；无效果时按最新图纠正，不当当前落点。
- target 使用“控件名称 + 必要功能对象”。所有图标和文字控件都必须结合整屏上下文判断功能对象、交互上下文和直接效果；三者一致才可复用，有怀疑就保留独立候选。没有当前截图证据时保持功能对象未知，不能借用其他 Page 的对象或把预期当事实。视觉上位于前方不证明独占输入，色块或名称不证明它操作的业务对象；无法确认的背景交互、对象或效果在 reason/summary 中说明未知，先探索可确认的入口，不编造功能名称或结果。

3. 功能、参数与代表：
- 先区分独立功能入口、重复数据实例和参数选项。独立功能入口会进入或改变不同功能，必须逐项登记，不能把多个功能入口概括为“其他”；重复数据实例只有数据对象不同且结构和直接效果相同时才选一个代表；参数选项属于同一 Operation，只记录值域，不逐项创建任务。无法确定就保留独立候选。普通展开只补内容或原有操作时保留原Region；显露服务该对象、共同显隐的独立任务上下文才增结果Region；内联时归入可见来源容器，触发控件保留原归属。
- 同质数据的代表也必须是一个具体可见成员，name/target说明所选实例或明确位置；不要把“所有同类按钮”写成一个Element。该成员内部不同功能的控件仍分开；其他同类成员和值域可记入Region说明，无须逐个建任务。功能概括放在Region memory，不用集合名称替代当前物理owner。
- 每条Operation填parameter_status=unknown|none|observed及parameter_summary。none无参数；observed仅表示形式已见，不代表选项完整；unknown形式未知。parameter_summary写形式、已确认选项和未知范围；当次取值、勾选和可用性写Element.observation，不清楚写不确定，框架附截图证据。后续只补变化；不同功能的复选框分别登记。
- 为补未知功能、条件或指令所需值域才展开选择器；已知值域不重开，打开后记录实际选项，不逐个应用。可能显露子配置或改变子控件可用性的模式/总开关用explore，做安全可逆对照，记录可用性前置条件并恢复临时值。禁用不等于消失，互斥/依赖的推测与实测分开写memory，已确认关系不重复试验。作用明确且无子配置未知项的普通复选框或文本框用record，不为证明能勾选/输入而探索。未查范围保留未知，普通数值不穷举边界/组合。
- 仅在确需两个代表验证同类关系时用representative_probe，先登记成员，再在首个动作前声明完整成员、两个代表和稳定operation_ref。普通功能调查不强制代表探针，不伪造结果。
- """ + HANDLING_GUIDANCE + """
- 范围允许的安全入口通向未知结构时explore；普通已知取值record。不因先交清单、action=null把未知入口都设成record。
- 探索范围优先于待办派发；只为必要结构比较或恢复进入范围外页面，不探索其内部参数。范围内未知功能用explore，已掌握的用record；“已知”依据图和功能证据，不靠名称推断，不重复点击选中入口。
- 已登记但尚未执行的操作若需要修正探索决策，在增量 page_report 中复制当前 owner 和稳定 operation_ref，明确 handling 与原因；只在 reason 说“跳过”不会更新待办。已执行的结果不靠重报 handling 改写。

4. 调查滚动与动作：
- 截断、滚动条或连续延伸只说明可调查，不要求滚到底。survey_complete只管当前前景；未开子菜单/其他页另由explore待办负责。同质数据列表的结构、代表控件和操作已明确即可true；有限参数列表仍有未见选项或存在未知功能时继续查看，coverage_note记实际范围。无滚动证据的完整静态视图直接true，不虚构scroll。direction为查看内容方向：down下方、up上方、left左侧、right右侧。任何scroll都须填已登记且可见的region_ref。Android的point_1000是手势起点，amount是像素距离；起点须在Region内避开悬浮控件及固定导航。新内容只补报。
- back的真实primitive：桌面为Esc，Android为系统返回；它不是截图中的左上返回按钮。要点击可见返回控件，使用click及当前绑定owner/point，不能按名称假设两者等价；返回后仍核对实际结果。
- 每轮最多一个动作。click、double_click、right_click、long_press、input_text、hover 和 scroll 都必须填写当前截图中的 point_1000，只有 back/wait 可为 null。功能动作 owner_ref使用当前卡片的 Element/Region；非滚动恢复可为空。action 不输出 Operation/Task 编号或动作 purpose；representative_probe例外复制稳定 co。目标不可见时逐步导航或恢复，不用旧坐标；前景接管输入时不能点击背景，即使控件未被几何遮挡。
- 提交page_report的同一轮不执行click，不能用空owner_ref点击刚报告的功能。收到缺少owner的反馈后，优先用next_operation_ref改选当前可见、已绑定且可执行的其他待办；原候选保留，不把未执行的提议当作失败。单独处理干扰的恢复点击使用page_report=null。
- Android当前输入只可靠支持ASCII；代表文本优先短ASCII。投递失败保持 no_effect/retry，不能把部分输入报完成。系统键盘或输入法可见时不得执行 scroll；先Back隐藏并取得fresh截图。

5. 动作结算与功能总结：
- Region效果必须与真实应用动作有因果关系。操作前已出现、并非应用交互触发的系统通知/环境浮层不能登记为应用Region或写入应用region_effects；悬停显露通知关闭按钮、清理这种通知只能在reason中记作环境恢复，不能把后方应用Region谎报updated或编造空引用disappeared。应用动作实际触发的可复现反馈须有真实前后证据，并按原归属/Region合同核对。
- 本轮提交合同要求结算时，原样回填attempt_ref，从实际动作卡复制owner_ref/action；编辑阶段由框架保留回执候选，不重新填写。element_actions/region_actions只列before/after直接证明且与真实primitive相同的已登记动作。completed=true表示该owner的直接可见效果成立，不表示批准Task；投递或鼠标落点不等于成功，无结果证据必须false。错误落点只结算实际命中的已登记owner；新owner先登记。
- owner_ref为空的恢复不完成Operation，完成数组必须为空；scroll必须按Region和方向结算。scroll 的 completed=true 必须由内容位移、新内容、滚动条变化或到达边界支持；前后无位移填false。仍有截断或滚动条只能支持下一次 bounded retry，不能把未来重试的理由写成本次 success。
- 描述操作功能时，在target、reason或memory中选最能说明作用的已观察结果：可能是区块显露、消失或内容更新，不要求所有伴随变化都相同。region_effects仍如实报告因果。一个功能入口可在不同条件下到达不同页面/区块形态，不为复用入口强行合并它们。图中保留的来源连接仅供理解入口，不自动继承全部显隐结果。
- 当前目标已显示且无需改变时，不重复点击当前入口；当前共享区块的另一个入口虽然在本地标为recorded，若同一稳定功能仍有未完成待办，则可使用框架给出的当前owner继续探索。recorded不等于控件被禁用，完成仍须真实结果。
- region_effects只列本次与功能相关、需要记录的区块变化：appeared/disappeared/updated，每项判断cause=action/external/uncertain；不能仅因变化发生在点击后就归因给按钮。保持不变的区块和无关变化可以省略；干扰判断或交互时在已有reason中简述，仍遵守前景恢复规则。可能相关但因果不清用uncertain。已知区块用region_ref且report_index=null；本轮清单中的区块可用page_report.regions的从0开始序号report_index且region_ref=""。效果引用须与本轮最终区块清单对齐：若拆为多个区块且各自变化都需记录，分别报告，不能以其中一项代指全部。只换数据对象/列表内容而组件未变用updated，不为普通参数值建新Region。没有需报告的变化填[]，解释沿用previous_action.reason，无需逐项解释所有省略。
- memory只保留会改变后续选择的认识：适用情境、能复用的规律或例外、下次应怎样探索。单纯复述本次点击或当前数值放在reason/summary，不当成新经验。对照旧memory与本轮事实，只有新认识或修正才更新，保留仍有效的结论；证据不足写成暂定判断。经验类型不预设，也不要求每轮输出。
- 当前任务由框架维护。next_operation_ref仅在主动切换到另一个当前可见的开放待办时填写稳定co；继续当前任务、滚动寻找入口或补充清点时留空，用action.owner_ref指定实际动作对象。已记录的操作不一定有开放待办。切换理由放在strategy；先结算上一动作，普通清点未完成时可继续调查但不切换任务。
- function_info可以更新动作前的来源 Region，也可以更新动作后重新可见的已知 Region；新出现的 Region在本轮清点时填写说明。内容简要写能做什么、参数值域、代表结果、新结构和缺失事实。笔记不授权新操作或替代证据。
- representative_same_kind_required=true且最终代表completed=true时，根据两次截图填写 representative_same_kind=true/false，并用function_info说明机制。true只把两个代表记为verified，其余同类binding记为未执行的代表覆盖；false不批量结算。其他轮填null。
- owner completed=true时，参数未确认或本次补齐了该操作的选项范围，就填parameter_info；无新参数证据填null，completed=false 时 parameter_info=null，不改变原参数状态。无参数按钮不能用结果表单的参数覆盖。
- 按“本轮提交合同”的唯一阶段提交；纠正卡说明当前错误，不能重放真实GUI动作。缓存编辑仅改候选，退出编辑后才在下一轮重判位置和回执；暂存不等于审核通过。

不同功能模式不批量完成；不要把会解锁后续核心操作的安全前置输入仅标为 record。不要点击当前截图中不存在、只在旧截图出现过的目标。不以应用名、按钮文字或历史位置制定例外。
"""


RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "app_scope": {"type": "string", "enum": [
            "target_app", "external_app", "uncertain"]},
        "strategy": {"type": "string", "minLength": 1, "maxLength": 240},
        "screen": {"anyOf": [{
            "type": "object",
            "properties": {
                "identity": {"type": "string", "enum": [
                    "new_page", "new_state", "known", "uncertain"]},
                "page_ref": {"type": "string"},
                "page_name": {"type": "string", "minLength": 1},
                "page_summary": {"type": "string", "minLength": 1},
                "state_ref": {"type": "string"},
                "state_name": {"type": "string", "minLength": 1},
                "state_summary": {"type": "string", "minLength": 1},
            },
            "required": [
                "identity", "page_ref", "page_name", "page_summary",
                "state_ref", "state_name", "state_summary",
            ],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "previous_action": {"anyOf": [{
            "type": "object",
            "properties": {
                "attempt_ref": {"type": "string", "minLength": 1},
                "element_actions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "element_ref": {"type": "string", "minLength": 1},
                        "action": {"type": "string", "enum": [
                            "click", "double_click", "right_click",
                            "long_press", "input_text", "hover"]},
                        "completed": {"type": "boolean"},
                    },
                    "required": ["element_ref", "action", "completed"],
                    "additionalProperties": False,
                }},
                "region_actions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "region_ref": {"type": "string", "minLength": 1},
                        "action": {"type": "string", "enum": ["scroll"]},
                        "direction": {"type": "string", "enum": [
                            "up", "down", "left", "right"]},
                        "completed": {"type": "boolean"},
                    },
                    "required": [
                        "region_ref", "action", "direction", "completed"],
                    "additionalProperties": False,
                }},
                "function_info": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "region_ref": {"type": "string", "minLength": 1},
                        "memory": {"type": "string", "minLength": 1},
                    },
                    "required": ["region_ref", "memory"],
                    "additionalProperties": False,
                }},
                "region_effects": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "region_ref": {"type": "string"},
                        "report_index": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
                        "change": {"type": "string", "enum": ["appeared", "disappeared", "updated"]},
                        "cause": {"type": "string", "enum": ["action", "external", "uncertain"]},
                    },
                    "required": ["region_ref", "report_index", "change", "cause"],
                    "additionalProperties": False,
                }},
                "parameter_info": {"anyOf": [{
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": [
                            "none", "observed"]},
                        "summary": {"type": "string", "minLength": 1},
                    },
                    "required": ["status", "summary"],
                    "additionalProperties": False,
                }, {"type": "null"}]},
                "representative_same_kind": {"anyOf": [
                    {"type": "boolean"}, {"type": "null"}]},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": [
                "attempt_ref", "element_actions", "region_actions",
                "function_info", "parameter_info", "representative_same_kind", "region_effects",
                "reason",
            ],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "representative_probe": {"anyOf": [{
            "type": "object",
            "properties": {
                "operation_ref": {"type": "string", "minLength": 1},
                "goal": {"type": "string", "minLength": 1},
                "member_owner_refs": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 2,
                    "maxItems": 32,
                },
                "representative_owner_refs": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": [
                "operation_ref", "goal", "member_owner_refs",
                "representative_owner_refs"],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "page_report": {"anyOf": [{
            "type": "object",
            "properties": {
                "regions": {"type": "array", "description": "先确定当前接管输入的完整容器，再列其内部功能组。若拆出多个子组，须保留可见父容器并填写parent_ref；父区elements可为空。不要将后方窗口的标题或按钮混入前景。", "items": {
                    "type": "object",
                    "properties": {
                        "region_ref": {"type": "string"},
                        "parent_ref": {"anyOf": [
                            {"type": "string"}, {"type": "integer", "minimum": 0},
                            {"type": "null"}]},
                        "name": {"type": "string", "minLength": 1},
                        "summary": {"type": "string", "minLength": 1},
                        "memory": {"type": "string", "minLength": 1},
                        "elements": {"type": "array", "description": "只列有交互依据的具体控件。输出前移除纯标签、图标标识、读数等静态条目，内容归Region summary；不能为通过校验编造click。独立配置选项和导航入口不能用数据代表法合并。逐项核对是否属于当前前景及直接父区。", "items": {
                            "type": "object",
                            "properties": {
                                "element_ref": {"type": "string"},
                                "observation": {"type": "string"},
                                "name": {"type": "string", "minLength": 1},
                                "operations": {"type": "array", "description": CONTROL_ACTION_GUIDANCE, "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string", "enum": [
                                            "click", "double_click", "right_click",
                                            "long_press", "input_text", "hover"]},
                                        "target": {"type": "string", "minLength": 1},
                                        "handling": {"type": "string", "enum": [
                                            "explore", "record", "defer"]},
                                        "reason": {"type": "string", "minLength": 1},
                                        "operation_ref": {"type": "string"},
                                        "parameter_status": {"type": "string", "enum": [
                                            "unknown", "none", "observed"]},
                                        "parameter_summary": {"type": "string", "minLength": 1},
                                    },
                                    "required": [
                                        "action", "target", "handling", "reason", "operation_ref",
                                        "parameter_status", "parameter_summary"],
                                    "additionalProperties": False,
                                }},
                            },
                            "required": ["element_ref", "name", "observation", "operations"],
                            "additionalProperties": False,
                        }},
                        "region_operations": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "enum": ["scroll"]},
                                "direction": {"type": "string", "enum": [
                                    "up", "down", "left", "right"]},
                                "target": {"type": "string", "minLength": 1},
                                "handling": {"type": "string", "enum": [
                                    "explore", "record", "defer"]},
                                "reason": {"type": "string", "minLength": 1},
                                "operation_ref": {"type": "string"},
                                "parameter_status": {"type": "string", "enum": [
                                    "unknown", "none", "observed"]},
                                "parameter_summary": {"type": "string", "minLength": 1},
                            },
                            "required": [
                                "action", "direction", "target", "handling", "reason", "operation_ref",
                                "parameter_status", "parameter_summary"],
                            "additionalProperties": False,
                        }},
                    },
                    "required": [
                        "region_ref", "parent_ref", "name", "summary", "memory", "elements",
                        "region_operations"],
                    "additionalProperties": False,
                }},
                "survey_complete": {"type": "boolean", "description": "当前前景本身是否已清点完整；未展开的子菜单或其他页面属于后续explore任务，不阻止当前清点完成。"},
                "coverage_note": {"type": "string", "minLength": 1},
            },
            "required": ["regions", "survey_complete", "coverage_note"],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "page_report_edits": {"anyOf": [{"type": "array", "minItems": 1, "maxItems": 64,
            "description": "普通轮null；仅收到清单增量纠正卡时优先使用。按JSON Pointer路径对缓存page_report做add/replace/remove，未改内容由框架保留。此模式screen/previous_action/page_report/action全null，原位置和回执由框架保留；不查历史或切任务。路径如/regions/1/elements/-追加控件，/regions/1/parent_ref修改父引用。数组删除从大到小；新增区块追加到/regions/-，不要替换整个regions数组。新增Element仍须提供完整name/element_ref/observation/operations字段；新增或替换每个operation必须同时提供action/target/handling/reason/operation_ref/parameter_status/parameter_summary，不能只写action和target。替换整项会覆盖原对象的未列字段；只改单字段时使用字段路径。",
            "items": {"type": "object", "properties": {
                "op": {"type": "string", "enum": ["add", "replace", "remove"]},
                "path": {"type": "string"}, "value_json": {"type": ["string", "null"], "description": "add/replace的值编码为JSON字符串，可表示对象、数组、字符串、数字或布尔值；remove填null。"}},
                "required": ["op", "path", "value_json"], "additionalProperties": False}}, {"type": "null"}]},
        "action": {"anyOf": [{
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": [
                    "click", "double_click", "right_click", "long_press",
                    "input_text", "hover", "scroll", "back", "wait"]},
                "owner_ref": {"type": "string", "description": "当前Element/Region；仅有当前动作候选且视觉确认匹配时可填@current（owner_confirmation.v1），由框架绑定。不匹配不能使用。"},
                "target": {"type": "string"},
                "point_1000": {"anyOf": [{
                    "type": "array", "items": {"type": "number", "minimum": 0,
                    "maximum": 1000}, "minItems": 2, "maxItems": 2,
                }, {"type": "null"}]},
                "text": {"anyOf": [
                    {"type": "string", "maxLength": 200}, {"type": "null"}]},
                "direction": {"anyOf": [
                    {"type": "string"}, {"type": "null"}]},
                "amount": {"anyOf": [
                    {"type": "integer", "minimum": 1, "maximum": 1000},
                    {"type": "null"}]},
            },
            "required": [
                "kind", "owner_ref", "target", "point_1000", "text",
                "direction", "amount",
            ],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "region_refinement": REFINEMENT_SCHEMA,
        "context_query": {"anyOf": [{"type": "string", "maxLength": 200}, {
            "type": "object", "properties": {key: {"type": "string"} for key in
                ("label", "function", "region", "action", "state_ref", "region_ref")},
            "required": ["label", "function", "region", "action", "state_ref", "region_ref"],
            "additionalProperties": False}],
            "description": "普通轮空字符串。局部候选不能解释当前图时，按当前可见控件补查：label为标签，function为功能，region为区块描述；明确的action/state_ref/region_ref作筛选，不确定留空，也可用短字符串。只读：previous_action/page_report/action/region_refinement=null，next_operation_ref为空，screen可null。每观察最多两次不同查询；未召回不等于新页面。"},
        "next_operation_ref": {"type": "string"},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "app_scope", "strategy", "screen", "previous_action",
        "representative_probe", "page_report", "page_report_edits", "action", "next_operation_ref", "region_refinement", "context_query", "reason",
    ],
    "additionalProperties": False,
}


def schema_instruction(schema: Dict[str, Any]) -> str:
    return (
        "\n只输出一个符合下列 JSON Schema 的对象，不要 Markdown 或额外文字：\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )


def submission_schema(contract):
    if not contract:
        return RESPONSE_SCHEMA
    schema = deepcopy(RESPONSE_SCHEMA)
    if contract.get('phase') != 'inventory_edits':
        schema['properties']['page_report_edits'] = {'type': 'null'}
        return schema
    schema['properties']['app_scope'] = {'type': 'string', 'enum': ['target_app']}
    for field in contract['null_fields']:
        schema['properties'][field] = {'type': 'null'}
    for field in contract['empty_fields']:
        if field in schema['properties']:
            schema['properties'][field] = {'type': 'string', 'enum': ['']}
    return schema


def build_user_prompt(context: Dict[str, Any], *, correction: str = "") -> str:
    payload = dict(context)
    if correction:
        if isinstance(payload.get("状态栏"), str):
            payload["状态栏"] = "\n".join(
                line for line in payload["状态栏"].splitlines()
                if not line.startswith("- 当前思路："))
        payload["上轮格式或合同错误"] = correction
    return (
        "图片顺序已在输入中说明。请依据最新截图和以下框架记录继续当前探索。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


__all__ = [
    "MAIN_SYSTEM_PROMPT", "RESPONSE_SCHEMA", "build_user_prompt",
    "schema_instruction",
]
