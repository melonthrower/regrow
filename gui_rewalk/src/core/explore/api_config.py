"""Local configuration for the OpenAI-compatible explore backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml


_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class ExploreAPIConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    reasoning_effort: str = "medium"
    timeout_seconds: int = 300


def local_explore_api_config_path() -> Path:
    return Path(__file__).resolve().parents[4] / ".guiwalk.local.yaml"


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"explore_api.{field_name} must be a non-empty string")
    return value.strip()


def _https_base_url(value: Any) -> str:
    base_url = _required_text(value, "base_url").rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme.casefold() != "https" or not parsed.netloc:
        raise ValueError("explore_api.base_url must be an HTTPS URL")
    return base_url


def _reasoning_effort(value: Any) -> str:
    effort = _required_text(value or "medium", "reasoning_effort").casefold()
    if effort not in _REASONING_EFFORTS:
        raise ValueError(
            "explore_api.reasoning_effort must be one of: "
            + ", ".join(sorted(_REASONING_EFFORTS))
        )
    return effort


def _timeout_seconds(value: Any) -> int:
    if value is None:
        return 300
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("explore_api.timeout_seconds must be a positive integer")
    return value


def load_explore_api_config(path: Path | str) -> ExploreAPIConfig:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"explore API config is unavailable: {config_path}"
        ) from exc
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("explore API config is not valid YAML") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("explore API config root must be a mapping")
    if isinstance(payload.get("version"), bool) or payload.get("version") != 1:
        raise ValueError("explore API config version must be 1")
    section = payload.get("explore_api")
    if not isinstance(section, Mapping):
        raise ValueError("explore_api must be a mapping")
    return ExploreAPIConfig(
        base_url=_https_base_url(section.get("base_url")),
        api_key=_required_text(section.get("api_key"), "api_key"),
        model=_required_text(section.get("model"), "model"),
        reasoning_effort=_reasoning_effort(section.get("reasoning_effort")),
        timeout_seconds=_timeout_seconds(section.get("timeout_seconds")),
    )


__all__ = [
    "ExploreAPIConfig",
    "load_explore_api_config",
    "local_explore_api_config_path",
]
