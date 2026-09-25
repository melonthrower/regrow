from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "capture_mobile_screens.py"
SPEC = importlib.util.spec_from_file_location("capture_mobile_screens", MODULE_PATH)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def png(width: int = 1080, height: int = 2400) -> bytes:
    return (
        capture.PNG_SIGNATURE
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"fake-crc-and-data"
    )


def result(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class FakeRunner:
    def __init__(self, screenshot: bytes | None = None, devices: bytes | None = None):
        self.calls: list[list[str]] = []
        self.screenshot = screenshot if screenshot is not None else png()
        self.devices = devices if devices is not None else b"List of devices attached\nserial-1\tdevice\n"

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[-1:] == ["devices"]:
            return result(self.devices)
        if argv[-3:] == ["exec-out", "screencap", "-p"]:
            return result(self.screenshot)
        if argv[-2:] == ["shell", "getprop"]:
            return result(
                b"[ro.product.manufacturer]: [Example]\n"
                b"[ro.product.model]: [Phone]\n"
                b"[ro.build.version.release]: [14]\n"
                b"[ro.build.version.sdk]: [34]\n"
            )
        if argv[-4:] == ["shell", "dumpsys", "window", "windows"]:
            return result(b"mCurrentFocus=Window{abc u0 com.example/.MainActivity}\n")
        raise AssertionError(f"unexpected argv: {argv}")


def test_slug_and_session_name_block_path_traversal():
    assert capture.slugify(" ../../Settings / Wi-Fi ") == "settings-wi-fi"
    assert capture.slugify("中文") == "unlabeled"
    assert "/" not in capture.slugify("a/b\\c")
    with pytest.raises(capture.CaptureError):
        capture.validate_session_name("../../escape")
    with pytest.raises(capture.CaptureError):
        capture.validate_session_name("nested/session")
    assert capture.validate_session_name("pixel7.settings_01") == "pixel7.settings_01"


def test_png_validation_returns_ihdr_dimensions_and_rejects_invalid_data():
    assert capture.png_dimensions(png(321, 654)) == (321, 654)
    with pytest.raises(capture.CaptureError, match="signature"):
        capture.png_dimensions(b"not-png")
    with pytest.raises(capture.CaptureError, match="IHDR"):
        capture.png_dimensions(capture.PNG_SIGNATURE + b"\x00" * 8)
    malformed = capture.PNG_SIGNATURE + struct.pack(">I", 12) + b"IHDR" + struct.pack(">II", 1, 1)
    with pytest.raises(capture.CaptureError, match="IHDR"):
        capture.png_dimensions(malformed)


@pytest.mark.parametrize(
    ("devices", "requested", "expected", "message"),
    [
        ({}, None, None, "No online"),
        ({"one": "device"}, None, "one", None),
        ({"one": "device", "two": "device"}, None, None, "Multiple"),
        ({"one": "offline"}, "one", None, "not online"),
        ({"one": "device"}, "missing", None, "not found"),
    ],
)
def test_device_selection(devices, requested, expected, message):
    if message:
        with pytest.raises(capture.CaptureError, match=message):
            capture.select_device(devices, requested)
    else:
        assert capture.select_device(devices, requested) == expected


def test_device_parser_ignores_daemon_noise_and_tracks_offline_states():
    raw = (
        b"* daemon started successfully *\n"
        b"List of devices attached\n"
        b"good\tdevice product:x model:y\n"
        b"bad\toffline\n\n"
    )
    assert capture.parse_adb_devices(raw) == {"good": "device", "bad": "offline"}


def test_screenshot_uses_exec_out_argv_and_preserves_png_bytes():
    runner = FakeRunner(screenshot=png(10, 20))
    client = capture.AdbClient("custom-adb", serial="serial-X", runner=runner)
    assert client.capture_png() == png(10, 20)
    assert runner.calls == [["custom-adb", "-s", "serial-X", "exec-out", "screencap", "-p"]]


def test_public_tap_swipe_and_back_use_explicit_argv_without_shell_strings():
    calls = []

    def runner(argv):
        calls.append(list(argv))
        return result()

    client = capture.AdbClient("custom-adb", serial="serial-X", runner=runner)
    client.tap(12.8, 34.2)
    client.swipe(1, 190, 2, 20, 450)
    client.back()
    assert calls == [
        ["custom-adb", "-s", "serial-X", "shell", "input", "tap", "12", "34"],
        ["custom-adb", "-s", "serial-X", "shell", "input", "swipe", "1", "190", "2", "20", "450"],
        ["custom-adb", "-s", "serial-X", "shell", "input", "keyevent", "4"],
    ]


def test_first_write_resume_increment_and_existing_file_is_not_overwritten(tmp_path):
    times = iter(["2026-01-01T00:00:00.000Z", "2026-01-01T00:00:01.000Z"])
    store = capture.SessionStore(
        tmp_path,
        "session-1",
        {"serial": "serial-1", "model": "Phone"},
        prefix="shot",
        clock=lambda: next(times),
    )
    first = store.add_frame("Home / Main", png(100, 200), {"package": "pkg", "activity": "pkg.Main"})
    assert first["index"] == 1
    assert first["image"] == "images/shot_000001_home-main.png"
    assert (store.session_dir / first["image"]).read_bytes() == png(100, 200)
    sidecar = json.loads((store.session_dir / first["sidecar"]).read_text(encoding="utf-8"))
    assert sidecar["sha256"] == first["sha256"]
    assert sidecar["foreground_package"] == "pkg"

    orphan = store.images_dir / "shot_000002_home-main.png"
    orphan.write_bytes(b"do-not-overwrite")
    resumed = capture.SessionStore(
        tmp_path,
        "session-1",
        {"serial": "serial-1"},
        prefix="shot",
        clock=lambda: "2026-01-01T00:00:02.000Z",
    )
    second = resumed.add_frame("Home / Main", png(300, 400))
    assert second["index"] == 3
    assert orphan.read_bytes() == b"do-not-overwrite"
    manifest = json.loads(resumed.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == capture.SCHEMA_ID
    assert [frame["index"] for frame in manifest["frames"]] == [1, 3]


def test_resume_rejects_a_different_device(tmp_path):
    capture.SessionStore(tmp_path, "same-session", {"serial": "first"})
    with pytest.raises(capture.CaptureError, match="belongs to device"):
        capture.SessionStore(tmp_path, "same-session", {"serial": "second"})


def test_undo_removes_only_last_manifest_frame_and_its_files(tmp_path):
    store = capture.SessionStore(tmp_path, "undo-session", {"serial": "serial-1"})
    first = store.add_frame("first", png())
    second = store.add_frame("second", png())
    undone = store.undo()
    assert undone == second
    assert (store.session_dir / first["image"]).exists()
    assert not (store.session_dir / second["image"]).exists()
    assert not (store.session_dir / second["sidecar"]).exists()
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert [frame["index"] for frame in manifest["frames"]] == [1]
    assert store.undo() == first
    assert store.undo() is None


def test_capture_once_main_success_writes_dataset_without_real_adb(tmp_path):
    runner = FakeRunner(screenshot=png(720, 1280))
    output: list[str] = []
    errors: list[str] = []
    code = capture.main(
        [
            "--adb",
            "fake-adb",
            "--output-root",
            str(tmp_path),
            "--session",
            "test-session",
            "--settle-seconds",
            "0",
            "--capture-once",
            "Settings home",
        ],
        runner=runner,
        output=output.append,
        error_output=errors.append,
    )
    assert code == 0
    assert not errors
    manifest = json.loads((tmp_path / "test-session" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["frames"]) == 1
    frame = manifest["frames"][0]
    assert (frame["width"], frame["height"]) == (720, 1280)
    assert frame["foreground_package"] == "com.example"
    assert frame["foreground_activity"] == "com.example.MainActivity"


def test_capture_once_main_returns_nonzero_for_expected_device_error(tmp_path):
    runner = FakeRunner(devices=b"List of devices attached\noffline-1\toffline\n")
    errors: list[str] = []
    code = capture.main(
        ["--output-root", str(tmp_path), "--session", "failed", "--capture-once"],
        runner=runner,
        output=lambda _message: None,
        error_output=errors.append,
    )
    assert code == 2
    assert errors and "No online Android device" in errors[0]
    assert not (tmp_path / "failed").exists()


def test_interactive_plain_text_captures_and_commands_do_not_capture(tmp_path):
    runner = FakeRunner()
    client = capture.AdbClient(serial="serial-1", runner=runner)
    store = capture.SessionStore(tmp_path, "interactive", {"serial": "serial-1"})
    app = capture.CaptureApp(client, store, settle_seconds=0)
    commands = iter(["Home page", "s", "u", "q"])
    output: list[str] = []
    capture.interactive_loop(app, input_func=lambda _prompt: next(commands), output=output.append)
    assert not store.frames
    assert any("Captured" in line for line in output)
    assert any("Undid frame" in line for line in output)
