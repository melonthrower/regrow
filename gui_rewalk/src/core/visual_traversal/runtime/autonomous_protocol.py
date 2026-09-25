"""Qwen task prompts and tool catalog for autonomous exploration."""

from __future__ import annotations

from typing import Any, Dict, List

from .autonomous_map import (
    MAP_TOOL_NAMES,
    NaturalExplorationMap,
    ToolEvidence,
)

TOOL_NAMES = MAP_TOOL_NAMES | {
    "handle_interruption", "click", "input_text", "hover", "scroll",
    "navigate", "gesture", "reuse_entry_result", "review_entry_record",
    "complete_region_probe", "defer_current_task", "report_app_scope",
}

TOOL_CATALOG = [
    {
        "name": "report_app_scope",
        "description": (
            "仅当框架说明系统无法确认当前窗口归属时使用。根据当前完整截图，以及附带时的最近一张"
            "已确认目标应用截图，判断当前前景仍是目标应用、是目标应用上方的临时遮挡、已经进入其他"
            "应用，或视觉证据仍不足。必须依据可见的应用内容、窗口结构或遮挡关系判断，不能把系统的"
            "未知结果本身当成离开应用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "classification": {
                    "type": "string",
                    "enum": [
                        "target_app", "target_app_obstructed",
                        "external_app", "uncertain",
                    ],
                },
            },
            "required": ["classification"],
            "additionalProperties": False,
        },
        "effect": "app_scope_observation",
        "returns": "记录本轮视觉归属判断；不登记页面、区域、入口或动作边",
        "requires_review": False,
        "executes_gui": False,
    },
    {
        "name": "page_identity",
        "description": (
            "当当前最前景界面的 Page 或 material Variant 不能由已知边和视觉证据可靠定位时，调用独立 "
            "specialist 与候选 Page/Variant 代表截图比较；自然地图为空时也用它登记清晰根界面。"
            "临时弹窗或提示不单独分类：只要仍有足够页面证据就继续判断身份，只有遮挡使身份确实不可判断"
            "时才返回 uncertain。同一已知 Page 上提出新 Variant 时必须调用；reason 说明具体视觉争议。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "suspected_pages": {
                    "type": "array", "items": {"type": "string"},
                },
                "proposed_new_name": {"type": "string"},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["suspected_pages", "proposed_new_name", "reason"],
            "additionalProperties": False,
        },
        "effect": "analysis_proposal",
        "returns": (
            "known/new 会形成绑定当前截图的待复核提案；uncertain 只返回证据，不登记页面"
        ),
        "requires_review": "known_or_new_only",
        "executes_gui": False,
    },
    {
        "name": "report_record_error",
        "description": (
            "当截图与框架账本冲突时上报具体错误，例如页面误合并、Region 不准、入口被错标已探索。"
            "争议默认只保存，不直接删除或覆盖已有证据。页面身份争议会在同一次调用中触发独立页面复核；"
            "specialist 的判断和理由会以自然语言返回，known/new 结果仍需你下一轮审核后才会写入地图。"
            "当前精确 explore_entry 若从最新截图可确认账本语义错误，或已经回到来源状态却仍找不到目标，"
            "可令 kind=entry、subject=当前 entry_id，并分别填写 problem_type=semantic_mismatch 或 "
            "target_not_found；后者只在需要时比较首次发现截图与当前截图。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": [
                    "page_identity", "region", "entry",
                    "coverage", "navigation",
                ]},
                "subject": {"type": "string"},
                "observed_problem": {"type": "string"},
                "problem_type": {
                    "type": "string",
                    "enum": ["semantic_mismatch", "target_not_found"],
                },
            },
            "required": ["kind", "subject", "observed_problem"],
            "additionalProperties": False,
        },
        "effect": "ledger_dispute",
        "returns": "说明争议是否已记录；Page 身份或精确 Entry 争议还会返回独立 specialist 的判断和理由",
        "requires_review": "page_identity_or_exact_entry_specialist",
        "executes_gui": False,
    },
    {
        "name": "review_entry_record",
        "description": (
            "仅在本轮目录动态提供时，读取最近一次同截图 Entry Reviewer 的完整临时延期记录，"
            "或纠正其中明确不应作为入口的精确 (Region, operation, target)。correct 只能引用该记录现有的 "
            "deferred_entries；它会清除相应临时延期，但不能删除正式入口、修改 Page/Region/边，"
            "也不能把候选改为保留。若仍需新视觉证据则不要纠正，继续取得新截图后复核。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string", "enum": ["inspect", "correct"],
                },
                "drop_deferred_entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "region_name": {"type": "string"},
                            "entry_operation": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": [
                            "region_name", "entry_operation", "target"],
                        "additionalProperties": False,
                    },
                },
                "reason": {"type": "string"},
            },
            "required": ["operation", "drop_deferred_entries", "reason"],
            "additionalProperties": False,
        },
        "effect": "provisional_entry_review_correction",
        "returns": (
            "当前 Reviewer 临时延期记录、已清除项、仍延期项和未改变的正式账本边界"
        ),
        "requires_review": False,
        "executes_gui": False,
    },
    {
        "name": "handle_interruption",
        "description": (
            "仅当疑似临时前景层确实遮挡、阻止或使当前阶段目标无法可靠判断时调用独立干扰处理 "
            "Agent；不影响当前目标时直接忽略。框架自动附上最新完整截图和当前任务，specialist "
            "会在 ignore/wait/hover/click/back/unresolved 中选择一种最小策略。hover 后先重新截图；"
            "click 仍须独立 Click Reviewer 复核，specialist 不能批准自己的点击。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "suspected_surface": {
                    "type": "string",
                    "description": "截图中实际可见的疑似干扰表面。",
                },
                "obstruction_reason": {
                    "type": "string",
                    "description": "它如何影响当前阶段精确目标的视觉原因。",
                },
            },
            "required": ["suspected_surface", "obstruction_reason"],
            "additionalProperties": False,
        },
        "effect": "bounded_interruption_strategy",
        "returns": "specialist 选择的最小策略，以及执行后需观察的真实结果",
        "requires_review": "click_strategy_only",
        "executes_gui": "strategy_dependent",
    },
    {
        "name": "reuse_entry_result",
        "description": (
            "仅在当前 explore_entry 任务提供 equivalent_entry_candidates 时使用："
            "这些候选来自 Agent 已显式合并的共享 Region，不是框架按名称猜出的相似按钮。"
            "若当前入口与候选的可见控件角色、目标页面和最近真实结果一致，且当前截图没有显示"
            "来源栈、状态或上下文会改变结果，应优先引用两个精确 entry_id 复用结果，不执行 GUI 动作。"
            "仅位于不同 Page 不是重新点击的理由；Back、关闭、状态切换等有具体上下文依赖证据的控件"
            "才直接探索，并在本轮顶层 reason 中说明该证据。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "representative_entry_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": [
                "entry_id", "representative_entry_id", "reason",
            ],
            "additionalProperties": False,
        },
        "effect": "entry_equivalence_proposal",
        "returns": "说明当前入口是否已按显式语义判断建立 infer 关系",
        "requires_review": "framework_binding_check",
        "executes_gui": False,
    },
    {
        "name": "complete_region_probe",
        "description": (
            "Use only for the assigned probe_region task after checking the "
            "latest screenshot, the Region's known capabilities, and its visible "
            "internal controls. It means no additional safe, user-visible core "
            "operation remains to probe in this Region. Give the concrete visual "
            "reason. One representative success is sufficient when it accounts "
            "for the Region's only remaining visible core operation; different "
            "values on the same control are homogeneous examples, not new "
            "operations. Do not use it merely because another distinct visible "
            "operation is inconvenient to locate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "effect": "region_probe_coverage_decision",
        "returns": (
            "Natural-language confirmation of the exact Page and Region whose "
            "capability probing was closed, or the concrete binding error."
        ),
        "requires_review": False,
        "executes_gui": False,
    },
    {
        "name": "finish_exploration",
        "description": (
            "只有在已检查当前页、其他主入口、未恢复状态和已知未覆盖项后才提出结束。"
            "这是完成提议，不是强制终止；框架会返回仍缺少的事实证据。若某个已派发入口经多次真实尝试后"
            "在执行精确目标前就被证明无法到达或无法定位，也可在此提交证据并填写它的精确 entry_id；"
            "框架只关闭该明确绑定的任务。Reviewer 已确认并执行的点击若没有可见效果，不属于不可达："
            "在 previous_action.reason 解释原因即可，框架会保存原因并结束本轮该入口任务。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "unreachable_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "page_name": {"type": "string", "minLength": 1},
                            "entry_id": {
                                "type": "string", "minLength": 1,
                                "description": (
                                    "入口任务必须填写框架派发的精确 entry_id；"
                                    "页面或 Region 级证据填空字符串。"
                                ),
                            },
                            "subject": {"type": "string", "minLength": 1},
                            "evidence": {"type": "string", "minLength": 1},
                        },
                        "required": [
                            "page_name", "entry_id", "subject", "evidence",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["unreachable_evidence"],
            "additionalProperties": False,
        },
        "effect": "completion_proposal",
        "returns": "finish_accepted，或带事实缺口清单的 finish_rejected",
        "requires_review": "framework_gap_check",
        "executes_gui": False,
    },
]


PAGE_IDENTITY_SPECIALIST_PROMPT = """\
你是独立 Page Identity specialist，只判断当前完整截图属于哪个目标应用 Page 及其 material Variant，不规划动作，
也不负责识别、分类或关闭临时弹窗。框架会提供当前完整截图、主 Agent 怀疑的已登记 Page、各 Variant 的代表
完整截图和可见谓词、到达来源/入口/邻接关系，以及上一次否决纠正。到达上下文只用于缩小候选，不能凌驾于
当前截图、候选截图和稳定语义锚点。

判别原则：
- Page 是可跨状态重认的稳定功能位置，由选中的主导航、页面标题、主要内容组织等语义锚点确定。打开同一功能
  内的对话框、输入查询、出现结果或创建/删除对象，不应仅因此另建 Page。
- Variant 是同一 Page 内会实质改变可执行操作、前置条件、可见结果或恢复路径的可操作状态。应用内对话框、
  搜索结果、已创建对象等只有在仍由同一 Page 锚定且确实影响后续规划时才拆 Variant。
- 临时弹窗、Toast、横幅或局部遮挡不是独立身份结果。只要页面标题、导航、稳定布局或其他视觉证据仍足以
  判断，就忽略遮挡；hover、焦点、滚动位置、时间或被动动态数据变化也不拆 Variant。遮挡使 Page 或 Variant
  确实无法判断时才返回 uncertain。
- known Page/Variant 必须由已检查候选和当前最前景操作界面共同支持，并复用已登记规范名；共同背景、相似颜色、
  动态内容或名称相似不能单独证明身份。new Variant 只能在 Page 已知但现有 Variant 均被可见 material 事实排除时提出。
- 若 arrival_context 提供 recent_action，它是最近一次真实 GUI 动作的自然语言上下文。最近动作是同页 scroll，
  且主内容和交互组织连续时，粘性顶栏或视口位移不能单独支持新 Page/Variant。
- 当 registered_page_count=0 时，清晰的目标应用根界面返回 new Page + new Variant。其余情况下，new Page
  只在相关 Page 候选均被稳定功能锚点排除后返回；缺少证据时返回 uncertain。
- visible_predicates 只列当前截图中用于重认该 material Variant 的简短事实。surface_kind 是观察事实，不是身份键。
  reason 必须同时说明 Page 与 Variant 裁决依据，支持证据和冲突证据分开列出。

只返回结构化对象：status=known|new|uncertain；page_name/matched_page_name；surface_kind；
variant_name；variant_identity=known|new|uncertain；visible_predicates[]；summary；supporting_evidence[]；
conflicting_evidence[]；checked_candidates[]；reason。known 只能引用本次提供的已登记候选。
"""


PAGE_IDENTITY_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [
            "known", "new", "uncertain",
        ]},
        "page_name": {"type": "string"},
        "matched_page_name": {"type": "string"},
        "variant_name": {"type": "string"},
        "variant_identity": {"type": "string", "enum": [
            "known", "new", "uncertain",
        ]},
        "visible_predicates": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Current visible facts that distinguish this material Variant."
            ),
        },
        "surface_kind": {"type": "string", "enum": [
            "page", "dialog", "menu", "drawer", "other",
        ]},
        "summary": {"type": "string"},
        "supporting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "conflicting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "checked_candidates": {
            "type": "array", "items": {"type": "string"},
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "status", "page_name", "matched_page_name", "surface_kind",
        "variant_name", "variant_identity", "visible_predicates",
        "summary", "supporting_evidence", "conflicting_evidence",
        "checked_candidates", "reason",
    ],
    "additionalProperties": False,
}


PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT = """\
你是独立页面身份复核器。只判断当前完整截图属于哪个稳定功能页面，不判断页面状态版本，也不规划动作。

同一页面必须保持相同的主要功能界面和导航上下文。滚动位置、普通状态值、动态内容、局部展开或焦点变化都不会单独产生新页面。临时弹窗、提示或遮挡不是页面；如果遮挡导致标题、导航、主要容器等页面证据不足，返回 uncertain。

known 只能引用本次提供的候选页面；只有当前截图中的稳定功能锚点明确排除全部候选时才返回 new。reason 必须点名截图中的标题、选中导航、主要内容容器或其他独特证据，并说明它支持哪个候选或排除了哪些候选；不能只写“布局相同”或“结构相似”。
"""


PAGE_ONLY_IDENTITY_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [
            "known", "new", "uncertain",
        ]},
        "page_name": {"type": "string"},
        "matched_page_name": {"type": "string"},
        "surface_kind": {"type": "string", "enum": [
            "page", "dialog", "menu", "drawer", "other",
        ]},
        "summary": {"type": "string"},
        "supporting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "conflicting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "checked_candidates": {
            "type": "array", "items": {"type": "string"},
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "status", "page_name", "matched_page_name", "surface_kind",
        "summary", "supporting_evidence", "conflicting_evidence",
        "checked_candidates", "reason",
    ],
    "additionalProperties": False,
}


VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT = """\
当前页面已经确认。你是独立页面状态版本复核器，只判断当前完整截图是否属于该页面已有的实质状态版本，不重新判断页面，也不规划动作。

只有当前状态会实质改变后续可执行操作、操作前置条件、规划所需的可见结果或恢复路径时，才建立新的页面状态版本。滚动、悬停、焦点、时间、动画、被动数据、普通数值变化和临时遮挡都不是新状态版本。

known 只能引用本次提供的候选状态版本；只有当前截图中的实质可操作状态明确排除全部候选时才返回 new。reason 必须说明具体哪些可执行操作、前置条件、可见结果或恢复路径发生了差异；证据不足返回 uncertain。
"""


VARIANT_ONLY_IDENTITY_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "variant_name": {"type": "string"},
        "variant_identity": {"type": "string", "enum": [
            "known", "new", "uncertain",
        ]},
        "visible_predicates": {
            "type": "array", "items": {"type": "string"},
        },
        "supporting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "conflicting_evidence": {
            "type": "array", "items": {"type": "string"},
        },
        "checked_candidates": {
            "type": "array", "items": {"type": "string"},
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "variant_name", "variant_identity", "visible_predicates",
        "supporting_evidence", "conflicting_evidence",
        "checked_candidates", "reason",
    ],
    "additionalProperties": False,
}


PROTOCOL_PROMPT = """\
只根据最新完整截图和框架事实工作。普通阶段用 screen.name 报告稳定功能位置的 Page 规范名，用 screen.variant 报告该 Page 内会实质改变
可执行操作、前置条件、可见结果或恢复路径的 material Variant。应用内对话框、搜索结果或创建对象可形成 Variant，
但滚动、hover、焦点、时间、被动数据变化、临时遮挡和普通分区不会。known 必须沿用已登记 Page/Variant 名；new 只在
当前可见事实排除已有候选时使用，并给出用于重认的 visible_predicates。若 pending_action 被判断为 no_visible_change，
继续报告其来源 Page 和 Variant；如果认为原绑定错误，报告 uncertain 并调用 page_identity 或上报身份账本争议，不能
直接改报另一个 known/new。动作前图只用于 previous_action，历史身份、Region、入口和路线只作语义线索，旧截图坐标不能复用。

每轮回复都必须填写一个非空的顶层 reason：用简短自然语言说明本轮页面判断、当前阶段结论以及为什么选择该工具或不执行动作。
它不是重复 previous_action.reason；后者只解释上一真实动作的结果。有 equivalent_entry_candidates 时，若选择直接动作而非
reuse_entry_result，顶层 reason 必须指出当前截图中具体的来源栈、状态或上下文依赖证据，不能只说“再验证一次更安全”。

当前 task 是本轮唯一主任务，current stage 是本轮唯一需要推进的阶段。先完成阶段说明中的目标；阶段是否完成由框架根据
页面、Region、入口和真实动作证据确认。完成后令 action=null，框架会在下一轮提供新阶段和所需上下文，不要预先执行
下一阶段动作。若截图表明阶段或账本不正确，可以报告身份或账本错误，不要为满足阶段名称而猜测。你决定阶段内的路线与
工具；框架执行 GUI、保存证据、维护账本，并在调用不适用时说明什么未执行、为什么以及如何修正。不要原样重复同一失败调用。

回复只填写当前存在的事实：有待结算 GUI 动作时才填写 previous_action；有待审 Page Identity 提案时才填写
previous_tool_review；有当前页结构增量时才填写 page_update。
Page Identity specialist 的 known/new 结果必须经 previous_tool_review 接受后才写账本。

previous_action 只结算所附动作前图与最新图之间的最后一个真实 GUI 动作。点击目标由 pending_action 和 Reviewer 固定，
你只判断其可见结果，不能根据落地页把它改成另一个按钮；结果不满足派发入口时 matches_intent=false，即使画面已经变化。
当前任务是在发现未知功能，不要根据按钮名称预测尚未登记的目的地；Reviewer 确认目标后出现连贯的即时跳转，
就是该目标的真实结果，即使另一个入口也到同一页面，仍应报告 matches_intent=true。
控件是否可用可能取决于当前环境、页面状态或尚未满足的前置条件；
当真实结果与预期不一致时，结合动作前后图在 reason 中说明最可能的原因和可见依据，不要只重复 outcome，也不要默认是
页面账本错误。failure_kind 是你是否结束当前入口派发的明确裁决，不由框架根据像素变化替你决定。Reviewer 已确认
精确目标和点位、真实点击后没有出现入口结果，且你判断本次结果已经足以结束该入口时，failure_kind 只判断两类原因：
temporarily_unavailable 表示它是真控件但当前状态、前置条件或环境使其不可用；not_interactive 表示登记目标其实是
静态内容而不是功能控件。no_effect 是框架记录的动作事实，unreachable 只用于尚未执行目标时的导航/定位问题，二者都
不是 failure_kind 选项。仍需继续当前入口、需要在新状态重试或证据不足时令 failure_kind=null，并在 reason 中说明依据；
框架会保留入口待办，并执行你本轮选择的下一动作。
若 pending_action 提供 same_region_pending_entries，且这次入口动作真实产生了符合意图的区块内状态变化，
可以在 business_effect.same_operation_entry_ids 中列出其中共享同一交互模板、前置状态、用户意图和可见效果，
且区别仅为内容实例或参数值的精确入口编号，并用 same_operation_reason 说明共同模板和具体差异。入口身份、结构角色、
前置状态、目标页面或可见效果任一不同都不要包含；
当前已选项导致的无变化动作也不能作为覆盖依据。框架只把实际执行入口记为真实验证，列表中的入口记为同质推断覆盖。
若前后图已经发生可见变化，但变化只来自前景菜单、弹层或其他临时表面消失，而派发目标的结果尚未出现，报告
outcome=changed、matches_intent=false、failure_kind=null；这不是目标控件无效果。先结算这个真实变化，再由你根据
最新无遮挡截图决定是否继续尝试当前入口。

不要执行不可逆、外部提交、敏感或明显危险操作。临时干扰没有遮挡、阻止或使当前阶段目标无法可靠判断时，
忽略它并继续当前探索，不要为了清理界面而主动关闭。确实影响当前阶段时调用 handle_interruption，把具体的
ignore/wait/hover/click/back 恢复策略交给独立 specialist；不要直接猜测关闭控件、悬停位置或借用其他界面的
相似控件，也不要把干扰登记为应用功能。
若框架事实出现 last_scroll_result，其中 container_hint 只是你上次描述的滚动容器，frame_changed 只表示所附 scroll 的前后完整截图字节是否不同；框架不推断
是否出现新内容、是否到达边界，也不推断落点、方向或界面响应。frame_changed=false 时结合两帧判断原因且不得原样重试。
根据判断改换动作；
若相应 Region 的主要范围已观察完，则用 page_update 将其 coverage_complete=true，并令 action=null。
连续重复相同动作且没有可见变化时必须换方向、位置或其他动作，不要原样重试。根据 attempt_count、最近真实
结果和重复路线主动避开其他循环。point_1000 始终相对最新完整截图，范围为 0..1000。
"""


SURVEY_PAGE_PROMPT = """\
当前任务是 survey_page：确认页面并登记其 Region 和大多数明确功能入口，不执行已登记入口的功能。会进入或切换独立
功能内容、展开隐藏功能内容或解除功能限制的控件属于入口，应登记；具体操作页中仅改变数值、状态或完成当前功能的
内部控件不是遍历入口。明显只会离开应用的控件只登记其语义；应用外界面不是应用内入口或 Page，执行后不要继续调查。
遍历范围是目标应用的主要功能，即让用户执行、查看、创建、修改、控制或配置该应用核心用途的功能表面。仅解释应用、
提供参考信息或展示非功能元信息且不承载核心操作的辅助内容不登记为入口。只列出如何调用或操作既有功能的方法、
但本身不执行或配置核心功能的内容，同样属于参考信息。不要只按名称判断；尚未展开、可能包含未知
主要功能分支的容器入口可以先登记。菜单、面板或其他容器已经展开，只表示其中各分支需要逐项检查，不代表所有
可点击分支都要登记；展开后不符合主要功能边界的分支直接省略。

入口表示从当前 Page 可执行的图边，不要求控件属于页面主体：应用内全局或顶级导航只要会切换到其他独立功能内容，
也必须作为候选登记；当前已选中、点击后不会切换内容的导航项不重复登记。

结构增量只写 page_update。为每个 Region 取一个在当前页面和 known_region_candidates 中有区分度的稳定自然语言名称；
优先使用可见功能标题或主要内容，不用位置、序号和动态数值命名。summary 简述用于区分身份的主要组件及角色，不写泛泛主题。
Region 按共同功能角色的组件组划分，不按单个按钮、图标或标签拆分；这些控件应归入其可见的工具栏、导航组、
内容面板或设置组。若 Reviewer 指出碎片化或归属错误，重新提交完整划分，而不是把遗漏控件另建成 Region。
同一审核讨论中的修订只修改框架或 Reviewer 明确指出的问题；未被指出且与最新截图不冲突的 Region name、entry target
和归属保持不变。不要在修正 bbox、coverage、summary 或其他局部字段时顺带改名或改绑。只有最新截图证明原身份或归属
错误，或 Reviewer 明确要求改变 Region 集合、身份或归属时才修改，并在顶层 reason 中说明具体依据。
先确定当前唯一的应用内 active interaction surface。若当前 Page 是应用自己的菜单、对话框、抽屉、搜索/命令面板或
其他正在接收输入的功能表面，只划分这个表面；后方仍可见的宿主页只是上下文，不写入本轮 Regions，也不要把当前
功能表面当作干扰调用 handle_interruption 关闭。若没有这类前景功能表面，才划分当前应用页面。始终排除桌面顶栏、
Dock/任务栏、IME、其他应用内容以及最小化、最大化/还原、关闭等窗口管理控件。
按组件是否能独立出现、消失、替换、滚动或承担稳定的工具/导航/内容角色确定边界；同一功能视图中仅由标题或视觉分栏
区分、总是共同出现和替换的内部小节合并为一个 Region。主编辑区、画布、列表、终端内容区等可以是有效 Region，
前提是它们在当前应用中有明确稳定的功能角色，而不只是“承载任意页面内容”的空泛槽位。Region 是否成立不取决于
候选入口数量；只有一个入口的独立功能组件也可以成立。
Region 是用于全局去重和入口身份复用的稳定功能组件身份，不是页面中的矩形范围、通用内容容器、位置或布局槽位。
同一 Region 可以在多个 Page 上出现；它的主要组件、组件角色和功能入口应保持稳定，使一次探索得到的入口身份和
已验证结果能够在这些 occurrence 之间可靠复用。候选的 canonical_name 和 component_signature 是旧 Region 的代表事实。
功能身份必须来自容器内具体、稳定的主要组件和入口语义。“承载当前页面内容”“中心工作区”或“主视图容器”只描述
布局槽位，不是可复用的功能角色。若 name/summary 只能说明它是承载各页不同内容的通用区域，应按当前内部功能重新划分和
命名，不要把这个外层槽位提议为共享 Region。
共享 Region 是入口去重的候选边界：候选中的
verified_entries 是该共享 Region 内已有真实验证结果的入口，只含本轮批量绑定所需的精确信息。只有当前 Region 的主要组件、组件角色和关键入口
能够对应，且没有关键冲突时，才复用其 canonical_name 并填写 equivalent_to_region_ref；动态数值和绝对位置可以不同。
判断能否复用前先问：若把候选 Region 已登记的入口身份和已验证结果应用到当前 Region，是否仍然准确，且不会把控件身份、
功能或结果对应错？只有具体内部组件、入口语义和迁移结果都明确对应时才合并。候选列出的具体入口若被服务不同功能的入口
取代，或主要组件已换成另一组控件，应保留为不同 Region；不能用相似控件外形或同类容器抵消该冲突。若只是使用同一中心
工作区、外层容器或空间槽位，必须越过外层容器比较内部功能组件。仅主题相近、布局相似或到达同一页面不足以合并；不确定时
留空，框架建立新的共享 Region。equivalence_reason 简述实际对应
组件或保留新区块的关键冲突。若复用，理由必须点名候选签名和当前截图中至少一个功能相同的具体内部组件或入口；只有
workspace、container、structural role 或相同位置不能支持复用。region_ref 只用于这次精确映射，不能凭名称或位置猜测。入口放在所属 Region 的 entries 中，
框架自动绑定 Page 和 Region；不要重复输出 region_name，也不要填写新 entry_id。若当前可见入口与 verified_entries 中某项的
控件角色、状态和真实结果稳定等价，填写其 equivalent_to_entry_id，框架会直接为当前来源 Page 建立 inferred edge，不再派发重复点击。
仅来源 Page 不同不是拒绝复用的理由；有具体来源栈、状态或控件角色冲突时才不绑定。同轮重复实例放 equivalent_occurrences。
框架把成功项写入下一轮页面账本，只把未写入项及其可读原因作为纠正反馈返回。某 Region 的入口被拒时，
其本轮 complete=true 会延后；当前 Region 阶段保持不变，直到 Agent 补交或给出其他处理结果。
框架不按字符串、位置或截图哈希合并。record_regions 阶段只登记稳定的功能组件身份、入口及其语义归属。
scroll.container_hint 用自然语言描述截图中实际想滚动的容器，不要求它是已登记 Region；point 使用全屏 0..1000 坐标。

coverage_complete 表示已观察主要范围，允许少量遗漏；明显仍有大段内容时继续滚动。忽略不妨碍当前操作的临时
前景层，不等于其下方 Region 已观察完整；若它遮住一段足以隐藏普通控件的连续范围，该 Region 保持 false，等待
后续无遮挡截图再复查。所有 Region 都明确完成后，框架会直接转入入口任务。known_entries 中的入口已登记，不要重复登记。
"""


ENTRY_REVIEW_SPECIALIST_PROMPT = """\
你是独立 Entry Reviewer。当前任务审核页面调查提出的入口候选及其所属 Region 的入口覆盖，不规划路线、不执行
GUI 动作，也不重新划分 Region。以最新完整截图为事实依据，同时检查页面调查的理由是否与截图和候选一致。
如果主 Agent 的理由把你最终剔除的候选说成应探索入口，或把你最终保留的候选说成不应探索，
reason_consistent 必须为 false；若主 Agent 声称某 Region 已完整、而你因视觉证据不足延期该 Region，也必须为 false。
它判断的是理由中的功能和覆盖结论是否与你的裁决一致，不是理由提到的文字是否在截图中可见。

遍历范围是目标应用的主要功能：让用户执行、查看、创建、修改、控制或配置该应用核心用途的功能表面。仅解释
应用、提供参考信息或展示非功能元信息、且不承载核心操作的辅助内容，不进入功能图。不要只按控件名称判断，
要根据它实际承载的能力及其与应用核心用途的关系判断。只列出如何调用或操作既有功能的方法、但本身不执行或
配置核心功能的内容，也属于参考信息。

窗口标题栏或工具栏中，最小化、最大化/还原和关闭这三类窗口管理控件不探索；其余可见可交互控件都必须进入
候选检查，但“必须检查”不等于“必须保留”。只保留点击后会打开或切换主要功能的独立 Page、对话框、菜单、
面板，或显露一个此前隐藏且需要单独调查的主要功能 Region 的控件。尚未展开、但可能包含未知主要功能分支的
容器入口可以保留；展开后只保留实际服务于主要功能的分支。

仅改变当前功能的数值、运行状态、选择状态，或只执行、暂停、恢复、重置、提交当前功能而不产生新功能表面的
控件，不是遍历入口。independent_entries 是本轮逐像素复核后的完整保留清单：同时列出 candidates 中仍成立的
原始 Region 和 target，以及截图中明确符合上述边界、但页面调查漏掉的新 target。新 target 只要求使用 regions
中已有的原始 Region 名，不要求已存在于 candidates；它必须与同一 Region 的已有 candidate 明确不同。若可见
部分只是已有 candidate 的遮挡状态、别名、另一种描述或纯位置称呼，不得新增。若 reason 明确认定某个可见控件
是有效入口，就必须把同一控件列入 independent_entries，不能只在理由中承认。原候选因前景层遮挡、画面裁切或
视觉证据不足而暂时
无法看清实际控件时，不能把它判成
非主要功能，也不能凭历史或惯例保留；把其原始 Region 和 target 放入 deferred_entries，框架会保持所属 Region
未完成并等待后续无遮挡观察。即使没有可命名的原候选，只要前景层、裁切或模糊使某个 regions 中的 Region
无法可靠检查是否还漏了主要功能入口，也把该 Region 的原始 name 放入 deferred_regions；不能只因现有候选清晰
就推断被盖范围没有入口。遮挡位于 Region 外，或该 Region 已能完整检查时不得延期。明确属于辅助内容、当前功能
内部控件或窗口管理的候选直接剔除，不得延期。

coverage_audit_regions 中的每个 Region 都必须在本轮逐一复核，即使主 Agent 没有为它提出 candidates；
直接依据当前完整截图和该 Region 的功能边界检查是否漏了会打开或切换主要功能表面的入口。能可靠检查时给出完整
裁决，不能可靠检查时放入 deferred_regions。若请求附有带 R 标签的同帧图，R 框只标示每个已批准 Region 的当前
可见边界；必须查看框内实际像素来找漏项或判断遮挡，不能把 summary、主 Agent reason 或已有 candidates 当成覆盖
证据。只能使用 regions 中已经批准的原始 Region name；不能创建、拆分、
合并、重命名或改绑 Region。若你认为划分有问题，只在 reason 中说明，不得通过 independent_entries 或 deferred_regions
臆造新 Region。

若请求中含 entry_dispute，本轮仅复核其中精确的已登记 Entry 是否被错当成独立功能入口，不重新审核页面覆盖，
也不补报其他入口。若它仍会打开、切换或显露需单独调查的主要功能表面，把该原始候选放入
independent_entries；若最新截图不足以判断，放入 deferred_entries；若它明确只是当前功能内部的输入、数值、
选择、状态、提交或取消控件，则两个 Entry 数组均不包含它。此模式 deferred_regions 为空。
reason_consistent 还要判断 observed_problem 对该精确 Entry 的描述是否与截图和裁决一致。不要因为主 Agent 请求
纠错就自动同意，也不要删除或改写其已有观察证据。

若输入含 review_conversation，它是主 Agent 与你之间此前未解决意见的完整自然语言转交。逐条回应其中被丢弃、
保留或延期的具体候选，不要沿用旧结论而忽略主 Agent 的修订。若仍认为某候选不是入口，结构化数组必须剔除它，
reason 也必须明确说明它为什么只是当前功能内部控件；若 reason 认为它会打开或切换独立功能表面，就必须将同一
候选保留在 independent_entries。结构化选择和自然语言理由不能表达相反结论。

candidates 只是主 Agent 的提案，不是可见控件的封闭清单。对每个待审 R 框，必须依据截图逐个检查同一组件组内
所有明确可交互的同级项；reason 要交代这些同级项为何保留、剔除或延期，符合入口边界的项必须全部写入
independent_entries。仍有未交代的可见同级项时，不得声称没有其他入口或覆盖完整。
没有延期项时将 deferred_entries 和 deferred_regions 填空数组。应用内全局或顶级导航若会切换其他主要功能内容，
同样属于入口；当前已选中的无效果导航项不补。
"""


EXPLORE_ENTRY_PROMPT = """\
当前任务是 explore_entry：只处理 exploration_task 中精确 entry_id 对应的入口。先到达其来源页面并定位真实控件，再执行
一次安全尝试，观察真实结果、登记页面边，并恢复本任务造成的可逆状态。click.entry_id 表示本次实际点击的已登记控件，
不是当前任务标签。每次点击前先查看本轮“当前 Page 的既有探索”；若当前截图中的实际控件与其中某项的 Page、Region 和控件角色明确对应，
无论本次用于入口探索、导航、恢复还是关闭干扰，都填该项的精确 entry_id。只有确认没有对应的已登记入口时才留空；
不得把当前任务的 entry_id 绑定到另一个控件。

若 task 提供 equivalent_entry_candidates，只比较当前入口与这些共享 Region 内的候选。候选出现表示 Region 已由 Agent 显式
判为同一功能区，不是框架按名称或位置猜测。若可见控件角色、目标页面和最近真实结果一致，且当前截图没有显示结果依赖来源栈、
状态或上下文，应优先调用 reuse_entry_result 建立 infer 关系；仅位于不同 Page 不是重新点击的理由。Back、关闭、状态切换等
存在具体上下文依赖证据时才直接探索，并在本轮顶层 reason 中说清证据。不要从未提供的 ID 或全局名称猜测等价关系。

若最新截图已经足以确认当前精确 Entry 只是当前功能内部的输入、数值、选择、状态、提交或取消控件，而不会打开、
切换或显露需要单独调查的主要功能表面，调用 report_record_error：kind=entry，subject 填 task.entry_id，
observed_problem 写明可见功能关系。框架会调用独立 Entry Reviewer，并把完整判断和理由返回给你；单次省略候选只
记录争议，不会直接停用正式 Entry。不要用这条通道代替失败点击、暂时不可用、无法到达或普通页面覆盖复核，也不要上报
其他 entry_id。

途中首次出现的新页面或真实跳转边可以先用 screen 最小登记，完整 Region/page_update 调查留给框架随后派发的 survey_page；
不要在当前入口任务里转去调查无关的已知功能。task.route 是框架给出的建议路线，你仍根据最新截图自行执行或选择更直接的可见路线。
Reviewer 已确认精确目标和点位、真实点击后没有出现入口结果时，在 previous_action.reason 中结合前后图说明最可能原因。
只有你判断证据已经足以结束该入口时，才将 failure_kind 判断为 temporarily_unavailable 或 not_interactive；框架会保存
该分类与原因并停止再次派发。若仍需在新状态继续当前入口，令 failure_kind=null 并选择下一动作。不要把已执行但未得到
入口结果的点击报告成页面或图不可达。只有在尚未执行精确目标前，路线或目标本身已被
明确证明无法到达或定位时，才用 finish_exploration 的 unreachable_evidence 提交当前 entry_id 和真实证据。
"""


REGION_PROBE_PROMPT = """\
The current task is probe_region. Discover user-visible core operations performed
inside task.region; do not register those controls as Entries. An Entry opens,
switches, or reveals a separately inspectable function surface, while an internal
operation changes or runs the function already represented by this Region.

Work only on the assigned Page and Region. Choose a visible, clearly safe
operation, let the independent Click Reviewer verify the exact control, execute
it, and settle the real before/after result. Report business_effect only when
both values are visually grounded, using state_change for a property update,
object_creation for a newly visible object, object_removal for an object that
visibly disappeared, or query_result for results caused by the submitted query.
Use an exact approved Region name from the arrival
context for the visible effect. The action source Region and effect Region may
differ. Bind only concrete inputs or selected values used by this action. Do not
infer capability success from a click, expected behavior, or pixel change.
Avoid destructive, externally submitted, permission-changing, account, or
irreversible actions. Follow task.reason's coverage priority. One representative
result covers that operation type for traversal even when its separate evidence
verification level remains discovered. Never repeat the same control with
different homogeneous values merely to add evidence. Inspect the latest
screenshot for a distinct safe, user-visible core operation. If the assigned
Region is registered on another material Variant but is absent now, reveal that
known surface through a visible safe Entry or route; absence from the current
Variant is not completion evidence. When no distinct operation remains on the
observed Region, call complete_region_probe with the concrete visual reason.

input_text is available only in this Region-probe phase. Use it only for short,
non-sensitive search, filter, or query text whose entry itself merely reveals
visible results. It does not press Enter. Never use it for credentials, messages,
form submission, data creation/editing, authorization, or other consequential
input.
"""


REGION_EQUIVALENCE_REVIEW_PROMPT = """\
当前任务只处理 pending_corrections 指出的共享功能区域争议，不执行界面动作，也不调查其他区域。根据最新截图和纠正理由，
比较具体内部组件、组件作用和关键入口；相同位置、相似布局、相近主题或同属一个页面都不能证明是同一功能区域。当前请求
没有提供足够的跨页面对应证据时，保留为新的功能区域，交给后续动作前后批量复核。用 page_update 重报当前截图中的区域和
入口，action=null；不要输出当前响应结构中不存在的共享引用字段。
"""


STAGE_PROMPTS = {
    "resolve_app_scope": """\
系统暂时无法确认当前前景窗口是否属于目标应用。本轮只比较当前完整截图与附带的最近一张已确认目标应用截图，调用
report_app_scope 报告视觉归属。不要登记或修订 Page、Region、入口和动作结果，也不要执行界面动作。
""",
    "identify_page": """\
当前阶段是 identify_page（确认页面身份）。只判断当前截图属于清晰的 known/new 页面，或在确实不确定时调用 page_identity。
本轮不判断 Variant；Page 确认后，下一轮只提供该 Page 的 Variant。
""",
    "identify_variant": """\
当前 Page 已确认；本轮只判断其 material Variant，完成后继续自主探索。
""",
    "review_page_identity": """\
只复核 specialist 的 Page 判断；接受后下一轮再判断该 Page 的 Variant。
""",
    "review_variant_identity": """\
Page 已确认；只复核 specialist 对该 Page 的 Variant 判断，完成后继续自主探索。
""",
    "review_identity": """\
当前阶段是 review_identity（复核 Page Identity 提案）。只根据当前截图和 specialist 证据提交 previous_tool_review。
接受后页面才会登记；拒绝或不确定时说明裁决，不预先执行页面调查或入口动作。
""",
    "record_regions": """\
当前阶段是 record_regions（建立页面结构）。页面身份已经确定；用一次 page_update 批量登记当前截图中可辨认的 Region，
并把当前已清楚可见的功能入口放进所属 Region 的 entries，由框架自动绑定。主要范围已看清的小型或静态 Region 可同轮直接 coverage_complete=true；
只有仍需滚动、展开或继续观察的 Region 留为 false，不要把所有 Region 机械拆成逐个调查轮次。不要执行已登记入口的功能。
若当前 Page 本身是应用内菜单、对话框、抽屉或搜索/命令面板，只划分该 active surface，不登记后方宿主页，也不调用
handle_interruption 清除它。提交前逐一删除应用外表面和窗口管理控件的语义 Region 或入口；把同一连续组件中按按钮
类型、标题、卡片或视觉分栏拆出的碎片合并。
若 task.reason 用自然语言说明最近动作没有切换 Page、但显露或改变了一个功能表面，这是一次增量调查：
保留既有完成事实，只补充当前动作新显露或明显改变的功能 Region 和入口。
""",
    "review_region_equivalence": """\
当前阶段是 review_region_equivalence（复核共享 Region）。只解决 pending_corrections 指出的 Region
等价提案；完成条件是明确重报为同一共享 Region或独立新 Region。
""",
    "survey_region": """\
当前阶段是 survey_region（调查指定 Region）。只围绕 task.region 观察主要范围、把尚未登记的不同功能入口放进该 Region 的 entries，并在视觉上
确有需要时滚动或展开内容。认为主要范围已看完时提交 coverage_complete=true；false 不是必须继续滚动的命令。
若内容在容器边缘明显被截断或仍向外延续，先在本阶段对可能容器做一次低风险滚动观察，不要先报完成；没有可见的延续证据时不做额外查漏。
若局部事实为 distinct_frame_since_incomplete=false，说明该 Region 自上次明确 incomplete 后仍是同一字节帧；
它不能作为新的覆盖证据直接改成 complete，应先通过滚动、展开或其他观察得到不同视觉帧再判断。
同一截图中若其他小型 Region 的主要范围也已看清，可在同一 page_update 中一并登记或完成，无需等待框架逐个派发；
真实滚动可作用于承载该内容的 Region、外层页面或其他可见容器，不要求滚动容器与 Region 一一对应。
用 survey_memory 维护该 Region 的简短累计调查记忆：写实际语义锚点、连续滚动或展开轨迹、跳跃或不确定区间以及仍待
检查的方向；不要预设顶部/中部/底部或固定段数，也不要重复入口账本。每次滚动结算后结合旧记忆与新截图更新它。
若列表或瀑布流持续加载新的帖子、商品等内容实例，覆盖目标是发现不同质 Region 和功能入口类型，不是枚举所有内容实例。
滚动观察中若内容实例继续更换，但页面结构和不同质功能入口不再增加，可在 survey_memory 写明观察批次、重复结构和剩余
不确定项后报告主要范围完成；同质实例引用已登记代表或显式等价 occurrence，不要逐个创建任务。一次无变化或临时加载停顿
本身不能证明这类动态列表已经覆盖完成。
""",
    "probe_region": """\
The current stage is probe_region. Probe one not-yet-covered internal operation
in task.region, or call complete_region_probe when no distinct visible core
operation remains. Different values on the same control are not distinct
operations.
""",
    "route_to_page": """\
当前阶段是 route_to_page（到达待调查页面或目标区域可调查的页面状态）。根据最新截图和已知页面关系逐步导航到 task.page；到达后准确报告页面身份，
若当前任务绑定 Region 且 task.route 指向同一 Page 的另一个 material Variant，Page 名相同仍不算到达，须恢复到
路线所示 Variant。路线步骤带 entry_id 时，它是已验证导航入口：点击该步骤应绑定这个精确 ID，不把导航动作记为
目标 Region 的内部操作。若当前 Page 已是 task.page 但 task.route 为空，说明目标区域在当前状态下不可完整调查且暂无
已验证状态转换；根据最新截图自行寻找一个安全、可见的局部导航或恢复步骤，不要把缺少已知路线直接判断为不可达。
每次只执行一步并观察真实落点，框架会记录动作边并重新计算。完整 Region 调查留给下一阶段。task.route 只是路线建议，
不能代替真实 GUI 动作。
""",
    "route_to_source": """\
当前阶段是 route_to_source（回到入口来源页）。只把当前界面导航到 task.page；途中真实出现的新页面或边可以最小登记，
但不调查无关功能。若当前 Page 已是 task.page 但 task.route 为空，说明入口所需页面状态尚未满足且暂无已验证状态转换；
根据最新截图自行寻找一个安全、可见的局部导航或恢复步骤，每次只执行一步并观察真实落点。当前页及入口来源状态满足后，
本阶段完成。
""",
    "locate_entry": """\
当前阶段是 locate_entry（定位并尝试派发入口）。只处理 task.entry_id 对应的 target：在来源 Region 中重新按最新截图定位，
执行一次安全尝试，并在下一轮结算真实结果。若目标当前不可见，留在来源页，通过滚动或与目标 Region 直接相关的局部
展开继续定位；不要仅因无关导航控件可见就离开来源页。Reviewer 已确认并执行的精确点击若没有出现入口结果，下一轮必须在
previous_action.reason 说明最可能原因。你判断该结果已经足以结束入口时，才将 failure_kind 判断为
temporarily_unavailable 或 not_interactive；仍需继续时保持 null 并选择下一动作。不要提交不可达证据。
点击的实际控件若与本轮“当前 Page 的既有探索”中某个已登记入口明确对应，即使它是导航、恢复、关闭干扰或顺路动作，
也绑定该入口的精确 entry_id；只有没有对应已登记入口时才留空。
""",
    "completion_ready": """\
当前阶段是 completion_ready（完成复核）。对照最新截图和当前页 Region/入口事实做最后检查：若截图仍显示未登记的 Region、
入口或明显被截断的连续内容，可补交 page_update 或做一次必要的滚动观察，框架会重新打开对应任务；不要把账本中已有 Region
换个近义名称重复登记。确无待办时调用 finish_exploration 提议完成。若框架返回缺口，下一轮按新阶段处理。
""",
}


SETTLEMENT_GATE_PROMPT = """\
本轮还必须先结算 pending_action：previous_action 只评价所附动作前图与最新图之间的这一次真实动作。若结算结果使当前阶段
完成或改变，框架会保存结果并在下一轮重建阶段；同轮附带的下一阶段动作不会执行。
"""


# General visual/evidence invariants only. The framework still does not classify
# UI by strings, styles, fixed scroll counts, or application-specific rules.
PROTOCOL_PROMPT += """
Scrolling or moving a viewport normally keeps the same Page. Do not invent a
new Page from content displacement alone. Judge Page continuity from the latest
visual organization, the natural-language graph, and the recent action context.
"""

SURVEY_PAGE_PROMPT += """
A function entry must be a currently visible, pointable interactive affordance
or have reliable interaction evidence. Do not turn static titles, content,
display values, or disabled controls into entries by inventing an action verb.
Reuse a verified Cross-Page entry during page survey only through the exact
equivalent_to_entry_id exposed on its shared Region; otherwise wait for the
corresponding explore_entry task and use reuse_entry_result. Equivalence is your
explicit semantic judgment, never a framework string match.
"""

STAGE_PROMPTS["route_to_page"] += """
If the current Page is not task.page, action=null is not progress: execute the
first visible route step or report a concrete blocker.
"""
STAGE_PROMPTS["route_to_source"] += """
If the current Page is not task.page, action=null is not progress: execute the
first visible route step or report a concrete blocker.
"""

SETTLEMENT_GATE_PROMPT += """
The activated control is fixed by pending_action and the independent Reviewer;
do not rename it from the landing Page. Judge only its result from the after
frame: a target-related toast, banner, or revealed content can verify
activation; staying on one Page does not by itself mean failure. Discovery has
no predicted destination: a coherent immediate transition belongs to the
Reviewer-bound target even when another entry shares the same landing Page.
The pending entry action has already executed. task.page is its before-action
source, not a Page where the after screenshot must remain. Settle the result
before routing back; do not reject a new landing merely because it differs from
task.page.
"""


# Compact main-Agent task contracts. Detailed visual criteria stay in the
# corresponding stateless specialist instead of being repeated here.
PROTOCOL_PROMPT = """\
只推进框架提供的当前任务和当前阶段。页面、页面状态版本、功能区域、入口与动作结果只有在相应复核或真实操作后才成为事实。最新完整截图优先于历史；历史只用于理解已经尝试的路线、参数、结果和拒绝理由，旧坐标不得复用。
"""

SURVEY_PAGE_PROMPT = """\
当前任务是调查页面或 task.region，产物是稳定功能区域和其中对用户命令有意义的操作。功能区域是共同承担一个稳定功能角色的组件组，不是单个按钮或矩形位置；工具栏、导航组、内容面板和设置组中的控件归属其服务的区域，不能因占位、分栏或动作不同随意拆区。

整页调查必须列出当前前景交互表面中属于目标应用的所有稳定区域；常驻、重复、简单或没有候选操作都不是省略理由。task.region 调查只更新该区域。排除系统顶栏、Dock、输入法、其他应用和窗口管理控件；外部临时表面遮住目标区域时先调用 handle_interruption，取得无遮挡截图后再调查。应用内模态表面在前景时，后方不可交互内容只作上下文。

逐个扫描当前区域内可见的交互组件组，并把对理解或执行用户命令有意义的操作提交给入口复核器分类，不要在主 Agent 阶段把“无需真实探索”误当成“无需记录”。例如上一项、下一项、布尔切换或参数选择通常应登记但无需逐个试验；打开详情、菜单、编辑模式，改变其他区域，或解决有价值交互歧义的操作通常需要探索；静态文字和装饰不登记，危险、不可逆或有外部效果的命令操作只登记、不执行。重复内容或参数值只提交一个代表，文字与附属图标只有预期直接效果相同时才合并。

全局或顶级导航中会切换到另一稳定功能内容的未选中项都应登记，不能只看当前项或两端控件。known_entries 已是正式操作，不要重新放入 entries；当前已选中、禁用或受前置状态阻挡不删除既有操作。入口争议只通过 page_update.entry_resolutions 处理 task.region 内的候选，每项给出 keep 或 drop 和具体理由。

operation 描述用户操作，target 是带必要功能上下文的控件名，subject 只作可选说明。同页重复且各自有状态的同质实例分别建区，后续实例用 same_group_as 指向首个；已分组实例出现明确能力冲突时用 split_from_group=true。control_type 只决定执行方式：当前可直接输入且最终需要 input_text 的字段才是 input，先点击才显露输入框的目标仍是 control。调查只观察、滚动、建账和复核；page_update 只提交结构事实，不与界面动作同时请求。
"""

EXPLORE_ENTRY_PROMPT = """\
当前任务是探索一个已经登记的操作。task.operation 是要验证的用户操作，task.target 是带功能上下文的语义控件名。只处理 task.entry_id 对应的可见控件；task.region 是它所属区块，region_survey 已由框架确认完成。路线、定位、恢复和真正尝试都属于这条任务；中间步骤失败只结算该步骤，不能结束这条操作任务。真正尝试时使用 purpose=entry_attempt，其他动作按实际作用填写 purpose。task.control_type=input 时，真正尝试必须使用 input_text；点击聚焦只能作为 locating 中间步骤，不能完成输入操作。不要顺路执行同一区块的其他目标。
task 给出等价入口候选时，若当前控件角色、参数意义和已验证结果一致且没有具体状态冲突，调用结果复用工具；若仍需真实操作，理由必须说明截图中的具体差异。
已经回到该入口的来源状态、扫描其所属区块后仍找不到目标时，调用 report_record_error，填写 kind=entry、subject=task.entry_id、problem_type=target_not_found 和具体可见依据；框架只在这时按需比较首次发现截图与当前截图。
"""


ENTRY_PRESENCE_REVIEW_PROMPT = """\
你是独立入口存在性复核器。图1是某个已登记操作首次被接受时的完整截图，图2是主 Agent 在同一来源状态定位失败时的当前完整截图。只判断给定操作目标在两张图中的视觉证据，不规划动作、不补入口、不凭应用惯例猜测。

discovery_presence：图1明确支持该操作目标为 supported，明确不含或与目标矛盾为 unsupported，证据含糊为 uncertain。current_presence：图2明确可见为 present，明确缺失为 missing，证据含糊为 uncertain。reason 点名两图中的具体标签、图标归属或缺失位置。
"""

ENTRY_REVIEW_SPECIALIST_PROMPT = """\
你是独立操作复核器。根据产生本次候选的固定完整截图，审核指定区域内操作的真实性、归属、去重和探索价值；候选不是封闭清单。你不判断页面身份、不重划区域、不规划动作。

遵守四条原则：
1. 按组件组扫描，再比较候选；只补充截图中可直接辨认的命令相关漏项，不凭应用惯例补全。原候选必须原样保留 region_name、operation 和 target；只有补项可新命名。同意图、同直接效果的实例或参数只留一个代表，效果不同不能合并。
2. independent_entries 表示需要真实探索：操作会打开新功能表面、形成可继续操作的结果、改变其他区域、解锁后续操作，或解决有价值的交互歧义。菜单、编辑界面及产生结果集合的搜索/筛选应探索；仅因可点击或常用不能证明需要探索。
3. record_only_entries 表示值得正式记录但无需专门遍历：语义已看清，执行只产生浅显局部状态、连续值、选择成员、内容位置或待提交表单字段变化。上一项、下一项、开关、普通参数和表单字段通常属此类；产生结果集合的输入除外。这里只证明操作存在，不证明效果或路线已验证。危险、不可逆或有外部效果但命令相关的操作也只记录，记录不授权执行。
4. deferred_entries 表示操作有探索价值，但因遮挡、裁切、模糊、禁用或缺前置状态而暂不可执行；non_task_entries 只放静态、装饰、应用外或无命令语义的候选。不能用 non_task_entries 表示“无需探索但值得记录”。

应用内全局或顶级导航中会切换稳定功能内容的未选中项必须补齐。每项只归属其实际服务的一个区域，不能按距离猜测。coverage 只依据固定截图；区域被遮挡到可能漏掉同组控件时写入 deferred_regions。

shared_region_entries 是该正式区域已有的操作，不是待重新发现的候选。只有 operation 和语义 target 都精确一致时才可填写 equivalent_to_entry_id；任一项不同就按新操作审核。当前选中、禁用或受前置状态阻挡不能删除既有操作。

operation 描述操作，target 是带功能上下文的控件名；subject 只作说明，control_type 只决定执行方式。reason 按组件组说明分类依据。只改变执行时机时 reason_consistent=true；自然语言判断与截图或结构化分类矛盾时才为 false。
"""

STAGE_PROMPTS = {
    "identify_page": "当前阶段是确认页面身份。只判断当前截图属于已知页面、新页面或确实不确定；需要候选复核时调用页面身份工具。本轮不判断页面状态版本，也不执行其他动作。\n",
    "identify_variant": "当前页面已经确认。本轮只判断当前截图属于该页面的哪个实质页面状态版本；需要候选复核时调用状态版本身份工具，不重新判断页面。\n",
    "review_page_identity": "只复核页面身份专家的结论，不执行其他动作。\n",
    "review_variant_identity": "只复核页面状态版本专家的结论，不执行其他动作。\n",
    "review_identity": "只复核待处理的身份专家结论，不执行其他动作。\n",
    "record_regions": "当前阶段是建立页面结构。一次提交当前可见功能区域以及各区域中当前可见的独立功能入口；主要范围已经看清的区域可直接标记 coverage_complete=true。只提交 page_update，action=null。\n",
    "review_region_equivalence": "只根据框架返回的具体复核意见修正当前页面的功能区域提案。\n",
    "survey_region": "当前阶段是继续调查 task.region。先扫描组件组并按未知功能信息筛选入口；纯参数语义和未决问题写入 survey_memory。可滚动或局部展开取证；结构事实用 page_update 提交，界面动作与 page_update 分开请求。主要范围看清后将 coverage_complete 设为 true。\n",
    "route_to_page": "根据最新截图和已验证路线逐步导航到 task.page；一次只执行一个实际可见步骤。\n",
    "route_to_source": "根据最新截图和已验证路线逐步回到入口来源页面；一次只执行一个实际可见步骤。\n",
    "locate_entry": "当前阶段是定位并尝试入口；根据最新截图继续这条入口任务。\n",
}

SETTLEMENT_GATE_PROMPT = """\
当前有一项已经执行但尚未结算的界面操作。本轮先只比较动作前截图和最新截图，判断这一个操作产生的真实可见结果；
操作目标及其在当前任务中的作用已经由框架绑定，不得根据落地结果将它改写成其他控件。尚未完成的路线、定位和调查步骤继续保留。

导航、定位、临时干扰处理或区域调查只结算对应的局部结果；中间导航或定位动作失败不能结束目标入口。只有
purpose=entry_attempt 才判断入口结果；探索未知入口时不预设落地页面，执行后连贯出现的即时变化就是待记录结果。

用 effects 逐项报告截图中实际受影响的已知范围：入口所属区域用 owner_region，其他区域必须填写正式区域名称；
结构变化填 structure，状态变化填 state，数值或文字值联动填 value。一个动作影响多个已知区域时全部列出，框架只会让
structure 对应区域重新调查，state/value 不会令结构覆盖失效。页面临时交互模式用 page_mode，只记录截图中已经出现的
模式和当前已选区域；选择成员不同不产生页面状态版本。跨页面仍可见的应用级事实用 app_state，同值的前后观察只表示
真实确认了持续性。不要根据应用惯例、隐藏权限或内容类别补写范围。

为兼容旧记录，只有无法用上述已知范围表达时才使用 visible_effect；变化只发生在入口所属区域时填 owner_structure 或
owner_state，出现新的页面级表面或影响范围无法局限到所属区域时填 page_structure 或 uncertain。

局部目标未实现时说明前后截图中的具体原因。只有入口已经被真实尝试且证据足以停止重试，才填写终止原因。若结算改变
当前阶段，本轮不再请求下一动作；阶段未变时可以根据最新截图继续下一步。
"""

_MAIN_TOOL_DESCRIPTIONS = {
    "report_app_scope": "系统窗口归属暂时不可用时，根据当前截图和附带的最近一张目标应用截图报告视觉归属；不登记探索事实。",
    "page_identity": "当前页面或页面状态版本无法可靠确定时，请求对应的独立身份复核。候选和代表截图由框架提供，reason 说明当前截图中的具体争议。",
    "report_record_error": "最新截图与正式账本冲突时，报告页面、状态版本、功能区域、入口、覆盖或导航中的具体记录问题；普通动作失败不属于记录错误。",
    "handle_interruption": "疑似临时表面确实遮挡或阻止当前阶段时，请求独立行动复核器判断是否需要一个可见、低风险的恢复动作。",
    "reuse_entry_result": "当前任务明确给出等价入口候选，且可见控件角色、上下文和已验证结果一致时，复用该精确代表入口的结果。",
    "defer_current_task": "当前已派发入口在尝试前已被可见控件阻断，或精确尝试后无可见结果且截图显示前置控件时使用。prerequisite_target 必须逐字填写一个当前已登记的可执行控件，不能填写浮层或区域名；同时说明可见阻断理由。",
}
TOOL_CATALOG = [
    {
        **item,
        "description": _MAIN_TOOL_DESCRIPTIONS.get(
            str(item.get("name") or ""), str(item.get("description") or "")),
    }
    for item in TOOL_CATALOG
    if item.get("name") in _MAIN_TOOL_DESCRIPTIONS
] + [{
    "name": "defer_current_task",
    "description": _MAIN_TOOL_DESCRIPTIONS["defer_current_task"],
    "input_schema": {
        "type": "object",
        "properties": {
            "prerequisite_target": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["prerequisite_target", "reason"],
        "additionalProperties": False,
    },
    "effect": "defer_current_entry_until_prerequisite_settles",
    "returns": "当前入口的延期记录，或拒绝原因",
    "requires_review": False,
    "executes_gui": False,
}]


def protocol_prompt_for(
    task_type: str,
    phase: str = "",
    *,
    has_pending_action: bool = False,
) -> str:
    """Return the current task and stage instructions only."""
    task_kind = str(task_type or "survey_page")
    phase_name = str(phase or "").strip()
    if phase_name in {
        "identify_page", "identify_variant", "review_page_identity",
        "review_variant_identity", "review_identity", "resolve_app_scope",
    }:
        task_prompt = ""
    elif phase_name == "review_region_equivalence":
        task_prompt = REGION_EQUIVALENCE_REVIEW_PROMPT
    elif task_kind == "survey_page":
        task_prompt = SURVEY_PAGE_PROMPT
    else:
        task_prompt = EXPLORE_ENTRY_PROMPT
    stage_prompt = STAGE_PROMPTS.get(phase_name, "")
    settlement_prompt = SETTLEMENT_GATE_PROMPT if has_pending_action else ""
    return task_prompt + stage_prompt + settlement_prompt


def available_tool_catalog(*, pending_identity: bool) -> List[Dict[str, Any]]:
    return [dict(item) for item in TOOL_CATALOG]
