from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .contracts import (
    CalendarSeed,
    ContactSeed,
    FileSeed,
    ManifestError,
    MessageSeed,
    PhotoSeed,
    SeedManifest,
    SystemSeed,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data" / "dev_seed" / "guitraverse_mobile_seed_v1.yaml"
PROFILE_RE = re.compile(r"^guitraverse_mobile_seed_v[1-9]\d*$")
AVD_RE = re.compile(r"^guitraverse_mobile_seed$")
RESERVED_NUMBER_RE = re.compile(r"^55501\d{2}$")
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ALLOWED_DEVICE_ROOTS = {"DCIM", "Documents", "Download", "Music", "Pictures"}
FORBIDDEN_KEY_PARTS = {"api_key", "password", "secret", "token", "credential"}


def _expect_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{label} must be a mapping")
    return value


def _expect_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ManifestError(f"{label} has unsupported fields: {', '.join(unknown)}")


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ManifestError(f"{label} must be non-empty")
    return result


def _check_synthetic_text(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ManifestError(f"{label} contains credential field {key}")
            _check_synthetic_text(item, f"{label}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _check_synthetic_text(item, f"{label}[{index}]")
        return
    if not isinstance(value, str):
        return
    if re.search(r"https?://", value, flags=re.IGNORECASE):
        raise ManifestError(f"{label} contains URL")
    if re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", value):
        raise ManifestError(f"{label} contains email")


def _device_path(value: Any, label: str) -> str:
    text = _text(value, label).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ManifestError(f"{label} must be a safe relative device path")
    if path.parts[0] not in ALLOWED_DEVICE_ROOTS:
        raise ManifestError(f"{label} uses an unsupported device root")
    return str(path)


def _unique(values: Iterable[str], label: str) -> None:
    items = list(values)
    if len(items) != len(set(items)):
        raise ManifestError(f"{label} contains duplicate values")


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> SeedManifest:
    manifest_path = Path(path)
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ManifestError(f"manifest unavailable: {type(exc).__name__}") from exc
    payload = _expect_mapping(raw, "manifest")
    _expect_keys(payload, {
        "schema", "profile", "avd_name", "snapshot_name",
        "required_packages", "system", "contacts", "files", "messages",
        "calendar", "photos",
    }, "manifest")
    _check_synthetic_text(payload, "manifest")

    schema = _text(payload.get("schema"), "schema")
    if schema != "guitraverse.mobile_seed.v1":
        raise ManifestError("schema must be guitraverse.mobile_seed.v1")
    profile = _text(payload.get("profile"), "profile")
    if not PROFILE_RE.fullmatch(profile):
        raise ManifestError("profile must be versioned as guitraverse_mobile_seed_vN")
    avd_name = _text(payload.get("avd_name"), "avd_name")
    if not AVD_RE.fullmatch(avd_name):
        raise ManifestError("AVD name must be the dedicated guitraverse_mobile_seed")
    snapshot_name = _text(payload.get("snapshot_name"), "snapshot_name")
    if snapshot_name != profile or not PROFILE_RE.fullmatch(snapshot_name):
        raise ManifestError("snapshot must match the versioned profile")

    package_values = payload.get("required_packages")
    if not isinstance(package_values, list) or not package_values:
        raise ManifestError("required_packages must be a non-empty list")
    packages = tuple(_text(item, "required package") for item in package_values)
    _unique(packages, "required_packages")
    if any(not PACKAGE_RE.fullmatch(item) for item in packages):
        raise ManifestError("required package name is invalid")

    system_raw = _expect_mapping(payload.get("system"), "system")
    _expect_keys(system_raw, {"airplane_mode", "wifi", "rotation", "locale"}, "system")
    if not isinstance(system_raw.get("airplane_mode"), bool) or not isinstance(
            system_raw.get("wifi"), bool):
        raise ManifestError("system airplane_mode and wifi must be boolean")
    rotation = _text(system_raw.get("rotation"), "system.rotation")
    locale = _text(system_raw.get("locale"), "system.locale")
    if rotation != "portrait" or locale != "en-US":
        raise ManifestError("system requires portrait and en-US")
    system = SystemSeed(
        bool(system_raw["airplane_mode"]), bool(system_raw["wifi"]),
        rotation, locale,
    )

    contacts: list[ContactSeed] = []
    for index, item in enumerate(payload.get("contacts") or []):
        value = _expect_mapping(item, f"contacts[{index}]")
        _expect_keys(value, {"name", "number"}, f"contacts[{index}]")
        name = _text(value.get("name"), f"contacts[{index}].name")
        number = _text(value.get("number"), f"contacts[{index}].number")
        if not name.startswith("GUITRAVERSE Seed "):
            raise ManifestError("contact names must use the GUITRAVERSE Seed prefix")
        if not RESERVED_NUMBER_RE.fullmatch(number):
            raise ManifestError("contact number must use the reserved 55501xx range")
        contacts.append(ContactSeed(name, number))
    if not contacts:
        raise ManifestError("contacts must be non-empty")
    _unique((item.name for item in contacts), "contact names")
    _unique((item.number for item in contacts), "contact numbers")

    files: list[FileSeed] = []
    for index, item in enumerate(payload.get("files") or []):
        value = _expect_mapping(item, f"files[{index}]")
        _expect_keys(value, {"path", "kind", "content", "title"}, f"files[{index}]")
        path_value = _device_path(value.get("path"), f"files[{index}].path")
        kind = _text(value.get("kind"), f"files[{index}].kind")
        if kind not in {"text", "pdf", "image", "audio"}:
            raise ManifestError(f"files[{index}].kind is unsupported")
        content = str(value.get("content") or "")
        title = str(value.get("title") or "").strip()
        if kind == "text" and not content:
            raise ManifestError("text file content must be non-empty")
        if kind != "text" and not title.startswith("GUITRAVERSE Seed "):
            raise ManifestError("generated file title must use GUITRAVERSE Seed")
        files.append(FileSeed(path_value, kind, content, title))
    if not files:
        raise ManifestError("files must be non-empty")
    _unique((item.path for item in files), "file paths")

    contact_numbers = {item.number for item in contacts}
    messages: list[MessageSeed] = []
    for index, item in enumerate(payload.get("messages") or []):
        value = _expect_mapping(item, f"messages[{index}]")
        _expect_keys(value, {"from", "body"}, f"messages[{index}]")
        sender = _text(value.get("from"), f"messages[{index}].from")
        body = _text(value.get("body"), f"messages[{index}].body")
        if sender not in contact_numbers:
            raise ManifestError("message sender must be a reserved seed contact")
        messages.append(MessageSeed(sender, body))
    _unique((f"{item.sender}\0{item.body}" for item in messages), "messages")

    calendar: list[CalendarSeed] = []
    for index, item in enumerate(payload.get("calendar") or []):
        value = _expect_mapping(item, f"calendar[{index}]")
        _expect_keys(value, {
            "title", "offset_days", "hour", "duration_minutes",
        }, f"calendar[{index}]")
        title = _text(value.get("title"), f"calendar[{index}].title")
        if not title.startswith("GUITRAVERSE Seed "):
            raise ManifestError("calendar title must use GUITRAVERSE Seed")
        offset = int(value.get("offset_days", -1))
        hour = int(value.get("hour", -1))
        duration = int(value.get("duration_minutes", 0))
        if not 0 <= offset <= 31 or not 0 <= hour <= 23 or not 15 <= duration <= 480:
            raise ManifestError("calendar offset/hour/duration is out of range")
        calendar.append(CalendarSeed(title, offset, hour, duration))
    _unique((item.title for item in calendar), "calendar titles")

    photos: list[PhotoSeed] = []
    for index, item in enumerate(payload.get("photos") or []):
        value = _expect_mapping(item, f"photos[{index}]")
        _expect_keys(value, {"path", "label", "color"}, f"photos[{index}]")
        photo_path = _device_path(value.get("path"), f"photos[{index}].path")
        label = _text(value.get("label"), f"photos[{index}].label")
        color = _text(value.get("color"), f"photos[{index}].color")
        if not label.startswith("GUITRAVERSE Seed ") or not COLOR_RE.fullmatch(color):
            raise ManifestError("photo label/color is invalid")
        photos.append(PhotoSeed(photo_path, label, color))
    _unique((item.path for item in photos), "photo paths")
    _unique([item.path for item in files] + [item.path for item in photos], "all seed paths")

    return SeedManifest(
        schema, profile, avd_name, snapshot_name, packages, system,
        tuple(contacts), tuple(files), tuple(messages), tuple(calendar),
        tuple(photos),
    )


def canonical_manifest_digest(manifest: SeedManifest) -> str:
    encoded = json.dumps(
        asdict(manifest), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_seed_plan(manifest: SeedManifest) -> dict[str, Any]:
    return {
        "schema": "guitraverse.mobile_seed.plan.v1",
        "profile": manifest.profile,
        "avd_name": manifest.avd_name,
        "snapshot_name": manifest.snapshot_name,
        "manifest_digest": canonical_manifest_digest(manifest),
        "required_packages": list(manifest.required_packages),
        "preflight": [
            "exact local emulator serial", "exact dedicated AVD",
            "boot completed", "locale en-US", "required packages installed",
        ],
        "mutations": [
            {"kind": "system_settings", "count": 4},
            {"kind": "contacts", "count": len(manifest.contacts)},
            {"kind": "files", "count": len(manifest.files)},
            {"kind": "inbound_sms", "count": len(manifest.messages)},
            {"kind": "calendar", "count": len(manifest.calendar)},
            {"kind": "photos", "count": len(manifest.photos)},
            {"kind": "media_scan", "count": len(manifest.files) + len(manifest.photos)},
        ],
    }
