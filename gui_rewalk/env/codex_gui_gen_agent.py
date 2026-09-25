"""Codex CLI screenshot transport for existing visual collection consumers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Optional, Sequence

from gui_rewalk.env.gui_gen_agent import array_to_jpeg_bytes
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_agent import (
    CodexAutonomousAgent,
)


logger = logging.getLogger("desktopenv.agent")


class CodexGUIGenAgent:
    """Expose the existing ``predict_mm`` contract through ``codex exec``."""

    def __init__(
        self,
        *,
        model_version: str,
        output_root: str,
        action_space: str = "gen_data",
        observation_type: str = "screenshot",
        timeout: int = 300,
        runner: Callable[..., Any] = subprocess.run,
        command: Optional[Sequence[str]] = None,
        **_: Any,
    ) -> None:
        if observation_type != "screenshot":
            raise ValueError(
                "CodexGUIGenAgent supports screenshot observations only")
        self.model = "Codex"
        self.model_version = str(model_version or "").strip()
        if not self.model_version:
            raise ValueError("Codex model_version cannot be empty")
        self.output_root = Path(output_root).expanduser().resolve()
        self.temp_root = self.output_root / "_codex_gui_tmp"
        self.debug_path = self.output_root / "_codex_gui_debug.jsonl"
        self.action_space = action_space
        self.observation_type = observation_type
        self.enable_thinking = False
        self.timeout = int(timeout)
        self.runner = runner
        self.command = list(command) if command is not None else None
        self.last_prompt_tokens_details: dict[str, int] = {}
        self.thoughts: list[Any] = []
        self.actions: list[Any] = []
        self.observations: list[Any] = []

    def _command(self) -> list[str]:
        return list(self.command or CodexAutonomousAgent._command())

    def _record(self, payload: dict[str, Any]) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)
        with self.debug_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _invoke(
        self,
        prompt: str,
        images: Sequence[Any],
        *,
        system_prompt: str = "",
        timeout_seconds: Optional[float] = None,
    ) -> str:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="codex_collection_", dir=self.temp_root,
        ) as temporary:
            temporary_path = Path(temporary)
            image_paths = []
            for index, image in enumerate(images, 1):
                image_path = temporary_path / f"image_{index}.jpg"
                image_path.write_bytes(array_to_jpeg_bytes(image))
                image_paths.append(image_path)
            output_path = temporary_path / "response.txt"
            command = self._command() + [
                "exec", "-m", self.model_version,
                "--sandbox", "read-only",
                "--skip-git-repo-check", "--json",
            ]
            for image_path in image_paths:
                command.extend(["-i", str(image_path)])
            command.extend(["-o", str(output_path), "-"])
            request_prompt = (
                str(system_prompt or "")
                + ("\n\n" if system_prompt else "")
                + str(prompt or "")
            )
            completed = self.runner(
                command,
                cwd=temporary,
                input=request_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=float(timeout_seconds or self.timeout),
                check=False,
            )
            if completed.returncode != 0:
                detail = str(
                    completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"codex CLI exited {completed.returncode}: {detail[:500]}")
            try:
                raw = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"codex CLI did not write a final response: {exc}") from exc
        self._record({
            "backend": "codex_cli",
            "model": self.model_version,
            "prompt": request_prompt,
            "image_count": len(images),
            "raw_response": raw,
        })
        return raw

    def predict_mm(self, text_prompt: str, images: list[Any]):
        raw = self._invoke(text_prompt, images)
        return raw, None, None, 1

    def predict_mm_with_policy(
        self,
        text_prompt: str,
        images: list[Any],
        max_attempts: int,
        timeout_seconds: Optional[float] = None,
        system_prompt: str = "",
    ):
        del max_attempts
        raw = self._invoke(
            text_prompt,
            images,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
        )
        return raw, None, None, 1

    @staticmethod
    def parse_json(response: Any, fields: Optional[list[str]] = None):
        if isinstance(response, tuple):
            response = response[0] if response else ""
        text = str(response or "")
        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw = fenced.group(1) if fenced else None
        if raw is None:
            start, end = text.find("{"), text.rfind("}")
            raw = text[start:end + 1] if start >= 0 and end > start else ""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Codex JSON response: %.300s", text)
            return None
        if fields:
            return {key: data.get(key, "") for key in fields}
        return data

    def reset(self, replacement_logger=None) -> None:
        global logger
        if replacement_logger is not None:
            logger = replacement_logger
        self.thoughts = []
        self.actions = []
        self.observations = []


__all__ = ["CodexGUIGenAgent"]
