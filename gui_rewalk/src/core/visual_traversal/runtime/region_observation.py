"""Lazy Region observation for the page -> Region -> control runtime."""

from __future__ import annotations

import copy
import io
import logging
from typing import Any, Dict, List, Optional

from gui_rewalk.src.core.graph.state_graph import (
    StateGraph,
    region_scroll_scope_id,
)

from ..block_first_inventory import BlockFirstInventoryExperiment
from ..state.identity import compute_variant_signature
from ..visual_perception import VisualElement

logger = logging.getLogger(__name__)

MAX_REGION_OBSERVATION_ATTEMPTS = 3
REGION_LAZY_PERCEPTION_MODE = "region_lazy"


def _experiment(host) -> BlockFirstInventoryExperiment:
    current = getattr(host, "_region_inventory_experiment", None)
    if current is None:
        current = BlockFirstInventoryExperiment(
            host.agent, ledger=getattr(host, "vlm_ledger", None))
        host._region_inventory_experiment = current
    return current


def _region_rows(blocks, prefix: str):
    rows = []
    labels = {}
    for index, block in enumerate(blocks or [], 1):
        label = f"{prefix}{index}"
        rows.append({
            "region": label,
            "name": str(block.get("role") or "").strip(),
            "description": str(block.get("description") or "").strip(),
        })
        labels[label] = block
    return rows, labels


def _region_partition(
        host, discovery, source_data, screenshots=None,
        triggering_action: str = "", allow_mapping: bool = True):
    """Normalize a fresh PageMap against one already registered partition."""
    current_blocks = [{
        "local_id": str(region.get("region_id") or f"r{index}"),
        "role": str(region.get("name") or "").strip(),
        "description": str(region.get("description") or "").strip(),
    } for index, region in enumerate(discovery.get("regions") or [])]
    source_blocks = list((source_data or {}).get("semantic_blocks") or [])
    current_rows, current_labels = _region_rows(current_blocks, "B")
    known_rows, known_labels = _region_rows(source_blocks, "A")
    audit = {
        "schema_version": "region_partition_mapping.v1",
        "status": "not_applicable",
        "matches": [],
        "new_current_regions": [],
        "unresolved_current_regions": [],
        "unmatched_known_regions": [],
        "raw_model_response": "",
    }
    if not source_blocks:
        audit["status"] = "initial"
        audit["new_current_regions"] = list(current_labels)
        return current_blocks, audit
    if not allow_mapping:
        audit.update({
            "status": "page_scoped_new",
            "new_current_regions": [
                str(block.get("local_id") or "")
                for block in current_blocks
            ],
            "unmatched_known_regions": [
                str(block.get("region_id") or "")
                for block in source_blocks if block.get("region_id")
            ],
        })
        for block in current_blocks:
            block["mapping_status"] = "new"
            block["observed_candidate_ids"] = [block["local_id"]]
        return current_blocks, audit

    judge = getattr(host, "block_identity_judge", None)
    result = judge.align_region_partitions(
        str((source_data or {}).get("page_name") or ""),
        known_rows,
        str(discovery.get("interface_name") or ""),
        current_rows,
        screenshots,
        triggering_action,
    ) if judge is not None and hasattr(
        judge, "align_region_partitions") else None
    audit["raw_model_response"] = str(
        getattr(judge, "last_raw_response", "") or "")[:20000]
    if result is None:
        audit["status"] = "unresolved"
        audit["unresolved_current_regions"] = list(current_labels)
        for block in current_blocks:
            block["mapping_status"] = "unresolved"
            block["observed_candidate_ids"] = [block["local_id"]]
        return current_blocks, audit

    normalized = []
    for match in result.get("matches") or []:
        known = list(match["known_region_ids"])
        current = list(match["current_region_ids"])
        candidate_ids = [
            str(current_labels[label]["local_id"]) for label in current]
        for known_label in known:
            source = known_labels[known_label]
            normalized.append({
                "local_id": str(source.get("local_id") or known_label),
                "region_id": str(source.get("region_id") or ""),
                "role": str(source.get("role") or "").strip(),
                "description": str(source.get("description") or "").strip(),
                "mapping_status": "persisted",
                "observed_candidate_ids": candidate_ids,
            })
        audit["matches"].append({
            "known_region_ids": [
                str(known_labels[label].get("region_id") or "")
                for label in known
            ],
            "current_region_ids": candidate_ids,
            "reason": str(match.get("reason") or ""),
        })
    for label in result.get("new_current_region_ids") or []:
        block = dict(current_labels[label])
        block["mapping_status"] = "new"
        block["observed_candidate_ids"] = [block["local_id"]]
        normalized.append(block)
    for label in result.get("unresolved_current_region_ids") or []:
        block = dict(current_labels[label])
        block["mapping_status"] = "unresolved"
        block["observed_candidate_ids"] = [block["local_id"]]
        normalized.append(block)
    audit.update({
        "status": "mapped",
        "new_current_regions": [
            str(current_labels[label]["local_id"])
            for label in result.get("new_current_region_ids") or []
        ],
        "unresolved_current_regions": [
            str(current_labels[label]["local_id"])
            for label in result.get("unresolved_current_region_ids") or []
        ],
        "unmatched_known_regions": [
            str(known_labels[label].get("region_id") or "")
            for label in result.get("unmatched_known_region_ids") or []
        ],
    })
    return normalized, audit


def _attempt_id(host, event_index) -> str:
    if event_index in (None, ""):
        return ""
    getter = getattr(getattr(host, "graph", None), "action_attempt", None)
    if not callable(getter):
        return ""
    try:
        return str((getter(int(event_index)) or {}).get("attempt_id") or "")
    except (TypeError, ValueError, KeyError):
        return ""


def register_region_map(
    host, obs: Dict[str, Any], path: List[Dict[str, Any]],
    replay_hints=None, *, variant_of_state_id: str = "",
    variant_candidate_state_ids=(),
    proposed_page_name: str = "",
):
    """Register a confirmed-new State from a Region-only page map."""
    shot = obs["screenshot"]
    experiment = _experiment(host)
    discovery: Dict[str, Any] = {}
    for attempt in range(MAX_REGION_OBSERVATION_ATTEMPTS):
        try:
            discovery = experiment.discover(
                shot, force_refresh=bool(attempt))
        except Exception as exc:
            discovery = {
                "status": "request_failed", "regions": [],
                "interface_name": "", "reason": str(exc)[:240],
            }
        if discovery.get("status") == "ok":
            break
    if discovery.get("status") != "ok":
        raise RuntimeError(
            "Region map unavailable after three attempts: "
            f"{discovery.get('status') or 'unknown'}")

    page_name = (
        " ".join(str(proposed_page_name or "").split())
        or str(discovery.get("interface_name") or "").strip()
    )
    fingerprint = StateGraph.compute_visual_fingerprint(shot)

    transition = getattr(host, "_pending_transition", None) or {}
    source_state_id = str(transition.get("source_id") or "")
    candidate_ids = list(dict.fromkeys(
        str(candidate_id)
        for candidate_id in (
            variant_candidate_state_ids
            or ([variant_of_state_id] if variant_of_state_id else [])
        )
        if str(candidate_id)
    ))
    if not candidate_ids:
        candidate_ids = [source_state_id]
    mapping_results = []
    for candidate_id in candidate_ids:
        candidate_data = (getattr(host, "_state_data", {}) or {}).get(
            candidate_id) or {}
        candidate_shot = b""
        candidate_path = host.registry.known_path(candidate_id)
        if candidate_path:
            try:
                with open(candidate_path, "rb") as handle:
                    candidate_shot = handle.read()
            except OSError:
                candidate_shot = b""
        candidate_partition, candidate_audit = _region_partition(
            host, discovery, candidate_data,
            [candidate_shot, shot] if candidate_shot else None,
            str(transition.get("clicked_label") or ""),
            allow_mapping=bool(variant_of_state_id))
        persisted_count = sum(
            1 for block in candidate_partition
            if str(block.get("mapping_status") or "") == "persisted")
        unresolved_count = len(
            candidate_audit.get("unresolved_current_regions") or [])
        mapping_results.append((
            (unresolved_count == 0, persisted_count, -unresolved_count),
            candidate_id,
            candidate_data,
            candidate_partition,
            candidate_audit,
        ))
    (
        _score, mapping_source_id, source_data, partition, partition_audit,
    ) = max(
        mapping_results, key=lambda item: item[0])
    partition_audit["mapping_source_state_id"] = mapping_source_id
    partition_audit["mapping_candidate_state_ids"] = candidate_ids

    source_region_ids = {
        str(block.get("region_id") or "")
        for block in (source_data.get("semantic_blocks") or [])
        if block.get("region_id")
    }
    tmp_path = host._screenshot_to_tmp(shot)
    try:
        state_id, is_new = host.registry.register(
            shot, tmp_path, button_names=[], region_set=set(),
            page_name=page_name, region_set_authoritative=False,
            force_new=True)
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except OSError:
            pass
    real_path = host.writer.save_screenshot(state_id, shot, replace=is_new)
    host.registry._states[state_id] = (
        host.registry._states[state_id][0], real_path)

    event_index = transition.get("event_index")
    attempt_id = _attempt_id(host, event_index)

    blocks = []
    statuses = {}
    for index, region in enumerate(partition):
        local_id = str(region.get("local_id") or f"r{index}")
        region_id = str(region.get("region_id") or f"{state_id}:{local_id}")
        block = {
            "local_id": local_id,
            "region_id": region_id,
            "role": str(region.get("role") or "").strip(),
            "description": str(region.get("description") or "").strip(),
            "scope": "target_app",
            "interaction": "direct",
            "scrollable": None,
            "element_ids": [],
            "element_names": [],
            "observation_status": "pending",
            "mapping_status": str(
                region.get("mapping_status") or "initial"),
            "observed_candidate_ids": list(
                region.get("observed_candidate_ids") or [local_id]),
        }
        if block["mapping_status"] == "new" and attempt_id:
            block["introduced_by_attempt_id"] = attempt_id
        blocks.append(block)
        statuses[region_id] = {
            "status": "pending", "attempts": 0, "reason": ""}

    persisted_page_id = ""
    if variant_of_state_id:
        persisted_page_id = str(source_data.get("page_id") or "")
    region_structure = [
        str(block.get("region_id") or "")
        for block in blocks
    ]
    page_id, variant_id = host.registry.record_page_variant(
        state_id, page_name, elements=[],
        observed_facts={"region_structure": region_structure},
        namespace=host.app_name, persisted_page_id=persisted_page_id)
    observed_facts = host.registry.variant_facts_of(state_id)
    variant_signature = compute_variant_signature(observed_facts)
    target_region_ids = {
        str(block.get("region_id") or "")
        for block in blocks if block.get("region_id")
    }
    introduced = [{
        "region_id": str(block.get("region_id") or ""),
        "name": str(block.get("role") or ""),
        "description": str(block.get("description") or ""),
        "introduced_by_attempt_id": attempt_id,
    } for block in blocks if block.get("mapping_status") == "new"]
    unresolved = [{
        "region_id": str(block.get("region_id") or ""),
        "name": str(block.get("role") or ""),
        "description": str(block.get("description") or ""),
    } for block in blocks if block.get("mapping_status") == "unresolved"]
    binding_status = "none"
    if variant_of_state_id and introduced and not unresolved:
        binding_status = "bound" if len(introduced) == 1 else "candidate_set"
    elif variant_of_state_id and unresolved:
        binding_status = "unresolved"
    region_transition = {
        "schema_version": "region_transition.v1",
        "source_state_id": source_state_id,
        "target_state_id": state_id,
        "relationship": (
            "same_page_variant" if variant_of_state_id else "different_page"),
        "mapping_status": partition_audit["status"],
        "persisted_region_ids": sorted(source_region_ids & target_region_ids),
        "introduced_regions": introduced,
        "removed_region_ids": sorted(source_region_ids - target_region_ids),
        "unresolved_regions": unresolved,
        "result_binding": {
            "kind": "introduced_region",
            "status": binding_status,
            "attempt_id": attempt_id,
            "region_ids": [item["region_id"] for item in introduced],
        },
    }
    data = {
        "elements": [],
        "path": list(path),
        "replay_hints": list(replay_hints or []),
        "page_name": page_name,
        "page_id": page_id,
        "variant_id": variant_id,
        "surface_kind": "page",
        "observed_facts": observed_facts,
        "visible_capabilities": [],
        "semantic_blocks": blocks,
        "region_partition_mapping": partition_audit,
        "region_transition": region_transition,
        "region_observation": statuses,
        "perception_mode": REGION_LAZY_PERCEPTION_MODE,
    }
    host._state_data[state_id] = data
    host._bfs_queue.append(state_id)
    host.registry.set_buttons(state_id, [])
    host.graph.add_state(
        state_id=state_id, elements=[], screenshot_path=real_path,
        app_name=host.app_name, action_path_from_root=list(path),
        state_type="visual", visual_fingerprint=fingerprint,
        page_name=page_name, page_id=page_id, variant_id=variant_id,
        page_identity_version="semantic_page_variant_v1",
        variant_signature=variant_signature, observed_facts=observed_facts,
        visible_capabilities=[], semantic_blocks=blocks,
        region_partition_mapping=partition_audit,
        region_transition=region_transition,
        perception_mode=REGION_LAZY_PERCEPTION_MODE,
        geometry_mode="region_localized_on_demand",
    )
    host.graph.graph.nodes[state_id]["region_observation"] = copy.deepcopy(
        statuses)
    host.writer.save_node(
        state_id=state_id, screenshot_bytes=shot, elements=[],
        visual_fingerprint=fingerprint,
        action_path_from_root=list(path), page_name=page_name,
        app_id=host.app_name, page_id=page_id, variant_id=variant_id,
        page_identity_version="semantic_page_variant_v1",
        variant_signature=variant_signature, observed_facts=observed_facts,
        visible_capabilities=[], capability_records=[],
        semantic_blocks=blocks,
        region_partition_mapping=partition_audit,
        region_transition=region_transition,
        perception_mode=REGION_LAZY_PERCEPTION_MODE,
        geometry_mode="region_localized_on_demand",
    )
    host._last_live_observation_elements = []
    host._last_live_observation_state_id = state_id
    host.perception.last_page_name = page_name
    host.perception.last_semantic_blocks = copy.deepcopy(blocks)
    host.review_debug.record_event(
        "region_map_registered", node=state_id, page=page_name,
        regions=len(blocks))
    return state_id, is_new


def pending_region_ids(host, state_id: str) -> List[str]:
    data = getattr(host, "_state_data", {}).get(str(state_id)) or {}
    statuses = data.get("region_observation") or {}
    return [
        str(region_id) for region_id, record in statuses.items()
        if str((record or {}).get("status") or "") in {
            "pending", "retry"}
    ]


def unresolved_region_ids(host, state_id: Optional[str] = None) -> List[str]:
    result = []
    for candidate_id, data in getattr(host, "_state_data", {}).items():
        if state_id is not None and str(candidate_id) != str(state_id):
            continue
        for region_id, record in (
                data.get("region_observation") or {}).items():
            if str((record or {}).get("status") or "") == "unresolved":
                result.append(f"{candidate_id}:{region_id}")
    return result


def _block_for(data: Dict[str, Any], region_id: str):
    return next((
        block for block in data.get("semantic_blocks") or []
        if str(block.get("region_id") or "") == str(region_id)
    ), None)


def _to_elements(rows, block, start_id: int) -> List[VisualElement]:
    result = []
    region_id = str(block.get("region_id") or "")
    role = str(block.get("role") or "")
    for offset, row in enumerate(rows or []):
        target = str(row.get("target") or "")
        result.append(VisualElement(
            id=start_id + offset,
            name=target,
            bbox_xywh=[0, 0, 0, 0],
            center=[0, 0],
            el_type="button",
            interactive=True,
            category="control",
            risk="none",
            enabled=True,
            stateful=False,
            source="region_inventory",
            region=role,
            region_id=region_id,
            geometry_status="semantic_only",
            action_label=str(row.get("entry_id") or ""),
            execution_safety="safe",
        ))
    return result


def _region_bbox_px(
        screenshot_bytes: bytes, bbox_1000) -> Optional[List[int]]:
    """Convert one registered Region box to the live-frame pixel contract."""
    if not isinstance(bbox_1000, (list, tuple)) or len(bbox_1000) != 4:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(screenshot_bytes)) as image:
            width, height = image.size
        x0, y0, x1, y1 = [int(value) for value in bbox_1000]
    except (OSError, TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        return None
    return [
        int(round(x0 / 1000.0 * width)),
        int(round(y0 / 1000.0 * height)),
        int(round(x1 / 1000.0 * width)),
        int(round(y1 / 1000.0 * height)),
    ]


def observe_next_region(host, state_id: str,
                        observation: Dict[str, Any], *,
                        region_id: str = "") -> str:
    """Observe one pending Region. Return updated/retry/unresolved/none."""
    data = getattr(host, "_state_data", {}).get(str(state_id)) or {}
    pending = pending_region_ids(host, state_id)
    if not pending:
        return "none"
    region_id = str(region_id or "")
    if region_id:
        if region_id not in pending:
            return "already_complete" if region_id in (
                data.get("region_observation") or {}) else "unknown"
    else:
        region_id = pending[0]
    status = (data.get("region_observation") or {})[region_id]
    block = _block_for(data, region_id)
    shot = (observation or {}).get("screenshot")
    if block is None or not shot:
        status["attempts"] = int(status.get("attempts", 0)) + 1
        status["reason"] = "current Region or screenshot unavailable"
    else:
        experiment = _experiment(host)
        discovery = {
            "interface_name": str(data.get("page_name") or ""),
            "regions": [{
                "region_id": str(block.get("local_id") or ""),
                "name": str(block.get("role") or ""),
                "description": str(block.get("description") or ""),
            }],
        }
        selected = discovery["regions"][0]
        try:
            localization = experiment.locate(
                shot, discovery, selected,
                force_refresh=bool(status.get("attempts")))
            if localization.get("status") != "ok":
                raise RuntimeError(
                    localization.get("reason") or "Region not found")
            inventory, crop = experiment.inventory(
                shot, discovery, selected, localization,
                force_refresh=bool(status.get("attempts")),
                image_mode="context_crop")
            if inventory.get("status") != "ok":
                raise RuntimeError(
                    f"Region inventory {inventory.get('status')}")
            elements = _to_elements(
                inventory.get("function_entries"), block,
                len(data.get("elements") or []))
            region_bbox = _region_bbox_px(
                shot, localization.get("bbox_1000"))
            if region_bbox is not None:
                for element in elements:
                    element.region_bbox = list(region_bbox)
            data.setdefault("elements", []).extend(elements)
            block.update({
                "bbox_1000": list(localization["bbox_1000"]),
                "viewport_bbox_1000": list(localization["bbox_1000"]),
                "scrollable": localization.get("scrollable"),
                "element_ids": [element.id for element in elements],
                "element_names": [element.name for element in elements],
                "observation_status": "complete",
            })
            status.update({
                "status": "complete",
                "attempts": int(status.get("attempts", 0)) + 1,
                "reason": "",
            })
            recorder = getattr(
                getattr(host, "graph", None), "record_scroll_scope", None)
            if callable(recorder):
                scope_id = region_scroll_scope_id(region_id)
                existing = getattr(
                    getattr(host, "graph", None), "scroll_ledger", {}
                ).get(scope_id, {})
                if existing.get("complete") is True:
                    recorder(
                        scope_id=scope_id,
                        state_id=str(state_id),
                        region_id=region_id,
                        role=str(block.get("role") or "region"),
                        classification=str(
                            existing.get("classification") or "unknown"),
                        termination=str(
                            existing.get("termination") or "unknown"),
                        bottom_reached=bool(
                            existing.get("bottom_reached")),
                        top_restored=bool(existing.get("top_restored")),
                        steps=int(existing.get("steps", 0) or 0),
                        max_steps=int(existing.get("max_steps", 0) or 0),
                        detail="mapped Region reuses prior scroll evidence",
                    )
                elif localization.get("scrollable") is False:
                    recorder(
                        scope_id=scope_id,
                        state_id=str(state_id),
                        region_id=region_id,
                        role=str(block.get("role") or "region"),
                        classification="static",
                        termination="static",
                        top_restored=True,
                        detail=(
                            "latest Region locator explicitly classified "
                            "the visible Region as non-scrollable"),
                    )
                else:
                    recorder(
                        scope_id=scope_id,
                        state_id=str(state_id),
                        region_id=region_id,
                        role=str(block.get("role") or "region"),
                        classification="unknown",
                        termination="pending",
                        top_restored=True,
                        detail=(
                            "new Region requires one bounded behavioral "
                            "scroll audit"),
                    )
            crop_bytes = io.BytesIO()
            crop.save(crop_bytes, format="PNG")
            host.writer.save_region_image(
                str(state_id), region_id, crop_bytes.getvalue())
            host.registry.set_buttons(state_id, elements)
            host.region_registry.mark_seen(region_id, state_id)
            host.region_registry.record_mapped_elements(
                region_id, [element.name for element in elements])
            node = host.graph.graph.nodes[str(state_id)]
            node["elements"] = [
                element.to_dict() for element in data["elements"]]
            node["semantic_blocks"] = copy.deepcopy(
                data["semantic_blocks"])
            node["region_observation"] = copy.deepcopy(
                data["region_observation"])
            node["variant_signature"] = compute_variant_signature(
                data.get("observed_facts") or {})
            host.perception.last_page_name = str(
                data.get("page_name") or "")
            host.perception.last_semantic_blocks = copy.deepcopy(
                data["semantic_blocks"])
            host._last_live_observation_state_id = str(state_id)
            host._last_live_observation_elements = list(data["elements"])
            host._persist_exploration_state(str(state_id))
            host.review_debug.record_event(
                "region_inventory_complete", node=state_id,
                region=region_id, controls=len(elements))
            return "updated"
        except Exception as exc:
            status["attempts"] = int(status.get("attempts", 0)) + 1
            status["reason"] = str(exc)[:240]
            logger.warning(
                "Region observation failed for %s/%s: %s",
                str(state_id)[:8], region_id, exc)

    if int(status.get("attempts", 0)) >= MAX_REGION_OBSERVATION_ATTEMPTS:
        status["status"] = "unresolved"
        if block is not None:
            block["observation_status"] = "unresolved"
        node = getattr(getattr(host, "graph", None), "graph", None)
        if node is not None and str(state_id) in node:
            node.nodes[str(state_id)]["region_observation"] = copy.deepcopy(
                data.get("region_observation") or {})
            node.nodes[str(state_id)]["semantic_blocks"] = copy.deepcopy(
                data.get("semantic_blocks") or [])
        host._persist_exploration_state(str(state_id))
        return "unresolved"
    status["status"] = "retry"
    if block is not None:
        block["observation_status"] = "retry"
    node = getattr(getattr(host, "graph", None), "graph", None)
    if node is not None and str(state_id) in node:
        node.nodes[str(state_id)]["region_observation"] = copy.deepcopy(
            data.get("region_observation") or {})
        node.nodes[str(state_id)]["semantic_blocks"] = copy.deepcopy(
            data.get("semantic_blocks") or [])
    host._persist_exploration_state(str(state_id))
    return "retry"


__all__ = [
    "MAX_REGION_OBSERVATION_ATTEMPTS",
    "observe_next_region",
    "pending_region_ids",
    "register_region_map",
    "unresolved_region_ids",
]
