"""Foreground/interruption recovery and unknown-landing adoption."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from .contracts import (
    AttemptContext, PerceptionUnavailable, RunCursor, StageDirective,
)

logger = logging.getLogger(__name__)

INTERRUPTION_MAX_ROUNDS = 3

class RecoveryHost(Protocol):
    pass

@dataclass
class RecoveryObservation:
    observation: object
    relaunched: bool
    on_app: bool


def ensure_on_app(
    host: RecoveryHost,
    obs: Dict[str, Any],
    *,
    pause: float,
) -> Tuple[Dict[str, Any], bool, bool]:
    """Return a live target-app observation or fail closed.

    System-owned foreground evidence is checked once, then once more after the
    current frame settles. A confirmed external/unobservable surface gets one
    cheap BACK/Esc recovery before bounded relaunch. Unknown ownership never
    mutates the GUI, and no off-app frame is registered here.
    """
    host._last_off_app_kind = ""
    host._last_off_app_reason = ""
    host._last_off_app_recovered_by_back = False
    if host.focus_guard is None:
        return obs, False, True
    shot = obs.get("screenshot")
    if not shot:
        host._last_off_app_kind = "screenshot_unavailable"
        host._last_off_app_reason = "observation has no screenshot"
        on_app = False
    else:
        on_app = host._is_target_app_foreground(shot)
    # Window/task metadata can be transiently false or unavailable while an
    # action settles. Re-read once before any recovery mutation.
    if on_app is not True and shot:
        try:
            settled = host._settle(obs) if host._settle_enabled else obs
            settled_shot = settled.get("screenshot") if settled else None
            if settled_shot:
                on_app = host._is_target_app_foreground(settled_shot)
                obs = settled
                shot = settled_shot
        except Exception:
            pass
    if on_app is None:
        host._last_off_app_kind = "focus_unknown"
        host._last_off_app_reason = (
            getattr(host.focus_guard, "last_reason", "")
            or "system foreground ownership unavailable")
        host.review_debug.record_event(
            "system_app_focus", step=host._action_count,
            verdict="focus_unknown", reason=host._last_off_app_reason)
        return obs, False, False
    if on_app is False and shot:
        host._last_off_app_kind = getattr(
            host.focus_guard, "last_kind", "external_app") or "external_app"
        host._last_off_app_reason = getattr(
            host.focus_guard, "last_reason", "") or "left target app"
    host.review_debug.record_event(
        "system_app_focus", step=host._action_count,
        verdict=("on_app" if on_app else "off_app"),
        reason=getattr(host.focus_guard, "last_reason", ""))
    # A system overlay is often cheaper to dismiss than recovering by relaunch.
    if not on_app:
        try:
            action = (
                {"action_type": "navigate_back"}
                if getattr(host, "_is_touch", True) else
                {"action_type": "PRESS", "parameters": {"key": "esc"}}
            )
            obs = host.env.step(action, pause=pause)
            shot = obs.get("screenshot")
            after_back = (
                host._is_target_app_foreground(shot) if shot else False)
            if after_back is True:
                logger.info(
                    "focus guard: BACK dismissed an off-app overlay "
                    "(OS/GMS dialog) — stayed in '%s'", host.app_name)
                on_app = True
                host._last_off_app_recovered_by_back = True
            elif after_back is None:
                host._last_off_app_kind = "focus_unknown"
                host._last_off_app_reason = (
                    getattr(host.focus_guard, "last_reason", "")
                    or "system foreground ownership unavailable")
                return obs, False, False
            elif shot:
                host._last_off_app_kind = getattr(
                    host.focus_guard, "last_kind", "unknown") or "unknown"
                host._last_off_app_reason = getattr(
                    host.focus_guard, "last_reason", "") or ""
        except Exception as exc:
            logger.debug("focus guard: BACK-dismiss failed (%s)", exc)
    attempts = 0
    relaunched = False
    if not on_app and host.relaunch_fn is None:
        return obs, False, False
    while attempts < host.MAX_RELAUNCH_ATTEMPTS and not on_app:
        attempts += 1
        host._relaunch_attempts += 1
        logger.warning(
            "focus guard: off-app detected, relaunching '%s' (attempt %d)",
            host.app_name, attempts)
        try:
            obs = host.relaunch_fn()
        except Exception as exc:
            logger.warning("focus guard: relaunch failed: %s", exc)
            return obs, relaunched, False
        relaunched = True
        shot = obs.get("screenshot")
        if not shot:
            return obs, relaunched, False
        on_app = host._is_target_app_foreground(shot)
        if on_app is None:
            host._last_off_app_kind = "focus_unknown"
            host._last_off_app_reason = (
                getattr(host.focus_guard, "last_reason", "")
                or "system foreground ownership unavailable")
            return obs, relaunched, False
    if not on_app:
        logger.warning(
            "focus guard: still OFF-APP after %d relaunch attempts for '%s' — "
            "refusing to register off-app screen", attempts, host.app_name)
    return obs, relaunched, on_app


def dismiss_interruptions(
    host: RecoveryHost,
    obs: Dict[str, Any],
    *,
    pause: float,
    force_first: bool = False,
    page_identity_flagged: bool = False,
) -> Dict[str, Any]:
    """Dismiss bounded startup or Page-identity interruptions.

    Perception decides whether the current surface is an interruption; the
    existing InterruptionDismisser chooses a safe control. Startup may force
    one semantic check before root registration, while Page Identity may
    explicitly flag the first round.
    """
    host._startup_surface_unresolved = False
    if (
        not force_first
        and not page_identity_flagged
        and bool(getattr(host.perception, "use_semantic_inventory", False))
        and os.environ.get("GUIWALK_REGION_LAZY_INVENTORY", "1") == "1"
    ):
        return obs
    if not getattr(host, "_dismiss_enabled", True) or host.interruption is None:
        return obs
    force_refresh_inventory = False
    for round_index in range(INTERRUPTION_MAX_ROUNDS):
        shot = obs.get("screenshot")
        if not shot:
            return obs
        try:
            if getattr(host.perception, "use_semantic_inventory", False):
                cached_shot = getattr(
                    host.perception, "_cur_frame_bytes", None)
                cached = list(getattr(
                    host.perception, "last_all_elements", []) or [])
                elements = (
                    cached
                    if (not force_refresh_inventory
                        and cached_shot == shot and cached)
                    else host.perception.semantic_inventory(
                        shot, force_refresh=force_refresh_inventory)
                )
            else:
                elements = host.perception.detect_and_name(shot)
            force_refresh_inventory = False
        except Exception as exc:
            logger.debug("dismiss: perception failed (%s)", exc)
            return obs
        flagged = bool(getattr(
            host.perception, "last_is_interruption", False))
        if page_identity_flagged and round_index == 0:
            flagged = True
        if not flagged and not force_first and not page_identity_flagged:
            return obs
        decision = host.interruption.decide(shot, elements)
        button = decision.get("button")
        host.review_debug.record_agent(
            "dismisser", step=host._action_count,
            verdict=(getattr(button, "name", "") if button else "no-control"),
            reason=str(decision.get("reason", ""))[:120],
            round=round_index + 1,
        )
        if decision.get("action") != "click" or button is None:
            usable_controls = any(
                bool(getattr(element, "interactive", False))
                and getattr(element, "enabled", None) is not False
                for element in elements
            )
            passive_startup = force_first and not usable_controls
            if ((flagged or passive_startup)
                    and round_index + 1 < INTERRUPTION_MAX_ROUNDS):
                import time
                logger.info(
                    "dismiss: waiting for passive startup/interruption "
                    "(round %d/%d)", round_index + 1,
                    INTERRUPTION_MAX_ROUNDS)
                time.sleep(pause)
                try:
                    obs = host.env._get_obs()
                    if host._settle_enabled:
                        obs = host._settle(obs)
                except Exception as exc:
                    logger.warning(
                        "dismiss: passive wait failed (%s)", exc)
                    if flagged:
                        host._startup_surface_unresolved = True
                    return obs
                force_refresh_inventory = True
                continue
            if flagged:
                host._startup_surface_unresolved = True
            if decision.get("action") == "done" and not flagged:
                logger.info(
                    "dismiss: normal frame confirmed; no interruption")
            elif flagged:
                logger.info(
                    "dismiss: interruption flagged but no safe control chosen "
                    "— leaving frame as-is")
            else:
                logger.info(
                    "dismiss: no dismissal requested — leaving frame as-is")
            return obs
        center = host._live_center_for(button, obs)
        if center is None:
            logger.info(
                "dismiss: '%s' could not be rebound and reviewed; no click",
                button.name)
            if flagged:
                host._startup_surface_unresolved = True
            return obs
        cx, cy = center
        logger.info(
            "dismiss: closing interruption via '%s' (round %d/%d)",
            button.name, round_index + 1, INTERRUPTION_MAX_ROUNDS)
        try:
            obs = host.env.step(
                {"action_type": "CLICK",
                 "parameters": {"x": cx, "y": cy, "button": "left"}},
                pause=pause)
            if host._settle_enabled:
                obs = host._settle(obs)
        except Exception as exc:
            logger.warning("dismiss: click failed (%s)", exc)
            return obs
    logger.info(
        "dismiss: still flagged after %d rounds — giving up",
        INTERRUPTION_MAX_ROUNDS)
    host._startup_surface_unresolved = bool(
        getattr(host.perception, "last_is_interruption", False))
    return obs


def recover_route_observation(host: RecoveryHost, observation):
    current, relaunched, on_app = host._ensure_on_app(observation)
    return RecoveryObservation(current, relaunched, on_app)


def refresh_verified_landing(
    host: RecoveryHost, observation, target_id: str, *, strict: bool = False,
):
    """Refresh live evidence after Router verified an existing landing."""
    target_id = str(target_id)
    target = host._state_data.get(target_id) or {}
    path = list(target.get("path") or [])
    hints = list(target.get("replay_hints") or [])
    sentinel = object()
    prior_preferred = getattr(
        host, "_registration_preferred_state_once", sentinel)
    prior_bypass = getattr(host, "_map_guided_bypass_once", sentinel)
    host._registration_preferred_state_once = target_id
    host._map_guided_bypass_once = True
    host._last_live_observation_elements = None
    host._last_live_observation_state_id = None
    try:
        state_id, _is_new = host._register(observation, path, hints)
    except PerceptionUnavailable:
        host._last_arrival_rset = set()
        host._last_arrival_names = []
        host._last_arrival_page_name = ""
        if strict:
            return None, [], []
        return target_id, path, hints
    finally:
        if prior_preferred is sentinel:
            try:
                delattr(host, "_registration_preferred_state_once")
            except AttributeError:
                pass
        else:
            host._registration_preferred_state_once = prior_preferred
        if prior_bypass is sentinel:
            try:
                delattr(host, "_map_guided_bypass_once")
            except AttributeError:
                pass
        else:
            host._map_guided_bypass_once = prior_bypass
    state_id = str(state_id)
    if strict and state_id != target_id:
        return None, [], []
    actual = host._state_data.get(state_id) or {}
    return (
        state_id,
        list(actual.get("path") or path),
        list(actual.get("replay_hints") or hints),
    )


def adopt_relaunch_landing(
    host: RecoveryHost, obs: Dict[str, Any], parent_id: Optional[str] = None,
    parent_action: Optional[Dict[str, Any]] = None,
    parent_label: str = "",
) -> Tuple[
    Optional[str],
    List[Dict[str, Any]],
    List[Optional[Dict[str, Any]]],
    bool,
]:
    """Adopt the real on-app landing after a relaunch.

    Candidate matching may recognize a persisted state directly. If it cannot,
    register the fresh screenshot normally: registration may still merge it by
    visual/functional evidence, or create the genuinely new landing. Relaunch
    is a root observation, so a newly registered landing starts with an empty
    replay path.
    """
    landed_id = host._router_identify(obs, source_id=parent_id)
    landed_is_new = False
    known_landing = bool(
        landed_id
        and landed_id in host.graph.graph
        and landed_id in host._state_data
    )
    if known_landing:
        try:
            landed_id, _path, _hints = refresh_verified_landing(
                host, obs, str(landed_id), strict=True)
        except Exception as exc:
            logger.error(
                "recovery could not refresh the live known landing: %s", exc)
            landed_id = None
        if not landed_id:
            logger.error(
                "recovery could not refresh usable live evidence for the "
                "known landing")
            host.graph.stop_reason = "state_restore_failed"
            return None, [], [], False
        logger.info(
            "recovery refreshed actual known landing %s", landed_id)
    else:
        try:
            landed_id, landed_is_new = host._register(obs, [], [])
        except Exception as exc:
            logger.error(
                "recovery could not register the live relaunch landing: %s",
                exc)
            host.graph.stop_reason = "state_restore_failed"
            return None, [], [], False
        if (not landed_id
                or landed_id not in host.graph.graph
                or landed_id not in host._state_data):
            logger.error(
                "recovery registration returned no usable live landing")
            host.graph.stop_reason = "state_restore_failed"
            return None, [], [], False
        logger.info(
            "recovery adopted actual relaunch landing %s (%s)",
            landed_id, "new" if landed_is_new else "revisit")
    data = host._state_data[landed_id]
    path = list(data.get("path") or [])
    hints = list(data.get("replay_hints") or [])
    if (parent_id is not None and parent_action is not None
            and parent_id in host.graph.graph
            and not host.graph.graph.has_edge(parent_id, landed_id)):
        host.graph.add_transition(
            src=parent_id, dst=landed_id, action=parent_action,
            element_id="", element_label=parent_label,
            semantic_description=parent_label or "(relaunch-reconnect)",
        )
        logger.info("relaunch: reconnected edge %s -> %s (preserved in-flight "
                    "transition)", parent_id, landed_id)
    return landed_id, path, hints, landed_is_new




@dataclass
class RecoveryOutcome:
    directive: StageDirective
    cursor: RunCursor

def recover_attempt(host: RecoveryHost, cursor: RunCursor,
                    attempt: AttemptContext) -> RecoveryOutcome:
    """Handle off-app and relaunch outcomes before landing verification."""
    plan = attempt.candidate
    elem = plan.element
    action = attempt.action
    obs = attempt.observation
    relaunched = attempt.relaunched
    on_app = attempt.on_app
    _update_event = attempt.update_event
    _is_stateful_action = plan.is_stateful
    _stateful_evidence = dict(plan.stateful_evidence)
    _mutation_id = plan.mutation_id
    current_id = cursor.state_id
    current_path = list(cursor.path)
    current_hints = list(cursor.replay_hints)
    current_obs = obs
    off_app_streak = cursor.off_app_streak

    def done(directive):
        return RecoveryOutcome(directive, RunCursor(
            current_id, current_obs, list(current_path),
            list(current_hints), off_app_streak,
        ))

    if (on_app and not relaunched and bool(getattr(
            host, "_last_off_app_recovered_by_back", False))):
        _off_kind = host._last_off_app_kind or "unknown"
        _off_reason = host._last_off_app_reason or "left target app"
        _terminal_outcome = host._terminal_off_app_outcome(_off_kind)
        if _terminal_outcome:
            host._record_abnormal_button(
                current_id, elem, _terminal_outcome, _off_reason, action)
        if _is_stateful_action:
            _update_event(
                outcome=(_terminal_outcome or _off_kind),
                detail=_off_reason,
                evidence={
                    "focus_kind": _off_kind,
                    "recovered": True,
                    "recovery_action": "navigate_back",
                },
            )
            host.review_debug.record_event(
                "off_app_click", node=current_id, elem=elem.name,
                recovered=True, recovery_action="navigate_back",
                kind=_off_kind, reason=_off_reason)
            host.graph.save(host.graph_save_path)
            host.graph.stop_reason = "state_restore_failed"
            logger.error(
                "stateful click left the target app before BACK recovery; "
                "mutation outcome is unknown, stopping fail-closed")
            return done(StageDirective.STOP)
        recovered_id, recovered_path, recovered_hints, _recovered_is_new = \
            host._register_landed(obs, parent_id=current_id)
        if recovered_id is None:
            _update_event(
                outcome=(_terminal_outcome or _off_kind),
                detail=_off_reason,
                evidence={
                    "focus_kind": _off_kind,
                    "recovered": True,
                    "recovery_action": "navigate_back",
                    "landing_identified": False,
                },
            )
            host.review_debug.record_event(
                "off_app_click", node=current_id, elem=elem.name,
                recovered=True, recovery_action="navigate_back",
                kind=_off_kind, reason=_off_reason,
                landing_identified=False)
            host.graph.stop_reason = "state_restore_failed"
            host.graph.save(host.graph_save_path)
            return done(StageDirective.STOP)
        current_id = recovered_id
        current_path = list(recovered_path)
        current_hints = list(recovered_hints)
        _update_event(
            outcome=(_terminal_outcome or _off_kind),
            detail=_off_reason,
            evidence={
                "focus_kind": _off_kind,
                "recovered": True,
                "recovery_action": "navigate_back",
                "landing_identified": True,
                "recovered_state": current_id,
            },
        )
        host.review_debug.record_event(
            "off_app_click", node=cursor.state_id, elem=elem.name,
            recovered=True, recovery_action="navigate_back",
            kind=_off_kind, reason=_off_reason,
            recovered_state=current_id)
        host.graph.save(host.graph_save_path)
        return done(StageDirective.CONTINUE)

    if not on_app:
        _off_kind = host._last_off_app_kind or "unknown"
        _off_reason = host._last_off_app_reason or "target app unavailable"
        if _off_kind == "focus_unknown":
            _update_event(
                outcome="focus_unknown",
                detail=_off_reason,
                evidence={"focus_kind": _off_kind, "recovered": False},
            )
            host.review_debug.record_event(
                "app_focus_unknown", node=current_id, elem=elem.name,
                reason=_off_reason)
            host.graph.stop_reason = "focus_unknown"
            host.graph.save(host.graph_save_path)
            return done(StageDirective.STOP)
        _terminal_outcome = host._terminal_off_app_outcome(_off_kind)
        if _terminal_outcome:
            host._record_abnormal_button(
                current_id, elem, _terminal_outcome, _off_reason, action)
        _update_event(
            outcome=(_terminal_outcome or _off_kind),
            detail=_off_reason,
            evidence={"focus_kind": _off_kind, "recovered": False},
        )
        host.review_debug.record_event(
            "off_app_click", node=current_id, elem=elem.name,
            recovered=bool(relaunched), kind=_off_kind,
            reason=_off_reason)
        off_app_streak += 1
        host.graph.save(host.graph_save_path)
        if _is_stateful_action:
            host.graph.stop_reason = "state_restore_failed"
            logger.error("stateful click left the target app; mutation "
                         "outcome is unknown, stopping fail-closed")
            return done(StageDirective.STOP)
        return done(StageDirective.CONTINUE)
    off_app_streak = 0
    if relaunched:
        _off_kind = host._last_off_app_kind or "unknown"
        _off_reason = host._last_off_app_reason or "left target app"
        _terminal_outcome = host._terminal_off_app_outcome(_off_kind)
        if _terminal_outcome:
            host._record_abnormal_button(
                current_id, elem, _terminal_outcome, _off_reason, action)
        _relaunch_source_id = current_id
        current_id, current_path, current_hints, _landed_is_new = \
            host._register_landed(obs, parent_id=current_id)
        if current_id is None:
            _update_event(
                outcome="state_restore_failed",
                detail="relaunch landing did not match a persisted state",
                evidence={"focus_kind": _off_kind, "recovered": True},
            )
            return done(StageDirective.STOP)
        _relaunch_landed_id = current_id
        _relaunch_evidence = {
            **_stateful_evidence,
            "focus_kind": _off_kind,
            "recovered": True,
        }
        _stateful_relaunch_status = "not_stateful"
        if _is_stateful_action:
            _before_value = str(
                elem.state_value or "unknown").strip().lower()
            _after_value = str(host._state_value_on_state(
                current_id, elem.state_key) or "unknown").strip().lower()
            _known_values = {"off", "on"}
            if (_before_value in _known_values
                    and _after_value in _known_values):
                _stateful_relaunch_status = (
                    "unchanged" if _before_value == _after_value
                    else "changed")
            else:
                _stateful_relaunch_status = "unknown"
            _relaunch_evidence.update({
                "after_value": _after_value,
                "registered_target": current_id,
                "mutation_status": _stateful_relaunch_status,
            })
            if (_stateful_relaunch_status == "unchanged"
                    and _landed_is_new
                    and host._stateful_landing_equivalent(
                        _relaunch_source_id,
                        _relaunch_landed_id,
                        state_key=elem.state_key,
                        before_value=_before_value,
                        after_value=_after_value,
                    )
                    and host._discard_uncommitted_equivalent_state(
                        _relaunch_landed_id,
                        _relaunch_source_id,
                        reason="stateful relaunch preserved page and facts",
                    )):
                current_id = _relaunch_source_id
                source_data = host._state_data.get(current_id) or {}
                current_path = list(source_data.get("path") or [])
                current_hints = list(
                    source_data.get("replay_hints") or [])
                _relaunch_evidence.update({
                    "registered_target": current_id,
                    "equivalent_provisional_state_discarded": True,
                })
        _update_event(
            target=current_id,
            outcome=(_terminal_outcome or _off_kind),
            detail=_off_reason,
            evidence=_relaunch_evidence,
        )
        host.graph.save(host.graph_save_path)
        if _is_stateful_action:
            host._stateful_inflight = None
            if _stateful_relaunch_status == "unchanged":
                logger.warning(
                    "stateful click crashed/relaunched the app but the "
                    "structured value remained %s; retiring the control "
                    "as %s without opening a mutation",
                    _relaunch_evidence.get("after_value"),
                    _terminal_outcome or _off_kind)
                return done(StageDirective.CONTINUE)
            host._active_state_mutation = {
                "mutation_id": _mutation_id,
                "source_state": _relaunch_source_id,
                "mutated_state": current_id,
                "state_key": elem.state_key,
                "before_value": elem.state_value,
                "after_value": _relaunch_evidence.get(
                    "after_value", "unknown"),
            }
            host.graph.stop_reason = "state_restore_failed"
            logger.error(
                "stateful click required app relaunch and the structured "
                "mutation status is %s; stopping fail-closed",
                _stateful_relaunch_status)
            return done(StageDirective.STOP)
        return done(StageDirective.CONTINUE)
    return done(StageDirective.LANDING)
