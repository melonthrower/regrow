"""Startup and resume adoption for traversal runs."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .contracts import PerceptionUnavailable, TraversalRuntimeHost

logger = logging.getLogger(__name__)

@dataclass
class BootstrapOutcome:
    terminal: object | None
    state_id: str = ""
    path: List[Dict[str, object]] = None
    replay_hints: List[Optional[Dict[str, object]]] = None
    observation: Dict[str, object] = None

def bootstrap_traversal(host: TraversalRuntimeHost, initial_obs):
    for name, default in (
        ("_active_state_mutation", None), ("_stateful_inflight", None),
        ("_stateful_probe_count", 0), ("_stateful_probe_sources", set()),
        ("_stateful_probe_limit", 0), ("_stateful_per_node_limit", 0),
        ("_stateful_budget_blocked", False),
    ):
        if not hasattr(host, name):
            setattr(host, name, default)
    path = []
    initial_obs, _, on_app = host._ensure_on_app(initial_obs)
    if not on_app:
        logger.error("could not reach target app %r on startup", host.app_name)
        host.graph.save(host.graph_save_path)
        try:
            host.vlm_ledger.save()
        except Exception:
            pass
        return BootstrapOutcome(host.graph)
    if host._settle_enabled:
        initial_obs = host._settle(initial_obs)
    host._refresh_window_crop()
    resuming = bool(host.graph.graph.number_of_nodes())
    if host._preserve_initial_surface:
        logger.info("startup: preserving caller-selected initial surface")
        host.review_debug.record_agent(
            "startup_policy", step=host._action_count,
            verdict="preserve_initial_surface",
            reason="caller selected the current live surface as traversal root",
        )
    elif not resuming:
        initial_obs = host._dismiss_interruptions(initial_obs, force_first=True)
        if getattr(host, "_startup_surface_unresolved", False):
            logger.error(
                "startup surface is still a transient/interruption; "
                "refusing to register it as an application state"
            )
            host.graph.stop_reason = "startup_interruption_unresolved"
            host.graph.save(host.graph_save_path)
            try:
                host.vlm_ledger.save()
            except Exception:
                pass
            host.review_debug.close()
            return BootstrapOutcome(host.graph)
    try:
        if resuming:
            current_id, _, _, _ = host._register_landed(initial_obs)
            if current_id is None:
                logger.error("resume landing does not match a persisted state")
                host.graph.save(host.graph_save_path)
                try:
                    host.vlm_ledger.save()
                except Exception:
                    pass
                host.review_debug.close()
                return BootstrapOutcome(host.graph)
            host.graph.stop_reason = "incomplete"
        else:
            current_id, _ = host._register(initial_obs, path)
    except PerceptionUnavailable as exc:
        logger.error("startup state unavailable; preserving graph: %s", exc)
        host.graph.stop_reason = (
            "state_restore_failed" if resuming else "perception_unavailable"
        )
        host.graph.save(host.graph_save_path)
        try:
            host.vlm_ledger.save()
        except Exception:
            pass
        host.review_debug.close()
        return BootstrapOutcome(host.graph)
    return BootstrapOutcome(
        None, current_id, list(host._state_data[current_id]["path"]),
        list(host._state_data[current_id].get("replay_hints", [])), initial_obs,
    )
