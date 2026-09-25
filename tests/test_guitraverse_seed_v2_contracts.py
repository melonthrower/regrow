from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from tools.guitraverse_seed import (
    AppSeedStatus,
    CertificateIsolation,
    SeedCertificate,
    SharedSeedStatus,
    canonical_digest,
    certificate_ready,
    load_apps_lock,
    load_assets_lock,
    load_v2_manifest,
    render_lock,
)
from tools.guitraverse_seed.locks import validate_apps_lock_records, validate_assets_lock_records


ADAPTER_IDS = (
    "markor",
    "clipper",
    "simple_calendar",
    "tasks_org",
    "simple_draw",
    "simple_gallery",
    "simple_sms",
    "audio_recorder",
    "miniwob",
    "pro_expense",
    "broccoli",
    "osmand",
    "open_tracks",
    "vlc",
    "joplin",
    "retro_music",
)


APP_COUNTS = {
    "markor": 10,
    "clipper": 1,
    "simple_calendar": 10,
    "tasks_org": 10,
    "simple_draw": 5,
    "simple_gallery": 10,
    "simple_sms": 10,
    "audio_recorder": 5,
    "miniwob": 0,
    "pro_expense": 10,
    "broccoli": 10,
    "osmand": 10,
    "open_tracks": 4,
    "vlc": 10,
    "joplin": 10,
    "retro_music": 10,
}


def _objects(prefix: str, count: int, shapes: list[str], *, data_key: str = "text") -> list[dict]:
    return [
        {
            "seed_id": f"{prefix}_{index:02d}",
            "display_name": f"{prefix} representative {index}",
            "shape_tags": shapes if index == 1 else [shapes[0]],
            "data": {data_key: f"synthetic {prefix} value {index}"},
        }
        for index in range(1, count + 1)
    ]


def _dataset(dataset_id: str, count: int, shapes: list[str], objects: list[dict] | None = None, **extra) -> dict:
    return {
        "dataset_id": dataset_id,
        "expected_count": count,
        "required_shapes": shapes,
        "objects": _objects(dataset_id, count, shapes) if objects is None else objects,
        **extra,
    }


def valid_manifest() -> dict:
    shared = [
        _dataset(
            "contacts",
            10,
            ["reserved_number", "searchable", "detail", "editable", "safe_delete"],
            [
                {
                    "seed_id": f"contact_{index:02d}",
                    "display_name": f"Seed Contact {index}",
                    "shape_tags": ["reserved_number", "searchable", "detail", "editable", "safe_delete"]
                    if index == 1
                    else ["reserved_number"],
                    "data": {"phone": f"55501{index:02d}"},
                }
                for index in range(1, 11)
            ],
        ),
        _dataset(
            "sms",
            10,
            ["inbound", "multiple_conversations", "searchable", "detail"],
            [
                {
                    "seed_id": f"sms_{index:02d}",
                    "display_name": f"Inbound message {index}",
                    "shape_tags": ["inbound", "multiple_conversations", "searchable", "detail"]
                    if index == 1
                    else ["inbound"],
                    "data": {"sender": f"55501{index:02d}", "body": f"Synthetic inbound {index}"},
                }
                for index in range(1, 11)
            ],
        ),
        _dataset("system_calendar", 10, ["past", "today", "future", "recurring", "editable"]),
        _dataset("call_logs", 10, ["inbound", "outbound", "missed", "detail"]),
        _dataset("clock", 2, ["alarm", "world_clock", "editable"]),
        _dataset(
            "shared_files",
            23,
            ["document", "image", "audio", "video", "multiple_directories", "no_result_query"],
        ),
    ]
    for index, item in enumerate(shared[-1]["objects"], 1):
        item["data"] = {"kind": "image" if index <= 10 else "audio" if index <= 20 else "video"}
    app_datasets = []
    reference_targets = {
        "simple_gallery": "shared_files_01",
        "simple_sms": "sms_01",
        "vlc": "shared_files_02",
        "retro_music": "shared_files_03",
    }
    for adapter_id in ADAPTER_IDS:
        count = APP_COUNTS[adapter_id]
        if adapter_id == "miniwob":
            app_datasets.append(
                _dataset(
                    adapter_id,
                    0,
                    ["launcher_reachable", "built_in_page_reachable"],
                    [],
                    declared_shapes=["launcher_reachable", "built_in_page_reachable"],
                )
            )
        elif adapter_id in reference_targets:
            target = reference_targets[adapter_id]
            app_datasets.append(
                _dataset(
                    adapter_id,
                    count,
                    ["shared_reference", "searchable", "detail"],
                    [
                        {
                            "seed_id": f"{adapter_id}_ref_{index:02d}",
                            "display_name": f"{adapter_id} reference {index}",
                            "shape_tags": ["shared_reference", "searchable", "detail"]
                            if index == 1
                            else ["shared_reference"],
                            "data": {"shared_seed_id": f"sms_{index:02d}" if adapter_id == "simple_sms" else f"shared_files_{index:02d}" if adapter_id == "simple_gallery" else f"shared_files_{index + 10:02d}" if adapter_id == "retro_music" else f"shared_files_{index + 10:02d}"},
                        }
                        for index in range(1, count + 1)
                    ],
                    reference_only=True,
                )
            )
        else:
            app_datasets.append(
                _dataset(adapter_id, count, ["searchable", "detail", "editable", "safe_delete"])
            )
    return {
        "schema": "guitraverse.explore_seed.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "profile": "guitraverse_mobile_seed_v2",
        "snapshot_name": "guitraverse_mobile_seed_v2",
        "builder_avd": "guitraverse_mobile_seed",
        "source_snapshot": "guitraverse_mobile_seed_v1",
        "prng_seed": 20260830,
        "adapters": list(ADAPTER_IDS),
        "shared_datasets": shared,
        "app_datasets": app_datasets,
    }


def valid_apps_lock() -> dict:
    return {
        "schema": "guitraverse.mobile_apps_lock.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "state": "locked",
        "entries": [
            {
                "adapter_id": adapter_id,
                "display_name": f"{adapter_id} app",
                "gcs_object": f"https://storage.googleapis.com/gresearch/android_world/{adapter_id}.apk",
                "sha256": "a" * 64,
                "size_bytes": 1024,
                "package": f"org.guitraverse.{adapter_id}",
                "version_name": "1.2.3",
                "version_code": 123,
                "signer_sha256": "b" * 64,
                "abis": ["x86_64"],
                "min_sdk": 23,
                "target_sdk": 33,
                "upstream_url": "https://example.org/source",
                "upstream_revision": "v1.2.3",
                "spdx_license": "Apache-2.0",
                "redistributable": True,
                "trademark_note": "Synthetic contract fixture only.",
                "verified_at": "2026-08-30T12:00:00Z",
            }
            for adapter_id in ADAPTER_IDS
        ],
    }


def _write_yaml(tmp_path, name: str, payload: dict):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_v2_manifest_round_trip_has_exact_adapters_and_immutable_data(tmp_path):
    profile = load_v2_manifest(_write_yaml(tmp_path, "profile.yaml", valid_manifest()))

    assert profile.adapter_ids == ADAPTER_IDS
    assert profile.release_id == "guitraverse_mobile_seed_v2"
    assert isinstance(profile.shared_datasets, tuple)
    assert isinstance(profile.shared_datasets[0].objects[0].data, tuple)


def test_v2_manifest_accepts_one_current_clipboard_value_instead_of_fake_history(tmp_path):
    payload = valid_manifest()
    clipper = next(item for item in payload["app_datasets"] if item["dataset_id"] == "clipper")
    clipper.update(
        expected_count=1,
        required_shapes=["current_clipboard", "structured_text", "service_reachable"],
        objects=[
            {
                "seed_id": "clipper_01",
                "display_name": "Structured current clipboard",
                "shape_tags": ["current_clipboard", "structured_text", "service_reachable"],
                "data": {"text": "GUITRAVERSE_Seed_clipboard_route_dinner_receipt"},
            }
        ],
    )

    profile = load_v2_manifest(_write_yaml(tmp_path, "single-clipboard.yaml", payload))

    dataset = next(item for item in profile.app_datasets if item.dataset_id == "clipper")
    assert dataset.expected_count == 1


def test_tracked_v2_manifest_is_the_literal_traversal_inventory():
    manifest_path = Path(__file__).resolve().parents[1] / "data" / "dev_seed" / "guitraverse_explore_seed_v2.yaml"
    profile = load_v2_manifest(manifest_path)

    assert profile.adapter_ids == ADAPTER_IDS
    assert {dataset.dataset_id: dataset.expected_count for dataset in profile.shared_datasets} == {
        "contacts": 10,
        "sms": 10,
        "system_calendar": 10,
        "call_logs": 10,
        "clock": 3,
        "shared_files": 24,
    }
    assert {dataset.dataset_id: dataset.expected_count for dataset in profile.app_datasets} == APP_COUNTS


def test_tracked_v2_manifest_uses_live_verified_paths_and_storage_units():
    manifest_path = Path(__file__).resolve().parents[1] / "data" / "dev_seed" / "guitraverse_explore_seed_v2.yaml"
    profile = load_v2_manifest(manifest_path)
    shared = {item.seed_id: dict(item.data) for dataset in profile.shared_datasets for item in dataset.objects}
    apps = {
        dataset.dataset_id: {item.seed_id: dict(item.data) for item in dataset.objects}
        for dataset in profile.app_datasets
    }
    datasets = {item.dataset_id: item for item in (*profile.shared_datasets, *profile.app_datasets)}

    assert shared["shared_files_01"]["path"] == "Documents/GUITRAVERSE/field_notebook.txt"
    assert shared["shared_files_03"]["path"] == "Pictures/GUITRAVERSE/coastal_view.png"
    assert shared["shared_files_06"] == {
        "artist": "Field Recordings",
        "duration_seconds": 35,
        "kind": "audio",
        "path": "Music/GUITRAVERSE/morning_walk.mp3",
        "title": "Morning Walk",
    }
    assert [shared[seed_id]["duration_seconds"] for seed_id in (
        "shared_files_06", "shared_files_07", "shared_files_08", "shared_files_12", "shared_files_18",
        "shared_files_19", "shared_files_20", "shared_files_21", "shared_files_22", "shared_files_23",
    )] == list(range(35, 81, 5))
    assert [shared[seed_id]["path"] for seed_id in (
        "shared_files_03", "shared_files_04", "shared_files_05", "shared_files_13", "shared_files_14",
        "shared_files_15", "shared_files_16", "shared_files_17", "shared_files_24", "shared_files_25",
    )] == [
        "Pictures/GUITRAVERSE/coastal_view.png",
        "Pictures/GUITRAVERSE/market_receipt.png",
        "Pictures/GUITRAVERSE/trail_map.png",
        "Pictures/GUITRAVERSE/sunset_field.png",
        "Pictures/GUITRAVERSE/violet_receipt.png",
        "Pictures/GUITRAVERSE/orchard_map.png",
        "Pictures/GUITRAVERSE/silver_lake.png",
        "Pictures/GUITRAVERSE/black_stone.png",
        "Pictures/GUITRAVERSE/white_canvas.png",
        "Pictures/GUITRAVERSE/brown_trail.png",
    ]
    assert [value["path"] for value in apps["simple_draw"].values()] == [
        "Pictures/GUITRAVERSE/SimpleDraw/blue_square.png",
        "Pictures/GUITRAVERSE/SimpleDraw/red_circle.png",
        "Pictures/GUITRAVERSE/SimpleDraw/green_line.png",
        "Pictures/GUITRAVERSE/SimpleDraw/yellow_branch.png",
        "Pictures/GUITRAVERSE/SimpleDraw/white_canvas.png",
    ]
    assert [value["duration_db_microseconds"] for value in apps["audio_recorder"].values()] == [
        1_000_000, 4_000_000, 8_000_000, 16_000_000, 2_000_000,
    ]
    assert all(value["db_indexed"] is True for value in apps["audio_recorder"].values())
    assert all(value["group_key"] is None for value in apps["osmand"].values())
    assert all(value["marker_next_key"] is None for value in apps["osmand"].values())
    assert apps["osmand"]["osmand_01"]["serialized_description"] == "location#Balzers"
    assert datasets["clipper"].expected_count == 1
    assert dict(datasets["clipper"].objects[0].data)["text"].startswith("Route dinner receipt")
    assert [dict(item.data) for item in datasets["clock"].objects] == [
        {"label": "Morning", "time": "07:15"},
        {"label": "Evening", "time": "18:40"},
        {"city": "London"},
    ]


def test_tracked_v2_manifest_keeps_internal_ids_out_of_gui_visible_content():
    manifest_path = Path(__file__).resolve().parents[1] / "data" / "dev_seed" / "guitraverse_explore_seed_v2.yaml"
    profile = load_v2_manifest(manifest_path)
    visible = [
        value
        for dataset in (*profile.shared_datasets, *profile.app_datasets)
        for item in dataset.objects
        for value in (item.display_name, *map(str, dict(item.data).values()))
    ]

    assert not any("guitraverse seed" in value.casefold() for value in visible)
    assert not any("seed tone" in value.casefold() for value in visible)
    assert not any("photo_" in value.casefold() for value in visible)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value.update(adapters=list(ADAPTER_IDS[:-1])), "adapter"),
        (lambda value: value.update(adapters=[*ADAPTER_IDS[:-1], "markor"]), "adapter"),
        (lambda value: value.update(adapters=[*ADAPTER_IDS, "unexpected"]), "adapter"),
        (lambda value: value.update(unexpected=True), "unknown"),
        (lambda value: value["shared_datasets"][0].update(expected_count=9), "count"),
        (lambda value: value["shared_datasets"][0]["objects"][0].update(shape_tags=["reserved_number"]), "shape"),
        (lambda value: value["app_datasets"][5]["objects"][0]["data"].update(shared_seed_id="missing_seed"), "shared"),
        (lambda value: value["shared_datasets"][0]["objects"][0]["data"].update(phone="12025550123"), "reserved"),
        (lambda value: value["shared_datasets"][0]["objects"][0]["data"].update(url="https://example.org"), "url"),
        (lambda value: value["shared_datasets"][0]["objects"][0]["data"].update(api_key="not-a-secret"), "credential"),
    ],
)
def test_v2_manifest_rejects_invalid_contract_content(tmp_path, mutate, error):
    payload = valid_manifest()
    mutate(payload)

    with pytest.raises(ValueError, match=error):
        load_v2_manifest(_write_yaml(tmp_path, "invalid.yaml", payload))


def test_apps_and_assets_locks_round_trip(tmp_path):
    apps = load_apps_lock(_write_yaml(tmp_path, "apps.yaml", valid_apps_lock()))
    assets = load_assets_lock(
        _write_yaml(
            tmp_path,
            "assets.yaml",
            {
                "schema": "guitraverse.mobile_assets_lock.v2",
                "release_id": "guitraverse_mobile_seed_v2",
                "state": "draft",
                "generator_provenance": {"generator_id": "guitraverse.assets", "generator_version": "v1"},
                "entries": [],
            },
        )
    )

    assert tuple(entry.adapter_id for entry in apps.entries) == ADAPTER_IDS
    assert assets.state == "draft"
    assert assets.entries == ()


def test_apps_lock_and_render_allow_a_pure_java_apk_without_abis(tmp_path):
    payload = valid_apps_lock()
    payload["entries"][0]["abis"] = []
    lock = load_apps_lock(_write_yaml(tmp_path, "pure-java.yaml", payload))

    rendered = render_lock(lock.entries)
    round_trip = load_apps_lock(_write_yaml(tmp_path, "pure-java-rendered.yaml", yaml.safe_load(rendered)))

    assert lock.entries[0].abis == ()
    assert round_trip.entries[0].abis == ()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("gcs_object", "http://storage.googleapis.com/gresearch/android_world/markor.apk", "GCS"),
        ("sha256", "", "sha256"),
        ("size_bytes", 0, "size"),
        ("package", "not a package", "package"),
        ("version_name", "", "version"),
        ("version_code", 0, "version"),
        ("signer_sha256", "B" * 64, "signer"),
        ("spdx_license", "unknown", "license"),
    ],
)
def test_apps_lock_rejects_unverified_metadata(tmp_path, field, value, error):
    payload = valid_apps_lock()
    payload["entries"][0][field] = value

    with pytest.raises(ValueError, match=error):
        load_apps_lock(_write_yaml(tmp_path, "apps-invalid.yaml", payload))


def test_locked_assets_cannot_be_empty_and_unknown_asset_fields_are_rejected(tmp_path):
    locked_empty = {
        "schema": "guitraverse.mobile_assets_lock.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "state": "locked",
        "generator_provenance": {"generator_id": "guitraverse.assets", "generator_version": "v1"},
        "entries": [],
    }
    with pytest.raises(ValueError, match="locked"):
        load_assets_lock(_write_yaml(tmp_path, "assets-locked.yaml", locked_empty))

    draft_with_unknown = deepcopy(locked_empty)
    draft_with_unknown["state"] = "draft"
    draft_with_unknown["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        load_assets_lock(_write_yaml(tmp_path, "assets-unknown.yaml", draft_with_unknown))


def test_asset_entry_requires_safe_path_hash_and_mapping_generation_parameters(tmp_path):
    payload = {
        "schema": "guitraverse.mobile_assets_lock.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "state": "locked",
        "generator_provenance": {"generator_id": "guitraverse.assets", "generator_version": "v1"},
        "entries": [
            {
                "asset_id": "tone_one",
                "device_path": "GUITRAVERSE/Music/tone_one.wav",
                "kind": "audio",
                "sha256": "c" * 64,
                "size_bytes": 128,
                "source_type": "generated",
                "source": "deterministic tone",
                "generator_id": "guitraverse.assets",
                "generator_version": "v1",
                "generation_params": "host dependent",
                "spdx_license": "Apache-2.0",
            }
        ],
    }

    with pytest.raises(ValueError, match="generation_params"):
        load_assets_lock(_write_yaml(tmp_path, "assets-invalid-params.yaml", payload))


def test_asset_lock_accepts_standard_android_media_root_with_seed_component(tmp_path):
    payload = {
        "schema": "guitraverse.mobile_assets_lock.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "state": "locked",
        "generator_provenance": {"generator_id": "guitraverse.assets", "generator_version": "v1"},
        "entries": [
            {
                "asset_id": "tone_one",
                "device_path": "Music/GUITRAVERSE/tone_01.mp3",
                "kind": "audio",
                "sha256": "c" * 64,
                "size_bytes": 128,
                "source_type": "generated",
                "source": "deterministic tone",
                "generator_id": "guitraverse.assets",
                "generator_version": "v1",
                "generation_params": {},
                "spdx_license": "CC0-1.0",
            }
        ],
    }

    lock = load_assets_lock(_write_yaml(tmp_path, "standard-media-root.yaml", payload))
    assert lock.entries[0].device_path == "Music/GUITRAVERSE/tone_01.mp3"

    payload["entries"][0]["device_path"] = "Music/unowned/tone_01.mp3"
    with pytest.raises(ValueError, match="device_path"):
        load_assets_lock(_write_yaml(tmp_path, "unowned-media-root.yaml", payload))


def test_canonical_digest_ignores_mapping_key_order():
    assert canonical_digest({"outer": {"b": 2, "a": 1}, "a": [3, 2]}) == canonical_digest(
        {"a": [3, 2], "outer": {"a": 1, "b": 2}}
    )


def _ready_certificate(*, partial_adapter: str = "") -> SeedCertificate:
    app_statuses = tuple(
        AppSeedStatus(
            adapter_id=adapter_id,
            installed=True,
            setup=True,
            data=True,
            gui=True,
            evidence=(f"evidence/{adapter_id}.json",),
            partial_reason="needs retry" if adapter_id == partial_adapter else "",
        )
        for adapter_id in ADAPTER_IDS
    )
    shared_statuses = tuple(
        SharedSeedStatus(domain=domain, passed=True, evidence=(f"evidence/{domain}.json",))
        for domain in ("contacts", "sms", "calendar", "call_logs", "clock", "files_media")
    )
    return SeedCertificate(
        release_id="guitraverse_mobile_seed_v2",
        snapshot_name="guitraverse_mobile_seed_v2",
        code_commit="ee28c07c",
        manifest_digest="c" * 64,
        apps_lock_digest="d" * 64,
        assets_lock_digest="e" * 64,
        generator_provenance="guitraverse.assets@v1",
        app_statuses=app_statuses,
        shared_statuses=shared_statuses,
        snapshot_saved=True,
        snapshot_list=("guitraverse_mobile_seed_v1", "guitraverse_mobile_seed_v2"),
        isolation=CertificateIsolation(True, True, ("evidence/isolation.json",)),
        known_gaps=(),
        valid_until="2026-12-31T00:00:00Z",
    )


def test_certificate_readiness_requires_every_app_to_be_complete():
    assert not certificate_ready(_ready_certificate())
    assert not certificate_ready(_ready_certificate(partial_adapter="joplin"))


def test_certificate_rejects_invented_digests_without_locked_bound_inputs():
    assert not certificate_ready(_ready_certificate())


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value["shared_datasets"][0]["objects"][0].update(display_name="https://example.org"), "url"),
        (lambda value: value["shared_datasets"][0].update(required_shapes=["not valid"]), "shape"),
        (lambda value: value["app_datasets"][5]["objects"][1]["data"].update(shared_seed_id="shared_files_01"), "reference"),
        (lambda value: value["app_datasets"][5]["objects"][0]["data"].update(shared_seed_id="contact_01"), "reference"),
    ],
)
def test_manifest_rejects_unsafe_metadata_and_wrong_or_duplicate_references(tmp_path, mutate, error):
    payload = valid_manifest()
    mutate(payload)
    with pytest.raises(ValueError, match=error):
        load_v2_manifest(_write_yaml(tmp_path, "unsafe.yaml", payload))


def test_locks_accept_full_spdx_and_reject_unsafe_path_and_digest_collisions(tmp_path):
    payload = valid_apps_lock()
    payload["entries"][0]["spdx_license"] = "ISC"
    assert load_apps_lock(_write_yaml(tmp_path, "isc.yaml", payload)).entries[0].spdx_license == "ISC"

    assets = {
        "schema": "guitraverse.mobile_assets_lock.v2", "release_id": "guitraverse_mobile_seed_v2", "state": "locked",
        "generator_provenance": {"generator_id": "guitraverse.assets", "generator_version": "v1"},
        "entries": [{"asset_id": "one", "device_path": "GUITRAVERSE\\tone.wav", "kind": "audio", "sha256": "c" * 64,
                     "size_bytes": 1, "source_type": "generated", "source": "tone", "generator_id": "guitraverse.assets",
                     "generator_version": "v1", "generation_params": {}, "spdx_license": "CC0-1.0"}],
    }
    with pytest.raises(ValueError, match="device_path"):
        load_assets_lock(_write_yaml(tmp_path, "unsafe-path.yaml", assets))
    with pytest.raises(ValueError, match="mapping key"):
        canonical_digest({1: "one", "1": "string one"})


def test_hand_built_invalid_app_lock_records_are_rejected(tmp_path):
    lock = load_apps_lock(_write_yaml(tmp_path, "apps.yaml", valid_apps_lock()))
    assert not validate_apps_lock_records(replace(lock, entries=(replace(lock.entries[0], sha256="BAD"), *lock.entries[1:])))


def test_hand_built_assets_lock_requires_generator_provenance(tmp_path):
    payload = {"schema": "guitraverse.mobile_assets_lock.v2", "release_id": "guitraverse_mobile_seed_v2", "state": "locked", "generator_provenance": {"generator_id": "g", "generator_version": "v"}, "entries": [{"asset_id": "a", "device_path": "GUITRAVERSE/a", "kind": "text", "sha256": "a" * 64, "size_bytes": 1, "source_type": "generated", "source": "s", "generator_id": "g", "generator_version": "v", "generation_params": {}, "spdx_license": "MIT"}]}
    lock = load_assets_lock(_write_yaml(tmp_path, "assets-valid.yaml", payload))
    assert not validate_assets_lock_records(replace(lock, generator_provenance=(("generator_id", ""), ("generator_version", ""))))
