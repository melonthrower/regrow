from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import SeedManifest
from .manifest_v1 import canonical_manifest_digest


DEFAULT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "guitraverse_seed_reports"


def _report_path(root: Path, profile: str, command: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = root / profile
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{timestamp}_{command}.json"


def write_v1_report(
    root: Path,
    manifest: SeedManifest,
    command: str,
    result: Mapping[str, Any],
    history: Sequence[Sequence[str]] = (),
) -> Path:
    payload = {
        "schema": "guitraverse.mobile_seed.report.v1",
        "command": command,
        "profile": manifest.profile,
        "manifest_digest": canonical_manifest_digest(manifest),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "result": result,
        "adb_commands": [list(item[3:]) for item in history],
    }
    path = _report_path(root, manifest.profile, command)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


_write_report = write_v1_report
