#!/usr/bin/env python3
"""Small loopback UI for previewing and saving VMware desktop screenshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import webbrowser


DEFAULT_VMRUN = Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe")
MAX_JSON_BODY = 16_384
CATEGORIES = {"normal": "正常图片", "variant": "变体"}


class ScreenshotError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


Runner = Callable[[Sequence[str], float], Any]
Fetcher = Callable[[str, float], tuple[bytes, str]]


def subprocess_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=timeout, shell=False,
        )
    except FileNotFoundError as exc:
        raise ScreenshotError(f"找不到 vmrun：{argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotError(f"vmrun 超时（{timeout:g} 秒）。") from exc
    except OSError as exc:
        raise ScreenshotError(f"无法运行 vmrun：{exc}") from exc


def http_fetch(url: str, timeout: float) -> tuple[bytes, str]:
    try:
        with urlopen(Request(url, headers={"Accept": "image/png,image/jpeg"}), timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        raise ScreenshotError(f"虚拟机截图接口返回 HTTP {exc.code}。") from exc
    except URLError as exc:
        raise ScreenshotError(f"无法连接虚拟机截图接口：{exc.reason}") from exc
    except TimeoutError as exc:
        raise ScreenshotError(f"连接虚拟机截图接口超时（{timeout:g} 秒）。") from exc
    except OSError as exc:
        raise ScreenshotError(f"读取虚拟机截图失败：{exc}") from exc


def image_info(data: bytes) -> tuple[str, str, int, int]:
    """Return canonical MIME type, extension, width, and height for PNG/JPEG."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
            raise ScreenshotError("截图是损坏的 PNG 文件。")
        width, height = struct.unpack(">II", data[16:24])
        if width <= 0 or height <= 0:
            raise ScreenshotError("PNG 截图尺寸无效。")
        return "image/png", ".png", width, height

    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 4 <= len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            length = struct.unpack(">H", data[index:index + 2])[0]
            if length < 2 or index + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if length < 7:
                    break
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                if width > 0 and height > 0:
                    return "image/jpeg", ".jpg", width, height
                break
            index += length
        raise ScreenshotError("截图是损坏的 JPEG 文件或缺少尺寸信息。")

    raise ScreenshotError("截图接口没有返回 PNG 或 JPEG 图片。")


class VMwareClient:
    def __init__(self, executable: str | Path, runner: Runner = subprocess_runner, timeout: float = 10.0) -> None:
        self.executable = str(executable)
        self.runner = runner
        self.timeout = timeout

    def _run(self, *args: str) -> bytes:
        argv = [self.executable, "-T", "ws", *args]
        result = self.runner(argv, self.timeout)
        if int(getattr(result, "returncode", 1)) != 0:
            stderr = bytes(getattr(result, "stderr", b"") or b"").decode("utf-8", "replace").strip()
            detail = f"：{stderr}" if stderr else ""
            raise ScreenshotError(f"vmrun 命令失败（{' '.join(args)}）{detail}")
        return bytes(getattr(result, "stdout", b"") or b"")

    def running_vms(self) -> list[str]:
        lines = self._run("list").decode("utf-8", "replace").splitlines()
        paths = [line.strip() for line in lines[1:] if line.strip()]
        return paths

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))

    def select_running(self, requested_vmx: str | Path | None = None) -> str:
        running = self.running_vms()
        if requested_vmx is not None:
            requested_key = self._path_key(requested_vmx)
            for vmx in running:
                if self._path_key(vmx) == requested_key:
                    return vmx
            raise ScreenshotError(f"指定的虚拟机未运行：{requested_vmx}")
        if not running:
            raise ScreenshotError("没有检测到正在运行的 VMware 虚拟机。请先启动虚拟机。")
        if len(running) > 1:
            raise ScreenshotError("检测到多个正在运行的 VMware 虚拟机，请用 --vmx 指定一个 .vmx 文件。")
        return running[0]

    def guest_ip(self, vmx: str) -> str:
        value = self._run("getGuestIPAddress", vmx).decode("utf-8", "replace").strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ScreenshotError(f"vmrun 返回的虚拟机 IP 无效：{value or '<empty>'}") from exc


class ScreenshotService:
    """Own the in-memory desktop preview and the two fixed output categories."""

    def __init__(
        self,
        vmware: VMwareClient,
        output_dir: Path,
        requested_vmx: str | Path | None = None,
        fetcher: Fetcher = http_fetch,
        fetch_timeout: float = 10.0,
    ) -> None:
        self.vmware = vmware
        self.requested_vmx = requested_vmx
        self.fetcher = fetcher
        self.fetch_timeout = fetch_timeout
        self.output_dir = Path(output_dir).resolve()
        self.category_dirs = {key: self.output_dir / directory for key, directory in CATEGORIES.items()}
        for directory in self.category_dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._preview: bytes | None = None
        self._content_type = ""
        self._extension = ""
        self._vmx = ""
        self._ip = ""
        self._width = 0
        self._height = 0
        self._version = 0
        self._sequence = 0

    def refresh(self) -> dict[str, Any]:
        """Fetch one desktop preview into memory without creating an output image."""

        with self._lock:
            vmx = self.vmware.select_running(self.requested_vmx)
            ip = self.vmware.guest_ip(vmx)
            host = f"[{ip}]" if ipaddress.ip_address(ip).version == 6 else ip
            data, _reported_type = self.fetcher(f"http://{host}:5000/screenshot", self.fetch_timeout)
            content_type, extension, width, height = image_info(data)
            self._preview = data
            self._content_type = content_type
            self._extension = extension
            self._vmx = vmx
            self._ip = ip
            self._width = width
            self._height = height
            self._version += 1
            return self.preview_metadata()

    def preview_metadata(self) -> dict[str, Any]:
        return {
            "vmx": self._vmx,
            "ip": self._ip,
            "width": self._width,
            "height": self._height,
            "content_type": self._content_type,
            "version": self._version,
            "preview_url": f"/api/preview?v={self._version}",
        }

    def preview_image(self) -> tuple[bytes, str]:
        with self._lock:
            if self._preview is None:
                raise ScreenshotError("请先刷新虚拟机桌面画面。", 409)
            return self._preview, self._content_type

    def _save_atomic_unique(self, directory: Path, data: bytes) -> Path:
        self._sequence += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        fd, temporary_name = tempfile.mkstemp(prefix=".screenshot-", suffix=".tmp", dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            attempt = 0
            while True:
                extra = f"_{attempt}" if attempt else ""
                filename = f"screenshot_{stamp}_{os.getpid()}_{self._sequence:04d}{extra}{self._extension}"
                destination = directory / filename
                try:
                    os.link(temporary, destination)
                    return destination
                except FileExistsError:
                    attempt += 1
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def capture(self, category: Any) -> dict[str, Any]:
        if not isinstance(category, str) or category not in self.category_dirs:
            raise ScreenshotError("category 必须是 normal 或 variant。")
        with self._lock:
            if self._preview is None:
                raise ScreenshotError("请先刷新虚拟机桌面画面，再保存截图。", 409)
            destination = self._save_atomic_unique(self.category_dirs[category], self._preview)
            return {
                "category": category,
                "path": str(destination),
                "relative_path": destination.relative_to(self.output_dir).as_posix(),
                "vmx": self._vmx,
                "ip": self._ip,
                "width": self._width,
                "height": self._height,
            }


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VMware 桌面截图</title>
<style>
:root{color-scheme:dark;font-family:system-ui,"Microsoft YaHei",sans-serif}body{margin:0;background:#101722;color:#eef4ff}
main{width:min(1100px,calc(100% - 32px));margin:28px auto}.bar,.status,.screen{background:#1a2534;border:1px solid #33445a;border-radius:12px}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:14px;padding:14px}button{border:0;border-radius:8px;padding:10px 18px;color:#fff;background:#1687d9;font-size:15px;cursor:pointer}
button:disabled{opacity:.45;cursor:not-allowed}#capture{background:#28a36a}.choice{display:flex;gap:14px;align-items:center}.status{margin:14px 0;padding:12px 14px;min-height:24px;white-space:pre-wrap;overflow-wrap:anywhere}
.status.error{border-color:#a94d56;color:#ffbdc3}.status.ok{border-color:#34855f;color:#baf4d5}.screen{min-height:500px;padding:14px;display:grid;place-items:center}
#preview{display:none;max-width:100%;max-height:76vh;object-fit:contain;border-radius:6px}#empty{color:#9cabc0}
</style></head><body><main>
<h1>VMware 桌面截图</h1>
<div class="bar"><button id="refresh" type="button">刷新桌面画面</button>
<div class="choice" role="radiogroup" aria-label="截图分类"><label><input type="radio" name="category" value="normal" checked> 正常图片</label><label><input type="radio" name="category" value="variant"> 变体</label></div>
<button id="capture" type="button" disabled>保存截图</button></div>
<div id="status" class="status">请先点击“刷新桌面画面”。刷新只显示 VMware 虚拟机桌面，不会保存文件。</div>
<div class="screen"><div id="empty">尚无虚拟机桌面画面</div><img id="preview" alt="当前 VMware 虚拟机桌面"></div>
</main><script>
const refreshButton=document.getElementById('refresh'),captureButton=document.getElementById('capture'),statusBox=document.getElementById('status'),preview=document.getElementById('preview'),empty=document.getElementById('empty');let hasPreview=false;
function setStatus(message,kind=''){statusBox.textContent=message;statusBox.className='status '+kind}
async function api(path,body={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||`HTTP ${response.status}`);return value.result}
async function busy(work){refreshButton.disabled=true;captureButton.disabled=true;try{await work()}catch(error){setStatus(error.message||'操作失败，请查看脚本终端输出。','error')}finally{refreshButton.disabled=false;captureButton.disabled=!hasPreview}}
refreshButton.addEventListener('click',()=>busy(async()=>{setStatus('正在读取 VMware 虚拟机桌面…');const result=await api('/api/refresh');preview.src=result.preview_url+'&t='+Date.now();preview.style.display='block';empty.style.display='none';hasPreview=true;setStatus(`已刷新：${result.width}×${result.height} · ${result.ip}\n${result.vmx}\n尚未保存文件。`,'ok')}));
captureButton.addEventListener('click',()=>busy(async()=>{const category=document.querySelector('input[name="category"]:checked').value;const result=await api('/api/capture',{category});setStatus(`保存成功：${result.path}`,'ok')}));
</script></body></html>
"""


def _loopback_host(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ScreenshotError("--host 必须是 127.0.0.1 或 localhost。") from exc
    if not address.is_loopback or address.version != 4:
        raise ScreenshotError("拒绝绑定到非 IPv4 回环地址。")
    return str(address)


def make_handler(service: ScreenshotService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SimpleVMwareScreenshot/1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, error: Exception) -> None:
            status = error.status if isinstance(error, ScreenshotError) else 500
            message = str(error) if isinstance(error, ScreenshotError) else f"内部错误：{error}"
            self._json(status, {"error": message})

        def _json_body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ScreenshotError("无效的 Content-Length。") from exc
            if length < 0 or length > MAX_JSON_BODY:
                self.close_connection = True
                raise ScreenshotError("JSON 请求过大。", 413)
            if length == 0:
                return {}
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ScreenshotError("请求不是有效 JSON。") from exc
            if not isinstance(value, dict):
                raise ScreenshotError("JSON 请求必须是对象。")
            return value

        def do_GET(self) -> None:
            try:
                path = urlsplit(self.path).path
                if path == "/":
                    self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/preview":
                    body, content_type = service.preview_image()
                    self._send(200, body, content_type)
                else:
                    raise ScreenshotError("页面不存在。", 404)
            except Exception as exc:
                self._error(exc)

        def do_POST(self) -> None:
            try:
                path = urlsplit(self.path).path
                body = self._json_body()
                if path == "/api/refresh":
                    result = service.refresh()
                elif path == "/api/capture":
                    result = service.capture(body.get("category"))
                else:
                    raise ScreenshotError("接口不存在。", 404)
                self._json(200, {"result": result})
            except Exception as exc:
                self._error(exc)

    return Handler


def make_server(service: ScreenshotService, host: str, port: int) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ScreenshotError("--port 必须在 0 到 65535 之间。")
    return ThreadingHTTPServer((_loopback_host(host), port), make_handler(service))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 VMware 桌面虚拟机画面并分类保存截图。")
    parser.add_argument("--vmrun", default=str(DEFAULT_VMRUN), help="vmrun.exe 路径")
    parser.add_argument("--vmx", type=Path, help="指定一个正在运行的 .vmx；仅一个虚拟机运行时可省略")
    parser.add_argument("--output-dir", type=Path, default=Path("测试图片"), help="输出根目录（默认：启动 cwd 下的 ./测试图片）")
    parser.add_argument("--host", default="127.0.0.1", help="仅允许 IPv4 回环地址（默认：127.0.0.1）")
    parser.add_argument("--port", type=int, default=8770, help="本地网页端口（默认：8770）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        service = ScreenshotService(VMwareClient(args.vmrun), args.output_dir, args.vmx)
        server = make_server(service, args.host, args.port)
        url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
        print(f"VMware 桌面截图工具：{url}")
        print(f"保存目录：{service.output_dir}")
        if not args.no_open:
            threading.Timer(0.2, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
        finally:
            server.server_close()
        return 0
    except (ScreenshotError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
