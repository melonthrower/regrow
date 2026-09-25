from __future__ import annotations

from dataclasses import asdict
import datetime as dt
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import struct
import tempfile
from typing import Any, Iterable, Mapping
import wave

from PIL import Image, ImageDraw

from .adb import AdbClient, preflight_device
from .contracts import DeviceGuardError, SeedManifest
from .manifest_v1 import canonical_manifest_digest


def _query_ok(output: str, expected: Iterable[str]) -> bool:
    normalized = output.casefold()
    return all(str(item).casefold() in normalized for item in expected)


def _content_bind(column: str, value_type: str, value: Any) -> str:
    return f"{column}:{value_type}:{shlex.quote(str(value))}"


def verify_seed(manifest: SeedManifest, adb: AdbClient) -> dict[str, Any]:
    identity = preflight_device(manifest, adb)
    errors: list[str] = []
    airplane = adb.run("shell", "settings", "get", "global", "airplane_mode_on").strip()
    wifi = adb.run("shell", "settings", "get", "global", "wifi_on").strip()
    rotation = adb.run("shell", "settings", "get", "system", "user_rotation").strip()
    if airplane != ("1" if manifest.system.airplane_mode else "0"):
        errors.append("system.airplane_mode")
    if wifi != ("1" if manifest.system.wifi else "0"):
        errors.append("system.wifi")
    if rotation != "0":
        errors.append("system.rotation")
    domains: dict[str, bool] = {"system": not errors}

    contacts = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.contacts/data", "--projection",
        "raw_contact_id:mimetype:data1")
    domains["contacts"] = _query_ok(
        contacts, [value for item in manifest.contacts for value in (item.name, item.number)])

    file_results = []
    for item in manifest.files:
        remote = PurePosixPath("/sdcard") / item.path
        output = adb.run(
            "shell", "find", str(remote.parent), "-maxdepth", "1",
            "-type", "f", "-name", remote.name, "-print", check=False)
        file_results.append(any(
            line.strip() == str(remote) for line in output.splitlines()))
    domains["files"] = all(file_results)

    messages = adb.run(
        "shell", "content", "query", "--uri", "content://sms/inbox",
        "--projection", "address:body")
    domains["messages"] = _query_ok(
        messages, [value for item in manifest.messages for value in (item.sender, item.body)])

    events = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.calendar/events", "--projection", "title")
    domains["calendar"] = _query_ok(events, [item.title for item in manifest.calendar])

    images = adb.run(
        "shell", "content", "query", "--uri",
        "content://media/external/images/media", "--projection", "_display_name")
    photos_ok = _query_ok(images, [PurePosixPath(item.path).name for item in manifest.photos])
    audio_files = [item for item in manifest.files if item.kind == "audio"]
    if audio_files:
        audio = adb.run(
            "shell", "content", "query", "--uri",
            "content://media/external/audio/media", "--projection", "_display_name")
        photos_ok = photos_ok and _query_ok(
            audio, [PurePosixPath(item.path).name for item in audio_files])
    domains["photos"] = photos_ok
    for name, ok in domains.items():
        if not ok:
            errors.append(name)
    return {
        "schema": "guitraverse.mobile_seed.verify.v1",
        "profile": manifest.profile,
        "manifest_digest": canonical_manifest_digest(manifest),
        "device": asdict(identity),
        "ok": not errors,
        "domains": domains,
        "errors": list(dict.fromkeys(errors)),
    }


def _make_pdf(path: Path, title: str) -> None:
    escaped = title.replace("(", "[").replace(")", "]")
    content = f"BT /F1 22 Tf 72 700 Td ({escaped}) Tj ET".encode("ascii")
    body = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj\n"
        + f"4 0 obj<</Length {len(content)}>>stream\n".encode("ascii")
        + content
        + b"\nendstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    path.write_bytes(body)


def _make_image(path: Path, label: str, color: str) -> None:
    image = Image.new("RGB", (1080, 1440), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 620, 1020, 820), fill="#20252b")
    draw.text((90, 700), label, fill="white")
    image.save(path, "PNG" if path.suffix.casefold() == ".png" else "JPEG")


def _make_audio(path: Path, title: str) -> None:
    del title
    sample_rate = 8000
    frame_count = sample_rate * 2
    frames = bytearray()
    for index in range(frame_count):
        value = round(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(bytes(frames))


def _local_assets(manifest: SeedManifest, root: Path) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    for item in manifest.files:
        local = root / PurePosixPath(item.path).name
        if item.kind == "text":
            local.write_text(item.content, encoding="utf-8")
        elif item.kind == "pdf":
            _make_pdf(local, item.title)
        elif item.kind == "image":
            _make_image(local, item.title, "#3f7f5f")
        else:
            _make_audio(local, item.title)
        assets[item.path] = local
    for item in manifest.photos:
        local = root / PurePosixPath(item.path).name
        _make_image(local, item.label, item.color)
        assets[item.path] = local
    return assets


def _apply_system(manifest: SeedManifest, adb: AdbClient) -> None:
    airplane = "enable" if manifest.system.airplane_mode else "disable"
    wifi = "enable" if manifest.system.wifi else "disable"
    adb.run("shell", "cmd", "connectivity", "airplane-mode", airplane)
    adb.run("shell", "svc", "wifi", wifi)
    adb.run("shell", "settings", "put", "system", "accelerometer_rotation", "0")
    adb.run("shell", "settings", "put", "system", "user_rotation", "0")


def _apply_contacts(manifest: SeedManifest, adb: AdbClient) -> None:
    existing = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.contacts/data", "--projection",
        "raw_contact_id:mimetype:data1", check=False)
    used_raw_ids = {
        match.group(1)
        for line in existing.splitlines()
        if "mimetype=vnd.android.cursor.item/phone_v2" in line
        for match in [re.search(r"raw_contact_id=(\d+)", line)]
        if match is not None
    }
    for contact in manifest.contacts:
        if contact.name in existing and contact.number in existing:
            continue
        raw = adb.run(
            "shell", "content", "query", "--uri",
            "content://com.android.contacts/raw_contacts", "--projection",
            "_id:account_name:account_type", check=False)
        raw_ids = {
            match.group(1)
            for line in raw.splitlines()
            if "account_name=GUITRAVERSE" in line
            for match in [re.search(r"_id=(\d+)", line)]
            if match is not None
        }
        unused = sorted(raw_ids - used_raw_ids, key=int)
        if unused:
            raw_id = unused[0]
        else:
            inserted = adb.run(
                "shell", "content", "insert", "--uri",
                "content://com.android.contacts/raw_contacts",
                "--bind", _content_bind("account_name", "s", "GUITRAVERSE"),
                "--bind", _content_bind("account_type", "s", "LOCAL"),
            )
            match = re.search(r"raw_contacts/(\d+)", inserted)
            if match is not None:
                raw_id = match.group(1)
            else:
                refreshed = adb.run(
                    "shell", "content", "query", "--uri",
                    "content://com.android.contacts/raw_contacts", "--projection",
                    "_id:account_name:account_type", check=False)
                refreshed_ids = {
                    item.group(1)
                    for line in refreshed.splitlines()
                    if "account_name=GUITRAVERSE" in line
                    for item in [re.search(r"_id=(\d+)", line)]
                    if item is not None
                }
                new_ids = sorted(
                    refreshed_ids - raw_ids - used_raw_ids, key=int)
                if not new_ids:
                    raise DeviceGuardError(
                        "contact provider did not return a raw contact id")
                raw_id = new_ids[-1]
        adb.run(
            "shell", "content", "insert", "--uri",
            "content://com.android.contacts/data",
            "--bind", _content_bind("raw_contact_id", "i", raw_id),
            "--bind", _content_bind(
                "mimetype", "s", "vnd.android.cursor.item/name"),
            "--bind", _content_bind("data1", "s", contact.name),
        )
        adb.run(
            "shell", "content", "insert", "--uri",
            "content://com.android.contacts/data",
            "--bind", _content_bind("raw_contact_id", "i", raw_id),
            "--bind", _content_bind(
                "mimetype", "s", "vnd.android.cursor.item/phone_v2"),
            "--bind", _content_bind("data1", "s", contact.number),
            "--bind", _content_bind("data2", "i", 2),
        )
        used_raw_ids.add(raw_id)
        existing += f"\n{contact.name} {contact.number}"
    _deduplicate_seed_contact_rows(manifest, adb)


def _deduplicate_seed_contact_rows(
    manifest: SeedManifest,
    adb: AdbClient,
) -> None:
    raw = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.contacts/raw_contacts", "--projection",
        "_id:account_name:account_type", check=False)
    raw_ids = {
        match.group(1)
        for line in raw.splitlines()
        if "account_name=GUITRAVERSE" in line
        for match in [re.search(r"_id=(\d+)", line)]
        if match is not None
    }
    data = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.contacts/data", "--projection",
        "_id:raw_contact_id:mimetype:data1", check=False)
    allowed_values = {
        "vnd.android.cursor.item/name": {
            contact.name for contact in manifest.contacts},
        "vnd.android.cursor.item/phone_v2": {
            contact.number for contact in manifest.contacts},
    }
    groups: dict[tuple[str, str, str], list[int]] = {}
    for line in data.splitlines():
        data_id = re.search(r"(?:^| )_id=(\d+)", line)
        raw_id = re.search(r"raw_contact_id=(\d+)", line)
        mimetype = re.search(r"mimetype=([^,]+)", line)
        value = re.search(r"data1=(.*)$", line)
        if not all((data_id, raw_id, mimetype, value)):
            continue
        raw_value = raw_id.group(1)
        mime_value = mimetype.group(1)
        data_value = value.group(1)
        if (raw_value not in raw_ids
                or data_value not in allowed_values.get(mime_value, set())):
            continue
        groups.setdefault(
            (raw_value, mime_value, data_value), []).append(
                int(data_id.group(1)))
    for ids in groups.values():
        for duplicate_id in sorted(ids)[1:]:
            adb.run(
                "shell", "content", "delete", "--uri",
                "content://com.android.contacts/data", "--where",
                f"_id={duplicate_id}")


def _push_assets(manifest: SeedManifest, adb: AdbClient, assets: Mapping[str, Path]) -> None:
    for relative, local in assets.items():
        remote = f"/sdcard/{relative}"
        adb.run("shell", "mkdir", "-p", str(PurePosixPath(remote).parent))
        adb.push(local, remote)


def _apply_messages(manifest: SeedManifest, adb: AdbClient) -> None:
    existing = adb.run(
        "shell", "content", "query", "--uri", "content://sms/inbox",
        "--projection", "address:body", check=False)
    for message in manifest.messages:
        if message.sender in existing and message.body in existing:
            continue
        adb.run("emu", "sms", "send", message.sender, message.body)


def _calendar_id(adb: AdbClient) -> str:
    output = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.calendar/calendars", "--projection",
        "_id:account_name:calendar_displayName", check=False)
    match = re.search(
        r"_id=(\d+)[^\n]*(?:account_name|calendar_displayName)=GUITRAVERSE",
        output,
    )
    if match:
        return match.group(1)
    uri = (
        "content://com.android.calendar/calendars?caller_is_syncadapter=true"
        "&account_name=GUITRAVERSE&account_type=LOCAL"
    )
    adb.run(
        "shell", "content", "insert", "--uri", shlex.quote(uri),
        "--bind", _content_bind("account_name", "s", "GUITRAVERSE"),
        "--bind", _content_bind("account_type", "s", "LOCAL"),
        "--bind", _content_bind("name", "s", "GUITRAVERSE"),
        "--bind", _content_bind(
            "calendar_displayName", "s", "GUITRAVERSE"),
        "--bind", _content_bind("calendar_color", "i", -12627531),
        "--bind", _content_bind("calendar_access_level", "i", 700),
        "--bind", _content_bind("ownerAccount", "s", "GUITRAVERSE"),
        "--bind", _content_bind("visible", "i", 1),
        "--bind", _content_bind("sync_events", "i", 1),
    )
    output = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.calendar/calendars", "--projection",
        "_id:account_name:calendar_displayName")
    match = re.search(r"_id=(\d+)[^\n]*GUITRAVERSE", output)
    if match is None:
        raise DeviceGuardError("calendar provider did not return the seed calendar id")
    return match.group(1)


def _apply_calendar(manifest: SeedManifest, adb: AdbClient) -> None:
    existing = adb.run(
        "shell", "content", "query", "--uri",
        "content://com.android.calendar/events", "--projection", "title",
        check=False)
    calendar_id = _calendar_id(adb)
    today = dt.datetime.now(dt.timezone.utc).date()
    for event in manifest.calendar:
        if event.title in existing:
            continue
        start = dt.datetime.combine(
            today + dt.timedelta(days=event.offset_days),
            dt.time(event.hour, 0), tzinfo=dt.timezone.utc)
        end = start + dt.timedelta(minutes=event.duration_minutes)
        adb.run(
            "shell", "content", "insert", "--uri",
            "content://com.android.calendar/events",
            "--bind", _content_bind("calendar_id", "i", calendar_id),
            "--bind", _content_bind("title", "s", event.title),
            "--bind", _content_bind(
                "dtstart", "l", round(start.timestamp() * 1000)),
            "--bind", _content_bind(
                "dtend", "l", round(end.timestamp() * 1000)),
            "--bind", _content_bind("eventTimezone", "s", "UTC"),
        )


def _scan_media(manifest: SeedManifest, adb: AdbClient) -> None:
    for relative in [item.path for item in manifest.files] + [
            item.path for item in manifest.photos]:
        adb.run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
            f"file:///sdcard/{relative}", check=False)


def apply_seed(
    manifest: SeedManifest,
    adb: AdbClient,
    *,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != manifest.profile:
        raise DeviceGuardError(
            f"apply confirmation must exactly equal {manifest.profile}")
    identity = preflight_device(manifest, adb)
    with tempfile.TemporaryDirectory(prefix="guitraverse_seed_") as directory:
        assets = _local_assets(manifest, Path(directory))
        _apply_system(manifest, adb)
        _apply_contacts(manifest, adb)
        _push_assets(manifest, adb, assets)
        _apply_messages(manifest, adb)
        _apply_calendar(manifest, adb)
        _scan_media(manifest, adb)
    result = verify_seed(manifest, adb)
    result["applied_to"] = asdict(identity)
    return result


def _snapshot(
    manifest: SeedManifest,
    adb: AdbClient,
    *,
    action: str,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != manifest.snapshot_name:
        raise DeviceGuardError(
            f"snapshot confirmation must exactly equal {manifest.snapshot_name}")
    identity = preflight_device(manifest, adb)
    adb.run("emu", "avd", "snapshot", action, manifest.snapshot_name, timeout=180)
    snapshots = adb.run("emu", "avd", "snapshot", "list", timeout=60)
    return {
        "schema": "guitraverse.mobile_seed.snapshot.v1",
        "action": action,
        "snapshot_name": manifest.snapshot_name,
        "device": asdict(identity),
        "listed": manifest.snapshot_name in snapshots,
    }


def save_snapshot(
    manifest: SeedManifest, adb: AdbClient, *, confirmation: str,
) -> dict[str, Any]:
    return _snapshot(
        manifest, adb, action="save", confirmation=confirmation)


def load_snapshot(
    manifest: SeedManifest, adb: AdbClient, *, confirmation: str,
) -> dict[str, Any]:
    return _snapshot(
        manifest, adb, action="load", confirmation=confirmation)
