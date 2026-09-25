#!/usr/bin/env python3
"""Interactively collect Android screenshots for offline grounding evaluation.

The tool is intentionally read-only with respect to the device.  It only runs
ADB discovery, screenshot, and metadata-inspection commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
import unicodedata
from typing import Any, Callable, Mapping, Sequence


SCHEMA_ID = "gui_rewalk.mobile_grounding_capture.v1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_OUTPUT_ROOT = Path("data/imported/mobile_grounding")


class CaptureError(RuntimeError):
    """An expected, user-facing capture failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_session_name() -> str:
    return datetime.now(timezone.utc).strftime("mobile-%Y%m%dT%H%M%SZ")


def slugify(value: str, fallback: str = "unlabeled", max_length: int = 80) -> str:
    """Return an ASCII, path-safe slug suitable for a filename component."""

    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-._")
    slug = slug[:max_length].rstrip("-._")
    return slug or fallback


def validate_session_name(value: str) -> str:
    """Validate a session directory name without silently changing its identity."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value or ""):
        raise CaptureError(
            "Session must be 1-128 ASCII letters, digits, '.', '_' or '-', "
            "must start with a letter or digit, and must not contain a path."
        )
    if value in {".", ".."}:
        raise CaptureError("Session must not be '.' or '..'.")
    return value


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Validate the PNG signature and first IHDR chunk, then return its size."""

    if not isinstance(data, bytes) or not data.startswith(PNG_SIGNATURE):
        raise CaptureError("ADB screenshot is not a PNG (invalid signature).")
    if len(data) < 33:
        raise CaptureError("ADB screenshot is a truncated PNG (missing IHDR).")
    chunk_length = struct.unpack(">I", data[8:12])[0]
    if data[12:16] != b"IHDR" or chunk_length != 13:
        raise CaptureError("ADB screenshot has an invalid PNG IHDR chunk.")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise CaptureError("ADB screenshot reports an invalid image size.")
    return width, height


def parse_adb_devices(output: bytes) -> dict[str, str]:
    devices: dict[str, str] = {}
    for raw_line in output.decode("utf-8", "replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            devices[fields[0]] = fields[1]
    return devices


def select_device(devices: Mapping[str, str], requested: str | None = None) -> str:
    if requested:
        state = devices.get(requested)
        if state is None:
            raise CaptureError(f"Requested ADB device '{requested}' was not found.")
        if state != "device":
            raise CaptureError(f"Requested ADB device '{requested}' is not online (state: {state}).")
        return requested

    online = sorted(serial for serial, state in devices.items() if state == "device")
    if not online:
        raise CaptureError("No online Android device found. Check 'adb devices'.")
    if len(online) > 1:
        joined = ", ".join(online)
        raise CaptureError(f"Multiple Android devices are online ({joined}); choose one with --serial.")
    return online[0]


Runner = Callable[[Sequence[str]], Any]


def subprocess_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise CaptureError(f"ADB executable was not found: {argv[0]}") from exc
    except OSError as exc:
        raise CaptureError(f"Could not run ADB: {exc}") from exc


class AdbClient:
    def __init__(self, executable: str = "adb", serial: str | None = None, runner: Runner = subprocess_runner):
        self.executable = executable
        self.serial = serial
        self.runner = runner

    def _argv(self, *args: str, use_serial: bool = True) -> list[str]:
        argv = [self.executable]
        if use_serial and self.serial:
            argv.extend(["-s", self.serial])
        argv.extend(args)
        return argv

    def _run(self, *args: str, use_serial: bool = True, required: bool = True) -> Any:
        result = self.runner(self._argv(*args, use_serial=use_serial))
        if required and int(getattr(result, "returncode", 1)) != 0:
            stderr = getattr(result, "stderr", b"") or b""
            detail = stderr.decode("utf-8", "replace").strip()
            suffix = f": {detail}" if detail else ""
            raise CaptureError(f"ADB command failed ({' '.join(args)}){suffix}")
        return result

    def discover(self, requested: str | None = None) -> str:
        result = self._run("devices", use_serial=False)
        serial = select_device(parse_adb_devices(result.stdout), requested)
        self.serial = serial
        return serial

    def capture_png(self) -> bytes:
        result = self._run("exec-out", "screencap", "-p")
        data = bytes(result.stdout)
        png_dimensions(data)
        return data

    def tap(self, x: int, y: int) -> None:
        """Send one explicit integer-coordinate tap to the selected device."""

        self._run("shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Send one explicit integer-coordinate swipe to the selected device."""

        self._run(
            "shell", "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)),
        )

    def back(self) -> None:
        """Send one explicit Android Back key event to the selected device."""

        self._run("shell", "input", "keyevent", "4")

    def foreground(self) -> dict[str, str]:
        result = self._run("shell", "dumpsys", "window", "windows", required=False)
        if int(getattr(result, "returncode", 1)) != 0:
            return {"package": "", "activity": ""}
        text = bytes(result.stdout).decode("utf-8", "replace")
        match = re.search(r"(?:mCurrentFocus|mFocusedApp)[^\n]*?\s([A-Za-z0-9_.]+)/(\.?[A-Za-z0-9_.$]+)", text)
        if not match:
            return {"package": "", "activity": ""}
        package, activity = match.groups()
        if activity.startswith("."):
            activity = package + activity
        return {"package": package, "activity": activity}

    def device_metadata(self) -> dict[str, str]:
        metadata = {"serial": self.serial or ""}
        result = self._run("shell", "getprop", required=False)
        if int(getattr(result, "returncode", 1)) != 0:
            return metadata
        properties: dict[str, str] = {}
        for key, value in re.findall(r"^\[([^]]+)\]: \[([^]]*)\]$", bytes(result.stdout).decode("utf-8", "replace"), re.MULTILINE):
            properties[key] = value
        for output_key, property_key in (
            ("manufacturer", "ro.product.manufacturer"),
            ("model", "ro.product.model"),
            ("android_release", "ro.build.version.release"),
            ("sdk", "ro.build.version.sdk"),
        ):
            if properties.get(property_key):
                metadata[output_key] = properties[property_key]
        return metadata


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(encoded, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


class SessionStore:
    """Own a resumable session directory and its append-only frame records."""

    def __init__(
        self,
        output_root: Path,
        session: str,
        device: Mapping[str, str],
        adb_executable: str = "adb",
        prefix: str = "frame",
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.output_root = Path(output_root)
        self.session = validate_session_name(session)
        self.session_dir = self.output_root / self.session
        self.images_dir = self.session_dir / "images"
        self.frames_dir = self.session_dir / "frames"
        self.manifest_path = self.session_dir / "manifest.json"
        self.device = dict(device)
        self.prefix = slugify(prefix, fallback="frame", max_length=40)
        self.clock = clock
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_or_create(adb_executable)

    def _load_or_create(self, adb_executable: str) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CaptureError(f"Cannot resume invalid manifest: {self.manifest_path}: {exc}") from exc
            if manifest.get("schema") != SCHEMA_ID:
                raise CaptureError(f"Cannot resume manifest with unsupported schema: {manifest.get('schema')!r}")
            if manifest.get("session", {}).get("id") != self.session:
                raise CaptureError("Manifest session id does not match its directory.")
            old_serial = manifest.get("device", {}).get("serial")
            if old_serial and old_serial != self.device.get("serial"):
                raise CaptureError(
                    f"Session belongs to device '{old_serial}', not '{self.device.get('serial', '')}'."
                )
            if not isinstance(manifest.get("frames"), list):
                raise CaptureError("Manifest frames must be a list.")
            saved_prefix = manifest.get("capture", {}).get("prefix")
            if isinstance(saved_prefix, str) and saved_prefix:
                self.prefix = slugify(saved_prefix, fallback="frame", max_length=40)
            return manifest

        now = self.clock()
        manifest = {
            "schema": SCHEMA_ID,
            "session": {"id": self.session, "created_utc": now, "updated_utc": now},
            "device": self.device,
            "capture": {"adb_executable": adb_executable, "prefix": self.prefix},
            "frames": [],
        }
        _write_json_atomic(self.manifest_path, manifest)
        return manifest

    @property
    def frames(self) -> list[dict[str, Any]]:
        return self.manifest["frames"]

    @property
    def next_index(self) -> int:
        indices = [int(frame.get("index", 0)) for frame in self.frames]
        return max(indices, default=0) + 1

    def _available_paths(self, label: str) -> tuple[int, str, Path, Path]:
        index = self.next_index
        label_slug = slugify(label)
        while True:
            stem = f"{self.prefix}_{index:06d}_{label_slug}"
            image_path = self.images_dir / f"{stem}.png"
            sidecar_path = self.frames_dir / f"{stem}.json"
            if not image_path.exists() and not sidecar_path.exists():
                return index, stem, image_path, sidecar_path
            index += 1

    def add_frame(self, label: str, png: bytes, foreground: Mapping[str, str] | None = None) -> dict[str, Any]:
        width, height = png_dimensions(png)
        index, _stem, image_path, sidecar_path = self._available_paths(label)
        timestamp = self.clock()
        fg = dict(foreground or {})
        record: dict[str, Any] = {
            "index": index,
            "label": label.strip() or "unlabeled",
            "image": image_path.relative_to(self.session_dir).as_posix(),
            "sidecar": sidecar_path.relative_to(self.session_dir).as_posix(),
            "captured_utc": timestamp,
            "sha256": hashlib.sha256(png).hexdigest(),
            "width": width,
            "height": height,
            "serial": self.device.get("serial", ""),
            "foreground_package": fg.get("package", ""),
            "foreground_activity": fg.get("activity", ""),
        }
        created: list[Path] = []
        try:
            with image_path.open("xb") as handle:
                handle.write(png)
            created.append(image_path)
            _write_json_atomic(sidecar_path, record)
            created.append(sidecar_path)
            self.frames.append(record)
            self.manifest["session"]["updated_utc"] = timestamp
            _write_json_atomic(self.manifest_path, self.manifest)
        except BaseException:
            # Keep the manifest and frame files consistent even when Ctrl-C
            # lands between the image, sidecar, and atomic manifest writes.
            if self.frames and self.frames[-1] is record:
                self.frames.pop()
            for path in reversed(created):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise
        return record

    def _safe_session_path(self, relative: str) -> Path:
        candidate = (self.session_dir / relative).resolve()
        root = self.session_dir.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise CaptureError(f"Manifest contains an unsafe path: {relative!r}") from exc
        return candidate

    def undo(self) -> dict[str, Any] | None:
        if not self.frames:
            return None
        record = self.frames.pop()
        self.manifest["session"]["updated_utc"] = self.clock()
        _write_json_atomic(self.manifest_path, self.manifest)
        for key in ("image", "sidecar"):
            relative = record.get(key)
            if isinstance(relative, str):
                try:
                    self._safe_session_path(relative).unlink()
                except FileNotFoundError:
                    pass
        return record


class CaptureApp:
    def __init__(
        self,
        adb: AdbClient,
        store: SessionStore,
        settle_seconds: float = 0.3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adb = adb
        self.store = store
        self.settle_seconds = settle_seconds
        self.sleeper = sleeper

    def capture(self, label: str = "") -> dict[str, Any]:
        if self.settle_seconds:
            self.sleeper(self.settle_seconds)
        png = self.adb.capture_png()
        foreground = self.adb.foreground()
        return self.store.add_frame(label, png, foreground)


INTERACTIVE_HELP = """Commands:
  <Enter> or c [label]  capture the current screen
  ordinary text         capture using that text as the label
  s                     show session status
  u                     undo the last frame in this session
  h                     show this help
  q                     save and quit
"""


def interactive_loop(
    app: CaptureApp,
    input_func: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> None:
    output(INTERACTIVE_HELP.rstrip())
    while True:
        try:
            command = input_func("capture> ")
        except (EOFError, KeyboardInterrupt):
            output("\nCapture session closed safely.")
            return
        stripped = command.strip()
        lower = stripped.lower()
        if lower == "q":
            output("Capture session closed safely.")
            return
        if lower == "h":
            output(INTERACTIVE_HELP.rstrip())
            continue
        if lower == "s":
            output(
                f"Session: {app.store.session} | device: {app.adb.serial} | "
                f"frames: {len(app.store.frames)} | next: {app.store.next_index}"
            )
            continue
        if lower == "u":
            undone = app.store.undo()
            output(f"Undid frame {undone['index']}: {undone['label']}" if undone else "Nothing to undo.")
            continue
        if lower == "c":
            label = ""
        elif lower.startswith("c "):
            label = stripped[2:].strip()
        else:
            label = stripped
        record = app.capture(label)
        output(
            f"Captured {record['index']:06d} {record['width']}x{record['height']} "
            f"-> {record['image']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture manually visited Android screens into a resumable offline grounding dataset."
    )
    parser.add_argument("--adb", default="adb", help="ADB executable (default: adb from PATH)")
    parser.add_argument("--serial", help="ADB device serial; required when multiple devices are online")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--session", default=None, help="Safe session directory name")
    parser.add_argument("--settle-seconds", type=float, default=0.3, help="Pause before each capture (default: 0.3)")
    parser.add_argument("--prefix", default="frame", help="Safe filename prefix (default: frame)")
    parser.add_argument(
        "--capture-once",
        nargs="?",
        const="",
        default=None,
        metavar="LABEL",
        help="capture one frame non-interactively, with an optional label",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = subprocess_runner,
    input_func: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    error_output: Callable[[str], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    error_output = error_output or (lambda message: print(message, file=sys.stderr))
    try:
        if args.settle_seconds < 0:
            raise CaptureError("--settle-seconds must be zero or greater.")
        session = validate_session_name(args.session or default_session_name())
        adb = AdbClient(args.adb, runner=runner)
        serial = adb.discover(args.serial)
        store = SessionStore(
            args.output_root,
            session,
            adb.device_metadata(),
            adb_executable=args.adb,
            prefix=args.prefix,
        )
        app = CaptureApp(adb, store, args.settle_seconds, sleeper=sleeper)
        output(f"Using device {serial}; session directory: {store.session_dir}")
        if args.capture_once is not None:
            record = app.capture(args.capture_once)
            output(f"Captured frame {record['index']:06d}: {record['image']}")
            return 0
        interactive_loop(app, input_func=input_func, output=output)
        return 0
    except CaptureError as exc:
        error_output(f"error: {exc}")
        return 2
    except OSError as exc:
        error_output(f"error: filesystem operation failed: {exc}")
        return 2
    except KeyboardInterrupt:
        output("\nCapture session closed safely.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
