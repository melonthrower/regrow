"""In-process entry for an optional fixed-target Mingle traversal probe."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _target_matches(desired: str, candidate: str) -> bool:
    desired_norm = " ".join(str(desired).casefold().split())
    candidate_norm = " ".join(str(candidate).casefold().split())
    return bool(desired_norm and desired_norm in candidate_norm)


def install_forced_explorer_path() -> None:
    raw_targets = os.environ.get("GUIWALK_PROBE_FORCED_TARGETS", "")
    if not raw_targets:
        return
    try:
        targets = [str(value) for value in json.loads(raw_targets) if str(value)]
    except (TypeError, ValueError, json.JSONDecodeError):
        targets = []
    if not targets:
        return

    from gui_rewalk.src.core.visual_traversal import agents
    from gui_rewalk.src.core.visual_traversal.action_space import (
        is_android,
        normalize_native_action,
    )

    original = agents.ExplorerAgent

    class ForcedPathExplorer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._probe_target_index = 0

        def choose(self, screenshot_bytes, context, *, platform):
            pending = [
                item
                for item in context.get("pending_buttons") or []
                if isinstance(item, dict)
            ]
            if self._probe_target_index >= len(targets):
                return {
                    "covered": [],
                    "semantic_only": [
                        {
                            "choice_id": str(item.get("choice_id") or ""),
                            "reason": "probe forced path is complete",
                        }
                        for item in pending
                    ],
                    "next_action": None,
                }
            desired = targets[self._probe_target_index]
            match = next(
                (
                    item
                    for item in pending
                    if _target_matches(desired, str(item.get("name") or ""))
                ),
                None,
            )
            if match is None:
                return {
                    "covered": [],
                    "semantic_only": [],
                    "next_action": None,
                }

            # Keep the real Explorer call in the ledger, but hold the action path
            # constant so the policy A/B differs only after target selection.
            super().choose(screenshot_bytes, context, platform=platform)
            raw_action = {"action_type": "click" if is_android(platform) else "CLICK"}
            action, error = normalize_native_action(raw_action, platform=platform)
            if error or action is None:
                return {}
            self._probe_target_index += 1
            return {
                "covered": [],
                "semantic_only": [],
                "next_action": {
                    "action": action,
                    "choice_id": str(match.get("choice_id") or ""),
                    "reason": f"probe forced target {desired}",
                },
            }

    agents.ExplorerAgent = ForcedPathExplorer


def main() -> int:
    install_forced_explorer_path()
    from gui_rewalk import run_visual_traversal

    return run_visual_traversal.main()


if __name__ == "__main__":
    raise SystemExit(main())
