"""Fail-closed local APK download, inspection, lock rendering and install."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

import yaml

from .androidworld_apps import AndroidWorldApkSource
from .contracts import ApkLockEntry, DeviceGuardError, SeedContext


_GCS_PREFIX = "https://storage.googleapis.com/gresearch/android_world/"
_PACKAGE = re.compile(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'")
_SDK = re.compile(r"^(sdkVersion|targetSdkVersion):'?(\d+)'?", re.MULTILINE)
_ABI = re.compile(r"^native-code:\s*(.*)$", re.MULTILINE)
_QUOTED = re.compile(r"'([^']+)'")
_SIGNER = re.compile(r"certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class DownloadError(RuntimeError):
    pass


class MetadataError(RuntimeError):
    pass


class InstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedApk:
    source: AndroidWorldApkSource
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class InspectedApk:
    package: str
    version_name: str
    version_code: int
    min_sdk: int
    target_sdk: int
    abis: tuple[str, ...]
    signer_sha256: str


@dataclass(frozen=True)
class InstallResult:
    package: str
    version_name: str
    version_code: int
    apk_path: str


def _valid_source_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and url.startswith(_GCS_PREFIX)


def _digest(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _matches_expected(source: AndroidWorldApkSource, size: int, digest: str) -> bool:
    return ((not source.expected_size_bytes or source.expected_size_bytes == size)
            and (not source.expected_sha256 or source.expected_sha256 == digest))


def _close(response: object) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def download_apks(
    source_specs: Sequence[AndroidWorldApkSource],
    cache_root: str | Path,
    opener: Callable[[str], object] = urlopen,
) -> tuple[DownloadedApk, ...]:
    """Download official objects atomically, re-hashing every cache hit."""
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    downloaded: list[DownloadedApk] = []
    for source in source_specs:
        if not _valid_source_url(source.gcs_object):
            raise DownloadError("APK source must be the official AndroidWorld HTTPS prefix")
        target = root / source.filename
        if target.exists():
            size, digest = _digest(target)
            if _matches_expected(source, size, digest):
                downloaded.append(DownloadedApk(source, target, size, digest))
                continue
        temporary: Path | None = None
        response = None
        try:
            response = opener(source.gcs_object)
            final_url = getattr(response, "geturl", lambda: source.gcs_object)()
            if not isinstance(final_url, str) or not _valid_source_url(final_url):
                raise DownloadError("APK redirect left the official AndroidWorld prefix")
            with NamedTemporaryFile("wb", delete=False, dir=root, prefix=f".{source.filename}.", suffix=".part") as handle:
                temporary = Path(handle.name)
                while chunk := getattr(response, "read")(1024 * 1024):
                    handle.write(chunk)
            size, digest = _digest(temporary)
            if not _matches_expected(source, size, digest):
                raise DownloadError("downloaded APK size or SHA-256 does not match expected metadata")
            temporary.replace(target)
            temporary = None
            downloaded.append(DownloadedApk(source, target, size, digest))
        except DownloadError:
            raise
        except OSError as exc:
            raise DownloadError(f"APK download failed for {source.filename}: {exc}") from exc
        finally:
            _close(response)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return tuple(downloaded)


def _tool(sdk_tools: Mapping[str, str] | str | Path, name: str) -> str:
    if isinstance(sdk_tools, Mapping):
        try:
            return str(sdk_tools[name])
        except KeyError as exc:
            raise MetadataError(f"missing SDK tool: {name}") from exc
    return str(Path(sdk_tools) / name)


def _run(runner: Callable[..., subprocess.CompletedProcess[str]], argv: list[str]) -> str:
    result = runner(argv, capture_output=True, text=True, timeout=60)
    output = f"{result.stdout or ''}{result.stderr or ''}"
    if result.returncode != 0:
        raise MetadataError(f"SDK command failed ({Path(argv[0]).name}): {output.strip()[:300]}")
    return output


def _native_abis(path: Path, badging: str) -> tuple[str, ...]:
    native = _ABI.search(badging)
    if native:
        values = tuple(_QUOTED.findall(native.group(1)))
        if values:
            return values
        raise MetadataError("aapt native-code metadata is invalid")
    try:
        with zipfile.ZipFile(path) as archive:
            native_libs = [name for name in archive.namelist() if name.startswith("lib/") and name.endswith(".so")]
    except zipfile.BadZipFile as exc:
        raise MetadataError("APK is not a readable zip archive") from exc
    if native_libs:
        raise MetadataError("APK has native libraries but aapt reported no native ABI")
    return ()


def inspect_apk(
    path: str | Path,
    sdk_tools: Mapping[str, str] | str | Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InspectedApk:
    apk = Path(path)
    badging = _run(runner, [_tool(sdk_tools, "aapt"), "dump", "badging", str(apk)])
    package = _PACKAGE.search(badging)
    sdk_values = dict(_SDK.findall(badging))
    if not package or set(sdk_values) != {"sdkVersion", "targetSdkVersion"}:
        raise MetadataError("aapt package/version/SDK metadata is incomplete")
    signer_output = _run(runner, [_tool(sdk_tools, "apksigner"), "verify", "--print-certs", str(apk)])
    signer = _SIGNER.search(signer_output)
    signer_sha = signer.group(1).replace(":", "").lower() if signer else ""
    if not _SHA256.fullmatch(signer_sha):
        raise MetadataError("apksigner SHA-256 signer metadata is incomplete")
    return InspectedApk(
        package.group(1), package.group(3), int(package.group(2)), int(sdk_values["sdkVersion"]),
        int(sdk_values["targetSdkVersion"]), _native_abis(apk, badging), signer_sha)


def _complete_entry(entry: ApkLockEntry) -> bool:
    values = asdict(entry)
    required = ("adapter_id", "display_name", "gcs_object", "sha256", "size_bytes", "package", "version_name",
                "version_code", "signer_sha256", "min_sdk", "target_sdk", "upstream_url", "upstream_revision",
                "spdx_license", "trademark_note", "verified_at")
    return (all(values[name] for name in required)
            and isinstance(values["size_bytes"], int) and values["size_bytes"] > 0
            and isinstance(values["version_code"], int) and values["version_code"] > 0
            and isinstance(values["min_sdk"], int) and values["min_sdk"] > 0
            and isinstance(values["target_sdk"], int) and values["target_sdk"] > 0
            and isinstance(values["redistributable"], bool)
            and isinstance(values["abis"], tuple)
            and all(isinstance(abi, str) and abi for abi in values["abis"])
            and len(set(values["abis"])) == len(values["abis"])
            and _SHA256.fullmatch(values["sha256"]) is not None
            and _SHA256.fullmatch(values["signer_sha256"]) is not None)


def render_lock(entries: Sequence[ApkLockEntry]) -> str:
    """Render only already-complete lock records; never infer legal fields."""
    if not entries or any(not isinstance(entry, ApkLockEntry) or not _complete_entry(entry) for entry in entries):
        raise MetadataError("render_lock requires complete ApkLockEntry values")
    payload = {
        "schema": "guitraverse.mobile_apps_lock.v2",
        "release_id": "guitraverse_mobile_seed_v2",
        "state": "locked",
        "entries": [asdict(entry) | {"abis": list(entry.abis)} for entry in entries],
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def verify_locked_apk(
    entry: ApkLockEntry,
    path: str | Path,
    sdk_tools: Mapping[str, str] | str | Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InspectedApk:
    if not isinstance(entry, ApkLockEntry) or not _complete_entry(entry):
        raise MetadataError("verify_locked_apk requires a complete ApkLockEntry")
    apk = Path(path)
    if not apk.is_file():
        raise MetadataError("locked APK file is missing")
    size, digest = _digest(apk)
    if size != entry.size_bytes:
        raise MetadataError("APK size mismatch")
    if digest != entry.sha256:
        raise MetadataError("APK SHA-256 mismatch")
    inspected = inspect_apk(apk, sdk_tools, runner=runner)
    checks = {
        "package": (inspected.package, entry.package),
        "version_name": (inspected.version_name, entry.version_name),
        "version_code": (inspected.version_code, entry.version_code),
        "min_sdk": (inspected.min_sdk, entry.min_sdk),
        "target_sdk": (inspected.target_sdk, entry.target_sdk),
        "abis": (inspected.abis, entry.abis),
        "signer": (inspected.signer_sha256, entry.signer_sha256),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise MetadataError(f"APK {label} mismatch")
    return inspected


def install_locked_apk(
    entry: ApkLockEntry,
    path: str | Path,
    context: SeedContext,
    adb,
    sdk_tools: Mapping[str, str] | str | Path,
    confirmation: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InstallResult:
    if confirmation != "guitraverse_mobile_seed_v2":
        raise InstallError("install confirmation must be guitraverse_mobile_seed_v2")
    if context.release_id != "guitraverse_mobile_seed_v2":
        raise InstallError("install context must be guitraverse_mobile_seed_v2")
    inspected = verify_locked_apk(entry, path, sdk_tools, runner=runner)
    adb.run("install", "-r", str(path))
    package_path = adb.run("shell", "pm", "path", entry.package, check=False)
    if not any(line.startswith("package:") for line in package_path.splitlines()):
        raise InstallError("pm path did not confirm the installed package")
    dumpsys = adb.run("shell", "dumpsys", "package", entry.package, check=False)
    if (entry.package not in dumpsys or f"versionName={inspected.version_name}" not in dumpsys
            or not re.search(rf"versionCode={re.escape(str(inspected.version_code))}(?:\s|$)", dumpsys)):
        raise InstallError("dumpsys package metadata does not match locked APK")
    return InstallResult(entry.package, inspected.version_name, inspected.version_code, str(path))
