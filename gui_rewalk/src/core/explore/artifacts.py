"""Filesystem evidence writer for the modular exploration kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import re

from .ledger import ExplorationLedger


class ArtifactStore:
    def __init__(
        self,
        output_root: str,
        *,
        checkpoint_callback: Optional[Callable[[ExplorationLedger], None]] = None,
    ) -> None:
        self.root = Path(output_root)
        self.frames = self.root / "screenshots"
        self.attempts = self.root / "action_attempts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.frames.mkdir(parents=True, exist_ok=True)
        self.attempts.mkdir(parents=True, exist_ok=True)
        self.frame_count = max((
            int(match.group(1))
            for path in self.frames.glob("frame_*.png")
            if (match := re.fullmatch(r"frame_(\d+)\.png", path.name))
        ), default=0)
        self.checkpoint_callback = checkpoint_callback
        self._last_checkpoint_callback_key: str | None = None

    def save_frame(self, screenshot: bytes) -> str:
        self.frame_count += 1
        relative = Path("screenshots") / f"frame_{self.frame_count:05d}.png"
        (self.root / relative).write_bytes(screenshot)
        return relative.as_posix()

    def save_attempt_before(self, attempt_id: str, screenshot: bytes) -> str:
        directory = self.attempts / attempt_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "before.png"
        path.write_bytes(screenshot)
        return path.relative_to(self.root).as_posix()

    def save_attempt_after(self, attempt_id: str, screenshot: bytes) -> str:
        directory = self.attempts / attempt_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "after.png"
        path.write_bytes(screenshot)
        return path.relative_to(self.root).as_posix()

    def save_attempt_anchor(self, attempt_id: str, anchor: bytes) -> str:
        directory = self.attempts / attempt_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "anchor.png"
        path.write_bytes(anchor)
        return path.relative_to(self.root).as_posix()

    def read(self, relative_path: str) -> bytes:
        return (self.root / relative_path).read_bytes()

    def checkpoint(self, ledger: ExplorationLedger) -> None:
        ledger.save(self.root / "exploration_ledger.json")
        with (self.root / "events.jsonl").open("w", encoding="utf-8") as stream:
            for event in ledger.events:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        callback_key = _settled_checkpoint_key(ledger)
        if (
            self.checkpoint_callback is not None
            and callback_key is not None
            and callback_key != self._last_checkpoint_callback_key
        ):
            self.checkpoint_callback(ledger)
            self._last_checkpoint_callback_key = callback_key

    def write_completion(self, payload: Dict[str, Any]) -> str:
        path = self.root / "modular_completion.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def archive_completion(self) -> str:
        path = self.root / "modular_completion.json"
        if not path.is_file():
            return ""
        index = 1
        while True:
            archived = self.root / f"modular_completion.pre_resume_{index:03d}.json"
            if not archived.exists():
                path.replace(archived)
                return str(archived)
            index += 1


__all__ = ["ArtifactStore"]


def _settled_checkpoint_key(ledger: ExplorationLedger) -> str | None:
    """Allow one initial pair and then only newly settled real attempts."""
    snapshot = getattr(ledger, "snapshot", None)
    if not callable(snapshot):
        return "legacy"
    attempts = snapshot().get("attempts")
    if not isinstance(attempts, list):
        return None
    if not attempts:
        return "initial"
    last_attempt = attempts[-1]
    if not isinstance(last_attempt, dict):
        return None
    if any(not str(item.get("outcome") or "") for item in attempts if isinstance(item, dict)):
        return None
    attempt_id = str(last_attempt.get("attempt_id") or "")
    return "attempt:" + attempt_id if attempt_id else None
