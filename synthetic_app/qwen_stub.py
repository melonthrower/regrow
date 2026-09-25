"""Offline legacy response adapter for reusing the current Qwen parser.

This does not inspect screenshots and is not a traversal agent.  Tests select a
known fixture observation explicitly, while production traversal continues to
call the real Qwen model with the unchanged semantic-inventory prompt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


class QwenFixtureStub:
    """Return one selected oracle response through the GUIGenAgent tuple API."""

    def __init__(self, state_key: str, responses_path: Path | None = None):
        path = responses_path or ROOT / "qwen_responses.json"
        self.responses = json.loads(path.read_text(encoding="utf-8"))
        self.set_state(state_key)

    def set_state(self, state_key: str) -> None:
        if state_key not in self.responses:
            known = ", ".join(sorted(self.responses))
            raise KeyError(f"unknown fixture state {state_key!r}; choose one of: {known}")
        self.state_key = state_key

    def _reply(self) -> tuple[str, None, None, int]:
        return (
            json.dumps(self.responses[self.state_key], ensure_ascii=False),
            None,
            None,
            0,
        )

    def predict_mm(self, _text_prompt: str, _images: list[Any]):
        return self._reply()

    def predict_mm_with_policy(
        self,
        _text_prompt: str,
        _images: list[Any],
        max_attempts: int,
        timeout_seconds: float | None = None,
    ):
        del max_attempts, timeout_seconds
        return self._reply()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print one Qwen-shaped fixture response")
    parser.add_argument("state_key", nargs="?", default="home.default")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    stub = QwenFixtureStub(args.state_key)
    if args.list:
        print("\n".join(sorted(stub.responses)))
    else:
        print(json.dumps(stub.responses[stub.state_key], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
