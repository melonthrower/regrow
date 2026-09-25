"""Run-owned environment/ledger checkpoint pairs for Android exploration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping


SCHEMA = "guitraverse.run_checkpoint.v1"
_RUN_ID = re.compile(r"[^A-Za-z0-9_.-]+")


class RunCheckpointStore:
    """Keep only complete checkpoint pairs; never synthesize a mixed resume."""

    def __init__(self, root: str | Path, *, run_id: str, keep: int = 2) -> None:
        if not isinstance(keep, int) or keep not in {1, 2}:
            raise ValueError("run checkpoints retain one or two pairs")
        cleaned = _RUN_ID.sub("_", str(run_id or "")).strip("._")
        if not cleaned:
            raise ValueError("run checkpoint needs a safe run id")
        self.root = Path(root)
        self.directory = self.root / "checkpoints"
        self.run_id = cleaned
        self.keep = keep

    def save(
        self,
        ledger: Mapping[str, Any],
        *,
        app_id: str,
        package_versions: Mapping[str, str],
        seed_plan_digest: str,
        save_environment: Callable[[str], None],
        delete_environment: Callable[[str], None],
    ) -> dict[str, Any] | None:
        """Save one quiescent environment/ledger pair, or skip a pending action."""
        payload = _plain(ledger)
        last_attempt = _last_settled_attempt(payload)
        if last_attempt is None:
            return None
        if not isinstance(app_id, str) or not app_id:
            raise ValueError("checkpoint app_id must be non-empty")
        versions = {
            str(package): str(version)
            for package, version in package_versions.items()
            if str(package) and str(version)
        }
        if not versions:
            raise ValueError("checkpoint package_versions must be non-empty")
        _digest_text(seed_plan_digest, "seed_plan_digest")

        self.directory.mkdir(parents=True, exist_ok=True)
        generation = self._next_generation()
        environment_snapshot = f"guitraverse_run_{self.run_id}_{generation:06d}"
        ledger_path = self.directory / f"ledger_{generation:06d}.json"
        checkpoint_path = self.directory / f"checkpoint_{generation:06d}.json"
        ledger_digest = _digest(payload)
        record = {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "generation": generation,
            "environment_snapshot": environment_snapshot,
            "ledger_path": str(ledger_path.resolve()),
            "ledger_digest": ledger_digest,
            "last_settled_attempt": last_attempt,
            "app_id": app_id,
            "package_versions": versions,
            "seed_plan_digest": seed_plan_digest,
        }
        try:
            save_environment(environment_snapshot)
            _write_json(ledger_path, payload)
            _write_json(checkpoint_path, record)
        except Exception:
            try:
                delete_environment(environment_snapshot)
            except Exception:
                pass
            raise
        self._prune(delete_environment=delete_environment)
        return record

    def latest(
        self,
        *,
        environment_exists: Callable[[str], bool],
    ) -> dict[str, Any]:
        """Return the newest complete pair, ignoring torn or inconsistent files."""
        issues = []
        for path in reversed(sorted(self.directory.glob("checkpoint_*.json"))):
            try:
                record = _read_json(path)
                self._validate_record(record)
                ledger_path = Path(record["ledger_path"])
                ledger = _read_json(ledger_path)
                if _digest(ledger) != record["ledger_digest"]:
                    issues.append(f"{path.name}: ledger_digest 不匹配")
                    continue
                if _last_settled_attempt(ledger) != record["last_settled_attempt"]:
                    issues.append(f"{path.name}: last_settled_attempt 不匹配")
                    continue
                if not environment_exists(record["environment_snapshot"]):
                    issues.append(f"{path.name}: 环境快照 {record['environment_snapshot']} 不存在")
                    continue
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                issues.append(f"{path.name}: {type(exc).__name__}: {exc}")
                continue
            return record
        raise ValueError(
            "no complete matching run checkpoint pair exists；"
            + ("；".join(issues) if issues else f"{self.directory} 中没有 checkpoint 文件")
            + "。请恢复匹配的图与环境快照，不要单独修改摘要或伪造已结算动作。")

    def clear(self, *, delete_environment: Callable[[str], None]) -> None:
        """Remove retained run checkpoints after a fully completed exploration."""
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("checkpoint_*.json")):
            try:
                record = _read_json(path)
                self._validate_record(record)
                delete_environment(record["environment_snapshot"])
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            ledger_path = None
            try:
                ledger_path = Path(_read_json(path).get("ledger_path") or "")
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            path.unlink(missing_ok=True)
            if ledger_path is not None:
                ledger_path.unlink(missing_ok=True)

    def _next_generation(self) -> int:
        generations = []
        for path in self.directory.glob("checkpoint_*.json"):
            match = re.fullmatch(r"checkpoint_(\d{6})\.json", path.name)
            if match is not None:
                generations.append(int(match.group(1)))
        return max(generations, default=0) + 1

    def _prune(self, *, delete_environment: Callable[[str], None]) -> None:
        records = sorted(self.directory.glob("checkpoint_*.json"))
        for path in records[:-self.keep]:
            try:
                record = _read_json(path)
                self._validate_record(record)
                delete_environment(record["environment_snapshot"])
                Path(record["ledger_path"]).unlink(missing_ok=True)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            path.unlink(missing_ok=True)

    def _validate_record(self, record: Mapping[str, Any]) -> None:
        if set(record) != {
            "schema", "run_id", "generation", "environment_snapshot",
            "ledger_path", "ledger_digest", "last_settled_attempt", "app_id",
            "package_versions", "seed_plan_digest",
        }:
            raise ValueError("run checkpoint fields do not match schema v1")
        if record["schema"] != SCHEMA or record["run_id"] != self.run_id:
            raise ValueError(f"run checkpoint identity mismatch: expected schema={SCHEMA}, run_id={self.run_id}; received schema={record['schema']}, run_id={record['run_id']}；请选正确运行的存档。")
        if not isinstance(record["generation"], int) or record["generation"] < 1:
            raise ValueError(f"run checkpoint generation={record['generation']!r} is invalid；应为正整数，请恢复有效存档，不要手改代次。")
        for field in ("environment_snapshot", "ledger_path", "last_settled_attempt", "app_id"):
            if not isinstance(record[field], str) or not record[field]:
                raise ValueError(f"run checkpoint {field} is invalid")
        _digest_text(record["ledger_digest"], "ledger_digest")
        _digest_text(record["seed_plan_digest"], "seed_plan_digest")
        if not isinstance(record["package_versions"], Mapping) or not record["package_versions"]:
            raise ValueError("run checkpoint package_versions is invalid")


def _last_settled_attempt(ledger: Mapping[str, Any]) -> str | None:
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("checkpoint ledger attempts must be a list")
    last = ""
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ValueError("checkpoint ledger attempt is invalid")
        outcome = attempt.get("outcome")
        attempt_id = attempt.get("attempt_id")
        if not isinstance(outcome, str) or not outcome:
            return None
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("checkpoint settled attempt has no id")
        last = attempt_id
    return last or "initial"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("checkpoint JSON must be an object")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _digest_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


__all__ = ["RunCheckpointStore", "SCHEMA"]
