"""Read-only, fail-closed matching of a live frame to a known Page State."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)
_REPLY_KEYS = {"status", "state_ref", "reason"}


def _vlm_json(vlm: Any, prompt: str, images: Sequence[Any]) -> Mapping[str, Any]:
    raw = vlm.predict_mm(prompt, list(images))
    if isinstance(raw, tuple):
        raw = raw[0] if raw else ""
    if isinstance(raw, Mapping):
        return raw
    text = str(raw or "").strip()
    match = _JSON_OBJECT.search(text)
    parsed = json.loads(match.group(0) if match else text)
    if not isinstance(parsed, Mapping):
        raise ValueError("VLM output is not a JSON object")
    return parsed


def _bytes(value: Any) -> Optional[bytes]:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return None


def _missing_screenshot(value: Any) -> bool:
    if value is None:
        return True
    content = _bytes(value)
    if content is not None:
        return not content
    return isinstance(value, str) and not value


class KnownPageStateLocator:
    """Return one exact known State ref, or ``None`` without mutating inputs."""

    def __init__(self, vlm: Any):
        self.vlm = vlm
        self.last_reason = ""

    def locate(
        self,
        live_screenshot: Any,
        candidates: Sequence[Mapping[str, Any]],
        *,
        page_ref: str,
    ) -> Optional[str]:
        self.last_reason = ""
        try:
            if _missing_screenshot(live_screenshot):
                return self._unresolved("live screenshot is missing")
            scoped = [
                candidate
                for candidate in candidates
                if isinstance(candidate, Mapping)
                and candidate.get("page_ref") == page_ref
            ]
            if not page_ref or not scoped:
                return self._unresolved("no candidates for the requested Page")

            state_refs = []
            screenshots = []
            cards = []
            for candidate in scoped:
                state_ref = candidate.get("state_ref")
                screenshot = candidate.get("screenshot")
                if (
                    not isinstance(state_ref, str)
                    or not state_ref
                    or _missing_screenshot(screenshot)
                ):
                    return self._unresolved("candidate State evidence is incomplete")
                regions = candidate.get("regions")
                if not isinstance(regions, list):
                    return self._unresolved("candidate State evidence is incomplete")
                state_refs.append(state_ref)
                screenshots.append(screenshot)
                cards.append({
                    "state_ref": state_ref,
                    "page_ref": page_ref,
                    "state_name": str(candidate.get("state_name") or ""),
                    "state_summary": str(candidate.get("state_summary") or ""),
                    "regions": regions,
                })

            live_bytes = _bytes(live_screenshot)
            exact = [
                state_ref
                for state_ref, screenshot in zip(state_refs, screenshots)
                if live_bytes is not None and _bytes(screenshot) == live_bytes
            ]
            if len(exact) == 1:
                self.last_reason = "unique byte-identical known State"
                return exact[0]
            if len(exact) > 1:
                return self._unresolved("multiple byte-identical candidate States")

            prompt = (
                "Match image 1, the current live frame, to exactly one already "
                "known State on the requested Page. Remaining images correspond "
                "to the candidate cards in order. Use the State summary, stable "
                "Region/Operation structure, and full screenshots. Do not create "
                "or merge a State. Return exactly either "
                '{"status":"known","state_ref":"...","reason":"..."} or '
                '{"status":"unresolved","state_ref":"","reason":"..."}.\n'
                f"Requested page_ref: {json.dumps(page_ref, ensure_ascii=False)}\n"
                "Candidate State cards: "
                f"{json.dumps(cards, ensure_ascii=False)}"
            )
            result = _vlm_json(
                self.vlm, prompt, [live_screenshot, *screenshots])
            if set(result) != _REPLY_KEYS:
                return self._unresolved("malformed State locator reply")
            status = result.get("status")
            state_ref = result.get("state_ref")
            reason = result.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                return self._unresolved("malformed State locator reply")
            self.last_reason = reason.strip()
            if status == "unresolved" and state_ref == "":
                return None
            if (
                status == "known"
                and isinstance(state_ref, str)
                and state_ref in state_refs
            ):
                return state_ref
            return self._unresolved("State locator did not select a valid candidate")
        except Exception as exc:
            return self._unresolved(
                f"State locator unavailable: {type(exc).__name__}")

    def _unresolved(self, reason: str) -> None:
        self.last_reason = reason
        return None


__all__ = ["KnownPageStateLocator"]
