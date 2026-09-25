from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression

from .contracts import ApkLockEntry, AppsLock, AssetLockEntry, AssetsLock, ManifestError
from .manifest_v2 import ADAPTER_IDS


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PACKAGE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")
_ANDROID_SHARED_ROOTS = frozenset({"DCIM", "Documents", "Download", "Movies", "Music", "Pictures"})


def _load(path: str | Path, label: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"invalid {label} YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{label} root must be a mapping")
    return raw


def _strict(raw: dict[str, Any], fields: set[str], label: str) -> None:
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ManifestError(f"unknown {label} fields: {sorted(unknown)}")
    if missing:
        raise ManifestError(f"missing {label} fields: {sorted(missing)}")


def _text(raw: dict[str, Any], field: str, label: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} {field} is required")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManifestError(f"{label} sha256 must be lowercase 64-hex")
    return value


def _spdx(value: object, label: str) -> str:
    if not isinstance(value, str) or value.lower() in {"unknown", "proprietary"}:
        raise ManifestError(f"{label} license must be a known SPDX identifier")
    try:
        return canonicalize_license_expression(value)
    except InvalidLicenseExpression as exc:
        raise ManifestError(f"{label} license must be a known SPDX identifier") from exc


def _https(value: str, label: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ManifestError(f"{label} must be HTTPS")


def _parse_app(raw: Any) -> ApkLockEntry:
    if not isinstance(raw, dict):
        raise ManifestError("APK entry must be a mapping")
    fields = {
        "adapter_id", "display_name", "gcs_object", "sha256", "size_bytes", "package", "version_name",
        "version_code", "signer_sha256", "abis", "min_sdk", "target_sdk", "upstream_url", "upstream_revision",
        "spdx_license", "redistributable", "trademark_note", "verified_at",
    }
    _strict(raw, fields, "APK entry")
    adapter_id = _text(raw, "adapter_id", "APK entry")
    gcs_object = _text(raw, "gcs_object", "APK entry")
    if not gcs_object.startswith("https://storage.googleapis.com/gresearch/android_world/"):
        raise ManifestError("APK GCS object must be an official HTTPS AndroidWorld source")
    size_bytes = raw["size_bytes"]
    version_code = raw["version_code"]
    min_sdk = raw["min_sdk"]
    target_sdk = raw["target_sdk"]
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (size_bytes, version_code, min_sdk, target_sdk)):
        raise ManifestError("APK size and version/SDK values must be positive")
    if min_sdk > target_sdk:
        raise ManifestError("APK SDK ordering is invalid")
    package = _text(raw, "package", "APK entry")
    if not _PACKAGE.fullmatch(package):
        raise ManifestError("APK package syntax is invalid")
    abis = raw["abis"]
    if not isinstance(abis, list) or any(not isinstance(item, str) or not item for item in abis) or len(set(abis)) != len(abis):
        raise ManifestError("APK ABI list is invalid")
    upstream_url = _text(raw, "upstream_url", "APK entry")
    _https(upstream_url, "APK upstream_url")
    verified_at = _text(raw, "verified_at", "APK entry")
    if not _TIME.fullmatch(verified_at):
        raise ManifestError("APK verified_at must be ISO/RFC3339-like")
    if not isinstance(raw["redistributable"], bool):
        raise ManifestError("APK redistributable must be boolean")
    return ApkLockEntry(
        adapter_id, _text(raw, "display_name", "APK entry"), gcs_object, _sha(raw["sha256"], "APK"), size_bytes,
        package, _text(raw, "version_name", "APK entry"), version_code, _sha(raw["signer_sha256"], "APK signer"),
        tuple(abis), min_sdk, target_sdk, upstream_url, _text(raw, "upstream_revision", "APK entry"),
        _spdx(raw["spdx_license"], "APK"), raw["redistributable"], _text(raw, "trademark_note", "APK entry"), verified_at,
    )


def load_apps_lock(path: str | Path) -> AppsLock:
    raw = _load(path, "apps lock")
    _strict(raw, {"schema", "release_id", "state", "entries"}, "apps lock")
    if raw["schema"] != "guitraverse.mobile_apps_lock.v2" or raw["release_id"] != "guitraverse_mobile_seed_v2":
        raise ManifestError("apps lock is not v2")
    if raw["state"] != "locked" or not isinstance(raw["entries"], list):
        raise ManifestError("apps lock must be locked with entries")
    entries = tuple(_parse_app(item) for item in raw["entries"])
    adapter_ids = tuple(item.adapter_id for item in entries)
    packages = tuple(item.package for item in entries)
    sources = tuple(item.gcs_object for item in entries)
    if adapter_ids != ADAPTER_IDS or len(set(packages)) != len(packages) or len(set(sources)) != len(sources):
        raise ManifestError("apps lock must contain every exact adapter once")
    return AppsLock(raw["schema"], raw["release_id"], raw["state"], entries)


def validate_apps_lock_records(lock: AppsLock) -> bool:
    try:
        if lock.schema != "guitraverse.mobile_apps_lock.v2" or lock.release_id != "guitraverse_mobile_seed_v2" or lock.state != "locked":
            return False
        entries = tuple(_parse_app({**dataclasses.asdict(entry), "abis": list(entry.abis)}) for entry in lock.entries)
        return tuple(entry.adapter_id for entry in entries) == ADAPTER_IDS and len({entry.package for entry in entries}) == len(entries) and len({entry.gcs_object for entry in entries}) == len(entries)
    except (ManifestError, TypeError):
        return False


def _freeze(value: Any, label: str) -> object:
    if isinstance(value, dict):
        if any(not isinstance(key, str) or not key for key in value):
            raise ManifestError(f"invalid {label}")
        return tuple((key, _freeze(value[key], label)) for key in sorted(value))
    if isinstance(value, list):
        return tuple(_freeze(item, label) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ManifestError(f"invalid {label}")


def _parse_asset(raw: Any) -> AssetLockEntry:
    if not isinstance(raw, dict):
        raise ManifestError("asset entry must be a mapping")
    fields = {
        "asset_id", "device_path", "kind", "sha256", "size_bytes", "source_type", "source", "generator_id",
        "generator_version", "generation_params", "spdx_license",
    }
    _strict(raw, fields, "asset entry")
    device_path = _text(raw, "device_path", "asset entry")
    parts = device_path.split("/")
    seed_owned = parts[0] == "GUITRAVERSE" or (
        len(parts) > 1 and parts[0] in _ANDROID_SHARED_ROOTS and parts[1] == "GUITRAVERSE"
    )
    if "\\" in device_path or re.match(r"[A-Za-z]:|[a-zA-Z][a-zA-Z0-9+.-]*:", device_path) or any(ord(char) < 32 for char in device_path) or device_path.startswith("/") or any(part in {"", ".", ".."} for part in parts) or not seed_owned:
        raise ManifestError("asset device_path must be seed-owned relative")
    size_bytes = raw["size_bytes"]
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        raise ManifestError("asset size must be positive")
    if not isinstance(raw["generation_params"], dict):
        raise ManifestError("asset generation_params must be a mapping")
    return AssetLockEntry(
        _text(raw, "asset_id", "asset entry"), device_path, _text(raw, "kind", "asset entry"),
        _sha(raw["sha256"], "asset"), size_bytes, _text(raw, "source_type", "asset entry"),
        _text(raw, "source", "asset entry"), _text(raw, "generator_id", "asset entry"),
        _text(raw, "generator_version", "asset entry"), _freeze(raw["generation_params"], "asset generation_params"),
        _spdx(raw["spdx_license"], "asset"),
    )


def load_assets_lock(path: str | Path) -> AssetsLock:
    raw = _load(path, "assets lock")
    _strict(raw, {"schema", "release_id", "state", "generator_provenance", "entries"}, "assets lock")
    if raw["schema"] != "guitraverse.mobile_assets_lock.v2" or raw["release_id"] != "guitraverse_mobile_seed_v2":
        raise ManifestError("assets lock is not v2")
    if raw["state"] not in {"draft", "locked"} or not isinstance(raw["entries"], list):
        raise ManifestError("assets lock state or entries is invalid")
    provenance = raw["generator_provenance"]
    if not isinstance(provenance, dict):
        raise ManifestError("assets generator provenance must be a mapping")
    _strict(provenance, {"generator_id", "generator_version"}, "assets generator provenance")
    provenance_items = tuple((key, _text(provenance, key, "assets generator provenance")) for key in sorted(provenance))
    entries = tuple(_parse_asset(item) for item in raw["entries"])
    if raw["state"] == "locked" and not entries:
        raise ManifestError("locked assets file cannot be empty")
    if len({entry.asset_id for entry in entries}) != len(entries) or len({entry.device_path for entry in entries}) != len(entries):
        raise ManifestError("asset IDs and paths must be unique")
    return AssetsLock(raw["schema"], raw["release_id"], raw["state"], provenance_items, entries)


def validate_assets_lock_records(lock: AssetsLock) -> bool:
    try:
        if lock.schema != "guitraverse.mobile_assets_lock.v2" or lock.release_id != "guitraverse_mobile_seed_v2" or lock.state != "locked" or not lock.entries:
            return False
        provenance = dict(lock.generator_provenance)
        if set(provenance) != {"generator_id", "generator_version"} or not all(isinstance(value, str) and value for value in provenance.values()):
            return False
        entries = tuple(_parse_asset({**dataclasses.asdict(entry), "generation_params": dict(entry.generation_params)}) for entry in lock.entries)
        return len({entry.asset_id for entry in entries}) == len(entries) and len({entry.device_path for entry in entries}) == len(entries)
    except (ManifestError, TypeError):
        return False


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ManifestError("canonical digest mapping key must be a string")
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_digest(value: Any) -> str:
    payload = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
