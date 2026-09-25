# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pure-visual UI state graph and JSON persistence.

The graph deliberately knows nothing about accessibility trees.  Visual state
identity is owned by :mod:`visual_traversal.visual_state`; this module provides
only screenshot fingerprints, node/edge storage, and stable node-link JSON.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile
import time
from io import BytesIO
from typing import Any, Dict, List, Mapping, Optional

import imagehash
import networkx as nx
from PIL import Image


logger = logging.getLogger("desktopenv.graph.state")

TASKBAR_CROP_PX = 48
TOP_CROP_PX = 0
GRAPH_SCHEMA_VERSION = 3

# Geometry is observation-local evidence.  Persisted graph actions must instead
# describe a live-groundable semantic selector so another environment never
# replays discovery coordinates.
_GEOMETRY_KEYS = frozenset({
    "x", "y", "x1", "y1", "x2", "y2", "left", "top", "right", "bottom",
    "width", "height", "w", "h", "bbox", "bbox_xywh", "box", "center",
    "point", "position", "coordinates", "coordinate", "start_x", "start_y",
    "end_x", "end_y", "source_x", "source_y", "target_x", "target_y",
})
_NON_ROUTING_OUTCOMES = frozenset({
    "attempted", "executed", "no_effect", "transitioned_inconsistent",
    "permission_blocked", "disabled", "blocked", "external_app", "app_crash",
    "perception_failed", "quarantined_source_mismatch", "failed", "failure",
    "error", "cancelled", "canceled", "prerequisite_cleanup",
})


def region_scroll_scope_id(region_id: Any) -> str:
    """Return the one durable scroll-ledger key for a stable Region."""
    value = str(region_id or "").strip()
    if not value:
        raise ValueError("region scroll scope requires region_id")
    return f"region:{value}"


def page_scroll_scope_id(state_id: Any) -> str:
    """Return the page-level key used only when no stable Region owns scrolling."""
    value = str(state_id or "").strip()
    if not value:
        raise ValueError("page scroll scope requires state_id")
    return f"state:{value}:page"


def scroll_evidence_complete(
    *,
    classification: Any,
    termination: Any,
    bottom_reached: Any = False,
    top_restored: Any = False,
) -> bool:
    """Evaluate the shared static/bottom-and-restore completion contract."""
    kind = str(classification or "").strip().casefold()
    ending = str(termination or "").strip().casefold()
    if kind == "static":
        return ending in {"static", "viewport_stable"} and bool(top_restored)
    return (
        kind == "scrollable"
        and ending in {"viewport_stable", "bottom_reached"}
        and bool(bottom_reached)
        and bool(top_restored)
    )


def _without_geometry(value: Any) -> Any:
    """Deep-copy JSON-like data while dropping coordinate-bearing fields."""
    if isinstance(value, dict):
        return {
            str(key): _without_geometry(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _GEOMETRY_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_without_geometry(item) for item in value]
    return copy.deepcopy(value)


def _semantic_action(
    action: Any,
    *,
    element_id: str = "",
    element_label: str = "",
    semantic_description: str = "",
    region: str = "",
) -> Dict[str, Any]:
    """Normalize an executed primitive into a portable semantic action."""
    raw = action if isinstance(action, dict) else {"action": str(action or "")}
    action_type = str(
        raw.get("action_type") or raw.get("type") or raw.get("action") or "UNKNOWN"
    ).strip().upper()
    result: Dict[str, Any] = {"action_type": action_type or "UNKNOWN"}

    selector = raw.get("selector") if isinstance(raw.get("selector"), dict) else {}
    selector = _without_geometry(selector)
    if element_label:
        selector.setdefault("element_label", str(element_label))
    if region:
        selector.setdefault("region", str(region))
    if semantic_description and not selector.get("description"):
        selector["description"] = str(semantic_description)
    if selector:
        result["selector"] = selector

    parameters = raw.get("parameters")
    if isinstance(parameters, dict):
        parameters = _without_geometry(parameters)
        if parameters:
            result["parameters"] = parameters

    # Preserve non-geometric recipe structure and keyboard/text semantics used by
    # legacy non-click actions, but never persist the original pointer geometry.
    for key in ("key", "keys", "text", "button", "direction", "amount"):
        if key in raw and key not in result:
            result[key] = _without_geometry(raw[key])
    sequence = raw.get("steps") or raw.get("actions") or raw.get("action_sequence")
    if isinstance(sequence, list):
        result["steps"] = [_semantic_action(step) for step in sequence]
    return result


def _edge_identity_payload(
    source: str, target: str, action: Dict[str, Any]
) -> str:
    return json.dumps(
        {"source": str(source or ""), "target": str(target or ""), "action": action},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def set_visual_crop(top_px: int, bottom_px: int) -> None:
    """Configure platform-specific screenshot hash crop margins."""
    global TOP_CROP_PX, TASKBAR_CROP_PX
    TOP_CROP_PX = max(0, int(top_px))
    TASKBAR_CROP_PX = max(0, int(bottom_px))


def _cropped_image(screenshot_bytes: bytes) -> Image.Image:
    image = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
    width, height = image.size
    top = min(TOP_CROP_PX, max(0, height - 1))
    bottom = max(top + 1, height - TASKBAR_CROP_PX)
    return image.crop((0, top, width, bottom))


class StateGraph:
    """Directed graph of visual UI states and executed transitions."""

    def __init__(self, app_name: str):
        self.graph = nx.DiGraph()
        self.app_name = app_name
        self._action_counter = 0
        self.stop_reason = "incomplete"
        self.abnormal_buttons: List[Dict[str, Any]] = []
        # Schema v3 has one durable source of truth: semantic action edges, each
        # owning its append-only attempts.  ``self.graph`` remains a compact
        # compatibility topology whose edges only reference action_edge_ids.
        self.action_edges: List[Dict[str, Any]] = []
        # Page/variant and capability containers are intentionally lightweight;
        # identity/candidate generation lives in visual traversal, while this
        # module guarantees their round-trip persistence.
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        # Scroll evidence is required to distinguish a genuinely exhausted long
        # Settings surface from a frontier that merely never saw below-fold rows.
        # It is keyed by a stable state/region scope and contains no screenshots.
        self.scroll_ledger: Dict[str, Dict[str, Any]] = {}
        self._live_sync = None

    @staticmethod
    def compute_visual_state_id(screenshot_bytes: bytes) -> str:
        """Return the cropped screenshot perceptual hash."""
        return str(imagehash.phash(_cropped_image(screenshot_bytes)))

    @staticmethod
    def compute_exact_screenshot_hash(screenshot_bytes: bytes) -> str:
        """Return a strict hash of normalized cropped screenshot pixels."""
        image = _cropped_image(screenshot_bytes).convert("RGB")
        width, height = image.size
        payload = width.to_bytes(4, "big") + height.to_bytes(4, "big") \
            + image.tobytes()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def compute_visual_fingerprint(screenshot_bytes: bytes) -> Dict[str, Any]:
        """Return complementary hashes used as persisted visual evidence."""
        original = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
        cropped = _cropped_image(screenshot_bytes)
        width, height = original.size
        return {
            "version": "visual_fingerprint_v1",
            "exact_sha256": StateGraph.compute_exact_screenshot_hash(
                screenshot_bytes),
            "phash": str(imagehash.phash(cropped)),
            "dhash": str(imagehash.dhash(cropped)),
            "ahash": str(imagehash.average_hash(cropped)),
            "width": width,
            "height": height,
            "crop_top_px": TOP_CROP_PX,
            "crop_bottom_px": TASKBAR_CROP_PX,
        }

    def add_state(
        self,
        state_id: str,
        elements: List[Dict[str, Any]],
        screenshot_path: str,
        app_name: str,
        action_path_from_root: Optional[List[Dict[str, Any]]] = None,
        state_type: str = "visual",
        visual_fingerprint: Optional[Dict[str, Any]] = None,
        page_name: str = "",
        page_id: str = "",
        variant_id: str = "",
        page_identity_version: str = "",
        variant_signature: Optional[Any] = None,
        observed_facts: Optional[Dict[str, Any]] = None,
        visible_capabilities: Optional[List[Any]] = None,
        semantic_blocks: Optional[List[Dict[str, Any]]] = None,
        region_partition_mapping: Optional[Dict[str, Any]] = None,
        region_transition: Optional[Dict[str, Any]] = None,
        perception_mode: str = "",
        geometry_mode: str = "",
    ) -> bool:
        """Add a visual node; return ``True`` only when it is new."""
        if state_id in self.graph:
            node = self.graph.nodes[state_id]
            old_page = str(node.get("page_id") or state_id)
            old_variant = str(node.get("variant_id") or state_id)
            node["visit_count"] = int(node.get("visit_count", 0)) + 1
            if visual_fingerprint and not node.get("visual_fingerprint"):
                node["visual_fingerprint"] = visual_fingerprint
            if page_name and not node.get("page_name"):
                node["page_name"] = page_name
            resolved_page = str(page_id or node.get("page_id") or state_id)
            resolved_variant = str(
                variant_id or node.get("variant_id") or state_id)
            node["page_id"] = resolved_page
            node["variant_id"] = resolved_variant
            if page_identity_version:
                node["page_identity_version"] = str(page_identity_version)
            node.pop("page_anchor_tokens", None)
            if variant_signature is not None:
                node["variant_signature"] = copy.deepcopy(variant_signature)
            if observed_facts:
                facts = dict(node.get("observed_facts") or {})
                facts.update(copy.deepcopy(observed_facts))
                node["observed_facts"] = facts
            if visible_capabilities:
                visible = list(node.get("visible_capabilities") or [])
                for capability in visible_capabilities:
                    if capability not in visible:
                        visible.append(copy.deepcopy(capability))
                node["visible_capabilities"] = visible
            if semantic_blocks is not None:
                node["semantic_blocks"] = copy.deepcopy(semantic_blocks)
            if region_partition_mapping is not None:
                node["region_partition_mapping"] = copy.deepcopy(
                    region_partition_mapping)
            if region_transition is not None:
                node["region_transition"] = copy.deepcopy(region_transition)
            if perception_mode:
                node["perception_mode"] = str(perception_mode)
            if geometry_mode:
                node["geometry_mode"] = str(geometry_mode)
            self._register_page_variant(
                state_id=state_id,
                page_id=resolved_page,
                variant_id=resolved_variant,
                page_name=str(node.get("page_name") or page_name or ""),
                variant_signature=node.get("variant_signature"),
                observed_facts=node.get("observed_facts") or {},
                visible_capabilities=node.get("visible_capabilities") or [],
            )
            if old_page != resolved_page or old_variant != resolved_variant:
                self._cascade_state_identity_refinement(
                    state_id=str(state_id),
                    old_page_id=old_page,
                    old_variant_id=old_variant,
                    new_page_id=resolved_page,
                    new_variant_id=resolved_variant,
                )
            return False

        resolved_page = str(page_id or state_id)
        resolved_variant = str(variant_id or state_id)
        self.graph.add_node(
            state_id,
            state_id=state_id,
            state_type=state_type or "visual",
            screenshot_path=screenshot_path,
            elements=elements,
            app_name=app_name,
            visit_count=1,
            action_path_from_root=list(action_path_from_root or []),
            unreachable=False,
            visual_fingerprint=visual_fingerprint or {},
            page_name=page_name or "",
            page_id=resolved_page,
            variant_id=resolved_variant,
            page_identity_version=str(
                page_identity_version
                or ("external" if page_id or variant_id else "legacy_state")
            ),
            variant_signature=copy.deepcopy(variant_signature),
            observed_facts=copy.deepcopy(observed_facts or {}),
            visible_capabilities=copy.deepcopy(visible_capabilities or []),
            semantic_blocks=copy.deepcopy(semantic_blocks or []),
            region_partition_mapping=copy.deepcopy(
                region_partition_mapping or {}),
            region_transition=copy.deepcopy(region_transition or {}),
            perception_mode=str(perception_mode or "legacy_grounded"),
            geometry_mode=str(geometry_mode or "stored_bbox"),
        )
        self._register_page_variant(
            state_id=state_id,
            page_id=resolved_page,
            variant_id=resolved_variant,
            page_name=page_name,
            variant_signature=variant_signature,
            observed_facts=observed_facts or {},
            visible_capabilities=visible_capabilities or [],
        )
        logger.info(
            "New visual state %s (elements=%d, graph=%d nodes/%d edges)",
            state_id,
            len(elements),
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )
        return True

    def _cascade_state_identity_refinement(
        self,
        *,
        state_id: str,
        old_page_id: str,
        old_variant_id: str,
        new_page_id: str,
        new_variant_id: str,
    ) -> None:
        """Keep edge/capability provenance aligned with a richer node observation."""
        old_variant_still_used = bool(
            ((self.pages.get(old_page_id) or {}).get("variants") or {})
            .get(old_variant_id, {}).get("state_ids"))
        old_page_still_used = bool(
            (self.pages.get(old_page_id) or {}).get("variants"))
        affected_source_edges: set[str] = set()
        affected_target_edges: set[str] = set()
        for action_edge in self.action_edges:
            edge_id = str(action_edge.get("action_edge_id") or "")
            if str(action_edge.get("source") or "") == state_id:
                action_edge["source_page_id"] = new_page_id
                action_edge["source_variant_id"] = new_variant_id
                affected_source_edges.add(edge_id)
            if str(action_edge.get("target") or "") == state_id:
                action_edge["target_page_id"] = new_page_id
                action_edge["target_variant_id"] = new_variant_id
                affected_target_edges.add(edge_id)

        def _replace(values: Any, old: str, new: str, keep_old: bool) -> List[Any]:
            result = list(values or [])
            if not keep_old:
                result = [value for value in result if str(value) != old]
            if new and new not in [str(value) for value in result]:
                result.append(new)
            return result

        for capability_id, capability in self.capabilities.items():
            if not isinstance(capability, dict):
                continue
            source_refs = [
                ref for ref in capability.get("source_elements") or []
                if isinstance(ref, dict)]
            source_matches = False
            for source_ref in source_refs:
                if str(source_ref.get("state_id") or "") != state_id:
                    continue
                source_matches = True
                source_ref["variant_id"] = new_variant_id
            edge_refs = {
                str(value) for value in capability.get("action_edge_ids") or []}
            target_matches = bool(edge_refs & affected_target_edges)
            if source_matches:
                if str(capability.get("page_id") or "") == old_page_id:
                    capability["page_id"] = new_page_id
                for key in ("evidence_variants", "entry_variants"):
                    capability[key] = _replace(
                        capability.get(key), old_variant_id, new_variant_id,
                        old_variant_still_used)
                available = capability.setdefault("available_when", {})
                available["variant_ids"] = _replace(
                    available.get("variant_ids"), old_variant_id, new_variant_id,
                    old_variant_still_used)
                for map_key in (
                    "facts_by_variant", "availability_by_variant",
                    "requires_by_variant",
                ):
                    values = available.get(map_key)
                    if not isinstance(values, dict) or old_variant_id not in values:
                        continue
                    values.setdefault(new_variant_id, copy.deepcopy(
                        values[old_variant_id]))
                    if not old_variant_still_used:
                        values.pop(old_variant_id, None)
                new_page = self.pages.setdefault(
                    new_page_id,
                    {"page_id": new_page_id, "semantic_name": "", "variants": {}},
                )
                page_capabilities = new_page.setdefault("capability_ids", [])
                if capability_id not in page_capabilities:
                    page_capabilities.append(capability_id)
            if target_matches:
                capability["target_pages"] = _replace(
                    capability.get("target_pages"), old_page_id, new_page_id,
                    old_page_still_used)
                capability["target_variants"] = _replace(
                    capability.get("target_variants"), old_variant_id,
                    new_variant_id, old_variant_still_used)
                for effect in capability.get("effects") or []:
                    if not isinstance(effect, dict):
                        continue
                    if str(effect.get("target_page_id") or "") == old_page_id:
                        effect["target_page_id"] = new_page_id
                    if str(effect.get("target_variant_id") or "") == old_variant_id:
                        effect["target_variant_id"] = new_variant_id
                predicate = str(capability.get("success_predicate") or "")
                old_target = f"{old_page_id}@{old_variant_id}"
                if old_target and old_target in predicate:
                    capability["success_predicate"] = predicate.replace(
                        old_target, f"{new_page_id}@{new_variant_id}")

    def _register_page_variant(
        self,
        *,
        state_id: str,
        page_id: str,
        variant_id: str,
        page_name: str = "",
        variant_signature: Optional[Any] = None,
        observed_facts: Optional[Dict[str, Any]] = None,
        visible_capabilities: Optional[List[Any]] = None,
    ) -> None:
        """Fold one visual state into the persisted page/variant catalog."""
        state_id = str(state_id)
        page_id = str(page_id)
        variant_id = str(variant_id)
        # Node attributes are the membership source of truth.  A richer revisit
        # may refine a state's page/variant identity; remove the old catalog
        # membership before inserting the new one so resume cannot resurrect a
        # stale variant containing the same execution state.
        for old_page_id, old_page in list(self.pages.items()):
            variants = old_page.get("variants")
            if not isinstance(variants, dict):
                continue
            for old_variant_id, old_variant in list(variants.items()):
                if old_page_id == page_id and old_variant_id == variant_id:
                    continue
                state_ids = list(old_variant.get("state_ids") or [])
                if state_id not in state_ids:
                    continue
                old_variant["state_ids"] = [
                    value for value in state_ids if str(value) != state_id]
                if not old_variant["state_ids"]:
                    variants.pop(old_variant_id, None)
            if not variants and old_page_id != page_id:
                self.pages.pop(old_page_id, None)
        page = self.pages.setdefault(
            page_id,
            {
                "page_id": page_id,
                "semantic_name": str(page_name or ""),
                "variants": {},
            },
        )
        if page_name and not page.get("semantic_name"):
            page["semantic_name"] = str(page_name)
        variants = page.setdefault("variants", {})
        variant = variants.setdefault(
            variant_id,
            {
                "variant_id": variant_id,
                "state_ids": [],
                "variant_signature": copy.deepcopy(variant_signature),
                "observed_facts": {},
                "visible_capabilities": [],
            },
        )
        state_ids = variant.setdefault("state_ids", [])
        if state_id not in state_ids:
            state_ids.append(state_id)
        if variant_signature is not None:
            variant["variant_signature"] = copy.deepcopy(variant_signature)
        variant.setdefault("observed_facts", {}).update(
            copy.deepcopy(observed_facts or {}))
        visible = variant.setdefault("visible_capabilities", [])
        for capability in visible_capabilities or []:
            if capability not in visible:
                visible.append(copy.deepcopy(capability))

    @staticmethod
    def _merge_unique(target: Dict[str, Any], source: Dict[str, Any], key: str) -> None:
        values = list(target.get(key) or [])
        for value in list(source.get(key) or []):
            if value not in values:
                values.append(copy.deepcopy(value))
        target[key] = values

    def register_capability_candidates(
        self,
        state_id: str,
        candidates: List[Dict[str, Any]],
    ) -> List[str]:
        """Merge observation-time candidates into the page capability catalog."""
        if state_id not in self.graph:
            raise ValueError(f"unknown capability source state: {state_id}")
        node = self.graph.nodes[state_id]
        page_id = str(node.get("page_id") or state_id)
        variant_id = str(node.get("variant_id") or state_id)
        visible_ids = list(node.get("visible_capabilities") or [])
        for raw in candidates or []:
            if not isinstance(raw, dict):
                continue
            capability = copy.deepcopy(raw)
            capability_id = str(capability.get("capability_id") or "")
            if not capability_id:
                continue
            capability["capability_id"] = capability_id
            capability.setdefault("page_id", page_id)
            capability.setdefault("status", "discovered")
            existing = self.capabilities.get(capability_id)
            if existing is None:
                self.capabilities[capability_id] = capability
            else:
                from gui_rewalk.src.core.visual_traversal.capability_discovery import (
                    merge_capability_records,
                )
                self.capabilities[capability_id] = merge_capability_records(
                    existing, capability)
            if capability_id not in visible_ids:
                visible_ids.append(capability_id)

        node["visible_capabilities"] = visible_ids
        page = self.pages.setdefault(
            page_id,
            {"page_id": page_id, "semantic_name": "", "variants": {}},
        )
        page_caps = page.setdefault("capability_ids", [])
        for capability_id in visible_ids:
            if capability_id not in page_caps:
                page_caps.append(capability_id)
        variant = page.setdefault("variants", {}).setdefault(
            variant_id,
            {"variant_id": variant_id, "state_ids": [str(state_id)]},
        )
        variant["visible_capabilities"] = list(visible_ids)
        return visible_ids

    @staticmethod
    def _normal_label(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    def _record_capability_entry_execution(
        self,
        *,
        source: str,
        target: str,
        element_id: str,
        element_label: str,
        region: str,
        action_edge_ids: List[str],
        effect_verdict: str,
        effect_note: str,
        landing_verified: Optional[bool],
    ) -> None:
        """Attach real entry-execution provenance without claiming user effects.

        A verified landing proves that the recorded selector can be executed and
        routed. It does not prove that a user-visible function succeeded. The
        latter is induced separately from append-only effect observations.
        """
        if landing_verified is not True or source not in self.graph \
                or target not in self.graph:
            return
        verified_edges = {
            str(edge.get("action_edge_id") or "")
            for edge in self.action_edges
            if edge.get("routing_verified") is True
        }
        evidence_edges = [
            edge_id for edge_id in action_edge_ids if edge_id in verified_edges]
        if not evidence_edges:
            return
        source_node = self.graph.nodes[source]
        target_node = self.graph.nodes[target]
        source_variant = str(source_node.get("variant_id") or source)
        target_variant = str(target_node.get("variant_id") or target)
        target_page = str(target_node.get("page_id") or target)
        region_transition = (
            target_node.get("region_transition")
            if isinstance(target_node.get("region_transition"), dict)
            else {}
        )
        introduced_regions = [
            copy.deepcopy(item)
            for item in region_transition.get("introduced_regions") or []
            if isinstance(item, dict)
        ]
        action_result_regions = introduced_regions if (
            region_transition.get("relationship") == "same_page_variant"
            and str((region_transition.get("result_binding") or {}).get(
                "status") or "") in {"bound", "candidate_set"}
        ) else []
        wanted_id = str(element_id or "")
        wanted_label = self._normal_label(element_label)
        wanted_region = self._normal_label(region)
        for capability_id in list(source_node.get("visible_capabilities") or []):
            capability = self.capabilities.get(str(capability_id))
            if not isinstance(capability, dict):
                continue
            matches = False
            for source_ref in capability.get("source_elements") or []:
                if not isinstance(source_ref, dict):
                    continue
                if str(source_ref.get("variant_id") or "") not in {
                    "", source_variant,
                }:
                    continue
                ref_id = str(source_ref.get("element_id") or "")
                ref_label = self._normal_label(source_ref.get("element_label"))
                ref_region = self._normal_label(source_ref.get("region"))
                if wanted_id and ref_id:
                    # Grounded ids disambiguate repeated labels.  Never fall
                    # back to the label after two concrete ids disagree.
                    matches = ref_id == wanted_id
                elif wanted_label and ref_label == wanted_label:
                    matches = not (
                        wanted_region and ref_region
                        and wanted_region != ref_region)
                if matches:
                    break
            if not matches:
                continue
            for key, value in (
                ("action_edge_ids", evidence_edges),
                ("target_pages", [target_page]),
                ("target_variants", [target_variant]),
            ):
                self._merge_unique(capability, {key: value}, key)
            execution_evidence = {
                "kind": "entry_execution",
                "action_edge_ids": list(evidence_edges),
                "target_page_id": target_page,
                "target_variant_id": target_variant,
                "landing_verified": True,
            }
            if action_result_regions:
                execution_evidence["introduced_regions"] = action_result_regions
                execution_evidence["result_binding"] = copy.deepcopy(
                    region_transition.get("result_binding") or {})
            if effect_verdict:
                execution_evidence["observed_outcome"] = str(effect_verdict)
            if effect_note:
                execution_evidence["description"] = str(effect_note)
            records = list(capability.get("entry_execution_evidence") or [])
            if execution_evidence not in records:
                records.append(execution_evidence)
            capability["entry_execution_evidence"] = records

    def mark_unreachable(self, state_id: str) -> None:
        if state_id in self.graph:
            self.graph.nodes[state_id]["unreachable"] = True

    def reclassify_element_noninteractive(
        self,
        state_id: str,
        *,
        element_id: str = "",
        element_uid: str = "",
        element_label: str = "",
    ) -> bool:
        """Apply a live-perception correction to one stale control candidate.

        This records no action outcome: no click was executed.  Instead the
        element ceases to be a control and any unverified capability whose only
        source was that element is removed from the online catalogue.
        """
        state_id = str(state_id or "")
        if state_id not in self.graph:
            return False
        wanted_id = str(element_id or "")
        wanted_uid = str(element_uid or "")
        wanted_label = self._normal_label(element_label)

        def _matches(record: Mapping[str, Any]) -> bool:
            record_uid = str(
                record.get("element_uid") or record.get("uid") or "")
            if wanted_uid and record_uid:
                return wanted_uid == record_uid
            record_id = str(
                record.get("element_id")
                if record.get("element_id") is not None
                else record.get("id") if record.get("id") is not None else "")
            if wanted_id and record_id:
                return wanted_id == record_id
            return bool(
                wanted_label
                and wanted_label == self._normal_label(
                    record.get("element_label") or record.get("element_name")
                    or record.get("name"))
            )

        node = self.graph.nodes[state_id]
        matched = False
        for element in node.get("elements") or []:
            if not isinstance(element, dict) or not _matches(element):
                continue
            element.update({
                "interactive": False,
                "category": "display",
                "visited": True,
            })
            matched = True
        if not matched:
            return False

        for capability_id, capability in list(self.capabilities.items()):
            sources = []
            removed_source = False
            for source in capability.get("source_elements") or []:
                if (isinstance(source, Mapping)
                        and str(source.get("state_id") or "") == state_id
                        and _matches(source)):
                    removed_source = True
                    continue
                sources.append(source)
            if not removed_source:
                continue
            capability["source_elements"] = sources
            if not sources and not capability.get("action_edge_ids"):
                self.capabilities.pop(capability_id, None)

        valid_capability_ids = set(self.capabilities)
        for _node_id, live_node in self.graph.nodes(data=True):
            live_node["visible_capabilities"] = [
                capability_id
                for capability_id in (live_node.get("visible_capabilities") or [])
                if str(capability_id) in valid_capability_ids
            ]
        for page in self.pages.values():
            page_capabilities: List[str] = []
            for variant in (page.get("variants") or {}).values():
                visible: List[str] = []
                for member in variant.get("state_ids") or []:
                    if str(member) not in self.graph:
                        continue
                    for capability_id in (
                            self.graph.nodes[str(member)].get(
                                "visible_capabilities") or []):
                        capability_id = str(capability_id)
                        if (capability_id in valid_capability_ids
                                and capability_id not in visible):
                            visible.append(capability_id)
                variant["visible_capabilities"] = visible
                for capability_id in visible:
                    if capability_id not in page_capabilities:
                        page_capabilities.append(capability_id)
            page["capability_ids"] = page_capabilities
        return True

    def remove_uncommitted_state(
        self,
        state_id: str,
        *,
        alias_to: str = "",
    ) -> bool:
        """Remove a provisional node only when no durable graph fact needs it.

        ``alias_to`` is an already-registered equivalent execution state.  Any
        non-committed attempts whose provisional target is ``state_id`` are moved
        to that canonical state before removal.  Committed topology, verified
        landings, source attempts, or terminal abnormal evidence make removal
        fail closed.
        """
        state_id = str(state_id or "")
        alias_to = str(alias_to or "")
        if not state_id or state_id not in self.graph:
            return False
        if not alias_to or alias_to == state_id or alias_to not in self.graph:
            return False
        if self.graph.in_degree(state_id) or self.graph.out_degree(state_id):
            return False
        if any(str(item.get("state_id") or "") == state_id
               for item in self.abnormal_buttons):
            return False

        movable_indices: List[int] = []
        for edge in self.action_edges:
            if str(edge.get("source") or "") == state_id:
                return False
            attempts = list(edge.get("attempts") or [])
            if str(edge.get("target") or "") == state_id:
                if (self._edge_is_topology_referenced(
                        str(edge.get("action_edge_id") or ""))
                        or any(str(attempt.get("target") or "") != state_id
                               for attempt in attempts)):
                    return False
            for attempt in attempts:
                if str(attempt.get("source") or "") == state_id:
                    return False
                if str(attempt.get("target") or "") != state_id:
                    continue
                if (attempt.get("committed") is True
                        or attempt.get("landing_verified") is True):
                    return False
                index = attempt.get("action_index")
                if not isinstance(index, int) and not str(index).isdigit():
                    return False
                movable_indices.append(int(index))

        # Validation above is complete; only now mutate the append-only attempts.
        for event_index in movable_indices:
            self.update_action_event(event_index, target=alias_to)
        for edge in list(self.action_edges):
            if str(edge.get("target") or "") != state_id:
                continue
            if edge.get("attempts") or self._edge_is_topology_referenced(
                    str(edge.get("action_edge_id") or "")):
                return False
            self.action_edges.remove(edge)

        node = copy.deepcopy(self.graph.nodes[state_id])
        removed_page_id = str(node.get("page_id") or state_id)
        removed_variant_id = str(node.get("variant_id") or state_id)
        self.graph.remove_node(state_id)

        # Remove scroll evidence that was attributable only to this provisional
        # node. Shared scopes retain their other state memberships.
        for scope_id, record in list(self.scroll_ledger.items()):
            members = [
                str(value) for value in (record.get("state_ids") or [])
                if str(value) != state_id
            ]
            had_state = len(members) != len(record.get("state_ids") or [])
            if had_state:
                record["state_ids"] = members
                if not members:
                    self.scroll_ledger.pop(scope_id, None)

        valid_edge_ids = {
            str(edge.get("action_edge_id") or "") for edge in self.action_edges}
        live_node_capabilities = {
            str(capability_id)
            for _live_state, live_node in self.graph.nodes(data=True)
            for capability_id in (live_node.get("visible_capabilities") or [])
        }
        for capability_id, capability in list(self.capabilities.items()):
            sources = [
                source for source in (capability.get("source_elements") or [])
                if not isinstance(source, dict)
                or str(source.get("state_id") or "") != state_id
            ]
            capability["source_elements"] = sources
            capability["action_edge_ids"] = [
                edge_id for edge_id in (capability.get("action_edge_ids") or [])
                if str(edge_id) in valid_edge_ids
            ]
            if (not sources and not capability["action_edge_ids"]
                    and str(capability_id) not in live_node_capabilities):
                self.capabilities.pop(capability_id, None)

        valid_capability_ids = set(self.capabilities)
        for _live_state, live_node in self.graph.nodes(data=True):
            live_node["visible_capabilities"] = [
                capability_id
                for capability_id in (live_node.get("visible_capabilities") or [])
                if str(capability_id) in valid_capability_ids
            ]

        page = self.pages.get(removed_page_id)
        if isinstance(page, dict):
            variants = page.get("variants") or {}
            variant = variants.get(removed_variant_id)
            if isinstance(variant, dict):
                variant["state_ids"] = [
                    value for value in (variant.get("state_ids") or [])
                    if str(value) != state_id
                ]
                if not variant["state_ids"]:
                    variants.pop(removed_variant_id, None)
            if not variants:
                self.pages.pop(removed_page_id, None)

        # Recompute page/variant capability projections from the remaining node
        # membership so the discarded observation cannot survive as catalogue
        # evidence.
        for page_id, page in list(self.pages.items()):
            page_capabilities: List[str] = []
            variants = page.get("variants") or {}
            for variant_id, variant in list(variants.items()):
                state_ids = [
                    str(value) for value in (variant.get("state_ids") or [])
                    if str(value) in self.graph
                ]
                if not state_ids:
                    variants.pop(variant_id, None)
                    continue
                variant["state_ids"] = state_ids
                visible: List[str] = []
                for live_state in state_ids:
                    for capability_id in (
                            self.graph.nodes[live_state].get(
                                "visible_capabilities") or []):
                        capability_id = str(capability_id)
                        if (capability_id in valid_capability_ids
                                and capability_id not in visible):
                            visible.append(capability_id)
                variant["visible_capabilities"] = visible
                for capability_id in visible:
                    if capability_id not in page_capabilities:
                        page_capabilities.append(capability_id)
            page["capability_ids"] = page_capabilities
            if not variants:
                self.pages.pop(page_id, None)

        # Remove variant-local availability projections only when the discarded
        # variant no longer exists anywhere in the live graph.
        live_variants = {
            str(data.get("variant_id") or live_state)
            for live_state, data in self.graph.nodes(data=True)
        }
        if removed_variant_id not in live_variants:
            for capability in self.capabilities.values():
                for key in ("evidence_variants", "entry_variants"):
                    capability[key] = [
                        value for value in (capability.get(key) or [])
                        if str(value) != removed_variant_id
                    ]
                available = capability.get("available_when")
                if not isinstance(available, dict):
                    continue
                available["variant_ids"] = [
                    value for value in (available.get("variant_ids") or [])
                    if str(value) != removed_variant_id
                ]
                for key in (
                    "facts_by_variant", "availability_by_variant",
                    "requires_by_variant",
                ):
                    mapping = available.get(key)
                    if isinstance(mapping, dict):
                        mapping.pop(removed_variant_id, None)
        return True

    def record_scroll_scope(
        self,
        *,
        scope_id: str,
        state_id: str = "",
        region_id: str = "",
        role: str = "page",
        classification: str = "unknown",
        termination: str = "unknown",
        bottom_reached: bool = False,
        top_restored: bool = False,
        steps: int = 0,
        max_steps: int = 0,
        detail: str = "",
    ) -> Dict[str, Any]:
        """Upsert deterministic scroll exhaustion evidence for one scope.

        A completed shared-region observation is never downgraded by a later
        reuse/skip record.  Failed or capped attempts remain visible until a
        subsequent real observation proves both bottom reach and top restore.
        """
        scope_id = str(scope_id or "").strip()
        if not scope_id:
            raise ValueError("scroll scope_id is required")
        normalized_region_id = str(region_id or "").strip()
        if normalized_region_id:
            expected_scope_id = region_scroll_scope_id(normalized_region_id)
            if scope_id != expected_scope_id:
                raise ValueError(
                    "Region scroll evidence must use its canonical scope_id "
                    f"{expected_scope_id!r}, got {scope_id!r}")
        elif scope_id.startswith("region:"):
            raise ValueError(
                "Region scroll scope requires the matching region_id")
        incoming_complete = scroll_evidence_complete(
            classification=classification,
            termination=termination,
            bottom_reached=bottom_reached,
            top_restored=top_restored,
        )
        record = self.scroll_ledger.get(scope_id)
        if record is None:
            record = {
                "scope_id": scope_id,
                "state_ids": [],
                "region_id": str(region_id or ""),
                "role": str(role or "page"),
                "classification": str(classification or "unknown"),
                "termination": str(termination or "unknown"),
                "bottom_reached": bool(bottom_reached),
                "top_restored": bool(top_restored),
                "steps": max(0, int(steps or 0)),
                "max_steps": max(0, int(max_steps or 0)),
                "detail": str(detail or ""),
                "observations": 0,
            }
            self.scroll_ledger[scope_id] = record
        existing_complete = bool(record.get("complete"))
        if incoming_complete or not existing_complete:
            record.update({
                "region_id": str(region_id or record.get("region_id") or ""),
                "role": str(role or record.get("role") or "page"),
                "classification": str(classification or "unknown"),
                "termination": str(termination or "unknown"),
                "bottom_reached": bool(bottom_reached),
                "top_restored": bool(top_restored),
                "steps": max(0, int(steps or 0)),
                "max_steps": max(0, int(max_steps or 0)),
                "detail": str(detail or ""),
                "complete": bool(incoming_complete),
            })
        state_ids = record.setdefault("state_ids", [])
        if state_id and str(state_id) not in state_ids:
            state_ids.append(str(state_id))
        record["observations"] = int(record.get("observations", 0) or 0) + 1
        return record

    def _new_action_edge_id(self, payload: str) -> str:
        base = "ae_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        candidate = base
        suffix = 2
        known = {str(edge.get("action_edge_id")): edge for edge in self.action_edges}
        while candidate in known:
            edge = known[candidate]
            if edge.get("identity_payload") == payload:
                return candidate
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _ensure_action_edge(
        self,
        *,
        source: str,
        target: str,
        action: Any,
        element_id: str = "",
        element_label: str = "",
        semantic_description: str = "",
        region: str = "",
    ) -> Dict[str, Any]:
        semantic = _semantic_action(
            action,
            element_id=element_id,
            element_label=element_label,
            semantic_description=semantic_description,
            region=region,
        )
        source = str(source or "")
        target = str(target or "")
        exact = [
            edge for edge in self.action_edges
            if str(edge.get("source") or "") == source
            and str(edge.get("target") or "") == target
            and edge.get("action") == semantic
        ]
        if exact:
            return exact[0]
        # The first executions of a control may fail/no-effect before any target
        # is known.  Once one attempt verifies a landing, promote that unresolved
        # semantic edge in place so the earlier failures remain attempts of the
        # same button/function instead of becoming a parallel orphan edge.
        if target:
            unresolved = [
                edge for edge in self.action_edges
                if str(edge.get("source") or "") == source
                and not str(edge.get("target") or "")
                and edge.get("action") == semantic
            ]
            if len(unresolved) == 1:
                edge = unresolved[0]
                target_node = self.graph.nodes[target] if target in self.graph else {}
                edge["target"] = target
                edge["target_page_id"] = str(
                    target_node.get("page_id") or target)
                edge["target_variant_id"] = str(
                    target_node.get("variant_id") or target)
                edge["identity_payload"] = _edge_identity_payload(
                    source, target, semantic)
                self._refresh_action_edge(edge)
                return edge
        if not target:
            semantic_matches = [
                edge for edge in self.action_edges
                if str(edge.get("source") or "") == source
                and edge.get("action") == semantic
            ]
            if len(semantic_matches) == 1:
                return semantic_matches[0]

        payload = _edge_identity_payload(source, target, semantic)
        source_node = self.graph.nodes[source] if source in self.graph else {}
        target_node = self.graph.nodes[target] if target in self.graph else {}
        edge = {
            "action_edge_id": self._new_action_edge_id(payload),
            "identity_payload": payload,
            "source": source,
            "target": target,
            "source_page_id": str(source_node.get("page_id") or source),
            "source_variant_id": str(source_node.get("variant_id") or source),
            "target_page_id": str(target_node.get("page_id") or target),
            "target_variant_id": str(target_node.get("variant_id") or target),
            "action": semantic,
            "element_id": str(element_id or ""),
            "element_label": str(element_label or ""),
            "semantic_description": str(semantic_description or ""),
            "region": str(region or ""),
            "attempts": [],
            "attempt_count": 0,
            "routing_verified": False,
        }
        self.action_edges.append(edge)
        return edge

    def _find_attempt(
        self, event_index: int
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        for edge in reversed(self.action_edges):
            for attempt in reversed(edge.get("attempts") or []):
                if int(attempt.get("action_index", -1)) == int(event_index):
                    return edge, attempt
        raise ValueError(f"unknown transition event index: {event_index}")

    @staticmethod
    def _refresh_action_edge(edge: Dict[str, Any]) -> None:
        attempts = list(edge.get("attempts") or [])
        edge["attempt_count"] = len(attempts)
        target = str(edge.get("target") or "")
        edge["routing_verified"] = bool(target) and any(
            attempt.get("committed") is True
            and attempt.get("landing_verified") is True
            and str(attempt.get("target") or "") == target
            and str(attempt.get("outcome") or "").strip().lower()
            not in _NON_ROUTING_OUTCOMES
            for attempt in attempts
        )

    def _edge_is_topology_referenced(self, action_edge_id: str) -> bool:
        return any(
            action_edge_id in (data.get("action_edge_ids") or [])
            for _source, _target, data in self.graph.edges(data=True)
        )

    def _move_attempt_to_target(
        self,
        edge: Dict[str, Any],
        attempt: Dict[str, Any],
        target: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        target = str(target or "")
        if not target or str(edge.get("target") or "") == target:
            return edge, attempt
        target_edge = self._ensure_action_edge(
            source=str(edge.get("source") or ""),
            target=target,
            action=edge.get("action") or {},
            element_id=str(edge.get("element_id") or ""),
            element_label=str(edge.get("element_label") or ""),
            semantic_description=str(edge.get("semantic_description") or ""),
            region=str(edge.get("region") or ""),
        )
        edge.get("attempts", []).remove(attempt)
        attempt["action_edge_id"] = target_edge["action_edge_id"]
        target_edge.setdefault("attempts", []).append(attempt)
        self._refresh_action_edge(edge)
        self._refresh_action_edge(target_edge)
        if not edge.get("attempts") and not self._edge_is_topology_referenced(
                str(edge.get("action_edge_id") or "")):
            self.action_edges.remove(edge)
        return target_edge, attempt

    def add_transition(
        self,
        src: str,
        dst: str,
        action: Any,
        element_id: str = "",
        element_label: str = "",
        semantic_description: str = "",
        region: str = "",
        effect_verdict: str = "",
        effect_note: str = "",
        landing_verified: Optional[bool] = None,
        target_page_name: str = "",
        event_index: Optional[int] = None,
        event_indices: Optional[List[int]] = None,
        action_steps: int = 1,
        action_sequence: Optional[List[Any]] = None,
        transition_kind: str = "",
        effect_kind: str = "",
    ) -> int:
        """Commit a topology relation while retaining every semantic action."""
        if src not in self.graph or dst not in self.graph:
            missing = [node for node in (src, dst) if node not in self.graph]
            raise ValueError(
                "transition endpoints must be registered page variants first: "
                + ", ".join(str(node) for node in missing)
            )
        linked_event_indices = [
            int(index) for index in (event_indices or [])
            if isinstance(index, int) or str(index).isdigit()
        ]
        if event_index is None and linked_event_indices:
            event_index = linked_event_indices[-1]
        if event_index is None:
            event_index = self.record_action_event(
                source=src,
                target=dst,
                action=action,
                element_id=element_id,
                element_label=element_label,
                semantic_description=semantic_description,
                region=region,
                outcome=effect_verdict or "transitioned",
                detail=effect_note,
                landing_verified=landing_verified,
                target_page_name=target_page_name,
                committed=True,
            )
        if event_index not in linked_event_indices:
            linked_event_indices.append(event_index)
        for linked_index in linked_event_indices:
            self._mark_event_committed(
                linked_index,
                target=dst,
                outcome=effect_verdict or "transitioned",
                detail=effect_note,
                landing_verified=landing_verified,
                target_page_name=target_page_name,
            )

        linked_edge_ids: List[str] = []
        for linked_index in linked_event_indices:
            linked_edge, _attempt = self._find_attempt(linked_index)
            action_edge_id = str(linked_edge.get("action_edge_id") or "")
            if action_edge_id and action_edge_id not in linked_edge_ids:
                linked_edge_ids.append(action_edge_id)
        if len(linked_edge_ids) == 1:
            linked_edge = next(
                edge for edge in self.action_edges
                if edge.get("action_edge_id") == linked_edge_ids[0])
            linked_edge["action_steps"] = max(0, int(action_steps or 0))
            linked_edge["action_sequence"] = [
                _semantic_action(step) for step in (action_sequence or [])]
            linked_edge["transition_kind"] = str(transition_kind or "")
            linked_edge["effect_kind"] = str(effect_kind or "")
            self._refresh_action_edge(linked_edge)

        previous = self.graph.get_edge_data(src, dst, default={}) or {}
        action_indices = list(previous.get("action_indices") or [])
        for linked_index in linked_event_indices:
            if linked_index not in action_indices:
                action_indices.append(linked_index)
        action_edge_ids = list(previous.get("action_edge_ids") or [])
        for action_edge_id in linked_edge_ids:
            if action_edge_id not in action_edge_ids:
                action_edge_ids.append(action_edge_id)
        semantic = _semantic_action(
            action,
            element_id=element_id,
            element_label=element_label,
            semantic_description=semantic_description,
            region=region,
        )
        self.graph.add_edge(
            src,
            dst,
            action=semantic,
            element_id=element_id,
            element_label=element_label,
            semantic_description=semantic_description,
            region=region,
            effect_verdict=effect_verdict,
            effect_note=effect_note,
            landing_verified=landing_verified,
            target_page_name=target_page_name,
            timestamp=time.time(),
            action_index=event_index,
            action_indices=action_indices,
            action_edge_ids=action_edge_ids,
            transition_count=len(action_indices),
            action_steps=max(0, int(action_steps or 0)),
            action_sequence=[_semantic_action(step) for step in (action_sequence or [])],
            transition_kind=str(transition_kind or ""),
            effect_kind=str(effect_kind or ""),
            routing_verified=any(
                edge.get("routing_verified") is True
                for edge in self.action_edges
                if edge.get("action_edge_id") in action_edge_ids
            ),
        )
        self._record_capability_entry_execution(
            source=str(src),
            target=str(dst),
            element_id=str(element_id or ""),
            element_label=str(element_label or ""),
            region=str(region or ""),
            action_edge_ids=linked_edge_ids,
            effect_verdict=str(effect_verdict or ""),
            effect_note=str(effect_note or ""),
            landing_verified=landing_verified,
        )
        return event_index

    def record_action_event(
        self,
        *,
        source: str,
        action: Any,
        target: str = "",
        element_id: str = "",
        element_label: str = "",
        semantic_description: str = "",
        region: str = "",
        outcome: str = "attempted",
        detail: str = "",
        landing_verified: Optional[bool] = None,
        target_page_name: str = "",
        committed: bool = False,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append one attempt under its semantic action edge."""
        semantic = _semantic_action(
            action,
            element_id=element_id,
            element_label=element_label,
            semantic_description=semantic_description,
            region=region,
        )
        edge = self._ensure_action_edge(
            source=source,
            target=target,
            action=semantic,
            element_id=element_id,
            element_label=element_label,
            semantic_description=semantic_description,
            region=region,
        )
        self._action_counter += 1
        event_id = f"{self.app_name}:{self._action_counter}"
        attempt = {
            "attempt_id": event_id,
            "event_id": event_id,
            "action_index": self._action_counter,
            "action_edge_id": edge["action_edge_id"],
            "source": str(source or ""),
            "target": str(target or ""),
            "action": semantic,
            "element_id": str(element_id or ""),
            "element_label": str(element_label or ""),
            "semantic_description": str(semantic_description or ""),
            "region": str(region or ""),
            "outcome": str(outcome or "attempted"),
            "detail": str(detail or ""),
            "landing_verified": landing_verified,
            "target_page_name": str(target_page_name or ""),
            "committed": bool(committed),
            "timestamp": time.time(),
            "evidence": copy.deepcopy(evidence or {}),
        }
        edge.setdefault("attempts", []).append(attempt)
        self._refresh_action_edge(edge)
        return self._action_counter

    def _mark_event_committed(
        self,
        event_index: int,
        *,
        target: str,
        outcome: str,
        detail: str,
        landing_verified: Optional[bool],
        target_page_name: str,
    ) -> None:
        self.update_action_event(
            event_index,
            target=str(target or ""),
            outcome=str(outcome or "transitioned"),
            detail=str(detail or ""),
            landing_verified=landing_verified,
            target_page_name=str(target_page_name or ""),
            committed=True,
        )

    def update_action_event(self, event_index: int, **changes: Any) -> Dict[str, Any]:
        """Update mutable result fields without changing action identity."""
        mutable = {
            "target", "outcome", "detail", "landing_verified",
            "target_page_name", "committed", "evidence",
        }
        edge, attempt = self._find_attempt(event_index)
        for key, value in changes.items():
            if key not in mutable:
                raise ValueError(f"immutable or unknown event field: {key}")
            attempt[key] = (
                copy.deepcopy(value or {}) if key == "evidence" else value)
        edge, attempt = self._move_attempt_to_target(
            edge, attempt, str(attempt.get("target") or ""))
        self._refresh_action_edge(edge)
        return attempt

    def correct_action_event_semantics(
        self,
        event_index: int,
        *,
        action: Any,
        element_label: str,
        semantic_description: str = "",
        region: str = "",
    ) -> Dict[str, Any]:
        """Move one uncommitted attempt to its corrected semantic action edge."""
        edge, attempt = self._find_attempt(event_index)
        if attempt.get("committed") is True:
            raise ValueError("committed action semantics cannot be corrected")

        corrected_action = copy.deepcopy(
            action if isinstance(action, dict) else {})
        selector = dict(corrected_action.get("selector") or {})
        selector["element_label"] = str(element_label or "")
        selector["description"] = str(
            semantic_description or element_label or "")
        corrected_action["selector"] = selector
        semantic = _semantic_action(
            corrected_action,
            element_id=str(attempt.get("element_id") or ""),
            element_label=str(element_label or ""),
            semantic_description=str(
                semantic_description or element_label or ""),
            region=str(region or attempt.get("region") or ""),
        )
        target_edge = self._ensure_action_edge(
            source=str(attempt.get("source") or ""),
            target=str(attempt.get("target") or ""),
            action=semantic,
            element_id=str(attempt.get("element_id") or ""),
            element_label=str(element_label or ""),
            semantic_description=str(
                semantic_description or element_label or ""),
            region=str(region or attempt.get("region") or ""),
        )
        if target_edge is not edge:
            edge.get("attempts", []).remove(attempt)
            target_edge.setdefault("attempts", []).append(attempt)
            attempt["action_edge_id"] = target_edge["action_edge_id"]
        attempt.update({
            "action": semantic,
            "element_label": str(element_label or ""),
            "semantic_description": str(
                semantic_description or element_label or ""),
            "region": str(region or attempt.get("region") or ""),
        })
        self._refresh_action_edge(edge)
        self._refresh_action_edge(target_edge)
        if (target_edge is not edge and not edge.get("attempts")
                and not self._edge_is_topology_referenced(
                    str(edge.get("action_edge_id") or ""))):
            self.action_edges.remove(edge)
        return attempt

    def action_attempt(self, event_index: int) -> Dict[str, Any]:
        """Return one attempt record by its stable action index."""
        _edge, attempt = self._find_attempt(event_index)
        return attempt

    def merge_action_event_evidence(
        self, event_index: int, evidence: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge independent observer facts without erasing prior evidence."""
        edge, attempt = self._find_attempt(event_index)
        merged = copy.deepcopy(attempt.get("evidence") or {})
        merged.update(copy.deepcopy(evidence or {}))
        attempt["evidence"] = merged
        self._refresh_action_edge(edge)
        return attempt

    def append_effect_observation(
        self, event_index: int, observation: Any,
    ) -> Dict[str, Any]:
        """Append normalized effect evidence without changing attempt results."""
        from gui_rewalk.src.core.graph.effect_observation import (
            append_effect_observation,
        )

        edge, attempt = self._find_attempt(event_index)
        evidence = copy.deepcopy(attempt.get("evidence") or {})
        existing = evidence.get("effect_observations")
        if existing is None:
            existing = []
        if not isinstance(existing, list):
            raise ValueError("effect_observations must be an append-only list")
        observations = append_effect_observation(existing, observation)
        observations[-1]["observation_index"] = len(observations) - 1
        evidence["effect_observations"] = observations
        attempt["evidence"] = evidence
        self._refresh_action_edge(edge)
        return copy.deepcopy(observations[-1])
    def record_abnormal_button(
        self,
        *,
        state_id: str,
        element_id: str,
        element_uid: str,
        element_name: str,
        region: str,
        region_id: str,
        reason: str,
        detail: str = "",
        action: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a terminal button failure without fabricating a graph edge."""
        key = (state_id, element_uid or element_id or element_name, reason)
        now = time.time()
        for record in self.abnormal_buttons:
            existing = (
                record.get("state_id", ""),
                record.get("element_uid") or record.get("element_id")
                or record.get("element_name", ""),
                record.get("reason", ""),
            )
            if existing == key:
                record["occurrences"] = int(record.get("occurrences", 1)) + 1
                record["last_timestamp"] = now
                if detail:
                    record["detail"] = detail
                if evidence:
                    record["evidence"] = copy.deepcopy(evidence)
                return record
        record = {
            "state_id": state_id,
            "element_id": str(element_id or ""),
            "element_uid": str(element_uid or ""),
            "element_name": str(element_name or ""),
            "region": str(region or ""),
            "region_id": str(region_id or ""),
            "reason": str(reason or "unknown"),
            "detail": str(detail or ""),
            "action": action or {},
            "evidence": copy.deepcopy(evidence or {}),
            "occurrences": 1,
            "first_timestamp": now,
            "last_timestamp": now,
        }
        self.abnormal_buttons.append(record)
        return record

    def save(self, path: str) -> None:
        """Atomically persist the graph as node-link JSON."""
        if self._live_sync is not None:
            try:
                self._live_sync(self)
            except Exception:
                logger.exception(
                    "live_sync before save failed; refusing to persist a stale "
                    "snapshot")
                raise

        for edge in self.action_edges:
            edge["action"] = _semantic_action(
                edge.get("action") or {},
                element_id=str(edge.get("element_id") or ""),
                element_label=str(edge.get("element_label") or ""),
                semantic_description=str(edge.get("semantic_description") or ""),
                region=str(edge.get("region") or ""),
            )
            for attempt in edge.get("attempts") or []:
                attempt["action"] = copy.deepcopy(edge["action"])
            self._refresh_action_edge(edge)
        for _source, _target, edge in self.graph.edges(data=True):
            edge["action"] = _semantic_action(
                edge.get("action") or {},
                element_id=str(edge.get("element_id") or ""),
                element_label=str(edge.get("element_label") or ""),
                semantic_description=str(edge.get("semantic_description") or ""),
                region=str(edge.get("region") or ""),
            )
            edge["action_sequence"] = [
                _semantic_action(step) for step in (edge.get("action_sequence") or [])]

        data = nx.node_link_data(self.graph, edges="edges")
        data["app_name"] = self.app_name
        data["graph_schema_version"] = GRAPH_SCHEMA_VERSION
        data["action_counter"] = self._action_counter
        data["stop_reason"] = self.stop_reason
        data["abnormal_buttons"] = copy.deepcopy(self.abnormal_buttons)
        data["pages"] = copy.deepcopy(self.pages)
        data["capabilities"] = copy.deepcopy(self.capabilities)
        data["scroll_ledger"] = [
            copy.deepcopy(self.scroll_ledger[key])
            for key in sorted(self.scroll_ledger)
        ]
        data["action_edges"] = []
        for raw_edge in self.action_edges:
            edge = copy.deepcopy(raw_edge)
            edge.pop("identity_payload", None)
            data["action_edges"].append(edge)

        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        except Exception:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise

    @staticmethod
    def _normal_container(raw: Any, id_key: str) -> Dict[str, Dict[str, Any]]:
        if isinstance(raw, dict):
            return copy.deepcopy(raw)
        if isinstance(raw, list):
            result: Dict[str, Dict[str, Any]] = {}
            for ordinal, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get(id_key) or ordinal)
                result[identifier] = copy.deepcopy(item)
            return result
        return {}

    def _load_v3_action_edges(self, raw_edges: Any) -> None:
        items = list(raw_edges.values()) if isinstance(raw_edges, dict) else raw_edges
        if not isinstance(items, list):
            return
        used_ids: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            edge = copy.deepcopy(raw)
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            semantic = _semantic_action(
                edge.get("action") or {},
                element_id=str(edge.get("element_id") or ""),
                element_label=str(edge.get("element_label") or ""),
                semantic_description=str(edge.get("semantic_description") or ""),
                region=str(edge.get("region") or ""),
            )
            payload = _edge_identity_payload(source, target, semantic)
            action_edge_id = str(edge.get("action_edge_id") or "")
            if not action_edge_id or action_edge_id in used_ids:
                action_edge_id = self._new_action_edge_id(payload)
                suffix = 2
                base = action_edge_id
                while action_edge_id in used_ids:
                    action_edge_id = f"{base}_{suffix}"
                    suffix += 1
            used_ids.add(action_edge_id)
            edge.update({
                "action_edge_id": action_edge_id,
                "identity_payload": payload,
                "source": source,
                "target": target,
                "action": semantic,
                "element_id": str(edge.get("element_id") or ""),
                "element_label": str(edge.get("element_label") or ""),
                "semantic_description": str(edge.get("semantic_description") or ""),
                "region": str(edge.get("region") or ""),
            })
            source_node = self.graph.nodes[source] if source in self.graph else {}
            target_node = self.graph.nodes[target] if target in self.graph else {}
            edge.setdefault(
                "source_page_id", str(source_node.get("page_id") or source))
            edge.setdefault(
                "source_variant_id", str(source_node.get("variant_id") or source))
            edge.setdefault(
                "target_page_id", str(target_node.get("page_id") or target))
            edge.setdefault(
                "target_variant_id", str(target_node.get("variant_id") or target))
            attempts: List[Dict[str, Any]] = []
            for raw_attempt in raw.get("attempts") or []:
                if not isinstance(raw_attempt, dict):
                    continue
                attempt = copy.deepcopy(raw_attempt)
                attempt.update({
                    "action_edge_id": action_edge_id,
                    "source": str(attempt.get("source") or source),
                    "target": str(attempt.get("target") or target),
                    "action": copy.deepcopy(semantic),
                    "element_id": str(attempt.get("element_id") or edge["element_id"]),
                    "element_label": str(
                        attempt.get("element_label") or edge["element_label"]),
                    "semantic_description": str(
                        attempt.get("semantic_description")
                        or edge["semantic_description"]),
                    "region": str(attempt.get("region") or edge["region"]),
                    "evidence": copy.deepcopy(attempt.get("evidence") or {}),
                })
                event_id = str(
                    attempt.get("attempt_id") or attempt.get("event_id") or "")
                attempt["attempt_id"] = event_id
                attempt["event_id"] = event_id
                attempts.append(attempt)
            edge["attempts"] = attempts
            self._refresh_action_edge(edge)
            self.action_edges.append(edge)

    def _append_legacy_attempt(self, raw: Dict[str, Any]) -> int:
        preferred = int(raw.get("action_index", 0) or 0)
        used = {
            int(item.get("action_index", 0) or 0)
            for item in self.transition_events
        }
        if preferred <= 0 or preferred in used:
            preferred = max(used | {self._action_counter}, default=0) + 1
        self._action_counter = max(self._action_counter, preferred)
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        semantic = _semantic_action(
            raw.get("action") or {},
            element_id=str(raw.get("element_id") or ""),
            element_label=str(raw.get("element_label") or ""),
            semantic_description=str(raw.get("semantic_description") or ""),
            region=str(raw.get("region") or ""),
        )
        edge = self._ensure_action_edge(
            source=source,
            target=target,
            action=semantic,
            element_id=str(raw.get("element_id") or ""),
            element_label=str(raw.get("element_label") or ""),
            semantic_description=str(raw.get("semantic_description") or ""),
            region=str(raw.get("region") or ""),
        )
        event_id = str(raw.get("event_id") or f"{self.app_name}:{preferred}")
        attempt = copy.deepcopy(raw)
        attempt.update({
            "attempt_id": str(raw.get("attempt_id") or event_id),
            "event_id": event_id,
            "action_index": preferred,
            "action_edge_id": edge["action_edge_id"],
            "source": source,
            "target": target,
            "action": semantic,
            "element_id": str(raw.get("element_id") or ""),
            "element_label": str(raw.get("element_label") or ""),
            "semantic_description": str(raw.get("semantic_description") or ""),
            "region": str(raw.get("region") or ""),
            "outcome": str(raw.get("outcome") or "attempted"),
            "detail": str(raw.get("detail") or ""),
            "landing_verified": raw.get("landing_verified"),
            "target_page_name": str(raw.get("target_page_name") or ""),
            "committed": bool(raw.get("committed")),
            "timestamp": float(raw.get("timestamp", 0.0) or 0.0),
            "evidence": copy.deepcopy(raw.get("evidence") or {}),
        })
        edge.setdefault("attempts", []).append(attempt)
        self._refresh_action_edge(edge)
        return preferred

    def _relink_topology(self) -> None:
        by_id = {
            str(edge.get("action_edge_id") or ""): edge
            for edge in self.action_edges
        }
        for source, target, data in self.graph.edges(data=True):
            data["action"] = _semantic_action(
                data.get("action") or {},
                element_id=str(data.get("element_id") or ""),
                element_label=str(data.get("element_label") or ""),
                semantic_description=str(data.get("semantic_description") or ""),
                region=str(data.get("region") or ""),
            )
            data["action_sequence"] = [
                _semantic_action(step) for step in (data.get("action_sequence") or [])]
            declared_indexes = {
                int(index) for index in (
                    list(data.get("action_indices") or [])
                    + [data.get("action_index")]
                )
                if isinstance(index, int) or str(index).isdigit()
            }
            action_edge_ids = [
                str(action_edge_id)
                for action_edge_id in (data.get("action_edge_ids") or [])
                if str(action_edge_id) in by_id
                and str(by_id[str(action_edge_id)].get("source") or "") == str(source)
                and str(by_id[str(action_edge_id)].get("target") or "") == str(target)
            ]
            for action_edge in self.action_edges:
                if str(action_edge.get("source") or "") != str(source) \
                        or str(action_edge.get("target") or "") != str(target):
                    continue
                attempts = list(action_edge.get("attempts") or [])
                matches_index = bool(declared_indexes) and any(
                    int(attempt.get("action_index", -1)) in declared_indexes
                    for attempt in attempts)
                committed = any(attempt.get("committed") is True for attempt in attempts)
                action_edge_id = str(action_edge.get("action_edge_id") or "")
                if (matches_index or (not declared_indexes and committed)) \
                        and action_edge_id not in action_edge_ids:
                    action_edge_ids.append(action_edge_id)
            data["action_edge_ids"] = action_edge_ids
            all_indexes = list(data.get("action_indices") or [])
            for action_edge_id in action_edge_ids:
                for attempt in by_id[action_edge_id].get("attempts") or []:
                    index = int(attempt.get("action_index", 0) or 0)
                    if index and index not in all_indexes:
                        all_indexes.append(index)
            data["action_indices"] = all_indexes
            data["transition_count"] = len(all_indexes)
            data["routing_verified"] = any(
                by_id[action_edge_id].get("routing_verified") is True
                for action_edge_id in action_edge_ids)

    def _rebuild_page_catalog(self) -> None:
        previous = copy.deepcopy(self.pages)
        self.pages = {}
        for state_id, node in self.graph.nodes(data=True):
            page_id = str(node.get("page_id") or state_id)
            variant_id = str(node.get("variant_id") or state_id)
            node["page_id"] = page_id
            node["variant_id"] = variant_id
            node.setdefault("variant_signature", None)
            node.setdefault("observed_facts", {})
            node.setdefault("visible_capabilities", [])
            self._register_page_variant(
                state_id=str(state_id),
                page_id=page_id,
                variant_id=variant_id,
                page_name=str(node.get("page_name") or ""),
                variant_signature=node.get("variant_signature"),
                observed_facts=node.get("observed_facts") or {},
                visible_capabilities=node.get("visible_capabilities") or [],
            )
        # Preserve page-level annotations and capability references, but never
        # copy historical state membership back over the node-derived catalog.
        for page_id, page in self.pages.items():
            old_page = previous.get(page_id)
            if not isinstance(old_page, dict):
                continue
            if not page.get("semantic_name") and old_page.get("semantic_name"):
                page["semantic_name"] = str(old_page["semantic_name"])
            for key, value in old_page.items():
                if key in {"page_id", "semantic_name", "variants"}:
                    continue
                if isinstance(value, list):
                    values = list(page.get(key) or [])
                    for item in value:
                        if item not in values:
                            values.append(copy.deepcopy(item))
                    page[key] = values
                else:
                    page.setdefault(key, copy.deepcopy(value))
            old_variants = old_page.get("variants") or {}
            for variant_id, variant in page.get("variants", {}).items():
                old_variant = old_variants.get(variant_id)
                if not isinstance(old_variant, dict):
                    continue
                for key, value in old_variant.items():
                    if key in {
                        "variant_id", "state_ids", "variant_signature",
                        "observed_facts", "visible_capabilities",
                    }:
                        continue
                    variant.setdefault(key, copy.deepcopy(value))

    def _migrate_legacy_page_identity(self) -> None:
        """Project schema-v1/v2 execution states into semantic pages/variants."""
        try:
            from gui_rewalk.src.core.visual_traversal.visual_state import (
                compute_page_id,
                compute_variant_id,
                compute_variant_signature,
                observed_variant_facts,
                semantic_page_key,
            )
        except Exception:
            logger.exception(
                "page/variant migration helpers unavailable; retaining legacy ids")
            return
        self.pages = {}
        for state_id, node in self.graph.nodes(data=True):
            page_name = str(node.get("page_name") or "")
            elements = node.get("elements") or []
            page_id = compute_page_id(
                page_name,
                semantic_key=(semantic_page_key(page_name, elements)
                              if page_name else f"state:{state_id}"),
                namespace=self.app_name,
            )
            facts = observed_variant_facts(elements)
            variant_id = compute_variant_id(page_id, facts)
            node.update({
                "app_name": str(node.get("app_name") or self.app_name),
                "page_id": page_id,
                "variant_id": variant_id,
                "page_identity_version": "semantic_page_variant_v1",
                "variant_signature": compute_variant_signature(facts),
                "observed_facts": facts,
                "visible_capabilities": list(
                    node.get("visible_capabilities") or []),
            })

    def _repair_capability_variant_membership(self) -> None:
        """Rebuild capability availability from its grounded source States."""
        for capability in self.capabilities.values():
            if not isinstance(capability, dict):
                continue
            source_variants: set[str] = set()
            facts_by_variant: Dict[str, Dict[str, Any]] = {}
            for source_ref in capability.get("source_elements") or []:
                if not isinstance(source_ref, dict):
                    continue
                state_id = str(source_ref.get("state_id") or "")
                if state_id not in self.graph:
                    continue
                node = self.graph.nodes[state_id]
                variant_id = str(node.get("variant_id") or state_id)
                source_ref["variant_id"] = variant_id
                source_variants.add(variant_id)
                facts_by_variant.setdefault(
                    variant_id,
                    copy.deepcopy(dict(node.get("observed_facts") or {})),
                )
            if not source_variants:
                continue
            ordered_variants = sorted(source_variants)
            capability["entry_variants"] = list(ordered_variants)
            capability["evidence_variants"] = list(ordered_variants)
            available = capability.setdefault("available_when", {})
            available["variant_ids"] = list(ordered_variants)
            available["facts_by_variant"] = facts_by_variant
            fallback_status = str(
                capability.get("availability_status") or "discovered")
            fallback_requires = copy.deepcopy(
                list(capability.get("requires") or []))
            available["availability_by_variant"] = {
                variant_id: fallback_status
                for variant_id in ordered_variants
            }
            available["requires_by_variant"] = {
                variant_id: copy.deepcopy(fallback_requires)
                for variant_id in ordered_variants
            }

    @classmethod
    def load(cls, path: str) -> "StateGraph":
        """Load schema v3 and migrate v1/v2 node-link graphs."""
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)

        app_name = data.pop("app_name", "unknown")
        schema_version = int(data.pop("graph_schema_version", 1) or 1)
        if schema_version > GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported graph schema version {schema_version}; "
                f"max supported is {GRAPH_SCHEMA_VERSION}")
        action_counter = data.pop("action_counter", 0)
        stop_reason = data.pop("stop_reason", "incomplete")
        abnormal_buttons = data.pop("abnormal_buttons", [])
        transition_events = data.pop("transition_events", [])
        raw_action_edges = data.pop("action_edges", [])
        raw_pages = data.pop("pages", {})
        raw_capabilities = data.pop("capabilities", {})
        raw_scroll_ledger = data.pop("scroll_ledger", {})
        edges_key = "edges" if "edges" in data else "links"

        graph = cls(app_name)
        graph.graph = nx.node_link_graph(data, edges=edges_key)
        for _state_id, node in graph.graph.nodes(data=True):
            node.pop("page_anchor_tokens", None)
            if node.get("page_identity_version") == "hierarchical_page_identity_v1":
                node["page_identity_version"] = "semantic_page_variant_v1"
        graph.pages = graph._normal_container(raw_pages, "page_id")
        graph.capabilities = graph._normal_container(
            raw_capabilities, "capability_id")
        graph.scroll_ledger = graph._normal_container(
            raw_scroll_ledger, "scope_id")
        if schema_version >= 3 and raw_action_edges:
            graph._load_v3_action_edges(raw_action_edges)
        else:
            topology_by_index: Dict[int, tuple[Any, Any, Dict[str, Any]]] = {}
            for source, target, edge in graph.graph.edges(data=True):
                indexes = list(edge.get("action_indices") or [])
                indexes.append(edge.get("action_index"))
                for index in indexes:
                    if isinstance(index, int) or str(index).isdigit():
                        topology_by_index[int(index)] = (source, target, edge)
            for raw in transition_events or []:
                if not isinstance(raw, dict):
                    continue
                migrated = copy.deepcopy(raw)
                topology = topology_by_index.get(
                    int(migrated.get("action_index", 0) or 0))
                if topology is not None:
                    source, target, edge = topology
                    migrated["source"] = str(migrated.get("source") or source)
                    migrated["target"] = str(migrated.get("target") or target)
                    for key, fallback in (
                        ("action", edge.get("action") or {}),
                        ("element_id", edge.get("element_id") or ""),
                        ("element_label", edge.get("element_label") or ""),
                        ("semantic_description", edge.get("semantic_description") or ""),
                        ("region", edge.get("region") or ""),
                        ("landing_verified", edge.get("landing_verified")),
                        ("target_page_name", edge.get("target_page_name") or ""),
                    ):
                        if migrated.get(key) in (None, "", {}):
                            migrated[key] = fallback
                graph._append_legacy_attempt(migrated)

            existing_indexes = {
                int(attempt.get("action_index", 0) or 0)
                for attempt in graph.transition_events
            }
            for source, target, edge in graph.graph.edges(data=True):
                declared = [
                    int(index) for index in (
                        list(edge.get("action_indices") or [])
                        + [edge.get("action_index")]
                    )
                    if isinstance(index, int) or str(index).isdigit()
                ]
                if any(index in existing_indexes for index in declared):
                    continue
                graph._append_legacy_attempt({
                    "event_id": f"{app_name}:{declared[-1] if declared else 0}",
                    "action_index": declared[-1] if declared else 0,
                    "source": str(source),
                    "target": str(target),
                    "action": edge.get("action") or {},
                    "element_id": str(edge.get("element_id") or ""),
                    "element_label": str(edge.get("element_label") or ""),
                    "semantic_description": str(
                        edge.get("semantic_description") or ""),
                    "region": str(edge.get("region") or ""),
                    "outcome": str(edge.get("effect_verdict") or "transitioned"),
                    "detail": str(edge.get("effect_note") or ""),
                    "landing_verified": edge.get("landing_verified"),
                    "target_page_name": str(edge.get("target_page_name") or ""),
                    "committed": True,
                    "timestamp": float(edge.get("timestamp", 0.0) or 0.0),
                    "evidence": {},
                    "legacy_reconstructed": True,
                })
        graph._relink_topology()
        if schema_version < 3:
            graph._migrate_legacy_page_identity()
        graph._rebuild_page_catalog()
        graph._repair_capability_variant_membership()
        max_event = max(
            (int(item.get("action_index", 0) or 0)
             for item in graph.transition_events),
            default=0,
        )
        graph._action_counter = max(int(action_counter or 0), max_event)
        graph.stop_reason = str(stop_reason or "incomplete")
        graph.abnormal_buttons = list(abnormal_buttons or [])
        return graph

    @property
    def transition_events(self) -> List[Dict[str, Any]]:
        """Read-only schema-v2 compatibility view over nested attempts."""
        return sorted(
            [
                copy.deepcopy(attempt)
                for edge in self.action_edges
                for attempt in (edge.get("attempts") or [])
            ],
            key=lambda item: int(item.get("action_index", 0) or 0),
        )

    @property
    def routing_graph(self) -> nx.DiGraph:
        """Derived route view containing only explicitly verified landings."""
        route = nx.DiGraph()
        route.graph.update(copy.deepcopy(self.graph.graph))
        route.add_nodes_from(
            (node, copy.deepcopy(data)) for node, data in self.graph.nodes(data=True))
        by_id = {
            str(edge.get("action_edge_id") or ""): edge
            for edge in self.action_edges
        }
        for source, target, topology in self.graph.edges(data=True):
            verified = [
                by_id[action_edge_id]
                for action_edge_id in (topology.get("action_edge_ids") or [])
                if action_edge_id in by_id
                and by_id[action_edge_id].get("routing_verified") is True
            ]
            if not verified:
                continue
            representative = min(
                verified,
                key=lambda edge: (
                    int(edge.get("action_steps", topology.get("action_steps", 1)) or 1),
                    str(edge.get("action_edge_id") or ""),
                ),
            )
            attempts = [
                attempt for attempt in (representative.get("attempts") or [])
                if attempt.get("committed") is True
                and attempt.get("landing_verified") is True
                and str(attempt.get("outcome") or "").strip().lower()
                not in _NON_ROUTING_OUTCOMES
            ]
            latest = max(
                attempts,
                key=lambda attempt: int(attempt.get("action_index", 0) or 0),
            )
            attrs = copy.deepcopy(topology)
            route_contexts = sorted({
                str((attempt.get("evidence") or {}).get("route_context") or "")
                for attempt in attempts
                if str((attempt.get("evidence") or {}).get("route_context") or "")
            })
            attrs.update({
                "action": copy.deepcopy(representative.get("action") or {}),
                "element_id": str(representative.get("element_id") or ""),
                "element_label": str(representative.get("element_label") or ""),
                "semantic_description": str(
                    representative.get("semantic_description") or ""),
                "region": str(representative.get("region") or ""),
                "effect_verdict": str(latest.get("outcome") or ""),
                "effect_note": str(latest.get("detail") or ""),
                "landing_verified": True,
                "target_page_name": str(latest.get("target_page_name") or ""),
                "action_index": int(latest.get("action_index", 0) or 0),
                "action_edge_ids": [
                    str(edge.get("action_edge_id")) for edge in verified],
                "routing_verified": True,
                "route_contexts": route_contexts,
                "action_steps": int(
                    representative.get("action_steps", attrs.get("action_steps", 1))
                    or 1),
                "action_sequence": copy.deepcopy(
                    representative.get("action_sequence") or []),
                "transition_kind": str(
                    representative.get("transition_kind") or ""),
                "effect_kind": str(
                    representative.get("effect_kind")
                    or attrs.get("effect_kind") or ""),
            })
            route.add_edge(source, target, **attrs)
        return route

    def routing_view(self) -> nx.DiGraph:
        """Method alias for callers that prefer an explicit view constructor."""
        return self.routing_graph

    def coverage_view(self) -> Dict[str, Any]:
        """Derived exploration view; no duplicate coverage graph is stored."""
        outcomes: Dict[str, int] = {}
        for attempt in self.transition_events:
            outcome = str(attempt.get("outcome") or "unknown")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return {
            "pages": len(self.pages),
            "variants": sum(
                len((page.get("variants") or {}))
                for page in self.pages.values()
                if isinstance(page, dict)
            ),
            "action_edges": len(self.action_edges),
            "attempts": self.num_transition_events,
            "attempt_outcomes": dict(sorted(outcomes.items())),
            "scroll_scopes": {
                "total": len(self.scroll_ledger),
                "complete": sum(
                    item.get("complete") is True
                    for item in self.scroll_ledger.values()),
                "incomplete": sum(
                    item.get("complete") is not True
                    for item in self.scroll_ledger.values()),
            },
            "capabilities": {
                "discovered": sum(
                    str(item.get("status") or "") == "discovered"
                    for item in self.capabilities.values()),
                "verified": sum(
                    str(item.get("status") or "") == "verified"
                    for item in self.capabilities.values()),
            },
        }

    def capability_view(self) -> Dict[str, Any]:
        """Derived canonical Page -> Variant -> Capability presentation view."""
        return {
            "app_name": self.app_name,
            "pages": copy.deepcopy(self.pages),
            "capabilities": copy.deepcopy(self.capabilities),
        }

    @property
    def num_nodes(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def num_edges(self) -> int:
        return self.graph.number_of_edges()

    @property
    def num_transition_events(self) -> int:
        return len(self.transition_events)
