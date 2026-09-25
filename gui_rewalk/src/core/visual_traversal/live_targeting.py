"""Current-frame target rebinding for visual traversal clicks.

The component depends on environment, perception, and reviewer services through
explicit arguments and intentionally has no dependency on ``visual_engine``.
"""

from __future__ import annotations

import copy
import io
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from .visual_perception import (
    ACTIVE_OVERLAY_SURFACE_KINDS,
    ACTIVE_SURFACE_PAGE,
    VisualElement,
    _bbox_sufficiently_inside_surface,
    _draw_som,
    _normalize_surface_kind,
)
from .visual_state import assign_element_uids
from .stateful import normalize_state_key
from . import visual_relocate as _reloc


logger = logging.getLogger(__name__)


def bbox_iou_xywh(left: Any, right: Any) -> float:
    try:
        lx, ly, lw, lh = [float(value) for value in left]
        rx, ry, rw, rh = [float(value) for value in right]
    except (TypeError, ValueError):
        return 0.0
    if min(lw, lh, rw, rh) <= 0:
        return 0.0
    x0, y0 = max(lx, rx), max(ly, ry)
    x1, y1 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def bbox_overlap_over_smaller(left: Any, right: Any) -> float:
    """Return intersection divided by the smaller box area (xywh)."""
    try:
        lx, ly, lw, lh = [float(value) for value in left]
        rx, ry, rw, rh = [float(value) for value in right]
    except (TypeError, ValueError):
        return 0.0
    if min(lw, lh, rw, rh) <= 0:
        return 0.0
    x0, y0 = max(lx, rx), max(ly, ry)
    x1, y1 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    smaller = min(lw * lh, rw * rh)
    return intersection / smaller if smaller > 0 else 0.0


def bbox_area_xywh(bbox: Any) -> float:
    try:
        width, height = float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError, IndexError):
        return float("inf")
    return max(0.0, width) * max(0.0, height)


def _point_inside_xyxy(point: Any, bbox: Any) -> bool:
    try:
        x, y = float(point[0]), float(point[1])
        x0, y0, x1, y1 = [float(value) for value in bbox]
    except (TypeError, ValueError, IndexError):
        return False
    return x0 <= x <= x1 and y0 <= y <= y1


def grounding_correction_hint(diagnostic: Any) -> str:
    """Return concise feedback for one model-produced grounding failure."""
    if not isinstance(diagnostic, dict):
        return ""
    status = str(diagnostic.get("status") or "").strip()
    if not status or status in {"matched", "agent_unavailable", "request_failed"}:
        return ""
    reason = str(
        diagnostic.get("reason") or diagnostic.get("detail")
        or "the response did not satisfy the grounding contract").strip()
    parts = [f"The previous grounding result was rejected: {status} ({reason})."]
    bbox = diagnostic.get("bbox_1000")
    point = diagnostic.get("click_point_1000")
    if bbox is not None:
        parts.append(f"Rejected bbox_1000={bbox}.")
    if point is not None:
        parts.append(f"Rejected click_point_1000={point}.")
    if status == "invalid_coordinate_space":
        parts.append(
            "Return coordinate_space=\"normalized_1000\" and do not return "
            "source-image pixel coordinates.")
    elif status == "coordinate_out_of_range":
        parts.append(
            "Every bbox_1000 and click_point_1000 value must be an integer "
            "within 0..1000, not a source-image pixel coordinate.")
    elif status == "invalid_geometry":
        parts.append(
            "Return an integer positive-area bbox_1000 within 0..1000, not "
            "source-image pixel coordinates, and keep click_point_1000 inside "
            "that bbox.")
    elif status == "surface_mismatch":
        parts.append(
            "Locate the requested control on the current frontmost active "
            "surface, not on the background interface outside it.")
    else:
        parts.append(
            "Inspect the screenshot again and return one corrected response. "
            "If the target still cannot be confirmed, return found=false.")
    return " ".join(parts)


def overlay_surface_binding(
    element: VisualElement,
) -> Optional[Tuple[str, List[int]]]:
    kind = _normalize_surface_kind(
        getattr(element, "surface_kind", ""),
        is_modal=(str(getattr(element, "surface_kind", "") or "")
                  .strip().casefold() in ACTIVE_OVERLAY_SURFACE_KINDS),
    )
    bbox = getattr(element, "surface_bbox_xywh", None)
    if (kind not in ACTIVE_OVERLAY_SURFACE_KINDS
            or not isinstance(bbox, (list, tuple)) or len(bbox) != 4):
        return None
    try:
        normalized_bbox = [int(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if normalized_bbox[2] <= 0 or normalized_bbox[3] <= 0:
        return None
    return kind, normalized_bbox


def live_overlay_surface_matches(
    element: VisualElement,
    perception: Any,
) -> bool:
    """Confirm the same active overlay still exists after live grounding."""
    binding = overlay_surface_binding(element)
    if binding is None:
        return True
    stored_kind, stored_bbox = binding
    if not bool(getattr(perception, "last_is_modal", False)):
        return False
    live_kind = _normalize_surface_kind(
        getattr(perception, "last_surface_kind", ""), is_modal=True)
    live_bbox = getattr(perception, "last_window_xywh", None)
    if live_kind != stored_kind:
        return False
    if not isinstance(live_bbox, (list, tuple)) or len(live_bbox) != 4:
        return False
    return bbox_overlap_over_smaller(stored_bbox, live_bbox) >= 0.60


def is_explicit_noninteractive(element: VisualElement) -> bool:
    return (
        getattr(element, "interactive", None) is False
        and " ".join(
            (getattr(element, "category", "") or "")
            .casefold().split()) == "display"
    )


def best_live_rebind_match(
    stored: VisualElement,
    live: List[VisualElement],
    shot: bytes,
    *,
    normalize_name: Callable[[str], str],
    name_matches: Callable[[str, str], bool],
) -> Optional[VisualElement]:
    """Find the strongest current-frame counterpart without guessing a click."""
    try:
        assign_element_uids(shot, live)
    except Exception:
        pass
    wanted_name = normalize_name(getattr(stored, "name", ""))
    wanted_uid = str(getattr(stored, "uid", "") or "")
    wanted_state_key = normalize_state_key(
        getattr(stored, "state_key", ""))
    scored = []
    for fresh in live:
        fresh_state_key = normalize_state_key(
            getattr(fresh, "state_key", ""))
        if bool(getattr(stored, "stateful", False)):
            if (not bool(getattr(fresh, "stateful", False))
                    or not wanted_state_key
                    or fresh_state_key != wanted_state_key):
                continue
        fresh_uid = str(getattr(fresh, "uid", "") or "")
        uid_match = bool(wanted_uid and fresh_uid == wanted_uid)
        name_match = bool(
            wanted_name
            and name_matches(
                wanted_name, normalize_name(getattr(fresh, "name", ""))))
        iou = bbox_iou_xywh(
            getattr(stored, "bbox_xywh", []),
            getattr(fresh, "bbox_xywh", []),
        )
        if (not wanted_state_key
                and not uid_match and not name_match and iou < 0.45):
            continue
        try:
            distance = (
                (float(fresh.center[0]) - float(stored.center[0])) ** 2
                + (float(fresh.center[1]) - float(stored.center[1])) ** 2
            )
        except Exception:
            distance = float("inf")
        element_type = " ".join(
            str(getattr(fresh, "el_type", "") or "").casefold().split())
        try:
            area = max(1, int(fresh.bbox_xywh[2])) * max(
                1, int(fresh.bbox_xywh[3]))
        except Exception:
            area = 1 << 60
        stateful_widget = element_type in {
            "switch", "toggle", "checkbox", "radio", "radio button",
        }
        rank = (
            stateful_widget if wanted_state_key else False,
            -area if wanted_state_key else 0,
            uid_match,
            name_match,
            iou,
            -distance,
        )
        scored.append((rank, fresh))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def review_rejects_target(review: Any, target: VisualElement) -> bool:
    """Return whether QA explicitly rejects this target's current box."""
    if not isinstance(review, dict):
        return False
    target_id = str(getattr(target, "id", ""))
    wrong = {str(value) for value in (review.get("wrong") or [])}
    if target_id in wrong:
        return True
    return any(
        target_id in {str(value) for value in group}
        for group in (review.get("duplicate") or [])
        if isinstance(group, list)
    )


def region_context_prior(
    element: VisualElement, shot: bytes,
) -> Tuple[VisualElement, Optional[Dict[str, Any]]]:
    """Adjust a copy's expected location only after region and context agree."""
    region_bbox = getattr(element, "region_bbox", None)
    stored_region = getattr(element, "_region_map", None)
    if stored_region is None:
        stored_region = getattr(element, "_region_template", None)
    if not isinstance(region_bbox, (list, tuple)) or len(region_bbox) != 4 \
            or stored_region is None:
        return element, None
    live_region = _reloc.crop_region(shot, list(region_bbox))
    evidence = _reloc.match_region_view(live_region, stored_region)
    if not evidence.get("accepted"):
        return element, {"accepted": False, "region": evidence}

    context = getattr(element, "_context_template", None)
    offset = getattr(element, "_context_center_offset", None)
    match = _reloc.relocate_unique(context, live_region) \
        if context is not None and offset is not None else None
    if match is None:
        return element, {"accepted": True, "region": evidence,
                         "context": "not_unique_or_missing"}
    x, y, score, margin = match
    rx0, ry0 = int(region_bbox[0]), int(region_bbox[1])
    px = rx0 + int(x) + int(offset[0])
    py = ry0 + int(y) + int(offset[1])
    prior = copy.copy(element)
    try:
        width, height = int(element.bbox_xywh[2]), int(element.bbox_xywh[3])
        prior.center = [px, py]
        prior.bbox_xywh = [px - width // 2, py - height // 2, width, height]
    except Exception:
        return element, {"accepted": True, "region": evidence,
                         "context": "invalid_stored_geometry"}
    return prior, {"accepted": True, "region": evidence,
                   "context_score": score, "context_margin": margin,
                   "predicted_center": [px, py]}


class LiveTargeting:
    """Resolve one stored element to a reviewed center on a fresh frame."""

    def __init__(
        self,
        *,
        env: Any,
        perception: Any,
        reviewer: Any = None,
        normalize_name: Callable[[str], str],
        name_matches: Callable[[str, str], bool],
        semantic_attempt_sink: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.env = env
        self.perception = perception
        self.reviewer = reviewer
        self.normalize_name = normalize_name
        self.name_matches = name_matches
        self.semantic_attempt_sink = semantic_attempt_sink
        self.last_observation: Optional[Dict[str, Any]] = None

    def _record_semantic_attempt(
        self, *, shot: bytes, stored_target: VisualElement,
        target_attempt: int, diagnostic: Dict[str, Any],
        reviewer: Dict[str, Any], grounded_target: Optional[VisualElement],
        outcome: str,
    ) -> None:
        if not callable(self.semantic_attempt_sink):
            return
        try:
            self.semantic_attempt_sink(
                screenshot_bytes=shot,
                stored_target=stored_target,
                target_attempt=target_attempt,
                diagnostic=diagnostic,
                reviewer=reviewer,
                grounded_target=grounded_target,
                outcome=outcome,
            )
        except Exception as exc:
            # Artifact IO is diagnostic only. It cannot approve or veto a click.
            logger.warning(
                "semantic grounding attempt artifact failed for '%s': %s",
                stored_target.name, exc)

    def _review_semantic_target(
        self, shot: bytes, target: VisualElement, stored_target: VisualElement,
    ) -> Dict[str, Any]:
        """Run the independent click-point reviewer and fail closed."""
        review_target = getattr(self.reviewer, "review_target", None)
        if not callable(review_target):
            return {
                "accepted": False,
                "status": "review_unavailable",
                "reason": "target reviewer unavailable",
            }
        try:
            review = review_target(shot, target, stored_target)
        except Exception as exc:
            logger.warning(
                "target reviewer failed for '%s': %s",
                stored_target.name, exc)
            return {
                "accepted": False,
                "status": "review_unavailable",
                "reason": f"review_error:{exc}",
            }
        if not isinstance(review, dict) or not isinstance(
                review.get("accepted"), bool):
            return {
                "accepted": False,
                "status": "review_unavailable",
                "reason": "invalid_review_response",
            }
        result = dict(review)
        result["status"] = (
            "target_review_accepted"
            if result["accepted"] else "target_review_rejected"
        )
        return result

    def _fixture_oracle_center(self, elem: VisualElement) -> Optional[List[int]]:
        """Return deterministic fixture geometry without VLM grounding/review."""
        resolver = getattr(self.env, "resolve_fixture_grounding", None)
        try:
            diagnostic = dict(resolver(elem) or {}) if callable(resolver) else {
                "status": "unavailable", "reason": "fixture resolver unavailable"}
        except Exception as exc:
            diagnostic = {"status": "unavailable", "reason": str(exc)}
        center = diagnostic.get("center")
        if (diagnostic.get("status") != "matched"
                or not isinstance(center, (list, tuple)) or len(center) != 2):
            self.last_observation = {
                "status": "target_not_found",
                "method": "fixture_oracle_grounding",
                "diagnostic": diagnostic,
            }
            return None
        try:
            result = [int(center[0]), int(center[1])]
        except (TypeError, ValueError):
            return None
        self.last_observation = {
            "status": "matched",
            "method": "fixture_oracle_grounding",
            "diagnostic": diagnostic,
        }
        logger.info("fixture oracle grounded '%s' -> %s (%s)",
                    elem.name, result, diagnostic.get("action_id", ""))
        return result

    def live_center_for(
        self,
        elem: VisualElement,
        obs: Optional[Dict[str, Any]],
        correction_hint: str = "",
    ) -> Optional[List[int]]:
        """Return a schema-validated current-frame center, or fail closed."""
        self.last_observation = None
        binding = overlay_surface_binding(elem)
        getter = getattr(self.env, "_get_obs", None) \
            if self.env is not None else None
        if callable(getter):
            try:
                live_obs = getter()
            except Exception as exc:
                logger.warning("live capture failed for '%s': %s", elem.name, exc)
                self.last_observation = {
                    "status": "surface_capture_failed",
                    "detail": str(exc),
                }
                return None
            if not isinstance(live_obs, dict) or not live_obs.get("screenshot"):
                self.last_observation = {
                    "status": "surface_capture_failed",
                    "detail": "fresh observation has no screenshot",
                }
                return None
            if isinstance(obs, dict):
                obs.update(live_obs)
            else:
                obs = live_obs
        elif binding is not None and self.env is not None:
            self.last_observation = {
                "status": "surface_capture_failed",
                "surface_kind": binding[0],
            }
            return None

        shot = obs.get("screenshot") if isinstance(obs, dict) else None
        if not shot:
            return None

        if bool(getattr(self.env, "fixture_oracle_grounding", False)):
            return self._fixture_oracle_center(elem)

        if bool(getattr(self.perception, "use_semantic_inventory", False)):
            review_correction = str(correction_hint or "")
            for target_attempt in (1, 2):
                target = self.perception.ground_target(
                    shot, elem, force_refresh=(target_attempt == 2),
                    correction_hint=review_correction)
                diagnostic = dict(getattr(
                    self.perception, "last_target_grounding", {}) or {})
                if target is None:
                    failure_status = str(
                        diagnostic.get("status") or "target_not_found")
                    failure_reason = str(
                        diagnostic.get("reason") or diagnostic.get("detail")
                        or "grounding_failed")
                    failed_review = {
                        "accepted": False, "status": "not_run",
                        "reason": failure_reason,
                    }
                    self._record_semantic_attempt(
                        shot=shot, stored_target=elem,
                        target_attempt=target_attempt,
                        diagnostic=diagnostic, reviewer=failed_review,
                        grounded_target=None, outcome="grounding_failed")
                    self.last_observation = {
                        "status": failure_status,
                        "method": "semantic_target_grounding",
                        "diagnostic": diagnostic,
                    }
                    if target_attempt == 1:
                        grounding_correction = grounding_correction_hint(
                            diagnostic)
                        if grounding_correction:
                            review_correction = grounding_correction
                            continue
                    return None
                if binding is not None and not _point_inside_xyxy(
                        target.center, [
                            binding[1][0],
                            binding[1][1],
                            binding[1][0] + binding[1][2],
                            binding[1][1] + binding[1][3],
                        ]):
                    surface_diagnostic = dict(diagnostic)
                    surface_diagnostic.update({
                        "status": "surface_mismatch",
                        "reason": (
                            "grounded click point is outside the current "
                            f"frontmost {binding[0]} surface"),
                        "surface_kind": binding[0],
                    })
                    failed_review = {
                        "accepted": False,
                        "status": "surface_mismatch",
                        "reason": surface_diagnostic["reason"],
                    }
                    self._record_semantic_attempt(
                        shot=shot, stored_target=elem,
                        target_attempt=target_attempt,
                        diagnostic=surface_diagnostic, reviewer=failed_review,
                        grounded_target=target, outcome="surface_mismatch")
                    self.last_observation = {
                        "status": "surface_mismatch",
                        "method": "semantic_target_grounding",
                        "fresh": target,
                        "review": failed_review,
                        "diagnostic": surface_diagnostic,
                    }
                    if target_attempt == 1:
                        review_correction = grounding_correction_hint(
                            surface_diagnostic)
                        continue
                    return None

                validation = {
                    "accepted": True,
                    "status": "locator_schema_validated",
                    "reason": "grounding output passed coordinate validation",
                }
                diagnostic["local_validation"] = validation
                review = self._review_semantic_target(shot, target, elem)
                if review.get("accepted") is True:
                    self._record_semantic_attempt(
                        shot=shot, stored_target=elem,
                        target_attempt=target_attempt,
                        diagnostic=diagnostic, reviewer=review,
                        grounded_target=target, outcome="accepted")
                    self.last_observation = {
                        "status": "matched",
                        "method": "semantic_target_grounding",
                        "fresh": target,
                        "review": review,
                        "diagnostic": diagnostic,
                    }
                    return [int(target.center[0]), int(target.center[1])]

                self._record_semantic_attempt(
                    shot=shot, stored_target=elem,
                    target_attempt=target_attempt,
                    diagnostic=diagnostic, reviewer=review,
                    grounded_target=target, outcome="review_rejected")
                self.last_observation = {
                    "status": str(
                        review.get("status") or "target_review_rejected"),
                    "method": "semantic_target_grounding",
                    "fresh": target,
                    "review": review,
                    "diagnostic": diagnostic,
                }
                if (target_attempt == 1
                        and review.get("status") == "target_review_rejected"):
                    review_correction = str(review.get("reason") or (
                        "The marked point is not confirmed on the requested "
                        "target; locate a different directly operable point."))
                    continue
                return None
            return None

        # Visual memory is a prior, never click authority.  Large-region
        # confirmation must pass before context can influence the VLM rebind.
        rebind_source, visual_evidence = region_context_prior(elem, shot)
        if visual_evidence is not None:
            logger.info(
                "region-visual prior '%s': region=%s context=%s predicted=%s",
                elem.name,
                bool(visual_evidence.get("accepted")),
                visual_evidence.get("context", "matched"),
                visual_evidence.get("predicted_center"),
            )

        for attempt in range(2):
            try:
                if attempt:
                    try:
                        live = self.perception.detect_and_name(
                            shot, force_refresh=True) or []
                    except TypeError:
                        # Lightweight test doubles may expose the old signature.
                        live = self.perception.detect_and_name(shot) or []
                else:
                    live = self.perception.detect_and_name(shot) or []
            except Exception as exc:
                logger.debug("live grounding failed for '%s': %s", elem.name, exc)
                return None
            if not live:
                return None

            # Redraw from the returned, re-numbered batch so reviewer and target
            # ids refer to exactly the same elements.
            review_elements = list(live)
            try:
                review_som = _draw_som(
                    Image.open(io.BytesIO(shot)).convert("RGB"),
                    [candidate.bbox_xywh for candidate in review_elements],
                )
            except Exception:
                review_som = None

            if binding is not None:
                if not live_overlay_surface_matches(elem, self.perception):
                    self.last_observation = {
                        "status": "surface_missing",
                        "surface_kind": binding[0],
                        "stored_surface_bbox": list(binding[1]),
                        "live_surface_kind": getattr(
                            self.perception, "last_surface_kind",
                            ACTIVE_SURFACE_PAGE),
                        "live_surface_bbox": getattr(
                            self.perception, "last_window_xywh", None),
                        "method": "live_grounding",
                    }
                    return None
                live_surface = getattr(
                    self.perception, "last_window_xywh", None)
                live = [
                    candidate for candidate in live
                    if _bbox_sufficiently_inside_surface(
                        candidate.bbox_xywh, live_surface)
                ]
                if not live:
                    return None

            region_bbox = getattr(elem, "region_bbox", None)
            if isinstance(region_bbox, (list, tuple)) and len(region_bbox) == 4:
                try:
                    rx0, ry0, rx1, ry1 = (
                        float(value) for value in region_bbox)
                    live = [
                        candidate for candidate in live
                        if rx0 <= float(candidate.center[0]) <= rx1
                        and ry0 <= float(candidate.center[1]) <= ry1
                    ]
                except (TypeError, ValueError):
                    return None
                if not live:
                    return None

            target = best_live_rebind_match(
                rebind_source,
                live,
                shot,
                normalize_name=self.normalize_name,
                name_matches=self.name_matches,
            )
            if target is None:
                return None
            if is_explicit_noninteractive(target):
                self.last_observation = {
                    "status": "noninteractive",
                    "fresh": target,
                    "method": "live_grounding",
                }
                return None

            review = {}
            if self.reviewer is not None:
                review = self.reviewer.review(review_som, review_elements)
            if review_rejects_target(review, target):
                logger.warning(
                    "click QA rejected '%s' box id=%s (%s)",
                    elem.name,
                    getattr(target, "id", ""),
                    "retrying once" if attempt == 0 else "fail-closed",
                )
                if attempt == 0:
                    continue
                self.last_observation = {
                    "status": "review_rejected",
                    "fresh": target,
                    "review": review,
                    "method": "live_grounding",
                }
                return None

            if bool(getattr(elem, "stateful", False)):
                elem.bbox_xywh = list(target.bbox_xywh)
                elem.center = [int(target.center[0]), int(target.center[1])]
                elem.el_type = target.el_type or elem.el_type
                elem.state_value = target.state_value or elem.state_value
            if visual_evidence is not None:
                self.last_observation = {
                    "status": "matched", "fresh": target,
                    "method": ("region_context_grounding"
                               if visual_evidence.get("accepted")
                               else "live_grounding"),
                    "visual_evidence": visual_evidence,
                }
            return [int(target.center[0]), int(target.center[1])]
        return None
