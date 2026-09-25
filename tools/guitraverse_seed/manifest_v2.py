from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import yaml

from .contracts import ManifestError, TraversalSeedDataset, TraversalSeedObject, TraversalSeedProfile


ADAPTER_IDS = (
    "markor", "clipper", "simple_calendar", "tasks_org", "simple_draw", "simple_gallery",
    "simple_sms", "audio_recorder", "miniwob", "pro_expense", "broccoli", "osmand",
    "open_tracks", "vlc", "joplin", "retro_music",
)
_SHARED_DATASET_IDS = ("contacts", "sms", "system_calendar", "call_logs", "clock", "shared_files")
_APP_COUNTS = {
    "markor": 10, "clipper": 1, "simple_calendar": 10, "tasks_org": 10,
    "simple_draw": 5, "simple_gallery": 10, "simple_sms": 10, "audio_recorder": 5,
    "miniwob": 0, "pro_expense": 10, "broccoli": 10, "osmand": 10,
    "vlc": 10, "joplin": 10, "retro_music": 10,
}
_REFERENCE_ONLY = frozenset({"simple_gallery", "simple_sms", "vlc", "retro_music"})
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(\d{7,})(?!\d)")
_CREDENTIAL_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.IGNORECASE)


def _load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"invalid manifest YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest root must be a mapping")
    return value


def _strict(mapping: dict[str, Any], allowed: set[str], scope: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ManifestError(f"unknown {scope} fields: {sorted(unknown)}")
    missing = allowed - set(mapping)
    if missing:
        raise ManifestError(f"missing {scope} fields: {sorted(missing)}")


def _strings(value: Any, scope: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{scope} must be a non-empty string list")
    if len(set(value)) != len(value):
        raise ManifestError(f"{scope} contains duplicates")
    for item in value:
        _freeze(item, scope)
        if "shape" in scope and not re.fullmatch(r"[a-z][a-z0-9_]*", item):
            raise ManifestError(f"{scope} must use stable ASCII shape identifiers")
    return tuple(value)


def _freeze(value: Any, scope: str) -> object:
    if isinstance(value, dict):
        frozen: list[tuple[str, object]] = []
        for key in sorted(value):
            if not isinstance(key, str) or not key:
                raise ManifestError(f"{scope} has an invalid data key")
            if _CREDENTIAL_KEY.search(key):
                raise ManifestError(f"credential-like key in {scope}")
            frozen.append((key, _freeze(value[key], scope)))
        return tuple(frozen)
    if isinstance(value, list):
        return tuple(_freeze(item, scope) for item in value)
    if isinstance(value, str):
        if "http://" in value or "https://" in value:
            raise ManifestError(f"external url in {scope}")
        if _EMAIL.search(value):
            raise ManifestError(f"email address in {scope}")
        for phone in _PHONE.findall(value):
            if not re.fullmatch(r"55501\d{2}", phone):
                raise ManifestError(f"non-reserved phone number in {scope}")
        return value
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ManifestError(f"unsupported value in {scope}")


def _parse_object(raw: Any, scope: str) -> TraversalSeedObject:
    if not isinstance(raw, dict):
        raise ManifestError(f"{scope} object must be a mapping")
    _strict(raw, {"seed_id", "display_name", "shape_tags", "data"}, f"{scope} object")
    seed_id = raw["seed_id"]
    display_name = raw["display_name"]
    if not isinstance(seed_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", seed_id):
        raise ManifestError(f"{scope} seed_id must be stable ASCII")
    if not isinstance(display_name, str) or not display_name:
        raise ManifestError(f"{scope} display_name is required")
    _freeze(display_name, scope)
    shapes = _strings(raw["shape_tags"], f"{scope} shape_tags")
    if not isinstance(raw["data"], dict):
        raise ManifestError(f"{scope} data must be a mapping")
    return TraversalSeedObject(seed_id, display_name, shapes, _freeze(raw["data"], scope))


def _parse_dataset(raw: Any, scope: str) -> TraversalSeedDataset:
    if not isinstance(raw, dict):
        raise ManifestError(f"{scope} dataset must be a mapping")
    required = {"dataset_id", "expected_count", "required_shapes", "objects"}
    optional = {"reference_only", "declared_shapes"}
    unknown = set(raw) - required - optional
    missing = required - set(raw)
    if unknown:
        raise ManifestError(f"unknown {scope} dataset fields: {sorted(unknown)}")
    if missing:
        raise ManifestError(f"missing {scope} dataset fields: {sorted(missing)}")
    dataset_id = raw["dataset_id"]
    if not isinstance(dataset_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", dataset_id):
        raise ManifestError(f"invalid {scope} dataset id")
    expected_count = raw["expected_count"]
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
        raise ManifestError(f"invalid {dataset_id} count")
    required_shapes = _strings(raw["required_shapes"], f"{dataset_id} required_shapes")
    declared_shapes = () if "declared_shapes" not in raw else _strings(raw["declared_shapes"], f"{dataset_id} declared_shapes")
    reference_only = raw.get("reference_only", False)
    if not isinstance(reference_only, bool):
        raise ManifestError(f"{dataset_id} reference_only must be boolean")
    if not isinstance(raw["objects"], list):
        raise ManifestError(f"{dataset_id} objects must be a list")
    objects = tuple(_parse_object(item, dataset_id) for item in raw["objects"])
    if len(objects) != expected_count:
        raise ManifestError(f"{dataset_id} count does not match objects")
    object_shapes = {shape for item in objects for shape in item.shape_tags}
    if not set(required_shapes).issubset(object_shapes | set(declared_shapes)):
        raise ManifestError(f"{dataset_id} required shape is missing")
    return TraversalSeedDataset(dataset_id, expected_count, required_shapes, objects, reference_only, declared_shapes)


def _thaw_data(data: tuple[tuple[str, object], ...]) -> dict[str, object]:
    return dict(data)


def _validate_dataset_inventory(profile: TraversalSeedProfile) -> None:
    shared = {item.dataset_id: item for item in profile.shared_datasets}
    apps = {item.dataset_id: item for item in profile.app_datasets}
    if tuple(item.dataset_id for item in profile.shared_datasets) != _SHARED_DATASET_IDS:
        raise ManifestError("shared dataset inventory is not literal v2")
    if tuple(item.dataset_id for item in profile.app_datasets) != ADAPTER_IDS:
        raise ManifestError("app dataset inventory is not literal v2")
    for name in ("contacts", "sms", "system_calendar", "call_logs"):
        if shared[name].expected_count != 10:
            raise ManifestError(f"{name} count must be 10")
    if shared["clock"].expected_count < 1:
        raise ManifestError("clock requires representatives")
    if not 20 <= shared["shared_files"].expected_count <= 25:
        raise ManifestError("shared_files count must be 20-25")
    for adapter_id, count in _APP_COUNTS.items():
        if apps[adapter_id].expected_count != count:
            raise ManifestError(f"{adapter_id} has an invalid count")
    if not 3 <= apps["open_tracks"].expected_count <= 5:
        raise ManifestError("open_tracks count must be 3-5")
    if apps["miniwob"].objects or not apps["miniwob"].declared_shapes:
        raise ManifestError("miniwob must declare reachability without records")
    for adapter_id in _REFERENCE_ONLY:
        dataset = apps[adapter_id]
        if not dataset.reference_only:
            raise ManifestError(f"{adapter_id} must be reference-only")
        for item in dataset.objects:
            if set(_thaw_data(item.data)) != {"shared_seed_id"}:
                raise ManifestError(f"{adapter_id} reference duplicates shared payload")
    all_ids = [item.seed_id for dataset in (*profile.shared_datasets, *profile.app_datasets) for item in dataset.objects]
    if len(set(all_ids)) != len(all_ids):
        raise ManifestError("duplicate seed id")
    shared_by_dataset = {dataset.dataset_id: {item.seed_id: item for item in dataset.objects} for dataset in profile.shared_datasets}
    shared_ids = {seed_id for values in shared_by_dataset.values() for seed_id in values}
    for dataset in profile.app_datasets:
        if dataset.reference_only:
            references: set[str] = set()
            for item in dataset.objects:
                target = _thaw_data(item.data)["shared_seed_id"]
                if target not in shared_ids:
                    raise ManifestError("dangling shared reference")
                if target in references:
                    raise ManifestError("duplicate shared reference")
                references.add(target)
                target_dataset = "sms" if dataset.dataset_id == "simple_sms" else "shared_files"
                if target not in shared_by_dataset[target_dataset]:
                    raise ManifestError("reference domain is invalid")
                target_object = shared_by_dataset[target_dataset][target]
                kind = _thaw_data(target_object.data).get("kind")
                allowed = {
                    "simple_sms": {None}, "simple_gallery": {"image", "video"},
                    "retro_music": {"audio"}, "vlc": {"audio", "video"},
                }[dataset.dataset_id]
                if dataset.dataset_id != "simple_sms" and kind not in allowed:
                    raise ManifestError("reference kind is invalid")


def load_v2_manifest(path: str | Path) -> TraversalSeedProfile:
    raw = _load_yaml(path)
    fields = {
        "schema", "release_id", "profile", "snapshot_name", "builder_avd", "source_snapshot", "prng_seed",
        "adapters", "shared_datasets", "app_datasets",
    }
    _strict(raw, fields, "manifest")
    identity = {
        "schema": "guitraverse.explore_seed.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "profile": "guitraverse_mobile_seed_v2",
        "snapshot_name": "guitraverse_mobile_seed_v2",
        "builder_avd": "guitraverse_mobile_seed",
        "source_snapshot": "guitraverse_mobile_seed_v1",
    }
    for field, expected in identity.items():
        if raw[field] != expected:
            raise ManifestError(f"invalid v2 {field}")
    if not isinstance(raw["prng_seed"], int) or isinstance(raw["prng_seed"], bool):
        raise ManifestError("prng_seed must be an integer")
    adapters = _strings(raw["adapters"], "adapters")
    if adapters != ADAPTER_IDS:
        raise ManifestError("adapter IDs must be the exact v2 set")
    if not isinstance(raw["shared_datasets"], list) or not isinstance(raw["app_datasets"], list):
        raise ManifestError("dataset inventories must be lists")
    profile = TraversalSeedProfile(
        raw["schema"], raw["release_id"], raw["profile"], raw["snapshot_name"], raw["builder_avd"],
        raw["source_snapshot"], raw["prng_seed"], adapters,
        tuple(_parse_dataset(item, "shared") for item in raw["shared_datasets"]),
        tuple(_parse_dataset(item, "app") for item in raw["app_datasets"]),
    )
    _validate_dataset_inventory(profile)
    return profile
