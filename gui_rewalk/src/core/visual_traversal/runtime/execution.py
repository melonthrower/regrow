"""Live grounding and environment execution for one candidate."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .contracts import (
    AttemptContext, CandidateContext, RunCursor, StageDirective,
    TraversalRuntimeHost,
 )
from ..grounding.scroll import (
    REGION_SCROLL_MIN_CHANGED_FRACTION, STITCH_MAX_SCROLL_STEPS,
    STITCH_SCROLL_FRAC, VIEW_STABLE_DISTANCE, _crop_normalized_region,
    _region_scroll_fraction, _scroll_action,
)

logger = logging.getLogger(__name__)
DEFAULT_PAUSE = 2.0

def _click_action(element):
    return {
        "action_type": "CLICK",
        "parameters": {"x": int(element.center[0]), "y": int(element.center[1]),
                       "button": "left"},
    }

def _review_grounded_target(reviewer, shot, target, stored_target):
    review_target = getattr(reviewer, "review_target", None)
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
            getattr(stored_target, "name", ""), exc)
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


@dataclass
class ExecutionOutcome:
    directive: StageDirective
    cursor: RunCursor
    attempt: Optional[AttemptContext] = None


def _semantic_scroll_map_target(
    host, state_id, elem, obs, correction_hint: str = "",
):
    """Resolve a target by rechecking the live viewport after every map-guided scroll."""
    perception = getattr(host, "perception", None)
    resolver = getattr(perception, "ground_target_with_scroll_map", None)
    writer = getattr(host, "writer", None)
    loader = getattr(writer, "load_region_image", None)
    region_id = str(getattr(elem, "region_id", "") or "")
    blocks = list((getattr(host, "_state_data", {}).get(state_id) or {}).get(
        "semantic_blocks") or [])
    scroll_records = getattr(
        getattr(host, "graph", None), "scroll_ledger", {}) or {}
    persisted_scroll_map = any(
        str(record.get("region_id") or "") == region_id
        and str(record.get("classification") or "") == "scrollable"
        and record.get("complete") is True
        and state_id in {
            str(value) for value in (record.get("state_ids") or [])
        }
        for record in scroll_records.values()
        if isinstance(record, dict)
    )
    if (not callable(resolver) or not callable(loader) or not region_id
            or not persisted_scroll_map):
        return None
    region_map = loader(state_id, region_id)
    shot = obs.get("screenshot") if isinstance(obs, dict) else None
    if not region_map or not shot:
        return None

    actions: List[Dict[str, Any]] = []
    block = next((
        item for item in blocks
        if str(item.get("region_id") or "") == region_id
        and isinstance(item.get("viewport_bbox_1000"), list)
        and len(item["viewport_bbox_1000"]) == 4
    ), None)
    gesture_fraction = (
        _region_scroll_fraction(block["viewport_bbox_1000"])
        if block is not None else STITCH_SCROLL_FRAC
    )

    def reclassify_clipped_target(target, diagnostic):
        """Treat a boundary-clipped scroll target as offscreen, not clickable."""
        if target is None or block is None:
            return target, str(diagnostic.get("status") or "")
        try:
            x0, y0, x1, y1 = [
                int(value) for value in diagnostic["bbox_1000"]]
            bx0, by0, bx1, by1 = [
                int(value) for value in block["viewport_bbox_1000"]]
        except (KeyError, TypeError, ValueError):
            return target, str(diagnostic.get("status") or "")
        touches_top = y0 <= by0
        touches_bottom = y1 >= by1
        if touches_top == touches_bottom:
            return target, str(diagnostic.get("status") or "")
        direction = "above" if touches_top else "below"
        try:
            image_size = list(diagnostic.get("image_size") or [])
            if len(image_size) != 2:
                from PIL import Image
                image = Image.open(io.BytesIO(shot))
                image_size = [image.width, image.height]
            width, height = [int(value) for value in image_size]
            anchor = [
                round((bx0 + bx1) * width / 2000),
                round((by0 + by1) * height / 2000),
            ]
        except (OSError, TypeError, ValueError):
            return target, str(diagnostic.get("status") or "")
        diagnostic.update({
            "model_status": str(diagnostic.get("status") or ""),
            "status": direction,
            "scroll_anchor_px": anchor,
            "geometry_reclassified": "target_bbox_touches_viewport_boundary",
            "reason": (
                f"target actionable bbox touches the scroll viewport "
                f"{'top' if touches_top else 'bottom'} boundary"
            ),
        })
        return None, direction

    def frame_stable(before, after):
        if block is not None:
            try:
                import io
                import numpy as np
                from PIL import Image

                bbox = list(block["viewport_bbox_1000"])
                before_crop = _crop_normalized_region(before, bbox)
                after_crop = _crop_normalized_region(after, bbox)
                before_pixels = np.asarray(
                    Image.open(io.BytesIO(before_crop)).convert("RGB"))
                after_pixels = np.asarray(
                    Image.open(io.BytesIO(after_crop)).convert("RGB"))
                if (before_pixels.shape == after_pixels.shape
                        and before_pixels.size):
                    delta = np.abs(
                        before_pixels.astype(np.int16)
                        - after_pixels.astype(np.int16))
                    changed_fraction = float(
                        (delta.max(axis=2) > 15).mean())
                    return (
                        changed_fraction
                        < REGION_SCROLL_MIN_CHANGED_FRACTION
                    )
            except Exception:
                pass
        hasher = getattr(host, "_frame_phash", None)
        if callable(hasher):
            try:
                return (hasher(before) - hasher(after)) <= VIEW_STABLE_DISTANCE
            except Exception:
                pass
        return before == after

    def record(target_attempt, diagnostic, review, grounded, outcome):
        sink = getattr(writer, "save_target_grounding_attempt", None)
        if not callable(sink):
            return
        try:
            sink(
                screenshot_bytes=shot, stored_target=elem,
                target_attempt=target_attempt, diagnostic=diagnostic,
                reviewer=review, grounded_target=grounded, outcome=outcome)
        except Exception as exc:
            logger.warning("scroll-map target artifact failed: %s", exc)

    def accept_visible(target, diagnostic, target_attempt):
        diagnostic["local_validation"] = {
            "accepted": True,
            "status": "locator_schema_validated",
            "reason": "scroll-map grounding passed coordinate validation",
        }
        review = _review_grounded_target(
            getattr(host, "reviewer", None), shot, target, elem)
        if review.get("accepted") is True:
            record(target_attempt, diagnostic, review, target, "accepted")
            host._last_live_rebind_observation = {
                "status": "matched", "method": "semantic_scroll_map_target",
                "diagnostic": diagnostic, "review": review, "fresh": target,
            }
            return [int(target.center[0]), int(target.center[1])]

        record(
            target_attempt, diagnostic, review, target, "review_rejected")
        host._last_live_rebind_observation = {
            "status": str(
                review.get("status") or "target_review_rejected"),
            "method": "semantic_scroll_map_target",
            "diagnostic": diagnostic, "review": review, "fresh": target,
        }
        if review.get("status") != "target_review_rejected":
            return None

        corrected = resolver(
            shot, region_map, elem, force_refresh=True,
            correction_hint=str(review.get("reason") or (
                "The marked point is not confirmed on the requested target; "
                "locate a different directly operable point.")))
        corrected_diagnostic = dict(getattr(
            perception, "last_scroll_map_grounding", {}) or {})
        corrected_status = str(corrected_diagnostic.get("status") or "")
        if corrected_status == "visible":
            corrected, corrected_status = reclassify_clipped_target(
                corrected, corrected_diagnostic)
        corrected_attempt = target_attempt + 1
        if corrected is None or corrected_status != "visible":
            failed_review = {
                "accepted": False,
                "status": "not_run",
                "reason": "corrected grounding was not a visible target",
            }
            record(
                corrected_attempt, corrected_diagnostic, failed_review,
                corrected, "grounding_failed")
            host._last_live_rebind_observation = {
                "status": "target_review_correction_failed",
                "method": "semantic_scroll_map_target",
                "diagnostic": corrected_diagnostic,
                "review": failed_review,
            }
            return None

        corrected_diagnostic["local_validation"] = {
            "accepted": True,
            "status": "locator_schema_validated",
            "reason": "scroll-map grounding passed coordinate validation",
        }
        corrected_review = _review_grounded_target(
            getattr(host, "reviewer", None), shot, corrected, elem)
        corrected_outcome = (
            "accepted"
            if corrected_review.get("accepted") is True
            else "review_rejected"
        )
        record(
            corrected_attempt, corrected_diagnostic, corrected_review,
            corrected, corrected_outcome)
        host._last_live_rebind_observation = {
            "status": (
                "matched" if corrected_review.get("accepted") is True
                else str(corrected_review.get("status")
                         or "target_review_rejected")
            ),
            "method": "semantic_scroll_map_target",
            "diagnostic": corrected_diagnostic,
            "review": corrected_review,
            "fresh": corrected,
        }
        if corrected_review.get("accepted") is not True:
            return None
        return [int(corrected.center[0]), int(corrected.center[1])]

    current_obs = obs
    for target_attempt in range(1, STITCH_MAX_SCROLL_STEPS + 2):
        resolver_kwargs = {"force_refresh": False}
        if correction_hint:
            resolver_kwargs["correction_hint"] = correction_hint
        target = resolver(shot, region_map, elem, **resolver_kwargs)
        diagnostic = dict(getattr(
            perception, "last_scroll_map_grounding", {}) or {})
        status = str(diagnostic.get("status") or "")
        if status == "visible":
            target, status = reclassify_clipped_target(target, diagnostic)
        if target is not None and status == "visible":
            center = accept_visible(target, diagnostic, target_attempt)
            if center is None:
                return {
                    "center": None, "observation": current_obs,
                    "actions": actions,
                    "status": str((getattr(
                        host, "_last_live_rebind_observation", {}) or {}).get(
                            "status") or "target_review_rejected"),
                }
            return {
                "center": center, "observation": current_obs,
                "actions": actions, "status": "matched",
            }
        if status == "absent":
            review = {
                "accepted": False, "status": "not_run",
                "reason": "target absent from stored Region long image",
            }
            record(target_attempt, diagnostic, review, None, "grounding_failed")
            host._last_live_rebind_observation = {
                "status": "target_absent_from_scroll_map",
                "method": "semantic_scroll_map_target",
                "diagnostic": diagnostic,
            }
            return {
                "center": None, "observation": current_obs,
                "actions": actions, "status": "absent",
            }
        if status not in {"above", "below"}:
            return None

        record(target_attempt, diagnostic, {
            "accepted": False, "status": "not_run",
            "reason": f"target is {status} the current viewport",
        }, None, "offscreen")
        if len(actions) >= STITCH_MAX_SCROLL_STEPS:
            break
        anchor = list(diagnostic.get("scroll_anchor_px") or [])
        if len(anchor) != 2:
            return None
        direction = "up" if status == "above" else "down"
        action = _scroll_action(
            direction, frac=gesture_fraction, slow=True)
        action["parameters"].update({"x": int(anchor[0]), "y": int(anchor[1])})
        try:
            next_obs = host.env.step(action, pause=0.4)
        except Exception as exc:
            host._last_live_rebind_observation = {
                "status": "scroll_failed", "method": "semantic_scroll_map_target",
                "detail": str(exc), "diagnostic": diagnostic,
            }
            return {"center": None, "observation": current_obs,
                    "actions": actions, "status": "scroll_failed"}
        actions.append(action)
        if getattr(host, "_settle_enabled", False):
            next_obs = host._settle(next_obs)
        next_obs, _relaunched, on_app = host._ensure_on_app(next_obs)
        if (not on_app or not isinstance(next_obs, dict)
                or not next_obs.get("screenshot")):
            host._last_live_rebind_observation = {
                "status": "surface_capture_failed",
                "method": "semantic_scroll_map_target",
            }
            return {
                "center": None, "observation": next_obs,
                "actions": actions, "status": "surface_capture_failed",
            }
        next_shot = next_obs["screenshot"]
        if frame_stable(shot, next_shot):
            host._last_live_rebind_observation = {
                "status": "scroll_stalled",
                "method": "semantic_scroll_map_target",
                "diagnostic": diagnostic,
            }
            return {
                "center": None, "observation": next_obs,
                "actions": actions, "status": "scroll_stalled",
            }
        current_obs = next_obs
        shot = next_shot

    record(STITCH_MAX_SCROLL_STEPS + 1, diagnostic, {
        "accepted": False, "status": "not_run",
        "reason": "target not visible before the map-guided safety limit",
    }, None, "grounding_failed")
    host._last_live_rebind_observation = {
        "status": "scroll_safety_limit",
        "method": "semantic_scroll_map_target",
        "diagnostic": diagnostic,
    }
    return {"center": None, "observation": current_obs,
            "actions": actions, "status": "scroll_safety_limit"}

def execute_candidate(host: TraversalRuntimeHost, cursor: RunCursor,
                      plan: CandidateContext) -> ExecutionOutcome:
    """Live-bind, execute and persist the attempted→executed event boundary."""
    elem = plan.element
    decision_reason = plan.decision_reason
    _is_stateful_action = plan.is_stateful
    _stateful_evidence = dict(plan.stateful_evidence)
    current_id = cursor.state_id
    current_obs = cursor.observation
    current_path = list(cursor.path)
    current_hints = list(cursor.replay_hints)

    def done(directive):
        return ExecutionOutcome(directive, RunCursor(
            current_id, current_obs, list(current_path),
            list(current_hints), cursor.off_app_streak,
        ))

    def recover_inherited_target() -> bool:
        """Keep the old full-registration recovery out of IdentityResolver."""
        nonlocal current_id, current_path, current_hints
        marker = getattr(host, "_map_guided_inherited", None)
        if not isinstance(marker, dict) or marker.get("state_id") != current_id:
            return False
        host._map_guided_inherited = None
        semantic = bool(getattr(
            getattr(host, "perception", None),
            "use_semantic_inventory", False))
        if semantic and getattr(host, "identity_resolver", None) is not None:
            # IdentityResolver has already confirmed this Page. Re-registering
            # here would only resolve to the same ledger again and prevent the
            # target's ordinary bounded failure count from advancing.
            return False
        host._map_guided_bypass_once = True
        try:
            corrected_id, _is_new = host._register(
                current_obs, current_path, current_hints)
        except Exception as exc:
            logger.warning("map-guided forced registration failed: %s", exc)
            host.review_debug.record_event(
                "map_guided_forced_registration", node=current_id,
                verdict="failed", reason=str(exc)[:200])
            return False
        finally:
            host._map_guided_bypass_once = False
        corrected = host._state_data.get(corrected_id) or {}
        current_id = corrected_id
        current_path = list(corrected.get("path", current_path))
        current_hints = list(corrected.get("replay_hints", current_hints) or [])
        host.review_debug.record_event(
            "map_guided_forced_registration", node=corrected_id,
            verdict="recovered", failed_target=getattr(elem, "name", ""))
        return True

    if not plan.targeted:
        action = dict(plan.action or {})
        _verify_effect = bool(host._verify_navigation_effect)
        _before_shot = (current_obs or {}).get("screenshot")
        _attempt_label = host._edge_label(elem, decision_reason)
        _ledger_action = host._portable_graph_action(action, elem)
        host._action_count += 1
        _event_index = None
        if hasattr(host.graph, "record_action_event"):
            event_evidence = {}
            if plan.direct_action:
                event_evidence = {
                    "element_agent_direct_action": True,
                    "element_agent_target": str(
                        getattr(elem, "name", "") or ""),
                    "element_agent_action_type": str(
                        action.get("action_type") or ""),
                }
                parameters = dict(action.get("parameters") or {})
                if "x" in parameters and "y" in parameters:
                    event_evidence["element_agent_point_px"] = [
                        int(parameters["x"]), int(parameters["y"])]
            _event_index = host.graph.record_action_event(
                source=current_id, action=_ledger_action,
                element_id=str(getattr(elem, "id", "") or ""),
                element_label=str(getattr(elem, "name", "") or ""),
                semantic_description=_attempt_label,
                region=str(getattr(elem, "region", "") or ""),
                outcome="attempted", committed=False,
                evidence=event_evidence,
            )
        save_attempt_shot = getattr(
            host, "_save_action_attempt_screenshot", None)
        if callable(save_attempt_shot):
            save_attempt_shot(_event_index, "before", _before_shot)
        def _update_event(**changes):
            if (_event_index is not None
                    and hasattr(host.graph, "update_action_event")):
                evidence = changes.pop("evidence", None)
                if changes:
                    host.graph.update_action_event(_event_index, **changes)
                if evidence is not None and hasattr(
                        host.graph, "merge_action_event_evidence"):
                    host.graph.merge_action_event_evidence(
                        _event_index, evidence)
                elif evidence is not None:
                    host.graph.update_action_event(
                        _event_index, evidence=evidence)
        try:
            obs = host.env.step(action, pause=DEFAULT_PAUSE)
        except Exception as exc:
            _update_event(outcome="execution_error", detail=str(exc)[:240],
                          landing_verified=False)
            host._maybe_save()
            return done(StageDirective.CONTINUE)
        _update_event(outcome="executed")
        if host._settle_enabled:
            obs = host._settle(obs)
        if callable(save_attempt_shot):
            save_attempt_shot(
                _event_index, "after",
                (obs or {}).get("screenshot"))
        obs, relaunched, on_app = host._ensure_on_app(obs)
        current_obs = obs
        attempt = AttemptContext(
            candidate=plan, observation=obs, action=action,
            pre_actions=[], before_shot=_before_shot,
            verify_effect=_verify_effect, attempt_label=_attempt_label,
            ledger_action=_ledger_action, event_index=_event_index,
            update_event=_update_event, relaunched=relaunched, on_app=on_app,
        )
        return ExecutionOutcome(
            StageDirective.RECOVERY,
            RunCursor(current_id, current_obs, list(cursor.path),
                      list(cursor.replay_hints), cursor.off_app_streak),
            attempt)

    pre_actions: List[Dict[str, Any]] = []
    live_center: Optional[List[int]] = None
    if plan.direct_action:
        direct_action = dict(plan.action or {})
        direct_type = str(direct_action.get("action_type") or "")
        direct_parameters = (
            direct_action
            if direct_type[:1].islower() else
            dict(direct_action.get("parameters") or {})
        )
        try:
            live_center = [
                int(direct_parameters["x"]), int(direct_parameters["y"])]
        except (KeyError, TypeError, ValueError):
            host.review_debug.record_event(
                "element_agent_direct_action", node=current_id,
                verdict="invalid", reason="direct CLICK has no pixel point")
            return done(StageDirective.CONTINUE)
        elem.center = list(live_center)
        host.review_debug.record_event(
            "element_agent_direct_action", node=current_id,
            verdict="accepted", element=str(getattr(elem, "name", "") or ""),
            center=list(live_center))
    else:
        correction_lookup = getattr(host, "_targeting_correction_for", None)
        correction_hint = (
            correction_lookup(current_id, elem)
            if callable(correction_lookup) else "")
        scroll_map_result = _semantic_scroll_map_target(
            host, current_id, elem, current_obs,
            correction_hint=correction_hint)
        if scroll_map_result is not None:
            current_obs = scroll_map_result["observation"]
            pre_actions.extend(scroll_map_result["actions"])
            live_center = scroll_map_result["center"]
            if live_center is None:
                if recover_inherited_target():
                    return done(StageDirective.CONTINUE)
                failure_count = host._record_click_failure(
                    current_id, elem, "scroll_map_target_not_confirmed") or 1
                logger.warning(
                    "scroll-map target '%s' not confirmed (%s, failure %d); "
                    "continuing traversal", elem.name,
                    scroll_map_result.get("status"), failure_count)
                return done(StageDirective.CONTINUE)
            elem.center = list(live_center)
        else:
            live_center = (
                host._live_center_for(
                    elem, current_obs, correction_hint=correction_hint)
                if correction_hint else
                host._live_center_for(elem, current_obs)
            )
            if live_center is None:
                if recover_inherited_target():
                    return done(StageDirective.CONTINUE)
                if host._retire_live_noninteractive_reclassification(
                        current_id, elem):
                    host._maybe_save()
                    return done(StageDirective.CONTINUE)
                host._record_click_failure(
                    current_id, elem, "visible_target_not_confirmed")
                return done(StageDirective.CONTINUE)
            if live_center != list(elem.center):
                logger.info("visible live retarget '%s' %s -> %s",
                            elem.name, elem.center, live_center)
                elem.center = live_center
    marker = getattr(host, "_map_guided_inherited", None)
    if isinstance(marker, dict) and marker.get("state_id") == current_id:
        # The one immediate target was successfully rebound.  Later failures
        # must use the ordinary retry/retirement policy, not this safety guard.
        host._map_guided_inherited = None
    action = dict(plan.action or {}) or _click_action(elem)
    action_type = str(action.get("action_type") or "")
    if not plan.direct_action:
        if action_type[:1].islower():
            action.update({"x": int(elem.center[0]), "y": int(elem.center[1])})
        else:
            parameters = dict(action.get("parameters") or {})
            parameters.update({"x": int(elem.center[0]),
                               "y": int(elem.center[1])})
            if action_type in {"CLICK", "RIGHT_CLICK", "DOUBLE_CLICK"}:
                parameters.setdefault("button", "left")
            action["parameters"] = parameters
    _verify_effect = bool(host._verify_navigation_effect)
    _before_shot = (current_obs or {}).get("screenshot")
    _attempt_label = (host._stateful_edge_label(
                          elem,
                          _stateful_evidence.get("expected_after_value", ""))
                      if _is_stateful_action
                      else host._edge_label(elem, decision_reason))
    _ledger_action = host._portable_graph_action(action, elem)
    if _is_stateful_action:
        host._stateful_inflight = dict(_stateful_evidence)
    host._action_count += 1
    _event_index = None
    if hasattr(host.graph, "record_action_event"):
        event_evidence = dict(_stateful_evidence)
        if plan.direct_action:
            event_evidence.update({
                "element_agent_direct_action": True,
                "element_agent_target": str(elem.name or ""),
                "element_agent_action_type": action_type,
                "element_agent_point_px": list(live_center or []),
            })
        _event_index = host.graph.record_action_event(
            source=current_id,
            action=_ledger_action,
            element_id=str(elem.id),
            element_label=str(elem.name or _attempt_label),
            semantic_description=_attempt_label,
            region=getattr(elem, "region", "") or "",
            outcome="attempted",
            committed=False,
            evidence=event_evidence,
        )
    save_attempt_shot = getattr(
        host, "_save_action_attempt_screenshot", None)
    if callable(save_attempt_shot):
        save_attempt_shot(_event_index, "before", _before_shot)
    def _update_event(**changes):
        if _event_index is not None \
                and hasattr(host.graph, "update_action_event"):
            evidence = changes.pop("evidence", None)
            if changes:
                host.graph.update_action_event(_event_index, **changes)
            if evidence is not None and hasattr(
                    host.graph, "merge_action_event_evidence"):
                host.graph.merge_action_event_evidence(
                    _event_index, evidence)
            elif evidence is not None:
                host.graph.update_action_event(
                    _event_index, evidence=evidence)
    try:
        obs = host.env.step(action, pause=DEFAULT_PAUSE)
    except Exception as e:
        if _is_stateful_action:
            host._stateful_inflight = None
        logger.warning("click failed on '%s': %s", elem.name, e)
        _update_event(
            outcome="execution_error",
            detail=str(e)[:240],
            landing_verified=False,
        )
        host._record_click_failure(current_id, elem, "env_step_failed")
        host._maybe_save()
        return done(StageDirective.CONTINUE)
    _update_event(outcome="executed")
    if host._settle_enabled:
        obs = host._settle(obs)
    if callable(save_attempt_shot):
        save_attempt_shot(
            _event_index, "after",
            (obs or {}).get("screenshot"))
    obs, relaunched, on_app = host._ensure_on_app(obs)
    current_obs = obs
    next_cursor = RunCursor(
        current_id, current_obs, list(cursor.path),
        list(cursor.replay_hints), cursor.off_app_streak,
    )
    attempt = AttemptContext(
        candidate=plan, observation=obs, action=action,
        pre_actions=pre_actions, before_shot=_before_shot,
        verify_effect=_verify_effect, attempt_label=_attempt_label,
        ledger_action=_ledger_action, event_index=_event_index,
        update_event=_update_event, relaunched=relaunched, on_app=on_app,
    )
    return ExecutionOutcome(StageDirective.RECOVERY, next_cursor, attempt)
