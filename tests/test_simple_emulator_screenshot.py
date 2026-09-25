from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "simple_emulator_screenshot.py"
SPEC = importlib.util.spec_from_file_location("simple_emulator_screenshot", MODULE_PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def test_vmware_refresh_cache_and_two_fixed_capture_categories(tmp_path):
    vmx = r"C:\VMs\Ubuntu0\Ubuntu0.vmx"

    def png(width: int, height: int, marker: bytes) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00" + marker
        )

    first = png(100, 200, b"first-crc")
    second = png(300, 400, b"second-crc")
    commands = []

    def runner(argv, timeout):
        commands.append((list(argv), timeout))
        if argv[-1] == "list":
            return SimpleNamespace(returncode=0, stdout=f"Total running VMs: 1\n{vmx}\n".encode(), stderr=b"")
        assert argv[-2:] == ["getGuestIPAddress", vmx]
        return SimpleNamespace(returncode=0, stdout=b"<PRIVATE_HOST>\n", stderr=b"")

    frames = [first, second]
    fetches = []

    def fetcher(url, timeout):
        fetches.append((url, timeout))
        return frames.pop(0), "image/png"

    output = tmp_path / "测试图片"
    client = tool.VMwareClient("vmrun.exe", runner=runner)
    service = tool.ScreenshotService(client, output, fetcher=fetcher)
    with pytest.raises(tool.ScreenshotError, match="先刷新"):
        service.capture("normal")
    with pytest.raises(tool.ScreenshotError, match="normal 或 variant"):
        service.capture("other")

    metadata = service.refresh()
    assert metadata["vmx"] == vmx and metadata["ip"] == "<PRIVATE_HOST>"
    assert metadata["width"] == 100 and metadata["height"] == 200
    assert list(output.rglob("*.png")) == []
    assert service.preview_image() == (first, "image/png")
    assert fetches == [("http://<PRIVATE_HOST>:5000/screenshot", 10.0)]

    normal = service.capture("normal")
    normal_path = Path(normal["path"])
    assert normal_path.parent == output.resolve() / "正常图片"
    assert normal_path.read_bytes() == first
    assert len(fetches) == 1

    service.refresh()
    assert list((output / "变体").glob("*.png")) == []
    variant = service.capture("variant")
    variant_path = Path(variant["path"])
    assert variant_path.parent == output.resolve() / "变体"
    assert variant_path.read_bytes() == second and normal_path.read_bytes() == first
    assert fetches[-1] == ("http://<PRIVATE_HOST>:5000/screenshot", 10.0)
    assert [command[0][3] for command in commands] == ["list", "getGuestIPAddress", "list", "getGuestIPAddress"]
