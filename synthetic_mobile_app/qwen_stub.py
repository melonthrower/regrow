"""Offline legacy response stub accepted by the current Qwen parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


class QwenMobileFixtureStub:
    def __init__(self, state_key: str, responses_path: Path | None = None):
        path = responses_path or ROOT / "qwen_responses.json"
        self.responses = json.loads(path.read_text(encoding="utf-8"))
        self.set_state(state_key)

    def set_state(self, state_key: str) -> None:
        if state_key not in self.responses:
            raise KeyError(f"unknown Mingle fixture state {state_key!r}")
        self.state_key = state_key

    def _reply(self) -> tuple[str, None, None, int]:
        return json.dumps(self.responses[self.state_key], ensure_ascii=False), None, None, 0

    def predict_mm(self, _text_prompt: str, _images: list[Any]):
        return self._reply()

    def predict_mm_with_policy(
        self, _text_prompt: str, _images: list[Any], max_attempts: int,
        timeout_seconds: float | None = None,
    ):
        del max_attempts, timeout_seconds
        return self._reply()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_key", nargs="?", default="inbox.top")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    stub = QwenMobileFixtureStub(args.state_key)
    print("\n".join(sorted(stub.responses)) if args.list else json.dumps(
        stub.responses[stub.state_key], ensure_ascii=False, indent=2
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
