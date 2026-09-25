"""Declarative on-demand tools exposed to the target exploration Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import io
from typing import Any, Callable, Dict, List, Tuple

from PIL import Image


class EvidenceMode(str, Enum):
    """Screenshot/evidence bundle required by one tool invocation."""

    NONE = "none"
    CURRENT_FULL = "current_full"
    BEFORE_AFTER = "before_after"
    CURRENT_AND_REGION = "current_and_region"


class ToolEffect(str, Enum):
    """State boundary used by the dispatcher and debug ledger."""

    READ_ONLY = "read_only"
    PERCEPTION_WRITE = "perception_write"
    UI_ACTION = "ui_action"


@dataclass(frozen=True)
class ToolContext:
    host: Any
    state_id: str
    observation: Dict[str, Any]
    page_graph: Dict[str, Any]
    region_directory: Dict[str, Any]
    task: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceBundle:
    """Images stay inside the tool boundary and are never echoed to the Agent."""

    images: Dict[str, bytes] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    status: str
    tool: str
    data: Dict[str, Any] = field(default_factory=dict)
    observation_changed: bool = False
    ledger_changed: bool = False
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "tool": self.tool,
            "data": dict(self.data),
            "observation_changed": self.observation_changed,
            "ledger_changed": self.ledger_changed,
            "message": self.message,
        }


ToolHandler = Callable[[ToolContext, Dict[str, Any], EvidenceBundle], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    argument_schema: Dict[str, Dict[str, Any]]
    evidence_mode: EvidenceMode
    effect: ToolEffect
    handler: ToolHandler

    def for_prompt(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": {
                name: str(rule.get("example") or rule.get("type") or "")
                for name, rule in self.argument_schema.items()
            },
            "evidence_mode": self.evidence_mode.value,
            "effect": self.effect.value,
        }


def _element_row(element) -> Dict[str, Any]:
    return {
        "target": str(getattr(element, "name", "") or ""),
        "status": str(
            getattr(element, "exploration_status", "") or "pending"),
    }


def _region_row(data: Dict[str, Any], block: Dict[str, Any]) -> Dict[str, Any]:
    region_id = str(block.get("region_id") or "")
    status = dict((data.get("region_observation") or {}).get(region_id) or {})
    all_controls = [
        _element_row(element)
        for element in data.get("elements") or []
        if str(getattr(element, "region_id", "") or "") == region_id
    ]
    controls = all_controls[:20]
    return {
        "name": str(block.get("role") or ""),
        "description": str(block.get("description") or ""),
        "bbox_1000": block.get("viewport_bbox_1000") or block.get("bbox_1000"),
        "scrollable": block.get("scrollable"),
        "observation_status": str(
            status.get("status") or block.get("observation_status") or "pending"),
        "controls": controls,
        "controls_omitted": max(0, len(all_controls) - len(controls)),
    }


def current_region_directory(host, state_id: str) -> Dict[str, Any]:
    """Return prompt-local Region refs plus a private stable-id mapping."""
    data = getattr(host, "_state_data", {}).get(str(state_id)) or {}
    rows = []
    refs = {}
    for index, block in enumerate(data.get("semantic_blocks") or []):
        if not isinstance(block, dict):
            continue
        region_ref = f"r{index}"
        region_id = str(block.get("region_id") or "")
        row = {"region_ref": region_ref, **_region_row(data, block)}
        rows.append(row)
        if region_id:
            refs[region_ref] = region_id
    return {"regions": rows, "region_ids": refs}


def _page_summary(host, state_ids: List[str]) -> Dict[str, Any]:
    names = []
    regions = []
    seen_regions = set()
    for state_id in state_ids:
        data = getattr(host, "_state_data", {}).get(str(state_id)) or {}
        name = str(data.get("page_name") or "")
        if name and name not in names:
            names.append(name)
        for block in data.get("semantic_blocks") or []:
            if not isinstance(block, dict):
                continue
            region_id = str(block.get("region_id") or "")
            key = region_id or str(block.get("role") or "")
            if not key or key in seen_regions:
                continue
            seen_regions.add(key)
            regions.append(_region_row(data, block))
    return {
        "page_name": names[0] if names else "Unknown page",
        "regions": regions,
    }


def _route_summary(host, current_state_id: str,
                   destination_state_ids: List[str]) -> Dict[str, Any]:
    best = None
    for destination in destination_state_ids:
        route = host.router.plan_route(str(current_state_id), str(destination))
        if route is None:
            continue
        if best is None or len(route) < len(best):
            best = list(route)
    if best is None:
        return {"status": "no_verified_route", "steps": []}
    state_data = getattr(host, "_state_data", {})
    return {
        "status": "already_there" if not best else "verified_route",
        "steps": [{
            "target": str(step.get("name") or ""),
            "area": str(step.get("region") or ""),
            "reaches": str((state_data.get(str(step.get("dst") or "")) or {}).get(
                "page_name") or step.get("dst") or ""),
        } for step in best],
    }


def _crop_region(screenshot: bytes, bbox_1000) -> bytes:
    if not isinstance(bbox_1000, list) or len(bbox_1000) != 4:
        return b""
    try:
        with Image.open(io.BytesIO(screenshot)) as image:
            x0, y0, x1, y1 = [float(value) for value in bbox_1000]
            if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
                return b""
            box = (
                round(x0 * image.width / 1000.0),
                round(y0 * image.height / 1000.0),
                round(x1 * image.width / 1000.0),
                round(y1 * image.height / 1000.0),
            )
            crop = image.crop(box)
            payload = io.BytesIO()
            crop.save(payload, format="PNG")
            return payload.getvalue()
    except (OSError, TypeError, ValueError):
        return b""


def _validate_arguments(spec: ToolSpec,
                        arguments: Any) -> Tuple[Dict[str, Any], str]:
    if not isinstance(arguments, dict):
        return {}, "tool arguments must be an object"
    unknown = sorted(set(arguments) - set(spec.argument_schema))
    if unknown:
        return {}, f"unknown arguments for {spec.name}: {unknown}"
    normalized = {}
    for name, rule in spec.argument_schema.items():
        value = arguments.get(name)
        if rule.get("required") and value in (None, ""):
            return {}, f"missing required argument: {name}"
        if value is None:
            continue
        if rule.get("type") == "string" and not isinstance(value, str):
            return {}, f"argument {name} must be a string"
        normalized[name] = value
    return normalized, ""


def _build_evidence(spec: ToolSpec, context: ToolContext,
                    arguments: Dict[str, Any]) -> Tuple[EvidenceBundle, str]:
    if spec.evidence_mode is EvidenceMode.NONE:
        return EvidenceBundle(), ""
    screenshot = (context.observation or {}).get("screenshot")
    if not isinstance(screenshot, bytes) or not screenshot:
        return EvidenceBundle(), "current screenshot unavailable"
    images = {"current_full": screenshot}
    metadata: Dict[str, Any] = {"state_id": str(context.state_id)}
    if spec.evidence_mode is EvidenceMode.CURRENT_AND_REGION:
        region_ref = str(arguments.get("region_ref") or "")
        region_id = str((context.region_directory.get(
            "region_ids") or {}).get(region_ref) or "")
        if not region_id:
            return EvidenceBundle(), f"unknown current region_ref: {region_ref}"
        row = next((
            item for item in context.region_directory.get("regions") or []
            if str(item.get("region_ref") or "") == region_ref
        ), {})
        metadata.update({"region_ref": region_ref, "region_id": region_id})
        region_crop = _crop_region(screenshot, row.get("bbox_1000"))
        if region_crop:
            images["region_crop"] = region_crop
    elif spec.evidence_mode is EvidenceMode.BEFORE_AFTER:
        provider = getattr(context.host, "_agent_tool_before_after", None)
        if not callable(provider):
            return EvidenceBundle(), "before/after evidence provider unavailable"
        pair = provider(arguments, context.task)
        if not isinstance(pair, dict) or not pair.get("before") or not pair.get(
                "after"):
            return EvidenceBundle(), "before/after screenshots unavailable"
        images = {"before": pair["before"], "after": pair["after"]}
        metadata.update(dict(pair.get("metadata") or {}))
    return EvidenceBundle(images=images, metadata=metadata), ""


def _recall_page(context: ToolContext, arguments: Dict[str, Any],
                 _evidence: EvidenceBundle) -> ToolResult:
    page_ref = str(arguments.get("page_ref") or "")
    state_ids = list((context.page_graph.get(
        "state_ids_by_ref") or {}).get(page_ref) or [])
    if not state_ids:
        return ToolResult(
            "error", "recall_page", message=f"unknown page_ref: {page_ref}")
    return ToolResult(
        "ok", "recall_page",
        data={"page_ref": page_ref, **_page_summary(context.host, state_ids)},
    )


def _find_route(context: ToolContext, arguments: Dict[str, Any],
                _evidence: EvidenceBundle) -> ToolResult:
    page_ref = str(arguments.get("page_ref") or "")
    state_ids = list((context.page_graph.get(
        "state_ids_by_ref") or {}).get(page_ref) or [])
    if not state_ids:
        return ToolResult(
            "error", "find_route", message=f"unknown page_ref: {page_ref}")
    return ToolResult(
        "ok", "find_route",
        data={
            "page_ref": page_ref,
            **_route_summary(context.host, context.state_id, state_ids),
        },
    )


def _inspect_region(context: ToolContext, arguments: Dict[str, Any],
                    evidence: EvidenceBundle) -> ToolResult:
    region_ref = str(arguments.get("region_ref") or "")
    region_id = str(evidence.metadata.get("region_id") or "")
    from .region_observation import observe_next_region
    outcome = observe_next_region(
        context.host, context.state_id, context.observation,
        region_id=region_id,
    )
    refreshed = current_region_directory(context.host, context.state_id)
    row = next((
        item for item in refreshed.get("regions") or []
        if str((refreshed.get("region_ids") or {}).get(
            str(item.get("region_ref") or "")) or "") == region_id
    ), {})
    status = "ok" if outcome in {
        "updated", "already_complete", "none"} else "incomplete"
    return ToolResult(
        status, "inspect_region",
        data={
            "region_ref": region_ref,
            "outcome": outcome,
            "region": row,
            "evidence_images": sorted(evidence.images),
        },
        ledger_changed=(outcome == "updated"),
        message=("Region observation completed" if outcome == "updated" else ""),
    )


TOOLS: Dict[str, ToolSpec] = {
    "recall_page": ToolSpec(
        name="recall_page",
        description=(
            "Read the Regions and registered controls of one known page; "
            "do not execute a GUI action."
        ),
        argument_schema={
            "page_ref": {"type": "string", "required": True, "example": "p0"},
        },
        evidence_mode=EvidenceMode.NONE,
        effect=ToolEffect.READ_ONLY,
        handler=_recall_page,
    ),
    "find_route": ToolSpec(
        name="find_route",
        description=(
            "Find a verified route from the current page to a known page; "
            "do not execute the route."
        ),
        argument_schema={
            "page_ref": {"type": "string", "required": True, "example": "p0"},
        },
        evidence_mode=EvidenceMode.NONE,
        effect=ToolEffect.READ_ONLY,
        handler=_find_route,
    ),
    "inspect_region": ToolSpec(
        name="inspect_region",
        description=(
            "Inspect one Region on the current page and register its visible "
            "functional controls."
        ),
        argument_schema={
            "region_ref": {"type": "string", "required": True, "example": "r0"},
        },
        evidence_mode=EvidenceMode.CURRENT_AND_REGION,
        effect=ToolEffect.PERCEPTION_WRITE,
        handler=_inspect_region,
    ),
}


def tool_catalog() -> List[Dict[str, Any]]:
    return [spec.for_prompt() for spec in TOOLS.values()]


def execute_agent_tool(context: ToolContext,
                       tool_call: Dict[str, Any]) -> ToolResult:
    """Resolve one declared tool, build only its evidence, then invoke it."""
    name = str(tool_call.get("tool_name") or "").strip().casefold()
    spec = TOOLS.get(name)
    if spec is None:
        return ToolResult("error", name, message=f"unknown tool: {name}")
    arguments, error = _validate_arguments(spec, tool_call.get("arguments"))
    if error:
        return ToolResult("error", name, message=error)
    evidence, error = _build_evidence(spec, context, arguments)
    if error:
        return ToolResult("missing_evidence", name, message=error)
    try:
        return spec.handler(context, arguments, evidence)
    except Exception as exc:
        return ToolResult("error", name, message=str(exc)[:300])


__all__ = [
    "EvidenceBundle", "EvidenceMode", "ToolContext", "ToolEffect",
    "ToolResult", "ToolSpec", "TOOLS", "current_region_directory",
    "execute_agent_tool", "tool_catalog",
]
