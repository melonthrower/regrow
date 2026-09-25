from __future__ import annotations

import copy
from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest
import yaml


from tools.guitraverse_mobile_seed import (
    DEFAULT_MANIFEST,
    AdbClient,
    DeviceGuardError,
    ManifestError,
    apply_seed,
    build_seed_plan,
    canonical_manifest_digest,
    load_snapshot,
    load_manifest,
    main,
    preflight_device,
    save_snapshot,
    verify_seed,
    _apply_contacts,
    _apply_system,
    _local_assets,
)


def _payload() -> dict:
    return {
        "schema": "guitraverse.mobile_seed.v1",
        "profile": "guitraverse_mobile_seed_v1",
        "avd_name": "guitraverse_mobile_seed",
        "snapshot_name": "guitraverse_mobile_seed_v1",
        "required_packages": [
            "com.android.providers.contacts",
            "com.android.providers.telephony",
            "com.android.providers.calendar",
            "com.android.providers.media.module",
            "com.google.android.documentsui",
        ],
        "system": {
            "airplane_mode": False,
            "wifi": True,
            "rotation": "portrait",
            "locale": "en-US",
        },
        "contacts": [
            {"name": "GUITRAVERSE Seed Alice", "number": "5550101"},
            {"name": "GUITRAVERSE Seed Bob", "number": "5550102"},
        ],
        "files": [
            {
                "path": "Download/guitraverse_seed_note.txt",
                "kind": "text",
                "content": "GUITRAVERSE seed note\n",
            },
            {
                "path": "Documents/guitraverse_seed_document.pdf",
                "kind": "pdf",
                "title": "GUITRAVERSE Seed Document",
            },
            {
                "path": "Music/guitraverse_seed_audio.wav",
                "kind": "audio",
                "title": "GUITRAVERSE Seed Tone",
            },
        ],
        "messages": [
            {"from": "5550101", "body": "Seed meeting moved to 3 PM"},
            {"from": "5550102", "body": "Seed photo received"},
        ],
        "calendar": [
            {
                "title": "GUITRAVERSE Seed Team Meeting",
                "offset_days": 0,
                "hour": 15,
                "duration_minutes": 60,
            },
            {
                "title": "GUITRAVERSE Seed Appointment",
                "offset_days": 1,
                "hour": 10,
                "duration_minutes": 30,
            },
        ],
        "photos": [
            {
                "path": "DCIM/Camera/guitraverse_seed_landscape.jpg",
                "label": "GUITRAVERSE Seed Landscape",
                "color": "#3f6f8f",
            },
            {
                "path": "Pictures/guitraverse_seed_receipt.png",
                "label": "GUITRAVERSE Seed Receipt",
                "color": "#8f6f3f",
            },
        ],
    }


def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "seed.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_repository_manifest_is_valid_and_uses_only_synthetic_reserved_data():
    manifest = load_manifest(DEFAULT_MANIFEST)

    assert manifest.schema == "guitraverse.mobile_seed.v1"
    assert manifest.profile == "guitraverse_mobile_seed_v1"
    assert manifest.avd_name == "guitraverse_mobile_seed"
    assert manifest.snapshot_name == "guitraverse_mobile_seed_v1"
    assert [item.number for item in manifest.contacts] == ["5550101", "5550102"]
    assert all(item.path.startswith((
        "Download/", "Documents/", "Music/", "Pictures/"))
               for item in manifest.files)
    assert all("GUITRAVERSE Seed" in item.title for item in manifest.calendar)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(profile="seed_v1"), "profile"),
        (lambda value: value.update(snapshot_name="default_boot"), "snapshot"),
        (lambda value: value["contacts"][1].update(number="13800138000"),
         "reserved"),
        (lambda value: value["contacts"][1].update(number="5550101"),
         "duplicate"),
        (lambda value: value["files"][0].update(path="../secret.txt"),
         "relative"),
        (lambda value: value["files"][0].update(
            content="https://example.com/account"), "URL"),
        (lambda value: value["messages"][0].update(
            body="email me at real@example.com"), "email"),
    ],
)
def test_manifest_rejects_non_synthetic_or_ambiguous_seed_data(
    tmp_path,
    mutate,
    message,
):
    payload = _payload()
    mutate(payload)

    with pytest.raises(ManifestError, match=message):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_digest_and_plan_are_deterministic(tmp_path):
    payload = _payload()
    first = load_manifest(_write_manifest(tmp_path, payload))
    reordered = copy.deepcopy(payload)
    reordered["system"] = dict(reversed(list(reordered["system"].items())))
    second_path = tmp_path / "reordered.yaml"
    second_path.write_text(
        yaml.safe_dump(reordered, sort_keys=False), encoding="utf-8")
    second = load_manifest(second_path)

    first_digest = canonical_manifest_digest(first)
    second_digest = canonical_manifest_digest(second)
    plan = build_seed_plan(first)

    assert first_digest == second_digest
    assert len(first_digest) == 64
    assert plan["schema"] == "guitraverse.mobile_seed.plan.v1"
    assert plan["manifest_digest"] == first_digest
    assert [step["kind"] for step in plan["mutations"]] == [
        "system_settings", "contacts", "files", "inbound_sms",
        "calendar", "photos", "media_scan",
    ]
    assert "external_send" not in json.dumps(plan)
    assert "pm clear" not in json.dumps(plan)


def test_audio_seed_is_generated_without_an_external_encoder(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))

    assets = _local_assets(manifest, tmp_path)
    audio = assets["Music/guitraverse_seed_audio.wav"].read_bytes()

    assert audio[:4] == b"RIFF"
    assert audio[8:12] == b"WAVE"


def test_system_seed_uses_android_connectivity_command_not_protected_broadcast(
    tmp_path,
):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    fake = _FakeRun()
    client = _client(fake)

    _apply_system(manifest, client)

    commands = [call[3:] for call in fake.calls]
    assert ("shell", "cmd", "connectivity", "airplane-mode", "disable") in commands
    assert not any(command[:3] == ("shell", "am", "broadcast")
                   for command in commands)


def test_contact_seed_reuses_existing_guitraverse_raw_row_without_sort_query(
    tmp_path,
):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    manifest = replace(manifest, contacts=manifest.contacts[:1])

    class _ContactRun:
        def __init__(self):
            self.calls = []

        def __call__(self, argv, **_kwargs):
            call = tuple(str(item) for item in argv)
            self.calls.append(call)
            args = call[3:]
            if (args[:3] == ("shell", "content", "query")
                    and "contacts/phones" in " ".join(args)):
                stdout = "No result found.\n"
            elif (args[:3] == ("shell", "content", "query")
                    and "raw_contacts" in " ".join(args)):
                assert "--sort" not in args
                stdout = "Row: 0 _id=1, account_name=GUITRAVERSE\n"
            elif (args[:3] == ("shell", "content", "insert")
                    and args[4] == "content://com.android.contacts/raw_contacts"):
                raise AssertionError("existing unused raw contact should be reused")
            else:
                stdout = "Inserted row.\n"
            return subprocess.CompletedProcess(call, 0, stdout, "")

    fake = _ContactRun()
    _apply_contacts(manifest, _client(fake))

    rendered = [" ".join(call) for call in fake.calls]
    assert any("raw_contact_id:i:1" in command for command in rendered)
    assert any("data1:s:'GUITRAVERSE Seed Alice'" in command
               for command in rendered)


def test_contact_seed_removes_only_duplicate_rows_for_seed_raw_contacts(
    tmp_path,
):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))

    class _DuplicateContactRun:
        def __init__(self):
            self.calls = []

        def __call__(self, argv, **_kwargs):
            call = tuple(str(item) for item in argv)
            self.calls.append(call)
            args = call[3:]
            joined = " ".join(args)
            if (args[:3] == ("shell", "content", "query")
                    and "raw_contacts" in joined):
                stdout = (
                    "Row: 0 _id=1, account_name=GUITRAVERSE\n"
                    "Row: 1 _id=2, account_name=GUITRAVERSE\n"
                )
            elif args[:3] == ("shell", "content", "query"):
                stdout = (
                    "Row: 0 _id=10, raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Alice\n"
                    "Row: 1 _id=11, raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550101\n"
                    "Row: 2 _id=12, raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550101\n"
                    "Row: 3 _id=20, raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Bob\n"
                    "Row: 4 _id=21, raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550102\n"
                    "Row: 5 _id=22, raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550102\n"
                )
            else:
                stdout = "Deleted 1 row.\n"
            return subprocess.CompletedProcess(call, 0, stdout, "")

    fake = _DuplicateContactRun()
    _apply_contacts(manifest, _client(fake))

    deletes = [call[3:] for call in fake.calls
               if call[3:6] == ("shell", "content", "delete")]
    assert [command[command.index("--where") + 1] for command in deletes] == [
        "_id=12", "_id=22",
    ]


class _FakeRun:
    def __init__(
        self,
        *,
        avd_name="guitraverse_mobile_seed",
        missing_package="",
        missing_file=False,
        persist_locale="en-US",
        product_locale="en-US",
    ):
        self.avd_name = avd_name
        self.missing_package = missing_package
        self.missing_file = missing_file
        self.persist_locale = persist_locale
        self.product_locale = product_locale
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, **_kwargs):
        call = tuple(str(item) for item in argv)
        self.calls.append(call)
        args = call[3:]
        stdout = ""
        returncode = 0
        if args == ("get-state",):
            stdout = "device\n"
        elif args == ("emu", "avd", "name"):
            stdout = f"{self.avd_name}\nOK\n"
        elif args == ("shell", "getprop", "sys.boot_completed"):
            stdout = "1\n"
        elif args == ("shell", "getprop", "persist.sys.locale"):
            stdout = f"{self.persist_locale}\n"
        elif args == ("shell", "getprop", "ro.product.locale"):
            stdout = f"{self.product_locale}\n"
        elif args[:3] == ("shell", "pm", "path"):
            package = args[3]
            if package == self.missing_package:
                returncode = 1
            else:
                stdout = f"package:/system/{package}.apk\n"
        elif args[:4] == ("shell", "settings", "get", "global"):
            stdout = "0\n" if args[4] == "airplane_mode_on" else "1\n"
        elif args[:4] == ("shell", "settings", "get", "system"):
            stdout = "0\n"
        elif args[:3] == ("shell", "content", "query"):
            joined = " ".join(args)
            if "contacts/phones" in joined:
                stdout = (
                    "Row: 0 display_name=GUITRAVERSE Seed Alice, number=5550101\n"
                    "Row: 1 display_name=GUITRAVERSE Seed Bob, number=5550102\n"
                )
            elif "com.android.contacts/data" in joined:
                stdout = (
                    "Row: 0 raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Alice\n"
                    "Row: 1 raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550101\n"
                    "Row: 2 raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Bob\n"
                    "Row: 3 raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550102\n"
                )
            elif "sms/inbox" in joined:
                stdout = (
                    "Row: 0 address=5550101, body=Seed meeting moved to 3 PM\n"
                    "Row: 1 address=5550102, body=Seed photo received\n"
                )
            elif "calendar/events" in joined:
                stdout = (
                    "Row: 0 title=GUITRAVERSE Seed Team Meeting\n"
                    "Row: 1 title=GUITRAVERSE Seed Appointment\n"
                )
            elif "media/external/images" in joined:
                stdout = (
                    "Row: 0 _display_name=guitraverse_seed_landscape.jpg\n"
                    "Row: 1 _display_name=guitraverse_seed_receipt.png\n"
                )
            elif "media/external/audio" in joined:
                stdout = "Row: 0 _display_name=guitraverse_seed_audio.wav\n"
        elif args[:3] == ("shell", "ls", "-1"):
            if self.missing_file:
                returncode = 1
                stdout = f"ls: {args[3]}: No such file or directory\n"
            else:
                stdout = args[3].rsplit("/", 1)[-1] + "\n"
        elif args[:2] == ("shell", "find"):
            name = args[args.index("-name") + 1]
            if self.missing_file:
                returncode = 1
                stdout = f"find: {args[2]}/{name}: No such file or directory\n"
            else:
                stdout = f"{args[2]}/{name}\n"
        elif args == ("emu", "avd", "snapshot", "list"):
            stdout = "guitraverse_mobile_seed_v1\nOK\n"
        return subprocess.CompletedProcess(call, returncode, stdout, "")


def _client(fake: _FakeRun, serial="emulator-5612") -> AdbClient:
    return AdbClient("adb", serial, run_command=fake)


def test_apply_confirmation_and_serial_guard_stop_before_any_adb_call(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    fake = _FakeRun()

    with pytest.raises(DeviceGuardError, match="confirmation"):
        apply_seed(manifest, _client(fake), confirmation="wrong-profile")
    assert fake.calls == []

    with pytest.raises(DeviceGuardError, match="local emulator"):
        preflight_device(
            manifest,
            AdbClient("adb", "127.0.0.1:5709", run_command=fake),
        )
    assert fake.calls == []


def test_wrong_avd_or_missing_package_stops_before_first_mutation(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    wrong_avd = _FakeRun(avd_name="Small_Phone_seeded")

    with pytest.raises(DeviceGuardError, match="AVD"):
        preflight_device(manifest, _client(wrong_avd))
    assert not any(" put " in " ".join(call) for call in wrong_avd.calls)

    missing = _FakeRun(missing_package="com.android.providers.calendar")
    with pytest.raises(DeviceGuardError, match="required package"):
        preflight_device(manifest, _client(missing))
    assert not any(" put " in " ".join(call) for call in missing.calls)


def test_preflight_uses_product_locale_when_fresh_avd_has_no_persist_locale(
    tmp_path,
):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    fresh_avd = _FakeRun(persist_locale="", product_locale="en-US")

    identity = preflight_device(manifest, _client(fresh_avd))

    assert identity.locale == "en-US"


def test_verify_is_read_only_and_checks_every_seed_domain(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    fake = _FakeRun()
    client = _client(fake)

    result = verify_seed(manifest, client)

    assert result["ok"] is True
    assert set(result["domains"]) == {
        "system", "contacts", "files", "messages", "calendar", "photos",
    }
    rendered = [" ".join(call) for call in fake.calls]
    forbidden = (" settings put ", " content insert ", " content delete ",
                 " push ", " emu sms send ", " snapshot save ", " snapshot load ")
    assert not any(token in command for token in forbidden for command in rendered)


def test_verify_does_not_treat_missing_file_error_text_as_present(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    missing = _FakeRun(missing_file=True)

    result = verify_seed(manifest, _client(missing))

    assert result["domains"]["files"] is False
    assert result["ok"] is False


def test_verify_reads_contacts_data_when_legacy_phones_uri_is_empty(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))

    class _DataContactsRun(_FakeRun):
        def __call__(self, argv, **kwargs):
            call = tuple(str(item) for item in argv)
            args = call[3:]
            joined = " ".join(args)
            if (args[:3] == ("shell", "content", "query")
                    and "content://contacts/phones/" in joined):
                self.calls.append(call)
                return subprocess.CompletedProcess(
                    call, 0, "No result found.\n", "")
            if (args[:3] == ("shell", "content", "query")
                    and "content://com.android.contacts/data" in joined):
                self.calls.append(call)
                return subprocess.CompletedProcess(call, 0, (
                    "Row: 0 raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Alice\n"
                    "Row: 1 raw_contact_id=1, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550101\n"
                    "Row: 2 raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/name, "
                    "data1=GUITRAVERSE Seed Bob\n"
                    "Row: 3 raw_contact_id=2, "
                    "mimetype=vnd.android.cursor.item/phone_v2, data1=5550102\n"
                ), "")
            return super().__call__(argv, **kwargs)

    result = verify_seed(manifest, _client(_DataContactsRun()))

    assert result["domains"]["contacts"] is True


def test_snapshot_mutation_requires_exact_version_confirmation(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _payload()))
    fake = _FakeRun()
    client = _client(fake)

    with pytest.raises(DeviceGuardError, match="snapshot confirmation"):
        save_snapshot(manifest, client, confirmation="default_boot")
    assert fake.calls == []

    saved = save_snapshot(
        manifest, client, confirmation="guitraverse_mobile_seed_v1")
    loaded = load_snapshot(
        manifest, client, confirmation="guitraverse_mobile_seed_v1")

    assert saved["listed"] is True and loaded["listed"] is True
    rendered = [call[3:] for call in fake.calls]
    assert ("emu", "avd", "snapshot", "save",
            "guitraverse_mobile_seed_v1") in rendered
    assert ("emu", "avd", "snapshot", "load",
            "guitraverse_mobile_seed_v1") in rendered


def test_plan_cli_never_calls_adb(tmp_path, capsys):
    manifest_path = _write_manifest(tmp_path, _payload())
    fake = _FakeRun()

    exit_code = main([
        "--manifest", str(manifest_path),
        "--report-root", str(tmp_path / "reports"),
        "plan",
    ], run_command=fake)

    assert exit_code == 0
    assert fake.calls == []
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["schema"] == "guitraverse.mobile_seed.plan.v1"
