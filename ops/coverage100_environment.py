"""Fresh per-application environment helpers for bounded coverage batches.

The helpers never reuse a running desktop container or emulator process. They
start disposable instances from the seeded image/AVD and return the exact
runtime endpoints to the caller. Call ``cleanup`` in a finally block.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


ANDROID_SDK = Path("/data/shenghonghui/android-sdk")
EMULATOR = ANDROID_SDK / "emulator/emulator"
ADB = ANDROID_SDK / "platform-tools/adb"


def _free_port(*, even: bool = False) -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
            if not even or port % 2 == 0:
                return port
            # Linux may always allocate odd ephemeral ports. Probe the adjacent
            # console port while its odd ADB peer is still held by this socket.
            with socket.socket() as console:
                try:
                    console.bind(("127.0.0.1", port - 1))
                except OSError:
                    continue
                return port - 1


def _wait(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise TimeoutError(description)


@dataclass
class FreshEnvironment:
    kind: str
    control_port: int
    grpc_port: Optional[int] = None
    container: str = ""
    process: Optional[subprocess.Popen] = None
    log_path: Optional[Path] = None
    log_stream: object = None

    def config(self) -> Dict[str, object]:
        result = {"platform": "desktop" if self.kind == "desktop" else "android",
                  "port": self.control_port}
        if self.grpc_port is not None:
            result["grpc"] = self.grpc_port
        if self.container:
            result["container"] = self.container
        return result

    def cleanup(self) -> None:
        if self.kind == "desktop" and self.container:
            if self.log_path is not None:
                with self.log_path.open("a", encoding="utf-8") as stream:
                    subprocess.run(["docker", "logs", "--tail", "200", self.container],
                                   stdout=stream, stderr=subprocess.STDOUT, check=False)
            subprocess.run(["docker", "rm", "-f", self.container],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        if self.kind == "android" and self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        if self.log_stream not in (None, subprocess.DEVNULL):
            self.log_stream.close()


def start_fresh_desktop(*, name: str, qcow: str = "/tmp/System_seeded_v2.qcow2",
                        image: str = "happysixd/osworld-docker", timeout: float = 180,
                        log_path: Optional[Path] = None) -> FreshEnvironment:
    """Start a new seeded desktop container with a new storage volume."""
    if not Path(qcow).is_file():
        raise ValueError(f"Desktop seed is not a regular file: {qcow}")
    control, vnc, vlc, chrome = (_free_port() for _ in range(4))
    command = ["docker", "run", "-d", "--rm", "--name", name,
               "--device", "/dev/kvm", "--cap-add", "NET_ADMIN",
               "-e", "RAM_SIZE=4G", "-e", "CPU_CORES=4", "-e", "DISK_SIZE=32G",
               "--mount", f"type=bind,src={qcow},dst=/System.qcow2,readonly",
               "--mount", "type=volume,dst=/storage",
               "-p", f"127.0.0.1:{control}:5000", "-p", f"127.0.0.1:{vnc}:8006",
               "-p", f"127.0.0.1:{vlc}:8080", "-p", f"127.0.0.1:{chrome}:9222", image]
    if log_path is not None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.with_suffix('.command.json').write_text(json.dumps(command, indent=2))
    launched = subprocess.run(command, capture_output=True, text=True, check=False)
    if log_path is not None:
        log_path.write_text(json.dumps({'returncode': launched.returncode,
            'stdout': launched.stdout, 'stderr': launched.stderr}, indent=2) + '\n')
    launched.check_returncode()
    container = launched.stdout.strip()
    environment = FreshEnvironment("desktop", control, container=container, log_path=log_path)
    try:
        import requests
        def ready():
            try:
                return requests.get(f"http://127.0.0.1:{control}/screenshot", timeout=5).status_code == 200
            except requests.RequestException:
                return False
        _wait(ready, timeout, "fresh desktop controller did not become ready")
    except Exception:
        environment.cleanup()
        raise
    return environment


def start_fresh_android(*, avd: str = "guitraverse_mobile_seed", feature_vulkan: bool = True,
                        timeout: float = 180, log_path: Optional[Path] = None) -> FreshEnvironment:
    """Start a disposable read-only emulator process from the seeded AVD."""
    port = _free_port(even=True)
    grpc = _free_port()
    while grpc in (port, port + 1):
        grpc = _free_port()
    command = [str(EMULATOR), "-avd", avd, "-read-only", "-no-snapshot-save",
               "-no-window", "-no-audio", "-no-boot-anim", "-gpu", "swiftshader_indirect",
               "-port", str(port), "-grpc", str(grpc)]
    if feature_vulkan:
        command.extend(["-feature", "-Vulkan"])
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("w", encoding="utf-8")
    else:
        log_stream = subprocess.DEVNULL
    process = subprocess.Popen(command, stdout=log_stream, stderr=subprocess.STDOUT,
                               start_new_session=True)
    environment = FreshEnvironment("android", port, grpc_port=grpc, process=process,
                                   log_path=log_path, log_stream=log_stream)
    serial = f"emulator-{port}"
    try:
        def ready():
            if process.poll() is not None:
                raise RuntimeError(f"fresh Android emulator exited with code {process.returncode}")
            try:
                result = subprocess.run([str(ADB), "-s", serial, "shell", "getprop", "sys.boot_completed"],
                                        capture_output=True, text=True, check=False, timeout=10)
            except subprocess.TimeoutExpired:
                return False
            return result.stdout.strip() == "1"
        _wait(ready, timeout, f"fresh Android emulator {serial} did not boot")
        subprocess.run([str(ADB), "-s", serial, "shell", "settings", "put", "system", "pointer_location", "0"], check=False)
        subprocess.run([str(ADB), "-s", serial, "shell", "settings", "put", "system", "show_touches", "0"], check=False)
    except Exception:
        environment.cleanup()
        raise
    return environment


__all__ = ["FreshEnvironment", "start_fresh_android", "start_fresh_desktop"]
