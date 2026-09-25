"""Thin coordinator for the staged visual traversal lifecycle."""
from __future__ import annotations

import logging

from .bootstrap import bootstrap_traversal
from .completion import finish_traversal
from .contracts import RunCursor, StageDirective, TraversalRuntimeHost
from .execution import execute_candidate
from .element_task import active_element_task, record_element_task_action
from .landing import process_landing
from .recovery import recover_attempt
from .scheduling import (
    available_unvisited_candidates, plan_candidate,
    prepare_current_scroll_audit, schedule_frontier,
)

logger = logging.getLogger(__name__)

def run_traversal(host: TraversalRuntimeHost, initial_obs):
    bootstrap = bootstrap_traversal(host, initial_obs)
    if bootstrap.terminal is not None:
        return bootstrap.terminal
    cursor = RunCursor(
        bootstrap.state_id, bootstrap.observation,
        list(bootstrap.path or []), list(bootstrap.replay_hints or []), 0,
    )

    while host._action_count < host.max_actions:
        host._refresh_window_crop()
        if cursor.off_app_streak >= host.MAX_CONSECUTIVE_OFF_APP:
            logger.error(
                "off-app %d times in a row for %r; stopping traversal",
                cursor.off_app_streak, host.app_name,
            )
            host.graph.stop_reason = "off_app"
            break
        if (not host._active_state_mutation
                and host.graph.graph.number_of_nodes() >= host.max_states
                and not host._next_unvisited(cursor.state_id)):
            logger.info("reached max_states with current state exhausted")
            host.graph.stop_reason = "max_states"
            break

        node_count = host.graph.graph.number_of_nodes()
        if node_count > host._last_node_count:
            host._last_node_count = node_count
            host._moves_without_new = 0
            # New graph evidence can make an earlier failed route viable.
            host._route_blocked_targets.clear()
            host._route_target_failure_counts.clear()

        state_id, path, hints = host._reconcile_position(
            cursor.state_id, cursor.observation, cursor.path,
            cursor.replay_hints,
        )
        cursor = RunCursor(
            state_id, cursor.observation, list(path), list(hints),
            cursor.off_app_streak,
        )
        live_sync = getattr(host.graph, "_live_sync", None)
        if callable(live_sync):
            # Scheduling must never read a different Page/Region/frontier view
            # from the one that would be persisted or restored.
            live_sync(host.graph)
        host._log_progress()
        task = active_element_task(host)
        if task is None:
            scroll_audit = prepare_current_scroll_audit(
                host, cursor.state_id, cursor.observation, cursor.path,
                cursor.replay_hints, cursor.off_app_streak,
            )
            if scroll_audit is not None:
                cursor = RunCursor(
                    scroll_audit.state_id, scroll_audit.observation,
                    scroll_audit.path, scroll_audit.replay_hints,
                    scroll_audit.off_app_streak,
                )
                if scroll_audit.stop:
                    break
                continue
        from .region_observation import observe_next_region, pending_region_ids
        if task is None and pending_region_ids(host, cursor.state_id):
            # Qwen should choose from the active surface as a whole.  Finish
            # observing its registered Regions before asking for a target
            # instead of letting the framework expose one Region at a time.
            observe_next_region(host, cursor.state_id, cursor.observation)
            continue
        candidates = available_unvisited_candidates(host, cursor.state_id)
        if not candidates and task is not None and task.get("goal_element"):
            # An active target Agent may be on a newly reached page whose
            # Regions are intentionally still pending.  Keep the Agent in
            # control so it can call inspect_region or act on the screenshot.
            candidates = [task["goal_element"]]
        if not candidates:
            scheduled = schedule_frontier(
                host, cursor.state_id, cursor.observation, cursor.path,
                cursor.replay_hints, cursor.off_app_streak,
            )
            cursor = RunCursor(
                scheduled.state_id, scheduled.observation, scheduled.path,
                scheduled.replay_hints, scheduled.off_app_streak,
            )
            if scheduled.stop:
                break
            continue

        planned = plan_candidate(host, cursor, candidates)
        if planned.directive is StageDirective.STOP:
            break
        if planned.directive is not StageDirective.EXECUTION:
            continue
        if planned.candidate is None:
            continue

        source_cursor = cursor
        executed = execute_candidate(host, cursor, planned.candidate)
        cursor = executed.cursor
        if executed.directive is StageDirective.STOP:
            record_element_task_action(
                host, planned.candidate, source_cursor, cursor,
                executed.attempt, stage="execution_stopped")
            break
        if executed.attempt is None:
            record_element_task_action(
                host, planned.candidate, source_cursor, cursor,
                stage="execution_not_completed")
            continue

        recovered = recover_attempt(host, cursor, executed.attempt)
        cursor = recovered.cursor
        if recovered.directive is StageDirective.STOP:
            record_element_task_action(
                host, planned.candidate, source_cursor, cursor,
                executed.attempt, stage="recovery_stopped")
            break
        if recovered.directive is StageDirective.CONTINUE:
            record_element_task_action(
                host, planned.candidate, source_cursor, cursor,
                executed.attempt, stage="recovered_without_landing")
            continue

        landed = process_landing(host, cursor, executed.attempt)
        cursor = landed.cursor
        record_element_task_action(
            host, planned.candidate, source_cursor, cursor,
            executed.attempt, stage="landing_processed")
        if landed.directive is StageDirective.STOP:
            break

    return finish_traversal(host)
