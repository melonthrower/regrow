#!/usr/bin/env python3
"""Loopback-only Android screenshot mirror with fixed ADB input commands."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import sys
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit


MAX_JSON_BODY = 8_192
MAX_COORDINATE = 10_000
MIN_SWIPE_DURATION_MS = 1
MAX_SWIPE_DURATION_MS = 10_000
KEYEVENTS = {"back": "4", "home": "3", "recents": "187"}


class MirrorError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


Runner = Callable[[Sequence[str], float], Any]


def subprocess_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=timeout, shell=False,
        )
    except FileNotFoundError as exc:
        raise MirrorError(f"ADB executable not found: {argv[0]}", 502) from exc
    except subprocess.TimeoutExpired as exc:
        raise MirrorError(f"ADB timed out after {timeout:g} seconds", 504) from exc
    except OSError as exc:
        raise MirrorError(f"ADB could not start: {exc}", 502) from exc


class AdbClient:
    def __init__(self, adb: str, serial: str, runner: Runner = subprocess_runner):
        self.adb = adb
        self.serial = serial
        self.runner = runner

    def _run(self, *command: str, binary: bool = False) -> bytes:
        argv = [self.adb, "-s", self.serial, *command]
        result = self.runner(argv, 15.0)
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", "replace").strip() or "unknown ADB error"
            raise MirrorError(f"ADB failed: {error}", 502)
        return result.stdout if binary else b""

    def frame(self) -> bytes:
        return self._run("exec-out", "screencap", "-p", binary=True)

    def tap(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self._run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def key(self, name: str) -> None:
        self._run("shell", "input", "keyevent", KEYEVENTS[name])


def _json_object(body: bytes, expected_keys: set[str]) -> dict[str, Any]:
    if len(body) > MAX_JSON_BODY:
        raise MirrorError("JSON body is too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MirrorError("Request body must be a JSON object") from exc
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise MirrorError("Request payload has invalid fields")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MirrorError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _page(refresh_ms: int) -> bytes:
    return f"""<!doctype html>
<meta charset=\"utf-8\">
<title>Android mirror</title>
<style>
html, body {{ height: 100%; margin: 0; }}
body {{ font-family: sans-serif; box-sizing: border-box; padding: 8px;
       display: flex; flex-direction: column; gap: 8px; align-items: center; }}
#controls {{ flex: 0 0 auto; display: flex; gap: 8px; }}
#screen {{ flex: 1 1 0; min-height: 0; width: 100%; display: flex;
           align-items: center; justify-content: center; }}
#frame {{ display: block; width: auto; height: auto; max-width: 100%; max-height: 100%;
          touch-action: none; user-select: none; }}
button {{ padding: 6px 12px; }}
</style>
<div id=\"controls\"><button data-key=\"back\">Back</button><button data-key=\"home\">Home</button><button data-key=\"recents\">Recents</button></div>
<div id=\"screen\"><img id=\"frame\" alt=\"Android screen\"></div>
<script>
const image = document.querySelector('#frame');
let start = null;
const post = (path, payload) => fetch(path, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload)}});
const point = event => {{
  const box = image.getBoundingClientRect();
  return {{x: Math.round((event.clientX - box.left) * image.naturalWidth / box.width), y: Math.round((event.clientY - box.top) * image.naturalHeight / box.height)}};
}};
const refresh = () => {{ image.src = '/frame.png?t=' + Date.now(); }};
image.addEventListener('pointerdown', event => {{ start = point(event); image.setPointerCapture(event.pointerId); event.preventDefault(); }});
image.addEventListener('pointerup', event => {{
  if (!start) return;
  const end = point(event), moved = Math.abs(end.x - start.x) + Math.abs(end.y - start.y) > 10;
  post(moved ? '/swipe' : '/tap', moved ? {{x1: start.x, y1: start.y, x2: end.x, y2: end.y, duration_ms: 300}} : start);
  start = null;
}});
image.addEventListener('wheel', event => {{
  event.preventDefault();
  const from = point(event), distance = Math.max(100, Math.round(image.naturalHeight * 0.3));
  const to = {{x: from.x, y: Math.max(0, Math.min(image.naturalHeight, from.y + (event.deltaY > 0 ? -distance : distance)))}};
  post('/swipe', {{x1: from.x, y1: from.y, x2: to.x, y2: to.y, duration_ms: 250}});
}}, {{passive: false}});
document.querySelectorAll('[data-key]').forEach(button => button.addEventListener('click', () => post('/key', {{key: button.dataset.key}})));
refresh(); setInterval(refresh, {refresh_ms});
</script>""".encode("utf-8")


class MirrorService:
    def __init__(self, client: AdbClient, refresh_ms: int):
        self.client = client
        self.refresh_ms = refresh_ms

    def handle(self, method: str, path: str, body: bytes) -> tuple[int, str, bytes]:
        try:
            if method == "GET" and path == "/":
                return 200, "text/html; charset=utf-8", _page(self.refresh_ms)
            if method == "GET" and path == "/frame.png":
                return 200, "image/png", self.client.frame()
            if method == "POST" and path == "/tap":
                payload = _json_object(body, {"x", "y"})
                self.client.tap(
                    _integer(payload["x"], "x", 0, MAX_COORDINATE),
                    _integer(payload["y"], "y", 0, MAX_COORDINATE),
                )
                return 204, "text/plain; charset=utf-8", b""
            if method == "POST" and path == "/swipe":
                payload = _json_object(body, {"x1", "y1", "x2", "y2", "duration_ms"})
                self.client.swipe(
                    _integer(payload["x1"], "x1", 0, MAX_COORDINATE),
                    _integer(payload["y1"], "y1", 0, MAX_COORDINATE),
                    _integer(payload["x2"], "x2", 0, MAX_COORDINATE),
                    _integer(payload["y2"], "y2", 0, MAX_COORDINATE),
                    _integer(payload["duration_ms"], "duration_ms", MIN_SWIPE_DURATION_MS, MAX_SWIPE_DURATION_MS),
                )
                return 204, "text/plain; charset=utf-8", b""
            if method == "POST" and path == "/key":
                payload = _json_object(body, {"key"})
                if payload["key"] not in KEYEVENTS:
                    raise MirrorError("key must be back, home, or recents")
                self.client.key(payload["key"])
                return 204, "text/plain; charset=utf-8", b""
            raise MirrorError("Endpoint not found", 404)
        except MirrorError as exc:
            return exc.status, "text/plain; charset=utf-8", str(exc).encode("utf-8")


def make_handler(service: MirrorService):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise MirrorError("Content-Length must be an integer") from exc
            if length < 0 or length > MAX_JSON_BODY:
                raise MirrorError("JSON body is too large")
            return self.rfile.read(length)

        def do_GET(self) -> None:
            self._respond(*service.handle("GET", urlsplit(self.path).path, b""))

        def do_POST(self) -> None:
            try:
                body = self._body()
            except MirrorError as exc:
                self._respond(exc.status, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                return
            self._respond(*service.handle("POST", urlsplit(self.path).path, body))

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def make_server(service: MirrorService, host: str, port: int) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise MirrorError("--host must be 127.0.0.1 or localhost")
    if not 0 <= port <= 65535:
        raise MirrorError("--port must be from 0 to 65535")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror one Android device in a loopback-only web page.")
    parser.add_argument("--adb", required=True, help="ADB executable path")
    parser.add_argument("--serial", required=True, help="Android device serial")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost (default: 127.0.0.1)")
    parser.add_argument("--port", required=True, type=int, help="loopback TCP port")
    parser.add_argument("--refresh-ms", default=500, type=int, help="frame refresh interval (default: 500)")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("--host must be 127.0.0.1 or localhost")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be from 0 to 65535")
    if not 100 <= args.refresh_ms <= 10_000:
        parser.error("--refresh-ms must be from 100 to 10000")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        server = make_server(MirrorService(AdbClient(args.adb, args.serial), args.refresh_ms), args.host, args.port)
        print(f"Android mirror listening at http://127.0.0.1:{server.server_address[1]}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            server.server_close()
        return 0
    except MirrorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
