"""Runtime Android app names must resolve to the exact v2 dataset inventory."""

from __future__ import annotations

from pathlib import Path

from tools.guitraverse_seed.runtime_apps import RUNTIME_APP_TO_DATASET
from tools.guitraverse_seed.v2_runtime import (
    _default_dataset_adapters,
    apply_seed_plan,
    build_traversal_seed_plan,
)


MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "dev_seed"
    / "guitraverse_explore_seed_v2.yaml"
)


EXPECTED = {
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


def test_runtime_app_map_covers_every_v2_androidworld_app() -> None:
    assert RUNTIME_APP_TO_DATASET == EXPECTED


def test_every_runtime_app_name_builds_a_serializable_exact_plan() -> None:
    for runtime_app, dataset_id in EXPECTED.items():
        plan = build_traversal_seed_plan(
            MANIFEST,
            base_snapshot="guitraverse_mobile_clean_base_v1",
            app_id=runtime_app,
        )

        assert plan["apps"] == [runtime_app]
        assert {item["dataset_id"] for item in plan["objects"]} <= {
            dataset_id, "sms", "shared_files",
        }


def test_default_adapter_registry_covers_every_v2_dataset() -> None:
    assert set(_default_dataset_adapters()) == {
        *EXPECTED.values(), "sms", "shared_files",
    }


def test_every_runtime_app_plan_dispatches_only_its_declared_datasets() -> None:
    for runtime_app, dataset_id in EXPECTED.items():
        plan = build_traversal_seed_plan(
            MANIFEST,
            base_snapshot="guitraverse_mobile_clean_base_v1",
            app_id=runtime_app,
        )
        calls: list[str] = []

        def adapter(objects, _device, _environment, *, name):
            calls.append(name)
            return [True] * len(objects)

        adapter_names = {
            *plan["datasets"],
            *(item["dataset_id"] for item in plan["objects"]),
        }
        report = apply_seed_plan(
            plan,
            object(),
            expected_snapshot="guitraverse_mobile_clean_base_v1",
            dataset_adapters={
                name: (lambda objects, device, environment, name=name: adapter(
                    objects, device, environment, name=name))
                for name in adapter_names
            },
        )

        assert set(calls) == adapter_names
        assert report["ok"] is True
