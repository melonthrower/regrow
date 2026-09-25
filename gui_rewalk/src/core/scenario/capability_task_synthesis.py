"""Build minimal executable tasks from an evidence-backed capability graph."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Mapping, Tuple

from .capability_induction import CAPABILITY_GRAPH_SCHEMA
from .capability_instruction_gen import (
    TASK_ELIGIBLE_VERIFICATION_LEVELS,
    CapabilityRef,
    Instruction,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parameter_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


_COMPOSITION_PROMPT = """你是 GUI 用户任务文案助手。下面的任务骨架已经由框架选定。

要求：
1. 只把每个骨架润色成一条自然、实用的用户指令。
2. 不得增加、删除或替换功能，不得修改参数。
3. 不要写页面导航或点击步骤；如果无法自然表达，instruction 返回空字符串。
4. 只输出 JSON：
{{"instructions":[{{"skeleton_id":"sk001","instruction":"..."}}]}}

任务骨架：
应用：{app_id}
{skeletons}
"""


def _composition_capabilities(
    capability_graph: Mapping[str, Any],
) -> Dict[str, Mapping[str, Any]]:
    if not isinstance(capability_graph, Mapping):
        raise ValueError("capability graph must be an object")
    if capability_graph.get("schema_version") != CAPABILITY_GRAPH_SCHEMA:
        raise ValueError("unsupported capability graph schema")
    raw_capabilities = capability_graph.get("capabilities")
    if not isinstance(raw_capabilities, list):
        raise ValueError("capability graph capabilities must be a list")
    by_id: Dict[str, Mapping[str, Any]] = {}
    for raw in raw_capabilities:
        if not isinstance(raw, Mapping):
            raise ValueError("capability graph capabilities must contain objects")
        capability_id = _text(raw.get("capability_id"))
        if not capability_id or capability_id in by_id:
            raise ValueError(
                "capability graph needs unique non-empty capability_id values")
        recipe = raw.get("execution_recipe")
        if _text(raw.get("name")) and isinstance(recipe, list) and recipe:
            by_id[capability_id] = raw
    return by_id


def _compact_capability_cards(
    capabilities: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    for capability_id, capability in capabilities.items():
        surface = next((
            item for item in (capability.get("entry_surfaces") or [])
            if isinstance(item, Mapping)
        ), {})
        card: Dict[str, Any] = {
            "capability_id": capability_id,
            "name": _text(capability.get("name")),
        }
        page_id = _text(surface.get("page_id"))
        if page_id:
            card["page"] = page_id
        defaults, _, _ = _parameter_defaults(capability)
        if defaults:
            card["parameter_examples"] = _parameter_examples(
                capability, defaults)[:3]
        elif _candidate_example(capability):
            card["observed_example"] = _candidate_example(capability)
        outcome = _text(capability.get("predicate_description"))
        if outcome:
            card["outcome"] = outcome
        cards.append(card)
    return cards


def _candidate_example(capability: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = capability.get("parameter_candidates")
    if not isinstance(candidates, Mapping) or not candidates:
        return {}
    if not all(isinstance(values, list) and len(values) == 1
               for values in candidates.values()):
        return {}
    return {
        str(name): copy.deepcopy(values[0])
        for name, values in candidates.items()
    }


def _validated_selection(
    raw: Mapping[str, Any],
    capabilities: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    capability_id = _text(raw.get("capability_id"))
    capability = capabilities.get(capability_id)
    if capability is None:
        raise ValueError(f"unknown capability_id {capability_id!r}")
    params = raw.get("params") or {}
    if not isinstance(params, Mapping):
        raise ValueError(f"capability {capability_id!r} params must be an object")
    params = {str(key): copy.deepcopy(value) for key, value in params.items()}
    defaults, _, _ = _parameter_defaults(capability)
    examples = _parameter_examples(capability, defaults)
    if set(params) != set(defaults) or _stable(params) not in {
            _stable(item) for item in examples}:
        raise ValueError(
            f"capability {capability_id!r} params are not an observed example")
    return {"capability_id": capability_id, "params": params}


def _instruction_skeletons(
    capabilities: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    skeletons: List[Dict[str, Any]] = []
    for card in _compact_capability_cards(capabilities):
        capability = capabilities[card["capability_id"]]
        defaults, _, _ = _parameter_defaults(capability)
        params = _parameter_examples(capability, defaults)[0]
        selection = _validated_selection({
            "capability_id": card["capability_id"],
            "params": params,
        }, capabilities)
        visible_card = dict(card)
        visible_card["params"] = selection["params"]
        skeletons.append({
            "skeleton_id": f"sk{len(skeletons) + 1:03d}",
            "capabilities": [visible_card],
            "selections": [selection],
        })
    return skeletons


def compose_instruction_drafts(
    capability_graph: Mapping[str, Any],
    agent: Any,
    *,
    n: int = 6,
    start: int = 0,
) -> List[Dict[str, Any]]:
    """Let an Agent polish framework-selected, bounded task skeletons."""
    capabilities = _composition_capabilities(capability_graph)
    if not capabilities:
        return []
    limit = max(1, int(n))
    start = max(0, int(start))
    skeletons = _instruction_skeletons(capabilities)[start:start + limit]
    if not skeletons:
        return []
    visible_skeletons = [{
        "skeleton_id": item["skeleton_id"],
        "capabilities": item["capabilities"],
    } for item in skeletons]
    prompt = _COMPOSITION_PROMPT.format(
        app_id=_text(capability_graph.get("app_id")),
        skeletons=json.dumps(
            visible_skeletons, ensure_ascii=False, separators=(",", ":")),
    )
    try:
        response, *_ = agent.predict_mm(prompt, [])
        raw = str(response or "").strip()
        match = re.search(r"\{.*\}", raw, re.S)
        payload = json.loads(match.group(0) if match else raw)
    except Exception:
        return []
    raw_instructions = payload.get("instructions")
    if not isinstance(raw_instructions, list):
        return []
    skeleton_by_id = {item["skeleton_id"]: item for item in skeletons}
    drafts: List[Dict[str, Any]] = []
    seen = set()
    for raw_instruction in raw_instructions:
        if not isinstance(raw_instruction, Mapping):
            continue
        skeleton_id = _text(raw_instruction.get("skeleton_id"))
        instruction = _text(raw_instruction.get("instruction"))
        skeleton = skeleton_by_id.get(skeleton_id)
        if not instruction or skeleton is None or skeleton_id in seen:
            continue
        seen.add(skeleton_id)
        drafts.append({
            "instruction": instruction,
            "capabilities": copy.deepcopy(skeleton["selections"]),
        })
    return drafts


def _bind_recipe_value(value: Any, params: Mapping[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    for name, replacement in params.items():
        value = value.replace(f"{{{{{name}}}}}", _parameter_text(replacement))
    return value


def _recipe_step_text(
    raw: Mapping[str, Any], params: Mapping[str, Any],
) -> str:
    action = _text(
        raw.get("action_type") or raw.get("kind") or raw.get("action")
    ).upper()
    selector = raw.get("selector")
    target = ""
    if isinstance(selector, Mapping):
        target = _text(
            selector.get("element_label")
            or selector.get("description")
            or selector.get("target"))
    parameters = raw.get("parameters")
    text_value = ""
    if isinstance(parameters, Mapping):
        text_value = _text(_bind_recipe_value(parameters.get("text"), params))
    if action in {"TYPE", "TYPING", "INPUT_TEXT"} and text_value:
        return f"{action} {text_value}" + (f" in {target}" if target else "")
    return " ".join(part for part in (action, target) if part)


def selected_capability_context(
    capability_graph: Mapping[str, Any],
    selections: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return concise successful recipes only for the selected capabilities."""
    capabilities = _composition_capabilities(capability_graph)
    context: List[Dict[str, Any]] = []
    for raw in selections:
        selection = _validated_selection(raw, capabilities)
        capability = capabilities[selection["capability_id"]]
        recipe = capability.get("execution_recipe") or []
        render_params = selection["params"] or _candidate_example(capability)
        steps = [
            _recipe_step_text(step, render_params)
            for step in recipe if isinstance(step, Mapping)
        ]
        context.append({
            "capability_id": selection["capability_id"],
            "name": _text(capability.get("name")),
            "params": selection["params"],
            "steps": [step for step in steps if step],
            "success": (
                _text(capability.get("predicate_description"))
                or _text(capability.get("name"))
            ),
        })
    return context


def _entry_surface(capability: Mapping[str, Any]) -> Dict[str, Any]:
    surfaces = capability.get("entry_surfaces")
    if not isinstance(surfaces, list):
        raise ValueError("task-eligible capability entry_surfaces must be a list")
    for raw in surfaces:
        if isinstance(raw, Mapping) and _text(raw.get("state_id")):
            return dict(raw)
    raise ValueError("task-eligible capability needs an entry surface with state_id")


def _parameter_defaults(capability: Mapping[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    raw_parameters = capability.get("parameters") or []
    if not isinstance(raw_parameters, list):
        raise ValueError("task-eligible capability parameters must be a list")
    domains: Dict[str, List[Any]] = {}
    for raw in raw_parameters:
        if not isinstance(raw, Mapping):
            raise ValueError("task-eligible capability parameters must contain objects")
        name = _text(raw.get("name"))
        domain = raw.get("domain")
        values = domain.get("values") if isinstance(domain, Mapping) else None
        if not name or name in domains or not isinstance(values, list) or not values:
            raise ValueError(
                "each task-eligible parameter needs a unique name and non-empty domain.values")
        domains[name] = list(values)
    if not domains:
        return {}, "", ""
    if len(domains) == 1:
        slot, values = next(iter(domains.items()))
        value = values[0]
        return {slot: value}, slot, _parameter_text(value)

    raw_examples = capability.get("parameter_examples")
    if not isinstance(raw_examples, list) or not raw_examples:
        raise ValueError(
            "multi-parameter capability requires non-empty parameter_examples")
    parameter_names = set(domains)
    examples: List[Dict[str, Any]] = []
    for raw in raw_examples:
        if (not isinstance(raw, Mapping)
                or {str(key) for key in raw} != parameter_names):
            raise ValueError(
                "parameter_examples must bind every declared parameter exactly")
        example = {str(key): copy.deepcopy(value) for key, value in raw.items()}
        if any(
            _stable(example[name]) not in {
                _stable(value) for value in domains[name]}
            for name in parameter_names
        ):
            raise ValueError("parameter_examples contains a value outside its domain")
        examples.append(example)
    return examples[0], "", ""


def _parameter_examples(
    capability: Mapping[str, Any], fallback: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    raw_examples = capability.get("parameter_examples")
    if raw_examples is None:
        if len(fallback) == 1:
            name = next(iter(fallback))
            values = next((
                item.get("domain", {}).get("values")
                for item in capability.get("parameters") or []
                if isinstance(item, Mapping)
                and _text(item.get("name")) == name
                and isinstance(item.get("domain"), Mapping)
            ), None)
            if isinstance(values, list) and values:
                return [
                    {name: copy.deepcopy(value)} for value in values]
        return [dict(fallback)]
    if not isinstance(raw_examples, list) or not raw_examples:
        raise ValueError("parameter_examples must be a non-empty list")
    expected = set(fallback)
    domains = {
        _text(item.get("name")): item.get("domain", {}).get("values")
        for item in capability.get("parameters") or []
        if isinstance(item, Mapping) and isinstance(item.get("domain"), Mapping)
    }
    examples: List[Dict[str, Any]] = []
    for raw in raw_examples:
        if (not isinstance(raw, Mapping)
                or {str(key) for key in raw} != expected):
            raise ValueError(
                "parameter_examples must bind every declared parameter exactly")
        example = {str(key): copy.deepcopy(value) for key, value in raw.items()}
        if any(
            not isinstance(domains.get(name), list)
            or _stable(value) not in {_stable(item) for item in domains[name]}
            for name, value in example.items()
        ):
            raise ValueError("parameter_examples contains a value outside its domain")
        examples.append(example)
    return examples


def _instruction_text(name: str, params: Mapping[str, Any]) -> str:
    if not params:
        return name
    assignments = "，".join(
        f"{key}={_stable(value)}" for key, value in params.items())
    return f"{name}（{assignments}）"


def _apply_params(ref: CapabilityRef, params: Mapping[str, Any]) -> CapabilityRef:
    result = copy.deepcopy(ref)
    result.params = dict(params)
    if len(result.params) == 1:
        result.slot, raw_value = next(iter(result.params.items()))
        result.value = _parameter_text(raw_value)
        result.param_type = "enum"
    elif result.params:
        result.slot = ""
        result.value = ""
        result.param_type = "enum"
    return result


def synthesize_single_capability_instructions(
    capability_graph: Mapping[str, Any],
    *,
    app_id: str = "",
) -> List[Instruction]:
    """Return one deterministic task per effect-verified/composable capability.

    Parameterized tasks choose one complete tuple observed in real evidence.
    """
    if not isinstance(capability_graph, Mapping):
        raise ValueError("capability graph must be an object")
    if capability_graph.get("schema_version") != CAPABILITY_GRAPH_SCHEMA:
        raise ValueError("unsupported capability graph schema")
    graph_app_id = _text(capability_graph.get("app_id"))
    chosen_app_id = _text(app_id) or graph_app_id
    if not chosen_app_id:
        raise ValueError("capability graph needs app_id")
    if graph_app_id and app_id and graph_app_id != _text(app_id):
        raise ValueError("requested app_id conflicts with capability graph")
    raw_capabilities = capability_graph.get("capabilities")
    if not isinstance(raw_capabilities, list):
        raise ValueError("capability graph capabilities must be a list")

    seen_ids = set()
    instructions: List[Instruction] = []
    for raw in raw_capabilities:
        if not isinstance(raw, Mapping):
            raise ValueError("capability graph capabilities must contain objects")
        capability_id = _text(raw.get("capability_id"))
        if not capability_id or capability_id in seen_ids:
            raise ValueError("capability graph needs unique non-empty capability_id values")
        seen_ids.add(capability_id)
        verification_level = _text(raw.get("verification_level")).casefold()
        if verification_level not in TASK_ELIGIBLE_VERIFICATION_LEVELS:
            continue
        name = _text(raw.get("name"))
        if not name:
            raise ValueError("task-eligible capability needs a name")
        surface = _entry_surface(raw)
        recipe = raw.get("execution_recipe")
        if not isinstance(recipe, list) or not recipe or not all(
                isinstance(step, Mapping) for step in recipe):
            raise ValueError("task-eligible capability needs a non-empty execution_recipe")
        params, slot, value = _parameter_defaults(raw)
        node_id = _text(surface.get("state_id"))
        ref = CapabilityRef(
            node_id=node_id,
            target_node="",
            page_name=_text(surface.get("page_id")) or node_id,
            name=name,
            param_type="enum" if params else "none",
            slot=slot,
            value=value,
            runtime=False,
            app_id=chosen_app_id,
            capability_id=capability_id,
            requires=[dict(item) for item in (raw.get("preconditions") or [])
                      if isinstance(item, Mapping)],
            effects=[dict(item) for item in (raw.get("effects") or [])
                     if isinstance(item, Mapping)],
            success_predicate=raw.get("success_predicate") or "",
            execution_recipe=[dict(step) for step in recipe],
            availability_status=("verified" if verification_level in {
                "effect_verified", "composable"} else verification_level),
            verification_level=verification_level,
            action_steps=len(recipe),
            params=params,
        )
        instructions.append(Instruction(
            instruction_id=f"CAP{len(instructions) + 1:03d}",
            type="single",
            instruction=_instruction_text(name, params),
            capability_refs=[ref],
            params={key: _parameter_text(value) for key, value in params.items()},
            apps_involved=[chosen_app_id],
            fixed_order=True,
        ))
    return instructions


def synthesize_cleanup_cycle_instructions(
    capability_graph: Mapping[str, Any],
    *,
    app_id: str = "",
) -> List[Instruction]:
    """Build create-then-cleanup tasks only from verified cleanup relations."""
    singles = synthesize_single_capability_instructions(
        capability_graph, app_id=app_id)
    refs = {
        item.capability_refs[0].capability_id:
        copy.deepcopy(item.capability_refs[0])
        for item in singles
        if item.capability_refs[0].verification_level in {"effect_verified", "composable"}
    }
    raw_capabilities = capability_graph.get("capabilities") or []
    capabilities = {
        _text(item.get("capability_id")): item
        for item in raw_capabilities if isinstance(item, Mapping)
    }
    relations = capability_graph.get("relations")
    if not isinstance(relations, list):
        raise ValueError("capability graph relations must be a list")
    seen_ids: set[str] = set()
    instructions: List[Instruction] = []
    for raw in relations:
        if not isinstance(raw, Mapping):
            raise ValueError("capability graph relations must contain objects")
        if _text(raw.get("relation_type")) != "cleanup_cycle":
            continue
        relation_id = _text(raw.get("relation_id"))
        if not relation_id or relation_id in seen_ids:
            raise ValueError("cleanup relations need unique non-empty relation_id values")
        seen_ids.add(relation_id)
        source_id = _text(raw.get("source_capability_id"))
        cleanup_id = _text(raw.get("cleanup_capability_id"))
        if source_id not in refs or cleanup_id not in refs:
            raise ValueError(
                f"cleanup relation {relation_id!r} references a "
                "non-task-eligible capability")
        source = copy.deepcopy(refs[source_id])
        cleanup = copy.deepcopy(refs[cleanup_id])
        links = raw.get("parameter_links") or []
        if not isinstance(links, list):
            raise ValueError(
                f"cleanup relation {relation_id!r} parameter_links must be a list")
        link_specs = []
        for link in links:
            if not isinstance(link, Mapping):
                raise ValueError("cleanup relation parameter_links must contain objects")
            source_name = _text(link.get("source_parameter"))
            cleanup_name = _text(link.get("cleanup_parameter"))
            values = link.get("values")
            if (not source_name or not cleanup_name
                    or not isinstance(values, list) or not values):
                raise ValueError(
                    f"cleanup relation {relation_id!r} has an incomplete parameter link")
            source_domain = next((
                item.get("domain", {}).get("values")
                for item in capabilities[source_id].get("parameters") or []
                if isinstance(item, Mapping)
                and _text(item.get("name")) == source_name
                and isinstance(item.get("domain"), Mapping)
            ), None)
            cleanup_domain = next((
                item.get("domain", {}).get("values")
                for item in capabilities[cleanup_id].get("parameters") or []
                if isinstance(item, Mapping)
                and _text(item.get("name")) == cleanup_name
                and isinstance(item.get("domain"), Mapping)
            ), None)
            if (not isinstance(source_domain, list)
                    or not isinstance(cleanup_domain, list)):
                raise ValueError(
                    f"cleanup relation {relation_id!r} references an "
                    "undeclared parameter")
            allowed_values = {_stable(value) for value in values}
            source_values = {_stable(value) for value in source_domain}
            cleanup_values = {_stable(value) for value in cleanup_domain}
            if (not allowed_values.issubset(source_values)
                    or not allowed_values.issubset(cleanup_values)):
                raise ValueError(
                    f"cleanup relation {relation_id!r} value is outside "
                    "a confirmed parameter domain")
            link_specs.append((
                source_name,
                cleanup_name,
                allowed_values,
                source_values,
                cleanup_values,
            ))

        source_examples = _parameter_examples(
            capabilities[source_id], source.params)
        cleanup_examples = _parameter_examples(
            capabilities[cleanup_id], cleanup.params)
        chosen: Tuple[Dict[str, Any], Dict[str, Any]] | None = None
        for source_example in source_examples:
            candidate_cleanup = dict(cleanup.params)
            valid = True
            for (source_name, cleanup_name, allowed_values,
                 source_domain, cleanup_domain) in link_specs:
                if source_name not in source_example:
                    valid = False
                    break
                value = source_example[source_name]
                encoded = _stable(value)
                if (encoded not in allowed_values
                        or encoded not in source_domain
                        or encoded not in cleanup_domain):
                    valid = False
                    break
                candidate_cleanup[cleanup_name] = copy.deepcopy(value)
            if (valid and any(
                    _stable(candidate_cleanup) == _stable(example)
                    for example in cleanup_examples)):
                chosen = (dict(source_example), candidate_cleanup)
                break
        if chosen is None:
            raise ValueError(
                f"cleanup relation {relation_id!r} has no jointly observed "
                "parameter assignment")
        source_params, cleanup_params = chosen
        source = _apply_params(source, source_params)
        cleanup = _apply_params(cleanup, cleanup_params)
        cleanup.depends_on = list(dict.fromkeys([
            *cleanup.depends_on, source.capability_id]))
        params = {
            key: _parameter_text(value)
            for key, value in source.params.items()
        }
        instructions.append(Instruction(
            instruction_id=relation_id,
            type="cleanup_cycle",
            instruction=(
                f"{_instruction_text(source.name, source.params)}，"
                f"确认效果后执行{cleanup.name}恢复初始状态"
            ),
            capability_refs=[source, cleanup],
            params=params,
            apps_involved=[source.app_id],
            fixed_order=True,
        ))
    return instructions

