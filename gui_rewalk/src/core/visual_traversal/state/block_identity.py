"""Stable Region registration and cross-interface correspondence."""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Tuple

from PIL import Image

from ..grounding.region.registry import element_is_action

logger = logging.getLogger(__name__)

def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _surface_for_role(role_value: Any) -> str:
    role = _norm(role_value).replace(" ", "_")
    if any(token in role for token in ("popup", "menu", "drawer", "bottom_sheet")):
        return "popup_menu"
    if any(token in role for token in ("dialog", "modal")):
        return "dialog"
    return "page"


def semantic_surface_kind(blocks, explicit: Any = "") -> str:
    """Return the active top-level surface kind from perception or block roles."""
    normalized = _norm(explicit).replace(" ", "_")
    if normalized in {"popup_menu", "dialog", "drawer", "bottom_sheet", "popover"}:
        return normalized
    for block in blocks or []:
        inferred = _surface_for_role(block.get("role"))
        if inferred != "page":
            return inferred
    return "page"


def semantic_surface_host_token(
    blocks, *, surface_kind: Any = "", page_name: Any = ""
) -> str:
    """Identity token for one shared overlay mounted on a concrete host Page."""
    kind = semantic_surface_kind(blocks, surface_kind)
    host = _norm(page_name)
    if kind == "page" or not host:
        return ""
    return f"surface_host:{host}"


def semantic_region_set(
    blocks, elements, *, surface_kind: Any = "", page_name: Any = ""
) -> set[str]:
    """Return stable block references for structure/audit, never page identity."""
    return {
        f"region:{block.get('region_id')}"
        for block in (blocks or []) if block.get("region_id")
    }


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _crop_blocks(screenshot: bytes, bboxes) -> Dict[str, bytes]:
    image = Image.open(io.BytesIO(screenshot)).convert("RGB")
    width, height = image.size
    crops: Dict[str, bytes] = {}
    for local_id, bbox in (bboxes or {}).items():
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(1000.0, x1), min(1000.0, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        px = (
            max(0, min(width, round(x0 * width / 1000))),
            max(0, min(height, round(y0 * height / 1000))),
            max(0, min(width, round(x1 * width / 1000))),
            max(0, min(height, round(y1 * height / 1000))),
        )
        if px[2] <= px[0] or px[3] <= px[1]:
            continue
        crops[str(local_id)] = _png(image.crop(px))
    return crops


def _state_region_rows(data: Dict[str, Any], prefix: str):
    """Build a request-local text table from one node's stable Regions."""
    names: Dict[str, List[str]] = {}
    for block in data.get("semantic_blocks") or []:
        region_id = str(block.get("region_id") or "")
        if not region_id:
            continue
        names.setdefault(region_id, [])
        for name in block.get("element_names") or []:
            value = " ".join(str(name or "").split())
            if value and value not in names[region_id]:
                names[region_id].append(value)
    for element in data.get("elements") or []:
        get = element.get if isinstance(element, dict) else (
            lambda key, default=None: getattr(element, key, default))
        region_id = str(get("region_id", "") or "")
        value = " ".join(str(get("name", "") or "").split())
        if region_id and value:
            names.setdefault(region_id, [])
            if value not in names[region_id]:
                names[region_id].append(value)
    ids = list(names)
    rows = [
        {"region": f"{prefix}{index}", "contains": names[region_id]}
        for index, region_id in enumerate(ids, 1)
    ]
    return rows, {
        f"{prefix}{index}": region_id
        for index, region_id in enumerate(ids, 1)
    }


def compare_state_regions(*, state_a: Dict[str, Any], state_b: Dict[str, Any],
                          judge) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Ask once which already-recorded Regions are identical across two nodes."""
    rows_a, labels_a = _state_region_rows(state_a, "A")
    rows_b, labels_b = _state_region_rows(state_b, "B")
    audit = {
        "schema_version": "semantic_region_correspondence.v1",
        "interface_a": str(state_a.get("page_name") or ""),
        "interface_b": str(state_b.get("page_name") or ""),
        "regions_a": rows_a,
        "regions_b": rows_b,
        "raw_model_response": "",
        "same_regions": [],
    }
    if judge is None or not rows_a or not rows_b:
        return audit, {}
    result = judge.align_regions(
        audit["interface_a"], rows_a, audit["interface_b"], rows_b)
    audit["raw_model_response"] = str(
        getattr(judge, "last_raw_response", "") or "")[:20000]
    if result is None:
        audit["status"] = "unavailable"
        return audit, {}
    aliases: Dict[str, str] = {}
    for row in result.get("same_regions") or []:
        a_id = labels_a[str(row["interface_a_region"])]
        b_id = labels_b[str(row["interface_b_region"])]
        if a_id != b_id:
            def order_key(value: str):
                suffix = value[1:] if value.startswith("r") else ""
                return (0, int(suffix)) if suffix.isdigit() else (1, value)
            keep_id, drop_id = sorted((a_id, b_id), key=order_key)
            aliases[drop_id] = keep_id
        audit["same_regions"].append({
            "interface_a_region": a_id,
            "interface_b_region": b_id,
        })
    audit["status"] = "mapped"
    audit["interface_a_final_regions"] = result[
        "interface_a_final_regions"]
    audit["interface_b_final_regions"] = result[
        "interface_b_final_regions"]
    return audit, aliases


def resolve_semantic_blocks(
    *, screenshot: bytes, blocks: List[Dict[str, Any]], elements,
    perception, judge, region_registry, writer, state_data,
    pending_transition=None, page_name: str = "", candidate_state_ids=None,
) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    """Mint Regions for a newly confirmed node; do no cross-node matching."""
    surface_kind = str(getattr(perception, "last_surface_kind", "page") or "page")
    if blocks and all(bool(block.get("fixture_oracle")) for block in blocks):
        bboxes = {
            str(block.get("local_id") or ""): list(block["bbox_1000"])
            for block in blocks
            if isinstance(block.get("bbox_1000"), list)
            and len(block.get("bbox_1000")) == 4
        }
        perception.last_block_localization = {
            "status": "ok" if len(bboxes) == len(blocks) else "partial",
            "method": "fixture_oracle_inventory",
            "coordinate_space": "normalized_1000",
            "bboxes_1000": bboxes,
        }
        local_crops = _crop_blocks(screenshot, bboxes)
        mapping = {}
        region_crops: Dict[str, bytes] = {}
        for block in blocks:
            local_id = str(block.get("local_id") or "")
            members = [element for element in elements
                       if str(getattr(element, "region_id", "") or "") == local_id]
            names = [getattr(element, "name", "") for element in members]
            actions = [getattr(element, "name", "") for element in members
                       if element_is_action(element)]
            region_id, _is_new = region_registry.register(
                role=str(block.get("role") or "other"), names=names,
                scrollable=bool(block.get("scrollable")),
                member_tokens=names, action_names=actions)
            block["region_id"] = region_id
            mapping[local_id] = region_id
            if local_id in local_crops:
                region_crops[region_id] = local_crops[local_id]
            for element in members:
                element.region_id = region_id
        return {
            "schema_version": "semantic_block_identity_attempt.v1",
            "method": "fixture_oracle_inventory",
            "localization": dict(perception.last_block_localization),
            "validated_mapping": mapping,
            "created_concepts": [],
        }, region_crops
    bboxes = {
        str(block.get("local_id") or ""): list(block["bbox_1000"])
        for block in blocks
        if isinstance(block.get("bbox_1000"), list)
        and len(block.get("bbox_1000")) == 4
    }
    if len(bboxes) != len(blocks):
        raise RuntimeError(
            "semantic inventory did not provide every block bbox_1000")
    perception.last_block_localization = {
        "status": "ok", "method": "semantic_inventory",
        "coordinate_space": "normalized_1000", "bboxes_1000": bboxes,
    }
    crops = _crop_blocks(screenshot, bboxes)
    mapping: Dict[str, str] = {}
    created: List[str] = []
    for block in blocks:
        local_id = str(block.get("local_id") or "")
        members = [element for element in elements
                   if str(getattr(element, "region_id", "") or "") == local_id]
        concept_id = region_registry.mint_semantic_concept(
            role="block", names=[], action_names=[],
            surface_kind=surface_kind,
            descriptor={}, representative=crops.get(local_id))
        mapping[local_id] = concept_id
        created.append(concept_id)
        block["region_id"] = concept_id
        block["role"] = ""
        for element in members:
            element.region_id = concept_id
            element.region = ""

    audit = {
        "schema_version": "semantic_block_identity_attempt.v1",
        "method": "new_node_region_mint",
        "localization": dict(getattr(perception, "last_block_localization", {}) or {}),
        "validated_mapping": {
            local_id: {
                "concept_id": str(next(
                    (block.get("region_id") for block in blocks
                     if block.get("local_id") == local_id), "")),
                "reason": "minted for new node before cross-interface comparison",
            }
            for local_id in mapping
        },
        "created_concepts": created,
    }
    try:
        writer.save_block_identity_attempt(
            audit=audit, current_atlas=None,
            current_crops=crops)
    except Exception as exc:
        logger.warning("block identity artifact persistence failed: %s", exc)
    region_crops: Dict[str, bytes] = {}
    for block in blocks:
        local_id = str(block.get("local_id") or "")
        region_id = str(block.get("region_id") or "")
        payload = crops.get(local_id)
        if region_id and payload:
            region_crops[region_id] = payload
    return audit, region_crops
