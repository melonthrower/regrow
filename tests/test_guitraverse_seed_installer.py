from __future__ import annotations

import hashlib
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from tools.guitraverse_seed.androidworld_apps import ANDROIDWORLD_APPS, VLC_ALTERNATE_CANDIDATE
from tools.guitraverse_seed.contracts import ApkLockEntry, DeviceGuardError, SeedContext
from tools.guitraverse_seed.installer import (
    DownloadError,
    InstallError,
    MetadataError,
    download_apks,
    inspect_apk,
    install_locked_apk,
    render_lock,
    verify_locked_apk,
)


class _Response:
    def __init__(self, body: bytes, url: str, *, fail: bool = False) -> None:
        self.body = body
        self.url = url
        self.fail = fail
        self.closed = False

    def read(self, _size: int = -1) -> bytes:
        if self.fail:
            raise OSError("fixture download failed")
        value, self.body = self.body, b""
        return value

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        self.closed = True


def _apk(path: Path, *, native: bool = True) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if native:
            archive.writestr("lib/x86_64/libfixture.so", b"fixture")
        archive.writestr("classes.dex", b"dex")
    return path


def _entry(path: Path) -> ApkLockEntry:
    payload = path.read_bytes()
    return ApkLockEntry(
        "markor", "Markor", "https://storage.googleapis.com/gresearch/android_world/markor.apk",
        hashlib.sha256(payload).hexdigest(), len(payload), "net.gsantner.markor", "2.0", 146,
        "a" * 64, ("x86_64",), 23, 33, "https://example.org/markor", "v2.0",
        "Apache-2.0", True, "Fixture only.", "2026-08-30T12:00:00Z",
    )


def _runner(*, package="net.gsantner.markor", version_name="2.0", version_code=146,
            min_sdk=23, target_sdk=33, abis=("x86_64",), signer="a" * 64):
    def run(argv, **_kwargs):
        command = tuple(map(str, argv))
        if command[1:3] == ("dump", "badging"):
            native = "" if not abis else "\nnative-code: " + " ".join(f"'{abi}'" for abi in abis)
            return subprocess.CompletedProcess(command, 0, (
                f"package: name='{package}' versionCode='{version_code}' versionName='{version_name}'\n"
                f"sdkVersion:'{min_sdk}'\ntargetSdkVersion:'{target_sdk}'{native}\n"), "")
        if command[1:3] == ("verify", "--print-certs"):
            digest = ":".join(signer[index:index + 2] for index in range(0, len(signer), 2))
            return subprocess.CompletedProcess(command, 0, f"Signer #1 certificate SHA-256 digest: {digest}\n", "")
        raise AssertionError(f"unexpected SDK command: {command}")
    return run


def test_exact_androidworld_registry_and_vlc_alternate_are_explicit():
    assert [(item.adapter_id, item.package, item.filename) for item in ANDROIDWORLD_APPS] == [
        ("markor", "net.gsantner.markor", "net.gsantner.markor_146.apk"),
        ("clipper", "ca.zgrs.clipper", "clipper.apk"),
        ("simple_calendar", "com.simplemobiletools.calendar.pro", "com.simplemobiletools.calendar.pro_238.apk"),
        ("tasks_org", "org.tasks", "org.tasks_130605.apk"),
        ("simple_draw", "com.simplemobiletools.draw.pro", "com.simplemobiletools.draw.pro_79.apk"),
        ("simple_gallery", "com.simplemobiletools.gallery.pro", "com.simplemobiletools.gallery.pro_396.apk"),
        ("simple_sms", "com.simplemobiletools.smsmessenger", "com.simplemobiletools.smsmessenger_85.apk"),
        ("audio_recorder", "com.dimowner.audiorecorder", "com.dimowner.audiorecorder_926.apk"),
        ("miniwob", "com.google.androidenv.miniwob", "miniwobapp.apk"),
        ("pro_expense", "com.arduia.expense", "com.arduia.expense_11.apk"),
        ("broccoli", "com.flauschcode.broccoli", "com.flauschcode.broccoli_1020600.apk"),
        ("osmand", "net.osmand", "net.osmand-4.6.13.apk"),
        ("open_tracks", "de.dennisguse.opentracks", "de.dennisguse.opentracks_5705.apk"),
        ("vlc", "org.videolan.vlc", "org.videolan.vlc_13050408.apk"),
        ("joplin", "net.cozic.joplin", "net.cozic.joplin_2097740.apk"),
        ("retro_music", "code.name.monkey.retromusic", "code.name.monkey.retromusic_10603.apk"),
    ]
    assert VLC_ALTERNATE_CANDIDATE.filename == "org.videolan.vlc_13050407.apk"
    assert all(item.gcs_object.startswith("https://storage.googleapis.com/gresearch/android_world/") for item in ANDROIDWORLD_APPS)


def test_download_rejects_redirect_outside_androidworld_prefix(tmp_path):
    spec = ANDROIDWORLD_APPS[0]
    with pytest.raises(DownloadError, match="redirect"):
        download_apks((spec,), tmp_path, opener=lambda _url: _Response(b"apk", "https://example.org/markor.apk"))
    assert not list(tmp_path.glob("*.apk"))


def test_failed_download_never_promotes_temp_file(tmp_path):
    spec = ANDROIDWORLD_APPS[0]
    with pytest.raises(DownloadError, match="download"):
        download_apks((spec,), tmp_path, opener=lambda url: _Response(b"partial", url, fail=True))
    assert not list(tmp_path.iterdir())


def test_cached_hash_mismatch_redownloads_before_returning(tmp_path):
    spec = replace(ANDROIDWORLD_APPS[0], expected_sha256=hashlib.sha256(b"fresh").hexdigest(), expected_size_bytes=5)
    (tmp_path / spec.filename).write_bytes(b"stale")
    result = download_apks((spec,), tmp_path, opener=lambda url: _Response(b"fresh", url))
    assert result[0].path.read_bytes() == b"fresh"


def test_inspection_parses_badging_and_signer_metadata(tmp_path):
    path = _apk(tmp_path / "fixture.apk")
    inspected = inspect_apk(path, {"aapt": "aapt", "apksigner": "apksigner"}, runner=_runner())
    assert (inspected.package, inspected.version_name, inspected.version_code) == ("net.gsantner.markor", "2.0", 146)
    assert (inspected.min_sdk, inspected.target_sdk, inspected.abis, inspected.signer_sha256) == (23, 33, ("x86_64",), "a" * 64)


def test_verify_stops_before_inspection_when_size_or_hash_mismatches(tmp_path):
    path = _apk(tmp_path / "fixture.apk")
    runner_called = False
    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("inspection must not run")
    with pytest.raises(MetadataError, match="size"):
        verify_locked_apk(replace(_entry(path), size_bytes=path.stat().st_size + 1), path, {}, runner=runner)
    assert not runner_called


@pytest.mark.parametrize("field,value", [("package", "other.package"), ("version_name", "3.0"), ("min_sdk", 24), ("abis", ("x86",)), ("signer_sha256", "b" * 64)])
def test_verify_rejects_aapt_or_signer_metadata_mismatch(tmp_path, field, value):
    path = _apk(tmp_path / "fixture.apk")
    with pytest.raises(MetadataError, match=field.split("_")[0]):
        verify_locked_apk(replace(_entry(path), **{field: value}), path, {"aapt": "aapt", "apksigner": "apksigner"}, runner=_runner())


class _Adb:
    def __init__(self, *, install_ok=True, pm_path="package:/data/app/markor.apk\n", dumpsys="Package [net.gsantner.markor] (123):\n  versionCode=146 minSdk=23 targetSdk=33\n  versionName=2.0\n"):
        self.install_ok, self.pm_path, self.dumpsys, self.calls = install_ok, pm_path, dumpsys, []
    def run(self, *args, **_kwargs):
        self.calls.append(args)
        if args[:1] == ("install",):
            if not self.install_ok:
                raise DeviceGuardError("install failed")
            return "Success\n"
        if args == ("shell", "pm", "path", "net.gsantner.markor"):
            return self.pm_path
        if args == ("shell", "dumpsys", "package", "net.gsantner.markor"):
            return self.dumpsys
        raise AssertionError(args)


def _context() -> SeedContext:
    return SeedContext("emulator-5554", "guitraverse_mobile_seed", "guitraverse_mobile_seed_v2", "a" * 64, 33, "en-US", "fixture")


def test_install_requires_exact_confirmation_before_adb(tmp_path):
    path = _apk(tmp_path / "fixture.apk")
    adb = _Adb()
    with pytest.raises(InstallError, match="confirmation"):
        install_locked_apk(_entry(path), path, _context(), adb, {}, "wrong", runner=_runner())
    assert adb.calls == []


def test_install_failure_and_missing_post_install_metadata_fail_closed(tmp_path):
    path = _apk(tmp_path / "fixture.apk")
    entry = _entry(path)
    failing = _Adb(install_ok=False)
    with pytest.raises(DeviceGuardError, match="install"):
        install_locked_apk(entry, path, _context(), failing, {"aapt": "aapt", "apksigner": "apksigner"}, "guitraverse_mobile_seed_v2", runner=_runner())
    assert failing.calls == [("install", "-r", str(path))]
    missing = _Adb(pm_path="", dumpsys="")
    with pytest.raises(InstallError, match="pm path"):
        install_locked_apk(entry, path, _context(), missing, {"aapt": "aapt", "apksigner": "apksigner"}, "guitraverse_mobile_seed_v2", runner=_runner())
    wrong_metadata = _Adb(dumpsys="Package [net.gsantner.markor] (123):\n  versionCode=999\n  versionName=9.9\n")
    with pytest.raises(InstallError, match="dumpsys"):
        install_locked_apk(entry, path, _context(), wrong_metadata, {"aapt": "aapt", "apksigner": "apksigner"}, "guitraverse_mobile_seed_v2", runner=_runner())


def test_render_lock_requires_complete_entries_and_is_deterministic(tmp_path):
    path = _apk(tmp_path / "fixture.apk")
    entry = _entry(path)
    assert render_lock((entry,)) == render_lock((entry,))
    with pytest.raises(MetadataError, match="complete"):
        render_lock((replace(entry, spdx_license=""),))


@pytest.mark.parametrize("field", ("upstream_url", "upstream_revision", "spdx_license", "trademark_note", "verified_at"))
def test_incomplete_locked_metadata_stops_before_sdk_or_adb(tmp_path, field):
    path = _apk(tmp_path / "fixture.apk")
    entry = replace(_entry(path), **{field: ""})
    runner_calls = []

    def runner(*args, **_kwargs):
        runner_calls.append(args)
        raise AssertionError("SDK inspection must not run")

    with pytest.raises(MetadataError, match="complete"):
        verify_locked_apk(entry, path, {"aapt": "aapt", "apksigner": "apksigner"}, runner=runner)
    adb = _Adb()
    with pytest.raises(MetadataError, match="complete"):
        install_locked_apk(entry, path, _context(), adb, {"aapt": "aapt", "apksigner": "apksigner"}, "guitraverse_mobile_seed_v2", runner=runner)
    assert runner_calls == []
    assert adb.calls == []
