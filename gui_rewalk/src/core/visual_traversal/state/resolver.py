"""Authoritative screenshot identity resolution before semantic observation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from .block_identity import semantic_region_set
from .identity import signature_names
from .map_guided import page_candidate_payloads


logger = logging.getLogger(__name__)


def identify_existing_frame(
    host: Any,
    observation: Optional[Dict[str, Any]],
    elements: Optional[list[Any]] = None,
) -> Optional[str]:
    """Resolve one observed frame against existing States without mutation.

    A semantic frame uses its stable Region occurrences; the legacy path uses
    the host's current Region observation. With no Region evidence, the Registry
    accepts only one unique exact-frame match. Folded element wording supports
    functional arbitration but never selects an old State by itself.
    """
    if not isinstance(observation, dict):
        return None
    screenshot = observation.get("screenshot")
    if not screenshot:
        return None

    names = signature_names(elements) if elements else None
    if not names:
        names = None
    temporary_path = host._screenshot_to_tmp(screenshot)
    if elements and bool(getattr(
            getattr(host, "perception", None),
            "use_semantic_inventory", False)):
        blocks = list(getattr(
            host.perception, "last_semantic_blocks", []) or [])
        if not blocks:
            blocks = [{"region_id": getattr(element, "region_id", "")}
                      for element in elements]
        region_set = semantic_region_set(blocks, elements)
    else:
        region_set = (
            host._arrival_region_set(observation, elements)
            if elements else set()
        )
    try:
        return host.registry.identify(
            screenshot,
            temporary_path,
            button_names=names,
            region_set=region_set,
            judge=host._judge_same_page,
            page_name=str(getattr(
                getattr(host, "perception", None),
                "last_page_name", "") or ""),
        )
    except Exception as exc:
        logger.debug("frame identity check failed (%s)", exc)
        return None
    finally:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass


@dataclass(frozen=True)
class IdentityResolution:
    verdict: str
    state_id: str = ""
    reason: str = ""
    exact: bool = False
    proposed_new_page_name: str = ""
    is_interruption: bool = False

    @property
    def known(self) -> bool:
        return self.verdict == "known" and bool(self.state_id)


class IdentityResolver:
    """Resolve a screenshot as KNOWN, NEW, or UNRESOLVED.

    The resolver deliberately consumes only screenshot evidence plus the graph's
    expected destinations.  Whole-page semantic inventory is downstream work,
    never a prerequisite for identity.
    """

    def __init__(
        self,
        *,
        registry,
        state_data: Dict[str, Dict[str, Any]],
        judge,
        descriptor_fn: Callable[[str], Optional[Dict[str, Any]]],
        local_candidates_fn: Optional[
            Callable[[str, str], Iterable[str]]] = None,
    ):
        self.registry = registry
        self.state_data = state_data
        self.judge = judge
        self.descriptor_fn = descriptor_fn
        self.local_candidates_fn = local_candidates_fn

    def resolve(
        self,
        screenshot: bytes,
        *,
        source_id: str = "",
        clicked_label: str = "",
        clicked_bbox=None,
        clicked_point=None,
    ) -> IdentityResolution:
        if not screenshot:
            return IdentityResolution(
                "unresolved", reason="identity screenshot is empty")

        exact_lookup = getattr(
            self.registry, "exact_frame_state_ids", None)
        exact_ids = list(exact_lookup(screenshot)) \
            if callable(exact_lookup) else []
        if len(exact_ids) == 1:
            return IdentityResolution(
                "known", str(exact_ids[0]), "unique exact-frame match", True)
        if not self.state_data:
            return IdentityResolution(
                "new", reason="no registered State exists")
        if self.judge is None:
            return IdentityResolution(
                "unresolved", reason="page identity judge unavailable")

        global_ids = [str(state_id) for state_id in self.state_data]
        local_ids = []
        if source_id and callable(self.local_candidates_fn):
            local_ids = [
                str(state_id) for state_id in
                self.local_candidates_fn(source_id, clicked_label)
            ]
        local_ids = list(dict.fromkeys(local_ids))
        global_ids = list(dict.fromkeys([*local_ids, *global_ids]))
        payloads = page_candidate_payloads(
            global_ids, self.registry, self.descriptor_fn)
        if not payloads:
            return IdentityResolution(
                "unresolved",
                reason="registered Pages have no screenshot evidence")

        transition = {
            "source_id": source_id,
            "clicked_label": clicked_label,
            "clicked_bbox": clicked_bbox,
            "clicked_point": clicked_point,
        }
        known_path = getattr(self.registry, "known_path", None)
        source_path = (
            known_path(source_id)
            if source_id and callable(known_path) else None
        )
        if source_path:
            transition["source_screenshot_path"] = str(source_path)
        try:
            choice = self.judge.which_page(
                screenshot, payloads, transition=transition,
                current_observation=None)
        except TypeError as exc:
            # Keep small fixtures and older judge adapters usable while the
            # authoritative resolver owns the transition-aware contract.
            if "transition" not in str(exc):
                raise
            choice = self.judge.which_page(
                screenshot, payloads, current_observation=None)
        valid_ids = {item["sid"] for item in payloads}
        reason = str(getattr(self.judge, "last_reason", "") or "")
        proposed_name = str(getattr(
            self.judge, "last_proposed_new_page_name", "") or "")
        if choice in valid_ids:
            return IdentityResolution("known", choice, reason)
        if choice == "UNRESOLVED":
            return IdentityResolution(
                "unresolved", reason=reason or "page identity unresolved",
                is_interruption=bool(getattr(
                    self.judge, "last_is_interruption", False)))
        if choice != "NEW":
            return IdentityResolution(
                "unresolved", reason="invalid Page identity result")
        return IdentityResolution(
            "new",
            reason=reason or "selected Page screenshots differ",
            proposed_new_page_name=proposed_name,
        )


__all__ = [
    "IdentityResolution",
    "IdentityResolver",
    "identify_existing_frame",
]
