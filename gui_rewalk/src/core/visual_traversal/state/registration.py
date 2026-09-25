"""Registration stage for visual observations."""
from __future__ import annotations

import copy
import logging
import os
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple

from gui_rewalk.src.core.graph.state_graph import StateGraph
from .. import visual_relocate as _reloc
from ..capability_discovery import discover_capabilities, normalize_semantic_text
from ..runtime.contracts import PerceptionUnavailable
from .identity import compute_variant_signature, signature_names
from .matching import assign_element_uids

logger = logging.getLogger(__name__)

_PAGE_IDENTITY_VERSION = "semantic_page_variant_v1"
_PASSIVE_FEEDBACK_REFRESH_LIMIT = 2
_PASSIVE_FEEDBACK_REFRESH_DELAY = 1.0


class RegistrationHost(Protocol):
    """Engine capabilities consumed by registration orchestration."""
    app_name: str
    graph_save_path: str


def retry_semantic_scroll_audit(
        self: RegistrationHost, obs: Dict[str, Any], state_id: str) -> bool:
    """Repeat only an incomplete semantic scroll audit on the current State.

    A normal semantic revisit preserves the State's durable Region table.
    Completion recovery reuses that same table and its observation geometry;
    it does not ask perception to partition the known State again.
    """
    if (not getattr(self.perception, "use_semantic_inventory", False)
            or not getattr(self, "_scroll_aggregate_enabled", False)):
        return False
    data = self._state_data.setdefault(str(state_id), {})
    all_blocks = copy.deepcopy(list(data.get("semantic_blocks") or []))
    all_elements = copy.deepcopy(list(data.get("elements") or []))
    stable_blocks = copy.deepcopy(all_blocks)
    stable_elements = copy.deepcopy(all_elements)
    incomplete_region_ids = {
        str(record.get("region_id") or "")
        for record in getattr(
            getattr(self, "graph", None), "scroll_ledger", {}).values()
        if (
            isinstance(record, dict)
            and record.get("complete") is not True
            and str(record.get("region_id") or "")
        )
    }
    if incomplete_region_ids:
        stable_blocks = [
            block for block in stable_blocks
            if str(block.get("region_id") or "") in incomplete_region_ids
        ]
        stable_elements = [
            element for element in stable_elements
            if str(getattr(element, "region_id", "") or "")
            in incomplete_region_ids
        ]
    if not stable_blocks:
        raise PerceptionUnavailable(
            "semantic scroll audit retry has no stable State inventory")

    bboxes = {}
    for block in stable_blocks:
        region_id = str(block.get("region_id") or "")
        bbox = block.get("viewport_bbox_1000")
        if (not region_id or not isinstance(bbox, list)
                or len(bbox) != 4):
            raise PerceptionUnavailable(
                "semantic scroll audit retry has no stable Region viewport")
        bboxes[region_id] = list(bbox)

    try:
        fresh_obs = self.env.step({"action_type": "WAIT"}, pause=1.0)
    except Exception as exc:
        raise PerceptionUnavailable(
            f"semantic scroll audit retry could not refresh viewport: {exc}")
    shot = (fresh_obs or {}).get("screenshot")
    if not shot:
        raise PerceptionUnavailable(
            "semantic scroll audit retry refresh has no screenshot")

    from .block_identity import _crop_blocks
    crops = _crop_blocks(shot, bboxes)
    if len(crops) != len(stable_blocks):
        raise PerceptionUnavailable(
            "semantic scroll audit retry could not crop every stable Region")

    sentinel = object()
    saved_data = {
        key: data.get(key, sentinel)
        for key in ("_semantic_scroll_blocks", "_semantic_scroll_region_crops")
    }
    saved_attrs = {
        key: self.__dict__.get(key, sentinel)
        for key in (
            "_semantic_scroll_seed",
            "_semantic_scroll_seed_region_crops",
            "_semantic_scroll_seed_region_bboxes",
            "_semantic_scroll_force_top",
            "_scroll_node_local_functions",
        )
    }
    saved_blocks = self.perception.last_semantic_blocks
    completed_region_crops = {}
    completed_blocks = []
    updated_elements = list(stable_elements)
    try:
        self.perception.last_semantic_blocks = stable_blocks
        self._semantic_scroll_seed = list(stable_elements)
        self._semantic_scroll_seed_region_crops = dict(crops)
        self._semantic_scroll_seed_region_bboxes = dict(bboxes)
        self._semantic_scroll_force_top = True
        updated_elements = list(self._scroll_aggregate(
            fresh_obs, stable_elements, state_id=str(state_id)))
        completed_region_crops = dict(
            data.get("_semantic_scroll_region_crops") or {})
        completed_blocks = copy.deepcopy(list(
            data.get("_semantic_scroll_blocks") or stable_blocks))
    finally:
        self.perception.last_semantic_blocks = saved_blocks
        for key, value in saved_attrs.items():
            if value is sentinel:
                self.__dict__.pop(key, None)
            else:
                self.__dict__[key] = value
        for key, value in saved_data.items():
            if value is sentinel:
                data.pop(key, None)
            else:
                data[key] = value
    if completed_region_crops:
        completed_region_ids = {
            str(region_id)
            for region_id in completed_region_crops
            if str(region_id)
        }
        completed_blocks = [
            block for block in completed_blocks
            if str(block.get("region_id") or "") in completed_region_ids
        ]
        replacement_elements = [
            element for element in updated_elements
            if str(getattr(element, "region_id", "") or "")
            in completed_region_ids
        ]
        merged_elements = []
        inserted_regions = set()
        replacements_by_region = {
            region_id: [
                element for element in replacement_elements
                if str(getattr(element, "region_id", "") or "") == region_id
            ]
            for region_id in completed_region_ids
        }
        for element in all_elements:
            region_id = str(getattr(element, "region_id", "") or "")
            if region_id not in completed_region_ids:
                merged_elements.append(element)
                continue
            if region_id not in inserted_regions:
                merged_elements.extend(replacements_by_region.get(region_id, []))
                inserted_regions.add(region_id)
        for block in completed_blocks:
            region_id = str(block.get("region_id") or "")
            if region_id not in inserted_regions:
                merged_elements.extend(replacements_by_region.get(region_id, []))
                inserted_regions.add(region_id)

        renumber = getattr(self, "_renumber_unique", None)
        if callable(renumber):
            renumber(merged_elements)
        else:
            for index, element in enumerate(merged_elements):
                element.id = index
        _refresh_semantic_block_members(completed_blocks, merged_elements)

        completed_by_region = {
            str(block.get("region_id") or ""): block
            for block in completed_blocks
        }
        merged_blocks = []
        written_regions = set()
        for block in all_blocks:
            region_id = str(block.get("region_id") or "")
            replacement = completed_by_region.get(region_id)
            if replacement is None:
                merged_blocks.append(block)
                continue
            merged = copy.deepcopy(block)
            merged.update(copy.deepcopy(replacement))
            merged_blocks.append(merged)
            written_regions.add(region_id)
        for region_id, block in completed_by_region.items():
            if region_id not in written_regions:
                merged_blocks.append(block)
        for block in merged_blocks:
            region_id = str(block.get("region_id") or "")
            members = [
                element for element in merged_elements
                if str(getattr(element, "region_id", "") or "") == region_id
            ]
            block["element_ids"] = [
                getattr(element, "id", None) for element in members]
            block["element_names"] = [
                str(getattr(element, "name", "") or "")
                for element in members]

        data["elements"] = merged_elements
        data["semantic_blocks"] = merged_blocks

        registry = getattr(self, "registry", None)
        set_buttons = getattr(registry, "set_buttons", None)
        if callable(set_buttons):
            set_buttons(str(state_id), merged_elements)
        page_name = str(data.get("page_name") or "")
        page_id = str(data.get("page_id") or state_id)
        variant_id = str(data.get("variant_id") or state_id)
        record_variant = getattr(registry, "record_page_variant", None)
        if callable(record_variant):
            page_id, variant_id = record_variant(
                str(state_id), page_name, elements=merged_elements,
                namespace=self.app_name, persisted_page_id=page_id)
        variant_facts = getattr(registry, "variant_facts_of", None)
        observed_facts = (
            variant_facts(str(state_id))
            if callable(variant_facts)
            else dict(data.get("observed_facts") or {}))
        variant_sig = compute_variant_signature(observed_facts)
        capabilities = discover_capabilities(
            page_id=page_id, variant_id=variant_id, state_id=str(state_id),
            elements=merged_elements)
        visible_ids = [
            item["capability_id"] for item in capabilities
            if item.get("capability_id")]
        register_capabilities = getattr(
            getattr(self, "graph", None),
            "register_capability_candidates", None)
        if callable(register_capabilities):
            visible_ids = register_capabilities(
                str(state_id), capabilities)
        data.update({
            "page_id": page_id,
            "variant_id": variant_id,
            "observed_facts": observed_facts,
            "visible_capabilities": list(visible_ids),
        })

        elem_dicts = [element.to_dict() for element in merged_elements]
        native_graph = getattr(getattr(self, "graph", None), "graph", None)
        if native_graph is not None and str(state_id) in native_graph:
            node = native_graph.nodes[str(state_id)]
            node["elements"] = copy.deepcopy(elem_dicts)
            node["semantic_blocks"] = copy.deepcopy(merged_blocks)
            node["page_id"] = page_id
            node["variant_id"] = variant_id
            node["variant_signature"] = copy.deepcopy(variant_sig)
            node["observed_facts"] = copy.deepcopy(observed_facts)
            node["visible_capabilities"] = list(visible_ids)
        update_observation = getattr(
            self.writer, "update_node_observation", None)
        if callable(update_observation):
            update_observation(
                str(state_id), elements=elem_dicts, page_name=page_name,
                page_id=page_id, variant_id=variant_id,
                page_identity_version=str(
                    data.get("page_identity_version")
                    or _PAGE_IDENTITY_VERSION),
                variant_signature=variant_sig,
                observed_facts=observed_facts,
                visible_capabilities=list(visible_ids),
                semantic_blocks=merged_blocks,
                perception_mode=str(
                    data.get("perception_mode") or "semantic_inventory"),
                geometry_mode=str(data.get("geometry_mode") or ""),
            )
        region_registry = getattr(self, "region_registry", None)
        record_mapped = getattr(
            region_registry, "record_mapped_elements", None)
        if callable(record_mapped):
            for block in merged_blocks:
                region_id = str(block.get("region_id") or "")
                if region_id:
                    record_mapped(
                        region_id,
                        [element.name for element in merged_elements
                         if str(getattr(
                             element, "region_id", "") or "") == region_id])
        persist_capabilities = getattr(
            self, "_persist_online_capabilities", None)
        if callable(persist_capabilities):
            persist_capabilities(str(state_id))
        maybe_save = getattr(self, "_maybe_save", None)
        if callable(maybe_save):
            maybe_save()
    for region_id, payload in completed_region_crops.items():
        self.writer.save_region_image(str(state_id), str(region_id), payload)
    return True


def _landing_navigation_context(self) -> str:
    """Describe the semantic source/action chain for sparse landing frames."""
    transition = getattr(self, "_pending_transition", None) or {}
    source_id = str(transition.get("source_id") or "")
    lines = []
    if source_id:
        source = self._state_data.get(source_id) or {}
        lines.extend([
            f"Previous page: {str(source.get('page_name') or '(unknown)')}",
            f"Action/control that opened the current frame: "
            f"{str(transition.get('clicked_label') or '(unknown)')}",
        ])
        graph = getattr(getattr(self, "graph", None), "graph", None)
        if graph is not None and source_id in graph:
            incoming = []
            for parent, _target, data in graph.in_edges(source_id, data=True):
                label = str((data or {}).get("element_label") or "").strip()
                parent_name = str(
                    (self._state_data.get(str(parent)) or {}).get("page_name") or "")
                if label:
                    incoming.append(
                        f"The previous page itself was reached from "
                        f"{parent_name or parent} via {label}.")
            lines.extend(sorted(set(incoming))[:3])
    state_data = getattr(self, "_state_data", {}) or {}
    known_names = sorted({
        " ".join(str(data.get("page_name") or "").split())
        for data in state_data.values()
        if str(data.get("page_name") or "").strip()
    }, key=str.casefold)
    if known_names:
        lines.append(
            "Registered operable-interface names: " + "; ".join(known_names))
        lines.append(
            "If the current active interface matches one of them, reuse that "
            "name exactly. Otherwise create a concise new name that distinguishes "
            "the frontmost function.")
    return "\n".join(lines)


def _semantic_inventory_for_landing(
        self, shot: bytes, *, force_refresh: bool = False):
    """Call the current perception contract with transition context."""
    context = _landing_navigation_context(self)
    try:
        return self.perception.semantic_inventory(
            shot, navigation_context=context, force_refresh=force_refresh)
    except TypeError as exc:
        # Small test/fixture perceptions may still implement an older signature.
        # Do not hide unrelated TypeErrors.
        message = str(exc)
        if ("navigation_context" not in message
                and "force_refresh" not in message):
            raise
        try:
            return self.perception.semantic_inventory(
                shot, force_refresh=force_refresh)
        except TypeError as fallback_exc:
            if "force_refresh" not in str(fallback_exc):
                raise
            return self.perception.semantic_inventory(shot)


def _refresh_passive_feedback_observation(self, obs, elements):
    """Replace a passive-feedback landing with a fresh unobscured observation."""
    if not bool(getattr(
            self.perception, "last_passive_feedback_present", False)):
        return obs, elements
    latest = obs
    latest_elements = elements
    for attempt in range(1, _PASSIVE_FEEDBACK_REFRESH_LIMIT + 1):
        time.sleep(_PASSIVE_FEEDBACK_REFRESH_DELAY)
        try:
            latest = self.env._get_obs()
            if getattr(self, "_settle_enabled", False):
                latest = self._settle(latest)
        except Exception as exc:
            raise PerceptionUnavailable(
                f"passive feedback refresh capture failed: {exc}") from exc
        shot = (latest or {}).get("screenshot")
        if not shot:
            raise PerceptionUnavailable(
                "passive feedback refresh produced no screenshot")
        latest_elements = _semantic_inventory_for_landing(
            self, shot, force_refresh=True)
        self.review_debug.record_event(
            "passive_feedback_refresh",
            attempt=attempt,
            cleared=not bool(getattr(
                self.perception, "last_passive_feedback_present", False)),
        )
        if not bool(getattr(
                self.perception, "last_passive_feedback_present", False)):
            return latest, latest_elements
    self.review_debug.record_event(
        "passive_feedback_ignored",
        reason="no operable feedback control after bounded refresh",
    )
    logger.warning(
        "passive feedback remained after bounded refresh; continuing with "
        "the latest functional inventory")
    return latest, latest_elements


def _current_observation(self, elements=None) -> Dict[str, Any]:
    """Return a compact current-interface description for VLM shortlisting."""
    names = []
    seen = set()
    for element in elements or []:
        name = " ".join(str(getattr(element, "name", "") or "").split())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return {
        "name": str(getattr(self.perception, "last_page_name", "") or ""),
        "targets": names,
    }


def _preferred_page_id_for_observation(
        self, preferred_state: str, surface_kind: str) -> str:
    """Keep an app-owned active overlay attached to its source Page."""
    preferred_page_id = str(
        self.registry.page_id_of(preferred_state) or ""
        if preferred_state else "")
    from ..visual_perception import ACTIVE_OVERLAY_SURFACE_KINDS
    if str(surface_kind or "") not in ACTIVE_OVERLAY_SURFACE_KINDS:
        return preferred_page_id
    transition = getattr(self, "_pending_transition", None) or {}
    source_id = str(transition.get("source_id") or "")
    if not source_id:
        return preferred_page_id
    source_data = self._state_data.get(source_id) or {}
    return str(
        source_data.get("page_id")
        or self.registry.page_id_of(source_id)
        or preferred_page_id)


def _inherit_map_guided(self, state_id: str, reason: str) -> Tuple[str, bool]:
    """Adopt only durable identity/element data; create no new observation."""
    data = self._state_data.get(state_id) or {}
    elements = data.get("elements") or []
    if not elements and not data.get("semantic_blocks"):
        raise ValueError("confirmed state has no reusable Region/control ledger")
    page_name = str(data.get("page_name") or "")
    page_id, variant_id = self.registry.record_page_variant(
        state_id, page_name, elements=elements, namespace=self.app_name,
        persisted_page_id=str(data.get("page_id") or ""),
    )
    data["page_id"] = page_id
    data["variant_id"] = variant_id
    self._last_arrival_rset = set(self.registry.region_set_of(state_id))
    self._last_arrival_names = list(signature_names(elements))
    self._last_arrival_page_name = page_name
    self._map_guided_inherited = {"state_id": state_id, "reason": reason}
    self.perception.last_page_name = page_name
    self.perception.last_semantic_blocks = copy.deepcopy(
        data.get("semantic_blocks") or [])
    self._last_live_observation_state_id = state_id
    self._last_live_observation_elements = None
    self.review_debug.record_event(
        "map_guided_inheritance", node=state_id, reason=reason,
        elements=len(elements))
    return state_id, False


def _try_map_guided(self, shot: bytes, *, arrival_elements=None,
                    current_observation=None):
    """Return ``(registration-or-None, pregrounded-elements, names)``."""
    if (os.environ.get("GUIWALK_MAP_GUIDED_ID", "1") != "1"
            or getattr(self, "_map_guided_bypass_once", False)):
        return None, None, None
    transition = getattr(self, "_pending_transition", None)
    router = getattr(self, "router", None)
    judge = getattr(self, "page_judge", None)
    if not transition or router is None or judge is None:
        return None, None, None
    from .map_guided import confirm_arrival

    candidates = router.expected_destinations(
        str(transition.get("source_id") or ""),
        str(transition.get("clicked_label") or ""))
    self.review_debug.record_event(
        "map_guided_candidates", candidates=list(candidates),
        source=transition.get("source_id"),
        clicked_label=transition.get("clicked_label"))
    self._map_guided_preferred_state = None
    self._map_guided_force_new = False
    self._map_guided_occurrence_page_state = None
    matched_page_state = str(
        transition.get("matched_page_state_id") or "")
    if (transition.get("force_new_occurrence")
            and matched_page_state in self._state_data):
        self._map_guided_force_new = True
        self._map_guided_occurrence_page_state = matched_page_state
        self.review_debug.record_event(
            "map_guided_source_occurrence_split",
            source=transition.get("source_id"),
            matched_page_state=matched_page_state)
        return None, arrival_elements, (
            signature_names(arrival_elements)
            if arrival_elements else None)
    identity_transition = dict(transition)
    identity_transition["source_name"] = str(
        (self._state_data.get(str(transition.get("source_id") or "")) or {}).get(
            "page_name") or "")
    source_path = self.registry.known_path(str(
        transition.get("source_id") or ""))
    if source_path:
        identity_transition["source_screenshot_path"] = str(source_path)
    try:
        state_id, reason = confirm_arrival(
            self._state_data, self.registry, _reloc, candidates, shot, judge,
            self._node_descriptor, transition=identity_transition,
            current_observation=current_observation,
            fallback_candidate_ids=self._state_data.keys())
    except Exception as exc:
        logger.warning("map-guided confirmation failed closed: %s", exc)
        self.review_debug.record_event(
            "map_guided_decision", verdict="error", reason=str(exc)[:200])
        return None, None, None
    self.review_debug.record_event(
        "map_guided_decision", verdict=(state_id or "NEW"), reason=reason)
    if state_id:
        source_id = str(transition.get("source_id") or "")
        requires_fresh = bool(
            transition.get("requires_fresh_observation")
            or (transition.get("visual_changed") and state_id == source_id)
        )
        if requires_fresh:
            self.review_debug.record_event(
                "map_guided_fresh_observation_required",
                node=state_id,
                source=source_id,
                reason=("effect_verification"
                        if transition.get("requires_fresh_observation")
                        else "same_page_visual_change"),
            )
            if getattr(self.perception, "use_semantic_inventory", False):
                self._map_guided_preferred_state = state_id
                return None, arrival_elements, (
                    signature_names(arrival_elements)
                    if arrival_elements else None)
            return None, None, None
        if getattr(self.perception, "use_semantic_inventory", False):
            # Candidate identity may reuse the durable State id, never its old
            # screenshot or element set. Ordinary semantic registration below
            # persists this live observation against the matched identity.
            self._map_guided_preferred_state = state_id
            self.review_debug.record_event(
                "map_guided_fresh_identity", node=state_id, reason=reason)
            return None, arrival_elements, (
                signature_names(arrival_elements)
                if arrival_elements else None)
        try:
            return _inherit_map_guided(self, state_id, reason), None, None
        except Exception as exc:
            logger.warning("map-guided inheritance unavailable: %s", exc)
            return None, None, None

    if reason.startswith("vlm:NEW:"):
        self._map_guided_force_new = True

    # A multi-choice NEW unlocks one ordinary grounding.  Reuse it below if
    # global evidence does not recover a remote old state.
    if not reason.startswith("vlm:NEW:"):
        return None, None, None
    arrival_els = arrival_elements
    try:
        if arrival_els is not None:
            pass
        elif getattr(self.perception, "use_semantic_inventory", False):
            arrival_els = _semantic_inventory_for_landing(self, shot)
        else:
            arrival_els = self.perception.detect_and_name(shot)
    except Exception as exc:
        logger.debug("map-guided global fallback grounding failed: %s", exc)
    arrival_names = signature_names(arrival_els) if arrival_els else None
    return None, arrival_els, arrival_names


def _refresh_semantic_block_members(blocks, elements) -> None:
    """Persist only stable block references and mapped target evidence."""
    for block in blocks or []:
        region_id = str(block.get("region_id") or "")
        scrollable = block.get("scrollable")
        viewport_bbox = (
            block.get("viewport_bbox_1000") or block.get("bbox_1000"))
        if not (isinstance(viewport_bbox, list)
                and len(viewport_bbox) == 4):
            viewport_bbox = None
        members = [
            element
            for element in elements or []
            if str(getattr(element, "region_id", "") or "") == region_id
        ]
        block.clear()
        stable = {
            "region_id": region_id,
            "scrollable": scrollable,
            "element_ids": [getattr(element, "id", None)
                            for element in members],
            "element_names": [str(getattr(element, "name", "") or "")
                              for element in members],
        }
        if viewport_bbox is not None:
            stable["viewport_bbox_1000"] = list(viewport_bbox)
        block.update(stable)


def _direct_live_actions(live_elements, live_blocks):
    """Return actions owned by the current frontmost target-app surface."""
    live_ids = {
        element_id
        for block in (live_blocks or [])
        if str(block.get("scope") or "target_app").casefold() == "target_app"
        and str(block.get("interaction") or "direct").casefold() == "direct"
        for element_id in (block.get("element_ids") or [])
    }
    return [
        element for element in (live_elements or [])
        if getattr(element, "id", None) in live_ids
        and getattr(element, "interactive", True) is not False
    ]


def _reconcile_known_state_live_targets(
        historical, live_elements, live_blocks, perception):
    """Reuse old target identity within an already verified GUI State."""
    live_actions = _direct_live_actions(live_elements, live_blocks)
    historical_candidates = [
        element for element in (historical or [])
        if getattr(element, "interactive", True) is not False
        if str(getattr(element, "exploration_status", "") or "") != "terminal"
    ]
    known_historical_names = {
        normalize_semantic_text(getattr(element, "name", ""))
        for element in (historical or [])
        if getattr(element, "interactive", True) is not False
        if normalize_semantic_text(getattr(element, "name", ""))
    }
    unmatched = [
        element for element in live_actions
        if normalize_semantic_text(getattr(element, "name", ""))
        not in known_historical_names
    ]
    reconcile = getattr(perception, "reconcile_semantic_targets", None)
    if not historical_candidates or not unmatched or not callable(reconcile):
        return []
    mappings = reconcile(historical_candidates, unmatched)
    historical_by_id = {
        str(getattr(element, "id", "")): element
        for element in historical_candidates
    }
    reconciled = []
    for element in unmatched:
        historical_element = historical_by_id.get(
            str((mappings or {}).get(str(getattr(element, "id", ""))) or ""))
        if historical_element is None:
            continue
        live_name = str(getattr(element, "name", "") or "")
        element.name = str(getattr(historical_element, "name", "") or "")
        element.group = str(getattr(historical_element, "group", "") or "")
        reconciled.append({
            "live_name": live_name,
            "historical_name": element.name,
            "historical_id": str(getattr(historical_element, "id", "")),
        })
    return reconciled


def _rewrite_region_refs(value, aliases: Dict[str, str]) -> bool:
    """Rewrite persisted Region-reference fields after a VLM-confirmed merge."""
    changed = False
    if isinstance(value, list):
        for item in value:
            changed = _rewrite_region_refs(item, aliases) or changed
        return changed
    if not isinstance(value, dict):
        return False
    for key, item in list(value.items()):
        if key in {"region_id", "source_region_id"}:
            replacement = aliases.get(str(item or ""))
            if replacement:
                value[key] = replacement
                changed = True
        elif isinstance(item, (dict, list)):
            changed = _rewrite_region_refs(item, aliases) or changed
    return changed


def _apply_region_aliases(self, aliases: Dict[str, str]) -> List[str]:
    """Apply stable Region merges to live registries and graph evidence."""
    aliases = {
        str(drop): str(keep) for drop, keep in (aliases or {}).items()
        if str(drop) and str(keep) and str(drop) != str(keep)
    }
    if not aliases:
        return []
    for drop_id, keep_id in aliases.items():
        if not self.region_registry.merge_semantic_concepts(keep_id, drop_id):
            raise PerceptionUnavailable(
                f"cannot merge Region {drop_id} into {keep_id}")
    region_sets = getattr(self.registry, "_region_sets", {})
    for state_id, values in list(region_sets.items()):
        region_sets[state_id] = {
            (f"region:{aliases[token[7:]]}"
             if str(token).startswith("region:")
             and str(token)[7:] in aliases else token)
            for token in values
        }
    changed_states = []
    for state_id, data in self._state_data.items():
        changed = False
        for element in data.get("elements") or []:
            region_id = str(
                element.get("region_id", "") if isinstance(element, dict)
                else getattr(element, "region_id", "") or "")
            if region_id in aliases:
                if isinstance(element, dict):
                    element["region_id"] = aliases[region_id]
                else:
                    element.region_id = aliases[region_id]
                changed = True
        changed = _rewrite_region_refs(
            data.get("semantic_blocks") or [], aliases) or changed
        if changed:
            changed_states.append(str(state_id))
    graph_obj = getattr(getattr(self, "graph", None), "graph", None)
    if graph_obj is not None:
        for _node_id, payload in graph_obj.nodes(data=True):
            _rewrite_region_refs(payload, aliases)
        for _source, _target, payload in graph_obj.edges(data=True):
            _rewrite_region_refs(payload, aliases)
    graph = getattr(self, "graph", None)
    for attr in ("action_edges", "abnormal_buttons", "scroll_ledger"):
        _rewrite_region_refs(getattr(graph, attr, None), aliases)
    return changed_states


def _persist_region_alias_nodes(self, state_ids, *, skip_state: str = "") -> None:
    """Refresh sidecars of old nodes whose Region references were merged."""
    for state_id in dict.fromkeys(map(str, state_ids or [])):
        if not state_id or state_id == str(skip_state or ""):
            continue
        data = self._state_data.get(state_id) or {}
        try:
            self.writer.update_node_observation(
                state_id,
                elements=[
                    dict(element) if isinstance(element, dict)
                    else element.to_dict()
                    for element in data.get("elements") or []
                ],
                page_name=str(data.get("page_name") or ""),
                page_id=str(data.get("page_id") or ""),
                variant_id=str(data.get("variant_id") or state_id),
                page_identity_version=_PAGE_IDENTITY_VERSION,
                variant_signature=compute_variant_signature(
                    data.get("observed_facts") or {}),
                observed_facts=dict(data.get("observed_facts") or {}),
                visible_capabilities=list(
                    data.get("visible_capabilities") or []),
                node_local_functions=list(
                    data.get("node_local_functions") or []),
                semantic_blocks=list(data.get("semantic_blocks") or []),
                perception_mode=str(data.get("perception_mode") or ""),
            )
        except Exception as exc:
            logger.warning("Region-alias sidecar refresh failed for %s: %s",
                           state_id, exc)


def _preferred_page_name(self: RegistrationHost, observed_name: str) -> str:
    """Keep a known node's stable label after Page identity selected it."""
    preferred_state = str(
        getattr(self, "_map_guided_preferred_state", "") or "")
    preferred_data = self._state_data.get(preferred_state) or {}
    return str(preferred_data.get("page_name") or observed_name)


def _register_semantic_observation(
        self: RegistrationHost, obs: Dict[str, Any], path: List[Dict[str, Any]],
        replay_hints: Optional[List[Optional[Dict[str, Any]]]] = None,
        arrival_elements=None,
) -> Tuple[str, bool]:
    """Register bbox-free semantic inventory without invoking legacy perception."""
    shot = obs["screenshot"]
    elements = (list(arrival_elements) if arrival_elements is not None
                else _semantic_inventory_for_landing(self, shot))
    # This is the physical landing inventory.  Keep it separate from the
    # durable node ledger: revisit top-up deliberately preserves historical
    # identity, while action verification must read current state values and
    # current function visibility from this exact frame.
    live_observation_elements = list(elements or [])
    self._last_live_observation_elements = live_observation_elements
    blocks = list(getattr(self.perception, "last_semantic_blocks", []) or [])
    live_observation_blocks = copy.deepcopy(blocks)
    if not elements or not blocks:
        self.review_debug.record_event(
            "perception_unavailable", mode="semantic_inventory",
            step=self._action_count, path_length=len(path))
        raise PerceptionUnavailable(
            "semantic inventory produced no trustworthy blocks/elements")
    tmp_path = self._screenshot_to_tmp(shot)
    page_name = str(getattr(self.perception, "last_page_name", "") or "").strip()
    fixture_oracle = all(bool(block.get("fixture_oracle")) for block in blocks)
    preferred_state = str(
        getattr(self, "_map_guided_preferred_state", "") or "")
    occurrence_page_state = str(
        getattr(self, "_map_guided_occurrence_page_state", "") or "")
    if occurrence_page_state:
        preferred_state = ""
    preferred_data = self._state_data.get(preferred_state) or {}
    from .block_identity import (
        compare_state_regions,
        resolve_semantic_blocks,
        semantic_region_set,
    )
    if preferred_data:
        # Page identity has already selected this old node. A request-local VLM
        # label (including a fixture oracle's coarse host-page label) may be kept
        # in the observation audit, but it must not overwrite the stable readable
        # name previously assigned to the node.
        page_name = _preferred_page_name(self, page_name)
    if preferred_data and not fixture_oracle:
        # Page identity has already selected this old node. Its Region table is
        # stable; this live frame must not mint or rename Regions from transient
        # inventory wording.
        elements = list(preferred_data.get("elements") or [])
        blocks = copy.deepcopy(preferred_data.get("semantic_blocks") or [])
        region_crops = {}
        _identity_audit = {
            "schema_version": "semantic_block_identity_attempt.v1",
            "method": "reuse_known_node_region_table",
            "state_id": preferred_state,
        }
    else:
        _identity_audit, region_crops = resolve_semantic_blocks(
            screenshot=shot, blocks=blocks, elements=elements,
            perception=self.perception, judge=self.block_identity_judge,
            region_registry=self.region_registry, writer=self.writer,
            state_data=self._state_data,
            pending_transition=getattr(self, "_pending_transition", None),
            page_name=page_name)
    arrival_names = signature_names(elements)
    surface_kind = str(
        getattr(self.perception, "last_surface_kind", "") or "page"
    ).strip()
    region_set = semantic_region_set(
        blocks, elements, surface_kind=surface_kind, page_name=page_name)
    try:
        preferred_page_id = _preferred_page_id_for_observation(
            self, occurrence_page_state or preferred_state, surface_kind)
        state_id, is_new = self.registry.register(
            shot, tmp_path, judge=self._judge_same_page,
            button_names=arrival_names, region_set=region_set,
            page_name=page_name,
            region_set_authoritative=False,
            preferred_page_id=preferred_page_id,
            preferred_state_id=preferred_state,
            # Semantic registration may reuse an old State only when the
            # screenshot/VLM identity layer explicitly selected it. Region and
            # element observations describe that State; they never choose it.
            force_new=bool(
                getattr(self, "_map_guided_force_new", False)
                or not preferred_state))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    self._last_live_observation_state_id = state_id
    real_path = self.writer.save_screenshot(
        state_id, shot, replace=is_new)
    self.registry._states[state_id] = (self.registry._states[state_id][0], real_path)
    fingerprint = StateGraph.compute_visual_fingerprint(shot)
    node_local = list(getattr(self.perception, "last_node_local_functions", []) or [])

    data = self._state_data.setdefault(
        state_id, {"elements": [], "path": list(path),
                   "replay_hints": list(replay_hints) if replay_hints else []})
    historical = list(data.get("elements") or [])

    # Semantic inventory is the element source for every viewport too. It has
    # no persistent identity of its own. ScrollRuntime must map its Region table
    # to stable Regions before any changed viewport can be aggregated.
    if is_new and getattr(self, "_scroll_aggregate_enabled", False):
        self._semantic_scroll_seed = list(elements)
        self._semantic_scroll_seed_region_crops = dict(region_crops)
        localized = dict(
            (_identity_audit.get("localization") or {}).get("bboxes_1000") or {})
        self._semantic_scroll_seed_region_bboxes = {
            str(block.get("region_id") or ""): list(localized[local_id])
            for block in blocks
            for local_id in [str(block.get("local_id") or "")]
            if str(block.get("region_id") or "") and local_id in localized
        }
        try:
            elements = self._scroll_aggregate(obs, elements, state_id=state_id)
        finally:
            self.__dict__.pop("_semantic_scroll_seed", None)
            self.__dict__.pop("_semantic_scroll_seed_region_crops", None)
            self.__dict__.pop("_semantic_scroll_seed_region_bboxes", None)
        scroll_blocks = data.pop("_semantic_scroll_blocks", None)
        scroll_region_crops = data.pop(
            "_semantic_scroll_region_crops", None)
        if scroll_blocks:
            blocks = list(scroll_blocks)
        if isinstance(scroll_region_crops, dict):
            # The completed scroll audit is authoritative for Region images.
            # Replacing instead of updating is important: a scrollable Region
            # deliberately omitted because its crop sequence was incomplete must
            # not retain the seed viewport and masquerade as a complete long map.
            region_crops = dict(scroll_region_crops)

    if is_new:
        final_elements = list(elements)
        self._renumber_unique(final_elements)
        data["elements"] = final_elements
        self._bfs_queue.append(state_id)
    else:
        reconciled = _reconcile_known_state_live_targets(
            historical, live_observation_elements, live_observation_blocks,
            self.perception)
        if reconciled:
            self.review_debug.record_event(
                "known_state_live_targets_reconciled",
                state_id=state_id, mappings=reconciled)
        final_elements = historical
        data["elements"] = final_elements
    if is_new:
        self.perception.last_page_name = page_name
    _refresh_semantic_block_members(blocks, final_elements)
    data["page_name"] = page_name
    data["semantic_blocks"] = blocks

    alias_changed_states: List[str] = []
    transition = getattr(self, "_pending_transition", None) or {}
    source_id = str(transition.get("source_id") or "")
    if is_new and source_id:
        source_data = self._state_data.get(source_id) or {}
        data["entry_source_page_id"] = str(
            source_data.get("page_id")
            or self.registry.page_id_of(source_id)
            or source_id)
    pair_key = tuple(sorted((source_id, str(state_id))))
    compared_pairs = self.__dict__.setdefault(
        "_region_pair_comparisons", set())
    if (source_id and source_id != state_id
            and source_id in self._state_data
            and pair_key not in compared_pairs):
        audit, aliases = compare_state_regions(
            state_a=self._state_data[source_id], state_b=data,
            judge=self.block_identity_judge)
        if aliases:
            alias_changed_states = _apply_region_aliases(self, aliases)
            blocks = list(data.get("semantic_blocks") or blocks)
            final_elements = list(data.get("elements") or final_elements)
            region_crops = {
                aliases.get(region_id, region_id): payload
                for region_id, payload in region_crops.items()
            }
        if audit.get("status") == "mapped":
            compared_pairs.add(pair_key)
        try:
            self.writer.save_block_identity_attempt(
                audit=audit, current_atlas=None, current_crops={})
        except Exception as exc:
            logger.warning("Region correspondence artifact failed: %s", exc)

    region_set = semantic_region_set(
        blocks, final_elements, surface_kind=surface_kind,
        page_name=page_name)
    self._last_arrival_rset = set(region_set)
    self._last_arrival_names = list(signature_names(final_elements))
    self._last_arrival_page_name = page_name
    # Landing verification reads the current observation, not the durable node
    # ledger. A known-node revisit may reuse canonical Regions/actions, but it
    # must not replace fresh state values or visibility with historical data.
    self._last_live_observation_elements = live_observation_elements
    for block in blocks:
        self.region_registry.mark_seen(
            str(block.get("region_id") or ""), state_id)
    for region_id in {
            str(getattr(element, "region_id", "") or "")
            for element in final_elements}:
        if region_id:
            self.region_registry.record_mapped_elements(
                region_id,
                [element.name for element in final_elements
                 if str(getattr(element, "region_id", "") or "") == region_id])
    self.registry.set_buttons(state_id, final_elements)
    page_id, variant_id = self.registry.record_page_variant(
        state_id, page_name, elements=final_elements, namespace=self.app_name,
        persisted_page_id=preferred_page_id)
    observed_facts = self.registry.variant_facts_of(state_id)
    variant_sig = compute_variant_signature(observed_facts)
    capabilities = discover_capabilities(
        page_id=page_id, variant_id=variant_id, state_id=state_id,
        elements=final_elements)
    visible_ids = [item["capability_id"] for item in capabilities
                   if item.get("capability_id")]
    data.update({"page_name": page_name, "page_id": page_id,
                  "variant_id": variant_id,
                  "surface_kind": surface_kind,
                 "observed_facts": observed_facts,
                 "visible_capabilities": visible_ids,
                 "semantic_blocks": blocks,
                 "perception_mode": "semantic_inventory"})
    elem_dicts = [element.to_dict() for element in final_elements]
    self.graph.add_state(
        state_id=state_id, elements=(elem_dicts if is_new else []),
        screenshot_path=real_path, app_name=self.app_name,
        action_path_from_root=list(path), state_type="visual",
        visual_fingerprint=fingerprint, page_name=page_name,
        page_id=page_id, variant_id=variant_id,
        page_identity_version=_PAGE_IDENTITY_VERSION,
        variant_signature=variant_sig, observed_facts=observed_facts,
        visible_capabilities=visible_ids, semantic_blocks=blocks,
        perception_mode="semantic_inventory")
    visible_ids = self.graph.register_capability_candidates(state_id, capabilities)
    data["visible_capabilities"] = list(visible_ids)
    if is_new:
        self.writer.save_node(
            state_id=state_id, screenshot_bytes=shot, elements=elem_dicts,
            visual_fingerprint=fingerprint, som_image=None,
            action_path_from_root=list(path), node_local_functions=node_local,
            page_name=page_name, app_id=self.app_name, page_id=page_id,
            variant_id=variant_id, page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts, visible_capabilities=visible_ids,
            capability_records=capabilities, semantic_blocks=blocks,
            perception_mode="semantic_inventory")
        saved_region_ids = set()
        for region_id, payload in region_crops.items():
            if self.writer.save_region_image(state_id, region_id, payload):
                saved_region_ids.add(region_id)
        for block in blocks:
            region_id = str(block.get("region_id") or "")
            if region_id and region_id not in saved_region_ids:
                logger.warning(
                    "region image missing: state=%s region_id=%s "
                    "(localization failed or out-of-bounds; no full-page fallback)",
                    state_id, region_id)
    else:
        self.writer.update_node_observation(
            state_id, elements=elem_dicts, page_name=page_name, page_id=page_id,
            variant_id=variant_id, page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts, visible_capabilities=visible_ids,
            node_local_functions=node_local, semantic_blocks=blocks,
            perception_mode="semantic_inventory")
        self._persist_online_capabilities(state_id)
    _persist_region_alias_nodes(
        self, alias_changed_states, skip_state=state_id)
    logger.info("registered %s semantic state %s page=%r (%d elements, %d blocks)",
                "NEW" if is_new else "revisit", state_id, page_name,
                len(final_elements), len(blocks))
    return state_id, is_new

def register_observation(self: RegistrationHost, obs: Dict[str, Any], path: List[Dict[str, Any]],
              replay_hints: Optional[List[Optional[Dict[str, Any]]]] = None
              ) -> Tuple[str, bool]:
    """Register the current screenshot as a state; persist artifacts if new.

    ``replay_hints`` (priority-3) is a list parallel to ``path``: for each
    CLICK action a ``{"template", "post_shot", "name"}`` dict (None
    for SCROLL/PRESS) so a later closed-loop hard-reset replay can relocate
    each step and same-page-gate it. Stored alongside the path.
    """
    from gui_rewalk.src.core.graph.state_graph import StateGraph
    scoped_preferred = str(
        getattr(self, "_registration_preferred_state_once", "") or "")
    self.__dict__.pop("_registration_preferred_state_once", None)
    # Map-guided decisions belong to exactly one registration. A previous
    # landing must never pin a later Router refresh to the wrong node.
    self._map_guided_preferred_state = scoped_preferred or None
    self._map_guided_force_new = False
    self._map_guided_occurrence_page_state = None
    self._map_guided_inherited = None
    shot = obs["screenshot"]
    semantic = bool(getattr(self.perception, "use_semantic_inventory", False))
    fresh_known_state = ""
    if semantic:
        transition = getattr(self, "_pending_transition", None) or {}
        resolver = getattr(self, "identity_resolver", None)
        if resolver is not None:
            def resolve_page_identity():
                return resolver.resolve(
                    shot,
                    source_id=str(transition.get("source_id") or ""),
                    clicked_label=str(transition.get("clicked_label") or ""),
                    clicked_bbox=transition.get("clicked_bbox"),
                    clicked_point=transition.get("clicked_point"),
                )

            resolution = resolve_page_identity()
            if resolution.is_interruption:
                self.review_debug.record_event(
                    "page_identity_interruption",
                    verdict="dismiss",
                    reason=resolution.reason,
                )
                dismiss = getattr(self, "_dismiss_interruptions", None)
                if not callable(dismiss):
                    raise PerceptionUnavailable(
                        "page identity interruption cannot be dismissed")
                cleaned_obs = dismiss(
                    obs, page_identity_flagged=True)
                cleaned_shot = (cleaned_obs or {}).get("screenshot")
                if (getattr(self, "_startup_surface_unresolved", False)
                        or not cleaned_shot or cleaned_shot == shot):
                    raise PerceptionUnavailable(
                        "page identity interruption remains unresolved")
                if cleaned_obs is not obs:
                    obs.clear()
                    obs.update(cleaned_obs)
                shot = cleaned_shot
                resolution = resolve_page_identity()
                if resolution.is_interruption:
                    raise PerceptionUnavailable(
                        "page identity interruption remains after dismissal")
            self.review_debug.record_event(
                "identity_resolution",
                verdict=resolution.verdict,
                node=resolution.state_id,
                reason=resolution.reason,
                exact=resolution.exact,
                proposed_new_page_name=(
                    resolution.proposed_new_page_name or ""),
                shortlisted_page_ids=list(getattr(
                    getattr(self, "page_judge", None),
                    "last_candidate_page_ids", ()) or ()),
            )
            if resolution.known:
                can_refresh_live_inventory = (
                    callable(getattr(
                        self.perception, "fixture_inventory_provider", None))
                    or os.environ.get(
                        "GUIWALK_REGION_LAZY_INVENTORY", "1") == "0"
                )
                if (transition.get("requires_fresh_observation")
                        and can_refresh_live_inventory):
                    fresh_known_state = str(resolution.state_id)
                    self._map_guided_preferred_state = fresh_known_state
                    self.review_debug.record_event(
                        "known_state_fresh_observation_required",
                        node=fresh_known_state,
                        reason="stateful_action",
                    )
                else:
                    try:
                        return _inherit_map_guided(
                            self, resolution.state_id, resolution.reason)
                    except Exception as exc:
                        raise PerceptionUnavailable(
                            "known State has no reusable Region/control ledger: "
                            f"{exc}") from exc
            if resolution.verdict == "unresolved":
                raise PerceptionUnavailable(
                    f"page identity unresolved: {resolution.reason}")
            self._map_guided_force_new = True
            if (
                os.environ.get("GUIWALK_REGION_LAZY_INVENTORY", "1") == "1"
                and getattr(self, "agent", None) is not None
                and not callable(getattr(
                    self.perception, "fixture_inventory_provider", None))
            ):
                from ..runtime.region_observation import register_region_map
                proposed_page_name = (
                    resolution.proposed_new_page_name
                    if resolution.verdict == "new" else "")
                try:
                    return register_region_map(
                        self, obs, path, replay_hints=replay_hints,
                        proposed_page_name=proposed_page_name,
                    )
                except Exception as exc:
                    self.review_debug.record_event(
                        "region_map_unavailable", reason=str(exc)[:240])
                    raise PerceptionUnavailable(str(exc)) from exc
    arrival_els = (
        _semantic_inventory_for_landing(self, shot) if semantic else None)
    if semantic:
        obs, arrival_els = _refresh_passive_feedback_observation(
            self, obs, arrival_els)
        shot = obs["screenshot"]
    if fresh_known_state:
        fast_result, map_arrival_els, arrival_names = None, None, None
    else:
        fast_result, map_arrival_els, arrival_names = _try_map_guided(
            self, shot, arrival_elements=arrival_els,
            current_observation=(
                _current_observation(self, arrival_els) if semantic else None))
    if map_arrival_els is not None:
        arrival_els = map_arrival_els
    if fast_result is not None:
        return fast_result
    if semantic:
        return _register_semantic_observation(
            self, obs, path, replay_hints=replay_hints,
            arrival_elements=arrival_els)
    # Legacy SoM/segmentation path remains isolated below.  Semantic mode must
    # return above and must not mix bbox-based identity into its contracts.
    # Use a throwaway temp file for the SSIM comparison so we don't litter
    # the screenshots dir before the stable state_id is known.
    tmp_path = self._screenshot_to_tmp(shot)

    # [2026-07-08 用户 根因C] 页身份 VLM judge 提成方法 _judge_same_page,register 与
    # identify(back 落点核对)复用同一个 —— identify 从前不带 judge, ±1 区块抖动直接
    # None -> 误判迷路 hard-reset。现在两边对称。
    _judge = self._judge_same_page

    # Ground the legacy arrival frame so Region-set arbitration has a functional
    # summary and the traversal has a fresh coverage inventory. Semantic mode
    # returned above; this fallback never treats button wording alone as State
    # identity.
    if arrival_els is None and getattr(
            self.perception, "use_vlm_grounding", False):
        try:
            arrival_els = self.perception.detect_and_name(shot)
            arrival_names = signature_names(arrival_els)  # §1+§7 group-folded
        except Exception as e:
            logger.debug("arrival grounding for button-id failed (%s)", e)
    if not arrival_els:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        self.review_debug.record_event(
            "perception_unavailable", step=self._action_count,
            path_length=len(path), screenshot_bytes=len(shot or b""))
        raise PerceptionUnavailable(
            "live frame produced no trustworthy visual elements")
    self._last_live_observation_elements = list(arrival_els)
    # [2026-07-07 用户] REGION-SET IDENTITY: compute the arrival frame's region
    # structure (geometric, no VLM) and hand it to register() as the SOLE merge
    # discriminator — pHash no longer merges pHash-near/content-different siblings
    # (Privacy vs Bluetooth). Empty (touch/modal/sparse) -> legacy pHash path.
    _arrival_rset = self._arrival_region_set(obs, arrival_els)
    # [2026-07-08 用户] 合并质检 —— 区块检测 + 按钮检测【一次调用】,跑在区块分割后、
    # register(命名/身份 mint)之前。目的:让质检员在身份定死前指出"右侧 content 面板
    # 明明有却没被切出来"(稀疏面板被 <2 门槛丢 / segVLM 抖动漏切)——这是同页分裂→
    # hard-reset 的根因 B。区块有漏 -> 重分割一次、重算 rset(用修好的集定身份);框问题
    # 记入 transcript(取代命名后那次 log-only reviewer.review)。默认开, 置 GUIWALK_MERGED_QA=0
    # 回退旧行为。revert: 删本 if 块 + 恢复命名后的 reviewer.review。
    _merged_rev = None
    _merged_subject = None
    if (os.environ.get("GUIWALK_MERGED_QA", "1") != "0"
            and arrival_els
            and getattr(self.perception, "last_som_image", None) is not None):
        try:
            _merged_rev = self.reviewer.review_with_regions(
                self.perception.last_som_image, arrival_els,
                getattr(self, "_last_regions_desc", []))
            _merged_subject = self._review_subject_signature(
                arrival_els, self.perception.last_som_image)
            _rmiss = _merged_rev.get("region_missing") or []
            if _rmiss:
                # 漏了区块(多为 content)-> 强制重分割一次(清同帧缓存), 重算 rset。
                logger.info("[merged-qa] 漏区块 %s -> 重分割重算 rset",
                            [m.get("role") for m in _rmiss])
                self._seg_cache_key = None
                _rset2 = self._arrival_region_set(
                    obs, arrival_els, force_region_refresh=True)
                if _rset2 != _arrival_rset:
                    logger.info("[merged-qa] rset 修复: %s -> %s",
                                sorted(_arrival_rset), sorted(_rset2))
                    _arrival_rset = _rset2
        except Exception as _qe:
            logger.debug("merged QA failed (%s); 跳过", _qe)
    # [2026-07-07 用户 问题1] remember THIS frame's true region-set so the main
    # loop's on-page self-check (_reconcile_position) can compare it against
    # current_id's stored identity for FREE — no extra grounding.
    self._last_arrival_rset = _arrival_rset
    self._last_arrival_names = list(arrival_names or [])
    self._last_arrival_page_name = (
        getattr(self.perception, "last_page_name", "") or "").strip()
    try:
        state_id, is_new = self.registry.register(
            shot, tmp_path, judge=_judge, button_names=arrival_names,
            region_set=_arrival_rset,
            page_name=self._last_arrival_page_name)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    self._last_live_observation_state_id = state_id
    # [2026-07-07 用户 取证] on a MERGE (identity matched an EXISTING node), save the
    # EXACT frame register grounded + log its rset — so a false-match (a clean
    # Privacy frame identified as a main page) is caught RED-HANDED with the image.
    if not is_new:
        try:
            _md = os.path.join(os.path.dirname(self.graph_save_path), "_merge_shots")
            os.makedirs(_md, exist_ok=True)
            self._merge_seq = getattr(self, "_merge_seq", 0) + 1
            _mfn = os.path.join(_md, f"merge{self._merge_seq:03d}_{state_id[:8]}.png")
            with open(_mfn, "wb") as _mf:
                _mf.write(shot)
            logger.info("[merge-shot] %s matched=%s rset=%s",
                        os.path.basename(_mfn), state_id[:8], sorted(_arrival_rset))
        except Exception as _me:
            logger.debug("merge-shot save failed: %s", _me)
    real_path = self.writer.save_screenshot(
        state_id, shot, replace=is_new)
    # Re-point the registry at the stable on-disk path for future SSIM checks.
    self.registry._states[state_id] = (
        self.registry._states[state_id][0], real_path
    )

    fingerprint = StateGraph.compute_visual_fingerprint(shot)
    # Per-registration accumulator. Scroll helpers refill it from every
    # grounded viewport; resetting here prevents a non-scrollable next node
    # from inheriting the previous node's local-only functions.
    self._scroll_node_local_functions = []
    if is_new:
        # node_image: bytes saved as the node's canonical screenshot (top frame
        # by default; the full-page COMPOSITE when stitching succeeds).
        node_image = shot
        stitched = None
        if self._stitch_node_image and self._scroll_aggregate_enabled:
            # STITCH PATH. Capture the scroll frames WITHOUT per-viewport naming
            # (seed the aggregate with YOLO-only top boxes — the page is named
            # once on the composite), then build the full-page node from them.
            seed = self._detect_boxes_only(shot)
            self._scroll_aggregate(
                obs, seed, state_id=state_id)  # fills frame/offset buffers
            stitched = self._build_stitched_node(shot)
        if stitched is not None:
            elements, node_image, som_for_writer = stitched
            node_local = list(self.perception.last_node_local_functions)
        else:
            # PER-VIEWPORT PATH (flag off, or stitch fell back). Identical to the
            # prior behaviour: name the top viewport, then scroll-aggregate the
            # below-the-fold rows with per-viewport naming. Reuse the arrival
            # grounding (already computed for button-id) to avoid a 2nd call.
            elements = (arrival_els if arrival_els is not None
                        else self.perception.detect_and_name(shot))
            node_local = list(self.perception.last_node_local_functions)
            # In-node scroll-aggregate: reveal below-the-fold clickable rows so
            # long-list pages (settings/clock/contacts) are explored in full,
            # not just their top viewport. Off for desktop / non-scrollable pages.
            if self._region_dedup and not getattr(self, "_is_touch", True):
                # [REGION-SCROLL CHANGE 8] region-aware: segment regions, register
                # each in the shared RegionRegistry, scroll only NEW scrollable
                # regions, and mark shared (already-seen) regions' elements
                # visited so they are not re-explored. revert: delete this branch.
                elements = self._regional_scroll_dedup(obs, elements, state_id)
                # [REGION-SCROLL CHANGE 14] persist each scrollable region's
                # stitched composite as a node artifact (full region, not just top
                # viewport) for downstream capability synth / instruction viewing.
                for _role, _png in getattr(self, "_region_composites", {}).items():
                    try:
                        self.writer.save_region_composite(state_id, _role, _png)
                    except Exception as _e:
                        logger.debug("save_region_composite(%s) failed: %s", _role, _e)
            elif self._scroll_aggregate_enabled:
                elements = self._scroll_aggregate(
                    obs, elements, state_id=state_id)
            som_for_writer = self.perception.last_som_image
        # [2026-07-07 用户A] reviewer SELF-HEAL before committing: re-ground modal
        # frames whose boxes the reviewer flags wrong (Qwen mislocation) so bad
        # coords never reach set_buttons / graph / the click path. revert: delete.
        _initial_review = (
            _merged_rev
            if (_merged_rev is not None
                and _merged_subject == self._review_subject_signature(
                    elements, som_for_writer))
            else None)
        elements, som_for_writer, _heal_review = self._heal_grounding_via_review(
            shot, elements, som_for_writer,
            initial_review=_initial_review)
        # Re-number so every element in THIS node carries a unique, contiguous
        # id. detect_and_name numbers each frame 0..N independently, so the
        # scroll-aggregate above CONCATENATES several 0..N runs -> duplicate
        # ids within one node (contacts home had ids 2/5/11 twice). Those
        # collisions corrupt any id->element map (the frontier scheduler's, the
        # graph edge's element_id) and were the source of the mis-clicks. One
        # node, one id space — assigned once the full element set is known.
        self._renumber_unique(elements)
        # Record this node's full button universe — doubles as the coverage
        # ledger (every meaningful button to be clicked) AND the button-set
        # identity index (so a future mid-scroll viewport re-identifies here).
        self.registry.set_buttons(state_id, elements)
        # Assign visual uids from the TOP frame for the PER-VIEWPORT path (the
        # registered, identity frame). The STITCH path already assigned uids from
        # the composite (where each element's true appearance lives) inside
        # _build_stitched_node — re-hashing here on the top frame would corrupt
        # below-the-fold uids (their viewport-y shows different content on the
        # top frame), so it is skipped there.
        if stitched is None:
            assign_element_uids(shot, elements)
        # Ensure every element carries a relocation template (the non-scroll /
        # desktop path skips _scroll_aggregate, and a few crops may have been
        # rejected as unreliable -> leave None -> VLM fallback). In the stitch
        # path the template was already cropped from the right scroll frame.
        for e in elements:
            if getattr(e, "_template", None) is None:
                e._template = _reloc.save_template(shot, e.bbox_xywh)
        node_local = self._collected_node_local_functions(node_local)
        _page_name = (getattr(self.perception, "last_page_name", "") or "").strip()
        page_id, variant_id = self.registry.record_page_variant(
            state_id,
            _page_name,
            elements=elements,
            namespace=self.app_name,
        )
        observed_facts = self.registry.variant_facts_of(state_id)
        variant_sig = compute_variant_signature(observed_facts)
        capability_candidates = discover_capabilities(
            page_id=page_id,
            variant_id=variant_id,
            state_id=state_id,
            elements=elements,
            extra_functions=node_local,
        )
        visible_capability_ids = [
            item["capability_id"] for item in capability_candidates
            if item.get("capability_id")
        ]
        self._state_data[state_id] = {
            "elements": elements, "path": list(path),
            "replay_hints": list(replay_hints) if replay_hints else [],
            "page_name": _page_name,
            "page_id": page_id,
            "variant_id": variant_id,
            "observed_facts": observed_facts,
            "visible_capabilities": visible_capability_ids,
            "is_system_dialog": bool(getattr(self.perception,
                                             "last_is_system_dialog", False))}
        elem_dicts = [e.to_dict() for e in elements]
        # When stitching produced a full-page composite, make IT the node's
        # canonical image for the GRAPH + node artifact. CRITICAL for identity:
        # the registry's SSIM path (``screenshots/<id>.png`` == ``real_path``)
        # stays the TOP frame — a re-visit registers from its top frame, so SSIM
        # must compare against a top frame, NOT the tall composite (which would
        # SSIM-mismatch and re-introduce scroll-splits). So we write the
        # composite to a SEPARATE file and only point the graph/node artifact at
        # it; the registry tuple is left untouched (top-frame pHash + top-frame
        # path). Identity therefore remains the tolerant element-set/chrome-band
        # path, never the composite pixels.
        graph_shot_path = real_path
        if node_image is not shot:
            graph_shot_path = self.writer.save_fullpage(state_id, node_image)
        self.graph.add_state(
            state_id=state_id, elements=elem_dicts, screenshot_path=graph_shot_path,
            app_name=self.app_name, action_path_from_root=list(path),
            state_type="visual", visual_fingerprint=fingerprint,
            page_name=_page_name,
            page_id=page_id,
            variant_id=variant_id,
            page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts,
            visible_capabilities=visible_capability_ids,
        )
        visible_capability_ids = self.graph.register_capability_candidates(
            state_id, capability_candidates)
        self._state_data[state_id]["visible_capabilities"] = list(
            visible_capability_ids)
        self.writer.save_node(
            state_id=state_id, screenshot_bytes=node_image, elements=elem_dicts,
            visual_fingerprint=fingerprint, som_image=som_for_writer,
            action_path_from_root=list(path), node_local_functions=node_local,
            page_name=_page_name,
            app_id=self.app_name,
            page_id=page_id,
            variant_id=variant_id,
            page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts,
            visible_capabilities=visible_capability_ids,
            capability_records=capability_candidates,
        )
        self._bfs_queue.append(state_id)
        _pg = _page_name   # [用户] 整页 VLM 名
        logger.info("registered NEW visual state %s 页面「%s」(%d clickable, %d node-local)",
                    state_id, _pg or "?", len(elements), len(node_local))
        # [2026-07-07 用户 删除] region-identity OBSERVER(log-only)已删——region-set
        # 身份早已是 register/identify 的主判据(不再是观察阶段),观察器冗余。
        # [2026-07-08 用户] Annotation QA:合并质检已在 register 前跑过一次(区块+框),
        # 这里【复用】那次结果记档,不再二次调 VLM(保持每节点调用次数不变)。若合并质检
        # 未跑(flag 关 / 无 som / 无 arrival_els),回退到命名后单跑一次(旧行为)。
        # revert: 无条件 `_rev = self.reviewer.review(som_for_writer, elements)`。
        try:
            _rev = _heal_review or _merged_rev
            if _rev is None:
                _rev = self.reviewer.review(som_for_writer, elements)
            if not _rev.get("ok", True):
                logger.info("review[%s]: wrong=%s missing=%s duplicate=%s "
                            "region_missing=%s",
                            state_id[:8], _rev.get("wrong"),
                            [m.get("name") for m in _rev.get("missing", [])][:6],
                            _rev.get("duplicate"),
                            [m.get("role") for m in _rev.get("region_missing", [])])
            # DEBUG-agent: persist the full verdict + this node's elements
            # (unicode-safe, structured) for post-run inspection.
            self.review_debug.record_node(state_id, elements, _rev)
        except Exception as _re:
            logger.debug("annotation review failed: %s", _re)
    else:
        # [REGION-SCROLL CHANGE 3b] TOP-UP on revisit: a merge used to touch
        # nothing, so any row seen only on a later visit was lost. set_buttons
        # now UNIONs, so folding this arrival's buttons in only GROWS the ledger
        # (coverage frontier) — never shrinks it. revert: delete these 3 lines.
        node_local = list(self.perception.last_node_local_functions)
        live_data = self._state_data.setdefault(
            state_id,
            {"elements": [], "path": list(path), "replay_hints": []},
        )
        # A revisit repairs an interrupted scroll audit.  Certified shared
        # desktop regions are reused by ``_regional_scroll_dedup``; a mobile
        # page is re-scrolled only while its page scope is incomplete.
        if arrival_els:
            if self._region_dedup and not getattr(self, "_is_touch", True):
                arrival_els = self._regional_scroll_dedup(
                    obs, arrival_els, state_id)
            elif self._scroll_aggregate_enabled:
                _scope = getattr(
                    getattr(self, "graph", None), "scroll_ledger", {}
                ).get(f"state:{state_id}:page", {})
                if not _scope or _scope.get("complete") is not True:
                    arrival_els = self._scroll_aggregate(
                        obs, arrival_els, state_id=state_id)
            assign_element_uids(shot, arrival_els)
            existing = live_data.setdefault("elements", [])
            next_id = max(
                (int(getattr(element, "id", -1)) for element in existing),
                default=-1,
            ) + 1
            noninteractive_corrections = []
            for element in arrival_els:
                matches = []
                for prior in existing:
                    score = self._topup_match_score(prior, element)
                    if score is not None:
                        matches.append((score, prior))
                if matches:
                    matches.sort(key=lambda item: item[0], reverse=True)
                    prior = matches[0][1]
                    prior_uid = str(getattr(prior, "uid", "") or "")
                    prior_label = str(getattr(prior, "name", "") or "")
                    if self._merge_topup_observation(prior, element):
                        noninteractive_corrections.append((
                            str(getattr(prior, "id", "")),
                            prior_uid,
                            prior_label,
                        ))
                    continue
                element.id = next_id
                next_id += 1
                if getattr(element, "_template", None) is None:
                    element._template = _reloc.save_template(
                        shot, element.bbox_xywh)
                existing.append(element)
            # Identity/coverage is derived from the merged physical ledger,
            # never from raw revisit aliases.  Apply explicit static-display
            # corrections before re-mining capabilities so an old candidate
            # cannot be reintroduced by the same top-up transaction.
            self.registry.set_buttons(state_id, existing)
            for element_id, element_uid, element_label in (
                    noninteractive_corrections):
                self.graph.reclassify_element_noninteractive(
                    state_id,
                    element_id=element_id,
                    element_uid=element_uid,
                    element_label=element_label,
                )
        node_local = self._collected_node_local_functions(node_local)
        _page_name = str(
            live_data.get("page_name")
            or getattr(self.perception, "last_page_name", "")
            or ""
        ).strip()
        final_elements = live_data.get("elements") or arrival_els or []
        page_id, variant_id = self.registry.record_page_variant(
            state_id,
            _page_name,
            elements=final_elements,
            namespace=self.app_name,
        )
        observed_facts = self.registry.variant_facts_of(state_id)
        variant_sig = compute_variant_signature(observed_facts)
        capability_candidates = discover_capabilities(
            page_id=page_id,
            variant_id=variant_id,
            state_id=state_id,
            elements=live_data.get("elements") or arrival_els or [],
            extra_functions=node_local,
        )
        newly_visible_capability_ids = [
            item["capability_id"] for item in capability_candidates
            if item.get("capability_id")
        ]
        visible_capability_ids = list(
            live_data.get("visible_capabilities") or [])
        for capability_id in newly_visible_capability_ids:
            if capability_id not in visible_capability_ids:
                visible_capability_ids.append(capability_id)
        live_data.update({
            "page_name": _page_name,
            "page_id": page_id,
            "variant_id": variant_id,
            "observed_facts": observed_facts,
            "visible_capabilities": visible_capability_ids,
        })
        self.graph.add_state(
            state_id=state_id, elements=[], screenshot_path=real_path,
            app_name=self.app_name, state_type="visual", visual_fingerprint=fingerprint,
            page_name=_page_name,
            page_id=page_id,
            variant_id=variant_id,
            page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts,
            visible_capabilities=visible_capability_ids,
        )
        visible_capability_ids = self.graph.register_capability_candidates(
            state_id, capability_candidates)
        live_data["visible_capabilities"] = list(visible_capability_ids)
        self.writer.update_node_observation(
            state_id,
            elements=[
                element.to_dict()
                for element in (live_data.get("elements") or [])],
            page_name=_page_name,
            page_id=page_id,
            variant_id=variant_id,
            page_identity_version=_PAGE_IDENTITY_VERSION,
            variant_signature=variant_sig,
            observed_facts=observed_facts,
            visible_capabilities=visible_capability_ids,
            node_local_functions=node_local,
        )
        self._persist_online_capabilities(state_id)
    return state_id, is_new
