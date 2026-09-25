"""Final persistence and stop-reason handling for traversal runs."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def finish_traversal(host):
    if getattr(host.graph, "stop_reason", "incomplete") == "incomplete":
        host.graph.stop_reason = "max_actions"
    if host._active_state_mutation or host._stateful_inflight:
        logger.error(
            "traversal ended with an un-restored stateful mutation: %s",
            (host._active_state_mutation or host._stateful_inflight or {}).get(
                "mutation_id", "?"),
        )
        host.graph.stop_reason = "state_restore_failed"
    host.graph.save(host.graph_save_path)
    try:
        host.vlm_ledger.save()
        snapshot = host.vlm_ledger.snapshot()
        logger.info(
            "VLM ledger: %d logical calls, %d transport attempts, "
            "%d cache hits, %.1fs model latency -> %s",
            snapshot["logical_calls"], snapshot["transport_attempts"],
            snapshot["cache_hits"], snapshot["latency_seconds"],
            host.vlm_ledger.output_path,
        )
    except Exception as exc:
        logger.warning("vlm ledger final save failed (%s)", exc)
    logger.info(
        "visual traversal done: %d states, %d actions (stop=%s)",
        host.graph.graph.number_of_nodes(), host._action_count,
        host.graph.stop_reason,
    )
    host.review_debug.close()
    return host.graph
