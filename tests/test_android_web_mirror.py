from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "android_web_mirror.py"


def load_mirror():
    assert MODULE_PATH.exists(), "android_web_mirror.py is missing"
    spec = importlib.util.spec_from_file_location("android_web_mirror", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    def __init__(self, *, stdout: bytes = b"\x89PNG\r\n\x1a\nframe", stderr: bytes = b"", returncode: int = 0):
        self.calls: list[list[str]] = []
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        return SimpleNamespace(stdout=self.stdout, stderr=self.stderr, returncode=self.returncode)


def service(runner: FakeRunner, refresh_ms: int = 275):
    mirror = load_mirror()
    client = mirror.AdbClient("custom-adb", "serial-X", runner=runner)
    return mirror.MirrorService(client, refresh_ms=refresh_ms)


def test_frame_tap_swipe_and_key_use_only_fixed_adb_argv():
    runner = FakeRunner()
    app = service(runner)

    status, content_type, frame = app.handle("GET", "/frame.png", b"")
    assert (status, content_type, frame) == (200, "image/png", b"\x89PNG\r\n\x1a\nframe")

    assert app.handle("POST", "/tap", b'{"x":12,"y":34}')[0] == 204
    assert app.handle("POST", "/swipe", b'{"x1":1,"y1":190,"x2":2,"y2":20,"duration_ms":450}')[0] == 204
    assert app.handle("POST", "/key", b'{"key":"home"}')[0] == 204

    assert runner.calls == [
        ["custom-adb", "-s", "serial-X", "exec-out", "screencap", "-p"],
        ["custom-adb", "-s", "serial-X", "shell", "input", "tap", "12", "34"],
        ["custom-adb", "-s", "serial-X", "shell", "input", "swipe", "1", "190", "2", "20", "450"],
        ["custom-adb", "-s", "serial-X", "shell", "input", "keyevent", "3"],
    ]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/tap", {"x": -1, "y": 5}),
        ("/tap", {"x": True, "y": 5}),
        ("/tap", {"x": 5, "y": 6, "shell": "rm -rf /"}),
        ("/swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 0}),
        ("/swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 10001}),
        ("/key", {"key": "volume_up"}),
    ],
)
def test_invalid_input_payloads_are_rejected_without_running_adb(path, payload):
    runner = FakeRunner()
    status, content_type, body = service(runner).handle("POST", path, json.dumps(payload).encode())

    assert status == 400
    assert content_type == "text/plain; charset=utf-8"
    assert body
    assert runner.calls == []


def test_html_endpoint_contains_refresh_and_all_input_controls():
    status, content_type, body = service(FakeRunner(), refresh_ms=275).handle("GET", "/", b"")
    html = body.decode("utf-8")

    assert (status, content_type) == (200, "text/html; charset=utf-8")
    assert "/frame.png" in html
    assert "/tap" in html
    assert "/swipe" in html
    assert "Back" in html
    assert "Home" in html
    assert "Recents" in html
    assert "275" in html
    assert "event.deltaY > 0 ? -distance : distance" in html


def test_adb_failure_is_returned_as_a_clear_gateway_error():
    runner = FakeRunner(stderr=b"device offline", returncode=1)
    status, content_type, body = service(runner).handle("GET", "/frame.png", b"")

    assert (status, content_type) == (502, "text/plain; charset=utf-8")
    assert "ADB failed: device offline" in body.decode("utf-8")


def test_parser_defaults_to_loopback_and_rejects_non_loopback_hosts():
    mirror = load_mirror()

    args = mirror.parse_args(["--adb", "fake-adb", "--serial", "serial-X", "--port", "8765"])
    assert (args.host, args.refresh_ms) == ("127.0.0.1", 500)
    with pytest.raises(SystemExit):
        mirror.parse_args([
            "--adb", "fake-adb", "--serial", "serial-X", "--port", "8765", "--host", "0.0.0.0"
        ])
