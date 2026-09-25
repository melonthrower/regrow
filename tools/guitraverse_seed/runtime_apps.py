"""Authoritative Android runtime-name to v2 seed-dataset bindings."""

from __future__ import annotations

from .androidworld_apps import ANDROIDWORLD_APPS


RUNTIME_APP_TO_DATASET = {
    "markor": "markor",
    "clipper": "clipper",
    "simple_calendar_pro": "simple_calendar",
    "tasks": "tasks_org",
    "simple_draw_pro": "simple_draw",
    "simple_gallery_pro": "simple_gallery",
    "simple_sms_messenger": "simple_sms",
    "audio_recorder": "audio_recorder",
    "miniwob": "miniwob",
    "pro_expense": "pro_expense",
    "broccoli": "broccoli",
    "osmand": "osmand",
    "opentracks": "open_tracks",
    "vlc": "vlc",
    "joplin": "joplin",
    "retro_music": "retro_music",
}

_PACKAGE_BY_DATASET = {
    item.adapter_id: item.package
    for item in ANDROIDWORLD_APPS
}


def dataset_id_for_runtime_app(app_name: str) -> str:
    """Resolve one public traversal/collection app name without guessing."""
    name = str(app_name or "").strip()
    if name in RUNTIME_APP_TO_DATASET:
        return RUNTIME_APP_TO_DATASET[name]
    if name in _PACKAGE_BY_DATASET:
        return name
    raise ValueError(f"no v2 dataset binding is declared for runtime app {name!r}")


def package_for_runtime_app(app_name: str) -> str:
    """Return the package tied to the same binding used by SeedPlan."""
    return _PACKAGE_BY_DATASET[dataset_id_for_runtime_app(app_name)]


def package_for_dataset(dataset_id: str) -> str:
    """Return the package for an already resolved v2 dataset id."""
    try:
        return _PACKAGE_BY_DATASET[dataset_id]
    except KeyError as exc:
        raise ValueError(f"no Android package is declared for dataset {dataset_id!r}") from exc


__all__ = [
    "RUNTIME_APP_TO_DATASET",
    "dataset_id_for_runtime_app",
    "package_for_runtime_app",
    "package_for_dataset",
]
