"""Strict Qwen main-turn response schema and validation helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence

VALID_OUTCOMES = {
    "not_applicable", "changed", "no_visible_change", "uncertain",
}

BUSINESS_EFFECT_KINDS = (
    "state_change", "object_creation", "object_removal", "query_result",
)


def identity_stage_from_context(
    exploration_map: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    """Return the staged identity response mode and its selected Page."""
    context = exploration_map if isinstance(exploration_map, Mapping) else {}
    task = context.get("task")
    phase = str(
        task.get("phase") if isinstance(task, Mapping) else ""
    ).strip().casefold()
    stage = ""
    if phase in {"identify_page", "review_page_identity"}:
        stage = "page"
    elif phase in {"identify_variant", "review_variant_identity"}:
        stage = "variant"
    elif phase == "resolve_app_scope":
        stage = "app_scope"
    selected = context.get("selected_page")
    if not isinstance(selected, Mapping):
        selected = {}
    return (
        stage,
        str(selected.get("name") or "").strip(),
        str(selected.get("identity") or "").strip().casefold(),
    )


def fixed_identity_from_context(
    exploration_map: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Return the reviewed identity for ordinary main-Agent stages."""
    context = exploration_map if isinstance(exploration_map, Mapping) else {}
    task = context.get("task")
    phase = str(
        task.get("phase") if isinstance(task, Mapping) else ""
    ).strip().casefold()
    if phase in {
        "identify_page", "identify_variant", "review_page_identity",
        "review_variant_identity", "review_identity", "resolve_app_scope",
    } or context.get("pending_action"):
        return "", ""
    page_name = str(context.get("current_page") or "").strip()
    variant_name = str(context.get("current_variant") or "").strip()
    if not page_name or not variant_name:
        return "", ""
    return page_name, variant_name


_BBOX_SCHEMA = {"anyOf": [{"type": "array", "items": {"type": "number"},
                            "minItems": 4, "maxItems": 4}, {"type": "null"}]}
_ENTRY_OCCURRENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string"},
        "bbox_1000": _BBOX_SCHEMA,
    },
    "required": ["target"],
    "additionalProperties": False,
}
_NEW_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": (
                "当前截图中实际可见、可指向的语义控件名；包含区分功能"
                "所需的最短上下文，不要只抄写无语义图标或通用标签，"
                "也不要逐项枚举重复内容实例。"
            ),
        },
        "operation": {
            "type": "string",
            "description": (
                "简短、稳定地描述用户做什么；不要写控件坐标或用当前"
                "内容实例、参数值命名。"
            ),
        },
        "subject": {
            "type": "string",
            "description": (
                "可选的可读功能对象说明；只帮助描述，不参与入口身份。"
            ),
        },
        "control_type": {
            "type": "string", "enum": ["control", "input"],
            "description": (
                "只有当前截图中已经可直接输入文字、最终动作需要 "
                "input_text 的字段才使用 input；需要先点击才能显露输入框"
                "的目标仍是 control，其余目标省略或使用 control。"
            ),
        },
    },
    "required": ["target", "operation"],
    "additionalProperties": False,
}
_PAGE_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Stable natural-language Region name that distinguishes its "
                "main function from nearby Regions; do not name it from a "
                "generic layout slot, position, sequence, or changing value."
            ),
        },
        "summary": {"type": "string", "minLength": 1},
        "survey_memory": {
            "type": "string",
            "description": (
                "该区域的简短累计调查记忆：记录已看清的组件关系、仍待"
                "验证的问题和必要的观察轨迹；不要重复正式操作账本。"
            ),
        },
        "coverage_complete": {"type": "boolean"},
        "same_group_as": {
            "type": "string",
            "description": (
                "For a repeated independently stateful Region instance, name "
                "an earlier Region in this same update that represents the "
                "same reusable function; otherwise omit it."
            ),
        },
        "split_from_group": {
            "type": "boolean",
            "description": (
                "True only when the latest screenshot visibly conflicts with "
                "this existing repeated-instance grouping. The existing Region "
                "Reviewer must accept the revised partition before the framework "
                "detaches and reopens inferred work."
            ),
        },
        "entries": {
            "type": "array",
            "items": _NEW_ENTRY_SCHEMA,
            "description": (
                "该区域中当前可见、安全、不同质且对理解或执行用户命令"
                "有意义的操作；是否需要真实探索由入口复核器另行分类。"
                "实例或参数值不同不自动形成不同操作。每项用 target 提供"
                "一个代表目标，框架自动绑定到父区域。"
            ),
        },
    },
    "required": ["name", "summary", "coverage_complete", "entries"],
    "additionalProperties": False,
}
_PAGE_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array", "items": _PAGE_REGION_SCHEMA,
        },
        "entry_resolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_name": {"type": "string"},
                    "operation": {"type": "string"},
                    "target": {"type": "string"},
                    "decision": {
                        "type": "string", "enum": ["keep", "drop"],
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": [
                    "region_name", "operation", "target", "decision", "reason",
                ],
                "additionalProperties": False,
            },
            "description": (
                "仅在历史中存在入口争议时填写。对每个争议候选恰好给出"
                "一条保留或删除结论和具体理由；不能靠从 regions.entries "
                "省略候选来表示删除。"
            ),
        },
    },
    "required": ["regions"],
    "additionalProperties": False,
}
_ENTRY_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "independent_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_name": {"type": "string"},
                    "target": {"type": "string"},
                    "operation": {"type": "string"},
                    "subject": {"type": "string"},
                    "control_type": {
                        "type": "string", "enum": ["control", "input"],
                    },
                    "equivalent_to_entry_id": {
                        "type": "string",
                        "description": (
                            "Exact shared_region_entries entry_id when this "
                            "visible target has the same operation and semantic "
                            "control meaning in the active context."
                        ),
                    },
                    "equivalence_reason": {
                        "type": "string",
                        "description": (
                            "Concrete visible role and function correspondence; "
                            "required when equivalent_to_entry_id is non-empty."
                        ),
                    },
                },
                "required": [
                    "region_name", "target", "operation",
                ],
                "additionalProperties": False,
            },
            "description": (
                "被审核区域中所有当前可见、安全、不同质，且其直接结果能"
                "显露新功能表面、改变其他区域结果或解决明确交互歧义的"
                "操作。既包含仍成立的原候选，也包含候选漏报的操作；漏报"
                "项必须使用已有审核区域名。浅显但有命令价值的操作写入"
                "record_only_entries；字段、参数值或增减方向不同不算不同质；重复内容实例"
                "只保留一个代表目标，不同意图或不同结果保持为不同操作。"
            ),
        },
        "non_task_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_name": {"type": "string"},
                    "operation": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["region_name", "operation", "target"],
                "additionalProperties": False,
            },
            "description": (
                "Every original candidate that is visible enough to judge but "
                "has no command-relevant operation semantics, or is static, "
                "decorative or external. A useful shallow, unsafe, irreversible "
                "or externally consequential "
                "operation is record-only; a useful temporarily unavailable "
                "candidate is deferred. Use the exact original "
                "Region, operation and target; do not add screenshot controls that the "
                "main Agent did not propose."
            ),
        },
        "record_only_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_name": {"type": "string"},
                    "target": {"type": "string"},
                    "operation": {"type": "string"},
                    "subject": {"type": "string"},
                    "control_type": {
                        "type": "string", "enum": ["control", "input"],
                    },
                },
                "required": [
                    "region_name", "target", "operation",
                ],
                "additionalProperties": False,
            },
            "description": (
                "Visible command-relevant operations whose semantics should "
                "remain in the formal operation inventory, but whose direct "
                "effect is already clear enough that a dedicated traversal "
                "task would add little structural evidence. These are observed "
                "operations, not verified effects or routes. Recording an "
                "unsafe, irreversible or externally consequential operation "
                "does not authorize its execution."
            ),
        },
        "deferred_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_name": {"type": "string"},
                    "target": {"type": "string"},
                    "operation": {"type": "string"},
                    "subject": {"type": "string"},
                    "control_type": {
                        "type": "string", "enum": ["control", "input"],
                    },
                },
                "required": [
                    "region_name", "target", "operation",
                ],
                "additionalProperties": False,
            },
            "description": (
                "Exact pending candidate pairs that cannot be judged from the "
                "current screenshot because the actual control is obscured, "
                "cropped, or visually unclear, or that remain functionally "
                "useful but cannot be executed in the current visible state "
                "until a prerequisite is satisfied. Do not defer candidates that "
                "are visibly auxiliary, dangerous, or window-management controls."
            ),
        },
        "deferred_regions": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Exact names from pending_entry_review.regions whose entry "
                "coverage cannot be checked reliably because that Region is "
                "obscured, cropped, or visually unclear, including when a "
                "covered part of a continuous interactive layout could contain "
                "peer entries. Region coverage is not candidate visibility: "
                "if a foreground surface covers a continuous Region area large "
                "enough to hide a normal control, defer it even when all named "
                "candidates remain visible. Do not defer when the obstruction "
                "is outside the Region or too small to hide a control."
            ),
        },
    },
    "required": [
        "independent_entries", "record_only_entries", "non_task_entries",
        "deferred_entries", "deferred_regions",
    ],
    "additionalProperties": False,
}
ENTRY_REVIEW_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        **deepcopy(_ENTRY_REVIEW_SCHEMA["properties"]),
        "reason_consistent": {
            "type": "boolean",
            "description": (
                "Whether the main Agent's stated reason agrees with the latest "
                "screenshot and the reviewer's keep/drop/defer decisions. Return "
                "false when the reason calls a dropped candidate explorable or "
                "calls a retained candidate non-explorable, or claims complete "
                "coverage for a deferred Region. Keep this true when the main "
                "Agent identified the function correctly and the reviewer only "
                "changes an unavailable candidate from keep to defer."
            ),
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Brief visual and functional justification for the retained, "
                "added, dropped, and deferred entries or Regions."
            ),
        },
        "task_strategy": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240,
            "description": (
                "用一句可执行短计划说明当前探索任务接下来如何推进；"
                "覆盖旧策略，不复述历史或展开长推理。"
            ),
        },
    },
    "required": [
        "independent_entries", "record_only_entries", "non_task_entries",
        "deferred_entries", "deferred_regions", "reason_consistent", "reason",
    ],
    "additionalProperties": False,
}
ENTRY_PRESENCE_REVIEW_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "discovery_presence": {
            "type": "string",
            "enum": ["supported", "unsupported", "uncertain"],
        },
        "current_presence": {
            "type": "string",
            "enum": ["present", "missing", "uncertain"],
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["discovery_presence", "current_presence", "reason"],
    "additionalProperties": False,
}
RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "screen": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Canonical Page-node name for the current functional "
                        "surface, not the most prominent header, app-shell, "
                        "parent-container, or Region label."
                    ),
                },
                "identity": {"type": "string", "enum": [
                    "new", "known", "uncertain"]},
                "variant": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "Stable natural name for the current material "
                                "Variant within this Page."
                            ),
                        },
                        "identity": {
                            "type": "string",
                            "enum": ["new", "known", "uncertain"],
                        },
                        "visible_predicates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Short current-screen facts that distinguish "
                                "this Variant for future re-identification. "
                                "Do not include bbox or click coordinates."
                            ),
                        },
                    },
                    "required": [
                        "name", "identity", "visible_predicates",
                    ],
                    "additionalProperties": False,
                    "description": (
                        "Material operable condition inside the stable Page. "
                        "Do not split scroll, hover, focus, time, passive data, "
                        "temporary obstruction, or ordinary content sections."
                    ),
                },
            },
            "required": ["name", "identity", "variant"],
            "additionalProperties": False,
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Concise natural-language reason for the stage conclusion and "
                "chosen tool or lack of action."
            ),
        },
        "previous_action": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": sorted(VALID_OUTCOMES)},
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Natural-language explanation of the observed result. "
                        "When it differs from the expected result, state the "
                        "most likely contextual cause and visible evidence."
                    ),
                },
                "matches_intent": {
                    "type": "boolean",
                    "description": (
                        "The Reviewer-bound target is fixed. True only when "
                        "the visible result satisfies that pending entry or "
                        "action. During discovery, a coherent immediate "
                        "transition is that target's observed result even when "
                        "the destination was not known or another entry shares "
                        "it. task.page is the before-action source, not a "
                        "required landing Page; do not predict a destination "
                        "from the target name."
                    ),
                },
                "failure_kind": {
                    "anyOf": [
                        {"type": "string", "enum": [
                            "temporarily_unavailable", "not_interactive",
                        ]},
                        {"type": "null"},
                    ],
                    "description": (
                        "Set a non-null value only when the main Agent explicitly "
                        "decides that a Reviewer-confirmed exact entry attempt "
                        "should stop: the real control is temporarily unavailable "
                        "or the target is not interactive. Use null while the "
                        "entry should remain retryable or for other outcomes."
                    ),
                },
                "effects": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "properties": {
                            "scope_type": {
                                "type": "string",
                                "enum": [
                                    "owner_region", "region", "page_mode",
                                    "app_state",
                                ],
                            },
                            "scope_name": {
                                "type": "string", "minLength": 1,
                                "description": (
                                    "Use the dispatched owner name, an exact "
                                    "approved Region name, or a concise observed "
                                    "page-mode/application-state fact name."
                                ),
                            },
                            "change_kind": {
                                "type": "string",
                                "enum": ["structure", "state", "value"],
                            },
                            "before_value": {
                                "type": "string",
                            },
                            "after_value": {
                                "type": "string",
                            },
                            "selected_region_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 64,
                                "description": (
                                    "For page_mode only, exact currently selected "
                                    "known Region names. Omit otherwise."
                                ),
                            },
                        },
                        "required": [
                            "scope_type", "scope_name", "change_kind",
                            "before_value", "after_value",
                        ],
                        "additionalProperties": False,
                    },
                    "description": (
                        "Compact visible effects on known scopes. Report every "
                        "affected known Region; value-only effects do not request "
                        "a structure survey. Page modes and application states "
                        "contain only states actually visible in the attached "
                        "before/after screenshots."
                    ),
                },
                "business_effect": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "effect_kind": {
                                    "type": "string",
                                    "enum": list(BUSINESS_EFFECT_KINDS),
                                    "description": (
                                        "The visible business result produced by "
                                        "the just-settled action."
                                    ),
                                },
                                "region_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": (
                                        "Exact approved Region on the source Page "
                                        "where the changed fact is visible."
                                    ),
                                },
                                "capability_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": (
                                        "Concise user-facing function whose "
                                        "state was visibly changed."
                                    ),
                                },
                                "fact": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": (
                                        "Stable observable property that changed; "
                                        "name the state, not the click target."
                                    ),
                                },
                                "before_value": {
                                    "type": "string",
                                },
                                "after_value": {
                                    "type": "string",
                                },
                                "parameter_bindings": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                    "description": (
                                        "Concrete input or selected values used "
                                        "by this action; use an empty object when "
                                        "the result has no parameter. Names use "
                                        "portable identifiers such as city_query."
                                    ),
                                },
                                "same_operation_entry_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 32,
                                    "description": (
                                        "Exact IDs from pending_action."
                                        "same_region_pending_entries that are "
                                        "the same control-group operation and "
                                        "differ only by parameter value. Omit "
                                        "when none are proven by this action."
                                    ),
                                },
                                "same_operation_reason": {
                                    "type": "string",
                                    "description": (
                                        "Concrete visual reason that the listed "
                                        "entries share this operation template."
                                    ),
                                },
                            },
                            "required": [
                                "effect_kind", "region_name",
                                "capability_name", "fact", "before_value",
                                "after_value", "parameter_bindings",
                            ],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ],
                    "description": (
                        "Observed user-visible business effect in one exact "
                        "approved Region on the source Page, caused by the just-"
                        "settled action. Report a property change, object creation "
                        "or removal, or query result only when its before and after facts "
                        "are both visually grounded. Use null for navigation, "
                        "menus, dialogs, Region reveals, passive or dynamic "
                        "changes, or a hidden or merely expected result."
                    ),
                },
                "visible_effect": {
                    "type": "string",
                    "enum": [
                        "owner_structure", "owner_state", "page_structure",
                        "none", "uncertain",
                    ],
                    "description": (
                        "Scope of the visible result. Use owner_structure only "
                        "when changed controls are confined to the dispatched "
                        "Entry's Region."
                    ),
                },
            },
            "required": [
                "outcome", "reason", "matches_intent", "failure_kind",
                "business_effect",
            ],
            "additionalProperties": False,
        },
        "previous_tool_review": {"anyOf": [{
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": [
                        "accept", "reject", "uncertain"]},
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Natural-language reason for accepting, rejecting, "
                            "or leaving the specialist proposal uncertain."
                        ),
                    },
                },
                "required": ["decision", "reason"],
                "additionalProperties": False,
            }, {"type": "null"}]},
        "page_update": {"anyOf": [_PAGE_UPDATE_SCHEMA, {"type": "null"}]},
        "entry_review": {"anyOf": [_ENTRY_REVIEW_SCHEMA, {"type": "null"}]},
        "action": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "tool_name": {"type": "string"},
                "tool_arguments": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
            "required": ["tool_name", "tool_arguments"],
            "additionalProperties": False,
        },
    },
    "required": ["screen", "reason", "task_strategy", "action"],
    "additionalProperties": False,
}


def response_schema_for_tools(
    tool_catalog: Sequence[Dict[str, Any]],
    *,
    has_previous: bool = False,
    requires_tool_review: bool = False,
    requires_entry_review: bool = False,
    identity_stage: str = "",
    fixed_identity: bool = False,
) -> Dict[str, Any]:
    """Build the smallest state-specific response schema for this turn."""
    variants: List[Dict[str, Any]] = []
    base_action = RESPONSE_SCHEMA["properties"]["action"]
    for item in tool_catalog:
        name = str(item.get("name") or "").strip()
        arguments = item.get("input_schema")
        if not name or not isinstance(arguments, dict):
            continue
        variant = deepcopy(base_action)
        variant["properties"]["tool_name"] = {
            "type": "string", "enum": [name],
        }
        variant["properties"]["tool_arguments"] = deepcopy(arguments)
        if name in {"click", "input_text", "hover", "scroll", "navigate", "gesture"}:
            variant["properties"]["purpose"] = {
                "type": "string",
                "enum": [
                    "navigation", "locating", "entry_attempt",
                    "interruption_recovery", "region_survey",
                    "operation_attempt",
                ],
                "description": "这一步界面动作在当前任务中的实际作用。",
            }
            variant["required"] = [
                "purpose", "tool_name", "tool_arguments",
            ]
        else:
            variant["properties"].pop("purpose", None)
        variants.append(variant)
    if not variants:
        raise ValueError("at least one strict tool schema must be exposed")
    schema = deepcopy(RESPONSE_SCHEMA)
    identity_stage = str(identity_stage or "").strip().casefold()
    if identity_stage == "page":
        schema["properties"]["screen"] = {
            "type": "object",
            "properties": {
                "name": deepcopy(
                    RESPONSE_SCHEMA["properties"]["screen"]["properties"][
                        "name"
                    ]
                ),
                "identity": {"type": "string", "enum": [
                    "new", "known", "uncertain",
                ]},
            },
            "required": ["name", "identity"],
            "additionalProperties": False,
        }
    elif identity_stage == "variant":
        schema["properties"]["screen"] = {
            "type": "object",
            "properties": {
                "variant": deepcopy(
                    RESPONSE_SCHEMA["properties"]["screen"]["properties"][
                        "variant"
                    ]
                ),
            },
            "required": ["variant"],
            "additionalProperties": False,
        }
    elif fixed_identity:
        schema["properties"].pop("screen", None)
    elif identity_stage == "app_scope":
        schema["properties"].pop("screen", None)
    schema["properties"]["action"] = {"anyOf": [*variants, {"type": "null"}]}
    if not has_previous:
        schema["properties"].pop("previous_action", None)
    if not requires_tool_review:
        schema["properties"].pop("previous_tool_review", None)
    if requires_entry_review:
        schema["properties"].pop("page_update", None)
        schema["properties"]["action"] = {"type": "null"}
    else:
        schema["properties"].pop("entry_review", None)
    if identity_stage in {"page", "variant"}:
        schema["properties"].pop("page_update", None)
        schema["properties"].pop("entry_review", None)
    schema["required"] = ["reason", "task_strategy", "action"]
    if not fixed_identity and identity_stage != "app_scope":
        schema["required"].insert(0, "screen")
    if has_previous:
        schema["required"].append("previous_action")
    if requires_tool_review:
        schema["required"].append("previous_tool_review")
    if requires_entry_review:
        schema["required"].append("entry_review")
    return schema


def _require_model_reason(
    payload: Dict[str, Any],
    *,
    role: str,
) -> Dict[str, Any]:
    """Reject a model judgment that gives no human-readable rationale."""
    if not str(payload.get("reason") or "").strip():
        raise RuntimeError(f"{role} returned no non-empty reason")
    return payload
