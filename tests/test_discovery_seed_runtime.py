"""Regression: domain seed planning is retired from traversal, retained in M13.

The historical test exercised ``empty alarm -> hidden prerequisite recipe`` and
required the engine to collapse several GUI primitives into one SEQUENCE edge.
That is now intentionally the wrong contract: Create/Add is an ordinary frontier
click and every observed landing remains a variant execution node.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal import visual_engine  # noqa: E402
from gui_rewalk.src.core.visual_traversal.runtime.runner import run_traversal  # noqa: E402
from gui_rewalk.src.core.visual_traversal.runtime.scheduling import plan_candidate  # noqa: E402
from gui_rewalk.src.core.visual_traversal.visual_engine import (  # noqa: E402
    VisualTraversalEngine,
)


def test_discovery_seed_is_retired_from_traversal_but_retained_in_m13() -> None:
    traversal_cli = (ROOT / "gui_rewalk" / "run_visual_traversal.py").read_text(
        encoding="utf-8")
    assert "--no_discovery_prerequisites" not in traversal_cli
    assert "discovery_precondition_factory" not in traversal_cli

    run_source = inspect.getsource(run_traversal) + inspect.getsource(plan_candidate)
    assert "_run_discovery_seed_setup(" not in run_source
    assert "is_seed = False" in run_source
    assert "discovery_precondition_resolver" not in inspect.signature(
        VisualTraversalEngine).parameters
    assert "cleanup_discovery_resources" not in inspect.signature(
        VisualTraversalEngine).parameters
    assert "discovery_precondition_factory" not in inspect.signature(
        visual_engine.run).parameters
    assert not hasattr(VisualTraversalEngine, "_run_discovery_seed_setup")
    assert not hasattr(VisualTraversalEngine, "_cleanup_owned_discovery_resources")

    # Prerequisite ownership remains available to the later collection/planning
    # stage; retiring traversal seed must not delete M13's explicit resolver.
    collection_cli = (ROOT / "gui_rewalk" / "run_visual_collection.py").read_text(
        encoding="utf-8")
    assert "prerequisite" in collection_cli.casefold()



def main() -> int:
    test_discovery_seed_is_retired_from_traversal_but_retained_in_m13()
    print("PASS discovery seed retired from traversal; prerequisite planning stays in M13")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
