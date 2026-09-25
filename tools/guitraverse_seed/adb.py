from __future__ import annotations

from dataclasses import asdict
import re
import subprocess
from typing import Callable

from .contracts import DeviceGuardError, DeviceIdentity, SeedManifest


SERIAL_RE = re.compile(r"^emulator-\d{4,5}$")


class AdbClient:
    def __init__(
        self,
        adb_path: str,
        serial: str,
        *,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.adb_path = str(adb_path)
        self.serial = str(serial)
        self.run_command = run_command
        self.history: list[list[str]] = []

    def run(self, *args: str, timeout: float = 30, check: bool = True) -> str:
        argv = [self.adb_path, "-s", self.serial, *map(str, args)]
        self.history.append(argv)
        result = self.run_command(
            argv, capture_output=True, text=True, timeout=timeout)
        output = f"{result.stdout or ''}{result.stderr or ''}"
        if check and result.returncode != 0:
            raise DeviceGuardError(
                f"ADB command failed ({' '.join(args[:3])}): {output.strip()[:300]}")
        return output

    def push(self, local_path, remote_path: str) -> str:
        return self.run("push", str(local_path), remote_path, timeout=120)


def _avd_name(output: str) -> str:
    lines = [line.strip() for line in output.splitlines()
             if line.strip() and line.strip().upper() != "OK"]
    return lines[0] if lines else ""


def preflight_device(manifest: SeedManifest, adb: AdbClient) -> DeviceIdentity:
    if not SERIAL_RE.fullmatch(adb.serial):
        raise DeviceGuardError("seed mutations require a local emulator-<port> serial")
    if adb.run("get-state").strip() != "device":
        raise DeviceGuardError("device is not online")
    actual_avd = _avd_name(adb.run("emu", "avd", "name"))
    if actual_avd != manifest.avd_name:
        raise DeviceGuardError(
            f"AVD mismatch: expected {manifest.avd_name}, got {actual_avd or 'unknown'}")
    booted = adb.run("shell", "getprop", "sys.boot_completed").strip() == "1"
    if not booted:
        raise DeviceGuardError("emulator boot is incomplete")
    locale = adb.run("shell", "getprop", "persist.sys.locale").strip()
    if not locale:
        locale = adb.run("shell", "getprop", "ro.product.locale").strip()
    if locale != manifest.system.locale:
        raise DeviceGuardError(
            f"locale mismatch: expected {manifest.system.locale}, got {locale or 'unknown'}")
    installed: list[str] = []
    for package in manifest.required_packages:
        output = adb.run("shell", "pm", "path", package, check=False)
        if "package:" not in output:
            raise DeviceGuardError(f"required package is missing: {package}")
        installed.append(package)
    return DeviceIdentity(adb.serial, actual_avd, booted, locale, tuple(installed))
